#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le harnais est du code de test : il a besoin d'être testé lui aussi.

Un harnais cassé rend toutes les épreuves qui s'en servent silencieusement
vertes. Un shim qui n'écrit rien, un piège qui n'attrape pas, un journal
d'appels toujours vide : chacun transforme la suite en décoration.
"""

import os
import subprocess
import sys
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

from test.devstack_harness import (  # noqa: E402
    PIEGE,
    BinPiege,
    ShimDir,
    which_sous,
)


def lance(commande, shim):
    """Joue une commande shell sous le PATH du shim."""
    return subprocess.run(
        ["bash", "-c", commande],
        capture_output=True,
        text=True,
        env=shim.env(),
        timeout=30,
    )


class TestLeShimDecideQuiExiste(unittest.TestCase):
    def test_a_declared_binary_is_found(self):
        with ShimDir(outil="echo trouve") as shim:
            self.assertIsNotNone(which_sous(shim, "outil"))

    def test_an_undeclared_binary_is_absent_under_a_bare_path(self):
        with ShimDir(nu=True, outil="exit 0") as shim:
            self.assertIsNone(which_sous(shim, "git"))
            # Contrôle positif : le shim n'est pas vide pour autant.
            self.assertIsNotNone(which_sous(shim, "outil"))

    def test_the_real_binaries_stay_reachable_by_default(self):
        """Le défaut des quatre copies remplacées : /usr/bin reste au PATH."""
        with ShimDir(outil="exit 0") as shim:
            self.assertIn("/usr/bin", shim.path())

    def test_a_stub_plays_the_body_it_was_given(self):
        with ShimDir(outil="echo bonjour") as shim:
            self.assertEqual("bonjour", lance("outil", shim).stdout.strip())


class TestLeJournalDitCeQuiAServi(unittest.TestCase):
    """Sans lui, un test passe aussi bien quand le code ne tourne pas."""

    def test_an_unused_stub_leaves_the_log_empty(self):
        with ShimDir(outil="exit 0") as shim:
            self.assertEqual([], shim.appels)

    def test_a_used_stub_is_recorded(self):
        with ShimDir(outil="exit 0") as shim:
            lance("outil", shim)
            self.assertEqual(["outil"], shim.appels)

    def test_the_log_keeps_the_order_and_the_repeats(self):
        with ShimDir(un="exit 0", deux="exit 0") as shim:
            lance("un; deux; un", shim)
            self.assertEqual(["un", "deux", "un"], shim.appels)


class TestLePiegeAttrape(unittest.TestCase):
    """Un piège qui n'attrape pas laisse passer le vrai binaire."""

    def test_calling_a_trapped_binary_fails_on_exit(self):
        with self.assertRaises(BinPiege) as leve:
            with ShimDir(interdit=PIEGE) as shim:
                lance("interdit", shim)
        self.assertIn("interdit", str(leve.exception))

    def test_not_calling_it_passes(self):
        """Contrôle positif : le piège ne doit pas échouer tout seul."""
        with ShimDir(interdit=PIEGE, permis="exit 0") as shim:
            lance("permis", shim)
        self.assertTrue(True)

    def test_a_trapped_binary_exists_but_refuses(self):
        """Il doit être TROUVABLE, sinon le code testé prend un autre chemin
        et l'épreuve ne dit plus rien de ce qu'elle croyait tester."""
        with self.assertRaises(BinPiege):
            with ShimDir(interdit=PIEGE) as shim:
                self.assertIsNotNone(which_sous(shim, "interdit"))
                resultat = lance("interdit", shim)
                self.assertEqual(127, resultat.returncode)

    def test_the_temporary_directory_is_removed_even_after_a_trap(self):
        chemin = None
        try:
            with ShimDir(interdit=PIEGE) as shim:
                chemin = shim.chemin
                lance("interdit", shim)
        except BinPiege:
            pass
        self.assertFalse(os.path.exists(chemin))


if __name__ == "__main__":
    unittest.main()
