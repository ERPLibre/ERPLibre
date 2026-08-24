#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le nettoyage ne doit jamais proposer un fichier EN USAGE.

Rapporté, et c'est le pire défaut possible ici : après avoir renommé une VM
« erplibre-ubuntu-2404 » en « erplibre-ubuntu-2404-MIGRATION », le nettoyage
offrait au « rm -f » son disque de 63 Go, son seed et son nvram — tous les
trois attachés à une VM EN MARCHE. La cause : l'orphelinat se jugeait sur le
NOM du fichier comparé aux noms de domaines.

Le nom ne dit rien de l'usage. L'autorité, c'est libvirt : ce qu'un domaine
référence n'est pas orphelin, quel que soit son nom. Et devant un « rm -f »
de 63 Go, un second contrôle indépendant (les fichiers qu'un processus tient
ouverts) vaut le coup.
"""

import os
import sys
import unittest

sys.argv = ["todo.py"]
from script.todo.todo import TODO  # noqa: E402

# La forme RÉELLE, relevée sur la machine : le nvram porte un attribut
# « template », et c'est ce qui l'avait fait manquer d'un premier filtre.
XML_MIGRATION = """<domain type='kvm'>
  <name>erplibre-ubuntu-2404-MIGRATION</name>
  <os firmware='efi'>
    <loader readonly='yes' type='pflash'>/usr/share/OVMF/OVMF_CODE_4M.fd</loader>
    <nvram template='/usr/share/OVMF/OVMF_VARS_4M.fd'>/var/lib/libvirt/qemu/nvram/erplibre-ubuntu-2404_VARS.fd</nvram>
  </os>
  <devices>
    <disk type='file' device='disk'>
      <source file='/var/lib/libvirt/images/erplibre-ubuntu-2404.qcow2'/>
      <target dev='vda' bus='virtio'/>
    </disk>
    <disk type='file' device='disk'>
      <source file='/var/lib/libvirt/images/iso/erplibre-ubuntu-2404-seed.iso'/>
      <target dev='vdb' bus='virtio'/>
    </disk>
    <interface type='network'>
      <source network='default'/>
    </interface>
  </devices>
</domain>
"""
DISQUE = "/var/lib/libvirt/images/erplibre-ubuntu-2404.qcow2"
SEED = "/var/lib/libvirt/images/iso/erplibre-ubuntu-2404-seed.iso"
NVRAM = "/var/lib/libvirt/qemu/nvram/erplibre-ubuntu-2404_VARS.fd"


def todo_avec(xml_par_domaine, ouverts=()):
    """Une instance TODO dont libvirt et /proc sont remplacés par des faits."""
    todo = TODO.__new__(TODO)
    todo._qemu_list_domains = lambda: list(xml_par_domaine)
    todo._qemu_dumpxml = lambda nom, inactive=True: xml_par_domaine.get(
        nom, ""
    )
    todo._qemu_files_in_use = lambda: set(ouverts)
    return todo


class TestCeQueLesDomainesReferencent(unittest.TestCase):
    def setUp(self):
        self.todo = todo_avec(
            {"erplibre-ubuntu-2404-MIGRATION": XML_MIGRATION}
        )

    def test_a_renamed_domain_still_owns_its_files(self):
        # Le cœur du rapport : le nom du fichier n'a plus rien à voir avec le
        # nom du domaine, et c'est parfaitement normal après un renommage.
        refs = self.todo._qemu_referenced_files()
        for chemin in (DISQUE, SEED, NVRAM):
            self.assertEqual(
                refs.get(chemin), "erplibre-ubuntu-2404-MIGRATION", chemin
            )

    def test_the_nvram_is_read_despite_its_attribute(self):
        # « <nvram template='…'>chemin</nvram> » : attendre « <nvram> » nu
        # manquait le fichier le plus facile à perdre.
        self.assertIn(NVRAM, self.todo._qemu_referenced_files())

    def test_the_network_source_is_not_a_file(self):
        # « <source network='default'/> » ne doit pas entrer dans la liste.
        for chemin in self.todo._qemu_referenced_files():
            self.assertTrue(chemin.startswith("/"), chemin)

    def test_a_domain_without_xml_is_simply_skipped(self):
        todo = todo_avec({"fantome": ""})
        self.assertEqual(todo._qemu_referenced_files(), {})


class TestLeTri(unittest.TestCase):
    """(orphelins, protégés) : c'est ce tri qui décide de ce qui est effacé."""

    def _tri(self, candidats, xml=None, ouverts=()):
        todo = todo_avec(
            xml if xml is not None else {"vm-a": XML_MIGRATION}, ouverts
        )
        return todo._qemu_split_orphans(candidats)

    def test_a_referenced_file_is_never_an_orphan(self):
        orph, prot = self._tri([(63, DISQUE, "disque orphelin")])
        self.assertEqual(orph, [])
        self.assertEqual(prot[0][2], "vm-a")

    def test_an_unreferenced_file_stays_an_orphan(self):
        perdu = "/var/lib/libvirt/images/plus-personne.qcow2"
        orph, prot = self._tri([(1, perdu, "disque orphelin")])
        self.assertEqual([o[1] for o in orph], [perdu])
        self.assertEqual(prot, [])

    def test_a_file_held_open_is_protected_even_without_libvirt(self):
        # Un qemu lancé à la main, ou une définition que libvirt a perdue :
        # le fichier est ouvert, donc il n'est pas à jeter.
        perdu = "/var/lib/libvirt/images/lancee-a-la-main.qcow2"
        orph, prot = self._tri(
            [(1, perdu, "disque orphelin")], xml={}, ouverts=(perdu,)
        )
        self.assertEqual(orph, [])
        self.assertIn(
            prot[0][2], (perdu, "un processus en cours", "a running process")
        )

    def test_the_three_files_of_the_report_are_all_kept(self):
        candidats = [
            (63_000_000_000, DISQUE, "disque orphelin"),
            (528_000, NVRAM, "nvram orpheline"),
            (368_000, SEED, "seed orphelin"),
        ]
        orph, prot = self._tri(candidats)
        self.assertEqual(orph, [], "un fichier en usage serait effacé")
        self.assertEqual(len(prot), 3)


