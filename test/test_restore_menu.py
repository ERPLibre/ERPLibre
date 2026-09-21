#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La restauration du menu : ce qu'elle cite, et la porte qu'elle passe.

Restaurer DÉTRUIT la base cible, dont le nom est du texte libre tapé au
clavier. Deux choses en découlent : le nom traverse une commande exécutée
par bash, donc il est cité ; et une base qui existe déjà ne s'écrase
qu'après une garde qui la nomme.

Ni base ni terminal : l'exécution est simulée.
"""

import os
import shlex
import sys
import unittest
from unittest.mock import MagicMock, patch

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

sys.argv = ["todo.py"]

from script.database import db_restore  # noqa: E402
from script.database import drill_guard  # noqa: E402
from script.todo.todo import TODO  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402


def menu(statuts=(0, 0, 0), bases=()):
    """Un menu dont l'exécution est simulée.

    La PREMIÈRE commande lancée est toujours « db list » : la porte lit
    ce qu'elle va détruire avant de laisser bâtir quoi que ce soit.
    `statuts` donne les codes des commandes qui suivent.
    """
    todo = TODO()
    todo.db_manager._execute = MagicMock()
    todo.db_manager._execute.exec_command_live.side_effect = [
        (0, list(bases))
    ] + [(code, []) for code in statuts]
    return todo


def commandes(todo):
    """Ce qui a été lancé, la lecture de la liste mise à part : elle ne
    détruit rien et son rang fausserait tous les comptes."""
    return [
        appel[0][0]
        for appel in todo.db_manager._execute.exec_command_live.call_args_list
        if "db list" not in appel[0][0]
    ]


class TestLesDeuxNomsSontCites(unittest.TestCase):
    """Ils traversent une commande exécutée par bash (`shell=True`). Un nom
    tapé au clavier y devenait une commande.

    L'ÉPREUVE DÉCOUPE COMME BASH. Chercher le texte dangereux dans la
    chaîne ne prouve rien : cité, il s'y trouve toujours, et c'est bien le
    but. Ce qui se tient est qu'il reste UN SEUL MOT après découpage —
    donc un argument, jamais une commande de plus.

    Réponses, dans l'ordre : source, fichier, nom de base, cache,
    neutraliser, mise à jour.
    """

    @patch("script.todo.database_manager.os.path.isfile", return_value=True)
    @patch("builtins.input")
    def test_a_database_name_stays_one_single_word(self, saisie, _isfile):
        saisie.side_effect = [
            "1",
            "sauvegarde",
            "a; touch pris",
            "n",
            "n",
            "n",
        ]
        todo = menu()
        todo.db_manager.restore_from_database()
        for commande in commandes(todo):
            mots = shlex.split(commande)
            self.assertIn("a; touch pris", mots)
            self.assertNotIn("touch", mots)

    @patch("script.todo.database_manager.os.path.isfile", return_value=True)
    @patch("builtins.input")
    def test_an_image_name_stays_one_too(self, saisie, _isfile):
        """Le nom d'IMAGE traverse la même commande, et aucune garde ne le
        lisait : elles ne regardaient que le nom de base."""
        saisie.side_effect = ["1", "a; touch pris", "cible", "n", "n", "n"]
        todo = menu()
        todo.db_manager.restore_from_database()
        mots = shlex.split(commandes(todo)[0])
        self.assertIn("a; touch pris", mots)
        self.assertNotIn("touch", mots)


class TestLaBrancheDuNavigateur(unittest.TestCase):
    """Le fichier choisi passe par le composeur du menu, qui rend un NOM
    sous image_db/ : son basename portait « .zip », et un fichier pris
    ailleurs n'y est pas."""

    @patch("builtins.input")
    def test_the_chosen_path_goes_through_the_composer(self, saisie):
        saisie.side_effect = ["", "", "n", "n", "n"]
        todo = menu()
        chemin = os.path.join(os.getcwd(), "image_db", "sauvegarde.zip")
        vus = []
        todo.db_manager._image_name = lambda c: vus.append(c) or "sauvegarde"
        todo.db_manager.open_file_image_db = (
            lambda: todo.db_manager._on_dir_selected(chemin)
        )
        todo.db_manager.restore_from_database()
        self.assertEqual([chemin], vus)
        self.assertIn("--image sauvegarde", commandes(todo)[0])
        self.assertNotIn(".zip", commandes(todo)[0])

    @patch("builtins.input")
    def test_leaving_the_browser_without_choosing_launches_nothing(
        self, saisie
    ):
        """`q` ou `esc` laisse le chemin vide : rien ne part, et le
        composeur n'est pas consulté sur un chemin qui n'existe pas."""
        saisie.side_effect = [""]
        todo = menu()
        todo.db_manager._image_name = lambda c: self.fail(c)
        todo.db_manager.open_file_image_db = lambda: None
        todo.db_manager.restore_from_database()
        self.assertEqual([], commandes(todo))


class PorteDeBanc(unittest.TestCase):
    """Le menu, sa liste de bases simulée et sa garde bouchonnée."""

    def porte(self, bases=(), listable=True, exercice=False):
        todo = TODO()
        todo.db_manager._execute = MagicMock()
        todo.db_manager._execute.exec_command_live.return_value = (
            0 if listable else 1,
            list(bases),
        )
        self.garde = patch.object(
            drill_guard, "is_drill_database", return_value=exercice
        )
        self.garde.start()
        self.addCleanup(self.garde.stop)
        return todo


