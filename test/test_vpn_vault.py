#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le coffre KeePassXC : aller-retour d'un PSK, et permissions.

Un vrai fichier .kdbx est créé dans un répertoire temporaire — pykeepass fait
tout hors ligne, donc ces tests ne demandent ni root, ni réseau, ni coffre de
l'utilisateur. Ils sont ignorés (et le disent) si pykeepass n'est pas
installé, plutôt que de passer en silence.
"""

import io
import json
import os
import stat
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.config.config_file import ConfigFile
from script.todo.kdbx_manager import KdbxManager
from script.vpn.vault import (
    VaultError,
    VpnVault,
    secrets_from_env,
    secrets_to_env,
)

try:
    from pykeepass import create_database
except ModuleNotFoundError:
    create_database = None

MASTER = "coffre-de-test"
PSK = "cl3-Pr3-P4rt4g33!"
PPP_PASSWORD = "m0tD3P4ss3-PPP"
TITLE = "ERPLibre VPN / acme"


@unittest.skipUnless(create_database, "pykeepass n'est pas installé")
class VpnVaultRoundTrip(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.kdbx_path = os.path.join(self.tmp.name, "secrets.kdbx")
        create_database(self.kdbx_path, password=MASTER)
        # 0600 d'emblée : sinon chaque test verrait le coffre resserré à
        # l'ouverture et l'annoncerait, ce qui noierait la sortie de la
        # suite sous un avertissement qui n'est le sujet que d'un test.
        os.chmod(self.kdbx_path, 0o600)

        # Le mot de passe maître est mis dans la configuration UNIQUEMENT
        # ici : c'est ce qui permet au test de tourner sans saisie. Le CLI,
        # lui, signale cette situation à l'utilisateur.
        self.base = os.path.join(self.tmp.name, "todo.json")
        with open(self.base, "w") as fh:
            json.dump(
                {"kdbx": {"path": self.kdbx_path, "password": MASTER}}, fh
            )
        self.private = os.path.join(self.tmp.name, "private.json")
        self.patches = [
            patch("script.config.config_file.CONFIG_FILE", self.base),
            patch(
                "script.config.config_file.CONFIG_OVERRIDE_FILE",
                os.path.join(self.tmp.name, "override.json"),
            ),
            patch(
                "script.config.config_file.CONFIG_OVERRIDE_PRIVATE_FILE",
                self.private,
            ),
        ]
        for item in self.patches:
            item.start()
        config = ConfigFile()
        self.vault = VpnVault(config, KdbxManager(config))

    def tearDown(self):
        for item in self.patches:
            item.stop()
        self.tmp.cleanup()

    def test_write_then_read(self):
        self.vault.write(
            TITLE,
            {"username": "ACME\\user", "password": "ppp", "psk": PSK},
        )
        values = self.vault.read(TITLE, fields=("psk", "password"))
        self.assertEqual(values["psk"], PSK)
        self.assertEqual(values["password"], "ppp")
        self.assertEqual(values["username"], "ACME\\user")

    def test_password_is_the_native_field_not_a_custom_one(self):
        """`password` est un champ NATIF de KeePassXC. Le chercher parmi les
        propriétés personnalisées le rendrait vide, alors qu'un pilote a le
        droit de le déclarer dans ses `secret_fields`."""
        self.vault.write(TITLE, {"password": "ppp", "psk": PSK})
        entry = self.vault._open().find_entries_by_title(TITLE, first=True)
        self.assertEqual(entry.password, "ppp")
        self.assertIsNone(entry.get_custom_property("password"))

    def test_psk_is_a_protected_property(self):
        """Protégée = chiffrée en mémoire et masquée dans KeePassXC, comme
        le champ mot de passe."""
        self.vault.write(TITLE, {"psk": PSK})
        entry = self.vault._open().find_entries_by_title(TITLE, first=True)
        self.assertTrue(entry.is_custom_property_protected("psk"))

    def test_entry_lands_in_its_own_group(self):
        self.vault.write(TITLE, {"psk": PSK})
        entry = self.vault._open().find_entries_by_title(TITLE, first=True)
        self.assertEqual(entry.group.name, "ERPLibre VPN")

    def test_update_keeps_the_untouched_fields(self):
        """Une réponse vide dans le menu ne doit pas effacer l'autre
        secret : `write` ne touche que les clés qu'on lui donne."""
        self.vault.write(TITLE, {"password": "ppp", "psk": PSK})
        self.vault.write(TITLE, {"password": "nouveau"})
        values = self.vault.read(TITLE, fields=("psk", "password"))
        self.assertEqual(values["password"], "nouveau")
        self.assertEqual(values["psk"], PSK)

    def test_missing_entry_reads_as_empty(self):
        """« Pas encore de secret » est un état normal, pas une panne."""
        values = self.vault.read("ERPLibre VPN / inconnu", fields=("psk",))
        self.assertEqual(values, {"username": "", "password": "", "psk": ""})
        self.assertFalse(self.vault.exists("ERPLibre VPN / inconnu"))

    def test_the_vault_stays_owner_only_after_a_write(self):
        """LE test de non-régression.

        `PyKeePass.save()` réécrit le fichier et lui redonne le mode du
        umask — 0664 sur Ubuntu. Un chmod fait une fois à la création ne
        survivait pas au premier enregistrement : le coffre devenait
        lisible par toute la machine sans que personne ne touche à rien.
        """
        os.chmod(self.kdbx_path, 0o600)
        self.vault.write(TITLE, {"password": "ppp", "psk": PSK})
        mode = stat.S_IMODE(os.stat(self.kdbx_path).st_mode)
        self.assertEqual(mode, 0o600, oct(mode))

    def test_a_loose_vault_is_tightened_and_it_says_so(self):
        """Trouvé desserré, il ne l'est pas resté — et ce n'est pas nous qui
        l'avions laissé ainsi, donc on le dit."""
        os.chmod(self.kdbx_path, 0o664)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            self.vault.read(TITLE, fields=("psk",))
        mode = stat.S_IMODE(os.stat(self.kdbx_path).st_mode)
        self.assertEqual(mode, 0o600, oct(mode))
        self.assertIn("0600", buffer.getvalue())

    def test_protect_leaves_an_already_tight_vault_alone(self):
        os.chmod(self.kdbx_path, 0o600)
        self.assertFalse(self.vault.protect())

    def test_stored_master_password_is_reported(self):
        self.assertTrue(self.vault.master_password_is_stored())


