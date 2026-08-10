#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import json
import logging
import os
import tempfile
import unittest
from pathlib import Path

from script.todo.mail.accounts import account_from_preset
from script.todo.mail.menu import cache_summary
from script.todo.mail.store import Store


class TestCacheSummary(unittest.TestCase):
    # Sans injection, `resolve_mode` retombe sur les VRAIES préférences de la
    # machine, et `todo_prefs` crée `~/.erplibre` au passage.
    CLEAR = staticmethod(lambda k, d=None: "clear")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.accounts = [
            account_from_preset("perso", "a@x.ca", "generic"),
            account_from_preset("travail", "b@x.ca", "generic"),
        ]

    def tearDown(self):
        self.tmp.cleanup()

    def test_one_row_per_account(self):
        rows = cache_summary(
            self.accounts, base=self.base, prefs_get=self.CLEAR
        )
        self.assertEqual([r["name"] for r in rows], ["perso", "travail"])

    def test_reports_the_effective_mode(self):
        self.accounts[0].cache_mode = "encrypted"
        rows = cache_summary(
            self.accounts, base=self.base, prefs_get=lambda k, d=None: "clear"
        )
        self.assertEqual(rows[0]["mode"], "encrypted")
        self.assertEqual(rows[1]["mode"], "clear")

    def test_size_is_zero_before_any_sync(self):
        rows = cache_summary(
            self.accounts, base=self.base, prefs_get=self.CLEAR
        )
        self.assertEqual(rows[0]["size"], 0)

    def test_size_grows_with_the_cache(self):
        store = Store(self.accounts[0], mode="clear", base=self.base)
        store.open()
        store.upsert_folder("INBOX")
        store.write_body("INBOX", 1, b"x" * 4096)
        store.close()
        rows = cache_summary(
            self.accounts, base=self.base, prefs_get=self.CLEAR
        )
        self.assertGreater(rows[0]["size"], 4000)

    def test_missing_cache_does_not_raise(self):
        rows = cache_summary(
            self.accounts,
            base=self.base / "inexistant",
            prefs_get=self.CLEAR,
        )
        self.assertEqual(len(rows), 2)


class TestAddAccountRollsBack(unittest.TestCase):
    """Une sauvegarde ratée ne doit pas laisser le mot de passe dans le coffre."""

    def test_failed_save_removes_the_orphan_secret(self):
        from unittest.mock import MagicMock, patch

        import script.todo.mail.menu as menu

        vault = MagicMock()
        vault.available_backends.return_value = ["kdbx"]
        with patch.object(
            menu, "secret_store_for", return_value=vault
        ), patch.object(
            menu.mail_accounts, "save", side_effect=OSError("disque plein")
        ), patch.object(
            menu, "_load_accounts", return_value=[]
        ), patch(
            "builtins.input",
            side_effect=[
                "perso",
                "moi@x.ca",
                "",
                "4",
                "imap.x.ca",
                "smtp.x.ca",
            ],
        ), patch(
            "getpass.getpass", return_value="hunter2"
        ):
            menu._add_account(MagicMock())

        vault.set.assert_called_once()
        vault.delete.assert_called_once_with("kdbx:ERPLibre/Mail/perso")

    def test_failed_save_does_not_crash_the_menu(self):
        from unittest.mock import MagicMock, patch

        import script.todo.mail.menu as menu

        vault = MagicMock()
        vault.available_backends.return_value = ["kdbx"]
        with patch.object(
            menu, "secret_store_for", return_value=vault
        ), patch.object(
            menu.mail_accounts, "save", side_effect=OSError("disque plein")
        ), patch.object(
            menu, "_load_accounts", return_value=[]
        ), patch(
            "builtins.input",
            side_effect=[
                "perso",
                "moi@x.ca",
                "",
                "4",
                "imap.x.ca",
                "smtp.x.ca",
            ],
        ), patch(
            "getpass.getpass", return_value="hunter2"
        ):
            menu._add_account(MagicMock())  # ne doit pas lever


