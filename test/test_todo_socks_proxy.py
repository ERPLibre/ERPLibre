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
import ast
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
        occupes=(),
    ):
        """Déroule la commande sur des réponses écrites d'avance.

        Les ports `occupes` sont pris, tous les autres libres : sans cela,
        le résultat dépendrait de ce qui écoute sur le poste qui teste."""
        todo = TODO.__new__(TODO)
        todo.execute = ExecuteFactice()
        todo._ask_ssh_target = lambda: cible
        todo._port_is_free = lambda port: int(port) not in occupes
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

    def test_un_defaut_occupe_propose_le_suivant_libre(self):
        commandes, _ = self.joue([""], occupes={1080, 1081})
        self.assertEqual(["ssh -D 1082 -N -C vm-essai"], commandes)

    def test_un_port_choisi_occupe_passe_au_suivant_et_le_dit(self):
        commandes, sortie = self.joue(["9050"], occupes={9050})
        self.assertEqual(["ssh -D 9051 -N -C vm-essai"], commandes)
        self.assertIn("9050", sortie)
        # Le mode d'emploi donne au navigateur le port RÉELLEMENT ouvert.
        self.assertIn("127.0.0.1, port 9051", sortie)

    def test_sans_port_libre_proche_on_demande_et_non_renonce(self):
        occupes = set(range(9050, 9071))
        commandes, _ = self.joue(["9050", ""], occupes=occupes)
        self.assertEqual([], commandes)
        commandes, _ = self.joue(["9050", "o"], occupes=occupes)
        self.assertEqual(["ssh -D 9050 -N -C vm-essai"], commandes)

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
    """Le menu de déploiement : ses numéros mènent-ils où ils promettent ?

    L'épreuve ne cite AUCUN numéro. La version précédente affirmait « le VPN
    est en 10 » et virait au rouge le jour où une entrée s'est insérée avant
    lui, alors que le menu restait juste. Ce qui casse vraiment, c'est un
    numéro affiché qui appelle autre chose — et cela se vérifie en comparant
    la liste des entrées à la chaîne de branches, quelle que soit leur
    longueur.
    """

    @staticmethod
    def _methode(nom):
        source = (RACINE / "script/todo/todo.py").read_text(encoding="utf-8")
        arbre = ast.parse(source)
        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.FunctionDef) and noeud.name == nom:
                return noeud
        raise AssertionError("methode introuvable : %s" % nom)

    @staticmethod
    def _entrees(methode):
        """Les libellés des entrées numérotées, dans l'ordre.

        Une entrée {"section": ...} ne consomme pas de numéro — c'est ce que
        fait `fill_help_info`, et la numérotation doit s'y accorder.
        """
        for noeud in ast.walk(methode):
            if not isinstance(noeud, ast.Assign):
                continue
            cibles = [c.id for c in noeud.targets if isinstance(c, ast.Name)]
            if "choices" not in cibles or not isinstance(noeud.value, ast.List):
                continue
            libelles = []
            for element in noeud.value.elts:
                if not isinstance(element, ast.Dict):
                    continue
                cles = [k.value for k in element.keys if isinstance(k, ast.Constant)]
                if "section" in cles:
                    continue
                textes = [n.value for n in ast.walk(element)
                          if isinstance(n, ast.Constant) and isinstance(n.value, str)
                          and not n.value.startswith("prompt_description")]
                libelles.append(" ".join(textes))
            return libelles
        raise AssertionError("aucune liste « choices »")

    @staticmethod
    def _branches(methode):
        """Les (numéro, nom appelé) de la chaîne if/elif qui suit le menu."""
        trouvees = []
        for noeud in ast.walk(methode):
            if not isinstance(noeud, ast.If):
                continue
            test = noeud.test
            if not (isinstance(test, ast.Compare)
                    and isinstance(test.left, ast.Name) and test.left.id == "status"
                    and len(test.comparators) == 1
                    and isinstance(test.comparators[0], ast.Constant)):
                continue
            numero = test.comparators[0].value
            appele = ""
            for interne in ast.walk(ast.Module(body=noeud.body, type_ignores=[])):
                if isinstance(interne, ast.Call) and isinstance(interne.func, ast.Attribute):
                    appele = interne.func.attr
                    break
            trouvees.append((numero, appele))
        return trouvees

    def test_chaque_numero_affiche_a_sa_branche(self):
        methode = self._methode("prompt_execute_deploy")
        entrees = self._entrees(methode)
        branches = dict(self._branches(methode))

        self.assertIn("0", branches, "le retour n'est pas cable")
        numerotes = [str(n) for n in range(1, len(entrees) + 1)]
        self.assertEqual(
            sorted(set(numerotes) - set(branches)), [],
            "des entrees affichees ne menent nulle part",
        )
        self.assertEqual(
            sorted(set(branches) - set(numerotes) - {"0"}), [],
            "des branches repondent a des numeros que le menu n'affiche pas",
        )

    def test_le_proxy_socks_ferme_la_section_locale(self):
        methode = self._methode("prompt_execute_deploy")
        entrees = self._entrees(methode)
        branches = dict(self._branches(methode))

        rang = next(i for i, libelle in enumerate(entrees, start=1)
                    if "SOCKS" in libelle)
        self.assertEqual(rang, 4, "le proxy SOCKS n'est plus le quatrieme")
        self.assertEqual(branches.get(str(rang)), "_deploy_socks_proxy")

    def test_le_vpn_mene_a_son_sous_menu(self):
        methode = self._methode("prompt_execute_deploy")
        entrees = self._entrees(methode)
        branches = dict(self._branches(methode))

        rang = next(i for i, libelle in enumerate(entrees, start=1)
                    if "VPN" in libelle)
        self.assertEqual(branches.get(str(rang)), "prompt_execute_vpn")


if __name__ == "__main__":
    unittest.main()
