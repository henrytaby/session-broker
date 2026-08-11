from __future__ import annotations

import json
import re

from app.domain.models import Fingerprint
from app.infrastructure.fingerprint.chrome_finder import (
    detect_chrome_version,
    detect_webgl_renderer,
)


def default_fingerprint(chrome_version: int | None = None) -> Fingerprint:
    """Build a default fingerprint, auto-detecting the Chrome version."""
    if chrome_version is None:
        chrome_version = detect_chrome_version()
    cv = chrome_version
    return Fingerprint(
        user_agent=(
            f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            f"(KHTML, like Gecko) Chrome/{cv}.0.0.0 Safari/537.36"
        ),
        platform="Win32",
        languages=["es-419", "es", "en"],
        timezone="America/La_Paz",
        locale="es-419",
        screen_width=1920,
        screen_height=1080,
        color_depth=24,
        hardware_concurrency=8,
        device_memory=8,
        webgl_vendor="Google Inc. (NVIDIA)",
        webgl_renderer=(
            "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)"
        ),
        sec_ch_ua=f'"Chromium";v="{cv}", "Not)A;Brand";v="24", "Google Chrome";v="{cv}"',
    )


def reconcile_chrome_version(fp: Fingerprint, local_chrome_version: int | None = None) -> Fingerprint:
    """Adjust a server-provided fingerprint to the LOCAL Chrome major version.

    The server generates the fingerprint with its own Chrome version, but the
    client runs a (possibly different) local Chrome binary. If the UA / sec-ch-ua
    client hints report a version that doesn't match the local binary, Google can
    correlate the mismatch (JA3 TLS fingerprint + UA inconsistency) as "different
    device". This rewrites user_agent + sec_ch_ua to match the local Chrome so the
    network-level fingerprint (TLS, UA) stays coherent with the binary actually
    making the requests.

    Everything else (WebGL, screen, timezone, audio) is kept from the server's
    fingerprint to keep all clients looking like the SAME device — only the Chrome
    version is reconciled to the local binary to avoid UA/TLS mismatches.
    """
    if local_chrome_version is None:
        local_chrome_version = detect_chrome_version()
    cv = local_chrome_version
    m = re.search(r"Chrome/(\d+)", fp.user_agent)
    if m and int(m.group(1)) == cv:
        return fp  # already coherent
    fp.user_agent = (
        f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) Chrome/{cv}.0.0.0 Safari/537.36"
    )
    fp.sec_ch_ua = f'"Chromium";v="{cv}", "Not)A;Brand";v="24", "Google Chrome";v="{cv}"'
    return fp


def build_chromium_args(fp: Fingerprint) -> list[str]:
    """Flags for chromium.launch(). Only flags Chrome accepts without warnings.

    Per patchright's "Best Practice" (https://github.com/Kaliiiiiiiiii-Vinyzu/
    patchright-python#best-practice), do NOT override user_agent or sec-ch-ua via
    CLI when using channel="chrome": Chrome's native UA is already the correct
    `Chrome/<cv>.0.0.0` (NOT HeadlessChrome in non-headless mode), and the
    sec-ch-ua Client Hints Chrome auto-sends match the local binary's TLS
    fingerprint (JA3/JA4). Overriding them here can only introduce mismatches
    between what the page sees (UA-string) and the actual TLS handshake.

    Patchright injects `--disable-blink-features=AutomationControlled` itself
    in its default args (patching navigator.webdriver at the blink layer). We
    don't strip it; Chrome v150+ shows a yellow "unsupported flag" infobar but
    that infobar is LOCAL (web pages cannot read infobars) and patchright's
    auto-removal of --enable-automation --no-sandbox etc. already covers the
    main automation flags.

    The fingerprint's UA/sec_ch_ua fields are still consumed by init_script()
    to spoof navigator.userAgentData for cross-PC consistency, but the CLI /
    headers no longer override what Chrome natively sends.
    """
    return [
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        "--disable-sync",
        "--disable-component-update",
        "--disable-default-apps",
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--lang=es-419",
        "--start-maximized",
        "--password-store=basic",
        "--use-mock-keychain",
    ]


def build_context_opts(fp: Fingerprint) -> dict:
    """Options for browser.new_context() syncing TZ/locales/screen.

    Per patchright's "Best Practice" (https://github.com/Kaliiiiiiiiii-Vinyzu/
    patchright-python#best-practice) we do NOT set user_agent or sec-ch-ua*
    extra HTTP headers: Chrome's native client hints already match the local
    binary's TLS (JA3/JA4) handshake. Overriding them would desync the network
    layer (JA3 from binary Chrome/151) from the page layer
    (UA-string we'd inject) and let Google correlate "same account, different
    device". The init_script() handles navigator.userAgentData / sec-ch-ua
    at the JS layer for cross-PC consistency without touching the wire.

    We still set timezone_id, locale, geolocation, accept-language header and
    viewport/screen — those need user-visible spoofing (TZ / screen size /
    language in the language list) that Chrome does not derive from the binary.
    """
    return {
        "viewport": {"width": fp.screen_width, "height": fp.screen_height},
        "screen": {"width": fp.screen_width, "height": fp.screen_height},
        "locale": fp.locale,
        "timezone_id": fp.timezone,
        "geolocation": {"longitude": -68.15, "latitude": -16.50, "accuracy": 100},
        "permissions": ["geolocation"],
        "color_scheme": "light",
        "extra_http_headers": {
            # accept-language stays: it's not user-agent dependent and our
            # claimed locales list (es-419, es, en) is part of the shared
            # fingerprint across all PCs on the LAN.
            "accept-language": f"{fp.languages[0]},{fp.languages[0]};q=0.9,en;q=0.8",
        },
    }


