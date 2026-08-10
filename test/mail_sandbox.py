#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Un vrai serveur IMAP et un vrai serveur SMTP, jetables, pour les tests.

Pourquoi : tous les autres tests courriel passent par un double
(`FakeImapTransport`, `MagicMock`). Un double ne produit que ce qu'on avait
imaginé en l'écrivant — c'est précisément par là que des bugs de protocole
sont passés jusqu'à l'utilisateur. Ce module ouvre de VRAIES sockets sur
127.0.0.1 pour que le client soit exercé sur du vrai TCP.

L'intérêt n'est pas la conformité : un serveur poli ne prouve pas grand-chose.
L'intérêt est de pouvoir SE CONDUIRE MAL à la demande — servir un en-tête en
octets 8 bits, un charset `unknown-8bit`, une connexion coupée en plein FETCH.
Ajouter une méchanceté doit rester une petite addition (une sous-classe de
`Fault`, ou de simples octets déclarés par le test), jamais un nouveau serveur.

## Le réacteur Twisted ne se redémarre pas

`reactor.run()` ne peut être appelé qu'UNE fois par processus ; après
`reactor.stop()` il refuse de repartir. `unittest` enchaîne les tests dans un
seul processus : « un réacteur par test » échouerait dès le deuxième test, et
la panne ressemble à un blocage, pas à une erreur claire.

D'où le choix ici : UN seul réacteur, démarré à la demande dans un fil de
fond, et JAMAIS arrêté avant la fin du processus. Un test n'ouvre et ne ferme
qu'un port d'écoute (`reactor.listenTCP` / `port.stopListening`). L'état
propre par test ne vient donc pas du réacteur — il vient des objets : chaque
test construit ses propres boîtes et ses propres messages, et rien n'est
partagé entre deux tests. Les tests passent donc dans n'importe quel ordre et
un par un.

`aiosmtpd.Controller` porte sa propre boucle asyncio dans un fil et n'a pas ce
problème ; il ne sait en revanche pas se lier au port 0 tel quel, voir
`SmtpSandbox`.

## Sécurité

Rien ici ne sort de la machine : on se lie à 127.0.0.1 sur le port 0 (l'OS
choisit), jamais sur un port fixe qui entrerait en collision avec ce qui
écoute déjà. Aucun trousseau, aucun `~/.erplibre`, aucun identifiant réel.
"""
from __future__ import annotations

import atexit
import email
import logging
import re
import socket
import threading
import unittest
import warnings
from dataclasses import dataclass, field
from io import BytesIO

from twisted.cred import checkers, portal
from twisted.internet import protocol
from twisted.internet.threads import blockingCallFromThread
from twisted.mail import imap4
from zope.interface import implementer

from script.todo.mail.accounts import Account, ServerConf

REACTOR_START_TIMEOUT = 10
SERVER_STOP_TIMEOUT = 10

USER = "moi"
PASSWORD = "secret"

# Tous les bacs à sable actuellement à l'écoute. Sert de preuve de non-fuite :
# à la fin d'un test l'ensemble doit être revenu à ce qu'il était (voir
# `TestSandboxLifecycle` dans `test_mail_live_server.py`).
LIVE_SERVERS: set = set()


# --------------------------------------------------------------------------
# Le réacteur, un seul, dans un fil de fond
# --------------------------------------------------------------------------

_reactor_lock = threading.Lock()
_reactor_thread: threading.Thread | None = None


def reactor_in_thread():
    """Le réacteur global, en marche dans un fil de fond.

    Idempotent : le premier appel le démarre, les suivants le retrouvent. On
    ne l'arrête qu'à la sortie du processus (`atexit`), parce qu'un réacteur
    arrêté ne repart jamais.
    """
    global _reactor_thread
    from twisted.internet import reactor

    with _reactor_lock:
        if _reactor_thread is None:
            running = threading.Event()
            reactor.callWhenRunning(running.set)
            _reactor_thread = threading.Thread(
                target=reactor.run,
                kwargs={"installSignalHandlers": False},
                name="mail-sandbox-reactor",
                daemon=True,
            )
            _reactor_thread.start()
            if not running.wait(REACTOR_START_TIMEOUT):
                raise RuntimeError(
                    "le réacteur Twisted n'a pas démarré en"
                    f" {REACTOR_START_TIMEOUT}s"
                )
            atexit.register(_stop_reactor)
    return reactor


def _stop_reactor() -> None:
    """Arrêt de fin de processus. Le fil est `daemon` : même si le réacteur
    reste coincé, il n'empêchera pas Python de sortir."""
    global _reactor_thread
    from twisted.internet import reactor

    thread, _reactor_thread = _reactor_thread, None
    if thread is None:
        return
    try:
        reactor.callFromThread(reactor.stop)
    except Exception:
        # Le réacteur peut déjà être mort : la sortie du processus ne doit
        # jamais échouer là-dessus.
        return
    thread.join(SERVER_STOP_TIMEOUT)


