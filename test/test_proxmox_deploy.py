#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Déployer sur un hôte Proxmox : l'hyperviseur est AILLEURS.

Toute la différence avec QEMU/KVM tient là. Rien ne s'exécute sur la machine
locale : il faut d'abord savoir OÙ, puis tout envoyer par SSH. Ces tests
gardent ce qui a été appris contre un hôte réel (Proxmox VE 9.2.11 dans une VM
libvirt), une panne après l'autre :

- « qm » exige root. La voie « VM QEMU locale » ne donne que l'accès
  d'erplibre : il faut sudo, et l'enrober AUTOUR de toute la commande — les
  commandes de ce module sont des suites et des redirections, et « sudo cmd »
  n'élèverait que le premier mot.
- Une Proxmox installée SUR Debian n'a AUCUN pont. On en propose un INTERNE :
  ajouter l'interface physique à un pont déplace l'adresse de l'hôte et coupe
  la session SSH — à distance, c'est sans retour.
- Sur un pont interne, aucun DHCP ne répond : l'adresse doit être fixe, et
  elle est alors connue AVANT le démarrage. La chercher ensuite était absurde.
- L'agent invité n'est pas dans l'image cloud Debian : le voisinage de l'hôte
  (« ip neigh ») est le seul repli, et il a trouvé l'adresse là où l'agent
  répondait « not running ».
"""

import shlex
import subprocess
import sys
import unittest
from unittest import mock

sys.argv = ["todo.py"]
from script.proxmox import proxmox_deploy as pve  # noqa: E402
from script.todo.todo import TODO  # noqa: E402

# Sorties RÉELLES relevées sur l'hôte d'essai.
PVEVERSION = (
    "pve-manager/9.2.11/f6997e698c7933ea (running kernel: 7.0.14-12-pve)"
)
QM_LIST = """      VMID NAME                 STATUS     MEM(MB)    BOOTDISK(GB) PID
       100 vm-essai             running    2048              16.00 2726
       101 avec un espace       stopped    4096              32.00 0
"""
PVESM = """Name             Type     Status           Total            Used       Available        %
local             dir     active        32815812         6873084        24559348   20.94%
sauvegarde        dir   inactive        99999999               0        99999999    0.00%
"""
NEIGH = """192.168.123.1 dev enp1s0 lladdr 52:54:00:cd:73:ef REACHABLE
10.10.10.150 dev vmbr0 lladdr bc:24:11:93:da:22 REACHABLE
"""
QM_CONFIG = """boot: order=scsi0
memory: 2048
net0: virtio=BC:24:11:93:DA:22,bridge=vmbr0
scsi0: local:100/vm-100-disk-0.raw,discard=on,size=16G,ssd=1
"""
INTERFACES = """auto lo
iface lo inet loopback

iface enp1s0 inet manual

auto vmbr0
iface vmbr0 inet static
    address 10.10.10.1/24
    bridge-ports none
    bridge-stp off

auto vmbr1
iface vmbr1 inet manual
    bridge-ports enp2s0
