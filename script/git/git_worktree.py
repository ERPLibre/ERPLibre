#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les worktrees git d'un checkout : les lister, en créer, en retirer.

Un worktree est un second répertoire de travail du même dépôt, sur une
autre branche : deux branches s'éditent et se testent côte à côte sans
remiser ni changer de branche. git refuse d'extraire une branche déjà
extraite dans un autre worktree ; `worktree_de_branche` dit lequel la
tient.

Un worktree d'ERPLibre ne porte que les fichiers suivis : ni les venvs, ni
les dépôts d'addons de Google Repo, ni `config.conf`, ni `private/`. Les
tests de l'outillage y tournent avec le venv du checkout principal ; une
instance Odoo, elle, demande le checkout principal.

Chaque fonction prend `lancer`, un subprocess.run, pour se tester sans
dépôt. Lancé seul, le module liste les worktrees :
    ./script/git/git_worktree.py [--racine CHEMIN]
"""

import argparse
import os
import re
import subprocess
import sys


def _git(racine, args, lancer=subprocess.run):
    """(code, sortie, erreur) de `git -C racine args`."""
    try:
        fait = lancer(
            ["git", "-C", racine] + list(args),
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        return 1, "", str(exc)
    return fait.returncode, fait.stdout, fait.stderr.strip()


def analyser(porcelaine):
    """Les worktrees de la sortie de `git worktree list --porcelain`, dans
    son ordre, le principal en tête. Chacun est un dict : path, head,
    branch (sans refs/heads/, None détaché), detached, bare, locked,
    prunable (raison ou None)."""
    worktrees = []
    courant = None
    for ligne in porcelaine.splitlines():
        if not ligne:
            courant = None
            continue
        cle, _, valeur = ligne.partition(" ")
        if cle == "worktree":
            courant = {
                "path": valeur,
                "head": None,
                "branch": None,
                "detached": False,
                "bare": False,
                "locked": None,
                "prunable": None,
            }
            worktrees.append(courant)
        elif courant is None:
            continue
        elif cle == "HEAD":
            courant["head"] = valeur
        elif cle == "branch":
            courant["branch"] = valeur.removeprefix("refs/heads/")
        elif cle in ("detached", "bare"):
            courant[cle] = True
        elif cle in ("locked", "prunable"):
            courant[cle] = valeur or cle
    return worktrees


def lister(racine, lancer=subprocess.run):
    """Les worktrees du dépôt de `racine` (voir `analyser`), chacun avec
    « principal » vrai pour le premier et « existe » faux pour un
    répertoire disparu. Lève ValueError hors d'un dépôt git."""
    code, sortie, erreur = _git(
        racine, ["worktree", "list", "--porcelain"], lancer
    )
    if code:
        raise ValueError(erreur or "git worktree list")
    worktrees = analyser(sortie)
    for rang, worktree in enumerate(worktrees):
        worktree["principal"] = rang == 0
        worktree["existe"] = os.path.isdir(worktree["path"])
    return worktrees


def fichiers_modifies(chemin, lancer=subprocess.run):
    """Le nombre de fichiers modifiés ou non suivis du worktree `chemin`,
    ou None s'il ne se lit pas."""
    code, sortie, _erreur = _git(
        chemin, ["status", "--porcelain", "--untracked-files=normal"], lancer
    )
    if code:
        return None
    return len([ligne for ligne in sortie.splitlines() if ligne.strip()])


def worktree_de_branche(worktrees, branche):
    """Le worktree qui tient `branche` extraite, ou None."""
    for worktree in worktrees:
        if worktree["branch"] == branche:
            return worktree
    return None


def chemin_propose(racine_principale, branche):
    """Un répertoire voisin du checkout principal, nommé d'après lui et la
    fin de `branche` : « ~/git/erplibre » et « dev/odoo_18_fix » donnent
    « ~/git/erplibre_odoo_18_fix ». Garder le worktree hors du checkout
    évite que git status, Google Repo ou les outils qui balaient l'arbre
    le prennent pour du contenu."""
    principal = os.path.normpath(racine_principale)
    fin = re.sub(r"[^A-Za-z0-9._-]+", "_", branche.rsplit("/", 1)[-1])
    return os.path.join(
        os.path.dirname(principal),
        f"{os.path.basename(principal)}_{fin.strip('_') or 'worktree'}",
    )


