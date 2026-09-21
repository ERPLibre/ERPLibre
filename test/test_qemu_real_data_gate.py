#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La règle d'or, enfin atteignable : données réelles et posture.

Le vocabulaire existait, le verdict était écrit, et il n'était rendu à
personne : la clé n'avait aucun ÉCRIVAIN et la règle aucun APPELANT. Une
règle qu'on ne peut pas déclencher ne protège rien.

TROIS CHAMPS, ET AUCUN NE SE DÉDUIT DES AUTRES. Où le code est posé, ce que
le réseau atteint, ce que la machine porte. Les confondre produit les deux
accidents symétriques : une maquette qui parle à tout l'Internet parce
qu'elle n'est « pas en production », et une machine de production confinée
au point de ne plus pouvoir se mettre à jour.

LE REFUS ARRIVE AVANT QUE LA MACHINE EXISTE, au seul point que les deux
interfaces traversent. C'est le seul moment où il ne coûte rien.

Aujourd'hui une SEULE posture accepte des données réelles, et ce n'est pas
la plus stricte : la stricte borne ses destinations mais rien n'applique
encore sa politique. Cette épreuve le dira en tombant.
"""

import os
import sys
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

sys.argv = ["todo.py"]

from script.posture import registry as R  # noqa: E402
from script.posture import spec as S  # noqa: E402
from script.todo.deploy_form_lib import build_spec  # noqa: E402
from script.todo.todo import TODO  # noqa: E402
from script.vm import backend as VM  # noqa: E402

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


def spec_de(**extra):
    return build_spec([VM_UNE], [], dict(FORM, **extra))


class TestLaCleATrouveUnEcrivain(unittest.TestCase):
    def test_a_mute_spec_carries_no_real_data(self):
        """Le doute penche du côté qui ne promet rien : l'inverse ferait
        d'un formulaire incomplet une machine qu'on croit protégée."""
        self.assertFalse(S.real_data(spec_de()))

    def test_what_the_form_says_reaches_the_spec(self):
        self.assertTrue(S.real_data(spec_de(real_data=True)))

    def test_it_reads_back_through_the_key_that_names_it(self):
        """La clé est nommée à un seul endroit ; l'écrire à la main chez
        chaque consommateur devient une faute de frappe silencieuse."""
        self.assertIn(S.REAL_DATA_KEY, spec_de(real_data=True))

    def test_it_is_independent_of_where_the_code_is_installed(self):
        """« prod » ne dit QUE le chemin d'installation."""
        avec = spec_de(
            real_data=True,
            install={
                "branch": "x",
                "prod": False,
                "label": "x",
                "cmd": "x",
                "monitor": False,
            },
        )
        self.assertTrue(S.real_data(avec))

    def test_it_is_independent_of_the_posture(self):
        for nom in R.posture_names():
            with self.subTest(posture=nom):
                self.assertTrue(
                    S.real_data(spec_de(real_data=True, posture=nom))
                )


class TestLeRefusArriveAvantLaMachine(unittest.TestCase):
    """Au point de passage unique : les deux interfaces le traversent."""

    def parts(self, **extra):
        return TODO.__new__(TODO)._qemu_deploy_parts_for(
            VM_UNE, spec_de(**extra), dry_run=True
        )

    def test_real_data_on_an_unconfined_posture_is_refused(self):
        with self.assertRaises(VM.VmBackendError) as pris:
            self.parts(real_data=True, posture="open")
        self.assertIn(S.REAL_DATA_UNCONFINED, str(pris.exception))

    def test_the_strict_posture_is_refused_too_and_that_is_the_point(self):
        """Elle borne ses destinations, et rien n'applique encore sa
        politique. Le jour où quelque chose l'applique, cette épreuve
        tombe — c'est le compteur du travail."""
        self.assertFalse(R.allows_real_data(R.get_posture("paranoid")))
        with self.assertRaises(VM.VmBackendError):
            self.parts(real_data=True, posture="paranoid")

    def test_the_only_posture_that_confines_goes_through(self):
        """Contrôle positif : tout refuser ne protégerait rien, cela
        empêcherait seulement de déployer."""
        self.assertTrue(self.parts(real_data=True, posture="local-only"))

    def test_exactly_one_posture_accepts_real_data_today(self):
        acceptees = [
            nom
            for nom in R.posture_names()
            if R.allows_real_data(R.get_posture(nom))
        ]
        self.assertEqual(["local-only"], acceptees)

    def test_an_unknown_posture_is_refused_and_never_falls_back(self):
        """Replier sur la plus libre déploierait en sortie libre un spec
        qui demandait du confinement — le sens inverse de la demande."""
        with self.assertRaises(VM.VmBackendError) as pris:
            self.parts(posture="restricted")
        self.assertIn(S.UNKNOWN_POSTURE, str(pris.exception))

    def test_a_deployment_without_real_data_is_untouched(self):
        """La plupart des déploiements sont là, et ne doivent rien payer."""
        for nom in R.posture_names():
            with self.subTest(posture=nom):
                self.assertTrue(self.parts(posture=nom))

    def test_the_refusal_names_both_halves_of_the_couple(self):
        """Un refus qui ne nomme qu'une moitié envoie corriger la mauvaise."""
        with self.assertRaises(VM.VmBackendError) as pris:
            self.parts(real_data=True, posture="open")
        dit = str(pris.exception)
        self.assertIn("open", dit)
        self.assertIn("True", dit)

    def test_the_rule_is_checked_at_the_single_gate(self):
        """Ailleurs, une des deux interfaces la contournerait."""
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
                    and interne.func.attr == "check"
                    and getattr(interne.func.value, "id", "") == "posture_spec"
                ):
                    porteurs.append(noeud.name)
        self.assertEqual(["_qemu_deploy_parts_for"], porteurs)


if __name__ == "__main__":
    unittest.main()