class TestLaPorteDeLaDestructionInteractive(PorteDeBanc):
    """LE POINT DE PASSAGE de l'étage interactif. Restaurer DÉTRUIT la base
    cible — db_restore la droppe — et le nom cible est du texte libre. La
    collision était imprimée (« ## Drop X ## ») et jamais questionnée.

    La garde d'exercice existait, avec ses épreuves et zéro appelant : elle
    ne gardait que l'effacement en LOT. Ici elle sert enfin de feu vert.
    """

    def test_a_target_that_does_not_exist_asks_nothing(self):
        """Rien à détruire : poser une question ferait prendre l'habitude
        de la balayer."""
        todo = self.porte(bases=["autre"])
        with patch("builtins.input") as saisie:
            self.assertTrue(todo.db_manager._may_destroy("neuve"))
        saisie.assert_not_called()

    def test_a_drill_target_passes_and_says_which(self):
        """Le feu vert de la garde : drapeau de neutralisation ou compte
        d'essai. Il se DIT — passer en silence ne distingue plus « la base
        a été reconnue » de « rien n'a été regardé »."""
        import io as tampon_io
        from contextlib import redirect_stdout

        todo = self.porte(bases=["essai"], exercice=True)
        tampon = tampon_io.StringIO()
        with patch("builtins.input") as saisie:
            with redirect_stdout(tampon):
                self.assertTrue(todo.db_manager._may_destroy("essai"))
        saisie.assert_not_called()
        self.assertTrue(tampon.getvalue().strip())

    def test_a_real_target_demands_the_name_retyped(self):
        """Recopier un nom oblige à regarder ce qu'on détruit, là où « o »
        se tape par réflexe. Une espace en trop reste le même nom : la
        garde tient l'attention, elle ne punit pas la frappe."""
        todo = self.porte(bases=["reelle"], exercice=False)
        for reponse in ("reelle", " reelle "):
            with self.subTest(reponse=reponse):
                with patch("builtins.input", return_value=reponse):
                    self.assertTrue(todo.db_manager._may_destroy("reelle"))

    def test_a_real_target_refuses_anything_else(self):
        """« oui » et « o » sont refusés EXPRÈS : ce sont les réponses
        qu'on donne sans lire."""
        todo = self.porte(bases=["reelle"], exercice=False)
        for reponse in ("", "oui", "o", "reell", "REELLE"):
            with self.subTest(reponse=reponse):
                with patch("builtins.input", return_value=reponse):
                    self.assertFalse(todo.db_manager._may_destroy("reelle"))

    def test_a_postgres_that_will_not_answer_refuses(self):
        """Ne pas savoir ce qui sera détruit n'est pas savoir qu'il n'y a
        rien : parier sur la seconde lecture est ce que la porte existe
        pour empêcher."""
        todo = self.porte(listable=False)
        with patch("builtins.input") as saisie:
            self.assertFalse(todo.db_manager._may_destroy("cible"))
        saisie.assert_not_called()

    def test_an_empty_server_is_not_a_mute_one(self):
        """Zéro base est une RÉPONSE ; une liste illisible n'en est pas
        une. Les confondre laisse passer l'une ou refuse l'autre.

        `input` est bouchonné alors que ce chemin n'en lit aucun : une
        garde cassée le ferait descendre jusqu'à la retape, et l'épreuve
        attendrait sur stdin au lieu d'échouer. Une épreuve qui BLOQUE ne
        tue aucun mutant — elle fige le banc.
        """
        todo = self.porte(bases=[], listable=True)
        with patch("builtins.input") as saisie:
            self.assertTrue(todo.db_manager._may_destroy("cible"))
        saisie.assert_not_called()


class TestLaPorteEstSurLeChemin(PorteDeBanc):
    def test_a_refused_target_launches_nothing(self):
        todo = self.porte(bases=["reelle"], exercice=False)
        with patch(
            "script.todo.database_manager.os.path.isfile", return_value=True
        ):
            with patch("builtins.input") as saisie:
                saisie.side_effect = [
                    "1",
                    "sauvegarde",
                    "reelle",
                    "n",
                    "n",
                    "n",
                    "non",
                ]
                todo.db_manager.restore_from_database()
        lancees = [
            appel[0][0]
            for appel in (
                todo.db_manager._execute.exec_command_live.call_args_list
            )
        ]
        self.assertEqual([], [c for c in lancees if "db_restore" in c])


class TestLaGardeNeDescendPasEnLot(unittest.TestCase):
    """43 cibles make restaurent dans des noms recyclés — test, template,
    code_generator, robotlibre. Une base fraîchement restaurée n'a ni
    drapeau ni compte d'essai, donc elle se lit RÉELLE : la garde y
    refuserait tout. Elle appartient à l'étage interactif, et ce contrôle
    négatif est ce qui l'y retient dans six mois.
    """

    def test_the_batch_restore_never_imports_the_guard(self):
        chemin = os.path.join(RACINE, "script", "database", "db_restore.py")
        with open(chemin, encoding="utf-8") as fichier:
            source = fichier.read()
        self.assertNotIn("drill_guard", source)


if __name__ == "__main__":
    unittest.main()
