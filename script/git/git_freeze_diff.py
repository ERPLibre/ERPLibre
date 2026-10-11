#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Comparer deux gels : ce que chaque dépôt a changé de l'un à l'autre.

Un CÔTÉ de la comparaison est l'un de trois états :

- une révision git d'ERPLibre (HEAD, un tag, un commit) : les
  « freeze-revision » des fichiers de `manifest/` qu'elle a committés ;
- « worktree » : les mêmes fichiers sur le disque, gel écrit et peut-être
  pas encore committé ;
- « clones » : le commit HEAD de chaque clone, l'état réel du checkout.

Sans argument, la comparaison va du gel committé (HEAD) aux clones : ce qui
a bougé depuis le dernier gel. Le rapport nomme aussi le HEAD d'ERPLibre, un
gel écrit mais pas committé et les clones modifiés.

Les commits se comparent DANS le clone local : avance et retard, fichiers et
lignes, regroupés par type de fichier, module ou dossier. Aucun accès réseau,
sauf `--fetch`, qui va chercher en parallèle les commits absents du clone.
"""

import argparse
import concurrent.futures
import glob
import os
import shlex
import shutil
import subprocess
import sys
import time

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.append(new_path)

from script.git import manifest_freeze  # noqa: E402

WORKTREE = "worktree"
CLONES = "clones"
MANIFEST_DIR = "manifest"
GROUPS = ("ext", "module", "dir", "none")
# Au-delà de ce nombre de fichiers changés, tous projets confondus, le
# diffstat de chaque projet est borné à AUTO_STAT_COUNT fichiers ; en deçà,
# il s'affiche en entier. `--stat-count` passe outre dans les deux sens.
AUTO_FULL_FILES = 60
AUTO_STAT_COUNT = 10
# Les listes de projets sans commit à comparer (nouveaux, retirés, non
# clonés) s'abrègent au-delà de ce nombre, sauf avec `--all`.
LIST_LIMIT = 25
# Les refs nommées par commit au-delà de ce nombre se comptent sans se nommer.
REFS_LIMIT = 10
# Le sommaire liste le clone dont le dernier fetch a plus de ces jours, car
# ses branches distantes peuvent retarder sur le serveur.
FRESH_DAYS = 7
# Les branches et tags d'ERPLibre qui portent un gel, lus au plus : les plus
# récents d'abord. Le nombre d'écartés est dit.
ERPLIBRE_REFS_LIMIT = 12

STATUS_CHANGED = "changed"
STATUS_SAME = "same"
STATUS_NEW = "new"
STATUS_GONE = "gone"
STATUS_NOT_CLONED = "not cloned"


def _git(path, *args):
    """Lance git dans `path`. Rend (code, sortie sans blanc final).

    Le blanc de TÊTE est gardé : la première ligne d'un diffstat en porte un.
    """
    res = subprocess.run(
        ["git", "-C", path, *args],
        capture_output=True,
        text=True,
    )
    return res.returncode, res.stdout.rstrip()


def _pool(jobs):
    return concurrent.futures.ThreadPoolExecutor(max_workers=max(1, jobs))


def default_jobs():
    return os.cpu_count() or 4


# Lecture d'un côté


def _entries_from_texts(textes):
    """{clé: entrée} des projets de plusieurs fichiers sources.

    `textes` est une suite de (fichier, texte). Une entrée porte « name »,
    « path », « sha » (le freeze-revision, ou None), « branch » et « file ».
    Un projet défini dans plusieurs fichiers garde sa DERNIÈRE définition,
    commit compris, même absent : c'est la règle de la fusion qui produit le
    manifeste local, et `textes` vient donc dans son ordre (`merge_order`).
    Un projet sans « path » prend son nom pour chemin, comme dans git-repo.
    """
    entrees = {}
    for fichier, texte in textes:
        for _, _, attrs in manifest_freeze.iter_projects(texte):
            cle = manifest_freeze.project_key(
                attrs.get("name"), attrs.get("path")
            )
            entrees[cle] = {
                "name": attrs.get("name"),
                "path": attrs.get("path") or attrs.get("name"),
                "sha": attrs.get(manifest_freeze.FREEZE_ATTR) or None,
                "branch": attrs.get("revision"),
                "remote": attrs.get("remote"),
                "file": fichier,
            }
    return entrees


def active_sources(racine):
    """Les fichiers sources que la fusion lit, dans son ordre, relatifs à la
    racine. Le répertoire courant y passe le temps de la lecture."""
    from script.git import git_freeze_manifest

    depart = os.getcwd()
    try:
        os.chdir(racine)
        return git_freeze_manifest.default_sources()
    finally:
        os.chdir(depart)


def merge_order(racine, fichiers):
    """`fichiers` dans l'ordre où la fusion les lit.

    Ceux qu'elle ne lit pas viennent d'abord, triés, puis les siens dans son
    ordre : la dernière définition l'emporte, donc celle d'un fichier actif.
    Une configuration illisible (un checkout incomplet) laisse l'ordre trié.
    """
    try:
        actifs = active_sources(racine)
    except Exception:
        actifs = []
    presents = set(fichiers)
    actifs = [f for f in dict.fromkeys(actifs) if f in presents]
    return sorted(presents - set(actifs)) + actifs


def read_worktree(racine):
    """Le gel des fichiers de `manifest/` tels qu'ils sont sur le disque."""
    fichiers = [
        os.path.relpath(chemin, racine)
        for chemin in glob.glob(os.path.join(racine, MANIFEST_DIR, "*.xml"))
    ]
    textes = []
    for fichier in merge_order(racine, fichiers):
        with open(os.path.join(racine, fichier)) as fh:
            textes.append((fichier, fh.read()))
    return _entries_from_texts(textes)


def resolve_ref(racine, ref):
    """Le commit complet d'une révision d'ERPLibre, ou None si inconnue."""
    code, sha = _git(
        racine, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"
    )
    return sha if not code and sha else None


def read_ref(racine, ref):
    """Le gel des fichiers de `manifest/` tels que `ref` les a committés."""
    code, liste = _git(
        racine, "ls-tree", "--name-only", ref, "--", f"{MANIFEST_DIR}/"
    )
    if code:
        raise ValueError(f"unknown revision: {ref}")
    fichiers = [f for f in liste.splitlines() if f.endswith(".xml")]
    textes = []
    for fichier in merge_order(racine, fichiers):
        code, texte = _git(racine, "show", f"{ref}:{fichier}")
        if not code:
            textes.append((fichier, texte))
    return _entries_from_texts(textes)


def is_clone(chemin):
    """Vrai si `chemin` est la RACINE d'un dépôt git.

    Un dossier non cloné sous le checkout ERPLibre, lui-même un dépôt git,
    ferait sinon tourner git dans ERPLibre : son commit, ses distants.
    """
    if not chemin or not os.path.isdir(chemin):
        return False
    code, racine = _git(chemin, "rev-parse", "--show-toplevel")
    return not code and os.path.realpath(racine) == os.path.realpath(chemin)


def inspect_clone(chemin):
    """État d'un clone : {sha, dirty, head_branch, cloned}."""
    vide = {"sha": None, "dirty": False, "head_branch": None, "cloned": False}
    if not is_clone(chemin):
        return vide
    code, sha = _git(chemin, "rev-parse", "--verify", "HEAD")
    if code or not manifest_freeze.is_sha(sha):
        return vide
    _, branche = _git(chemin, "symbolic-ref", "--quiet", "--short", "HEAD")
    _, sale = _git(chemin, "status", "--porcelain", "--untracked-files=no")
    return {
        "sha": sha,
        "dirty": bool(sale),
        "head_branch": branche or None,
        "cloned": True,
    }


