#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le test long de l'infrastructure d'appel (coturn, ntfy) sur des VM.

Lui crée des VM Debian et Arch et y installe pour de bon ; ceux-ci
gardent sa forme sans aucune VM :

- « --dry-run » montre les commandes de création et ne crée rien ;
- « --detruire » défait d'après le rapport, au contrat de descente.py ;
- chaque appel borné est rattrapé : un délai dépassé est un verdict, pas
  une trace ;
- il prend le verrou des tests longs et le menu sait le lancer et le
  défaire ;
- il pilote les MÊMES briques que le menu (`call_infra`), des `Answers` à
  la place des questions, et rien de secret n'atteint son journal ;
- en production, ses `Answers` viennent des briques des questions du menu,
  et le verdict du crochet lancé à la main se calcule sur les numéros de
  série des deux certificats inventés ;
- les courses en conteneurs (une par moteur) et la migration prennent la
  méthode et le moteur comme le menu les bâtit, et une image refusée par la
  limite du registre donne un verdict à part, ni vert ni échec. Leurs
  scripts d'hôte sont lus par `sh -n`, jamais joués : aucun moteur ni outil
  système ne part d'ici.
"""

import ast
import base64
import contextlib
import dataclasses
import datetime
import hashlib
import io
import json
import os
import shlex
import shutil
import ssl
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.argv = ["todo.py"]

RACINE = Path(__file__).resolve().parents[1]
SCRIPT = RACINE / "long_test/call_infra.py"
SRC = SCRIPT.read_text(encoding="utf-8")

sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "long_test"))

import call_infra as lt  # noqa: E402
import descente  # noqa: E402

from script.todo import call_infra as ci  # noqa: E402
from script.todo import call_infra_container as cc  # noqa: E402
from script.todo import odoo_link as ol  # noqa: E402
from script.todo import todo_i18n  # noqa: E402

IP = "192.0.2.10"
NOW = datetime.datetime.now(datetime.timezone.utc)


def b64(text):
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def lancer(maison, *args, descentes=()):
    """Le script mené dans ce processus, sur un HOME qui ne contient rien.
    Rend (code, sortie). `descentes` : les PID qu'autre_descente rend.

    Pas de sous-processus : un call_infra.py vivant est, pour les tests des
    autres tests longs que le lanceur unitaire passe en parallèle, une
    descente en cours, et leur « --detruire » refuse alors de travailler.
    Le verrou n'est pas le sujet de ces tests : autre_descente n'y voit
    rien."""
    sortie = io.StringIO()
    with (
        mock.patch.dict(os.environ, {"HOME": maison}),
        mock.patch.object(descente, "autre_descente", lambda: list(descentes)),
        # Un essai à blanc ne lance rien : une commande qui partirait
        # d'ici (création de VM, clé ssh) échoue le test au lieu de tourner.
        mock.patch("subprocess.run", side_effect=_aucun_processus),
        mock.patch("subprocess.Popen", side_effect=_aucun_processus),
        contextlib.redirect_stdout(sortie),
        contextlib.redirect_stderr(io.StringIO()),
    ):
        code = lt.mener(list(args))
    return code, sortie.getvalue()


def _aucun_processus(argv, *args, **kwargs):
    raise AssertionError(f"processus lancé par un essai à blanc : {argv}")


class LaPlace(unittest.TestCase):
    def test_it_lives_out_of_the_unit_runner(self):
        self.assertTrue(SCRIPT.exists())
        self.assertFalse((RACINE / "test/test_call_infra_long.py").exists())

    def test_it_is_executable(self):
        """Le menu et le README l'appellent directement."""
        self.assertTrue(os.access(SCRIPT, os.X_OK))

    def test_it_parses(self):
        ast.parse(SRC)


class LEssaiABlanc(unittest.TestCase):
    def setUp(self):
        self.maison = tempfile.mkdtemp(prefix="longtest-call-infra-")
        self.addCleanup(shutil.rmtree, self.maison, ignore_errors=True)

    def _fichiers(self):
        trouves = []
        for dossier, _sous, fichiers in os.walk(self.maison):
            trouves += [os.path.join(dossier, f) for f in fichiers]
        return trouves

    def test_it_lists_the_creation_commands_and_creates_nothing(self):
        code, sortie = lancer(self.maison, "--dry-run")
        self.assertEqual(0, code, sortie)
        self.assertIn("deploy_qemu.py", sortie)
        self.assertIn("--distro debian --version 13", sortie)
        self.assertIn("--distro arch --version latest", sortie)
        self.assertIn("long-call-infra-debian", sortie)
        self.assertIn("long-call-infra-arch", sortie)
        self.assertTrue(
            "--cache-ca" in sortie or "--cache-bypass" in sortie,
            "les drapeaux du cache manquent",
        )
        self.assertIn("--dry-run", sortie)
        # Rien de créé : ni rapport réel, ni entrée ssh, ni certificat.
        rapports = [f for f in self._fichiers() if f.endswith(".json")]
        self.assertTrue(rapports, "le plan doit écrire son rapport à blanc")
        for chemin in rapports:
            with self.subTest(chemin=chemin):
                self.assertTrue(chemin.endswith("-dryrun.json"))
                with open(chemin, encoding="utf-8") as fh:
                    rapport = json.load(fh)
                self.assertTrue(rapport["dry_run"])
                self.assertEqual("call_infra", rapport["outil"])
        self.assertFalse(os.path.exists(os.path.join(self.maison, ".ssh")))
        self.assertFalse([f for f in self._fichiers() if f.endswith(".crt")])
        # Le rapport à blanc et son journal, rien d'autre.
        self.assertEqual(
            [],
            [
                f
                for f in self._fichiers()
                if not f.endswith(("-dryrun.json", ".log"))
            ],
        )

    def test_one_distribution_only(self):
        code, sortie = lancer(self.maison, "--dry-run", "--distro", "arch")
        self.assertEqual(0, code, sortie)
        self.assertIn("--distro arch --version latest", sortie)
        self.assertNotIn("--distro debian", sortie)

    def test_an_unknown_distribution_is_refused(self):
        with self.assertRaises(SystemExit) as fin:
            lancer(self.maison, "--dry-run", "--distro", "fedora")
        self.assertNotEqual(0, fin.exception.code)

    # Les étapes de la production, dans l'ordre où elles tournent.
    PROD = (
        "certificats",
        "installation",
        "nginx-installe",
        "verification",
        "crochet-fourni",
        "crochet-lignee",
        "crochet-retour",
        "crochet-remise",
        "verification-apres-crochet",
        "rien-a-changer",
        "desinstallation",
        "etat-apres-desinstallation",
        "ports-fermes",
        "desinstallation-vide",
    )

    def _etapes(self, sortie):
        return [
            ligne.split("étapes : ", 1)[1].split(", ")
            for ligne in sortie.splitlines()
            if "étapes : " in ligne
        ]

    def test_the_production_plan_lists_its_steps_and_creates_nothing(self):
        code, sortie = lancer(self.maison, "--dry-run", "--scenario", "prod")
        self.assertEqual(0, code, sortie)
        self.assertIn("--distro debian --version 13", sortie)
        self.assertIn("--distro arch --version latest", sortie)
        self.assertIn("long-call-infra-debian", sortie)
        self.assertIn("long-call-infra-arch", sortie)
        debian, arch = self._etapes(sortie)
        self.assertEqual(
            ["vm", "ssh", "cloud-init", "ufw-actif", *self.PROD], debian
        )
        self.assertEqual(
            ["vm", "ssh", "cloud-init", "pacman", *self.PROD], arch
        )
        self.assertNotIn("ntfy-ancien", sortie)
        rapports = [f for f in self._fichiers() if f.endswith(".json")]
        self.assertTrue(rapports)
        self.assertTrue(all(f.endswith("-dryrun.json") for f in rapports))
        self.assertFalse(os.path.exists(os.path.join(self.maison, ".ssh")))
        self.assertFalse([f for f in self._fichiers() if f.endswith(".crt")])

    def test_the_development_plan_has_its_own_steps(self):
        code, sortie = lancer(self.maison, "--dry-run", "--scenario", "dev")
        self.assertEqual(0, code, sortie)
        self.assertEqual(
            [list(lt.ETAPES["dev"]["debian"]), list(lt.ETAPES["dev"]["arch"])],
            self._etapes(sortie),
        )
        self.assertNotIn("crochet", sortie)

    def test_both_scenarios_by_default(self):
        """Chaque scénario par défaut : dev et prod sur les deux systèmes,
        odoo et migration sur Debian, conteneur une fois par moteur."""
        code, sortie = lancer(self.maison, "--dry-run")
        self.assertEqual(0, code, sortie)
        self.assertEqual(9, len(self._etapes(sortie)))
        self.assertIn("ntfy-ancien", sortie)
        self.assertIn("crochet-lignee", sortie)
        self.assertIn("b-bascule", sortie)
        self.assertIn("odoo-secret", sortie)
        self.assertIn("migration-conteneurs", sortie)

    # Les étapes du scénario des serveurs Odoo, dans l'ordre où elles
    # tournent.
    ODOO = (
        "odoo-harnais",
        "installation",
        "a-fixe",
        "a-par-odoo",
        "a-retire",
        "a-revoque",
        "b-module",
        "b-bascule",
        "b-utilisateur",
        "b-invite",
        "c-module",
        "c-sans-redemarrage",
        "b-et-c",
        "verification-secret",
        "b-rotation",
        "b-grace",
        "c-retire",
        "b-reste",
        "c-revoque",
        "a-refuse",
        "b-retire",
        "desinstallation",
        "bases-supprimees",
    )

    def _bases(self, sortie):
        return [
            ligne.split("bases : ", 1)[1].split(", ")
            for ligne in sortie.splitlines()
            if "bases : " in ligne
        ]

    def test_the_odoo_plan_lists_its_steps_and_databases(self):
        code, sortie = lancer(self.maison, "--dry-run", "--scenario", "odoo")
        self.assertEqual(0, code, sortie)
        self.assertIn("--distro debian --version 13", sortie)
        self.assertNotIn("--distro arch", sortie)
        self.assertEqual(
            [["vm", "ssh", "cloud-init", "ufw-actif", *self.ODOO]],
            self._etapes(sortie),
        )
        (bases,) = self._bases(sortie)
        self.assertEqual(3, len(bases))
        for base, lettre in zip(bases, "abc"):
            with self.subTest(base=base):
                self.assertRegex(base, rf"^call_infra_odoo_\d+_\d+_{lettre}$")
                self.assertLessEqual(len(base), 63)
        self.assertNotIn("mobile_sync_", sortie)
        # Rien de créé : ni base, ni serveur, ni dossier de course.
        self.assertEqual(
            [],
            [
                f
                for f in self._fichiers()
                if not f.endswith(("-dryrun.json", ".log"))
            ],
        )

    def test_the_odoo_scenario_runs_on_debian_only(self):
        code, sortie = lancer(
            self.maison, "--dry-run", "--distro", "arch", "--scenario", "odoo"
        )
        self.assertEqual(1, code)
        self.assertIn("debian", sortie)
        self.assertNotIn("deploy_qemu.py", sortie)
        code, sortie = lancer(self.maison, "--dry-run", "--scenario", "odoo")
        self.assertEqual(0, code, sortie)
        self.assertEqual(1, len(self._etapes(sortie)))
        code, sortie = lancer(self.maison, "--dry-run", "--distro", "arch")
        self.assertEqual(0, code, sortie)
        self.assertEqual(2, len(self._etapes(sortie)))
        self.assertEqual([], self._bases(sortie))

    def test_an_unknown_scenario_is_refused(self):
        with self.assertRaises(SystemExit) as fin:
            lancer(self.maison, "--dry-run", "--scenario", "staging")
        self.assertNotEqual(0, fin.exception.code)


class LeDefaire(unittest.TestCase):
    """La forme du rapport est le CONTRAT du défaire partagé (descente.py) :
    « outil », « pid », et une entrée de niveau 1 par VM encore debout."""

    ETAGE = {
        "niveau": 1,
        "nom": "long-call-infra-debian",
        "uuid": "aaaa-bbbb",
        "alias": "long-call-infra-debian",
        "cree": True,
    }

    def setUp(self):
        self.maison = tempfile.mkdtemp(prefix="longtest-call-infra-")
        self.dossier = os.path.join(self.maison, ".erplibre/longtest")
        os.makedirs(self.dossier)
        self.addCleanup(shutil.rmtree, self.maison, ignore_errors=True)

    def _defaire(self, rapport):
        with open(
            os.path.join(self.dossier, "long-call-infra-19990101-000000.json"),
            "w",
            encoding="utf-8",
        ) as fh:
            json.dump(rapport, fh)
        return lancer(self.maison, "--detruire", "--dry-run")[1]

    def test_the_report_names_the_vm(self):
        sortie = self._defaire(
            {
                "outil": "call_infra",
                "dry_run": False,
                "pid": 1,
                "etages": [self.ETAGE],
            }
        )
        self.assertIn("long-call-infra-debian", sortie)
        self.assertIn("rien ne sera détruit", sortie)

    def test_a_dry_run_report_is_never_used(self):
        sortie = self._defaire(
            {
                "outil": "call_infra",
                "dry_run": True,
                "pid": 1,
                "etages": [self.ETAGE],
            }
        )
        self.assertIn("rien à défaire", sortie)

    def test_another_tool_report_is_not_ours(self):
        sortie = self._defaire(
            {
                "outil": "install_nixos",
                "dry_run": False,
                "pid": 1,
                "etages": [self.ETAGE],
            }
        )
        self.assertIn("rien à défaire", sortie)

    def test_the_report_carries_the_pid_of_its_run(self):
        self.assertIn('"pid": os.getpid()', SRC)


class RienNInterrompLaCourse(unittest.TestCase):
    """`subprocess.run(..., timeout=...)` lève TimeoutExpired quand la
    commande dépasse son délai : un test lancé sans surveillance doit
    rendre un verdict, pas une trace."""

    def test_every_bounded_call_is_caught(self):
        arbre = ast.parse(SRC)
        bornes = [
            n.lineno
            for n in ast.walk(arbre)
            if isinstance(n, ast.Call)
            and ast.unparse(n.func) == "subprocess.run"
            and any(m.arg == "timeout" for m in n.keywords)
        ]
        self.assertGreaterEqual(len(bornes), 3)
        couvertes = set()
        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.Try) and self._attrape_le_delai(noeud):
                for corps in noeud.body:
                    for interne in ast.walk(corps):
                        if hasattr(interne, "lineno"):
                            couvertes.add(interne.lineno)
        for ligne in bornes:
            with self.subTest(ligne=ligne):
                self.assertIn(ligne, couvertes)

    # Les classes dont TimeoutExpired hérite, elle comprise : un `except`
    # qui en nomme une rattrape le délai dépassé.
    PARENTS_DU_DELAI = {
        "TimeoutExpired",
        "SubprocessError",
        "Exception",
        "BaseException",
    }

    @classmethod
    def _attrape_le_delai(cls, essai):
        """Vrai quand un `except` de `essai` est nu ou nomme une classe de
        PARENTS_DU_DELAI, seule ou dans un tuple."""
        for gestion in essai.handlers:
            if gestion.type is None:
                return True
            types = (
                gestion.type.elts
                if isinstance(gestion.type, ast.Tuple)
                else [gestion.type]
            )
            noms = {ast.unparse(t).rsplit(".", 1)[-1] for t in types}
            if noms & cls.PARENTS_DU_DELAI:
                return True
        return False

    def test_a_handler_without_the_timeout_does_not_count(self):
        """Un `except OSError` laisse passer TimeoutExpired : l'appel qu'il
        entoure n'est pas rattrapé."""

        def essai(source):
            return ast.parse(source).body[0]

        self.assertFalse(
            self._attrape_le_delai(essai("try:\n x()\nexcept OSError:\n y"))
        )
        for gestion in (
            "except (OSError, subprocess.SubprocessError):",
            "except subprocess.TimeoutExpired:",
            "except Exception:",
            "except:",
        ):
            with self.subTest(gestion=gestion):
                self.assertTrue(
                    self._attrape_le_delai(essai(f"try:\n x()\n{gestion}\n y"))
                )

    def test_every_run_is_bounded(self):
        """Un appel sans délai pend la course entière sur un ssh muet."""
        arbre = ast.parse(SRC)
        for n in ast.walk(arbre):
            if (
                isinstance(n, ast.Call)
                and ast.unparse(n.func) == "subprocess.run"
            ):
                with self.subTest(ligne=n.lineno):
                    self.assertTrue(
                        any(m.arg == "timeout" for m in n.keywords)
                    )


