#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import hashlib
import json
import os
import stat
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from script.todo.mail.rules import storage
from script.todo.mail.rules.lock import file_lock
from script.todo.mail.rules.model import (
    MAX_IMAGE_BYTES,
    Armed,
    MediaRef,
    RuleError,
    RulesBusy,
    new_rule,
)
from script.todo.mail.rules.storage import EngineState

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def mode_of(path: Path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


class StorageCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name) / "mail"
        self.src = Path(self._tmp.name) / "src"
        self.src.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def image(self, name: str, data: bytes = PNG) -> Path:
        path = self.src / name
        path.write_bytes(data)
        return path

    def add(self, name="Absence", account="perso"):
        rule = new_rule("reply", name)
        storage.upsert_rule(account, rule, base=self.base)
        return rule


class TestLayout(StorageCase):
    """Un dossier privé par compte, sous `.rules`."""

    def test_files_are_0600_and_folders_0700(self):
        self.add()
        storage.save_state("perso", EngineState(cursor=3), base=self.base)
        folder = self.base / ".rules" / "perso"
        self.assertEqual(mode_of(self.base / ".rules"), 0o700)
        self.assertEqual(mode_of(folder), 0o700)
        self.assertEqual(mode_of(folder / "rules.json"), 0o600)
        self.assertEqual(mode_of(folder / "state.json"), 0o600)
        self.assertEqual(mode_of(folder / "lock"), 0o600)
        self.assertEqual(mode_of(storage.media_dir("perso", self.base)), 0o700)

    def test_paths_live_under_dot_rules_per_account(self):
        self.assertEqual(
            storage.rules_path("perso", self.base),
            self.base / ".rules" / "perso" / "rules.json",
        )
        self.assertEqual(
            storage.state_path("perso", self.base),
            self.base / ".rules" / "perso" / "state.json",
        )
        self.assertEqual(
            storage.lock_path("perso", self.base),
            self.base / ".rules" / "perso" / "lock",
        )
        self.assertEqual(
            storage.media_dir("perso", self.base),
            self.base / ".rules" / "perso" / "media",
        )

    def test_accounts_perso_and_perso_state_share_no_file(self):
        paths = {}
        for account in ("perso", "perso.state"):
            paths[account] = {
                storage.rules_path(account, self.base),
                storage.state_path(account, self.base),
                storage.lock_path(account, self.base),
                storage.media_dir(account, self.base),
            }
        self.assertEqual(paths["perso"] & paths["perso.state"], set())
        self.add("Une", "perso")
        storage.save_state(
            "perso.state", EngineState(cursor=9), base=self.base
        )
        self.assertEqual(len(storage.load("perso", base=self.base)), 1)
        self.assertEqual(
            storage.load_state("perso", base=self.base).cursor, None
        )

    def test_account_name_escaping_the_folder_is_refused(self):
        for name in ("", "../x", ".rules", "a/b"):
            with self.subTest(name=name):
                with self.assertRaises(RuleError):
                    storage.rules_path(name, self.base)

    def test_reads_create_nothing(self):
        self.assertEqual(storage.load("perso", base=self.base), [])
        self.assertEqual(
            storage.load_state("perso", base=self.base), EngineState()
        )
        self.assertFalse(self.base.exists())

    def test_symlinked_account_folder_is_refused(self):
        target = Path(self._tmp.name) / "ailleurs"
        target.mkdir()
        storage.rules_dir(self.base)
        (self.base / ".rules" / "perso").symlink_to(target)
        with self.assertRaises(RuleError):
            storage.rules_path("perso", self.base)


