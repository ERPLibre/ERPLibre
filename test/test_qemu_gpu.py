#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""GPU de l'hôte : détection, déploiement, et réglage d'une VM éteinte.

Une VM graphique sans accélération rend tout par le processeur — le bureau
comme l'émulateur Android qui tourne dedans. L'hôte a un GPU ou non ; s'il en
a un, la VM doit le prendre, et c'est le défaut.

Ce que ces tests gardent, appris en le cassant :

- UN SEUL « --video » : la 3D remplace le « --video virtio », elle ne s'y
  ajoute pas — deux écrans, et l'invité n'en peuple qu'un.
- « --add-device --graphics egl-headless » n'est PAS idempotent : deux appels,
  deux affichages. D'où l'état lu avant tout plan.
- « virt-xml --memory N » ne touche que <currentMemory> : la RAM plafonnait en
  silence à l'ancien maximum.
- Le retrait de la 3D cible le TYPE egl-headless : sans ce ciblage, c'est la
  console VNC de la VM qui disparaît.
- « --define » sur chaque commande : sans lui, virt-xml POSE UNE QUESTION et
  le menu se bloque sans rien dire.
"""

import contextlib
import importlib.util
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.argv = ["todo.py"]
from script.todo import qemu_hardware as hw  # noqa: E402
from script.todo.todo import TODO  # noqa: E402


def _deploy_qemu():
    """deploy_qemu.py chargé comme module, comme le fait todo.py."""
    path = Path(__file__).resolve().parents[1] / "script/qemu/deploy_qemu.py"
    spec = importlib.util.spec_from_file_location("deploy_qemu", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


DQ = _deploy_qemu()

# XML réel d'une VM du parc, réduit à ce qui décide du matériel.
XML_SANS_3D = """<domain type='kvm'>
  <name>erplibre-ubuntu-2604-gnome</name>
  <memory unit='KiB'>33554432</memory>
  <currentMemory unit='KiB'>33554432</currentMemory>
  <vcpu placement='static'>8</vcpu>
  <devices>
    <graphics type='vnc' port='5900' autoport='yes' listen='127.0.0.1'>
      <listen type='address' address='127.0.0.1'/>
    </graphics>
    <video>
      <model type='virtio' heads='1' primary='yes'/>
    </video>
  </devices>
</domain>
"""

XML_AVEC_3D = XML_SANS_3D.replace(
    "<model type='virtio' heads='1' primary='yes'/>",
    "<model type='virtio' heads='1' primary='yes'>"
    "<acceleration accel3d='yes'/></model>",
).replace(
    "</video>",
    "</video>\n    <graphics type='egl-headless'>"
    "<gl rendernode='/dev/dri/renderD128'/></graphics>",
)

# XML persistant complet : mode CPU, écrans, interface réseau. C'est cette
# forme-là que « virsh dumpxml --inactive » rend, sans les décorations que
# libvirt ajoute au démarrage (portid, vnetN, alias).
XML_COMPLET = """<domain type='kvm'>
  <name>erplibre-ubuntu-2604-gnome</name>
  <memory unit='KiB'>33554432</memory>
  <currentMemory unit='KiB'>33554432</currentMemory>
  <vcpu placement='static'>8</vcpu>
  <cpu mode='host-passthrough' check='none' migratable='on'/>
  <devices>
    <interface type='network'>
      <mac address='52:54:00:fc:a1:34'/>
      <source network='default'/>
      <model type='virtio'/>
    </interface>
    <graphics type='vnc' port='-1' autoport='yes' listen='127.0.0.1'/>
    <video>
      <model type='virtio' heads='1' primary='yes'/>
    </video>
  </devices>
</domain>
"""

XML_SERVEUR = """<domain type='kvm'>
  <name>erplibre-serveur</name>
  <memory unit='KiB'>2097152</memory>
  <vcpu placement='static'>2</vcpu>
  <devices/>
