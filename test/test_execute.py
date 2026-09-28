#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import ast
import glob
import os
import pty
import select
import shlex
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from script.execute import execute
from script.execute.execute import (
    Execute,
    holds_secret_trigger,
    redact_for_storage,
    redact_secrets,
)

REPO = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
# Borne d'une lecture linéaire de 64 Kio : quelques dizaines de
# millisecondes sur un poste au repos, plusieurs fois plus sur un poste
# chargé ; une lecture au carré de la longueur en prend des secondes. La
# borne garde une marge large des deux côtés.
LINEAR_SECONDS = 0.5


class TestExecuteInit(unittest.TestCase):
    """Test Execute class initialization."""

    @patch("shutil.which")
    def test_init_with_gnome_terminal(self, mock_which):
        mock_which.side_effect = lambda x: (
            "/usr/bin/gnome-terminal" if x == "gnome-terminal" else None
        )
        exe = Execute()
        self.assertIn("gnome-terminal", exe.cmd_source_erplibre)
        self.assertIn(".venv.erplibre", exe.cmd_source_erplibre)
        self.assertIn("gnome-terminal", exe.cmd_source_default)

    @patch("shutil.which")
    def test_init_with_osascript(self, mock_which):
        mock_which.side_effect = lambda x: (
            "/usr/bin/osascript" if x == "osascript" else None
        )
        exe = Execute()
        self.assertIn("osascript", exe.cmd_source_erplibre)

    @patch("shutil.which", return_value=None)
    def test_init_fallback_source(self, mock_which):
        exe = Execute()
        self.assertIn(".venv.erplibre/bin/activate", exe.cmd_source_erplibre)
        self.assertEqual(exe.cmd_source_default, "")


