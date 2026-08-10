#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ajout de compte depuis le TUI : `n` (ou le nœud "+ Ajouter un compte")
ouvre le formulaire, et un compte sauvegardé doit devenir utilisable sans
redémarrer — présent à la fois dans `self.sessions` ET dans l'arbre.

Comme `test_mail_compose.py` : `on_mount` lit `todo_prefs`, qui crée
`~/.erplibre` s'il est absent, et l'écran d'ajout lit/écrit
`~/.erplibre/mail/accounts.json` par les mêmes fonctions que le CLI. `$HOME`
est donc détourné vers un dossier jetable pour tout le module.
"""
import os
import tempfile
import unittest
from pathlib import Path

from script.todo.mail import accounts as mail_accounts


class FakeConfigFile:
    """Un `config_file` minimal — seuls `get_config_value`/`set_config_value`
    sont utilisés par `account_setup`, pas besoin du vrai `ConfigFile`."""

    def __init__(self):
        self._values: dict = {}

    def get_config_value(self, keys):
        node = self._values
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                return None
            node = node[key]
        return node

    def set_config_value(self, keys, value):
        node = self._values
        for key in keys[:-1]:
            node = node.setdefault(key, {})
        node[keys[-1]] = value


class FakeSecretStore:
    """Coffre en mémoire : suffisant pour vérifier ce que le formulaire y
    écrit, sans toucher ni pykeepass ni le trousseau système."""

    def __init__(self):
        self._data: dict = {}

    def available_backends(self):
        return ["kdbx"]

    def get(self, ref):
        return self._data.get(ref)

    def set(self, ref, value):
        self._data[ref] = value

    def delete(self, ref):
        self._data.pop(ref, None)


class FakeTransport:
    def list_folders(self):
        return []

    def logout(self):
        pass


class TuiAccountCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Ces tests comparent des libellés d'arbre en français : ils fixent
        # donc la langue au lieu d'hériter de celle que le fichier précédent
        # a laissée, sinon ils passent seuls et échouent dans la suite
        # complète — ce qui est arrivé.
        #
        # On écrit la mémoïsation directement : `set_lang()` PERSISTE la
        # langue dans ./env_var.sh, un fichier suivi par git, donc l'appeler
        # depuis un test modifierait l'arbre de travail.
        from script.todo import todo_i18n

        self._old_lang = todo_i18n._current_lang
        todo_i18n._current_lang = "fr"

        self.fake_home = tempfile.TemporaryDirectory()
        self._old_home = os.environ.get("HOME")
        os.environ["HOME"] = self.fake_home.name

        self.cache_dir = tempfile.TemporaryDirectory()
        self.config_file = FakeConfigFile()
        # Un kdbx déjà configuré : le flux saute `VaultScreen` et va droit à
        # `AccountScreen`, ce que couvrent les tests de cette classe.
        self.config_file.set_config_value(
            ["kdbx", "path"], "/already/configured.kdbx"
        )
        self.secret_store = FakeSecretStore()

    def tearDown(self):
        from script.todo import todo_i18n

        # Rendre la langue telle qu'on l'a trouvée : ne pas reproduire sur
        # les tests suivants la fuite qui a cassé ceux-ci.
        todo_i18n._current_lang = self._old_lang

        if self._old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self._old_home
        self.fake_home.cleanup()
        self.cache_dir.cleanup()

    async def _mounted_app(self, sessions=None):
        # `run_tui(run_app=False, ...)` ne renvoie rien : capter la première
        # `App` construite, comme `test_mail_compose.py`.
        import textual.app

        from script.todo.mail.tui import run_tui

        captured = []
        orig_init = textual.app.App.__init__

        def capturing_init(app_self, *a, **kw):
            orig_init(app_self, *a, **kw)
            captured.append(app_self)

        textual.app.App.__init__ = capturing_init
        try:
            run_tui(
                run_app=False,
                sessions=sessions or [],
                config_file=self.config_file,
                secret_store=self.secret_store,
                connect_fn=lambda account, password: FakeTransport(),
                base=Path(self.cache_dir.name),
            )
        finally:
            textual.app.App.__init__ = orig_init
        return captured[-1]


class TestAccountNodeAndBinding(TuiAccountCase):
    async def test_add_account_leaf_is_at_the_bottom_of_the_tree(self):
        from textual.widgets import Tree

        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            tree = app.query_one("#folders", Tree)
            labels = [str(child.label) for child in tree.root.children]
            self.assertTrue(
                any("Ajouter un compte" in label for label in labels)
            )

    async def test_n_opens_the_account_form(self):
        from textual.screen import ModalScreen
        from textual.widgets import Input

        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()
            self.assertIsInstance(app.screen, ModalScreen)
            # Le kdbx est déjà configuré : c'est `AccountScreen`, pas
            # `VaultScreen`, qui doit s'ouvrir — la présence de `#acc_name`
            # le distingue sans exposer les classes imbriquées.
            self.assertIsNotNone(app.screen.query_one("#acc_name", Input))

    async def test_add_account_node_opens_the_same_screen_as_n(self):
        from textual.screen import ModalScreen
        from textual.widgets import Input, Tree

        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            tree = app.query_one("#folders", Tree)
            add_node = next(
                child
                for child in tree.root.children
                if "Ajouter un compte" in str(child.label)
            )
            tree.select_node(add_node)
            tree.action_select_cursor()
            await pilot.pause()
            self.assertIsInstance(app.screen, ModalScreen)
            self.assertIsNotNone(app.screen.query_one("#acc_name", Input))


class TestAccountScreenSavesAndGoesLive(TuiAccountCase):
    """La couture qui compte : un compte sauvegardé doit apparaître dans
    `self.sessions` ET dans l'arbre, sans redémarrer le TUI."""

    async def test_valid_submission_is_saved_and_usable_immediately(self):
        from textual.screen import ModalScreen
        from textual.widgets import Input, Select, Tree

        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()

            screen = app.screen
            screen.query_one("#acc_name", Input).value = "perso"
            screen.query_one("#acc_email", Input).value = "moi@x.ca"
            screen.query_one("#acc_password", Input).value = "hunter2"
            self.assertEqual(
                screen.query_one("#acc_preset", Select).value, "generic"
            )
            screen.query_one("#acc_imap", Input).value = "imap.x.ca"
            screen.query_one("#acc_smtp", Input).value = "smtp.x.ca"

            await pilot.press("ctrl+s")
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()

            # L'écran s'est refermé.
            self.assertNotIsInstance(app.screen, ModalScreen)

            # Le fichier de comptes le confirme.
            saved = mail_accounts.load()
            self.assertEqual([a.name for a in saved], ["perso"])
            self.assertEqual(
                self.secret_store.get(saved[0].secret_ref), "hunter2"
            )

            # ET le TUI en tient une session utilisable tout de suite.
            self.assertEqual(len(app.sessions), 1)
            self.assertEqual(app.sessions[0].account.name, "perso")

            # ET l'arbre la montre, sans redémarrer.
            tree = app.query_one("#folders", Tree)
            labels = [str(child.label) for child in tree.root.children]
            self.assertTrue(any("perso" in label for label in labels))

    async def test_cancel_creates_nothing(self):
        from textual.screen import ModalScreen
        from textual.widgets import Input

        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()
            app.screen.query_one("#acc_name", Input).value = "perso"

            await pilot.press("escape")
            await pilot.pause()

            self.assertNotIsInstance(app.screen, ModalScreen)
            self.assertEqual(mail_accounts.load(), [])
            self.assertEqual(app.sessions, [])

    async def test_invalid_name_is_refused_and_the_screen_stays_open(self):
        from textual.screen import ModalScreen
        from textual.widgets import Input, Static

        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()

            screen = app.screen
            # `/` est refusé par `Account.__post_init__` : le message doit
            # se lire sur l'écran, pas remonter en exception.
            screen.query_one("#acc_name", Input).value = "per/so"
            screen.query_one("#acc_email", Input).value = "moi@x.ca"
            screen.query_one("#acc_password", Input).value = "hunter2"

            await pilot.press("ctrl+s")
            await pilot.pause()

            self.assertIsInstance(app.screen, ModalScreen)
            status = screen.query_one("#account_status", Static)
            self.assertTrue(str(status.content))
            self.assertEqual(mail_accounts.load(), [])

    async def test_missing_password_is_refused_with_a_message(self):
        from textual.screen import ModalScreen
        from textual.widgets import Input, Static

        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()

            screen = app.screen
            screen.query_one("#acc_name", Input).value = "perso"
            screen.query_one("#acc_email", Input).value = "moi@x.ca"

            await pilot.press("ctrl+s")
            await pilot.pause()

            self.assertIsInstance(app.screen, ModalScreen)
            status = screen.query_one("#account_status", Static)
            self.assertTrue(str(status.content))
            self.assertEqual(mail_accounts.load(), [])


