#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'écran de déploiement Proxmox VE.

Ce que Proxmox a en plus de QEMU/KVM, et qui doit donc être éprouvé ici : le
VMID choisi AVANT le téléchargement de l'image (l'hôte ne dit « déjà pris »
qu'après), l'adresse qui s'en déduit sur un pont interne, le stockage et le
pont lus sur l'hôte, et une VM qui existe déjà et qu'on ne doit surtout pas
écraser.

Le rendu est vérifié sans terminal (`run_test`), sur un contexte synthétique :
aucun hôte Proxmox n'est joint.
"""

import asyncio
import sys
import unittest
from unittest import mock

sys.argv = ["todo.py"]
from script.todo.proxmox_deploy_form import (  # noqa: E402
    assign_vmids,
    build_spec,
    res_label,
    run_proxmox_form,
)

try:
    import textual  # noqa: F401

    TEXTUAL = True
except Exception:  # pragma: no cover - dépend de l'environnement
    TEXTUAL = False


def rangee(nom, etat="new"):
    return {
        "vm": {
            "name": nom,
            "distro": "debian",
            "version": "13",
            "arch": "amd64",
            "vcpus": 2,
            "ram": 2048,
            "disk": "32G",
        },
        "state": etat,
        "note": "",
        "disk_gb": 32,
    }


class TestVmid(unittest.TestCase):
    """Proxmox refuse un VMID déjà pris, et il le dit APRÈS avoir téléchargé
    l'image : le choix se fait donc avant, d'après ce que l'hôte déclare."""

    def test_taken_ids_are_skipped(self):
        rows = [rangee("a"), rangee("b")]
        assign_vmids(rows, [100, 101, 103], 100, lambda v: "ip=dhcp")
        self.assertEqual([r["vm"]["vmid"] for r in rows], [102, 104])

    def test_an_existing_vm_keeps_its_own(self):
        rows = [rangee("a", "exists"), rangee("b")]
        assign_vmids(rows, [], 100, lambda v: "ip=dhcp")
        self.assertNotIn("vmid", rows[0]["vm"])
        self.assertEqual(rows[1]["vm"]["vmid"], 100)

    def test_the_first_vmid_is_honoured(self):
        rows = [rangee("a")]
        assign_vmids(rows, [], 250, lambda v: "ip=dhcp")
        self.assertEqual(rows[0]["vm"]["vmid"], 250)

    def test_a_vmid_never_goes_below_100(self):
        # Proxmox réserve les VMID sous 100.
        rows = [rangee("a")]
        assign_vmids(rows, [], 7, lambda v: "ip=dhcp")
        self.assertEqual(rows[0]["vm"]["vmid"], 100)

    def test_the_address_is_derived_from_the_vmid(self):
        rows = [rangee("a"), rangee("b")]
        assign_vmids(rows, [], 100, lambda v: f"ip=10.10.10.{50 + v % 200}/24")
        self.assertEqual(rows[0]["vm"]["ipconfig"], "ip=10.10.10.150/24")
        self.assertEqual(rows[1]["vm"]["ipconfig"], "ip=10.10.10.151/24")

    def test_without_a_bridge_rule_it_falls_back_to_dhcp(self):
        rows = [rangee("a")]
        assign_vmids(rows, [], 100, None)
        self.assertEqual(rows[0]["vm"]["ipconfig"], "ip=dhcp")


class TestSpec(unittest.TestCase):
    def _form(self, **extra):
        base = {
            "host": {"target": "erplibre@10.0.0.5"},
            "storage": "local-lvm",
            "bridge": "vmbr0",
            "res_label": "x1",
            "ssh_key": "/home/x/.ssh/id_ed25519.pub",
            "start": True,
            "add_ssh_config": True,
            "install": {
                "branch": "develop",
                "label": "Odoo 18",
                "cmd": "make",
            },
            "monitor": True,
            "parallelism": 2,
        }
        base.update(extra)
        return base

    def test_an_existing_vm_is_never_recreated(self):
        vms = [{"name": "a"}, {"name": "b"}]
        spec = build_spec(vms, ["b"], self._form())
        self.assertEqual([v["name"] for v in spec["vms"]], ["a"])
        self.assertEqual(spec["existing"], ["b"])

    def test_the_user_defaults_to_erplibre(self):
        spec = build_spec([], [], self._form())
        self.assertEqual(spec["user"], "erplibre")

    def test_the_monitor_choice_reaches_the_spec(self):
        # Le suivi est demandé au NIVEAU DU DÉPLOIEMENT : une VM sans
        # ERPLibre se suit aussi.
        spec = build_spec([], [], self._form(install=None, monitor=True))
        self.assertIsNone(spec["install"])
        self.assertTrue(spec["monitor"])

    def test_the_resource_label_names_the_common_setting(self):
        self.assertEqual(res_label("3"), "x3")
        self.assertNotEqual(res_label("custom"), "xcustom")


def contexte():
    def entree(distro, version, arch="amd64"):
        return {
            "name": f"erplibre-{distro}-{version}",
            "distro": distro,
            "version": version,
            "arch": arch,
            "ram": 2048,
            "disk": "32G",
        }

    return {
        "host": {
            "target": "erplibre@10.0.0.5",
            "sudo": "sudo ",
            "label": "pve",
        },
        "node": "pve1",
        "catalog": {
            "amd64": [
                entree("ubuntu", "26.04"),
                entree("debian", "13"),
                entree("fedora", "44"),
                entree("proxmox", "9"),
            ],
            "arm64": [entree("debian", "13", "arm64")],
        },
        "arches": ["amd64", "arm64"],
        "native": "amd64",
        "names": ["erplibre-debian-13"],
        "vmids": [100, 101],
        "next_vmid": 102,
        "storages": ["local-lvm", "local"],
        "storage": "local-lvm",
        "storage_avail": {
            "local-lvm": 90 * (1 << 30),
            "local": 12 * (1 << 30),
        },
        "bridges": ["vmbr0"],
        "bridge": "vmbr0",
        "ipconfig": lambda pont, vmid: f"ip=10.10.10.{50 + vmid % 200}/24",
        "build_command": lambda vm, spec: [f"qm create {vm['vmid']}"],
        "branches": ["develop", "master"],
        "install_profiles": [("ERPLibre + Odoo 18", "make install_odoo_18")],
        "distro_profiles": {
            "proxmox": (
                "Hyperviseur Proxmox VE (sans Odoo)",
                "./script/proxmox/install_proxmox.sh",
            )
        },
        "ssh_key": "/home/x/.ssh/id_ed25519.pub",
        "cpu_presets": [2, 4, 8],
        "ram_presets": [2048, 4096, 8192],
        "disk_presets": ["32G", "64G"],
        "base_vcpus": 2,
        "host_cpu": 8,
        "free_ram": 12000,
        "extra_disk_gb": 10,
    }


