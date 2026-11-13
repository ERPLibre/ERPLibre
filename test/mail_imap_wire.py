#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Un serveur IMAP scripté, pour faire jouer le VRAI `imaplib` de
l'interpréteur courant contre un serveur dont le test connaît chaque
octet.

Il parle une ligne par commande, sans littéral : accueil sans code
`[CAPABILITY …]`, `CAPABILITY`, `LOGIN` (identifiants non vérifiés),
`SELECT` (une seule boîte, quel que soit son nom), `UID FETCH`,
`UID STORE` (`+FLAGS`, avec ou sans `(UNCHANGEDSINCE m)`), `NOOP` et
`LOGOUT` ; tout autre verbe reçoit `BAD`. `hold` retient la réponse d'une
commande jusqu'à l'arrivée de la suivante : c'est la réponse en retard
d'un serveur lent, sans aucune horloge côté serveur.

Tout se passe sur `127.0.0.1`, port éphémère. N'importe que la
bibliothèque standard : les tests du noyau le chargent aussi sous le
Python d'Odoo.
"""

import imaplib
import re
import socket
import threading
import unittest
from dataclasses import dataclass

USER = "boite.regles@example.org"
PASSWORD = "secret-de-fil"
# Délai de chaque lecture côté serveur, en secondes.
SERVER_TIMEOUT = 10
UIDVALIDITY = 42
# Période à laquelle le fil d'écoute relit l'événement d'arrêt.
ACCEPT_POLL = 0.05

_STORE_RE = re.compile(
    rb"^(\d+)\s+(?:\(UNCHANGEDSINCE\s+(\d+)\)\s+)?\+FLAGS\s+\(([^)]*)\)$",
    re.IGNORECASE,
)
_FETCH_RE = re.compile(rb"^([\d,]+)\s+\((.*)\)$")


@dataclass
class WireMessage:
    flags: list
    modseq: int


class WireServer:
    """Le serveur : un fil d'acceptation, un fil par connexion.

    `messages` (uid → `WireMessage`) est partagé par les connexions ;
    `received` note chaque ligne de commande reçue, sans CRLF, AVANT que
    sa réponse ne parte.
    """

    def __init__(
        self,
        *,
        condstore: bool = True,
        condstore_after_login: bool = False,
        keywords: bool = True,
    ) -> None:
        self.condstore = condstore
        self.condstore_after_login = condstore_after_login
        self.keywords = keywords
        self.messages = {
            1: WireMessage(flags=[], modseq=5),
            2: WireMessage(flags=[], modseq=6),
        }
        self.received: list[bytes] = []
        self.port = 0
        self._lock = threading.Lock()
        self._recu = threading.Condition(self._lock)
        self._arret = threading.Event()
        self._retenir: set[str] = set()
        self._listen = None
        self._threads: list[threading.Thread] = []
        self._sockets: list = []

    # -- pilotage par le test ----------------------------------------

    def start(self) -> "WireServer":
        ecoute = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        ecoute.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        ecoute.bind(("127.0.0.1", 0))
        ecoute.listen(8)
        # `accept` bloqué ne se réveille pas quand un autre fil ferme la
        # socket : il revient regarder l'événement d'arrêt à chaque délai.
        ecoute.settimeout(ACCEPT_POLL)
        self._listen = ecoute
        self.port = ecoute.getsockname()[1]
        fil = threading.Thread(target=self._accept, daemon=True)
        self._threads.append(fil)
        fil.start()
        return self

    def stop(self) -> None:
        """Idempotent : ferme chaque connexion et l'écoute, joint les fils.

        Un fil qui survit au délai de jonction est un défaut du serveur, et
        lève ici plutôt que d'attendre."""
        self._arret.set()
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
        if self._listen is not None:
            try:
                self._listen.close()
            except OSError:
                pass
        for fil in list(self._threads):
            fil.join(timeout=2)
            assert not fil.is_alive(), "fil du serveur scripté bloqué"

    def wait_received(self, count: int, timeout: float = 0.5) -> bool:
        """Vrai dès que `count` lignes sont notées ; faux au bout de
        `timeout` secondes."""
        with self._recu:
            return self._recu.wait_for(
                lambda: len(self.received) >= count, timeout=timeout
            )

    def hold(self, verb: str) -> None:
        """Retient la réponse COMPLÈTE de la prochaine commande `verb` ;
        elle part juste avant la réponse de la commande suivante."""
        with self._lock:
            self._retenir.add(verb.upper())

    def touch(self, uid: int, flag: str) -> None:
        """Un autre client pose `flag` sur `uid` : son MODSEQ monte."""
        with self._lock:
            message = self.messages[uid]
            if flag not in message.flags:
                message.flags.append(flag)
            message.modseq = self._plus_haut() + 1

    def verbs(self) -> list[str]:
        """Le verbe de chaque ligne reçue, `UID` suivi de sa commande."""
        with self._lock:
            lignes = list(self.received)
        return [_verbe(ligne) for ligne in lignes]

    def connect(self, testcase) -> imaplib.IMAP4:
        """Un vrai client `imaplib` authentifié, refermé au nettoyage.

        Jamais une socket bloquante : un défaut du serveur fait échouer le
        test en 5 s au lieu de le figer."""
        client = imaplib.IMAP4("127.0.0.1", self.port, timeout=5)

        def fermer():
            try:
                client.shutdown()
            except Exception:
                # Déjà fermé par le test : rien à rendre.
                pass

        testcase.addCleanup(fermer)
        client.login(USER, PASSWORD)
        return client

    # -- service -----------------------------------------------------

    def _plus_haut(self) -> int:
        return max((m.modseq for m in self.messages.values()), default=0)

    def _accept(self) -> None:
        ecoute = self._listen
        while not self._arret.is_set():
            try:
                conn, _ = ecoute.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            conn.settimeout(SERVER_TIMEOUT)
            with self._lock:
                if self._arret.is_set():
                    conn.close()
                    return
                self._sockets.append(conn)
            fil = threading.Thread(
                target=self._serve, args=(conn,), daemon=True
            )
            self._threads.append(fil)
            fil.start()

    def _serve(self, conn) -> None:
        try:
            self._dialogue(conn)
        except (OSError, ValueError):
            # Connexion fermée sous le fil, par le client ou par `stop`.
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def _dialogue(self, conn) -> None:
        fichier = conn.makefile("rb")
        conn.sendall(b"* OK ready\r\n")
        session = {"auth": False}
        retenue = b""
        while True:
            brute = fichier.readline()
            if not brute:
                return
            ligne = brute.rstrip(b"\r\n")
            with self._recu:
                self.received.append(ligne)
                self._recu.notify_all()
            reponse, fin = self._repondre(ligne, session)
            verbe = _verbe(ligne)
            with self._lock:
                retenir = verbe in self._retenir
                self._retenir.discard(verbe)
            if retenir:
                retenue += reponse
                continue
            conn.sendall(retenue + reponse)
            retenue = b""
            if fin:
                return

    def _repondre(self, ligne: bytes, session: dict) -> tuple[bytes, bool]:
        morceaux = ligne.split(b" ", 2)
        tag = morceaux[0]
        verbe = morceaux[1].upper() if len(morceaux) > 1 else b""
        reste = morceaux[2] if len(morceaux) > 2 else b""
        if verbe == b"CAPABILITY":
            caps = b"IMAP4rev1 AUTH=PLAIN"
            if self.condstore and (
                not self.condstore_after_login or session["auth"]
            ):
                caps += b" CONDSTORE"
            return (
                b"* CAPABILITY " + caps + b"\r\n" + tag + b" OK done\r\n",
                False,
            )
        if verbe == b"LOGIN":
            session["auth"] = True
            return tag + b" OK logged in\r\n", False
        if verbe == b"SELECT":
            return self._select(tag), False
        if verbe == b"UID":
            sous, _, args = reste.partition(b" ")
            sous = sous.upper()
            if sous == b"FETCH":
                return self._fetch(tag, args), False
            if sous == b"STORE":
                return self._store(tag, args), False
            return tag + b" BAD unknown\r\n", False
        if verbe == b"NOOP":
            return tag + b" OK done\r\n", False
        if verbe == b"LOGOUT":
            return b"* BYE bye\r\n" + tag + b" OK done\r\n", True
        return tag + b" BAD unknown\r\n", False

    def _rang(self, uid: int) -> int:
        return sorted(self.messages).index(uid) + 1

    def _select(self, tag: bytes) -> bytes:
        with self._lock:
            nombre = len(self.messages)
            suivant = max(self.messages, default=0) + 1
            plus_haut = self._plus_haut()
        sortie = (
            f"* {nombre} EXISTS\r\n"
            f"* OK [UIDVALIDITY {UIDVALIDITY}] u\r\n"
            f"* OK [UIDNEXT {suivant}] n\r\n"
        ).encode()
        if self.condstore:
            sortie += f"* OK [HIGHESTMODSEQ {plus_haut}] h\r\n".encode()
        return sortie + tag + b" OK [READ-WRITE] done\r\n"

    def _fetch(self, tag: bytes, args: bytes) -> bytes:
        trouve = _FETCH_RE.match(args)
        if not trouve:
            return tag + b" BAD fetch\r\n"
        avec_modseq = self.condstore and b"MODSEQ" in trouve.group(2).upper()
        sortie = b""
        with self._lock:
            for morceau in trouve.group(1).split(b","):
                uid = int(morceau)
                message = self.messages.get(uid)
                if message is None:
                    continue
                texte = f"UID {uid} FLAGS ({' '.join(message.flags)})"
                if avec_modseq:
                    texte += f" MODSEQ ({message.modseq})"
                sortie += f"* {self._rang(uid)} FETCH ({texte})\r\n".encode()
        return sortie + tag + b" OK done\r\n"

    def _store(self, tag: bytes, args: bytes) -> bytes:
        trouve = _STORE_RE.match(args)
        if not trouve:
            return tag + b" BAD store\r\n"
        uid = int(trouve.group(1))
        depuis = trouve.group(2)
        if depuis is not None and not self.condstore:
            return tag + b" BAD no condstore\r\n"
        with self._lock:
            message = self.messages.get(uid)
            if message is None:
                return tag + b" OK done\r\n"
            if depuis is not None and message.modseq > int(depuis):
                return (
                    tag
                    + f" OK [MODIFIED {uid}] conditional store failed\r\n".encode()
                )
            for drapeau in trouve.group(3).decode("ascii").split():
                if not self.keywords and not drapeau.startswith("\\"):
                    continue
                if drapeau not in message.flags:
                    message.flags.append(drapeau)
            message.modseq = self._plus_haut() + 1
            texte = f"UID {uid}"
            if self.condstore:
                texte += f" MODSEQ ({message.modseq})"
            texte += f" FLAGS ({' '.join(message.flags)})"
            ligne = f"* {self._rang(uid)} FETCH ({texte})\r\n".encode()
        return ligne + tag + b" OK done\r\n"


def _verbe(ligne: bytes) -> str:
    """« UID FETCH », « UID STORE », ou le verbe seul, en majuscules."""
    morceaux = ligne.split(b" ", 3)
    verbe = morceaux[1].upper() if len(morceaux) > 1 else b""
    if verbe == b"UID" and len(morceaux) > 2:
        verbe += b" " + morceaux[2].upper()
    return verbe.decode("ascii", "replace")


class WireCase(unittest.TestCase):
    """Démarre un `WireServer` par test, réglé par `SERVER`."""

    SERVER: dict = {}

    def setUp(self):
        super().setUp()
        self.server = WireServer(**self.SERVER).start()
        self.addCleanup(self.server.stop)