def read_clones(racine, definitions, jobs=None):
    """Le commit HEAD de chaque clone que `definitions` nomme.

    `definitions` est une table {clé: entrée} au format de
    `_entries_from_texts` ; le « sha » de chaque entrée rendue est celui du
    clone, ou None quand le chemin n'est pas cloné.
    """
    cles = list(definitions)
    with _pool(jobs or default_jobs()) as pool:
        etats = list(
            pool.map(
                lambda c: (
                    inspect_clone(os.path.join(racine, definitions[c]["path"]))
                    if definitions[c]["path"]
                    else inspect_clone(None)
                ),
                cles,
            )
        )
    clones = {}
    for cle, etat in zip(cles, etats):
        clones[cle] = dict(definitions[cle], **etat)
    return clones


def default_definitions(racine):
    """Les projets des fichiers sources que la fusion lit aujourd'hui."""
    textes = []
    for fichier in active_sources(racine):
        with open(os.path.join(racine, fichier)) as fh:
            textes.append((fichier, fh.read()))
    return _entries_from_texts(textes)


def read_side(racine, spec, definitions=None, jobs=None):
    """Lit un côté. `definitions` sert au côté « clones » : les projets à
    inspecter ; par défaut, ceux des fichiers sources actifs."""
    if spec == WORKTREE:
        return read_worktree(racine)
    if spec == CLONES:
        if definitions is None:
            definitions = default_definitions(racine)
        return read_clones(racine, definitions, jobs=jobs)
    if not resolve_ref(racine, spec):
        raise ValueError(f"unknown revision: {spec}")
    return read_ref(racine, spec)


# Comparaison


def compare(gauche, droite, clones_side=None):
    """Lignes de comparaison, triées par chemin.

    Chaque ligne porte « key », « path », « old », « new », « status » et
    les entrées des deux côtés. Un projet sans commit d'aucun côté n'en
    produit pas. `clones_side` (« left », « right » ou None) dit quel côté
    est l'état des clones : un chemin qu'il n'a pas cloné y est « not
    cloned » plutôt qu'un projet sans gel.
    """

    def non_clone(cote, cle):
        return cle in cote and not cote[cle].get("cloned")

    lignes = []
    for cle in sorted(
        set(gauche) | set(droite),
        key=lambda c: ((gauche.get(c) or droite.get(c))["path"] or "", c),
    ):
        g = gauche.get(cle) or {}
        d = droite.get(cle) or {}
        ancien, neuf = g.get("sha"), d.get("sha")
        if not ancien and not neuf:
            continue
        if ancien and neuf:
            statut = STATUS_SAME if ancien == neuf else STATUS_CHANGED
        elif neuf:
            statut = (
                STATUS_NOT_CLONED
                if clones_side == "left" and non_clone(gauche, cle)
                else STATUS_NEW
            )
        elif clones_side == "right" and non_clone(droite, cle):
            statut = STATUS_NOT_CLONED
        else:
            statut = STATUS_GONE
        lignes.append(
            {
                "key": cle,
                "path": g.get("path") or d.get("path"),
                "old": ancien,
                "new": neuf,
                "status": statut,
                "left": g,
                "right": d,
            }
        )
    return lignes


def has_commit(chemin, sha):
    code, _ = _git(chemin, "cat-file", "-e", f"{sha}^{{commit}}")
    return code == 0


def numstat(chemin, ancien, neuf):
    """[(ajoutées, retirées, fichier)] entre deux commits.

    Un fichier binaire compte 0 ligne ; un fichier renommé porte son NOUVEAU
    chemin. Le format NUL de git (`-z`) rend les chemins tels quels : ni
    guillemets autour d'un nom accentué, ni « {a => b} » pour un renommage.
    """
    code, sortie = _git(
        chemin,
        "-c",
        "core.quotePath=false",
        "diff",
        "--numstat",
        "-z",
        ancien,
        neuf,
    )
    if code:
        return []
    champs = sortie.split("\0")
    fichiers = []
    i = 0
    while i < len(champs):
        morceaux = champs[i].split("\t", 2)
        i += 1
        if len(morceaux) != 3:
            continue
        plus, moins, fichier = morceaux
        if not fichier:
            # Un renommage : l'ancien chemin puis le nouveau suivent.
            if i + 1 >= len(champs):
                break
            fichier = champs[i + 1]
            i += 2
        fichiers.append(
            (
                int(plus) if plus.isdigit() else 0,
                int(moins) if moins.isdigit() else 0,
                fichier,
            )
        )
    return fichiers


def project_stats(chemin, ancien, neuf):
    """Les statistiques d'un projet changé, lues dans son clone.

    Rend {missing, ahead, behind, shallow, files}. `missing` liste ce que
    le clone n'a pas (« clone » pour un chemin qui n'en est pas un, « old »,
    « new ») ; les compteurs sont alors None. `ahead` compte les commits du
    nouveau absents de l'ancien, `behind` l'inverse : un retour en arrière a
    `ahead` nul.

    Dans un clone superficiel, deux commits sans ancêtre commun connu
    semblent diverger alors que l'historique coupé cache leur lien :
    `shallow` est vrai et les compteurs restent None.
    """
    vide = {"ahead": None, "behind": None, "shallow": False, "files": []}
    if not is_clone(chemin):
        return dict(vide, missing=["clone"])
    manquants = [
        nom
        for nom, sha in (("old", ancien), ("new", neuf))
        if not has_commit(chemin, sha)
    ]
    if manquants:
        return dict(vide, missing=manquants)
    fichiers = numstat(chemin, ancien, neuf)
    sans_base, _ = _git(chemin, "merge-base", ancien, neuf)
    if sans_base:
        _, superficiel = _git(chemin, "rev-parse", "--is-shallow-repository")
        if superficiel == "true":
            return dict(vide, missing=[], shallow=True, files=fichiers)
    code, compte = _git(
        chemin, "rev-list", "--left-right", "--count", f"{ancien}...{neuf}"
    )
    behind, ahead = (
        (int(x) for x in compte.split()) if not code else (None, None)
    )
    return {
        "missing": [],
        "ahead": ahead,
        "behind": behind,
        "shallow": False,
        "files": fichiers,
    }


def fill_stats(racine, lignes, jobs=None):
    """Pose « stats » et « branches » sur chaque ligne changée, en
    parallèle."""
    changees = [lg for lg in lignes if lg["status"] == STATUS_CHANGED]

    def calcul(lg):
        chemin = os.path.join(racine, lg["path"])
        return (
            project_stats(chemin, lg["old"], lg["new"]),
            branch_context(chemin, lg),
        )

    with _pool(jobs or default_jobs()) as pool:
        resultats = list(pool.map(calcul, changees))
    for ligne, (stats, branches) in zip(changees, resultats):
        ligne["stats"] = stats
        ligne["branches"] = branches
    return lignes


# Branches autour des commits


