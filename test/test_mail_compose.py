#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.smtp_send import SmtpError, build_message
from script.todo.mail.store import MessageMeta, Store
from script.todo.mail.tui import (
    MailboxRef,
    Session,
    append_attachment_path,
    deliver,
    edit_in_external_editor,
    parse_paths,
    parse_recipients,
    resolve_sent_folder,
)


class TestParseRecipients(unittest.TestCase):
    def test_single(self):
        self.assertEqual(parse_recipients("a@y.ca"), ["a@y.ca"])

    def test_comma_separated(self):
        self.assertEqual(
            parse_recipients("a@y.ca, b@y.ca"), ["a@y.ca", "b@y.ca"]
        )

    def test_semicolon_also_works(self):
        self.assertEqual(
            parse_recipients("a@y.ca; b@y.ca"), ["a@y.ca", "b@y.ca"]
        )

    def test_keeps_display_names(self):
        self.assertEqual(
            parse_recipients("Alice <a@y.ca>, b@y.ca"),
            ["Alice <a@y.ca>", "b@y.ca"],
        )

    def test_drops_empty_fragments(self):
        self.assertEqual(
            parse_recipients("a@y.ca,,  ,b@y.ca"), ["a@y.ca", "b@y.ca"]
        )

    def test_empty_string(self):
        self.assertEqual(parse_recipients(""), [])


class TestParsePaths(unittest.TestCase):
    """Contrairement aux destinataires, les chemins de pièces jointes ne se
    séparent QUE par un point-virgule : une virgule est légale dans un nom de
    fichier (`Facture, T3.pdf`)."""

    def test_single(self):
        self.assertEqual(parse_paths("a.pdf"), ["a.pdf"])

    def test_comma_in_a_filename_survives(self):
        self.assertEqual(parse_paths("Facture, T3.pdf"), ["Facture, T3.pdf"])

    def test_semicolon_separates(self):
        self.assertEqual(parse_paths("a.pdf; b.pdf"), ["a.pdf", "b.pdf"])

    def test_double_quoted_path_is_unquoted(self):
        self.assertEqual(parse_paths('"a, b.pdf"'), ["a, b.pdf"])

    def test_single_quoted_path_is_unquoted(self):
        self.assertEqual(parse_paths("'a.pdf'"), ["a.pdf"])

    def test_drops_empty_fragments(self):
        self.assertEqual(parse_paths("a.pdf;;  ;b.pdf"), ["a.pdf", "b.pdf"])

    def test_empty_string(self):
        self.assertEqual(parse_paths(""), [])


class TestAppendAttachmentPath(unittest.TestCase):
    """`append_attachment_path` est la seule logique testable du bouton
    Parcourir : le reste (suspendre Textual, ouvrir urwid) a besoin d'un
    écran monté ou d'un vrai terminal, voir `TestBrowseFilesButton`."""

    def test_empty_field_gets_just_the_path(self):
        self.assertEqual(append_attachment_path("", "a.pdf"), "a.pdf")

    def test_appends_after_an_existing_path(self):
        self.assertEqual(
            append_attachment_path("a.pdf", "b.pdf"), "a.pdf; b.pdf"
        )

    def test_field_already_ending_in_separator_is_not_doubled(self):
        self.assertEqual(
            append_attachment_path("a.pdf;", "b.pdf"), "a.pdf; b.pdf"
        )

    def test_no_leading_separator_on_an_empty_field(self):
        self.assertFalse(append_attachment_path("", "a.pdf").startswith(";"))

    def test_none_is_treated_as_empty(self):
        self.assertEqual(append_attachment_path(None, "a.pdf"), "a.pdf")


class TestExternalEditor(unittest.TestCase):
    def test_returns_what_the_editor_wrote(self):
        def runner(cmd):
            path = Path(cmd[-1])
            path.write_text("écrit dans vim")
            return 0

        self.assertEqual(
            edit_in_external_editor("départ", editor="vim", runner=runner),
            "écrit dans vim",
        )

    def test_seeds_the_file_with_the_current_text(self):
        seen = {}

        def runner(cmd):
            seen["contenu"] = Path(cmd[-1]).read_text()
            return 0

        edit_in_external_editor("brouillon", editor="vim", runner=runner)
        self.assertEqual(seen["contenu"], "brouillon")

    def test_non_zero_exit_keeps_the_original(self):
        def runner(cmd):
            Path(cmd[-1]).write_text("ignoré")
            return 1

        self.assertEqual(
            edit_in_external_editor("départ", editor="vim", runner=runner),
            "départ",
        )

    def test_missing_editor_keeps_the_original(self):
        def runner(cmd):
            raise FileNotFoundError("pas d'éditeur")

        self.assertEqual(
            edit_in_external_editor("départ", editor="absent", runner=runner),
            "départ",
        )

    def test_temp_file_is_removed(self):
        seen = {}

        def runner(cmd):
            seen["chemin"] = Path(cmd[-1])
            return 0

        edit_in_external_editor("x", editor="vim", runner=runner)
        self.assertFalse(seen["chemin"].exists())


class DeliverCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.account = account_from_preset("perso", "moi@x.ca", "generic")
        self.store = Store(
            self.account, mode="clear", base=Path(self.tmp.name)
        )
        self.store.open()
        self.msg = build_message(self.account, "a@y.ca", "Devis", "Bonjour")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def session(self, online=True, transport=None):
        class FakeSyncer:
            def __init__(self, transport):
                self.transport = transport
                self.synced = []

            def sync_one(self, folder_name):
                self.synced.append(folder_name)

        syncer = FakeSyncer(transport) if online else None
        return Session(self.account, self.store, syncer)


class TestResolveSentFolder(DeliverCase):
    """Le préréglage (`account.sent_folder`) n'est qu'une supposition : le
    serveur annonce lui-même son dossier Envoyés par l'attribut `\\Sent`,
    que `imap_transport.parse_list_line` traduit en `role="sent"` et que
    `Syncer._sync_folder` enregistre via `store.upsert_folder`. Une fois ce
    rôle connu, il doit l'emporter sur la supposition."""

    def test_uses_the_role_the_server_announced(self):
        self.store.upsert_folder("INBOX.Sent", "Envoyés", "sent")
        self.assertEqual(resolve_sent_folder(self.session()), "INBOX.Sent")

    def test_falls_back_to_the_preset_without_a_sent_role(self):
        self.store.upsert_folder("INBOX", "INBOX", "inbox")
        self.assertEqual(
            resolve_sent_folder(self.session()), self.account.sent_folder
        )

    def test_falls_back_when_the_store_has_no_folder_yet(self):
        self.assertEqual(
            resolve_sent_folder(self.session()), self.account.sent_folder
        )

    def test_falls_back_when_the_store_is_none(self):
        session = Session(self.account, None, None)
        self.assertEqual(
            resolve_sent_folder(session), self.account.sent_folder
        )

    def test_falls_back_when_the_store_read_raises(self):
        """Round 2 de la revue : un cache verrouillé ou corrompu ne doit
        JAMAIS faire lever cette fonction. Sans ça, l'exception s'échapperait
        de `deliver()` (l'appel se fait AVANT son `try`), remonterait à
        `ComposeScreen.action_send`, et un envoi SMTP déjà réussi se
        lirait comme un échec d'ENVOI — exactement la double-envoi que la
        conception de `deliver` existe pour empêcher."""

        class BrokenStore:
            def folders(self):
                raise OSError("base verrouillée")

        session = Session(self.account, BrokenStore(), None)
        self.assertEqual(
            resolve_sent_folder(session), self.account.sent_folder
        )


