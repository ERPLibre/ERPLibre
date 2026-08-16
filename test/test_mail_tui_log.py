#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La fenêtre de diagnostic, touche `l` : la fin de `~/.erplibre/mail.log`,
et les erreurs de synchronisation de la session en cours — sans quitter le
client pour aller les lire dans un fichier.

Le piège que ce fichier vérifie explicitement : une fenêtre qui s'ouvre VIDE
reproduit exactement la plainte qui justifie son existence (« j'ai une
erreur, mais aucun log »). Chaque état — absent, vide, illisible, aucune
erreur de session — doit se dire en toutes lettres.
"""
import os
import tempfile
import unittest
from pathlib import Path

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.store import Store
from script.todo.mail.tui import Session, read_log_tail


class TestReadLogTail(unittest.TestCase):
    """`read_log_tail` est une fonction pure (aucun import Textual) : elle
    se teste seule, sans monter d'écran."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self):
        # Un fichier laissé à 0o000 empêcherait parfois le nettoyage du
        # dossier temporaire selon le système de fichiers : on restaure les
        # droits avant de nettoyer, plutôt que de dépendre de ce détail.
        for entry in self.base.glob("*"):
            entry.chmod(0o644)
        self.tmp.cleanup()

    def test_missing_file_returns_explicit_message(self):
        from script.todo.todo_i18n import t

        lines, message = read_log_tail(self.base / "absent.log")
        self.assertEqual(lines, [])
        self.assertEqual(message, t("mail_log_missing"))

    def test_empty_file_returns_explicit_message(self):
        from script.todo.todo_i18n import t

        path = self.base / "mail.log"
        path.write_bytes(b"")

        lines, message = read_log_tail(path)
        self.assertEqual(lines, [])
        self.assertEqual(message, t("mail_log_empty"))

    def test_unreadable_file_returns_explicit_message(self):
        from script.todo.todo_i18n import t

        if os.geteuid() == 0:
            self.skipTest(
                "racine : les permissions de fichier ne bloquent rien"
            )

        path = self.base / "mail.log"
        path.write_text("2026-08-04 boum\n")
        path.chmod(0o000)

        lines, message = read_log_tail(path)
        self.assertEqual(lines, [])
        self.assertTrue(message.startswith(t("mail_log_unreadable")))

    def test_tail_shows_only_the_last_lines(self):
        path = self.base / "mail.log"
        path.write_text("".join(f"ligne {i}\n" for i in range(1, 501)))

        lines, message = read_log_tail(path, max_lines=50)

        self.assertEqual(message, "")
        self.assertEqual(len(lines), 50)
        self.assertEqual(lines[0], "ligne 451")
        self.assertEqual(lines[-1], "ligne 500")

    def test_does_not_read_the_whole_file(self):
        """La contrainte centrale : un journal qui grossit sans borne ne
        doit jamais être chargé en entier pour n'en montrer que la fin.
        Vérifié en espionnant les octets RÉELLEMENT lus sur le fichier
        cible, pas en devinant depuis le résultat."""
        import builtins

        path = self.base / "big.log"
        line = ("x" * 100) + "\n"
        with open(path, "w", encoding="utf-8") as handle:
            for _ in range(50_000):
                handle.write(line)
        total_size = path.stat().st_size
        self.assertGreater(total_size, 4_000_000)

        read_sizes = []
        orig_open = builtins.open

        def spying_open(*args, **kwargs):
            handle = orig_open(*args, **kwargs)
            if args and args[0] == path:
                orig_read = handle.read

                def spying_read(n=-1, *a, **k):
                    data = orig_read(n, *a, **k)
                    read_sizes.append(len(data))
                    return data

                handle.read = spying_read
            return handle

        builtins.open = spying_open
        try:
            lines, message = read_log_tail(path, max_lines=20)
        finally:
            builtins.open = orig_open

        self.assertEqual(message, "")
        self.assertEqual(len(lines), 20)
        self.assertLess(sum(read_sizes), total_size)

    def test_survives_non_utf8_bytes(self):
        """Un vrai journal peut contenir des octets qui ne sont pas de
        l'UTF-8 valide (encodage local du serveur distant reproduit tel
        quel dans un message d'exception, par exemple) : ça ne doit jamais
        faire lever la lecture, seulement remplacer ce qui ne se décode
        pas."""
        path = self.base / "mail.log"
        with open(path, "wb") as handle:
            handle.write(b"2026-08-04 avant\n")
            handle.write(b"\xff\xfe pas de l'utf-8 valide\n")
            handle.write(b"2026-08-04 apres\n")

        lines, message = read_log_tail(path)

        self.assertEqual(message, "")
        self.assertEqual(lines[0], "2026-08-04 avant")
        self.assertEqual(lines[-1], "2026-08-04 apres")

    def test_survives_a_multiline_traceback(self):
        """Une vraie panne écrit une trace Python sur plusieurs lignes, pas
        une ligne bien propre : la dernière ligne de la trace doit rester
        visible dans la fin du journal."""
        traceback_text = (
            "2026-08-04 12:00:00 script.todo.mail.imap_sync ERROR sync a échoué\n"
            "Traceback (most recent call last):\n"
            '  File "imap_sync.py", line 140, in sync\n'
            "    folder = self._sync_folder(info)\n"
            "OSError: 530 refus du serveur\n"
        )
        path = self.base / "mail.log"
        path.write_text(traceback_text)

        lines, message = read_log_tail(path, max_lines=10)

        self.assertEqual(message, "")
        self.assertEqual(lines[-1], "OSError: 530 refus du serveur")
        self.assertIn("Traceback (most recent call last):", lines)

    class _FakeStatResult:
        def __init__(self, size):
            self.st_size = size

    class _ShrunkAfterStatPath:
        """Simule une rotation de journal : `stat()` rapporte encore
        l'ANCIENNE taille (non nulle), mais le fichier est déjà vide au
        moment où `open()` puis `read()` s'exécutent — la lecture par blocs
        rend alors `b""`, sans qu'aucune des deux gardes précédentes
        (`exists()`, `size == 0`) ne l'ait vu venir."""

        def exists(self):
            return True

        def stat(self):
            return TestReadLogTail._FakeStatResult(1000)

    def test_a_file_truncated_between_stat_and_read_is_treated_as_empty(self):
        """`size > 0` au moment du `stat()` ne garantit RIEN sur ce que la
        lecture rendra ensuite : un journal peut être tronqué entre les deux
        (rotation de journal, notamment) — exactement le cas qu'une revue a
        retrouvé après qu'une passe précédente eut, à tort, jugé ce garde-fou
        mort."""
        import builtins

        from script.todo.todo_i18n import t

        fake_path = self._ShrunkAfterStatPath()
        orig_open = builtins.open

        def spying_open(file, *args, **kwargs):
            if file is fake_path:
                import io

                return io.BytesIO(b"")
            return orig_open(file, *args, **kwargs)

        builtins.open = spying_open
        try:
            lines, message = read_log_tail(fake_path)
        finally:
            builtins.open = orig_open

        self.assertEqual(lines, [])
        self.assertEqual(message, t("mail_log_empty"))


