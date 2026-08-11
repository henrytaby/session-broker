from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

from app.core.config import settings
from app.core.logging import get_logger
from app.domain.exceptions import ChatNotReadyError
from app.domain.ports.ai_session import IAISession

log = get_logger(__name__)

# Selectors isolated as constants (DOM changes are the main residual risk).
_INPUT_SELECTOR = '[role="textbox"]'
_RESPONSE_SELECTOR = "model-response"
# The ".model-response-text" child holds ONLY the answer body, without the
# "Gemini said" accessibility label that inner_text() on the parent includes.
_RESPONSE_BODY_SELECTOR = "model-response .model-response-text"
# The ".markdown" sub-element holds the rendered response HTML (p, b, ul, li, img).
_MARKDOWN_SELECTOR = "model-response .model-response-text .markdown"
# Placeholder prefixes Gemini renders before the real answer stream starts
# (status chips like "Analyzing...", "Clarifying the Query", "Gemini said").
_LABEL_PREFIX = "Gemini said"

# JS function executed via page.evaluate to extract clean HTML from the
# Nth model-response: normalizes Angular <single-image> to real <img>, removes
# Angular comment placeholders and irrelevant attributes.
_EXTRACT_HTML_JS = """() => {
    const idx = arguments[0];
    const all = document.querySelectorAll('model-response .model-response-text');
    if (idx >= all.length) return '';
    const el = all[idx];
    const md = el.querySelector('.markdown');
    if (!md) return '';
    const clone = md.cloneNode(true);
    // Remove Angular comment placeholders
    clone.querySelectorAll('*').forEach(n => {
        for (let i = n.childNodes.length - 1; i >= 0; i--) {
            const c = n.childNodes[i];
            if (c.nodeType === 8) n.removeChild(c);
        }
        // Strip Angular-specific attributes
        [...n.attributes].forEach(a => {
            if (a.name.startsWith('_ng') || a.name.startsWith('_nghost') || a.name.startsWith('_ngcontent') || a.name.startsWith('data-path') || a.name.startsWith('data-index') || a.name === 'jslog' || a.name === 'inline-copy-host') {
                n.removeAttribute(a.name);
            }
        });
    });
    // Normalize <single-image> / .image-container to real <img>
    const imgs = clone.querySelectorAll('single-image, .image-container');
    imgs.forEach(c => {
        let uri = c.getAttribute('data-full-size-image-uri');
        if (!uri) {
            const inner = c.querySelector('[data-full-size-image-uri]');
            if (inner) uri = inner.getAttribute('data-full-size-image-uri');
        }
        if (uri) {
            const img = document.createElement('img');
            img.src = uri;
            img.style.maxWidth = '100%';
            img.style.borderRadius = '8px';
            img.style.margin = '8px 0';
            img.alt = '';
            c.replaceWith(img);
        }
    });
    // Also convert remaining <single-image> wrappers
    const wrappers = clone.querySelectorAll('response-element, .attachment-container');
    wrappers.forEach(w => {
        const innerHtml = w.innerHTML;
        if (innerHtml.trim()) {
            const div = document.createElement('div');
            div.innerHTML = innerHtml;
            w.replaceWith(div);
        } else {
            w.remove();
        }
    });
    // Remove empty class attributes
    clone.querySelectorAll('[class=""]').forEach(n => n.removeAttribute('class'));
    // Collapse HTML comments
    let html = clone.innerHTML.replace(/<!--[\\s\\S]*?-->/g, '');
    return html;
}"""


def _strip_label(text: str) -> str:
    """Strip the leading 'Gemini said' accessibility label if present."""
    if text.startswith(_LABEL_PREFIX):
        text = text[len(_LABEL_PREFIX):]
    return text.strip()


