#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""The deck kernel: dispatch, flash, ticks, error isolation."""

import contextlib
import io
import os
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import streamdeck_stubs as S  # noqa: E402

S.install()
from erplibre_streamdeck import kernel as K  # noqa: E402
from erplibre_streamdeck.plugin import (  # noqa: E402
    Fixture,
    HomeButton,
    KeyFace,
    LoadedPlugin,
    Page,
    Plugin,
    PLUGIN_API,
    Poll,
    TileProvider,
)
from erplibre_streamdeck.ui import colors, render  # noqa: E402

# The real painter: KernelCase replaces it with a recorder, which takes
# any text; the real one calls len() on it.
REAL_SET_KEY = render.set_key


class StrictLock:
    """The kernel lock, whose acquire never waits: taken again while it
    is held, it raises where a threading.Lock would hang the test."""

    def __init__(self):
        self._lock = threading.Lock()

    def acquire(self, blocking=True, timeout=-1):
        if not self._lock.acquire(blocking=False):
            raise RuntimeError("kernel lock taken twice")
        return True

    def release(self):
        self._lock.release()

    def locked(self):
        return self._lock.locked()

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()


class FakeDbus:
    def __init__(self, ok=True):
        self.ok = ok
        self.checks = 0

    def available(self):
        self.checks += 1
        return self.ok


def loaded(pid, plugin):
    return LoadedPlugin(pid, plugin, "repo", Path(f"{pid}.py"))


class KernelCase(unittest.TestCase):
    def setUp(self):
        self.clock = S.FakeClock()
        self.journal = io.StringIO()
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(
            mock.patch("time.monotonic", self.clock.monotonic)
        )
        stack.enter_context(mock.patch("time.sleep", self.clock.sleep))
        stack.enter_context(
            mock.patch.object(render, "set_key", S.recorder())
        )
        stack.enter_context(contextlib.redirect_stderr(self.journal))
        self.deck = S.FakeDeck(5, 3)
        self.calls = []

    def kernel(self, *plugins, dbus=None):
        with mock.patch.object(K, "dbus_mod", dbus or FakeDbus()):
            return K.Kernel(self.deck, list(plugins))

    def page_plugin(self, pid="p", page_id="pg", **page_kw):
        def render_(ctx):
            self.calls.append(("render", page_id))
            ctx.set_key(0, (1, 2, 3), "X")

        def handle(ctx, key):
            self.calls.append(("handle", key))

        kw = dict(keys=None, render=render_, handle=handle)
        kw.update(page_kw)
        return loaded(pid, Plugin(api=PLUGIN_API, pages=[Page(page_id, **kw)]))


class DispatchTest(KernelCase):
    def test_release_is_ignored_and_press_goes_to_page(self):
        k = self.kernel(self.page_plugin())
        k.goto("pg")
        k.handle_key(3, False)
        k.handle_key(3, True)
        self.assertEqual([("render", "pg"), ("handle", 3)], self.calls)
        self.assertEqual(3, k.last_press_key)

    def test_press_during_flash_is_ignored(self):
        k = self.kernel(self.page_plugin())
        k.goto("pg")
        k.set_flash(True)
        k.handle_key(1, True)
        self.clock.advance(K.RESULT_FLASH_SEC)
        k.handle_key(2, True)
        self.assertEqual([("render", "pg"), ("handle", 2)], self.calls)

    def test_flash_overlays_pressed_key_and_neighbours(self):
        k = self.kernel(self.page_plugin())
        k.goto("pg")
        k.handle_key(7, True)
        k.set_flash(False)
        k.render()
        screen = self.deck.rendering()
        for key in (2, 6, 7, 8, 12):
            self.assertEqual("ERR", screen[key][1], key)
        self.assertEqual("X", screen[0][1])


class IsolationTest(KernelCase):
    def boom(self, *a):
        raise ValueError("bad")

    def test_handle_error_flashes_and_goes_home(self):
        k = self.kernel(self.page_plugin(handle=self.boom))
        k.goto("pg")
        k.handle_key(4, True)
        self.assertEqual("idle", k.page_id)
        self.assertEqual("err", k.flash_result)
        self.assertIn("p: page pg handle failed", self.journal.getvalue())

    def test_render_error_shows_home(self):
        k = self.kernel(self.page_plugin(render=self.boom))
        k.goto("pg")
        self.assertEqual("idle", k.page_id)

    def test_repeated_failure_logged_once(self):
        k = self.kernel(self.page_plugin(handle=self.boom))
        for _ in range(3):
            k.goto("pg")
            self.clock.advance(1)
            k.handle_key(4, True)
        self.assertEqual(
            1, self.journal.getvalue().count("page pg handle failed")
        )

    def test_logged_again_after_a_success(self):
        state = {"fail": True}

        def handle(ctx, key):
            if state["fail"]:
                raise ValueError("bad")

        k = self.kernel(self.page_plugin(handle=handle))
        for fail in (True, False, True):
            state["fail"] = fail
            k.goto("pg")
            self.clock.advance(1)
            k.handle_key(4, True)
        self.assertEqual(
            2, self.journal.getvalue().count("page pg handle failed")
        )

    def test_setup_error_refuses_the_plugin(self):
        bad = loaded(
            "bad",
            Plugin(api=PLUGIN_API, pages=[Page("b", None, print, print)],
                   setup=self.boom),
        )
        k = self.kernel(bad, self.page_plugin())
        self.assertEqual(["p"], [lp.id for lp in k.plugins])
        self.assertEqual("bad", k.refused[0][0])
        self.assertNotIn("b", k.pages)

    def test_shutdown_error_continues_with_the_next_plugin(self):
        ran = []
        a = loaded("a", Plugin(api=PLUGIN_API, shutdown=self.boom))
        b = loaded(
            "b",
            Plugin(api=PLUGIN_API, shutdown=lambda ctx: ran.append("b")),
        )
        self.kernel(a, b).shutdown()
        self.assertEqual(["b"], ran)
        self.assertIn("a: shutdown failed", self.journal.getvalue())


