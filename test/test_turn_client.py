#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Client STUN/TURN de `script/todo/turn_client.py` : vecteurs RFC 5769,
clés long terme et REST, Allocate contre de faux serveurs UDP, TCP et TLS
lancés dans un fil sur 127.0.0.1.

Les faux serveurs encodent et vérifient les messages avec leurs propres
fonctions, écrites ici à partir des RFC 5389 et 5766, et non avec celles du
module : un défaut commun aux deux côtés ne se cacherait pas derrière un
aller-retour réussi.
"""

import ast
import base64
import binascii
import hashlib
import hmac
import os
import shutil
import socket
import ssl
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from script.todo import turn_client as tc

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MAGIC = 0x2112A442
ALLOCATE = 0x0003
REFRESH = 0x0004
BINDING = 0x0001

# Valeurs inventées pour les faux serveurs.
REALM = b"turn.exemple.test"
NONCE = b"nonce-exemple-0001"
USER = "erplibre-check"
PASSWORD = "mot-de-passe-exemple"
KEY = hashlib.md5(f"{USER}:turn.exemple.test:{PASSWORD}".encode()).digest()
RELAYED = ("192.0.2.10", 50000)
MAPPED = ("198.51.100.7", 40001)


def hexbytes(text):
    return bytes.fromhex("".join(text.split()))


# RFC 5769 §2.1, « Sample Request » : mot de passe court terme
# « VOkJxbRl1RmTxUk/WvJxBt », bourrage du USERNAME en espaces.
RFC5769_REQUEST = hexbytes(
    """
    00 01 00 58 21 12 a4 42 b7 e7 a7 01 bc 34 d6 86 fa 87 df ae
    80 22 00 10 53 54 55 4e 20 74 65 73 74 20 63 6c 69 65 6e 74
    00 24 00 04 6e 00 01 ff
    80 29 00 08 93 2f f9 b1 51 26 3b 36
    00 06 00 09 65 76 74 6a 3a 68 36 76 59 20 20 20
    00 08 00 14 9a ea a7 0c bf d8 cb 56 78 1e f2 b5 b2 d3 f2 49 c1 b5 71 a2
    80 28 00 04 e5 7a 3b cf
    """
)

# RFC 5769 §2.2, « Sample IPv4 Response » : 192.0.2.1 port 32853.
RFC5769_RESPONSE = hexbytes(
    """
    01 01 00 3c 21 12 a4 42 b7 e7 a7 01 bc 34 d6 86 fa 87 df ae
    80 22 00 0b 74 65 73 74 20 76 65 63 74 6f 72 20
    00 20 00 08 00 01 a1 47 e1 12 a6 43
    00 08 00 14 2b 91 f5 99 fd 9e 90 c3 8c 74 89 f9 2a f9 ba 53 f0 6b e7 d7
    80 28 00 04 c0 7d 4c 96
    """
)

# RFC 5769 §2.4, « Sample Request with Long-Term Authentication » : pas de
# FINGERPRINT, mot de passe « TheMatrIX » après SASLprep.
RFC5769_LONG_TERM = hexbytes(
    """
    00 01 00 60 21 12 a4 42 78 ad 34 33 c6 ad 72 c0 29 da 41 2e
    00 06 00 12 e3 83 9e e3 83 88 e3 83 aa e3 83 83 e3 82 af e3 82 b9 00 00
    00 15 00 1c 66 2f 2f 34 39 39 6b 39 35 34 64 36 4f 4c 33 34 6f 4c 39 46
    53 54 76 79 36 34 73 41
    00 14 00 0b 65 78 61 6d 70 6c 65 2e 6f 72 67 00
    00 08 00 14 f6 70 24 65 6d d6 4a 3e 02 b8 e0 71 2e 85 c9 a2 8c a8 96 66
    """
)
RFC5769_LONG_TERM_USER = "マトリックス"


# --- Encodage indépendant, côté faux serveur -----------------------------


def attr(kind, value):
    pad = (-len(value)) % 4
    return struct.pack("!HH", kind, len(value)) + value + b"\0" * pad


def xor_v4(address, txid):
    host, port = address
    raw = socket.inet_aton(host)
    xaddr = bytes(
        a ^ b for a, b in zip(raw, struct.pack("!I", MAGIC), strict=True)
    )
    return struct.pack("!BBH", 0, 1, port ^ (MAGIC >> 16)) + xaddr


def message(kind, txid, attrs, key=None):
    body = b"".join(attr(k, v) for k, v in attrs)
    if key is not None:
        head = struct.pack("!HHI", kind, len(body) + 24, MAGIC) + txid
        mac = hmac.new(key, head + body, hashlib.sha1).digest()
        body += attr(0x0008, mac)
    head = struct.pack("!HHI", kind, len(body) + 8, MAGIC) + txid
    crc = (binascii.crc32(head + body) ^ 0x5354554E) & 0xFFFFFFFF
    body += attr(0x8028, struct.pack("!I", crc))
    return struct.pack("!HHI", kind, len(body), MAGIC) + txid + body


def parse(data):
    """(type, txid, {attribut: valeur}, positions) d'une requête reçue."""
    kind, length, magic = struct.unpack("!HHI", data[:8])
    assert magic == MAGIC, "magic cookie"
    assert length == len(data) - 20, "longueur d'en-tête"
    txid = data[8:20]
    attrs, offsets = {}, {}
    pos = 20
    while pos < len(data):
        k, n = struct.unpack("!HH", data[pos : pos + 4])
        attrs[k] = data[pos + 4 : pos + 4 + n]
        offsets[k] = pos
        pos += 4 + n + ((-n) % 4)
    return kind, txid, attrs, offsets


