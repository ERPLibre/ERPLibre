#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'écran des cibles : ce qu'il retient, ce qu'il écrit, ce qu'il refuse.

Aucune machine, aucun réseau : les trois fichiers de configuration et les
préférences sont déplacés dans un temporaire, et les réponses au clavier sont
une liste. Ce qui est vérifié ici est l'ENCHAÎNEMENT — un écran qui écrirait
la bonne cible en oubliant de la retenir laisserait l'utilisateur croire
qu'il a choisi.
"""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

from script.remote import deploy_target as D  # noqa: E402
from script.todo.todo import TODO  # noqa: E402


class EcranCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = os.path.join(self.tmp.name, "todo.json")
        with open(self.base, "w") as fh:
            json.dump({D.CONFIG_KEY: []}, fh)
        self.patches = [
            patch("script.config.config_file.CONFIG_FILE", self.base),
            patch(
                "script.config.config_file.CONFIG_OVERRIDE_FILE",
                os.path.join(self.tmp.name, "override.json"),
            ),
            patch(
                "script.config.config_file.CONFIG_OVERRIDE_PRIVATE_FILE",
                os.path.join(self.tmp.name, "private.json"),
            ),
        ]
        for item in self.patches:
            item.start()
        self.prefs = {}
        prefs = patch.multiple(
            "script.remote.deploy_target.todo_prefs",
            get=lambda cle, defaut=None: self.prefs.get(cle, defaut),
            set=lambda cle, valeur: self.prefs.__setitem__(cle, valeur),
        )
        prefs.start()
        self.patches.append(prefs)
        self.ecran = TODO.__new__(TODO)

    def tearDown(self):
        for item in self.patches:
            item.stop()
        self.tmp.cleanup()

    def jouer(self, *reponses):
        """Déroule l'écran sur ces réponses, et rend ce qu'il a affiché."""
        sortie = io.StringIO()
        with patch("builtins.input", side_effect=list(reponses)):
            with redirect_stdout(sortie):
                self.ecran._deploy_ssh_targets()
        return sortie.getvalue()

    # Le formulaire, dans l'ordre de CHAMPS : nom, adresse, rebond, port,
    # clé, chemin, domaine, courriel. Une réponse vide garde la valeur.
    def formulaire(self, nom, adresse, **reste):
        return [
            nom,
            adresse,
            reste.get("jump", ""),
            reste.get("port", ""),
            reste.get("identity", ""),
            reste.get("path", ""),
            reste.get("domain", ""),
            reste.get("admin_email", ""),
        ]


class TestLEcranVide(EcranCase):
    def test_it_says_there_is_none_and_offers_to_add(self):
        affiche = self.jouer("0")
        self.assertIn("[a]", affiche)

    def test_adding_the_first_one_selects_it(self):
        """Sans cela, la cible existe et l'écran continue de dire
        « aucune » : on croirait avoir choisi."""
        self.jouer(
            "a", *self.formulaire("essai", "compte@machine.example"), "0"
        )
        self.assertEqual(["essai"], D.names())
        self.assertEqual("essai", D.selected()["name"])


class TestChoisirUneCible(EcranCase):
    def setUp(self):
        super().setUp()
        D.save({"name": "un", "target": "compte@un.example"})
        D.save({"name": "deux", "target": "compte@deux.example"})

    def test_a_number_selects_the_target_it_designates(self):
        self.jouer("2", "0")
        self.assertEqual("deux", D.selected()["name"])

    def test_the_selected_one_is_marked_in_the_list(self):
        D.select("deux")
        affiche = self.jouer("0")
        ligne = [l for l in affiche.splitlines() if "deux" in l][0]
        self.assertIn("←", ligne)
        autre = [l for l in affiche.splitlines() if "un —" in l][0]
        self.assertNotIn("←", autre)

    def test_a_number_out_of_range_changes_nothing(self):
        D.select("un")
        self.jouer("9", "0")
        self.assertEqual("un", D.selected()["name"])

    def test_forgetting_clears_the_selection(self):
        D.select("un")
        self.jouer("o", "0")
        self.assertIsNone(D.selected())


class TestModifierUneCible(EcranCase):
    def setUp(self):
        super().setUp()
        D.save({"name": "un", "target": "compte@un.example", "port": "2222"})

    def test_an_empty_answer_keeps_the_value_in_place(self):
        """Corriger un champ ne doit pas obliger à ressaisir les sept
        autres."""
        self.jouer("m", "1", *self.formulaire("", ""), "0")
        cible = D.load("un")
        self.assertEqual("compte@un.example", cible["target"])
        self.assertEqual("2222", cible["port"])

    def test_editing_one_field_leaves_the_others_alone(self):
        self.jouer("m", "1", *self.formulaire("", "compte@autre.example"), "0")
        self.assertEqual("compte@autre.example", D.load("un")["target"])
        self.assertEqual("2222", D.load("un")["port"])

    def test_renaming_removes_the_old_entry(self):
        """Sans le retrait, la même machine serait deux fois dans
        l'inventaire, sous deux noms."""
        D.select("un")
        self.jouer("m", "1", *self.formulaire("deux", ""), "0")
        self.assertEqual(["deux"], D.names())
        self.assertEqual("deux", D.selected()["name"])

    def test_a_refused_value_is_said_and_writes_nothing(self):
        affiche = self.jouer(
            "m", "1", *self.formulaire("", "adresse avec espaces"), "0"
        )
        self.assertIn("✗", affiche)
        self.assertEqual("compte@un.example", D.load("un")["target"])


class TestSupprimerUneCible(EcranCase):
    def setUp(self):
        super().setUp()
        D.save({"name": "un", "target": "compte@un.example"})

    def test_it_asks_before_deleting(self):
        self.jouer("s", "1", "n", "0")
        self.assertEqual(["un"], D.names())

    def test_a_yes_deletes_it(self):
        self.jouer("s", "1", "y", "0")
        self.assertEqual([], D.names())

    def test_a_deleted_selection_is_simply_asked_for_again(self):
        D.select("un")
        self.jouer("s", "1", "y", "0")
        self.assertIsNone(D.selected())

    def test_a_shared_target_says_why_it_stays(self):
        with open(self.base, "w") as fh:
            json.dump(
                {
                    D.CONFIG_KEY: [
                        {"name": "equipe", "target": "compte@e.example"}
                    ]
                },
                fh,
            )
        # La fusion pose le fichier partagé AVANT le privé : « equipe »
        # est donc la première, et « un » la seconde.
        affiche = self.jouer("s", "1", "y", "0")
        self.assertIn("✗", affiche)
        self.assertIn("equipe", D.names())


class TestLEnteteDuMenu(EcranCase):
    """Cinq entrées installent ou redémarrent : lire à qui l'on parle
    AVANT de choisir est ce qui évite de le découvrir après."""

    def test_it_names_the_selected_target(self):
        D.save({"name": "un", "target": "compte@un.example"})
        D.select("un")
        sortie = io.StringIO()
        with redirect_stdout(sortie):
            self.ecran._deploy_ssh_show_target()
        self.assertIn("un", sortie.getvalue())
        self.assertIn("compte@un.example", sortie.getvalue())

    def test_it_says_so_when_there_is_none(self):
        sortie = io.StringIO()
        with redirect_stdout(sortie):
            self.ecran._deploy_ssh_show_target()
        self.assertNotIn("@", sortie.getvalue())


if __name__ == "__main__":
    unittest.main()
