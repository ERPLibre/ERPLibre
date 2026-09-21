#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce qu'une instance vivante ne permet PAS se dit AVANT la clé.

L'entrée « A live remote instance » demandait l'URL, la base, le login et
une clé d'API de PRODUCTION, se connectait pour de bon, puis ouvrait un
écran où les cinq analyses sont refusées — chacune avec sa raison. L'écran
disait donc la vérité, mais après avoir fait payer le secret.

AUCUNE ANALYSE NE LIT UNE SESSION RPC, et ce n'est pas un oubli : quatre
descendent dans des tables qu'aucune session n'expose — pg_catalog,
pg_attribute, une jointure sur arch_db, un retard calculé en SQL — et la
cinquième ÉCRIT, ce qu'on ne fait pas sur une production.

Ni réseau ni instance : la connexion est simulée.
"""

import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

sys.argv = ["todo.py"]

from script.analyse import monitoring as M  # noqa: E402
from script.todo.todo import TODO  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402


def menu():
    return TODO.__new__(TODO)


def demander(reponses):
    """L'entrée « instance vivante », nourrie de réponses simulées."""
    tampon = io.StringIO()
    with mock.patch("builtins.input", side_effect=list(reponses)):
        with mock.patch("getpass.getpass", return_value="secret"):
            with mock.patch.object(
                M, "live_connect", return_value=(2, "18.0")
            ) as connexion:
                with redirect_stdout(tampon):
                    rendu = menu()._monitoring_live()
    return rendu, tampon.getvalue(), connexion


class TestCeQuiNestPasTenuSeDitAvantLaCle(unittest.TestCase):
    def test_no_analysis_reads_a_live_instance(self):
        """Le fait qui justifie tout le reste. S'il change un jour, cette
        épreuve tombe et l'avertissement doit être revu."""
        self.assertEqual((), M.available(M.KIND_LIVE))
        self.assertEqual(len(M.ANALYSES), len(M.unavailable(M.KIND_LIVE)))

    def test_the_warning_comes_before_any_credential(self):
        _rendu, ecran, connexion = demander(["n"])
        self.assertFalse(connexion.called)
        self.assertNotIn("://", ecran)

    def test_each_refusal_says_its_reason(self):
        """Par `t()` et non par la chaîne anglaise : la clé EST l'anglais,
        mais la SORTIE est traduite, et une épreuve écrite sur la clé tient
        la langue au lieu du contenu."""
        _rendu, ecran, _c = demander(["n"])
        for analyse in M.unavailable(M.KIND_LIVE):
            with self.subTest(analyse=analyse["key"]):
                self.assertIn(t(analyse["why_not"]), ecran)

    def test_backing_out_asks_nothing_more(self):
        rendu, _ecran, connexion = demander(["n"])
        self.assertIsNone(rendu)
        self.assertFalse(connexion.called)

    def test_going_on_anyway_still_connects(self):
        """Le refus n'est pas un verrou : quelqu'un peut vouloir seulement
        vérifier que ses identifiants passent."""
        with mock.patch("click.prompt", return_value="1"):
            rendu, _ecran, connexion = demander(
                ["o", "https://example.invalid", "base", "moi"]
            )
        self.assertTrue(connexion.called)
        self.assertEqual(M.KIND_LIVE, rendu[0])


if __name__ == "__main__":
    unittest.main()
