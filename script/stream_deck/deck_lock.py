#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Verrou du Stream Deck : un seul programme du deck à la fois.

Deux programmes qui ouvrent le même périphérique HID se disputent ses
touches et son écran sans qu'aucun ne le dise. Chaque programme du deck
prend ce verrou au démarrage ; le second sort en BUSY_EXIT (2) en nommant
le premier.

Le verrou est un fcntl.flock exclusif sur $XDG_RUNTIME_DIR/erplibre-home/
deck.lock. flock appartient à la description de fichier ouverte : il tient
tant que le fichier reste ouvert, donc jusqu'à la fin du processus, et deux
open() du même fichier, même dans un seul processus, s'excluent. Le fichier
porte « PID programme » du détenteur ; il reste en place après lui, et seul
le flock dit si le deck est pris.

Bibliothèque standard seulement : TODO la charge hors du venv du deck.
"""

import fcntl
import os
import stat
import sys
import tempfile

BUSY_EXIT = 2
LOCK_NAME = "deck.lock"

# Les fichiers verrouillés par ce processus : les garder ouverts garde le
# verrou jusqu'à la sortie.
_held = []


class DeckBusy(Exception):
    """Le verrou est tenu ailleurs ; `holder` vaut (pid, programme)."""

    def __init__(self, holder):
        super().__init__("Stream Deck in use by %s (PID %s)" % holder[::-1])
        self.holder = holder


def lock_path(environ=None):
    """Le chemin du verrou : sous $XDG_RUNTIME_DIR/erplibre-home, ou, sans
    lui (une connexion sans session), sous le répertoire temporaire du
    système, dans un dossier propre à l'uid."""
    environ = os.environ if environ is None else environ
    runtime = environ.get("XDG_RUNTIME_DIR")
    if runtime:
        dossier = os.path.join(runtime, "erplibre-home")
    else:
        dossier = os.path.join(
            tempfile.gettempdir(), "erplibre-home-%d" % os.getuid()
        )
    return os.path.join(dossier, LOCK_NAME)


def read_holder(path):
    """(pid, programme) écrits dans le verrou, en chaînes ; « ? » pour ce
    qui manque ou ne se lit pas."""
    try:
        with open(path, encoding="utf-8") as fh:
            mots = fh.read().split()
    except OSError:
        mots = []
    mots += ["?", "?"]
    return mots[0], mots[1]


def _open_private(path):
    """Ouvre `path` en lecture-écriture, créé en 0600 dans un dossier créé
    en 0700. Le dossier doit appartenir à l'uid courant et rester fermé aux
    autres comptes, et `path` ne doit pas être un lien symbolique : sous le
    répertoire temporaire commun, un autre compte pourrait sinon poser le
    dossier, ou un lien vers un fichier que la troncature viderait. Lève
    OSError sinon."""
    dossier = os.path.dirname(path)
    os.makedirs(dossier, mode=0o700, exist_ok=True)
    etat = os.lstat(dossier)
    if (
        not stat.S_ISDIR(etat.st_mode)
        or etat.st_uid != os.getuid()
        or etat.st_mode & 0o077
    ):
        raise PermissionError("%s: not a private directory" % dossier)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    return os.fdopen(fd, "r+", encoding="utf-8")


def acquire(program, path=None):
    """Prend le verrou pour `program` et le garde jusqu'à la sortie du
    processus. Rend le fichier ouvert ; lève DeckBusy quand une autre
    description de fichier le tient, OSError quand le dossier ou le
    fichier n'est pas privé (voir _open_private)."""
    path = path or lock_path()
    fh = _open_private(path)
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fh.close()
        raise DeckBusy(read_holder(path)) from None
    fh.seek(0)
    fh.truncate()
    fh.write("%d %s\n" % (os.getpid(), program))
    fh.flush()
    _held.append(fh)
    return fh


def acquire_or_exit(program, path=None):
    """acquire(), ou une ligne sur la sortie d'erreur qui nomme le
    détenteur et une sortie en BUSY_EXIT."""
    try:
        return acquire(program, path)
    except DeckBusy as busy:
        pid, detenteur = busy.holder
        print(
            "Stream Deck in use by %s (PID %s); close it first."
            % (detenteur, pid),
            file=sys.stderr,
        )
        sys.exit(BUSY_EXIT)


def holder(path=None):
    """(pid, programme) du détenteur, ou None quand le verrou est libre ou
    n'a jamais été pris. Sonde par un flock non bloquant aussitôt rendu."""
    path = path or lock_path()
    try:
        fh = open(path, encoding="utf-8")
    except OSError:
        return None
    with fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            return read_holder(path)
        fcntl.flock(fh, fcntl.LOCK_UN)
    return None
