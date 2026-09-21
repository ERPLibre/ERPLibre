#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les verbes de déploiement SSH, lus sans joindre une seule machine.

« make -n » développe la recette sans l'exécuter : la ligne ssh exacte que
chaque verbe produirait est donc vérifiable depuis une station, en quelques
millisecondes et sans réseau.

Ce qu'on y contrôle : qu'une option ajoutée aux variables atteigne TOUS les
verbes, rsync compris. Un réglage qui n'en atteint que la moitié est pire que
son absence — la machine répond à neuf commandes et refuse les deux autres,
sans que rien n'explique la différence.
"""

import os
import subprocess
import sys
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

# Les onze verbes, et ce qu'il faut leur donner en plus de l'hôte pour que
# leur garde les laisse développer la recette.
VERBES = {
    "ssh_check": {},
    "ssh_push": {},
    "ssh_install": {},
    "ssh_run": {},
    "ssh_stop": {},
    "ssh_restart": {},
    "ssh_status": {},
    "ssh_logs": {},
    "ssh_make": {"SSH_TARGET": "run"},
    "ssh_install_systemd": {},
    "ssh_install_nginx": {"SSH_DOMAIN": "site.example"},
}


def recette(verbe, **variables):
    """Ce que « make -n » développe pour ce verbe, sans rien exécuter."""
    argv = ["make", "-n", verbe, "SSH_HOST=machine.example"]
    argv += [f"{cle}={valeur}" for cle, valeur in variables.items()]
    res = subprocess.run(
        argv, cwd=RACINE, capture_output=True, text=True, timeout=60
    )
    return res.stdout


class MakeDisponible(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            subprocess.run(
                ["make", "--version"], capture_output=True, timeout=20
            )
        except (OSError, subprocess.SubprocessError):
            raise unittest.SkipTest("make absent")


class TestLesOnzeVerbesExistent(MakeDisponible):
    def test_every_verb_expands_to_something(self):
        """Une faute de frappe dans la liste rendrait toutes les autres
        épreuves vertes sans rien prouver."""
        self.assertEqual(11, len(VERBES))
        for verbe, extra in VERBES.items():
            with self.subTest(verbe=verbe):
                self.assertIn("ssh", recette(verbe, **extra))


class TestLeRebondAtteintTout(MakeDisponible):
    """Un rebond qui n'atteint que la moitié des verbes est pire que rien."""

    def test_every_verb_carries_the_jump(self):
        for verbe, extra in VERBES.items():
            with self.subTest(verbe=verbe):
                sortie = recette(verbe, SSH_JUMP="bastion.example", **extra)
                self.assertIn("-J bastion.example", sortie)

    def test_rsync_carries_it_too(self):
        """Elle voyage par « -e », que le développement doit montrer."""
        sortie = recette("ssh_push", SSH_JUMP="bastion.example")
        self.assertIn('-e "ssh ', sortie)
        debut = sortie.index('-e "ssh ')
        self.assertIn(
            "-J bastion.example", sortie[debut : sortie.index('"', debut + 4)]
        )

    def test_no_verb_carries_it_when_it_is_not_asked_for(self):
        """Contrôle positif : l'option n'est pas systématique."""
        for verbe, extra in VERBES.items():
            with self.subTest(verbe=verbe):
                self.assertNotIn("-J", recette(verbe, **extra))


class TestLaLigneSshExacte(MakeDisponible):
    """Ce que produit une invocation nue, figé au caractère près."""

    PREFIXE = "ssh -o StrictHostKeyChecking=accept-new"

    def test_a_bare_invocation_produces_the_expected_line(self):
        sortie = recette("ssh_check")
        self.assertIn(f"{self.PREFIXE} erplibre@machine.example", sortie)

    def test_no_port_is_forced_when_none_is_asked_for(self):
        """« -p 22 » posé en dur écrase le Port qu'un alias déclare, et rend
        injoignable par ces verbes une machine que « ssh <alias> » joint."""
        self.assertNotIn("-p", recette("ssh_check"))

    def test_the_port_travels_when_it_is_given(self):
        """Contrôle positif : l'option existe toujours."""
        sortie = recette("ssh_check", SSH_PORT="2222")
        self.assertIn(f"{self.PREFIXE} -p 2222 erplibre@", sortie)

    def test_the_key_lands_between_the_options_and_the_account(self):
        sortie = recette("ssh_check", SSH_KEY="~/.ssh/deploiement")
        self.assertIn(
            f"{self.PREFIXE} -i ~/.ssh/deploiement erplibre@machine.example",
            sortie,
        )

    def test_the_three_options_keep_a_fixed_order(self):
        sortie = recette(
            "ssh_check", SSH_PORT="2222", SSH_KEY="cle", SSH_JUMP="bastion"
        )
        self.assertIn(f"{self.PREFIXE} -p 2222 -i cle -J bastion ", sortie)

    def test_an_empty_option_leaves_no_gap_behind(self):
        """Une espace posée hors du $(if ...) reste dans la ligne quand
        l'option est vide, et se voit à chaque lecture du développement."""
        self.assertNotIn(f"{self.PREFIXE}  ", recette("ssh_check"))


class TestLaVerificationExecuteCeQuelleAnnonce(MakeDisponible):
    def test_uname_is_run_and_not_printed(self):
        """Enfermé dans la chaîne de « echo », il s'affichait au lieu de
        s'exécuter : la commande annonçait un contrôle qu'elle ne faisait
        pas, et rendait 0 sur une machine dont on ne savait rien."""
        sortie = recette("ssh_check")
        self.assertIn("' && uname -a", sortie)
        self.assertNotIn("uname -a'", sortie)


class TestLaGardeSurLHote(MakeDisponible):
    def test_every_verb_refuses_to_run_without_a_host(self):
        """Sans elle, ssh tenterait « erplibre@ » et le dirait mal."""
        for verbe, extra in VERBES.items():
            with self.subTest(verbe=verbe):
                argv = ["make", "-n", verbe] + [
                    f"{c}={v}" for c, v in extra.items()
                ]
                res = subprocess.run(
                    argv,
                    cwd=RACINE,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                self.assertIn("SSH_HOST is required", res.stdout)

    def test_the_usage_line_names_the_jump(self):
        """Le message d'erreur est le seul endroit où l'option se découvre."""
        self.assertIn("SSH_JUMP", recette("ssh_check"))


if __name__ == "__main__":
    unittest.main()
