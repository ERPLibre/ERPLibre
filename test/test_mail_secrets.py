#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import os
import stat
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from script.todo.mail.secrets import (
    SecretError,
    SecretStore,
    create_kdbx,
    keyring_is_safe,
)


class FakeKeyringBackend:
    """Imite un backend keyring, sans toucher au trousseau de la machine."""

    def __init__(self, name="keyring.backends.SecretService.Keyring"):
        self.__class__.__module__ = name.rsplit(".", 1)[0]
        self._name = name
        self.store = {}


class TestKeyringSafety(unittest.TestCase):
    def _with_backend(self, module_name, class_name):
        backend = MagicMock()
        type(backend).__module__ = module_name
        type(backend).__qualname__ = class_name
        return backend

    def test_secretservice_is_safe(self):
        backend = self._with_backend(
            "keyring.backends.SecretService", "Keyring"
        )
        with patch("keyring.get_keyring", return_value=backend):
            self.assertTrue(keyring_is_safe())

    def test_macos_is_safe(self):
        backend = self._with_backend("keyring.backends.macOS", "Keyring")
        with patch("keyring.get_keyring", return_value=backend):
            self.assertTrue(keyring_is_safe())

    def test_windows_is_safe(self):
        backend = self._with_backend(
            "keyring.backends.Windows", "WinVaultKeyring"
        )
        with patch("keyring.get_keyring", return_value=backend):
            self.assertTrue(keyring_is_safe())

    def test_plaintext_alt_is_refused(self):
        backend = self._with_backend("keyrings.alt.file", "PlaintextKeyring")
        with patch("keyring.get_keyring", return_value=backend):
            self.assertFalse(keyring_is_safe())

    def test_fail_backend_is_refused(self):
        backend = self._with_backend("keyring.backends.fail", "Keyring")
        with patch("keyring.get_keyring", return_value=backend):
            self.assertFalse(keyring_is_safe())

    def test_unknown_backend_is_refused(self):
        """Par défaut on refuse : un backend qu'on ne connaît pas peut écrire en clair."""
        backend = self._with_backend("un.paquet.inconnu", "Keyring")
        with patch("keyring.get_keyring", return_value=backend):
            self.assertFalse(keyring_is_safe())


class TestCreateKdbxPermissions(unittest.TestCase):
    """`create_database` (pykeepass) écrit d'abord un fichier `.tmp` via
    `construct`, avec `open(filename, "w+b")` — donc à l'umask du process —
    avant de le déplacer sur la cible. Resserrer l'umask le temps de l'appel
    est donc la seule façon de fermer cette fenêtre : un `os.open` sur la
    cible ne verrait jamais ce fichier intermédiaire."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "nested", "test.kdbx")

    def tearDown(self):
        self.tmp.cleanup()

    def test_file_is_0600(self):
        create_kdbx(self.path, "motdepasse")
        mode = stat.S_IMODE(os.stat(self.path).st_mode)
        self.assertEqual(mode, 0o600)

    def test_parent_dir_is_0700(self):
        create_kdbx(self.path, "motdepasse")
        mode = stat.S_IMODE(os.stat(os.path.dirname(self.path)).st_mode)
        self.assertEqual(mode, 0o700)

    def test_restores_the_process_umask(self):
        before = os.umask(0o022)
        os.umask(before)  # `os.umask` ne peut que remplacer : on relit puis
        # on rétablit exactement ce qu'on avait, sans jamais l'avoir changé
        # pour de vrai entre les deux appels.
        create_kdbx(self.path, "motdepasse")
        after = os.umask(before)
        os.umask(after)
        self.assertEqual(after, before)

    def test_umask_is_tightened_while_the_file_is_built(self):
        """La preuve directe : PENDANT `create_database`, l'umask doit être
        resserré, sinon le fichier `.tmp` intermédiaire existe, même
        brièvement, à l'umask permissif du process."""
        seen = {}

        def fake_create_database(path, password=None):
            seen["umask"] = os.umask(0)
            os.umask(seen["umask"])
            with open(path, "wb"):
                pass

        with patch(
            "pykeepass.create_database", side_effect=fake_create_database
        ):
            create_kdbx(self.path, "motdepasse")

        self.assertEqual(seen["umask"], 0o077)


