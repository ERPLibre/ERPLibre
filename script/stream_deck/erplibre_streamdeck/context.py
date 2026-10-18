# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""The one object a plugin receives: the deck, the kernel's services,
and the plugin's own state namespace."""

import sys

from erplibre_streamdeck import settings as settings_mod
from erplibre_streamdeck.plugin import KeyFace
from erplibre_streamdeck.ui import i18n, render


class Context:
    def __init__(self, kernel, plugin_id):
        self._kernel = kernel
        self.plugin_id = plugin_id
        self.geo = kernel.geo
        self.dbus = kernel.dbus
        self.settings = settings_mod
        self.style = render.STYLE

    @property
    def page(self):
        """The id of the page shown; "idle" on the home screen."""
        return self._kernel.page_id

    @property
    def keys(self):
        """keys(geo) of the page shown, as computed at start."""
        return self._kernel.page_keys.get(self._kernel.page_id)

    @property
    def home_keys(self):
        """Plugin id -> its home button key, -1 when it has none."""
        return dict(self._kernel.home.home_keys)

    def t(self, label):
        return i18n.t(label)

    def set_key(self, key, color, text="", icon=None, extra_draw=None):
        """Paint one key; `color` may be a KeyFace."""
        if isinstance(color, KeyFace):
            color, text, icon, extra_draw = (
                color.color, color.text, color.icon, color.extra_draw
            )
        render.set_key(
            self._kernel.deck, key, color, text, icon, extra_draw
        )

    def flash(self, ok, reason=None):
        """Record the OK/ERR flash on the last pressed key; a reason for
        a failure goes to the journal. Does not render."""
        if not ok and reason:
            self.log(reason)
        self._kernel.set_flash(ok)

    def goto(self, page_id):
        self._kernel.goto(page_id)

    def home(self):
        self._kernel.goto("idle")

    def render(self):
        self._kernel.render()

    def run_blocking(self, work, then=None):
        """Run work() in a thread, without the lock; the next loop pass
        calls then(ctx, result, error) under it. work() uses only values
        captured before the call, plus `dbus` and `log`. False (and an
        ERR flash) while this plugin already has a job running."""
        return self._kernel.run_blocking(self.plugin_id, work, then)

    def state(self, plugin_id=None):
        return self._kernel.state(plugin_id or self.plugin_id)

    def locked(self):
        """The kernel lock, for a thread the plugin started:
        `with ctx.locked(): ...`. Never from a plugin callable: it
        already runs with the lock held, and the lock is not
        reentrant."""
        return self._kernel.lock

    def log(self, msg):
        print(
            f"[erplibre-home] {self.plugin_id}: {msg}",
            file=sys.stderr,
            flush=True,
        )