class TestVaultScreenFirst(TuiAccountCase):
    """Sans kdbx configuré, `VaultScreen` s'ouvre avant `AccountScreen`, et
    l'annuler annule tout le flux."""

    def setUp(self):
        super().setUp()
        # Ce groupe teste justement l'ABSENCE de configuration.
        self.config_file = FakeConfigFile()

    async def test_no_kdbx_configured_opens_vault_screen_first(self):
        from textual.screen import ModalScreen
        from textual.widgets import Input

        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()
            self.assertIsInstance(app.screen, ModalScreen)
            self.assertIsNotNone(app.screen.query_one("#vault_path", Input))

    async def test_cancelling_the_vault_cancels_the_whole_flow(self):
        from textual.screen import ModalScreen

        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()

            await pilot.press("escape")
            await pilot.pause()

            self.assertNotIsInstance(app.screen, ModalScreen)
            self.assertIsNone(
                self.config_file.get_config_value(["kdbx", "path"])
            )

    async def test_creating_the_vault_then_proceeds_to_the_account_form(self):
        from textual.screen import ModalScreen
        from textual.widgets import Input

        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()

            vault_path = os.path.join(self.cache_dir.name, "new.kdbx")
            app.screen.query_one("#vault_path", Input).value = vault_path
            app.screen.query_one("#vault_password", Input).value = "hunter2"
            app.screen.query_one("#vault_password_confirm", Input).value = (
                "hunter2"
            )

            await pilot.click("#vault_create")
            await pilot.pause()

            self.assertIsInstance(app.screen, ModalScreen)
            self.assertIsNotNone(app.screen.query_one("#acc_name", Input))
            self.assertTrue(os.path.isfile(vault_path))
            self.assertEqual(
                self.config_file.get_config_value(["kdbx", "path"]),
                vault_path,
            )

    async def test_mismatched_vault_passwords_are_refused(self):
        from textual.screen import ModalScreen
        from textual.widgets import Input, Static

        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()

            vault_path = os.path.join(self.cache_dir.name, "new.kdbx")
            app.screen.query_one("#vault_path", Input).value = vault_path
            app.screen.query_one("#vault_password", Input).value = "hunter2"
            app.screen.query_one("#vault_password_confirm", Input).value = (
                "autrechose"
            )

            await pilot.click("#vault_create")
            await pilot.pause()

            self.assertIsInstance(app.screen, ModalScreen)
            status = app.screen.query_one("#vault_status", Static)
            self.assertTrue(str(status.content))
            self.assertFalse(os.path.isfile(vault_path))


