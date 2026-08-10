#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import tempfile
import unittest
from pathlib import Path

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.tui import (
    MailboxRef,
    Session,
    mailbox_refs,
    open_sessions,
)


class FailingConnect:
    def __init__(self, message="serveur injoignable"):
        self.message = message

    def __call__(self, account, password):
        raise OSError(self.message)


class FakeTransport:
    def list_folders(self):
        return []

    def logout(self):
        pass


class FakeSecrets:
    def __init__(self, password="hunter2"):
        self.password = password

    def get(self, ref):
        return self.password

    def set(self, ref, value):
        self.password = value


class SessionCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.accounts = [
            account_from_preset("perso", "moi@x.ca", "generic"),
            account_from_preset("travail", "moi@y.ca", "generic"),
        ]
        # Épinglé : sans ça, resolve_mode lirait les préférences réelles de la
        # machine et le test dépendrait de ~/.erplibre.
        for account in self.accounts:
            account.cache_mode = "clear"

    def tearDown(self):
        self.tmp.cleanup()


class TestOpenSessions(SessionCase):
    def test_one_session_per_account(self):
        sessions = open_sessions(
            self.accounts,
            FakeSecrets(),
            base=self.base,
            connect_fn=lambda a, p: FakeTransport(),
        )
        self.assertEqual(
            [s.account.name for s in sessions], ["perso", "travail"]
        )
        for s in sessions:
            s.close()

    def test_disabled_account_is_skipped(self):
        self.accounts[1].enabled = False
        sessions = open_sessions(
            self.accounts,
            FakeSecrets(),
            base=self.base,
            connect_fn=lambda a, p: FakeTransport(),
        )
        self.assertEqual([s.account.name for s in sessions], ["perso"])
        for s in sessions:
            s.close()

    def test_cache_opens_even_when_the_network_fails(self):
        """Réseau coupé : la boîte doit rester consultable."""
        sessions = open_sessions(
            self.accounts,
            FakeSecrets(),
            base=self.base,
            connect_fn=FailingConnect(),
        )
        self.assertTrue(all(not s.online for s in sessions))
        self.assertTrue(all(s.store is not None for s in sessions))
        for s in sessions:
            s.close()

    def test_network_error_is_kept_for_display(self):
        sessions = open_sessions(
            self.accounts,
            FakeSecrets(),
            base=self.base,
            connect_fn=FailingConnect("530 refus"),
        )
        self.assertIn("530", sessions[0].error)
        for s in sessions:
            s.close()

    def test_missing_password_marks_offline(self):
        class NoSecret:
            def get(self, ref):
                return None

        sessions = open_sessions(
            self.accounts,
            NoSecret(),
            base=self.base,
            connect_fn=lambda a, p: FakeTransport(),
        )
        self.assertFalse(sessions[0].online)
        for s in sessions:
            s.close()

    def test_online_when_everything_works(self):
        sessions = open_sessions(
            self.accounts,
            FakeSecrets(),
            base=self.base,
            connect_fn=lambda a, p: FakeTransport(),
        )
        self.assertTrue(all(s.online for s in sessions))
        for s in sessions:
            s.close()