class TestExecCommandLive(unittest.TestCase):
    """Test exec_command_live method."""

    def setUp(self):
        with patch("shutil.which", return_value=None):
            self.exe = Execute()

    def test_simple_command_returns_zero(self):
        result = self.exe.exec_command_live(
            "echo hello",
            source_erplibre=False,
            quiet=True,
        )
        self.assertEqual(result, 0)

    def test_failing_command_returns_nonzero(self):
        result = self.exe.exec_command_live(
            "exit 42",
            source_erplibre=False,
            quiet=True,
        )
        self.assertEqual(result, 42)

    def test_return_status_and_output(self):
        status, output = self.exe.exec_command_live(
            "echo hello",
            source_erplibre=False,
            quiet=True,
            return_status_and_output=True,
        )
        self.assertEqual(status, 0)
        self.assertEqual(output, ["hello"])

    def test_events_announce_each_command_redacted(self):
        self.assertIsNone(Execute.events)
        events = []
        self.exe.events = events.append
        rc = self.exe.exec_command_live(
            "MY_PASSWORD=hunter2 true; exit 3",
            source_erplibre=False,
            quiet=True,
        )
        self.assertEqual(rc, 3)
        start, end = events
        self.assertEqual(
            start, {"t": "run_start", "cmd": "MY_PASSWORD='***' true; exit 3"}
        )
        self.assertEqual((end["t"], end["rc"]), ("run_end", 3))
        self.assertIsInstance(end["secs"], float)

    def test_a_broken_event_hook_never_breaks_the_command(self):
        def hook(message):
            raise RuntimeError("forged failure")

        self.exe.events = hook
        rc = self.exe.exec_command_live(
            "exit 4", source_erplibre=False, quiet=True
        )
        self.assertEqual(rc, 4)

    def test_an_interrupted_command_still_ends(self):
        events = []
        self.exe.events = events.append
        with patch("subprocess.Popen", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.exe.exec_command_live(
                    "true", source_erplibre=False, quiet=True
                )
        self.assertEqual([e["t"] for e in events], ["run_start", "run_end"])
        self.assertIsNone(events[1]["rc"])

    def test_a_terminal_that_fails_still_ends_the_command(self):
        events = []
        self.exe.events = events.append
        with patch.object(Execute, "_job_control_tty", side_effect=OSError):
            rc = self.exe.exec_command_live(
                "true", source_erplibre=False, quiet=True
            )
        self.assertEqual(rc, 1)
        self.assertEqual([e["t"] for e in events], ["run_start", "run_end"])

    def test_an_interrupt_while_announcing_opens_no_terminal(self):
        def hook(message):
            raise KeyboardInterrupt

        self.exe.events = hook
        with patch.object(Execute, "_job_control_tty") as tty:
            with self.assertRaises(KeyboardInterrupt):
                self.exe.exec_command_live(
                    "true", source_erplibre=False, quiet=True
                )
        tty.assert_not_called()

    def test_return_status_and_output_multiline(self):
        status, output = self.exe.exec_command_live(
            "echo -e 'line1\nline2\nline3'",
            source_erplibre=False,
            quiet=True,
            return_status_and_output=True,
        )
        self.assertEqual(status, 0)
        self.assertEqual(output, ["line1", "line2", "line3"])

    def test_return_status_and_command(self):
        status, cmd = self.exe.exec_command_live(
            "echo test",
            source_erplibre=False,
            quiet=True,
            return_status_and_command=True,
        )
        self.assertEqual(status, 0)
        self.assertEqual(cmd, "echo test")

    def test_return_status_and_output_and_command(self):
        status, cmd, output = self.exe.exec_command_live(
            "echo result",
            source_erplibre=False,
            quiet=True,
            return_status_and_output_and_command=True,
        )
        self.assertEqual(status, 0)
        self.assertEqual(cmd, "echo result")
        self.assertEqual(output, ["result"])

    def test_source_erplibre_prepends_activate(self):
        status, cmd = self.exe.exec_command_live(
            "echo test",
            source_erplibre=True,
            quiet=True,
            return_status_and_command=True,
        )
        self.assertIn(".venv.erplibre/bin/activate", cmd)

    def test_single_source_erplibre(self):
        status, cmd = self.exe.exec_command_live(
            "echo test",
            source_erplibre=False,
            single_source_erplibre=True,
            quiet=True,
            return_status_and_command=True,
        )
        self.assertIn(".venv.erplibre/bin/activate", cmd)
        self.assertIn("echo test", cmd)

    def test_single_source_odoo_no_version_returns_error(self):
        with patch("os.path.exists", return_value=False):
            result = self.exe.exec_command_live(
                "echo test",
                source_erplibre=False,
                single_source_odoo=True,
                source_odoo="",
                quiet=True,
            )
        # `1`, pas `-1` : e24b185 a rendu à ce chemin la FORME que
        # l'appelant demande (un tuple s'il en attend un) et en a profité
        # pour donner un vrai code de sortie. Aucun appelant ne compare à
        # -1, qui n'est d'ailleurs pas un code de sortie valide.
        self.assertEqual(result, 1)

    def test_a_command_never_launched_is_not_interrupted(self):
        # Rendue sans lancer la commande, la main ne porte pas l'interruption
        # d'une commande précédente : une mise à jour d'Odoo qui lit le
        # drapeau montre son erreur au lieu de quitter TODO.
        self.enterContext(patch.object(Execute, "ctrl_c_stops_command", True))
        self.enterContext(patch.object(Execute, "interrupted", True))
        with patch("os.path.exists", return_value=False):
            result = self.exe.exec_command_live(
                "echo test",
                source_erplibre=False,
                single_source_odoo=True,
                quiet=True,
            )
        self.assertEqual(result, 1)
        self.assertIs(Execute.interrupted, False)

    def test_single_source_odoo_with_version(self):
        status, cmd = self.exe.exec_command_live(
            "echo test",
            source_erplibre=False,
            single_source_odoo=True,
            source_odoo="odoo18",
            quiet=True,
            return_status_and_command=True,
        )
        self.assertIn(".venv.odoo18/bin/activate", cmd)

    def test_new_env_passed_to_subprocess(self):
        status, output = self.exe.exec_command_live(
            "echo $MY_TEST_VAR",
            source_erplibre=False,
            quiet=True,
            new_env={"MY_TEST_VAR": "test_value_123"},
            return_status_and_output=True,
        )
        self.assertEqual(status, 0)
        self.assertEqual(output, ["test_value_123"])

    def test_empty_output_command(self):
        status, output = self.exe.exec_command_live(
            "true",
            source_erplibre=False,
            quiet=True,
            return_status_and_output=True,
        )
        self.assertEqual(status, 0)
        self.assertEqual(output, [])


# Tient le rôle du worker d'une session web : rétablit SIGINT (un SIGINT
# ignoré s'hérite, d'un lanceur en arrière-plan), prend le PTY comme terminal
# de contrôle, lance une commande avec le contrôle de tâches, puis dit son
# code, si le terminal lui est revenu, et qu'il vit encore.
JOB_CHILD = r"""
import fcntl, os, signal, termios
signal.signal(signal.SIGINT, signal.default_int_handler)
fcntl.ioctl(0, termios.TIOCSCTTY, 0)
from script.execute.execute import Execute
exe = Execute()
exe.job_control = True
rc = exe.exec_command_live('read -r x; echo "got $x"; sleep 30', False)
back = os.tcgetpgrp(0) == os.getpgrp()
print(f"rc={rc} back={back}", flush=True)
print("alive", flush=True)
"""


def _descendant_stopped(pid, timeout=0.3):
    """Vrai si un descendant de `pid` (via /proc) atteint l'état arrêté (T)
    avant le délai ; balaie l'arbre des enfants à chaque tour, un stade
    stoppé n'apparaissant que sous son parent direct."""

    def any_stopped(root):
        for children_path in glob.glob(f"/proc/{root}/task/*/children"):
            try:
                with open(children_path) as f:
                    kids = f.read().split()
            except OSError:
                continue
            for kid in kids:
                try:
                    with open(f"/proc/{kid}/status") as f:
                        status = f.read()
                except OSError:
                    continue
                if "State:\tT" in status or any_stopped(kid):
                    return True
        return False

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any_stopped(pid):
            return True
        time.sleep(0.01)
    return False


def _read_until(fd, marker, timeout=10.0):
    """Octets lus sur `fd` jusqu'à `marker` compris ; échec au délai."""
    out = b""
    deadline = time.monotonic() + timeout
    while marker not in out:
        left = deadline - time.monotonic()
        if left <= 0 or not select.select([fd], [], [], left)[0]:
            raise AssertionError(f"{marker!r} not seen in {out!r}")
        try:
            out += os.read(fd, 65536)
        except OSError:  # EIO : plus personne au bout de l'esclave
            raise AssertionError(f"{marker!r} not seen in {out!r}")
    return out


class TestJobControl(unittest.TestCase):
    def test_off_by_default_the_command_shares_the_caller_group(self):
        with patch("shutil.which", return_value=None):
            exe = Execute()
        self.assertIs(exe.job_control, False)
        with (
            patch("subprocess.Popen", wraps=subprocess.Popen) as popen,
            patch("os.tcsetpgrp") as tcsetpgrp,
        ):
            rc = exe.exec_command_live("true", False, quiet=True)
        self.assertEqual(rc, 0)
        self.assertNotIn("process_group", popen.call_args.kwargs)
        tcsetpgrp.assert_not_called()

    def test_without_a_controlling_terminal_it_runs_as_in_the_cli(self):
        with patch("shutil.which", return_value=None):
            exe = Execute()
        exe.job_control = True
        with (
            patch("os.open", side_effect=OSError("no terminal")),
            patch("subprocess.Popen", wraps=subprocess.Popen) as popen,
        ):
            rc = exe.exec_command_live("true", False, quiet=True)
        self.assertEqual(rc, 0)
        self.assertNotIn("process_group", popen.call_args.kwargs)

    def test_outside_the_main_thread_it_runs_as_in_the_cli(self):
        with patch("shutil.which", return_value=None):
            exe = Execute()
        exe.job_control = True
        ttys = []
        with patch("os.open") as open_:
            thread = threading.Thread(
                target=lambda: ttys.append(exe._job_control_tty())
            )
            thread.start()
            thread.join()
        self.assertEqual(ttys, [None])
        open_.assert_not_called()

    def test_a_foreground_refused_leaves_no_command_behind(self):
        with patch("shutil.which", return_value=None):
            exe = Execute()
        exe.job_control = True
        tty = os.open(os.devnull, os.O_RDWR)
        started, real = [], subprocess.Popen

        def popen(*args, **kwargs):
            started.append(real(*args, **kwargs))
            return started[-1]

        with (
            patch.object(Execute, "_job_control_tty", return_value=tty),
            patch(
                "script.execute.execute._set_foreground",
                side_effect=OSError(5, "EIO"),
            ),
            patch("subprocess.Popen", side_effect=popen),
            patch("os.close", wraps=os.close) as close,
        ):
            rc = exe.exec_command_live("sleep 30", False, quiet=True)
        started[0].stdout.close()
        # Tuée et attendue ; le descripteur se ferme malgré l'échec.
        self.assertEqual((rc, started[0].returncode), (1, -signal.SIGKILL))
        close.assert_any_call(tty)

    def test_ctrl_c_stops_the_command_and_not_its_caller(self):
        master, slave = pty.openpty()
        self.addCleanup(os.close, master)
        child = subprocess.Popen(
            [sys.executable, "-c", JOB_CHILD],
            stdin=slave,
            stdout=slave,
            stderr=slave,
            cwd=REPO,
            start_new_session=True,
        )
        os.close(slave)
        # Sur un échec, les nettoyages tournent en ordre inverse, child.kill
        # d'abord : la mort du chef de session envoie SIGHUP au groupe au
        # premier plan de son terminal, la commande qui y est restée.
        self.addCleanup(child.wait, 10)
        self.addCleanup(child.kill)
        _read_until(master, b"Execute command")
        # La commande lit le terminal : elle y est au premier plan.
        os.write(master, b"yes\n")
        out = _read_until(master, b"got yes")
        os.write(master, b"\x03")
        out += _read_until(master, b"alive")
        self.assertIn(b"rc=-2 back=True", out)
        self.assertEqual(child.wait(10), 0)

    def test_ctrl_z_does_not_suspend_and_ctrl_c_still_stops_it(self):
        master, slave = pty.openpty()
        self.addCleanup(os.close, master)
        child = subprocess.Popen(
            [sys.executable, "-c", JOB_CHILD],
            stdin=slave,
            stdout=slave,
            stderr=slave,
            cwd=REPO,
            start_new_session=True,
        )
        os.close(slave)
        self.addCleanup(child.wait, 10)
        self.addCleanup(child.kill)
        _read_until(master, b"Execute command")
        os.write(master, b"yes\n")
        out = _read_until(master, b"got yes")
        # VSUSP désactivé : Ctrl+Z ne met pas la commande en état arrêté (T),
        # où elle resterait faute d'un shell pour la reprendre. On laisse le
        # temps à un état T de s'installer avant Ctrl+C : sans le délai, les
        # deux octets sont traités avant qu'un SIGTSTP délivré n'ait figé le
        # groupe, et le test réussirait même sans le correctif.
        os.write(master, b"\x1a")
        self.assertFalse(_descendant_stopped(child.pid))
        os.write(master, b"\x03")
        out += _read_until(master, b"alive")
        self.assertIn(b"rc=-2 back=True", out)
        self.assertEqual(child.wait(10), 0)


# Tient le rôle du CLI : SIGINT rendu à son gestionnaire par défaut (un
# SIGINT ignoré s'hérite, d'un lanceur en arrière-plan), le PTY pris comme
# terminal de contrôle, et aucun contrôle de tâches : la commande de argv[1]
# partage le groupe de l'enfant. Muette si argv[2] vaut « quiet » ; argv[3]
# vaut « cli » pour `ctrl_c_stops_command`, comme todo.py, et « script »
# sinon. Sous REFUSE_KILL, `terminate` et `kill` lèvent PermissionError,
# comme sur le processus d'un autre compte. Dit son code, celui de
# `run_end`, le nombre et la dernière de ses lignes, si le terminal fait
# l'écho, puis « ask », et répète la ligne qu'il lit ensuite : il vit
# encore.
CLI_CHILD = r"""
import fcntl, os, signal, subprocess, sys, termios
signal.signal(signal.SIGINT, signal.default_int_handler)
fcntl.ioctl(0, termios.TIOCSCTTY, 0)
if os.environ.get("REFUSE_KILL"):
    def refuse(process):
        raise PermissionError(1, "Operation not permitted")
    subprocess.Popen.terminate = subprocess.Popen.kill = refuse
from script.execute.execute import Execute
from script.todo import todo_i18n
todo_i18n.use_lang("en")
Execute.ctrl_c_stops_command = sys.argv[3] == "cli"
exe = Execute()
events = []
exe.events = events.append
rc, lines = exe.exec_command_live(
    sys.argv[1],
    False,
    quiet=sys.argv[2] == "quiet",
    return_status_and_output=True,
)
last = lines[-1] if lines else ""
end = events[-1]["rc"]
print(f"rc={rc} end={end} lines={len(lines)} last={last} .", flush=True)
print(f"echo={bool(termios.tcgetattr(0)[3] & termios.ECHO)}", flush=True)
print("ask", flush=True)
print("read", input(), flush=True)
"""

# Une commande qui écrit toutes les 10 ms, et qui dit sur le terminal
# qu'elle a démarré : l'octet Ctrl+C n'est écrit qu'une fois « armed » lu.
# Les deux marqueurs s'écrivent coupés (ar''med) : la commande affichée par
# `exec_command_live` ne les porte pas, seule la commande lancée les imprime.
TICKS = "while :; do echo ti''ck; sleep 0.01; done"
ARMED = "echo ar''med > /dev/tty; "


def _sigint_pending(pid):
    """Vrai si SIGINT attend encore d'être remis à `pid` (SigPnd ou ShdPnd
    de /proc/<pid>/status)."""
    with open(f"/proc/{pid}/status") as f:
        fields = dict(line.split(":\t", 1) for line in f if ":\t" in line)
    pending = int(fields["SigPnd"], 16) | int(fields["ShdPnd"], 16)
    return bool(pending & 1 << (signal.SIGINT - 1))


class TestCtrlCInTheCli(unittest.TestCase):
    """Sans contrôle de tâches, Ctrl+C arrête la commande et rend la main à
    l'appelant, qui continue ; deux Ctrl+C de plus forcent une commande qui
    l'ignore. Chaque enfant a sa session et son PTY : l'octet Ctrl+C
    n'atteint jamais le groupe du lanceur de tests."""

    def spawn(self, command, quiet=True, role="cli", **env):
        """Lance CLI_CHILD sur un PTY neuf et `command`, dans le rôle `role`,
        avec les variables `env` en plus, et attend que la commande soit
        armée."""
        self.master, slave = pty.openpty()
        self.addCleanup(os.close, self.master)
        self.pending = b""
        mode = "quiet" if quiet else "loud"
        self.child = subprocess.Popen(
            [sys.executable, "-c", CLI_CHILD, command, mode, role],
            stdin=slave,
            stdout=slave,
            stderr=slave,
            cwd=REPO,
            env={**os.environ, **env},
            start_new_session=True,
        )
        os.close(slave)
        # Nettoyages en ordre inverse : child.kill d'abord, dont la mort du
        # chef de session envoie SIGHUP au groupe de la commande.
        self.addCleanup(self.child.wait, 10)
        self.addCleanup(self.child.kill)
        self.until(b"armed")

    def until(self, marker, timeout=10.0):
        """Ce que l'enfant a écrit jusqu'à `marker` compris, depuis la
        marque précédente ; ce qui suit attend la marque suivante. Échec au
        délai, ou quand plus personne ne tient l'esclave (EIO)."""
        deadline = time.monotonic() + timeout
        while marker not in self.pending:
            left = deadline - time.monotonic()
            ready = left > 0 and select.select([self.master], [], [], left)[0]
            try:
                chunk = os.read(self.master, 65536) if ready else b""
            except OSError:
                chunk = b""
            if not chunk:
                raise AssertionError(f"{marker!r} not in {self.pending!r}")
            self.pending += chunk
        cut = self.pending.index(marker) + len(marker)
        seen, self.pending = self.pending[:cut], self.pending[cut:]
        return seen

    def ctrl_c(self):
        """Écrit l'octet Ctrl+C, puis attend que l'enfant en ait reçu le
        SIGINT : le terminal renvoie l'écho « ^C » une fois SIGINT envoyé
        au groupe, puis SIGINT quitte les signaux en attente de l'enfant.
        Deux SIGINT remis avant que Python n'appelle le gestionnaire ne
        font qu'un appel : la pause couvre cet appel, que la prochaine
        écriture de la commande, toutes les 10 ms, déclenche au plus tard
        en réveillant la lecture."""
        os.write(self.master, b"\x03")
        self.until(b"^C")
        deadline = time.monotonic() + 10
        while self.child.poll() is None and _sigint_pending(self.child.pid):
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.01)
        self.assertIsNone(self.child.poll(), "Ctrl+C ended the CLI")
        time.sleep(0.1)

    def waits(self):
        """Attend que l'enfant dorme dans l'attente de sa commande
        (`wait4`, que /proc/<pid>/wchan nomme do_wait)."""
        deadline = time.monotonic() + 10
        while True:
            with open(f"/proc/{self.child.pid}/wchan") as f:
                if f.read() == "do_wait":
                    return
            self.assertLess(time.monotonic(), deadline, "never waits")
            time.sleep(0.01)

    def goes_on(self):
        """L'enfant lit encore une ligne après la commande, et finit bien ;
        rend ce qu'il a écrit jusqu'à la répéter."""
        os.write(self.master, b"next\n")
        out = self.until(b"read next")
        self.assertEqual(self.child.wait(10), 0)
        return out

    def test_ctrl_c_stops_the_command_and_not_the_cli(self):
        self.spawn(ARMED + TICKS, quiet=False)
        self.until(b"tick")
        os.write(self.master, b"\x03")
        out = self.until(b"ask")
        self.assertIn(b"rc=-2 end=-2 ", out)
        self.assertIn(b"Command interrupted (Ctrl+C).", out)
        self.goes_on()

    def test_a_second_ctrl_c_while_it_dies_leaves_the_caller_asking(self):
        # Le double Ctrl+C réflexe : la commande meurt au premier, et le
        # second, 0,2 s après, tombe à la question suivante sans arrêter
        # l'appelant. Deux secondes plus tard, Ctrl+C y lève
        # KeyboardInterrupt, comme le gestionnaire par défaut.
        self.spawn(ARMED + TICKS)
        os.write(self.master, b"\x03")
        first = time.monotonic()
        self.assertIn(b"rc=-2 end=-2 ", self.until(b"ask"))
        time.sleep(max(0.0, first + 0.2 - time.monotonic()))
        self.ctrl_c()
        time.sleep(2)
        self.assertIsNone(self.child.poll(), "the second Ctrl+C ended it")
        os.write(self.master, b"\x03")
        self.until(b"KeyboardInterrupt")
        self.assertEqual(self.child.wait(10), -signal.SIGINT)

    def test_outside_the_cli_ctrl_c_still_stops_the_caller(self):
        # Un script qui importe Execute, lancé seul ou par TODO : il meurt
        # de Ctrl+C avec sa commande, au lieu de continuer sur un résultat
        # partiel.
        self.spawn(ARMED + TICKS, role="script")
        os.write(self.master, b"\x03")
        self.assertIn(b"KeyboardInterrupt", self.until(b"KeyboardInterrupt"))
        self.assertEqual(self.child.wait(10), -signal.SIGINT)
        self.assertNotIn(b"ask", self.pending)

    def test_a_command_that_exits_0_on_ctrl_c_is_a_failure(self):
        # Elle a rattrapé Ctrl+C sans finir son travail : un appelant qui
        # teste son code ne la prend pas pour une réussite.
        self.spawn(
            "trap 'exit 0' INT; " + ARMED + "while :; do sleep 0.01; done"
        )
        os.write(self.master, b"\x03")
        self.assertIn(b"rc=-2 end=-2 ", self.until(b"ask"))
        self.goes_on()

    def test_the_terminal_modes_come_back_after_it(self):
        # Tuée, la commande ne défait pas son `stty -echo` : sans retour
        # des modes, la question suivante se taperait à l'aveugle.
        self.spawn("stty -echo; " + ARMED + TICKS)
        os.write(self.master, b"\x03")
        out = self.until(b"ask")
        self.assertIn(b"rc=-2 end=-2 ", out)
        self.assertIn(b"echo=True", out)
        self.goes_on()

    def test_a_second_ctrl_c_terminates_a_command_that_ignores_it(self):
        self.spawn("trap '' INT; " + ARMED + TICKS)
        self.ctrl_c()
        self.ctrl_c()
        self.assertIn(b"rc=-15 end=-15 ", self.until(b"ask"))
        self.goes_on()

    def test_a_third_ctrl_c_kills_it_despite_a_pipe_held_open(self):
        # Le sous-shell en arrière-plan hérite de SIGINT et SIGTERM ignorés
        # et garde le tube ouvert après la mort de la commande : la lecture
        # l'attendrait sans fin. Tube fermé, sa prochaine écriture le tue.
        held = "(while :; do echo held; sleep 0.01; done) & "
        ignores = "trap '' INT TERM; " + held + ARMED
        self.spawn(ignores + "while :; do sleep 0.01; done")
        self.ctrl_c()
        self.ctrl_c()
        self.ctrl_c()
        self.assertIn(b"rc=-9 end=-9 ", self.until(b"ask"))
        self.goes_on()

    def test_a_fourth_ctrl_c_leaves_a_refused_kill_whose_pipe_is_read(self):
        # Sa sortie ailleurs, la commande a fermé le tube : il ne reste que
        # son attente. `terminate` et `kill` refusés, le troisième Ctrl+C
        # lève dans cette attente, et le quatrième lève KeyboardInterrupt
        # chez l'appelant, qui sinon attendrait sans fin.
        away = "exec >/dev/null 2>&1; "
        ignores = "trap '' INT; " + ARMED + away
        self.spawn(ignores + "while :; do sleep 0.01; done", REFUSE_KILL="1")
        self.waits()
        self.ctrl_c()
        self.ctrl_c()
        self.ctrl_c()
        # Popen.wait laisse un quart de seconde à la commande avant de
        # relever KeyboardInterrupt, puis l'appelant attend de nouveau.
        self.waits()
        os.write(self.master, b"\x03")
        self.until(b"KeyboardInterrupt")
        self.assertEqual(self.child.wait(10), -signal.SIGINT)
        self.assertNotIn(b"ask", self.pending)

    def test_the_output_written_while_it_stops_is_read_to_the_end(self):
        # 200 000 lignes, vingt fois le tube : sans lecteur, la commande
        # resterait bloquée sur son écriture et ne finirait jamais.
        flood = "trap 'seq 1 200000; exit 3' INT; "
        self.spawn(flood + ARMED + "while :; do sleep 0.01; done")
        os.write(self.master, b"\x03")
        out = self.until(b"ask")
        self.assertIn(b"rc=3 end=3 lines=200000 last=200000 .", out)
        self.goes_on()

    def test_what_is_typed_while_it_stops_answers_nothing(self):
        # La commande rattrape SIGINT, puis rend son propre code une fois le
        # fichier $GO créé : entre les deux, une ligne tapée attend dans le
        # terminal, et la question suivante ne la lit pas.
        go = os.path.join(
            self.enterContext(tempfile.TemporaryDirectory()), "go"
        )
        wait = 'while [ ! -e "$GO" ]; do sleep 0.01; done; exit 3'
        catch = f"trap 'echo got-int > /dev/tty; {wait}' INT; "
        self.spawn(catch + ARMED + "while :; do sleep 0.01; done", GO=go)
        os.write(self.master, b"\x03")
        self.until(b"got-int")
        os.write(self.master, b"typed\n")
        # L'écho dit que le terminal tient la ligne.
        self.until(b"typed")
        open(go, "w").close()
        self.assertIn(b"rc=3 end=3 ", self.until(b"ask"))
        self.assertNotIn(b"read typed", self.goes_on())

    def test_the_counter_holds_sigint_only_in_the_cli_main_thread(self):
        """Le compteur prend SIGINT le temps de la commande et le rend au
        gestionnaire par défaut ; avec le contrôle de tâches, hors du fil
        principal ou sur un SIGINT ignoré, SIGINT reste ce qu'il était."""
        before = signal.signal(signal.SIGINT, signal.default_int_handler)
        self.addCleanup(signal.signal, signal.SIGINT, before)
        with patch("shutil.which", return_value=None):
            exe = Execute()
        real_read, seen, codes = os.read, [], []

        def read(fd, size):
            seen.append(signal.getsignal(signal.SIGINT))
            return real_read(fd, size)

        def during(run):
            """Le gestionnaire de SIGINT à la dernière lecture de la
            sortie, la commande tournant encore."""
            seen.clear()
            with patch("os.read", side_effect=read):
                run()
            return seen[-1]

        def cli():
            codes.append(exe.exec_command_live("true", False, quiet=True))

        def in_a_thread():
            thread = threading.Thread(target=cli)
            thread.start()
            thread.join(10)

        self.assertIs(during(cli), signal.default_int_handler)
        self.enterContext(patch.object(Execute, "ctrl_c_stops_command", True))
        self.enterContext(patch.object(Execute, "interrupted", None))
        counter = during(cli)
        self.assertIsNot(counter, signal.default_int_handler)
        self.assertTrue(callable(counter))
        self.assertIs(
            signal.getsignal(signal.SIGINT), signal.default_int_handler
        )
        self.assertIs(Execute.interrupted, False)
        exe.job_control = True
        with patch.object(Execute, "_job_control_tty", return_value=None):
            self.assertIs(during(cli), signal.default_int_handler)
        exe.job_control = False
        self.assertIs(during(in_a_thread), signal.default_int_handler)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        self.assertEqual(during(cli), signal.SIG_IGN)
        self.assertEqual(signal.getsignal(signal.SIGINT), signal.SIG_IGN)
        self.assertEqual(codes, [0, 0, 0, 0, 0])

    def test_the_grace_after_an_interrupted_command(self):
        """Une commande interrompue laisse son compteur tenir SIGINT : un
        Ctrl+C dans le délai de grâce est perdu, le premier après lève
        KeyboardInterrupt et rend SIGINT au gestionnaire par défaut, et la
        commande suivante pose le sien à sa place."""
        before = signal.signal(signal.SIGINT, signal.default_int_handler)
        self.addCleanup(signal.signal, signal.SIGINT, before)
        self.enterContext(patch.object(Execute, "ctrl_c_stops_command", True))
        self.enterContext(patch.object(Execute, "interrupted", None))

        def interrupted():
            """Un compteur qui a compté un Ctrl+C, rendu à sa fin."""
            counter = execute._CtrlC()
            counter.catch()
            counter.count = 1
            counter.release()
            return counter

        counter = interrupted()
        self.assertIs(signal.getsignal(signal.SIGINT), counter)
        self.assertIsNone(counter(signal.SIGINT, None))
        self.assertIs(signal.getsignal(signal.SIGINT), counter)
        counter.ended -= counter.GRACE
        with self.assertRaises(KeyboardInterrupt):
            counter(signal.SIGINT, None)
        self.assertIs(
            signal.getsignal(signal.SIGINT), signal.default_int_handler
        )

        counter = interrupted()
        with patch("shutil.which", return_value=None):
            exe = Execute()
        real_read, seen = os.read, []
        started, real_popen = [], subprocess.Popen

        def read(fd, size):
            seen.append(signal.getsignal(signal.SIGINT))
            return real_read(fd, size)

        def popen(*args, **kwargs):
            started.append(real_popen(*args, **kwargs))
            return started[-1]

        with (
            patch("os.read", side_effect=read),
            patch("subprocess.Popen", side_effect=popen),
        ):
            self.assertEqual(
                exe.exec_command_live("true", False, quiet=True), 0
            )
        started[0].stdout.close()
        self.assertIsInstance(seen[-1], execute._CtrlC)
        self.assertIsNot(seen[-1], counter)
        self.assertIs(
            signal.getsignal(signal.SIGINT), signal.default_int_handler
        )

    def test_each_loop_of_commands_stops_after_a_ctrl_c(self):
        """Une boucle de script/todo qui lance une commande par élément lit
        `Execute.interrupted` : un échec la fait passer à l'élément suivant,
        Ctrl+C l'arrête."""
        loops, blind = 0, []
        for path in sorted(
            glob.glob(f"{REPO}/script/todo/**/*.py", recursive=True)
        ):
            with open(path, encoding="utf-8") as f:
                tree = ast.parse(f.read())
            for loop in ast.walk(tree):
                if not isinstance(loop, ast.For):
                    continue
                names = [
                    node.attr
                    for node in ast.walk(loop)
                    if isinstance(node, ast.Attribute)
                ]
                if "exec_command_live" not in names:
                    continue
                loops += 1
                if "interrupted" not in names:
                    blind.append(
                        f"{os.path.relpath(path, REPO)}:{loop.lineno}"
                    )
        self.assertEqual(blind, [])
        self.assertGreaterEqual(loops, 15)


