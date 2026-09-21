#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Tests unitaires d'un module Odoo qui n'exigent NI base de données NI
# serveur : ceux qui dérivent de BaseCase plutôt que de TransactionCase.
#
# Odoo découvre ses modules par « addons_path », jamais par PYTHONPATH :
# « odoo.addons » est un paquet à espace de noms que le serveur peuple à son
# démarrage depuis cette liste. Importer « odoo.addons.<module>.tests.<x> »
# hors du serveur échoue donc quel que soit le PYTHONPATH, avec un
# ModuleNotFoundError qui désigne le module plutôt que la cause.
#
# Ce script peuple « odoo.addons.__path__ » depuis config.conf, charge les
# modules de test nommés en argument, et rend le code de sortie d'unittest —
# ce qui le rend utilisable tel quel dans une cible make.
#
# Un test qui demande une base échoue ici, bruyamment. C'est voulu : il n'a
# rien à faire dans une suite qui promet de tourner en quelques secondes,
# sans PostgreSQL, et le dire vaut mieux que l'ignorer.
#
#   script/test/run_module_unit_test.py <module>.tests.<fichier> [...]

import configparser
import os
import sys
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _version_odoo():
    """Rend la version Odoo du checkout, qui nomme le répertoire du serveur."""
    with open(os.path.join(RACINE, ".odoo-version")) as fichier:
        return fichier.read().strip()


def _chemins_addons():
    """Rend la liste addons_path de config.conf, dans son ordre.

    configparser lit le fichier tel que le serveur le lit ; composer la
    liste de tête la ferait dériver du jour où un dépôt y est ajouté.
    """
    config = configparser.ConfigParser()
    config.read(os.path.join(RACINE, "config.conf"))
    brut = config.get("options", "addons_path", fallback="")
    return [chemin.strip() for chemin in brut.split(",") if chemin.strip()]


def preparer_odoo():
    """Rend « odoo.addons » capable de résoudre les modules du checkout."""
    sys.path.insert(0, os.path.join(RACINE, f"odoo{_version_odoo()}", "odoo"))
    import odoo.addons

    for chemin in _chemins_addons():
        if chemin not in odoo.addons.__path__ and os.path.isdir(chemin):
            odoo.addons.__path__.append(chemin)


def main(noms):
    if not noms:
        print(
            "usage: script/test/run_module_unit_test.py"
            " <module>.tests.<fichier> [...]",
            file=sys.stderr,
        )
        return 2

    preparer_odoo()

    chargeur = unittest.TestLoader()
    suite = unittest.TestSuite()
    for nom in noms:
        module = __import__(f"odoo.addons.{nom}", fromlist=["*"])
        suite.addTests(chargeur.loadTestsFromModule(module))

    if suite.countTestCases() == 0:
        # Zéro test n'est PAS « zéro échec » : c'est une suite qui n'a rien
        # trouvé. Sans ce garde, un nom de module mal orthographié rend un
        # vert que personne n'a mérité.
        print("ÉCHEC : aucun test dans les modules nommés.", file=sys.stderr)
        return 2

    resultat = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if resultat.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
