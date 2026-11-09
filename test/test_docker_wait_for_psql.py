#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""docker/wait-for-psql.py devant un faux psycopg2 et une fausse horloge :
aucune base n'est jointe et aucune attente n'est réelle.

Le script s'exécute dans ce processus, sous runpy. Le faux psycopg2 rend,
appel après appel, les issues d'une liste : une erreur OperationalError ou
une connexion qui note sa fermeture. time.sleep avance la fausse horloge que
lit time.time.

Ce que ces tests gardent :

- une connexion réussie après des échecs sort en 0 : le premier démarrage
  d'un compose, sur une base qui s'initialise, ne s'arrête pas ;
- la connexion réussie est fermée ;
- des échecs jusqu'au délai sortent en 1, sur l'erreur de la dernière
  tentative ;
- une tentative a lieu même avec un délai nul.
"""

import contextlib
import io
import runpy
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parent.parent
SCRIPT = RACINE / "docker" / "wait-for-psql.py"

ARGUMENTS = [
    "--db_host",
    "hote-invente",
    "--db_port",
    "5432",
    "--db_user",
    "essai",
    "--db_password",
    "mdp-invente",
]


class FausseConnexion:
    def __init__(self):
        self.fermee = False

    def close(self):
        self.fermee = True


def faux_psycopg2(issues):
    """Un module psycopg2 dont connect rend, dans l'ordre, les issues :
    « echec » lève OperationalError, « succes » rend une FausseConnexion.
    Rend le module, la liste des connexions rendues et le compteur
    d'appels."""
    module = types.ModuleType("psycopg2")

    class OperationalError(Exception):
        pass

    module.OperationalError = OperationalError
    connexions = []
    appels = [0]

    def connect(**_kwargs):
        rang = appels[0]
        appels[0] += 1
        issue = issues[min(rang, len(issues) - 1)]
        if issue == "echec":
            raise OperationalError(f"tentative {rang + 1} refusée")
        connexion = FausseConnexion()
        connexions.append(connexion)
        return connexion

    module.connect = connect
    return module, connexions, appels


def lancer(issues, *options):
    """Exécute le script avec les issues données ; rend le code de sortie,
    la sortie d'erreur, les connexions rendues et le nombre d'appels."""
    module, connexions, appels = faux_psycopg2(issues)
    horloge = [1000.0]

    def dormir(secondes):
        horloge[0] += secondes

    erreur = io.StringIO()
    with mock.patch.dict(sys.modules, {"psycopg2": module}), mock.patch(
        "time.time", lambda: horloge[0]
    ), mock.patch("time.sleep", dormir), mock.patch.object(
        sys, "argv", [str(SCRIPT), *ARGUMENTS, *options]
    ), contextlib.redirect_stdout(
        io.StringIO()
    ), contextlib.redirect_stderr(
        erreur
    ):
        try:
            runpy.run_path(str(SCRIPT), run_name="__main__")
            code = 0
        except SystemExit as sortie:
            code = sortie.code
    return code, erreur.getvalue(), connexions, appels[0]


class TestWaitForPsql(unittest.TestCase):
    def test_un_succes_apres_des_echecs_sort_en_zero(self):
        code, erreur, connexions, appels = lancer(
            ["echec", "echec", "succes"], "--timeout", "10"
        )
        self.assertEqual(0, code, erreur)
        self.assertEqual("", erreur)
        self.assertEqual(3, appels)
        self.assertEqual(1, len(connexions))
        self.assertTrue(connexions[0].fermee)

    def test_un_succes_d_emblee_sort_en_zero(self):
        code, erreur, connexions, appels = lancer(["succes"])
        self.assertEqual(0, code, erreur)
        self.assertEqual(1, appels)
        self.assertTrue(connexions[0].fermee)

    def test_des_echecs_jusqu_au_delai_sortent_en_un(self):
        code, erreur, connexions, appels = lancer(["echec"], "--timeout", "3")
        self.assertEqual(1, code)
        self.assertEqual([], connexions)
        # Une tentative par seconde de fausse horloge, la dernière au délai.
        self.assertEqual(4, appels)
        self.assertIn("Database connection failure", erreur)
        self.assertIn("tentative 4 refusée", erreur)

    def test_un_delai_nul_tente_une_fois(self):
        code, erreur, _, appels = lancer(["echec"], "--timeout", "0")
        self.assertEqual(1, code)
        self.assertEqual(1, appels)
        self.assertIn("tentative 1 refusée", erreur)


if __name__ == "__main__":
    unittest.main()