</domain>
"""

NODE = "/dev/dri/renderD128"


class TestDetection(unittest.TestCase):
    """Le GPU se lit dans /dev/dri, pas dans une liste de cartes connues."""

    def _dri(self, *names):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for n in names:
            Path(tmp.name, n).touch()
        return tmp.name

    def test_it_keeps_render_nodes_and_ignores_the_rest(self):
        """« card0 » est le nœud d'affichage, pas de rendu : QEMU ouvre
        renderD*, et lui donner card0 échouerait au démarrage."""
        found = DQ.host_render_nodes(
            self._dri("card0", "renderD128", "by-path")
        )
        self.assertEqual(1, len(found))
        self.assertTrue(found[0].endswith("renderD128"))

    def test_several_cards_come_out_sorted(self):
        found = DQ.host_render_nodes(self._dri("renderD129", "renderD128"))
        self.assertEqual(
            ["renderD128", "renderD129"], [Path(f).name for f in found]
        )

    def test_a_host_without_dri_answers_empty(self):
        """Cet hyperviseur-ci est lui-même une VM sans GPU : /dev/dri n'existe
        pas du tout. Une exception ici ferait échouer TOUT déploiement."""
        self.assertEqual([], DQ.host_render_nodes("/nexistepas/dri"))
        self.assertEqual("", DQ.host_gpu_node("/nexistepas/dri"))

    def test_presence_is_the_test_not_our_own_access(self):
        """Le nœud appartient au groupe « render » ; libvirt donne l'accès au
        démarrage du domaine. Tester nos droits rejetterait un hôte valable."""
        d = self._dri("renderD128")
        os.chmod(Path(d, "renderD128"), 0o000)
        self.assertTrue(DQ.host_gpu_node(d).endswith("renderD128"))


class TestDecision(unittest.TestCase):
    """« Par défaut avec GPU s'il existe » — et le silence n'est pas permis."""

    def test_auto_takes_the_gpu_when_there_is_one(self):
        on, msg = DQ.gpu_decision("auto", NODE, True)
        self.assertTrue(on)
        self.assertIn(NODE, msg)

    def test_auto_without_gpu_says_why_it_falls_back(self):
        """Sans ce message, une VM en rendu logiciel ne s'explique pas — et on
        cherche la lenteur ailleurs pendant des heures."""
        on, msg = DQ.gpu_decision("auto", "", True)
        self.assertFalse(on)
        self.assertTrue(msg.strip())

    def test_forcing_it_without_a_node_refuses_and_warns(self):
        """libvirt refuse de démarrer un domaine dont le rendernode manque :
        obéir aveuglément à « --gpu on » livrerait une VM qui ne démarre pas.
        """
        on, msg = DQ.gpu_decision("on", "", True)
        self.assertFalse(on)
        self.assertIn("⚠", msg)

    def test_off_stays_off_and_silent(self):
        self.assertEqual((False, ""), DQ.gpu_decision("off", NODE, True))

    def test_no_screen_no_3d(self):
        """Une VM serveur n'a pas d'écran : la 3D n'y accélérerait rien, et le
        « --edit --video » échouerait faute de périphérique vidéo."""
        on, _ = DQ.gpu_decision("auto", NODE, False)
        self.assertFalse(on)


class TestDeployArgs(unittest.TestCase):
    def test_the_args_carry_both_halves(self):
        """L'accélération sur le virtio-gpu ET un affichage capable de
        contexte GL : l'une sans l'autre ne donne aucune 3D."""
        args = DQ.gpu_install_args(NODE)
        self.assertIn("model.acceleration.accel3d=on", " ".join(args))
        self.assertIn(f"gl.rendernode={NODE}", " ".join(args))

    def test_only_one_video_device_survives(self):
        """Le bug qui donne deux écrans : garder « --video virtio » à côté du
        « --video » de la 3D. L'invité n'en peuple alors qu'un."""
        video, gpu_args, _ = DQ.gpu_apply(
            ["--video", "virtio"], "auto", NODE, True
        )
        self.assertEqual([], video)
        self.assertEqual(1, (video + gpu_args).count("--video"))

    def test_without_gpu_the_plain_video_stays(self):
        video, gpu_args, _ = DQ.gpu_apply(
            ["--video", "virtio"], "auto", "", True
        )
        self.assertEqual(["--video", "virtio"], video)
        self.assertEqual([], gpu_args)

    def test_the_egl_display_is_added_beside_vnc_not_instead(self):
        """« egl-headless » n'ouvre aucun port : il ne remplace pas la console
        VNC, il porte le contexte OpenGL. Les deux cohabitent."""
        args = DQ.gpu_install_args(NODE)
        self.assertIn("type=egl-headless", " ".join(args))
        self.assertNotIn("vnc", " ".join(args))


