#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Où se connecter : saisie manuelle ou ~/.ssh/config (`_ask_ssh_target`).

Ce que ces tests gardent :

- « Entrée » choisit ~/.ssh/config, dès qu'il déclare un hôte ;
- sans hôte déclaré, fichier absent compris, la question n'est pas posée et
  la saisie manuelle commence aussitôt ;
- une saisie manuelle propose son ajout à ~/.ssh/config, sous un nom
  suggéré, annoncé avant d'être écrit, et revient alors sous cet alias ;
- un nom déjà déclaré n'est jamais remplacé, y compris déclaré là où la
  lecture du fichier ne voit pas (Include, « Host=nom ») ; un nom invalide
  est redemandé ;
- une adresse invalide n'est jamais écrite : un « HostName » vide ou à deux
  mots fait refuser à ssh le fichier entier ;
- le bloc ajouté garde la vérification de la clé d'hôte ; s'il est éclipsé
  par un bloc plus haut, la cible tapée est rendue ;
- un alias existant tapé à la main, seul ou après « utilisateur@ », reste
  un alias et n'est pas recopié ;
- un ~/.ssh/config qui n'est pas en UTF-8 n'est pas réécrit.

Les hôtes et adresses sont inventés (domaine .test, plage 203.0.113.0/24
réservée à la documentation).
"""

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.argv = ["todo.py"]
from script.todo.todo import TODO  # noqa: E402

CONFIG = """Host banc-essai
    HostName 203.0.113.7
    User testeur
    ProxyJump rebond-essai
