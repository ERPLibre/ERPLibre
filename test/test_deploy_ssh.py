#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le menu Deploy › SSH : ce qu'il compose, sans joindre une machine.

La ligne « make » qu'il produit part dans un shell. Ce qui la compose venait
d'invites retapées à chaque commande ; à mesure qu'elle vient d'un fichier
relu, une valeur fautive cesse d'être une faute de frappe visible pour
devenir un piège qui se rejoue.

Les valeurs piégées de ces épreuves sont INVENTÉES. Choisir un vrai chemin
« parce qu'il est parlant » le figerait pour toujours dans le dépôt.
"""

import os
import shlex
import subprocess
import sys
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

from script.todo.todo import TODO  # noqa: E402

# `self` n'est pas lu : la composition ne dépend d'aucun état du menu.
construire = TODO._build_ssh_make_cmd


def jouee(commande):
    """Les mots que le shell VOIT, en remplaçant make par un afficheur.

    Relire la chaîne ne prouve rien — c'est le découpage du shell qui
    décide, et c'est lui qu'on interroge.
    """
    res = subprocess.run(
        ["bash", "-c", commande.replace("make ", "printf '%s\\n' ", 1)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return res.stdout.splitlines()


class TestLaCitationDesValeurs(unittest.TestCase):
    def test_a_plain_command_is_unsurprising(self):
        """Contrôle positif : citer ne doit pas déformer l'ordinaire."""
        self.assertEqual(
            ["make", "ssh_run", "SSH_HOST=machine.example"],
            shlex.split(
                construire(None, "ssh_run", {"SSH_HOST": "machine.example"})
            ),
        )

    def test_a_value_that_would_split_the_command_stays_one_word(self):
        piege = "/depot/un dossier; touch /tmp/temoin-invente"
        commande = construire(None, "ssh_run", {"SSH_PATH": piege})
        self.assertEqual(["ssh_run", f"SSH_PATH={piege}"], jouee(commande))

    def test_a_value_carrying_a_quote_no_longer_closes_the_quoting(self):
        """Des guillemets posés à la main se refermaient dessus, et le
        reste de la ligne devenait des commandes."""
        piege = 'un"dossier'
        commande = construire(None, "ssh_run", {"SSH_PATH": piege})
        self.assertEqual(["ssh_run", f"SSH_PATH={piege}"], jouee(commande))

    def test_a_backtick_is_not_run(self):
        piege = "/depot/`touch /tmp/temoin-invente`"
        commande = construire(None, "ssh_run", {"SSH_PATH": piege})
        self.assertEqual(["ssh_run", f"SSH_PATH={piege}"], jouee(commande))

    def test_the_tilde_is_left_to_the_remote_shell(self):
        """Développé ici, il désignerait le compte de la station."""
        commande = construire(
            None, "ssh_run", {"SSH_PATH": "~/erplibre_deploy_2"}
        )
        self.assertIn("SSH_PATH=~/erplibre_deploy_2", jouee(commande))


class TestCeQuiEntreDansLaLigne(unittest.TestCase):
    def test_the_extra_values_are_quoted_the_same_way(self):
        """Elles portent le domaine et le courriel : la même origine, donc
        le même traitement."""
        commande = construire(
            None,
            "ssh_install_nginx",
            {"SSH_HOST": "machine.example"},
            extra={"SSH_DOMAIN": "un site.example"},
        )
        self.assertIn("SSH_DOMAIN=un site.example", jouee(commande))

    def test_an_empty_value_is_omitted(self):
        """Écrite vide, elle écraserait le défaut du Makefile."""
        commande = construire(
            None, "ssh_run", {"SSH_HOST": "machine.example", "SSH_KEY": ""}
        )
        self.assertNotIn("SSH_KEY", commande)

    def test_the_target_leads_the_line(self):
        commande = construire(None, "ssh_logs", {"SSH_HOST": "m.example"})
        self.assertTrue(commande.startswith("make ssh_logs "), commande)


if __name__ == "__main__":
    unittest.main()