class TestReadState(unittest.TestCase):
    def test_it_reads_what_the_vm_has(self):
        st = hw.hw_state(XML_SANS_3D)
        self.assertEqual("erplibre-ubuntu-2604-gnome", st["name"])
        self.assertEqual(8, st["vcpus"])
        self.assertEqual(32768, st["mem_mib"])
        self.assertEqual("virtio", st["video"])
        self.assertFalse(st["accel3d"])
        self.assertTrue(st["screen"])

    def test_it_sees_an_existing_3d_setup(self):
        st = hw.hw_state(XML_AVEC_3D)
        self.assertTrue(st["accel3d"])
        self.assertTrue(st["egl"])
        self.assertEqual(NODE, st["render"])

    def test_egl_headless_alone_is_not_a_screen(self):
        """Il n'affiche rien et n'ouvre aucun port. Le compter comme écran
        proposerait la 3D à une VM qui n'a rien à accélérer."""
        xml = XML_SERVEUR.replace(
            "<devices/>",
            "<devices><graphics type='egl-headless'/></devices>",
        )
        self.assertFalse(hw.hw_state(xml)["screen"])

    def test_the_balloon_target_is_what_the_vm_gets(self):
        """<memory> est le maximum, <currentMemory> ce que la VM voit. Lire le
        premier annoncerait 32 Go à une VM qui en a 4."""
        xml = XML_SANS_3D.replace(
            "<currentMemory unit='KiB'>33554432</currentMemory>",
            "<currentMemory unit='KiB'>4194304</currentMemory>",
        )
        self.assertEqual(4096, hw.hw_state(xml)["mem_mib"])

    def test_units_are_exact(self):
        """KB vaut mille octets, KiB en vaut 1024 : le schéma libvirt autorise
        les deux, et « à peu près » se voit dans le tableau."""
        for unit, value, mib in (
            ("KiB", 1048576, 1024),
            ("MiB", 2048, 2048),
            ("GiB", 4, 4096),
            ("bytes", 1073741824, 1024),
        ):
            xml = XML_SERVEUR.replace(
                "<memory unit='KiB'>2097152</memory>",
                f"<memory unit='{unit}'>{value}</memory>",
            )
            self.assertEqual(mib, hw.hw_state(xml)["mem_mib"], unit)

    def test_broken_xml_gives_an_empty_state(self):
        st = hw.hw_state("<domain")
        self.assertEqual("", st["name"])
        self.assertEqual(0, st["vcpus"])

    def test_autostart_comes_from_outside_the_xml(self):
        """Il vit dans un lien symbolique de libvirt, pas dans la définition."""
        self.assertTrue(hw.hw_state(XML_SANS_3D, autostart=True)["autostart"])


class TestPlan(unittest.TestCase):
    def _plan(self, xml, want, node=NODE, autostart=False):
        return hw.hw_plan(hw.hw_state(xml, autostart), want, node)

    def test_nothing_wanted_nothing_planned(self):
        self.assertEqual([], self._plan(XML_SANS_3D, {}))

    def test_the_same_values_change_nothing(self):
        """Revalider le formulaire sans rien toucher ne doit RIEN lancer."""
        plan = self._plan(
            XML_SANS_3D, {"vcpus": 8, "ram": 32768, "gpu": False}
        )
        self.assertEqual([], plan)

    def test_3d_already_on_the_same_node_is_not_added_twice(self):
        """« --add-device --graphics egl-headless » deux fois pose DEUX
        affichages : c'est l'état lu qui l'empêche, pas virt-xml."""
        self.assertEqual([], self._plan(XML_AVEC_3D, {"gpu": True}))

    def test_another_node_is_edited_in_place(self):
        plan = self._plan(
            XML_AVEC_3D, {"gpu": True}, node="/dev/dri/renderD129"
        )
        joined = [" ".join(e["cmd"]) for e in plan]
        self.assertEqual(1, len(plan))
        self.assertIn("--edit type=egl-headless", joined[0])
        self.assertNotIn("--add-device", joined[0])

    def test_turning_3d_on_carries_both_halves(self):
        plan = self._plan(XML_SANS_3D, {"gpu": True})
        joined = " ".join(" ".join(e["cmd"]) for e in plan)
        self.assertIn("model.acceleration.accel3d=on", joined)
        self.assertIn(f"gl.rendernode={NODE}", joined)

    def test_turning_3d_off_targets_the_type_so_vnc_survives(self):
        """Un « --remove-device --graphics » sans cible emporterait la console
        VNC : plus aucun accès à l'écran de la VM."""
        plan = self._plan(XML_AVEC_3D, {"gpu": False})
        removals = [e for e in plan if "--remove-device" in e["cmd"]]
        self.assertEqual(1, len(removals))
        self.assertIn("type=egl-headless", removals[0]["cmd"])

    def test_ram_sets_the_maximum_too(self):
        """« --memory N » seul ne touche que <currentMemory> : la VM plafonne
        à son ancien maximum, sans un mot."""
        plan = self._plan(XML_SANS_3D, {"ram": 65536})
        arg = [c for c in plan[0]["cmd"] if c.startswith("memory=")][0]
        self.assertIn("memory=65536", arg)
        self.assertIn("currentMemory=65536", arg)

    def test_3d_without_a_host_node_is_refused_with_a_reason(self):
        plan = hw.hw_plan(hw.hw_state(XML_SANS_3D), {"gpu": True}, "")
        self.assertEqual(1, len(plan))
        self.assertNotIn("cmd", plan[0])
        self.assertTrue(plan[0]["skip"])

    def test_3d_on_a_screenless_vm_is_refused(self):
        """« --edit --video » échouerait : il n'y a pas de périphérique vidéo
        à modifier. Mieux vaut le dire que laisser virt-xml protester."""
        plan = self._plan(XML_SERVEUR, {"gpu": True})
        self.assertEqual(1, len(plan))
        self.assertIn("skip", plan[0])

    def test_autostart_only_moves_when_it_differs(self):
        self.assertEqual(
            [], self._plan(XML_SANS_3D, {"autostart": True}, autostart=True)
        )
        plan = self._plan(XML_SANS_3D, {"autostart": False}, autostart=True)
        self.assertIn("--disable", plan[0]["cmd"])

    def test_every_command_defines_and_names_its_uri(self):
        """Sans « --define », virt-xml INTERROGE l'utilisateur quand le domaine
        tourne : le menu se bloque sur une question qu'on ne voit pas. Sans
        « --connect », un appel non root viserait qemu:///session, où les VM du
        parc n'existent pas."""
        plan = self._plan(XML_SANS_3D, {"vcpus": 4, "ram": 8192, "gpu": True})
        self.assertTrue(plan)
        for entry in plan:
            self.assertIn("--define", entry["cmd"])
            self.assertIn("qemu:///system", entry["cmd"])

    def test_a_state_without_a_name_plans_nothing(self):
        """Un dumpxml illisible ne doit pas produire une commande sans cible."""
        self.assertEqual([], hw.hw_plan({}, {"vcpus": 4}, NODE))


