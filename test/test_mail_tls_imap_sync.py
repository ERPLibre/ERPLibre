#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Un lien IMAP supplémentaire dont le certificat est refusé.

Le refus ne se tait pas comme un lien de plus que le fournisseur refuse :
il remonte dans `SyncReport.tls_error`, et aucun autre lien n'est tenté
pendant la passe. Le lien principal synchronise tous les dossiers.
"""

import unittest

from test_mail_sync_folders_parallel import ParallelCase

from script.todo.mail.smtp_send import tls

FP = "ab" * 32


def _refus():
    return tls.TlsCertificateError(
        protocol="imap",
        host="serveur.example.org",
        port=993,
        reason="untrusted",
        fingerprint=FP,
    )


class TestExtraLinkTls(ParallelCase):
    def test_a_refused_extra_link_is_reported(self):
        refus = _refus()

        def fabrique():
            raise refus

        rapport = self._syncer(3, fabrique=fabrique).sync()
        self.assertIs(rapport.tls_error, refus)
        self.assertEqual(rapport.folders, len(self.DOSSIERS))
        self.assertEqual(
            self._sujets(),
            sorted(f"Message de {nom}" for nom in self.DOSSIERS),
        )

    def test_no_further_extra_link_after_a_tls_refusal(self):
        appels = []

        def fabrique():
            appels.append(1)
            raise _refus()

        self._syncer(3, fabrique=fabrique).sync()
        self.assertEqual(len(appels), 1)

    def test_another_extra_link_failure_stays_silent(self):
        appels = []

        def fabrique():
            appels.append(1)
            raise OSError("trop de liens")

        rapport = self._syncer(3, fabrique=fabrique).sync()
        self.assertIsNone(rapport.tls_error)
        self.assertEqual(rapport.folders, len(self.DOSSIERS))
        self.assertEqual(len(appels), 2)

    def test_a_sync_without_extra_link_has_no_tls_error(self):
        self.assertIsNone(self._syncer(1).sync().tls_error)


if __name__ == "__main__":
    unittest.main()
