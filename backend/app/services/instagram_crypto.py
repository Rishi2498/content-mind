"""Encryption utilities for Instagram token storage.

Uses AES-GCM (authenticated encryption) with keys derived from the
configured INSTAGRAM_ENCRYPTION_KEY via HKDF. If no key is configured,
operations fail closed (raise) rather than storing plaintext.
"""

from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from ..config import get_settings


# Module-level cached key (bytes) for the current process.
_ENCRYPTION_KEY: bytes | None = None


def _get_or_derive_key() -> bytes:
    """Return the 32-byte AES-GCM key, deriving it once per process."""
    global _ENCRYPTION_KEY
    if _ENCRYPTION_KEY is not None:
        return _ENCRYPTION_KEY

    settings = get_settings()
    secret = settings.instagram_encryption_key
    if not secret:
        raise RuntimeError(
            "INSTAGRAM_ENCRYPTION_KEY is not set. Cannot encrypt/decrypt tokens. "
            "Set a 32+ character secret in the environment."
        )

    # Derive a 32-byte key using HKDF-SHA256 with a fixed info string.
    # This ensures the key is suitable for AES-256-GCM even if the
    # configured secret is longer/shorter or not exactly 32 bytes.
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"contentmind-instagram-token-encryption",
    )
    _ENCRYPTION_KEY = hkdf.derive(secret.encode("utf-8"))
    return _ENCRYPTION_KEY


def encrypt_token(plaintext: str) -> str:
    """Encrypt a token string and return a base64-encoded ciphertext.

    Format: base64(nonce(12) || ciphertext || tag(16))
    """
    if not plaintext:
        return ""

    key = _get_or_derive_key()
    aesgcm = AESGCM(key)

    # Generate a random 96-bit nonce for AES-GCM.
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)

    # The ciphertext includes the 16-byte authentication tag at the end.
    combined = nonce + ciphertext
    return base64.b64encode(combined).decode("ascii")


def decrypt_token(ciphertext_b64: str) -> str:
    """Decrypt a base64-encoded ciphertext back to the original token string."""
    if not ciphertext_b64:
        return ""

    key = _get_or_derive_key()
    aesgcm = AESGCM(key)

    try:
        combined = base64.b64decode(ciphertext_b64)
    except Exception as e:
        raise ValueError("Invalid encrypted token format") from e

    if len(combined) < 12 + 16:
        raise ValueError("Encrypted token too short")

    nonce = combined[:12]
    ciphertext = combined[12:]

    try:
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    except Exception as e:
        raise ValueError("Token decryption failed (wrong key or corrupted data)") from e

    return plaintext.decode("utf-8")