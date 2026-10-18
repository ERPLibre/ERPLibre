# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""DEV RELOAD: ask the GNOME extension to reload itself (HotReload)."""

from erplibre_streamdeck.plugin import (
    PLUGIN_API, HomeButton, KeyFace, Plugin,
)
from erplibre_streamdeck.ui import colors


def _hot_reload_extension(ctx):
    """Call the extension's HotReload D-Bus method. Returns True on
    success: exit 0 and a non-empty string answer."""
    try:
        r = ctx.dbus.call("HotReload", timeout=10)
        if not r.ok:
            ctx.log(f"HotReload dbus: {r.stderr.strip()}")
            return False
        return bool(r.string)
    except Exception as e:
        ctx.log(f"HotReload error: {e}")
        return False


def _press(ctx):
    ctx.flash(_hot_reload_extension(ctx))
    ctx.render()


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