class LastResortTest(KernelCase):
    """What a plugin returns, or a bug in a pass, never stops the loop
    thread, the key callback or the first render."""

    def tile_plugin(self, face):
        return loaded("z", Plugin(api=PLUGIN_API, tiles=[TileProvider(
            5, lambda ctx: ["q"], lambda ctx, item: face,
            lambda ctx, item: None,
        )]))

    def test_face_whose_paint_raises_is_painted_empty(self):
        k = self.kernel(self.tile_plugin(KeyFace(colors.OK, 5)))
        key = k.home.pool[0]
        with mock.patch.object(render, "set_key", REAL_SET_KEY):
            k.render()
            k.render()
        last = [img for kk, img in self.deck.images if kk == key][-1]
        self.assertEqual(colors.EMPTY, last.color)
        self.assertEqual(
            1,
            self.journal.getvalue().count(f"z: key {key} paint failed"),
        )

    def test_loop_pass_that_raises_is_logged_and_the_loop_goes_on(self):
        k = self.kernel(self.page_plugin())
        passes = []

        def step(now):
            passes.append(now)
            raise RuntimeError("pass")

        self.deck.polls = 3
        with mock.patch.object(k, "step", step):
            k.loop()
        self.assertEqual(3, len(passes))
        self.assertEqual(
            1, self.journal.getvalue().count("kernel: loop pass failed")
        )

    def test_key_callback_that_raises_is_logged_and_unlocks(self):
        k = self.kernel(self.page_plugin())
        k.goto("pg")
        self.calls.clear()
        with mock.patch.object(
            k, "handle_key", side_effect=RuntimeError("key")
        ):
            k.on_key(self.deck, 3, True)
            k.on_key(self.deck, 3, True)
        self.assertFalse(k.lock.locked())
        self.assertEqual(
            1, self.journal.getvalue().count("kernel: key callback failed")
        )
        k.on_key(self.deck, 3, True)
        self.assertEqual([("handle", 3)], self.calls)


class UnknownPageTest(KernelCase):
    def test_goto_unknown_goes_home_and_loop_survives(self):
        k = self.kernel(self.page_plugin())
        k.goto("missing")
        self.assertEqual("idle", k.page_id)
        self.assertIn("unknown page missing", self.journal.getvalue())
        k.page_id = "poisoned"
        k.handle_key(1, True)
        self.assertEqual("idle", k.page_id)
        k.page_id = "poisoned"
        self.deck.polls = 2
        k.loop()
        self.assertEqual("idle", k.page_id)

    def test_keys_error_refuses_the_plugin(self):
        bad = loaded(
            "bad",
            Plugin(api=PLUGIN_API,
                   pages=[Page("b", lambda geo: 1 / 0, print, print)]),
        )
        k = self.kernel(bad, self.page_plugin())
        self.assertEqual(["p"], [lp.id for lp in k.plugins])
        self.assertEqual(("bad", "keys raised"), k.refused[0])
        self.assertNotIn("b", k.pages)


class TickTest(KernelCase):
    def test_flash_blocks_every_tick(self):
        ticks = []
        k = self.kernel(
            self.page_plugin(tick=lambda ctx, now: ticks.append(now))
        )
        k.goto("pg")
        k.set_flash(True)
        k.step(self.clock.now)          # flash live: nothing
        self.clock.advance(K.RESULT_FLASH_SEC)
        k.step(self.clock.now)          # expired: render only
        self.assertEqual([], ticks)
        self.assertIsNone(k.flash_result)
        k.step(self.clock.now)
        self.assertEqual(1, len(ticks))

    def test_period_and_first_pass(self):
        ticks = []
        k = self.kernel(
            self.page_plugin(
                tick=lambda ctx, now: ticks.append(now), period=2.0
            )
        )
        k.goto("pg")
        k.step(self.clock.now)
        self.clock.advance(1)
        k.step(self.clock.now)
        self.clock.advance(1)
        k.step(self.clock.now)
        self.assertEqual(2, len(ticks))

    def test_tick_error_goes_home(self):
        k = self.kernel(self.page_plugin(tick=lambda c, n: 1 / 0))
        k.goto("pg")
        k.step(self.clock.now)
        self.assertEqual("idle", k.page_id)

    def test_home_ticks_and_refresh(self):
        renders = []
        asks = {"n": 0}

        def home_tick(ctx, now):
            asks["n"] += 1
            return False

        p = loaded("h", Plugin(api=PLUGIN_API, home_tick=home_tick))
        k = self.kernel(p)
        with mock.patch.object(k, "render", lambda: renders.append(1)):
            k.step(self.clock.now)       # first pass: refresh renders
            self.clock.advance(0.3)
            k.step(self.clock.now)       # tick ran, no render asked
        self.assertEqual(2, asks["n"])
        self.assertEqual(1, len(renders))

    def test_loop_clears_schedules(self):
        ticks = []
        k = self.kernel(
            self.page_plugin(
                tick=lambda ctx, now: ticks.append(now), period=2.0
            )
        )
        k.goto("pg")
        self.deck.polls = 1
        k.loop()
        self.deck.polls = 1
        k.loop()
        self.assertEqual(2, len(ticks))


