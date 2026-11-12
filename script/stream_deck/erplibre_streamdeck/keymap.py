# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""keymap.json: the home layout of each deck model, format 1.

The GNOME extension writes the file; the deck program only reads it, at
each kernel build. Its shape:

    {"format": 1, "revision": 7,
     "layouts": {"0084": {"keys": [
       {"key": 0, "action": "plugin:timers", "icon": "timer",
        "label": "Timers"},
       {"key": 1, "action": "tiles"},
       {"key": 2, "action": "empty"}]}}}

`layouts` maps a USB product id, 4 lowercase hex digits, to a layout;
at most MAX_MODELS of them. A layout's `keys` holds at most the model's
key count of entries: `key` an int in [0, total_keys), unique; `action`
"plugin:<id>" (that plugin's home button), "tiles" (a dashboard key) or
"empty" (a black key); `icon` a name of ui/icons.py ICONS, or absent;
`label` a str of at most LABEL_MAX code points without a control
character, or absent. `icon` and `label` replace the face of a home
button only; on "tiles" and "empty" they are checked and unused. Fields
not named here are ignored.

load() keeps today's automatic layout ({}) for a file missing,
unreadable, larger than MAX_BYTES, not JSON, of another format, or with
too many models. layout_for() keeps it (None) for a model absent or a
layout without a keys list or with more entries than keys; otherwise an
invalid entry is skipped, and a plugin not loaded leaves its key empty,
each with one problem line.

catalog() is the --catalog output: what a layout may name on this
checkout, and the geometry of every visual model the Stream Deck
library knows."""

import json
import re
import sys
import unicodedata
from dataclasses import dataclass

from erplibre_streamdeck import paths
from erplibre_streamdeck.ui import icons

FORMAT = 1
MAX_MODELS = 16
LABEL_MAX = 16
# A keymap.json of MAX_MODELS models of the largest deck is far below.
MAX_BYTES = 256 * 1024
# Journal lines of one build's problems; the rest is counted in one line.
PROBLEM_LINES = 10
PLUGIN_ID = r"[a-z][a-z0-9_]{0,63}"
PLUGIN_ACTION_RE = re.compile(rf"plugin:({PLUGIN_ID})\Z")
FIXED_ACTIONS = ("tiles", "empty")


@dataclass(frozen=True)
class Entry:
    key: int
    action: str
    icon: str | None = None
    label: str | None = None


def _journal(msg):
    print(f"[erplibre-home] keymap: {msg}", file=sys.stderr, flush=True)


def _show(value):
    """A value of the file as a journal shows it: repr, cut at 40."""
    text = repr(value)
    return text if len(text) <= 40 else text[:39] + "…"


def load(path=None):
    """The parsed keymap.json at `path` (default paths.KEYMAP_FILE), or
    {} with one journal line when it cannot be used; {} silently when
    there is no file."""
    path = paths.KEYMAP_FILE if path is None else path
    try:
        with open(path, "rb") as f:
            raw = f.read(MAX_BYTES + 1)
    except FileNotFoundError:
        return {}
    except OSError as exc:
        _journal(f"{path}: unreadable: {exc.strerror or exc}")
        return {}
    if len(raw) > MAX_BYTES:
        _journal(f"{path}: larger than {MAX_BYTES} bytes, ignored")
        return {}
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        _journal(f"{path}: not JSON: {type(exc).__name__}, ignored")
        return {}
    why = _file_error(data)
    if why:
        _journal(f"{path}: {why}, ignored")
        return {}
    return data


def _file_error(data):
    """Why the top level of a parsed file is not format 1, or None."""
    if not isinstance(data, dict):
        return "not an object"
    fmt = data.get("format")
    if isinstance(fmt, bool) or fmt != FORMAT:
        return f"format {_show(fmt)} is not {FORMAT}"
    layouts = data.get("layouts")
    if not isinstance(layouts, dict):
        return "layouts is not an object"
    if len(layouts) > MAX_MODELS:
        return f"{len(layouts)} models, more than {MAX_MODELS}"
    return None


def _label_error(label):
    if not isinstance(label, str):
        return f"label {_show(label)} is not a string"
    if len(label) > LABEL_MAX:
        return f"label longer than {LABEL_MAX}"
    if any(unicodedata.category(c) == "Cc" for c in label):
        return "label with a control character"
    return None


def _entry(raw, total_keys, icon_names):
    """(Entry, None) for a valid entry, or (None, why)."""
    if not isinstance(raw, dict):
        return None, "not an object"
    key = raw.get("key")
    if (
        not isinstance(key, int)
        or isinstance(key, bool)
        or not 0 <= key < total_keys
    ):
        return None, f"key {_show(key)} outside 0..{total_keys - 1}"
    action = raw.get("action")
    if not isinstance(action, str) or not (
        action in FIXED_ACTIONS or PLUGIN_ACTION_RE.match(action)
    ):
        return None, f"unknown action {_show(action)}"
    icon = raw.get("icon")
    if "icon" in raw and (not isinstance(icon, str) or icon not in icon_names):
        return None, f"unknown icon {_show(icon)}"
    label = raw.get("label")
    if "label" in raw:
        why = _label_error(label)
        if why:
            return None, why
    return Entry(key, action, icon, label), None


def layout_for(data, product_id_hex, geo, plugin_ids, icon_names):
    """The layout of model `product_id_hex` in `data` (load()'s result)
    on `geo`: (entries, problems). entries is None when the automatic
    layout stays; a "plugin:<id>" entry whose id is not in `plugin_ids`
    (the loaded plugins with a home button) becomes an "empty" entry.
    problems holds one line per entry skipped or emptied, and one per
    plugin of `plugin_ids` the layout does not name."""
    layouts = data.get("layouts") if isinstance(data, dict) else None
    if not isinstance(layouts, dict) or product_id_hex not in layouts:
        return None, []
    where = f"layout {product_id_hex}"
    layout = layouts[product_id_hex]
    keys = layout.get("keys") if isinstance(layout, dict) else None
    if not isinstance(keys, list):
        return None, [f"{where}: no keys list, automatic layout kept"]
    if len(keys) > geo.total_keys:
        return None, [
            f"{where}: {len(keys)} entries for {geo.total_keys} keys, "
            "automatic layout kept"
        ]
    plugin_ids = set(plugin_ids)
    entries, problems = [], []
    seen_keys, seen_plugins = set(), set()
    for index, raw in enumerate(keys):
        entry, why = _entry(raw, geo.total_keys, icon_names)
        if entry is None:
            problems.append(f"{where} entry {index}: {why}: skipped")
            continue
        if entry.key in seen_keys:
            problems.append(
                f"{where} entry {index}: key {entry.key} already named: "
                "skipped"
            )
            continue
        match = PLUGIN_ACTION_RE.match(entry.action)
        if match:
            pid = match.group(1)
            if pid in seen_plugins:
                problems.append(
                    f"{where} entry {index}: plugin {pid} already has a "
                    "key: skipped"
                )
                continue
            seen_plugins.add(pid)
            if pid not in plugin_ids:
                problems.append(
                    f"{where}: plugin {pid} not loaded with a home "
                    f"button: key {entry.key} left empty"
                )
                entry = Entry(entry.key, "empty")
        seen_keys.add(entry.key)
        entries.append(entry)
    for pid in sorted(plugin_ids - seen_plugins):
        problems.append(f"{where}: plugin {pid} has no key")
    return entries, problems


def capped(problems):
    """The first PROBLEM_LINES problems, and one line counting the rest:
    a hostile file cannot flood the journal."""
    lines = list(problems[:PROBLEM_LINES])
    rest = len(problems) - PROBLEM_LINES
    if rest > 0:
        lines.append(f"{rest} more problems not shown")
    return lines


def models():
    """{"<4 hex>": {"cols", "rows", "keys"}} of every visual model of
    the Stream Deck library, sorted. The library's "dummy" transport
    answers one deck object per product id it knows, built from the
    class constants: no device is opened or even looked for."""
    from StreamDeck.DeviceManager import DeviceManager

    found = {}
    for deck in DeviceManager("dummy").enumerate():
        if not deck.is_visual():
            continue
        rows, cols = deck.key_layout()
        found[f"{deck.product_id():04x}"] = {
            "cols": cols,
            "rows": rows,
            "keys": deck.key_count(),
        }
    return dict(sorted(found.items()))


def catalog(plugins):
    """The --catalog output for the loaded `plugins`: format, the
    actions ("plugin:<id>" of each plugin with a home button, sorted,
    then "tiles" and "empty"), the icon names, and models()."""
    actions = sorted(
        f"plugin:{lp.id}"
        for lp in plugins
        if lp.plugin.home_button is not None
    )
    return {
        "format": FORMAT,
        "actions": actions + list(FIXED_ACTIONS),
        "icons": sorted(icons.ICONS),
        "models": models(),
    }
