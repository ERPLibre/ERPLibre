#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Acquérir l'outil : version épinglée, somme vérifiée, refus par défaut.

Ce qu'on refuse de faire est le sujet. Demander « la dernière version » à une
forge, la télécharger sans authentifier la réponse et l'exécuter, c'est
confier à quiconque se place sur le trajet le droit de choisir ce qui tourne
sur la machine — un binaire qui lancera ensuite des VM et recevra des
secrets.

Chaque épreuve de refus est doublée d'un contrôle positif : un mécanisme qui
refuse TOUT passerait la moitié de ce fichier sans rien protéger.
"""

import hashlib
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

from script.vm import lima_install as I  # noqa: E402


class TestCeQuiNeSInstallePas(unittest.TestCase):
    def test_latest_is_refused(self):
        """Il désigne une chose différente à chaque appel : il n'y a rien à
        comparer, donc rien à vérifier."""
        for mot in ("latest", "LATEST", "main", "master", "", "   "):
            with self.subTest(version=mot):
                plan, raison = I.plan(mot, "macos", "arm64")
                self.assertIsNone(plan)
                self.assertIn(raison, (I.UNPINNED, I.UNKNOWN_RELEASE))

    def test_latest_is_refused_even_when_someone_pinned_it(self):
        """La garde porte sur le MOT, et non sur l'absence de la table. Un
        « latest » qu'on aurait épinglé désignerait quand même une archive
        différente à chaque publication — la somme deviendrait fausse sans
        que personne n'ait rien changé."""
        with patch.dict(
            I.RELEASES, {"latest": {("Darwin", "arm64"): "a" * 64}}
        ):
            plan, raison = I.plan("latest", "macos", "arm64")
        self.assertIsNone(plan)
        self.assertEqual(I.UNPINNED, raison)

    def test_a_version_absent_from_the_table_is_refused(self):
        plan, raison = I.plan("1.2.3", "macos", "arm64")
        self.assertIsNone(plan)
        self.assertEqual(I.UNKNOWN_RELEASE, raison)

    def test_an_unknown_system_or_arch_is_refused(self):
        for systeme, arch in (("plan9", "arm64"), ("macos", "vax")):
            with self.subTest(systeme=systeme, arch=arch):
                plan, raison = I.plan("1.2.3", systeme, arch)
                self.assertIsNone(plan)
                self.assertEqual(I.UNKNOWN_TARGET, raison)

    def test_every_refusal_is_in_the_closed_vocabulary(self):
        self.assertTrue(I.REFUSALS)
        cas = (
            ("latest", "macos", "arm64"),
            ("1.2.3", "macos", "arm64"),
            ("1.2.3", "plan9", "arm64"),
        )
        for version, systeme, arch in cas:
            with self.subTest(version=version):
                self.assertIn(I.plan(version, systeme, arch)[1], I.REFUSALS)


class TestCeQuiSInstalleQuandCEstEpingle(unittest.TestCase):
    """Contrôle positif : refuser tout ne protégerait rien."""

    SOMME = "a" * 64

    def test_a_pinned_version_yields_a_plan(self):
        with patch.dict(
            I.RELEASES, {"1.2.3": {("Darwin", "arm64"): self.SOMME}}
        ):
            plan, raison = I.plan("1.2.3", "macos", "arm64")
        self.assertEqual(I.OK, raison)
        self.assertEqual("1.2.3", plan.version)
        self.assertEqual(self.SOMME, plan.sha256)
        self.assertIn("v1.2.3", plan.url)
        self.assertIn("Darwin-arm64", plan.url)

    def test_the_leading_v_is_accepted_and_normalised(self):
        with patch.dict(
            I.RELEASES, {"1.2.3": {("Darwin", "arm64"): self.SOMME}}
        ):
            plan, raison = I.plan("v1.2.3", "macos", "arm64")
        self.assertEqual(I.OK, raison)
        self.assertEqual("1.2.3", plan.version)

    def test_aarch64_and_arm64_name_the_same_archive(self):
        """Deux mots pour une architecture ; inventer la correspondance chez
        chaque appelant la ferait diverger."""
        self.assertEqual(
            I.target_tokens("macos", "aarch64"),
            I.target_tokens("macos", "arm64"),
        )


