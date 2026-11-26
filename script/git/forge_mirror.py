#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Les miroirs natifs d'une forge Forgejo qui suivent l'origine de chaque
dépôt, et la configuration du minuteur qui en avance les dépôts de travail.

Chaque dépôt « <propriétaire>/<dépôt> » de la forge, celui qui reçoit les
pushes et les pull requests, a pour miroir « <propriétaire>-mirror/<dépôt> »
: une organisation privée par propriétaire d'origine, le nom du dépôt
inchangé. Un miroir est en lecture seule — la forge refuse tout push et
toute pull request — d'où un espace de noms à part, disjoint de tous les
propriétaires connus sans égard à la casse, comme Forgejo compare les noms.

L'origine d'un dépôt est le remote du manifeste qui le sert, c'est-à-dire
le fork sur GitHub, et non l'amont de ce fork : la mise à niveau des forks
publie sur ce fork, et le dépôt de la forge en a reçu la même branche. Les
surcouches de forge (`forge_manifest`) sont écartées de la lecture : elles
redirigent ces remotes vers la forge elle-même.

Seule une origine qui se lit anonymement en https se suit : la forge la
clone sans identifiants, et aucun jeton GitHub n'entre dans la forge.

Le module ne fait aucun appel réseau, sauf `origine_publique`.
"""

import os
import re
import subprocess
import sys

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
if new_path not in sys.path:
    sys.path.append(new_path)

from script.git import forgejo_client, git_freeze_manifest  # noqa: E402
from script.git import github_fork, push_remote, repo_upgrade  # noqa: E402

SUFFIXE = "-mirror"
INTERVALLE_DEFAUT = "1h"
# Le plancher par défaut de Forgejo ([mirror] MIN_INTERVAL) : un intervalle
# plus court est refusé par la migration.
INTERVALLE_MIN = 10 * 60
_INTERVALLE = re.compile(r"^(?:(\d+)h)?(?:(\d+)m)?$")
_SCHEMA = re.compile(r"^(?:[a-z][a-z0-9+.-]*://|[^@/:\s]+@[^/:\s]+:)", re.I)
_SURCOUCHE = re.compile(r"^git_manifest_forge_.+\.xml$")
DELAI_ORIGINE = 60


def organisation_miroir(proprietaire, interdits=()):
    """(nom, "") de l'organisation des miroirs de `proprietaire`, ou
    (None, motif) : « no owner », « owner already ends in -mirror » (le
    minuteur refuse un dépôt de travail dont le propriétaire porte
    `SUFFIXE`, et toute la configuration avec lui), « name refused by
    Forgejo » (plus de 40 caractères, séparateur doublé) ou « collides
    with an owner » quand le nom, en minuscules, est l'un des
    `interdits`."""
    if not proprietaire:
        return None, "no owner"
    if proprietaire.lower().endswith(SUFFIXE):
        return None, "owner already ends in -mirror"
    nom = proprietaire + SUFFIXE
    if not forgejo_client.nom_organisation_valide(nom):
        return None, "name refused by Forgejo"
    if nom.lower() in {i.lower() for i in interdits if i}:
        return None, "collides with an owner"
    return nom, ""


def intervalle_valide(texte):
    """Vrai pour une durée Go en heures et minutes (« 1h », « 30m »,
    « 1h30m ») d'au moins `INTERVALLE_MIN` secondes."""
    m = _INTERVALLE.match(texte or "")
    if not m or not (m.group(1) or m.group(2)):
        return False
    secondes = int(m.group(1) or 0) * 3600 + int(m.group(2) or 0) * 60
    return secondes >= INTERVALLE_MIN


def url_du_projet(fetch, nom):
    """L'URL du dépôt `nom` d'un remote de `fetch`, jointe comme git-repo
    la joint (« fetch » sans « / » final, « / », nom), ou None pour un
    fetch vide ou relatif (sans schéma ni forme « user@hôte: »)."""
    fetch = (fetch or "").strip()
    if not fetch or not nom or not _SCHEMA.match(fetch):
        return None
    return f"{fetch.rstrip('/')}/{nom}"


