#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les Stream Deck de l'hôte passés à la VM dès sa création.

Deux options de deploy_qemu.py, et leur case dans les deux formulaires :

- « --usb-hostdev VID:PID|BUS.DEV » ajoute un --hostdev à virt-install,
  APRÈS la tranche 3D pour survivre au repli EGL, confronté d'abord aux
  périphériques branchés : absent, il est sauté sans faire échouer la VM ;
  deux identiques, chacun est épinglé par bus.dev ;
- « --spice-usbredir » pose un affichage SPICE AVANT le VNC, sur une VM
  graphique x86 seulement : virt-viewer ouvre le premier affichage, et seul
  SPICE a le menu de redirection USB.

Ce que ces tests gardent aussi :

- la case atteint la commande à travers la spec, et seule la PREMIÈRE VM
  graphique du parc reçoit les decks : libvirt refuse de démarrer un second
  domaine qui les tiendrait ;
- la recréation d'une VM rejoue ce qu'elle avait reçu, rien de plus ;
- sans les options, la commande ne change pas d'un argument.

Les périphériques sont inventés ; aucun sysfs réel n'est lu.
"""

import importlib.util
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.argv = ["todo.py"]
from script.todo import deploy_form_lib as dfl  # noqa: E402
from script.todo.qemu_deploy import spec_usb_receiver  # noqa: E402
from script.todo.todo import TODO  # noqa: E402

RACINE = Path(__file__).resolve().parents[1]


def _deploy_qemu():
    path = RACINE / "script/qemu/deploy_qemu.py"
    spec = importlib.util.spec_from_file_location("deploy_qemu", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


DQ = _deploy_qemu()

SORTIE_EGL = "qemu-system-x86_64: egl: eglInitialize failed\n"


def _dev(bus, num, vid="0fd9", pid="0080", product="Stream Deck MK.2"):
    """Un périphérique dans la forme de qemu_usb.read_usb_device()."""
    return {
        "sysname": f"{bus}-{num}",
        "busnum": bus,
        "devnum": num,
        "vid": vid,
        "pid": pid,
        "product": product,
        "manufacturer": "Elgato",
        "serial": f"TESTSERIAL{bus}{num}",
        "device_class": "00",
        "is_deck": vid == "0fd9",
    }


DECK = _dev(3, 5)
JUMEAU = _dev(3, 9)
CLAVIER = _dev(1, 2, vid="1234", pid="5678", product="Clavier")


# --------------------------------------------------------------------------- #
# deploy_qemu.py
# --------------------------------------------------------------------------- #
class LesSelecteurs(unittest.TestCase):
    def test_both_forms_are_accepted_and_repeatable(self):
        args = DQ.build_parser().parse_args(
            ["--usb-hostdev", "0fd9:0080", "--usb-hostdev", "3.5"]
        )
        self.assertEqual(["0fd9:0080", "3.5"], args.usb_hostdev)

    def test_the_default_is_none(self):
        args = DQ.build_parser().parse_args([])
        self.assertEqual([], args.usb_hostdev)
        self.assertFalse(args.spice_usbredir)

    def test_a_sysfs_name_is_refused_at_parse_time(self):
        """« 3-5 » est un nom sysfs : le second nombre est un PORT."""
        with (
            redirect_stdout(io.StringIO()),
            mock.patch("sys.stderr", io.StringIO()),
            self.assertRaises(SystemExit),
        ):
            DQ.build_parser().parse_args(["--usb-hostdev", "3-5"])


class LeHostdev(unittest.TestCase):
    def test_a_unique_device_goes_by_vid_pid(self):
        args, lignes = DQ.usb_hostdev_args(["0fd9:0080"], [DECK, CLAVIER])
        self.assertEqual(
            ["--hostdev", "0fd9:0080,source.startupPolicy=optional"], args
        )
        self.assertIn("Stream Deck MK.2", lignes[0])

    def test_an_absent_device_is_skipped_with_a_warning(self):
        args, lignes = DQ.usb_hostdev_args(["0fd9:0080"], [CLAVIER])
        self.assertEqual([], args)
        self.assertIn("⚠", lignes[0])
        self.assertIn("0fd9:0080", lignes[0])

    def test_two_identical_decks_are_pinned_without_leading_zeros(self):
        """libvirt lirait « 009 » comme un octal invalide."""
        args, _ = DQ.usb_hostdev_args(["0fd9:0080"], [DECK, JUMEAU])
        self.assertEqual(
            [
                "--hostdev",
                "3.5,source.startupPolicy=optional",
                "--hostdev",
                "3.9,source.startupPolicy=optional",
            ],
            args,
        )

    def test_a_device_named_twice_is_passed_once(self):
        args, _ = DQ.usb_hostdev_args(["0fd9:0080", "3.5"], [DECK])
        self.assertEqual(2, len(args))

    def test_a_bus_dev_selector_reaches_its_device(self):
        args, _ = DQ.usb_hostdev_args(["3.9"], [DECK, JUMEAU])
        self.assertEqual(
            ["--hostdev", "3.9,source.startupPolicy=optional"], args
        )


def _args(**kw):
    base = dict(
        name="vm-a",
        memory=4096,
        vcpus=2,
        arch="amd64",
        network="network=default,model=virtio",
        graphics="none",
        desktop=True,
        gpu="off",
        gpu_node="/dev/dri/renderD128",
        attach_console=False,
        bios=False,
        usb_hostdev=[],
        spice_usbredir=False,
    )
    base.update(kw)
    return SimpleNamespace(**base)


class LeRefus(unittest.TestCase):
    def test_a_desktop_x86_vm_is_accepted(self):
        self.assertEqual("", DQ.usb_refusal(_args(spice_usbredir=True)))

    def test_spice_needs_a_screen(self):
        refus = DQ.usb_refusal(_args(spice_usbredir=True, desktop=False))
        self.assertIn("--spice-usbredir", refus)
        self.assertIn("--desktop", refus)

    def test_an_explicit_display_is_a_screen(self):
        self.assertEqual(
            "",
            DQ.usb_refusal(
                _args(
                    spice_usbredir=True,
                    desktop=False,
                    graphics="vnc,listen=127.0.0.1",
                )
            ),
        )

    def test_spice_is_x86_only(self):
        refus = DQ.usb_refusal(_args(spice_usbredir=True, arch="arm64"))
        self.assertIn("x86_64", refus)

    def test_s390x_has_no_usb_bus(self):
        refus = DQ.usb_refusal(_args(usb_hostdev=["3.5"], arch="s390x"))
        self.assertIn("--usb-hostdev", refus)

    def test_a_hostdev_on_a_server_is_accepted(self):
        self.assertEqual(
            "", DQ.usb_refusal(_args(usb_hostdev=["3.5"], desktop=False))
        )


class LeNoyau(unittest.TestCase):
    """Le noyau cloud de Debian n'a pas d'USB : un serveur qui reçoit un
    --usb-hostdev prend l'image « generic », comme un bureau."""

    def test_a_server_with_a_hostdev_gets_the_generic_image(self):
        args = _args(usb_hostdev=["0fd9:0080"], desktop=False)
        self.assertTrue(DQ.wants_full_kernel(args))
        self.assertEqual(
            "debian-12-generic-amd64.qcow2",
            DQ.default_image_name(
                "debian", "bookworm", "amd64", "12", DQ.wants_full_kernel(args)
            ),
        )

    def test_a_plain_server_keeps_the_cloud_image(self):
        args = _args(desktop=False)
        self.assertFalse(DQ.wants_full_kernel(args))
        self.assertEqual("genericcloud", DQ.debian_variant("12", False))

    def test_a_desktop_needs_the_full_kernel(self):
        self.assertTrue(DQ.wants_full_kernel(_args()))

    def test_spice_redirection_needs_the_full_kernel(self):
        """Une VM non bureau, à --graphics vnc, accepte --spice-usbredir :
        le deck redirigé par virt-viewer exige lui aussi l'USB du noyau."""
        args = _args(
            desktop=False,
            spice_usbredir=True,
            graphics="vnc,listen=127.0.0.1",
        )
        self.assertEqual("", DQ.usb_refusal(args))
        self.assertTrue(DQ.wants_full_kernel(args))