@unittest.skipUnless(TEXTUAL, "Textual absent")
class TestEcran(unittest.TestCase):
    """Le formulaire, monté sans terminal."""

    def _rendu(self, gestes):
        ctx = contexte()
        resultat = {}

        async def scenario():
            from textual.widgets import SelectionList

            app = run_proxmox_form(ctx, run_app=False)
            async with app.run_test(size=(200, 50)) as pilote:
                await pilote.pause()
                liste = app.query_one(SelectionList)
                for i in range(3):
                    liste.select(liste.get_option_at_index(i).value)
                await pilote.pause()
                await pilote.pause()
                await gestes(app, pilote)
                # Relevé AVANT la sortie du contexte : `run_test` démonte
                # l'écran, et « #totals » n'existe plus après.
                from textual.widgets import Static

                widget = app.query_one("#totals", Static)
                app.ligne_totaux = str(
                    getattr(widget, "_content", "") or widget.render()
                )
                resultat["app"] = app

        asyncio.run(scenario())
        return resultat["app"]

    def test_the_plan_shows_a_row_per_selected_system(self):
        async def rien(app, pilote):
            pass

        app = self._rendu(rien)
        self.assertEqual(len(app.rows), 3)

    def test_the_head_line_carries_the_vmid_and_the_address(self):
        async def rien(app, pilote):
            pass

        app = self._rendu(rien)
        tete = app._row_head(0, app.rows[0])
        self.assertIn("VMID", tete)
        self.assertIn("10.10.10.", tete)

    def test_an_existing_vm_is_marked_and_gets_no_vmid(self):
        async def rien(app, pilote):
            pass

        app = self._rendu(rien)
        deja = [r for r in app.rows if r["state"] == "exists"]
        self.assertEqual(len(deja), 1)
        self.assertNotIn("VMID", app._row_head(1, deja[0]))

    def test_mounting_does_not_mark_every_row_as_custom(self):
        # Poser « value= » sur un Select fait émettre un Changed : pris pour
        # une saisie, il surchargeait les trois champs de CHAQUE VM et toutes
        # les rangées portaient la marque ✎ avant qu'on ne touche à rien.
        async def rien(app, pilote):
            pass

        app = self._rendu(rien)
        self.assertEqual(app.overrides, {})
        self.assertNotIn("✎", app._row_head(0, app.rows[0]))

    def test_a_lock_survives_a_common_setting(self):
        async def gestes(app, pilote):
            app._set_lock(0, True)
            await pilote.pause()
            app.custom["ram"] = 8192
            app.profile = "custom"
            app._clear_overrides(("ram",))
            app._recompute()
            await pilote.pause()

        app = self._rendu(gestes)
        self.assertEqual(app.rows[0]["vm"]["ram"], 2048)

    def test_a_copy_adds_a_vm_with_its_own_vmid(self):
        async def gestes(app, pilote):
            app._add_copy(0, 1)
            await pilote.pause()

        app = self._rendu(gestes)
        self.assertEqual(len(app.rows), 4)
        vmids = [r["vm"]["vmid"] for r in app.rows if r["state"] != "exists"]
        self.assertEqual(len(vmids), len(set(vmids)))

    def test_deploying_yields_a_spec_the_engine_can_run(self):
        async def gestes(app, pilote):
            app.action_deploy()

        app = self._rendu(gestes)
        spec = app.result
        self.assertEqual(len(spec["vms"]), 2)
        self.assertEqual(spec["existing"], ["erplibre-debian-13"])
        self.assertEqual(spec["storage"], "local-lvm")
        self.assertEqual(spec["bridge"], "vmbr0")
        for vm in spec["vms"]:
            self.assertIn("vmid", vm)
            self.assertIn("ip=", vm["ipconfig"])
        self.assertEqual(spec["install"]["branch"], "develop")

    def _totaux(self, app):
        return app.ligne_totaux

    def test_the_totals_line_shows_the_room_left_on_the_storage(self):
        async def rien(app, pilote):
            pass

        ligne = self._totaux(self._rendu(rien))
        # « pvesm status » donne déjà la place : la demande du plan s'affiche
        # donc à côté d'elle, sans un aller-retour de plus vers l'hôte.
        self.assertIn("/ 90 G", ligne)
        self.assertIn("local-lvm", ligne)

    def test_changing_the_storage_changes_the_room(self):
        # La marque de génération ne vaut que pour les widgets de RANGÉE :
        # l'exiger des widgets globaux faisait taire tous les réglages
        # communs, stockage compris.
        async def gestes(app, pilote):
            from textual.widgets import Select

            app.query_one("#f_storage", Select).value = "local"
            await pilote.pause()
            await pilote.pause()

        ligne = self._totaux(self._rendu(gestes))
        self.assertIn("/ 12 G", ligne)
        self.assertIn("local", ligne)

    def test_a_plan_bigger_than_the_storage_is_flagged(self):
        async def gestes(app, pilote):
            from textual.widgets import Select

            app.query_one("#f_storage", Select).value = "local"
            await pilote.pause()
            await pilote.pause()

        self.assertIn("⚠", self._totaux(self._rendu(gestes)))

    def test_a_common_setting_reaches_every_vm(self):
        async def gestes(app, pilote):
            # « value = True » sur le bouton : action_next_button() ne
            # déplace que la surbrillance et n'émet aucun message.
            list(app.query("#f_profile RadioButton"))[2].value = True
            await pilote.pause()
            await pilote.pause()

        app = self._rendu(gestes)
        self.assertEqual(app.profile, "3")
        self.assertTrue(all(r["vm"]["ram"] == 6144 for r in app.rows))

    def test_the_resource_label_survives_the_markup(self):
        # « [x1] » se faisait manger : Static lit le balisage Rich, et une
        # balise inconnue disparaît avec son contenu.
        async def rien(app, pilote):
            pass

        self.assertIn("x1", self._totaux(self._rendu(rien)))

    def test_a_nested_proxmox_guest_installs_its_hypervisor(self):
        # Même défaut que sur l'écran QEMU/KVM avant correction : un Proxmox
        # imbriqué recevait ERPLibre et Odoo 18.
        async def gestes(app, pilote):
            from textual.widgets import SelectionList

            liste = app.query_one(SelectionList)
            liste.select(liste.get_option_at_index(3).value)
            await pilote.pause()
            await pilote.pause()

        app = self._rendu(gestes)
        par = {r["vm"]["distro"]: r for r in app.rows}
        self.assertEqual(
            par["proxmox"]["vm"]["install_cmd"],
            "./script/proxmox/install_proxmox.sh",
        )
        # Et ses voisines gardent le choix commun.
        self.assertEqual(par["ubuntu"]["vm"]["install_cmd"], "")
        # Cinq gigaoctets pour un dépôt qu'elle ne clonera pas.
        self.assertEqual(par["proxmox"]["disk_gb"], 32)
        self.assertEqual(par["ubuntu"]["disk_gb"], 42)

    def test_text_prompts_are_not_a_cancellation(self):
        # {} n'est pas None : l'appelant distingue « annulé » de
        # « pose-moi les questions à l'ancienne ».
        async def gestes(app, pilote):
            from textual.widgets import Button

            app.on_button_pressed(
                type("E", (), {"button": Button("x", id="prompts")})()
            )

        app = self._rendu(gestes)
        self.assertEqual(app.result, {})

    def test_cancelling_yields_nothing(self):
        async def gestes(app, pilote):
            app.action_cancel()

        self.assertIsNone(self._rendu(gestes).result)


