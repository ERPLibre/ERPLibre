#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""La langue du binaire du cache, vue du menu.

Le binaire traduit ses messages humains selon --lang. Le menu doit donc dire
laquelle il veut, et la bonne : la langue de todo.py pour ce qu'il AFFICHE,
le français pour ce qu'il LIT — il ne connaît les libellés que dans cette
langue. Et ce qu'il lit dans un journal écrit par le service, dont la langue
est fixée à l'installation, il doit le reconnaître dans les deux.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from script.todo import qemu_cache_menu as menu  # noqa: E402

CATALOGUE = RACINE / "script" / "qemu_cache" / "catalogue_en.go"


class TestLOptionDeLangue(unittest.TestCase):
    def test_une_sortie_lue_est_demandee_en_francais(self):
        with mock.patch.object(menu, "get_lang", return_value="en"):
            self.assertEqual(menu.option_langue(lue=True), "--lang fr")

    def test_une_sortie_affichee_suit_la_langue_de_todo(self):
        for langue in ("fr", "en"):
            with mock.patch.object(menu, "get_lang", return_value=langue):
                self.assertEqual(menu.option_langue(), f"--lang {langue}")

    def test_le_pre_remplissage_parle_la_langue_de_todo(self):
        """Lancé par sudo -u : EL_LANG n'y arriverait pas, l'option si."""
        with mock.patch.object(menu, "get_lang", return_value="en"):
            cmd = menu.miroir_prefetch_cmd("/tmp/liste", [])
        self.assertIn("--lang en", cmd)

    def test_le_retrait_d_exception_garde_nft_en_bout_de_tube(self):
        """Le message humain va à l'erreur standard ; la sortie standard
        porte les règles que nft lit, et ne se traduit jamais."""
        with mock.patch.object(menu, "get_lang", return_value="en"):
            cmd = menu.bypass_retrait_cmd("52:54:00:00:00:04")
        self.assertIn("--lang en", cmd)
        self.assertTrue(cmd.endswith("| sudo nft -f -"))


class TestCeQueLeMenuLit(unittest.TestCase):
    def test_l_occupation_du_miroir_est_lue_en_francais(self):
        vu = {}

        def faux_lire(cmd, delai=15):
            vu["cmd"] = cmd
            return "objets      : 3\ndépôts git  : 12 en miroir, 4.2 Gio\n"

        with (
            mock.patch.object(
                menu.QemuCacheMenuMixin, "_cache_lire", staticmethod(faux_lire)
            ),
            mock.patch.object(menu, "get_lang", return_value="en"),
        ):
            rendu = menu.QemuCacheMenuMixin._cache_miroir_occupation()
        self.assertIn("--lang fr", vu["cmd"])
        self.assertEqual(rendu, ("12", "4.2 Gio"))

    def test_le_journal_est_lu_dans_les_deux_langues(self):
        """La langue du service est celle de son installation, pas celle de
        qui ouvre le menu : un refus appris doit être reconnu dans les deux."""
        journal = (
            "tunnel opaque retenu pour npm.example (3 échec(s)) : EOF\n"
            "opaque tunnel kept for pypi.example (3 failure(s)): EOF\n"
        )
        commandes = []

        def faux_lire(cmd, delai=15):
            commandes.append(cmd)
            return journal

        with mock.patch.object(
            menu.QemuCacheMenuMixin, "_cache_lire", staticmethod(faux_lire)
        ):
            hotes = menu.QemuCacheMenuMixin._cache_refus_appris()
        self.assertEqual(hotes, ["npm.example", "pypi.example"])
        for motif in menu.REFUS_APPRIS:
            self.assertIn(motif, commandes[0])

    def test_le_catalogue_porte_ce_que_le_menu_lit(self):
        """Une traduction qui s'écarte de ces libellés rendrait le menu
        aveugle sans qu'aucun test du binaire ne le voie."""
        texte = CATALOGUE.read_text(encoding="utf-8")
        self.assertIn('"opaque tunnel kept for %s (', texte)
        for libelle in ("authority   : %s", "fingerprint : %s"):
            self.assertIn(f'"{libelle}', texte)
        for prefixe in menu.LIBELLES_TUS:
            self.assertTrue(
                prefixe in texte or prefixe in ("autorité", "empreinte"),
                prefixe,
            )


if __name__ == "__main__":
    unittest.main()
