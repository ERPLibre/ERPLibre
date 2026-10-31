#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Client STUN/TURN minimal, stdlib seule : le contrôle de coturn depuis la
machine qui lance `todo.py`.

`binding()` envoie une requête STUN Binding et rend l'adresse vue par le
serveur. `allocate()` déroule une allocation TURN complète (RFC 5766) :

1. Allocate sans authentification, REQUESTED-TRANSPORT UDP ;
2. le serveur répond 401 avec REALM et NONCE ;
3. Allocate authentifié : USERNAME, REALM, NONCE, MESSAGE-INTEGRITY
   (HMAC-SHA1 sous la clé long terme), FINGERPRINT. Un 438 (nonce périmé)
   est rejoué une fois avec le nouveau nonce ;
4. succès : l'adresse relayée vient de XOR-RELAYED-ADDRESS, puis un Refresh
   de durée 0 libère l'allocation tout de suite au lieu de la laisser
   expirer sur le serveur. Ce Refresh ne change pas le verdict.

`permission()` insère, entre l'étape 3 et le Refresh, un CreatePermission
(RFC 5766 §9) vers un pair donné : coturn le refuse en 403 quand le pair
tombe dans ses plages `denied-peer-ip`, ce qui prouve qu'un relais ne joint
pas le réseau privé de l'hôte.

La clé est `long_term_key(utilisateur, realm, mot_de_passe)` : le realm doit
donc être connu de l'appelant, c'est celui que l'installeur a écrit. Pour
des identifiants temporaires, `rest_credentials()` donne le couple
utilisateur / mot de passe dont on tire la même clé.

Transports : « udp » (retransmission dès 0,5 s, doublée à chaque essai,
RFC 5389 §7.2.1), « tcp » et « tls » (un message STUN se délimite seul par
la longueur de son en-tête : 20 octets puis le corps). Toute l'allocation
tient dans UN budget `timeout`, résolution du nom, retransmissions et
Refresh compris.

