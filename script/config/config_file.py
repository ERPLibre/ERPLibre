#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
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
    def get_config(self, key_param: str) -> Any:
        config_base: dict = {}
        config_override: dict = {}
        config_private: dict = {}

        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE) as cfg:
                config_base = json.load(cfg)

        if os.path.exists(CONFIG_OVERRIDE_FILE):
            with open(CONFIG_OVERRIDE_FILE) as cfg:
                config_override = json.load(cfg)

        if os.path.exists(CONFIG_OVERRIDE_PRIVATE_FILE):
            with open(CONFIG_OVERRIDE_PRIVATE_FILE) as cfg:
                config_private = json.load(cfg)

        merged_base_private = self.deep_merge_with_lists(
            config_base, config_private, list_strategy="extend"
        )
        merged_config = self.deep_merge_with_lists(
            merged_base_private, config_override, list_strategy="extend"
        )

        return merged_config.get(key_param)

    def get_config_value(self, params: list[str]) -> Any:
        config_data = self.get_config(params[0])
        for param in params[1:]:
            if param in config_data:
                config_data = config_data.get(param)
        return config_data

    def get_logo_ascii_file_path(self) -> str:
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
                # Extend: dest_list + src_list
                result[k] = result[k] + v
            elif k in result and isinstance(result[k], str):
                if v:
                    result[k] = v
            else:
                result[k] = v
        return result