class TestBaseOf(unittest.TestCase):
    """La base des règles vient du cache, jamais d'un chemin en dur."""

    def test_clear_cache_gives_the_parent_of_its_root(self):
        store = SimpleNamespace(mode="clear", root=Path("/x/mail/perso"))
        self.assertEqual(storage.base_of(store), Path("/x/mail"))

    def test_encrypted_cache_gives_the_parent_of_its_root(self):
        store = SimpleNamespace(mode="encrypted", root=Path("/x/mail/perso"))
        self.assertEqual(storage.base_of(store), Path("/x/mail"))

    def test_ephemeral_cache_gives_none(self):
        store = SimpleNamespace(
            mode="ephemeral", root=Path("/dev/shm/x/perso")
        )
        self.assertIsNone(storage.base_of(store))

    def test_real_store_under_a_temporary_base(self):
        from script.todo.mail.accounts import account_from_preset
        from script.todo.mail.store import Store

        account = account_from_preset(
            "perso", "boite.regles@example.org", "generic"
        )
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(account, mode="clear", base=Path(tmp))
            self.assertEqual(storage.base_of(store), Path(tmp))
            store = Store(account, mode="ephemeral", base=Path(tmp))
            self.assertIsNone(storage.base_of(store))


class TestRules(StorageCase):
    def test_atomic_write_leaves_no_temporary_file(self):
        for index in range(3):
            self.add(f"Règle {index}")
        files = os.listdir(self.base / ".rules" / "perso")
        self.assertFalse([name for name in files if name.endswith(".tmp")])

    def test_file_is_indented_utf8_json(self):
        self.add("Été")
        text = storage.rules_path("perso", self.base).read_text("utf-8")
        self.assertIn("Été", text)
        self.assertIn('\n  "rules"', text)
        self.assertEqual(json.loads(text)["account"], "perso")

    def test_new_rules_are_appended_ten_by_ten(self):
        first, second = self.add("Une"), self.add("Deux")
        rules = storage.load("perso", base=self.base)
        self.assertEqual([r.id for r in rules], [first.id, second.id])
        self.assertEqual([r.order for r in rules], [10, 20])

    def test_upsert_replaces_by_id(self):
        rule = self.add()
        rule.name = "Renommée"
        storage.upsert_rule("perso", rule, base=self.base)
        rules = storage.load("perso", base=self.base)
        self.assertEqual([r.name for r in rules], ["Renommée"])

    def test_upsert_validates_first(self):
        rule = new_rule()
        rule.throttle_minutes = 0
        with self.assertRaises(RuleError):
            storage.upsert_rule("perso", rule, base=self.base)
        self.assertEqual(storage.load("perso", base=self.base), [])

    def test_upsert_keeps_the_arming_on_disk(self):
        rule = self.add()
        armed = Armed(7, 100, 1793000000)
        storage.set_armed("perso", {rule.id: armed}, base=self.base)
        rule.name = "Modifiée pendant le réarmement"
        rule.armed = None
        storage.upsert_rule("perso", rule, base=self.base)
        self.assertEqual(storage.load("perso", base=self.base)[0].armed, armed)

    def test_upsert_with_rearm_replaces_the_arming(self):
        rule = self.add()
        storage.set_armed("perso", {rule.id: Armed(7, 100, 1)}, base=self.base)
        fresh = Armed(7, 250, 2)
        storage.upsert_rule("perso", rule, rearm=fresh, base=self.base)
        self.assertEqual(storage.load("perso", base=self.base)[0].armed, fresh)

    def test_upsert_of_a_disabled_rule_disarms_it(self):
        rule = self.add()
        storage.set_armed("perso", {rule.id: Armed(7, 100, 1)}, base=self.base)
        rule.enabled = False
        storage.upsert_rule("perso", rule, base=self.base)
        stored = storage.load("perso", base=self.base)[0]
        self.assertFalse(stored.enabled)
        self.assertIsNone(stored.armed)

    def test_upsert_with_lock_held_does_not_wait_for_the_lock(self):
        rule = new_rule()
        with file_lock(storage.lock_path("perso", self.base), wait=0) as held:
            self.assertTrue(held)
            storage.upsert_rule("perso", rule, base=self.base, lock_held=True)
        self.assertEqual(len(storage.load("perso", base=self.base)), 1)

    def test_rules_busy_when_another_descriptor_holds_the_lock(self):
        rule = new_rule()
        with file_lock(storage.lock_path("perso", self.base), wait=0) as held:
            self.assertTrue(held)
            started = time.monotonic()
            with self.assertRaises(RulesBusy):
                storage.upsert_rule("perso", rule, base=self.base, wait=0.3)
            self.assertGreaterEqual(time.monotonic() - started, 0.25)
            for call in (
                lambda: storage.delete_rule(
                    "perso", "x", base=self.base, wait=0
                ),
                lambda: storage.move_rule(
                    "perso", "x", 1, base=self.base, wait=0
                ),
                lambda: storage.set_enabled(
                    "perso", "x", True, armed=None, base=self.base, wait=0
                ),
            ):
                with self.assertRaises(RulesBusy):
                    call()
        storage.upsert_rule("perso", rule, base=self.base, wait=0)

    def test_move_rule_renumbers(self):
        one, two, three = self.add("Un"), self.add("Deux"), self.add("Trois")
        storage.move_rule("perso", three.id, -1, base=self.base)
        rules = storage.load("perso", base=self.base)
        self.assertEqual([r.name for r in rules], ["Un", "Trois", "Deux"])
        self.assertEqual([r.order for r in rules], [10, 20, 30])
        storage.move_rule("perso", one.id, 5, base=self.base)
        rules = storage.load("perso", base=self.base)
        self.assertEqual([r.name for r in rules], ["Trois", "Deux", "Un"])
        storage.move_rule("perso", two.id, -9, base=self.base)
        rules = storage.load("perso", base=self.base)
        self.assertEqual([r.name for r in rules], ["Deux", "Trois", "Un"])

    def test_delete_rule(self):
        keep, drop = self.add("Garde"), self.add("Retire")
        storage.delete_rule("perso", drop.id, base=self.base)
        self.assertEqual(
            [r.id for r in storage.load("perso", base=self.base)], [keep.id]
        )
        storage.delete_rule("perso", "inconnu", base=self.base)

    def test_set_enabled_arms_on_enable_and_disarms_on_disable(self):
        rule = self.add()
        storage.set_armed("perso", {rule.id: Armed(7, 10, 1)}, base=self.base)
        storage.set_enabled(
            "perso", rule.id, False, armed=None, base=self.base
        )
        stored = storage.load("perso", base=self.base)[0]
        self.assertFalse(stored.enabled)
        self.assertIsNone(stored.armed)
        armed = Armed(7, 300, 5)
        storage.set_enabled(
            "perso", rule.id, True, armed=armed, base=self.base
        )
        stored = storage.load("perso", base=self.base)[0]
        self.assertTrue(stored.enabled)
        self.assertEqual(stored.armed, armed)

    def test_set_enabled_without_change_keeps_the_arming(self):
        rule = self.add()
        armed = Armed(7, 10, 1)
        storage.set_armed("perso", {rule.id: armed}, base=self.base)
        storage.set_enabled("perso", rule.id, True, armed=None, base=self.base)
        self.assertEqual(storage.load("perso", base=self.base)[0].armed, armed)

    def test_future_version_is_refused_and_file_left_intact(self):
        self.add()
        path = storage.rules_path("perso", self.base)
        data = json.loads(path.read_text())
        data["version"] = 2
        path.write_text(json.dumps(data))
        before = path.read_bytes()
        with self.assertRaises(RuleError):
            storage.load("perso", base=self.base)
        with self.assertRaises(RuleError):
            storage.upsert_rule("perso", new_rule(), base=self.base)
        self.assertEqual(path.read_bytes(), before)

    def test_unreadable_json_is_a_rule_error(self):
        path = storage.rules_path("perso", self.base)
        path.write_text("{pas du json")
        with self.assertRaises(RuleError):
            storage.load("perso", base=self.base)

    def test_unknown_root_keys_survive_every_mutation(self):
        first = self.add()
        second = self.add("Deuxième")
        path = storage.rules_path("perso", self.base)
        data = json.loads(path.read_text())
        data["caps"] = {"per_pass": 5, "per_hour": 30}
        data["futur"] = ["gardé"]
        path.write_text(json.dumps(data))
        mutations = (
            lambda: storage.upsert_rule("perso", first, base=self.base),
            lambda: storage.move_rule("perso", second.id, -1, base=self.base),
            lambda: storage.set_enabled(
                "perso", first.id, False, armed=None, base=self.base
            ),
            lambda: storage.set_armed(
                "perso", {second.id: Armed(7, 10, 1)}, base=self.base
            ),
            lambda: storage.delete_rule("perso", first.id, base=self.base),
        )
        for index, mutate in enumerate(mutations):
            with self.subTest(mutation=index):
                mutate()
                data = json.loads(path.read_text())
                self.assertEqual(data["caps"], {"per_pass": 5, "per_hour": 30})
                self.assertEqual(data["futur"], ["gardé"])
                self.assertEqual(data["version"], 1)

    def test_rule_that_load_would_refuse_is_never_written(self):
        self.add()
        path = storage.rules_path("perso", self.base)
        before = path.read_bytes()
        cases = {
            "empty id": dict(id=""),
            "name None": dict(name=None),
            "enabled as text": dict(enabled="oui"),
            "unserializable extra": dict(extra={"x": object()}),
        }
        for label, changes in cases.items():
            with self.subTest(case=label):
                rule = new_rule("reply", "Fautive")
                for key, value in changes.items():
                    setattr(rule, key, value)
                with self.assertRaises(RuleError):
                    storage.upsert_rule("perso", rule, base=self.base)
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(len(storage.load("perso", base=self.base)), 1)

    def test_incomplete_arming_is_never_written(self):
        rule = self.add()
        path = storage.rules_path("perso", self.base)
        before = path.read_bytes()
        broken = Armed(uidvalidity=7, uidnext=None, at=1)
        with self.assertRaises(RuleError):
            storage.upsert_rule("perso", rule, rearm=broken, base=self.base)
        with self.assertRaises(RuleError):
            storage.set_armed("perso", {rule.id: broken}, base=self.base)
        self.assertEqual(path.read_bytes(), before)


