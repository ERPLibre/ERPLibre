#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les colonnes vivantes d'une VM posée sur un hôte Proxmox distant.

Elles venaient toutes de virsh : état, durée, écrit/s, RAM, disque. Or virsh
ne connaît pas les VM d'un hôte Proxmox — elles restaient donc VIDES, et le
relevé d'état les déclarait même « effacées », ce qui éteignait le reste.

L'hôte sait tout cela : « pvesh get /cluster/resources --type vm » rend
l'état, la mémoire, le disque et le cumul écrit de TOUTES ses VM en un appel.
Le relevé prend la forme exacte de celui de virsh, pour que le calcul du
débit, de la RAM et des colonnes ne sache pas d'où vient la mesure.
"""

import sys
import unittest
from unittest import mock

sys.argv = ["todo.py"]
from script.todo import qemu_install_monitor as mon  # noqa: E402

# Sortie RÉELLE relevée sur l'hôte d'essai (une VM, stockage en fichiers :
# Proxmox y rapporte « disk: 0 », d'où le « du » qui suit).
REPONSE = (
    '[{"cpu":0.01,"disk":0,"diskread":32633856,"diskwrite":328233472,'
    '"id":"qemu/100","maxcpu":1,"maxdisk":4294967296,"maxmem":536870912,'
    '"mem":385351680,"name":"pve-suivi","netin":190,"netout":0,'
    '"node":"erplibre-proxmox-9","status":"running","template":0,'
    '"type":"qemu","uptime":127,"vmid":100}]\n'
    "---ERPLIBRE-DU---\n"
    "4294971392\t/var/lib/vz/images/100/\n"
)


class TestLaLecture(unittest.TestCase):
    def setUp(self):
        self.releves = mon.parse_pvestats(REPONSE)

    def test_the_vm_is_keyed_by_its_name(self):
        # Le suivi raisonne en NOMS : c'est ce que porte le manifeste.
        self.assertEqual(list(self.releves), ["pve-suivi"])

    def test_the_shape_matches_the_virsh_one(self):
        # Même forme exprès : `ram_pair`, `WriteWindow` et les colonnes
        # fonctionnent alors sans distinguer la source.
        attendus = {
            "ram_used",
            "ram_total",
            "ram_at",
            "wr_bytes",
            "disk_used",
            "disk_total",
        }
        self.assertTrue(attendus <= set(self.releves["pve-suivi"]))

    def test_the_measures_are_the_ones_the_host_gave(self):
        rec = self.releves["pve-suivi"]
        self.assertEqual(rec["ram_used"], 385351680)
        self.assertEqual(rec["ram_total"], 536870912)
        self.assertEqual(rec["wr_bytes"], 328233472)
        self.assertEqual(rec["state"], "running")
        self.assertEqual(rec["uptime"], 127)

    def test_a_zero_disk_falls_back_to_the_real_size(self):
        # Sur un stockage en fichiers, Proxmox NE CALCULE PAS la taille
        # occupée et rapporte 0 : la colonne aurait affiché « 0/4G ».
        self.assertEqual(self.releves["pve-suivi"]["disk_used"], 4294971392)
        self.assertEqual(self.releves["pve-suivi"]["disk_total"], 4294967296)

    def test_the_reading_is_fresh_so_the_ram_is_shown(self):
        # `ram_pair` refuse un relevé périmé : sans horodatage, la RAM d'une
        # VM distante ne s'afficherait jamais.
        rec = self.releves["pve-suivi"]
        self.assertNotEqual(mon.ram_pair(rec, rec["ram_at"]), "-")

    def test_garbage_yields_nothing_rather_than_raising(self):
        for brut in ("", "pas du json", "{}", "---ERPLIBRE-DU---"):
            self.assertEqual(mon.parse_pvestats(brut), {})


class TestLAppel(unittest.TestCase):
    """Un appel par HÔTE, mis en cache : chaque tour coûte une poignée de
    main ssh (1 s mesuré) quand virsh coûte 0,03 s pour tout le parc."""

    def setUp(self):
        mon._PVE_CACHE.update({"at": 0.0, "stats": {}})

    def _vms(self, n=2):
        return [
            {
                "name": f"vm-{i}",
                "pve": {
                    "target": "erplibre@pve1",
                    "sudo": "sudo ",
                    "vmid": 100 + i,
                },
            }
            for i in range(n)
        ]

    def test_two_vms_of_the_same_host_cost_one_call(self):
        with mock.patch(
            "script.proxmox.proxmox_deploy.run", return_value=(0, REPONSE)
        ) as appel:
            mon.read_pvestats(self._vms(2), now=1000.0)
        self.assertEqual(appel.call_count, 1)

    def test_a_local_only_plan_calls_nothing(self):
        with mock.patch("script.proxmox.proxmox_deploy.run") as appel:
            self.assertEqual(mon.read_pvestats([{"name": "locale"}]), {})
        appel.assert_not_called()

    def test_the_cache_spares_the_next_tick(self):
        with mock.patch(
            "script.proxmox.proxmox_deploy.run", return_value=(0, REPONSE)
        ) as appel:
            mon.read_pvestats(self._vms(1), now=1000.0)
            mon.read_pvestats(self._vms(1), now=1000.0 + 1)
            self.assertEqual(appel.call_count, 1)
            # Passé l'intervalle, on redemande.
            mon.read_pvestats(
                self._vms(1), now=1000.0 + mon.PVE_STATS_INTERVAL + 0.1
            )
            self.assertEqual(appel.call_count, 2)

    def test_a_failing_host_yields_nothing_rather_than_wrong_numbers(self):
        with mock.patch(
            "script.proxmox.proxmox_deploy.run", return_value=(255, "timeout")
        ):
            self.assertEqual(mon.read_pvestats(self._vms(1), now=1.0), {})


class TestPasDePoubelleTropTot(unittest.TestCase):
    """« Effacée » est un état TERMINAL : la ligne gèle sur 🗑 pour de bon.

    Rapporté sur une VM Arch déployée sur Proxmox : poubelle dès le premier
    tour, alors que la VM venait de naître. Un relevé manquant ne prouve
    rien — l'hôte peut être occupé, la VM en train de démarrer, le relevé en
    cache d'avant sa création.
    """

    def setUp(self):
        mon._PVE_CACHE.update({"at": 0.0, "stats": {}, "ok": False})

    def _vm(self):
        return {
            "name": "vm-a",
            "pve": {
                "target": "hote",
                "sudo": "sudo ",
                "vmid": 105,
                "addr": "10.10.10.155",
            },
        }

    def test_a_silent_host_is_not_a_deletion(self):
        # (relevés, succès) : la nuance est tout le correctif.
        with mock.patch(
            "script.proxmox.proxmox_deploy.run", return_value=(255, "timeout")
        ):
            stats, ok = mon.read_pvestats_detail([self._vm()], now=1.0)
        self.assertEqual(stats, {})
        self.assertFalse(ok)

    def test_a_host_that_answers_says_so(self):
        with mock.patch(
            "script.proxmox.proxmox_deploy.run", return_value=(0, "[]")
        ):
            stats, ok = mon.read_pvestats_detail([self._vm()], now=1.0)
        self.assertEqual(stats, {})
        self.assertTrue(ok, "l'hôte a répondu : la VM est vraiment absente")

    def test_the_cache_keeps_the_verdict_too(self):
        with mock.patch(
            "script.proxmox.proxmox_deploy.run", return_value=(0, "[]")
        ) as appel:
            mon.read_pvestats_detail([self._vm()], now=100.0)
            _stats, ok = mon.read_pvestats_detail([self._vm()], now=100.5)
        self.assertEqual(appel.call_count, 1)
        self.assertTrue(ok, "le cache rendait « échec » à chaque tour suivant")

    def test_it_takes_several_absences_to_conclude(self):
        # Trois, pas une : le nombre est explicite, pas enfoui.
        self.assertGreaterEqual(mon.PVE_ABSENCES_AVANT_EFFACEE, 2)

    def test_the_short_reader_still_returns_only_stats(self):
        # `read_pvestats` reste la forme courte pour la boucle des colonnes.
        with mock.patch(
            "script.proxmox.proxmox_deploy.run", return_value=(0, "[]")
        ):
            self.assertEqual(mon.read_pvestats([self._vm()], now=7.0), {})


class TestLesAutresCheminsVersLaPoubelle(unittest.TestCase):
    """Trouvés par un audit, pas à l'usage : trois autres façons d'arriver au
    🗑 sur un seul incident. « Effacée » gèle la ligne pour de bon, donc
    chacune valait un correctif."""

    def test_a_broken_pvesh_is_not_an_answer(self):
        # La commande est une SUITE : son code de sortie est celui du DERNIER
        # maillon. Un pvesh en panne rendait « l'hôte a répondu, la VM n'y est
        # plus » — et trois tours plus tard, la poubelle.
        self.assertFalse(
            mon._resources_parsable("permission denied\n---ERPLIBRE-DU---\n")
        )
        self.assertTrue(mon._resources_parsable("[]\n---ERPLIBRE-DU---\n"))

    def test_a_failing_host_never_counts_as_an_answer(self):
        mon._PVE_CACHE.update({"at": 0.0, "stats": {}, "ok": False})
        vm = {"name": "vm-a", "pve": {"target": "h", "sudo": "", "vmid": 1}}
        with mock.patch(
            "script.proxmox.proxmox_deploy.run",
            return_value=(0, "sudo: a password is required\n"),
        ):
            _stats, ok = mon.read_pvestats_detail([vm], now=10.0)
        self.assertFalse(ok, "code 0 ne prouve pas que pvesh a parlé")

    def test_an_unknown_proxmox_status_is_not_a_deletion(self):
        # Proxmox en a d'autres que les trois attendus : « prelaunch »,
        # « suspended », « internal-error », « hibernated ».
        for etat in ("prelaunch", "suspended", "internal-error", "hibernated"):
            self.assertIsNone(
                mon.PVE_ETATS.get(etat),
                "l'état n'est pas dans la table : le repli doit être « la VM"
                " existe », pas « gone »",
            )

    def test_the_absence_counter_is_explicit(self):
        self.assertGreaterEqual(mon.PVE_ABSENCES_AVANT_EFFACEE, 2)


class TestCeQueLaConfirmationPromet(unittest.TestCase):
    """La confirmation de suppression annonçait un fichier qcow2 local à
    TOUTE VM, Proxmox comprise.

    Sur une VM Proxmox ce fichier n'existe pas : son disque vit dans un
    stockage que seul l'hôte connaît. La ligne désignait donc un chemin local
    — au mieux inexistant, au pire celui d'une autre VM du même nom. C'est
    exactement la peur qui avait fait remonter le nettoyage : « le nettoyage
    risque d'effacer des VM en production »."""

    def test_a_proxmox_vm_never_shows_a_local_path(self):
        lignes = mon.delete_lines(
            {"name": "vm-a", "pve": {"target": "pve9", "vmid": 101}}
        )
        texte = " ".join(lignes)
        self.assertNotIn("/var/lib/libvirt", texte)
        self.assertNotIn("qcow2", texte)

    def test_it_names_the_host_and_the_vmid(self):
        # Le nom ne suffit pas : deux VM peuvent le porter, seul le VMID est
        # unique — et il faut savoir SUR QUELLE machine ça se passe.
        texte = " ".join(
            mon.delete_lines(
                {"name": "vm-a", "pve": {"target": "pve9", "vmid": 101}}
            )
        )
        self.assertIn("pve9", texte)
        self.assertIn("101", texte)
        self.assertIn("qm destroy 101", texte)

    def test_a_local_vm_still_names_its_file(self):
        # La voie libvirt ne régresse pas : là, le fichier EST ce qu'on efface.
        texte = " ".join(mon.delete_lines({"name": "vm-a"}))
        self.assertIn("/var/lib/libvirt/images/vm-a.qcow2", texte)


