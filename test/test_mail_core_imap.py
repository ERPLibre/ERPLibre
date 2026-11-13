#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce que le noyau lit d'IMAP et la revendication sur une connexion
`imaplib` nue, sans le transport du client.

Le double du client applique l'arité d'`uid()` des versions récentes
d'`imaplib`, qui refusent un STORE à plus de trois arguments. Le serveur
scripté de `mail_imap_wire` fait jouer le VRAI `imaplib` de
l'interpréteur courant : la revendication et le lien abandonné y sont
éprouvés sous chaque version.

N'importe que la bibliothèque standard, `erplibre_mail_core` et
`mail_imap_wire`.
"""

import calendar
import imaplib
import sys
import time
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
if str(RACINE / "script" / "lib" / "erplibre_mail_core") not in sys.path:
    sys.path.insert(0, str(RACINE / "script" / "lib" / "erplibre_mail_core"))
if str(RACINE / "test") not in sys.path:
    sys.path.insert(0, str(RACINE / "test"))

from erplibre_mail_core import imap  # noqa: E402
from erplibre_mail_core.claim import ClaimProbe  # noqa: E402
from erplibre_mail_core.i18n import t  # noqa: E402
from mail_imap_wire import WireCase  # noqa: E402

OWN = "boite.regles@example.org"
CAROLE = "carole.regle@example.org"


# L'arité qu'`uid()` impose à ses arguments après la commande, selon les
# versions récentes d'`imaplib`.
ARITE_UID = {"STORE": 3, "FETCH": 2, "COPY": 2}


class ClientDouble:
    """Un client `imaplib` réduit : chaque `uid()` ou `xatom()` rend la
    réponse suivante de `reponses` et note la commande.

    `uid()` refuse, comme `imaplib`, un STORE qui n'a pas exactement trois
    arguments, un FETCH ou un COPY qui n'en a pas deux. `xatom()` range les
    lignes d'une réponse OK parmi les FETCH non étiquetés, comme le vrai
    client ; toute autre réponse est rendue telle quelle."""

    def __init__(self, reponses=(), capacites=b"IMAP4rev1"):
        self.reponses = list(reponses)
        self.capacites = capacites
        self.capabilities = ("IMAP4REV1",)
        self.untagged_responses = {}
        self.appels = []

    def select(self, mailbox):
        self.untagged_responses = {"UIDVALIDITY": [b"42"], "UIDNEXT": [b"9"]}
        return "OK", [b"3"]

    def response(self, code):
        return "OK", self.untagged_responses.pop(code, [None])

    def capability(self):
        return "OK", [self.capacites]

    def _suivante(self):
        reponse = self.reponses.pop(0)
        if isinstance(reponse, BaseException):
            raise reponse
        return reponse

    def uid(self, command, *args):
        attendu = ARITE_UID.get(command.upper())
        if attendu is not None and len(args) != attendu:
            raise ValueError(f"{command} : {len(args)} arguments")
        self.appels.append((command, args))
        return self._suivante()

    def xatom(self, name, *args):
        self.appels.append((name, args))
        typ, lignes = self._suivante()
        if typ != "OK":
            return typ, lignes
        recues = [ligne for ligne in lignes if ligne is not None]
        if recues:
            self.untagged_responses.setdefault("FETCH", []).extend(recues)
        return "OK", [b"done"]


class TestImapConnection(unittest.TestCase):
    def test_claim_on_a_bare_connection(self):
        client = ClientDouble(
            [
                ("OK", [b"1 (UID 1 FLAGS (\\Seen) MODSEQ (7))"]),
                ("OK", [b"1 (UID 1 FLAGS (\\Seen $ErpLibreRule) MODSEQ (8))"]),
            ],
            capacites=b"IMAP4rev1 CONDSTORE",
        )
        connexion = imap.ImapConnection(client)
        sonde = connexion.claim_probe("INBOX", 1, uidvalidity=42)
        self.assertEqual(sonde, ClaimProbe("free", "atomic", 7))
        self.assertEqual(connexion.claim_store(1, sonde), "stored")
        self.assertEqual(
            client.appels[-1],
            (
                "UID",
                (
                    "STORE",
                    "1",
                    "(UNCHANGEDSINCE 7)",
                    "+FLAGS",
                    "($ErpLibreRule)",
                ),
            ),
        )
        # Sonde puis STORE : la ligne FETCH du STORE suffit, aucune relecture.
        self.assertEqual(len(client.appels), 2)
        self.assertNotIn("FETCH", client.untagged_responses)
        self.assertFalse(connexion._sans_condstore)

    def test_select_reads_the_mailbox_numbers(self):
        info = imap.ImapConnection(ClientDouble()).select("INBOX")
        self.assertEqual(
            (info.uidvalidity, info.uidnext, info.exists), (42, 9, 3)
        )


class TestStoreKeyword(unittest.TestCase):
    def test_a_plain_store_goes_out_through_xatom_too(self):
        client = ClientDouble(
            [
                ("OK", [b"1 (UID 1 FLAGS (\\Seen))"]),
                ("OK", [b"1 (UID 1 FLAGS (\\Seen $ErpLibreRule))"]),
            ],
            capacites=b"IMAP4rev1",
        )
        connexion = imap.ImapConnection(client)
        sonde = connexion.claim_probe("INBOX", 1, uidvalidity=42)
        self.assertEqual(sonde, ClaimProbe("free", "plain"))
        self.assertEqual(connexion.claim_store(1, sonde), "stored")
        self.assertEqual(
            client.appels[-1],
            ("UID", ("STORE", "1", "+FLAGS", "($ErpLibreRule)")),
        )

    def test_the_double_refuses_a_store_with_four_arguments(self):
        client = ClientDouble([("OK", [None])])
        with self.assertRaises(ValueError):
            client.uid(
                "STORE", "1", "(UNCHANGEDSINCE 7)", "+FLAGS", "(\\Seen)"
            )


def _apres_tag(ligne: bytes) -> bytes:
    return ligne.split(b" ", 1)[1]


class TestClaimOnTheRealImaplib(WireCase):
    """La revendication jouée par le vrai `imaplib` de l'interpréteur."""

    SERVER = {"condstore": True}

    def connexion(self):
        self.client = self.server.connect(self)
        return imap.ImapConnection(self.client)

    def test_an_atomic_claim_is_one_conditional_store(self):
        conn = self.connexion()
        sonde = conn.claim_probe("INBOX", 1, uidvalidity=42)
        self.assertEqual(sonde, ClaimProbe("free", "atomic", 5))
        self.assertEqual(conn.claim_store(1, sonde), "stored")
        derniere = self.server.received[-1]
        self.assertEqual(
            _apres_tag(derniere),
            b"UID STORE 1 (UNCHANGEDSINCE 5) +FLAGS ($ErpLibreRule)",
        )
        self.assertEqual(self.server.verbs()[-1], "UID STORE")
        self.assertIn("$ErpLibreRule", self.server.messages[1].flags)

    def test_a_change_since_the_probe_answers_modified(self):
        conn = self.connexion()
        sonde = conn.claim_probe("INBOX", 1, uidvalidity=42)
        self.server.touch(1, "\\Seen")
        self.assertEqual(conn.claim_store(1, sonde), "modified")
        self.assertEqual(self.server.messages[1].flags, ["\\Seen"])

    def test_the_store_leaves_no_fetch_for_the_next_command(self):
        conn = self.connexion()
        sonde = conn.claim_probe("INBOX", 1, uidvalidity=42)
        self.assertEqual(conn.claim_store(1, sonde), "stored")
        self.assertNotIn("FETCH", self.client.untagged_responses)
        self.assertEqual(conn.fetch_flags([2]), [(2, "")])

    def test_a_server_without_condstore_gets_a_plain_store(self):
        self.server.condstore = False
        conn = self.connexion()
        sonde = conn.claim_probe("INBOX", 1, uidvalidity=42)
        self.assertEqual(sonde, ClaimProbe("free", "plain"))
        self.assertEqual(conn.claim_store(1, sonde), "stored")
        stores = [
            ligne
            for ligne in self.server.received
            if b"UID STORE" in ligne.upper()
        ]
        self.assertEqual(len(stores), 1)
        self.assertNotIn(b"UNCHANGEDSINCE", stores[0])

    def test_a_server_that_drops_keywords_is_refused(self):
        self.server.keywords = False
        conn = self.connexion()
        sonde = conn.claim_probe("INBOX", 1, uidvalidity=42)
        self.assertEqual(conn.claim_store(1, sonde), "refused")
        self.assertEqual(self.server.messages[1].flags, [])

    def test_condstore_announced_after_login_gives_atomic(self):
        self.server.condstore_after_login = True
        conn = self.connexion()
        sonde = conn.claim_probe("INBOX", 1, uidvalidity=42)
        self.assertEqual(sonde, ClaimProbe("free", "atomic", 5))
        self.assertEqual(conn.claim_store(1, sonde), "stored")

    def test_condstore_after_login_is_read_even_if_imaplib_keeps_the_old_list(
        self,
    ):
        """Un `imaplib` qui ne relit pas les capacités après LOGIN y laisse
        la liste d'avant connexion : la sonde demande `CAPABILITY`."""
        self.server.condstore_after_login = True
        conn = self.connexion()
        self.client.capabilities = tuple(
            c for c in self.client.capabilities if c != "CONDSTORE"
        )
        repere = len(self.server.received)
        sonde = conn.claim_probe("INBOX", 1, uidvalidity=42)
        self.assertEqual(sonde.mode, "atomic")
        apres = self.server.verbs()[repere:]
        # La sonde sélectionne, demande `CAPABILITY`, puis lit le message
        # avec son MODSEQ.
        self.assertEqual(apres, ["SELECT", "CAPABILITY", "UID FETCH"])


