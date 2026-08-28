#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le test long QEMU-dans-QEMU, et le garde qui donne un sens à sa mesure.

`deploy_qemu.py` n'échoue PAS quand KVM manque : il pose « --virt-type qemu »
et crée une VM entièrement émulée, sept minutes et demie de démarrage, sans
qu'aucun code de retour ne le dise. Une descente qui ne le vérifierait pas
irait plus « profond » en mesurant de la TCG empilée — un chiffre plus
flatteur, et faux.

Ces tests-ci ne créent aucune machine : ils lisent des sorties de `virsh` et de
`/sys` telles qu'elles arrivent vraiment, et vérifient ce qu'on en conclut.
"""

import contextlib
import io
import os
import sys
import unittest

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)
sys.path.insert(0, os.path.join(RACINE, "long_test"))
sys.argv = ["todo.py"]

import deep_qemu  # noqa: E402


class TestLireCeQueVirshEcrit(unittest.TestCase):
    """Des sorties RÉELLES, prises sur la machine, pas inventées."""

    def test_the_address_table_has_a_header_and_a_mask(self):
        vrai = (
            " Name       MAC address          Protocol     Address\n"
            "----------------------------------------------------------\n"
            " vnet3      52:54:00:79:78:a4    ipv4         192.168.123.118/24\n"
        )
        self.assertEqual(deep_qemu.parse_domifaddr(vrai), "192.168.123.118")

    def test_a_domain_without_a_lease_yet_gives_nothing(self):
        vide = (
            " Name       MAC address          Protocol     Address\n"
            "----------------------------------------------------------\n"
            " vnet0      52:54:00:aa:bb:cc    N/A          N/A\n"
        )
        self.assertEqual(deep_qemu.parse_domifaddr(vide), "")
        self.assertEqual(deep_qemu.parse_domifaddr(""), "")
        self.assertEqual(deep_qemu.parse_domifaddr(None), "")

    def test_an_emulated_domain_is_recognised(self):
        emule = "<domain type='qemu' id='3'>\n  <name>deep-qemu-2</name>\n"
        self.assertEqual(deep_qemu.parse_domaine(emule)["type"], "qemu")

    def test_an_accelerated_domain_and_its_cpu_mode(self):
        vrai = (
            "<domain type='kvm' id='3'>\n"
            "  <name>deep-qemu-2</name>\n"
            "  <cpu mode='host-passthrough' check='none' migratable='on'/>\n"
        )
        vu = deep_qemu.parse_domaine(vrai)
        self.assertEqual(vu["type"], "kvm")
        self.assertEqual(vu["cpu"], "host-passthrough")

    def test_an_unreadable_dumpxml_claims_nothing(self):
        vu = deep_qemu.parse_domaine("error: failed to get domain")
        self.assertEqual(vu["type"], "")
        self.assertEqual(vu["cpu"], "")


class TestUnEtageQuiNeSaitPasHeberger(unittest.TestCase):
    """Ce qui n'a pas été lu vaut NON.

    Si /sys/module/kvm_amd/parameters/nested n'existe pas, c'est que le module
    n'est pas chargé — et l'étage suivant serait émulé. Traiter l'absence
    comme un oui rendrait le contrôle décoratif."""

    def test_a_missing_nested_line_is_not_a_yes(self):
        vu = deep_qemu.parse_controle("KVM=oui\nDISQUE=120G\n")
        self.assertTrue(vu["kvm"])
        self.assertFalse(vu["nested"])
        self.assertEqual(vu["disque_go"], 120)

    def test_both_spellings_of_yes_are_accepted(self):
        for valeur in ("Y", "1"):
            with self.subTest(valeur=valeur):
                vu = deep_qemu.parse_controle(f"KVM=oui\nNESTED={valeur}\n")
                self.assertTrue(vu["nested"])

    def test_nested_off_is_read_as_off(self):
        for valeur in ("N", "0"):
            with self.subTest(valeur=valeur):
                vu = deep_qemu.parse_controle(f"KVM=oui\nNESTED={valeur}\n")
                self.assertFalse(vu["nested"])

    def test_no_kvm_device_at_all(self):
        vu = deep_qemu.parse_controle("KVM=non\nNESTED=Y\nDISQUE=50G\n")
        self.assertFalse(vu["kvm"])

    def test_an_empty_answer_asserts_nothing(self):
        vu = deep_qemu.parse_controle("")
        self.assertFalse(vu["kvm"])
        self.assertFalse(vu["nested"])
        self.assertEqual(vu["disque_go"], 0)

    def test_the_probe_is_written_for_dash(self):
        """/bin/sh est dash sur Debian : « set -o pipefail » y répond
        « Illegal option » et sort à la première ligne."""
        for interdit in ("[[", "pipefail", "$(", "&&\n"):
            self.assertNotIn(interdit, deep_qemu.CONTROLE_CMD, interdit)


class TestLesListesAptAvantToute(unittest.TestCase):
    """Constaté au premier lancement réel : « --setup-host » a échoué en ZÉRO
    seconde sur « Unable to locate package qemu-system-x86 », alors que le
    paquet existe. La VM venait de démarrer, ses listes ne portaient que
    « bookworm-security », et un apt-get update les a complétées d'un coup.

    Le message parlait de paquets introuvables, pas de listes vides : c'est
    exactement le genre de diagnostic qui envoie chercher au mauvais endroit.
    """

    def setUp(self):
        self.d = deep_qemu.Descente.__new__(deep_qemu.Descente)
        self.d.dry_run = False
        self.d.journal = None
        self.d.niveau_courant = 1
        self.d._envoyer_cli = lambda hote: True
        self.faits = []

    def _repond(self, code_apt=0):
        def executer(hote, cmd, delai, etiquette="", **k):
            self.faits.append(etiquette)
            if etiquette == "apt-get update":
                return code_apt, ""
            return 0, ""

        self.d.executer = executer

    def test_the_lists_are_refreshed_before_the_install(self):
        self._repond()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(self.d.installer({"target": "h"}))
        self.assertEqual(
            self.faits, ["apt-get update", "deploy_qemu --setup-host"]
        )

    def test_an_apt_lock_that_never_lets_go_stops_the_level(self):
        """Installer sur des listes vides donnerait « paquet introuvable » —
        un diagnostic qui envoie chercher au mauvais endroit."""
        self._repond(code_apt=1)
        with contextlib.redirect_stdout(io.StringIO()) as sortie:
            self.assertFalse(self.d.installer({"target": "h"}))
        self.assertIn("verrou reste tenu", sortie.getvalue())
        self.assertNotIn("deploy_qemu --setup-host", self.faits)

    def test_the_daily_timers_are_stopped_first(self):
        """apt-daily tient le verrou des listes au premier démarrage.
        install_proxmox.sh a la même parade, et pour la même raison."""
        self.assertIn("apt-daily.timer", deep_qemu.PREPARE_APT_CMD)
        self.assertIn("apt-daily.service", deep_qemu.PREPARE_APT_CMD)

    def test_it_retries_rather_than_giving_up_at_once(self):
        self.assertIn("while", deep_qemu.PREPARE_APT_CMD)
        self.assertIn("sleep", deep_qemu.PREPARE_APT_CMD)

    def test_the_apt_probe_is_written_for_dash(self):
        for interdit in ("[[", "pipefail", "seq "):
            self.assertNotIn(interdit, deep_qemu.PREPARE_APT_CMD, interdit)


class TestChaqueEtageSonSousReseau(unittest.TestCase):
    """Le « default » de libvirt sert 192.168.122.0/24 à TOUS les étages.

    Constaté au premier essai réel : l'étage 2, dont l'adresse était
    192.168.122.45 — servie par le « default » de son parent — a vu son propre
    « net-start default » refusé net :

        error: internal error: Network is already in use by interface enp1s0

    Un invité qui vit DANS un réseau ne peut pas servir le même."""

    def test_two_levels_never_share_a_subnet(self):
        vus = [deep_qemu.cidr_pour(p) for p in range(1, 11)]
        self.assertEqual(len(set(vus)), 10, vus)

    def test_it_avoids_libvirts_own_and_the_hosts(self):
        """122 est celui de libvirt, 123 celui de la machine où ce test a été
        écrit : tomber sur l'un ou l'autre recréerait la collision."""
        for profondeur in range(1, 11):
            prefixe = deep_qemu.cidr_pour(profondeur)
            self.assertNotIn(prefixe, ("192.168.122", "192.168.123"))

    def test_the_subnet_is_derived_not_drawn(self):
        # Deux appels pour la même profondeur donnent le même : rien de tiré
        # au hasard, sinon --detruire et le diagnostic ne se retrouveraient pas.
        self.assertEqual(deep_qemu.cidr_pour(3), deep_qemu.cidr_pour(3))

    def test_a_depth_of_zero_or_less_still_gives_a_subnet(self):
        for profondeur in (0, -1):
            self.assertTrue(deep_qemu.cidr_pour(profondeur).startswith("192."))

    def test_the_network_xml_is_one_line(self):
        """Elle traverse deux couches de quoting pour atterrir dans dash : un
        heredoc n'y survivrait pas."""
        xml = deep_qemu.reseau_xml("192.168.131")
        self.assertNotIn("\n", xml)
        self.assertIn("<name>default</name>", xml)
        self.assertIn("192.168.131.1", xml)
        self.assertIn("mode='nat'", xml)

    def test_the_dhcp_range_lives_in_its_own_subnet(self):
        xml = deep_qemu.reseau_xml("192.168.137")
        self.assertIn("start='192.168.137.10'", xml)
        self.assertIn("end='192.168.137.200'", xml)
        # Et la passerelle n'est pas dans la plage servie.
        self.assertIn("address='192.168.137.1'", xml)

    def test_the_level_redefines_before_starting(self):
        """« net-start » sur un réseau dont le sous-réseau collisionne échoue :
        il faut le REDÉFINIR, pas seulement le démarrer."""
        faits = []
        d = deep_qemu.Descente.__new__(deep_qemu.Descente)
        d.dry_run = False
        d.journal = None
        d.niveau_courant = 2
        d.profondeur_racine = 0

        def executer(hote, cmd, delai, etiquette="", **k):
            faits.append(cmd)
            return 0, "NET: Active:  yes\nUNITE:active\n"

        d.executer = executer
        with contextlib.redirect_stdout(io.StringIO()) as sortie:
            self.assertTrue(d.remettre_debout({"target": "h"}))
        pose = faits[0]
        self.assertLess(pose.index("net-undefine"), pose.index("net-define"))
        self.assertLess(pose.index("net-define"), pose.index("net-start"))
        # Le sous-réseau de CET étage, pas un autre.
        self.assertIn("192.168.132", pose)
        self.assertIn("192.168.132.0/24", sortie.getvalue())

    def test_a_borrowed_root_shifts_every_subnet(self):
        """Partir d'une racine déjà au troisième étage : le premier enfant est
        au quatrième, et doit prendre le sous-réseau du quatrième."""
        faits = []
        d = deep_qemu.Descente.__new__(deep_qemu.Descente)
        d.dry_run = False
        d.journal = None
        d.niveau_courant = 1
        d.profondeur_racine = 3
        d.executer = lambda h, c, delai, e="", **k: (
            faits.append(c) or (0, "NET: Active:  yes\nUNITE:active\n")
        )
        with contextlib.redirect_stdout(io.StringIO()):
            d.remettre_debout({"target": "h"})
        self.assertIn(deep_qemu.cidr_pour(4), faits[0])


