#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Recréation, depuis le suivi, d'une VM en échec ou effacée (touche n).

Ce que ces tests gardent :

- la spec de création de chaque VM est gardée à côté de son journal, en
  0600 — elle porte l'identité git —, et session.json n'en a que le chemin ;
- la spec gardée est réduite à cette VM, sans « existante » ;
- recréer REMPLACE l'entrée du même nom, à sa place, au lieu de la refuser
  comme un doublon ; l'ancien journal est mis de côté ;
- le suivi remet la ligne à zéro avec la nouvelle entrée (UUID compris) ;
- les refus : VM Proxmox, spec absente, installation en cours, effacement
  refusé.

_launch_one est remplacé : aucun processus n'est détaché, aucune VM créée.
"""

import json
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.path.insert(0, str(RACINE / "test"))

from async_case import AsyncCase  # noqa: E402

from script.todo import qemu_install_monitor as mon  # noqa: E402

SPEC = {
    "vms": [
        {
            "name": "vm-a",
            "distro": "debian",
            "version": "13",
            "arch": "amd64",
            "ram": 4096,
            "vcpus": 2,
            "disk": "40G",
        }
    ],
    "existing": [],
    "git_name": "Personne Fictive",
    "git_email": "personne@example.invalid",
    "add_ssh_config": True,
    "parallelism": 1,
}


def _sans_lancement(test):
    for cible, valeur in (
        ("_launch_one", lambda *a, **k: None),
        ("local_uuid", lambda nom: "uuid-neuf"),
    ):
        patch = mock.patch.object(mon, cible, valeur)
        patch.start()
        test.addCleanup(patch.stop)


class TestLaSpecEstGardee(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        _sans_lancement(self)
        patch = mock.patch.object(mon, "session_dir", lambda: self.base)
        patch.start()
        self.addCleanup(patch.stop)

    def lance(self, **extra):
        vm = {"name": "vm-a", "ip": "10.0.0.1", "spec": SPEC}
        return mon.launch_installs([vm], "develop", "true", **extra)

    def test_la_spec_est_ecrite_en_0600_hors_de_la_session(self):
        chemin = self.lance()
        entree = json.loads(Path(chemin).read_text())["vms"][0]
        fichier = Path(entree["spec_file"])
        self.assertEqual(SPEC, json.loads(fichier.read_text()))
        self.assertEqual(0o600, stat.S_IMODE(fichier.stat().st_mode))
        self.assertNotIn("example.invalid", Path(chemin).read_text())
        self.assertEqual(SPEC, mon.read_vm_spec(entree))

    def test_sans_spec_rien_n_est_lu(self):
        self.assertIsNone(mon.read_vm_spec({"name": "x"}))
        self.assertIsNone(mon.read_vm_spec({"spec_file": "/nulle/part"}))

    def test_recreer_remplace_l_entree_a_sa_place(self):
        chemin = mon.launch_installs(
            [
                {"name": "vm-z", "ip": "10.0.0.9"},
                {"name": "vm-a", "ip": "10.0.0.1", "spec": SPEC},
            ],
            "develop",
            "true",
        )
        avant = json.loads(Path(chemin).read_text())["vms"][1]
        Path(avant["log"]).write_text(f"essai\n{mon.EXIT_MARKER} 1\n")
        mon.launch_installs(
            [{"name": "vm-a", "ip": "10.0.0.7", "spec": SPEC}],
            "develop",
            "true",
            session=chemin,
            replace=True,
        )
        vms = json.loads(Path(chemin).read_text())["vms"]
        self.assertEqual(["vm-z", "vm-a"], [v["name"] for v in vms])
        apres = vms[1]
        self.assertEqual("10.0.0.7", apres["ip"])
        self.assertEqual(avant["log"], apres["log"])
        self.assertEqual([avant["log"] + ".1"], apres["previous_logs"])
        self.assertEqual(1, apres["recreations"])
        self.assertIn(
            f"{mon.EXIT_MARKER} 1", Path(avant["log"] + ".1").read_text()
        )
        self.assertEqual(("running", None), mon.read_status(apres["log"]))

    def test_sans_remplacement_le_doublon_reste_refuse(self):
        chemin = self.lance()
        with self.assertRaises(ValueError):
            mon.launch_installs(
                [{"name": "vm-a", "ip": "10.0.0.7"}],
                "develop",
                "true",
                session=chemin,
            )


class TestLaSpecReduiteAUneVm(unittest.TestCase):
    def test_une_vm_aucune_existante_sans_demande_de_recreation(self):
        sys.argv = ["todo.py"]
        from script.todo.todo import TODO

        parc = dict(
            SPEC,
            vms=[SPEC["vms"][0], dict(SPEC["vms"][0], name="vm-b")],
            existing=["vm-c"],
            recreate=True,
        )
        reduite = TODO._qemu_spec_vm(parc, parc["vms"][1])
        self.assertEqual(["vm-b"], [v["name"] for v in reduite["vms"]])
        self.assertEqual([], reduite["existing"])
        self.assertNotIn("recreate", reduite)
        self.assertEqual(SPEC["git_email"], reduite["git_email"])


class TestLeDeploiementTransmet(unittest.TestCase):
    """_qemu_install_erplibre_monitored : la spec de chaque VM et le mode
    remplacement arrivent à launch_installs ; les entrées rendues sont
    celles de CES VM, cherchées par nom."""

    def test_spec_remplacement_et_entrees_par_nom(self):
        sys.argv = ["todo.py"]
        from script.todo.todo import TODO

        recus = {}
        with tempfile.TemporaryDirectory() as coin:
            session = Path(coin, "session.json")
            session.write_text(
                json.dumps(
                    {
                        "vms": [
                            {"name": "vm-a", "ip": "ancienne"},
                            {"name": "vm-z", "ip": "10.0.0.9"},
                        ]
                    }
                )
            )

            def faux_launch(vms, branch, remote, **kw):
                recus.update(vms=vms, kw=kw)
                return str(session)

            todo = TODO.__new__(TODO)
            with mock.patch.object(mon, "launch_installs", faux_launch):
                rendues = todo._qemu_install_erplibre_monitored(
                    ["vm-a"],
                    "develop",
                    ip_map={"vm-a": "10.0.0.7"},
                    meta={"vm-a": ("debian", "13", "amd64")},
                    session=str(session),
                    specs={"vm-a": SPEC},
                    remplace=True,
                )
        self.assertEqual(SPEC, recus["vms"][0]["spec"])
        self.assertTrue(recus["kw"]["replace"])
        self.assertEqual(["vm-a"], [e["name"] for e in rendues])


class TestLaDemandeDeRecreationTraverseLeDeploiement(unittest.TestCase):
    """_qemu_deploie_spec_corps : « recreate » dans la spec devient le mode
    remplacement du suivi, et chaque VM y part avec sa spec réduite. Les
    étapes coûteuses (création, IP, ssh) sont remplacées."""

    def corps(self, spec):
        sys.argv = ["todo.py"]
        from script.todo.todo import TODO

        todo = TODO.__new__(TODO)
        recu = {}

        def suivi(noms, *a, **kw):
            recu.update(noms=noms, kw=kw)
            return []

        for nom, valeur in (
            ("_qemu_deploy_parts_for", lambda vm, spec, **k: ["true"]),
            (
                "_qemu_deploy_jobs_cli",
                self.travaux,
            ),
            (
                "_qemu_resolve_ips",
                lambda noms, labels=None: {"vm-a": "10.0.0.7"},
            ),
            ("_ssh_private_key", lambda cle: ""),
            ("_write_ssh_config_entry", lambda *a, **k: None),
            ("_qemu_install_erplibre_monitored", suivi),
        ):
            setattr(todo, nom, valeur)
        todo._qemu_deploie_spec_corps(spec, False, "/session.json")
        return recu

    def travaux(self, jobs, workers, stdin=None):
        """Les travaux réussis, et l'entrée qu'ils ont reçue."""
        self.entree = stdin
        return [(n, 0, "", 1.0) for _i, n, _p in jobs]

    def test_les_travaux_ne_lisent_pas_le_terminal_du_suivi(self):
        import subprocess

        self.corps(dict(SPEC))
        self.assertEqual(subprocess.DEVNULL, self.entree)

    def test_recreate_devient_remplacement(self):
        recu = self.corps(dict(SPEC, recreate=True))
        self.assertTrue(recu["kw"]["remplace"])
        self.assertEqual(["vm-a"], recu["noms"])
        self.assertNotIn("recreate", recu["kw"]["specs"]["vm-a"])

    def test_sans_demande_pas_de_remplacement(self):
        recu = self.corps(dict(SPEC))
        self.assertFalse(recu["kw"]["remplace"])


class FauxTodo:
    """Le TODO du menu, réduit à la création."""

    def __init__(self, res=None):
        self.res = res
        self.appels = []

    def _qemu_deploie_spec(self, spec, session=None):
        self.appels.append((spec, session))
        return self.res


class FauxTodoPve(FauxTodo):
    """Le même, avec la voie Proxmox : chaque appel note par où il passe."""

    def _qemu_deploie_spec(self, spec, session=None):
        self.appels.append(("qemu", spec, session))
        return self.res

    def _pve_deploie_spec(self, spec, session=None):
        self.appels.append(("pve", spec, session))
        return self.res

    def _qemu_import_module(self):
        return None

    def _pve_vm_commands(self, mod, vm, spec):
        # Une version que le catalogue ne connaît plus ne se bâtit pas.
        if vm.get("version") == "retiree":
            raise KeyError(vm["version"])
        return ["true"]


PVE = {
    "target": "erplibre@hote-essai",
    "sudo": "sudo ",
    "jump": "",
    "vmid": 101,
    "addr": "10.10.10.151",
}
SPEC_PVE = {
    "host": {"target": "erplibre@hote-essai", "sudo": "sudo "},
    "storage": "local-lvm",
    "bridge": "vmbr1",
    "gpu3d": False,
    "vms": [
        {
            "name": "vm-a",
            "distro": "debian",
            "version": "13",
            "arch": "amd64",
            "ram": 4096,
            "vcpus": 2,
            "disk": "40G",
            "vmid": 101,
            "ipconfig": "ip=10.10.10.151/24,gw=10.10.10.1",
        }
    ],
    "existing": [],
}


class TestLeSuivi(AsyncCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        for cible, valeur in (
            ("read_domstats", lambda: ""),
            ("arm_balloon", lambda names: None),
            ("virsh_domstates", lambda: {}),
            ("_port_open", lambda ip, port=8069, timeout=0.5: False),
            ("record_duration", lambda *a, **k: None),
            # Une VM Proxmox ne doit joindre aucun hôte réel.
            ("read_pvestats_detail", lambda vms: ({}, True)),
            ("read_pvestats", lambda vms: {}),
        ):
            patch = mock.patch.object(mon, cible, valeur)
            patch.start()
            self.addCleanup(patch.stop)

    def app(self, code=1, todo=None, spec=True, pve=None):
        log = self.base / "vm-a.log"
        fin = f"{mon.EXIT_MARKER} {code}\n" if code is not None else ""
        log.write_text(f"===> install\n{fin}")
        entree = {
            "name": "vm-a",
            "ip": "127.0.0.9",
            "arch": "amd64",
            "log": str(log),
            "ssh": "ssh erplibre@127.0.0.9",
            "disk": str(self.base / "vm-a.qcow2"),
            "uuid": "uuid-ancien",
        }
        if spec:
            fichier = self.base / "vm-a.spec.json"
            fichier.write_text(json.dumps(SPEC if spec is True else spec))
            entree["spec_file"] = str(fichier)
        if pve:
            entree["pve"] = pve
        manifeste = {
            "branch": "develop",
            "started": time.time() - 600,
            "vms": [entree],
        }
        chemin = self.base / "session.json"
        chemin.write_text(json.dumps(manifeste))
        self.chemin = str(chemin)
        return mon.run_monitor(str(chemin), run_app=False, todo=todo)

    async def ouvre(self, app, pilot):
        await pilot.pause()
        await app._tick_table()
        await pilot.pause()

    async def refus(self, app, pilot):
        await self.ouvre(app, pilot)
        with mock.patch.object(app, "notify") as notify:
            await pilot.press("n")
            await pilot.pause()
        self.assertNotEqual("ConfirmScreen", type(app.screen).__name__)
        return notify.call_args[0][0]

    async def test_n_efface_recree_et_remet_la_ligne_a_zero(self):
        from textual.widgets import DataTable

        neuve = {
            "name": "vm-a",
            "ip": "10.0.0.7",
            "log": str(self.base / "vm-a.log"),
            "uuid": "uuid-neuf",
            "started": time.time(),
        }
        todo = FauxTodo({"added": [neuve], "failed": [], "no_ip": []})
        app = self.app(todo=todo)
        async with app.run_test(size=(150, 30)) as pilot:
            await self.ouvre(app, pilot)
            with mock.patch.object(
                app, "_delete_for_recreate", return_value=True
            ):
                await pilot.press("n")
                await pilot.pause()
                self.assertEqual("ConfirmScreen", type(app.screen).__name__)
                await pilot.click("#c_yes")
                await app.workers.wait_for_complete()
                await pilot.pause()
            spec, session = todo.appels[0]
            self.assertTrue(spec["recreate"])
            self.assertEqual(self.chemin, session)
            self.assertEqual("vm-a", spec["vms"][0]["name"])
            self.assertNotIn("vm-a", app._final)
            self.assertEqual("uuid-neuf", app._vm_by_name("vm-a")["uuid"])
            self.assertEqual("10.0.0.7", app._vm_by_name("vm-a")["ip"])
            table = app.query_one("#vms", DataTable)
            self.assertEqual(1, table.row_count)

    async def test_sans_adresse_l_uuid_du_domaine_neuf_est_garde(self):
        """Création réussie, aucune IP : pas d'installation, mais l'entrée
        doit reconnaître le domaine neuf, sinon n, r et d le refusent pour
        toujours ; la marque de recréation part."""
        todo = FauxTodo({"added": [], "failed": [], "no_ip": ["vm-a"]})
        app = self.app(todo=todo)
        async with app.run_test(size=(150, 30)) as pilot:
            await self.ouvre(app, pilot)
            with mock.patch.object(
                app, "_delete_for_recreate", return_value=True
            ), mock.patch.object(mon, "local_uuid", lambda nom: "uuid-neuf"):
                await pilot.press("n")
                await pilot.pause()
                await pilot.click("#c_yes")
                await app.workers.wait_for_complete()
                await pilot.pause()
            self.assertEqual("uuid-neuf", app._vm_by_name("vm-a")["uuid"])
            entree = json.loads(Path(self.chemin).read_text())["vms"][0]
            self.assertEqual("uuid-neuf", entree["uuid"])
            self.assertNotIn("recreating", entree)

    async def test_une_reussite_recreee_ailleurs_est_adoptee(self):
        app = self.app(code=0, todo=FauxTodo())
        async with app.run_test(size=(150, 30)) as pilot:
            await self.ouvre(app, pilot)
            self.assertEqual("done", app._final["vm-a"][0])
            log = self.base / "vm-a.log"
            os.replace(log, str(log) + ".1")
            log.write_text("en-tête neuf\n")
            await app._tick_table()
            await pilot.pause()
            self.assertNotIn("vm-a", app._final)

    async def test_un_effacement_refuse_ne_recree_rien(self):
        todo = FauxTodo({"added": [], "failed": [], "no_ip": []})
        app = self.app(todo=todo)
        async with app.run_test(size=(150, 30)) as pilot:
            await self.ouvre(app, pilot)
            with mock.patch.object(
                app, "_delete_for_recreate", return_value=False
            ):
                await pilot.press("n")
                await pilot.pause()
                await pilot.click("#c_yes")
                await pilot.pause()
            self.assertEqual([], todo.appels)
            self.assertIn("vm-a", app._final)
            entree = json.loads(Path(self.chemin).read_text())["vms"][0]
            self.assertNotIn("recreating", entree)

    async def test_une_vm_effacee_se_recree_aussi(self):
        """Sa ligne quitte 🗑 et n'y retombe pas au tick suivant, avant que
        virsh ait revu le domaine."""
        neuve = {
            "name": "vm-a",
            "ip": "10.0.0.7",
            "log": str(self.base / "vm-a.log"),
            "uuid": "uuid-neuf",
        }
        todo = FauxTodo({"added": [neuve], "failed": [], "no_ip": []})
        app = self.app(code=None, todo=todo)
        async with app.run_test(size=(150, 30)) as pilot:
            await self.ouvre(app, pilot)
            app._domstate["vm-a"] = "gone"
            await app._tick_table()
            self.assertEqual("deleted", app._final["vm-a"][0])
            with mock.patch.object(
                app, "_delete_for_recreate", return_value=True
            ):
                await pilot.press("n")
                await pilot.pause()
                await pilot.click("#c_yes")
                await app.workers.wait_for_complete()
                await pilot.pause()
            await app._tick_table()
            self.assertNotIn("vm-a", app._final)

    async def test_une_installation_en_cours_est_refusee(self):
        app = self.app(code=None, todo=FauxTodo())
        async with app.run_test(size=(150, 30)) as pilot:
            msg = await self.refus(app, pilot)
            self.assertEqual(
                mon.t(
                    "Its install is still running: wait for it to end"
                    " before recreating the VM."
                ),
                msg,
            )

    async def test_sans_spec_gardee_la_recreation_est_refusee(self):
        app = self.app(todo=FauxTodo(), spec=False)
        async with app.run_test(size=(150, 30)) as pilot:
            msg = await self.refus(app, pilot)
            self.assertEqual(
                mon.t(
                    "This VM's creation parameters were not kept (older"
                    " session, or a VM only monitored). Deploy it again"
                    " from the menu."
                ),
                msg,
            )

    def parametres_differents(self):
        return mon.t(
            "The kept parameters do not match this VM (host or VMID): deploy"
            " it again from the menu."
        )

    async def test_une_vm_proxmox_avec_une_spec_qemu_est_refusee(self):
        app = self.app(todo=FauxTodoPve(), pve=dict(PVE))
        async with app.run_test(size=(150, 30)) as pilot:
            self.assertEqual(
                self.parametres_differents(), await self.refus(app, pilot)
            )

    async def test_un_autre_vmid_ou_un_autre_hote_est_refuse(self):
        for ecart in ({"vmid": 102}, {"target": "erplibre@autre"}):
            with self.subTest(ecart=ecart):
                app = self.app(
                    todo=FauxTodoPve(),
                    pve=dict(PVE, **ecart),
                    spec=SPEC_PVE,
                )
                async with app.run_test(size=(150, 30)) as pilot:
                    self.assertEqual(
                        self.parametres_differents(),
                        await self.refus(app, pilot),
                    )

    async def test_une_vm_locale_avec_une_spec_proxmox_est_refusee(self):
        app = self.app(todo=FauxTodoPve(), spec=SPEC_PVE)
        async with app.run_test(size=(150, 30)) as pilot:
            self.assertEqual(
                self.parametres_differents(), await self.refus(app, pilot)
            )

    async def test_sans_voie_proxmox_la_recreation_est_refusee(self):
        app = self.app(todo=FauxTodo(), pve=dict(PVE), spec=SPEC_PVE)
        async with app.run_test(size=(150, 30)) as pilot:
            self.assertEqual(
                mon.t("Recreating a VM is not available from this monitor."),
                await self.refus(app, pilot),
            )

    async def test_une_version_retiree_est_refusee_avant_toute_destruction(
        self,
    ):
        spec = json.loads(json.dumps(SPEC_PVE))
        spec["vms"][0]["version"] = "retiree"
        app = self.app(todo=FauxTodoPve(), pve=dict(PVE), spec=spec)
        async with app.run_test(size=(150, 30)) as pilot:
            self.assertEqual(
                mon.t(
                    "The kept parameters no longer build this VM (the"
                    " catalog changed): deploy it again from the menu."
                ),
                await self.refus(app, pilot),
            )

    async def test_n_recree_une_vm_proxmox_par_sa_voie(self):
        """La VM Proxmox passe par _pve_deploie_spec, jamais par la voie
        QEMU ; la ligne reprend avec la nouvelle entrée, adresse comprise."""
        neuve = {
            "name": "vm-a",
            "ip": "hote-essai+vm-a",
            "log": str(self.base / "vm-a.log"),
            "pve": dict(PVE, addr="10.10.10.152"),
            "started": time.time(),
        }
        todo = FauxTodoPve({"added": [neuve], "failed": [], "no_ip": []})
        app = self.app(todo=todo, pve=dict(PVE), spec=SPEC_PVE)
        async with app.run_test(size=(150, 30)) as pilot:
            await self.ouvre(app, pilot)
            app._pve_absences["vm-a"] = 2
            with mock.patch.object(
                app, "_delete_for_recreate", return_value=True
            ) as efface:
                await pilot.press("n")
                await pilot.pause()
                self.assertEqual("ConfirmScreen", type(app.screen).__name__)
                await pilot.click("#c_yes")
                await app.workers.wait_for_complete()
                await pilot.pause()
            self.assertEqual(
                SPEC_PVE["storage"], efface.call_args[0][1]["storage"]
            )
            voie, spec, session = todo.appels[0]
            self.assertEqual("pve", voie)
            self.assertTrue(spec["recreate"])
            self.assertEqual(self.chemin, session)
            self.assertNotIn("vm-a", app._final)
            self.assertNotIn("vm-a", app._pve_absences)
            self.assertEqual(0.0, mon._PVE_CACHE["at"])
            self.assertEqual(
                "10.10.10.152", app._vm_by_name("vm-a")["pve"]["addr"]
            )

    async def test_une_recreation_proxmox_sans_installation_ne_lit_aucun_uuid(
        self,
    ):
        app = self.app(todo=FauxTodoPve(), pve=dict(PVE), spec=SPEC_PVE)
        async with app.run_test(size=(150, 30)) as pilot:
            await self.ouvre(app, pilot)
            spec = dict(SPEC_PVE, recreate=True)
            with mock.patch.object(
                mon, "local_uuid", side_effect=AssertionError("uuid lu")
            ), mock.patch.object(mon, "release_recreate") as libere:
                res = app._settle_recreation(
                    spec, {"added": [], "failed": ["vm-a"], "no_ip": []}
                )
            libere.assert_called_once_with(self.chemin, "vm-a")
            self.assertNotIn("recreated_uuid", res)

    async def test_sans_todo_la_recreation_est_refusee(self):
        app = self.app(todo=None)
        async with app.run_test(size=(150, 30)) as pilot:
            msg = await self.refus(app, pilot)
            self.assertEqual(
                mon.t("Recreating a VM is not available from this monitor."),
                msg,
            )

    async def test_une_recreation_faite_ailleurs_est_adoptee(self):
        """Ligne effacée ici, journal remplacé par un autre suivi."""
        app = self.app(code=None, todo=FauxTodo())
        async with app.run_test(size=(150, 30)) as pilot:
            await self.ouvre(app, pilot)
            app._domstate["vm-a"] = "gone"
            await app._tick_table()
            self.assertEqual("deleted", app._final["vm-a"][0])
            log = self.base / "vm-a.log"
            os.replace(log, str(log) + ".1")
            log.write_text("en-tête neuf\n")
            app._domstate.pop("vm-a")
            await app._tick_table()
            await pilot.pause()
            self.assertNotIn("vm-a", app._final)


class TestLaCommandeDEffacement(unittest.TestCase):
    """recreate_delete_cmd exécutée sous bash, virsh et sudo remplacés.

    FAUX_DOMAINES : domaines que « list » connaît ; FAUX_UUID : ce que rend
    « domuuid » ; FAUX_LIST_RC : code de « list » (virsh illisible) ;
    FAUX_UNDEFINE_RC : code de « undefine »."""

    VIRSH = """#!/bin/bash
