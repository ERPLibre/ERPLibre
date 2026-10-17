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
porte « PID programme départ » du détenteur, départ étant l'instant de
départ de son processus (champ 22 de /proc/<pid>/stat), qui distingue un
PID repris de celui qui a écrit ; un texte sans ce troisième champ se lit
encore. Le fichier reste en place après le détenteur, et seul le flock dit
si le deck est pris.

Lancé en commande, le module tient le verrou pour un jeu, que la passation
(erplibre_home_handover.sh) lance ainsi :

    python3 deck_lock.py game <commande> [arguments…]

Le verrou est pris au nom de « game », la commande tourne en enfant et le
module sort avec son code, 128 + N quand un signal N l'a tuée, comme bash.
Le descripteur du verrou passe à la commande (pass_fds), et de là à tout
processus qu'elle lance sans fermer ses descripteurs : le deck reste pris
tant qu'un processus du jeu vit, même si l'enveloppe est tuée, et un
service relancé trop tôt sort en 2 au lieu de se superposer au jeu.

Un programme du deck lancé sous la commande tient le verrou par le
descripteur hérité. S'il ne l'a pas hérité (un subprocess python ferme les
descripteurs), il trouve son ancêtre au nom de « game » dans le verrou,
tourne sous ce verrou, et un fil attend de le reprendre à son nom : le deck
reste pris s'il survit au jeu. L'ancêtre n'est reconnu que si son instant
de départ est celui du texte : une enveloppe morte dont un ancêtre a repris
le PID n'ouvre pas le deck. Par le descripteur hérité, le texte n'est
jamais réécrit : il nomme encore « game » et le PID de l'enveloppe quand
seul ce programme tient le deck, et holder_pids() nomme les vrais
détenteurs.

Tout processus d'un jeu passe ce verrou : un programme du deck qui y tourne
prend en plus, sans attendre, un second flock sur deck.inner, à côté du
verrou. Le suivant, dans le même jeu, le trouve tenu et sort en BUSY_EXIT
en nommant le premier. deck.inner part avec son programme (son descripteur
ne passe pas à un exec) ; hors jeu, il n'est jamais lu, et l'enveloppe
lancée dans un jeu ne le prend pas.

Bibliothèque standard seulement : TODO la charge hors du venv du deck, et
la passation la lance sous le python3 du système.
"""

import fcntl
import os
import re
import select
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time

BUSY_EXIT = 2
# Le tiler sort en NO_DECK_EXIT quand aucun Stream Deck à écran n'est
# branché (un autre périphérique Elgato passe ExecCondition) ; comme
# BUSY_EXIT, l'unité ne le relance pas.
NO_DECK_EXIT = 3
LOCK_NAME = "deck.lock"
# Le verrou qui écarte un second programme du deck dans un même jeu, posé
# à côté de LOCK_NAME.
INNER_NAME = "deck.inner"
# Le nom sous lequel la passation tient le verrou pendant un jeu.
HANDOVER_PROGRAM = "game"

# Les fichiers verrouillés par ce processus : les garder ouverts garde le
# verrou jusqu'à la sortie.
_held = []


class DeckBusy(Exception):
    """Le verrou est tenu ailleurs ; `holder` vaut (pid, programme, départ),
    voir parse_holder."""

    def __init__(self, holder):
        super().__init__(
            "Stream Deck in use by %s (PID %s)" % (holder[1], holder[0])
        )
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
    """(pid, programme, départ) lus dans le texte du verrou, en chaînes. Le
    PID n'est gardé que fait de chiffres, le programme que fait de lettres,
    de chiffres, de « _ » et de « - » ; « ? » sinon, et pour ce qui manque.
    Le départ, troisième champ facultatif, vaut None quand il manque (un
    texte écrit sans lui), « ? » quand il n'est pas fait de chiffres : il
    ne concorde alors avec aucun processus. Status affiche ces mots et la
    diagnostic en tire « kill <pid> » : aucun texte arbitraire n'y passe."""
    mots = texte.split()
    depart = None
    if len(mots) > 2:
        depart = mots[2] if re.fullmatch(r"[0-9]{1,20}", mots[2]) else "?"
    mots += ["?", "?"]
    pid = mots[0] if re.fullmatch(r"[0-9]{1,10}", mots[0]) else "?"
    programme = (
        mots[1] if re.fullmatch(r"[A-Za-z0-9_-]{1,32}", mots[1]) else "?"
    )
    return pid, programme, depart


def _stat_fields(pid, proc="/proc"):
    """Les champs de <proc>/<pid>/stat après la dernière « ) » (le nom de
    commande peut en porter) : l'état d'abord (champ 3), l'instant de
    départ à l'index 19 (champ 22). None quand le fichier ne se lit pas."""
    try:
        with open(
            os.path.join(proc, str(pid), "stat"),
            encoding="utf-8",
            errors="replace",
        ) as fh:
            return fh.read().rsplit(")", 1)[1].split()
    except (OSError, IndexError):
        return None