Les messages reçus sont validés : magic cookie, longueur, FINGERPRINT s'il
est présent, transaction attendue. En UDP, un datagramme qui ne passe pas
est ignoré comme du bruit ; sur un flux, il termine l'échange en
« malformed ». Le succès authentifié doit porter une MESSAGE-INTEGRITY juste
sous la clé : absente ou fausse, elle vient d'un serveur qui ne connaît pas
la clé, et l'allocation échoue en « integrity ». Un succès dès le premier
Allocate, sans authentification, est un relais ouvert : échec en « no-auth ».
"""

import base64
import binascii
import hashlib
import hmac
import ipaddress
import os
import socket
import ssl
import struct
import threading
import time
from dataclasses import dataclass

MAGIC_COOKIE = 0x2112A442
_FINGERPRINT_XOR = 0x5354554E
_HEADER = struct.Struct("!HHI")

BINDING_REQUEST = 0x0001
ALLOCATE_REQUEST = 0x0003
REFRESH_REQUEST = 0x0004
CREATE_PERMISSION_REQUEST = 0x0008

# Bits de classe du type de message (RFC 5389 §6) : 0b00 requête,
# 0b10 succès, 0b11 erreur.
_CLASS_MASK = 0x0110
_CLASS_SUCCESS = 0x0100
_CLASS_ERROR = 0x0110

MAPPED_ADDRESS = 0x0001
USERNAME = 0x0006
MESSAGE_INTEGRITY = 0x0008
ERROR_CODE = 0x0009
LIFETIME = 0x000D
XOR_PEER_ADDRESS = 0x0012
REALM = 0x0014
NONCE = 0x0015
XOR_RELAYED_ADDRESS = 0x0016
REQUESTED_TRANSPORT = 0x0019
XOR_MAPPED_ADDRESS = 0x0020
FINGERPRINT = 0x8028

# REQUESTED-TRANSPORT : numéro de protocole IP (17 = UDP) puis 3 octets RFFU.
_TRANSPORT_UDP = bytes([17, 0, 0, 0])
TRANSPORTS = ("udp", "tcp", "tls")

# Valeurs de `Allocation.error` autres qu'un code TURN « <code> <raison> » ;
# la docstring d'`Allocation` dit ce que chacune signifie. Un appelant qui
# traduit les erreurs couvre cette liste, et affiche le code TURN tel quel.
ERRORS = (
    "timeout",
    "refused",
    "tls",
    "closed",
    "unreachable",
    "malformed",
    "integrity",
    "no-auth",
)

# Retransmission UDP : premier délai, et attente maximale du Refresh final.
_RTO = 0.5
_REFRESH_WAIT = 2.0


@dataclass(frozen=True)
class Allocation:
    """Résultat de `allocate()`.

    Rendu aussi par `permission()`, dont le succès dit que le pair est
    accordé ; `relayed` vaut alors l'adresse relayée de l'allocation.

    `error` vaut None sur un succès, sinon un code TURN ou une valeur de
    `ERRORS` :
    - « <code> <raison> » : l'erreur TURN rendue par le serveur
      (« 401 Unauthorized », « 403 Forbidden »…) ;
    - « timeout » : aucune réponse dans le budget ;
    - « refused » : connexion refusée (TCP) ou ICMP « port unreachable »
      (UDP) ;
    - « tls » : poignée de main ou vérification du certificat en échec ;
    - « closed » : le serveur a coupé le flux en cours d'échange ;
    - « unreachable » : nom introuvable ou réseau injoignable ;
    - « malformed » : réponse qui n'est pas un message STUN valide ;
    - « integrity » : succès authentifié dont la MESSAGE-INTEGRITY manque
      ou ne se vérifie pas sous la clé ;
    - « no-auth » : le serveur alloue sans authentification (relais ouvert).
    """

    ok: bool
    relayed: tuple[str, int] | None
    error: str | None


@dataclass(frozen=True)
class Message:
    """Message STUN décodé : type, identifiant de transaction (12 octets)
    et attributs dans leur ordre d'arrivée."""

    kind: int
    txid: bytes
    attrs: tuple[tuple[int, bytes], ...]

    def attr(self, kind):
        """Valeur du premier attribut `kind`, ou None."""
        for k, value in self.attrs:
            if k == kind:
                return value
        return None

    @property
    def is_success(self):
        return self.kind & _CLASS_MASK == _CLASS_SUCCESS

    @property
    def is_error(self):
        return self.kind & _CLASS_MASK == _CLASS_ERROR


def long_term_key(username: str, realm: str, password: str) -> bytes:
    """Clé long terme : MD5(« utilisateur:realm:mot_de_passe »), RFC 5389
    §15.4. Le mot de passe est pris tel quel (pas de SASLprep)."""
    return hashlib.md5(f"{username}:{realm}:{password}".encode()).digest()


def rest_credentials(secret: str, user: str, expiry: int) -> tuple[str, str]:
    """Identifiants temporaires du « TURN REST API » que coturn accepte avec
    `use-auth-secret` : utilisateur « <expiration>:<user> », mot de passe
    base64(HMAC-SHA1(secret, utilisateur)). `expiry` est un horodatage Unix."""
    username = f"{expiry}:{user}"
    digest = hmac.new(
        secret.encode(), username.encode(), hashlib.sha1
    ).digest()
    return username, base64.b64encode(digest).decode()


def attribute(kind: int, value: bytes) -> bytes:
    """Un attribut encodé, bourré de zéros jusqu'à un multiple de 4."""
    return (
        struct.pack("!HH", kind, len(value))
        + value
        + b"\0" * (-len(value) % 4)
    )


def seal(
    kind: int,
    txid: bytes,
    attributes: bytes,
    key: bytes | None,
    fingerprint: bool = True,
) -> bytes:
    """Message complet : en-tête, `attributes` (déjà encodés), puis
    MESSAGE-INTEGRITY si `key` est donnée et FINGERPRINT si demandé.

    Chaque empreinte se calcule sur un en-tête dont la longueur couvre déjà
    l'attribut qu'on ajoute (RFC 5389 §15.4 et §15.5), d'où un en-tête
    reconstruit pour chacune."""
    body = attributes
    if key is not None:
        head = _HEADER.pack(kind, len(body) + 24, MAGIC_COOKIE) + txid
        mac = hmac.new(key, head + body, hashlib.sha1).digest()
        body += attribute(MESSAGE_INTEGRITY, mac)
    if fingerprint:
        head = _HEADER.pack(kind, len(body) + 8, MAGIC_COOKIE) + txid
        body += attribute(FINGERPRINT, struct.pack("!I", _crc(head + body)))
    return _HEADER.pack(kind, len(body), MAGIC_COOKIE) + txid + body


