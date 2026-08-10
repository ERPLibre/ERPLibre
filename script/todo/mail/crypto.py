#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Scellement du cache courriel.

Une enveloppe AUTO-DESCRIPTIVE précède chaque donnée : le premier octet-paire
dit comment lire la suite. Conséquence voulue : une base écrite en clair reste
lisible après passage en mode chiffré, et l'inverse échoue bruyamment plutôt
que de rendre du charabia.

    clair    b"P0" + donnees
    chiffre  b"E1" + nonce(12) + AES-256-GCM(chiffre || tag)
"""
from __future__ import annotations

import os

from script.todo.todo_i18n import t

CLEAR_MAGIC = b"P0"
SEALED_MAGIC = b"E1"
NONCE_LEN = 12
KEY_LEN = 32


class CryptoError(Exception):
    """Clé absente, clé fausse, enveloppe inconnue ou donnée altérée."""


def new_key() -> bytes:
    """Une clé AES-256 tirée du générateur du système."""
    return os.urandom(KEY_LEN)


class MailCrypto:
    """Interface commune. `open` sait toujours lire une enveloppe en clair."""

    def seal(self, data: bytes) -> bytes:
        raise NotImplementedError

    def open(self, blob: bytes) -> bytes:
        raise NotImplementedError

    @staticmethod
    def _split(blob: bytes) -> tuple[bytes, bytes]:
        if not isinstance(blob, (bytes, bytearray)) or len(blob) < 2:
            raise CryptoError(t("mail_err_envelope_too_short"))
        return bytes(blob[:2]), bytes(blob[2:])


class NullCrypto(MailCrypto):
    """Mode `clear` : on marque, on ne chiffre pas."""

    def seal(self, data: bytes) -> bytes:
        return CLEAR_MAGIC + data

    def open(self, blob: bytes) -> bytes:
        magic, body = self._split(blob)
        if magic == CLEAR_MAGIC:
            return body
        if magic == SEALED_MAGIC:
            raise CryptoError(t("mail_err_sealed_in_clear_mode"))
        raise CryptoError(f"{t('mail_err_unknown_envelope')} {magic!r}")


class AesGcmCrypto(MailCrypto):
    """Modes `encrypted` et `ephemeral` : AES-256-GCM, nonce neuf à chaque appel."""

    def __init__(self, key: bytes) -> None:
        if not isinstance(key, (bytes, bytearray)) or len(key) != KEY_LEN:
            raise CryptoError(
                f"{t('mail_err_key_wrong_length')} {KEY_LEN}"
                f" {t('mail_err_octets_unit')}"
            )
        try:
            from cryptography.exceptions import InvalidTag
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError as exc:  # pragma: no cover - dépendance absente
            raise CryptoError(
                t("mail_err_cryptography_not_installed")
            ) from exc
        self._aes = AESGCM(bytes(key))
        self._invalid_tag = InvalidTag

    def seal(self, data: bytes) -> bytes:
        nonce = os.urandom(NONCE_LEN)
        return SEALED_MAGIC + nonce + self._aes.encrypt(nonce, data, None)

    def open(self, blob: bytes) -> bytes:
        magic, body = self._split(blob)
        if magic == CLEAR_MAGIC:
            return body
        if magic != SEALED_MAGIC:
            raise CryptoError(f"{t('mail_err_unknown_envelope')} {magic!r}")
        nonce, payload = body[:NONCE_LEN], body[NONCE_LEN:]
        try:
            return self._aes.decrypt(nonce, payload, None)
        except self._invalid_tag as exc:
            raise CryptoError(t("mail_err_decrypt_refused")) from exc
        except ValueError as exc:
            raise CryptoError(
                f"{t('mail_err_envelope_unreadable')} {exc}"
            ) from exc
        # Toute autre exception remonte telle quelle : un bug de programmation
        # ne doit JAMAIS se déguiser en « mauvaise clé ».


def build_crypto(mode: str, key: bytes | None) -> MailCrypto:
    """La boîte qui correspond au mode de cache d'un compte."""
    if mode == "clear":
        return NullCrypto()
    if mode in ("encrypted", "ephemeral"):
        if key is None:
            raise CryptoError(
                f"{t('mail_err_mode_prefix')} {mode}"
                f" {t('mail_err_mode_requires_key')}"
            )
        return AesGcmCrypto(key)
    raise CryptoError(f"{t('mail_err_unknown_cache_mode')} {mode}")
