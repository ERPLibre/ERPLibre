#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Sessions du hub web : un PTY, un enfant, l'anneau de sa sortie.

Chaque enfant est un `python -c` jetable qui tient le rôle du worker :
aucun test ne lance TODO. Le client est un double qui garde ce qu'il
reçoit.
"""

import asyncio
import os
import re
import signal
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from todo_web_env import CHILD

from script.todo.web import sessions

REPO = Path(__file__).resolve().parent.parent

# Demande un worker neuf la première fois, attend la seconde.
RESTART_CHILD = r"""
import os, sys
if os.path.exists("started"):
    print("second", flush=True)
    sys.stdin.readline()
else:
    open("started", "w").close()
    print("first", flush=True)
    sys.exit(75)
"""

# Demande un worker neuf à chaque lancement, et compte ses lancements.
LOOP_CHILD = r"""
import sys
with open("starts", "a") as f:
    f.write("+")
sys.exit(75)
"""

DEAF_CHILD = r"""
import signal, time
signal.signal(signal.SIGHUP, signal.SIG_IGN)
print("ready", flush=True)
while True:
    time.sleep(1)
"""

# Un worker qui lance chaque commande de son argv avec le contrôle de
# tâches et dit son code, puis répète la ligne qu'il lit.
JOB_CHILD = r"""
import fcntl, signal, sys, termios
signal.signal(signal.SIGINT, signal.default_int_handler)
signal.signal(signal.SIGHUP, signal.SIG_DFL)
fcntl.ioctl(0, termios.TIOCSCTTY, 0)
from script.execute.execute import Execute
exe = Execute()
exe.job_control = True
for command in sys.argv[1:]:
    rc = exe.exec_command_live(command, False, quiet=True)
    print(f"rc={rc}", flush=True)
print("read", input(), flush=True)
"""

# Un worker qui attend un enfant de son propre groupe, sans contrôle de
# tâches, comme subprocess.run dans TODO.
BUSY_CHILD = r"""
import fcntl, signal, subprocess, termios
signal.signal(signal.SIGINT, signal.default_int_handler)
fcntl.ioctl(0, termios.TIOCSCTTY, 0)
print("ready", flush=True)
try:
    subprocess.run(["sleep", "30"])
except KeyboardInterrupt:
    print("INT", flush=True)
"""

# Un enfant fugitif dans une session neuve (virt-viewer, `setsid -f`) :
# hors du groupe du worker, jamais busy. SIGHUP (close) tue l'enfant lui-même,
# hors du groupe que `_kill` atteint : sans cela, il survit au test.
NEWGROUP_CHILD = r"""
import os, signal, subprocess, sys, time
child = subprocess.Popen(["sleep", "30"], start_new_session=True)
def cleanup(signum, frame):
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    sys.exit(0)
signal.signal(signal.SIGHUP, cleanup)
print("ready", flush=True)
time.sleep(30)
"""

# Un enfant zombie, faute d'être attendu (comme le Popen d'une commande en
# arrière-plan que rien ne réattend avant le suivant) : jamais busy non
# plus.
ZOMBIE_CHILD = r"""
import os, time
if os.fork() == 0:
    os._exit(0)
print("ready", flush=True)
time.sleep(30)
"""


def _state(pid):
    """État du processus `pid` (champ 3 de /proc/<pid>/stat), ou None."""
    try:
        with open(f"/proc/{pid}/stat", "rb") as f:
            return f.read().rsplit(b")", 1)[-1].split()[0]
    except (OSError, IndexError):
        return None


class Client:
    """Double d'un client ; `gate`, une fois posé, retient chaque envoi."""

    def __init__(self):
        self.data = bytearray()
        self.events = []
        self.closed = None
        self.gate = None

    async def send(self, data):
        if self.gate is not None:
            await self.gate.wait()
        self.data += data

    def event(self, message):
        self.events.append(message)

    def close(self, code, reason):
        self.closed = (code, reason)


