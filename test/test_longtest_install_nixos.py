#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le test long qui installe ERPLibre sur NixOS.

Lui crée une VM et prend des heures ; ceux-ci gardent sa forme en quelques
millisecondes. Ce qu'ils tiennent :

- il envoie la commande du MENU, pas une chaîne à lui. Un test qui
  installerait par ses propres soins prouverait SON chemin, et c'est
  précisément là que se cachaient les pannes ;
- le verdict porte sur l'ÉTAT de la machine, pas sur un code de retour :
  « nixos-rebuild switch » rend 4 sur un système pourtant activé, et chaque
  bloc d'outil du menu rend 0 par construction ;
- l'installation part en UNE session ssh, comme le déploiement le fait. C'est
  la condition qui expose la panne du premier passage — celle qui disparaît
  dès qu'on rejoue dans une session neuve ;
- il est dans long_test/ et le lanceur unitaire ne le ramasse pas ;
- « --dry-run » ne crée rien et le dit.
"""

import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.argv = ["todo.py"]

RACINE = Path(__file__).resolve().parents[1]
SCRIPT = RACINE / "long_test/install_nixos.py"
SRC = SCRIPT.read_text(encoding="utf-8")


class LaPlace(unittest.TestCase):
    def test_it_lives_out_of_the_unit_runner(self):
        """Le lanceur balaie « test/test_*.py » et doit rester lançable en
        quelques secondes, même sans virtualisation."""
        self.assertTrue(SCRIPT.exists())
        self.assertFalse((RACINE / "test/test_install_nixos_long.py").exists())

    def test_it_is_executable(self):
        """Le menu et le README l'appellent directement."""
        self.assertTrue(os.access(SCRIPT, os.X_OK))

    def test_it_parses(self):
        ast.parse(SRC)


class LeCheminEprouve(unittest.TestCase):
    def test_the_install_command_comes_from_the_menu(self):
        """Deux copies d'une chaîne d'installation divergent, et c'est la
        copie du test qui reste verte pendant que le produit casse."""
        self.assertIn("_qemu_erplibre_remote_cmd", SRC)
        # Aucune chaîne d'installation écrite ici.
        self.assertNotIn("make install_odoo", SRC)
        self.assertNotIn("git clone", SRC)

    def test_the_block_goes_in_one_ssh_session(self):
        """La session est ouverte AVANT que « make install_os » n'applique le
        module : c'est ce qui expose la panne du premier passage."""
        self.assertIn('["bash -s"]', SRC.replace("'", '"'))

    def test_the_verdict_is_the_state_not_the_return_code(self):
        """Le code de retour est noté, pas cru."""
        self.assertIn("all(controles.values())", SRC)

    def test_what_must_compile_is_named(self):
        """Les paquets sans roue amont sont ceux qui tombent quand les
        en-têtes manquent, et eux seuls."""
        for module in ("psycopg2", "ldap", "cups", "MySQLdb"):
            with self.subTest(module=module):
                self.assertIn(module, SRC)

    def test_a_missing_answer_is_not_a_success(self):
        """« 000 » est l'absence de réponse : l'accepter ferait passer une VM
        où rien n'écoute."""
        self.assertNotIn('"000"', SRC)
        self.assertIn('"303"', SRC)


class LePlan(unittest.TestCase):
    """Ce que la machine doit avoir AVANT qu'on crée quoi que ce soit."""

    def test_the_free_space_asked_for_is_what_gets_written(self):
        """Un qcow2 n'est pas préalloué : il ne prend que ce qu'on y écrit.
        Comparer les 40 Go du disque VIRTUEL à l'espace libre faisait refuser
        le test sur une machine qui pouvait parfaitement le mener."""
        self.assertIn("DISQUE_ECRIT_GO", SRC)
        i = SRC.index("if disque <")
        self.assertIn("DISQUE_ECRIT_GO", SRC[i : i + 120])
        self.assertNotIn("if disque < DISQUE_GO", SRC)

    def test_the_written_figure_is_smaller_than_the_virtual_disk(self):
        """Si l'un rattrapait l'autre, la distinction n'aurait plus d'objet et
        le seuil serait faux dans l'autre sens."""
        vals = {}
        for ligne in SRC.splitlines():
            for nom in ("DISQUE_GO", "DISQUE_ECRIT_GO"):
                if ligne.startswith(f"{nom} = "):
                    vals[nom] = int(ligne.split("=")[1])
        self.assertLess(vals["DISQUE_ECRIT_GO"], vals["DISQUE_GO"])

    def test_it_refuses_before_creating_anything(self):
        """Annoncer un plan qui ne tient pas coûte une heure pour rien : le
        contrôle passe AVANT la création."""
        self.assertLess(SRC.index("def plan_tient"), SRC.index("def mener"))
        i = SRC.index("if not args.dry_run and not plan_tient")
        self.assertLess(i, SRC.index("nom, uuid = creer_vm"))


