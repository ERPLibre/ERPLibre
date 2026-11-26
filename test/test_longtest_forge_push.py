#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le test long de la forge Forgejo, vu du menu et de son défaire.

Ce qu'ils tiennent, sans VM :
- le menu des tests longs le lance à blanc (15) et pour de vrai (16) ;
- il partage le verrou des autres tests longs et le défaire du menu ;
- « --detruire » refuse tant qu'un test long tourne, sans lire de rapport.
"""

import argparse
import sys
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "long_test"))

import descente  # noqa: E402
import forge_push  # noqa: E402

from script.todo import longtest_menu  # noqa: E402
from script.todo.todo_i18n import TRANSLATIONS  # noqa: E402


class Menu(longtest_menu.LongTestMenuMixin):
    def __init__(self):
        self.lances = []

    def fill_help_info(self, choices):
        return ""

    def _longtest_run(self, nom, args="", demander=None):
        self.lances.append((nom, args))


class TestLeMenu(unittest.TestCase):
    def test_15_plans_and_16_runs(self):
        menu = Menu()
        with (
            mock.patch.object(
                longtest_menu.click, "prompt", side_effect=["15", "16", "0"]
            ),
            mock.patch("builtins.print"),
        ):
            menu.prompt_execute_longtest()
        self.assertEqual(
            menu.lances,
            [("forge_push.py", "--dry-run"), ("forge_push.py", "")],
        )

    def test_it_shares_the_lock_and_the_undo(self):
        self.assertIn("forge_push.py", descente.SCRIPTS)
        self.assertIn("forge_push.py", longtest_menu.SCRIPTS_DEFAISABLES)

    def test_every_label_is_translated(self):
        for cle in (
            "Forgejo forge receives the project: plan only (dry-run)",
            "Forgejo forge receives the project: run it",
        ):
            with self.subTest(cle=cle):
                self.assertTrue(TRANSLATIONS[cle].get("fr"))


class TestLeDefaire(unittest.TestCase):
    def test_a_running_long_test_blocks_the_undo(self):
        with (
            mock.patch.object(
                forge_push, "autre_descente", return_value=[4242]
            ),
            mock.patch.object(forge_push, "dernier_rapport") as rapport,
            mock.patch.object(forge_push, "detruire_etage1") as detruire,
            mock.patch.object(forge_push, "dire"),
        ):
            self.assertEqual(forge_push.detruire(), 1)
        rapport.assert_not_called()
        detruire.assert_not_called()

    def test_nothing_running_reads_the_last_report(self):
        with (
            mock.patch.object(forge_push, "autre_descente", return_value=[]),
            mock.patch.object(
                forge_push, "dernier_rapport", return_value=(None, {})
            ),
            mock.patch.object(forge_push, "detruire_etage1") as detruire,
            mock.patch.object(forge_push, "dire"),
        ):
            self.assertEqual(forge_push.detruire(), 0)
        detruire.assert_not_called()


class FausseCourse:
    def __init__(self):
        self.etapes = []
        self.rapport = {}

    def etape(self, nom, ok, detail=""):
        self.etapes.append((nom, ok, detail))
        return ok


class TestLeRetour(unittest.TestCase):
    """L'étape « retour », sans VM : elle suit la vérification, et
    échoue sans rien lancer quand ERPLibre n'a pas été poussé."""

    def test_it_follows_the_verification(self):
        self.assertLess(
            forge_push.ETAPES.index("verification"),
            forge_push.ETAPES.index("retour"),
        )

    def test_without_erplibre_nothing_runs(self):
        course = FausseCourse()
        with mock.patch.object(forge_push.subprocess, "run") as lancer:
            self.assertFalse(
                forge_push.retour(course, mock.Mock(), None, "/nulle-part")
            )
        lancer.assert_not_called()
        self.assertEqual(course.etapes[0][:2], ("retour", False))

    def test_a_failed_git_step_stops_before_the_api(self):
        course = FausseCourse()
        client = mock.Mock()
        cible = {
            "proprietaire": "P",
            "depot": "d",
            "branche": "X.0",
            "remote": "ssh://git@forge.example.invalid:2222/P/d.git",
        }
        fini = mock.Mock(returncode=128, stderr="fatal: refusé")
        with mock.patch.object(
            forge_push.subprocess, "run", return_value=fini
        ):
            self.assertFalse(
                forge_push.retour(course, client, cible, "/nulle-part")
            )
        self.assertIn("git init", course.etapes[0][2])
        client.assurer_pull_request.assert_not_called()


