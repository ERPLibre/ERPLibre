#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Une règle de réponse, de bout en bout, sur un vrai IMAP et un vrai SMTP.

La boîte de réception reçoit un message ordinaire, un message de liste et
une réponse automatique. Seul le premier reçoit une réponse : un message
SMTP, adressé à l'expéditeur, conforme à la RFC 3834, HTML avec son image
en ligne, copié dans Envoyés. Le corps lu par la règle descend par
BODY.PEEK : l'original reste non lu. Une seconde passe n'envoie rien.

Les INTERNALDATE sont posées explicitement, après l'armement et près de
l'horloge injectée : la date fixe du bac à sable rendrait les messages
antérieurs à l'armement ou trop vieux.
"""

import calendar
import email
import email.policy
import email.utils
import os
import tempfile
import time
import unittest
from pathlib import Path

try:
    import aiosmtpd  # noqa: F401
    import twisted  # noqa: F401

    SANDBOX_MISSING = ""
except ImportError as exc:  # pragma: no cover - dépend de l'installation
    SANDBOX_MISSING = str(exc)

if SANDBOX_MISSING:  # pragma: no cover - dépend de l'installation
    MailSandboxCase = unittest.TestCase
else:
    from mail_sandbox import PASSWORD, MailSandboxCase, sandbox_account

OWN = "boite.regles@example.org"
CAROLE = "carole.regle@example.org"
LISTE = "liste-annonces@example.net"
REPONDEUR = "service.repondeur@example.com"
RECU = calendar.timegm((2026, 10, 27, 10, 0, 0))
RECU_IMAP = b"27-Oct-2026 10:00:00 +0000"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def brut(frm, uid, *entetes):
    lignes = [
        f"From: {frm}",
        f"To: {OWN}",
        f"Subject: Question {uid}",
        f"Message-ID: <{uid}@example.net>",
        *entetes,
        "",
        "Bonjour, une question.",
        "",
    ]
    return "\r\n".join(lignes).encode()


@unittest.skipIf(
    bool(SANDBOX_MISSING), f"serveurs de test absents ({SANDBOX_MISSING})"
)
class TestReplyRuleEndToEnd(MailSandboxCase):
    def setUp(self):
        from script.todo.mail import imap_transport
        from script.todo.mail.imap_sync import Syncer
        from script.todo.mail.rules import storage
        from script.todo.mail.rules.model import (
            Armed,
            Condition,
            Group,
            new_rule,
        )
        from script.todo.mail.tui import Session

        self.imap = self.imap_server()
        self.smtp = self.smtp_server()
        self.inbox = self.imap.folder("INBOX")
        self.sent = self.imap.folder("INBOX.Sent", attributs=("\\Sent",))
        self.inbox.deliver(
            brut(f"Carole <{CAROLE}>", 1), uid=1, internal_date=RECU_IMAP
        )
        self.inbox.deliver(
            brut(LISTE, 2, "List-Id: <annonces.example.net>"),
            uid=2,
            internal_date=RECU_IMAP,
        )
        self.inbox.deliver(
            brut(REPONDEUR, 3, "Auto-Submitted: auto-replied"),
            uid=3,
            internal_date=RECU_IMAP,
        )
        self.account = sandbox_account(
            imap_port=self.imap.port,
            smtp_port=self.smtp.port,
            name="perso",
            address=OWN,
        )
        self.store = self.temp_store(self.account)
        self.base = Path(self.store.root).parent
        transport = imap_transport.connect(self.account, PASSWORD)
        self.addCleanup(transport.logout)
        self.session = Session(
            self.account,
            self.store,
            Syncer(self.store, transport),
            password=PASSWORD,
        )

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        logo = Path(tmp.name) / "logo.png"
        logo.write_bytes(PNG)
        ref = storage.import_media("perso", logo, base=self.base)
        rule = new_rule("reply", "Absence")
        rule.action.format = "html"
        rule.action.body = '<p>Je suis absente.</p><img src="logo.png">'
        rule.action.images = [ref]
        rule.filter = Group("all", [Condition("body", "bonjour")])
        storage.upsert_rule(
            "perso", rule, rearm=Armed(42, 1, RECU - 3600), base=self.base
        )
        self.store.rule_log_claim(
            rule.id,
            "pre-approuvee",
            outcome="sent",
            at=RECU - 30 * 86400,
            fingerprint=rule.fingerprint(),
        )

    def passe(self):
        from script.todo.mail.rules import engine

        return engine.run_pass(
            self.session,
            report=self.session.sync(),
            all_accounts=[],
            now=lambda: RECU + 600,
        )

    def test_one_reply_reaches_the_sender_and_is_filed(self):
        bilan = self.passe()
        self.assertEqual((bilan.sent, bilan.status), (1, "ok"))
        self.assertEqual(bilan.skipped["list"], 1)
        self.assertEqual(bilan.skipped["auto_submitted"], 1)
        self.assertEqual(len(self.smtp.messages), 1)
        sorti = self.smtp.messages[0]
        self.assertEqual(sorti.rcpt_tos, [CAROLE])
        self.assertEqual(sorti.mail_from, OWN)
        entetes = sorti.headers()
        self.assertEqual(entetes["Auto-Submitted"], "auto-replied")
        self.assertEqual(entetes["X-Auto-Response-Suppress"], "All")
        self.assertIn("erplibre-rules", entetes["X-Loop"])
        self.assertEqual(entetes["In-Reply-To"], "<1@example.net>")
        types = [part.get_content_type() for part in entetes.walk()]
        self.assertIn("multipart/related", types)
        self.assertIn("image/png", types)
        self.assertEqual(len(self.sent.appended), 1)

    def test_the_originals_stay_unread(self):
        self.passe()
        # Le corps a bien été lu par la règle : il est en cache.
        self.assertIsNotNone(self.store.read_body("INBOX", 1))
        for message in self.inbox.messages:
            self.assertNotIn("\\Seen", message.flags)

    def test_a_second_pass_sends_nothing(self):
        self.passe()
        bilan = self.passe()
        self.assertEqual(bilan.sent, 0)
        self.assertEqual(len(self.smtp.messages), 1)


MOIS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
BRUNO = "bruno.filtre@example.net"
DENIS = "denis.tri@example.org"
DMARC_CAROLE = "mx.example.org; dmarc=pass header.from=example.org"


def imap_date(epoch):
    """L'INTERNALDATE au format IMAP, en UTC, sans dépendre de la locale."""
    g = time.gmtime(epoch)
    return (
        f"{g.tm_mday:02d}-{MOIS[g.tm_mon - 1]}-{g.tm_year}"
        f" {g.tm_hour:02d}:{g.tm_min:02d}:{g.tm_sec:02d} +0000"
    ).encode()


