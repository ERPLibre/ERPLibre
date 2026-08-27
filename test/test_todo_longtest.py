#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les tests LONGS : qu'ils existent, qu'ils annoncent, et qu'ils ne
polluent pas la suite unitaire.

Un test qui crée dix VM n'a rien à faire dans `test/` : le lanceur unitaire
doit rester lançable en quelques secondes, partout, y compris sur une machine
sans virtualisation. Ce fichier-ci vérifie la frontière, et que l'essai à
blanc du test long dit quelque chose sans rien créer.
"""

import os
import subprocess
import sys
import unittest

sys.argv = ["todo.py"]
from script.todo.todo import TODO  # noqa: E402

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON = os.path.join(RACINE, ".venv.erplibre/bin/python")


class TestLaFrontiere(unittest.TestCase):
    """LongTest est hors de portée du lanceur unitaire, et ce n'est pas un
    rangement de confort."""

    def test_the_unit_runner_does_not_sweep_LongTest(self):
        with open(
            os.path.join(RACINE, "script/test/run_unit_test.sh"),
            encoding="utf-8",
        ) as fh:
            lanceur = fh.read()
        # Le lanceur ne liste que des fichiers de test/ : rien qui parte de
        # LongTest, sinon la suite unitaire créerait des VM.
        self.assertNotIn("LongTest", lanceur)

    def test_the_runner_only_looks_under_test(self):
        """Le lanceur balaie TOUT test/test_*.py depuis qu'une liste de
        préfixes a laissé 2400 tests hors de la suite.

        La frontière n'est donc plus un nom mais un RÉPERTOIRE : ce qui doit
        rester hors de la suite doit vivre ailleurs que dans test/. C'est
        exactement pourquoi LongTest est à la racine."""
        with open(
            os.path.join(RACINE, "script/test/run_unit_test.sh"),
            encoding="utf-8",
        ) as fh:
            lanceur = fh.read()
        self.assertIn("test/test_*.py", lanceur)
        # Aucun chemin du lanceur ne sort de test/ : sinon LongTest y
        # entrerait par la porte de service.
        self.assertNotIn("LongTest", lanceur)

    def test_the_script_is_executable_and_documented(self):
        script = os.path.join(RACINE, "LongTest/deep_proxmox.py")
        self.assertTrue(os.access(script, os.X_OK), "doit être exécutable")
        # La doc est un .base.md : un .md généré se perd au prochain
        # « make doc_markdown ».
        self.assertTrue(
            os.path.exists(os.path.join(RACINE, "LongTest/README.base.md"))
        )


class TestLEssaiABlanc(unittest.TestCase):
    """L'essai à blanc annonce le plan et n'exécute RIEN.

    C'est ce qui rend un test de plusieurs heures relisable avant de le
    lancer : on voit les ressources de chaque étage et les commandes, sans
    créer une machine."""

    @classmethod
    def setUpClass(cls):
        import tempfile

        # HOME temporaire : la suite unitaire tourne souvent, et elle n'a pas
        # à semer un rapport dans ~/.erplibre à chaque passage.
        cls.maison = tempfile.mkdtemp()
        cls.res = subprocess.run(
            [
                PYTHON,
                os.path.join(RACINE, "LongTest/deep_proxmox.py"),
                "--depth",
                "4",
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            timeout=180,
            cwd=RACINE,
            env=dict(os.environ, PYTHONPATH=RACINE, HOME=cls.maison),
        )

    @classmethod
    def tearDownClass(cls):
        import shutil

        shutil.rmtree(cls.maison, ignore_errors=True)

    def test_it_exits_cleanly(self):
        self.assertEqual(self.res.returncode, 0, self.res.stderr[-800:])

    def test_it_announces_the_plan_before_anything(self):
        """Les LIGNES du plan, pas les chiffres.

        La version d'avant cherchait « 1 », « 2 », « 3 », « 4 » dans la
        sortie : l'en-tête « 28 cœurs, 29128 Mo, 138 Go » et l'horodatage du
        journal les fournissent tous. Elle passait même à --depth 1, avec une
        seule ligne de plan — elle ne prouvait rien."""
        import re

        plan = re.findall(
            r"^\s+(\d+)\s+(\d+)\s+(\d+) Mo\s+(\d+) Go\s*$",
            self.res.stdout,
            re.M,
        )
        self.assertEqual([int(p[0]) for p in plan], [1, 2, 3, 4])
        self.assertIn("dry-run", self.res.stdout)

    def test_it_shows_the_commands_it_would_send(self):
        # Une étape affichée est une étape rejouable à la main : c'est ainsi
        # que les pannes de ce module ont été diagnostiquées.
        self.assertIn("qm create", self.res.stdout)
        self.assertIn("install_proxmox.sh", self.res.stdout)

    def test_the_installer_is_run_by_bash_not_sh(self):
        """Le script porte « set -euo pipefail » et un shebang bash.

        Sur Debian /bin/sh est dash, qui répond « set: Illegal option -o
        pipefail » et sort à la PREMIÈRE ligne — vérifié. Lancé par sh, chaque
        étage aurait échoué sur l'installation, à tous les coups."""
        # Sur la LIGNE, pas dans le texte : « bash /tmp/… » contient
        # « sh /tmp/… », donc un assertNotIn naïf échouait sur lui-même.
        lignes = [
            ligne.strip()
            for ligne in self.res.stdout.splitlines()
            if "install_proxmox.sh" in ligne
            and not ligne.strip().startswith("scp")
        ]
        self.assertTrue(lignes)
        for ligne in lignes:
            self.assertTrue(
                ligne.startswith("bash "), f"lancé par autre chose : {ligne}"
            )

    def test_the_first_level_gets_an_ssh_entry(self):
        """La CLI QEMU/KVM n'écrit PAS d'entrée ~/.ssh/config.

        Sans elle, « ssh deep-pve-1 » rend « Name or service not known » et la
        descente attendait son plein délai avant de conclure « jamais
        joignable » — sur une VM qui répondait parfaitement à son adresse.
        Trouvé au premier lancement réel, pas par l'attaque."""
        import inspect
        import sys as _sys

        _sys.path.insert(0, os.path.join(RACINE, "LongTest"))
        import deep_proxmox

        src = inspect.getsource(deep_proxmox.Descente.creer_etage1)
        self.assertIn("_write_ssh_config_entry", src)
        self.assertIn("_qemu_vm_ip_now", src)
        # Et une VM sans adresse n'est pas déclarée prête.
        self.assertIn("créée mais sans adresse", src)

    def test_the_dry_run_claims_nothing_reached(self):
        """Le rapport d'un essai à blanc était indiscernable d'une réussite —
        JSON compris — et « --detruire » s'en servait."""
        import glob
        import json

        fichiers = glob.glob(
            os.path.join(self.maison, ".erplibre/longtest/*.json")
        )
        self.assertEqual(len(fichiers), 1, fichiers)
        self.assertIn("dryrun", fichiers[0])
        with open(fichiers[0], encoding="utf-8") as fh:
            rapport = json.load(fh)
        self.assertTrue(rapport["dry_run"])
        self.assertEqual(rapport["atteinte"], 0)
        self.assertTrue(all(not e["ok"] for e in rapport["etages"]))

    def test_the_first_level_is_wide_and_the_others_are_not(self):
        # 12 vCPU au quatrième étage ont gelé un noyau invité ; deux
        # avançaient.
        # Par expression exacte : la ligne « machine : … Mo … Go » du haut
        # contient les mêmes unités et décalait l'index d'un cran.
        import re

        plan = re.findall(
            r"^\s+(\d+)\s+(\d+)\s+(\d+) Mo\s+(\d+) Go\s*$",
            self.res.stdout,
            re.M,
        )
        self.assertEqual(len(plan), 4, plan)
        niveaux = {int(n): int(v) for n, v, _r, _d in plan}
        self.assertGreater(niveaux[1], 1, "le premier étage peut être large")
        for niveau in (2, 3, 4):
            self.assertEqual(niveaux[niveau], 2, f"étage {niveau}")


