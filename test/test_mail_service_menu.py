#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Menu Courriel [7] (ou [6] › [8]) : le service sans interface, sur des doubles.

`click.prompt` et `input` sont pilotés par `side_effect`, `getpass` par
un paramètre. Les fonctions de `service` et de `credential` qui touchent
au système sont des doubles ; `subprocess.run` est remplacé par une
assertion. `HOME` et `XDG_CONFIG_HOME` pointent vers des dossiers
temporaires.
"""

import contextlib
import getpass
import io
import os
import subprocess
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest import mock

from script.todo.mail import credential, menu, service
from script.todo.mail.accounts import account_from_preset
from script.todo.mail.service import ServiceError, ServiceStatus
from script.todo.todo_i18n import t

OWN = "boite.regles@example.org"
MAITRE = "maitre-essai"
AUTRE_DEPOT = "/srv/depot erplibre"
# La vraie lecture d'état, gardée avant que `setUp` la double.
_VRAI_STATUS = service.status


class FakeConfig(dict):
    """La configuration réduite à un dict ; une clé absente rend None."""

    def get_config_value(self, keys):
        valeur = self
        for cle in keys:
            if not isinstance(valeur, dict) or cle not in valeur:
                return None
            valeur = valeur[cle]
        return valeur


class FauxTodo:
    def __init__(self, config_file=None):
        self.config_file = config_file

    def _menu_header(self):
        return "--"


class FakeResource:
    """`resource` réduit à la limite des fichiers core."""

    RLIMIT_CORE = 4

    def __init__(self):
        self.limite = (1000, 2000)
        self.poses = []

    def getrlimit(self, which):
        assert which == self.RLIMIT_CORE
        return self.limite

    def setrlimit(self, which, valeur):
        assert which == self.RLIMIT_CORE
        self.poses.append(valeur)
        self.limite = valeur


class ServiceMenuCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.patch(
            mock.patch.dict(
                os.environ,
                {
                    "HOME": str(self.home),
                    "XDG_CONFIG_HOME": str(self.home / "ailleurs"),
                },
            )
        )
        self.patch(
            mock.patch.object(
                subprocess,
                "run",
                side_effect=AssertionError("programme système appelé"),
            )
        )
        self.run = mock.Mock(side_effect=AssertionError("run appelé"))
        self.account = account_from_preset("perso", OWN, "generic")
        self.account.cache_mode = "clear"
        self.account.secret_ref = "kdbx:Mail/perso"
        self.patch(
            mock.patch.object(menu, "_load_accounts", lambda: [self.account])
        )
        self.cred = self.home / "credstore.encrypted" / "erplibre-mail-kdbx"
        self.doubles = {}
        for module, nom, valeur in (
            (service, "status", ServiceStatus()),
            (service, "installed_repo", ""),
            (service, "installed_interval", None),
            (service, "install", None),
            (service, "uninstall", True),
            (service, "installed_parts", (True, True)),
            (service, "start_now", (0, "")),
            (service, "linger_enabled", True),
            (service, "enable_linger", True),
            (service, "disable_linger", True),
            (credential, "user_scope_supported", True),
            (credential, "credential_path", self.cred),
            (credential, "setup_credential", self.cred),
        ):
            self.doubles[nom] = self.patch(
                mock.patch.object(module, nom, return_value=valeur)
            )
        self.resource = FakeResource()
        self.patch(mock.patch.object(menu, "resource", self.resource))
        self.getpass = mock.Mock(return_value=MAITRE)
        self.config = FakeConfig(kdbx={"path": "private/essai.kdbx"})

    def patch(self, patcheur):
        valeur = patcheur.start()
        self.addCleanup(patcheur.stop)
        return valeur

    def lancer(self, invites, reponses=(), *, isatty=True, config=True):
        """`_service_menu` avec ces réponses à `click.prompt` et à
        `input` ; rend ce qui a été imprimé."""
        sortie = io.StringIO()
        with (
            mock.patch.object(
                menu.click, "prompt", side_effect=list(invites)
            ) as invite,
            mock.patch("builtins.input", side_effect=list(reponses)) as ask,
            contextlib.redirect_stdout(sortie),
        ):
            menu._service_menu(
                FauxTodo(self.config if config else None),
                run=self.run,
                getpass_fn=self.getpass,
                isatty=lambda: isatty,
            )
        self.invite = invite
        self.ask = ask
        return sortie.getvalue()

    def questions(self):
        return [c.args[0] for c in self.ask.call_args_list]

    def regle_active(self, enabled=True):
        """Une règle de réponse dans la base que lit le service."""
        from script.todo.mail.rules import storage
        from script.todo.mail.rules.model import (
            Condition,
            Group,
            new_rule,
        )
        from script.todo.mail.store import default_base

        rule = new_rule("reply", "Absence")
        rule.enabled = enabled
        rule.action.body = "Je suis absente."
        rule.filter = Group("all", [Condition("body", "bonjour")])
        storage.upsert_rule(self.account.name, rule, base=default_base())


class TestEntry(ServiceMenuCase):
    def test_entry_eight_opens_the_service_menu(self):
        base = self.home / "base"
        sortie = io.StringIO()
        with (
            mock.patch.object(menu, "_service_menu") as sous_menu,
            mock.patch("builtins.input", return_value="1"),
            mock.patch.object(
                menu.click, "prompt", side_effect=["8", "0"]
            ) as invite,
            contextlib.redirect_stdout(sortie),
        ):
            todo = FauxTodo()
            menu.prompt_mail_rules(todo, base=base)
        sous_menu.assert_called_once_with(todo)
        self.assertIn(
            f"[8] {t('mail_rules_menu_service')}",
            invite.call_args_list[0].args[0],
        )

    def test_the_mail_menu_opens_the_service_without_any_account(self):
        """Sans compte, le choix d'un compte du menu des règles s'arrête
        avant [8] : l'entrée [7] du menu Courriel ouvre le service quand
        même, pour le désinstaller."""
        sortie = io.StringIO()
        with (
            mock.patch.object(menu, "_configure_mail_logging"),
            mock.patch.object(menu, "_load_accounts", lambda: []),
            mock.patch.object(menu, "_service_menu") as sous_menu,
            mock.patch.object(
                menu.click, "prompt", side_effect=["7", "0"]
            ) as invite,
            contextlib.redirect_stdout(sortie),
        ):
            todo = FauxTodo()
            menu.prompt_execute_mail(todo)
        sous_menu.assert_called_once_with(todo)
        self.assertIn(
            f"[7] {t('mail_rules_menu_service')}",
            invite.call_args_list[0].args[0],
        )
        self.assertNotIn(t("mail_no_account"), sortie.getvalue())

    def test_the_menu_shows_the_state_then_its_entries(self):
        sortie = self.lancer(["0"])
        self.assertIn(service.status_text(ServiceStatus()), sortie)
        texte = self.invite.call_args_list[0].args[0]
        for rang, cle in enumerate(
            (
                "mail_service_menu_install",
                "mail_service_menu_credential",
                "mail_service_menu_start",
                "mail_service_menu_uninstall",
            ),
            start=1,
        ):
            self.assertIn(f"[{rang}] {t(cle)}", texte)
        self.doubles["status"].assert_called_with(
            run=self.run, config_file=self.config
        )

    def test_the_state_names_a_clear_vault_password_of_the_config(self):
        """Sans credential, un `kdbx.password` de la configuration se dit
        en clair et déconseillé ; sa valeur n'est jamais imprimée."""
        reel = _VRAI_STATUS
        muet = mock.Mock(return_value=mock.Mock(returncode=1, stdout=""))
        self.doubles["status"].side_effect = lambda **kw: reel(
            run=muet, config_file=kw.get("config_file")
        )
        self.config = FakeConfig(
            kdbx={"path": "private/essai.kdbx", "password": "repli-essai"}
        )
        sortie = self.lancer(["0"])
        self.assertIn(t("mail_service_status_credential_config"), sortie)
        self.assertNotIn(t("mail_service_status_credential_no"), sortie)
        self.assertNotIn("repli-essai", sortie)
        self.config = FakeConfig(kdbx={"path": "private/essai.kdbx"})
        sortie = self.lancer(["0"])
        self.assertIn(t("mail_service_status_credential_no"), sortie)

    def test_start_runs_a_pass_or_says_why_not(self):
        sortie = self.lancer(["3", "0"])
        self.assertIn(t("mail_service_started"), sortie)
        self.doubles["start_now"].return_value = (1, "Unit not found")
        sortie = self.lancer(["3", "0"])
        self.assertIn(
            f"{t('mail_service_install_failed')} Unit not found", sortie
        )