class TestOpenTuiAllowsEmptyAccounts(unittest.TestCase):
    """Le TUI sait désormais créer un compte depuis son propre écran : le
    refus historique de s'ouvrir sans compte (`mail_no_account`) défait
    exactement la fonctionnalité que cette tâche ajoute."""

    def test_opens_with_zero_accounts_instead_of_refusing(self):
        from unittest.mock import MagicMock, patch

        import script.todo.mail.menu as menu

        todo = MagicMock()
        with patch.object(menu, "_load_accounts", return_value=[]), patch(
            "script.todo.mail.tui.open_sessions", return_value=[]
        ) as mock_open, patch("script.todo.mail.tui.run_tui") as mock_run:
            menu._open_tui(todo)

        mock_open.assert_called_once()
        mock_run.assert_called_once()

    def test_passes_config_file_and_the_secret_store_through(self):
        """Sans ça, l'écran d'ajout de compte du TUI n'aurait ni où écrire
        le chemin du kdbx, ni de coffre pour y déposer le mot de passe."""
        from unittest.mock import MagicMock, patch

        import script.todo.mail.menu as menu

        todo = MagicMock()
        secrets = MagicMock()
        with patch.object(
            menu, "_load_accounts", return_value=[]
        ), patch.object(menu, "secret_store_for", return_value=secrets), patch(
            "script.todo.mail.tui.open_sessions", return_value=[]
        ), patch(
            "script.todo.mail.tui.run_tui"
        ) as mock_run:
            menu._open_tui(todo)

        _, kwargs = mock_run.call_args
        self.assertIs(kwargs["config_file"], todo.config_file)
        self.assertIs(kwargs["secret_store"], secrets)


class TestSyncNowSurfacesResync(unittest.TestCase):
    """`report.purged` (dossiers vidés car l'UIDVALIDITY a changé) doit
    atteindre l'utilisateur — il ne suffit pas qu'il soit calculé et testé
    dans `imap_sync.py`, encore faut-il qu'un appelant l'affiche."""

    def test_purged_folders_are_printed(self):
        import io
        from contextlib import redirect_stdout
        from types import SimpleNamespace
        from unittest.mock import MagicMock, patch

        import script.todo.mail.menu as menu

        account = account_from_preset("perso", "a@x.ca", "generic")

        class FakeSession:
            def __init__(self):
                self.account = account
                self.online = True
                self.error = ""

            def sync(self):
                return SimpleNamespace(
                    new_messages=1, errors=[], purged=["INBOX"]
                )

            def close(self):
                pass

        buf = io.StringIO()
        with patch.object(
            menu, "_load_accounts", return_value=[account]
        ), patch(
            "script.todo.mail.tui.open_sessions",
            return_value=[FakeSession()],
        ), redirect_stdout(
            buf
        ):
            menu._sync_now(MagicMock())

        self.assertIn("INBOX", buf.getvalue())