class TestRedactSecrets(unittest.TestCase):
    """Ce qui doit disparaître d'une commande affichée, et ce qui doit rester.

    Le caviardage est le DERNIER rempart et non le premier : un secret sur
    argv est déjà lisible par tout compte de la machine dans
    /proc/<pid>/cmdline, où aucun filtre n'atteint. Ces tests défendent donc
    la trace — terminal, journal, sortie CI — et rien d'autre.

    Trois familles portent un secret, et elles ne se ressemblent pas. Une
    option se reconnaît par son nom, une variable d'environnement par le
    sien, et un jeton d'en-tête n'a NI l'un NI l'autre : il suit le mot
    « Bearer ». Un filtre bâti sur les deux premières laisse passer la
    troisième, qui est exactement celle qu'une API de modèle emploie.

    Les valeurs sont inventées, comme l'exige la règle du dépôt pour tout
    exemple qui illustre un interdit.
    """

    def test_env_api_key_is_redacted(self):
        sortie = redact_secrets("OPENAI_API_KEY=sk-inventeXYZ python x.py")
        self.assertNotIn("sk-inventeXYZ", sortie)
        self.assertIn("OPENAI_API_KEY='***'", sortie)

    def test_env_apikey_without_separator(self):
        sortie = redact_secrets("MISTRAL_APIKEY=abc123 ./run")
        self.assertNotIn("abc123", sortie)

    def test_bearer_header_is_redacted(self):
        sortie = redact_secrets(
            "curl -H 'Authorization: Bearer sk-inventeABC' http://h/v1/models"
        )
        self.assertNotIn("sk-inventeABC", sortie)
        self.assertIn("Authorization: Bearer '***'", sortie)

    def test_basic_header_is_redacted(self):
        sortie = redact_secrets("Authorization: Basic dXNlcjpmYXV4")
        self.assertNotIn("dXNlcjpmYXV4", sortie)

    def test_header_case_is_ignored(self):
        sortie = redact_secrets("authorization: bearer sk-inventeDEF")
        self.assertNotIn("sk-inventeDEF", sortie)

    def test_option_password_still_redacted(self):
        sortie = redact_secrets("odoo --db_password 'inventeGHI'")
        self.assertNotIn("inventeGHI", sortie)

    def test_option_name_survives(self):
        """Le nom de l'option reste : la commande doit rester reproductible."""
        sortie = redact_secrets("odoo --db_password 'inventeJKL'")
        self.assertIn("--db_password", sortie)

    def test_a_pwd_variable_is_redacted_not_the_directory(self):
        sortie = redact_secrets("MASTER_PWD=inventeMNO PWD=/tmp OLDPWD=/srv")
        self.assertEqual(sortie, "MASTER_PWD='***' PWD=/tmp OLDPWD=/srv")

    def test_a_quoted_apostrophe_stays_inside_the_value(self):
        """`shlex.quote` écrit une apostrophe en segments collés
        (« 'it'"'"'s ») : la valeur court jusqu'au premier blanc hors
        guillemets, pour l'option comme pour la variable, et un guillemet
        jamais refermé emporte le reste du mot. Sur disque, rien ne reste
        après le mot guetté que porte le nom d'une option."""
        mot = shlex.quote("it's9inventeAB")
        cut = "tool --password ***"
        for ligne, attendu, stocke in (
            (f"tool --password {mot} -v", "tool --password '***' -v", cut),
            (
                f"tool --token=\"a b\"'c'{mot} -v",
                "tool --token='***' -v",
                "tool --token ***",
            ),
            (f"MASTER_PWD={mot} odoo", "MASTER_PWD='***' odoo", None),
            ("tool --password 'inventeCD", "tool --password '***'", cut),
            (
                "tool --password ab'inventeEF -v",
                "tool --password '***' -v",
                cut,
            ),
        ):
            with self.subTest(ligne=ligne):
                self.assertEqual(redact_secrets(ligne), attendu)
                stocke = stocke or attendu
                self.assertEqual(redact_for_storage(ligne), stocke)

    def test_a_long_word_or_run_of_dashes_is_fast(self):
        """Une option ne commence ni après un caractère de mot ni après un
        tiret, et ne se lit, comme une variable, que suivie d'un blanc ou
        d'un « = » : une ligne de séparateurs, de mots liés par des tirets
        ou d'un mot qui se répète coûte un temps proportionnel à sa
        longueur, jamais à son carré. Une valeur faite de guillemets, collés
        ou jamais refermés, aussi."""
        for ligne in (
            "-" * 16384 + " token",
            "a-" * 8192 + " token",
            "--" + "token" * 3277,
            "PASSWORD" * 8192,
            "--password " + "'a" * 8192,
            "--password '" + "a" * 16384,
            "--password " + "a'" * 8192,
            "A_PASSWORD=" + "\"'" * 8192,
            "PASSWORD_" * 7282 + "= x",
            "PASSWORD_" * 7282 + "=",
        ):
            with self.subTest(debut=ligne[:4]):
                debut = time.monotonic()
                redact_secrets(ligne)
                self.assertLess(time.monotonic() - debut, LINEAR_SECONDS)

    def test_a_path_is_not_a_secret(self):
        """Rien ne disparaît d'une commande qui ne porte aucun secret."""
        commande = "make test_unit_file F=test/test_execute.py"
        self.assertEqual(redact_secrets(commande), commande)

    def test_empty_text_survives(self):
        self.assertEqual(redact_secrets(""), "")
        self.assertIsNone(redact_secrets(None))


