#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Atomic JSON writes and process liveness of the deck package."""

import io
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import streamdeck_stubs as S  # noqa: E402

S.install()
from erplibre_streamdeck import (  # noqa: E402
    jsonfile, liveness, paths, settings,
)
from erplibre_streamdeck.plugins import (  # noqa: E402
    claude_sessions, layouts, mpv_sessions, todo_terminals,
)


class WriteAtomicTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name, "sub")
        self.path = self.dir / "settings.json"

    def test_writes_and_creates_the_directory(self):
        jsonfile.write_atomic(self.path, {"a": 1})
        self.assertEqual({"a": 1}, json.loads(self.path.read_text()))

    def test_failure_keeps_old_file_and_no_temp(self):
        jsonfile.write_atomic(self.path, {"a": 1})
        with mock.patch("os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                jsonfile.write_atomic(self.path, {"a": 2})
        self.assertEqual({"a": 1}, json.loads(self.path.read_text()))
        self.assertEqual(["settings.json"], os.listdir(self.dir))

    def test_unserialisable_data_keeps_old_file(self):
        jsonfile.write_atomic(self.path, {"a": 1})
        with self.assertRaises(TypeError):
            jsonfile.write_atomic(self.path, {"a": object()})
        self.assertEqual({"a": 1}, json.loads(self.path.read_text()))
        self.assertEqual(["settings.json"], os.listdir(self.dir))

    def test_file_mode_follows_the_umask(self):
        mask = os.umask(0)
        os.umask(mask)
        jsonfile.write_atomic(self.path, {"a": 1})
        self.assertEqual(0o666 & ~mask, self.path.stat().st_mode & 0o777)

    def test_link_is_followed_and_target_mode_kept(self):
        self.dir.mkdir()
        real = self.dir / "real.json"
        real.write_text("{}")
        real.chmod(0o600)
        link = self.dir / "link.json"
        link.symlink_to(real)
        jsonfile.write_atomic(link, {"a": 3})
        self.assertTrue(link.is_symlink())
        self.assertEqual({"a": 3}, json.loads(real.read_text()))
        self.assertEqual(0o600, real.stat().st_mode & 0o7777)

    def test_existing_file_keeps_its_mode(self):
        self.dir.mkdir()
        self.path.write_text("{}")
        self.path.chmod(0o600)
        jsonfile.write_atomic(self.path, {"a": 1})
        self.assertEqual(0o600, self.path.stat().st_mode & 0o7777)

    def test_new_file_gets_the_umask_default(self):
        mask = os.umask(0)
        os.umask(mask)
        jsonfile.write_atomic(self.path, {"a": 1})
        self.assertEqual(0o666 & ~mask, self.path.stat().st_mode & 0o7777)

    def test_dangling_link_creates_its_target(self):
        self.dir.mkdir()
        real = self.dir / "real.json"
        link = self.dir / "link.json"
        link.symlink_to(real)
        jsonfile.write_atomic(link, {"a": 4})
        self.assertTrue(link.is_symlink())
        self.assertEqual({"a": 4}, json.loads(real.read_text()))

    def test_temp_file_is_replaced_from_the_target_directory(self):
        """os.replace is atomic only within one file system: a temporary
        file elsewhere would fail to move, or be copied."""
        with mock.patch("os.replace", wraps=os.replace) as replace:
            jsonfile.write_atomic(self.path, {"a": 1})
        src, dst = replace.call_args.args
        self.assertEqual(os.path.dirname(dst), os.path.dirname(src))
        self.assertEqual(os.path.realpath(self.path), dst)

    def test_temp_file_is_flushed_and_fsynced_before_replace(self):
        """A crash after the replace must not leave an empty file: the
        whole text is on disk before the new name points to it."""
        events = []
        real_fsync = os.fsync

        def fsync(fd):
            events.append(("fsync", os.fstat(fd).st_size))
            real_fsync(fd)

        def replace(src, dst):
            events.append(("replace", None))
            os.rename(src, dst)

        with mock.patch("os.fsync", fsync), \
                mock.patch("os.replace", replace):
            jsonfile.write_atomic(self.path, {"a": 1})
        size = len(json.dumps({"a": 1}, indent=2))
        self.assertEqual([("fsync", size), ("replace", None)], events)

    def test_write_leaves_the_process_umask_alone(self):
        # The umask is process-wide: setting it in a job thread would
        # widen or narrow the files every other thread creates.
        with mock.patch("os.umask", side_effect=AssertionError("umask")):
            jsonfile.write_atomic(self.path, {"a": 1})
        self.assertEqual({"a": 1}, json.loads(self.path.read_text()))


class LivenessTest(unittest.TestCase):
    LINE = ("4242 (a b) c (d)) S 1 4242 4242 0 -1 4194560 100 0 0 0 "
            "1 2 0 0 20 0 1 0 987654 1000 100")

    def test_parse_after_last_paren(self):
        self.assertEqual(987654, liveness.parse_start_ticks(self.LINE))

    def test_this_process_started_in_the_past(self):
        ms = liveness.started_ms(os.getpid())
        self.assertIsNotNone(ms)
        self.assertLess(ms, time.time() * 1000 + 1000)

    def test_start_converts_ticks_and_boot_time_to_epoch_ms(self):
        files = {
            "/proc/7/stat": self.LINE,
            "/proc/stat": "cpu  1 2 3\nbtime 1700000000\nprocesses 9\n",
        }

        def fake_open(path, *args, **kwargs):
            return io.StringIO(files[path])

        real_sysconf = os.sysconf

        def sysconf(name):
            return 250 if name == "SC_CLK_TCK" else real_sysconf(name)

        with mock.patch.object(liveness, "open", fake_open, create=True), \
                mock.patch("os.sysconf", sysconf):
            # 987654 ticks at 250 Hz after boot: 3950.616 s.
            self.assertEqual(
                1_700_003_950_616, liveness.started_ms(7)
            )

    def test_missing_pid(self):
        self.assertIsNone(liveness.started_ms(4194304))
        self.assertFalse(liveness.alive(4194304, 0))

    def test_alive_within_slack(self):
        with mock.patch.object(liveness, "started_ms", return_value=10_000):
            self.assertTrue(liveness.alive(7, 9_000))      # 1 s late: slack
            self.assertTrue(liveness.alive(7, 20_000))     # born before
            self.assertFalse(liveness.alive(7, 4_000))     # 6 s younger

    def test_start_exactly_at_the_slack_is_alive(self):
        with mock.patch.object(liveness, "started_ms", return_value=10_000):
            self.assertTrue(liveness.alive(7, 5_000))
            self.assertFalse(liveness.alive(7, 4_999))


class LoaderTest(unittest.TestCase):
    def setUp(self):
        S.wipe()
        self.addCleanup(S.wipe)

    def put(self, kind, name, data):
        d = paths.state_dir() / kind
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(json.dumps(data))

    def claude(self, **kw):
        self.put("claude", "s.json", dict({"session_id": "s"}, **kw))
        return claude_sessions.load_sessions()

    def mpv(self, **kw):
        self.put("mpv", "p.json", dict({"url": "u"}, **kw))
        return mpv_sessions.load_sessions()

    def test_claude_recycled_pid_dropped(self):
        with mock.patch.object(liveness, "started_ms", return_value=9000):
            self.assertEqual([], self.claude(pid=7, ts_active=1000))

    def test_claude_original_pid_kept(self):
        with mock.patch.object(liveness, "started_ms", return_value=500):
            self.assertEqual(1, len(self.claude(pid=7, ts_active=1000)))

    def test_claude_uses_oldest_stamp(self):
        with mock.patch.object(liveness, "started_ms", return_value=9000):
            out = self.claude(pid=7, ts_active=1000, ts_stop=50000)
        self.assertEqual([], out)

    def test_claude_zero_stamps_do_not_count(self):
        """An empty stamp is 0, the epoch: counted, it would make every
        process younger than the session and drop it."""
        with mock.patch.object(liveness, "started_ms", return_value=9000):
            out = self.claude(pid=7, ts_active=0, ts_stop=0, ts_tool=10000)
        self.assertEqual(1, len(out))

    def test_claude_without_stamps_checks_proc(self):
        self.assertEqual(1, len(self.claude(pid=os.getpid())))
        self.assertEqual([], self.claude(pid=4194304))

    def test_claude_pid_zero_kept(self):
        self.assertEqual(1, len(self.claude(pid=0, ts_active=1000)))

    def test_mpv_recycled_pid_dropped(self):
        with mock.patch.object(liveness, "started_ms", return_value=9000):
            self.assertEqual([], self.mpv(pid=7, started_at=1000))

    def test_mpv_original_pid_kept(self):
        with mock.patch.object(liveness, "started_ms", return_value=500):
            self.assertEqual(1, len(self.mpv(pid=7, started_at=1000)))

    def test_mpv_without_started_at_checks_proc(self):
        self.assertEqual(1, len(self.mpv(pid=os.getpid())))
        self.assertEqual([], self.mpv(pid=4194304))

    def test_mpv_pid_zero_kept(self):
        self.assertEqual(1, len(self.mpv(pid=0, started_at=1000)))


class WritersUseWriteAtomicTest(unittest.TestCase):
    def test_settings_save(self):
        with mock.patch.object(jsonfile, "write_atomic") as w:
            settings.save({"a": 1})
        w.assert_called_once_with(paths.SETTINGS_FILE, {"a": 1})

    def test_layouts_save(self):
        with mock.patch.object(jsonfile, "write_atomic") as w:
            layouts._layouts_save({"slots": {}})
        w.assert_called_once_with(paths.LAYOUTS_FILE, {"slots": {}})

    def test_registry_save(self):
        with mock.patch.object(jsonfile, "write_atomic") as w:
            todo_terminals.save_registry([{"window_id": "1"}])
        w.assert_called_once_with(
            todo_terminals.registry_path(), [{"window_id": "1"}],
            indent=None,
        )


if __name__ == "__main__":
    unittest.main()
