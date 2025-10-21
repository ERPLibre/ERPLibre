#!/usr/bin/env python3
# © 2021-2025 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import json
import logging
import os

CONFIG_FILE = "./script/todo/todo.json"
CONFIG_OVERRIDE_FILE = "./private/todo/todo_override.json"
CONFIG_OVERRIDE_PRIVATE_FILE = "./private/todo/todo_override_private.json"
LOGO_ASCII_FILE = "./script/todo/logo_ascii.txt"

logging.basicConfig(
    format=(
        "%(asctime)s,%(msecs)d %(levelname)-8s [%(filename)s:%(lineno)d]"
        " %(message)s"
    ),
    datefmt="%Y-%m-%d:%H:%M:%S",
    level=logging.INFO,
)
_logger = logging.getLogger(__name__)


class ConfigFile:
    def get_config(self, lst_params):
        # Open file
        config_file = CONFIG_FILE
        if os.path.exists(CONFIG_OVERRIDE_FILE):
            config_file = CONFIG_OVERRIDE_FILE

        find_in_private = False
        if os.path.exists(CONFIG_OVERRIDE_PRIVATE_FILE):
            with open(CONFIG_OVERRIDE_PRIVATE_FILE) as cfg:
                dct_data = json.load(cfg)
                for param in lst_params:
                    if param in dct_data.keys():
                        find_in_private = True
                        dct_data = dct_data[param]

        if not find_in_private:
            with open(config_file) as cfg:
                dct_data = json.load(cfg)
                for param in lst_params:
                    try:
                        dct_data = dct_data[param]
                    except KeyError:
                        _logger.error(
                            f"KeyError on file {config_file} with keys"
                            f" {lst_params}"
                        )
                        return {}
        return dct_data

    def get_logo_ascii_file_path(self):
        return LOGO_ASCII_FILE
