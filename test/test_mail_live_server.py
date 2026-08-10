#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les tests courriel qui parlent à un VRAI serveur.

Tous les autres tests du paquet `mail` passent par un double. Ceux-ci ouvrent
une socket sur 127.0.0.1, vers un serveur IMAP (Twisted) et un serveur SMTP
(aiosmtpd) démarrés puis tués par le test lui-même — voir `mail_sandbox.py`.

Ce qu'on cherche n'est PAS la conformité : c'est de reproduire ce qu'un
double n'aurait jamais produit, parce que son auteur ne l'avait pas imaginé.
Chaque classe ci-dessous nomme le risque réel qu'elle couvre.

Ils NE tournent PAS dans la boucle rapide : sans `twisted` ni `aiosmtpd`,
tout le fichier se saute proprement. Pour les lancer volontairement :

    .venv.erplibre/bin/python -m unittest discover -s test \\
        -p test_mail_live_server.py -v
"""
import email.utils
import threading
import unittest
import unittest.mock

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
        LIVE_SERVERS,
        PASSWORD,
        DropConnection,
        MailSandboxCase,
        RefuseCommand,
        port_is_closed,
        sandbox_account,
    )

requires_servers = unittest.skipIf(
    bool(SANDBOX_MISSING),
    f"serveurs de test absents ({SANDBOX_MISSING})"
    " : pip install -r requirement/erplibre_require-ments.txt",
)

# Le message qui a cassé la production. Deux méchancetés en une : un mot
# encodé RFC 2047 qui annonce `unknown-8bit`, étiquette qu'aucun codec Python
# ne connaît, et un `From` qui porte des octets 8 bits BRUTS, sans encodage
# d'aucune sorte. Les deux existent en vrai ; aucun double ne les produisait.
HOSTILE = (
    b"From: Ren\xe9 Lavall\xe9e <rene@example.org>\r\n"
    b"To: moi@example.ca\r\n"
    b"Subject: =?unknown-8bit?Q?sujet_h=E9rit=E9?=\r\n"
    b"Date: Wed, 06 Aug 2026 10:00:00 +0000\r\n"
    b"Message-ID: <hostile-1@example.org>\r\n"
    b'Content-Type: text/plain; charset="unknown-8bit"\r\n'
    b"\r\n"
    b"Bonjour, corps accentu\xe9.\r\n"
)


def polite(uid: int, subject: str = "Devis") -> bytes:
    """Un message ordinaire, servi par le chemin normal de Twisted."""
    return (
        f"From: Alice <alice@example.org>\r\n"
        f"To: moi@example.ca\r\n"
        f"Subject: {subject}\r\n"
        f"Date: Wed, 06 Aug 2026 10:0{uid}:00 +0000\r\n"
        f"Message-ID: <poli-{uid}@example.org>\r\n"
        f"\r\n"
        f"Corps du message {uid}.\r\n"
    ).encode()


@requires_servers
class TestUnknown8bitDoesNotAbortSync(MailSandboxCase):
    """Bug 1 : `unknown encoding: unknown-8bit` arrêtait la sync d'un dossier
    pour de bon — le dossier échouait à chaque passe, donc son `last_uid`
    n'avançait jamais et l'utilisateur ne voyait plus rien arriver.

    Le risque couvert : un en-tête qu'aucun codec Python ne sait lire ne doit
    pas coûter le dossier. Ici l'étiquette arrive VRAIMENT du réseau, décodée
    par `imaplib` puis `parse_fetch_headers`, et non fabriquée par le test.
    """

    def setUp(self):
        self.imap = self.imap_server()
        self.imap.folder("INBOX").deliver(HOSTILE, flags=["\\Seen"])
        self.account = sandbox_account(imap_port=self.imap.port)
        self.store = self.temp_store(self.account)
        self.transport = self.imap_transport(self.imap, self.account)

    def sync(self):
        from script.todo.mail.imap_sync import Syncer

        return Syncer(self.store, self.transport).sync()

    def stored(self):
        state = self.store.folder_state("INBOX")
        return self.store.list_messages(state["id"])

    def test_sync_reports_no_error(self):
        self.assertEqual(self.sync().errors, [])

    def test_the_message_is_stored(self):
        self.sync()
        self.assertEqual(len(self.stored()), 1)

    def test_the_unknown_charset_is_substituted_not_fatal(self):
        """`charset.decode_bytes` remplace ce qu'il ne sait pas lire. Sans ce
        garde-fou, `decode_header` lève `LookupError` et le message n'existe
        pas du tout."""
        self.sync()
        subject = self.stored()[0].subject
        self.assertTrue(subject.startswith("sujet h"))
        self.assertIn("�", subject)

    def test_raw_8bit_header_bytes_survive_the_wire(self):
        """Le `From` part en octets 8 bits bruts, sans encodage : c'est ce
        que fait un vrai MTA relâché, et ce que Twisted refuse de reformater
        (voir `SandboxIMAP4Server.spew_body`)."""
        self.sync()
        self.assertIn("Lavall", self.stored()[0].frm)
        self.assertIn("rene@example.org", self.stored()[0].frm)

    def test_the_body_still_yields_a_snippet(self):
        """Le corps porte le même charset inconnu : ouvrir le message ne doit
        pas échouer non plus."""
        from script.todo.mail.imap_sync import Syncer

        syncer = Syncer(self.store, self.transport)
        syncer.sync()
        raw = syncer.fetch_body("INBOX", 1)
        self.assertIn(b"Bonjour", raw)
        self.assertIn("Bonjour", self.stored()[0].snippet)

    def test_the_bytes_are_served_verbatim(self):
        """Le corps rendu par le serveur est OCTET POUR OCTET celui déclaré :
        si le bac à sable réécrivait quoi que ce soit, il ne prouverait plus
        rien sur le vrai réseau."""
        from script.todo.mail.imap_sync import Syncer

        syncer = Syncer(self.store, self.transport)
        syncer.sync()
        self.assertEqual(syncer.fetch_body("INBOX", 1), HOSTILE)


@requires_servers
class TestWhatLeavesBySmtp(MailSandboxCase):
    """Le risque couvert : le Cci ne doit JAMAIS apparaître dans un en-tête.

    C'est la propriété de sécurité que tout le plan protège, et jusqu'ici
    elle n'était vérifiée que sur l'objet `EmailMessage` que nous tenions en
    main. Ici on l'affirme sur les OCTETS reçus à l'autre bout de la socket —
    ce que le serveur a vraiment lu.
    """

    def setUp(self):
        from script.todo.mail import smtp_send

        self.smtp = self.smtp_server()
        self.account = sandbox_account(
            smtp_port=self.smtp.port,
            address="moi@example.ca",
            display_name="Mathieu Benoit",
        )
        self.transport = smtp_send.connect(self.account, PASSWORD)
        self.addCleanup(self.transport.quit)
        self.msg = smtp_send.build_message(
            self.account,
            ["alice@example.org"],
            "Devis daté d'août",
            "Bonjour Alice",
            cc=["copie@example.org"],
            bcc=["cache@example.org"],
            date="Fri, 01 Aug 2026 10:41:00 +0000",
            msgid="<fixe@erplibre>",
        )
        self.served = smtp_send.send(self.account, self.msg, self.transport)

    @property
    def sent(self):
        return self.smtp.messages[0]

    def test_the_server_received_exactly_one_message(self):
        self.assertEqual(len(self.smtp.messages), 1)

    def test_bcc_is_absent_from_the_bytes_that_left(self):
        self.assertNotIn(b"cache@example.org", self.sent.content)
        self.assertNotIn(b"Bcc", self.sent.content)
        self.assertNotIn(b"X-ERPLibre-Bcc", self.sent.content)

    def test_bcc_is_absent_from_every_header(self):
        parsed = self.sent.headers()
        self.assertIsNone(parsed.get("Bcc"))
        self.assertIsNone(parsed.get("X-ERPLibre-Bcc"))

    def test_bcc_is_served_by_the_envelope(self):
        """Caché ne veut pas dire non livré : le Cci ne vit que dans
        l'enveloppe SMTP, que le serveur nous rend ici telle qu'il l'a
        reçue."""
        self.assertIn("cache@example.org", self.sent.rcpt_tos)
        self.assertEqual(
            sorted(self.sent.rcpt_tos),
            sorted(
                ["alice@example.org", "copie@example.org", "cache@example.org"]
            ),
        )

    def test_the_envelope_sender_is_the_account(self):
        self.assertEqual(self.sent.mail_from, "moi@example.ca")

    def test_send_reports_the_recipients_it_served(self):
        self.assertEqual(sorted(self.served), sorted(self.sent.rcpt_tos))

    def test_nothing_8bit_left_on_the_wire(self):
        """Un en-tête accentué doit partir encodé RFC 2047. Sorti brut, il
        serait mutilé par le premier relais venu — et c'est exactement le
        genre d'octet qui nous est revenu en `unknown-8bit`."""
        headers = self.sent.content.split(b"\r\n\r\n", 1)[0]
        headers.decode("ascii")  # lève si un octet 8 bits a fui

    def test_the_accented_subject_arrives_intact(self):
        self.assertEqual(
            self.sent.headers()["Subject"],
            "Devis =?utf-8?q?dat=C3=A9_d=27ao=C3=BBt?=",
        )
        from script.todo.mail.imap_transport import decode_header_value

        self.assertEqual(
            decode_header_value(self.sent.headers()["Subject"]),
            "Devis daté d'août",
        )

    def test_the_visible_headers_are_the_ones_we_built(self):
        parsed = self.sent.headers()
        self.assertEqual(parsed["From"], "Mathieu Benoit <moi@example.ca>")
        self.assertEqual(parsed["To"], "alice@example.org")
        self.assertEqual(parsed["Cc"], "copie@example.org")
        self.assertEqual(parsed["Message-ID"], "<fixe@erplibre>")