class TestMailLogFile(unittest.TestCase):
    """Aucun gestionnaire n'existait nulle part dans `script/todo/mail/`
    avant ce correctif : les modules journalisent (`_logger.exception(...)`),
    mais brancher un gestionnaire est le travail de L'APPLICATION — ici,
    `prompt_execute_mail`, le seul point d'entrée du paquet. Jamais vers la
    console : Textual possède le terminal pendant tout le TUI.
    """

    def setUp(self):
        self.fake_home = tempfile.TemporaryDirectory()
        self._old_home = os.environ.get("HOME")
        os.environ["HOME"] = self.fake_home.name

    def tearDown(self):
        import script.todo.mail.menu as menu

        logger = logging.getLogger("script.todo.mail")
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
        logger.propagate = True
        menu._LOG_CONFIGURED = False

        if self._old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._old_home
        self.fake_home.cleanup()

    def test_creates_the_log_file_under_home(self):
        import script.todo.mail.menu as menu

        menu._configure_mail_logging()
        logging.getLogger("script.todo.mail.tui").error("boum")

        log_path = Path(self.fake_home.name) / ".erplibre" / "mail.log"
        self.assertTrue(log_path.exists())
        self.assertIn("boum", log_path.read_text())

    def test_is_idempotent(self):
        import script.todo.mail.menu as menu

        menu._configure_mail_logging()
        menu._configure_mail_logging()

        logger = logging.getLogger("script.todo.mail")
        file_handlers = [
            h for h in logger.handlers if isinstance(h, logging.FileHandler)
        ]
        self.assertEqual(len(file_handlers), 1)

    def test_never_installs_a_console_handler(self):
        import script.todo.mail.menu as menu

        menu._configure_mail_logging()

        logger = logging.getLogger("script.todo.mail")
        non_file_stream_handlers = [
            h
            for h in logger.handlers
            if isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.FileHandler)
        ]
        self.assertEqual(non_file_stream_handlers, [])

    def test_never_leaks_to_the_console_via_root_propagation(self):
        """`script/todo/todo.py:68` calls `logging.basicConfig()` at
        import time, which installs a `StreamHandler` on the ROOT logger.
        `propagate` defaults to `True`: without disabling it explicitly,
        every `_logger.exception(...)` in the mail package would ALSO
        reach that root handler — straight onto the terminal Textual owns
        for the whole TUI. `test_never_installs_a_console_handler` above
        cannot catch this: it only inspects `script.todo.mail`'s OWN
        handlers, never what a PARENT logger does with a propagated
        record.

        Reproduced for real in the full suite: this exact leak showed up,
        unprompted, in the middle of `unittest`'s dotted progress output
        the first time the mail tests ran in a process where
        `script.todo.todo` (and its `basicConfig`) had already been
        imported by an earlier test file.
        """
        import io

        import script.todo.mail.menu as menu
        import script.todo.todo  # noqa: F401 - installe le handler racine

        root = logging.getLogger()
        buf = io.StringIO()
        capture = logging.StreamHandler(buf)
        root.addHandler(capture)
        try:
            menu._configure_mail_logging()
            logging.getLogger("script.todo.mail.tui").error("ne doit pas fuir")
        finally:
            root.removeHandler(capture)

        self.assertEqual(buf.getvalue(), "")

    def test_prompt_execute_mail_configures_logging_before_the_loop(self):
        """`prompt_execute_mail` est le seul point d'entrée du paquet
        `mail` : c'est là, et nulle part ailleurs, que le gestionnaire doit
        être branché."""
        from unittest.mock import MagicMock, patch

        import script.todo.mail.menu as menu

        with patch("click.prompt", return_value="0"):
            menu.prompt_execute_mail(MagicMock())

        logger = logging.getLogger("script.todo.mail")
        self.assertTrue(
            any(isinstance(h, logging.FileHandler) for h in logger.handlers)
        )


class TestCacheSizeAndPurge(unittest.TestCase):
    """`_cache_size_and_purge` doit survivre à un coffre absent et à un
    cache corrompu — les deux tuaient tout le CLI avant ce correctif.

    `Store(account)` sans `base` retombe sur `~/.erplibre/mail` : on détourne
    `$HOME`, comme `TestComposeScreenMounted` (test_mail_compose.py), plutôt
    que d'ajouter un paramètre `base` qu'aucun appelant réel n'utilise.
    """

    def setUp(self):
        self.fake_home = tempfile.TemporaryDirectory()
        self._old_home = os.environ.get("HOME")
        os.environ["HOME"] = self.fake_home.name

    def tearDown(self):
        if self._old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._old_home
        self.fake_home.cleanup()

    def test_purges_a_healthy_encrypted_account_without_raising(self):
        from unittest.mock import MagicMock, patch

        import script.todo.mail.menu as menu

        account = account_from_preset("perso", "a@x.ca", "generic")
        account.cache_mode = "encrypted"
        vault = {}
        secrets = MagicMock()
        secrets.get.side_effect = vault.get
        secrets.set.side_effect = lambda ref, value: vault.__setitem__(
            ref, value
        )

        with patch.object(
            menu, "_load_accounts", return_value=[account]
        ), patch.object(menu, "secret_store_for", return_value=secrets), patch(
            "builtins.input", side_effect=["1", "o"]
        ):
            menu._cache_size_and_purge(MagicMock())  # ne doit pas lever

    def test_corrupted_cache_is_removed_from_disk_instead_of_crashing(self):
        from unittest.mock import MagicMock, patch

        import script.todo.mail.menu as menu

        account = account_from_preset("perso", "a@x.ca", "generic")
        store = Store(account)
        store.root.mkdir(parents=True, exist_ok=True)
        (store.root / "cache.db").write_bytes(b"pas une base sqlite" * 50)

        with patch.object(
            menu, "_load_accounts", return_value=[account]
        ), patch.object(
            menu, "secret_store_for", return_value=MagicMock()
        ), patch(
            "builtins.input", side_effect=["1", "o"]
        ):
            menu._cache_size_and_purge(MagicMock())  # ne doit pas lever

        self.assertFalse(store.root.exists())


