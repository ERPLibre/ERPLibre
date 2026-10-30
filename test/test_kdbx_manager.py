#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ouverture du coffre KeePass depuis le CLI, puis sans interface.

Un mot de passe refusé est le cas NORMAL de cette fonction : elle le dit
sans laisser remonter `pykeepass.exceptions.CredentialsError`, laisse
recommencer, et laisse partir. L'invite nomme le coffre qu'elle ouvre.

Sans interface (`interactive=False`), rien n'est demandé ni imprimé : la
raison d'un échec se lit dans `last_error`, et l'échec est mémorisé.
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from pykeepass import create_database

from script.todo.kdbx_manager import KdbxManager

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# Argon2 remplacé pour tout le module : voir argon2_rapide.py.
from argon2_rapide import setUpModule  # noqa: E402,F401


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
        with (
            patch("getpass.getpass", side_effect=list(reponses)),
            patch(
                "builtins.print",
                # `**k` : un bouchon de `print` doit accepter la signature de
                # `print`. Sans lui, ajouter un `flush=True` dans le code
                # testé faisait échouer six tests sur une différence qui n'a
                # rien à voir avec ce qu'ils vérifient.
                side_effect=lambda *a, **k: vues.append(" ".join(map(str, a))),
            ),
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
        with (
            patch(
                "getpass.getpass",
                side_effect=lambda **k: appels.append(1) or "",
            ),
            patch("builtins.print"),
        ):
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


class FakeConfig(dict):
    """La configuration réduite à un dict ; une clé absente de premier
    niveau lève `TypeError`, comme `ConfigFile.get_config_value`."""

    def get_config_value(self, keys):
        if keys[0] not in self:
            raise TypeError("argument of type 'NoneType' is not iterable")
        valeur = self[keys[0]]
        for cle in keys[1:]:
            valeur = valeur.get(cle) if isinstance(valeur, dict) else None
        return valeur


class TestNonInteractive(unittest.TestCase):
    """Le service sans interface : rien n'est demandé ni imprimé."""

    MAITRE = "maitre-essai"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.chemin = os.path.join(tmp.name, "coffre.kdbx")
        create_database(self.chemin, password=self.MAITRE)
        demande = MagicMock(side_effect=AssertionError("terminal demandé"))
        fenetre = MagicMock()
        fenetre.Tk.side_effect = AssertionError("fenêtre ouverte")
        dit = MagicMock(side_effect=AssertionError("print appelé"))
        for cible, double in (
            ("getpass.getpass", demande),
            ("script.todo.kdbx_manager.tk", fenetre),
            ("builtins.print", dit),
        ):
            rustine = patch(cible, double)
            rustine.start()
            self.addCleanup(rustine.stop)

    def manager(self, config, password=None):
        return KdbxManager(config, password=password, interactive=False)

    def test_never_asks_a_terminal_nor_a_file_dialog(self):
        for config in (
            FakeConfig(),
            FakeConfig({"kdbx": {"path": ""}}),
            FakeConfig({"kdbx": {"path": self.chemin}}),
            FakeConfig({"kdbx": {"path": self.chemin, "password": "faux"}}),
        ):
            self.assertIsNone(self.manager(config).get_kdbx())

    def test_the_given_password_opens_the_vault(self):
        config = FakeConfig({"kdbx": {"path": self.chemin}})
        manager = self.manager(config, password=self.MAITRE)
        self.assertIsNotNone(manager.get_kdbx())
        self.assertEqual(manager.last_error, "")

    def test_the_configured_password_is_the_fallback(self):
        config = FakeConfig(
            {"kdbx": {"path": self.chemin, "password": self.MAITRE}}
        )
        self.assertIsNotNone(self.manager(config).get_kdbx())
        # Le mot de passe donné passe devant celui de la configuration.
        faux = FakeConfig({"kdbx": {"path": self.chemin, "password": "x"}})
        self.assertIsNotNone(
            self.manager(faux, password=self.MAITRE).get_kdbx()
        )

    def test_no_password_is_reported_not_raised(self):
        manager = self.manager(FakeConfig({"kdbx": {"path": self.chemin}}))
        self.assertIsNone(manager.get_kdbx())
        self.assertEqual(manager.last_error, "no_password")

    def test_a_wrong_password_is_tried_once_then_remembered(self):
        from pykeepass import PyKeePass

        appels = []

        def compte(*args, **kwargs):
            appels.append(1)
            return PyKeePass(*args, **kwargs)

        manager = self.manager(
            FakeConfig({"kdbx": {"path": self.chemin}}), password="faux"
        )
        with patch("pykeepass.PyKeePass", side_effect=compte):
            self.assertIsNone(manager.get_kdbx())
            self.assertIsNone(manager.get_kdbx())
            self.assertIsNone(manager.get_kdbx())
        self.assertEqual(len(appels), 1)
        self.assertEqual(manager.last_error, "wrong_password")

    def test_a_missing_path_is_reported(self):
        for config in (FakeConfig(), FakeConfig({"kdbx": {"path": ""}})):
            manager = self.manager(config, password=self.MAITRE)
            self.assertIsNone(manager.get_kdbx())
            self.assertEqual(manager.last_error, "not_configured")
        absent = os.path.join(os.path.dirname(self.chemin), "absent.kdbx")
        manager = self.manager(
            FakeConfig({"kdbx": {"path": absent}}), password=self.MAITRE
        )
        self.assertIsNone(manager.get_kdbx())
        self.assertEqual(manager.last_error, "unreadable")

    def test_a_tilde_path_is_expanded(self):
        dossier = os.path.dirname(self.chemin)
        with patch.dict(os.environ, {"HOME": dossier}):
            manager = self.manager(
                FakeConfig({"kdbx": {"path": "~/coffre.kdbx"}}),
                password=self.MAITRE,
            )
            self.assertIsNotNone(manager.get_kdbx())

    def test_a_missing_pykeepass_is_reported(self):
        manager = self.manager(
            FakeConfig({"kdbx": {"path": self.chemin}}), password=self.MAITRE
        )
        with patch.dict("sys.modules", {"pykeepass": None}):
            self.assertIsNone(manager.get_kdbx())
        self.assertEqual(manager.last_error, "no_pykeepass")


if __name__ == "__main__":
    unittest.main()