class TestVaultScreenSurvivesDiskErrors(TuiAccountCase):
    """`_create`/`_choose` do real disk I/O (`create_kdbx`,
    `ConfigFile.set_config_value`) and only caught `SecretError` — a plain
    `OSError` (disque plein, permission refusée) escaped into Textual's own
    handler, which renders every local, including the plaintext vault
    password sitting right there in the same frame."""

    def setUp(self):
        super().setUp()
        # Ce groupe teste justement l'ABSENCE de configuration : c'est
        # `VaultScreen`, pas `AccountScreen`, qui est en cause ici.
        self.config_file = FakeConfigFile()

    async def test_create_vault_oserror_keeps_the_screen_open(self):
        from unittest.mock import patch

        from textual.screen import ModalScreen
        from textual.widgets import Input, Static

        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()

            vault_path = os.path.join(self.cache_dir.name, "new.kdbx")
            app.screen.query_one("#vault_path", Input).value = vault_path
            app.screen.query_one("#vault_password", Input).value = "hunter2"
            app.screen.query_one("#vault_password_confirm", Input).value = (
                "hunter2"
            )

            with patch(
                "script.todo.mail.account_setup.create_vault",
                side_effect=OSError("disque plein"),
            ):
                await pilot.click("#vault_create")
                await pilot.pause()

            # Toujours un ModalScreen : ni plantage, ni fermeture d'écran.
            self.assertIsInstance(app.screen, ModalScreen)
            status = app.screen.query_one("#vault_status", Static)
            self.assertTrue(str(status.content))
            self.assertFalse(os.path.isfile(vault_path))

    async def test_create_reports_an_unopenable_vault_itself(self):
        """`_create` crée le fichier PUIS l'ouvre tout de suite,
        symétriquement à `_choose` : un coffre créé mais inouvrable
        (mauvaise entropie, corruption immédiate, ...) doit se signaler ICI,
        pas plus tard sur `AccountScreen` — l'utilisateur peut encore agir
        sur le coffre à cet instant précis."""
        from unittest.mock import patch

        from pykeepass.exceptions import CredentialsError
        from textual.screen import ModalScreen
        from textual.widgets import Input, Static

        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()

            vault_path = os.path.join(self.cache_dir.name, "new.kdbx")
            app.screen.query_one("#vault_path", Input).value = vault_path
            app.screen.query_one("#vault_password", Input).value = "hunter2"
            app.screen.query_one("#vault_password_confirm", Input).value = (
                "hunter2"
            )

            # `create_vault` (donc `create_kdbx`) tourne pour de vrai — le
            # fichier existe. Seule l'OUVERTURE qui suit échoue.
            with patch(
                "pykeepass.PyKeePass",
                side_effect=CredentialsError("mauvais mot de passe"),
            ):
                await pilot.click("#vault_create")
                await pilot.pause()

            # Toujours `VaultScreen` : `#vault_path` n'existe que là,
            # `AccountScreen` ne l'a jamais poussé.
            self.assertIsInstance(app.screen, ModalScreen)
            self.assertIsNotNone(app.screen.query_one("#vault_path", Input))
            status = app.screen.query_one("#vault_status", Static)
            self.assertTrue(str(status.content))
            self.assertTrue(os.path.isfile(vault_path))

    async def test_use_existing_vault_oserror_keeps_the_screen_open(self):
        from unittest.mock import patch

        from textual.screen import ModalScreen
        from textual.widgets import Input, Static

        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()

            existing_path = os.path.join(self.cache_dir.name, "existing.kdbx")
            with open(existing_path, "wb") as handle:
                handle.write(b"not a real kdbx, just a file")
            app.screen.query_one("#vault_path", Input).value = existing_path
            app.screen.query_one("#vault_password", Input).value = "hunter2"

            with patch(
                "script.todo.mail.account_setup.use_existing_vault",
                side_effect=OSError("permission refusée"),
            ):
                await pilot.click("#vault_choose")
                await pilot.pause()

            self.assertIsInstance(app.screen, ModalScreen)
            status = app.screen.query_one("#vault_status", Static)
            self.assertTrue(str(status.content))

    async def test_guard_covers_the_first_statement_in_create(self):
        """Protection structurelle (round 3) : trois manches ont chacune
        trouvé un appel qui tournait hors garde parce que le `try` ouvrait
        trop tard. Ce test casse la TOUTE PREMIÈRE lecture faite à
        l'intérieur du `try` de `_create` (`#vault_path`) — s'il repasse au
        rouge, c'est que le `try` a de nouveau été repoussé plus bas."""
        from textual.screen import ModalScreen
        from textual.widgets import Input, Static

        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()

            screen = app.screen
            orig_query_one = screen.query_one

            def failing_query_one(selector, *args, **kwargs):
                if selector == "#vault_path":
                    raise RuntimeError("échec simulé sur la 1re lecture")
                return orig_query_one(selector, *args, **kwargs)

            screen.query_one = failing_query_one

            await pilot.click("#vault_create")
            await pilot.pause()

            self.assertIsInstance(app.screen, ModalScreen)
            status = orig_query_one("#vault_status", Static)
            self.assertTrue(str(status.content))

    async def test_guard_covers_the_first_statement_in_choose(self):
        """Même protection que ci-dessus, pour `_choose`."""
        from textual.screen import ModalScreen
        from textual.widgets import Input, Static

        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()

            screen = app.screen
            orig_query_one = screen.query_one

            def failing_query_one(selector, *args, **kwargs):
                if selector == "#vault_path":
                    raise RuntimeError("échec simulé sur la 1re lecture")
                return orig_query_one(selector, *args, **kwargs)

            screen.query_one = failing_query_one

            await pilot.click("#vault_choose")
            await pilot.pause()

            self.assertIsInstance(app.screen, ModalScreen)
            status = orig_query_one("#vault_status", Static)
            self.assertTrue(str(status.content))