class LaCommande(unittest.TestCase):
    """virt_install avec un FauxRunner : l'ordre des affichages et le
    --hostdev, en premier essai comme après le repli EGL."""

    def _lancer(self, args, devs=(DECK,), sortie=None):
        lances = []

        class FauxRunner:
            dry_run = False
            use_sudo = False

            def run(self, cmd, *, privileged=False, check=True, capture=False):
                lances.append(list(cmd))
                if capture:
                    return sortie or (0, "")
                return None

        with (
            mock.patch.object(DQ, "host_arch", return_value="amd64"),
            mock.patch.object(DQ, "kvm_available", return_value=True),
            mock.patch.object(DQ, "host_gpu_node", return_value=""),
            mock.patch.object(DQ, "usb_host_devices", return_value=list(devs)),
            mock.patch.object(DQ, "os") as faux_os,
        ):
            faux_os.getuid.return_value = 1000
            buf = io.StringIO()
            with redirect_stdout(buf):
                DQ.virt_install(
                    args,
                    Path("/tmp/d.qcow2"),
                    Path("/tmp/s.iso"),
                    "ubuntu26.04",
                    FauxRunner(),
                )
        return lances, buf.getvalue()

    @staticmethod
    def _graphics(cmd):
        return [cmd[i + 1] for i, a in enumerate(cmd) if a == "--graphics"]

    def test_spice_comes_before_vnc(self):
        lances, _ = self._lancer(_args(spice_usbredir=True))
        self.assertEqual(
            ["spice,listen=127.0.0.1", "vnc,listen=127.0.0.1"],
            self._graphics(lances[0]),
        )

    def test_the_hostdev_is_in_the_command(self):
        lances, sortie = self._lancer(_args(usb_hostdev=["0fd9:0080"]))
        self.assertIn("0fd9:0080,source.startupPolicy=optional", lances[0])
        self.assertIn("Stream Deck", sortie)

    def test_an_absent_deck_does_not_stop_the_install(self):
        lances, sortie = self._lancer(
            _args(usb_hostdev=["0fd9:0080"]), devs=()
        )
        self.assertEqual(1, len(lances))
        self.assertNotIn("--hostdev", lances[0])
        self.assertIn("⚠", sortie)

    def test_without_the_options_nothing_changes(self):
        """Ni SPICE ni --hostdev : l'affichage reste le seul VNC."""
        lances, _ = self._lancer(_args())
        self.assertEqual(["vnc,listen=127.0.0.1"], self._graphics(lances[0]))
        self.assertNotIn("--hostdev", lances[0])

    def test_sysfs_is_not_read_without_a_selector(self):
        appels = []
        with mock.patch.object(
            DQ, "usb_host_devices", side_effect=lambda: appels.append(1)
        ):
            args = _args()
            with (
                mock.patch.object(DQ, "host_arch", return_value="amd64"),
                mock.patch.object(DQ, "kvm_available", return_value=True),
                mock.patch.object(DQ, "host_gpu_node", return_value=""),
                mock.patch.object(DQ, "os") as faux_os,
                redirect_stdout(io.StringIO()),
            ):
                faux_os.getuid.return_value = 1000
                runner = SimpleNamespace(
                    run=lambda cmd, **kw: (
                        (0, "") if kw.get("capture") else None
                    )
                )
                DQ.virt_install(
                    args, Path("/d"), Path("/s"), "ubuntu26.04", runner
                )
        self.assertEqual([], appels)

    def test_both_survive_the_egl_fallback(self):
        """SPICE est avant la tranche 3D, --hostdev après : le repli EGL,
        qui ne retire que la tranche, les garde tous les deux."""
        args = _args(
            spice_usbredir=True, usb_hostdev=["0fd9:0080"], gpu="auto"
        )
        lances = []

        class FauxRunner:
            dry_run = False
            use_sudo = False

            def run(self, cmd, *, privileged=False, check=True, capture=False):
                lances.append(list(cmd))
                return (1, SORTIE_EGL) if capture else None

        with (
            mock.patch.object(DQ, "host_arch", return_value="amd64"),
            mock.patch.object(DQ, "kvm_available", return_value=True),
            mock.patch.object(DQ, "usb_host_devices", return_value=[DECK]),
            mock.patch.object(DQ, "os") as faux_os,
            redirect_stdout(io.StringIO()),
        ):
            faux_os.getuid.return_value = 1000
            DQ.virt_install(
                args, Path("/d"), Path("/s"), "ubuntu26.04", FauxRunner()
            )
        premier, dernier = lances[0], lances[-1]
        self.assertIn("model.acceleration.accel3d=on", " ".join(premier))
        self.assertNotIn("accel3d", " ".join(dernier))
        for cmd in (premier, dernier):
            with self.subTest(essai=lances.index(cmd)):
                graphics = self._graphics(cmd)
                self.assertEqual("spice,listen=127.0.0.1", graphics[0])
                self.assertEqual("vnc,listen=127.0.0.1", graphics[1])
                self.assertIn("0fd9:0080,source.startupPolicy=optional", cmd)