class PollTest(KernelCase):
    """Polls: active under the lock, read without it, store under it."""

    def poll_plugin(self, read, period=0.0, active=None, store=None,
                    pages=()):
        self.seen = []

        def store_(ctx, data):
            self.seen.append(("store", data, self.k.lock.locked()))
            ctx.state().value = data
            return False

        def active_(ctx):
            self.seen.append(("active", self.k.lock.locked()))
            return True

        poll = Poll(period, active or active_, read, store or store_)
        return loaded("p", Plugin(
            api=PLUGIN_API, pages=list(pages), polls=[poll]
        ))

    def test_inactive_poll_is_not_read(self):
        reads = []
        self.k = self.kernel(self.poll_plugin(
            lambda: reads.append(1), active=lambda ctx: False
        ))
        for _ in range(3):
            self.k.step(self.clock.now)
            self.clock.advance(1)
        self.assertEqual([], reads)

    def test_read_once_per_period(self):
        reads = []

        def read():
            reads.append(self.clock.now)
            return len(reads)

        self.k = self.kernel(self.poll_plugin(read, period=2.0))
        for _ in range(5):
            self.k.step(self.clock.now)
            self.clock.advance(1)
        self.assertEqual(3, len(reads))
        self.assertEqual(3, self.k.state("p").value)

    def test_read_runs_outside_the_lock(self):
        held = []
        self.k = self.kernel(self.poll_plugin(
            lambda: held.append(self.k.lock.locked()) or "d"
        ))
        self.k.step(self.clock.now)
        self.assertEqual([False], held)
        self.assertEqual(
            [("active", True), ("store", "d", True)], self.seen
        )

    def test_store_true_on_home_renders_once(self):
        renders = []
        changed = {"v": True}
        self.k = self.kernel(self.poll_plugin(
            lambda: 1, store=lambda ctx, data: changed["v"]
        ))
        with mock.patch.object(
            self.k, "render", lambda: renders.append(1)
        ):
            self.k.step(self.clock.now)    # store and refresh: one
            self.assertEqual(1, len(renders))
            self.clock.advance(0.3)
            self.k.step(self.clock.now)    # store asks: one
            self.assertEqual(2, len(renders))
            changed["v"] = False
            self.clock.advance(0.3)
            self.k.step(self.clock.now)    # nothing asks
        self.assertEqual(2, len(renders))

    def test_failing_read_keeps_cache_and_logs_once(self):
        values = iter([7])

        def read():
            return next(values)            # StopIteration after one

        self.k = self.kernel(self.poll_plugin(read))
        for _ in range(4):
            self.k.step(self.clock.now)
            self.clock.advance(1)
        self.assertEqual(7, self.k.state("p").value)
        self.assertEqual(
            1, self.journal.getvalue().count("p: poll 0 read failed")
        )

    def test_flash_blocks_every_poll(self):
        reads = []
        self.k = self.kernel(self.poll_plugin(lambda: reads.append(1)))
        self.k.set_flash(True)
        self.k.step(self.clock.now)        # flash live: nothing
        self.clock.advance(K.RESULT_FLASH_SEC)
        self.k.step(self.clock.now)        # expired: render only
        self.assertEqual([], reads)
        self.assertEqual([], self.seen)
        self.k.step(self.clock.now)
        self.assertEqual([1], reads)

    def test_flash_during_read_skips_the_store(self):
        def read():
            self.k.set_flash(True)     # a press flashed meanwhile
            return 1

        self.k = self.kernel(self.poll_plugin(read))
        self.k.step(self.clock.now)
        self.assertEqual([], [e for e in self.seen if e[0] == "store"])

    def test_stop_during_read_skips_the_store(self):
        def read():
            self.k.running = False     # shutdown meanwhile
            return 1

        self.k = self.kernel(self.poll_plugin(read))
        self.k.step(self.clock.now)
        self.assertEqual([], [e for e in self.seen if e[0] == "store"])

    def test_store_true_on_a_page_renders_before_the_tick(self):
        order = []

        def render_(ctx):
            order.append("render")

        page = Page(
            "pg", None, render_, print,
            tick=lambda ctx, now: order.append("tick"),
        )
        self.k = self.kernel(self.poll_plugin(
            lambda: 1, store=lambda ctx, data: True, pages=[page]
        ))
        self.k.goto("pg")
        order.clear()
        self.k.step(self.clock.now)
        self.assertEqual(["render", "tick"], order)

    def test_each_poll_keeps_its_own_period(self):
        reads = []
        polls = [
            Poll(period, lambda ctx: True,
                 lambda period=period: reads.append(period),
                 lambda ctx, data: False)
            for period in (1.0, 3.0)
        ]
        self.k = self.kernel(loaded("p", Plugin(
            api=PLUGIN_API, polls=polls
        )))
        for _ in range(6):
            self.k.step(self.clock.now)
            self.clock.advance(1)
        self.assertEqual(6, reads.count(1.0))
        self.assertEqual(2, reads.count(3.0))

    def test_failing_active_or_store_is_isolated(self):
        """A raising active() leaves its poll unread, a raising store()
        asks no render; both are journaled once and the other polls and
        the page tick run on."""
        def boom(*args):
            raise ValueError("bad")

        reads, stored, renders, ticks = [], [], [], []
        polls = [
            Poll(0.0, boom, lambda: reads.append(0), lambda c, d: True),
            Poll(0.0, lambda ctx: True, lambda: 1, boom),
            Poll(0.0, lambda ctx: True, lambda: 2,
                 lambda ctx, data: stored.append(data) or False),
        ]
        page = Page(
            "pg", None, lambda ctx: renders.append(1), print,
            tick=lambda ctx, now: ticks.append(now),
        )
        self.k = self.kernel(loaded("p", Plugin(
            api=PLUGIN_API, pages=[page], polls=polls
        )))
        self.k.goto("pg")
        renders.clear()
        for _ in range(3):
            self.k.step(self.clock.now)
            self.clock.advance(1)
        self.assertEqual([], reads)
        self.assertEqual([2, 2, 2], stored)
        self.assertEqual(3, len(ticks))
        self.assertEqual([], renders)
        journal = self.journal.getvalue()
        self.assertEqual(1, journal.count("p: poll 0 active failed"))
        self.assertEqual(1, journal.count("p: poll 1 store failed"))


