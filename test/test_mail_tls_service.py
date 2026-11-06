#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Un certificat refusé dans la commande sans interface : code de sortie
9, ligne qui nomme en tête protocole, point d'accès, raison et empreintes,
dès la passe du refus ; le service n'épingle jamais.

Même montage que `test_mail_service_run_sandbox.py` : `HOME`, coffre,
règles et cache temporaires, IMAP derrière `TlsFront`, SMTP d'`aiosmtpd`
en TLS ; l'autorité de test n'est acceptée que sous `trusting`.
"""

import io
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import aiosmtpd  # noqa: F401
    import cryptography  # noqa: F401
    import twisted  # noqa: F401

    SANDBOX_MISSING = ""
except ImportError as exc:  # pragma: no cover - dépend de l'installation
    SANDBOX_MISSING = str(exc)

if SANDBOX_MISSING:  # pragma: no cover - dépend de l'installation
    MailSandboxCase = unittest.TestCase
else:
    import mail_tls
    import test_mail_service_run_sandbox as bout_en_bout
    from mail_sandbox import MailSandboxCase, sandbox_account

from argon2_rapide import setUpModule  # noqa: E402,F401

from script.todo.mail.smtp_send import tls  # noqa: E402

OWN = "boite.regles@example.org"
FP_A = "ab" * 32
FP_B = "cd" * 32


@unittest.skipIf(
    bool(SANDBOX_MISSING), f"serveurs de test absents ({SANDBOX_MISSING})"
)
class TlsServiceCase(MailSandboxCase):
    # Le montage du service de bout en bout, emprunté sans ses tests.
    # Importé comme module et non par nom : une classe de tests nommée
    # ici verrait ses tests relancés dans ce fichier.
    nouveau_home = bout_en_bout.TestServiceEndToEnd.nouveau_home
    environ = staticmethod(bout_en_bout.TestServiceEndToEnd.environ)
    installer = bout_en_bout.TestServiceEndToEnd.installer
    manager = bout_en_bout.TestServiceEndToEnd.manager
    connect = bout_en_bout.TestServiceEndToEnd.connect
    assert_clean = bout_en_bout.TestServiceEndToEnd.assert_clean

    def setUp(self):
        from script.todo.mail.rules.model import Condition, Group, new_rule

        self.pki = mail_tls.shared_pki()
        mail_tls.quiet_tls_log(self)
        confiance = mail_tls.trusting(self.pki.ca_path)
        confiance.start()
        self.addCleanup(confiance.stop)
        self.home = self.nouveau_home()
        rustine = mock.patch.dict(os.environ, self.environ(self.home))
        rustine.start()
        self.addCleanup(rustine.stop)
        filet = mock.patch(
            "script.todo.mail.rules.run.ConfigFile",
            side_effect=AssertionError("configuration réelle lue"),
        )
        filet.start()
        self.addCleanup(filet.stop)
        self.imap = self.imap_server()
        self.inbox = self.imap.folder("INBOX")
        self.imap.folder("INBOX.Sent", attributs=("\\Sent",))
        self.rule = new_rule("reply", "Absence")
        self.rule.action.body = "Je suis absente."
        self.rule.filter = Group("all", [Condition("body", "bonjour")])
        self.connexions = 0
        self.sorties = []

    def monter(
        self,
        *,
        imap_leaf=None,
        smtp_leaf=None,
        question_recue=True,
        name="perso",
    ):
        """Le compte, ses serveurs et sa machine : IMAP en `ssl` derrière
        un frontal qui présente `imap_leaf` (en clair sans lui), SMTP en
        `ssl` avec `smtp_leaf` (en clair sans lui)."""
        if question_recue:
            self.inbox.deliver(
                bout_en_bout.question(),
                uid=1,
                internal_date=bout_en_bout.RECU_IMAP,
            )
        imap_port, imap_sec = self.imap.port, "none"
        if imap_leaf is not None:
            self.front = self.imap_tls(self.imap, self.pki.leaf(imap_leaf))
            imap_port, imap_sec = self.front.port, "ssl"
        if smtp_leaf is not None:
            self.smtp = self.smtp_server(
                tls="ssl", leaf=self.pki.leaf(smtp_leaf)
            )
            smtp_sec = "ssl"
        else:
            self.smtp = self.smtp_server()
            smtp_sec = "none"
        self.account = sandbox_account(
            imap_port=imap_port,
            smtp_port=self.smtp.port,
            name=name,
            address=OWN,
            imap_security=imap_sec,
            smtp_security=smtp_sec,
        )
        self.kdbx, self.secrets, self.creds, self.base = self.installer(
            self.home
        )
        if name != "perso":
            # `installer` range la règle sous « perso » ; le service ne
            # traite qu'un compte qui a une règle active.
            from script.todo.mail.rules import storage

            storage.upsert_rule(name, self.rule, base=self.base)

    def lancer(self, *argv, **champs):
        from test_mail_service_run_sandbox import RECU, FakeConfig

        from script.todo.mail.rules import run

        valeurs = dict(
            config_file=FakeConfig({"kdbx": {"path": str(self.kdbx)}}),
            env={"CREDENTIALS_DIRECTORY": str(self.creds)},
            out=io.StringIO(),
            now=lambda: bout_en_bout.RECU + 600,
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

    def epingler(self, kind, port):
        from script.todo.mail import accounts

        accounts.pin_certificate(
            self.account.name,
            "127.0.0.1",
            port,
            self.pki.leaf(kind).fingerprint,
        )

    def accounts_bytes(self):
        from script.todo.mail import accounts

        return accounts.accounts_path().read_bytes()


class TestServiceTls(TlsServiceCase):
    def test_an_imap_certificate_refusal_exits_9_with_endpoint_and_fingerprint(
        self,
    ):
        from script.todo.mail.rules import run
        from script.todo.todo_i18n import t

        self.monter(imap_leaf="self_a")
        code, sortie = self.lancer()
        self.assertEqual(code, run.EXIT_TLS, sortie)
        self.assertEqual(code, 9)
        fp = self.pki.leaf("self_a").fingerprint
        self.assertIn(
            f"perso : {t('mail_service_kind_tls')} IMAP"
            f" 127.0.0.1:{self.front.port} untrusted sha256={fp}",
            sortie,
        )
        self.assertEqual(self.smtp.messages, [])
        self.assertNotIn(b"LOGIN", self.front.commands)

    def test_the_service_never_pins(self):
        self.monter(imap_leaf="self_a")
        avant = self.accounts_bytes()
        entree = io.StringIO("CONFIANCE\nTRUST\n")
        with mock.patch.object(sys, "stdin", entree):
            code, _ = self.lancer()
            self.lancer("--quiet")
        self.assertEqual(code, 9)
        self.assertEqual(self.accounts_bytes(), avant)
        self.assertEqual(entree.tell(), 0)
        self.assertNotIn("script.todo.mail.tls_trust", self._imports_of_run())

    @staticmethod
    def _imports_of_run():
        import ast

        from script.todo.mail.rules import run

        with open(run.__file__, encoding="utf-8") as source:
            arbre = ast.parse(source.read())
        noms = set()
        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.ImportFrom) and noeud.module:
                noms.add(noeud.module)
                noms |= {f"{noeud.module}.{a.name}" for a in noeud.names}
            elif isinstance(noeud, ast.Import):
                noms |= {a.name for a in noeud.names}
        return noms

    def test_a_changed_certificate_exits_9(self):
        self.monter(imap_leaf="self_b")
        self.epingler("self_a", self.front.port)
        code, sortie = self.lancer()
        self.assertEqual(code, 9, sortie)
        self.assertIn(" changed ", sortie)

    def test_a_changed_certificate_line_names_both_fingerprints(self):
        self.monter(imap_leaf="self_b")
        self.epingler("self_a", self.front.port)
        _, sortie = self.lancer()
        a = self.pki.leaf("self_a").fingerprint
        b = self.pki.leaf("self_b").fingerprint
        self.assertIn(f"changed sha256={b} pinned={a}", sortie)

    def test_a_pinned_certificate_lets_the_pass_run(self):
        self.monter(imap_leaf="self_a")
        self.epingler("self_a", self.front.port)
        code, sortie = self.lancer()
        self.assertEqual(code, 0, sortie)
        self.assertEqual(len(self.smtp.messages), 1)
        self.assertIn(b"LOGIN", self.front.commands)

    def test_an_smtp_refusal_in_the_outbox_exits_9(self):
        from script.todo.mail.smtp_send import build_message
        from script.todo.mail.store import Store
        from script.todo.todo_i18n import t

        self.monter(smtp_leaf="self_a", question_recue=False)
        store = Store(self.account, mode="clear", base=self.base)
        store.open()
        try:
            msg = build_message(
                self.account, "carole.regle@example.org", "Devis", "Bonjour"
            )
            store.queue_message(
                msg.as_bytes(), "carole.regle@example.org", "Devis"
            )
        finally:
            store.close()
        code, sortie = self.lancer()
        self.assertEqual(code, 9, sortie)
        fp = self.pki.leaf("self_a").fingerprint
        self.assertTrue(
            sortie.startswith(
                f"perso : {t('mail_service_kind_tls')} SMTP"
                f" 127.0.0.1:{self.smtp.port} untrusted sha256={fp}"
            ),
            sortie,
        )
        store = Store(self.account, mode="clear", base=self.base)
        store.open()
        try:
            self.assertEqual(len(store.outbox()), 1)
        finally:
            store.close()
        self.assertEqual(self.smtp.messages, [])

    def test_a_rule_reply_refused_by_tls_exits_9_in_the_same_pass(self):
        from script.todo.mail.store import Store

        self.monter(smtp_leaf="self_a")
        code, sortie = self.lancer()
        self.assertEqual(code, 9, sortie)
        self.assertIn(" SMTP 127.0.0.1:", sortie)
        store = Store(self.account, mode="clear", base=self.base)
        store.open()
        try:
            journal = store.rule_log_entries(self.rule.id)
            file = store.outbox()
        finally:
            store.close()
        self.assertIn(
            ("queued", "smtp_transient"),
            [(e["outcome"], e["reason"]) for e in journal],
        )
        self.assertEqual([e["kind"] for e in file], ["auto_reply"])
        self.assertEqual(self.smtp.messages, [])

    def test_a_refusal_while_filing_a_sent_copy_exits_9(self):
        from script.todo.mail.smtp_send import build_message
        from script.todo.mail.store import Store
        from script.todo.todo_i18n import t

        self.monter(imap_leaf="self_a", question_recue=False)
        self.epingler("self_a", self.front.port)
        store = Store(self.account, mode="clear", base=self.base)
        store.open()
        try:
            msg = build_message(
                self.account, "carole.regle@example.org", "Devis", "Bonjour"
            )
            store.queue_message(
                msg.as_bytes(), "carole.regle@example.org", "Devis"
            )
        finally:
            store.close()
        front, nouvelle = self.front, self.pki.leaf("self_b")

        def connecter(account, secret):
            transport = self.connect(account, secret)

            def append_mort(*_args):
                # Le lien meurt pendant le dépôt, et le serveur présente
                # un autre certificat à la reprise.
                front.use(nouvelle)
                raise OSError("lien mort")

            transport.append = append_mort
            return transport

        code, sortie = self.lancer(connect_fn=connecter)
        self.assertEqual(code, 9, sortie)
        a = self.pki.leaf("self_a").fingerprint
        self.assertTrue(
            sortie.startswith(
                f"perso : {t('mail_service_kind_tls')} IMAP"
                f" 127.0.0.1:{front.port} changed sha256={nouvelle.fingerprint}"
                f" pinned={a}"
            ),
            sortie,
        )
        self.assertEqual(len(self.smtp.messages), 1)

    def test_a_refusal_met_by_the_rules_exits_9(self):
        from script.todo.mail.rules import engine

        self.monter(imap_leaf="self_a")
        self.epingler("self_a", self.front.port)
        front, nouvelle = self.front, self.pki.leaf("self_b")
        vrai = engine.run_pass

        def run_pass(session, **champs):
            # Un échange du moteur trouve le lien mort ; la reprise voit
            # un autre certificat et la session passe hors ligne.
            front.use(nouvelle)

            def mort(_transport):
                raise OSError("lien mort")

            with self.assertRaises(tls.TlsCertificateError):
                session.avec_lien(mort)
            return vrai(session, **champs)

        with mock.patch.object(engine, "run_pass", run_pass):
            code, sortie = self.lancer()
        self.assertEqual(code, 9, sortie)
        self.assertIn(
            f" IMAP 127.0.0.1:{front.port} changed"
            f" sha256={nouvelle.fingerprint}",
            sortie,
        )

    def test_a_tls_refusal_is_written_at_every_quiet_pass(self):
        self.monter(imap_leaf="self_a")
        _, premiere = self.lancer("--quiet")
        _, seconde = self.lancer("--quiet")
        self.assertIn("sha256=", premiere)
        self.assertIn("sha256=", seconde)

    def test_a_tls_refusal_after_the_sync_is_written_at_every_quiet_pass(
        self,
    ):
        self.monter(smtp_leaf="self_a")
        _, premiere = self.lancer("--quiet")
        _, seconde = self.lancer("--quiet")
        self.assertIn("sha256=", premiere)
        self.assertIn("sha256=", seconde)


class TestLongLines(TlsServiceCase):
    HOTE = ("h" * 48) + ".example.org"

    def refus(self, reason):
        return tls.TlsCertificateError(
            protocol="smtp",
            host=self.HOTE,
            port=65535,
            reason=reason,
            fingerprint=FP_B,
            pinned=FP_A if reason == "changed" else None,
        )

    def test_the_fingerprints_are_whole_with_long_names(self):
        from script.todo.mail.tui import FlushResult
        from script.todo.todo_i18n import t

        self.assertEqual(len(self.HOTE), 60)
        self.monter(name="compte-de-seize1", question_recue=False)
        self.assertEqual(len(self.account.name), 16)
        for raison in ("untrusted", "changed"):
            for source in ("vidange", "ouverture"):
                with self.subTest(raison=raison, source=source):
                    exc = self.refus(raison)
                    if source == "vidange":
                        with mock.patch(
                            "script.todo.mail.tui.flush_outbox",
                            return_value=FlushResult(0, 0, 1, tls_error=exc),
                        ):
                            code, sortie = self.lancer()
                    else:

                        def refuse(account, secret, exc=exc):
                            raise exc

                        code, sortie = self.lancer(connect_fn=refuse)
                    ligne = sortie.strip().splitlines()[0]
                    self.assertEqual(code, 9)
                    self.assertIn(f"sha256={FP_B}", ligne)
                    # En tête : une ligne plus chargée coupe sa fin, jamais
                    # l'élément TLS.
                    self.assertTrue(
                        ligne.startswith(
                            f"{self.account.name} : "
                            f"{t('mail_service_kind_tls')} SMTP"
                        ),
                        ligne,
                    )
                    if raison == "changed":
                        self.assertIn(f"pinned={FP_A}", ligne)
                    self.assertFalse(ligne.endswith("…"), ligne)
                    self.assertLess(len(ligne), 300)


class TestExitCodes(unittest.TestCase):
    def test_the_tls_kind_comes_after_the_vault_and_before_auth(self):
        from script.todo.mail.rules import run

        self.assertEqual(run.EXIT_BY_KIND["tls"], 9)
        self.assertEqual(run.EXIT_PRIORITY, (1, 8, 3, 9, 7, 5, 4, 6, 0))
        self.assertEqual(run.worst_exit([7, 9]), 9)
        self.assertEqual(run.worst_exit([9, 4, 6]), 9)
        self.assertEqual(run.worst_exit([9, 3]), 3)
        self.assertEqual(run.worst_exit([9, 8]), 8)
        self.assertNotIn("tls", run.REPEAT_SILENT_KINDS)

    def test_the_status_line_labels_exit_9(self):
        from script.todo.mail import service
        from script.todo.todo_i18n import t

        st = service.ServiceStatus(installed=True, last_exit=9)
        self.assertIn(t("mail_service_exit_9"), service.status_text(st))


if __name__ == "__main__":
    unittest.main()
