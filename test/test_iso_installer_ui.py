#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'interface de l'installateur de l'ISO : le déroulé commun
(erplibre_ui_flow), le mode texte (erplibre_ui_plain), le choix du mode
(erplibre_ui), le catalogue de traduction, et l'écran Textual
(erplibre_ui_tui) piloté par App.run_test() quand textual s'importe.

Ce que ces tests tiennent :

- le clavier est le premier champ, le profil ERPLibre le dernier ; les
  phrases LUKS, le mot de passe de root et le volume secret n'apparaissent
  que si la disposition, la politique root ou la réponse les demandent ;
- une réponse refusée l'est par le code du profil machine, une
  confirmation qui diffère est refusée, et rien n'est effacé sans le nom
  du disque retapé ;
- le document de réponses ne vit que dans un fichier 0600 de RUN_DIR
  pendant que le cœur tourne, puis disparaît ; la sortie montrée ne porte
  jamais un secret ;
- chaque phrase de l'interface a sa traduction française.

Faits, profils, noms et phrases secrètes sont INVENTÉS ; aucun test ne
lance loadkeys, getent, archinstall ni le cœur.
"""

import io
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test import iso_installer_modules as m

mp, facts_mod, dk, ai, pl, ei = m.load()
sys.path.insert(0, str(m.SHARE_DIR))
sys.dont_write_bytecode = True

import erplibre_ui as ui  # noqa: E402
import erplibre_ui_flow as flow  # noqa: E402
import erplibre_ui_i18n as i18n  # noqa: E402
import erplibre_ui_plain as plain  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from async_case import AsyncCase  # noqa: E402

try:
    import erplibre_ui_tui as tui
    import textual  # noqa: F401

    TEXTUAL = True
except Exception:  # pragma: no cover - dépend de l'environnement
    TEXTUAL = False

SONDE_COMPTE = "Compte-inventé-42"
SONDE_LUKS = "phrase-luks-inventée"
SONDE_SECRET = "phrase-secrète-inventée"
SONDE_ROOT = "racine-inventée-7"
ERPLIBRE = [
    {"key": "odoo18", "label": "Odoo 18"},
    {"key": "home", "label": "ERPLibre Home"},
    {"key": "gnome", "label": "GNOME seul"},
]


def tr_en():
    return i18n.Translator("en")


def ask_profile(**override):
    """Profil chiffré dont le clavier, le fuseau et le compte se
    demandent ; volume secret facultatif de 4 Gio."""
    profil = m.luks_profile(
        live={"keymap": "ask"},
        system={"timezone": "ask", "console_keymap": "ask"},
        user={"name": "ask", "sudo": True},
    )
    profil["disk"]["lvm"]["secret_lv"] = {"size_gib": 4, "optional": True}
    profil = mp.merge(profil, override)
    return mp.effective(profil, [str(m.PROFILES_DIR)])


def context(tmp, profile=None, facts=None, **extra):
    ctx = {
        "paths": dict(
            ei.DEFAULT_PATHS,
            run=os.path.join(tmp, "run"),
            log=os.path.join(tmp, "log"),
            target=os.path.join(tmp, "cible"),
            core="/chemin/inventé/erplibre-installer",
        ),
        "facts": facts or m.uefi_laptop(),
        "params": {},
        "profile": profile or ask_profile(),
        "origin": "/run/archiso/bootmnt/erplibre/machine.json",
        "machine_found": True,
        "profile_error": None,
        "erplibre": list(ERPLIBRE),
        "erplibre_doc": {"default_profile": "odoo18"},
        "lang": "en",
        "keymaps": ["us", "fr", "cf", "de"],
        "timezones": ["UTC", "Europe/Paris"],
    }
    ctx.update(extra)
    return ctx


def good_values(**extra):
    valeurs = {
        "keymap": "us",
        "system.timezone": "Europe/Paris",
        "disk.lvm.secret_lv": True,
        "user.name": "camille",
        "user_password": SONDE_COMPTE,
        "user_password_confirm": SONDE_COMPTE,
        "root": "lock",
        "luks_passphrase": SONDE_LUKS,
        "luks_passphrase_confirm": SONDE_LUKS,
        "secret_lv_passphrase": SONDE_SECRET,
        "secret_lv_passphrase_confirm": SONDE_SECRET,
        "erplibre_profile": "home",
    }
    valeurs.update(extra)
    return valeurs


class FakeRun:
    """subprocess.run simulé : tout réussit, chaque argv est noté."""

    def __init__(self, network=True):
        self.calls = []
        self.network = network

    def __call__(self, argv, **_kw):
        self.calls.append(list(argv))
        rc = 0
        if argv[:2] == ["getent", "hosts"] and not self.network:
            rc = 2
        return type("R", (), {"returncode": rc, "stdout": "", "stderr": ""})()


class FakePopen:
    """subprocess.Popen simulé : relit le document de réponses au
    lancement (il doit exister, en 0600), puis rend `lines` et `rc`."""

    def __init__(self, lines=(), rc=0):
        self.lines = list(lines)
        self.rc = rc
        self.argv = None
        self.doc = None
        self.mode = None
        self.kwargs = None

    def __call__(self, argv, **kwargs):
        self.argv = list(argv)
        self.kwargs = kwargs
        chemin = argv[argv.index("--answers") + 1]
        self.mode = stat.S_IMODE(os.stat(chemin).st_mode)
        with open(chemin, encoding="utf-8") as fh:
            self.doc = json.load(fh)
        proc = type("P", (), {})()
        proc.stdout = iter(f"{ligne}\n" for ligne in self.lines)
        proc.wait = lambda: self.rc
        return proc


class TestFields(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_keyboard_first_erplibre_profile_last(self):
        ctx = context(self.tmp.name)
        cles = [c["key"] for c in flow.form_fields(ctx, tr_en())]
        self.assertEqual(cles[0], "keymap")
        self.assertEqual(cles[-1], "erplibre_profile")
        self.assertIn("system.timezone", cles)
        self.assertIn("user.name", cles)
        # Le clavier de la console cible suit celui du live : pas de champ.
        self.assertNotIn("system.console_keymap", cles)
        self.assertNotIn("live.keymap", cles)
        self.assertLess(cles.index("user_password"), cles.index("root"))
        self.assertLess(cles.index("root"), cles.index("luks_passphrase"))

    def test_keymap_default_follows_a_literal_profile(self):
        ctx = context(
            self.tmp.name, profile=ask_profile(live={"keymap": "fr"})
        )
        champ = flow.form_fields(ctx, tr_en())[0]
        self.assertEqual(champ["default"], "fr")
        ctx = context(self.tmp.name)
        self.assertEqual(flow.form_fields(ctx, tr_en())[0]["default"], "us")

    def test_disk_field_only_when_auto_does_not_decide(self):
        ctx = context(self.tmp.name)
        cles = [c["key"] for c in flow.form_fields(ctx, tr_en())]
        self.assertNotIn("disk", cles)
        faits = m.uefi_laptop()
        faits["disks"].append(m.disk("sda", 900, tran="sata"))
        ctx = context(self.tmp.name, facts=faits)
        champ = next(
            c for c in flow.form_fields(ctx, tr_en()) if c["key"] == "disk"
        )
        self.assertEqual(
            [v for v, _l in champ["choices"]], ["/dev/nvme0n1", "/dev/sda"]
        )
        self.assertEqual(champ["default"], "/dev/sda")
        # La clé de démarrage n'est jamais proposée.
        self.assertNotIn("/dev/sdz", [v for v, _l in champ["choices"]])
        # Support de démarrage non reconnu : un seul candidat ne suffit
        # plus, le disque se choisit à l'écran.
        faits = m.uefi_laptop(boot_medium_unknown=True)
        ctx = context(self.tmp.name, facts=faits)
        self.assertTrue(flow.disk_field_needed(ctx))
        valeurs = good_values(disk="/dev/nvme0n1")
        doc, erreurs = flow.collect(ctx, valeurs, tr_en())
        self.assertEqual(erreurs, [])
        self.assertTrue(flow.review(ctx, doc, tr_en())["ok"])

    def test_visibility_follows_layout_root_and_secret_volume(self):
        ctx = context(self.tmp.name)
        vus = flow.visible(ctx, {"root": "lock"})
        self.assertIn("luks_passphrase", vus)
        self.assertNotIn("root_password", vus)
        self.assertNotIn("secret_lv_passphrase", vus)
        vus = flow.visible(
            ctx, {"root": "password", "disk.lvm.secret_lv": True}
        )
        self.assertIn("root_password_confirm", vus)
        self.assertIn("secret_lv_passphrase", vus)
        plain_ctx = context(
            self.tmp.name, profile=ask_profile(disk={"layout": "plain"})
        )
        vus = flow.visible(plain_ctx, {"disk.lvm.secret_lv": True})
        self.assertNotIn("luks_passphrase", vus)
        self.assertNotIn("disk.lvm.secret_lv", vus)
        self.assertNotIn("secret_lv_passphrase", vus)

    def test_layout_asked_drives_the_luks_fields(self):
        ctx = context(
            self.tmp.name, profile=ask_profile(disk={"layout": "ask"})
        )
        cles = [c["key"] for c in flow.form_fields(ctx, tr_en())]
        self.assertIn("disk.layout", cles)
        self.assertNotIn("luks_passphrase", flow.visible(ctx, {}))
        vus = flow.visible(ctx, {"disk.layout": "lvm_on_luks"})
        self.assertIn("luks_passphrase", vus)

    def test_without_sudo_root_needs_a_password(self):
        ctx = context(self.tmp.name, profile=ask_profile(user={"sudo": False}))
        cles = [c["key"] for c in flow.form_fields(ctx, tr_en())]
        self.assertNotIn("root", cles)
        self.assertIn("root_password", flow.visible(ctx, {}))


class TestCollect(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ctx = context(self.tmp.name)

    def test_good_values_give_a_complete_document(self):
        doc, erreurs = flow.collect(self.ctx, good_values(), tr_en())
        self.assertEqual(erreurs, [])
        self.assertEqual(doc["schema"], ei.ANSWERS_SCHEMA)
        self.assertEqual(
            doc["answers"],
            {
                "live.keymap": "us",
                "system.timezone": "Europe/Paris",
                "disk.lvm.secret_lv": True,
                "user.name": "camille",
            },
        )
        self.assertEqual(doc["root"], "lock")
        self.assertEqual(doc["erplibre_profile"], "home")
        self.assertEqual(
            doc["secrets"],
            {
                "user_password": SONDE_COMPTE,
                "luks_passphrase": SONDE_LUKS,
                "secret_lv_passphrase": SONDE_SECRET,
            },
        )
        self.assertEqual(ei.check_answers(doc, True), [])

    def test_refusals(self):
        cas = {
            "keymap": dict(keymap="inexistant"),
            "user.name": dict({"user.name": "root"}),
            "system.timezone": dict({"system.timezone": "nulle part"}),
            "user_password_confirm": dict(user_password_confirm="autre"),
            "luks_passphrase": dict(
                luks_passphrase="court", luks_passphrase_confirm="court"
            ),
            "erplibre_profile": dict(erplibre_profile="inconnu"),
        }
        for cle, valeurs in cas.items():
            with self.subTest(cle=cle):
                _doc, erreurs = flow.collect(
                    self.ctx, good_values(**valeurs), tr_en()
                )
                self.assertEqual([c for c, _m in erreurs], [cle])

    def test_a_refused_secret_is_not_compared(self):
        _doc, erreurs = flow.collect(
            self.ctx,
            good_values(user_password="", user_password_confirm="x"),
            tr_en(),
        )
        self.assertEqual([c for c, _m in erreurs], ["user_password"])

    def test_auto_and_ask_are_never_answers(self):
        _v, refus = flow.check_profile_answer(
            "system.hostname", "auto", tr_en()
        )
        self.assertIsNotNone(refus)
        valeur, refus = flow.check_profile_answer(
            "system.locales", "fr_CA.UTF-8, en_US.UTF-8", tr_en()
        )
        self.assertIsNone(refus)
        self.assertEqual(valeur, ["fr_CA.UTF-8", "en_US.UTF-8"])

    def test_chosen_disk_reaches_the_answers(self):
        faits = m.uefi_laptop()
        faits["disks"].append(m.disk("sda", 900, tran="sata"))
        ctx = context(self.tmp.name, facts=faits)
        doc, erreurs = flow.collect(
            ctx, good_values(disk="/dev/nvme0n1"), tr_en()
        )
        self.assertEqual(erreurs, [])
        self.assertEqual(doc["answers"]["disk.target"], "/dev/nvme0n1")
        avis = flow.review(ctx, doc, tr_en())
        self.assertTrue(avis["ok"], avis["messages"])
        self.assertEqual(
            avis["prep"]["settings"]["derived"]["disk"]["name"], "nvme0n1"
        )
        _doc, erreurs = flow.collect(ctx, good_values(), tr_en())
        self.assertEqual([c for c, _m in erreurs], ["disk"])


class TestReviewAndRecap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ctx = context(self.tmp.name)
        self.doc, _e = flow.collect(self.ctx, good_values(), tr_en())

    def test_review_waits_only_for_the_disk_name(self):
        avis = flow.review(self.ctx, self.doc, tr_en())
        self.assertTrue(avis["ok"])
        self.assertEqual(avis["prep"]["reason"], "disk-not-confirmed")

    def test_recap_shows_the_erased_disk_and_no_secret(self):
        avis = flow.review(self.ctx, self.doc, tr_en())
        vue = flow.recap(self.ctx, self.doc, avis["prep"], tr_en())
        self.assertEqual(vue["expected"], "nvme0n1")
        self.assertTrue(vue["disk"].startswith("/dev/nvme0n1  500 GiB"))
        self.assertEqual(vue["nvme_lbaf"], 1)
        self.assertIn("2  root", " ".join(vue["partitions"]))
        texte = json.dumps(vue, ensure_ascii=False)
        for sonde in (SONDE_COMPTE, SONDE_LUKS, SONDE_SECRET):
            self.assertNotIn(sonde, texte)
        self.assertIn("< [luks]", texte)
        self.assertIn(("User", "camille"), [tuple(x) for x in vue["summary"]])

    def test_keymap_mismatch_is_a_warning(self):
        ctx = context(
            self.tmp.name, profile=ask_profile(system={"console_keymap": "de"})
        )
        doc, _e = flow.collect(ctx, good_values(), tr_en())
        avis = flow.review(ctx, doc, tr_en())
        vue = flow.recap(ctx, doc, avis["prep"], tr_en())
        self.assertTrue(any("« de »" in a for a in vue["warnings"]))

    def test_blocking_review_says_why(self):
        ctx = context(
            self.tmp.name, erplibre=[{"key": "odoo18", "label": "x"}]
        )
        avis = flow.review(ctx, self.doc, tr_en())
        self.assertFalse(avis["ok"])
        self.assertIn("« home »", avis["messages"][0])
        faits = m.uefi_laptop()
        faits["disks"] = [m.usb_key()]
        ctx = context(
            self.tmp.name,
            facts=faits,
            profile=ask_profile(disk={"target": "/dev/sdz"}),
        )
        doc, _e = flow.collect(ctx, good_values(), tr_en())
        avis = flow.review(ctx, doc, tr_en())
        self.assertFalse(avis["ok"])
        self.assertEqual(avis["prep"]["reason"], "blocking-warnings")
        self.assertIn("boot medium", "\n".join(avis["messages"]))

    def test_confirmation_by_name_or_path(self):
        prep = flow.review(self.ctx, self.doc, tr_en())["prep"]
        self.assertTrue(flow.disk_confirmed(prep, "nvme0n1"))
        self.assertTrue(flow.disk_confirmed(prep, "/dev/nvme0n1"))
        self.assertFalse(flow.disk_confirmed(prep, "sdz"))
        self.assertFalse(flow.disk_confirmed(prep, ""))
        doc = flow.confirm_document(self.doc, " nvme0n1 ", True)
        self.assertEqual(
            doc["confirm"], {"disk": "nvme0n1", "nvme_format": True}
        )
        self.assertEqual(self.doc["confirm"], {})
        cles = [e["key"] for e in ERPLIBRE]
        self.assertTrue(
            ei.prepare(self.ctx["profile"], self.ctx["facts"], doc, cles)["ok"]
        )


class TestRunCore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ctx = context(self.tmp.name)

    def test_answers_file_lives_only_while_the_core_runs(self):
        popen = FakePopen(["\x1b[1;32mInstalling\x1b[0m", "fin\r"], rc=0)
        lignes = []
        doc = {"schema": 1, "secrets": {"user_password": SONDE_COMPTE}}
        rc = flow.run_core(self.ctx, doc, lignes.append, popen=popen)
        self.assertEqual(rc, 0)
        self.assertEqual(popen.mode, 0o600)
        self.assertEqual(popen.doc, doc)
        self.assertEqual(lignes, ["Installing", "fin"])
        self.assertEqual(popen.argv[0], "/chemin/inventé/erplibre-installer")
        self.assertNotIn("--dry-run", popen.argv)
        self.assertEqual(popen.kwargs["stdin"], flow.subprocess.DEVNULL)
        self.assertEqual(os.listdir(self.ctx["paths"]["run"]), [])

    def test_answers_file_removed_when_the_core_cannot_start(self):
        def echec(*_a, **_k):
            raise OSError("introuvable")

        lignes = []
        rc = flow.run_core(self.ctx, {"schema": 1}, lignes.append, popen=echec)
        self.assertEqual(rc, 127)
        self.assertEqual(os.listdir(self.ctx["paths"]["run"]), [])

    def test_dry_run_reaches_the_core(self):
        popen = FakePopen()
        flow.run_core(self.ctx, {}, lambda _l: None, popen=popen, dry_run=True)
        self.assertIn("--dry-run", popen.argv)

    def test_stage_log_tail(self):
        chemin = os.path.join(self.tmp.name, "stage.log")
        queue = flow.StageLogTail(chemin)
        self.assertEqual(queue.poll(), [])
        with open(chemin, "w") as fh:
            fh.write("un\ndeux")
        self.assertEqual(queue.poll(), ["un"])
        with open(chemin, "a") as fh:
            fh.write(" suite\ntrois\n")
        self.assertEqual(queue.poll(), ["deux suite", "trois"])
        with open(chemin, "w") as fh:
            fh.write("neuf\n")
        self.assertEqual(queue.poll(), ["neuf"])

    def test_wait_ready(self):
        lignes = []
        self.assertTrue(
            flow.wait_ready(lignes.append, tr_en(), FakeRun(), lambda _s: None)
        )
        self.assertFalse(
            flow.wait_ready(
                lignes.append,
                tr_en(),
                FakeRun(network=False),
                lambda _s: None,
                network_s=3,
            )
        )
        self.assertIn("Waiting for the network…", lignes)

    def test_exit_messages(self):
        self.assertEqual(
            flow.exit_message(tr_en(), 0), "The installation succeeded."
        )
        self.assertIn(
            "nothing was written", flow.exit_message(tr_en(), 0, True)
        )
        self.assertIn("archinstall", flow.exit_message(tr_en(), 26, True))
        self.assertIn("99", flow.exit_message(tr_en(), 99))

    def test_archinstall_commands(self):
        config, archinstall = flow.archinstall_commands(self.ctx, "home", "")
        self.assertEqual(config[:3], [flow.CONFIG_BIN, "--profile", "home"])
        self.assertEqual(archinstall, ["archinstall", "--config", config[4]])


class TestLiveLists(unittest.TestCase):
    def test_keymaps_and_timezones(self):
        with tempfile.TemporaryDirectory() as tmp:
            for rel in ("i386/qwerty/us.map.gz", "i386/azerty/fr.map.gz"):
                chemin = Path(tmp, "kbd", rel)
                chemin.parent.mkdir(parents=True, exist_ok=True)
                chemin.write_bytes(b"")
            Path(tmp, "kbd", "include").mkdir()
            Path(tmp, "kbd", "include", "compose.inc").write_text("")
            self.assertEqual(flow.list_keymaps(Path(tmp, "kbd")), ["fr", "us"])
            for rel in (
                "UTC",
                "Europe/Paris",
                "posix/Europe/Paris",
                "zone.tab",
            ):
                chemin = Path(tmp, "zi", rel)
                chemin.parent.mkdir(parents=True, exist_ok=True)
                chemin.write_bytes(b"")
            self.assertEqual(
                flow.list_timezones(Path(tmp, "zi")), ["Europe/Paris", "UTC"]
            )
        self.assertEqual(flow.list_keymaps("/chemin/absent"), [])

    def test_load_context_reads_machine_json_and_profiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            share = Path(tmp, "share")
            share.mkdir()
            (share / "profiles.json").write_text(
                json.dumps(
                    {
                        "lang": "en",
                        "default_profile": "odoo18",
                        "profiles": [
                            {"key": "odoo18", "label": {"en": "Odoo 18"}}
                        ],
                    }
                )
            )
            boot = Path(tmp, "boot")
            (boot / "erplibre").mkdir(parents=True)
            (boot / "erplibre" / "machine.json").write_text(
                json.dumps(m.plain_profile())
            )
            paths = {
                "share": str(share),
                "profiles": str(m.PROFILES_DIR),
                "config_tool": str(m.CONFIG_TOOL),
                "boot_mount": str(boot),
                "run": str(Path(tmp, "run")),
                "keymaps": str(Path(tmp, "kbd")),
                "zoneinfo": str(Path(tmp, "zi")),
            }
            ctx = flow.load_context(paths=paths, raw_facts={"efi": True})
            self.assertTrue(ctx["machine_found"])
            self.assertEqual(flow.profile_name(ctx), "essai-plain")
            self.assertEqual(
                ctx["erplibre"], [{"key": "odoo18", "label": "Odoo 18"}]
            )
            self.assertEqual(ctx["lang"], "en")
            (boot / "erplibre" / "machine.json").unlink()
            ctx = flow.load_context(paths=paths, raw_facts={"efi": True})
            self.assertFalse(ctx["machine_found"])
            self.assertEqual(flow.profile_name(ctx), "generic")
            self.assertIn("guided", flow.profile_title(ctx, tr_en()))


class TestMode(unittest.TestCase):
    def test_choose_mode(self):
        oui = lambda _fd: True  # noqa: E731
        non = lambda _fd: False  # noqa: E731
        tty1 = lambda _fd: "/dev/tty1"  # noqa: E731
        serie = lambda _fd: "/dev/ttyS0"  # noqa: E731
        vrai = lambda: True  # noqa: E731
        faux = lambda: False  # noqa: E731
        env = {"TERM": "linux"}
        cas = (
            (dict(plain=True), ("plain", "option")),
            (dict(env={"TERM": "dumb"}), ("plain", "term")),
            (dict(env={}), ("plain", "term")),
            (dict(env=env, isatty=non), ("plain", "not-a-tty")),
            (dict(env=env, ttyname=serie), ("plain", "serial")),
            (dict(env=env, textual_ok=faux), ("plain", "no-textual")),
            (dict(env=env), ("tui", None)),
        )
        for options, attendu in cas:
            with self.subTest(**{k: str(v) for k, v in options.items()}):
                base = dict(isatty=oui, ttyname=tty1, textual_ok=vrai)
                base.update(options)
                self.assertEqual(ui.choose_mode(**base), attendu)


class TestTranslation(unittest.TestCase):
    def test_every_ui_phrase_has_a_french_translation(self):
        from script.iso.archlinux import build_iso

        doc, manquantes = build_iso.catalogue_document(
            build_iso.catalogue_strings()
        )
        self.assertEqual(manquantes, [])
        self.assertIn("Install ERPLibre", doc["fr"])
        self.assertIn("Target disk", doc["fr"])

    def test_translator_and_catalogue(self):
        with tempfile.TemporaryDirectory() as tmp:
            chemin = Path(tmp, i18n.CATALOGUE_FILE)
            chemin.write_text(
                json.dumps({"version": 1, "fr": {"Next": "Suivant"}})
            )
            fr = i18n.translator(tmp, "fr")
            self.assertEqual(fr("Next"), "Suivant")
            self.assertEqual(fr("Absent {x}", x=1), "Absent 1")
            self.assertEqual(fr("Champ {absent}"), "Champ {absent}")
            self.assertEqual(fr("Champ {absent}", autre=1), "Champ ?")
            self.assertEqual(fr.toggled()("Next"), "Next")
            chemin.write_text(json.dumps({"version": 99, "fr": {"a": "b"}}))
            self.assertEqual(i18n.load_catalogue(chemin), {})
        self.assertEqual(i18n.load_catalogue("/chemin/absent"), {})
        self.assertEqual(i18n.pick_lang("de", None, "en"), "en")
        self.assertEqual(i18n.pick_lang(), "fr")


class TestPlainMode(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ctx = context(self.tmp.name)
        self.out = []

    def session(self, lignes, secrets, popen=None, run=None):
        self.popen = popen or FakePopen(["ok"], rc=0)
        self.run = run or FakeRun()
        interface = plain.PlainUI(
            self.ctx,
            tr_en(),
            read=plain.ask_lines(lignes),
            secret=plain.ask_lines(secrets),
            write=self.out.append,
            run=self.run,
            popen=self.popen,
            sleep=lambda _s: None,
        )
        return interface.session()

    # Réponses dans l'ordre des champs : clavier, fuseau, volume secret,
    # compte, root (Entrée garde « verrouillé »), profil ERPLibre (2 =
    # home), format NVMe (non), nom du disque, puis « 1 » = redémarrer.
    LIGNES = ["1", "cf", "", "o", "camille", "", "2", "n", "nvme0n1", "1"]
    SECRETS = [
        SONDE_COMPTE,
        SONDE_COMPTE,
        SONDE_LUKS,
        SONDE_LUKS,
        SONDE_SECRET,
        SONDE_SECRET,
    ]

    def test_full_install_then_reboot(self):
        action, donnee, _tr = self.session(self.LIGNES, self.SECRETS)
        self.assertEqual((action, donnee), ("reboot", None))
        self.assertIn(["loadkeys", "cf"], self.run.calls)
        doc = self.popen.doc
        # Taille et modèle du disque montré : le cœur refuse si le nom
        # désigne un autre disque au moment d'effacer.
        self.assertEqual(
            doc["confirm"],
            {
                "disk": "nvme0n1",
                "nvme_format": False,
                "disk_size": 500 * m.GIB,
                "disk_model": "Disque fictif 9000",
            },
        )
        self.assertEqual(doc["answers"]["live.keymap"], "cf")
        self.assertEqual(doc["answers"]["system.timezone"], "UTC")
        self.assertEqual(doc["erplibre_profile"], "home")
        self.assertEqual(doc["secrets"]["luks_passphrase"], SONDE_LUKS)
        # Mode texte : le cœur hérite de la console.
        self.assertIsNone(self.popen.kwargs["stdin"])
        sortie = "\n".join(self.out)
        for sonde in (SONDE_COMPTE, SONDE_LUKS, SONDE_SECRET):
            self.assertNotIn(sonde, sortie)
        self.assertIn("ALL DATA ON THIS DISK WILL BE ERASED:", sortie)
        self.assertIn("The installation succeeded.", sortie)
        self.assertEqual(os.listdir(self.ctx["paths"]["run"]), [])

    def test_nvme_format_is_in_the_summary_that_is_confirmed(self):
        # Oui au formatage NVMe : le récapitulatif affiché ensuite porte la
        # commande « nvme format » et des secteurs LUKS de 4096, ceux que
        # le cœur emploiera.
        lignes = list(self.LIGNES)
        lignes[7] = "o"
        action, _d, _tr = self.session(lignes, self.SECRETS)
        self.assertEqual(action, "reboot")
        recap = self.out[self.out.index("Summary — nothing is written yet") :]
        commandes = recap[recap.index("Commands") :]
        self.assertTrue(
            any(
                c.strip().startswith("nvme format /dev/nvme0n1")
                for c in commandes
            ),
            commandes,
        )
        self.assertTrue(
            any("LUKS sector size" in c and "4096" in c for c in recap), recap
        )
        self.assertTrue(self.popen.doc["confirm"]["nvme_format"])

    def test_secrets_read_from_stdin_when_it_is_not_a_terminal(self):
        # Sans terminal, getpass lirait /dev/tty : les phrases viennent de
        # la même entrée que les autres réponses.
        lu = plain.ask_lines(["une"])
        with mock.patch.object(plain, "_stdin_is_tty", return_value=False):
            interface = plain.PlainUI(self.ctx, tr_en(), read=lu)
        self.assertIs(interface._secret, lu)
        with mock.patch.object(plain, "_stdin_is_tty", return_value=True):
            interface = plain.PlainUI(self.ctx, tr_en(), read=lu)
        self.assertIs(interface._secret, plain.getpass.getpass)

    def test_wrong_disk_name_erases_nothing(self):
        lignes = list(self.LIGNES)
        lignes[8] = "sdz"
        lignes[9:] = ["q"]
        action, _d, _tr = self.session(lignes, self.SECRETS)
        self.assertEqual(action, "shell")
        self.assertIsNone(self.popen.argv)
        self.assertIn("Cancelled: nothing was erased.", self.out)

    def test_a_refused_answer_is_asked_again(self):
        lignes = ["1", "inexistant", "cf"] + self.LIGNES[2:]
        secrets = [SONDE_COMPTE, "autre", SONDE_COMPTE, SONDE_COMPTE]
        secrets += self.SECRETS[2:]
        action, _d, _tr = self.session(lignes, secrets)
        self.assertEqual(action, "reboot")
        formulaire = self.out[
            : self.out.index("Summary — nothing is written yet")
        ]
        refus = [ligne for ligne in formulaire if ligne.startswith("  ! ")]
        self.assertEqual(len(refus), 2, refus)
        self.assertIn("« inexistant »", refus[0])
        self.assertIn("The two entries differ.", refus[1])

    def test_home_actions(self):
        self.assertEqual(self.session(["2"], [])[:2], ("todo", None))
        self.assertEqual(
            self.session(["3", ""], [])[:2], ("archinstall", "odoo18")
        )
        action, _d, tr = self.session(["l", "q"], [])
        self.assertEqual((action, tr.lang), ("shell", "fr"))
        # Fin de l'entrée : retour au shell, sans trace.
        self.assertEqual(self.session([], [])[0], "shell")

    def test_no_network_stops_before_the_core(self):
        action, _d, _tr = self.session(
            self.LIGNES[:-1] + ["2"], self.SECRETS, run=FakeRun(network=False)
        )
        self.assertEqual(action, "shell")
        self.assertIsNone(self.popen.argv)
        self.assertIn(
            "No network: connect a cable, or Wi-Fi with iwctl.", self.out
        )


class TestRunAction(unittest.TestCase):
    def test_todo_runs_the_launcher_and_pauses_on_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = context(tmp)
            lanceur = os.path.join(tmp, "erplibre-todo")
            with open(lanceur, "w", encoding="utf-8") as fh:
                fh.write("#!/bin/sh\n")
            os.chmod(lanceur, 0o755)
            pauses, sortie = [], io.StringIO()
            for rc, attendu in ((0, 0), (3, 1)):
                appels = []

                def run(argv, rc=rc, **kw):
                    appels.append((list(argv), kw["env"]["EL_LANG"]))
                    return type("R", (), {"returncode": rc})()

                with (
                    mock.patch.object(ui.flow, "TODO_BIN", lanceur),
                    mock.patch.object(ui, "_pause", pauses.append),
                ):
                    self.assertIsNone(
                        ui.run_action(
                            "todo", None, ctx, tr_en(), run, sortie.write
                        )
                    )
                self.assertEqual(appels, [([lanceur], "en")])
                self.assertEqual(len(pauses), attendu)
        self.assertIn("ERPLibre TODO returned 3.", sortie.getvalue())

    def test_archinstall_and_reboot(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = context(tmp)
            ctx["paths"]["guided_config"] = os.path.join(tmp, "g", "c.json")
            run = FakeRun()
            sortie = io.StringIO()
            original = ui._pause
            ui._pause = lambda _tr: None
            try:
                self.assertIsNone(
                    ui.run_action(
                        "archinstall", "home", ctx, tr_en(), run, sortie.write
                    )
                )
                self.assertEqual(run.calls[-1][0], "archinstall")
                self.assertEqual(
                    ui.run_action("reboot", None, ctx, tr_en(), run), 0
                )
                self.assertEqual(run.calls[-1], ["systemctl", "reboot"])
                self.assertEqual(
                    ui.run_action("shell", None, ctx, tr_en(), run), 0
                )
            finally:
                ui._pause = original


@unittest.skipUnless(TEXTUAL, "textual absent")
class TestTextual(AsyncCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ctx = context(self.tmp.name)
        self.run = FakeRun()
        self.popen = FakePopen(["Installing", "done"], rc=0)

    def app(self):
        return tui.InstallerApp(
            self.ctx,
            tr_en(),
            run=self.run,
            popen=self.popen,
            sleep=lambda _s: None,
        )

    async def settle(self, app, pilot):
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()

    async def test_home_offers_three_choices_and_todo_exits(self):
        app = self.app()
        async with app.run_test(size=(100, 40)) as pilot:
            await self.settle(app, pilot)
            self.assertIsInstance(app.screen, tui.HomeScreen)
            for bouton in ("install", "todo", "archinstall"):
                app.screen.query_one(f"#{bouton}")
            await pilot.press("2")
        self.assertEqual(app.return_value[:2], ("todo", None))

    async def test_language_toggle(self):
        catalogue = {"Install ERPLibre": "Installer ERPLibre"}
        app = tui.InstallerApp(
            self.ctx, i18n.Translator("en", catalogue), run=self.run
        )
        async with app.run_test(size=(100, 40)) as pilot:
            await self.settle(app, pilot)
            await pilot.press("l")
            await self.settle(app, pilot)
            libelle = str(app.screen.query_one("#install").label)
            self.assertIn("Installer ERPLibre", libelle)
            await pilot.press("q")
        self.assertEqual(app.return_value[2].lang, "fr")

    def fill(self, screen, valeurs):
        from textual.widgets import Checkbox, Input, Select

        for cle, valeur in valeurs.items():
            w = screen.query_one(f"#w-{tui.safe_id(cle)}")
            if isinstance(w, (Input, Checkbox, Select)):
                w.value = valeur

    async def test_install_from_form_to_reboot(self):
        app = self.app()
        async with app.run_test(size=(100, 40)) as pilot:
            await self.settle(app, pilot)
            await pilot.press("1")
            await self.settle(app, pilot)
            form = app.screen
            self.assertIsInstance(form, tui.FormScreen)
            self.assertIn(["loadkeys", "us"], self.run.calls)
            self.assertEqual(form.focused.id, "w-keymap")
            self.assertFalse(form.query_one("#f-root_password").display)
            valeurs = good_values(keymap="cf")
            valeurs["user_password_confirm"] = "autre"
            self.fill(form, valeurs)
            await pilot.pause()
            self.assertTrue(form.query_one("#f-secret_lv_passphrase").display)
            await pilot.press("f10")
            await self.settle(app, pilot)
            self.assertIs(app.screen, form)
            erreur = str(form.query_one("#e-user_password_confirm").render())
            self.assertIn("The two entries differ.", erreur)
            self.assertIn(["loadkeys", "cf"], self.run.calls)
            self.fill(form, {"user_password_confirm": SONDE_COMPTE})
            await pilot.press("f10")
            await self.settle(app, pilot)
            recap = app.screen
            self.assertIsInstance(recap, tui.RecapScreen)
            recap.query_one("#confirm").value = "sdz"
            await pilot.click("#install")
            await self.settle(app, pilot)
            self.assertIs(app.screen, recap)
            self.assertIsNone(self.popen.argv)
            # Un bouton ignore un second appui pendant son effet visuel.
            await pilot.pause(0.5)
            recap.query_one("#confirm").value = "nvme0n1"
            recap.query_one("#nvme").value = True
            await pilot.click("#install")
            await self.settle(app, pilot)
            await self.settle(app, pilot)
            self.assertIsInstance(app.screen, tui.FinalScreen)
            self.assertEqual(
                self.popen.doc["confirm"],
                {
                    "disk": "nvme0n1",
                    "nvme_format": True,
                    "disk_size": 500 * m.GIB,
                    "disk_model": "Disque fictif 9000",
                },
            )
            self.assertEqual(self.popen.doc["answers"]["live.keymap"], "cf")
            self.assertEqual(os.listdir(self.ctx["paths"]["run"]), [])
            await pilot.press("r")
        self.assertEqual(app.return_value[:2], ("reboot", None))

    async def test_disk_choice_and_bracketed_model(self):
        # Un modèle entre crochets s'affiche tel quel, sans être lu comme
        # une balise.
        faits = m.uefi_laptop()
        faits["disks"].append(
            m.disk("sda", 900, tran="sata", model="Disque [fictif]")
        )
        self.ctx = context(self.tmp.name, facts=faits)
        app = self.app()
        async with app.run_test(size=(100, 40)) as pilot:
            await self.settle(app, pilot)
            await pilot.press("1")
            await self.settle(app, pilot)
            form = app.screen
            self.fill(form, good_values(disk="/dev/nvme0n1"))
            await pilot.press("f10")
            await self.settle(app, pilot)
            recap = app.screen
            self.assertIsInstance(recap, tui.RecapScreen)
            self.assertEqual(recap.view["expected"], "nvme0n1")
            await pilot.press("escape")
            await self.settle(app, pilot)
            self.fill(form, {"disk": "/dev/sda"})
            await pilot.press("f10")
            await self.settle(app, pilot)
            self.assertEqual(app.screen.view["expected"], "sda")
            self.assertIn("Disque [fictif]", app.screen.view["disk"])

    async def test_quit_refused_while_installing(self):
        app = self.app()
        async with app.run_test(size=(100, 40)) as pilot:
            await self.settle(app, pilot)
            app.busy = True
            await pilot.press("ctrl+q")
            await pilot.pause()
            self.assertTrue(app.is_running)
            app.busy = False
            await pilot.press("ctrl+q")
        self.assertEqual(app.return_value[0], "shell")

    async def test_no_way_out_while_installing(self):
        # La palette de commandes porte sa propre commande « Quit » : elle
        # est retirée, et action_quit obéit à la même garde que Ctrl+Q.
        app = self.app()
        self.assertFalse(tui.InstallerApp.ENABLE_COMMAND_PALETTE)
        async with app.run_test(size=(100, 40)) as pilot:
            await self.settle(app, pilot)
            app.busy = True
            await pilot.press("ctrl+p")
            await pilot.pause()
            self.assertNotIn("CommandPalette", type(app.screen).__name__)
            await app.action_quit()
            await pilot.pause()
            self.assertTrue(app.is_running)
            app.busy = False
            await app.action_quit()
        self.assertEqual(app.return_value[0], "shell")

    async def test_nvme_box_updates_the_summary(self):
        app = self.app()
        async with app.run_test(size=(100, 40)) as pilot:
            await self.settle(app, pilot)
            await pilot.press("1")
            await self.settle(app, pilot)
            self.fill(app.screen, good_values())
            await pilot.press("f10")
            await self.settle(app, pilot)
            recap = app.screen
            self.assertIsInstance(recap, tui.RecapScreen)
            commandes = str(recap.query_one("#commands").render())
            self.assertNotIn("nvme format", commandes)
            recap.query_one("#nvme").value = True
            await pilot.pause()
            commandes = str(recap.query_one("#commands").render())
            self.assertIn("nvme format /dev/nvme0n1", commandes)
            resume = str(recap.query_one("#summary").render())
            self.assertIn("4096", resume)
            recap.query_one("#nvme").value = False
            await pilot.pause()
            commandes = str(recap.query_one("#commands").render())
            self.assertNotIn("nvme format", commandes)

    async def test_archinstall_screen_returns_the_profile(self):
        app = self.app()
        async with app.run_test(size=(100, 40)) as pilot:
            await self.settle(app, pilot)
            await pilot.press("3")
            await self.settle(app, pilot)
            self.assertIsInstance(app.screen, tui.ArchinstallScreen)
            await pilot.click("#start")
        self.assertEqual(app.return_value[:2], ("archinstall", "odoo18"))


if __name__ == "__main__":
    unittest.main()