class TestReport(StorageCase):
    """Les réglages du rapport (clé racine « report ») et son instantané."""

    def path(self):
        return storage.rules_path("perso", self.base)

    def test_report_defaults_without_key(self):
        self.assertEqual(
            storage.load_report("perso", base=self.base),
            storage.ReportSettings(),
        )
        self.add()
        self.assertEqual(
            storage.load_report("perso", base=self.base),
            storage.ReportSettings(),
        )
        partial = storage.report_from_dict({"days": 3})
        self.assertEqual(partial.days, 3)
        self.assertEqual(partial.weeks, storage.DEFAULT_REPORT_WEEKS)

    def test_report_bounds_are_enforced(self):
        refused = {
            "days": [0, 32, True, "7", 7.0],
            "weeks": [-1, 9, False],
            "delay_window_days": [0, 366, None],
            "format": ["pdf", 1],
            "lang": ["de", None],
            "auth_serv_id": ["a b", "a;b", "é", "x" * 256, 3],
        }
        for name, values in refused.items():
            for value in values:
                with self.subTest(field=name, value=value):
                    with self.assertRaises(RuleError) as caught:
                        storage.report_from_dict({name: value})
                    self.assertIn(f"report.{name}", str(caught.exception))
        accepted = storage.report_from_dict(
            {
                "days": 31,
                "weeks": 0,
                "delay_window_days": 365,
                "format": "html",
                "lang": "en",
                "auth_serv_id": "mx.example.org",
            }
        )
        self.assertEqual(accepted.weeks, 0)
        with self.assertRaises(RuleError):
            storage.report_from_dict(["days"])

    def test_save_report_keeps_rules_caps_and_unknown_subkeys(self):
        rule = self.add()
        data = json.loads(self.path().read_text())
        data["caps"] = {"per_pass": 5, "per_hour": 30}
        data["report"] = {"days": 3, "futur": "gardé"}
        data["autre"] = [1]
        self.path().write_text(json.dumps(data))
        settings = storage.ReportSettings(
            days=10, weeks=2, lang="fr", auth_serv_id="mx.example.org"
        )
        storage.save_report("perso", settings, base=self.base)
        data = json.loads(self.path().read_text())
        self.assertEqual(data["caps"], {"per_pass": 5, "per_hour": 30})
        self.assertEqual(data["autre"], [1])
        self.assertEqual(data["report"]["futur"], "gardé")
        self.assertEqual(data["report"]["days"], 10)
        self.assertEqual(
            storage.load_report("perso", base=self.base), settings
        )
        self.assertEqual(
            [r.id for r in storage.load("perso", base=self.base)], [rule.id]
        )
        before = self.path().read_bytes()
        with self.assertRaises(RuleError):
            storage.save_report(
                "perso", storage.ReportSettings(days=0), base=self.base
            )
        self.assertEqual(self.path().read_bytes(), before)

    def test_rule_mutation_keeps_report(self):
        rule = self.add()
        settings = storage.ReportSettings(days=12)
        storage.save_report("perso", settings, base=self.base)
        storage.upsert_rule("perso", rule, base=self.base)
        storage.set_enabled(
            "perso", rule.id, False, armed=None, base=self.base
        )
        storage.save_caps("perso", storage.Caps(4, 8), base=self.base)
        self.assertEqual(
            storage.load_report("perso", base=self.base), settings
        )

    def test_report_future_version_is_refused(self):
        self.add()
        data = json.loads(self.path().read_text())
        data["version"] = 99
        self.path().write_text(json.dumps(data))
        with self.assertRaises(RuleError):
            storage.load_report("perso", base=self.base)
        with self.assertRaises(RuleError):
            storage.save_report(
                "perso", storage.ReportSettings(), base=self.base
            )

    def test_report_snapshot_is_private_and_unreadable_gives_none(self):
        self.assertIsNone(
            storage.load_report_snapshot("perso", base=self.base)
        )
        content = {"key": {"day": "2026-10-28"}, "mailbox": {"days": []}}
        storage.save_report_snapshot("perso", content, base=self.base)
        path = storage.account_dir("perso", self.base) / "report_snapshot.json"
        self.assertEqual(mode_of(path), 0o600)
        self.assertEqual(
            storage.load_report_snapshot("perso", base=self.base), content
        )
        for broken in ("{pas du json", "[1, 2]", "\udcff"):
            with self.subTest(broken=broken):
                path.write_text(broken, errors="surrogateescape")
                self.assertIsNone(
                    storage.load_report_snapshot("perso", base=self.base)
                )


