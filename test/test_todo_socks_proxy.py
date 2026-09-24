#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le proxy SOCKS ouvre-t-il le bon tunnel, et le dit-il assez ?

« -D » ne relaie pas UN service comme « -L » : il ouvre un relais SOCKS, par
lequel le navigateur atteint n'importe quelle destination depuis la machine
distante. Trois choses décident si la commande sert à quelque chose, et ces
tests les gardent :

- l'ALIAS de ~/.ssh/config est passé tel quel à ssh. Le remplacer par
  « user@hôte » perdrait son ProxyJump, et une VM imbriquée sans route directe
  deviendrait injoignable ;
- le port choisi se retrouve dans la commande ET dans le mode d'emploi du
  navigateur, sans quoi l'utilisateur règle Firefox sur un port qui n'écoute
  pas ;
- le mode d'emploi passe AVANT le lancement : la commande ne rend la main
  qu'au Ctrl+C, et c'est pendant qu'elle tourne qu'on règle le navigateur.
"""

import builtins
import contextlib
import io
import sys
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.todo.todo import TODO  # noqa: E402


class ExecuteFactice:
    def __init__(self):
        self.commandes = []

    def exec_command_live(self, cmd, **kwargs):
        self.commandes.append(cmd)


class BancProxy(unittest.TestCase):
    def joue(
        self,
        reponses,
        cible=("vm-essai", "u", "10.0.0.1", "vm-essai", True),
    ):
        """Déroule la commande sur des réponses écrites d'avance."""
        todo = TODO.__new__(TODO)
        todo.execute = ExecuteFactice()
        todo._ask_ssh_target = lambda: cible
        suite = iter(reponses)
        ancien = builtins.input
        builtins.input = lambda *a, **k: next(suite, "")
        sortie = io.StringIO()
        try:
            with contextlib.redirect_stdout(sortie):
                todo._deploy_socks_proxy()
        finally:
            builtins.input = ancien
        return todo.execute.commandes, sortie.getvalue()


class TestLaCommande(BancProxy):
    def test_le_port_par_defaut_est_1080(self):
        commandes, _ = self.joue([""])
        self.assertEqual(["ssh -D 1080 -N -C vm-essai"], commandes)

    def test_le_port_se_change(self):
        commandes, _ = self.joue(["9050"])
        self.assertEqual(["ssh -D 9050 -N -C vm-essai"], commandes)

    def test_un_port_qui_n_est_pas_un_nombre_retombe_sur_1080(self):
        commandes, _ = self.joue(["mille-quatre-vingts"])
        self.assertEqual(["ssh -D 1080 -N -C vm-essai"], commandes)

    def test_l_alias_ssh_est_passe_tel_quel(self):
        """Le remplacer par user@hôte perdrait son ProxyJump."""
        commandes, _ = self.joue(
            [""], cible=("bond", "u", "10.0.0.2", "bond", True)
        )
        self.assertIn(" bond", commandes[0])
        self.assertNotIn("@", commandes[0])

    def test_renoncer_a_l_adresse_ne_lance_rien(self):
        todo = TODO.__new__(TODO)
        todo.execute = ExecuteFactice()
        todo._ask_ssh_target = lambda: None
        with contextlib.redirect_stdout(io.StringIO()):
            todo._deploy_socks_proxy()
        self.assertEqual([], todo.execute.commandes)


class TestLeModeDEmploi(BancProxy):
    def test_il_nomme_le_port_choisi(self):
        _, sortie = self.joue(["9050"])
        self.assertIn("127.0.0.1", sortie)
        self.assertIn("9050", sortie)
        self.assertNotIn("1080", sortie)

    def test_il_precede_le_lancement(self):
        """La commande ne rend la main qu'au Ctrl+C."""
        _, sortie = self.joue([""])
        self.assertLess(sortie.index("127.0.0.1"), sortie.index("Ctrl+C"))

    def test_il_parle_du_dns_distant(self):
        _, sortie = self.joue([""])
        self.assertIn("SOCKS v5", sortie)
        self.assertIn("DNS", sortie.upper())


class TestLeMenu(unittest.TestCase):
    def test_l_entree_ferme_la_section_locale(self):
        """Quatrième, et la suite glisse : le VPN passe de 9 à 10."""
        source = (RACINE / "script/todo/todo.py").read_text(encoding="utf-8")
        debut = source.index("def prompt_execute_deploy(self)")
        menu = source[debut : source.index("def prompt_execute_deploy_ssh")]
        self.assertIn(
            'elif status == "4":\n                self._deploy_socks_proxy()',
            menu,
        )
        self.assertIn(
            'elif status == "10":\n                self.prompt_execute_vpn()',
            menu,
        )


if __name__ == "__main__":
    unittest.main()