def init_script(fp: Fingerprint) -> str:
    """Large JS blob injected via context.add_init_script().

    Ported character-for-character from v9's Fingerprint.init_script(). It
    spoofs navigator, plugins, window.chrome, permissions, screen, WebGL and
    sec-ch-ua client hints. Canvas is intentionally left untouched (breaking it
    would corrupt Gemini image/video generation).
    """
    return f"""
(() => {{
  const ua = {json.dumps(fp.user_agent)};
  const plat = {json.dumps(fp.platform)};
  const langs = {json.dumps(fp.languages)};
  const tz = {json.dumps(fp.timezone)};
  const sw = {fp.screen_width};
  const sh = {fp.screen_height};
  const cd = {fp.color_depth};
  const hc = {fp.hardware_concurrency};
  const dm = {fp.device_memory};
  const wv = {json.dumps(fp.webgl_vendor)};
  const wr = {json.dumps(fp.webgl_renderer)};
  const secua = {json.dumps(fp.sec_ch_ua)};

  // navigator
  try {{ Object.defineProperty(navigator, 'webdriver', {{ get: () => undefined }}); }} catch(e){{}}
  try {{ Object.defineProperty(navigator, 'userAgent', {{ get: () => ua }}); }} catch(e){{}}
  try {{ Object.defineProperty(navigator, 'platform', {{ get: () => plat }}); }} catch(e){{}}
  try {{ Object.defineProperty(navigator, 'language', {{ get: () => langs[0] }}); }} catch(e){{}}
  try {{ Object.defineProperty(navigator, 'languages', {{ get: () => langs }}); }} catch(e){{}}
  try {{ Object.defineProperty(navigator, 'hardwareConcurrency', {{ get: () => hc }}); }} catch(e){{}}
  try {{ Object.defineProperty(navigator, 'deviceMemory', {{ get: () => dm }}); }} catch(e){{}}
  try {{ Object.defineProperty(navigator, 'maxTouchPoints', {{ get: () => 0 }}); }} catch(e){{}}

  // plugins falsos pero realistas
  try {{
    const fakePlugins = [
      {{name: "PDF Viewer", filename: "internal-pdf-viewer", description: "Portable Document Format"}},
      {{name: "Chrome PDF Viewer", filename: "internal-pdf-viewer", description: "Portable Document Format"}},
      {{name: "Chromium PDF Viewer", filename: "internal-pdf-viewer", description: "Portable Document Format"}},
      {{name: "Microsoft Edge PDF Viewer", filename: "internal-pdf-viewer", description: "Portable Document Format"}},
      {{name: "WebKit built-in PDF", filename: "internal-pdf-viewer", description: "Portable Document Format"}}
    ];
    Object.defineProperty(navigator, 'plugins', {{
      get: () => {{
        const arr = fakePlugins.map(p => Object.assign(document.createElement('object'), p));
        arr.namedItem = n => arr.find(p => p.name === n) || null;
        arr.refresh = () => {{}};
        arr.item = i => arr[i] || null;
        return arr;
      }}
    }});
  }} catch(e){{}}

  // window.chrome spoof: emperically verified (Chrome v151 + channel="chrome"
  // non-headless) that bare Chrome exposes `window.chrome = {{}}` with only
  // `csi` and `loadTimes` as real functions. `chrome.runtime` is `undefined`
  // when no extension is installed — patchright+channel="chrome" already
  // reproduces this *exactly*. So we ONLY add the functions if they don't
  // exist (don't pollute `chrome.runtime` / `chrome.app` which a page could
  // check for extension context).
  try {{
    if (!window.chrome) window.chrome = {{}};
    if (!window.chrome.csi) window.chrome.csi = () => {{}};
    if (!window.chrome.loadTimes) window.chrome.loadTimes = () => ({{}});
  }} catch(e){{}}

  // permissions API
  try {{
    const origQuery = navigator.permissions && navigator.permissions.query;
    if (origQuery) {{
      navigator.permissions.query = (params) => (
        params.name === 'notifications'
          ? Promise.resolve({{ state: Notification.permission }})
          : origQuery.call(navigator.permissions, params)
      );
    }}
  }} catch(e){{}}

  // screen
  try {{
    Object.defineProperty(screen, 'width', {{ get: () => sw }});
    Object.defineProperty(screen, 'availWidth', {{ get: () => sw }});
    Object.defineProperty(screen, 'height', {{ get: () => sh }});
    Object.defineProperty(screen, 'availHeight', {{ get: () => sh - 40 }});
    Object.defineProperty(screen, 'colorDepth', {{ get: () => cd }});
    Object.defineProperty(screen, 'pixelDepth', {{ get: () => cd }});
  }} catch(e){{}}

  // WebGL spoof
  try {{
    const getParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(param) {{
      if (param === 37445) return wv;  // UNMASKED_VENDOR_WEBGL
      if (param === 37446) return wr;  // UNMASKED_RENDERER_WEBGL
      return getParameter.call(this, param);
    }};
    if (window.WebGL2RenderingContext) {{
      const g2 = WebGL2RenderingContext.prototype.getParameter;
      WebGL2RenderingContext.prototype.getParameter = function(param) {{
        if (param === 37445) return wv;
        if (param === 37446) return wr;
        return g2.call(this, param);
      }};
    }}
  }} catch(e){{}}

  // NO tocamos canvas -> romperia generacion de imagenes/videos de Gemini
  // Google no usa canvas fingerprint para ban, si para tracking.
  // Es mejor dejarlo intacto que corromperlo.

  // Audio fingerprint spoof (OfflineAudioContext / AnalyserNode)
  // Google usa el hash de la respuesta de AudioContext para deviceID.
  // Devolvemos valores deterministicos para que todas las PCs reporten
  // el mismo audio fingerprint.
  try {{
    const spoofFrequencies = new Float32Array([0,0,0,0,0]);
    const origGetFloatFrequencyData = AnalyserNode.prototype.getFloatFrequencyData;
    AnalyserNode.prototype.getFloatFrequencyData = function(arr) {{
      for (let i = 0; i < arr.length; i++) arr[i] = -100 + (i % 7) * 0.001;
    }};
    const origCreateAnalyser = AudioContext.prototype.createAnalyser;
    AudioContext.prototype.createAnalyser = function() {{
      const a = origCreateAnalyser.call(this);
      a.frequencyBinCount = 1024;
      return a;
    }};
    if (window.OfflineAudioContext) {{
      const origGetChannelData = AudioBuffer.prototype.getChannelData;
      AudioBuffer.prototype.getChannelData = function() {{
        const data = origGetChannelData.apply(this, arguments);
        // Deterministic noise seed (same across PCs) instead of hardware-dependent float noise
        for (let i = 0; i < data.length; i++) {{
          data[i] = (Math.sin(i * 0.0001) * 0.0001);
        }}
        return data;
      }};
    }}
  }} catch(e){{}}

  // AudioContext.sampleRate spoof (hardware-dependent value)
  try {{
    try {{ Object.defineProperty(AudioContext.prototype, 'sampleRate', {{ get: () => 44100 }}); }} catch(e){{}}
    try {{ Object.defineProperty(OfflineAudioContext.prototype, 'sampleRate', {{ get: () => 44100 }}); }} catch(e){{}}
  }} catch(e){{}}

  // Font enumeration spoof (document.fonts.check / FontFaceSet)
  // Limitamos a un set comun de fuentes para evitar enumerar las instaladas
  // localmente (que difieren entre PCs).
  try {{
    if (document.fonts && document.fonts.check) {{
      const origCheck = document.fonts.check.bind(document.fonts);
      const commonFonts = new Set([
        'Arial', 'Helvetica', 'Times New Roman', 'Courier New', 'Verdana',
        'Georgia', 'Palatino', 'Garamond', 'Comic Sans MS', 'Trebuchet MS',
        'Lucida Console', 'Tahoma', 'Calibri', 'Cambria', 'Segoe UI'
      ]);
      document.fonts.check = function(font, family) {{
        // Acepta solo fuentes comunes; rechaza todo lo demas como "no disponible"
        const fam = (family || '').split(',')[0].trim().replace(/['"]/g, '');
        if (commonFonts.has(fam)) return true;
        return origCheck(font, family);
      }};
    }}
  }} catch(e){{}}

  // Battery API spoof (navigator.getBattery) -> valor fijo consistente
  try {{
    if (navigator.getBattery) {{
      navigator.getBattery = () => Promise.resolve({{
        charging: true, chargingTime: 0, dischargingTime: Infinity,
        level: 1, addEventListener: () => {{}}, removeEventListener: () => {{}}
      }});
    }}
  }} catch(e){{}}

  // sec-ch-ua client hints (version dinamica desde Python)
  try {{
    const cv = {json.dumps(str(fp.user_agent))}.match(/Chrome\\/(\\d+)/);
    const ver = cv ? cv[1] : "127";
    if (navigator.userAgentData) {{
      Object.defineProperty(navigator, 'userAgentData', {{
        get: () => ({{
          brands: [
            {{ brand: "Chromium", version: ver }},
            {{ brand: "Google Chrome", version: ver }},
            {{ brand: "Not)A;Brand", version: "24" }}
          ],
          mobile: false,
          platform: "Windows"
        }})
      }});
    }}
  }} catch(e){{}}
}})();
"""


__all__ = [
    "default_fingerprint",
    "build_chromium_args",
    "build_context_opts",
    "init_script",
    "reconcile_chrome_version",
    "detect_chrome_version",
    "detect_webgl_renderer",
]
