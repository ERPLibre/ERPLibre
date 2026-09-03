#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La 3D se coche à la création, même sur une VM sans écran.

« auto » s'abstient sans écran virtuel : une VM serveur n'a pas demandé de
périphérique vidéo, et lui en poser un d'office changerait son matériel. Mais
une VM sans console peut vouloir un virtio-gpu accéléré — rendu hors écran,
émulateur qui tourne dedans. La case le demande explicitement.

Ce que ces tests gardent :

- la case atteint vraiment la commande, à travers la spec ;
- sans elle, rien ne change pour une VM serveur ;
- « --graphics none » et « egl-headless » ne coexistent jamais : le premier
  dit « aucun affichage », le second EST un affichage.
"""

import importlib.util
import sys
import unittest
from pathlib import Path

sys.argv = ["todo.py"]
from script.todo.deploy_form_lib import build_spec  # noqa: E402
from script.todo.todo import TODO  # noqa: E402

RACINE = Path(__file__).resolve().parents[1]
NODE = "/dev/dri/renderD128"


def _deploy_qemu():
    path = RACINE / "script/qemu/deploy_qemu.py"
    spec = importlib.util.spec_from_file_location("deploy_qemu", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


DQ = _deploy_qemu()


class LaDecision(unittest.TestCase):
    def test_auto_still_abstains_without_a_screen(self):
        """Le défaut ne doit pas changer : une VM serveur reste sans vidéo."""
        on, msg = DQ.gpu_decision("auto", NODE, False)
        self.assertFalse(on)
        self.assertEqual("", msg)

    def test_on_now_enables_3d_without_a_screen(self):
        on, msg = DQ.gpu_decision("on", NODE, False)
        self.assertTrue(on)
        self.assertIn("sans écran", msg)

    def test_off_wins_over_everything(self):
        self.assertEqual((False, ""), DQ.gpu_decision("off", NODE, False))

    def test_without_a_host_node_it_still_refuses(self):
        on, msg = DQ.gpu_decision("on", "", False)
        self.assertFalse(on)
        self.assertTrue(msg)


class LaCaseAtteintLaCommande(unittest.TestCase):
    def setUp(self):
        self.todo = TODO.__new__(TODO)

    def _parts(self, gpu3d):
        vm = {
            "name": "vm-a",
            "distro": "ubuntu",
            "version": "24.04",
            "arch": "amd64",
            "ram": 4096,
            "vcpus": 2,
            "disk": "20G",
        }
        spec = {
            "vms": [vm],
            "gpu3d": gpu3d,
            "install": None,
            "ssh_key": "",
            "vm_tools": (),
        }
        return self.todo._qemu_deploy_parts_for(vm, spec, dry_run=True)

    def test_the_box_adds_the_flag(self):
        self.assertIn("--gpu", self._parts(True))
        parts = self._parts(True)
        self.assertEqual("on", parts[parts.index("--gpu") + 1])

    def test_without_the_box_nothing_is_added(self):
        self.assertNotIn("--gpu", self._parts(False))


class LaSpecLaTransporte(unittest.TestCase):
    def _spec(self, form_extra):
        form = {
            "res_label": "x1",
            "ssh_key": "",
            "install": None,
            "add_ssh_config": True,
            "parallelism": 1,
        }
        form.update(form_extra)
        return build_spec([{"name": "vm-a"}], [], form)

    def test_the_checkbox_reaches_the_spec(self):
        self.assertTrue(self._spec({"gpu3d": True})["gpu3d"])

    def test_its_default_is_off(self):
        self.assertFalse(self._spec({})["gpu3d"])


class LAbiFigee(unittest.TestCase):
    """Une 3D demandée que l'ABI figée annule doit se voir.

    Depuis libvirt 12.5.0, le <model> vidéo porte un attribut « device »
    qui grave le device QEMU retenu, pour tenir l'ABI de l'invité stable
    d'un démarrage à l'autre. Il l'emporte sur « accel3d » : une VM
    démarrée une première fois sans 3D garde le device sans GL, et cocher
    la 3D ensuite ne change rien à ce que QEMU reçoit. La définition et
    la ligne de commande se contredisent alors en silence.
    """

    XML = (
        "<domain><name>vm</name><vcpu>8</vcpu>"
        "<memory unit='KiB'>33554432</memory><devices>"
        "<video><model type='virtio' heads='1' {attr}>"
        "<acceleration accel3d='{accel}'/></model></video>"
        "<graphics type='egl-headless'>"
        "<gl rendernode='/dev/dri/renderD128'/></graphics>"
        "</devices></domain>"
    )

    def _etat(self, device="", accel="yes"):
        from script.todo.qemu_hardware import hw_state

        attr = f"device='{device}'" if device else ""
        return hw_state(self.XML.format(attr=attr, accel=accel), False)

    def test_the_pinned_device_is_read(self):
        self.assertEqual(
            self._etat("virtio-vga")["video_device"], "virtio-vga"
        )
        self.assertEqual(self._etat()["video_device"], "")

    def test_a_non_gl_pin_defeats_the_requested_3d(self):
        from script.todo.qemu_hardware import pin_defeats_3d

        self.assertTrue(pin_defeats_3d(self._etat("virtio-vga")))

    def test_a_gl_pin_does_not(self):
        """Le suffixe « -gl » est ce qui distingue les deux devices.

        Sans cette lecture, tout épinglage passerait pour une panne et la
        VM correctement accélérée porterait un avertissement à tort.
        """
        from script.todo.qemu_hardware import pin_defeats_3d

        self.assertFalse(pin_defeats_3d(self._etat("virtio-vga-gl")))
        self.assertFalse(pin_defeats_3d(self._etat("virtio-gpu-gl")))

    def test_no_pin_and_no_3d_are_not_flagged(self):
        """Deux cas voisins qu'un test trop large confondrait : libvirt
        antérieur à 12.5.0 n'écrit pas l'attribut, et une VM sans 3D
        demandée n'a rien à signaler même si son device est figé."""
        from script.todo.qemu_hardware import pin_defeats_3d

        self.assertFalse(pin_defeats_3d(self._etat()))
        self.assertFalse(pin_defeats_3d(self._etat("virtio-vga", accel="no")))

    def test_the_summary_says_so(self):
        """La ligne de résumé est celle sur laquelle on décide : elle ne
        doit pas afficher « 3D » tout court quand la 3D ne tourne pas."""
        from script.todo.qemu_hardware import hw_summary

        figee = hw_summary(self._etat("virtio-vga"))
        vivante = hw_summary(self._etat("virtio-vga-gl"))
        self.assertIn("virtio-vga", figee)
        self.assertIn("⚠", figee)
        self.assertNotIn("⚠", vivante)


