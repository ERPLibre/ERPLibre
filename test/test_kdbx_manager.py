#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ouverture du coffre KeePass depuis le CLI.

Un mot de passe refusé est le cas NORMAL de cette fonction : elle le dit,
laisse recommencer, et laisse partir. Sans ce rattrapage, pykeepass lève
`CredentialsError` sous une trace de quarante lignes et le CLI s'arrête.
L'invite nomme le coffre qu'elle ouvre, plusieurs pouvant exister.

Sans terminal, le mot de passe vient du fichier que nomme
KDBX_PASSWORD_FILE, ou de kdbx.password ; sans affichage, aucun sélecteur
Tk.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from pykeepass import create_database

from script.todo.kdbx_manager import KdbxManager

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# Argon2 remplacé pour tout le module : voir argon2_rapide.py.
from argon2_rapide import setUpModule  # noqa: E402,F401


def isoler_environnement(test):
    """Retire KDBX_PASSWORD_FILE de l'environnement pour la durée du test
    ``test``, et le rend à la fin : la variable, posée chez le développeur
    ou dans un conteneur, prend le pas sur kdbx.password et sur la saisie
    que ces tests simulent."""
    environnement = patch.dict(os.environ)
    environnement.start()
    test.addCleanup(environnement.stop)
    os.environ.pop("KDBX_PASSWORD_FILE", None)


class KdbxCase(unittest.TestCase):
    def setUp(self):
        isoler_environnement(self)
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
                # `**k` : un bouchon de `print` accepte la signature de
                # `print`, `flush=True` compris, pour que ces tests ne
                # dépendent pas des arguments nommés du code testé.
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
        """L'invite nomme le fichier, plusieurs coffres pouvant exister, et
        n'affiche jamais une clé i18n brute comme `enter_password`."""
        _, vu = self._saisies("faux", "")
        self.assertIn(self.chemin, vu)
        self.assertNotIn("enter_password", vu)


class TestGivingUpIsPossible(KdbxCase):
    def test_an_empty_entry_gives_up_immediately(self):
        """Une saisie vide est la porte de sortie : sans elle, seul l'arrêt
        du programme mettrait fin aux demandes."""
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
            # `**k` : voir KdbxCase._saisies.
            side_effect=lambda *a, **k: vues.append(" ".join(map(str, a))),
        ):
            resultat = self._manager("mauvais").get_kdbx()
        self.assertIsNone(resultat)
        self.assertIn("KeePass", "\n".join(vues))


class TestPasswordFile(KdbxCase):
    """KDBX_PASSWORD_FILE : le mot de passe vient d'un fichier, un secret
    docker par exemple, sans terminal et avant kdbx.password."""

    def _ouvrir(self, contenu=None, configure=None):
        """get_kdbx avec KDBX_PASSWORD_FILE vers un fichier qui porte
        ``contenu`` : du texte écrit en UTF-8, des octets écrits tels quels,
        ou None pour un fichier absent. Rend (résultat, affiché, nombre de
        getpass)."""
        secret = os.path.join(self.tmp.name, "secret")
        if isinstance(contenu, bytes):
            Path(secret).write_bytes(contenu)
        elif contenu is not None:
            Path(secret).write_text(contenu, encoding="utf-8")
        vues = []
        with (
            patch.dict(os.environ, {"KDBX_PASSWORD_FILE": secret}),
            patch("getpass.getpass") as saisie,
            patch(
                "builtins.print",
                side_effect=lambda *a, **k: vues.append(" ".join(map(str, a))),
            ),
        ):
            resultat = self._manager(configure).get_kdbx()
        return resultat, "\n".join(vues), saisie.call_count

    def test_the_file_opens_the_vault_without_a_prompt(self):
        resultat, _, saisies = self._ouvrir("bon\n")
        self.assertIsNotNone(resultat)
        self.assertEqual(0, saisies)

    def test_the_file_wins_over_the_configuration(self):
        resultat, _, _ = self._ouvrir("bon", configure="mauvais")
        self.assertIsNotNone(resultat)

    def test_a_wrong_password_in_the_file_is_reported(self):
        resultat, vu, saisies = self._ouvrir("faux")
        self.assertIsNone(resultat)
        self.assertIn("KeePass", vu)
        self.assertEqual(0, saisies)

    def test_a_missing_file_is_named_and_never_prompts(self):
        resultat, vu, saisies = self._ouvrir(None, configure="bon")
        self.assertIsNone(resultat)
        self.assertIn("KDBX_PASSWORD_FILE", vu)
        self.assertEqual(0, saisies)

    def test_a_password_set_instead_of_a_path_is_never_shown(self):
        """La variable porte le mot de passe au lieu d'un chemin : le
        fichier est absent, et le message ne cite pas la valeur."""
        vues = []
        with (
            patch.dict(
                os.environ, {"KDBX_PASSWORD_FILE": "Zq7-pas-un-chemin"}
            ),
            patch("getpass.getpass") as saisie,
            patch(
                "builtins.print",
                side_effect=lambda *a, **k: vues.append(" ".join(map(str, a))),
            ),
        ):
            resultat = self._manager("bon").get_kdbx()
        vu = "\n".join(vues)
        self.assertIsNone(resultat)
        self.assertEqual(0, saisie.call_count)
        self.assertIn("KDBX_PASSWORD_FILE", vu)
        self.assertNotIn("Zq7-pas-un-chemin", vu)

    def test_an_empty_file_is_refused(self):
        resultat, vu, saisies = self._ouvrir("\n")
        self.assertIsNone(resultat)
        self.assertIn("KDBX_PASSWORD_FILE", vu)
        self.assertEqual(0, saisies)

    def test_a_byte_order_mark_is_not_part_of_the_password(self):
        resultat, _, _ = self._ouvrir("\ufeffbon\n")
        self.assertIsNotNone(resultat)

    def test_a_non_utf8_file_is_refused_without_quoting_it(self):
        """Le texte de UnicodeDecodeError cite l'octet fautif et sa
        position : seule une raison générique s'affiche."""
        resultat, vu, saisies = self._ouvrir(b"bo\xe9n\xff\n", configure="bon")
        self.assertIsNone(resultat)
        self.assertEqual(0, saisies)
        self.assertIn("KDBX_PASSWORD_FILE", vu)
        self.assertIn("UTF-8", vu)
        for fuite in ("0xe9", "0xff", "\\x", "position", "codec"):
            self.assertNotIn(fuite, vu)

    def test_no_terminal_names_the_two_ways_out(self):
        vues = []
        with (
            patch("getpass.getpass", side_effect=EOFError),
            patch(
                "builtins.print",
                side_effect=lambda *a, **k: vues.append(" ".join(map(str, a))),
            ),
        ):
            self.assertIsNone(self._manager().get_kdbx())
        vu = "\n".join(vues)
        self.assertIn("KDBX_PASSWORD_FILE", vu)
        self.assertIn("kdbx.password", vu)


