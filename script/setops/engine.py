#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le moteur Set-OPS tel que le manifeste le déclare, et ce que git en dit.

LE MANIFESTE EST LA SEULE AUTORITÉ. `manifest/git_manifest_setops.xml` porte
le chemin du moteur et la révision épinglée. La fusion des manifestes, le
script de rapatriement et l'écran d'état les LISENT ici plutôt que d'en
garder une copie, qui divergerait au premier déplacement.

PUR D'UN CÔTÉ, E/S MINCES DE L'AUTRE. `parse_manifest`, `groups_of`,
`mise_de_cote`, `is_pinned` et `ignore_probe` travaillent sur du texte. Les
autres fonctions lisent le disque ou lancent `git`, et ne lèvent jamais : un
verdict inconnu vaut `None` — ou la relation `inconnue` —, et l'appelant
décide quoi en dire.

GIT NE REMONTE JAMAIS AU-DESSUS DU DOSSIER VISÉ. Un dossier sans `.git` posé
sous le checkout d'ERPLibre ferait répondre le dépôt englobant : son HEAD
passerait pour celui du moteur, son arbre sali pour celui du moteur.
`GIT_CEILING_DIRECTORIES` arrête la recherche au dossier visé.

Aucun import du code du moteur, aucun appel réseau.

Point d'entrée, lancé DEPUIS LA RACINE d'ERPLibre (la racine est le dossier
courant, comme pour les scripts de script/manifest/) :

    python -m script.setops.engine chemin
    python -m script.setops.engine verifier-emplacement