def branch_tip(chemin, branche, distant=None):
    """La référence complète de la branche `branche` dans un clone, ou None.

    D'abord la branche distante du distant du projet, puis celle de
    n'importe quel distant, puis la branche locale. Les refs « m/ » de
    git-repo n'en sont pas : elles nomment la révision du manifeste, pas une
    branche.
    """
    if not branche or manifest_freeze.is_sha(branche):
        return None
    motifs = [f"refs/remotes/{distant}/{branche}"] if distant else []
    motifs += [f"refs/remotes/*/{branche}", f"refs/heads/{branche}"]
    for motif in motifs:
        _, refs = _git(chemin, "for-each-ref", "--format=%(refname)", motif)
        for ref in refs.splitlines():
            if not ref.startswith("refs/remotes/m/"):
                return ref
    return None


def _compte(chemin, plage):
    code, n = _git(chemin, "rev-list", "--count", plage)
    return int(n) if not code and n.isdecimal() else None


def _refs(chemin, option, sha):
    code, noms = _git(
        chemin, "for-each-ref", option, sha, "--format=%(refname:short)"
    )
    return noms.splitlines() if not code else []


def commit_context(chemin, sha, tip=None, superficiel=False):
    """Où se trouve un commit parmi les refs d'un clone.

    Rend {behind, off, at, refs, more}. `behind` compte les commits de la
    pointe `tip` absents de `sha`, `off` ceux de `sha` absents de la pointe
    (un commit hors de la branche) ; None sans pointe, ou dans un clone
    superficiel qui ne connaît pas leur ancêtre commun. `at` nomme les refs
    qui pointent sur le commit, `refs` les autres qui le contiennent, toutes
    sortes confondues (branches, distantes, tags, « m/ »), `REFS_LIMIT` au
    plus ; `more` compte les autres.
    """
    ctx = {"behind": None, "off": None}
    if tip:
        sans_base = superficiel and _git(chemin, "merge-base", sha, tip)[0]
        if not sans_base:
            ctx["behind"] = _compte(chemin, f"{sha}..{tip}")
            ctx["off"] = _compte(chemin, f"{tip}..{sha}")
    ctx["at"] = _refs(chemin, "--points-at", sha)
    noms = [n for n in _refs(chemin, "--contains", sha) if n not in ctx["at"]]
    ctx["refs"] = noms[:REFS_LIMIT]
    ctx["more"] = max(0, len(noms) - REFS_LIMIT)
    return ctx


def last_fetch(chemin):
    """L'heure du dernier fetch d'un clone (epoch), ou None s'il n'en a
    jamais fait. git écrit FETCH_HEAD à chaque fetch."""
    code, fichier = _git(chemin, "rev-parse", "--git-path", "FETCH_HEAD")
    if code:
        return None
    if not os.path.isabs(fichier):
        fichier = os.path.join(chemin, fichier)
    try:
        return os.path.getmtime(fichier)
    except OSError:
        return None


def _court_ref(ref):
    for prefixe in ("refs/remotes/", "refs/heads/", "refs/tags/"):
        if ref and ref.startswith(prefixe):
            return ref[len(prefixe) :]
    return ref


def branch_context(chemin, ligne):
    """Les branches autour des deux commits d'une ligne changée, ou None
    hors d'un clone.

    La branche est celle du manifeste : « revision » du nouveau côté, ou de
    l'ancien. Rend {branch, tip, fetched, old, new}, où old et new valent
    `commit_context`, ou None pour un commit absent du clone.
    """
    if not is_clone(chemin):
        return None
    g, d = ligne["left"], ligne["right"]
    branche = next(
        (
            b
            for b in (d.get("branch"), g.get("branch"))
            if b and not manifest_freeze.is_sha(b)
        ),
        None,
    )
    tip = branch_tip(chemin, branche, d.get("remote") or g.get("remote"))
    _, superficiel = _git(chemin, "rev-parse", "--is-shallow-repository")
    ctx = {
        "branch": branche,
        "tip": _court_ref(tip),
        "fetched": last_fetch(chemin),
    }
    for cote in ("old", "new"):
        sha = ligne[cote]
        ctx[cote] = (
            commit_context(chemin, sha, tip, superficiel == "true")
            if sha and has_commit(chemin, sha)
            else None
        )
    return ctx


# Les gels des branches et des tags d'ERPLibre


def frozen_refs(racine, limite=ERPLIBRE_REFS_LIMIT):
    """Les branches et tags d'ERPLibre dont `manifest/` gèle un projet.

    Rend ([(noms, commit)], écartés) : les plus récents d'abord, `limite`
    au plus, les noms d'un même commit réunis (« master, origin/master »).
    Les refs « HEAD » des distants, qui doublent une branche, sont omises.
    """
    _, sortie = _git(
        racine,
        "for-each-ref",
        "--sort=-committerdate",
        "--format=%(refname)%09%(refname:short)%09%(objectname)"
        "%09%(*objectname)",
        "refs/heads",
        "refs/remotes",
        "refs/tags",
    )
    par_commit = {}
    for ligne in sortie.splitlines():
        complet, nom, objet, deref = (ligne.split("\t") + [""] * 4)[:4]
        if complet.endswith("/HEAD"):
            continue
        par_commit.setdefault(deref or objet, []).append(nom)
    commits = list(par_commit)
    geles = set()
    for i in range(0, len(commits), 50):
        lot = commits[i : i + 50]
        _, trouves = _git(
            racine,
            "grep",
            "-l",
            "-e",
            manifest_freeze.FREEZE_ATTR,
            *lot,
            "--",
            f"{MANIFEST_DIR}/",
        )
        geles.update(lg.split(":", 1)[0] for lg in trouves.splitlines())
    retenus = [c for c in commits if c in geles]
    return (
        [(", ".join(par_commit[c]), c) for c in retenus[:limite]],
        max(0, len(retenus) - limite),
    )


def erplibre_freezes(racine, refs):
    """[(noms, {clé: commit gelé})] des refs que rend `frozen_refs`."""
    tables = []
    for noms, commit in refs:
        try:
            gel = read_ref(racine, commit)
        except ValueError:
            continue
        tables.append(
            (noms, {c: e["sha"] for c, e in gel.items() if e["sha"]})
        )
    return tables


def frozen_in(tables, cle, sha):
    """Les noms des refs d'ERPLibre qui gèlent le projet `cle` sur `sha`."""
    return [noms for noms, gel in tables if sha and gel.get(cle) == sha]


def fetch_commits(chemin, shas):
    """Va chercher des commits absents d'un clone. Rend les shas encore
    absents.

    Chaque distant du clone est essayé, d'abord sur le commit seul, puis en
    entier : un serveur peut refuser un commit qu'il n'annonce pas.
    """
    if not is_clone(chemin):
        return list(shas)
    manquants = [s for s in shas if not has_commit(chemin, s)]
    if not manquants:
        return []
    _, distants = _git(chemin, "remote")
    for distant in distants.splitlines():
        _git(chemin, "fetch", "--quiet", "--no-tags", distant, *manquants)
        manquants = [s for s in manquants if not has_commit(chemin, s)]
        if not manquants:
            return []
        _git(chemin, "fetch", "--quiet", "--no-tags", distant)
        manquants = [s for s in manquants if not has_commit(chemin, s)]
        if not manquants:
            return []
    return manquants


def missing_rows(lignes):
    return [
        lg
        for lg in lignes
        if lg.get("stats")
        and lg["stats"]["missing"]
        and "clone" not in lg["stats"]["missing"]
    ]


