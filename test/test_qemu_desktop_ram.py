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

Une saveur n'est offerte qu'aux systèmes qui l'installent : Proxmox VE n'en
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
    # Table inventée : un système qui reçoit GNOME dans une seule de ses
    # versions, et un autre qui n'en reçoit aucune.
    TABLE = {"debian": {"13": ["gnome"]}, "proxmox": {}}

    def test_proxmox_gets_no_desktop(self):
        self.assertEqual([], TODO._qemu_desktops_for("proxmox", "9"))

    def test_the_imperative_families_get_gnome(self):
        for distro, version in (
            ("ubuntu", "26.04"),
            ("debian", "13"),
            ("fedora", "44"),
            ("arch", "latest"),
        ):
            self.assertIn(
                "gnome", TODO._qemu_desktops_for(distro, version), distro
            )

    def test_an_unknown_version_gets_nothing(self):
        """Fermé : une version absente de la table n'en reçoit aucune,
        même d'un système qui en reçoit ailleurs."""
        self.assertEqual([], TODO._qemu_desktops_for("debian", "99"))
        self.assertEqual([], TODO._qemu_desktops_for("debian", ""))

    def test_an_empty_table_keeps_every_flavour(self):
        self.assertEqual(self.CLES, desktops_for("x", "1", self.CLES, {}))

    def test_a_pair_absent_from_the_table_gets_nothing(self):
        self.assertEqual([], desktops_for("x", "1", self.CLES, self.TABLE))
        self.assertEqual(
            [], desktops_for("debian", "12", self.CLES, self.TABLE)
        )
        self.assertEqual(
            ["gnome"], desktops_for("debian", "13", self.CLES, self.TABLE)
        )

    def test_the_fleet_is_offered_the_union(self):
        self.assertEqual(
            ["gnome"],
            desktops_for_fleet(
                [("proxmox", "9"), ("debian", "13")], self.CLES, self.TABLE
            ),
        )
        self.assertEqual(
            [],
            desktops_for_fleet(
                [("proxmox", "9"), ("debian", "12")], self.CLES, self.TABLE
            ),
        )

    def test_the_cli_question_leaves_proxmox_out(self):
        buf = io.StringIO()
        with (
            mock.patch("builtins.input", lambda *a: "2") as _i,
            mock.patch("sys.stdout", buf),
        ):
            self.assertEqual("", _todo()._qemu_ask_desktop([("proxmox", "9")]))
        # Aucune saveur : la question n'est même pas posée.
        self.assertNotIn("GNOME", buf.getvalue())

    def test_the_cli_question_offers_a_mixed_fleet_its_desktops(self):
        buf = io.StringIO()
        with (
            mock.patch("builtins.input", lambda *a: "2"),
            mock.patch("sys.stdout", buf),
        ):
            choix = _todo()._qemu_ask_desktop(
                [("debian", "13"), ("proxmox", "9")]
            )
        self.assertEqual("gnome", choix)
        self.assertIn("GNOME", buf.getvalue())

    def test_the_cli_question_follows_the_version(self):
        """Plasma 6 existe pour Debian 13 et non pour Debian 12 : la
        question ne l'offre qu'au parc qui compte une version qui l'a."""
        label = TODO._QEMU_DESKTOP["plasma"]["label"]
        for version, offert in (("12", False), ("13", True)):
            buf = io.StringIO()
            with (
                mock.patch("builtins.input", lambda *a: ""),
                mock.patch("sys.stdout", buf),
            ):
                _todo()._qemu_ask_desktop([("debian", version)])
            self.assertEqual(offert, label in buf.getvalue(), version)

    def test_build_vms_leaves_a_vm_without_the_flavour_a_server(self):
        entries = [
            {
                "name": n,
                "distro": d,
                "version": v,
                "arch": "amd64",
                "ram": 1024,
                "disk": "20G",
            }
            for n, d, v in (
                ("vm-pve", "proxmox", "9"),
                ("vm-old", "debian", "12"),
                ("vm-deb", "debian", "13"),
            )
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
            by_release=self.TABLE,
            min_ram=PLANCHER,
        )
        pve, old, deb = vms
        for vm in (pve, old):
            self.assertEqual("", vm["desktop"])
            self.assertEqual(1024, vm["ram"])
        self.assertEqual("vm-pve", pve["name"])
        self.assertEqual("vm-old", old["name"])
        self.assertEqual("gnome", deb["desktop"])
        self.assertEqual(PLANCHER, deb["ram"])
        self.assertEqual("vm-deb-gnome", deb["name"])


