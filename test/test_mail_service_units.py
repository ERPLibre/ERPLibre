#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les unités systemd utilisateur du service des règles, sur des doubles.

Aucun programme système n'est lancé : `systemctl` et `loginctl` sont des
doubles qui enregistrent chaque `argv`, et `subprocess.run` est remplacé
par une assertion. `HOME` pointe vers un dossier temporaire, et
`XDG_CONFIG_HOME` vers un AUTRE, que le module ne doit pas suivre. Seul
`test_systemd_analyze_accepts_the_units` lance un vrai programme, en
lecture seule, sur des fichiers d'un dossier temporaire.
"""

import json
import os
import shutil
import stat
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from script.todo.mail import credential, service
from script.todo.mail.rules import storage
from script.todo.mail.rules.model import Condition, Group, new_rule
from script.todo.mail.service import ServiceError, ServiceStatus
from script.todo.todo_i18n import t

# Le vrai `subprocess.run`, pris avant que le filet ne le remplace.
VRAI_RUN = subprocess.run
DEPOT = Path("/srv/depot erplibre")
PYTHON = DEPOT / ".venv.erplibre" / "bin" / "python"
MAITRE = "maitre-essai"
T_SUIVANTE = 1_780_000_600
T_DERNIERE = 1_780_000_000

SERVICE_ATTENDU = """\
# Written by ERPLibre TODO, Mail > Rules > Service; rewritten on update.
[Unit]
Description=ERPLibre mail rules, one pass for every account

[Service]
Type=oneshot
WorkingDirectory=/srv/depot erplibre
ExecStart="/srv/depot erplibre/.venv.erplibre/bin/python" \
-m script.todo.mail.rules.run --quiet
Environment=PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8
LoadCredentialEncrypted=erplibre-mail-kdbx
SuccessExitStatus=6
TimeoutStartSec=10min
SyslogIdentifier=erplibre-mail-rules
UMask=0077
Nice=10
IOSchedulingClass=best-effort
IOSchedulingPriority=7
LimitCORE=0
NoNewPrivileges=yes
RestrictSUIDSGID=yes
RestrictRealtime=yes
RestrictNamespaces=yes
LockPersonality=yes
SystemCallArchitectures=native
"""

TIMER_ATTENDU = """\
# Written by ERPLibre TODO, Mail > Rules > Service; rewritten on update.
[Unit]
Description=ERPLibre mail rules every 5 min

[Timer]
OnStartupSec=2min
OnUnitActiveSec=5min
RandomizedDelaySec=30s
AccuracySec=30s

