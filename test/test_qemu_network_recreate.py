#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Recréer le sous-réseau d'un réseau libvirt sous les VM qui y vivent.

Une VM prend son adresse par DHCP dans le /24 de son réseau et en sort par le
.1, porté par le pont. Changer ce /24 sous une VM allumée la laisse avec un
bail qui ne mène nulle part ; abattre le réseau détache en plus son tap du
pont, et rien ne l'y rebranche tant qu'elle n'a pas redémarré.

D'où l'ordre que ces tests gardent :

- les VM attachées sont ARRÊTÉES avant que le réseau ne soit touché, et ce
  sont exactement celles-là qui redémarrent ensuite ;
- une VM qui n'obéit pas au shutdown ANNULE la redéfinition : la faire sous
  elle lui retirerait pont et passerelle ;
- un préfixe visé qui recouvre ce que l'hôte route déjà est REFUSÉ — c'est la
  panne d'origine, l'hôte y perdant sa propre passerelle au profit du pont ;
- un réseau qui sert déjà le préfixe visé n'est PAS redéfini : relancer
  l'opération ne doit rien casser.
"""

import importlib.util
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.argv = ["todo.py"]

RACINE = Path(__file__).resolve().parents[1]


def _network_qemu():
    """network_qemu.py chargé comme module, comme le fait le menu TODO."""
    path = RACINE / "script/qemu/network_qemu.py"
    spec = importlib.util.spec_from_file_location("network_qemu", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


NQ = _network_qemu()

XML_DEFAUT = """<network>
  <name>default</name>
  <uuid>2cf1310d-8812-456e-b761-9867efe4af8d</uuid>
  <forward mode='nat'/>
  <bridge name='virbr0' stp='on' delay='0'/>
  <mac address='52:54:00:6b:6d:2f'/>
  <ip address='192.168.131.1' netmask='255.255.255.0'>
    <dhcp>
      <range start='192.168.131.2' end='192.168.131.254'/>
    </dhcp>
  </ip>
</network>
"""

# Une définition de domaine, réduite à ce que le script y cherche.
XML_VM = """<domain type='kvm'>
  <name>{nom}</name>
  <devices>
    <interface type='network'>
      <source network='{reseau}'/>
    </interface>
  </devices>