@requires_servers
class TestSmtpRefusals(MailSandboxCase):
    """Le risque couvert : un refus du serveur doit devenir une `SmtpError`
    lisible, jamais une exception brute remontée dans le TUI."""

    def test_a_wrong_password_is_an_smtp_error(self):
        """Le serveur EXIGE l'authentification et la refuse pour de vrai —
        un 535 sur le fil, pas une exception injectée.

        La sous-classe ne change rien au protocole : elle ne sert qu'à
        retenir la connexion pour la fermer. `smtp_send.connect()` ne ferme
        pas sa socket quand `login()` échoue — elle traîne jusqu'au
        ramasse-miettes, ce qui est bénin dans le TUI mais laisserait ici un
        `ResourceWarning` attaché à un test au hasard.
        """
        import smtplib

        from script.todo.mail.smtp_send import SmtpError, connect

        opened = []

        class Recording(smtplib.SMTP):
            def __init__(inner, *args, **kwargs):
                super().__init__(*args, **kwargs)
                opened.append(inner)

        smtp = self.smtp_server(require_auth=True)
        account = sandbox_account(smtp_port=smtp.port)
        with unittest.mock.patch("smtplib.SMTP", Recording):
            with self.assertRaises(SmtpError):
                connect(account, "mauvais-mot-de-passe")
        for client in opened:
            client.close()

    def test_a_closed_port_is_an_smtp_error(self):
        """Le serveur est démarré puis tué : le port est fermé pour de bon,
        et personne d'autre n'écoute dessus."""
        from script.todo.mail.smtp_send import SmtpError, connect

        smtp = self.smtp_server()
        port = smtp.port
        smtp.stop()
        account = sandbox_account(smtp_port=port)
        with self.assertRaises(SmtpError):
            connect(account, PASSWORD)


