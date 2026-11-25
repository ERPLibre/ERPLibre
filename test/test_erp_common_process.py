#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Processus d'une instance : pid, port, journaux, état
(script/erp_common/process).

De vrais fichiers pid et de vraies sockets sur 127.0.0.1 ; la vie d'un pid
vient d'un Système factice. Ce qui se garde :
- l'état dit la vérité en quatre valeurs : lancée, arrêtée, à moitié (un
  démon mort, l'autre vivant), inconnue — jamais « arrêtée » pour un
  fichier pid illisible ;
- un port en écoute est pris, un TIME_WAIT laissé par une connexion
  fermée ne l'est pas.
"""

import os
import socket
import sys
import tempfile
import time
import unittest
import warnings
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.erp_common import process  # noqa: E402


class TestPortLibre(unittest.TestCase):
    """De vraies sockets sur 127.0.0.1, un port éphémère."""

    def test_a_listening_port_is_taken(self):
        with socket.socket() as serveur:
            serveur.bind(("127.0.0.1", 0))
            serveur.listen()
            self.assertFalse(process.port_is_free(serveur.getsockname()[1]))

    def test_time_wait_left_by_a_closed_connection_does_not_take_it(self):
        # nginx, Apache et le relais de ports de Podman ouvrent tous leur
        # écoute en SO_REUSEADDR, et un TIME_WAIT laisse écouter de nouveau.
        serveur = socket.socket()
        serveur.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        serveur.bind(("127.0.0.1", 0))
        serveur.listen()
        port = serveur.getsockname()[1]
        client = socket.create_connection(("127.0.0.1", port))
        conn, _adresse = serveur.accept()
        conn.close()  # le serveur ferme d'abord : TIME_WAIT de son côté
        client.close()
        serveur.close()
        self.assertTrue(process.port_is_free(port))

    def test_the_real_system_asks_the_same_question(self):
        with socket.socket() as serveur:
            serveur.bind(("127.0.0.1", 0))
            serveur.listen()
            port = serveur.getsockname()[1]
            self.assertFalse(process.System().port_free(port))


class Vivants:
    """Système factice : seuls les pid de `vivants` sont en vie."""

    def __init__(self, *vivants):
        self.vivants = set(vivants)

    def alive(self, pid):
        return pid in self.vivants


class Pids(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dossier = Path(tmp.name)

    def fichier(self, nom, contenu):
        chemin = self.dossier / nom
        if isinstance(contenu, bytes):
            chemin.write_bytes(contenu)
        else:
            chemin.write_text(contenu)
        return str(chemin)


class TestReadPid(Pids):
    def test_each_kind_of_pid_file(self):
        cas = (
            ("4001\n", 4001),
            ("pas un pid\n", process.UNREADABLE),
            (b"\xff\xfe", process.UNREADABLE),
            ("", process.UNREADABLE),
        )
        for contenu, attendu in cas:
            with self.subTest(contenu=contenu):
                chemin = self.fichier("demon.pid", contenu)
                self.assertEqual(process.read_pid(chemin), attendu)

    def test_an_absent_file_is_none(self):
        self.assertIsNone(process.read_pid(str(self.dossier / "absent.pid")))


class TestEtat(Pids):
    def etat(self, systeme, *fichiers):
        return process.state(
            tuple(process.live_pid(f, systeme) for f in fichiers)
        )

    def test_running_when_every_daemon_lives(self):
        a = self.fichier("a.pid", "4001\n")
        b = self.fichier("b.pid", "4002\n")
        self.assertEqual(self.etat(Vivants(4001, 4002), a, b), "running")

    def test_stopped_when_no_pid(self):
        a = str(self.dossier / "a.pid")
        b = str(self.dossier / "b.pid")
        self.assertEqual(self.etat(Vivants(), a, b), "stopped")

    def test_half_running_is_not_reported_as_running(self):
        a = self.fichier("a.pid", "4001\n")
        b = self.fichier("b.pid", "4002\n")
        self.assertEqual(self.etat(Vivants(4002), a, b), "half running")

    def test_an_unreadable_pid_file_is_unknown_not_stopped(self):
        # Un fichier pid présent mais illisible ne prouve rien : le dire
        # « arrêtée » ferait relancer par-dessus un démon peut-être vivant.
        a = self.fichier("a.pid", "pas un pid\n")
        b = str(self.dossier / "b.pid")
        self.assertEqual(self.etat(Vivants(), a, b), "unknown")
        self.assertNotEqual(
            process.STATE_LABELS["unknown"], process.STATE_LABELS["stopped"]
        )

    def test_a_single_daemon_is_running_or_stopped(self):
        a = self.fichier("a.pid", "4001\n")
        self.assertEqual(self.etat(Vivants(4001), a), "running")
        self.assertEqual(self.etat(Vivants(), a), "stopped")

    def test_every_state_has_a_label(self):
        self.assertEqual(set(process.STATE_LABELS), set(process.STATES))


class TestSystem(unittest.TestCase):
    def test_this_process_is_alive(self):
        self.assertTrue(process.System().alive(os.getpid()))

    def test_spawn_detaches_and_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = os.path.join(tmp, "out.log")
            systeme = process.System()
            # spawn ne garde pas le Popen : Python récolte l'enfant seul et
            # signale qu'il tournait encore à la libération.
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", ResourceWarning)
                pid = systeme.spawn(
                    ["sh", "-c", 'echo "$MARQUE"'], journal, {"MARQUE": "vu"}
                )
            for _ in range(100):
                if Path(journal).read_text():
                    break
                time.sleep(0.05)
            self.assertEqual(Path(journal).read_text(), "vu\n")
            # Un pid fini, ou d'un autre compte, se signale sans erreur.
            systeme.kill(pid, 0)


class TestTail(Pids):
    def test_the_last_lines_only(self):
        chemin = self.fichier(
            "x.log", "\n".join(f"ligne {i}" for i in range(50)) + "\n"
        )
        self.assertEqual(
            process.tail_file(chemin, 3), ["ligne 47", "ligne 48", "ligne 49"]
        )

    def test_an_absent_log_is_none(self):
        self.assertIsNone(process.tail_file(str(self.dossier / "x.log"), 3))


if __name__ == "__main__":
    unittest.main()
