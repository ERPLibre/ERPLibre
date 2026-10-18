# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Discovery of the deck plugins.

Two directories: the package's plugins/, then the user's
$XDG_CONFIG_HOME/erplibre-home/deck-plugins/. A plugin's id is its file
stem ([a-z][a-z0-9_]*); files starting with "_" are skipped. A user
plugin replaces a repository plugin of the same id. An id listed in
DECK_PLUGINS_OFF is not imported. A plugin is refused, with its reason
in the report, when its import raises, it has no PLUGIN, its api is not
PLUGIN_API, or one of its pages is already taken; the others load."""

import importlib
import importlib.util
import re
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path

from erplibre_streamdeck import paths
from erplibre_streamdeck.plugin import LoadedPlugin, Plugin, PLUGIN_API

ID_RE = re.compile(r"[a-z][a-z0-9_]*\Z")
REPO_DIR = Path(__file__).resolve().parent / "plugins"
USER_PACKAGE = "erplibre_streamdeck_user"


@dataclass
class Report:
    entries: list = field(default_factory=list)

    def add(self, pid, status, detail=""):
        self.entries.append((pid, status, detail))

    def lines(self):
        out = []
        for pid, status, detail in self.entries:
            out.append(f"{pid}: {status}" + (f": {detail}" if detail else ""))
        return out


def parse_off(text):
    return [part.strip() for part in text.split(",") if part.strip()]


def _files(directory):
    if directory is None or not Path(directory).is_dir():
        return []
    return sorted(
        p for p in Path(directory).glob("*.py")
        if not p.name.startswith("_")
    )


def _import(pid, path, by_name):
    """The package's own plugins import by module name, so they share
    the package's module identity; any other file imports by path."""
    if by_name:
        return importlib.import_module(f"erplibre_streamdeck.plugins.{pid}")
    if USER_PACKAGE not in sys.modules:
        sys.modules[USER_PACKAGE] = types.ModuleType(USER_PACKAGE)
    name = f"{USER_PACKAGE}.{pid}"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def load(off=(), repo_dir=None, user_dir=None):
    repo_dir = REPO_DIR if repo_dir is None else repo_dir
    user_dir = paths.user_plugin_dir() if user_dir is None else user_dir
    report = Report()
    chosen = {}
    for origin, directory in (("repo", repo_dir), ("user", user_dir)):
        for path in _files(directory):
            pid = path.stem
            if not ID_RE.match(pid):
                report.add(pid, "refused", "file name is not a plugin id")
                continue
            if pid in chosen and origin == "user":
                report.add(pid, "replaced by user", str(chosen[pid][1]))
            chosen[pid] = (origin, path)
    off = set(off)
    loaded, pages = [], {}
    for pid in sorted(chosen):
        origin, path = chosen[pid]
        if pid in off:
            report.add(pid, "off")
            continue
        by_name = origin == "repo" and Path(repo_dir) == REPO_DIR
        try:
            module = _import(pid, path, by_name)
        except Exception as exc:
            report.add(pid, "refused", f"import: {type(exc).__name__}: {exc}")
            continue
        plugin = getattr(module, "PLUGIN", None)
        if not isinstance(plugin, Plugin):
            report.add(pid, "refused", "no PLUGIN")
            continue
        if plugin.api != PLUGIN_API:
            report.add(
                pid, "refused", f"api {plugin.api} != {PLUGIN_API}"
            )
            continue
        clash = [p.id for p in plugin.pages if p.id in pages]
        if clash:
            report.add(
                pid,
                "refused",
                f"page {clash[0]} already taken by {pages[clash[0]]}",
            )
            continue
        for page in plugin.pages:
            pages[page.id] = pid
        loaded.append(LoadedPlugin(pid, plugin, origin, path))
        report.add(pid, "active", origin)
    return loaded, report
