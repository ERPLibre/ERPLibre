#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""TtyWatch : l'état du terminal d'une session, lu sur le maître et dans
/proc.

Chaque enfant est un `python -c` jetable sur un PTY neuf, dont il fait son
terminal de contrôle ; aucun test ne lance TODO.
"""

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
from unittest.mock import patch

from script.todo.web import ttywatch

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
        master, slave = pty.openpty()
        watch = ttywatch.TtyWatch(master, os.getpid())
        os.close(master)
        os.close(slave)
        self.assertIsNone(watch.probe().reader)

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


if __name__ == "__main__":
    unittest.main()