# --------------------------------------------------------------------------
# Les méchancetés
# --------------------------------------------------------------------------


@dataclass
class Fault:
    """Une panne serveur déclenchée par une commande cliente.

    Ajouter une méchanceté = une sous-classe de trois lignes. `command` dit
    sur quelle commande elle se déclenche (`b"FETCH"`, `b"SELECT"`...),
    `after` combien d'occurrences on laisse passer avant de frapper — c'est
    ce qui permet de couper la connexion au milieu d'une passe plutôt qu'à
    son premier mot — et `strike()` fait le mal.

    Le déclenchement est compté, pas chronométré : aucun test ne dépend
    d'une durée, donc aucun ne devient instable sur une machine chargée.
    """

    command: bytes
    after: int = 0
    fired: int = field(default=0, init=False)

    def matches(self, command: bytes) -> bool:
        if command.upper() != self.command.upper():
            return False
        self.fired += 1
        return self.fired > self.after

    def strike(self, server, tag) -> None:
        raise NotImplementedError


@dataclass
class DropConnection(Fault):
    """Le serveur raccroche sans un mot, la commande restée sans réponse.

    C'est la panne réseau ordinaire — coupure Wi-Fi, pare-feu, serveur qui
    redémarre — et celle qu'aucun double n'a jamais produite, puisqu'un
    double répond toujours.
    """

    def strike(self, server, tag) -> None:
        server.transport.abortConnection()


@dataclass
class RefuseCommand(Fault):
    """Le serveur répond NO. Un dossier qu'on n'a pas le droit de lire, un
    quota dépassé : le client doit continuer sur les autres dossiers."""

    text: bytes = b"Sandbox refuses this command"

    def strike(self, server, tag) -> None:
        server.sendNegativeResponse(tag, self.text)


# --------------------------------------------------------------------------
# Le contenu servi : des octets, tels que le test les déclare
# --------------------------------------------------------------------------


def _as_text(value) -> str:
    return (
        value.decode("ascii", "replace") if isinstance(value, bytes) else value
    )


def _as_bytes(value) -> bytes:
    return (
        value.encode("ascii", "replace") if isinstance(value, str) else value
    )


def _split_header_lines(raw: bytes) -> list[bytes]:
    """Les lignes d'en-tête de `raw`, repliements compris, terminées en CRLF.

    On accepte le LF seul en entrée : c'est ce que rend `as_bytes()`, donc ce
    que le client dépose vraiment par APPEND. Découper sur le seul CRLF
    rendrait alors le message ENTIER comme un unique en-tête, sans rien lever.
    Le terminateur rendu, lui, est toujours CRLF — c'est le format du fil.
    """
    head = re.split(rb"\r?\n\r?\n", raw, maxsplit=1)[0]
    lines: list[bytes] = []
    for line in re.split(rb"\r?\n", head):
        if not line:
            continue
        if line[:1] in (b" ", b"\t") and lines:
            lines[-1] += b"\r\n" + line
        else:
            lines.append(line)
    return [line + b"\r\n" for line in lines]