@unittest.skipUnless(create_database, "pykeepass n'est pas installé")
class VpnVaultBootstrap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = os.path.join(self.tmp.name, "todo.json")
        with open(self.base, "w") as fh:
            json.dump({"kdbx": {"path": "", "password": ""}}, fh)
        self.private = os.path.join(self.tmp.name, "private.json")
        self.patches = [
            patch("script.config.config_file.CONFIG_FILE", self.base),
            patch(
                "script.config.config_file.CONFIG_OVERRIDE_FILE",
                os.path.join(self.tmp.name, "override.json"),
            ),
            patch(
                "script.config.config_file.CONFIG_OVERRIDE_PRIVATE_FILE",
                self.private,
            ),
        ]
        for item in self.patches:
            item.start()
        config = ConfigFile()
        self.vault = VpnVault(config, KdbxManager(config))
        self.target = os.path.join(self.tmp.name, "nouveau.kdbx")

    def tearDown(self):
        for item in self.patches:
            item.stop()
        self.tmp.cleanup()

    def _answers(self, *values):
        answers = iter(values)
        return lambda _prompt: next(answers)

    def test_creates_the_vault_and_remembers_where(self):
        with patch("getpass.getpass", return_value=MASTER):
            path = self.vault.ensure_vault(ask=self._answers(self.target, "o"))
        self.assertEqual(path, self.target)
        self.assertTrue(os.path.exists(self.target))
        # Le chemin est retenu dans le fichier PRIVÉ, le seul gitignored.
        with open(self.private) as fh:
            self.assertEqual(json.load(fh)["kdbx"]["path"], self.target)

    def test_new_vault_is_owner_only(self):
        with patch("getpass.getpass", return_value=MASTER):
            self.vault.ensure_vault(ask=self._answers(self.target, "o"))
        mode = stat.S_IMODE(os.stat(self.target).st_mode)
        self.assertEqual(mode, 0o600, oct(mode))

    def test_refusing_creates_nothing(self):
        path = self.vault.ensure_vault(ask=self._answers(self.target, "n"))
        self.assertEqual(path, "")
        self.assertFalse(os.path.exists(self.target))

    def test_mismatched_confirmation_creates_nothing(self):
        with patch("getpass.getpass", side_effect=[MASTER, "autre"]):
            with self.assertRaises(VaultError):
                self.vault.ensure_vault(ask=self._answers(self.target, "o"))
        self.assertFalse(os.path.exists(self.target))

    def test_reading_without_a_configured_vault_says_so(self):
        """Sans chemin, `KdbxManager` ouvrirait un sélecteur graphique et,
        sur un serveur sans tkinter, journaliserait une erreur au lieu de
        dire ce qui manque."""
        with self.assertRaises(VaultError) as caught:
            self.vault.read(TITLE, fields=("psk",))
        self.assertIn("coffre", str(caught.exception).lower())