class TestLeControleArreteLaDescente(unittest.TestCase):
    """Un étage sans KVM ne casse pas : il bascule en émulation et continue.
    C'est ce silence-là que le contrôle doit rompre."""

    def setUp(self):
        self.d = deep_qemu.Descente.__new__(deep_qemu.Descente)
        self.d.dry_run = False
        self.d.journal = None
        self.d.niveau_courant = 2

    def _repond(self, sortie, code=0):
        self.d.executer = lambda h, c, delai, etiquette="", **k: (code, sortie)

    def test_a_level_without_kvm_stops_the_descent(self):
        self._repond("KVM=non\nNESTED=Y\nDISQUE=90G\n")
        with contextlib.redirect_stdout(io.StringIO()) as sortie:
            self.assertFalse(self.d.controler({"target": "h"}))
        self.assertIn("serait ÉMULÉ", sortie.getvalue())

    def test_a_level_without_nesting_stops_the_descent(self):
        self._repond("KVM=oui\nNESTED=N\nDISQUE=90G\n")
        with contextlib.redirect_stdout(io.StringIO()) as sortie:
            self.assertFalse(self.d.controler({"target": "h"}))
        self.assertIn("imbriquée absente", sortie.getvalue())

    def test_an_unreadable_probe_concludes_nothing(self):
        # Une lecture qui échoue ne dit pas « pas de KVM » : elle ne dit rien.
        self._repond("", code=255)
        with contextlib.redirect_stdout(io.StringIO()) as sortie:
            self.assertFalse(self.d.controler({"target": "h"}))
        self.assertIn("illisible", sortie.getvalue())

    def test_a_healthy_level_passes(self):
        """Le contrôle NÉGATIF : sans lui, ce garde interdirait toute
        descente."""
        self._repond("KVM=oui\nNESTED=Y\nDISQUE=90G\n")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(self.d.controler({"target": "h"}))


