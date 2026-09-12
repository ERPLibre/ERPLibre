#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from script.todo.mail.accounts import (
    PRESETS,
    SCHEMA_VERSION,
    Account,
    AccountError,
    account_from_preset,
    find,
    load,
    save,
    write_template,
)
from script.todo.todo_i18n import TRANSLATIONS, t


class TestPresets(unittest.TestCase):
    def test_four_presets(self):
        self.assertEqual(
            set(PRESETS), {"gmail", "outlook", "icloud", "generic"}
        )

    def test_gmail_servers(self):
        self.assertEqual(PRESETS["gmail"]["imap"]["host"], "imap.gmail.com")
        self.assertEqual(PRESETS["gmail"]["imap"]["port"], 993)
        self.assertEqual(PRESETS["gmail"]["smtp"]["host"], "smtp.gmail.com")
        self.assertEqual(PRESETS["gmail"]["smtp"]["port"], 587)

    def test_security_values_are_known(self):
        for key, preset in PRESETS.items():
            for proto in ("imap", "smtp"):
                self.assertIn(
                    preset[proto]["security"],
                    ("ssl", "starttls", "none"),
                    f"{key}.{proto}",
                )

    def test_app_password_flag(self):
        self.assertTrue(PRESETS["gmail"]["app_password"])
        self.assertTrue(PRESETS["icloud"]["app_password"])
        self.assertFalse(PRESETS["generic"]["app_password"])

    def test_microsoft_no_longer_promises_an_app_password(self):
        """Microsoft refuse tout mot de passe sur IMAP — le mot de passe
        d'application compris, puisque c'est la même authentification
        simple. Envoyer quelqu'un en générer un le fait travailler pour un
        secret que le serveur rejettera."""
        self.assertFalse(PRESETS["outlook"]["app_password"])

    def test_every_preset_carries_a_note(self):
        """La note est le seul endroit où un fournisseur explique ce qu'il
        attend. Un préréglage sans note laisse l'utilisateur deviner."""
        for cle, preset in PRESETS.items():
            self.assertIn("note_key", preset, cle)
            self.assertNotEqual(t(preset["note_key"]), preset["note_key"], cle)

    def test_the_microsoft_note_names_what_is_needed_instead(self):
        """Dire « le mot de passe ne marche pas » sans dire ce qui marche
        laisse l'utilisateur devant un compte qu'il croit mal configuré."""
        for langue in ("fr", "en"):
            texte = TRANSLATIONS["mail_preset_note_outlook"][langue]
            self.assertIn("OAuth", texte)


class TestAccountFromPreset(unittest.TestCase):
    def test_fills_servers_and_user(self):
        acc = account_from_preset("perso", "moi@gmail.com", "gmail")
        self.assertEqual(acc.imap.host, "imap.gmail.com")
        self.assertEqual(acc.imap.user, "moi@gmail.com")
        self.assertEqual(acc.smtp.user, "moi@gmail.com")

    def test_user_override(self):
        acc = account_from_preset(
            "perso", "moi@x.ca", "generic", user="login-different"
        )
        self.assertEqual(acc.imap.user, "login-different")

    def test_secret_ref_defaults_to_kdbx(self):
        acc = account_from_preset("perso", "moi@x.ca", "generic")
        self.assertEqual(acc.secret_ref, "kdbx:ERPLibre/Mail/perso")

    def test_secret_ref_keyring(self):
        acc = account_from_preset(
            "perso", "moi@x.ca", "generic", vault="keyring"
        )
        self.assertEqual(acc.secret_ref, "keyring:perso")

    def test_cache_key_ref(self):
        acc = account_from_preset("perso", "moi@x.ca", "generic")
        self.assertEqual(
            acc.cache_key_ref(), "kdbx:ERPLibre/Mail/perso/cache-key"
        )

    def test_cache_mode_inherits_by_default(self):
        self.assertIsNone(
            account_from_preset("perso", "moi@x.ca", "generic").cache_mode
        )

    def test_unknown_preset_raises(self):
        with self.assertRaises(AccountError):
            account_from_preset("perso", "moi@x.ca", "aol")

    def test_empty_name_raises(self):
        with self.assertRaises(AccountError):
            account_from_preset("", "moi@x.ca", "generic")

    def test_name_with_slash_raises(self):
        """Le nom sert de segment de chemin et de référence kdbx."""
        with self.assertRaises(AccountError):
            account_from_preset("per/so", "moi@x.ca", "generic")


