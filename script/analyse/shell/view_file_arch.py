#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Arch de référence des vues, telle que le module la déclare.

Ce fichier ne se lance PAS seul : il est poussé dans l'entrée standard d'un
``odoo-bin shell``, qui lui fournit ``env``. Lancé directement, il ne trouve
aucun ``env`` et ne fait rien.

Pourquoi passer par l'ORM plutôt que relire le XML
--------------------------------------------------
La question « à quoi comparer l'arch en base » a une réponse dans le code
d'Odoo : c'est ce que fait son propre bouton « Reset view », mode ``hard`` —
``view.with_context(read_arch_from_file=True, lang=None).arch``.

Cette seule expression gère ce qu'une relecture du XML devrait réimplémenter :
localiser le fichier par ``arch_fs``, y trouver le bon nœud par identifiant
externe ou par identifiant court, suivre un ``<record>`` qui ne fait que
re-pointer, transformer un ``<template>`` en ``<t t-name>``, résoudre les
``%(xmlid)s`` en identifiants réels. Réécrire tout cela, c'est se tromper
autrement qu'Odoo.

Aucune écriture
---------------
``odoo/cli/shell.py`` fait un ``rollback`` après exécution. Le ``rollback``
final ici est une ceinture par-dessus cette bretelle ; il n'y a aucun
``commit``, et il n'y en aura pas.
"""

import json
import os

VIEW_IDS = os.environ.get("VIEW_IDS", "")
LANG = os.environ.get("ANALYSE_LANG") or None

lst_id = [int(part) for part in VIEW_IDS.split(",") if part.strip().isdigit()]
lst_out = []

if lst_id:
    views = env["ir.ui.view"].with_context(active_test=False).browse(lst_id)
    for view in views.exists():
        try:
            # lang=None demande la valeur brute, non traduite : comparer une
            # arch traduite à une arch source ferait ressortir chaque terme
            # traduit comme une différence.
            reference = view.with_context(
                read_arch_from_file=True, lang=LANG
            ).arch
            error = None
        except Exception as exc:  # une vue cassée ne doit pas tuer le lot
            reference, error = None, f"{type(exc).__name__}: {exc}"
        try:
            stored = view.with_context(lang=LANG).arch
        except Exception as exc:
            stored, error = None, error or f"{type(exc).__name__}: {exc}"
        lst_out.append(
            {
                "id": view.id,
                "xml_id": view.xml_id or view.key or "",
                "arch_db": stored,
                "arch_file": reference,
                "error": error,
            }
        )

print("ANALYSE_JSON_BEGIN")
print(json.dumps(lst_out))
print("ANALYSE_JSON_END")
env.cr.rollback()