echo "virsh $*" >> "$FAUX_JOURNAL"
case " $* " in
  *" list "*) [ "${FAUX_LIST_RC:-0}" = 0 ] || exit "$FAUX_LIST_RC"
    for d in $FAUX_DOMAINES; do echo "$d"; done ;;
  *" domuuid "*) echo "$FAUX_UUID" ;;
  *" undefine "*) exit "${FAUX_UNDEFINE_RC:-0}" ;;
esac
exit 0
"""
    SUDO = """#!/bin/bash
echo "sudo $*" >> "$FAUX_JOURNAL"
[ "$1" = rm ] && exit 0
exec "$@"
"""

    def lance(self, uuid="uuid-ancien", **env_faux):
        coin = tempfile.TemporaryDirectory()
        self.addCleanup(coin.cleanup)
        for nom, corps in (("virsh", self.VIRSH), ("sudo", self.SUDO)):
            f = Path(coin.name, nom)
            f.write_text(corps)
            f.chmod(0o755)
        journal = Path(coin.name, "journal")
        env = {
            "PATH": f"{coin.name}:/usr/bin:/bin",
            "FAUX_JOURNAL": str(journal),
            "FAUX_DOMAINES": "",
            "FAUX_UUID": "",
        }
        env.update({k: str(v) for k, v in env_faux.items()})
        with mock.patch.object(mon, "sudo_prefix", lambda: ""):
            cmd = mon.recreate_delete_cmd("vm-a", uuid)
        import subprocess

        res = subprocess.run(
            ["bash", "-c", cmd], env=env, capture_output=True, text=True
        )
        appels = journal.read_text().splitlines() if journal.exists() else []
        return res, appels

    def efface(self, appels):
        return [a for a in appels if " destroy " in a or " undefine " in a]

    def rm(self, appels):
        return [a for a in appels if a.startswith("sudo rm")]

    def test_le_domaine_de_la_session_est_efface(self):
        res, appels = self.lance(FAUX_DOMAINES="vm-a", FAUX_UUID="uuid-ancien")
        self.assertEqual(0, res.returncode, res.stdout)
        self.assertTrue(self.efface(appels))
        self.assertTrue(self.rm(appels))

    def test_un_nom_repris_par_une_autre_vm_est_refuse(self):
        res, appels = self.lance(FAUX_DOMAINES="vm-a", FAUX_UUID="uuid-autre")
        self.assertEqual(1, res.returncode)
        self.assertEqual([], self.efface(appels))
        self.assertEqual([], self.rm(appels))

    def test_sans_uuid_connu_un_domaine_present_est_refuse(self):
        res, appels = self.lance(uuid="", FAUX_DOMAINES="vm-a")
        self.assertEqual(1, res.returncode)
        self.assertEqual([], self.efface(appels))
        self.assertEqual([], self.rm(appels))

    def test_un_virsh_illisible_refuse_tout(self):
        """Ni « absent » ni « présent » : rien n'est effacé, pas même les
        fichiers."""
        res, appels = self.lance(FAUX_LIST_RC=1, FAUX_DOMAINES="vm-a")
        self.assertEqual(1, res.returncode)
        self.assertEqual([], self.efface(appels))
        self.assertEqual([], self.rm(appels))

    def test_un_domaine_absent_ne_laisse_que_ses_fichiers(self):
        res, appels = self.lance(FAUX_DOMAINES="vm-autre")
        self.assertEqual(0, res.returncode, res.stdout)
        self.assertEqual([], self.efface(appels))
        self.assertTrue(self.rm(appels))

    def test_un_nom_voisin_n_est_pas_le_domaine(self):
        res, appels = self.lance(FAUX_DOMAINES="vm-ab vm-a-2")
        self.assertEqual(0, res.returncode)
        self.assertEqual([], self.efface(appels))

    def test_un_undefine_en_echec_garde_le_disque(self):
        res, appels = self.lance(
            FAUX_DOMAINES="vm-a", FAUX_UUID="uuid-ancien", FAUX_UNDEFINE_RC=1
        )
        self.assertEqual(1, res.returncode)
        self.assertEqual([], self.rm(appels))


FAUX_QM = """#!/bin/sh
echo "qm $*" >> "$JOURNAL"
case "$1" in
  list) [ "$QM_LIST" = echec ] && exit 2
        echo "VMID NAME STATUS"
        [ -n "$PRESENT" ] && echo "$PRESENT $NOM running"
        exit 0 ;;
  config) echo "name: $NOM" ;;
  destroy) exit ${RC_DESTROY:-0} ;;
