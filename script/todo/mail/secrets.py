#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Où vivent les mots de passe courriel.

Deux coffres, dans cet ordre : le kdbx du dépôt (déjà utilisé par le CLI pour
OpenAI et les comptes Odoo), puis le trousseau du système.

Le trousseau système n'est accepté QUE si son backend chiffre vraiment. Sans
service de secrets — SSH, conteneur, poste sans session graphique — `keyring`
retombe sur `keyrings.alt`, qui écrit le mot de passe en clair dans un fichier.
L'accepter en silence serait un piège, donc on refuse et on le dit.

Référence de secret : "<coffre>:<chemin>"
    kdbx:ERPLibre/Mail/perso              -> groupe ERPLibre > Mail, entrée perso
    kdbx:ERPLibre/Mail/perso/cache-key    -> ... entrée cache-key
    keyring:perso                         -> service "erplibre-mail", user perso
"""
from __future__ import annotations

import logging

from script.todo.todo_i18n import t

_logger = logging.getLogger(__name__)

KEYRING_SERVICE = "erplibre-mail"

# Backends dont on sait qu'ils chiffrent. Liste blanche volontaire : un
# backend inconnu est refusé, parce qu'on ne peut pas prouver qu'il chiffre.
SAFE_BACKENDS = {
    ("keyring.backends.SecretService", "Keyring"),
    ("keyring.backends.macOS", "Keyring"),
    ("keyring.backends.Windows", "WinVaultKeyring"),
    ("keyring.backends.kwallet", "DBusKeyring"),
}


class SecretError(Exception):
    """Aucun coffre utilisable, ou référence malformée."""


def keyring_backend_name() -> str:
    """Nom pleinement qualifié du backend keyring actif, "" s'il est absent."""
    try:
        import keyring
    except ImportError:
        return ""
    backend = keyring.get_keyring()
    cls = type(backend)
    return f"{cls.__module__}.{cls.__qualname__}"


def keyring_is_safe() -> bool:
    """Vrai seulement si le backend actif chiffre pour de bon."""
    try:
        import keyring
    except ImportError:
        return False
    cls = type(keyring.get_keyring())
    return (cls.__module__, cls.__qualname__) in SAFE_BACKENDS


def create_kdbx(path: str, password: str) -> None:
    """Crée une base KeePass vide. Refuse d'écraser un fichier existant."""
    import os

    from pykeepass import create_database

    if os.path.exists(path):
        raise SecretError(f"{t('mail_err_file_already_exists')} {path}")
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    os.chmod(parent, 0o700)
    # `create_database` écrit d'abord un fichier `.tmp` — `construct` l'ouvre
    # avec `open(filename, "w+b")`, donc à l'umask du process — avant un
    # `shutil.move` vers `path` (pykeepass évite ainsi de corrompre une base
    # existante en cas d'échec). Un `os.open` sur `path` ne fermerait donc
    # PAS la fenêtre : c'est ce fichier intermédiaire, invisible d'ici, qui
    # porterait le coffre en clair. Resserrer l'umask le temps de l'appel
    # couvre les deux fichiers.
    previous_umask = os.umask(0o077)
    try:
        create_database(path, password=password)
    finally:
        os.umask(previous_umask)
    os.chmod(path, 0o600)


class SecretStore:
    """Lecture et écriture de secrets, par référence."""

    def __init__(self, kdbx_manager=None, use_keyring: bool = True) -> None:
        self._kdbx_manager = kdbx_manager
        self._use_keyring = use_keyring

    # -- API publique ---------------------------------------------------

    def available_backends(self) -> list[str]:
        found = []
        if self._kdbx_manager is not None:
            found.append("kdbx")
        if self._use_keyring and keyring_is_safe():
            found.append("keyring")
        return found

    def get(self, ref: str) -> str | None:
        scheme, path = self._parse(ref)
        if scheme == "kdbx":
            entry = self._kdbx_entry(path, create=False)
            return entry.password if entry else None
        return self._keyring_call("get_password", path)

    def set(self, ref: str, secret: str) -> None:
        scheme, path = self._parse(ref)
        if scheme == "kdbx":
            entry = self._kdbx_entry(path, create=True)
            entry.password = secret
            self._kdbx().save()
            return
        self._keyring_call("set_password", path, secret)

    def delete(self, ref: str) -> None:
        scheme, path = self._parse(ref)
        if scheme == "kdbx":
            entry = self._kdbx_entry(path, create=False)
            if entry:
                self._kdbx().delete_entry(entry)
                self._kdbx().save()
            return
        self._keyring_call("delete_password", path)

    # -- Détail ---------------------------------------------------------

    @staticmethod
    def _parse(ref: str) -> tuple[str, str]:
        scheme, sep, path = (ref or "").partition(":")
        if not sep or scheme not in ("kdbx", "keyring") or not path:
            raise SecretError(f"{t('mail_err_invalid_secret_ref')} {ref!r}")
        return scheme, path

    def _kdbx(self):
        if self._kdbx_manager is None:
            raise SecretError(t("mail_err_no_kdbx_configured"))
        kp = self._kdbx_manager.get_kdbx()
        if kp is None:
            raise SecretError(t("mail_err_kdbx_unreadable"))
        return kp

    def _kdbx_entry(self, path: str, create: bool):
        """`path` = "Groupe/SousGroupe/Titre". Crée les groupes au besoin."""
        kp = self._kdbx()
        *group_names, title = path.split("/")
        group = kp.root_group
        for name in group_names:
            found = next((g for g in group.subgroups if g.name == name), None)
            if found is None:
                if not create:
                    return None
                found = kp.add_group(group, name)
            group = found
        entry = next((e for e in group.entries if e.title == title), None)
        if entry is None and create:
            entry = kp.add_entry(group, title, "", "")
        return entry

    def _keyring_call(self, func_name: str, *args):
        if not self._use_keyring:
            raise SecretError(t("mail_err_no_vault_available"))
        if not keyring_is_safe():
            raise SecretError(
                f"{t('mail_err_keyring_plaintext')}"
                f" {keyring_backend_name() or 'absent'})."
                f" {t('mail_err_keyring_plaintext_hint')}"
            )
        import keyring

        return getattr(keyring, func_name)(KEYRING_SERVICE, *args)
