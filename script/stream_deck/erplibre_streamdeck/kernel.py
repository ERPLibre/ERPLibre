# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""The deck kernel: the page shown, the OK/ERR flash, the dispatch of
keys, renders and ticks to the plugins, and their isolation.

Every plugin call goes through guard(): an exception is written to the
journal once per (plugin, call, error) until that call succeeds again,
and the kernel recovers (flash ERR, home screen, empty key) instead of
dying. A plugin's SystemExit is such an exception; the one a SIGTERM
raises (deck_lock.SigtermExit) is the service's stop and passes.
handle_key, render and step's locked part expect the caller to hold
`lock`; on_key() (the deck's key callback) and loop() take it.
Both also catch what escapes a pass under the plugin id "kernel", so
neither thread dies.

A slow call runs through run_blocking(): a worker thread runs it without
the lock, and the next loop pass hands its result back under the lock.
Until then the plugin is busy: its last pressed key shows "…", and its
presses, polls, page tick and home tick do not reach it; key 0 of its
page still leaves for the home screen.

A plugin's polls (plugin.Poll) feed its renders: read() runs in the loop
thread with the lock released, so a slow process never holds the keys,
and store() keeps the result under the lock."""

import sys
import threading
import time
import traceback
import types

import deck_lock

from erplibre_streamdeck import dbus as dbus_mod
from erplibre_streamdeck.context import Context
from erplibre_streamdeck.plugin import Geometry, KeyFace
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
    def __init__(self, deck, plugins, settings=None):
        from erplibre_streamdeck import home

        self.deck = deck
        # Read-only deck settings (Context.setting); set before any
        # plugin setup runs.
        self.settings = dict(settings or {})
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
        # Plugin id -> (page id, key) of the press that started its job.
        self.busy = {}
        # (plugin id, then, result, error) of the jobs that ended: the
        # only kernel state a worker thread touches, under
        # _finished_lock.
        self._finished = []
        self._finished_lock = threading.Lock()
        self.refused = []
        self.plugins = []
        self.pages = {}
        self.page_keys = {}
        self.home = home.Home(self.geo, [], self.guard)
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
        self.home = home.Home(self.geo, self.plugins, self.guard)
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
        except deck_lock.SigtermExit:
            raise
        except (Exception, SystemExit) as exc:
            self._journal(plugin_id, what, exc, traceback.format_exc())
            return False, None
        self.errors.succeeded(plugin_id, what)
        return True, result

    def _journal(self, plugin_id, what, exc, trace):
        """Write `what failed: exc!r` and its traceback, unless ErrorLog
        has already written this failure."""
        if self.errors.failed(plugin_id, what, exc):
            print(
                f"[erplibre-home] {plugin_id}: {what} failed: "
                f"{exc!r}\n{trace}",
                file=sys.stderr,
                flush=True,
            )

    def paint(self, key, face):
        """Paint a KeyFace; raises what render.set_key raises on a bad
        field (a text that is not a str, a colour PIL refuses). Draws
        nothing once the kernel has stopped."""
        if not self.running:
            return
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
        if not self.running:
            return
        if self.flash_result:
            if self._flash_live():
                self._render_page()
                self._paint_busy()
                self._overlay_flash()
                return
            self.flash_result = None
        self._render_page()
        self._paint_busy()

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

    def on_key(self, deck, key, pressed):
        """The deck's key callback, run by the StreamDeck reader thread:
        an exception escaping it would end that thread's reads."""
        with self.lock:
            self.guard("kernel", "key callback", self.handle_key, key,
                       pressed)

    def handle_key(self, key, pressed):
        """A press reaches the plugin that owns the key, unless that
        plugin is busy: the press then flashes ERR, except key 0 of a
        page, which the kernel answers by going home. Key 0 is BACK on
        every page, so a long job never holds the deck on its page."""
        if not pressed or self._flash_live():
            return
        self.last_press_key = key
        if self.page_id not in self.pages:
            self.page_id = HOME
        if self.page_id == HOME:
            owner = self.home.owner(key)
        else:
            owner, page = self.pages[self.page_id]
        if owner in self.busy:
            if self.page_id != HOME and key == 0:
                self.goto(HOME)
                return
            self.set_flash(False)
            self.render()
            return
        if self.page_id == HOME:
            self.home.press(self, key)
            return
        ok, _ = self.guard(
            owner, f"page {page.id} handle", page.handle,
            self.ctx(owner), key,
        )
        if not ok:
            self.set_flash(False)
            self.goto(HOME)

    # -- slow actions

    def run_blocking(self, plugin_id, work, then=None):
        """Run work() in a thread, outside the lock; the plugin is busy
        until the next loop pass hands the result to then(ctx, result,
        error) under the lock. Called from a plugin callable, with the
        kernel lock held; it does not take the lock. False (and an ERR
        flash) when the plugin already has a job. A thread that cannot
        start raises here and leaves the plugin free."""
        if plugin_id in self.busy:
            self.set_flash(False)
            self.render()
            return False

        def runner():
            # Every exception reaches the result: a job that ends
            # without queuing would leave its plugin busy for good.
            # The traceback is formatted here, where it is current; the
            # drain journals it under the lock.
            try:
                result, error, trace = work(), None, None
            except BaseException as exc:
                result, error = None, exc
                trace = traceback.format_exc()
            with self._finished_lock:
                self._finished.append(
                    (plugin_id, then, result, error, trace)
                )

        threading.Thread(target=runner, daemon=True).start()
        # The caller holds the lock and drain_jobs() needs it: the job
        # cannot be drained before it is marked busy.
        self.busy[plugin_id] = (self.page_id, self.last_press_key)
        if self.flash_result:
            # A recorded flash, even expired, stays painted until a
            # render; render() clears an expired one and paints "…".
            self.render()
        else:
            self._paint_busy()
        return True

    def _paint_busy(self):
        """Paint "…" on the key of each job started on the page shown."""
        for page_id, key in self.busy.values():
            if key is not None and page_id == self.page_id:
                self.paint(key, KeyFace(colors.BUSY, "…"))

    def drain_jobs(self):
        """Hand finished jobs to their plugins; True when one ran. Once
        the kernel has stopped, results are dropped. A job that raised
        is journaled first, as "job failed", once until a job of that
        plugin ends without raising (ErrorLog). Without `then`, a
        truthy result without error flashes OK, anything else ERR."""
        with self._finished_lock:
            finished, self._finished = self._finished, []
        for plugin_id, then, result, error, trace in finished:
            self.busy.pop(plugin_id, None)
            if not self.running:
                continue
            if error is None:
                self.errors.succeeded(plugin_id, "job")
            else:
                self._journal(plugin_id, "job", error, trace)
            if then is None:
                self.set_flash(error is None and bool(result))
                self.render()
                continue
            ok, _ = self.guard(
                plugin_id, "job result", then, self.ctx(plugin_id),
                result, error,
            )
            if not ok:
                self.set_flash(False)
                self.render()
        return bool(finished)

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
        """One loop pass. Under the lock: a recorded flash ends the pass
        (rendered once expired); finished jobs are handed back, and a
        flash they record ends the pass too; the due polls are chosen.
        Outside it: the D-Bus recheck (gdbus may take its 3 s timeout)
        and the polls' read(). Under it again: their store(), then the
        page's tick, or on the home screen the due home ticks, with at
        most one render for the polls and the home step together. A
        busy plugin's polls and ticks are skipped."""
        with self.lock:
            if self.flash_result:
                if not self._flash_live():
                    self.render()
                return
            self.drain_jobs()
            if self.flash_result:
                return
            due = self._due_polls(now)
        if self.recheck_dbus(now):
            with self.lock:
                self.render()
        reads = [
            (lp, i, poll, self.guard(lp.id, f"poll {i} read", poll.read))
            for lp, i, poll in due
        ]
        with self.lock:
            # A key press may have flashed, or a shutdown stopped the
            # kernel, while the lock was released.
            if not self.running or self.flash_result:
                return
            want = False
            for lp, i, poll, (ok, data) in reads:
                if not ok:
                    continue
                ok, changed = self.guard(
                    lp.id, f"poll {i} store", poll.store, self.ctx(lp.id),
                    data,
                )
                want = want or bool(ok and changed)
            if self.page_id not in self.pages:
                self.page_id = HOME
            if self.page_id == HOME:
                self._home_step(now, want)
                return
            if want:
                self.render()
            self._page_tick(now)

    def _due_polls(self, now):
        """(plugin, index, poll) of the active polls whose period has
        elapsed; each has its own stamp, so the first pass takes them
        all."""
        due = []
        for lp in self.plugins:
            if lp.id in self.busy:
                continue
            for i, poll in enumerate(lp.plugin.polls):
                ok, active = self.guard(
                    lp.id, f"poll {i} active", poll.active, self.ctx(lp.id)
                )
                if ok and active and self._due(
                    f"poll:{lp.id}:{i}", poll.period, now
                ):
                    due.append((lp, i, poll))
        return due

    def _page_tick(self, now):
        owner, page = self.pages[self.page_id]
        if page.tick is None or owner in self.busy:
            return
        if not self._due(f"page:{page.id}", page.period, now):
            return
        ok, _ = self.guard(
            owner, f"page {page.id} tick", page.tick,
            self.ctx(owner), now,
        )
        if not ok:
            self.goto(HOME)

    def _home_step(self, now, want=False):
        """The due home ticks, then one render when a tick, the polls
        (`want`) or the HOME_REFRESH_SEC refresh asks for it."""
        for lp in self.plugins:
            tick = lp.plugin.home_tick
            if tick is None or lp.id in self.busy:
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
            self.guard("kernel", "loop pass", self.step, time.monotonic())
            time.sleep(LOOP_SEC)

    def shutdown(self):
        for lp in self.plugins:
            if lp.plugin.shutdown is not None:
                self.guard(
                    lp.id, "shutdown", lp.plugin.shutdown, self.ctx(lp.id)
                )
