#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le filtre de secrets dit « CHAQUE affichage » : qu'il en soit ainsi.

LA PORTÉE ANNONCÉE EST LA GARANTIE. Un filtre appliqué à un lanceur sur
trois rassure au-delà de ce qu'il tient, et sa présence décourage d'en poser
un au point d'affichage suivant — c'est ce qui rend une garde à portée
étroite plus coûteuse qu'une garde absente.

Deux lignes consécutives du même journal le montraient : la commande écrite
brute, puis l'écho de l'enfant caviardé. Même secret, même fichier.

Ces épreuves portent donc sur LES TROIS lanceurs, et sur les trois sorties
que chacun alimente : l'écran, le journal d'étape, et le fichier de
progression qu'on relit des semaines plus tard.

LE FILTRE NE RETIRE QUE LA VALEUR. Le nom de l'option reste, sans quoi une
commande caviardée cesserait d'être lisible — et l'on relit ces journaux
précisément pour comprendre ce qui a été lancé.
"""

import io
import os
import sys
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

sys.argv = ["todo.py"]

from script.execute import execute as E  # noqa: E402

# Une valeur inventée, vérifiée absente du reste du dépôt : un secret
# d'exemple pris dans le parc se figerait ici pour toujours.
SECRET = "s3cr3t-de-banc"


class TestCeQueLeFiltreRetire(unittest.TestCase):
    """Ce qu'il enlève, et surtout ce qu'il laisse."""

    def test_the_value_goes_and_the_option_name_stays(self):
        """Une commande caviardée doit rester LISIBLE : on relit ces
        journaux pour comprendre ce qui a été lancé, et une ligne dont
        l'option a disparu ne l'apprend plus."""
        vu = E.redact_secrets(f"./x.sh --db_password {SECRET}")
        self.assertNotIn(SECRET, vu)
        self.assertIn("--db_password", vu)

    def test_a_command_without_a_secret_comes_back_untouched(self):
        """Contrôle positif : caviarder tout reviendrait à ne rien dire."""
        nu = "./odoo_bin.sh db --list"
        self.assertEqual(nu, E.redact_secrets(nu))

    def test_nothing_at_all_is_not_an_error(self):
        for vide in ("", None):
            with self.subTest(vide=vide):
                self.assertFalse(E.redact_secrets(vide))


class TestLesTroisLanceursCaviardentLaCommande(unittest.TestCase):
    """« CHAQUE affichage » couvre les trois, ou la phrase est fausse.

    Le contrôle est STRUCTUREL parce qu'il porte sur un engagement de
    portée : la question n'est pas « ce cas-là fuit-il » — aucune commande
    du dépôt ne porte aujourd'hui de secret jusque-là — mais « le prochain
    point d'affichage sera-t-il gardé ». Un jour quelqu'un passera un mot
    de passe sur la ligne de commande, et c'est alors que la phrase devra
    être vraie.
    """

    LANCEURS = ("run_captured", "run_on_terminal")

    @staticmethod
    def corps(nom):
        import ast

        chemin = os.path.join(RACINE, "script", "todo", "todo_upgrade.py")
        source = io.open(chemin, encoding="utf-8").read()
        lignes = source.splitlines()
        for noeud in ast.walk(ast.parse(source)):
            if isinstance(noeud, ast.FunctionDef) and noeud.name == nom:
                return "\n".join(lignes[noeud.lineno - 1 : noeud.end_lineno])
        raise AssertionError(f"{nom} introuvable")

    def test_no_launcher_prints_the_raw_command(self):
        """`print(cmd)` met le secret à l'écran, d'où il part dans une
        capture d'écran ou un copier-coller de rapport."""
        for nom in self.LANCEURS:
            with self.subTest(lanceur=nom):
                self.assertNotIn("print(cmd)", self.corps(nom))

    def test_no_launcher_logs_the_raw_command(self):
        """Le journal d'étape SURVIT à la session : c'est la sortie dont
        la durée de vie est la plus longue des trois."""
        for nom in self.LANCEURS:
            with self.subTest(lanceur=nom):
                self.assertNotIn('note_step_log(f"$ {cmd}")', self.corps(nom))

    def test_no_launcher_persists_the_raw_command(self):
        """Le fichier de progression est relu et RÉAFFICHÉ par deux autres
        écrans : un secret qui y entre ressort ailleurs, longtemps après."""
        for nom in self.LANCEURS:
            with self.subTest(lanceur=nom):
                self.assertNotIn(
                    "lst_command_executed.append(cmd)", self.corps(nom)
                )

    def test_each_launcher_actually_calls_the_filter(self):
        """Contrôle positif : retirer les trois affichages satisferait les
        épreuves ci-dessus sans rien caviarder."""
        for nom in self.LANCEURS:
            with self.subTest(lanceur=nom):
                self.assertIn("redact_secrets", self.corps(nom))


class TestLaCommandeRendueEstDejaCaviardee(unittest.TestCase):
    """Ce que le lanceur REND sert à être relu, pas rejoué.

    L'écran imprimait la commande caviardée et la RENDAIT brute ; l'appelant
    l'écrivait alors verbatim dans le fichier de progression. Le filtre
    laisse le nom de l'option, donc la valeur rendue reste lisible.
    """

    def test_the_returned_command_carries_no_secret(self):
        import ast

        chemin = os.path.join(RACINE, "script", "execute", "execute.py")
        source = io.open(chemin, encoding="utf-8").read()
        lignes = source.splitlines()
        for noeud in ast.walk(ast.parse(source)):
            if (
                isinstance(noeud, ast.FunctionDef)
                and noeud.name == "exec_command_live"
            ):
                corps = "\n".join(lignes[noeud.lineno - 1 : noeud.end_lineno])
                rendus = [
                    ligne.strip()
                    for ligne in corps.splitlines()
                    if ligne.strip().startswith("return ")
                    and "command" in ligne
                ]
                self.assertTrue(
                    rendus, "plus aucun retour ne porte la commande"
                )
                for ligne in rendus:
                    with self.subTest(retour=ligne[:50]):
                        self.assertIn("redact_secrets", ligne)
                return
        raise AssertionError("exec_command_live introuvable")


if __name__ == "__main__":
    unittest.main()