def branche_existe(racine, branche, lancer=subprocess.run):
    """Vrai quand `branche` est une branche locale du dépôt."""
    code, _sortie, _erreur = _git(
        racine,
        ["show-ref", "--verify", "--quiet", f"refs/heads/{branche}"],
        lancer,
    )
    return code == 0


def commande_creer(chemin, branche, base=None, nouvelle=True):
    """Les arguments de `git worktree add` : une nouvelle `branche` partie
    de `base` (HEAD si None), ou une branche existante extraite."""
    if nouvelle:
        args = ["worktree", "add", "-b", branche, chemin]
        return args + [base] if base else args
    return ["worktree", "add", chemin, branche]


def creer(racine, chemin, branche, base=None, nouvelle=True, lancer=None):
    """Crée le worktree ; rend (code, message de git)."""
    code, sortie, erreur = _git(
        racine,
        commande_creer(chemin, branche, base, nouvelle),
        lancer or subprocess.run,
    )
    return code, (erreur or sortie).strip()


def supprimer(racine, chemin, forcer=False, lancer=subprocess.run):
    """Retire le worktree `chemin` : son répertoire et son entrée. git
    refuse un worktree aux fichiers modifiés ou verrouillé, sauf
    `forcer`. La branche reste. Rend (code, message de git)."""
    args = ["worktree", "remove"] + (["--force"] if forcer else []) + [chemin]
    code, sortie, erreur = _git(racine, args, lancer)
    return code, (erreur or sortie).strip()


def supprimer_branche(racine, branche, lancer=subprocess.run):
    """`git branch -d` : ne retire qu'une branche fusionnée dans son amont
    ou dans HEAD, jamais du travail non fusionné. Rend (code, message)."""
    code, sortie, erreur = _git(racine, ["branch", "-d", branche], lancer)
    return code, (erreur or sortie).strip()


def nettoyer(racine, simuler=True, lancer=subprocess.run):
    """`git worktree prune` : oublie les entrées dont le répertoire a
    disparu, effacé à la main au lieu d'être retiré. `simuler` montre ce
    qui partirait sans rien toucher. Rend (code, lignes de git)."""
    args = ["worktree", "prune", "--verbose"] + (
        ["--dry-run"] if simuler else []
    )
    code, sortie, erreur = _git(racine, args, lancer)
    lignes = [ligne for ligne in (sortie + erreur).splitlines() if ligne]
    return code, lignes


def decrire(worktree, modifies=None, maison=None, traduire=str):
    """Une ligne lisible : chemin (~ pour `maison`), branche ou commit
    détaché, puis les marques — principal, verrouillé, disparu, fichiers
    modifiés —, chacune passée par `traduire`."""
    chemin = worktree["path"]
    maison = maison if maison is not None else os.path.expanduser("~")
    if maison and (chemin == maison or chemin.startswith(maison + os.sep)):
        chemin = "~" + chemin[len(maison) :]
    if worktree["bare"]:
        quoi = "(bare)"
    elif worktree["branch"]:
        quoi = f"[{worktree['branch']}]"
    else:
        quoi = f"({(worktree['head'] or '')[:8]} {traduire('detached')})"
    marques = []
    if worktree.get("principal"):
        marques.append(traduire("main worktree"))
    if worktree["locked"]:
        marques.append(traduire("locked"))
    if worktree["prunable"] or not worktree.get("existe", True):
        marques.append(traduire("directory missing"))
    if modifies:
        marques.append(f"{modifies} {traduire('modified files')}")
    suite = f"  · {', '.join(marques)}" if marques else ""
    return f"{chemin}  {quoi}{suite}"


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="List the git worktrees of a checkout."
    )
    parser.add_argument(
        "--racine",
        default=os.path.normpath(
            os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "..", ".."
            )
        ),
    )
    config = parser.parse_args(argv)
    try:
        worktrees = lister(config.racine)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    for worktree in worktrees:
        modifies = (
            fichiers_modifies(worktree["path"]) if worktree["existe"] else None
        )
        print(decrire(worktree, modifies))
    return 0


if __name__ == "__main__":
    sys.exit(main())