def url_origine(url):
    """L'URL https anonyme que la forge peut cloner pour `url`, ou None.
    Un dépôt GitHub, en https ou en ssh, devient
    « https://github.com/<o>/<r>.git » ; une autre URL https garde son
    hôte et son chemin, sans identifiants ; ssh hors de GitHub, file://,
    chemin relatif et None rendent None."""
    url = (url or "").strip()
    depot = github_fork.depot_github(url)
    if depot:
        return f"https://github.com/{depot[0]}/{depot[1]}.git"
    m = re.match(r"^https://(?:[^@/]+@)?([^/@\s]+)(/\S+)$", url)
    if not m:
        return None
    return f"https://{m.group(1)}{m.group(2)}"


def meme_origine(a, b):
    """Vrai quand `a` et `b` visent le même dépôt (`repo_upgrade.cle_url`,
    chemin en minuscules) : « .git », « / » final, identifiants et casse
    de l'hôte ne comptent pas."""
    if not a or not b:
        return False

    def cle(url):
        c = repo_upgrade.cle_url(url)
        return (c[0], c[1].lower()) if isinstance(c, tuple) else c

    return cle(a) == cle(b)


def qualifier(depot, origine):
    """La nature d'un dépôt déjà présent là où un miroir est attendu :
    « pas_miroir » (un dépôt ordinaire), « autre_origine » (le miroir d'une
    autre URL), « en_cours » (vide : la migration se poursuit) ou
    « existant »."""
    if not depot.get("mirror"):
        return "pas_miroir"
    if not meme_origine(depot.get("original_url"), origine):
        return "autre_origine"
    if depot.get("empty"):
        return "en_cours"
    return "existant"


def sans_surcouches(sources):
    """`sources` sans les surcouches de forge de `private/manifest/`."""
    dossier = os.path.normpath(git_freeze_manifest.PRIVATE_MANIFEST_DIR)

    def surcouche(chemin):
        chemin = os.path.normpath(chemin)
        parent = os.path.dirname(chemin)
        return _SURCOUCHE.match(os.path.basename(chemin)) and (
            parent == dossier or parent.endswith(os.sep + dossier)
        )

    return [s for s in sources if not surcouche(s)]


def remotes_d_origine(odoo_version=None):
    """{remote: fetch} des fichiers que lit `push_remote.projets_actifs`,
    sans les surcouches de forge : le fetch d'origine de chaque remote.
    Chemins relatifs : le dossier courant doit être la racine."""
    lus = list(
        dict.fromkeys(
            git_freeze_manifest.default_sources()
            + git_freeze_manifest.freeze_sources(odoo_version)
        )
    )
    return git_freeze_manifest.read_remotes(sans_surcouches(lus))


def proprietaires_connus(remotes):
    """Le propriétaire (`push_remote.proprietaire_de`) de chaque remote de
    `remotes`, cloné ou non : tout propriétaire qu'un push pourrait
    créer sur la forge."""
    return {
        p
        for p in (push_remote.proprietaire_de(f) for f in remotes.values())
        if p
    }


def _sans_git(nom):
    return nom[: -len(".git")] if nom.endswith(".git") else nom


