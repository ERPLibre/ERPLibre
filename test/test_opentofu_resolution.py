#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La résolution OpenTofu : champs vides remplis depuis un hôte Proxmox."""

import copy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.argv = ["todo.py"]
from script.opentofu import resolution as rs  # noqa: E402
from script.opentofu import spec as sp  # noqa: E402
from script.todo import todo_i18n  # noqa: E402

_LANGUE_ORIGINE = todo_i18n._current_lang


def setUpModule():
    todo_i18n._current_lang = "fr"


def tearDownModule():
    todo_i18n._current_lang = _LANGUE_ORIGINE


QM_VIDE = "      VMID NAME                 STATUS     MEM(MB)    BOOTDISK(GB) PID\n"
QM_LIST = QM_VIDE + (
    "       100 vm-essai             running    2048              16.00 2726\n"
    "       101 autre                stopped    4096              32.00 0\n"
)
PVESM_IMAGES = """Name             Type     Status           Total            Used       Available        %
local             dir     active        32815812         6873084        24559348   20.94%
"""
PVESM_SNIPPETS = PVESM_IMAGES
IP_LINK = "3: vmbr0: <BROADCAST,MULTICAST,UP> mtu 1500 qdisc noqueue\n"
INTERNE = """auto lo
iface lo inet loopback

auto vmbr0
iface vmbr0 inet static
    address 10.10.10.1/24
    bridge-ports none
    bridge-stp off
"""
LAN = """auto vmbr0
iface vmbr0 inet static
    address 192.0.2.5/24
    bridge-ports enp1s0
"""
RESOLV = "nameserver 127.0.0.53\nnameserver 192.0.2.1\n"


def _executer(qm=QM_VIDE, interfaces=INTERNE, snippets=PVESM_SNIPPETS, echec=""):
    reponses = {
        "hostname": "pve1\n",
        "pvesm status --content images": PVESM_IMAGES,
        "pvesm status --content snippets": snippets,
        "ip -o link show type bridge": IP_LINK,
        "cat /etc/network/interfaces": interfaces,
        "qm list": qm,
    }

    def executer(cmd):
        if echec and echec in cmd:
            return 1, ""
        if "resolv.conf" in cmd:
            return 0, RESOLV
        return 0, reponses[cmd]

    return executer


def _ssh(adresse="203.0.113.9"):
    """Lecteur `ssh -G` factice : adresse, compte et port de l'hôte."""
    return lambda: {"adresse": adresse, "user": "admin", "port": 2222}


def _ssh_interdit():
    raise AssertionError("ssh -G lu alors que rien ne manquait")


def _spec(nb=1):
    spec = sp.nouvelle_spec("parc-a", "hote-x")
    vm = spec["vms"][0]
    spec["vms"] = [dict(vm, nom=f"parc-a-vm-{i}") for i in range(1, nb + 1)]
    return spec