@implementer(imap4.IMessage, imap4.IMessageFile)
class SandboxMessage:
    """Un message servi VERBATIM, tel que le test l'a écrit.

    `IMessageFile` (une seule méthode, `open()`) est ce qui rend possible de
    servir des octets hostiles : sur un FETCH du message entier, Twisted
    recopie ce flux tel quel au lieu de repasser par son chemin MIME, qui
    finit en `networkString()` → `.encode("ascii")` et refuserait tout octet
    8 bits.
    """

    def __init__(self, uid: int, raw: bytes, flags=(), internal_date=None):
        self.uid = uid
        self.raw = raw
        self.flags = list(flags)
        self.internal_date = internal_date or b"06-Aug-2026 10:00:00 +0000"
        self.parsed = email.message_from_bytes(raw)

    # -- IMessagePart / IMessage ----------------------------------------

    def getUID(self) -> int:
        return self.uid

    def getFlags(self) -> list:
        return list(self.flags)

    def getInternalDate(self) -> bytes:
        return self.internal_date

    def getHeaders(self, negate, *names) -> dict:
        """Les en-têtes en `str` — ce que Twisted attend (il fait
        `v.splitlines()`, donc surtout pas un `email.header.Header`).

        Les NOMS demandés, eux, arrivent en OCTETS depuis le serveur
        (`IMAP4Server.spew_body` passe `part.header.fields`), alors que les
        recherches internes (`search_SUBJECT`...) les passent en `str`. Une
        comparaison sur un seul des deux types rend un dictionnaire vide —
        sans erreur, et donc sans rien pour la faire remarquer : le client ne
        voit qu'un message sans sujet ni date.
        """
        wanted = {_as_text(n).upper() for n in names}
        return {
            key: str(value)
            for key, value in self.parsed.items()
            if (
                (key.upper() not in wanted)
                if negate
                else (key.upper() in wanted)
            )
        }

    def raw_header_block(self, negate, fields) -> bytes:
        """Les mêmes en-têtes, mais en OCTETS bruts.

        Twisted ne sait pas les servir : `_formatHeaders` finit par
        `networkString()`, donc `.encode("ascii")`, et lève sur le moindre
        octet 8 bits. Or c'est exactement ce qu'un vrai serveur nous a
        envoyé le jour du bug. `SandboxIMAP4Server.spew_body` bascule ici
        quand le bloc n'est pas ASCII (voir sa docstring).
        """
        wanted = {_as_bytes(f).upper() for f in fields}
        out = []
        for line in _split_header_lines(self.raw):
            name = line.split(b":", 1)[0].strip().upper()
            if (name not in wanted) if negate else (name in wanted):
                out.append(line)
        return b"".join(out) + b"\r\n"

    def open(self):
        return BytesIO(self.raw)

    def getBodyFile(self):
        parts = re.split(rb"\r?\n\r?\n", self.raw, maxsplit=1)
        return BytesIO(parts[1] if len(parts) > 1 else b"")

    def getSize(self) -> int:
        return len(self.raw)

    def isMultipart(self) -> bool:
        return self.parsed.is_multipart()

    def getSubPart(self, part):
        raise TypeError("le bac à sable ne sert pas de sous-partie")