@unittest.skipUnless(TEXTUAL, "Textual absent")
class TestCreerUnPont(unittest.TestCase):
    """Sans pont, « qm create » est impossible — et l'écran refusait de
    déployer sans offrir le moindre moyen d'en avoir un. Rapporté.

    Le pont INTERNE se crée depuis l'écran parce qu'il ne touche à aucune
    interface physique : il n'y a rien à faire arbitrer. Un pont sur le LAN
    déplace l'adresse de l'hôte et coupe la session : il reste manuel.
    """

    def _ecran(self, fabrique, ponts=()):
        from script.todo.proxmox_deploy_form import (
            CREER_PONT,
            run_proxmox_form,
        )

        ctx = contexte()
        ctx["bridges"] = list(ponts)
        ctx["bridge"] = ponts[0] if ponts else ""
        ctx["make_bridge"] = fabrique
        ctx["internal_bridge"] = ("vmbr0", "10.10.10.1/24")
        vu = {}

        async def scenario():
            from textual.widgets import Select

            app = run_proxmox_form(ctx, run_app=False)
            async with app.run_test(size=(200, 55)) as pilote:
                await pilote.pause()
                selecteur = app.query_one("#f_bridge", Select)
                vu["choix_avant"] = [str(o[1]) for o in selecteur._options]
                selecteur.value = CREER_PONT
                for _ in range(30):
                    await pilote.pause()
                    if vu.get("fait"):
                        break
                    vu["fait"] = bool(app._ponts) and app._bridge()
                await pilote.pause()
                vu["pont"] = app._bridge()
                vu["choix_apres"] = [str(o[1]) for o in selecteur._options]

        asyncio.run(scenario())
        return vu

    def test_the_entry_is_offered_when_no_bridge_exists(self):
        vu = self._ecran(lambda: ("vmbr0", ""))
        self.assertIn("__creer_pont__", vu["choix_avant"])

    def test_choosing_it_creates_the_bridge_and_selects_it(self):
        vu = self._ecran(lambda: ("vmbr0", ""))
        self.assertEqual(vu["pont"], "vmbr0")
        self.assertIn("vmbr0", vu["choix_apres"])

    def test_a_failure_leaves_no_bridge_selected(self):
        # Laissé sur « créer », le sélecteur ferait déployer une VM sur
        # « __creer_pont__ » — un nom que « qm create » refuserait.
        vu = self._ecran(lambda: ("", "Operation not supported"))
        self.assertEqual(vu["pont"], "")

    def test_the_entry_stays_offered_when_a_bridge_exists(self):
        # Un hôte avec un seul pont sur le LAN : on peut vouloir un réseau
        # interne pour un parc d'essai.
        vu = self._ecran(lambda: ("vmbr0", ""), ponts=("vmbr9",))
        self.assertIn("__creer_pont__", vu["choix_avant"])
        self.assertIn("vmbr9", vu["choix_avant"])


