#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Les modules Odoo qui diffèrent dans les dépôts du checkout : ceux qu'une
mise à jour doit passer à -u.

Les dépôts examinés sont ceux qu'une comparaison de gels (`git_freeze_diff`)
voit changés ou apparus, plus, sur demande, les dépôts git de
`odoo<V>/addons/addons`, que le manifeste ne connaît pas. Chacun se compare
selon l'un de deux modes :

- la BRANCHE : son HEAD contre `<distant>/<V>`, où <V> est la version
  d'Odoo du checkout (« 18.0 ») et <distant> le « remote » que le manifeste
  donne au projet — git-repo nomme le distant du clone d'après lui. Un fork
  sans branche <V> se replie sur la branche du manifeste (« 18.0_dev »). Un
  dépôt hors manifeste prend « origin », sinon son seul distant, sinon
  celui de la branche suivie ;
- le GEL : l'ancien commit de la comparaison contre le nouveau, ce que la
  comparaison a changé — après un pull, les modules à mettre à jour. Un
  dépôt hors manifeste, qui n'a pas de gel, garde sa branche.

Aucun accès réseau : les références sont celles du dernier fetch, et un
commit absent du clone se signale plutôt que de se chercher.

Un module est un dossier qui porte un `__manifest__.py` (ou
`__openerp__.py`) dans l'un des deux arbres : un module retiré d'un côté se
compte aussi. Un fichier hors de tout module ne compte pour aucun.
"""

import argparse
import os
import sys

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.append(new_path)

from script.git import git_freeze_diff, manifest_freeze  # noqa: E402

MANIFESTES = ("__manifest__.py", "__openerp__.py")

# Les deux références possibles d'un dépôt : la branche de la version sur
# son distant, ou l'ancien commit de la comparaison de gels.
MODE_BRANCHE = "branch"
MODE_GEL = "freeze"

# Les statuts d'une comparaison qui désignent un clone dont le HEAD compte :
# un projet changé ou apparu. « same » n'a pas bougé, « gone » et « not
# cloned » n'ont pas de clone à lire.
STATUTS_RETENUS = (git_freeze_diff.STATUS_CHANGED, git_freeze_diff.STATUS_NEW)

# Les quatre comparaisons proposées, dans l'ordre du menu des gels. La
# quatrième se calcule : `previous_freeze` lit l'historique d'ERPLibre.
COMPARAISONS = {
    "1": ("HEAD", git_freeze_diff.CLONES),
    "2": (git_freeze_diff.WORKTREE, git_freeze_diff.CLONES),
    "3": ("HEAD", git_freeze_diff.WORKTREE),
}


def _git(chemin, *args):
    return git_freeze_diff._git(chemin, *args)


def _git_z(chemin, *args):
    """La sortie d'une commande git en `-z`, découpée, ou None en échec."""
    code, sortie = _git(chemin, *args)
    if code:
        return None
    return [x for x in sortie.split("\0") if x]


def dossier_addons_addons(racine, version):
    return os.path.join(racine, f"odoo{version}", "addons", "addons")


def depots_addons_addons(racine, version):
    """Les dépôts git de `odoo<V>/addons/addons` : le dossier lui-même s'il
    en est un, et chacun de ses sous-dossiers directs qui en est un. Un
    `.git` fichier (worktree, sous-module) compte comme un dossier."""
    base = dossier_addons_addons(racine, version)
    if not os.path.isdir(base):
        return []
    trouves = []
    if os.path.exists(os.path.join(base, ".git")):
        trouves.append(base)
    for nom in sorted(os.listdir(base)):
        sous = os.path.join(base, nom)
        if os.path.isdir(sous) and os.path.exists(os.path.join(sous, ".git")):
            trouves.append(sous)
    return [d for d in trouves if git_freeze_diff.is_clone(d)]


def distant_par_defaut(chemin):
    """Le distant d'un dépôt hors manifeste : « origin », sinon le seul
    distant, sinon celui de la branche suivie ; None si rien ne tranche."""
    code, sortie = _git(chemin, "remote")
    distants = sortie.split() if not code else []
    if "origin" in distants:
        return "origin"
    if len(distants) == 1:
        return distants[0]
    code, suivie = _git(
        chemin, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"
    )
    if not code and "/" in suivie:
        distant = suivie.split("/", 1)[0]
        if distant in distants:
            return distant
    return None