"""


class TestLectureDesSorties(unittest.TestCase):
    def test_the_version_proves_it_is_a_proxmox(self):
        """Une adresse saisie à la main peut être n'importe quelle machine :
        sans cette preuve, la première commande « qm » échouerait sur un
        « command not found » qui n'explique rien."""
        self.assertEqual("9.2.11", pve.parse_pveversion(PVEVERSION))
        self.assertEqual(
            "", pve.parse_pveversion("bash: pveversion: not found")
        )

    def test_a_vm_name_with_spaces_is_read_whole(self):
        """« qm list » sépare par des espaces, et un nom peut en contenir : on
        découpe par les deux bouts, le milieu est le nom."""
        vms = pve.parse_qm_list(QM_LIST)
        self.assertEqual([100, 101], [v["vmid"] for v in vms])
        self.assertEqual("avec un espace", vms[1]["name"])
        self.assertEqual("running", vms[0]["status"])

    def test_the_header_is_not_a_vm(self):
        self.assertEqual([], pve.parse_qm_list("      VMID NAME  STATUS\n"))
        self.assertEqual([], pve.parse_qm_list(""))

    def test_only_active_storages_count_and_kib_become_bytes(self):
        st = pve.parse_storages(PVESM)
        self.assertEqual(["local", "sauvegarde"], [s["name"] for s in st])
        self.assertTrue(st[0]["actif"])
        self.assertFalse(st[1]["actif"])
        self.assertEqual(24559348 * 1024, st[0]["avail"])

    def test_bridges_are_read_without_their_at_suffix(self):
        texte = "3: vmbr0: <BROADCAST,UP>\n4: vmbr1@if2: <BROADCAST>\n"
        self.assertEqual(["vmbr0", "vmbr1"], pve.parse_bridges(texte))

    def test_the_guest_agent_answer_drops_loopback_and_ipv6(self):
        json_txt = (
            '[{"name":"lo","ip-addresses":[{"ip-address-type":"ipv4",'
            '"ip-address":"127.0.0.1"}]},{"name":"eth0","ip-addresses":['
            '{"ip-address-type":"ipv4","ip-address":"10.10.10.150"},'
            '{"ip-address-type":"ipv6","ip-address":"fe80::1"}]}]'
        )
        self.assertEqual(["10.10.10.150"], pve.parse_guest_ips(json_txt))

    def test_a_missing_agent_is_not_a_crash(self):
        """Sa réponse n'est pas du JSON : « QEMU guest agent is not running »."""
        self.assertEqual(
            [], pve.parse_guest_ips("QEMU guest agent is not running")
        )

    def test_the_mac_links_a_vm_to_its_address(self):
        """Le seul lien quand l'agent manque, et l'image cloud Debian ne
        l'embarque pas."""
        mac = pve.mac_from_config(QM_CONFIG)
        self.assertEqual("bc:24:11:93:da:22", mac)
        self.assertEqual("10.10.10.150", pve.ip_from_neigh(NEIGH, mac))

    def test_an_unknown_mac_finds_nothing(self):
        self.assertEqual("", pve.ip_from_neigh(NEIGH, "de:ad:be:ef:00:00"))
        self.assertEqual("", pve.ip_from_neigh(NEIGH, ""))

    def test_a_lan_bridge_and_an_internal_one_are_told_apart(self):
        ponts = pve.parse_bridge_config(INTERFACES)
        self.assertEqual("", ponts["vmbr0"]["ports"])
        self.assertEqual("10.10.10.1/24", ponts["vmbr0"]["address"])
        self.assertEqual("enp2s0", ponts["vmbr1"]["ports"])

    def test_orphans_are_the_volumes_no_vm_claims(self):
        liste = (
            "Volid                     Format  Type      Size VMID\n"
            "local:100/vm-100-disk-0.raw raw   images 17179869184 100\n"
            "local:999/vm-999-disk-0.raw raw   images  8589934592 999\n"
        )
        orph = pve.parse_orphans(liste, [100])
        self.assertEqual(1, len(orph))
        self.assertIn("999", orph[0][0])


class TestLesChoix(unittest.TestCase):
    def test_the_vmid_skips_the_taken_ones(self):
        """Proxmox refuse un VMID pris, et le dit APRÈS le téléchargement de
        l'image : on choisit donc avant, d'après ce que l'hôte déclare."""
        self.assertEqual(
            102, pve.next_vmid([{"vmid": 100}, {"vmid": 101}, {"vmid": 103}])
        )
        self.assertEqual(100, pve.next_vmid([]))

    def test_the_storage_is_the_freest_active_one(self):
        st = pve.parse_storages(PVESM)
        self.assertEqual("local", pve.pick_storage(st))

    def test_an_unknown_storage_is_refused_not_guessed(self):
        """« local-lvm » n'existe pas partout : un repli deviné ferait échouer
        « qm set » après le téléchargement de l'image."""
        self.assertEqual(
            "", pve.pick_storage(pve.parse_storages(PVESM), "nas")
        )

    def test_vmbr0_wins_when_it_exists(self):
        self.assertEqual("vmbr0", pve.pick_bridge(["vmbr9", "vmbr0"]))
        self.assertEqual("br-lan", pve.pick_bridge(["br-lan"]))
        self.assertEqual("", pve.pick_bridge([]))


