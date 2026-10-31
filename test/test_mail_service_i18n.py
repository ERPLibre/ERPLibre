#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les chaînes du service sans interface : commande, coffre, unités,
menu [8] et état.

`t()` rend la clé elle-même quand elle manque : rien n'échoue, et
l'écran afficherait « mail_service_exit_243 » en toutes lettres.
"""

import re
import unittest
from pathlib import Path

from script.todo.mail import service
from script.todo.todo_i18n import TRANSLATIONS

SERVICE_KEYS = (
    "mail_service_cli_description",
    "mail_service_cli_account_help",
    "mail_service_cli_quiet_help",
    "mail_service_already_running",
    "mail_service_accounts_unreadable",
    "mail_service_no_account",
    "mail_service_unknown_account",
    "mail_service_no_active_rules",
    "mail_service_account_disabled",
    "mail_service_account_ephemeral",
    "mail_service_rules_unreadable",
    "mail_service_vault_locked",
    "mail_service_vault_no_password",
    "mail_service_vault_wrong_password",
    "mail_service_vault_not_configured",
    "mail_service_vault_unreadable",
    "mail_service_vault_no_pykeepass",
    "mail_service_keyring_no_bus",
    "mail_service_keyring_locked",
    "mail_service_keyring_unsafe",
    "mail_service_keyring_timeout",
    "mail_service_keyring_unsupported",
    "mail_service_keyring_no_collection",
    "mail_service_kind_vault",
    "mail_service_kind_auth",
    "mail_service_kind_network",
    "mail_service_kind_busy",
    "mail_service_kind_cache",
    "mail_service_kind_config",
    "mail_service_kind_other",
    "mail_service_outbox_error",
    "mail_service_folder_errors",
    "mail_service_busy",
    "mail_service_rule_error",
    "mail_service_unexpected",
    "mail_err_kdbx_busy",
    "mail_service_creds_no_kdbx",
    "mail_service_creds_unsupported",
    "mail_service_creds_unsupported_hint",
    "mail_service_creds_ask",
    "mail_service_creds_wrong",
    "mail_service_creds_failed",
    "mail_service_creds_verify_failed",
    "mail_service_creds_written",
    "mail_service_creds_cancelled",
    "mail_service_creds_no_tty",
    "mail_service_creds_scope_warning",
    "mail_service_creds_scope_ask",
    "mail_service_creds_delete_ask",
    "mail_rules_menu_service",
    "mail_service_menu_install",
    "mail_service_menu_credential",
    "mail_service_menu_start",
    "mail_service_menu_uninstall",
    "mail_service_ask_interval",
    "mail_service_interval_refused",
    "mail_service_installed",
    "mail_service_install_failed",
    "mail_service_no_systemd",
    "mail_service_no_venv",
    "mail_service_path_refused",
    "mail_service_needs_credential",
    "mail_service_journal_hint",
    "mail_service_started",
    "mail_service_uninstall_ask",
    "mail_service_uninstalled",
    "mail_service_not_installed",
    "mail_service_linger_off",
    "mail_service_linger_ask",
    "mail_service_linger_on",
    "mail_service_linger_failed",
    "mail_service_linger_hint",
    "mail_service_linger_disable_ask",
    "mail_service_linger_disabled",
    "mail_service_one_host_warning",
    "mail_service_dev_checkout_warning",
    "mail_service_other_repo",
    "mail_service_other_repo_ask",
    "mail_service_status_title",
    "mail_service_status_reading",
    "mail_service_status_not_installed",
    "mail_service_status_installed_off",
    "mail_service_status_active",
    "mail_service_status_next",
    "mail_service_status_last_exit",
    "mail_service_status_outdated",
    "mail_service_status_other_repo",
    "mail_service_status_repo_missing",
    "mail_service_status_unknown",
    "mail_service_status_credential_yes",
    "mail_service_status_credential_no",
    "mail_service_status_credential_config",
)
# Fichiers dont chaque `t("mail_…")` littéral doit être déclaré.
SOURCES = (
    "script/todo/mail/service.py",
    "script/todo/mail/credential.py",
    "script/todo/mail/menu.py",
    "script/todo/mail/rules/run.py",
)
REPO = Path(__file__).resolve().parents[1]


class TestServiceKeys(unittest.TestCase):
    def assert_translated(self, keys):
        manquantes = sorted(
            cle
            for cle in keys
            if not (
                isinstance(TRANSLATIONS.get(cle), dict)
                and TRANSLATIONS[cle].get("fr")
                and TRANSLATIONS[cle].get("en")
            )
        )
        self.assertEqual(manquantes, [], f"clés sans fr/en : {manquantes}")

    def test_every_service_key_exists_in_both_languages(self):
        self.assert_translated(SERVICE_KEYS)

    def test_every_exit_code_has_a_label(self):
        self.assertEqual(
            service.EXIT_LABELS, (0, 1, 2, 3, 4, 5, 6, 7, 8, 200, 203, 243)
        )
        self.assert_translated(
            f"mail_service_exit_{code}" for code in service.EXIT_LABELS
        )

    def test_every_literal_key_of_the_service_files_is_declared(self):
        motif = re.compile(r"""(?<![A-Za-z_])t\((["'])(mail_[a-z0-9_]+)\1\)""")
        utilisees = set()
        for chemin in SOURCES:
            texte = (REPO / chemin).read_text(encoding="utf-8")
            utilisees |= {m.group(2) for m in motif.finditer(texte)}
        self.assertIn("mail_service_status_title", utilisees)
        self.assert_translated(utilisees)

    def test_the_active_label_takes_the_interval(self):
        for langue in ("fr", "en"):
            texte = TRANSLATIONS["mail_service_status_active"][langue]
            self.assertIn("{n}", texte)
            self.assertNotIn("{n}", texte.format(n=5))


if __name__ == "__main__":
    unittest.main()
