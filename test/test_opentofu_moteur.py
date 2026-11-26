#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'interface Moteur et le plan commun."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from script.opentofu import moteur as mo  # noqa: E402


class TestMoteur(unittest.TestCase):
    def test_formater_plan_quatre_actions(self):
        plan = [
            mo.Changement("creer", "a", "proxmox_virtual_environment_vm"),
            mo.Changement(
                "modifier",
                "b",
                "proxmox_virtual_environment_vm",
                [("ram", 2048, 4096)],
            ),
            mo.Changement("remplacer", "c", "r"),
            mo.Changement("detruire", "d", "r"),
        ]
        lignes = mo.formater_plan(plan)
        self.assertTrue(lignes[0].startswith("+ créer a"))
        self.assertTrue(lignes[1].startswith("~ modifier b"))
        self.assertEqual(lignes[2], "    ram : 2048 → 4096")
        self.assertTrue(lignes[3].startswith("± remplacer c"))
        self.assertTrue(lignes[4].startswith("- détruire d"))
        self.assertEqual(len(lignes), 5)

    def test_plan_vide(self):
        self.assertEqual(mo.formater_plan([]), ["Aucun changement."])

    def test_est_destructeur(self):
        self.assertFalse(mo.est_destructeur([mo.Changement("creer", "a", "r")]))
        self.assertTrue(mo.est_destructeur([mo.Changement("remplacer", "a", "r")]))
        self.assertTrue(mo.est_destructeur([mo.Changement("detruire", "a", "r")]))

    def test_action_inconnue(self):
        with self.assertRaises(ValueError):
            mo.Changement("x", "a", "r")

    def test_moteur_inconnu(self):
        with self.assertRaises(KeyError) as c:
            mo.moteur_pour({"moteur": "x"})
        self.assertIn("x", str(c.exception))

    def test_moteur_abstrait(self):
        with self.assertRaises(TypeError):
            mo.Moteur()

    def test_enregistrer_et_instancier(self):
        class Faux(mo.Moteur):
            nom = "faux"

            def __init__(self, **kw):
                self.kw = kw

            def disponible(self):
                return True, ""

            def preparer(self, spec):
                return mo.Resultat(True)

            def planifier(self, spec, journal):
                return mo.Resultat(True), []

            def appliquer(self, spec, journal):
                return mo.Resultat(True)

            def detruire(self, spec, journal):
                return mo.Resultat(True)

            def etat(self, spec):
                return []

            def sorties(self, spec):
                return {}

        mo.enregistrer("faux", Faux)
        try:
            m = mo.moteur_pour({"moteur": "faux"}, a=1)
            self.assertEqual(m.kw, {"a": 1})
        finally:
            mo._REGISTRE.pop("faux")


if __name__ == "__main__":
    unittest.main()
