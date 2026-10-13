#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le gel d'un projet de manifeste : un commit ÉCRIT À CÔTÉ de sa branche.

Chaque `<project>` d'un fichier source de `manifest/` garde sa branche dans
« revision » et reçoit le commit gelé dans « freeze-revision ». Les deux
lectures partent donc du même élément, et rien ne peut dériver entre deux
fichiers.

Un fork peut recevoir en plus, dans « fork-upstream-freeze-revision », le
commit de son amont sur lequel le commit gelé repose : leur base de fusion.
Cet attribut ne vaut que pour le commit gelé à côté de lui ; un gel qui
change « freeze-revision » sans fournir de base le retire.

git-repo ne voit jamais ces deux attributs : la fusion qui produit le
manifeste local les consomme, et choisit selon son argument de poser le
commit ou la branche dans « revision ».

Les fichiers sources sont réécrits comme du TEXTE, élément par élément. Une
relecture XML suivie d'une écriture perdrait les commentaires, dont des
`<project>` commentés, et la mise en forme d'un attribut par ligne.

Bibliothèque standard seulement : le serveur git local l'importe, et il
peut tourner sous un interpréteur sans les dépendances du venv.
"""

import re

FREEZE_ATTR = "freeze-revision"
FORK_UPSTREAM_FREEZE_ATTR = "fork-upstream-freeze-revision"

# Où chaque attribut se pose quand la balise ne le porte pas encore : après
# la première de ces ancres présente.
_ANCRES = {
    FREEZE_ATTR: ("revision", "path", "name"),
    FORK_UPSTREAM_FREEZE_ATTR: (
        "fork-upstream",
        "fork-upstream-name",
        "fork-upstream-remote",
        FREEZE_ATTR,
        "revision",
        "path",
        "name",
    ),
}

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


def _set_attr(tag, attr, valeur):
    """Pose ou met à jour l'attribut `attr` dans une balise `<project>`.

    Un attribut neuf se place juste après la première ancre de `_ANCRES`
    présente, avec le même séparateur qu'elle : retour à la ligne et
    indentation dans un bloc d'un attribut par ligne, simple espace sur une
    balise d'une ligne. Le blanc exigé devant le nom distingue
    « freeze-revision » de « fork-upstream-freeze-revision », et le « =" »
    qui le suit distingue « fork-upstream » de « fork-upstream-name ».
    """
    existant = re.search(r'(\s)%s="[^"]*"' % re.escape(attr), tag)
    if existant:
        return (
            tag[: existant.start()]
            + f'{existant.group(1)}{attr}="{valeur}"'
            + tag[existant.end() :]
        )
    for ancre in _ANCRES[attr]:
        m = re.search(r'(\s+)%s="[^"]*"' % re.escape(ancre), tag)
        if m:
            return (
                tag[: m.end()]
                + f'{m.group(1)}{attr}="{valeur}"'
                + tag[m.end() :]
            )
    return tag


def _drop_attr(tag, attr):
    """Retire l'attribut `attr` et le blanc qui le précède.

    Le blanc exigé devant le nom fait que retirer « freeze-revision »
    laisse « fork-upstream-freeze-revision » intact.
    """
    return re.sub(r'\s+%s="[^"]*"' % re.escape(attr), "", tag)


# Base amont non fournie : distincte de None, qui demande de la retirer.
_INCHANGEE = object()


def _set_freeze(tag, sha, base=_INCHANGEE):
    """Pose le commit gelé `sha` (None : n'y touche pas) et la base amont.

    `base` est écrite, ou retirée si elle vaut None. Non fournie, la base
    existante survit seulement si le commit gelé ne change pas : elle ne
    vaut que pour lui.
    """
    if sha is not None:
        if dict(_ATTRS.findall(tag)).get(FREEZE_ATTR) != sha and (
            base is _INCHANGEE
        ):
            base = None
        tag = _set_attr(tag, FREEZE_ATTR, sha)
    if base is _INCHANGEE:
        return tag
    if base is None:
        return _drop_attr(tag, FORK_UPSTREAM_FREEZE_ATTR)
    return _set_attr(tag, FORK_UPSTREAM_FREEZE_ATTR, base)


def _drop_freeze(tag):
    """Retire le commit gelé et la base amont qui l'accompagne."""
    tag = _drop_attr(tag, FREEZE_ATTR)
    return _drop_attr(tag, FORK_UPSTREAM_FREEZE_ATTR)


def rewrite(text, freeze=None, unfreeze=False, upstream=None):
    """Réécrit les `<project>` d'un fichier source. Rend (texte, clés changées).

    `freeze` associe une clé `project_key` au commit à poser ; `upstream`
    associe une clé à la base amont à poser dans
    « fork-upstream-freeze-revision », ou à None pour la retirer. Une clé
    absente d'`upstream` garde sa base si son commit gelé ne change pas, et
    la perd sinon. Un projet absent des deux tables n'est pas touché.
    `unfreeze` retire les deux attributs de tous les projets. Tout ce qui
    n'est pas une balise `<project>` visée est rendu à l'octet près.
    """
    freeze = freeze or {}
    upstream = upstream or {}
    morceaux = []
    changees = []
    curseur = 0
    for debut, fin, attrs in iter_projects(text):
        cle = project_key(attrs.get("name"), attrs.get("path"))
        tag = text[debut:fin]
        if unfreeze:
            neuf = _drop_freeze(tag)
        elif cle in freeze or cle in upstream:
            neuf = _set_freeze(
                tag, freeze.get(cle), upstream.get(cle, _INCHANGEE)
            )
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
    format de xmltodict (« @revision »…). Les attributs « @freeze-revision »
    et « @fork-upstream-freeze-revision » en sont toujours retirés.

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
        valeur.pop(f"@{FORK_UPSTREAM_FREEZE_ATTR}", None)
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