@unittest.skipUnless(TEXTUAL, "Textual absent")
class TestLInterpretePython(unittest.TestCase):
    """L'écran Proxmox n'offrait pas le choix, donc envoyait toujours
    « automatique » — et comme mise n'est jamais installé d'office, c'était
    pyenv, qui COMPILE Python. Rapporté sur une VM Arch : « il utilise le
    tar.xz pour le compiler »."""

    def _ecran(self, gestes=None, mise_arches=("amd64", "arm64")):
        from script.todo.proxmox_deploy_form import run_proxmox_form

        ctx = contexte()
        ctx["mise_arches"] = mise_arches
        vu = {}

        async def scenario():
            from textual.widgets import SelectionList

            app = run_proxmox_form(ctx, run_app=False)
            async with app.run_test(size=(200, 60)) as pilote:
                await pilote.pause()
                liste = app.query_one(SelectionList)
                liste.select(liste.get_option_at_index(0).value)
                await pilote.pause()
                await pilote.pause()
                if gestes:
                    await gestes(app, pilote)
                vu["choix"] = app._python_provider()
                app.action_deploy()
                vu["spec"] = app.result or {}

        asyncio.run(scenario())
        return vu

    def test_mise_is_offered_by_default(self):
        # Un CPython précompilé plutôt qu'une compilation de trois minutes.
        self.assertEqual(self._ecran()["choix"], "mise")

    def test_the_choice_reaches_the_spec(self):
        async def gestes(app, pilote):
            list(app.query("#f_python RadioButton"))[1].value = True
            await pilote.pause()

        vu = self._ecran(gestes)
        self.assertEqual(vu["choix"], "pyenv")
        self.assertEqual(vu["spec"].get("python_provider"), "pyenv")

    def test_an_arch_mise_does_not_serve_yields_nothing(self):
        # « mise indisponible » ne veut pas dire « l'utilisateur exige
        # pyenv » : un choix explicite écarterait le Python de la distro.
        self.assertEqual(self._ecran(mise_arches=("s390x",))["choix"], "")


class TestLeDisquePromis(unittest.TestCase):
    """Le plan annonçait « 25G » et « qm resize » recevait 20 G.

    La voie libvirt ajoute la marge d'ERPLibre à la taille créée ; celle de
    Proxmox la perdait entre l'écran et la commande. La VM naissait cinq
    gigaoctets trop petite pour ce qu'on venait de lui promettre."""

    def _taille(self, install, cmd_vm=""):
        import sys

        sys.argv = ["todo.py"]
        from script.todo.todo import TODO

        todo = TODO.__new__(TODO)
        vm = {"disk": "20G", "install_cmd": cmd_vm}
        return todo._pve_disk_with_margin(vm, {"install": install})

    def test_the_margin_reaches_the_created_disk(self):
        self.assertEqual(
            self._taille(
                {
                    "branch": "develop",
                    "cmd": "make install_os && make install_odoo_18",
                }
            ),
            "25G",
        )

    def test_nothing_to_install_means_no_margin(self):
        self.assertEqual(self._taille(None), "20G")

    def test_a_hypervisor_profile_gets_no_margin(self):
        # Elle est réservée au dépôt ERPLibre, qu'un Proxmox ne clonera pas.
        self.assertEqual(
            self._taille(
                {
                    "branch": "develop",
                    "cmd": "./script/proxmox/install_proxmox.sh",
                }
            ),
            "20G",
        )


class TestDeuxVmDuMemeNom(unittest.TestCase):
    """Sur Proxmox, seul le VMID est unique : deux VM du même hôte peuvent
    porter le même nom. « Changer l'état » les choisissait par NOM — cocher
    l'une éteignait les deux."""

    def test_selecting_one_twin_takes_only_that_one(self):
        import sys

        sys.argv = ["todo.py"]
        from script.todo.todo import TODO

        todo = TODO.__new__(TODO)
        vms = [
            {"vmid": 100, "name": "jumeau", "status": "running"},
            {"vmid": 101, "name": "jumeau", "status": "running"},
        ]
        rangs = [str(i) for i in range(1, len(vms) + 1)]
        for choix, attendu in (
            ("1", [100]),
            ("2", [101]),
            ("1,2", [100, 101]),
        ):
            voulus = {
                int(r)
                for r in todo._parse_index_selection(choix, rangs)
                if str(r).isdigit()
            }
            self.assertEqual(
                [vm["vmid"] for i, vm in enumerate(vms, 1) if i in voulus],
                attendu,
                choix,
            )


class TestUnParcMixte(unittest.TestCase):
    """Le plan porte branche, profil et type PAR RANGÉE — le déploiement
    lisait encore la seule valeur commune.

    C'est le cas qu'on déploie le plus souvent sur un Proxmox : un
    hyperviseur imbriqué à côté de VM ERPLibre. Une seule VM qui porte sa
    propre valeur suffit à rendre la carte nécessaire — « len(set) > 1 » ne
    l'aurait pas vu, et tout le parc serait retombé sur le commun."""

    def _capture(self, vms):
        import contextlib
        import io
        import sys

        sys.argv = ["todo.py"]
        from script.todo.todo import TODO

        vu = {}
        todo = TODO.__new__(TODO)
        todo._write_ssh_config_entry = lambda *a, **k: None
        todo._ssh_private_key = lambda k: None
        todo._ssh_config_block = lambda nom: {}
        todo._qemu_list_domains = lambda: []
        todo._pve_guest_ip = lambda vmid, attente=120: ""
        todo._pve_write_guide = lambda *a, **k: True
        todo._pve_set_timezone = lambda *a, **k: True
        todo._qemu_import_module = lambda: None

        def prise(noms, branche, alias, finale, **kw):
            vu.update(branche=branche, finale=finale, kw=kw)

        todo._qemu_install_erplibre_monitored = prise
        spec = {
            "host": {"target": "pve1"},
            "vms": vms,
            "user": "erplibre",
            "add_ssh_config": True,
            "install": {
                "branch": "develop",
                "cmd": "make install_odoo_18",
                "label": "X",
            },
            "monitor": True,
            "desktop": "",
        }
        with contextlib.redirect_stdout(io.StringIO()):
            todo._pve_after_create(
                spec["host"], spec, [v["name"] for v in vms], ""
            )
        return vu

    def _vm(self, nom, **extra):
        base = {
            "name": nom,
            "vmid": 100,
            "ipconfig": "ip=10.10.10.150/24,gw=10.10.10.1",
            "install_cmd": "",
        }
        base.update(extra)
        return base

    def test_a_single_vm_with_its_own_branch_forces_the_map(self):
        vu = self._capture(
            [
                self._vm("vm-a", branch="master"),
                self._vm("vm-b", vmid=101),
            ]
        )
        self.assertEqual(vu["branche"], {"vm-a": "master", "vm-b": "develop"})

    def test_a_uniform_fleet_keeps_the_common_value(self):
        vu = self._capture([self._vm("vm-a"), self._vm("vm-b", vmid=101)])
        self.assertEqual(vu["branche"], "develop")

    def test_a_per_vm_desktop_reaches_the_install(self):
        vu = self._capture(
            [
                self._vm("vm-a", desktop="gnome"),
                self._vm("vm-b", vmid=101),
            ]
        )
        self.assertEqual(vu["kw"]["desktop"], {"vm-a": "gnome", "vm-b": ""})

    def test_a_uniform_fleet_keeps_the_common_desktop(self):
        vu = self._capture([self._vm("vm-a"), self._vm("vm-b", vmid=101)])
        self.assertEqual(vu["kw"]["desktop"], "")