class TestInstall(ServiceMenuCase):
    def test_install_asks_the_interval_and_installs(self):
        self.doubles["installed_interval"].return_value = 12
        sortie = self.lancer(["1", 9, "0"])
        self.doubles["install"].assert_called_once_with(9, run=self.run)
        appel = self.invite.call_args_list[1]
        self.assertEqual(appel.args[0], t("mail_service_ask_interval"))
        self.assertEqual(appel.kwargs["default"], 12)
        borne = appel.kwargs["type"]
        self.assertEqual((borne.min, borne.max), (1, 1440))
        self.assertIn(f"{t('mail_service_installed')} 9 min", sortie)
        self.assertIn(t("mail_service_journal_hint"), sortie)
        self.assertIn(t("mail_service_dev_checkout_warning"), sortie)

    def test_the_default_interval_is_five_minutes(self):
        self.lancer(["1", 5, "0"])
        self.assertEqual(self.invite.call_args_list[1].kwargs["default"], 5)

    def test_a_refused_install_is_printed_and_the_menu_stays(self):
        self.doubles["install"].side_effect = ServiceError("refusé")
        sortie = self.lancer(["1", 5, "0"])
        self.assertIn("refusé", sortie)
        self.assertNotIn(t("mail_service_installed"), sortie)
        self.doubles["linger_enabled"].assert_not_called()

    def test_install_warns_one_host_per_account(self):
        sortie = self.lancer(["1", 5, "0"])
        self.assertIn(t("mail_service_one_host_warning"), sortie)

    def test_install_warns_about_linger_and_enables_it_only_on_yes(self):
        self.doubles["linger_enabled"].return_value = False
        for reponse in ("n", "", "plus tard"):
            with self.subTest(reponse=reponse):
                sortie = self.lancer(["1", 5, "0"], [reponse])
                self.assertIn(t("mail_service_linger_off"), sortie)
                self.assertIn(
                    t("mail_service_linger_ask"), self.questions()[0]
                )
                self.doubles["enable_linger"].assert_not_called()
        sortie = self.lancer(["1", 5, "0"], ["o"])
        self.doubles["enable_linger"].assert_called_once_with(run=self.run)
        self.assertIn(t("mail_service_linger_on"), sortie)
        self.doubles["enable_linger"].return_value = False
        sortie = self.lancer(["1", 5, "0"], ["yes"])
        self.assertIn(t("mail_service_linger_failed"), sortie)
        self.assertIn(t("mail_service_linger_hint"), sortie)

    def test_linger_unknown_or_on_asks_nothing(self):
        for etat in (True, None):
            with self.subTest(etat=etat):
                self.doubles["linger_enabled"].return_value = etat
                sortie = self.lancer(["1", 5, "0"])
                self.assertNotIn(t("mail_service_linger_off"), sortie)
                self.assertEqual(self.questions(), [])
        self.doubles["enable_linger"].assert_not_called()

    def test_install_without_credential_warns_when_a_kdbx_account_exists(
        self,
    ):
        self.regle_active()
        sortie = self.lancer(["1", 5, "0"])
        self.assertIn(t("mail_service_needs_credential"), sortie)
        self.cred.parent.mkdir(parents=True)
        self.cred.write_bytes(b"\x00chiffre")
        sortie = self.lancer(["1", 5, "0"])
        self.assertNotIn(t("mail_service_needs_credential"), sortie)
        self.cred.unlink()
        self.account.secret_ref = "keyring:mail/perso"
        sortie = self.lancer(["1", 5, "0"])
        self.assertNotIn(t("mail_service_needs_credential"), sortie)

    def test_a_configured_vault_password_needs_no_credential(self):
        self.regle_active()
        self.config = FakeConfig(
            kdbx={"path": "private/essai.kdbx", "password": "repli"}
        )
        sortie = self.lancer(["1", 5, "0"])
        self.assertNotIn(t("mail_service_needs_credential"), sortie)
        self.config = FakeConfig(
            kdbx={"path": "private/essai.kdbx", "password": ""}
        )
        sortie = self.lancer(["1", 5, "0"])
        self.assertIn(t("mail_service_needs_credential"), sortie)

    def test_an_account_without_active_rule_needs_no_credential(self):
        sortie = self.lancer(["1", 5, "0"])
        self.assertNotIn(t("mail_service_needs_credential"), sortie)
        self.regle_active(enabled=False)
        sortie = self.lancer(["1", 5, "0"])
        self.assertNotIn(t("mail_service_needs_credential"), sortie)

    def test_install_from_another_checkout_asks_first(self):
        self.doubles["installed_repo"].return_value = AUTRE_DEPOT
        for reponse in ("n", ""):
            with self.subTest(reponse=reponse):
                sortie = self.lancer(["1", "0"], [reponse])
                self.assertIn(t("mail_service_other_repo"), sortie)
                self.assertIn(AUTRE_DEPOT, sortie)
                self.assertIn(str(service.repo_root()), sortie)
                self.assertIn(
                    t("mail_service_other_repo_ask"), self.questions()[0]
                )
                self.assertIn(t("mail_service_creds_cancelled"), sortie)
                self.doubles["install"].assert_not_called()
        self.lancer(["1", 5, "0"], ["o"])
        self.doubles["install"].assert_called_once_with(5, run=self.run)

    def test_the_same_checkout_asks_nothing(self):
        self.doubles["installed_repo"].return_value = str(service.repo_root())
        sortie = self.lancer(["1", 5, "0"])
        self.assertNotIn(t("mail_service_other_repo"), sortie)
        self.assertEqual(self.questions(), [])


