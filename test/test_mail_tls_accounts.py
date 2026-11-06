#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les empreintes épinglées dans `accounts.json`, l'écriture du fichier et
le geste qui épingle (`tls_trust`).

Le fichier garde la version 3 : un client déjà lancé relit un fichier
épinglé sans erreur. Une épingle illisible est écartée avec une ligne de
journal, jamais fatale. Une écriture remplace le fichier d'un coup, sous
un verrou, et garde les épingles du disque.
"""

import json
import os
import re
import string
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from script.todo import todo_i18n
from script.todo.mail import accounts, tls_trust
from script.todo.mail.accounts import Account, AccountError, ServerConf
from script.todo.mail.smtp_send import tls

OWN = "boite.regles@example.org"
CAROLE = "carole.regle@example.org"
FP_A = "ab" * 32
FP_B = "cd" * 32
HOTE = "serveur.example.org"

# Les clés de compte et de `ServerConf` qu'écrivait et que lisait le code
# d'avant les épingles : un lecteur de ce temps-là lève sur une clé
# inconnue dans `imap`/`smtp`, et ignore une clé de compte inconnue.
ANCIENNES_CLES_COMPTE = {
    "name",
    "email",
    "imap",
    "smtp",
    "secret_ref",
    "display_name",
    "preset",
    "cache_mode",
    "sent_folder",
    "enabled",
    "auth",
    "signature",
}
ANCIENNES_CLES_SERVEUR = {"host", "port", "security", "user"}

# Le texte qu'écrivait le code d'avant les épingles pour `_comptes()`.
TEXTE_SANS_EPINGLE = """{
  "version": 3,
  "default_account": "perso",
  "accounts": [
    {
      "name": "perso",
      "email": "boite.regles@example.org",
      "imap": {
        "host": "serveur.example.org",
        "port": 993,
        "security": "ssl",
        "user": "boite.regles@example.org"
      },
      "smtp": {
        "host": "serveur.example.org",
        "port": 587,
        "security": "starttls",
        "user": "boite.regles@example.org"
      },
      "secret_ref": "kdbx:ERPLibre/Mail/perso",
      "display_name": "",
      "preset": "generic",
      "cache_mode": null,
      "sent_folder": "Sent",
      "enabled": true,
      "auth": "login",
      "signature": ""
    },
    {
      "name": "carole",
      "email": "carole.regle@example.org",
      "imap": {
        "host": "serveur.example.org",
        "port": 993,
        "security": "ssl",
        "user": "carole.regle@example.org"
      },
      "smtp": {
        "host": "serveur.example.org",
        "port": 587,
        "security": "starttls",
        "user": "carole.regle@example.org"
      },
      "secret_ref": "kdbx:ERPLibre/Mail/carole",
      "display_name": "",
      "preset": "generic",
      "cache_mode": null,
      "sent_folder": "Sent",
      "enabled": true,
      "auth": "login",
      "signature": ""
    }
  ]
}"""


def _compte(nom, adresse, **extra):
    return Account(
        name=nom,
        email=adresse,
        imap=ServerConf(host=HOTE, port=993, security="ssl", user=adresse),
        smtp=ServerConf(
            host=HOTE, port=587, security="starttls", user=adresse
        ),
        secret_ref=f"kdbx:ERPLibre/Mail/{nom}",
        **extra,
    )


def _comptes():
    return [_compte("perso", OWN), _compte("carole", CAROLE)]


def _refus(reason="untrusted", fingerprint=FP_A, pinned=None, names=()):
    return tls.TlsCertificateError(
        protocol="imap",
        host=HOTE,
        port=993,
        reason=reason,
        fingerprint=fingerprint,
        pinned=pinned,
        names=names,
    )


class FileCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "mail" / "accounts.json"

    def ecrit(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data))

    def brut(self):
        return json.loads(self.path.read_text())


class TestPinsInTheFile(FileCase):
    def test_pins_round_trip_normalised(self):
        forme = ":".join(FP_A[i : i + 2].upper() for i in range(0, 64, 2))
        compte = _compte(
            "perso", OWN, tls_pins={"SERVEUR.example.org.:993": forme}
        )
        accounts.save([compte], self.path)
        self.assertEqual(
            self.brut()["accounts"][0]["tls_pins"],
            {f"{HOTE}:993": "sha256:" + FP_A},
        )
        self.assertEqual(
            accounts.load(self.path)[0].tls_pins,
            {f"{HOTE}:993": "sha256:" + FP_A},
        )

    def test_a_file_without_pins_is_written_as_before(self):
        accounts.save(_comptes(), self.path)
        self.assertEqual(self.path.read_text(), TEXTE_SANS_EPINGLE)
        self.assertNotIn("tls_pins", self.path.read_text())

    def test_a_pinned_file_stays_version_3(self):
        accounts.save(_comptes(), self.path)
        accounts.pin_certificate("perso", HOTE, 993, FP_A, self.path)
        self.assertEqual(self.brut()["version"], 3)
        self.assertEqual(accounts.SCHEMA_VERSION, 3)

    def test_an_older_reader_reads_a_pinned_file(self):
        accounts.save(_comptes(), self.path)
        accounts.pin_certificate("perso", HOTE, 993, FP_A, self.path)
        data = self.brut()
        self.assertLessEqual(data["version"], 3)
        for brut in data["accounts"]:
            self.assertLessEqual(
                set(brut) - ANCIENNES_CLES_COMPTE, {"tls_pins"}
            )
            for cote in ("imap", "smtp"):
                self.assertLessEqual(set(brut[cote]), ANCIENNES_CLES_SERVEUR)
        self.assertIn("tls_pins", data["accounts"][0])

    def test_other_account_guard_survives_a_pin(self):
        from script.todo.mail.rules import engine

        accounts.save(_comptes(), self.path)
        accounts.pin_certificate("perso", HOTE, 993, FP_A, self.path)
        perso = accounts.load(self.path)[0]
        with mock.patch.object(
            accounts, "accounts_path", return_value=self.path
        ):
            autres = engine.other_account_addresses(perso)
        self.assertIn(CAROLE, autres)

    def test_an_invalid_pin_value_is_ignored_with_a_warning(self):
        accounts.save(_comptes(), self.path)
        data = self.brut()
        data["accounts"][0]["tls_pins"] = {
            f"{HOTE}:993": "pas une empreinte",
            f"{HOTE}:587": "sha256:" + FP_B,
        }
        self.ecrit(data)
        with self.assertLogs("script.todo.mail.accounts", "WARNING") as log:
            perso = accounts.load(self.path)[0]
        self.assertEqual(perso.tls_pins, {f"{HOTE}:587": "sha256:" + FP_B})
        self.assertNotIn("pas une empreinte", "\n".join(log.output))

    def test_an_invalid_pin_key_is_ignored_with_a_warning(self):
        accounts.save(_comptes(), self.path)
        data = self.brut()
        data["accounts"][0]["tls_pins"] = {
            "sans-port": "sha256:" + FP_A,
            f"{HOTE}:587": "sha256:" + FP_B,
        }
        self.ecrit(data)
        with self.assertLogs("script.todo.mail.accounts", "WARNING"):
            perso = accounts.load(self.path)[0]
        self.assertEqual(perso.tls_pins, {f"{HOTE}:587": "sha256:" + FP_B})

    def test_a_non_mapping_is_ignored_with_a_warning(self):
        accounts.save(_comptes(), self.path)
        for valeur in ([], "", 0, False, "x"):
            with self.subTest(valeur=valeur):
                data = self.brut()
                data["accounts"][0]["tls_pins"] = valeur
                self.ecrit(data)
                with self.assertLogs(
                    "script.todo.mail.accounts", "WARNING"
                ) as log:
                    perso = accounts.load(self.path)[0]
                self.assertEqual(perso.tls_pins, {})
                self.assertEqual(len(log.output), 1)
        for valeur in (None, "absent"):
            with self.subTest(valeur=valeur):
                data = self.brut()
                if valeur == "absent":
                    data["accounts"][0].pop("tls_pins", None)
                else:
                    data["accounts"][0]["tls_pins"] = None
                self.ecrit(data)
                with self.assertNoLogs("script.todo.mail.accounts", "WARNING"):
                    perso = accounts.load(self.path)[0]
                self.assertEqual(perso.tls_pins, {})

    def test_a_corrupt_pin_does_not_block_the_other_accounts(self):
        accounts.save(_comptes(), self.path)
        data = self.brut()
        data["accounts"][0]["tls_pins"] = {"x": 12}
        self.ecrit(data)
        with self.assertLogs("script.todo.mail.accounts", "WARNING"):
            lus = accounts.load(self.path)
        self.assertEqual([a.name for a in lus], ["perso", "carole"])

    def test_the_template_stays_version_3(self):
        accounts.write_template(self.path)
        data = self.brut()
        self.assertEqual(data["version"], 3)
        for brut in data["accounts"]:
            self.assertNotIn("tls_pins", brut)

    def test_no_password_word_in_a_pinned_file(self):
        accounts.save(_comptes(), self.path)
        accounts.pin_certificate("perso", HOTE, 993, FP_A, self.path)
        self.assertNotIn("password", self.path.read_text().lower())


class TestPinWrites(FileCase):
    def setUp(self):
        super().setUp()
        accounts.save(_comptes(), self.path)

    def test_pin_certificate_refuses_an_invalid_fingerprint(self):
        avant = self.path.read_bytes()
        with self.assertRaises(AccountError):
            accounts.pin_certificate("perso", HOTE, 993, "zz", self.path)
        self.assertEqual(self.path.read_bytes(), avant)

    def test_pin_certificate_on_an_unknown_account_raises(self):
        avant = self.path.read_bytes()
        with self.assertRaises(AccountError):
            accounts.pin_certificate("inconnu", HOTE, 993, FP_A, self.path)
        self.assertEqual(self.path.read_bytes(), avant)

    def test_pin_certificate_rereads_and_keeps_other_accounts(self):
        data = self.brut()
        data["accounts"][1]["signature"] = "Carole, sur le disque"
        self.ecrit(data)
        relu = accounts.pin_certificate("perso", HOTE, 993, FP_A, self.path)
        self.assertEqual(relu.tls_pins, {f"{HOTE}:993": "sha256:" + FP_A})
        carole = accounts.load(self.path)[1]
        self.assertEqual(carole.signature, "Carole, sur le disque")

    def test_pin_replaces_the_previous_fingerprint_of_the_endpoint(self):
        accounts.pin_certificate("perso", HOTE, 993, FP_A, self.path)
        accounts.pin_certificate("perso", HOTE.upper(), 993, FP_B, self.path)
        self.assertEqual(
            accounts.load(self.path)[0].tls_pins,
            {f"{HOTE}:993": "sha256:" + FP_B},
        )

    def test_unpin_certificate_removes_only_that_endpoint(self):
        accounts.pin_certificate("perso", HOTE, 993, FP_A, self.path)
        accounts.pin_certificate("perso", HOTE, 587, FP_B, self.path)
        accounts.unpin_certificate("perso", f"{HOTE}:993", self.path)
        self.assertEqual(
            accounts.load(self.path)[0].tls_pins,
            {f"{HOTE}:587": "sha256:" + FP_B},
        )

    def test_unpin_of_an_absent_key_writes_nothing(self):
        avant = self.path.read_bytes()
        mtime = os.stat(self.path).st_mtime_ns
        with mock.patch.object(accounts, "_write_private") as ecrit:
            accounts.unpin_certificate("perso", f"{HOTE}:993", self.path)
        ecrit.assert_not_called()
        self.assertEqual(self.path.read_bytes(), avant)
        self.assertEqual(os.stat(self.path).st_mtime_ns, mtime)

    def test_pinned_certificates_lists_in_order(self):
        accounts.pin_certificate("carole", HOTE, 993, FP_B, self.path)
        accounts.pin_certificate("perso", HOTE, 993, FP_A, self.path)
        accounts.pin_certificate(
            "perso", "autre.example.net", 465, FP_B, self.path
        )
        self.assertEqual(
            accounts.pinned_certificates(accounts.load(self.path)),
            [
                ("perso", "autre.example.net:465", FP_B),
                ("perso", f"{HOTE}:993", FP_A),
                ("carole", f"{HOTE}:993", FP_B),
            ],
        )

    def test_a_stale_save_keeps_a_pin_set_meanwhile(self):
        lue = accounts.load(self.path)
        accounts.pin_certificate("perso", HOTE, 993, FP_A, self.path)
        lue[0].signature = "Signée"
        accounts.save(lue, self.path)
        perso = accounts.load(self.path)[0]
        self.assertEqual(perso.signature, "Signée")
        self.assertEqual(perso.tls_pins, {f"{HOTE}:993": "sha256:" + FP_A})

    def test_a_stale_save_does_not_revive_a_removed_pin(self):
        accounts.pin_certificate("perso", HOTE, 993, FP_A, self.path)
        lue = accounts.load(self.path)
        self.assertTrue(lue[0].tls_pins)
        accounts.unpin_certificate("perso", f"{HOTE}:993", self.path)
        accounts.save(lue, self.path)
        self.assertEqual(accounts.load(self.path)[0].tls_pins, {})

    def test_re_adding_an_account_keeps_its_pins(self):
        from script.todo.mail.account_setup import save_new_account

        accounts.pin_certificate("perso", HOTE, 993, FP_A, self.path)
        neuf = _compte("perso", OWN, signature="Nouvelle")
        coffre = mock.Mock()
        with mock.patch.object(
            accounts, "accounts_path", return_value=self.path
        ):
            save_new_account(coffre, [neuf, _comptes()[1]], neuf, "secret")
        perso = accounts.load(self.path)[0]
        self.assertEqual(perso.signature, "Nouvelle")
        self.assertEqual(perso.tls_pins, {f"{HOTE}:993": "sha256:" + FP_A})

    def test_a_new_account_is_written_with_its_own_pins(self):
        neuf = _compte(
            "neuf", "neuf@example.org", tls_pins={f"{HOTE}:993": FP_B}
        )
        accounts.save(accounts.load(self.path) + [neuf], self.path)
        self.assertEqual(
            accounts.load(self.path)[2].tls_pins,
            {f"{HOTE}:993": "sha256:" + FP_B},
        )

    def test_the_write_is_atomic(self):
        avant = self.path.read_bytes()

        def panne(*_a, **_k):
            raise OSError("disque plein")

        with mock.patch.object(accounts.os, "replace", panne):
            with self.assertRaises(OSError):
                accounts.pin_certificate("perso", HOTE, 993, FP_A, self.path)
            with self.assertRaises(OSError):
                accounts.save(_comptes()[:1], self.path)
        self.assertEqual(self.path.read_bytes(), avant)
        restes = [
            p.name
            for p in self.path.parent.iterdir()
            if p.name.startswith(".accounts.")
        ]
        self.assertEqual(restes, [])
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)

    def test_a_held_lock_refuses_to_write(self):
        from script.todo.mail.rules.lock import file_lock

        avant = self.path.read_bytes()
        verrou = self.path.parent / accounts.ACCOUNTS_LOCK_NAME
        with (
            mock.patch.object(accounts, "ACCOUNTS_LOCK_WAIT_S", 0.05),
            file_lock(verrou, wait=0) as tenu,
        ):
            self.assertTrue(tenu)
            for geste in (
                lambda: accounts.save(_comptes()[:1], self.path),
                lambda: accounts.pin_certificate(
                    "perso", HOTE, 993, FP_A, self.path
                ),
                lambda: accounts.unpin_certificate(
                    "perso", f"{HOTE}:993", self.path
                ),
            ):
                with self.assertRaises(AccountError) as ctx:
                    geste()
                self.assertEqual(
                    str(ctx.exception), todo_i18n.t("mail_err_accounts_busy")
                )
        self.assertEqual(self.path.read_bytes(), avant)


class TestRefreshPins(FileCase):
    def setUp(self):
        super().setUp()
        accounts.save(_comptes(), self.path)

    def test_refresh_tls_pins_reads_the_disk(self):
        compte = accounts.load(self.path)[0]
        accounts.pin_certificate("perso", HOTE, 993, FP_A, self.path)
        accounts.refresh_tls_pins(compte, self.path)
        self.assertEqual(compte.tls_pins, {f"{HOTE}:993": "sha256:" + FP_A})
        accounts.unpin_certificate("perso", f"{HOTE}:993", self.path)
        accounts.refresh_tls_pins(compte, self.path)
        self.assertEqual(compte.tls_pins, {})

    def test_refresh_tls_pins_keeps_memory_when_the_file_is_unreadable(self):
        compte = _compte("perso", OWN, tls_pins={f"{HOTE}:993": FP_A})
        self.path.write_text("{ pas du json")
        accounts.refresh_tls_pins(compte, self.path)
        self.assertEqual(compte.tls_pins, {f"{HOTE}:993": "sha256:" + FP_A})

    def test_refresh_tls_pins_keeps_memory_when_the_account_is_absent(self):
        compte = _compte("ailleurs", OWN, tls_pins={f"{HOTE}:993": FP_A})
        accounts.refresh_tls_pins(compte, self.path)
        self.assertEqual(compte.tls_pins, {f"{HOTE}:993": "sha256:" + FP_A})


class TestPinSource(FileCase):
    """Un compte relit ses épingles dans le fichier d'où il vient ; un
    compte construit en mémoire n'ouvre aucun fichier, `HOME` compris."""

    def setUp(self):
        super().setUp()
        accounts.save(_comptes(), self.path)
        accounts.pin_certificate("perso", HOTE, 993, FP_A, self.path)
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        # Un HOME dont `accounts.json` porte un compte du même nom, avec
        # une autre épingle : il ne doit jamais être lu.
        rustine = mock.patch.dict(os.environ, {"HOME": home.name})
        rustine.start()
        self.addCleanup(rustine.stop)
        accounts.save([_compte("perso", OWN)])
        accounts.pin_certificate("perso", HOTE, 993, FP_B)

    def test_load_and_save_tie_the_account_to_their_file(self):
        self.assertEqual(
            accounts.source_of(accounts.load(self.path)[0]), self.path
        )
        compte = _compte("neuf", OWN)
        self.assertIsNone(accounts.source_of(compte))
        accounts.save([*accounts.load(self.path), compte], self.path)
        self.assertEqual(accounts.source_of(compte), self.path)

    def test_a_tied_account_rereads_its_own_file(self):
        compte = accounts.load(self.path)[0]
        accounts.unpin_certificate("perso", f"{HOTE}:993", self.path)
        accounts.refresh_tls_pins(compte)
        self.assertEqual(compte.tls_pins, {})

    def test_an_account_built_in_memory_opens_no_file(self):
        compte = _compte("perso", OWN, tls_pins={f"{HOTE}:993": FP_A})
        with mock.patch.object(
            accounts, "load", side_effect=AssertionError("fichier lu")
        ):
            accounts.refresh_tls_pins(compte)
        self.assertEqual(compte.tls_pins, {f"{HOTE}:993": "sha256:" + FP_A})