# --------------------------------------------------------------------------- #
# deploy_form_lib : qui reçoit quoi
# --------------------------------------------------------------------------- #
def _vm(name, desktop="gnome", arch="amd64"):
    return {
        "name": name,
        "distro": "ubuntu",
        "version": "24.04",
        "arch": arch,
        "ram": 4096,
        "vcpus": 2,
        "disk": "20G",
        "desktop": desktop,
    }


class LaRegle(unittest.TestCase):
    def test_a_server_is_not_eligible(self):
        self.assertFalse(dfl.usb_eligible(_vm("vm-a", desktop="")))

    def test_s390x_is_not_eligible(self):
        self.assertFalse(dfl.usb_eligible(_vm("vm-a", arch="s390x")))

    def test_arm64_gets_the_deck_but_not_spice(self):
        vm = _vm("vm-a", arch="arm64")
        self.assertTrue(dfl.usb_eligible(vm))
        self.assertFalse(dfl.usb_spice_eligible(vm))

    def test_the_receiver_is_the_first_graphical_vm(self):
        vms = [_vm("vm-srv", desktop=""), _vm("vm-b"), _vm("vm-c")]
        self.assertEqual("vm-b", dfl.usb_receiver(vms))
        self.assertEqual("", dfl.usb_receiver([_vm("vm-srv", desktop="")]))

    def test_selectors_name_decks_only(self):
        self.assertEqual(
            ["0fd9:0080"], dfl.usb_deck_selectors([DECK, CLAVIER])
        )

    def test_identical_decks_are_pinned(self):
        self.assertEqual(
            ["3.5", "3.9"], dfl.usb_deck_selectors([DECK, JUMEAU])
        )

    def test_the_spec_carries_both_keys(self):
        form = {
            "res_label": "x1",
            "ssh_key": "",
            "install": None,
            "add_ssh_config": True,
            "parallelism": 1,
        }
        vide = dfl.build_spec([{"name": "vm-a"}], [], form)
        self.assertEqual([], vide["usb_hostdev"])
        self.assertFalse(vide["spice_usbredir"])
        form.update(usb_hostdev=["0fd9:0080"], spice_usbredir=True)
        plein = dfl.build_spec([{"name": "vm-a"}], [], form)
        self.assertEqual(["0fd9:0080"], plein["usb_hostdev"])
        self.assertTrue(plein["spice_usbredir"])


