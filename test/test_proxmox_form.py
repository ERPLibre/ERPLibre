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
        # Deux noms : le chaîné « hôte+vm », qui dit où la machine vit, et le
        # nom court quand aucun domaine local ne le porte déjà.
        self.assertEqual(essai(False, cmd, False), [["pve1+vm-a", "vm-a"]])
        # Décoché, suivi demandé : le suivi entre aussi par le rebond.
        self.assertEqual(essai(False, None, True), [["pve1+vm-a", "vm-a"]])
        # Décoché et rien à faire dans la VM : le choix est respecté.
        self.assertEqual(essai(False, None, False), [])
        # Coché : écrite, évidemment.
        self.assertEqual(essai(True, None, False), [["pve1+vm-a", "vm-a"]])

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