def message(frm, to, msgid, sujet, date, *entetes):
    lignes = [
        f"From: {frm}",
        f"To: {to}",
        f"Subject: {sujet}",
        f"Message-ID: {msgid}",
        f"Date: {email.utils.formatdate(date, usegmt=True)}",
        *entetes,
        "",
        "Bonjour, une question.",
        "",
    ]
    return "\r\n".join(lignes).encode()


@unittest.skipIf(
    bool(SANDBOX_MISSING), f"serveurs de test absents ({SANDBOX_MISSING})"
)
class TestStatsRuleEndToEnd(MailSandboxCase):
    """Une règle de rapport sur un vrai IMAP et un vrai SMTP, fuseau UTC.

    Historique : deux messages de Carole, répondus en 2 h et 4 h (réponses
    classées dans Envoyés, `In-Reply-To` et `Date`), le premier lu, et un
    message d'un tiers répondu en 1 h. Demandes à l'instant : Carole,
    authentifiée, et Bruno, sans `Authentication-Results`.
    """

    def setUp(self):
        from script.todo.mail import imap_transport
        from script.todo.mail.imap_sync import Syncer
        from script.todo.mail.rules import storage
        from script.todo.mail.rules.model import Armed, new_rule
        from script.todo.mail.tui import Session

        self._old_tz = os.environ.get("TZ")
        os.environ["TZ"] = "UTC"
        time.tzset()
        self.addCleanup(self.restaurer_tz)

        self.imap = self.imap_server()
        self.smtp = self.smtp_server()
        self.inbox = self.imap.folder("INBOX")
        self.sent = self.imap.folder("INBOX.Sent", attributs=("\\Sent",))
        historique = (
            (1, f"Carole <{CAROLE}>", RECU - 3 * 86400, 2 * 3600, True),
            (2, CAROLE, RECU - 2 * 86400, 4 * 3600, False),
            (3, DENIS, RECU - 86400, 3600, False),
        )
        for uid, frm, recu, delai, lu in historique:
            sujet = "Dossier confidentiel" if uid == 3 else f"Question {uid}"
            self.inbox.deliver(
                message(frm, OWN, f"<{uid}@example.net>", sujet, recu),
                flags=("\\Seen",) if lu else (),
                uid=uid,
                internal_date=imap_date(recu),
            )
            self.sent.deliver(
                message(
                    OWN,
                    frm,
                    f"<r{uid}@example.org>",
                    f"Re: {sujet}",
                    recu + delai,
                    f"In-Reply-To: <{uid}@example.net>",
                ),
                flags=("\\Seen",),
                uid=uid,
                internal_date=imap_date(recu + delai),
            )
        self.inbox.deliver(
            message(
                f"Carole <{CAROLE}>",
                OWN,
                "<10@example.net>",
                "Mes statistiques ?",
                RECU,
                f"Authentication-Results: {DMARC_CAROLE}",
            ),
            uid=10,
            internal_date=RECU_IMAP,
        )
        self.inbox.deliver(
            message(BRUNO, OWN, "<11@example.net>", "Question 11", RECU),
            uid=11,
            internal_date=RECU_IMAP,
        )
        self.account = sandbox_account(
            imap_port=self.imap.port,
            smtp_port=self.smtp.port,
            name="perso",
            address=OWN,
        )
        self.store = self.temp_store(self.account)
        self.base = Path(self.store.root).parent
        transport = imap_transport.connect(self.account, PASSWORD)
        self.addCleanup(transport.logout)
        self.session = Session(
            self.account,
            self.store,
            Syncer(self.store, transport),
            password=PASSWORD,
        )
        self.rule = new_rule("stats", "Rapport")
        self.rule.action.body += "\nVotre délai : {{delai_moyen}}.\n"
        self.rule.armed = Armed(42, 10, RECU - 3600)
        storage.upsert_rule(
            "perso", self.rule, rearm=self.rule.armed, base=self.base
        )
        self.store.rule_log_claim(
            self.rule.id,
            "pre-approuvee",
            outcome="sent",
            at=RECU - 30 * 86400,
            fingerprint=self.rule.fingerprint(),
        )

    def restaurer_tz(self):
        if self._old_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self._old_tz
        time.tzset()

    def passe(self):
        from script.todo.mail.rules import engine

        return engine.run_pass(
            self.session,
            report=self.session.sync(),
            all_accounts=[],
            now=lambda: RECU + 600,
        )

    def sorti(self):
        self.assertEqual(len(self.smtp.messages), 1)
        return email.message_from_bytes(
            self.smtp.messages[0].content, policy=email.policy.default
        )

    def test_only_the_authenticated_sender_gets_the_report(self):
        bilan = self.passe()
        self.assertEqual((bilan.sent, bilan.status), (1, "ok"))
        self.assertEqual(bilan.skipped["unauthenticated"], 1)
        self.assertEqual(self.smtp.messages[0].rcpt_tos, [CAROLE])
        entetes = self.sorti()
        self.assertEqual(entetes["Auto-Submitted"], "auto-replied")
        self.assertEqual(entetes["In-Reply-To"], "<10@example.net>")

    def test_the_report_is_html_with_a_table_and_text_with_an_aligned_table(
        self,
    ):
        from script.todo.todo_i18n import t

        self.passe()
        msg = self.sorti()
        texte = msg.get_body(preferencelist=("plain",)).get_content()
        html = msg.get_body(preferencelist=("html",)).get_content()
        # Trois originaux reçus dans les sept jours clos, un lu, trois
        # répondus ; Carole : 2 h et 4 h, soit 3 h en moyenne.
        lignes = texte.splitlines()
        debut = next(
            i
            for i, ligne in enumerate(lignes)
            if ligne.startswith(t("mail_stats_report_col_day"))
        )
        fin = next(
            i
            for i, ligne in enumerate(lignes)
            if ligne.startswith(t("mail_stats_report_total"))
        )
        tableau = lignes[debut : fin + 1]
        self.assertEqual(len(tableau), 9)
        self.assertEqual(len({len(ligne) for ligne in tableau}), 1)
        self.assertEqual(tableau[-1].split()[1:], ["3", "1", "3"])
        self.assertIn("2026-10-26", tableau[-2])
        self.assertIn("Votre délai : 3 h.", texte)
        self.assertIn("<table", html)
        self.assertIn(
            f"<th>{t('mail_stats_report_total')}</th>"
            '<td style="text-align:right">3</td>',
            html,
        )
        self.assertNotIn("<p><table", html)

    def test_the_report_carries_no_other_address_or_subject(self):
        self.passe()
        brut = self.smtp.messages[0].content.decode("utf-8", "replace")
        for secret in (
            BRUNO,
            DENIS,
            "confidentiel",
            "Question 1",
            "Question 11",
        ):
            with self.subTest(secret=secret):
                self.assertNotIn(secret, brut)
        msg = self.sorti()
        for genre in ("plain", "html"):
            corps = msg.get_body(preferencelist=(genre,)).get_content()
            self.assertNotIn("@", corps)

    def test_a_second_pass_sends_nothing(self):
        self.passe()
        bilan = self.passe()
        self.assertEqual(bilan.sent, 0)
        self.assertEqual(len(self.smtp.messages), 1)

    def test_a_trial_to_oneself_changes_no_statistic(self):
        from script.todo.mail import imap_transport
        from script.todo.mail.imap_sync import Syncer
        from script.todo.mail.rules import engine
        from script.todo.mail.rules.report import collect_mailbox
        from script.todo.mail.rules.storage import ReportSettings

        reglages = ReportSettings()
        maintenant = RECU + 600
        self.session.sync()
        avant = collect_mailbox(self.store, reglages, now=maintenant)
        entete = engine.fetch_inbox_header(self.session, 10, uidvalidity=42)
        sim = engine.simulate(
            self.session,
            self.rule,
            entete,
            uidvalidity=42,
            all_accounts=[],
            now=lambda: maintenant,
        )
        self.assertEqual(sim.reason, "send")
        self.assertIn("3 h", sim.rendered.text)
        engine.send_trial(self.session, self.rule, sim, now=lambda: maintenant)
        essai = self.smtp.messages[-1]
        self.assertEqual(essai.rcpt_tos, [OWN])
        self.assertEqual(len(self.sent.appended), 1)
        # Le bac à sable capture sans remettre : la copie reçue est posée
        # à la main, datée d'hier pour tomber dans les tranches.
        self.inbox.deliver(
            essai.content, uid=20, internal_date=imap_date(RECU - 86400)
        )
        self.session.sync()
        self.assertEqual(
            collect_mailbox(self.store, reglages, now=maintenant), avant
        )

        neuf = self.temp_store(self.account)
        transport = imap_transport.connect(self.account, PASSWORD)
        self.addCleanup(transport.logout)
        Syncer(neuf, transport).sync()
        self.assertEqual(
            collect_mailbox(neuf, reglages, now=maintenant), avant
        )


