#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Geler les dépôts clonés : écrire leur commit dans LEUR fichier source.

Le gel porte sur les fichiers de la version d'Odoo active :
`git_manifest_odoo<V>.xml`, `git_manifest_odoo<V>_dev.xml` et
`git_manifest_extra_odoo<V>.xml`. Il pose le commit courant de chacun de
leurs clones dans « freeze-revision », à côté de la branche que « revision »
garde. Les autres fichiers de la fusion sont lus sans être écrits, et la
fusion n'applique que le gel de ces trois fichiers : les projets des autres
suivent leur branche. Le dégel retire l'attribut de tous les fichiers.

Le gel n'agit sur aucun clone : il écrit des fichiers à committer. Il prend
effet à la reconfiguration suivante, lancée avec `--freeze`
(`make repo_configure_all FREEZE=1`) ; sans cet argument, la reconfiguration
suit les branches.

Ne sont pas gelés, et sont listés : un projet non cloné, un projet qu'un
autre fichier fusionné définit aussi (la fusion garde l'une des définitions
selon l'ordre des fichiers, et le gel n'en écrit qu'une), et un clone dont
le commit n'est contenu dans aucune branche distante, car une installation
neuve ne pourrait pas aller le chercher.
"""

import argparse
import concurrent.futures
import glob
import os
import subprocess
import sys

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.append(new_path)

from script.git import manifest_freeze  # noqa: E402


def get_config(argv=None):
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__.split("\n\n")[0],
        epilog=(
            "Apply with: make repo_configure_all FREEZE=1\n"
            "Follow the branches again with: make repo_configure_all"
        ),
    )
    parser.add_argument(
        "--unfreeze",
        action="store_true",
        help=f"Remove {manifest_freeze.FREEZE_ATTR} from every source file.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change, write nothing.",
    )
    parser.add_argument(
        "--source",
        action="append",
        help=(
            "Source manifest file to write, repeatable. Default: the"
            " manifests of the active Odoo version, git_manifest_odoo<V>.xml,"
            " git_manifest_odoo<V>_dev.xml and git_manifest_extra_odoo<V>.xml;"
            " a freeze accepts only those, and still reads every merged file"
            " to find duplicates. With --unfreeze: any file, by default every"
            " manifest/*.xml and the merged files."
        ),
    )
    return parser.parse_args(argv)


def _git(path, *args):
    """Lance git dans `path`. Rend (code, sortie sans blanc final)."""
    res = subprocess.run(
        ["git", "-C", path, *args],
        capture_output=True,
        text=True,
    )
    return res.returncode, res.stdout.strip()


def inspect_clone(path):
    """État d'un clone : (sha, motif de refus ou None, sale).

    Le refus vaut pour un chemin qui n'est pas un clone, et pour un commit
    qu'aucune référence distante ne contient. Un arbre de travail modifié
    n'empêche pas le gel : le commit, lui, existe chez le distant ; l'appel
    le signale seulement.

    Le clone doit être la RACINE de son dépôt : un dossier non cloné sous
    le checkout ERPLibre, lui-même un dépôt git, rendrait sinon le commit
    d'ERPLibre. Les références « refs/remotes/m/ » ne comptent pas : git-repo
    les pose sur la révision du manifeste, elles ne prouvent pas que le
    distant a le commit.
    """
    if not path or not os.path.isdir(path):
        return None, "not cloned", False
    code, racine = _git(path, "rev-parse", "--show-toplevel")
    if code or os.path.realpath(racine) != os.path.realpath(path):
        return None, "not a git clone", False
    code, sha = _git(path, "rev-parse", "--verify", "HEAD")
    if code or not manifest_freeze.is_sha(sha):
        return None, "not a git clone", False
    code, contenants = _git(
        path,
        "for-each-ref",
        "--contains",
        "HEAD",
        "--format=%(refname)",
        "refs/remotes",
    )
    distants = [
        r
        for r in contenants.splitlines()
        if not r.startswith("refs/remotes/m/")
    ]
    if code or not distants:
        return sha, "commit on no remote branch", False
    _, sale = _git(path, "status", "--porcelain", "--untracked-files=no")
    return sha, None, bool(sale)


def read_sources(sources):
    """{clé: [(fichier, attributs)]} pour les projets de chaque fichier."""
    definitions = {}
    for fichier in sources:
        with open(fichier) as fh:
            texte = fh.read()
        for _, _, attrs in manifest_freeze.iter_projects(texte):
            cle = manifest_freeze.project_key(
                attrs.get("name"), attrs.get("path")
            )
            definitions.setdefault(cle, []).append((fichier, attrs))
    return definitions


def default_sources():
    """Les fichiers sources que la fusion lit, dans le même ordre."""
    from script.git.git_merge_repo_manifest import default_input_paths

    return [p for p in default_input_paths() if p.endswith(".xml")]


def freeze_sources(odoo_version=None):
    """Les fichiers que le gel écrit : ceux de la version d'Odoo active.

    `git_manifest_odoo<V>.xml`, `git_manifest_odoo<V>_dev.xml` et
    `git_manifest_extra_odoo<V>.xml`, dans l'ordre de la fusion, ceux qui
    existent. `odoo_version` (« 18.0 ») vient par défaut de `.odoo-version` ;
    sans version, la liste est vide. Les fragments communs, les autres
    versions installées et les manifestes privés n'en font pas partie.
    """
    if odoo_version is None:
        try:
            with open(".odoo-version") as fh:
                odoo_version = fh.readline().strip()
        except OSError:
            odoo_version = ""
    if not odoo_version:
        return []
    noms = (
        f"git_manifest_odoo{odoo_version}.xml",
        f"git_manifest_odoo{odoo_version}_dev.xml",
        f"git_manifest_extra_odoo{odoo_version}.xml",
    )
    chemins = [os.path.join("manifest", nom) for nom in noms]
    return [c for c in chemins if os.path.isfile(c)]


def unfreeze_sources():
    """Tous les fichiers où un gel a pu être écrit.

    Plus large que `default_sources` : un fichier gelé quand les modules
    extra étaient actifs doit pouvoir être dégelé après leur retrait.
    """
    return list(
        dict.fromkeys(sorted(glob.glob("manifest/*.xml")) + default_sources())
    )


def plan_freeze(definitions, inspect=inspect_clone, workers=8, ecrits=None):
    """Calcule le gel. Rend ({fichier: {clé: sha}}, refus, sales).

    `refus` est une liste de (clé, motif), `sales` une liste de clés.
    `ecrits`, quand il est donné, borne les fichiers à écrire : un projet
    qu'aucun d'eux ne définit est ignoré sans être listé, et un projet
    qu'ils définissent et qu'un autre fichier redéfinit est refusé.
    """
    par_fichier = {}
    refus = []
    sales = []
    candidats = {}
    for cle, defs in definitions.items():
        if ecrits is not None and not any(f in ecrits for f, _ in defs):
            continue
        if len(defs) > 1:
            fichiers = ", ".join(f for f, _ in defs)
            refus.append((cle, f"defined in several sources: {fichiers}"))
            continue
        fichier, attrs = defs[0]
        candidats[cle] = (fichier, attrs.get("path"))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        etats = dict(
            zip(
                candidats,
                pool.map(lambda c: inspect(candidats[c][1]), candidats),
            )
        )
    for cle, (fichier, _) in candidats.items():
        sha, motif, sale = etats[cle]
        if motif:
            refus.append((cle, motif))
            continue
        if sale:
            sales.append(cle)
        par_fichier.setdefault(fichier, {})[cle] = sha
    return par_fichier, refus, sales


def write_sources(par_fichier, unfreeze=False, dry_run=False, sources=()):
    """Réécrit les fichiers. Rend {fichier: clés changées}."""
    fichiers = list(sources) if unfreeze else list(par_fichier)
    changes = {}
    for fichier in fichiers:
        with open(fichier) as fh:
            texte = fh.read()
        neuf, cles = manifest_freeze.rewrite(
            texte,
            freeze=par_fichier.get(fichier),
            unfreeze=unfreeze,
        )
        if not cles:
            continue
        changes[fichier] = cles
        if not dry_run:
            with open(fichier, "w") as fh:
                fh.write(neuf)
    return changes


def main(argv=None):
    config = get_config(argv)
    # Les chemins des projets sont relatifs à la racine du dépôt, où le
    # répertoire courant passe ; un `--source` donné depuis ailleurs est
    # d'abord ramené à cette racine.
    if config.source:
        config.source = [
            os.path.relpath(os.path.abspath(s), new_path)
            for s in config.source
        ]
    os.chdir(new_path)
    verbe = "would change" if config.dry_run else "changed"

    if config.unfreeze:
        sources = config.source or unfreeze_sources()
        changes = write_sources(
            {}, unfreeze=True, dry_run=config.dry_run, sources=sources
        )
        total = sum(len(c) for c in changes.values())
        for fichier, cles in changes.items():
            print(f"{fichier}: {len(cles)} projects {verbe}")
        print(f"Unfreeze: {total} projects follow their branch again.")
        return 0

    portee = freeze_sources()
    if not portee:
        print(
            "ERROR: no manifest of the active Odoo version; check"
            " .odoo-version and manifest/git_manifest_odoo<V>.xml"
        )
        return 1
    ecrits = config.source or portee
    dehors = [f for f in ecrits if f not in portee]
    if dehors:
        # La fusion n'appliquerait pas un gel écrit ailleurs.
        print(
            f"ERROR: not a manifest of the active Odoo version:"
            f" {', '.join(dehors)}; accepted: {', '.join(portee)}"
        )
        return 2
    # Les autres fichiers de la fusion sont lus sans être écrits : ils
    # révèlent un projet que la fusion définit aussi ailleurs.
    lus = list(dict.fromkeys(default_sources() + portee))
    print(f"Freeze sources: {', '.join(ecrits)}")
    definitions = read_sources(lus)
    par_fichier, refus, sales = plan_freeze(definitions, ecrits=ecrits)
    changes = write_sources(par_fichier, dry_run=config.dry_run)

    geles = sum(len(c) for c in par_fichier.values())
    for fichier, cles in changes.items():
        print(f"{fichier}: {len(cles)} projects {verbe}")
    print(
        f"Freeze: {geles} projects pinned,"
        f" {sum(len(c) for c in changes.values())} {verbe},"
        f" {len(refus)} skipped."
    )
    non_clones = [c for c, m in refus if m == "not cloned"]
    autres = [(c, m) for c, m in refus if m != "not cloned"]
    if non_clones:
        print(f"Not cloned, left as is: {len(non_clones)}")
        for cle in sorted(non_clones):
            print(f"  - {cle}")
    if autres:
        print(f"WARNING: not frozen: {len(autres)}")
        for cle, motif in sorted(autres):
            print(f"  - {cle}: {motif}")
    if sales:
        print(
            f"WARNING: {len(sales)} clones have uncommitted changes; their"
            " commit is frozen, not those changes:"
        )
        for cle in sorted(sales):
            print(f"  - {cle}")
    if geles and not config.dry_run:
        print("Apply with: make repo_configure_all FREEZE=1")
    return 0 if geles else 1


if __name__ == "__main__":
    sys.exit(main())