class TestAccountScreenSurvivesDiskErrors(TuiAccountCase):
    """`action_save` reads `mail_accounts.load()` to compute `existing`
    BEFORE its own try/except — an `OSError` there (accounts.json illisible)
    escaped uncaught, with the plaintext account password still a local in
    that same frame."""

    async def test_load_oserror_keeps_the_screen_open(self):
        from unittest.mock import patch

        from textual.screen import ModalScreen
        from textual.widgets import Input, Static

        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()

            screen = app.screen
            screen.query_one("#acc_name", Input).value = "perso"
            screen.query_one("#acc_email", Input).value = "moi@x.ca"
            screen.query_one("#acc_password", Input).value = "hunter2"
            screen.query_one("#acc_imap", Input).value = "imap.x.ca"
            screen.query_one("#acc_smtp", Input).value = "smtp.x.ca"

            with patch(
                "script.todo.mail.accounts.load",
                side_effect=OSError("disque plein"),
            ):
                await pilot.press("ctrl+s")
                await pilot.pause()

            self.assertIsInstance(app.screen, ModalScreen)
            status = screen.query_one("#account_status", Static)
            self.assertTrue(str(status.content))
            self.assertEqual(app.sessions, [])

    async def test_pykeepass_error_during_save_keeps_the_screen_open(self):
        """`secret_store.set()` peut atteindre `PyKeePass(...)` pour la
        première fois ici (coffre tout juste créé sans ouverture immédiate,
        avant le fix `_create`, ou coffre modifié entre-temps) : pykeepass
        lève `CredentialsError`/`HeaderChecksumError`/..., qui ne sont PAS
        des `OSError` — le guard doit rester `except Exception` pour ne
        jamais laisser passer `password` en clair vers la traceback de
        Textual."""
        from pykeepass.exceptions import CredentialsError
        from textual.screen import ModalScreen
        from textual.widgets import Input, Static

        def raise_credentials_error(ref, value):
            raise CredentialsError("mauvais mot de passe")

        self.secret_store.set = raise_credentials_error

        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()

            screen = app.screen
            screen.query_one("#acc_name", Input).value = "perso"
            screen.query_one("#acc_email", Input).value = "moi@x.ca"
            screen.query_one("#acc_password", Input).value = "hunter2"
            screen.query_one("#acc_imap", Input).value = "imap.x.ca"
            screen.query_one("#acc_smtp", Input).value = "smtp.x.ca"

            await pilot.press("ctrl+s")
            await pilot.pause()

            self.assertIsInstance(app.screen, ModalScreen)
            status = screen.query_one("#account_status", Static)
            self.assertTrue(str(status.content))
            self.assertEqual(app.sessions, [])
            self.assertEqual(mail_accounts.load(), [])

    async def test_available_backends_error_keeps_the_screen_open(self):
        """Le cinquième chemin (round 3) : `self.secret_store
        .available_backends()` tournait hors de toute garde, alors que
        `password` était déjà une variable locale. Le vrai
        `keyring.core.load_config()` peut lever `ModuleNotFoundError` ou
        `AttributeError` sur un backend configuré mais cassé — ni l'une ni
        l'autre n'est une `OSError`."""
        from textual.screen import ModalScreen
        from textual.widgets import Input, Static

        def raise_broken_backend():
            raise ModuleNotFoundError("backend keyring introuvable")

        self.secret_store.available_backends = raise_broken_backend

        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()

            screen = app.screen
            screen.query_one("#acc_name", Input).value = "perso"
            screen.query_one("#acc_email", Input).value = "moi@x.ca"
            screen.query_one("#acc_password", Input).value = "hunter2"
            screen.query_one("#acc_imap", Input).value = "imap.x.ca"
            screen.query_one("#acc_smtp", Input).value = "smtp.x.ca"

            await pilot.press("ctrl+s")
            await pilot.pause()

            self.assertIsInstance(app.screen, ModalScreen)
            status = screen.query_one("#account_status", Static)
            self.assertTrue(str(status.content))
            self.assertEqual(app.sessions, [])

    async def test_guard_covers_the_first_statement_in_action_save(self):
        """Protection structurelle (round 3) : casse la TOUTE PREMIÈRE
        lecture faite à l'intérieur du `try` d'`action_save` (`#acc_name`)
        — si ce test repasse au rouge, c'est que le `try` a de nouveau été
        repoussé après cette ligne."""
        from textual.screen import ModalScreen
        from textual.widgets import Static

        app = await self._mounted_app()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()

            screen = app.screen
            orig_query_one = screen.query_one

            def failing_query_one(selector, *args, **kwargs):
                if selector == "#acc_name":
                    raise RuntimeError("échec simulé sur la 1re lecture")
                return orig_query_one(selector, *args, **kwargs)

            screen.query_one = failing_query_one

            await pilot.press("ctrl+s")
            await pilot.pause()

            self.assertIsInstance(app.screen, ModalScreen)
            status = orig_query_one("#account_status", Static)
            self.assertTrue(str(status.content))


