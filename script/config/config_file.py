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

    def set_config_value(self, keys: list[str], value: Any) -> None:
        """Écrit `value` sous le chemin `keys` dans
        CONFIG_OVERRIDE_PRIVATE_FILE.

        C'est le seul des trois fichiers fusionnés par `get_config` qui
        soit gitignored (`git check-ignore` le confirme ; `private/` lui-
        même est un dossier versionné, et CONFIG_OVERRIDE_FILE ne l'est
        pas) — donc le seul où une valeur personnelle comme `kdbx.path`
        peut être écrite sans finir commitée.

        Fusionne avec le contenu existant plutôt que de l'écraser, et
        écrit de façon atomique : fichier temporaire créé en 0600 dans le
        même dossier, puis `os.replace` (qui hérite du mode de la source).
        Le fichier réel n'est donc jamais vu à moitié écrit, et un fichier
        déjà présent avec des permissions trop larges se retrouve corrigé.
        """
        data: Dict[str, Any] = {}
        if os.path.exists(CONFIG_OVERRIDE_PRIVATE_FILE):
            with open(CONFIG_OVERRIDE_PRIVATE_FILE) as cfg:
                data = json.load(cfg)

        node = data
        for key in keys[:-1]:
            node = node.setdefault(key, {})
        node[keys[-1]] = value

        parent = os.path.dirname(CONFIG_OVERRIDE_PRIVATE_FILE) or "."
        os.makedirs(parent, exist_ok=True)
        os.chmod(parent, 0o700)

        tmp_path = f"{CONFIG_OVERRIDE_PRIVATE_FILE}.tmp"
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as tmp_file:
            json.dump(data, tmp_file, indent=2, ensure_ascii=False)
        os.replace(tmp_path, CONFIG_OVERRIDE_PRIVATE_FILE)

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
