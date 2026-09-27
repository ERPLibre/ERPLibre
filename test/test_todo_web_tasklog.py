#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Journaux de tâches du hub web : écriture, clôture, relecture, purge et
reprise, sur un HOME temporaire. Les secrets sont inventés."""

import datetime
import json
import os
import stat
import time
import unittest
from unittest.mock import patch

from compression import zstd
from todo_web_env import private_env

from script.todo.web import paths, tasklog

DAY = 24 * 3600


def _mode(path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


class StoreCase(unittest.TestCase):
    def setUp(self):
        tmp = private_env(self.addCleanup)
        (tmp / "checkout").mkdir()
        self.base = paths.tasks_dir(tmp / "checkout")

    def task(self, when=None):
        """Une tâche ouverte à `when` (time.time()), lancée par l'entrée
        « 1 » : sa première ligne, si elle vaut « 1 », est l'écho."""
        now = time.time() if when is None else when
        info = {
            "id": tasklog.new_id(now),
            "session": "s1",
            "crumbs": ["TODO", "Execute"],
            "entry": "Show code status",
            "key": "1",
            "start": now,
        }
        return tasklog.TaskLog(self.base, info, skip=("1",))

    def texts(self, task_id):
        page = tasklog.read(self.base, task_id, 1, 1000)
        return [r["d"] for r in page["lines"] if r["s"] == "out"]


