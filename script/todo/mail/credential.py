#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le mot de passe maître du coffre, transmis au service par systemd.

L'unité du service déclare `LoadCredentialEncrypted=` : systemd déchiffre le
fichier au démarrage et le dépose dans `$CREDENTIALS_DIRECTORY`, un dossier
privé au processus, effacé à sa sortie. Ce module lit ce dépôt, et nulle
part ailleurs : ni variable d'environnement, ni argument de ligne de
commande, que d'autres processus du même compte pourraient lire.

Il écrit aussi ce fichier chiffré : `systemd-creds --user encrypt` reçoit
le clair par l'entrée standard et rend le chiffré par la sortie standard,
que ce module écrit en 0600. Le clair ne touche jamais le disque ni la
ligne de commande. Un credential chiffré pour l'utilisateur protège d'une
copie du disque seulement : tout programme lancé sous le même compte peut
le déchiffrer sans rien demander.

Le dossier `credstore.encrypted` est celui que cherche le gestionnaire
systemd de l'utilisateur : sous SON dossier de configuration, lu dans
`systemctl --user show -p UnitPath`, et non dans l'environnement du
shell, qui peut différer du sien.

Chaque fonction qui lance un programme prend `run` (signature de
`subprocess.run`), résolu à l'appel : un test qui remplace
`subprocess.run` intercepte aussi l'appel qu'il aurait oublié de doubler.
"""

from __future__ import annotations

import contextlib
import hmac
import os
import re
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path

from script.todo.todo_i18n import t

CREDENTIAL_ID = "erplibre-mail-kdbx"
CREDSTORE_NAME = "credstore.encrypted"
# `systemd-creds --user` (chiffrement pour l'utilisateur, sans privilège)
# existe depuis systemd 256.
SYSTEMD_CREDS_MIN = 256
CREDS_TIMEOUT_S = 30
# Délai des lectures d'état de systemctl, en secondes.
SYSTEMCTL_TIMEOUT_S = 3
# Longueur gardée de la sortie d'erreur de systemd-creds dans un message.
STDERR_MAX = 200
# Un mot de passe maître tient en quelques dizaines d'octets ; au-delà, le
# fichier n'est pas celui qu'on attend et n'est pas lu en mémoire.
CREDENTIAL_MAX_BYTES = 4096


def read_master_password(env: Mapping[str, str] = os.environ) -> str | None:
    """Le mot de passe maître passé par systemd, ou None.

    None quand `$CREDENTIALS_DIRECTORY` manque ou est vide, et quand le
    fichier `CREDENTIAL_ID` y est absent, illisible, vide, plus gros que
    `CREDENTIAL_MAX_BYTES` ou hors UTF-8. Un seul saut de ligne final est
    retiré : celui qu'ajoute un fichier écrit par `echo`.
    """
    directory = env.get("CREDENTIALS_DIRECTORY") or ""
    if not directory:
        return None
    path = Path(directory) / CREDENTIAL_ID
    try:
        with open(path, "rb") as handle:
            data = handle.read(CREDENTIAL_MAX_BYTES + 1)
    except OSError:
        return None
    if not data or len(data) > CREDENTIAL_MAX_BYTES:
        return None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if text.endswith("\n"):
        text = text[:-1]
    return text or None


class CredentialError(Exception):
    """Le mot de passe maître n'a pas pu être chiffré pour le service.
    Message pour l'humain, sans le mot de passe."""


def _runner(run: Callable | None) -> Callable:
    return run if run is not None else subprocess.run


