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
import time
import unittest

sys.argv = ["todo.py"]
from script.todo.deploy_form_lib import run_deploy_progress  # noqa: E402

try:
    import textual  # noqa: F401

    TEXTUAL = True
except Exception:  # pragma: no cover - dépend de l'environnement
    TEXTUAL = False


async def attendre(pilote, condition, plafond=10.0):
    """Rend dès que `condition()` est vraie, en laissant l'application
    avancer entre deux regards.

    Une attente sur CONDITION et non sur une durée : la durée fixe devait
    couvrir le pire cas d'une machine chargée, et tous les passages la
    payaient. Le plafond ne sert qu'à échouer en le disant."""
    fin = time.monotonic() + plafond
    while not condition():
        if time.monotonic() > fin:
            raise AssertionError(f"condition non atteinte en {plafond} s")
        await pilote.pause(0.05)
    await pilote.pause()


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
                    "for i in $(seq 1 6); do echo ligne $i; sleep 0.3; done",
                ],
            )
        ]
        vu = {}

        async def scenario():
            from textual.widgets import RichLog

            app = run_deploy_progress(jobs, 1, run_app=False)
            async with app.run_test(size=(120, 30)) as pilote:
                journal = app.query_one(RichLog)
                await attendre(pilote, lambda: len(journal.lines) > 0)
                vu["premieres"] = len(journal.lines)
                vu["fini_a_la_premiere"] = app._done
                await attendre(
                    pilote, lambda: len(journal.lines) > vu["premieres"]
                )
                await attendre(pilote, lambda: app._done)
                vu["toutes"] = len(journal.lines)

        asyncio.run(scenario())
        # Une ligne à l'écran AVANT la fin du travail, puis de plus en plus.
        self.assertEqual(
            vu["fini_a_la_premiere"], 0, "rien à l'écran pendant le travail"
        )
        self.assertEqual(vu["toutes"], 6)

    def test_the_output_is_not_written_twice(self):
        # `_finish` réécrivait tout : la sortie apparaîtrait en double.
        jobs = [("1", "vm-court", ["bash", "-c", "echo une; echo deux"])]
        vu = {}

        async def scenario():
            from textual.widgets import RichLog

            app = run_deploy_progress(jobs, 1, run_app=False)
            async with app.run_test(size=(120, 30)) as pilote:
                await attendre(pilote, lambda: app._done)
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
                await attendre(pilote, lambda: app._done)
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
                await attendre(pilote, lambda: app._done)
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
                await attendre(pilote, lambda: app._done)
                vu["reussies"] = list(app._reussies)

        asyncio.run(scenario())
        self.assertEqual(vu["reussies"], [])


@unittest.skipUnless(TEXTUAL, "Textual absent")
class TestCeQuiSuit(unittest.TestCase):
    """Rapporté : on attendait devant une fenêtre « terminée » sans savoir
    que l'installation d'ERPLibre démarre en la quittant."""

    def _sommaire(self, suite):
        # Un travail qui DURE : sinon il finit avant le premier relevé, et le
        # test ne prouve rien de l'avant/après.
        jobs = [("1", "vm-a", ["bash", "-c", "sleep 1; echo ok"])]
        vu = {}

        async def scenario():
            from textual.widgets import Static

            app = run_deploy_progress(jobs, 1, run_app=False, suite=suite)
            async with app.run_test(size=(140, 30)) as pilote:
                await pilote.pause()
                vu["pendant"] = str(app.query_one("#summary", Static).render())
                vu["fini_pendant"] = app._done
                await attendre(pilote, lambda: app._done)
                vu["apres"] = str(app.query_one("#summary", Static).render())

        asyncio.run(scenario())
        return vu

    def test_it_says_what_follows_once_everything_is_done(self):
        vu = self._sommaire("Quitter (q) pour lancer l'installation")
        self.assertEqual(vu["fini_pendant"], 0, "relevé trop tard")
        self.assertNotIn("Quitter", vu["pendant"])
        self.assertIn("Quitter", vu["apres"])

    def test_nothing_is_promised_when_nothing_follows(self):
        vu = self._sommaire("")
        self.assertNotIn("→", vu["apres"])


@unittest.skipUnless(TEXTUAL, "Textual absent")
class TestLaCibleSsh(unittest.TestCase):
    """« s » utilisait le NOM de la VM. Sur Proxmox, l'entrée ~/.ssh/config
    n'existe pas encore à ce moment — et ce nom peut désigner une machine
    LOCALE homonyme, qui s'ouvrait alors à sa place."""

    def _lance(self, ssh_cmds):
        import contextlib
        import os

        jobs = [("1", "erplibre-ubuntu-2604", ["bash", "-c", "echo ok"])]
        vu = []

        async def scenario():
            app = run_deploy_progress(
                jobs, 1, run_app=False, ssh_cmds=ssh_cmds
            )
            async with app.run_test(size=(140, 30)) as pilote:
                await attendre(pilote, lambda: app._done)
                vrai = os.system
                os.system = vu.append
                app.suspend = lambda: contextlib.nullcontext()
                try:
                    app.action_ssh()
                finally:
                    os.system = vrai

        asyncio.run(scenario())
        return vu[0] if vu else ""

    def test_the_given_command_wins(self):
        cible = "ssh -J erplibre-proxmox-9 erplibre@10.10.10.151"
        self.assertIn(cible, self._lance({"erplibre-ubuntu-2604": cible}))

    def test_without_one_it_falls_back_to_the_name(self):
        self.assertIn("ssh erplibre-ubuntu-2604", self._lance(None))


if __name__ == "__main__":
    unittest.main(verbosity=2)
