#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La famille d'une panne, et ce que le journal du service en garde."""

import imaplib
import socket
import sqlite3
import unittest

from script.todo.mail import errors
from script.todo.mail.accounts import AccountError
from script.todo.mail.imap_transport import ImapAuthError, ImapError
from script.todo.mail.oauth import OAuthError, RefreshRefused
from script.todo.mail.secrets import MissingSecret, SecretError
from script.todo.mail.smtp_send import SmtpAuthError
from script.todo.mail.store import StoreError


def enchaine(exc, cause):
    """`exc` levée `from cause`, telle qu'un `raise ... from` la laisse."""
    try:
        try:
            raise cause
        except BaseException as inner:
            raise exc from inner
    except BaseException as outer:
        return outer


class TestClassify(unittest.TestCase):
    def test_a_missing_secret_is_a_vault_failure(self):
        self.assertEqual(errors.classify(MissingSecret("absent")), "vault")
        self.assertEqual(errors.classify(SecretError("coffre")), "vault")

    def test_a_vault_busy_in_another_process_is_a_vault_failure(self):
        from script.todo.kdbx_write import KdbxBusy

        self.assertEqual(errors.classify(KdbxBusy("occupé")), "vault")

    def test_an_imap_error_caused_by_a_socket_is_a_network_failure(self):
        exc = enchaine(ImapError("connexion"), ConnectionRefusedError(111))
        self.assertEqual(errors.classify(exc), "network")
        exc = enchaine(ImapError("coupé"), imaplib.IMAP4.abort("eof"))
        self.assertEqual(errors.classify(exc), "network")
        self.assertEqual(errors.classify(socket.timeout()), "network")

    def test_an_imap_login_refusal_is_an_auth_failure(self):
        exc = enchaine(
            ImapError("refus"),
            imaplib.IMAP4.error("[AUTHENTICATIONFAILED] non"),
        )
        self.assertEqual(errors.classify(exc), "auth")
        self.assertEqual(errors.classify(ImapAuthError("jeton")), "auth")
        self.assertEqual(errors.classify(SmtpAuthError("smtp")), "auth")
        exc = enchaine(
            ImapError("ascii"), UnicodeEncodeError("ascii", "é", 0, 1, "x")
        )
        self.assertEqual(errors.classify(exc), "auth")
        self.assertEqual(errors.classify(ImapError("autre chose")), "other")

    def test_a_refused_refresh_is_an_auth_failure(self):
        self.assertEqual(
            errors.classify(RefreshRefused("invalid_grant")), "auth"
        )
        self.assertEqual(
            errors.classify(OAuthError("réponse étrange")), "auth"
        )

    def test_an_oauth_timeout_is_a_network_failure(self):
        exc = enchaine(OAuthError("délai"), TimeoutError("lecture"))
        self.assertEqual(errors.classify(exc), "network")

    def test_a_store_error_is_a_cache_failure(self):
        self.assertEqual(errors.classify(StoreError("corrompu")), "cache")
        exc = sqlite3.DatabaseError("file is not a database")
        self.assertEqual(errors.classify(exc), "cache")
        self.assertEqual(errors.classify(AccountError("json")), "config")

    def test_a_locked_cache_is_busy_not_unreadable(self):
        exc = sqlite3.OperationalError("database is locked")
        self.assertEqual(errors.classify(exc), "busy")
        enveloppe = enchaine(StoreError("cache"), exc)
        self.assertEqual(errors.classify(enveloppe), "busy")
        occupe = sqlite3.OperationalError("database table is busy")
        self.assertEqual(errors.classify(occupe), "busy")

    def test_anything_else_is_other(self):
        self.assertEqual(errors.classify(ValueError("x")), "other")
        self.assertEqual(errors.classify(KeyError("y")), "other")

    def test_journal_detail_keeps_the_class_and_the_response_code_only(self):
        exc = ImapAuthError(
            "[AUTHENTICATIONFAILED] refus pour boite.regles@example.org"
        )
        self.assertEqual(
            errors.journal_detail(exc), "ImapAuthError [AUTHENTICATIONFAILED]"
        )
        enveloppe = enchaine(
            ImapError("hôte injoignable"),
            imaplib.IMAP4.error("b'[UNAVAILABLE] plus tard'"),
        )
        self.assertEqual(
            errors.journal_detail(enveloppe), "ImapError [UNAVAILABLE]"
        )
        self.assertEqual(
            errors.journal_detail(ValueError("texte [minuscule] privé")),
            "ValueError",
        )
        self.assertEqual(errors.journal_detail(None), "")

    def test_a_cause_chain_that_loops_ends(self):
        a = ValueError("a")
        b = ValueError("b")
        a.__cause__ = b
        b.__cause__ = a
        self.assertEqual(errors.classify(a), "other")
        self.assertEqual(errors.journal_detail(a), "ValueError")


if __name__ == "__main__":
    unittest.main()
