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


def setUpModule():
    """L'attente ssh ne part JAMAIS pour de vrai depuis les tests.

    Le déploiement attend qu'une VM fraîche réponde en ssh avant de lui poser
    le guide, le fuseau, le miroir et l'autorité — une adresse n'est pas une
    machine prête. Les harnais d'ici remplacent chaque geste distant mais
    appellent le vrai `_pve_ssh` : sans ce remplacement, chacun tenterait une
    connexion vers un alias inventé et la suite unitaire y perdrait des
    minutes. Les tests de l'attente elle-même la rappellent sur place.
    """
    from script.todo.todo import TODO

    patch = mock.patch.object(TODO, "_pve_attendre_ssh", lambda *a, **k: True)
    patch.start()
    unittest.addModuleCleanup(patch.stop)


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
        # L'hôte d'essai est une VM de notre pont : la case « Sans connexion
        # internet » est donc offerte, comme sur un Proxmox imbriqué.
        "cache_offert": True,
        # L'hôte d'essai a un nœud de rendu et le VIRGL : la case 3D est
        # donc offerte, comme sur un hôte Proxmox capable.
        "gpu_offert": True,
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


@unittest.skipUnless(TEXTUAL, "Textual absent")
class TestLePreVolDuCacheSurProxmox(unittest.TestCase):
    """Ce que le cache ne détient pas, aucune VM coupée ne le lira.

    Le formulaire libvirt le dit depuis toujours ; celui de Proxmox partait
    sans rien vérifier, et l'échec tombait une heure plus tard, à la pose du
    bureau — un message qui accuse le dépôt, jamais le cache. F5 à nouveau
    vaut passage outre : le journal peut avoir tourné, ou le magasin avoir
    été rempli autrement.
    """

    def _deployer(self, absentes=(), hors_ligne=True):
        """Deux F5 d'affilée. Rend ce que la spec valait après chacun."""
        import asyncio
        from unittest import mock

        from script.qemu import cache_offline

        ctx = contexte()
        vu = {}

        async def scenario():
            from textual.widgets import Checkbox, SelectionList

            app = run_proxmox_form(ctx, run_app=False)
            async with app.run_test(size=(200, 50)) as pilote:
                await pilote.pause()
                liste = app.query_one(SelectionList)
                liste.select(liste.get_option_at_index(0).value)
                await pilote.pause()
                if hors_ligne:
                    app.query_one("#f_offline", Checkbox).value = True
                await pilote.pause()
                app.action_deploy()
                vu["premier"] = getattr(app, "result", None)
                app.action_deploy()
                vu["second"] = getattr(app, "result", None)

        with (
            mock.patch.object(
                cache_offline, "suites_absentes", return_value=list(absentes)
            ),
            mock.patch.object(
                cache_offline, "composants_absents", return_value=[]
            ),
            mock.patch.object(
                cache_offline, "manques_hors_ligne", return_value=[]
            ),
            mock.patch.object(
                cache_offline, "paquets_absents", return_value=[]
            ),
            mock.patch.object(
                cache_offline, "miroirs_absents", return_value=[]
            ),
        ):
            asyncio.run(scenario())
        return vu

    def test_le_premier_f5_avertit_au_lieu_de_partir(self):
        vu = self._deployer(absentes=[("ubuntu", "26.04")])
        self.assertFalse(vu["premier"], "parti sans rien dire du manque")
        self.assertTrue(vu["second"], "le second F5 ne passe pas outre")

    def test_un_magasin_complet_ne_retarde_personne(self):
        """Un avertissement qui tombe quand rien ne manque s'apprend par
        cœur, et c'est ainsi qu'on cesse de le lire."""
        vu = self._deployer(absentes=[])
        self.assertTrue(vu["premier"], "avertissement sans manque")

    def test_en_ligne_le_pre_vol_ne_se_pose_pas(self):
        """Le cache n'est qu'un raccourci tant que l'amont répond : ce qui
        lui manque se télécharge, et rien n'échoue."""
        vu = self._deployer(absentes=[("ubuntu", "26.04")], hors_ligne=False)
        self.assertTrue(vu["premier"], "le pré-vol s'est posé hors coupure")