@implementer(imap4.IMailbox, imap4.IMailboxInfo)
class SandboxMailbox:
    def __init__(self, name: str, uidvalidity: int = 42):
        self.name = name
        self.uidvalidity = uidvalidity
        self.messages: list[SandboxMessage] = []
        self.listeners: list = []
        self.appended: list[tuple[bytes, tuple]] = []

    # -- écriture par le test -------------------------------------------

    def deliver(self, raw: bytes, flags=(), uid: int | None = None):
        message = SandboxMessage(
            uid if uid is not None else self.getUIDNext(), raw, flags
        )
        self.messages.append(message)
        return message

    def _max_uid(self) -> int:
        return max((m.uid for m in self.messages), default=0)

    # -- IMailbox --------------------------------------------------------

    def getFlags(self) -> list:
        return ["\\Seen", "\\Answered", "\\Flagged", "\\Deleted", "\\Draft"]

    def getUIDValidity(self) -> int:
        return self.uidvalidity

    def getUIDNext(self) -> int:
        return self._max_uid() + 1

    def getUID(self, message: int) -> int:
        return self.messages[message - 1].uid

    def getMessageCount(self) -> int:
        return len(self.messages)

    def getRecentCount(self) -> int:
        return 0

    def getUnseenCount(self) -> int:
        return sum(1 for m in self.messages if "\\Seen" not in m.flags)

    def isWriteable(self) -> bool:
        return True

    def getHierarchicalDelimiter(self) -> str:
        return "."

    def requestStatus(self, names):
        return imap4.statusRequestHelper(self, names)

    def addListener(self, listener) -> None:
        self.listeners.append(listener)

    def removeListener(self, listener) -> None:
        if listener in self.listeners:
            self.listeners.remove(listener)

    def addMessage(self, body, flags=(), date=None):
        """APPEND. Doit rendre un `Deferred` et non un entier : Twisted fait
        `d.addCallback(...)` sur le résultat sans le passer par
        `maybeDeferred`, et un entier y devient un « Server error encountered
        while opening mailbox » — un message qui désigne le mauvais coupable.
        """
        from twisted.internet import defer

        raw = body.read() if hasattr(body, "read") else body
        self.appended.append((raw, tuple(flags)))
        self.deliver(raw, flags)
        return defer.succeed(len(self.messages))

    def fetch(self, messages, uid):
        """`messages` est un `MessageSet` : il faut lui donner sa borne haute
        avant de l'interroger, sinon `*` ne veut rien dire."""
        if uid:
            messages.last = self._max_uid()
            return [(m.uid, m) for m in self.messages if m.uid in messages]
        messages.last = len(self.messages)
        return [
            (index + 1, m)
            for index, m in enumerate(self.messages)
            if index + 1 in messages
        ]

    def store(self, messages, flags, mode, uid):
        out = {}
        for number, message in self.fetch(messages, uid):
            current = set(message.flags)
            if mode < 0:
                current -= set(flags)
            elif mode > 0:
                current |= set(flags)
            else:
                current = set(flags)
            message.flags = sorted(current)
            out[number] = message.flags
        return out

    def expunge(self) -> list:
        return []

    def destroy(self) -> None:
        pass


@implementer(imap4.IAccount)
class SandboxIMAPAccount:
    def __init__(self):
        self.boxes: dict[str, SandboxMailbox] = {}

    def add(self, name: str, uidvalidity: int = 42) -> SandboxMailbox:
        box = SandboxMailbox(name, uidvalidity)
        self.boxes[name] = box
        return box

    def _key(self, path: str) -> str:
        # INBOX est insensible à la casse (RFC 3501), le reste ne l'est pas.
        return "INBOX" if path.upper() == "INBOX" else path

    def listMailboxes(self, ref, wildcard):
        return list(self.boxes.items())

    def select(self, path, rw=True):
        return self.boxes.get(self._key(path))

    def create(self, path):
        self.add(self._key(path))
        return True

    def delete(self, path):
        self.boxes.pop(self._key(path), None)

    def rename(self, old, new):
        self.boxes[self._key(new)] = self.boxes.pop(self._key(old))

    def isSubscribed(self, name):
        return True

    def subscribe(self, name):
        return True

    def unsubscribe(self, name):
        return True


@implementer(portal.IRealm)
class _SandboxRealm:
    def __init__(self, account: SandboxIMAPAccount):
        self.account = account

    def requestAvatar(self, avatarId, mind, *interfaces):
        return imap4.IAccount, self.account, lambda: None


# --------------------------------------------------------------------------
# Le serveur IMAP
# --------------------------------------------------------------------------