class TestDeliver(DeliverCase):
    def test_sends_and_reports(self):
        """Le chemin HEUREUX, et il faut un transport pour l'emprunter.

        Sans transport, `session.syncer.transport` vaut None, l'APPEND part
        en AttributeError, et `deliver` renvoie son statut d'ÉCHEC. Le test
        passait quand même : « a@y.ca » figure dans les deux statuts, celui
        du succès comme celui de l'échec. D'où le transport ici, et une
        assertion qui distingue les deux — sinon ce test dit seulement que
        `deliver` a renvoyé quelque chose.
        """

        class FakeTransport:
            def append(self, folder, raw, flags):
                pass

        sent = []
        status = deliver(
            self.session(transport=FakeTransport()),
            self.msg,
            send_fn=lambda acc, m, tr: sent.append(m) or ["a@y.ca"],
        )
        self.assertEqual(len(sent), 1)
        self.assertIn("a@y.ca", status)
        # `⚠` et le balisage rouge sont posés par le chemin d'échec seul, et
        # ne dépendent pas de la langue — contrairement au texte traduit.
        self.assertNotIn("⚠", status)
        self.assertNotIn("[b red]", status)

    def test_appends_to_the_sent_folder(self):
        class FakeTransport:
            def __init__(self):
                self.appended = []

            def append(self, folder, raw, flags):
                self.appended.append((folder, flags))

        transport = FakeTransport()
        deliver(
            self.session(transport=transport),
            self.msg,
            send_fn=lambda acc, m, tr: ["a@y.ca"],
        )
        self.assertEqual(transport.appended[0][0], self.account.sent_folder)
        self.assertIn("\\Seen", transport.appended[0][1])

    def test_appends_to_the_resolved_folder_not_the_preset(self):
        """La couture qui compte : `resolve_sent_folder` seul ne suffit pas
        à prouver que `deliver` s'en sert réellement pour l'APPEND."""

        class FakeTransport:
            def __init__(self):
                self.appended = []

            def append(self, folder, raw, flags):
                self.appended.append((folder, flags))

        self.store.upsert_folder("INBOX.Sent", "Envoyés", "sent")
        self.assertNotEqual("INBOX.Sent", self.account.sent_folder)

        transport = FakeTransport()
        deliver(
            self.session(transport=transport),
            self.msg,
            send_fn=lambda acc, m, tr: ["a@y.ca"],
        )
        self.assertEqual(transport.appended[0][0], "INBOX.Sent")

    def test_append_failure_does_not_lose_the_send(self):
        """Le message est parti : un APPEND raté ne doit pas se lire comme un échec."""

        class BrokenTransport:
            def append(self, folder, raw, flags):
                raise OSError("dossier Envoyés introuvable")

        status = deliver(
            self.session(transport=BrokenTransport()),
            self.msg,
            send_fn=lambda acc, m, tr: ["a@y.ca"],
        )
        self.assertIn("a@y.ca", status)

    def test_append_failure_is_unmistakable_and_logged(self):
        """Round 17 : l'échec ne doit plus se lire comme un simple suffixe en
        bout de ligne — il doit ressortir (préfixe, mis en évidence) et
        laisser une trace dans le journal."""

        class BrokenTransport:
            def append(self, folder, raw, flags):
                raise OSError("dossier Envoyés introuvable")

        with self.assertLogs("script.todo.mail.tui", level="ERROR"):
            status = deliver(
                self.session(transport=BrokenTransport()),
                self.msg,
                send_fn=lambda acc, m, tr: ["a@y.ca"],
            )
        self.assertIn("a@y.ca", status)
        self.assertTrue(status.startswith("[b red]"))
        self.assertIn("dossier Envoyés introuvable", status)

    def test_offline_session_refuses(self):
        with self.assertRaises(SmtpError):
            deliver(self.session(online=False), self.msg)

    def test_send_failure_is_propagated(self):
        def boom(acc, m, tr):
            raise SmtpError("550 refus")

        with self.assertRaises(SmtpError):
            deliver(self.session(), self.msg, send_fn=boom)

    def test_successful_append_triggers_a_targeted_sync_of_sent(self):
        """Design (`docs/superpowers/specs/2026-08-02-email-tui-design.md`,
        ligne 308) : « écriture locale immédiate pour qu'il apparaisse sans
        attendre la sync ». Pas de ligne fabriquée — une sync ciblée sur
        Envoyés, puisque c'est le serveur qui attribue l'UID."""

        class FakeTransport:
            def append(self, folder, raw, flags):
                pass

        session = self.session(transport=FakeTransport())
        deliver(session, self.msg, send_fn=lambda acc, m, tr: ["a@y.ca"])
        self.assertEqual(session.syncer.synced, [self.account.sent_folder])

    def test_targeted_sync_uses_the_resolved_folder_not_the_preset(self):
        class FakeTransport:
            def append(self, folder, raw, flags):
                pass

        self.store.upsert_folder("INBOX.Sent", "Envoyés", "sent")
        self.assertNotEqual("INBOX.Sent", self.account.sent_folder)

        session = self.session(transport=FakeTransport())
        deliver(session, self.msg, send_fn=lambda acc, m, tr: ["a@y.ca"])
        self.assertEqual(session.syncer.synced, ["INBOX.Sent"])

    def test_failed_append_does_not_trigger_a_sync(self):
        """Rien à synchroniser : l'APPEND n'a pas eu lieu."""

        class BrokenTransport:
            def append(self, folder, raw, flags):
                raise OSError("dossier Envoyés introuvable")

        session = self.session(transport=BrokenTransport())
        deliver(session, self.msg, send_fn=lambda acc, m, tr: ["a@y.ca"])
        self.assertEqual(session.syncer.synced, [])

    def test_appended_copy_has_no_bcc_header(self):
        """Le Cci ne doit pas fuir par la copie qui part par IMAP.

        `send()` retire déjà `X-ERPLibre-Bcc` avant l'envoi SMTP, mais la
        copie déposée dans Envoyés part par IMAP : sans `without_bcc`, le Cci
        redeviendrait un en-tête lisible sur le serveur.
        """

        class FakeTransport:
            def __init__(self):
                self.appended = []

            def append(self, folder, raw, flags):
                self.appended.append(raw)

        msg = build_message(
            self.account, "a@y.ca", "Devis", "Bonjour", bcc="secret@y.ca"
        )
        transport = FakeTransport()
        deliver(
            self.session(transport=transport),
            msg,
            send_fn=lambda acc, m, tr: ["a@y.ca"],
        )
        self.assertNotIn(b"X-ERPLibre-Bcc", transport.appended[0])
        self.assertNotIn(b"secret@y.ca", transport.appended[0])