class TestWant(unittest.TestCase):
    def test_empty_fields_keep_the_current_values(self):
        """Valider sans rien saisir ne doit pas rétrécir la VM à néant."""
        st = hw.hw_state(XML_SANS_3D)
        want = hw.build_want(st, "", "", False, False)
        self.assertEqual(8, want["vcpus"])
        self.assertEqual(32768, want["ram"])

    def test_gigabytes_are_understood(self):
        st = hw.hw_state(XML_SANS_3D)
        self.assertEqual(8192, hw.build_want(st, "", "8G", 0, 0)["ram"])

    def test_nonsense_does_not_shrink_the_vm(self):
        st = hw.hw_state(XML_SANS_3D)
        want = hw.build_want(st, "beaucoup", "gros", 0, 0)
        self.assertEqual(8, want["vcpus"])
        self.assertEqual(32768, want["ram"])


class TestDisplay(unittest.TestCase):
    def test_the_ram_field_stays_short_enough_to_read(self):
        """« 32768 » ne tient pas dans le champ et s'affichait « 3276 » : un
        nombre tronqué qu'on valide sans regarder rétrécit la machine."""
        self.assertEqual("32G", hw.ram_field(32768))
        self.assertEqual("1536", hw.ram_field(1536))
        for mib in (1024, 12288, 32768, 65536):
            self.assertLessEqual(len(hw.ram_field(mib)), 4)

    def test_sizes_read_like_sizes(self):
        self.assertEqual("1 Go", hw.fmt_mib(1024))
        self.assertEqual("1,5 Go", hw.fmt_mib(1536))
        self.assertEqual("512 Mo", hw.fmt_mib(512))

    def test_the_summary_names_the_render_node(self):
        self.assertIn("renderD128", hw.hw_summary(hw.hw_state(XML_AVEC_3D)))

    def test_a_screen_without_3d_says_software_rendering(self):
        summary = hw.hw_summary(hw.hw_state(XML_SANS_3D))
        self.assertIn("8 vCPU", summary)
        self.assertIn(hw.t("software rendering"), summary)