class TestSymlinkedFile(FileCase):
    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cible = Path(tmp.name) / "config" / "accounts.json"
        self.cible.parent.mkdir()
        accounts.save(_comptes(), self.cible)
        self.path.parent.mkdir(parents=True)
        self.path.symlink_to(self.cible)

    def test_a_save_writes_through_the_link(self):
        comptes = accounts.load(self.path)
        comptes[0].signature = "Bonne journée"
        accounts.save(comptes, self.path)
        self.assertTrue(self.path.is_symlink())
        self.assertEqual(
            accounts.load(self.cible)[0].signature, "Bonne journée"
        )
        self.assertEqual(self.cible.stat().st_mode & 0o777, 0o600)

    def test_a_pin_writes_through_the_link(self):
        accounts.pin_certificate("perso", HOTE, 993, FP_A, self.path)
        self.assertTrue(self.path.is_symlink())
        self.assertEqual(
            accounts.load(self.cible)[0].tls_pins,
            {f"{HOTE}:993": "sha256:" + FP_A},
        )
        restes = [
            p.name
            for p in (
                *self.cible.parent.iterdir(),
                *self.path.parent.iterdir(),
            )
            if p.name.endswith(".tmp")
        ]
        self.assertEqual(restes, [])


class TestTlsTrust(FileCase):
    def setUp(self):
        super().setUp()
        accounts.save(_comptes(), self.path)

    def test_question_for_a_refusal_names_account_endpoint_reason_and_fingerprint(
        self,
    ):
        texte = tls_trust.question("perso", _refus())
        self.assertIn("perso", texte)
        self.assertIn(f"{HOTE}:993", texte)
        self.assertIn("IMAP", texte)
        self.assertIn(tls.reason_text("untrusted"), texte)
        self.assertIn(tls.format_fingerprint(FP_A), texte)

    def test_question_for_a_change_names_both_fingerprints(self):
        texte = tls_trust.question(
            "perso", _refus("changed", fingerprint=FP_B, pinned=FP_A)
        )
        self.assertIn(tls.format_fingerprint(FP_A), texte)
        self.assertIn(tls.format_fingerprint(FP_B), texte)
        self.assertLess(
            texte.index(tls.format_fingerprint(FP_A)),
            texte.index(tls.format_fingerprint(FP_B)),
        )

    def test_question_shows_the_fingerprint_in_openssl_form(self):
        texte = tls_trust.question("perso", _refus())
        self.assertRegex(texte, r"(?:[0-9A-F]{2}:){31}[0-9A-F]{2}")
        self.assertNotIn(FP_A, texte)

    def test_question_for_a_wrong_name_lists_the_certificate_names(self):
        texte = tls_trust.question(
            "perso",
            _refus("hostname", names=("autre.example.net", "x.example.net")),
        )
        self.assertIn("autre.example.net, x.example.net", texte)
        sans = tls_trust.question("perso", _refus("hostname"))
        self.assertIn(todo_i18n.t("mail_tls_question_names_unknown"), sans)

    def test_question_for_validity_says_dates_are_no_longer_checked(self):
        self.assertIn(
            todo_i18n.t("mail_tls_question_validity"),
            tls_trust.question("perso", _refus("validity")),
        )
        self.assertNotIn(
            todo_i18n.t("mail_tls_question_validity"),
            tls_trust.question("perso", _refus()),
        )

    def test_question_for_nonconforming_advises_fixing_the_certificate(self):
        self.assertIn(
            todo_i18n.t("mail_tls_question_nonconforming"),
            tls_trust.question("perso", _refus("nonconforming")),
        )

    def test_pin_writes_the_file_and_the_account_in_memory(self):
        compte = accounts.load(self.path)[0]
        tls_trust.pin(compte, _refus(), self.path)
        attendu = {f"{HOTE}:993": "sha256:" + FP_A}
        self.assertEqual(compte.tls_pins, attendu)
        self.assertEqual(accounts.load(self.path)[0].tls_pins, attendu)

    def test_pin_refuses_an_unpinnable_refusal(self):
        avant = self.path.read_bytes()
        compte = accounts.load(self.path)[0]
        with self.assertRaises(ValueError):
            tls_trust.pin(compte, _refus(fingerprint=""), self.path)
        self.assertEqual(self.path.read_bytes(), avant)

    def test_unpin_removes_the_pin(self):
        accounts.pin_certificate("perso", HOTE, 993, FP_A, self.path)
        tls_trust.unpin("perso", f"{HOTE}:993", self.path)
        self.assertEqual(accounts.load(self.path)[0].tls_pins, {})