class TestDefaireSansEffacerAutreChose(unittest.TestCase):
    """« --detruire » effaçait par SOUS-CHAÎNE de nom, dans le mauvais ordre,
    sans confirmation et sans honorer --dry-run.

    Quatre défauts trouvés en attaquant le code écrit, chacun capable
    d'emporter une machine qui n'appartient pas au test. « qm destroy --purge »
    emporte les disques ET les entrées de sauvegarde."""

    def setUp(self):
        sys.path.insert(0, os.path.join(RACINE, "LongTest"))
        import deep_proxmox

        self.dp = deep_proxmox

    def test_the_deepest_level_goes_first(self):
        """Le tri comptait les « + » de l'alias — or alias_etage remplace le
        « + » du parent par un « - », donc chaque alias en portait
        exactement UN. Le tri ne triait rien, et la destruction partait du
        plus HAUT : « qm destroy --purge » sur l'étage 2 emportait le disque
        contenant les étages 3 et suivants."""
        rapport = {
            "etages": [
                {"niveau": 2, "vmid": 100, "parent_alias": "a"},
                {"niveau": 4, "vmid": 100, "parent_alias": "c"},
                {"niveau": 3, "vmid": 100, "parent_alias": "b"},
            ]
        }
        niveaux = [n for n, _p, _v, _nom in self.dp.a_defaire(rapport)]
        self.assertEqual(niveaux, [4, 3, 2])

    def test_a_level_without_a_vmid_is_not_guessed(self):
        # Un étage abandonné avant « qm create » n'a rien créé : ne rien
        # inventer à sa place.
        rapport = {"etages": [{"niveau": 2}, {"niveau": 3, "vmid": 101}]}
        self.assertEqual(len(self.dp.a_defaire(rapport)), 0)

    def test_the_alias_chain_really_flattens_the_plus(self):
        # La cause du tri mort, énoncée pour qu'on ne la réintroduise pas.
        alias, precedent = "deep-pve-1", "deep-pve-1"
        for niveau in (2, 3, 4):
            alias = self.dp.alias_etage(niveau, precedent)
            precedent = alias
        self.assertEqual(alias.count("+"), 1, alias)

    def test_an_exact_name_is_required(self):
        """Le filtre était « NOM_BASE in name » : une VM de labo appelée
        « deep-pve-lab » sur un hyperviseur de production tombait dedans."""
        import inspect

        src = inspect.getsource(self.dp.detruire_une)
        self.assertIn("!= nom", src)
        self.assertNotIn("in presentes[vmid]", src)

    def test_dry_run_reports_are_never_used_to_destroy(self):
        """Un rapport d'essai à blanc n'a rien créé : s'en servir ferait
        détruire d'après un plan."""
        import inspect

        src = inspect.getsource(self.dp.dernier_rapport)
        self.assertIn('rapport.get("dry_run")', src)

    def test_destruction_honours_dry_run_and_asks(self):
        import inspect

        src = inspect.getsource(self.dp.detruire)
        self.assertIn("dry_run", src)
        # Une confirmation explicite, pas un « o/N » : le menu lançait cette
        # option d'une seule touche.
        self.assertIn("OUI", src)
        principal = inspect.getsource(self.dp.principal)
        self.assertIn("dry_run=args.dry_run", principal)


class TestLeMenu(unittest.TestCase):
    def test_the_mixin_is_wired_into_TODO(self):
        todo = TODO.__new__(TODO)
        self.assertTrue(hasattr(todo, "prompt_execute_longtest"))

    def test_the_script_is_found_from_the_repository_root(self):
        todo = TODO.__new__(TODO)
        ancien = os.getcwd()
        try:
            os.chdir(RACINE)
            self.assertTrue(todo._longtest_script("deep_proxmox.py"))
            self.assertFalse(todo._longtest_script("nexiste-pas.py"))
        finally:
            os.chdir(ancien)

    def test_the_test_menu_offers_it(self):
        import inspect

        src = inspect.getsource(TODO.prompt_execute_test)
        self.assertIn("prompt_execute_longtest", src)
        self.assertIn("Long tests", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
