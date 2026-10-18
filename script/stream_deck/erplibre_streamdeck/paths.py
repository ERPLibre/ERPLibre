# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Every path of the deck program, anchored on this file.

settings.json and layouts.json live under the literal
~/.config/erplibre-home, the location the deck has always written; the
user plugin directory follows $XDG_CONFIG_HOME, like streamdeck.conf.
The state directory is read at call time from $XDG_STATE_HOME."""

import os
from pathlib import Path

STREAM_DECK_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = STREAM_DECK_DIR.parent.parent
CONFIG_DIR = Path(os.path.expanduser("~/.config/erplibre-home"))
SETTINGS_FILE = CONFIG_DIR / "settings.json"
LAYOUTS_FILE = CONFIG_DIR / "layouts.json"
SETTINGS_LIB = REPO_ROOT / "script/install/erplibre_home_settings.sh"


def state_dir():
    """$XDG_STATE_HOME/erplibre-home, ~/.local/state when unset."""
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser(
        "~/.local/state"
    )
    return Path(base) / "erplibre-home"


def user_plugin_dir():
    """$XDG_CONFIG_HOME/erplibre-home/deck-plugins, ~/.config when
    unset or empty."""
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser(
        "~/.config"
    )
    return Path(base) / "erplibre-home" / "deck-plugins"
