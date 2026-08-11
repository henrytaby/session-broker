# AGENTS.md — Gestión de Sesiones de Navegador (Servidor + Clientes + Chat Gemini)

## Descripción del proyecto

Sistema para compartir sesiones de Google (y otros servicios) entre múltiples PCs en una LAN
sin compartir contraseñas, y sin que Google detecte que son dispositivos diferentes.

**Arquitectura**: Clean Architecture (hexagonal) — Servidor central (PC de trabajo, FastAPI) +
clientes remotos (PCs en la red LAN). Además integra un **chat con Gemini** que se conecta por
CDP a la instancia headless `pc1` levantada por el propio servidor.

El servidor desencripta las cookies de Chrome/Brave usando DPAPI de Windows, comprime el
perfil completo (con IndexedDB + Service Workers), y expone todo vía API HTTP. Los clientes
descargan el perfil + cookies + huella de navegador, y abren Chrome local con sesión activa.
El chat reutiliza la instancia headless `pc1` (no abre el perfil master, evita conflictos de lock).

## Configuración del entorno

```powershell
# Entorno virtual (obligatorio)
.\venv\Scripts\activate

# Instalar dependencias
pip install -r requirements.txt
patchright install chromium   # solo si no hay Chrome oficial
```

**Python**: 3.10+ (probado con 3.10.0)
**SO**: Windows 10/11 (DPAPI es específico de Windows)
**Navegador**: Chrome oficial instalado (detectado automáticamente, no Chromium de Playwright)

## Estructura de paquetes (Clean Architecture)

```
C:\00gemini\
  server.py                    # wrapper -> python -m app.main
  client.py                    # wrapper -> python -m client.main
  decrypt_profile.py           # shim -> app.infrastructure.crypto.cli
  fingerprint_cloner.py        # shim -> app.infrastructure.fingerprint.cli (reexporta API v9)
  .env.example / .env          # config (pydantic-settings)
  pyproject.toml               # pytest + ruff
  requirements.txt
  app/
    main.py                    # uvicorn entry (servidor) + CLI (--instances, --refresh)
    core/        config.py, logging.py        # Settings (.env) + logging stdlib
    domain/      models.py, exceptions.py, ports/*  # interfaces + modelos pydantic
    application/ services/ (session, lock, chat) + workers/ (storage_state, chrome_watchdog)
    infrastructure/
      crypto/     dpapi.py, aes_gcm.py, chrome_cookies.py, storage_state_assembler.py, cli.py
      fingerprint/ fingerprint.py, chrome_finder.py, provider.py, cli.py
      profile/    profile_zipper.py, profile_store.py, chrome_finder.py, chrome_process.py
      lock/       in_memory_lock.py
      chat/       gemini_cdp_session.py   # IAISession via connect_over_cdp
      api/        server.py (factory+lifeespan), deps.py, auth.py, routers/{session,chat}.py
    composition/ root.py       # DI: cablea adapters concretos -> app.state
  client/
    main.py, http_client.py (httpx+reintentos), profile_cache.py, browser_launcher.py
  static/ index.html          # frontend chat (WS /ws/gemini)
  tests/                      # crypto, fingerprint, lock, routers (pytest)
```

## Comandos

```powershell
# Verificar que todo compila
python -c "import app.main; import client.main; print('OK')"

# Lint + tests
ruff check .
pytest -q

# --- SERVIDOR (PC central, donde está la sesión) ---
python server.py                       # = python -m app.main (1 instancia Chrome headless + chat)
python server.py --instances 0         # solo API HTTP, sin Chrome headless ni chat
python server.py --instances 2         # 2 instancias Chrome headless
python server.py --refresh             # recopiar perfil master a instancias

# --- CLIENTES (PCs remotas en la LAN) ---
python client.py http://192.168.68.61:8000               # con turnos (IPs distintas)
python client.py http://192.168.68.61:8000 --no-lock      # misma red, sin turnos
python client.py http://192.168.68.61:8000 --force         # forzar descarga de perfil
python client.py http://192.168.68.61:8000 --no-lock https://mail.google.com/  # URL custom

# --- CHAT (frontend web) ---
#  Abrir navegador a http://<servidor>:8000/  (WebSocket /ws/gemini)

# --- DESCIFRADO DPAPI (tooling, shim preservado) ---
python decrypt_profile.py --profile C:\chrome-sessions\master --out storage_state.json
python decrypt_profile.py                       # rutas por defecto

# --- HUELLA DIGITAL (tooling, shim preservado) ---
python fingerprint_cloner.py --out fingerprint.json
```

