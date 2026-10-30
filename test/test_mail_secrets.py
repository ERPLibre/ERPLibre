#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import os
import stat
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from script.todo import kdbx_write
from script.todo.kdbx_manager import KdbxManager
from script.todo.mail import secrets as mail_secrets
from script.todo.mail.rules.lock import file_lock
from script.todo.mail.secrets import (
    SecretError,
    SecretStore,
    create_kdbx,
    keyring_headless_problem,
    keyring_is_safe,
)
from script.todo.todo_i18n import t

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# Argon2 remplacé pour tout le module : voir argon2_rapide.py.
from argon2_rapide import setUpModule  # noqa: E402,F401


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
        # Le verrou d'écriture du coffre vit sous ~/.erplibre/locks.
        maison = patch.dict(os.environ, {"HOME": self.tmp.name})
        maison.start()
        self.addCleanup(maison.stop)
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
        with (
            patch(
                "script.todo.mail.secrets.keyring_is_safe", return_value=True
            ),
            patch(
                "keyring.set_password",
                side_effect=lambda s, u, p: vault.__setitem__((s, u), p),
            ),
            patch(
                "keyring.get_password",
                side_effect=lambda s, u: vault.get((s, u)),
            ),
        ):
            self.store.set("keyring:perso", "hunter2")
            self.assertEqual(self.store.get("keyring:perso"), "hunter2")

    def test_refuses_unsafe_backend(self):
        # `keyring.get_keyring` est patché AUSSI : le message d'erreur passe par
        # keyring_backend_name(), qui interrogerait sinon le vrai trousseau.
        with (
            patch(
                "script.todo.mail.secrets.keyring_is_safe", return_value=False
            ),
            patch("keyring.get_keyring", return_value=MagicMock()),
        ):
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


class FakeConfig(dict):
    """La configuration réduite à un dict ; une clé absente rend None."""

    def get_config_value(self, keys):
        valeur = self
        for cle in keys:
            valeur = valeur.get(cle) if isinstance(valeur, dict) else None
        return valeur


