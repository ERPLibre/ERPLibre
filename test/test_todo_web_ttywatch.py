#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""TtyWatch : l'état du terminal d'une session, lu sur le maître et dans
/proc, et ce qu'une session en fait : `tty_state` au client, frappes
filtrées, file d'entrée vidée devant une invite de secret, collage passé
une ligne à la fois.

Chaque enfant est un `python -c` jetable sur un PTY neuf, dont il fait son
terminal de contrôle ; aucun test ne lance TODO. Le client est un double
qui date ce qu'il reçoit.
"""

import asyncio
import builtins
import fcntl
import os
import pty
import signal
import struct
import subprocess
import sys
import termios
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from script.todo.web import sessions, ttywatch

REPO = Path(__file__).resolve().parent.parent
# Prend le PTY comme terminal de contrôle : /dev/tty le désigne ensuite.
CTTY = "import fcntl, termios; fcntl.ioctl(0, termios.TIOCSCTTY, 0)\n"

# Enfants qui disent « ready » puis attendent une entrée du terminal.
READERS = {
    "read": "import os; print('ready', flush=True); os.read(0, 10)",
    "input": "print('ready', flush=True); input()",
    "getpass": "import getpass; print('ready'); getpass.getpass('pw: ')",
    "select": "import select, sys; print('ready', flush=True)\n"
    "select.select([sys.stdin], [], [], 30)",
    "poll": "import select; p = select.poll(); p.register(0, select.POLLIN)\n"
    "print('ready', flush=True); p.poll(30000)",
    "epoll": "import selectors; s = selectors.DefaultSelector()\n"
    "s.register(0, selectors.EVENT_READ); print('ready', flush=True)\n"
    "s.select(30)",
    "readline": "import readline; print('ready', flush=True); input('> ')",
    "thread": "import os, threading, time\n"
    "threading.Thread(target=os.read, args=(0, 10), daemon=True).start()\n"
    "print('ready', flush=True); time.sleep(30)",
    "grandchild": "import subprocess, sys\n"
    "subprocess.run([sys.executable, '-c',"
    " 'import os; print(\"ready\", flush=True); os.read(0, 10)'])",
}

# Enfants qui disent « ready » puis attendent autre chose que le terminal.
WAITERS = {
    "sleep": "import time; print('ready', flush=True); time.sleep(30)",
    "select": "import select, socket; a, b = socket.socketpair()\n"
    "print('ready', flush=True); select.select([a], [], [], 30)",
    "poll": "import select; p = select.poll(); p.register(1, select.POLLPRI)\n"
    "print('ready', flush=True); p.poll(30000)",
    "epoll": "import selectors, socket; a, b = socket.socketpair()\n"
    "s = selectors.DefaultSelector(); s.register(a, selectors.EVENT_READ)\n"
    "print('ready', flush=True); s.select(30)",
    "child": "import subprocess; print('ready', flush=True)\n"
    "subprocess.run(['sleep', '30'])",
    "zombie": "import subprocess, time; p = subprocess.Popen(['true'])\n"
    "print('ready', flush=True); time.sleep(30)",
}


# Invite de mot de passe après une première ligne, puis une ligne encore.
SECRET = r"""
import getpass
print("ready", flush=True)
input()
print("length", len(getpass.getpass("pw: ")), flush=True)
input()
"""

READ_THEN_SLEEP = r"""
import time
print("ready", flush=True)
input()
print("sleeping", flush=True)
time.sleep(30)
"""

# ESC[?1049h en deux écritures, puis ESC[?1049l après une ligne.
ALTSCREEN = r"""
import sys, time
sys.stdout.write("\x1b[?10")
sys.stdout.flush()
time.sleep(0.2)
sys.stdout.write("49h")
sys.stdout.flush()
input()
sys.stdout.write("\x1b[?1049l")
sys.stdout.flush()
input()
"""

FULL_SCREEN = r"""
import sys, time
sys.stdout.write("\x1b[?1049h")
sys.stdout.flush()
time.sleep(30)
"""

# Coupe l'écho au bout d'une demi-seconde, sans rien écrire.
SILENT = r"""
import termios, time
print("ready", flush=True)
time.sleep(0.5)
attrs = termios.tcgetattr(0)
attrs[3] &= ~termios.ECHO
termios.tcsetattr(0, termios.TCSANOW, attrs)
time.sleep(30)
"""

# Lit une touche à la fois hors du mode canonique, comme un éditeur de
# ligne (PyREPL, readline), et calcule 5 ms sur chacune avant de relire.
BUSY = r"""
import os, time, tty
tty.setcbreak(0)
print("ready", flush=True)
while True:
    key = os.read(0, 1)
    os.write(1, b"<" + key + b">")
    end = time.perf_counter() + 0.005
    while time.perf_counter() < end:
        pass
