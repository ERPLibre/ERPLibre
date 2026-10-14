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

Lancé en commande, le module tient le verrou pour un jeu, que la passation
(erplibre_home_handover.sh) lance ainsi :

    python3 deck_lock.py game <commande> [arguments…]

Le verrou est pris au nom de « game », la commande tourne en enfant et le
module sort avec son code, 128 + N quand un signal N l'a tuée, comme bash.
Le descripteur du verrou n'est pas héritable (PEP 446) : un enfant que le
jeu laisse derrière lui ne garde pas le deck. Un programme du deck lancé
sous la commande, directement ou par un shell, trouve son ancêtre au nom de
« game » dans le verrou et tourne sous ce verrou au lieu de sortir en 2.

Bibliothèque standard seulement : TODO la charge hors du venv du deck, et
la passation la lance sous le python3 du système.
"""

import fcntl
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile

BUSY_EXIT = 2
# Le tiler sort en NO_DECK_EXIT quand aucun Stream Deck à écran n'est
# branché (un autre périphérique Elgato passe ExecCondition) ; comme
# BUSY_EXIT, l'unité ne le relance pas.
NO_DECK_EXIT = 3
LOCK_NAME = "deck.lock"
# Le nom sous lequel la passation tient le verrou pendant un jeu.
HANDOVER_PROGRAM = "game"

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


def parse_holder(texte):
    """(pid, programme) lus dans le texte du verrou, en chaînes. Le PID
    n'est gardé que fait de chiffres, le programme que fait de lettres, de
    chiffres, de « _ » et de « - » ; « ? » sinon, et pour ce qui manque.
    Status affiche ces deux mots et la diagnostic en tire « kill <pid> » :
    aucun texte arbitraire n'y passe."""
    mots = texte.split() + ["?", "?"]
    pid = mots[0] if re.fullmatch(r"[0-9]{1,10}", mots[0]) else "?"
    programme = (
        mots[1] if re.fullmatch(r"[A-Za-z0-9_-]{1,32}", mots[1]) else "?"
    )
    return pid, programme


def _check_private_dir(dossier):
    """Lève PermissionError (une OSError) si `dossier` n'est pas un
    dossier de l'uid courant fermé aux autres comptes : sous le répertoire
    temporaire commun, un autre compte pourrait l'avoir posé."""
    etat = os.lstat(dossier)
    if (
        not stat.S_ISDIR(etat.st_mode)
        or etat.st_uid != os.getuid()
        or etat.st_mode & 0o077
    ):
        raise PermissionError("%s: not a private directory" % dossier)


def _open_private(path):
    """Ouvre `path` en lecture-écriture, créé en 0600 dans un dossier créé
    en 0700. Le dossier doit être privé (_check_private_dir) et `path` ne
    doit pas être un lien symbolique, qu'une troncature suivrait jusqu'à un
    autre fichier. Lève OSError sinon."""
    dossier = os.path.dirname(path)
    os.makedirs(dossier, mode=0o700, exist_ok=True)
    _check_private_dir(dossier)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    return os.fdopen(fd, "r+", encoding="utf-8")


def _ancestors():
    """Les PID des ancêtres de ce processus, du parent vers init, lus dans
    /proc/<pid>/stat ; la liste s'arrête à la première lecture impossible.
    Le nom de commande, entre parenthèses, peut porter des espaces : le
    PID du parent est le deuxième champ après la dernière « ) »."""
    pid = os.getppid()
    ancetres = []
    while pid > 1 and len(ancetres) < 256:
        ancetres.append(pid)
        try:
            with open("/proc/%d/stat" % pid, encoding="utf-8") as fh:
                pid = int(fh.read().rsplit(")", 1)[1].split()[1])
        except (OSError, IndexError, ValueError):
            break
    return ancetres


def acquire(program, path=None):
    """Prend le verrou pour `program` et le garde jusqu'à la sortie du
    processus. Rend le fichier ouvert, ou None quand un ancêtre le tient au
    nom de HANDOVER_PROGRAM : la passation tient alors le deck pour ce
    processus, qui tourne sous ce verrou. Lève DeckBusy quand un autre
    processus le tient, OSError quand le dossier ou le fichier n'est pas
    privé (voir _open_private)."""
    path = path or lock_path()
    fh = _open_private(path)
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        tenu = parse_holder(fh.read())
        fh.close()
        if tenu[1] == HANDOVER_PROGRAM and tenu[0] != "?":
            if int(tenu[0]) in _ancestors():
                return None
        raise DeckBusy(tenu) from None
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
    """(pid, programme) du détenteur (voir parse_holder), ou None quand le
    verrou est libre, n'a jamais été pris, ou que son dossier n'est pas
    privé. Sonde par un flock non bloquant aussitôt rendu. L'ouverture est
    non bloquante et seul un fichier ordinaire est lu : une FIFO posée à sa
    place ne fige pas Status."""
    path = path or lock_path()
    try:
        _check_private_dir(os.path.dirname(path))
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    with os.fdopen(fd, "r", encoding="utf-8", errors="replace") as fh:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        try:
            fcntl.flock(fh, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            return parse_holder(fh.read())
        fcntl.flock(fh, fcntl.LOCK_UN)
    return None


def exit_on_sigterm():
    """SIGTERM (systemctl stop, kill) lève SystemExit(128 + SIGTERM) dans le
    fil principal au lieu de tuer le processus sur place : les finally qui
    remettent le deck à zéro et les fonctions atexit passent. Un second
    SIGTERM est ignoré, pour ne pas interrompre ce nettoyage."""

    def sortir(signum, _frame):
        signal.signal(signum, signal.SIG_IGN)
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, sortir)


def run(program, argv, path=None):
    """Lance `argv` en tenant le verrou au nom de `program` jusqu'à sa fin.
    Rend le code de la commande, 128 + N quand le signal N l'a tuée ;
    BUSY_EXIT sans rien lancer quand le deck est pris, 1 quand le verrou ne
    s'ouvre pas, 127 ou 126 quand la commande manque ou ne s'exécute pas.

    SIGINT et SIGHUP ne font rien ici : venus du terminal, ils frappent
    tout le groupe, donc la commande aussi, et le module attend sa fin.
    SIGTERM est passé à la commande : « kill <pid> » sur le PID que le
    verrou nomme termine le jeu. Les gestionnaires sont des fonctions et
    non SIG_IGN, si bien que la commande les reçoit à leur défaut."""
    try:
        acquire(program, path)
    except DeckBusy as busy:
        pid, detenteur = busy.holder
        print(
            "Stream Deck in use by %s (PID %s); close it first."
            % (detenteur, pid),
            file=sys.stderr,
        )
        return BUSY_EXIT
    except OSError as err:
        print("Stream Deck lock: %s" % err, file=sys.stderr)
        return 1
    enfant = []

    def recevoir(signum, _frame):
        if signum == signal.SIGTERM and enfant:
            enfant[0].send_signal(signum)

    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, recevoir)
    try:
        enfant.append(subprocess.Popen(argv))
    except OSError as err:
        print("%s: %s" % (argv[0], err.strerror), file=sys.stderr)
        return 126 if isinstance(err, PermissionError) else 127
    code = enfant[0].wait()
    return 128 - code if code < 0 else code


def main(argv):
    """deck_lock.py <programme> <commande> [arguments…] ; voir run()."""
    if len(argv) < 2:
        print(
            "usage: deck_lock.py <program> <command> [arguments…]",
            file=sys.stderr,
        )
        return 1
    return run(argv[0], argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
