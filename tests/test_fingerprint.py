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


def test_build_chromium_args_contains_lang_and_useragent():
    fp = default_fingerprint(chrome_version=140)
    args = build_chromium_args(fp)
    assert any(a.startswith("--user-agent=") for a in args)
    assert "--lang=es-419" in args
    assert "--start-maximized" in args
    # Patchright-managed flags must NOT be present (would warn on Chrome v150+)
    assert "--disable-blink-features=AutomationControlled" not in args
    assert "--disable-infobars" not in args


def test_build_context_opts_has_tz_and_headers():
    fp = default_fingerprint(chrome_version=140)
    opts = build_context_opts(fp)
    assert opts["timezone_id"] == "America/La_Paz"
    assert opts["locale"] == "es-419"
    assert opts["extra_http_headers"]["sec-ch-ua"] == fp.sec_ch_ua
    assert opts["extra_http_headers"]["sec-ch-ua-platform"] == '"Windows"'


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