class TestLesCommandes(unittest.TestCase):
    def _spec(self, **extra):
        base = {
            "name": "vm-essai",
            "memory": 2048,
            "vcpus": 2,
            "disk": "12G",
            "storage": "local",
            "bridge": "vmbr0",
            "image": "debian-13-genericcloud-amd64.qcow2",
            "sshkey_path": "/root/.ssh/erplibre-deploy.pub",
            "ipconfig": "ip=10.10.10.150/24,gw=10.10.10.1",
        }
        base.update(extra)
        return base

    def test_the_sequence_is_in_the_order_proxmox_needs(self):
        cmds = pve.create_cmds(100, self._spec())
        joint = "\n".join(cmds)
        self.assertTrue(cmds[0].startswith("qm create 100"))
        self.assertIn("import-from=", joint)
        self.assertIn(":cloudinit", joint)
        self.assertIn("--boot order=scsi0", joint)
        self.assertIn("qm resize 100 scsi0 12G", joint)
        self.assertTrue(cmds[-1].endswith("qm start 100"))

    def test_the_agent_and_the_serial_console_are_asked_for(self):
        """Sans agent, aucune adresse ; sans serial0, « qm terminal » est
        inutilisable et il ne reste que l'interface web."""
        cmd = pve.create_cmds(100, self._spec())[0]
        self.assertIn("--agent enabled=1", cmd)
        self.assertIn("--serial0 socket", cmd)

    def test_a_name_with_a_space_cannot_break_the_command(self):
        """Le nom vient d'une saisie : découpée par le shell, elle doit rester
        UN argument. « rm » ne doit jamais devenir une commande."""
        mechant = "vm essai; rm -rf /"
        cmds = pve.create_cmds(100, self._spec(name=mechant))
        args = shlex.split(cmds[0])
        self.assertIn(mechant, args)
        self.assertNotIn("rm", args)

    def test_destroy_stops_first_and_purges(self):
        cmds = pve.destroy_cmds(100)
        self.assertIn("qm stop 100", cmds[0])
        self.assertIn("--purge 1", cmds[1])

    def test_the_image_is_fetched_once_on_the_host(self):
        cmd = pve.image_fetch_cmd("https://x/deb.qcow2", "deb.qcow2")
        self.assertIn("if [ -s", cmd)
        self.assertIn("wget", cmd)

    def test_the_internal_bridge_never_touches_a_physical_nic(self):
        """Le point le plus important de ce module : ajouter l'interface au
        pont déplace l'adresse de l'hôte et coupe la session SSH — à distance,
        sans retour."""
        cmds = pve.bridge_setup_cmds(uplink="enp1s0")
        joint = "\n".join(cmds)
        self.assertIn("bridge-ports none", joint)
        self.assertNotIn("bridge-ports enp1s0", joint)
        self.assertIn("MASQUERADE", joint)
        self.assertIn("ip_forward", joint)

    def test_the_bridge_stanza_is_added_only_once(self):
        cmds = pve.bridge_setup_cmds()
        self.assertIn("grep -qE", cmds[0])
        self.assertIn("||", cmds[0])

    def test_an_internal_bridge_gets_a_static_address(self):
        """Aucun DHCP n'y répondrait : la VM resterait muette."""
        ponts = pve.parse_bridge_config(INTERFACES)
        self.assertEqual(
            "ip=10.10.10.150/24,gw=10.10.10.1",
            pve.ipconfig_for(ponts["vmbr0"], 100),
        )

    def test_a_lan_bridge_gets_dhcp(self):
        ponts = pve.parse_bridge_config(INTERFACES)
        self.assertEqual("ip=dhcp", pve.ipconfig_for(ponts["vmbr1"], 100))

    def test_two_vms_do_not_share_an_address(self):
        ponts = pve.parse_bridge_config(INTERFACES)
        a = pve.ipconfig_for(ponts["vmbr0"], 100)
        b = pve.ipconfig_for(ponts["vmbr0"], 101)
        self.assertNotEqual(a, b)

    def test_a_static_address_is_known_before_boot(self):
        self.assertEqual(
            "10.10.10.150",
            pve.ip_from_ipconfig("ip=10.10.10.150/24,gw=10.10.10.1"),
        )
        self.assertEqual("", pve.ip_from_ipconfig("ip=dhcp"))


class TestLePrivilege(unittest.TestCase):
    def test_the_whole_command_is_wrapped_not_just_its_first_word(self):
        """« sudo mkdir && if … fi » n'élèverait que le mkdir, et la
        redirection resterait celle du shell non privilégié : « permission
        denied » sur /root ou /boot/efi."""
        compose = "mkdir -p /root/.ssh && printf x > /root/.ssh/k"
        enrobe = pve.wrap_privilege(compose, "sudo ")
        self.assertTrue(enrobe.startswith("sudo sh -c "))
        self.assertIn("printf x > /root/.ssh/k", enrobe)

    def test_without_sudo_the_command_is_untouched(self):
        self.assertEqual("qm list", pve.wrap_privilege("qm list", ""))

    def test_ssh_never_asks_a_question_it_cannot_show(self):
        """BatchMode : une invite de mot de passe dans un menu bloquerait sans
        rien afficher."""
        argv = pve.ssh_argv({"target": "root@h"}, "qm list")
        self.assertIn("BatchMode=yes", argv)
        self.assertIn("ConnectTimeout=10", " ".join(argv))

    def test_the_jump_and_the_port_travel(self):
        argv = pve.ssh_argv(
            {"target": "root@h", "jump": "rebond", "port": "2222"}, "x"
        )
        self.assertIn("-J", argv)
        self.assertIn("rebond", argv)
        self.assertIn("-p", argv)
        self.assertIn("2222", argv)

    def test_a_console_gets_a_tty_and_no_batchmode(self):
        argv = pve.ssh_argv({"target": "root@h"}, "qm terminal 100", tty=True)
        self.assertIn("-t", argv)
        self.assertNotIn("BatchMode=yes", argv)