class TestEphemeralCleanupOnSignals(SessionCase):
    """`atexit` ne s'exécute pas sur un signal : sans un gestionnaire
    `SIGINT`/`SIGTERM` dédié, un cache éphémère survivrait à un `kill` ou un
    Ctrl+C — exactement ce que ce mode promet d'éviter.

    On déclenche le gestionnaire installé directement plutôt que d'envoyer un
    vrai signal au processus de test, et on restaure l'ancien gestionnaire
    dans `tearDown` pour ne pas polluer le reste de la suite.

    Piège vécu : quand la disposition précédente n'est PAS appelable
    (`SIG_DFL`, le cas par défaut), le gestionnaire se renvoie maintenant
    POUR DE VRAI le signal après le nettoyage — sinon il l'avalerait (voir
    `test_sigterm_actually_terminates_the_process`). Appeler ce gestionnaire
    directement avec la disposition par défaut en place tuerait donc le
    processus de test lui-même : `test_sigterm_removes_the_ephemeral_root`
    installe d'abord un `_previous` factice et appelable pour rester une
    invocation directe sûre, et laisse la vraie fin de processus au test
    suivant, seul endroit sûr pour l'observer (un sous-processus dédié).
    """

    def setUp(self):
        super().setUp()
        import signal

        self._orig_sigint = signal.getsignal(signal.SIGINT)
        self._orig_sigterm = signal.getsignal(signal.SIGTERM)

    def tearDown(self):
        import signal

        signal.signal(signal.SIGINT, self._orig_sigint)
        signal.signal(signal.SIGTERM, self._orig_sigterm)
        super().tearDown()

    def test_sigterm_removes_the_ephemeral_root(self):
        import signal

        # Un `_previous` factice mais appelable : la branche de repli qui
        # renvoie le signal pour de vrai (cas `SIG_DFL`) n'est PAS sûre à
        # emprunter ici, puisqu'on invoque le gestionnaire directement dans
        # le processus de test — elle est couverte séparément, en
        # sous-processus, par `test_sigterm_actually_terminates_the_process`.
        signal.signal(signal.SIGTERM, lambda signum, frame: None)

        for account in self.accounts:
            account.cache_mode = "ephemeral"
        sessions = open_sessions(
            self.accounts,
            FakeSecrets(),
            base=self.base,
            connect_fn=lambda a, p: FakeTransport(),
        )
        roots = [s.store.root for s in sessions]
        self.assertTrue(all(r.exists() for r in roots))

        handler = signal.getsignal(signal.SIGTERM)
        handler(signal.SIGTERM, None)

        self.assertFalse(any(r.exists() for r in roots))

    def test_sigterm_actually_terminates_the_process(self):
        """Un test qui ne vérifie QUE le nettoyage ne peut pas distinguer
        « nettoyé puis sorti » de « nettoyé puis resté vivant » — c'est
        exactement cette distinction que la régression a ratée : le
        gestionnaire chaîné n'appelait le précédent handler que s'il était
        `callable`, or la disposition par défaut de SIGTERM (`SIG_DFL`) est
        l'entier 0, pas un appelable — le signal était donc avalé.

        On lance un vrai sous-processus, on lui envoie SIGTERM pour de
        vrai (pas un appel direct du handler), et on vérifie qu'il MEURT.
        """
        import signal
        import subprocess
        import sys

        repo_root = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as base_dir:
            script = f"""
import os
import signal
import sys
import time

sys.path.insert(0, {str(repo_root)!r})

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.tui import open_sessions


class FakeTransport:
    def list_folders(self):
        return []

    def logout(self):
        pass


class FakeSecrets:
    def get(self, ref):
        return "hunter2"

    def set(self, ref, value):
        pass


account = account_from_preset("perso", "moi@x.ca", "generic")
account.cache_mode = "ephemeral"
sessions = open_sessions(
    [account],
    FakeSecrets(),
    base={str(base_dir)!r},
    connect_fn=lambda a, p: FakeTransport(),
)
print(str(sessions[0].store.root), flush=True)

os.kill(os.getpid(), signal.SIGTERM)

# Ne doit JAMAIS s'imprimer : y arriver veut dire que le signal a été avalé.
time.sleep(2)
print("FAILURE: still alive after SIGTERM", flush=True)
"""
            script_path = Path(base_dir) / "sigterm_child.py"
            script_path.write_text(script)

            result = subprocess.run(
                [sys.executable, str(script_path)],
                capture_output=True,
                text=True,
                timeout=10,
            )

            lines = [
                line for line in result.stdout.splitlines() if line.strip()
            ]
            self.assertTrue(
                lines, f"aucune sortie de l'enfant : {result.stderr}"
            )
            root = Path(lines[0])

            self.assertNotIn("still alive", result.stdout)
            self.assertEqual(result.returncode, -signal.SIGTERM)
            self.assertFalse(root.exists())