def _start_time(pid, proc="/proc"):
    """L'instant de départ de `pid` (champ 22 de /proc/<pid>/stat, en tops
    d'horloge depuis le démarrage), en chaîne, ou None. Un PID repris par un
    autre processus en a un autre."""
    champs = _stat_fields(pid, proc)
    return champs[19] if champs and len(champs) > 19 else None


def holder_running(tenu, proc="/proc"):
    """Vrai quand le PID que nomme `tenu` (parse_holder) désigne encore le
    processus qui a écrit le texte : il vit, n'est pas un zombie, et son
    instant de départ est celui du texte quand le texte en porte un. Faux
    pour un PID « ? »."""
    pid, _programme, depart = tenu
    if pid == "?":
        return False
    champs = _stat_fields(pid, proc)
    if not champs or champs[0] in ("Z", "X"):
        return False
    return depart is None or (len(champs) > 19 and champs[19] == depart)


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


def _write_holder(fh, program):
    """Écrit « PID programme départ » de ce processus dans `fh`, sans le
    départ quand /proc ne le donne pas."""
    texte = "%d %s" % (os.getpid(), program)
    depart = _start_time(os.getpid())
    if depart is not None:
        texte += " " + depart
    fh.seek(0)
    fh.truncate()
    fh.write(texte + "\n")
    fh.flush()


def _game_ancestor(tenu):
    """Vrai quand `tenu` (parse_holder) nomme « game » et un ancêtre de ce
    processus, qui a l'instant de départ du texte quand le texte en porte
    un : un PID d'enveloppe morte repris par un ancêtre ne compte pas."""
    pid, programme, depart = tenu
    if programme != HANDOVER_PROGRAM or pid == "?":
        return False
    if int(pid) not in _ancestors():
        return False
    return depart is None or depart == _start_time(int(pid))


def _hold_inner(program, path):
    """Dans un jeu, prend deck.inner (INNER_NAME, à côté de `path`) pour
    `program` sans attendre, et le garde jusqu'à la sortie du processus.
    Lève DeckBusy en nommant le programme du deck qui le tient déjà dans ce
    jeu. L'enveloppe (HANDOVER_PROGRAM) n'en prend pas : le programme du
    deck qu'elle lance le prend. Le descripteur, comme tout descripteur
    ouvert par python, ne passe pas à un exec : un enfant du programme ne
    garde pas deck.inner après lui."""
    if program == HANDOVER_PROGRAM:
        return
    fh = _open_private(os.path.join(os.path.dirname(path), INNER_NAME))
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        tenu = parse_holder(fh.read())
        fh.close()
        raise DeckBusy(tenu) from None
    _write_holder(fh, program)
    _held.append(fh)


def _inherited(path, exclu):
    """Un descripteur de ce processus ouvert sur le verrou `path`, hérité
    d'un ancêtre, et qui le tient : flock sur une description de fichier
    qui tient déjà le verrou réussit. None sinon. Les descripteurs que ce
    processus a pris lui-même (_held) ne comptent pas : deux acquire() d'un
    même processus s'excluent. `exclu`, le descripteur que l'appelant vient
    d'ouvrir, ne compte pas non plus : sur un verrou devenu libre, son
    flock réussirait."""
    try:
        cible = os.stat(path, follow_symlinks=False)
        noms = os.listdir("/proc/self/fd")
    except OSError:
        return None
    propres = {fh.fileno() for fh in _held if not fh.closed} | {exclu}
    for nom in noms:
        fd = int(nom)
        if fd in propres:
            continue
        try:
            etat = os.fstat(fd)
        except OSError:
            continue
        if not stat.S_ISREG(etat.st_mode) or (etat.st_dev, etat.st_ino) != (
            cible.st_dev,
            cible.st_ino,
        ):
            continue
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            continue
        return fd
    return None


def _take_over(fh, program):
    """Un fil démon bloque sur le verrou par `fh` et, dès que le jeu le
    rend, l'écrit au nom de ce processus, qu'il tient jusqu'à sa sortie."""

    def attendre():
        fcntl.flock(fh, fcntl.LOCK_EX)
        _write_holder(fh, program)

    _held.append(fh)
    threading.Thread(target=attendre, name="deck-lock", daemon=True).start()


