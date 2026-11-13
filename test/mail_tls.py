#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Autorité, certificats et petits serveurs TLS pour les tests.

Tout se génère dans un dossier temporaire, retiré à la fin du processus :
une autorité de test, des certificats de serveur signés par elle ou
auto-signés, conformes aux contrôles stricts de X.509 (`VERIFY_X509_STRICT`,
actif par défaut à partir de Python 3.13). L'autorité n'est acceptée que
par `trusting`, qui remplace `erplibre_mail_core.tls.verified_context` le
temps d'un test : le code de production ne la voit jamais.

`MiniServer` parle juste assez d'IMAP ou de SMTP pour qu'`imaplib` et
`smtplib` mènent une poignée de main TLS, directe ou après `STARTTLS`, puis
s'authentifient ; il note chaque verbe reçu.

`cryptography` s'importe à l'usage : un module qui importe celui-ci sans
générer de certificat n'en dépend pas. N'importe rien du client courriel.
"""

from __future__ import annotations

import atexit
import datetime
import functools
import ipaddress
import shutil
import socket
import ssl
import tempfile
import threading
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

LEAF_KINDS = (
    "ok",
    "wrong_name",
    "expired",
    "self_a",
    "self_b",
    "no_aki",
    "non_ca_issuer",
)
CA_NAME = "Autorite de test"
SELF_NAME = "serveur.example.org"
WRONG_NAME = "autre.example.net"
# Délai de chaque lecture d'une connexion de `MiniServer`, en secondes.
SERVER_TIMEOUT = 10
# Période à laquelle le fil d'écoute de `MiniServer` relit son état.
ACCEPT_POLL = 0.05


def crypto_available() -> bool:
    """Vrai si `cryptography` s'importe."""
    try:
        import cryptography  # noqa: F401
    except ImportError:
        return False
    return True


def require_crypto(testcase=None) -> None:
    """Saute le test (ou la classe) si `cryptography` manque."""
    if not crypto_available():
        raise unittest.SkipTest(
            "cryptography absent : aucun certificat de test à générer"
        )


@dataclass(frozen=True)
class Leaf:
    """Un certificat de serveur et sa clé, sur disque."""

    cert_path: str
    key_path: str
    der: bytes
    # Calculée par `cryptography`, indépendamment du code testé.
    fingerprint: str


