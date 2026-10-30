#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Écrire le coffre KeePass sans perdre l'écriture d'un autre processus.

Le client, le menu et le service ouvrent chacun le même kdbx. Chacun garde
en mémoire la base telle qu'il l'a lue ; sans précaution, le dernier qui
enregistre efface ce que les autres ont écrit entre-temps. `writing` sert
toute écriture : verrou exclusif, relecture du disque, modification,
écriture atomique, verrou rendu.

Le verrou vit dans `~/.erplibre/locks/`, et non à côté du coffre : le
coffre par défaut est dans un dossier versionné, où un fichier de verrou
voisin apparaîtrait dans `git status`. Il est nommé d'après le chemin RÉEL
du coffre : deux écritures du même fichier, par un chemin relatif, absolu
ou un lien, prennent le même verrou.

Le verrou est consultatif : un éditeur externe (KeePassXC) ne le prend
pas. La relecture sous verrou réduit la fenêtre sans la fermer.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import logging
import os
import tempfile
import threading
import weakref
from collections.abc import Iterator
from pathlib import Path

from script.todo.mail.rules.lock import file_lock
from script.todo.todo_i18n import t

_logger = logging.getLogger(__name__)

# Le verrou du coffre n'est tenu que le temps d'une relecture et d'une
# écriture sur le disque, une ou deux dérivations de clé.
KDBX_LOCK_WAIT_S = 10.0
# Le rafraîchissement d'un jeton OAuth fait du réseau sous son verrou :
# l'attente couvre le délai de l'échange (`oauth.DELAI_SECONDES`, 30 s)
# plus une marge. Valeur recopiée, `oauth` étant hors de ce module.
REFRESH_LOCK_WAIT_S = 35.0

TMP_SUFFIX = ".tmp.kdbx"

# Identité du fichier que reflète chaque base ouverte, prise à sa dernière
# lecture ou écriture. Clé faible : une base fermée sort de la table.
_LOADED: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()

# Verrou de chaque base ouverte, entre les fils d'un même processus. Une
# relecture remplace l'arbre en mémoire : faite par un fil pendant qu'un
# autre modifie puis enregistre, elle rend la mémoire et l'identité
# retenue discordantes, et une lecture fraîche ne relit plus le disque.
_KP_LOCKS: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
_KP_LOCKS_GUARD = threading.Lock()
# Pour un objet sans référence faible possible : un verrou commun.
_SHARED_KP_LOCK = threading.RLock()


class KdbxBusy(Exception):
    """Un autre processus écrit le coffre depuis plus que l'attente permise."""


def _locks_dir() -> Path:
    """`~/.erplibre/locks`, créé en 0700 au besoin."""
    directory = Path.home() / ".erplibre" / "locks"
    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    return directory


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "surrogateescape")).hexdigest()


def lock_path_for(kdbx_path) -> Path:
    """Le fichier de verrou du coffre `kdbx_path`, commun à toutes ses
    écritures quel que soit le chemin donné."""
    real = os.path.realpath(os.path.expanduser(os.fspath(kdbx_path)))
    return _locks_dir() / f"kdbx-{_digest(real)[:16]}.lock"


def refresh_lock_path(ref: str) -> Path:
    """Le fichier de verrou du rafraîchissement OAuth de la référence
    `ref`, distinct de celui du coffre : le réseau, qui se fait sous ce
    verrou, ne bloque jamais une autre écriture du coffre."""
    return _locks_dir() / f"oauth-{_digest(ref)[:16]}.lock"


@contextlib.contextmanager
def write_lock(kdbx_path, *, wait: float = KDBX_LOCK_WAIT_S) -> Iterator[None]:
    """Tient le verrou d'écriture du coffre ; `KdbxBusy` après `wait`
    secondes sans l'obtenir."""
    with file_lock(lock_path_for(kdbx_path), wait=wait) as held:
        if not held:
            raise KdbxBusy(t("mail_err_kdbx_busy"))
        yield


@contextlib.contextmanager
def refresh_lock(
    ref: str, *, wait: float = REFRESH_LOCK_WAIT_S
) -> Iterator[None]:
    """Tient le verrou de rafraîchissement OAuth de `ref` ; `KdbxBusy`
    après `wait` secondes sans l'obtenir."""
    with file_lock(refresh_lock_path(ref), wait=wait) as held:
        if not held:
            raise KdbxBusy(t("mail_err_kdbx_busy"))
        yield


def kp_lock(kp) -> threading.RLock:
    """Le verrou réentrant de `kp` dans ce processus, créé au besoin.

    `writing` le tient de la relecture à l'enregistrement ; toute
    relecture faite hors de `writing` le prend aussi.
    """
    with _KP_LOCKS_GUARD:
        try:
            lock = _KP_LOCKS.get(kp)
            if lock is None:
                lock = _KP_LOCKS[kp] = threading.RLock()
        except TypeError:
            return _SHARED_KP_LOCK
        return lock


