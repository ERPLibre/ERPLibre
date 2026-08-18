#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Outils de développement des VM graphiques : filtrage, disque, commande.

Ce qui se vérifie ici sans VM : qu'un outil demandé pour tout le parc n'atterrit
que sur les machines qui peuvent le recevoir, que la place disque annoncée suit
ce filtrage, et qu'un outil qui échoue ne fait pas tomber l'installation
d'ERPLibre avec lui — celle-ci ayant duré une heure.
"""

import subprocess
import sys
import unittest

sys.argv = ["todo.py"]
from script.todo.todo import TODO  # noqa: E402


class TestToolFiltering(unittest.TestCase):
    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.all = tuple(TODO._QEMU_DESKTOP_TOOLS)

    def test_a_server_gets_no_graphical_tool(self):
        """Un IDE sans bureau n'a rien pour s'afficher."""
        self.assertEqual([], self.todo._qemu_tools_for(self.all, "amd64", ""))

    def test_android_studio_is_x86_64_only(self):
        """Google ne publie aucune archive Linux aarch64 : toutes les variantes
        de l'URL rendent 404, et product-info.json ne déclare que Linux/amd64.
        """
        self.assertIn(
            "android", self.todo._qemu_tools_for(self.all, "amd64", "gnome")
        )
        for arch in ("arm64", "s390x"):
            self.assertNotIn(
                "android",
                self.todo._qemu_tools_for(self.all, arch, "gnome"),
                arch,
            )

    def test_pycharm_follows_jetbrains_two_architectures(self):
        for arch in ("amd64", "arm64"):
            self.assertIn(
                "pycharm",
                self.todo._qemu_tools_for(self.all, arch, "gnome"),
                arch,
            )
        self.assertNotIn(
            "pycharm", self.todo._qemu_tools_for(self.all, "s390x", "gnome")
        )

    def test_gnome_extensions_only_under_gnome(self):
        self.assertIn(
            "gnome_ext", self.todo._qemu_tools_for(self.all, "amd64", "gnome")
        )
        self.assertNotIn(
            "gnome_ext",
            self.todo._qemu_tools_for(self.all, "amd64", "cinnamon"),
        )

    def test_unknown_key_is_ignored(self):
        self.assertEqual(
            [], self.todo._qemu_tools_for(("nope",), "amd64", "gnome")
        )


class TestToolDisk(unittest.TestCase):
    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.all = tuple(TODO._QEMU_DESKTOP_TOOLS)

    def test_disk_follows_the_filtering(self):
        """Une VM qui ne recevra pas Android Studio ne doit pas se voir gonfler
        son disque de ses 8 Go."""
        full = self.todo._qemu_tools_disk_gb(self.all, "amd64", "gnome")
        arm = self.todo._qemu_tools_disk_gb(self.all, "arm64", "gnome")
        self.assertEqual(
            full - arm, TODO._QEMU_DESKTOP_TOOLS["android"]["disk_gb"]
        )

    def test_a_server_costs_nothing(self):
        self.assertEqual(
            0, self.todo._qemu_tools_disk_gb(self.all, "amd64", "")
        )

    def test_the_deploy_command_grows_the_disk(self):
        """Le disque demandé à deploy_qemu.py doit inclure les outils : c'est
        la seule valeur qui compte, celle du qcow2 réellement créé."""
        spec = {
            "ssh_key": "",
            "desktop": "gnome",
            "desktop_tools": self.all,
            "install": {
                "branch": "develop",
                "prod": False,
                "cmd": "make install_os && make install_odoo_18",
                "label": "x",
                "monitor": True,
            },
        }
        vm = {
            "distro": "ubuntu",
            "version": "24.04",
            "arch": "amd64",
            "name": "v",
            "ram": 3072,
            "vcpus": 4,
            "disk": "20G",
            "desktop": "gnome",
        }
        parts = self.todo._qemu_deploy_parts_for(vm, spec, dry_run=True)
        size = parts[parts.index("--disk-size") + 1]
        expected = (
            20
            + TODO.ERPLIBRE_EXTRA_DISK_GB
            + TODO.QEMU_DESKTOP_EXTRA_DISK_GB
            + sum(s["disk_gb"] for s in TODO._QEMU_DESKTOP_TOOLS.values())
        )
        self.assertEqual(f"{expected}G", size)


class TestToolRemoteCommand(unittest.TestCase):
    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.all = tuple(TODO._QEMU_DESKTOP_TOOLS)

    def _sh_ok(self, script):
        """Le shell accepte-t-il ce script ? « bash -n » ne l'exécute pas."""
        return subprocess.run(
            ["bash", "-n"], input=script, text=True, capture_output=True
        )

    def test_every_combination_is_valid_shell(self):
        combos = [
            (),
            ("pycharm",),
            ("android",),
            ("gnome_ext",),
            self.all,
        ]
        for tools in combos:
            script = self.todo._qemu_erplibre_remote_cmd(
                "develop", None, False, "gnome", "mise", "deb", tools
            )
            res = self._sh_ok(script)
            self.assertEqual(0, res.returncode, f"{tools} : {res.stderr}")

    def test_tools_come_before_the_clone_and_the_make(self):
        """L'ordre est ce qui fait marcher la configuration du projet : PyCharm
        écrit le .idea du dépôt en l'ouvrant une fois, et c'est l'installation
        qui, ENSUITE, y lance pycharm_configuration.py."""
        script = self.todo._qemu_erplibre_remote_cmd(
            "develop", None, False, "gnome", "", "deb", ("pycharm",)
        )
        self.assertLess(script.index("PyCharm"), script.index("git clone"))
        self.assertLess(
            script.index("PyCharm"), script.index("make install_os")
        )

    def test_the_install_owns_the_project_configuration(self):
        """update_env_version.pycharm_update() lance déjà le script, et sait se
        taire sans .idea. Doubler l'appel n'écrivait qu'une erreur dans le
        journal d'une VM neuve."""
        script = self.todo._qemu_erplibre_remote_cmd(
            "develop", None, False, "gnome", "", "deb", ("pycharm",)
        )
        self.assertNotIn("pycharm_configuration", script)

    def test_a_failing_tool_never_masks_a_failing_install(self):
        """Le code de sortie doit rester celui de l'installation : c'est lui que
        lit le tableau de bord pour dire ✅ ou ❌."""
        script = (
            "set -e\n"
            "curl() { return 7; }; sudo() { return 7; }\n"
            + self.todo._qemu_tools_remote_cmd(("pycharm", "android"), False)
            + "\nexit 3\n"  # l'installation qui suit, en échec
        )
        res = subprocess.run(
            ["bash", "-c", script], capture_output=True, text=True
        )
        self.assertEqual(3, res.returncode, res.stdout + res.stderr)

    def test_a_failing_tool_still_returns_zero(self):
        """Le bloc d'outils est lui-même gardé : PyCharm indisponible ne doit
        pas transformer une installation réussie en échec."""
        script = "set -e\n" + self.todo._qemu_tools_remote_cmd(self.all, False)
        # Tout ce qui pourrait réussir est neutralisé : ni réseau, ni sudo.
        stub = (
            "curl() { return 7; }; sudo() { return 7; }; tar() { return 7; }; "
            "export -f curl sudo tar 2>/dev/null || true\n"
        )
        res = subprocess.run(
            ["bash", "-c", stub + script], capture_output=True, text=True
        )
        self.assertEqual(0, res.returncode, res.stderr)
        self.assertIn("PyCharm", res.stdout)