class TestComposeScreenMounted(unittest.IsolatedAsyncioTestCase):
    """Monte l'écran de composition pour de vrai, via `run_test()`.

    `MailApp` et `ComposeScreen` sont des classes locales à `run_tui` : rien
    ne les expose. On capte l'instance en interceptant le PREMIER
    `App.__init__` appelé pendant `run_tui(run_app=False, ...)` — un
    monkeypatch entièrement contenu à ce test, restauré dans un `finally`.

    `on_mount` lit aussi les préférences via `todo_prefs`, qui crée
    `~/.erplibre` s'il est absent : sans détourner `$HOME` vers un répertoire
    jetable, monter l'écran pour de vrai toucherait la machine.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.account = account_from_preset("perso", "moi@x.ca", "generic")
        self.store = Store(
            self.account, mode="clear", base=Path(self.tmp.name)
        )
        self.store.open()
        self.fake_home = tempfile.TemporaryDirectory()
        self._old_home = os.environ.get("HOME")
        os.environ["HOME"] = self.fake_home.name

    def tearDown(self):
        if self._old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._old_home
        self.fake_home.cleanup()
        self.store.close()
        self.tmp.cleanup()

    class _FakeSyncer:
        def __init__(self, transport):
            self.transport = transport

        def sync(self, progress=None):
            from types import SimpleNamespace

            return SimpleNamespace(new_messages=0, errors=[], purged=[])

        def sync_one(self, folder_name):
            from types import SimpleNamespace

            return SimpleNamespace(new_messages=0, errors=[], folders=1)

        def fetch_body(self, folder, uid):
            return None

    class _FakeIMAPTransport:
        def __init__(self):
            self.appended = []

        def append(self, folder, raw, flags):
            self.appended.append((folder, raw, flags))

    class _FakeSMTPTransport:
        def quit(self):
            pass

    async def _mounted_app(self, imap_transport):
        import textual.app

        from script.todo.mail.tui import run_tui

        session = Session(
            self.account,
            self.store,
            self._FakeSyncer(imap_transport),
            password="hunter2",
        )

        captured = []
        orig_init = textual.app.App.__init__

        def capturing_init(app_self, *a, **kw):
            orig_init(app_self, *a, **kw)
            captured.append(app_self)

        textual.app.App.__init__ = capturing_init
        try:
            run_tui(run_app=False, sessions=[session])
        finally:
            textual.app.App.__init__ = orig_init
        return captured[-1]

    async def test_send_failure_keeps_the_screen_up_with_the_error(self):
        from textual.screen import ModalScreen
        from textual.widgets import Input, Static, TextArea

        import script.todo.mail.smtp_send as smtp_send_mod

        app = await self._mounted_app(self._FakeIMAPTransport())
        orig_connect, orig_send = smtp_send_mod.connect, smtp_send_mod.send
        smtp_send_mod.connect = (
            lambda account, password: self._FakeSMTPTransport()
        )

        def boom(account, msg, transport):
            raise SmtpError("550 refus")

        smtp_send_mod.send = boom
        try:
            async with app.run_test() as pilot:
                await pilot.press("c")
                await pilot.pause()
                self.assertIsInstance(app.screen, ModalScreen)

                app.screen.query_one("#to", Input).value = "dest@example.com"
                app.screen.query_one("#subject", Input).value = "Sujet"
                app.screen.query_one("#body", TextArea).text = "Corps"

                await pilot.press("ctrl+s")
                await pilot.pause()

                # Le brouillon reste à l'écran, avec l'erreur du serveur.
                self.assertIsInstance(app.screen, ModalScreen)
                status = app.screen.query_one("#compose_status", Static)
                self.assertIn("550 refus", str(status.content))
        finally:
            smtp_send_mod.connect = orig_connect
            smtp_send_mod.send = orig_send

    async def test_send_success_dismisses_and_files_a_copy(self):
        from textual.screen import ModalScreen
        from textual.widgets import Input, Static, TextArea

        import script.todo.mail.smtp_send as smtp_send_mod

        imap_transport = self._FakeIMAPTransport()
        app = await self._mounted_app(imap_transport)
        orig_connect, orig_send = smtp_send_mod.connect, smtp_send_mod.send
        smtp_send_mod.connect = (
            lambda account, password: self._FakeSMTPTransport()
        )
        smtp_send_mod.send = lambda account, msg, transport: [
            "dest@example.com"
        ]
        try:
            async with app.run_test() as pilot:
                await pilot.press("c")
                await pilot.pause()

                app.screen.query_one("#to", Input).value = "dest@example.com"
                app.screen.query_one("#subject", Input).value = "Sujet"
                app.screen.query_one("#body", TextArea).text = "Corps"

                await pilot.press("ctrl+s")
                await pilot.pause()

                # L'écran s'est refermé ; le statut principal confirme l'envoi.
                self.assertNotIsInstance(app.screen, ModalScreen)
                status = app.query_one("#status", Static)
                self.assertIn("dest@example.com", str(status.content))
                self.assertEqual(
                    imap_transport.appended[0][0], self.account.sent_folder
                )
        finally:
            smtp_send_mod.connect = orig_connect
            smtp_send_mod.send = orig_send

    async def test_forward_attaches_the_original_message(self):
        """Régression : `_open_with_original` construisait un brouillon de
        transfert portant le message original en pièce jointe
        `message/rfc822`, mais ne passait que `subject`/`body` à
        `ComposeScreen` — `action_send` reconstruit le message depuis le
        formulaire, donc l'original ne partait JAMAIS. Ce test regarde le
        message réellement remis à `send()`, pas les valeurs par défaut du
        formulaire : c'est la couture que Task 12 a trouvée trouée.

        `_original_message()` est fixée directement : sa propre logique
        (cache, réseau) est déjà couverte ailleurs, et n'est pas la couture
        visée ici.
        """
        from textual.widgets import Input

        import script.todo.mail.smtp_send as smtp_send_mod

        original = build_message(
            self.account,
            "quelqu.un@ailleurs.ca",
            "Rapport trimestriel",
            "Contenu original à transférer",
        )
        session = Session(
            self.account,
            self.store,
            self._FakeSyncer(self._FakeIMAPTransport()),
            password="hunter2",
        )

        app = await self._mounted_app(self._FakeIMAPTransport())
        app._original_message = lambda: (session, original)

        captured = {}

        def capture_send(account, msg, transport):
            captured["msg"] = msg
            return ["dest@example.com"]

        orig_connect, orig_send = smtp_send_mod.connect, smtp_send_mod.send
        smtp_send_mod.connect = (
            lambda account, password: self._FakeSMTPTransport()
        )
        smtp_send_mod.send = capture_send
        try:
            async with app.run_test() as pilot:
                await pilot.press("f")
                await pilot.pause()

                app.screen.query_one("#to", Input).value = "dest@example.com"
                await pilot.press("ctrl+s")
                await pilot.pause()
        finally:
            smtp_send_mod.connect = orig_connect
            smtp_send_mod.send = orig_send

        self.assertIn("msg", captured)
        sent = captured["msg"]
        attachment_types = [
            part.get_content_type() for part in sent.iter_attachments()
        ]
        self.assertIn("message/rfc822", attachment_types)
        forwarded = next(
            part
            for part in sent.iter_attachments()
            if part.get_content_type() == "message/rfc822"
        ).get_payload(0)
        self.assertEqual(forwarded["Subject"], "Rapport trimestriel")


class TestExternalEditorSuspendsTerminal(TestComposeScreenMounted):
    """`vim`/`nano` tourne par `subprocess` et a besoin du terminal —
    Textual le tient encore et continue d'y dessiner tant qu'on ne le lui a
    pas repris. Ce test ne peut pas vérifier la reprise RÉELLE du terminal
    (il faudrait un vrai tty, voir le rapport pour la vérification
    manuelle) : il vérifie seulement que `App.suspend()` est entré AVANT
    l'appel à l'éditeur, pas après ni pas du tout."""

    async def test_suspend_wraps_the_editor_call(self):
        from textual.widgets import TextArea

        import script.todo.mail.tui as tui_mod

        app = await self._mounted_app(self._FakeIMAPTransport())
        order = []

        @contextmanager
        def fake_suspend(self_app):
            order.append("suspend")
            yield

        def fake_editor(text):
            order.append("editor")
            return "nouveau texte"

        orig_editor = tui_mod.edit_in_external_editor
        tui_mod.edit_in_external_editor = fake_editor
        try:
            async with app.run_test() as pilot:
                await pilot.press("c")
                await pilot.pause()
                # Une vraie frappe de touche, focus laissé où `c` l'a mis
                # (le champ « À » via `Input`) : `ctrl+e` est un accord de
                # contrôle, pas un caractère imprimable, donc `Input` ne le
                # capture pas pour l'insérer — contrairement à l'ancien `e`
                # nu, qu'un widget de texte avale avant qu'il n'atteigne la
                # liaison de touche de l'écran (constaté par un essai
                # isolé). C'est justement ce que corrige `ctrl+e`.
                with patch.object(type(app), "suspend", fake_suspend):
                    await pilot.press("ctrl+e")
                    await pilot.pause()

                self.assertEqual(
                    app.screen.query_one("#body", TextArea).text,
                    "nouveau texte",
                )
        finally:
            tui_mod.edit_in_external_editor = orig_editor

        self.assertEqual(order, ["suspend", "editor"])

    async def test_ctrl_e_reaches_the_binding_with_focus_on_the_body(self):
        """Le bug rapporté : `e` nu ne se déclenchait QUE si le focus se
        trouvait par hasard sur un bouton, jamais depuis la zone de texte du
        corps — le widget de texte avale le caractère imprimable avant qu'il
        n'atteigne la liaison. `ctrl+e` n'est pas un caractère imprimable :
        il doit déclencher l'éditeur même avec le focus sur `#body`."""
        from textual.widgets import TextArea

        import script.todo.mail.tui as tui_mod

        app = await self._mounted_app(self._FakeIMAPTransport())
        calls = []

        @contextmanager
        def fake_suspend(self_app):
            yield

        def fake_editor(text):
            calls.append(text)
            return text

        orig_editor = tui_mod.edit_in_external_editor
        tui_mod.edit_in_external_editor = fake_editor
        try:
            async with app.run_test() as pilot:
                await pilot.press("c")
                await pilot.pause()
                body = app.screen.query_one("#body", TextArea)
                body.focus()
                await pilot.pause()

                with patch.object(type(app), "suspend", fake_suspend):
                    await pilot.press("ctrl+e")
                    await pilot.pause()
        finally:
            tui_mod.edit_in_external_editor = orig_editor

        self.assertEqual(len(calls), 1)