class TestLePontQuiNeMeneraitNullePart(unittest.TestCase):
    """Le pont NAT était écrit AVANT qu'on sache si le NAT existe.

    Résultat rapporté : la strophe posée dans /etc/network/interfaces, le
    pont absent, et six lignes d'iptables qui ne parlent pas de redémarrage.
    L'avertissement sur le noyau existait — mais à la CONFIRMATION de l'hôte,
    et l'hôte est ensuite mémorisé : on revient des jours plus tard créer un
    pont, et plus personne ne rappelle rien."""

    def _todo(self, sortie):
        import sys

        sys.argv = ["todo.py"]
        from script.todo.todo import TODO

        todo = TODO.__new__(TODO)
        vu = []
        todo._pve_host = lambda ask=True: {"target": "pve9", "sudo": ""}
        todo._pve_uplink = lambda: "eth0"

        def faux_run(host, cmd, timeout=120):
            vu.append(cmd)
            from script.proxmox import proxmox_deploy as pve

            if cmd == pve.NAT_CHECK_CMD:
                return 0, sortie
            return 0, ""

        return todo, vu, faux_run

    def _sortie(self, nat, pve_kernel="7.0.14-14-pve"):
        return (
            f"{'7.0.14-14-pve' if nat else '6.12.101+deb13-cloud-amd64'}\n"
            f"---ERPLIBRE-NAT---\n{'NAT-OK' if nat else 'NAT-KO'}\n"
            f"---ERPLIBRE-PVE-KERNEL---\n{pve_kernel}\n"
        )

    def test_nothing_is_written_when_there_is_no_nat(self):
        todo, vu, faux = self._todo(self._sortie(nat=False))
        with mock.patch("script.proxmox.proxmox_deploy.run", faux):
            nom, raison = todo._pve_make_internal_bridge()
        self.assertEqual(nom, "")
        self.assertTrue(raison)
        # Une seule commande : la sonde. Rien n'a touché au fichier.
        self.assertEqual(len(vu), 1, vu)
        self.assertNotIn(
            "interfaces", " ".join(vu), "la strophe ne doit pas être écrite"
        )

    def test_the_reason_names_the_kernel_to_boot(self):
        todo, _vu, faux = self._todo(self._sortie(nat=False))
        with mock.patch("script.proxmox.proxmox_deploy.run", faux):
            ok, lignes = todo._pve_nat_ready({"target": "pve9", "sudo": ""})
        self.assertFalse(ok)
        texte = " ".join(lignes)
        self.assertIn("6.12.101+deb13-cloud-amd64", texte)
        self.assertIn("7.0.14-14-pve", texte)
        self.assertIn("reboot", texte)

    def test_an_unfinished_install_says_so_instead(self):
        todo, _vu, faux = self._todo(self._sortie(nat=False, pve_kernel=""))
        with mock.patch("script.proxmox.proxmox_deploy.run", faux):
            _ok, lignes = todo._pve_nat_ready({"target": "pve9", "sudo": ""})
        texte = " ".join(lignes)
        self.assertNotIn("reboot", texte, "rien à redémarrer, rien de posé")

    def test_a_working_host_goes_through(self):
        todo, vu, faux = self._todo(self._sortie(nat=True))
        with mock.patch("script.proxmox.proxmox_deploy.run", faux):
            todo._pve_make_internal_bridge()
        self.assertGreater(len(vu), 1, "la création doit suivre la sonde")


class TestUneProxmoxImbriqueeDoitRedemarrer(unittest.TestCase):
    """Le sommaire ne disait pas qu'une VM qui vient de recevoir Proxmox
    tourne encore le noyau de son image cloud.

    On le redécouvrait des jours plus tard, en créant un pont, devant six
    lignes d'iptables."""

    def _juge(self, vm, commun=""):
        import sys

        sys.argv = ["todo.py"]
        from script.todo.todo import TODO

        return TODO._pve_installs_proxmox(
            vm, {"install": {"cmd": commun}} if commun else {}
        )

    def test_a_vm_that_gets_the_hypervisor(self):
        self.assertTrue(
            self._juge({"install_cmd": "./script/proxmox/install_proxmox.sh"})
        )

    def test_through_the_common_choice_too(self):
        self.assertTrue(self._juge({}, "./script/proxmox/install_proxmox.sh"))

    def test_an_erplibre_vm_is_left_alone(self):
        self.assertFalse(
            self._juge({}, "make install_os && make install_odoo_18")
        )

    def test_a_vm_of_its_own_overrides_the_common_choice(self):
        # Parc mixte : la commande de la VM l'emporte sur celle du parc.
        self.assertFalse(
            self._juge(
                {"install_cmd": "make install_odoo_18"},
                "./script/proxmox/install_proxmox.sh",
            )
        )


