#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Home screen allocation, dashboard, and the taps that follow it."""

import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import streamdeck_stubs as S  # noqa: E402

S.install()
from erplibre_streamdeck import home  # noqa: E402
from erplibre_streamdeck import keymap  # noqa: E402
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

    def test_owner_of_button_fixture_tile_and_free_key(self):
        k = self.kernel()
        self.assertIsNone(k.home.owner(9))   # no tile before a render
        k.render()
        self.assertEqual("tiling", k.home.owner(0))
        self.assertEqual("sound", k.home.owner(10))
        self.assertEqual("a", k.home.owner(9))
        self.assertEqual("b", k.home.owner(12))
        self.assertIsNone(k.home.owner(13))

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


class IsolationTest(DashboardTest):
    def fixture_plugin(self, pid, place):
        return LoadedPlugin(pid, Plugin(api=PLUGIN_API, fixtures=[
            Fixture(5, place, lambda ctx, key, i: None,
                    lambda ctx, key, i: None)]), "repo", Path(f"{pid}.py"))

    def test_bad_place_is_skipped(self):
        def boom(geo, hk):
            raise ValueError("x")

        good = self.fixture_plugin("g", lambda geo, hk: [13])
        for bad_place in (boom, lambda geo, hk: None,
                          lambda geo, hk: ["a"]):
            bad = self.fixture_plugin("bad", bad_place)
            k = self.kernel(extra=[bad, good])
            self.assertIn(13, k.home.fixtures)
            self.assertEqual(
                ["g"], [v[0] for v in k.home.fixtures.values()
                        if v[0] in ("g", "bad")])

    def test_generator_raising_midway(self):
        def gen(ctx):
            yield "z1"
            raise OSError("mid")

        bad = LoadedPlugin("z", Plugin(api=PLUGIN_API, tiles=[
            TileProvider(5, gen, lambda c, i: None,
                         lambda c, i: None)]), "repo", Path("z.py"))
        k = self.kernel(extra=[bad])
        k.render()
        self.assertEqual("a1", self.deck.rendering()[9][1])
        self.assertFalse(
            [v for v in k.home.tile_map.values() if v[0] == "z"])

    def test_non_keyface_paints_empty(self):
        bad = LoadedPlugin("z", Plugin(api=PLUGIN_API, tiles=[
            TileProvider(5, lambda ctx: ["q"], lambda c, i: "oops",
                         lambda c, i: None)]), "repo", Path("z.py"))
        k = self.kernel(extra=[bad])
        k.render()
        self.assertEqual("", self.deck.rendering()[9][1])

    def test_raising_button_press_flashes_err(self):
        def boom(ctx):
            raise RuntimeError("press")

        bad = LoadedPlugin("z", Plugin(
            api=PLUGIN_API,
            home_button=HomeButton(1, face("z"), boom),
        ), "repo", Path("z.py"))
        k = self.kernel(extra=[bad])
        key = k.home.home_keys["z"]
        k.handle_key(key, True)
        self.assertEqual("err", k.flash_result)

    def test_face_failure_is_journaled_once_per_key(self):
        def face_(ctx, item):
            if item == "bad":
                raise RuntimeError("face")
            return KeyFace((3, 3, 3), item)

        z = LoadedPlugin("z", Plugin(api=PLUGIN_API, tiles=[
            TileProvider(5, lambda ctx: ["bad", "good"], face_,
                         lambda c, i: None)]), "repo", Path("z.py"))
        journal = io.StringIO()
        with contextlib.redirect_stderr(journal):
            k = self.kernel(extra=[z])
            for _ in range(3):
                k.render()
        lines = [
            ln for ln in journal.getvalue().splitlines()
            if "tile face" in ln and "failed" in ln
        ]
        self.assertEqual(1, len(lines), lines)

    def test_fixture_face_failure_is_journaled_once_per_key(self):
        """A fixture spans several keys: one that fails next to one that
        paints is written once, under the key that fails."""
        def face_(ctx, key, index):
            if index == 0:
                raise RuntimeError("face")
            return KeyFace((3, 3, 3), "ok")

        z = LoadedPlugin("z", Plugin(api=PLUGIN_API, fixtures=[
            Fixture(5, lambda geo, hk: [13, 14], face_,
                    lambda c, k, i: None)]), "repo", Path("z.py"))
        journal = io.StringIO()
        with contextlib.redirect_stderr(journal):
            k = self.kernel(extra=[z])
            for _ in range(3):
                k.render()
        lines = [
            ln for ln in journal.getvalue().splitlines()
            if "fixture face" in ln and "failed" in ln
        ]
        self.assertEqual(1, len(lines), lines)
        self.assertIn("z: fixture face 13 failed", lines[0])
        self.assertEqual("ok", self.deck.rendering()[14][1])