## Endpoints de la API HTTP (servidor, puerto 8000)

| Endpoint | Token | Descripción |
|----------|-------|-------------|
| `GET /` | No | Frontend de chat (HTML + WS) |
| `GET /health` | No | Estado de instancias Chrome + API |
| `GET /storage_state` | Sí | Cookies desencriptadas (formato Playwright) |
| `GET /fingerprint` | Sí | Huella de navegador (UA, TZ, WebGL, screen) |
| `GET /profile_zip` | Sí | Perfil completo comprimido (con IndexedDB) |
| `GET /lock?client=NOMBRE` | Sí | Solicitar turno (evita uso simultáneo) |
| `GET /unlock?client=NOMBRE` | Sí | Liberar turno |
| `WS /ws/gemini` | No | Chat streaming: recibe `{prompt}`, envía `{type:chunk/complete/error}` |

El token se envía como `?token=gemini2024` (definido en `AUTH_TOKEN` / `.env`) o cabecera
`Authorization: Bearer gemini2024`. Se compara con `secrets.compare_digest` (constante en tiempo).

## Configuración (.env)

Ver `.env.example`. Campos clave:

| Campo | Default | Descripción |
|-------|---------|-------------|
| `SESSIONS_DIR` | `C:\chrome-sessions` | Raíz de perfiles |
| `MASTER_PROFILE_NAME` | `master` | Perfil ORIGINAL (solo lectura) |
| `API_HOST`/`API_PORT` | `0.0.0.0`/`8000` | Bind de la API |
| `AUTH_TOKEN` | `gemini2024` | Token de API |
| `CHROME_INSTANCES` | `1` | N° instancias headless (0 = solo API) |
| `CHROME_HEADLESS` | `true` | `false` para depuración visible |
| `GEMINI_CDP_PORT` | `19230` | Puerto CDP real de pc1 (NO el proxy viejo 9221) |
| `STORAGE_STATE_REFRESH_SEC` | `180` | Re-desencriptar cookies cada N seg |
| `SESSION_LOCK_TIMEOUT_SEC` | `600` | Timeout del turno |
| `PROFILE_ZIP_CACHE_HOURS` | `1` | Cache del perfil en cliente |
| `LOG_LEVEL` | `INFO` | Nivel de logging |

**Nota de puertos**: El proxy CDP público de v8/v9 fue **eliminado**. Solo el puerto 8000
abre firewall. El chat se conecta por CDP local (`127.0.0.1:GEMINI_CDP_PORT`). La fórmula de
puertos Chrome debug es `19220 + i*10` (pc1 → 19230, pc2 → 19240, ...).

## Flujo de datos (cómo funciona)

### Servidor (PC central)

```
1. create_app() -> lifespan: composition root cablea adapters; inicia storage_state_worker
   y chrome_watchdog; inicializa IAISession (connect_over_cdp a pc1).
2. master se lee (nunca se abre con navegador): crypto desencripta cookies -> StorageState
   (memoria + storage_state_live.json); profile_zipper genera profile.zip.
3. API FastAPI: /storage_state, /fingerprint, /profile_zip, /lock, /unlock, /health (sin token).
4. Chat: WS /ws/gemini -> chat_service.send_prompt_and_stream -> gemini_cdp_session
   (CDP a pc1 headless) -> stream de chunks al WS. Frontend en GET /.
5. Watchdog reinicia pc1 si cae; chat_service reconecta en el siguiente prompt.
```