def reference(chemin, version, distant, branche=None):
    """(ref, cherchées) : la première branche DISTANTE que le clone connaît,
    `<distant>/<version>` puis `<distant>/<branche>`, la branche que le
    manifeste donne au projet, quand elle est autre ; ref vaut None si
    aucune n'existe, et cherchées nomme ce qui a été essayé.

    Une branche locale du même nom ne compte pas : elle peut porter le
    travail même qu'on cherche à mesurer.
    """
    if not distant:
        return None, []
    noms = [version]
    if branche and branche != version and not manifest_freeze.is_sha(branche):
        noms.append(branche)
    cherchees = []
    for nom in noms:
        ref = f"refs/remotes/{distant}/{nom}"
        cherchees.append(f"{distant}/{nom}")
        code, _ = _git(chemin, "rev-parse", "--verify", "--quiet", ref)
        if not code:
            return ref, cherchees
    return None, cherchees


def dossiers_modules(chemin, *revisions):
    """Les dossiers de module (relatifs au dépôt, « » pour un dépôt qui est
    lui-même un module) des arbres de `revisions`, réunis."""
    dossiers = set()
    for rev in revisions:
        fichiers = _git_z(chemin, "ls-tree", "-r", "-z", "--name-only", rev)
        for f in fichiers or []:
            if os.path.basename(f) in MANIFESTES:
                dossiers.add(os.path.dirname(f))
    return dossiers


def module_de(fichier, dossiers):
    """Le dossier de module le plus profond qui contient `fichier`, ou
    None hors de tout module."""
    parent = os.path.dirname(fichier)
    while True:
        if parent in dossiers:
            return parent
        if not parent:
            return None
        parent = os.path.dirname(parent)


def modules_differents(chemin, ancien, neuf="HEAD"):
    """Les noms des modules dont un fichier diffère entre deux révisions.

    Rend None quand git échoue. Sans détection de renommage : un fichier
    déplacé d'un module à l'autre compte pour les deux.
    """
    fichiers = _git_z(
        chemin, "diff", "--name-only", "-z", "--no-renames", ancien, neuf
    )
    if fichiers is None:
        return None
    if not fichiers:
        return set()
    dossiers = dossiers_modules(chemin, ancien, neuf)
    noms = set()
    for f in fichiers:
        dossier = module_de(f, dossiers)
        if dossier is None:
            continue
        noms.add(os.path.basename(dossier or os.path.normpath(chemin)))
    return noms


def depots_du_choix(racine, gauche, droite):
    """Les projets qu'une comparaison de gels voit changés ou apparus, et
    dont le clone existe : [{path, remote, branch, old, new}], où « old » et
    « new » sont les commits des deux côtés (« old » vaut None pour un
    projet apparu) et « branch » la branche du manifeste.

    Lève ValueError sur une révision inconnue, comme `build`.
    """
    rapport = git_freeze_diff.build(racine, gauche, droite)
    depots = []
    for lg in rapport["rows"]:
        if lg["status"] not in STATUTS_RETENUS or not lg["path"]:
            continue
        if not git_freeze_diff.is_clone(os.path.join(racine, lg["path"])):
            continue
        g, d = lg["left"], lg["right"]
        depots.append(
            {
                "path": lg["path"],
                "remote": d.get("remote") or g.get("remote"),
                "branch": d.get("branch") or g.get("branch"),
                "old": lg["old"],
                "new": lg["new"],
            }
        )
    return depots


def depot_hors_manifeste(racine, chemin):
    """L'entrée d'un dépôt que le manifeste ne connaît pas : ni distant ni
    branche déclarés, ni commits de gel. Il se compare toujours à sa
    branche, quel que soit le mode."""
    return {"path": os.path.relpath(chemin, racine), "remote": None}


def _court(ref):
    return ref.removeprefix("refs/remotes/")


