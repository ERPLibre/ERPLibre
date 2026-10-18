#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""The Claude and mpv session pages: they refresh when what they show
changes and go home when the session ends."""

import contextlib
import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import streamdeck_stubs as S  # noqa: E402

S.install()
from erplibre_streamdeck import kernel as K  # noqa: E402
from erplibre_streamdeck import paths  # noqa: E402
from erplibre_streamdeck.plugin import LoadedPlugin  # noqa: E402
from erplibre_streamdeck.plugins import claude_sessions  # noqa: E402
from erplibre_streamdeck.plugins import mpv_sessions  # noqa: E402
from erplibre_streamdeck.ui import render  # noqa: E402


class FakeDbus:
    @staticmethod
    def available():
        return True


class SessionPagesCase(unittest.TestCase):
    def setUp(self):
        S.wipe()
        self.clock = S.FakeClock()
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(
            mock.patch("time.monotonic", self.clock.monotonic)
        )
        stack.enter_context(
            mock.patch.object(render, "set_key", S.recorder())
        )
        stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
        self.deck = S.FakeDeck(5, 3)

    def kernel(self, module, settings=None):
        lp = LoadedPlugin("p", module.PLUGIN, "repo", Path("p.py"))
        with mock.patch.object(K, "dbus_mod", FakeDbus()):
            return K.Kernel(self.deck, [lp], settings=settings)

    def write(self, kind, name, data):
        d = paths.state_dir() / kind
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(json.dumps(data), encoding="utf-8")

    def count_renders(self, k):
        n = []
        real = k.render
        k.render = lambda: (n.append(1), real())[1]
        return n

    def prime(self, k):
        """The first check after the page opens: nothing changed, so
        nothing is drawn, and the period starts from here."""
        n = self.count_renders(k)
        self.tick(k, 0)
        self.assertEqual([], n)

    def tick(self, k, seconds):
        self.clock.advance(seconds)
        k.step(self.clock.now)


class ClaudePageTest(SessionPagesCase):
    def put(self, **kw):
        d = {"session_id": "a", "description": "topic", "ts_active": 5}
        d.update(kw)
        self.write("claude", "a.json", d)

    def shown(self, settings=None):
        self.put()
        k = self.kernel(claude_sessions, settings)
        k.state("p").sid = "a"
        k.goto("claude_session")
        self.prime(k)
        return k

    def test_unchanged_session_does_not_render(self):
        k = self.shown()
        n = self.count_renders(k)
        self.tick(k, 1.5)
        self.tick(k, 1.5)
        self.assertEqual([], n)
        self.assertEqual("claude_session", k.page_id)

    def test_changed_status_renders_once(self):
        k = self.shown()
        n = self.count_renders(k)
        self.put(ts_tool=9)
        self.tick(k, 1.5)
        self.tick(k, 1.5)
        self.assertEqual([1], n)

    def test_removed_file_goes_home(self):
        k = self.shown()
        (paths.state_dir() / "claude" / "a.json").unlink()
        self.tick(k, 1.5)
        self.assertEqual("idle", k.page_id)

    def test_period_follows_the_setting(self):
        k = self.shown({"session_refresh_sec": 2.5})
        self.put(ts_tool=9)
        n = self.count_renders(k)
        self.tick(k, 1.0)
        self.assertEqual([], n)
        self.tick(k, 1.0)
        self.assertEqual([], n)
        self.tick(k, 1.0)
        self.assertEqual([1], n)

    def test_default_period_is_one_second(self):
        k = self.shown()
        self.put(ts_tool=9)
        n = self.count_renders(k)
        self.tick(k, 0.5)
        self.assertEqual([], n)
        self.tick(k, 0.6)
        self.assertEqual([1], n)

    def test_kernels_with_other_periods_do_not_interfere(self):
        fast = self.shown({"session_refresh_sec": 0.5})
        slow = self.kernel(claude_sessions, {"session_refresh_sec": 30})
        slow.state("p").sid = "a"
        slow.goto("claude_session")
        self.prime(slow)
        self.put(ts_tool=9)
        n_fast = self.count_renders(fast)
        n_slow = self.count_renders(slow)
        self.tick(fast, 1.0)
        self.tick(slow, 1.0)
        self.assertEqual(([1], []), (n_fast, n_slow))
        self.assertEqual(0.0, claude_sessions.PLUGIN.pages[0].period)


class MpvPageTest(SessionPagesCase):
    def put(self, title="song"):
        self.write("mpv", "1.json", {"pid": 0, "title": title})

    def shown(self):
        self.put()
        k = self.kernel(mpv_sessions)
        k.state("p").pid = 0
        k.goto("mpv_session")
        self.prime(k)
        return k

    def test_unchanged_title_does_not_render(self):
        k = self.shown()
        n = self.count_renders(k)
        self.tick(k, 1.5)
        self.assertEqual([], n)

    def test_changed_title_renders_once(self):
        k = self.shown()
        n = self.count_renders(k)
        self.put("other")
        self.tick(k, 1.5)
        self.tick(k, 1.5)
        self.assertEqual([1], n)

    def test_removed_file_goes_home(self):
        k = self.shown()
        (paths.state_dir() / "mpv" / "1.json").unlink()
        self.tick(k, 1.5)
        self.assertEqual("idle", k.page_id)

    def test_period_follows_the_setting(self):
        self.put()
        k = self.kernel(mpv_sessions, {"session_refresh_sec": 2.5})
        k.state("p").pid = 0
        k.goto("mpv_session")
        self.prime(k)
        self.put("other")
        n = self.count_renders(k)
        self.tick(k, 2.0)
        self.assertEqual([], n)
        self.tick(k, 1.0)
        self.assertEqual([1], n)


if __name__ == "__main__":
    unittest.main()