class TestFailFastOnTheRealImaplib(WireCase):
    """`fail_fast` sur le vrai `imaplib` : un délai dépassé abandonne le
    lien, et plus rien n'est lu ni envoyé.

    Un espion sur `client.send`, posé AVANT `fail_fast`, n'est appelé que
    si le garde laisse passer : « rien n'est parti » se prouve côté
    client sans course, puis côté serveur par une attente bornée."""

    def lien(self):
        client = self.server.connect(self)
        self.envois = []
        original = client.send

        def espion(data):
            self.envois.append(data)
            return original(data)

        client.send = espion
        imap.fail_fast(client)
        client.select("INBOX")
        return client

    def expire(self, client):
        """Retient la réponse d'un NOOP, que le client attend 0,3 s."""
        self.server.hold("NOOP")
        client.sock.settimeout(0.3)
        with self.assertRaises(OSError):
            client.noop()

    def rien_ne_part(self, envois_avant):
        self.assertEqual(len(self.envois), envois_avant)
        repere = len(self.server.received)
        self.assertFalse(self.server.wait_received(repere + 1, timeout=0.3))

    def test_a_late_answer_is_never_read_as_the_next_one(self):
        client = self.lien()
        self.expire(client)
        avant = len(self.envois)
        with self.assertRaises(imaplib.IMAP4.abort):
            client.uid("FETCH", "1", "(UID FLAGS)")
        self.rien_ne_part(avant)
        self.assertEqual(self.server.verbs()[-1], "NOOP")

    def test_logout_after_a_timeout_sends_nothing_and_does_not_wait(self):
        client = self.lien()
        self.expire(client)
        avant = len(self.envois)
        debut = time.monotonic()
        with self.assertRaises(imaplib.IMAP4.abort):
            client.logout()
        self.assertLess(time.monotonic() - debut, 0.3)
        self.rien_ne_part(avant)
        self.assertNotIn("LOGOUT", self.server.verbs())

    def test_the_abort_names_the_link_and_the_cause(self):
        client = self.lien()
        self.expire(client)
        with self.assertRaises(imaplib.IMAP4.abort) as ctx:
            client.noop()
        self.assertIn(t("mail_err_link_abandoned"), str(ctx.exception))
        self.assertIn("TimeoutError", str(ctx.exception))

    def test_a_healthy_link_is_unchanged(self):
        client = self.lien()
        conn = imap.ImapConnection(client)
        sonde = conn.claim_probe("INBOX", 1, uidvalidity=42)
        self.assertEqual(conn.claim_store(1, sonde), "stored")
        self.assertEqual(client.noop()[0], "OK")
        client.logout()
        self.assertEqual(self.server.verbs()[-1], "LOGOUT")