def _crc(data):
    return (binascii.crc32(data) ^ _FINGERPRINT_XOR) & 0xFFFFFFFF


def _walk(data):
    """(type, début, valeur) de chaque attribut ; ValueError si tronqué."""
    pos = 20
    while pos < len(data):
        if pos + 4 > len(data):
            raise ValueError("attribut tronqué")
        kind, length = struct.unpack("!HH", data[pos : pos + 4])
        end = pos + 4 + length
        if end > len(data):
            raise ValueError("attribut tronqué")
        yield kind, pos, data[pos + 4 : end]
        pos = end + (-length % 4)


def decode(data: bytes) -> Message:
    """Décode un message STUN ; ValueError s'il n'en est pas un : moins de
    20 octets, deux bits de tête non nuls, magic cookie ou longueur faux,
    attribut tronqué, FINGERPRINT faux ou qui n'est pas le dernier."""
    if len(data) < 20:
        raise ValueError("message trop court")
    kind, length, magic = _HEADER.unpack(data[:8])
    if kind & 0xC000 or magic != MAGIC_COOKIE:
        raise ValueError("pas un message STUN")
    if length != len(data) - 20 or length % 4:
        raise ValueError("longueur incohérente")
    attrs = []
    for k, pos, value in _walk(data):
        if k == FINGERPRINT:
            if pos + 8 != len(data):
                raise ValueError("FINGERPRINT pas en dernier")
            if struct.pack("!I", _crc(data[:pos])) != value:
                raise ValueError("FINGERPRINT faux")
        attrs.append((k, value))
    return Message(kind, data[8:20], tuple(attrs))


def integrity_ok(data: bytes, key: bytes) -> bool:
    """La MESSAGE-INTEGRITY de `data` se vérifie-t-elle sous `key` ? False
    si l'attribut manque."""
    for kind, pos, value in _walk(data):
        if kind == MESSAGE_INTEGRITY:
            head = data[:2] + struct.pack("!H", pos + 24 - 20) + data[4:pos]
            mac = hmac.new(key, head, hashlib.sha1).digest()
            return hmac.compare_digest(mac, value)
    return False


def _family_port(value):
    """(famille, port) des 4 premiers octets d'un attribut d'adresse ;
    ValueError si la valeur est plus courte, comme pour toute autre forme
    invalide, pour que l'appelant n'ait qu'une exception à attraper."""
    if len(value) < 4:
        raise ValueError("attribut d'adresse tronqué")
    return value[1], struct.unpack("!H", value[2:4])[0]


def xor_address(value: bytes, txid: bytes) -> tuple[str, int]:
    """Adresse d'un XOR-MAPPED-ADDRESS ou XOR-RELAYED-ADDRESS : le port est
    masqué par les 16 bits hauts du magic cookie, l'adresse par le cookie
    (IPv4) ou le cookie suivi de la transaction (IPv6). ValueError si la
    valeur est tronquée ou d'une famille inconnue."""
    family, port = _family_port(value)
    mask = struct.pack("!I", MAGIC_COOKIE) + txid
    if family == 0x01 and len(value) >= 8:
        raw = bytes(a ^ b for a, b in zip(value[4:8], mask[:4], strict=True))
        return socket.inet_ntop(socket.AF_INET, raw), port ^ (
            MAGIC_COOKIE >> 16
        )
    if family == 0x02 and len(value) >= 20:
        raw = bytes(a ^ b for a, b in zip(value[4:20], mask, strict=True))
        return socket.inet_ntop(socket.AF_INET6, raw), port ^ (
            MAGIC_COOKIE >> 16
        )
    raise ValueError("famille d'adresse inconnue")