def integrity_ok(data, key):
    """MESSAGE-INTEGRITY et FINGERPRINT d'une requête reçue, recalculés."""
    _kind, _txid, attrs, offsets = parse(data)
    mi = offsets[0x0008]
    head = data[:2] + struct.pack("!H", mi + 24 - 20) + data[4:mi]
    mac = hmac.new(key, head, hashlib.sha1).digest()
    fp = offsets[0x8028]
    assert fp == mi + 24, "FINGERPRINT suit MESSAGE-INTEGRITY"
    crc = (binascii.crc32(data[:fp]) ^ 0x5354554E) & 0xFFFFFFFF
    return mac == attrs[0x0008] and struct.pack("!I", crc) == attrs[0x8028]


def error_attr(code, reason):
    return (0x0009, struct.pack("!HBB", 0, code // 100, code % 100) + reason)


class FakeTurn:
    """Faux serveur TURN : `answers` est une liste de fonctions
    `(requête, txid, attributs) -> réponse | None`, consommées une par
    requête reçue ; liste épuisée, plus rien ne répond. Les requêtes reçues
    restent dans `received`."""

    def __init__(self, answers, transport="udp", tls_context=None):
        self.answers = list(answers)
        self.received = []
        self.transport = transport
        self.tls_context = tls_context
        kind = socket.SOCK_DGRAM if transport == "udp" else socket.SOCK_STREAM
        self.sock = socket.socket(socket.AF_INET, kind)
        self.sock.bind(("127.0.0.1", 0))
        if transport != "udp":
            self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        self.sock.close()
        self.thread.join(5)

    def _answer(self, data):
        self.received.append(data)
        if not self.answers:
            return None
        _kind, txid, attrs, _off = parse(data)
        return self.answers.pop(0)(data, txid, attrs)

    def _run(self):
        self.sock.settimeout(0.1)
        if self.transport == "udp":
            while not self.stop.is_set():
                try:
                    data, peer = self.sock.recvfrom(2048)
                except (socket.timeout, OSError):
                    continue
                reply = self._answer(data)
                if reply:
                    for chunk in reply if isinstance(reply, list) else [reply]:
                        self.sock.sendto(chunk, peer)
            return
        while not self.stop.is_set():
            try:
                conn, _peer = self.sock.accept()
            except (socket.timeout, OSError):
                continue
            conn.settimeout(5)
            try:
                if self.tls_context is not None:
                    conn = self.tls_context.wrap_socket(conn, server_side=True)
                self._serve_stream(conn)
            except (OSError, ssl.SSLError):
                pass
            finally:
                conn.close()

    def _serve_stream(self, conn):
        while not self.stop.is_set():
            head = self._read(conn, 20)
            if not head:
                return
            body = self._read(conn, struct.unpack("!H", head[2:4])[0])
            reply = self._answer(head + body)
            if reply:
                # Coupé en deux envois : le client doit relire jusqu'à la
                # longueur annoncée par l'en-tête.
                conn.sendall(reply[:7])
                time.sleep(0.02)
                conn.sendall(reply[7:])

    @staticmethod
    def _read(conn, n):
        data = b""
        while len(data) < n:
            chunk = conn.recv(n - len(data))
            if not chunk:
                return None
            data += chunk
        return data


def unauthorized(_data, txid, _attrs):
    return message(
        0x0113,
        txid,
        [error_attr(401, b"Unauthorized"), (0x0014, REALM), (0x0015, NONCE)],
    )


def allocated(data, txid, attrs):
    assert attrs[0x0006] == USER.encode()
    assert attrs[0x0014] == REALM and attrs[0x0015] == NONCE
    assert attrs[0x0019] == b"\x11\0\0\0", "REQUESTED-TRANSPORT UDP"
    if not integrity_ok(data, KEY):
        return message(0x0113, txid, [error_attr(400, b"Bad Request")])
    return message(
        0x0103,
        txid,
        [
            (0x0016, xor_v4(RELAYED, txid)),
            (0x0020, xor_v4(MAPPED, txid)),
            (0x000D, struct.pack("!I", 600)),
        ],
        key=KEY,
    )


def refreshed(data, txid, attrs):
    assert integrity_ok(data, KEY)
    return message(0x0104, txid, [(0x000D, struct.pack("!I", 0))], key=KEY)


class TestVectors(unittest.TestCase):
    def test_rfc5769_sample_request_integrity_and_fingerprint(self):
        txid = RFC5769_REQUEST[8:20]
        attrs = RFC5769_REQUEST[20:-32]
        sealed = tc.seal(0x0001, txid, attrs, b"VOkJxbRl1RmTxUk/WvJxBt")
        self.assertEqual(sealed, RFC5769_REQUEST)

    def test_rfc5769_sample_response_decodes_and_verifies(self):
        msg = tc.decode(RFC5769_RESPONSE)
        self.assertEqual(msg.kind, 0x0101)
        self.assertEqual(
            tc.xor_address(msg.attr(0x0020), msg.txid), ("192.0.2.1", 32853)
        )
        self.assertTrue(
            tc.integrity_ok(RFC5769_RESPONSE, b"VOkJxbRl1RmTxUk/WvJxBt")
        )
        self.assertFalse(tc.integrity_ok(RFC5769_RESPONSE, b"autre"))

    def test_rfc5769_long_term_request(self):
        key = tc.long_term_key(
            RFC5769_LONG_TERM_USER, "example.org", "TheMatrIX"
        )
        txid = RFC5769_LONG_TERM[8:20]
        attrs = RFC5769_LONG_TERM[20:-24]
        sealed = tc.seal(0x0001, txid, attrs, key, fingerprint=False)
        self.assertEqual(sealed, RFC5769_LONG_TERM)

    def test_decode_rejects_a_corrupted_fingerprint(self):
        bad = RFC5769_RESPONSE[:-1] + bytes([RFC5769_RESPONSE[-1] ^ 1])
        with self.assertRaises(ValueError):
            tc.decode(bad)

    def test_decode_rejects_a_wrong_length_or_cookie(self):
        with self.assertRaises(ValueError):
            tc.decode(RFC5769_RESPONSE[:-4])
        with self.assertRaises(ValueError):
            tc.decode(
                RFC5769_RESPONSE[:4] + b"\0\0\0\0" + RFC5769_RESPONSE[8:]
            )


class TestCredentials(unittest.TestCase):
    def test_long_term_key_is_md5_of_user_realm_password(self):
        self.assertEqual(
            tc.long_term_key("user", "realm", "pass"),
            hashlib.md5(b"user:realm:pass").digest(),
        )

    def test_rest_credentials(self):
        username, password = tc.rest_credentials("s3cret", "odoo", 1893456000)
        self.assertEqual(username, "1893456000:odoo")
        expected = base64.b64encode(
            hmac.new(b"s3cret", b"1893456000:odoo", hashlib.sha1).digest()
        ).decode()
        self.assertEqual(password, expected)


class FakeCase(unittest.TestCase):
    def fake(self, answers, transport="udp", tls_context=None):
        server = FakeTurn(answers, transport, tls_context)
        self.addCleanup(server.close)
        return server

    def requests(self, server):
        return [parse(data) for data in server.received]


class TestAllocateUdp(FakeCase):
    def test_success_then_refresh_with_lifetime_zero(self):
        server = self.fake([unauthorized, allocated, refreshed])
        result = tc.allocate(
            "127.0.0.1", server.port, "udp", USER, KEY, timeout=3
        )
        self.assertEqual(result, tc.Allocation(True, RELAYED, None))
        kinds = [r[0] for r in self.requests(server)]
        self.assertEqual(kinds, [ALLOCATE, ALLOCATE, REFRESH])
        first = self.requests(server)[0][2]
        self.assertNotIn(0x0008, first, "premier Allocate sans intégrité")
        self.assertEqual(first[0x0019], b"\x11\0\0\0")
        refresh = self.requests(server)[2][2]
        self.assertEqual(refresh[0x000D], struct.pack("!I", 0))
        self.assertEqual(refresh[0x0015], NONCE)

    def test_wrong_key_is_refused_by_the_fake(self):
        server = self.fake([unauthorized, allocated])
        result = tc.allocate(
            "127.0.0.1", server.port, "udp", USER, b"\0" * 16, timeout=3
        )
        self.assertEqual(result, tc.Allocation(False, None, "400 Bad Request"))

    def test_401_twice_fails_with_the_code(self):
        server = self.fake([unauthorized, unauthorized])
        result = tc.allocate(
            "127.0.0.1", server.port, "udp", USER, KEY, timeout=3
        )
        self.assertFalse(result.ok)
        self.assertIsNone(result.relayed)
        self.assertTrue(result.error.startswith("401"), result.error)

    def test_other_error_on_first_request(self):
        def forbidden(_data, txid, _attrs):
            return message(0x0113, txid, [error_attr(403, b"Forbidden")])

        server = self.fake([forbidden])
        result = tc.allocate(
            "127.0.0.1", server.port, "udp", USER, KEY, timeout=3
        )
        self.assertEqual(result, tc.Allocation(False, None, "403 Forbidden"))

    def test_stale_nonce_is_retried_once_with_the_new_nonce(self):
        def stale(_data, txid, _attrs):
            return message(
                0x0113,
                txid,
                [
                    error_attr(438, b"Stale Nonce"),
                    (0x0014, REALM),
                    (0x0015, NONCE),
                ],
            )

        server = self.fake([unauthorized, stale, allocated, refreshed])
        result = tc.allocate(
            "127.0.0.1", server.port, "udp", USER, KEY, timeout=3
        )
        self.assertEqual(result, tc.Allocation(True, RELAYED, None))

    def test_no_answer_is_a_timeout_within_the_budget(self):
        server = self.fake([])
        start = time.monotonic()
        result = tc.allocate(
            "127.0.0.1", server.port, "udp", USER, KEY, timeout=1.0
        )
        self.assertLess(time.monotonic() - start, 2.0)
        self.assertEqual(result, tc.Allocation(False, None, "timeout"))
        self.assertGreaterEqual(len(server.received), 2, "retransmission UDP")

    def test_foreign_datagram_is_ignored(self):
        def noise_then_401(data, txid, attrs):
            other = bytes(12)
            return [
                b"garbage",
                message(0x0101, other, []),
                unauthorized(data, txid, attrs),
            ]

        server = self.fake([noise_then_401, allocated, refreshed])
        result = tc.allocate(
            "127.0.0.1", server.port, "udp", USER, KEY, timeout=3
        )
        self.assertTrue(result.ok, result)

    def test_success_survives_an_unanswered_refresh(self):
        server = self.fake([unauthorized, allocated])
        start = time.monotonic()
        result = tc.allocate(
            "127.0.0.1", server.port, "udp", USER, KEY, timeout=1.0
        )
        self.assertTrue(result.ok)
        self.assertLess(time.monotonic() - start, 2.0)

    def test_unknown_transport_is_refused(self):
        with self.assertRaises(ValueError):
            tc.allocate("127.0.0.1", 3478, "sctp", USER, KEY)

    def test_short_relayed_address_is_malformed(self):
        def short_relayed(_data, txid, _attrs):
            return message(0x0103, txid, [(0x0016, b"\0\x01")], key=KEY)

        server = self.fake([unauthorized, short_relayed])
        result = tc.allocate(
            "127.0.0.1", server.port, "udp", USER, KEY, timeout=3
        )
        self.assertEqual(result, tc.Allocation(False, None, "malformed"))

    def test_open_relay_is_a_failure_and_is_released(self):
        def open_relay(_data, txid, _attrs):
            return message(0x0103, txid, [(0x0016, xor_v4(RELAYED, txid))])

        def released(_data, txid, _attrs):
            return message(0x0104, txid, [(0x000D, struct.pack("!I", 0))])

        server = self.fake([open_relay, released])
        result = tc.allocate(
            "127.0.0.1", server.port, "udp", USER, b"\0" * 16, timeout=3
        )
        self.assertEqual(result, tc.Allocation(False, None, "no-auth"))
        self.assertEqual(
            [r[0] for r in self.requests(server)], [ALLOCATE, REFRESH]
        )
        self.assertEqual(
            self.requests(server)[1][2][0x000D], struct.pack("!I", 0)
        )

    def test_authenticated_success_without_integrity_is_refused(self):
        def unsigned(_data, txid, _attrs):
            return message(0x0103, txid, [(0x0016, xor_v4(RELAYED, txid))])

        server = self.fake([unauthorized, unsigned, refreshed])
        result = tc.allocate(
            "127.0.0.1", server.port, "udp", USER, KEY, timeout=3
        )
        self.assertEqual(result, tc.Allocation(False, None, "integrity"))

    def test_success_signed_with_another_key_is_refused(self):
        def signed_elsewhere(_data, txid, _attrs):
            return message(
                0x0103,
                txid,
                [(0x0016, xor_v4(RELAYED, txid))],
                key=b"\x01" * 16,
            )

        server = self.fake([unauthorized, signed_elsewhere, refreshed])
        result = tc.allocate(
            "127.0.0.1", server.port, "udp", USER, KEY, timeout=3
        )
        self.assertEqual(result, tc.Allocation(False, None, "integrity"))


class TestResolution(unittest.TestCase):
    """La résolution du nom compte dans le budget : un résolveur muet ne
    doit pas retenir l'appel au-delà de `timeout`."""

    def stalled_resolver(self):
        release = threading.Event()
        self.addCleanup(release.set)

        def getaddrinfo(*_args, **_kwargs):
            release.wait(10)
            raise socket.gaierror("résolveur muet")

        patcher = mock.patch.object(tc.socket, "getaddrinfo", getaddrinfo)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_allocate_stalled_resolver_is_a_timeout_within_the_budget(self):
        self.stalled_resolver()
        start = time.monotonic()
        result = tc.allocate(
            "turn.exemple.test", 3478, "udp", USER, KEY, timeout=0.5
        )
        self.assertLess(time.monotonic() - start, 1.5)
        self.assertEqual(result, tc.Allocation(False, None, "timeout"))

    def test_binding_stalled_resolver_is_none_within_the_budget(self):
        self.stalled_resolver()
        start = time.monotonic()
        self.assertIsNone(tc.binding("turn.exemple.test", 3478, timeout=0.5))
        self.assertLess(time.monotonic() - start, 1.5)

    def test_unknown_name_is_unreachable(self):
        def getaddrinfo(*_args, **_kwargs):
            raise socket.gaierror("nom inconnu")

        with mock.patch.object(tc.socket, "getaddrinfo", getaddrinfo):
            result = tc.allocate(
                "turn.exemple.test", 3478, "udp", USER, KEY, timeout=2
            )
        self.assertEqual(result, tc.Allocation(False, None, "unreachable"))


class TestAllocateStream(FakeCase):
    def test_tcp_framing_success(self):
        server = self.fake(
            [unauthorized, allocated, refreshed], transport="tcp"
        )
        result = tc.allocate(
            "127.0.0.1", server.port, "tcp", USER, KEY, timeout=3
        )
        self.assertEqual(result, tc.Allocation(True, RELAYED, None))
        self.assertEqual(
            [r[0] for r in self.requests(server)],
            [ALLOCATE, ALLOCATE, REFRESH],
        )

    def test_tcp_refused(self):
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        result = tc.allocate("127.0.0.1", port, "tcp", USER, KEY, timeout=2)
        self.assertEqual(result, tc.Allocation(False, None, "refused"))

    def test_tls_against_a_plain_server_is_a_tls_error(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        self.addCleanup(listener.close)

        def serve():
            conn, _ = listener.accept()
            conn.sendall(b"HTTP/1.0 400 Bad Request\r\n\r\n")
            conn.close()

        threading.Thread(target=serve, daemon=True).start()
        port = listener.getsockname()[1]
        result = tc.allocate("127.0.0.1", port, "tls", USER, KEY, timeout=3)
        self.assertEqual(result, tc.Allocation(False, None, "tls"))

    @unittest.skipUnless(shutil.which("openssl"), "openssl absent")
    def test_tls_success_with_supplied_ca_and_server_name(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        cert = os.path.join(tmp, "cert.pem")
        key = os.path.join(tmp, "key.pem")
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-keyout",
                key,
                "-out",
                cert,
                "-days",
                "2",
                "-subj",
                "/CN=turn.exemple.test",
                "-addext",
                "subjectAltName=DNS:turn.exemple.test",
            ],
            check=True,
            capture_output=True,
            timeout=60,
        )
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        server = self.fake(
            [unauthorized, allocated, refreshed],
            transport="tcp",
            tls_context=context,
        )
        result = tc.allocate(
            "127.0.0.1",
            server.port,
            "tls",
            USER,
            KEY,
            timeout=5,
            cafile=cert,
            server_name="turn.exemple.test",
        )
        self.assertEqual(result, tc.Allocation(True, RELAYED, None))
        # Sans l'autorité fournie, le certificat ne se vérifie pas.
        server2 = self.fake(
            [unauthorized], transport="tcp", tls_context=context
        )
        result = tc.allocate(
            "127.0.0.1",
            server2.port,
            "tls",
            USER,
            KEY,
            timeout=5,
            server_name="turn.exemple.test",
        )
        self.assertEqual(result, tc.Allocation(False, None, "tls"))


class TestBinding(FakeCase):
    @staticmethod
    def mapped(_data, txid, attrs):
        assert 0x8028 in attrs, "FINGERPRINT"
        return message(0x0101, txid, [(0x0020, xor_v4(MAPPED, txid))])

    def test_udp_binding_returns_the_mapped_address(self):
        server = self.fake([self.mapped])
        self.assertEqual(
            tc.binding("127.0.0.1", server.port, timeout=3), MAPPED
        )
        self.assertEqual(self.requests(server)[0][0], BINDING)

    def test_tcp_binding(self):
        server = self.fake([self.mapped], transport="tcp")
        self.assertEqual(
            tc.binding("127.0.0.1", server.port, "tcp", timeout=3), MAPPED
        )

    def test_short_mapped_address_is_none(self):
        def short(_data, txid, _attrs):
            return message(0x0101, txid, [(0x0020, b"\0")])

        def short_plain(_data, txid, _attrs):
            return message(0x0101, txid, [(0x0001, b"\0\x01")])

        for answer in (short, short_plain):
            server = self.fake([answer])
            self.assertIsNone(tc.binding("127.0.0.1", server.port, timeout=2))

    def test_address_decoders_reject_short_values(self):
        for value in (b"", b"\0", b"\0\x01", b"\0\x01\0"):
            with self.assertRaises(ValueError):
                tc.xor_address(value, bytes(12))

    def test_no_answer_is_none(self):
        server = self.fake([])
        start = time.monotonic()
        self.assertIsNone(tc.binding("127.0.0.1", server.port, timeout=0.8))
        self.assertLess(time.monotonic() - start, 1.8)


class TestStdlibOnly(unittest.TestCase):
    def test_module_imports_only_stdlib(self):
        with open(os.path.join(REPO, "script", "todo", "turn_client.py")) as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module.split(".")[0]]
            for name in names:
                self.assertIn(name, sys.stdlib_module_names)


if __name__ == "__main__":
    unittest.main()
