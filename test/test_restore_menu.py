#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La restauration du menu lit ce qu'elle lance, comme son jumeau.

DEUX CHEMINS FONT LA MÊME CHOSE, ET UN SEUL ÉTAIT CORRIGÉ. `TODO::
_monitoring_restore` coupe la chaîne sur un code non nul, réserve `status`
aux codes de sortie et enchaîne sur `more_arg`. `DatabaseManager::
restore_from_database` faisait tout l'inverse : la même variable portait
six sens — un choix de menu, deux réponses oui/non et trois codes de
sortie — si bien que le code de retour était écrasé par la question
suivante avant d'avoir pu servir. La chaîne continuait donc sur une base
que la restauration venait d'échouer à créer.

CE QUE LA CONVERGENCE FERME AUSSI. L'entrée « [1] » promettait un nom de
fichier et n'en demandait aucun ; la branche du navigateur rendait un
basename portant « .zip » là où `image_path` en rajoute un. Les deux noms
saisis traversaient un f-string exécuté par bash sans être cités.

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
from script.todo.todo import TODO  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402


def menu(statuts=(0, 0, 0)):
    """Un menu dont l'exécution est simulée. `statuts` donne les codes de
    sortie rendus dans l'ordre des commandes lancées."""
    todo = TODO()
    todo.db_manager._execute = MagicMock()
    todo.db_manager._execute.exec_command_live.side_effect = [
        (code, []) for code in statuts
    ]
    return todo


def commandes(todo):
    return [
        appel[0][0]
        for appel in todo.db_manager._execute.exec_command_live.call_args_list
    ]


class TestLEntreeParNomDemandeUnNom(unittest.TestCase):
    """Elle promettait « By filename » et posait `file_name = status`,
    donc visait image_db/1.zip quoi qu'on ait voulu."""

    @patch("script.todo.database_manager.os.path.isfile", return_value=True)
    @patch("builtins.input")
    def test_it_asks_for_the_image_name(self, saisie, _isfile):
        saisie.side_effect = ["1", "sauvegarde", "", "n", "n"]
        todo = menu()
        todo.db_manager.restore_from_database()
        self.assertIn("--image sauvegarde", commandes(todo)[0])

    @patch("script.todo.database_manager.os.path.isfile", return_value=False)
    @patch("builtins.input")
    def test_an_image_that_is_not_there_launches_nothing(
        self, saisie, _isfile
    ):
        """Le zip absent se disait sur la machine, après que la commande
        ait été bâtie et lancée."""
        saisie.side_effect = ["1", "jamais-vue", "", "n", "n"]
        todo = menu()
        todo.db_manager.restore_from_database()
        self.assertEqual([], commandes(todo))

    @patch("script.todo.database_manager.os.path.isfile", return_value=True)
    @patch("builtins.input")
    def test_the_path_of_the_zip_comes_from_db_restore(self, saisie, isfile):
        """`image_path` est composé LÀ et nulle part ailleurs : le recopier
        ici en ferait une divergence le jour où le répertoire change."""
        saisie.side_effect = ["1", "sauvegarde", "", "n", "n"]
        menu().db_manager.restore_from_database()
        isfile.assert_called_once_with(db_restore.image_path("sauvegarde"))