class TestMenuGlue(unittest.TestCase):
    """Le raccord dans todo.py : ce qui est éteint, et ce qui s'exécute."""

    def _todo(self, states, xml=XML_SANS_3D, node=NODE):
        todo = TODO.__new__(TODO)
        todo._qemu_domstate = lambda name: states[name]
        todo._qemu_dumpxml = lambda name: xml.replace(
            "erplibre-ubuntu-2604-gnome", name
        )
        todo._qemu_autostart = lambda name: False
        todo._qemu_host_gpu_node = lambda: node
        # Aucun test ne doit atteindre virsh : la liste des réseaux est fournie.
        todo._qemu_net_choices = lambda: ["network:default"]
        todo.launched = []
        todo.execute = mock.Mock()
        todo.execute.exec_command_live = (
            lambda cmd, **kw: todo.launched.append(cmd)
        )
        return todo

    def _run(self, todo, names, answers):
        it = iter(answers)
        out = io.StringIO()
        with mock.patch("builtins.input", lambda *a: next(it, "")):
            with contextlib.redirect_stdout(out):
                todo._qemu_adjust_hardware(names)
        return out.getvalue()

    def test_a_running_vm_is_left_alone_and_said_so(self):
        """virt-xml y écrirait une définition qui ne prend effet qu'au
        prochain démarrage : un réglage qui paraît appliqué et ne l'est pas."""
        todo = self._todo({"vm-a": "running"})
        todo._qemu_hw_form = lambda rows, node, nets=None: {}
        out = self._run(todo, ["vm-a"], [])
        self.assertIn("vm-a", out)
        self.assertEqual([], todo.launched)

    def test_a_shut_off_vm_is_adjusted(self):
        todo = self._todo({"vm-a": "shut off"})
        todo._qemu_hw_form = lambda rows, node, nets=None: {
            "vm-a": {"vcpus": 4, "ram": 8192, "gpu": True}
        }
        self._run(todo, ["vm-a"], ["o"])
        joined = " ".join(todo.launched)
        self.assertIn("--vcpus 4", joined)
        self.assertIn("accel3d=on", joined)
        self.assertTrue(all(c.startswith("sudo ") for c in todo.launched))

    def test_nothing_to_change_launches_nothing(self):
        todo = self._todo({"vm-a": "shut off"})
        todo._qemu_hw_form = lambda rows, node, nets=None: {
            "vm-a": {"vcpus": 8, "ram": 32768, "gpu": False}
        }
        out = self._run(todo, ["vm-a"], [])
        self.assertEqual([], todo.launched)
        self.assertIn(hw.t("Nothing to change."), out)

    def test_refusing_the_confirmation_launches_nothing(self):
        todo = self._todo({"vm-a": "shut off"})
        todo._qemu_hw_form = lambda rows, node, nets=None: {
            "vm-a": {"vcpus": 4}
        }
        self._run(todo, ["vm-a"], ["n"])
        self.assertEqual([], todo.launched)

    def test_cancelling_the_form_launches_nothing(self):
        todo = self._todo({"vm-a": "shut off"})
        todo._qemu_hw_form = lambda rows, node, nets=None: None
        self._run(todo, ["vm-a"], [])
        self.assertEqual([], todo.launched)

    def test_the_skipped_3d_is_explained_not_silent(self):
        todo = self._todo({"vm-a": "shut off"}, node="")
        todo._qemu_hw_form = lambda rows, node, nets=None: {
            "vm-a": {"gpu": True}
        }
        out = self._run(todo, ["vm-a"], [])
        self.assertIn(hw.t("no render node on the host"), out)
        self.assertEqual([], todo.launched)

    def test_the_host_gpu_is_announced_before_anything_else(self):
        todo = self._todo({"vm-a": "shut off"})
        todo._qemu_hw_form = lambda rows, node, nets=None: None
        out = self._run(todo, ["vm-a"], [])
        self.assertIn(NODE, out)

    def test_the_prompts_take_over_when_textual_is_absent(self):
        """Le repli en ligne n'est pas décoratif : sans Textual, c'est la SEULE
        voie, et un {} mal interprété annulerait tout."""
        todo = self._todo({"vm-a": "shut off"})
        todo._qemu_hw_form = lambda rows, node, nets=None: {}
        # vCPU, RAM, 3D, démarrage auto, mode CPU, écrans, puis la validation.
        self._run(todo, ["vm-a"], ["6", "", "o", "n", "", "", "o"])
        self.assertIn("--vcpus 6", " ".join(todo.launched))

    def test_an_empty_answer_keeps_the_current_state(self):
        """Le défaut d'une question fermée est l'état ACTUEL de la VM : sur un
        formulaire de matériel, le silence ne modifie rien."""
        todo = TODO.__new__(TODO)
        with mock.patch("builtins.input", lambda *a: ""):
            self.assertTrue(todo._qemu_ask_bool("? ", True))
            self.assertFalse(todo._qemu_ask_bool("? ", False))
        with mock.patch("builtins.input", lambda *a: "n'importe quoi"):
            self.assertTrue(todo._qemu_ask_bool("? ", True))

    def test_autostart_is_read_from_virsh(self):
        out = "Id:  -\nName: vm-a\nAutostart:      enable\n"
        with mock.patch(
            "subprocess.run",
            return_value=subprocess.CompletedProcess([], 0, out, ""),
        ):
            self.assertTrue(TODO._qemu_autostart("vm-a"))
        with mock.patch("subprocess.run", side_effect=OSError):
            self.assertFalse(TODO._qemu_autostart("vm-a"))