class TestLesMiroirs(unittest.TestCase):
    """Les étapes « miroirs » et « synchro », sans VM : leur place, le
    choix de la branche suivie, le verdict d'une passe, et l'arrêt quand
    le minuteur ne s'installe pas."""

    TETE = "a" * 40
    DIV = "d" * 40

    def test_they_follow_the_feedback_and_are_off_by_default(self):
        self.assertEqual(
            forge_push.ETAPES[-3:], ("retour", "miroirs", "synchro")
        )
        with mock.patch.object(forge_push, "mener", side_effect=lambda a: a):
            self.assertEqual(forge_push.main([]).miroirs, 0)
            self.assertEqual(forge_push.main(["--miroirs", "2"]).miroirs, 2)

    def test_the_followed_branch(self):
        self.assertEqual(
            forge_push.branche_de_suivi(
                lambda b: b in ("master", "dev"), "dev"
            ),
            "master",
        )
        self.assertIsNone(
            forge_push.branche_de_suivi(lambda b: b == "dev", "dev")
        )
        self.assertIsNone(forge_push.branche_de_suivi(lambda b: False, "dev"))

    def test_the_branch_advanced_by_retour_is_never_followed(self):
        """« retour » fusionne dans la branche poussée un commit absent de
        l'origine : depuis develop, le miroir suit master."""
        self.assertEqual(
            forge_push.branche_de_suivi(
                lambda b: b in ("develop", "master"), "develop"
            ),
            "master",
        )
        self.assertIsNone(
            forge_push.branche_de_suivi(lambda b: b == "master", "master")
        )

    def resultats(self, **etats):
        base = {
            "longtest-ff": "avance",
            "longtest-ahead": "en_avance",
            "longtest-div": "divergent",
            "develop": "creee",
        }
        base.update(etats)
        return {
            "debut": "2099-01-01T09:00:00Z",
            "resultats": [
                {"depot": "P/E", "branche": b, "etat": e}
                for b, e in base.items()
            ]
            + [{"depot": "P/c", "branche": "X.0", "etat": "a_jour"}],
        }

    def verifier(self, etat, precedent=None, lus=None):
        client = mock.Mock()
        lus = lus or {"longtest-ff": self.TETE, "longtest-div": self.DIV}
        client.commit_de_branche.side_effect = lambda o, r, b: lus[b]
        return forge_push.verifier_synchro(
            etat,
            precedent or {"debut": "2099-01-01T08:00:00Z"},
            "P/E",
            self.TETE,
            {"longtest-div": self.DIV},
            client,
            "P",
            "E",
        )

    def test_the_expected_pass_has_no_gap(self):
        self.assertEqual(self.verifier(self.resultats()), [])

    def test_a_clone_with_local_commits_may_diverge(self):
        """Un clone poussé avec des commits absents de son origine diverge
        de son miroir : c'est l'état juste, pas un écart. Un refus en
        reste un."""
        etat = self.resultats()
        etat["resultats"].append(
            {"depot": "P/d", "branche": "X.0", "etat": "divergent"}
        )
        self.assertEqual(self.verifier(etat), [])
        etat["resultats"].append(
            {"depot": "P/d", "branche": "Y.0", "etat": "refuse"}
        )
        self.assertEqual(len(self.verifier(etat)), 1)

    def test_every_gap_is_reported(self):
        self.assertEqual(
            len(self.verifier(self.resultats(**{"longtest-div": "avance"}))), 1
        )
        etat = self.resultats()
        self.assertIn("no new pass", self.verifier(etat, precedent=etat))
        lus = {"longtest-ff": "b" * 40, "longtest-div": self.DIV}
        self.assertEqual(len(self.verifier(self.resultats(), lus=lus)), 1)
        etat["resultats"].append(
            {"depot": "P/c", "branche": "Y", "etat": "refuse"}
        )
        self.assertEqual(len(self.verifier(etat)), 1)

    def test_a_timer_that_does_not_install_stops_the_step(self):
        course = FausseCourse()
        client = mock.Mock()
        erplibre = {"proprietaire": "P", "depot": "E", "branche": "dev"}
        with mock.patch.object(
            forge_push.forge_vm, "installer_synchro", return_value=False
        ):
            self.assertFalse(
                forge_push.miroirs(
                    course,
                    client,
                    {"ip": "192.0.2.7"},
                    erplibre,
                    [],
                    "/nulle-part.log",
                    "/nulle-part",
                )
            )
        self.assertEqual(course.etapes[0][:2], ("miroirs", False))
        client.assert_not_called()
        client.assurer_miroir.assert_not_called()


