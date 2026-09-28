#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La dérivation rapide des tests KeePass, et un témoin du vrai Argon2.

Les fichiers de tests du coffre remplacent Argon2 par `argon2_rapide`. Ce
fichier-ci ne le fait PAS pour tout le module : il garde le seul
aller-retour qui passe par la vraie dérivation, et vérifie que la doublure
garde ce dont les autres tests dépendent — une clé qui suit le mot de passe.
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from argon2_rapide import derivation_rapide  # noqa: E402
from pykeepass import PyKeePass  # noqa: E402
from pykeepass.exceptions import CredentialsError  # noqa: E402

from script.todo.mail.secrets import create_kdbx  # noqa: E402


def aller_retour(test):
    """Crée un coffre par le code de production, le rouvre, puis essaie
    un mauvais mot de passe."""
    with tempfile.TemporaryDirectory() as tmp:
        chemin = os.path.join(tmp, "coffre.kdbx")
        create_kdbx(chemin, "bon-mot-de-passe")
        PyKeePass(chemin, password="bon-mot-de-passe")
        with test.assertRaises(CredentialsError):
            PyKeePass(chemin, password="mauvais")


class TestLaDoublure(unittest.TestCase):
    ARGS = dict(
        time_cost=2, memory_cost=65536, parallelism=2, hash_len=32, type=2
    )

    def test_it_is_deterministic(self):
        self.assertEqual(
            derivation_rapide(b"secret", b"sel", **self.ARGS),
            derivation_rapide(b"secret", b"sel", **self.ARGS),
        )

    def test_the_key_follows_the_password_and_the_salt(self):
        cle = derivation_rapide(b"secret", b"sel", **self.ARGS)
        self.assertNotEqual(
            cle, derivation_rapide(b"autre", b"sel", **self.ARGS)
        )
        self.assertNotEqual(
            cle, derivation_rapide(b"secret", b"sal", **self.ARGS)
        )
        self.assertEqual(len(cle), 32)

    def test_a_vault_still_opens_and_refuses_a_wrong_password(self):
        with mock.patch("argon2.low_level.hash_secret_raw", derivation_rapide):
            aller_retour(self)


class TestLeVraiArgon2(unittest.TestCase):
    """Le témoin : sans doublure, le code de production crée un coffre que
    pykeepass rouvre par la vraie dérivation."""

    def test_a_vault_made_with_the_real_kdf_opens(self):
        import argon2.low_level

        self.assertIsNot(
            argon2.low_level.hash_secret_raw,
            derivation_rapide,
            "la doublure est restée en place : ce test ne prouve rien",
        )
        aller_retour(self)


if __name__ == "__main__":
    unittest.main()