class RecheckDbusTest(KernelCase):
    def test_rechecks_while_missing_then_stops(self):
        dbus = FakeDbus(ok=False)
        k = self.kernel(dbus=dbus)
        self.assertEqual(1, dbus.checks)
        self.assertFalse(k.recheck_dbus(self.clock.now + 1))
        self.assertEqual(1, dbus.checks)
        dbus.ok = True
        self.assertTrue(k.recheck_dbus(self.clock.now + K.DBUS_RECHECK_SEC))
        self.assertFalse(k.recheck_dbus(self.clock.now + 100))
        self.assertEqual(2, dbus.checks)

    def test_recheck_runs_without_the_lock(self):
        """gdbus may wait for its timeout: a recheck under the lock
        would hold every key press as long."""
        dbus = FakeDbus(ok=False)
        k = self.kernel(dbus=dbus)
        held = []
        dbus.available = lambda: held.append(k.lock.locked()) or True
        self.clock.advance(K.DBUS_RECHECK_SEC)
        k.step(self.clock.now)
        self.assertEqual([False], held)
        self.assertTrue(k.dbus_ok)


class LeftoverTest(KernelCase):
    def test_system_exit_in_handle_is_isolated(self):
        def bye(ctx, key):
            raise SystemExit(3)

        k = self.kernel(self.page_plugin(handle=bye))
        k.goto("pg")
        k.handle_key(1, True)
        self.assertEqual("idle", k.page_id)
        self.assertIn("handle failed", self.journal.getvalue())

    def test_keyboard_interrupt_still_propagates(self):
        def stop(ctx, key):
            raise KeyboardInterrupt

        k = self.kernel(self.page_plugin(handle=stop))
        k.goto("pg")
        with self.assertRaises(KeyboardInterrupt):
            k.handle_key(1, True)

    def test_a_sigterm_during_a_plugin_call_propagates(self):
        """The SystemExit of exit_on_sigterm is the service's stop, not a
        plugin's error: swallowed, it would leave the service running
        with SIGTERM already ignored."""
        import deck_lock

        def probe(ctx):
            raise deck_lock.SigtermExit(143)

        plugin = loaded("p", Plugin(api=PLUGIN_API, setup=probe))
        with self.assertRaises(SystemExit) as caught:
            self.kernel(plugin)
        self.assertEqual(143, caught.exception.code)
        self.assertNotIn("setup failed", self.journal.getvalue())

    def test_nothing_painted_after_running_is_false(self):
        k = self.kernel(self.page_plugin())
        k.goto("pg")
        self.deck.screen.clear()
        k.running = False
        k.render()
        self.assertEqual({}, self.deck.screen)

    def test_paint_draws_nothing_after_running_is_false(self):
        k = self.kernel(self.page_plugin())
        self.deck.screen.clear()
        k.running = False
        k.paint(3, KeyFace(colors.OK, "x"))
        self.assertEqual({}, self.deck.screen)