class TestCredential(ServiceMenuCase):
    def test_the_credential_assistant_never_prints_the_password(self):
        sortie = self.lancer(["2", "0"], ["o"])
        self.doubles["setup_credential"].assert_called_once_with(
            MAITRE,
            kdbx_path="private/essai.kdbx",
            dest=self.cred,
            run=self.run,
        )
        self.getpass.assert_called_once_with(t("mail_service_creds_ask"))
        self.assertIn(t("mail_service_creds_scope_warning"), sortie)
        self.assertIn(f"{t('mail_service_creds_written')} {self.cred}", sortie)
        self.assertNotIn(MAITRE, sortie)
        for appel in self.invite.call_args_list + self.ask.call_args_list:
            self.assertNotIn(MAITRE, repr(appel))

    def test_a_refused_password_is_printed_without_it(self):
        self.doubles[
            "setup_credential"
        ].side_effect = credential.CredentialError(
            t("mail_service_creds_wrong")
        )
        sortie = self.lancer(["2", "0"], ["o"])
        self.assertIn(t("mail_service_creds_wrong"), sortie)
        self.assertNotIn(t("mail_service_creds_written"), sortie)
        self.assertNotIn(MAITRE, sortie)

    def test_a_credstore_write_failure_does_not_blame_systemd_creds(self):
        """Un OSError ne vient que de l'écriture du credstore : le message
        nomme le dossier, pas `systemd-creds`, et pas le chemin."""
        self.doubles["setup_credential"].side_effect = PermissionError(
            13, "refusé", str(self.home / "credstore.encrypted")
        )
        sortie = self.lancer(["2", "0"], ["o"])
        self.assertIn(
            f"{t('mail_service_creds_write_failed')} PermissionError", sortie
        )
        self.assertNotIn(t("mail_service_creds_failed"), sortie)
        self.assertNotIn(str(self.home), sortie)
        self.assertNotIn(t("mail_service_creds_written"), sortie)

    def test_without_a_kdbx_nothing_is_asked(self):
        sortie = self.lancer(["2", "0"], config=False)
        self.assertIn(t("mail_service_creds_no_kdbx"), sortie)
        self.config = FakeConfig()
        sortie = self.lancer(["2", "0"])
        self.assertIn(t("mail_service_creds_no_kdbx"), sortie)
        self.getpass.assert_not_called()
        self.doubles["user_scope_supported"].assert_not_called()

    def test_the_credential_assistant_refuses_without_user_scope(self):
        self.doubles["user_scope_supported"].return_value = False
        sortie = self.lancer(["2", "0"])
        self.assertIn(t("mail_service_creds_unsupported"), sortie)
        self.assertIn(t("mail_service_creds_unsupported_hint"), sortie)
        self.getpass.assert_not_called()
        self.doubles["setup_credential"].assert_not_called()

    def test_the_credential_assistant_stops_on_no_without_any_call(self):
        for reponse in ("n", "", "peut-être"):
            with self.subTest(reponse=reponse):
                sortie = self.lancer(["2", "0"], [reponse])
                self.assertIn(t("mail_service_creds_cancelled"), sortie)
                self.assertIn(
                    t("mail_service_creds_scope_ask"), self.questions()[0]
                )
        self.getpass.assert_not_called()
        self.run.assert_not_called()
        self.doubles["setup_credential"].assert_not_called()
        self.doubles["credential_path"].assert_not_called()
        self.assertEqual(self.resource.poses, [])

    def test_the_credential_assistant_refuses_without_a_tty(self):
        sortie = self.lancer(["2", "0"], isatty=False)
        self.assertIn(t("mail_service_creds_no_tty"), sortie)
        self.getpass.assert_not_called()
        self.doubles["setup_credential"].assert_not_called()
        self.assertFalse(self.cred.exists())

    def test_a_getpass_that_would_echo_is_refused(self):
        def en_echo(invite):
            warnings.warn("écho", getpass.GetPassWarning, stacklevel=1)
            return MAITRE

        self.getpass.side_effect = en_echo
        sortie = self.lancer(["2", "0"], ["o"])
        self.assertIn(t("mail_service_creds_no_tty"), sortie)
        self.doubles["setup_credential"].assert_not_called()

    def test_an_empty_password_cancels(self):
        self.getpass.return_value = ""
        sortie = self.lancer(["2", "0"], ["o"])
        self.assertIn(t("mail_service_creds_cancelled"), sortie)
        self.doubles["setup_credential"].assert_not_called()

    def test_the_credential_assistant_restores_the_core_limit(self):
        pendant = []
        self.getpass.side_effect = lambda invite: (
            pendant.append(self.resource.limite) or MAITRE
        )
        self.lancer(["2", "0"], ["o"])
        self.assertEqual(pendant, [(0, 2000)])
        self.assertEqual(self.resource.limite, (1000, 2000))
        # Rendue aussi quand l'assistant lève.
        self.resource.poses.clear()
        self.doubles["setup_credential"].side_effect = RuntimeError("panne")
        with self.assertRaises(RuntimeError):
            self.lancer(["2", "0"], ["o"])
        self.assertEqual(self.resource.poses, [(0, 2000), (1000, 2000)])
        self.assertEqual(self.resource.limite, (1000, 2000))