class TestQuandLeVertRedescend(unittest.TestCase):
    """Le 🟢 était acquis pour toujours.

    « Odoo ne redescend pas en cours d'install » : c'était faux. Le service
    redémarre au moins une fois — systemd l'active à la fin du make — et il
    lui arrive de mourir. La VM restait verte en servant plus rien, et c'est
    précisément le moment où on veut le savoir."""

    def _sonde(self, reponse):
        return lambda _ip, _port: reponse

    def test_a_local_vm_that_stopped_answering_goes_back(self):
        etat, sonde = mon.odoo_reading(
            {"ip": "10.0.0.1"},
            {},
            deja_vert=True,
            dernier=0.0,
            maintenant=mon.ODOO_RECHECK + 1,
            sonde=self._sonde(False),
        )
        self.assertIs(etat, False)
        self.assertTrue(sonde)

    def test_a_green_local_vm_is_not_probed_every_tick(self):
        # La sonde est un connect() TCP par VM : à chaque tour (2 s) c'est
        # cher pour une réponse qui ne bouge presque jamais.
        etat, sonde = mon.odoo_reading(
            {"ip": "10.0.0.1"},
            {},
            deja_vert=True,
            dernier=100.0,
            maintenant=101.0,
            sonde=self._sonde(False),
        )
        self.assertIsNone(etat, "rien de neuf ne doit être affirmé")
        self.assertFalse(sonde)

    def test_a_red_local_vm_is_probed_every_tick(self):
        _etat, sonde = mon.odoo_reading(
            {"ip": "10.0.0.1"},
            {},
            deja_vert=False,
            dernier=100.0,
            maintenant=101.0,
            sonde=self._sonde(True),
        )
        self.assertTrue(sonde)

    def test_a_proxmox_vm_is_read_every_tick_for_free(self):
        # Le port est testé DEPUIS L'HÔTE, avec les statistiques : d'ici, une
        # adresse de pont interne ne répond jamais.
        def lu(odoo):
            return mon.odoo_reading(
                {"pve": {"vmid": 1}},
                {"odoo": odoo},
                deja_vert=True,
                dernier=0.0,
                maintenant=1.0,
                sonde=self._sonde(True),
            )[0]

        self.assertIs(lu(True), True)
        self.assertIs(lu(False), False)

    def test_a_silent_host_is_not_a_dead_odoo(self):
        # Sans relevé, on ne sait RIEN : l'appelant garde le dernier état.
        etat, _s = mon.odoo_reading(
            {"pve": {"vmid": 1}},
            {},
            deja_vert=True,
            dernier=0.0,
            maintenant=1.0,
            sonde=self._sonde(True),
        )
        self.assertIsNone(etat)