class SandboxIMAP4Server(imap4.IMAP4Server):
    def __init__(self, sandbox: "ImapSandbox"):
        # `IMAP4Server.__init__` prend (chal, contextFactory, scheduler) et
        # NON un portal : celui-ci s'affecte après coup.
        super().__init__()
        self.sandbox = sandbox

    def connectionMade(self):
        self.sandbox.connections.add(self)
        super().connectionMade()

    def connectionLost(self, reason):
        self.sandbox.connections.discard(self)
        super().connectionLost(reason)

    def dispatchCommand(self, tag, cmd, rest, uid=None):
        """Le seul point où les méchancetés s'insèrent.

        `UID FETCH ...` passe ici deux fois — une pour `UID`, une pour le
        `FETCH` interne — ce qui permet à un `Fault` de viser précisément
        l'une ou l'autre.
        """
        for fault in self.sandbox.faults:
            if fault.matches(cmd):
                fault.strike(self, tag)
                return None
        return super().dispatchCommand(tag, cmd, rest, uid)

    def spew_body(self, part, id, msg, _w=None, _f=None):
        """Sert les en-têtes en octets bruts quand ils ne sont pas ASCII.

        Par défaut on laisse faire Twisted : le bac à sable est un serveur
        POLI, et les tests doivent traverser son vrai code. Mais son
        `_formatHeaders` se termine par `networkString()` — un `.encode(
        "ascii")` — et lève sur le moindre octet 8 bits, que tout vrai
        serveur transmet pourtant sans broncher. Dans ce seul cas on écrit
        le littéral nous-mêmes, avec les octets déclarés par le test. Le
        cadrage du littéral reste celui de Twisted (`imap4._literal`).
        """
        block = None
        if part.header is not None:
            raw = getattr(msg, "raw_header_block", None)
            if raw is not None:
                block = raw(part.header.negate, part.header.fields)
        if block is None or _is_ascii(block):
            return super().spew_body(part, id, msg, _w, _f)
        write = _w if _w is not None else self.transport.write
        write(bytes(part) + b" " + imap4._literal(block))
        return None


def _is_ascii(data: bytes) -> bool:
    try:
        data.decode("ascii")
    except UnicodeDecodeError:
        return False
    return True


class _SandboxFactory(protocol.Factory):
    def __init__(self, sandbox: "ImapSandbox"):
        self.sandbox = sandbox

    def buildProtocol(self, addr):
        server = SandboxIMAP4Server(self.sandbox)
        server.factory = self
        server.portal = self.sandbox.portal
        return server


class ImapSandbox:
    """Un serveur IMAP jetable, sur un port éphémère de 127.0.0.1.

    Usage :

        imap = ImapSandbox()
        imap.folder("INBOX").deliver(RAW_BYTES, flags=["\\\\Seen"])
        imap.fail(DropConnection(b"FETCH", after=1))
        imap.start()
        ...
        imap.stop()

    `MailSandboxCase.imap_server()` fait tout cela et branche l'arrêt sur
    `addCleanup`, qui s'exécute même quand le test échoue.
    """

    def __init__(self):
        self.account = SandboxIMAPAccount()
        self.faults: list[Fault] = []
        self.connections: set = set()
        self.port = 0
        self._listening = None
        checker = checkers.InMemoryUsernamePasswordDatabaseDontUse()
        checker.addUser(USER.encode(), PASSWORD.encode())
        self.portal = portal.Portal(_SandboxRealm(self.account))
        self.portal.registerChecker(checker)

    # -- déclaration du contenu -----------------------------------------

    def folder(self, name: str, uidvalidity: int = 42) -> SandboxMailbox:
        return self.account.boxes.get(name) or self.account.add(
            name, uidvalidity
        )

    def fail(self, fault: Fault) -> Fault:
        self.faults.append(fault)
        return fault

    # -- cycle de vie -----------------------------------------------------

    def start(self) -> "ImapSandbox":
        reactor = reactor_in_thread()
        self._listening = blockingCallFromThread(
            reactor,
            reactor.listenTCP,
            0,
            _SandboxFactory(self),
            interface="127.0.0.1",
        )
        self.port = self._listening.getHost().port
        LIVE_SERVERS.add(self)
        return self

    def stop(self) -> None:
        """Ferme le port ET coupe les connexions encore ouvertes.

        `stopListening` seul cesse d'ACCEPTER : une session cliente restée
        ouverte garderait un descripteur et un protocole vivants d'un test à
        l'autre.
        """
        listening, self._listening = self._listening, None
        LIVE_SERVERS.discard(self)
        if listening is None:
            return
        from twisted.internet import reactor

        def close():
            for server in list(self.connections):
                server.transport.abortConnection()
            return listening.stopListening()

        blockingCallFromThread(reactor, close)