class SessionCase(unittest.IsolatedAsyncioTestCase):
    async def open(self, child=CHILD, root=REPO, on_end=None, args=()):
        argv = [sys.executable, "-c", child, *args]
        session = sessions.Session(
            "s1", str(root), "fr", 100, 30, argv=argv, on_end=on_end
        )
        await session.start()
        self.addAsyncCleanup(session.close)
        return session

    async def until(self, predicate, timeout=10.0):
        deadline = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() > deadline:
                self.fail(f"still waiting: {predicate.__doc__ or predicate}")
            await asyncio.sleep(0.01)

    async def seen(self, session, marker):
        await self.until(lambda: marker in session.ring.data)


class TestTerminal(SessionCase):
    async def test_a_controlling_terminal_its_size_and_the_hello(self):
        session = await self.open()
        await self.seen(session, b"ready fr 100x30")
        session.resize(90, 20)
        self.assertEqual(os.get_terminal_size(session.master), (90, 20))

    async def test_the_ctrl_c_byte_is_sigint_for_the_foreground(self):
        session = await self.open()
        await self.seen(session, b"ready")
        self.assertTrue(session.write(b"\x03"))
        await asyncio.wait_for(session.ended.wait(), 10)
        self.assertIn(b"INT", session.ring.data)
        self.assertEqual(session.code, 5)

    async def test_stop_without_anything_launched_changes_nothing(self):
        session = await self.open()
        await self.seen(session, b"ready")
        self.assertFalse(session.busy)
        self.assertFalse(session.interrupt())
        self.assertTrue(session.write(b"exit 4\n"))
        await asyncio.wait_for(session.ended.wait(), 10)
        self.assertEqual(session.code, 4)

    async def test_stop_stops_the_command_and_the_worker_lives(self):
        session = await self.open(JOB_CHILD, args=["sleep 30"])
        await self.until(lambda: session.running)
        self.assertTrue(session.interrupt())
        await self.seen(session, b"rc=-2")
        self.assertFalse(session.running)
        self.assertIsNone(session.proc.returncode)

    async def test_stop_reaches_a_command_behind_unread_input(self):
        session = await self.open(JOB_CHILD, args=["sleep 30"])
        await self.until(lambda: session.running)
        # Des lignes que la commande ne lit pas remplissent le terminal :
        # l'octet Ctrl+C attendrait derrière elles.
        self.assertTrue(session.write(b"y\n" * 4000))
        await asyncio.sleep(0.3)
        self.assertTrue(session.interrupt())
        await self.seen(session, b"rc=-2")
        # Ce qui restait ne répond pas à la question suivante.
        session.write(b"next\n")
        await self.seen(session, b"read next")

    async def test_stop_clears_the_input_of_a_command_that_exits_itself(self):
        # La commande rattrape SIGINT et rend un code, comme pip : aucun
        # signal ne l'a tuée, et ce qu'on lui a tapé ne répond pas pour
        # autant à la question suivante.
        armed = "trap 'exit 1' INT; echo armed > /dev/tty; sleep 30"
        session = await self.open(JOB_CHILD, args=[armed])
        await self.seen(session, b"armed")
        self.assertTrue(session.write(b"y\n" * 3))
        await asyncio.sleep(0.3)
        self.assertTrue(session.interrupt())
        await self.seen(session, b"rc=1")
        session.write(b"next\n")
        await self.seen(session, b"read next")
        self.assertNotIn(b"read y", session.ring.data)

    async def test_stop_resumes_a_command_that_suspended_itself(self):
        session = await self.open(JOB_CHILD, args=["kill -TSTP 0; sleep 30"])
        await self.until(lambda: session.running)
        command = os.tcgetpgrp(session.master)
        await self.until(lambda: _state(command) == b"T")
        self.assertTrue(session.interrupt())
        await self.seen(session, b"rc=-2")
        self.assertFalse(session.running)
        self.assertIsNone(session.proc.returncode)

    async def test_stop_reaches_a_child_of_the_worker_group(self):
        session = await self.open(BUSY_CHILD)
        await self.seen(session, b"ready")
        await self.until(lambda: session.busy)
        self.assertFalse(session.running)
        self.assertEqual(session.idle(time.monotonic() + 10**4), 0)
        self.assertTrue(session.interrupt())
        await asyncio.wait_for(session.ended.wait(), 10)
        self.assertIn(b"INT", session.ring.data)

    async def test_a_child_in_a_new_session_does_not_count_as_busy(self):
        session = await self.open(NEWGROUP_CHILD)
        await self.seen(session, b"ready")
        for _ in range(5):
            self.assertFalse(session.busy)
            await asyncio.sleep(0.05)
        self.assertFalse(session.interrupt())

    async def test_an_unreaped_zombie_does_not_count_as_busy(self):
        session = await self.open(ZOMBIE_CHILD)
        await self.seen(session, b"ready")
        for _ in range(5):
            self.assertFalse(session.busy)
            await asyncio.sleep(0.05)
        self.assertFalse(session.interrupt())

    async def test_commands_share_the_terminal_and_session_of_sudo(self):
        # sudo (timestamp_type=tty) garde son ticket par terminal et par
        # session : /proc/<pid>/stat donne la session (champ 6) et le
        # terminal de contrôle (champ 7).
        probe = "cut -d' ' -f6,7 /proc/$$/stat > /dev/tty"
        session = await self.open(JOB_CHILD, args=[probe, probe])
        await self.until(lambda: session.ring.data.count(b"rc=0") == 2)
        data = bytes(session.ring.data)
        keys = re.findall(rb"^(\d+) (\d+)\r$", data, re.M)
        self.assertEqual(len(keys), 2)
        self.assertEqual(keys[0], keys[1])
        sid, tty = map(int, keys[0])
        self.assertEqual(sid, session.proc.pid)
        self.assertNotEqual(tty, 0)

    async def test_input_beyond_the_limit_is_refused(self):
        session = await self.open()
        big = b"x" * (sessions.INPUT_LIMIT + 1)
        self.assertFalse(session.write(big))
        self.assertEqual(session.inbox, b"")
        self.assertTrue(session.write(b"exit 4\n"))
        await asyncio.wait_for(session.ended.wait(), 10)
        self.assertEqual(session.code, 4)