</domain>
"""


def reseaux(*cidrs):
    import ipaddress

    return [ipaddress.ip_network(c, strict=False) for c in cidrs]


class Args:
    """Les options de la ligne de commande, réduites à ce que recreer lit."""

    def __init__(self, **kw):
        self.network = kw.get("network", "default")
        self.prefix = kw.get("prefix", "192.168.122")
        self.timeout = kw.get("timeout", 1)
        self.force_off = kw.get("force_off", False)
        self.assume_yes = kw.get("assume_yes", True)
        self.dry_run = kw.get("dry_run", False)


class Parc:
    """Un hôte bouchonné : ses VM, leur état, et ce que virsh en dit.

    Les états sont MUTABLES : « shutdown » éteint la VM dans ce parc, si bien
    que l'attente d'extinction du script s'y termine comme sur une vraie
    machine, sans dormir.
    """

    def __init__(self, vms, reseau="default"):
        # vms : {nom: "running" | "shut off"}
        self.etats = dict(vms)
        self.reseau = reseau
        self.sourdes = set()
        self.lancees = []

    def virsh_out(self, args, use_sudo, timeout=20):
        verbe = args[0]
        if verbe == "list":
            return " ".join(self.etats)
        if verbe == "domstate":
            return self.etats[args[1]]
        if verbe == "dumpxml":
            return XML_VM.format(nom=args[-1], reseau=self.reseau)
        if verbe == "net-dumpxml":
            return XML_DEFAUT
        if verbe == "net-dhcp-leases":
            return ""
        return ""

    def run(self, cmd, **kwargs):
        propre = [
            x for x in cmd if x not in ("virsh", "-c", NQ.DQ.LIBVIRT_URI)
        ]
        self.lancees.append(propre)
        verbe, cible = propre[0], propre[-1]
        if verbe == "shutdown" and cible not in self.sourdes:
            self.etats[cible] = "shut off"
        elif verbe == "destroy":
            self.etats[cible] = "shut off"
        elif verbe == "start":
            self.etats[cible] = "running"

    def verbes(self):
        return [c[0] for c in self.lancees]


def lancer(
    parc, args=None, hote=("192.168.2.0/24",), etat_reseau=(True, True)
):
    """Lance recreer() sur un parc bouchonné. Rend (code, sortie)."""
    runner = mock.MagicMock()
    runner.dry_run = False
    runner.use_sudo = False
    runner.run.side_effect = parc.run
    with mock.patch.object(
        NQ.DQ, "virsh_out", side_effect=parc.virsh_out
    ), mock.patch.object(
        NQ.DQ, "host_networks", return_value=reseaux(*hote)
    ), mock.patch.object(
        NQ.DQ, "libvirt_networks_cidrs", return_value=[]
    ), mock.patch.object(
        NQ.DQ, "network_state", return_value=etat_reseau
    ):
        with redirect_stdout(io.StringIO()) as sortie:
            code = NQ.recreer(args or Args(), runner)
    return code, sortie.getvalue()


class LOrdreDesTroisGestes(unittest.TestCase):
    def test_the_vms_stop_before_the_network_moves_and_start_after(self):
        """L'ordre EST la fonctionnalité : redéfinir sous une VM allumée lui
        retire son pont, la redémarrer avant la redéfinition lui redonne un
        bail dans l'ancien /24."""
        parc = Parc({"vm-a": "running", "vm-b": "running"})
        code, texte = lancer(parc)
        self.assertEqual(0, code)
        verbes = parc.verbes()
        self.assertEqual(
            ["shutdown", "shutdown", "net-destroy", "net-define"], verbes[:4]
        )
        self.assertLess(verbes.index("net-define"), verbes.index("start"))
        self.assertEqual(["net-start", "net-autostart"], verbes[4:6])
        self.assertEqual(["start", "start"], verbes[6:])

    def test_only_the_vms_it_stopped_are_started_again(self):
        """Une VM éteinte AVANT l'opération le reste : ce script recrée un
        sous-réseau, il ne décide pas de ce qui tourne sur l'hôte."""
        parc = Parc({"vm-a": "running", "vm-b": "shut off"})
        lancer(parc)
        demarrees = [c[-1] for c in parc.lancees if c[0] == "start"]
        self.assertEqual(["vm-a"], demarrees)

    def test_only_the_vms_of_that_network_are_touched(self):
        """Une VM sur un autre réseau n'a rien à faire dans l'opération."""
        parc = Parc({"vm-a": "running"}, reseau="autre-reseau")
        lancer(parc)
        self.assertNotIn("shutdown", parc.verbes())
        self.assertNotIn("start", parc.verbes())

    def test_a_network_without_vm_is_still_recreated(self):
        parc = Parc({})
        code, _ = lancer(parc)
        self.assertEqual(0, code)
        self.assertIn("net-define", parc.verbes())


class LaVmQuiNObeitPas(unittest.TestCase):
    def test_a_vm_that_stays_up_cancels_the_redefinition(self):
        """Rien n'est touché : la redéfinition sous une VM vivante lui
        retirerait son pont ET sa passerelle, et elle n'a même plus de quoi
        le dire."""
        parc = Parc({"vm-a": "running"})
        parc.sourdes.add("vm-a")
        code, texte = lancer(parc)
        self.assertEqual(1, code)
        self.assertNotIn("net-define", parc.verbes())
        self.assertNotIn("net-destroy", parc.verbes())
        self.assertIn("--force-off", texte)

    def test_force_off_cuts_the_power_and_the_work_goes_on(self):
        parc = Parc({"vm-a": "running"})
        parc.sourdes.add("vm-a")
        code, _ = lancer(parc, Args(force_off=True))
        self.assertEqual(0, code)
        self.assertIn("destroy", parc.verbes())
        self.assertLess(
            parc.verbes().index("destroy"), parc.verbes().index("net-define")
        )


