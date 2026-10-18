# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""The deck kernel: the page shown, the OK/ERR flash, the dispatch of
keys, renders and ticks to the plugins, and their isolation.

Every plugin call goes through guard(): an exception is written to the
journal once per (plugin, call, error) until that call succeeds again,
and the kernel recovers (flash ERR, home screen, empty key) instead of
dying. handle_key, render and step's locked part expect the caller to
hold `lock`; the app's key callback and loop() take it."""

import sys
import threading
import time
import traceback
import types

from erplibre_streamdeck import dbus as dbus_mod
from erplibre_streamdeck.context import Context
from erplibre_streamdeck.plugin import Geometry
from erplibre_streamdeck.ui import colors, render

HOME = "idle"
# How long the OK/ERR feedback stays on the pressed key and its four
# neighbours; key presses are ignored meanwhile.
RESULT_FLASH_SEC = 0.5
# While the extension's D-Bus interface is missing, look for it again
# this often: the service can start before GNOME Shell exports it.
DBUS_RECHECK_SEC = 5.0
# The home screen redraws this often: the mic and the session tiles
# follow the system without a tick of their own.
HOME_REFRESH_SEC = 2.0
LOOP_SEC = 0.3


class ErrorLog:
    """Which (plugin, call) last failed with which error."""

    def __init__(self):
        self._last = {}

    def failed(self, plugin_id, what, exc):
        """True when this failure must be written: a new error for this
        call, or the first since it last succeeded."""
        sig = (type(exc).__name__, str(exc))
        if self._last.get((plugin_id, what)) == sig:
            return False
        self._last[(plugin_id, what)] = sig
        return True

    def succeeded(self, plugin_id, what):
        self._last.pop((plugin_id, what), None)