def xor_peer(host: str, port: int, txid: bytes) -> bytes:
    """Valeur d'un XOR-PEER-ADDRESS pour `host` (IPv4 ou IPv6 littérale),
    masquée comme `xor_address` la démasque. ValueError pour une valeur
    qui n'est pas une adresse IP."""
    address = ipaddress.ip_address(host)
    mask = struct.pack("!I", MAGIC_COOKIE) + txid
    raw = address.packed
    masked = bytes(a ^ b for a, b in zip(raw, mask[: len(raw)], strict=True))
    family = 0x01 if address.version == 4 else 0x02
    return struct.pack("!BBH", 0, family, port ^ (MAGIC_COOKIE >> 16)) + masked


def _plain_address(value):
    """Adresse d'un MAPPED-ADDRESS (non masquée, serveurs RFC 3489)."""
    family, port = _family_port(value)
    if family == 0x01 and len(value) >= 8:
        return socket.inet_ntop(socket.AF_INET, value[4:8]), port
    if family == 0x02 and len(value) >= 20:
        return socket.inet_ntop(socket.AF_INET6, value[4:20]), port
    raise ValueError("famille d'adresse inconnue")


def _error_text(msg):
    """« <code> <raison> » d'une réponse d'erreur."""
    value = msg.attr(ERROR_CODE)
    if value is None or len(value) < 4:
        return "malformed"
    code = (value[2] & 0x07) * 100 + value[3]
    reason = value[4:].decode("utf-8", "replace").strip()
    return f"{code} {reason}".strip()


def _error_code(msg):
    value = msg.attr(ERROR_CODE)
    if value is None or len(value) < 4:
        return None
    return (value[2] & 0x07) * 100 + value[3]


def _resolve(host, port, kind, deadline):
    """Première adresse de `getaddrinfo`, bornée par `deadline`.

    `getaddrinfo` n'a pas de délai propre : il attend celui du résolveur,
    tentatives comprises. Il tourne donc dans un fil démon dont l'attente
    s'arrête au budget ; TimeoutError si le résolveur n'a pas répondu, le
    fil s'achève seul quand il répond. Toute exception du fil remonte telle
    quelle chez l'appelant : `socket.gaierror` (un OSError) pour un nom que
    le résolveur ne connaît pas, UnicodeError (un ValueError) pour un nom
    que l'encodage IDNA refuse avant toute requête, label vide ou de plus
    de 63 caractères."""
    outcome = {}

    def run():
        try:
            outcome["info"] = socket.getaddrinfo(host, port, type=kind)
        except Exception as exc:  # relancée dans le fil appelant
            outcome["error"] = exc

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(max(0.0, deadline - time.monotonic()))
    if worker.is_alive():
        raise TimeoutError("résolution hors budget")
    if "error" in outcome:
        raise outcome["error"]
    return outcome["info"][0]


