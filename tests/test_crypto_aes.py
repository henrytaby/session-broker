from __future__ import annotations

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.infrastructure.crypto.aes_gcm import decrypt_value

MASTER_KEY = b"0123456789ABCDEF0123456789ABCDEF"  # 32 bytes


def _v10(plaintext: bytes) -> bytes:
    nonce = b"012345678901"
    ct = AESGCM(MASTER_KEY).encrypt(nonce, plaintext, None)
    return b"v10" + nonce + ct


def test_decrypt_empty_returns_empty():
    assert decrypt_value(b"", MASTER_KEY) == ""
    assert decrypt_value(None, MASTER_KEY) == ""  # type: ignore[arg-type]


def test_decrypt_v10_plain():
    assert decrypt_value(_v10(b"hello-world"), MASTER_KEY) == "hello-world"


def test_decrypt_v10_with_domain_hash_skipped():
    """Chrome v127+ prepends 32 bytes of SHA-256(host); they must be skipped."""
    domain_hash = b"x" * 32
    payload = domain_hash + b"hashed-value"
    assert decrypt_value(_v10(payload), MASTER_KEY) == "hashed-value"


def test_decrypt_v10_short_payload_returned_as_is():
    """Payloads <= 32 bytes cannot have a domain hash -> decoded directly."""
    assert decrypt_value(_v10(b"short"), MASTER_KEY) == "short"


def test_decrypt_invalid_returns_empty():
    bad = b"v10" + b"0" * 30  # not a valid GCM ciphertext
    assert decrypt_value(bad, MASTER_KEY) == ""


def test_decrypt_plain_dpapi_fallback(monkeypatch):
    """Non-v10 values go through win32crypt.CryptUnprotectData."""
    import app.infrastructure.crypto.aes_gcm as mod

    def fake_unprotect(data, *a, **kw):
        return (None, b"dpapi-decoded")

    monkeypatch.setattr(mod.win32crypt, "CryptUnprotectData", fake_unprotect)
    assert decrypt_value(b"raw-bytes", MASTER_KEY) == "dpapi-decoded"


def test_decrypt_plain_dpapi_failure_returns_empty(monkeypatch):
    import app.infrastructure.crypto.aes_gcm as mod

    def fake_unprotect(data, *a, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(mod.win32crypt, "CryptUnprotectData", fake_unprotect)
    assert decrypt_value(b"raw-bytes", MASTER_KEY) == ""