class TestUneVmEmuleeNestPasUneMesure(unittest.TestCase):
    """« deploy_qemu » rend 0 en créant une VM émulée. La descente doit s'en
    apercevoir à la création, pas après sept minutes de démarrage."""

    def setUp(self):
        self.d = deep_qemu.Descente.__new__(deep_qemu.Descente)
        self.d.dry_run = False
        self.d.journal = None
        self.d.niveau_courant = 2
        self.d._envoyer_cli = lambda hote: True

    def _machine(self, xml, adresse=" x y ipv4 10.0.0.9/24"):
        def executer(hote, cmd, delai, etiquette="", **k):
            if "dumpxml" in cmd:
                return 0, xml
            if "domifaddr" in cmd:
                return 0, adresse
            return 0, ""

        self.d.executer = executer

    def test_an_emulated_child_is_refused(self):
        self._machine("<domain type='qemu' id='1'><name>x</name>")
        with contextlib.redirect_stdout(io.StringIO()) as sortie:
            identite, adresse = self.d.creer_enfant(
                {"target": "p"},
                2,
                {"vcpu": 2, "ram": 2048, "disque": 20},
                ("default",),
            )
        self.assertIsNone(identite)
        self.assertIsNone(adresse)
        self.assertIn("ÉMULÉE", sortie.getvalue())

    def test_an_accelerated_child_is_kept(self):
        self._machine(
            "<domain type='kvm' id='1'><name>x</name>"
            "<cpu mode='host-passthrough'/>"
        )
        with contextlib.redirect_stdout(io.StringIO()):
            identite, adresse = self.d.creer_enfant(
                {"target": "p"},
                2,
                {"vcpu": 2, "ram": 2048, "disque": 20},
                ("default",),
            )
        self.assertEqual(identite, "deep-qemu-2")
        self.assertEqual(adresse, "10.0.0.9")

    def test_the_identity_is_noted_before_anything_is_created(self):
        """Une création échouée à mi-chemin laisserait sinon une machine que
        le rapport ne nomme nulle part — et que --detruire ne peut pas
        défaire."""
        vus = []
        self._machine("<domain type='qemu'>")
        with contextlib.redirect_stdout(io.StringIO()):
            self.d.creer_enfant(
                {"target": "p"},
                4,
                {"vcpu": 2, "ram": 2048, "disque": 20},
                ("default",),
                noter=vus.append,
            )
        # Notée, alors même que la création a été REFUSÉE ensuite.
        self.assertEqual(vus, ["deep-qemu-4"])

    def test_a_child_without_an_address_is_refused(self):
        self._machine("<domain type='kvm'>", adresse=" x y N/A N/A")
        with contextlib.redirect_stdout(io.StringIO()) as sortie:
            identite, _a = self.d.creer_enfant(
                {"target": "p"},
                2,
                {"vcpu": 2, "ram": 2048, "disque": 20},
                ("default",),
            )
        self.assertIsNone(identite)
        self.assertIn("sans adresse", sortie.getvalue())