class TestEffacerUneVm(unittest.TestCase):
    """L'autre bout du même défaut : effacer par le NOM laissait 63 Go.

    « rm /var/lib/libvirt/images/<nom>.qcow2 » ne trouve rien quand la VM a
    été renommée — la définition partait, le disque restait, et devenait un
    vrai orphelin de 63 Go que le nettoyage n'osait plus toucher.
    """

    def test_a_renamed_vm_deletes_its_real_files(self):
        todo = todo_avec({"erplibre-ubuntu-2404-MIGRATION": XML_MIGRATION})
        self.assertEqual(
            todo._qemu_vm_own_files("erplibre-ubuntu-2404-MIGRATION"),
            [DISQUE, SEED],
        )

    def test_the_nvram_is_left_to_virsh_undefine(self):
        # « virsh undefine --nvram » s'en charge : le lister deux fois ne
        # sert à rien, et un « rm » sur un nvram encore utilisé serait pire.
        todo = todo_avec({"vm-a": XML_MIGRATION})
        self.assertNotIn(NVRAM, todo._qemu_vm_own_files("vm-a"))

    def test_a_file_shared_with_a_neighbour_is_spared(self):
        # Image de FOND d'une chaîne de qcow2 : l'effacer creverait l'autre.
        partage = (
            "<domain><devices><disk><source file='"
            + DISQUE
            + "'/></disk></devices></domain>"
        )
        todo = todo_avec({"vm-a": XML_MIGRATION, "vm-b": partage})
        propres = todo._qemu_vm_own_files("vm-a")
        self.assertNotIn(DISQUE, propres)
        self.assertIn(SEED, propres)

    def test_a_vm_without_files_yields_nothing_rather_than_a_guess(self):
        todo = todo_avec({"vm-a": "<domain><devices/></domain>"})
        self.assertEqual(todo._qemu_vm_own_files("vm-a"), [])


CONFIG_SSH = """Host exo
    HostName 132.207.112.51

Host erplibre-ubuntu-2404
    HostName 192.168.123.170
    User erplibre

Host erplibre-partie
    HostName 192.168.123.99
    User erplibre

Host erplibre-imbriquee
    HostName 10.10.10.150
    User erplibre
    ProxyJump erplibre-proxmox-9

Host erplibre-sur-proxmox
    HostName 10.10.10.151
    User erplibre
"""