def acquire(program, path=None):
    """Prend le verrou pour `program` et le garde jusqu'à la sortie du
    processus. Rend le fichier ouvert, ou None quand un ancêtre le tient au
    nom de HANDOVER_PROGRAM.

    Le verrou déjà tenu l'est pour ce processus dans deux cas, sans texte
    réécrit : un descripteur hérité du jeu le tient (_inherited), et le
    fichier rendu est ce descripteur ; ou un ancêtre le tient au nom de
    « game » (_game_ancestor) sans que le descripteur ait été hérité, et
    _take_over le reprend à la fin du jeu. Dans ces deux cas, deck.inner
    (_hold_inner) écarte un second programme du deck du même jeu. Un
    détenteur parti entre le premier essai et cette recherche laisse le
    verrou libre : un second essai le prend. Lève DeckBusy quand un autre
    processus le tient, OSError quand le dossier ou le fichier n'est pas
    privé (voir _open_private)."""
    path = path or lock_path()
    fh = _open_private(path)
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        tenu = parse_holder(fh.read())
        herite = _inherited(path, fh.fileno())
        if herite is not None:
            fh.close()
            _hold_inner(program, path)
            fh = os.fdopen(herite, "r+", encoding="utf-8")
            _held.append(fh)
            return fh
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if _game_ancestor(tenu):
                try:
                    _hold_inner(program, path)
                except BaseException:
                    fh.close()
                    raise
                _take_over(fh, program)
                return None
            fh.close()
            raise DeckBusy(tenu) from None
    _write_holder(fh, program)
    _held.append(fh)
    return fh


def acquire_or_exit(program, path=None):
    """acquire(), ou une ligne sur la sortie d'erreur qui nomme le
    détenteur et une sortie en BUSY_EXIT."""
    try:
        return acquire(program, path)
    except DeckBusy as busy:
        pid, detenteur, _depart = busy.holder
        print(
            "Stream Deck in use by %s (PID %s); close it first."
            % (detenteur, pid),
            file=sys.stderr,
        )
        sys.exit(BUSY_EXIT)


def holder(path=None):
    """(pid, programme, départ) du détenteur (voir parse_holder), ou None
    quand le verrou est libre, n'a jamais été pris, ou que son dossier n'est
    pas privé. Sonde par un flock non bloquant aussitôt rendu. L'ouverture est
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


def holder_pids(path=None, proc="/proc"):
    """Les PID, triés, des processus de ce compte qui ont le verrou ouvert :
    le détenteur, ou, pour un jeu, l'enveloppe et chaque processus du jeu
    qui en a hérité. Les processus d'un autre compte ne se lisent pas et
    sont omis. Le lien /proc/<pid>/fd/<n> est comparé au chemin réel du
    verrou, sans ouvrir ce qu'il désigne."""
    path = os.path.realpath(path or lock_path())
    pids = []
    for nom in os.listdir(proc):
        if not nom.isdigit():
            continue
        dossier = os.path.join(proc, nom, "fd")
        try:
            fds = os.listdir(dossier)
        except OSError:
            continue
        for fd in fds:
            try:
                if os.readlink(os.path.join(dossier, fd)) == path:
                    pids.append(int(nom))
                    break
            except OSError:
                continue
    return sorted(pids)


def exit_on_sigterm():
    """SIGTERM (systemctl stop, kill) lève SystemExit(128 + SIGTERM) dans le
    fil principal au lieu de tuer le processus sur place : les finally qui
    remettent le deck à zéro et les fonctions atexit passent. Un second
    SIGTERM est ignoré, pour ne pas interrompre ce nettoyage."""

    def sortir(signum, _frame):
        signal.signal(signum, signal.SIG_IGN)
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, sortir)


def process_table(proc="/proc"):
    """{pid: (ppid, pgrp, tpgid, état)} des processus lisibles sous `proc`,
    lus dans <pid>/stat après la dernière « ) » (le nom de commande peut en
    porter). tpgid est le groupe au premier plan du terminal du processus,
    -1 sans terminal. Un processus parti pendant la lecture est omis."""
    table = {}
    for nom in os.listdir(proc):
        if not nom.isdigit():
            continue
        try:
            with open(
                os.path.join(proc, nom, "stat"),
                encoding="utf-8",
                errors="replace",
            ) as fh:
                champs = fh.read().rsplit(")", 1)[1].split()
            table[int(nom)] = (
                int(champs[1]),
                int(champs[2]),
                int(champs[5]),
                champs[0],
            )
        except (OSError, IndexError, ValueError):
            continue
    return table


def signal_targets(signum, root, table):
    """Les PID à qui passer `signum` reçu par `root` : ses descendants dans
    `table` (process_table), zombies exclus. Pour SIGINT, ceux qui sont au
    premier plan de leur terminal (pgrp == tpgid) sont épargnés : un Ctrl-C
    les a déjà frappés, et un second SIGINT couperait leur nettoyage."""
    enfants = {}
    for pid, (ppid, _pgrp, _tpgid, _etat) in table.items():
        enfants.setdefault(ppid, []).append(pid)
    cibles = []
    vus = {root}
    a_voir = list(enfants.get(root, ()))
    while a_voir:
        pid = a_voir.pop()
        if pid in vus:
            continue
        vus.add(pid)
        a_voir.extend(enfants.get(pid, ()))
        _ppid, pgrp, tpgid, etat = table[pid]
        if etat in ("Z", "X"):
            continue
        if signum == signal.SIGINT and pgrp == tpgid:
            continue
        cibles.append(pid)
    return sorted(cibles)