class LEssaiABlanc(unittest.TestCase):
    def test_it_creates_nothing_and_says_so(self):
        fini = subprocess.run(
            [
                str(RACINE / ".venv.erplibre/bin/python"),
                str(SCRIPT),
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            timeout=180,
            cwd=RACINE,
        )
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertIn("--dry-run", fini.stdout)
        # Le plan montre la commande de création, sans la lancer.
        self.assertIn("deploy_qemu.py", fini.stdout)
        self.assertIn("--distro nixos", fini.stdout)

    def test_the_dry_run_report_is_named_apart(self):
        """Un rapport d'essai à blanc n'a rien créé : le confondre avec un
        vrai ferait détruire d'après une liste vide."""
        self.assertIn("-dryrun.json", SRC)


class RienNInterrompLaCourse(unittest.TestCase):
    """Un test lancé pour des heures sans surveillance doit rendre un
    VERDICT, pas une trace d'exception.

    `subprocess.run(..., timeout=...)` lève TimeoutExpired quand la commande
    dépasse son délai — et c'est le cas normal ici, pas l'exception : un ssh
    pendu, une création qui traîne, une installation qui n'en finit pas."""

    def test_every_bounded_call_is_caught(self):
        arbre = ast.parse(SRC)
        # Les appels bornés, et la ligne de chacun.
        bornes = []
        for noeud in ast.walk(arbre):
            if not isinstance(noeud, ast.Call):
                continue
            cible = ast.unparse(noeud.func)
            if cible != "subprocess.run":
                continue
            if any(m.arg == "timeout" for m in noeud.keywords):
                bornes.append(noeud.lineno)
        self.assertGreaterEqual(len(bornes), 4)
        # Les lignes couvertes par un « try ».
        couvertes = set()
        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.Try):
                for corps in noeud.body:
                    for interne in ast.walk(corps):
                        if hasattr(interne, "lineno"):
                            couvertes.add(interne.lineno)
        for ligne in bornes:
            with self.subTest(ligne=ligne):
                self.assertIn(ligne, couvertes)

    def test_a_timeout_is_reported_not_raised(self):
        """Ce que le journal doit porter à la place de la trace."""
        self.assertIn("installation interrompue", SRC)


