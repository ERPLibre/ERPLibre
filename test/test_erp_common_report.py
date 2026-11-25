#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Bilan de santé : vérification de l'épinglage et affichage des résultats
(script/erp_common/report).

Ce qui se garde :
- une instance qui n'est pas au commit (à l'image) épinglé est un warn :
  après une montée revenue en arrière, rien d'autre ne le dirait ;
- chaque résultat s'affiche avec sa marque et le libellé que l'ERP donne ;
- un seul fail fait échouer le bilan, des warn seuls ne le font pas.
"""

import sys
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.erp_common import report  # noqa: E402

COMMIT = "0123456789abcdef0123456789abcdef01234567"
AUTRE = "f" * 40


class TestPin(unittest.TestCase):
    def setUp(self):
        self.pin = {
            "commit": COMMIT,
            "docker_image": "docker.io/acme/acme:24.0.0",
        }

    def test_an_instance_at_the_pin_is_ok(self):
        r = report.check_pin({"runtime": "native", "commit": COMMIT}, self.pin)
        self.assertEqual(r, report.Result("pin", "ok", COMMIT[:7]))

    def test_an_instance_behind_the_pin_is_a_warning(self):
        self.pin["commit"] = AUTRE
        r = report.check_pin({"runtime": "native", "commit": COMMIT}, self.pin)
        self.assertEqual(r.level, "warn")
        self.assertIn(AUTRE[:7], r.detail)

    def test_a_container_on_another_image_than_the_pin_is_a_warning(self):
        entree = {
            "runtime": "container",
            "image": "docker.io/acme/acme:23.0.4",
        }
        r = report.check_pin(entree, self.pin)
        self.assertEqual(r.level, "warn")
        self.assertIn("acme:23.0.4", r.detail)
        self.assertIn("acme:24.0.0", r.detail)
        entree["image"] = self.pin["docker_image"]
        self.assertEqual(report.check_pin(entree, self.pin).level, "ok")


class TestAffichage(unittest.TestCase):
    def afficher(self, resultats, libelles):
        lignes = []
        echec = report.show(resultats, libelles, out=lignes.append)
        return echec, lignes

    def test_each_result_shows_its_mark_and_the_erp_label(self):
        libelles = {**report.LABELS, "site": "Site"}
        echec, lignes = self.afficher(
            [
                report.Result("site", "ok", "servi"),
                report.Result("pin", "warn", "en retard"),
            ],
            libelles,
        )
        self.assertFalse(echec)
        self.assertEqual(
            lignes,
            [
                f"  {report.MARKS['ok']} {report.t('Site')}: servi",
                f"  {report.MARKS['warn']} {report.t('Pin')}: en retard",
            ],
        )

    def test_one_failure_fails_the_report(self):
        echec, lignes = self.afficher(
            [
                report.Result("pin", "ok", "a"),
                report.Result("pin", "fail", "no answer"),
                report.Result("pin", "ok", "b"),
            ],
            report.LABELS,
        )
        self.assertTrue(echec)
        self.assertEqual(len(lignes), 3)
        self.assertIn("no answer", lignes[1])

    def test_warnings_alone_are_success(self):
        echec, _lignes = self.afficher(
            [report.Result("pin", "warn", "1 file")], report.LABELS
        )
        self.assertFalse(echec)

    def test_every_level_has_a_mark(self):
        self.assertEqual(set(report.MARKS), set(report.LEVELS))
        self.assertEqual(len(set(report.MARKS.values())), len(report.LEVELS))


if __name__ == "__main__":
    unittest.main()
