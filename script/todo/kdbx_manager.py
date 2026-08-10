#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import getpass
import logging

from script.todo.todo_i18n import t

_logger = logging.getLogger(__name__)

try:
    import tkinter as tk
    from tkinter import filedialog

    from pykeepass import PyKeePass
    from pykeepass.exceptions import CredentialsError
except ModuleNotFoundError:
    PyKeePass = None
    tk = None
    filedialog = None

    class CredentialsError(Exception):
        """Jamais levée ici : sans pykeepass, `get_kdbx` sort avant d'ouvrir
        quoi que ce soit. Définie pour que le `except` reste écrivable."""


class KdbxManager:
    def __init__(self, config_file) -> None:
        self._config_file = config_file
        self._kdbx = None

    def get_kdbx(self, attempts: int = 3):
        if self._kdbx:
            return self._kdbx

        kdbx_file_path = self._config_file.get_config_value(["kdbx", "path"])
        if not kdbx_file_path:
            if tk is None:
                _logger.error("tkinter is not available")
                return None
            root = tk.Tk()
            root.withdraw()
            kdbx_file_path = filedialog.askopenfilename(
                title="Select a File",
                filetypes=(("KeepassX files", "*.kdbx"),),
            )
        if not kdbx_file_path:
            _logger.error(
                "KDBX is not configured, please fill"
                f" {self._config_file.CONFIG_FILE}"
            )
            return None

        if PyKeePass is None:
            _logger.error("pykeepass is not installed")
            return None

        kdbx_password = self._config_file.get_config_value(
            ["kdbx", "password"]
        )
        if kdbx_password:
            # Mot de passe pris dans la configuration : personne à qui
            # redemander, mais il peut être faux — le dire au lieu de
            # laisser remonter une trace de la bibliothèque.
            try:
                self._kdbx = PyKeePass(kdbx_file_path, password=kdbx_password)
            except CredentialsError:
                print(t("kdbx_wrong_password"))
                return None
            return self._kdbx

        # Saisie interactive. Un mot de passe refusé est le cas NORMAL ici,
        # pas une panne : la bibliothèque lève `CredentialsError` et, sans
        # ce rattrapage, la trace remontait jusqu'à tuer le CLI. On nomme
        # aussi le coffre — l'invite ne disait pas DE QUOI elle parlait.
        print(f"{t('kdbx_vault_is')} {kdbx_file_path}")
        for _ in range(attempts):
            password = getpass.getpass(prompt=t("kdbx_ask_password"))
            if not password:
                print(t("kdbx_give_up"))
                return None
            try:
                self._kdbx = PyKeePass(kdbx_file_path, password=password)
            except CredentialsError:
                print(t("kdbx_wrong_password"))
                continue
            return self._kdbx
        print(t("kdbx_give_up"))
        return None

    def get_extra_command_user(
        self, kdbx_key: str | list | None
    ) -> str | list:
        values = []
        if kdbx_key:
            kp = self.get_kdbx()
            if not kp:
                return ""
            if type(kdbx_key) is not list:
                kdbx_keys = [kdbx_key]
            else:
                kdbx_keys = kdbx_key
            for key in kdbx_keys:
                entry = kp.find_entries_by_title(key, first=True)
                try:
                    odoo_user = entry.username
                except AttributeError:
                    _logger.error(f"Cannot find username from keys {key}")
                try:
                    odoo_password = entry.password
                except AttributeError:
                    _logger.error(f"Cannot find password from keys {key}")
                values.append(
                    " --default_email_auth"
                    f" {odoo_user} --default_password_auth"
                    f" '{odoo_password}'"
                )
        if len(values) == 0:
            return ""
        elif len(values) == 1:
            return values[0]
        return values