# --------------------------------------------------------------------------- #
# qemu_deploy.py : la spec jusqu'à la commande
# --------------------------------------------------------------------------- #
class LaSpecAtteintLaCommande(unittest.TestCase):
    def setUp(self):
        self.todo = TODO.__new__(TODO)

    def _spec(self, vms, **kw):
        spec = {
            "vms": vms,
            "install": None,
            "ssh_key": "",
            "vm_tools": (),
            "usb_hostdev": ["0fd9:0080"],
            "spice_usbredir": True,
        }
        spec.update(kw)
        return spec

    def _parts(self, vm, spec):
        return self.todo._qemu_deploy_parts_for(vm, spec, dry_run=True)

    def test_the_receiver_gets_the_deck_and_spice(self):
        vm = _vm("vm-a")
        parts = self._parts(vm, self._spec([vm]))
        self.assertEqual("0fd9:0080", parts[parts.index("--usb-hostdev") + 1])
        self.assertIn("--spice-usbredir", parts)

    def test_the_other_graphical_vms_get_spice_only(self):
        a, b = _vm("vm-a"), _vm("vm-b")
        parts = self._parts(b, self._spec([a, b]))
        self.assertNotIn("--usb-hostdev", parts)
        self.assertIn("--spice-usbredir", parts)

    def test_a_server_gets_nothing(self):
        vm = _vm("vm-a", desktop="")
        parts = self._parts(vm, self._spec([vm]))
        self.assertNotIn("--usb-hostdev", parts)
        self.assertNotIn("--spice-usbredir", parts)

    def test_an_arm64_desktop_gets_the_deck_without_spice(self):
        vm = _vm("vm-a", arch="arm64")
        parts = self._parts(vm, self._spec([vm]))
        self.assertIn("--usb-hostdev", parts)
        self.assertNotIn("--spice-usbredir", parts)

    def test_the_fleet_desktop_applies_when_the_vm_has_none(self):
        """La CLI pose le type une fois pour tout le parc."""
        vm = _vm("vm-a")
        del vm["desktop"]
        spec = self._spec([vm], desktop="gnome")
        self.assertEqual("vm-a", spec_usb_receiver(spec, vm))
        self.assertIn("--usb-hostdev", self._parts(vm, spec))

    def test_without_the_box_nothing_is_added(self):
        vm = _vm("vm-a")
        parts = self._parts(
            vm, self._spec([vm], usb_hostdev=[], spice_usbredir=False)
        )
        self.assertNotIn("--usb-hostdev", parts)
        self.assertNotIn("--spice-usbredir", parts)

    def test_recreating_replays_what_each_vm_received(self):
        a, b = _vm("vm-a"), _vm("vm-b")
        spec = self._spec([a, b])
        self.assertEqual(
            ["0fd9:0080"], TODO._qemu_spec_vm(spec, a)["usb_hostdev"]
        )
        reduite = TODO._qemu_spec_vm(spec, b)
        self.assertEqual([], reduite["usb_hostdev"])
        self.assertTrue(reduite["spice_usbredir"])
        self.assertNotIn("--usb-hostdev", self._parts(b, reduite))

    def test_the_proxmox_commands_follow_the_same_receiver(self):
        a, b = _vm("vm-a"), _vm("vm-b")
        spec = self._spec([a, b], usb_hostdev=True)
        self.assertIs(True, TODO._pve_spec_usb_hostdev(spec, a))
        self.assertEqual([], TODO._pve_spec_usb_hostdev(spec, b))


