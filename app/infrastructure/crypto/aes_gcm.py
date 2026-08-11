from __future__ import annotations

import win32crypt

from app.core.logging import get_logger

log = get_logger(__name__)

# Dual crypto backend, selected at import time (mirrors the original v9 logic):
# prefer pycryptodome, fall back to cryptography.
try:
    from Crypto.Cipher import AES as _PyCryptoAES

    USE_CRYPTOGRAPHY = False
except ImportError:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    USE_CRYPTOGRAPHY = True


def decrypt_value(encrypted_value: bytes, master_key: bytes) -> str:
    """Decrypt a single cookie value (v10/v11 AES-GCM or DPAPI plaintext).

    Chrome v127+ inserts 32 bytes of SHA-256(host_key) at the start of the
    plaintext (App-Bound Encryption / domain hash). They are skipped
    automatically. The fragile try/except chain is ported verbatim from v9.
    """
    if encrypted_value is None or len(encrypted_value) == 0:
        return ""

    if encrypted_value[:3] in (b"v10", b"v11"):
        if USE_CRYPTOGRAPHY:
            nonce = encrypted_value[3:15]
            ciphertext_and_tag = encrypted_value[15:]
            aesgcm = AESGCM(master_key)
            try:
                plaintext = aesgcm.decrypt(nonce, ciphertext_and_tag, None)
            except Exception as e:
                log.debug("decrypt error: %r", e)
                return ""
        else:
            iv = encrypted_value[3:15]
            payload = encrypted_value[15:]
            cipher = _PyCryptoAES.new(master_key, _PyCryptoAES.MODE_GCM, nonce=iv)
            try:
                plaintext = cipher.decrypt_and_verify(payload[:-16], payload[-16:])
            except Exception:
                return ""

        if plaintext and len(plaintext) > 32:
            try:
                plaintext[32:].decode("utf-8")
                plaintext = plaintext[32:]
            except UnicodeDecodeError:
                try:
                    plaintext.decode("utf-8")
                except UnicodeDecodeError:
                    plaintext = plaintext[32:]
                    try:
                        plaintext.decode("utf-8")
                    except UnicodeDecodeError:
                        return ""

        try:
            return plaintext.decode("utf-8")
        except UnicodeDecodeError:
            return plaintext.decode("latin-1", errors="replace")
    else:
        try:
            return (
                win32crypt.CryptUnprotectData(encrypted_value, None, None, None, 0)[1]
                .decode("utf-8", errors="replace")
            )
        except Exception:
            return ""
