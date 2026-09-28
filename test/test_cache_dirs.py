#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les dossiers privés partagés par les caches.

Ce que ces tests protègent est le passage d'un cache à DEUX : le ménage des
dossiers éphémères se fait dans un dossier public, commun à tous les caches
et à tous les utilisateurs de la machine. Un balayage qui ne regarderait pas
le préfixe emporterait le cache vivant du voisin.
"""

import os
import tempfile
import unittest
from pathlib import Path

from script.todo import cache_dirs


class Refusee(Exception):
    """La classe d'exception qu'un appelant fournit."""


class SweepCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def _dossier(self, nom: str) -> Path:
        chemin = self.base / nom
        chemin.mkdir()
        (chemin / "cache.db").write_text("x")
        return chemin


class TestTheSweepStaysInItsOwnPrefix(SweepCase):
    def test_an_orphan_of_this_prefix_goes(self):
        mort = self._dossier("erplibre-a-999999999")
        self.assertEqual(
            cache_dirs.sweep_orphan_ephemeral("erplibre-a-", self.base), 1
        )
        self.assertFalse(mort.exists())

    def test_an_orphan_of_another_prefix_stays(self):
        """Le cache du voisin, orphelin lui aussi, ne regarde pas celui-ci :
        c'est à son propre balayage de s'en charger."""
        voisin = self._dossier("erplibre-b-999999999")
        cache_dirs.sweep_orphan_ephemeral("erplibre-a-", self.base)
        self.assertTrue(voisin.exists())

    def test_a_living_process_keeps_its_cache(self):
        vivant = self._dossier(f"erplibre-a-{os.getpid()}")
        self.assertEqual(
            cache_dirs.sweep_orphan_ephemeral("erplibre-a-", self.base), 0
        )
        self.assertTrue(vivant.exists())

    def test_a_name_that_is_not_a_pid_is_left_alone(self):
        """Le suffixe sert d'identifiant de processus : ce qui n'en est pas
        un n'a pas été posé par ce mécanisme, et ne lui appartient pas."""
        etranger = self._dossier("erplibre-a-notes")
        cache_dirs.sweep_orphan_ephemeral("erplibre-a-", self.base)
        self.assertTrue(etranger.exists())

    def test_a_missing_base_is_not_an_error(self):
        absente = self.base / "jamais-creee"
        self.assertEqual(
            cache_dirs.sweep_orphan_ephemeral("erplibre-a-", absente), 0
        )


class TestTheRootIsPrivate(SweepCase):
    def test_it_is_created_in_0700(self):
        import stat

        racine = self.base / "parent" / "compte"
        cache_dirs.prepare_private_root(
            racine, ephemeral=False, erreur=Refusee
        )
        self.assertEqual(stat.S_IMODE(os.stat(racine).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(racine.parent).st_mode), 0o700)

    def test_a_symlinked_ephemeral_parent_is_refused(self):
        """Le chemin d'un dossier éphémère est devinable — il porte le PID —
        et son parent est public. Un tiers qui l'a pré-créé en lien
        symbolique ferait écrire le cache là où il désigne."""
        cible = self.base / "ailleurs"
        cible.mkdir()
        parent = self.base / "public" / "erplibre-a-1"
        parent.parent.mkdir()
        parent.symlink_to(cible)
        with self.assertRaises(Refusee):
            cache_dirs.prepare_private_root(
                parent / "compte", ephemeral=True, erreur=Refusee
            )

    def test_the_caller_chooses_the_exception(self):
        """Chaque cache a la sienne, et ses appelants attrapent déjà
        celle-là."""
        cible = self.base / "cible"
        cible.mkdir()
        parent = self.base / "public2" / "erplibre-a-1"
        parent.parent.mkdir()
        parent.symlink_to(cible)

        class Autre(Exception):
            pass

        with self.assertRaises(Autre):
            cache_dirs.prepare_private_root(
                parent / "compte", ephemeral=True, erreur=Autre
            )


if __name__ == "__main__":
    unittest.main()
