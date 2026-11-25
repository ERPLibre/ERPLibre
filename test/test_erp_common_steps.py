#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le moteur d'étapes commun aux installateurs d'ERP (script/erp_common).

Ce qui se garde :
- l'essai à blanc n'exécute rien, sauf les sondes sans sudo ;
- un contenu écrit sous sudo passe par stdin, jamais par argv, et un
  fichier écrit sans sudo porte le mode demandé ;
- les secrets générés n'ont que des lettres et des chiffres ;
- le dossier d'état et le registre portent le nom de l'ERP reçu, aucun
  autre : chaque test qui en dépend tourne pour deux noms ;
- run_steps s'arrête à la première étape en échec et ne promet une
  reprise que pour une erreur qui en permet une.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.erp_common import steps  # noqa: E402

# Deux noms : celui d'un ERP réel et un nom inventé, pour prouver que rien
# n'est écrit en dur.
ERPS = ("dolibarr", "acme")

REPRISE = "Nothing was undone: running again resumes at this step."


class Sortie:
    """Collecte ce que le Runner affiche, à la place de print."""

    def __init__(self):
        self.lignes = []

    def __call__(self, texte):
        self.lignes.append(texte)


def runner_sans_exec(dry_run=False):
    """Runner dont toute exécution réelle fait échouer le test."""
    sortie = Sortie()
    runner = steps.Runner(dry_run=dry_run, out=sortie)
    runner._exec = mock.Mock(side_effect=AssertionError("exécuté"))
    return runner, sortie


class TestStepError(unittest.TestCase):
    def test_an_error_is_resumable_and_without_detail_by_default(self):
        e = steps.StepError("échec")
        self.assertEqual(str(e), "échec")
        self.assertEqual(e.detail, "")
        self.assertTrue(e.resumable)

    def test_a_refusal_carries_its_detail_and_is_not_resumable(self):
        e = steps.StepError("refus", "sortie", resumable=False)
        self.assertEqual(e.detail, "sortie")
        self.assertFalse(e.resumable)


class TestRunnerEssaiABlanc(unittest.TestCase):
    def test_run_shows_the_command_and_executes_nothing(self):
        runner, sortie = runner_sans_exec(dry_run=True)
        res = runner.run(["sudo", "mariadb"], input="MOT-DE-PASSE")
        self.assertEqual(res, (0, ""))
        self.assertEqual(
            sortie.lignes, ["      [dry-run] $ sudo mariadb  < stdin"]
        )
        # Ce qui passe par stdin n'est jamais affiché.
        self.assertNotIn("MOT-DE-PASSE", "".join(sortie.lignes))

    def test_a_probe_without_sudo_still_runs(self):
        runner = steps.Runner(dry_run=True, out=Sortie())
        runner._exec = mock.Mock(return_value=(0, "oui"))
        self.assertEqual(runner.probe(["dpkg-query", "-W"]), (0, "oui"))
        runner._exec.assert_called_once_with(
            ["dpkg-query", "-W"], None, None, None
        )

    def test_a_probe_with_sudo_does_not_run(self):
        runner, _sortie = runner_sans_exec(dry_run=True)
        self.assertIsNone(runner.probe(["sudo", "cat", "/etc/fichier"]))

    def test_write_writes_nothing(self):
        runner, sortie = runner_sans_exec(dry_run=True)
        with tempfile.TemporaryDirectory() as tmp:
            chemin = os.path.join(tmp, "secrets.env")
            runner.write(chemin, "A=1\n")
            runner.write(chemin, "A=1\n", sudo=True)
            self.assertFalse(os.path.exists(chemin))
        self.assertIn(f"      [dry-run] write {chemin} (0o600)", sortie.lignes)