def plan_miroirs(projets, remotes, interdits):
    """(paires, écartés) des miroirs de `projets` : des dicts de
    `projets_actifs`, ou celui de la racine, qui porte déjà « origine » et
    « branches ».

    Une paire : « projet », « depot » (« <propriétaire>/<dépôt> »),
    « miroir » (« <propriétaire>-mirror/<dépôt> »), « origine » (l'URL
    https anonyme) et « branches » ({travail, miroir, creer}). Sans
    branches données, la branche du manifeste se suit sous son nom, sans
    être créée. Deux projets du même dépôt, sans égard à la casse, font
    une paire, leurs branches réunies sans « travail » doublé. Un écarté
    est (projet, motif)."""
    paires, ecartes, index = [], [], {}
    for p in projets:
        nom = _sans_git(p.get("nom") or "")
        if not forgejo_client.nom_depot_valide(nom):
            ecartes.append((p, "invalid repository name"))
            continue
        origine = p.get("origine") or url_origine(
            url_du_projet(remotes.get(p.get("remote")), p.get("nom"))
        )
        if not origine:
            ecartes.append((p, "no https origin"))
            continue
        org, motif = organisation_miroir(p.get("proprietaire"), interdits)
        if not org:
            ecartes.append((p, motif))
            continue
        branches = p.get("branches") or (
            [{"travail": p["branche"], "miroir": p["branche"], "creer": False}]
            if p.get("branche")
            else None
        )
        if not branches:
            ecartes.append((p, "no branch"))
            continue
        depot = f"{p['proprietaire']}/{nom}"
        deja = index.get(depot.lower())
        if deja is not None:
            vues = {b["travail"] for b in deja["branches"]}
            deja["branches"] += [
                dict(b) for b in branches if b["travail"] not in vues
            ]
            continue
        paire = {
            "projet": p,
            "depot": depot,
            "miroir": f"{org}/{nom}",
            "origine": origine,
            "branches": [dict(b) for b in branches],
        }
        index[depot.lower()] = paire
        paires.append(paire)
    return paires, ecartes


def config_synchro(paires):
    """La configuration du minuteur pour `paires` : ni projet, ni origine,
    ni forge, ni compte, que l'hôte de la forge lit chez lui."""
    return {
        "version": 1,
        "paires": [
            {
                "depot": p["depot"],
                "miroir": p["miroir"],
                "branches": [
                    {
                        "travail": b["travail"],
                        "miroir": b["miroir"],
                        "creer": bool(b.get("creer")),
                    }
                    for b in p["branches"]
                ],
            }
            for p in paires
        ],
    }


def origine_publique(url, delai=DELAI_ORIGINE):
    """Vrai quand `url` se lit sans identifiants (« git ls-remote » de
    HEAD). Ni la configuration git de l'utilisateur ni ses gestionnaires
    d'identifiants ne s'appliquent, et aucune invite n'est possible : un
    dépôt privé échoue comme il échouerait pour la forge."""
    env = dict(
        repo_upgrade.env_sans_invite(),
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_ASKPASS="true",
        SSH_ASKPASS="true",
    )
    try:
        fini = subprocess.run(
            [
                "git",
                "-c",
                "credential.helper=",
                "ls-remote",
                "--exit-code",
                url,
                "HEAD",
            ],
            capture_output=True,
            text=True,
            timeout=delai,
            env=env,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return fini.returncode == 0


def resume_etat(etat, libelle=str, depuis="since"):
    """Les lignes d'un état de passe (`forge_sync.passe`) : la date, le
    décompte par état, puis une ligne par résultat qui n'est ni « a_jour »
    ni « avance » : « <depot> <branche>: <etat> <detail> (<depuis>
    <date>) ». `libelle(etat)` rend le libellé d'un état, l'identifiant
    lui-même par défaut ; `depuis` précède la date d'une divergence."""
    if not etat:
        return []
    resultats = etat.get("resultats") or []
    compte = {}
    for r in resultats:
        compte[r.get("etat")] = compte.get(r.get("etat"), 0) + 1
    lignes = [
        f"{etat.get('debut', '?')} → {etat.get('fin', '?')}",
        ", ".join(f"{n} {libelle(e)}" for e, n in sorted(compte.items()))
        or "-",
    ]
    for r in resultats:
        if r.get("etat") in ("a_jour", "avance"):
            continue
        ligne = (
            f"{r.get('depot')} {r.get('branche')}: {libelle(r.get('etat'))}"
        )
        if r.get("detail"):
            ligne += f" {r['detail']}"
        if r.get("depuis"):
            ligne += f" ({depuis} {r['depuis']})"
        lignes.append(ligne)
    return lignes