def _alive(pid):
    try:
        with open("/proc/%d/stat" % pid, encoding="utf-8") as fh:
            return fh.read().rsplit(")", 1)[1].split()[0] not in ("Z", "X")
    except (OSError, IndexError):
        return False


def _pidfd(pid):
    """Un pidfd sur `pid` (Linux 5.3, Python 3.9), qui le désigne même si
    son PID est repris ; None où il n'existe pas : l'attente lit alors
    /proc. Lève ProcessLookupError quand `pid` est déjà parti."""
    try:
        return os.pidfd_open(pid)
    except (AttributeError, PermissionError):
        return None
    except OSError as err:
        if isinstance(err, ProcessLookupError):
            raise
        return None


def _send(pid, pidfd, signum):
    """Envoie `signum` à `pid` par son pidfd quand il existe : un PID repris
    entre la lecture de /proc et l'envoi ne reçoit rien. Lève
    ProcessLookupError quand le processus est parti."""
    if pidfd is None:
        os.kill(pid, signum)
    else:
        signal.pidfd_send_signal(pidfd, signum)


def _wait_gone(attendus):
    """Attend la fin de chaque processus de `attendus` ({pid: pidfd|None}),
    que le gestionnaire de signal peut agrandir pendant l'attente."""
    while attendus:
        pid, pidfd = attendus.popitem()
        if pidfd is None:
            while _alive(pid):
                time.sleep(0.1)
            continue
        try:
            select.select([pidfd], [], [])
        finally:
            os.close(pidfd)


def run(program, argv, path=None):
    """Lance `argv` en tenant le verrou au nom de `program` jusqu'à sa fin.
    Rend le code de la commande, 128 + N quand le signal N l'a tuée ;
    BUSY_EXIT sans rien lancer quand le deck est pris, 1 quand le verrou ne
    s'ouvre pas, 127 ou 126 quand la commande manque ou ne s'exécute pas.

    Le descripteur du verrou passe à la commande : le deck reste pris tant
    qu'un processus du jeu le garde ouvert, après la fin du module compris.

    SIGTERM et SIGINT sont passés à TOUS les descendants du module
    (signal_targets), sauf, pour SIGINT, ceux au premier plan du terminal,
    que le Ctrl-C a déjà frappés ; puis le module attend leur fin avant de
    sortir : un jeu lancé sous un shell (la boucle de la galerie) est un
    petit-enfant, qu'un shell non interactif tué ne prévient pas. Un
    descendant arrêté (état T) reçoit aussi SIGCONT, sans quoi le signal
    resterait en suspens et l'attente sans fin. La commande reste dans
    le groupe de processus du module : un jeu interactif garde le premier
    plan du terminal, ses Ctrl-C et ses lectures. SIGHUP ne fait rien : venu
    du terminal, il frappe le jeu lui-même. Les gestionnaires sont des
    fonctions et non SIG_IGN, si bien que la commande les reçoit à leur
    défaut. Un signal reçu avant que la commande existe lui est passé dès
    son lancement."""
    try:
        fh = acquire(program, path)
    except DeckBusy as busy:
        pid, detenteur, _depart = busy.holder
        print(
            "Stream Deck in use by %s (PID %s); close it first."
            % (detenteur, pid),
            file=sys.stderr,
        )
        return BUSY_EXIT
    except OSError as err:
        print("Stream Deck lock: %s" % err, file=sys.stderr)
        return 1
    lance = []
    en_attente = []
    attendus = {}

    def faire_suivre(signum):
        table = process_table()
        for pid in signal_targets(signum, os.getpid(), table):
            try:
                if pid not in attendus:
                    attendus[pid] = _pidfd(pid)
                _send(pid, attendus[pid], signum)
                if table[pid][3] == "T":
                    _send(pid, attendus[pid], signal.SIGCONT)
            except ProcessLookupError:
                continue

    def recevoir(signum, _frame):
        if signum == signal.SIGHUP:
            return
        if lance:
            faire_suivre(signum)
        else:
            en_attente.append(signum)

    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, recevoir)
    try:
        enfant = subprocess.Popen(
            argv, pass_fds=() if fh is None else (fh.fileno(),)
        )
    except OSError as err:
        print("%s: %s" % (argv[0], err.strerror), file=sys.stderr)
        return 126 if isinstance(err, PermissionError) else 127
    lance.append(enfant)
    for signum in en_attente:
        faire_suivre(signum)
    code = enfant.wait()
    _wait_gone(attendus)
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