"""

from __future__ import annotations

import argparse
import os
import posixpath
import re
import shlex
import subprocess
import sys
import xml.etree.ElementTree as ET
from typing import NamedTuple

MANIFEST = os.path.join("manifest", "git_manifest_setops.xml")
GROUP = "setops"

# Relations entre le HEAD du clone et l'épingle. Le vocabulaire est clos.
# `absente` est un constat — git lit le clone, l'épingle n'y est pas — et
# `inconnue` l'absence de constat : les confondre ferait conseiller un
# rapatriement là où rien n'établit qu'il manque quelque chose.
EGAL = "egal"
AVANCE = "avance"
RETARD = "retard"
DIVERGE = "diverge"
ABSENTE = "absente"
INCONNUE = "inconnue"
RELATIONS = (EGAL, AVANCE, RETARD, DIVERGE, ABSENTE, INCONNUE)

# Codes de sortie du point d'entrée, lus par le script de rapatriement.
RC_OK = 0
RC_DECLARATION = 2
RC_OCCUPE = 3

# Un nom qu'aucun fichier ne porte, posé SOUS le parent pour interroger ses
# règles d'exclusion : voir `ignore_probe`.
SONDE = ".sonde-setops-ignore"

# Borne de chaque appel git local. Aucun ne touche le réseau : dépasser ce
# délai veut dire un dépôt verrouillé ou un disque qui ne répond plus.
GIT_TIMEOUT = 30

_SHA = re.compile(r"[0-9a-fA-F]{40}")


class Declaration(NamedTuple):
    """Le projet Set-OPS du manifeste : où il se pose, sur quelle révision."""

    path: str
    revision: str
    upstream: str
    remote: str


def groups_of(texte) -> list[str]:
    """Les groupes d'un attribut « groups », découpés comme Google Repo les
    découpe : sur les virgules ET les blancs, éléments vides écartés."""
    if not isinstance(texte, str):
        return []
    return [g for g in re.split(r"[,\s]+", texte) if g]


def parse_manifest(texte) -> Declaration | None:
    """La déclaration du moteur dans le texte d'un manifeste Google Repo.

    Le moteur est LE projet du groupe `setops` : aucun, ou deux, et rien
    n'est déclaré. Un texte illisible ne déclare rien non plus.

    Le chemin reste sous la racine de l'espace de travail — ni absolu, ni
    remontant par « .. » — ou il n'est pas déclaré : il finit dans une
    commande « mv » affichée à l'utilisateur. Il est rendu normalisé.

    Une révision absente est rendue vide : la déclaration existe, elle n'est
    pas épinglée, et `is_pinned` le dira.
    """
    if not isinstance(texte, str) or not texte.strip():
        return None
    try:
        arbre = ET.fromstring(texte)
    except ET.ParseError:
        return None
    defaut = arbre.find("default")
    remote_defaut = defaut.get("remote", "") if defaut is not None else ""
    retenus = [
        p
        for p in arbre.findall("project")
        if GROUP in groups_of(p.get("groups"))
    ]
    if len(retenus) != 1:
        return None
    projet = retenus[0]
    chemin = (projet.get("path") or "").strip()
    if not chemin or posixpath.isabs(chemin):
        return None
    chemin = posixpath.normpath(chemin)
    if chemin == "." or chemin == ".." or chemin.startswith("../"):
        return None
    return Declaration(
        path=chemin,
        revision=(projet.get("revision") or "").strip(),
        upstream=(projet.get("upstream") or "").strip(),
        remote=(projet.get("remote") or remote_defaut).strip(),
    )


def declaration(racine) -> Declaration | None:
    """La déclaration lue dans `MANIFEST` sous `racine` ; None si illisible."""
    try:
        with open(os.path.join(racine, MANIFEST), encoding="utf-8") as f:
            return parse_manifest(f.read())
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def mise_de_cote(chemin) -> str:
    """La commande qui met de côté un clone occupant `chemin`, sans rien
    supprimer ; le chemin est cité pour être recopié tel quel."""
    return f"mv {shlex.quote(chemin)} {shlex.quote(chemin + '.manuel')}"


def is_pinned(revision) -> bool:
    """Vrai pour un SHA complet de 40 hex, seule révision qui ne bouge pas.

    Une branche, un tag ou un SHA abrégé désignent demain autre chose
    qu'aujourd'hui.
    """
    return isinstance(revision, str) and bool(_SHA.fullmatch(revision))


def managed_by_repo(racine, chemin) -> bool | None:
    """`chemin` figure-t-il dans `.repo/project.list` sous `racine` ?

    None sans `.repo/` : rien n'est géré, rien ne peut s'en dire. Un
    `.repo/` initialisé mais jamais synchronisé n'a pas de liste, et ne
    gère donc rien : False. Une liste illisible vaut None.
    """
    dossier = os.path.join(racine, ".repo")
    if not os.path.isdir(dossier):
        return None
    liste = os.path.join(dossier, "project.list")
    if not os.path.lexists(liste):
        return False
    cherche = posixpath.normpath(str(chemin).strip())
    try:
        with open(liste, encoding="utf-8") as f:
            lignes = f.read().splitlines()
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    return any(
        posixpath.normpath(ligne.strip()) == cherche
        for ligne in lignes
        if ligne.strip()
    )


def repo_worktree(racine, chemin) -> bool | None:
    """L'arbre `chemin` est-il un de ceux que Google Repo pose sous `racine` ?

    `managed_by_repo` dit ce que le dernier sync VISAIT : repo écrit sa
    liste même quand le rapatriement échoue. Ici se lit ce qu'il a POSÉ.
    Repo garde le dépôt git hors de l'arbre : `.git` y est un lien vers
    `.repo/projects/`, ou un fichier « gitdir: » vers `.repo/` (arbres
    « git worktree »). Seule compte la destination, résolue : un clone
    manuel porte un vrai dossier `.git`, et un arbre sans `.git` en est un
    sur lequel repo extrairait sa révision par-dessus les fichiers présents
    — tous deux False.

    None si le fichier « gitdir: » ne se lit pas.
    """
    depot_repo = os.path.realpath(os.path.join(racine, ".repo"))
    dotgit = os.path.join(racine, chemin, ".git")
    if os.path.isdir(dotgit):
        gitdir = dotgit
    elif os.path.isfile(dotgit):
        try:
            with open(dotgit, encoding="utf-8") as f:
                premiere = f.readline().strip()
        except (OSError, UnicodeDecodeError, ValueError):
            return None
        if not premiere.startswith("gitdir:"):
            return False
        gitdir = os.path.join(
            os.path.dirname(dotgit), premiere[len("gitdir:") :].strip()
        )
    else:
        return False
    reel = os.path.realpath(gitdir)
    return os.path.commonpath([reel, depot_repo]) == depot_repo


def _git(dossier, *args):
    """`git -C dossier args`, recherche du dépôt bornée à `dossier`.

    Rend le CompletedProcess, ou None quand git n'a pas pu tourner (absent,
    délai dépassé, argument invalide). L'environnement hérité perd ses
    `GIT_*` — un `GIT_DIR` posé par un hook viserait un autre dépôt — et
    gagne `GIT_OPTIONAL_LOCKS=0` : une lecture ne prend pas le verrou de
    l'index qu'une synchronisation concurrente attend. Il gagne aussi
    `GIT_NO_LAZY_FETCH=1` : dans un clone partiel, git demanderait un objet
    absent au remote qui l'a promis, un appel réseau. git 2.45 et suivants
    honorent la variable ; les plus anciens l'ignorent.
    """
    try:
        reel = os.path.realpath(dossier)
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env["GIT_CEILING_DIRECTORIES"] = os.path.dirname(reel)
        env["GIT_OPTIONAL_LOCKS"] = "0"
        env["GIT_NO_LAZY_FETCH"] = "1"
        return subprocess.run(
            ["git", "-C", reel, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=GIT_TIMEOUT,
            check=False,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _is_ancestor(moteur, ancetre, descendant) -> bool | None:
    """`merge-base --is-ancestor` : 0 oui, 1 non, tout autre code inconnu."""
    fait = _git(moteur, "merge-base", "--is-ancestor", ancetre, descendant)
    if fait is None or fait.returncode not in (0, 1):
        return None
    return fait.returncode == 0


def _count(moteur, plage) -> int | None:
    """Le nombre de commits de `plage` (« a..b »), None si illisible."""
    fait = _git(moteur, "rev-list", "--count", plage)
    if fait is None or fait.returncode:
        return None
    try:
        return int(fait.stdout.strip())
    except ValueError:
        return None


def relation_to_pin(moteur, sha) -> tuple[str, int | None]:
    """Où le HEAD du clone `moteur` se tient par rapport à l'épingle `sha`.

    Rend (relation, n), relation dans `RELATIONS` :
    - `egal` : n = 0 ;
    - `avance` : n = commits du HEAD absents de l'épingle ;
    - `retard` : n = commits de l'épingle absents du HEAD ;
    - `diverge` : n = None, chaque côté porte ce que l'autre n'a pas ;
    - `absente` : n = None, git lit le HEAD du clone et n'y trouve pas
      l'objet épinglé — épingle jamais rapatriée ;
    - `inconnue` : n = None, rien n'est établi — `sha` n'est pas un SHA
      complet, git ne lit pas le HEAD ou ne répond pas, l'épingle n'est
      pas un commit, ou `merge-base` échoue.

    `cat-file -e` sur l'objet nu rend 1 pour un objet absent, et tout
    autre échec par un autre code : seul ce 1 vaut `absente`. Le suffixe
    « ^{commit} » confondrait les deux, et se résout donc à part : c'est
    le commit qu'il rend qui se compare au HEAD. Une épingle qui désigne
    un tag annoté vaut ainsi le commit du tag, et non le SHA du tag, que
    ne porte aucun HEAD.

    Tout se lit dans les objets locaux, sans réseau.
    """
    if not is_pinned(sha):
        return INCONNUE, None
    epingle = sha.lower()
    tete = _git(moteur, "rev-parse", "--verify", "-q", "HEAD^{commit}")
    if tete is None or tete.returncode:
        return INCONNUE, None
    head = tete.stdout.strip()
    present = _git(moteur, "cat-file", "-e", epingle)
    if present is None or present.returncode not in (0, 1):
        return INCONNUE, None
    if present.returncode == 1:
        return ABSENTE, None
    commit = _git(moteur, "rev-parse", "--verify", "-q", epingle + "^{commit}")
    if commit is None or commit.returncode:
        return INCONNUE, None
    epingle = commit.stdout.strip()
    if head == epingle:
        return EGAL, 0
    epingle_dans_head = _is_ancestor(moteur, epingle, head)
    head_dans_epingle = _is_ancestor(moteur, head, epingle)
    if epingle_dans_head is None or head_dans_epingle is None:
        return INCONNUE, None
    if epingle_dans_head:
        return AVANCE, _count(moteur, f"{epingle}..{head}")
    if head_dans_epingle:
        return RETARD, _count(moteur, f"{head}..{epingle}")
    return DIVERGE, None


def dirty_count(moteur) -> int | None:
    """Le nombre d'entrées de `git status --porcelain`, fichiers non suivis
    compris ; None si `moteur` n'est pas un dépôt lisible."""
    fait = _git(moteur, "status", "--porcelain")
    if fait is None or fait.returncode:
        return None
    return sum(1 for ligne in fait.stdout.splitlines() if ligne.strip())