"""

# Lit une ligne, calcule 5 ms, puis coupe l'écho sans vider la file
# (TCSANOW) et lit le secret.
BUSY_THEN_SECRET = r"""
import termios, time
print("ready", flush=True)
input()
end = time.perf_counter() + 0.005
while time.perf_counter() < end:
    pass
attrs = termios.tcgetattr(0)
attrs[3] &= ~termios.ECHO
termios.tcsetattr(0, termios.TCSANOW, attrs)
print("secret was", repr(input()), flush=True)
"""

# 8 Mo de sortie d'un coup, en lignes de 4 Ko.
FLOOD = r"""
import os
print("ready", flush=True)
input()
for _ in range(2000):
    os.write(1, b"x" * 4000 + b"\n")
print("END", flush=True)
input()
"""

# Coupe l'écho sans vider la file (TCSANOW), puis lit ce qui y reste.
TYPEAHEAD = r"""
import os, select, termios, time
print("ready", flush=True)
input()
attrs = termios.tcgetattr(0)
attrs[3] &= ~termios.ECHO
termios.tcsetattr(0, termios.TCSANOW, attrs)
print("pw: ", end="", flush=True)
time.sleep(0.5)
ready = select.select([0], [], [], 0.5)[0]
print("got", os.read(0, 100) if ready else b"nothing", flush=True)
"""

# Lit une ligne, coupe l'écho SANS vider l'entrée et lit aussitôt : aucune
# sonde ne devance ce « mot de passe ».
IMMEDIATE_SECRET = r"""
import termios
print("ready", flush=True)
input()
attrs = termios.tcgetattr(0)
attrs[3] &= ~termios.ECHO
termios.tcsetattr(0, termios.TCSANOW, attrs)
print("secret was", repr(input("pw: ")), flush=True)
"""

THREE_LINES = r"""
print("ready", flush=True)
for _ in range(3):
    print("got", input(), flush=True)
"""

# Trois lignes, un tiers de seconde de sommeil après chacune : pendant ce
# temps, rien ne lit le terminal.
SLOW_LINES = r"""
import time
print("ready", flush=True)
for _ in range(3):
    print("got", input(), flush=True)
    time.sleep(0.3)
"""

# Deux questions du port du worker, puis deux lignes lues sans question,
# comme par un programme que TODO lance lui-même.
PORT_QUESTIONS = r"""
import os, sys
sys.path.insert(0, %r)
from script.todo.ui import pipe_port
port = pipe_port.PipePort(int(os.environ["TODO_WEB_FD"]), 0)
first = port.ask("Q1: ")
print("answers", repr(first), repr(port.ask("Q2: ")), flush=True)
print("got", repr(input()), repr(input()), flush=True)
"""


def asked(session):
    """Le texte de la question que la session tient ouverte, ou None."""
    return session.asking["text"] if session.asking is not None else None


def dropped(client) -> list:
    """`(taille, raison)` des `dropped` que `client` a reçus, dans
    l'ordre."""
    return [
        (m["bytes"], m["reason"])
        for _, m in client.events
        if m["t"] == "dropped"
    ]


def queued(fd) -> int:
    """Octets que l'esclave `fd` tient prêts à lire."""
    return struct.unpack("i", fcntl.ioctl(fd, termios.FIONREAD, b"\0" * 4))[0]


class Child:
    """Un `python -c` sur un PTY neuf ; `output` garde ce qu'il écrit."""

    def __init__(self, test, code):
        self.master, slave = pty.openpty()
        self.proc = subprocess.Popen(
            [sys.executable, "-c", CTTY + code],
            stdin=slave,
            stdout=slave,
            stderr=slave,
            start_new_session=True,
        )
        os.close(slave)
        os.set_blocking(self.master, False)
        self.output = b""
        test.addCleanup(self.stop)
        self.watch = ttywatch.TtyWatch(self.master, self.proc.pid)

    def stop(self):
        if self.proc.poll() is None:
            os.killpg(self.proc.pid, signal.SIGKILL)
        self.proc.wait()
        os.close(self.master)

    def read(self):
        try:
            self.output += os.read(self.master, 65536)
        except (BlockingIOError, OSError):
            pass

    def until(self, predicate, timeout=10.0):
        deadline = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() > deadline:
                raise AssertionError(f"still waiting: {self.output[-200:]!r}")
            time.sleep(0.01)
            self.read()

    def blocked(self) -> bool:
        """Vrai quand chaque processus vivant de l'enfant est bloqué dans un
        appel système."""
        for pid in ttywatch.descendants(self.proc.pid):
            if ttywatch._ended(pid):
                continue
            for tid in os.listdir(f"/proc/{pid}/task"):
                if not ttywatch._syscall(pid, tid)[0].isdigit():
                    return False
        return True