class TestLEcranDUneVmProxmox(unittest.TestCase):
    """« Console de l'hyperviseur » conseillait des commandes virsh sur une
    machine qui n'a pas libvirt.

    Le tunnel lit le port VNC par « virsh vncdisplay » sur l'hyperviseur. Un
    Proxmox VE n'a pas de libvirt : la commande échoue, et l'absence de port
    était lue « écran fermé ». On imprimait alors « sudo virsh edit » — sur un
    hôte où le binaire n'existe pas. Ce n'est pas un écran fermé, c'est la
    mauvaise question : Proxmox sert son écran par un ticket, sur son
    interface web."""

    def _sortie(self, qm_present, port=0):
        import contextlib
        import io
        import sys

        sys.argv = ["todo.py"]
        from script.todo.todo import TODO

        todo = TODO.__new__(TODO)
        todo._ssh_proxyjump = lambda nom: "pve9"
        todo._qemu_vnc_port = staticmethod(lambda d, j="": port)
        todo._hypervisor_is_proxmox = lambda jump: qm_present
        tampon = io.StringIO()
        with contextlib.redirect_stdout(tampon):
            todo._qemu_console_tunnel("pve9+vm-a", "ssh_config")
        return tampon.getvalue()

    def test_a_proxmox_host_is_never_told_to_run_virsh(self):
        sortie = self._sortie(qm_present=True)
        self.assertNotIn("virsh", sortie)
        self.assertIn("qm terminal", sortie)
        self.assertIn("8006", sortie, "l'interface web est le second chemin")

    def test_a_libvirt_host_keeps_its_repair_commands(self):
        # La voie libvirt ne régresse pas : sans port, ses commandes de
        # réparation restent la bonne réponse.
        sortie = self._sortie(qm_present=False)
        self.assertIn("virsh edit", sortie)

    def test_a_working_vnc_port_still_wins(self):
        # La sonde ne doit pas s'exécuter quand il y a un port : ce serait un
        # aller-retour ssh pour rien.
        sortie = self._sortie(qm_present=True, port=5901)
        self.assertIn("-L 5901:127.0.0.1:5901", sortie)
        self.assertNotIn("qm terminal", sortie)


class TestUnSeulNomDansSshConfig(unittest.TestCase):
    """L'entrée portait DEUX noms sur sa ligne « Host », puis le mauvais.

    D'abord le doublon : « Host erplibre-proxmox-9+erplibre-arch-latest
    erplibre-arch-latest ». ssh n'a besoin que d'un nom, et le second
    n'ajoutait qu'une façon de plus d'écrire la même adresse.

    Puis le choix. Prendre le nom COURT quand il se trouvait libre donnait un
    parc incohérent : sur un même déploiement de trois VM, deux recevaient
    « hôte+vm » — leurs noms étaient pris par des domaines locaux — et la
    troisième son nom court. Une convention qui dépend de ce qui traîne dans
    le fichier n'est pas une convention. Le chaîné est systématique."""

    def _choisit(self, nom, locaux=()):
        import sys

        sys.argv = ["todo.py"]
        from script.todo.todo import TODO

        todo = TODO.__new__(TODO)
        return todo._pve_alias_names(nom, f"pve9+{nom}", set(locaux), "pve9")

    def test_one_name_and_it_is_the_chained_one(self):
        noms, vole = self._choisit("erplibre-arch-latest")
        self.assertEqual(noms, ["pve9+erplibre-arch-latest"])
        self.assertFalse(vole)

    def test_a_fleet_gets_one_single_convention(self):
        # Le défaut rapporté : trois VM du même déploiement, deux nommées
        # d'une façon et la troisième d'une autre.
        noms = [
            self._choisit(n, locaux=("erplibre-ubuntu-2604",))[0][0]
            for n in (
                "erplibre-ubuntu-2604",
                "erplibre-arch-latest",
                "erplibre-proxmox-9",
            )
        ]
        self.assertTrue(
            all(n.startswith("pve9+") for n in noms),
            f"un parc, une convention : {noms}",
        )

    def test_a_local_namesake_is_still_named(self):
        # Le nom chaîné ne lui vole rien, mais on le DIT : c'est ce qui
        # explique pourquoi « ssh <nom court> » va ailleurs.
        _noms, vole = self._choisit(
            "erplibre-arch-latest", locaux=("erplibre-arch-latest",)
        )
        self.assertTrue(vole)

    def test_no_deploy_path_writes_two_names_anymore(self):
        import re
        from pathlib import Path as P

        src = P("script/todo/proxmox_menu.py").read_text(encoding="utf-8")
        self.assertIsNone(
            re.search(r"noms_alias\.append|noms\.append\(vm\[.name.\]\)", src),
            "le second nom ne doit plus être ajouté",
        )