class TestPasswordClearedBeforeDismiss(TuiAccountCase):
    """Round 4 : `password`/`confirm` ne sont pas scopés au `try` par
    Python — ils restent des noms liés dans le cadre de
    `_create`/`_choose`/`action_save` jusqu'au retour de la fonction, garde
    ou pas. Round 3 affirmait, à tort, que le `try` "s'étend jusqu'au
    dismiss compris" ; il ne l'atteint pas textuellement.

    Vérifié avant d'écrire quoi que ce soit (Textual 8.2.8,
    `textual/screen.py:130` et `textual/message_pump.py:507-519,695-704`,
    puis confirmé empiriquement par un script autonome) :
    `Screen.dismiss()` ne rappelle PAS son callback de résultat
    directement — `ResultCallback.__call__` fait
    `self.requester.call_next(self.callback, result)`, qui EMPILE l'appel
    pour le cycle de message SUIVANT. Ce callback (`_after_account_added`/
    `_after_vault_screen`) tourne donc APRÈS que cette méthode soit
    retournée pour de bon, dans un cadre d'appel disjoint — une exception
    qui y survient n'inclut PAS le cadre de `action_save`/`_create`/
    `_choose` dans sa traceback (vérifié : marcher `exc.__traceback__`
    depuis un tel échec ne trouve jamais ce cadre). Le "sixième chemin" tel
    que décrit (le cadre appelant vivant pendant un callback synchrone)
    n'est donc pas démontré sur cette version de Textual.

    Ce qui reste vrai et vaut la peine d'être gardé : `password`/`confirm`
    n'ont plus aucun usage après le `try`, et les mettre à `None` avant
    `dismiss()` ne coûte rien — de la défense en profondeur, pas la
    fermeture d'une fuite démontrée. Ces tests vérifient donc la propriété
    réelle du code : au moment où `dismiss()` est appelé, le mot de passe
    n'est plus dans les locales de l'appelant — sans prétendre qu'un
    callback en aval y aurait accès de toute façon."""

    def setUp(self):
        super().setUp()
        # Par défaut : `_create`/`_choose` exigent l'ABSENCE de kdbx
        # configuré. Le test `action_save` reconfigure un kdbx localement
        # avant de monter l'app.
        self.config_file = FakeConfigFile()

    async def test_password_is_cleared_before_dismiss_in_action_save(self):
        import sys

        from textual.widgets import Input

        self.config_file.set_config_value(
            ["kdbx", "path"], "/already/configured.kdbx"
        )

        app = await self._mounted_app()
        captured = {}

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()

            screen = app.screen
            screen.query_one("#acc_name", Input).value = "perso"
            screen.query_one("#acc_email", Input).value = "moi@x.ca"
            screen.query_one("#acc_password", Input).value = "hunter2"
            screen.query_one("#acc_imap", Input).value = "imap.x.ca"
            screen.query_one("#acc_smtp", Input).value = "smtp.x.ca"

            orig_dismiss = type(screen).dismiss

            def spying_dismiss(self_screen, result=None):
                # Le cadre de l'APPELANT de `dismiss()` est `action_save`
                # lui-même : c'est exactement ce qu'on veut inspecter.
                caller = sys._getframe(1)
                captured["password"] = caller.f_locals.get(
                    "password", "absent-des-locales"
                )
                return orig_dismiss(self_screen, result)

            screen.dismiss = spying_dismiss.__get__(screen)

            await pilot.press("ctrl+s")
            await pilot.pause()

        self.assertIn("password", captured)
        self.assertIsNone(captured["password"])

    async def test_password_is_cleared_before_dismiss_in_create(self):
        import sys

        from textual.widgets import Input

        app = await self._mounted_app()
        captured = {}

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()

            screen = app.screen
            vault_path = os.path.join(self.cache_dir.name, "new.kdbx")
            screen.query_one("#vault_path", Input).value = vault_path
            screen.query_one("#vault_password", Input).value = "hunter2"
            screen.query_one("#vault_password_confirm", Input).value = (
                "hunter2"
            )

            orig_dismiss = type(screen).dismiss

            def spying_dismiss(self_screen, result=None):
                caller = sys._getframe(1)
                captured["password"] = caller.f_locals.get(
                    "password", "absent-des-locales"
                )
                captured["confirm"] = caller.f_locals.get(
                    "confirm", "absent-des-locales"
                )
                return orig_dismiss(self_screen, result)

            screen.dismiss = spying_dismiss.__get__(screen)

            await pilot.click("#vault_create")
            await pilot.pause()

        self.assertIn("password", captured)
        self.assertIsNone(captured["password"])
        self.assertIsNone(captured["confirm"])

    async def test_password_is_cleared_before_dismiss_in_choose(self):
        import sys

        from pykeepass import create_database
        from textual.widgets import Input

        vault_path = os.path.join(self.cache_dir.name, "existing.kdbx")
        create_database(vault_path, password="hunter2")

        app = await self._mounted_app()
        captured = {}

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()

            screen = app.screen
            screen.query_one("#vault_path", Input).value = vault_path
            screen.query_one("#vault_password", Input).value = "hunter2"

            orig_dismiss = type(screen).dismiss

            def spying_dismiss(self_screen, result=None):
                caller = sys._getframe(1)
                captured["password"] = caller.f_locals.get(
                    "password", "absent-des-locales"
                )
                return orig_dismiss(self_screen, result)

            screen.dismiss = spying_dismiss.__get__(screen)

            await pilot.click("#vault_choose")
            await pilot.pause()

        self.assertIn("password", captured)
        self.assertIsNone(captured["password"])


if __name__ == "__main__":
    unittest.main()