class FixtureOrderTest(unittest.TestCase):
    def test_a_key_already_taken_is_skipped_by_a_later_fixture(self):
        def fixture(pid, order, keys):
            return LoadedPlugin(
                pid,
                Plugin(
                    api=PLUGIN_API,
                    fixtures=[
                        Fixture(order, lambda geo, hk: keys, None, None)
                    ],
                ),
                "repo",
                Path(f"{pid}.py"),
            )

        button = LoadedPlugin(
            "btn",
            Plugin(
                api=PLUGIN_API,
                home_button=HomeButton(1, face("B"), lambda ctx: None),
            ),
            "repo",
            Path("btn.py"),
        )
        geo = Geometry(5, 3, 15)
        alloc = home.allocate(
            geo,
            [
                button,
                fixture("first", 1, [0, 13]),
                fixture("later", 2, [13, 14]),
            ],
        )
        self.assertEqual(0, alloc.home_keys["btn"])
        self.assertEqual(
            {13: "first", 14: "later"},
            {k: v[0] for k, v in alloc.fixtures.items()},
        )

    def test_the_mic_takes_order_10_and_the_layout_shortcuts_20(self):
        """A fixture of a user plugin claims the mic key and the first
        shortcut key: below 10 it takes both, between 10 and 20 the
        second only, above 20 neither."""
        from erplibre_streamdeck.plugins import layouts, sound

        repo = [
            LoadedPlugin(pid, module.PLUGIN, "repo", Path(f"{pid}.py"))
            for pid, module in (("layouts", layouts), ("sound", sound))
        ]
        geo = Geometry(8, 4, 32)
        mic, first_shortcut = 24, 25
        for order, owners in (
            (9, ("probe", "probe")),
            (11, ("sound", "probe")),
            (19, ("sound", "probe")),
            (21, ("sound", "layouts")),
        ):
            probe = LoadedPlugin(
                "probe",
                Plugin(
                    api=PLUGIN_API,
                    fixtures=[
                        Fixture(
                            order,
                            lambda geo, hk: [mic, first_shortcut],
                            None,
                            None,
                        )
                    ],
                ),
                "user",
                Path("probe.py"),
            )
            fixtures = home.allocate(geo, repo + [probe]).fixtures
            self.assertEqual(
                owners,
                (fixtures[mic][0], fixtures[first_shortcut][0]),
                order,
            )


def entry(key, action, icon=None, label=None):
    return keymap.Entry(key, action, icon, label)


