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
  série des deux certificats inventés.
"""

import ast
import base64
import contextlib
import datetime
import io
import json
import os
import shutil
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
from script.todo import todo_i18n  # noqa: E402

IP = "192.0.2.10"
NOW = datetime.datetime.now(datetime.timezone.utc)


def b64(text):
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def lancer(maison, *args):
    """Le script mené dans ce processus, sur un HOME qui ne contient rien.
    Rend (code, sortie).

    Pas de sous-processus : un call_infra.py vivant est, pour les tests des
    autres tests longs que le lanceur unitaire passe en parallèle, une
    descente en cours, et leur « --detruire » refuse alors de travailler.
    Le verrou n'est pas le sujet de ces tests : autre_descente n'y voit
    rien."""
    sortie = io.StringIO()
    with (
        mock.patch.dict(os.environ, {"HOME": maison}),
        mock.patch.object(descente, "autre_descente", lambda: []),
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

    def test_the_development_plan_is_the_first_lot(self):
        code, sortie = lancer(self.maison, "--dry-run", "--scenario", "dev")
        self.assertEqual(0, code, sortie)
        self.assertEqual(
            [list(lt.ETAPES["dev"]["debian"]), list(lt.ETAPES["dev"]["arch"])],
            self._etapes(sortie),
        )
        self.assertNotIn("crochet", sortie)

    def test_both_scenarios_by_default(self):
        code, sortie = lancer(self.maison, "--dry-run")
        self.assertEqual(0, code, sortie)
        self.assertEqual(4, len(self._etapes(sortie)))
        self.assertIn("ntfy-ancien", sortie)
        self.assertIn("crochet-lignee", sortie)

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
                side_effect=lambda c, d, s: self._vu(crees, d, s),
            ),
        ):
            code, _sortie = lancer(self.maison, *args)
        return code, crees

    @staticmethod
    def _vu(crees, distro, scenario):
        crees.append((distro, scenario))
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
                side_effect=lambda c, d, s: self._vu(crees, d, s),
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
                ("arch", "dev"),
                ("arch", "prod"),
            ],
            crees,
        )


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
        self.assertEqual(
            self.todo._longtest_question("--detruire", "call_infra.py"),
            self.todo._longtest_question("--detruire"),
        )


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
            "@@ACTIVE ntfy active\n"
        )
        masque = lt.masquer(texte)
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
        self.assertIn('"$(cat)"', commande)
        self.assertTrue(commande.endswith("</dev/null"))
        commande = lt.commande_distante(utilisateur="ntfy")
        self.assertIn("-u ntfy", commande)
        commande = lt.commande_distante(
            env={"NTFY_BASE_URL": "http://192.0.2.10:8080"}, shell="bash"
        )
        self.assertIn("env NTFY_BASE_URL=http://192.0.2.10:8080", commande)
        self.assertIn('bash -c "$(cat)"', commande)
        commande = lt.commande_distante(root=False, shell="bash")
        self.assertFalse(commande.startswith("sudo"))

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
    )
    # Ce qui ne sert qu'à l'écran du menu : le texte d'un refus, les notes
    # affichées sous l'aperçu du pare-feu.
    ECRAN_SEUL = {"SUPPORTED", "firewall_notes"}

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


if __name__ == "__main__":
    unittest.main()
