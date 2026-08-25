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
from script.todo.todo_i18n import t  # noqa: E402

# Sorties RÉELLES relevées sur l'hôte d'essai.
PVEVERSION = (
    "pve-manager/9.2.11/f6997e698c7933ea (running kernel: 7.0.14-12-pve)"
)
# Ce que ssh écrit sur stderr à chaque connexion d'un hôte en
# UserKnownHostsFile=/dev/null. Ce n'est pas un diagnostic.
AVERTISSEMENT = (
    "Warning: Permanently added '192.168.123.227' (ED25519) to the list "
    "of known hosts.\n"
)
SPEC_VM = {
    "name": "essai",
    "memory": 512,
    "vcpus": 1,
    "disk": "4G",
    "storage": "local",
    "bridge": "vmbr0",
    "image": "debian-13.qcow2",
    "user": "erplibre",
    "start": True,
}
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


class TestLeBruitDeSsh(unittest.TestCase):
    """Ce que ssh ajoute n'est pas la réponse de l'hôte.

    Le cas vécu, du début à la fin : « ip -o link show type bridge » ne rend
    RIEN sur un hôte sans pont, la sortie ne contient donc que
    l'avertissement de ssh sur la clé — que `parse_bridges` a pris pour un nom
    de pont. « (ED25519) » s'est retrouvé dans « --net0 virtio,bridge=… »,
    enrobé de « sudo sh -c », et dash a répondu :

        sh: 1: Syntax error: "(" unexpected

    Trois lignes de code entre la cause et un message incompréhensible.
    """

    def test_the_warning_never_becomes_a_bridge(self):
        self.assertEqual(pve.parse_bridges(AVERTISSEMENT), [])

    def test_real_bridges_are_still_read(self):
        vrai = (
            "2: vmbr0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc "
            "noqueue state UP mode DEFAULT group default qlen 1000\\    "
            "link/ether bc:24:11:00:00:01\n"
            "3: vmbr1: <BROADCAST,MULTICAST> mtu 1500 qdisc noop state DOWN\n"
        )
        self.assertEqual(
            pve.parse_bridges(AVERTISSEMENT + vrai), ["vmbr0", "vmbr1"]
        )

    def test_a_veth_pair_keeps_only_its_own_name(self):
        ligne = "7: fwln100i0@fwpr100p0: <BROADCAST,MULTICAST,UP> mtu 1500\n"
        self.assertEqual(pve.parse_bridges(ligne), ["fwln100i0"])

    def test_the_noise_is_stripped_at_the_source(self):
        for bruit in (
            AVERTISSEMENT,
            "Pseudo-terminal will not be allocated because stdin is not a terminal.\n",
            "Connection to 10.0.0.5 closed.\n",
            "Shared connection to 10.0.0.5 closed.\n",
            "mesg: ttyname failed: Inappropriate ioctl for device\n",
        ):
            self.assertEqual(pve.strip_ssh_noise(bruit), "")
        self.assertEqual(
            pve.strip_ssh_noise(AVERTISSEMENT + "vmbr0\n"), "vmbr0\n"
        )

    def test_the_answer_survives_the_filter(self):
        # Un filtre qui mange la réponse serait pire que le bruit.
        self.assertIn(
            "pve-manager", pve.strip_ssh_noise(AVERTISSEMENT + PVEVERSION)
        )


class TestLeNoyau(unittest.TestCase):
    """Tant que l'hôte tourne le noyau de la distribution, il n'a ni module
    bridge ni table NAT : ifupdown2 répond « Operation not supported », et
    quand /run/network manque il répond même « Another instance of this
    program is already running » — un mensonge. Vécu sur l'hôte d'essai."""

    def test_the_running_kernel_is_read_from_pveversion(self):
        self.assertEqual(
            pve.parse_kernel(
                "pve-manager/9.2.11/abc (running kernel: 6.12.95+deb13-cloud-amd64)"
            ),
            "6.12.95+deb13-cloud-amd64",
        )
        self.assertEqual(
            pve.parse_kernel(
                "pve-manager/9.2.11/abc (running kernel: 7.0.14-12-pve)"
            ),
            "7.0.14-12-pve",
        )
        self.assertEqual(pve.parse_kernel("n'importe quoi"), "")

    def test_the_bridge_creates_the_lock_directory_first(self):
        # Sans /run/network, ifupdown2 accuse une autre instance et le pont
        # ne monte jamais.
        montee = pve.bridge_setup_cmds("vmbr0", "10.10.10.1/24", "enp1s0")[-1]
        self.assertIn("mkdir -p /run/network", montee)
        # Et l'erreur d'IFUP n'est pas masquée : c'est elle qui explique.
        # Porté sur l'appel lui-même, et non sur toute la ligne : le repli qui
        # suit sonde légitimement (« ip link show », « iptables -C »), et
        # interdire « 2>/dev/null » partout lui interdisait d'exister.
        ifup = montee[montee.index("ifup ") :].split("||")[0]
        self.assertNotIn("2>", ifup)