class LaPlaceDesVM(unittest.TestCase):
    """`--garder` laisse chaque VM debout : la place se compte pour toutes
    celles de la course, pas pour une seule."""

    # Assez pour une VM et sa marge, pas pour deux.
    UNE = (8, lt.MEMOIRE_MO + lt.MARGE_RAM_MO + 512, 100)

    def setUp(self):
        self.maison = tempfile.mkdtemp(prefix="longtest-call-infra-")
        self.addCleanup(shutil.rmtree, self.maison, ignore_errors=True)
        self.journal = os.path.join(self.maison, "x.log")

    def _plan(self, nombre):
        with (
            mock.patch.object(lt, "capacite_hote", return_value=self.UNE),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            return lt.plan_tient(self.journal, nombre)

    def test_room_for_one_vm(self):
        self.assertTrue(self._plan(1))

    def test_room_for_two_vms(self):
        self.assertFalse(self._plan(2))
        large = (8, 2 * (lt.MEMOIRE_MO + lt.MARGE_RAM_MO), 100)
        with (
            mock.patch.object(lt, "capacite_hote", return_value=large),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertTrue(lt.plan_tient(self.journal, 2))

    def _mener(self, *args):
        crees = []
        with (
            mock.patch.object(lt, "capacite_hote", return_value=self.UNE),
            mock.patch.object(
                lt,
                "mener_un",
                side_effect=lambda c, d, s, v=None: self._vu(crees, d, s, v),
            ),
        ):
            code, _sortie = lancer(self.maison, *args)
        return code, crees

    @staticmethod
    def _vu(crees, distro, scenario, variante=None):
        crees.append((distro, scenario, *([variante] if variante else [])))
        return {"distro": distro, "scenario": scenario, "verdict": "OK"}

    def test_keeping_every_vm_asks_room_for_each(self):
        code, crees = self._mener("--garder", "--scenario", "dev")
        self.assertEqual(1, code)
        self.assertEqual([], crees)

    def test_keeping_one_system_asks_room_for_one(self):
        _code, crees = self._mener(
            "--garder", "--distro", "arch", "--scenario", "prod"
        )
        self.assertEqual([("arch", "prod")], crees)

    def test_keeping_needs_one_scenario(self):
        """Les deux scénarios d'un système prennent le même nom de VM :
        garder la première ferait refuser la seconde. La course le dit
        avant de rien créer, même quand la place ne manque pas."""
        crees = []
        large = (16, 10 * (lt.MEMOIRE_MO + lt.MARGE_RAM_MO), 1000)
        with (
            mock.patch.object(lt, "capacite_hote", return_value=large),
            mock.patch.object(
                lt,
                "mener_un",
                side_effect=lambda c, d, s, v=None: self._vu(crees, d, s, v),
            ),
        ):
            code, sortie = lancer(self.maison, "--garder")
        self.assertEqual(1, code)
        self.assertEqual([], crees)
        self.assertIn("--scenario dev", sortie)
        _code, crees = self._mener("--garder", "--scenario", "dev")
        self.assertEqual([], crees, "la place pour deux VM manque")

    def test_both_scenarios_run_one_after_the_other(self):
        code, crees = self._mener()
        self.assertEqual(0, code)
        self.assertEqual(
            [
                ("debian", "dev"),
                ("debian", "prod"),
                ("debian", "odoo"),
                ("debian", "conteneur", "docker"),
                ("debian", "conteneur", "podman"),
                ("debian", "conteneur", "podman-rootless"),
                ("debian", "migration"),
                ("arch", "dev"),
                ("arch", "prod"),
            ],
            crees,
        )

    def test_keeping_one_engine_keeps_one_vm(self):
        """Les courses d'un système prennent le même nom de VM : trois
        moteurs ne se gardent pas ensemble, un seul oui."""
        code, crees = self._mener("--garder", "--scenario", "conteneur")
        self.assertEqual((1, []), (code, crees))
        _code, crees = self._mener(
            "--garder", "--scenario", "conteneur", "--moteur", "podman"
        )
        self.assertEqual([("debian", "conteneur", "podman")], crees)


class LesListes(unittest.TestCase):
    def test_it_shares_the_lock(self):
        self.assertIn("call_infra.py", descente.SCRIPTS)

    def test_the_menu_can_undo_it(self):
        from script.todo.longtest_menu import (
            SCRIPTS_DEFAISABLES,
            SCRIPTS_DESCENTE,
        )

        self.assertIn("call_infra.py", SCRIPTS_DESCENTE)
        self.assertIn("call_infra.py", SCRIPTS_DEFAISABLES)


class LeMenu(unittest.TestCase):
    def setUp(self):
        from script.todo.todo import TODO

        self.todo = TODO.__new__(TODO)

    def test_the_menu_launches_the_plan_and_the_run(self):
        vus = []
        self.todo.fill_help_info = lambda choix: ""
        self.todo._longtest_run = lambda nom, args="", demander=None: (
            vus.append((nom, args))
        )
        with mock.patch(
            "script.todo.longtest_menu.click.prompt",
            side_effect=["16", "17", "0"],
        ):
            with contextlib.redirect_stdout(io.StringIO()):
                self.todo.prompt_execute_longtest()
        self.assertEqual(
            vus, [("call_infra.py", "--dry-run"), ("call_infra.py", "")]
        )

    def test_the_labels_are_translated(self):
        menu = (RACINE / "script/todo/longtest_menu.py").read_text(
            encoding="utf-8"
        )
        for cle in (
            "Call infrastructure on throwaway VMs: plan only (dry-run)",
            "Call infrastructure on throwaway VMs: run it",
        ):
            with self.subTest(cle=cle):
                self.assertIn(cle, menu)
                self.assertIn(cle, todo_i18n.TRANSLATIONS)

    def test_its_question_says_what_it_creates(self):
        question = self.todo._longtest_question("", "call_infra.py")
        self.assertNotEqual(question, self.todo._longtest_question(""))
        for cle in question:
            with self.subTest(cle=cle):
                self.assertIn(cle, todo_i18n.TRANSLATIONS)
                self.assertIn("fr", todo_i18n.TRANSLATIONS[cle])

    def test_destroying_asks_the_destroy_question(self):
        """La destruction de ce test supprime aussi ses bases Odoo : sa
        question le dit, dans les deux langues."""
        question = self.todo._longtest_question("--detruire", "call_infra.py")
        self.assertNotEqual(
            question, self.todo._longtest_question("--detruire")
        )
        self.assertNotEqual(
            question, self.todo._longtest_question("", "call_infra.py")
        )
        avertissement = todo_i18n.TRANSLATIONS[question[0]]
        for langue in ("fr", "en"):
            with self.subTest(langue=langue):
                self.assertIn("call_infra_odoo_", avertissement[langue])
                self.assertIn(langue, todo_i18n.TRANSLATIONS[question[1]])

    def test_its_question_counts_the_vms_of_a_full_run(self):
        """Une VM par course : le nombre que l'avertissement du menu
        annonce est celui des courses d'une course complète."""
        maison = tempfile.mkdtemp(prefix="longtest-call-infra-")
        self.addCleanup(shutil.rmtree, maison, ignore_errors=True)
        code, sortie = lancer(maison, "--dry-run")
        self.assertEqual(0, code, sortie)
        courses = sum("étapes : " in ligne for ligne in sortie.splitlines())
        mots = {9: ("nine VMs", "neuf VM")}
        avertissement, _q = self.todo._longtest_question("", "call_infra.py")
        textes = todo_i18n.TRANSLATIONS[avertissement]
        self.assertIn(courses, mots)
        self.assertIn(mots[courses][0], textes["en"])
        self.assertIn(mots[courses][1], textes["fr"])

    def test_its_question_names_the_odoo_scenario(self):
        avertissement, _q = self.todo._longtest_question("", "call_infra.py")
        textes = todo_i18n.TRANSLATIONS[avertissement]
        for langue in ("fr", "en"):
            with self.subTest(langue=langue):
                self.assertIn("Odoo", textes[langue])
                self.assertIn("odoo", textes[langue])


class LeReadme(unittest.TestCase):
    def test_the_readme_documents_it_in_both_languages(self):
        base = (RACINE / "long_test/README.base.md").read_text(
            encoding="utf-8"
        )
        self.assertEqual(base.count("## call_infra.py"), 2)
        for nom in ("README.md", "README.fr.md"):
            with self.subTest(nom=nom):
                texte = (RACINE / "long_test" / nom).read_text(
                    encoding="utf-8"
                )
                self.assertIn("## call_infra.py", texte)

    def test_the_odoo_scenario_is_documented_in_both_halves(self):
        base = (RACINE / "long_test/README.base.md").read_text(
            encoding="utf-8"
        )
        sections = base.split("## call_infra.py")[1:]
        for nom in ("README.md", "README.fr.md"):
            texte = (RACINE / "long_test" / nom).read_text(encoding="utf-8")
            sections.append(texte.split("## call_infra.py", 1)[1])
        for section in sections:
            section = section.split("\n## ", 1)[0]
            with self.subTest(debut=section[:60]):
                for mot in (
                    "--scenario odoo",
                    "erplibre_turn",
                    "call_infra_odoo_",
                    "use-auth-secret",
                    "join_call_ice_guest",
                ):
                    self.assertIn(mot, section)

    def test_the_production_scenario_is_documented_in_both_halves(self):
        base = (RACINE / "long_test/README.base.md").read_text(
            encoding="utf-8"
        )
        sections = base.split("## call_infra.py")[1:]
        self.assertEqual(2, len(sections))
        for nom in ("README.md", "README.fr.md"):
            texte = (RACINE / "long_test" / nom).read_text(encoding="utf-8")
            sections.append(texte.split("## call_infra.py", 1)[1])
        for section in sections:
            section = section.split("\n## ", 1)[0]
            with self.subTest(debut=section[:60]):
                for mot in (
                    "--scenario prod",
                    "nginx",
                    "RENEWED_LINEAGE",
                    "MainPID",
                    "turn.call.exemple.test",
                ):
                    self.assertIn(mot, section)

    def test_the_container_scenarios_are_documented_in_both_halves(self):
        base = (RACINE / "long_test/README.base.md").read_text(
            encoding="utf-8"
        )
        sections = base.split("## call_infra.py")[1:]
        for nom in ("README.md", "README.fr.md"):
            texte = (RACINE / "long_test" / nom).read_text(encoding="utf-8")
            sections.append(texte.split("## call_infra.py", 1)[1])
        for section in sections:
            section = section.split("\n## ", 1)[0]
            with self.subTest(debut=section[:60]):
                for mot in (
                    "--scenario conteneur",
                    "--moteur",
                    "podman-rootless",
                    "--scenario migration",
                    "limite-registre",
                    "Docker Hub",
                    "call_infra_ntfy_downgrade",
                ):
                    self.assertIn(mot, section)


class LesBriques(unittest.TestCase):
    def test_vm_names(self):
        self.assertEqual("long-call-infra-debian", lt.nom_vm("debian"))
        self.assertEqual("long-call-infra-arch", lt.nom_vm("arch"))

    def test_creation_line(self):
        argv = lt.argv_creation(
            "debian", "long-call-infra-debian", "", ["--cache-bypass"]
        )
        texte = " ".join(argv)
        self.assertIn("deploy_qemu.py --distro debian --version 13", texte)
        self.assertIn("--name long-call-infra-debian", texte)
        self.assertEqual("--cache-bypass", argv[-1])
        self.assertNotIn("sudo", argv)
        argv = lt.argv_creation("arch", "x", "/k.pub")
        self.assertIn("--version", argv)
        self.assertEqual("latest", argv[argv.index("--version") + 1])
        self.assertEqual("/k.pub", argv[argv.index("--ssh-key") + 1])

    def test_secrets_are_masked(self):
        texte = (
            "[NTFY] ok\n"
            "@@ADMIN_PASSWORD Mot-de-passe-invente-42\n"
            "@@CHECK_KEY 0123456789abcdef0123456789abcdef\r\n"
            "@@TURN_SECRET turn.exemple.test Secret-invente-du-journal-55\n"
            "@@TURN_USER turn.exemple.test erplibre-0a1b2c3d "
            "fedcba9876543210fedcba9876543210\n"
            "@@ACTIVE ntfy active\n"
        )
        masque = lt.masquer(texte)
        self.assertNotIn("Secret-invente-du-journal-55", masque)
        self.assertNotIn("fedcba9876543210", masque)
        self.assertIn("@@TURN_SECRET ***", masque)
        self.assertIn("@@TURN_USER ***", masque)
        self.assertNotIn("Mot-de-passe-invente-42", masque)
        self.assertNotIn("0123456789abcdef", masque)
        self.assertIn("@@ADMIN_PASSWORD ***", masque)
        self.assertIn("@@CHECK_KEY ***", masque)
        self.assertIn("@@ACTIVE ntfy active", masque)

    def test_phone_tokens_are_masked(self):
        """Le jeton qu'imprime `ntfy token add` ouvre les sujets du
        téléphone tant que la VM vit : il ne va pas au journal, où qu'il
        soit dans la ligne."""
        texte = (
            "token tk_Inventeabc123XYZ created for user erm_longtest\n"
            "autre tk_Zz9 fin\r\n"
            "tk_ seul, sans jeton\n"
        )
        masque = lt.masquer(texte)
        self.assertNotIn("tk_Inventeabc123XYZ", masque)
        self.assertNotIn("tk_Zz9", masque)
        self.assertIn("token tk_*** created for user erm_longtest\n", masque)
        self.assertIn("autre tk_*** fin\r\n", masque)
        self.assertIn("tk_ seul, sans jeton\n", masque)

    def test_remote_command_reads_the_script_from_stdin(self):
        """Le corps du script ne passe ni dans l'argv local de ssh ni dans
        le journal : il arrive par l'entrée standard."""
        commande = lt.commande_distante()
        self.assertTrue(commande.startswith("sudo -n "))
        self.assertTrue(
            commande.endswith("""sh -c 'eval "$(cat)" </dev/null'""")
        )
        commande = lt.commande_distante(utilisateur="ntfy")
        self.assertIn("-u ntfy", commande)
        commande = lt.commande_distante(
            env={"NTFY_BASE_URL": "http://192.0.2.10:8080"}, shell="bash"
        )
        self.assertIn("env NTFY_BASE_URL=http://192.0.2.10:8080", commande)
        self.assertIn("""bash -c 'eval "$(cat)" </dev/null'""", commande)
        commande = lt.commande_distante(root=False, shell="bash")
        self.assertFalse(commande.startswith("sudo"))

    def test_the_script_never_becomes_an_argv_of_the_remote_shell(self):
        """Joué pour de vrai par un `sh` local, comme l'hôte le ferait :
        le script ne paraît pas dans l'argv du shell qui le joue, et ses
        commandes ne lisent rien de l'entrée standard."""
        script = (
            "secret=jeton-invente-0123\n"
            'tr "\\0" " " </proc/$$/cmdline; echo\n'
            'lu=$(cat); echo "lu=[$lu]"\n'
        )
        fait = subprocess.run(
            ["sh", "-c", lt.commande_distante(root=False)],
            input=script.encode(),
            stdout=subprocess.PIPE,
            check=True,
        )
        sortie = fait.stdout.decode()
        self.assertNotIn("jeton-invente-0123", sortie)
        self.assertIn("lu=[]", sortie)

    def test_check_verdict(self):
        L = ci.CheckLine
        requis = ("turn-udp", "ntfy-health")
        lignes = [
            L("turn-udp", True, "call_infra_check_relayed"),
            L("ntfy-health", True, "call_infra_check_healthy"),
            L("firewall", None, "call_infra_check_firewall_none"),
        ]
        self.assertEqual((True, []), lt.verdict_controle(lignes, requis))
        manque = lignes[1:]
        self.assertEqual(
            (False, ["turn-udp"]), lt.verdict_controle(manque, requis)
        )
        douteux = [lignes[0], L("ntfy-health", None, "x"), lignes[2]]
        self.assertEqual(
            (False, ["ntfy-health"]), lt.verdict_controle(douteux, requis)
        )
        rouge = lignes[:2] + [L("cert-expiry", False, "x")]
        self.assertEqual(
            (False, ["cert-expiry"]), lt.verdict_controle(rouge, requis)
        )

    def test_mixing_result(self):
        self.assertEqual("melange-ok", lt.resultat_melange(True, True))
        self.assertEqual("melange-refuse", lt.resultat_melange(False, True))
        self.assertEqual("melange-refuse", lt.resultat_melange(True, False))

    def test_answers(self):
        debian = lt.reponses(IP, "CERT", "KEY")
        self.assertEqual(frozenset(ci.SERVICES), debian.services)
        self.assertEqual("supplied", debian.tls)
        self.assertEqual(("CERT", "KEY"), (debian.cert_pem, debian.key_pem))
        self.assertEqual(IP, debian.public_name)
        arch = lt.reponses(IP)
        self.assertEqual("none", arch.tls)
        self.assertIsNone(arch.cert_pem)

    def test_the_menu_bricks_are_used_not_copied(self):
        for brique in (
            "ci.probe_script",
            "ci.parse_probe",
            "ci.plan_install",
            "ci.install_script",
            "ci.installed_state",
            "ci.firewall_preview",
            "ci.firewall_script",
            "ci.firewall_record",
            "ci.with_firewall",
            "ci.state_write_script",
            "ci.check_remote_script",
            "ci.parse_check_remote",
            "ci.check_local",
            "ci.uninstall_script",
            "nm.access_script",
            "nm.list_script",
            "local_cert.issue",
            "turn_client.allocate",
            "turn_client.rest_credentials",
            "_qemu_cloud_init_wait",
            "_qemu_pacman_prepare_cmd",
            "ci.default_names",
            "ci.certificate_names",
            "ci.external_ip_for",
            "ci.deploy_hook_text",
            "_call_infra_nginx_facts",
            "ci.plan_odoo_add",
            "ci.apply_odoo_add",
            "ci.apply_odoo_remove",
            "ci.turn_mode_for",
            "ci.check_through_odoo",
            "ci.state_answers",
            "ci.turn_host",
            ".join_call_ice(",
            ".join_call_ice_guest(",
            "ol.WebApi",
            "ol.owned_username",
            "_call_infra_module_kind",
            "_call_infra_ntfy_text",
            "_call_infra_exempt_ok",
            "mso.versions_installees",
            "mso.construire_gabarit",
            "mso.copier_gabarit",
            "mso.demarrer_serveur",
            "mso.arreter_serveur",
            "mso.supprimer_base",
            "ci.engine_offer",
            "ci.method_refusal",
            "ci.odoo_add_script",
            "ci.odoo_added_state",
            "ci.odoo_result",
            "ci.ntfy_cli",
            "cc.engine_argv",
            "cc.rootless_prefix",
            "cc.version_older",
            "cim.PORT_REFUSAL",
        ):
            with self.subTest(brique=brique):
                self.assertIn(brique, SRC)


DEBIAN_UFW_PROBE = (
    "\n@@OS debian 13 \n@@SYSTEMD yes\n@@HOSTNAME vm\n"
    f"@@ADDR {IP}\n@@PORT tcp 22 sshd\n"
    "@@COTURN - - -\n@@NTFY - - /etc/ntfy/server.yml\n"
    "@@FIREWALL ufw\n@@END\n"
)


class Hote:
    """Faux transport : rend les sorties dans l'ordre, retient les
    scripts reçus."""

    def __init__(self, *sorties):
        self.sorties = list(sorties)
        self.scripts = []
        self.options = []

    def __call__(self, cible, script, log, delai, **kw):
        self.scripts.append(script)
        self.options.append(kw)
        return self.sorties.pop(0)


class LeCheminDuMenu(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.mkdtemp(prefix="longtest-call-infra-")
        self.addCleanup(shutil.rmtree, self.dossier, ignore_errors=True)
        self.log = os.path.join(self.dossier, "x.log")
        self.ans = lt.reponses(IP)

    def test_install_probe_install_firewall_state(self):
        regles = ci.firewall_rules(self.ans)
        ajout = "".join(
            f"@@FIREWALL_ADDED {r.proto} {r.port} {r.service}\n"
            for r in regles
        )
        hote = Hote(
            (0, DEBIAN_UFW_PROBE),
            (0, "@@ACTIVE coturn active\n@@ACTIVE ntfy active\n@@SAVED yes"),
            (0, ajout + "@@FIREWALL_PERSISTED yes\n@@END\n"),
            (0, "@@SAVED yes\n"),
        )
        res = lt.installer("vm", self.ans, self.log, executer=hote)
        self.assertTrue(res["ok"], res)
        self.assertFalse(res["rien_a_faire"])
        self.assertEqual(4, len(hote.scripts))
        self.assertEqual(ci.probe_script(), hote.scripts[0])
        self.assertIn("@@SAVED yes", hote.scripts[1])
        self.assertEqual(
            ci.firewall_script("ufw", regles, "allow"), hote.scripts[2]
        )
        etat = res["etat"]
        self.assertEqual("ufw", etat["firewall"]["kind"])
        self.assertEqual(len(regles), len(etat["firewall"]["rules"]))
        self.assertEqual(ci.state_write_script(etat), hote.scripts[3])

    def test_http_challenge_opens_the_firewall_before_the_install(self):
        # Comme le menu : le défi HTTP-01 passe pendant l'installation.
        ans = ci.Answers(
            services=frozenset({"coturn"}),
            tls="letsencrypt",
            cert_pem=None,
            key_pem=None,
            public_name="exemple.test",
            mode="production",
            turn_name="turn.exemple.test",
            acme="http-standalone",
            min_port=ci.PROD_MIN_PORT,
            max_port=ci.PROD_MAX_PORT,
        )
        regles = ci.firewall_rules(ans)
        ajout = "".join(
            f"@@FIREWALL_ADDED {r.proto} {r.port} {r.service}\n"
            for r in regles
        )
        hote = Hote(
            (0, DEBIAN_UFW_PROBE),
            (0, ajout + "@@FIREWALL_PERSISTED yes\n@@END\n"),
            (0, "@@ACTIVE coturn active\n@@SAVED yes"),
            (0, "@@SAVED yes\n"),
        )
        res = lt.installer("vm", ans, self.log, executer=hote)
        self.assertTrue(res["ok"], res)
        self.assertEqual(4, len(hote.scripts))
        self.assertEqual(
            ci.firewall_script("ufw", regles, "allow"), hote.scripts[1]
        )
        self.assertIn("@@ACTIVE", hote.scripts[2])
        self.assertEqual(len(regles), len(res["etat"]["firewall"]["rules"]))
        # Un pare-feu en échec arrête avant l'installation.
        hote = Hote((0, DEBIAN_UFW_PROBE), (1, "@@FIREWALL_FAILED\n"))
        res = lt.installer("vm", ans, self.log, executer=hote)
        self.assertEqual("pare-feu", res["etape"])
        self.assertEqual(2, len(hote.scripts))

    def test_no_firewall_runs_no_firewall_script(self):
        sonde = DEBIAN_UFW_PROBE.replace("ufw", "none")
        hote = Hote(
            (0, sonde),
            (0, "@@ACTIVE coturn active\n@@ACTIVE ntfy active\n@@SAVED yes"),
            (0, "@@SAVED yes\n"),
        )
        res = lt.installer("vm", self.ans, self.log, executer=hote)
        self.assertTrue(res["ok"], res)
        self.assertEqual(3, len(hote.scripts))

    def test_a_failed_install_stops_before_the_state(self):
        hote = Hote(
            (0, DEBIAN_UFW_PROBE),
            (1, "@@FAILED payload-ntfy\n@@SAVED no\n"),
        )
        res = lt.installer("vm", self.ans, self.log, executer=hote)
        self.assertFalse(res["ok"])
        self.assertEqual("install", res["etape"])
        self.assertEqual(2, len(hote.scripts))

    def test_same_answers_change_nothing(self):
        facts = ci.parse_probe(DEBIAN_UFW_PROBE.replace("ufw", "none"))
        plan = ci.plan_install(facts, self.ans, NOW)
        etat = ci.written_state(plan, "20261030-000000")
        sonde = (
            "@@OS debian 13 \n@@SYSTEMD yes\n@@HOSTNAME vm\n"
            f"@@ADDR {IP}\n"
            "@@PORT udp 3478 turnserver\n@@PORT tcp 3478 turnserver\n"
            "@@PORT tcp 8080 ntfy\n"
            "@@COTURN coturn active /etc/turnserver.conf\n"
            "@@NTFY ntfy active /etc/ntfy/server.yml\n"
            f"@@FILE /etc/turnserver.conf {b64(ci.coturn_config(self.ans))}\n"
            f"@@FILE /etc/ntfy/server.yml {b64(plan.configs['ntfy'])}\n"
            "@@FIREWALL none\n"
            f"@@STATE {b64(json.dumps(etat))}\n@@END\n"
        )
        hote = Hote((0, sonde))
        res = lt.installer("vm", self.ans, self.log, executer=hote)
        self.assertTrue(res["ok"], res)
        self.assertTrue(res["rien_a_faire"])
        self.assertEqual(1, len(hote.scripts))

    def test_the_admin_added_to_an_adopted_ntfy_is_recorded(self):
        """L'installateur crée l'administrateur dans un ntfy adopté : l'état
        le dit, pour que la désinstallation l'en retire comme le menu."""
        etrangere = 'listen-http: ":8080"\nauth-default-access: "deny-all"\n'
        sonde = (
            DEBIAN_UFW_PROBE.replace("ufw", "none")
            .replace(
                "@@PORT tcp 22 sshd",
                "@@PORT tcp 22 sshd\n@@PORT tcp 8080 ntfy",
            )
            .replace(
                "@@NTFY - - /etc/ntfy/server.yml",
                "@@NTFY ntfy active /etc/ntfy/server.yml\n"
                f"@@FILE /etc/ntfy/server.yml {b64(etrangere)}",
            )
        )
        hote = Hote(
            (0, sonde),
            (
                0,
                "@@ADMIN_PASSWORD Mot-de-passe-invente-42\n"
                "@@ACTIVE coturn active\n@@ACTIVE ntfy active\n@@SAVED yes",
            ),
            (0, "@@SAVED yes\n"),
        )
        res = lt.installer("vm", self.ans, self.log, executer=hote)
        self.assertTrue(res["ok"], res)
        self.assertIn("ntfy", res["adoptes"])
        self.assertIs(True, res["etat"]["services"]["ntfy"]["admin_added"])
        self.assertEqual(ci.state_write_script(res["etat"]), hote.scripts[2])

    def test_rules_left_pending_by_a_cut_run_are_recorded(self):
        """Une règle posée par un passage dont l'état ne s'est pas écrit
        (`pending/firewall`) entre à l'état, même quand le pare-feu de ce
        passage ne la remontre pas."""
        sonde = DEBIAN_UFW_PROBE.replace(
            "@@END", "@@FIREWALL_PENDING ufw tcp 5349 coturn\n@@END"
        )
        hote = Hote(
            (0, sonde),
            (0, "@@ACTIVE coturn active\n@@ACTIVE ntfy active\n@@SAVED yes"),
            (0, "@@FIREWALL_PERSISTED yes\n@@END\n"),
            (0, "@@SAVED yes\n"),
        )
        res = lt.installer("vm", self.ans, self.log, executer=hote)
        self.assertTrue(res["ok"], res)
        self.assertIn(
            ["tcp", "5349", "coturn"], res["etat"]["firewall"]["rules"]
        )

    def _sonde_a_jour(self, pare_feu, etat=None, fin=""):
        """La sonde d'un hôte où les deux services sont déjà ceux de
        `self.ans` : le plan n'y trouve rien à changer."""
        facts = ci.parse_probe(DEBIAN_UFW_PROBE.replace("ufw", "none"))
        plan = ci.plan_install(facts, self.ans, NOW)
        if etat is None:
            etat = ci.written_state(plan, "20261030-000000")
        return (
            "@@OS debian 13 \n@@SYSTEMD yes\n@@HOSTNAME vm\n"
            f"@@ADDR {IP}\n"
            "@@PORT udp 3478 turnserver\n@@PORT tcp 3478 turnserver\n"
            "@@PORT tcp 8080 ntfy\n"
            "@@COTURN coturn active /etc/turnserver.conf\n"
            "@@NTFY ntfy active /etc/ntfy/server.yml\n"
            f"@@FILE /etc/turnserver.conf {b64(ci.coturn_config(self.ans))}\n"
            f"@@FILE /etc/ntfy/server.yml {b64(plan.configs['ntfy'])}\n"
            f"@@FIREWALL {pare_feu}\n"
            f"@@STATE {b64(json.dumps(etat))}\n{fin}@@END\n"
        ), etat

    def test_nothing_to_change_still_offers_missing_rules(self):
        """Services à jour, règles absentes de l'état : la relance pose et
        consigne le pare-feu, comme le menu."""
        sonde, etat = self._sonde_a_jour("ufw")
        regles = ci.firewall_rules(self.ans)
        ajout = "".join(
            f"@@FIREWALL_ADDED {r.proto} {r.port} {r.service}\n"
            for r in regles
        )
        hote = Hote(
            (0, sonde),
            (0, ajout + "@@FIREWALL_PERSISTED yes\n@@END\n"),
            (0, "@@SAVED yes\n"),
        )
        res = lt.installer("vm", self.ans, self.log, executer=hote)
        self.assertTrue(res["ok"], res)
        self.assertTrue(res["rien_a_faire"])
        self.assertEqual(3, len(hote.scripts))
        self.assertEqual(
            ci.firewall_script("ufw", regles, "allow"), hote.scripts[1]
        )
        self.assertEqual(len(regles), len(res["etat"]["firewall"]["rules"]))
        self.assertEqual(ci.state_write_script(res["etat"]), hote.scripts[2])
        self.assertEqual(etat["services"], res["etat"]["services"])

    def test_nothing_to_change_with_rules_recorded_runs_nothing(self):
        sonde, etat = self._sonde_a_jour("ufw")
        record = ci.firewall_record(
            "ufw",
            "".join(
                f"@@FIREWALL_ADDED {r.proto} {r.port} {r.service}\n"
                for r in ci.firewall_rules(self.ans)
            ),
        )
        sonde, _etat = self._sonde_a_jour(
            "ufw", ci.with_firewall(etat, record)
        )
        hote = Hote((0, sonde))
        res = lt.installer("vm", self.ans, self.log, executer=hote)
        self.assertTrue(res["ok"] and res["rien_a_faire"], res)
        self.assertEqual(1, len(hote.scripts))

    def test_a_refusal_is_a_failed_plan(self):
        hote = Hote((0, DEBIAN_UFW_PROBE.replace("debian 13", "fedora 43")))
        res = lt.installer("vm", self.ans, self.log, executer=hote)
        self.assertFalse(res["ok"])
        self.assertEqual("plan", res["etape"])

    def test_uninstall_without_state_is_nothing(self):
        hote = Hote((0, DEBIAN_UFW_PROBE), (0, "@@NOTHING\n"))
        self.assertEqual(
            "rien", lt.desinstaller("vm", True, self.log, executer=hote)
        )
        self.assertIn("@@NOTHING", hote.scripts[1])

    def test_uninstall_with_state(self):
        facts = ci.parse_probe(DEBIAN_UFW_PROBE.replace("ufw", "none"))
        plan = ci.plan_install(facts, self.ans, NOW)
        etat = ci.written_state(plan, "20261030-000000")
        sonde = DEBIAN_UFW_PROBE.replace(
            "@@END", f"@@STATE {b64(json.dumps(etat))}\n@@END"
        )
        hote = Hote((0, sonde), (0, "@@REMOVED state\n@@DONE yes\n"))
        self.assertEqual(
            "fait", lt.desinstaller("vm", True, self.log, executer=hote)
        )
        self.assertIn("@@DONE", hote.scripts[1])
        hote = Hote((0, sonde), (1, "@@FAILED firewall\n@@DONE no\n"))
        self.assertEqual(
            "echec", lt.desinstaller("vm", True, self.log, executer=hote)
        )

    def test_uninstall_removes_rules_left_pending(self):
        """Une règle posée sans avoir été consignée part avec les autres."""
        facts = ci.parse_probe(DEBIAN_UFW_PROBE.replace("ufw", "none"))
        etat = ci.written_state(
            ci.plan_install(facts, self.ans, NOW), "20261030-000000"
        )
        sonde = DEBIAN_UFW_PROBE.replace(
            "@@END",
            f"@@STATE {b64(json.dumps(etat))}\n"
            "@@FIREWALL_PENDING ufw tcp 5349 coturn\n@@END",
        )
        hote = Hote((0, sonde), (0, "@@REMOVED state\n@@DONE yes\n"))
        self.assertEqual(
            "fait", lt.desinstaller("vm", True, self.log, executer=hote)
        )
        # Le script du pare-feu voyage en base64 dans celui de la
        # désinstallation.
        retrait = ci.firewall_script(
            "ufw", [ci.Rule("tcp", "5349", "coturn")], "delete"
        )
        self.assertTrue(b64(retrait) in hote.scripts[1], "règle oubliée")


class LeMemeCheminQueLeMenu(unittest.TestCase):
    """Chaque brique de `call_infra` que les étapes du menu appellent est
    appelée ici aussi : une brique ajoutée au menu et oubliée par le test
    long ferait certifier un chemin que le produit ne prend plus."""

    ETAPES_DU_MENU = (
        "_call_infra_probe",
        "_call_infra_install",
        "_call_infra_installed",
        "_call_infra_firewall",
        "_call_infra_save_state",
        "_call_infra_report",
        "_call_infra_uninstall",
        "_call_infra_uninstalled",
        "_call_infra_coturn_host",
        "_call_infra_module_choice",
        "_call_infra_ask_exempt",
        "_call_infra_add_odoo",
        "_call_infra_apply_odoo",
        "_call_infra_odoo_line",
        "_call_infra_remove_one",
        "_call_infra_check_odoo",
        "_call_infra_ask_install_method",
    )
    # Ce qui ne sert qu'à l'écran du menu : le texte d'un refus, les notes
    # affichées sous l'aperçu du pare-feu, l'explication du module absent,
    # les comptes que la question des ajouts du moteur ne propose pas.
    ECRAN_SEUL = {
        "SUPPORTED",
        "firewall_notes",
        "MODULE_ABSENT_WARNING",
        "accounts_kept",
    }

    def test_every_brick_of_the_menu_steps_is_called(self):
        menu = ast.parse(
            (RACINE / "script/todo/call_infra_menu.py").read_text(
                encoding="utf-8"
            )
        )
        etapes = {
            n.name: n
            for n in ast.walk(menu)
            if isinstance(n, ast.FunctionDef) and n.name in self.ETAPES_DU_MENU
        }
        self.assertEqual(set(self.ETAPES_DU_MENU), set(etapes))
        appelees = {
            n.attr
            for n in ast.walk(ast.parse(SRC))
            if isinstance(n, ast.Attribute)
            and isinstance(n.value, ast.Name)
            and n.value.id == "ci"
        }
        for nom, etape in etapes.items():
            briques = {
                a.attr
                for a in ast.walk(etape)
                if isinstance(a, ast.Attribute)
                and isinstance(a.value, ast.Name)
                and a.value.id == "ci"
            }
            for brique in sorted(briques - self.ECRAN_SEUL):
                with self.subTest(etape=nom, brique=brique):
                    self.assertIn(brique, appelees)

    # Les questions de la production : chacune de leurs briques bâtit les
    # `Answers` que le test long écrit à leur place.
    QUESTIONS_DE_PRODUCTION = (
        "_call_infra_ask_production",
        "_call_infra_ask_external_ip",
    )
    # Ce qui ne sert qu'à proposer de nouveau les valeurs d'un état de
    # production déjà écrit.
    RELANCE_SEULE = {"is_production"}

    def test_the_production_answers_come_from_the_menu_builders(self):
        menu = ast.parse(
            (RACINE / "script/todo/call_infra_menu.py").read_text(
                encoding="utf-8"
            )
        )
        questions = {
            n.name: n
            for n in ast.walk(menu)
            if isinstance(n, ast.FunctionDef)
            and n.name in self.QUESTIONS_DE_PRODUCTION
        }
        self.assertEqual(set(self.QUESTIONS_DE_PRODUCTION), set(questions))
        appelees = {
            n.attr
            for n in ast.walk(ast.parse(SRC))
            if isinstance(n, ast.Attribute)
            and isinstance(n.value, ast.Name)
            and n.value.id == "ci"
        }
        for nom, question in questions.items():
            briques = {
                a.attr
                for a in ast.walk(question)
                if isinstance(a, ast.Attribute)
                and isinstance(a.value, ast.Name)
                and a.value.id == "ci"
            }
            self.assertTrue(briques, nom)
            for brique in sorted(briques - self.RELANCE_SEULE):
                with self.subTest(question=nom, brique=brique):
                    self.assertIn(brique, appelees)
        # Le choix de nginx (installé ou existant) est celui du menu, par
        # sa propre fonction.
        self.assertIn("._call_infra_nginx_facts(", SRC)

    def _menu_answers(self, facts, resolve, typed_ip):
        """Les `Answers` que le menu bâtit pour cette sonde quand
        l'opérateur choisit la production avec un certificat fourni et
        accepte chaque valeur proposée (l'adresse tapée quand le nom de
        TURN ne se résout pas)."""
        from script.todo import call_infra_menu as cim
        from script.todo.todo import TODO

        t = todo_i18n.t
        todo = TODO.__new__(TODO)
        choices = iter(["2", "2"])  # mode production, certificat fourni

        def reply(prompt=""):
            if t("call_infra_ask_domain") in prompt:
                return lt.DOMAINE
            if t("call_infra_ask_typed_ip") in prompt:
                return typed_ip
            if prompt.startswith(t("Your choice (1/2)") + " "):
                return next(choices)
            return ""

        with (
            mock.patch("builtins.input", side_effect=reply),
            mock.patch.object(cim, "_resolve", resolve),
            mock.patch.object(
                TODO, "_call_infra_read_pair", return_value=("crt", "key")
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            return todo._call_infra_ask_answers(None, facts)

    def test_the_production_answers_are_the_menu_ones(self):
        # Mêmes réponses, et non seulement mêmes briques : un menu qui
        # changerait sa façon de régler external-ip ou nginx fait échouer
        # le test long au lieu de le laisser certifier l'ancienne.
        nginx = DEBIAN_UFW_PROBE.replace(
            "@@FIREWALL ufw", "@@NGINX active debian\n@@FIREWALL ufw"
        )
        for sonde in (DEBIAN_UFW_PROBE, nginx):
            facts = ci.parse_probe(sonde)
            for nom, resolve in (
                ("local", resolution(IP)),
                ("nat", resolution("203.0.113.7")),
                ("introuvable", resolution()),
            ):
                with self.subTest(nginx=sonde is nginx, nom=nom):
                    menu = self._menu_answers(facts, resolve, IP)
                    self.assertIsNotNone(menu)
                    self.assertEqual(
                        lt.reponses_prod(IP, "crt", "key", facts, resolve),
                        menu,
                    )


def resolution(*adresses):
    """Double de `socket.getaddrinfo` : `adresses`, ou le nom qui ne se
    résout pas quand il n'y en a aucune. Aucun test n'interroge le DNS."""

    def resoudre(nom, port):
        if not adresses:
            raise OSError("nom inconnu")
        return [(2, 1, 6, "", (a, 0)) for a in adresses]

    return resoudre


class LaProduction(unittest.TestCase):
    """Le scénario de production : les `Answers` du menu en production,
    les certificats inventés, et le crochet de déploiement lancé à la main
    dont le verdict se calcule sur les deux certificats."""

    @classmethod
    def setUpClass(cls):
        cls.dossier = tempfile.mkdtemp(prefix="longtest-call-infra-")
        noms = lt.noms_certificat(IP)
        tls = os.path.join(cls.dossier, "tls")
        chemins = lt.local_cert.issue(tls, noms)
        cls.premier = lt.paire(chemins)
        cls.second = lt.paire(lt.local_cert.issue(tls, noms))
        cls.ca = chemins["ca_crt"]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dossier, ignore_errors=True)

    def setUp(self):
        self.log = os.path.join(self.dossier, "x.log")
        self.journal = os.path.join(self.dossier, "j.log")

    def _faits(self, nginx=""):
        sonde = DEBIAN_UFW_PROBE
        if nginx:
            sonde = sonde.replace("@@END", f"@@NGINX {nginx}\n@@END")
        return ci.parse_probe(sonde)

    def test_answers_are_the_production_answers_of_the_menu(self):
        ans = lt.reponses_prod(IP, "CERT", "KEY")
        self.assertEqual("production", ans.mode)
        self.assertEqual(frozenset(ci.SERVICES), ans.services)
        self.assertEqual("supplied", ans.tls)
        self.assertEqual(("CERT", "KEY"), (ans.cert_pem, ans.key_pem))
        self.assertEqual("call.exemple.test", ans.public_name)
        self.assertEqual("ntfy.call.exemple.test", ans.ntfy_name)
        self.assertEqual("turn.call.exemple.test", ans.turn_name)
        self.assertEqual("install", ans.nginx)
        self.assertEqual(
            (ci.PROD_MIN_PORT, ci.PROD_MAX_PORT), (ans.min_port, ans.max_port)
        )
        self.assertEqual(ci.NTFY_HTTP_PORT, ans.ntfy_port)
        self.assertFalse(ans.ntfy_web or ans.turns_443)

    def test_nginx_on_the_host_is_the_existing_one(self):
        """Le menu dit « existant » à un nginx que la sonde voit, celui que
        la première installation a posé compris."""
        sans = lt.reponses_prod(IP, "C", "K", self._faits(), resolution())
        self.assertEqual("install", sans.nginx)
        avec = lt.reponses_prod(
            IP, "C", "K", self._faits("active debian"), resolution()
        )
        self.assertEqual("existing", avec.nginx)

    def test_public_address_as_the_menu_settles_it(self):
        faits = self._faits()
        # Un nom de TURN qui ne se résout pas : le menu fait taper
        # l'adresse, celle de la VM.
        ans = lt.reponses_prod(IP, "C", "K", faits, resolution())
        self.assertEqual(IP, ans.external_ip)
        ans = lt.reponses_prod(IP, "C", "K", faits, resolution(IP))
        self.assertIsNone(ans.external_ip)
        ans = lt.reponses_prod(IP, "C", "K", faits, resolution("203.0.113.7"))
        self.assertEqual("203.0.113.7", ans.external_ip)

    def test_the_certificate_covers_both_names_and_the_address(self):
        self.assertEqual(
            ["turn.call.exemple.test", "ntfy.call.exemple.test", IP],
            lt.noms_certificat(IP),
        )
        ans = lt.reponses_prod(IP, *self.premier)
        self.assertEqual(
            [*ci.certificate_names(ans), IP], lt.noms_certificat(IP)
        )
        # Le plan accepte le certificat : il porte chaque nom voulu.
        facts = self._faits()
        plan = ci.plan_install(
            facts,
            lt.reponses_prod(IP, *self.premier, facts, resolution()),
            NOW,
        )
        self.assertFalse(plan.nothing_to_do)

    def test_serials_are_read_from_the_certificates(self):
        un, deux = lt.serie_pem(self.premier[0]), lt.serie_pem(self.second[0])
        self.assertIsInstance(un, int)
        self.assertNotEqual(un, deux)
        for pem, serie in ((self.premier[0], un), (self.second[0], deux)):
            fini = subprocess.run(
                ["openssl", "x509", "-noout", "-serial"],
                input=pem,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(int(fini.stdout.split("=", 1)[1], 16), serie)
            der = lt.ssl.PEM_cert_to_DER_cert(pem)
            self.assertEqual(serie, lt.serie_der(der))
        self.assertIsNone(lt.serie_der(None))
        self.assertIsNone(lt.serie_der(b"\x30\x03\x02"))
        self.assertIsNone(lt.serie_pem("pas un certificat"))

    def _der(self, pem):
        return lt.ssl.PEM_cert_to_DER_cert(pem)

    LIGNEE = (
        "@@HOOK copied /etc/erplibre-call/tls/turn.crt"
        " /etc/erplibre-call/tls/turn.key\n"
        "@@HOOK signal coturn\n@@HOOK applied\n@@HOOK nginx-reloaded\n"
    )

    def _verdict(self, sortie=None, code=0, pids=("4242", "4242"), vus=None):
        requis, interdits = lt.attendus_crochet("crochet-lignee", "coturn")
        if vus is None:
            vus = {
                "turn-tls": (self.second[0], self._der(self.second[0])),
                "nginx": (self.premier[0], self._der(self.premier[0])),
            }
        return lt.verdict_crochet(
            code,
            self.LIGNEE if sortie is None else sortie,
            requis,
            interdits,
            pids,
            vus,
        )

    def test_the_hook_verdict_follows_the_two_certificates(self):
        ok, detail = self._verdict()
        self.assertTrue(ok, detail)
        self.assertEqual(
            f"{lt.serie_pem(self.second[0]):X}",
            detail["series"]["turn-tls"]["vue"],
        )
        # Le même certificat vu, l'autre attendu : le verdict change.
        ok, detail = self._verdict(
            vus={"turn-tls": (self.premier[0], self._der(self.second[0]))}
        )
        self.assertFalse(ok)
        series = detail["series"]["turn-tls"]
        self.assertNotEqual(series["attendue"], series["vue"])
        ok, _d = self._verdict(vus={"turn-tls": (self.second[0], None)})
        self.assertFalse(ok)

    def test_the_hook_verdict_wants_the_same_coturn_process(self):
        self.assertFalse(self._verdict(pids=("4242", "4300"))[0])
        self.assertFalse(self._verdict(pids=("0", "0"))[0])
        self.assertFalse(self._verdict(pids=("", ""))[0])
        self.assertFalse(self._verdict(code=1)[0])

    def test_the_hook_verdict_reads_its_markers(self):
        sans_signal = self.LIGNEE.replace("@@HOOK signal coturn\n", "")
        self.assertFalse(self._verdict(sans_signal)[0])
        perime = self.LIGNEE.replace("@@HOOK applied", "@@HOOK applied-stale")
        self.assertFalse(self._verdict(perime)[0])
        requis, interdits = lt.attendus_crochet("crochet-fourni", "coturn")
        fourni = "@@HOOK coturn-skip not-letsencrypt\n@@HOOK nginx-reloaded\n"
        vus = {"turn-tls": (self.premier[0], self._der(self.premier[0]))}
        ok, detail = lt.verdict_crochet(
            0, fourni, requis, interdits, ("7", "7"), vus
        )
        self.assertTrue(ok, detail)
        ok, detail = lt.verdict_crochet(
            0, fourni + "@@HOOK signal coturn\n", requis, interdits,
            ("7", "7"), vus,
        )  # fmt: skip
        self.assertFalse(ok)
        self.assertEqual(["signal"], detail["en_trop"])

    def test_the_hook_step_runs_the_product_hook_on_the_fake_lineage(self):
        sc = lt.Scenario("debian", self.log, self.journal, "prod")
        hote = Hote(
            (0, "@@PID 4242\n"),
            (0, "@@LINEAGE placed\n"),
            (0, self.LIGNEE),
            (0, "@@PID 4242\n"),
        )
        vus = {
            5349: self._der(self.second[0]),
            443: self._der(self.premier[0]),
        }
        ans = lt.reponses_prod(IP, *self.premier)
        with contextlib.redirect_stdout(io.StringIO()):
            lt.crochet(
                sc,
                "vm",
                IP,
                ans,
                "coturn",
                "crochet-lignee",
                self.second,
                self.second[0],
                executer=hote,
                vu=lambda adresse, port, nom: vus[port],
                attente=0,
            )
        self.assertTrue(sc.etapes["crochet-lignee"], sc.details)
        self.assertEqual(lt.script_lignee(*self.second), hote.scripts[1])
        self.assertEqual(ci.deploy_hook_text(), hote.scripts[2])
        self.assertEqual(
            {"RENEWED_LINEAGE": ci.LINEAGE_DIR}, hote.options[2]["env"]
        )
        self.assertEqual("bash", hote.options[2]["shell"])

    def test_the_hook_steps_put_the_host_back(self):
        """Fourni, puis la lignée, puis le retour à la première paire ; la
        remise passe même quand une passe échoue."""
        sc = lt.Scenario("debian", self.log, self.journal, "prod")
        pid = (0, "@@PID 4242\n")
        pose = (0, "@@LINEAGE placed\n")
        fourni = "@@HOOK coturn-skip not-letsencrypt\n@@HOOK nginx-reloaded\n"
        hote = Hote(
            pid, pose, (0, fourni), pid,
            (0, "@@STAGED letsencrypt\n"),
            pid, pose, (0, self.LIGNEE), pid,
            pid, pose, (0, self.LIGNEE), pid,
            (0, "@@RESTORED yes\n"),
        )  # fmt: skip
        # Un hôte qui fait ce que fait le crochet : sous l'état « Let's
        # Encrypt », coturn sert la dernière paire posée en lignée.
        sert = {"turn": self.premier[0], "lignee": None, "le": False}

        def vu(adresse, port, nom):
            return self._der(sert["turn"] if port == 5349 else self.premier[0])

        def executer(cible, script, log, delai, **kw):
            for pem in (self.premier, self.second):
                if script == lt.script_lignee(*pem):
                    sert["lignee"] = pem[0]
            if script == lt.script_etat_lignee():
                sert["le"] = True
            if script == ci.deploy_hook_text() and sert["le"]:
                sert["turn"] = sert["lignee"]
            return hote(cible, script, log, delai, **kw)

        ans = lt.reponses_prod(IP, *self.premier)
        with contextlib.redirect_stdout(io.StringIO()):
            lt.crochets(
                sc, "vm", IP, ans, "coturn", self.premier, self.second,
                executer=executer, vu=vu, attente=0,
            )  # fmt: skip
        for etape in (
            "crochet-fourni",
            "crochet-lignee",
            "crochet-retour",
            "crochet-remise",
        ):
            with self.subTest(etape=etape):
                self.assertTrue(sc.etapes[etape], sc.details.get(etape))
        self.assertEqual(lt.script_etat_lignee(), hote.scripts[4])
        self.assertEqual(lt.script_remise(), hote.scripts[-1])

        sc = lt.Scenario("debian", self.log, self.journal, "prod")
        hote = Hote(
            pid, pose, (0, fourni), pid,
            (1, ""),
            (0, "@@RESTORED yes\n"),
        )  # fmt: skip
        with contextlib.redirect_stdout(io.StringIO()):
            lt.crochets(
                sc, "vm", IP, ans, "coturn", self.premier, self.second,
                executer=hote, vu=vu, attente=0,
            )  # fmt: skip
        self.assertFalse(sc.etapes["crochet-lignee"])
        self.assertTrue(sc.etapes["crochet-remise"])
        self.assertEqual(lt.script_remise(), hote.scripts[-1])

    def test_the_host_scripts_parse(self):
        scripts = {
            "lignee": lt.script_lignee(*self.second),
            "pid": lt.script_pid("coturn"),
            "etat": lt.script_etat_lignee(),
            "remise": lt.script_remise(),
            "traces": lt.script_traces(),
        }
        for nom, script in scripts.items():
            with self.subTest(script=nom):
                fini = subprocess.run(
                    ["sh", "-n"],
                    input=script,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                self.assertEqual(0, fini.returncode, fini.stderr)
        # La clé voyage en base64, jamais en clair dans le corps.
        corps = self.second[1].splitlines()[1]
        self.assertNotIn(corps, scripts["lignee"])
        for fichier in ("fullchain.pem", "privkey.pem", "cert.pem"):
            self.assertIn(f"{ci.LINEAGE_DIR}/{fichier}", scripts["lignee"])
        self.assertIn(ci.STATE_PATH, scripts["etat"])
        self.assertIn("letsencrypt", scripts["etat"])

    def _bac(self, script, racine):
        """`script` lancé par sh, chaque chemin de /etc/ déplacé sous
        `racine` : la lignée, l'état et leur remise sans root."""
        fini = subprocess.run(
            ["sh", "-c", script.replace("/etc/", f"{racine}/etc/")],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(0, fini.returncode, fini.stderr)
        return fini.stdout

    def test_the_fake_lineage_and_the_state_are_put_back(self):
        racine = tempfile.mkdtemp(prefix="longtest-call-infra-bac-")
        self.addCleanup(shutil.rmtree, racine, ignore_errors=True)
        etat_chemin = racine + ci.STATE_PATH
        os.makedirs(os.path.dirname(etat_chemin))
        etat = {"services": {"coturn": {"settings": {"tls": "supplied"}}}}
        with open(etat_chemin, "w", encoding="utf-8") as fh:
            json.dump(etat, fh)
        os.chmod(etat_chemin, 0o600)
        with open(etat_chemin, encoding="utf-8") as fh:
            origine = fh.read()

        sortie = self._bac(lt.script_lignee(*self.second), racine)
        self.assertIn("@@LINEAGE placed", sortie)
        lignee = racine + ci.LINEAGE_DIR
        for nom, texte in (
            ("fullchain.pem", self.second[0]),
            ("cert.pem", self.second[0]),
            ("privkey.pem", self.second[1]),
        ):
            with open(os.path.join(lignee, nom), encoding="utf-8") as fh:
                self.assertEqual(texte, fh.read(), nom)
        mode = os.stat(os.path.join(lignee, "privkey.pem")).st_mode & 0o777
        self.assertEqual(0o600, mode)
        self.assertTrue(os.path.exists(racine + lt.TEMOIN_LE))

        self.assertIn(
            "@@STAGED letsencrypt", self._bac(lt.script_etat_lignee(), racine)
        )
        with open(etat_chemin, encoding="utf-8") as fh:
            marque = json.load(fh)
        self.assertEqual(
            "letsencrypt", marque["services"]["coturn"]["settings"]["tls"]
        )
        self.assertEqual(0o600, os.stat(etat_chemin).st_mode & 0o777)

        self.assertIn("@@RESTORED yes", self._bac(lt.script_remise(), racine))
        with open(etat_chemin, encoding="utf-8") as fh:
            self.assertEqual(origine, fh.read())
        self.assertFalse(os.path.exists(racine + "/etc/letsencrypt"))
        self.assertFalse(os.path.exists(racine + lt.ETAT_GARDE))

        # Un /etc/letsencrypt déjà là : seule la fausse lignée part.
        autre = racine + "/etc/letsencrypt/renewal/autre.conf"
        os.makedirs(os.path.dirname(autre))
        open(autre, "w", encoding="utf-8").close()
        self._bac(lt.script_lignee(*self.premier), racine)
        self.assertFalse(os.path.exists(racine + lt.TEMOIN_LE))
        self._bac(lt.script_remise(), racine)
        self.assertTrue(os.path.exists(autre))
        self.assertFalse(os.path.exists(lignee))
        with open(etat_chemin, encoding="utf-8") as fh:
            self.assertEqual(origine, fh.read())

    def test_nginx_installed_with_the_layout_of_each_system(self):
        site, lien, _inc = ci._nginx_paths("debian")
        etat = {
            "nginx": {
                "installed_by_tool": True,
                "layout": "debian",
                "site": site,
                "link": lien,
                "include": None,
            }
        }
        sortie = f"@@NGINX_FILE {site}\n@@NGINX_FILE {lien}\n@@END\n"
        self.assertTrue(lt.verdict_nginx(etat, sortie, "debian")[0])
        sans_lien = f"@@NGINX_FILE {site}\n@@END\n"
        self.assertFalse(lt.verdict_nginx(etat, sans_lien, "debian")[0])
        self.assertFalse(lt.verdict_nginx(etat, sortie, "arch")[0])
        pas_a_nous = {"nginx": dict(etat["nginx"], installed_by_tool=False)}
        self.assertFalse(lt.verdict_nginx(pas_a_nous, sortie, "debian")[0])
        self.assertFalse(lt.verdict_nginx({}, sortie, "debian")[0])

        site, _lien, inclus = ci._nginx_paths("arch-include")
        etat = {
            "nginx": {
                "installed_by_tool": True,
                "layout": "arch-include",
                "site": site,
                "link": None,
                "include": inclus,
            }
        }
        sortie = f"@@NGINX_FILE {site}\n@@INCLUDE present\n@@END\n"
        self.assertTrue(lt.verdict_nginx(etat, sortie, "arch")[0])
        sans_ligne = f"@@NGINX_FILE {site}\n@@END\n"
        self.assertFalse(lt.verdict_nginx(etat, sans_ligne, "arch")[0])

    def test_nothing_left_after_the_uninstall(self):
        propre = "@@UFW_RULES 0\n@@PKG nginx un\n@@END\n"
        ok, apres = lt.verdict_apres_prod(0, propre, "debian")
        self.assertTrue(ok, apres)
        self.assertTrue(lt.verdict_apres_prod(0, "@@END\n", "arch")[0])
        self.assertFalse(lt.verdict_apres_prod(1, propre, "debian")[0])
        self.assertFalse(
            lt.verdict_apres_prod(0, "@@UFW_RULES 0\n", "debian")[0]
        )
        for reste, cle in (
            (f"@@NGINX_FILE {ci.NGINX_INCLUDE_DIR}", "sans-site-nginx"),
            ("@@INCLUDE present", "sans-ligne-include"),
            ("@@HOOK present", "sans-crochet"),
            ("@@LINEAGE present", "sans-crochet"),
            ("@@CALL_DIR present", "sans-dossier-outil"),
            ("@@ACME present", "sans-dossier-acme"),
            ("@@PKG nginx ii", "nginx-purge"),
            ("@@PKG nginx-common rc", "nginx-purge"),
            ("@@NGINX_BIN present", "nginx-purge"),
            ("@@UNIT coturn", "sans-unite-coturn"),
            ("@@UFW_RULES 2", "sans-regle-ufw"),
        ):
            with self.subTest(reste=reste):
                sortie = propre.replace("@@END", f"{reste}\n@@END")
                if reste.startswith("@@UFW_RULES"):
                    sortie = f"{reste}\n@@END\n"
                ok, apres = lt.verdict_apres_prod(0, sortie, "debian")
                self.assertFalse(ok)
                self.assertFalse(apres[cle])

    SONDES = {
        "debian": DEBIAN_UFW_PROBE,
        "arch": DEBIAN_UFW_PROBE.replace("debian 13", "arch rolling").replace(
            "@@FIREWALL ufw", "@@FIREWALL none"
        ),
    }
    # Ce qu'un hôte complaisant répond à tout script hors de la sonde :
    # chaque porte du scénario s'ouvre, les verdicts restent à lire.
    TOUT_VA = (
        "@@UFW active\n@@SAVED yes\n@@PID 4242\n@@LINEAGE placed\n"
        "@@STAGED letsencrypt\n@@RESTORED yes\n@@DONE yes\n@@END\n"
    )

    def _course_prod(self, distro):
        """`scenario_prod` mené de bout en bout sur un faux hôte : ssh,
        réseau et DNS remplacés, openssl réel pour les certificats."""
        reel = subprocess.run
        sonde = self.SONDES[distro]

        def run(argv, *a, **kw):
            if argv and argv[0] == "openssl":
                return reel(argv, *a, **kw)
            sortie = sonde if kw.get("input") == ci.probe_script() else None
            return subprocess.CompletedProcess(
                argv, 0, stdout=sortie or self.TOUT_VA, stderr=""
            )

        def verifier(cible, adresse, cafile, log, executer=None):
            noms = lt.CONTROLES["prod"][distro]
            return [ci.CheckLine(n, True, "x") for n in noms], {}

        sc = lt.Scenario(distro, self.log, self.journal, "prod")
        dossier = tempfile.mkdtemp(prefix="longtest-call-infra-prod-")
        self.addCleanup(shutil.rmtree, dossier, ignore_errors=True)
        with (
            mock.patch.object(lt.subprocess, "run", side_effect=run),
            mock.patch.object(
                lt.socket, "getaddrinfo", side_effect=OSError("inconnu")
            ),
            mock.patch.object(lt, "certificat_vu", return_value=None),
            mock.patch.object(lt, "DELAI_SERIE", 0),
            mock.patch.object(lt, "verifier", side_effect=verifier),
            mock.patch.object(lt, "ports_fermes", return_value={}),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            lt.scenario_prod(sc, "vm", IP, dossier)
        return sc

    def test_the_production_run_notes_every_planned_step(self):
        """Le plan à blanc annonce les étapes que la course note, dans
        l'ordre : aucune n'est sautée, aucune n'est inventée."""
        for distro in ("debian", "arch"):
            with self.subTest(distro=distro):
                sc = self._course_prod(distro)
                self.assertEqual(
                    list(lt.ETAPES["prod"][distro][2:]), list(sc.etapes)
                )
                self.assertTrue(sc.etapes["installation"], sc.details)
                self.assertTrue(sc.etapes["crochet-remise"])

    def test_the_menu_path_takes_answers_from_the_probe(self):
        """Les réponses de production dépendent de la sonde (nginx, adresse
        publique) : l'installation les bâtit après elle, comme le menu."""
        vues = []

        def reponses(facts):
            vues.append(facts)
            return lt.reponses(IP)

        hote = Hote(
            (0, DEBIAN_UFW_PROBE.replace("ufw", "none")),
            (0, "@@ACTIVE coturn active\n@@ACTIVE ntfy active\n@@SAVED yes"),
            (0, "@@SAVED yes\n"),
        )
        res = lt.installer("vm", reponses, self.log, executer=hote)
        self.assertTrue(res["ok"], res)
        self.assertEqual(1, len(vues))
        self.assertEqual("debian", vues[0].family)
        self.assertEqual(lt.reponses(IP), res["answers"])


class LeTransport(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.mkdtemp(prefix="longtest-call-infra-")
        self.addCleanup(shutil.rmtree, self.dossier, ignore_errors=True)
        self.log = os.path.join(self.dossier, "x.log")

    def test_the_output_is_masked_in_the_log_not_in_the_result(self):
        secret = "@@ADMIN_PASSWORD Mot-de-passe-invente-42\n@@ACTIVE ntfy x\n"
        fini = subprocess.CompletedProcess([], 0, stdout=secret)
        with mock.patch.object(lt.subprocess, "run", return_value=fini) as r:
            code, sortie = lt.distant("vm", "echo", self.log, 30)
        self.assertEqual(0, code)
        self.assertEqual(secret, sortie)
        with open(self.log, encoding="utf-8") as fh:
            journal = fh.read()
        self.assertNotIn("Mot-de-passe-invente-42", journal)
        # Le script part par l'entrée standard, jamais par l'argv.
        self.assertEqual("echo", r.call_args.kwargs["input"])
        self.assertNotIn("echo", r.call_args.args[0])
        self.assertIn(30, [r.call_args.kwargs.get("timeout")])

    def test_a_timeout_is_a_result(self):
        with mock.patch.object(
            lt.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired("ssh", 1),
        ):
            code, sortie = lt.distant("vm", "echo", self.log, 1)
        self.assertIsNone(code)
        self.assertEqual("", sortie)
        with open(self.log, encoding="utf-8") as fh:
            self.assertIn("interrompu", fh.read())


# --- Le scénario des serveurs Odoo -----------------------------------------

URL_ODOO = "http://127.0.0.1:40001"
EXEMPT = "198.51.100.20"


def ligne_ice(url, ok, erreur=None):
    """Une ligne de `check_through_odoo` pour `url` : verte, ou en échec
    sous `erreur`."""
    if ok:
        return ci.CheckLine(
            f"odoo-ice-{url}",
            True,
            "call_infra_check_ice_relayed",
            {"url": url, "relayed": "192.0.2.10:50000"},
        )
    return ci.CheckLine(
        f"odoo-ice-{url}",
        False,
        "call_infra_check_ice_error",
        {"url": url, "error": erreur},
    )


UDP = f"turn:{IP}:3478?transport=udp"
TCP = f"turn:{IP}:3478?transport=tcp"
TLS = f"turns:{IP}:5349?transport=tcp"


class LesBriquesOdoo(unittest.TestCase):
    def test_database_names(self):
        bases = lt.noms_bases("4242_20261101120000")
        self.assertEqual(
            {
                "a": "call_infra_odoo_4242_20261101120000_a",
                "b": "call_infra_odoo_4242_20261101120000_b",
                "c": "call_infra_odoo_4242_20261101120000_c",
            },
            bases,
        )
        for mauvais in ("", "x y", "MAJ_1", "1;drop"):
            with self.subTest(mauvais=mauvais):
                with self.assertRaises(ValueError):
                    lt.noms_bases(mauvais)

    def test_url_kinds(self):
        self.assertEqual("turn-udp", lt.sorte_url(UDP))
        self.assertEqual("turn-udp", lt.sorte_url(f"turn:{IP}:3478"))
        self.assertEqual("turn-tcp", lt.sorte_url(TCP))
        self.assertEqual("turns", lt.sorte_url(TLS))
        self.assertEqual("stun", lt.sorte_url(f"stun:{IP}:3478"))

    def test_ice_verdict_accepts_exactly_the_expected_kinds(self):
        lignes = [ligne_ice(UDP, True), ligne_ice(TCP, True)]
        ok, detail = lt.verdict_ice(lignes, ("turn-udp", "turn-tcp"))
        self.assertTrue(ok, detail)
        # Un turns: de trop, ou un manquant, n'est pas ce qu'on attendait.
        ok, detail = lt.verdict_ice(
            lignes + [ligne_ice(TLS, True)], ("turn-udp", "turn-tcp")
        )
        self.assertFalse(ok)
        self.assertEqual(["turns"], detail["en_trop"])
        ok, detail = lt.verdict_ice(lignes, ("turn-udp", "turn-tcp", "turns"))
        self.assertFalse(ok)
        self.assertEqual(["turns"], detail["manque"])
        rouge = [ligne_ice(UDP, True), ligne_ice(TCP, False, "timeout")]
        ok, detail = lt.verdict_ice(rouge, ("turn-udp", "turn-tcp"))
        self.assertFalse(ok)
        self.assertEqual([f"odoo-ice-{TCP}"], detail["en_defaut"])
        self.assertFalse(lt.verdict_ice([], ())[0])

    def test_ice_verdict_of_a_refusal_wants_a_401(self):
        """Des identifiants révoqués : coturn les refuse (401). Une panne
        (délai, connexion) ne prouve pas la révocation."""
        refus = [
            ligne_ice(UDP, False, "401 Unauthorized"),
            ligne_ice(TCP, False, "401 Unauthorized"),
        ]
        attendus = ("turn-udp", "turn-tcp")
        self.assertTrue(lt.verdict_ice(refus, attendus, refuse=True)[0])
        panne = [refus[0], ligne_ice(TCP, False, "timeout")]
        self.assertFalse(lt.verdict_ice(panne, attendus, refuse=True)[0])
        vert = [refus[0], ligne_ice(TCP, True)]
        self.assertFalse(lt.verdict_ice(vert, attendus, refuse=True)[0])
        aucun = [ci.CheckLine("odoo-ice", False, "call_infra_check_ice_none")]
        self.assertFalse(lt.verdict_ice(aucun, attendus, refuse=True)[0])

    def test_the_exempt_address_is_the_menu_one(self):
        """Le menu propose l'adresse du nom de l'URL d'Odoo, la boucle
        locale d'un Odoo du harnais tombe, l'adresse tapée l'emporte."""
        self.assertEqual(EXEMPT, lt.exempt_du_menu(URL_ODOO, EXEMPT))
        self.assertIsNone(lt.exempt_du_menu(URL_ODOO, ""))
        with mock.patch.object(
            lt.cim, "_resolve", return_value=[(2, 1, 6, "", (IP, 0))]
        ):
            self.assertEqual(
                IP, lt.exempt_du_menu("https://odoo.exemple.test", "")
            )

    def test_the_address_the_vm_sees(self):
        self.assertEqual("127.0.0.1", lt.adresse_vers("127.0.0.1"))
        self.assertEqual("", lt.adresse_vers("pas une adresse"))

    def test_coturn_mode_from_its_config(self):
        def faits(texte):
            return mock.Mock(coturn={"config_text": texte})

        self.assertEqual("secret", lt.mode_conf(faits("a\nuse-auth-secret\n")))
        self.assertEqual("fixed", lt.mode_conf(faits("lt-cred-mech\nb\n")))
        self.assertIsNone(lt.mode_conf(faits("lt-cred-mech\nuse-auth-secret")))
        self.assertIsNone(lt.mode_conf(mock.Mock(coturn=None)))
        self.assertIsNone(lt.mode_conf(None))

    def test_exempt_hosts_from_the_probe(self):
        yml = f"{lt.nm.EXEMPT_HOSTS_KEY}: {EXEMPT}, 203.0.113.7\n"
        self.assertEqual(
            [EXEMPT, "203.0.113.7"],
            lt.exempts(mock.Mock(ntfy={"config_text": yml})),
        )
        self.assertEqual([], lt.exempts(mock.Mock(ntfy=None)))
        self.assertEqual([], lt.exempts(None))


class FauxLien:
    """`ol.WebApi` d'une base inventée : rend ses faits, note ses appels,
    lève `erreur` à `facts()` quand on la lui donne."""

    def __init__(
        self, module="uninstalled", rows=(), params=None, erreur=None
    ):
        self.odoo = ol.OdooFacts(
            "18.0", 18, module, dict(params or {}), tuple(rows), "127.0.0.1"
        )
        self.erreur = erreur
        self.appels = []

    def facts(self):
        if self.erreur:
            raise self.erreur
        return self.odoo

    def install_module(self):
        self.appels.append(("install_module",))

    def set_params(self, values):
        self.appels.append(("set_params", dict(values)))

    def replace_rows(self, owned, rows):
        self.appels.append(("replace_rows", owned, [dict(r) for r in rows]))


class LeCheminOdoo(unittest.TestCase):
    """« Ajouter » et « Retirer un serveur Odoo » par les briques du menu :
    sonde, faits de la base, plan, puis le script de l'hôte et Odoo."""

    BASE = "call_infra_odoo_1_19990101000000_a"

    def setUp(self):
        self.dossier = tempfile.mkdtemp(prefix="longtest-call-infra-")
        self.addCleanup(shutil.rmtree, self.dossier, ignore_errors=True)
        self.log = os.path.join(self.dossier, "x.log")
        self.ans = lt.reponses(IP)
        facts = ci.parse_probe(DEBIAN_UFW_PROBE.replace("ufw", "none"))
        self.plan = ci.plan_install(facts, self.ans, NOW)
        self.etat = ci.written_state(self.plan, "20261030-000000")
        self.cle = ol.odoo_key(URL_ODOO, self.BASE)

    def sonde(self, etat):
        texte = (
            "@@OS debian 13 \n@@SYSTEMD yes\n@@HOSTNAME vm\n"
            f"@@ADDR {IP}\n"
            "@@COTURN coturn active /etc/turnserver.conf\n"
            "@@NTFY ntfy active /etc/ntfy/server.yml\n"
            f"@@FILE /etc/turnserver.conf {b64(ci.coturn_config(self.ans))}\n"
            f"@@FILE /etc/ntfy/server.yml {b64(self.plan.configs['ntfy'])}\n"
            "@@FIREWALL none\n"
        )
        if etat is not None:
            texte += f"@@STATE {b64(json.dumps(etat))}\n"
        return texte + "@@END\n"

    def ajouter(self, hote, lien, module=False, exempt=EXEMPT):
        return lt.ajouter_odoo(
            "vm",
            lien,
            URL_ODOO,
            self.BASE,
            module,
            exempt,
            self.log,
            executer=hote,
            maintenant=NOW,
        )

    def test_a_module_less_odoo_gets_three_rows_of_a_fixed_account(self):
        hote = Hote(
            (0, self.sonde(self.etat)),
            (0, "@@ODOO_ADDED yes\n"),
            (0, "@@SAVED yes\n"),
        )
        lien = FauxLien()
        res = self.ajouter(hote, lien)
        self.assertTrue(res["ok"], res)
        self.assertEqual("user", res["plan"].kind)
        self.assertEqual(3, len(hote.scripts))
        self.assertEqual(ci.probe_script(), hote.scripts[0])
        self.assertIn("@@ODOO_ADDED", hote.scripts[1])
        self.assertEqual(
            ci.state_write_script(res["etat"], pending_taken=False),
            hote.scripts[2],
        )
        fiche = res["etat"]["odoos"][self.cle]
        self.assertEqual("user", fiche["credential"]["kind"])
        self.assertEqual(EXEMPT, fiche["exempt"])
        self.assertNotIn(("install_module",), lien.appels)
        (_nom, proprietaire, lignes) = lien.appels[-1]
        self.assertEqual(ol.owned_username(URL_ODOO, self.BASE), proprietaire)
        self.assertEqual(3, len(lignes))
        # Le mot de passe du compte fixe va dans Odoo, jamais au journal.
        mot = next(r["credential"] for r in lignes if "credential" in r)
        journal = ""
        if os.path.exists(self.log):
            with open(self.log, encoding="utf-8") as fh:
                journal = fh.read()
        self.assertNotIn(mot, journal)
        self.assertNotIn(mot, "".join(hote.scripts[2:]))

    def test_the_module_is_installed_by_the_tool_when_asked(self):
        hote = Hote(
            (0, self.sonde(self.etat)),
            (0, "@@ODOO_ADDED yes\n"),
            (0, "@@SAVED yes\n"),
        )
        lien = FauxLien()
        res = self.ajouter(hote, lien, module=True)
        self.assertTrue(res["ok"], res)
        self.assertEqual("secret", res["plan"].kind)
        self.assertEqual(("install_module",), lien.appels[0])
        self.assertEqual("secret", res["etat"]["turn_mode"])

    def test_the_other_mode_is_refused_before_anything_changes(self):
        autre = ci.odoo_added_state(
            self.etat,
            ol.odoo_key("http://127.0.0.1:40002", "autre"),
            "secret",
            "S" * 43,
            None,
            None,
            NOW,
            check_secret="C" * 43,
        )
        hote = Hote((0, self.sonde(autre)))
        lien = FauxLien()
        res = self.ajouter(hote, lien)
        self.assertFalse(res["ok"])
        self.assertEqual("plan", res["etape"])
        self.assertEqual("call_infra_turn_mode_mismatch", res["refus"])
        self.assertEqual(1, len(hote.scripts))
        self.assertEqual([], lien.appels)

    def test_no_coturn_and_odoo_errors_are_refusals(self):
        res = self.ajouter(Hote((0, self.sonde(None))), FauxLien())
        self.assertEqual(
            ("coturn", "call_infra_odoo_no_coturn"),
            (res["etape"], res["refus"]),
        )
        erreur = ol.OdooError("call_infra_odoo_login", database=self.BASE)
        res = self.ajouter(
            Hote((0, self.sonde(self.etat))), FauxLien(erreur=erreur)
        )
        self.assertEqual(
            ("odoo", "call_infra_odoo_login"), (res["etape"], res["refus"])
        )
        res = self.ajouter(Hote((None, "")), FauxLien())
        self.assertEqual("sonde", res["etape"])

    def test_a_failed_odoo_write_is_rolled_back_and_says_its_cause(self):
        hote = Hote(
            (0, self.sonde(self.etat)),
            (0, "@@ODOO_ADDED yes\n"),
            (0, "@@ODOO_ROLLBACK yes\n"),
        )
        lien = FauxLien()
        erreur = ol.OdooError("call_infra_odoo_rpc_error", message="x")
        lien.replace_rows = mock.Mock(side_effect=erreur)
        res = self.ajouter(hote, lien)
        self.assertFalse(res["ok"])
        self.assertEqual(
            "call_infra_odoo_write_failed/call_infra_odoo_rpc_error",
            res["refus"],
        )
        self.assertIn("@@ODOO_ROLLBACK", hote.scripts[2])

    def test_remove_cleans_odoo_then_revokes_on_the_host(self):
        etat = ci.odoo_added_state(
            self.etat,
            self.cle,
            "user",
            "P" * 43,
            ol.owned_username(URL_ODOO, self.BASE),
            None,
            NOW,
        )
        hote = Hote((0, self.sonde(etat)), (0, "@@ODOO_REMOVED yes\n"))
        lien = FauxLien()
        res = lt.retirer_odoo(
            "vm", lien, self.cle, self.log, executer=hote, maintenant=NOW
        )
        self.assertTrue(res["ok"], res)
        self.assertNotIn(self.cle, res["etat"]["odoos"])
        self.assertEqual("set_params", lien.appels[0][0])
        self.assertEqual(
            ("replace_rows", ol.owned_username(URL_ODOO, self.BASE), []),
            lien.appels[1],
        )
        self.assertIn("@@ODOO_REMOVED", hote.scripts[1])
        # Un Odoo que l'état ne consigne pas : refus, rien sur l'hôte.
        hote = Hote((0, self.sonde(self.etat)))
        res = lt.retirer_odoo(
            "vm", FauxLien(), self.cle, self.log, executer=hote
        )
        self.assertFalse(res["ok"])
        self.assertEqual(1, len(hote.scripts))

    def test_through_odoo_as_a_user_and_as_a_guest(self):
        ice = [{"urls": UDP, "username": "1:odoo-u6", "credential": "x"}]
        api = mock.Mock()
        api.join_call_ice.return_value = ice
        api.join_call_ice_guest.return_value = ice
        harnais = mock.Mock()
        harnais.lien.return_value = api
        allocation = mock.Mock(return_value=[ligne_ice(UDP, True)])
        with mock.patch.object(lt.ci, "check_through_odoo", allocation):
            rendu, lignes = lt.par_odoo(harnais, "b", self.etat, "/ca.crt")
            self.assertEqual(ice, rendu)
            self.assertEqual([ligne_ice(UDP, True)], lignes)
            harnais.lien.assert_called_with("b", *lt.UTILISATEUR_ODOO)
            api.join_call_ice.assert_called_with(*lt.UTILISATEUR_ODOO)
            lien = f"{URL_ODOO}/chat/1/jeton"
            lt.par_odoo(harnais, "b", self.etat, "/ca.crt", invitation=lien)
            api.join_call_ice_guest.assert_called_with(lien)
        appel = allocation.call_args
        self.assertEqual((ice, IP, None, "/ca.crt"), appel.args)
        self.assertEqual(ci.turn_host(self.ans), appel.kwargs["turn_host"])
        api.join_call_ice.side_effect = ol.OdooError("call_infra_odoo_x")
        rendu, lignes = lt.par_odoo(harnais, "b", self.etat, None)
        self.assertEqual([], rendu)
        self.assertEqual([False], [li.ok for li in lignes])

    def test_the_invitation_link_of_a_public_channel(self):
        lien = mock.Mock(url=URL_ODOO)
        lien._execute.side_effect = [7, [{"id": 7, "uuid": "abc-123"}]]
        self.assertEqual(
            f"{URL_ODOO}/chat/7/abc-123", lt.lien_invitation(lien)
        )
        cree = lien._execute.call_args_list[0].args
        self.assertEqual(("discuss.channel", "create"), cree[:2])
        self.assertEqual("channel", cree[2][0]["channel_type"])
        self.assertIs(False, cree[2][0]["group_public_id"])


class LeHarnais(unittest.TestCase):
    """Les trois bases Odoo du scénario, copiées du gabarit de
    mobile_sync_odoo : chacune entre au rapport avant d'exister."""

    def setUp(self):
        self.dossier = tempfile.mkdtemp(prefix="longtest-call-infra-")
        self.addCleanup(shutil.rmtree, self.dossier, ignore_errors=True)
        self.ordre = []

    def _course(self):
        course = mock.Mock()
        course.noter_base.side_effect = lambda b: self.ordre.append(
            ("note", b)
        )
        return course

    def test_each_database_is_reported_before_it_exists(self):
        version = mock.Mock()
        course = self._course()
        serveurs = iter(
            mock.Mock(url=f"http://127.0.0.1:4000{i}") for i in range(3)
        )
        with (
            mock.patch.object(
                lt.mso, "versions_installees", return_value={18: version}
            ) as versions,
            mock.patch.object(lt.mso, "construire_gabarit") as gabarit,
            mock.patch.object(
                lt.mso,
                "copier_gabarit",
                side_effect=lambda v, b: self.ordre.append(("copie", b)),
            ),
            mock.patch.object(
                lt.mso,
                "demarrer_serveur",
                side_effect=lambda v, b, r: next(serveurs),
            ) as demarrer,
        ):
            harnais = lt.Harnais(self.dossier, "1_19990101000000", course)
            ok, detail = harnais.preparer()
        self.assertTrue(ok, detail)
        versions.assert_called_once_with(demandees=(18,))
        gabarit.assert_called_once()
        bases = list(lt.noms_bases("1_19990101000000").values())
        self.assertEqual(
            [x for b in bases for x in (("note", b), ("copie", b))],
            self.ordre,
        )
        # Un dossier par serveur : chacun y écrit sa configuration.
        dossiers = {str(c.args[2]) for c in demarrer.call_args_list}
        self.assertEqual(3, len(dossiers))
        self.assertEqual("http://127.0.0.1:40001", harnais.url("b"))
        lien = harnais.lien("c")
        self.assertIsInstance(lien, ol.WebApi)
        self.assertEqual(bases[2], lien.database)
        self.assertEqual(lt.ADMIN_ODOO[0], lien.login)

    def test_a_missing_prerequisite_is_a_failed_step(self):
        course = self._course()
        with mock.patch.object(
            lt.mso,
            "versions_installees",
            side_effect=lt.mso.PrerequisManquant("Odoo 18 absent"),
        ):
            harnais = lt.Harnais(self.dossier, "1_19990101000000", course)
            ok, detail = harnais.preparer()
        self.assertFalse(ok)
        self.assertIn("Odoo 18 absent", detail)
        self.assertEqual([], self.ordre)

    def test_undoing_stops_the_servers_and_drops_the_databases(self):
        course = self._course()
        harnais = lt.Harnais(self.dossier, "1_19990101000000", course)
        harnais.inscrites = ["call_infra_odoo_1_19990101000000_a"]
        serveur = mock.Mock()
        harnais.serveurs = {"a": serveur}
        with (
            mock.patch.object(lt.mso, "arreter_serveur") as arreter,
            mock.patch.object(lt.mso, "supprimer_base") as supprimer,
            mock.patch.object(lt, "bases_restantes", return_value=[]),
        ):
            self.assertEqual([], harnais.defaire())
        arreter.assert_called_once_with(serveur)
        supprimer.assert_called_once_with("call_infra_odoo_1_19990101000000_a")
        course.oublier_odoo.assert_called_once_with()
        # Une base qui reste garde sa place au rapport.
        course = self._course()
        harnais = lt.Harnais(self.dossier, "1_19990101000000", course)
        harnais.inscrites = ["call_infra_odoo_1_19990101000000_a"]
        reste = ["call_infra_odoo_1_19990101000000_a"]
        with (
            mock.patch.object(lt.mso, "supprimer_base"),
            mock.patch.object(lt, "bases_restantes", return_value=reste),
        ):
            self.assertEqual(reste, harnais.defaire())
        course.oublier_odoo.assert_not_called()

    def test_remaining_databases_are_read_from_postgresql(self):
        noms = ["call_infra_odoo_1_2_a", "call_infra_odoo_1_2_b"]
        with (
            mock.patch.object(
                lt.mso, "psql", return_value="call_infra_odoo_1_2_a\nautre"
            ),
            mock.patch.object(lt.mso, "CACHE", Path(self.dossier)),
        ):
            self.assertEqual(
                ["call_infra_odoo_1_2_a"], lt.bases_restantes(noms)
            )
            filestore = (
                Path(self.dossier) / "data/filestore/call_infra_odoo_1_2_b"
            )
            filestore.mkdir(parents=True)
            self.assertEqual(noms, lt.bases_restantes(noms))
        with mock.patch.object(
            lt.mso, "psql", side_effect=RuntimeError("psql : refusé")
        ):
            self.assertEqual(noms, lt.bases_restantes(noms))

    def test_the_run_reports_its_databases(self):
        journal = os.path.join(self.dossier, "long-call-infra-1.log")
        course = lt.Course(False, journal)
        self.assertRegex(course.identifiant, r"^\d+_\d{14}$")
        course.noter_base("call_infra_odoo_1_2_a")
        with open(course.chemin, encoding="utf-8") as fh:
            self.assertEqual(
                ["call_infra_odoo_1_2_a"], json.load(fh)["odoo"]["bases"]
            )
        course.oublier_odoo()
        with open(course.chemin, encoding="utf-8") as fh:
            self.assertEqual([], json.load(fh)["odoo"]["bases"])


class LeDefaireOdoo(unittest.TestCase):
    """`--detruire` arrête les serveurs Odoo et supprime les bases que les
    rapports de ce test nomment encore, puis défait les VM."""

    BASES = [
        "call_infra_odoo_123_19990101000000_a",
        "call_infra_odoo_123_19990101000000_b",
    ]

    def setUp(self):
        self.maison = tempfile.mkdtemp(prefix="longtest-call-infra-")
        self.addCleanup(shutil.rmtree, self.maison, ignore_errors=True)
        self.dossier = os.path.join(self.maison, ".erplibre/longtest")
        os.makedirs(self.dossier)
        self.journal = os.path.join(self.dossier, "x.log")

    def _rapport(self, nom="long-call-infra-19990101-000000.json", **champs):
        rapport = {
            "outil": "call_infra",
            "dry_run": False,
            "pid": 1,
            "etages": [],
            # Un nom d'une autre forme n'est jamais supprimé.
            "odoo": {
                "bases": [
                    self.BASES[0],
                    "mobile_sync_run_1_2_18",
                    self.BASES[1],
                ]
            },
        }
        rapport.update(champs)
        chemin = os.path.join(self.dossier, nom)
        with open(chemin, "w", encoding="utf-8") as fh:
            json.dump(rapport, fh)
        return chemin

    def _defaire(self, dry_run=False, vivante=False):
        with (
            mock.patch.object(lt, "descente_vivante", return_value=vivante),
            mock.patch.object(lt, "serveurs_de", return_value=[4242]) as de,
            mock.patch.object(lt, "arreter_serveurs") as arreter,
            mock.patch.object(lt.mso, "supprimer_base") as supprimer,
            mock.patch.object(lt, "bases_restantes", return_value=[]),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            n = lt.defaire_odoo(self.journal, dry_run, dossier=self.dossier)
        return n, de, arreter, supprimer

    def test_the_databases_of_the_report_are_dropped(self):
        chemin = self._rapport()
        n, de, arreter, supprimer = self._defaire()
        self.assertEqual(2, n)
        de.assert_called_once_with(chemin[: -len(".json")])
        arreter.assert_called_once_with([4242], chemin[: -len(".json")])
        self.assertEqual(
            self.BASES, [c.args[0] for c in supprimer.call_args_list]
        )
        with open(chemin, encoding="utf-8") as fh:
            self.assertEqual([], json.load(fh)["odoo"]["bases"])

    def test_a_dry_run_drops_nothing(self):
        chemin = self._rapport()
        n, _de, arreter, supprimer = self._defaire(dry_run=True)
        self.assertEqual(2, n)
        arreter.assert_not_called()
        supprimer.assert_not_called()
        with open(chemin, encoding="utf-8") as fh:
            self.assertEqual(3, len(json.load(fh)["odoo"]["bases"]))

    def test_other_reports_are_left_alone(self):
        self._rapport("long-call-infra-a.json", outil="install_nixos")
        self._rapport("long-call-infra-b-dryrun.json", dry_run=True)
        self.assertEqual(0, self._defaire()[0])
        self.assertEqual(0, self._defaire(vivante=True)[0])

    def test_destroy_drops_the_databases_then_the_vms(self):
        def detruire(famille, journal, dry_run, avant):
            avant(dry_run)
            ordre.append(("vm", dry_run))
            return 0

        self._rapport(etages=[LeDefaire.ETAGE])
        for options, a_blanc in (((), False), (("--dry-run",), True)):
            ordre = []
            with (
                self.subTest(options=options),
                mock.patch.object(
                    lt,
                    "defaire_odoo",
                    side_effect=lambda j, d: ordre.append(("odoo", d)),
                ),
                mock.patch.object(lt, "detruire", side_effect=detruire),
            ):
                code, _sortie = lancer(self.maison, "--detruire", *options)
            self.assertEqual(0, code)
            self.assertEqual([("odoo", a_blanc), ("vm", a_blanc)], ordre)

    def _detruire_pour_de_vrai(self, *options, reponse="OUI", descentes=()):
        """`--detruire` par le défaire partagé, VM et processus bouchés ;
        rend (code, arreter_serveurs, supprimer_base, detruire_etage1) et
        garde la sortie dans `self.sortie`."""
        with (
            mock.patch.object(lt, "descente_vivante", return_value=False),
            mock.patch.object(lt, "serveurs_de", return_value=[4242]),
            mock.patch.object(lt, "arreter_serveurs") as arreter,
            mock.patch.object(lt.mso, "supprimer_base") as supprimer,
            mock.patch.object(lt, "bases_restantes", return_value=[]),
            mock.patch.object(
                descente, "descente_vivante", return_value=False
            ),
            mock.patch.object(
                descente, "detruire_etage1", return_value=True
            ) as etage1,
            mock.patch.object(descente, "retirer_alias"),
            mock.patch("builtins.input", return_value=reponse),
        ):
            code, self.sortie = lancer(
                self.maison, "--detruire", *options, descentes=descentes
            )
        return code, arreter, supprimer, etage1

    def test_without_a_vm_report_a_dry_run_lists_the_databases(self):
        chemin = self._rapport()
        code, arreter, supprimer, etage1 = self._detruire_pour_de_vrai(
            "--dry-run"
        )
        self.assertEqual(0, code)
        self.assertIn(self.BASES[0], self.sortie)
        self.assertIn("aucune base supprimée", self.sortie)
        self.assertNotIn("rien à défaire", self.sortie)
        arreter.assert_not_called()
        supprimer.assert_not_called()
        etage1.assert_not_called()
        with open(chemin, encoding="utf-8") as fh:
            self.assertEqual(3, len(json.load(fh)["odoo"]["bases"]))

    def test_without_a_vm_report_a_running_descent_drops_nothing(self):
        chemin = self._rapport()
        code, arreter, supprimer, etage1 = self._detruire_pour_de_vrai(
            descentes=[999999]
        )
        self.assertEqual(1, code)
        self.assertIn("une descente tourne", self.sortie)
        self.assertNotIn(self.BASES[0], self.sortie)
        arreter.assert_not_called()
        supprimer.assert_not_called()
        with open(chemin, encoding="utf-8") as fh:
            self.assertEqual(3, len(json.load(fh)["odoo"]["bases"]))

    def test_without_a_vm_report_a_refusal_drops_nothing(self):
        self._rapport()
        code, arreter, supprimer, etage1 = self._detruire_pour_de_vrai(
            reponse="oui"
        )
        self.assertEqual(1, code)
        self.assertIn(self.BASES[0], self.sortie)
        arreter.assert_not_called()
        supprimer.assert_not_called()

    def test_without_a_vm_report_a_confirmation_drops_the_databases(self):
        chemin = self._rapport()
        code, arreter, supprimer, etage1 = self._detruire_pour_de_vrai()
        self.assertEqual(0, code)
        arreter.assert_called_once_with([4242], chemin[: -len(".json")])
        self.assertEqual(
            self.BASES, [c.args[0] for c in supprimer.call_args_list]
        )
        etage1.assert_not_called()
        with open(chemin, encoding="utf-8") as fh:
            self.assertEqual([], json.load(fh)["odoo"]["bases"])

    def test_with_a_vm_report_a_running_descent_drops_nothing(self):
        self._rapport(etages=[LeDefaire.ETAGE])
        code, arreter, supprimer, etage1 = self._detruire_pour_de_vrai(
            descentes=[999999]
        )
        self.assertEqual(1, code)
        supprimer.assert_not_called()
        etage1.assert_not_called()

    def test_destroy_dry_run_stops_no_server_and_drops_no_database(self):
        chemin = self._rapport(etages=[LeDefaire.ETAGE])
        code, arreter, supprimer, etage1 = self._detruire_pour_de_vrai(
            "--dry-run"
        )
        self.assertEqual(0, code)
        arreter.assert_not_called()
        supprimer.assert_not_called()
        etage1.assert_not_called()
        with open(chemin, encoding="utf-8") as fh:
            self.assertEqual(3, len(json.load(fh)["odoo"]["bases"]))

    def test_destroy_refused_keeps_the_databases(self):
        self._rapport(etages=[LeDefaire.ETAGE])
        code, arreter, supprimer, etage1 = self._detruire_pour_de_vrai(
            reponse="non"
        )
        self.assertEqual(1, code)
        arreter.assert_not_called()
        supprimer.assert_not_called()
        etage1.assert_not_called()

    def test_destroy_confirmed_drops_the_databases_then_the_vm(self):
        chemin = self._rapport(etages=[LeDefaire.ETAGE])
        code, arreter, supprimer, etage1 = self._detruire_pour_de_vrai()
        self.assertEqual(0, code)
        arreter.assert_called_once_with([4242], chemin[: -len(".json")])
        self.assertEqual(
            self.BASES, [c.args[0] for c in supprimer.call_args_list]
        )
        etage1.assert_called_once()

    def test_a_live_run_keeps_its_servers_and_databases(self):
        chemin = self._rapport()
        n, _de, arreter, supprimer = self._defaire(vivante=True)
        self.assertEqual(0, n)
        arreter.assert_not_called()
        supprimer.assert_not_called()
        with open(chemin, encoding="utf-8") as fh:
            self.assertEqual(3, len(json.load(fh)["odoo"]["bases"]))

    def test_the_servers_of_a_run_are_found_by_their_config(self):
        proc = os.path.join(self.maison, "proc")
        for entree in ("12", "13", "self", "x"):
            os.makedirs(os.path.join(proc, entree))
        course = os.path.join(self.dossier, "long-call-infra-1")
        for entree in ("14", "15"):
            os.makedirs(os.path.join(proc, entree))
        lignes = {
            12: f"python /o/odoo18.0/odoo/odoo-bin -c {course}/odoo-a/odoo18.conf",
            13: "python /o/odoo18.0/odoo/odoo-bin -c /ailleurs/odoo18.conf",
            # Le chemin dans une autre commande n'en fait pas un serveur.
            14: f"tail -f {course}/odoo-a/odoo18.log",
            15: f"vim {course}/odoo-a/odoo18.conf",
        }
        self.assertEqual(
            [12],
            lt.serveurs_de(
                course, proc=proc, lire=lambda p: lignes.get(p, "")
            ),
        )

    def test_a_server_that_lingers_is_killed(self):
        vivants = {12, 13}
        envois = []

        def tuer(pid, signal_):
            envois.append((pid, signal_))
            if pid == 12 or signal_ == lt.signal.SIGKILL:
                vivants.discard(pid)

        course = "/c/long-call-infra-1"
        lt.arreter_serveurs(
            [12, 13],
            course,
            tuer=tuer,
            lire=lambda p: (
                f"python odoo-bin -c {course}/odoo-a/odoo18.conf"
                if p in vivants
                else ""
            ),
            delai=0,
        )
        self.assertEqual(
            [
                (12, lt.signal.SIGTERM),
                (13, lt.signal.SIGTERM),
                (13, lt.signal.SIGKILL),
            ],
            envois,
        )
        self.assertEqual(set(), vivants)


class LArretDesServeurs(unittest.TestCase):
    def test_a_reused_pid_is_not_killed(self):
        # Le serveur s'arrête au SIGTERM ; son pid revient aussitôt à un
        # autre programme, qui ne reçoit pas de SIGKILL.
        envois = []
        lt.arreter_serveurs(
            [12],
            "/c/long-call-infra-1",
            tuer=lambda pid, signal_: envois.append((pid, signal_)),
            lire=lambda p: "/usr/bin/autre-programme --option",
            delai=0,
        )
        self.assertEqual([(12, lt.signal.SIGTERM)], envois)


class Monde:
    """Le coturn et les trois Odoo d'une course inventée, tels que les
    briques du scénario les voient : chaque ajout ou retrait les change
    comme le produit le fait. `redemarre` et `revoque` faux simulent un
    produit qui ne redémarre pas coturn à la bascule ou qui ne révoque
    rien."""

    def __init__(self, base):
        self.base = base
        self.mode = None
        self.pid = 100
        self.odoos = {}
        self.secrets = set()
        self.comptes = set()
        self.liste = []
        self.odoo = {
            lettre: {"module": "uninstalled", "params": {}, "rows": ()}
            for lettre in "abc"
        }
        self.n = 0
        self.redemarre = True
        self.revoque = True

    @staticmethod
    def _sha(valeur):
        return hashlib.sha256(valeur.encode("utf-8")).hexdigest()

    def etat(self):
        etat = json.loads(json.dumps(self.base))
        if self.mode:
            etat["turn_mode"] = self.mode
        if self.mode == "secret":
            etat["check_secret_sha256"] = "0" * 64
        etat["odoos"] = {
            cle: {
                "credential": (
                    {"kind": "secret", "value_sha256": self._sha(o["valeur"])}
                    if o["sorte"] == "secret"
                    else {"kind": "user", "user": "erplibre-00000000"}
                ),
                "retired": [
                    {"value_sha256": self._sha(v), "expires_at": "2999-01-01"}
                    for v in o["anciens"]
                ],
                "exempt": o["exempt"],
            }
            for cle, o in self.odoos.items()
        }
        return etat

    def sonde(self, cible, log, executer):
        conf = (
            "use-auth-secret\n" if self.mode == "secret" else "lt-cred-mech\n"
        )
        yml = (
            f"{lt.nm.EXEMPT_HOSTS_KEY}: {','.join(self.liste)}\n"
            if self.liste
            else ""
        )
        return mock.Mock(
            state=self.etat(),
            coturn={"config_text": conf},
            ntfy={"config_text": yml},
        )

    def ajouter(self, cible, lien, url, base, module, exempt, log, **kw):
        lettre, cle = lien.lettre, ol.odoo_key(url, base)
        voulu = (
            "secret"
            if module or self.odoo[lettre]["module"] == "installed"
            else "fixed"
        )
        if self.odoos and (self.mode or "fixed") != voulu:
            return {
                "ok": False,
                "etape": "plan",
                "plan": None,
                "etat": None,
                "refus": "call_infra_turn_mode_mismatch",
            }
        if voulu == "secret" and self.mode != "secret" and self.redemarre:
            self.pid += 1
        self.mode = voulu
        self.n += 1
        valeur = f"valeur-{self.n}"
        avant = self.odoos.get(cle)
        anciens = []
        if voulu == "secret":
            self.odoo[lettre].update(
                module="installed",
                params={ol.PARAM_URLS: "u", ol.PARAM_SECRET: "sha256:0"},
                rows=(),
            )
            anciens = [avant["valeur"]] if avant else []
            self.secrets.add(valeur)
        else:
            nom = ol.owned_username(url, base)
            self.odoo[lettre]["rows"] = tuple(
                {"server_type": "turn", "uri": "x", "username": nom}
                for _ in range(3)
            )
            self.comptes.add(valeur)
        self.odoos[cle] = {
            "sorte": "secret" if voulu == "secret" else "user",
            "valeur": valeur,
            "anciens": anciens,
            "exempt": exempt,
            "lettre": lettre,
        }
        if exempt and exempt not in self.liste:
            self.liste.append(exempt)
        return {
            "ok": True,
            "etape": "",
            "refus": None,
            "plan": mock.Mock(key=cle),
            "etat": self.etat(),
        }

    def retirer(self, cible, lien, cle, log, **kw):
        o = self.odoos.pop(cle)
        if self.revoque:
            self.secrets -= {o["valeur"], *o["anciens"]}
            self.comptes.discard(o["valeur"])
        self.odoo[lien.lettre].update(params={}, rows=())
        if o["exempt"] and all(
            x["exempt"] != o["exempt"] for x in self.odoos.values()
        ):
            self.liste.remove(o["exempt"])
        return {"ok": True, "etape": "", "refus": None, "etat": self.etat()}

    def allouer(self, ice, etat, cafile):
        if not ice:
            return [
                ci.CheckLine("odoo-ice", False, "call_infra_check_ice_none")
            ]
        vivant = ice["valeur"] in self.secrets | self.comptes
        urls = [UDP, TCP] + ([TLS] if ice["sorte"] == "secret" else [])
        return [
            ligne_ice(u, vivant, None if vivant else "401 Unauthorized")
            for u in urls
        ]

    def par_odoo(self, harnais, lettre, etat, cafile, invitation=None):
        o = next(
            (o for o in self.odoos.values() if o["lettre"] == lettre), None
        )
        ice = dict(o) if o else []
        return ice, self.allouer(ice, etat, cafile)

    def verifier(self, cible, adresse, cafile, log, executer=None):
        noms = lt.CONTROLES["odoo"]["debian"]
        lignes = [ci.CheckLine(n, True, "x") for n in noms]
        return lignes, {"turn_secrets": [(IP, v) for v in self.secrets]}

    def odoo_facts(self, lettre):
        o = self.odoo[lettre]
        return ol.OdooFacts(
            "18.0", 18, o["module"], dict(o["params"]), o["rows"], "127.0.0.1"
        )


class LeScenarioOdoo(unittest.TestCase):
    """`scenario_odoo` mené de bout en bout sur un monde inventé : chaque
    brique qui touche l'hôte, Odoo ou le réseau est remplacée, les verdicts
    sont ceux du scénario."""

    def setUp(self):
        self.dossier = tempfile.mkdtemp(prefix="longtest-call-infra-")
        self.addCleanup(shutil.rmtree, self.dossier, ignore_errors=True)
        self.log = os.path.join(self.dossier, "x.log")
        self.journal = os.path.join(self.dossier, "j.log")
        ans = lt.reponses(IP)
        facts = ci.parse_probe(DEBIAN_UFW_PROBE.replace("ufw", "none"))
        plan = ci.plan_install(facts, ans, NOW)
        self.base = ci.written_state(plan, "20261030-000000")
        self.monde = Monde(self.base)
        self.harnais = []

    def _harnais(self, preparer=(True, {})):
        monde, harnais = self.monde, self.harnais

        class Faux:
            def __init__(
                self, dossier, identifiant, course=None, journal=None
            ):
                self.bases = lt.noms_bases(identifiant)
                self.defait = False
                harnais.append(self)

            def preparer(self):
                return preparer

            def url(self, lettre):
                return f"http://127.0.0.1:{40001 + 'abc'.index(lettre)}"

            def lien(self, lettre, login="admin", mdp="admin"):
                return mock.Mock(
                    lettre=lettre,
                    url=self.url(lettre),
                    facts=lambda: monde.odoo_facts(lettre),
                )

            def defaire(self):
                self.defait = True
                return []

        return Faux

    def _course(self, preparer=(True, {})):
        tls = {}
        for role in ("server_crt", "server_key", "ca_crt"):
            tls[role] = os.path.join(self.dossier, role)
            with open(tls[role], "w", encoding="utf-8") as fh:
                fh.write(role)

        def preparer_vm(sc, cible, distro):
            sc.noter("cloud-init", True)
            return sc.noter("ufw-actif", True)

        installe = {
            "ok": True,
            "etape": "",
            "etat": self.base,
            "answers": lt.reponses(IP),
        }
        sc = lt.Scenario("debian", self.log, self.journal, "odoo")
        m = self.monde
        with (
            mock.patch.object(lt, "_preparer", preparer_vm),
            mock.patch.object(lt, "Harnais", self._harnais(preparer)),
            mock.patch.object(lt.local_cert, "issue", return_value=tls),
            mock.patch.object(lt, "installer", return_value=installe),
            mock.patch.object(lt, "adresse_vers", return_value=EXEMPT),
            mock.patch.object(lt, "_sonde", m.sonde),
            mock.patch.object(lt, "_pid", lambda *a: str(m.pid)),
            mock.patch.object(lt, "ajouter_odoo", m.ajouter),
            mock.patch.object(lt, "retirer_odoo", m.retirer),
            mock.patch.object(lt, "par_odoo", m.par_odoo),
            mock.patch.object(lt, "allouer", m.allouer),
            mock.patch.object(lt, "verifier", m.verifier),
            mock.patch.object(lt, "lien_invitation", return_value="lien"),
            mock.patch.object(lt, "desinstaller", return_value="fait"),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            lt.scenario_odoo(sc, "vm", IP, self.dossier)
        return sc

    def test_the_odoo_run_notes_every_planned_step(self):
        sc = self._course()
        self.assertEqual(
            list(lt.ETAPES["odoo"]["debian"][2:]), list(sc.etapes)
        )
        self.assertEqual(
            [], [n for n, ok in sc.etapes.items() if not ok], sc.details
        )
        self.assertTrue(self.harnais[0].defait)

    def test_a_switch_without_restart_is_seen(self):
        self.monde.redemarre = False
        sc = self._course()
        self.assertFalse(sc.etapes["b-bascule"])
        self.assertTrue(sc.etapes["c-sans-redemarrage"])

    def test_credentials_left_alive_are_seen(self):
        self.monde.revoque = False
        sc = self._course()
        self.assertFalse(sc.etapes["a-revoque"])
        self.assertFalse(sc.etapes["c-revoque"])
        self.assertTrue(sc.etapes["b-grace"])

    def test_a_harness_that_fails_still_drops_its_databases(self):
        sc = self._course(preparer=(False, "Odoo 18 absent"))
        self.assertEqual(
            ["cloud-init", "ufw-actif", "odoo-harnais", "bases-supprimees"],
            list(sc.etapes),
        )
        self.assertFalse(sc.etapes["odoo-harnais"])
        self.assertTrue(sc.etapes["bases-supprimees"])
        self.assertTrue(self.harnais[0].defait)


# --- Conteneurs et migration ------------------------------------------------

# Les lignes de la sonde des moteurs, par moteur présent.
SONDE_MOTEUR = {
    "docker": (
        "@@ENGINE docker 26.1.5\n@@COMPOSE docker docker compose\n"
        "@@DOCKER_SERVICE active enabled\n"
    ),
    "podman": (
        "@@ENGINE podman 5.4.2\n@@COMPOSE podman podman-compose\n"
        "@@PODMAN_RESTART enabled\n"
    ),
}
SONDE_SANS_MOTEUR = DEBIAN_UFW_PROBE.replace("ufw", "none")


def sonde_avec(moteur=None, extra=""):
    """La sonde d'une Debian sans pare-feu, le moteur `moteur` présent
    (une clé de SONDE_MOTEUR) et les lignes `extra`."""
    lignes = (SONDE_MOTEUR[moteur] if moteur else "") + extra
    return SONDE_SANS_MOTEUR.replace("@@END", f"{lignes}@@END")


def etat_conteneur(answers, uid=990):
    """L'état qu'écrit une installation en conteneurs pour `answers` :
    celui du plan, les ids des comptes posés comme le script les lit, et
    les paquets proposés consignés."""
    engine = answers.engine
    rootless = (
        "@@ROOTLESS 1 1 1 1 enabled\n@@USER_BUS 1\n"
        if answers.rootless
        else ""
    )
    facts = ci.parse_probe(sonde_avec(engine, rootless))
    plan = ci.plan_install(facts, answers, NOW)
    etat = ci.written_state(plan, "20261102-101500")
    for svc in etat["services"]:
        etat["services"][svc].update(uid=uid, gid=uid)
        if answers.rootless:
            etat["services"][svc]["account"] = cc.ROOTLESS_ACCOUNT
    if answers.rootless:
        etat["container"]["uid"] = uid
    offre = ci.engine_offer(
        ci.parse_probe(SONDE_SANS_MOTEUR), engine, answers.rootless
    )
    etat["container"]["engine_packages_added"] = list(offre)
    return etat


class LesCoursesConteneur(unittest.TestCase):
    def setUp(self):
        self.maison = tempfile.mkdtemp(prefix="longtest-call-infra-")
        self.addCleanup(shutil.rmtree, self.maison, ignore_errors=True)

    def _fichiers(self):
        trouves = []
        for dossier, _sous, fichiers in os.walk(self.maison):
            trouves += [os.path.join(dossier, f) for f in fichiers]
        return trouves

    @staticmethod
    def _courses(sortie):
        return [
            ligne.split("── ", 1)[1]
            for ligne in sortie.splitlines()
            if "── " in ligne
        ]

    @staticmethod
    def _etapes(sortie):
        return [
            ligne.split("étapes : ", 1)[1].split(", ")
            for ligne in sortie.splitlines()
            if "étapes : " in ligne
        ]

    def test_three_engines_three_courses_and_their_steps(self):
        code, sortie = lancer(
            self.maison, "--dry-run", "--scenario", "conteneur"
        )
        self.assertEqual(0, code, sortie)
        self.assertEqual(
            [
                "debian 13 (conteneur docker)",
                "debian 13 (conteneur podman)",
                "debian 13 (conteneur podman-rootless)",
            ],
            self._courses(sortie),
        )
        docker, podman, rootless = self._etapes(sortie)
        for moteur, etapes in zip(lt.MOTEURS, (docker, podman, rootless)):
            with self.subTest(moteur=moteur):
                self.assertEqual(
                    list(lt.etapes_de("conteneur", "debian", moteur)), etapes
                )
                for etape in (
                    "moteur-propose",
                    "moteur-installe",
                    "proprietaires",
                    "odoo-secret",
                    "odoo-second",
                    "relais-prive",
                    "crochet-lignee",
                    "redemarrage",
                    "rien-a-changer",
                    "relance-up",
                    "etat-apres-desinstallation",
                ):
                    self.assertIn(etape, etapes)
        self.assertIn("melange (information)", docker)
        self.assertNotIn("melange (information)", podman + rootless)
        self.assertIn("prod-443-non-root", podman)
        self.assertNotIn("prod-443-non-root", docker + rootless)
        self.assertNotIn("--distro arch", sortie)
        self.assertEqual(
            [],
            [
                f
                for f in self._fichiers()
                if not f.endswith(("-dryrun.json", ".log"))
            ],
        )

    def test_one_engine_one_course(self):
        code, sortie = lancer(
            self.maison,
            "--dry-run",
            "--scenario",
            "conteneur",
            "--moteur",
            "podman-rootless",
        )
        self.assertEqual(0, code, sortie)
        self.assertEqual(
            ["debian 13 (conteneur podman-rootless)"], self._courses(sortie)
        )

    def test_the_engine_option_belongs_to_the_container_scenario(self):
        code, sortie = lancer(
            self.maison, "--dry-run", "--scenario", "dev", "--moteur", "docker"
        )
        self.assertEqual(1, code)
        self.assertNotIn("deploy_qemu.py", sortie)
        with self.assertRaises(SystemExit):
            lancer(self.maison, "--dry-run", "--moteur", "lxc")

    def test_containers_and_migration_run_on_debian_only(self):
        for scenario in ("conteneur", "migration"):
            with self.subTest(scenario=scenario):
                code, sortie = lancer(
                    self.maison,
                    "--dry-run",
                    "--distro",
                    "arch",
                    "--scenario",
                    scenario,
                )
                self.assertEqual(1, code)
                self.assertNotIn("deploy_qemu.py", sortie)

    def test_the_migration_plan_names_its_database(self):
        code, sortie = lancer(
            self.maison, "--dry-run", "--scenario", "migration"
        )
        self.assertEqual(0, code, sortie)
        self.assertEqual(
            [["vm", "ssh", "cloud-init", "ufw-actif", *lt._MIGRATION_ETAPES]],
            self._etapes(sortie),
        )
        (ligne,) = [
            ligne.split("bases : ", 1)[1]
            for ligne in sortie.splitlines()
            if "bases : " in ligne
        ]
        self.assertRegex(ligne, r"^call_infra_odoo_\d+_\d+_a$")
        self.assertLessEqual(len(ligne), 63)
        self.assertNotIn("mobile_sync_", sortie)

    def test_the_migration_database_is_not_an_odoo_one(self):
        """Les deux scénarios d'une même course ont leurs bases à eux, et
        `--detruire` reconnaît chacune."""
        code, sortie = lancer(self.maison, "--dry-run", "--distro", "debian")
        self.assertEqual(0, code, sortie)
        odoo, migration = [
            ligne.split("bases : ", 1)[1].split(", ")
            for ligne in sortie.splitlines()
            if "bases : " in ligne
        ]
        self.assertEqual(3, len(odoo))
        self.assertEqual(1, len(migration))
        self.assertNotIn(migration[0], odoo)
        self.assertTrue(lt._BASE_ODOO.match(migration[0]))

    def test_each_course_has_its_log(self):
        sc = lt.Scenario("debian", "x", "j", "conteneur", variante="docker")
        self.assertEqual("docker", sc.ligne()["variante"])
        course = mock.Mock(dossier=self.maison, journal=os.devnull)
        with (
            mock.patch.object(lt, "creer_vm", return_value=(None, "", False)),
            mock.patch.object(lt, "Scenario", wraps=lt.Scenario) as fait,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            lt.mener_un(course, "debian", "conteneur", "podman-rootless")
            lt.mener_un(course, "debian", "dev")
        journaux = [appel.args[1] for appel in fait.call_args_list]
        self.assertEqual(
            [
                os.path.join(
                    self.maison, "conteneur-podman-rootless-debian.log"
                ),
                os.path.join(self.maison, "dev-debian.log"),
            ],
            journaux,
        )


class LesVerdictsDesConteneurs(unittest.TestCase):
    """Chaque verdict des courses conteneur et migration refuse ce qu'il ne
    prouve pas : un marqueur sans date de démarrage changée, deux lectures
    vides, un téléphone absent de la liste, un retour vert sans refus."""

    def test_a_recreation_is_proven_by_the_start_date(self):
        cas = (
            (True, True, ["t1", "t2"], True),
            (True, True, ["t1", "t1"], False),
            (True, True, ["", "t2"], False),
            (True, False, ["t1", "t2"], False),
            (False, False, ["t1", "t1"], True),
            (False, False, ["t1", "t2"], False),
            (False, True, ["t1", "t1"], False),
            (False, False, ["", ""], False),
        )
        for bascule, recree, debuts, vert in cas:
            with self.subTest(bascule=bascule, recree=recree, debuts=debuts):
                self.assertIs(
                    lt.verdict_recreation(bascule, recree, debuts), vert
                )

    def test_the_offered_packages_must_be_recorded(self):
        self.assertTrue(
            lt.verdict_moteur_installe(
                ["podman", "uidmap"], ["podman", "uidmap", "x"]
            )
        )
        self.assertFalse(
            lt.verdict_moteur_installe(["podman", "uidmap"], ["podman"])
        )
        self.assertFalse(lt.verdict_moteur_installe([], ["podman"]))

    def test_two_empty_reads_prove_nothing(self):
        self.assertTrue(lt.verdict_secrets({"a"}, {"a"}))
        self.assertFalse(lt.verdict_secrets(set(), set()))
        self.assertFalse(lt.verdict_secrets({"a"}, {"b"}))

    def test_the_phone_must_be_in_the_listing(self):
        self.assertTrue(lt.verdict_telephone("tel-1", ["tel-1", "tel-2"]))
        self.assertFalse(lt.verdict_telephone("tel-1", ["tel-2"]))
        self.assertFalse(lt.verdict_telephone("tel-1", None))
        self.assertFalse(lt.verdict_telephone(None, [None]))

    def test_the_up_rerun_needs_a_run_and_ntfy_back(self):
        couru = dict(ok=True, rien_a_faire=False, etape="")
        marche = {"etat": "running"}
        self.assertTrue(lt.verdict_relance_up(0, couru, marche))
        self.assertFalse(lt.verdict_relance_up(1, couru, marche))
        self.assertFalse(
            lt.verdict_relance_up(0, dict(couru, rien_a_faire=True), marche)
        )
        self.assertFalse(
            lt.verdict_relance_up(0, dict(couru, ok=False), marche)
        )
        self.assertFalse(lt.verdict_relance_up(0, couru, {"etat": "exited"}))

    def test_the_return_needs_the_refusal_with_an_older_host_ntfy(self):
        migre = dict(
            ok=True,
            refus=None,
            migration="done",
            plan=mock.Mock(migration="to_packages"),
        )
        refuse = dict(
            ok=False,
            refus="call_infra_ntfy_downgrade",
            migration=None,
            plan=None,
        )
        self.assertTrue(lt.verdict_retour(False, migre))
        self.assertFalse(lt.verdict_retour(True, migre))
        self.assertTrue(lt.verdict_retour(True, refuse))
        self.assertFalse(lt.verdict_retour(False, refuse))
        self.assertFalse(
            lt.verdict_retour(False, dict(migre, migration="rolled-back"))
        )


class LaLimiteDuRegistre(unittest.TestCase):
    """Une image refusée par la limite de tirage du registre n'est ni un
    vert ni un échec : la course dit de réessayer plus tard."""

    def setUp(self):
        self.dossier = tempfile.mkdtemp(prefix="longtest-call-infra-")
        self.addCleanup(shutil.rmtree, self.dossier, ignore_errors=True)
        self.log = os.path.join(self.dossier, "x.log")
        self.journal = os.path.join(self.dossier, "j.log")

    def _reponses(self, facts):
        return lt.methode_du_menu(
            lt.reponses(IP), facts, "container", "docker"
        )

    def test_the_install_output_says_rate_limit(self):
        hote = Hote(
            (0, SONDE_SANS_MOTEUR),
            (1, "@@PULL_FAILED coturn rate-limit\n@@SAVED no\n"),
        )
        res = lt.installer("vm", self._reponses, self.log, executer=hote)
        self.assertFalse(res["ok"])
        self.assertTrue(res["limite"])
        self.assertEqual("install", res["etape"])
        hote = Hote(
            (0, SONDE_SANS_MOTEUR),
            (1, "@@PULL_FAILED coturn failed\n@@SAVED no\n"),
        )
        res = lt.installer("vm", self._reponses, self.log, executer=hote)
        self.assertFalse(res["limite"])

    def test_the_course_verdict_is_the_registry_limit(self):
        installe = {
            "ok": False,
            "etape": "install",
            "limite": True,
            "refus": None,
        }

        def installer(cible, answers, log, **kw):
            answers(ci.parse_probe(SONDE_SANS_MOTEUR))
            return installe

        def preparer(sc, cible, distro):
            sc.noter("cloud-init", True)
            return sc.noter("ufw-actif", True)

        sc = lt.Scenario(
            "debian", self.log, self.journal, "conteneur", variante="docker"
        )
        with (
            mock.patch.object(lt, "_preparer", preparer),
            mock.patch.object(lt, "installer", side_effect=installer),
            contextlib.redirect_stdout(io.StringIO()) as ecran,
        ):
            lt.scenario_conteneur(sc, "vm", IP, self.dossier)
        ligne = sc.ligne()
        self.assertEqual(lt.LIMITE_REGISTRE, ligne["verdict"])
        self.assertNotIn("ECHEC", ligne["verdict"])
        self.assertNotIn("installation", sc.etapes)
        self.assertTrue(sc.etapes["moteur-propose"])
        self.assertIn(lt.MESSAGE_LIMITE, ecran.getvalue())
        # Un échec avant la limite reste un échec.
        sc.noter("ufw-actif", False)
        self.assertEqual("ECHEC(ufw-actif)", sc.ligne()["verdict"])

    def test_the_run_exits_two_and_says_it(self):
        maison = tempfile.mkdtemp(prefix="longtest-call-infra-")
        self.addCleanup(shutil.rmtree, maison, ignore_errors=True)

        def mener_un(course, distro, scenario, variante=None):
            verdict = "OK" if variante != "podman" else lt.LIMITE_REGISTRE
            return {"distro": distro, "scenario": scenario, "verdict": verdict}

        large = (16, 10 * (lt.MEMOIRE_MO + lt.MARGE_RAM_MO), 1000)
        with (
            mock.patch.object(lt, "capacite_hote", return_value=large),
            mock.patch.object(lt, "mener_un", side_effect=mener_un),
        ):
            code, sortie = lancer(maison, "--scenario", "conteneur")
        self.assertEqual(2, code, sortie)
        self.assertIn(f"{lt.LIMITE_REGISTRE} — {lt.MESSAGE_LIMITE}", sortie)
        self.assertEqual(
            1,
            lt.bilan(
                [{"verdict": "ECHEC(x)"}, {"verdict": lt.LIMITE_REGISTRE}],
                2,
                os.devnull,
            ),
        )
        self.assertEqual(1, lt.bilan([{"verdict": "OK"}], 2, os.devnull))
        self.assertEqual(0, lt.bilan([{"verdict": "OK"}], 1, os.devnull))


class LeMenuDesConteneurs(unittest.TestCase):
    """La méthode et le moteur sont ceux de `_call_infra_ask_install_method`
    : paquets manquants proposés et acceptés, refus levés avant le plan,
    sauf celui d'un port, que le plan rend."""

    def test_a_missing_engine_is_offered_and_accepted(self):
        facts = ci.parse_probe(SONDE_SANS_MOTEUR)
        vu = {}
        ans = lt.methode_du_menu(
            lt.reponses(IP), facts, "container", "podman-rootless", vu
        )
        self.assertEqual(
            ("container", "podman", True, True),
            (ans.method, ans.engine, ans.rootless, ans.install_engine),
        )
        self.assertEqual(ci.engine_offer(facts, "podman", True), vu["offre"])
        self.assertTrue(vu["offre"])
        facts = ci.parse_probe(sonde_avec("docker"))
        ans = lt.methode_du_menu(
            lt.reponses(IP), facts, "container", "docker", vu
        )
        self.assertEqual((), vu["offre"])
        self.assertFalse(ans.install_engine)

    def test_the_menu_refusals_stop_before_the_plan(self):
        etat = etat_conteneur(
            lt.methode_du_menu(
                lt.reponses(IP),
                ci.parse_probe(SONDE_SANS_MOTEUR),
                "container",
                "docker",
            )
        )
        sonde = sonde_avec(
            "docker",
            f"@@NTFY_HOST 2.11.0\n@@STATE {b64(json.dumps(etat))}\n",
        )
        facts = ci.parse_probe(sonde)
        with self.assertRaises(ci.Refusal) as refus:
            lt.methode_du_menu(lt.reponses(IP), facts, "packages")
        self.assertEqual("call_infra_ntfy_downgrade", refus.exception.key)
        hote = Hote((0, sonde))
        res = lt.installer(
            "vm",
            lambda f: lt.methode_du_menu(lt.reponses(IP), f, "packages"),
            os.devnull,
            executer=hote,
        )
        self.assertEqual(
            ("methode", "call_infra_ntfy_downgrade"),
            (res["etape"], res["refus"]),
        )
        self.assertEqual(1, len(hote.scripts))

    def test_a_port_refusal_waits_for_the_plan(self):
        facts = ci.parse_probe(sonde_avec("podman"))
        bas = dataclasses.replace(lt.reponses(IP), ntfy_port=80)
        ans = lt.methode_du_menu(bas, facts, "container", "podman")
        self.assertEqual(80, ans.ntfy_port)
        with self.assertRaises(ci.Refusal) as refus:
            ci.plan_install(facts, ans, NOW)
        self.assertEqual("call_infra_container_port", refus.exception.key)

    def test_production_coturn_alone_on_443(self):
        facts = ci.parse_probe(SONDE_SANS_MOTEUR)
        ans = lt.reponses_prod_coturn(IP, "crt", "key", facts, resolution())
        self.assertEqual(frozenset({"coturn"}), ans.services)
        self.assertTrue(ans.turns_443)
        self.assertIsNone(ans.nginx)
        self.assertEqual(443, ci.coturn_tls_port(ans))
        self.assertEqual("production", ans.mode)


class LesScriptsConteneur(unittest.TestCase):
    def setUp(self):
        base = lt.reponses(IP)
        facts = ci.parse_probe(SONDE_SANS_MOTEUR)
        self.etats = {
            moteur: etat_conteneur(
                lt.methode_du_menu(base, facts, "container", moteur)
            )
            for moteur in lt.MOTEURS
        }

    def test_the_host_scripts_parse(self):
        scripts = {"proprietaires": lt.script_proprietaires()}
        for moteur, etat in self.etats.items():
            scripts[f"conteneurs-{moteur}"] = lt.script_conteneurs(etat, 30)
            scripts[f"auto-{moteur}"] = lt.script_auto(etat)
            scripts[f"secret-{moteur}"] = lt.script_secret(IP, "s3", etat)
        scripts["demarrage"] = lt.SCRIPT_DEMARRAGE
        scripts["redemarrer"] = lt.SCRIPT_REDEMARRER
        scripts["port"] = lt.script_port_bas(443)
        scripts["apres"] = lt.script_apres_conteneur(["docker.io", "uidmap"])
        for nom, script in scripts.items():
            with self.subTest(script=nom):
                # Lu, jamais joué : aucun moteur ni outil système ne part
                # d'ici.
                fini = subprocess.run(
                    ["sh", "-n"],
                    input=script,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                self.assertEqual(0, fini.returncode, fini.stderr)

    def test_the_engine_comes_from_the_state(self):
        docker = lt.script_conteneurs(self.etats["docker"])
        self.assertIn('eng() { docker "$@"; }', docker)
        self.assertIn(cc.CONTAINERS["coturn"], docker)
        self.assertIn(cc.CONTAINERS["ntfy"], docker)
        rootless = lt.script_conteneurs(self.etats["podman-rootless"])
        self.assertIn(
            shlex.join(cc.rootless_prefix(cc.ROOTLESS_ACCOUNT, 990)), rootless
        )
        secret = lt.script_secret(IP, "s3", self.etats["docker"])
        self.assertIn(
            f"eng exec -u 990:990 {cc.CONTAINERS['coturn']} turnadmin -s",
            secret,
        )
        self.assertIn(ci.COTURN_DB, secret)
        self.assertNotIn("systemctl", secret)
        self.assertIn("systemctl show", lt.script_secret(IP, "s3"))
        etat = json.loads(json.dumps(self.etats["docker"]))
        etat["container"]["engine"] = "docker; reboot"
        with self.assertRaises(ValueError):
            lt.script_conteneurs(etat)

    def test_the_restart_units_of_each_engine(self):
        self.assertIn("docker.service", lt.script_auto(self.etats["docker"]))
        self.assertIn(
            "podman-restart.service", lt.script_auto(self.etats["podman"])
        )
        rootless = lt.script_auto(self.etats["podman-rootless"])
        self.assertIn("systemctl --user is-enabled", rootless)
        self.assertIn(f"linger/{cc.ROOTLESS_ACCOUNT}", rootless)

    def test_container_states_are_read_back(self):
        sortie = (
            "@@CSTATE coturn running 4242 990:990 2026-11-02 10:00:00 +0000"
            " UTC\n@@CSTATE ntfy exited 0 - \n"
        )
        lus = lt.etats_conteneurs(sortie)
        self.assertEqual("4242", lus["coturn"]["pid"])
        self.assertEqual(
            "2026-11-02 10:00:00 +0000 UTC", lus["coturn"]["demarre"]
        )
        self.assertEqual("exited", lus["ntfy"]["etat"])

    def test_the_databases_belong_to_the_state_accounts(self):
        etat = self.etats["podman-rootless"]
        bon = (
            f"@@OWNER coturn {cc.ROOTLESS_ACCOUNT} 990\n"
            f"@@OWNER ntfy {cc.ROOTLESS_ACCOUNT} 990\n"
        )
        self.assertTrue(lt.verdict_proprietaires(etat, bon)[0])
        subordonne = bon.replace(
            f"coturn {cc.ROOTLESS_ACCOUNT} 990", "coturn UNKNOWN 100989"
        )
        ok, detail = lt.verdict_proprietaires(etat, subordonne)
        self.assertFalse(ok)
        self.assertFalse(detail["coturn-ok"])
        self.assertFalse(lt.verdict_proprietaires(etat, "")[0])

    def test_the_reboot_verdict(self):
        etats = {"coturn": {"etat": "running"}, "ntfy": {"etat": "running"}}
        auto = "@@AUTO podman-restart.service enabled\n"
        self.assertTrue(lt.verdict_redemarrage("a", "b", etats, auto)[0])
        for avant, apres, lus, sortie in (
            ("a", "a", etats, auto),
            ("", "b", etats, auto),
            ("a", "b", {"coturn": {"etat": "exited"}}, auto),
            ("a", "b", {}, auto),
            ("a", "b", etats, "@@AUTO x disabled\n"),
            ("a", "b", etats, "@@AUTO user enabled\n@@LINGER non\n"),
        ):
            with self.subTest(avant=avant, apres=apres, sortie=sortie):
                self.assertFalse(
                    lt.verdict_redemarrage(avant, apres, lus, sortie)[0]
                )

    def test_port_443_held_by_a_non_root_turnserver(self):
        self.assertTrue(
            lt.verdict_port_bas("@@LISTEN turnserver 990\n@@END\n")[0]
        )
        for sortie in (
            "@@LISTEN turnserver 0\n@@END\n",
            "@@LISTEN nginx 33\n@@END\n",
            "@@END\n",
            "@@LISTEN turnserver 990\n",
        ):
            with self.subTest(sortie=sortie):
                self.assertFalse(lt.verdict_port_bas(sortie)[0])

    def test_nothing_left_after_the_container_uninstall(self):
        propre = "@@PKG docker.io un\n@@UFW_RULES 0\n@@END\n"
        self.assertTrue(lt.verdict_apres_conteneur(0, propre)[0])
        self.assertFalse(lt.verdict_apres_conteneur(1, propre)[0])
        for reste, cle in (
            ("@@CONTAINER erplibre-call-coturn", "sans-conteneur"),
            ("@@IMAGE docker.io/coturn/coturn:4.18.0", "sans-image"),
            ("@@IMAGE_FILE binwiederhier/ntfy", "sans-image"),
            ("@@VOLUME /var/lib/docker/volumes/0a1b/", "sans-volume"),
            ("@@COMPOSE present", "sans-compose"),
            (f"@@ACCOUNT {cc.ROOTLESS_ACCOUNT}", "sans-compte"),
            ("@@HOME present", "sans-compte"),
            ("@@LINGER present", "sans-compte"),
            ("@@PKG docker.io ii", "sans-paquet-moteur"),
            ("@@PKG docker.io rc", "sans-paquet-moteur"),
            ("@@CALL_DIR present", "sans-dossier-outil"),
        ):
            with self.subTest(reste=reste):
                sortie = propre.replace("@@END", f"{reste}\n@@END")
                ok, detail = lt.verdict_apres_conteneur(0, sortie)
                self.assertFalse(ok)
                self.assertFalse(detail[cle])
        ok, detail = lt.verdict_apres_conteneur(0, "@@UFW_RULES 2\n@@END\n")
        self.assertFalse(detail["sans-regle-ufw"])

    def test_the_hook_without_nginx(self):
        requis, interdits = lt.attendus_crochet(
            "crochet-lignee", cc.CONTAINERS["coturn"], nginx=False
        )
        self.assertIn(f"signal {cc.CONTAINERS['coturn']}", requis)
        self.assertNotIn("nginx-reloaded", requis)
        self.assertIn("applied-stale", interdits)
        requis, _i = lt.attendus_crochet("crochet-fourni", "x", nginx=False)
        self.assertEqual(("coturn-skip not-letsencrypt",), requis)


class MondeConteneur:
    """L'hôte d'une course `conteneur` tel que les scripts le voient :
    coturn recréé par la bascule en mode secret, signalé sans redémarrer
    par le crochet, relancé par le redémarrage. `recree` faux simule un
    produit qui recrée coturn à chaque ajout d'Odoo."""

    def __init__(self, premier):
        self.demarre = 1
        self.pid = 4242
        self.boot = 1
        self.recree = True
        self.premier = premier
        self.sert = premier[0]
        self.lignee = None
        self.le = False
        self.vus = []
        self.etat = {"services": {}}

    def etats(self):
        return "".join(
            f"@@CSTATE {svc} running {self.pid} 990:990 t{self.demarre}\n"
            for svc in ci.SERVICES
        )

    def distant(self, cible, script, log, delai, **kw):
        self.vus.append(script)
        if "@@CSTATE" in script:
            return 0, self.etats()
        if "@@ODOO_ADDED" in script:
            bascule = "install_coturn.sh" in script
            if bascule or not self.recree:
                self.demarre += 1
                self.pid += 1
            sortie = "@@RECREATE 1\n" if bascule or not self.recree else ""
            return 0, sortie + "@@TURN_MODE secret\n@@ODOO_ADDED yes\n"
        if "@@SAVED" in script:
            return 0, "@@SAVED yes\n"
        if script == lt.script_proprietaires():
            return 0, "".join(
                f"@@OWNER {svc} {fiche['account']} {fiche['uid']}\n"
                for svc, fiche in self.etat["services"].items()
            )
        if "turnadmin" in script:
            return 0, "@@SECRET_RC 0\n"
        if "@@LINEAGE" in script:
            self.lignee = script
            return 0, "@@LINEAGE placed\n"
        if script == lt.script_etat_lignee():
            self.le = True
            return 0, "@@STAGED letsencrypt\n"
        if script == ci.deploy_hook_text():
            if not self.le:
                return 0, "@@HOOK coturn-skip not-letsencrypt\n"
            self.sert = self.lignee_pem
            return 0, (
                "@@HOOK copied a b\n"
                f"@@HOOK signal {cc.CONTAINERS['coturn']}\n@@HOOK applied\n"
            )
        if script == lt.script_remise():
            self.le = False
            return 0, "@@RESTORED yes\n"
        if script == lt.SCRIPT_DEMARRAGE:
            return 0, f"@@BOOT b{self.boot}\n"
        if script == lt.SCRIPT_REDEMARRER:
            self.boot += 1
            self.pid += 1
            return 0, "@@REBOOT scheduled\n"
        if "@@AUTO" in script:
            return 0, "@@AUTO unite enabled\n@@LINGER oui\n"
        if "@@LISTEN" in script:
            return 0, "@@LISTEN turnserver 990\n@@END\n"
        if "@@UFW_RULES" in script:
            return 0, "@@PKG docker.io un\n@@UFW_RULES 0\n@@END\n"
        return 0, ""


class LeScenarioConteneur(unittest.TestCase):
    """`scenario_conteneur` mené de bout en bout : chaque brique qui touche
    l'hôte ou le réseau est remplacée, les certificats sont de vrais
    certificats d'une autorité inventée, les verdicts ceux du scénario."""

    def setUp(self):
        self.dossier = tempfile.mkdtemp(prefix="longtest-call-infra-")
        self.addCleanup(shutil.rmtree, self.dossier, ignore_errors=True)
        self.log = os.path.join(self.dossier, "x.log")
        self.journal = os.path.join(self.dossier, "j.log")

    def _course(self, moteur, preparer_monde=None):
        sc = lt.Scenario(
            "debian", self.log, self.journal, "conteneur", variante=moteur
        )
        vrai_issue = lt.local_cert.issue
        certificats = []

        def issue(dossier, noms):
            chemins = vrai_issue(dossier, noms)
            certificats.append(lt.paire(chemins))
            return chemins

        mondes = []
        appels = []
        installes = []

        def installer(cible, answers, log, **kw):
            # Après la première installation, le moteur est là, et en
            # rootless newuidmap et le bus de session aussi (`@@ROOTLESS`,
            # `@@USER_BUS`).
            facts = ci.parse_probe(
                sonde_avec(None)
                if not appels
                else sonde_avec(
                    lt.MOTEURS[moteur][0],
                    "@@ROOTLESS 1 1 1 1 enabled\n@@USER_BUS 1\n",
                )
            )
            ans = answers(facts)
            appels.append(ans)
            if ans.mode == "production":
                etat = ci.written_state(
                    ci.plan_install(
                        ci.parse_probe(sonde_avec(ans.engine)), ans, NOW
                    ),
                    "20261102-101500",
                )
                for fiche in etat["services"].values():
                    fiche.update(uid=990, gid=990)
                etat["container"]["engine_packages_added"] = ["podman"]
            else:
                etat = etat_conteneur(ans)
            if mondes:
                mondes[0].etat = etat
            installes.append(etat)
            return {
                "ok": True,
                "etape": "",
                "limite": False,
                "refus": None,
                "rien_a_faire": len(appels) == 2,
                "etat": etat,
                "answers": ans,
                "plan": None,
                "migration": None,
            }

        def verifier(cible, adresse, cafile, log, executer=None):
            noms = (
                lt.CONTROLES_PROD_COTURN
                if appels and appels[-1].mode == "production"
                else lt.CONTROLES["conteneur"]["debian"]
            )
            return [ci.CheckLine(n, True, "x") for n in noms], {}

        def vu(adresse, port, nom):
            return ssl.PEM_cert_to_DER_cert(mondes[0].sert)

        def distant(cible, script, log, delai, **kw):
            if not mondes:
                mondes.append(MondeConteneur(certificats[0]))
                mondes[0].etat = installes[-1]
                if preparer_monde:
                    preparer_monde(mondes[0])
            monde = mondes[0]
            for pem in certificats[:2]:
                if script == lt.script_lignee(*pem):
                    monde.lignee_pem = pem[0]
            return monde.distant(cible, script, log, delai, **kw)

        def preparer(sc, cible, distro):
            sc.noter("cloud-init", True)
            return sc.noter("ufw-actif", True)

        allocation = mock.Mock(ok=True, error=None)
        with (
            mock.patch.object(lt, "_preparer", preparer),
            mock.patch.object(lt.local_cert, "issue", side_effect=issue),
            mock.patch.object(lt, "installer", side_effect=installer),
            mock.patch.object(lt, "verifier", side_effect=verifier),
            mock.patch.object(lt, "distant", side_effect=distant),
            mock.patch.object(
                lt, "desinstaller", side_effect=["fait", "rien", "fait"]
            ),
            mock.patch.object(lt, "ports_fermes", return_value={}),
            mock.patch.object(lt, "certificat_vu", side_effect=vu),
            mock.patch.object(lt, "attendre_ssh", return_value=True),
            mock.patch.object(lt, "DELAI_SERIE", 0),
            mock.patch.object(lt, "DELAI_REDEMARRAGE", 0),
            mock.patch.object(
                lt.turn_client, "allocate", return_value=allocation
            ),
            mock.patch.object(
                lt.turn_client, "permission", return_value=allocation
            ),
            mock.patch.object(
                lt.socket, "getaddrinfo", side_effect=OSError("inconnu")
            ),
            mock.patch.object(
                lt.subprocess, "run", side_effect=self._seul_openssl
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            lt.scenario_conteneur(sc, "vm", IP, self.dossier)
        return sc, mondes, appels

    _vrai_run = staticmethod(subprocess.run)

    @classmethod
    def _seul_openssl(cls, argv, *a, **kw):
        """openssl, pour les vrais certificats ; rien d'autre ne part d'ici
        (ni ssh, ni moteur)."""
        if argv and argv[0] == "openssl":
            return cls._vrai_run(argv, *a, **kw)
        raise AssertionError(f"processus lancé : {argv}")

    def test_each_engine_notes_every_planned_step(self):
        for moteur in lt.MOTEURS:
            with self.subTest(moteur=moteur):
                sc, _mondes, appels = self._course(moteur)
                prevues = [
                    e
                    for e in lt.etapes_de("conteneur", "debian", moteur)[2:]
                    if not e.endswith("(information)")
                ]
                self.assertEqual(prevues, list(sc.etapes))
                self.assertEqual(
                    [],
                    [n for n, ok in sc.etapes.items() if not ok],
                    sc.details,
                )
                self.assertEqual("OK", sc.ligne()["verdict"])
                engine, rootless = lt.MOTEURS[moteur]
                self.assertEqual(
                    ("container", engine, rootless, True),
                    (
                        appels[0].method,
                        appels[0].engine,
                        appels[0].rootless,
                        appels[0].install_engine,
                    ),
                )
                # La relance trouve le moteur : rien n'est plus proposé.
                self.assertFalse(appels[1].install_engine)
        self.assertIn("melange", self._course("docker")[0].details)

    def test_a_recreate_on_every_odoo_is_seen(self):
        def recree_toujours(monde):
            monde.recree = False

        sc, _m, _a = self._course("docker", recree_toujours)
        self.assertTrue(sc.etapes["odoo-secret"])
        self.assertFalse(sc.etapes["odoo-second"])

    def test_a_refused_private_relay_is_seen(self):
        refus = mock.Mock(ok=False, error="403 Forbidden")
        with mock.patch.object(
            lt.turn_client, "permission", return_value=refus
        ):
            sc = lt.Scenario("debian", self.log, self.journal, "conteneur")
            with contextlib.redirect_stdout(io.StringIO()):
                lt.relais_prive(sc, lt.reponses(IP), "secret-invente-0123")
        self.assertFalse(sc.etapes["relais-prive"])
        self.assertEqual(
            "403 Forbidden", sc.details["relais-prive"]["resultat"]
        )

    def test_a_stopped_ntfy_comes_back_through_up(self):
        for moteur in ("docker", "podman-rootless"):
            with self.subTest(moteur=moteur):
                sc, mondes, appels = self._course(moteur)
                self.assertTrue(sc.etapes["relance-up"], sc.details)
                arrets = [
                    v
                    for v in mondes[0].vus
                    if v.endswith(f"eng stop {cc.CONTAINERS['ntfy']}")
                ]
                self.assertEqual(1, len(arrets))
                if moteur == "podman-rootless":
                    self.assertIn("runuser -u erplibre-call", arrets[0])

    def test_the_hook_signals_the_container(self):
        sc, mondes, _a = self._course("podman-rootless")
        detail = sc.details["crochet-lignee"]
        self.assertIn(f"signal {cc.CONTAINERS['coturn']}", detail["crochet"])
        self.assertEqual(detail["pid"][0], detail["pid"][1])
        self.assertIn(ci.deploy_hook_text(), mondes[0].vus)

    def test_the_production_phase_holds_443(self):
        sc, _m, appels = self._course("podman")
        prod = appels[-1]
        self.assertEqual(
            (frozenset({"coturn"}), True, "podman", False),
            (prod.services, prod.turns_443, prod.engine, prod.rootless),
        )
        self.assertTrue(sc.etapes["prod-443-non-root"])
        self.assertTrue(sc.etapes["prod-verification"])


class LeScenarioMigration(unittest.TestCase):
    """`scenario_migration` mené de bout en bout sur un hôte inventé : la
    méthode change deux fois, l'Odoo reste branché."""

    def setUp(self):
        self.dossier = tempfile.mkdtemp(prefix="longtest-call-infra-")
        self.addCleanup(shutil.rmtree, self.dossier, ignore_errors=True)
        self.log = os.path.join(self.dossier, "x.log")
        self.journal = os.path.join(self.dossier, "j.log")
        self.harnais = []

    def _course(self, ntfy_hote=None, readd=(), secrets_apres=None):
        harnais = self.harnais

        class Faux:
            def __init__(
                self,
                dossier,
                identifiant,
                course=None,
                journal=None,
                lettres=lt.LETTRES_ODOO,
            ):
                self.bases = {
                    k: v
                    for k, v in lt.noms_bases(identifiant).items()
                    if k in lettres
                }
                self.defait = False
                harnais.append(self)

            def preparer(self):
                return True, {}

            def url(self, lettre):
                return "http://127.0.0.1:40001"

            def lien(self, lettre, *a):
                return mock.Mock()

            def defaire(self):
                self.defait = True
                return []

        tls = {}
        for role in ("server_crt", "server_key", "ca_crt"):
            tls[role] = os.path.join(self.dossier, role)
            with open(tls[role], "w", encoding="utf-8") as fh:
                fh.write(role)
        paquets = ci.written_state(
            ci.plan_install(
                ci.parse_probe(SONDE_SANS_MOTEUR), lt.reponses(IP), NOW
            ),
            "20261102-101500",
        )
        paquets["turn_mode"] = "secret"
        appels = []

        def installer(cible, answers, log, **kw):
            sonde = sonde_avec(
                "podman", f"@@NTFY_HOST {ntfy_hote}\n" if ntfy_hote else ""
            )
            if callable(answers):
                facts = ci.parse_probe(sonde)
                if appels:
                    etat_avant = (
                        etat_conteneur(appels[-1])
                        if appels[-1].method == "container"
                        else paquets
                    )
                    facts = dataclasses.replace(facts, state=etat_avant)
                try:
                    answers = answers(facts)
                except ci.Refusal as refus:
                    return {
                        "ok": False,
                        "etape": "methode",
                        "refus": refus.key,
                        "limite": False,
                        "plan": None,
                        "migration": None,
                        "etat": None,
                    }
            appels.append(answers)
            sens = None
            if len(appels) > 1:
                sens = (
                    "to_container"
                    if answers.method == "container"
                    else "to_packages"
                )
            etat = (
                etat_conteneur(answers)
                if answers.method == "container"
                else paquets
            )
            return {
                "ok": True,
                "etape": "",
                "refus": None,
                "limite": False,
                "etat": etat,
                "answers": answers,
                "plan": mock.Mock(migration=sens, odoo_readd=tuple(readd)),
                "migration": "done" if sens else None,
            }

        lus = {"avant": [(IP, "s1"), (IP, "s2")]}

        def verifier(cible, adresse, cafile, log, executer=None):
            noms = lt.CONTROLES["migration"]["debian"]
            premier = "vu" not in lus
            lus["vu"] = True
            secrets_lus = (
                lus["avant"]
                if premier or secrets_apres is None
                else secrets_apres
            )
            return [ci.CheckLine(n, True, "x") for n in noms], {
                "turn_secrets": secrets_lus
            }

        telephones = []

        def distant(cible, script, log, delai, **kw):
            if "token" in script and "add" in script:
                telephones.append(kw)
                return 0, "token tk_Abc created for user erm_longtest\n"
            if " access --config" in script:
                return 0, f"user {nm_phone()} (role: user)\n"
            return 0, "@@OWNER ntfy\n"

        sonde_retour = ci.parse_probe(
            sonde_avec(
                "podman", f"@@NTFY_HOST {ntfy_hote}\n" if ntfy_hote else ""
            )
        )
        sc = lt.Scenario(
            "debian",
            self.log,
            self.journal,
            "migration",
            course=mock.Mock(identifiant="42_20261102101500"),
        )

        def preparer(sc, cible, distro):
            sc.noter("cloud-init", True)
            return sc.noter("ufw-actif", True)

        ajout = {
            "ok": True,
            "etape": "",
            "refus": None,
            "plan": None,
            "etat": paquets,
        }
        ice = [ligne_ice(u, True) for u in (UDP, TCP, TLS)]
        with (
            mock.patch.object(lt, "_preparer", preparer),
            mock.patch.object(lt, "Harnais", Faux),
            mock.patch.object(lt.local_cert, "issue", return_value=tls),
            mock.patch.object(lt, "paire", return_value=(None, None)),
            mock.patch.object(lt, "installer", side_effect=installer),
            mock.patch.object(lt, "verifier", side_effect=verifier),
            mock.patch.object(lt, "distant", side_effect=distant),
            mock.patch.object(lt, "_sonde", return_value=sonde_retour),
            mock.patch.object(lt, "adresse_vers", return_value=EXEMPT),
            mock.patch.object(lt, "exempt_du_menu", return_value=EXEMPT),
            mock.patch.object(lt, "ajouter_odoo", return_value=ajout),
            mock.patch.object(
                lt,
                "retirer_odoo",
                return_value={"ok": True, "refus": None},
            ),
            mock.patch.object(lt, "par_odoo", return_value=([], ice)),
            mock.patch.object(lt, "desinstaller", return_value="fait"),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            lt.scenario_migration(sc, "vm", IP, self.dossier)
        return sc, appels

    def test_the_migration_notes_every_planned_step(self):
        sc, appels = self._course()
        self.assertEqual(
            ["cloud-init", "ufw-actif", *lt._MIGRATION_ETAPES], list(sc.etapes)
        )
        self.assertEqual(
            [], [n for n, ok in sc.etapes.items() if not ok], sc.details
        )
        self.assertEqual(
            ["packages", "container", "packages"], [a.method for a in appels]
        )
        self.assertEqual(
            ("podman", False), (appels[1].engine, appels[1].rootless)
        )
        self.assertEqual(["a"], list(self.harnais[0].bases))
        self.assertRegex(
            self.harnais[0].bases["a"], r"^call_infra_odoo_42_\d+0_a$"
        )
        self.assertTrue(self.harnais[0].defait)

    def test_an_older_host_ntfy_refuses_the_way_back(self):
        sc, appels = self._course(ntfy_hote="2.11.0")
        self.assertTrue(sc.etapes["retour-paquets"], sc.details)
        self.assertEqual(
            "call_infra_ntfy_downgrade", sc.details["retour-paquets"]["refus"]
        )
        self.assertEqual(["packages", "container"], [a.method for a in appels])

    def test_an_odoo_to_plug_again_fails_the_migration(self):
        sc, _a = self._course(readd=("http://x|y",))
        self.assertFalse(sc.etapes["migration-conteneurs"])
        self.assertNotIn("secrets-identiques", sc.etapes)
        self.assertTrue(sc.etapes["bases-supprimees"])

    def test_a_lost_secret_is_seen(self):
        sc, _a = self._course(secrets_apres=[(IP, "s1")])
        self.assertFalse(sc.etapes["secrets-identiques"])
        self.assertNotIn("s1", json.dumps(sc.details))


def nm_phone():
    return lt.nm.phone_user(lt.LIBELLE_TELEPHONE)


if __name__ == "__main__":
    unittest.main()
