#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'aperçu et le déploiement sortent de la même fonction — et pourtant ils
diffèrent. Voici de combien, et le contrat qui l'empêche de grandir.

Le point de passage unique se déclare tel : les deux interfaces produisent
la même spec, donc la même commande, « et c'est ce qui rend leur divergence
vérifiable par un test ». Mais l'argv N'EST PAS identique, par construction
et à bon droit : l'aperçu ne s'élève pas, n'attend aucune adresse, et
demande au script appelé de ne rien faire.

TROIS JETONS RETIRÉS, UN AJOUTÉ. L'écart est volontaire et documenté ; ce
qui manquait est une épreuve qui le BORNE. Sans elle, chaque option nouvelle
peut s'ajouter d'un seul côté, et l'aperçu cesse de montrer ce qui sera
lancé sans que rien ne tombe.

L'épreuve retire les quatre jetons connus et exige que le RESTE soit
identique, dans l'ordre : c'est ce qui distingue « l'écart est celui-là » de
« il y a un écart quelque part ».

Rien ici ne touche à une machine : le constructeur ne fait aucune I/O.
"""

import os
import sys
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

sys.argv = ["todo.py"]

from script.todo.deploy_form_lib import build_spec  # noqa: E402
from script.todo.todo import TODO  # noqa: E402

FORM = {
    "res_label": "x1",
    "ssh_key": "",
    "install": None,
    "add_ssh_config": False,
    "parallelism": 1,
}

VM_UNE = {
    "distro": "ubuntu",
    "version": "24.04",
    "arch": "amd64",
    "name": "essai",
    "ram": 4096,
    "vcpus": 2,
    "disk": "30G",
}

# Ce que le VRAI chemin porte et que l'aperçu ne porte pas. Chacun a sa
# raison : l'aperçu ne s'élève pas, il n'attend aucune adresse, et il ne
# confirme rien puisqu'il ne fait rien.
RETIRES_A_BLANC = ("sudo", "--no-wait-ip", "-y")

# Ce que l'aperçu ajoute : il demande au script appelé de n'agir pas non
# plus. C'est la MÊME position que « -y » dans la commande.
AJOUTE_A_BLANC = ("--dry-run",)


def menu():
    return TODO.__new__(TODO)


def spec_de(**extra):
    return build_spec([VM_UNE], [], dict(FORM, **extra))


class TestLApercuMontreCeQueLaSpecPorte(unittest.TestCase):
    """Une spec réduite perdait une douzaine de champs, et l'aperçu
    affirmait montrer ce qui serait lancé."""

    def apercu(self, **extra):
        import io as tampon_io
        from contextlib import redirect_stdout

        spec = spec_de(**extra)
        tampon = tampon_io.StringIO()
        with redirect_stdout(tampon):
            menu()._qemu_print_dry_run(spec)
        return tampon.getvalue()

    def test_what_it_prints_is_what_the_gate_returns(self):
        """L'invariant qui ne peut pas se tromper sur l'orthographe d'une
        option : la ligne imprimée EST l'argv de la porte, mot pour mot."""
        import shlex

        spec = spec_de(timezone="Etc/UTC", gpu3d=True, git_name="Banc")
        attendu = menu()._qemu_deploy_parts_for(VM_UNE, spec, dry_run=True)
        vu = self.apercu(timezone="Etc/UTC", gpu3d=True, git_name="Banc")
        lignes = [l.strip() for l in vu.splitlines() if "deploy_qemu" in l]
        self.assertEqual(1, len(lignes), vu)
        self.assertEqual(attendu, shlex.split(lignes[0]))

    def test_the_fields_a_reduced_spec_lost_are_back(self):
        """Chacun était perdu, un par un. Les noms d'option sont ceux que
        le constructeur écrit, pas ceux qu'on croit."""
        vu = self.apercu(
            timezone="Etc/UTC",
            desktop="gnome",
            gpu3d=True,
            git_name="Banc",
            git_email="banc@exemple.invalid",
        )
        for attendu in (
            "--timezone Etc/UTC",
            "--desktop",
            "--gpu on",
            "--git-name Banc",
            "--git-email banc@exemple.invalid",
        ):
            with self.subTest(attendu=attendu):
                self.assertIn(attendu, vu)

    def test_a_reduced_spec_would_carry_none_of_them(self):
        """Contrôle négatif : ce que l'aperçu fabriquait avant. Sans lui,
        l'épreuve d'à côté pourrait passer sur un argv qui les porte pour
        une autre raison."""
        import io as tampon_io
        from contextlib import redirect_stdout

        reduite = {
            "vms": [VM_UNE],
            "ssh_key": "",
        }
        tampon = tampon_io.StringIO()
        with redirect_stdout(tampon):
            menu()._qemu_print_dry_run(reduite)
        vu = tampon.getvalue()
        for absent in ("--timezone", "--git-name", "--gpu on"):
            with self.subTest(absent=absent):
                self.assertNotIn(absent, vu)

    def test_a_spec_without_machines_prints_no_command(self):
        """Elle ne doit pas lever : l'aperçu se demande avant tout choix."""
        import io as tampon_io
        from contextlib import redirect_stdout

        tampon = tampon_io.StringIO()
        with redirect_stdout(tampon):
            menu()._qemu_print_dry_run({})
        self.assertNotIn("deploy_qemu", tampon.getvalue())

    def test_the_preview_shows_one_line_per_machine(self):
        vu = self.apercu()
        lignes = [l for l in vu.splitlines() if "deploy_qemu" in l]
        self.assertEqual(1, len(lignes), vu)

    def test_it_takes_the_spec_and_not_a_list_of_machines(self):
        """La signature EST l'invariant : recevoir une liste laisserait
        refabriquer une spec réduite à l'intérieur."""
        import inspect

        signature = inspect.signature(TODO._qemu_print_dry_run)
        self.assertEqual(["self", "spec"], list(signature.parameters))