class TestLeDns(unittest.TestCase):
    """« --ipconfig0 » ne porte pas le DNS : une VM en adresse fixe se
    retrouvait sans résolveur. Mesuré sur la VM d'essai — le NAT routait, mais
    « getent hosts deb.debian.org » ne rendait rien."""

    def test_the_resolved_stub_is_useless_to_a_guest(self):
        self.assertEqual(pve.parse_nameservers("nameserver 127.0.0.53"), [])

    def test_real_resolvers_are_kept_in_order(self):
        self.assertEqual(
            pve.parse_nameservers(
                "nameserver 192.168.123.1\nnameserver 1.1.1.1\n"
                "nameserver 192.168.123.1\n"
            ),
            ["192.168.123.1", "1.1.1.1"],
        )

    def test_a_static_address_gets_the_resolvers(self):
        spec = dict(
            SPEC_VM,
            ipconfig="ip=10.10.10.150/24,gw=10.10.10.1",
            nameservers=["192.168.123.1"],
        )
        ci = [c for c in pve.create_cmds(100, spec) if "--ciuser" in c][0]
        self.assertIn("--nameserver 192.168.123.1", ci)

    def test_dhcp_needs_none(self):
        # Le bail DHCP porte déjà le DNS.
        spec = dict(SPEC_VM, ipconfig="ip=dhcp", nameservers=["192.168.123.1"])
        ci = [c for c in pve.create_cmds(100, spec) if "--ciuser" in c][0]
        self.assertNotIn("--nameserver", ci)


class TestLAvancement(unittest.TestCase):
    """Cent lignes « transferred … » enterraient l'erreur utile : le journal du
    premier essai réel faisait 136 lignes pour 34 utiles."""

    def test_a_burst_collapses_to_one_line(self):
        texte = (
            "Formatting 'disk.raw'\n"
            + "".join(
                f"transferred {i}.0 MiB of 3.0 GiB ({i}%)\n" for i in range(50)
            )
            + "scsi0: successfully created disk\n"
        )
        propre = pve.collapse_progress(texte)
        self.assertIn("50 lignes d'avancement", propre)
        self.assertIn("successfully created disk", propre)
        self.assertLess(len(propre.splitlines()), 6)

    def test_what_is_not_progress_is_untouched(self):
        texte = "400 Parameter verification failed.\nnet0: invalid format\n"
        self.assertEqual(pve.collapse_progress(texte).strip(), texte.strip())


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
        # Deux appels : « pveversion », puis la sonde qui demande à ssh s'il
        # passe — c'est elle qui distingue les deux pannes.
        host, sortie = self._confirm(
            [(127, "bash: pveversion: not found"), (0, "")]
        )
        self.assertIsNone(host)
        self.assertIn("pveversion", sortie)

    def test_a_reachable_machine_without_proxmox_says_exactly_that(self):
        """Le cas rapporté : « je n'arrive pas à me connecter, pourtant il est
        accessible ». La machine répondait ; c'est Proxmox qui manquait, et le
        message parlait d'injoignabilité."""
        host, sortie = self._confirm(
            [
                (127, AVERTISSEMENT + "bash: pveversion: command not found"),
                (0, AVERTISSEMENT),
            ]
        )
        self.assertIsNone(host)
        # Comparé à la TRADUCTION, pas à un mot français : la langue de
        # l'interface se change (EL_LANG), et un test qui la suppose échoue
        # pour une raison qui n'a rien à voir avec ce qu'il vérifie.
        self.assertIn(t("Reachable, but Proxmox VE is not there:"), sortie)
        self.assertIn("install_proxmox.sh", sortie)
        # Et surtout : ne plus envoyer chercher un problème de réseau.
        self.assertNotIn(t("SSH does not get through:"), sortie)

    def test_an_unreachable_machine_says_ssh_does_not_get_through(self):
        panne = "ssh: connect to host 10.0.0.9 port 22: No route to host"
        host, sortie = self._confirm([(255, panne), (255, panne)])
        self.assertIsNone(host)
        self.assertIn("No route to host", sortie)
        self.assertNotIn("install_proxmox.sh", sortie)

    def test_the_ssh_key_warning_is_never_shown_as_the_error(self):
        # Affichée comme preuve, elle envoyait chercher un problème de clé
        # d'hôte qui n'existait pas — c'est ce qu'on voyait dans le rapport.
        host, sortie = self._confirm(
            [(127, AVERTISSEMENT), (0, AVERTISSEMENT)]
        )
        self.assertIsNone(host)
        self.assertNotIn("Permanently added", sortie)

    def test_only_the_lines_that_teach_something_are_kept(self):
        self.assertEqual(
            TODO._pve_clean_output(
                AVERTISSEMENT + "\nbash: pveversion: command not found\n"
            ),
            ["bash: pveversion: command not found"],
        )
        self.assertEqual(TODO._pve_clean_output(AVERTISSEMENT), [])
        self.assertEqual(TODO._pve_clean_output(""), [])

    def test_the_install_hint_pipes_the_repo_script(self):
        # Le script est autonome : « bash -s » suffit, rien à copier d'abord.
        indice = self._todo()._pve_install_hint({"target": "pve1"})
        self.assertIn(TODO.PVE_INSTALL_SCRIPT, indice)
        self.assertIn("ssh pve1 sudo bash -s", indice)

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
        """L'équivalent des dix-sept commandes, plus le choix de l'hôte.

        Le menu vit dans son propre fichier depuis le refactor : la cohérence
        numéro/dispatch, elle, est vérifiée par le socle commun de
        test_todo_menu.py, qui sert les deux menus.
        """
        src = open("script/todo/proxmox_menu.py", encoding="utf-8").read()
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