class JobTest(KernelCase):
    def setUp(self):
        super().setUp()
        patch = mock.patch("threading.Thread", S.FakeThread)
        patch.start()
        self.addCleanup(patch.stop)
        S.FakeThread.queue.clear()

    def run_jobs(self):
        while S.FakeThread.queue:
            job = S.FakeThread.queue.pop(0)
            job.target(*job.args, **job.kwargs)

    def slow_plugin(self, work, then=None, calls=None):
        def handle(ctx, key):
            (calls if calls is not None else []).append(key)
            ctx.run_blocking(work, then)

        return self.page_plugin(handle=handle)

    def test_busy_mark_then_result_on_next_pass(self):
        k = self.kernel(self.slow_plugin(lambda: True))
        k.goto("pg")
        k.handle_key(3, True)
        self.assertEqual("…", self.deck.screen[3][1])
        self.assertIn("p", k.busy)
        self.run_jobs()
        k.step(self.clock.now)
        self.assertNotIn("p", k.busy)
        self.assertEqual("ok", k.flash_result)

    def test_error_reaches_then(self):
        seen = []
        k = self.kernel(self.slow_plugin(
            lambda: 1 / 0, lambda ctx, r, e: seen.append(type(e))))
        k.goto("pg")
        k.handle_key(3, True)
        self.run_jobs()
        k.step(self.clock.now)
        self.assertEqual([ZeroDivisionError], seen)

    def test_job_press_after_an_expired_flash_clears_it(self):
        # The flash is over but still painted: the press repaints the
        # page under the "…", and the next pass hands the result back
        # instead of spending itself on clearing the flash.
        seen = []
        k = self.kernel(self.slow_plugin(
            lambda: True, lambda ctx, r, e: seen.append(r)))
        k.goto("pg")
        k.set_flash(True)
        k.render()
        self.assertEqual("OK!", self.deck.screen[0][1])
        self.clock.advance(K.RESULT_FLASH_SEC + 0.1)
        k.handle_key(3, True)
        self.assertIsNone(k.flash_result)
        self.assertEqual("X", self.deck.screen[0][1])
        self.assertEqual("\u2026", self.deck.screen[3][1])
        self.run_jobs()
        k.step(self.clock.now)
        self.assertEqual([True], seen)

    def fail_once(self, k, exc_or_none):
        """Run one job of plugin p that raises `exc_or_none` (or returns
        True when None), and hand it back."""
        def work():
            if exc_or_none is not None:
                raise exc_or_none
            return True

        k.state("p").work = work
        k.handle_key(3, True)
        self.run_jobs()
        k.step(self.clock.now)
        self.clock.advance(1)
        k.step(self.clock.now)

    def job_failures(self):
        return self.journal.getvalue().count("p: job failed: ")

    def test_failed_job_is_journaled_with_its_traceback_once(self):
        seen = []
        k = self.kernel(self.slow_plugin(
            lambda: k.state("p").work(),
            lambda ctx, r, e: seen.append(e)))
        k.goto("pg")
        self.fail_once(k, OSError(28, "No space left on device"))
        journal = self.journal.getvalue()
        self.assertIn(
            "[erplibre-home] p: job failed: OSError(28, "
            "'No space left on device')", journal)
        self.assertIn("Traceback (most recent call last)", journal)
        self.assertIn("raise exc_or_none", journal)
        self.assertEqual(OSError, type(seen[0]))
        self.fail_once(k, OSError(28, "No space left on device"))
        self.assertEqual(1, self.job_failures())
        self.assertEqual(2, len(seen))

    def test_job_success_rearms_the_failure_journal(self):
        k = self.kernel(self.slow_plugin(lambda: k.state("p").work()))
        k.goto("pg")
        self.fail_once(k, OSError("disk"))
        self.fail_once(k, None)
        self.fail_once(k, OSError("disk"))
        self.assertEqual(2, self.job_failures())

    def test_second_press_on_busy_plugin_flashes_err(self):
        calls = []
        k = self.kernel(self.slow_plugin(lambda: True, calls=calls))
        k.goto("pg")
        k.handle_key(3, True)
        self.clock.advance(1)
        k.handle_key(4, True)
        self.assertEqual([3], calls)          # plugin not called again
        self.assertEqual("err", k.flash_result)
        self.assertEqual(1, len(S.FakeThread.queue))

    def test_busy_mark_only_on_its_page(self):
        k = self.kernel(self.slow_plugin(lambda: True))
        k.goto("pg")
        k.handle_key(3, True)
        k.goto("idle")
        self.assertNotEqual(
            "…", (self.deck.screen.get(3) or [0, ""])[1]
        )

    def test_results_dropped_after_stop(self):
        seen = []
        k = self.kernel(self.slow_plugin(
            lambda: True, lambda ctx, r, e: seen.append(r)))
        k.goto("pg")
        k.handle_key(3, True)
        k.running = False
        self.run_jobs()
        k.drain_jobs()
        self.assertEqual([], seen)

    def test_page_tick_skipped_while_busy(self):
        ticks = []
        k = self.kernel(self.page_plugin(
            handle=lambda ctx, key: ctx.run_blocking(lambda: True),
            tick=lambda ctx, now: ticks.append(now)))
        k.goto("pg")
        k.handle_key(3, True)
        self.clock.advance(1)
        k.step(self.clock.now)
        self.assertEqual([], ticks)

    def test_falsy_result_without_then_flashes_err(self):
        k = self.kernel(self.slow_plugin(lambda: False))
        k.goto("pg")
        k.handle_key(3, True)
        self.run_jobs()
        k.step(self.clock.now)
        self.assertEqual("err", k.flash_result)

    def test_then_that_raises_flashes_err(self):
        def then(ctx, result, error):
            raise ValueError("then")

        k = self.kernel(self.slow_plugin(lambda: True, then))
        k.goto("pg")
        k.handle_key(3, True)
        self.run_jobs()
        k.step(self.clock.now)
        self.assertEqual("err", k.flash_result)
        self.assertNotIn("p", k.busy)
        self.assertIn("p: job result failed", self.journal.getvalue())

    def test_render_repaints_the_busy_mark(self):
        k = self.kernel(self.slow_plugin(lambda: True))
        k.goto("pg")
        k.handle_key(3, True)
        k.render()
        self.assertEqual("…", self.deck.screen[3][1])
        self.assertEqual(
            "%02x%02x%02x" % colors.BUSY, self.deck.screen[3][0]
        )

    def test_key_zero_leaves_a_busy_page_without_the_plugin(self):
        calls = []
        k = self.kernel(self.slow_plugin(lambda: True, calls=calls))
        k.goto("pg")
        k.handle_key(3, True)
        self.clock.advance(1)
        k.handle_key(0, True)
        self.assertEqual("idle", k.page_id)
        self.assertIsNone(k.flash_result)
        self.assertEqual([3], calls)

    def test_other_key_of_a_busy_page_flashes_err(self):
        calls = []
        k = self.kernel(self.slow_plugin(lambda: True, calls=calls))
        k.goto("pg")
        k.handle_key(3, True)
        self.clock.advance(1)
        k.handle_key(3, True)
        self.assertEqual("pg", k.page_id)
        self.assertEqual("err", k.flash_result)
        self.assertEqual([3], calls)

    def test_thread_that_fails_to_start_leaves_plugin_free(self):
        class NoThread(S.FakeThread):
            def start(self):
                raise RuntimeError("can't start new thread")

        k = self.kernel(self.slow_plugin(lambda: True))
        k.goto("pg")
        with mock.patch("threading.Thread", NoThread):
            k.handle_key(3, True)
        self.assertNotIn("p", k.busy)
        self.assertNotEqual("\u2026", self.deck.screen[3][1])
        self.assertIn("p: page pg handle failed", self.journal.getvalue())

    def test_base_exception_in_work_reaches_then(self):
        class Abort(BaseException):
            pass

        def work():
            raise Abort()

        seen = []
        k = self.kernel(self.slow_plugin(
            work, lambda ctx, r, e: seen.append(type(e))))
        k.goto("pg")
        k.handle_key(3, True)
        self.run_jobs()
        k.step(self.clock.now)
        self.assertEqual([Abort], seen)
        self.assertNotIn("p", k.busy)

    def home_plugin(self, pid, tick=None, calls=None):
        def press(ctx):
            calls.append(pid)
            ctx.run_blocking(lambda: True)

        return loaded(pid, Plugin(
            api=PLUGIN_API,
            home_button=HomeButton(
                1, lambda ctx: KeyFace((1, 1, 1), pid), press
            ),
            home_tick=tick,
        ))

    def test_home_press_on_busy_plugin_flashes_err(self):
        calls = []
        k = self.kernel(self.home_plugin("h", calls=calls))
        key = k.home.home_keys["h"]
        k.handle_key(key, True)
        self.clock.advance(1)
        k.handle_key(key, True)
        self.assertEqual(["h"], calls)
        self.assertEqual("err", k.flash_result)

    def test_home_tick_skipped_while_busy(self):
        ticks = []
        k = self.kernel(self.home_plugin(
            "h", tick=lambda ctx, now: ticks.append(now), calls=[]))
        k.handle_key(k.home.home_keys["h"], True)
        self.clock.advance(1)
        k.step(self.clock.now)
        self.assertEqual([], ticks)
        self.run_jobs()
        k.step(self.clock.now)          # drained: OK flash ends the pass
        self.clock.advance(K.RESULT_FLASH_SEC)
        k.step(self.clock.now)          # flash expired: render only
        k.step(self.clock.now)
        self.assertEqual(1, len(ticks))

    def test_busy_plugin_poll_is_skipped(self):
        reads, actives = [], []
        poll = Poll(
            0.0, lambda ctx: actives.append(1) or True,
            lambda: reads.append(1), lambda ctx, data: False,
        )
        k = self.kernel(loaded("p", Plugin(
            api=PLUGIN_API,
            pages=[Page(
                "pg", None, print,
                lambda ctx, key: ctx.run_blocking(lambda: True),
            )],
            polls=[poll],
        )))
        k.goto("pg")
        k.handle_key(3, True)
        self.clock.advance(1)
        k.step(self.clock.now)
        self.assertEqual(([], []), (reads, actives))
        self.run_jobs()
        k.step(self.clock.now)          # drained: OK flash ends the pass
        self.clock.advance(K.RESULT_FLASH_SEC)
        k.step(self.clock.now)          # flash expired: render only
        k.step(self.clock.now)
        self.assertEqual([1], reads)

    def test_the_worker_is_a_daemon_never_joined(self):
        """A job may wait minutes on a dialog: a joined or non-daemon
        worker would hold the service's stop as long."""
        k = self.kernel(self.slow_plugin(lambda: True))
        k.goto("pg")
        k.handle_key(3, True)
        worker = S.FakeThread.queue[0]
        self.run_jobs()
        k.step(self.clock.now)
        k.running = False
        k.shutdown()
        self.assertIs(True, worker.daemon)
        self.assertFalse(worker.joined)

    def test_then_runs_under_the_lock_and_work_without_it(self):
        """The press arrives through on_key, which holds the lock:
        run_blocking taking it again would deadlock the deck."""
        held = []
        k = self.kernel(self.slow_plugin(
            lambda: held.append(("work", k.lock.locked())) or True,
            lambda ctx, r, e: held.append(("then", k.lock.locked())),
        ))
        k.lock = StrictLock()
        k.goto("pg")
        k.on_key(self.deck, 3, True)
        self.assertIn("p", k.busy)
        self.assertNotIn("failed", self.journal.getvalue())
        self.run_jobs()
        k.step(self.clock.now)
        self.assertEqual([("work", False), ("then", True)], held)

    def test_raising_work_without_then_flashes_err(self):
        k = self.kernel(self.slow_plugin(lambda: 1 / 0))
        k.goto("pg")
        k.handle_key(3, True)
        self.run_jobs()
        k.step(self.clock.now)
        self.assertEqual("err", k.flash_result)

    def test_run_blocking_says_whether_the_job_started(self):
        returns = []

        def handle(ctx, key):
            returns.append(ctx.run_blocking(lambda: True))
            returns.append(ctx.run_blocking(lambda: True))

        k = self.kernel(self.page_plugin(handle=handle))
        k.goto("pg")
        k.handle_key(3, True)
        self.assertEqual([True, False], returns)
        self.assertEqual("err", k.flash_result)
        self.assertEqual(1, len(S.FakeThread.queue))
        self.assertIn("p", k.busy)

    def test_busy_plugin_fixture_and_tile_flash_err(self):
        calls = []

        def press(ctx):
            calls.append("button")
            ctx.run_blocking(lambda: True)

        k = self.kernel(loaded("h", Plugin(
            api=PLUGIN_API,
            home_button=HomeButton(
                1, lambda ctx: KeyFace((1, 1, 1), "h"), press
            ),
            fixtures=[Fixture(
                1, lambda geo, hk: [14],
                lambda ctx, key, i: KeyFace((1, 1, 1), "f"),
                lambda ctx, key, i: calls.append("fixture"),
            )],
            tiles=[TileProvider(
                1, lambda ctx: ["t"],
                lambda ctx, item: KeyFace((1, 1, 1), item),
                lambda ctx, item: calls.append("tile"),
            )],
        )))
        k.render()
        tile = k.home.pool[0]
        k.handle_key(k.home.home_keys["h"], True)
        for key in (14, tile):
            self.clock.advance(K.RESULT_FLASH_SEC)
            k.handle_key(key, True)
            self.assertEqual("err", k.flash_result, key)
        self.assertEqual(["button"], calls)

    def test_other_plugins_work_while_one_is_busy(self):
        calls = []
        k = self.kernel(
            self.home_plugin("h", calls=calls),
            self.home_plugin("o", calls=calls),
            self.page_plugin(),
        )
        k.handle_key(k.home.home_keys["h"], True)
        self.clock.advance(1)
        k.handle_key(k.home.home_keys["o"], True)
        self.assertEqual(["h", "o"], calls)
        self.assertEqual({"h", "o"}, set(k.busy))
        k.goto("pg")
        k.handle_key(3, True)
        self.assertIn(("handle", 3), self.calls)
        self.assertIsNone(k.flash_result)