class TestRedactUrlCredentials(unittest.TestCase):
    """Identifiants portés par une URL (userinfo, RFC 3986 §3.2.1).

    Ni nom d'option ni nom de variable : le secret suit « user: » ou tient
    lieu de nom d'utilisateur. Schéma, hôte, chemin et nom d'utilisateur
    ordinaire restent, pour que la commande reste lisible. Valeurs inventées.
    """

    def test_password_in_userinfo_is_masked(self):
        sortie = redact_secrets(
            "psql postgresql://odoo:inventeMNO@db.example/base"
        )
        self.assertNotIn("inventeMNO", sortie)
        self.assertIn("postgresql://odoo:***@db.example/base", sortie)

    def test_token_as_password_is_masked(self):
        sortie = redact_secrets(
            "git clone https://x-access-token:inventePQR@forge.example/o/r.git"
        )
        self.assertNotIn("inventePQR", sortie)
        self.assertIn("https://x-access-token:***@forge.example", sortie)

    def test_prefixed_token_as_user_is_masked(self):
        sortie = redact_secrets(
            "git clone https://ghp_inventeSTU@forge.example/o/r.git"
        )
        self.assertNotIn("ghp_inventeSTU", sortie)
        self.assertIn("https://***@forge.example/o/r.git", sortie)

    def test_long_opaque_user_is_masked(self):
        jeton = "invente" + "x" * 30
        sortie = redact_secrets(f"curl https://{jeton}@forge.example/api")
        self.assertNotIn(jeton, sortie)

    def test_token_followed_by_a_password_is_masked(self):
        """Forme GitHub : le jeton tient lieu de nom d'utilisateur ET porte
        un mot de passe (« x-oauth-basic »). La règle du mot de passe masque
        d'abord ce second segment ; celle du jeton doit encore reconnaître
        l'@ à travers le « :*** » qui reste, sans quoi le jeton passe seul en
        clair."""
        jeton = "invente" + "T" * 33
        sortie = redact_secrets(
            f"git clone https://{jeton}:x-oauth-basic@forge.example/o/r.git"
        )
        self.assertNotIn(jeton, sortie)
        self.assertNotIn("x-oauth-basic", sortie)
        self.assertIn("https://***:***@forge.example/o/r.git", sortie)

    def test_password_with_unencoded_at_sign_is_masked_in_full(self):
        """Un « @ » non encodé dans le mot de passe (RFC 3986 l'interdit,
        ça arrive) ne doit pas fuir sa moitié : le masquage s'étend, glouton,
        jusqu'au DERNIER @ avant l'hôte."""
        sortie = redact_secrets(
            "psql postgresql://odoo:inventeP@ss@db.example/base"
        )
        self.assertNotIn("inventeP@ss", sortie)
        self.assertIn("postgresql://odoo:***@db.example/base", sortie)

    def test_a_password_with_a_stop_character_stays_masked(self):
        """Sans « @ » avant « ? », « # », une virgule ou un guillemet, le
        masque va jusqu'au dernier « @ » : un mot de passe qui porte l'un
        d'eux reste caché en entier."""
        for mot in ("ab,cd", "it's", "pa?ss", "pa#ss", 'q"x'):
            ligne = f"git clone https://u:{mot}@forge.example/r.git"
            with self.subTest(mot=mot):
                self.assertEqual(
                    redact_secrets(ligne),
                    "git clone https://u:***@forge.example/r.git",
                )

    def test_the_mask_stops_before_a_query_a_comma_or_a_quote(self):
        """Un « @ » plus loin sur la ligne, après « ? », « # », une virgule
        ou un guillemet, n'appartient pas à l'userinfo : le masque s'arrête
        avant, et l'hôte affiché reste le vrai."""
        for suite in (
            "?next=forged@example",
            "#forged@example",
            ",odoo@db2.example/base",
            '",mail="forged@example',
            "',forged@example",
        ):
            ligne = f"psql postgresql://odoo:inventeYZ@db.example{suite}"
            with self.subTest(suite=suite):
                sortie = redact_secrets(ligne)
                self.assertNotIn("inventeYZ", sortie)
                self.assertEqual(
                    sortie, f"psql postgresql://odoo:***@db.example{suite}"
                )

    def test_ordinary_user_survives(self):
        for commande in (
            "git clone ssh://git@forge.example/o/r.git",
            "curl https://alice@forge.example/x",
        ):
            self.assertEqual(redact_secrets(commande), commande)

    def test_port_and_path_colon_survive(self):
        for commande in (
            "curl http://localhost:8069/web/login",
            "curl https://forge.example/a:b@c",
        ):
            self.assertEqual(redact_secrets(commande), commande)

    def test_url_in_the_middle_of_a_printed_line_is_masked(self):
        ligne = "Cloning from https://u:inventeVWX@forge.example/o/r.git\n"
        self.assertNotIn("inventeVWX", redact_secrets(ligne))

    def test_long_line_without_a_scheme_is_fast(self):
        """Le schéma des deux motifs est borné (32 caractères) : sur une
        ligne sans « :// », chaque position n'essaie qu'un préfixe
        `[a-z0-9+.-]` de 32 caractères au plus avant d'abandonner, et le
        temps reste proportionnel à la longueur, jamais à son carré."""
        ligne = "a." * 10000
        debut = time.monotonic()
        redact_secrets(ligne)
        self.assertLess(time.monotonic() - debut, 1.0)