class TestBrowseFilesButton(TestComposeScreenMounted):
    """Le bouton Parcourir ouvre `todo_file_browser.FileBrowser` sous
    `App.suspend()` — urwid et Textual ne peuvent pas se partager le
    terminal. Le sélecteur urwid lui-même n'est pas testable ici (il a
    besoin d'un vrai terminal) : voir le rapport pour la vérification
    manuelle."""

    async def test_suspends_and_appends_the_chosen_path(self):
        from textual.widgets import Button, Input

        import script.todo.todo_file_browser as browser_mod

        app = await self._mounted_app(self._FakeIMAPTransport())
        order = []

        @contextmanager
        def fake_suspend(self_app):
            order.append("suspend")
            yield

        class FakeFileBrowser:
            def __init__(self, initial_path, callback):
                order.append("constructed")
                self.initial_path = initial_path
                self.callback = callback

            def run_main_frame(self):
                # `urwid.MainLoop.run()` avale `ExitMainLoop` (`with
                # suppress(ExitMainLoop): self._run()`) — c'est ce qui rend
                # normal, dans le vrai composant, l'appel à
                # `todo_file_browser.exit_program()` que fait le callback
                # réel. Le reproduire ici est nécessaire : sans ça, ce faux
                # laisserait l'exception s'échapper, ce qu'un VRAI
                # `FileBrowser` ne ferait jamais.
                import urwid

                order.append("run")
                try:
                    self.callback("/chosen/devis.pdf")
                except urwid.ExitMainLoop:
                    pass

        async with app.run_test() as pilot:
            await pilot.press("c")
            await pilot.pause()
            with patch.object(
                type(app), "suspend", fake_suspend
            ), patch.object(browser_mod, "FileBrowser", FakeFileBrowser):
                app.screen.query_one("#browse_files", Button).press()
                await pilot.pause()

            self.assertEqual(
                app.screen.query_one("#files", Input).value,
                "/chosen/devis.pdf",
            )

        self.assertEqual(order, ["suspend", "constructed", "run"])

    async def test_a_failing_browser_leaves_the_draft_intact(self):
        """Un sélecteur qui échoue à s'ouvrir ne doit PAS emporter le
        brouillon : perdre un brouillon à cause d'un sélecteur cassé serait
        pire que ne pas avoir de sélecteur du tout."""
        from textual.widgets import Button, Input, Static

        import script.todo.todo_file_browser as browser_mod

        app = await self._mounted_app(self._FakeIMAPTransport())

        @contextmanager
        def broken_suspend(self_app):
            raise RuntimeError("terminal incompatible")
            yield  # pragma: no cover - jamais atteint

        async with app.run_test() as pilot:
            await pilot.press("c")
            await pilot.pause()
            app.screen.query_one("#subject", Input).value = "Ne pas perdre"
            with patch.object(type(app), "suspend", broken_suspend):
                app.screen.query_one("#browse_files", Button).press()
                await pilot.pause()

            # Le brouillon est toujours là, et l'écran ne s'est pas fermé.
            self.assertEqual(
                app.screen.query_one("#subject", Input).value,
                "Ne pas perdre",
            )
            status = app.screen.query_one("#compose_status", Static)
            self.assertIn("terminal incompatible", str(status.content))


