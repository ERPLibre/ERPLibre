#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Pousser les dépôts du manifeste vers un remote choisi, en parallèle.

Les dépôts sont les clones des projets de la version d'Odoo active, lus
dans les mêmes fichiers que le gel (`git_freeze_manifest.freeze_sources`).
Le remote visé est un nom de remote des clones : celui du manifeste, un
autre déjà posé, ou un remote neuf que `poser_remote` ajoute à chaque clone
à partir d'une URL de base, « <base>/<propriétaire>/<dépôt> ». Le
propriétaire vient de l'URL « fetch » du remote du projet dans le
manifeste, son dernier segment, et le dépôt de son nom : la forge reçoit la
même arborescence que l'hôte d'origine.

Un remote ajouté porte un autre nom que ceux du manifeste : git-repo
réécrit l'URL des remotes qu'il connaît à chaque synchronisation, pas celle
des autres. Il ne reçoit pas de refspec de fetch utile et « skipFetchAll »
l'écarte de « git fetch --all » : on y pousse, on n'en tire pas.

Deux contenus se poussent :
  - `MODE_MANIFESTE`, le commit extrait (HEAD) sur la branche que suit le
    manifeste, débarrassée d'un suffixe daté « _maj_<AAAAMMJJ> » ;
  - `MODE_TOUT`, en plus, chaque branche locale, chaque branche de suivi du
    remote du manifeste et chaque étiquette.