def refresh_clone(chemin, shas):
    """Rafraîchit les refs d'un clone, puis va chercher les commits encore
    absents. Rend les shas toujours absents."""
    if not is_clone(chemin):
        return list(shas)
    _git(chemin, "fetch", "--quiet", "--all")
    return fetch_commits(chemin, shas)


def fetch_missing(racine, lignes, jobs=None):
    """Rafraîchit en parallèle chaque clone d'une ligne changée : ses
    branches et ses tags, et les commits qui lui manquent. Refait ensuite
    les stats et les branches. Rend {chemin: shas encore absents}."""
    a_chercher = [
        lg
        for lg in lignes
        if lg["status"] == STATUS_CHANGED
        and "clone" not in (lg.get("stats") or {}).get("missing", [])
    ]
    with _pool(jobs or default_jobs()) as pool:
        restes = list(
            pool.map(
                lambda lg: refresh_clone(
                    os.path.join(racine, lg["path"]), [lg["old"], lg["new"]]
                ),
                a_chercher,
            )
        )
    fill_stats(racine, a_chercher, jobs=jobs)
    return {lg["path"]: r for lg, r in zip(a_chercher, restes) if r}


# Regroupement


def group_key(fichier, by):
    """La clé de regroupement d'un fichier changé.

    « ext » : l'extension (« (none) » sans extension). « dir » : le premier
    dossier. « module » : le module Odoo, soit le premier dossier, ou le
    suivant sous un dossier « addons » (odoo/addons/<module>).
    """
    if by == "ext":
        base = os.path.basename(fichier)
        _, ext = os.path.splitext(base)
        return ext.lower() if ext and ext != base else "(none)"
    parties = fichier.split("/")
    if len(parties) == 1:
        return "(root)"
    if by == "module":
        for i, partie in enumerate(parties[:-1]):
            if partie == "addons" and i + 2 < len(parties):
                return "/".join(parties[: i + 2])
    return parties[0]


def group_files(fichiers, by):
    """[(clé, fichiers, ajoutées, retirées)], du plus gros au plus petit."""
    groupes = {}
    for plus, moins, fichier in fichiers:
        g = groupes.setdefault(group_key(fichier, by), [0, 0, 0])
        g[0] += 1
        g[1] += plus
        g[2] += moins
    return sorted(
        ((k, n, p, m) for k, (n, p, m) in groupes.items()),
        key=lambda x: (-(x[2] + x[3]), x[0]),
    )


# Contexte du checkout


def head_info(racine):
    """{sha, branch} du checkout ERPLibre ; branch None si détaché."""
    _, sha = _git(racine, "rev-parse", "--verify", "HEAD")
    _, branche = _git(racine, "symbolic-ref", "--quiet", "--short", "HEAD")
    return {"sha": sha or None, "branch": branche or None}


def uncommitted_freeze(racine):
    """Clés dont le freeze-revision de `manifest/` diffère de HEAD."""
    try:
        engage = read_ref(racine, "HEAD")
    except ValueError:
        return []
    ecrit = read_worktree(racine)
    return sorted(
        c
        for c in set(engage) | set(ecrit)
        if (engage.get(c) or {}).get("sha") != (ecrit.get(c) or {}).get("sha")
    )


def _gel_du_fichier(racine, ref, fichier):
    """{clé: sha} d'un fichier tel que `ref` l'a committé ; {} s'il n'y
    existe pas."""
    code, texte = _git(racine, "show", f"{ref}:{fichier}")
    if code:
        return {}
    return {
        c: e["sha"] for c, e in _entries_from_texts([(fichier, texte)]).items()
    }


def is_freeze_commit(racine, sha):
    """Vrai si le commit pose un NOUVEAU commit gelé sur au moins un projet.

    Un commit qui ne fait que dégeler, ou qui modifie une autre partie d'une
    ligne qui porte « freeze-revision », n'en est pas un. Chaque fichier
    de `manifest/` qu'il touche se compare à son état dans le premier
    parent ; un commit racine se compare à rien.
    """
    code, fichiers = _git(
        racine,
        "diff-tree",
        "--root",
        "--no-commit-id",
        "--name-only",
        "-r",
        sha,
        "--",
        f"{MANIFEST_DIR}/",
    )
    if code:
        return False
    for fichier in fichiers.splitlines():
        if not fichier.endswith(".xml"):
            continue
        avant = _gel_du_fichier(racine, f"{sha}^", fichier)
        apres = _gel_du_fichier(racine, sha, fichier)
        if any(s and s != avant.get(c) for c, s in apres.items()):
            return True
    return False


def freeze_commits(racine, limite=20, examen=500):
    """[(sha, date, sujet)] des commits d'ERPLibre qui ont gelé un projet
    dans `manifest/`, du plus récent au plus ancien, `limite` au plus.

    `git log -G` présélectionne les commits dont une ligne changée porte
    l'attribut, `is_freeze_commit` les confirme ; au plus `examen`
    candidats sont lus.
    """
    code, sortie = _git(
        racine,
        "log",
        f"-{examen}",
        f"-G{manifest_freeze.FREEZE_ATTR}",
        "--format=%H%x09%ad%x09%s",
        "--date=short",
        "--",
        f"{MANIFEST_DIR}/",
    )
    if code:
        return []
    gels = []
    for ligne in sortie.splitlines():
        if ligne.count("\t") < 2:
            continue
        sha, date, sujet = ligne.split("\t", 2)
        if is_freeze_commit(racine, sha):
            gels.append((sha, date, sujet))
            if len(gels) >= limite:
                break
    return gels


def previous_freeze(racine):
    """(avant-dernier, dernier) commits de gel, ou None s'il en manque."""
    gels = freeze_commits(racine, limite=2)
    if len(gels) < 2:
        return None
    return gels[1][0], gels[0][0]


# Rapport


def build(racine, gauche, droite, jobs=None):
    """Calcule la comparaison. Rend le rapport, une table que `render` lit.

    Lève ValueError sur une révision inconnue.
    """
    cote_g = None if gauche == CLONES else read_side(racine, gauche, jobs=jobs)
    cote_d = None if droite == CLONES else read_side(racine, droite, jobs=jobs)
    if CLONES in (gauche, droite):
        # Les clones à inspecter : ceux des fichiers actifs, plus tout projet
        # que l'autre côté nomme, pour qu'un chemin gelé puis disparu se
        # voie comme « non cloné » et non comme un dégel.
        definitions = default_definitions(racine)
        for autre in (cote_g, cote_d):
            for cle, entree in (autre or {}).items():
                definitions.setdefault(cle, entree)
        clones = read_clones(racine, definitions, jobs=jobs)
        cote_g = clones if cote_g is None else cote_g
        cote_d = clones if cote_d is None else cote_d
    cote_clones = (
        "right" if droite == CLONES else "left" if gauche == CLONES else None
    )
    lignes = compare(cote_g, cote_d, clones_side=cote_clones)
    fill_stats(racine, lignes, jobs=jobs)
    rapport = {
        "racine": racine,
        "from": gauche,
        "to": droite,
        "rows": lignes,
        "head": head_info(racine),
        "uncommitted": [],
        "dirty": [],
        "frozen": {
            "from": sum(1 for e in cote_g.values() if e.get("sha")),
            "to": sum(1 for e in cote_d.values() if e.get("sha")),
        },
    }
    if WORKTREE not in (gauche, droite):
        rapport["uncommitted"] = uncommitted_freeze(racine)
    if CLONES in (gauche, droite):
        rapport["dirty"] = sorted(
            e["path"] for e in clones.values() if e.get("dirty")
        )
    refs, ecartes = frozen_refs(racine)
    rapport["erplibre"] = erplibre_freezes(racine, refs)
    rapport["erplibre_dropped"] = ecartes
    rapport["now"] = time.time()
    return rapport


