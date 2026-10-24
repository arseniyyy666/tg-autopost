"""Authenticated encryption (AES-256-GCM) for stored Telegram sessions.

A session string gives full access to a Telegram account, so it is never stored
in plain text. Keys come only from the environment (SESSION_KEYS) and support
rotation: new data is encrypted with the highest key version, old versions are
kept just to decrypt existing rows.
"""
import base64
import os
from functools import lru_cache

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

NONCE_SIZE = 12


class CryptoError(Exception):
    """Invalid key configuration or data that cannot be decrypted."""


class SessionCipher:
    def __init__(self, keys_spec: str):
        self._keys: dict[int, bytes] = {}
        for item in keys_spec.split(","):
            item = item.strip()
            if not item:
                continue
            version_text, _, key_b64 = item.partition(":")
            try:
                version = int(version_text)
                key = base64.urlsafe_b64decode(key_b64)
            except ValueError:
                raise CryptoError("invalid SESSION_KEYS format") from None
            if len(key) != 32:
                raise CryptoError("each session key must be 32 bytes")
            self._keys[version] = key
        if not self._keys:
            raise CryptoError("SESSION_KEYS is empty")
        self.current_version = max(self._keys)

    def encrypt(self, plaintext: str, aad: bytes) -> tuple[bytes, int]:
        nonce = os.urandom(NONCE_SIZE)
        key = self._keys[self.current_version]
        blob = nonce + AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), aad)
        return blob, self.current_version

    def decrypt(self, blob: bytes, key_version: int, aad: bytes) -> str:
        key = self._keys.get(key_version)
        if key is None or len(blob) <= NONCE_SIZE:
            raise CryptoError("cannot decrypt stored data")
        try:
            plain = AESGCM(key).decrypt(blob[:NONCE_SIZE], blob[NONCE_SIZE:], aad)
        except InvalidTag:
            raise CryptoError("cannot decrypt stored data") from None
        return plain.decode("utf-8")


@lru_cache(maxsize=1)
def get_cipher() -> SessionCipher:
    from app.config import settings

    return SessionCipher(settings.session_keys)


def session_aad(user_id: int) -> bytes:
    """Bind a ciphertext to its owner so it cannot be swapped between users."""
    return f"tg-session:{user_id}".encode()