class TestNeDetruireQueLeSien(unittest.TestCase):
    """« virsh undefine --remove-all-storage » efface un disque pour de bon."""

    def setUp(self):
        self.vrai = deep_qemu.pve.run
        self.addCleanup(setattr, deep_qemu.pve, "run", self.vrai)
        self.lances = []

    def _parent_avec(self, noms):
        def faux(hote, remote, timeout=120):
            self.lances.append(remote)
            if "list --all --name" in remote:
                return 0, "\n".join(noms) + "\n"
            return 0, ""

        deep_qemu.pve.run = faux

    def test_a_name_that_merely_contains_ours_is_left_alone(self):
        self._parent_avec(["deep-qemu-lab", "autre"])
        with contextlib.redirect_stdout(io.StringIO()):
            res = deep_qemu.detruire_une(
                "p", "deep-qemu-2", "deep-qemu-2", None
            )
        self.assertTrue(res)  # absente, donc rien à faire
        self.assertFalse([c for c in self.lances if "undefine" in c])

    def test_our_own_machine_is_stopped_then_undefined(self):
        self._parent_avec(["deep-qemu-2"])
        with contextlib.redirect_stdout(io.StringIO()):
            res = deep_qemu.detruire_une(
                "p", "deep-qemu-2", "deep-qemu-2", None
            )
        self.assertTrue(res)
        ordre = [c for c in self.lances if "destroy" in c or "undefine" in c]
        self.assertEqual(len(ordre), 2)
        self.assertIn("destroy", ordre[0])
        self.assertIn("--remove-all-storage", ordre[1])

    def test_an_unreachable_parent_touches_nothing(self):
        deep_qemu.pve.run = lambda h, r, t=120: (255, "")
        with contextlib.redirect_stdout(io.StringIO()) as sortie:
            self.assertFalse(
                deep_qemu.detruire_une("p", "deep-qemu-2", "deep-qemu-2", None)
            )
        self.assertIn("rien touché", sortie.getvalue())


