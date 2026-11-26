#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Geler les dépôts clonés : écrire leur commit dans LEUR fichier source.

Le gel porte sur les fichiers de la version d'Odoo active :
`git_manifest_odoo<V>.xml`, `git_manifest_odoo<V>_dev.xml` et
`git_manifest_extra_odoo<V>.xml` dans `manifest/`, puis, s'il existe, le
manifeste privé `private/manifest/git_manifest_private_odoo<V>.xml`. Il
pose le commit courant de chacun de leurs clones dans « freeze-revision »,
à côté de la branche que « revision » garde, dans le fichier qui déclare
le projet et nul autre. Les autres fichiers de la fusion sont lus sans être
écrits, et la fusion n'applique que le gel de ces fichiers et des fragments
communs : les projets des autres suivent leur branche. Le dégel retire
l'attribut de tous les fichiers.

Avec `--upstream`, chaque fork gelé dont l'amont est DÉCLARÉ reçoit aussi,
dans « fork-upstream-freeze-revision », la base de fusion de son commit gelé
avec la branche amont : le commit amont sur lequel il repose. C'est la seule
partie qui touche au réseau. Une base introuvable n'empêche jamais le gel du
commit : le fork est listé avec son motif, sa base n'est pas écrite, et une
base existante ne survit que si le commit gelé n'a pas changé. Le fetch de
l'amont range des objets dans le clone et approfondit un clone superficiel ;
il ne déplace ni branche ni référence, et ne touche pas l'arbre de travail.

Avec `--branches`, un clone extrait sur une branche autre que la
« revision » de son projet donne aussi cette branche à « revision » : la
reconfiguration suivra la branche, le gel épinglant son commit. Seule une
branche que le remote du projet porte, et qui contient le commit gelé,
s'écrit ; les autres sont listées, avec ce qui manque, et leur projet garde
sa branche. Une tête détachée ne change rien. `branches_a_publier` et
`publier_branche` servent à pousser d'abord une branche absente du distant
ou en avance sur lui, jamais de force : le gel lui-même ne pousse rien.

Le gel ne change l'état d'aucun clone : il écrit des fichiers à committer. Il prend
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
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.append(new_path)

from script.git import (  # noqa: E402
    command_echo,
    manifest_freeze,
    repo_upgrade,
)

# Les interrogations d'amont passent par le réseau : moins nombreuses en
# parallèle que les inspections locales.
PARALLELE_AMONT = 4
# Un clone superficiel s'approfondit par doublements de cette profondeur,
# jusqu'au plafond.
PROFONDEUR_DEPART = 50
PROFONDEUR_MAX = 1600


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
        help=(
            f"Remove {manifest_freeze.FREEZE_ATTR} and"
            f" {manifest_freeze.FORK_UPSTREAM_FREEZE_ATTR} from every source"
            " file."
        ),
    )
    parser.add_argument(
        "--upstream",
        action="store_true",
        help=(
            f"Also write {manifest_freeze.FORK_UPSTREAM_FREEZE_ATTR}: the"
            " merge base of each frozen fork with its declared upstream"
            " branch. Fetches every upstream over the network, and deepens a"
            f" shallow clone up to {PROFONDEUR_MAX} commits."
        ),
    )
    parser.add_argument(
        "--branches",
        action="store_true",
        help=(
            "Also write in revision the branch each clone is on, when it"
            " differs from the manifest. Only a branch that the project's"
            " remote carries and that contains the frozen commit is"
            " written; the others are listed. Pushes nothing."
        ),
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
            " git_manifest_odoo<V>_dev.xml and git_manifest_extra_odoo<V>.xml,"
            " and its private manifest"
            " private/manifest/git_manifest_private_odoo<V>.xml when it"
            " exists; a freeze accepts only those, and still reads every"
            " merged file to find duplicates. With --unfreeze: any file, by"
            " default every manifest/*.xml, every private manifest of an Odoo"
            " version and the merged files."
        ),
    )
    return parser.parse_args(argv)


def _git(path, *args):
    """Lance git dans `path`. Rend (code, sortie sans blanc final)."""
    command_echo.show(["git", "-C", path, *args])
    res = subprocess.run(
        ["git", "-C", path, *args],
        capture_output=True,
        text=True,
    )
    return res.returncode, res.stdout.strip()