class LaQuestionEnLigne(unittest.TestCase):
    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.todo._qemu_host_usb_devices = lambda: [DECK, CLAVIER]

    def _demander(self, vms, reponse):
        vues = []

        def entree(prompt=""):
            vues.append(prompt)
            return reponse

        buf = io.StringIO()
        with (
            mock.patch("builtins.input", entree),
            redirect_stdout(buf),
        ):
            res = self.todo._qemu_ask_usb_decks(vms)
        return res, vues, buf.getvalue()

    def test_a_server_fleet_is_not_asked(self):
        res, vues, _ = self._demander([_vm("vm-a", desktop="")], "y")
        self.assertEqual(([], False), res)
        self.assertEqual([], vues)

    def test_yes_gives_the_selectors_and_spice(self):
        res, vues, sortie = self._demander([_vm("vm-a")], "y")
        self.assertEqual((["0fd9:0080"], True), res)
        self.assertEqual(1, len(vues))
        self.assertIn("Stream Deck MK.2", sortie)

    def test_the_default_is_no(self):
        res, _, _ = self._demander([_vm("vm-a")], "")
        self.assertEqual(([], False), res)


class LeServiceDeckDeLHote(unittest.TestCase):
    """_qemu_usb_hand_over_decks : le service deck de cet hôte, face aux
    decks passés à la création, suit la règle de l'attachement du menu."""

    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.service = {"installed": True, "active": True}
        self.lus = []
        self.commandes = []

        def etat(jump=""):
            self.lus.append(jump)
            return dict(self.service)

        self.todo._qemu_usb_service_state = etat
        self.todo._qemu_usb_exec = lambda cmd: self.commandes.append(cmd)

    def _spec(self, **kw):
        spec = {"vms": [_vm("vm-a")], "usb_hostdev": ["0fd9:0080"]}
        spec.update(kw)
        return spec

    def _remettre(self, spec, reponse):
        buf = io.StringIO()
        with (
            mock.patch("builtins.input", lambda prompt="": reponse),
            redirect_stdout(buf),
        ):
            self.todo._qemu_usb_hand_over_decks(spec)
        return buf.getvalue()

    def test_accepting_stops_the_service_before_the_creation(self):
        spec = self._spec()
        self._remettre(spec, "y")
        self.assertEqual(["0fd9:0080"], spec["usb_hostdev"])
        self.assertEqual(1, len(self.commandes))
        self.assertIn("stop", self.commandes[0])
        self.assertIn("erplibre-home-streamdeck.service", self.commandes[0])

    def test_refusing_keeps_the_decks_on_the_host(self):
        spec = self._spec(spice_usbredir=True)
        self._remettre(spec, "n")
        self.assertEqual([], spec["usb_hostdev"])
        self.assertTrue(spec["spice_usbredir"])
        self.assertEqual([], self.commandes)

    def test_an_idle_service_asks_nothing(self):
        self.service = {"installed": True, "active": False}
        spec = self._spec()
        with mock.patch("builtins.input", side_effect=AssertionError):
            self.todo._qemu_usb_hand_over_decks(spec)
        self.assertEqual(["0fd9:0080"], spec["usb_hostdev"])
        self.assertEqual([], self.commandes)

    def test_no_deck_or_no_receiver_reads_nothing(self):
        for spec in (
            self._spec(usb_hostdev=[]),
            self._spec(usb_hostdev=True),
            self._spec(vms=[_vm("vm-a", desktop="")]),
        ):
            self.todo._qemu_usb_hand_over_decks(spec)
        self.assertEqual([], self.lus)


