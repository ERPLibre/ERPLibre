#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le sélecteur de fichier : choisir doit fermer l'écran, annuler doit exister.

Le défaut que ces tests verrouillent : `select_file` appelait bien le callback
mais ne quittait pas la boucle urwid. Le choix était donc enregistré et
l'écran restait ouvert, sans aucune touche pour le fermer — le sélecteur
paraissait figé au moment précis où il venait de faire son travail. Seul
Ctrl+C en sortait, ce qui abandonnait l'opération.

`ExitMainLoop` est ce qui termine une boucle urwid : la lever EST la
fermeture. Ces tests l'attendent donc comme un succès, pas comme une erreur.
"""

import os
import tempfile
import unittest

import urwid

from script.todo.todo_file_browser import FileBrowser


class BrowserCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp()
        open(os.path.join(self.directory, "sauvegarde.zip"), "w").close()
        os.mkdir(os.path.join(self.directory, "sous_dossier"))
        self.chosen = []

    def browser(self, **kwargs):
        return FileBrowser(self.directory, self.chosen.append, **kwargs)

    def button(self, browser, label):
        for widget in browser.list_walker:
            if isinstance(widget, urwid.Button) and widget.label == label:
                return widget
        raise AssertionError(f"bouton '{label}' absent")


class TestChoosingClosesTheBrowser(BrowserCase):
    def test_selecting_a_file_reports_it_and_ends_the_loop(self):
        browser = self.browser()
        with self.assertRaises(urwid.ExitMainLoop):
            browser.select_file(self.button(browser, "sauvegarde.zip"))
        self.assertEqual(
            self.chosen, [os.path.join(self.directory, "sauvegarde.zip")]
        )

    def test_selecting_a_directory_reports_it_and_ends_the_loop(self):
        browser = self.browser(open_dir=True)
        with self.assertRaises(urwid.ExitMainLoop):
            browser.select_directory(self.button(browser, "."))
        self.assertEqual(self.chosen, [self.directory])


class TestNavigatingDoesNotClose(BrowserCase):
    """Se déplacer n'est pas choisir : la boucle doit continuer."""

    def test_entering_a_directory(self):
        browser = self.browser()
        browser.open_directory(self.button(browser, "sous_dossier/"))
        self.assertEqual(
            browser.current_path, os.path.join(self.directory, "sous_dossier")
        )
        self.assertEqual(self.chosen, [])

    def test_going_up(self):
        browser = self.browser()
        browser.go_up_directory(None)
        self.assertEqual(browser.current_path, os.path.dirname(self.directory))
        self.assertEqual(self.chosen, [])

    def test_arrow_keys_do_not_quit(self):
        browser = self.browser()
        for key in ("up", "down", "enter", "a"):
            browser.unhandled_input(key)
        self.assertEqual(self.chosen, [])


class TestCancelling(BrowserCase):
    """Sortir sans choisir doit être possible.

    Toutes les autres sorties sélectionnent quelque chose. Un appelant qui
    propose une solution de rechange — taper un chemin — ne devient
    atteignable que si l'on peut renoncer.
    """

    def test_q_and_escape_quit_without_choosing(self):
        for key in ("q", "Q", "esc"):
            browser = self.browser()
            with self.assertRaises(urwid.ExitMainLoop):
                browser.unhandled_input(key)
            self.assertEqual(self.chosen, [], key)


class TestListing(BrowserCase):
    def test_files_are_offered_when_picking_a_file(self):
        labels = [
            w.label
            for w in self.browser().list_walker
            if isinstance(w, urwid.Button)
        ]
        self.assertIn("sauvegarde.zip", labels)
        self.assertIn("sous_dossier/", labels)

    def test_files_are_hidden_when_picking_a_directory(self):
        labels = [
            w.label
            for w in self.browser(open_dir=True).list_walker
            if isinstance(w, urwid.Button)
        ]
        self.assertNotIn("sauvegarde.zip", labels)
        self.assertIn(".", labels)

    def test_an_unreadable_directory_does_not_crash(self):
        browser = self.browser()
        browser.current_path = os.path.join(self.directory, "nowhere")
        browser.refresh_list()
        self.assertTrue(len(browser.list_walker) >= 1)


if __name__ == "__main__":
    unittest.main()
