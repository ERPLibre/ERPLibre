#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les options que SeleniumLib donne à Chrome.

Sans --window_size, Chrome prend la taille de Firefox headless : sa fenêtre
par défaut sans écran est trop étroite pour la barre de statut du client
web. --headless lui est transmis. --use_firefox_driver, vrai par défaut, ne
désigne plus Firefox quand --use_chrome_driver est donné : Chrome recevait
les extensions de Firefox et s'arrêtait au démarrage. Le pilote Chrome est
remplacé par un simulacre ; aucun navigateur ne s'ouvre.
"""

import argparse
import os
import sys
import unittest
from unittest import mock

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.selenium import selenium_lib  # noqa: E402


def options_chrome(*argv):
    """Les arguments passés à Chrome, et si une extension a été installée."""
    parser = argparse.ArgumentParser()
    selenium_lib.fill_parser(parser)
    config = parser.parse_args(
        ["--use_chrome_driver", "--url", "http://odoo.essai.invalid", *argv]
    )
    with (
        mock.patch.object(selenium_lib.webdriver, "Chrome") as chrome,
        mock.patch("selenium.webdriver.chrome.service.Service"),
        mock.patch("builtins.print"),
    ):
        outil = selenium_lib.SeleniumLib(config)
        outil.configure(ignore_open_web=True)
    arguments = chrome.call_args.kwargs["options"].arguments
    return arguments, outil.driver.install_addon.called


class TestOptionsChrome(unittest.TestCase):
    def test_sans_taille_la_fenetre_prend_celle_de_firefox_headless(self):
        arguments, _ = options_chrome("--headless")
        self.assertIn(
            f"--window-size={selenium_lib.CHROME_WINDOW_SIZE_DEFAULT}",
            arguments,
        )

    def test_la_taille_demandee_l_emporte(self):
        arguments, _ = options_chrome("--window_size", "1920,1080")
        self.assertIn("--window-size=1920,1080", arguments)
        self.assertEqual(
            1, sum(a.startswith("--window-size=") for a in arguments)
        )

    def test_headless_est_transmis(self):
        self.assertIn("--headless=new", options_chrome("--headless")[0])
        self.assertNotIn("--headless=new", options_chrome()[0])

    def test_chrome_ne_recoit_pas_les_extensions_de_firefox(self):
        """Sans --no_dark_mode, Firefox installe Dark Reader ; Chrome n'a
        pas cette commande et s'arrêtait au démarrage."""
        _, extension = options_chrome("--headless")
        self.assertFalse(extension)


if __name__ == "__main__":
    unittest.main()
