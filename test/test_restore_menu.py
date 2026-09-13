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
from script.database import drill_guard  # noqa: E402
from script.todo.todo import TODO  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402


def menu(statuts=(0, 0, 0), bases=()):
    """Un menu dont l'exécution est simulée.

    La PREMIÈRE commande lancée est toujours « db --list » : la porte lit
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
        if "db --list" not in appel[0][0]
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
                saisie.side_effect = ["1", "sauvegarde", "reelle", "n", "non"]
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