class TestLockedWrites(unittest.TestCase):
    """Écritures du kdbx sous verrou, relecture comprise."""

    REF = "kdbx:ERPLibre/Mail/perso"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dossier = Path(tmp.name)
        maison = patch.dict(os.environ, {"HOME": tmp.name})
        maison.start()
        self.addCleanup(maison.stop)
        self.path = self.dossier / "coffre.kdbx"
        create_kdbx(str(self.path), "maitre-essai")

    def magasin(self):
        """Un SecretStore au coffre ouvert d'avance, comme le client."""
        manager = KdbxManager(
            FakeConfig(
                {"kdbx": {"path": str(self.path), "password": "maitre-essai"}}
            ),
            interactive=False,
        )
        self.assertIsNotNone(manager.get_kdbx())
        return SecretStore(kdbx_manager=manager, use_keyring=False)

    def identite(self):
        info = self.path.stat()
        return info.st_ino, info.st_mtime_ns

    def test_update_writes_the_new_value(self):
        store = self.magasin()
        vus = []

        def change(courant):
            vus.append(courant)
            return "neuf"

        self.assertEqual(store.update(self.REF, change), "neuf")
        self.assertEqual(vus, [None])
        self.assertEqual(self.magasin().get(self.REF), "neuf")

    def test_update_returning_none_writes_nothing(self):
        store = self.magasin()
        store.set(self.REF, "garde")
        avant = self.identite()
        self.assertEqual(store.update(self.REF, lambda courant: None), "garde")
        self.assertEqual(
            store.update(self.REF, lambda courant: courant), "garde"
        )
        self.assertEqual(self.identite(), avant)
        with self.assertRaises(ValueError):
            store.update(self.REF, mock_raise(ValueError("refus")))
        self.assertEqual(self.identite(), avant)

    def test_update_sees_a_value_written_by_another_handle(self):
        ancien = self.magasin()
        self.magasin().set(self.REF, "ailleurs")
        garde = ancien.update(self.REF, lambda courant: f"{courant}-suite")
        self.assertEqual(garde, "ailleurs-suite")
        self.assertEqual(self.magasin().get(self.REF), "ailleurs-suite")

    def test_a_busy_vault_is_a_secret_error(self):
        store = self.magasin()
        verrou = kdbx_write.lock_path_for(self.path)
        with (
            patch.object(kdbx_write, "KDBX_LOCK_WAIT_S", 0.1),
            file_lock(verrou, wait=0) as tenu,
        ):
            self.assertTrue(tenu)
            with self.assertRaises(SecretError) as ctx:
                store.set(self.REF, "x")
        self.assertEqual(str(ctx.exception), t("mail_err_kdbx_busy"))
        self.assertIsInstance(ctx.exception.__cause__, kdbx_write.KdbxBusy)
        self.assertIsNone(self.magasin().get(self.REF))

    def test_a_fresh_get_rereads_only_a_changed_file(self):
        store = self.magasin()
        kp = store._kdbx()
        with patch.object(kp, "reload", wraps=kp.reload) as relu:
            self.assertIsNone(store.get(self.REF, fresh=True))
            self.assertEqual(relu.call_count, 0)
            self.magasin().set(self.REF, "tourne")
            self.assertIsNone(store.get(self.REF))
            self.assertEqual(store.get(self.REF, fresh=True), "tourne")
            self.assertEqual(relu.call_count, 1)
            self.assertEqual(store.get(self.REF, fresh=True), "tourne")
            self.assertEqual(relu.call_count, 1)

    def test_a_fresh_get_from_another_thread_waits_for_a_write(self):
        """Une lecture fraîche d'un autre fil ne relit pas la base entre
        la relecture et l'enregistrement d'une écriture : la valeur
        écrite reste celle que rend la lecture fraîche suivante."""
        autre = "kdbx:ERPLibre/Mail/autre"
        store = self.magasin()
        kp = store._kdbx()
        self.magasin().set(self.REF, "b-1")
        dans_le_bloc = threading.Event()
        relues = []
        vraie_relecture = kp.reload

        def relire():
            relues.append(dans_le_bloc.is_set())
            vraie_relecture()

        def change(courant):
            dans_le_bloc.set()
            # L'état d'un fil qui a comparé les identités juste avant la
            # relecture de l'écriture : il croit devoir relire.
            kdbx_write.note_loaded(kp, (0, 0))
            lecteur = threading.Thread(
                target=store.get, args=(autre,), kwargs={"fresh": True}
            )
            lecteur.start()
            lecteur.join(0.3)
            fils.append(lecteur)
            dans_le_bloc.clear()
            return "b-2"

        fils = []
        with patch.object(kp, "reload", side_effect=relire):
            self.assertEqual(store.update(self.REF, change), "b-2")
            fils[0].join(5)
        self.assertFalse(fils[0].is_alive())
        self.assertNotIn(True, relues)
        self.assertEqual(self.magasin().get(self.REF), "b-2")
        self.assertEqual(store.get(self.REF, fresh=True), "b-2")

    def test_a_vault_opened_elsewhere_is_reread_once(self):
        from pykeepass import PyKeePass

        kp = PyKeePass(str(self.path), password="maitre-essai")
        store = SecretStore(
            kdbx_manager=SimpleNamespace(get_kdbx=lambda: kp),
            use_keyring=False,
        )
        self.magasin().set(self.REF, "ecrit-apres")
        self.assertIsNone(store.get(self.REF))
        self.assertEqual(store.get(self.REF, fresh=True), "ecrit-apres")


def mock_raise(exc):
    def lever(*args, **kwargs):
        raise exc

    return lever


def _backend(module="keyring.backends.SecretService", name="Keyring", **attrs):
    cls = type(name, (), dict(attrs))
    cls.__module__ = module
    cls.__qualname__ = name
    return cls()


class _NotFound(Exception):
    pass


def _interdit(nom):
    def lever(*args, **kwargs):
        raise AssertionError(f"{nom} appelé")

    return lever


class FakeCollection:
    def __init__(self, locked=False):
        self.locked = locked

    def is_locked(self):
        return self.locked

    unlock = staticmethod(_interdit("unlock"))


