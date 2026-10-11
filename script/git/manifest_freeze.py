#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le gel d'un projet de manifeste : un commit ÉCRIT À CÔTÉ de sa branche.

Chaque `<project>` d'un fichier source de `manifest/` garde sa branche dans
« revision » et reçoit le commit gelé dans « freeze-revision ». Les deux
lectures partent donc du même élément, et rien ne peut dériver entre deux
fichiers.

git-repo ne voit jamais « freeze-revision » : la fusion qui produit le
manifeste local le consomme, et choisit selon son argument de poser le
commit ou la branche dans « revision ».

Les fichiers sources sont réécrits comme du TEXTE, élément par élément. Une
relecture XML suivie d'une écriture perdrait les commentaires, dont des
`<project>` commentés, et la mise en forme d'un attribut par ligne.

Bibliothèque standard seulement : le serveur git local l'importe, et il
peut tourner sous un interpréteur sans les dépendances du venv.
"""

import re

FREEZE_ATTR = "freeze-revision"

_SHA = re.compile(r"^[0-9a-f]{40}$")
_COMMENT = re.compile(r"<!--.*?-->", re.S)
# Une valeur d'attribut de manifeste ne contient jamais « > » : le motif
# s'arrête donc à la fin de la balise ouvrante, auto-fermante ou non.
_PROJECT = re.compile(r"<project\b[^>]*>", re.S)
_ATTRS = re.compile(r'([\w:.-]+)="([^"]*)"')


def is_sha(value):
    """Vrai si `value` est un commit complet, et non une branche ou un tag."""
    return bool(value) and bool(_SHA.match(value))


def project_key(name, path):
    """Clé d'un projet : la même que celle de la fusion des manifestes.

    Le nom seul ne suffit pas : un même dépôt peut être cloné à plusieurs
    chemins, un par version d'Odoo installée.
    """
    return f"{name}+{path}"


def manifest_branch(revision, upstream=None, dest_branch=None):
    """La branche qu'un projet suit, quel que soit le mode de la fusion.

    En mode gelé, le manifeste local porte le commit dans « revision » et
    la branche dans « dest-branch » et « upstream ». Rend None pour un
    commit sans branche connue : à l'appelant de choisir son repli.
    """
    if is_sha(revision):
        return dest_branch or upstream or None
    return revision


def iter_projects(text):
    """Rend (début, fin, attributs) pour chaque `<project>` hors commentaire.

    `début` et `fin` bornent la balise ouvrante dans `text`.
    """
    commentaires = [m.span() for m in _COMMENT.finditer(text)]
    for m in _PROJECT.finditer(text):
        if any(a <= m.start() < b for a, b in commentaires):
            continue
        yield m.start(), m.end(), dict(_ATTRS.findall(m.group(0)))


def _set_freeze(tag, sha):
    """Pose ou met à jour « freeze-revision » dans une balise `<project>`.

    L'attribut neuf se place juste après « revision », avec le même
    séparateur que lui : retour à la ligne et indentation dans un bloc d'un
    attribut par ligne, simple espace sur une balise d'une ligne.
    """
    existant = re.search(r'(\s)%s="[^"]*"' % re.escape(FREEZE_ATTR), tag)
    if existant:
        return (
            tag[: existant.start()]
            + f'{existant.group(1)}{FREEZE_ATTR}="{sha}"'
            + tag[existant.end() :]
        )
    for ancre in ("revision", "path", "name"):
        m = re.search(r'(\s+)%s="[^"]*"' % ancre, tag)
        if m:
            return (
                tag[: m.end()]
                + f'{m.group(1)}{FREEZE_ATTR}="{sha}"'
                + tag[m.end() :]
            )
    return tag


def _drop_freeze(tag):
    """Retire « freeze-revision » et le blanc qui le précède."""
    return re.sub(r'\s+%s="[^"]*"' % re.escape(FREEZE_ATTR), "", tag)


def rewrite(text, freeze=None, unfreeze=False):
    """Réécrit les `<project>` d'un fichier source. Rend (texte, clés changées).

    `freeze` associe une clé `project_key` au commit à poser ; un projet
    absent de la table n'est pas touché. `unfreeze` retire l'attribut de
    tous les projets. Tout ce qui n'est pas une balise `<project>` visée est
    rendu à l'octet près.
    """
    freeze = freeze or {}
    morceaux = []
    changees = []
    curseur = 0
    for debut, fin, attrs in iter_projects(text):
        cle = project_key(attrs.get("name"), attrs.get("path"))
        tag = text[debut:fin]
        if unfreeze:
            neuf = _drop_freeze(tag)
        elif cle in freeze:
            neuf = _set_freeze(tag, freeze[cle])
        else:
            continue
        if neuf != tag:
            morceaux.append(text[curseur:debut])
            morceaux.append(neuf)
            curseur = fin
            changees.append(cle)
    morceaux.append(text[curseur:])
    return "".join(morceaux), changees


def apply_freeze(projects, freeze):
    """Choisit la révision de chaque projet fusionné. Rend (gelés, manquants).

    `projects` est la table de la fusion, clé `project_key`, valeurs au
    format de xmltodict (« @revision »…). L'attribut « @freeze-revision »
    en est toujours retiré.

    Avec `freeze`, un projet qui porte un commit le reçoit dans
    « @revision », et sa branche passe dans « @upstream » et
    « @dest-branch » : git-repo s'en sert pour aller chercher le commit
    (`sync -c`) et pour qu'une branche ouverte par `repo start` suive la
    branche plutôt que le commit. Un projet sans commit garde sa branche et
    figure parmi les manquants, sauf si sa « revision » est déjà un commit :
    il est alors épinglé par sa source, sans rien manquer.
    """
    geles = []
    manquants = []
    for cle, valeur in projects.items():
        sha = valeur.pop(f"@{FREEZE_ATTR}", None)
        if not freeze:
            continue
        if not sha:
            if not is_sha(valeur.get("@revision")):
                manquants.append(cle)
            continue
        branche = valeur.get("@revision")
        valeur["@revision"] = sha
        if branche and not is_sha(branche):
            valeur.setdefault("@upstream", branche)
            valeur.setdefault("@dest-branch", branche)
        geles.append(cle)
    return geles, manquants