class LePrefixeVise(unittest.TestCase):
    def test_a_prefix_the_host_already_routes_is_refused(self):
        """La panne d'origine, dans l'autre sens : poser le réseau sur le /24
        de l'hôte donne au pont l'adresse de la passerelle, et la machine
        perd son accès au réseau au démarrage suivant."""
        parc = Parc({"vm-a": "running"})
        code, texte = lancer(
            parc, Args(prefix="192.168.2"), hote=("192.168.2.0/24",)
        )
        self.assertEqual(1, code)
        self.assertNotIn("net-define", parc.verbes())
        self.assertIn("passerelle", texte)

    def test_the_stopped_vms_start_again_even_when_nothing_moved(self):
        """Un refus ne doit pas laisser le parc éteint : les VM arrêtées pour
        l'opération sont rendues à l'état où on les a prises."""
        parc = Parc({"vm-a": "running"})
        lancer(parc, Args(prefix="192.168.2"), hote=("192.168.2.0/24",))
        self.assertEqual("running", parc.etats["vm-a"])

    def test_a_prefix_already_served_is_not_redefined(self):
        """Idempotence : relancer l'opération sur un réseau déjà bon ne le
        redéfinit pas, et n'abat donc rien sous les VM.

        Le cycle d'extinction et de rallumage, lui, a lieu : c'est ce qui
        REBRANCHE le tap d'une VM sur le pont. Un réseau abattu laisse ses VM
        détachées, et libvirt ne les y remet pas de lui-même — sur un parc
        déjà déplacé, c'est la seule chose qui reste à faire."""
        parc = Parc({"vm-a": "running"})
        code, texte = lancer(parc, Args(prefix="192.168.131"))
        self.assertEqual(0, code)
        self.assertNotIn("net-define", parc.verbes())
        self.assertNotIn("net-destroy", parc.verbes())
        self.assertEqual(["shutdown", "net-autostart", "start"], parc.verbes())

    def test_an_invalid_prefix_stops_the_program(self):
        """Trois octets, et un /24 que ipaddress accepte. Un préfixe pris de
        travers réécrirait le XML au hasard."""
        for mauvais in ("192.168", "192.168.1.1", "192.168.999", "abc"):
            with self.assertRaises(SystemExit):
                NQ.valider_prefixe(mauvais)
        self.assertEqual("192.168.122", NQ.valider_prefixe("192.168.122"))


class LaLecture(unittest.TestCase):
    def test_the_prefix_comes_from_the_subnet(self):
        self.assertEqual("192.168.122", NQ.prefixe_de("192.168.122.0/24"))
        self.assertEqual("", NQ.prefixe_de(""))

    def test_the_attached_vms_are_read_from_the_persistent_definition(self):
        """« --inactive » : la vue vivante d'une VM allumée est décorée de ce
        que libvirt lui a alloué au démarrage, mais c'est la définition qui
        dit à quel réseau elle revient."""
        parc = Parc({"vm-a": "running"})
        with mock.patch.object(NQ.DQ, "virsh_out", side_effect=parc.virsh_out):
            self.assertEqual(["vm-a"], NQ.domaines_du_reseau("default", False))
            self.assertEqual([], NQ.domaines_du_reseau("autre", False))

    def test_a_paused_vm_counts_as_alive(self):
        """Une VM en pause tient toujours son tap : la redéfinir sous elle la
        casse comme une VM qui tourne."""
        parc = Parc({"vm-a": "paused"})
        with mock.patch.object(NQ.DQ, "virsh_out", side_effect=parc.virsh_out):
            self.assertTrue(NQ.domaine_actif("vm-a", False))


if __name__ == "__main__":
    unittest.main()