class TestToolDiscoverability(unittest.TestCase):
    """Ce qui est installé doit pouvoir être TROUVÉ. Vécu : Android Studio
    posé dans /opt, lanceur nommé « studio », et l'utilisateur conclut à un
    échec parce que « android-studio » ne répond pas."""

    def setUp(self):
        self.todo = TODO.__new__(TODO)

    def test_android_studio_answers_to_both_names(self):
        cmd = self.todo._qemu_android_studio_remote_cmd()
        self.assertIn("/usr/local/bin/studio;", cmd)
        self.assertIn("/usr/local/bin/android-studio;", cmd)

    def test_the_log_says_where_it_landed(self):
        pycharm = self.todo._qemu_pycharm_remote_cmd()
        android = self.todo._qemu_android_studio_remote_cmd()
        self.assertIn("/opt/pycharm", pycharm)
        self.assertIn("/opt/android-studio", android)

    def test_pycharm_says_what_creates_the_project(self):
        """Le .idea n'existe qu'après une première ouverture de PyCharm : le
        journal le dit, plutôt que de laisser croire à un échec."""
        cmd = self.todo._qemu_pycharm_remote_cmd()
        self.assertIn(".idea", cmd)


class TestPycharmCommunity(unittest.TestCase):
    """PyCharm doit s'ouvrir sans compte : c'est toute la différence entre une
    VM utilisable au premier démarrage et une VM qui demande une licence."""

    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.cmd = self.todo._qemu_pycharm_remote_cmd()

    def test_the_community_line_is_what_is_looked_up(self):
        """Mesuré dans une VM : le build unifié s'arrête sur
        « NoValidIdeLicense » et n'ouvre jamais le projet."""
        self.assertIn("pycharm-community-", self.cmd)
        self.assertIn("data.services.jetbrains.com", self.cmd)

    def test_no_version_is_frozen_in_the_repository(self):
        """Le flux donne la plus récente : rien à mettre à jour ici quand
        JetBrains publie un correctif."""
        self.assertNotIn("2025.2.6", self.cmd)
        self.assertNotIn("pycharm-community-2", self.cmd)

    def test_both_architectures_are_asked_for(self):
        self.assertIn("linuxARM64", self.cmd)
        self.assertIn("jb=linux", self.cmd)

    def test_the_fallback_names_its_cost(self):
        """Le repli sert le build unifié : le dire, plutôt que de le laisser
        découvrir au premier lancement."""
        self.assertIn("code=PCC&latest", self.cmd)
        self.assertIn("JetBrains", self.cmd)