@requires_servers
class TestConnectionDroppedMidSync(MailSandboxCase):
    """Le risque couvert : une coupure en pleine passe ne doit ni faire
    tomber le TUI, ni PERDRE des messages en avançant `last_uid` sur des
    en-têtes jamais reçus. Aucun double ne coupe jamais la ligne : il répond
    toujours.
    """

    def setUp(self):
        self.imap = self.imap_server()
        inbox = self.imap.folder("INBOX")
        for uid in (1, 2, 3):
            inbox.deliver(polite(uid), uid=uid)
        self.account = sandbox_account(imap_port=self.imap.port)
        self.store = self.temp_store(self.account)

    def syncer(self):
        from script.todo.mail.imap_sync import Syncer

        return Syncer(self.store, self.imap_transport(self.imap, self.account))

    def test_a_drop_is_reported_not_raised(self):
        self.imap.fail(DropConnection(b"FETCH"))
        with self.assertLogs("script.todo.mail.imap_sync", level="ERROR"):
            report = self.syncer().sync()
        self.assertEqual(len(report.errors), 1)
        self.assertIn("INBOX", report.errors[0])

    def test_a_drop_before_the_headers_loses_nothing(self):
        """La coupure tombe sur le tout premier FETCH : rien n'a été stocké,
        donc `last_uid` ne doit pas avoir bougé — sinon les trois messages
        seraient sautés pour toujours."""
        self.imap.fail(DropConnection(b"FETCH"))
        with self.assertLogs("script.todo.mail.imap_sync", level="ERROR"):
            self.syncer().sync()
        state = self.store.folder_state("INBOX")
        self.assertEqual(state["last_uid"], 0)

    def test_the_next_pass_recovers_every_message(self):
        self.imap.fail(DropConnection(b"FETCH"))
        with self.assertLogs("script.todo.mail.imap_sync", level="ERROR"):
            self.syncer().sync()
        self.imap.faults.clear()
        report = self.syncer().sync()
        self.assertEqual(report.errors, [])
        self.assertEqual(report.new_messages, 3)
        state = self.store.folder_state("INBOX")
        self.assertEqual(
            sorted(m.uid for m in self.store.list_messages(state["id"])),
            [1, 2, 3],
        )

    def test_a_drop_after_the_headers_keeps_what_arrived(self):
        """Cette fois la coupure tombe sur le FETCH des drapeaux, après que
        les en-têtes soient descendus : le travail déjà fait doit rester."""
        self.imap.fail(DropConnection(b"FETCH", after=1))
        with self.assertLogs("script.todo.mail.imap_sync", level="ERROR"):
            report = self.syncer().sync()
        self.assertEqual(report.new_messages, 3)
        state = self.store.folder_state("INBOX")
        self.assertEqual(len(self.store.list_messages(state["id"])), 3)

    def test_a_refused_folder_does_not_cost_the_others(self):
        """Un NO sur un dossier — droits, quota, boîte verrouillée — laisse
        le reste de la boîte utilisable. Ici le refus vient du serveur, pas
        d'une exception que le test aurait injectée."""
        self.imap.folder("INBOX.Archive").deliver(polite(9), uid=9)
        self.imap.fail(
            RefuseCommand(b"SELECT", after=1, text=b"Mailbox locked")
        )
        with self.assertLogs("script.todo.mail.imap_sync", level="ERROR"):
            report = self.syncer().sync()
        self.assertEqual(report.folders, 2)
        self.assertEqual(len(report.errors), 1)
        self.assertEqual(report.new_messages, 3)


