# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""DEV RELOAD: ask the GNOME extension to reload itself (HotReload)."""

from erplibre_streamdeck.plugin import (
    PLUGIN_API, HomeButton, KeyFace, Plugin,
)
from erplibre_streamdeck.ui import colors


def _hot_reload(dbus, log):
    """HotReload on the extension; True on exit 0 with a non-empty
    answer. Runs outside the lock: only `dbus` and `log`."""
    try:
        r = dbus.call("HotReload", timeout=10)
        if not r.ok:
            log(f"HotReload dbus: {r.stderr.strip()}")
            return False
        return bool(r.string)
    except Exception as e:
        log(f"HotReload error: {e}")
        return False


def _press(ctx):
    # No `then`: the kernel flashes OK on a truthy result, ERR
    # otherwise, and renders.
    dbus, log = ctx.dbus, ctx.log
    ctx.run_blocking(lambda: _hot_reload(dbus, log))


PLUGIN = Plugin(
    api=PLUGIN_API,
    home_button=HomeButton(
        30,
        face=lambda ctx: KeyFace(
            colors.DEV_RELOAD, "DEV\nRELOAD", icon="dev_reload"
        ),
        press=_press,
    ),
)