# --------------------------------------------------------------------------
# Le serveur SMTP
# --------------------------------------------------------------------------


@dataclass
class SentMessage:
    """Ce qui est VRAIMENT sorti : l'enveloppe et les octets sur le fil."""

    mail_from: str
    rcpt_tos: list
    content: bytes

    def headers(self):
        return email.message_from_bytes(self.content)


class _CaptureHandler:
    def __init__(self):
        self.messages: list[SentMessage] = []

    async def handle_DATA(self, server, session, envelope):
        self.messages.append(
            SentMessage(
                mail_from=envelope.mail_from,
                rcpt_tos=list(envelope.rcpt_tos),
                content=bytes(envelope.content),
            )
        )
        return "250 Message accepted for delivery"


class SmtpSandbox:
    """Un serveur SMTP jetable qui capture ce qu'on lui remet.

    `aiosmtpd.Controller` ne sait pas se lier au port 0 : après `start()` il
    rouvre une connexion de vérification vers `self.port`, qui vaut encore 0.
    On relit le vrai numéro sur la socket avant cette vérification — c'est le
    seul point à corriger.
    """

    def __init__(self, *, require_auth: bool = False):
        from aiosmtpd.controller import Controller
        from aiosmtpd.smtp import AuthResult, LoginPassword

        # Deux bruits d'`aiosmtpd` sans objet ici, et qui masqueraient les
        # vraies pannes dans la sortie des tests : un WARNING à chaque
        # authentification réussie (« Session.login_data is deprecated »), et
        # un avertissement sur AUTH sans TLS — justifié en production, sans
        # objet pour un serveur qu'on vient de démarrer soi-même sur la
        # boucle locale. Le filtre est posé ici et non à l'import : le
        # lanceur `unittest` réinitialise `warnings.filters` avant de courir.
        logging.getLogger("mail.log").setLevel(logging.ERROR)
        warnings.filterwarnings(
            "ignore",
            message="Requiring AUTH while not requiring TLS",
            category=UserWarning,
        )

        def authenticate(server, session, envelope, mechanism, auth_data):
            ok = isinstance(auth_data, LoginPassword) and (
                auth_data.login == USER.encode()
                and auth_data.password == PASSWORD.encode()
            )
            if ok:
                return AuthResult(success=True, auth_data=auth_data)
            # `handled` vaut True PAR DÉFAUT, et veut dire « j'ai déjà répondu
            # au client moi-même ». Un simple `AuthResult(success=False)`
            # laisse donc `aiosmtpd` muet : le client attend une réponse qui
            # ne vient jamais et le test se bloque jusqu'au délai de la
            # socket, sans rien dire de la cause.
            return AuthResult(success=False, handled=False)

        class _Port0Controller(Controller):
            def _trigger_server(self):
                if self.port == 0 and self.server is not None:
                    self.port = self.server.sockets[0].getsockname()[1]
                super()._trigger_server()

        self.handler = _CaptureHandler()
        self.controller = _Port0Controller(
            self.handler,
            hostname="127.0.0.1",
            port=0,
            authenticator=authenticate,
            auth_required=require_auth,
            auth_require_tls=False,
        )
        self.port = 0
        self._running = False

    @property
    def messages(self) -> list[SentMessage]:
        return self.handler.messages

    def start(self) -> "SmtpSandbox":
        # Marqué vivant AVANT de démarrer : `Controller.start()` lance déjà
        # son fil avant de pouvoir échouer, et le nettoyage doit passer
        # derrière lui même dans ce cas-là.
        self._running = True
        LIVE_SERVERS.add(self)
        self.controller.start()
        self.port = self.controller.port
        return self

    def stop(self) -> None:
        """Idempotent : un test peut vouloir tuer son serveur en plein
        milieu, et le nettoyage repassera derrière lui de toute façon."""
        if not self._running:
            return
        self._running = False
        LIVE_SERVERS.discard(self)
        self.controller.stop(no_assert=True)