def changed_rows(rapport):
    return [lg for lg in rapport["rows"] if lg["status"] == STATUS_CHANGED]


def _court(sha):
    return sha[:8] if sha else "-"


def _nom(spec):
    """Le nom court d'un côté : un commit complet s'abrège."""
    return _court(spec) if manifest_freeze.is_sha(spec) else spec


# Les indications qui renvoient à un geste : la ligne de commande et le menu
# n'offrent pas le même.
HINTS = {
    False: {
        "uncommitted": "compare them with --from HEAD --to worktree",
        "all": "--all lists them",
        "fetch": "refresh with --fetch",
        "stat": "--stat-count 0 shows all",
    },
    True: {
        "uncommitted": "compare them with choice 3",
        "all": "--all lists them, on the command line",
        "fetch": "refresh with f",
        "stat": "s N shows all",
    },
}


def _label(racine, spec):
    if spec == WORKTREE:
        return "manifest/ on disk (worktree)"
    if spec == CLONES:
        return "clones (HEAD of each clone)"
    sha = resolve_ref(racine, spec)
    return f"{spec} ({_court(sha)})" if sha and sha != spec else _court(sha)


def _commits(stats):
    if stats["missing"]:
        return "missing " + "+".join(stats["missing"])
    if stats.get("shallow"):
        return "? shallow"
    if stats["ahead"] is None:
        return "?"
    texte = f"+{stats['ahead']} -{stats['behind']}"
    if not stats["ahead"] and stats["behind"]:
        texte += " rollback"
    return texte


def _totaux(fichiers):
    return (
        len(fichiers),
        sum(f[0] for f in fichiers),
        sum(f[1] for f in fichiers),
    )


def _notes(ligne):
    notes = []
    g, d = ligne["left"], ligne["right"]
    if g.get("branch") and d.get("branch") and g["branch"] != d["branch"]:
        if not manifest_freeze.is_sha(d["branch"]):
            notes.append(f"branch {g['branch']} -> {d['branch']}")
    if d.get("dirty") or g.get("dirty"):
        notes.append("dirty")
    branche = d.get("head_branch") or g.get("head_branch")
    if branche:
        notes.append(f"on {branche}")
    return ", ".join(notes)


def _position(ctx):
    """La place d'un commit sur sa branche : « tip », « -12 » (12 commits
    derrière la pointe), « +2 off » (2 commits hors de la branche), « ? »
    sans mesure."""
    if not ctx or ctx.get("behind") is None:
        return "?"
    texte = "tip" if not ctx["behind"] else f"-{ctx['behind']}"
    if ctx.get("off"):
        texte += f" +{ctx['off']} off"
    return texte


def _colonne_branche(ligne):
    """La colonne courte du tableau : la branche et la place des deux
    commits, « 18.0 -12->tip »."""
    ctx = ligne.get("branches")
    if not ctx or not ctx.get("branch"):
        return ""
    if not ctx.get("tip"):
        return f"{ctx['branch']} (no ref)"
    return (
        f"{ctx['branch']} {_position(ctx.get('old'))}"
        f"->{_position(ctx.get('new'))}"
    )