class LeDefaire(unittest.TestCase):
    """La forme du rapport n'est pas libre : c'est le CONTRAT du défaire
    partagé de descente.py, et rien dans le langage ne l'impose.

    Le rapport écrit d'abord n'avait pas d'« etages » — dernier_rapport
    l'écartait comme « rien créé », « --detruire » répondait « rien à
    défaire », et la VM survivait à ce qui devait l'effacer."""

    ETAGE = {
        "niveau": 1,
        "nom": "long-nixos-000000",
        "uuid": "aaaa-bbbb",
        "alias": "long-nixos-000000",
        "cree": True,
    }

    def setUp(self):
        self.maison = tempfile.mkdtemp(prefix="longtest-nixos-")
        self.dossier = os.path.join(self.maison, ".erplibre/longtest")
        os.makedirs(self.dossier)
        self.addCleanup(shutil.rmtree, self.maison, ignore_errors=True)

    def _defaire(self, rapport):
        """Le script, à blanc, sur un HOME qui ne contient que ce rapport."""
        with open(
            os.path.join(self.dossier, "long-nixos-19990101-000000.json"),
            "w",
            encoding="utf-8",
        ) as fh:
            json.dump(rapport, fh)
        env = dict(os.environ, HOME=self.maison)
        fini = subprocess.run(
            [
                str(RACINE / ".venv.erplibre/bin/python"),
                str(SCRIPT),
                "--detruire",
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            timeout=180,
            cwd=RACINE,
            env=env,
        )
        return fini.stdout

    def test_the_machine_named_is_the_one_the_report_carries(self):
        """Et non un nom recalculé : le script nomme ses VM avec l'heure, là
        où le repli du défaire partagé dirait « long-nixos-1 »."""
        sortie = self._defaire(
            {
                "outil": "install_nixos",
                "dry_run": False,
                "pid": 1,
                "etages": [self.ETAGE],
            }
        )
        self.assertIn("long-nixos-000000", sortie)
        self.assertNotIn("long-nixos-1 ", sortie)
        # Une seule machine : aucune imbriquée.
        self.assertIn("0 VM imbriquée(s)", sortie)
        self.assertIn("rien ne sera détruit", sortie)

    def test_a_report_without_that_shape_finds_nothing(self):
        """La preuve que le contrat compte : la forme écrite d'abord."""
        sortie = self._defaire(
            {
                "outil": "install_nixos",
                "dry_run": False,
                "vm": {"nom": "long-nixos-000000", "uuid": "aaaa"},
            }
        )
        self.assertIn("rien à défaire", sortie)

    def test_a_dry_run_report_is_never_used_to_destroy(self):
        """Un plan n'a rien créé : détruire d'après lui viserait des machines
        qui n'existent pas, ou pire, celles d'une autre course."""
        sortie = self._defaire(
            {
                "outil": "install_nixos",
                "dry_run": True,
                "pid": 1,
                "etages": [self.ETAGE],
            }
        )
        self.assertIn("rien à défaire", sortie)

    def test_the_report_carries_the_pid_of_its_run(self):
        """Sans lui, « --detruire » lancé pendant une installation prendrait
        le rapport de la course EN COURS — le plus récent — et détruirait la
        machine sous elle."""
        self.assertIn('"pid": os.getpid()', SRC)


class LeVerrouEtLeMenu(unittest.TestCase):
    def test_it_shares_the_lock_of_the_other_long_tests(self):
        """Deux tests longs se disputent la RAM, le disque et ~/.ssh/config
        aussi sûrement que deux descentes de la même pile."""
        src = (RACINE / "long_test/descente.py").read_text(encoding="utf-8")
        self.assertIn('"install_nixos.py"', src)

    def test_the_menu_offers_it_dry_and_for_real(self):
        from script.todo.longtest_menu import SCRIPTS_DEFAISABLES

        menu = (RACINE / "script/todo/longtest_menu.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("ERPLibre on NixOS: run it", menu)
        self.assertIn("ERPLibre on NixOS: plan only (dry-run)", menu)
        self.assertIn("install_nixos.py", SCRIPTS_DEFAISABLES)

    def test_the_menu_does_not_pass_a_depth(self):
        """Une seule machine : « --depth » n'a pas de sens ici, et le script
        le refuserait."""
        menu = (RACINE / "script/todo/longtest_menu.py").read_text(
            encoding="utf-8"
        )
        bloc = menu.split('if script == "install_nixos.py":')[1][:400]
        self.assertNotIn("--depth", bloc)

    def test_every_label_is_translated(self):
        from script.todo.todo_i18n import TRANSLATIONS

        for cle in (
            "ERPLibre on NixOS: plan only (dry-run)",
            "ERPLibre on NixOS: run it",
            "Where does the install run?",
            "Create a fresh NixOS VM",
            "Use a NixOS machine you already have",
        ):
            with self.subTest(cle=cle):
                self.assertIn(cle, TRANSLATIONS)
                self.assertTrue(TRANSLATIONS[cle].get("fr"))
                self.assertTrue(TRANSLATIONS[cle].get("en"))


class LaCreationDeLaVmEstPrivilegiee(unittest.TestCase):
    """Le dossier des images appartient à root en 755 sur une installation
    ordinaire de libvirt.

    Sans sudo, la CLI s'arrête à l'étape 1 sur « Permission refusée » avant
    d'avoir rien créé : le test ne peut pas tourner du tout, pas même échouer
    utilement. Le menu — le chemin du produit — passe sudo dès que ce n'est
    pas un essai à blanc, et c'est cette forme qui est reprise ici.
    """

    def _module(self):
        sys.path.insert(0, str(RACINE / "long_test"))
        import install_nixos

        return install_nixos

    def test_the_real_run_asks_for_privilege(self):
        mod = self._module()
        vu = {}

        class Fini:
            returncode = 1

        def faux_run(argv, **kw):
            vu["argv"] = argv
            return Fini()

        vrai = mod.subprocess.run
        self.addCleanup(setattr, mod.subprocess, "run", vrai)
        mod.subprocess.run = faux_run
        mod.creer_vm("essai", None, dry_run=False)
        self.assertEqual("sudo", vu["argv"][0])
        self.assertIn("deploy_qemu.py", " ".join(vu["argv"]))

    def test_the_dry_run_asks_for_none(self):
        """Un essai qui n'écrit rien n'a aucune raison de demander un mot de
        passe, et le menu ne le demande pas non plus."""
        mod = self._module()
        vu = []
        vrai = mod.dire
        self.addCleanup(setattr, mod, "dire", vrai)
        mod.dire = lambda texte, journal=None: vu.append(texte)
        nom, uuid = mod.creer_vm("essai", None, dry_run=True)
        self.assertEqual(("essai", ""), (nom, uuid))
        ligne = " ".join(vu)
        self.assertIn("deploy_qemu.py", ligne)
        self.assertNotIn("sudo", ligne)

    def test_its_sibling_does_the_same(self):
        """descente.py crée l'étage 1 de la même façon, et l'oubli y était
        le même : un correctif posé d'un seul côté laisse l'autre au mur."""
        src = (RACINE / "long_test/descente.py").read_text(encoding="utf-8")
        self.assertIn('([] if self.dry_run else ["sudo"]) + [', src)


if __name__ == "__main__":
    unittest.main()