class LayoutAllocationTest(unittest.TestCase):
    """allocate() with a keymap.json layout: it is the home screen."""

    def test_without_a_file_the_layout_is_unchanged(self):
        """No file: layout_for gives None, and every geometry of the
        single file's facts is laid out as before."""
        with tempfile.TemporaryDirectory() as tmp:
            data = keymap.load(Path(tmp) / "keymap.json")
        for (cols, rows), (keys, fixed, pool) in (
            AllocationTest.EXPECT.items()
        ):
            geo = Geometry(cols, rows, cols * rows)
            layout, problems = keymap.layout_for(
                data, "0084", geo, set(ORDERS), set()
            )
            self.assertEqual((None, []), (layout, problems))
            loaded = plugins()
            alloc = home.allocate(geo, loaded, layout=layout)
            before = home.allocate(geo, loaded)
            self.assertEqual(before, alloc, (cols, rows))
            for pid, key in keys.items():
                self.assertEqual(key, alloc.home_keys[pid], (cols, pid))
            self.assertEqual(fixed, sorted(alloc.fixtures), (cols, rows))
            self.assertEqual(pool, alloc.pool, (cols, rows))

    def test_named_plugins_take_their_keys(self):
        geo = Geometry(5, 3, 15)
        alloc = home.allocate(geo, plugins(), layout=[
            entry(14, "plugin:timers"), entry(7, "plugin:tiling"),
        ])
        self.assertEqual(14, alloc.home_keys["timers"])
        self.assertEqual(7, alloc.home_keys["tiling"])
        self.assertEqual("timers", alloc.buttons[14][0])
        self.assertEqual({7, 14}, set(alloc.buttons))

    def test_an_unnamed_plugin_gets_no_home_key(self):
        geo = Geometry(4, 2, 8)
        alloc = home.allocate(geo, plugins(), layout=[
            entry(0, "plugin:timers"),
        ])
        for pid in ORDERS:
            if pid != "timers":
                self.assertEqual(-1, alloc.home_keys[pid], pid)
        self.assertEqual({0: "timers"},
                         {k: v[0] for k, v in alloc.buttons.items()})

    def test_fixtures_skip_named_keys(self):
        """The mic fixture asks for the first key of the last row: named
        `empty` there, it gets no key; the layouts shortcuts follow the
        layouts key and skip a named one."""
        geo = Geometry(8, 4, 32)
        alloc = home.allocate(geo, plugins(), layout=[
            entry(24, "empty"),
            entry(1, "plugin:layouts"),
            entry(26, "tiles"),
        ])
        self.assertEqual(1, alloc.home_keys["layouts"])
        self.assertNotIn(24, alloc.fixtures)
        self.assertEqual({25: "layouts", 27: "layouts"},
                         {k: v[0] for k, v in alloc.fixtures.items()})

    def test_the_dashboard_takes_tiles_keys_first_then_free_keys(self):
        geo = Geometry(4, 2, 8)
        alloc = home.allocate(geo, plugins(off=("sound",)), layout=[
            entry(0, "plugin:timers"),
            entry(6, "tiles"),
            entry(3, "tiles"),
            entry(1, "empty"),
        ])
        self.assertEqual([3, 6, 2, 4, 5, 7], alloc.pool)

    def test_a_named_plugin_not_loaded_leaves_its_key_empty(self):
        """layout_for keeps the entry of a plugin whose setup is still
        to come; a plugin the kernel then refuses is not in allocate's
        list, and its key stays out of the dashboard and the fixtures."""
        geo = Geometry(4, 2, 8)
        alloc = home.allocate(geo, plugins(off=("timers",)), layout=[
            entry(5, "plugin:timers"),
        ])
        self.assertNotIn(5, alloc.buttons)
        self.assertNotIn(5, alloc.pool)
        self.assertNotIn(5, alloc.fixtures)
        self.assertNotIn("timers", alloc.home_keys)

    def test_the_mic_poll_runs_only_while_its_fixture_holds_a_key(self):
        """On a 4x2 deck the mic asks for key 4. A layout naming key 4
        leaves the fixture no key: its 2 s poll stays off. Without a
        layout, or one leaving key 4 free, it runs on the home screen."""
        from erplibre_streamdeck.plugins import sound

        mic_poll = sound.PLUGIN.polls[1]
        self.assertIs(sound._mic_shown, mic_poll.active)
        other = Plugin(api=PLUGIN_API, fixtures=[Fixture(
            30, lambda geo, hk: [5], lambda ctx, key, i: None,
            lambda ctx, key, i: None,
        )])
        loaded = [
            LoadedPlugin("sound", sound.PLUGIN, "repo", Path("sound.py")),
            LoadedPlugin("other", other, "user", Path("other.py")),
        ]
        for layout, shown in (
            (None, True),
            ([entry(0, "plugin:sound")], True),
            ([entry(4, "plugin:sound")], False),
            ([entry(4, "empty")], False),
        ):
            with mock.patch.object(
                K, "dbus_mod", mock.Mock(available=bool)
            ):
                k = K.Kernel(S.FakeDeck(4, 2), loaded, layout=layout)
            ctx = k.ctx("sound")
            self.assertEqual(shown, 4 in k.home.fixtures, layout)
            self.assertEqual(shown, mic_poll.active(ctx), layout)
            self.assertEqual([4] if shown else [], ctx.fixture_keys)
            k.goto("sound")
            self.assertFalse(mic_poll.active(ctx), layout)

    def test_icon_and_label_replace_the_home_face_only(self):
        with mock.patch.object(render, "set_key", S.recorder()):
            deck = S.FakeDeck(4, 2)
            pressed = []
            button = LoadedPlugin("timers", Plugin(
                api=PLUGIN_API,
                home_button=HomeButton(
                    1,
                    lambda ctx: KeyFace((9, 8, 7), "TIMERS", "tile"),
                    lambda ctx: pressed.append("timers"),
                ),
            ), "repo", Path("timers.py"))
            other = LoadedPlugin("tiling", Plugin(
                api=PLUGIN_API,
                home_button=HomeButton(
                    2,
                    lambda ctx: KeyFace((1, 2, 3), "TILE", "tile"),
                    lambda ctx: None,
                ),
            ), "repo", Path("tiling.py"))
            with mock.patch.object(
                K, "dbus_mod", mock.Mock(available=bool)
            ):
                k = K.Kernel(deck, [button, other], layout=[
                    entry(2, "plugin:timers", "timer", "Minuteries"),
                    entry(3, "plugin:tiling", None, "Fenêtres"),
                ])
            k.render()
            screen = deck.rendering()
            self.assertEqual(["090807", "Minuteries", "timer"], screen[2])
            self.assertEqual(["010203", "Fenêtres", "tile"], screen[3])
            k.handle_key(2, True)
            self.assertEqual(["timers"], pressed)