Un push n'est jamais forcé : un distant qui porte des commits que le clone
n'a pas refuse la mise à jour, et le refus est rapporté. Un clone
superficiel se pousse tel quel, sauf s'il est approfondi d'abord
(`approfondir`) : beaucoup de serveurs refusent l'historique tronqué.
"""

import argparse
import concurrent.futures
import os
import re
import sys

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.append(new_path)

from script.git import (  # noqa: E402
    git_freeze_manifest,
    manifest_freeze,
    repo_upgrade,
)

MODE_MANIFESTE = "manifest"
MODE_TOUT = "all"
MODES = (MODE_MANIFESTE, MODE_TOUT)
PARALLELE = repo_upgrade.PARALLELE


def proprietaire_de(fetch):
    """Le dernier segment de chemin de l'URL `fetch` d'un remote : le
    propriétaire (organisation ou compte) des dépôts qu'il sert. None pour
    une URL sans chemin ou relative (« .. »)."""
    url = (fetch or "").strip().rstrip("/")
    m = re.match(r"^(?:[a-z+]+://[^/]+|[^@/:]+@[^/:]+:)(/?.*)$", url)
    if not m:
        return None
    segments = [s for s in m.group(1).split("/") if s]
    if not segments or segments[-1] in (".", ".."):
        return None
    return segments[-1]


def url_cible(base, proprietaire, nom):
    """« <base>/<proprietaire>/<nom>.git », sans « / » doublé."""
    nom = nom if nom.endswith(".git") else f"{nom}.git"
    return f"{base.rstrip('/')}/{proprietaire}/{nom}"


def projets_actifs(odoo_version=None):
    """Les projets clonés de la version d'Odoo active, triés par chemin.

    Chaque projet est un dict : « cle », « chemin », « nom », « remote »
    (celui du manifeste), « branche » (la branche suivie, sans suffixe
    daté, ou None) et « proprietaire » (voir `proprietaire_de`). Comme dans
    la fusion, la dernière définition d'un projet l'emporte. Les chemins
    sont relatifs à la racine du dépôt, où le répertoire courant doit se
    trouver ; un projet non cloné n'y figure pas.
    """
    portee = git_freeze_manifest.freeze_sources(odoo_version)
    lus = list(dict.fromkeys(git_freeze_manifest.default_sources() + portee))
    definitions = git_freeze_manifest.read_sources(lus)
    defaut = git_freeze_manifest.read_default(lus)
    fetch = git_freeze_manifest.read_remotes(lus)
    projets = []
    for cle, defs in definitions.items():
        if not any(f in portee for f, _ in defs):
            continue
        attrs = defs[-1][1]
        chemin = attrs.get("path") or attrs.get("name")
        if not chemin or not repo_upgrade.est_clone(chemin):
            continue
        remote = attrs.get("remote") or defaut.get("remote")
        branche = manifest_freeze.manifest_branch(
            attrs.get("revision") or defaut.get("revision"),
            attrs.get("upstream"),
            attrs.get("dest-branch"),
        )
        projets.append(
            {
                "cle": cle,
                "chemin": chemin,
                "nom": attrs.get("name"),
                "remote": remote,
                "branche": manifest_freeze.base_branch(branche),
                "proprietaire": proprietaire_de(fetch.get(remote)),
            }
        )
    return sorted(projets, key=lambda p: p["chemin"])


def _en_parallele(fonction, elements, jobs):
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        return list(pool.map(fonction, elements))


def remotes_des_clones(chemins, jobs=PARALLELE):
    """{nom de remote: nombre de clones qui le portent}."""

    def noms(chemin):
        out, _err, code = repo_upgrade.git(["remote"], chemin)
        return set() if code else set(out.split())

    compte = {}
    for ensemble in _en_parallele(noms, chemins, jobs):
        for nom in ensemble:
            compte[nom] = compte.get(nom, 0) + 1
    return dict(sorted(compte.items()))


def poser_remote(chemin, nom, url):
    """Pose le remote `nom` à `url` dans le clone. Rend (etat, url en place).

    `etat` vaut « ajoute », « present » (même dépôt au sens de
    `repo_upgrade.cle_url`), « autre_url » (le remote existe ailleurs : il
    n'est pas touché), « refuse » ou « non_clone ». Un remote ajouté ne
    porte pas d'étiquettes (« --no-tags ») et « skipFetchAll » l'écarte de
    « git fetch --all ».
    """
    if not repo_upgrade.est_clone(chemin):
        return "non_clone", None
    en_place = repo_upgrade.url_du_remote(chemin, nom)
    if en_place is not None:
        if repo_upgrade.cle_url(en_place) == repo_upgrade.cle_url(url):
            return "present", en_place
        return "autre_url", en_place
    _out, _err, code = repo_upgrade.git(
        ["remote", "add", "--no-tags", nom, url], chemin
    )
    if not code:
        _out, _err, code = repo_upgrade.git(
            ["config", f"remote.{nom}.skipFetchAll", "true"], chemin
        )
    return ("refuse" if code else "ajoute"), None


def plan_remote(projets, nom, base):
    """[(projet, url)] du remote `nom` à poser à partir de `base`, et les
    projets écartés faute de propriétaire connu : [(projet, motif)]."""
    poses, ecartes = [], []
    for p in projets:
        if not p["proprietaire"] or not p["nom"]:
            ecartes.append((p, "no owner in the manifest fetch URL"))
            continue
        poses.append((p, url_cible(base, p["proprietaire"], p["nom"])))
    return poses, ecartes


def _refs(chemin, motif):
    out, _err, code = repo_upgrade.git(
        ["for-each-ref", "--format=%(refname)", motif], chemin
    )
    return [] if code else out.split()


def refspecs(chemin, mode, remote_manifeste, branche):
    """Les refspecs à pousser pour `mode`, ou ([], motif).

    `MODE_MANIFESTE` : « HEAD:refs/heads/<branche> ». `MODE_TOUT` y
    ajoute chaque branche locale, chaque branche de suivi de
    `remote_manifeste` (sa référence symbolique HEAD exclue) et
    « refs/tags/*:refs/tags/* ». Une destination n'est poussée qu'une fois :
    HEAD l'emporte pour la branche du manifeste, puis la branche locale sur
    la branche de suivi homonyme.
    """
    cibles = {}
    if branche:
        cibles[f"refs/heads/{branche}"] = "HEAD"
    if mode == MODE_TOUT:
        for ref in _refs(chemin, "refs/heads/"):
            cibles.setdefault(ref, ref)
        if remote_manifeste:
            prefixe = f"refs/remotes/{remote_manifeste}/"
            for ref in _refs(chemin, prefixe):
                nom = ref[len(prefixe) :]
                if nom != "HEAD":
                    cibles.setdefault(f"refs/heads/{nom}", ref)
    if not cibles:
        return [], "no branch to push"
    specs = [f"{src}:{dst}" for dst, src in cibles.items()]
    if mode == MODE_TOUT:
        specs.append("refs/tags/*:refs/tags/*")
    return specs, None


def approfondir(chemin, remote_manifeste):
    """Rapatrie tout l'historique d'un clone superficiel depuis le remote
    du manifeste. Rend (code, erreur)."""
    _out, err, code = repo_upgrade.git(
        ["fetch", "--quiet", "--unshallow", "--no-tags", remote_manifeste],
        chemin,
        repo_upgrade.DELAI_APPROFONDIR,
    )
    return code, err.strip()


def pousser_un(chemin, remote, specs):
    """Pousse `specs` vers `remote`, sans force. Rend (code, erreur)."""
    _out, err, code = repo_upgrade.git(
        ["push", "--porcelain", remote, *specs], chemin
    )
    return code, err.strip()


def pousser_en_parallele(cibles, jobs=PARALLELE, suivi=None):
    """Pousse chaque cible, `jobs` à la fois. Rend les résultats dans
    l'ordre des cibles.

    Une cible est un dict « chemin », « remote », « specs » ; son résultat
    la complète de « code » et « erreur ». `suivi`, appelé avec chaque
    résultat dès qu'il arrive, sert à l'affichage d'avancement.
    """
    resultats = [None] * len(cibles)
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        futurs = {
            pool.submit(pousser_un, c["chemin"], c["remote"], c["specs"]): i
            for i, c in enumerate(cibles)
        }
        for futur in concurrent.futures.as_completed(futurs):
            i = futurs[futur]
            code, erreur = futur.result()
            resultats[i] = dict(cibles[i], code=code, erreur=erreur)
            if suivi:
                suivi(resultats[i])
    return resultats


def preparer_cibles(projets, remote, mode):
    """(cibles, écartés) : une cible par projet dont les refspecs se
    calculent, et [(projet, motif)] pour les autres."""
    cibles, ecartes = [], []
    for p in projets:
        specs, motif = refspecs(p["chemin"], mode, p["remote"], p["branche"])
        if motif:
            ecartes.append((p, motif))
            continue
        cibles.append(
            {"chemin": p["chemin"], "remote": remote, "specs": specs}
        )
    return cibles, ecartes


def get_config(argv=None):
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__.split("\n\n")[0],
    )
    parser.add_argument(
        "--remote",
        required=True,
        help="Name of the remote to push to, in every clone.",
    )
    parser.add_argument(
        "--url",
        help=(
            "Base URL of a forge: adds the remote as <url>/<owner>/<repo>"
            " to every clone that lacks it."
        ),
    )
    parser.add_argument(
        "--mode",
        choices=MODES,
        default=MODE_MANIFESTE,
        help=(
            "manifest: the checked-out commit on the manifest branch (default)."
            " all: also every branch and tag the clone knows."
        ),
    )
    parser.add_argument(
        "--unshallow",
        action="store_true",
        help="Fetch the full history of shallow clones before pushing.",
    )
    parser.add_argument("--jobs", type=int, default=PARALLELE)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the remotes and refspecs, push nothing.",
    )
    return parser.parse_args(argv)


def main(argv=None):
    config = get_config(argv)
    os.chdir(new_path)
    projets = projets_actifs()
    if not projets:
        print("ERROR: no cloned project for the active Odoo version.")
        return 1
    if config.url:
        poses, sans = plan_remote(projets, config.remote, config.url)
        for p, motif in sans:
            print(f"  - {p['chemin']}: {motif}")
        etats = {}
        for p, url in poses:
            etat = (
                ("plan", None)
                if config.dry_run
                else poser_remote(p["chemin"], config.remote, url)
            )
            etats.setdefault(etat[0], []).append(p["chemin"])
            if etat[0] in ("autre_url", "refuse"):
                print(f"  ! {p['chemin']}: remote {config.remote} {etat[0]}")
        print(
            "Remote "
            + config.remote
            + ": "
            + ", ".join(f"{len(v)} {k}" for k, v in sorted(etats.items()))
        )
    if config.unshallow and not config.dry_run:
        for p in projets:
            if repo_upgrade.est_superficiel(p["chemin"]):
                code, err = approfondir(p["chemin"], p["remote"])
                if code:
                    print(f"  ! {p['chemin']}: unshallow failed: {err[-300:]}")
    cibles, ecartes = preparer_cibles(projets, config.remote, config.mode)
    for p, motif in ecartes:
        print(f"  - {p['chemin']}: {motif}")
    if config.dry_run:
        for c in cibles:
            print(f"  {c['chemin']} → {c['remote']}: {' '.join(c['specs'])}")
        print(f"Push: {len(cibles)} repositories would be pushed.")
        return 0

    def suivi(r):
        etat = "ok" if not r["code"] else "FAILED"
        print(f"  [{etat}] {r['chemin']}", flush=True)

    resultats = pousser_en_parallele(cibles, config.jobs, suivi)
    echecs = [r for r in resultats if r["code"]]
    print(
        f"Push: {len(resultats) - len(echecs)} pushed, {len(echecs)} failed,"
        f" {len(ecartes)} skipped."
    )
    for r in echecs:
        print(f"  - {r['chemin']}: {r['erreur'][-300:]}")
    return 1 if echecs else 0


if __name__ == "__main__":
    sys.exit(main())
