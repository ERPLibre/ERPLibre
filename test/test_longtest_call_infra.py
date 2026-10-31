#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le test long de l'infrastructure d'appel (coturn, ntfy) sur des VM.

Lui crée une VM Debian et une VM Arch et y installe pour de bon ; ceux-ci
gardent sa forme sans aucune VM :

- « --dry-run » montre les commandes de création et ne crée rien ;
- « --detruire » défait d'après le rapport, au contrat de descente.py ;
- chaque appel borné est rattrapé : un délai dépassé est un verdict, pas
  une trace ;
- il prend le verrou des tests longs et le menu sait le lancer et le
  défaire ;
- il pilote les MÊMES briques que le menu (`call_infra`), des `Answers` à
  la place des questions, et rien de secret n'atteint son journal.
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
        contextlib.redirect_stdout(sortie),
        contextlib.redirect_stderr(io.StringIO()),
    ):
        code = lt.mener(list(args))
    return code, sortie.getvalue()


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

    def test_one_distribution_only(self):
        code, sortie = lancer(self.maison, "--dry-run", "--distro", "arch")
        self.assertEqual(0, code, sortie)
        self.assertIn("--distro arch --version latest", sortie)
        self.assertNotIn("--distro debian", sortie)

    def test_an_unknown_distribution_is_refused(self):
        with self.assertRaises(SystemExit) as fin:
            lancer(self.maison, "--dry-run", "--distro", "fedora")
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
                lt, "mener_un", side_effect=lambda c, d: self._vu(crees, d)
            ),
        ):
            code, _sortie = lancer(self.maison, *args)
        return code, crees

    @staticmethod
    def _vu(crees, distro):
        crees.append(distro)
        return {"distro": distro, "verdict": "OK"}

    def test_keeping_every_vm_asks_room_for_each(self):
        code, crees = self._mener("--garder")
        self.assertEqual(1, code)
        self.assertEqual([], crees)

    def test_keeping_one_system_asks_room_for_one(self):
        _code, crees = self._mener("--garder", "--distro", "arch")
        self.assertEqual(["arch"], crees)


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
            "ci.written_state",
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

    def __call__(self, cible, script, log, delai, **kw):
        self.scripts.append(script)
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
