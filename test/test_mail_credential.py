#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le mot de passe maître déposé par systemd dans `$CREDENTIALS_DIRECTORY`,
et son chiffrement par `systemd-creds --user`.

Aucun programme système n'est lancé : `systemctl` et `systemd-creds` sont
des doubles, et `subprocess.run` est remplacé par une assertion. `HOME`
pointe vers un dossier temporaire.
"""

import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# Argon2 remplacé pour tout le module : voir argon2_rapide.py.
from argon2_rapide import setUpModule  # noqa: E402,F401

from script.todo.mail import credential  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402

MAITRE = "maitre-essai"


class TestReadMasterPassword(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dossier = Path(tmp.name)
        self.env = {"CREDENTIALS_DIRECTORY": str(self.dossier)}

    def ecrire(self, data: bytes) -> None:
        (self.dossier / credential.CREDENTIAL_ID).write_bytes(data)

    def test_reads_the_credential_from_its_directory(self):
        self.ecrire(b"maitre-essai")
        self.assertEqual(
            credential.read_master_password(self.env), "maitre-essai"
        )

    def test_no_directory_gives_none(self):
        self.ecrire(b"maitre-essai")
        self.assertIsNone(credential.read_master_password({}))
        self.assertIsNone(
            credential.read_master_password({"CREDENTIALS_DIRECTORY": ""})
        )

    def test_a_missing_file_gives_none(self):
        self.assertIsNone(credential.read_master_password(self.env))
        self.ecrire(b"")
        self.assertIsNone(credential.read_master_password(self.env))

    def test_one_final_newline_is_dropped(self):
        self.ecrire(b"maitre-essai\n")
        self.assertEqual(
            credential.read_master_password(self.env), "maitre-essai"
        )
        self.ecrire(b"maitre-essai\n\n")
        self.assertEqual(
            credential.read_master_password(self.env), "maitre-essai\n"
        )

    def test_an_oversized_file_gives_none(self):
        self.ecrire(b"x" * (credential.CREDENTIAL_MAX_BYTES + 1))
        self.assertIsNone(credential.read_master_password(self.env))
        self.ecrire(b"x" * credential.CREDENTIAL_MAX_BYTES)
        self.assertEqual(
            len(credential.read_master_password(self.env)),
            credential.CREDENTIAL_MAX_BYTES,
        )

    def test_a_non_utf8_file_gives_none(self):
        self.ecrire(b"\xff\xfe")
        self.assertIsNone(credential.read_master_password(self.env))

    def test_an_unreadable_file_gives_none(self):
        if os.geteuid() == 0:
            self.skipTest("root lit tout fichier")
        self.ecrire(b"maitre-essai")
        os.chmod(self.dossier / credential.CREDENTIAL_ID, 0)
        self.assertIsNone(credential.read_master_password(self.env))


class FakeSystemd:
    """Répond comme `systemctl` et `systemd-creds` ; enregistre chaque
    appel (argv et arguments nommés)."""

    def __init__(self, home, *, unit_path=None, version="systemd 259 (x)"):
        self.appels = []
        self.unit_path = unit_path
        self.version = version
        self.aide = "  --user               Select user-scoped credential"
        self.encrypt = (0, b"\x00chiffre\x01", b"")
        self.decrypt = None
        self.home = home

    def __call__(self, argv, **kwargs):
        self.appels.append((list(argv), kwargs))
        if argv[:3] == ["systemctl", "--user", "show"]:
            if self.unit_path is None:
                raise FileNotFoundError("systemctl")
            return SimpleNamespace(returncode=0, stdout=self.unit_path)
        if argv == ["systemctl", "--version"]:
            if isinstance(self.version, Exception):
                raise self.version
            return SimpleNamespace(returncode=0, stdout=self.version)
        if argv == ["systemd-creds", "--help"]:
            return SimpleNamespace(returncode=0, stdout=self.aide)
        if argv[:3] == ["systemd-creds", "--user", "encrypt"]:
            code, sortie, erreur = self.encrypt
            return SimpleNamespace(
                returncode=code, stdout=sortie, stderr=erreur
            )
        if argv[:3] == ["systemd-creds", "--user", "decrypt"]:
            sortie = self.decrypt
            if sortie is None:
                sortie = self.dernier_clair()
            return SimpleNamespace(returncode=0, stdout=sortie, stderr=b"")
        raise AssertionError(f"appel imprévu : {argv}")

    def dernier_clair(self):
        for argv, kwargs in reversed(self.appels):
            if argv[:3] == ["systemd-creds", "--user", "encrypt"]:
                return kwargs.get("input")
        return b""


class SystemdCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        rustine = mock.patch.dict(
            os.environ,
            {
                "HOME": str(self.home),
                "XDG_CONFIG_HOME": str(self.home / "ailleurs"),
            },
        )
        rustine.start()
        self.addCleanup(rustine.stop)
        filet = mock.patch.object(
            subprocess,
            "run",
            side_effect=AssertionError("programme système appelé"),
        )
        filet.start()
        self.addCleanup(filet.stop)
        self.systemd = FakeSystemd(self.home, unit_path="")
        self.dest = (
            self.home
            / ".config"
            / "credstore.encrypted"
            / (credential.CREDENTIAL_ID)
        )


class TestCredstoreLocation(SystemdCase):
    def test_the_credstore_follows_the_manager_xdg_config_home(self):
        home = self.home
        self.systemd.unit_path = " ".join(
            [
                f"{home}/.config/systemd/user.control",
                "/run/user/1000/systemd/transient",
                f"{home}/conf-perso/systemd/user",
                "/etc/systemd/user",
                f"{home}/.local/share/systemd/user",
            ]
        )
        self.assertEqual(
            credential.credstore_dir(run=self.systemd),
            home / "conf-perso" / "credstore.encrypted",
        )
        self.assertEqual(
            credential.credential_path(run=self.systemd),
            home / "conf-perso" / "credstore.encrypted" / "erplibre-mail-kdbx",
        )
        argv, kwargs = self.systemd.appels[0]
        self.assertEqual(
            argv, ["systemctl", "--user", "show", "-p", "UnitPath", "--value"]
        )
        self.assertNotIn("env", kwargs)

    def test_an_unreadable_unit_path_falls_back_to_dot_config(self):
        attendu = self.home / ".config"
        for unit_path in (None, "", "/etc/systemd/user /usr/lib/systemd/user"):
            with self.subTest(unit_path=unit_path):
                self.systemd.unit_path = unit_path
                self.assertEqual(
                    credential.manager_config_home(run=self.systemd), attendu
                )
        refus = mock.Mock(
            return_value=SimpleNamespace(returncode=1, stdout="")
        )
        self.assertEqual(credential.manager_config_home(run=refus), attendu)
        delai = mock.Mock(
            side_effect=subprocess.TimeoutExpired(["systemctl"], 3)
        )
        self.assertEqual(credential.manager_config_home(run=delai), attendu)

    def test_user_scope_needs_systemd_256_and_the_user_switch(self):
        self.assertTrue(credential.user_scope_supported(run=self.systemd))
        self.systemd.version = "systemd 255 (255.4-1ubuntu8)"
        self.assertFalse(credential.user_scope_supported(run=self.systemd))
        self.systemd.version = "systemd 259 (x)"
        self.systemd.aide = "  --tpm2-device=PATH"
        self.assertFalse(credential.user_scope_supported(run=self.systemd))
        self.systemd.version = FileNotFoundError("systemctl")
        self.assertFalse(credential.user_scope_supported(run=self.systemd))


class TestEncryption(SystemdCase):
    def chiffres(self):
        return [
            (argv, kwargs)
            for argv, kwargs in self.systemd.appels
            if argv[0] == "systemd-creds"
        ]

    def test_the_password_goes_through_stdin_never_argv(self):
        credential.encrypt_master_password(MAITRE, self.dest, run=self.systemd)
        ((argv, kwargs),) = self.chiffres()
        self.assertEqual(
            argv,
            [
                "systemd-creds",
                "--user",
                "encrypt",
                "--name=erplibre-mail-kdbx",
                "-",
                "-",
            ],
        )
        self.assertEqual(kwargs["input"], MAITRE.encode())
        for element in argv:
            self.assertNotIn(MAITRE, element)
        for valeur in (kwargs.get("env") or {}).values():
            self.assertNotIn(MAITRE, valeur)
        self.assertEqual(self.dest.read_bytes(), b"\x00chiffre\x01")

    def test_the_credential_file_is_0600_in_a_0700_directory(self):
        ancien = os.umask(0o022)
        try:
            credential.encrypt_master_password(
                MAITRE, self.dest, run=self.systemd
            )
        finally:
            os.umask(ancien)
        self.assertEqual(stat.S_IMODE(self.dest.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.dest.parent.stat().st_mode), 0o700)

    def test_no_temporary_is_left_behind(self):
        credential.encrypt_master_password(MAITRE, self.dest, run=self.systemd)
        self.assertEqual(os.listdir(self.dest.parent), [self.dest.name])
        with mock.patch.object(
            credential.os, "replace", side_effect=OSError("disque plein")
        ):
            with self.assertRaises(OSError):
                credential.encrypt_master_password(
                    MAITRE, self.dest, run=self.systemd
                )
        self.assertEqual(os.listdir(self.dest.parent), [self.dest.name])

    def test_a_refused_encryption_writes_nothing_and_hides_the_password(self):
        self.systemd.encrypt = (
            1,
            b"",
            f"Failed to encrypt '{MAITRE}': refused".encode(),
        )
        with self.assertRaises(credential.CredentialError) as ctx:
            credential.encrypt_master_password(
                MAITRE, self.dest, run=self.systemd
            )
        message = str(ctx.exception)
        self.assertTrue(message.startswith(t("mail_service_creds_failed")))
        self.assertIn("refused", message)
        self.assertNotIn(MAITRE, message)
        self.assertFalse(self.dest.exists())
        self.systemd.encrypt = (0, b"", b"")
        with self.assertRaises(credential.CredentialError):
            credential.encrypt_master_password(
                MAITRE, self.dest, run=self.systemd
            )
        self.assertFalse(self.dest.exists())

    def coffre(self):
        from script.todo.mail.secrets import create_kdbx

        chemin = self.home / "coffre.kdbx"
        create_kdbx(str(chemin), MAITRE)
        return str(chemin)

    def test_setup_checks_encrypts_and_reads_back(self):
        rendu = credential.setup_credential(
            MAITRE, kdbx_path=self.coffre(), dest=self.dest, run=self.systemd
        )
        self.assertEqual(rendu, self.dest)
        self.assertTrue(self.dest.exists())
        argv, kwargs = self.chiffres()[-1]
        self.assertEqual(
            argv[:4],
            [
                "systemd-creds",
                "--user",
                "decrypt",
                "--name=erplibre-mail-kdbx",
            ],
        )
        self.assertEqual(argv[-2:], [str(self.dest), "-"])
        self.assertNotIn("input", kwargs)

    def test_a_wrong_master_password_writes_nothing(self):
        with self.assertRaises(credential.CredentialError) as ctx:
            credential.setup_credential(
                "faux",
                kdbx_path=self.coffre(),
                dest=self.dest,
                run=self.systemd,
            )
        self.assertEqual(str(ctx.exception), t("mail_service_creds_wrong"))
        self.assertEqual(self.chiffres(), [])
        self.assertFalse(self.dest.exists())

    def test_an_unreadable_credential_is_removed(self):
        self.systemd.decrypt = b"autre-chose"
        with self.assertRaises(credential.CredentialError) as ctx:
            credential.setup_credential(
                MAITRE,
                kdbx_path=self.coffre(),
                dest=self.dest,
                run=self.systemd,
            )
        self.assertEqual(
            str(ctx.exception), t("mail_service_creds_verify_failed")
        )
        self.assertFalse(self.dest.exists())

    def test_remove_credential_says_whether_a_file_was_removed(self):
        self.assertFalse(credential.remove_credential(self.dest))
        credential.encrypt_master_password(MAITRE, self.dest, run=self.systemd)
        self.assertTrue(credential.remove_credential(self.dest))
        self.assertFalse(self.dest.exists())

    def test_a_forgotten_runner_hits_the_safety_net(self):
        with self.assertRaises(AssertionError):
            subprocess.run(["systemctl", "--version"])
        with self.assertRaises(AssertionError):
            credential.user_scope_supported()
        with self.assertRaises(AssertionError):
            credential.manager_config_home()


if __name__ == "__main__":
    unittest.main()