class TestChaqueVoieTransmetLaSpecEntiere(unittest.TestCase):
    """Deux appels, deux fautes distinctes : l'un jouait l'aperçu AVANT la
    collecte des options — il n'y avait rien à montrer, par construction —
    et l'autre avait la spec complète en main sans la transmettre."""

    @staticmethod
    def _corps(nom):
        import ast

        chemin = os.path.join(RACINE, "script", "todo", "qemu_deploy.py")
        with open(chemin, encoding="utf-8") as fichier:
            arbre = ast.parse(fichier.read())
        trouves = [
            noeud
            for noeud in ast.walk(arbre)
            if isinstance(noeud, ast.FunctionDef) and noeud.name == nom
        ]
        assert len(trouves) == 1, nom
        return trouves[0]

    @staticmethod
    def _rang(corps, attribut):
        import ast

        for noeud in ast.walk(corps):
            if (
                isinstance(noeud, ast.Call)
                and isinstance(noeud.func, ast.Attribute)
                and noeud.func.attr == attribut
            ):
                return noeud.lineno
        return None

    def test_the_line_path_collects_the_options_first(self):
        """Avant la collecte, l'aperçu n'a rien à montrer et fabrique une
        spec réduite : l'ordre EST la correction."""
        corps = self._corps("_qemu_deploy")
        collecte = self._rang(corps, "_qemu_collect_options_cli")
        apercu = self._rang(corps, "_qemu_print_dry_run")
        self.assertIsNotNone(collecte)
        self.assertIsNotNone(apercu)
        self.assertLess(collecte, apercu)

    def test_no_caller_hands_over_only_the_machines(self):
        """« spec["vms"] » à la place de « spec » est une perte pure, et
        elle ne se voit sur aucun écran."""
        import ast

        chemin = os.path.join(RACINE, "script", "todo", "qemu_deploy.py")
        with open(chemin, encoding="utf-8") as fichier:
            arbre = ast.parse(fichier.read())
        appels = [
            noeud
            for noeud in ast.walk(arbre)
            if isinstance(noeud, ast.Call)
            and isinstance(noeud.func, ast.Attribute)
            and noeud.func.attr == "_qemu_print_dry_run"
        ]
        self.assertEqual(2, len(appels), "les deux voies")
        for appel in appels:
            self.assertEqual(1, len(appel.args))
            self.assertIsInstance(appel.args[0], ast.Name)
            self.assertEqual("spec", appel.args[0].id)


