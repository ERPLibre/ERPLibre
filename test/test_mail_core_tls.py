#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La vérification TLS du noyau : empreintes, clés d'épingle, contextes,
raisons d'un refus, sonde, comparaison à l'épingle et `smtp.connect`.

Les poignées de main se font contre `mail_tls.MiniServer`, sur la boucle
locale, avec des certificats générés pour le test ; l'autorité de test
n'est acceptée que sous `mail_tls.trusting`.

N'importe que la bibliothèque standard, `erplibre_mail_core` et
`mail_tls` : la suite tourne aussi sous le Python d'Odoo.
"""

import ast
import hashlib
import imaplib
import os
import smtplib
import socket
import ssl
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

RACINE = Path(__file__).resolve().parent.parent
NOYAU = RACINE / "script" / "lib" / "erplibre_mail_core"
if str(NOYAU) not in sys.path:
    sys.path.insert(0, str(NOYAU))
if str(RACINE / "test") not in sys.path:
    sys.path.insert(0, str(RACINE / "test"))

import mail_tls  # noqa: E402
from erplibre_mail_core import i18n, smtp, tls  # noqa: E402
from erplibre_mail_core.catalog import CATALOG  # noqa: E402

TLS_PY = NOYAU / "erplibre_mail_core" / "tls.py"
FP_A = "ab" * 32
FP_B = "cd" * 32
PROTOCOLES = (("imap", "ssl"), ("imap", "starttls"))
TOUS = (
    ("imap", "ssl"),
    ("imap", "starttls"),
    ("smtp", "ssl"),
    ("smtp", "starttls"),
)


def _poignee(protocol, security, port, context=None):
    """Une poignée de main d'`imaplib` ou de `smtplib`, avec le contexte de
    production (`tls.context_for(None)`) ; la connexion est refermée."""
    contexte = context or tls.context_for(None)
    if protocol == "imap":
        if security == "ssl":
            client = imaplib.IMAP4_SSL(
                "127.0.0.1", port, ssl_context=contexte, timeout=5
            )
        else:
            client = imaplib.IMAP4("127.0.0.1", port, timeout=5)
            client.starttls(ssl_context=contexte)
        client.shutdown()
    else:
        if security == "ssl":
            client = smtplib.SMTP_SSL(
                "127.0.0.1", port, timeout=5, context=contexte
            )
        else:
            client = smtplib.SMTP("127.0.0.1", port, timeout=5)
            client.starttls(context=contexte)
        client.close()


class CryptoCase(unittest.TestCase):
    """Saute la classe si `cryptography` manque ; démarre les serveurs."""

    @classmethod
    def setUpClass(cls):
        mail_tls.require_crypto()
        cls.pki = mail_tls.shared_pki()

    def setUp(self):
        super().setUp()
        mail_tls.quiet_tls_log(self)

    def serveur(self, protocol, security, kind):
        srv = mail_tls.MiniServer(protocol, security, self.pki.leaf(kind))
        self.addCleanup(srv.stop)
        return srv.start()

    def refus(self, protocol, security, port):
        with self.assertRaises(ssl.SSLCertVerificationError) as ctx:
            _poignee(protocol, security, port)
        return ctx.exception


class LangCase(unittest.TestCase):
    def setUp(self):
        precedent = i18n.configure(default_lang=None, translator=None)
        self.addCleanup(lambda: i18n.configure(**precedent))


class TestFingerprint(LangCase):
    def test_fingerprint_is_the_sha256_of_the_der(self):
        der = b"\x30\x03\x02\x01\x01"
        self.assertEqual(tls.fingerprint(der), hashlib.sha256(der).hexdigest())

    def test_format_groups_bytes_in_uppercase_pairs(self):
        texte = tls.format_fingerprint("0a1b" + "ff" * 30)
        self.assertEqual(texte.split(":")[:3], ["0A", "1B", "FF"])
        self.assertEqual(len(texte), 95)

    def test_unreadable_fingerprint_is_spelled_out(self):
        self.assertEqual(
            tls.format_fingerprint(""),
            CATALOG["mail_tls_fingerprint_unreadable"]["fr"],
        )

    def test_parse_pin_accepts_prefix_colons_and_case(self):
        forme = ":".join(FP_A[i : i + 2].upper() for i in range(0, 64, 2))
        for valeur in (
            FP_A,
            "sha256:" + FP_A,
            "SHA256:" + forme,
            f" {forme} ",
        ):
            with self.subTest(valeur=valeur):
                self.assertEqual(tls.parse_pin(valeur), FP_A)

    def test_parse_pin_refuses_wrong_length_and_non_hex(self):
        for valeur in (FP_A[:-2], FP_A + "00", "zz" * 32, "", None, 12, []):
            with self.subTest(valeur=valeur):
                self.assertIsNone(tls.parse_pin(valeur))

    def test_pin_value_round_trips(self):
        self.assertEqual(tls.pin_value(FP_A.upper()), "sha256:" + FP_A)
        self.assertEqual(tls.parse_pin(tls.pin_value(FP_A)), FP_A)
        with self.assertRaises(ValueError):
            tls.pin_value("pas une empreinte")


class TestPinKey(unittest.TestCase):
    def test_host_is_lowercased_and_trailing_dot_dropped(self):
        self.assertEqual(
            tls.pin_key(" Serveur.Example.ORG. ", 993),
            "serveur.example.org:993",
        )

    def test_ipv6_host_is_bracketed(self):
        self.assertEqual(tls.pin_key("::1", 993), "[::1]:993")
        self.assertEqual(tls.pin_key("[::1]", 993), "[::1]:993")

    def test_split_pin_key_round_trips(self):
        for hote, port in (("serveur.example.org", 993), ("::1", 465)):
            with self.subTest(hote=hote):
                cle = tls.pin_key(hote, port)
                self.assertEqual(tls.split_pin_key(cle), (hote, port))
        self.assertEqual(
            tls.split_pin_key("SERVEUR.example.org:587"),
            ("serveur.example.org", 587),
        )

    def test_split_pin_key_refuses_garbage_and_bad_ports(self):
        for cle in (
            "",
            "serveur",
            ":993",
            "serveur:0",
            "serveur:65536",
            "serveur:abc",
            "::1:993",
            "[::1]993",
            None,
            993,
        ):
            with self.subTest(cle=cle):
                self.assertIsNone(tls.split_pin_key(cle))

    def test_account_pin_reads_only_its_endpoint(self):
        pins = {"serveur.example.org:993": "sha256:" + FP_A}
        self.assertEqual(
            tls.account_pin(pins, "SERVEUR.example.org", 993), FP_A
        )
        self.assertIsNone(tls.account_pin(pins, "serveur.example.org", 465))
        self.assertIsNone(tls.account_pin(pins, "autre.example.net", 993))

    def test_account_pin_without_pins_is_none(self):
        for pins in (None, {}, [], "x"):
            with self.subTest(pins=pins):
                self.assertIsNone(tls.account_pin(pins, "h", 993))


class TestContexts(unittest.TestCase):
    def test_verified_context_requires_certificate_and_name(self):
        contexte = tls.verified_context()
        self.assertEqual(contexte.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(contexte.check_hostname)

    def test_verified_context_refuses_below_tls12(self):
        for contexte in (tls.verified_context(), tls.pinning_context()):
            with self.subTest(contexte=contexte):
                self.assertNotEqual(
                    contexte.minimum_version,
                    ssl.TLSVersion.MINIMUM_SUPPORTED,
                )
                self.assertGreaterEqual(
                    contexte.minimum_version, ssl.TLSVersion.TLSv1_2
                )

    def test_pinning_context_checks_neither_name_nor_chain(self):
        contexte = tls.pinning_context()
        self.assertEqual(contexte.verify_mode, ssl.CERT_NONE)
        self.assertFalse(contexte.check_hostname)

    def test_context_for_picks_by_pin(self):
        self.assertEqual(tls.context_for(None).verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(tls.context_for(None).check_hostname)
        self.assertEqual(tls.context_for(FP_A).verify_mode, ssl.CERT_NONE)

    def test_chain_context_checks_the_chain_without_the_name(self):
        contexte = tls.chain_context()
        self.assertEqual(contexte.verify_mode, ssl.CERT_REQUIRED)
        self.assertFalse(contexte.check_hostname)


def _verif(code):
    exc = ssl.SSLCertVerificationError(1, "refus")
    exc.verify_code = code
    exc.verify_message = "message"
    return exc


class TestReasons(CryptoCase):
    def test_hostname_codes(self):
        for code in (62, 63, 64):
            with self.subTest(code=code):
                self.assertEqual(tls.reason_of(_verif(code)), "hostname")

    def test_validity_codes(self):
        for code in (9, 10):
            with self.subTest(code=code):
                self.assertEqual(tls.reason_of(_verif(code)), "validity")

    def test_strict_conformance_codes_are_nonconforming(self):
        for code in (80, 85, 89, 94):
            with self.subTest(code=code):
                self.assertEqual(tls.reason_of(_verif(code)), "nonconforming")
        for code in (78, 95):
            with self.subTest(code=code):
                self.assertEqual(tls.reason_of(_verif(code)), "untrusted")

    def test_an_invalid_ca_is_untrusted(self):
        # 79 se lève aussi hors du mode strict : une chaîne dont un
        # émetteur n'est pas une autorité n'est pas un défaut de forme.
        self.assertEqual(tls.reason_of(_verif(79)), "untrusted")

    def test_any_other_code_is_untrusted(self):
        for code in (18, 19, 20, 21, 0, None):
            with self.subTest(code=code):
                self.assertEqual(tls.reason_of(_verif(code)), "untrusted")
        self.assertEqual(tls.reason_of(OSError("x")), "untrusted")

    def test_a_leaf_without_aki_is_refused_as_nonconforming(self):
        if not tls.verified_context().verify_flags & ssl.VERIFY_X509_STRICT:
            self.skipTest("ce Python ne pose pas VERIFY_X509_STRICT")
        for protocol, security in TOUS:
            with self.subTest(protocol=protocol, security=security):
                srv = self.serveur(protocol, security, "no_aki")
                with mail_tls.trusting(self.pki.ca_path):
                    exc = self.refus(protocol, security, srv.port)
                self.assertEqual(tls.reason_of(exc), "nonconforming")

    def test_a_chain_issued_by_a_non_ca_leaf_is_refused_as_untrusted(self):
        for protocol, security in TOUS:
            with self.subTest(protocol=protocol, security=security):
                srv = self.serveur(protocol, security, "non_ca_issuer")
                with mail_tls.trusting(self.pki.ca_path):
                    exc = self.refus(protocol, security, srv.port)
                self.assertEqual(exc.verify_code, 79)
                self.assertEqual(tls.reason_of(exc), "untrusted")

    def test_a_non_ca_issuer_is_refused_without_the_strict_flag(self):
        # Le Python d'Odoo ne pose pas VERIFY_X509_STRICT : le code 79 y
        # tombe aussi, ce qui le sépare des contrôles de conformité.
        srv = self.serveur("imap", "ssl", "non_ca_issuer")
        contexte = ssl.create_default_context(cafile=self.pki.ca_path)
        contexte.verify_flags &= ~ssl.VERIFY_X509_STRICT
        with self.assertRaises(ssl.SSLCertVerificationError) as ctx:
            imaplib.IMAP4_SSL(
                "127.0.0.1", srv.port, ssl_context=contexte, timeout=10
            )
        self.assertEqual(ctx.exception.verify_code, 79)
        self.assertEqual(tls.reason_of(ctx.exception), "untrusted")


class TestContextSource(unittest.TestCase):
    def _fonctions(self):
        arbre = ast.parse(TLS_PY.read_text(encoding="utf-8"))
        return arbre, {
            n.name: n for n in arbre.body if isinstance(n, ast.FunctionDef)
        }

    def test_context_for_calls_verified_context_without_arguments(self):
        arbre, fonctions = self._fonctions()
        appels = [
            n
            for n in ast.walk(fonctions["context_for"])
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "verified_context"
        ]
        self.assertTrue(appels)
        for appel in appels:
            self.assertEqual(appel.args, [])
            self.assertEqual(appel.keywords, [])
        dedans = set(map(id, ast.walk(fonctions["verified_context"])))
        for noeud in ast.walk(arbre):
            if id(noeud) in dedans:
                continue
            nom = (
                getattr(noeud, "id", None)
                or getattr(noeud, "arg", None)
                or (noeud.value if isinstance(noeud, ast.Constant) else None)
            )
            self.assertNotEqual(nom, "cafile", ast.dump(noeud))

    def test_context_for_calls_the_spy_with_nothing(self):
        espion = mock.Mock(return_value="contexte")
        with mock.patch.object(tls, "verified_context", espion):
            self.assertEqual(tls.context_for(None), "contexte")
        espion.assert_called_once_with()


class TestHandshakes(CryptoCase):
    def test_a_valid_certificate_is_accepted(self):
        for protocol, security in TOUS:
            with self.subTest(protocol=protocol, security=security):
                srv = self.serveur(protocol, security, "ok")
                with mail_tls.trusting(self.pki.ca_path):
                    _poignee(protocol, security, srv.port)

    def test_the_production_context_refuses_the_test_authority(self):
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("SSL_CERT_FILE", "SSL_CERT_DIR")
        }
        with mock.patch.dict(os.environ, env, clear=True):
            for protocol, security in TOUS:
                with self.subTest(protocol=protocol, security=security):
                    srv = self.serveur(protocol, security, "ok")
                    exc = self.refus(protocol, security, srv.port)
                    self.assertEqual(tls.reason_of(exc), "untrusted")

    def test_a_wrong_name_is_refused_as_hostname(self):
        for protocol, security in TOUS:
            with self.subTest(protocol=protocol, security=security):
                srv = self.serveur(protocol, security, "wrong_name")
                with mail_tls.trusting(self.pki.ca_path):
                    exc = self.refus(protocol, security, srv.port)
                self.assertEqual(tls.reason_of(exc), "hostname")

    def test_a_self_signed_certificate_is_refused_as_untrusted(self):
        for protocol, security in TOUS:
            with self.subTest(protocol=protocol, security=security):
                srv = self.serveur(protocol, security, "self_a")
                with mail_tls.trusting(self.pki.ca_path):
                    exc = self.refus(protocol, security, srv.port)
                self.assertEqual(tls.reason_of(exc), "untrusted")

    def test_an_expired_certificate_is_refused_as_validity(self):
        for protocol, security in TOUS:
            with self.subTest(protocol=protocol, security=security):
                srv = self.serveur(protocol, security, "expired")
                with mail_tls.trusting(self.pki.ca_path):
                    exc = self.refus(protocol, security, srv.port)
                self.assertEqual(tls.reason_of(exc), "validity")


class TestProbe(CryptoCase):
    def test_peer_certificate_reads_the_der_for_each_protocol_and_security(
        self,
    ):
        leaf = self.pki.leaf("self_a")
        for protocol, security in TOUS:
            with self.subTest(protocol=protocol, security=security):
                srv = self.serveur(protocol, security, "self_a")
                lu = tls.peer_certificate(
                    protocol, "127.0.0.1", srv.port, security, 5
                )
                self.assertEqual(lu, (leaf.der, ()))

    def test_the_chain_probe_reads_the_certificate_names(self):
        srv = self.serveur("imap", "ssl", "wrong_name")
        with mail_tls.trusting(self.pki.ca_path):
            lu = tls.peer_certificate(
                "imap",
                "127.0.0.1",
                srv.port,
                "ssl",
                5,
                context=tls.chain_context(),
            )
        self.assertEqual(lu[1], ("autre.example.net",))
        self.assertEqual(lu[0], self.pki.leaf("wrong_name").der)

    def test_the_probe_sends_no_credentials(self):
        permis = {"CAPABILITY", "STARTTLS", "EHLO", "QUIT", "LOGOUT"}
        for protocol, security in TOUS:
            with self.subTest(protocol=protocol, security=security):
                srv = self.serveur(protocol, security, "self_a")
                self.assertIsNotNone(
                    tls.peer_certificate(
                        protocol, "127.0.0.1", srv.port, security, 5
                    )
                )
                srv.stop()
                self.assertLessEqual(set(srv.commands), permis)

    def test_a_failing_probe_returns_none(self):
        with socket.socket() as libre:
            libre.bind(("127.0.0.1", 0))
            port = libre.getsockname()[1]
        for protocol, security in TOUS:
            with self.subTest(protocol=protocol, security=security):
                self.assertIsNone(
                    tls.peer_certificate(
                        protocol, "127.0.0.1", port, security, 2
                    )
                )

    def test_an_unknown_protocol_or_plain_security_returns_none(self):
        self.assertIsNone(tls.peer_certificate("pop", "h", 1, "ssl", 1))
        self.assertIsNone(tls.peer_certificate("imap", "h", 1, "none", 1))


class TestCertificateError(LangCase, CryptoCase):
    def setUp(self):
        LangCase.setUp(self)
        mail_tls.quiet_tls_log(self)

    def test_the_message_names_endpoint_protocol_reason_and_fingerprint(
        self,
    ):
        exc = tls.TlsCertificateError(
            protocol="imap",
            host="Serveur.example.org",
            port=993,
            reason="untrusted",
            fingerprint=FP_A,
        )
        texte = str(exc)
        self.assertNotIn("\n", texte)
        self.assertIn("serveur.example.org:993 (IMAP)", texte)
        self.assertIn(CATALOG["mail_tls_refused"]["fr"], texte)
        self.assertIn(CATALOG["mail_tls_reason_untrusted"]["fr"], texte)
        self.assertIn(tls.format_fingerprint(FP_A), texte)
        self.assertEqual(exc.endpoint, "serveur.example.org:993")

    def test_the_changed_message_names_both_fingerprints(self):
        exc = tls.TlsCertificateError(
            protocol="smtp",
            host="serveur.example.org",
            port=465,
            reason="changed",
            fingerprint=FP_B,
            pinned=FP_A,
        )
        texte = str(exc)
        self.assertIn(CATALOG["mail_tls_changed"]["fr"], texte)
        self.assertIn("(SMTP)", texte)
        self.assertIn(tls.format_fingerprint(FP_A), texte)
        self.assertIn(tls.format_fingerprint(FP_B), texte)
        self.assertLess(
            texte.index(tls.format_fingerprint(FP_A)),
            texte.index(tls.format_fingerprint(FP_B)),
        )

    def test_an_unreadable_fingerprint_is_not_pinnable(self):
        exc = tls.TlsCertificateError(
            protocol="imap", host="h", port=993, reason="untrusted"
        )
        self.assertFalse(exc.pinnable)
        self.assertIn(
            CATALOG["mail_tls_fingerprint_unreadable"]["fr"], str(exc)
        )
        self.assertTrue(
            tls.TlsCertificateError(
                protocol="imap",
                host="h",
                port=993,
                reason="untrusted",
                fingerprint=FP_A,
            ).pinnable
        )

    def test_the_message_keeps_its_data_without_the_catalog_keys(self):
        absentes = {
            k: v for k, v in CATALOG.items() if not k.startswith("mail_tls_")
        }
        i18n.configure(translator=lambda key, lang: None)
        with mock.patch.dict(CATALOG, absentes, clear=True):
            for raison, epingle in (("untrusted", None), ("changed", FP_A)):
                with self.subTest(raison=raison):
                    texte = str(
                        tls.TlsCertificateError(
                            protocol="smtp",
                            host="serveur.example.org",
                            port=587,
                            reason=raison,
                            fingerprint=FP_B,
                            pinned=epingle,
                        )
                    )
                    self.assertIn("serveur.example.org:587", texte)
                    self.assertIn("SMTP", texte)
                    self.assertIn(":".join(["CD"] * 32), texte)
                    if epingle:
                        self.assertIn(":".join(["AB"] * 32), texte)

    def test_certificate_error_probes_and_fills_the_fingerprint(self):
        for protocol, security in TOUS:
            with self.subTest(protocol=protocol, security=security):
                srv = self.serveur(protocol, security, "self_a")
                with mail_tls.trusting(self.pki.ca_path):
                    origine = self.refus(protocol, security, srv.port)
                    with self.assertLogs("erplibre_mail_core.tls", "WARNING"):
                        exc = tls.certificate_error(
                            origine,
                            protocol=protocol,
                            host="127.0.0.1",
                            port=srv.port,
                            security=security,
                            timeout=5,
                        )
                self.assertEqual(
                    exc.fingerprint, self.pki.leaf("self_a").fingerprint
                )
                self.assertEqual(exc.reason, "untrusted")
                self.assertEqual(exc.names, ())
                self.assertTrue(exc.pinnable)
                self.assertTrue(exc.detail)

    def test_a_hostname_refusal_carries_the_certificate_names(self):
        srv = self.serveur("smtp", "starttls", "wrong_name")
        with mail_tls.trusting(self.pki.ca_path):
            origine = self.refus("smtp", "starttls", srv.port)
            exc = tls.certificate_error(
                origine,
                protocol="smtp",
                host="127.0.0.1",
                port=srv.port,
                security="starttls",
                timeout=5,
            )
        self.assertEqual(exc.reason, "hostname")
        self.assertEqual(exc.names, ("autre.example.net",))
        self.assertEqual(
            exc.fingerprint, self.pki.leaf("wrong_name").fingerprint
        )

    def test_it_is_neither_an_oserror_nor_a_protocol_error(self):
        from erplibre_mail_core.imap import ImapAuthError, ImapError

        self.assertFalse(issubclass(tls.TlsCertificateError, OSError))
        for autre in (
            ImapError,
            ImapAuthError,
            smtp.SmtpError,
            smtp.SmtpAuthError,
            ssl.SSLError,
        ):
            with self.subTest(autre=autre.__name__):
                self.assertFalse(issubclass(tls.TlsCertificateError, autre))

    def test_it_is_explicitly_transient(self):
        exc = tls.TlsCertificateError(
            protocol="smtp", host="h", port=1, reason="untrusted"
        )
        self.assertIs(exc.permanent, False)
        self.assertIs(tls.TlsCertificateError.permanent, False)


class _Sock:
    def __init__(self, der):
        self.der = der

    def getpeercert(self, binary_form=False):
        return self.der if binary_form else {}


class TestCheckPin(LangCase):
    def setUp(self):
        super().setUp()
        mail_tls.quiet_tls_log(self)

    def test_a_matching_pin_passes(self):
        der = b"certificat"
        fp = hashlib.sha256(der).hexdigest()
        tls.check_pin(
            _Sock(der),
            "sha256:" + fp.upper(),
            protocol="imap",
            host="h",
            port=993,
        )

    def test_another_certificate_raises_changed_with_both(self):
        der = b"autre"
        with self.assertRaises(tls.TlsCertificateError) as ctx:
            tls.check_pin(
                _Sock(der), FP_A, protocol="smtp", host="h", port=465
            )
        exc = ctx.exception
        self.assertEqual(exc.reason, "changed")
        self.assertEqual(exc.pinned, FP_A)
        self.assertEqual(exc.fingerprint, hashlib.sha256(der).hexdigest())

    def test_a_socket_without_certificate_raises_changed_unreadable(self):
        for sock in (_Sock(None), object()):
            with self.subTest(sock=sock):
                with self.assertRaises(tls.TlsCertificateError) as ctx:
                    tls.check_pin(
                        sock, FP_A, protocol="imap", host="h", port=1
                    )
                self.assertEqual(ctx.exception.reason, "changed")
                self.assertEqual(ctx.exception.fingerprint, "")
                self.assertFalse(ctx.exception.pinnable)

    def test_an_unreadable_pin_raises_changed(self):
        der = b"certificat"
        with self.assertRaises(tls.TlsCertificateError) as ctx:
            tls.check_pin(
                _Sock(der), "illisible", protocol="imap", host="h", port=1
            )
        self.assertEqual(ctx.exception.reason, "changed")
        self.assertIsNone(ctx.exception.pinned)

    def test_a_changed_certificate_is_logged(self):
        der = b"autre"
        with self.assertLogs("erplibre_mail_core.tls", "WARNING") as journal:
            with self.assertRaises(tls.TlsCertificateError):
                tls.check_pin(
                    _Sock(der),
                    FP_A,
                    protocol="imap",
                    host="serveur.example.org",
                    port=993,
                )
        ligne = "\n".join(journal.output)
        self.assertIn("serveur.example.org:993", ligne)
        self.assertIn("changed", ligne)
        self.assertIn(FP_A, ligne)
        self.assertIn(hashlib.sha256(der).hexdigest(), ligne)


def _compte(port, security, *, pins=None, attribut=True):
    compte = SimpleNamespace(
        smtp=SimpleNamespace(
            host="127.0.0.1", port=port, security=security, user="moi"
        ),
        auth="login",
    )
    if attribut:
        compte.tls_pins = pins or {}
    return compte


class TestSmtpConnect(CryptoCase):
    def connecte(self, compte):
        transport = smtp.connect(compte, "secret")
        transport.quit()

    def test_valid_certificate_connects_and_authenticates(self):
        for security in ("ssl", "starttls"):
            with self.subTest(security=security):
                srv = self.serveur("smtp", security, "ok")
                with mail_tls.trusting(self.pki.ca_path):
                    self.connecte(_compte(srv.port, security))
                srv.stop()
                self.assertIn("AUTH", srv.commands)

    def test_self_signed_is_refused_with_its_fingerprint(self):
        for security in ("ssl", "starttls"):
            with self.subTest(security=security):
                srv = self.serveur("smtp", security, "self_a")
                with mail_tls.trusting(self.pki.ca_path):
                    with self.assertRaises(tls.TlsCertificateError) as ctx:
                        smtp.connect(_compte(srv.port, security), "secret")
                self.assertNotIsInstance(ctx.exception, smtp.SmtpError)
                self.assertEqual(ctx.exception.reason, "untrusted")
                self.assertEqual(
                    ctx.exception.fingerprint,
                    self.pki.leaf("self_a").fingerprint,
                )
                srv.stop()
                self.assertNotIn("AUTH", srv.commands)

    def test_wrong_name_is_refused_as_hostname(self):
        srv = self.serveur("smtp", "ssl", "wrong_name")
        with mail_tls.trusting(self.pki.ca_path):
            with self.assertRaises(tls.TlsCertificateError) as ctx:
                smtp.connect(_compte(srv.port, "ssl"), "secret")
        self.assertEqual(ctx.exception.reason, "hostname")

    def test_a_pinned_self_signed_certificate_connects(self):
        leaf = self.pki.leaf("self_a")
        for security in ("ssl", "starttls"):
            with self.subTest(security=security):
                srv = self.serveur("smtp", security, "self_a")
                pins = {
                    tls.pin_key("127.0.0.1", srv.port): tls.pin_value(
                        leaf.fingerprint
                    )
                }
                with mail_tls.trusting(self.pki.ca_path):
                    self.connecte(_compte(srv.port, security, pins=pins))

    def test_a_changed_certificate_is_refused_before_auth(self):
        for security in ("ssl", "starttls"):
            with self.subTest(security=security):
                srv = self.serveur("smtp", security, "self_b")
                pins = {
                    tls.pin_key("127.0.0.1", srv.port): tls.pin_value(
                        self.pki.leaf("self_a").fingerprint
                    )
                }
                with self.assertRaises(tls.TlsCertificateError) as ctx:
                    smtp.connect(_compte(srv.port, security, pins=pins), "s")
                self.assertEqual(ctx.exception.reason, "changed")
                self.assertEqual(
                    ctx.exception.fingerprint,
                    self.pki.leaf("self_b").fingerprint,
                )
                srv.stop()
                self.assertNotIn("AUTH", srv.commands)

    def test_an_account_without_tls_pins_is_verified(self):
        srv = self.serveur("smtp", "ssl", "self_a")
        compte = _compte(srv.port, "ssl", attribut=False)
        self.assertFalse(hasattr(compte, "tls_pins"))
        with self.assertRaises(tls.TlsCertificateError):
            smtp.connect(compte, "secret")

    def test_plain_security_ignores_pins(self):
        compte = _compte(25, "none", pins={"127.0.0.1:25": "sha256:" + FP_A})
        client = mock.MagicMock()
        with mock.patch("smtplib.SMTP", return_value=client) as ctor:
            smtp.connect(compte, "secret")
        ctor.assert_called_once_with("127.0.0.1", 25, timeout=30)
        client.starttls.assert_not_called()
        client.login.assert_called_once_with("moi", "secret")


class TestProductionSource(unittest.TestCase):
    def test_cafile_is_passed_nowhere_in_production(self):
        for chemin in sorted((RACINE / "script").rglob("*.py")):
            if chemin == TLS_PY:
                continue
            with self.subTest(fichier=str(chemin.relative_to(RACINE))):
                self.assertNotIn(
                    "cafile=",
                    chemin.read_text(encoding="utf-8", errors="replace"),
                )


if __name__ == "__main__":
    unittest.main()