class TestTerminalModes(unittest.TestCase):
    def test_the_master_reads_the_modes_of_the_slave(self):
        master, slave = pty.openpty()
        self.addCleanup(os.close, master)
        self.addCleanup(os.close, slave)
        watch = ttywatch.TtyWatch(master, os.getpid())
        state = watch.probe()
        self.assertEqual((state.echo, state.canon), (True, True))
        self.assertEqual(state.signals, b"\x03\x1c\x1a")
        attrs = termios.tcgetattr(slave)
        attrs[3] &= ~(termios.ECHO | termios.ICANON | termios.ISIG)
        termios.tcsetattr(slave, termios.TCSANOW, attrs)
        state = watch.probe()
        self.assertEqual((state.echo, state.canon), (False, False))
        self.assertEqual(state.signals, b"")

    def test_a_closed_master_makes_the_reader_unknown(self):
        # Un terminal ordinaire : l'écho actif garde le champ masqué fermé.
        master, slave = pty.openpty()
        watch = ttywatch.TtyWatch(master, os.getpid())
        os.close(master)
        os.close(slave)
        self.assertEqual(watch.probe(), (True, True, None, False, b""))

    def test_a_disabled_signal_character_is_left_out(self):
        # _POSIX_VDISABLE : un caractère nul ne devient aucun signal.
        master, slave = pty.openpty()
        self.addCleanup(os.close, master)
        self.addCleanup(os.close, slave)
        attrs = termios.tcgetattr(slave)
        attrs[6][termios.VQUIT] = b"\0"
        termios.tcsetattr(slave, termios.TCSANOW, attrs)
        watch = ttywatch.TtyWatch(master, os.getpid())
        self.assertEqual(watch.probe().signals, b"\x03\x1a")

    def test_a_password_prompt_turns_the_echo_off(self):
        child = Child(self, READERS["getpass"])
        child.until(lambda: b"pw: " in child.output)
        state = child.watch.probe()
        self.assertEqual((state.echo, state.canon), (False, True))

    def test_password_text_with_the_echo_on_keeps_the_echo(self):
        child = Child(self, "input('[sudo] password for x: ')")
        child.until(lambda: b"password for x: " in child.output)
        child.until(lambda: child.watch.probe().reader)
        self.assertIs(child.watch.probe().echo, True)


