#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce que le hub sait du terminal d'une session, sans le deviner du texte.

`TtyWatch(maître, pid)` suit le PTY d'une session dont le worker, meneur
de sa session Unix, a le pid `pid` :

- `probe()` rend un `TtyState` : `echo` et `canon`, les drapeaux ECHO et
  ICANON de l'esclave (sous Linux, tcgetattr sur le maître rend ceux de
  l'esclave) ; `reader`, vrai quand un processus de la session attend une
  entrée du terminal, faux sinon, None quand /proc ne permet pas de le
  savoir ; `altscreen`, l'écran alternatif ; `signals`, les caractères
  que le noyau change en signal (Ctrl+C, Ctrl+\\, Ctrl+Z) ;
- `feed(octets)` suit l'écran alternatif dans la sortie, à travers les
  coupures entre deux morceaux.

Les processus de la session sont le worker et ses descendants, lus dans
`/proc/<pid>/task/*/children`. L'un d'eux attend le terminal quand un de
ses fils d'exécution est bloqué (`/proc/<pid>/task/<tid>/syscall`) dans
un appel de lecture ou d'attente qui vise l'esclave ou `/dev/tty` : read,
readv et splice nomment le descripteur en premier argument ; select et
pselect6 le portent dans leur ensemble de lecture, poll et ppoll dans
leur tableau, lus dans `/proc/<pid>/mem` ; epoll dans
`/proc/<pid>/fdinfo/<epfd>`. Un processus setuid (sudo, su), ou hors de
portée de ptrace, refuse ces fichiers : le lecteur devient inconnu, comme
sur une architecture absente de SYSCALLS.
"""

import os
import platform
import re
import select
import stat
import struct
import termios
from typing import NamedTuple

# Appels système qui attendent une entrée, par architecture : « fd » nomme
# le descripteur en premier argument, « select » le passe dans un ensemble
# de bits, « poll » dans un tableau de pollfd, « epoll » par une instance
# epoll. aarch64 suit la table générique du noyau, sans select ni poll.
SYSCALLS = {
    "x86_64": {
        "fd": {0, 19, 275},  # read, readv, splice
        "select": {23, 270},  # select, pselect6
        "poll": {7, 271},  # poll, ppoll
        "epoll": {232, 281, 441},  # epoll_wait, epoll_pwait, epoll_pwait2
    },
    "aarch64": {
        "fd": {63, 65, 76},
        "select": {72},
        "poll": {73},
        "epoll": {22, 441},
    },
}
MACHINE = platform.machine()
# /dev/tty : le terminal de contrôle de qui l'ouvre.
DEV_TTY = os.makedev(5, 0)
# Au-delà, un ensemble ou un tableau n'est pas lu : il vient d'un
# programme qui surveille des milliers de descripteurs, pas d'une invite.
FD_LIMIT = 1024
# Écran alternatif : ESC[?1049h/l, ESC[?1047h/l, ESC[?47h/l ; RIS (ESC c)
# remet le terminal à zéro, écran principal compris.
ALTSCREEN = re.compile(rb"\x1b\[\?(?:1049|1047|47)([hl])|\x1bc")
# Octets gardés d'un morceau au suivant : la plus longue séquence, moins
# un. Relire une séquence déjà vue redonne le même état.
TAIL = len(b"\x1b[?1049h") - 1


class TtyState(NamedTuple):
    echo: bool
    canon: bool
    reader: bool | None
    altscreen: bool
    signals: bytes


def children(pid) -> list:
    """Pids des enfants de `pid` ; aucun si /proc ne les donne pas."""
    found = []
    try:
        tids = os.listdir(f"/proc/{pid}/task")
    except OSError:
        return found
    for tid in tids:
        try:
            with open(f"/proc/{pid}/task/{tid}/children", "rb") as f:
                found.extend(int(child) for child in f.read().split())
        except OSError:
            continue
    return found


def descendants(pid) -> list:
    """`pid` puis ses descendants encore en vie."""
    found, pending = [], [pid]
    while pending:
        current = pending.pop()
        found.append(current)
        pending.extend(children(current))
    return found


def _syscall(pid, tid) -> list:
    """Champs de `/proc/<pid>/task/<tid>/syscall` : le numéro de l'appel
    en cours et ses six arguments, « running » en plein calcul, « -1 »
    hors appel. PermissionError pour un processus hors de portée."""
    with open(f"/proc/{pid}/task/{tid}/syscall", "rb") as f:
        return f.read().split()


def _peek(pid, address, size) -> bytes:
    """`size` octets de la mémoire du processus `pid` à `address` ; le même
    droit que `syscall` ouvre `mem`. OSError si elle ne se lit pas."""
    fd = os.open(f"/proc/{pid}/mem", os.O_RDONLY | os.O_CLOEXEC)
    try:
        data = os.pread(fd, size, address)
    finally:
        os.close(fd)
    if len(data) < size:
        raise OSError(f"short read at {address:#x}")
    return data


def _epoll_fds(pid, epfd) -> list:
    """Descripteurs qu'une instance epoll surveille en lecture, lus dans
    fdinfo : lignes « tfd: <fd> events: <masque hexadécimal> … »."""
    fds = []
    with open(f"/proc/{pid}/fdinfo/{epfd}") as f:
        for line in f:
            fields = line.split()
            if fields[:1] == ["tfd:"] and int(fields[3], 16) & select.EPOLLIN:
                fds.append(int(fields[1]))
    return fds


class TtyWatch:
    """État du terminal d'une session : voir le module."""

    def __init__(self, master, pid):
        self.master = master
        self.pid = pid
        self.tty = os.stat(os.ptsname(master)).st_rdev
        self.calls = SYSCALLS.get(MACHINE)
        self.altscreen = False
        self.tail = b""

    def feed(self, data: bytes) -> None:
        """Suit l'écran alternatif dans `data`, la suite de la sortie."""
        text = self.tail + data
        for match in ALTSCREEN.finditer(text):
            self.altscreen = match.group(1) == b"h"
        self.tail = text[-TAIL:]

    def probe(self) -> TtyState:
        """L'état du terminal à cet instant."""
        attrs = termios.tcgetattr(self.master)
        lflag, cc = attrs[3], attrs[6]
        signals = b""
        if lflag & termios.ISIG:
            chars = (cc[termios.VINTR], cc[termios.VQUIT], cc[termios.VSUSP])
            # Un caractère nul est désactivé (_POSIX_VDISABLE).
            signals = b"".join(c for c in chars if c != b"\0")
        return TtyState(
            echo=bool(lflag & termios.ECHO),
            canon=bool(lflag & termios.ICANON),
            reader=self.reader(),
            altscreen=self.altscreen,
            signals=signals,
        )

    def reader(self) -> bool | None:
        """Vrai si un processus de la session attend le terminal ; None si
        aucun ne l'attend et que l'un d'eux ne se laisse pas lire, ou si
        l'architecture n'a pas de table."""
        if self.calls is None:
            return None
        unknown = False
        for pid in descendants(self.pid):
            try:
                if self._waits(pid):
                    return True
            except PermissionError:
                unknown = True
            except OSError:
                continue  # fini entre-temps
        return None if unknown else False

    def _waits(self, pid) -> bool:
        for tid in os.listdir(f"/proc/{pid}/task"):
            fields = _syscall(pid, tid)
            if not fields or not fields[0].isdigit():
                continue
            number = int(fields[0])
            args = [int(field, 16) for field in fields[1:7]]
            for fd in self._fds(pid, number, args):
                if self._is_tty(pid, fd):
                    return True
        return False

    def _fds(self, pid, number, args) -> list:
        """Descripteurs dont l'appel `number` attend une entrée."""
        calls = self.calls
        if number in calls["fd"]:
            return [args[0]]
        if number in calls["select"]:
            count, readfds = args[0], args[1]
            if not readfds or not 0 < count <= FD_LIMIT:
                return []
            bits = _peek(pid, readfds, (count + 7) // 8)
            return [fd for fd in range(count) if bits[fd // 8] >> fd % 8 & 1]
        if number in calls["poll"]:
            entries, count = args[0], args[1]
            if not entries or not 0 < count <= FD_LIMIT:
                return []
            data = _peek(pid, entries, 8 * count)
            return [
                fd
                for fd, events, _ in struct.iter_unpack("ihh", data)
                if events & select.POLLIN
            ]
        if number in calls["epoll"]:
            return _epoll_fds(pid, args[0])
        return []

    def _is_tty(self, pid, fd) -> bool:
        """Vrai si le descripteur `fd` du processus désigne l'esclave ou
        /dev/tty."""
        try:
            st = os.stat(f"/proc/{pid}/fd/{fd}")
        except FileNotFoundError:
            return False
        return stat.S_ISCHR(st.st_mode) and st.st_rdev in (self.tty, DEV_TTY)