class _Link:
    """Une connexion vers le serveur, ouverte pour toute l'allocation : en
    UDP, l'allocation appartient au quintuplet, le Refresh doit donc partir
    du même socket ; en TCP et TLS, de la même connexion.

    `deadline` est une heure de `time.monotonic()` : chaque attente se borne
    au temps qui reste, et TimeoutError part quand il n'en reste plus."""

    def __init__(self, host, port, transport, deadline, cafile, server_name):
        self.transport = transport
        self.deadline = deadline
        kind = socket.SOCK_DGRAM if transport == "udp" else socket.SOCK_STREAM
        family, _t, _p, _c, address = _resolve(host, port, kind, deadline)
        self.sock = socket.socket(family, kind)
        try:
            self.sock.settimeout(self._remaining(deadline))
            self.sock.connect(address)
            if transport == "tls":
                context = ssl.create_default_context(cafile=cafile)
                self.sock = context.wrap_socket(
                    self.sock, server_hostname=server_name or host
                )
        except BaseException:
            self.sock.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.sock.close()

    @staticmethod
    def _remaining(deadline):
        left = deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError("budget épuisé")
        return left

    def exchange(self, kind, attributes, key, deadline=None):
        """Envoie une requête et rend (réponse décodée, octets bruts) de la
        même transaction. `attributes` est déjà encodé, ou une fonction de
        l'identifiant de transaction quand un attribut en dépend
        (XOR-PEER-ADDRESS d'un pair IPv6)."""
        deadline = min(deadline or self.deadline, self.deadline)
        txid = os.urandom(12)
        if callable(attributes):
            attributes = attributes(txid)
        request = seal(kind, txid, attributes, key)
        if self.transport == "udp":
            return self._exchange_udp(request, txid, deadline)
        return self._exchange_stream(request, txid, deadline)

    def _exchange_udp(self, request, txid, deadline):
        rto = _RTO
        self.sock.send(request)
        resend_at = time.monotonic() + rto
        while True:
            left = self._remaining(deadline)
            if time.monotonic() >= resend_at:
                self.sock.send(request)
                rto *= 2
                resend_at = time.monotonic() + rto
            self.sock.settimeout(
                max(0.001, min(left, resend_at - time.monotonic()))
            )
            try:
                data = self.sock.recv(65535)
            except TimeoutError:
                continue
            try:
                msg = decode(data)
            except ValueError:
                continue
            if msg.txid == txid and (msg.is_success or msg.is_error):
                return msg, data

    def _exchange_stream(self, request, txid, deadline):
        self.sock.settimeout(self._remaining(deadline))
        self.sock.sendall(request)
        while True:
            head = self._read(20, deadline)
            body = self._read(struct.unpack("!H", head[2:4])[0], deadline)
            msg = decode(head + body)
            if msg.txid == txid and (msg.is_success or msg.is_error):
                return msg, head + body

    def _read(self, n, deadline):
        data = b""
        while len(data) < n:
            self.sock.settimeout(self._remaining(deadline))
            chunk = self.sock.recv(n - len(data))
            if not chunk:
                raise ConnectionResetError("flux fermé par le serveur")
            data += chunk
        return data


def _check_transport(transport):
    if transport not in TRANSPORTS:
        raise ValueError(f"transport inconnu : {transport!r}")


def binding(
    host: str, port: int, transport: str = "udp", timeout: float = 5.0
) -> tuple[str, int] | None:
    """Requête STUN Binding ; rend l'adresse (hôte, port) vue par le serveur,
    ou None sans réponse valable. En « tls », le certificat se vérifie contre
    les autorités du système et le nom `host`."""
    _check_transport(transport)
    deadline = time.monotonic() + timeout
    try:
        with _Link(host, port, transport, deadline, None, None) as link:
            msg, _raw = link.exchange(BINDING_REQUEST, b"", None)
        if not msg.is_success:
            return None
        value = msg.attr(XOR_MAPPED_ADDRESS)
        if value is not None:
            return xor_address(value, msg.txid)
        value = msg.attr(MAPPED_ADDRESS)
        return _plain_address(value) if value is not None else None
    except (OSError, ValueError):
        return None


def allocate(
    host: str,
    port: int,
    transport: str,
    username: str,
    key: bytes,
    timeout: float = 5.0,
    cafile: str | None = None,
    server_name: str | None = None,
) -> Allocation:
    """Allocation TURN authentifiée puis libérée ; voir l'en-tête du module.

    `cafile` restreint la vérification TLS à cette autorité (un certificat
    fourni) ; sans lui, les autorités du système. `server_name` est le nom
    attendu dans le certificat, `host` par défaut. ValueError pour un
    transport inconnu ; tout le reste finit dans `Allocation.error`."""
    _check_transport(transport)
    target = (host, port, transport, cafile, server_name)
    return _run(target, username, key, timeout, None)


def permission(
    host: str,
    port: int,
    transport: str,
    username: str,
    key: bytes,
    peer: str,
    timeout: float = 5.0,
    cafile: str | None = None,
    server_name: str | None = None,
) -> Allocation:
    """Allocation comme `allocate()`, puis CreatePermission vers `peer`
    (adresse IP littérale) avant la libération, dans le même budget.

    Succès : le serveur accorde le pair. Le refus du serveur rend son code,
    « 403 Forbidden » pour un pair de ses plages `denied-peer-ip` ; un
    accord sans MESSAGE-INTEGRITY juste sous la clé rend « integrity ».
    Une allocation en échec rend son erreur sans rien demander de plus.
    ValueError pour un transport inconnu ou un pair qui n'est pas une
    adresse IP."""
    _check_transport(transport)
    ipaddress.ip_address(peer)
    target = (host, port, transport, cafile, server_name)
    return _run(target, username, key, timeout, peer)


