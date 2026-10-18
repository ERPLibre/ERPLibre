#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""The deck kernel: dispatch, flash, ticks, error isolation."""

import contextlib
import io
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import streamdeck_stubs as S  # noqa: E402

S.install()
from erplibre_streamdeck import kernel as K  # noqa: E402
from erplibre_streamdeck.plugin import (  # noqa: E402
    KeyFace,
    LoadedPlugin,
    Page,
    Plugin,
    PLUGIN_API,
    TileProvider,
)
from erplibre_streamdeck.ui import colors, render  # noqa: E402

# The real painter: KernelCase replaces it with a recorder, which takes
# any text; the real one calls len() on it.
REAL_SET_KEY = render.set_key


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


if __name__ == "__main__":
    unittest.main()
