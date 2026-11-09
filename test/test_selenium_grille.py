#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les identifiants du routeur d'une grille Selenium (--use_network), et
la ligne d'aide d'une session que la grille refuse sans --headless.

Le routeur du compose Selenium exige une authentification Basic.
client_grille rend l'adresse de pilotage sans identifiants et une
ClientConfig qui les porte : de l'URL, décodés, sinon de l'environnement.
SeleniumLib les passe à webdriver.Remote, remplacé ici par un simulacre ;
aucune grille n'est contactée.
"""

import argparse
import base64
import os
import sys
import tempfile
import unittest
from unittest import mock

from selenium.common.exceptions import (
    SessionNotCreatedException,
    WebDriverException,
)

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.selenium import selenium_lib  # noqa: E402

SANS_ENV = {
    selenium_lib.ENV_ROUTEUR_UTILISATEUR: "",
    selenium_lib.ENV_ROUTEUR_MOT_DE_PASSE: "",
}


def basic(utilisateur, mot_de_passe):
    jeton = base64.b64encode(f"{utilisateur}:{mot_de_passe}".encode())
    return {"Authorization": f"Basic {jeton.decode()}"}


class TestClientGrille(unittest.TestCase):
    def test_identifiants_de_l_url_retires_de_l_adresse_et_decodes(self):
        with mock.patch.dict(os.environ, SANS_ENV):
            adresse, config = selenium_lib.client_grille(
                "http://pilote:a%40b%3Ac@127.0.0.1:8075"
            )
        self.assertEqual(adresse, "http://127.0.0.1:8075/wd/hub")
        self.assertEqual(config.remote_server_addr, adresse)
        self.assertEqual(config.get_auth_header(), basic("pilote", "a@b:c"))

    def test_sans_identifiants_dans_l_url_l_environnement_les_donne(self):
        env = {
            selenium_lib.ENV_ROUTEUR_UTILISATEUR: "pilote",
            selenium_lib.ENV_ROUTEUR_MOT_DE_PASSE: "essai-routeur",
        }
        with mock.patch.dict(os.environ, env):
            adresse, config = selenium_lib.client_grille(
                "http://127.0.0.1:8075"
            )
        self.assertEqual(adresse, "http://127.0.0.1:8075/wd/hub")
        self.assertEqual(
            config.get_auth_header(), basic("pilote", "essai-routeur")
        )

    def test_l_url_l_emporte_sur_l_environnement(self):
        env = {
            selenium_lib.ENV_ROUTEUR_UTILISATEUR: "autre",
            selenium_lib.ENV_ROUTEUR_MOT_DE_PASSE: "autre-secret",
        }
        with mock.patch.dict(os.environ, env):
            _, config = selenium_lib.client_grille(
                "http://pilote:essai@127.0.0.1:8075"
            )
        self.assertEqual(config.get_auth_header(), basic("pilote", "essai"))

    def test_sans_identifiants_aucune_authentification(self):
        with mock.patch.dict(os.environ, SANS_ENV):
            adresse, config = selenium_lib.client_grille(
                "http://localhost:4444"
            )
        self.assertEqual(adresse, "http://localhost:4444/wd/hub")
        self.assertIsNone(config.get_auth_header())


class TestRemoteRecoitLesIdentifiants(unittest.TestCase):
    def test_firefox_distant_recoit_la_client_config(self):
        parser = argparse.ArgumentParser()
        selenium_lib.fill_parser(parser)
        config = parser.parse_args(
            [
                "--use_network",
                "http://pilote:essai@127.0.0.1:8075",
                "--url",
                "http://odoo.essai.invalid",
                "--headless",
            ]
        )
        with (
            tempfile.TemporaryDirectory() as racine,
            mock.patch.object(tempfile, "tempdir", racine),
            mock.patch.dict(os.environ, SANS_ENV),
            mock.patch.object(selenium_lib.webdriver, "Remote") as remote,
            mock.patch("builtins.print"),
        ):
            outil = selenium_lib.SeleniumLib(config)
            outil.configure(ignore_open_web=True)
        kwargs = remote.call_args.kwargs
        self.assertEqual(
            kwargs["command_executor"], "http://127.0.0.1:8075/wd/hub"
        )
        self.assertEqual(
            kwargs["client_config"].get_auth_header(),
            basic("pilote", "essai"),
        )


def lancer_contre_grille(options, refus):
    """configure() d'un Firefox distant dont webdriver.Remote lève refus ;
    rend l'exception qui remonte et les lignes passées à print."""
    parser = argparse.ArgumentParser()
    selenium_lib.fill_parser(parser)
    config = parser.parse_args(
        [
            "--use_network",
            "http://127.0.0.1:8075",
            "--url",
            "http://odoo.essai.invalid",
        ]
        + options
    )
    with (
        tempfile.TemporaryDirectory() as racine,
        mock.patch.object(tempfile, "tempdir", racine),
        mock.patch.dict(os.environ, SANS_ENV),
        mock.patch.object(selenium_lib.webdriver, "Remote", side_effect=refus),
        mock.patch("builtins.print") as affiche,
    ):
        outil = selenium_lib.SeleniumLib(config)
        try:
            outil.configure(ignore_open_web=True)
        except Exception as erreur:
            remontee = erreur
        else:
            remontee = None
    lignes = [" ".join(map(str, c.args)) for c in affiche.call_args_list]
    return remontee, lignes


class TestGrilleSansEcran(unittest.TestCase):
    """Une grille dont aucun nœud n'ouvre la session rend une 500 « Could
    not start a new session » ; sans --headless, une ligne le rattache à
    l'absence d'écran des nœuds, et l'exception remonte toujours."""

    REFUS = SessionNotCreatedException(
        "Could not start a new session. Could not start a new session."
        " Error while creating session with the driver service."
    )

    def indices(self, lignes):
        return [ligne for ligne in lignes if "--headless" in ligne]

    def test_sans_headless_la_ligne_d_aide_s_affiche(self):
        remontee, lignes = lancer_contre_grille([], self.REFUS)
        self.assertIs(remontee, self.REFUS)
        self.assertEqual(1, len(self.indices(lignes)), lignes)

    def test_avec_headless_aucune_ligne_d_aide(self):
        remontee, lignes = lancer_contre_grille(["--headless"], self.REFUS)
        self.assertIs(remontee, self.REFUS)
        self.assertEqual([], self.indices(lignes))

    def test_une_autre_erreur_n_a_pas_de_ligne_d_aide(self):
        for refus in (
            WebDriverException("Connection refused"),
            OSError("Could not start a new session"),
        ):
            with self.subTest(refus=refus):
                remontee, lignes = lancer_contre_grille([], refus)
                self.assertIs(remontee, refus)
                self.assertEqual([], self.indices(lignes))


if __name__ == "__main__":
    unittest.main()