class Kernel:
    def __init__(self, deck, plugins):
        from erplibre_streamdeck import home

        self.deck = deck
        rows, cols = deck.key_layout()
        self.geo = Geometry(cols, rows, cols * rows)
        self.lock = threading.Lock()
        self.running = True
        self.page_id = HOME
        self.flash_result = None
        self.flash_time = 0.0
        self.last_press_key = None
        self.dbus = dbus_mod
        self.errors = ErrorLog()
        self._states = {}
        self._contexts = {}
        self._schedule = {}
        self.refused = []
        self.plugins = []
        self.pages = {}
        self.page_keys = {}
        self.home = home.Home(self.geo, [])
        for lp in self._setup(list(plugins)):
            keys = {}
            for page in lp.plugin.pages:
                ok, value = (
                    self.guard(
                        lp.id, f"page {page.id} keys", page.keys, self.geo
                    )
                    if page.keys
                    else (True, None)
                )
                if not ok:
                    self.refused.append((lp.id, "keys raised"))
                    break
                keys[page.id] = value
            else:
                self.plugins.append(lp)
                for page in lp.plugin.pages:
                    self.pages[page.id] = (lp.id, page)
                    self.page_keys[page.id] = keys[page.id]
        self.home = home.Home(self.geo, self.plugins)
        self.dbus_ok = self.dbus.available()
        self._dbus_checked_at = time.monotonic()

    # -- plugin plumbing

    def _setup(self, plugins):
        kept = []
        for lp in plugins:
            if lp.plugin.setup is not None:
                ok, _ = self.guard(
                    lp.id, "setup", lp.plugin.setup, self.ctx(lp.id)
                )
                if not ok:
                    self.refused.append((lp.id, "setup raised"))
                    continue
            kept.append(lp)
        return kept

    def state(self, plugin_id):
        if plugin_id not in self._states:
            self._states[plugin_id] = types.SimpleNamespace()
        return self._states[plugin_id]

    def ctx(self, plugin_id):
        if plugin_id not in self._contexts:
            self._contexts[plugin_id] = Context(self, plugin_id)
        return self._contexts[plugin_id]

    def guard(self, plugin_id, what, fn, *args):
        """Call fn(*args); (True, result), or (False, None) after
        writing the error to the journal (see ErrorLog)."""
        try:
            result = fn(*args)
        except Exception as exc:
            if self.errors.failed(plugin_id, what, exc):
                print(
                    f"[erplibre-home] {plugin_id}: {what} failed: "
                    f"{exc!r}\n{traceback.format_exc()}",
                    file=sys.stderr,
                    flush=True,
                )
            return False, None
        self.errors.succeeded(plugin_id, what)
        return True, result

    def paint(self, key, face):
        render.set_key(
            self.deck, key, face.color, face.text, face.icon,
            face.extra_draw,
        )

    # -- pages and flash

    def set_flash(self, ok):
        self.flash_result = "ok" if ok else "err"
        self.flash_time = time.monotonic()

    def _flash_live(self):
        return (
            self.flash_result is not None
            and time.monotonic() - self.flash_time < RESULT_FLASH_SEC
        )

    def goto(self, page_id):
        if page_id != HOME and page_id not in self.pages:
            print(
                f"[erplibre-home] kernel: unknown page {page_id}",
                file=sys.stderr,
                flush=True,
            )
            page_id = HOME
        self.page_id = page_id
        self.render()

    def render(self):
        if self.flash_result:
            if self._flash_live():
                self._render_page()
                self._overlay_flash()
                return
            self.flash_result = None
        self._render_page()

    def _render_page(self):
        if self.page_id not in self.pages:
            self.page_id = HOME
        if self.page_id != HOME:
            owner, page = self.pages[self.page_id]
            ok, _ = self.guard(
                owner, f"page {page.id} render", page.render,
                self.ctx(owner),
            )
            if ok:
                return
            self.page_id = HOME
        self.home.render(self)

    def _overlay_flash(self):
        color = colors.OK if self.flash_result == "ok" else colors.ERR
        label = "OK!" if self.flash_result == "ok" else "ERR"
        if self.last_press_key is None:
            # No key pressed yet (a flash raised by a tick): the whole
            # deck shows it.
            keys = range(self.geo.total_keys)
        else:
            keys = self._key_neighbors(self.last_press_key)
            keys.add(self.last_press_key)
        for k in keys:
            if 0 <= k < self.geo.total_keys:
                render.set_key(self.deck, k, color, label)

    def _key_neighbors(self, key):
        cols, rows = self.geo.cols, self.geo.rows
        if key is None or cols <= 0 or rows <= 0:
            return set()
        col, row = key % cols, key // cols
        out = set()
        for dc, dr in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nc, nr = col + dc, row + dr
            if 0 <= nc < cols and 0 <= nr < rows:
                out.add(nr * cols + nc)
        return out

    def handle_key(self, key, pressed):
        if not pressed or self._flash_live():
            return
        self.last_press_key = key
        if self.page_id not in self.pages:
            self.page_id = HOME
        if self.page_id == HOME:
            self.home.press(self, key)
            return
        owner, page = self.pages[self.page_id]
        ok, _ = self.guard(
            owner, f"page {page.id} handle", page.handle,
            self.ctx(owner), key,
        )
        if not ok:
            self.set_flash(False)
            self.goto(HOME)

    # -- loop

    def recheck_dbus(self, now):
        """While the extension is missing, look for it again every
        DBUS_RECHECK_SEC; True when it has just appeared, so the caller
        redraws. Once found it is never checked again."""
        if self.dbus_ok or now - self._dbus_checked_at < DBUS_RECHECK_SEC:
            return False
        self._dbus_checked_at = now
        self.dbus_ok = self.dbus.available()
        return self.dbus_ok

    def _due(self, name, period, now):
        if now - self._schedule.get(name, 0.0) >= period:
            self._schedule[name] = now
            return True
        return False

    def step(self, now):
        """One loop pass. Outside the lock: the D-Bus recheck (gdbus may
        take its 3 s timeout). Under it: a recorded flash ends the pass
        (rendered once expired); otherwise the page's tick, or on the
        home screen the due home ticks and at most one render."""
        if self.recheck_dbus(now):
            with self.lock:
                self.render()
        with self.lock:
            if self.flash_result:
                if not self._flash_live():
                    self.render()
                return
            if self.page_id not in self.pages:
                self.page_id = HOME
            if self.page_id == HOME:
                self._home_step(now)
                return
            owner, page = self.pages[self.page_id]
            if page.tick is None:
                return
            if not self._due(f"page:{page.id}", page.period, now):
                return
            ok, _ = self.guard(
                owner, f"page {page.id} tick", page.tick,
                self.ctx(owner), now,
            )
            if not ok:
                self.goto(HOME)

    def _home_step(self, now):
        want = False
        for lp in self.plugins:
            tick = lp.plugin.home_tick
            if tick is None:
                continue
            if not self._due(f"home:{lp.id}", lp.plugin.home_period, now):
                continue
            ok, asked = self.guard(
                lp.id, "home tick", tick, self.ctx(lp.id), now
            )
            want = want or bool(ok and asked)
        if self._due("home-refresh", HOME_REFRESH_SEC, now):
            want = True
        if want:
            self.render()

    def loop(self):
        self._schedule.clear()
        while self.running and self.deck.is_open():
            self.step(time.monotonic())
            time.sleep(LOOP_SEC)

    def shutdown(self):
        for lp in self.plugins:
            if lp.plugin.shutdown is not None:
                self.guard(
                    lp.id, "shutdown", lp.plugin.shutdown, self.ctx(lp.id)
                )