class ContextTest(KernelCase):
    """What a plugin's Context gives it: its own state, the journal, the
    flash and the kernel lock."""

    def test_each_plugin_has_its_own_state_namespace(self):
        k = self.kernel(
            self.page_plugin("a", "pa"), self.page_plugin("b", "pb")
        )
        k.ctx("a").state().value = 1
        self.assertFalse(hasattr(k.ctx("b").state(), "value"))
        self.assertIsNot(k.ctx("a").state(), k.ctx("b").state())
        self.assertIs(k.ctx("b").state(), k.ctx("a").state("b"))

    def test_log_and_flash_reason_are_one_line_under_the_plugin_id(self):
        k = self.kernel(self.page_plugin())
        k.ctx("p").log("disk full")
        k.ctx("p").flash(False, "no window")
        self.assertEqual(
            "[erplibre-home] p: disk full\n[erplibre-home] p: no window\n",
            self.journal.getvalue(),
        )

    def test_flash_records_without_rendering(self):
        """The plugin renders or leaves its page right after: a flash
        that rendered would draw the deck twice."""
        k = self.kernel(self.page_plugin())
        k.goto("pg")
        self.deck.screen.clear()
        k.ctx("p").flash(False)
        self.assertEqual({}, self.deck.screen)
        self.assertEqual("err", k.flash_result)

    def test_locked_is_the_kernel_lock(self):
        """A thread the plugin starts takes ctx.locked() before touching
        its state: any other lock lets it run beside a key press."""
        k = self.kernel(self.page_plugin())
        with k.ctx("p").locked():
            self.assertTrue(k.lock.locked())
        self.assertFalse(k.lock.locked())


