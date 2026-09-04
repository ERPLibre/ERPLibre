#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ouverture du coffre KeePass depuis le CLI.

Signalé à l'usage : une mauvaise saisie affichait une trace `construct` de
quarante lignes, puis `pykeepass.exceptions.CredentialsError`, et tuait le
CLI — `make: *** Error 1`. L'invite disait par ailleurs `enter_password`,
la clé i18n brute, sans nommer ce qu'elle demandait.

Un mot de passe refusé est le cas NORMAL de cette fonction : elle doit le
dire, laisser recommencer, et laisser partir.
"""
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from pykeepass import create_database

from script.todo.kdbx_manager import KdbxManager


class KdbxCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.chemin = os.path.join(self.tmp.name, "coffre.kdbx")
        create_database(self.chemin, password="bon")

    def tearDown(self):
        self.tmp.cleanup()

    def _manager(self, mot_de_passe_configure=None):
        config = MagicMock()
        config.get_config_value.side_effect = lambda keys: (
            self.chemin if keys == ["kdbx", "path"] else mot_de_passe_configure
        )
        return KdbxManager(config)

    def _saisies(self, *reponses):
        """Renvoie (résultat, texte affiché) pour une suite de saisies."""
        vues = []
        with patch("getpass.getpass", side_effect=list(reponses)), patch(
            "builtins.print",
            # `**k` : un bouchon de `print` doit accepter la signature de
            # `print`. Sans lui, ajouter un `flush=True` dans le code
            # testé faisait échouer six tests sur une différence qui n'a
            # rien à voir avec ce qu'ils vérifient.
            side_effect=lambda *a, **k: vues.append(" ".join(map(str, a))),
        ):
            resultat = self._manager().get_kdbx()
        return resultat, "\n".join(vues)


class TestWrongPasswordIsToldNotRaised(KdbxCase):
    def test_three_refusals_give_up_without_raising(self):
        resultat, vu = self._saisies("faux1", "faux2", "faux3")
        self.assertIsNone(resultat)
        self.assertEqual(vu.count("Mot de passe incorrect"), 3)

    def test_the_message_names_keepass_not_the_library_error(self):
        """« Invalid credentials » ne dit pas DE QUOI on parle : l'erreur
        d'authentification du serveur de courriel a exactement le même
        libellé. Le mot « KeePass » est ce qui les distingue."""
        _, vu = self._saisies("faux", "")
        self.assertIn("KeePass", vu)
        self.assertNotIn("CredentialsError", vu)
        self.assertNotIn("Traceback", vu)

    def test_the_prompt_says_which_vault_it_wants_to_open(self):
        """L'invite affichait `enter_password`, une clé i18n absente de la
        table. Elle doit nommer le fichier : plusieurs coffres peuvent
        exister, et rien ne disait lequel était demandé."""
        _, vu = self._saisies("faux", "")
        self.assertIn(self.chemin, vu)
        self.assertNotIn("enter_password", vu)


class TestGivingUpIsPossible(KdbxCase):
    def test_an_empty_entry_gives_up_immediately(self):
        """Sans porte de sortie, la seule façon de quitter était de tuer le
        programme — ce que la trace faisait, mais par accident."""
        resultat, vu = self._saisies("")
        self.assertIsNone(resultat)
        self.assertIn("abandonne", vu)

    def test_giving_up_asks_only_once(self):
        appels = []
        with patch(
            "getpass.getpass", side_effect=lambda **k: appels.append(1) or ""
        ), patch("builtins.print"):
            self._manager().get_kdbx()
        self.assertEqual(len(appels), 1)


class TestRecoveryAndSuccess(KdbxCase):
    def test_a_wrong_try_does_not_prevent_a_later_good_one(self):
        """Le contrôle POSITIF : sans lui, une fonction qui refuserait
        TOUJOURS passerait les tests ci-dessus."""
        resultat, _ = self._saisies("faux", "bon")
        self.assertIsNotNone(resultat)

    def test_a_good_password_opens_the_vault_at_once(self):
        resultat, _ = self._saisies("bon")
        self.assertIsNotNone(resultat)

    def test_a_wrong_password_from_the_configuration_is_reported(self):
        """Chemin sans saisie : personne à qui redemander, mais la trace ne
        doit pas remonter pour autant."""
        vues = []
        with patch(
            "builtins.print",
            # `**k` : un bouchon de `print` doit accepter la signature de
            # `print`. Sans lui, ajouter un `flush=True` dans le code
            # testé faisait échouer six tests sur une différence qui n'a
            # rien à voir avec ce qu'ils vérifient.
            side_effect=lambda *a, **k: vues.append(" ".join(map(str, a))),
        ):
            resultat = self._manager("mauvais").get_kdbx()
        self.assertIsNone(resultat)
        self.assertIn("KeePass", "\n".join(vues))


if __name__ == "__main__":
    unittest.main()
