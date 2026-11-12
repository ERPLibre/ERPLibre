#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Faire prendre à un projet de manifeste le fork d'une organisation.

Le projet change de remote : « <Organisation>_origin_<amont> », dont le
« fetch » est https://github.com/<Organisation>/. Sa branche (« revision »)
et son commit gelé (« freeze-revision ») ne changent pas : le fork porte
les mêmes commits, ou les recevra par une ref posée par github_fork.

Ce qui change, c'est sa provenance (fork-upstream-*), selon `mode` :

- AMONT_ORIGINE — un projet déjà forké garde son amont : le nouveau fork
  se rebase sur le même amont que l'ancien (OCA par exemple), et les
  attributs fork-upstream-* restent tels quels.
- AMONT_FORK — l'ancienne source devient l'amont : fork-upstream-remote
  nomme l'ancien remote, fork-upstream sa branche, et la base gelée est
  l'ancien commit gelé, que le fork partage. Un projet qui n'était pas un
  fork prend toujours ce chemin : son ancienne source est son seul amont.

Le fichier est réécrit comme du texte, balise par balise, avec les outils
de manifest_freeze : commentaires, `<project>` commentés et mise en forme
d'un attribut par ligne restent à l'octet près.
"""

import re

from script.git import manifest_freeze, repo_upgrade

AMONT_ORIGINE = "origine"
AMONT_FORK = "fork"

_COMMENT = re.compile(r"<!--.*?-->", re.S)
_REMOTE = re.compile(r"<remote\b[^>]*>", re.S)
_ATTRS = re.compile(r'([\w:.-]+)="([^"]*)"')


def fetch_github(organisation):
    return f"https://github.com/{organisation}/"


def _hors_commentaires(text, motif):
    commentaires = [m.span() for m in _COMMENT.finditer(text)]
    for m in motif.finditer(text):
        if not any(a <= m.start() < b for a, b in commentaires):
            yield m


def remotes_du_texte(text):
    """{nom: fetch} des `<remote>` du fichier, hors commentaires."""
    res = {}
    for m in _hors_commentaires(text, _REMOTE):
        attrs = dict(_ATTRS.findall(m.group(0)))
        if attrs.get("name"):
            res[attrs["name"]] = attrs.get("fetch", "")
    return res


def _meme_fetch(a, b):
    """Deux fetch qui visent le même hôte et la même organisation : GitHub
    ne distingue pas la casse d'un propriétaire."""
    return (a or "").rstrip("/").lower() == (b or "").rstrip("/").lower()


def amont_actuel(projet, remotes):
    """L'amont d'un projet déjà forké, ou None : son remote, son nom amont
    et sa branche, déclarés ou devinés par la convention « _origin_ »."""
    amont = repo_upgrade.resoudre_amont(projet, remotes)
    if amont is None:
        return None
    return amont["remote"]