def manager_config_home(*, run: Callable | None = None) -> Path:
    """Le dossier de configuration du gestionnaire systemd de
    l'utilisateur ; `~/.config` à défaut.

    La première entrée de `UnitPath` de la forme `<X>/systemd/user` située
    sous le dossier personnel donne `<X>` : les entrées qui la précèdent
    (`user.control`, `transient`) ne finissent pas ainsi, et celle de
    `$XDG_DATA_HOME` vient après. Ni `XDG_CONFIG_HOME` du shell ni
    `show-environment`, qui rend l'environnement transmis aux unités et
    non celui du gestionnaire.
    """
    home = Path.home()
    fallback = home / ".config"
    try:
        result = _runner(run)(
            ["systemctl", "--user", "show", "-p", "UnitPath", "--value"],
            capture_output=True,
            text=True,
            timeout=SYSTEMCTL_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return fallback
    if getattr(result, "returncode", 1) != 0:
        return fallback
    for entry in str(result.stdout or "").split():
        path = Path(entry)
        if not path.is_absolute() or path.parts[-2:] != ("systemd", "user"):
            continue
        config = path.parent.parent
        if config.is_relative_to(home):
            return config
    return fallback


def credstore_dir(*, run: Callable | None = None) -> Path:
    """Le dossier des credentials chiffrés de l'utilisateur."""
    return manager_config_home(run=run) / CREDSTORE_NAME


def credential_path(*, run: Callable | None = None) -> Path:
    """Le fichier chiffré du mot de passe maître du coffre."""
    return credstore_dir(run=run) / CREDENTIAL_ID


def user_scope_supported(*, run: Callable | None = None) -> bool:
    """Vrai si systemd (256 ou plus) chiffre un credential pour
    l'utilisateur (`systemd-creds --user`). Faux si un programme manque,
    échoue ou dépasse son délai."""
    runner = _runner(run)
    try:
        version = runner(
            ["systemctl", "--version"],
            capture_output=True,
            text=True,
            timeout=SYSTEMCTL_TIMEOUT_S,
        )
        found = re.search(r"systemd\s+(\d+)", str(version.stdout or ""))
        if not found or int(found.group(1)) < SYSTEMD_CREDS_MIN:
            return False
        aide = runner(
            ["systemd-creds", "--help"],
            capture_output=True,
            text=True,
            timeout=SYSTEMCTL_TIMEOUT_S,
        )
        return "--user" in str(aide.stdout or "")
    except (OSError, subprocess.SubprocessError, ValueError):
        return False


def _clean_stderr(stderr, password: str) -> str:
    """La sortie d'erreur d'un programme, sans le mot de passe, sur une
    ligne et `STDERR_MAX` caractères au plus."""
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", "replace")
    text = str(stderr or "")
    if password:
        text = text.replace(password, "***")
    text = " ".join(text.split())
    return text[:STDERR_MAX]


def _write_private(dest: Path, data: bytes) -> None:
    """Écrit `data` dans `dest` d'un coup, en 0600, dans un dossier 0700.

    Le temporaire naît en 0600 (`mkstemp`) dans le dossier de `dest`, est
    synchronisé puis renommé ; il est retiré sur toute exception.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(dest.parent, 0o700)
    fd, tmp = tempfile.mkstemp(
        dir=dest.parent, prefix=f".{dest.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, dest)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    os.chmod(dest, 0o600)


def encrypt_master_password(
    password: str, dest: Path, *, run: Callable | None = None
) -> None:
    """Chiffre `password` pour le gestionnaire systemd de l'utilisateur
    et l'écrit dans `dest` (0600, dossier 0700).

    Le clair passe par l'entrée standard de `systemd-creds`, jamais par
    ses arguments ni son environnement ; le chiffré revient par sa sortie
    standard. Un refus lève `CredentialError` avec la sortie d'erreur
    nettoyée, et rien n'est écrit.
    """
    try:
        result = _runner(run)(
            [
                "systemd-creds",
                "--user",
                "encrypt",
                f"--name={CREDENTIAL_ID}",
                "-",
                "-",
            ],
            input=password.encode("utf-8"),
            capture_output=True,
            timeout=CREDS_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CredentialError(
            f"{t('mail_service_creds_failed')} {type(exc).__name__}"
        ) from None
    if result.returncode != 0 or not result.stdout:
        detail = _clean_stderr(result.stderr, password)
        raise CredentialError(
            f"{t('mail_service_creds_failed')} {detail}".rstrip()
        )
    _write_private(Path(dest), bytes(result.stdout))


def _decrypts_to(
    dest: Path, password: str, *, run: Callable | None = None
) -> bool:
    """Vrai si le gestionnaire de l'utilisateur relit `dest` en
    `password` ; la sortie passe par un tube, jamais par le disque."""
    try:
        result = _runner(run)(
            [
                "systemd-creds",
                "--user",
                "decrypt",
                f"--name={CREDENTIAL_ID}",
                "--newline=no",
                str(dest),
                "-",
            ],
            capture_output=True,
            timeout=CREDS_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if result.returncode != 0 or not isinstance(result.stdout, bytes):
        return False
    return hmac.compare_digest(result.stdout, password.encode("utf-8"))


def setup_credential(
    password: str,
    *,
    kdbx_path: str,
    dest: Path,
    run: Callable | None = None,
) -> Path:
    """Vérifie `password` sur le coffre, le chiffre dans `dest`, puis
    prouve que le gestionnaire saura le relire ; rend `dest`.

    Un mot de passe que le coffre refuse n'écrit rien. Un fichier qui ne
    se relit pas est retiré avant que l'erreur ne remonte.
    """
    try:
        from pykeepass import PyKeePass
        from pykeepass.exceptions import CredentialsError
    except ModuleNotFoundError:
        raise CredentialError(t("mail_service_vault_no_pykeepass")) from None
    try:
        PyKeePass(os.path.expanduser(kdbx_path), password=password)
    except CredentialsError:
        raise CredentialError(t("mail_service_creds_wrong")) from None
    except Exception as exc:
        raise CredentialError(
            f"{t('mail_service_vault_unreadable')} ({type(exc).__name__})"
        ) from None
    dest = Path(dest)
    encrypt_master_password(password, dest, run=run)
    if not _decrypts_to(dest, password, run=run):
        remove_credential(dest)
        raise CredentialError(t("mail_service_creds_verify_failed"))
    return dest


def remove_credential(dest: Path) -> bool:
    """Supprime le fichier chiffré ; vrai s'il y en avait un."""
    try:
        os.unlink(dest)
    except FileNotFoundError:
        return False
    return True