class FaceAndPressFailureTest(unittest.TestCase):
    """A face or a press that raises, on a button, a fixture or a tile."""

    def setUp(self):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch.object(render, "set_key", S.recorder()))
        self.journal = io.StringIO()
        stack.enter_context(contextlib.redirect_stderr(self.journal))
        self.deck = S.FakeDeck(5, 3)

    def plugin(self, fail):
        def check(value):
            if fail["on"]:
                raise RuntimeError("plugin")
            return value

        return LoadedPlugin(
            "z",
            Plugin(
                api=PLUGIN_API,
                home_button=HomeButton(
                    1,
                    lambda ctx: check(KeyFace((3, 3, 3), "b")),
                    lambda ctx: check(None),
                ),
                fixtures=[
                    Fixture(
                        1,
                        lambda geo, hk: [13],
                        lambda ctx, key, i: check(KeyFace((3, 3, 3), "f")),
                        lambda ctx, key, i: check(None),
                    )
                ],
                tiles=[
                    TileProvider(
                        1,
                        lambda ctx: ["t"],
                        lambda ctx, item: check(KeyFace((3, 3, 3), item)),
                        lambda ctx, item: check(None),
                    )
                ],
            ),
            "repo",
            Path("z.py"),
        )

    def kernel_of(self, fail):
        with mock.patch.object(K, "dbus_mod", mock.Mock(available=bool)):
            return K.Kernel(self.deck, [self.plugin(fail)])

    def test_a_raising_face_paints_its_key_empty(self):
        fail = {"on": False}
        k = self.kernel_of(fail)
        k.render()
        keys = {"b": 0, "f": 13, "t": k.home.pool[0]}
        screen = self.deck.rendering()
        self.assertEqual(list(keys), [screen[key][1] for key in keys.values()])
        fail["on"] = True
        k.render()
        screen = self.deck.rendering()
        empty = "%02x%02x%02x" % home.EMPTY.color
        for label, key in keys.items():
            self.assertEqual([empty, ""], screen[key][:2], label)

    def test_a_raising_fixture_or_tile_press_flashes_err(self):
        for what in ("fixture", "tile"):
            with self.subTest(what=what):
                fail = {"on": False}
                k = self.kernel_of(fail)
                k.render()
                fail["on"] = True
                key = 13 if what == "fixture" else k.home.pool[0]
                k.handle_key(key, True)
                self.assertEqual("err", k.flash_result)
                self.assertIn(
                    f"z: {what} press failed", self.journal.getvalue()
                )


if __name__ == "__main__":
    unittest.main()
