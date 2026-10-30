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

import contextlib
import logging
import os
import threading
from collections.abc import Callable, Mapping
from pathlib import Path

from script.todo import kdbx_write
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


# Le seul backend que le service lit sans session : Secret Service, sondé
# sans jamais rien déverrouiller ni créer.
SECRET_SERVICE_BACKEND = ("keyring.backends.SecretService", "Keyring")
# Attente de la sonde du trousseau, en secondes : un bus muet ne fige pas
# la passe.
KEYRING_PROBE_S = 5.0


class SecretError(Exception):
    """Aucun coffre utilisable, ou référence malformée."""


class MissingSecret(SecretError):
    """Le coffre répond, mais n'a pas d'entrée pour cette référence."""


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


def _user_bus_socket() -> Path:
    """La socket du bus de session que systemd ouvre pour l'utilisateur."""
    return Path(f"/run/user/{os.getuid()}/bus")


def _probe_keyring() -> str:
    """Le corps de `keyring_headless_problem`, hors de la garde du délai.

    Ni `get_default_collection` ni `create_collection` : le premier CRÉE
    la collection absente, donc ouvre une invite « choisir un mot de
    passe ». `Collection(conn)` lève `ItemNotFoundException` sans rien
    créer. Jamais `unlock()` : une invite graphique surgirait sur le
    bureau à chaque passe.
    """
    if not keyring_is_safe():
        return "mail_service_keyring_unsafe"
    import keyring

    backend = keyring.get_keyring()
    cls = type(backend)
    if (cls.__module__, cls.__qualname__) != SECRET_SERVICE_BACKEND:
        # KWallet ouvre un portefeuille fermé par une fenêtre : refusé
        # avant tout appel au bus.
        return "mail_service_keyring_unsupported"
    import secretstorage

    conn = secretstorage.dbus_init()
    try:
        path = getattr(backend, "preferred_collection", None)
        try:
            if path:
                collection = secretstorage.Collection(conn, path)
            else:
                collection = secretstorage.Collection(conn)
        except secretstorage.ItemNotFoundException:
            return "mail_service_keyring_no_collection"
        if collection.is_locked():
            return "mail_service_keyring_locked"
        return ""
    finally:
        with contextlib.suppress(Exception):
            conn.close()