class Interruption(BaseException):
    """Une interruption qui n'est pas `KeyboardInterrupt`, que `unittest`
    relancerait au lieu d'en faire un échec."""


class Bout:
    """Les trois points d'entrée-sortie d'un client `imaplib`. La méthode
    désignée lève `erreur` à son PREMIER appel seulement, puis rend
    normalement."""

    def __init__(self, methode=None, erreur=None):
        self.methode = methode
        self.erreur = erreur
        self.appels = []

    def _appel(self, nom, valeur):
        self.appels.append(nom)
        if nom == self.methode and self.erreur is not None:
            erreur, self.erreur = self.erreur, None
            raise erreur
        return valeur

    def read(self, size):
        return self._appel("read", b"x" * size)

    def readline(self):
        return self._appel("readline", b"ligne\r\n")

    def send(self, data):
        return self._appel("send", None)


def _solliciter(bout, methode):
    if methode == "read":
        return bout.read(4)
    if methode == "readline":
        return bout.readline()
    return bout.send(b"x")


class TestFailFastWrapper(unittest.TestCase):
    METHODES = ("read", "readline", "send")
    ERREURS = (OSError, TimeoutError, Interruption)

    def test_an_exception_from_any_io_method_abandons_the_link(self):
        for methode in self.METHODES:
            for classe in self.ERREURS:
                with self.subTest(methode=methode, erreur=classe.__name__):
                    erreur = classe("panne")
                    bout = imap.fail_fast(Bout(methode, erreur))
                    with self.assertRaises(classe) as ctx:
                        _solliciter(bout, methode)
                    self.assertIs(ctx.exception, erreur)
                    for autre in self.METHODES:
                        with self.assertRaises(imaplib.IMAP4.abort) as ctx:
                            _solliciter(bout, autre)
                        self.assertIn(classe.__name__, str(ctx.exception))

    def test_the_original_methods_are_not_called_after_the_failure(self):
        for methode in self.METHODES:
            with self.subTest(methode=methode):
                bout = imap.fail_fast(Bout(methode, OSError("panne")))
                with self.assertRaises(OSError):
                    _solliciter(bout, methode)
                vus = list(bout.appels)
                for autre in self.METHODES:
                    with self.assertRaises(imaplib.IMAP4.abort):
                        _solliciter(bout, autre)
                self.assertEqual(bout.appels, vus)

    def test_results_pass_through_while_the_link_is_alive(self):
        bout = Bout()
        self.assertIs(imap.fail_fast(bout), bout)
        self.assertEqual(bout.read(4), b"xxxx")
        self.assertEqual(bout.readline(), b"ligne\r\n")
        self.assertIsNone(bout.send(b"x"))
        self.assertEqual(bout.appels, ["read", "readline", "send"])

    def test_only_the_first_cause_is_named(self):
        bout = imap.fail_fast(Bout("read", TimeoutError("délai")))
        with self.assertRaises(TimeoutError):
            bout.read(1)
        for _ in range(2):
            with self.assertRaises(imaplib.IMAP4.abort) as ctx:
                bout.send(b"x")
        self.assertIn("(TimeoutError)", str(ctx.exception))
        self.assertNotIn("abort", str(ctx.exception))