def _jours(rapport, epoch):
    return int((rapport.get("now", time.time()) - epoch) // 86400)


def _abrege(chemin, largeur):
    """Un chemin tenu dans `largeur` : la fin, qui le nomme, est gardée."""
    if len(chemin) <= largeur:
        return chemin
    return "…" + chemin[-(largeur - 1) :]


def _summary_context(rapport, aide):
    """Les côtés comparés, le HEAD d'ERPLibre, et ce qui n'est dans aucun
    gel : le gel pas encore committé, les clones modifiés, un côté sans
    gel."""
    racine = rapport["racine"]
    head = rapport["head"]
    out = [
        f"Freeze diff: {_label(racine, rapport['from'])}"
        f" -> {_label(racine, rapport['to'])}",
        f"ERPLibre HEAD: {_court(head['sha'])}"
        + (f" on {head['branch']}" if head["branch"] else " (detached)"),
    ]
    if rapport["uncommitted"]:
        out.append(
            f"WARNING: manifest/ holds {len(rapport['uncommitted'])}"
            " freeze-revision changes not committed"
            f" ({aide['uncommitted']})."
        )
    if rapport["dirty"]:
        out.append(
            f"WARNING: {len(rapport['dirty'])} clones have uncommitted"
            " changes, not part of any freeze:"
        )
        out.extend(f"  - {p}" for p in rapport["dirty"])
    for cote in ("from", "to"):
        spec = rapport[cote]
        if spec != CLONES and not rapport["frozen"][cote]:
            out.append(
                f"NOTE: {_nom(spec)} holds no freeze-revision. Freeze with"
                " make repo_freeze, then commit manifest/."
            )
    return out


def _summary_counts(lignes):
    if not lignes:
        return ["No project has a frozen commit on either side."]
    compte = {}
    for lg in lignes:
        compte[lg["status"]] = compte.get(lg["status"], 0) + 1
    statuts = (
        STATUS_SAME,
        STATUS_CHANGED,
        STATUS_NEW,
        STATUS_GONE,
        STATUS_NOT_CLONED,
    )
    return [
        f"{len(lignes)} projects: "
        + ", ".join(f"{compte[s]} {s}" for s in statuts if compte.get(s))
    ]


def _summary_table(changees):
    """Le tableau compact des projets changés, numérotés à partir de 1."""
    if not changees:
        return []
    stats = [
        lg.get("stats") or {"missing": ["?"], "files": []} for lg in changees
    ]
    largeur = max(len(lg["path"]) for lg in changees)
    largeur = max(min(largeur, 50), len("project"))
    large_c = max([len("commits")] + [len(_commits(st)) for st in stats])
    large_b = max(
        [len("vs branch")] + [len(_colonne_branche(lg)) for lg in changees]
    )
    out = [
        "",
        f" {'#':>3}  {'project':<{largeur}}  {'old':<8}  {'new':<8}"
        f"  {'commits':<{large_c}}"
        f"  {'files':>6} {'+lines':>8} {'-lines':>8}"
        f"  {'vs branch':<{large_b}}".rstrip(),
    ]
    for i, (lg, st) in enumerate(zip(changees, stats), 1):
        n, plus, moins = _totaux(st["files"])
        chiffres = (
            f"  {n:>6} {'+' + str(plus):>8} {'-' + str(moins):>8}"
            if not st["missing"]
            else " " * 26
        )
        notes = _notes(lg)
        out.append(
            (
                f" {i:>3}  {_abrege(lg['path'], largeur):<{largeur}}"
                f"  {_court(lg['old']):<8}  {_court(lg['new']):<8}"
                f"  {_commits(st):<{large_c}}{chiffres}"
                f"  {_colonne_branche(lg):<{large_b}}"
                + (f"  [{notes}]" if notes else "")
            ).rstrip()
        )
    return out


def _summary_lists(rapport, aide, show_all):
    """Les projets qui n'ont de commit que d'un côté, ou pas de clone."""
    de, vers = _nom(rapport["from"]), _nom(rapport["to"])
    titres = {
        STATUS_NEW: (f"No commit in {de}, commit in {vers}", "from"),
        STATUS_GONE: (f"Commit in {de}, none in {vers}", "to"),
        STATUS_NOT_CLONED: ("Commit on one side, path not cloned", None),
    }
    out = []
    for statut, (titre, cote_vide) in titres.items():
        liste = [lg for lg in rapport["rows"] if lg["status"] == statut]
        if not liste:
            continue
        out.append("")
        out.append(f"{titre}: {len(liste)}")
        sans_gel = (
            cote_vide
            and rapport[cote_vide] != CLONES
            and not rapport.get("frozen", {}).get(cote_vide)
        )
        if sans_gel and not show_all:
            out.append(f"  ({aide['all']})")
            continue
        montres = liste if show_all else liste[:LIST_LIMIT]
        out.extend(
            f"  - {lg['path']} {_court(lg['old'] or lg['new'])}"
            for lg in montres
        )
        if len(montres) < len(liste):
            out.append(
                f"  ... {len(liste) - len(montres)} more ({aide['all']})"
            )
    return out


def _clones_anciens(rapport, changees):
    """[(chemin, jours ou None)] des clones dont le dernier fetch a plus de
    FRESH_DAYS jours, ou qui n'en ont jamais fait."""
    vieux = []
    for lg in changees:
        ctx = lg.get("branches")
        if not ctx:
            continue
        if ctx["fetched"] is None:
            vieux.append((lg["path"], None))
        elif _jours(rapport, ctx["fetched"]) > FRESH_DAYS:
            vieux.append((lg["path"], _jours(rapport, ctx["fetched"])))
    return vieux


def _summary_warnings(rapport, aide, changees):
    """Ce qui limite la mesure : commits absents, clones superficiels,
    refs anciennes, refs d'ERPLibre non lues."""
    out = []
    manquantes = missing_rows(rapport["rows"])
    if manquantes:
        out += [
            "",
            f"{len(manquantes)} projects lack a commit locally, no count;"
            f" {aide['fetch']}:",
        ]
        for lg in manquantes:
            for cote in lg["stats"]["missing"]:
                out.append(f"  - {lg['path']}: {cote} {lg[cote]}")
    superficiels = [
        lg for lg in changees if (lg.get("stats") or {}).get("shallow")
    ]
    if superficiels:
        out += [
            "",
            f"{len(superficiels)} shallow clones: commits not counted, their"
            " history is cut (git -C <path> fetch --unshallow restores it):",
        ]
        out.extend(f"  - {lg['path']}" for lg in superficiels)
    vieux = _clones_anciens(rapport, changees)
    if vieux:
        out += [
            "",
            f"{len(vieux)} clones not fetched for over {FRESH_DAYS} days:"
            f" their branches may lag behind the server; {aide['fetch']}.",
        ]
        out.extend(
            f"  - {p}: " + ("never fetched" if j is None else f"{j} days ago")
            for p, j in vieux
        )
    if rapport.get("erplibre_dropped"):
        out += [
            "",
            f"{rapport['erplibre_dropped']} older ERPLibre branches or tags"
            f" holding a freeze are not read (the {ERPLIBRE_REFS_LIMIT} most"
            " recent are).",
        ]
    return out


def render_summary(rapport, show_all=False, menu=False):
    """Les lignes du sommaire : contexte, compteurs et tableau compact.

    `menu` choisit les indications du menu plutôt que de la ligne de
    commande. Les projets sans commit d'un côté se listent, sauf quand ce
    côté ne porte aucun gel : la liste serait celle de tous les projets.
    """
    aide = HINTS[menu]
    changees = changed_rows(rapport)
    return (
        _summary_context(rapport, aide)
        + _summary_counts(rapport["rows"])
        + _summary_table(changees)
        + _summary_lists(rapport, aide, show_all)
        + _summary_warnings(rapport, aide, changees)
    )


def auto_stat_count(rapport):
    """Le bornage du diffstat : 0 (tout) quand le total est court."""
    total = sum(
        len((lg.get("stats") or {}).get("files") or [])
        for lg in changed_rows(rapport)
    )
    return 0 if total <= AUTO_FULL_FILES else AUTO_STAT_COUNT


def diffstat(racine, ligne, stat_count=0, largeur=100):
    """Le diffstat git d'un projet changé, borné à `stat_count` fichiers
    (0 : tous)."""
    args = ["-c", "core.quotePath=false", "diff", f"--stat={largeur}"]
    if stat_count:
        args.append(f"--stat-count={stat_count}")
    code, sortie = _git(
        os.path.join(racine, ligne["path"]), *args, ligne["old"], ligne["new"]
    )
    return sortie.splitlines() if not code else []


def render_groups(fichiers, by, indent="    "):
    if by == "none" or not fichiers:
        return []
    out = [f"{indent}by {by}:"]
    for cle, n, plus, moins in group_files(fichiers, by):
        out.append(
            f"{indent}  {cle:<30} {n:>5} files"
            f" {'+' + str(plus):>8} {'-' + str(moins):>8}"
        )
    return out


def history_range(ligne):
    """La plage git qui montre ce qui sépare les deux commits."""
    st = ligne.get("stats") or {}
    if st.get("shallow"):
        return f"{ligne['old']}..{ligne['new']}"
    if st.get("ahead") == 0 and st.get("behind"):
        return f"{ligne['new']}..{ligne['old']}"
    if st.get("behind"):
        return f"{ligne['old']}...{ligne['new']}"
    return f"{ligne['old']}..{ligne['new']}"


def log_oneline(racine, ligne):
    """git log --oneline de ce qui sépare les deux commits. Sur une plage
    symétrique, « < » marque un commit de l'ancien, « > » du nouveau."""
    plage = history_range(ligne)
    options = ["--left-right"] if "..." in plage else []
    code, sortie = _git(
        os.path.join(racine, ligne["path"]),
        "log",
        "--oneline",
        *options,
        plage,
    )
    return sortie.splitlines() if not code else []


def render_logs(rapport):
    """Le git log --oneline de chaque projet changé, numéroté comme le
    tableau du sommaire."""
    out = []
    for i, lg in enumerate(changed_rows(rapport), 1):
        if (lg.get("stats") or {}).get("missing"):
            continue
        out.append(
            f"[{i}] {lg['path']}  {_court(lg['old'])} -> {_court(lg['new'])}"
        )
        out.extend(f"    {c}" for c in log_oneline(rapport["racine"], lg))
    return out


def render_branches(rapport, ligne, indent="    "):
    """Les branches autour des deux commits d'une ligne changée.

    La branche du manifeste et la date du dernier fetch, puis pour chaque
    commit : sa place sur la branche, les refs du clone qui pointent dessus
    ou le contiennent, et les branches ou tags d'ERPLibre qui le gèlent.
    """
    ctx = ligne.get("branches")
    out = []
    if ctx:
        quand = (
            "never fetched"
            if ctx["fetched"] is None
            else time.strftime("%Y-%m-%d", time.localtime(ctx["fetched"]))
            + f", {_jours(rapport, ctx['fetched'])} days ago"
        )
        cible = f" = {ctx['tip']}" if ctx["tip"] else ", no such ref here"
        out.append(
            f"{indent}branch {ctx['branch'] or '-'}{cible}; refs as of {quand}"
        )
    tables = rapport.get("erplibre") or []
    for cote in ("old", "new"):
        sha = ligne[cote]
        c = (ctx or {}).get(cote)
        morceaux = []
        if c:
            if c.get("behind") is not None:
                place = (
                    "at the tip"
                    if not c["behind"]
                    else f"{c['behind']} behind the tip"
                )
                if c.get("off"):
                    place += f", {c['off']} not on the branch"
                morceaux.append(place)
            if c["at"]:
                morceaux.append("is " + ", ".join(c["at"]))
            if c["refs"]:
                plus = f" (+{c['more']})" if c["more"] else ""
                morceaux.append("in " + ", ".join(c["refs"]) + plus)
            elif not c["at"]:
                morceaux.append("in no ref of the clone")
        elif ctx:
            morceaux.append("not in the clone")
        geles = frozen_in(tables, ligne["key"], sha)
        if geles:
            morceaux.append("frozen by ERPLibre " + "; ".join(geles))
        if morceaux:
            out.append(f"{indent}{cote} {_court(sha)}: " + "; ".join(morceaux))
    return out


def open_graph(racine, ligne):
    """Ouvre le graphe décoré des deux commits et de la pointe de leur
    branche : tig, ou git log --graph à défaut, qui passe par le pager.

    Le graphe part de l'ancêtre commun des trois, inclus. Rend le code de
    sortie, comme `open_history`.
    """
    chemin = os.path.join(racine, ligne["path"])
    ctx = ligne.get("branches") or {}
    refs = [ligne["old"], ligne["new"]]
    if ctx.get("tip"):
        refs.append(ctx["tip"])
    code, base = _git(chemin, "merge-base", "--octopus", *refs)
    exclus = []
    if (
        not code
        and base
        and not _git(chemin, "rev-parse", "-q", "--verify", f"{base}^")[0]
    ):
        exclus = [f"^{base}^@"]
    if shutil.which("tig"):
        commande = ["tig", *refs, *exclus]
    else:
        commande = [
            "git",
            "log",
            "--graph",
            "--oneline",
            "--decorate",
            *refs,
            *exclus,
        ]
    return _attendre(commande, chemin)


def _attendre(commande, chemin):
    """Lance `commande` dans `chemin` sur le terminal, et attend sa fin
    même si un Ctrl-C l'interrompt. Rend son code de sortie."""
    processus = subprocess.Popen(commande, cwd=chemin)
    while True:
        try:
            return processus.wait()
        except KeyboardInterrupt:
            continue


def matrix(racine, specs, jobs=None):
    """Le commit gelé de chaque projet dans plusieurs côtés à la fois.

    `specs` est une suite de côtés (révisions d'ERPLibre, « worktree »,
    « clones »). Rend {columns, rows} où chaque ligne est (chemin, [commit
    ou None par colonne]), triée par chemin ; un projet sans commit nulle
    part n'en produit pas. Lève ValueError sur une révision inconnue.
    """
    tables = [
        None if s == CLONES else read_side(racine, s, jobs=jobs) for s in specs
    ]
    if CLONES in specs:
        definitions = default_definitions(racine)
        for table in tables:
            for cle, entree in (table or {}).items():
                definitions.setdefault(cle, entree)
        clones = read_clones(racine, definitions, jobs=jobs)
        tables = [clones if tb is None else tb for tb in tables]
    cles = set().union(*tables) if tables else set()
    lignes = []
    for cle in cles:
        shas = [(tb.get(cle) or {}).get("sha") for tb in tables]
        if not any(shas):
            continue
        chemin = next(tb[cle]["path"] for tb in tables if cle in tb)
        lignes.append((chemin or "", shas))
    return {"columns": list(specs), "rows": sorted(lignes)}


def render_matrix(table, show_all=False):
    """Le tableau projet × côtés. Sauf `show_all`, seules les lignes où les
    colonnes diffèrent ; un commit égal à celui de la colonne de gauche
    s'écrit « = »."""
    colonnes = [_abrege(_nom(c), 14) for c in table["columns"]]
    lignes = [(p, s) for p, s in table["rows"] if show_all or len(set(s)) > 1]
    out = [
        f"{len(table['rows'])} projects, {len(lignes)} shown"
        + ("" if show_all else " (those that differ; --all shows every one)")
    ]
    if not lignes:
        return out
    largeur = min(max(len(p) for p, _ in lignes), 50)
    out.append(
        (
            f"  {'project':<{largeur}}  "
            + "  ".join(f"{c:<14}" for c in colonnes)
        ).rstrip()
    )
    for chemin, shas in lignes:
        cases = []
        for i, sha in enumerate(shas):
            cases.append(
                "=" if i and sha and sha == shas[i - 1] else _court(sha)
            )
        out.append(
            (
                f"  {_abrege(chemin, largeur):<{largeur}}  "
                + "  ".join(f"{c:<14}" for c in cases)
            ).rstrip()
        )
    return out


def default_matrix_sides(racine):
    """Les côtés de la matrice par défaut : les branches et tags d'ERPLibre
    qui portent un gel, puis le disque et les clones."""
    refs, _ = frozen_refs(racine)
    return [noms.split(", ")[0] for noms, _ in refs] + [WORKTREE, CLONES]


def render_details(
    rapport,
    stat_count=None,
    group_by="ext",
    log=False,
    numeros=None,
    menu=False,
):
    """Le détail de chaque projet changé : diffstat, groupes, journal.

    `stat_count` None choisit selon la taille (`auto_stat_count`).
    `numeros` restreint aux lignes de ces numéros du tableau (à partir de 1).
    `menu` choisit les indications du menu.
    """
    racine = rapport["racine"]
    changees = changed_rows(rapport)
    if stat_count is None:
        stat_count = auto_stat_count(rapport)
    out = []
    tous = []
    for i, lg in enumerate(changees, 1):
        if numeros and i not in numeros:
            continue
        st = lg.get("stats") or {}
        if st.get("missing"):
            continue
        tous.extend(st.get("files") or [])
        out.append("")
        out.append(
            f"[{i}] {lg['path']}  {_court(lg['old'])} -> {_court(lg['new'])}"
            f"  ({_commits(st)})"
        )
        out.extend(render_branches(rapport, lg))
        stat = diffstat(racine, lg, stat_count=stat_count)
        out.extend(f"    {s}" for s in stat)
        if stat_count and len(st.get("files") or []) > stat_count:
            out.append(
                f"    (diffstat limited to {stat_count} of"
                f" {len(st['files'])} files; {HINTS[menu]['stat']})"
            )
        out.extend(render_groups(st.get("files") or [], group_by))
        if log:
            out.append("    log:")
            out.extend(f"      {c}" for c in log_oneline(racine, lg))
    if (
        len(
            [
                lg
                for lg in changees
                if not (lg.get("stats") or {}).get("missing")
            ]
        )
        > 1
        and not numeros
    ):
        out.append("")
        out.append("All changed projects:")
        out.extend(render_groups(tous, group_by, indent="  "))
    return out


def render_tip(rapport):
    """La suggestion de worktree : lire un ancien commit à côté du clone."""
    changees = [
        lg
        for lg in changed_rows(rapport)
        if not (lg.get("stats") or {}).get("missing")
    ]
    if not changees:
        return []
    lg = changees[0]
    cible = shlex.quote(f"{os.path.basename(lg['path'])}-{_court(lg['old'])}")
    return [
        "",
        "Tip: open the old commit beside the clone, without moving it:",
        f"  git -C {shlex.quote(lg['path'])} worktree add --detach"
        f' "$(mktemp -d)"/{cible} {lg["old"]}',
        "  then: git -C <path> worktree remove <dir>",
    ]


def open_history(racine, ligne):
    """Ouvre l'historique d'un projet changé : tig, ou git log à défaut.

    Le programme hérite du terminal (aucun tube) : tig en a besoin pour
    s'afficher. Un Ctrl-C tapé pendant qu'il tourne lui revient, et
    l'appelant continue d'attendre sa fin plutôt que de s'interrompre.
    Rend son code de sortie, négatif s'il a été tué par un signal.
    """
    chemin = os.path.join(racine, ligne["path"])
    plage = history_range(ligne)
    if shutil.which("tig"):
        commande = ["tig", plage]
    else:
        commande = ["git", "log", "--oneline", "--graph", plage]
    return _attendre(commande, chemin)


# Ligne de commande


def get_config(argv=None):
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Compare two freezes: what each repository changed from one to"
            " the other."
        ),
        epilog=(
            "A side is an ERPLibre revision (HEAD, a tag, a commit),"
            f" '{WORKTREE}' or '{CLONES}'.\n"
            "Examples:\n"
            "  git_freeze_diff.py                  HEAD -> clones\n"
            "  git_freeze_diff.py --to worktree    uncommitted freeze\n"
            "  git_freeze_diff.py --previous       previous -> last freeze\n"
            "  git_freeze_diff.py --from v1.8.0 --to HEAD --log"
        ),
    )
    parser.add_argument(
        "--from",
        dest="gauche",
        default="HEAD",
        metavar="SIDE",
        help=f"An ERPLibre revision, {WORKTREE} or {CLONES}. Default: HEAD.",
    )
    parser.add_argument(
        "--to",
        dest="droite",
        default=CLONES,
        metavar="SIDE",
        help=(
            f"An ERPLibre revision, {WORKTREE} or {CLONES}."
            f" Default: {CLONES}."
        ),
    )
    parser.add_argument(
        "--previous",
        action="store_true",
        help="Compare the two last commits that froze a project.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List the commits that froze a project, then stop.",
    )
    parser.add_argument(
        "--list-refs",
        action="store_true",
        help=(
            "List the ERPLibre branches and tags holding a freeze, then stop."
        ),
    )
    parser.add_argument(
        "--matrix",
        nargs="?",
        const="",
        metavar="SIDE,SIDE",
        help=(
            "Show the frozen commit of every project in several sides at"
            " once, then stop. Default: the ERPLibre branches and tags holding"
            f" a freeze, {WORKTREE} and {CLONES}."
        ),
    )
    parser.add_argument(
        "--graph",
        metavar="N|PATH",
        help=(
            "Open the decorated graph of project N (or PATH): both commits"
            " and the tip of their branch."
        ),
    )
    parser.add_argument(
        "--stat-count",
        type=int,
        default=None,
        help=(
            "Files shown in each project's diffstat; 0 shows all. Default:"
            f" all up to {AUTO_FULL_FILES} changed files in total, else"
            f" {AUTO_STAT_COUNT}."
        ),
    )
    parser.add_argument(
        "--group-by",
        choices=GROUPS,
        default="ext",
        help="Group the changed lines by file type, Odoo module or folder.",
    )
    parser.add_argument(
        "--summary", action="store_true", help="Only the compact table."
    )
    parser.add_argument(
        "--log", action="store_true", help="git log --oneline per project."
    )
    parser.add_argument(
        "--tig",
        nargs="?",
        const="all",
        metavar="N|PATH",
        help=(
            "Open tig on project N of the table, or on PATH; alone: on each"
            " project in turn."
        ),
    )
    parser.add_argument(
        "--fetch",
        action="store_true",
        help=(
            "Refresh the branches and tags of each changed clone and fetch"
            " the commits it lacks, in parallel, before comparing."
        ),
    )
    parser.add_argument(
        "--all", action="store_true", help="Do not shorten the project lists."
    )
    parser.add_argument("--jobs", type=int, default=default_jobs())
    return parser.parse_args(argv)


