#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""ISO ERPLibre Arch Linux : construction en conteneur, sans moteur.

Couvre script/iso/archlinux/container_build.py (choix du moteur, âge de
l'image, argv de build et de run) et le mode container de build_iso.main.
Les fiches de moteur imitent celles de container_runtime.etat ; aucun
moteur n'est interrogé, aucun conteneur lancé."""

import contextlib
import datetime
import io
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from script.iso.archlinux import build_iso
from script.iso.archlinux import container_build as cb
from script.todo import container_runtime

ROOT = Path(__file__).resolve().parents[1]
TODAY = datetime.date(2031, 3, 15)
EPOCH = 1_700_000_000


def fiche(moteur, sans_sudo=True, avec_sudo=False, rootless=None):
    return {
        "moteur": moteur,
        "sans_sudo": sans_sudo,
        "avec_sudo": avec_sudo,
        "rootless": rootless,
        "docker_host": None,
    }


PODMAN = fiche("podman", rootless=True)
# Checkout simulé : main ne lance pas git, la liste vient d'ici.
CHECKOUT = {
    "files": ["script/todo/todo.py", "script/todo/exemple_neuf.py"],
    "untracked": 1,
    "bytes": 3 * 1024**2,
}
DOCKER = fiche("docker", rootless=False)
cmd = container_runtime.commande


class TestImage(unittest.TestCase):
    def test_parse_image_lines_podman_and_docker(self):
        text = (
            "localhost/erplibre-isobuilder:20310301\n"
            "localhost/erplibre-isobuilder:latest\n"
            "erplibre-isobuilder:20310310\n"
            "erplibre-isobuilder:essai\n"
            "autre-image:20310311\n"
            "<none>:<none>\n"
        )
        self.assertEqual(cb.parse_image_lines(text), ["20310301", "20310310"])

    def test_fresh_tag_takes_newest_within_age(self):
        self.assertEqual(
            cb.fresh_tag(["20310301", "20310310"], TODAY), "20310310"
        )
        self.assertEqual(cb.fresh_tag(["20310301"], TODAY), "20310301")
        self.assertIsNone(cb.fresh_tag(["20310228"], TODAY))
        self.assertIsNone(cb.fresh_tag([], TODAY))
        # Horloge reculée : l'image existe, elle est reprise.
        self.assertEqual(cb.fresh_tag(["20310401"], TODAY), "20310401")

    def test_build_argv_pulls_and_never_reuses_cache(self):
        argv = cb.build_argv(PODMAN, cmd, "20310315")
        self.assertEqual(
            argv,
            [
                "podman",
                "build",
                "--pull=always",
                "--no-cache",
                "-t",
                "erplibre-isobuilder:20310315",
                "-t",
                "erplibre-isobuilder:latest",
                "-f",
                str(cb.CONTAINERFILE),
                str(cb.CONTAINER_DIR),
            ],
        )
        self.assertEqual(
            cb.build_argv(DOCKER, cmd, "x")[:3], ["docker", "build", "--pull"]
        )

    def test_images_and_rmi_argv(self):
        self.assertEqual(
            cb.images_argv(PODMAN, cmd),
            [
                "podman",
                "images",
                "--format",
                "{{.Repository}}:{{.Tag}}",
                "erplibre-isobuilder",
            ],
        )
        sudo_docker = fiche("docker", sans_sudo=False, avec_sudo=True)
        self.assertEqual(
            cb.rmi_argv(sudo_docker, cmd, "20310301"),
            ["sudo", "docker", "rmi", "erplibre-isobuilder:20310301"],
        )

    def test_containerfile_matches_container_uid(self):
        """La plage subuid du Containerfile commence juste après
        CONTAINER_UID, l'UID que --userns=keep-id donne à l'appelant."""
        text = cb.CONTAINERFILE.read_text()
        uid = cb.CONTAINER_UID
        for name in ("subuid", "subgid"):
            match = re.search(rf'"(\d+):(\d+):(\d+)" > /etc/{name}', text)
            self.assertIsNotNone(match, name)
            owner, first, count = map(int, match.groups())
            self.assertEqual(owner, uid)
            self.assertEqual(first, uid + 1)
            # Les UID que possède l'espace de noms d'un Podman sans root
            # (0 à 65536 avec la plage usuelle de l'hôte).
            self.assertLessEqual(first + count - 1, 65536)
        self.assertIn("setcap cap_setuid+ep /usr/bin/newuidmap", text)
        self.assertIn("archiso", text)
        self.assertIn("pacman -Syu", text)


class TestRuntime(unittest.TestCase):
    def test_strategy(self):
        self.assertEqual(cb.strategy(PODMAN), cb.STRATEGY_USERNS)
        self.assertEqual(
            cb.strategy(fiche("podman", sans_sudo=False, avec_sudo=True)),
            cb.STRATEGY_ROOT,
        )
        self.assertEqual(
            cb.strategy(fiche("podman", rootless=False)), cb.STRATEGY_ROOT
        )
        self.assertEqual(cb.strategy(DOCKER), cb.STRATEGY_ROOT)
        self.assertEqual(
            cb.strategy(fiche("docker", sans_sudo=False, avec_sudo=True)),
            cb.STRATEGY_ROOT,
        )
        # Docker sans root : ni devtmpfs, ni keep-id.
        self.assertIsNone(cb.strategy(fiche("docker", rootless=True)))

    def test_pick_runtime_order(self):
        mort = fiche("podman", sans_sudo=False)
        self.assertIs(cb.pick_runtime([DOCKER, PODMAN]), PODMAN)
        self.assertIs(cb.pick_runtime([DOCKER, mort]), DOCKER)
        self.assertIs(cb.pick_runtime([DOCKER, PODMAN], "docker"), DOCKER)
        self.assertIsNone(cb.pick_runtime([DOCKER, mort], "podman"))
        # Sans sudo avant par sudo, quel que soit l'ordre de préférence.
        podman_sudo = fiche("podman", sans_sudo=False, avec_sudo=True)
        self.assertIs(cb.pick_runtime([DOCKER, podman_sudo]), DOCKER)
        self.assertIs(cb.pick_runtime([podman_sudo]), podman_sudo)
        self.assertIsNone(cb.pick_runtime([fiche("docker", rootless=True)]))
        self.assertIsNone(cb.pick_runtime([]))


class TestRunArgv(unittest.TestCase):
    INNER = ["python3", "x"]

    def test_userns_runs_unprivileged(self):
        argv = cb.run_argv(
            PODMAN, cmd, "img:1", "/depot", "/sortie", "/cache", self.INNER
        )
        self.assertEqual(
            argv,
            [
                "podman",
                "run",
                "--rm",
                "--userns=keep-id:uid=1000,gid=1000",
                "--security-opt",
                "unmask=/proc/*",
                "--security-opt",
                "label=disable",
                "--security-opt",
                "apparmor=unconfined",
                "-e",
                "PYTHONDONTWRITEBYTECODE=1",
                "-e",
                "PYTHONUNBUFFERED=1",
                "-v",
                "/depot:/src:ro",
                "-v",
                "/sortie:/out",
                "-v",
                "/cache:/var/cache/pacman/pkg",
                "img:1",
                "python3",
                "x",
            ],
        )
        self.assertNotIn("--privileged", argv)
        self.assertNotIn("--cap-add", argv)

    def test_root_adds_sys_admin_only(self):
        argv = cb.run_argv(
            fiche("docker", sans_sudo=False, avec_sudo=True),
            cmd,
            "img:1",
            "/depot",
            "/sortie",
            "/cache",
            self.INNER,
            work_parent="/travail",
        )
        self.assertEqual(
            argv[:6],
            ["sudo", "docker", "run", "--rm", "--cap-add", "SYS_ADMIN"],
        )
        self.assertNotIn("--privileged", argv)
        self.assertNotIn("--userns=keep-id:uid=1000,gid=1000", argv)
        self.assertIn("/travail:/work", argv)
        # « deny mount » du profil AppArmor par défaut et l'étiquette
        # SELinux des volumes : levés pour root aussi.
        texte = " ".join(argv)
        self.assertIn("--security-opt apparmor=unconfined", texte)
        self.assertIn("--security-opt label=disable", texte)

    def test_refuses_colon_in_path_and_unsupported_runtime(self):
        with self.assertRaises(ValueError):
            cb.run_argv(PODMAN, cmd, "i", "/a:b", "/o", "/c", self.INNER)
        with self.assertRaises(ValueError):
            cb.run_argv(
                fiche("docker", rootless=True),
                cmd,
                "i",
                "/d",
                "/o",
                "/c",
                self.INNER,
            )

    def test_inner_argv(self):
        argv = cb.inner_argv(["--branch", "b"], EPOCH)
        self.assertEqual(
            argv,
            [
                "python3",
                "/src/script/iso/archlinux/build_iso.py",
                "--builder",
                "host",
                "--output-dir",
                "/out",
                "--work-dir",
                cb.INNER_WORK,
                "--source-date-epoch",
                str(EPOCH),
                "--branch",
                "b",
            ],
        )
        argv = cb.inner_argv(
            [], EPOCH, work_name="w1", keep_work=True, owner="1234:5678"
        )
        self.assertIn("/work/w1", argv)
        self.assertIn("--keep-work", argv)
        self.assertEqual(
            argv[-4:],
            ["--chown", "1234:5678", "--chown-tree", cb.PKG_CACHE],
        )


class TestMainContainer(unittest.TestCase):
    def _main(self, *argv, fiches=(PODMAN,), tags=(), run=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(
                mock.patch.object(
                    build_iso, "_runtime_facts", return_value=list(fiches)
                )
            )
            stack.enter_context(
                mock.patch.object(
                    build_iso, "_image_tags", return_value=list(tags)
                )
            )
            stack.enter_context(
                mock.patch.object(
                    build_iso.datetime,
                    "date",
                    mock.Mock(today=mock.Mock(return_value=TODAY)),
                )
            )
            stack.enter_context(
                mock.patch.object(build_iso.time, "time", return_value=EPOCH)
            )
            stack.enter_context(
                mock.patch.object(
                    build_iso, "read_checkout", return_value=CHECKOUT
                )
            )
            if run is not None:

                class FakePopen:
                    def __init__(self, argv, **kw):
                        self.rc = run(argv, **kw).returncode

                    def wait(self):
                        return self.rc

                stack.enter_context(
                    mock.patch.object(build_iso.subprocess, "run", run)
                )
                stack.enter_context(
                    mock.patch.object(build_iso.subprocess, "Popen", FakePopen)
                )
            stack.enter_context(contextlib.redirect_stdout(out))
            stack.enter_context(contextlib.redirect_stderr(err))
            rc = build_iso.main(list(argv))
        return rc, out.getvalue(), err.getvalue()

    def test_default_builder_is_container_and_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "iso"
            cache = Path(tmp) / "cache"
            rc, text, _err = self._main(
                "--dry-run",
                "--output-dir",
                str(out_dir),
                "--pkg-cache",
                str(cache),
                tags=["20310310"],
            )
            self.assertEqual(rc, 0)
            self.assertFalse(out_dir.exists())
            self.assertFalse(cache.exists())
        self.assertIn("erplibre-isobuilder:20310310 (reprise)", text)
        self.assertNotIn("build       :", text)
        self.assertIn("podman run --rm --userns=keep-id", text)
        self.assertIn("--source-date-epoch 1700000000", text)
        self.assertIn(build_iso.iso_basename(EPOCH), text)
        self.assertIn("checkout    : 2 fichiers, dont 1 non suivis", text)
        self.assertIn(
            "--checkout-list /out/.erplibre-checkout-1700000000.list", text
        )

    def test_stale_or_refreshed_image_is_rebuilt(self):
        rc, text, _err = self._main(
            "--dry-run", "--output-dir", "/o", tags=["20310101"]
        )
        self.assertEqual(rc, 0)
        self.assertIn("erplibre-isobuilder:20310315 (à construire)", text)
        self.assertIn("podman build --pull=always --no-cache", text)
        # --refresh-image reconstruit même une image du jour.
        rc, text, _err = self._main(
            "--dry-run",
            "--refresh-image",
            "--output-dir",
            "/o",
            tags=["20310315"],
        )
        self.assertEqual(rc, 0)
        self.assertIn("(à construire)", text)

    def test_docker_gets_chown_and_sys_admin(self):
        rc, text, _err = self._main(
            "--dry-run",
            "--output-dir",
            "/o",
            fiches=[fiche("podman", sans_sudo=False), DOCKER],
            tags=["20310315"],
        )
        self.assertEqual(rc, 0)
        self.assertIn("docker run --rm --cap-add SYS_ADMIN", text)
        self.assertIn(f"--chown {os.getuid()}:{os.getgid()}", text)

    def test_options_reach_the_inner_build(self):
        rc, text, _err = self._main(
            "--dry-run",
            "--output-dir",
            "/o",
            "--branch",
            "branche-test",
            "--auto-default",
            "gnome",
            "--lang",
            "en",
            tags=["20310315"],
        )
        self.assertEqual(rc, 0)
        self.assertIn("--branch branche-test", text)
        self.assertIn("--auto-default gnome", text)
        self.assertIn("--lang en", text)
        self.assertIn("erplibre-archlinux-autotest-", text)

    def test_keep_work_mounts_host_work_and_refuses_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "w1"
            rc, text, _err = self._main(
                "--dry-run",
                "--keep-work",
                "--work-dir",
                str(work),
                "--output-dir",
                "/o",
                tags=["20310315"],
            )
            self.assertEqual(rc, 0)
            self.assertIn(f"{tmp}:/work", text)
            self.assertIn("--work-dir /work/w1", text)
            work.mkdir()
            rc, _text, err = self._main(
                "--dry-run",
                "--work-dir",
                str(work),
                "--output-dir",
                "/o",
                tags=["20310315"],
            )
            self.assertEqual(rc, 1)
            self.assertIn("existe déjà", err)

    def test_refusals(self):
        rc, _t, err = self._main("--dry-run", "--output-dir", "/o", fiches=[])
        self.assertEqual(rc, 2)
        self.assertIn("--builder host", err)
        rc, _t, err = self._main(
            "--dry-run", "--releng", "/ailleurs", "--output-dir", "/o"
        )
        self.assertEqual(rc, 2)
        self.assertIn("--releng", err)
        rc, _t, err = self._main(
            "--dry-run", "--output-dir", "/o", "--chown", "pas-un-uid"
        )
        self.assertEqual(rc, 2)

    def test_auto_falls_back_to_host(self):
        with mock.patch.object(
            build_iso, "_main_host", return_value=0
        ) as host:
            rc, text, _err = self._main(
                "--builder", "auto", "--dry-run", fiches=[]
            )
        self.assertEqual(rc, 0)
        host.assert_called_once()
        self.assertIn("construction sur l'hôte", text)

    def test_real_run_builds_image_prunes_and_reports_host_iso(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "iso"

            liste = out_dir / build_iso.CHECKOUT_LIST_NAME.format(epoch=EPOCH)
            vues = []

            def run(argv, **_kw):
                calls.append(argv)
                if argv[1] == "run":
                    # Le conteneur lit la liste sous /out pendant son run.
                    vues.append(liste.read_bytes())
                    name = build_iso.iso_basename(EPOCH)
                    (out_dir / name).write_bytes(b"iso")
                return subprocess.CompletedProcess(argv, 0)

            rc, text, _err = self._main(
                "--output-dir",
                str(out_dir),
                "--pkg-cache",
                str(Path(tmp) / "cache"),
                tags=["20310101"],
                run=run,
            )
            self.assertEqual(rc, 0)
            self.assertTrue((Path(tmp) / "cache").is_dir())
            self.assertFalse(liste.exists())
        self.assertEqual(
            vues,
            [b"script/todo/todo.py\0script/todo/exemple_neuf.py\0"],
        )
        self.assertIn(f"--checkout-list /out/{liste.name}", " ".join(calls[2]))
        verbs = [a[1] for a in calls]
        self.assertEqual(verbs, ["build", "rmi", "run"])
        self.assertEqual(calls[1][-1], "erplibre-isobuilder:20310101")
        self.assertIn(str(out_dir / build_iso.iso_basename(EPOCH)), text)
        self.assertIn("Durée", text)

    def test_failed_image_build_stops_before_run(self):
        calls = []

        def run(argv, **_kw):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 1)

        with tempfile.TemporaryDirectory() as tmp:
            rc, _text, err = self._main(
                "--output-dir",
                str(Path(tmp) / "iso"),
                "--pkg-cache",
                str(Path(tmp) / "cache"),
                run=run,
            )
        self.assertEqual(rc, 1)
        self.assertEqual([a[1] for a in calls], ["build"])
        self.assertIn("image", err)

    def test_failed_run_without_iso(self):
        def run(argv, **_kw):
            return subprocess.CompletedProcess(argv, -15)

        with tempfile.TemporaryDirectory() as tmp:
            rc, _text, err = self._main(
                "--output-dir",
                str(Path(tmp) / "iso"),
                "--pkg-cache",
                str(Path(tmp) / "cache"),
                tags=["20310315"],
                run=run,
            )
        self.assertEqual(rc, 143)
        self.assertIn("conteneur", err)


class TestChown(unittest.TestCase):
    def test_parse_owner(self):
        self.assertEqual(build_iso.parse_owner("12:34"), (12, 34))
        for bad in ("", "12", "a:b", "12:34:56"):
            with self.assertRaises(ValueError):
                build_iso.parse_owner(bad)

    def test_chown_outputs_spares_build_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "work"
            (work / "profile/airootfs").mkdir(parents=True)
            (work / "profile/airootfs/f").write_text("x")
            (work / "build/x86_64").mkdir(parents=True)
            iso = Path(tmp) / "a.iso"
            iso.write_text("x")
            seen = []
            with mock.patch.object(
                build_iso.os, "lchown", lambda p, u, g: seen.append(str(p))
            ):
                build_iso.chown_outputs(
                    (7, 8),
                    [iso, Path(tmp) / "absent.sha256", work],
                    [work / "profile"],
                )
        self.assertIn(str(iso), seen)
        self.assertIn(str(work), seen)
        self.assertIn(str(work / "profile/airootfs/f"), seen)
        # Comparé au chemin de WORK/build lui-même : le TMPDIR du lanceur
        # de tests porte « build » dans son nom.
        build = str(work / "build")
        self.assertFalse(any(p.startswith(build) for p in seen))
        self.assertNotIn(str(Path(tmp) / "absent.sha256"), seen)


if __name__ == "__main__":
    unittest.main()