@requires_servers
class TestSentCopyLandsOnTheServer(MailSandboxCase):
    """Bug 3 : la liste montrait un état périmé après un envoi.

    Le chemin réel est APPEND puis `sync_one` sur le dossier Envoyés. Le
    risque couvert : la copie doit exister CHEZ LE SERVEUR, sous l'UID que le
    serveur attribue — pas un UID inventé localement, qui entrerait en
    collision avec un futur message réel — et elle ne doit pas rouvrir la
    porte du Cci par ce second chemin.
    """

    def setUp(self):
        from script.todo.mail import smtp_send

        self.imap = self.imap_server()
        self.sent_box = self.imap.folder("INBOX.Sent")
        self.sent_box.deliver(polite(1, "Un envoi précédent"), uid=1)
        self.account = sandbox_account(
            imap_port=self.imap.port, sent_folder="INBOX.Sent"
        )
        self.store = self.temp_store(self.account)
        self.transport = self.imap_transport(self.imap, self.account)
        self.msg = smtp_send.build_message(
            self.account,
            ["alice@example.org"],
            "Copie classée",
            "Bonjour",
            bcc=["cache@example.org"],
            date="Fri, 01 Aug 2026 10:41:00 +0000",
            msgid="<copie@erplibre>",
        )

    def file_the_copy(self):
        """Exactement ce que fait `deliver()` dans `tui.py` : `without_bcc`
        puis APPEND, puis une sync ciblée."""
        from script.todo.mail.imap_sync import Syncer
        from script.todo.mail.smtp_send import without_bcc

        self.transport.append(
            self.account.sent_folder,
            without_bcc(self.msg).as_bytes(),
            ["\\Seen"],
        )
        return Syncer(self.store, self.transport).sync_one(
            self.account.sent_folder
        )

    def test_the_server_accepted_the_append(self):
        self.file_the_copy()
        self.assertEqual(len(self.sent_box.appended), 1)

    def test_the_copy_the_server_stored_carries_no_bcc(self):
        """Assertion sur les octets DÉPOSÉS, pas sur notre objet en mémoire :
        c'est la seconde porte par laquelle le Cci pourrait fuir."""
        self.file_the_copy()
        stored, _flags = self.sent_box.appended[0]
        self.assertNotIn(b"cache@example.org", stored)
        self.assertNotIn(b"X-ERPLibre-Bcc", stored)

    def test_the_flags_we_asked_for_reached_the_server(self):
        self.file_the_copy()
        _stored, flags = self.sent_box.appended[0]
        self.assertIn("\\Seen", flags)

    def test_the_copy_shows_up_in_the_list(self):
        report = self.file_the_copy()
        self.assertEqual(report.errors, [])
        state = self.store.folder_state("INBOX.Sent")
        subjects = {m.subject for m in self.store.list_messages(state["id"])}
        self.assertIn("Copie classée", subjects)

    def test_the_uid_comes_from_the_server(self):
        """La boîte contenait déjà un message : la copie doit porter l'UID 2,
        celui que le serveur a attribué."""
        self.file_the_copy()
        state = self.store.folder_state("INBOX.Sent")
        stored = {
            m.subject: m.uid for m in self.store.list_messages(state["id"])
        }
        self.assertEqual(stored["Copie classée"], 2)


