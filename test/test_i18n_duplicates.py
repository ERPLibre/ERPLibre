#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Une clé de traduction en double écrase la précédente, sans un mot.

Python construit un dictionnaire littéral de haut en bas : la dernière
occurrence gagne. Une clé posée deux fois avec des valeurs différentes fait
donc qu'un menu affiche la traduction d'un autre, et rien ne le signale — ni
au chargement, ni à l'exécution, ni au test qui exerce le premier menu.

C'est arrivé : « running » et « stopped » existaient déjà, et des clés
homonymes ajoutées pour un service ont été avalées par elles. Le symptôme
était un « Service : en cours » là où le fichier disait « actif ».

Le contrôle lit le fichier par son ARBRE et non par une expression
régulière : la mienne n'attrapait que la forme multiligne, et la collision
était écrite sur une seule ligne.
"""

import ast
import collections
import sys
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
I18N = RACINE / "script" / "todo" / "todo_i18n.py"
sys.path.insert(0, str(RACINE / "script" / "todo"))


def cles_litterales():
    """Les clés du dictionnaire TRANSLATIONS, dans l'ordre du fichier.

    Par l'arbre syntaxique : une clé écrite sur une ligne et une clé écrite
    sur plusieurs sont le même nœud, alors qu'elles n'ont pas la même forme
    dans le texte.
    """
    arbre = ast.parse(I18N.read_text(encoding="utf-8"))
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, ast.Assign):
            continue
        cibles = [c.id for c in noeud.targets if isinstance(c, ast.Name)]
        if "TRANSLATIONS" not in cibles:
            continue
        if not isinstance(noeud.value, ast.Dict):
            continue
        return [
            k.value
            for k in noeud.value.keys
            if isinstance(k, ast.Constant) and isinstance(k.value, str)
        ]
    raise AssertionError("TRANSLATIONS introuvable")


class TestClesUniques(unittest.TestCase):
    def test_aucune_cle_nest_ecrite_deux_fois(self):
        compte = collections.Counter(cles_litterales())
        doubles = sorted(k for k, n in compte.items() if n > 1)
        self.assertEqual(
            doubles,
            [],
            "clés en double — la dernière écrase les précédentes, sans un "
            f"mot : {doubles}",
        )

    def test_le_controle_lit_bien_quelque_chose(self):
        """Un test qui ne trouve aucune clé passerait toujours."""
        self.assertGreater(len(cles_litterales()), 1000)

    def test_chaque_cle_porte_les_deux_langues(self):
        import todo_i18n

        manques = [
            k
            for k, v in todo_i18n.TRANSLATIONS.items()
            if not isinstance(v, dict) or "fr" not in v or "en" not in v
        ]
        self.assertEqual(manques, [], f"traductions incomplètes : {manques}")


if __name__ == "__main__":
    unittest.main()