def analyser(racine, version, depots, mode=MODE_BRANCHE):
    """Les modules qui diffèrent, dépôt par dépôt.

    En MODE_BRANCHE, chaque dépôt compare son HEAD à `<distant>/<version>`,
    ou à défaut à `<distant>/<branche du manifeste>` (`reference`) ; un
    distant absent se devine (`distant_par_defaut`). En MODE_GEL, un dépôt
    qui porte les commits d'une comparaison (« new ») compare l'ancien au
    nouveau : ce que la comparaison a changé ; un dépôt hors manifeste garde
    sa branche.

    Rend {modules : la liste triée, sans doublon ; par_depot : {chemin :
    liste triée} ; repli : [(chemin, branche prise à défaut de la
    version)] ; sans_branche : [(chemin, branches cherchées)] ;
    sans_ancien : [chemin] d'un projet apparu ; absents : [(chemin,
    commit)] qui manque au clone ; echecs : [chemin] où git a échoué}.
    """
    resultat = {
        "modules": set(),
        "par_depot": {},
        "repli": [],
        "sans_branche": [],
        "sans_ancien": [],
        "absents": [],
        "echecs": [],
    }
    for depot in depots:
        relatif = depot["path"]
        chemin = os.path.join(racine, relatif)
        if mode == MODE_GEL and "new" in depot:
            ancien, neuf = depot["old"], depot["new"]
            if not ancien:
                resultat["sans_ancien"].append(relatif)
                continue
            manque = [
                sha
                for sha in (ancien, neuf)
                if not git_freeze_diff.has_commit(chemin, sha)
            ]
            if manque:
                resultat["absents"].append((relatif, manque[0][:8]))
                continue
        else:
            distant = depot.get("remote") or distant_par_defaut(chemin)
            ancien, cherchees = reference(
                chemin, version, distant, depot.get("branch")
            )
            neuf = "HEAD"
            if not ancien:
                resultat["sans_branche"].append(
                    (relatif, " · ".join(cherchees) or f"?/{version}")
                )
                continue
            if not ancien.endswith(f"/{version}"):
                resultat["repli"].append((relatif, _court(ancien)))
        noms = modules_differents(chemin, ancien, neuf)
        if noms is None:
            resultat["echecs"].append(relatif)
            continue
        if noms:
            resultat["par_depot"][relatif] = sorted(noms)
            resultat["modules"] |= noms
    resultat["modules"] = sorted(resultat["modules"])
    return resultat


def main():
    parser = argparse.ArgumentParser(
        description="""List the Odoo modules that differ, for the
        repositories a freeze comparison sees changed: between each HEAD and
        <remote>/<odoo version> (--mode branch), or between the two commits
        of the comparison (--mode freeze). One module per line on stdout.""",
    )
    parser.add_argument("--from", dest="gauche", default="HEAD")
    parser.add_argument("--to", dest="droite", default=git_freeze_diff.CLONES)
    parser.add_argument(
        "--mode", choices=(MODE_BRANCHE, MODE_GEL), default=MODE_BRANCHE
    )
    parser.add_argument(
        "--addons-addons",
        action="store_true",
        help="Also compare the git repositories of odoo<V>/addons/addons.",
    )
    parser.add_argument(
        "--version", help="Odoo version, .odoo-version by default."
    )
    args = parser.parse_args()
    racine = new_path
    version = args.version
    if not version:
        with open(os.path.join(racine, ".odoo-version")) as fh:
            version = fh.read().strip()
    try:
        depots = depots_du_choix(racine, args.gauche, args.droite)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    if args.addons_addons:
        depots += [
            depot_hors_manifeste(racine, d)
            for d in depots_addons_addons(racine, version)
        ]
    resultat = analyser(racine, version, depots, args.mode)
    for chemin, ref in resultat["repli"]:
        print(f"fallback {ref}: {chemin}", file=sys.stderr)
    for chemin, refs in resultat["sans_branche"]:
        print(f"no {refs}: {chemin}", file=sys.stderr)
    for chemin in resultat["sans_ancien"]:
        print(f"no old side: {chemin}", file=sys.stderr)
    for chemin, sha in resultat["absents"]:
        print(f"commit {sha} missing, fetch: {chemin}", file=sys.stderr)
    for chemin in resultat["echecs"]:
        print(f"git failed: {chemin}", file=sys.stderr)
    for module in resultat["modules"]:
        print(module)
    return 0


if __name__ == "__main__":
    sys.exit(main())