class TestLesDeuxTestsLongsSeRessemblent(unittest.TestCase):
    """Ce qui doit être identique doit l'être, et ce qui doit différer aussi."""

    def setUp(self):
        import deep_proxmox

        self.pve, self.qemu = deep_proxmox, deep_qemu

    def test_they_share_one_engine(self):
        import descente

        for module in (self.pve, self.qemu):
            self.assertTrue(issubclass(module.Descente, descente.Descente))

    def test_every_hook_is_implemented_by_both(self):
        import descente

        crochets = (
            "preparer_parent",
            "creer_enfant",
            "installer",
            "noyau_convient",
            "remettre_debout",
            "controler",
        )
        for module in (self.pve, self.qemu):
            for crochet in crochets:
                self.assertIsNot(
                    getattr(module.Descente, crochet),
                    getattr(descente.Descente, crochet),
                    f"{module.OUTIL} n'implémente pas {crochet}",
                )

    def test_they_never_share_a_name_a_tool_or_a_report(self):
        self.assertNotEqual(self.pve.OUTIL, self.qemu.OUTIL)
        self.assertNotEqual(self.pve.NOM_BASE, self.qemu.NOM_BASE)
        self.assertNotEqual(
            self.pve.FAMILLE.detruire_une, self.qemu.FAMILLE.detruire_une
        )

    def test_the_qemu_stack_asks_for_less(self):
        """libvirtd seul tient dans un gibioctet là où cinq démons PVE en
        demandent deux."""
        from script.proxmox import nesting

        pve = nesting.nesting_plan(3, 28, 39000, 150)
        qemu = nesting.nesting_plan(3, 28, 39000, 150, nesting.COUTS_QEMU)
        self.assertLess(qemu["niveaux"][0]["ram"], pve["niveaux"][0]["ram"])
        self.assertLess(
            qemu["niveaux"][0]["disque"], pve["niveaux"][0]["disque"]
        )


if __name__ == "__main__":
    unittest.main()
