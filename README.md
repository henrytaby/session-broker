# Gestión de Sesiones de Navegador (Servidor + Clientes + Chat Gemini)

Sistema para **compartir sesiones de Google** (y otros servicios) entre varios PCs de una LAN
**sin compartir contraseñas** y sin que Google detecte que son dispositivos distintos. Se
basa en **Clean Architecture** (FastAPI + routers + DI), desencripta las cookies de Chrome con
DPAPI de Windows y reinyecta el perfil completo + huella de navegador en cada cliente.

Además integra un **chat con Gemini** que se conecta por CDP a una instancia Chrome headless
levantada por el propio servidor.

## Arquitectura

```
PC central (servidor)                       PCs remotos (clientes, LAN)
  - master: perfil ORIGINAL (solo lectura)   - Descarga fingerprint + profile.zip + cookies
  - pc1, pc2...: copias headless              - Abre Chrome local con sesion activa
  - FastAPI (puerto 8000)                     - Huella anti-deteccion inyectada (JS init_script)
  - Chat Gemini via CDP local a pc1
```

Ver `AGENTS.md` para el detalle completo de estructura de paquetes, puertos, flujo de datos y
auditoría anti-detección.

## Requisitos

- **Python 3.10+** (probado con 3.10.0)
- **Windows 10/11** (DPAPI es específico de Windows)
- **Chrome oficial** instalado (detectado automáticamente; no se usa Chromium de Playwright)

## Configuración

```powershell
.\venv\Scripts\activate         # entorno virtual (obligatorio)
pip install -r requirements.txt
patchright install chromium    # solo si no hay Chrome oficial
copy .env.example .env          # y edita valores (AUTH_TOKEN, SESSIONS_DIR, etc.)
```

## Uso

### Servidor (PC central, donde está la sesión master)

```powershell
python server.py                       # 1 instancia Chrome headless + chat
python server.py --instances 0         # solo API HTTP, sin Chrome ni chat
python server.py --instances 2         # 2 instancias Chrome headless
python server.py --refresh             # recopia perfil master a instancias
```

### Clientes (PCs remotas en la LAN)

```powershell
python client.py http://192.168.68.61:8000               # con turnos (IPs distintas)
python client.py http://192.168.68.61:8000 --no-lock      # misma LAN, sin turnos
python client.py http://192.168.68.61:8000 --force        # forzar descarga de perfil
python client.py http://192.168.68.61:8000 --no-lock https://mail.google.com/  # URL custom
```

Los datos locales del cliente (perfil cache, cookies, descargas) se guardan en
`client/data/` (no se suben al repositorio; ver `.gitignore`).

### Chat (frontend web)

Abrir el navegador en `http://<servidor>:8000/` — WebSocket `/ws/gemini`.

### Tooling (shims preservados)

```powershell
python decrypt_profile.py --profile C:\chrome-sessions\master --out storage_state.json
python fingerprint_cloner.py --out fingerprint.json
```

### Scripts de operación del perfil master

`scripts/chrome_start_master.bat` abre Chrome con el perfil master
(lo único que abre master con un navegador real; los scripts Python solo lo leen).
`scripts/cerrar_master.bat` cierra los procesos Chrome del perfil master.

## Endpoints de la API (puerto 8000)

| Endpoint | Token | Descripción |
|----------|-------|-------------|
| `GET /` | No | Frontend de chat (HTML + WS) |
| `GET /health` | No | Estado de instancias Chrome + API |
| `GET /storage_state` | Sí | Cookies desencriptadas (formato Playwright) |
| `GET /fingerprint` | Sí | Huella de navegador (UA, TZ, WebGL, screen) |
| `GET /profile_zip` | Sí | Perfil completo comprimido (con IndexedDB) |
| `GET /lock?client=NOMBRE` | Sí | Solicitar turno |
| `GET /unlock?client=NOMBRE` | Sí | Liberar turno |
| `WS /ws/gemini` | No | Chat streaming Gemini |

El token se envía como `?token=...` (cabecera `Authorization: Bearer ...`).
Comparación con `secrets.compare_digest` (constante en tiempo).

## Calidad

```powershell
ruff check .
pytest -q
```

## Documentación

- `AGENTS.md` — descripción técnica completa, flujo de datos, auditoría anti-detección,
  troubleshooting y datos de configuración (`.env`).
- `docs/guia-funcional-anti-deteccion.md` — guía funcional del spoofing de huella.
