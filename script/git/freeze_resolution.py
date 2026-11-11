#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Résoudre l'écart d'un dépôt d'addons à son gel.

Les dépôts viennent de `repo_state.py snapshot` : chaque entrée porte
« path », « url » (celle du manifeste), « head », « branch »,
« manifest_branch », « freeze_revision » et « freeze », l'écart de HEAD au
commit gelé (« alignment »). Ce module ÉCRIT : il déplace des HEAD et
réécrit `manifest/`, et chaque appelant demande d'abord.

Deux résolutions, selon le sens de l'écart :

- remettre au gel — HEAD est en retard sur le gel, ou le commit gelé manque
  au clone. Le commit est rapatrié depuis l'URL du manifeste et non depuis
  le remote du clone : un projet dont le manifeste a changé de fork garde
  l'ancien remote jusqu'à la prochaine synchronisation, et le commit gelé
  n'y est pas. Un clone tronqué le reçoit en profondeur 1. HEAD est ensuite
  détaché sur lui, comme git-repo le laisse ; une branche locale reste où
  elle était.
- mettre à jour le gel — HEAD porte des commits que le gel n'a pas. HEAD
  devient le gel, dans les fichiers de `manifest/` qui portaient l'ancien,
  mais seulement s'il est publié : un gel que personne d'autre ne peut
  rapatrier casse l'installation suivante.

Un dépôt aux fichiers modifiés n'est jamais touché. Un écart dans les deux
sens (« decale »), ou que le clone tronqué ne permet pas de mesurer
(« indetermine »), demande un choix humain : il est seulement classé.
"""

import glob
import os
import shlex
import subprocess

from script.git import manifest_freeze

DELAI_GIT = 60
DELAI_RESEAU = 300

REMETTRE = "remettre"
MAJ_GEL = "maj_gel"
SALES = "sales"
MANUELS = "manuels"
# L'alignement de « freeze » qui mène à chaque résolution.
PAR_ALIGNEMENT = {
    "en_retard": REMETTRE,
    "introuvable": REMETTRE,
    "en_avance": MAJ_GEL,
    "decale": MANUELS,
    "indetermine": MANUELS,
    "erreur": MANUELS,
}


def git(clone, *args, delai=DELAI_GIT):
    """`git -C clone args` ; rend le CompletedProcess, sans lever : le code
    127 dit que git manque, 124 que le délai a expiré."""
    try:
        return subprocess.run(
            ["git", "-C", clone, *args],
            capture_output=True,
            text=True,
            timeout=delai,
            stdin=subprocess.DEVNULL,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args, 124, "", "timeout")
    except OSError as exc:
        return subprocess.CompletedProcess(args, 127, "", str(exc))


def hors_gel(depot):
    """L'alignement de `depot` à son gel quand il n'y est pas, sinon None."""
    alignement = (depot.get("freeze") or {}).get("alignment")
    return None if alignement in (None, "conforme") else alignement


def classer(depots, est_sale):
    """{résolution: [dépôts]} pour les dépôts hors de leur gel.

    `est_sale(depot)` dit si le clone a des fichiers modifiés : un tel dépôt
    va dans SALES quel que soit son écart, et rien ne le déplace."""
    classes = {REMETTRE: [], MAJ_GEL: [], SALES: [], MANUELS: []}
    for depot in depots:
        alignement = hors_gel(depot)
        if not alignement:
            continue
        if est_sale(depot):
            classes[SALES].append(depot)
        else:
            classes[PAR_ALIGNEMENT.get(alignement, MANUELS)].append(depot)
    return classes


class _Git:
    """`git -C <clone>` pour un dépôt du checkout. Chaque appel passe
    d'abord à `noter`, quand il est donné, sous la forme qu'on retaperait
    depuis la racine : « git -C <chemin relatif> … »."""

    def __init__(self, racine, chemin, noter=None):
        self.clone = os.path.join(racine, chemin)
        self.chemin = chemin
        self.noter = noter

    def __call__(self, *args, delai=DELAI_GIT):
        if self.noter:
            self.noter(shlex.join(["git", "-C", self.chemin, *args]))
        return git(self.clone, *args, delai=delai)


def _sale(g):
    """Vrai si le clone a des fichiers suivis modifiés ou des fichiers non
    suivis que rien n'ignore ; None si git ne répond pas."""
    fait = g("status", "--porcelain")
    if fait.returncode != 0:
        return None
    return bool(fait.stdout.strip())


def _a_le_commit(g, sha):
    return g("cat-file", "-e", f"{sha}^{{commit}}").returncode == 0


def _superficiel(g):
    return g("rev-parse", "--is-shallow-repository").stdout.strip() == "true"