def ignore_probe(chemin) -> str:
    """Le chemin que `parent_is_ignored` soumet à git pour un moteur posé en
    `chemin` : `SONDE`, directement sous le parent normalisé.

    La question porte sur un nom inventé SOUS le parent, et non sur le
    parent lui-même : une règle « dossier/ » ne vaut que pour un dossier,
    et git ne sait pas qu'un chemin absent du disque en est un. La sonde
    répond donc aussi sur un clone neuf. L'écran d'état cite ce chemin dans
    sa source : le verdict et sa source posent la même question.
    """
    parent = posixpath.dirname(posixpath.normpath(str(chemin)))
    return posixpath.join(parent, SONDE)


def parent_is_ignored(racine, chemin) -> bool | None:
    """Ce qui se pose à côté de `chemin` est-il ignoré par le dépôt `racine` ?

    Le moteur cherche ses écosystèmes parmi ses dossiers FRÈRES : c'est le
    parent qui doit être ignoré, faute de quoi un écosystème — des données
    de client — serait commité avec ERPLibre. La question porte sur
    `ignore_probe(chemin)` ; `--no-index` interroge les règles seules.

    None si `racine` n'est pas un dépôt git lisible.
    """
    sonde = ignore_probe(chemin)
    fait = _git(racine, "check-ignore", "-q", "--no-index", "--", sonde)
    if fait is None or fait.returncode not in (0, 1):
        return None
    return fait.returncode == 0


