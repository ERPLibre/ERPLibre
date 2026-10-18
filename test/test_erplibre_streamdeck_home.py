#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Home screen allocation, dashboard, and the taps that follow it."""

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
from erplibre_streamdeck import home  # noqa: E402
from erplibre_streamdeck import kernel as K  # noqa: E402
from erplibre_streamdeck.plugin import (  # noqa: E402
    Fixture,
    Geometry,
    HomeButton,
    KeyFace,
    LoadedPlugin,
    Plugin,
    PLUGIN_API,
    TileProvider,
)
from erplibre_streamdeck.ui import render  # noqa: E402

# The repository's home buttons, by order, as the single file lays them.
ORDERS = {
    "tiling": 10, "timers": 20, "dev_reload": 30, "sound": 40,
    "layouts": 50, "a11y": 60, "bluetooth": 70, "translate": 80,
    "todo_terminals": 90,
}


def face(label):
    return lambda ctx: KeyFace((1, 1, 1), label)


def plugins(off=()):
    out = []
    for pid, order in ORDERS.items():
        if pid in off:
            continue
        fixtures = []
        if pid == "sound":
            fixtures.append(Fixture(
                10,
                lambda geo, hk: (
                    [(geo.rows - 1) * geo.cols] if geo.rows >= 2 else []
                ),
                lambda ctx, key, i: KeyFace((2, 2, 2), "MIC"),
                lambda ctx, key, i: None,
            ))
        if pid == "layouts":
            def place(geo, hk):
                lk = hk.get("layouts", -1)
                if lk < 0 or geo.rows < 2 or lk + 3 > geo.cols:
                    return []
                base = (geo.rows - 1) * geo.cols + lk
                return [base + i for i in range(3)]
            fixtures.append(Fixture(
                20, place, lambda ctx, key, i: None, lambda c, k, i: None,
            ))
        button = HomeButton(order, face(pid), lambda ctx: None)
        out.append(LoadedPlugin(
            pid,
            Plugin(api=PLUGIN_API, home_button=button, fixtures=fixtures),
            "repo",
            Path(f"{pid}.py"),
        ))
    return out


class AllocationTest(unittest.TestCase):
    """The single file's facts (map-tests.md §4 "Geometry facts")."""

    EXPECT = {
        (3, 2): ({"tiling": 0, "timers": 1, "dev_reload": 2}, [3], [4, 5]),
        (4, 2): ({"sound": 3}, [4], [5, 6, 7]),
        (5, 3): (
            {"layouts": 4, "a11y": 5, "bluetooth": 6, "translate": 7,
             "todo_terminals": 8},
            [10],
            [9, 11, 12, 13, 14],
        ),
        (8, 4): (
            {"translate": 7, "todo_terminals": 8},
            [24, 28, 29, 30],
            list(range(9, 24)) + [25, 26, 27, 31],
        ),
    }

    def test_geometries(self):
        for (cols, rows), (keys, fixed, pool) in self.EXPECT.items():
            geo = Geometry(cols, rows, cols * rows)
            alloc = home.allocate(geo, plugins())
            for pid, key in keys.items():
                self.assertEqual(key, alloc.home_keys[pid], (cols, pid))
            self.assertEqual(fixed, sorted(alloc.fixtures), (cols, rows))
            self.assertEqual(pool, alloc.pool, (cols, rows))

    def test_tile_and_timer_never_share_a_key(self):
        for cols, rows in S.GEOMETRIES:
            geo = Geometry(cols, rows, cols * rows)
            hk = home.allocate(geo, plugins()).home_keys
            self.assertNotEqual(hk["tiling"], hk["timers"])

    def test_allocation_with_each_plugin_off(self):
        for off in ORDERS:
            for cols, rows in S.GEOMETRIES:
                geo = Geometry(cols, rows, cols * rows)
                alloc = home.allocate(geo, plugins(off=(off,)))
                used = [k for k in alloc.home_keys.values() if k >= 0]
                self.assertEqual(len(used), len(set(used)))
                self.assertEqual(
                    sorted(used)[: min(cols, len(used))],
                    list(range(min(cols, len(used)))),
                    (off, cols, rows),
                )
                taken = set(used) | set(alloc.fixtures)
                self.assertFalse(taken & set(alloc.pool))

    def test_layout_shortcuts_follow_layout_key(self):
        geo = Geometry(8, 4, 32)
        alloc = home.allocate(geo, plugins(off=("tiling", "sound")))
        self.assertEqual(2, alloc.home_keys["layouts"])
        self.assertEqual([26, 27, 28], sorted(alloc.fixtures))


class DashboardTest(unittest.TestCase):
    def setUp(self):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(
            mock.patch.object(render, "set_key", S.recorder())
        )
        stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
        self.deck = S.FakeDeck(5, 3)
        self.pressed = []
        self.items = {"a": ["a1", "a2"], "b": ["b1"]}

    def kernel(self, extra=()):
        tiles = []
        for order, pid in ((10, "a"), (20, "b")):
            tiles.append(LoadedPlugin(pid, Plugin(
                api=PLUGIN_API,
                tiles=[TileProvider(
                    order,
                    lambda ctx, pid=pid: list(self.items[pid]),
                    lambda ctx, item: KeyFace((3, 3, 3), item),
                    lambda ctx, item: self.pressed.append(item),
                )],
            ), "repo", Path(f"{pid}.py")))
        with mock.patch.object(K, "dbus_mod", mock.Mock(available=bool)):
            return K.Kernel(self.deck, plugins() + tiles + list(extra))

    def test_order_and_tap_reads_last_render(self):
        k = self.kernel()
        k.render()
        screen = self.deck.rendering()
        self.assertEqual(["a1", "a2", "b1"],
                         [screen[key][1] for key in (9, 11, 12)])
        self.items["a"].insert(0, "a0")  # appears after the render
        k.handle_key(9, True)
        self.assertEqual(["a1"], self.pressed)

    def test_items_error_leaves_keys_to_next_provider(self):
        def boom(ctx):
            raise OSError("state dir")

        bad = LoadedPlugin("z", Plugin(api=PLUGIN_API, tiles=[
            TileProvider(5, boom, None, None)]), "repo", Path("z.py"))
        k2 = self.kernel(extra=[bad])
        k2.render()
        screen = self.deck.rendering()
        self.assertEqual("a1", screen[9][1])

    def test_no_ext_on_key_zero_only_when_free(self):
        k = self.kernel()
        k.dbus_ok = False
        k.render()
        self.assertEqual("tiling", self.deck.rendering()[0][1])
        with mock.patch.object(K, "dbus_mod", mock.Mock(available=bool)):
            k2 = K.Kernel(self.deck, [])
        k2.dbus_ok = False
        k2.render()
        self.assertEqual("NO\nEXT", self.deck.rendering()[0][1])


if __name__ == "__main__":
    unittest.main()
