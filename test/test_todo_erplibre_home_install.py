#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Les deux entrées d'installation locale d'ERPLibre Home du menu Stream
Deck.

« Installer ERPLibre Home (local) » pose la base, « Installer ERPLibre Home
Stream Deck (local) » le niveau Stream Deck, base comprise. Les deux lancent
le même installateur, la seconde avec --stream-deck, après quatre questions
dont les réponses par défaut donnent --deck-program=tiler et
--restart-after-game : ces tests-ci répondent Entrée à chacune. Les autres
réponses sont gardées par test_todo_streamdeck_menu.py.

L'installateur rend trois issues, et le menu les annonce chacune par une
seule ligne : 0 installé, 2 système hors périmètre — avec la raison que
l'installateur écrit sur sa ligne « UNSUPPORTED: » —, tout autre code un
échec. Le lanceur est remplacé par un double qui retient la commande et ses
options et rend le code et les lignes qu'on lui fixe : aucun processus ne
part.
"""

import contextlib
import io
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.todo import todo_i18n  # noqa: E402
from script.todo.todo import TODO  # noqa: E402

INSTALLATEUR = "./script/install/install_erplibre_home.sh"
# Chaque entrée : la méthode que le menu appelle, la commande qu'elle lance.
ENTREES = {
    "_erplibre_home_install_local": INSTALLATEUR,
    "_erplibre_home_streamdeck_install_local": (
        INSTALLATEUR + " --stream-deck --deck-program=tiler"
        " --restart-after-game"
    ),
}


class ExecuteFactice:
    """Rend (code, lignes), la forme de return_status_and_output=True."""

    def __init__(self, code, lignes=()):
        self.appels = []
        self.code = code
        self.lignes = list(lignes)

    def exec_command_live(self, cmd, **kwargs):
        self.appels.append((cmd, kwargs))
        return self.code, list(self.lignes)


class TestInstallationLocale(unittest.TestCase):
    def setUp(self):
        todo_i18n._current_lang = "en"

    def tearDown(self):
        todo_i18n._current_lang = None

    def lancer(self, methode, code, lignes=()):
        todo = TODO.__new__(TODO)
        todo.execute = ExecuteFactice(code, lignes)
        sortie = io.StringIO()
        with (
            contextlib.redirect_stdout(sortie),
            mock.patch("builtins.input", return_value=""),
        ):
            rendu = getattr(todo, methode)()
        return todo.execute.appels, sortie.getvalue(), rendu

    def test_chaque_entree_lance_sa_commande_hors_du_venv_erplibre(self):
        for methode, commande in ENTREES.items():
            with self.subTest(methode=methode):
                appels, _, _ = self.lancer(methode, 0)
                self.assertEqual(len(appels), 1)
                cmd, kwargs = appels[0]
                self.assertEqual(cmd, commande)
                self.assertIs(kwargs.get("source_erplibre"), False)
                self.assertIs(kwargs.get("return_status_and_output"), True)

    def test_le_succes_dit_de_rouvrir_la_session(self):
        for methode in ENTREES:
            with self.subTest(methode=methode):
                _, sortie, rendu = self.lancer(methode, 0)
                self.assertIn("✅", sortie)
                self.assertIn("Log out and back in", sortie)
                self.assertIs(rendu, False)

    def test_le_code_2_montre_la_raison_seule(self):
        lignes = [
            "family=arch",
            "UNSUPPORTED: GNOME 52 not in shell-version",
        ]
        for methode in ENTREES:
            with self.subTest(methode=methode):
                _, sortie, rendu = self.lancer(methode, 2, lignes)
                self.assertIn(
                    "ERPLibre Home not supported on this system:"
                    " GNOME 52 not in shell-version",
                    sortie,
                )
                self.assertNotIn("UNSUPPORTED:", sortie)
                self.assertNotIn("❌", sortie)
                self.assertIs(rendu, False)

    def test_le_code_2_sans_raison_le_dit(self):
        _, sortie, _ = self.lancer(
            "_erplibre_home_install_local", 2, ["family=arch"]
        )
        self.assertIn(
            "ERPLibre Home not supported on this system:"
            " no reason reported by the installer",
            sortie,
        )

    def test_un_autre_code_renvoie_a_la_sortie(self):
        for methode in ENTREES:
            with self.subTest(methode=methode):
                _, sortie, rendu = self.lancer(
                    methode, 1, ["E: Unable to locate package"]
                )
                self.assertIn("❌", sortie)
                self.assertIn("see the output above", sortie)
                self.assertNotIn("not supported", sortie)
                self.assertIs(rendu, False)

    def test_l_installateur_appele_existe_et_s_execute(self):
        chemin = RACINE / INSTALLATEUR
        self.assertTrue(chemin.is_file(), f"{INSTALLATEUR} absent")
        self.assertTrue(
            os.access(chemin, os.X_OK), f"{INSTALLATEUR} non exécutable"
        )


if __name__ == "__main__":
    unittest.main()