class FakeTransport:
    def list_folders(self):
        return []

    def logout(self):
        pass


class LogScreenCase(unittest.IsolatedAsyncioTestCase):
    """Monte `MailApp` pour de vrai, `$HOME` détourné vers un dossier
    jetable — comme `test_mail_tui_account.py` : `on_mount` lit
    `todo_prefs`, qui crée `~/.erplibre` s'il est absent, et le chemin du
    journal (`menu.mail_log_path()`) EST sous `~/.erplibre` : sans ce
    détournement, monter l'écran toucherait la vraie machine ET risquerait
    de lire le vrai journal de l'utilisateur, qui contient les réponses de
    son serveur de courriel.
    """

    def setUp(self):
        self.fake_home = tempfile.TemporaryDirectory()
        self._old_home = os.environ.get("HOME")
        os.environ["HOME"] = self.fake_home.name

        self.cache_dir = tempfile.TemporaryDirectory()
        self.account = account_from_preset("perso", "moi@x.ca", "generic")
        self.account.cache_mode = "clear"
        self.store = Store(
            self.account, mode="clear", base=Path(self.cache_dir.name)
        )
        self.store.open()

    def tearDown(self):
        self.store.close()
        if self._old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._old_home
        self.fake_home.cleanup()
        self.cache_dir.cleanup()

    def _log_path(self) -> Path:
        from script.todo.mail.menu import mail_log_path

        return mail_log_path()

    class _FakeSyncer:
        def __init__(self, transport, errors=None):
            self.transport = transport
            self._errors = errors or []

        def sync(self, progress=None):
            from types import SimpleNamespace

            return SimpleNamespace(
                new_messages=0, errors=list(self._errors), purged=[]
            )

        def sync_one(self, folder_name):
            from types import SimpleNamespace

            return SimpleNamespace(new_messages=0, errors=[], folders=1)

        def fetch_body(self, folder, uid):
            return None

    async def _mounted_app(self, session=None):
        import textual.app

        from script.todo.mail.tui import run_tui

        sessions = [session] if session is not None else []
        captured = []
        orig_init = textual.app.App.__init__

        def capturing_init(app_self, *a, **kw):
            orig_init(app_self, *a, **kw)
            captured.append(app_self)

        textual.app.App.__init__ = capturing_init
        try:
            run_tui(run_app=False, sessions=sessions)
        finally:
            textual.app.App.__init__ = orig_init
        return captured[-1]