class TestTaskLog(StoreCase):
    def test_directories_are_0700_and_files_0600(self):
        task = self.task()
        task.output(b"hello\r\n")
        day = task.path.parent
        self.assertEqual((_mode(self.base), _mode(day)), (0o700, 0o700))
        self.assertEqual(_mode(task.path), 0o600)
        task.close("done")
        self.assertFalse(task.path.exists())
        for name in (task.path.name + ".zst", "index.jsonl"):
            self.assertEqual(_mode(day / name), 0o600, name)

    def test_lines_are_cleaned_numbered_and_redacted(self):
        task = self.task()
        for chunk in (
            b"\r\n1\r\n",
            b"\x1b[32mgreen\x1b[0m text\x07\r\n\r\n",
            b"50%\r75%\r100%\r\n",
            b"Password: inventeAB\r\n",
            b"clone https://u:inventeCD@forge.example/r\r\n",
            b"caf\xc3",
            b"\xa9 \xff\r\n",
            b"\x1b]0;title\x07no newline",
        ):
            task.output(chunk)
        self.assertNotIn(b"invente", task.path.read_bytes())
        task.close("done")
        expected = [
            "green text",
            "",
            "100%",
            "Password: ***",
            "clone https://u:***@forge.example/r",
            "café �",
            "no newline",
        ]
        self.assertEqual(self.texts(task.info["id"]), expected)
        page = tasklog.read(self.base, task.info["id"], 1, 10)
        self.assertEqual([r["n"] for r in page["lines"]], list(range(1, 9)))
        self.assertEqual(page["lines"][0]["d"]["t"], "task_start")
        packed = task.path.with_name(task.path.name + ".zst")
        self.assertNotIn(b"invente", zstd.decompress(packed.read_bytes()))

    def test_events_and_commands_make_the_index_entry(self):
        task = self.task()
        task.event({"t": "run_start", "cmd": "make repo_show_status"})
        task.output(b"clean\r\n")
        task.event({"t": "run_end", "rc": 2, "secs": 0.5})
        entry = task.close("done")
        self.assertEqual(
            {k: entry[k] for k in ("crumbs", "entry", "state", "lines")},
            {
                "crumbs": ["TODO", "Execute"],
                "entry": "Show code status",
                "state": "done",
                "lines": 1,
            },
        )
        command = {"cmd": "make repo_show_status", "rc": 2, "secs": 0.5}
        self.assertEqual(entry["commands"], [command])
        self.assertEqual(tasklog.entries(self.base), [entry])

    def test_a_task_that_kept_nothing_leaves_no_file(self):
        task = self.task()
        task.output(b"\r\n1\r\n\r\n")
        self.assertIsNone(task.close("done"))
        self.assertFalse(task.path.parent.exists())
        self.assertEqual(tasklog.entries(self.base), [])

    def test_over_the_cap_the_tail_follows_an_omission(self):
        task = self.task()
        # 40 lignes de 9 octets : les 10 premières tiennent sous le plafond,
        # puis les 30 derniers octets restent, dont la fin de ligne coupée
        # en tête (3 octets) part aussi.
        lines = b"".join(b"line %02d\r\n" % n for n in range(40))
        with patch.multiple(tasklog, CAP=90, TAIL=30):
            task.output(lines[:60])
            task.output(lines[60:])
            task.close("done")
        page = tasklog.read(self.base, task.info["id"], 1, 100)
        records = [(r["s"], r["d"]) for r in page["lines"][1:]]
        omitted = ("event", {"t": "omitted", "bytes": len(lines) - 120 + 3})
        self.assertIn(omitted, records)
        at = records.index(omitted)
        self.assertEqual(records[at - 1], ("out", "line 09"))
        self.assertEqual(
            records[at + 1 :], [("out", f"line {n}") for n in (37, 38, 39)]
        )

    def test_a_cut_through_a_secret_keeps_no_piece_of_it(self):
        # Le plafond coupe l'URL, la fin retenue commence dans le mot de
        # passe de la ligne suivante : ni l'une ni l'autre ne reste.
        data = (
            b"x" * 30
            + b" https://u:inventeKLMNOP@forge.example/r\r\n"
            + b"Password: inventeQRSTUV\r\nend\r\n"
        )
        task = self.task()
        with patch.multiple(tasklog, CAP=45, TAIL=16):
            task.output(data)
            task.close("done")
        page = tasklog.read(self.base, task.info["id"], 2, 100)
        omitted = {"t": "omitted", "bytes": len(data) - len(b"end\r\n")}
        self.assertEqual(
            [(r["s"], r["d"]) for r in page["lines"]],
            [("event", omitted), ("out", "end")],
        )
        packed = task.path.with_name(task.path.name + ".zst")
        for piece in (b"invente", b"KLMNOP", b"QRSTUV"):
            self.assertNotIn(piece, zstd.decompress(packed.read_bytes()))

    def test_a_secret_across_the_line_limit_is_still_masked(self):
        # Une ligne plus longue que LINE_LIMIT est masquée entière, puis
        # coupée : le secret à cheval sur la coupure ne passe pas.
        width = tasklog.LINE_LIMIT
        task = self.task()
        task.output(
            b"x" * (width - 14) + b" https://u:inventeAB@forge.example\r\n"
        )
        task.output(b"q" * (width - 11) + b" Password: inventeCD\r\n")
        task.close("done")
        texts = self.texts(task.info["id"])
        self.assertEqual(
            ["".join(texts[:2]), "".join(texts[2:])],
            [
                "x" * (width - 14) + " https://u:***@forge.example",
                "q" * (width - 11) + " Password: ***",
            ],
        )
        self.assertEqual([len(t) for t in texts[::2]], [width, width])

    def test_a_secret_across_the_partial_limit_is_still_masked(self):
        # PARTIAL_LIMIT force une ligne sans fin à s'écrire avant son \n ;
        # un secret qui commence avant la limite et finit après, dans le
        # morceau suivant reçu du PTY, ne doit ni se couper en deux moitiés
        # en clair (l'URL), ni sortir en clair une fois séparé du mot qui
        # l'aurait fait masquer (le mot de passe).
        task = self.task()
        with patch.object(tasklog, "PARTIAL_LIMIT", 40):
            task.output(b"x" * 30 + b" https://u:inven")
            task.output(b"teAB@forge.example/r\r\n")
            task.output(b"y" * 30 + b" Password: inv")
            task.output(b"enteCD more\r\n")
            task.close("done")
        self.assertEqual(
            self.texts(task.info["id"]),
            [
                "x" * 30 + " https://u:***@forge.example/r",
                "y" * 30 + " Password: ***",
            ],
        )
        packed = task.path.with_name(task.path.name + ".zst")
        self.assertNotIn(b"invente", zstd.decompress(packed.read_bytes()))

    def test_a_tainted_line_survives_many_tiny_chunks_past_the_limit(self):
        # Beaucoup de très petits morceaux, sans jamais de \n : la ligne
        # guettée doit rester intacte et se masquer entière malgré une
        # fragmentation extrême, bien au-delà de PARTIAL_LIMIT.
        task = self.task()
        secret = b"inventeAB" + b"9" * 40
        with patch.object(tasklog, "PARTIAL_LIMIT", 40):
            task.output(b"https://u:")
            for byte in secret:
                task.output(bytes([byte]))
            task.output(b"@forge.example\r\n")
            task.close("done")
        self.assertEqual(
            self.texts(task.info["id"]), ["https://u:***@forge.example"]
        )
        packed = task.path.with_name(task.path.name + ".zst")
        self.assertNotIn(b"invente", zstd.decompress(packed.read_bytes()))

    def test_a_long_tainted_line_costs_linear_not_quadratic_time(self):
        # Lines.feed ne doit jamais relire toute la ligne guettée déjà
        # accumulée à chaque envoi : un temps proportionnel à son carré
        # bloquerait la boucle asyncio commune à toutes les sessions.
        lines = tasklog.Lines()
        chunk = b"a" * (64 * 1024)
        debut = time.monotonic()
        lines.feed(b"https://" + chunk)
        for _ in range(1023):  # 64 Mio au total, guettée du début à la fin
            lines.feed(chunk)
        self.assertLess(time.monotonic() - debut, 3.0)

    def test_a_closed_log_reads_back_page_by_page(self):
        task = self.task()
        task.output(b"".join(b"%d\r\n" % n for n in range(10, 20)))
        task.close("done")
        task_id = task.info["id"]
        first = tasklog.read(self.base, task_id, 1, 4)
        self.assertEqual([r["n"] for r in first["lines"]], [1, 2, 3, 4])
        self.assertEqual((first["next"], first["eof"]), (5, False))
        last = tasklog.read(self.base, task_id, 9, 4)
        self.assertEqual([r["n"] for r in last["lines"]], [9, 10, 11])
        self.assertEqual((last["next"], last["eof"]), (12, True))
        self.assertEqual(last["state"], "done")
        other = tasklog.new_id(time.time())
        self.assertIsNone(tasklog.read(self.base, other, 1, 4))

    def test_an_open_log_reads_as_open(self):
        task = self.task()
        task.output(b"working\r\n")
        page = tasklog.read(self.base, task.info["id"], 1, 10)
        self.assertEqual(page["state"], "open")
        self.assertEqual(page["lines"][-1]["d"], "working")


