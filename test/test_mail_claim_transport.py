#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La revendication d'un message au niveau du transport IMAP.

`claim_probe` lit si un message peut être revendiqué et dans quel mode,
`claim_store` pose le mot-clé. Les cas de protocole se jouent contre le
bac à sable (avec et sans CONDSTORE, PERMANENTFLAGS restreint, boîte en
lecture seule, mots-clés jetés) ; les lignes FETCH que le bac à sable ne
produit pas (plusieurs lignes d'un même UID, BAD à MODSEQ) se jouent
contre un double du client `imaplib`. Le double applique l'arité d'`uid()`
des versions récentes d'`imaplib` : un STORE à plus de trois arguments y
lève, quel que soit l'interpréteur.
"""

import imaplib
import unittest

from script.todo.mail.claim import (
    CLAIM_KEYWORD,
    ClaimProbe,
    has_claim,
    without_claim,
)
from script.todo.mail.imap_transport import (
    ImapError,
    ImaplibTransport,
    parse_fetch_headers,
)

try:
    import aiosmtpd  # noqa: F401
    import twisted  # noqa: F401

    SANDBOX_MISSING = ""
except ImportError as exc:  # pragma: no cover - dépend de l'installation
    SANDBOX_MISSING = str(exc)

if SANDBOX_MISSING:  # pragma: no cover - dépend de l'installation
    MailSandboxCase = unittest.TestCase
else:
    from mail_sandbox import (
        PASSWORD,
        USER,
        Interfere,
        MailSandboxCase,
        sandbox_account,
    )

OWN = "boite.regles@example.org"
CAROLE = "carole.regle@example.org"


def brut(uid):
    return (
        f"From: {CAROLE}\r\nTo: {OWN}\r\nSubject: Question {uid}\r\n"
        f"Message-ID: <{uid}@example.net>\r\n\r\nBonjour.\r\n"
    ).encode()


# L'arité qu'`uid()` impose à ses arguments après la commande, selon les
# versions récentes d'`imaplib`.
ARITE_UID = {"STORE": 3, "FETCH": 2, "COPY": 2}


class ClientDouble:
    """Un client `imaplib` réduit : chaque `uid()` ou `xatom()` rend la
    réponse suivante de `reponses` (ou lève l'exception qui s'y trouve).

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


class TestClaimHelpers(unittest.TestCase):
    def test_has_claim_ignores_case_and_partial_tokens(self):
        self.assertTrue(has_claim("\\Seen $ErpLibreRule"))
        self.assertTrue(has_claim("$ERPLIBRERULE"))
        self.assertTrue(has_claim(["\\Seen", "$erplibrerule"]))
        self.assertFalse(has_claim("$ErpLibreRuleX \\Seen"))
        self.assertFalse(has_claim(""))
        self.assertFalse(has_claim(None))

    def test_without_claim_keeps_the_other_flags_in_order(self):
        self.assertEqual(
            without_claim("\\Seen  $erplibrerule \\Flagged $ErpLibreRuleX"),
            ["\\Seen", "\\Flagged", "$ErpLibreRuleX"],
        )
        self.assertEqual(without_claim(None), [])

    def test_fetch_flags_and_headers_still_parse_lines_with_modseq(self):
        client = ClientDouble(
            [("OK", [b"1 (UID 1 FLAGS (\\Seen) MODSEQ (12))"])]
        )
        transport = ImaplibTransport(client)
        self.assertEqual(transport.fetch_flags([1]), [(1, "\\Seen")])
        entetes = parse_fetch_headers(
            [
                (
                    b"1 (UID 1 FLAGS (\\Seen) MODSEQ (12) RFC822.SIZE 40"
                    b" BODY[HEADER.FIELDS (FROM)] {20}",
                    b"From: a@example.org\r\n\r\n",
                ),
                b")",
            ]
        )
        self.assertEqual(
            (entetes[0].uid, entetes[0].flags, entetes[0].size),
            (1, "\\Seen", 40),
        )

    def test_fetch_flags_ignores_a_line_without_flags(self):
        client = ClientDouble(
            [
                (
                    "OK",
                    [
                        b"1 (UID 1 MODSEQ (13))",
                        b"1 (UID 1 FLAGS (\\Seen) MODSEQ (14))",
                        b"2 (UID 2 MODSEQ (15))",
                    ],
                )
            ]
        )
        self.assertEqual(
            ImaplibTransport(client).fetch_flags([1, 2]), [(1, "\\Seen")]
        )

    def test_the_conditional_store_goes_out_through_xatom(self):
        client = ClientDouble(
            [
                ("OK", [b"1 (UID 1 FLAGS (\\Seen) MODSEQ (7))"]),
                ("OK", [b"1 (UID 1 FLAGS (\\Seen $ErpLibreRule) MODSEQ (8))"]),
            ],
            capacites=b"IMAP4rev1 CONDSTORE",
        )
        transport = ImaplibTransport(client)
        sonde = transport.claim_probe("INBOX", 1, uidvalidity=42)
        self.assertEqual(sonde, ClaimProbe("free", "atomic", 7))
        self.assertEqual(transport.claim_store(1, sonde), "stored")
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

    def sonde(self, lignes):
        client = ClientDouble(
            [("OK", lignes)], capacites=b"IMAP4rev1 CONDSTORE"
        )
        return ImaplibTransport(client).claim_probe("INBOX", 1, uidvalidity=42)

    def test_the_probe_keeps_the_last_line_of_its_uid_with_flags(self):
        ancienne = b"1 (UID 1 FLAGS (\\Seen) MODSEQ (12))"
        sans_drapeaux = b"1 (UID 1 MODSEQ (15))"
        posee = b"1 (UID 1 FLAGS (\\Seen $ErpLibreRule) MODSEQ (14))"
        self.assertEqual(
            self.sonde([ancienne, sans_drapeaux, posee]),
            ClaimProbe("present", "atomic", 14),
        )
        libre = b"1 (UID 1 FLAGS (\\Seen \\Answered) MODSEQ (14))"
        self.assertEqual(
            self.sonde([posee.replace(b"14", b"11"), sans_drapeaux, libre]),
            ClaimProbe("free", "atomic", 14),
        )

    def test_a_bad_answer_to_modseq_falls_back_to_plain_for_the_connection(
        self,
    ):
        client = ClientDouble(
            [
                imaplib.IMAP4.error("FETCH command error: BAD"),
                ("OK", [b"1 (UID 1 FLAGS (\\Seen))"]),
                ("OK", [b"1 (UID 1 FLAGS (\\Seen))"]),
            ],
            capacites=b"IMAP4rev1 CONDSTORE",
        )
        transport = ImaplibTransport(client)
        self.assertEqual(
            transport.claim_probe("INBOX", 1, uidvalidity=42),
            ClaimProbe("free", "plain"),
        )
        self.assertEqual(
            transport.claim_probe("INBOX", 1, uidvalidity=42).mode, "plain"
        )
        demandes = [args[1] for _cmd, args in client.appels]
        self.assertEqual(
            demandes, ["(UID FLAGS MODSEQ)", "(UID FLAGS)", "(UID FLAGS)"]
        )

    def test_a_bad_answer_to_unchangedsince_retries_in_plain(self):
        client = ClientDouble(
            [imaplib.IMAP4.error("UID command error: BAD")],
            capacites=b"IMAP4rev1 CONDSTORE",
        )
        transport = ImaplibTransport(client)
        resultat = transport.claim_store(1, ClaimProbe("free", "atomic", 7))
        self.assertEqual(resultat, "retry")
        self.assertTrue(transport._sans_condstore)

    def test_a_store_without_its_fetch_line_is_reread_before_concluding(
        self,
    ):
        """Un serveur peut taire la ligne FETCH d'un STORE : la relecture
        tranche, au lieu de conclure que le message a disparu."""
        cas = (
            ([b"1 (UID 1 FLAGS ($ErpLibreRule))"], "stored"),
            ([b"1 (UID 1 FLAGS (\\Seen))"], "refused"),
            ([None], "gone"),
        )
        for relu, attendu in cas:
            with self.subTest(attendu=attendu):
                client = ClientDouble([("OK", [None]), ("OK", relu)])
                transport = ImaplibTransport(client)
                self.assertEqual(
                    transport.claim_store(1, ClaimProbe("free", "plain")),
                    attendu,
                )
                self.assertEqual(len(client.appels), 2)

    def test_a_refused_reread_after_an_accepted_store_is_unknown(self):
        """Le STORE accepté a peut-être posé le mot-clé : un NO à la
        relecture ne dit pas qu'il n'a rien appliqué."""
        for refus in (("NO", [b"message expunged"]), ("BAD", [b"syntax"])):
            with self.subTest(refus=refus[0]):
                client = ClientDouble([("OK", [None]), refus])
                self.assertEqual(
                    ImaplibTransport(client).claim_store(
                        1, ClaimProbe("free", "plain")
                    ),
                    "unknown",
                )

    def test_a_link_failure_during_the_store_goes_through(self):
        client = ClientDouble([imaplib.IMAP4.abort("socket error")])
        with self.assertRaises(imaplib.IMAP4.abort):
            ImaplibTransport(client).claim_store(
                1, ClaimProbe("free", "plain")
            )

    def test_a_store_answered_no_raises(self):
        client = ClientDouble([("NO", [b"quota"])])
        with self.assertRaises(ImapError):
            ImaplibTransport(client).claim_store(
                1, ClaimProbe("free", "plain")
            )


class SandboxClaimCase(MailSandboxCase):
    SANDBOX = {}

    def setUp(self):
        self.serveur = self.imap_server(**self.SANDBOX)
        self.inbox = self.serveur.folder("INBOX")
        self.autre = self.serveur.folder("Archives")
        for uid in (1, 2):
            self.inbox.deliver(brut(uid), uid=uid)
        self.autre.deliver(brut(9), uid=9)

    def transport(self):
        return self.imap_transport(
            self.serveur, sandbox_account(imap_port=self.serveur.port)
        )

    def sonde(self, transport, uid=1, uidvalidity=42):
        return transport.claim_probe("INBOX", uid, uidvalidity=uidvalidity)

    def revendique(self, transport, uid=1):
        return transport.claim_store(uid, self.sonde(transport, uid))

    def drapeaux(self, uid=1):
        return list(self.inbox.by_uid(uid).flags)


@unittest.skipIf(
    bool(SANDBOX_MISSING), f"serveurs de test absents ({SANDBOX_MISSING})"
)
class TestClaimCondstore(SandboxClaimCase):
    SANDBOX = {"condstore": True}

    def test_a_free_message_is_claimed_atomically(self):
        transport = self.transport()
        sonde = self.sonde(transport)
        self.assertEqual((sonde.status, sonde.mode), ("free", "atomic"))
        self.assertEqual(sonde.modseq, self.inbox.by_uid(1).modseq)
        self.assertEqual(transport.claim_store(1, sonde), "stored")
        self.assertEqual(self.drapeaux(), [CLAIM_KEYWORD])

    def test_a_second_client_finds_the_keyword_present(self):
        self.assertEqual(self.revendique(self.transport()), "stored")
        sonde = self.sonde(self.transport())
        self.assertEqual((sonde.status, sonde.mode), ("present", "atomic"))

    def test_a_change_between_probe_and_store_is_reported_modified(self):
        transport = self.transport()
        sonde = self.sonde(transport)
        self.serveur.fail(
            Interfere(
                b"STORE",
                action=lambda: self.inbox.marquer_ailleurs(1, "\\Seen"),
            )
        )
        self.assertEqual(transport.claim_store(1, sonde), "modified")
        self.assertEqual(self.drapeaux(), ["\\Seen"])

    def test_the_store_leaves_no_fetch_for_the_next_command(self):
        transport = self.transport()
        self.assertEqual(self.revendique(transport), "stored")
        self.assertEqual(transport.fetch_flags([2]), [(2, "")])

    def test_a_stale_modified_does_not_turn_the_next_store_into_modified(
        self,
    ):
        transport = self.transport()
        sonde = self.sonde(transport)
        transport.client.untagged_responses["MODIFIED"] = [b"1"]
        self.assertEqual(transport.claim_store(1, sonde), "stored")

    def test_an_expunged_uid_at_store_time_is_gone_not_stored(self):
        transport = self.transport()
        sonde = self.sonde(transport)
        self.serveur.fail(
            Interfere(b"STORE", action=lambda: self.inbox.expurger(1))
        )
        self.assertEqual(transport.claim_store(1, sonde), "gone")

    def test_a_server_that_drops_keywords_is_refused_even_with_condstore(
        self,
    ):
        self.inbox.keywords = False
        transport = self.transport()
        sonde = self.sonde(transport)
        self.assertEqual(sonde.mode, "atomic")
        self.assertEqual(transport.claim_store(1, sonde), "refused")
        self.assertEqual(self.drapeaux(), [])

    def test_a_nomodseq_mailbox_falls_back_to_plain(self):
        self.serveur.nomodseq = True
        transport = self.transport()
        sonde = self.sonde(transport)
        self.assertEqual((sonde.status, sonde.mode), ("free", "plain"))
        self.assertIsNone(sonde.modseq)
        self.assertEqual(transport.claim_store(1, sonde), "stored")


@unittest.skipIf(
    bool(SANDBOX_MISSING), f"serveurs de test absents ({SANDBOX_MISSING})"
)
class TestClaimCondstoreAfterLogin(SandboxClaimCase):
    SANDBOX = {"condstore": True, "condstore_after_login": True}

    def test_condstore_announced_after_login_is_seen(self):
        transport = self.transport()
        sonde = self.sonde(transport)
        self.assertEqual((sonde.status, sonde.mode), ("free", "atomic"))
        self.assertEqual(transport.claim_store(1, sonde), "stored")

    def test_condstore_after_login_is_seen_even_if_imaplib_keeps_the_old_list(
        self,
    ):
        """Un `imaplib` qui ne relit pas les capacités après LOGIN y laisse
        la liste d'avant connexion, sans CONDSTORE : la sonde le voit
        quand même."""
        transport = self.transport()
        transport.client.capabilities = tuple(
            c for c in transport.client.capabilities if c != "CONDSTORE"
        )
        self.assertNotIn("CONDSTORE", transport.client.capabilities)
        sonde = self.sonde(transport)
        self.assertEqual((sonde.status, sonde.mode), ("free", "atomic"))
        self.assertEqual(transport.claim_store(1, sonde), "stored")


@unittest.skipIf(
    bool(SANDBOX_MISSING), f"serveurs de test absents ({SANDBOX_MISSING})"
)
class TestClaimPlain(SandboxClaimCase):
    def test_without_condstore_the_claim_is_plain_and_reread(self):
        transport = self.transport()
        sonde = self.sonde(transport)
        self.assertEqual(sonde, ClaimProbe("free", "plain"))
        self.assertEqual(transport.claim_store(1, sonde), "stored")
        self.assertEqual(self.drapeaux(), [CLAIM_KEYWORD])
        self.assertEqual(self.sonde(transport).status, "present")

    def test_an_expunged_uid_is_gone(self):
        self.inbox.expurger(1)
        self.assertEqual(self.sonde(self.transport()).status, "gone")

    def test_an_expunged_uid_at_store_time_is_gone_not_stored(self):
        transport = self.transport()
        sonde = self.sonde(transport)
        self.serveur.fail(
            Interfere(b"STORE", action=lambda: self.inbox.expurger(1))
        )
        self.assertEqual(transport.claim_store(1, sonde), "gone")

    def test_a_changed_uidvalidity_is_renumbered(self):
        self.assertEqual(
            self.sonde(self.transport(), uidvalidity=41).status,
            "renumbered",
        )

    def test_the_keyword_is_recognised_whatever_its_case(self):
        self.inbox.by_uid(1).flags = ["$erplibrerule"]
        self.assertEqual(self.sonde(self.transport()).status, "present")


@unittest.skipIf(
    bool(SANDBOX_MISSING), f"serveurs de test absents ({SANDBOX_MISSING})"
)
class TestClaimRefused(SandboxClaimCase):
    def test_permanentflags_without_wildcard_is_unsupported_without_any_store(
        self,
    ):
        self.serveur.permanent_flags = ("\\Seen", "\\Flagged")
        transport = self.transport()
        sonde = self.sonde(transport)
        self.assertEqual(
            sonde, ClaimProbe("unsupported", "none", reason="keywords")
        )
        self.assertEqual(self.drapeaux(), [])

    def test_permanentflags_listing_the_keyword_allows_it(self):
        self.serveur.permanent_flags = ("\\Seen", CLAIM_KEYWORD.upper())
        transport = self.transport()
        self.assertEqual(self.revendique(transport), "stored")

    def test_permanentflags_with_the_wildcard_allows_it(self):
        self.serveur.permanent_flags = ("\\Seen", "\\*")
        self.assertEqual(self.revendique(self.transport()), "stored")

    def test_a_server_that_drops_keywords_is_refused_after_reread(self):
        self.inbox.keywords = False
        self.assertEqual(self.revendique(self.transport()), "refused")
        self.assertEqual(self.drapeaux(), [])

    def test_a_read_only_inbox_raises_and_leaves_the_client_usable(self):
        self.inbox.writeable = False
        transport = self.transport()
        with self.assertRaises(ImapError):
            self.sonde(transport)
        self.assertEqual(transport.client.noop()[0], "OK")
        transport.select("Archives")
        self.assertEqual(transport.fetch_flags([9]), [(9, "")])


@unittest.skipIf(
    bool(SANDBOX_MISSING), f"serveurs de test absents ({SANDBOX_MISSING})"
)
class TestSandboxCondstore(MailSandboxCase):
    """Le bac à sable lui-même, parlé par `imaplib` brut."""

    def client(self, **options):
        serveur = self.imap_server(condstore=True, **options)
        self.inbox = serveur.folder("INBOX")
        self.inbox.deliver(brut(1), uid=1)
        self.serveur = serveur
        client = imaplib.IMAP4("127.0.0.1", serveur.port)
        self.addCleanup(client.shutdown)
        return client

    def test_select_announces_permanentflags_and_highestmodseq(self):
        client = self.client(permanent_flags=("\\Seen", "\\*"))
        client.login(USER, PASSWORD)
        client.select("INBOX")
        self.assertEqual(
            client.response("PERMANENTFLAGS")[1], [b"(\\Seen \\*)"]
        )
        self.assertEqual(
            client.response("HIGHESTMODSEQ")[1],
            [str(self.inbox.modseq).encode()],
        )

    def test_a_stale_unchangedsince_answers_modified_and_changes_nothing(
        self,
    ):
        client = self.client()
        client.login(USER, PASSWORD)
        client.select("INBOX")
        vieux = self.inbox.by_uid(1).modseq - 1
        typ, _ = client.xatom(
            "UID",
            "STORE",
            "1",
            f"(UNCHANGEDSINCE {vieux})",
            "+FLAGS",
            "(\\Seen)",
        )
        self.assertEqual(typ, "OK")
        self.assertEqual(client.response("FETCH")[1], [None])
        self.assertEqual(client.response("MODIFIED")[1], [b"1"])
        self.assertEqual(self.inbox.by_uid(1).flags, [])

    def test_a_silent_conditional_store_still_sends_fetch_with_modseq(self):
        client = self.client()
        client.login(USER, PASSWORD)
        client.select("INBOX")
        actuel = self.inbox.by_uid(1).modseq
        typ, _ = client.xatom(
            "UID",
            "STORE",
            "1",
            f"(UNCHANGEDSINCE {actuel})",
            "+FLAGS.SILENT",
            "(\\Seen)",
        )
        self.assertEqual(typ, "OK")
        self.assertEqual(
            client.response("FETCH")[1],
            [f"1 (UID 1 MODSEQ ({actuel + 1}))".encode()],
        )
        self.assertEqual(self.inbox.by_uid(1).flags, ["\\Seen"])

    def test_condstore_after_login_is_absent_before_login(self):
        client = self.client(condstore_after_login=True)
        self.assertNotIn("CONDSTORE", client.capabilities)
        client.login(USER, PASSWORD)
        self.assertIn(b"CONDSTORE", client.capability()[1][-1].split())

    def test_interfere_runs_its_action_and_lets_the_command_through(self):
        client = self.client()
        client.login(USER, PASSWORD)
        client.select("INBOX")
        vus = []
        self.serveur.fail(Interfere(b"FETCH", action=lambda: vus.append(1)))
        typ, data = client.uid("FETCH", "1", "(UID FLAGS MODSEQ)")
        self.assertEqual(typ, "OK")
        self.assertEqual(vus, [1])
        self.assertIn(b"MODSEQ", data[0])
        typ, data = client.uid("FETCH", "1", "(UID FLAGS)")
        self.assertEqual((typ, vus), ("OK", [1, 1]))

    def test_an_announced_change_reaches_the_connection_without_flags(self):
        client = self.client()
        client.login(USER, PASSWORD)
        client.select("INBOX")
        self.inbox.marquer_ailleurs(1, "\\Seen", annoncer=True)
        typ, data = client.uid("FETCH", "1", "(UID FLAGS)")
        self.assertEqual(typ, "OK")
        self.assertTrue(
            any(b"MODSEQ" in d and b"FLAGS" not in d for d in data)
        )


if __name__ == "__main__":
    unittest.main()