class TestLogScreenOpensAndCloses(LogScreenCase):
    async def test_l_opens_the_log_screen(self):
        from textual.screen import ModalScreen

        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("l")
            await pilot.pause()

            self.assertIsInstance(app.screen, ModalScreen)

    async def test_escape_closes_it_without_disturbing_the_mail_list(self):
        from textual.screen import ModalScreen
        from textual.widgets import DataTable

        session = Session(
            self.account,
            self.store,
            self._FakeSyncer(FakeTransport()),
            password="hunter2",
        )
        self.store.upsert_folder("INBOX", "INBOX", "inbox")

        app = await self._mounted_app(session)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            table_before = app.query_one("#list", DataTable)
            rows_before = table_before.row_count

            await pilot.press("l")
            await pilot.pause()
            self.assertIsInstance(app.screen, ModalScreen)

            await pilot.press("escape")
            await pilot.pause()

            self.assertNotIsInstance(app.screen, ModalScreen)
            table_after = app.query_one("#list", DataTable)
            self.assertEqual(table_after.row_count, rows_before)

    async def test_binding_is_translated(self):
        from script.todo.todo_i18n import t

        app = await self._mounted_app()
        binding = next(b for key, b in app._bindings if key == "l")
        self.assertEqual(binding.description, t("mail_log_binding"))


class TestLogScreenTailContent(LogScreenCase):
    async def test_missing_log_file_says_so_explicitly(self):
        from textual.widgets import Log

        from script.todo.todo_i18n import t

        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("l")
            await pilot.pause()

            log_widget = app.screen.query_one("#log_tail", Log)
            text = "\n".join(str(line) for line in log_widget.lines)
            self.assertIn(t("mail_log_missing"), text)

    async def test_tail_of_a_real_log_file_is_shown(self):
        from textual.widgets import Log

        log_path = self._log_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("".join(f"ligne {i}\n" for i in range(1, 301)))

        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("l")
            await pilot.pause()

            log_widget = app.screen.query_one("#log_tail", Log)
            text = "\n".join(str(line) for line in log_widget.lines)
            self.assertIn("ligne 300", text)
            self.assertNotIn("ligne 1\n", text + "\n")