TEMOIN = "temoin.cci@example.com"
PDF = b"%PDF-1.4\n1 0 obj << >> endobj\ntrailer << >>\n%%EOF\n"


def original_complet():
    """Un message de Bruno : texte et HTML avec une image liée, un PDF
    joint, un Cc et un Cci tiers, des en-têtes de remise."""
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["Return-Path"] = f"<{BRUNO}>"
    msg["Received"] = "from mx.example.org by mx.example.org; " + (
        email.utils.formatdate(RECU, usegmt=True)
    )
    msg["From"] = f"Bruno <{BRUNO}>"
    msg["To"] = OWN
    msg["Cc"] = TEMOIN
    msg["Bcc"] = TEMOIN
    msg["Subject"] = "Devis à relayer"
    msg["Message-ID"] = "<relais1@example.net>"
    msg["Date"] = email.utils.formatdate(RECU, usegmt=True)
    msg.set_content("Bonjour, voici le devis.\n")
    msg.add_alternative(
        "<html><body><p>Bonjour, voici le devis.</p>"
        '<img src="cid:logo@example.net"></body></html>\n',
        subtype="html",
    )
    msg.get_payload()[1].add_related(
        PNG, "image", "png", cid="<logo@example.net>"
    )
    msg.add_attachment(
        PDF, maintype="application", subtype="pdf", filename="devis.pdf"
    )
    return msg.as_bytes(policy=email.policy.SMTP)