class TestLaTableNat(unittest.TestCase):
    """« Table does not exist » : six lignes d'iptables et « code de retour 1 »,
    après avoir déjà écrit la strophe dans /etc/network/interfaces.

    Rien dans ce bruit ne dit qu'il faut redémarrer. Et le cas n'a rien
    d'exotique : notre propre install_proxmox.sh pose le noyau Proxmox sans
    redémarrer — lancé par ssh, un reboot couperait la session. Une Proxmox
    imbriquée fraîchement installée est donc TOUJOURS sur le noyau cloud de
    Debian, qui est dépouillé de tout netfilter.

    On demande donc à la table NAT elle-même, et non au NOM du noyau : « -pve »
    est un indice, pas une preuve."""

    def _sortie(self, kernel, nat, pve_kernel=""):
        return (
            f"{kernel}\n---ERPLIBRE-NAT---\n"
            f"{'NAT-OK' if nat else 'NAT-KO'}\n"
            f"---ERPLIBRE-PVE-KERNEL---\n{pve_kernel}\n"
        )

    def test_a_working_host(self):
        lu = pve.parse_nat_check(
            self._sortie("7.0.14-14-pve", True, "7.0.14-14-pve")
        )
        self.assertTrue(lu["nat"])
        self.assertEqual(lu["kernel"], "7.0.14-14-pve")

    def test_the_cloud_kernel_waiting_for_a_reboot(self):
        # L'état exact rapporté : le noyau Proxmox est POSÉ, pas amorcé.
        lu = pve.parse_nat_check(
            self._sortie("6.12.101+deb13-cloud-amd64", False, "7.0.14-14-pve")
        )
        self.assertFalse(lu["nat"])
        self.assertEqual(lu["pve_kernel"], "7.0.14-14-pve")

    def test_an_unfinished_install_has_no_pve_kernel(self):
        lu = pve.parse_nat_check(
            self._sortie("6.12.101+deb13-cloud-amd64", False)
        )
        self.assertFalse(lu["nat"])
        self.assertEqual(lu["pve_kernel"], "")

    def test_ssh_noise_does_not_become_a_kernel(self):
        brut = (
            "Warning: Permanently added 'x' (ED25519) to the list of known"
            " hosts.\n" + self._sortie("7.0.14-14-pve", True, "7.0.14-14-pve")
        )
        self.assertEqual(pve.parse_nat_check(brut)["kernel"], "7.0.14-14-pve")

    def test_the_probe_asks_the_table_not_the_name(self):
        self.assertIn("iptables -t nat", pve.NAT_CHECK_CMD)
        self.assertIn("uname -r", pve.NAT_CHECK_CMD)