@requires_servers
class TestFolderListing(MailSandboxCase):
    """Le risque couvert : les noms de dossiers viennent d'une réponse LIST
    réelle, avec son délimiteur, ses guillemets et son UTF-7 modifié, pas
    d'une chaîne que le test aurait écrite dans le format qui l'arrange.

    C'est ce que le bac à sable donne gratuitement : Twisted encode de
    lui-même le nom accentué en UTF-7 modifié (RFC 3501), un aller-retour
    qu'aucun double n'avait jamais fait faire à `decode_mailbox`.
    """

    ACCENTED = "INBOX.Courriels envoyés"

    def setUp(self):
        self.imap = self.imap_server()
        for name in ("INBOX", "INBOX.Sent", self.ACCENTED):
            self.imap.folder(name).deliver(polite(1), uid=1)
        self.transport = self.imap_transport(self.imap)

    def test_every_folder_is_listed(self):
        self.assertEqual(len(self.transport.list_folders()), 3)

    def test_the_accented_name_arrives_in_modified_utf7(self):
        """Le nom BRUT est celui du fil — c'est lui qu'il faudra renvoyer au
        serveur pour sélectionner le dossier, pas sa version lisible."""
        names = {f.name for f in self.transport.list_folders()}
        self.assertIn("INBOX.Courriels envoy&AOk-s", names)

    def test_the_accented_name_is_decoded_for_display(self):
        display = {f.name: f.display for f in self.transport.list_folders()}
        self.assertEqual(display["INBOX.Courriels envoy&AOk-s"], self.ACCENTED)

    def test_inbox_gets_its_role_from_its_name(self):
        roles = {f.name: f.role for f in self.transport.list_folders()}
        self.assertEqual(roles["INBOX"], "inbox")

    def test_no_special_use_role_is_announced(self):
        """LACUNE ASSUMÉE — bug 2 (le dossier Envoyés annoncé par le serveur)
        reste hors de portée : Twisted n'annonce que
        `IMAP4REV1 NAMESPACE IDLE`, sans `SPECIAL-USE`. Implémenter
        l'extension nous-mêmes reviendrait à tester notre propre supposition
        sur elle — précisément l'erreur que ce bac à sable existe pour
        éviter. Ce test verrouille la lacune au lieu de la maquiller : le
        jour où un serveur de test l'annoncera, il échouera et rappellera
        qu'il y a mieux à écrire."""
        self.assertNotIn(
            "SPECIAL-USE",
            str(self.transport.client.capabilities).upper(),
        )
        roles = {f.role for f in self.transport.list_folders()}
        self.assertEqual(roles - {"inbox"}, {None})