class LockHeldTest(KernelCase):
    """The key callback and the loop hold the kernel lock across every
    plugin call they make; only Poll.read and the D-Bus recheck run
    without it."""

    CALLS = (
        "page render",
        "page handle",
        "page tick",
        "home face",
        "home press",
        "home tick",
        "fixture face",
        "fixture press",
        "tile items",
        "tile face",
        "tile press",
        "poll active",
        "poll store",
    )

    def test_every_plugin_callback_runs_with_the_lock_held(self):
        held = {}

        def probe(name, value=None):
            def call(*args):
                held.setdefault(name, []).append(self.k.lock.locked())
                return value

            return call

        def press(ctx):
            probe("home press")(ctx)
            ctx.goto("pg")

        face = KeyFace((1, 1, 1), "x")
        page = Page(
            "pg",
            None,
            probe("page render"),
            probe("page handle"),
            tick=probe("page tick"),
        )
        fixture = Fixture(
            1,
            lambda geo, hk: [13],
            probe("fixture face", face),
            probe("fixture press"),
        )
        tiles = TileProvider(
            1,
            probe("tile items", ["t"]),
            probe("tile face", face),
            probe("tile press"),
        )
        poll = Poll(
            0.0, probe("poll active", True), lambda: 1, probe("poll store")
        )
        self.k = self.kernel(
            loaded(
                "p",
                Plugin(
                    api=PLUGIN_API,
                    pages=[page],
                    home_button=HomeButton(1, probe("home face", face), press),
                    home_tick=probe("home tick"),
                    fixtures=[fixture],
                    tiles=[tiles],
                    polls=[poll],
                ),
            )
        )
        self.deck.polls = 1
        self.k.loop()  # home tick, then the refresh
        for key in (13, self.k.home.pool[0], 0, 3):
            self.k.on_key(self.deck, key, True)
        self.k.set_flash(True)
        self.clock.advance(K.RESULT_FLASH_SEC + 0.1)
        self.deck.polls = 2
        self.k.loop()  # the flash ends, the page tick
        self.assertEqual(2, len(held["page render"]))
        self.assertEqual(sorted(self.CALLS), sorted(held))
        for name, values in held.items():
            self.assertEqual([True] * len(values), values, name)
        self.assertFalse(self.k.lock.locked())

    def test_the_redraw_after_the_extension_appears_holds_the_lock(self):
        """recheck_dbus runs outside the lock; the home render it asks
        for, once the extension is found, runs under it again."""
        held = {}

        def probe(name, value):
            def call(*args):
                held.setdefault(name, []).append(k.lock.locked())
                return value

            return call

        face = KeyFace((1, 1, 1), "x")
        dbus = FakeDbus(ok=False)
        k = self.kernel(
            loaded(
                "p",
                Plugin(
                    api=PLUGIN_API,
                    home_button=HomeButton(
                        1, probe("home face", face), lambda ctx: None
                    ),
                    tiles=[
                        TileProvider(
                            1,
                            probe("tile items", ["t"]),
                            probe("tile face", face),
                            lambda ctx, item: None,
                        )
                    ],
                ),
            ),
            dbus=dbus,
        )
        # The home refresh is stamped one second before the recheck is
        # due, so the only render of the next pass is the recheck's.
        self.clock.advance(K.DBUS_RECHECK_SEC - 1)
        k.step(self.clock.now)
        held.clear()
        dbus.ok = True
        self.clock.advance(1)
        k.step(self.clock.now)
        self.assertTrue(k.dbus_ok)
        self.assertEqual(2, dbus.checks)
        self.assertEqual(
            ["home face", "tile face", "tile items"], sorted(held)
        )
        for name, values in held.items():
            self.assertEqual([True] * len(values), values, name)
        self.assertFalse(k.lock.locked())

    def test_the_key_callback_holds_the_lock_during_the_press(self):
        """The loop thread runs between two presses: a press dispatched
        without the lock would run beside a loop pass."""
        held = []
        k = self.kernel(
            self.page_plugin(
                handle=lambda ctx, key: held.append(k.lock.locked())
            )
        )
        k.goto("pg")
        k.on_key(self.deck, 3, True)
        self.assertEqual([True], held)
        self.assertFalse(k.lock.locked())