def main(argv=None, racine=None, out=None, err=None) -> int:
    """Point d'entrée du script de rapatriement ; rend le code de sortie.

    - `chemin` : écrit le chemin déclaré, seul sur sa ligne ;
    - `verifier-emplacement` : 0 si le chemin est libre, ou si Google Repo
      le liste ET y a posé l'arbre ; `RC_OCCUPE` si autre chose l'occupe,
      avec la commande qui le met de côté. Rien n'est jamais supprimé ni
      déplacé ici.

    Sans déclaration lisible, les deux rendent `RC_DECLARATION`.
    """
    out = out or sys.stdout
    err = err or sys.stderr
    racine = racine or os.getcwd()
    parser = argparse.ArgumentParser(
        prog="python -m script.setops.engine",
        description="Le moteur Set-OPS déclaré par " + MANIFEST + ".",
    )
    parser.add_argument("action", choices=("chemin", "verifier-emplacement"))
    args = parser.parse_args(argv)

    decl = declaration(racine)
    if decl is None:
        print(
            f"Erreur : aucune déclaration lisible du moteur dans {MANIFEST}"
            f" (un seul projet du groupe « {GROUP} », chemin sous la"
            " racine).",
            file=err,
        )
        return RC_DECLARATION
    if args.action == "chemin":
        print(decl.path, file=out)
        return RC_OK

    if not os.path.lexists(os.path.join(racine, decl.path)):
        return RC_OK
    if (
        managed_by_repo(racine, decl.path) is True
        and repo_worktree(racine, decl.path) is True
    ):
        return RC_OK
    print(
        f"Erreur : {decl.path} existe et Google Repo ne le gère pas.\n"
        "  repo sync refuserait d'y poser le moteur, ou extrairait sa"
        " révision par-dessus les fichiers présents. Rien n'est supprimé"
        " ici :\n"
        "  mettre ce dossier de côté, puis relancer.\n"
        f"    {mise_de_cote(decl.path)}",
        file=err,
    )
    return RC_OCCUPE


if __name__ == "__main__":
    sys.exit(main())