def select_rows(rapport, choix):
    """Les lignes changées que désigne `choix` : « all », un numéro du
    tableau ou un chemin. Rend [] si rien ne correspond."""
    changees = [
        lg
        for lg in changed_rows(rapport)
        if not (lg.get("stats") or {}).get("missing")
    ]
    if choix == "all":
        return changees
    tous = changed_rows(rapport)
    if choix.isdecimal() and 1 <= int(choix) <= len(tous):
        ligne = tous[int(choix) - 1]
        return [ligne] if ligne in changees else []
    chemin = choix.rstrip("/")
    return [lg for lg in changees if lg["path"] == chemin]


def _main_list(config, racine):
    """Les options qui listent puis s'arrêtent. Rend un code de sortie, ou
    None quand aucune n'est demandée."""
    if config.list:
        gels = freeze_commits(racine)
        if not gels:
            print("No commit froze a project in manifest/.")
            return 1
        for sha, date, sujet in gels:
            print(f"{sha[:8]}  {date}  {sujet}")
        return 0
    if config.list_refs:
        refs, ecartes = frozen_refs(racine)
        if not refs:
            print("No ERPLibre branch or tag holds a freeze.")
            return 1
        for noms, commit in refs:
            print(f"{commit[:8]}  {noms}")
        if ecartes:
            print(f"... {ecartes} older ones not listed")
        return 0
    if config.matrix is not None:
        cotes = [c for c in config.matrix.split(",") if c]
        try:
            table = matrix(
                racine, cotes or default_matrix_sides(racine), jobs=config.jobs
            )
        except ValueError as exc:
            print(f"ERROR: {exc}")
            return 2
        print("\n".join(render_matrix(table, show_all=config.all)))
        return 0
    return None