esac
exit 0
"""


class TestLaCommandeDEffacementPve(unittest.TestCase):
    """recreate_delete_suite_pve, jouée sous bash avec de faux qm, pvesm, ip
    et ls : rien n'est détruit tant que tout n'a pas été vérifié."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.journal = self.base / "journal"
        for nom, texte in (
            ("qm", FAUX_QM),
            ("pvesm", '#!/bin/sh\n[ "$STOCKAGE" = ok ]\n'),
            ("ip", '#!/bin/sh\n[ "$PONT" = ok ]\n'),
            ("ls", '#!/bin/sh\n[ "$RENDU" = ok ]\n'),
        ):
            (self.bin / nom).write_text(texte)
            (self.bin / nom).chmod(0o755)

    def lance(self, gpu3d=False, **env_vm):
        # Le PATH ci-dessous perd la doublure du lanceur : ce faux sudo
        # refuse. La suite tourne déjà sous le sudo de pve_host_cmd, elle
        # n'en appelle aucun.
        (self.bin / "sudo").write_text("#!/bin/sh\nexit 1\n")
        (self.bin / "sudo").chmod(0o755)
        self.journal.write_text("")
        env = dict(
            os.environ,
            PATH=f"{self.bin}:/usr/bin:/bin",
            JOURNAL=str(self.journal),
            NOM="vm-a",
            PRESENT="101",
            STOCKAGE="ok",
            PONT="ok",
            RENDU="ok",
        )
        env.update(env_vm)
        cmd = mon.recreate_delete_suite_pve(
            101, "vm-a", "local-lvm", "vmbr1", gpu3d
        )
        fin = subprocess.run(
            ["bash", "-c", cmd], env=env, capture_output=True, text=True
        )
        return fin.returncode, self.journal.read_text(), fin.stdout

    def test_the_same_vm_is_stopped_then_destroyed(self):
        rc, journal, _ = self.lance()
        self.assertEqual(0, rc)
        self.assertIn("qm stop 101 --skiplock 1", journal)
        self.assertIn(
            "qm destroy 101 --purge 1 --destroy-unreferenced-disks 1", journal
        )

    def test_a_vmid_carrying_another_name_is_refused(self):
        rc, journal, sortie = self.lance(NOM="autre")
        self.assertEqual(1, rc)
        self.assertNotIn("destroy", journal)
        self.assertIn("REFUS", sortie)

    def test_an_absent_vmid_destroys_nothing_and_passes(self):
        rc, journal, _ = self.lance(PRESENT="")
        self.assertEqual(0, rc)
        self.assertNotIn("destroy", journal)

    def test_an_unreadable_qm_refuses(self):
        rc, journal, sortie = self.lance(QM_LIST="echec")
        self.assertEqual(1, rc)
        self.assertNotIn("destroy", journal)
        self.assertIn("REFUS", sortie)

    def test_a_failed_destroy_fails(self):
        self.assertEqual(1, self.lance(RC_DESTROY="1")[0])

    def test_what_the_recreation_needs_is_checked_first(self):
        for manque in ({"STOCKAGE": ""}, {"PONT": ""}, {"RENDU": ""}):
            with self.subTest(manque=manque):
                rc, journal, sortie = self.lance(gpu3d=True, **manque)
                self.assertEqual(1, rc)
                # Refusé avant la moindre question à qm.
                self.assertEqual("", journal)
                self.assertIn("REFUS", sortie)


