#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce que l'image Docker lit au démarrage vaut-il pour Odoo 10 à 20 ?

Deux fichiers sont partagés par toutes les versions. docker/odoo.conf doit
nommer l'interface d'écoute : Odoo 20 remplace une valeur vide par
127.0.0.1, et le port publié du conteneur ne mène alors à rien.
docker/wait-for-psql.py est lancé par le python de l'image, en 2.7 pour
Odoo 10 : sans déclaration d'encodage, un seul caractère non ASCII y est une
SyntaxError, et le conteneur redémarre en boucle.
"""

import configparser
import re
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]


class TestOdooConfEcouteHorsDuConteneur(unittest.TestCase):
    def test_l_interface_est_nommee_et_non_locale(self):
        conf = configparser.ConfigParser(
            comment_prefixes=("#", ";"), interpolation=None, strict=False
        )
        conf.read(RACINE / "docker/odoo.conf", encoding="utf-8")
        self.assertEqual(
            "0.0.0.0", conf.get("options", "http_interface", fallback="")
        )


class TestWaitForPsqlSeLitEnPython2(unittest.TestCase):
    def test_un_fichier_non_ascii_declare_son_encodage(self):
        brut = (RACINE / "docker/wait-for-psql.py").read_bytes()
        if brut.isascii():
            return
        # PEP 263 : la déclaration doit tenir dans l'une des deux premières
        # lignes, sinon Python 2 la cherche en vain.
        tete = brut.decode("utf-8").splitlines()[:2]
        self.assertTrue(
            any(re.search(r"coding[:=]\s*utf-?8", l) for l in tete), tete
        )


if __name__ == "__main__":
    unittest.main()
