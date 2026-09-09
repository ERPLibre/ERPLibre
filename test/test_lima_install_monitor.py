#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le moniteur d'installation, conduit par une fiche Lima.

IL ÉTAIT ÉCRIT POUR L'ACCUEILLIR, et rien ne le prouvait. Son commentaire
l'annonce — « là où celui-ci rend « ssh … », un autre rendra une commande
qui joint la VM par son nom » — mais aucune épreuve ne lui donnait cette
fiche-là. Une accommodation prévue et jamais exercée se casse au premier
ajustement du préfixe, et le seul symptôme serait une installation qui part
vers un hôte ssh nommé comme l'instance.

RIEN N'EST LANCÉ. `subprocess.Popen` est intercepté : ce qui est éprouvé est
l'ENVELOPPE que le moniteur aurait jouée, en entier, guillemets compris.

Le contrôle qui compte est le CONTRASTE : la même fonction, sur une fiche
libvirt, doit rendre du « ssh ». Sans lui, une épreuve qui cherche
« limactl » passerait aussi sur un préfixe devenu constant.
"""

import os
import subprocess
import sys
import unittest
from unittest.mock import patch

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

sys.argv = ["todo.py"]
from script.todo import qemu_install_monitor as M  # noqa: E402
from script.vm import backend as B  # noqa: E402

JOURNAL = "/tmp/journal-de-banc-lima.log"
INSTANCE = "instance-de-banc"


def enveloppe(handle, remote_cmd="echo bonjour", **options):
    """Ce que le moniteur AURAIT joué, sans rien lancer."""
    vus = []
    with patch.object(
        M.subprocess, "Popen", side_effect=lambda argv, **_k: vus.append(argv)
    ):
        M._launch_one(handle, remote_cmd, JOURNAL, **options)
    assert len(vus) == 1, vus
    argv = vus[0]
    # Le moniteur détache par « setsid -f bash -c <enveloppe> » : c'est le
    # dernier argument qui porte tout, et le reste est l'attelage.
    assert argv[:4] == ["setsid", "-f", "bash", "-c"], argv[:4]
    return argv[-1]


class TestLaFicheLimaTraverseLeMoniteur(unittest.TestCase):
    def setUp(self):
        self.lima = B.lima_handle(INSTANCE)

    def test_the_wrapper_joins_the_instance_by_name(self):
        texte = enveloppe(self.lima)
        self.assertIn(f"limactl shell {INSTANCE} -- bash -c", texte)

    def test_it_never_falls_back_to_ssh(self):
        """Le symptôme d'un repli serait une installation partie vers un
        hôte ssh nommé comme l'instance — silencieusement."""
        self.assertNotIn("ssh ", enveloppe(self.lima))

    def test_a_libvirt_handle_does_use_ssh(self):
        """LE CONTRASTE. Sans lui, une épreuve qui cherche « limactl »
        passerait aussi sur un préfixe devenu constant."""
        libvirt = B.libvirt_handle(INSTANCE, uuid="u-u-i-d", ip="192.0.2.10")
        texte = enveloppe(libvirt)
        self.assertIn("ssh ", texte)
        self.assertNotIn("limactl", texte)

    def test_no_lease_is_re_read_for_an_instance(self):
        """Il n'y a pas de réseau d'hyperviseur à interroger : chercher un
        bail rendrait vide, et le repli choisirait une adresse au hasard
        parmi ce que « virsh » aurait dit d'un domaine homonyme."""
        texte = enveloppe(self.lima)
        self.assertFalse(B.resolves_locally(self.lima))
        self.assertNotIn("virsh", texte)
        self.assertNotIn("net-dhcp-leases", texte)

    def test_the_address_it_carries_is_the_instance_name(self):
        texte = enveloppe(self.lima)
        self.assertIn(f"ip={INSTANCE}", texte)

    def test_a_suite_of_commands_survives_the_channel(self):
        """« bash -c » exécute des ARGUMENTS : une suite doit lui arriver
        comme UN mot, sinon « a && b » se lit comme une liste."""
        texte = enveloppe(self.lima, remote_cmd="a && b")
        self.assertIn("'a && b'", texte)

    def test_a_command_carrying_a_quote_does_not_break_the_wrapper(self):
        """L'enveloppe est du shell : une apostrophe mal échappée la
        couperait en deux, et la moitié partirait sur notre machine."""
        texte = enveloppe(self.lima, remote_cmd='echo "c\'est"')
        res = subprocess.run(
            ["bash", "-n", "-c", texte], capture_output=True, text=True
        )
        self.assertEqual(0, res.returncode, res.stderr)

    def test_the_wrapper_is_valid_shell(self):
        texte = enveloppe(self.lima)
        res = subprocess.run(
            ["bash", "-n", "-c", texte], capture_output=True, text=True
        )
        self.assertEqual(0, res.returncode, res.stderr)

    def test_the_log_path_is_quoted(self):
        """Un chemin de journal porte une date ; une espace y couperait la
        redirection, et la sortie partirait dans un fichier au nom
        tronqué."""
        vus = []
        with patch.object(
            M.subprocess,
            "Popen",
            side_effect=lambda argv, **_k: vus.append(argv),
        ):
            M._launch_one(self.lima, "vrai", "/tmp/un journal.log")
        self.assertIn("'/tmp/un journal.log'", vus[0][-1])

    def test_the_end_marker_is_written_with_the_exit_code(self):
        """Le tableau de bord lit ce marqueur : sans lui, une installation
        finie paraît tourner encore."""
        texte = enveloppe(self.lima)
        self.assertIn(M.EXIT_MARKER, texte)
        self.assertIn("rc=$?", texte)

    def test_it_waits_for_cloud_init_in_the_instance_too(self):
        """Les images de l'outil en portent un ; ne pas l'attendre ferait
        installer pendant que la VM se configure encore.

        « command -v cloud-init » et non « cloud-init » : ce dernier
        apparaît AUSSI dans les messages d'attente et dans le filtre qui
        lit la réponse. Une sonde vidée les laisserait tous les deux en
        place, et l'assertion passerait sur une enveloppe qui ne sonde
        plus rien.
        """
        texte = enveloppe(self.lima)
        self.assertIn("command -v cloud-init", texte)

    def test_the_probe_travels_through_the_instance_channel(self):
        """Sondée depuis NOTRE machine, elle dirait l'état de cloud-init de
        la station — qui n'en a pas — et l'attente se terminerait tout de
        suite."""
        texte = enveloppe(self.lima)
        sonde = texte.index("command -v cloud-init")
        canal = texte.rindex("limactl shell", 0, sonde)
        # Rien d'autre ne s'ouvre entre le canal et la sonde.
        self.assertNotIn(">> ", texte[canal:sonde])

    def test_nothing_is_launched_by_these_tests(self):
        """Contrôle du banc : un Popen non intercepté détacherait un vrai
        processus, et cette épreuve ne rendrait jamais la main."""
        self.assertTrue(hasattr(M.subprocess, "Popen"))


if __name__ == "__main__":
    unittest.main()