### Cliente (PC remota)

```
1. [0/4] Solicita turno al servidor (/lock) — opcional con --no-lock
2. [1/4] Descarga fingerprint del servidor -> Fingerprint(**json)
3. [2/4] Descarga profile.zip (~20MB) -> extrae a client/data/chrome_profile_local\ (cache 1h, --force bypass)
4. [3/4] Descarga storage_state (cookies desencriptadas)
5. [4/4] launch_persistent_context(user_data_dir=chrome_profile_local) -> Chrome con IndexedDB + SW
         -> add_cookies(cookies desencriptadas) -> inyecta por encima de las que Chrome no pudo leer
         -> add_init_script(fingerprint) -> anti-detección JS en cada página
         -> navega a Gemini/Mail/etc -> sesión activa
6. Al cerrar el navegador -> libera turno (/unlock) — opcional
```

## Anti-detección (app/infrastructure/fingerprint/fingerprint.py)

Por qué Google NO detecta que es otro dispositivo:

| Técnica | Implementación |
|---------|----------------|
| `navigator.webdriver` | Eliminado por Patchright (CDP) + init_script JS |
| `--enable-automation` | Filtrado con `ignore_default_args` |
| User-Agent | Detecta versión real de Chrome (v151) -> UA coherente |
| sec-ch-ua client hints | Versión dinámica en `extra_http_headers` + `userAgentData` |
| UA local del cliente | `reconcile_chrome_version()` reescribe UA+sec-ch-ua a la versión **local** del binario Chrome del cliente (evita mismatch UA/TLS-JA3 vs fingerprint del servidor) |
| `navigator.platform` | Forzado a "Win32" |
| `navigator.plugins` | Array con 5 plugins PDF realistas |
| `window.chrome` | Repoblado: `.runtime`, `.app`, `.csi`, `.loadTimes` |
| WebGL vendor/renderer | Interceptado `getParameter(37445/37446)` -> GPU del servidor |
| `navigator.permissions` | Parcheado para coherencia con Notification API |
| Screen (width/height/colorDepth) | Spoofeado a 1920x1080/24bit |
| Timezone / locale | Forzado vía Playwright context (America/La_Paz, es-419) |
| Lenguaje | es-419 via context option + `--lang=es-419` flag |
| Audio fingerprint | `AudioContext`/`OfflineAudioContext`/`AnalyserNode` spoofeados con valores deterministicos (getChannelData, sampleRate=44100, frequencyData) -> mismo hash en todas las PCs |
| Font enumeration | `document.fonts.check` limitado a set comun de fuentes (Arial, Calibri...) para evitar enumerar las instaladas localmente |
| Battery API | `navigator.getBattery` spoofeado a valor fijo consistente (charging=true, level=1) |
| Canvas fingerprint | **NO se toca** (rompería generación de imágenes/videos de Gemini) |

### Flags de Chrome CLI (build_chromium_args)

Solo se pasan flags que Chrome v150+ acepta sin warnings:
- `--no-first-run`, `--no-default-browser-check`, `--start-maximized`
- `--disable-background-*` (throttling, networking, timer)
- `--disable-sync`, `--disable-component-update`, `--disable-default-apps`
- `--password-store=basic`, `--use-mock-keychain`, `--lang=es-419`

**NO se usan** (causan warnings en Chrome v151 / Patchright los maneja):
- `--disable-blink-features=AutomationControlled` (Patchright lo maneja internamente)
- `--disable-infobars` (deprecated)
- `--no-sandbox` (security warning)

## Seguridad

- **DPAPI**: Las cookies de Chrome en Windows están encriptadas con DPAPI (ligado al usuario de
  Windows). `app/infrastructure/crypto/dpapi.py` las desencripta con `win32crypt.CryptUnprotectData`.
- **AES-GCM**: Chrome v127+ usa AES-256-GCM con la llave maestra DPAPI. Nonce de 12 bytes.
  Backend dual: prefiere `pycryptodome`, falla a `cryptography` (`aes_gcm.py`).