def file_identity(path) -> tuple[int, int] | None:
    """(inode, mtime en ns) du fichier, lien suivi ; None s'il manque.

    Une écriture atomique remplace le fichier : l'inode change, et la date
    de modification avec lui.
    """
    try:
        info = os.stat(path)
    except (OSError, TypeError, ValueError):
        return None
    return (info.st_ino, info.st_mtime_ns)


def disk_path(kp) -> str | None:
    """Le chemin du fichier qu'écrit `kp`, None pour un flux ou un double.

    Même partage que `PyKeePass.save` : ce qui a une méthode `read` est un
    flux, pas un chemin. Un double de test (`MagicMock`) en a une, et
    garde ainsi l'enregistrement simple.
    """
    filename = getattr(kp, "filename", None)
    if not isinstance(filename, (str, os.PathLike)):
        return None
    if hasattr(filename, "read"):
        return None
    path = os.fspath(filename)
    return path if isinstance(path, str) and path else None


def note_loaded(kp, identity=None) -> None:
    """Retient que `kp` reflète le fichier d'identité `identity` (celle du
    fichier à cet instant si elle n'est pas donnée)."""
    if identity is None:
        path = disk_path(kp)
        identity = file_identity(path) if path else None
    try:
        if identity is None:
            _LOADED.pop(kp, None)
        else:
            _LOADED[kp] = identity
    except TypeError:
        # Objet sans référence faible possible : rien n'est retenu, et la
        # prochaine lecture fraîche relira le disque.
        pass


def loaded_identity(kp) -> tuple[int, int] | None:
    """L'identité retenue pour `kp`, None si elle est inconnue."""
    try:
        return _LOADED.get(kp)
    except TypeError:
        return None


def _fsync_dir(directory: str) -> None:
    with contextlib.suppress(OSError):
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def save_atomic(kp, path=None) -> None:
    """Écrit `kp` dans `path` (son propre fichier par défaut) d'un coup.

    La base est construite en mémoire, écrite dans un temporaire 0600 du
    même dossier, synchronisée, puis renommée sur la cible : un lecteur
    voit l'ancien coffre ou le nouveau, jamais un fichier tronqué, et le
    coffre reste en 0600 quel que soit l'umask. Un lien symbolique est
    écrit À TRAVERS : la cible change, le lien reste un lien. Le
    temporaire est retiré sur toute exception.
    """
    target = os.path.realpath(os.fspath(path or kp.filename))
    buffer = io.BytesIO()
    kp.save(buffer)
    data = buffer.getvalue()
    directory, name = os.path.split(target)
    fd, tmp = tempfile.mkstemp(
        dir=directory, prefix=f".{name}.", suffix=TMP_SUFFIX
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    _fsync_dir(directory)


def _remove_orphans(target: str) -> None:
    """Retire les temporaires `.<nom>.*.tmp.kdbx` laissés par un écrivain
    tué avant son renommage ; chacun est une copie complète du coffre.
    Appelé verrou tenu : aucun autre écrivain n'a de temporaire en cours."""
    directory, name = os.path.split(target)
    prefix = f".{name}."
    try:
        names = os.listdir(directory or ".")
    except OSError:
        return
    for other in names:
        if not (other.startswith(prefix) and other.endswith(TMP_SUFFIX)):
            continue
        try:
            os.unlink(os.path.join(directory, other))
        except FileNotFoundError:
            pass
        except OSError as exc:
            _logger.info(
                "temporaire du coffre non retiré (%s)", type(exc).__name__
            )


class _Write:
    """Ce que reçoit le bloc de `writing` : la base relue, à modifier."""

    def __init__(self, kp) -> None:
        self.kp = kp
        self.skipped = False

    def skip(self) -> None:
        """Rien à écrire : le coffre n'est pas réenregistré en sortie."""
        self.skipped = True


@contextlib.contextmanager
def writing(kp, *, wait: float = KDBX_LOCK_WAIT_S) -> Iterator[_Write]:
    """Modifier `kp` et l'écrire sans écraser un autre processus.

    Verrou du coffre → retrait des temporaires orphelins → relecture du
    disque → bloc → écriture atomique → verrou rendu. Le bloc cherche ses
    entrées APRÈS la relecture, dans `w.kp` : une entrée trouvée avant
    appartient à l'arbre remplacé. Rien n'est écrit si le bloc lève ou
    appelle `skip()`. `KdbxBusy` si le verrou ne vient pas en `wait`
    secondes. Le verrou de `kp` dans le processus (`kp_lock`) est pris
    avant celui du coffre : un autre fil du même processus ne relit pas
    `kp` entre la relecture et l'écriture.

    Un `kp` sans chemin de fichier (flux, double de test) n'a ni verrou ni
    relecture : le bloc puis `kp.save()`.
    """
    path = disk_path(kp)
    if path is None:
        write = _Write(kp)
        yield write
        if not write.skipped:
            kp.save()
        return
    target = os.path.realpath(path)
    with kp_lock(kp), write_lock(path, wait=wait):
        _remove_orphans(target)
        identity = file_identity(target)
        kp.reload()
        note_loaded(kp, identity)
        write = _Write(kp)
        yield write
        if not write.skipped:
            save_atomic(kp, path)
            note_loaded(kp, file_identity(target))