@unittest.skipIf(
    bool(SANDBOX_MISSING), f"serveurs de test absents ({SANDBOX_MISSING})"
)
class TestForwardRuleEndToEnd(MailSandboxCase):
    """Une règle de redirection sur un vrai IMAP et un vrai SMTP.

    INBOX reçoit un message de Bruno, en copie et en copie cachée à un
    tiers ; la règle le relaie à Carole et Denis, en transfert ou en vraie
    redirection selon le test.
    """

    def setUp(self):
        from script.todo.mail import imap_transport
        from script.todo.mail.imap_sync import Syncer
        from script.todo.mail.tui import Session

        self.imap = self.imap_server()
        self.smtp = self.smtp_server()
        self.inbox = self.imap.folder("INBOX")
        self.sent = self.imap.folder("INBOX.Sent", attributs=("\\Sent",))
        self.brut = original_complet()
        self.inbox.deliver(self.brut, uid=1, internal_date=RECU_IMAP)
        self.account = sandbox_account(
            imap_port=self.imap.port,
            smtp_port=self.smtp.port,
            name="perso",
            address=OWN,
        )
        self.store = self.temp_store(self.account)
        self.base = Path(self.store.root).parent
        transport = imap_transport.connect(self.account, PASSWORD)
        self.addCleanup(transport.logout)
        self.session = Session(
            self.account,
            self.store,
            Syncer(self.store, transport),
            password=PASSWORD,
        )

    def regle(self, mode="inline", targets=(CAROLE, DENIS)):
        """Une règle `forward` armée avant les messages et approuvée."""
        from script.todo.mail.rules import storage
        from script.todo.mail.rules.model import Armed, new_rule

        rule = new_rule("forward", f"Relais {mode}")
        rule.action.body = "Transmis par la boîte des règles."
        rule.action.options.update(targets=list(targets), mode=mode)
        storage.upsert_rule(
            "perso", rule, rearm=Armed(42, 1, RECU - 3600), base=self.base
        )
        self.store.rule_log_claim(
            rule.id,
            f"pre-{rule.id}",
            outcome="sent",
            at=RECU - 30 * 86400,
            fingerprint=rule.fingerprint(),
        )
        return rule

    def passe(self):
        from script.todo.mail.rules import engine

        return engine.run_pass(
            self.session,
            report=self.session.sync(),
            all_accounts=[],
            now=lambda: RECU + 600,
        )

    def raisons(self, rule):
        return [
            e["reason"]
            for e in self.store.rule_log_entries(rule.id)
            if e["at"] > RECU
        ]

    @staticmethod
    def entetes(contenu: bytes) -> bytes:
        return contenu.split(b"\r\n\r\n", 1)[0]

    def test_inline_forward_reaches_the_targets_with_its_attachment(self):
        self.regle("inline")
        bilan = self.passe()
        self.assertEqual((bilan.sent, bilan.status), (1, "ok"))
        self.assertEqual(len(self.smtp.messages), 1)
        sorti = self.smtp.messages[0]
        self.assertEqual(sorti.mail_from, OWN)
        self.assertEqual(sorti.rcpt_tos, [CAROLE, DENIS])
        msg = email.message_from_bytes(
            sorti.content, policy=email.policy.default
        )
        self.assertEqual(msg["To"], "undisclosed-recipients:;")
        self.assertEqual(msg["Reply-To"], BRUNO)
        self.assertEqual(msg["Subject"], "Fwd: Devis à relayer")
        self.assertEqual(msg["Auto-Submitted"], "auto-generated")
        self.assertIsNone(msg["X-ERPLibre-Bcc"])
        types = [part.get_content_type() for part in msg.walk()]
        for attendu in ("multipart/related", "image/png", "application/pdf"):
            self.assertIn(attendu, types)
        pdf = next(
            p for p in msg.walk() if p.get_content_type() == "application/pdf"
        )
        self.assertEqual(pdf.get_content(), PDF)
        texte = msg.get_body(("plain",)).get_content()
        self.assertTrue(texte.startswith("Transmis par la boîte des règles."))
        self.assertIn("Bonjour, voici le devis.", texte)
        html = msg.get_body(("html",)).get_content()
        self.assertIn("cid:logo@example.net", html)

    def test_redirect_arrives_byte_for_byte_after_one_resent_block(self):
        from script.todo.mail.smtp_send import (
            REDIRECT_DROPPED_FIELDS,
            strip_header_fields,
            to_crlf,
        )

        self.regle("redirect")
        self.assertEqual(self.passe().sent, 1)
        sorti = self.smtp.messages[0]
        self.assertEqual(sorti.rcpt_tos, [CAROLE, DENIS])
        lignes = sorti.content.split(b"\r\n")
        bloc = 0
        while lignes[bloc].startswith(b"Resent-") or lignes[bloc][:1] in (
            b" ",
            b"\t",
        ):
            bloc += 1
        noms = [
            ligne.split(b":", 1)[0]
            for ligne in lignes[:bloc]
            if ligne.startswith(b"Resent-")
        ]
        self.assertEqual(
            noms, [b"Resent-From", b"Resent-Date", b"Resent-Message-ID"]
        )
        reste = b"\r\n".join(lignes[bloc:])
        attendu = to_crlf(
            strip_header_fields(self.brut, REDIRECT_DROPPED_FIELDS)
        )
        self.assertEqual(reste.rstrip(b"\r\n"), attendu.rstrip(b"\r\n"))
        self.assertNotIn(b"\r\nBcc:", sorti.content)
        self.assertNotIn(b"Return-Path:", sorti.content)
        # Rien n'est classé dans Envoyés pour une redirection.
        self.assertEqual(self.sent.appended, [])

    def test_the_envelope_never_reaches_the_original_cc_or_bcc(self):
        self.regle("inline")
        self.regle("attachment")
        self.regle("redirect")
        self.assertEqual(self.passe().sent, 3)
        self.assertEqual(len(self.smtp.messages), 3)
        for sorti in self.smtp.messages:
            with self.subTest(debut=sorti.content[:40]):
                self.assertEqual(sorti.rcpt_tos, [CAROLE, DENIS])
                self.assertNotIn(b"\nBcc:", sorti.content)
                self.assertNotIn(b"X-ERPLibre-Bcc", sorti.content)

    def test_the_original_stays_unread(self):
        self.regle("inline")
        self.passe()
        self.assertIsNotNone(self.store.read_body("INBOX", 1))
        for message in self.inbox.messages:
            self.assertNotIn("\\Seen", message.flags)

    def test_the_forward_is_filed_in_sent_and_the_redirect_is_not(self):
        self.regle("inline")
        self.regle("redirect")
        self.assertEqual(self.passe().sent, 2)
        self.assertEqual(len(self.sent.appended), 1)
        copie = self.sent.appended[0][0]
        self.assertIn(b"Fwd: ", copie)
        self.assertNotIn(b"X-ERPLibre-Bcc", copie)
        self.assertNotIn(b"Resent-From", copie)

    def test_a_target_redirecting_back_causes_no_loop(self):
        """Revenue telle quelle, la redirection porte le Message-ID de
        l'original : `duplicate`, qui ne se journalise pas. Sous un
        Message-ID réécrit en route, le bloc `Resent-From` de ce compte
        l'arrête : `resent_loop`."""
        rule = self.regle("redirect")
        self.passe()
        retour = self.smtp.messages[0].content
        self.inbox.deliver(retour, uid=2, internal_date=RECU_IMAP)
        self.assertEqual(self.passe().sent, 0)
        self.assertEqual(self.raisons(rule), [None])
        reecrit = retour.replace(
            b"Message-ID: <relais1@example.net>",
            b"Message-ID: <relais1-retour@example.org>",
        )
        self.assertNotEqual(reecrit, retour)
        self.inbox.deliver(reecrit, uid=3, internal_date=RECU_IMAP)
        bilan = self.passe()
        self.assertEqual((bilan.sent, bilan.skipped["resent_loop"]), (0, 1))
        self.assertEqual(len(self.smtp.messages), 1)
        self.assertEqual(self.raisons(rule)[0], "resent_loop")

    def test_a_target_forwarding_back_causes_no_loop(self):
        rule = self.regle("inline", targets=(CAROLE,))
        self.passe()
        self.inbox.deliver(
            message(CAROLE, OWN, "<2@example.org>", "Fwd: Devis", RECU),
            uid=2,
            internal_date=RECU_IMAP,
        )
        bilan = self.passe()
        self.assertEqual(
            (bilan.sent, bilan.skipped["no_forward_target"]), (0, 1)
        )
        self.assertEqual(len(self.smtp.messages), 1)
        self.assertEqual(self.raisons(rule)[0], "no_forward_target")

    def test_a_target_auto_reply_causes_no_loop(self):
        rule = self.regle("redirect")
        self.passe()
        self.inbox.deliver(
            message(
                CAROLE,
                OWN,
                "<absence@example.org>",
                "Absente : Devis à relayer",
                RECU,
                "Auto-Submitted: auto-replied",
                "In-Reply-To: <relais1@example.net>",
            ),
            uid=2,
            internal_date=RECU_IMAP,
        )
        bilan = self.passe()
        self.assertEqual((bilan.sent, bilan.skipped["auto_reply"]), (0, 1))
        self.assertEqual(len(self.smtp.messages), 1)
        self.assertEqual(self.raisons(rule)[0], "auto_reply")

    def test_the_targets_never_see_each_other(self):
        self.regle("inline")
        self.regle("redirect")
        self.passe()
        self.assertEqual(len(self.smtp.messages), 2)
        for sorti in self.smtp.messages:
            entetes = self.entetes(sorti.content)
            with self.subTest(debut=entetes[:40]):
                self.assertNotIn(CAROLE.encode(), entetes)
                self.assertNotIn(DENIS.encode(), entetes)
                self.assertNotIn(b"Resent-To", entetes)

    def test_a_second_pass_sends_nothing(self):
        self.regle("inline")
        self.regle("redirect")
        self.assertEqual(self.passe().sent, 2)
        bilan = self.passe()
        self.assertEqual(bilan.sent, 0)
        self.assertEqual(len(self.smtp.messages), 2)


if __name__ == "__main__":
    unittest.main()
