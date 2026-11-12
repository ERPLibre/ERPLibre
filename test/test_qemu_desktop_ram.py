#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Une VM graphique : plancher de RAM, saveurs offertes, système transmis.

Le minimum du catalogue est celui d'un serveur (1024 Mo pour Debian ou Arch),
et un bureau ne tient pas dedans. La CLI choisit les ressources AVANT le type
de VM : le relèvement doit donc se faire après la question du type, et se
voir au récapitulatif. Le formulaire, lui, le fait dès qu'une rangée devient
graphique. Une seule fonction décide pour les deux, et
`_qemu_build_deploy_parts` la rappelle en dernier rempart.

Une saveur n'est offerte qu'aux systèmes qui l'installent : NixOS n'en
installe aucune, et le bloc du bureau y échouerait sur « gestionnaire de
paquets inconnu ». Ce bloc reçoit aussi le système de la VM, dont ses paquets
et son accès distant dépendent au-delà du gestionnaire de paquets.
"""

import io
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.argv = ["todo.py"]

from script.todo.deploy_form_lib import (  # noqa: E402
    build_vms,
    desktop_ram,
    desktops_for,
    desktops_for_fleet,
    raise_desktop_ram,
)
from script.todo.todo import TODO  # noqa: E402

try:
    import textual  # noqa: F401

    TEXTUAL = True
except Exception:  # pragma: no cover - dépend de l'environnement
    TEXTUAL = False

PLANCHER = 4096


class _Arret(Exception):
    """Interrompt la collecte CLI juste après le type de VM."""


def _todo():
    todo = TODO.__new__(TODO)
    todo._host_free_ram_mb = lambda: 0
    return todo


class TestLePlancher(unittest.TestCase):
    def test_the_floor_is_the_one_the_installer_declares(self):
        self.assertEqual(PLANCHER, TODO.QEMU_DESKTOP_MIN_RAM_MB)

    def test_a_desktop_is_raised_to_the_floor(self):
        self.assertEqual(PLANCHER, desktop_ram(1024, "gnome", PLANCHER))

    def test_a_larger_value_is_kept(self):
        self.assertEqual(8192, desktop_ram(8192, "gnome", PLANCHER))

    def test_a_server_keeps_its_ram(self):
        self.assertEqual(1024, desktop_ram(1024, "", PLANCHER))
        self.assertEqual(1024, desktop_ram(1024, None, PLANCHER))

    def test_a_null_floor_changes_nothing(self):
        self.assertEqual(1024, desktop_ram(1024, "gnome", 0))

    def test_raise_in_place_names_only_what_changed(self):
        vms = [
            {"name": "a", "ram": 1024, "desktop": "gnome"},
            {"name": "b", "ram": 8192, "desktop": "gnome"},
            {"name": "c", "ram": 1024, "desktop": ""},
        ]
        relevees = raise_desktop_ram(vms, PLANCHER)
        self.assertEqual(["a"], [vm["name"] for vm in relevees])
        self.assertEqual([4096, 8192, 1024], [vm["ram"] for vm in vms])


class TestLesSaveursOffertes(unittest.TestCase):
    CLES = ["gnome", "cinnamon"]

    def test_nixos_gets_no_desktop(self):
        self.assertEqual([], TODO._qemu_desktops_for("nixos"))

    def test_the_imperative_families_get_gnome(self):
        for distro in ("ubuntu", "debian", "fedora", "arch"):
            self.assertIn("gnome", TODO._qemu_desktops_for(distro), distro)

    def test_a_distro_absent_from_the_map_keeps_every_flavour(self):
        self.assertEqual(self.CLES, desktops_for("x", self.CLES, {}))

    def test_the_fleet_is_offered_the_union(self):
        carte = {"nixos": [], "debian": ["gnome"]}
        self.assertEqual(
            ["gnome"],
            desktops_for_fleet(["nixos", "debian"], self.CLES, carte),
        )
        self.assertEqual([], desktops_for_fleet(["nixos"], self.CLES, carte))

    def test_the_cli_question_leaves_nixos_out(self):
        buf = io.StringIO()
        with (
            mock.patch("builtins.input", lambda *a: "2") as _i,
            mock.patch("sys.stdout", buf),
        ):
            self.assertEqual("", _todo()._qemu_ask_desktop(["nixos"]))
        # Aucune saveur : la question n'est même pas posée.
        self.assertNotIn("GNOME", buf.getvalue())

    def test_the_cli_question_offers_a_mixed_fleet_its_desktops(self):
        buf = io.StringIO()
        with (
            mock.patch("builtins.input", lambda *a: "2"),
            mock.patch("sys.stdout", buf),
        ):
            choix = _todo()._qemu_ask_desktop(["debian", "nixos"])
        self.assertEqual("gnome", choix)
        self.assertIn("GNOME", buf.getvalue())

    def test_build_vms_leaves_a_nixos_vm_a_server(self):
        entries = [
            {
                "name": n,
                "distro": d,
                "version": "1",
                "arch": "amd64",
                "ram": 1024,
                "disk": "20G",
            }
            for n, d in (("vm-nix", "nixos"), ("vm-deb", "debian"))
        ]
        vms = build_vms(
            entries,
            "1",
            2,
            8,
            {},
            {},
            desktop="gnome",
            suffixes={"gnome": "gnome"},
            by_distro={"nixos": [], "debian": ["gnome"]},
            min_ram=PLANCHER,
        )
        nix, deb = vms
        self.assertEqual("", nix["desktop"])
        self.assertEqual(1024, nix["ram"])
        self.assertEqual("vm-nix", nix["name"])
        self.assertEqual("gnome", deb["desktop"])
        self.assertEqual(PLANCHER, deb["ram"])
        self.assertEqual("vm-deb-gnome", deb["name"])


class TestLaCli(unittest.TestCase):
    """Le chemin en ligne : ressources choisies, PUIS le type de VM."""

    def _collecte(self, vms, desktop_answer):
        todo = _todo()
        todo._qemu_default_ssh_key = lambda: "/k.pub"
        todo._qemu_ask_timezone = lambda: "UTC"
        todo._qemu_ask_locale = lambda: "C.UTF-8"
        vu = {}

        def arret(vms_):
            vu["vms"] = [dict(vm) for vm in vms_]
            raise _Arret

        todo._qemu_ask_app_store = arret
        reponses = iter(["", desktop_answer])
        buf = io.StringIO()
        with (
            mock.patch("builtins.input", lambda *a: next(reponses)),
            mock.patch("sys.stdout", buf),
        ):
            with self.assertRaises(_Arret):
                todo._qemu_collect_options_cli(vms, "x1")
        return vu["vms"], buf.getvalue()

    @staticmethod
    def _vm(name, distro, ram):
        return TODO._qemu_make_vm(distro, "13", "amd64", ram, "20G", 2, name)

    def test_a_desktop_raises_the_ram_after_the_question(self):
        vms, out = self._collecte([self._vm("vm-deb", "debian", 1024)], "2")
        self.assertEqual("gnome", vms[0]["desktop"])
        self.assertEqual(PLANCHER, vms[0]["ram"])
        self.assertIn(str(PLANCHER), out)
        self.assertIn("vm-deb-gnome", out)

    def test_a_larger_ram_is_kept(self):
        vms, _out = self._collecte([self._vm("vm-deb", "debian", 8192)], "2")
        self.assertEqual(8192, vms[0]["ram"])

    def test_a_server_is_left_alone(self):
        vms, _out = self._collecte([self._vm("vm-deb", "debian", 1024)], "")
        self.assertEqual("", vms[0]["desktop"])
        self.assertEqual(1024, vms[0]["ram"])

    def test_a_nixos_vm_of_a_mixed_fleet_stays_a_server(self):
        vms, out = self._collecte(
            [
                self._vm("vm-deb", "debian", 1024),
                self._vm("vm-nix", "nixos", 1024),
            ],
            "2",
        )
        deb, nix = vms
        self.assertEqual("gnome", deb["desktop"])
        self.assertEqual("", nix["desktop"])
        self.assertEqual(1024, nix["ram"])
        self.assertEqual("vm-nix", nix["name"])
        self.assertIn("vm-nix", out)

    def test_the_recap_shows_the_raised_value(self):
        """Une spec venue d'ailleurs que la CLI garde la même lecture : le
        récapitulatif affiche ce que « --memory » recevra."""
        todo = _todo()
        todo._qemu_image_lines = lambda spec: []
        todo._qemu_sudo_lines = lambda: []
        spec = {
            "vms": [
                dict(self._vm("vm-deb-gnome", "debian", 1024), desktop="gnome")
            ],
            "desktop": "gnome",
            "install": None,
            "ssh_key": "/k.pub",
            "add_ssh_config": False,
            "parallelism": 1,
        }
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            todo._qemu_print_recap(spec, [])
        self.assertIn(f"RAM {PLANCHER}Mo", buf.getvalue())
        self.assertNotIn("RAM 1024Mo", buf.getvalue())


class TestLaCommandeDeploiement(unittest.TestCase):
    """Le dernier rempart : la commande deploy_qemu.py elle-même."""

    def _memory(self, ram, desktop):
        parts = _todo()._qemu_build_deploy_parts(
            "debian",
            "13",
            "amd64",
            "vm",
            ram,
            2,
            "20G",
            None,
            None,
            True,
            desktop=desktop,
        )
        return int(parts[parts.index("--memory") + 1])

    def test_memory_reaches_the_floor_with_a_desktop(self):
        self.assertGreaterEqual(self._memory(1024, "gnome"), PLANCHER)

    def test_memory_keeps_a_larger_value(self):
        self.assertEqual(8192, self._memory(8192, "gnome"))

    def test_memory_of_a_server_is_untouched(self):
        self.assertEqual(1024, self._memory(1024, ""))


class TestLeSystemeAtteintLeBureau(unittest.TestCase):
    """Le bloc du bureau reçoit le système de la VM, sur les deux chemins."""

    def _todo(self):
        todo = _todo()
        appels = []

        def bureau(flavour, app_store, **kw):
            appels.append((flavour, app_store, kw))
            return "echo bureau; "

        todo._qemu_desktop_remote_cmd = bureau
        return todo, appels

    def test_desktop_only(self):
        todo, appels = self._todo()
        cmd = todo._qemu_erplibre_remote_cmd(
            None, desktop="gnome", distro="fedora"
        )
        self.assertEqual([("gnome", "deb", {"distro": "fedora"})], appels)
        subprocess.run(["bash", "-n", "-c", cmd], check=True)

    def test_with_erplibre(self):
        todo, appels = self._todo()
        cmd = todo._qemu_erplibre_remote_cmd(
            "develop", desktop="gnome", distro="arch"
        )
        self.assertEqual([("gnome", "deb", {"distro": "arch"})], appels)
        subprocess.run(["bash", "-n", "-c", cmd], check=True)

    def test_the_per_vm_loop_passes_each_vms_distro(self):
        """Un bureau commun suffit à imposer une commande PAR VM : sans elle
        la commande commune, qui ignore le système, servirait tout le parc."""
        todo, appels = self._todo()
        captures = {}

        def lancer(vms, branch, remote, **kw):
            captures["vms"] = vms
            raise _Arret

        with mock.patch(
            "script.todo.qemu_install_monitor.launch_installs", lancer
        ):
            with self.assertRaises(_Arret):
                todo._qemu_install_erplibre_monitored(
                    ["vm-a", "vm-b"],
                    None,
                    desktop="gnome",
                    ip_map={"vm-a": "192.0.2.10", "vm-b": "192.0.2.11"},
                    meta={
                        "vm-a": ("debian", "13", "amd64"),
                        "vm-b": ("fedora", "44", "amd64"),
                    },
                )
        recus = [kw.get("distro") for _f, _s, kw in appels]
        self.assertIn("debian", recus)
        self.assertIn("fedora", recus)
        self.assertTrue(all("remote_cmd" in e for e in captures["vms"]))


@unittest.skipUnless(TEXTUAL, "Textual absent")
class TestLeFormulaire(unittest.TestCase):
    """La rangée du formulaire : son type et sa RAM."""

    @staticmethod
    def _contexte():
        todo = TODO.__new__(TODO)
        mod = todo._qemu_import_module()
        todo._qemu_list_domains = lambda: []
        todo._qemu_branch_list = lambda: ["develop", "master"]
        ctx = todo._qemu_form_context(mod)
        ctx["free_ram"] = 64000
        ctx["host_cpu"] = 64
        return ctx

    def _scenario(self, distro, actions):
        import asyncio

        from script.todo.qemu_deploy_form import run_deploy_form

        ctx = self._contexte()
        vu = {}

        async def jouer():
            from textual.widgets import Select, SelectionList

            app = run_deploy_form(ctx, run_app=False)
            async with app.run_test(size=(200, 50)) as pilote:
                await pilote.pause()
                liste = app.query_one(SelectionList)
                rang = next(
                    i
                    for i, e in enumerate(app._entries())
                    if e["distro"] == distro and int(e["ram"]) < PLANCHER
                )
                liste.select(liste.get_option_at_index(rang).value)
                for _ in range(3):
                    await pilote.pause()
                sel = app.query_one("#v0_type", Select)
                vu["options"] = [v for _l, v in sel._options]
                for valeur in actions:
                    sel.value = valeur
                    for _ in range(3):
                        await pilote.pause()
                    vu.setdefault("ram", []).append(app.rows[0]["vm"]["ram"])

        asyncio.run(jouer())
        return vu

    def test_a_row_turned_graphical_is_raised_and_stays_raised(self):
        from script.todo.deploy_form_extras import SERVER

        vu = self._scenario("debian", ["gnome", SERVER])
        self.assertEqual([PLANCHER, PLANCHER], vu["ram"])

    def test_a_nixos_row_offers_no_desktop(self):
        from script.todo.deploy_form_extras import SERVER

        vu = self._scenario("nixos", [])
        self.assertEqual([SERVER], [v for v in vu["options"] if v])


if __name__ == "__main__":
    unittest.main(verbosity=1)