class TestLeReseauDuPontInterne(unittest.TestCase):
    """Le pont interne avait une adresse CODÉE EN DUR, 10.10.10.1/24.

    Un Proxmox dans un Proxmox hérite du réseau interne de son parent : la VM
    vivait en 10.10.10.152 avec 10.10.10.1 pour PASSERELLE. Lui demander de
    poser 10.10.10.1/24 sur son propre pont, c'est prendre l'adresse de sa
    passerelle et rendre tout le /24 local — la machine s'isole au milieu de
    la commande qui la configure. Vécu : « ifup » n'a jamais rendu la main, et
    la VM ne répondait plus ni en ssh ni en ping."""

    IMBRIQUE = (
        "2: eth0    inet 10.10.10.152/24 brd 10.10.10.255 scope global eth0\n"
        "default via 10.10.10.1 dev eth0 onlink\n"
        "10.10.10.0/24 dev eth0 proto kernel scope link src 10.10.10.152\n"
    )

    def test_a_nested_host_gets_another_subnet(self):
        self.assertNotEqual(
            pve.pick_internal_cidr(self.IMBRIQUE), "10.10.10.1/24"
        )
        self.assertEqual(
            pve.pick_internal_cidr(self.IMBRIQUE), "10.10.20.1/24"
        )

    def test_a_fresh_host_keeps_the_usual_one(self):
        vierge = "1: lo    inet 127.0.0.1/8 scope host lo\n"
        self.assertEqual(pve.pick_internal_cidr(vierge), "10.10.10.1/24")

    def test_a_route_alone_is_enough_to_collide(self):
        # Une route sans adresse locale suffit : c'est le cas exact de la
        # route par défaut « via 10.10.10.1 ».
        seule = "default via 10.10.10.1 dev eth0\n"
        self.assertNotEqual(pve.pick_internal_cidr(seule), "10.10.10.1/24")

    def test_a_supernet_rules_out_everything_under_it(self):
        # « 10.0.0.0/8 » couvre tous les candidats en 10.x. Un test sur les
        # trois premiers octets l'aurait raté.
        choisi = pve.pick_internal_cidr("10.0.0.0/8 dev x\n")
        self.assertFalse(choisi.startswith("10."), choisi)

    def test_when_nothing_is_free_it_says_so(self):
        tout = "\n".join(
            c.replace("1/24", "0/24") for c in pve.INTERNAL_CANDIDATES
        )
        self.assertEqual(pve.pick_internal_cidr(tout), "")

    def test_the_chosen_subnet_reaches_every_command(self):
        cmds = pve.bridge_setup_cmds(cidr="10.10.20.1/24", uplink="eth0")
        texte = "\n".join(cmds)
        self.assertIn("address 10.10.20.1/24", texte)
        self.assertIn("10.10.20.0/24", texte)
        self.assertNotIn("10.10.10.", texte)


class TestLeRepliQuiNeCoupePasLaLigne(unittest.TestCase):
    """« ifreload -a » en repli rechargeait TOUTES les interfaces.

    Y compris celle qui porte la session ssh — et sur une image cloud
    l'interface principale est décrite ailleurs (interfaces.d, netplan), donc
    ifupdown2 la descend sans la remonter. Le repli monte donc le pont à la
    main, sans toucher à rien d'autre."""

    def test_ifreload_is_gone(self):
        texte = "\n".join(pve.bridge_setup_cmds(uplink="eth0"))
        self.assertNotIn("ifreload", texte)

    def test_the_fallback_builds_the_bridge_itself(self):
        derniere = pve.bridge_setup_cmds(cidr="10.10.20.1/24", uplink="eth0")[
            -1
        ]
        self.assertIn("ifup vmbr0 ||", derniere)
        self.assertIn("ip link add vmbr0 type bridge", derniere)
        self.assertIn("ip addr add 10.10.20.1/24 dev vmbr0", derniere)
        self.assertIn("ip link set vmbr0 up", derniere)

    def test_the_masquerade_rule_is_idempotent(self):
        # « -C » avant « -A » : rejouée, la commande n'empile pas les règles.
        derniere = pve.bridge_setup_cmds(uplink="eth0")[-1]
        self.assertIn("iptables -t nat -C POSTROUTING", derniere)
        self.assertLess(
            derniere.index("-t nat -C"), derniere.index("-t nat -A")
        )

    def test_the_fallback_is_valid_shell(self):
        """Exécuté pour de vrai, ip/iptables/ifup bouchonnés.

        Un repli qu'on ne sait pas exécuter s'ouvre le jour où il casse — et
        celui-là tourne sur une machine qu'on ne peut plus joindre s'il rate.
        """
        import subprocess

        derniere = pve.bridge_setup_cmds(cidr="10.10.20.1/24", uplink="eth0")[
            -1
        ]
        bouchons = (
            'ip() { [ "$1 $2" = "link show" ] && return 1; return 0; }\n'
            "iptables() { return 1; }\n"
            "ifup() { return 1; }\n"
            "mkdir() { :; }\n"
        )
        res = subprocess.run(
            ["bash", "-c", bouchons + derniere],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(res.stderr, "", res.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=1)