@requires_servers
class TestSandboxLifecycle(MailSandboxCase):
    """Le risque couvert : une socket d'écoute oubliée ou un fil coincé
    empoisonneraient toute la suite. Ces tests-ci vérifient le bac à sable
    lui-même, pas le client."""

    def test_ports_are_ephemeral_and_distinct(self):
        first, second = self.imap_server(), self.imap_server()
        self.assertNotEqual(first.port, 0)
        self.assertNotEqual(first.port, second.port)

    def test_a_failing_test_still_closes_its_servers(self):
        """La preuve de non-fuite : on fait ÉCHOUER un test à l'intérieur du
        test, et on vérifie que ses serveurs sont morts quand même."""
        ports = {}

        class Doomed(MailSandboxCase):
            def runTest(inner):
                ports["imap"] = inner.imap_server().port
                ports["smtp"] = inner.smtp_server().port
                inner.fail("échec provoqué")

        before = set(LIVE_SERVERS)
        result = unittest.TestResult()
        Doomed().run(result)

        self.assertEqual(len(result.failures), 1)
        self.assertEqual(set(LIVE_SERVERS), before)
        self.assertTrue(port_is_closed(ports["imap"]))
        self.assertTrue(port_is_closed(ports["smtp"]))

    def test_an_open_client_session_does_not_survive_the_test(self):
        """`stopListening` seul cesse d'ACCEPTER : une session cliente restée
        ouverte garderait un descripteur vivant d'un test à l'autre."""
        ports = {}

        class LeavesAClientBehind(MailSandboxCase):
            def runTest(inner):
                sandbox = inner.imap_server()
                sandbox.folder("INBOX")
                ports["imap"] = sandbox.port
                inner.imap_transport(sandbox)  # jamais fermée par le test

        result = unittest.TestResult()
        LeavesAClientBehind().run(result)
        self.assertEqual(result.errors, [])
        self.assertTrue(port_is_closed(ports["imap"]))

    def test_only_one_reactor_thread_exists(self):
        """Le cœur du choix de conception : le réacteur Twisted ne se
        redémarre pas, donc il n'y en a qu'UN pour toute la session, quel que
        soit le nombre de serveurs démarrés."""
        self.imap_server()
        self.imap_server()
        reactors = [
            th
            for th in threading.enumerate()
            if th.name == "mail-sandbox-reactor"
        ]
        self.assertEqual(len(reactors), 1)

    def test_smtp_threads_do_not_pile_up(self):
        """`aiosmtpd` porte sa propre boucle asyncio dans un fil : chaque
        serveur arrêté doit rendre le sien."""
        before = threading.active_count()
        for _ in range(3):
            self.smtp_server().stop()
        self.assertLessEqual(threading.active_count(), before)