class TestMailboxRefs(SessionCase):
    def setUp(self):
        super().setUp()
        self.sessions = open_sessions(
            self.accounts,
            FakeSecrets(),
            base=self.base,
            connect_fn=lambda a, p: FakeTransport(),
        )

    def tearDown(self):
        for s in self.sessions:
            s.close()
        super().tearDown()

    def test_empty_when_no_folder(self):
        self.assertEqual(mailbox_refs(self.sessions), [])

    def test_lists_folders_of_every_account(self):
        self.sessions[0].store.upsert_folder("INBOX", "INBOX", "inbox")
        self.sessions[1].store.upsert_folder("INBOX", "INBOX", "inbox")
        refs = mailbox_refs(self.sessions)
        self.assertEqual(
            [(r.account_name, r.folder_name) for r in refs],
            [("perso", "INBOX"), ("travail", "INBOX")],
        )

    def test_inbox_comes_first(self):
        store = self.sessions[0].store
        store.upsert_folder("Archives", "Archives", None)
        store.upsert_folder("INBOX", "INBOX", "inbox")
        names = [r.folder_name for r in mailbox_refs(self.sessions)]
        self.assertEqual(names[0], "INBOX")

    def test_carries_unseen_count(self):
        store = self.sessions[0].store
        store.upsert_folder("INBOX", "INBOX", "inbox")
        store.set_folder_state("INBOX", unseen=4)
        self.assertEqual(mailbox_refs(self.sessions)[0].unseen, 4)

    def test_display_falls_back_to_name(self):
        self.sessions[0].store.upsert_folder("Projets")
        self.assertEqual(mailbox_refs(self.sessions)[0].display, "Projets")


class TestBrokenCache(SessionCase):
    """Un cache illisible sur UN compte ne doit pas couler les autres."""

    def _corrupt(self, name):
        root = self.base / name
        root.mkdir(parents=True, exist_ok=True)
        (root / "cache.db").write_bytes(b"pas une base sqlite" * 50)

    def _open(self):
        return open_sessions(
            self.accounts,
            FakeSecrets(),
            base=self.base,
            connect_fn=lambda a, p: FakeTransport(),
        )

    def test_the_other_accounts_still_open(self):
        self._corrupt("perso")
        sessions = self._open()
        self.assertEqual(
            [s.account.name for s in sessions], ["perso", "travail"]
        )
        self.assertIsNone(sessions[0].store)
        self.assertIsNotNone(sessions[1].store)
        for session in sessions:
            session.close()

    def test_the_broken_account_keeps_its_error(self):
        self._corrupt("perso")
        sessions = self._open()
        self.assertIn("cache.db", sessions[0].error)
        for session in sessions:
            session.close()

    def test_the_broken_account_is_offline(self):
        self._corrupt("perso")
        sessions = self._open()
        self.assertFalse(sessions[0].online)
        for session in sessions:
            session.close()

    def test_mailbox_refs_skips_it_without_raising(self):
        self._corrupt("perso")
        sessions = self._open()
        sessions[1].store.upsert_folder("INBOX", "INBOX", "inbox")
        refs = mailbox_refs(sessions)
        self.assertEqual([r.account_name for r in refs], ["travail"])
        for session in sessions:
            session.close()

    def test_closing_a_broken_session_does_not_raise(self):
        self._corrupt("perso")
        sessions = self._open()
        for session in sessions:
            session.close()


class TestImportsWithoutTextual(unittest.TestCase):
    def test_module_imports_without_textual(self):
        """Le module doit rester utilisable là où Textual n'est pas installé."""
        import script.todo.mail.tui as tui

        self.assertTrue(hasattr(tui, "run_tui"))


class TestSaveAttachment(unittest.TestCase):
    RAW = (
        b'Content-Type: multipart/mixed; boundary="B"\r\n\r\n'
        b"--B\r\nContent-Type: text/plain\r\n\r\ncorps\r\n"
        b"--B\r\nContent-Type: application/pdf\r\n"
        b'Content-Disposition: attachment; filename="devis.pdf"\r\n\r\n'
        b"%PDF\r\n--B--\r\n"
    )

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_writes_the_file(self):
        from script.todo.mail.tui import save_attachment

        target = save_attachment(self.RAW, 0, self.tmp.name)
        self.assertTrue(target.exists())
        self.assertEqual(target.name, "devis.pdf")

    def test_unknown_index_raises(self):
        from script.todo.mail.tui import save_attachment

        with self.assertRaises(ValueError):
            save_attachment(self.RAW, 7, self.tmp.name)

    def test_filename_cannot_escape_the_directory(self):
        """Le nom vient du message : il ne doit jamais écrire ailleurs."""
        from script.todo.mail.tui import save_attachment

        hostile = self.RAW.replace(b'"devis.pdf"', b'"../../evade.pdf"')
        target = save_attachment(hostile, 0, self.tmp.name)
        self.assertEqual(target.parent, Path(self.tmp.name))


if __name__ == "__main__":
    unittest.main()
