#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Un gros dict littéral écrit à la main perd une clé sans rien dire.

Python garde la DERNIÈRE valeur d'une clé répétée dans un littéral, et ne
signale rien : ni erreur, ni avertissement. Une seconde déclaration écrase
donc la première en silence, et la traduction qui s'applique n'est plus
celle qu'on lit à l'endroit où on la cherche.

Le défaut ne se voit pas depuis le dict chargé — au moment où le code peut
le lire, le doublon a déjà été fondu. Il faut donc relire la SOURCE, ce que
ce fichier fait à l'AST, et comparer ce qui est ÉCRIT à ce qui est CHARGÉ :
l'écart est le nombre de clés perdues.
"""

import ast
import collections
import io
import os
import sys
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

from script.todo.todo_i18n import TRANSLATIONS  # noqa: E402

# Les dicts sous surveillance : (chemin relatif, nom du dict, dict chargé).
# Un dict entre ici dès qu'il est littéral, écrit à la main, et assez grand
# pour qu'une clé répétée s'y cache — c'est-à-dire dès qu'on ne peut plus
# le relire en entier avant chaque ajout.
SURVEILLES = (
    ("script/todo/todo_i18n.py", "TRANSLATIONS", TRANSLATIONS),
    ("script/todo/todo.py", "_MENU_LABELS", None),
)


def lire(chemin):
    """Rend le contenu UTF-8 du fichier `chemin`."""
    with io.open(chemin, encoding="utf-8") as handle:
        return handle.read()


def cles_du_source(source, nom, origine="<source>"):
    """Rend (clé, ligne) de chaque clé ÉCRITE dans le dict littéral `nom`.

    Cherche l'affectation à `nom` n'importe où dans l'arbre, corps de classe
    compris. Une clé qui n'est pas une constante — une clé calculée, ou un
    `**autre` déplié — est ignorée : elle n'a pas de position à rapporter et
    ne relève pas de la répétition qu'on traque. Lève ValueError si le dict
    est introuvable, pour qu'une cible renommée fasse rougir le test plutôt
    que rendre une liste vide.
    """
    arbre = ast.parse(source, filename=origine)
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, ast.Assign):
            continue
        if not any(
            isinstance(cible, ast.Name) and cible.id == nom
            for cible in noeud.targets
        ):
            continue
        if not isinstance(noeud.value, ast.Dict):
            continue
        return [
            (cle.value, cle.lineno)
            for cle in noeud.value.keys
            if isinstance(cle, ast.Constant)
        ]
    raise ValueError(f"dict littéral « {nom} » introuvable dans {origine}")


def doublons(cles):
    """Rend {clé: [lignes]} pour les seules clés écrites plus d'une fois."""
    lignes = collections.defaultdict(list)
    for cle, ligne in cles:
        lignes[cle].append(ligne)
    return {cle: n for cle, n in lignes.items() if len(n) > 1}


class TestTheDetectorDetects(unittest.TestCase):
    """Un détecteur qui ne détecte rien laisse tout passer.

    Sans ce contrôle positif, un scanner cassé — mauvais nom cherché, AST
    qui ne descend pas dans les classes — rend zéro doublon sur n'importe
    quoi, et le test suivant passe en n'ayant rien prouvé.
    """

    CLAIR = 'X = {\n    "a": 1,\n    "b": 2,\n}\n'
    REPETE = 'X = {\n    "a": 1,\n    "b": 2,\n    "a": 3,\n}\n'

    def test_it_finds_a_repeated_key_and_names_both_lines(self):
        trouve = doublons(cles_du_source(self.REPETE, "X"))
        self.assertEqual(trouve, {"a": [2, 4]})

    def test_it_finds_nothing_in_a_clean_dict(self):
        self.assertEqual(doublons(cles_du_source(self.CLAIR, "X")), {})

    def test_it_reads_the_keys_it_is_given(self):
        cles = cles_du_source(self.CLAIR, "X")
        self.assertEqual([cle for cle, _ in cles], ["a", "b"])

    def test_it_descends_into_a_class_body(self):
        source = (
            'class C:\n    X = {\n        "a": 1,\n        "a": 2,\n    }\n'
        )
        self.assertEqual(doublons(cles_du_source(source, "X")), {"a": [3, 4]})

    def test_a_single_line_form_counts_as_much_as_a_block(self):
        source = 'X = {\n    "a": {"fr": 1},\n    "a": {\n        "fr": 2,\n    },\n}\n'
        self.assertEqual(doublons(cles_du_source(source, "X")), {"a": [2, 3]})

    def test_a_renamed_dict_fails_loudly_instead_of_reading_empty(self):
        with self.assertRaises(ValueError):
            cles_du_source(self.CLAIR, "PAS_CE_NOM")


class TestNoWatchedDictLosesAKey(unittest.TestCase):
    """Ce qui est écrit dans la source arrive en entier dans le dict."""

    def test_no_watched_dict_declares_a_key_twice(self):
        self.assertTrue(
            SURVEILLES, "aucun dict surveillé : le test ne prouve rien"
        )
        for relatif, nom, _ in SURVEILLES:
            with self.subTest(dict=nom):
                chemin = os.path.join(RACINE, relatif)
                cles = cles_du_source(lire(chemin), nom, relatif)
                self.assertTrue(cles, f"« {nom} » lu vide dans {relatif}")
                repetees = doublons(cles)
                self.assertEqual(
                    repetees,
                    {},
                    f"{relatif} : « {nom} » répète "
                    + ", ".join(
                        f"{cle!r} (lignes {', '.join(str(n) for n in lignes)})"
                        for cle, lignes in sorted(repetees.items())
                    ),
                )

    def test_what_is_written_is_what_is_loaded(self):
        """L'écart entre écrit et chargé EST le nombre de clés perdues."""
        charges = [(r, n, d) for r, n, d in SURVEILLES if d is not None]
        self.assertTrue(charges, "aucun dict chargé : le test ne prouve rien")
        for relatif, nom, charge in charges:
            with self.subTest(dict=nom):
                cles = cles_du_source(
                    lire(os.path.join(RACINE, relatif)), nom, relatif
                )
                self.assertEqual(
                    len(cles),
                    len(charge),
                    f"{relatif} : « {nom} » écrit {len(cles)} clés et en "
                    f"charge {len(charge)} — {len(cles) - len(charge)} perdue(s)",
                )


if __name__ == "__main__":
    unittest.main()