- **Hash de dominio**: Chrome v127+ inserta 32 bytes de SHA-256(host_key) al inicio del plaintext.
  `aes_gcm.decrypt_value` detecta y salta esos 32 bytes automáticamente.
- **Token de API**: `AUTH_TOKEN` en `.env` (default `gemini2024`). Comparación con
  `secrets.compare_digest`. Nunca se loguea el token.
- **expires_utc**: Conversión FILETIME -> Unix: `(expires_utc - 11644473600000000) // 1000000`.

## Limitaciones conocidas

1. **IP pública**: Si las PCs están en redes distintas (no misma LAN), Google ve 2 IPs -> riesgo
   de ban. Usar sistema de turnos (sin `--no-lock`) para IPs distintas.

2. **Expiración de tokens**: Google renueva los tokens cada horas. El servidor re-desencripta
   cada `STORAGE_STATE_REFRESH_SEC` (180s). Si el servidor está apagado, los tokens del cliente
   expiran eventualmente.

3. **WebGL físico**: El renderer está spoofeado (no es la GPU real del cliente). Riesgo residual
   de mismatch si Google mide timing de shaders (muy poco probable para Gemini).

4. **DPAPI local**: Las cookies inyectadas vía `add_cookies()` están en texto plano en memoria
   del navegador. No se guardan en SQLite local. Re-ejecutar `client.py` para persistencia.

5. **Concurrencia en la misma LAN**: Segura (misma IP pública vía NAT). `--no-lock` recomendado.

6. **Chat / selectores DOM de Gemini**: `gemini_cdp_session` aísla selectores en constantes
   (`[role="textbox"]` input, `model-response, [data-message-id]` output). Si Gemini cambia el
   DOM, el scraping se rompe. Riesgo residual.

7. **Headless detectado por Gemini**: patchright anti-detección; `CHROME_HEADLESS=false` para
   depuración. Riesgo residual.

8. **Prompts concurrentes en pc1**: `chat_service` serializa con `asyncio.Lock` (un prompt a la vez).

## Auditoría anti-detección (cobertura y riesgos residuales)

| Vector | Cubierto | Riesgo | Nota |
|--------|----------|--------|------|
| IP pública (misma LAN/NAT) | ✅ | Bajo | Todas ven mismo IP; lock mitiga IPs distintas |
| Tokens OAuth (IndexedDB+SW) | ✅ | Bajo | Perfil completo copiado; cookies re-inyectadas |
| `navigator.webdriver` | ✅ | Bajo | Patchright + init_script |
| WebGL renderer spoof | ✅ (design) | Bajo | Mismo renderer en todas; coherente |
| Canvas fingerprint | ✅ (no tocado) | Bajo | Por diseño (preserva imágenes de Gemini) |
| Timezone/Screen/Locale | ✅ | Bajo | |
| sec-ch-ua client hints | ✅ | Bajo-medio | `reconcile_chrome_version` ajusta a versión local |
| Audio fingerprint | ✅ | Bajo-medio | `AudioContext`/`OfflineAudioContext` valores deterministicos |
| Font enumeration | ✅ | Bajo | `document.fonts.check` restringido a set comun |
| Battery API | ✅ | Bajo | valor fijo consistent |
| **TLS fingerprint (JA3/JA4)** | ❌ | **Medio** | Depende de version de Chrome; ver recomendación abajo |
| **Sesiones concurrentes** | ⚠️ | **Medio** | `--no-lock` permite abrir Gemini a la vez; riesgo bajo mismo IP |
| Headless pc1 (chat) | ⚠️ | Medio | Solo CDP local; `CHROME_HEADLESS=false` para depurar |

### Recomendaciones anti-detección (operativas)

1. **Mantener todas las PCs de la LAN en la misma version de Chrome** que el servidor.
   El TLS fingerprint (JA3/JA4) depende de la version de Chrome + librería TLS. Versiones
   distintas -> distintos JA3 -> Google correlaciona "misma cuenta, distintos dispositivos
   de red". `reconcile_chrome_version()` ajusta el UA, pero el JA3 del handshake TLS viene del
   binario y no se puede spoofear. **Acción**: auto-updates activados; idealmente la misma
   version major en toda la LAN.

