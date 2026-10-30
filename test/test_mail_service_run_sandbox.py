#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La commande sans interface, de bout en bout, sur un vrai IMAP et SMTP.

Tout vit dans un `HOME` temporaire : comptes, cache, règles, état et
journal. Le coffre est un kdbx temporaire, ouvert par le mot de passe
maître que systemd déposerait dans `$CREDENTIALS_DIRECTORY` ; la
configuration du dépôt n'est jamais lue.

La boîte de réception reçoit une question de Carole, à laquelle une règle
de réponse armée et déjà approuvée répond. Chaque variante vérifie son
code de sortie, ce qui part (ou non) par SMTP, et que la sortie ne nomme
ni adresse ni sujet.
"""

import calendar
import io
import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import aiosmtpd  # noqa: F401
    import twisted  # noqa: F401

    SANDBOX_MISSING = ""
except ImportError as exc:  # pragma: no cover - dépend de l'installation
    SANDBOX_MISSING = str(exc)

if SANDBOX_MISSING:  # pragma: no cover - dépend de l'installation
    MailSandboxCase = unittest.TestCase
else:
    from mail_sandbox import PASSWORD, MailSandboxCase, sandbox_account

# Argon2 remplacé pour tout le module : voir argon2_rapide.py.
from argon2_rapide import setUpModule  # noqa: E402,F401

OWN = "boite.regles@example.org"
CAROLE = "carole.regle@example.org"
MAITRE = "maitre-essai"
RECU = calendar.timegm((2026, 10, 27, 10, 0, 0))
RECU_IMAP = b"27-Oct-2026 10:00:00 +0000"


class FakeConfig(dict):
    """La configuration réduite à un dict ; une clé absente rend None."""

    def get_config_value(self, keys):
        valeur = self
        for cle in keys:
            valeur = valeur.get(cle) if isinstance(valeur, dict) else None
        return valeur


def question():
    return "\r\n".join(
        [
            f"From: Carole <{CAROLE}>",
            f"To: {OWN}",
            "Subject: Question 1",
            "Message-ID: <1@example.net>",
            "",
            "Bonjour, une question.",
            "",
        ]
    ).encode()


@unittest.skipIf(
    bool(SANDBOX_MISSING), f"serveurs de test absents ({SANDBOX_MISSING})"
)
class TestServiceEndToEnd(MailSandboxCase):
    def setUp(self):
        from script.todo.mail import accounts as mail_accounts
        from script.todo.mail.rules import storage
        from script.todo.mail.rules.model import (
            Armed,
            Condition,
            Group,
            new_rule,
        )
        from script.todo.mail.secrets import SecretStore, create_kdbx
        from script.todo.mail.store import Store

        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        self.home = Path(home.name)
        rustine = mock.patch.dict(
            os.environ,
            {
                "HOME": str(self.home),
                "XDG_CONFIG_HOME": str(self.home / ".config"),
            },
        )
        rustine.start()
        self.addCleanup(rustine.stop)
        self.addCleanup(os.chdir, os.getcwd())
        filet = mock.patch(
            "script.todo.mail.rules.run.ConfigFile",
            side_effect=AssertionError("configuration réelle lue"),
        )
        filet.start()
        self.addCleanup(filet.stop)

        self.imap = self.imap_server()
        self.smtp = self.smtp_server()
        self.inbox = self.imap.folder("INBOX")
        self.sent = self.imap.folder("INBOX.Sent", attributs=("\\Sent",))
        self.inbox.deliver(question(), uid=1, internal_date=RECU_IMAP)
        self.account = sandbox_account(
            imap_port=self.imap.port,
            smtp_port=self.smtp.port,
            name="perso",
            address=OWN,
        )
        mail_accounts.save([self.account])

        self.kdbx = self.home / "coffre.kdbx"
        create_kdbx(str(self.kdbx), MAITRE)
        self.secrets = SecretStore(
            kdbx_manager=self.manager(), use_keyring=False
        )
        self.secrets.set(self.account.secret_ref, PASSWORD)
        self.creds = self.home / "creds"
        self.creds.mkdir()
        self.credential(MAITRE)

        self.base = self.home / ".erplibre" / "mail"
        rule = new_rule("reply", "Absence")
        rule.action.body = "Je suis absente."
        rule.filter = Group("all", [Condition("body", "bonjour")])
        storage.upsert_rule(
            "perso", rule, rearm=Armed(42, 1, RECU - 3600), base=self.base
        )
        store = Store(self.account, mode="clear", base=self.base)
        store.open()
        try:
            store.rule_log_claim(
                rule.id,
                "pre-approuvee",
                outcome="sent",
                at=RECU - 30 * 86400,
                fingerprint=rule.fingerprint(),
            )
        finally:
            store.close()
        self.connexions = 0
        self.sorties = []

    def manager(self):
        from script.todo.kdbx_manager import KdbxManager

        return KdbxManager(
            FakeConfig({"kdbx": {"path": str(self.kdbx)}}),
            password=MAITRE,
            interactive=False,
        )

    def credential(self, texte):
        from script.todo.mail import credential

        (self.creds / credential.CREDENTIAL_ID).write_text(texte)

    def connect(self, account, secret):
        from script.todo.mail import imap_transport

        self.connexions += 1
        return imap_transport.connect(account, secret)

    def lancer(self, *argv, **champs):
        from script.todo.mail.rules import run

        valeurs = dict(
            config_file=FakeConfig({"kdbx": {"path": str(self.kdbx)}}),
            env={"CREDENTIALS_DIRECTORY": str(self.creds)},
            out=io.StringIO(),
            now=lambda: RECU + 600,
            connect_fn=self.connect,
            configure_logging=False,
            use_keyring=False,
            limit_core=lambda: None,
        )
        valeurs.update(champs)
        deps = run.ServiceDeps(**valeurs)
        code = run.main(list(argv), deps=deps)
        sortie = deps.out.getvalue()
        self.sorties.append(sortie)
        self.assert_clean(sortie)
        return code, sortie

    def assert_clean(self, sortie):
        self.assertNotIn("@", sortie)
        self.assertNotIn("Question", sortie)
        self.assertNotIn(MAITRE, sortie)
        self.assertNotIn(PASSWORD, sortie)
        self.assertNotIn(str(self.home), sortie)

    # -- envoi ------------------------------------------------------------

    def test_one_reply_leaves_and_the_exit_is_zero(self):
        from script.todo.mail.rules import run

        code, sortie = self.lancer()
        self.assertEqual(code, run.EXIT_OK, sortie)
        self.assertEqual(len(self.smtp.messages), 1)
        self.assertEqual(self.smtp.messages[0].rcpt_tos, [CAROLE])
        self.assertEqual(len(self.sent.appended), 1)
        self.assertTrue(sortie.startswith("perso : "), sortie)

    def test_a_second_run_sends_nothing(self):
        from script.todo.mail.rules import run

        self.assertEqual(self.lancer()[0], run.EXIT_OK)
        code, _ = self.lancer("--quiet")
        self.assertEqual(code, run.EXIT_OK)
        self.assertEqual(len(self.smtp.messages), 1)

    def test_the_output_names_no_address_nor_subject(self):
        self.lancer()
        self.lancer()
        self.lancer(env={})
        self.credential("faux")
        self.lancer()
        self.assertEqual(len(self.sorties), 4)
        for sortie in self.sorties:
            self.assertTrue(sortie)
            self.assert_clean(sortie)

    # -- pannes -----------------------------------------------------------

    def test_without_credential_the_exit_is_vault_and_nothing_is_sent(self):
        from script.todo.mail.rules import run

        code, sortie = self.lancer(env={})
        self.assertEqual(code, run.EXIT_VAULT)
        self.assertEqual(len(sortie.splitlines()), 1)
        self.assertEqual(self.connexions, 0)
        self.assertEqual(self.smtp.messages, [])

    def test_a_wrong_master_password_exits_vault(self):
        from script.todo.mail.rules import run
        from script.todo.todo_i18n import t

        self.credential("faux")
        code, sortie = self.lancer()
        self.assertEqual(code, run.EXIT_VAULT)
        self.assertIn(t("mail_service_vault_wrong_password"), sortie)
        self.assertEqual(self.connexions, 0)
        self.assertEqual(self.smtp.messages, [])

    def test_a_refused_imap_password_exits_auth(self):
        from script.todo.mail.rules import run

        self.secrets.set(self.account.secret_ref, "mauvais")
        code, sortie = self.lancer()
        self.assertEqual(code, run.EXIT_AUTH, sortie)
        self.assertIn("ImapError", sortie)
        self.assertEqual(self.smtp.messages, [])

    def test_a_closed_port_exits_network(self):
        from script.todo.mail import accounts as mail_accounts
        from script.todo.mail.rules import run

        with socket.socket() as libre:
            libre.bind(("127.0.0.1", 0))
            port = libre.getsockname()[1]
        self.account.imap.port = port
        mail_accounts.save([self.account])
        code, sortie = self.lancer()
        self.assertEqual(code, run.EXIT_NETWORK, sortie)
        self.assertEqual(self.smtp.messages, [])

    def test_a_held_account_lock_exits_busy_and_sends_nothing(self):
        from script.todo.mail.rules import run, storage
        from script.todo.mail.rules.lock import file_lock
        from script.todo.todo_i18n import t

        with file_lock(storage.lock_path("perso", self.base), wait=0) as tenu:
            self.assertTrue(tenu)
            code, sortie = self.lancer(lock_wait=0.2)
        self.assertEqual(code, run.EXIT_BUSY)
        self.assertIn(t("mail_service_busy"), sortie)
        self.assertEqual(self.smtp.messages, [])

    def test_corrupted_rules_exit_rule_without_connecting(self):
        from script.todo.mail.rules import run, storage

        storage.rules_path("perso", self.base).write_text("{ corrompu")
        code, _ = self.lancer()
        self.assertEqual(code, run.EXIT_RULE)
        self.assertEqual(self.connexions, 0)
        self.assertEqual(self.smtp.messages, [])


if __name__ == "__main__":
    unittest.main()
