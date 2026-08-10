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
    Account,
    AccountError,
    account_from_preset,
    find,
    load,
    save,
    write_template,
)


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
        self.assertEqual(data["version"], 1)

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