class TestForm(unittest.IsolatedAsyncioTestCase):
    """Le formulaire monté pour de vrai : ce qu'il propose et ce qu'il rend."""

    async def _mount(self, rows, node):
        app = hw.run_hardware_form(rows, node, run_app=False)
        return app

    async def test_it_returns_the_intention_on_apply(self):
        from textual.widgets import Checkbox, Input

        app = await self._mount([hw.hw_state(XML_SANS_3D)], NODE)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#vcpus0", Input).value = "6"
            app.query_one("#ram0", Input).value = "8G"
            app.query_one("#gpu0", Checkbox).value = True
            await pilot.press("ctrl+s")
            await pilot.pause()
        want = app.want["erplibre-ubuntu-2604-gnome"]
        self.assertEqual(6, want["vcpus"])
        self.assertEqual(8192, want["ram"])
        self.assertTrue(want["gpu"])

    async def test_escape_returns_nothing(self):
        app = await self._mount([hw.hw_state(XML_SANS_3D)], NODE)
        async with app.run_test() as pilot:
            await pilot.press("escape")
            await pilot.pause()
        self.assertIsNone(app.want)

    async def test_3d_is_out_of_reach_without_a_host_node(self):
        """Cocher une case qui ne peut rien produire ferait attendre une
        accélération que l'hôte ne sait pas donner."""
        from textual.widgets import Checkbox

        app = await self._mount([hw.hw_state(XML_SANS_3D)], "")
        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertTrue(app.query_one("#gpu0", Checkbox).disabled)

    async def test_3d_is_out_of_reach_for_a_screenless_vm(self):
        from textual.widgets import Checkbox

        app = await self._mount([hw.hw_state(XML_SERVEUR)], NODE)
        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertTrue(app.query_one("#gpu0", Checkbox).disabled)

    async def test_the_fields_start_on_the_current_values(self):
        from textual.widgets import Input

        app = await self._mount([hw.hw_state(XML_SANS_3D)], NODE)
        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertEqual("8", app.query_one("#vcpus0", Input).value)
            self.assertEqual("32G", app.query_one("#ram0", Input).value)

    async def test_the_second_row_carries_cpu_screens_and_network(self):
        from textual.widgets import Input, Select

        app = hw.run_hardware_form(
            [hw.hw_state(XML_COMPLET)],
            NODE,
            nets=["network:default", "bridge:br0"],
            run_app=False,
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#cpu0", Select).value = "host-model"
            app.query_one("#heads0", Input).value = "2"
            app.query_one("#net0", Select).value = "bridge:br0"
            await pilot.press("ctrl+s")
            await pilot.pause()
        want = app.want["erplibre-ubuntu-2604-gnome"]
        self.assertEqual("host-model", want["cpu"])
        self.assertEqual(2, want["heads"])
        self.assertEqual("bridge:br0", want["net"])

    async def test_the_screens_value_is_actually_visible(self):
        """Sous six colonnes, Textual dessine le cadre du champ mais PAS son
        contenu : la valeur devient invisible, et on valide un champ qu'on
        croit vide. Pire qu'une troncature, donc vérifié à l'écran."""
        import re

        app = hw.run_hardware_form(
            [dict(hw.hw_state(XML_COMPLET), heads=3)], NODE, run_app=False
        )
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            svg = app.export_screenshot()
        rendu = re.findall(r">([^<>]+)</text>", svg)
        self.assertIn("3", [txt.strip() for txt in rendu])

    async def test_without_networks_to_offer_there_is_no_network_field(self):
        """Un hôte sans pont n'a qu'une voie : une liste à un seul choix ne
        vaut pas la place qu'elle prend."""
        app = hw.run_hardware_form(
            [dict(hw.hw_state(XML_COMPLET), net="")], NODE, run_app=False
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertEqual(0, len(app.query("#net0")))
            await pilot.press("ctrl+s")
            await pilot.pause()
        self.assertEqual("", app.want["erplibre-ubuntu-2604-gnome"]["net"])

    async def test_the_current_network_stays_selected(self):
        """La liste montre ce que la VM a : sans cela, valider sans y toucher
        la basculerait sur le premier choix de la liste."""
        from textual.widgets import Select

        app = hw.run_hardware_form(
            [hw.hw_state(XML_COMPLET)],
            NODE,
            nets=["bridge:br0", "network:default"],
            run_app=False,
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertEqual(
                "network:default", app.query_one("#net0", Select).value
            )
            await pilot.press("ctrl+s")
            await pilot.pause()
        want = app.want["erplibre-ubuntu-2604-gnome"]
        self.assertEqual("network:default", want["net"])
        self.assertEqual([], hw.hw_plan(hw.hw_state(XML_COMPLET), want, NODE))

    async def test_it_fits_in_eighty_columns(self):
        """Un terminal de 80 colonnes est le plus petit qu'on rencontre ;
        au-delà, les libellés se tronquent en « Démarrage automatiq… »."""
        import re

        rows = [hw.hw_state(XML_COMPLET), hw.hw_state(XML_SERVEUR)]
        app = hw.run_hardware_form(
            rows, NODE, nets=["network:default", "bridge:br0"], run_app=False
        )
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            svg = app.export_screenshot()
        texte = " ".join(re.findall(r">([^<>]+)</text>", svg))
        self.assertNotIn("…", texte)


class TestCpuScreensNetwork(unittest.TestCase):
    """Les trois réglages ajoutés, et pourquoi chacun est celui-là.

    Mesuré sur l'hôte avant de les offrir : « heads » atteint QEMU
    (max_outputs), « vram » NON sur un virtio-gpu — il n'est donc pas proposé.
    """

    def _plan(self, xml, want, node=NODE):
        return hw.hw_plan(hw.hw_state(xml), want, node)

    def test_it_reads_the_cpu_mode_screens_and_network(self):
        st = hw.hw_state(XML_COMPLET)
        self.assertEqual("host-passthrough", st["cpu"])
        self.assertEqual(1, st["heads"])
        self.assertEqual("network:default", st["net"])

    def test_a_vm_without_an_interface_has_no_network(self):
        self.assertEqual("", hw.hw_state(XML_SERVEUR)["net"])

    def test_a_bridge_is_read_as_a_bridge(self):
        """libvirt refuse type='network' avec un pont pour source : le type et
        le nom doivent voyager ensemble."""
        xml = XML_COMPLET.replace(
            "<interface type='network'>", "<interface type='bridge'>"
        ).replace("<source network='default'/>", "<source bridge='br0'/>")
        self.assertEqual("bridge:br0", hw.hw_state(xml)["net"])

    def test_the_label_marks_the_bridge_only(self):
        """Le réseau libvirt est le cas ordinaire ; le suffixe allongeait le
        libellé au-delà de la liste déroulante, qui se repliait."""
        self.assertEqual("default", hw.net_label("network:default"))
        self.assertIn("br0", hw.net_label("bridge:br0"))
        self.assertIn(hw.t("bridge"), hw.net_label("bridge:br0"))

    def test_the_spec_names_the_right_virt_xml_key(self):
        self.assertEqual("network=default", hw.net_spec("network:default"))
        self.assertEqual("bridge=br0", hw.net_spec("bridge:br0"))

    def test_passthrough_keeps_check_and_migratable(self):
        """C'est ce que virt-install écrit, et ce que veut la virtualisation
        imbriquée : sans eux libvirt vérifie un modèle qu'il n'a pas calculé.
        """
        xml = XML_COMPLET.replace(
            "<cpu mode='host-passthrough' check='none' migratable='on'/>",
            "<cpu mode='host-model'/>",
        )
        plan = self._plan(xml, {"cpu": "host-passthrough"})
        arg = plan[0]["cmd"][-1]
        self.assertIn("check=none", arg)
        self.assertIn("migratable=on", arg)

    def test_host_model_carries_nothing_extra(self):
        plan = self._plan(XML_COMPLET, {"cpu": "host-model"})
        self.assertEqual("host-model", plan[0]["cmd"][-1])

    def test_the_same_cpu_mode_changes_nothing(self):
        self.assertEqual(
            [], self._plan(XML_COMPLET, {"cpu": "host-passthrough"})
        )

    def test_screens_go_through_the_video_model(self):
        """« heads » devient max_outputs sur la ligne QEMU — vérifié par
        domxml-to-native. C'est le seul réglage vidéo qui y arrive."""
        plan = self._plan(XML_COMPLET, {"heads": 2})
        self.assertIn("model.heads=2", plan[0]["cmd"])

    def test_screens_on_a_screenless_vm_are_refused_not_attempted(self):
        """« --edit --video » sortirait en erreur au milieu du lot, et les
        commandes suivantes ne partiraient pas."""
        plan = self._plan(XML_SERVEUR, {"heads": 2})
        self.assertEqual(1, len(plan))
        self.assertIn("skip", plan[0])

    def test_screens_and_3d_are_two_separate_edits(self):
        """Vérifié sur un domaine réel : le second « --edit --video » ne
        remet pas heads à 1, et le premier ne perd pas l'accélération."""
        plan = self._plan(XML_COMPLET, {"heads": 2, "gpu": True})
        videos = [e for e in plan if "--video" in e.get("cmd", [])]
        self.assertEqual(2, len(videos))
        heads = [e for e in videos if "model.heads=2" in e["cmd"]]
        self.assertEqual(1, len(heads))
        self.assertNotIn("accel3d", " ".join(heads[0]["cmd"]))

    def test_switching_to_a_bridge(self):
        """Le MAC et l'adresse PCI survivent — vérifié sur un domaine réel,
        démarré : sans cela l'invité verrait une carte neuve, et son bail
        DHCP comme son nom d'interface changeraient."""
        plan = self._plan(XML_COMPLET, {"net": "bridge:br0"})
        self.assertIn("bridge=br0", plan[0]["cmd"])
        self.assertNotIn("mac", " ".join(plan[0]["cmd"]))

    def test_switching_back_to_a_libvirt_network(self):
        xml = XML_COMPLET.replace(
            "<interface type='network'>", "<interface type='bridge'>"
        ).replace("<source network='default'/>", "<source bridge='br0'/>")
        plan = hw.hw_plan(hw.hw_state(xml), {"net": "network:default"}, NODE)
        self.assertIn("network=default", plan[0]["cmd"])

    def test_the_same_network_changes_nothing(self):
        self.assertEqual(
            [], self._plan(XML_COMPLET, {"net": "network:default"})
        )

    def test_a_vm_without_an_interface_is_told_not_attempted(self):
        plan = self._plan(XML_SERVEUR, {"net": "bridge:br0"})
        self.assertEqual(1, len(plan))
        self.assertIn("skip", plan[0])

    def test_an_unknown_current_cpu_mode_stays_offered(self):
        """Une VM en mode « custom » ne doit pas voir son réglage disparaître
        d'une liste qui l'ignore : la liste afficherait un AUTRE mode que le
        sien, et valider le formulaire le changerait sans le dire."""
        modes = hw.cpu_choices([{"cpu": "custom"}])
        self.assertIn("custom", modes)
        self.assertIn("host-passthrough", modes)

    def test_the_network_list_merges_the_host_and_the_current_value(self):
        choices = hw.net_choices(
            [{"net": "bridge:br9"}], ["network:default", "bridge:br9"]
        )
        self.assertEqual(
            ["network:default", "bridge:br9"], [tok for tok, _ in choices]
        )

    def test_empty_answers_keep_the_current_hardware(self):
        st = hw.hw_state(XML_COMPLET)
        want = hw.build_want(
            st, "", "", False, False, cpu="", heads="", net=""
        )
        self.assertEqual("host-passthrough", want["cpu"])
        self.assertEqual(1, want["heads"])
        self.assertEqual("network:default", want["net"])
        self.assertEqual([], hw.hw_plan(st, want, ""))


class TestHostNetworks(unittest.TestCase):
    """Ce que l'hôte propose : ses réseaux libvirt, et ses ponts à lui."""

    def _choices(self, nets, infos, bridges):
        todo = TODO.__new__(TODO)
        sorties = {}
        sorties["net-list"] = nets
        sorties["bridge"] = bridges
        sorties.update(infos)

        def fake(cmd):
            if "net-list" in cmd:
                return sorties["net-list"]
            if "net-info" in cmd:
                return sorties.get(cmd[-1], [])
            return sorties["bridge"]

        todo._qemu_cmd_lines = fake
        return todo._qemu_net_choices()

    def test_a_libvirt_owned_bridge_is_not_offered_twice(self):
        """virbr0 EST le réseau « default » : l'offrir aussi comme pont
        proposerait deux fois le même chemin, dont un qui contourne la
        gestion du réseau par libvirt."""
        got = self._choices(
            ["default"],
            {"default": ["Name:           default", "Bridge:         virbr0"]},
            ["3: virbr0: <BROADCAST,MULTICAST,UP,LOWER_UP>"],
        )
        self.assertEqual(["network:default"], got)

    def test_a_real_bridge_is_offered(self):
        got = self._choices(
            ["default"],
            {"default": ["Bridge:         virbr0"]},
            [
                "3: virbr0: <BROADCAST>",
                "4: br0: <BROADCAST,MULTICAST,UP,LOWER_UP>",
            ],
        )
        self.assertEqual(["network:default", "bridge:br0"], got)

    def test_a_host_without_libvirt_answers_nothing(self):
        todo = TODO.__new__(TODO)
        todo._qemu_cmd_lines = lambda cmd: []
        self.assertEqual([], todo._qemu_net_choices())

    def test_the_persistent_definition_is_what_gets_read(self):
        """Sur une VM allumée, « dumpxml » sans --inactive rend la vue VIVANTE
        (portid, vnetN, alias) — pas la définition que virt-xml modifie."""
        vu = {}

        def fake_run(cmd, **kw):
            vu["cmd"] = cmd
            return subprocess.CompletedProcess([], 0, "<domain/>", "")

        with mock.patch("subprocess.run", side_effect=fake_run):
            TODO._qemu_dumpxml("vm-a")
        self.assertIn("--inactive", vu["cmd"])

    def test_a_numbered_pick_defaults_to_the_current_value(self):
        todo = TODO.__new__(TODO)
        out = io.StringIO()
        for reponse, attendu in (
            ("", "b"),
            ("mille", "b"),
            ("9", "b"),
            ("1", "a"),
            ("2", "b"),
        ):
            with mock.patch("builtins.input", lambda *a, r=reponse: r):
                with contextlib.redirect_stdout(out):
                    got = todo._qemu_pick("t", ["a", "b"], "b")
            self.assertEqual(attendu, got, reponse)


if __name__ == "__main__":
    unittest.main(verbosity=1)
