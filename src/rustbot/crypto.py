"""Encryption at rest for the Rust+ player token (CLAUDE.md §8).

Uses Fernet (AES-128-CBC + HMAC) so the token persisted in SQLite is not stored
as plaintext. This protects a leaked database file or backup *provided the
Fernet key is not stored alongside it* — the key lives in the environment, not
in the DB. It is deliberately "simple encryption" as the spec permits; it does
not defend against full host compromise (key + data on the same machine).
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


class CryptoError(Exception):
    """Raised when encryption or decryption fails (e.g. wrong/rotated key)."""


class TokenCipher:
    """Encrypt/decrypt small secrets with a Fernet key."""

    def __init__(self, key: str) -> None:
        """Initialize the cipher with a Fernet key.
        
        :param key: URL-safe base64 encoded Fernet key (generate with Fernet.generate_key()).
        :raises CryptoError: If the key is invalid or malformed.
        """
        try:
            self._fernet = Fernet(key.encode("utf-8"))
        except (ValueError, TypeError) as exc:
            raise CryptoError(
                "Invalid FERNET_KEY. Generate one with `python -m rustbot.genkey`."
            ) from exc

    def encrypt(self, plaintext: str) -> str:
        """Encrypt plaintext to a Fernet-encrypted base64 string.
        
        :param plaintext: The secret string to encrypt.
        :return: Base64-encoded ciphertext safe for persistent storage.
        """
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt a Fernet-encrypted base64 string back to plaintext.
        
        :param ciphertext: The encrypted string (as returned from encrypt()).
        :return: The decrypted plaintext.
        :raises CryptoError: If decryption fails (key mismatch or corrupted data).
        """
        try:
            return self._fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise CryptoError(
                "Could not decrypt stored token (key mismatch or corrupted data)."
            ) from exc

    @staticmethod
    def generate_key() -> str:
        """Generate a new url-safe base64 Fernet key."""
        return Fernet.generate_key().decode("utf-8")