class TestResoudre(unittest.TestCase):
    def test_remplit_les_vides(self):
        spec, change = rs.resoudre(_spec(), _executer(), _ssh())
        c = spec["cible"]
        self.assertTrue(change)
        self.assertEqual(c["api_url"], "https://203.0.113.9:8006/")
        self.assertEqual(c["noeud"], "pve1")
        self.assertEqual(c["stockage"], "local")
        self.assertEqual(c["stockage_snippets"], "local")
        self.assertEqual(c["pont"], "vmbr0")
        self.assertEqual(c["ssh_user"], "admin")
        self.assertEqual(c["ssh_port"], 2222)
        self.assertEqual(spec["vms"][0]["vmid"], 100)

    def test_ne_mute_pas_l_entree(self):
        entree = _spec()
        copie = copy.deepcopy(entree)
        rs.resoudre(entree, _executer(), _ssh())
        self.assertEqual(entree, copie)

    def test_vmid_saute_les_pris(self):
        spec, _ = rs.resoudre(_spec(2), _executer(qm=QM_LIST), _ssh("a"))
        self.assertEqual([v["vmid"] for v in spec["vms"]], [102, 103])

    def test_pont_interne_donne_ip_fixe(self):
        spec, _ = rs.resoudre(_spec(3), _executer(qm=QM_LIST), _ssh("a"))
        vm = spec["vms"][0]
        self.assertEqual(vm["vmid"], 102)
        self.assertEqual(vm["ip"], "10.10.10.152/24")
        self.assertEqual(vm["passerelle"], "10.10.10.1")
        self.assertEqual(vm["dns"], ["192.0.2.1"])

    def test_pont_lan_donne_dhcp(self):
        spec, _ = rs.resoudre(_spec(), _executer(interfaces=LAN), _ssh("a"))
        self.assertEqual(spec["vms"][0]["ip"], "dhcp")
        self.assertEqual(spec["vms"][0]["passerelle"], "")

    def test_deuxieme_resolution_ne_change_rien(self):
        premiere, _ = rs.resoudre(_spec(2), _executer(), _ssh("a"))
        seconde, change = rs.resoudre(premiere, _executer(), _ssh_interdit)
        self.assertIs(change, False)
        self.assertEqual(seconde, premiere)

    def test_vmid_du_parc_reserve(self):
        spec = _spec(2)
        spec["vms"][0]["vmid"] = 100
        spec, _ = rs.resoudre(spec, _executer(), _ssh("a"))
        self.assertEqual([v["vmid"] for v in spec["vms"]], [100, 101])

    def test_champ_rempli_respecte(self):
        spec = _spec()
        spec["cible"]["stockage"] = "x"
        spec["vms"][0]["ip"] = "dhcp"
        spec, _ = rs.resoudre(spec, _executer(), _ssh("a"))
        self.assertEqual(spec["cible"]["stockage"], "x")
        self.assertEqual(spec["vms"][0]["ip"], "dhcp")

    def test_compte_et_port_ssh_remplis_respectes(self):
        spec = _spec()
        spec["cible"].update(
            api_url="https://203.0.113.9:8006/", ssh_user="ops", ssh_port=22
        )
        spec, _ = rs.resoudre(spec, _executer(), _ssh_interdit)
        self.assertEqual(spec["cible"]["ssh_user"], "ops")
        self.assertEqual(spec["cible"]["ssh_port"], 22)

    def test_spec_sans_champs_ssh_les_resout(self):
        spec = _spec()
        del spec["cible"]["ssh_user"]
        del spec["cible"]["ssh_port"]
        spec["cible"]["api_url"] = "https://203.0.113.9:8006/"
        spec, _ = rs.resoudre(spec, _executer(), _ssh())
        self.assertEqual(spec["cible"]["ssh_user"], "admin")
        self.assertEqual(spec["cible"]["ssh_port"], 2222)

    def test_nom_d_hote_vide_refuse(self):
        executer = _executer()

        def vide(cmd):
            return (0, "\n") if cmd == "hostname" else executer(cmd)

        with self.assertRaises(rs.ResolutionImpossible):
            rs.resoudre(_spec(), vide, _ssh())

    def test_sans_snippets(self):
        with self.assertRaises(rs.ResolutionImpossible) as ctx:
            rs.resoudre(_spec(), _executer(snippets="Name Type\n"), _ssh("a"))
        self.assertIn("Préparer l'hôte", str(ctx.exception))

    def test_lecture_en_echec_est_nommee(self):
        with self.assertRaises(rs.ResolutionImpossible) as ctx:
            rs.resoudre(_spec(), _executer(echec="qm list"), _ssh("a"))
        self.assertIn("qm list", str(ctx.exception))


class TestSshHote(unittest.TestCase):
    def test_adresse_compte_et_port_de_ssh_g(self):
        sortie = "user bob\nhostname 203.0.113.9\nport 2222\n"
        faux = subprocess.CompletedProcess([], 0, sortie, "")
        with mock.patch.object(rs.subprocess, "run", return_value=faux) as r:
            self.assertEqual(
                rs.ssh_hote("alias"),
                {"adresse": "203.0.113.9", "user": "bob", "port": 2222},
            )
        self.assertEqual(r.call_args[0][0], ["ssh", "-G", "alias"])

    def test_port_de_la_spec_passe_a_ssh_g(self):
        sortie = "user bob\nhostname 203.0.113.9\nport 2200\n"
        faux = subprocess.CompletedProcess([], 0, sortie, "")
        with mock.patch.object(rs.subprocess, "run", return_value=faux) as r:
            self.assertEqual(rs.ssh_hote("alias", "2200")["port"], 2200)
        self.assertEqual(r.call_args[0][0], ["ssh", "-G", "-p", "2200", "alias"])

    def test_echec_ssh_g(self):
        for code, sortie in (
            (255, ""),
            (0, "user bob\nport 22\n"),
            (0, "user bob\nhostname h\nport x\n"),
        ):
            faux = subprocess.CompletedProcess([], code, sortie, "boom")
            with mock.patch.object(rs.subprocess, "run", return_value=faux):
                with self.assertRaises(rs.ResolutionImpossible, msg=sortie):
                    rs.ssh_hote("alias")


