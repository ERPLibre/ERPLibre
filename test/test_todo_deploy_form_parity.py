#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les deux écrans de déploiement offrent les MÊMES réglages du système invité.

Type de VM, production, magasin d'applications, outils de développement,
fuseau horaire, interpréteur Python : six réglages qui décrivent l'invité, pas
la machine qui le porte. Ils valent donc mot pour mot sur libvirt et sur
Proxmox VE.

C'est ce qui avait dérivé. L'écran QEMU/KVM les portait tous les six, l'écran
Proxmox trois : une VM créée là-bas naissait serveur nu, sans outils, en UTC —
et rien ne le disait. La duplication était le mécanisme de la dérive, pas son
symptôme : chaque correctif se posait sur un seul des deux écrans.

Ce fichier teste donc la PARITÉ elle-même, et pas six comportements. Ajouter
un réglage à un seul écran le fait échouer, quel que soit ce réglage."""

import asyncio
import sys
import unittest

sys.argv = ["todo.py"]
from script.todo.todo import TODO  # noqa: E402

try:
    import textual  # noqa: F401

    TEXTUAL = True
except Exception:  # pragma: no cover - dépend de l'environnement
    TEXTUAL = False

# Ce que porte le socle partagé. Les identifiants, parce qu'ils sont le
# contrat : c'est par eux que la spec est lue.
REGLAGES = ("f_type", "f_prod", "f_store", "f_tools", "f_tz", "f_python")

CATALOGUE = [
    {
        "distro": "ubuntu",
        "version": "26.04",
        "arch": "amd64",
        "name": "erplibre-ubuntu-2604",
        "ram": 2048,
        "disk": "20G",
    },
]


def todo_muet():
    todo = TODO.__new__(TODO)
    todo._qemu_list_domains = lambda: []
    todo._qemu_branch_list = lambda: ["develop", "master"]
    return todo


def contexte_proxmox(todo):
    """Le contexte de l'écran Proxmox, hôte simulé — aucune VM n'est créée."""
    return dict(
        host={"target": "pve", "label": "pve"},
        node="pve",
        arches=["amd64"],
        native="amd64",
        catalog={"amd64": list(CATALOGUE)},
        names=[],
        vmids=[],
        next_vmid=100,
        storages=["local-lvm"],
        storage="local-lvm",
        storage_avail={"local-lvm": 500 << 30},
        bridges=["vmbr0"],
        bridge="vmbr0",
        ipconfig=lambda _p, _v: "ip=dhcp",
        nameservers=["1.1.1.1"],
        branches=["develop", "master"],
        branch_current="develop",
        install_profiles=[
            ("ERPLibre + Odoo 18", "make install_os && make install_odoo_18")
        ],
        distro_profiles={},
        ssh_key="~/.ssh/id_ed25519.pub",
        cpu_presets=(1, 2, 4),
        ram_presets=(2048, 4096),
        disk_presets=(20, 40),
        base_vcpus=2,
        host_cpu=8,
        free_ram=16000,
        extra_disk_gb=5,
        **todo._qemu_guest_context(),
    )


def releve(fabrique, ctx, gestes=None):
    """Monte l'écran, choisit la première entrée, et relève ce qu'il porte."""
    vu = {}

    async def scenario():
        from textual.widgets import SelectionList

        app = fabrique(ctx, run_app=False)
        async with app.run_test(size=(220, 70)) as pilote:
            await pilote.pause()
            liste = app.query_one(SelectionList)
            liste.select(liste.get_option_at_index(0).value)
            await pilote.pause()
            await pilote.pause()
            if gestes:
                await gestes(app, pilote)
            vu["ids"] = {w.id for w in app.query("#fields *") if w.id}
            vu["spec"] = app._form_values()
            vu["noms"] = [r["vm"]["name"] for r in app.rows]
            vu["disques"] = [r["disk_gb"] for r in app.rows]

    asyncio.run(scenario())
    return vu


@unittest.skipUnless(TEXTUAL, "Textual absent")
class TestLesDeuxEcrans(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from script.todo.proxmox_deploy_form import run_proxmox_form
        from script.todo.qemu_deploy_form import run_deploy_form

        todo = todo_muet()
        mod = todo._qemu_import_module()
        cls.qemu = releve(run_deploy_form, todo._qemu_form_context(mod))
        cls.pve = releve(run_proxmox_form, contexte_proxmox(todo))

    def _porte(self, vu, ident):
        """Un réglage est là s'il a son widget — les outils sont une case par
        outil, donc un préfixe."""
        if ident == "f_tools":
            return any(i.startswith("f_tool_") for i in vu["ids"])
        return ident in vu["ids"]

    def test_both_screens_offer_the_same_guest_settings(self):
        for ident in REGLAGES:
            with self.subTest(reglage=ident):
                self.assertTrue(self._porte(self.qemu, ident), "QEMU/KVM")
                self.assertTrue(self._porte(self.pve, ident), "Proxmox")

    def test_both_specs_carry_the_same_guest_keys(self):
        from script.todo.deploy_form_extras import ExtrasMixin

        attendues = set(ExtrasMixin.extras_values(self._faux()))
        for nom, vu in (("QEMU/KVM", self.qemu), ("Proxmox", self.pve)):
            with self.subTest(ecran=nom):
                self.assertTrue(attendues <= set(vu["spec"]), nom)

    def _faux(self):
        """Un porteur du socle sans écran : la liste des clés ne dépend pas
        des widgets, et c'est justement ce qu'on veut vérifier."""
        from script.todo.deploy_form_extras import ExtrasMixin

        class Vide(ExtrasMixin):
            vms = ()
            rows = ()

            def query_one(self, _s, *_a):
                raise LookupError

        vide = Vide()
        vide.extras_init({})
        return vide

    def test_both_screens_bind_the_same_catalog_shortcuts(self):
        # « Versions principales » (F7) manquait à l'écran Proxmox, qui
        # affiche pourtant le même catalogue, drapeau « default » compris.
        from script.todo.proxmox_deploy_form import run_proxmox_form
        from script.todo.qemu_deploy_form import run_deploy_form

        todo = todo_muet()
        mod = todo._qemu_import_module()
        touches = {}
        for nom, app in (
            ("QEMU/KVM", run_deploy_form(todo._qemu_form_context(mod), False)),
            ("Proxmox", run_proxmox_form(contexte_proxmox(todo), False)),
        ):
            touches[nom] = {
                b[0]: b[1] for b in app.BINDINGS if b[1].startswith("select_")
            }
        self.assertEqual(touches["QEMU/KVM"], touches["Proxmox"])
        self.assertIn("select_main", touches["Proxmox"].values())

    def test_parallelism_follows_the_host_on_both_screens(self):
        # L'écran Proxmox plafonnait à quatre choix et en proposait UN, quel
        # que soit le nombre de cœurs de l'hôte.
        for nom, vu in (("QEMU/KVM", self.qemu), ("Proxmox", self.pve)):
            with self.subTest(ecran=nom):
                self.assertIn("f_par_all", vu["ids"], nom)


@unittest.skipUnless(TEXTUAL, "Textual absent")
class TestCeQueLeBureauChange(unittest.TestCase):
    """Choisir un bureau doit se voir sur les DEUX écrans, et de la même
    façon : le nom prend un suffixe, le disque grossit."""

    def _bureau(self):
        async def gestes(app, pilote):
            from textual.widgets import Checkbox

            list(app.query("#f_type RadioButton"))[1].value = True
            await pilote.pause()
            app.query_one("#f_tool_pycharm", Checkbox).value = True
            await pilote.pause()
            await pilote.pause()

        return gestes

    def test_the_name_gets_the_desktop_suffix(self):
        from script.todo.proxmox_deploy_form import run_proxmox_form

        todo = todo_muet()
        vu = releve(
            run_proxmox_form, contexte_proxmox(todo), gestes=self._bureau()
        )
        # Sans suffixe, une VM graphique et sa jumelle serveur portent le même
        # nom : la seconde est signalée « existe déjà » et ignorée.
        self.assertTrue(vu["noms"][0].endswith("-gnome"), vu["noms"])

    def test_the_disk_grows_by_the_desktop_and_the_tools(self):
        from script.todo.proxmox_deploy_form import run_proxmox_form

        todo = todo_muet()
        ctx = contexte_proxmox(todo)
        nu = releve(run_proxmox_form, ctx)
        avec = releve(run_proxmox_form, ctx, gestes=self._bureau())
        attendu = ctx["desktop_disk_gb"] + ctx["vm_tool_disk"]["pycharm"]
        self.assertEqual(
            avec["disques"][0] - nu["disques"][0],
            attendu,
            "le plan doit annoncer le surcoût AVANT de déployer",
        )

    def test_the_created_disk_matches_what_the_plan_announced(self):
        # C'est le pont entre l'écran et « qm resize » : le plan annonçait
        # 36 Go et la commande en demandait 20.
        todo = todo_muet()
        taille = todo._pve_disk_with_margin(
            {"disk": "20G", "arch": "amd64", "distro": "ubuntu"},
            {
                "install": {
                    "branch": "develop",
                    "cmd": "make install_os && make install_odoo_18",
                },
                "desktop": "gnome",
                "vm_tools": ("pycharm",),
            },
        )
        self.assertEqual(taille, "36G")


class TestCeQueSontCesVm(unittest.TestCase):
    """L'architecture d'une VM Proxmox venait de « virsh », qui ne connaît que
    les domaines d'ICI.

    Elle décide des outils : une VM ARM prise pour x86_64 recevait Android
    Studio, que Google ne publie pas pour elle — l'installation s'arrête, une
    heure plus tard. Même famille que le « s » qui partait vers la machine
    interne : on jugeait sur le nom."""

    def _outils(self, meta):
        vu = {}
        todo = TODO.__new__(TODO)
        todo._qemu_import_module = lambda: object()
        todo._qemu_resolve_ips = lambda noms: {n: "10.0.0.1" for n in noms}
        todo._qemu_vm_meta = lambda nom, mod: ("ubuntu", "26.04", "amd64")
        todo._qemu_erplibre_remote_cmd = lambda *a, **kw: ""

        def capture(vms, branche, remote):
            vu["archs"] = [v["arch"] for v in vms]
            raise SystemExit

        import script.todo.qemu_install_monitor as mon

        vrai = mon.launch_installs
        mon.launch_installs = capture
        try:
            todo._qemu_install_erplibre_monitored(
                ["vm-arm"], "develop", {"vm-arm": "10.0.0.1"}, meta=meta
            )
        except SystemExit:
            pass
        finally:
            mon.launch_installs = vrai
        return vu.get("archs")

    def test_the_caller_knows_better_than_virsh(self):
        self.assertEqual(
            self._outils({"vm-arm": ("ubuntu", "26.04", "arm64")}), ["arm64"]
        )

    def test_without_it_virsh_still_answers(self):
        # La voie libvirt ne régresse pas : ses domaines sont bien ici.
        self.assertEqual(self._outils(None), ["amd64"])


class TestLeFuseauDUneVmProxmox(unittest.TestCase):
    """« qm set » ne pose pas de fuseau : le cloud-init de Proxmox ne règle
    que l'utilisateur, la clé et le réseau. Une VM créée là restait en UTC, et
    on ne s'en aperçoit qu'aux horodatages."""

    def _pose(self, spec):
        vu = {}
        todo = TODO.__new__(TODO)
        todo._pve_ssh = lambda cible, cmd, **kw: (
            vu.setdefault("cmd", cmd),
            (0, ""),
        )[1]
        todo._pve_set_timezone("vm", spec)
        return vu.get("cmd", "")

    def test_the_timezone_reaches_the_vm(self):
        self.assertIn(
            "sudo timedatectl set-timezone America/Montreal",
            self._pose({"timezone": "America/Montreal"}),
        )

    def test_a_free_value_is_quoted(self):
        # La liste laisse la saisie libre : ce qui en sort part dans une
        # commande distante, donc il est cité.
        self.assertIn(
            "'a b; rm -rf /'", self._pose({"timezone": "a b; rm -rf /"})
        )

    def test_no_timezone_means_no_command(self):
        self.assertEqual(self._pose({}), "")

    def test_the_prompt_path_still_gets_one(self):
        # La voie par questions ne demande pas le fuseau ; sans défaut, elle
        # laissait la VM en UTC alors que la voie libvirt reprend celui de
        # l'hôte depuis toujours.
        import re
        from pathlib import Path

        src = Path("script/todo/proxmox_menu.py").read_text(encoding="utf-8")
        bloc = src[src.index("def _pve_deploy_prompts") :]
        bloc = bloc[: bloc.index("_pve_after_create")]
        self.assertTrue(
            re.search(r'"timezone":\s*self\._qemu_host_timezone\(\)', bloc),
            "le spec des invites doit porter un fuseau",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