class TestSyncSurfacesResync(TestComposeScreenMounted):
    """`Syncer.sync()` rend `report.purged` (dossiers vidés parce que le
    serveur a changé l'UIDVALIDITY) : `MailApp._sync` doit le montrer, pas
    seulement le calculer — sinon l'utilisateur ne sait jamais qu'une
    resynchronisation complète a eu lieu."""

    class _FakeSyncerWithPurge:
        def __init__(self, transport):
            self.transport = transport

        def sync(self, progress=None):
            from types import SimpleNamespace

            return SimpleNamespace(new_messages=2, errors=[], purged=["INBOX"])

        def fetch_body(self, folder, uid):
            return None

    async def test_purged_folders_are_shown_in_the_status(self):
        from textual.widgets import Static

        session = Session(
            self.account,
            self.store,
            self._FakeSyncerWithPurge(self._FakeIMAPTransport()),
            password="hunter2",
        )
        app = await self._mounted_app(self._FakeIMAPTransport())
        async with app.run_test() as pilot:
            # `on_mount` lance déjà sa propre synchronisation en tâche de
            # fond : l'attendre évite une course avec l'appel explicite
            # ci-dessous, qui écraserait sinon le statut au hasard.
            await app.workers.wait_for_complete()
            app._sync([session])
            await pilot.pause()
            status = app.query_one("#status", Static)
            self.assertIn("INBOX", str(status.content))


class TestSyncSurfacesErrors(TestComposeScreenMounted):
    """`report.errors` porte le texte exact de l'échec (`"dossier : exc"`,
    voir `imap_sync.Syncer.sync`) : avant ce correctif, `MailApp._sync` n'en
    affichait que le COMPTE (`"— 1 erreurs"`), perdant le texte que
    l'utilisateur aurait besoin de lire pour diagnostiquer quoi que ce
    soit."""

    class _FakeSyncerWithErrors:
        def __init__(self, transport):
            self.transport = transport

        def sync(self, progress=None):
            from types import SimpleNamespace

            return SimpleNamespace(
                new_messages=0,
                errors=["Archives : 501 refus du serveur"],
                purged=[],
            )

        def fetch_body(self, folder, uid):
            return None

    async def test_the_error_text_is_shown_not_just_the_count(self):
        from textual.widgets import Static

        session = Session(
            self.account,
            self.store,
            self._FakeSyncerWithErrors(self._FakeIMAPTransport()),
            password="hunter2",
        )
        app = await self._mounted_app(self._FakeIMAPTransport())
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            app._sync([session])
            await pilot.pause()
            status = app.query_one("#status", Static)
            self.assertIn(
                "Archives : 501 refus du serveur", str(status.content)
            )

    async def test_additional_errors_are_counted_alongside_the_first(self):
        from textual.widgets import Static

        class _FakeSyncerWithManyErrors:
            def __init__(self, transport):
                self.transport = transport

            def sync(self, progress=None):
                from types import SimpleNamespace

                return SimpleNamespace(
                    new_messages=0,
                    errors=["INBOX : 501 refus", "Archives : 502 refus"],
                    purged=[],
                )

            def fetch_body(self, folder, uid):
                return None

        session = Session(
            self.account,
            self.store,
            _FakeSyncerWithManyErrors(self._FakeIMAPTransport()),
            password="hunter2",
        )
        app = await self._mounted_app(self._FakeIMAPTransport())
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            app._sync([session])
            await pilot.pause()
            status = app.query_one("#status", Static)
            text = str(status.content)
            self.assertIn("INBOX : 501 refus", text)
            self.assertIn("+1", text)