class TestTlsKeys(unittest.TestCase):
    CLES = (
        "mail_tls_trust_word",
        "mail_tls_question_refused",
        "mail_tls_question_changed",
        "mail_tls_question_names",
        "mail_tls_question_names_unknown",
        "mail_tls_question_validity",
        "mail_tls_question_nonconforming",
        "mail_tls_compose_resend",
        "mail_tls_compose_kept",
        "mail_err_accounts_busy",
        "mail_tls_status",
        "mail_tls_review_binding",
        "mail_tls_review_none",
        "mail_tls_pin_unavailable",
        "mail_tls_pin_declined",
        "mail_tls_pin_failed",
        "mail_tls_pinned_done",
        "mail_tls_pinned_smtp_hint",
        "mail_tls_reconnected",
        "mail_tls_menu_hint",
        "mail_help_tls",
        "mail_connection_smtp_ok",
        "mail_connection_smtp_failed",
        "mail_account_tls_pins",
        "mail_tls_pins_none",
        "mail_tls_ask_unpin",
        "mail_tls_unpin_question",
        "mail_tls_unpinned",
        "mail_err_invalid_tls_pin",
        "mail_err_account_not_found",
        "mail_service_kind_tls",
        "mail_service_exit_9",
    )

    @staticmethod
    def champs(texte):
        return {nom for _, nom, _, _ in string.Formatter().parse(texte) if nom}

    def test_every_tls_key_has_both_languages_and_the_same_fields(self):
        for cle in self.CLES:
            with self.subTest(cle=cle):
                entree = todo_i18n.TRANSLATIONS[cle]
                self.assertTrue(entree.get("fr"))
                self.assertTrue(entree.get("en"))
                self.assertEqual(
                    self.champs(entree["fr"]), self.champs(entree["en"])
                )

    def test_the_trust_word_has_no_accent_and_differs_from_the_risk_word(
        self,
    ):
        for lang in ("fr", "en"):
            mot = todo_i18n.TRANSLATIONS["mail_tls_trust_word"][lang]
            self.assertTrue(re.fullmatch(r"[A-Z]+", mot), mot)
            self.assertNotEqual(
                mot, todo_i18n.TRANSLATIONS["mail_confirm_risk_word"][lang]
            )


if __name__ == "__main__":
    unittest.main()