class TestVaultPath(KdbxCase):
    """kdbx.path : « ~ » s'y développe, et un coffre qui ne s'ouvre pas
    pour une raison système rend None, le chemin et la raison affichés,
    sans trace FileNotFoundError."""

    def _ouvrir(self, *saisies, configure=None):
        """Rend (résultat, affiché, nombre de getpass)."""
        vues = []
        with (
            patch("getpass.getpass", side_effect=list(saisies)) as saisie,
            patch(
                "builtins.print",
                side_effect=lambda *a, **k: vues.append(" ".join(map(str, a))),
            ),
        ):
            resultat = self._manager(configure).get_kdbx()
        return resultat, "\n".join(vues), saisie.call_count

    def test_a_missing_vault_with_a_configured_password(self):
        self.chemin = os.path.join(self.tmp.name, "absent.kdbx")
        resultat, vu, _ = self._ouvrir(configure="bon")
        self.assertIsNone(resultat)
        self.assertIn(self.chemin, vu)
        self.assertIn(os.strerror(2), vu)
        self.assertNotIn("Traceback", vu)

    def test_a_missing_vault_asks_the_password_only_once(self):
        self.chemin = os.path.join(self.tmp.name, "absent.kdbx")
        resultat, vu, saisies = self._ouvrir("bon", "bon", "bon")
        self.assertIsNone(resultat)
        self.assertEqual(1, saisies)
        self.assertIn(self.chemin, vu)

    def test_a_directory_in_place_of_the_vault(self):
        self.chemin = self.tmp.name
        resultat, vu, _ = self._ouvrir(configure="bon")
        self.assertIsNone(resultat)
        self.assertIn(self.chemin, vu)

    def test_a_tilde_path_is_expanded(self):
        self.chemin = os.path.join("~", os.path.basename(self.chemin))
        with patch.dict(os.environ, {"HOME": self.tmp.name}):
            resultat, _, _ = self._ouvrir(configure="bon")
        self.assertIsNotNone(resultat)


class TestNoPathWithoutDisplay(unittest.TestCase):
    """Sans kdbx.path, le sélecteur Tk ne s'ouvre pas sans affichage : le
    gestionnaire le dit et rend None, sans trace TclError."""

    def setUp(self):
        isoler_environnement(self)

    def _sans_chemin(self):
        config = MagicMock()
        config.get_config_value.return_value = None
        return KdbxManager(config)

    def test_no_display_gives_none_and_names_the_config_key(self):
        import tkinter

        from script.todo import kdbx_manager

        with (
            patch.object(
                kdbx_manager.tk,
                "Tk",
                side_effect=tkinter.TclError("no $DISPLAY"),
            ),
            self.assertLogs(kdbx_manager._logger, "ERROR") as journal,
        ):
            resultat = self._sans_chemin().get_kdbx()
        self.assertIsNone(resultat)
        texte = "\n".join(journal.output)
        self.assertIn("No display", texte)
        self.assertIn("kdbx.path", texte)
        self.assertIn("todo_override_private.json", texte)

    def test_without_tkinter_gives_none(self):
        from script.todo import kdbx_manager

        with (
            patch.object(kdbx_manager, "tk", None),
            self.assertLogs(kdbx_manager._logger, "ERROR"),
        ):
            self.assertIsNone(self._sans_chemin().get_kdbx())

    def test_selenium_lib_uses_the_same_picker(self):
        """selenium_lib n'a pas son propre appel à Tk : il ouvre le coffre
        par KdbxManager, qui tient l'absence d'affichage."""
        texte = (
            Path(__file__).resolve().parent.parent
            / "script"
            / "selenium"
            / "selenium_lib.py"
        ).read_text(encoding="utf-8")
        self.assertIn("KdbxManager(self.config_file).get_kdbx()", texte)
        self.assertNotIn("tk.Tk(", texte)


if __name__ == "__main__":
    unittest.main()