class TestKdbxRoundtrip(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "test.kdbx")
        create_kdbx(self.path, "motdepasse")
        from pykeepass import PyKeePass

        self.kp = PyKeePass(self.path, password="motdepasse")
        manager = MagicMock()
        manager.get_kdbx.return_value = self.kp
        self.store = SecretStore(kdbx_manager=manager, use_keyring=False)

    def tearDown(self):
        self.tmp.cleanup()

    def test_created_file_exists(self):
        self.assertTrue(os.path.exists(self.path))

    def test_set_then_get(self):
        self.store.set("kdbx:ERPLibre/Mail/perso", "hunter2")
        self.assertEqual(self.store.get("kdbx:ERPLibre/Mail/perso"), "hunter2")

    def test_set_creates_nested_groups(self):
        self.store.set("kdbx:ERPLibre/Mail/travail", "s3cr3t")
        groups = [g.name for g in self.kp.groups]
        self.assertIn("ERPLibre", groups)
        self.assertIn("Mail", groups)

    def test_set_twice_overwrites(self):
        self.store.set("kdbx:ERPLibre/Mail/perso", "ancien")
        self.store.set("kdbx:ERPLibre/Mail/perso", "nouveau")
        self.assertEqual(self.store.get("kdbx:ERPLibre/Mail/perso"), "nouveau")

    def test_get_missing_returns_none(self):
        self.assertIsNone(self.store.get("kdbx:ERPLibre/Mail/absent"))

    def test_delete(self):
        self.store.set("kdbx:ERPLibre/Mail/perso", "hunter2")
        self.store.delete("kdbx:ERPLibre/Mail/perso")
        self.assertIsNone(self.store.get("kdbx:ERPLibre/Mail/perso"))

    def test_binary_key_survives_base64(self):
        """La clé de cache est stockée en base64 : 32 octets bruts doivent revenir intacts."""
        import base64

        raw = bytes(range(32))
        self.store.set(
            "kdbx:ERPLibre/Mail/perso/cache-key",
            base64.b64encode(raw).decode(),
        )
        got = self.store.get("kdbx:ERPLibre/Mail/perso/cache-key")
        self.assertEqual(base64.b64decode(got), raw)


class TestKeyringBranch(unittest.TestCase):
    def setUp(self):
        self.store = SecretStore(kdbx_manager=None, use_keyring=True)

    def test_set_and_get_through_keyring(self):
        vault = {}
        with patch(
            "script.todo.mail.secrets.keyring_is_safe", return_value=True
        ), patch(
            "keyring.set_password",
            side_effect=lambda s, u, p: vault.__setitem__((s, u), p),
        ), patch(
            "keyring.get_password", side_effect=lambda s, u: vault.get((s, u))
        ):
            self.store.set("keyring:perso", "hunter2")
            self.assertEqual(self.store.get("keyring:perso"), "hunter2")

    def test_refuses_unsafe_backend(self):
        # `keyring.get_keyring` est patché AUSSI : le message d'erreur passe par
        # keyring_backend_name(), qui interrogerait sinon le vrai trousseau.
        with patch(
            "script.todo.mail.secrets.keyring_is_safe", return_value=False
        ), patch("keyring.get_keyring", return_value=MagicMock()):
            with self.assertRaises(SecretError) as ctx:
                self.store.set("keyring:perso", "hunter2")
        # Traduit : on compare à la clé i18n elle-même, pas au mot français,
        # pour que le test suive la langue active plutôt que de la figer.
        from script.todo.todo_i18n import t

        self.assertIn(t("mail_err_keyring_plaintext"), str(ctx.exception))


class TestRefParsing(unittest.TestCase):
    def setUp(self):
        self.store = SecretStore(kdbx_manager=None, use_keyring=False)

    def test_unknown_scheme_raises(self):
        with self.assertRaises(SecretError):
            self.store.get("magique:perso")

    def test_missing_scheme_raises(self):
        with self.assertRaises(SecretError):
            self.store.get("perso")

    def test_no_backend_available_raises(self):
        with self.assertRaises(SecretError):
            self.store.set("keyring:perso", "x")


if __name__ == "__main__":
    unittest.main()