class TestLaVerificationEstFermeeParDefaut(unittest.TestCase):
    """C'est le dernier moment où l'on peut encore ne rien exécuter."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.chemin = os.path.join(self.tmp.name, "archive.tar.gz")
        self.contenu = b"une archive inventee, pas une vraie"
        with open(self.chemin, "wb") as fh:
            fh.write(self.contenu)
        self.somme = hashlib.sha256(self.contenu).hexdigest()

    def test_the_right_sum_passes(self):
        """Contrôle positif."""
        self.assertEqual(I.OK, I.verify(self.chemin, self.somme))

    def test_the_case_of_the_expected_sum_does_not_matter(self):
        self.assertEqual(I.OK, I.verify(self.chemin, self.somme.upper()))

    def test_one_changed_byte_is_refused(self):
        with open(self.chemin, "wb") as fh:
            fh.write(self.contenu + b"!")
        self.assertEqual(
            I.CHECKSUM_MISMATCH, I.verify(self.chemin, self.somme)
        )

    def test_a_sum_differing_only_at_the_end_is_refused(self):
        """Comparer un préfixe laisserait passer une archive dont la somme
        ne diffère que sur ses derniers caractères — et une collision de
        préfixe se fabrique, là où une collision entière ne se fabrique
        pas."""
        tordue = self.somme[:-1] + ("0" if self.somme[-1] != "0" else "1")
        self.assertEqual(I.CHECKSUM_MISMATCH, I.verify(self.chemin, tordue))

    def test_an_absent_file_is_refused_and_not_taken_for_success(self):
        manquant = os.path.join(self.tmp.name, "jamais-telecharge.tar.gz")
        self.assertEqual(I.FILE_ABSENT, I.verify(manquant, self.somme))

    def test_no_expected_sum_is_refused_too(self):
        """« Rien à vérifier » ne veut pas dire « vérifié ». C'est le refus
        qui manque le plus souvent, parce qu'il ressemble à un cas normal."""
        for attendue in ("", None, "   "):
            with self.subTest(attendue=attendue):
                self.assertNotEqual(I.OK, I.verify(self.chemin, attendue))

    def test_the_sum_is_read_in_chunks_and_still_correct(self):
        """Une archive pèse des dizaines de mégaoctets ; la charger d'un
        coup n'apporte rien, mais lire par blocs doit donner le même."""
        gros = os.path.join(self.tmp.name, "gros.bin")
        charge = os.urandom(3 * 1024 * 1024)
        with open(gros, "wb") as fh:
            fh.write(charge)
        self.assertEqual(hashlib.sha256(charge).hexdigest(), I.sha256_of(gros))

    def test_an_unreadable_file_hashes_to_nothing_rather_than_crashing(self):
        self.assertEqual("", I.sha256_of(os.path.join(self.tmp.name, "nul")))


class TestLaTableEllememe(unittest.TestCase):
    def test_it_ships_with_nothing_unverified_in_it(self):
        """Une somme se RELÈVE. En inventer une donnerait un mécanisme qui
        refuse tout, ou pire, qui accepte ce qu'il ne devrait pas. Cette
        épreuve n'interdit pas d'en ajouter — elle exige que ce qu'on ajoute
        ait la FORME d'une somme SHA-256."""
        for version, cibles in I.RELEASES.items():
            for cible, somme in cibles.items():
                with self.subTest(version=version, cible=cible):
                    self.assertRegex(somme, r"^[0-9a-fA-F]{64}$")
                    self.assertEqual(2, len(cible))


class TestElleNeTelechargeRien(unittest.TestCase):
    def test_the_module_fetches_nothing_and_runs_nothing(self):
        import ast

        chemin = os.path.join(RACINE, "script", "vm", "lima_install.py")
        with open(chemin, encoding="utf-8") as handle:
            arbre = ast.parse(handle.read())
        racines = set()
        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.Import):
                racines.update(a.name.split(".")[0] for a in noeud.names)
            elif isinstance(noeud, ast.ImportFrom) and noeud.module:
                racines.add(noeud.module.split(".")[0])
        self.assertTrue(racines, "aucun import lu : rien n'est prouvé")
        for interdit in ("urllib", "requests", "subprocess", "socket"):
            self.assertNotIn(interdit, racines)


if __name__ == "__main__":
    unittest.main()