class TestReader(unittest.TestCase):
    def test_a_child_waiting_on_the_terminal_is_a_reader(self):
        for name, code in READERS.items():
            with self.subTest(name):
                child = Child(self, code)
                child.until(lambda: b"ready" in child.output)
                child.until(lambda: child.watch.probe().reader)

    def test_a_child_waiting_on_anything_else_is_not(self):
        for name, code in WAITERS.items():
            with self.subTest(name):
                child = Child(self, code)
                child.until(lambda: b"ready" in child.output)
                child.until(child.blocked)
                self.assertIs(child.watch.probe().reader, False)

    def test_a_process_out_of_reach_makes_the_reader_unknown(self):
        child = Child(self, WAITERS["child"])
        child.until(lambda: b"ready" in child.output)
        child.until(lambda: len(ttywatch.descendants(child.proc.pid)) == 2)
        child.until(child.blocked)
        [_, sleeper] = ttywatch.descendants(child.proc.pid)
        original = ttywatch._syscall
        # setuid ; noyau sans le fichier syscall.
        for error in (PermissionError(13, "setuid"), FileNotFoundError(2, "")):
            with self.subTest(error=error):

                def refused(pid, tid):
                    if pid == sleeper:
                        raise error
                    return original(pid, tid)

                with patch.object(ttywatch, "_syscall", refused):
                    self.assertIsNone(child.watch.probe().reader)

    def test_a_process_denied_even_in_stat_makes_the_reader_unknown(self):
        # hidepid, ProtectProc : /proc/<pid>/stat refuse aussi la lecture,
        # comme le reste ; le vivant reste inconnu, jamais fini.
        child = Child(self, WAITERS["child"])
        child.until(lambda: b"ready" in child.output)
        child.until(lambda: len(ttywatch.descendants(child.proc.pid)) == 2)
        child.until(child.blocked)
        [_, sleeper] = ttywatch.descendants(child.proc.pid)
        original_elf64 = ttywatch._elf64
        original_open = builtins.open

        def elf64_refused(pid):
            if pid == sleeper:
                raise PermissionError(13, "ptrace")
            return original_elf64(pid)

        def stat_refused(path, *args, **kwargs):
            if path == f"/proc/{sleeper}/stat":
                raise PermissionError(13, "hidepid")
            return original_open(path, *args, **kwargs)

        with patch.object(ttywatch, "_elf64", elf64_refused):
            with patch.object(builtins, "open", stat_refused):
                self.assertIsNone(child.watch.probe().reader)

    def test_a_reader_is_found_beside_a_process_out_of_reach(self):
        child = Child(self, READERS["grandchild"])
        child.until(lambda: b"ready" in child.output)
        child.until(lambda: child.watch.probe().reader)
        original = ttywatch._syscall

        def refused(pid, tid):
            if pid == child.proc.pid:
                raise PermissionError(13, "setuid")
            return original(pid, tid)

        with patch.object(ttywatch, "_syscall", refused):
            self.assertIs(child.watch.probe().reader, True)

    def test_what_proc_cannot_say_makes_the_reader_unknown(self):
        # fdinfo d'un format inconnu ; programme 32 bits, d'une autre table.
        for name, code, mock in (
            ("_epoll_fds", READERS["epoll"], {"side_effect": ValueError()}),
            ("_elf64", READERS["read"], {"return_value": False}),
        ):
            with self.subTest(name):
                child = Child(self, code)
                child.until(lambda: child.watch.probe().reader)
                with patch.object(ttywatch, name, **mock):
                    self.assertIsNone(child.watch.probe().reader)

    def test_without_a_table_or_proc_the_reader_is_unknown(self):
        for name, value in (
            ("MACHINE", "forged-arch"),
            ("PROC_USABLE", False),
        ):
            with self.subTest(name):
                with patch.object(ttywatch, name, value):
                    child = Child(self, READERS["read"])
                child.until(lambda: b"ready" in child.output)
                self.assertIsNone(child.watch.probe().reader)

    def test_a_tagged_pointer_makes_the_reader_unknown(self):
        # aarch64 garde une étiquette dans l'octet de tête d'un pointeur :
        # au-delà de 2**63, aucun décalage de /proc/<pid>/mem ne le porte.
        child = Child(self, WAITERS["sleep"])
        child.until(lambda: b"ready" in child.output)
        child.until(child.blocked)
        number = str(min(child.watch.calls["select"])).encode()
        pointer = hex(2**64 - 16).encode()
        forged = [number, b"0x1", pointer, *[b"0x0"] * 6]
        with patch.object(ttywatch, "_syscall", return_value=forged):
            self.assertIsNone(child.watch.probe().reader)

    def test_an_epoll_beyond_fd_limit_is_not_read(self):
        child = Child(self, READERS["epoll"])
        child.until(lambda: child.watch.probe().reader)
        with patch.object(ttywatch, "FD_LIMIT", 0):
            self.assertIs(child.watch.probe().reader, False)


class TestAlternateScreen(unittest.TestCase):
    def setUp(self):
        master, slave = pty.openpty()
        self.addCleanup(os.close, master)
        self.addCleanup(os.close, slave)
        self.watch = ttywatch.TtyWatch(master, os.getpid())

    def test_a_sequence_cut_between_two_chunks_is_seen(self):
        self.watch.feed(b"text\x1b[?10")
        self.assertFalse(self.watch.altscreen)
        self.watch.feed(b"49hmore")
        self.assertTrue(self.watch.altscreen)
        self.watch.feed(b"\x1b[?1049")
        self.watch.feed(b"l")
        self.assertFalse(self.watch.altscreen)

    def test_each_mode_and_the_reset(self):
        for on, off in (
            (b"\x1b[?1049h", b"\x1b[?1049l"),
            (b"\x1b[?1047h", b"\x1b[?1047l"),
            (b"\x1b[?47h", b"\x1b[?47l"),
            (b"\x1b[?1049h", b"\x1bc"),
        ):
            with self.subTest(on=on, off=off):
                self.watch.feed(on)
                self.assertTrue(self.watch.probe().altscreen)
                self.watch.feed(b"\x1b[?25h" + b"x" * 20)
                self.assertTrue(self.watch.altscreen)
                self.watch.feed(off)
                self.assertFalse(self.watch.probe().altscreen)