class TestSyncLogsTotalFailure(TestComposeScreenMounted):
    """Quand `session.sync()` lève directement (connexion totalement
    perdue, pas un simple dossier récalcitrant), `MailApp._sync` affichait
    déjà le message d'erreur — mais sans jamais le journaliser."""

    class _FakeSyncerThatRaises:
        def __init__(self, transport):
            self.transport = transport

        def sync(self, progress=None):
            raise OSError("connexion perdue")

        def fetch_body(self, folder, uid):
            return None

    async def test_total_failure_is_logged(self):
        session = Session(
            self.account,
            self.store,
            self._FakeSyncerThatRaises(self._FakeIMAPTransport()),
            password="hunter2",
        )
        app = await self._mounted_app(self._FakeIMAPTransport())
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            with self.assertLogs("script.todo.mail.tui", level="ERROR"):
                app._sync([session])
            await pilot.pause()


class TestSyncSerializesAccess(TestComposeScreenMounted):
    """L'auto-refresh et un `r`/`R` manuel lancent chacun `_sync` via
    `run_worker(thread=True)`, avec `exclusive=False` : deux passes peuvent
    donc tourner en vrais threads en même temps, et `imaplib` n'est pas
    thread-safe. `_sync_lock` doit les sérialiser — l'annulation ne joue
    aucun rôle ici, elle ne s'applique pas aux workers de type thread."""

    class _SlowFakeSyncer:
        """Incrémente un compteur partagé pendant `sync()` : si deux passes
        s'exécutent en même temps, le compteur dépasse 1 au moins une fois."""

        def __init__(self, transport, active, guard, overlap):
            self.transport = transport
            self._active = active
            self._guard = guard
            self._overlap = overlap

        def sync(self, progress=None):
            import time
            from types import SimpleNamespace

            with self._guard:
                self._active["n"] += 1
                if self._active["n"] > 1:
                    self._overlap.set()
            time.sleep(0.05)
            with self._guard:
                self._active["n"] -= 1
            return SimpleNamespace(new_messages=0, errors=[], purged=[])

        def fetch_body(self, folder, uid):
            return None

    async def test_concurrent_syncs_are_serialized(self):
        import asyncio
        import threading

        overlap = threading.Event()
        active = {"n": 0}
        guard = threading.Lock()

        session_a = Session(
            self.account,
            self.store,
            self._SlowFakeSyncer(
                self._FakeIMAPTransport(), active, guard, overlap
            ),
            password="hunter2",
        )
        session_b = Session(
            self.account,
            self.store,
            self._SlowFakeSyncer(
                self._FakeIMAPTransport(), active, guard, overlap
            ),
            password="hunter2",
        )

        app = await self._mounted_app(self._FakeIMAPTransport())
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()

            t1 = threading.Thread(target=app._sync, args=([session_a],))
            t2 = threading.Thread(target=app._sync, args=([session_b],))
            t1.start()
            t2.start()
            # Une attente asynchrone, pas `Thread.join()` : bloquer la
            # boucle d'évènements empêcherait `call_from_thread` (utilisé par
            # `set_status` depuis ces threads) de jamais s'exécuter.
            while t1.is_alive() or t2.is_alive():
                await asyncio.sleep(0.01)
            await pilot.pause()

        self.assertFalse(overlap.is_set())


class TestPreviewShowsFullDate(TestComposeScreenMounted):
    """`format_date` reste compact pour la colonne de la liste — l'aperçu
    d'un message doit montrer la date PLEINE, sans avoir à deviner l'année
    ou le jour à partir de la date du jour."""

    async def test_header_shows_the_full_send_date(self):
        from textual.widgets import Static

        from script.todo.mail.tui_text import format_date_full

        meta = MessageMeta(
            uid=1,
            date=1785580860,
            size=100,
            flags="",
            msgid="<1@x.ca>",
            frm="Alice <a@y.ca>",
            to="moi@x.ca",
            subject="Devis",
            snippet="",
        )
        ref = MailboxRef(
            account_name=self.account.name,
            folder_name="INBOX",
            display="INBOX",
            unseen=0,
        )
        app = await self._mounted_app(self._FakeIMAPTransport())
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            # `current_meta`/`current_ref` sont la couture éprouvée ailleurs
            # dans ce fichier (voir `test_forward_attaches_the_original_message`) :
            # elle isole ce test du mécanisme de curseur du `DataTable`, qui
            # n'est pas ce que ce test vise à vérifier.
            app.current_ref = ref
            app.current_meta = lambda: meta
            app.show_preview()
            await pilot.pause()

            preview = app.query_one("#preview", Static)
            self.assertIn(format_date_full(meta.date), str(preview.content))


