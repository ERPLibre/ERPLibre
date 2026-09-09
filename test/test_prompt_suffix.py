#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le deux-points d'une invite est écrit une fois, pas deux.

`click.prompt` ajoute son propre suffixe — « : » suivi d'un espace — à
l'étiquette qu'on lui donne. Une étiquette qui porte déjà son deux-points
sortait donc en « Commande :: », et ce menu-là est le plus vu du logiciel.

Le contrôle lit l'ARBRE de tout `script/**/*.py` et RÉSOUT l'étiquette dans
les deux langues, parce que la ponctuation n'est pas la même : le français
met une espace avant le deux-points, l'anglais non, et une seule des deux
traductions peut porter la marque. Chercher dans le texte du code ne verrait
que la clé anglaise.

Deux suffixes explicites sont acceptés, et le choix se déduit de l'étiquette
elle-même : `" "` quand elle finit par un deux-points nu, `""` quand elle
porte déjà l'espace qui suit. Toute autre valeur est une décision à écrire
ici avec sa raison.

La couverture est PARTIELLE et le reste : une étiquette calculée — variable,
f-string, concaténation — n'est pas lisible dans l'arbre, et le contrôle
l'ignore plutôt que de l'approximer. Il voit les étiquettes littérales, qui
sont celles où le deux-points s'écrit à la main.
"""

import ast
import pathlib
import unittest

from script.todo.todo_i18n import TRANSLATIONS

RACINE = pathlib.Path(__file__).resolve().parents[1]


def _etiquette(noeud):
    """La clé de l'étiquette d'un `click.prompt`, ou None.

    Reconnaît `t("…")` et la chaîne nue. Une étiquette calculée — variable,
    f-string, concaténation — rend None : ce contrôle ne devine pas ce qu'il
    ne peut pas lire, et le dire est plus honnête que de l'approximer."""
    if not noeud.args:
        return None
    premier = noeud.args[0]
    if (
        isinstance(premier, ast.Call)
        and getattr(premier.func, "id", "") == "t"
        and premier.args
        and isinstance(premier.args[0], ast.Constant)
        and isinstance(premier.args[0].value, str)
    ):
        return premier.args[0].value
    if isinstance(premier, ast.Constant) and isinstance(premier.value, str):
        return premier.value
    return None


def _invites():
    """[(fichier:ligne, clé, suffixe explicite ou None)] de tout le paquet."""
    trouves = []
    for chemin in sorted(RACINE.glob("script/**/*.py")):
        try:
            arbre = ast.parse(chemin.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for noeud in ast.walk(arbre):
            if not isinstance(noeud, ast.Call):
                continue
            if getattr(noeud.func, "attr", "") != "prompt":
                continue
            cle = _etiquette(noeud)
            if cle is None:
                continue
            suffixe = None
            for mot in noeud.keywords:
                if mot.arg == "prompt_suffix" and isinstance(
                    mot.value, ast.Constant
                ):
                    suffixe = mot.value.value
            ou = f"{chemin.relative_to(RACINE)}:{noeud.lineno}"
            trouves.append((ou, cle, suffixe))
    return trouves


def _finit_par_deux_points(cle):
    """Vrai si l'étiquette finit par un deux-points dans UNE des langues."""
    for langue in ("fr", "en"):
        rendu = TRANSLATIONS.get(cle, {}).get(langue, cle)
        if rendu.rstrip().endswith(":"):
            return True
    return False


class TestLesInvitesFurentTrouvees(unittest.TestCase):
    """Sans ceci, une recherche cassée rendrait tous les tests verts."""

    def test_the_search_finds_prompts(self):
        self.assertGreater(len(_invites()), 20)

    def test_the_main_menu_prompt_is_among_them(self):
        cles = {cle for _, cle, _ in _invites()}
        self.assertIn("Command:", cles)


class TestAucunDeuxPointsDouble(unittest.TestCase):
    def test_every_colon_label_passes_its_suffix(self):
        fautives = [
            f"{ou} — {cle!r}"
            for ou, cle, suffixe in _invites()
            if _finit_par_deux_points(cle) and suffixe is None
        ]
        self.assertEqual(
            fautives,
            [],
            "click ajoute « : » : ces invites en afficheraient deux",
        )

    def test_the_suffix_matches_the_label(self):
        """L'espace est fourni une fois : par l'étiquette ou par le suffixe."""
        mauvais = []
        for ou, cle, suffixe in _invites():
            if suffixe is None:
                continue
            francais = TRANSLATIONS.get(cle, {}).get("fr", cle)
            attendu = "" if francais.endswith(": ") else " "
            if suffixe != attendu:
                mauvais.append(f"{ou} — {suffixe!r} au lieu de {attendu!r}")
        self.assertEqual(mauvais, [])

    def test_a_label_without_a_colon_leaves_click_alone(self):
        """Le suffixe par défaut est ce qui ponctue les autres invites."""
        inutiles = [
            f"{ou} — {cle!r}"
            for ou, cle, suffixe in _invites()
            if suffixe is not None and not _finit_par_deux_points(cle)
        ]
        self.assertEqual(inutiles, [])


if __name__ == "__main__":
    unittest.main()