class TestLeHorsLigneSurProxmox(unittest.TestCase):
    """La coupure d'amont, offerte sur Proxmox VE comme sur QEMU/KVM.

    Elle est posée ICI, sur le pont local, et jamais sur l'hôte distant : un
    hôte Proxmox qui reçoit l'autorité du cache est une VM de ce pont, et ses
    invités sortent derrière son adresse. Un hôte qui ne vit pas ici ne doit
    donc PAS se voir offrir la case — rien ici ne sait couper sa sortie, et
    une VM qui s'y bâtirait réussirait en ligne sous une promesse de
    hors-ligne.
    """

    def _todo(self):
        import sys

        sys.argv = ["todo.py"]
        from script.todo.todo import TODO

        todo = TODO.__new__(TODO)
        todo._write_ssh_config_entry = lambda *a, **k: None
        todo._ssh_private_key = lambda k: None
        todo._ssh_config_block = lambda nom: {}
        todo._pve_guest_ip = lambda vmid, attente=120: ""
        todo._pve_write_guide = lambda *a, **k: True
        todo._pve_set_timezone = lambda *a, **k: True
        todo._qemu_import_module = lambda: None
        return todo

    def test_la_case_ne_sort_que_pour_un_hote_qui_vit_ici(self):
        """C'est le même verdict que celui de l'autorité du cache : là où
        elle est posée, le trafic traverse notre pont."""
        todo = self._todo()
        todo._qemu_cache_ca_path = lambda: "/var/lib/cache/ca.crt"
        todo._qemu_list_domains = lambda: ["pve-imbrique"]
        self.assertTrue(
            todo._pve_cache_ca({"target": "erplibre@pve-imbrique"})
        )
        self.assertFalse(todo._pve_cache_ca({"target": "erplibre@ailleurs"}))

    def test_le_contexte_offre_la_case_selon_ce_verdict(self):
        from pathlib import Path

        racine = Path(__file__).resolve().parent.parent
        src = (racine / "script" / "todo" / "proxmox_menu.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"cache_offert": bool(self._pve_cache_ca(host))', src)

    def _capture(self, **kw):
        """Ce que l'installateur reçoit, la coupure tenue ou non."""
        import contextlib
        import io

        todo = self._todo()
        vu = {}
        todo._qemu_install_erplibre_monitored = lambda *a, **k: vu.update(k)
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
            "user": "erplibre",
            "add_ssh_config": True,
            "install": {"branch": "develop", "cmd": "make", "label": "X"},
            "monitor": True,
        }
        todo._qemu_list_domains = lambda: []
        with contextlib.redirect_stdout(io.StringIO()):
            todo._pve_after_create(spec["host"], spec, ["vm-a"], "", **kw)
        return vu

    def test_la_coupure_tenue_atteint_linstallateur(self):
        """Le guet reçoit la levée, et le manifeste porte la coupure : sans
        cela, la coupure tomberait avec ce processus — avant la fin de ce qui
        télécharge — et le bilan hors ligne ne saurait pas quoi relire."""
        vu = self._capture(coupee=True, debut=1789000000.0)
        self.assertTrue(vu["guet_hors_ligne"])
        self.assertTrue(vu["hors_ligne"])
        self.assertEqual(vu["deploy_started"], 1789000000.0)

    def test_sans_coupure_rien_nest_promis(self):
        vu = self._capture()
        self.assertFalse(vu["guet_hors_ligne"])
        self.assertFalse(vu["hors_ligne"])

    def test_le_deploiement_passe_par_lenveloppe(self):
        """La spec ENTIÈRE tient dans le bloc coupé, création comprise : une
        coupure levée avant l'installation ne prouverait rien."""
        import contextlib

        todo = self._todo()
        vu = {}

        @contextlib.contextmanager
        def fausse_coupure(actif):
            vu["demandee"] = actif
            yield actif

        todo._qemu_sans_internet = fausse_coupure
        todo._pve_deploy_spec = lambda *a, **k: vu.setdefault(
            "coupee", k.get("coupee")
        )
        todo._pve_run_spec({"target": "pve1"}, {"offline": True}, None)
        self.assertTrue(vu["demandee"], "la coupure n'a pas été demandée")
        self.assertTrue(vu["coupee"], "le déploiement ignore la coupure")

    def test_une_coupure_impossible_ne_deploie_rien(self):
        """Le refus vient de la coupure elle-même — amont debout, verrou pris,
        dnsmasq absent. Déployer quand même bâtirait une VM en ligne sous une
        promesse de hors-ligne."""
        import contextlib

        from script.todo.qemu_deploy import _SansInternetImpossible

        todo = self._todo()
        vu = {}

        @contextlib.contextmanager
        def refus(actif):
            raise _SansInternetImpossible()
            yield  # pragma: no cover - jamais atteint

        todo._qemu_sans_internet = refus
        todo._pve_deploy_spec = lambda *a, **k: vu.setdefault("parti", True)
        self.assertIsNone(
            todo._pve_run_spec({"target": "pve1"}, {"offline": True}, None)
        )
        self.assertNotIn("parti", vu)

    def test_la_case_atteint_la_spec(self):
        form = {
            "host": {"target": "pve1"},
            "storage": "local-lvm",
            "bridge": "vmbr0",
            "res_label": "x1",
            "ssh_key": "",
            "start": True,
            "add_ssh_config": True,
            "install": None,
            "monitor": True,
            "parallelism": 1,
            "offline": True,
        }
        self.assertTrue(build_spec([{"name": "a"}], [], form)["offline"])
        form["offline"] = False
        self.assertFalse(build_spec([{"name": "a"}], [], form)["offline"])

    def _ecran(self, cache_offert, cocher=False):
        """Monte l'écran avec — ou sans — le cache offert, et relève l'état
        DANS le contexte : `run_test` démonte les widgets en sortant."""
        from textual.widgets import Checkbox

        ctx = contexte()
        ctx["cache_offert"] = cache_offert
        vu = {}

        async def scenario():
            app = run_proxmox_form(ctx, run_app=False)
            async with app.run_test(size=(200, 50)) as pilote:
                await pilote.pause()
                cases = app.query("#f_offline")
                vu["offerte"] = bool(cases)
                if cocher and cases:
                    cases.first(Checkbox).value = True
                    await pilote.pause()
                suivi = app.query_one("#f_monitor", Checkbox)
                vu["suivi"] = suivi.value
                vu["suivi_fige"] = suivi.disabled
                vu["avertissement"] = [
                    w.display for w in app.query("#t_offline_w1")
                ]

        asyncio.run(scenario())
        return vu

    def test_sans_cache_aucune_case(self):
        """Une case sans effet est pire que pas de case : elle promet."""
        self.assertFalse(self._ecran(False)["offerte"])

    def test_avec_le_cache_la_case_est_la_et_muette_tant_quon_ny_touche_pas(
        self,
    ):
        vu = self._ecran(True)
        self.assertTrue(vu["offerte"])
        self.assertEqual(vu["avertissement"], [False])
        self.assertFalse(vu["suivi_fige"])

    def test_cocher_decouvre_lavertissement_et_fige_le_suivi(self):
        """Seule la voie suivie confie la levée au guet : sans suivi, la
        coupure tomberait avec le tableau de bord."""
        vu = self._ecran(True, cocher=True)
        self.assertEqual(vu["avertissement"], [True])
        self.assertTrue(vu["suivi"])
        self.assertTrue(vu["suivi_fige"])