class TestRunnerExecution(unittest.TestCase):
    def test_run_returns_the_code_and_both_outputs(self):
        runner = steps.Runner(out=Sortie())
        code, out = runner.run(
            [
                sys.executable,
                "-c",
                "import sys; print('dehors');"
                " print('erreur', file=sys.stderr); sys.exit(3)",
            ]
        )
        self.assertEqual(code, 3)
        self.assertIn("dehors", out)
        self.assertIn("erreur", out)

    def test_input_and_env_reach_the_command(self):
        runner = steps.Runner(out=Sortie())
        code, out = runner.run(
            [
                sys.executable,
                "-c",
                "import os, sys;"
                " print(sys.stdin.read() + os.environ['EL_ESSAI'])",
            ],
            input="lu-",
            env={"EL_ESSAI": "vu"},
        )
        self.assertEqual((code, out.strip()), (0, "lu-vu"))

    def test_a_missing_program_gives_127(self):
        runner = steps.Runner(out=Sortie())
        code, _out = runner.run(["/inexistant/erp-common-essai"])
        self.assertEqual(code, 127)

    def test_a_file_written_without_sudo_gets_the_requested_mode(self):
        runner = steps.Runner(out=Sortie())
        with tempfile.TemporaryDirectory() as tmp:
            chemin = Path(tmp, "secrets.env")
            chemin.write_text("ancien\n")
            chemin.chmod(0o644)
            runner.write(str(chemin), "A=1\n")
            self.assertEqual(chemin.read_text(), "A=1\n")
            self.assertEqual(chemin.stat().st_mode & 0o777, 0o600)

    def test_content_written_under_sudo_goes_through_stdin(self):
        runner = steps.Runner(out=Sortie())
        runner._exec = mock.Mock(return_value=(0, ""))
        runner.write(
            "/etc/erp/secrets.env",
            "SECRET=valeur\n",
            mode=0o640,
            sudo=True,
            owner="root",
            group="www-data",
        )
        argv, entree, _cwd, _env = runner._exec.call_args.args
        self.assertEqual(
            argv,
            [
                "sudo",
                "install",
                "-m",
                "640",
                "-o",
                "root",
                "-g",
                "www-data",
                "/dev/stdin",
                "/etc/erp/secrets.env",
            ],
        )
        self.assertEqual(entree, "SECRET=valeur\n")
        self.assertFalse(any("valeur" in a for a in argv))

    def test_a_failed_sudo_write_raises_with_the_output(self):
        runner = steps.Runner(out=Sortie())
        runner._exec = mock.Mock(return_value=(1, "refusé"))
        with self.assertRaises(steps.StepError) as err:
            runner.write("/etc/erp/x", "y", sudo=True)
        self.assertEqual(err.exception.detail, "refusé")
        self.assertIn("/etc/erp/x", str(err.exception))


