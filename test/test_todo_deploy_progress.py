#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La vue de progression d'un déploiement : en direct, et on peut y entrer.

Rapporté sur un déploiement Proxmox : « les logs ne sont pas live, ils sont
apparus à la toute fin » et « il manque les boutons comme s pour se connecter
en ssh ». Les deux étaient vrais de cette vue — elle exécutait chaque travail
avec `subprocess.run`, qui ne rend sa sortie qu'à la fin, et ses touches se
limitaient à copier et quitter.

Une VM sur Proxmox demande le téléchargement d'une image de 325 Mio puis
l'import de son disque : plusieurs minutes d'un bloc vide.
"""

import asyncio
import sys
import unittest

sys.argv = ["todo.py"]
from script.todo.deploy_form_lib import run_deploy_progress  # noqa: E402

try:
    import textual  # noqa: F401

    TEXTUAL = True
except Exception:  # pragma: no cover - dépend de l'environnement
    TEXTUAL = False


@unittest.skipUnless(TEXTUAL, "Textual absent")
class TestLeFlux(unittest.TestCase):
    def test_the_lines_appear_while_the_job_runs(self):
        """Le cœur du rapport : compté PENDANT, pas après."""
        jobs = [
            (
                "1",
                "vm-flux",
                [
                    "bash",
                    "-c",
                    "for i in $(seq 1 6); do echo ligne $i; sleep 1; done",
                ],
            )
        ]
        vu = []

        async def scenario():
            from textual.widgets import RichLog

            app = run_deploy_progress(jobs, 1, run_app=False)
            async with app.run_test(size=(120, 30)) as pilote:
                await pilote.pause()
                journal = app.query_one(RichLog)
                for _ in range(3):
                    await asyncio.sleep(1.5)
                    await pilote.pause()
                    vu.append(len(journal.lines))
                vu.append(len(app._reussies))

        asyncio.run(scenario())
        # Au moins une ligne AVANT la fin, et de plus en plus.
        self.assertGreater(vu[0], 0, "rien à l'écran pendant le travail")
        self.assertGreater(vu[2], vu[0], "l'affichage n'avance pas")

    def test_the_output_is_not_written_twice(self):
        # `_finish` réécrivait tout : la sortie apparaîtrait en double.
        jobs = [("1", "vm-court", ["bash", "-c", "echo une; echo deux"])]
        vu = {}

        async def scenario():
            from textual.widgets import RichLog

            app = run_deploy_progress(jobs, 1, run_app=False)
            async with app.run_test(size=(120, 30)) as pilote:
                await pilote.pause()
                await asyncio.sleep(1.5)
                await pilote.pause()
                vu["lignes"] = len(app.query_one(RichLog).lines)

        asyncio.run(scenario())
        self.assertEqual(vu["lignes"], 2)

    def test_a_command_that_cannot_start_still_says_so(self):
        # Le processus n'a rien écrit : c'est le seul cas où `_finish` doit
        # poser la sortie lui-même.
        jobs = [("1", "vm-absente", ["/n/existe/pas/du/tout"])]
        vu = {}

        async def scenario():
            from textual.widgets import RichLog

            app = run_deploy_progress(jobs, 1, run_app=False)
            async with app.run_test(size=(120, 30)) as pilote:
                await pilote.pause()
                await asyncio.sleep(1.0)
                await pilote.pause()
                vu["lignes"] = len(app.query_one(RichLog).lines)
                vu["resultats"] = list(app._reussies)

        asyncio.run(scenario())
        self.assertGreater(vu["lignes"], 0, "l'échec ne dit rien")
        self.assertEqual(vu["resultats"], [])


@unittest.skipUnless(TEXTUAL, "Textual absent")
class TestLaToucheSsh(unittest.TestCase):
    def test_the_key_is_offered(self):
        app = run_deploy_progress([("1", "vm", ["true"])], 1, run_app=False)
        self.assertIn("s", [b[0] for b in type(app).BINDINGS])

    def test_it_targets_the_vm_that_was_created(self):
        jobs = [("1", "vm-creee", ["bash", "-c", "echo ok"])]
        vu = {}

        async def scenario():
            app = run_deploy_progress(jobs, 1, run_app=False)
            async with app.run_test(size=(120, 30)) as pilote:
                await pilote.pause()
                await asyncio.sleep(1.2)
                await pilote.pause()
                vu["reussies"] = list(app._reussies)

        asyncio.run(scenario())
        # Par son NOM : c'est l'entrée ~/.ssh/config qui sait l'atteindre, et
        # pour une VM Proxmox elle porte le rebond.
        self.assertEqual(vu["reussies"], ["vm-creee"])

    def test_a_failed_job_is_not_offered(self):
        jobs = [("1", "vm-ratee", ["false"])]
        vu = {}

        async def scenario():
            app = run_deploy_progress(jobs, 1, run_app=False)
            async with app.run_test(size=(120, 30)) as pilote:
                await pilote.pause()
                await asyncio.sleep(1.2)
                await pilote.pause()
                vu["reussies"] = list(app._reussies)

        asyncio.run(scenario())
        self.assertEqual(vu["reussies"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
