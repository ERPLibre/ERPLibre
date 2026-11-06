#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La vérification des certificats contre les bacs à sable, en SSL et en
STARTTLS, avec les vrais `imap_transport.connect` et `smtp_send.connect`.

IMAP passe par `TlsFront` devant le serveur Twisted, SMTP par le TLS
d'`aiosmtpd`. Certificats et autorité de test viennent de `mail_tls` ;
l'autorité n'est acceptée que sous `trusting`.
"""

import threading
import unittest

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
    from mail_sandbox import (
        LIVE_SERVERS,
        PASSWORD,
        MailSandboxCase,
        TlsFront,
        close_imap_client,
        port_is_closed,
        sandbox_account,
    )

from script.todo.mail import imap_transport, smtp_send  # noqa: E402
from script.todo.mail.smtp_send import tls  # noqa: E402

requires_servers = unittest.skipIf(
    bool(SANDBOX_MISSING), f"bacs à sable absents ({SANDBOX_MISSING})"
)
SECURITES = ("ssl", "starttls")
OWN = "boite.regles@example.org"
CAROLE = "carole.regle@example.org"


@requires_servers
class TlsCase(MailSandboxCase):
    @classmethod
    def setUpClass(cls):
        cls.pki = mail_tls.shared_pki()

    def setUp(self):
        super().setUp()
        mail_tls.quiet_tls_log(self)

    def trusting(self):
        patch = mail_tls.trusting(self.pki.ca_path)
        patch.start()
        self.addCleanup(patch.stop)

    @staticmethod
    def pins(port, kind_leaf):
        return {
            tls.pin_key("127.0.0.1", port): tls.pin_value(
                kind_leaf.fingerprint
            )
        }


class TestImapTls(TlsCase):
    def serveur(self, security, kind):
        sandbox = self.imap_server()
        sandbox.folder("INBOX")
        front = self.imap_tls(
            sandbox, self.pki.leaf(kind), starttls=security == "starttls"
        )
        return sandbox, front

    def compte(self, front, security, pins=None):
        return sandbox_account(
            imap_port=front.port, imap_security=security, tls_pins=pins
        )

    def connecte(self, compte):
        transport = imap_transport.connect(compte, PASSWORD)
        self.addCleanup(close_imap_client, transport)
        return transport

    def refus(self, compte):
        with self.assertRaises(tls.TlsCertificateError) as ctx:
            imap_transport.connect(compte, PASSWORD)
        return ctx.exception

    def test_a_valid_certificate_connects_and_logs_in(self):
        self.trusting()
        for security in SECURITES:
            with self.subTest(security=security):
                _, front = self.serveur(security, "ok")
                transport = self.connecte(self.compte(front, security))
                noms = [f.name for f in transport.list_folders()]
                self.assertIn("INBOX", noms)
                self.assertIn(b"LOGIN", front.commands)

    def test_a_wrong_name_is_refused_with_its_fingerprint(self):
        self.trusting()
        for security in SECURITES:
            with self.subTest(security=security):
                _, front = self.serveur(security, "wrong_name")
                exc = self.refus(self.compte(front, security))
                self.assertEqual(exc.reason, "hostname")
                self.assertEqual(
                    exc.fingerprint, self.pki.leaf("wrong_name").fingerprint
                )
                self.assertEqual(exc.names, ("autre.example.net",))

    def test_a_self_signed_certificate_is_refused_with_its_fingerprint(self):
        self.trusting()
        for security in SECURITES:
            with self.subTest(security=security):
                _, front = self.serveur(security, "self_a")
                exc = self.refus(self.compte(front, security))
                self.assertEqual(exc.reason, "untrusted")
                fp = self.pki.leaf("self_a").fingerprint
                self.assertEqual(exc.fingerprint, fp)
                self.assertIn(tls.format_fingerprint(fp), str(exc))
                self.assertIn(f"127.0.0.1:{front.port}", str(exc))
                self.assertNotIsInstance(exc, imap_transport.ImapError)

    def test_an_expired_certificate_is_refused(self):
        self.trusting()
        for security in SECURITES:
            with self.subTest(security=security):
                _, front = self.serveur(security, "expired")
                self.assertEqual(
                    self.refus(self.compte(front, security)).reason,
                    "validity",
                )

    def test_a_pinned_self_signed_certificate_connects(self):
        self.trusting()
        for security in SECURITES:
            with self.subTest(security=security):
                _, front = self.serveur(security, "self_a")
                pins = self.pins(front.port, self.pki.leaf("self_a"))
                transport = self.connecte(self.compte(front, security, pins))
                self.assertIn(
                    "INBOX", [f.name for f in transport.list_folders()]
                )

    def test_a_changed_certificate_is_refused_with_both_fingerprints(self):
        self.trusting()
        a, b = self.pki.leaf("self_a"), self.pki.leaf("self_b")
        for security in SECURITES:
            with self.subTest(security=security):
                _, front = self.serveur(security, "self_a")
                front.use(b)
                lu = tls.peer_certificate(
                    "imap", "127.0.0.1", front.port, security, 5
                )
                self.assertEqual(lu[0], b.der)
                exc = self.refus(
                    self.compte(front, security, self.pins(front.port, a))
                )
                self.assertEqual(exc.reason, "changed")
                self.assertEqual(exc.pinned, a.fingerprint)
                self.assertEqual(exc.fingerprint, b.fingerprint)
                self.assertIn(tls.format_fingerprint(a.fingerprint), str(exc))
                self.assertIn(tls.format_fingerprint(b.fingerprint), str(exc))

    def test_no_credential_reaches_the_server_on_a_refusal(self):
        self.trusting()
        a = self.pki.leaf("self_a")
        for security in SECURITES:
            for cas in ("verification", "changed"):
                with self.subTest(security=security, cas=cas):
                    _, front = self.serveur(security, "self_b")
                    pins = (
                        self.pins(front.port, a) if cas == "changed" else None
                    )
                    self.refus(self.compte(front, security, pins))
                    front.stop()
                    self.assertNotIn(b"LOGIN", front.commands)
                    self.assertNotIn(b"AUTHENTICATE", front.commands)

    def test_the_production_trust_refuses_the_test_authority(self):
        for security in SECURITES:
            with self.subTest(security=security):
                _, front = self.serveur(security, "ok")
                self.assertEqual(
                    self.refus(self.compte(front, security)).reason,
                    "untrusted",
                )

    def test_a_pin_for_another_endpoint_is_ignored(self):
        self.trusting()
        for security in SECURITES:
            with self.subTest(security=security):
                _, front = self.serveur(security, "self_a")
                pins = self.pins(front.port + 1, self.pki.leaf("self_a"))
                exc = self.refus(self.compte(front, security, pins))
                self.assertEqual(exc.reason, "untrusted")

    def test_plain_security_ignores_pins(self):
        sandbox = self.imap_server()
        sandbox.folder("INBOX")
        compte = sandbox_account(
            imap_port=sandbox.port,
            tls_pins=self.pins(sandbox.port, self.pki.leaf("self_a")),
        )
        transport = self.connecte(compte)
        self.assertIn("INBOX", [f.name for f in transport.list_folders()])


class TestSmtpTls(TlsCase):
    def serveur(self, security, kind):
        return self.smtp_server(tls=security, leaf=self.pki.leaf(kind))

    def compte(self, srv, security, pins=None):
        return sandbox_account(
            smtp_port=srv.port,
            smtp_security=security,
            address=OWN,
            tls_pins=pins,
        )

    def envoie(self, compte):
        transport = smtp_send.connect(compte, PASSWORD)
        try:
            message = smtp_send.build_message(
                compte, [CAROLE], "Essai TLS", "Bonjour."
            )
            smtp_send.send(compte, message, transport)
        finally:
            transport.quit()

    def refus(self, compte):
        with self.assertRaises(tls.TlsCertificateError) as ctx:
            smtp_send.connect(compte, PASSWORD)
        return ctx.exception

    def test_a_valid_certificate_connects_and_logs_in(self):
        self.trusting()
        for security in SECURITES:
            with self.subTest(security=security):
                srv = self.serveur(security, "ok")
                self.envoie(self.compte(srv, security))
                self.assertEqual(len(srv.messages), 1)
                self.assertEqual(srv.messages[0].rcpt_tos, [CAROLE])
                self.assertTrue(srv.auth_attempts)

    def test_a_wrong_name_is_refused_with_its_fingerprint(self):
        self.trusting()
        for security in SECURITES:
            with self.subTest(security=security):
                srv = self.serveur(security, "wrong_name")
                exc = self.refus(self.compte(srv, security))
                self.assertEqual(exc.reason, "hostname")
                self.assertEqual(
                    exc.fingerprint, self.pki.leaf("wrong_name").fingerprint
                )

    def test_a_self_signed_certificate_is_refused_with_its_fingerprint(self):
        self.trusting()
        for security in SECURITES:
            with self.subTest(security=security):
                srv = self.serveur(security, "self_a")
                exc = self.refus(self.compte(srv, security))
                fp = self.pki.leaf("self_a").fingerprint
                self.assertEqual(exc.reason, "untrusted")
                self.assertEqual(exc.fingerprint, fp)
                self.assertIn(tls.format_fingerprint(fp), str(exc))
                self.assertNotIsInstance(exc, smtp_send.SmtpError)

    def test_an_expired_certificate_is_refused(self):
        self.trusting()
        for security in SECURITES:
            with self.subTest(security=security):
                srv = self.serveur(security, "expired")
                self.assertEqual(
                    self.refus(self.compte(srv, security)).reason, "validity"
                )

    def test_a_pinned_self_signed_certificate_connects(self):
        self.trusting()
        for security in SECURITES:
            with self.subTest(security=security):
                srv = self.serveur(security, "self_a")
                pins = self.pins(srv.port, self.pki.leaf("self_a"))
                self.envoie(self.compte(srv, security, pins))
                self.assertEqual(len(srv.messages), 1)

    def test_a_changed_certificate_is_refused_with_both_fingerprints(self):
        self.trusting()
        a, b = self.pki.leaf("self_a"), self.pki.leaf("self_b")
        for security in SECURITES:
            with self.subTest(security=security):
                srv = self.serveur(security, "self_a")
                srv.use_certificate(b)
                lu = tls.peer_certificate(
                    "smtp", "127.0.0.1", srv.port, security, 5
                )
                self.assertEqual(lu[0], b.der)
                exc = self.refus(
                    self.compte(srv, security, self.pins(srv.port, a))
                )
                self.assertEqual(exc.reason, "changed")
                self.assertEqual(exc.pinned, a.fingerprint)
                self.assertEqual(exc.fingerprint, b.fingerprint)

    def test_no_credential_reaches_the_server_on_a_refusal(self):
        self.trusting()
        a = self.pki.leaf("self_a")
        for security in SECURITES:
            for cas in ("verification", "changed"):
                with self.subTest(security=security, cas=cas):
                    srv = self.serveur(security, "self_b")
                    pins = self.pins(srv.port, a) if cas == "changed" else None
                    self.refus(self.compte(srv, security, pins))
                    self.assertEqual(srv.auth_attempts, [])
                    self.assertEqual(srv.messages, [])

    def test_the_production_trust_refuses_the_test_authority(self):
        for security in SECURITES:
            with self.subTest(security=security):
                srv = self.serveur(security, "ok")
                self.assertEqual(
                    self.refus(self.compte(srv, security)).reason, "untrusted"
                )

    def test_a_pin_for_another_endpoint_is_ignored(self):
        self.trusting()
        for security in SECURITES:
            with self.subTest(security=security):
                srv = self.serveur(security, "self_a")
                pins = self.pins(srv.port + 1, self.pki.leaf("self_a"))
                self.assertEqual(
                    self.refus(self.compte(srv, security, pins)).reason,
                    "untrusted",
                )

    def test_plain_security_ignores_pins(self):
        srv = self.smtp_server()
        compte = sandbox_account(
            smtp_port=srv.port,
            address=OWN,
            tls_pins=self.pins(srv.port, self.pki.leaf("self_a")),
        )
        self.envoie(compte)
        self.assertEqual(len(srv.messages), 1)


@requires_servers
class TestFrontLifecycle(MailSandboxCase):
    def test_the_front_closes_everything(self):
        pki = mail_tls.shared_pki()
        avant = set(LIVE_SERVERS)
        fils_avant = set(threading.enumerate())
        sandbox = self.imap_server()
        sandbox.folder("INBOX")
        front = TlsFront(sandbox.port, pki.leaf("ok")).start()
        try:
            with mail_tls.trusting(pki.ca_path):
                compte = sandbox_account(
                    imap_port=front.port, imap_security="ssl"
                )
                transport = imap_transport.connect(compte, PASSWORD)
                transport.list_folders()
        finally:
            front.stop()
        close_imap_client(transport)
        front.stop()
        self.assertTrue(port_is_closed(front.port))
        self.assertNotIn(front, LIVE_SERVERS)
        sandbox.stop()
        self.assertEqual(set(LIVE_SERVERS), avant)
        restants = [
            f
            for f in set(threading.enumerate()) - fils_avant
            if f.is_alive() and f.name != "mail-sandbox-reactor"
        ]
        self.assertEqual(restants, [])


if __name__ == "__main__":
    unittest.main()