class TestAidesDuRunner(unittest.TestCase):
    def test_tail_keeps_the_last_lines_without_edge_blanks(self):
        texte = "\n".join(str(i) for i in range(30)) + "\n\n"
        self.assertEqual(steps.tail(texte, 3), "27\n28\n29")
        self.assertEqual(steps.tail(None), "")

    def test_run_or_fail_returns_the_output(self):
        runner = steps.Runner(out=Sortie())
        runner._exec = mock.Mock(return_value=(0, "fait"))
        out = steps.run_or_fail(runner, ["vrai"], "message", cwd="/tmp")
        self.assertEqual(out, "fait")
        runner._exec.assert_called_once_with(["vrai"], None, "/tmp", None)

    def test_run_or_fail_raises_the_message_with_the_output_tail(self):
        runner = steps.Runner(out=Sortie())
        sortie = "\n".join(f"ligne {i}" for i in range(40))
        runner._exec = mock.Mock(return_value=(2, sortie))
        with self.assertRaises(steps.StepError) as err:
            steps.run_or_fail(runner, ["faux"], "Échec voulu.")
        self.assertEqual(str(err.exception), "Échec voulu.")
        self.assertEqual(err.exception.detail, steps.tail(sortie))
        self.assertTrue(err.exception.resumable)

    def test_sudo_read_returns_the_content_or_none(self):
        runner = steps.Runner(out=Sortie())
        runner._exec = mock.Mock(return_value=(0, "contenu"))
        self.assertEqual(steps.sudo_read(runner, "/etc/f"), "contenu")
        runner._exec.assert_called_once_with(
            ["sudo", "cat", "/etc/f"], None, None, None
        )
        runner._exec = mock.Mock(return_value=(1, "absent"))
        self.assertIsNone(steps.sudo_read(runner, "/etc/f"))
        runner, _sortie = runner_sans_exec(dry_run=True)
        self.assertIsNone(steps.sudo_read(runner, "/etc/f"))

    def test_sudo_exists_is_false_unless_the_test_succeeds(self):
        runner = steps.Runner(out=Sortie())
        runner._exec = mock.Mock(return_value=(0, ""))
        self.assertTrue(steps.sudo_exists(runner, "/etc/f"))
        runner._exec.assert_called_once_with(
            ["sudo", "test", "-e", "/etc/f"], None, None, None
        )
        runner._exec = mock.Mock(return_value=(1, ""))
        self.assertFalse(steps.sudo_exists(runner, "/etc/f"))
        runner, _sortie = runner_sans_exec(dry_run=True)
        self.assertFalse(steps.sudo_exists(runner, "/etc/f"))


class TestSecrets(unittest.TestCase):
    def test_generated_secrets_are_letters_and_digits_only(self):
        for longueur in (1, 20, 32, 64):
            valeur = steps.generate_secret(longueur)
            self.assertRegex(valeur, rf"^[A-Za-z0-9]{{{longueur}}}$")
        self.assertEqual(len(steps.generate_secret()), 32)

    def test_two_generated_secrets_differ(self):
        self.assertNotEqual(steps.generate_secret(), steps.generate_secret())

    def test_parse_secrets_skips_comments_and_keeps_equals_in_values(self):
        texte = "# commentaire=non\nDB_PASSWORD=a=b\n ADMIN = x \nvide\n"
        self.assertEqual(
            steps.parse_secrets(texte),
            {"DB_PASSWORD": "a=b", "ADMIN": " x "},
        )
        self.assertEqual(steps.parse_secrets(None), {})

    def test_read_secrets_of_a_missing_file_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            absent = os.path.join(tmp, "secrets.env")
            self.assertEqual(steps.read_secrets(absent), {})

    def test_read_secrets_reads_what_write_wrote(self):
        runner = steps.Runner(out=Sortie())
        with tempfile.TemporaryDirectory() as tmp:
            chemin = os.path.join(tmp, "secrets.env")
            runner.write(chemin, "A=1\nB=2\n")
            self.assertEqual(steps.read_secrets(chemin), {"A": "1", "B": "2"})


class TestStateDir(unittest.TestCase):
    def test_xdg_data_home_is_respected(self):
        with mock.patch.dict(os.environ, {"XDG_DATA_HOME": "/xdg"}):
            for erp in ERPS:
                with self.subTest(erp=erp):
                    self.assertEqual(
                        steps.state_dir(erp, "prod"),
                        f"/xdg/ERPLibre/{erp}/prod",
                    )

    def test_without_xdg_it_lives_under_the_home(self):
        env = {k: v for k, v in os.environ.items() if k != "XDG_DATA_HOME"}
        env["HOME"] = "/maison"
        with mock.patch.dict(os.environ, env, clear=True):
            for erp in ERPS:
                with self.subTest(erp=erp):
                    self.assertEqual(
                        steps.state_dir(erp, "essai"),
                        f"/maison/.local/share/ERPLibre/{erp}/essai",
                    )