# --------------------------------------------------------------------------- #
# La case du formulaire, sans écran
# --------------------------------------------------------------------------- #
class LaCase(unittest.TestCase):
    """usb_values / _usb_offered d'ExtrasMixin, widgets simulés."""

    def _porteur(self, vms, coche=True, devs=(DECK,), remote=False):
        from script.todo.deploy_form_extras import ExtrasMixin

        case = SimpleNamespace(value=coche, display=True)

        class Porteur(ExtrasMixin):
            pass

        porteur = Porteur()
        porteur.extras_init({"host_usb_devices": list(devs)})
        porteur.vms = vms
        porteur._usb_spice = not remote
        porteur._usb_remote = remote
        porteur._widget = lambda sel: case if sel == "#f_usb_deck" else None
        return porteur

    def test_checked_on_a_desktop_vm(self):
        self.assertEqual(
            {"usb_hostdev": ["0fd9:0080"], "spice_usbredir": True},
            self._porteur([_vm("vm-a")]).usb_values(),
        )

    def test_unchecked_gives_nothing(self):
        self.assertEqual(
            {"usb_hostdev": [], "spice_usbredir": False},
            self._porteur([_vm("vm-a")], coche=False).usb_values(),
        )

    def test_a_server_fleet_gives_nothing_even_checked(self):
        porteur = self._porteur([_vm("vm-a", desktop="")])
        self.assertFalse(porteur._usb_offered())
        self.assertEqual([], porteur.usb_values()["usb_hostdev"])

    def test_a_remote_node_defers_to_creation(self):
        """Proxmox : l'écran ne lit pas le nœud, la spec dit « les decks
        branchés » et pvesh les lit à la création. Jamais de SPICE."""
        self.assertEqual(
            {"usb_hostdev": True, "spice_usbredir": False},
            self._porteur([_vm("vm-a")], devs=(), remote=True).usb_values(),
        )


try:
    import textual  # noqa: F401

    TEXTUAL = True
except Exception:  # pragma: no cover - dépend de l'environnement
    TEXTUAL = False


@unittest.skipUnless(TEXTUAL, "Textual absent")
class LeFormulaire(unittest.TestCase):
    """L'écran QEMU/KVM : la case n'apparaît qu'avec une VM graphique, et
    cochée, elle porte les decks préchargés dans la spec."""

    def _releve(self, desktop):
        import asyncio

        from script.todo.qemu_deploy_form import run_deploy_form

        todo = TODO.__new__(TODO)
        todo._qemu_list_domains = lambda: []
        todo._qemu_branch_list = lambda: ["develop", "master"]
        todo._qemu_host_usb_devices = lambda: [DECK]
        ctx = todo._qemu_form_context(todo._qemu_import_module())
        ctx["defaults"] = dict(ctx["defaults"], desktop=desktop)
        vu = {}

        async def scenario():
            from textual.widgets import Checkbox, SelectionList

            app = run_deploy_form(ctx, run_app=False)
            async with app.run_test(size=(220, 70)) as pilote:
                await pilote.pause()
                liste = app.query_one(SelectionList)
                liste.select(liste.get_option_at_index(0).value)
                await pilote.pause()
                await pilote.pause()
                case = app.query_one("#f_usb_deck", Checkbox)
                vu["display"] = case.display
                case.value = True
                await pilote.pause()
                vu["spec"] = app._form_values()

        with redirect_stdout(io.StringIO()):
            asyncio.run(scenario())
        return vu

    def test_hidden_for_a_server(self):
        vu = self._releve("")
        self.assertFalse(vu["display"])
        self.assertEqual([], vu["spec"]["usb_hostdev"])
        self.assertFalse(vu["spec"]["spice_usbredir"])

    def test_shown_and_carried_for_a_desktop(self):
        vu = self._releve("gnome")
        self.assertTrue(vu["display"])
        self.assertEqual(["0fd9:0080"], vu["spec"]["usb_hostdev"])
        self.assertTrue(vu["spec"]["spice_usbredir"])


if __name__ == "__main__":
    unittest.main()