2. **`--no-lock` solo en la misma LAN**. Si 2+ PCs en la misma LAN abren Gemini
   simultaneamente, Google ve mismo IP -> riesgo bajo de ban, pero puede aparecer un
   challenge "verify it's you" ocasional (no es ban). En redes distintas (IPs publicas
   distintas), SIEMPRE usar el sistema de turnos (sin `--no-lock`).

3. **Riesgo realista = challenge, no ban**. Lo mas probable es que Google envie un email
   "Your account was accessed from a new device" o pida re-verificar (SMS). No es una
   suspension. Un ban real requeriria: IPs multiples simultaneas + huellas inconsistentes +
   actividad automatizada detectable. El setup actual (misma IP, UA coherente, fingerprint
   estable) evita esos triggers.

4. **PCs con GPUs fisicas distintas**: el canvas fingerprint difiere naturalmente aunque el
   renderer WebGL esté spoofeado. Google podria ver "mismo renderer reportado, distinto
   canvas hash". Riesgo residual bajo (no se toca canvas por diseño — romperia la generacion
   de imagenes de Gemini).

5. **Audio/Battery/Fonts spoofing**: ahora cubiertos en `init_script()` para que todas las PCs
   reporten los mismos valores (mismo audio hash, mismo battery state, mismas fuentes
   "disponibles"). Reduce la correlacion pasiva de deviceID.

## Troubleshooting

| Síntoma | Causa | Solución |
|---------|-------|----------|
| Google pide contraseña | Perfil sin IndexedDB / cookies expiradas | `--force` en cliente + `--refresh` en servidor |
| Chrome no abre | `ignore_default_args=True` muy agresivo | Solo filtrar flags específicos |
| Warning "unsupported flag" | Flag deprecated en Chrome v150+ | Remover de `build_chromium_args` |
| `TargetClosedError` | Chrome se cierra al arrancar | Verificar que `ignore_default_args` no es `True` |
| TikTok/otros no funcionan | No hay sesión en el perfil master | Abrir Chrome master, loguearse, reiniciar servidor |
| Navegador chiquito | viewport fijado | Usar `no_viewport=True` + `--start-maximized` |
| Descarga abre 10 ventanas | `os.startfile` en cada descarga | Debounce de 10s en `_last_opened` |
| Chat 503 / "no disponible" | `--instances 0` o pc1 caída | Usar `--instances 1`+; watchdog reinicia pc1 |
| `GEMINI_CDP_PORT` wrong | Se usó el proxy viejo 9221 | Debe ser 19230 (puerto Chrome debug real de pc1) |

## Archivos de datos

```
C:\chrome-sessions\master\              — Perfil ORIGINAL de Chrome (NO se modifica, solo se lee)
C:\chrome-sessions\pc1\                 — Copia del master (usa el Chrome headless del servidor)
C:\chrome-sessions\storage_state_live.json  — Cookies desencriptadas (regeneradas cada 3 min)
C:\chrome-sessions\profile.zip          — Perfil comprimido para clientes (~20MB; solo login-critico)
C:\chrome-sessions\fingerprint.json     — Huella de navegador serializada

C:\00gemini\client\data\chrome_profile_local\  — Perfil local del cliente (cacé, < 1h)
C:\00gemini\client\data\storage_state_local.json — Cookies locales del cliente
C:\00gemini\client\data\Descargas_Bot\        — Carpeta de descargas del cliente (se abre auto)
```

`scripts/chrome_start_master.bat` abre master directamente vía `chrome.exe --user-data-dir=...` — es lo
ÚNICO que abre master con un navegador real, y es manual/externo al código Python. Los scripts
Python nunca abren master con navegador (solo leen sus archivos). Esto es por diseño.

## Versiones