class TestLaBonneMachine(unittest.TestCase):
    """Le pire défaut de la série : l'installation partie AILLEURS.

    Vécu le 24 août 2026. Une VM déployée sur Proxmox sous le nom
    « erplibre-ubuntu-2604 » — nom déjà porté par un domaine LOCAL. Le
    lanceur détaché ré-résout l'adresse de la VM à chaque tour par virsh, qui
    a répondu avec le domaine local : ERPLibre + Odoo se sont installés sur la
    MAUVAISE machine, et le journal l'affichait sans que rien n'alerte
    (« → 192.168.123.118 »).

    Pour une VM distante, l'alias ~/.ssh/config est la seule vérité : il
    porte le rebond par l'hôte Proxmox.
    """

    def _wrapper(self, **kw):
        """Le script du lanceur, capturé sans rien exécuter."""
        vus = {}
        vrai = mon.subprocess.Popen

        class FauxPopen:
            def __init__(self, argv, *a, **k):
                vus["argv"] = argv

        mon.subprocess.Popen = FauxPopen
        try:
            mon._launch_one("cible", "echo bonjour", "/dev/null", "vm-a", **kw)
        finally:
            mon.subprocess.Popen = vrai
        return vus["argv"][-1]

    def test_a_local_vm_still_gets_its_address_refreshed(self):
        # Le bail change en cours de route (cloud-init renomme l'hôte) : la
        # ré-résolution est indispensable pour une VM LOCALE.
        script = self._wrapper(pve=False)
        self.assertIn("virsh", script)

    def test_a_proxmox_vm_is_never_re_resolved(self):
        # C'est le correctif : aucun appel à virsh, donc aucun risque de
        # tomber sur un domaine local homonyme.
        script = self._wrapper(pve=True)
        self.assertNotIn("virsh", script)

    def test_the_target_stays_the_alias(self):
        script = self._wrapper(pve=True)
        self.assertIn("ip=cible", script)