class TestPki:
    """Autorité et certificats de test, dans `directory`.

    Chaque sorte de feuille se génère une fois, à la première demande.
    """

    __test__ = False

    def __init__(self, directory: str):
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID

        self.directory = Path(directory)
        self._leaves: dict[str, Leaf] = {}
        self._lock = threading.Lock()
        self._ca_key = ec.generate_private_key(ec.SECP256R1())
        maintenant = datetime.datetime.now(datetime.timezone.utc)
        nom = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, CA_NAME)])
        public = self._ca_key.public_key()
        self._ca_cert = (
            x509.CertificateBuilder()
            .subject_name(nom)
            .issuer_name(nom)
            .public_key(public)
            .serial_number(x509.random_serial_number())
            .not_valid_before(maintenant - datetime.timedelta(days=1))
            .not_valid_after(maintenant + datetime.timedelta(days=60))
            .add_extension(
                x509.BasicConstraints(ca=True, path_length=None),
                critical=True,
            )
            .add_extension(
                x509.KeyUsage(
                    digital_signature=False,
                    content_commitment=False,
                    key_encipherment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    key_cert_sign=True,
                    crl_sign=True,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .add_extension(
                x509.SubjectKeyIdentifier.from_public_key(public),
                critical=False,
            )
            .sign(self._ca_key, hashes.SHA256())
        )
        self.ca_path = str(self.directory / "autorite.pem")
        Path(self.ca_path).write_bytes(
            self._ca_cert.public_bytes(serialization.Encoding.PEM)
        )

    def leaf(self, kind: str) -> Leaf:
        """La feuille `kind` (voir `LEAF_KINDS`) :

        - `ok` : SAN IP:127.0.0.1 et DNS:localhost, signée par l'autorité ;
        - `wrong_name` : SAN DNS:autre.example.net seulement, signée ;
        - `expired` : comme `ok`, période de validité passée ;
        - `self_a`, `self_b` : auto-signées, SAN IP:127.0.0.1, clés
          distinctes ;
        - `no_aki` : comme `ok`, sans AuthorityKeyIdentifier, refusée par
          les contrôles stricts ;
        - `non_ca_issuer` : SAN IP:127.0.0.1, signée par la feuille
          légitime d'un autre domaine (`CA:FALSE`, émise par l'autorité),
          que le serveur présente à sa suite : la chaîne d'une interception.
        """
        if kind not in LEAF_KINDS:
            raise ValueError(kind)
        with self._lock:
            if kind not in self._leaves:
                self._leaves[kind] = self._make(kind)
            return self._leaves[kind]

    def _make(self, kind: str) -> Leaf:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

        cle = ec.generate_private_key(ec.SECP256R1())
        public = cle.public_key()
        maintenant = datetime.datetime.now(datetime.timezone.utc)
        if kind == "non_ca_issuer":
            return self._make_non_ca_issued(cle, maintenant)
        if kind == "expired":
            debut = maintenant - datetime.timedelta(days=60)
            fin = maintenant - datetime.timedelta(days=30)
        else:
            debut = maintenant - datetime.timedelta(days=1)
            fin = maintenant + datetime.timedelta(days=30)
        auto = kind in ("self_a", "self_b")
        if kind == "wrong_name":
            noms = [x509.DNSName(WRONG_NAME)]
            cn = WRONG_NAME
        elif auto:
            noms = [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            cn = SELF_NAME
        else:
            noms = [
                x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                x509.DNSName("localhost"),
            ]
            cn = "localhost"
        sujet = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
        ski = x509.SubjectKeyIdentifier.from_public_key(public)
        constructeur = (
            x509.CertificateBuilder()
            .subject_name(sujet)
            .issuer_name(sujet if auto else self._ca_cert.subject)
            .public_key(public)
            .serial_number(x509.random_serial_number())
            .not_valid_before(debut)
            .not_valid_after(fin)
            .add_extension(
                x509.BasicConstraints(ca=False, path_length=None),
                critical=True,
            )
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    content_commitment=False,
                    key_encipherment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    key_cert_sign=False,
                    crl_sign=False,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .add_extension(
                x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
                critical=False,
            )
            .add_extension(x509.SubjectAlternativeName(noms), critical=False)
            .add_extension(ski, critical=False)
        )
        if auto:
            constructeur = constructeur.add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_subject_key_identifier(
                    ski
                ),
                critical=False,
            )
            signataire = cle
        else:
            if kind != "no_aki":
                constructeur = constructeur.add_extension(
                    x509.AuthorityKeyIdentifier.from_issuer_public_key(
                        self._ca_key.public_key()
                    ),
                    critical=False,
                )
            signataire = self._ca_key
        cert = constructeur.sign(signataire, hashes.SHA256())
        return self._write(kind, cert, cle)

    @staticmethod
    def _server_extensions(constructeur):
        """Contraintes de base `CA:FALSE`, usages d'une feuille de serveur
        (`keyCertSign` absent), sans les noms ni les identifiants."""
        from cryptography import x509
        from cryptography.x509.oid import ExtendedKeyUsageOID

        return (
            constructeur.add_extension(
                x509.BasicConstraints(ca=False, path_length=None),
                critical=True,
            )
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    content_commitment=False,
                    key_encipherment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    key_cert_sign=False,
                    crl_sign=False,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .add_extension(
                x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
                critical=False,
            )
        )

    def _make_non_ca_issued(self, cle, maintenant) -> Leaf:
        """La feuille `non_ca_issuer` : le relais est une feuille ordinaire
        de `WRONG_NAME` émise par l'autorité ; il signe la feuille
        présentée, et le fichier de certificat porte les deux, feuille
        d'abord."""
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID

        debut = maintenant - datetime.timedelta(days=1)
        fin = maintenant + datetime.timedelta(days=30)
        cle_relais = ec.generate_private_key(ec.SECP256R1())
        nom_relais = x509.Name(
            [x509.NameAttribute(NameOID.COMMON_NAME, WRONG_NAME)]
        )
        relais = (
            self._server_extensions(
                x509.CertificateBuilder()
                .subject_name(nom_relais)
                .issuer_name(self._ca_cert.subject)
                .public_key(cle_relais.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(debut)
                .not_valid_after(fin)
            )
            .add_extension(
                x509.SubjectAlternativeName([x509.DNSName(WRONG_NAME)]),
                critical=False,
            )
            .add_extension(
                x509.SubjectKeyIdentifier.from_public_key(
                    cle_relais.public_key()
                ),
                critical=False,
            )
            .add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(
                    self._ca_key.public_key()
                ),
                critical=False,
            )
            .sign(self._ca_key, hashes.SHA256())
        )
        feuille = (
            self._server_extensions(
                x509.CertificateBuilder()
                .subject_name(
                    x509.Name(
                        [x509.NameAttribute(NameOID.COMMON_NAME, SELF_NAME)]
                    )
                )
                .issuer_name(nom_relais)
                .public_key(cle.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(debut)
                .not_valid_after(fin)
            )
            .add_extension(
                x509.SubjectAlternativeName(
                    [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
                ),
                critical=False,
            )
            .add_extension(
                x509.SubjectKeyIdentifier.from_public_key(cle.public_key()),
                critical=False,
            )
            .add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(
                    cle_relais.public_key()
                ),
                critical=False,
            )
            .sign(cle_relais, hashes.SHA256())
        )
        return self._write(
            "non_ca_issuer",
            feuille,
            cle,
            suite=relais.public_bytes(serialization.Encoding.PEM),
        )

    def _write(self, kind: str, cert, cle, suite: bytes = b"") -> Leaf:
        """Écrit le certificat `kind` (suivi de `suite`, les certificats
        que le serveur présente après lui) et sa clé en 0600 ; rend la
        feuille."""
        from cryptography.hazmat.primitives import hashes, serialization

        cert_path = self.directory / f"{kind}.pem"
        key_path = self.directory / f"{kind}.key"
        cert_path.write_bytes(
            cert.public_bytes(serialization.Encoding.PEM) + suite
        )
        key_path.write_bytes(
            cle.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        key_path.chmod(0o600)
        return Leaf(
            cert_path=str(cert_path),
            key_path=str(key_path),
            der=cert.public_bytes(serialization.Encoding.DER),
            fingerprint=cert.fingerprint(hashes.SHA256()).hex(),
        )


_shared: TestPki | None = None
_shared_lock = threading.Lock()


def shared_pki() -> TestPki:
    """Une autorité par processus, dans un dossier temporaire retiré à la
    sortie."""
    global _shared
    require_crypto()
    with _shared_lock:
        if _shared is None:
            dossier = tempfile.mkdtemp(prefix="mail-tls-")
            atexit.register(shutil.rmtree, dossier, True)
            _shared = TestPki(dossier)
        return _shared


def quiet_tls_log(testcase: unittest.TestCase) -> None:
    """Retient, le temps du test, les lignes du journal des refus de
    certificat : sans gestionnaire, Python les écrirait sur la sortie
    d'erreur. `assertLogs` les voit toujours."""
    import logging

    logger = logging.getLogger("erplibre_mail_core.tls")
    retenue = logging.NullHandler()
    logger.addHandler(retenue)
    testcase.addCleanup(logger.removeHandler, retenue)


def server_context(leaf: Leaf) -> ssl.SSLContext:
    """Le contexte d'un serveur qui présente `leaf`."""
    contexte = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    contexte.load_cert_chain(leaf.cert_path, leaf.key_path)
    return contexte


def trusting(ca_path: str):
    """`mock.patch` qui fait accepter l'autorité `ca_path` par le contexte
    vérifiant du noyau, et elle seule, le temps d'un bloc ou d'un test."""
    from erplibre_mail_core import tls

    return mock.patch(
        "erplibre_mail_core.tls.verified_context",
        functools.partial(tls.verified_context, cafile=ca_path),
    )


class _Lines:
    """Lecture ligne à ligne d'une socket, sans tampon caché : après
    `STARTTLS`, la socket se remplace et rien n'y reste en suspens."""

    def __init__(self, sock):
        self.sock = sock
        self.buffer = b""

    def readline(self) -> bytes:
        while b"\n" not in self.buffer:
            morceau = self.sock.recv(4096)
            if not morceau:
                raise ConnectionError("fermée")
            self.buffer += morceau
        ligne, _, self.buffer = self.buffer.partition(b"\n")
        return ligne.rstrip(b"\r")


class MiniServer:
    """Serveur IMAP ou SMTP minimal, TLS direct (`ssl`) ou `starttls`.

    Un fil par connexion. `commands` porte le verbe, en majuscules, de
    chaque ligne reçue, avant et après TLS. Une poignée de main refusée par
    le client ferme la connexion sans lever dans le fil.

    `starttls_preamble` part EN CLAIR, dans un envoi à part, AVANT la
    réponse `OK` de STARTTLS, et `starttls_trailer` dans le même envoi que
    cette réponse, après elle (IMAP seulement) : ce qu'un tiers sur le
    chemin glisserait avant la poignée de main. LIST rend le seul dossier
    `INBOX`.
    """

    def __init__(self, protocol: str, security: str, leaf: Leaf):
        if protocol not in ("imap", "smtp"):
            raise ValueError(protocol)
        if security not in ("ssl", "starttls"):
            raise ValueError(security)
        self.protocol = protocol
        self.security = security
        self._context = server_context(leaf)
        self.commands: list[str] = []
        self.starttls_preamble = b""
        self.starttls_trailer = b""
        self.port = 0
        self._listen = None
        self._threads: list[threading.Thread] = []
        self._sockets: list = []
        self._lock = threading.Lock()
        self._running = False

    def use(self, leaf: Leaf) -> None:
        """Les connexions SUIVANTES présentent `leaf`."""
        self._context = server_context(leaf)

    def start(self) -> "MiniServer":
        ecoute = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        ecoute.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        ecoute.bind(("127.0.0.1", 0))
        ecoute.listen(8)
        # `accept` bloqué ne se réveille pas quand un autre fil ferme la
        # socket : il revient regarder `_running` à chaque délai.
        ecoute.settimeout(ACCEPT_POLL)
        self._listen = ecoute
        self.port = ecoute.getsockname()[1]
        self._running = True
        fil = threading.Thread(target=self._accept, daemon=True)
        self._threads.append(fil)
        fil.start()
        return self

    def stop(self) -> None:
        """Idempotent : ferme l'écoute et chaque connexion, joint les
        fils."""
        self._running = False
        with self._lock:
            sockets = list(self._sockets)
        for sock in sockets:
            # `shutdown` réveille un `recv` bloqué dans un autre fil, ce
            # que `close` seul ne fait pas.
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except (OSError, ValueError):
                pass
            try:
                sock.close()
            except OSError:
                pass
        for fil in list(self._threads):
            fil.join(timeout=SERVER_TIMEOUT)
        if self._listen is not None:
            try:
                self._listen.close()
            except OSError:
                pass
            self._listen = None

    def _accept(self) -> None:
        ecoute = self._listen
        while self._running:
            try:
                conn, _ = ecoute.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            conn.settimeout(SERVER_TIMEOUT)
            if not self._running:
                conn.close()
                return
            with self._lock:
                self._sockets.append(conn)
            fil = threading.Thread(
                target=self._serve, args=(conn,), daemon=True
            )
            self._threads.append(fil)
            fil.start()

    def _note(self, ligne: bytes) -> None:
        verbe = ligne.split(b" ", 2)
        if self.protocol == "imap":
            mot = verbe[1] if len(verbe) > 1 else b""
        else:
            mot = verbe[0]
        self.commands.append(mot.decode("ascii", "replace").upper())

    def _wrap(self, conn):
        tls_conn = self._context.wrap_socket(conn, server_side=True)
        with self._lock:
            self._sockets.append(tls_conn)
        return tls_conn

    def _serve(self, conn) -> None:
        try:
            if self.security == "ssl":
                conn = self._wrap(conn)
            if self.protocol == "imap":
                self._imap(conn)
            else:
                self._smtp(conn)
        except (OSError, ConnectionError, ssl.SSLError, ValueError):
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def _imap(self, conn) -> None:
        en_clair = self.security == "starttls"

        def caps():
            return (
                b"IMAP4rev1"
                + (b" STARTTLS" if en_clair else b"")
                + (b" AUTH=PLAIN")
            )

        conn.sendall(b"* OK [CAPABILITY " + caps() + b"] ready\r\n")
        lignes = _Lines(conn)
        while True:
            ligne = lignes.readline()
            self._note(ligne)
            morceaux = ligne.split(b" ", 2)
            tag = morceaux[0]
            verbe = morceaux[1].upper() if len(morceaux) > 1 else b""
            if verbe == b"CAPABILITY":
                conn.sendall(b"* CAPABILITY " + caps() + b"\r\n")
                conn.sendall(tag + b" OK done\r\n")
            elif verbe == b"STARTTLS" and en_clair:
                if self.starttls_preamble:
                    conn.sendall(self.starttls_preamble)
                conn.sendall(
                    tag + b" OK Begin TLS\r\n" + self.starttls_trailer
                )
                conn = self._wrap(conn)
                lignes = _Lines(conn)
                en_clair = False
            elif verbe == b"LOGIN":
                conn.sendall(tag + b" OK logged in\r\n")
            elif verbe == b"LIST":
                conn.sendall(
                    b'* LIST (\\HasNoChildren) "/" "INBOX"\r\n'
                    + tag
                    + b" OK done\r\n"
                )
            elif verbe == b"LOGOUT":
                conn.sendall(b"* BYE bye\r\n" + tag + b" OK done\r\n")
                return
            else:
                conn.sendall(tag + b" BAD unknown\r\n")

    def _smtp(self, conn) -> None:
        en_clair = self.security == "starttls"
        conn.sendall(b"220 ready\r\n")
        lignes = _Lines(conn)
        while True:
            ligne = lignes.readline()
            self._note(ligne)
            verbe = ligne.split(b" ", 1)[0].upper()
            if verbe in (b"EHLO", b"HELO"):
                if en_clair:
                    conn.sendall(
                        b"250-mini\r\n250-AUTH PLAIN\r\n250 STARTTLS\r\n"
                    )
                else:
                    conn.sendall(b"250-mini\r\n250 AUTH PLAIN\r\n")
            elif verbe == b"STARTTLS" and en_clair:
                conn.sendall(b"220 go\r\n")
                conn = self._wrap(conn)
                lignes = _Lines(conn)
                en_clair = False
            elif verbe == b"AUTH":
                conn.sendall(b"235 ok\r\n")
            elif verbe == b"QUIT":
                conn.sendall(b"221 bye\r\n")
                return
            else:
                conn.sendall(b"502 no\r\n")
