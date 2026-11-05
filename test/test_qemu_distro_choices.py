#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""QEMU/KVM et Proxmox VE : la distribution, la version et l'architecture,
sous les règles des choix.

Chacune se choisit par son numéro ou son nom tel que la liste l'écrit ;
une réponse vide prend le défaut, que la liste marque ; une faute est dite
et la question revient, au lieu de prendre le défaut en silence ; [0]
revient, et chaque appelant s'arrête alors avant de rien télécharger,
créer ni déployer. Chaque liste de réponses finit par une réponse
acceptée ou « 0 ».

Les hôtes, les commandes et le module de déploiement sont doublés : rien
n'est lancé.
"""

import io
import sys
import types
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.argv = ["todo.py"]
from script.todo.todo import TODO  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402

MOD = types.SimpleNamespace(
    DISTROS={"forged": ({"1": ("c", "o", 1, "1G")}, "1")}
)


class _Execute:
    """Note chaque commande, sans rien lancer."""

    def __init__(self):
        self.cmds = []

    def exec_command_live(self, cmd, **opts):
        self.cmds.append(cmd)
        return 0


class _Cas(unittest.TestCase):
    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.todo._qemu_stat_avg = lambda *a: ""
        self.todo._native_arch = lambda: "amd64"
        self.todo.execute = _Execute()
        self.shows = []
        self.todo._pve_show = lambda cmd, **k: (
            self.shows.append(cmd)
            or (
                0,
                "",
            )
        )
        self.todo._qemu_import_module = lambda: MOD

    def play(self, method, *answers, args=()):
        """Ce que rend `method` quand `input` reçoit `answers` ; ce qui
        s'imprime va dans `self.shown`, les invites dans `self.asked`."""
        out = io.StringIO()
        with (
            mock.patch("builtins.input", side_effect=answers) as asked,
            redirect_stdout(out),
        ):
            got = getattr(self.todo, method)(*args)
        self.shown = out.getvalue()
        self.asked = [call.args[0] for call in asked.call_args_list]
        return got

    def refused(self):
        return [
            line[len(t("Invalid choice: ")) :]
            for line in self.shown.splitlines()
            if line.startswith(t("Invalid choice: "))
        ]


class TestLaDistributionEtLaVersion(_Cas):
    def test_a_number_or_a_name_as_shown_and_blank_the_marked_default(self):
        for answer, distro in (
            ("", "ubuntu"),
            ("2", "debian"),
            ("arch", "arch"),
        ):
            with self.subTest(answer=answer):
                self.assertEqual(
                    self.play("_qemu_prompt_distro", answer), distro
                )
        self.assertIn(f"[1] ubuntu {t('(default)')}\n", self.shown)
        for answer, version in (("", "42"), ("1", "41"), ("44", "44")):
            with self.subTest(version=answer):
                got = self.play(
                    "_qemu_prompt_version", answer, args=("fedora",)
                )
                self.assertEqual(got, version)
        self.assertIn(f"[2] 42 {t('(default)')}\n", self.shown)
        self.assertNotIn("*", self.shown)

    def test_an_invalid_answer_is_named_and_asked_again(self):
        # « 01 », un nom d'une autre casse, un numéro hors de la liste ou
        # écrit autrement qu'elle ne l'affiche sont refusés, et ne prennent
        # jamais le défaut.
        wrong = ["01", "Debian", "10", "²", "x"]
        self.assertEqual(
            self.play("_qemu_prompt_distro", *wrong, "2"), "debian"
        )
        self.assertEqual(self.refused(), wrong)
        wrong = ["041", "+1", "9", "ubuntu"]
        got = self.play("_qemu_prompt_version", *wrong, "0", args=("fedora",))
        self.assertIsNone(got)
        self.assertEqual(self.refused(), wrong)

    def test_zero_goes_back(self):
        self.assertIsNone(self.play("_qemu_prompt_distro", "0"))
        self.assertIsNone(
            self.play("_qemu_prompt_version", "0", args=("debian",))
        )


class TestLArchitecture(_Cas):
    def test_a_number_a_name_or_its_alias_and_blank_the_native(self):
        cases = (
            ("", "amd64"),
            ("2", "arm64"),
            ("aarch64", "arm64"),
            ("x86_64", "amd64"),
            ("s390x", "s390x"),
            ("4", "all"),
            ("all", "all"),
        )
        for answer, arch in cases:
            with self.subTest(answer=answer):
                self.assertEqual(
                    self.play("_qemu_prompt_infra_arch", answer), arch
                )
        native = f"[1] amd64 (x86_64) — {t('native')} {t('(default)')}\n"
        self.assertIn(native, self.shown)
        every = t("All supported architectures")
        # « all » se tape parce que la liste l'écrit.
        self.assertIn(f"[4] all — {every}\n", self.shown)
        # Une arch émulée et « all » avertissent encore, la native jamais.
        self.play("_qemu_prompt_infra_arch", "arm64")
        emulated = t(
            "This architecture is emulated (TCG): boot and install are"
            " much slower than the native one."
        )
        self.assertIn(emulated, self.shown)
        self.play("_qemu_prompt_infra_arch", "all")
        note = t("(includes emulated architectures — some VMs are slow)")
        self.assertIn(note, self.shown)
        self.play("_qemu_prompt_infra_arch", "")
        self.assertNotIn("⚠", self.shown)

    def test_an_invalid_answer_is_named_and_zero_goes_back(self):
        # « * » et une autre casse sont refusés : « * » ne vaut « tout » que
        # dans un choix multiple.
        wrong = ["*", "AMD64", "5", "01"]
        self.assertIsNone(self.play("_qemu_prompt_infra_arch", *wrong, "0"))
        self.assertEqual(self.refused(), wrong)
        self.assertNotIn("⚠", self.shown)


class TestLesAppelantsReviennentSur0(_Cas):
    """[0] à la distribution, ou à la version après la distribution par
    défaut : rien n'est téléchargé, créé ni déployé, et aucune autre
    question n'est posée."""

    BACK = (("0",), ("", "0"))

    def test_download_an_image_downloads_nothing(self):
        self.todo._qemu_script_path = lambda: "/forged/deploy_qemu.py"
        for answers in self.BACK:
            with self.subTest(answers=answers):
                self.assertIsNone(self.play("_qemu_download_image", *answers))
                self.assertEqual(len(self.asked), len(answers))
        self.assertEqual(self.todo.execute.cmds, [])
        self.play("_qemu_download_image", "2", "", "n")
        [cmd] = self.todo.execute.cmds
        self.assertIn("--distro debian --version 12", cmd)

    def test_proxmox_fetches_and_deploys_nothing(self):
        self.todo._pve_host = lambda: {"target": "root@forged-pve"}
        for method in ("_pve_fetch_image", "_pve_deploy_prompts"):
            for answers in self.BACK:
                with self.subTest(method=method, answers=answers):
                    self.assertIsNone(self.play(method, *answers))
                    self.assertEqual(len(self.asked), len(answers))
        self.assertEqual(self.shows, [])

    def test_the_deployment_catalogue_deploys_nothing(self):
        got = self.play("_qemu_collect_vms_cli", "0", args=(MOD,))
        self.assertIsNone(got)
        self.assertEqual(len(self.asked), 1)


if __name__ == "__main__":
    unittest.main()
