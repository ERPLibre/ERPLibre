#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Ce qu'un écart de code contient : des langages, des modules, du poids.

Lit la sortie de « git diff --numstat » et rien d'autre. Compter les LIGNES
D'UN ÉCART et non les lignes d'un arbre : ce qui intéresse une mise à niveau
est ce qui CHANGE, et un compteur d'état ne sait pas répondre sur un fichier
supprimé ni sur une plage de commits.

Aucune dépendance ajoutée, et c'est délibéré. Le seul compteur de lignes que
le dépôt ait jamais appelé est absent de son propre environnement, ce qui
l'a rendu muet sans que rien ne le signale ; « git diff --numstat » est
toujours là, coûte quelques centièmes de seconde sur des dizaines de dépôts,
et ne peut pas disparaître sous les pieds de l'outil.

Le seau se décide sur le CHEMIN, pas sur la seule extension
------------------------------------------------------------
La règle sert à répondre « ce module demande-t-il une relecture ». Un
recensement de l'arbre la tranche : la quasi-totalité des « .po » vit sous
« i18n/ », la quasi-totalité des « .md » sous « readme/ », et la quasi-
totalité des « .html » est le « static/description/index.html » ENGENDRÉ à
partir de ces mêmes fichiers. Une règle qui ne lirait que l'extension
classerait cette page en code et rendrait faux le verdict « documentation
seulement » sur la forme de changement la plus courante.
"""

from __future__ import annotations

import os
import re

# Le module d'un fichier est le premier segment de son chemin dans le dépôt.
# Le fork du cœur d'Odoo est le seul à loger ses modules plus bas, et le
# dépôt nomme déjà cette exception ailleurs.
PREFIXES_DEFAUT = ("",)
PREFIXES_ODOO_CORE = ("addons/", "odoo/addons/")

EXT_I18N = (".po", ".pot")
EXT_DOC = (".md", ".rst", ".txt")
# Les suffixes que le dépôt compte déjà comme du code, augmentés de ceux
# qu'un module Odoo porte sans qu'ils soient du texte libre.
EXT_CODE = (
    ".py",
    ".xml",
    ".js",
    ".csv",
    ".css",
    ".scss",
    ".less",
    ".sql",
    ".sh",
    ".yml",
    ".yaml",
    ".json",
    ".cfg",
    ".toml",
)

LANGAGES = {
    ".py": "Python",
    ".xml": "XML",
    ".js": "JavaScript",
    ".po": "Traduction",
    ".pot": "Traduction",
    ".csv": "CSV",
    ".css": "CSS",
    ".scss": "SCSS",
    ".less": "LESS",
    ".md": "Markdown",
    ".rst": "reStructuredText",
    ".html": "HTML",
    ".sql": "SQL",
    ".sh": "Shell",
    ".yml": "YAML",
    ".yaml": "YAML",
    ".json": "JSON",
}

# La page engendrée à partir du répertoire « readme » d'un module OCA. Elle
# porte l'extension du code et le contenu de la documentation.
PAGE_ENGENDREE = "static/description/index.html"

# « git diff --numstat » rend « {ancien => neuf} » au milieu d'un chemin
# renommé, et « ancien => neuf » quand le renommage porte sur le chemin
# entier. Le chemin d'ARRIVÉE est celui qui existe encore.
RE_ACCOLADES = re.compile(r"\{[^{}]*=> ?([^{}]*)\}")


def chemin_arrivee(chemin):
    """Le chemin après renommage, ou le chemin tel quel.

    Un renommage compte pour le fichier qui EXISTE ; rattacher l'écart au
    nom de départ le rangerait dans un module qui n'a plus le fichier.
    """
    chemin = RE_ACCOLADES.sub(r"\1", chemin)
    if " => " in chemin:
        chemin = chemin.split(" => ")[-1]
    return chemin.replace("//", "/").strip()


def classer_fichier(chemin):
    """« i18n », « doc », « code » ou « autre » pour un chemin de dépôt."""
    chemin = chemin_arrivee(chemin)
    bas = chemin.lower()
    segments = bas.split("/")
    ext = os.path.splitext(bas)[1]

    if "i18n" in segments or ext in EXT_I18N:
        return "i18n"
    if "readme" in segments or ext in EXT_DOC:
        return "doc"
    if bas.endswith(PAGE_ENGENDREE):
        return "doc"
    if ext in EXT_CODE or ext == ".html":
        return "code"
    return "autre"


def langage(chemin):
    """Le langage affiché pour un chemin, « Autre » à défaut."""
    ext = os.path.splitext(chemin_arrivee(chemin).lower())[1]
    return LANGAGES.get(ext, "Autre")


def module_de(chemin, prefixes=PREFIXES_DEFAUT):
    """Le module Odoo qui porte ce fichier, ou None.

    Rend None pour un fichier posé à la racine du dépôt : il n'appartient à
    aucun module, et l'attribuer au premier venu fausserait le compte des
    modules touchés.
    """
    chemin = chemin_arrivee(chemin)
    for prefixe in prefixes:
        if prefixe and not chemin.startswith(prefixe):
            continue
        reste = chemin[len(prefixe) :]
        parts = [p for p in reste.split("/") if p]
        if len(parts) >= 2:
            return parts[0]
    return None


def lire_numstat(texte):
    """[(ajouts, retraits, chemin)] depuis « git diff --numstat ».

    Un fichier binaire est rendu « - » par git sur les deux compteurs. Il
    est gardé avec des compteurs à zéro : il a bien changé, et le taire
    ferait disparaître son module du rapport.
    """
    lignes = []
    for brute in texte.splitlines():
        champs = brute.split("\t")
        if len(champs) < 3:
            continue
        ajouts, retraits, chemin = champs[0], champs[1], "\t".join(champs[2:])
        lignes.append(
            (
                0 if ajouts.strip() == "-" else int(ajouts or 0),
                0 if retraits.strip() == "-" else int(retraits or 0),
                chemin_arrivee(chemin),
            )
        )
    return lignes


def agreger(lignes, prefixes=PREFIXES_DEFAUT):
    """Le compte d'un écart : par seau, par langage, par module.

    « modules_doc » ne retient qu'un module dont AUCUN fichier changé n'est
    du code : c'est la liste que l'on peut sauter en relecture, et il suffit
    d'un fichier de code pour qu'un module en sorte.
    """
    seaux = {"i18n": 0, "doc": 0, "code": 0, "autre": 0}
    langs = {}
    modules = {}
    ajouts_total = retraits_total = 0

    for ajouts, retraits, chemin in lignes:
        seau = classer_fichier(chemin)
        seaux[seau] += 1
        ajouts_total += ajouts
        retraits_total += retraits

        nom = langage(chemin)
        entree = langs.setdefault(
            nom, {"ajouts": 0, "retraits": 0, "fichiers": 0}
        )
        entree["ajouts"] += ajouts
        entree["retraits"] += retraits
        entree["fichiers"] += 1

        module = module_de(chemin, prefixes)
        if module:
            mod = modules.setdefault(module, {"seaux": set(), "fichiers": 0})
            mod["seaux"].add(seau)
            mod["fichiers"] += 1

    modules_doc = sorted(
        n for n, m in modules.items() if "code" not in m["seaux"]
    )
    modules_code = sorted(
        n for n, m in modules.items() if "code" in m["seaux"]
    )
    return {
        "fichiers": len(lignes),
        "ajouts": ajouts_total,
        "retraits": retraits_total,
        "seaux": seaux,
        "langages": {
            n: v
            for n, v in sorted(langs.items(), key=lambda kv: -kv[1]["ajouts"])
        },
        "modules": sorted(modules),
        "modules_doc": modules_doc,
        "modules_code": modules_code,
    }