def inspect_clone(path, amont=None):
    """État d'un clone : (sha, motif de refus ou None, sale).

    Le refus vaut pour un chemin qui n'est pas un clone, et pour un commit
    qu'aucune référence distante ne contient. Un arbre de travail modifié
    n'empêche pas le gel : le commit, lui, existe chez le distant ; l'appel
    le signale seulement.

    Le clone doit être la RACINE de son dépôt : un dossier non cloné sous
    le checkout ERPLibre, lui-même un dépôt git, rendrait sinon le commit
    d'ERPLibre. Les références « refs/remotes/m/ » ne comptent pas : git-repo
    les pose sur la révision du manifeste, elles ne prouvent pas que le
    distant a le commit. Celles de `amont`, le remote amont nommé d'un fork
    (« fork-upstream-remote »), non plus : elles prouvent que l'amont a le
    commit, pas que le fork, d'où git-repo le récupère, l'a.
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
    exclus = ("refs/remotes/m/",)
    if amont:
        exclus += (f"refs/remotes/{amont}/",)
    distants = [r for r in contenants.splitlines() if not r.startswith(exclus)]
    if code or not distants:
        return sha, "commit on no remote branch", False
    _, sale = _git(path, "status", "--porcelain", "--untracked-files=no")
    return sha, None, bool(sale)


# Les motifs d'`inspect_branch` qu'un push sans force règle : aucune
# branche de suivi ne la montre au distant, ou la copie distante est en
# retard. La lecture étant locale, une branche que le distant porte sans
# que le clone l'ait jamais récupérée tombe aussi dans le premier.
BRANCHE_ABSENTE = "branch not on the remote (no tracking branch)"
BRANCHE_EN_AVANCE = "branch ahead of the remote"
A_PUBLIER = (BRANCHE_ABSENTE, BRANCHE_EN_AVANCE)


def _contient(path, ref, commit="HEAD"):
    """Vrai si la référence `ref` existe et contient `commit`."""
    code, _ = _git(path, "rev-parse", "--verify", "--quiet", ref)
    if code:
        return False
    code, _ = _git(path, "merge-base", "--is-ancestor", commit, ref)
    return code == 0


def inspect_branch(path, remote, revision):
    """La branche d'un clone à écrire dans « revision » : (branche, motif).

    Une `revision` datée (« <base>_maj_<AAAAMMJJ> ») revient d'abord à sa
    base : (base, None) quand `refs/remotes/<remote>/<base>` contient HEAD
    et que le clone est détaché ou sur une copie datée de cette base. C'est
    l'état qu'une publication laisse : la copie datée poussée sur la
    branche du fork, le clone détaché sur ce commit.

    Sinon, (None, None) quand rien ne change : tête détachée, ou branche
    égale à `revision`. Sinon la branche extraite, et un motif None quand la
    branche de suivi `refs/remotes/<remote>/<branche>` contient HEAD : le
    remote du projet, d'où git-repo récupère, porte alors la branche et le
    commit gelé. Les motifs : `BRANCHE_ABSENTE`, `BRANCHE_EN_AVANCE` (HEAD
    descend de la copie distante), « branch diverged from the remote »,
    « revision pinned to a commit » (une révision commit ne se remplace pas
    par une branche) et « no remote ». La lecture reste locale : la branche
    de suivi vaut ce que le dernier fetch ou push en a appris.

    Comme pour `inspect_clone`, le chemin doit être la RACINE de son dépôt :
    un dossier non cloné sous le checkout ERPLibre rendrait sinon la branche
    d'ERPLibre. Un chemin qui n'en est pas une rend (None, None).
    """
    if not path or not os.path.isdir(path):
        return None, None
    code, racine = _git(path, "rev-parse", "--show-toplevel")
    if code or os.path.realpath(racine) != os.path.realpath(path):
        return None, None
    # Le nom complet, et non « --short » : une étiquette homonyme ferait
    # rendre « heads/<branche> ».
    code, ref = _git(path, "symbolic-ref", "--quiet", "HEAD")
    branche = (
        ref[len("refs/heads/") :]
        if not code and ref.startswith("refs/heads/")
        else None
    )
    base = manifest_freeze.base_branch(revision)
    if (
        base != revision
        and remote
        and (branche is None or manifest_freeze.base_branch(branche) == base)
        and _contient(path, f"refs/remotes/{remote}/{base}")
    ):
        return base, None
    if not branche or branche == revision:
        return None, None
    if manifest_freeze.is_sha(revision):
        return branche, "revision pinned to a commit"
    if not remote:
        return branche, "no remote"
    suivi = f"refs/remotes/{remote}/{branche}"
    code, _ = _git(path, "rev-parse", "--verify", "--quiet", suivi)
    if code:
        return branche, BRANCHE_ABSENTE
    if _contient(path, suivi):
        return branche, None
    code, _ = _git(path, "merge-base", "--is-ancestor", suivi, "HEAD")
    if code == 0:
        return branche, BRANCHE_EN_AVANCE
    return branche, "branch diverged from the remote"


def read_default(sources):
    """{« remote », « revision »} du `<default>` de la fusion.

    Comme dans la fusion, le dernier fichier qui en porte un l'emporte ;
    un projet sans « remote » ni « revision » prend les siens. Un fichier
    vide ou illisible n'apporte pas de `<default>`.
    """
    defaut = {"remote": None, "revision": None}
    for fichier in sources:
        try:
            e = ET.parse(fichier).getroot().find("default")
        except (ET.ParseError, OSError):
            continue
        if e is not None:
            for attr in defaut:
                defaut[attr] = e.get(attr) or defaut[attr]
    return defaut


def plan_branches(
    definitions, defaut=None, inspect=inspect_branch, workers=8, ecrits=None
):
    """Calcule les branches à écrire. Rend ({clé: branche}, écartées).

    `écartées` est une liste de dicts « cle », « chemin », « remote »,
    « branche », « revision » (celle du manifeste) et « motif » : une
    branche que `inspect` ne retient pas. `ecrits` borne les fichiers comme
    dans `plan_freeze`, et un projet défini dans plusieurs fichiers est
    ignoré, `plan_freeze` le refusant déjà. `defaut` vient de
    `read_default`.
    """
    defaut = defaut or {}
    candidats = {}
    for cle, defs in definitions.items():
        if ecrits is not None and not any(f in ecrits for f, _ in defs):
            continue
        if len(defs) != 1:
            continue
        attrs = defs[0][1]
        candidats[cle] = (
            attrs.get("path"),
            attrs.get("remote") or defaut.get("remote"),
            attrs.get("revision") or defaut.get("revision"),
        )
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        etats = dict(
            zip(
                candidats,
                pool.map(lambda c: inspect(*candidats[c]), candidats),
            )
        )
    branches = {}
    ecartees = []
    for cle, (chemin, remote, revision) in candidats.items():
        branche, motif = etats[cle]
        if not branche:
            continue
        if motif:
            ecartees.append(
                {
                    "cle": cle,
                    "chemin": chemin,
                    "remote": remote,
                    "branche": branche,
                    "revision": revision,
                    "motif": motif,
                }
            )
            continue
        branches[cle] = branche
    return branches, ecartees


def branches_a_publier(odoo_version=None):
    """Les branches qu'un push sans force rendrait gelables.

    Les écartées de `plan_branches` dont le motif est dans `A_PUBLIER`,
    pour les fichiers que le gel écrit, triées par chemin. Les chemins sont
    relatifs à la racine du dépôt, où le répertoire courant doit se
    trouver.
    """
    portee = freeze_sources(odoo_version)
    lus = list(dict.fromkeys(default_sources() + portee))
    _, ecartees = plan_branches(
        read_sources(lus), read_default(lus), ecrits=portee
    )
    return sorted(
        (e for e in ecartees if e["motif"] in A_PUBLIER),
        key=lambda e: e["chemin"],
    )


def publier_branche(path, remote, branche):
    """Pousse la branche locale `branche` sur la branche homonyme du remote.

    Jamais de force : git refuse quand le distant porte des commits que la
    branche locale n'a pas. Passe par `repo_upgrade.git`, comme la
    publication des forks : délai borné, aucune invite d'identifiants, et
    une erreur rendue plutôt que levée. Rend (code, message d'erreur).
    """
    ref = f"refs/heads/{branche}"
    _out, err, code = repo_upgrade.git(["push", remote, f"{ref}:{ref}"], path)
    return code, err.strip()


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
    """Les fichiers sources que la fusion lit, dans le même ordre, chemins
    normalisés : un CSV qui écrit « ./private/… » nomme le même fichier que
    `freeze_sources`, et ne le fait pas lire deux fois."""
    from script.git.git_merge_repo_manifest import default_input_paths

    chemins = [
        os.path.normpath(p)
        for p in default_input_paths()
        if p.endswith(".xml")
    ]
    return list(dict.fromkeys(chemins))


# Le dossier des manifestes privés, et le nom de celui d'une version
# d'Odoo : ses dépôts ne figurent dans aucun fichier de manifest/, il est le
# seul fichier où les geler.
PRIVATE_MANIFEST_DIR = os.path.join("private", "manifest")
PRIVATE_MANIFEST = "git_manifest_private_odoo{version}.xml"


def active_version(racine=""):
    """La version d'Odoo active (« 18.0 »), première ligne de
    `.odoo-version` sous `racine` (le dossier courant par défaut) ; "" sans
    fichier lisible."""
    try:
        with open(os.path.join(racine, ".odoo-version")) as fh:
            return fh.readline().strip()
    except OSError:
        return ""


def private_source(odoo_version=None, racine=""):
    """Le manifeste privé de `odoo_version`, relatif à `racine`, ou None.

    `private/manifest/git_manifest_private_odoo<V>.xml`, quand il existe
    sous `racine` (le dossier courant par défaut). `odoo_version` vient par
    défaut de `.odoo-version` ; sans version, None.
    """
    if odoo_version is None:
        odoo_version = active_version(racine)
    if not odoo_version:
        return None
    chemin = os.path.join(
        PRIVATE_MANIFEST_DIR, PRIVATE_MANIFEST.format(version=odoo_version)
    )
    return chemin if os.path.isfile(os.path.join(racine, chemin)) else None


def freeze_sources(odoo_version=None):
    """Les fichiers que le gel écrit : ceux de la version d'Odoo active.

    `git_manifest_odoo<V>.xml`, `git_manifest_odoo<V>_dev.xml` et
    `git_manifest_extra_odoo<V>.xml` de `manifest/`, puis le manifeste privé
    de la version (`private_source`) : l'ordre de la fusion, qui lit les
    manifestes privés en dernier. Seuls ceux qui existent sont rendus.
    `odoo_version` (« 18.0 ») vient par défaut de `.odoo-version` ; sans
    version, la liste est vide. Les fragments communs, les autres versions
    installées et leurs manifestes privés n'en font pas partie.
    """
    if odoo_version is None:
        odoo_version = active_version()
    if not odoo_version:
        return []
    noms = (
        f"git_manifest_odoo{odoo_version}.xml",
        f"git_manifest_odoo{odoo_version}_dev.xml",
        f"git_manifest_extra_odoo{odoo_version}.xml",
    )
    chemins = [os.path.join("manifest", nom) for nom in noms]
    chemins = [c for c in chemins if os.path.isfile(c)]
    prive = private_source(odoo_version)
    return chemins + [prive] if prive else chemins


# Le nom d'un manifeste propre à une version d'Odoo : le principal, son
# fragment _dev et ses modules extra.
_VERSION_MANIFEST = re.compile(
    r"git_manifest_(extra_)?odoo\d+\.\d+(_dev)?\.xml"
)


def common_sources(racine=""):
    """Les fragments communs dont la fusion applique les freeze-revision :
    ceux que listent les CSV de conf/, sans aucun manifeste propre à une
    version. Chemins relatifs à `racine`, le dossier courant par défaut."""
    from script.git.git_merge_repo_manifest import common_input_paths

    return [
        chemin
        for chemin in common_input_paths(racine)
        if not _VERSION_MANIFEST.fullmatch(os.path.basename(chemin))
    ]


def honored_sources(odoo_version=None):
    """Les fichiers dont la fusion applique les freeze-revision.

    Ceux que le gel écrit (`freeze_sources`), manifeste privé de la
    version active compris, puis les fragments communs à toutes les
    versions d'Odoo, ceux que listent les CSV de conf/ : un projet commun,
    image_db ou un outil, n'a pas d'autre fichier où être gelé, et son
    commit vaut pour chaque version. Le gel d'une autre version installée,
    manifeste privé compris, et celui de tout autre fichier privé restent
    ignorés.
    """
    return list(dict.fromkeys(freeze_sources(odoo_version) + common_sources()))


def unfreeze_sources():
    """Tous les fichiers où un gel a pu être écrit.

    Plus large que `default_sources` : un fichier gelé quand les modules
    extra étaient actifs, ou le manifeste privé d'une version qui ne l'est
    plus, doit pouvoir être dégelé après coup.
    """
    prives = glob.glob(
        os.path.join(
            PRIVATE_MANIFEST_DIR, PRIVATE_MANIFEST.format(version="*")
        )
    )
    return list(
        dict.fromkeys(
            sorted(glob.glob("manifest/*.xml"))
            + sorted(prives)
            + default_sources()
        )
    )


def plan_freeze(definitions, inspect=inspect_clone, workers=8, ecrits=None):
    """Calcule le gel. Rend ({fichier: {clé: sha}}, refus, sales).

    `refus` est une liste de (clé, motif), `sales` une liste de clés.
    `ecrits`, quand il est donné, borne les fichiers à écrire : un projet
    qu'aucun d'eux ne définit est ignoré sans être listé, et un projet
    qu'ils définissent et qu'un autre fichier redéfinit est refusé.
    `inspect` reçoit le chemin du clone et le remote amont nommé du projet
    (« fork-upstream-remote »), ou None.
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
        amont = attrs.get("fork-upstream-remote")
        if amont == attrs.get("remote"):
            amont = None
        candidats[cle] = (fichier, attrs.get("path"), amont)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        etats = dict(
            zip(
                candidats,
                pool.map(lambda c: inspect(*candidats[c][1:]), candidats),
            )
        )
    for cle, (fichier, _, _) in candidats.items():
        sha, motif, sale = etats[cle]
        if motif:
            refus.append((cle, motif))
            continue
        if sale:
            sales.append(cle)
        par_fichier.setdefault(fichier, {})[cle] = sha
    return par_fichier, refus, sales


# Une surcouche de forge (script/git/forge_manifest.py) redirige des
# remotes vers une forge qui ne porte que les dépôts qu'on y a poussés, pas
# les amonts des forks : la base amont se calcule sans elle.
FORGE_OVERLAY = re.compile(r"(?:^|/)git_manifest_forge_[^/]+\.xml$")


def sans_surcouches(sources):
    """`sources` sans les surcouches de forge."""
    return [
        s for s in sources if not FORGE_OVERLAY.search(s.replace(os.sep, "/"))
    ]


def read_remotes(sources):
    """{nom: fetch} des `<remote>` de tous les fichiers.

    Un fork peut nommer un remote amont déclaré dans un autre fichier que
    le sien : la table couvre donc tout l'ensemble fusionné. Comme dans la
    fusion, le dernier fichier qui définit un remote l'emporte.
    """
    remotes = {}
    for fichier in sources:
        try:
            racine = ET.parse(fichier).getroot()
        except (ET.ParseError, OSError):
            continue
        for e in racine.findall("remote"):
            remotes[e.get("name")] = e.get("fetch")
    return remotes


def _bases(chemin, sha, cible="FETCH_HEAD"):
    """Les bases de fusion de `sha` et de `cible` (FETCH_HEAD par défaut),
    triées ; [] si aucune."""
    out, _err, code = repo_upgrade.git(
        ["merge-base", "--all", sha, cible], chemin
    )
    return sorted(out.split()) if code == 0 else []


def _compter(chemin, intervalle):
    """Le nombre de commits de `intervalle` (« a..b »), ou None."""
    out, _err, code = repo_upgrade.git(
        ["rev-list", "--count", intervalle], chemin
    )
    return int(out) if code == 0 and out.strip().isdigit() else None


def _url_fork(chemin, remote):
    """L'URL du remote `remote` du clone, ou de son seul remote ; ou None."""
    if not remote:
        out, _err, code = repo_upgrade.git(["remote"], chemin)
        noms = out.split()
        if code or len(noms) != 1:
            return None
        remote = noms[0]
    out, _err, code = repo_upgrade.git(["remote", "get-url", remote], chemin)
    return out.strip() if code == 0 and out.strip() else None


def _frontieres(chemin):
    """Les commits frontière d'un clone superficiel, ou None si illisible.

    Ce sont les lignes du fichier que « rev-parse --git-path shallow »
    désigne, chemin relatif au clone. Un clone approfondi jusqu'à sa racine
    n'a plus ce fichier : l'ensemble est alors vide.
    """
    out, _err, code = repo_upgrade.git(
        ["rev-parse", "--git-path", "shallow"], chemin
    )
    if code or not out.strip():
        return None
    fichier = os.path.join(chemin, out.strip())
    try:
        with open(fichier) as fh:
            return set(fh.read().split())
    except FileNotFoundError:
        return set()
    except OSError:
        return None


def _bases_sures(chemin, sha, bases, cible="FETCH_HEAD"):
    """Vrai si aucune frontière ne peut cacher une meilleure base.

    Une frontière coupe les parents d'un commit : derrière elle, sur la
    ligne principale amont, peut se trouver la vraie base, alors qu'un
    commit commun plus ancien reste joignable par le second parent d'une
    fusion. Les bases sont sûres quand aucun commit frontière n'est
    joignable depuis `sha` ou `cible` (FETCH_HEAD par défaut) sans passer
    par elles, soit absent de « rev-list sha cible ^base… ». Sur un clone
    complet, l'ensemble des frontières est vide et la condition tient
    d'office.
    """
    frontieres = _frontieres(chemin)
    if frontieres is None:
        return False
    if not frontieres:
        return True
    out, _err, code = repo_upgrade.git(
        ["rev-list", sha, cible] + [f"^{b}" for b in bases], chemin
    )
    if code:
        return False
    return not frontieres.intersection(out.split())


def _bases_superficiel(chemin, sha, amont, remote, ref, constat):
    """Approfondit un clone superficiel jusqu'à une base. Rend les bases.

    À chaque tour, le côté fork s'approfondit le long de `ref` depuis
    l'URL de son remote (« --deepen », qui n'ajoute que de l'historique),
    puis l'amont arrive dans FETCH_HEAD à la même profondeur
    (« --depth »). La profondeur double de PROFONDEUR_DEPART à
    PROFONDEUR_MAX et s'arrête à la première base qu'aucune frontière ne
    peut fausser (`_bases_sures`). Le fetch par
    URL ne déplace ni branche ni référence distante : seul l'historique
    présent, et donc « .git/shallow », change. Un refus est écrit dans
    `constat` ; « profondeur » y reçoit celle du dernier tour.
    """
    url_fork = _url_fork(chemin, remote)
    if not url_fork:
        constat["motif"] = "fork unreachable"
        return []
    faite = 0
    profondeur = PROFONDEUR_DEPART
    while profondeur <= PROFONDEUR_MAX:
        _out, _err, code = repo_upgrade.git(
            [
                "fetch",
                "--quiet",
                f"--deepen={profondeur - faite}",
                url_fork,
                ref,
            ],
            chemin,
        )
        if code:
            constat["motif"] = "fork unreachable"
            return []
        faite = profondeur
        if not repo_upgrade.recuperer_amont(
            chemin, amont["url"], amont["branche"], profondeur=profondeur
        ):
            constat["motif"] = "upstream unreachable"
            return []
        constat["profondeur"] = profondeur
        bases = _bases(chemin, sha)
        if bases and _bases_sures(chemin, sha, bases):
            return bases
        profondeur *= 2
    constat["motif"] = f"shallow: no base within {PROFONDEUR_MAX}"
    return []


def base_amont(chemin, sha, amont, remote=None, ref=None):
    """La base amont du commit gelé `sha` d'un clone. Rend un constat.

    Le constat est un dict : « base » (commit, ou None), « motif » du refus
    (ou None), « nous » et « retard » (commits du fork depuis la base,
    commits amont absents de `sha`), « profondeur » (None pour un clone
    complet). `amont` vient de `repo_upgrade.resoudre_amont` ; seul un
    amont DÉCLARÉ est interrogé, une URL devinée pouvant viser un autre
    dépôt. `remote` et `ref` nomment le remote du fork et ce qu'il en suit,
    pour approfondir un clone superficiel.

    La branche amont arrive dans FETCH_HEAD et la base se calcule dans le
    même appel : le FETCH_HEAD qu'un « repo sync » laisse pointe le fork.
    """
    constat = {
        "base": None,
        "motif": None,
        "nous": None,
        "retard": None,
        "profondeur": None,
    }
    if (
        not amont
        or amont["source"] != "declare"
        or not amont["remote_declare"]
        or not amont["url"]
    ):
        constat["motif"] = "upstream not declared"
        return constat
    if not amont["branche"]:
        constat["motif"] = "no upstream branch"
        return constat
    if repo_upgrade.est_superficiel(chemin):
        bases = _bases_superficiel(
            chemin, sha, amont, remote, ref or sha, constat
        )
        if constat["motif"]:
            return constat
    elif repo_upgrade.recuperer_amont(chemin, amont["url"], amont["branche"]):
        bases = _bases(chemin, sha)
    else:
        constat["motif"] = "upstream unreachable"
        return constat
    if not bases:
        constat["motif"] = "no merge base"
    elif len(bases) > 1:
        constat["motif"] = "ambiguous merge base"
    else:
        constat["base"] = bases[0]
        constat["nous"] = _compter(chemin, f"{bases[0]}..{sha}")
        constat["retard"] = _compter(chemin, f"{sha}..FETCH_HEAD")
    return constat


def plan_upstream(
    definitions,
    par_fichier,
    remotes,
    calculer=base_amont,
    workers=PARALLELE_AMONT,
    revisions=None,
):
    """Calcule la base amont des forks gelés. Rend ({clé: base}, constats).

    `par_fichier` est le plan de `plan_freeze`. `constats` associe chaque
    fork gelé au constat de `calculer`, complété de son « chemin » et de
    son « sha » gelé ; un projet qui n'est pas un fork n'y figure pas. Les
    forks s'interrogent en parallèle, `workers` à la fois. `revisions`
    associe une clé à la branche que le gel écrit : un clone superficiel
    s'approfondit le long de celle-là, qui contient le commit gelé, plutôt
    que de l'ancienne.
    """
    revisions = revisions or {}
    forks = {}
    for geles in par_fichier.values():
        for cle, sha in geles.items():
            attrs = definitions[cle][0][1]
            amont = repo_upgrade.resoudre_amont(attrs, remotes)
            if amont is not None:
                forks[cle] = (attrs, sha, amont)

    def interroger(cle):
        attrs, sha, amont = forks[cle]
        ref = revisions.get(cle) or manifest_freeze.manifest_branch(
            attrs.get("revision"),
            attrs.get("upstream"),
            attrs.get("dest-branch"),
        )
        constat = calculer(
            attrs.get("path"),
            sha,
            amont,
            remote=attrs.get("remote"),
            ref=ref or sha,
        )
        return dict(constat, chemin=attrs.get("path"), sha=sha)

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        constats = dict(zip(forks, pool.map(interroger, forks)))
    bases = {c: k["base"] for c, k in constats.items() if k["base"]}
    return bases, constats


def print_upstream(constats):
    """Affiche la provenance de chaque fork gelé, puis ceux sans base."""
    trouves = sorted(
        (k for k in constats.values() if k["base"]),
        key=lambda k: k["chemin"] or "",
    )
    for k in trouves:
        ligne = (
            f"  {k['chemin']}: {k['sha'][:12]} = upstream"
            f" {k['base'][:12]} +{k['nous']} ours"
        )
        if k["retard"] is not None:
            ligne += f", {k['retard']} behind upstream"
        if k["profondeur"]:
            ligne += f" (shallow, deepened to {k['profondeur']})"
        print(ligne)
    sans = sorted((c, k["motif"]) for c, k in constats.items() if k["motif"])
    print(
        f"Upstream: {len(trouves)} bases found, {len(sans)} forks without"
        " base."
    )
    if sans:
        print(f"WARNING: no upstream base: {len(sans)}")
        for cle, motif in sans:
            print(f"  - {cle}: {motif}")


def print_branches(definitions, revisions, ecartees, dry_run=False):
    """Affiche chaque branche écrite, ancienne → nouvelle, puis les
    écartées avec leur motif ; celles qu'un push règle disent comment.
    `dry_run` annonce ce qui s'écrirait plutôt que ce qui s'est écrit."""
    for cle in sorted(revisions, key=lambda c: definitions[c][0][1]["path"]):
        attrs = definitions[cle][0][1]
        ancienne = attrs.get("revision") or "(default)"
        print(f"  {attrs['path']}: {ancienne} → {revisions[cle]}")
    ecrit = "would be written" if dry_run else "written"
    print(
        f"Branches: {len(revisions)} {ecrit}, {len(ecartees)} left on their"
        " manifest branch."
    )
    if ecartees:
        print(f"WARNING: branch not written: {len(ecartees)}")
        for e in sorted(ecartees, key=lambda e: e["chemin"]):
            ligne = f"  - {e['chemin']}: {e['branche']}: {e['motif']}"
            if e["motif"] in A_PUBLIER:
                ligne += (
                    f"; push it to {e['remote']} (or fetch it if the remote"
                    " already has it), then freeze again"
                )
            print(ligne)


def write_sources(
    par_fichier,
    unfreeze=False,
    dry_run=False,
    sources=(),
    upstream=None,
    revisions=None,
):
    """Réécrit les fichiers. Rend {fichier: clés changées}.

    `upstream` associe une clé à sa base amont, `revisions` à la branche à
    poser dans « revision », comme `rewrite` l'entend ; seule une clé gelée
    dans le fichier les reçoit.
    """
    fichiers = list(sources) if unfreeze else list(par_fichier)
    upstream = upstream or {}
    revisions = revisions or {}
    changes = {}
    for fichier in fichiers:
        with open(fichier) as fh:
            texte = fh.read()
        geles = par_fichier.get(fichier) or {}
        neuf, cles = manifest_freeze.rewrite(
            texte,
            freeze=geles,
            unfreeze=unfreeze,
            upstream={c: b for c, b in upstream.items() if c in geles},
            revisions={c: b for c, b in revisions.items() if c in geles},
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
    defaut = read_default(lus)
    branches, ecartees = plan_branches(definitions, defaut, ecrits=ecrits)
    if not config.branches:
        # Sans --branches, seule une révision datée revient à sa base :
        # elle n'existe que par un gel des branches, que la publication de
        # la copie datée sur la branche du fork a rendu caduc.
        branches = {
            c: b
            for c, b in branches.items()
            if b
            == manifest_freeze.base_branch(
                definitions[c][0][1].get("revision") or defaut.get("revision")
            )
        }
        ecartees = []
    # Une branche ne s'écrit qu'à côté de son commit gelé.
    geles_cles = {c for g in par_fichier.values() for c in g}
    revisions = {c: b for c, b in branches.items() if c in geles_cles}
    bases, constats = {}, None
    if config.upstream:
        bases, constats = plan_upstream(
            definitions,
            par_fichier,
            read_remotes(sans_surcouches(lus)),
            revisions=revisions,
        )
    changes = write_sources(
        par_fichier,
        dry_run=config.dry_run,
        upstream=bases,
        revisions=revisions,
    )

    geles = sum(len(c) for c in par_fichier.values())
    for fichier, cles in changes.items():
        print(f"{fichier}: {len(cles)} projects {verbe}")
    print(
        f"Freeze: {geles} projects pinned,"
        f" {sum(len(c) for c in changes.values())} {verbe},"
        f" {len(refus)} skipped."
    )
    if constats is not None:
        print_upstream(constats)
    if config.branches or revisions:
        print_branches(definitions, revisions, ecartees, config.dry_run)
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