class TestAuthKind(unittest.TestCase):
    """Un compte dit COMMENT il s'authentifie, et non plus seulement avec
    quel secret. Sans ce champ, le transport devrait deviner d'après le
    préréglage — et un serveur générique qui parle OAuth serait alors
    inatteignable."""

    def test_an_account_authenticates_by_password_unless_it_says_otherwise(
        self,
    ):
        self.assertEqual(
            account_from_preset("perso", "a@x.ca", "generic").auth, "login"
        )

    def test_an_unknown_authentication_is_refused_at_construction(self):
        """Une faute de frappe dans `accounts.json` doit se voir à la
        lecture, pas à la première connexion refusée."""
        with self.assertRaises(AccountError):
            account_from_preset("perso", "a@x.ca", "generic", auth="magique")

    def test_the_token_reference_sits_beside_the_password_not_over_it(self):
        """Le jeton et le mot de passe ne se remplacent pas : un compte qui
        repasse au mot de passe ne doit pas avoir perdu le sien, et un
        écrasement silencieux serait impossible à rattraper."""
        compte = account_from_preset("perso", "a@x.ca", "generic")
        self.assertEqual(compte.secret_ref, "kdbx:ERPLibre/Mail/perso")
        self.assertEqual(
            compte.refresh_token_ref(), "kdbx:ERPLibre/Mail/perso/oauth-token"
        )

    def test_the_three_references_of_an_account_are_all_distinct(self):
        compte = account_from_preset("perso", "a@x.ca", "generic")
        refs = {
            compte.secret_ref,
            compte.cache_key_ref(),
            compte.refresh_token_ref(),
        }
        self.assertEqual(len(refs), 3)