class TestStore(StoreCase):
    def closed(self, when, text=b"out\r\n"):
        task = self.task(when)
        task.output(text)
        return task.close("done")

    def noon(self, days_ago):
        """Midi, heure locale, `days_ago` jours avant aujourd'hui : loin de
        minuit, qu'un changement d'heure ferait franchir."""
        day = datetime.date.today() - datetime.timedelta(days_ago)
        return datetime.datetime.combine(day, datetime.time(12)).timestamp()

    def test_entries_are_newest_first_and_page_by_id(self):
        now = time.time()
        old, mid, new = (self.closed(now - s) for s in (2 * DAY, 60, 0))
        self.assertEqual(tasklog.entries(self.base, 2), [new, mid])
        before = tasklog.entries(self.base, 2, before=mid["id"])
        self.assertEqual(before, [old])

    def test_purge_removes_a_day_at_31_days_not_at_29(self):
        gone, kept = self.closed(self.noon(31)), self.closed(self.noon(29))
        expiry = tasklog.expiry()
        self.assertEqual(
            expiry, datetime.date.today() - datetime.timedelta(30)
        )
        self.assertEqual(tasklog.purge(self.base, expiry), 1)
        self.assertEqual(tasklog.entries(self.base), [kept])
        self.assertIsNone(tasklog.read(self.base, gone["id"], 1, 1))

    def test_purge_keeps_only_an_open_log(self):
        self.closed(self.noon(40))
        running = self.task(self.noon(40))
        running.output(b"still running\r\n")
        self.closed(self.noon(35))
        self.assertEqual(tasklog.purge(self.base), 2)
        self.assertTrue(running.path.exists())
        self.assertEqual(tasklog.entries(self.base), [])
        # Close plus tard, la tâche écrit un index neuf dans son jour.
        entry = running.close("done")
        self.assertEqual(tasklog.entries(self.base), [entry])

    def test_a_torn_index_line_loses_no_other_entry(self):
        first = self.closed(time.time())
        day = self.base / tasklog.day_of(first["id"])
        with open(day / "index.jsonl", "ab") as index:
            index.write(b'{"id": "2026')  # un écrivain tué en pleine ligne
        second = self.closed(time.time())
        self.assertCountEqual(tasklog.entries(self.base), [first, second])

    def test_recover_closes_what_a_killed_hub_left(self):
        task = self.task()
        task.event({"t": "run_start", "cmd": "sleep 60"})
        task.output(b"started\r\n")
        os.close(task.fd)  # le hub meurt : rien n'est clos
        with open(task.path, "ab") as log:
            log.write(b'{"n": 4, "t": 0.5, "s": "out", "d": "tor')
        self.assertEqual(tasklog.recover(self.base), 1)
        [entry] = tasklog.entries(self.base)
        self.assertEqual((entry["state"], entry["lines"]), ("interrupted", 1))
        self.assertEqual(entry["crumbs"], ["TODO", "Execute"])
        command = {"cmd": "sleep 60", "rc": None, "secs": None}
        self.assertEqual(entry["commands"], [command])
        self.assertEqual(self.texts(entry["id"]), ["started"])
        self.assertFalse(task.path.exists())
        self.assertEqual(tasklog.recover(self.base), 0)

    def test_an_invalid_id_names_no_file(self):
        # Des chiffres arabes-indiens valent \d, pas [0-9].
        arabic = "".join(chr(0x660 + int(c)) for c in "20260101")
        for task_id in (
            "../x",
            "20260101-000000-zzzzzz",
            "",
            "a/b",
            arabic + "-000000-abcdef",
        ):
            with self.assertRaises(ValueError):
                tasklog.day_of(task_id)


if __name__ == "__main__":
    unittest.main()
