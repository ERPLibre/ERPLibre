#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le processus de recherche par expression régulière après un `fork` :
le fils lance le sien, celui du parent n'est ni signalé ni désynchronisé.

Un serveur en prefork forke ses workers après l'import des modules : le
module doit y rester juste. N'importe que la bibliothèque standard et
`erplibre_mail_core`.
"""

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
import warnings
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parent.parent
NOYAU = RACINE / "script" / "lib" / "erplibre_mail_core"
if str(NOYAU) not in sys.path:
    sys.path.insert(0, str(NOYAU))

from erplibre_mail_core.rules import regex_worker  # noqa: E402

PEUT_FORKER = hasattr(os, "fork")


def forker():
    """`os.fork()` sans l'avertissement d'un processus à plusieurs fils."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return os.fork()


def attendre(pid: int, delai: float = 20.0) -> int:
    """Le code de sortie du fils `pid` ; un fils encore vivant après
    `delai` secondes est tué et rend -1 (bloqué)."""
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        fini, statut = os.waitpid(pid, os.WNOHANG)
        if fini:
            return os.waitstatus_to_exitcode(statut)
        time.sleep(0.02)
    os.kill(pid, 9)
    os.waitpid(pid, 0)
    return -1


@unittest.skipUnless(PEUT_FORKER, "os.fork absent")
class TestFork(unittest.TestCase):
    def setUp(self):
        worker = regex_worker._WORKER
        self.assertEqual(worker.search("b+", ["abbb"], 5.0), 0)
        self.proc = worker._proc
        self.assertIsNotNone(self.proc)

    def assert_parent_intact(self):
        worker = regex_worker._WORKER
        self.assertIs(worker._proc, self.proc)
        self.assertIsNone(self.proc.poll())
        self.assertEqual(worker.search("z", ["a", "z"], 5.0), 1)
        self.assertEqual(worker.search("q", ["a"], 5.0), -1)

    def test_a_forked_child_starts_its_own_worker(self):
        pid = forker()
        if pid == 0:
            code = 1
            try:
                worker = regex_worker._WORKER
                if worker._proc is None and (
                    worker.search("b+", ["abbb"], 5.0) == 0
                ):
                    code = 0
                worker.close()
            finally:
                os._exit(code)
        self.assertEqual(attendre(pid), 0)
        self.assert_parent_intact()

    def test_a_forked_child_can_fork_again(self):
        """Le verrou que recrée un fils est celui que son propre `fork`
        prend : un petit-fils ne bloque pas."""
        pid = forker()
        if pid == 0:
            code = 1
            try:
                petit = forker()
                if petit == 0:
                    os._exit(
                        0
                        if regex_worker._WORKER.search("b", ["b"], 5.0) == 0
                        else 1
                    )
                code = attendre(petit)
            finally:
                os._exit(code)
        self.assertEqual(attendre(pid, 40.0), 0)
        self.assert_parent_intact()

    def test_a_fork_waits_for_the_request_in_flight(self):
        """Une requête écrite mais pas encore vidée au moment du `fork` ne
        doit pas partir une seconde fois depuis le fils."""
        worker = regex_worker._WORKER
        pret = threading.Event()
        reponse = []

        def requete():
            with worker._lock:
                proc = worker._proc
                proc.stdin.write(
                    (json.dumps(["x", ["x"]]) + "\n").encode("ascii")
                )
                pret.set()
                time.sleep(0.3)
                proc.stdin.flush()
                reponse.append(worker._readline(proc, 5.0))

        fil = threading.Thread(target=requete)
        fil.start()
        pret.wait(5)
        pid = forker()
        if pid == 0:
            os._exit(0)
        fil.join(10)
        self.assertEqual(attendre(pid), 0)
        self.assertEqual(reponse, [b"0"])
        self.assertEqual(worker.search("a", ["a"], 5.0), 0)
        self.assertEqual(worker.search("b", ["a", "b"], 5.0), 1)
        self.assertEqual(worker.search("c", ["a"], 5.0), -1)
        self.assert_parent_intact()

    def test_a_child_leaving_normally_spares_the_parent_worker(self):
        script = textwrap.dedent(
            f"""
            import os, sys, warnings
            sys.path.insert(0, {str(NOYAU)!r})
            from erplibre_mail_core.rules import regex_worker
            w = regex_worker._WORKER
            assert w.search("b", ["b"], 5.0) == 0
            avant = w._proc.pid
            warnings.simplefilter("ignore", DeprecationWarning)
            pid = os.fork()
            if pid == 0:
                sys.exit(0)
            _p, statut = os.waitpid(pid, 0)
            assert os.waitstatus_to_exitcode(statut) == 0
            assert w._proc.pid == avant and w._proc.poll() is None
            assert w.search("c", ["a", "c"], 5.0) == 1
            print("ok")
            """
        )
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        env.pop("PYTHONPATH", None)
        with tempfile.TemporaryDirectory() as dossier:
            sortie = subprocess.run(
                [sys.executable, "-B", "-c", script],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=dossier,
                env=env,
            )
        self.assertEqual(sortie.returncode, 0, sortie.stderr)
        self.assertEqual(sortie.stdout.strip(), "ok")


class TestAfterFork(unittest.TestCase):
    def test_after_fork_never_signals_the_inherited_worker(self):
        worker = regex_worker._Worker()
        ancien_verrou = worker._lock
        ancien_verrou.acquire()
        proc = mock.Mock()
        worker._proc = proc
        worker._buffer = b"reste"
        worker._after_fork()
        proc.kill.assert_not_called()
        proc.wait.assert_not_called()
        proc.send_signal.assert_not_called()
        proc.terminate.assert_not_called()
        proc.stdin.close.assert_called_once_with()
        proc.stdout.close.assert_called_once_with()
        self.assertIsNone(worker._proc)
        self.assertEqual(worker._buffer, b"")
        self.assertIsNot(worker._lock, ancien_verrou)
        self.assertFalse(worker._lock.locked())


if __name__ == "__main__":
    unittest.main()
