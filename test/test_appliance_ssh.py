#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le transport ssh vers une appliance, maintenant que plusieurs le partagent.

Il était éprouvé À TRAVERS le module Proxmox, donc seulement sur les usages
que Proxmox en fait. Devenu partagé, son contrat mérite d'être dit ici : ce
qu'une fiche d'hôte produit comme ligne ssh, ce que « privilège » enveloppe
exactement, et ce que « jouer » rend quand rien ne répond.
"""

import os
import subprocess
import sys
import unittest
from unittest.mock import patch

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

from script.remote import appliance_ssh as A  # noqa: E402


class TestLaLigneSsh(unittest.TestCase):
    """« target » seul suffit : ~/.ssh/config porte déjà le reste."""

    def test_an_alias_alone_produces_a_minimal_line(self):
        argv = A.ssh_argv({"target": "appliance"}, "vrai")
        self.assertEqual("ssh", argv[0])
        self.assertEqual(["appliance", "vrai"], argv[-2:])
        self.assertIn("BatchMode=yes", argv)
        self.assertNotIn("-J", argv)
        self.assertNotIn("-p", argv)

    def test_the_port_and_the_jump_are_added_when_given(self):
        argv = A.ssh_argv(
            {"target": "appliance", "port": "2222", "jump": "rebond"}, "vrai"
        )
        self.assertEqual("2222", argv[argv.index("-p") + 1])
        self.assertEqual("rebond", argv[argv.index("-J") + 1])

    def test_a_tty_drops_batch_mode_and_asks_for_one(self):
        """BatchMode interdit toute invite ; un mot de passe en réclame une."""
        argv = A.ssh_argv({"target": "appliance"}, "vrai", tty=True)
        self.assertIn("-t", argv)
        self.assertNotIn("BatchMode=yes", argv)

    def test_the_remote_command_stays_one_argument(self):
        """Le découper laisserait ssh recoller les morceaux à sa façon."""
        argv = A.ssh_argv({"target": "appliance"}, "a && b || c")
        self.assertEqual("a && b || c", argv[-1])


class TestLElevationEnveloppeToutLaSuite(unittest.TestCase):
    """« sudo <suite> » n'élèverait que le PREMIER mot."""

    def test_it_wraps_the_whole_command_and_not_its_first_word(self):
        eleve = A.wrap_privilege("mkdir /root/x && echo ok > /root/y", "sudo")
        self.assertTrue(eleve.startswith("sudo sh -c "))
        # Le tout est UN argument : la redirection est celle du shell élevé.
        self.assertIn("mkdir /root/x && echo ok > /root/y", eleve)
        self.assertFalse(eleve.startswith("sudo mkdir"))

    def test_without_a_prefix_the_command_is_untouched(self):
        self.assertEqual("qm list", A.wrap_privilege("qm list", ""))

    def test_the_wrapped_command_survives_a_shell_round_trip(self):
        """Le contrôle qui compte : la suite doit s'exécuter ENTIÈRE."""
        eleve = A.wrap_privilege("echo un && echo deux", "sudo")
        sans_sudo = eleve[len("sudo ") :]
        res = subprocess.run(
            ["bash", "-c", sans_sudo], capture_output=True, text=True
        )
        self.assertEqual("un\ndeux", res.stdout.strip())


class TestCeQueSshAjouteEstRetire(unittest.TestCase):
    """Une ligne de ssh n'apprend rien sur la commande jouée."""

    def test_its_own_lines_go(self):
        brut = (
            "Warning: Permanently added 'x' (ED25519) to known hosts.\n"
            "vraie sortie\n"
            "Connection to x closed.\n"
        )
        self.assertEqual("vraie sortie\n", A.strip_ssh_noise(brut))

    def test_a_line_that_merely_mentions_it_stays(self):
        """Le filtre porte sur le DÉBUT de ligne, pas sur le mot."""
        brut = "le journal dit Connection to x closed quelque part\n"
        self.assertEqual(brut, A.strip_ssh_noise(brut))

    def test_an_empty_output_stays_empty(self):
        self.assertEqual("", A.strip_ssh_noise(""))
        self.assertEqual("", A.strip_ssh_noise(None))


