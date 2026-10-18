# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Discovery of the deck plugins.

Two directories: the package's plugins/, then the user's
$XDG_CONFIG_HOME/erplibre-home/deck-plugins/. A plugin's id is its file
stem ([a-z][a-z0-9_]*); files starting with "_" are skipped. A user
plugin replaces a repository plugin of the same id. An id listed in
DECK_PLUGINS_OFF is not imported. A plugin is refused, with its reason
in the report, when its import raises (SystemExit included), it has no
PLUGIN, its api is not PLUGIN_API, a field of PLUGIN has the wrong shape
(see _shape_error), or one of its pages is already taken; the others
load. A directory that cannot be listed counts as empty, with one
"unreadable" entry in the report under its path."""

import importlib
import importlib.util
import os
import re
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path

from erplibre_streamdeck import paths
from erplibre_streamdeck.plugin import (
    Fixture,
    HomeButton,
    LoadedPlugin,
    Page,
    Plugin,
    PLUGIN_API,
    TileProvider,
)

ID_RE = re.compile(r"[a-z][a-z0-9_]*\Z")
REPO_DIR = Path(__file__).resolve().parent / "plugins"
USER_PACKAGE = "erplibre_streamdeck_user"


@dataclass
class Report:
    entries: list = field(default_factory=list)

    def add(self, pid, status, detail=""):
        self.entries.append((pid, status, detail))

    @staticmethod
    def line(pid, status, detail=""):
        return f"{pid}: {status}" + (f": {detail}" if detail else "")

    def lines(self):
        return [self.line(*entry) for entry in self.entries]


def _files(directory, report):
    """The plugin files of `directory`, sorted; [] when it is None or
    not a directory, and [] plus an "unreadable" entry when listing it
    raises OSError."""
    if directory is None:
        return []
    directory = Path(directory)
    try:
        if not directory.is_dir():
            return []
        names = os.listdir(directory)
    except OSError as exc:
        report.add(
            str(directory),
            "unreadable",
            f"{type(exc).__name__}: {exc.strerror or exc}",
        )
        return []
    return sorted(
        directory / name for name in names
        if name.endswith(".py") and not name.startswith("_")
    )


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_order(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _optional(value):
    return value is None or callable(value)


def _shape_error(plugin):
    """Why `plugin`'s fields cannot be laid out or called, or None. The
    kernel and the home screen read these fields unguarded: orders are
    sorted, page ids are dict keys, callables are called."""
    if not isinstance(plugin.pages, list):
        return "pages is not a list"
    for page in plugin.pages:
        if not isinstance(page, Page) or not isinstance(page.id, str):
            return "pages must hold Pages with a str id"
        if not (callable(page.render) and callable(page.handle)
                and _optional(page.keys) and _optional(page.tick)
                and _is_number(page.period)):
            return f"page {page.id} has a field of the wrong type"
    button = plugin.home_button
    if button is not None and not (
        isinstance(button, HomeButton) and _is_order(button.order)
        and callable(button.face) and callable(button.press)
    ):
        return ("home_button must be None or a HomeButton with an int "
                "order and callables")
    for name, cls, calls in (
        ("fixtures", Fixture, ("place", "face", "press")),
        ("tiles", TileProvider, ("items", "face", "press")),
    ):
        items = getattr(plugin, name)
        if not isinstance(items, list):
            return f"{name} is not a list"
        for item in items:
            if not (isinstance(item, cls) and _is_order(item.order)
                    and all(callable(getattr(item, c)) for c in calls)):
                return (f"{name} must hold {cls.__name__}s with an int "
                        "order and callables")
    for name in ("home_tick", "setup", "shutdown"):
        if not _optional(getattr(plugin, name)):
            return f"{name} is not callable"
    if not _is_number(plugin.home_period):
        return "home_period is not a number"
    return None


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
        for path in _files(directory, report):
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
        except (Exception, SystemExit) as exc:
            # SystemExit: a plugin calling sys.exit() at import must not
            # stop the deck. KeyboardInterrupt still propagates.
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
        shape = _shape_error(plugin)
        if shape:
            report.add(pid, "refused", shape)
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