class IsolationDetailTest(KernelCase):
    def test_a_handle_failure_is_journaled_with_its_traceback(self):
        def handle(ctx, key):
            raise ValueError("bad")

        k = self.kernel(self.page_plugin(handle=handle))
        k.goto("pg")
        k.handle_key(4, True)
        journal = self.journal.getvalue()
        self.assertIn(
            "[erplibre-home] p: page pg handle failed: ValueError('bad')",
            journal,
        )
        self.assertIn("Traceback (most recent call last)", journal)
        self.assertIn('raise ValueError("bad")', journal)

    def test_a_render_that_raises_draws_the_home_screen(self):
        home = loaded(
            "h",
            Plugin(
                api=PLUGIN_API,
                home_button=HomeButton(
                    1, lambda ctx: KeyFace((1, 1, 1), "H"), lambda ctx: None
                ),
            ),
        )

        def render_(ctx):
            raise ValueError("bad")

        k = self.kernel(home, self.page_plugin(render=render_))
        self.deck.screen.clear()
        k.goto("pg")
        self.assertEqual("idle", k.page_id)
        self.assertIn(0, self.deck.screen, "home not drawn")
        self.assertEqual("H", self.deck.screen[0][1])
        self.assertIn("p: page pg render failed", self.journal.getvalue())

    def test_a_different_error_of_the_same_call_is_journaled_at_once(self):
        errors = iter(
            [
                ValueError("a"),
                ValueError("a"),
                ValueError("b"),
                TypeError("b"),
            ]
        )

        def handle(ctx, key):
            raise next(errors)

        k = self.kernel(self.page_plugin(handle=handle))
        for _ in range(4):
            k.goto("pg")
            self.clock.advance(1)
            k.handle_key(4, True)
        lines = [
            ln
            for ln in self.journal.getvalue().splitlines()
            if "page pg handle failed" in ln
        ]
        self.assertEqual(
            ["ValueError('a')", "ValueError('b')", "TypeError('b')"],
            [ln.split("failed: ")[1] for ln in lines],
        )


class HomeStepTest(KernelCase):
    def test_home_ticks_asking_for_a_render_get_one_per_pass(self):
        ticks, renders = [], []

        def tick(ctx, now):
            ticks.append(now)
            return True

        k = self.kernel(
            loaded("a", Plugin(api=PLUGIN_API, home_tick=tick)),
            loaded("b", Plugin(api=PLUGIN_API, home_tick=tick)),
        )
        with mock.patch.object(k, "render", lambda: renders.append(1)):
            for _ in range(3):
                k.step(self.clock.now)
                self.clock.advance(0.3)
        self.assertEqual(6, len(ticks))
        self.assertEqual(3, len(renders))

    def test_a_raising_home_tick_is_journaled_once_and_the_deck_goes_on(
        self,
    ):
        ran = []

        def boom(ctx, now):
            raise ValueError("bad")

        k = self.kernel(
            loaded("a", Plugin(api=PLUGIN_API, home_tick=boom)),
            loaded(
                "b",
                Plugin(
                    api=PLUGIN_API, home_tick=lambda ctx, now: ran.append(now)
                ),
            ),
        )
        self.deck.polls = 3
        k.loop()
        self.assertEqual(3, len(ran))
        self.assertTrue(k.running)
        self.assertEqual("idle", k.page_id)
        self.assertEqual(
            1, self.journal.getvalue().count("a: home tick failed")
        )

    def test_the_home_screen_redraws_every_two_seconds(self):
        renders = []
        k = self.kernel()
        start = self.clock.now
        with mock.patch.object(
            k, "render", lambda: renders.append(self.clock.now - start)
        ):
            for offset in (0.0, 1.95, 2.05, 4.0, 4.1):
                self.clock.now = start + offset
                k.step(self.clock.now)
        self.assertEqual([0.0, 2.05, 4.1], [round(t, 2) for t in renders])


class FlashDurationTest(KernelCase):
    def test_the_flash_lasts_half_a_second(self):
        k = self.kernel(self.page_plugin())
        k.goto("pg")
        start = self.clock.now
        k.set_flash(True)
        self.clock.now = start + 0.49
        k.handle_key(1, True)
        self.clock.now = start + 0.51
        k.handle_key(2, True)
        self.assertEqual(
            [("handle", 2)], [c for c in self.calls if c[0] == "handle"]
        )


if __name__ == "__main__":
    unittest.main()
