#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'ordre des gestes de la restauration : ce qu'on vérifie avant de
détruire, et ce qu'on dit en détruisant.

LE DROP PRÉCÉDAIT LA RESTAURATION, ET RIEN NE REGARDAIT L'IMAGE. Un
« --image » mal tapé supprimait la base cible puis échouait sur un fichier
absent : il ne restait rien. Le contrôle du filestore lit bien ce chemin,
mais après la restauration — trop tard pour empêcher quoi que ce soit.

L'IMAGE N'EST EXIGÉE QUE SI ELLE VA SERVIR. Le dépôt compte des dizaines
de cibles make qui restaurent en clonant un cache déjà présent : exiger le
zip là refuserait des chaînes qui marchent, et une garde qui refuse à tort
finit désactivée.

Le module est chargé PAR SON CHEMIN : il n'est pas importable par son nom
de paquet, et une copie de sa logique dériverait de la sienne.

Les noms de base et d'image cités ici sont inventés.
"""

import contextlib
import importlib.util
import io
import os
import sys
import types
import unittest
from unittest.mock import patch

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)


def module():
    chemin = os.path.join(RACINE, "script", "database", "db_restore.py")
    spec = importlib.util.spec_from_file_location("dbr_banc", chemin)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


DBR = module()


def config(image="essai", only_drop=False, ignore_cache=False):
    return types.SimpleNamespace(
        image=image, only_drop=only_drop, ignore_cache=ignore_cache
    )


ABSENTE = staticmethod(lambda _chemin: False)
PRESENTE = staticmethod(lambda _chemin: True)


class TestLeCheminDeLImage(unittest.TestCase):
    """Composé à un seul endroit : recopié, il diverge le jour où le
    répertoire change de nom."""

    def test_it_names_the_zip_under_image_db(self):
        self.assertEqual(
            os.path.join("image_db", "essai.zip"), DBR.image_path("essai")
        )

    def test_the_filestore_check_uses_that_very_function(self):
        """Deux compositions du même chemin sont une divergence en
        attente."""
        import inspect

        source = inspect.getsource(DBR.verify_filestore)
        self.assertIn("image_path(image)", source)
        self.assertNotIn('os.path.join("image_db"', source)


class TestCeQuiEstVerifieAvantDeDetruire(unittest.TestCase):
    def test_a_missing_image_is_named_before_anything_is_dropped(self):
        self.assertEqual(
            os.path.join("image_db", "essai.zip"),
            DBR.missing_image(config(), [], exists=ABSENTE),
        )

    def test_a_present_image_lets_it_through(self):
        self.assertEqual("", DBR.missing_image(config(), [], exists=PRESENTE))

    def test_it_returns_the_path_and_not_a_boolean(self):
        """Un refus qui ne dit pas ce qu'il a cherché envoie fouiller
        image_db à la main."""
        manque = DBR.missing_image(config(), [], exists=ABSENTE)
        self.assertIn("essai", manque)

    def test_a_clone_from_an_existing_cache_needs_no_image(self):
        """Des dizaines de cibles make sont dans ce cas : le zip n'est
        jamais ouvert, et l'exiger les refuserait toutes."""
        self.assertEqual(
            "",
            DBR.missing_image(config(), ["_cache_essai"], exists=ABSENTE),
        )

    def test_ignore_cache_needs_the_image_even_with_a_cache(self):
        """Elle restaure DEPUIS l'image, cache ou pas."""
        self.assertEqual(
            os.path.join("image_db", "essai.zip"),
            DBR.missing_image(
                config(ignore_cache=True), ["_cache_essai"], exists=ABSENTE
            ),
        )

    def test_only_drop_needs_no_image(self):
        """Elle ne restaure rien : exiger un zip refuserait une purge
        parfaitement légitime."""
        self.assertEqual(
            "",
            DBR.missing_image(config(only_drop=True), [], exists=ABSENTE),
        )

    def test_the_cache_of_another_image_does_not_count(self):
        """Le cache est nommé d'après l'image : celui d'une autre ne dit
        rien de celle-ci."""
        self.assertEqual(
            os.path.join("image_db", "essai.zip"),
            DBR.missing_image(config(), ["_cache_autre"], exists=ABSENTE),
        )


class TestLOrdreDansLeCorpsDeMain(unittest.TestCase):
    """Une décision juste, appelée trop tard, ne garde rien.

    Le corps de `main` n'est pas pilotable sans base ni odoo_bin : ce qui
    est éprouvé ici est l'ORDRE des lignes, qui est exactement ce qui
    avait cédé.
    """

    @staticmethod
    def corps():
        import inspect

        return inspect.getsource(DBR.main)

    def test_the_image_is_checked_before_the_drop(self):
        source = self.corps()
        self.assertLess(
            source.index("missing_image("),
            source.index("--drop --database {config.database}"),
        )

    def test_the_refusal_says_nothing_was_dropped(self):
        """Un « image absente » seul laisse croire que la base est
        peut-être déjà partie."""
        self.assertIn("nothing was dropped", self.corps())

    def test_the_drop_is_said_and_not_logged(self):
        """`logging` part au niveau que réclame LOGLEVEL : sous
        « WARNING », la seule trace d'une destruction disparaissait."""
        source = self.corps()
        self.assertIn('print(f"## Drop {config.database} ##")', source)
        self.assertNotIn('_logger.info(f"## Drop', source)


class TestLeRefusSArrete(unittest.TestCase):
    """Il sort en erreur : continuer après avoir dit non détruirait
    quand même."""

    def test_a_missing_image_exits_non_zero_and_drops_nothing(self):
        lance = []
        with patch.object(
            DBR,
            "get_config",
            lambda: types.SimpleNamespace(
                database="cible",
                image="essai",
                only_drop=False,
                ignore_cache=True,
                clean_cache=False,
                neutralize=False,
            ),
        ), patch.object(
            DBR, "get_list_db_cache", lambda _a: (["cible"], [])
        ), patch.object(
            DBR, "check_output", lambda *a, **k: lance.append(a) or b""
        ), patch.object(
            DBR.os.path, "isfile", lambda _c: False
        ), patch.object(
            DBR, "image_path", lambda _i: "image_db/essai.zip"
        ):
            with self.assertRaises(SystemExit) as sortie:
                with contextlib.redirect_stdout(io.StringIO()):
                    DBR.main()
        self.assertNotEqual(0, sortie.exception.code)
        self.assertEqual([], lance)


if __name__ == "__main__":
    unittest.main()