class TestUninstall(ServiceMenuCase):
    def test_uninstall_asks_twice_and_passes_the_answer(self):
        self.doubles["linger_enabled"].return_value = False
        sortie = self.lancer(["4", "0"], ["o", ""])
        self.doubles["uninstall"].assert_called_once_with(
            remove_credential=True, run=self.run
        )
        self.assertEqual(
            [q.strip() for q in self.questions()[:2]],
            [
                t("mail_service_uninstall_ask"),
                t("mail_service_creds_delete_ask"),
            ],
        )
        self.assertIn(t("mail_service_uninstalled"), sortie)
        for garder in ("n", "non", "NO"):
            with self.subTest(garder=garder):
                self.doubles["uninstall"].reset_mock()
                self.lancer(["4", "0"], ["o", garder])
                self.doubles["uninstall"].assert_called_once_with(
                    remove_credential=False, run=self.run
                )
        self.doubles["uninstall"].reset_mock()
        self.lancer(["4", "0"], ["n"])
        self.doubles["uninstall"].assert_not_called()

    def test_nothing_installed_is_said(self):
        self.doubles["uninstall"].return_value = False
        sortie = self.lancer(["4", "0"], ["o", ""])
        self.assertIn(t("mail_service_not_installed"), sortie)
        self.doubles["linger_enabled"].assert_not_called()

    def test_nothing_installed_nor_credential_asks_nothing(self):
        self.doubles["installed_parts"].return_value = (False, False)
        sortie = self.lancer(["4", "0"])
        self.assertIn(t("mail_service_not_installed"), sortie)
        self.assertEqual(self.questions(), [])
        self.doubles["uninstall"].assert_not_called()

    def test_without_credential_only_the_uninstall_is_asked(self):
        self.doubles["installed_parts"].return_value = (True, False)
        self.doubles["linger_enabled"].return_value = False
        sortie = self.lancer(["4", "0"], ["o"])
        self.assertEqual(
            [q.strip() for q in self.questions()],
            [t("mail_service_uninstall_ask")],
        )
        self.doubles["uninstall"].assert_called_once_with(
            remove_credential=False, run=self.run
        )
        self.assertIn(t("mail_service_uninstalled"), sortie)

    def test_a_refused_uninstall_is_printed(self):
        self.doubles["uninstall"].side_effect = ServiceError(
            t("mail_service_no_systemd_uninstall")
        )
        sortie = self.lancer(["4", "0"], ["o", ""])
        self.assertIn(t("mail_service_no_systemd_uninstall"), sortie)
        self.assertNotIn(t("mail_service_no_systemd"), sortie)
        self.assertNotIn(t("mail_service_uninstalled"), sortie)

    def test_uninstall_offers_to_disable_linger_only_when_on(self):
        self.doubles["linger_enabled"].return_value = True
        sortie = self.lancer(["4", "0"], ["o", "", "o"])
        self.assertIn(
            t("mail_service_linger_disable_ask"), self.questions()[2]
        )
        self.doubles["disable_linger"].assert_called_once_with(run=self.run)
        self.assertIn(t("mail_service_linger_disabled"), sortie)
        self.doubles["disable_linger"].reset_mock()
        self.lancer(["4", "0"], ["o", "", ""])
        self.doubles["disable_linger"].assert_not_called()
        for etat in (False, None):
            with self.subTest(etat=etat):
                self.doubles["linger_enabled"].return_value = etat
                self.lancer(["4", "0"], ["o", ""])
                self.assertEqual(len(self.questions()), 2)
        self.doubles["disable_linger"].assert_not_called()
        self.doubles["linger_enabled"].return_value = True
        self.doubles["disable_linger"].return_value = False
        sortie = self.lancer(["4", "0"], ["o", "", "y"])
        self.assertIn(t("mail_service_linger_failed"), sortie)


class TestEnvironmentUntouched(ServiceMenuCase):
    def test_a_full_tour_leaves_no_unit_nor_credential(self):
        self.lancer(["1", 5, "2", "3", "4", "0"], ["o", "o", "", ""])
        self.assertFalse((self.home / ".config").exists())
        self.assertFalse((self.home / "ailleurs").exists())
        self.assertFalse((self.home / ".erplibre").exists())
        self.run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
