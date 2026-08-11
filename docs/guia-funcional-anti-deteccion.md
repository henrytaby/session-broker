# Guía Funcional y Anti-Detección — Gestión de Sesiones de Navegador

> Documento didáctico que explica **cómo funciona** el sistema, **qué cubre** para evitar
> que Google detecte/banee la cuenta o pida re-verificación, **qué no cubre** (y por qué), y
> **lo que NO debes hacer**. Incluye diagramas, mapas de cobertura y recomendaciones.

---

## Tabla de contenidos

1. [¿Qué problema resuelve? (El "por qué")](#1-qu%C3%A9-problema-resuelve-el-por-qu%C3%A9)
2. [Arquitectura general (el mapa)](#2-arquitectura-general-el-mapa)
3. [El servidor (PC central) — paso a paso](#3-el-servidor-pc-central--paso-a-paso)
4. [El cliente (PC remota) — paso a paso](#4-el-cliente-pc-remota--paso-a-paso)
5. [El chat con Gemini — cómo funciona](#5-el-chat-con-gemini--c%C3%B3mo-funciona)
6. [El enfoque híbrido (por qué solo cookies no bastan)](#6-el-enfoque-h%C3%ADbrido-por-qu%C3%A9-solo-cookies-no-bastan)
7. [Cómo no ser detectado por Google](#7-c%C3%B3mo-no-ser-detectado-por-google)
8. [Cobertura anti-detección (qué cubrimos)](#8-cobertura-anti-detecci%C3%B3n-qu%C3%A9-cubrimos)
9. [Lo que NO cubrimos (y si se puede cubrir)](#9-lo-que-no-cubrimos-y-si-se-puede-cubrir)
10. [Lo que NO debes hacer (reglas operativas)](#10-lo-que-no-debes-hacer-reglas-operativas)
11. [Gestión de riesgos: ban vs challenge](#11-gesti%C3%B3n-de-riesgos-ban-vs-challenge)
12. [Checklist de operación segura](#12-checklist-de-operaci%C3%B3n-segura)

---

## 1. ¿Qué problema resuelve? (El "por qué")

**El problema**: Tienes una cuenta de Google (con sesión activa en tu PC de trabajo) y quieres
usar esa misma sesión en **otras PCs de tu red LAN** (casa, oficina, otros equipos) **sin
compartir tu contraseña** y **sin que Google sospeche** que son dispositivos distintos.

**¿Por qué no es trivial copiar y pegar el perfil de Chrome?**

| Intento ingenuo | Por qué falla |
|---|---|
| Copiar la carpeta del perfil de Chrome a otra PC | Las **cookies están encriptadas con DPAPI** (ligado al usuario de Windows). En otra PC no se pueden desencriptar → sesión muere. |
| Exportar cookies y pegarlas en otra PC | Google guarda tokens OAuth en **IndexedDB + Service Workers**, no solo en cookies. Sin IndexedDB, Google pide re-login. |
| Abrir Gemini en 2 PCs con la misma cuenta simultáneamente | Google puede ver 2 IPs/huellas distintas → riesgo de "verify it's you". |

**La solución** de este sistema:

1. El **servidor** (PC donde se originó la sesión) desencripta las cookies con DPAPI (porque
   es el mismo usuario de Windows) y comprime el perfil **completo** (incluyendo IndexedDB).
2. Los **clientes** descargan ese perfil + cookies + una huella de navegador idéntica.
3. El cliente lanza Chrome local con el perfil completo + cookies inyectadas + huella →
   Google cree que es el **mismo dispositivo** (aunque sea otra PC física).

---

## 2. Arquitectura general (el mapa)

```mermaid
flowchart LR
    subgraph Servidor["🖥️ Servidor (PC central)"]
        Master["Perfil MASTER\n(solo lectura)\nC:\chrome-sessions\master"]
        Crypto["Crypto DPAPI\n+ AES-GCM"]
        Zip["profile.zip\n(51 MB)"]
        FP["fingerprint.json"]
        State["storage_state_live.json\n(cookies desencriptadas)"]
        Chrome1["Chrome headless pc1\n(puerto 19230)"]
        API["API FastAPI\npuerto 8000"]
        Chat["Chat CDP\n(scraping Gemini)"]
        Master --> Crypto --> State
        Master --> Zip
        Master --> FP
        Chrome1 --> Chat
        API --- State & FP & Zip
        Chat --> API
    end
    subgraph Cliente["💻 Cliente (PC remota LAN)"]
        Downloader["httpx\n+ cache 1h"]
        LocalProfile["client/data/chrome_profile_local\n(extraído del zip)"]
        Cookies["cookies inyectadas"]
        Fingerprint["huella aplicada"]
        Browser["Chrome local\n(sesión activa)"]
        Downloader --> LocalProfile & Cookies & Fingerprint
        LocalProfile & Cookies & Fingerprint --> Browser
    end
    API =="HTTP (LAN)"==> Downloader
    Browser =="Navegación directa\na Google/Gemini"==> Google
    Chrome1 =="CDP local 127.0.0.1"==> Chat
```

**Línea de fuego**: el único tráfico que sale a Internet es:
- **Cliente → Google** (Gemini, Mail, etc.) — el navegador real del cliente.
- **pc1 (servidor) → Google** — solo para el chat (scraping headless).

La API del servidor (puerto 8000) **solo** se usa dentro de la LAN para que los clientes
descarguen perfil/cookies/huella. No sale a Internet.

---

## 3. El servidor (PC central) — paso a paso

```mermaid
flowchart TD
    A["python server.py"] --> B["composition root:\ncablea adapters (DI)"]
    B --> C["detectar Chrome real\n+ WebGL renderer (dxdiag)"]
    C --> D["--refresh? → copiar master → pc1\nrobocopy multi-thread"]
    D --> E["desencriptar cookies DPAPI\n→ storage_state_live.json"]
    E --> F["comprimir perfil → profile.zip"]
    F --> G["lanzar pc1 headless\n(puerto 19230)"]
    G --> H["inicializar chat CDP\nconnect_over_cdp"]
    H --> I["iniciar workers async:\n• storage_state_worker (180s)\n• chrome_watchdog (10s)"]
    I --> J["uvicorn FastAPI\npuerto 8000"]
    J --> K{"¿llega request?"}
    K -->|"/health"| L["estado Chrome + API"]
    K -->|"/storage_state"| M["cookies desencriptadas"]
    K -->|"/fingerprint"| N["huella de navegador"]
    K -->|"/profile_zip"| O["perfil completo 51MB"]
    K -->|"/lock /unlock"| P["sistema de turnos"]
    K -->|"WS /ws/gemini"| Q["chat streaming"]
```

### Componentes clave del servidor

| Componente | Archivo | Qué hace |
|---|---|---|
| **Crypto DPAPI** | `app/infrastructure/crypto/dpapi.py` | Lee `Local State`, desencripta la llave maestra con `CryptUnprotectData` (DPAPI del usuario de Windows). Solo funciona en la PC donde se originó la sesión. |
| **AES-GCM** | `app/infrastructure/crypto/aes_gcm.py` | Desencripta cada cookie (v10/v11). Chrome v127+ añade 32 bytes de SHA-256(host) al inicio → se saltan automáticamente. Backend dual: `pycryptodome` → `cryptography`. |
| **Profile zipper** | `app/infrastructure/profile/profile_zipper.py` | Comprime master → `profile.zip` (51 MB), excluyendo Cache/SW storage/basura. — archivo stale (600s) → regenera. |
| **Fingerprint provider** | `app/infrastructure/fingerprint/provider.py` | Detecta versión real de Chrome + WebGL renderer (vía dxdiag) → `fingerprint.json`. |
| **Chrome watchdog** | `app/application/workers/chrome_watchdog.py` | Loop async cada 10s: si pc1 cae → reinicia. |
| **Storage state worker** | `app/application/workers/storage_state_worker.py` | Loop async cada 180s: re-desencripta cookies (captura tokens renovados por Google). Vía `to_thread` (es DPAPI bloqueante). |
| **Chat CDP** | `app/infrastructure/chat/gemini_cdp_session.py` | Se conecta por CDP a pc1, escribe prompts en Gemini, scrapea el HTML de las respuestas. |

### Por qué master nunca se abre con navegador (por diseño)

```mermaid
flowchart LR
    subgraph "REGLA CRÍTICA"
        direction TB
        M["Perfil MASTER<br/>C:\chrome-sessions\master"]
        M -->|"❌ Los scripts Python SOLO LO LEEN"| Read["copiar / desencriptar / comprimir"]
        M -->|"✅ chrome_start_master.bat<br/>(manual, externo)"| Open["abrir con chrome.exe<br/>para loguearse"]
    end
```

Si un script Python abriera master con un navegador, Chrome crearía un **lock file**
(`SingletonLock`) que impediría que el servidor siguiera leyéndolo. Por eso:
- Los scripts **solo leen** los archivos de master (Cookies DB, Local State, perfil).
- `chrome_start_master.bat` es lo **único** que abre master con chrome.exe — y es manual,
  externo al código, solo para cuando necesitas loguearte por primera vez.

---

## 4. El cliente (PC remota) — paso a paso

```mermaid
flowchart TD
    Start["python client.py http://SERVIDOR:8000"] --> Step0{"--no-lock?"}
    Step0 -->|"No"| Lock["[0/4] Solicitar turno\n/lock?client=NOMBRE"]
    Step0 -->|"Sí"| Skip["[0/4] Turnos desactivados"]
    Lock --> LockWait{"¿concedido?"}
    LockWait -->|"No"| Wait["Esperar liberación\n(poll cada 5s)"]
    Wait --> LockWait
    LockWait -->|"Sí"| Step1
    Skip --> Step1
    Step1["[1/4] Descargar fingerprint\n→ Fingerprint(**json)"]
    Step1 --> Step2{"¿perfil en cache < 1h?"}
    Step2 -->|"Sí + !--force"| Cache["Reutilizar Local"]
    Step2 -->|"No / --force"| Download["[2/4] Descargar profile.zip\n(51 MB, httpx)→ extraer"]
    Cache --> Step3
    Download --> Step3
    Step3["[3/4] Descargar cookies desencriptadas\n/storage_state"]
    Step3 --> Recon["reconcile_chrome_version:\najustar UA a Chrome LOCAL"]
    Recon --> Step4["[4/4] launch_persistent_context\n+ add_cookies + add_init_script"]
    Step4 --> Nav["Navegar a Gemini/Mail\n→ sesión activa"]
    Nav --> Close{"¿cerrar ventana?"}
    Close -->|"Sí"| Unlock["/unlock (si no --no-lock)"]
```

### Por qué el cliente reconcilia la versión de Chrome

El servidor genera `fingerprint.json` con **su** versión de Chrome (ej. v151). Pero el cliente
corre un binario de Chrome **local** que puede ser distinto (ej. v130). Si el UA dice "Chrome 151"
pero el binario real es 130, Google puede correlacionar el **JA3 TLS** (que depende del binario)
con el UA y ver inconsistencia → "dispositivo distinto".

```mermaid
flowchart LR
    SrvFP["fingerprint del servidor\nUA: Chrome/151"] --> Recon["reconcile_chrome_version<br/>(detecta Chrome LOCAL)"]
    Local["Chrome local: v130"] --> Recon
    Recon --> Final["UA reescrito: Chrome/130<br/>sec-ch-ua actualizado<br/>TLS coherente con el binario"]
```

Todo lo demás (WebGL, pantalla, timezone, audio) **se mantiene del servidor** para que todas
las PCs se vean como el mismo dispositivo. Solo la versión de Chrome se ajusta al binario local.

---

## 5. El chat con Gemini — cómo funciona

El chat **no abre el perfil master** (evita conflictos de lock). Se conecta por CDP a la
instancia headless `pc1` que el servidor ya tiene corriendo:

```mermaid
sequenceDiagram
    participant U as Usuario (navegador)
    participant WS as FastAPI WebSocket
    participant CS as ChatService
    participant CDP as GeminiCdpSession
    participant G as Gemini (pc1 headless)

    U->>WS: {"prompt": "¿Qué es X?"}
    WS->>CS: send_prompt_and_stream("¿Qué es X?")
    CS->>CS: asyncio.Lock (serializa)
    CS->>CDP: ensure_ready()
    CDP->>G: connect_over_cdp(127.0.0.1:19230)
    CDP->>G: escribir en [role=textbox] + Enter
    WS-->>U: {"type": "thinking"} 🤔
    loop cada 0.3s
        CDP->>G: leer .model-response-text .markdown
        G-->>CDP: HTML de respuesta (creciendo)
        CDP-->>CS: clean HTML (negrillas, listas, imgs)
        CS-->>WS: {"type": "chunk", "html": "..."}
        WS-->>U: render HTML
    end
    CDP-->>CS: estable 2.5s → completo
    CS-->>WS: {"type": "complete"}
    WS-->>U: render markdown final ✅
```

### Por qué el chat usa scraping (y sus limitaciones)

Gemini **no tiene una API pública gratuita** para la sesión web; solo su API de pago (Google AI
Studio / Vertex). Para usar la sesión logueada gratis, el chat hace **scraping del DOM**:

| Lo que se scrapea bien | Lo que se pierde o es frágil |
|---|---|
| Texto con formato (`<p>`, `<b>`, `<ul>`, listas, tablas) | Tarjetas de lugares (`RICH-LIST-CARD`) — se reconstruyen parcialmente |
| Imágenes (`<img>` con `data-full-size-image-uri`) | Mapas interactivos de Google Maps (no replicables) |
| Indicador de "pensando" | "Side panels" de Gemini |
| Multi-turno (detecta el bloque nuevo por turno) | Si Gemini cambia sus custom elements → se rompe (riesgo residual) |

---

## 6. El enfoque híbrido (por qué solo cookies no bastan)

```mermaid
flowchart TB
    subgraph "Enfoque SOLO COOKIES (insuficiente)"
        C1["Cookies desencriptadas"] --> C2["add_cookies()"]
        C2 --> C3["Google pide re-login\nporque faltan tokens OAuth"]
    end
    subgraph "Enfoque HÍBRIDO (este sistema)"
        H1["Perfil completo ZIP\n+ IndexedDB + Service Workers"] --> H2["extraer a local"]
        H3["Cookies desencriptadas"] --> H4["add_cookies() encima del perfil"]
        H2 --> Browser["Chrome local"]
        H4 --> Browser
        H5["Fingerprint idéntica"] --> Browser
        Browser --> Result["✅ Sesión completa\nIndexedDB + SW + cookies = válido"]
    end
```

Google guarda los tokens de sesión en **IndexedDB** dentro del perfil, no en las cookies.
Copiar solo las cookies → Google no encuentra los tokens → pide contraseña. Copiar el perfil
completo (con IndexedDB) + reinyectar las cookies desencriptadas encima = sesión válida.

---

## 7. Cómo no ser detectado por Google

Google identifica dispositivos por una combinación de señales ("fingerprint"). El objetivo es
que **todas las PCs de la LAN parezcan el mismo dispositivo**.

### Las capas del fingerprint

```mermaid
flowchart TB
    subgraph "Lo que Google ve de cada navegador"
        L1["Red"] --> L1a["IP pública\n(JA3/JA4 TLS)"]
        L2["Navegador JS"] --> L2a["navigator.*\nUA, platform, languages\nhardwareConcurrency, deviceMemory\nwebdriver, plugins"]
        L2 --> L2b["WebGL vendor/renderer\n(GPU)"]
        L2 --> L2c["Audio fingerprint\n(AudioContext hash)"]
        L2 --> L2d["Fonts disponibles\n(document.fonts)"]
        L2 --> L2e["Battery API"]
        L2 --> L2f["Canvas fingerprint\n(GPU + driver)"]
        L3["Pantalla"] --> L3a["screen.width/height\ncolorDepth"]
        L4["Geografía"] --> L4a["Timezone, locale, idioma"]
        L5["Sesión"] --> L5a["Tokens OAuth\n(IndexedDB + SW)"]
    end
```

### Qué hace el sistema con cada capa

| Capa | Técnica de spoofing | Coherencia |
|---|---|---|
| **navigator.\*** | `init_script()` reescribe UA, platform, languages, hardwareConcurrency, deviceMemory, plugins, webdriver | ✅ Mismo en todas |
| **WebGL** | Intercepta `getParameter(37445/37446)` → GPU del servidor | ✅ Mismo GPU reportado |
| **Audio** | `OfflineAudioContext.getChannelData` → ruido deterministic; `sampleRate` = 44100 | ✅ Mismo audio hash |
| **Fonts** | `document.fonts.check` → solo set común (Arial, Calibri...) | ✅ Mismo conjunto |
| **Battery** | `navigator.getBattery` → valor fijo (charging=true, level=1) | ✅ Mismo estado |
| **Canvas** | **NO se toca** (rompería imágenes de Gemini) | ⚠️ Depende del hardware |
| **Screen** | Spoofeado a 1920x1080/24bit | ✅ Mismo |
| **Timezone/locale** | Forzado vía Playwright context (America/La_Paz, es-419) | ✅ Mismo |
| **sec-ch-ua** | Dinámico + reconciliado a versión local de Chrome | ✅ Coherente con binario |
| **Tokens OAuth** | Perfil completo copiado (IndexedDB + SW) + cookies reinyectadas | ✅ Válidos |

### El init_script: la "inyección" anti-detección

Cuando el cliente abre Chrome, inyecta un script JS en **cada página** antes de que cargue,
vía `context.add_init_script()`. Este script reescribe propiedades de `navigator`, intercepta
WebGL, AudioContext, fonts, battery, etc. para que todas las PCs reporten los mismos valores.

```mermaid
flowchart LR
    Page["Carga de página\nen Chrome local"] --> Before["Antes de JS de la página:\ninit_script se ejecuta"]
    Before --> Override["navigator.webdriver = undefined\nnavigator.userAgent = UA\nWebGL.getParameter → GPU del servidor\nAudioContext.getChannelData → ruido fijo\ndocument.fonts.check → set común\nnavigator.getBattery → fijo"]
    Override --> Ga["Google lee valores\nconsientes → mismo dispositivo"]
```

---

## 8. Cobertura anti-detección (qué cubrimos)

```mermaid
flowchart TD
    subgraph "✅ Cubierto (riesgo bajo)"
        A1["IP misma LAN/NAT"]
        A2["Tokens OAuth (IndexedDB+SW)"]
        A3["navigator.webdriver"]
        A4["WebGL renderer spoof"]
        A5["Canvas (no tocado, por diseño)"]
        A6["Timezone/Screen/Locale"]
        A7["sec-ch-ua client hints"]
        A8["Audio fingerprint"]
        A9["Font enumeration"]
        A10["Battery API"]
    end
    subgraph "⚠️ Riesgo medio (no cubierto)"
        B1["TLS fingerprint JA3/JA4\ndepende del binario Chrome"]
        B2["Sesiones concurrentes\n(--no-lock)"]
        B3["Headless pc1 detectado\n(exposición del chat)"]
    end
```

### Tabla detallada de cobertura

| Vector | Cubierto | Implementación | Riesgo |
|---|---|---|---|
| **IP pública (misma LAN)** | ✅ | NAT → mismo IP | Bajo |
| **Tokens OAuth** | ✅ | Perfil completo + cookies inyectadas | Bajo |
| **`navigator.webdriver`** | ✅ | Patchright CDP + init_script | Bajo |
| **WebGL renderer** | ✅ | Intercept `getParameter` | Bajo |
| **Canvas fingerprint** | ✅ (no tocado) | Por diseño (preserva Gemini) | Bajo |
| **Timezone/Screen/Locale** | ✅ | Playwright context | Bajo |
| **sec-ch-ua** | ✅ | Dinámico + `reconcile_chrome_version` | Bajo-medio |
| **Audio fingerprint** | ✅ | `AudioContext`/`OfflineAudioContext` valores deterministic | Bajo-medio |
| **Font enumeration** | ✅ | `document.fonts.check` restringido | Bajo |
| **Battery API** | ✅ | `getBattery` valor fijo | Bajo |
| **TLS fingerprint (JA3)** | ❌ | Depende del binario Chrome | **Medio** |
| **Sesiones concurrentes** | ⚠️ | `--no-lock` las permite | **Medio** |
| **Headless pc1** | ⚠️ | Solo CDP local | Medio |

---

## 9. Lo que NO cubrimos (y si se puede cubrir)

### 9.1 TLS fingerprint (JA3/JA4) — NO cubierto

**Qué es**: El handshake TLS inicial que hace Chrome depende de su versión + librería TLS.
Distintas versiones de Chrome → distintos JA3. Google puede loguear JA3 y correlacionar.

**Por qué no se cubre**: El JA3 viene del **binario de Chrome**, no se puede spoofear desde JS.
La única forma de controlarlo es usar la **misma versión de Chrome** en todas las PCs.

**¿Se puede cubrir?** Parcialmente: mantener todas las PCs en la misma major version de Chrome.
`reconcile_chrome_version()` ajusta el **UA** pero no el JA3 real.

```mermaid
flowchart LR
    CV["Versión Chrome LAN"] -->|"misma major"| JA3A["JAEJA3 idéntico\n✅ coherente"]
    CV -->|"distinta major"| JA3B["JA3 distinto\n❌ Google correlaciona\n'dispositivos distintos'"]
```

**Acción**: activar auto-updates de Chrome en todas las PCs; idealmente todas con la misma
versión major que el servidor.

### 9.2 Sesiones concurrentes (mismo IP) — mitigado, no eliminado

**Qué es**: Si 2+ PCs en la misma LAN abren Gemini a la vez con `--no-lock`, Google ve la
misma cuenta activa en "2 navegadores simultáneos" (distintos session tokens).

**¿Es ban?** No. Google permite sesiones concurrentes desde el mismo IP (familia/oficina).
Pero puede aparecer un "verify it's you" ocasional. **No es ban**, es un challenge.

**¿Se puede cubrir?** El sistema de turnos (`/lock`) lo elimina: solo una PC a la vez. Pero si
quieres uso simultáneo, el riesgo es bajo en misma LAN (mismo IP).

```mermaid
flowchart TD
    Sim{"2 PCs abren Gemini\nsimultáneo (misma LAN)"}
    Sim -->|--no-lock| Risk["Riesgo BAJO (mismo IP)\nPuede aparecer challenge\n'Verify it's you'"]
    Sim -->|con lock| Safe["Sin riesgo\n(turno: una a la vez)"]
```

### 9.3 Canvas fingerprint — NO cubierto (por diseño)

**Qué es**: El canvas fingerprint depende de la GPU + driver físicos. PCs con GPUs distintas
→ distinto canvas hash, aunque WebGL renderer esté spoofeado.

**Por qué no se cubre**: Si se spoofea el canvas, **se corrompe la generación de imágenes y
videos de Gemini** (Gemini dibuja en canvas). Por diseño se deja intacto.

**¿Se puede cubrir?** Técnicamente sí (añadir ruido al canvas), pero **rompería Gemini**.
No se cubre deliberadamente.

### 9.4 Headless de pc1 (chat) — NO cubierto

**Qué es**: pc1 corre Chrome `--headless=new` para el chat. Google puede detectar headless
(vía timing, propiedades del renderer, etc.).

**¿Se puede cubrir?** Parcialmente: `CHROME_HEADLESS=false` abre pc1 visible (útil para
depurar). Patchright tiene anti-detección, pero hay riesgo residual de que Gemini bloquee
respuestas en headless.

**Impacto**: solo afecta al chat, no al cliente (que abre Chrome visible).

### 9.5 Headless detection por Gemini — riesgo residual

Gemini podría pedir "verificar que eres humano" en pc1 porque detecta headless. Esto no afecta
a los clientes (que usan Chrome visible), solo al chat.

**Mitigación**: `CHROME_HEADLESS=false` para depurar; Patchright aplica anti-detección CDP.

---

## 10. Lo que NO debes hacer (reglas operativas)

### 🚫 Peligroso (puede causar ban o challenge)

| No hagas | Por qué | Alternativa |
|---|---|---|
| Usar el cliente desde **otra red** (IP pública distinta) **sin lock** | Google ve la misma cuenta desde 2 IPs simultáneas → señal clásica de cuenta comprometida | Siempre usar `--lock` (sin `--no-lock`) si las PCs están en redes distintas |
| Abrir Gemini en **muchas PCs simultáneamente** sin turnos | Igual cuenta, múltiples navegadores activos a la vez → challenge | Si necesitas simultáneo, limitarlo a 2 en misma LAN |
| Dejar versiones de Chrome **distintas** entre servidor y clientes | Mismatch UA vs JA3 → Google correlaciona dispositivos | Mantener todas en la misma major version |
| Compartir el `.env` con el `AUTH_TOKEN` por canales inseguros | El token protege la API de sesión | El token es solo LAN; no exponer fuera |
| Abrir master con Chrome manualmente mientras el servidor corre | Genera lock files que impiden al servidor leer master | Usar `chrome_start_master.bat` **solo** cuando el servidor esté detenido |

### ⚠️ Precaución (puede causar challenge, no ban)

| Ten cuidado | Por qué | Mitigación |
|---|---|---|
| Usar `--no-lock` en LANs con PCs que no controlas | Si alguien abre Gemini en otra LAN con tu perfil, hay 2 IPs | `--no-lock` solo en LAN propia y de confianza |
| Dejar el cliente abierto muchas horas | Las cookies inyectadas se vuelven stale (el perfil IndexedDB sigue válido) | Re-ejecutar `client.py` o usar `--force` |
| Actividad "automatizada" obvia (clicks a velocidad inhumana) | Google detecta bots | El sistema no automatiza; es uso humano normal |
| GPUs muy distintas entre PCs | Canvas fingerprint difiere naturalmente | Aceptar el riesgo residual (bajo) |

### ✅ Buenas prácticas

| Haz | Beneficio |
|---|---|
| `--refresh` al arrancar el servidor si cambiaste la sesión de master | Recopia master a pc1 con datos frescos |
| `--force` en cliente si Google pide login | Re-descarga perfil y cookies frescas |
| Mantener Chrome actualizado en todas las PCs (misma major) | JA3 coherente |
| Usar `--lock` si hay IPs públicas distintas | Evita multicuenta-detect simultáneo |
| Reiniciar el servidor si pc1 cae (watchdog lo hace solo cada 10s) | Chat disponible |

---

## 11. Gestión de riesgos: ban vs challenge

```mermaid
flowchart TD
    Setup["Setup: misma LAN, mismo IP\nfingerprint estable, UA coherente"] --> Eval{"¿Qué puede pasar?"}
    Eval -->|"Caso más probable"| Challenge["📧 Email:\n'Your account was accessed\nfrom a new device'"]
    Eval -->|"Caso posible"| Verify["🔐 Challenge:\n'verify it's you' (SMS)"]
    Eval -->|"Caso muy improbable"| Ban["🚫 Ban/Suspensión"]
    Challenge -->|"Ignorar / no acción"| OK1["Sin consecuencia"]
    Verify -->|"Re-verificar (SMS/App)"| OK2["Sigue funcionando"]
    Ban -->|"Requiere: IPs múltiples simultáneas\n+ huellas inconsistentes\n+ actividad automatizada"| Rare["El setup actual\nEVITA estos triggers"]
```

### La verdad honesta

| Evento | Probabilidad con este setup | Consecuencia |
|---|---|---|
| **Email "nuevo dispositivo"** | Media (al primer uso desde una PC nueva) | Nada. Solo notificación. |
| **Challenge "verifica tu identidad"** | Baja-media (ocasional) | Re-verificar con SMS/app. Sigue funcionando. |
| **Ban/suspensión** | Muy baja | Requeriría 2+ IPs públicas simultáneas + actividad automatizada obvia. El setup evita eso. |

**El setup actual no está diseñado para evadir un ban agresivo de Google** — está diseñado para
**uso compartido legítimo en una LAN familiar/oficina**, donde Google ya permite sesiones
múltiples. El riesgo realista es un "challenge" ocasional, no una suspensión.

---

## 12. Checklist de operación segura

### Antes de empezar (setup inicial)

- [ ] La PC servidor tiene la sesión de Google activa en Chrome (abrir master con `chrome_start_master.bat`, loguearse, **cerrar** el navegador)
- [ ] `pyright install chromium` o Chrome oficial instalado en el servidor
- [ ] Todas las PCs cliente tienen Chrome oficial instalado **con auto-updates activados**
- [ ] `.env` configurado con `AUTH_TOKEN` y `GEMINI_CDP_PORT=19230`

### Al arrancar el servidor

- [ ] `python server.py` (o `--instances 0` para solo API sin chat)
- [ ] Verificar `GET /health` responde (sin token)
- [ ] Verificar `curl "/storage_state?token=TOKEN"` devuelve cookies (con SID/1PSID)
- [ ] Si master cambió: `python server.py --refresh`

### Al usar un cliente

- [ ] `python client.py http://SERVIDOR:8000` (usar `--no-lock` solo si todos están en la misma LAN)
- [ ] Si Google pide login → `--force` + `--refresh` en servidor
- [ ] Si versión de Chrome local difiere del servidor → el sistema reconcilia automáticamente (ver log "Chrome local detectado: vNNN")
- [ ] Si hay challenge "verify it's you" → re-verificar con SMS, luego seguir (no es ban)

### Al terminar

- [ ] Cerrar el navegador del cliente (libera el turno automáticamente si no era `--no-lock`)
- [ ] El servidor puede quedarse corriendo (watchdog mantiene pc1)

### Mantenimiento

- [ ] Periódicamente: abrir master con `chrome_start_master.bat`, verificar que la sesión sigue activa, cerrar
- [ ] Si Google renueva la cuenta (cambio de contraseña) → re-loguear master + `--refresh`
- [ ] Mantener todas las PCs en la misma major version de Chrome (auto-updates)

---

## Resumen visual final

```mermaid
flowchart LR
    subgraph "Lo que PROTEGE"
        P1["Mismo IP (LAN/NAT)"]
        P2["Fingerprint idéntica\n(JS spoof: UA, WebGL,\naudio, fonts, battery)"]
        P3["Perfil completo\n(IndexedDB + SW + cookies)"]
        P4["Turnos (lock)\npara IPs distintas"]
        P5["UA reconciliado\nal Chrome local"]
    end
    subgraph "Lo que NO protege"
        N1["JA3 TLS\n(misma versión Chrome)"]
        N2["Canvas fingerprint\n(no se toca)"]
        N3["Sesiones simultáneas\n(--no-lock)"]
    end
    subgraph "Riesgo real"
        R1["📧 Notificación 'nuevo dispositivo'"]
        R2["🔐 Challenge 'verify it's you'\n(ocasional, no ban)"]
    end
    P1 & P2 & P3 & P4 & P5 -.->|"minimiza"| R1 & R2
    N1 & N2 & N3 -.->|"no elimina pero\nel riesgo es bajo"| R1 & R2
```

> **Conclusión**: El sistema minimiza la detección pasiva de Google manteniendo un fingerprint
> estable y coherente entre todas las PCs. El riesgo realista es un challenge ocasional (no
> ban), mitigado por uso de la misma LAN/dirección IP de salida. Las brechas no cubribles (JA3,
> canvas) son de fingerprinting de red/hardware que Google usa para correlación, no para
> suspensiones automáticas de cuentas de Gemini.