class TestRing(SessionCase):
    async def test_without_a_client_the_output_keeps_flowing(self):
        session = await self.open()
        session.write(b"big 1000000\n")
        await self.seen(session, b"END")
        self.assertGreater(session.ring.end, 1000000)

    async def test_an_attached_client_holds_the_output_back(self):
        session = await self.open()
        await self.seen(session, b"ready")
        client = Client()
        client.gate = asyncio.Event()
        session.attach(client)
        session.write(b"big 1000000\n")
        await asyncio.sleep(0.5)
        self.assertLess(session.ring.end, 300000)
        client.gate.set()
        await self.until(lambda: b"END" in client.data)
        self.assertEqual(client.data, session.ring.data)

    async def test_a_reattach_replays_from_after(self):
        session = await self.open()
        first = Client()
        session.attach(first)
        await self.until(lambda: b"ready" in first.data)
        after = session.ring.end
        session.write(b"big 10\n")
        await self.until(lambda: b"END" in first.data)
        second = Client()
        offset, truncated, previous = session.attach(second, after)
        self.assertEqual((offset, truncated), (after, False))
        self.assertIs(previous, first)
        await self.until(lambda: b"END" in second.data)
        self.assertTrue(second.data.startswith(b"big 10"))
        self.assertEqual(second.data, session.ring.data[after:])
        session.detach(first)
        self.assertIs(session.client, second)

    async def test_a_ring_that_lost_bytes_says_so(self):
        session = await self.open()
        session.ring.size = 1000
        session.write(b"big 5000\n")
        await self.seen(session, b"END")
        start = session.ring.start
        self.assertGreater(start, 0)
        client = Client()
        self.assertEqual(session.attach(client, 0)[:2], (start, True))
        self.assertEqual(session.attach(client)[:2], (start, True))
        end = session.ring.end
        self.assertEqual(session.attach(client, end)[:2], (end, False))


