#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les deux voies qui lancent « qm create » posent la MÊME machine.

UNE VM NE SE REDIMENSIONNE PAS APRÈS COUP SANS FRAIS. « qm create » fige la
taille du disque et les résolveurs de la VM ; ce qui manque là se répare à
la main, sur une machine déjà debout, ou ne se répare pas.

DEUX CONSTRUCTEURS POUR UN SEUL APPEL. L'écran bâtissait sa description de
VM en y ajoutant deux règles — le DNS de l'hôte, que « --ipconfig0 » ne
porte pas, et la marge de disque que réclame une installation d'ERPLibre —
là où le repli par questions bâtissait la sienne sans ni l'un ni l'autre.
Une VM née par les questions n'avait donc aucun résolveur en adresse fixe,
et naissait de la taille exactement demandée pour y poser cinq gigaoctets
de plus.

LA MARGE SE DÉCIDE AVANT DE CRÉER. La question de l'installation vient donc
avant la création, et non après : posée après, sa réponse arrive quand la
taille est déjà figée.

Ni réseau, ni hôte Proxmox : les invites sont simulées, « qm create » est
capturé et jamais lancé.
"""

import ast
import contextlib
import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

sys.argv = ["todo.py"]

from script.todo.todo import TODO  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402

MOD = type(
    "ModuleDeBanc",
    (),
    {
        "DISTROS": {"ubuntu": [{"24.04": ("noble", "24.04")}]},
        "image_url": staticmethod(lambda *_a: "http://example.invalid/i.img"),
        "default_image_name": staticmethod(lambda *_a: "i.img"),
    },
)()

# Une adresse de documentation (RFC 5737), vérifiée absente du reste du
# dépôt : un résolveur pris dans un parc réel se figerait ici pour toujours.
RESOLV = "nameserver 192.0.2.53\n"

DISQUE_DEMANDE = "20G"

# Le catalogue d'installation du banc : une commande qui clone bien le dépôt,
# donc qui déclenche la marge.
INSTALL_CMD = "make install_os && make install_odoo_18"


def deployer(reponses, resolv=RESOLV):
    """Mène le repli par questions jusqu'à « qm create ». Rend les appels
    reçus — (vmid, description de la VM) — et l'écran."""
    from script.proxmox import proxmox_deploy as pve

    todo = TODO.__new__(TODO)
    todo._pve_host = lambda: {"target": "hote"}
    todo._qemu_import_module = lambda: MOD
    todo._qemu_prompt_distro = lambda: "ubuntu"
    todo._qemu_prompt_version = lambda _d: "24.04"
    todo._qemu_ask_ram = lambda _l, _d: 4096
    todo._qemu_ask_cpu = lambda _l, _d, _h: 2
    todo._qemu_pick_branch = lambda: "develop"
    todo._qemu_pick_install_profile = lambda _d: ("ERPLibre", INSTALL_CMD)
    todo._qemu_host_timezone = lambda: "Etc/UTC"
    # Les réglages de l'invité, posés par l'invite partagée : le banc les
    # bouchonne pour n'éprouver que ce qui atteint « qm create ».
    todo._qemu_ask_timezone = lambda: "Etc/UTC"
    todo._qemu_ask_locale = lambda: "C.UTF-8"
    todo._qemu_ask_desktop = lambda: ""
    todo._qemu_desktop_suffixes = lambda: {}
    todo._qemu_ask_app_store = lambda _vms: "deb"
    todo._qemu_ask_vm_tools = lambda _vms: ()
    todo._qemu_ask_python_provider = lambda _a: ""
    todo._qemu_ask_ai_tools = lambda _t: ("", "", "")
    todo._qemu_default_ssh_key = lambda: ""
    todo._pve_vms = lambda: []
    todo._pve_print_summary = lambda *_a, **_k: None
    todo._pve_after_create = lambda *_a, **_k: []

    def montrer(cmd, **_kw):
        return (0, resolv) if cmd == pve.RESOLV_CMD else (0, "")

    todo._pve_show = montrer

    vus = []
    faux = {
        "parse_storages": lambda _o: ["local"],
        "parse_bridges": lambda _o: ["vmbr0"],
        "parse_bridge_config": lambda _o: {},
        "pick_storage": lambda _s: "local",
        "pick_bridge": lambda _p: "vmbr0",
        "next_vmid": lambda _v: 100,
        "ipconfig_for": lambda _i, _v: "ip=192.0.2.10/24,gw=192.0.2.1",
        "image_fetch_cmd": lambda _u, _i: "true",
        "ip_from_ipconfig": lambda _i: "192.0.2.10",
        "create_cmds": lambda vmid, detail: vus.append((vmid, detail)) or [],
    }
    tampon = io.StringIO()
    with contextlib.ExitStack() as pile:
        for nom, bouchon in faux.items():
            pile.enter_context(mock.patch.object(pve, nom, bouchon))
        pile.enter_context(
            mock.patch("builtins.input", side_effect=list(reponses))
        )
        pile.enter_context(redirect_stdout(tampon))
        todo._pve_deploy_prompts()
    return vus, tampon.getvalue()