def remettre_au_gel(racine, depot, noter=None):
    """Détache HEAD sur le commit gelé de `depot`. Rend (réussi, message).

    Refuse un clone modifié. Rapatrie d'abord le commit s'il manque, depuis
    l'URL du manifeste. `noter(commande)` reçoit chaque commande git avant
    qu'elle tourne."""
    g = _Git(racine, depot["path"], noter)
    sha = depot.get("freeze_revision")
    if not sha:
        return False, "no freeze-revision"
    etat = _sale(g)
    if etat is None:
        return False, "git status failed"
    if etat:
        return False, "modified files"
    if not _a_le_commit(g, sha):
        url = depot.get("url")
        if not url:
            return False, "no manifest URL to fetch the frozen commit from"
        profondeur = ["--depth=1"] if _superficiel(g) else []
        fait = g("fetch", "--quiet", *profondeur, url, sha, delai=DELAI_RESEAU)
        if fait.returncode != 0 or not _a_le_commit(g, sha):
            return False, (fait.stderr.strip() or "fetch failed")
    fait = g("checkout", "--quiet", "--detach", sha)
    if fait.returncode != 0:
        return False, fait.stderr.strip() or "checkout failed"
    return True, sha[:10]


def _tetes_distantes(g, url):
    """{sha: [branches]} des branches publiées à `url`, ou None."""
    fait = g("ls-remote", "--heads", url, delai=DELAI_RESEAU)
    if fait.returncode != 0:
        return None
    tetes = {}
    for ligne in fait.stdout.splitlines():
        sha, _, ref = ligne.partition("\t")
        tetes.setdefault(sha, []).append(ref.removeprefix("refs/heads/"))
    return tetes


def _contenu_dans(g, url, branche, head):
    """Vrai si `head` est un ancêtre de `branche` publiée à `url`."""
    profondeur = ["--depth=200"] if _superficiel(g) else []
    fait = g("fetch", "--quiet", *profondeur, url, branche, delai=DELAI_RESEAU)
    if fait.returncode != 0:
        return False
    return g("merge-base", "--is-ancestor", head, "FETCH_HEAD").returncode == 0


def publication(racine, depot, noter=None):
    """(publié, détail) pour le HEAD de `depot`.

    Publié quand HEAD est la pointe d'une branche à l'URL du manifeste, ou
    un ancêtre de la branche du manifeste ou de la branche locale courante
    une fois rapatriées. Sinon, le détail dit quoi pousser : la branche
    courante, ou, HEAD détaché, qu'il faut d'abord une branche. None quand
    l'URL ne répond pas. `noter` comme pour `remettre_au_gel`."""
    g = _Git(racine, depot["path"], noter)
    url, head = depot.get("url"), depot.get("head")
    if not url or not head:
        return None, "no manifest URL"
    tetes = _tetes_distantes(g, url)
    if tetes is None:
        return None, f"{url} unreachable"
    if head in tetes:
        return True, ", ".join(tetes[head])
    branches = [
        b for b in (depot.get("manifest_branch"), depot.get("branch")) if b
    ]
    for branche in dict.fromkeys(branches):
        if _contenu_dans(g, url, branche, head):
            return True, branche
    if depot.get("branch"):
        return False, f"git -C {depot['path']} push {url} {depot['branch']}"
    return False, "detached HEAD"


def fichiers_manifeste(racine):
    return sorted(glob.glob(os.path.join(racine, "manifest", "*.xml")))


def mettre_a_jour_gel(racine, depots, ecrire=True):
    """Pose le HEAD de chaque dépôt comme « freeze-revision » dans les
    fichiers de `manifest/` qui portent son ancien gel. Rend
    ({fichier relatif: [clés]}, [clés qui perdent leur base amont]).

    Seul l'élément `<project>` dont le gel vaut l'ancien commit change : un
    même projet gelé ailleurs sur un autre commit n'est pas touché. Changer
    le gel retire « fork-upstream-freeze-revision », qui ne vaut que pour
    le commit à côté de lui."""
    anciens = {
        manifest_freeze.project_key(d.get("name"), d["path"]): (
            d.get("freeze_revision"),
            d["head"],
        )
        for d in depots
    }
    changes, sans_base = {}, []
    for fichier in fichiers_manifeste(racine):
        with open(fichier) as fh:
            texte = fh.read()
        a_geler = {}
        for _debut, _fin, attrs in manifest_freeze.iter_projects(texte):
            cle = manifest_freeze.project_key(
                attrs.get("name"), attrs.get("path")
            )
            if (
                cle in anciens
                and attrs.get(manifest_freeze.FREEZE_ATTR) == (anciens[cle][0])
            ):
                a_geler[cle] = anciens[cle][1]
                if attrs.get(manifest_freeze.FORK_UPSTREAM_FREEZE_ATTR):
                    sans_base.append(cle)
        if not a_geler:
            continue
        neuf, cles = manifest_freeze.rewrite(texte, freeze=a_geler)
        if not cles:
            continue
        changes[os.path.relpath(fichier, racine)] = cles
        if ecrire:
            with open(fichier, "w") as fh:
                fh.write(neuf)
    return changes, sorted(set(sans_base))