@requires_servers
class TestSandboxServesWhatWasDeclared(MailSandboxCase):
    """Le bac à sable n'est utile que s'il ne réécrit rien. Si ces
    assertions-là tombent, tous les autres tests de ce fichier ne prouvent
    plus rien sur le vrai réseau."""

    def selected(self, imap, folder="INBOX"):
        transport = self.imap_transport(imap)
        transport.select(folder)
        return transport

    def test_a_polite_message_goes_through_twisteds_own_path(self):
        """Par défaut le serveur est POLI : les en-têtes ASCII sont formatés
        par Twisted, pas par nous (voir `SandboxIMAP4Server.spew_body`)."""
        imap = self.imap_server()
        imap.folder("INBOX").deliver(polite(1, "Devis"), uid=1)
        headers = self.selected(imap).fetch_headers([1])
        self.assertEqual(headers[0].subject, "Devis")
        self.assertEqual(headers[0].msgid, "<poli-1@example.org>")

    def test_flags_and_size_come_from_the_server(self):
        imap = self.imap_server()
        raw = polite(1)
        imap.folder("INBOX").deliver(raw, flags=["\\Seen"], uid=1)
        headers = self.selected(imap).fetch_headers([1])
        self.assertIn("\\Seen", headers[0].flags)
        self.assertEqual(headers[0].size, len(raw))

    def test_the_date_is_parsed_from_the_served_header(self):
        imap = self.imap_server()
        imap.folder("INBOX").deliver(polite(1), uid=1)
        headers = self.selected(imap).fetch_headers([1])
        expected = int(
            email.utils.parsedate_to_datetime(
                "Wed, 06 Aug 2026 10:01:00 +0000"
            ).timestamp()
        )
        self.assertEqual(headers[0].date, expected)

    def test_only_the_requested_uids_come_back(self):
        imap = self.imap_server()
        for uid in (1, 2, 3):
            imap.folder("INBOX").deliver(polite(uid), uid=uid)
        headers = self.selected(imap).fetch_headers([2])
        self.assertEqual([h.uid for h in headers], [2])

    def test_lf_only_line_endings_are_still_split_correctly(self):
        """`EmailMessage.as_bytes()` — ce que le client dépose par APPEND —
        termine ses lignes en LF SEUL, alors que le fil IMAP est en CRLF.

        Le message commence par un `Received` que le client ne demande pas,
        comme tout message ayant traversé un relais. Un découpage qui
        n'attendrait que du CRLF verrait UNE seule ligne, nommée `Received`,
        donc hors du filtre : le bloc rendu serait VIDE, sans rien lever.
        L'octet 8 bits dans `From` force le chemin verbatim, le seul où ce
        découpage sert.
        """
        imap = self.imap_server()
        raw = (
            "Received: from relais.example.org by example.ca; "
            "Wed, 06 Aug 2026 10:01:00 +0000\n"
            "From: Ren\xe9 <rene@example.org>\n"
            "To: moi@example.ca\n"
            "Subject: Devis\n"
            "Date: Wed, 06 Aug 2026 10:01:00 +0000\n"
            "Message-ID: <lf-1@example.org>\n"
            "\n"
            "Corps.\n"
        ).encode("latin-1")
        imap.folder("INBOX").deliver(raw, uid=1)
        headers = self.selected(imap).fetch_headers([1])
        self.assertEqual(headers[0].msgid, "<lf-1@example.org>")
        self.assertEqual(headers[0].subject, "Devis")
        self.assertIn("rene@example.org", headers[0].frm)

    def test_search_only_returns_uids_at_or_above_the_mark(self):
        imap = self.imap_server()
        for uid in (1, 2, 3):
            imap.folder("INBOX").deliver(polite(uid), uid=uid)
        self.assertEqual(self.selected(imap).search_uids(2), [2, 3])

    def test_store_flags_reaches_the_server(self):
        imap = self.imap_server()
        box = imap.folder("INBOX")
        box.deliver(polite(1), uid=1)
        transport = self.selected(imap)
        transport.store_flags(1, ["\\Seen"], [])
        self.assertEqual(transport.fetch_flags([1]), [(1, "\\Seen")])
        self.assertEqual(box.messages[0].flags, ["\\Seen"])


if __name__ == "__main__":
    unittest.main()