def _main_open(rapport, racine, choix, ouvrir):
    """Ouvre tig ou le graphe sur les projets que `choix` désigne ; une
    sortie en erreur arrête la suite. Rend un code de sortie."""
    lignes = select_rows(rapport, choix)
    if not lignes:
        print(f"ERROR: no changed project matches {choix}")
        return 2
    for ligne in lignes:
        if ouvrir(racine, ligne):
            break
    return 0


def main(argv=None):
    config = get_config(argv)
    racine = new_path
    code = _main_list(config, racine)
    if code is not None:
        return code
    if config.previous:
        paire = previous_freeze(racine)
        if not paire:
            print("Fewer than two commits froze a project.")
            return 1
        config.gauche, config.droite = paire
    try:
        rapport = build(racine, config.gauche, config.droite, jobs=config.jobs)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 2
    if config.fetch:
        restes = fetch_missing(racine, rapport["rows"], jobs=config.jobs)
        for chemin, shas in sorted(restes.items()):
            print(f"WARNING: still missing in {chemin}: {', '.join(shas)}")
    print("\n".join(render_summary(rapport, show_all=config.all)))
    if not config.summary:
        details = render_details(
            rapport,
            stat_count=config.stat_count,
            group_by=config.group_by,
            log=config.log,
        )
        print("\n".join(details + render_tip(rapport)))
    for choix, ouvrir in (
        (config.graph, open_graph),
        (config.tig, open_history),
    ):
        if choix:
            code = _main_open(rapport, racine, choix, ouvrir)
            if code:
                return code
    return 0


if __name__ == "__main__":
    sys.exit(main())
