#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Une surcouche privée qui fait synchroniser les dépôts depuis une forge.

La surcouche est un manifeste de `private/manifest/` qui ne porte que des
`<remote name=… fetch=…>` : la fusion des manifestes
(`git_merge_repo_manifest`) lit les fichiers privés en dernier, et le
dernier fichier qui définit un remote l'emporte. Chaque remote redéfini
garde son nom et prend pour fetch « <base>/<propriétaire>/ », le
propriétaire étant le dernier segment de son fetch d'origine : la forge
porte la même arborescence que l'hôte d'origine, celle que
`push_remote.plan_remote` y pousse. Les projets, leurs révisions et leurs
gels ne changent pas.

Les URL de la forge, qui nomment un hôte, restent ainsi hors de
`manifest/`. La surcouche prend effet à la reconfiguration suivante (`make
repo_configure_all`) : git-repo réécrit alors l'URL de ces remotes dans
chaque clone. La retirer, puis reconfigurer, ramène les URL d'origine.

Une surcouche redirige des REMOTES entiers : un projet d'un autre fichier
fusionné servi par l'un d'eux se synchronise aussi depuis la forge, et
échoue s'il n'y a pas été poussé. `projets_non_couverts` les liste.
"""

import csv
import os
import re
import sys
from xml.sax.saxutils import quoteattr

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
if new_path not in sys.path:
    sys.path.append(new_path)

from script.git import push_remote  # noqa: E402
from script.git import git_freeze_manifest, manifest_repo  # noqa: E402

GABARIT = os.path.join(
    git_freeze_manifest.PRIVATE_MANIFEST_DIR, "git_manifest_forge_{nom}.xml"
)
NOM_VALIDE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def chemin(nom):
    """La surcouche du remote de forge `nom`, relative à la racine. Lève
    ValueError pour un nom qui ne ferait pas un nom de fichier sûr."""
    if not NOM_VALIDE.match(nom or ""):
        raise ValueError(f"invalid remote name: {nom!r}")
    return GABARIT.format(nom=nom)


def remotes_rediriges(projets, base):
    """{remote du manifeste: fetch sur la forge} pour les `projets` (ceux
    de `push_remote.projets_actifs`). Un projet sans propriétaire connu
    n'apporte rien : son remote garde son URL."""
    rediriges = {}
    for p in projets:
        if p.get("remote") and p.get("proprietaire"):
            rediriges[p["remote"]] = f"{base.rstrip('/')}/{p['proprietaire']}/"
    return dict(sorted(rediriges.items()))


def texte(remotes):
    """Le manifeste qui redéfinit `remotes` ({nom: fetch})."""
    lignes = ['<?xml version="1.0" encoding="UTF-8" ?>', "<manifest>"]
    lignes += [
        f"    <remote name={quoteattr(n)} fetch={quoteattr(f)} />"
        for n, f in sorted(remotes.items())
    ]
    return "\n".join(lignes + ["</manifest>", ""])


def lire(racine, nom):
    """{nom: fetch} de la surcouche `nom` sous `racine`, ou {} sans elle."""
    import xml.etree.ElementTree as ET

    try:
        arbre = ET.parse(os.path.join(racine, chemin(nom))).getroot()
    except (ET.ParseError, OSError):
        return {}
    return {e.get("name"): e.get("fetch") for e in arbre.findall("remote")}


def _lignes_csv(racine):
    fichier = os.path.join(racine, manifest_repo.CSV_PRIVE)
    if not os.path.isfile(fichier):
        return []
    with open(fichier, encoding="utf-8", newline="") as fh:
        return [r.get("filepath", "") for r in csv.DictReader(fh)]


def _ecrire_csv(racine, lignes):
    fichier = os.path.join(racine, manifest_repo.CSV_PRIVE)
    os.makedirs(os.path.dirname(fichier), exist_ok=True)
    with open(fichier, "w", encoding="utf-8", newline="") as fh:
        fh.write('"filepath"\n')
        for ligne in lignes:
            fh.write(f"{ligne}\n")


def ecrire(racine, nom, remotes):
    """Écrit la surcouche `nom` et la place en DERNIER dans la liste des
    fichiers privés que la fusion lit : un manifeste privé lu après elle
    pourrait redéfinir l'un de ses remotes. Rend son chemin relatif."""
    relatif = chemin(nom)
    absolu = os.path.join(racine, relatif)
    os.makedirs(os.path.dirname(absolu), exist_ok=True)
    with open(absolu, "w", encoding="utf-8") as fh:
        fh.write(texte(remotes))
    autres = [
        ligne
        for ligne in _lignes_csv(racine)
        if os.path.normpath(ligne) != os.path.normpath(relatif)
    ]
    _ecrire_csv(racine, autres + [relatif])
    return relatif


def retirer(racine, nom):
    """Retire la surcouche `nom` et son inscription. Rend vrai si l'une ou
    l'autre existait."""
    relatif = chemin(nom)
    absolu = os.path.join(racine, relatif)
    existait = os.path.isfile(absolu)
    if existait:
        os.remove(absolu)
    lignes = _lignes_csv(racine)
    restantes = [
        ligne
        for ligne in lignes
        if os.path.normpath(ligne) != os.path.normpath(relatif)
    ]
    if len(restantes) != len(lignes):
        _ecrire_csv(racine, restantes)
        existait = True
    return existait


def surcouches(racine):
    """Les noms des surcouches présentes sous `racine`, triés."""
    dossier = os.path.join(racine, git_freeze_manifest.PRIVATE_MANIFEST_DIR)
    motif = re.compile(r"^git_manifest_forge_(.+)\.xml$")
    try:
        noms = os.listdir(dossier)
    except OSError:
        return []
    return sorted(m.group(1) for m in map(motif.match, noms) if m)


def projets_non_couverts(remotes, couverts, sources=None):
    """{clé: remote} des projets de la fusion servis par l'un des `remotes`
    mais absents de `couverts` (des clés de projet), triés par clé : ceux
    qu'une synchronisation chercherait sur la forge sans qu'ils y aient été
    poussés, les fragments communs à toutes les versions compris.
    `sources` : les fichiers de la fusion, par défaut ceux du checkout (le
    dossier courant doit être la racine)."""
    if sources is None:
        sources = git_freeze_manifest.default_sources()
    definitions = git_freeze_manifest.read_sources(sources)
    defaut = git_freeze_manifest.read_default(sources)
    manquants = {}
    for cle, defs in definitions.items():
        remote = defs[-1][1].get("remote") or defaut.get("remote")
        if remote in remotes and cle not in couverts:
            manquants[cle] = remote
    return dict(sorted(manquants.items()))


def base_du_remote(projets, nom):
    """La base de forge du remote `nom` des clones, déduite de son URL
    dans le premier clone qui le porte : l'URL privée de
    « <propriétaire>/<dépôt>.git ». None sans clone qui le porte."""
    from script.git import repo_upgrade

    for p in projets:
        url = repo_upgrade.url_du_remote(p["chemin"], nom)
        if not url or not p.get("proprietaire") or not p.get("nom"):
            continue
        suffixe = push_remote.url_cible("", p["proprietaire"], p["nom"])
        if url.endswith(suffixe):
            return url[: -len(suffixe)] or None
    return None