def _run(target, username, key, timeout, peer):
    """Allocation (et permission vers `peer` quand il est donné) vers
    `target` = (hôte, port, transport, cafile, server_name), chaque échec
    réseau ou TLS traduit en une valeur d'`ERRORS`."""
    host, port, transport, cafile, server_name = target
    deadline = time.monotonic() + timeout
    try:
        with _Link(
            host, port, transport, deadline, cafile, server_name
        ) as link:
            return _allocate_on(link, username, key, peer)
    except ssl.SSLError:
        return Allocation(False, None, "tls")
    except TimeoutError:
        return Allocation(False, None, "timeout")
    except ConnectionRefusedError:
        return Allocation(False, None, "refused")
    except ConnectionError:
        return Allocation(False, None, "closed")
    except ValueError:
        return Allocation(False, None, "malformed")
    except OSError:
        return Allocation(False, None, "unreachable")


def _allocate_on(link, username, key, peer=None):
    """Allocation authentifiée sur `link`, puis, avec `peer`, le
    CreatePermission de `_permit` ; l'allocation obtenue est toujours
    libérée avant de rendre le verdict."""
    transport = attribute(REQUESTED_TRANSPORT, _TRANSPORT_UDP)
    first, _raw = link.exchange(ALLOCATE_REQUEST, transport, None)
    if first.is_success:
        # Relais ouvert : n'importe qui alloue sans identifiants. C'est un
        # échec du contrôle ; l'allocation obtenue est libérée quand même.
        _release(link, b"", None)
        return Allocation(False, None, "no-auth")
    realm, nonce = first.attr(REALM), first.attr(NONCE)
    if _error_code(first) != 401 or realm is None or nonce is None:
        return Allocation(False, None, _error_text(first))

    for attempt in range(2):
        auth = (
            attribute(USERNAME, username.encode())
            + attribute(REALM, realm)
            + attribute(NONCE, nonce)
        )
        reply, raw = link.exchange(ALLOCATE_REQUEST, transport + auth, key)
        if attempt == 0 and _error_code(reply) == 438 and reply.attr(NONCE):
            nonce = reply.attr(NONCE)
            realm = reply.attr(REALM) or realm
            continue
        break
    if reply.is_error:
        return Allocation(False, None, _error_text(reply))
    if not integrity_ok(raw, key):
        _release(link, auth, key)
        return Allocation(False, None, "integrity")
    relayed = _relayed(reply)
    result = Allocation(True, relayed, None)
    if peer is not None:
        result = _permit(link, auth, key, peer, relayed)
    _release(link, auth, key)
    return result


def _permit(link, auth, key, peer, relayed):
    """CreatePermission vers `peer` sous les identifiants de l'allocation
    (`auth` : USERNAME, REALM, NONCE). Le port d'un XOR-PEER-ADDRESS est
    ignoré par le serveur (RFC 5766 §9.1) : 0."""
    reply, raw = link.exchange(
        CREATE_PERMISSION_REQUEST,
        lambda txid: attribute(XOR_PEER_ADDRESS, xor_peer(peer, 0, txid))
        + auth,
        key,
    )
    if reply.is_error:
        return Allocation(False, None, _error_text(reply))
    if not integrity_ok(raw, key):
        return Allocation(False, None, "integrity")
    return Allocation(True, relayed, None)


def _relayed(msg):
    value = msg.attr(XOR_RELAYED_ADDRESS)
    if value is None:
        raise ValueError("XOR-RELAYED-ADDRESS absent")
    return xor_address(value, msg.txid)


def _release(link, auth, key):
    """Refresh de durée 0 : libère l'allocation. Sans effet sur le verdict,
    il attend au plus `_REFRESH_WAIT` secondes et avale ses erreurs."""
    attributes = attribute(LIFETIME, struct.pack("!I", 0)) + auth
    try:
        link.exchange(
            REFRESH_REQUEST,
            attributes,
            key,
            deadline=time.monotonic() + _REFRESH_WAIT,
        )
    except (OSError, ValueError):
        pass