class TestLeTypeParRangee(unittest.TestCase):
    """Le socle commun des deux formulaires : le type commun et le type
    d'une rangée lisent la table par couple (système, version)."""

    @staticmethod
    def _ecran(table):
        from script.todo.deploy_form_extras import ExtrasMixin

        class Ecran(ExtrasMixin):
            vms = ()
            rows = ()

        ecran = Ecran()
        ecran.extras_init(
            {
                "desktops": [
                    [k, de["label"]] for k, de in TODO._QEMU_DESKTOP.items()
                ],
                "desktops_by_release": table,
            }
        )
        return ecran

    @staticmethod
    def _saveurs(options):
        from script.todo.deploy_form_extras import SERVER

        return [v for _l, v in options if v != SERVER]

    def test_a_row_is_offered_what_its_version_installs(self):
        ecran = self._ecran(TODO._qemu_desktops_by_release())
        douze = self._saveurs(ecran._type_options("debian", "12"))
        treize = self._saveurs(ecran._type_options("debian", "13"))
        self.assertIn("gnome", douze)
        self.assertNotIn("plasma", douze)
        self.assertIn("plasma", treize)
        self.assertEqual([], self._saveurs(ecran._type_options("proxmox", "")))

    def test_the_common_type_offers_what_some_release_installs(self):
        ecran = self._ecran({"debian": {"13": ["xfce"]}, "fedora": {}})
        self.assertEqual(["xfce"], [k for k, _l in ecran._extras["desktops"]])

    def test_an_empty_table_filters_nothing(self):
        ecran = self._ecran({})
        self.assertEqual(
            list(TODO._QEMU_DESKTOP),
            self._saveurs(ecran._type_options("debian", "12")),
        )


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

    def test_a_proxmox_vm_of_a_mixed_fleet_stays_a_server(self):
        vms, out = self._collecte(
            [
                self._vm("vm-deb", "debian", 1024),
                self._vm("vm-pve", "proxmox", 1024),
            ],
            "2",
        )
        deb, pve = vms
        self.assertEqual("gnome", deb["desktop"])
        self.assertEqual("", pve["desktop"])
        self.assertEqual(1024, pve["ram"])
        self.assertEqual("vm-pve", pve["name"])
        self.assertIn("vm-pve", out)

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

    def _parts(self, desktop, distro="arch", version="latest"):
        return _todo()._qemu_build_deploy_parts(
            distro,
            version,
            "amd64",
            "vm",
            8192,
            2,
            "20G",
            None,
            None,
            True,
            desktop=desktop,
        )

    def test_the_flavour_and_its_remote_access_reach_the_command(self):
        """Collée, « --desktop=<saveur> » : la forme séparée prendrait un
        positionnel suivant pour la saveur. Le genre d'accès se résout ici,
        deploy_qemu.py ne connaissant pas les saveurs."""
        parts = self._parts("hyprland")
        self.assertIn("--desktop=hyprland", parts)
        self.assertEqual("wayvnc", parts[parts.index("--desktop-remote") + 1])
        parts = self._parts("plasma", "debian", "13")
        self.assertEqual("x11", parts[parts.index("--desktop-remote") + 1])

    def test_a_server_gets_neither_option(self):
        parts = self._parts("")
        self.assertNotIn("--desktop-remote", parts)
        self.assertFalse([p for p in parts if p.startswith("--desktop")])

    def test_the_command_parses_back_to_the_same_flavour(self):
        """La commande bâtie ici, relue par l'analyseur de deploy_qemu.py."""
        todo = _todo()
        mod = todo._qemu_import_module()
        for flavour, par_distro in TODO._QEMU_DESKTOP_RELEASES.items():
            for distro, versions in par_distro.items():
                for version in versions:
                    with self.subTest(f=flavour, d=distro, v=version):
                        parts = self._parts(flavour, distro, version)
                        i = parts.index("--desktop-remote")
                        opts = [
                            p for p in parts if p.startswith("--desktop=")
                        ] + parts[i : i + 2]
                        args = mod.build_parser().parse_args(
                            ["--name", "vm"] + opts
                        )
                        self.assertEqual(
                            (
                                flavour,
                                todo._qemu_remote_kind(
                                    flavour, distro, version
                                ),
                            ),
                            (args.desktop, args.desktop_remote),
                        )


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
        self.assertEqual(
            [
                (
                    "gnome",
                    "deb",
                    {"distro": "fedora", "version": "", "keep_login": False},
                )
            ],
            appels,
        )
        subprocess.run(["bash", "-n", "-c", cmd], check=True)

    def test_with_erplibre(self):
        todo, appels = self._todo()
        cmd = todo._qemu_erplibre_remote_cmd(
            "develop", desktop="gnome", distro="arch", version="latest"
        )
        self.assertEqual(
            [
                (
                    "gnome",
                    "deb",
                    {
                        "distro": "arch",
                        "version": "latest",
                        "keep_login": False,
                    },
                )
            ],
            appels,
        )
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
        recus = [
            (kw.get("distro"), kw.get("version")) for _f, _s, kw in appels
        ]
        self.assertIn(("debian", "13"), recus)
        self.assertIn(("fedora", "44"), recus)
        self.assertTrue(all("remote_cmd" in e for e in captures["vms"]))

    def test_the_serial_path_passes_the_vms_version(self):
        """La voie sans suivi reçoit (distro, version, arch) de l'appelant :
        virsh ne connaît pas un domaine posé sur un hôte distant."""
        todo, appels = self._todo()
        todo._qemu_wait_ssh = lambda ip, user="": True
        todo._qemu_vm_meta = lambda *a: self.fail("virsh interrogé")
        todo.execute = mock.Mock()
        with mock.patch("sys.stdout", io.StringIO()):
            todo._qemu_install_erplibre_vm(
                "vm-a",
                None,
                None,
                ip="192.0.2.10",
                desktop="plasma",
                meta=("debian", "13", "amd64"),
            )
        self.assertEqual(
            [("debian", "13")],
            [(kw.get("distro"), kw.get("version")) for _f, _s, kw in appels],
        )

    def test_the_spec_gives_the_serial_path_its_version(self):
        """Sans suivi, _qemu_deploie_spec_corps tire (distro, version,
        arch) de la spec, comme la voie Proxmox."""
        todo = _todo()
        vus = {}

        def install(name, *a, **kw):
            vus[name] = kw.get("meta")

        todo._qemu_install_erplibre_vm = install
        todo._qemu_vm_password_hash = lambda spec: ""
        todo._qemu_vm_password = lambda spec: None
        todo._qemu_vm_user = lambda name: "u"
        todo._ssh_private_key = lambda key: None
        todo._qemu_deploy_parts_for = lambda *a, **k: []
        todo._qemu_deploy_jobs_cli = lambda jobs, workers, **k: [
            (name, 0, "", 0) for _id, name, _p in jobs
        ]
        todo._qemu_resolve_ips = lambda names, labels=None: {
            n: "192.0.2.20" for n in names
        }
        spec = {
            "vms": [
                {
                    "name": "vm-x-gnome",
                    "distro": "fedora",
                    "version": "45",
                    "arch": "arm64",
                    "desktop": "gnome",
                }
            ],
            "install": {
                "branch": "develop",
                "cmd": "true",
                "prod": False,
                "monitor": False,
            },
            "ssh_key": None,
            "add_ssh_config": False,
            "parallelism": 1,
        }
        with mock.patch("sys.stdout", io.StringIO()):
            todo._qemu_deploie_spec_corps(spec, None, None)
        self.assertEqual({"vm-x-gnome": ("fedora", "45", "arm64")}, vus)

    def test_the_spec_gives_the_monitored_path_its_meta(self):
        """Avec suivi, la voie par défaut : (distro, version, arch) viennent
        aussi de la spec, sans jamais relire le nom de la VM."""
        todo = _todo()
        vus = {}

        def suivi(deployed, *a, **kw):
            vus.update(kw.get("meta") or {})
            return []

        def nom_interdit(*a, **kw):
            raise AssertionError("méta relue dans le nom de la VM")

        todo._qemu_install_erplibre_monitored = suivi
        todo._qemu_vm_meta = nom_interdit
        todo._qemu_vm_password_hash = lambda spec: ""
        todo._qemu_vm_password = lambda spec: None
        todo._qemu_vm_user = lambda name: "u"
        todo._ssh_private_key = lambda key: None
        todo._qemu_deploy_parts_for = lambda *a, **k: []
        todo._qemu_deploy_jobs_cli = lambda jobs, workers, **k: [
            (name, 0, "", 0) for _id, name, _p in jobs
        ]
        todo._qemu_resolve_ips = lambda names, labels=None: {
            n: "192.0.2.21" for n in names
        }
        spec = {
            "vms": [
                {
                    "name": "poste-libre",
                    "distro": "rocky",
                    "version": "9",
                    "arch": "amd64",
                    "desktop": "cinnamon",
                }
            ],
            "install": {
                "branch": "develop",
                "cmd": "true",
                "prod": False,
                "monitor": True,
            },
            "ssh_key": None,
            "add_ssh_config": False,
            "parallelism": 1,
        }
        with mock.patch("sys.stdout", io.StringIO()):
            todo._qemu_deploie_spec_corps(spec, None, None)
        self.assertEqual({"poste-libre": ("rocky", "9", "amd64")}, vus)


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

    def test_a_nixos_row_offers_every_desktop(self):
        """NixOS 26.05, la version par défaut de la ligne, déclare chaque
        saveur par son module."""
        from script.todo.deploy_form_extras import SERVER

        vu = self._scenario("nixos", [])
        offertes = [v for v in vu["options"] if v]
        self.assertIn(SERVER, offertes)
        self.assertEqual(len(TODO._QEMU_DESKTOP) + 1, len(offertes))


if __name__ == "__main__":
    unittest.main(verbosity=1)
