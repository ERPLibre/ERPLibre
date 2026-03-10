#!/usr/bin/env python3
# © 2021-2025 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import getpass
import logging

from script.todo.todo_i18n import t

_logger = logging.getLogger(__name__)

try:
    import tkinter as tk
    from tkinter import filedialog

    from pykeepass import PyKeePass
except ModuleNotFoundError:
    PyKeePass = None
    tk = None
    filedialog = None


class KdbxManager:
    def __init__(self, config_file):
        self._config_file = config_file
        self._kdbx = None

    def get_kdbx(self):
        if self._kdbx:
            return self._kdbx

        kdbx_file_path = self._config_file.get_config_value(
            ["kdbx", "path"]
        )
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

        kdbx_password = self._config_file.get_config_value(
            ["kdbx", "password"]
        )
        if not kdbx_password:
            kdbx_password = getpass.getpass(prompt=t("enter_password"))

        if PyKeePass is None:
            _logger.error("pykeepass is not installed")
            return None

        kp = PyKeePass(kdbx_file_path, password=kdbx_password)
        if kp:
            self._kdbx = kp
        return kp

    def get_extra_command_user(self, kdbx_key):
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
                    _logger.error(
                        f"Cannot find username from keys {key}"
                    )
                try:
                    odoo_password = entry.password
                except AttributeError:
                    _logger.error(
                        f"Cannot find password from keys {key}"
                    )
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
