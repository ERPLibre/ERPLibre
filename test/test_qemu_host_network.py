#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le réseau libvirt de l'hôte, et la collision qui lui coûtait sa passerelle.

Le réseau « default » de libvirt sert 192.168.122.0/24. Toute VM déployée par
ce dépôt vit DANS ce réseau : son pont y prendrait l'adresse .1, celle de sa
propre passerelle. virsh refuse ce démarrage — mais seulement quand la route
est là. Au démarrage de la machine, libvirtd monte ses réseaux AVANT que le
bail DHCP ne soit arrivé : plus rien ne signale la collision, virbr0 prend
l'adresse de la passerelle, et l'hôte n'a plus de réseau. Une installation
suivie d'un redémarrage rendait donc la machine inutilisable.

Ce que ces tests gardent :

- un réseau en collision est DÉPLACÉ sur un /24 libre, par redéfinition —
  laquelle ne demande ni pont ni module du noyau, et passe donc là où le
  démarrage ne passe pas ;
- l'autostart ne s'arme JAMAIS sur un réseau en collision, et se RETIRE si on
  le trouve armé : c'est le seul geste qui protège le démarrage suivant ;
- l'autostart s'arme quand le seul obstacle est le noyau remplacé depuis le
  démarrage — c'est ce qui rend l'hôte utilisable en UN redémarrage ;
- l'état d'un réseau est lu en ANGLAIS : virsh traduit ses étiquettes, et un
  hôte en français lisait tout réseau comme éteint et jamais prêt ;
- le XML déplacé garde l'identité du réseau — UUID, pont, MAC ;
- un réseau démarré ne se compte PAS comme sa propre collision : il porte et
  route son /24 sur son pont, et ce pont est écarté de ce que « l'hôte occupe
  déjà ». Sans cette exclusion, le verdict était « collision » sur toute
  machine où le réseau tournait, quel que soit son sous-réseau, et le
  déplacement qui suivait retirait leur passerelle aux VM attachées.
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