class TestEnsureKdbx(unittest.TestCase):
    """`_ensure_kdbx` doit tenir la promesse de la conception (lignes
    204-207 du design) : créer un nouveau kdbx ou en choisir un existant
    quand aucun n'est configuré. Un vrai `ConfigFile`, pointé vers un
    dossier temporaire, sert de `todo.config_file` : on veut vérifier que
    `set_config_value` est réellement câblé, pas seulement appelé sur un
    mock.
    """

    def setUp(self):
        from types import SimpleNamespace
        from unittest.mock import patch as mock_patch

        from script.config.config_file import ConfigFile

        self.tmp = tempfile.TemporaryDirectory()
        self.private_path = os.path.join(
            self.tmp.name, "private", "todo", "todo_override_private.json"
        )
        # Rejoue la forme du vrai `script/todo/todo.json`, qui déclare déjà
        # une section "kdbx" avec path/password vides (ce squelette existe
        # justement pour que `get_config_value(["kdbx", "path"])` renvoie
        # toujours une chaîne, jamais None, quand rien n'est configuré) —
        # sans quoi l'absence totale de fichiers ferait planter
        # `get_config_value` (`"path" in None`), un cas que la vraie
        # configuration versionnée n'expose jamais.
        base_path = os.path.join(self.tmp.name, "base.json")
        with open(base_path, "w") as f:
            json.dump({"kdbx": {"path": "", "password": ""}}, f)
        self.patchers = [
            mock_patch(
                "script.config.config_file.CONFIG_OVERRIDE_PRIVATE_FILE",
                self.private_path,
            ),
            mock_patch(
                "script.config.config_file.CONFIG_FILE",
                base_path,
            ),
            mock_patch(
                "script.config.config_file.CONFIG_OVERRIDE_FILE",
                os.path.join(self.tmp.name, "nonexistent_override.json"),
            ),
        ]
        for patcher in self.patchers:
            patcher.start()
        self.todo = SimpleNamespace(config_file=ConfigFile())

    def tearDown(self):
        for patcher in self.patchers:
            patcher.stop()
        self.tmp.cleanup()

    def test_skips_the_prompt_when_already_configured(self):
        from unittest.mock import patch as mock_patch

        import script.todo.mail.menu as menu

        self.todo.config_file.set_config_value(
            ["kdbx", "path"], "/already/there.kdbx"
        )
        with mock_patch("builtins.input") as mock_input:
            result = menu._ensure_kdbx(self.todo)
        self.assertTrue(result)
        mock_input.assert_not_called()

    def test_create_writes_a_real_kdbx_and_records_its_path(self):
        from unittest.mock import patch as mock_patch

        import script.todo.mail.menu as menu

        kdbx_path = os.path.join(self.tmp.name, "new.kdbx")
        with mock_patch(
            "builtins.input", side_effect=["1", kdbx_path]
        ), mock_patch("getpass.getpass", side_effect=["hunter2", "hunter2"]):
            result = menu._ensure_kdbx(self.todo)
        self.assertTrue(result)
        self.assertTrue(os.path.isfile(kdbx_path))
        self.assertEqual(
            self.todo.config_file.get_config_value(["kdbx", "path"]),
            kdbx_path,
        )

    def test_mismatched_passwords_are_refused_and_nothing_is_created(self):
        from unittest.mock import patch as mock_patch

        import script.todo.mail.menu as menu

        kdbx_path = os.path.join(self.tmp.name, "new.kdbx")
        with mock_patch(
            "builtins.input", side_effect=["1", kdbx_path]
        ), mock_patch(
            "getpass.getpass", side_effect=["hunter2", "somethingelse"]
        ):
            result = menu._ensure_kdbx(self.todo)
        self.assertFalse(result)
        self.assertFalse(os.path.exists(kdbx_path))
        # Le squelette du vrai `todo.json` donne "" (pas None) tant que
        # rien n'a été configuré — c'est la valeur falsy que teste
        # `_ensure_kdbx`, peu importe sa forme exacte.
        self.assertFalse(
            self.todo.config_file.get_config_value(["kdbx", "path"])
        )

    def test_choosing_a_nonexistent_file_is_refused(self):
        from unittest.mock import patch as mock_patch

        import script.todo.mail.menu as menu

        missing_path = os.path.join(self.tmp.name, "nope.kdbx")
        with mock_patch("builtins.input", side_effect=["2", missing_path]):
            result = menu._ensure_kdbx(self.todo)
        self.assertFalse(result)
        # Le squelette du vrai `todo.json` donne "" (pas None) tant que
        # rien n'a été configuré — c'est la valeur falsy que teste
        # `_ensure_kdbx`, peu importe sa forme exacte.
        self.assertFalse(
            self.todo.config_file.get_config_value(["kdbx", "path"])
        )

    def test_choosing_an_existing_file_records_its_path(self):
        from unittest.mock import patch as mock_patch

        import script.todo.mail.menu as menu

        existing_path = os.path.join(self.tmp.name, "existing.kdbx")
        Path(existing_path).write_bytes(b"not a real kdbx, just a file")
        with mock_patch("builtins.input", side_effect=["2", existing_path]):
            result = menu._ensure_kdbx(self.todo)
        self.assertTrue(result)
        self.assertEqual(
            self.todo.config_file.get_config_value(["kdbx", "path"]),
            existing_path,
        )

    def test_cancel_creates_neither_file_nor_account(self):
        from unittest.mock import patch as mock_patch

        import script.todo.mail.menu as menu

        with mock_patch.object(
            menu.mail_accounts, "save"
        ) as mock_save, mock_patch("builtins.input", side_effect=["0"]):
            menu._add_account(self.todo)
        mock_save.assert_not_called()
        # Le squelette du vrai `todo.json` donne "" (pas None) tant que
        # rien n'a été configuré — c'est la valeur falsy que teste
        # `_ensure_kdbx`, peu importe sa forme exacte.
        self.assertFalse(
            self.todo.config_file.get_config_value(["kdbx", "path"])
        )