class GeminiCdpSession(IAISession):
    """IAISession impl that attaches to the already-running headless Chrome
    instance (pc1) over CDP instead of launching its own browser.

    Unlike the gemini-proxy sketch (launch_persistent_context), this connects
    via `connect_over_cdp` to GEMINI_CDP_PORT (the real Chrome debug port) and
    reuses the pc1 instance owned by the server. It never touches the master
    profile, avoiding lock conflicts.
    """

    def __init__(self, cdp_port: int | None = None, start_url: str | None = None) -> None:
        self._cdp_port = cdp_port if cdp_port is not None else settings.GEMINI_CDP_PORT
        self._start_url = start_url or settings.GEMINI_START_URL
        self._playwright = None
        self._browser = None
        self._page = None
        self._ready = False

    def is_ready(self) -> bool:
        return self._ready

    async def initialize(self) -> None:
        from patchright.async_api import async_playwright

        from app.domain.models import Fingerprint
        from app.infrastructure.fingerprint.chrome_finder import detect_chrome_version
        from app.infrastructure.fingerprint.fingerprint import (
            build_context_opts,
            init_script,
        )

        self._playwright = await async_playwright().start()
        endpoint = f"http://127.0.0.1:{self._cdp_port}"
        log.info("conectando via CDP a %s", endpoint)
        self._browser = await self._playwright.chromium.connect_over_cdp(endpoint)

        contexts = self._browser.contexts
        context = contexts[0] if contexts else await self._browser.new_context()
        pages = context.pages
        self._page = pages[0] if pages else await context.new_page()

        # CRITICAL anti-detection: pc1 was launched with --headless=new, so its
        # default UA contains "HeadlessChrome/..." (visible to pages AND reported
        # by /json/version). CDP-over-UAB cannot change the browser's process
        # UA after launch, but we CAN inject an init script that rewrites
        # navigator.userAgent / userAgentData on every page load, and set
        # sec-ch-ua Client Hints via extra_http_headers. Without this, Gemini
        # sees "HeadlessChrome" + navigator.webdriver=true on the chat page.
        cv = detect_chrome_version()
        fp = Fingerprint(
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
        try:
            await context.add_init_script(init_script(fp))
            ctx_opts = build_context_opts(fp)
            # viewport/screen are not settable on an existing CDP context,
            # but extra_http_headers IS (Emulation.setExtraHTTPHeaders).
            headers = ctx_opts.get("extra_http_headers", {})
            if headers:
                await context.set_extra_http_headers(headers)
            # timezone / locale cannot be set on an existing CDP-linked
            # context (they're new_context options). The init_script spoofs
            # navigator.language/languages; for Intl/TZ we rely on the server's
            # Windows timezone (America/La_Paz) matching the claimed fingerprint.
        except Exception as e:
            log.debug("no se pudo inyectar init_script en pc1: %r", e)

        current = self._page.url
        if "gemini.google.com" not in current:
            await self._page.goto(self._start_url, wait_until="domcontentloaded")
        else:
            # Already on Gemini: reload so the init_script runs (it only runs
            # on new navigations). This is idempotent on a logged-in session.
            try:
                await self._page.reload(wait_until="domcontentloaded", timeout=30000)
            except Exception:
                pass
        self._ready = True
        log.info("sesion de Gemini inicializada via CDP (pc1)")

    async def send_prompt_and_stream(self, prompt: str) -> AsyncGenerator[str, None]:
        if not self._ready or self._page is None:
            raise ChatNotReadyError("La sesion de chat no esta lista.")

        page = self._page
        try:
            editor = page.locator(_INPUT_SELECTOR).first
            await editor.click()
            await asyncio.sleep(0.3)
            await editor.type(prompt, delay=10)
            await asyncio.sleep(0.3)

            # Snapshot how many model-response blocks exist BEFORE this prompt,
            # so we capture only the NEW one (supports multi-turn conversations).
            before_count = await page.locator(_RESPONSE_SELECTOR).count()

            await page.keyboard.press("Enter")

            last_text = ""
            timeout = 90
            start_time = asyncio.get_event_loop().time()
            stable_count = 0
            # Require ~2.5s of stability so we don't exit while Gemini is still
            # showing the "Analyzing/Clarifying..." status chip before streaming.
            stable_needed = 10

            await asyncio.sleep(1)

            while asyncio.get_event_loop().time() - start_time < timeout:
                await asyncio.sleep(0.3)
                count = await page.locator(_RESPONSE_SELECTOR).count()
                if count <= before_count:
                    continue  # new response not yet rendered

                idx = count - 1
                # Extract clean HTML (with formatting + images) from the .markdown
                # sub-element inside the new model-response block.
                try:
                    current_text = await page.evaluate(_EXTRACT_HTML_JS, idx)
                except Exception:
                    try:
                        raw = await page.locator(_RESPONSE_BODY_SELECTOR).nth(idx).inner_text(timeout=1000)
                        current_text = _strip_label(raw)
                    except Exception:
                        continue

                if current_text and current_text != last_text:
                    stable_count = 0
                    yield current_text
                    last_text = current_text
                elif current_text and current_text == last_text:
                    stable_count += 1
                    if stable_count >= stable_needed:
                        break
            else:
                yield "[Timeout: La respuesta tardo demasiado]"
        except Exception as e:
            yield f"[Error en Playwright: {e}]"

    async def close(self) -> None:
        # connect_over_cdp does not own the browser; just disconnect + stop pw.
        self._ready = False
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                pass
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:
                pass


class FakeAISession(IAISession):
    """Test double implementing IAISession (used by tests / N_INSTANCES=0)."""

    def __init__(self, replies: list[str] | None = None) -> None:
        self._replies = replies or ["[fake] respuesta de prueba"]
        self._ready = False

    def is_ready(self) -> bool:
        return self._ready

    async def initialize(self) -> None:
        self._ready = True

    async def send_prompt_and_stream(self, prompt: str) -> AsyncGenerator[str, None]:
        if not self._ready:
            raise ChatNotReadyError("FakeAISession not ready")
        for r in self._replies:
            yield r

    async def close(self) -> None:
        self._ready = False