class TestLogScreenSessionErrors(LogScreenCase):
    async def test_errors_from_the_last_sync_are_shown(self):
        from textual.widgets import Static

        session = Session(
            self.account,
            self.store,
            self._FakeSyncer(
                FakeTransport(), errors=["Archives : 501 refus du serveur"]
            ),
            password="hunter2",
        )
        app = await self._mounted_app(session)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            app._sync([session])
            await pilot.pause()

            await pilot.press("l")
            await pilot.pause()

            errors_widget = app.screen.query_one("#log_errors", Static)
            self.assertIn(
                "Archives : 501 refus du serveur",
                str(errors_widget.render()),
            )

    async def test_no_session_errors_says_so_explicitly(self):
        from textual.widgets import Static

        from script.todo.todo_i18n import t

        session = Session(
            self.account,
            self.store,
            self._FakeSyncer(FakeTransport(), errors=[]),
            password="hunter2",
        )
        app = await self._mounted_app(session)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            app._sync([session])
            await pilot.pause()

            await pilot.press("l")
            await pilot.pause()

            errors_widget = app.screen.query_one("#log_errors", Static)
            self.assertIn(t("mail_log_no_errors"), str(errors_widget.render()))

    async def test_a_later_clean_sync_clears_a_previous_error(self):
        """« la dernière synchronisation » : une erreur d'il y a deux
        passes ne doit pas rester affichée comme si elle était toujours
        d'actualité."""
        from textual.widgets import Static

        from script.todo.todo_i18n import t

        session = Session(
            self.account,
            self.store,
            self._FakeSyncer(FakeTransport(), errors=["INBOX : 501 refus"]),
            password="hunter2",
        )
        app = await self._mounted_app(session)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            app._sync([session])
            await pilot.pause()

            # Deuxième synchronisation, propre cette fois.
            session.syncer = self._FakeSyncer(FakeTransport(), errors=[])
            app._sync([session])
            await pilot.pause()

            await pilot.press("l")
            await pilot.pause()

            errors_widget = app.screen.query_one("#log_errors", Static)
            text = str(errors_widget.render())
            self.assertIn(t("mail_log_no_errors"), text)
            self.assertNotIn("INBOX : 501 refus", text)


class TestLogScreenTotalSyncFailure(LogScreenCase):
    """`session.sync()` peut lever DIRECTEMENT (connexion totalement
    perdue), pas seulement rendre un `report.errors` : c'est la panne la
    plus grave, celle qu'un utilisateur ouvrirait précisément cette fenêtre
    pour diagnostiquer — un vrai `imaplib.IMAP4.abort ... Broken pipe` a été
    trouvé dans un journal réel après une telle panne. Le statut affiché au
    moment de la panne est éphémère (le prochain message l'efface) ; `l`
    existe pour regarder APRÈS coup, donc cette panne doit rester lisible
    dans la fenêtre, pas seulement dans la barre de statut du moment."""

    class _FakeSyncerThatRaises:
        def __init__(self, transport):
            self.transport = transport

        def sync(self, progress=None):
            raise OSError("imaplib.IMAP4.abort ... Broken pipe")

        def sync_one(self, folder_name):
            from types import SimpleNamespace

            return SimpleNamespace(new_messages=0, errors=[], folders=1)

        def fetch_body(self, folder, uid):
            return None

    async def test_total_failure_is_shown_in_the_window(self):
        from textual.widgets import Static

        session = Session(
            self.account,
            self.store,
            self._FakeSyncerThatRaises(FakeTransport()),
            password="hunter2",
        )
        app = await self._mounted_app(session)
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            app._sync([session])
            await pilot.pause()

            await pilot.press("l")
            await pilot.pause()

            errors_widget = app.screen.query_one("#log_errors", Static)
            self.assertIn(
                "imaplib.IMAP4.abort ... Broken pipe",
                str(errors_widget.render()),
            )


if __name__ == "__main__":
    unittest.main()