class TestFlush(unittest.TestCase):
    """tcflush au maître laisse l'entrée : `_drop_input` vide par l'esclave."""

    def setUp(self):
        self.master, self.slave = pty.openpty()
        self.addCleanup(os.close, self.master)
        self.addCleanup(os.close, self.slave)
        os.write(self.master, b"typeahead\n")
        deadline = time.monotonic() + 5
        while queued(self.slave) < 10 and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(queued(self.slave), 10)

    def test_tcflush_on_the_master_leaves_the_typeahead(self):
        for queue in (termios.TCIFLUSH, termios.TCOFLUSH, termios.TCIOFLUSH):
            with self.subTest(queue=queue):
                termios.tcflush(self.master, queue)
                self.assertEqual(queued(self.slave), 10)


class Client:
    """Double d'un client : octets et messages reçus, avec leur heure."""

    def __init__(self):
        self.data = bytearray()
        self.arrivals = []  # (heure, taille de data après l'envoi)
        self.events = []  # (heure, message)

    async def send(self, data):
        self.data += data
        self.arrivals.append((time.monotonic(), len(self.data)))

    def event(self, message):
        self.events.append((time.monotonic(), message))

    def close(self, code, reason):
        pass

    def states(self) -> list:
        return [m for _, m in self.events if m["t"] == "tty_state"]

    def seen(self, **fields) -> bool:
        """Vrai si un `tty_state` reçu porte ces valeurs."""
        return any(
            all(state[key] == value for key, value in fields.items())
            for state in self.states()
        )

    def arrived(self, marker) -> float:
        """Heure de l'envoi qui a complété `marker` dans `data`."""
        end = self.data.find(marker) + len(marker)
        return next(at for at, size in self.arrivals if size >= end)


class SessionCase(unittest.IsolatedAsyncioTestCase):
    async def open(self, code):
        argv = [sys.executable, "-c", CTTY + code]
        session = sessions.Session("t1", str(REPO), "en", 80, 24, argv=argv)
        await session.start()
        self.addAsyncCleanup(session.close)
        client = Client()
        session.attach(client)
        return session, client

    async def until(self, predicate, timeout=5.0):
        deadline = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() > deadline:
                self.fail(f"still waiting: {predicate}")
            await asyncio.sleep(0.01)