class TestRoundtrip(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "accounts.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_save_then_load(self):
        acc = account_from_preset("perso", "moi@gmail.com", "gmail")
        save([acc], self.path)
        loaded = load(self.path)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].to_dict(), acc.to_dict())

    def test_file_is_0600(self):
        save([account_from_preset("perso", "moi@x.ca", "generic")], self.path)
        mode = stat.S_IMODE(os.stat(self.path).st_mode)
        self.assertEqual(mode, 0o600)

    def test_parent_dir_is_0700(self):
        nested = Path(self.tmp.name) / "mail" / "accounts.json"
        save([account_from_preset("perso", "moi@x.ca", "generic")], nested)
        mode = stat.S_IMODE(os.stat(nested.parent).st_mode)
        self.assertEqual(mode, 0o700)

    def test_no_window_at_the_process_umask(self):
        """`write_text` puis `chmod` laisserait le fichier lisible à l'umask
        du process le temps entre les deux appels. Au moment où `chmod` est
        appelé, le fichier doit déjà être en 0600 — la preuve qu'il n'a
        jamais existé autrement."""
        from unittest.mock import patch

        seen = []
        original_chmod = os.chmod

        def spy(path, mode):
            if Path(path) == self.path:
                seen.append(stat.S_IMODE(os.stat(path).st_mode))
            return original_chmod(path, mode)

        with patch("os.chmod", side_effect=spy):
            save(
                [account_from_preset("perso", "moi@x.ca", "generic")],
                self.path,
            )

        self.assertEqual(seen, [0o600])

    def test_the_authentication_kind_survives_the_round_trip(self):
        """Perdu à l'écriture, il ramènerait le compte au mot de passe à la
        relecture suivante — et le refus du serveur passerait pour une
        panne de jeton."""
        acc = account_from_preset("perso", "a@x.ca", "generic", auth="oauth")
        save([acc], self.path)
        self.assertEqual(load(self.path)[0].auth, "oauth")

    def test_a_file_written_by_a_newer_version_is_refused_not_guessed(self):
        """Lire un fichier d'une version future champ par champ perd en
        silence ce qu'on ne connaît pas. Mieux vaut refuser que rendre un
        compte amputé qui s'écrira ensuite par-dessus l'original."""
        self.path.write_text(
            json.dumps({"version": SCHEMA_VERSION + 1, "accounts": []})
        )
        with self.assertRaises(AccountError):
            load(self.path)

    def test_a_file_from_the_first_version_still_loads(self):
        """La migration ne doit pas coûter son compte à qui en avait un."""
        self.path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "accounts": [
                        {
                            "name": "perso",
                            "email": "a@x.ca",
                            "imap": {
                                "host": "imap.x.ca",
                                "port": 993,
                                "security": "ssl",
                                "user": "a@x.ca",
                            },
                            "smtp": {
                                "host": "smtp.x.ca",
                                "port": 587,
                                "security": "starttls",
                                "user": "a@x.ca",
                            },
                            "secret_ref": "kdbx:ERPLibre/Mail/perso",
                        }
                    ],
                }
            )
        )
        comptes = load(self.path)
        self.assertEqual(comptes[0].auth, "login")

    def test_load_missing_file_returns_empty(self):
        self.assertEqual(load(Path(self.tmp.name) / "absent.json"), [])

    def test_no_password_key_is_written(self):
        save([account_from_preset("perso", "moi@x.ca", "generic")], self.path)
        raw = self.path.read_text()
        self.assertNotIn("password", raw.lower())

    def test_corrupt_json_raises(self):
        self.path.write_text("{ pas du json")
        with self.assertRaises(AccountError):
            load(self.path)

    def test_duplicate_name_raises_on_save(self):
        acc = account_from_preset("perso", "moi@x.ca", "generic")
        with self.assertRaises(AccountError):
            save([acc, acc], self.path)

    def test_find(self):
        accs = [
            account_from_preset("perso", "a@x.ca", "generic"),
            account_from_preset("travail", "b@x.ca", "generic"),
        ]
        self.assertEqual(find(accs, "travail").email, "b@x.ca")
        self.assertIsNone(find(accs, "absent"))


class TestTemplate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "accounts.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_writes_valid_json(self):
        write_template(self.path)
        data = json.loads(self.path.read_text())
        self.assertEqual(data["version"], SCHEMA_VERSION)

    def test_has_one_example_per_preset(self):
        write_template(self.path)
        data = json.loads(self.path.read_text())
        presets = {a["preset"] for a in data["accounts"]}
        self.assertEqual(presets, set(PRESETS))

    def test_examples_are_disabled(self):
        """Un modèle ne doit rien tenter de synchroniser tel quel."""
        write_template(self.path)
        data = json.loads(self.path.read_text())
        self.assertTrue(all(not a["enabled"] for a in data["accounts"]))

    def test_carries_comments(self):
        write_template(self.path)
        data = json.loads(self.path.read_text())
        self.assertIn("_comment", data)

    def test_refuses_to_overwrite(self):
        self.path.write_text("{}")
        with self.assertRaises(AccountError):
            write_template(self.path)

    def test_force_overwrites(self):
        self.path.write_text("{}")
        write_template(self.path, force=True)
        self.assertIn("accounts", json.loads(self.path.read_text()))

    def test_no_window_at_the_process_umask(self):
        from unittest.mock import patch

        seen = []
        original_chmod = os.chmod

        def spy(path, mode):
            if Path(path) == self.path:
                seen.append(stat.S_IMODE(os.stat(path).st_mode))
            return original_chmod(path, mode)

        with patch("os.chmod", side_effect=spy):
            write_template(self.path)

        self.assertEqual(seen, [0o600])


if __name__ == "__main__":
    unittest.main()