class TestRecordEntry(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.racine = Path(tmp.name)

    def registre(self, erp):
        return self.racine / "private" / erp / "instances.json"

    def test_a_dry_run_neither_reads_nor_writes(self):
        for erp in ERPS:
            with self.subTest(erp=erp):
                runner, sortie = runner_sans_exec(dry_run=True)
                charger = mock.Mock(side_effect=AssertionError("lu"))
                res = steps.record_entry(
                    runner, str(self.registre(erp)), charger, "erp", {}
                )
                self.assertEqual(res, steps.t("ok"))
                self.assertFalse(self.registre(erp).exists())
                self.assertEqual(
                    sortie.lignes,
                    [f"      [dry-run] record erp in {self.registre(erp)}"],
                )

    def test_the_entry_joins_the_known_instances_privately(self):
        for erp in ERPS:
            with self.subTest(erp=erp):
                runner = steps.Runner(out=Sortie())
                connues = {"ancienne": {"mode": "dev"}}
                steps.record_entry(
                    runner,
                    str(self.registre(erp)),
                    lambda: dict(connues),
                    "nouvelle",
                    {"mode": "prod"},
                )
                data = json.loads(self.registre(erp).read_text())
                self.assertEqual(
                    data,
                    {
                        "instances": {
                            "ancienne": {"mode": "dev"},
                            "nouvelle": {"mode": "prod"},
                        }
                    },
                )
                dossier = self.registre(erp).parent
                self.assertEqual(dossier.stat().st_mode & 0o777, 0o700)
                mode = self.registre(erp).stat().st_mode & 0o777
                self.assertEqual(mode, 0o600)

    def test_an_unreadable_registry_stops_before_writing(self):
        runner = steps.Runner(out=Sortie())

        def charger():
            raise steps.StepError("registre illisible")

        with self.assertRaises(steps.StepError):
            steps.record_entry(
                runner, str(self.registre("acme")), charger, "erp", {}
            )
        self.assertFalse(self.registre("acme").exists())


class TestRunSteps(unittest.TestCase):
    def setUp(self):
        self.sortie = Sortie()
        self.runner = steps.Runner(out=self.sortie)
        self.joues = []

    def etape(self, nom, erreur=None):
        def jouer(ctx, runner):
            self.joues.append(nom)
            if erreur:
                raise erreur
            return f"{nom} fait"

        return (nom, jouer)

    def test_every_step_runs_in_order(self):
        code = steps.run_steps(
            "ctx", self.runner, (self.etape("un"), self.etape("deux"))
        )
        self.assertEqual(code, 0)
        self.assertEqual(self.joues, ["un", "deux"])
        self.assertEqual(
            self.sortie.lignes, ["[1/2] un: un fait", "[2/2] deux: deux fait"]
        )

    def test_a_failure_stops_and_says_a_rerun_resumes(self):
        code = steps.run_steps(
            "ctx",
            self.runner,
            (
                self.etape("un"),
                self.etape("deux", steps.StepError("boom", "détail")),
                self.etape("trois"),
            ),
        )
        self.assertEqual(code, 1)
        self.assertEqual(self.joues, ["un", "deux"])
        self.assertIn(
            f"[2/3] deux: {steps.t('FAILED')} — boom", self.sortie.lignes
        )
        self.assertIn("détail", self.sortie.lignes)
        self.assertIn(steps.t(REPRISE), self.sortie.lignes)

    def test_a_refusal_does_not_promise_a_resume(self):
        code = steps.run_steps(
            "ctx",
            self.runner,
            (self.etape("un", steps.StepError("non", resumable=False)),),
        )
        self.assertEqual(code, 1)
        self.assertIn(
            steps.t("Step failed, stopping here."), self.sortie.lignes
        )
        self.assertNotIn(steps.t(REPRISE), self.sortie.lignes)

    def test_another_exception_is_not_swallowed(self):
        with self.assertRaises(ValueError):
            steps.run_steps(
                "ctx", self.runner, (self.etape("un", ValueError("bug")),)
            )


if __name__ == "__main__":
    unittest.main()