class TestSearchClear(TestComposeScreenMounted):
    """Le champ de recherche (`/`) n'avait aucun moyen de se vider : ni
    bouton, ni raccourci. Le bouton ✕ et Échap doivent vider `self.query`
    EN PLUS du champ — sinon la liste resterait filtrée par une requête
    devenue invisible, pire que pas de bouton du tout."""

    def setUp(self):
        super().setUp()
        folder_id = self.store.upsert_folder("INBOX", "INBOX", "inbox")
        self.store.upsert_messages(
            folder_id,
            [
                MessageMeta(
                    uid=1,
                    date=1785580860,
                    size=10,
                    flags="",
                    msgid="<1@x.ca>",
                    frm="Alice <a@y.ca>",
                    to="moi@x.ca",
                    subject="Devis",
                    snippet="",
                ),
                MessageMeta(
                    uid=2,
                    date=1785580860,
                    size=10,
                    flags="",
                    msgid="<2@x.ca>",
                    frm="Bob <b@y.ca>",
                    to="moi@x.ca",
                    subject="CR réunion",
                    snippet="",
                ),
            ],
        )

    async def test_clear_button_restores_the_full_list(self):
        from textual.widgets import Button, DataTable, Input

        app = await self._mounted_app(self._FakeIMAPTransport())
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("slash")
            for ch in "devis":
                await pilot.press(ch)
            await pilot.pause()

            table = app.query_one("#list", DataTable)
            self.assertEqual(app.query, "devis")
            self.assertEqual(table.row_count, 1)

            app.query_one("#search_clear", Button).press()
            await pilot.pause()

            # La couture qui compte : pas seulement le champ vidé, mais
            # `self.query` aussi — sinon la liste resterait filtrée par
            # une requête devenue invisible.
            self.assertEqual(app.query, "")
            self.assertEqual(app.query_one("#search", Input).value, "")
            self.assertEqual(table.row_count, 2)

    async def test_escape_clears_the_search_when_it_has_focus(self):
        app = await self._mounted_app(self._FakeIMAPTransport())
        async with app.run_test() as pilot:
            from textual.widgets import DataTable, Input

            await app.workers.wait_for_complete()
            app.query_one("#panes").add_class("fullscreen")
            await pilot.press("slash")
            for ch in "devis":
                await pilot.press(ch)
            await pilot.pause()
            self.assertEqual(app.query, "devis")

            await pilot.press("escape")
            await pilot.pause()

            self.assertEqual(app.query, "")
            self.assertEqual(app.query_one("#search", Input).value, "")
            table = app.query_one("#list", DataTable)
            self.assertEqual(table.row_count, 2)
            # Échap a été consommé par le vidage de la recherche, pas par
            # la sortie du plein écran.
            self.assertTrue(app.query_one("#panes").has_class("fullscreen"))

    async def test_escape_elsewhere_still_leaves_fullscreen(self):
        app = await self._mounted_app(self._FakeIMAPTransport())
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            app.query_one("#panes").add_class("fullscreen")
            await pilot.pause()

            await pilot.press("escape")
            await pilot.pause()

            self.assertFalse(app.query_one("#panes").has_class("fullscreen"))

    async def test_clearing_the_search_is_discoverable_in_the_footer(self):
        """Round 2 de la revue : le bouton ✕ a un `tooltip`, mais Textual ne
        déclenche les tooltips que sur `MouseMove` (vérifié dans
        `screen.py`) — aucun clavier n'y mène. Le vrai chemin accessible
        est la description traduite qu'affiche le pied d'écran, et
        SEULEMENT pendant que le champ a le focus (`Screen.active_bindings`,
        que `Footer` lit directement)."""
        from textual.widgets import Input

        from script.todo.todo_i18n import t

        app = await self._mounted_app(self._FakeIMAPTransport())
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()

            # Hors du champ : la liaison Échap de l'appli reste celle
            # d'avant, masquée — inchangée par ce correctif.
            outside = app.screen.active_bindings["escape"]
            self.assertFalse(outside.binding.show)

            await pilot.press("slash")
            await pilot.pause()

            # Dans le champ : une AUTRE liaison Échap, traduite et visible,
            # prend le dessus — c'est elle que le pied d'écran affiche.
            focused = app.screen.active_bindings["escape"]
            self.assertTrue(focused.binding.show)
            self.assertEqual(
                focused.binding.description, t("mail_search_clear")
            )
            self.assertIsInstance(app.focused, Input)

    async def test_clear_search_does_not_refresh_the_list_twice(self):
        """`clear_search` met `self.query` à jour ET rafraîchit tout de
        suite ; vider le champ poste aussi un `Input.Changed`, que
        `on_input_changed` aurait traité une seconde fois sans son
        garde-fou (`event.value == self.query`)."""
        app = await self._mounted_app(self._FakeIMAPTransport())
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("slash")
            for ch in "devis":
                await pilot.press(ch)
            await pilot.pause()

            calls = []
            original = app.refresh_list

            def counting_refresh_list():
                calls.append(1)
                original()

            app.refresh_list = counting_refresh_list
            app.clear_search()
            await pilot.pause()

            self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
