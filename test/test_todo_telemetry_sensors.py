#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'installation de lm-sensors depuis la vue système de la télémétrie.

Ce qui se vérifie ici sans rien installer : que les index se rafraîchissent
AVANT le paquet, que le nom du paquet suit la famille, que la détection des
capteurs passe en dernier, et qu'un refus comme un échec arrêtent la suite.
"""

import contextlib
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from script.todo import todo_install, todo_telemetry, ui
from script.todo.todo_i18n import t
from script.todo.ui.port import ScriptedPort


class TestSensorsInstallSteps(unittest.TestCase):
    def _steps(self, famille):
        with patch.object(todo_install, "family", lambda: famille):
            return todo_telemetry.sensors_install_steps()

    def test_the_refresh_comes_first(self):
        attendu = {
            "apt-get": [
                ["sudo", "apt-get", "update"],
                ["sudo", "apt-get", "install", "-y", "lm-sensors"],
            ],
            "dnf": [["sudo", "dnf", "install", "-y", "lm_sensors"]],
            "pacman": [
                ["sudo", "pacman", "-Syu", "--noconfirm"],
                ["sudo", "pacman", "-S", "--needed", "--noconfirm"]
                + ["lm_sensors"],
            ],
            "zypper": [
                ["sudo", "zypper", "--non-interactive", "refresh"],
                ["sudo", "zypper", "--non-interactive", "install"]
                + ["sensors"],
            ],
        }
        for famille, etapes in attendu.items():
            self.assertEqual(self._steps(famille), etapes, famille)

    def test_no_manager_gives_no_step(self):
        self.assertEqual(self._steps("brew"), [])


class TestInstallSensors(unittest.TestCase):
    ETAPES = [
        ["sudo", "apt-get", "update"],
        ["sudo", "apt-get", "install", "-y", "lm-sensors"],
    ]

    def _run(self, reponses, codes=()):
        lances, codes, reponses = [], list(codes), list(reponses)
        sortie = io.StringIO()

        def run(cmd):
            lances.append(cmd)
            return codes.pop(0) if codes else 0

        def demande(invite=""):
            print(invite, end="")
            if not reponses:
                raise AssertionError(f"question sans réponse : {invite!r}")
            return reponses.pop(0)

        with patch("builtins.input", demande), redirect_stdout(sortie):
            status = todo_telemetry.install_sensors(self.ETAPES, run=run)
        return status, lances, sortie.getvalue()

    def test_refresh_install_then_detection(self):
        status, lances, _ = self._run(["y"])
        self.assertFalse(status)
        self.assertEqual(
            lances,
            [
                "sudo apt-get update",
                "sudo apt-get install -y lm-sensors",
                "sudo sensors-detect --auto",
            ],
        )

    def test_every_step_is_shown_before_the_question(self):
        _, _, sortie = self._run(["n"])
        question = sortie.index(t("Install lm-sensors now?"))
        for commande in ("sudo apt-get update", "sudo sensors-detect --auto"):
            self.assertLess(sortie.index(commande), question)

    def test_a_refusal_runs_nothing(self):
        status, lances, _ = self._run([""])
        self.assertIsNone(status)
        self.assertEqual(lances, [])

    def test_a_failing_refresh_stops_everything(self):
        status, lances, sortie = self._run(["y"], codes=[256])
        self.assertEqual(status, 256)
        self.assertEqual(lances, ["sudo apt-get update"])
        self.assertIn(
            t("Refreshing the package indexes failed; nothing installed."),
            sortie,
        )

    def test_a_failing_install_skips_the_detection(self):
        status, lances, _ = self._run(["y"], codes=[0, 256])
        self.assertEqual(status, 256)
        self.assertNotIn("sudo sensors-detect --auto", lances)


class TestInstallFromTheSystemView(unittest.TestCase):
    """[i] de la vue système pose sa question dans le fil qui appelle
    l'action, par le port qui y est lié, la TUI suspendue. Un fil neuf
    n'hériterait pas du ContextVar du port : la question n'atteindrait pas
    le port lié. L'action est appelée directement, hors boucle Textual ;
    suspend() est un double qui note, le lanceur remplace os.system, le
    défaut de `run`."""

    ETAPES = [["sudo", "apt-get", "install", "-y", "forged-yesno-pkg"]]

    def _press_i(self, *answers):
        app = todo_telemetry.run_tui(run_app=False, state={"mode": "system"})
        app._mode = "system"
        etat = {"suspendue": False}

        @contextlib.contextmanager
        def suspend():
            etat["suspendue"] = True
            try:
                yield
            finally:
                etat["suspendue"] = False

        class Port(ScriptedPort):
            def _answer(self, message):
                message["suspendue"] = etat["suspendue"]
                return super()._answer(message)

        app.suspend = suspend
        app.notify = lambda *_args, **_how: None
        lances = []
        port = Port(answers)
        with (
            patch.object(todo_telemetry, "read_temperature", lambda: None),
            patch.object(
                todo_telemetry, "sensors_install_steps", lambda: self.ETAPES
            ),
            patch.object(
                todo_telemetry.install_sensors,
                "__defaults__",
                (lambda cmd: lances.append((cmd, etat["suspendue"])) or 0,),
            ),
            ui.bind(port),
            redirect_stdout(io.StringIO()),
        ):
            app.action_install_sensors()
        questions = [
            (e["kind"], e["default"], e["suspendue"]) for e in port.events
        ]
        return lances, questions

    def test_the_question_reaches_the_bound_port(self):
        for answers in ([""], [], ["n"]):
            with self.subTest(answers=answers):
                self.assertEqual(
                    self._press_i(*answers), ([], [("confirm", "n", True)])
                )

    def test_a_yes_installs_then_detects(self):
        lances, questions = self._press_i("o")
        self.assertEqual(
            lances,
            [
                ("sudo apt-get install -y forged-yesno-pkg", True),
                ("sudo sensors-detect --auto", True),
            ],
        )
        self.assertEqual(questions, [("confirm", "n", True)])


if __name__ == "__main__":
    unittest.main()