class TestElevation(unittest.TestCase):
    @staticmethod
    def _hote(reponses):
        vues = []

        def executer(cmd):
            vues.append(cmd)
            return reponses[cmd]

        return executer, vues

    def test_root(self):
        executer, _ = self._hote({"id -u": (0, "0\n")})
        self.assertEqual(rs.elevation(executer)[0], "")

    def test_sudo_sans_mot_de_passe(self):
        executer, _ = self._hote({"id -u": (0, "1000\n"), "sudo -n true": (0, "")})
        self.assertEqual(rs.elevation(executer)[0], "sudo ")

    def test_sudo_avec_mot_de_passe(self):
        executer, _ = self._hote({"id -u": (0, "1000\n"), "sudo -n true": (1, "")})
        sudo, raison = rs.elevation(executer)
        self.assertIsNone(sudo)
        self.assertIn("NOPASSWD", raison)

    def test_ssh_injoignable_distingue(self):
        executer, vues = self._hote({"id -u": (255, "")})
        sudo, raison = rs.elevation(executer)
        self.assertIsNone(sudo)
        self.assertIn("SSH", raison)
        self.assertNotIn("NOPASSWD", raison)
        self.assertEqual(vues, ["id -u"])


class TestExecuterSsh(unittest.TestCase):
    def test_enrobe_par_sudo_une_seule_fois(self):
        hote = {"target": "t", "jump": "", "port": "", "sudo": "sudo "}
        with mock.patch.object(rs.pve, "run", return_value=(0, "ok")) as r:
            self.assertEqual(rs.executer_ssh(hote)("qm list"), (0, "ok"))
        envoye_hote, cmd = r.call_args[0][:2]
        self.assertTrue(cmd.startswith("sudo sh -c "))
        self.assertFalse(envoye_hote.get("sudo"))


class TestDonneesVm(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cle = Path(self.tmp.name) / "id.pub"
        self.cle.write_text("ssh-ed25519 AAAAtest cle@test\n")
        self.spec = _spec()
        self.spec["compte"]["ssh_key"] = str(self.cle)
        self.mod = rs.charger_deploy_qemu()

    def test_donnees_vm_debian(self):
        d = rs.donnees_vm(self.spec, self.spec["vms"][0], self.mod)
        self.assertTrue(d["url"].startswith("https://"))
        self.assertTrue(d["fichier"].endswith(".qcow2"))
        self.assertTrue(d["user_data"].startswith("#cloud-config"))
        self.assertIn("AAAAtest", d["user_data"])
        self.assertIn("sha256", d)
        self.assertIs(d["uefi"], self.mod.requiert_uefi("debian"))

    def test_img_devient_qcow2(self):
        vm = dict(self.spec["vms"][0], distro="ubuntu", version="24.04")
        d = rs.donnees_vm(self.spec, vm, self.mod)
        self.assertTrue(d["fichier"].endswith(".qcow2"))
        self.assertNotIn(".img", d["fichier"])

    def test_fedora_non_resolue_refusee(self):
        vm = dict(self.spec["vms"][0], distro="fedora", version="44")
        with self.assertRaises(rs.ResolutionImpossible):
            rs.donnees_vm(self.spec, vm, self.mod)

    def test_cle_illisible(self):
        self.spec["compte"]["ssh_key"] = str(self.cle) + ".absent"
        with self.assertRaises(rs.ResolutionImpossible):
            rs.donnees_vm(self.spec, self.spec["vms"][0], self.mod)

    def test_cle_vide(self):
        self.cle.write_text("\n")
        with self.assertRaises(rs.ResolutionImpossible):
            rs.donnees_vm(self.spec, self.spec["vms"][0], self.mod)

    def test_charger_deploy_qemu_memorise(self):
        self.assertIs(rs.charger_deploy_qemu(), rs.charger_deploy_qemu())


if __name__ == "__main__":
    unittest.main()
