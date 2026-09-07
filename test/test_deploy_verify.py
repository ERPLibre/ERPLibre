#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce qu'un déploiement affirme, COUCHE PAR COUCHE — la station d'abord.

Un code unique perd ce qui sert le plus, et deux faits sur la même station
n'ont pas la même gravité : sans le groupe libvirt rien ne se déploie, sans
accélération tout se déploie encore — simplement émulé.

Les deux entrées se passent en paramètre : être hors du groupe ne se simule
pas en y étant, et une station sans accélération ne se fabrique pas. Rien
ici ne lance de sous-processus, rien n'exige de privilège.
"""

import os
import sys
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

from script.todo import deploy_verify as V  # noqa: E402
from script.todo import devstack_report as R  # noqa: E402
from script.todo import host_os  # noqa: E402


class TestLesDeuxGravites(unittest.TestCase):
    def couches(self, groupe=(True, True), kvm=True):
        return V.host_layers(groupe=groupe, kvm=kvm)

    def test_a_station_that_can_drive_and_accelerate_is_green(self):
        self.assertEqual(R.DS_OK, R.aggregate_layers(self.couches()))

    def test_without_the_group_nothing_deploys(self):
        """Le suivi d'installation tourne DÉTACHÉ, sans terminal : il ne
        peut répondre à aucune demande de mot de passe."""
        self.assertEqual(
            R.DS_ERR, R.aggregate_layers(self.couches(groupe=(False, False)))
        )

    def test_without_acceleration_everything_still_deploys(self):
        """Une lenteur n'est pas une panne : rendre ERR ici ferait refuser
        un hôte qui marche."""
        codes = [c.code for c in self.couches(kvm=False)]
        self.assertIn(R.DS_SKIP, codes)
        self.assertNotIn(R.DS_ERR, codes)

    def test_a_session_older_than_the_group_is_its_own_case(self):
        """Les groupes d'un processus sont figés à l'ouverture de session :
        proposer un usermod déjà fait envoie corriger ce qui l'est."""
        declaree = self.couches(groupe=(True, False))
        absente = self.couches(groupe=(False, False))
        self.assertEqual(R.DS_ERR, declaree[0].code)
        self.assertNotEqual(declaree[0].detail, absente[0].detail)
        self.assertNotEqual(declaree[0].remedy, absente[0].remedy)

    def test_every_failure_says_what_to_do(self):
        for groupe in ((True, False), (False, False)):
            for kvm in (True, False):
                for couche in self.couches(groupe=groupe, kvm=kvm):
                    if couche.code == R.DS_OK:
                        continue
                    with self.subTest(groupe=groupe, kvm=kvm):
                        self.assertTrue(couche.remedy)

    def test_both_facts_are_always_reported(self):
        """Taire celui qui va bien laisserait croire qu'il n'a pas été
        regardé — et un bloc muet se lit comme « tout va bien »."""
        for groupe in ((True, True), (True, False), (False, False)):
            for kvm in (True, False):
                with self.subTest(groupe=groupe, kvm=kvm):
                    self.assertEqual(
                        2, len(self.couches(groupe=groupe, kvm=kvm))
                    )

    def test_every_layer_is_in_the_closed_vocabulary(self):
        for couche in self.couches(groupe=(False, False), kvm=False):
            self.assertIn(couche.layer, R.LAYERS)

    def test_it_composes_and_does_not_probe(self):
        """Une deuxième mesure à côté de la première est ce qui les fait
        diverger, et c'est le chemin recopié qui dérive en silence."""
        import ast

        chemin = os.path.join(RACINE, "script", "todo", "deploy_verify.py")
        with open(chemin, encoding="utf-8") as fichier:
            arbre = ast.parse(fichier.read())
        importes = set()
        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.Import):
                importes.update(a.name for a in noeud.names)
            elif isinstance(noeud, ast.ImportFrom) and noeud.module:
                importes.add(noeud.module)
        self.assertNotIn("subprocess", importes)
        appels = [
            noeud.func.id
            for noeud in ast.walk(arbre)
            if isinstance(noeud, ast.Call) and isinstance(noeud.func, ast.Name)
        ]
        for interdit in ("print", "input", "open"):
            self.assertNotIn(interdit, appels)


class TestLaRegleDeLAcceleration(unittest.TestCase):
    """La présence suffit HORS root : libvirt tourne en root et se moque
    de notre appartenance au groupe kvm."""

    def test_an_absent_node_is_never_available(self):
        vrai = host_os.CHEMIN_KVM
        host_os.CHEMIN_KVM = "/n-existe-pas.invalid/kvm"
        self.addCleanup(setattr, host_os, "CHEMIN_KVM", vrai)
        self.assertFalse(host_os.kvm_available(euid=0))
        self.assertFalse(host_os.kvm_available(euid=1000))

    def test_presence_is_enough_when_we_are_not_root(self):
        """Tester nos propres droits ferait crier « pas de KVM » à un
        utilisateur simplement hors du groupe, dont les machines
        s'accéléreraient très bien."""
        vrai = host_os.CHEMIN_KVM
        host_os.CHEMIN_KVM = os.devnull
        self.addCleanup(setattr, host_os, "CHEMIN_KVM", vrai)
        self.assertTrue(host_os.kvm_available(euid=1000))

    def test_as_root_the_access_is_what_decides(self):
        """Un nœud présent mais illisible donne une émulation intégrale,
        sans que rien ne le signale."""
        import tempfile

        with tempfile.NamedTemporaryFile() as fichier:
            os.chmod(fichier.name, 0o000)
            vrai = host_os.CHEMIN_KVM
            host_os.CHEMIN_KVM = fichier.name
            self.addCleanup(setattr, host_os, "CHEMIN_KVM", vrai)
            lisible = os.access(fichier.name, os.R_OK | os.W_OK)
            self.assertEqual(lisible, host_os.kvm_available(euid=0))
            self.assertTrue(host_os.kvm_available(euid=1000))

    def test_the_capability_and_the_layer_agree_here(self):
        """La couche d'accélération est la SECONDE : la première dit le
        groupe, et les confondre ferait passer l'épreuve sur un hôte où
        l'une des deux va bien."""
        capacite = [c for c in host_os.capabilities() if c.name == "kvm"][0]
        couche = V.host_layers(groupe=(True, True))[1]
        self.assertEqual(capacite.present, couche.code == R.DS_OK)

    def test_and_they_read_it_through_the_same_function(self):
        """Elles ne diffèrent QUE sous root, sur un nœud présent et
        illisible — un cas qu'une épreuve sans privilège ne peut pas
        montrer. L'invariant se tient donc sur l'ARBRE : la capacité passe
        par la règle, elle ne relit pas le système de fichiers."""
        import ast

        chemin = os.path.join(RACINE, "script", "todo", "host_os.py")
        with open(chemin, encoding="utf-8") as fichier:
            arbre = ast.parse(fichier.read())
        corps = [
            noeud
            for noeud in ast.walk(arbre)
            if isinstance(noeud, ast.FunctionDef)
            and noeud.name == "capabilities"
        ][0]
        appels = [
            noeud.func.id
            for noeud in ast.walk(corps)
            if isinstance(noeud, ast.Call) and isinstance(noeud.func, ast.Name)
        ]
        self.assertIn("kvm_available", appels)
        attributs = [
            f"{getattr(n.func.value, 'id', '')}.{n.func.attr}"
            for n in ast.walk(corps)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        ]
        self.assertNotIn("path.exists", attributs)


if __name__ == "__main__":
    unittest.main()