[Install]
WantedBy=timers.target
"""


def reponse(code=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=code, stdout=stdout, stderr=stderr)


class FakeSystemctl:
    """Répond comme `systemctl --user` et `loginctl` ; enregistre chaque
    `argv`. `codes` donne le code rendu par action (`daemon-reload`,
    `enable`, …), 0 à défaut."""

    def __init__(self, home: Path):
        self.home = home
        self.appels = []
        self.codes = {}
        self.show = {}
        self.list_timers = "[]"
        self.linger = "no"

    def __call__(self, argv, **kwargs):
        argv = list(argv)
        self.appels.append(argv)
        if argv == ["systemctl", "--user", "show", "-p", "UnitPath"] + [
            "--value"
        ]:
            return reponse(
                stdout=f"/run/user/1000/systemd/user.control"
                f" {self.home}/.config/systemd/user"
                f" {self.home}/.local/share/systemd/user"
            )
        if argv[:2] == ["systemctl", "--user"]:
            action = argv[2]
            if action == "show":
                unite = argv[-1]
                code, sortie = self.show.get(unite, (0, ""))
                return reponse(code, sortie, "Failed to connect to bus")
            if action == "list-timers":
                return reponse(stdout=self.list_timers)
            return reponse(self.codes.get(action, 0), "", "refus du double")
        if argv[0] == "loginctl":
            if "show-user" in argv:
                return reponse(stdout=self.linger + "\n")
            return reponse(self.codes.get(argv[2], 0))
        raise AssertionError(f"appel imprévu : {argv}")

    def actions(self):
        """Les appels sans la résolution du dossier de configuration."""
        return [a for a in self.appels if "UnitPath" not in a]


class UnitsCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        rustine = mock.patch.dict(
            os.environ,
            {
                "HOME": str(self.home),
                "XDG_CONFIG_HOME": str(self.home / "ailleurs"),
            },
        )
        rustine.start()
        self.addCleanup(rustine.stop)
        filet = mock.patch.object(
            subprocess,
            "run",
            side_effect=AssertionError("programme système appelé"),
        )
        filet.start()
        self.addCleanup(filet.stop)
        self.systemd = FakeSystemctl(self.home)
        self.units = self.home / ".config" / "systemd" / "user"
        self.cred = (
            self.home
            / ".config"
            / credential.CREDSTORE_NAME
            / credential.CREDENTIAL_ID
        )
        self.depot = self.home / "depot 100%"
        self.python = self.depot / ".venv.erplibre" / "bin" / "python"
        self.python.parent.mkdir(parents=True)
        self.python.write_text("#!/bin/sh\n")
        self.python.chmod(0o755)

    def installer(self, n=5, repo=None):
        service.install(n, repo=repo or self.depot, run=self.systemd)

    def poser_credential(self):
        self.cred.parent.mkdir(parents=True, exist_ok=True)
        self.cred.write_bytes(b"\x00chiffre")


class TestRendering(UnitsCase):
    def test_the_service_unit_is_rendered_exactly(self):
        self.assertEqual(
            service.render_service(DEPOT, PYTHON), SERVICE_ATTENDU
        )

    def test_the_timer_unit_is_rendered_exactly(self):
        self.assertEqual(service.render_timer(5), TIMER_ATTENDU)

    def test_percent_quote_and_backslash_are_escaped_dollar_kept(self):
        self.assertEqual(
            service.quote_exec_arg('/a b/100%$x"y\\z'),
            '"/a b/100%%$x\\"y\\\\z"',
        )
        self.assertEqual(service.escape_specifiers("/a/%h"), "/a/%%h")
        texte = service.render_service(
            Path("/srv/d%p"), Path("/srv/d%p/v$HOME/bin/python")
        )
        self.assertIn("WorkingDirectory=/srv/d%%p\n", texte)
        self.assertIn('ExecStart="/srv/d%%p/v$HOME/bin/python" -m', texte)

    def test_a_dollar_in_the_python_reads_back_as_installed(self):
        python = Path("/srv/d$HOME/.venv.erplibre/bin/python")
        ligne = service.render_service(Path("/srv/d$HOME"), python)
        execstart = service._directive(ligne, "ExecStart")
        self.assertEqual(service._unquote_exec_arg(execstart), str(python))

    def test_an_escaped_python_reads_back(self):
        brut = '/srv/a "b"/100%$x\\y/python'
        self.assertEqual(
            service._unquote_exec_arg(service.quote_exec_arg(brut) + " -m"),
            brut,
        )

    def test_a_control_character_or_relative_path_is_refused(self):
        for chemin in (
            "depot/relatif",
            "/srv/depot\nExecStartPre=/bin/false",
            "/srv/de\x1bpot",
            "",
            "/srv/depot\\",
            "/srv/de\\pot",
            '/srv/de"pot',
            "/srv/depot ",
            "/srv/depot\t",
        ):
            with self.subTest(chemin=chemin):
                with self.assertRaises(ServiceError) as ctx:
                    service.check_unit_path(chemin)
                self.assertIn(
                    t("mail_service_path_refused"), str(ctx.exception)
                )
        with self.assertRaises(ServiceError):
            service.render_service(Path("/srv/de\npot"), PYTHON)
        self.assertEqual(service.check_unit_path(DEPOT), str(DEPOT))

    def test_the_interval_is_bounded(self):
        for n in (0, 1441, True, "5", 5.0, None, -3):
            with self.subTest(n=n):
                with self.assertRaises(ServiceError):
                    service.render_timer(n)
        self.assertIn("OnUnitActiveSec=1min\n", service.render_timer(1))
        self.assertIn("OnUnitActiveSec=1440min\n", service.render_timer(1440))

    def test_the_repo_root_is_the_commands_one(self):
        from script.todo.mail.rules import run

        self.assertEqual(service.repo_root(), run.repo_root())

    def test_the_venv_name_comes_from_the_repo_configuration(self):
        (self.depot / "conf").mkdir()
        (self.depot / "conf" / "python-erplibre-venv").write_text(
            ".venv.autre\n"
        )
        self.assertEqual(
            service.venv_python(self.depot),
            self.depot / ".venv.autre" / "bin" / "python",
        )
        self.assertEqual(
            service.venv_python(self.home / "sans-conf"),
            self.home / "sans-conf" / ".venv.erplibre" / "bin" / "python",
        )

    @unittest.skipIf(
        shutil.which("systemd-analyze") is None, "systemd-analyze absent"
    )
    def test_systemd_analyze_accepts_the_units(self):
        dossier = self.home / "unités 50% essai"
        dossier.mkdir()
        depot = dossier / "dépôt %h $HOME"
        python = depot / ".venv.erplibre" / "bin" / "python"
        python.parent.mkdir(parents=True)
        python.write_text("#!/bin/sh\n")
        python.chmod(0o755)
        fichier_service = dossier / service.SERVICE
        fichier_timer = dossier / service.TIMER
        fichier_service.write_text(service.render_service(depot, python))
        fichier_timer.write_text(service.render_timer(5))
        resultat = VRAI_RUN(
            [
                "systemd-analyze",
                "--user",
                "verify",
                str(fichier_service),
                str(fichier_timer),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        sortie = f"{resultat.stdout}\n{resultat.stderr}"
        if "Failed to connect" in sortie:
            self.skipTest("gestionnaire utilisateur injoignable")
        self.assertEqual(resultat.returncode, 0, sortie)
        for ligne in sortie.splitlines():
            self.assertNotIn(str(dossier), ligne)


class TestInstall(UnitsCase):
    def test_install_writes_both_units_then_reloads_enables_and_restarts(
        self,
    ):
        self.installer()
        self.assertEqual(
            self.systemd.actions(),
            [
                ["systemctl", "--user", "daemon-reload"],
                ["systemctl", "--user", "enable", "erplibre-mail-rules.timer"],
                [
                    "systemctl",
                    "--user",
                    "restart",
                    "erplibre-mail-rules.timer",
                ],
            ],
        )
        for nom, attendu in (
            (service.SERVICE, service.render_service(self.depot, self.python)),
            (service.TIMER, service.render_timer(5)),
        ):
            fichier = self.units / nom
            self.assertEqual(fichier.read_text(), attendu)
            self.assertEqual(stat.S_IMODE(fichier.stat().st_mode), 0o644)
        self.assertEqual(
            sorted(p.name for p in self.units.iterdir()),
            [
                service.SERVICE,
                service.TIMER,
            ],
        )
        self.assertFalse((self.home / "ailleurs").exists())

    def test_the_units_land_where_the_manager_reads_them(self):
        self.systemd.appels.clear()
        self.assertEqual(service.unit_dir(run=self.systemd), self.units)
        self.assertEqual(
            service.wants_link(run=self.systemd),
            self.units / "timers.target.wants" / service.TIMER,
        )

    def test_an_update_rewrites_the_timer_with_the_new_interval(self):
        self.installer(5)
        self.systemd.appels.clear()
        self.installer(12)
        self.assertIn(
            "OnUnitActiveSec=12min\n",
            (self.units / service.TIMER).read_text(),
        )
        self.assertEqual(service.installed_interval(run=self.systemd), 12)
        self.assertEqual(
            [a[2] for a in self.systemd.actions()],
            ["daemon-reload", "enable", "restart"],
        )

    def test_install_without_systemd_removes_what_it_created(self):
        self.systemd.codes["daemon-reload"] = 1
        with self.assertRaises(ServiceError) as ctx:
            self.installer()
        self.assertIn(t("mail_service_no_systemd"), str(ctx.exception))
        self.assertEqual(list(self.units.iterdir()), [])
        # Une unité qui existait reste, réécrite.
        self.units.mkdir(parents=True, exist_ok=True)
        (self.units / service.SERVICE).write_text("ancien\n")
        with self.assertRaises(ServiceError) as ctx:
            self.installer()
        self.assertIn(
            t("mail_service_reload_failed_update"), str(ctx.exception)
        )
        self.assertNotIn(t("mail_service_no_systemd"), str(ctx.exception))
        self.assertEqual(
            [p.name for p in self.units.iterdir()], [service.SERVICE]
        )
        self.assertEqual(
            (self.units / service.SERVICE).read_text(),
            service.render_service(self.depot, self.python),
        )

    def test_install_refuses_a_missing_venv_and_writes_nothing(self):
        self.python.unlink()
        with self.assertRaises(ServiceError) as ctx:
            self.installer()
        self.assertIn(t("mail_service_no_venv"), str(ctx.exception))
        self.assertFalse(self.units.exists())
        self.assertEqual(self.systemd.appels, [])

    def test_a_refused_interval_writes_nothing(self):
        with self.assertRaises(ServiceError):
            self.installer(0)
        self.assertFalse(self.units.exists())
        self.assertEqual(self.systemd.appels, [])

    def test_a_refused_enable_is_an_install_failure(self):
        self.systemd.codes["enable"] = 1
        with self.assertRaises(ServiceError) as ctx:
            self.installer()
        self.assertIn(t("mail_service_install_failed"), str(ctx.exception))


class TestUninstall(UnitsCase):
    def test_uninstall_disables_stops_removes_and_reloads_in_order(self):
        self.installer()
        lien = self.units / "timers.target.wants" / service.TIMER
        lien.parent.mkdir()
        lien.symlink_to(self.units / service.TIMER)
        self.systemd.appels.clear()
        self.assertTrue(service.uninstall(run=self.systemd))
        timer, unite = service.TIMER, service.SERVICE
        self.assertEqual(
            self.systemd.actions(),
            [
                ["systemctl", "--user", "show-environment"],
                ["systemctl", "--user", "disable", "--now", timer],
                ["systemctl", "--user", "stop", unite],
                ["systemctl", "--user", "daemon-reload"],
                ["systemctl", "--user", "reset-failed", unite],
            ],
        )
        self.assertFalse((self.units / unite).exists())
        self.assertFalse((self.units / timer).exists())
        self.assertFalse(lien.is_symlink())

    def test_tolerated_failures_do_not_stop_the_uninstall(self):
        self.installer()
        for action in ("disable", "stop", "reset-failed"):
            self.systemd.codes[action] = 5
        self.assertTrue(service.uninstall(run=self.systemd))
        self.assertFalse((self.units / service.SERVICE).exists())

    def test_uninstall_removes_the_credential_by_default(self):
        self.installer()
        self.poser_credential()
        service.uninstall(remove_credential=False, run=self.systemd)
        self.assertTrue(self.cred.exists())
        self.installer()
        service.uninstall(run=self.systemd)
        self.assertFalse(self.cred.exists())

    def test_uninstall_with_nothing_installed_calls_nothing(self):
        self.assertFalse(service.uninstall(run=self.systemd))
        self.assertEqual(self.systemd.actions(), [])
        # Un credential gardé ne compte pas comme « quelque chose à
        # retirer ».
        self.poser_credential()
        self.assertFalse(
            service.uninstall(remove_credential=False, run=self.systemd)
        )
        self.assertEqual(self.systemd.actions(), [])
        self.assertTrue(self.cred.exists())

    def test_a_lone_credential_is_removed_without_systemctl(self):
        self.poser_credential()
        self.assertTrue(service.uninstall(run=self.systemd))
        self.assertFalse(self.cred.exists())
        self.assertEqual(self.systemd.actions(), [])

    def test_uninstall_removes_a_dangling_wants_link(self):
        lien = self.units / "timers.target.wants" / service.TIMER
        lien.parent.mkdir(parents=True)
        lien.symlink_to(self.units / service.TIMER)
        self.assertTrue(service.status(run=self.systemd).installed)
        self.assertTrue(service.uninstall(run=self.systemd))
        self.assertFalse(lien.is_symlink())
        self.assertIn(
            ["systemctl", "--user", "daemon-reload"], self.systemd.actions()
        )

    def test_uninstall_without_user_bus_leaves_the_files(self):
        self.installer()
        self.poser_credential()
        self.systemd.codes["show-environment"] = 1
        self.systemd.appels.clear()
        with self.assertRaises(ServiceError) as ctx:
            service.uninstall(run=self.systemd)
        self.assertEqual(
            str(ctx.exception), t("mail_service_no_systemd_uninstall")
        )
        self.assertNotEqual(
            t("mail_service_no_systemd_uninstall"),
            t("mail_service_no_systemd"),
        )
        self.assertEqual(
            self.systemd.actions(),
            [["systemctl", "--user", "show-environment"]],
        )
        self.assertTrue((self.units / service.SERVICE).exists())
        self.assertTrue((self.units / service.TIMER).exists())
        self.assertTrue(self.cred.exists())

    def test_a_refused_reload_after_removal_is_reported(self):
        self.installer()
        self.systemd.codes["daemon-reload"] = 1
        with self.assertRaises(ServiceError) as ctx:
            service.uninstall(run=self.systemd)
        self.assertIn(
            t("mail_service_reload_failed_removed"), str(ctx.exception)
        )
        self.assertFalse((self.units / service.SERVICE).exists())

    def test_installed_parts_reads_units_and_credential_on_disk(self):
        self.assertEqual(
            service.installed_parts(run=self.systemd), (False, False)
        )
        self.poser_credential()
        self.assertEqual(
            service.installed_parts(run=self.systemd), (False, True)
        )
        self.installer()
        self.assertEqual(
            service.installed_parts(run=self.systemd), (True, True)
        )
        self.systemd.appels.clear()
        service.installed_parts(run=self.systemd)
        self.assertEqual(self.systemd.actions(), [])

    def test_start_now_does_not_wait(self):
        code, _ = service.start_now(run=self.systemd)
        self.assertEqual(code, 0)
        self.assertEqual(
            self.systemd.actions(),
            [["systemctl", "--user", "start", "--no-block", service.SERVICE]],
        )


class TestStatus(UnitsCase):
    def montrer(
        self,
        *,
        active="active",
        exit_status="0",
        exit_ts=f"@{T_DERNIERE + 20}",
        trigger=f"@{T_DERNIERE}",
    ):
        self.systemd.show[service.TIMER] = (
            0,
            "LoadState=loaded\n"
            f"ActiveState={active}\n"
            "UnitFileState=enabled\n"
            f"LastTriggerUSec={trigger}\n",
        )
        self.systemd.show[service.SERVICE] = (
            0,
            "Result=success\n"
            f"ExecMainStatus={exit_status}\n"
            f"ExecMainExitTimestamp={exit_ts}\n",
        )

    def installer_ici(self, n=5):
        """Installe depuis le dépôt courant, comme le menu."""
        with mock.patch.object(
            service, "venv_python", return_value=self.python
        ):
            service.install(n, run=self.systemd)

    def test_status_reads_show_properties(self):
        self.installer()
        self.montrer(exit_status="4")
        self.systemd.list_timers = json.dumps(
            [
                {
                    "next": T_SUIVANTE * 1_000_000,
                    "left": 0,
                    "unit": service.TIMER,
                    "activates": service.SERVICE,
                }
            ]
        )
        self.systemd.appels.clear()
        st = service.status(run=self.systemd)
        self.assertTrue(st.installed)
        self.assertTrue(st.up_to_date)
        self.assertTrue(st.enabled)
        self.assertTrue(st.active)
        self.assertEqual(st.interval_min, 5)
        self.assertEqual(st.next_run, T_SUIVANTE)
        self.assertEqual(st.last_run, T_DERNIERE + 20)
        self.assertEqual(st.last_exit, 4)
        self.assertEqual(st.repo, str(self.depot))
        self.assertFalse(st.repo_missing)
        self.assertEqual(st.error, "")
        argvs = [" ".join(a) for a in self.systemd.appels]
        self.assertFalse(
            any("NextElapseUSecRealtime" in a for a in argvs), argvs
        )
        self.assertTrue(any("--timestamp=unix" in a for a in argvs))
        self.assertTrue(
            any("list-timers --all --output=json" in a for a in argvs)
        )

    def test_status_computes_the_next_run_from_the_last_trigger(self):
        self.installer(7)
        self.montrer()
        self.systemd.list_timers = "NEXT LEFT LAST PASSED UNIT ACTIVATES\n"
        st = service.status(run=self.systemd)
        self.assertEqual(st.next_run, T_DERNIERE + 7 * 60)
        # Minuterie arrêtée : pas de prochaine passe.
        self.montrer(active="inactive")
        self.assertIsNone(service.status(run=self.systemd).next_run)

    def test_a_never_run_service_has_no_last_exit(self):
        self.installer()
        self.montrer(exit_status="0", exit_ts="")
        st = service.status(run=self.systemd)
        self.assertIsNone(st.last_run)
        self.assertIsNone(st.last_exit)
        self.assertNotIn(
            t("mail_service_status_last_exit"), service.status_text(st)
        )
        self.montrer(exit_status="0", exit_ts="n/a")
        self.assertIsNone(service.status(run=self.systemd).last_exit)

    def test_status_names_an_undecryptable_credential(self):
        self.installer()
        self.montrer(exit_status="243")
        texte = service.status_text(service.status(run=self.systemd))
        self.assertIn(t("mail_service_exit_243"), texte)

    def test_status_names_a_moved_checkout(self):
        self.installer()
        for code in ("200", "203"):
            with self.subTest(code=code):
                self.montrer(exit_status=code)
                texte = service.status_text(service.status(run=self.systemd))
                self.assertIn(t(f"mail_service_exit_{code}"), texte)
        self.python.unlink()
        st = service.status(run=self.systemd)
        self.assertTrue(st.repo_missing)
        self.assertIn(
            t("mail_service_status_repo_missing"), service.status_text(st)
        )
        shutil.rmtree(self.depot)
        self.assertTrue(service.status(run=self.systemd).repo_missing)

    def test_status_flags_a_service_installed_from_another_checkout(self):
        self.installer()
        self.montrer()
        texte = service.status_text(service.status(run=self.systemd))
        self.assertIn(t("mail_service_status_other_repo"), texte)
        self.assertNotIn(str(self.depot), texte)
        self.assertNotIn(str(self.home), texte)
        self.assertEqual(
            service.installed_repo(run=self.systemd), str(self.depot)
        )
        # Installé depuis ce dépôt-ci : rien à signaler.
        self.installer_ici()
        texte = service.status_text(service.status(run=self.systemd))
        self.assertNotIn(t("mail_service_status_other_repo"), texte)

    def test_status_without_user_bus_is_unknown_not_raised(self):
        self.installer()
        self.systemd.show[service.TIMER] = (1, "")
        self.systemd.show[service.SERVICE] = (1, "")
        st = service.status(run=self.systemd)
        self.assertTrue(st.error)
        self.assertTrue(st.installed)
        texte = service.status_text(st)
        self.assertIn(t("mail_service_status_unknown"), texte)
        self.assertNotIn(t("mail_service_status_active").format(n=5), texte)

    def test_status_survives_a_missing_systemctl(self):
        self.installer()

        def absent(argv, **kwargs):
            raise FileNotFoundError("systemctl")

        # Le dossier par défaut porte l'installation ; les lectures de
        # systemctl échouent sans lever.
        self.assertEqual(
            service.unit_dir(run=absent),
            self.home / ".config" / "systemd" / "user",
        )
        st = service.status(run=absent)
        self.assertTrue(st.installed)
        self.assertEqual(st.error, "FileNotFoundError")
        self.assertIn(
            t("mail_service_status_unknown"), service.status_text(st)
        )

    def test_status_of_an_outdated_unit_says_so(self):
        self.installer()
        self.montrer()
        fichier = self.units / service.SERVICE
        fichier.write_text(fichier.read_text().replace("Nice=10", "Nice=5"))
        st = service.status(run=self.systemd)
        self.assertFalse(st.up_to_date)
        self.assertIn(
            t("mail_service_status_outdated"), service.status_text(st)
        )

    def test_status_text_names_no_path(self):
        self.installer()
        self.poser_credential()
        self.montrer(exit_status="3")
        self.systemd.list_timers = json.dumps(
            [{"next": T_SUIVANTE * 1_000_000, "unit": service.TIMER}]
        )
        st = service.status(run=self.systemd)
        st.repo_missing = True
        texte = service.status_text(st)
        self.assertNotIn(
            "/", texte.replace(t("mail_service_status_title"), "")
        )
        self.assertIn(t("mail_service_status_credential_yes"), texte)
        self.assertIn(
            time.strftime("%H:%M", time.localtime(T_SUIVANTE)), texte
        )
        self.assertIn(t("mail_service_exit_3"), texte)
        self.assertEqual(texte.count("\n"), 0)

    def test_a_status_with_nothing_installed_asks_systemctl_nothing(self):
        st = service.status(run=self.systemd)
        self.assertEqual(self.systemd.actions(), [])
        self.assertEqual(
            service.status_text(st),
            f"{t('mail_service_status_title')}"
            f" {t('mail_service_status_not_installed')},"
            f" {t('mail_service_status_credential_no')}",
        )

    def test_an_exit_code_without_label_shows_its_number(self):
        st = ServiceStatus(installed=True, last_exit=137, credential=True)
        self.assertIn(
            f"{t('mail_service_status_last_exit')} 137",
            service.status_text(st),
        )


class TestLinger(UnitsCase):
    def test_linger_calls_never_ask_a_password(self):
        self.assertTrue(service.enable_linger("essai", run=self.systemd))
        self.assertTrue(service.disable_linger("essai", run=self.systemd))
        self.assertEqual(
            self.systemd.appels,
            [
                ["loginctl", "--no-ask-password", "enable-linger", "essai"],
                ["loginctl", "--no-ask-password", "disable-linger", "essai"],
            ],
        )

    def test_linger_is_read_and_enabled_only_on_request(self):
        self.assertIs(service.linger_enabled("essai", run=self.systemd), False)
        self.systemd.linger = "yes"
        self.assertIs(service.linger_enabled("essai", run=self.systemd), True)
        self.systemd.linger = "peut-être"
        self.assertIsNone(service.linger_enabled("essai", run=self.systemd))
        self.assertEqual(
            [a for a in self.systemd.appels if "enable-linger" in a], []
        )
        self.assertEqual(
            self.systemd.appels[0],
            ["loginctl", "show-user", "essai", "-p", "Linger", "--value"],
        )

    def test_a_refused_or_missing_loginctl_is_a_failure(self):
        self.systemd.codes["enable-linger"] = 1
        self.assertFalse(service.enable_linger("essai", run=self.systemd))

        def delai(argv, **kwargs):
            raise subprocess.TimeoutExpired(argv, 1)

        self.assertFalse(service.disable_linger("essai", run=delai))
        self.assertIsNone(service.linger_enabled("essai", run=delai))


class TestCycle(UnitsCase):
    def test_no_secret_reaches_any_systemctl_call(self):
        self.poser_credential()
        self.installer()
        service.status(run=self.systemd)
        service.start_now(run=self.systemd)
        service.linger_enabled("essai", run=self.systemd)
        service.uninstall(run=self.systemd)
        self.assertTrue(self.systemd.appels)
        for argv in self.systemd.appels:
            for element in argv:
                self.assertNotIn(MAITRE, element)
                self.assertNotIn("chiffre", element)

    def test_accounts_need_credential_only_for_an_active_kdbx_account(self):
        from script.todo.mail.accounts import account_from_preset

        perso = account_from_preset(
            "perso", "boite.regles@example.org", "generic"
        )
        perso.cache_mode = "clear"
        perso.secret_ref = "kdbx:Mail/perso"
        base = self.home / "regles"
        # Sans règle active exécutable, la passe n'ouvre pas le coffre.
        self.assertFalse(service.accounts_need_credential([perso], base))
        rule = new_rule("reply", "Absence")
        rule.action.body = "Je suis absente."
        rule.filter = Group("all", [Condition("body", "bonjour")])
        rule.enabled = False
        storage.upsert_rule("perso", rule, base=base)
        self.assertFalse(service.accounts_need_credential([perso], base))
        rule.enabled = True
        storage.upsert_rule("perso", rule, base=base)
        self.assertTrue(service.accounts_need_credential([perso], base))
        # Des règles illisibles arrêtent la passe avant le coffre.
        chemin = storage.rules_path("perso", base)
        bon = chemin.read_bytes()
        chemin.write_text("{")
        self.assertFalse(service.accounts_need_credential([perso], base))
        chemin.write_bytes(bon)
        perso.enabled = False
        self.assertFalse(service.accounts_need_credential([perso], base))
        perso.enabled = True
        perso.cache_mode = "ephemeral"
        self.assertFalse(service.accounts_need_credential([perso], base))
        perso.cache_mode = "clear"
        perso.secret_ref = "keyring:mail/perso"
        self.assertFalse(service.accounts_need_credential([perso], base))
        self.assertFalse(service.accounts_need_credential([], base))


if __name__ == "__main__":
    unittest.main()