if __name__ == "__main__":
    unittest.main()


try:
    import yaml
except ImportError:
    yaml = None


class LesGroupesGpuDeLInvite(unittest.TestCase):
    """Le compte de l'invité doit pouvoir OUVRIR le nœud de rendu.

    Le matériel virtuel accéléré ne suffit pas : dans l'invité, le nœud
    appartient à « root:render » en 0660, et un compte hors de ce groupe
    retombe sur le rendu logiciel alors que la négociation VIRGL a réussi.
    Rien ne le signale. En session graphique locale logind pose une ACL
    pour l'utilisateur du siège ; en SSH ou en tty, personne ne la pose.
    """

    def _args(self, distro="ubuntu", gpu="auto"):
        return DQ.build_parser().parse_args(
            ["--distro", distro, "--gpu", gpu, "--hostname", "vm"]
        )

    def _cc(self, **kw):
        return DQ.build_cloud_config(self._args(**kw), None, [])

    def test_the_account_joins_the_gpu_groups(self):
        """Sur les groupes DU COMPTE, et non sur le texte du document : le
        bloc qui déclare les groupes y porte déjà les deux mots, si bien
        qu'y chercher « render » passerait sans que personne n'y entre."""
        noms = DQ.user_groups("ubuntu", gpu=True).split(", ")
        self.assertIn("render", noms)
        self.assertIn("video", noms)
        self.assertNotIn("render", DQ.user_groups("ubuntu").split(", "))

    def test_gpu_off_leaves_the_account_alone(self):
        """« off » est un refus explicite : ne rien ajouter alors."""
        cc = self._cc(gpu="off")
        self.assertNotIn("render", cc)
        self.assertNotIn("video", cc)

    def test_the_admin_group_survives_every_distro(self):
        """Le groupe d'administration ne doit pas être perdu en chemin :
        sans lui la commodité disparaît, et un nom inconnu ferait bien
        pire — cloud-init ne créerait pas le compte du tout."""
        for distro, attendu in (
            ("ubuntu", "sudo"),
            ("debian", "sudo"),
            ("arch", "wheel"),
            ("almalinux", "wheel"),
        ):
            with self.subTest(distro=distro):
                self.assertIn(
                    attendu, DQ.user_groups(distro, gpu=True).split(", ")
                )

    def test_opensuse_still_gets_no_admin_group(self):
        """Son cloud-init n'en met pas et « wheel » n'y est pas garanti :
        en ajouter un risquerait un compte jamais créé."""
        noms = DQ.user_groups("opensuse", gpu=True).split(", ")
        self.assertNotIn("wheel", noms)
        self.assertNotIn("sudo", noms)
        self.assertIn("render", noms)

    @unittest.skipIf(yaml is None, "PyYAML absent")
    def test_the_groups_are_declared_before_being_used(self):
        """« useradd -G » échoue sur un nom de groupe INCONNU, et cloud-init
        ne crée alors pas le compte : ni mot de passe ni clé SSH, la VM
        démarre inaccessible. « render » manque des images anciennes, donc
        le déclarer n'est pas une précaution de style."""
        doc = yaml.safe_load(self._cc())
        self.assertEqual(["render", "video"], doc["groups"])
        for nom in ("render", "video"):
            self.assertIn(nom, doc["users"][0]["groups"].split(", "))

    @unittest.skipIf(yaml is None, "PyYAML absent")
    def test_the_document_stays_parsable_everywhere(self):
        for distro in ("ubuntu", "debian", "arch", "almalinux", "opensuse"):
            for gpu in ("auto", "on", "off"):
                with self.subTest(distro=distro, gpu=gpu):
                    doc = yaml.safe_load(self._cc(distro=distro, gpu=gpu))
                    self.assertEqual("vm", doc["hostname"])

    def test_the_preseed_creates_the_groups_before_using_them(self):
        """Debian passe par le preseed et non par cloud-init : la parité
        promise par build_preseed s'y perdrait sans cela. L'ORDRE compte —
        « usermod -aG » sur un groupe absent échoue."""
        pre = DQ.build_preseed(self._args(distro="debian"), "$6$x$y", [])
        i_add = pre.index("groupadd -f render")
        i_use = pre.index("usermod -aG render,video")
        self.assertLess(i_add, i_use)

    def test_the_preseed_says_nothing_when_gpu_is_off(self):
        pre = DQ.build_preseed(
            self._args(distro="debian", gpu="off"), "$6$x$y", []
        )
        self.assertNotIn("groupadd", pre)