class TestState(StorageCase):
    def test_state_round_trip(self):
        state = EngineState(
            uidvalidity=1700000001,
            cursor=4530,
            cache_epoch="5be1c0d29a7f3e44",
            hold_until=1793000000,
        )
        storage.save_state("perso", state, base=self.base)
        self.assertEqual(storage.load_state("perso", base=self.base), state)
        data = json.loads(storage.state_path("perso", self.base).read_text())
        self.assertEqual(data["version"], 1)

    def test_absent_state_is_fresh(self):
        self.assertEqual(
            storage.load_state("perso", base=self.base), EngineState()
        )

    def test_wrong_types_are_refused(self):
        path = storage.state_path("perso", self.base)
        path.write_text(json.dumps({"version": 1, "cursor": "12"}))
        with self.assertRaises(RuleError):
            storage.load_state("perso", base=self.base)


class TestMedia(StorageCase):
    def test_import_copies_with_private_mode(self):
        ref = storage.import_media(
            "perso", self.image("logo.png"), base=self.base
        )
        self.assertEqual(ref.file, "logo.png")
        self.assertEqual(ref.mime, "image/png")
        self.assertEqual(ref.sha256, hashlib.sha256(PNG).hexdigest())
        path = storage.media_dir("perso", self.base) / ref.file
        self.assertEqual(mode_of(path), 0o600)
        self.assertEqual(storage.read_media("perso", ref, base=self.base), PNG)

    def test_svg_without_converter_is_refused_and_never_stored(self):
        with mock.patch.object(
            storage.svg, "available_converters", return_value=[]
        ):
            with self.assertRaises(RuleError):
                storage.import_media(
                    "perso", self.image("logo.svg", b"<svg/>"), base=self.base
                )
        folder = storage.media_dir("perso", self.base)
        self.assertEqual(os.listdir(folder), [])

    def test_three_mebibytes_is_refused(self):
        big = self.image("grand.png", b"\x00" * (3 * 1024 * 1024))
        with self.assertRaises(RuleError):
            storage.import_media("perso", big, base=self.base)
        self.assertGreater(3 * 1024 * 1024, MAX_IMAGE_BYTES)

    def test_same_content_is_reused(self):
        first = storage.import_media(
            "perso", self.image("logo.png"), base=self.base
        )
        again = storage.import_media(
            "perso", self.image("logo.png"), base=self.base
        )
        self.assertEqual(first, again)
        self.assertEqual(
            os.listdir(storage.media_dir("perso", self.base)), ["logo.png"]
        )

    def test_different_content_under_the_same_name_gets_a_suffix(self):
        storage.import_media("perso", self.image("logo.png"), base=self.base)
        other = PNG + b"autre"
        second = storage.import_media(
            "perso", self.image("logo.png", other), base=self.base
        )
        third = storage.import_media(
            "perso", self.image("logo.png", other + b"!"), base=self.base
        )
        self.assertEqual(second.file, "logo-2.png")
        self.assertEqual(third.file, "logo-3.png")

    def test_name_is_sanitized(self):
        ref = storage.import_media(
            "perso", self.image("..logo été (1).png"), base=self.base
        )
        self.assertRegex(ref.file, r"^[A-Za-z0-9._-]+$")
        self.assertFalse(ref.file.startswith("."))
        self.assertNotIn("..", ref.file)

    def test_missing_source_is_a_rule_error(self):
        with self.assertRaises(RuleError):
            storage.import_media(
                "perso", self.src / "absent.png", base=self.base
            )

    def test_read_media_detects_a_modified_file(self):
        ref = storage.import_media(
            "perso", self.image("logo.png"), base=self.base
        )
        path = storage.media_dir("perso", self.base) / ref.file
        os.chmod(path, 0o600)
        path.write_bytes(PNG + b"retouche")
        with self.assertRaises(RuleError):
            storage.read_media("perso", ref, base=self.base)

    def test_read_media_refuses_a_missing_file_and_an_unsafe_name(self):
        for ref in (
            MediaRef("absent.png", "00", "image/png"),
            MediaRef("../rules.json", "00", "image/png"),
        ):
            with self.subTest(file=ref.file):
                with self.assertRaises(RuleError):
                    storage.read_media("perso", ref, base=self.base)

    def test_delete_rule_keeps_the_media(self):
        ref = storage.import_media(
            "perso", self.image("logo.png"), base=self.base
        )
        rule = new_rule()
        rule.action.images = [ref]
        storage.upsert_rule("perso", rule, base=self.base)
        storage.delete_rule("perso", rule.id, base=self.base)
        self.assertEqual(storage.read_media("perso", ref, base=self.base), PNG)


class TestFileLock(unittest.TestCase):
    """Deux descripteurs du même processus s'excluent."""

    def test_second_descriptor_waits_then_gives_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lock"
            with file_lock(path, wait=0) as first:
                self.assertTrue(first)
                with file_lock(path, wait=0.2, poll=0.05) as second:
                    self.assertFalse(second)
            with file_lock(path, wait=0) as third:
                self.assertTrue(third)

    def test_lock_is_released_after_an_exception(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lock"
            with self.assertRaises(ValueError):
                with file_lock(path, wait=0) as held:
                    self.assertTrue(held)
                    raise ValueError("arrêt")
            with file_lock(path, wait=0) as held:
                self.assertTrue(held)

    def test_symlink_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "cible"
            target.write_text("")
            link = Path(tmp) / "lock"
            link.symlink_to(target)
            with self.assertRaises(OSError):
                with file_lock(link, wait=0):
                    pass


if __name__ == "__main__":
    unittest.main()
