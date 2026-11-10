#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""SeleniumLib sur une machine sans écran ni Firefox, un conteneur ERPLibre :
le binaire Firefox qu'il cherche, et le coffre KeePass qu'il ouvre.

Ce que ces tests gardent :

- Firefox se cherche dans l'ordre snap, « firefox », « firefox-esr » ; sans
  aucun, FirefoxIntrouvable dit quoi faire au lieu d'un CalledProcessError
  de « which » ;
- configure() laisse FirefoxIntrouvable remonter tel quel, sans autre
  message ; une autre panne au démarrage du pilote remonte elle aussi, sous
  un seul message qui ne promet aucun repli ;
- le coffre s'ouvre par KdbxManager, et un coffre qui ne s'ouvre pas lève
  KdbxIndisponible au lieu de rendre None.
"""

import argparse
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.selenium import selenium_lib  # noqa: E402


def trouver(snap=False, presents=()):
    """trouver_firefox() quand le snap existe ou non et que ``presents``
    sont les seuls noms du PATH."""
    with (
        mock.patch.object(selenium_lib.Path, "exists", lambda self: snap),
        mock.patch.object(
            selenium_lib.shutil,
            "which",
            lambda nom: f"/usr/bin/{nom}" if nom in presents else None,
        ),
    ):
        return selenium_lib.trouver_firefox()


class TestTrouverFirefox(unittest.TestCase):
    def test_le_snap_passe_en_premier(self):
        self.assertEqual(
            selenium_lib.FIREFOX_SNAP,
            trouver(snap=True, presents=("firefox",)),
        )

    def test_firefox_avant_firefox_esr(self):
        self.assertEqual(
            "/usr/bin/firefox", trouver(presents=("firefox", "firefox-esr"))
        )

    def test_firefox_esr_seul_comme_sous_debian(self):
        self.assertEqual(
            "/usr/bin/firefox-esr", trouver(presents=("firefox-esr",))
        )

    def test_aucun_firefox_dit_quoi_faire(self):
        with self.assertRaises(selenium_lib.FirefoxIntrouvable) as erreur:
            trouver()
        message = str(erreur.exception)
        self.assertIn("firefox-esr", message)
        self.assertIn("--firefox_binary_path", message)
        self.assertIn("--use_network", message)


def configurer_firefox(trouver):
    """SeleniumLib.configure() pour Firefox local, ``trouver`` remplaçant
    trouver_firefox et webdriver.Firefox levant RuntimeError. Rend
    (exception levée, lignes affichées)."""
    parser = argparse.ArgumentParser()
    selenium_lib.fill_parser(parser)
    config = parser.parse_args(
        ["--url", "http://odoo.essai.invalid", "--headless"]
    )
    vues = []
    with (
        tempfile.TemporaryDirectory() as racine,
        mock.patch.object(tempfile, "tempdir", racine),
        mock.patch.object(selenium_lib, "trouver_firefox", trouver),
        mock.patch.object(
            selenium_lib.webdriver,
            "Firefox",
            side_effect=RuntimeError("geckodriver absent"),
        ),
        mock.patch(
            "builtins.print",
            side_effect=lambda *a, **k: vues.append(" ".join(map(str, a))),
        ),
    ):
        outil = selenium_lib.SeleniumLib(config)
        try:
            outil.configure(ignore_open_web=True)
        except Exception as e:
            return e, vues
    raise AssertionError("configure() n'a rien levé")


class TestDemarrageFirefox(unittest.TestCase):
    def test_firefox_introuvable_remonte_sans_autre_message(self):
        absent = selenium_lib.FirefoxIntrouvable("aucun Firefox")

        def trouver():
            raise absent

        erreur, vues = configurer_firefox(trouver)
        self.assertIs(absent, erreur)
        self.assertFalse([v for v in vues if "snap" in v.lower()], vues)
        self.assertFalse([v for v in vues if "web driver" in v], vues)

    def test_une_autre_panne_remonte_sans_promettre_de_repli(self):
        erreur, vues = configurer_firefox(lambda: "/usr/bin/firefox")
        self.assertIsInstance(erreur, RuntimeError)
        self.assertEqual("geckodriver absent", str(erreur))
        self.assertIn("Cannot start the web driver, cause below.", vues)
        self.assertFalse([v for v in vues if "snap" in v.lower()], vues)


class TestGetKdbx(unittest.TestCase):
    def outil(self):
        """Un SeleniumLib sans constructeur : get_kdbx ne lit que son
        coffre en cache et sa configuration."""
        outil = selenium_lib.SeleniumLib.__new__(selenium_lib.SeleniumLib)
        outil.kdbx = None
        outil.config_file = mock.MagicMock()
        return outil

    def test_un_coffre_ferme_leve_au_lieu_de_rendre_none(self):
        with (
            mock.patch.object(selenium_lib, "KdbxManager") as gestionnaire,
            mock.patch("builtins.print"),
        ):
            gestionnaire.return_value.get_kdbx.return_value = None
            with self.assertRaises(selenium_lib.KdbxIndisponible) as erreur:
                self.outil().get_kdbx()
        message = str(erreur.exception)
        self.assertIn("kdbx.path", message)
        self.assertIn("KDBX_PASSWORD_FILE", message)

    def test_le_coffre_ouvert_est_garde(self):
        outil = self.outil()
        coffre = object()
        with (
            mock.patch.object(selenium_lib, "KdbxManager") as gestionnaire,
            mock.patch("builtins.print"),
        ):
            gestionnaire.return_value.get_kdbx.return_value = coffre
            self.assertIs(coffre, outil.get_kdbx())
            self.assertIs(coffre, outil.get_kdbx())
        self.assertEqual(1, gestionnaire.return_value.get_kdbx.call_count)
        gestionnaire.assert_called_with(outil.config_file)


if __name__ == "__main__":
    unittest.main()