class TestPycharmFirstOpen(unittest.TestCase):
    """Ouverture sans écran, pour que le .idea existe avant l'installation."""

    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.cmd = self.todo._qemu_pycharm_project_cmd()

    def test_it_runs_between_the_clone_and_the_make(self):
        script = self.todo._qemu_erplibre_remote_cmd(
            "develop", None, False, "gnome", "", "deb", ("pycharm",)
        )
        self.assertLess(script.index("git clone"), script.index("xvfb-run"))
        self.assertLess(
            script.index("xvfb-run"), script.index("make install_os")
        )

    def test_only_when_pycharm_was_asked_for(self):
        script = self.todo._qemu_erplibre_remote_cmd(
            "develop", None, False, "gnome", "", "deb", ("android",)
        )
        self.assertNotIn("xvfb-run", script)

    def test_the_first_run_dialogs_are_answered_in_advance(self):
        """Sans réponse, la session attend un clic que personne ne donnera.

        Celle de la CONFIANCE est la plus coûteuse à rater : mesuré, le journal
        s'arrête 1,3 s après le démarrage et le projet ne s'ouvre jamais."""
        self.assertIn("idea.trust.all.projects=true", self.cmd)
        self.assertIn("jb.consents.confirmation.enabled=false", self.cmd)
        self.assertIn("consentOptions", self.cmd)
        # Le consentement est écrit REFUSÉ : aucune statistique ne part.
        self.assertIn("rsch.send.usage.stat:1.1:0:", self.cmd)

    def test_xvfb_package_names_are_per_family(self):
        """« xvfb » n'existe que chez Debian : ailleurs le paquet s'appelle
        autrement, et un nom inventé ne s'installerait pas."""
        self.assertEqual("xvfb", TODO._QEMU_XVFB_PKG["apt"])
        self.assertEqual("xorg-x11-server-Xvfb", TODO._QEMU_XVFB_PKG["dnf"])
        self.assertEqual("xorg-server-xvfb", TODO._QEMU_XVFB_PKG["pacman"])

    def test_it_gives_up_rather_than_hangs(self):
        """Un IDE qui ne s'ouvre pas ne doit pas retenir l'installation : le
        budget est borné et le processus tué."""
        self.assertIn("kill -TERM", self.cmd)
        self.assertIn("kill -KILL", self.cmd)
        self.assertIn(f"seq 1 {TODO._QEMU_PYCHARM_OPEN_TRIES}", self.cmd)

    def test_valid_shell(self):
        res = subprocess.run(
            ["bash", "-n"],
            input="set -e\n" + self.cmd,
            text=True,
            capture_output=True,
        )
        self.assertEqual(0, res.returncode, res.stderr)


class TestGnomeSiteExtensions(unittest.TestCase):
    """Extensions posées depuis extensions.gnome.org, par leur UUID."""

    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.block = self.todo._qemu_gnome_ext_remote_cmd()

    def test_the_three_requested_extensions_are_there(self):
        for uuid in (
            "gTile@vibou",
            "freon@UshakovVasilii_Github.yahoo.com",
            "tracker@aliakseiz.github.com",
        ):
            self.assertIn(uuid, self.block, uuid)

    def test_the_archive_follows_the_running_gnome(self):
        """Le site sert une archive DIFFERENTE selon la version demandée —
        gTile v59 en GNOME 46, v62 en 48 : figer une URL poserait une archive
        faite pour une autre version."""
        self.assertIn("shell_version=$sv", self.block)
        self.assertIn("gnome-shell --version", self.block)

    def test_valid_shell_and_never_fails_the_install(self):
        script = "set -e\n" + self.block
        self.assertEqual(
            0,
            subprocess.run(
                ["bash", "-n"], input=script, text=True, capture_output=True
            ).returncode,
        )
        # Sans gnome-shell dans le PATH, le bloc doit se taire proprement.
        res = subprocess.run(
            ["bash", "-c", "PATH=/nonexistent; " + script],
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, res.returncode, res.stderr)

    def test_a_session_bus_is_provided_for_dconf(self):
        """Un « ssh hote commande » n'a pas de bus de session : sans lui,
        l'activation ne peut rien ecrire dans dconf."""
        self.assertIn("dbus-run-session", self.block)


if __name__ == "__main__":
    unittest.main()