class TestChoixDeLHote(unittest.TestCase):
    """La question propre à Proxmox : sur QUELLE machine ?"""

    def _todo(self):
        todo = TODO.__new__(TODO)
        todo._pve_remember_host = lambda h: None
        return todo

    def test_an_unknown_host_key_is_recognised(self):
        for texte in (
            "Host key verification failed.",
            "The authenticity of host '10.0.0.1' can't be established.",
            "No ED25519 host key is known for 10.0.0.1",
        ):
            self.assertTrue(TODO._pve_hostkey_missing(texte), texte)
        self.assertFalse(TODO._pve_hostkey_missing("Permission denied"))

    def _confirm(self, reponses):
        """reponses : [(code, sortie)] pour chaque appel à pve.run."""
        it = iter(reponses)
        with mock.patch.object(
            pve, "run", side_effect=lambda *a, **k: next(it)
        ):
            import contextlib
            import io

            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                host = self._todo()._pve_confirm_host(
                    {"target": "erplibre@10.0.0.5", "jump": ""}
                )
            return host, out.getvalue()

    def test_a_non_proxmox_host_is_refused_with_what_was_seen(self):
        host, sortie = self._confirm([(127, "bash: pveversion: not found")])
        self.assertIsNone(host)
        self.assertIn("pveversion", sortie)

    def test_a_non_root_access_gets_sudo(self):
        """C'est le cas de la voie « VM QEMU locale » : cloud-init crée
        erplibre, pas root."""
        host, _s = self._confirm([(0, PVEVERSION), (0, "1000\n"), (0, "")])
        self.assertEqual("sudo ", host["sudo"])
        self.assertEqual("9.2.11", host["version"])

    def test_root_needs_no_sudo(self):
        host, _s = self._confirm([(0, PVEVERSION), (0, "0\n")])
        self.assertEqual("", host["sudo"])

    def test_without_root_nor_passwordless_sudo_it_stops(self):
        """Un sudo qui réclame un mot de passe bloquerait chaque commande du
        menu sur une invite que personne ne voit."""
        host, sortie = self._confirm(
            [
                (0, PVEVERSION),
                (0, "1000\n"),
                (1, "sudo: a password is required"),
            ]
        )
        self.assertIsNone(host)
        self.assertIn("root", sortie)


class TestLeMenu(unittest.TestCase):
    def test_proxmox_sits_right_under_qemu_in_the_deploy_menu(self):
        src = open("script/todo/todo.py", encoding="utf-8").read()
        i_qemu = src.index('"QEMU/KVM - Deploy an Ubuntu VM (libvirt)"')
        i_pve = src.index('"Proxmox VE - Deploy a VM on a remote host"')
        i_ntfy = src.index('"Deploy - Install NTFY notification server"')
        self.assertLess(i_qemu, i_pve)
        self.assertLess(i_pve, i_ntfy)

    def test_the_dispatch_follows_the_list(self):
        src = open("script/todo/todo.py", encoding="utf-8").read()
        self.assertIn(
            'elif status == "6":\n                self.prompt_execute_proxmox()',
            src,
        )
        self.assertIn(
            'elif status == "7":\n                self._deploy_ntfy_server()',
            src,
        )

    def test_every_qemu_entry_has_its_proxmox_counterpart(self):
        """L'équivalent des dix-sept commandes, plus le choix de l'hôte."""
        src = open("script/todo/todo.py", encoding="utf-8").read()
        debut = src.index("    def prompt_execute_proxmox(self):")
        bloc = src[debut : src.index("    def _pve_fetch_image(self):")]
        for n in range(1, 19):
            self.assertIn(f'elif status == "{n}":', bloc, f"entrée {n}")

    def test_the_script_is_valid_python(self):
        res = subprocess.run(
            [
                sys.executable,
                "-c",
                "import ast;ast.parse(open('script/proxmox/proxmox_deploy.py',encoding='utf-8').read())",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, res.returncode, res.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=1)
