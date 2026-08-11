from __future__ import annotations

import json

from app.domain.models import Fingerprint
from app.infrastructure.fingerprint.fingerprint import (
    build_chromium_args,
    build_context_opts,
    default_fingerprint,
    init_script,
)


def test_default_fingerprint_uses_chrome_version():
    fp = default_fingerprint(chrome_version=151)
    assert "Chrome/151.0.0.0" in fp.user_agent
    assert '"Chromium";v="151"' in fp.sec_ch_ua
    assert fp.platform == "Win32"
    assert fp.languages[0] == "es-419"


def test_fingerprint_roundtrip():
    fp = default_fingerprint(chrome_version=130)
    js = fp.model_dump_json()
    restored = Fingerprint.model_validate_json(js)
    assert restored == fp


def test_build_chromium_args_lang_no_useragent_override():
    """Per patchright Best Practice, we do NOT override --user-agent on the
    CLI when channel="chrome": Chrome's native UA is already the correct
    `Chrome/<cv>.0.0.0` and overrides would risk mismatches with the binary's
    actual TLS (JA3/JA4) handshake. The UA/sec-ch-ua spoofing is handled by
    init_script() at the JS layer instead."""
    fp = default_fingerprint(chrome_version=140)
    args = build_chromium_args(fp)
    assert not any(a.startswith("--user-agent=") for a in args)
    assert "--lang=es-419" in args
    assert "--start-maximized" in args
    # Patchright-managed flags must NOT be present in OUR args (patchright
    # injects its own defaults separately); --disable-blink-features=
    # AutomationControlled is patchright's, not ours.
    assert "--disable-blink-features=AutomationControlled" not in args
    assert "--disable-infobars" not in args


def test_build_context_opts_tz_locale_no_ua_secchua():
    """Per patchright Best Practice, do NOT set user_agent / sec-ch-ua* extra
    headers: Chrome's native hints match the binary's TLS fingerprint. We
    still set timezone_id, locale, and accept-language (network-visible parts
    that Chrome does not derive from the binary)."""
    fp = default_fingerprint(chrome_version=140)
    opts = build_context_opts(fp)
    assert opts["timezone_id"] == "America/La_Paz"
    assert opts["locale"] == "es-419"
    # user_agent is no longer set on context opts
    assert "user_agent" not in opts
    headers = opts["extra_http_headers"]
    # accept-language stays (it's part of the shared fingerprint)
    assert headers.get("accept-language", "").startswith(fp.languages[0])
    # sec-ch-ua* are no longer injected as custom headers
    assert "sec-ch-ua" not in headers
    assert "sec-ch-ua-mobile" not in headers
    assert "sec-ch-ua-platform" not in headers


def test_init_script_contains_spoofs():
    fp = default_fingerprint(chrome_version=140)
    js = init_script(fp)
    assert "webdriver" in js
    assert "37445" in js  # UNMASKED_VENDOR_WEBGL
    assert "37446" in js  # UNMASKED_RENDERER_WEBGL
    assert "fakePlugins" in js
    assert "userAgentData" in js
    # Canvas must NOT be actively spoofed (would corrupt Gemini image gen)
    assert "toDataURL" not in js
    assert "getImageData" not in js


def test_init_script_is_valid_js_payload():
    fp = default_fingerprint(chrome_version=140)
    js = init_script(fp)
    # It's an IIFE
    assert js.strip().startswith("(() => {")
    assert js.strip().endswith("})();")