class TestSessionState(SessionCase):
    async def test_a_password_prompt_reaches_the_client_within_0_2_s(self):
        # Sans l'horloge : la sortie de l'invite fait relire le terminal.
        with patch.object(sessions, "PROBE_SECONDS", 60):
            session, client = await self.open(SECRET)
            await self.until(lambda: b"ready" in client.data)
            session.write(b"go\n")
            await self.until(lambda: client.seen(echo=False), 1)
        at, state = next(
            (at, m)
            for at, m in client.events
            if m["t"] == "tty_state" and not m["echo"]
        )
        self.assertLess(at - client.arrived(b"pw: "), 0.2)
        self.assertEqual((state["canon"], state["altscreen"]), (True, False))
        session.write(b"hunter2\n")
        await self.until(lambda: b"length 7" in client.data)
        self.assertNotIn(b"hunter2", client.data)
        await self.until(lambda: client.states()[-1]["echo"])

    async def test_a_change_without_output_is_seen_by_the_clock(self):
        session, client = await self.open(SILENT)
        await self.until(lambda: b"ready" in client.data)
        wait = 0.5 + sessions.PROBE_SECONDS + 0.3
        await self.until(lambda: client.seen(echo=False), wait)

    async def test_a_new_client_gets_the_state_at_once(self):
        session, client = await self.open(SECRET)
        await self.until(lambda: client.seen(reader=True))
        session.write(b"go\n")
        await self.until(lambda: client.seen(echo=False))
        other = Client()
        session.attach(other)
        await self.until(lambda: other.seen(echo=False, canon=True), 0.2)

    async def test_a_flood_of_output_reads_proc_a_few_times_only(self):
        session, client = await self.open(FLOOD)
        await self.until(lambda: client.seen(reader=True))
        probes = []
        probe = session.watch.probe

        def slow():
            # 5 ms par sonde : l'écart entre deux sondes passe à 50 ms.
            probes.append(1)
            time.sleep(0.005)
            return probe()

        session.watch.probe = slow
        start = time.monotonic()
        session.write(b"go\n")
        await self.until(lambda: b"END" in client.data)
        elapsed = time.monotonic() - start
        # Une lecture par écart au plus, plus celles de l'horloge.
        most = elapsed / 0.05 + elapsed / sessions.PROBE_SECONDS
        self.assertLess(len(probes), most + 2)
        self.assertGreaterEqual(session.gap, 0.05)
        self.assertGreater(len(client.arrivals), len(probes))

    async def test_password_text_with_the_echo_on_never_says_echo_off(self):
        session, client = await self.open("input('[sudo] password for x: ')")
        await self.until(lambda: client.seen(reader=True))
        await asyncio.sleep(3 * sessions.PROBE_SECONDS)
        self.assertEqual({state["echo"] for state in client.states()}, {True})

    async def test_the_reader_follows_the_child(self):
        session, client = await self.open(READ_THEN_SLEEP)
        await self.until(lambda: client.seen(reader=True))
        session.write(b"go\n")
        await self.until(lambda: b"sleeping" in client.data)
        await self.until(lambda: client.states()[-1]["reader"] is False, 2)

    async def test_the_alternate_screen_cut_in_two_chunks_is_seen(self):
        session, client = await self.open(ALTSCREEN)
        await self.until(lambda: client.seen(altscreen=True, reader=True))
        session.write(b"\n")
        await self.until(lambda: not client.states()[-1]["altscreen"])

    async def test_typeahead_is_dropped_when_the_echo_goes_off(self):
        session, client = await self.open(TYPEAHEAD)
        await self.until(lambda: client.seen(reader=True))
        session.write(b"go\nforged\n")
        await self.until(lambda: b"got" in client.data)
        self.assertIn(b"got b'nothing'", client.data)


class TestGate(SessionCase):
    async def test_only_what_is_read_goes_through_and_signals_always(self):
        session, client = await self.open(READ_THEN_SLEEP)
        await self.until(lambda: client.seen(reader=True))
        self.assertEqual(await session.gate(b"go\n"), b"go\n")
        session.write(b"go\n")
        await self.until(lambda: client.states()[-1]["reader"] is False)
        self.assertEqual(await session.gate(b"abc"), b"")
        # Le noyau change Ctrl+C et Ctrl+Z en signal, sans lecteur.
        self.assertEqual(await session.gate(b"a\x03b\x1a"), b"\x03\x1a")

    async def test_each_keystroke_reads_the_terminal_again(self):
        # L'état gardé peut dater d'avant l'invite, ou d'un lecteur parti.
        session, client = await self.open(READ_THEN_SLEEP)
        await self.until(lambda: client.seen(reader=True))
        session.state = session.state._replace(reader=False)
        self.assertEqual(await session.gate(b"go\n"), b"go\n")
        session.write(b"go\n")
        await self.until(lambda: b"sleeping" in client.data)
        session.state = session.state._replace(reader=True)
        self.assertEqual(await session.gate(b"abc"), b"")

    async def test_a_key_behind_one_the_reader_still_handles_passes(self):
        # Le fil du lecteur calcule, hors de tout appel de lecture : la
        # touche suivante attend qu'il relise, au lieu d'être jetée.
        session, client = await self.open(BUSY)
        await self.until(lambda: client.seen(reader=True))
        for count in range(1, 11):
            session.write(await session.gate(b"a"))
            deadline = time.monotonic() + 1
            while session.watch.reader():
                self.assertLess(time.monotonic(), deadline, "never busy")
            self.assertEqual(await session.gate(b"b"), b"b")
            session.write(b"b")
            await self.until(lambda: client.data.count(b"<b>") == count)
        self.assertEqual(client.data.count(b"<a><b>"), 10)

    async def test_a_key_behind_a_reader_gone_to_sleep_waits_then_drops(self):
        session, client = await self.open(READ_THEN_SLEEP)
        await self.until(lambda: client.seen(reader=True))
        session.write(await session.gate(b"go\n"))
        await self.until(lambda: b"sleeping" in client.data)
        # Le lecteur vu avant `go` compte comme récent : la frappe attend,
        # puis est jetée.
        start = time.monotonic()
        with patch.object(sessions, "READER_RECENT", 60):
            self.assertEqual(await session.gate(b"abc"), b"")
        elapsed = time.monotonic() - start
        self.assertGreaterEqual(elapsed, sessions.HOLD_SECONDS)
        self.assertLess(elapsed, sessions.HOLD_SECONDS + 0.2)

    async def test_a_key_held_until_a_secret_prompt_is_dropped(self):
        # Tapée pendant que le lecteur calcule, avant l'invite : elle ne
        # devient pas le secret.
        session, client = await self.open(BUSY_THEN_SECRET)
        await self.until(lambda: client.seen(reader=True))
        session.write(await session.gate(b"go\n"))
        deadline = time.monotonic() + 1
        while session.watch.reader():
            self.assertLess(time.monotonic(), deadline, "never busy")
        self.assertEqual(await session.gate(b"forged\n"), b"")
        await self.until(lambda: client.seen(echo=False, reader=True))
        session.write(b"hunter2\n")
        await self.until(lambda: b"secret was" in client.data)
        self.assertIn(b"secret was 'hunter2'", client.data)

    async def test_the_alternate_screen_lets_everything_through(self):
        session, client = await self.open(FULL_SCREEN)
        await self.until(lambda: client.seen(altscreen=True, reader=False))
        self.assertEqual(await session.gate(b"q"), b"q")

    async def test_an_unknown_reader_lets_everything_through(self):
        # Architecture sans table ; /proc inutilisable ; esclave introuvable.
        for name, value in (
            ("MACHINE", "forged-arch"),
            ("PROC_USABLE", False),
            ("TtyWatch", Mock(side_effect=OSError)),
        ):
            with self.subTest(name):
                with patch.object(ttywatch, name, value):
                    session, client = await self.open(WAITERS["sleep"])
                await self.until(lambda: b"ready" in client.data)
                self.assertEqual(await session.gate(b"abc"), b"abc")