class TestReaders(unittest.TestCase):
    def test_parse_fetch_headers_fills_extra(self):
        brut = (
            f"From: Carole <{CAROLE}>\r\n"
            f"To: {OWN}\r\n"
            "Subject: Question\r\n"
            "Message-ID: <q1@example.org>\r\n"
            "Auto-Submitted: auto-replied\r\n"
            "List-Id: <liste.example.org>\r\n"
            "Precedence: bulk\r\n"
            "Precedence: list\r\n"
            "X-Loop: boucle\r\n\r\n"
        ).encode()
        entetes = imap.parse_fetch_headers(
            [
                (
                    b"1 (UID 12 FLAGS (\\Seen) RFC822.SIZE 900"
                    b' INTERNALDATE "06-Nov-2026 10:00:00 +0000"'
                    b" BODY[HEADER.FIELDS (FROM)] {200}",
                    brut,
                ),
                b")",
            ]
        )
        self.assertEqual(len(entetes), 1)
        entete = entetes[0]
        self.assertIsInstance(entete, imap.HeaderInfo)
        self.assertEqual((entete.uid, entete.size), (12, 900))
        self.assertEqual(
            entete.internaldate, calendar.timegm((2026, 11, 6, 10, 0, 0))
        )
        self.assertEqual(
            entete.extra,
            {
                "auto-submitted": "auto-replied",
                "list-id": "<liste.example.org>",
                "precedence": "bulk\nlist",
                "x-loop": "boucle",
            },
        )
        self.assertEqual(entete.frm_raw, f"Carole <{CAROLE}>")

    def test_extra_headers_names_are_the_guarded_ones(self):
        """Un en-tête que lisent les garde-fous et que le FETCH ne demande
        pas les laisserait tout passer sans rien dire."""
        noms = {nom.lower() for nom in imap.EXTRA_HEADERS}
        for nom in (
            "auto-submitted",
            "precedence",
            "list-id",
            "list-unsubscribe",
            "x-auto-response-suppress",
            "x-loop",
            "authentication-results",
            "x-spam-flag",
            "content-type",
            "resent-from",
            "return-path",
            "reply-to",
        ):
            with self.subTest(nom=nom):
                self.assertIn(nom, noms)
                self.assertIn(nom.upper(), imap.HEADER_FIELDS)

    def test_xoauth2_chain_format(self):
        self.assertEqual(
            imap.xoauth2_chain(OWN, "jeton"),
            f"user={OWN}\x01auth=Bearer jeton\x01\x01".encode(),
        )


if __name__ == "__main__":
    unittest.main()