class TestRedactSecretsByLine(unittest.TestCase):
    """Les lignes de `redact_secrets(texte)`, chacune avec le nombre de
    lignes du texte qu'elle couvre : une valeur entre guillemets que la
    marque remplace en retire les fins de ligne. Valeurs inventées."""

    def test_a_quoted_value_joins_the_lines_it_spans(self):
        for texte, attendu in (
            ("", [("", 1)]),
            ("a\nb", [("a", 1), ("b", 1)]),
            (
                "a\nTOKEN='inve\nnteAB' b\nc",
                [("a", 1), ("TOKEN='***' b", 2), ("c", 1)],
            ),
            (
                "A_TOKEN='x\ny' B_TOKEN='z\nw' c\nd",
                [("A_TOKEN='***' B_TOKEN='***' c", 3), ("d", 1)],
            ),
            (
                'tool --password "inve\n\nnteCD" -v\nd',
                [("tool --password '***' -v", 3), ("d", 1)],
            ),
            (
                "MASTER_PWD='a\nb' --token 'c\nd'\ne",
                [("MASTER_PWD='***' --token '***'", 3), ("e", 1)],
            ),
            # La valeur d'une option en fin de ligne est la ligne suivante :
            # masquée, sans rien joindre.
            ("--password\ninventeEF", [("--password", 1), ("'***'", 1)]),
        ):
            with self.subTest(texte=texte):
                lignes = execute.redact_secrets_by_line(texte)
                self.assertEqual(lignes, attendu)
                self.assertEqual(
                    "\n".join(ligne for ligne, _ in lignes),
                    redact_secrets(texte),
                )

    def test_the_lines_are_counted_in_linear_time(self):
        size = 64 * 1024
        for texte in (
            "TOKEN='" + "\n" * size + "'",
            "TOKEN='a\nb' " * (size // 12),
            "--password '\n' " * (size // 15),
            "--password\n" * (size // 11),
            "a\n" * (size // 2),
        ):
            with self.subTest(debut=texte[:12]):
                debut = time.monotonic()
                execute.redact_secrets_by_line(texte)
                self.assertLess(time.monotonic() - debut, LINEAR_SECONDS)


class TestRedactForStorage(unittest.TestCase):
    """Ce qu'une ligne de sortie devient avant d'être gardée sur disque :
    `redact_secrets`, puis le reste d'une ligne qui imprime un mot de passe
    après son mot, puis tout ce qui suit le premier mot guetté
    (SECRET_WORDS), séparateur compris. Valeurs inventées."""

    def test_a_printed_password_is_masked_after_its_word(self):
        for ligne, attendu in (
            ("Password: inventeAB", "Password ***"),
            ("admin password=inventeCD", "admin password ***"),
            ("passwd inventeEF", "passwd ***"),
            ("Mot de passe : inventeGH", "Mot de passe ***"),
            ("PASSWORD:inventeIJ et la suite", "PASSWORD ***"),
            ("a\nPassword: inventeKL\nb", "a\nPassword ***\nb"),
            # Une clé de configuration ou de JSON, et l'espace insécable
            # de la typographie française.
            ("admin_passwd = inventeMN", "admin_passwd ***"),
            ("db_password = inventeOP", "db_password ***"),
            ("POSTGRES_PASSWORD: inventeQR", "POSTGRES_PASSWORD ***"),
            ('{"password": "inventeST"}', '{"password ***'),
            ("{'password': 'inventeUV'}", "{'password ***"),
            ("Mot de passe : inventeWX", "Mot de passe ***"),
            ("Password? inventeYZ", "Password ***"),
        ):
            with self.subTest(ligne=ligne):
                self.assertEqual(redact_for_storage(ligne), attendu)

    def test_a_secret_key_is_masked_after_its_separator(self):
        """Une clé de configuration, de variable ou de JSON : un nom en
        majuscules préfixé, un suffixe collé, ou les clés passphrase,
        api_key, token et secret, suivis de « : », « = » ou « ? »."""
        for ligne, attendu in (
            ("PGPASSWORD: inventeAB", "PGPASSWORD ***"),
            ("new_password1 = inventeCD", "new_password ***"),
            ("password_confirm: inventeEF", "password ***"),
            ("passphrase: inventeGH", "passphrase ***"),
            ("api_key: inventeIJ", "api_key ***"),
            ("apikey = inventeKL", "apikey ***"),
            ('{"api-key": "inventeMN"}', '{"api-key ***'),
            ("token: inventeOP", "token ***"),
            ("GITHUB_TOKEN = inventeQR", "GITHUB_TOKEN ***"),
            ("client_secret: inventeST", "client_secret ***"),
            ("Secret? inventeUV", "Secret ***"),
        ):
            with self.subTest(ligne=ligne):
                self.assertEqual(redact_for_storage(ligne), attendu)

    def test_a_camel_case_or_glued_key_is_masked(self):
        """Le mot d'un secret se trouve n'importe où dans le nom de la clé :
        derrière une minuscule (camelCase) ou collé à un préfixe."""
        for ligne, attendu in (
            ("accessToken: inventeAB", "accessToken ***"),
            ("refreshToken=inventeCD", "refreshToken ***"),
            ("clientSecret: inventeEF", "clientSecret ***"),
            ("adminPassword: inventeGH", "adminPassword ***"),
            ("apiKey: inventeIJ", "apiKey ***"),
            ("pgpassword=inventeKL", "pgpassword ***"),
            ('{"accessToken": "inventeMN"}', '{"accessToken ***'),
        ):
            with self.subTest(ligne=ligne):
                self.assertEqual(redact_for_storage(ligne), attendu)

    def test_a_word_that_holds_a_secret_word_masks_the_rest(self):
        """Sans séparateur derrière elle, une clé n'en est pas une pour les
        motifs ; le mot guetté qu'elle porte, en tête d'un mot plus long ou
        seul, masque pourtant ce qui le suit. « passport » n'en porte
        aucun."""
        for ligne, attendu in (
            ("passport number 12", "passport number 12"),
            ("tokenizer output ready", "token ***"),
            ("token expired, sign in again", "token ***"),
            ("the secret ingredient", "the secret ***"),
            ("Passports: 3 checked", "Passports: 3 checked"),
        ):
            with self.subTest(ligne=ligne):
                self.assertEqual(redact_for_storage(ligne), attendu)

    def test_a_long_key_like_word_is_fast(self):
        """Une clé se lit mot par mot, séparateur et valeur vérifiés avant
        d'y chercher le mot d'un secret : un mot qui en répète un, sans
        valeur ou avec une valeur déjà masquée, coûte un temps
        proportionnel à sa longueur."""
        for ligne in (
            "PASSWORD" * 8192 + ":",
            "PASSWORD_" * 8192 + ": x",
            "PASSWORD" * 8192 + "='***'",
            "token" * 13107 + " = ",
            "A_" * 32768 + "x: y",
            "password-" * 8192 + ":",
            "a-" * 32768 + "x: y",
            "xpassword" * 7282 + ":",
            "aToken" * 10922 + ": x",
            "pgPasswor" * 7282 + ": x",
        ):
            with self.subTest(debut=ligne[:10], fin=ligne[-5:]):
                debut = time.monotonic()
                redact_for_storage(ligne)
                self.assertLess(time.monotonic() - debut, LINEAR_SECONDS)

    def test_a_run_of_blanks_is_read_once(self):
        """Une clé commence par un caractère de nom : une suite de blancs,
        espaces, tabulations ou les deux, n'en commence aucune et se lit
        une fois, par le nom qui la précède, jamais depuis chacun de ses
        blancs. 64 Kio se lisent sous LINEAR_SECONDS."""
        run = 64 * 1024
        for ligne in (
            "token" + " " * run + "x",
            "pass" + "\t" * run,
            "pass" + "\t" * run + "x",
            "key" + " \t" * (run // 2) + "| 12",
            "| key |" + " " * run + "| 12 |",
            "password" + " " * run,
            "token:" + " " * run,
            "key" + " " * run + ":" + " " * run,
            "secret " * (run // 7),
        ):
            with self.subTest(debut=ligne[:6], fin=ligne[-3:]):
                debut = time.monotonic()
                redact_for_storage(ligne)
                self.assertLess(time.monotonic() - debut, LINEAR_SECONDS)

    def test_each_mask_passes_the_fast_path(self):
        """Une ligne sans mot de `_TRIGGERS` n'essaie aucun motif : chaque
        forme qu'un motif masque en porte donc un, casse comprise (« ſ »
        égale « s » sans casse)."""
        for ligne in (
            "mysql --password inventeAB",
            "PGPASSWORD=inventeCD psql",
            "MASTER_PWD=inventeEF odoo",
            "Authorization: Bearer inventeGH",
            "git clone https://u:inventeIJ@forge.example/r",
            "git clone https://ghp_inventeKL@forge.example/r",
            "Password: inventeMN",
            "Paſſword: inventeOP",
            "PGPASSWORD: inventeQR",
            "passphrase: inventeST",
            "api_key: inventeUV",
            "token: inventeWX",
            "secret: inventeYZ",
        ):
            with self.subTest(ligne=ligne):
                self.assertNotIn("invente", redact_for_storage(ligne))

    def test_a_secret_word_masks_the_rest_of_its_line(self):
        """Un mot guetté, sans casse et sans borne de mot, masque la fin de
        sa ligne où qu'il tombe : collé au mot qui le précède, derrière un
        tiret, sans séparateur, un « i » écrit « ı » ou « İ » compris. Rien
        ne suit le mot : rien à masquer. Une ligne dont casefold change la
        longueur avant la fin de son mot ne l'y situe pas : elle part
        entière."""
        for ligne, attendu in (
            ("Loadingpasswd inventeAB", "Loadingpasswd ***"),
            ("x-ypasswd = inventeCD", "x-ypasswd ***"),
            ("-token = inventeEF", "-token ***"),
            ("tool -token = inventeGH", "tool -token ***"),
            ("abaccessToken=inventeIJ", "abaccessToken ***"),
            ("Bearer inventeKL", "Bearer ***"),
            ("API key: inventeMN", "API key ***"),
            ("passphrase inventeOP", "passphrase ***"),
            ("Loadingmot de passe inventeQR", "Loadingmot de passe ***"),
            ("Paſſword inventeST", "Paſſword ***"),
            ("Loadingapıkey inventeYZ", "Loadingapıkey ***"),
            ("Authorİzation inventeAB", "Authorİzation ***"),
            ("a\nLoadingpasswd inventeUV\nb", "a\nLoadingpasswd ***\nb"),
            ("Straße token inventeWX", "***"),
            ("Enter the password", "Enter the password"),
            ("OPENAI_API_KEY=inventeCD run", "OPENAI_API_KEY ***"),
        ):
            with self.subTest(ligne=ligne):
                self.assertEqual(redact_for_storage(ligne), attendu)

    def test_the_cut_falls_where_the_folded_prefix_ends(self):
        """La coupure se place dans la ligne quand ce qui précède la fin du
        mot garde sa longueur une fois passé par casefold : des « ß » qui
        allongent le début et autant de points combinants qui raccourcissent
        la fin ne la déplacent pas dans la valeur, qui part alors avec la
        ligne entière. Ce qui suit le mot peut changer de longueur."""
        for ligne, attendu in (
            ("ßßßßpasswd inventeWX" + "\u0307" * 4, "***"),
            ("ß" * 12 + "token inventeWX" + "\u0307" * 12, "***"),
            ("\u0307" * 4 + "passwd inventeWX", "***"),
            ("passwd inventeWX Straße", "passwd ***"),
            ("token inventeWX" + "\u0307" * 3, "token ***"),
        ):
            with self.subTest(ligne=ligne):
                self.assertEqual(redact_for_storage(ligne), attendu)

    def test_a_combining_dot_inside_a_secret_word_hides_nothing(self):
        """Un point combinant (U+0307), que `_fold` retire, glissé dans un
        mot guetté ne le cache pas au contrôle rapide : la ligne se masque
        comme le mot seul la masquerait, sur une ligne ou dans un texte."""
        for ligne in (
            "pas\u0307sword inventeWX",
            "to\u0307ken: inventeYZ",
            "Bea\u0307rer inventeAB",
            "a\npas\u0307swd = inventeCD\nb",
        ):
            with self.subTest(ligne=ligne):
                self.assertNotIn("invente", redact_for_storage(ligne))
                self.assertTrue(holds_secret_trigger(ligne))

    def test_a_line_joined_by_a_quoted_value_hides_no_secret_word(self):
        """Une valeur entre guillemets que `redact_secrets` masque d'une
        ligne à l'autre joint ces lignes en une : si l'une portait un mot
        guetté, que la marque « '***' » peut avoir emporté avec la valeur,
        la ligne jointe part entière ; sinon elle s'écrit masquée. Les
        autres lignes gardent leur forme."""
        for texte, attendu in (
            ("MASTER_PWD='a\n'api_key -> inventeWX", "***"),
            ("a\nGITHUB_TOKEN='inve\nnteAB' b\nc", "a\n***\nc"),
            ("MASTER_PWD='inve\nnteCD' odoo\nd", "MASTER_PWD='***' odoo\nd"),
            ("--password\ninventeEF", "--password\n'***'"),
        ):
            with self.subTest(texte=texte):
                self.assertEqual(redact_for_storage(texte), attendu)

    def test_a_secret_word_inside_a_masked_value_masks_the_line(self):
        """Le mot guetté se cherche dans la ligne avant les motifs : dans la
        valeur qu'un motif cache (identifiant d'URL, MASTER_PWD=), ou
        derrière une telle valeur, il ne se situe plus dans la ligne
        masquée, qui part entière."""
        for ligne in (
            "MASTER_PWD=secretAB inventeCD",
            "git clone https://u:tokenEF@forge.example/r inventeGH",
            "clone https://u:inventeIJ@forge.example/r token inventeKL",
        ):
            with self.subTest(ligne=ligne):
                self.assertEqual(redact_for_storage(ligne), "***")

    def test_a_line_without_a_secret_word_is_unchanged(self):
        """« pass », « pwd » et « auth » seuls ne sont pas des mots
        guettés, ni un mot qui ne fait que ressembler à l'un d'eux."""
        for ligne in (
            "Tests passed: 12",
            "pwd",
            "author: x",
            "passport number 12",
            "bypass mode on",
            "Passports: 3 checked",
            "authentication done",
            "keyboard: us",
        ):
            with self.subTest(ligne=ligne):
                self.assertEqual(redact_for_storage(ligne), ligne)

    def test_the_secret_word_scan_is_linear(self):
        """Chaque mot guetté se cherche une fois dans la ligne passée par
        `_fold` : 64 Kio de mots guettés, de leurs débuts ou de blancs se
        masquent sous LINEAR_SECONDS."""
        size = 64 * 1024
        for ligne in (
            "password" * (size // 8),
            "passw" * (size // 5),
            "mot de pass" * (size // 11),
            "api ke" * (size // 6),
            "tokenx " * (size // 7),
            " " * size + "token x",
            "ß" * size + "token x",
            "a\n" * (size // 2),
            "token x\n" * (size // 8),
        ):
            with self.subTest(debut=ligne[:10]):
                debut = time.monotonic()
                redact_for_storage(ligne)
                self.assertLess(time.monotonic() - debut, LINEAR_SECONDS)

    def test_redact_secrets_comes_first(self):
        ligne = "Cloning https://u:inventeMN@forge.example/o/r.git"
        self.assertEqual(
            redact_for_storage(ligne),
            "Cloning https://u:***@forge.example/o/r.git",
        )

    def test_a_prompt_keeps_its_word_and_other_lines_survive(self):
        """Une invite perd ce qui suit son mot guetté, séparateur compris ;
        une ligne sans mot guetté reste entière."""
        for ligne, attendu in (
            ("Password: ", "Password ***"),
            ("[sudo] password:", "[sudo] password ***"),
            ("Passwords rotate daily", "Password ***"),
            ("passwordless login", "password ***"),
            ("make test_unit", "make test_unit"),
            ("", ""),
        ):
            with self.subTest(ligne=ligne):
                self.assertEqual(redact_for_storage(ligne), attendu)
        self.assertIsNone(redact_for_storage(None))


class TestHoldsSecretTrigger(unittest.TestCase):
    """Un appelant qui doit couper un texte avant sa fin de ligne (todo web,
    tasklog.py) s'en sert pour savoir si `redact_for_storage` guette encore
    un mot dedans."""

    def test_a_trigger_word_is_found_whole_or_split_by_the_caller(self):
        for texte in (
            "Password: ",
            "clone https://",
            "PGPASSWORD=",
            "Mot de passe : inv",
            "Bearer x",
        ):
            with self.subTest(texte=texte):
                self.assertTrue(holds_secret_trigger(texte))

    def test_none_and_a_plain_line_hold_no_trigger(self):
        for texte in ("", None, "make test_unit", "no newline"):
            with self.subTest(texte=texte):
                self.assertFalse(holds_secret_trigger(texte))


if __name__ == "__main__":
    unittest.main()