class TestLeDisque(unittest.TestCase):
    """La colonne Disque annonçait un disque PLEIN qui ne l'était pas.

    Rapporté : « 6.0G/6.0G » sur une VM dont l'invité disait « 845M utilisés
    sur 5.8G ». La mesure venait de « du -sb », qui rend la taille APPARENTE :
    un disque raw creux la donne entière. « du -sB1 » compte les blocs
    réellement occupés — 1,2 Go, ce qui correspond.
    """

    def test_the_command_counts_real_blocks(self):
        self.assertIn("du -sB1", mon.PVE_STATS_CMD)
        self.assertNotIn("du -sb", mon.PVE_STATS_CMD)

    def test_the_measure_is_read_per_vmid(self):
        texte = (
            '[{"vmid":101,"name":"vm-a","disk":0,"maxdisk":6442450944,'
            '"mem":1,"maxmem":2,"diskwrite":0,"status":"running","uptime":1}]\n'
            "---ERPLIBRE-DU---\n"
            "1268518912\t/var/lib/vz/images/101/\n"
            "4294967296\t/var/lib/vz/images/999/\n"
        )
        rec = mon.parse_pvestats(texte)["vm-a"]
        self.assertEqual(rec["disk_used"], 1268518912)
        self.assertEqual(rec["disk_total"], 6442450944)
        self.assertEqual(
            mon.fmt_pair(rec["disk_used"], rec["disk_total"]), "1.2G/6.0G"
        )