"""


class SshTarget(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.addCleanup(self.home.cleanup)
        env = mock.patch.dict(os.environ, {"HOME": self.home.name})
        env.start()
        self.addCleanup(env.stop)
        self.cfg = os.path.join(self.home.name, ".ssh", "config")
        self.todo = TODO()
        # ssh -G lit le ~/.ssh/config du compte (passwd), pas celui de
        # $HOME : il est simulé à partir du fichier de test. « ailleurs »
        # déclare des noms que la lecture du fichier ne voit pas (Include) ;
        # « user_global » imite un « Host * » placé plus haut qui fixe User.
        self.ailleurs = {}
        self.user_global = None
        self.todo._ssh_resolve = self._ssh_g

    def _ssh_g(self, alias):
        if alias in self.ailleurs:
            return dict(self.ailleurs[alias])
        info = dict(TODO._ssh_config_entries(self.cfg)).get(alias, {})
        return {
            "hostname": info.get("hostname", alias),
            "user": self.user_global or info.get("user", "moi"),
        }

    def _ecrire(self, texte=CONFIG):
        os.makedirs(os.path.dirname(self.cfg), exist_ok=True)
        with open(self.cfg, "w", encoding="utf-8") as fh:
            fh.write(texte)

    def _lire(self):
        with open(self.cfg, encoding="utf-8") as fh:
            return fh.read()

    def _demander(self, *reponses):
        """`_ask_ssh_target` avec ces réponses ; rend (résultat, questions,
        sortie)."""
        questions = []
        suite = iter(reponses)

        def repondre(question=""):
            questions.append(question)
            return next(suite)

        sortie = io.StringIO()
        with (
            mock.patch("builtins.input", side_effect=repondre),
            mock.patch("getpass.getuser", return_value="moi"),
            redirect_stdout(sortie),
        ):
            res = self.todo._ask_ssh_target()
        return res, questions, sortie.getvalue()

    def test_enter_picks_ssh_config(self):
        self._ecrire()
        res, questions, _ = self._demander("", "1")
        self.assertEqual(
            ("banc-essai", "testeur", "203.0.113.7", "banc-essai", True), res
        )
        self.assertIn("2", questions[0])

    def test_no_config_skips_the_question(self):
        res, questions, _ = self._demander("moi@203.0.113.9", "n")
        self.assertEqual(
            ("moi@203.0.113.9", "moi", "203.0.113.9", "203.0.113.9", False),
            res,
        )
        self.assertNotIn("1/2", " ".join(questions))
        self.assertFalse(os.path.exists(self.cfg))

    def test_config_without_hosts_skips_the_question(self):
        self._ecrire("Host *\n    ServerAliveInterval 60\n")
        _, questions, _ = self._demander("moi@203.0.113.9", "n")
        self.assertNotIn("1/2", " ".join(questions))

    def test_manual_entry_added_under_the_suggested_name(self):
        self._ecrire()
        res, _, sortie = self._demander("1", "ops@srv.exemple.test", "", "")
        self.assertEqual(("srv", "ops", "srv.exemple.test", "srv", True), res)
        self.assertIn("Host srv", sortie)
        contenu = self._lire()
        self.assertIn("Host srv\n", contenu)
        self.assertIn("HostName srv.exemple.test", contenu)
        self.assertIn("User ops", contenu)
        self.assertIn("Host banc-essai", contenu)
        self.assertNotIn("StrictHostKeyChecking", contenu)

    def test_ip_gets_a_name_and_a_typed_name_wins(self):
        self.assertEqual(
            "hote-203-0-113-9",
            TODO._ssh_alias_suggestion("203.0.113.9", set()),
        )
        res, _, _ = self._demander("moi@203.0.113.9", "", "poste-essai")
        self.assertEqual("poste-essai", res[0])
        self.assertIn("Host poste-essai\n", self._lire())

    def test_taken_name_is_never_replaced(self):
        self._ecrire()
        res, questions, sortie = self._demander(
            "1", "moi@203.0.113.9", "o", "banc-essai", "autre-essai"
        )
        self.assertEqual("autre-essai", res[0])
        contenu = self._lire()
        self.assertIn("HostName 203.0.113.7", contenu)
        self.assertIn("ProxyJump rebond-essai", contenu)
        self.assertEqual(2, contenu.count("Host "))

    def test_suggestion_avoids_taken_names(self):
        self.assertEqual(
            "srv-2", TODO._ssh_alias_suggestion("srv.exemple.test", {"srv"})
        )

    def test_invalid_name_is_asked_again(self):
        res, _, _ = self._demander("moi@203.0.113.9", "", "web *", "web-essai")
        self.assertEqual("web-essai", res[0])

    def test_declined_writes_nothing(self):
        self._ecrire()
        avant = self._lire()
        res, _, _ = self._demander("1", "moi@203.0.113.9", "n")
        self.assertFalse(res[4])
        self.assertEqual(avant, self._lire())

    def test_typed_alias_stays_an_alias(self):
        """« banc-essai » tapé à la main garde son ProxyJump : la cible est
        l'alias, pas « moi@banc-essai »."""
        self._ecrire()
        res, questions, _ = self._demander("1", "banc-essai")
        self.assertEqual(
            ("banc-essai", "testeur", "203.0.113.7", "banc-essai", True), res
        )
        self.assertEqual(2, len(questions))

    def test_invalid_address_is_never_written(self):
        self._ecrire()
        avant = self._lire()
        for saisie in ("moi@", "moi@srv essai.test", "moi@srv.test:2222"):
            with self.subTest(saisie=saisie):
                res, questions, _ = self._demander("1", saisie)
                self.assertIsNone(res)
                self.assertEqual(2, len(questions))
        self.assertEqual(avant, self._lire())

    def test_missing_user_falls_back_to_the_account(self):
        res, _, _ = self._demander("@203.0.113.9", "n")
        self.assertEqual("moi@203.0.113.9", res[0])

    def test_user_at_alias_keeps_the_alias_block(self):
        self._ecrire()
        avant = self._lire()
        res, questions, _ = self._demander("1", "ops@banc-essai")
        self.assertEqual(
            ("ops@banc-essai", "ops", "203.0.113.7", "banc-essai", False), res
        )
        self.assertEqual(2, len(questions))
        self.assertEqual(avant, self._lire())

    def test_name_taken_outside_the_file_is_skipped(self):
        """« srv » déclaré dans un Include : ssh -G le résout ailleurs."""
        self.ailleurs["srv"] = {"hostname": "203.0.113.50", "user": "x"}
        res, questions, _ = self._demander("ops@srv.exemple.test", "", "")
        self.assertEqual("srv-2", res[0])
        self.assertIn("(srv-2)", questions[-1])

    def test_overridden_block_returns_the_typed_target(self):
        """Un « Host * » plus haut fixe User : l'alias mènerait ailleurs."""
        self.user_global = "root"
        res, _, sortie = self._demander("ops@srv.exemple.test", "", "")
        self.assertEqual(
            (
                "ops@srv.exemple.test",
                "ops",
                "srv.exemple.test",
                "srv.exemple.test",
                False,
            ),
            res,
        )
        self.assertIn("root@srv.exemple.test", sortie)

    def test_non_utf8_config_is_not_rewritten(self):
        os.makedirs(os.path.dirname(self.cfg), exist_ok=True)
        brut = (
            b"# commentaire \xe9\nHost banc-essai\n    HostName 203.0.113.7\n"
        )
        with open(self.cfg, "wb") as fh:
            fh.write(brut)
        res, _, _ = self._demander("1", "moi@203.0.113.9", "")
        self.assertEqual("moi@203.0.113.9", res[0])
        with open(self.cfg, "rb") as fh:
            self.assertEqual(brut, fh.read())

    def test_unknown_choice_cancels(self):
        self._ecrire()
        res, _, _ = self._demander("3")
        self.assertIsNone(res)


if __name__ == "__main__":
    unittest.main()
