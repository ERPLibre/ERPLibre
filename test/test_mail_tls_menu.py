#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Un certificat refusé dans le menu CLI : le test de connexion d'un
compte (IMAP puis SMTP) propose l'épinglage par un mot à taper et ne
redemande jamais le mot de passe ; `Comptes › [8]` liste et retire les
épingles ; la synchronisation et l'essai d'une règle disent où l'examiner.

`HOME` est un dossier temporaire ; `input`, `getpass` et les connexions
sont des doubles.
"""

import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from test_mail_rules_hooks import Imap

from script.todo.mail import accounts, menu
from script.todo.mail.accounts import account_from_preset
from script.todo.mail.imap_sync import Syncer
from script.todo.mail.smtp_send import build_message, tls
from script.todo.mail.store import MessageMeta, Store
from script.todo.mail.tui import FlushResult, Session
from script.todo.todo_i18n import t

OWN = "boite.regles@example.org"
CAROLE = "carole.regle@example.org"
HOTE = "serveur.example.org"
FP_A = "ab" * 32


def refus(protocol="imap", port=993, fingerprint=FP_A):
    return tls.TlsCertificateError(
        protocol=protocol,
        host=HOTE,
        port=port,
        reason="untrusted",
        fingerprint=fingerprint,
    )


class Transport:
    def list_folders(self):
        return ["INBOX", "Sent"]

    def logout(self):
        pass

    def quit(self):
        pass


class Connexions:
    """Un `connect` qui rend ses issues dans l'ordre (une exception est
    levée), puis un transport qui marche."""

    def __init__(self, *issues):
        self.issues = list(issues)
        self.appels = 0

    def __call__(self, account, secret):
        self.appels += 1
        issue = self.issues.pop(0) if self.issues else Transport()
        if isinstance(issue, BaseException):
            raise issue
        return issue


class MenuCase(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.TemporaryDirectory()
        self.ancien_home = os.environ.get("HOME")
        os.environ["HOME"] = self.home.name
        self.addCleanup(self._rendre_home)
        self.account = account_from_preset("perso", OWN, "generic")
        self.account.imap.host = HOTE
        self.account.smtp.host = HOTE
        accounts.save([self.account])
        coffre = mock.MagicMock()
        coffre.get.return_value = "secret"
        patcheur = mock.patch.object(
            menu, "secret_store_for", return_value=coffre
        )
        patcheur.start()
        self.addCleanup(patcheur.stop)

    def _rendre_home(self):
        if self.ancien_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self.ancien_home
        self.home.cleanup()

    def pins(self):
        return accounts.load()[0].tls_pins

    def essayer(self, saisies, imap=None, smtp=None):
        """`Comptes › [5]` sur le compte 1 ; rend la sortie et les appels
        à `getpass`."""
        sortie = io.StringIO()
        getpass = mock.Mock(return_value="")
        reponses = ["1", *saisies]
        self.invites = []

        def repondre(invite=""):
            self.invites.append(invite)
            return reponses.pop(0)

        with (
            mock.patch("builtins.input", side_effect=repondre),
            mock.patch("getpass.getpass", getpass),
            contextlib.redirect_stdout(sortie),
        ):
            menu._test_account(
                mock.MagicMock(),
                imap_connect=imap or Connexions(),
                smtp_connect=smtp or Connexions(),
            )
        return sortie.getvalue(), getpass


class TestConnectionTest(MenuCase):
    def test_an_imap_refusal_offers_the_pin_and_the_word_pins(self):
        imap = Connexions(refus())
        sortie, _ = self.essayer([t("mail_tls_trust_word")], imap=imap)
        self.assertIn(tls.format_fingerprint(FP_A), sortie)
        self.assertIn(t("mail_tls_trust_word"), self.invites[-1])
        self.assertEqual(self.pins(), {f"{HOTE}:993": "sha256:" + FP_A})
        self.assertEqual(imap.appels, 2)
        self.assertIn(t("mail_connection_ok"), sortie)
        self.assertIn(t("mail_connection_smtp_ok"), sortie)

    def test_a_wrong_word_pins_nothing(self):
        for saisie in ("o", "oui", "", t("mail_confirm_risk_word")):
            with self.subTest(saisie=saisie):
                imap = Connexions(refus())
                sortie, _ = self.essayer([saisie], imap=imap)
                self.assertEqual(self.pins(), {})
                self.assertEqual(imap.appels, 1)
                self.assertIn(
                    t("mail_tls_pin_declined").format(endpoint=f"{HOTE}:993"),
                    sortie,
                )
                self.assertNotIn(t("mail_connection_smtp_ok"), sortie)

    def test_a_tls_refusal_never_asks_for_the_password(self):
        with mock.patch.object(menu, "retry_password") as redemande:
            _, getpass = self.essayer([""], imap=Connexions(refus()))
        redemande.assert_not_called()
        getpass.assert_not_called()

    def test_smtp_is_tested_after_imap(self):
        smtp = Connexions()
        sortie, _ = self.essayer([], smtp=smtp)
        self.assertEqual(smtp.appels, 1)
        self.assertIn(t("mail_connection_smtp_ok"), sortie)

    def test_smtp_is_not_tested_after_an_imap_failure(self):
        smtp = Connexions()
        with mock.patch.object(menu, "retry_password", return_value=False):
            self.essayer(
                [], imap=Connexions(OSError("injoignable")), smtp=smtp
            )
        self.assertEqual(smtp.appels, 0)

    def test_an_smtp_refusal_offers_the_pin(self):
        smtp = Connexions(refus("smtp", 587))
        sortie, getpass = self.essayer([t("mail_tls_trust_word")], smtp=smtp)
        self.assertEqual(self.pins(), {f"{HOTE}:587": "sha256:" + FP_A})
        self.assertEqual(smtp.appels, 2)
        self.assertIn(t("mail_connection_smtp_ok"), sortie)
        getpass.assert_not_called()

    def test_another_smtp_failure_is_printed_without_asking(self):
        sortie, getpass = self.essayer(
            [], smtp=Connexions(OSError("injoignable"))
        )
        self.assertIn(t("mail_connection_smtp_failed"), sortie)
        getpass.assert_not_called()

    def test_an_unreadable_fingerprint_is_not_offered(self):
        imap = Connexions(refus(fingerprint=""))
        sortie, _ = self.essayer([], imap=imap)
        self.assertIn(
            t("mail_tls_pin_unavailable").format(endpoint=f"{HOTE}:993"),
            sortie,
        )
        self.assertEqual(len(self.invites), 1)
        self.assertEqual(self.pins(), {})

    def test_retry_password_stops_on_a_tls_refusal(self):
        sortie = io.StringIO()
        getpass = mock.Mock(return_value="nouveau")
        with (
            mock.patch("getpass.getpass", getpass),
            contextlib.redirect_stdout(sortie),
        ):
            ok = menu.retry_password(
                mock.MagicMock(),
                self.account,
                connect_fn=Connexions(refus(), refus(), refus()),
            )
        self.assertFalse(ok)
        self.assertEqual(getpass.call_count, 1)
        self.assertIn(t("mail_tls_menu_hint"), sortie.getvalue())


class TestPinsMenu(MenuCase):
    def menu(self, saisies):
        sortie = io.StringIO()
        with (
            mock.patch("builtins.input", side_effect=saisies),
            contextlib.redirect_stdout(sortie),
        ):
            menu._tls_pins_menu()
        return sortie.getvalue()

    def test_the_pins_menu_lists_and_removes_after_yes(self):
        accounts.pin_certificate("perso", HOTE, 993, FP_A)
        sortie = self.menu(["1", "o"])
        self.assertIn(f"perso — {HOTE}:993", sortie)
        self.assertIn(tls.format_fingerprint(FP_A), sortie)
        self.assertEqual(self.pins(), {})
        self.assertIn(
            t("mail_tls_unpinned").format(endpoint=f"{HOTE}:993"), sortie
        )

    def test_the_pins_menu_keeps_on_no(self):
        accounts.pin_certificate("perso", HOTE, 993, FP_A)
        for saisies in (["1", "n"], ["1", ""], [""], ["9"]):
            with self.subTest(saisies=saisies):
                self.menu(saisies)
                self.assertEqual(
                    self.pins(), {f"{HOTE}:993": "sha256:" + FP_A}
                )

    def test_the_pins_menu_without_pins(self):
        self.assertIn(t("mail_tls_pins_none"), self.menu([]))

    def test_the_accounts_menu_offers_entry_8(self):
        todo = SimpleNamespace(_menu_header=lambda: "--")
        sortie = io.StringIO()
        vues = []

        def invite(texte):
            vues.append(texte)
            return "8" if len(vues) == 1 else "0"

        with (
            mock.patch("click.prompt", side_effect=invite),
            mock.patch.object(menu, "_tls_pins_menu") as entree,
            contextlib.redirect_stdout(sortie),
        ):
            menu.prompt_mail_accounts(todo)
        entree.assert_called_once_with()
        self.assertIn(f"[8] {t('mail_account_tls_pins')}", vues[0])


class TestHints(MenuCase):
    def test_sync_now_prints_the_tls_hint(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = Store(self.account, mode="clear", base=Path(tmp.name))
        store.open()
        exc = refus()
        hors_ligne = Session(
            self.account,
            store,
            None,
            str(exc),
            "x",
            error_kind="tls",
            exc=exc,
        )
        sortie = io.StringIO()
        with (
            mock.patch(
                "script.todo.mail.tui.open_sessions", return_value=[hors_ligne]
            ),
            contextlib.redirect_stdout(sortie),
        ):
            menu._sync_now(mock.MagicMock())
        texte = sortie.getvalue()
        self.assertIn(str(exc), texte)
        self.assertIn(t("mail_tls_menu_hint"), texte)

    def test_sync_now_prints_the_hint_after_a_refusal_filing_a_copy(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = Store(self.account, mode="clear", base=Path(tmp.name))
        store.open()
        imap = Imap()

        def append_mort(*_args):
            raise OSError("lien mort")

        imap.append = append_mort
        exc = refus()
        session = Session(
            self.account,
            store,
            Syncer(store, imap),
            password="x",
            connect_fn=Connexions(exc),
        )
        msg = build_message(self.account, CAROLE, "Devis", "Bonjour")
        store.queue_message(msg.as_bytes(), CAROLE, "Devis")
        sortie = io.StringIO()
        with (
            mock.patch(
                "script.todo.mail.tui.open_sessions", return_value=[session]
            ),
            mock.patch(
                "script.todo.mail.smtp_send.connect",
                lambda account, secret: Transport(),
            ),
            mock.patch(
                "script.todo.mail.smtp_send.send",
                lambda account, msg, transport: [CAROLE],
            ),
            mock.patch.object(menu, "_run_rules"),
            contextlib.redirect_stdout(sortie),
        ):
            menu._sync_now(mock.MagicMock())
        texte = sortie.getvalue()
        self.assertIn(str(exc), texte)
        self.assertIn(t("mail_tls_menu_hint"), texte)
        self.assertIn(t("mail_outbox_flushed"), texte)

    def test_sync_now_prints_an_outbox_refusal(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = Store(self.account, mode="clear", base=Path(tmp.name))
        store.open()
        session = Session(self.account, store, mock.MagicMock(), password="x")
        rapport = SimpleNamespace(
            new_messages=0, errors=[], purged=[], tls_error=None
        )
        exc = refus("smtp", 587)
        sortie = io.StringIO()
        with (
            mock.patch(
                "script.todo.mail.tui.open_sessions", return_value=[session]
            ),
            mock.patch(
                "script.todo.mail.tui.flush_outbox",
                return_value=FlushResult(0, 0, 1, tls_error=exc),
            ),
            mock.patch.object(session, "sync", return_value=rapport),
            mock.patch.object(menu, "_run_rules"),
            contextlib.redirect_stdout(sortie),
        ):
            menu._sync_now(mock.MagicMock())
        self.assertIn(str(exc), sortie.getvalue())
        self.assertIn(t("mail_tls_menu_hint"), sortie.getvalue())

    def test_a_rule_trial_refusal_prints_the_tls_hint(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = Store(self.account, mode="clear", base=Path(tmp.name))
        store.open()
        inbox = store.upsert_folder("INBOX", "Boîte", "inbox")
        store.set_folder_state("INBOX", uidvalidity=7, uidnext=2)
        store.upsert_messages(
            inbox,
            [
                MessageMeta(
                    uid=1,
                    date=1_790_000_000,
                    size=10,
                    flags="",
                    msgid="<1@example.org>",
                    frm=CAROLE,
                    to=OWN,
                    subject="Devis",
                    snippet="",
                )
            ],
        )
        session = Session(self.account, store, None, password="x")
        exc = refus("smtp", 587)
        sortie = io.StringIO()
        with (
            mock.patch.object(menu, "_list_rules", return_value=[object()]),
            mock.patch("click.prompt", side_effect=["1", "1", "o"]),
            mock.patch(
                "script.todo.mail.tui.open_session", return_value=session
            ),
            mock.patch(
                "script.todo.mail.tui.trial_simulation",
                return_value=SimpleNamespace(sendable=True),
            ),
            mock.patch(
                "script.todo.mail.tui.rule_trial_lines", return_value=[]
            ),
            mock.patch(
                "script.todo.mail.rules.engine.send_trial", side_effect=exc
            ),
            contextlib.redirect_stdout(sortie),
        ):
            menu._trial(mock.MagicMock(), self.account, Path(tmp.name))
        self.assertIn(str(exc), sortie.getvalue())
        self.assertIn(t("mail_tls_menu_hint"), sortie.getvalue())


class TestTypedWord(unittest.TestCase):
    def test_ask_typed_word_keeps_the_risk_word_by_default(self):
        mot = t("mail_confirm_risk_word")
        with mock.patch("builtins.input", return_value=mot) as invite:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertTrue(menu._ask_typed_word("Question ?"))
        self.assertIn(mot, invite.call_args[0][0])
        with mock.patch(
            "builtins.input", return_value=t("mail_tls_trust_word")
        ):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertFalse(menu._ask_typed_word("Question ?"))
                self.assertTrue(
                    menu._ask_typed_word(
                        "Question ?", mot=t("mail_tls_trust_word")
                    )
                )


if __name__ == "__main__":
    unittest.main()