class TestLAncienNomSEnVa(unittest.TestCase):
    """La convention a changé : les entrées écrites AVANT portent le nom
    court, et rien ne les retirerait — elles ne portent pas le nom qu'on
    écrit maintenant. Deux blocs mèneraient à la même machine, ce qu'on
    venait justement d'enlever."""

    def setUp(self):
        import os
        import sys
        import tempfile

        sys.argv = ["todo.py"]
        from script.todo.todo import TODO

        self.maison = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.maison, ".ssh"))
        self._vrai = os.environ.get("HOME")
        os.environ["HOME"] = self.maison
        self.todo = TODO.__new__(TODO)

    def tearDown(self):
        import os
        import shutil

        if self._vrai is not None:
            os.environ["HOME"] = self._vrai
        shutil.rmtree(self.maison, ignore_errors=True)

    def _hosts(self):
        import os

        with open(
            os.path.join(self.maison, ".ssh/config"), encoding="utf-8"
        ) as fh:
            return [
                ligne.rstrip() for ligne in fh if ligne.startswith("Host ")
            ]

    def test_the_old_short_entry_is_retired(self):
        # L'état d'avant : une entrée écrite sous l'ancienne convention.
        self.todo._write_ssh_config_entry(
            ["vm-a"], "erplibre", "10.10.10.151", proxy_jump="pve9"
        )
        perime = self.todo._pve_alias_perime("vm-a", "pve9")
        self.assertEqual(perime, ["vm-a"])
        self.todo._write_ssh_config_entry(
            ["pve9+vm-a"],
            "erplibre",
            "10.10.10.151",
            proxy_jump="pve9",
            also_drop=perime,
        )
        self.assertEqual(self._hosts(), ["Host pve9+vm-a"])

    def test_a_local_vm_of_the_same_name_is_left_alone(self):
        # Sans ProxyJump vers cet hôte, le bloc n'est pas le nôtre : on n'y
        # touche pas, même s'il porte exactement ce nom.
        self.todo._write_ssh_config_entry(["vm-a"], "erplibre", "192.168.1.9")
        self.assertEqual(self.todo._pve_alias_perime("vm-a", "pve9"), [])
        self.todo._write_ssh_config_entry(
            ["pve9+vm-a"],
            "erplibre",
            "10.10.10.151",
            proxy_jump="pve9",
            also_drop=self.todo._pve_alias_perime("vm-a", "pve9"),
        )
        self.assertEqual(self._hosts(), ["Host vm-a", "Host pve9+vm-a"])

    def test_another_hosts_vm_is_left_alone(self):
        self.todo._write_ssh_config_entry(
            ["vm-a"], "erplibre", "10.0.0.9", proxy_jump="pve7"
        )
        self.assertEqual(self.todo._pve_alias_perime("vm-a", "pve9"), [])


class TestLeGuideDeConnexion(unittest.TestCase):
    """Une VM Proxmox n'avait AUCUN guide, quelle que soit sa distribution.

    Rapporté sur Arch : « pas l'écran de connexion, avec le guide qui dit de
    prendre pacman, comme sur ubuntu ». La voie libvirt livre /etc/motd par le
    « write_files » de cloud-init ; « qm set » n'offre pas cela. Le contenu
    vient de la MÊME source (`guide_files`) et part par ssh.
    """

    def _ecrit(self, vm=None, install=None, distro="arch"):
        import sys

        sys.argv = ["todo.py"]
        from script.todo.todo import TODO

        todo = TODO.__new__(TODO)
        vus = {}
        todo._pve_ssh = lambda cible, remote, timeout=60: (
            vus.update(cible=cible, remote=remote) or (0, "")
        )
        mod = todo._qemu_import_module()
        vm = vm or {
            "name": "vm-a",
            "distro": distro,
            "version": "latest",
            "arch": "amd64",
            "desktop": "",
            "install_cmd": "",
        }
        spec = {"user": "erplibre", "install": install}
        import contextlib
        import io

        with contextlib.redirect_stdout(io.StringIO()):
            ok = todo._pve_write_guide("hote+vm-a", vm, spec, mod)
        vus["ok"] = ok
        return vus

    def test_the_guide_goes_to_etc_motd_through_the_alias(self):
        vus = self._ecrit()
        self.assertTrue(vus["ok"])
        # Par l'ALIAS : lui seul porte le rebond vers le réseau interne.
        self.assertEqual(vus["cible"], "hote+vm-a")
        self.assertIn("/etc/motd", vus["remote"])
        self.assertIn("sudo tee", vus["remote"])

    def test_an_arch_vm_is_told_about_pacman(self):
        self.assertIn("pacman", self._ecrit(distro="arch")["remote"])

    def test_a_debian_vm_is_told_about_apt(self):
        self.assertIn("apt", self._ecrit(distro="debian")["remote"])

    def test_without_erplibre_the_guide_does_not_promise_a_repository(self):
        # Un guide qui annonce un dépôt absent est un guide qui mente.
        sans = self._ecrit(install=None)["remote"]
        self.assertNotIn("git/erplibre", sans)

    def test_with_erplibre_it_says_where_it_lives(self):
        avec = self._ecrit(
            install={
                "branch": "develop",
                "cmd": "make install_os && make install_odoo_18",
            }
        )["remote"]
        self.assertIn("git/erplibre", avec)

    def test_a_failure_is_said_not_swallowed(self):
        import contextlib
        import io
        import sys

        sys.argv = ["todo.py"]
        from script.todo.todo import TODO

        todo = TODO.__new__(TODO)
        todo._pve_ssh = lambda *a, **k: (255, "no route")
        mod = todo._qemu_import_module()
        vm = {
            "name": "vm-a",
            "distro": "arch",
            "version": "latest",
            "arch": "amd64",
            "desktop": "",
            "install_cmd": "",
        }
        with contextlib.redirect_stdout(io.StringIO()) as sortie:
            ok = todo._pve_write_guide("x", vm, {"user": "erplibre"}, mod)
        self.assertFalse(ok)
        self.assertIn("⚠", sortie.getvalue())


