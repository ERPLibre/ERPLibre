#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les chaînes du CODE d'un module, ses docstrings exclues.

À QUOI ÇA SERT. Plusieurs épreuves du dépôt tiennent l'invariant « ce
fichier n'écrit pas telle commande en littéral, il la demande au module qui
la possède ». Un filtre ligne à ligne sur « # » ne suffit pas : une
docstring qui EXPLIQUE la commande la cite légitimement, et la compter
ferait tomber l'épreuve sur de la prose.

POURQUOI UN MODULE ET NON TROIS COPIES. Ce contrôle a été recopié trois
fois, et la troisième était fautive : `getattr(noeud, "body")` s'applique
aussi à un `ast.IfExp`, dont le `body` est une EXPRESSION et non une liste
— d'où un « 'JoinedStr' object is not subscriptable » au premier fichier
qui portait une expression conditionnelle. Un contrôle recopié diverge de
sa copie au premier correctif ; celui-ci l'a fait avant même d'être fini.

Les nœuds qui portent une docstring sont ÉNUMÉRÉS pour cette raison : c'est
la liste du langage, et deviner par la présence d'un attribut « body »
attrape des nœuds qui n'en sont pas.
"""
from __future__ import annotations

import ast

# Les seuls nœuds dont le premier élément du corps peut être une docstring.
# Énumérés plutôt que déduits : voir l'en-tête.
PORTEURS_DE_DOCSTRING = (
    ast.Module,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
)


def _ids_des_docstrings(arbre) -> set:
    """Les identités des nœuds qui SONT une docstring."""
    trouves = set()
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, PORTEURS_DE_DOCSTRING):
            continue
        corps = noeud.body
        if (
            corps
            and isinstance(corps[0], ast.Expr)
            and isinstance(corps[0].value, ast.Constant)
            and isinstance(corps[0].value.value, str)
        ):
            trouves.add(id(corps[0].value))
    return trouves


def code_string_literals(source: str) -> list:
    """Toutes les chaînes littérales du code, docstrings exclues.

    Prend le TEXTE et non un chemin : l'analyse reste pure, donc éprouvable
    sur des cas inventés qu'aucun fichier du dépôt ne porte.

    Une f-string n'est PAS une chaîne littérale au sens de l'AST : ses
    morceaux constants le sont, et ils sont rendus. C'est ce qu'on veut —
    « f"limactl shell {nom}" » écrit bien la commande en dur.
    """
    arbre = ast.parse(source or "")
    docs = _ids_des_docstrings(arbre)
    return [
        noeud.value
        for noeud in ast.walk(arbre)
        if isinstance(noeud, ast.Constant)
        and isinstance(noeud.value, str)
        and id(noeud) not in docs
    ]


def literals_matching(source: str, aiguille: str) -> list:
    """Les chaînes du code qui CONTIENNENT `aiguille`, docstrings exclues.

    Rend la LISTE et non un booléen : une épreuve qui tombe doit pouvoir
    montrer ce qu'elle a trouvé, sans quoi il faut relire le fichier entier
    pour savoir laquelle des chaînes est en cause.
    """
    return [
        chaine for chaine in code_string_literals(source) if aiguille in chaine
    ]


def literals_in_file(chemin: str, aiguille: str) -> list:
    """`literals_matching` sur un fichier, pour l'appelant qui a un chemin."""
    with open(chemin, encoding="utf-8") as fichier:
        return literals_matching(fichier.read(), aiguille)