class TestLaTroisDSurProxmox(unittest.TestCase):
    """L'accélération 3D, offerte sur Proxmox VE comme sur QEMU/KVM.

    Deux moitiés, et l'une sans l'autre ne donne rien. L'ÉCRAN se pose à la
    création (« --vga virtio-gl ») ; l'ACCÈS au nœud de rendu est une affaire
    de groupes DANS l'invité, que « qm set » ne sait pas écrire. Sans les
    groupes, toute application GL retombe en rendu logiciel alors que la
    négociation VIRGL a réussi — et rien ne le signale.
    """

    def _todo(self):
        import sys

        sys.argv = ["todo.py"]
        from script.todo.todo import TODO

        return TODO.__new__(TODO)

    def test_les_groupes_sont_crees_avant_detre_donnes(self):
        """« usermod -aG » sur un groupe inconnu échoue, et « render » manque
        des images les plus anciennes."""
        todo = self._todo()
        vu = {}

        def faux_ssh(cible, cmd, timeout=120):
            vu["cible"], vu["cmd"] = cible, cmd
            return 0, ""

        todo._pve_ssh = faux_ssh
        import contextlib
        import io

        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(todo._pve_set_gpu_groups("pve+vm-a", "erplibre"))
        self.assertEqual(vu["cible"], "pve+vm-a")
        self.assertLess(
            vu["cmd"].index("groupadd -f render"),
            vu["cmd"].index("usermod -aG"),
        )
        self.assertIn("groupadd -f video", vu["cmd"])
        self.assertIn("usermod -aG render,video erplibre", vu["cmd"])

    def test_un_echec_est_dit_et_non_tu(self):
        todo = self._todo()
        todo._pve_ssh = lambda *a, **k: (255, "")
        import contextlib
        import io

        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie):
            self.assertFalse(todo._pve_set_gpu_groups("pve+vm-a", "erplibre"))
        self.assertIn("255", sortie.getvalue())

    def test_la_sonde_exige_le_noeud_ET_les_trois_bibliotheques(self):
        """Un hôte sans GPU n'expose aucun nœud de rendu ; sans VIRGL, GL ou
        EGL, Proxmox refuse de démarrer la machine — « missing libraries for
        'virtio-gl' detected! Please install 'libgl1' and 'libegl1' » —, et
        il le refuse APRÈS avoir écrit le disque. Un hôte peut porter GL sans
        EGL : les exiger ensemble est le seul contrôle qui vaille."""
        todo = self._todo()
        vus = []

        def faux_show(remote, timeout=120, quiet=False):
            vus.append(remote)
            # Rien de manquant : la sonde ne dit que son jeton final.
            return 0, "FIN\n"

        todo._pve_show = faux_show
        # Tout est là : la sonde ne dit que « FIN ».
        self.assertEqual(todo._pve_gpu_dispo(), (True, ""))
        for attendu in (
            "/dev/dri/renderD*",
            "libvirglrenderer.so.*",
            "libGL.so.1",
            "libEGL.so.1",
        ):
            self.assertIn(attendu, vus[0])

    def test_la_sonde_nomme_ce_qui_manque(self):
        """Le cas vécu : un hôte porte GL mais pas EGL, et Proxmox refuse de
        démarrer la machine APRÈS avoir écrit son disque. La case ne doit pas
        disparaître en silence — ce qui manque se nomme."""
        todo = self._todo()
        todo._pve_show = lambda *a, **k: (0, "libegl1\nFIN\n")
        self.assertEqual(todo._pve_gpu_dispo(), (False, "libegl1"))
        todo._pve_show = lambda *a, **k: (0, "noeud\nlibgl1\nlibegl1\nFIN\n")
        self.assertEqual(
            todo._pve_gpu_dispo(), (False, "noeud libgl1 libegl1")
        )

    def test_une_sonde_qui_naboutit_pas_naccuse_rien(self):
        """Sans le jeton final, une sortie vide voudrait dire « tout est
        là » : c'est ssh qui a échoué, et on ne promet rien."""
        todo = self._todo()
        todo._pve_show = lambda *a, **k: (0, "")
        self.assertEqual(todo._pve_gpu_dispo(), (False, ""))
        todo._pve_show = lambda *a, **k: (255, "FIN")
        self.assertEqual(todo._pve_gpu_dispo(), (False, ""))

    def test_le_choix_atteint_la_commande_de_creation(self):
        from pathlib import Path

        racine = Path(__file__).resolve().parent.parent
        src = (racine / "script" / "todo" / "proxmox_menu.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"gpu3d": bool(spec.get("gpu3d"))', src)
        # UNE sonde, deux clés : l'écran ne doit pas pouvoir offrir la case
        # et nommer en même temps ce qui l'empêche.
        self.assertIn("gpu_possible, gpu_manque = self._pve_gpu_dispo()", src)
        self.assertIn('"gpu_offert": gpu_possible', src)
        self.assertIn('"gpu_manque": gpu_manque', src)

    def test_la_case_atteint_la_spec(self):
        form = {
            "host": {"target": "pve1"},
            "storage": "local-lvm",
            "bridge": "vmbr0",
            "res_label": "x1",
            "ssh_key": "",
            "start": True,
            "add_ssh_config": True,
            "install": None,
            "monitor": True,
            "parallelism": 1,
            "gpu3d": True,
        }
        self.assertTrue(build_spec([{"name": "a"}], [], form)["gpu3d"])
        form["gpu3d"] = False
        self.assertFalse(build_spec([{"name": "a"}], [], form)["gpu3d"])

    def _ecran(self, gpu_offert, cocher=False, manque=""):
        """Monte l'écran avec — ou sans — la 3D possible sur l'hôte."""
        from textual.widgets import Checkbox, Static

        ctx = contexte()
        ctx["gpu_offert"] = gpu_offert
        ctx["gpu_manque"] = manque
        vu = {}

        async def scenario():
            app = run_proxmox_form(ctx, run_app=False)
            async with app.run_test(size=(200, 50)) as pilote:
                await pilote.pause()
                cases = app.query("#f_gpu3d")
                vu["offerte"] = bool(cases)
                if cocher and cases:
                    cases.first(Checkbox).value = True
                    await pilote.pause()
                vu["valeur"] = app._form_values()["gpu3d"]
                # Relevé DANS le contexte : « run_test » démonte les widgets
                # en sortant, et le texte n'existerait plus après.
                vu["explication"] = " ".join(
                    str(getattr(w, "_content", "") or w.render())
                    for w in app.query("#t_gpu_manque")
                )
                vu["geste"] = " ".join(
                    str(getattr(w, "_content", "") or w.render())
                    for w in app.query("#t_gpu_geste")
                )
                assert Static  # l'import sert au typage de la requête

        asyncio.run(scenario())
        return vu

    def test_sans_gpu_sur_lhote_aucune_case(self):
        """Une case qui promettrait une accélération que l'hôte ne peut pas
        rendre vaut moins que pas de case."""
        vu = self._ecran(False)
        self.assertFalse(vu["offerte"])
        self.assertFalse(vu["valeur"])

    def test_ce_qui_manque_est_nomme_avec_son_paquet(self):
        """Le cas vécu : la case avait disparu après correction de la sonde,
        sans que rien ne dise pourquoi. Elle nomme désormais la pièce ET la
        commande qui la pose — sur l'HÔTE, pas dans la VM."""
        vu = self._ecran(False, manque="libegl1")
        self.assertFalse(vu["offerte"])
        self.assertIn("libegl1", vu["explication"])
        self.assertIn("apt install libegl1", vu["geste"])

    def test_un_noeud_de_rendu_absent_ne_propose_aucun_paquet(self):
        """Le nœud vient du matériel ou d'un GPU transmis : « apt install
        noeud » enverrait l'opérateur dans le mur."""
        vu = self._ecran(False, manque="noeud")
        self.assertIn("noeud", vu["explication"])
        self.assertEqual(vu["geste"], "")

    def test_rien_nest_dit_quand_la_sonde_na_pas_abouti(self):
        """Sonde muette : on ne promet rien, et on n'accuse rien non plus."""
        vu = self._ecran(False)
        self.assertEqual(vu["explication"], "")
        self.assertEqual(vu["geste"], "")

    def test_avec_un_gpu_la_case_est_la_et_decochee(self):
        vu = self._ecran(True)
        self.assertTrue(vu["offerte"])
        self.assertFalse(vu["valeur"])

    def test_cocher_porte_le_choix_jusqua_la_spec(self):
        self.assertTrue(self._ecran(True, cocher=True)["valeur"])

    def _bouton(self, manque="libegl1", apres=(True, ""), moyen=True):
        """Monte l'écran, presse « Installer sur l'hôte », relève la suite.

        « suspend() » est remplacé : un écran monté sans terminal ne peut pas
        le rendre, et ce n'est pas lui qu'on éprouve. Ce qu'on éprouve, c'est
        que le paquet parte, que l'hôte soit RELU, et que l'écran suive.
        """
        import contextlib

        from textual.widgets import Button

        ctx = contexte()
        ctx["gpu_offert"] = False
        ctx["gpu_manque"] = manque
        vu = {"recu": None, "notes": []}
        if moyen:
            ctx["installer_gpu"] = lambda paquets: (
                vu.update(recu=paquets) or True
            )
            ctx["sonder_gpu"] = lambda: apres

        async def scenario():
            app = run_proxmox_form(ctx, run_app=False)
            async with app.run_test(size=(200, 60)) as pilote:
                await pilote.pause()
                app.suspend = lambda: contextlib.nullcontext()
                app.notify = lambda m, **k: vu["notes"].append(str(m))
                boutons = app.query("#f_gpu_poser")
                vu["bouton"] = bool(boutons)
                if boutons:
                    boutons.first(Button).press()
                    await pilote.pause()
                    await pilote.pause()
                vu["case"] = bool(app.query("#f_gpu3d"))
                vu["lignes"] = bool(app.query("#t_gpu_manque"))

        asyncio.run(scenario())
        return vu

    def test_le_bouton_pose_le_paquet_et_la_case_apparait(self):
        """Ce que l'opérateur demande : ne pas quitter l'écran pour une
        commande que l'écran vient de lui montrer."""
        vu = self._bouton()
        self.assertTrue(vu["bouton"])
        self.assertEqual(vu["recu"], "libegl1")
        self.assertTrue(vu["case"], "la case n'est pas apparue")
        self.assertFalse(vu["lignes"], "le message est resté sous la case")

    def test_seuls_les_paquets_partent_a_linstallation(self):
        """Le nœud de rendu ne s'installe pas : l'envoyer à apt ferait
        échouer la pose des paquets qui, eux, existent."""
        self.assertEqual(
            self._bouton(manque="noeud libegl1")["recu"], "libegl1"
        )

    def test_un_noeud_seul_ne_donne_aucun_bouton(self):
        vu = self._bouton(manque="noeud")
        self.assertFalse(vu["bouton"])
        self.assertFalse(vu["case"])

    def test_sans_moyen_de_poser_aucun_bouton(self):
        """Un bouton sans effet vaut moins qu'une commande à recopier."""
        self.assertFalse(self._bouton(moyen=False)["bouton"])

    def test_lhote_est_relu_et_la_case_ne_vient_pas_sur_parole(self):
        """Croire apt sur parole offrirait une case que Proxmox refuserait
        ensuite — après avoir écrit le disque de la VM."""
        vu = self._bouton(apres=(False, "libgl1"))
        self.assertFalse(vu["case"])
        self.assertTrue(vu["lignes"], "le message a disparu pour rien")
        self.assertTrue(any("libgl1" in n for n in vu["notes"]), vu["notes"])


class TestLeMiroirAptDesVmProxmox(unittest.TestCase):
    """Une VM Proxmox tire du miroir que le cache a rempli.

    Le magasin range ses index sous l'HÔTE demandé. Une VM qui réclame
    « archive.ubuntu.com » ne retrouve donc rien de ce qu'une autre a gardé
    depuis un miroir : hors ligne, chacun de ces index manque, et
    l'installation échoue plus bas sur des dépendances introuvables — un
    message qui accuse le dépôt, jamais le miroir.
    """

    def _todo(self):
        import sys

        sys.argv = ["todo.py"]
        from script.todo.todo import TODO

        return TODO.__new__(TODO)

    class _Mod:
        APT_MIRRORS_MAIN = [
            "http://miroir.invalid/ubuntu",
            "http://second.invalid/ubuntu",
        ]
        APT_MIRRORS_PORTS = ["http://miroir.invalid/ubuntu-ports"]
        PORTS_ARCHES = ("arm64", "s390x")

    def _poser(self, vm, code=0):
        import contextlib
        import io

        todo = self._todo()
        vu = {}

        def faux_ssh(cible, cmd, timeout=120):
            vu["cible"], vu["cmd"] = cible, cmd
            return code, ""

        todo._pve_ssh = faux_ssh
        with contextlib.redirect_stdout(io.StringIO()) as sortie:
            vu["rendu"] = todo._pve_set_apt_mirror("pve+vm-a", vm, self._Mod)
        vu["ecrit"] = sortie.getvalue()
        return vu

    def test_le_premier_miroir_remplace_les_depots_officiels(self):
        vu = self._poser({"distro": "ubuntu", "arch": "amd64"})
        self.assertTrue(vu["rendu"])
        self.assertIn("miroir.invalid/ubuntu", vu["cmd"])
        self.assertIn("archive|security", vu["cmd"])
        self.assertNotIn("second.invalid", vu["cmd"])

    def test_the_mirror_decision_reaches_the_log(self):
        """La console défile ; le journal est ce qu'on rouvre le lendemain.

        C'est en le rouvrant qu'on cherche quel miroir a été posé, le jour où
        l'installation échoue plus bas sur des dépendances introuvables — un
        message qui accuse le dépôt, jamais le miroir. Dite à l'écran seule,
        la décision manquait à l'endroit exact où on la cherche.
        """
        for code, marque, porte in (
            (0, "✓", "miroir.invalid"),
            (7, "⚠", "(7)"),
        ):
            with self.subTest(code=code):
                vm = {"distro": "ubuntu", "arch": "amd64"}
                self._poser(vm, code=code)
                notes = vm.get("notes") or []
                self.assertEqual(len(notes), 1, notes)
                self.assertTrue(notes[0].startswith(marque), notes[0])
                self.assertIn(porte, notes[0])

    def test_the_pinned_mirror_is_named_in_the_log(self):
        """« posé » sans dire lequel n'apprend rien : c'est le NOM qu'on
        vient chercher."""
        vm = {"distro": "ubuntu", "arch": "amd64"}
        self._poser(vm)
        self.assertIn("miroir.invalid/ubuntu", (vm["notes"] or [""])[0])

    def test_les_deux_formats_de_sources_sont_couverts(self):
        """Le « .sources » deb822 des images récentes, et le
        « sources.list » des anciennes : n'en réécrire qu'un laisse l'autre
        pointer ailleurs."""
        cmd = self._poser({"distro": "ubuntu", "arch": "amd64"})["cmd"]
        self.assertIn("/etc/apt/sources.list ", cmd)
        self.assertIn("sources.list.d/*.sources", cmd)
        self.assertIn("sources.list.d/*.list", cmd)

    def test_une_arche_ports_prend_son_propre_miroir(self):
        """Les arches « ports » ne sont pas sur archive.ubuntu.com, et amd64
        n'est pas sur ports.ubuntu.com."""
        cmd = self._poser({"distro": "ubuntu", "arch": "arm64"})["cmd"]
        # Le motif est une EXPRESSION : ses points sont échappés, sans quoi
        # ils vaudraient « n'importe quel caractère ».
        self.assertIn(r"ports\.ubuntu\.com/ubuntu-ports", cmd)
        self.assertIn("miroir.invalid/ubuntu-ports", cmd)

    def test_les_autres_distributions_sont_laissees_tranquilles(self):
        """Debian, Fedora et Arch ont leurs propres dépôts : y réécrire une
        URI ubuntu ne viserait rien."""
        todo = self._todo()
        todo._pve_ssh = lambda *a, **k: self.fail("ssh lancé pour rien")
        self.assertFalse(
            todo._pve_set_apt_mirror(
                "pve+vm-a", {"distro": "debian", "arch": "amd64"}, self._Mod
            )
        )

    def test_un_echec_est_dit(self):
        vu = self._poser({"distro": "ubuntu", "arch": "amd64"}, code=255)
        self.assertFalse(vu["rendu"])
        self.assertIn("255", vu["ecrit"])

    def test_le_miroir_est_pose_avant_lautorite_du_cache(self):
        """L'ordre est le sujet : l'autorité sert aux téléchargements, et le
        miroir décide OÙ ils vont. Posé après, il ne vaudrait que pour ce qui
        reste à venir."""
        from pathlib import Path

        racine = Path(__file__).resolve().parent.parent
        src = (racine / "script" / "todo" / "proxmox_menu.py").read_text(
            encoding="utf-8"
        )
        self.assertLess(
            src.index('self._pve_set_apt_mirror(vm["alias"]'),
            src.index("self._pve_set_cache_ca("),
        )


class TestLAttenteAvantLesGestesDansLInvite(unittest.TestCase):
    """Une adresse n'est pas une machine prête.

    Vécu : une VM Proxmox est née sans guide, en UTC, sans l'autorité du
    cache et sur le miroir de son image. Les quatre gestes passent tous par
    ssh et partaient dès l'adresse connue, pendant que cloud-init posait
    encore les comptes et les clés. Ils échouaient donc ENSEMBLE, et la panne
    ressemblait à quatre pannes sans lien.
    """

    def _todo(self):
        import sys

        sys.argv = ["todo.py"]
        from script.todo.todo import TODO

        return TODO.__new__(TODO)

    @property
    def attendre(self):
        """La VRAIE attente : le module de test la remplace partout
        ailleurs, et c'est elle qu'on éprouve ici."""
        from script.todo.proxmox_menu import ProxmoxMenuMixin

        return ProxmoxMenuMixin._pve_attendre_ssh

    def test_elle_rend_vrai_des_que_le_ssh_repond(self):
        todo = self._todo()
        essais = []
        todo._pve_ssh = lambda c, cmd, timeout=120: (
            essais.append(cmd),
            (0, ""),
        )[1]
        self.assertTrue(self.attendre(todo, "pve+vm-a"))
        self.assertEqual(essais, ["true"], "une seule sonde suffit")

    def test_elle_rend_faux_au_bout_du_delai(self):
        """Bornée par le TEMPS : un essai coûte le délai de connexion de ssh,
        que rien ici ne borne à l'avance."""
        import contextlib
        import io

        from script.todo import proxmox_menu

        todo = self._todo()
        todo._pve_ssh = lambda c, cmd, timeout=120: (255, "")
        horloge = iter([0, 0, 5, 10, 15, 20, 25, 30, 35, 40])
        with mock.patch.object(proxmox_menu.time, "sleep", lambda _s: None):
            with mock.patch.object(
                proxmox_menu.time, "time", lambda: next(horloge)
            ):
                with contextlib.redirect_stdout(io.StringIO()) as sortie:
                    rendu = self.attendre(todo, "pve+vm-a", delai=20)
        self.assertFalse(rendu)
        self.assertIn("ssh", sortie.getvalue())

    def test_sans_reponse_les_gestes_sont_sautes_et_dits(self):
        """Quatre échecs silencieux valent moins qu'un refus qui se nomme."""
        import contextlib
        import io

        todo = self._todo()
        faits = []
        todo._write_ssh_config_entry = lambda *a, **k: None
        todo._ssh_private_key = lambda k: None
        todo._qemu_list_domains = lambda: []
        todo._pve_guest_ip = lambda vmid, attente=120: ""
        todo._qemu_import_module = lambda: None
        todo._pve_attendre_ssh = lambda *a, **k: False
        for nom in (
            "_pve_write_guide",
            "_pve_set_timezone",
            "_pve_set_apt_mirror",
            "_pve_set_cache_ca",
        ):
            setattr(
                todo, nom, (lambda n: lambda *a, **k: faits.append(n))(nom)
            )
        todo._qemu_install_erplibre_monitored = lambda *a, **k: None
        spec = {
            "host": {"target": "pve1"},
            "vms": [
                {
                    "name": "vm-a",
                    "vmid": 100,
                    "ipconfig": "ip=10.0.0.2/24,gw=10.0.0.1",
                    "distro": "ubuntu",
                    "arch": "amd64",
                }
            ],
            "user": "erplibre",
            "add_ssh_config": True,
            "install": None,
            "monitor": False,
        }
        with contextlib.redirect_stdout(io.StringIO()) as sortie:
            todo._pve_after_create(spec["host"], spec, ["vm-a"], "")
        self.assertEqual(faits, [], f"des gestes sont partis : {faits}")
        self.assertIn("ssh", sortie.getvalue())


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


class TestLaVmCloneLeDepotDistant(unittest.TestCase):
    """« Le problème est revenu » — alors qu'il était corrigé.

    La VM ne reçoit pas le checkout d'ici : elle CLONE la branche depuis le
    dépôt DISTANT. Tout ce qui tourne dedans — install_proxmox.sh, les
    scripts d'installation, le Makefile — vient donc de là. Un correctif
    commité ici et non poussé lui est invisible.

    Vécu deux fois de suite : la correction de /etc/hosts était dans le
    checkout depuis la veille, absente du distant, et chaque VM déployée
    ensuite recevait l'ancien script. Il a fallu comparer les deux versions à
    la main pour le voir. Rien ne le disait."""

    def _todo(self, sortie, code=0):
        import sys

        sys.argv = ["todo.py"]
        from script.todo.todo import TODO

        todo = TODO.__new__(TODO)
        faux = mock.Mock(returncode=code, stdout=sortie)
        return todo, faux

    def test_the_gap_is_counted_and_named(self):
        todo, faux = self._todo(
            "abc1234 [FIX] un correctif\ndef5678 [ADD] autre chose\n"
        )
        with mock.patch("subprocess.run", return_value=faux):
            nombre, sujets = todo._qemu_branch_gap("develop")
        self.assertEqual(nombre, 2)
        self.assertIn("[FIX] un correctif", sujets[0])

    def test_nothing_to_say_when_the_remote_is_up_to_date(self):
        todo, faux = self._todo("")
        with mock.patch("subprocess.run", return_value=faux):
            self.assertEqual(todo._qemu_branch_gap("develop"), (0, []))
            self.assertEqual(todo._qemu_branch_gap_lines("develop"), [])

    def test_an_unknown_remote_branch_is_not_a_gap(self):
        # « origin/xyz » inconnu fait échouer git : ce n'est pas un écart à
        # signaler, c'est une question qui ne se pose pas. Le dire quand même
        # serait un avertissement à chaque déploiement d'une branche neuve.
        todo, faux = self._todo("", code=128)
        with mock.patch("subprocess.run", return_value=faux):
            self.assertEqual(todo._qemu_branch_gap("nouvelle"), (0, []))

    def test_no_branch_asks_nothing(self):
        todo, _faux = self._todo("")
        self.assertEqual(todo._qemu_branch_gap(""), (0, []))

    def test_the_long_list_is_trimmed_but_counted(self):
        todo, faux = self._todo(
            "\n".join(f"c{i} sujet {i}" for i in range(10))
        )
        with mock.patch("subprocess.run", return_value=faux):
            lignes = todo._qemu_branch_gap_lines("develop", limite=2)
        texte = " ".join(lignes)
        self.assertIn("10", texte, "le nombre TOTAL doit rester lisible")
        self.assertIn("8", texte, "et ce qui n'est pas montré, dit")
        self.assertIn("git push", texte)

    def test_both_screens_say_it_before_deploying(self):
        # L'avertissement ne vaut que là où on peut encore renoncer.
        import inspect

        from script.todo.proxmox_menu import ProxmoxMenuMixin
        from script.todo.qemu_deploy import QemuDeployMixin

        for fn in (
            ProxmoxMenuMixin._pve_confirm_spec,
            QemuDeployMixin._qemu_print_recap,
        ):
            with self.subTest(fonction=fn.__name__):
                self.assertIn("_qemu_branch_gap_lines", inspect.getsource(fn))


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

    def test_the_note_only_shows_when_nothing_reboots_it(self):
        """Avec suivi, l'enveloppe redémarre elle-même : réclamer un
        redémarrage déjà fait est une consigne fausse. Sans suivi, la voie en
        série s'arrête à la fin du script, et la note est la seule chose qui
        dit que l'hyperviseur n'est pas encore utilisable."""
        import contextlib
        import io
        import sys

        sys.argv = ["todo.py"]
        from script.todo.todo import TODO

        def sommaire(monitor):
            todo = TODO.__new__(TODO)
            spec = {
                "vms": [{"name": "pve-imbrique"}],
                "install": {
                    "cmd": "./script/proxmox/install_proxmox.sh",
                    "label": "Proxmox VE",
                    "branch": "develop",
                },
                "monitor": monitor,
                "storage": "local",
                "bridge": "vmbr0",
            }
            vm = dict(spec["vms"][0], alias="pve9+pve-imbrique", vmid=102)
            tampon = io.StringIO()
            with contextlib.redirect_stdout(tampon):
                todo._pve_print_summary(spec, [vm], "")
            return tampon.getvalue()

        self.assertIn("reboot", sommaire(monitor=False))
        self.assertNotIn("reboot", sommaire(monitor=True))

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


class TestNeRienPerdreDansSshConfig(unittest.TestCase):
    """~/.ssh/config contient les entrées PERSONNELLES de l'utilisateur.

    Ce fichier est réécrit en entier à chaque déploiement de VM. Deux pertes
    de données y ont été constatées, l'une capable de désactiver la
    vérification de clé d'hôte sur un serveur de production."""

    def setUp(self):
        import sys

        sys.argv = ["todo.py"]
        from script.todo.todo import TODO

        self.retirer = TODO._ssh_config_drop_hosts

    def test_a_block_with_an_unindented_body_goes_entirely(self):
        """L'indentation est COSMÉTIQUE dans ce format, et un fichier écrit à
        la main s'en passe souvent. La règle d'avant la prenait pour de la
        syntaxe : seule la ligne « Host » partait."""
        avant = (
            "Host prod\n"
            "    HostName prod.example.com\n"
            "    User root\n"
            "\n"
            "Host deep-1\n"
            "HostName 10.0.0.1\n"
            "User erplibre\n"
            "StrictHostKeyChecking no\n"
            "UserKnownHostsFile /dev/null\n"
            "IdentityFile ~/.ssh/id_deep\n"
        )
        apres = self.retirer(avant, ["deep-1"])
        # Rien du bloc retiré ne subsiste : sans Host au-dessus, ssh
        # rattacherait ces lignes à « prod » et la production perdrait sa
        # vérification de clé d'hôte.
        for orphelin in (
            "10.0.0.1",
            "StrictHostKeyChecking",
            "UserKnownHostsFile",
            "id_deep",
        ):
            self.assertNotIn(orphelin, apres, orphelin)
        # Et le bloc de l'utilisateur est intact.
        self.assertIn("HostName prod.example.com", apres)
        self.assertIn("User root", apres)

    def test_a_shared_host_line_keeps_the_names_not_dropped(self):
        """« Host prod-db vm-a » perdait le prod-db de l'utilisateur : le bloc
        partait en entier dès qu'UN de ses noms était repris."""
        avant = (
            "Host prod-db vm-a\n    HostName db.interne\n    ProxyJump pve9\n"
        )
        apres = self.retirer(avant, ["vm-a"])
        self.assertIn("Host prod-db\n", apres)
        self.assertNotIn("vm-a", apres)
        # Le corps suit le nom qui reste : sinon prod-db perd son rebond.
        self.assertIn("HostName db.interne", apres)
        self.assertIn("ProxyJump pve9", apres)

    def test_a_nickname_added_by_hand_survives_a_redeploy(self):
        avant = "Host pve9+vm-a webtest\n    HostName 10.10.10.5\n"
        apres = self.retirer(avant, ["pve9+vm-a"])
        self.assertIn("Host webtest\n", apres)
        self.assertIn("HostName 10.10.10.5", apres)

    def test_all_names_dropped_removes_the_block(self):
        avant = "Host a b\n    HostName 1.2.3.4\n\nHost garde\n    User x\n"
        apres = self.retirer(avant, ["a", "b"])
        self.assertNotIn("1.2.3.4", apres)
        self.assertIn("Host garde", apres)

    def test_a_match_section_is_never_swallowed(self):
        avant = (
            "Host part\n"
            "    HostName 10.0.0.9\n"
            "\n"
            "Match host *.interne\n"
            "    User admin\n"
        )
        apres = self.retirer(avant, ["part"])
        self.assertIn("Match host *.interne", apres)
        self.assertIn("User admin", apres)
        self.assertNotIn("10.0.0.9", apres)

    def test_comments_before_the_next_block_are_not_swallowed(self):
        avant = (
            "Host part\n"
            "    HostName 10.0.0.9\n"
            "\n"
            "# la machine du client, ne pas toucher\n"
            "Host client\n"
            "    HostName 10.0.0.10\n"
        )
        apres = self.retirer(avant, ["part"])
        self.assertIn("# la machine du client, ne pas toucher", apres)
        self.assertIn("Host client", apres)

    def test_global_directives_above_the_first_host_stay(self):
        avant = "ServerAliveInterval 60\n\nHost part\n    HostName 10.0.0.9\n"
        apres = self.retirer(avant, ["part"])
        self.assertIn("ServerAliveInterval 60", apres)
        self.assertNotIn("10.0.0.9", apres)

    def test_the_keyword_is_read_case_insensitively(self):
        # ssh lit ses mots-clés sans égard à la casse ; nous aussi, sinon un
        # « host » minuscule échappe au retrait et le nom vit deux fois.
        avant = "host part\n    HostName 10.0.0.9\n"
        self.assertNotIn("10.0.0.9", self.retirer(avant, ["part"]))

    def test_hostname_is_not_mistaken_for_a_host_line(self):
        avant = "Host garde\n    HostName part\n"
        apres = self.retirer(avant, ["part"])
        self.assertIn("Host garde", apres)
        self.assertIn("HostName part", apres)


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

    def test_dropping_the_last_entry_writes_no_nameless_block(self):
        """Retirer sans réécrire est un appel légitime : les machines
        n'existent plus.

        Constaté dans le vrai ~/.ssh/config de l'utilisateur : l'appel écrivait
        « Host » NU, suivi d'un « HostName » vide, puis mourait sur un
        IndexError en annonçant l'ajout. Le bloc sans nom s'applique à rien et
        brouille la lecture du fichier."""
        import os

        self.todo._write_ssh_config_entry(
            ["deep-1"], "erplibre", "10.10.10.150"
        )
        self.todo._write_ssh_config_entry(
            ["deep-2"], "erplibre", "10.10.10.151", proxy_jump="deep-1"
        )
        self.todo._write_ssh_config_entry(
            [], "erplibre", "", also_drop=("deep-1", "deep-2")
        )
        self.assertEqual(self._hosts(), [])
        with open(
            os.path.join(self.maison, ".ssh/config"), encoding="utf-8"
        ) as fh:
            reste = fh.read()
        self.assertNotIn("Host", reste)
        self.assertNotIn("HostName", reste)
        # Et le fichier garde ses droits : ssh refuse un config trop ouvert.
        self.assertEqual(
            oct(os.stat(os.path.join(self.maison, ".ssh/config")).st_mode)[
                -3:
            ],
            "600",
        )

    def test_dropping_one_entry_leaves_the_others_untouched(self):
        for nom, ip in (("garde-a", "10.0.0.1"), ("part", "10.0.0.2")):
            self.todo._write_ssh_config_entry([nom], "erplibre", ip)
        self.todo._write_ssh_config_entry(
            [], "erplibre", "", also_drop=("part",)
        )
        self.assertEqual(self._hosts(), ["Host garde-a"])

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


class TestLAutoriteDuCacheDansUneVmImbriquee(unittest.TestCase):
    """Une VM née sur un Proxmox imbriqué est interceptée sans le savoir.

    Le cache détourne tout ce qui sort de son pont. Un hôte Proxmox qui est
    lui-même une VM d'ici y est branché, et les machines qu'il porte sortent
    derrière son adresse : elles traversent donc le cache, alors que rien à
    l'intérieur ne leur a donné son autorité. Le mode de défaillance est
    trompeur — un dépôt apt en clair passe, si bien que l'installation
    démarre, et seuls les téléchargements HTTPS échouent, sur « self-signed
    certificate in certificate chain ».

    « qm set » ne sait écrire aucun fichier : l'autorité part par ssh, depuis
    la MÊME source que la voie libvirt (`cache_files`, `cache_commands`).
    """

    def _todo(self, domaines=("pve-local",), ca="/tmp/ca.crt"):
        import sys

        sys.argv = ["todo.py"]
        from script.todo.todo import TODO

        todo = TODO.__new__(TODO)
        todo._qemu_list_domains = lambda: list(domaines)
        todo._qemu_cache_ca_path = classmethod(lambda cls: ca).__get__(
            todo, type(todo)
        )
        return todo

    # -- Qui est concerné ----------------------------------------------

    def test_a_nested_proxmox_host_gets_the_authority(self):
        todo = self._todo()
        self.assertEqual(
            todo._pve_cache_ca({"target": "root@pve-local"}),
            "/tmp/ca.crt",
        )

    def test_a_proxmox_host_that_lives_elsewhere_gets_nothing(self):
        """Son trafic ne traverse pas ce pont : l'autorité n'y servirait à
        rien, et le cache doit s'installer sur cet hôte-là."""
        todo = self._todo()
        self.assertEqual(todo._pve_cache_ca({"target": "root@10.0.0.5"}), "")

    def test_no_cache_installed_here_means_no_authority(self):
        todo = self._todo(ca="")
        self.assertEqual(todo._pve_cache_ca({"target": "pve-local"}), "")

    # -- Ce qui est réellement posé ------------------------------------

    def _pose(self, distro="ubuntu", cache_files=None):
        import contextlib
        import io
        import tempfile

        todo = self._todo()
        vus = {}
        todo._pve_ssh = lambda cible, remote, timeout=60: (
            vus.update(cible=cible, remote=remote, timeout=timeout) or (0, "")
        )
        mod = todo._qemu_import_module()
        with tempfile.NamedTemporaryFile(
            "w", suffix=".crt", delete=False
        ) as fh:
            fh.write("-----BEGIN CERTIFICATE-----\nZm F1eA==\n")
            fh.write("-----END CERTIFICATE-----\n")
            ca = fh.name
        patch = (
            mock.patch.object(mod, "cache_files", cache_files)
            if cache_files
            else contextlib.nullcontext()
        )
        with contextlib.redirect_stdout(io.StringIO()), patch:
            vus["ok"] = todo._pve_set_cache_ca(
                "hote+vm-a", {"name": "vm-a", "distro": distro}, ca
            )
        return vus

    def test_the_authority_goes_where_the_family_reads_it(self):
        vus = self._pose()
        self.assertTrue(vus["ok"])
        # Par l'ALIAS : lui seul porte le rebond vers le réseau interne.
        self.assertEqual(vus["cible"], "hote+vm-a")
        self.assertIn(
            "/usr/local/share/ca-certificates/erplibre-cache.crt",
            vus["remote"],
        )

    def test_arch_does_not_get_the_debian_path(self):
        vus = self._pose(distro="arch")
        self.assertIn(
            "/etc/ca-certificates/trust-source/anchors", vus["remote"]
        )
        self.assertNotIn("/usr/local/share/ca-certificates", vus["remote"])

    def test_the_store_is_reread_then_the_variables_are_written(self):
        """Dans cet ordre : les variables visent le faisceau que la commande
        de confiance vient de régénérer."""
        vus = self._pose()
        confiance = vus["remote"].index("update-ca-certificates")
        for var in ("PIP_CERT", "REQUESTS_CA_BUNDLE", "NODE_EXTRA_CA_CERTS"):
            self.assertLess(confiance, vus["remote"].index(var), var)

    def test_the_content_comes_from_cache_files_and_is_not_rebuilt_here(self):
        """Une seule source pour les deux voies de livraison : ce que
        cloud-init écrirait est ce que ssh pose."""
        vus = self._pose(
            cache_files=lambda args: [
                ("/etc/anchors/temoin.crt", "0644", "PEM-TEMOIN", "")
            ]
        )
        self.assertIn("/etc/anchors/temoin.crt", vus["remote"])
        self.assertIn("PEM-TEMOIN", vus["remote"])

    def test_a_distro_out_of_the_table_poses_nothing(self):
        """Le fichier au mauvais endroit ne servirait à rien sans rien
        dire ; la VM télécharge en direct, ce qui marche."""
        vus = self._pose(distro="plan9")
        self.assertFalse(vus["ok"])
        self.assertNotIn("remote", vus)

    # -- Le câblage ----------------------------------------------------

    def test_the_authority_is_posed_before_the_install(self):
        """Le contrôle porte sur l'ORDRE : c'est l'installation qui
        télécharge, et un magasin relu ensuite ne rattrape rien."""
        import contextlib
        import io
        import sys

        sys.argv = ["todo.py"]
        from script.todo.todo import TODO

        ordre = []
        todo = TODO.__new__(TODO)
        todo._write_ssh_config_entry = lambda *a, **k: None
        todo._ssh_private_key = lambda k: None
        todo._pve_alias_perime = lambda *a, **k: []
        todo._qemu_list_domains = lambda: ["pve-local"]
        todo._qemu_cache_ca_path = classmethod(
            lambda cls: "/tmp/ca.crt"
        ).__get__(todo, type(todo))
        todo._pve_guest_ip = lambda vmid, attente=120: ""
        todo._pve_write_guide = lambda *a, **k: True
        todo._pve_set_timezone = lambda *a, **k: True
        todo._qemu_import_module = lambda: None
        todo._pve_set_cache_ca = lambda cible, vm, ca, **k: ordre.append(
            ("autorité", cible, ca)
        )
        todo._qemu_install_erplibre_monitored = lambda *a, **k: ordre.append(
            ("installation",)
        )
        spec = {
            "host": {"target": "root@pve-local"},
            "vms": [
                {
                    "name": "vm-a",
                    "vmid": 100,
                    "distro": "ubuntu",
                    "ipconfig": "ip=10.10.10.150/24,gw=10.10.10.1",
                    "install_cmd": "",
                }
            ],
            "user": "erplibre",
            "add_ssh_config": True,
            "install": {"branch": "develop", "cmd": "make x", "label": "X"},
            "monitor": True,
            "desktop": "",
        }
        with contextlib.redirect_stdout(io.StringIO()):
            todo._pve_after_create(spec["host"], spec, ["vm-a"], "")
        self.assertEqual([e[0] for e in ordre], ["autorité", "installation"])
        self.assertEqual(ordre[0][2], "/tmp/ca.crt")

    def test_a_remote_host_does_not_get_the_step_at_all(self):
        import contextlib
        import io
        import sys

        sys.argv = ["todo.py"]
        from script.todo.todo import TODO

        appels = []
        todo = TODO.__new__(TODO)
        todo._write_ssh_config_entry = lambda *a, **k: None
        todo._ssh_private_key = lambda k: None
        todo._pve_alias_perime = lambda *a, **k: []
        todo._qemu_list_domains = lambda: []
        todo._qemu_cache_ca_path = classmethod(
            lambda cls: "/tmp/ca.crt"
        ).__get__(todo, type(todo))
        todo._pve_guest_ip = lambda vmid, attente=120: ""
        todo._pve_write_guide = lambda *a, **k: True
        todo._pve_set_timezone = lambda *a, **k: True
        todo._qemu_import_module = lambda: None
        todo._pve_set_cache_ca = lambda *a: appels.append(a)
        todo._qemu_install_erplibre_monitored = lambda *a, **k: None
        spec = {
            "host": {"target": "root@10.0.0.5"},
            "vms": [
                {
                    "name": "vm-a",
                    "vmid": 100,
                    "distro": "ubuntu",
                    "ipconfig": "ip=10.10.10.150/24,gw=10.10.10.1",
                    "install_cmd": "",
                }
            ],
            "user": "erplibre",
            "add_ssh_config": True,
            "install": None,
            "monitor": False,
            "desktop": "",
        }
        with contextlib.redirect_stdout(io.StringIO()):
            todo._pve_after_create(spec["host"], spec, ["vm-a"], "")
        self.assertEqual(appels, [])


class TestLAutoriteDUneVmProxmoxHorsLigne(unittest.TestCase):
    """Une VM Proxmox déployée hors ligne reçoit, comme la voie libvirt, de quoi
    couper l'audit de npm : aucun cache ne rejoue ce service."""

    def test_seule_la_vm_hors_ligne_coupe_l_audit(self):
        import contextlib
        import io
        import sys
        import tempfile

        sys.argv = ["todo.py"]
        from script.todo.todo import TODO

        todo = TODO.__new__(TODO)
        vu = {}

        def faux_ssh(cible, cmd, timeout=120):
            vu["cmd"] = cmd
            return 0, ""

        todo._pve_ssh = faux_ssh
        with tempfile.NamedTemporaryFile(
            "w", suffix=".crt", delete=False
        ) as fh:
            fh.write("-----BEGIN CERTIFICATE-----\nZm F1eA==\n")
            fh.write("-----END CERTIFICATE-----\n")
            ca = fh.name
        rendus = {}
        with contextlib.redirect_stdout(io.StringIO()):
            for hors_ligne in (True, False):
                todo._pve_set_cache_ca(
                    "hote+vm-a",
                    {"name": "vm-a", "distro": "ubuntu"},
                    ca,
                    hors_ligne=hors_ligne,
                )
                rendus[hors_ligne] = vu.get("cmd", "")
        self.assertIn("NPM_CONFIG_AUDIT", rendus[True])
        self.assertNotIn("NPM_CONFIG_AUDIT", rendus[False])


class TestUnInviteQueLAutoriteNAtteintPas(unittest.TestCase):
    """Une distribution dont le magasin de confiance n'a pas de forme par
    fichier ne reçoit rien à poser.

    On n'arrive ici que lorsque l'hôte Proxmox est lui-même une VM de ce pont
    — c'est la condition de _pve_cache_ca. Son invité est donc détourné par
    le cache, et sans autorité chaque téléchargement HTTPS échoue sur
    « self-signed certificate in certificate chain ». Le taire déplace la
    panne dans la VM, des minutes plus tard et sans sa cause.
    """

    def _todo(self):
        import sys

        sys.argv = ["todo.py"]
        from script.todo.todo import TODO

        return TODO.__new__(TODO)

    class _Sans:
        @staticmethod
        def cache_files(args):
            return []

    class _Avec:
        @staticmethod
        def cache_files(args):
            return [
                ("/usr/local/share/ca-certificates/x.crt", "0644", "PEM", "")
            ]

        @staticmethod
        def cache_commands(args):
            return ["update-ca-certificates"]

    def _poser(self, mod, distro):
        import contextlib
        import io

        todo = self._todo()
        vu = {"ssh": []}
        todo._qemu_import_module = lambda: mod
        todo._pve_ssh = lambda cible, cmd, timeout=120: (
            vu["ssh"].append(cmd) or (0, "")
        )
        with contextlib.redirect_stdout(io.StringIO()) as sortie:
            vu["rendu"] = todo._pve_set_cache_ca(
                "pve+vm-a", {"distro": distro}, "/var/lib/cache/ca.crt"
            )
        vu["ecrit"] = sortie.getvalue()
        return vu

    def test_la_distribution_sans_magasin_est_nommee(self):
        vu = self._poser(self._Sans, "nixos")
        self.assertFalse(vu["rendu"])
        self.assertEqual([], vu["ssh"], "ssh lancé pour rien")
        self.assertIn("⚠", vu["ecrit"])
        self.assertIn("nixos", vu["ecrit"])

    def test_celle_qui_en_a_un_le_pose_sans_avertir(self):
        """L'avertissement ne doit pas se banaliser : le cas ordinaire sort
        un « ✓ » et rien d'autre."""
        vu = self._poser(self._Avec, "debian")
        self.assertTrue(vu["rendu"])
        self.assertEqual(1, len(vu["ssh"]))
        self.assertIn("update-ca-certificates", vu["ssh"][0])
        self.assertNotIn("⚠", vu["ecrit"])


class UnInviteImbriqueSortMasqueDerriereSonHote(unittest.TestCase):
    """Une distribution sans magasin de confiance par fichier ne peut RIEN
    recevoir, et le poser par déclaration arriverait trop tard : sur un
    système déclaratif, la première reconstruction EST le premier
    téléchargement.

    Le remède est de ne pas intercepter. Mais l'invité imbriqué sort MASQUÉ
    derrière son hôte : sur le pont d'ici, le cache ne voit que la MAC de
    l'hôte Proxmox, et c'est donc elle qu'il faut excepter.
    """

    def _todo(self):
        import sys

        sys.argv = ["todo.py"]
        from script.todo.todo import TODO

        return TODO.__new__(TODO)

    class _Mod:
        CACHE_BIN = "/usr/local/bin/erplibre_go_qemu_cache"

        @staticmethod
        def cache_sans_autorite(distro):
            return distro == "nixos"

    def _poser(self, distro, domaines=("pve-local",), mac="52:54:00:ab:cd:ef"):
        import contextlib
        import io

        todo = self._todo()
        vu = {"cmd": None}
        todo._qemu_import_module = lambda: self._Mod
        todo._qemu_list_domains = lambda: list(domaines)
        todo._qemu_domain_mac = lambda nom: mac

        class Fini:
            returncode = 0
            stdout = ""
            stderr = ""

        def faux_run(cmd, **kw):
            vu["cmd"] = cmd
            return Fini()

        import subprocess as sp

        vrai = sp.run
        self.addCleanup(setattr, sp, "run", vrai)
        sp.run = faux_run
        with contextlib.redirect_stdout(io.StringIO()) as sortie:
            vu["rendu"] = todo._pve_cache_bypass_hote(
                {"target": "pve-local"}, {"distro": distro}
            )
        vu["ecrit"] = sortie.getvalue()
        return vu

    def test_a_guest_with_a_trust_store_is_left_alone(self):
        """L'autorité suffit pour lui, et excepter son hôte lui retirerait le
        cache sans rien lui rendre."""
        vu = self._poser("debian")
        self.assertFalse(vu["rendu"])
        self.assertIsNone(vu["cmd"], "une commande lancée pour rien")

    def test_a_module_that_will_not_load_does_not_stop_the_creation(self):
        """Sans le module on ne sait pas si l'invité a un magasin de
        confiance : l'autorité reste la voie par défaut, et la suite de la
        création continue."""
        import contextlib
        import io

        todo = self._todo()
        todo._qemu_import_module = lambda: None
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(
                todo._pve_cache_bypass_hote(
                    {"target": "pve-local"}, {"distro": "nixos"}
                )
            )

    def test_a_remote_host_never_crosses_this_bridge(self):
        """Un hôte Proxmox qui ne vit pas ici n'est pas intercepté : rien à
        excepter, et sa MAC ne nous appartient pas."""
        vu = self._poser("nixos", domaines=())
        self.assertFalse(vu["rendu"])
        self.assertIsNone(vu["cmd"])

    def test_the_host_mac_is_the_one_excepted(self):
        """Celle de l'invité n'apparaît jamais sur ce pont : il est masqué."""
        vu = self._poser("nixos")
        self.assertTrue(vu["rendu"])
        joint = " ".join(vu["cmd"])
        self.assertIn("--bypass-add 52:54:00:ab:cd:ef", joint)
        self.assertIn("--bypass-name pve-local", joint)

    def test_the_decision_is_kept_for_the_log(self):
        """Dit à l'écran ET gardé : la console défile, le journal reste."""
        import contextlib
        import io

        todo = self._todo()
        vm = {"distro": "x"}
        with contextlib.redirect_stdout(io.StringIO()) as sortie:
            todo._pve_note(vm, "  ✓ une décision")
        self.assertIn("une décision", sortie.getvalue())
        self.assertEqual(["✓ une décision"], vm["notes"])

    def test_the_menu_hands_them_to_the_installer(self):
        """Gardées et non transmises, elles ne serviraient à personne."""
        from pathlib import Path

        racine = Path(__file__).resolve().parent.parent
        src = (racine / "script/todo/proxmox_menu.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("notes={", src)
        dep = (racine / "script/todo/qemu_deploy.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('entry["notes"] = list(notes[name])', dep)

    def test_offline_never_exempts(self):
        """L'amont du cache est alors coupé et le magasin est la SEULE
        source : excepter l'hôte ne le ferait pas télécharger en direct, cela
        le priverait de tout — ses propres paquets compris. Les deux issues
        échouent pour l'invité, mais celle-ci emporte l'hôte avec lui."""
        import contextlib
        import io
        import subprocess as sp

        todo = self._todo()
        todo._qemu_import_module = lambda: self._Mod
        todo._qemu_list_domains = lambda: ["pve-local"]
        todo._qemu_domain_mac = lambda nom: "52:54:00:ab:cd:ef"
        lance = []
        vrai = sp.run
        self.addCleanup(setattr, sp, "run", vrai)
        sp.run = lambda c, **k: lance.append(c)
        with contextlib.redirect_stdout(io.StringIO()):
            rendu = todo._pve_cache_bypass_hote(
                {"target": "pve-local"}, {"distro": "nixos"}, hors_ligne=True
            )
        self.assertFalse(rendu)
        self.assertEqual([], lance, "une exception posée hors ligne")

    def test_the_price_is_said(self):
        """L'exception vaut pour TOUT ce que l'hôte relaie, ses propres
        téléchargements compris. Le taire ferait chercher plus tard pourquoi
        le cache ne sert plus cet hôte."""
        vu = self._poser("nixos")
        self.assertIn("pve-local", vu["ecrit"])
        self.assertIn("✓", vu["ecrit"])
        self.assertTrue(
            len(vu["ecrit"].strip().splitlines()) >= 2,
            f"le prix n'est pas dit : {vu['ecrit']!r}",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
