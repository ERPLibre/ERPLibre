#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le manifeste d'installation, écrit pour une instance et non pour un ssh.

CE QUE LE TABLEAU DE BORD AFFICHE POUR QU'ON LE RECOPIE. Le champ « ssh »
d'une entrée était composé à la main — « ssh compte@<adresse> » — de TOUTE
machine, y compris de celles qui ne s'atteignent pas par ssh. Recopiée, une
telle ligne échoue chez celui qui la recopie, et rien dans le message de ssh
ne dit que le backend était le mauvais.

RIEN N'EST LANCÉ. `_launch_one` est intercepté ; ce qui est éprouvé est le
`session.json` écrit sur disque, dans un répertoire temporaire.

Le contrôle qui compte est le CONTRASTE : la même fonction, sur une entrée
libvirt, doit écrire une ligne ssh. Sans lui, une épreuve qui cherche
« limactl » passerait aussi sur un champ devenu constant.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

sys.argv = ["todo.py"]
from script.todo import qemu_install_monitor as M  # noqa: E402
from script.vm import lima as L  # noqa: E402

INSTANCE = "instance-de-banc"


class CasDeManifeste(unittest.TestCase):
    """Le répertoire de session est déplacé : écrire dans
    ~/.erplibre/qemu-install polluerait les suivis de qui lance l'épreuve."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.lances = []
        patcheur = patch.object(
            M, "session_dir", return_value=Path(self.tmp.name)
        )
        patcheur.start()
        self.addCleanup(patcheur.stop)
        lanceur = patch.object(
            M,
            "_launch_one",
            side_effect=lambda *a, **k: self.lances.append((a, k)),
        )
        lanceur.start()
        self.addCleanup(lanceur.stop)

    def manifeste(self, *vms, branch="mabranche", remote="vrai"):
        chemin = M.launch_installs(list(vms), branch, remote)
        with open(chemin, encoding="utf-8") as fichier:
            return json.load(fichier)


class TestUneInstanceDansLeManifeste(CasDeManifeste):
    ENTREE = {"name": INSTANCE, "ip": INSTANCE, "lima": True}

    def test_the_connect_line_is_the_tool_and_not_ssh(self):
        vu = self.manifeste(dict(self.ENTREE))["vms"][0]
        self.assertEqual(L.display(L.shell_argv(INSTANCE)), vu["ssh"])
        self.assertNotIn("ssh ", vu["ssh"])

    def test_a_libvirt_entry_does_get_an_ssh_line(self):
        """LE CONTRASTE : sans lui, une épreuve qui cherche « limactl »
        passerait aussi sur un champ devenu constant."""
        vu = self.manifeste(
            {"name": "vm-locale", "ip": "192.0.2.10", "uuid": "u-u-i-d"}
        )["vms"][0]
        self.assertIn("ssh ", vu["ssh"])
        self.assertIn("192.0.2.10", vu["ssh"])
        self.assertNotIn("limactl", vu["ssh"])

    def test_the_entry_says_which_backend_will_re_read_it(self):
        """Sans ce drapeau, `handle_of` rebâtirait une fiche libvirt au
        prochain ouvrage du suivi, et la suppression viserait un domaine
        local homonyme."""
        vu = self.manifeste(dict(self.ENTREE))["vms"][0]
        self.assertIs(True, vu.get("lima"))
        self.assertNotIn("uuid", vu)

    def test_no_identity_proof_is_invented_for_an_instance(self):
        """Elle n'en a pas, et la fabriquer armerait un garde qui ne garde
        rien."""
        vu = self.manifeste(dict(self.ENTREE))["vms"][0]
        self.assertNotIn("pve", vu)

    def test_the_launcher_receives_an_instance_handle(self):
        self.manifeste(dict(self.ENTREE))
        self.assertEqual(1, len(self.lances))
        fiche = self.lances[0][0][0]
        self.assertEqual("lima", fiche.backend)
        self.assertEqual(INSTANCE, fiche.key)

    def test_an_instance_never_carries_a_reboot(self):
        """Le redémarrage n'est déclenché que par l'installation de
        Proxmox, qui n'a aucun sens dans une instance — et ses étapes
        entrent par ssh, en clair dans leur propre code."""
        self.manifeste(dict(self.ENTREE), remote="make install_odoo_18")
        self.assertEqual("", self.lances[0][1]["reboot"])

    def test_two_machines_of_two_backends_keep_their_own_line(self):
        """Un parc mixte est le cas normal : une ligne partagée en
        enverrait une moitié au mauvais endroit."""
        vus = self.manifeste(
            dict(self.ENTREE),
            {"name": "vm-locale", "ip": "192.0.2.10", "uuid": "u"},
        )["vms"]
        self.assertIn("limactl", vus[0]["ssh"])
        self.assertIn("ssh ", vus[1]["ssh"])

    def test_the_log_is_written_and_named_after_the_instance(self):
        vu = self.manifeste(dict(self.ENTREE))["vms"][0]
        self.assertTrue(os.path.exists(vu["log"]))
        self.assertTrue(vu["log"].endswith(f"{INSTANCE}.log"))


class TestLeBancNeLancePersonne(CasDeManifeste):
    def test_nothing_is_detached_by_these_tests(self):
        """Un `_launch_one` non intercepté détacherait un vrai processus
        qui parlerait à une instance qui n'existe pas."""
        self.manifeste({"name": INSTANCE, "ip": INSTANCE, "lima": True})
        self.assertEqual(1, len(self.lances))

    def test_nothing_is_written_outside_the_temporary_directory(self):
        chemin = M.launch_installs(
            [{"name": INSTANCE, "ip": INSTANCE, "lima": True}], "b", "vrai"
        )
        self.assertTrue(chemin.startswith(self.tmp.name), chemin)


class TestAucuneLigneNEstPlusComposeeALaMain(unittest.TestCase):
    """DEUX sites l'écrivaient, et le second vit dans un tableau de bord
    asynchrone qu'aucune épreuve ne pilote.

    L'invariant porte donc sur le TEXTE du module : aucun littéral qui
    compose une ligne de connexion. Il couvre les deux sites d'un coup et
    toute rechute future, là où éprouver le second demanderait de faire
    tourner Textual.

    Les commentaires n'en sont pas — ce ne sont pas des chaînes — donc
    celui qui RACONTE le défaut d'origine reste, et c'est bien.
    """

    @staticmethod
    def litteraux(aiguille):
        from code_literals import literals_in_file

        chemin = os.path.join(
            RACINE, "script", "todo", "qemu_install_monitor.py"
        )
        return literals_in_file(chemin, aiguille)

    def test_no_literal_composes_a_connection_line(self):
        trouves = self.litteraux("erplibre@")
        self.assertEqual([], trouves, trouves)

    def test_the_sweep_reads_the_right_file(self):
        """Contrôle du banc : un chemin fautif rendrait zéro littéral, et
        l'épreuve passerait sans avoir rien lu."""
        self.assertTrue(self.litteraux("cloud-init"))

    def test_the_verb_is_what_both_sites_call(self):
        chemin = os.path.join(
            RACINE, "script", "todo", "qemu_install_monitor.py"
        )
        with open(chemin, encoding="utf-8") as fichier:
            source = fichier.read()
        self.assertEqual(2, source.count("vm_verbs.connect_command("))


if __name__ == "__main__":
    unittest.main()