class TestKeyringProbe(unittest.TestCase):
    """La sonde du trousseau pour le service : rien n'est déverrouillé ni
    créé, et un bus muet ne fige pas l'appelant. Le bus, `keyring` et
    `secretstorage` sont des doubles."""

    ENV = {"DBUS_SESSION_BUS_ADDRESS": "unix:path=/nulle-part/bus"}

    def setUp(self):
        self.ouvertures = []
        self.collections = []
        self.collection = FakeCollection()
        self.connexion = MagicMock()

        def dbus_init():
            self.ouvertures.append(True)
            return self.connexion

        def collection(conn, *chemin):
            self.collections.append(chemin)
            if isinstance(self.collection, Exception):
                raise self.collection
            return self.collection

        self.faux = SimpleNamespace(
            dbus_init=dbus_init,
            Collection=collection,
            ItemNotFoundException=_NotFound,
            get_default_collection=_interdit("get_default_collection"),
            create_collection=_interdit("create_collection"),
        )
        rustine = patch.dict(sys.modules, {"secretstorage": self.faux})
        rustine.start()
        self.addCleanup(rustine.stop)
        self.backend = _backend()
        anneau = patch("keyring.get_keyring", side_effect=lambda: self.backend)
        anneau.start()
        self.addCleanup(anneau.stop)

    def sonder(self, env=None, **kwargs):
        return keyring_headless_problem(
            self.ENV if env is None else env, **kwargs
        )

    def test_an_open_secret_service_collection_is_usable(self):
        self.assertEqual(self.sonder(), "")
        self.assertEqual(self.collections, [()])
        self.connexion.close.assert_called_once_with()

    def test_keyring_without_bus_is_refused(self):
        with patch.object(
            mail_secrets,
            "_user_bus_socket",
            return_value=Path("/nulle-part/bus"),
        ):
            self.assertEqual(self.sonder({}), "mail_service_keyring_no_bus")
        self.assertEqual(self.ouvertures, [])

    def test_a_locked_keyring_is_refused_without_unlocking(self):
        self.collection = FakeCollection(locked=True)
        self.assertEqual(self.sonder(), "mail_service_keyring_locked")

    def test_a_silent_keyring_times_out(self):
        relache = threading.Event()
        self.addCleanup(relache.set)
        self.faux.dbus_init = lambda: relache.wait(5) and self.connexion
        self.assertEqual(
            self.sonder(timeout=0.1), "mail_service_keyring_timeout"
        )

    def test_an_unsafe_keyring_is_refused(self):
        self.backend = _backend("keyrings.alt.file", "PlaintextKeyring")
        self.assertEqual(self.sonder(), "mail_service_keyring_unsafe")
        self.assertEqual(self.ouvertures, [])

    def test_a_missing_default_collection_is_refused_without_creating_it(
        self,
    ):
        self.collection = _NotFound("absente")
        self.assertEqual(self.sonder(), "mail_service_keyring_no_collection")

    def test_the_preferred_collection_is_the_one_probed(self):
        chemin = "/org/freedesktop/secrets/collection/courriel"
        self.backend = _backend(preferred_collection=chemin)
        self.assertEqual(self.sonder(), "")
        self.assertEqual(self.collections, [(chemin,)])

    def test_a_kwallet_backend_is_refused_without_dbus(self):
        self.backend = _backend("keyring.backends.kwallet", "DBusKeyring")
        self.faux.dbus_init = _interdit("dbus_init")
        self.assertEqual(self.sonder(), "mail_service_keyring_unsupported")

    def test_a_broken_bus_is_no_bus(self):
        self.faux.dbus_init = mock_raise(OSError("refusé"))
        self.assertEqual(self.sonder(), "mail_service_keyring_no_bus")

    def test_the_keyring_guard_refuses_a_read_once_locked(self):
        store = SecretStore(kdbx_manager=None, use_keyring=True)
        store.keyring_guard = lambda: "mail_service_keyring_locked"
        with (
            patch("keyring.get_password", side_effect=_interdit("backend")),
            patch.object(
                mail_secrets, "keyring_is_safe", _interdit("keyring_is_safe")
            ),
        ):
            with self.assertRaises(SecretError) as ctx:
                store.get("keyring:perso")
            with self.assertRaises(SecretError):
                store.set("keyring:perso", "x")
        self.assertEqual(str(ctx.exception), t("mail_service_keyring_locked"))


if __name__ == "__main__":
    unittest.main()