def plan(projet, remotes, organisation, mode, nom_fork=None):
    """Ce que le fork change pour `projet` (ses attributs de manifeste),
    sur la vue fusionnée `remotes` de sa version.

    Rend {remote, fetch, nouveau_remote, name, attrs, retirer} : le remote à
    poser (et s'il faut le déclarer), le nom du dépôt, les attributs
    fork-upstream-* à poser et ceux à retirer. `nom_fork` est le nom que
    GitHub a donné au fork, s'il diffère (sans « .git »)."""
    ancien_remote = projet.get("remote")
    nom = projet.get("name", "")
    fetch = fetch_github(organisation)
    amont_remote = amont_actuel(projet, remotes)
    if mode == AMONT_ORIGINE and amont_remote:
        suffixe = amont_remote
        attrs, retirer = {}, []
        nom_amont = projet.get("fork-upstream-name")
    else:
        # L'ancienne source devient l'amont : « ERPLibre_origin_OCA » donne
        # l'organisation qui le porte, ERPLibre.
        suffixe = (ancien_remote or "").split("_origin_")[0]
        branche = manifest_freeze.manifest_branch(
            projet.get("revision"),
            projet.get("upstream"),
            projet.get("dest-branch"),
        )
        attrs = {"fork-upstream-remote": ancien_remote}
        retirer = ["fork-upstream-name"]
        if branche:
            attrs["fork-upstream"] = branche
        else:
            retirer.append("fork-upstream")
        gele = projet.get(manifest_freeze.FREEZE_ATTR)
        if gele:
            attrs[manifest_freeze.FORK_UPSTREAM_FREEZE_ATTR] = gele
        else:
            retirer.append(manifest_freeze.FORK_UPSTREAM_FREEZE_ATTR)
        nom_amont = None
    # Le remote d'un fork se nomme « <organisation>_origin_<amont> » : c'est
    # ce nom que repo_upgrade lit pour savoir qu'un projet est un fork. Le
    # remote simple de l'organisation (« ERPLibre »), même vers la même URL,
    # n'est donc jamais repris : le projet cesserait d'être vu comme un fork.
    voulu = f"{organisation}_origin_{suffixe}"
    existant = next(
        (
            n
            for n, f in remotes.items()
            if n.lower() == voulu.lower() and _meme_fetch(f, fetch)
        ),
        None,
    )
    remote = existant or voulu
    homonyme = next((n for n in remotes if n.lower() == voulu.lower()), None)
    if not existant and homonyme:
        raise ValueError(
            f"remote {homonyme} déjà déclaré vers {remotes[homonyme]}"
        )
    nouveau_nom = nom
    nu = nom[: -len(".git")] if nom.endswith(".git") else nom
    if nom_fork and nom_fork != nu:
        nouveau_nom = f"{nom_fork}.git" if nom.endswith(".git") else nom_fork
        attrs["fork-upstream-name"] = nom_amont or nom
        if "fork-upstream-name" in retirer:
            retirer.remove("fork-upstream-name")
    return {
        "remote": remote,
        "fetch": fetch,
        "nouveau_remote": existant is None,
        "name": nouveau_nom,
        "attrs": attrs,
        "retirer": retirer,
    }


def ajouter_remote(text, nom, fetch):
    """Déclare `<remote name=nom fetch=fetch />` après le dernier remote du
    fichier, à son indentation. Rend le texte, inchangé si le remote y est
    déjà avec ce fetch ; refuse un même nom vers une autre URL."""
    existants = remotes_du_texte(text)
    if nom in existants:
        if _meme_fetch(existants[nom], fetch):
            return text
        raise ValueError(f"remote {nom} déjà déclaré vers {existants[nom]}")
    derniers = list(_hors_commentaires(text, _REMOTE))
    ligne = f'<remote name="{nom}" fetch="{fetch}" />'
    if derniers:
        fin = derniers[-1].end()
        debut_ligne = text.rfind("\n", 0, derniers[-1].start()) + 1
        indent = text[debut_ligne : derniers[-1].start()]
        return f"{text[:fin]}\n{indent}{ligne}{text[fin:]}"
    m = re.search(r"<manifest\b[^>]*>", text)
    if not m:
        raise ValueError("pas de balise <manifest>")
    return f"{text[: m.end()]}\n    {ligne}{text[m.end() :]}"


def appliquer(text, name, path, changement):
    """Réécrit le `<project>` name+path selon `changement` (rendu de
    `plan`). Rend (texte, vrai si le projet a été trouvé)."""
    for debut, fin, attrs in manifest_freeze.iter_projects(text):
        if attrs.get("name") != name or attrs.get("path") != path:
            continue
        tag = manifest_freeze._set_attr(
            text[debut:fin], "remote", changement["remote"]
        )
        if changement["name"] != name:
            tag = re.sub(
                r'(\sname=")[^"]*(")', rf'\g<1>{changement["name"]}\2', tag
            )
        for attr in changement["retirer"]:
            tag = manifest_freeze._drop_attr(tag, attr)
        for attr in (
            "fork-upstream-remote",
            "fork-upstream-name",
            "fork-upstream",
            manifest_freeze.FORK_UPSTREAM_FREEZE_ATTR,
        ):
            if attr in changement["attrs"]:
                tag = manifest_freeze._set_attr(
                    tag, attr, changement["attrs"][attr]
                )
        # Le remote est déclaré dans CE fichier, même s'il l'est déjà dans
        # un autre de la version : le manifeste « extra » ne se fusionne que
        # sur demande, et un remote qui n'y vit que manquerait alors.
        # ajouter_remote ne touche pas un fichier qui le déclare déjà.
        text = text[:debut] + tag + text[fin:]
        return (
            ajouter_remote(text, changement["remote"], changement["fetch"]),
            True,
        )
    return text, False
