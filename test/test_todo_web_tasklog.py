#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Journaux de tâches du hub web : écriture, clôture, relecture, purge et
reprise, puis les bornes d'une tâche lues des messages du canal
(`Recorder`), sur un HOME temporaire. Les secrets sont inventés."""

import datetime
import errno
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

    def stored(self, chunks):
        """`chunks` reçus un à un par une tâche, PARTIAL_LIMIT à 40, puis
        close : ses lignes relues, et son journal compressé, décompressé."""
        task = self.task()
        with patch.object(tasklog, "PARTIAL_LIMIT", 40):
            for chunk in chunks:
                task.output(chunk)
            task.close("done")
        packed = task.path.with_name(task.path.name + ".zst")
        data = zstd.decompress(packed.read_bytes())
        return self.texts(task.info["id"]), data


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

    def test_a_split_word_across_the_partial_limit_is_still_masked(self):
        # PARTIAL_LIMIT peut tomber pile au milieu du mot qui ferait
        # reconnaître un secret (« https:/|/ », « Pa|ssword ») plutôt qu'au
        # milieu de sa valeur : aucun des deux morceaux ne le porte encore
        # en entier, mais la coupure recule jusqu'à un blanc, pas à la
        # frontière du morceau du PTY, et le mot ne se retrouve jamais
        # coupé en deux.
        texts, packed = self.stored(
            [
                b"x" * 29 + b" a b https:/",
                b"/u:inventeAB@forge.example/r\r\n",
                b"y" * 34 + b" a b Pa",
                b"ssword: inventeCD more\r\n",
            ]
        )
        self.assertEqual(
            texts,
            [
                "x" * 29 + " ",
                "a b https://u:***@forge.example/r",
                "y" * 34 + " ",
                "a b Password: ***",
            ],
        )
        self.assertNotIn(b"invente", packed)

    def test_a_label_completed_past_the_partial_limit_holds_the_line(self):
        # Le morceau qui franchit PARTIAL_LIMIT achève l'étiquette et porte
        # sa valeur, ou une séquence ANSI en sépare les deux moitiés : aucun
        # morceau ne la porte seul, la ligne jointe si, et elle attend son
        # \n entière plutôt que de laisser la valeur hors de l'étiquette.
        y = b"y" * 30
        cases = (
            ([y + b" Pa", b"ssword: inventeEF", b"\r\n"], "Password: ***"),
            ([y + b" --pa", b"ssword inventeGH", b"\r\n"], "--password ***"),
            (
                [y + b" Au", b"thorization: Bearer inventeIJ", b"\r\n"],
                "Authorization: Bearer '***'",
            ),
            ([y + b" Pa", b"ssword: inventeKL\r", b"\n"], "Password: ***"),
            (
                [y + b" Pa\x1b[0m", b"ssword: inventeMN", b"\r\n"],
                "Password: ***",
            ),
        )
        for chunks, masked in cases:
            with self.subTest(chunks=chunks):
                texts, packed = self.stored(chunks)
                self.assertEqual(texts, ["y" * 30 + " " + masked])
                self.assertNotIn(b"invente", packed)

    def test_a_cut_keeps_two_whole_words_before_the_last_one(self):
        # « mot de passe » ne se reconnaît qu'entier : une coupure au seul
        # dernier blanc laisserait « passe : … », que rien ne masque.
        texts, packed = self.stored(
            [b"y" * 33 + b" mot de pa", b"sse : inventeOP\r\n"]
        )
        self.assertEqual(texts, ["y" * 33 + " ", "mot de passe : ***"])
        self.assertNotIn(b"invente", packed)

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

    def test_clean_keeps_a_real_line_before_control_characters(self):
        # Une version faite de seuls contrôles ne remplace pas la ligne.
        for line, shown in (
            ("progress 100%\r\x07", "progress 100%"),
            ("50%\r\x1b[K75%", "75%"),
            ("\x07\r", ""),
        ):
            with self.subTest(line=line):
                self.assertEqual(tasklog.clean(line), shown)

    def test_closing_twice_returns_the_first_entry(self):
        task = self.task()
        task.output(b"once\r\n")
        entry = task.close("done")
        task.output(b"late\r\n")
        self.assertIs(task.close("interrupted"), entry)
        self.assertEqual(tasklog.entries(self.base), [entry])
        self.assertEqual(self.texts(entry["id"]), ["once"])

    def records(self, task):
        page = tasklog.read(self.base, task.info["id"], 2, 100)
        return [(r["s"], r["d"]) for r in page["lines"]]

    def test_an_unfinished_line_comes_before_the_next_event(self):
        # L'invite d'une question précède sa question et sa réponse ; la
        # suite de la ligne, l'écho de la réponse, vient après elles.
        task = self.task()
        task.output(b"Path for the file [x]: ")
        task.event({"t": "ask", "kind": "text", "text": "Path"})
        task.event({"t": "answer", "value": "/tmp/y"})
        task.output(b"/tmp/y\r\nnext\r\n")
        task.close("done")
        self.assertEqual(
            self.records(task),
            [
                ("out", "Path for the file [x]: "),
                ("event", {"t": "ask", "kind": "text", "text": "Path"}),
                ("event", {"t": "answer", "value": "/tmp/y"}),
                ("out", "/tmp/y"),
                ("out", "next"),
            ],
        )

    def test_an_event_never_splits_a_secret_from_its_label(self):
        # Une ligne qui porte un mot guetté reste entière : l'événement
        # passe devant elle. Sans mot guetté, la coupure se fait, et la
        # suite se masque avec le début de la ligne déjà écrit : un mot
        # coupé par l'événement se reconnaît encore.
        cases = (
            (b"Database password: ", b"hunter2\r\n", None),
            (b"x pa", b"ssword: hunter2\r\n", ("x pa", "ssword: ***")),
            (b"mot de ", b"passe : hunter2\r\n", ("mot de ", "passe : ***")),
            (
                b"clone https:/",
                b"/u:hunter2@forge.example/r\r\n",
                ("clone https:/", "/u:***@forge.example/r"),
            ),
        )
        for before, after, split in cases:
            with self.subTest(before=before):
                task = self.task()
                task.output(before)
                task.event({"t": "answered"})
                task.output(after)
                task.close("done")
                event = ("event", {"t": "answered"})
                if split is None:
                    whole = "Database password: ***"
                    expected = [event, ("out", whole)]
                else:
                    expected = [("out", split[0]), event, ("out", split[1])]
                self.assertEqual(self.records(task), expected)
                packed = task.path.with_name(task.path.name + ".zst")
                data = zstd.decompress(packed.read_bytes())
                self.assertNotIn(b"hunter2", data)

    def test_a_line_is_split_once_and_its_rest_waits_for_its_end(self):
        # Un second événement sur la même ligne inachevée passe devant sa
        # suite, sans la couper de nouveau ; passé PARTIAL_LIMIT, la
        # suite se lit avec le début déjà écrit, qui achève le mot guetté.
        task = self.task()
        with patch.object(tasklog, "PARTIAL_LIMIT", 40):
            task.output(b"step x pa")
            task.event({"t": "run_start", "cmd": "a"})
            task.output(b"ssword: hunter2 a b c " + b"y" * 40)
            task.event({"t": "run_end", "rc": 0, "secs": 1})
            task.output(b" end\r\n")
            task.close("done")
        self.assertEqual(
            self.records(task),
            [
                ("out", "step x pa"),
                ("event", {"t": "run_start", "cmd": "a"}),
                ("event", {"t": "run_end", "rc": 0, "secs": 1}),
                ("out", "ssword: ***"),
            ],
        )
        packed = task.path.with_name(task.path.name + ".zst")
        self.assertNotIn(b"hunter2", zstd.decompress(packed.read_bytes()))

    def test_the_echo_of_the_answer_stays_out_before_an_event(self):
        task = self.task()
        task.output(b"1")
        task.event({"t": "run_start", "cmd": "true"})
        task.output(b"\r\nworking\r\n")
        task.close("done")
        self.assertEqual(
            self.records(task),
            [
                ("event", {"t": "run_start", "cmd": "true"}),
                ("out", "working"),
            ],
        )

    def test_over_the_cap_events_keep_their_place_in_the_tail(self):
        # 40 lignes de 9 octets, plafond après 10 : un événement dont la
        # sortie qui suit est omise s'écrit avant `omitted`, un événement
        # dans la fin retenue, entre ses lignes.
        lines = b"".join(b"line %02d\r\n" % n for n in range(40))
        task = self.task()
        with patch.multiple(tasklog, CAP=90, TAIL=30):
            task.output(lines[:108])
            task.event({"t": "run_start", "cmd": "early"})
            task.output(lines[108:315])
            task.event({"t": "run_end", "rc": 0, "secs": 1})
            task.output(lines[315:333])
            task.close("done")
        records = self.records(task)
        at = records.index(("out", "line 09"))
        self.assertEqual(
            records[at + 1 :],
            [
                ("event", {"t": "run_start", "cmd": "early"}),
                ("event", {"t": "omitted", "bytes": 333 - 90 - 27}),
                ("out", "line 34"),
                ("event", {"t": "run_end", "rc": 0, "secs": 1}),
                ("out", "line 35"),
                ("out", "line 36"),
            ],
        )

    def test_over_the_cap_waiting_events_stay_bounded(self):
        # Passé LATER octets d'événements en attente (35 chacun ici), le
        # plus ancien s'écrit aussitôt, devant la fin retenue.
        lines = b"".join(b"line %02d\r\n" % n for n in range(12))
        task = self.task()
        with patch.multiple(tasklog, CAP=90, TAIL=30, LATER=80):
            task.output(lines[:99])
            for n in range(3):
                task.event({"t": "run_start", "cmd": f"cmd {n}"})
            self.assertEqual(len(task.later), 2)
            task.output(lines[99:])
            task.close("done")
        records = self.records(task)
        at = records.index(("out", "line 09"))
        self.assertEqual(
            records[at + 1 :],
            [
                ("event", {"t": "run_start", "cmd": "cmd 0"}),
                ("out", "line 10"),
                ("event", {"t": "run_start", "cmd": "cmd 1"}),
                ("event", {"t": "run_start", "cmd": "cmd 2"}),
                ("out", "line 11"),
            ],
        )

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

    def test_purge_removes_a_day_at_31_days_not_at_30(self):
        # Le jour de 30 jours est le plus ancien gardé (`expiry`).
        gone, edge, kept = (self.closed(self.noon(d)) for d in (31, 30, 29))
        expiry = tasklog.expiry()
        self.assertEqual(
            expiry, datetime.date.today() - datetime.timedelta(30)
        )
        self.assertEqual(tasklog.purge(self.base, expiry), 1)
        self.assertEqual(tasklog.entries(self.base), [kept, edge])
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

    def test_recover_counts_what_it_seals_and_goes_past_a_failure(self):
        # Un disque plein fait échouer le scellement d'une tâche : les
        # suivantes se closent quand même, et seules elles comptent. Un
        # `.log` déjà à l'index n'est que retiré.
        stuck, left = self.task(), self.task()
        for task in (stuck, left):
            task.output(b"working\r\n")
            task.abandon()
        sealed = self.closed(time.time())
        stale = self.base / tasklog.day_of(sealed["id"])
        stale = stale / f"{sealed['id']}.log"
        stale.write_bytes(b"")  # scellé, puis tué avant de le retirer
        seal = tasklog._seal

        def full(path, entry):
            if path == stuck.path:
                raise OSError(errno.ENOSPC, "No space left on device")
            seal(path, entry)

        with (
            patch.object(tasklog, "_seal", side_effect=full),
            self.assertLogs(tasklog.log, "WARNING") as logs,
        ):
            self.assertEqual(tasklog.recover(self.base), 1)
        self.assertIn(stuck.info["id"], logs.output[0])
        self.assertTrue(stuck.path.exists())
        self.assertFalse(stale.exists())
        states = {e["id"]: e["state"] for e in tasklog.entries(self.base)}
        self.assertEqual(
            states, {left.info["id"]: "interrupted", sealed["id"]: "done"}
        )

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


MENU = {
    "t": "menu",
    "crumbs": ["TODO", "Code"],
    "items": [
        {"key": "1", "label": "Show code status"},
        {"key": "0", "label": "Back"},
    ],
    "text": "📍 TODO › Code\n[1] Show code status\n[0] Back\n: ",
}
# Le menu tel que le PTY le montre : ONLCR change chaque \n en \r\n.
SHOWN = MENU["text"].replace("\n", "\r\n").encode()


class TestRecorder(StoreCase):
    """Une tâche va de la réponse à un menu au menu suivant ; aucun worker,
    les messages du canal sont donnés tels que le hub les relaie."""

    def setUp(self):
        super().setUp()
        self.rec = tasklog.Recorder(self.base, "s1")

    def menu(self, qid):
        self.rec.worker(dict(MENU, qid=qid))

    def start(self, key="1"):
        """Le menu 1 montré, puis répondu par `key` ; l'écho suit."""
        self.menu(1)
        self.rec.output(SHOWN)
        self.rec.worker({"t": "answered", "qid": 1, "key": key})
        self.rec.output(key.encode() + b"\r\n")

    def records(self):
        [entry] = tasklog.entries(self.base)
        page = tasklog.read(self.base, entry["id"], 2, 100)
        return entry, [(r["s"], r["d"]) for r in page["lines"]]

    def test_menu_answer_commands_then_menu_bound_a_task(self):
        self.start()
        self.rec.worker({"t": "run_start", "cmd": "make repo_show_status"})
        self.rec.output(b"nothing to commit\r\n")
        self.rec.worker({"t": "run_end", "rc": 0, "secs": 0.2})
        self.rec.output(b"done\r\n")
        self.menu(2)
        self.assertIsNotNone(self.rec.waiting)
        self.rec.output(SHOWN)
        self.assertIsNone(self.rec.waiting)
        entry, records = self.records()
        self.assertEqual(
            (entry["crumbs"], entry["entry"], entry["state"]),
            (["TODO", "Code"], "Show code status", "done"),
        )
        command = {"cmd": "make repo_show_status", "rc": 0, "secs": 0.2}
        self.assertEqual(entry["commands"], [command])
        self.assertEqual(
            records,
            [
                ("event", {"t": "run_start", "cmd": command["cmd"]}),
                ("out", "nothing to commit"),
                ("event", {"t": "run_end", "rc": 0, "secs": 0.2}),
                ("out", "done"),
            ],
        )

    def test_a_menu_text_read_before_its_message_is_cut_too(self):
        self.start()
        self.rec.output(b"done\r\n" + SHOWN)
        self.menu(2)
        self.assertIsNone(self.rec.waiting)
        self.assertEqual(self.records()[1], [("out", "done")])

    def test_an_event_later_than_the_menu_text_keeps_its_order(self):
        # Le canal et le PTY sont deux flux : `run_end` peut arriver après
        # le texte du menu qui le suit.
        self.start()
        self.rec.worker({"t": "run_start", "cmd": "true"})
        self.rec.output(b"out\r\n" + SHOWN)
        self.rec.worker({"t": "run_end", "rc": 0, "secs": 0.1})
        self.menu(2)
        kinds = [
            (s, d if s == "out" else d["t"]) for s, d in self.records()[1]
        ]
        self.assertEqual(
            kinds,
            [("event", "run_start"), ("out", "out"), ("event", "run_end")],
        )

    def test_moving_between_menus_leaves_no_task(self):
        self.start()
        self.rec.output(b"\r\nWhat do you need?\r\n")  # l'en-tête du sous-menu
        self.rec.worker(dict(MENU, qid=2, crumbs=["TODO", "Code", "Sub"]))
        self.rec.output(SHOWN)
        self.assertIsNone(self.rec.task)
        self.start("0")
        self.menu(2)
        self.rec.output(SHOWN)
        self.start("9")  # hors des entrées : aucune tâche
        self.rec.output(b"Invalid choice\r\n")
        self.rec.worker({"t": "answered", "qid": 1})
        self.assertIsNone(self.rec.task)
        self.assertEqual(tasklog.entries(self.base), [])

    def test_a_leaf_that_leads_elsewhere_is_kept(self):
        # Un menu d'un autre fil, ni plus ni moins profond : la feuille qui
        # y mène a fait quelque chose, même sans événement.
        self.start()
        self.rec.output(b"report written\r\n")
        self.rec.worker(dict(MENU, qid=2, crumbs=["TODO", "Mail"]))
        self.rec.output(SHOWN)
        self.assertEqual(self.records()[1], [("out", "report written")])

    def test_a_menu_prompt_inside_the_output_does_not_close(self):
        # Un menu lu à l'écran ne porte que son invite : la même invite plus
        # haut dans la sortie n'est pas lui.
        menu = dict(MENU, text="Choice: ")
        self.rec.worker(dict(menu, qid=1))
        self.rec.output(b"Choice: ")
        self.rec.worker({"t": "answered", "qid": 1, "key": "1"})
        self.rec.output(b"1\r\nstep 1\r\nChoice: A was kept\r\n")
        self.rec.output(b"step 2 finished after that choice\r\n")
        self.rec.worker(dict(menu, qid=2))
        self.assertIsNotNone(self.rec.waiting)
        self.rec.output(b"Choice: ")
        self.assertIsNone(self.rec.waiting)
        self.assertEqual(
            [d for s, d in self.records()[1]],
            [
                "step 1",
                "Choice: A was kept",
                "step 2 finished after that choice",
            ],
        )

    def test_settle_closes_a_task_whose_menu_never_shows(self):
        self.start()
        self.rec.output(b"done\r\n")
        self.menu(2)
        waiting = self.rec.waiting
        self.rec.settle("20260101-000000-abcdef")
        self.assertEqual(self.rec.waiting, waiting)
        self.rec.settle(waiting)
        self.assertEqual(self.records()[1], [("out", "done")])

    def test_output_is_held_half_a_second_and_delays_are_planned(self):
        planned = []
        rec = tasklog.Recorder(
            self.base, "s1", later=lambda *call: planned.append(call)
        )
        rec.worker(dict(MENU, qid=1))
        rec.worker({"t": "answered", "qid": 1, "key": "1"})
        rec.output(b"working\r\n")
        self.assertIsNone(rec.task.fd)  # retenue : rien encore sur disque
        self.assertEqual(planned, [(tasklog.HOLD_SECONDS, rec.flush)])
        with patch.object(tasklog, "HOLD_SECONDS", 0):
            rec.flush()
        page = tasklog.read(self.base, rec.task.info["id"], 2, 10)
        self.assertEqual([r["d"] for r in page["lines"]], ["working"])
        rec.worker(dict(MENU, qid=2))  # son texte ne paraît pas
        waiting = rec.waiting
        self.assertEqual(
            planned[-1], (tasklog.SETTLE_SECONDS, rec.settle, waiting)
        )
        rec.settle(waiting)
        self.assertIsNone(rec.task)

    def test_a_command_is_masked_as_shown_whole(self):
        self.start()
        run = "mysql --password inventeAB -h db.example base"
        self.rec.worker({"t": "run_start", "cmd": run})
        self.rec.end()
        entry, records = self.records()
        shown = "mysql --password '***' -h db.example base"
        self.assertEqual(entry["commands"][0]["cmd"], shown)
        self.assertEqual(
            records, [("event", {"t": "run_start", "cmd": shown})]
        )

    def test_a_command_a_conninfo_password_hides_too(self):
        # « password= » sans option ni tiret : le masque de l'affichage n'y
        # touche pas seul (aucun « --password »), celui du stockage le
        # rattrape sans couper ce qu'il a déjà masqué ailleurs sur la ligne.
        self.start()
        run = 'psql "host=db.example password=hunter2" base'
        self.rec.worker({"t": "run_start", "cmd": run})
        self.rec.end()
        entry, records = self.records()
        shown = 'psql "host=db.example password=***'
        self.assertEqual(entry["commands"][0]["cmd"], shown)
        self.assertEqual(
            records, [("event", {"t": "run_start", "cmd": shown})]
        )
        self.assertNotIn("hunter2", repr(entry))
        self.assertNotIn("hunter2", repr(records))

    def test_a_secret_answer_is_never_kept(self):
        self.start()
        asks = [
            (2, "secret", "Passphrase: ", "answer", "hunter2"),
            (3, "text", "Database password: ", "answer", "hunter2"),
            (4, "text", "Name: ", "answer", "forged"),
            (5, "text", "Name: ", "cancel", None),
            (6, "confirm", "Continue? [y/N] ", None, None),
        ]
        for qid, kind, text, reply, value in asks:
            self.rec.worker(
                {"t": "ask", "qid": qid, "kind": kind, "text": text}
            )
            if reply is not None:
                self.rec.page({"t": reply, "qid": qid, "value": value})
            if kind == "secret":
                # La valeur d'un secret n'est pas même retenue.
                self.assertNotIn(value, repr(self.rec.given))
            self.rec.worker({"t": "answered", "qid": qid})
        self.rec.end()
        entry, records = self.records()
        self.assertEqual(entry["state"], "session-ended")
        ends = [d for s, d in records if d["t"] != "ask"]
        self.assertEqual(
            ends,
            [
                {"t": "answer", "value": "•••"},
                {"t": "answer", "value": "•••"},
                {"t": "answer", "value": "forged"},
                {"t": "cancel"},
                {"t": "answered"},
            ],
        )
        for path in self.base.rglob("*.zst"):
            self.assertNotIn(b"hunter2", zstd.decompress(path.read_bytes()))

    def test_a_secret_ended_without_an_answer_is_not_an_answer(self):
        # Annulée par la page ou au terminal, ou finie à l'échéance : ni
        # un secret ni une autre question ne s'y lit comme répondue.
        self.start()
        asks = [
            (2, "secret", {"t": "cancel"}, {}),
            (3, "secret", None, {"end": "cancel"}),
            (4, "secret", None, {"end": "timeout"}),
            (5, "countdown", None, {"end": "timeout"}),
            (6, "secret", None, {}),
        ]
        for qid, kind, reply, end in asks:
            ask = {"t": "ask", "qid": qid, "kind": kind, "text": "Key: "}
            self.rec.worker(ask)
            if reply is not None:
                self.rec.page(dict(reply, qid=qid))
            self.rec.worker({"t": "answered", "qid": qid, **end})
        self.rec.end()
        ends = [d for s, d in self.records()[1] if d["t"] != "ask"]
        self.assertEqual(
            ends,
            [
                {"t": "cancel"},
                {"t": "cancel"},
                {"t": "timeout"},
                {"t": "timeout"},
                {"t": "answer", "value": "•••"},
            ],
        )

    def test_a_long_notice_is_masked_whole_then_cut(self):
        # Coupée d'abord, « Password: » perdrait son début et le secret
        # qui le suit passerait.
        self.start()
        text = "Password: hunter2 " + "x" * 4082
        self.assertEqual(len(text), 4100)
        for kind in ("notice", "ask"):
            self.rec.worker({"t": kind, "qid": 2, "text": text})
        self.rec.end()
        texts = [d["text"] for s, d in self.records()[1]]
        self.assertEqual(texts, ["Password: ***", "Password: ***"])
        for path in self.base.rglob("*.zst"):
            self.assertNotIn(b"hunter2", zstd.decompress(path.read_bytes()))

    def test_a_failing_disk_drops_the_task_not_the_session(self):
        self.start()
        self.rec.output(b"working\r\n")
        full = OSError(28, "No space left on device")
        with (
            patch.object(tasklog.TaskLog, "close", side_effect=full),
            self.assertLogs(tasklog.log, "ERROR"),
        ):
            self.menu(2)
            self.rec.output(SHOWN)
        self.assertIsNone(self.rec.task)
        self.start()  # la session continue, et sa tâche suivante
        self.assertIsNotNone(self.rec.task)
        # Le journal abandonné reste, que le démarrage suivant reprend.
        self.assertEqual(tasklog.recover(self.base), 1)


if __name__ == "__main__":
    unittest.main()
