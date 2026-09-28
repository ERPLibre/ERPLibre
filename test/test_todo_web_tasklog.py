#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Journaux de tâches du hub web : écriture, clôture, relecture, purge et
reprise, puis les bornes d'une tâche lues des messages du canal
(`Recorder`), sur un HOME temporaire. Les secrets sont inventés."""

import contextlib
import datetime
import errno
import json
import os
import random
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

    def kept(self, chunks, event=None, **patches):
        """`chunks` reçus un à un, `event` entre deux s'il est donné, sous
        `patches` (attributs de tasklog), puis la tâche close : ses
        enregistrements, task_start excepté, et son journal compressé,
        décompressé."""
        task = self.task()
        guard = patch.multiple(tasklog, **patches) if patches else None
        with guard or contextlib.nullcontext():
            for at, chunk in enumerate(chunks):
                if at and event is not None:
                    task.event(event)
                task.output(chunk)
            task.close("done")
        page = tasklog.read(self.base, task.info["id"], 2, 1000)
        records = [(r["s"], r["d"]) for r in page["lines"]]
        packed = task.path.with_name(task.path.name + ".zst")
        return records, zstd.decompress(packed.read_bytes())


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
            "Password ***",
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
                "q" * (width - 11) + " Password ***",
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
                "y" * 30 + " Password ***",
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
                "a b Password ***",
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
            ([y + b" Pa", b"ssword: inventeEF", b"\r\n"], "Password ***"),
            ([y + b" --pa", b"ssword inventeGH", b"\r\n"], "--password ***"),
            (
                [y + b" Au", b"thorization: Bearer inventeIJ", b"\r\n"],
                "Authorization ***",
            ),
            ([y + b" Pa", b"ssword: inventeKL\r", b"\n"], "Password ***"),
            (
                [y + b" Pa\x1b[0m", b"ssword: inventeMN", b"\r\n"],
                "Password ***",
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
        self.assertEqual(texts, ["y" * 33 + " ", "mot de passe ***"])
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
        # Après la clôture, une sortie ou un événement ne recrée aucun
        # `.log`, que rien ne clorait plus.
        task = self.task()
        task.output(b"once\r\n")
        entry = task.close("done")
        task.output(b"late\r\n")
        task.event({"t": "run_start", "cmd": "late"})
        self.assertFalse(task.path.exists())
        self.assertIs(task.close("interrupted"), entry)
        self.assertEqual(tasklog.entries(self.base), [entry])
        self.assertEqual(self.texts(entry["id"]), ["once"])
        self.assertEqual(
            sorted(path.name for path in task.path.parent.iterdir()),
            [task.path.name + ".zst", "index.jsonl"],
        )

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
            (b"x pa", b"ssword: hunter2\r\n", ("x pa", "ssword ***")),
            (b"mot de ", b"passe : hunter2\r\n", ("mot de ", "passe ***")),
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
                    whole = "Database password ***"
                    expected = [event, ("out", whole)]
                else:
                    expected = [("out", split[0]), event, ("out", split[1])]
                self.assertEqual(self.records(task), expected)
                packed = task.path.with_name(task.path.name + ".zst")
                data = zstd.decompress(packed.read_bytes())
                self.assertNotIn(b"hunter2", data)

    def test_a_rewritten_line_after_an_event_is_masked_alone(self):
        # Le début déjà écrit devant un événement ne précède pas toujours
        # la suite : un retour chariot ou un effacement ANSI réécrit la
        # ligne, et la version gardée se lit seule. Elle se masque seule
        # comme derrière ce début, avec ou sans événement entre les deux.
        cases = (
            (b"Loading", b"\rpassword: hunter2\r\n", "password ***"),
            (b"Loading", b"\rtoken: hunter2\r\n", "token ***"),
            (
                b"Loading",
                b"\r\x1b[2Kpassword: hunter2\r\n",
                "password ***",
            ),
            (b"50", b"\rsecret=hunter2\r\n", "secret ***"),
            (b"Loading", b"\rpasswd hunter2\r\n", "passwd ***"),
            (
                b"Loading",
                b"\rmot de passe : hunter2\r\n",
                "mot de passe ***",
            ),
        )
        event = {"t": "answered"}
        for before, after, masked in cases:
            for between in ([event], []):
                with self.subTest(after=after, event=bool(between)):
                    task = self.task()
                    task.output(before)
                    for data in between:
                        task.event(data)
                    task.output(after)
                    task.close("done")
                    if between:
                        expected = [
                            ("out", before.decode()),
                            ("event", event),
                            ("out", masked),
                        ]
                    else:
                        expected = [("out", masked)]
                    self.assertEqual(self.records(task), expected)
                    packed = task.path.with_name(task.path.name + ".zst")
                    data = zstd.decompress(packed.read_bytes())
                    self.assertNotIn(b"hunter2", data)

    def test_an_unfinished_line_is_read_once_whatever_the_events(self):
        # Une ligne inachevée que `flush` refuse, parce qu'elle porte un
        # mot guetté, ne montre rien ou finit dans une séquence
        # d'échappement inachevée (un titre OSC), ne se relit pas à chaque
        # événement : ce qui en est lu ne croît pas avec leur nombre. Une
        # version nouvelle de la ligne (retour chariot) se lit de nouveau ;
        # celle qu'elle remplace portait-elle un mot guetté, la ligne
        # s'écrit entière en « *** » après l'événement.
        read = []

        def counted(function):
            def wrapper(text, *args):
                read.append(len(text))
                return function(text, *args)

            return wrapper

        event = {"t": "run_end", "rc": 0, "secs": 1}
        ready = [("out", "ready"), ("event", event)]
        masked = [("event", event), ("out", "***")]
        for partial, end in (
            (b"Database password: " + b"x" * 65536, masked),
            (b" " * 65536, ready),
            (b"\x1b]0;" + b"t " * 32768, ready),
        ):
            with self.subTest(partial=partial[:10]):
                task = self.task()
                read.clear()
                with patch.multiple(
                    tasklog,
                    _at_risk=counted(tasklog._at_risk),
                    _screen=counted(tasklog._screen),
                    _unfinished=counted(tasklog._unfinished),
                ):
                    task.output(partial)
                    task.event(event)
                    once = sum(read)
                    for _ in range(60):
                        task.event(event)
                    self.assertEqual(sum(read), once)
                    self.assertLessEqual(once, 4 * len(partial))
                    task.output(b"\rready")
                    task.event(event)
                    task.close("done")
                self.assertEqual(
                    self.records(task), [("event", event)] * 61 + end
                )

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
                ("out", "ssword ***"),
            ],
        )
        packed = task.path.with_name(task.path.name + ".zst")
        self.assertNotIn(b"hunter2", zstd.decompress(packed.read_bytes()))

    def test_an_event_inside_an_escape_sequence_holds_the_line(self):
        # Une ligne inachevée qui finit dans une séquence d'échappement
        # (ESC seul, CSI sans octet final) ne s'écrit pas devant
        # l'événement : sa suite, lue seule, collerait « [32m » ou « K » à
        # l'étiquette, que plus rien ne reconnaîtrait. La ligne s'écrit
        # entière après lui, sous le plafond comme au-delà, où
        # l'événement retenu prend la même place à la clôture.
        cases = (
            (
                b"abc \x1b",
                b"[32mpasswd\x1b[0m zqwsecret\n",
                "abc passwd ***",
            ),
            (
                b"Loading\r\x1b[2",
                b"KMot de passe : zqwsecret\r\n",
                "Mot de passe ***",
            ),
            (
                b"Loading\r\x1b[2",
                b"KPassword for user x: zqwsecret\r\n",
                "Password ***",
            ),
        )
        event = {"t": "answered"}
        head = b"x" * 20 + b"\r\n"
        for before, after, masked in cases:
            for between, cap in (
                (True, tasklog.CAP),
                (False, tasklog.CAP),
                (True, 8),
                (False, 8),
            ):
                with self.subTest(after=after, event=between, cap=cap):
                    task = self.task()
                    with patch.object(tasklog, "CAP", cap):
                        task.output(head)
                        task.output(before)
                        if between:
                            task.event(event)
                        task.output(after)
                        task.close("done")
                    if cap == 8:
                        first = ("event", {"t": "omitted", "bytes": 22})
                    else:
                        first = ("out", "x" * 20)
                    expected = [first, ("out", masked)]
                    if between:
                        expected.insert(1, ("event", event))
                    self.assertEqual(self.records(task), expected)
                    packed = task.path.with_name(task.path.name + ".zst")
                    data = zstd.decompress(packed.read_bytes())
                    self.assertNotIn(b"zqwsecret", data)

    def test_an_unfinished_escape_sequence_is_never_complete(self):
        # ESC seul ou suivi d'intermédiaires, CSI sans octet final, chaîne
        # OSC ou DCS sans terminateur, ou dont seul l'ESC du ST est venu :
        # la suite peut encore l'achever, et `flush` refuse la ligne qui
        # finit ainsi. ANSI ne lit jamais « \x1b[ » comme une séquence de
        # deux octets : il laisse entier ce qu'il ne sait pas achevé.
        for partial in (
            b"abc \x1b",
            b"abc \x1b[",
            b"abc \x1b[2",
            b"abc \x1b[1;3",
            b"abc \x1b[1 ",
            b"abc \x1b(",
            b"abc \x1b]0;t i",
            b"abc \x1bPq x",
            b"abc \x1b]0;t\x1b",
        ):
            with self.subTest(partial=partial):
                lines = tasklog.Lines()
                lines.feed(partial)
                self.assertEqual(lines.flush(), "")
        for partial in (
            b"abc \x1b[0m",
            b"abc \x1b]0;t i\x07",
            b"abc \x1b]0;t\x1b\\",
            b"abc \x1b(B",
        ):
            with self.subTest(partial=partial):
                lines = tasklog.Lines()
                lines.feed(partial)
                self.assertEqual(lines.flush(), "abc ")
        for sequence in ("\x1b[", "\x1b[2", "\x1b[1;3", "\x1b[1 ", "\x1b("):
            with self.subTest(sequence=sequence):
                self.assertEqual(tasklog.ANSI.sub("", sequence), sequence)

    def test_a_return_to_column_one_or_an_erase_rewrites_the_line(self):
        # Le curseur ramené en colonne 1 (CSI G, 0G, 1G) ou la ligne
        # effacée jusqu'au curseur ou entière (CSI 1K, 2K) réécrit la
        # ligne comme un retour chariot : seule la dernière version qui
        # montre quelque chose reste, et se masque seule. CSI K n'efface
        # que ce qui suit le curseur : rien de ce qui est gardé. La
        # couleur ne change rien au texte ; un titre OSC resté ouvert
        # finit devant la réécriture qui le suit.
        for line, shown in (
            ("Loading\x1b[1G\x1b[2Kpasswd zqwsecret", "passwd zqwsecret"),
            ("Loading\x1b[Gready", "ready"),
            ("Loading\x1b[0Gready", "ready"),
            ("Loading\x1b[1Gready", "ready"),
            ("Loading\x1b[2K\rready", "ready"),
            ("Loading\r\x1b[2Kready", "ready"),
            ("Loading\x1b[2Kready", "ready"),
            ("Loading\x1b[1Kready", "ready"),
            ("Loading\x1b[1G\x1b[Kready", "ready"),
            ("Loading\r\x1b[Kready", "ready"),
            ("\x1b[Kready", "ready"),
            ("Loading\x1b[K ready", "Loading ready"),
            ("Loading\x1b[12Gready", "Loadingready"),
            ("Loading\x1b[1G\x07", "Loading"),
            ("\x1b]0;title\x1b[2Kready", "ready"),
            ("\x1b]0;t i\x1b[1Gready", "ready"),
            ("\x1b[1;32mgreen\x1b[0m text", "green text"),
            ("a\x1b[32mb\x1b[0mc \x1b[4mu\x1b[24m", "abc u"),
        ):
            with self.subTest(line=line):
                self.assertEqual(tasklog.clean(line), shown)
        for data, masked in (
            (b"Loading\x1b[1G\x1b[2Kpasswd zqwsecret\r\n", "passwd ***"),
            (b"Loading\x1b[2Kpasswd zqwsecret\r\n", "passwd ***"),
            (b"50%\x1b[0Gmot de passe : zqwsecret\n", "mot de passe ***"),
        ):
            with self.subTest(data=data):
                task = self.task()
                task.output(data)
                task.close("done")
                self.assertEqual(self.records(task), [("out", masked)])
                packed = task.path.with_name(task.path.name + ".zst")
                data = zstd.decompress(packed.read_bytes())
                self.assertNotIn(b"zqwsecret", data)

    def test_a_cut_never_falls_inside_an_escape_sequence(self):
        # Un blanc peut être le texte d'une chaîne OSC ou DCS (un titre),
        # ou un octet intermédiaire d'une séquence : PARTIAL_LIMIT n'y
        # coupe jamais, pas plus que dans une séquence que la suite peut
        # encore achever. Chaque ligne arrive octet par octet ; mises bout
        # à bout, ses lignes gardées valent la ligne entière masquée.
        for data in (
            b"\x1b]0;a b c d e f\x07passwd zqwsecret\r\n",
            b"\x1b]0;t i t l e\x07mot de passe : zqwsecret\r\n",
            b"\x1b]0;a b c d e f\x1b\\passwd zqwsecret\r\n",
            b"\x1bPq a b c d e f\x1b\\token: zqwsecret\r\n",
            b"a b c d e \x1b[1   qpasswd zqwsecret\r\n",
            b"a b c d e f \x1b   Fpasswd zqwsecret\r\n",
        ):
            with self.subTest(data=data):
                task = self.task()
                with patch.object(tasklog, "PARTIAL_LIMIT", 15):
                    for byte in data:
                        task.output(bytes([byte]))
                    task.close("done")
                whole = tasklog._redact(tasklog.clean(data.decode()[:-2]))
                self.assertIn("***", whole)
                texts = self.texts(task.info["id"])
                self.assertEqual("".join(texts), whole)
                packed = task.path.with_name(task.path.name + ".zst")
                data = zstd.decompress(packed.read_bytes())
                self.assertNotIn(b"zqwsecret", data)

    def test_no_split_of_a_decorated_secret_line_keeps_its_value(self):
        # Fuzz déterministe : des lignes qui impriment une valeur inventée
        # derrière une étiquette, sous la forme d'un mot ou d'une clé,
        # précédées d'un retour chariot, d'un effacement, d'un retour en
        # colonne 1, d'une couleur, d'un titre OSC, d'un mot collé, d'un
        # déplacement du curseur (recul, origine, sauvegarde et reprise,
        # retours arrière, CSI en C1), d'une CSI avortée ou d'un retour
        # chariot dans un titre ; l'étiquette elle-même en couleur, suivie
        # d'un effacement, d'un titre, d'un retour chariot ou d'un retour
        # en colonne 1 qui la sépare de sa valeur (deux de ces habillages,
        # tirés d'une graine fixe, par forme et par début). Chacune arrive
        # coupée en deux à chaque position, puis en trois à des positions
        # tirées, un événement entre les morceaux ou non ; puis octet par
        # octet, PARTIAL_LIMIT tiré, un événement après des octets tirés.
        # Le .zst décompressé ne garde jamais la valeur.
        value = "inventeWX"
        forms = (
            ("passwd", " "),
            ("password", " "),
            ("Password for user x", ": "),
            ("mot de passe", " : "),
            ("token", ": "),
            ("accessToken", "="),
            ("-token", " = "),
            ("x-ypasswd", " = "),
            ("Authorization: Bearer", " "),
            ("API key", ": "),
            ("Paſſphrase", ": "),
        )
        befores = (
            "",
            "Loading\r",
            "Loading\r\x1b[K",
            "Loading\x1b[2K\r",
            "Loading\r\x1b[2K",
            "Loading\x1b[1G",
            "Loading\x1b[1G\x1b[2K",
            "Loading\x1b[2K",
            "Loading\x1b[2K\x1b[0G",
            "\x1b[K",
            "\x1b[1;32m",
            "\x1b]0;a b c\x07",
            "Loading \x1b]2;t i t l e\x1b\\",
            "Loading",
            "x-y",
            "Loading\x1b[1000D",
            "Loading\x1b[H",
            "\x1b7Loading\x1b8",
            "Loading\b\b\b\b\b\b\b",
            "Loading\x9b2K",
            "\x1b[2\x1b[0m",
            "Loading\x1b[?2K",
            "\x1b]0;a\rb\x07",
        )
        arounds = (
            "{}",
            "\x1b[1;32m{}\x1b[0m",
            "{}\x1b[K",
            "{}\x1b]0;x y\x07",
            "{}\x1b[2K",
            "{}\r",
            "{}\x1b[1G",
        )
        rng = random.Random(6)
        for label, sep in forms:
            cases, bytewise = [], []
            for before in befores:
                for around in rng.sample(arounds, 2):
                    line = before + around.format(label) + sep + value
                    data = (line + rng.choice(("\r\n", "\x1b[0m\n"))).encode()
                    for at in range(1, len(data)):
                        for event in (True, False):
                            cases.append(([data[:at], data[at:]], event))
                    for _ in range(6):
                        one, two = sorted(rng.sample(range(1, len(data)), 2))
                        chunks = [data[:one], data[one:two], data[two:]]
                        cases.append((chunks, rng.random() < 0.75))
                    events = {
                        at for at in range(len(data)) if rng.random() < 0.2
                    }
                    bytewise.append(([bytes([b]) for b in data], events))
            with self.subTest(label=label):
                self.assertIsNone(self.leak(cases, value))
            for limit in (4, 8, 15):
                with self.subTest(label=label, limit=limit):
                    with patch.object(tasklog, "PARTIAL_LIMIT", limit):
                        self.assertIsNone(self.leak(bytewise, value))

    def leak(self, cases, value):
        """Le premier cas de `cases` dont le .zst garde `value`, ou None.
        Un cas : `(morceaux, événement)`, un événement entre deux morceaux
        si `événement` est vrai, ou devant chaque morceau dont il tient
        l'indice si c'est un ensemble. Chaque ligne finit : les cas passent
        par une seule tâche, puis, si elle garde `value`, chacun par une
        tâche à lui."""
        event = {"t": "answered"}

        def kept(group):
            task = self.task()
            for chunks, between in group:
                for at, chunk in enumerate(chunks):
                    if at and (
                        at in between if isinstance(between, set) else between
                    ):
                        task.event(event)
                    task.output(chunk)
            task.close("done")
            packed = task.path.with_name(task.path.name + ".zst")
            return value.encode() in zstd.decompress(packed.read_bytes())

        if not kept(cases):
            return None
        return next(case for case in cases if kept([case]))

    def test_escape_sequences_are_read_in_linear_time(self):
        # Le hub nettoie et coupe chaque ligne dans sa boucle, que les
        # autres sessions attendent : 64 Kio faits de séquences, entières
        # ou inachevées, se nettoient, se coupent et se relisent chacun en
        # moins de 50 ms, jamais en un temps au carré de leur longueur.
        size = 64 * 1024
        for line in (
            "\x1b" * size,
            "\x1b[" * (size // 2),
            "\x1b]" * (size // 2),
            "\x1b[2K" * (size // 4),
            "\x1b[1G" * (size // 4),
            "\r\x1b[2" * (size // 4),
            "\x1b]0;t\x1b" * (size // 6),
            "\x1b]0;" + "a " * (size // 2),
            "\x1b[" + "1" * size,
            "\x1b[1" + " " * size + "x",
            "\x1b" + " " * size,
            "\x1b" + " " * size + "\x1b",
            "a \x1b[1 " * (size // 7),
            "a \x1b]0;b c\x07" * (size // 11),
        ):
            data = line.encode()
            whole, chunked = tasklog.Lines(), tasklog.Lines()
            whole.feed(data)

            def by_chunks():
                with patch.object(tasklog, "PARTIAL_LIMIT", 1024):
                    for at in range(0, len(data), 256):
                        chunked.feed(data[at : at + 256])

            for step, run in (
                ("clean", lambda: tasklog.clean(line)),
                ("cut", lambda: tasklog._cut(line)),
                ("flush", whole.flush),
                ("chunks", by_chunks),
            ):
                with self.subTest(line=line[:12], step=step):
                    debut = time.monotonic()
                    run()
                    self.assertLess(time.monotonic() - debut, 0.05)

    def test_a_secret_word_taints_the_rest_of_its_line(self):
        # Un mot guetté masque la fin de sa ligne où qu'il tombe : collé au
        # mot qui le précède, derrière un déplacement du curseur que la
        # ligne gardée ne rejoue pas, une CSI avortée ou une C1, ou derrière
        # un tiret. Ce qui le précède reste. Une ligne dont casefold change
        # la longueur ne situe pas son mot : elle part entière.
        for data, masked in (
            (b"Loadingpasswd inventeWX", "Loadingpasswd ***"),
            (b"LoadingPassword for user x: inventeWX", "LoadingPassword ***"),
            (b"Loadingmot de passe : inventeWX", "Loadingmot de passe ***"),
            (b"x-ymot de passe: inventeWX", "x-ymot de passe ***"),
            (b"\xc3\xa9tapeMot de passe: inventeWX", "étapeMot de passe ***"),
            (
                b"Loading\x1b[1;32mMot de passe\x1b[0m: inventeWX",
                "LoadingMot de passe ***",
            ),
            (
                b"LoadingAuthorization: Bearer inventeWX",
                "LoadingAuthorization ***",
            ),
            (b"Loading\x1b[1000Dpasswd inventeWX", "Loadingpasswd ***"),
            (b"Loading\x1b[7Dpasswd inventeWX", "Loadingpasswd ***"),
            (b"Loading\x1b[Hpasswd inventeWX", "Loadingpasswd ***"),
            (b"Loading\x1b[2J\x1b[Hpasswd inventeWX", "Loadingpasswd ***"),
            (b"\x1b7Loading\x1b8passwd inventeWX", "Loadingpasswd ***"),
            (b"\x1b[sLoading\x1b[upasswd inventeWX", "Loadingpasswd ***"),
            (
                b"Loading" + b"\b" * 7 + b"passwd inventeWX",
                "Loadingpasswd ***",
            ),
            (b"Loading\xc2\x9b2Kpasswd inventeWX", "Loading2Kpasswd ***"),
            (b"Loading\x1b[?2Kpasswd inventeWX", "Loadingpasswd ***"),
            (b"Loading\x1bEpasswd inventeWX", "Loadingpasswd ***"),
            (b"Loading\x1b[Kpasswd inventeWX", "Loadingpasswd ***"),
            (b"\x1b[2\x1b[0mpasswd inventeWX", "[2passwd ***"),
            (b"-token = inventeWX", "-token ***"),
            (b"x-ypasswd = inventeWX", "x-ypasswd ***"),
            (b"my-secret: inventeWX", "my-secret ***"),
            (b"LoadingPGPASSWORD=inventeWX", "LoadingPGPASSWORD ***"),
            (b"abaccessToken=inventeWX", "abaccessToken ***"),
            (b"API key: inventeWX", "API key ***"),
            (b"Bearer inventeWX", "Bearer ***"),
            (b"Pa\xc5\xbf\xc5\xbfphrase: inventeWX", "Paſſphrase ***"),
            (b"Stra\xc3\x9fe token: inventeWX", "***"),
        ):
            with self.subTest(data=data):
                records, packed = self.kept([data + b"\r\n"])
                self.assertEqual(records, [("out", masked)])
                self.assertNotIn(b"invente", packed)

    def test_a_secret_word_in_a_replaced_version_masks_the_line(self):
        # La valeur peut s'écrire seule par-dessus son étiquette : retour
        # chariot, retour en colonne 1 ou effacement entre les deux. Une
        # version remplacée qui portait un mot guetté masque la ligne
        # entière, même quand un morceau reçu plus tôt l'a déjà retirée de
        # la ligne en cours, qu'un événement la suive, qu'elle passe
        # PARTIAL_LIMIT ou le plafond.
        event = {"t": "answered"}
        pad = b" a b c d e" * 4
        for chunks, patches in (
            ([b"Password: \x1b[2KinventeWX\r\n"], {}),
            ([b"password: \x1b[1GinventeWX\r\n"], {}),
            ([b"password: \rinventeWX\r\n"], {}),
            ([b"Password: \rinve", b"nteWX\r\n"], {}),
            ([b"Password: ", b"\rinve", b"nteWX\r\n"], {}),
            (
                [b"Password: \r" + pad, b" inventeWX\r\n"],
                {"PARTIAL_LIMIT": 20},
            ),
            (
                [b"Password: \rx" + pad, b" inventeWX\r\n"],
                {"PARTIAL_LIMIT": 20},
            ),
            ([b"\x1b]0;token\rinve", b"nteWX\x07 done\r\n"], {}),
        ):
            for between in (None, event):
                with self.subTest(chunks=chunks, event=bool(between)):
                    records, packed = self.kept(chunks, between, **patches)
                    events = [("event", event)] * (len(chunks) - 1)
                    expected = [*events, ("out", "***")] if between else []
                    self.assertEqual(records, expected or [("out", "***")])
                    for piece in (b"inve", b"nteWX"):
                        self.assertNotIn(piece, packed)

    def test_a_carriage_return_inside_a_split_title_hides_nothing(self):
        # Un retour chariot dans une chaîne OSC que la suite achève dans un
        # autre morceau : la version gardée porte le mot guetté.
        records, packed = self.kept(
            [b"\x1b]0;a\rb", b"c\x07passwd inventeWX\r\n"]
        )
        self.assertEqual(records, [("out", "bcpasswd ***")])
        self.assertNotIn(b"invente", packed)

    def test_a_line_without_a_secret_word_is_stored_unchanged(self):
        # Ni « pass », ni « pwd », ni « auth » seuls, ni un mot qui ne fait
        # que ressembler à un mot guetté : la ligne s'écrit telle quelle,
        # d'un bloc ou coupée par un événement à chaque position.
        event = {"t": "answered"}
        for line in (
            "Tests passed: 12",
            "pwd",
            "author: x",
            "passport number 12",
            "bypass mode on",
            "Passports: 3 checked",
            "authentication done",
            "keyboard: us",
            "Loading 50% done",
        ):
            with self.subTest(line=line):
                data = (line + "\r\n").encode()
                records, _ = self.kept([data])
                self.assertEqual(records, [("out", line)])
                for at in range(1, len(data) - 2):
                    records, _ = self.kept([data[:at], data[at:]], event)
                    texts = "".join(d for s, d in records if s == "out")
                    self.assertEqual(texts, line)

    def test_a_cut_never_lets_the_rest_of_a_secret_line_through(self):
        # PARTIAL_LIMIT ne coupe pas une ligne qui porte un mot guetté,
        # d'un bloc, octet par octet, un événement entre les morceaux ou
        # non : ce qui suit le mot ne s'écrit jamais en clair.
        event = {"t": "answered"}
        for line in (
            b"x" * 30 + b" a b password: inventeWX y z w",
            b"x" * 30 + b" a b Loadingtoken = inventeWX y z w",
            b"a b c d e f g h i j k l m secret inventeWX n o p",
        ):
            data = line + b"\r\n"
            for chunks in ([data], [bytes([b]) for b in data]):
                for between in (None, event):
                    with self.subTest(line=line, n=len(chunks), ev=between):
                        records, packed = self.kept(
                            chunks, between, PARTIAL_LIMIT=12
                        )
                        self.assertNotIn(b"invente", packed)
                        self.assertIn("***", records[-1][1])

    def test_the_minimal_leaking_splits_keep_no_value(self):
        # Les lignes où une coupure en deux ou trois morceaux, un
        # événement entre chacun, laissait passer la valeur : aucune ne la
        # garde plus, quelle que soit la coupure.
        value = b"inventeWX"
        event = {"t": "answered"}
        for line in (
            b"x-ypasswd = " + value,
            b" x-ypasswd = " + value,
            b"x-y\x1b[1mpasswd\x1b[0m = " + value,
            b"abpasswd = " + value,
            b"ab_passwd = " + value,
            b"abpassword: " + value,
            b"x-ytoken: " + value,
            b"x-ymot de passe : " + value,
            b"LoadingPGPASSWORD=" + value,
            b"abaccessToken=" + value,
            b"my-secret: " + value,
            b"--db-password=" + value,
        ):
            data = line + b"\r\n"
            cases = []
            for one in range(1, len(data)):
                cases.append(([data[:one], data[one:]], True))
                for two in range(one + 1, len(data), 3):
                    chunks = [data[:one], data[one:two], data[two:]]
                    cases.append((chunks, True))
            with self.subTest(line=line):
                self.assertIsNone(self.leak(cases, value.decode()))

    def test_an_event_text_or_a_command_keeps_nothing_after_a_secret_word(
        self,
    ):
        # Le texte d'un avis ou d'une question et une commande suivent la
        # même règle que la sortie : lus sans séquence d'échappement, une
        # version remplacée comprise, ils ne gardent rien après un mot
        # guetté ; l'index non plus.
        rec = tasklog.Recorder(self.base, "s1")
        rec.worker(dict(MENU, qid=1))
        rec.worker({"t": "answered", "qid": 1, "key": "1"})
        for message in (
            {
                "t": "notice",
                "level": "info",
                "text": "Loadingpasswd inventeWX",
            },
            {
                "t": "notice",
                "level": "info",
                "text": "Password: \x1b[2KinventeWX",
            },
            {
                "t": "ask",
                "qid": 2,
                "kind": "text",
                "text": "\x1b[1mToken\x1b[0m: inventeWX\nNext: ",
            },
            {"t": "run_start", "cmd": "tool -token = inventeWX"},
        ):
            rec.worker(message)
        rec.end()
        [entry] = tasklog.entries(self.base)
        page = tasklog.read(self.base, entry["id"], 2, 100)
        texts = [r["d"].get("text", r["d"].get("cmd")) for r in page["lines"]]
        self.assertEqual(
            texts,
            [
                "Loadingpasswd ***",
                "***",
                "Token ***\nNext: ",
                "tool -token ***",
            ],
        )
        self.assertEqual(entry["commands"][0]["cmd"], "tool -token ***")
        self.assertNotIn("invente", json.dumps(entry))
        for path in self.base.rglob("*.zst"):
            self.assertNotIn(b"invente", zstd.decompress(path.read_bytes()))

    def test_the_secret_word_scan_is_linear(self):
        # Chaque ligne gardée se lit une fois par mot guetté, sans casse
        # et sans borne de mot : 64 Kio faits de mots guettés, de leurs
        # débuts, de versions ou de blancs s'écrivent en quelques dizaines
        # de millisecondes.
        size = 64 * 1024
        for line in (
            "password" * (size // 8),
            "passw" * (size // 5),
            "mot de pass" * (size // 11),
            "api ke" * (size // 6),
            "Password: \r" * (size // 11),
            "Password: \x1b[2K" * (size // 14),
            "tokenx " * (size // 7),
            " " * size + "token x",
            "\b" * size + "passwd x",
            "\x1b[1000D" * (size // 7) + "passwd x",
            "ß" * size + "token x",
        ):
            data = (line + "\r\n").encode()
            with self.subTest(line=line[:12]):
                task = self.task()
                debut = time.monotonic()
                task.output(data)
                task.close("done")
                self.assertLess(time.monotonic() - debut, 0.1)

    def test_clean_and_cut_make_no_call_per_sequence(self):
        # Nettoyer ou couper une ligne ne rappelle aucune fonction Python
        # par séquence d'échappement : 1 Mio de séquences denses se lit en
        # quelques dizaines de millisecondes.
        size = 1024 * 1024
        for line in (
            "\x1b]" * (size // 2),
            "\x1b[2K" * (size // 4),
            "\x1b[0m" * (size // 4),
            "\x1b[1G" * (size // 4),
            "a \x1b[1 " * (size // 7),
            "a \x1b]0;b c\x07 d\x1b[2K e\x1b[1G " * (size // 30),
            "x\r" * (size // 2),
            "\r\x1b[2" * (size // 4),
        ):
            for step, run in (
                ("clean", lambda: tasklog.clean(line)),
                ("cut", lambda: tasklog._cut(line)),
            ):
                with self.subTest(line=line[:12], step=step):
                    debut = time.monotonic()
                    run()
                    self.assertLess(time.monotonic() - debut, 0.1)

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

    def test_a_command_keeps_nothing_after_a_secret_word(self):
        # Une commande ne garde rien après son premier mot guetté, option
        # ou « password= » sans tiret ; sans mot guetté, le masque de
        # l'affichage y cache encore un identifiant d'URL ou MASTER_PWD. Un
        # mot guetté dans une valeur que ce masque cache la fait partir
        # entière.
        self.start()
        runs = (
            (
                "mysql --password inventeAB -h db.example base",
                "mysql --password ***",
            ),
            (
                'psql "host=db.example password=hunter2" base',
                'psql "host=db.example password ***',
            ),
            (
                "git clone https://u:inventeCD@forge.example/r",
                "git clone https://u:***@forge.example/r",
            ),
            ("MASTER_PWD=inventeEF odoo", "MASTER_PWD='***' odoo"),
            ("MASTER_PWD=secretGH odoo", "***"),
        )
        for run, _ in runs:
            self.rec.worker({"t": "run_start", "cmd": run})
        self.rec.end()
        entry, records = self.records()
        shown = [masked for _, masked in runs]
        self.assertEqual([c["cmd"] for c in entry["commands"]], shown)
        self.assertEqual(
            records, [("event", {"t": "run_start", "cmd": c}) for c in shown]
        )
        for secret in ("invente", "hunter2"):
            self.assertNotIn(secret, repr(entry))
            self.assertNotIn(secret, repr(records))

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
        self.assertEqual(texts, ["Password ***", "Password ***"])
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
