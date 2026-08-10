#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from script.todo.mail.account_setup import (
    create_vault,
    kdbx_is_configured,
    save_new_account,
    use_existing_vault,
)
from script.todo.mail.accounts import account_from_preset
from script.todo.mail.secrets import SecretError


class FakeConfigFile:
    """Un `config_file` minimal : seuls `get_config_value`/`set_config_value`
    sont utilisés par `account_setup`, pas besoin du vrai `ConfigFile`."""

    def __init__(self):
        self._values: dict = {}

    def get_config_value(self, keys):
        node = self._values
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                return None
            node = node[key]
        return node

    def set_config_value(self, keys, value):
        node = self._values
        for key in keys[:-1]:
            node = node.setdefault(key, {})
        node[keys[-1]] = value


class TestSaveNewAccountRollsBack(unittest.TestCase):
    """C'est la couture qu'un défaut réel emprunterait : un secret orphelin
    sous une référence qu'aucune configuration ne désigne, invisible."""

    def setUp(self):
        self.account = account_from_preset("perso", "a@x.ca", "generic")
        self.vault = MagicMock()

    def test_rollback_deletes_the_secret_when_save_raises(self):
        with patch(
            "script.todo.mail.account_setup.mail_accounts.save",
            side_effect=OSError("disque plein"),
        ):
            with self.assertRaises(OSError):
                save_new_account(
                    self.vault, [self.account], self.account, "hunter2"
                )
        self.vault.set.assert_called_once_with(
            self.account.secret_ref, "hunter2"
        )
        self.vault.delete.assert_called_once_with(self.account.secret_ref)

    def test_rollback_survives_a_vault_that_cannot_delete_either(self):
        """Le secret peut avoir déjà disparu du coffre : ce n'est pas une
        raison de masquer l'échec de la sauvegarde initiale."""
        self.vault.delete.side_effect = SecretError("introuvable")
        with patch(
            "script.todo.mail.account_setup.mail_accounts.save",
            side_effect=OSError("disque plein"),
        ):
            with self.assertRaises(OSError):
                save_new_account(
                    self.vault, [self.account], self.account, "hunter2"
                )

    def test_successful_save_leaves_the_secret_in_place(self):
        with patch(
            "script.todo.mail.account_setup.mail_accounts.save"
        ) as mock_save:
            save_new_account(
                self.vault, [self.account], self.account, "hunter2"
            )
        mock_save.assert_called_once_with([self.account])
        self.vault.set.assert_called_once_with(
            self.account.secret_ref, "hunter2"
        )
        self.vault.delete.assert_not_called()


class TestKdbxIsConfigured(unittest.TestCase):
    def test_false_when_nothing_is_configured(self):
        self.assertFalse(kdbx_is_configured(FakeConfigFile()))

    def test_false_on_the_empty_string(self):
        config = FakeConfigFile()
        config.set_config_value(["kdbx", "path"], "")
        self.assertFalse(kdbx_is_configured(config))

    def test_true_once_a_path_is_set(self):
        config = FakeConfigFile()
        config.set_config_value(["kdbx", "path"], "/already/there.kdbx")
        self.assertTrue(kdbx_is_configured(config))


class TestCreateVault(unittest.TestCase):
    def test_creates_a_real_kdbx_and_persists_its_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "new.kdbx")
            config = FakeConfigFile()
            create_vault(config, path, "hunter2")
            self.assertTrue(os.path.isfile(path))
            self.assertEqual(config.get_config_value(["kdbx", "path"]), path)

    def test_refuses_to_overwrite_an_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "already.kdbx")
            with open(path, "wb") as handle:
                handle.write(b"already there")
            config = FakeConfigFile()
            with self.assertRaises(SecretError):
                create_vault(config, path, "hunter2")
            self.assertIsNone(config.get_config_value(["kdbx", "path"]))


class TestUseExistingVault(unittest.TestCase):
    def test_refuses_a_nonexistent_file(self):
        config = FakeConfigFile()
        with self.assertRaises(SecretError):
            use_existing_vault(config, "/nope/does-not-exist.kdbx")
        self.assertIsNone(config.get_config_value(["kdbx", "path"]))

    def test_refuses_an_empty_path(self):
        config = FakeConfigFile()
        with self.assertRaises(SecretError):
            use_existing_vault(config, "")

    def test_accepts_and_persists_an_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "existing.kdbx")
            with open(path, "wb") as handle:
                handle.write(b"not a real kdbx, just a file")
            config = FakeConfigFile()
            use_existing_vault(config, path)
            self.assertEqual(config.get_config_value(["kdbx", "path"]), path)


if __name__ == "__main__":
    unittest.main()