class TestLAncienLanceurEstArrete(unittest.TestCase):
    def test_le_lanceur_qui_ecrit_dans_le_journal_s_arrete(self):
        import subprocess

        with tempfile.TemporaryDirectory() as coin:
            log = str(Path(coin, "vm-a.log"))
            # La ligne de commande porte le journal et le marqueur, comme
            # celle du vrai lanceur ; « ; true » garde bash vivant.
            subprocess.run(
                [
                    "setsid",
                    "-f",
                    "bash",
                    "-c",
                    f"sleep 60; true # {log} {mon.EXIT_MARKER}",
                ],
                check=True,
            )
            time.sleep(0.3)
            self.assertEqual(1, mon.stop_launchers(log))
            time.sleep(0.3)
            self.assertEqual(0, mon.stop_launchers(log))

    def test_un_autre_journal_n_est_pas_touche(self):
        self.assertEqual(0, mon.stop_launchers("/nulle/part/inexistant.log"))


class TestLaMarqueDeRecreation(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        log = self.base / "vm-a.log"
        log.write_text(f"x\n{mon.EXIT_MARKER} 1\n")
        self.session = str(self.base / "session.json")
        Path(self.session).write_text(
            json.dumps(
                {
                    "branch": "d",
                    "vms": [
                        {
                            "name": "vm-a",
                            "ip": "10.0.0.1",
                            "log": str(log),
                            "uuid": "uuid-ancien",
                            "remote_cmd": "true",
                        }
                    ],
                }
            )
        )

    def entree(self):
        return json.loads(Path(self.session).read_text())["vms"][0]

    def test_un_second_suivi_est_refuse(self):
        mon.claim_recreate(self.session, "vm-a")
        with self.assertRaises(mon.RelaunchRefused):
            mon.claim_recreate(self.session, "vm-a")

    def test_la_marque_d_un_suivi_mort_ne_bloque_pas(self):
        entree = self.entree()
        entree["recreating"] = {"pid": 2**22 + 12345, "since": 0}
        Path(self.session).write_text(
            json.dumps({"branch": "d", "vms": [entree]})
        )
        mon.claim_recreate(self.session, "vm-a")
        self.assertEqual(os.getpid(), self.entree()["recreating"]["pid"])

    def test_une_relance_est_refusee_pendant_la_recreation(self):
        # Le même domaine : seule la marque peut refuser.
        mon.claim_recreate(self.session, "vm-a")
        with mock.patch.object(
            mon, "_launch_one", lambda *a, **k: None
        ), mock.patch.object(mon, "local_uuid", lambda nom: "uuid-ancien"):
            with self.assertRaises(mon.RelaunchRefused) as refus:
                mon.relaunch_install(self.session, "vm-a")
            self.assertEqual(
                mon.t("A recreation of this VM is already under way."),
                str(refus.exception),
            )
            mon.release_recreate(self.session, "vm-a")
            mon.relaunch_install(self.session, "vm-a")

    def test_le_retrait_pose_l_uuid_du_domaine_neuf(self):
        mon.claim_recreate(self.session, "vm-a")
        mon.release_recreate(self.session, "vm-a", uuid="uuid-neuf")
        self.assertNotIn("recreating", self.entree())
        self.assertEqual("uuid-neuf", self.entree()["uuid"])


class TestLEffacementAvantRecreation(AsyncCase):
    """_delete_for_recreate, terminal « rendu » par une doublure."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        for cible, valeur in (
            ("read_domstats", lambda: ""),
            ("arm_balloon", lambda names: None),
            ("virsh_domstates", lambda: {}),
            ("_port_open", lambda ip, port=8069, timeout=0.5: False),
            ("stop_launchers", lambda log: 0),
            # Le relevé d'adresse de fond passe par « sudo virsh » : sous
            # charge, il tombait dans les commandes comptées ici.
            ("virsh_ip", lambda nom: ""),
        ):
            patch = mock.patch.object(mon, cible, valeur)
            patch.start()
            self.addCleanup(patch.stop)
        log = self.base / "vm-a.log"
        log.write_text(f"x\n{mon.EXIT_MARKER} 1\n")
        self.vm = {
            "name": "vm-a",
            "ip": "127.0.0.9",
            "log": str(log),
            "ssh": "ssh erplibre@127.0.0.9",
            "uuid": "uuid-ancien",
        }
        chemin = self.base / "session.json"
        chemin.write_text(
            json.dumps(
                {"branch": "d", "started": time.time(), "vms": [self.vm]}
            )
        )
        self.chemin = str(chemin)

    async def efface(self, rc_sudo=0, rc_bash=0, vm=None, spec=None):
        class Todo:
            execute = None

        menages = []

        app = mon.run_monitor(self.chemin, run_app=False, todo=Todo())
        commandes = []

        def run(argv, **kw):
            commandes.append(argv)
            rc = {"sudo": rc_sudo, "bash": rc_bash}.get(argv[0], 0)
            # Les tâches de fond du suivi passent aussi par ici : une sortie
            # vide, qu'elles savent lire.
            return mock.Mock(returncode=rc, stdout="", stderr="")

        async with app.run_test(size=(150, 30)):
            with mock.patch.object(
                app, "suspend", mock.MagicMock()
            ), mock.patch.object(
                mon.subprocess, "run", run
            ), mock.patch.object(
                mon.os, "geteuid", lambda: 1000
            ), mock.patch(
                "builtins.input", lambda *a: ""
            ), mock.patch(
                "script.todo.qemu_cache_menu.bypass_menage",
                lambda e: menages.append(e) or 0,
            ):
                ok = app._delete_for_recreate(vm or self.vm, spec)
        self.menages = menages
        return ok, [
            c for c in commandes if c[0] == "bash" or c[:2] == ["sudo", "-v"]
        ]

    async def test_l_effacement_porte_l_uuid_de_la_session(self):
        ok, cmds = await self.efface()
        self.assertTrue(ok)
        self.assertEqual(["sudo", "-v"], cmds[0])
        self.assertIn("uuid-ancien", cmds[1][2])

    async def test_une_vm_proxmox_est_effacee_sur_son_hote(self):
        vm = dict(self.vm, pve=dict(PVE))
        with mock.patch.object(
            mon, "read_pvestats_detail", lambda vms: ({}, True)
        ), mock.patch.object(mon, "read_pvestats", lambda vms: {}):
            ok, cmds = await self.efface(vm=vm, spec=SPEC_PVE)
        self.assertTrue(ok)
        commande = cmds[1][2]
        self.assertIn("erplibre@hote-essai", commande)
        self.assertIn("qm destroy 101", commande)
        self.assertIn("vmbr1", commande)
        self.assertNotIn("virsh", commande)
        # Rien n'a bougé ici : pas de ménage local.
        self.assertEqual([], self.menages)

    async def test_sans_sudo_local_une_vm_proxmox_s_efface_quand_meme(self):
        """L'effacement se fait sur l'hôte : le sudo local n'y est pour rien,
        et son refus ne doit pas bloquer la recréation."""
        vm = dict(self.vm, pve=dict(PVE))
        with mock.patch.object(
            mon, "read_pvestats_detail", lambda vms: ({}, True)
        ), mock.patch.object(mon, "read_pvestats", lambda vms: {}):
            ok, cmds = await self.efface(rc_sudo=1, vm=vm, spec=SPEC_PVE)
        self.assertTrue(ok)
        self.assertIn("qm destroy 101", cmds[1][2])

    async def test_un_ticket_sudo_refuse_n_efface_rien(self):
        ok, cmds = await self.efface(rc_sudo=1)
        self.assertFalse(ok)
        self.assertEqual([["sudo", "-v"]], cmds)

    async def test_un_refus_de_la_commande_arrete_la_recreation(self):
        ok, _ = await self.efface(rc_bash=1)
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