class TestOuVaLaCommande(unittest.TestCase):
    """Chaque action doit viser la BONNE machine.

    Une VM distante et un domaine local peuvent porter le même nom : « s »
    ouvrait la locale, la console ouvrait la console de la locale, et la pause
    suspendait la locale. Le VMID et le rebond sont les seules désignations
    qui ne trompent pas.
    """

    LOCALE = {"name": "vm-a", "ip": "192.168.123.118"}
    DISTANTE = {
        "name": "vm-a",
        "ip": "pve1+vm-a",
        "pve": {
            "target": "erplibre@pve1",
            "sudo": "sudo ",
            "jump": "",
            "vmid": 101,
            "addr": "10.10.10.151",
        },
    }

    def test_ssh_to_a_local_vm_uses_its_address(self):
        self.assertIn(
            "erplibre@192.168.123.118", mon.vm_ssh_prefix(self.LOCALE)
        )
        self.assertNotIn("-J", mon.vm_ssh_prefix(self.LOCALE))

    def test_ssh_to_a_remote_vm_goes_through_the_jump(self):
        cmd = mon.vm_ssh_prefix(self.DISTANTE)
        self.assertIn("-J", cmd)
        self.assertIn("erplibre@pve1", cmd)
        self.assertIn("erplibre@10.10.10.151", cmd)

    def test_without_an_address_it_falls_back_to_the_alias(self):
        vm = {"name": "vm-a", "ip": "pve1+vm-a", "pve": {"target": "pve1"}}
        self.assertIn("erplibre@pve1+vm-a", mon.vm_ssh_prefix(vm))

    def test_the_console_of_a_remote_vm_is_qm_terminal(self):
        cmd = mon.pve_host_cmd(
            self.DISTANTE["pve"], "qm terminal 101", tty=True
        )
        self.assertIn("ssh -t", cmd)
        self.assertIn("qm terminal 101", cmd)
        self.assertIn("sudo", cmd)
        # Et surtout PAS virsh, qui viserait le domaine local homonyme.
        self.assertNotIn("virsh", cmd)

    def test_a_host_without_sudo_is_not_wrapped(self):
        cmd = mon.pve_host_cmd({"target": "root@pve1", "sudo": ""}, "qm list")
        self.assertNotIn("sh -c", cmd)


