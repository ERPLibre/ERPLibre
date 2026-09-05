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
import io
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

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


# Chaque verbe et la cible « make » qu'il doit atteindre. La liste est le
# contrat : un verbe qui se tromperait de cible redémarrerait Odoo là où on
# demandait un journal, et rien d'autre ne le dirait.
VERBES = {
    "_deploy_ssh_check": "ssh_check",
    "_deploy_ssh_push": "ssh_push",
    "_deploy_ssh_install": "ssh_install",
    "_deploy_ssh_run": "ssh_run",
    "_deploy_ssh_stop": "ssh_stop",
    "_deploy_ssh_restart": "ssh_restart",
    "_deploy_ssh_status": "ssh_status",
    "_deploy_ssh_logs": "ssh_logs",
    "_deploy_ssh_make": "ssh_make",
    "_deploy_ssh_install_systemd": "ssh_install_systemd",
    "_deploy_ssh_install_nginx": "ssh_install_nginx",
}

CONNEXION = {"SSH_HOST": "machine.example"}


class Espion:
    """Ce que le menu aurait lancé, sans rien lancer."""

    def __init__(self):
        self.jouees = []

    def exec_command_live(self, commande, **_kwargs):
        self.jouees.append(commande)


def menu_factice(params=CONNEXION):
    """Un menu sans son constructeur : ces verbes n'en lisent rien.

    `params` à None simule l'abandon de la connexion.
    """
    menu = TODO.__new__(TODO)
    menu.execute = Espion()
    menu._get_ssh_params = lambda: params
    return menu


class TestLesOnzeVerbesAtteignentLeurCible(unittest.TestCase):
    def test_the_list_covers_every_verb(self):
        """Une liste incomplète rendrait les autres épreuves vertes sans
        rien prouver du verbe oublié."""
        self.assertEqual(11, len(VERBES))
        for methode in VERBES:
            self.assertTrue(hasattr(TODO, methode), methode)

    def test_every_verb_reaches_its_own_make_target(self):
        for methode, cible in VERBES.items():
            with self.subTest(verbe=methode):
                menu = menu_factice()
                with patch(
                    "script.todo.todo.click.prompt",
                    side_effect=["run", "admin@site.example"],
                ):
                    getattr(menu, methode)()
                self.assertEqual(1, len(menu.execute.jouees))
                self.assertTrue(
                    menu.execute.jouees[0].startswith(f"make {cible} "),
                    menu.execute.jouees[0],
                )

    def test_giving_up_the_connection_runs_nothing(self):
        for methode in VERBES:
            with self.subTest(verbe=methode):
                menu = menu_factice(params=None)
                with patch(
                    "script.todo.todo.click.prompt", side_effect=AssertionError
                ):
                    getattr(menu, methode)()
                self.assertEqual([], menu.execute.jouees)


class TestLOrdreDesQuestions(unittest.TestCase):
    """Deux verbes posent une question à eux, après la connexion."""

    def test_the_connection_comes_before_the_verbs_own_question(self):
        ordre = []
        menu = TODO.__new__(TODO)
        menu.execute = Espion()
        menu._get_ssh_params = lambda: ordre.append("connexion") or CONNEXION
        with patch(
            "script.todo.todo.click.prompt",
            side_effect=lambda *a, **k: ordre.append("verbe") or "run",
        ):
            menu._deploy_ssh_make()
        self.assertEqual(["connexion", "verbe"], ordre)

    def test_an_empty_answer_to_the_verbs_question_runs_nothing(self):
        for methode in ("_deploy_ssh_make", "_deploy_ssh_install_nginx"):
            with self.subTest(verbe=methode):
                menu = menu_factice()
                with patch(
                    "script.todo.todo.click.prompt", return_value="   "
                ):
                    getattr(menu, methode)()
                self.assertEqual([], menu.execute.jouees)

    def test_the_nginx_verb_carries_the_domain_and_the_email(self):
        menu = menu_factice()
        with patch(
            "script.todo.todo.click.prompt",
            side_effect=["site.example", "admin@site.example"],
        ):
            menu._deploy_ssh_install_nginx()
        mots = jouee(menu.execute.jouees[0])
        self.assertIn("SSH_DOMAIN=site.example", mots)
        self.assertIn("SSH_ADMIN_EMAIL=admin@site.example", mots)

    def test_the_make_verb_carries_the_target_it_was_given(self):
        menu = menu_factice()
        with patch("script.todo.todo.click.prompt", return_value="db_restore"):
            menu._deploy_ssh_make()
        self.assertIn("SSH_TARGET=db_restore", jouee(menu.execute.jouees[0]))


class TestLesTroisManquesSeDisentAutrement(unittest.TestCase):
    """Trois manques, trois messages : les confondre envoie corriger le
    mauvais champ, et l'utilisateur retape une adresse qui allait bien."""

    def manque(self, methode, reponse):
        menu = menu_factice()
        sortie = io.StringIO()
        with patch("script.todo.todo.click.prompt", return_value=reponse):
            with redirect_stdout(sortie):
                getattr(menu, methode)()
        self.assertEqual([], menu.execute.jouees)
        return sortie.getvalue()

    def test_a_missing_make_target_does_not_blame_the_host(self):
        dit = self.manque("_deploy_ssh_make", "   ")
        self.assertNotIn("host", dit.lower())
        self.assertNotIn("hôte", dit.lower())

    def test_a_missing_domain_does_not_blame_the_host_either(self):
        dit = self.manque("_deploy_ssh_install_nginx", "   ")
        self.assertNotIn("host", dit.lower())
        self.assertNotIn("hôte", dit.lower())

    def test_the_two_messages_are_not_the_same(self):
        """Contrôle positif : deux manques différents, deux phrases."""
        self.assertNotEqual(
            self.manque("_deploy_ssh_make", "  "),
            self.manque("_deploy_ssh_install_nginx", "  "),
        )


if __name__ == "__main__":
    unittest.main()