# --------------------------------------------------------------------------
# Le compte, et le socle de test
# --------------------------------------------------------------------------


def sandbox_account(
    imap_port: int = 0,
    smtp_port: int = 0,
    *,
    name: str = "bac-a-sable",
    address: str = "moi@example.ca",
    display_name: str = "",
    sent_folder: str = "INBOX.Sent",
) -> Account:
    """Un `Account` réel pointé sur les serveurs jetables.

    `security="none"` : on parle en clair sur la boucle locale, à un serveur
    qu'on vient de démarrer soi-même. Rien de tout cela ne quitte la machine.
    """
    return Account(
        name=name,
        email=address,
        display_name=display_name,
        preset="generic",
        imap=ServerConf(
            host="127.0.0.1", port=imap_port, security="none", user=USER
        ),
        smtp=ServerConf(
            host="127.0.0.1", port=smtp_port, security="none", user=USER
        ),
        secret_ref="kdbx:ERPLibre/Mail/bac-a-sable",
        cache_mode="clear",
        sent_folder=sent_folder,
    )


def close_imap_client(transport) -> None:
    """Ferme la socket cliente, quoi qu'il soit arrivé pendant le test.

    `ImaplibTransport.logout()` est best-effort : sur une connexion déjà
    morte — exactement ce que `DropConnection` produit — `imaplib.logout()`
    lève avant d'atteindre son propre `shutdown()`, et le descripteur reste
    ouvert jusqu'au ramasse-miettes. Acceptable dans le TUI, pas dans une
    suite de tests où il s'accumulerait.
    """
    transport.logout()
    try:
        transport.client.shutdown()
    except Exception:
        # Déjà fermée : c'est le cas normal quand `logout()` a réussi.
        pass


def port_is_closed(port: int, timeout: float = 0.5) -> bool:
    """Vrai si plus rien n'écoute sur ce port de la boucle locale."""
    with socket.socket() as probe:
        probe.settimeout(timeout)
        return probe.connect_ex(("127.0.0.1", port)) != 0


class MailSandboxCase(unittest.TestCase):
    """Le socle : tout serveur démarré ici meurt avec le test.

    L'arrêt passe par `addCleanup`, enregistré AVANT le démarrage :
    `unittest` l'exécute quel que soit le sort du test — succès, échec ou
    erreur — et même si `start()` lève à mi-chemin. Une socket d'écoute
    oubliée ou un fil coincé empoisonneraient toute la suite.
    """

    def imap_server(self) -> ImapSandbox:
        sandbox = ImapSandbox()
        self.addCleanup(sandbox.stop)
        return sandbox.start()

    def smtp_server(self, **kwargs) -> SmtpSandbox:
        sandbox = SmtpSandbox(**kwargs)
        self.addCleanup(sandbox.stop)
        return sandbox.start()

    def temp_store(self, account):
        """Un cache SQLite dans un dossier temporaire, jamais le vrai."""
        import tempfile
        from pathlib import Path

        from script.todo.mail.store import Store

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = Store(account, mode="clear", base=Path(tmp.name))
        self.addCleanup(store.close)
        store.open()
        return store

    def imap_transport(self, sandbox: ImapSandbox, account=None):
        """Le VRAI client (`imap_transport.connect`), branché sur le bac à
        sable — connexion et LOGIN compris."""
        from script.todo.mail import imap_transport

        account = account or sandbox_account(imap_port=sandbox.port)
        transport = imap_transport.connect(account, PASSWORD)
        self.addCleanup(close_imap_client, transport)
        return transport