class TestLaCi(unittest.TestCase):
    """L'option `--ci`, sans VM : ses étapes, ses refspecs, son refus
    d'un workflow non commité, et le verdict des étapes « ci » et
    « ci_push » contre un faux client."""

    HEAD = "c" * 40

    def test_the_option_and_the_steps(self):
        with mock.patch.object(forge_push, "mener", side_effect=lambda a: a):
            self.assertFalse(forge_push.main([]).ci)
            self.assertTrue(forge_push.main(["--ci"]).ci)
        etapes = forge_push.etapes(ci=True)
        self.assertEqual(forge_push.ETAPES, forge_push.etapes())
        self.assertLess(etapes.index("api"), etapes.index("runner"))
        self.assertLess(etapes.index("retour"), etapes.index("ci"))
        self.assertLess(etapes.index("ci"), etapes.index("miroirs"))
        self.assertEqual(etapes[-1], "ci_push")
        self.assertNotIn("ci", forge_push.ETAPES)

    def test_the_ci_refspecs_write_nothing_on_the_host(self):
        self.assertEqual(
            forge_push.specs_ci("b"),
            [
                "HEAD:refs/heads/b",
                "HEAD~1:refs/heads/ci-longtest-base",
                "HEAD:refs/heads/ci-longtest",
            ],
        )

    def test_an_uncommitted_workflow_is_refused(self):
        def git_hote(*args):
            manque = args[:2] == ("cat-file", "-e") and "unit_test" in args[2]
            return (1 if manque else 0), ""

        self.assertIn("COMMITTED", forge_push.refus_ci(git_hote))
        self.assertEqual(forge_push.refus_ci(lambda *a: (0, "")), "")
        self.assertIn(
            "HEAD~1",
            forge_push.refus_ci(
                lambda *a: (1 if a[0] == "rev-parse" else 0, "")
            ),
        )

    def test_the_menu_run_refuses_before_any_vm(self):
        args = argparse.Namespace(
            dry_run=False, ci=True, projets=0, jobs=1, miroirs=0
        )
        with mock.patch.object(
            forge_push, "refus_ci", return_value="not committed"
        ), mock.patch.object(
            forge_push.forge_vm, "cle_publique", return_value="/k.pub"
        ), mock.patch.object(
            forge_push.forge_vm, "git_hote", return_value=(0, "x")
        ), mock.patch.object(
            forge_push.push_remote, "projets_actifs", return_value=[]
        ), mock.patch.object(
            forge_push,
            "chemins_de_course",
            return_value=("/dev/null", "/dev/null", "/nulle-part"),
        ), mock.patch.object(
            forge_push, "Course"
        ), mock.patch.object(
            forge_push.forge_vm, "deployer"
        ) as deployer, mock.patch.object(
            forge_push.os, "chdir"
        ):
            self.assertEqual(forge_push.mener(args), 1)
        deployer.assert_not_called()

    def client(self, *statuts):
        client = mock.Mock()
        client.assurer_pull_request.return_value = ("creee", {"number": 4})
        client.statut_combine.side_effect = list(statuts)
        return client

    def lancer_ci(self, client):
        course = FausseCourse()
        cible = {"proprietaire": "P", "depot": "E"}
        with mock.patch.object(forge_push.time, "sleep"):
            ok = forge_push.ci(course, client, cible, self.HEAD)
        return ok, course

    def test_the_ci_step_waits_for_a_verdict(self):
        en_cours = {
            "state": "pending",
            "total_count": 1,
            "statuses": [{"context": "unit", "state": "pending"}],
        }
        fini = {
            "state": "success",
            "total_count": 1,
            "statuses": [
                {"context": "unit", "state": "success", "target_url": "u"}
            ],
        }
        client = self.client({}, en_cours, fini)
        ok, course = self.lancer_ci(client)
        self.assertTrue(ok)
        client.assurer_actions.assert_called_once_with("P", "E")
        client.assurer_pull_request.assert_called_once_with(
            "P", "E", "ci-longtest", "ci-longtest-base", "CI long test"
        )
        self.assertEqual(client.statut_combine.call_count, 3)
        self.assertEqual(course.rapport["ci"]["etat"], "succes")
        self.assertEqual(course.etapes[-1][:2], ("ci", True))

    def test_a_failed_ci_fails_the_step(self):
        echec = {
            "state": "failure",
            "total_count": 1,
            "statuses": [{"context": "unit", "state": "failure"}],
        }
        ok, course = self.lancer_ci(self.client(echec))
        self.assertFalse(ok)
        self.assertIn("unit", course.etapes[-1][2])

    def test_pushed_commits_carry_no_status(self):
        course = FausseCourse()
        cible = {"proprietaire": "P", "depot": "E"}
        client = mock.Mock()
        client.statut_combine.side_effect = [None, {"statuses": []}]
        with mock.patch.object(forge_push.time, "sleep"):
            self.assertTrue(
                forge_push.ci_push(course, client, cible, ["a" * 40, "b" * 40])
            )
        client.statut_combine.side_effect = [
            {"statuses": [{"state": "pending"}]}
        ]
        with mock.patch.object(forge_push.time, "sleep"):
            self.assertFalse(
                forge_push.ci_push(course, client, cible, ["a" * 40])
            )


if __name__ == "__main__":
    unittest.main()