class TestMailKeysAreTranslated(unittest.TestCase):
    """Le seul filet contre une clé oubliée.

    `t()` rend la clé elle-même quand elle est absente : rien n'échoue, et
    l'interface affiche « mail_body_error » en toutes lettres à l'utilisateur.
    Aucun autre test ne peut attraper ça.
    """

    def test_every_key_used_in_the_mail_package_is_declared(self):
        import re
        from pathlib import Path

        import script.todo.mail as mail_pkg
        from script.todo.todo_i18n import TRANSLATIONS

        pattern = re.compile(r"""(?<![A-Za-z_])t\((["'])(mail_[a-z_]+)\1\)""")
        used = set()
        for path in Path(mail_pkg.__file__).parent.glob("*.py"):
            used |= {m.group(2) for m in pattern.finditer(path.read_text())}
        self.assertTrue(
            used, "aucune clé trouvée : le motif ne correspond plus"
        )
        missing = sorted(used - set(TRANSLATIONS))
        self.assertEqual(
            missing, [], f"clés utilisées mais non traduites : {missing}"
        )


class TestTodoWiring(unittest.TestCase):
    def test_todo_exposes_prompt_assistant(self):
        from script.todo.todo import TODO

        self.assertTrue(hasattr(TODO, "prompt_assistant"))

    def test_todo_keeps_the_ai_question(self):
        from script.todo.todo import TODO

        self.assertTrue(hasattr(TODO, "_assistant_question"))

    def test_assistant_key_is_translated(self):
        from script.todo.todo_i18n import TRANSLATIONS

        self.assertIn("Assistant", TRANSLATIONS)
        self.assertNotIn("Question", TRANSLATIONS)

    def test_one_dispatches_to_assistant_question_only(self):
        """`hasattr` seul ne verrait pas deux branches de menu échangées —
        on pilote `click.prompt` et on vérifie que `[1]` appelle
        `_assistant_question`, PAS `prompt_execute_mail`.

        `_menu_header()` enregistre aussi une télémétrie best-effort dans
        `~/.erplibre` : on la neutralise, sinon ce test écrirait pour de
        vrai sur la machine.
        """
        from unittest.mock import patch

        from script.todo.todo import TODO

        todo = TODO()
        with patch.object(TODO, "_assistant_question") as mock_question, patch(
            "script.todo.mail.menu.prompt_execute_mail"
        ) as mock_mail, patch("click.prompt", side_effect=["1", "0"]), patch(
            "script.todo.todo_telemetry.record"
        ):
            todo.prompt_assistant()

        mock_question.assert_called_once_with()
        mock_mail.assert_not_called()

    def test_two_dispatches_to_mail_only(self):
        """Symétrique : `[2]` appelle `prompt_execute_mail`, PAS
        `_assistant_question`."""
        from unittest.mock import patch

        from script.todo.todo import TODO

        todo = TODO()
        with patch.object(TODO, "_assistant_question") as mock_question, patch(
            "script.todo.mail.menu.prompt_execute_mail"
        ) as mock_mail, patch("script.todo.todo_telemetry.record"), patch(
            "click.prompt", side_effect=["2", "0"]
        ):
            todo.prompt_assistant()

        mock_mail.assert_called_once_with(todo)
        mock_question.assert_not_called()