class SecretsHandedOverByEnvironment(unittest.TestCase):
    """Le menu tient déjà le coffre ouvert quand il lance `vpn.py`.

    Sans ce passage, le mot de passe maître était redemandé DEUX fois par
    connexion — un essai à blanc précède le montage. Par l'environnement et
    non par un argument : /proc/<pid>/environ n'est lisible que par le
    propriétaire, /proc/<pid>/cmdline par tout le monde.
    """

    def test_round_trip(self):
        env = secrets_to_env({"psk": PSK, "password": PPP_PASSWORD})
        with patch.dict(os.environ, env, clear=False):
            got = secrets_from_env(("psk", "password"))
        self.assertEqual(got, {"psk": PSK, "password": PPP_PASSWORD})

    def test_without_the_marker_nothing_is_claimed(self):
        """Un champ vide serait indistinguable d'un champ absent : le
        marqueur tranche, et on rouvre le coffre plutôt que de deviner."""
        env = secrets_to_env({"psk": PSK})
        del env["EL_VPN_SECRETS_PROVIDED"]
        with patch.dict(os.environ, env, clear=False):
            self.assertIsNone(secrets_from_env(("psk",)))

    def test_an_empty_secret_survives_the_trip(self):
        env = secrets_to_env({"psk": PSK, "wg_preshared_key": ""})
        with patch.dict(os.environ, env, clear=False):
            got = secrets_from_env(("psk", "wg_preshared_key"))
        self.assertEqual(got["wg_preshared_key"], "")
        self.assertEqual(got["psk"], PSK)

    def test_no_secret_in_a_variable_name(self):
        """Les noms de variables partent dans l'environnement d'un
        sous-processus : ils ne doivent porter que la CLÉ, jamais la
        valeur."""
        env = secrets_to_env({"psk": PSK})
        for name in env:
            self.assertNotIn(PSK, name)


@unittest.skipUnless(create_database, "pykeepass n'est pas installé")
class VaultToTunnel(unittest.TestCase):
    """La couture complète : coffre → profil → plan de montage.

    Les autres tests injectent les secrets à la main. Celui-ci les fait
    VRAIMENT sortir d'un .kdbx, comme le CLI, et vérifie qu'ils n'ont pas
    fui en chemin. C'est le seul qui juge l'ensemble.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.kdbx_path = os.path.join(self.tmp.name, "secrets.kdbx")
        create_database(self.kdbx_path, password=MASTER)
        # 0600 d'emblée : sinon chaque test verrait le coffre resserré à
        # l'ouverture et l'annoncerait, ce qui noierait la sortie de la
        # suite sous un avertissement qui n'est le sujet que d'un test.
        os.chmod(self.kdbx_path, 0o600)
        self.base = os.path.join(self.tmp.name, "todo.json")
        with open(self.base, "w") as fh:
            json.dump(
                {
                    "kdbx": {"path": self.kdbx_path, "password": MASTER},
                    "vpn": [],
                },
                fh,
            )
        self.patches = [
            patch("script.config.config_file.CONFIG_FILE", self.base),
            patch(
                "script.config.config_file.CONFIG_OVERRIDE_FILE",
                os.path.join(self.tmp.name, "override.json"),
            ),
            patch(
                "script.config.config_file.CONFIG_OVERRIDE_PRIVATE_FILE",
                os.path.join(self.tmp.name, "private.json"),
            ),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in self.patches:
            item.stop()
        self.tmp.cleanup()

    def test_secret_goes_from_the_vault_to_the_plan_without_leaking(self):
        from script.vpn import profiles
        from script.vpn.drivers.l2tp_ipsec import L2tpIpsecDriver
        from script.vpn.runner import Runner
        from script.vpn.vault import redact

        config = ConfigFile()
        vault = VpnVault(config, KdbxManager(config))
        profile = profiles.save(
            {
                "name": "acme",
                "driver": "l2tp_ipsec",
                "server": "127.0.0.1",
                "ppp_user": "ACME\\user",
                "routes": ["10.20.0.0/16"],
            }
        )
        vault.write(
            profiles.secret_title("acme"),
            {
                "username": profile["ppp_user"],
                "password": PPP_PASSWORD,
                "psk": PSK,
            },
        )

        secrets = vault.read(
            profiles.secret_title("acme"), fields=("psk", "password")
        )
        self.assertEqual(secrets["psk"], PSK)
        self.assertEqual(secrets["password"], PPP_PASSWORD)

        driver = L2tpIpsecDriver(profiles.load("acme"), secrets)
        runner = Runner(
            dry_run=True,
            quiet=True,
            redactor=lambda text: redact(text, driver.secret_values()),
        )
        self.assertTrue(driver.up(runner))

        # Le PSK atteint le fichier de secrets, en hexadécimal, et rien
        # d'autre.
        secret_writes = [
            op for op in runner.ops if op["kind"] == "write" and op["secret"]
        ]
        hex_psk = PSK.encode("utf-8").hex()
        self.assertTrue(
            any(hex_psk in op["content"] for op in secret_writes),
            "le PSK n'a pas atteint le fichier de secrets",
        )
        for op in runner.ops:
            if op["kind"] == "cmd":
                self.assertNotIn(PSK, op["cmd"])
                self.assertNotIn(PPP_PASSWORD, op["cmd"])
        # Le PSK en clair n'apparaît dans AUCUN contenu écrit : c'est sa
        # forme hexadécimale qui voyage.
        for op in secret_writes:
            self.assertNotIn(PSK, op["content"])


if __name__ == "__main__":
    unittest.main()