- **v9 clean arch** (actual): Clean Architecture (FastAPI + routers + DI + workers async + chat CDP).
  Proxy CDP público eliminado; chat vía CDP local a pc1.

### Cambios recientes (anti-detección)

- **Audio fingerprint spoofing**: `init_script()` ahora intercepta `AudioContext`,
  `OfflineAudioContext` (getChannelData → ruido deterministic), `AnalyserNode`
  (getFloatFrequencyData → valor fijo) y `sampleRate` (44100). Todas las PCs reportan el
  mismo audio hash.
- **Font enumeration spoofing**: `document.fonts.check` restringido a un set comun de fuentes
  (Arial, Calibri, Segoe UI...) para que las PCs no enumeren las instaladas localmente.
- **Battery API spoofing**: `navigator.getBattery` → valor fijo (charging=true, level=1).
- **Reconciliación de Chrome del cliente**: `reconcile_chrome_version(fp, local_cv)` en
  `client/main.py` reescribe `user_agent` + `sec_ch_ua` a la version mayor del Chrome local
  (detectada vía powershell) para evitar mismatch UA/TLS entre fingerprint del servidor y
  binario del cliente.
- **Chat streaming mejorado**: el scraper extrae HTML del `.markdown` interno de Gemini
  (preserva negrillas, listas, imágenes) en lugar de `inner_text()` plano; selector
  `.model-response-text .markdown`; conversión de títulos `<p><b>` → `<h3>` en el frontend;
  indicador "pensando" animado; normalización de `<single-image>` → `<img src>`.
- **AGENTS.md**: sección de auditoría anti-detección + recomendaciones operativas (JA3,
  sesiones concurrentes, mismo Chrome version).

### Cambios recientes (perfil.zip + cliente)

- **Fix bug `rmtree` en `profile_cache.download_and_extract`**: el zip se descargaba
  *dentro* de `chrome_profile_local/` y luego `shutil.rmtree(self._dir)` lo borraba antes
  de extraerlo (`FileNotFoundError` en `zipfile.ZipFile`). Ahora se descarga a un sibling
  `client/data/profile_download.zip` (fuera del dir del profile), se extrae con manejo de
  `BadZipFile`, y se limpia al final. La carpeta destino se crea siempre con `mkdir(parents=True)`.
- **Fix bug silencioso en `SKIP_DIRS` (profile_zipper)**: estaba escrito como
  `"Service Worker\CacheStorage"` (rel-path anidado) pero `os.walk` entrega nombres de
  dir **simples** (`"CacheStorage"`), así que nunca matcheaba y el zip llevaba ~538MB de
  CacheStorage. Reescrito para matchear por **nombre simple de un segmento**. El zip pasó
  de 301.88 MB → 19.88 MB (−93%).
- **Optimización del profile.zip**: `SKIP_DIRS` ahora también excluye modelos ML de Chrome
  (`optimization_guide_model_store` 44MB, `OnDeviceHeadSuggestModel` 7.5MB), `Safe Browsing`
  (20MB), `component_crx_cache` (13.7MB), `ShaderCache`/`GrShaderCache` (7MB),
  `Crashpad`/`BrowserMetrics`/`*.pma` (telemetría), `File System` (19MB PWA), `Sessions`
  (se regenera), `DawnWebGPUCache`/`DawnGraphiteCache` (caches de WebGPU). Se conserva todo
  lo **critico para login**: `IndexedDB` (tokens OAuth), `Service Worker/ScriptCache`
  (sin CacheStorage), `Network/` (cookies), `Local Storage`, `Login Data`, `Preferences`,
  `Web Data`, `Account Web Data`, `History`, `Extensions`, `Web Applications`.
- **Compression**: `compresslevel=1 → 6` (mejor ratio, build < 2s).
- **`.gitkeep` en `chrome_profile_local/` y `Descargas_Bot/`** + `.gitignore` ajustado
  (`carpeta/*` + `!carpeta/.gitkeep`) para que la estructura se preserve al clonar el repo
  sin subir el contenido (evita el `FileNotFoundError` en clones frescos).
