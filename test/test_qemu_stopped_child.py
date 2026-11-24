#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Runner.run signale un descendant arrêté par le noyau au lieu d'attendre.

Un processus à l'état T (SIGSTOP, SIGTTOU, SIGTTIN) ne reprend que sur
SIGCONT : sans surveillance, deploy_qemu.py l'attend sans fin. Ces tests
gardent :

- la lecture de /proc/<pid>/stat, comm à parenthèses compris ;
- la recherche des arrêtés parmi TOUS les descendants, le plus profond
  d'abord, sans les processus tracés ni les étrangers à l'arbre ;
- un seul message par épisode d'arrêt, après le délai de grâce ;
- aucune surveillance hors Linux ;
- de bout en bout, avec de vrais processus arrêtés, capture comprise ;
- Runner.run garde ses valeurs de retour, son message d'échec, son
  dry-run, et Ctrl+C tue l'enfant.

Les tests qui créent de vrais processus arrêtés ont des délais courts, un
chien de garde qui tue tout l'arbre, et faulthandler pour ne jamais pendre.
"""

import faulthandler
import importlib.util
import io
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.argv = ["todo.py"]

RACINE = Path(__file__).resolve().parents[1]


def _deploy_qemu():
    """deploy_qemu.py chargé comme module, comme le fait todo.py."""
    path = RACINE / "script/qemu/deploy_qemu.py"
    spec = importlib.util.spec_from_file_location("deploy_qemu", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


DQ = _deploy_qemu()

LINUX = sys.platform.startswith("linux") and Path("/proc").is_dir()
# Un enfant Python qui s'arrête lui-même, comme le ferait un SIGTTOU.
SE_SUSPEND = "import os,signal; os.kill(os.getpid(), signal.SIGSTOP)"


def _stat(proc: Path, pid: int, comm: str, etat: str, ppid: int) -> None:
    d = proc / str(pid)
    d.mkdir(exist_ok=True)
    (d / "stat").write_text(f"{pid} ({comm}) {etat} {ppid} {pid} {pid} 0 -1")


def _descendants(racine: int) -> list[int]:
    """racine et tous ses descendants vivants, lus dans /proc."""
    enfants: dict[int, list[int]] = {}
    for d in Path("/proc").iterdir():
        if not d.name.isdigit():
            continue
        try:
            lu = DQ.parse_proc_stat((d / "stat").read_text())
        except OSError:
            continue
        if lu:
            enfants.setdefault(lu[3], []).append(lu[0])
    tous, file = [], [racine]
    while file:
        pid = file.pop()
        if pid in tous:
            continue
        tous.append(pid)
        file.extend(enfants.get(pid, ()))
    return tous


def _tuer(pid: int, sig=signal.SIGKILL) -> None:
    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        pass


class ParseProcStat(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(
            (123, "apt-get", "T", 45),
            DQ.parse_proc_stat("123 (apt-get) T 45 123 123 0 -1"),
        )

    def test_comm_with_spaces_and_parens(self):
        self.assertEqual(
            (7, "a) b (c)", "S", 1),
            DQ.parse_proc_stat("7 (a) b (c)) S 1 0 0"),
        )

    def test_malformed_returns_none(self):
        for texte in ("", "garbage", "12 (x)", "12 (x) T notanint"):
            with self.subTest(texte=texte):
                self.assertIsNone(DQ.parse_proc_stat(texte))


class StoppedDescendants(unittest.TestCase):
    def test_fake_proc_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = Path(tmp)
            _stat(proc, 100, "sudo", "S", 1)
            _stat(proc, 101, "sh", "S", 100)
            _stat(proc, 102, "apt-get", "T", 101)
            _stat(proc, 103, "dpkg", "T", 100)
            _stat(proc, 104, "strace", "t", 100)
            _stat(proc, 200, "autre", "T", 1)
            (proc / "self").mkdir()
            (proc / "105").mkdir()
            self.assertEqual(
                [(102, "apt-get"), (103, "dpkg")],
                DQ.stopped_descendants(100, proc),
            )
            self.assertEqual(
                [(200, "autre")], DQ.stopped_descendants(200, proc)
            )
        self.assertEqual([], DQ.stopped_descendants(100, proc))


class Watch(unittest.TestCase):
    def test_grace_once_and_rearm(self):
        horloge = iter([0, 29, 30, 60, 61, 70, 100])
        messages: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            proc = Path(tmp)
            _stat(proc, 100, "sudo", "S", 1)
            _stat(proc, 102, "apt-get", "T", 100)
            w = DQ.StoppedChildWatch(
                100,
                "sudo apt-get update",
                grace=30,
                proc_root=proc,
                now=lambda: next(horloge),
                out=messages.append,
            )
            with mock.patch.object(DQ.sys, "platform", "linux"):
                self.assertEqual([], w.check())
                self.assertEqual([], w.check())
                self.assertEqual([], messages)
                self.assertEqual([102], w.check())
                self.assertEqual(1, len(messages))
                for attendu in (
                    "pid 102",
                    "kill -CONT 102",
                    "SIGTTOU",
                    "sudo apt-get update",
                ):
                    self.assertIn(attendu, messages[0])
                self.assertEqual([], w.check())
                _stat(proc, 102, "apt-get", "S", 100)
                self.assertEqual([], w.check())
                _stat(proc, 102, "apt-get", "T", 100)
                self.assertEqual([], w.check())
                self.assertEqual([102], w.check())
        self.assertEqual(2, len(messages))

    def test_noop_off_linux(self):
        espion = mock.Mock(return_value=[(1, "x")])
        with (
            mock.patch.object(DQ.sys, "platform", "darwin"),
            mock.patch.object(DQ, "stopped_descendants", espion),
        ):
            w = DQ.StoppedChildWatch(1, "x", grace=0)
            self.assertEqual([], w.check())
            self.assertEqual(
                (0, ""), DQ.run_watched([sys.executable, "-c", "pass"])
            )
        espion.assert_not_called()


class Message(unittest.TestCase):
    def _msg(self, **kw):
        base = dict(waited=31, foreign=False, background=False, label="cmd")
        base.update(kw)
        return DQ.stopped_message(42, "apt-get", "apt-get update", **base)

    def test_sudo_prefix_and_background_hint(self):
        m = self._msg(foreign=True, background=False)
        self.assertIn("sudo kill -CONT 42", m)
        self.assertIn("sudo kill 42", m)
        self.assertNotIn("« fg »", m)
        m = self._msg(foreign=False, background=True)
        self.assertIn("kill -CONT 42", m)
        self.assertNotIn("sudo ", m)
        self.assertIn("« fg »", m)
        m = DQ.stopped_message(
            42,
            "apt-get",
            "",
            waited=31,
            foreign=False,
            background=False,
            label="cmd",
        )
        self.assertIn("\n    apt-get\n", m)


class _Garde(unittest.TestCase):
    """Ni le test ni ses enfants ne peuvent pendre.

    faulthandler termine le processus de test au bout de 60 s ; le chien de
    garde tue tout l'arbre lancé au bout de 10 s. Popen est enveloppé pour
    connaître la racine de cet arbre. Seul un arbre dont la racine n'est pas
    encore récoltée est tué : un pid récolté est libre et peut désigner un
    processus étranger, alors qu'un pid non récolté reste réservé à l'enfant.
    """

    GARDE_S = 10.0

    def setUp(self):
        faulthandler.dump_traceback_later(60, exit=True)
        self.racines: list[int] = []
        self.procs: list[subprocess.Popen] = []
        vrai = subprocess.Popen

        def popen(*a, **kw):
            p = vrai(*a, **kw)
            self.racines.append(p.pid)
            self.procs.append(p)
            return p

        patch = mock.patch.object(DQ.subprocess, "Popen", popen)
        patch.start()
        self.addCleanup(patch.stop)
        self.chien = threading.Timer(self.GARDE_S, self._tout_tuer)
        self.chien.daemon = True
        self.chien.start()

    def tearDown(self):
        self.chien.cancel()
        self._tout_tuer()
        faulthandler.cancel_dump_traceback_later()

    def _tout_tuer(self):
        for p in self.procs:
            if p.returncode is not None:
                continue
            for pid in reversed(_descendants(p.pid)):
                _tuer(pid)


class GardeNeTuePasUnPidRecolte(_Garde):
    def test_reaped_root_is_left_alone(self):
        with DQ.subprocess.Popen([sys.executable, "-c", "pass"]) as p:
            pass
        self.assertIsNotNone(p.returncode)
        espion = mock.Mock()
        with mock.patch.object(sys.modules[__name__], "_tuer", espion):
            self._tout_tuer()
        espion.assert_not_called()

    @unittest.skipUnless(LINUX, "/proc de Linux requis")
    def test_running_root_is_killed(self):
        p = DQ.subprocess.Popen(["sleep", "30"])
        self._tout_tuer()
        self.assertEqual(-signal.SIGKILL, p.wait(timeout=5))


@unittest.skipUnless(LINUX, "/proc de Linux requis")
class EndToEnd(_Garde):
    def _surveiller(self, cmd, action, **kw):
        messages: list[str] = []
        signales: list[int] = []

        def rappel(msg):
            messages.append(msg)
            pid = int(msg.split("pid ", 1)[1].split()[0])
            signales.append(pid)
            _tuer(pid, action)

        debut = time.monotonic()
        res = DQ.run_watched(cmd, poll=0.05, grace=0.3, out=rappel, **kw)
        return res, messages, signales, time.monotonic() - debut

    def test_self_sigstop_child_detected_then_killed(self):
        (code, _), messages, signales, duree = self._surveiller(
            [sys.executable, "-c", SE_SUSPEND], signal.SIGKILL
        )
        self.assertEqual(-signal.SIGKILL, code)
        self.assertEqual(1, len(messages))
        self.assertEqual([self.racines[0]], signales)
        self.assertIn(f"pid {signales[0]}", messages[0])
        self.assertIn("python", messages[0])
        self.assertLess(duree, 5)

    def test_grandchild_detected_capture_still_collects(self):
        script = f"{sys.executable} -c '{SE_SUSPEND}'; echo after"
        res, messages, signales, _ = self._surveiller(
            ["sh", "-c", script], signal.SIGKILL, capture=True
        )
        self.assertEqual(1, len(signales))
        self.assertNotEqual(self.racines[0], signales[0])
        # Le shell peut annoncer l'enfant tué (« Killed ») sur stderr, que
        # la capture réunit à stdout : seule la fin de la sortie est fixe.
        code, sortie = res
        self.assertEqual(0, code)
        self.assertTrue(sortie.endswith("after\n"), sortie)

    def test_sigcont_resumes_sigstop(self):
        (code, _), messages, _s, _d = self._surveiller(
            [sys.executable, "-c", SE_SUSPEND], signal.SIGCONT
        )
        self.assertEqual(0, code)
        self.assertEqual(1, len(messages))

    def test_large_capture_no_deadlock(self):
        n = 2_000_000
        res = DQ.run_watched(
            [sys.executable, "-c", f"import sys; sys.stdout.write('x'*{n})"],
            capture=True,
            poll=0.01,
        )
        self.assertEqual((0, "x" * n), res)


class RunnerIntegration(_Garde):
    def _runner(self, dry_run=False):
        return DQ.Runner(False, dry_run)

    def test_check_exit_message_unchanged(self):
        cmd = [sys.executable, "-c", "raise SystemExit(3)"]
        with (
            redirect_stdout(io.StringIO()),
            self.assertRaises(SystemExit) as cm,
        ):
            self._runner().run(cmd)
        self.assertIn("Échec de la commande (code 3)", str(cm.exception))
        self.assertIn(" ".join(cmd), str(cm.exception))

    def test_capture_returns_and_prints(self):
        sortie = io.StringIO()
        with redirect_stdout(sortie):
            res = self._runner().run(
                [sys.executable, "-c", "print('hi')"], capture=True
            )
        self.assertEqual((0, "hi\n"), res)
        texte = sortie.getvalue()
        self.assertIn("  $ ", texte)
        self.assertLess(texte.index("  $ "), texte.index("hi"))

    def test_check_false_returns_none(self):
        with redirect_stdout(io.StringIO()):
            res = self._runner().run(
                [sys.executable, "-c", "raise SystemExit(3)"], check=False
            )
        self.assertIsNone(res)

    def test_dry_run_no_popen(self):
        espion = mock.Mock()
        with (
            mock.patch.object(DQ.subprocess, "Popen", espion),
            redirect_stdout(io.StringIO()),
        ):
            res = self._runner(dry_run=True).run(["true"], capture=True)
        self.assertEqual((0, ""), res)
        espion.assert_not_called()

    @unittest.skipUnless(LINUX, "/proc de Linux requis")
    def test_keyboard_interrupt_kills_child(self):
        vus: list[int] = []

        def interrompre(root_pid, *_a, **_k):
            vus.append(root_pid)
            raise KeyboardInterrupt

        debut = time.monotonic()
        with (
            mock.patch.object(DQ, "stopped_descendants", interrompre),
            self.assertRaises(KeyboardInterrupt),
        ):
            DQ.run_watched(["sleep", "30"], poll=0.05)
        self.assertLess(time.monotonic() - debut, 3)
        self.assertEqual(self.racines[:1], vus)
        with self.assertRaises(ProcessLookupError):
            os.kill(vus[0], 0)


if __name__ == "__main__":
    unittest.main()
