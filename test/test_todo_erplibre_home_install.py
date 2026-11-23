#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Les deux entrées d'installation locale du menu ERPLibre Home.

« Installer l'extension GNOME (local) » pose la base, « Installer le Stream
Deck » le niveau Stream Deck, extension comprise. Les deux lancent
le même installateur, la seconde avec --stream-deck, après trois questions
dont les réponses par défaut donnent --deck-program=tiler : ces tests-ci
répondent Entrée à chacune. Les autres réponses sont gardées par
test_todo_streamdeck_menu.py.

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
import tempfile
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
        # Les questions de l'installation Stream Deck lisent les réglages :
        # un HOME vide les rend absents, donc les défauts.
        dossier = tempfile.TemporaryDirectory()
        self.addCleanup(dossier.cleanup)
        environ = mock.patch.dict(os.environ, {"HOME": dossier.name})
        environ.start()
        self.addCleanup(environ.stop)
        os.environ.pop("XDG_CONFIG_HOME", None)

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

    def test_les_entrees_et_leurs_issues_se_lisent_en_francais(self):
        """t() d'une clé absente rend la clé, en anglais : chaque libellé
        et chaque ligne d'issue doit avoir sa traduction française."""
        todo_i18n._current_lang = "fr"
        libelles = {
            "Install the GNOME extension (local)": (
                "📦 Installer l'extension GNOME (local)"
            ),
            "Install the Stream Deck (adds the extension if needed)": (
                "📦 Installer le Stream Deck (ajoute l'extension au besoin)"
            ),
        }
        for cle, attendu in libelles.items():
            with self.subTest(cle=cle):
                self.assertEqual(todo_i18n.t(cle), attendu)
        issues = (
            (0, [], "✅ ERPLibre Home installé. Fermer la session"),
            (1, [], "❌ L'installation d'ERPLibre Home a échoué"),
            (
                2,
                ["UNSUPPORTED: GNOME 52 not in shell-version"],
                "ERPLibre Home non pris en charge sur ce système :"
                " GNOME 52 not in shell-version",
            ),
            (
                2,
                [],
                "ERPLibre Home non pris en charge sur ce système :"
                " aucune raison donnée par l'installateur",
            ),
        )
        for methode in ENTREES:
            for code, lignes, attendu in issues:
                with self.subTest(methode=methode, code=code, lignes=lignes):
                    _, sortie, _ = self.lancer(methode, code, lignes)
                    self.assertIn(attendu, sortie)

    def test_le_menu_installation_offre_s_pour_le_stream_deck(self):
        """« s » du choix de version d'Installation mène à la même entrée
        que le menu ERPLibre Home, ses quatre questions comprises : aucune
        commande n'est lancée par le choix de version lui-même."""
        todo = TODO.__new__(TODO)
        todo.execute = ExecuteFactice(0)
        questions = []

        def repondre(question=""):
            # Un « s » refusé repose la question : « 0 » y met fin.
            questions.append(question)
            if "Choose a version:" not in question:
                return "n"
            deja = sum("Choose a version:" in q for q in questions)
            return "s" if deja == 1 else "0"

        absent = mock.Mock(returncode=1)
        sortie = io.StringIO()
        with (
            contextlib.redirect_stdout(sortie),
            mock.patch("builtins.input", side_effect=repondre),
            mock.patch(
                "script.todo.todo.get_odoo_version",
                return_value=([], [], None),
            ),
            mock.patch(
                "script.todo.todo.subprocess.run", return_value=absent
            ) as lance,
            mock.patch.object(
                TODO,
                "_erplibre_home_choose_install",
                return_value=False,
            ) as entree,
        ):
            todo.prompt_install()
        entree.assert_called_once_with()
        choix = [q for q in questions if "Choose a version:" in q]
        self.assertEqual(len(choix), 1)
        self.assertIn(
            "s: ERPLibre Home with the GNOME extension and the Stream Deck",
            choix[0],
        )
        for appel in lance.call_args_list:
            self.assertNotIn(INSTALLATEUR, str(appel))
        self.assertEqual(todo.execute.appels, [])

    def choisir(self, reponses, niveau="none"):
        """Lance _erplibre_home_choose_install avec `reponses` au clavier ;
        rend (base, stream_deck, questions, sortie) : les deux entrées
        d'installation simulées et les questions posées."""
        todo = TODO.__new__(TODO)
        questions = []
        suite = iter(reponses)

        def repondre(question=""):
            questions.append(question)
            return next(suite)

        sortie = io.StringIO()
        with (
            contextlib.redirect_stdout(sortie),
            mock.patch("builtins.input", side_effect=repondre),
            mock.patch(
                "script.todo.todo.erplibre_home_status.installed_level",
                return_value=niveau,
            ),
            mock.patch.object(
                TODO, "_erplibre_home_install_local", return_value=False
            ) as base,
            mock.patch.object(
                TODO,
                "_erplibre_home_streamdeck_install_local",
                return_value=False,
            ) as deck,
        ):
            rendu = todo._erplibre_home_choose_install()
        self.assertIs(rendu, False)
        return base, deck, questions, sortie.getvalue()

    def test_s_asks_the_extension_then_the_stream_deck(self):
        """Les deux questions viennent avant celles de l'installation
        Stream Deck (le programme du deck) : l'extension d'abord, oui par
        défaut, puis le Stream Deck, non par défaut."""
        base, deck, questions, _ = self.choisir(["", "o"])
        self.assertEqual(len(questions), 2)
        self.assertIn("GNOME extension", questions[0])
        self.assertIn("(Y/n)", questions[0])
        self.assertIn("Stream Deck", questions[1])
        self.assertIn("(y/N)", questions[1])
        deck.assert_called_once_with()
        base.assert_not_called()

    def test_s_without_the_stream_deck_installs_the_extension_alone(self):
        for reponse in ("", "n", "non"):
            with self.subTest(reponse=reponse):
                base, deck, _, _ = self.choisir(["o", reponse])
                base.assert_called_once_with()
                deck.assert_not_called()

    def test_s_without_the_extension_installs_nothing(self):
        """Le Stream Deck exige l'extension : la refuser n'installe rien,
        ne pose pas la seconde question et le dit."""
        for reponse in ("n", "non", "N"):
            with self.subTest(reponse=reponse):
                base, deck, questions, sortie = self.choisir([reponse])
                base.assert_not_called()
                deck.assert_not_called()
                self.assertEqual(len(questions), 1)
                self.assertIn("Nothing to install", sortie)

    def test_with_the_extension_only_s_offers_the_stream_deck(self):
        """L'extension en place : seul l'ajout du Stream Deck est demandé,
        et l'ajouter lance l'installation Stream Deck, qui garde la base."""
        base, deck, questions, sortie = self.choisir(["o"], "base")
        self.assertEqual(len(questions), 1)
        self.assertIn("Stream Deck", questions[0])
        self.assertIn("already installed", sortie)
        deck.assert_called_once_with()
        base.assert_not_called()

    def test_with_the_extension_only_no_stream_deck_changes_nothing(self):
        base, deck, _, _ = self.choisir([""], "base")
        base.assert_not_called()
        deck.assert_not_called()

    def test_with_both_installed_s_offers_a_reinstall(self):
        for reponse, relance in (("o", True), ("", False), ("n", False)):
            with self.subTest(reponse=reponse):
                base, deck, questions, sortie = self.choisir(
                    [reponse], "stream_deck"
                )
                self.assertEqual(len(questions), 1)
                self.assertIn("Reinstall", questions[0])
                self.assertIn("already installed", sortie)
                self.assertEqual(relance, deck.called)
                base.assert_not_called()

    def test_the_two_questions_read_in_french(self):
        todo_i18n._current_lang = "fr"
        self.addCleanup(setattr, todo_i18n, "_current_lang", "en")
        _, _, questions, _ = self.choisir(["o", "n"])
        self.assertIn("extension GNOME", questions[0])
        self.assertIn("(O/n)", questions[0])
        self.assertIn("(o/N)", questions[1])

    def test_l_entree_s_du_menu_installation_se_lit_en_francais(self):
        """Le libellé de « s » passe par t() comme ses voisins du choix de
        version."""
        todo_i18n._current_lang = "fr"
        todo = TODO.__new__(TODO)
        todo.execute = ExecuteFactice(0)
        questions = []

        def repondre(question=""):
            questions.append(question)
            return "0"

        with (
            contextlib.redirect_stdout(io.StringIO()) as sortie,
            mock.patch("builtins.input", side_effect=repondre),
            mock.patch(
                "script.todo.todo.get_odoo_version",
                return_value=([], [], None),
            ),
        ):
            todo.prompt_install()
        menu = "".join(questions) + sortie.getvalue()
        self.assertIn(
            "s: ERPLibre Home avec l'extension GNOME et le Stream Deck", menu
        )

    def test_l_installateur_appele_existe_et_s_execute(self):
        chemin = RACINE / INSTALLATEUR
        self.assertTrue(chemin.is_file(), f"{INSTALLATEUR} absent")
        self.assertTrue(
            os.access(chemin, os.X_OK), f"{INSTALLATEUR} non exécutable"
        )


if __name__ == "__main__":
    unittest.main()
