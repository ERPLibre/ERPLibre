#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La confrontation de sortie DIT ce qu'elle va couper, avant de couper.

CE QU'ELLE FAIT VRAIMENT. Elle charge, par « sudo nft -f », un jeu de
règles en « policy drop » sur output ET forward — dans le jeu de règles de
l'HÔTE, sans espace de noms. La seule destination nommée est une adresse de
documentation, qui n'existe pas. La machine perd donc sa sortie réseau tant
que « --detruire » n'a pas tourné, et une session ssh tombe avec le reste.

CE QU'ELLE DISAIT. Rien. La première commande partait sans question, et le
rappel de « --detruire » n'arrivait qu'à la FIN — c'est-à-dire après la
coupure, sur un terminal qui pouvait ne plus rien afficher.

Le dépôt a déjà son patron pour ce geste : retaper « OUI », le message
nommant ce qui sera détruit. Il vaut ici.

Rien n'est chargé : l'élévation et l'exécution sont bouchonnées.
"""

import importlib.util
import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)


def module():
    """Le script de confrontation, chargé par son chemin."""
    chemin = os.path.join(RACINE, "long_test", "egress_confront.py")
    spec = importlib.util.spec_from_file_location("egress_confront", chemin)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestElleDitAvantDeCouper(unittest.TestCase):
    def setUp(self):
        self.mod = module()
        self.lances = []
        self.patch = mock.patch.object(
            self.mod,
            "jouer",
            side_effect=lambda argv, **k: (
                self.lances.append(argv) or (0, "")
            ),
        )
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def poser(self, reponse):
        tampon = io.StringIO()
        with mock.patch("builtins.input", return_value=reponse):
            with redirect_stdout(tampon):
                rendu = self.mod.poser(self.mod.regles_de_banc(), False)
        return rendu, tampon.getvalue()

    def test_the_dry_run_asks_nothing_and_runs_nothing(self):
        tampon = io.StringIO()
        with mock.patch("builtins.input") as saisie:
            with redirect_stdout(tampon):
                self.mod.poser(self.mod.regles_de_banc(), True)
        saisie.assert_not_called()
        self.assertEqual([], self.lances)

    def test_without_the_typed_word_nothing_is_loaded(self):
        rendu, _ecran = self.poser("oui")
        self.assertFalse(rendu)
        self.assertEqual([], self.lances)

    def test_the_warning_names_what_is_cut_and_how_to_undo(self):
        _rendu, ecran = self.poser("non")
        self.assertIn("--detruire", ecran)
        self.assertIn("ssh", ecran.lower())

    def test_the_warning_comes_before_any_command(self):
        """Annoncé après, le rappel arrive sur un terminal qui peut déjà
        ne plus rien afficher."""
        _rendu, ecran = self.poser("non")
        self.assertTrue(ecran.strip())
        self.assertEqual([], self.lances)

    def test_typing_it_loads_the_rules(self):
        rendu, _ecran = self.poser("OUI")
        self.assertTrue(self.lances)
        self.assertTrue(any("nft" in " ".join(argv) for argv in self.lances))
        self.assertTrue(rendu)


if __name__ == "__main__":
    unittest.main()