class TestRetryPassword(unittest.TestCase):
    def setUp(self):
        self.account = account_from_preset("perso", "a@x.ca", "generic")
        self.vault = {}

    def _todo(self):
        from unittest.mock import MagicMock

        return MagicMock()

    def test_a_timeout_does_not_blame_the_password(self):
        """Le serveur n'a RIEN dit : la commande est partie, aucune réponse.
        Accuser le mot de passe envoie chercher un mot de passe
        d'application pour un problème qui est ailleurs — signalé à
        l'usage, sur un « The read operation timed out » de Gmail."""
        lignes = self._lignes_affichees(
            "gmail",
            cause="connexion IMAP refusée : The read operation timed out",
        )
        self.assertNotIn("mot de passe d'application", lignes)

    def _invite(self, preset_key):
        """L'invite EXACTE affichée par `getpass`, pas ce qui la précède."""
        from unittest.mock import patch

        from script.todo.mail.menu import retry_password

        vues = []
        with patch(
            "getpass.getpass", side_effect=lambda p="": vues.append(p) or ""
        ), patch("script.todo.mail.menu.secret_store_for"), patch(
            "builtins.print"
        ):
            retry_password(
                self._todo(),
                account_from_preset("essai", "a@x.ca", preset_key),
                connect_fn=lambda a, p: None,
            )
        return vues[0]

    def test_the_prompt_itself_asks_for_the_app_password(self):
        """La note se lit une fois ; l'invite se relit à CHAQUE tentative.
        « Mot de passe : » invitait à saisir celui du compte, que ces
        fournisseurs refusent."""
        self.assertIn("application", self._invite("gmail"))

    def test_a_generic_provider_keeps_the_plain_prompt(self):
        self.assertNotIn("application", self._invite("generic"))

    def test_the_note_gives_the_address_not_a_menu_path(self):
        """Google cache cette page : un chemin de menu ne suffit pas, et
        les intitulés changent. L'URL, elle, se colle."""
        lignes = self._lignes_affichees("gmail")
        self.assertIn("https://myaccount.google.com/apppasswords", lignes)

    def test_googles_own_wording_is_recognised(self):
        """Le cas qui a manqué : une fois la double authentification
        active, Gmail répond « [ALERT] Application-specific password
        required » — sans « invalid credentials » ni « authentication
        failed ». Une liste de libellés attendus est toujours en retard sur
        les serveurs réels."""
        lignes = self._lignes_affichees(
            "gmail",
            cause=(
                "b'[ALERT] Application-specific password required:"
                " https://support.google.com/accounts/answer/185833'"
            ),
        )
        self.assertIn("mot de passe d'application", lignes)

    def test_an_unknown_refusal_still_shows_the_note(self):
        """La note est un CONSEIL, pas un verdict : la taire à tort coûte
        la panne, la donner à tort coûte une ligne. Un serveur dont on ne
        connaît pas la formulation doit donc l'obtenir."""
        lignes = self._lignes_affichees(
            "gmail", cause="b'[NO] something we have never seen before'"
        )
        self.assertIn("mot de passe d'application", lignes)

    def test_an_explicit_refusal_still_blames_the_password(self):
        """Le contrôle symétrique : restreindre l'affichage ne doit pas
        l'avoir supprimé dans le cas où il sert."""
        lignes = self._lignes_affichees(
            "gmail", cause="b'[AUTHENTICATIONFAILED] Invalid credentials'"
        )
        self.assertIn("mot de passe d'application", lignes)

    def _lignes_affichees(self, preset_key, cause=None):
        """Ce que l'utilisateur LIT avant qu'on lui redemande son mot de
        passe, quand la connexion vient d'être refusée."""
        from unittest.mock import patch

        from script.todo.mail.menu import retry_password

        compte = account_from_preset("essai", "a@x.ca", preset_key)
        vues = []
        with patch("getpass.getpass", return_value=""), patch(
            "script.todo.mail.menu.secret_store_for"
        ), patch(
            "builtins.print",
            side_effect=lambda *a: vues.append(" ".join(map(str, a))),
        ):
            retry_password(
                self._todo(),
                compte,
                connect_fn=lambda a, p: None,
                cause=cause,
            )
        return "\n".join(vues)

    def test_a_provider_needing_an_app_password_says_so_before_reasking(self):
        """Gmail répond « Invalid credentials » au mot de passe habituel
        exactement comme à une faute de frappe. Sans cette note, l'invite
        pousse à retaper le même — et à se le faire refuser trois fois."""
        lignes = self._lignes_affichees("gmail")
        self.assertIn("mot de passe d'application", lignes)
        # L'instruction PRÉCISE, pas seulement le constat : sans elle, on
        # sait qu'il faut autre chose sans savoir où le prendre.
        self.assertIn("myaccount.google.com", lignes)

    def test_a_generic_provider_says_nothing_of_the_kind(self):
        """Le contrôle négatif : sans lui, une note affichée à TOUS
        passerait ce test aussi bien."""
        self.assertNotIn(
            "mot de passe d'application", self._lignes_affichees("generic")
        )

    def test_updates_the_vault_after_a_good_password(self):
        from unittest.mock import patch

        from script.todo.mail.menu import retry_password

        class OkTransport:
            def logout(self):
                pass

        with patch("getpass.getpass", return_value="bon"), patch(
            "script.todo.mail.menu.secret_store_for"
        ) as store:
            store.return_value.set.side_effect = self.vault.__setitem__
            ok = retry_password(
                self._todo(),
                self.account,
                connect_fn=lambda a, p: OkTransport(),
            )
        self.assertTrue(ok)
        self.assertEqual(self.vault[self.account.secret_ref], "bon")

    def test_does_not_touch_the_vault_when_every_try_fails(self):
        from unittest.mock import patch

        from script.todo.mail.menu import retry_password

        def refuse(account, password):
            raise OSError("530 refus")

        with patch("getpass.getpass", return_value="faux"), patch(
            "script.todo.mail.menu.secret_store_for"
        ) as store:
            store.return_value.set.side_effect = self.vault.__setitem__
            ok = retry_password(
                self._todo(), self.account, attempts=2, connect_fn=refuse
            )
        self.assertFalse(ok)
        self.assertEqual(self.vault, {})

    def test_empty_input_gives_up(self):
        from unittest.mock import patch

        from script.todo.mail.menu import retry_password

        with patch("getpass.getpass", return_value=""):
            self.assertFalse(
                retry_password(
                    self._todo(), self.account, connect_fn=lambda a, p: None
                )
            )


if __name__ == "__main__":
    unittest.main()