# Les réponses, dans l'ordre où les invites les consomment : données réelles,
# posture, nom de VM, disque, installer ERPLibre, déployer maintenant.
def reponses(install="o"):
    return ["n", "1", "", DISQUE_DEMANDE, install, ""]


class TestCeQueLeRepliPasseAQmCreate(unittest.TestCase):
    """Deux règles, et chacune se paie sur une machine déjà debout."""

    def test_the_host_resolvers_reach_the_created_vm(self):
        """« --ipconfig0 » ne porte pas de résolveur : une VM en adresse
        fixe route alors sans rien résoudre, et « apt update » échoue sans
        que rien ne l'explique."""
        vus, _ecran = deployer(reponses())
        self.assertEqual(1, len(vus))
        self.assertEqual(["192.0.2.53"], list(vus[0][1]["nameservers"]))

    def test_an_erplibre_install_widens_the_disk_before_creation(self):
        """La taille est figée par « qm create » : la marge posée après
        n'existe pas."""
        vus, _ecran = deployer(reponses())
        self.assertEqual(
            f"{20 + TODO.ERPLIBRE_EXTRA_DISK_GB}G", vus[0][1]["disk"]
        )

    def test_without_an_install_the_typed_size_is_kept(self):
        """Contrôle positif : grossir toujours ferait payer la marge aux VM
        qui ne posent rien."""
        vus, _ecran = deployer(reponses(install="n"))
        self.assertEqual(DISQUE_DEMANDE, vus[0][1]["disk"])

    def test_the_screen_says_the_size_that_will_be_created(self):
        """Une marge ajoutée en silence se découvre au premier « df », sur
        une machine dont le disque ne se reprend plus sans frais."""
        _vus, ecran = deployer(reponses())
        self.assertIn(f"{20 + TODO.ERPLIBRE_EXTRA_DISK_GB}G", ecran)

    def test_an_unchanged_size_is_not_announced_twice(self):
        """Contrôle positif : répéter la taille tapée n'apprend rien et
        noie la ligne qui, elle, corrige une attente."""
        _vus, ecran = deployer(reponses(install="n"))
        self.assertNotIn(t("margin for what will be installed"), ecran)

    def test_a_host_without_a_resolver_creates_the_vm_all_the_same(self):
        """Un hôte dont « resolv.conf » ne nomme que la boucle locale ne
        doit pas empêcher la création : l'écran ne le fait pas non plus."""
        vus, _ecran = deployer(reponses(), resolv="nameserver 127.0.0.53\n")
        self.assertEqual(1, len(vus))
        self.assertEqual([], list(vus[0][1]["nameservers"]))


class TestLePointDePassageUnique(unittest.TestCase):
    """La parité ne se maintient pas à la relecture.

    Tant que les deux voies bâtissent chacune leur description, le prochain
    réglage se posera sur une seule — c'est ainsi que le DNS et la marge
    sont arrivés sur l'écran seul. Le contrôle porte donc sur le MÉCANISME :
    une seule fonction construit ce que « qm create » reçoit.
    """

    @staticmethod
    def corps(nom):
        chemin = os.path.join(RACINE, "script", "todo", "proxmox_menu.py")
        with io.open(chemin, encoding="utf-8") as fichier:
            source = fichier.read()
        for noeud in ast.walk(ast.parse(source)):
            if isinstance(noeud, ast.FunctionDef) and noeud.name == nom:
                return noeud
        raise AssertionError(f"{nom} introuvable")

    @staticmethod
    def appels(noeud):
        return {
            n.func.attr
            for n in ast.walk(noeud)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        }

    def test_the_prompt_path_builds_nothing_of_its_own(self):
        self.assertNotIn(
            "create_cmds", self.appels(self.corps("_pve_deploy_prompts"))
        )

    def test_the_prompt_path_goes_through_the_shared_builder(self):
        """Contrôle positif : ne plus appeler « qm create » du tout
        satisferait l'épreuve ci-dessus."""
        self.assertIn(
            "_pve_vm_commands", self.appels(self.corps("_pve_deploy_prompts"))
        )

    def test_the_shared_builder_is_the_one_that_calls_qm_create(self):
        self.assertIn(
            "create_cmds", self.appels(self.corps("_pve_vm_commands"))
        )


if __name__ == "__main__":
    unittest.main()