class TestLesEntreesSsh(unittest.TestCase):
    """Le nettoyage des entrées ~/.ssh/config jugeait, lui aussi, sur le NOM.

    Conséquence vécue : après le renommage de la VM, son alias
    « erplibre-ubuntu-2404 » ne correspondait plus à aucun domaine et a été
    effacé — alors qu'il menait à une machine EN MARCHE. Trois autres preuves
    valent mieux qu'un nom.
    """

    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.domaines = {"erplibre-ubuntu-2404-MIGRATION"}
        self.adresses = {"192.168.123.170": "erplibre-ubuntu-2404-MIGRATION"}

    def _juge(self, nom, distantes=()):
        return self.todo._ssh_entry_alive(
            CONFIG_SSH, nom, self.domaines, self.adresses, set(distantes)
        )

    def test_a_renamed_vm_keeps_its_alias(self):
        # L'adresse mène à un domaine vivant : le nom n'a plus d'importance.
        self.assertEqual(
            self._juge("erplibre-ubuntu-2404"),
            "erplibre-ubuntu-2404-MIGRATION",
        )

    def test_a_name_that_matches_a_domain_is_kept(self):
        self.assertTrue(self._juge("erplibre-ubuntu-2404-MIGRATION"))

    def test_a_jump_entry_is_kept(self):
        # Écrite pour une VM imbriquée ou distante : virsh ne la connaîtra
        # jamais, et son adresse n'est pas routable d'ici.
        self.assertTrue(self._juge("erplibre-imbriquee"))

    def test_a_vm_of_the_proxmox_host_is_kept(self):
        self.assertTrue(
            self._juge("erplibre-sur-proxmox", ["erplibre-sur-proxmox"])
        )

    def test_an_entry_that_leads_nowhere_is_an_orphan(self):
        self.assertEqual(self._juge("erplibre-partie"), "")


class TestLAdresseDUneVm(unittest.TestCase):
    """« --source arp » remonte les passerelles des ponts : la dernière
    candidate n'est pas la bonne.

    Vécu sur la VM renommée : son bail porte encore l'ancien nom d'hôte, donc
    aucune correspondance, et le repli sur « la dernière » annonçait
    192.168.122.1 — la passerelle — au lieu de 192.168.123.170.
    """

    def _todo(self, par_source):
        todo = TODO.__new__(TODO)
        todo._qemu_candidates_by_source = lambda nom: par_source
        todo._qemu_lease_ip_for_host = lambda nom, cands: None
        return todo

    def test_the_lease_wins_over_the_arp_table(self):
        todo = self._todo(
            {
                "lease": ["192.168.123.170"],
                "agent": ["192.168.123.170", "192.168.122.1"],
                "arp": ["192.168.123.170", "192.168.122.1"],
            }
        )
        self.assertEqual(todo._qemu_vm_ip_now("x"), "192.168.123.170")

    def test_without_a_lease_the_agent_speaks(self):
        todo = self._todo({"agent": ["10.0.0.5"], "arp": ["192.168.122.1"]})
        self.assertEqual(todo._qemu_vm_ip_now("x"), "10.0.0.5")

    def test_the_freshest_lease_of_the_source_is_taken(self):
        # Bail précoce (« ubuntu ») puis bail définitif : c'est le dernier du
        # BAIL qui compte, pas le dernier toutes sources confondues.
        todo = self._todo(
            {"lease": ["192.168.123.10", "192.168.123.11"], "arp": ["1.2.3.4"]}
        )
        self.assertEqual(todo._qemu_vm_ip_now("x"), "192.168.123.11")

    def test_nothing_known_yields_nothing(self):
        self.assertIsNone(self._todo({})._qemu_vm_ip_now("x"))

    def test_the_hosts_own_addresses_are_never_candidates(self):
        siennes = TODO._qemu_host_addresses()
        self.assertIn("127.0.0.1", siennes)
        for nom in TODO.__new__(TODO)._qemu_list_domains():
            for ips in TODO._qemu_candidates_by_source(nom).values():
                self.assertFalse(set(ips) & siennes, nom)


class TestLesFichiersOuverts(unittest.TestCase):
    """Le contrôle indépendant : /proc, sans privilège."""

    def test_it_finds_the_files_of_a_running_vm(self):
        # Sur cette machine, si une VM tourne, son disque est cité par la
        # ligne de commande de son qemu. Sinon, le test ne prouve rien et
        # doit le DIRE plutôt que de passer pour rien.
        todo = TODO.__new__(TODO)
        domaines = todo._qemu_list_domains()
        if not domaines:
            self.skipTest("aucune VM définie sur cette machine")
        ouverts = TODO._qemu_files_in_use()
        if not ouverts:
            self.skipTest("aucune VM démarrée sur cette machine")
        self.assertTrue(
            all(o.startswith("/var/lib/libvirt/") for o in ouverts)
        )

    def test_it_only_keeps_paths_that_exist(self):
        # La ligne de commande d'un processus quelconque peut contenir
        # n'importe quoi — ce test-ci en met la preuve dans la sienne :
        # /var/lib/libvirt/n-existe-pas-du-tout
        for chemin in TODO._qemu_files_in_use():
            self.assertTrue(os.path.exists(chemin), chemin)


if __name__ == "__main__":
    unittest.main(verbosity=2)