class TestPaste(SessionCase):
    async def test_a_paste_never_becomes_a_secret(self):
        session, client = await self.open(IMMEDIATE_SECRET)
        await self.until(lambda: client.seen(reader=True))
        session.write(await session.gate(b"go\nforged\n"), lines=True)
        await self.until(lambda: client.seen(echo=False, reader=True))
        self.assertEqual(session.held, b"")
        self.assertEqual(dropped(client), [(len(b"forged\n"), "question")])
        session.write(await session.gate(b"hunter2\n"), lines=True)
        await self.until(lambda: b"secret was" in client.data)
        self.assertIn(b"secret was 'hunter2'", client.data)

    async def test_its_lines_reach_their_reader_one_after_the_other(self):
        session, client = await self.open(THREE_LINES)
        await self.until(lambda: client.seen(reader=True))
        session.write(await session.gate(b"one\rtwo\nthree\r"), lines=True)
        self.assertEqual(session.held, b"two\nthree\r")
        await self.until(lambda: b"got three" in client.data)
        got = [
            client.data.find(b"got " + w) for w in (b"one", b"two", b"three")
        ]
        self.assertEqual(got, sorted(got))
        self.assertEqual(session.held, b"")

    async def test_a_known_reader_gets_one_line_per_read(self):
        session, client = await self.open(SLOW_LINES)
        await self.until(lambda: client.seen(reader=True))
        session.write(await session.gate(b"one\ntwo\nthree\n"), lines=True)
        for word, rest in ((b"one", b"two\nthree\n"), (b"two", b"three\n")):
            await self.until(lambda word=word: b"got " + word in client.data)
            # L'enfant dort : ni le hub ni l'esclave ne lui ont livré la
            # ligne suivante.
            self.assertEqual(session.held, rest)
            self.assertEqual(session._queued(), 0)
        await self.until(lambda: b"got three" in client.data)

    async def test_the_rest_of_a_paste_never_answers_the_next_question(self):
        session, client = await self.open(PORT_QUESTIONS % str(REPO))
        await self.until(lambda: session.asking is not None)
        await self.until(lambda: client.seen(reader=True))
        session.write(await session.gate(b"1\nforged\n"), lines=True)
        await self.until(lambda: asked(session) == "Q2: ")
        self.assertEqual(session.held, b"")
        self.assertEqual(dropped(client), [(len(b"forged\n"), "question")])
        session.write(b"typed\n", lines=True)
        await self.until(lambda: b"answers" in client.data)
        self.assertIn(b"answers '1' 'typed'", client.data)

    async def test_once_answered_a_paste_feeds_what_reads_next(self):
        session, client = await self.open(PORT_QUESTIONS % str(REPO))
        for number, text in ((b"1\n", "Q1: "), (b"2\n", "Q2: ")):
            await self.until(lambda text=text: asked(session) == text)
            session.write(number)
        await self.until(lambda: b"answers" in client.data)
        await self.until(lambda: session.asking is None)
        session.write(b"a\nb\n", lines=True)
        await self.until(lambda: b"got" in client.data)
        self.assertIn(b"got 'a' 'b'", client.data)

    async def test_ctrl_c_throws_away_what_waits(self):
        session, client = await self.open(READ_THEN_SLEEP)
        await self.until(lambda: client.seen(reader=True))
        session.write(await session.gate(b"go\nlater\n"), lines=True)
        await self.until(lambda: b"sleeping" in client.data)
        self.assertEqual(session.held, b"later\n")
        self.assertEqual(await session.gate(b"\x03"), b"\x03")
        self.assertEqual(session.held, b"")
        self.assertEqual(dropped(client), [(len(b"later\n"), "stop")])

    async def test_every_other_discard_is_reported(self):
        # Ctrl+C, une invite de secret et un message du worker ont leurs
        # tests ; ici, un lecteur devenu inconnu, une réponse de la page,
        # Arrêter, la fin du worker et, sans client, ce qu'un lecteur
        # inconnu retient.
        reasons = {
            "unknown reader": "unread",
            "answer": "question",
            "interrupt": "stop",
            "close": "stop",
        }
        cases = ("unknown reader", "answer", "interrupt", "close", "no client")
        for case in cases:
            with self.subTest(case):
                session, client = await self.open(READ_THEN_SLEEP)
                await self.until(lambda: client.seen(reader=True))
                session.write(await session.gate(b"go\nlater\n"), lines=True)
                await self.until(lambda: b"sleeping" in client.data)
                self.assertEqual(session.held, b"later\n")
                if case == "unknown reader":
                    session.state = session.state._replace(reader=None)
                    self.assertTrue(session.write(b"x", lines=True))
                elif case == "answer":
                    session.asking = {"t": "ask", "qid": 1}
                    self.assertTrue(session.answer({"t": "cancel", "qid": 1}))
                elif case == "interrupt":
                    # L'enfant dort sans enfant à lui : `interrupt` n'agit
                    # que sur une commande ou sur un enfant du worker.
                    children = patch.object(
                        sessions, "_has_children", return_value=True
                    )
                    with children:
                        self.assertTrue(session.interrupt())
                elif case == "close":
                    await session.close()
                else:
                    session.detach(client)
                    probe = session.watch.probe
                    session.watch.probe = lambda: probe()._replace(reader=None)
                    wait = 3 * sessions.PROBE_SECONDS
                    await self.until(lambda: not session.held, wait)
                    self.assertEqual(session.unreported, len(b"later\n"))
                    self.assertEqual(dropped(client), [])
                    continue
                self.assertEqual(session.held, b"")
                lost = [(len(b"later\n"), reasons[case])]
                self.assertEqual(dropped(client), lost)

    async def test_an_unknown_reader_gets_the_whole_paste(self):
        # Le lecteur reste inconnu toute la vie de l'enfant (PROC_USABLE
        # coupé à la construction de TtyWatch) : aucune sonde ne dirait
        # quand livrer la ligne suivante, le collage part donc entier, et
        # chaque frappe qui suit aussi.
        with patch.object(ttywatch, "PROC_USABLE", False):
            session, client = await self.open(THREE_LINES)
        await self.until(lambda: client.seen(reader=None))
        session.write(await session.gate(b"one\ntwo\n"), lines=True)
        self.assertEqual(session.held, b"")
        await self.until(lambda: b"got two" in client.data)
        for byte in b"three\r":
            session.write(await session.gate(bytes([byte])), lines=True)
        await self.until(lambda: b"got three" in client.data)
        self.assertEqual(dropped(client), [])

    def test_a_line_ends_at_its_first_cr_or_lf(self):
        cases = {
            b"a\rb\n": (b"a\r", b"b\n"),
            b"a\r\nb": (b"a\r\n", b"b"),
            b"a\nb\r": (b"a\n", b"b\r"),
            b"abc": (b"abc", b""),
        }
        for data, expected in cases.items():
            self.assertEqual(sessions._first_line(data), expected, data)


if __name__ == "__main__":
    unittest.main()