class TestLaColonneOdoo(unittest.TestCase):
    """Le port 8069 se teste DEPUIS L'HÔTE, dans l'appel déjà payé.

    Sondé depuis le poste, il ne répond jamais pour une VM sur pont interne :
    la colonne restait « — » quel que soit l'état d'Odoo. Un aller-retour ssh
    de plus par tour aurait coûté une seconde ; celui des statistiques est
    déjà là.
    """

    def test_the_probe_rides_along_the_stats_call(self):
        cmd = mon.pve_stats_cmd(["10.10.10.150", "10.10.10.151"])
        self.assertIn("pvesh get /cluster/resources", cmd)
        self.assertIn("/dev/tcp/$a/8069", cmd)
        self.assertIn("10.10.10.151", cmd)

    def test_without_addresses_nothing_is_added(self):
        self.assertEqual(mon.pve_stats_cmd([]), mon.PVE_STATS_CMD)

    def test_the_answer_is_read_per_address(self):
        sortie = (
            "[]\n---ERPLIBRE-DU---\n---ERPLIBRE-ODOO---\n"
            "ODOO 10.10.10.151\n"
        )
        self.assertEqual(mon.parse_odoo_probe(sortie), {"10.10.10.151"})

    def test_a_silent_port_yields_nothing(self):
        self.assertEqual(
            mon.parse_odoo_probe("[]\n---ERPLIBRE-DU---\n"), set()
        )
        self.assertEqual(mon.parse_odoo_probe(""), set())

    def test_the_du_block_is_not_mistaken_for_a_probe(self):
        # Les deux blocs se suivent : le lecteur doit prendre le bon.
        sortie = (
            "[]\n---ERPLIBRE-DU---\n1268518912\t/var/lib/vz/images/101/\n"
            "---ERPLIBRE-ODOO---\nODOO 10.10.10.151\n"
        )
        self.assertEqual(mon.parse_odoo_probe(sortie), {"10.10.10.151"})


class TestLeWebEtLaSuppression(unittest.TestCase):
    """Les deux dernières actions qui visaient la mauvaise machine."""

    INFO = {
        "target": "erplibre-proxmox-9",
        "sudo": "sudo ",
        "jump": "",
        "vmid": 101,
        "addr": "10.10.10.151",
    }

    def test_the_web_view_tunnels_through_the_host(self):
        argv = mon.web_tunnel_argv(self.INFO)
        self.assertEqual(argv[-1], "erplibre-proxmox-9")
        self.assertIn("-L", argv)
        self.assertIn("18069:10.10.10.151:8069", argv)
        # Pas de « -f » : le tunnel se referme par son PID, et « pkill -f »
        # tuait le shell qui l'avait lancé.
        self.assertNotIn("-f", argv)

    def test_a_local_vm_needs_no_tunnel(self):
        self.assertIsNone(mon.web_tunnel_argv(None))
        self.assertIsNone(mon.web_tunnel_argv({"target": "pve1"}))

    def test_the_jump_of_the_host_is_chained(self):
        argv = mon.web_tunnel_argv(dict(self.INFO, jump="rebond"))
        self.assertIn("-J", argv)
        self.assertIn("rebond", argv)

    def test_deleting_a_remote_vm_uses_its_vmid(self):
        cmd = mon.delete_vm_cmd_pve(self.INFO)
        self.assertIn("qm destroy 101", cmd)
        self.assertIn("--purge", cmd)
        # « virsh undefine <nom> » aurait effacé le domaine LOCAL homonyme.
        self.assertNotIn("virsh", cmd)

    def test_deleting_a_local_vm_is_unchanged(self):
        cmd = mon.delete_vm_cmd("vm-a", True)
        self.assertIn("virsh undefine", cmd)
        self.assertIn("/var/lib/libvirt/images/vm-a.qcow2", cmd)


class TestLEtat(unittest.TestCase):
    """Une VM absente de « virsh list » passait pour EFFACÉE."""

    def test_proxmox_states_map_to_libvirt_ones(self):
        self.assertEqual(mon.PVE_ETATS.get("running"), "running")
        self.assertEqual(mon.PVE_ETATS.get("stopped"), "shut off")

    def test_an_unknown_state_is_really_gone(self):
        # Absente de la réponse de l'hôte : la VM a vraiment disparu.
        self.assertIsNone(mon.PVE_ETATS.get(None))
        self.assertIsNone(mon.PVE_ETATS.get("n'importe quoi"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