class TestLaCleDHoteInconnue(unittest.TestCase):
    """Conclure « injoignable » sur une machine qui n'attend qu'un accord."""

    FORMULATIONS = (
        "Host key verification failed.",
        "The authenticity of host 'x' can't be established.",
        "No ED25519 host key is known for x and you have requested strict"
        " checking.",
    )

    def test_every_wording_is_recognised(self):
        """Trois selon la version de ssh et le type de clé ; en manquer une
        fait conclure à une panne de réseau sur un accord qui manque."""
        self.assertTrue(self.FORMULATIONS, "aucun cas : rien n'est prouvé")
        for texte in self.FORMULATIONS:
            with self.subTest(texte=texte[:32]):
                self.assertTrue(A.hostkey_missing(texte))

    def test_the_case_does_not_matter(self):
        self.assertTrue(A.hostkey_missing("HOST KEY VERIFICATION FAILED"))

    def test_another_failure_is_not_mistaken_for_it(self):
        """Contrôle positif : le prédicat doit aussi savoir dire non."""
        for texte in ("Permission denied (publickey).", "", None):
            with self.subTest(texte=texte):
                self.assertFalse(A.hostkey_missing(texte))


class TestLAvancementSeReplie(unittest.TestCase):
    """Un avancement compte pendant qu'il défile, pas dans un journal relu."""

    def test_a_burst_becomes_one_line_that_counts_it(self):
        brut = "\n".join(
            ["debut"]
            + ["transferred %d.0 GiB of 9.0 GiB" % n for n in range(1, 6)]
            + ["fin"]
        )
        replie = A.collapse_progress(brut)
        self.assertIn("debut", replie)
        self.assertIn("fin", replie)
        self.assertIn("5", replie)
        self.assertNotIn("transferred 3.0", replie)

    def test_what_is_not_progress_is_kept_verbatim(self):
        brut = "erreur : disque plein\nligne suivante"
        self.assertEqual(brut, A.collapse_progress(brut))


class TestJouerNeLevePas(unittest.TestCase):
    """Une panne de transport est un CODE, pas une exception à rattraper."""

    def test_a_timeout_answers_255_and_says_so(self):
        with patch.object(
            A.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired("ssh", 1),
        ):
            code, sortie = A.run({"target": "appliance"}, "vrai")
        self.assertEqual(255, code)
        self.assertIn("timeout", sortie)

    def test_an_unreachable_host_answers_255_and_names_the_cause(self):
        with patch.object(
            A.subprocess, "run", side_effect=OSError("ssh introuvable")
        ):
            code, sortie = A.run({"target": "appliance"}, "vrai")
        self.assertEqual(255, code)
        self.assertIn("ssh introuvable", sortie)

    def test_it_joins_both_streams_and_cleans_them(self):
        class Reponse:
            returncode = 0
            stdout = "utile\n"
            stderr = "Connection to x closed.\n"

        with patch.object(A.subprocess, "run", return_value=Reponse()):
            code, sortie = A.run({"target": "appliance"}, "vrai")
        self.assertEqual(0, code)
        self.assertEqual("utile\n", sortie)

    def test_the_sudo_field_elevates_the_command(self):
        vues = []

        class Reponse:
            returncode = 0
            stdout = ""
            stderr = ""

        def espion(argv, **_kwargs):
            vues.append(argv)
            return Reponse()

        with patch.object(A.subprocess, "run", side_effect=espion):
            A.run({"target": "appliance", "sudo": "sudo"}, "qm list")
        self.assertTrue(vues, "aucun appel : rien n'est prouvé")
        self.assertTrue(vues[0][-1].startswith("sudo sh -c "))

    def test_without_the_sudo_field_it_does_not(self):
        """Contrôle positif : l'élévation n'est pas systématique."""
        vues = []

        class Reponse:
            returncode = 0
            stdout = ""
            stderr = ""

        def espion(argv, **_kwargs):
            vues.append(argv)
            return Reponse()

        with patch.object(A.subprocess, "run", side_effect=espion):
            A.run({"target": "appliance"}, "qm list")
        self.assertEqual("qm list", vues[0][-1])


class TestLeModuleNeSaitRienDuProduit(unittest.TestCase):
    """Il parle à une appliance, pas à un hyperviseur en particulier."""

    def test_it_names_no_product(self):
        chemin = os.path.join(RACINE, "script", "remote", "appliance_ssh.py")
        with open(chemin, encoding="utf-8") as handle:
            source = handle.read().lower()
        for produit in ("proxmox", "pveversion", "vzdump"):
            self.assertNotIn(produit, source)

    def test_it_imports_only_the_standard_library(self):
        import ast

        chemin = os.path.join(RACINE, "script", "remote", "appliance_ssh.py")
        with open(chemin, encoding="utf-8") as handle:
            arbre = ast.parse(handle.read())
        racines = set()
        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.Import):
                racines.update(a.name.split(".")[0] for a in noeud.names)
            elif isinstance(noeud, ast.ImportFrom) and noeud.module:
                racines.add(noeud.module.split(".")[0])
        self.assertTrue(racines, "aucun import lu : rien n'est prouvé")
        self.assertEqual(set(), racines - set(sys.stdlib_module_names))


if __name__ == "__main__":
    unittest.main()