class TestLEcartLiciteEstBorne(unittest.TestCase):
    def deux_argv(self, spec=None):
        todo = menu()
        spec = spec if spec is not None else spec_de()
        return (
            todo._qemu_deploy_parts_for(VM_UNE, spec, dry_run=False),
            todo._qemu_deploy_parts_for(VM_UNE, spec, dry_run=True),
        )

    def test_the_gap_is_exactly_the_four_tokens_and_nothing_else(self):
        """L'assertion qui BORNE : le reste doit être identique, dans
        l'ordre. « Il y a un écart quelque part » ne dit rien."""
        vrai, blanc = self.deux_argv()
        self.assertEqual(
            [jeton for jeton in vrai if jeton not in RETIRES_A_BLANC],
            [jeton for jeton in blanc if jeton not in AJOUTE_A_BLANC],
        )

    def test_every_named_token_is_really_in_play(self):
        """Contrôle positif : un jeton nommé mais absent ferait passer
        l'épreuve d'à côté en n'excluant rien."""
        vrai, blanc = self.deux_argv()
        for jeton in RETIRES_A_BLANC:
            with self.subTest(jeton=jeton):
                self.assertIn(jeton, vrai)
                self.assertNotIn(jeton, blanc)
        for jeton in AJOUTE_A_BLANC:
            with self.subTest(jeton=jeton):
                self.assertIn(jeton, blanc)
                self.assertNotIn(jeton, vrai)

    def test_the_preview_never_elevates(self):
        """S'élever pour montrer une commande demanderait un mot de passe
        pour ne rien faire."""
        _vrai, blanc = self.deux_argv()
        self.assertNotIn("sudo", blanc)
        self.assertFalse(blanc[0].endswith("sudo"), blanc[0])

    def test_the_real_run_elevates_first(self):
        """Ailleurs qu'en tête, « sudo » n'élèverait pas la commande."""
        vrai, _blanc = self.deux_argv()
        self.assertEqual("sudo", vrai[0])

    def test_the_builder_is_reached_only_through_the_single_gate(self):
        """Le point de passage est unique parce que le constructeur ne
        s'atteint que par lui. Un appelant qui court-circuiterait la porte
        n'aurait ni le refus de backend, ni les drapeaux de confinement, et
        son aperçu divergerait sans que rien ne tombe.

        Les épreuves, elles, ont le droit de l'appeler directement : elles
        éprouvent le constructeur, elles ne déploient pas."""
        import ast

        chemin = os.path.join(RACINE, "script", "todo", "qemu_deploy.py")
        with open(chemin, encoding="utf-8") as fichier:
            arbre = ast.parse(fichier.read())
        porteurs = []
        for noeud in ast.walk(arbre):
            if not isinstance(noeud, ast.FunctionDef):
                continue
            for interne in ast.walk(noeud):
                if (
                    isinstance(interne, ast.Call)
                    and isinstance(interne.func, ast.Attribute)
                    and interne.func.attr == "_qemu_build_deploy_parts"
                ):
                    porteurs.append(noeud.name)
        self.assertEqual(["_qemu_deploy_parts_for"], porteurs)

    def test_the_gap_does_not_grow_with_what_the_spec_carries(self):
        """Le contrôle qui compte pour la suite : une spec riche ne doit
        pas creuser l'écart. Chaque champ nouveau atteint les DEUX argv ou
        aucun."""
        riche = spec_de(
            timezone="UTC",
            desktop="gnome",
            vm_tools=("git",),
            gpu3d=True,
            git_name="Banc",
            git_email="banc@exemple.invalid",
            posture="open",
        )
        vrai, blanc = self.deux_argv(riche)
        self.assertEqual(
            [jeton for jeton in vrai if jeton not in RETIRES_A_BLANC],
            [jeton for jeton in blanc if jeton not in AJOUTE_A_BLANC],
        )


if __name__ == "__main__":
    unittest.main()