class TestLifecycle(SessionCase):
    async def test_the_end_of_the_worker_says_bye_after_its_output(self):
        ended = []
        session = await self.open(on_end=ended.append)
        client = Client()
        session.attach(client)
        session.write(b"big 200000\nexit 3\n")
        await asyncio.wait_for(session.ended.wait(), 10)
        await self.until(lambda: client.closed is not None)
        self.assertIn(b"END", client.data)
        self.assertEqual(client.events, [{"t": "bye", "code": 3}])
        self.assertEqual(client.closed, (1000, "session ended"))
        self.assertEqual(ended, [session])

    async def test_close_hangs_up_and_the_worker_ends(self):
        session = await self.open()
        await self.seen(session, b"ready")
        await session.close()
        self.assertEqual(session.code, -signal.SIGHUP)
        with self.assertRaises(ProcessLookupError):
            os.kill(session.proc.pid, 0)

    async def test_a_worker_deaf_to_sighup_is_killed(self):
        session = await self.open(DEAF_CHILD)
        await self.seen(session, b"ready")
        with patch.object(sessions, "REAP_SECONDS", 0.2):
            await session.close()
        self.assertEqual(session.code, -signal.SIGKILL)

    async def test_a_command_deaf_to_sighup_is_killed(self):
        session = await self.open(JOB_CHILD, args=["trap '' HUP; sleep 30"])
        await self.until(lambda: session.running)
        command = os.tcgetpgrp(session.master)
        with patch.object(sessions, "REAP_SECONDS", 0.2):
            await session.close()

        def gone():
            try:
                os.killpg(command, 0)
            except ProcessLookupError:
                return True
            return False

        await self.until(gone, timeout=5)

    async def test_close_during_the_start_stops_the_new_worker(self):
        argv = [sys.executable, "-c", CHILD]
        session = sessions.Session("s1", str(REPO), "fr", 100, 30, argv=argv)
        starting = asyncio.ensure_future(session.start())
        await asyncio.sleep(0)
        self.assertIsNone(session.proc)
        await session.close()
        await asyncio.wait_for(starting, 10)
        self.assertEqual(session.code, -signal.SIGHUP)

    async def test_restart_keeps_the_id_and_the_ring(self):
        with tempfile.TemporaryDirectory() as root:
            session = await self.open(RESTART_CHILD, root=root)
            first = session.proc.pid
            await self.seen(session, b"second")
        self.assertIn(b"first", session.ring.data)
        self.assertNotEqual(session.proc.pid, first)
        self.assertEqual(session.id, "s1")
        self.assertFalse(session.ended.is_set())

    async def test_a_worker_that_always_restarts_ends_the_session(self):
        with tempfile.TemporaryDirectory() as root:
            session = await self.open(LOOP_CHILD, root=root)
            await asyncio.wait_for(session.ended.wait(), 10)
            starts = Path(root, "starts").read_text()
        self.assertEqual(session.code, sessions.RESTART)
        self.assertEqual(len(starts), sessions.RESTART_LIMIT + 1)

    async def test_only_known_views_reach_the_client(self):
        session = await self.open()
        client = Client()
        session.attach(client)
        for line in (
            b'{"t":"open_view","view":"shell"}',
            b'{"t":"spawn","argv":["sh"]}',
            b"not json",
            b'{"t":"open_view","view":"telemetry"}',
        ):
            session.write(b"send " + line + b"\n")
        await self.until(lambda: client.events)
        self.assertEqual(
            client.events, [{"t": "open_view", "view": "telemetry"}]
        )

    async def test_idle_counts_without_client_nor_command(self):
        session = await self.open()
        now = time.monotonic()
        client = Client()
        session.attach(client)
        self.assertEqual(session.idle(now + 100), 0)
        session.detach(client)
        self.assertGreaterEqual(session.idle(time.monotonic() + 60), 60)


if __name__ == "__main__":
    unittest.main()