class TestLeSuivi(unittest.TestCase):
    """La case « Suivre l'installation » doit commander quelque chose.

    Elle ne commandait rien : décochée, le tableau de bord s'ouvrait quand
    même ; cochée sans rien à installer, il ne s'ouvrait jamais. Le suivi
    vient du DÉPLOIEMENT, pas de l'installation — c'est la règle déjà tirée du
    côté QEMU/KVM après le même rapport.
    """

    def _apres_creation(self, install, monitor):
        """Rejoue l'épilogue du déploiement et dit quelle voie a été prise."""
        import sys

        sys.argv = ["todo.py"]
        from script.todo.todo import TODO

        todo = TODO.__new__(TODO)
        vus = {}
        todo._qemu_install_erplibre_monitored = lambda *a, **k: vus.setdefault(
            "tableau", a
        )
        todo._qemu_install_erplibre_vm = lambda *a, **k: vus.setdefault(
            "serie", a
        )
        todo._write_ssh_config_entry = lambda *a, **k: None
        todo._ssh_private_key = lambda k: None
        todo._pve_guest_ip = lambda vmid, attente=120: ""
        spec = {
            "host": {"target": "pve1"},
            "vms": [
                {
                    "name": "vm-a",
                    "vmid": 100,
                    "ipconfig": "ip=10.10.10.150/24,gw=10.10.10.1",
                    "install_cmd": "",
                }
            ],
            "add_ssh_config": False,
            "user": "erplibre",
            "install": install,
            "monitor": monitor,
        }
        import contextlib
        import io

        with contextlib.redirect_stdout(io.StringIO()):
            todo._pve_after_create(spec["host"], spec, ["vm-a"], "")
        return vus

    def test_ticked_without_anything_to_install_still_opens_it(self):
        # La commande distante regarde alors la VM ARRIVER : c'est justement
        # ce qu'on veut voir sur une VM déployée nue.
        vus = self._apres_creation(install=None, monitor=True)
        self.assertIn("tableau", vus)
        self.assertNotIn("serie", vus)

    def test_unticked_installs_without_the_dashboard(self):
        vus = self._apres_creation(
            install={"branch": "develop", "cmd": "make x", "label": "X"},
            monitor=False,
        )
        self.assertIn("serie", vus)
        self.assertNotIn("tableau", vus)

    def test_unticked_and_nothing_to_install_does_nothing(self):
        self.assertEqual(self._apres_creation(install=None, monitor=False), {})

    def test_the_ssh_entry_is_written_when_the_install_needs_it(self):
        """La VM est derrière l'hôte : le rebond de ~/.ssh/config est le SEUL
        chemin. Décoché alors qu'une installation est demandée, le suivi ne
        pouvait pas entrer dans la VM."""
        import contextlib
        import io
        import sys

        sys.argv = ["todo.py"]
        from script.todo.todo import TODO

        def essai(add_ssh_config, install, monitor):
            todo = TODO.__new__(TODO)
            ecrites = []
            todo._write_ssh_config_entry = lambda nom, *a, **k: ecrites.append(
                nom
            )
            todo._ssh_private_key = lambda k: None
            # Hermétique : le choix du nom lit la liste des domaines
            # locaux. Sans ce bouchon, le test dépendrait de la machine qui
            # le lance.
            todo._qemu_list_domains = lambda: []
            todo._pve_guest_ip = lambda vmid, attente=120: ""
            todo._qemu_install_erplibre_monitored = lambda *a, **k: None
            todo._qemu_install_erplibre_vm = lambda *a, **k: None
            spec = {
                "host": {"target": "pve1"},
                "vms": [
                    {
                        "name": "vm-a",
                        "vmid": 100,
                        "ipconfig": "ip=10.10.10.150/24,gw=10.10.10.1",
                        "install_cmd": "",
                    }
                ],
                "add_ssh_config": add_ssh_config,
                "user": "erplibre",
                "install": install,
                "monitor": monitor,
            }
            with contextlib.redirect_stdout(io.StringIO()):
                todo._pve_after_create(spec["host"], spec, ["vm-a"], "")
            return ecrites

        cmd = {"branch": "develop", "cmd": "make x", "label": "X"}
        # UN nom, et le chaîné : « hôte+vm » dit où la machine vit et ne
        # dépend pas de ce qui traîne dans ~/.ssh/config (voir
        # TestUnSeulNomDansSshConfig).
        self.assertEqual(essai(False, cmd, False), [["pve1+vm-a"]])
        # Décoché, suivi demandé : le suivi entre aussi par le rebond.
        self.assertEqual(essai(False, None, True), [["pve1+vm-a"]])
        # Décoché et rien à faire dans la VM : le choix est respecté.
        self.assertEqual(essai(False, None, False), [])
        # Coché : écrite, évidemment.
        self.assertEqual(essai(True, None, False), [["pve1+vm-a"]])

    def test_a_local_vm_of_the_same_name_keeps_its_alias(self):
        """Le piège qui a fait installer ERPLibre sur la MAUVAISE machine.

        Une VM déployée sur Proxmox sous un nom déjà porté par un domaine
        LOCAL volait son alias ~/.ssh/config, et le suivi — qui ré-résolvait
        l'adresse par virsh — partait installer sur la locale."""
        import contextlib
        import io
        import sys

        sys.argv = ["todo.py"]
        from script.todo.todo import TODO

        todo = TODO.__new__(TODO)
        ecrites = []
        todo._qemu_list_domains = lambda: ["vm-a"]
        todo._write_ssh_config_entry = lambda noms, *a, **k: ecrites.append(
            noms
        )
        todo._ssh_private_key = lambda k: None
        todo._pve_guest_ip = lambda vmid, attente=120: ""
        vus = {}
        todo._qemu_install_erplibre_monitored = (
            lambda noms, br, ipmap, cmd, **k: vus.update(ipmap=ipmap)
        )
        spec = {
            "host": {"target": "erplibre@pve1"},
            "vms": [
                {
                    "name": "vm-a",
                    "vmid": 100,
                    "ipconfig": "ip=10.10.10.150/24,gw=10.10.10.1",
                    "install_cmd": "",
                }
            ],
            "add_ssh_config": True,
            "user": "erplibre",
            "install": None,
            "monitor": True,
        }
        with contextlib.redirect_stdout(io.StringIO()) as sortie:
            todo._pve_after_create(spec["host"], spec, ["vm-a"], "")
        # SEUL le nom chaîné est écrit : l'alias court reste à la VM locale.
        self.assertEqual(ecrites, [["pve1+vm-a"]])
        # Et le suivi passe par ce nom-là, jamais par « vm-a ».
        self.assertEqual(vus["ipmap"], {"vm-a": "pve1+vm-a"})
        self.assertIn("pve1+vm-a", sortie.getvalue())

    def test_ticked_with_an_install_opens_it(self):
        vus = self._apres_creation(
            install={"branch": "develop", "cmd": "make x", "label": "X"},
            monitor=True,
        )
        self.assertIn("tableau", vus)


if __name__ == "__main__":
    unittest.main(verbosity=2)
