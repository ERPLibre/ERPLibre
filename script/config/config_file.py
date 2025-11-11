#!/usr/bin/env python3
# © 2021-2025 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import json
import logging
import os
from typing import Any, Dict, Literal, Mapping

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
    def get_config(self, key_param: str):
        # Open file and update dct_data
        dct_data_init = {}
        dct_data_second = {}
        dct_data_final = {}

        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE) as cfg:
                dct_data_init = json.load(cfg)

        if os.path.exists(CONFIG_OVERRIDE_FILE):
            with open(CONFIG_OVERRIDE_FILE) as cfg:
                dct_data_second = json.load(cfg)

        if os.path.exists(CONFIG_OVERRIDE_PRIVATE_FILE):
            with open(CONFIG_OVERRIDE_PRIVATE_FILE) as cfg:
                dct_data_final = json.load(cfg)

        dct_data_first_merge = self.deep_merge_with_lists(
            dct_data_init, dct_data_final, list_strategy="extend"
        )
        dct_data = self.deep_merge_with_lists(
            dct_data_first_merge, dct_data_second, list_strategy="extend"
        )

        return dct_data.get(key_param)

    def get_config_value(self, lst_params: list):
        dct_data = self.get_config(lst_params[0])
        for param in lst_params[1:]:
            if param in dct_data.keys():
                find_in_private = True
                dct_data = dct_data.get(param)
        return dct_data

    def get_logo_ascii_file_path(self):
        return LOGO_ASCII_FILE

    def deep_merge_with_lists(
        self,
        dest: Mapping[str, Any],
        src: Mapping[str, Any],
        list_strategy: Literal["replace", "extend"] = "replace",
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for k, v in dest.items():
            result[k] = v.copy() if isinstance(v, dict) else v

        for k, v in src.items():
            if (
                k in result
                and isinstance(result[k], dict)
                and isinstance(v, dict)
            ):
                result[k] = self.deep_merge_with_lists(
                    result[k], v, list_strategy
                )
            elif (
                k in result
                and isinstance(result[k], list)
                and isinstance(v, list)
                and list_strategy == "extend"
            ):
                # on étend : dest_list + src_list
                result[k] = result[k] + v
            elif k in result and isinstance(result[k], str):
                if v:
                    result[k] = v
            else:
                result[k] = v
        return result