class TestLaChaineSArreteSurUnCodeNonNul(unittest.TestCase):
    """La variable portait six sens, et le code de sortie était écrasé par
    la question suivante avant d'avoir pu servir."""

    @patch("script.todo.database_manager.os.path.isfile", return_value=True)
    @patch("builtins.input")
    def test_a_failed_restore_stops_everything(self, saisie, _isfile):
        saisie.side_effect = ["1", "sauvegarde", "cible", "n", "y"]
        todo = menu(statuts=(1,))
        todo.db_manager.restore_from_database()
        self.assertEqual(1, len(commandes(todo)))

    @patch("script.todo.database_manager.os.path.isfile", return_value=True)
    @patch("builtins.input")
    def test_a_failed_restore_says_so(self, saisie, _isfile):
        import io
        from contextlib import redirect_stdout

        saisie.side_effect = ["1", "sauvegarde", "cible", "n", "n"]
        todo = menu(statuts=(1,))
        tampon = io.StringIO()
        with redirect_stdout(tampon):
            todo.db_manager.restore_from_database()
        self.assertIn(t("The restore failed."), tampon.getvalue())

    @patch("script.todo.database_manager.os.path.isfile", return_value=True)
    @patch("builtins.input")
    def test_the_neutralize_chain_follows_the_flag_not_the_status(
        self, saisie, _isfile
    ):
        """`more_arg` dit qu'on a demandé la neutralisation ; `status` dit
        si la commande d'avant a réussi. Les confondre enchaînait sur une
        base que la restauration venait d'échouer à créer."""
        saisie.side_effect = ["1", "sauvegarde", "cible", "", "n"]
        todo = menu(statuts=(0, 0))
        todo.db_manager.restore_from_database()
        lancees = commandes(todo)
        self.assertEqual(2, len(lancees))
        self.assertIn("update_prod_to_dev.sh", lancees[1])

    @patch("script.todo.database_manager.os.path.isfile", return_value=True)
    @patch("builtins.input")
    def test_refusing_the_neutralize_runs_nothing_after(self, saisie, _isfile):
        """Le contrôle NÉGATIF du précédent. Après le refus du code non
        nul, `status` vaut toujours zéro : tester `status` plutôt que le
        drapeau se lit pareil sur le chemin qui réussit, et lance
        update_prod_to_dev sur une base qu'on n'a pas neutralisée."""
        saisie.side_effect = ["1", "sauvegarde", "cible", "n", "n"]
        todo = menu(statuts=(0,))
        todo.db_manager.restore_from_database()
        self.assertEqual(1, len(commandes(todo)))

    @patch("script.todo.database_manager.os.path.isfile", return_value=True)
    @patch("builtins.input")
    def test_a_failed_neutralize_stops_before_the_addons(
        self, saisie, _isfile
    ):
        saisie.side_effect = ["1", "sauvegarde", "cible", "", "y"]
        todo = menu(statuts=(0, 1))
        todo.db_manager.restore_from_database()
        self.assertEqual(2, len(commandes(todo)))


class TestLesDeuxNomsSontCites(unittest.TestCase):
    """Ils traversent un f-string exécuté par bash (`shell=True`). Un nom
    tapé au clavier y devenait une commande.

    L'ÉPREUVE DÉCOUPE COMME BASH. Chercher le texte dangereux dans la
    chaîne ne prouve rien : cité, il s'y trouve toujours, et c'est bien le
    but. Ce qui se tient est qu'il reste UN SEUL MOT après découpage —
    donc un argument, jamais une commande de plus.
    """

    @patch("script.todo.database_manager.os.path.isfile", return_value=True)
    @patch("builtins.input")
    def test_a_database_name_stays_one_single_word(self, saisie, _isfile):
        saisie.side_effect = ["1", "sauvegarde", "a; touch pris", "n", "n"]
        todo = menu()
        todo.db_manager.restore_from_database()
        mots = shlex.split(commandes(todo)[0])
        self.assertIn("a; touch pris", mots)
        self.assertNotIn("touch", mots)

    @patch("script.todo.database_manager.os.path.isfile", return_value=True)
    @patch("builtins.input")
    def test_an_image_name_stays_one_too(self, saisie, _isfile):
        """Le nom d'IMAGE traverse le même f-string, et aucune garde ne le
        lisait : elles ne regardaient que le nom de base."""
        saisie.side_effect = ["1", "a; touch pris", "cible", "n", "n"]
        todo = menu()
        todo.db_manager.restore_from_database()
        mots = shlex.split(commandes(todo)[0])
        self.assertIn("a; touch pris", mots)
        self.assertNotIn("touch", mots)


class TestLaBrancheDuNavigateur(unittest.TestCase):
    """Le basename portait « .zip » et `image_path` en rajoutait un."""

    @patch("script.todo.database_manager.os.path.isfile", return_value=True)
    @patch("builtins.input")
    def test_the_suffix_is_not_doubled(self, saisie, _isfile):
        saisie.side_effect = ["", "", "n", "n"]
        todo = menu()
        chemin = os.path.join(os.getcwd(), "image_db", "sauvegarde.zip")
        todo.db_manager.open_file_image_db = (
            lambda: todo.db_manager._on_dir_selected(chemin)
        )
        todo.db_manager.restore_from_database()
        self.assertIn("--image sauvegarde", commandes(todo)[0])
        self.assertNotIn(".zip", commandes(todo)[0])

    @patch("builtins.input")
    def test_leaving_the_browser_without_choosing_launches_nothing(
        self, saisie
    ):
        """`q` ou `esc` laisse le chemin vide, et le basename d'une chaîne
        vide est vide : la commande partait avec « --image » sans valeur."""
        saisie.side_effect = ["", "", "n", "n"]
        todo = menu()
        todo.db_manager.open_file_image_db = lambda: None
        todo.db_manager.restore_from_database()
        self.assertEqual([], commandes(todo))


if __name__ == "__main__":
    unittest.main()