def _deploy_qemu():
    """deploy_qemu.py chargé comme module, comme le fait todo.py."""
    path = RACINE / "script/qemu/deploy_qemu.py"
    spec = importlib.util.spec_from_file_location("deploy_qemu", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


DQ = _deploy_qemu()

# Le XML que virsh rend pour le réseau « default » d'une installation neuve.
XML_DEFAUT = """<network>
  <name>default</name>
  <uuid>2cf1310d-8812-456e-b761-9867efe4af8d</uuid>
  <forward mode='nat'/>
  <bridge name='virbr0' stp='on' delay='0'/>
  <mac address='52:54:00:6b:6d:2f'/>
  <ip address='192.168.122.1' netmask='255.255.255.0'>
    <dhcp>
      <range start='192.168.122.2' end='192.168.122.254'/>
    </dhcp>
  </ip>
</network>
"""

# « virsh net-info » sous locale française : les étiquettes sont traduites,
# les valeurs aussi.
INFO_FR = """Nom :          default
Actif :        oui
Persistant :    oui
Démarrage automatique : oui
"""

INFO_EN = """Name:           default
Active:         yes
Persistent:     yes
Autostart:      yes
"""


def reseaux(*cidrs):
    import ipaddress

    return [ipaddress.ip_network(c, strict=False) for c in cidrs]


class LaLecture(unittest.TestCase):
    """Ce que le script lit de virsh, et dans quelle langue."""

    def test_the_state_is_read_in_english(self):
        """virsh TRADUIT ses étiquettes. Le script forçait la locale nulle
        part : sur un hôte français, « Active: yes » ne se trouvait jamais,
        tout réseau passait pour éteint, et --setup-host déclarait l'hôte pas
        prêt quel que soit son état."""
        with mock.patch.object(DQ, "virsh_out", return_value=INFO_EN):
            self.assertEqual((True, True), DQ.network_state("default", False))

    def test_the_french_output_is_what_the_old_pattern_missed(self):
        """La preuve du défaut, figée : la sortie traduite ne contient AUCUN
        des deux motifs anglais. Si un jour on retire LC_ALL=C, ce test
        rappelle ce qu'on relit."""
        with mock.patch.object(DQ, "virsh_out", return_value=INFO_FR):
            self.assertEqual(
                (False, False), DQ.network_state("default", False)
            )

    def test_the_c_locale_is_forced(self):
        env = DQ.c_locale_env()
        self.assertEqual("C", env["LC_ALL"])
        self.assertEqual("C", env["LANG"])

    def test_the_subnet_comes_from_the_xml(self):
        self.assertEqual(
            "192.168.122.0/24", DQ.cidr_from_network_xml(XML_DEFAUT)
        )

    def test_an_unreadable_xml_says_nothing(self):
        """Rien plutôt qu'un sous-réseau deviné : c'est sur lui qu'on décide
        de déplacer un réseau."""
        self.assertEqual("", DQ.cidr_from_network_xml(""))
        self.assertEqual("", DQ.cidr_from_network_xml("<network/>"))


class LaCollision(unittest.TestCase):
    def test_the_default_network_collides_inside_a_deployed_vm(self):
        """Une VM de ce dépôt reçoit 192.168.122.x de son hôte, et son propre
        « default » sert le même /24 : la collision est la règle, pas le cas
        limite."""
        self.assertEqual(
            "192.168.122.0/24",
            DQ.network_collision(
                "192.168.122.0/24", reseaux("192.168.122.0/24")
            ),
        )

    def test_a_wider_host_route_still_collides(self):
        """Le recouvrement se CALCULE : un /16 de l'hôte contient le /24 du
        réseau, ce qu'une comparaison de préfixes texte ne verrait pas."""
        self.assertTrue(
            DQ.network_collision("192.168.131.0/24", reseaux("192.168.0.0/16"))
        )

    def test_a_free_subnet_does_not_collide(self):
        self.assertEqual(
            "",
            DQ.network_collision(
                "192.168.131.0/24", reseaux("192.168.122.0/24", "127.0.0.0/8")
            ),
        )

    def test_no_subnet_means_no_verdict(self):
        self.assertEqual("", DQ.network_collision("", reseaux("10.0.0.0/8")))


class CeQueLHoteOccupe(unittest.TestCase):
    """host_networks : ce qui compte comme « déjà pris », et ce qui non."""

    # Ce que rendent « ip -4 route show » et « ip -o -4 addr show » sur un hôte
    # dont le réseau local est ailleurs et dont le « default » de libvirt
    # tourne. Les deux dernières lignes de chaque sortie sont celles du pont.
    ROUTES = (
        "default via 192.168.2.1 dev enp6s0 proto dhcp src 192.168.2.11"
        " metric 100\n"
        "192.168.2.0/24 dev enp6s0 proto kernel scope link src 192.168.2.11\n"
        "192.168.122.0/24 dev virbr0 proto kernel scope link"
        " src 192.168.122.1\n"
    )
    ADRESSES = (
        "1: lo    inet 127.0.0.1/8 scope host lo\\       valid_lft forever\n"
        "2: enp6s0    inet 192.168.2.11/24 brd 192.168.2.255 scope global"
        " enp6s0\\       valid_lft forever\n"
        "3: virbr0    inet 192.168.122.1/24 brd 192.168.122.255 scope global"
        " virbr0\\       valid_lft forever\n"
    )

    def _host_networks(self, exclure=()):
        sorties = {"route": self.ROUTES, "addr": self.ADRESSES}

        def faux_run(args, **kwargs):
            quoi = "route" if "route" in args else "addr"
            return mock.Mock(stdout=sorties[quoi])

        with mock.patch.object(DQ.subprocess, "run", side_effect=faux_run):
            return {str(r) for r in DQ.host_networks(exclure_ponts=exclure)}

    def test_the_network_no_longer_collides_with_itself(self):
        """Le défaut qui déplaçait un réseau sain. Un « default » démarré
        route son propre /24 : compté, il est en collision avec lui-même sur
        TOUTE machine, et le déplacement qui suit retire aux VM attachées la
        passerelle qu'elles ont dans leur bail."""
        vus = self._host_networks(exclure=["virbr0"])
        self.assertNotIn("192.168.122.0/24", vus)
        self.assertEqual(
            "",
            DQ.network_collision("192.168.122.0/24", reseaux(*vus)),
        )

    def test_without_the_exclusion_the_verdict_was_always_collision(self):
        """La preuve du défaut, figée : sans exclusion, le même hôte — dont le
        réseau local est pourtant ailleurs — voit une collision."""
        vus = self._host_networks()
        self.assertIn("192.168.122.0/24", vus)

    def test_the_other_interfaces_still_count(self):
        """Écarter le pont n'aveugle pas sur le reste : c'est le réseau local
        de l'hôte qui rend une collision RÉELLE, et il doit rester vu."""
        vus = self._host_networks(exclure=["virbr0"])
        self.assertIn("192.168.2.0/24", vus)
        self.assertIn("127.0.0.0/8", vus)

    def test_a_line_without_a_readable_device_is_kept(self):
        """Sur « ce /24 est-il libre », le silence pèse du côté prudent : une
        ligne dont l'interface ne se lit pas compte comme occupée. Un pont
        inconnu ('' rendu par network_bridge) n'écarte donc rien."""
        self.assertEqual("", DQ.interface_de_ligne("192.168.9.0/24 proto ra"))
        vus = self._host_networks(exclure=[""])
        self.assertIn("192.168.122.0/24", vus)
        self.assertIn("192.168.2.0/24", vus)

    def test_the_interface_is_read_from_both_grammars(self):
        self.assertEqual(
            "enp6s0", DQ.interface_de_ligne("192.168.2.0/24 dev enp6s0 proto")
        )
        self.assertEqual(
            "virbr0",
            DQ.interface_de_ligne("3: virbr0    inet 192.168.122.1/24 scope"),
        )
        # Une interface appairée porte le nom de son pair : « eth0@if12 ».
        self.assertEqual(
            "eth0", DQ.interface_de_ligne("5: eth0@if12    inet 10.0.0.2/24")
        )


class LePontDuReseau(unittest.TestCase):
    def test_the_bridge_comes_from_the_xml(self):
        self.assertEqual("virbr0", DQ.bridge_from_network_xml(XML_DEFAUT))

    def test_no_bridge_says_nothing(self):
        """'' plutôt qu'un nom deviné : c'est sur lui qu'on écarte une
        interface de la recherche de collision."""
        self.assertEqual("", DQ.bridge_from_network_xml("<network/>"))
        self.assertEqual("", DQ.bridge_from_network_xml(""))


class LeFichierTemporaire(unittest.TestCase):
    """Le XML posé pour « net-define » : imprévisible, et retiré."""

    def test_it_is_removed_even_when_virsh_fails(self):
        with self.assertRaises(RuntimeError):
            with DQ.fichier_xml_temporaire("<network/>") as chemin:
                garde = chemin
                raise RuntimeError("virsh a échoué")
        self.assertFalse(Path(garde).exists())

    def test_the_name_is_not_predictable(self):
        """Un nom composé est un chemin devinable dans un répertoire où tout
        le monde écrit : qui l'occupe d'avance choisit ce que root définit."""
        with DQ.fichier_xml_temporaire("<network/>") as un:
            with DQ.fichier_xml_temporaire("<network/>") as deux:
                self.assertNotEqual(un, deux)

    def test_root_can_read_it(self):
        """virsh lit le fichier sous root, et le fichier temporaire d'un
        utilisateur non privilégié ne l'est pas toujours."""
        with DQ.fichier_xml_temporaire("<network/>") as chemin:
            self.assertTrue(Path(chemin).stat().st_mode & 0o044)


class LeSousReseauLibre(unittest.TestCase):
    def test_it_starts_above_the_two_usual_ones(self):
        """122 est celui de libvirt, 123 celui de beaucoup d'installations
        toutes faites : partir au-dessus des deux coûte un octet."""
        self.assertEqual(131, DQ.LIBVIRT_NET_BASE)
        self.assertEqual("192.168.131", DQ.free_subnet(reseaux()))

    def test_it_skips_what_is_taken(self):
        pris = reseaux("192.168.131.0/24", "192.168.132.0/24")
        self.assertEqual("192.168.133", DQ.free_subnet(pris))

    def test_a_saturated_range_says_so(self):
        """'' et non un sous-réseau au hasard : l'appelant doit pouvoir dire
        qu'il ne déplace rien."""
        pris = reseaux("192.168.0.0/16")
        self.assertEqual("", DQ.free_subnet(pris))


class LeDeplacement(unittest.TestCase):
    def test_the_network_keeps_its_identity(self):
        """Réécrit plutôt que reconstruit : l'UUID, le pont et le MAC restent,
        donc les domaines qui nomment ce réseau le retrouvent."""
        bouge = DQ.moved_network_xml(XML_DEFAUT, "192.168.122", "192.168.131")
        self.assertIn("2cf1310d-8812-456e-b761-9867efe4af8d", bouge)
        self.assertIn("<bridge name='virbr0'", bouge)
        self.assertIn("52:54:00:6b:6d:2f", bouge)

    def test_the_whole_subnet_moves(self):
        bouge = DQ.moved_network_xml(XML_DEFAUT, "192.168.122", "192.168.131")
        self.assertNotIn("192.168.122.", bouge)
        self.assertIn("<ip address='192.168.131.1'", bouge)
        self.assertIn("start='192.168.131.2'", bouge)
        self.assertIn("end='192.168.131.254'", bouge)
        self.assertEqual("192.168.131.0/24", DQ.cidr_from_network_xml(bouge))


class LOrdreDesGestes(unittest.TestCase):
    """ensure_network : déplacer, démarrer, puis armer — et pas autrement."""

    def _lancer(self, cidrs, hote, actif_apres, etat_initial):
        """Rend les commandes virsh lancées, dans l'ordre.

        `cidrs` : ce que « default » sert, avant puis après un déplacement.
        `hote` : ce que la machine route. `actif_apres` : le réseau démarre-t-il ?
        """
        runner = mock.MagicMock()
        runner.dry_run = False
        runner.use_sudo = False
        lancees = []
        runner.run.side_effect = lambda cmd, **kw: lancees.append(
            [x for x in cmd if x not in ("virsh", "-c", DQ.LIBVIRT_URI)]
        )
        suite_cidr = list(cidrs)
        etats = [etat_initial, (actif_apres, etat_initial[1])]

        with mock.patch.object(
            DQ,
            "network_cidr",
            side_effect=lambda *a: (
                suite_cidr.pop(0) if len(suite_cidr) > 1 else suite_cidr[0]
            ),
        ), mock.patch.object(
            DQ, "host_networks", return_value=reseaux(*hote)
        ), mock.patch.object(
            DQ, "libvirt_networks_cidrs", return_value=[]
        ), mock.patch.object(
            DQ, "virsh_out", return_value=XML_DEFAUT
        ), mock.patch.object(
            DQ,
            "network_state",
            side_effect=lambda *a: (
                etats.pop(0) if len(etats) > 1 else etats[0]
            ),
        ):
            with redirect_stdout(io.StringIO()) as sortie:
                DQ.ensure_network("default", runner)
        return lancees, sortie.getvalue()

    def test_a_colliding_network_is_moved_before_being_started(self):
        """La redéfinition ne demande ni pont ni module du noyau : elle passe
        là où le démarrage ne passe pas."""
        lancees, texte = self._lancer(
            cidrs=["192.168.122.0/24", "192.168.131.0/24"],
            hote=["192.168.122.0/24"],
            actif_apres=True,
            etat_initial=(False, False),
        )
        verbes = [c[0] for c in lancees]
        self.assertEqual(["net-define", "net-start", "net-autostart"], verbes)
        self.assertIn("192.168.131.0/24", texte)

    def test_autostart_is_never_armed_on_a_collision(self):
        """Le geste qui cassait la machine. Sans /24 libre, rien n'est
        déplacé — et alors rien n'est armé."""
        lancees, texte = self._lancer(
            cidrs=["192.168.122.0/24"],
            hote=["192.168.0.0/16"],
            actif_apres=False,
            etat_initial=(False, False),
        )
        self.assertNotIn("net-autostart", [c[0] for c in lancees])

    def test_an_armed_collision_is_disarmed(self):
        """L'état dans lequel --setup-host laissait la machine : un réseau
        inactif, en collision, et armé pour le prochain démarrage."""
        lancees, texte = self._lancer(
            cidrs=["192.168.122.0/24"],
            hote=["192.168.0.0/16"],
            actif_apres=False,
            etat_initial=(False, True),
        )
        self.assertIn(["net-autostart", "--disable", "default"], lancees)
        self.assertIn("autostart RETIRÉ", texte)

    def test_a_stale_kernel_keeps_the_one_reboot_shortcut(self):
        """Sans collision, un réseau qui ne démarre pas faute de modules du
        noyau reste armé : au retour du redémarrage, libvirt le monte seul et
        l'hôte est utilisable sans repasser par --setup-host."""
        lancees, _ = self._lancer(
            cidrs=["192.168.131.0/24"],
            hote=["192.168.122.0/24"],
            actif_apres=False,
            etat_initial=(False, False),
        )
        verbes = [c[0] for c in lancees]
        self.assertEqual(["net-start", "net-autostart"], verbes)

    def test_a_healthy_network_is_left_alone(self):
        """Idempotence : relancer --setup-host sur un hôte prêt ne doit rien
        lancer, et surtout pas redéfinir le réseau sous les VM qui tournent."""
        lancees, _ = self._lancer(
            cidrs=["192.168.131.0/24"],
            hote=["192.168.122.0/24"],
            actif_apres=True,
            etat_initial=(True, True),
        )
        self.assertEqual([], lancees)

    def test_an_active_network_without_collision_is_never_moved(self):
        """Le déplacer casserait les VM qui y sont attachées pour un danger
        qui n'existe pas."""
        lancees, _ = self._lancer(
            cidrs=["192.168.131.0/24"],
            hote=["192.168.122.0/24"],
            actif_apres=True,
            etat_initial=(True, True),
        )
        self.assertNotIn("net-define", [c[0] for c in lancees])

    def test_an_active_collision_is_torn_down_first(self):
        """La machine DÉJÀ cassée, celle qu'on retrouve après le démarrage
        fautif : le pont porte l'adresse de la passerelle. L'abattre rend
        l'accès au réseau avant toute autre chose — sans quoi il n'y a même
        pas de quoi télécharger un correctif."""
        lancees, texte = self._lancer(
            cidrs=["192.168.122.0/24", "192.168.131.0/24"],
            hote=["192.168.122.0/24"],
            actif_apres=True,
            etat_initial=(True, True),
        )
        verbes = [c[0] for c in lancees]
        self.assertEqual("net-destroy", verbes[0])
        self.assertLess(
            verbes.index("net-destroy"), verbes.index("net-define")
        )
        self.assertIn("rendre l'accès au réseau", texte)


if __name__ == "__main__":
    unittest.main()
