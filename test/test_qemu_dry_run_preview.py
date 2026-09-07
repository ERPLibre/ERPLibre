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