def keyring_headless_problem(
    env: Mapping[str, str] = os.environ, *, timeout: float = KEYRING_PROBE_S
) -> str:
    """Chaîne vide si le trousseau sert sans interaction ; sinon la clé
    i18n qui dit pourquoi.

    Sans bus de session (ni `DBUS_SESSION_BUS_ADDRESS` ni socket de
    l'utilisateur), rien n'est tenté. Le reste — choix du backend, bus,
    collection — tourne dans un fil démon borné à `timeout` secondes : un
    bus qui ne répond pas rend `mail_service_keyring_timeout` au lieu de
    figer l'appelant. Toute autre panne du bus rend
    `mail_service_keyring_no_bus`.
    """
    if not env.get("DBUS_SESSION_BUS_ADDRESS"):
        try:
            present = _user_bus_socket().exists()
        except OSError:
            present = False
        if not present:
            return "mail_service_keyring_no_bus"
    result = []

    def probe() -> None:
        try:
            result.append(_probe_keyring())
        except Exception as exc:
            _logger.info("sonde du trousseau : %s", type(exc).__name__)
            result.append("mail_service_keyring_no_bus")

    thread = threading.Thread(
        target=probe, name="erplibre-keyring-probe", daemon=True
    )
    thread.start()
    thread.join(timeout)
    if not result:
        return "mail_service_keyring_timeout"
    return result[0]


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
    """Lecture et écriture de secrets, par référence.

    Toute écriture dans le kdbx passe par `kdbx_write.writing` : verrou
    partagé entre processus, relecture du disque, écriture atomique. Un
    autre processus qui écrit le coffre au même moment ne perd donc rien.

    `keyring_guard`, posé par le service seulement, est appelé avant tout
    appel au trousseau : une chaîne non vide est la clé i18n d'un refus,
    levé en `SecretError` sans toucher au backend.
    """

    def __init__(self, kdbx_manager=None, use_keyring: bool = True) -> None:
        self._kdbx_manager = kdbx_manager
        self._use_keyring = use_keyring
        self.keyring_guard: Callable[[], str] | None = None

    # -- API publique ---------------------------------------------------

    def available_backends(self) -> list[str]:
        found = []
        if self._kdbx_manager is not None:
            found.append("kdbx")
        if self._use_keyring and keyring_is_safe():
            found.append("keyring")
        return found

    def get(self, ref: str, *, fresh: bool = False) -> str | None:
        """Le secret de `ref`, None s'il n'existe pas.

        `fresh=True` relit le kdbx sur le disque s'il a changé depuis son
        dernier chargement (identité du fichier), et seulement alors : un
        fichier inchangé ne coûte aucune dérivation de clé. Ignoré pour le
        trousseau, qui n'a pas de copie en mémoire.
        """
        scheme, path = self._parse(ref)
        if scheme == "kdbx":
            kp = self._kdbx()
            with kdbx_write.kp_lock(kp):
                if fresh:
                    self._reload_if_changed(kp)
                entry = self._kdbx_entry(kp, path, create=False)
                return entry.password if entry else None
        return self._keyring_call("get_password", path)

    def set(self, ref: str, secret: str) -> None:
        scheme, path = self._parse(ref)
        if scheme == "kdbx":
            with self._writing() as write:
                entry = self._kdbx_entry(write.kp, path, create=True)
                entry.password = secret
            return
        self._keyring_call("set_password", path, secret)

    def delete(self, ref: str) -> None:
        scheme, path = self._parse(ref)
        if scheme == "kdbx":
            with self._writing() as write:
                entry = self._kdbx_entry(write.kp, path, create=False)
                if entry:
                    write.kp.delete_entry(entry)
                else:
                    write.skip()
            return
        self._keyring_call("delete_password", path)

    def update(
        self, ref: str, change: Callable[[str | None], str | None]
    ) -> str | None:
        """Lit, transforme et écrit un secret d'un seul tenant ; rend la
        valeur gardée. `change` reçoit la valeur courante et rend la
        nouvelle, ou None pour garder la courante ; il tourne verrou tenu
        et ne fait pas de réseau.

        kdbx : lecture et écriture sous le verrou du coffre, après
        relecture ; rien n'est écrit si la valeur ne change pas ou si
        `change` lève. Trousseau : lecture puis écriture, sans verrou entre
        processus (le trousseau n'en offre pas).
        """
        scheme, path = self._parse(ref)
        if scheme == "kdbx":
            with self._writing() as write:
                entry = self._kdbx_entry(write.kp, path, create=False)
                current = entry.password if entry else None
                new = change(current)
                if new is None or new == current:
                    write.skip()
                    return current
                if entry is None:
                    entry = self._kdbx_entry(write.kp, path, create=True)
                entry.password = new
            return new
        current = self._keyring_call("get_password", path)
        new = change(current)
        if new is None or new == current:
            return current
        self._keyring_call("set_password", path, new)
        return new

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

    @contextlib.contextmanager
    def _writing(self):
        """`kdbx_write.writing` sur le coffre ; un coffre occupé trop
        longtemps par un autre processus devient une `SecretError`."""
        try:
            with kdbx_write.writing(
                self._kdbx(), wait=kdbx_write.KDBX_LOCK_WAIT_S
            ) as write:
                yield write
        except kdbx_write.KdbxBusy as exc:
            raise SecretError(t("mail_err_kdbx_busy")) from exc

    @staticmethod
    def _reload_if_changed(kp) -> None:
        """Relit `kp` si son fichier n'est plus celui qu'il reflète, ou si
        on ne sait pas lequel il reflète (base ouverte ailleurs).

        Comparaison, relecture et identité retenue se font sous le verrou
        de `kp` : une écriture d'un autre fil (`kdbx_write.writing`) ne
        s'intercale pas entre elles.
        """
        path = kdbx_write.disk_path(kp)
        if path is None:
            return
        with kdbx_write.kp_lock(kp):
            identity = kdbx_write.file_identity(path)
            loaded = kdbx_write.loaded_identity(kp)
            if identity is not None and identity == loaded:
                return
            kp.reload()
            kdbx_write.note_loaded(kp, identity)

    @staticmethod
    def _kdbx_entry(kp, path: str, create: bool):
        """`path` = "Groupe/SousGroupe/Titre". Crée les groupes au besoin."""
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
        if self.keyring_guard is not None:
            problem = self.keyring_guard()
            if problem:
                raise SecretError(t(problem))
        if not keyring_is_safe():
            raise SecretError(
                f"{t('mail_err_keyring_plaintext')}"
                f" {keyring_backend_name() or 'absent'})."
                f" {t('mail_err_keyring_plaintext_hint')}"
            )
        import keyring

        return getattr(keyring, func_name)(KEYRING_SERVICE, *args)
