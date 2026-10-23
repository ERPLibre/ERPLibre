#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Tirer le code déployé : un « git pull » de chaque dépôt, épinglé.

Deux modes
----------
- « branche » : chaque clone tire la branche qu'il suit (« @{u} ») ; sans
  elle, le remote et la branche que le manifeste local lui donne. Une HEAD
  détachée est sautée. La racine ERPLibre est un dépôt de plus, le premier.
- « manifeste » : la racine ERPLibre tire sa branche suivie, puis le
  manifeste local est régénéré par `git_merge_repo_manifest.py`, gelé ou non
  comme il l'est déjà, et chaque clone intègre la cible de sa nouvelle
  entrée, détaché ou non. Un clone détaché sans commit à lui — rien que
  « --remotes » ne contienne déjà — passe sur sa cible par « checkout
  --detach » (« bascule »), comme « repo sync » : un rebase rejouerait
  l'historique amont de son ancienne ligne sur la nouvelle.

La passe
--------
Récupération, essai à sec (JSON), application épinglée, enregistrement.
L'essai à sec ne fait que des « fetch » : aucune branche locale, aucune
HEAD, aucun arbre de travail ne bouge. L'application refait l'essai à sec
et n'écrit rien si la liste consentie ou un commit épinglé (« --expect
CHEMIN=CIBLE:HEAD ») a changé : elle n'intègre jamais une cible que
personne n'a vue.

Avant tout déplacement, une branche « <branche>_avant_pull_<horodatage> »
est posée sur HEAD : une référence seulement, sans checkout. Un arbre aux
fichiers suivis modifiés est mis de côté (« stash »), tiré, puis réappliqué ;
un « stash pop » qui bute remet l'arbre sur le commit tiré et garde le
stash, désigné par son commit. Un « stash push » qui ne crée aucune entrée
alors que l'arbre reste modifié (un sous-module déplacé, que le stash ne
sait pas garder) refuse le dépôt : « refs/stash » désignerait encore une
entrée plus ancienne, sans rapport. Un conflit de rebase ou de fusion est
abandonné et le dépôt revient sur son commit de départ (« conflit_annule »),
stash réappliqué : un arbre en conflit est du code que le serveur
chargerait. Les autres dépôts continuent.

Un fichier ignoré dont la cible fait un fichier suivi serait écrasé sans
avertissement par git : l'essai à sec le liste (« ecrases ») et la passe le
copie d'abord dans son dossier, puis le remet en place si le dépôt revient
à son départ.

Échéance
--------
« --budget SECONDES » borne la passe : passé ce délai, aucun dépôt, aucun
palier d'approfondissement, aucun clonage ni aucune installation ne
commence plus (« saute_delai »), et ce qui tourne finit dans son propre
délai. Celui qui lance la passe avec un délai à lui donne un budget plus
court, et l'enregistrement de la passe s'écrit après chaque dépôt : un
processus tué laisse la trace de ce qu'il a déjà fait. Les commandes
longues (« repo sync », fusion des manifestes, « poetry install ») tournent
dans leur propre groupe de processus, tué en entier quand leur délai expire.

Clone superficiel
-----------------
La récupération d'un clone superficiel passe « --shallow-since » à la date
de sa frontière la plus ancienne moins MARGE_FRONTIERE, jamais
« --depth » : « --depth » sur les références du clone raccourcit
l'historique visible de HEAD, et un fetch sans borne d'un clone divergé
télécharge tout l'historique de la cible. La borne marque frontière tout
commit dont un parent lui est antérieur, ce qui cache ses autres parents :
une frontière nouvelle posée dans l'historique de HEAD est retirée du
fichier « shallow » (ses parents sont dans le clone), et une frontière
nouvelle de la cible, plus récente que la borne, est repoussée par
« --deepen=1 », RACCORDS_MAX fois au plus — la fusion d'une vieille
branche ne cache plus une avance rapide.
Quand aucune base commune sûre n'apparaît, l'essai à sec l'annonce
(« superficiel ») et l'application n'approfondit que sur consentement
(« --approve-deepen ») : « --deepen » par paliers doublés jusqu'à
`git_freeze_manifest.PROFONDEUR_MAX`, avec « --no-tags », sans quoi le
suivi automatique des tags lance un second fetch qui bute sur « shallow
file has changed since we read it ».

Nouveaux dépôts du manifeste
----------------------------
Un projet du manifeste régénéré qui n'est pas cloné se clone par un
« repo sync » restreint à ses chemins, jamais par « git clone » : les clones
de git-repo ont un « .git » qui pointe dans « .repo/projects/ », et un
« .git/ » ordinaire fait échouer le « repo sync » suivant sur ce projet.
« repo sync » supprime aussi les arbres des projets sortis du manifeste,
même avec des chemins en argument : il n'est pas appelé quand
« .repo/project.list » nomme un chemin que « repo list -p » ne connaît
plus.

Rien n'est jamais poussé.

Un tag du manifeste se récupère sous « refs/repo_pull/tags/<t> », jamais
sur « refs/tags/<t> » : l'essai à sec ne déplace pas un tag local du même
nom.

Codes de sortie : 0 la commande a tourné (les refus par dépôt sont dans
« resultats ») ; 1 erreur interne ; 2 usage (version retapée fausse,
épingle illisible, nom de sauvegarde refusé, horodatage déjà pris) ;
3 chemin inconnu ou sauvegarde absente ; 4 plan changé, rien n'est écrit ;
5 une autre passe tient le verrou ; 6 « poetry install » a échoué.
"""

from __future__ import annotations

import contextlib
import datetime
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import traceback
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
)

from script.git import (  # noqa: E402
    git_freeze_manifest,
    manifest_freeze,
    repo_apply,
    repo_state,
    repo_upgrade,
)
from script.git.repo_upgrade import (  # noqa: E402
    DELAI_GIT,
    PARALLELE,
    REPO_ROOT,
    paint,
    t,
)

SCHEMA = 1

# Les enregistrements de passe, sous « tasks/ », qui n'est pas versionné.
DOSSIER_PASSES = os.path.join("tasks", "git_repo_pull")
FICHIER_VERROU = ".verrou"
MOTIF_SAUVEGARDE = re.compile(
    r"^(?P<branche>.+)_avant_pull_(?P<horodatage>\d{8}T\d{4})$"
)
MOTIF_HORODATAGE = re.compile(r"^\d{8}T\d{4}$")
MAX_ENTRANTS = 50
MAX_SORTIE = 4000
MODES = ("branche", "manifeste")
STRATEGIES = ("rebase", "ff", "merge")

EXIT_OK = 0
EXIT_INTERNE = 1
EXIT_USAGE = repo_apply.EXIT_USAGE
EXIT_CIBLE = 3
EXIT_PLAN_CHANGE = repo_apply.EXIT_PLAN_CHANGE
EXIT_OCCUPE = 5
EXIT_DEPS = 6

REPO_BIN = os.path.join(".venv.erplibre", "bin", "repo")
PYTHON_ERPLIBRE = os.path.join(".venv.erplibre", "bin", "python")
SCRIPT_FUSION = os.path.join("script", "git", "git_merge_repo_manifest.py")
DELAI_SYNC = 3600
DELAI_DEPS = 3600

# La marge (secondes) sous la plus ancienne frontière d'un clone
# superficiel : un commit daté un peu avant son parent, horloge décalée,
# reste au-dessus de la borne.
MARGE_FRONTIERE = 3600
# Les « --deepen=1 » qui repoussent une frontière nouvelle de la cible.
RACCORDS_MAX = 4
# L'espace où se récupère un tag du manifeste, hors de « refs/tags/ ».
ESPACE_TAGS = "refs/repo_pull/tags/"
MOTIF_DELAI = "time budget exhausted"

# Les verdicts de l'essai à sec, par dépôt.
VERDICTS = (
    "a_jour",
    "en_avance",
    "avance_rapide",
    "diverge",
    "bascule",
    "superficiel",
    "detache",
    "sans_cible",
    "cible_absente",
    "fetch_echoue",
    "operation_en_cours",
    "absent",
    "erreur",
)

# Les états d'un dépôt après l'application, d'un clone, d'un retour.
ETATS = (
    "avance",
    "tire",
    "a_jour",
    "conflit_annule",
    "stash_garde",
    "refuse_ff",
    "saute_detache",
    "saute_superficiel",
    "saute_operation",
    "superficiel_sans_base",
    "sauvegarde_existante",
    "restauration_echouee",
    "erreur",
    "clone",
    "clone_echoue",
    "clone_refuse",
    "clone_chemin_occupe",
    "revenu",
    "refuse_sale",
    "branche_changee",
    "head_deplacee",
    "sauvegarde_absente",
    "supprime",
    "refuse_courante",
    "saute_delai",
)

# Les états où HEAD a bougé : la sauvegarde y reste.
ETATS_DEPLACES = ("avance", "tire", "stash_garde")

# Les fichiers du dépôt ERPLibre qui décrivent les dépendances Python.
FICHIERS_DEPENDANCES_FIXES = (
    "pyproject.toml",
    "poetry.lock",
    "requirement/erplibre_require-ments.txt",
    "conf/supported_version_erplibre.json",
)

# Les fichiers vivants, non suivis, que la fusion des manifestes lit en plus
# de « manifest/ » et « conf/ ».
ENTREES_VIVES = (
    ".odoo-version",
    ".erplibre-state.json",
    os.path.join(".repo", "installed_odoo_version.txt"),
    os.path.join("private", "default_git_manifest.csv"),
)
DOSSIER_MOBILE = os.path.join("mobile", "erplibre_home_mobile")


class Occupe(Exception):
    """Une autre passe tient le verrou du checkout."""


# ── petits outils ───────────────────────────────────────────────────────


def git(args, dossier, delai=DELAI_GIT, ecrit=False):
    """(sortie, erreur, code) de `repo_state.git`, qui ne lève jamais.

    `ecrit` marque une commande qui écrit : l'éditeur devient « true » et
    l'entrée standard est vide, si bien qu'une question de git échoue
    aussitôt au lieu d'attendre un terminal.
    """
    if ecrit:
        return repo_state.git(
            ["-c", "core.editor=true", *args], dossier, delai, entree=""
        )
    return repo_state.git(args, dossier, delai)


def sans_secrets(texte):
    """`texte` dont chaque URL a perdu ce qui peut porter un secret."""
    return re.sub(
        r"[a-zA-Z][a-zA-Z0-9+.-]*://\S+",
        lambda m: repo_state.sans_identifiants(m.group(0)),
        texte or "",
    )


def premiere_ligne(err, code):
    return sans_secrets(repo_state.erreur_git(err, code))


def queue(texte):
    """La fin de `texte`, bornée à MAX_SORTIE caractères."""
    texte = sans_secrets((texte or "").strip())
    return texte[-MAX_SORTIE:]


def joindre(*morceaux):
    return "\n".join(x.strip() for x in morceaux if x and x.strip())


def maintenant_horodatage():
    return datetime.datetime.now().strftime("%Y%m%dT%H%M")


def echeance_de(budget):
    """L'échéance (« time.monotonic ») d'un budget en secondes, ou None."""
    return time.monotonic() + budget if budget else None


def echue(echeance):
    """Vrai quand l'échéance `echeance` (None : aucune) est passée."""
    return echeance is not None and time.monotonic() >= echeance


def borne(delai, echeance):
    """`delai` borné au temps qui reste avant `echeance`, 1 s au moins."""
    if echeance is None:
        return delai
    return max(1, min(delai, int(echeance - time.monotonic())))


def lancer(argv, delai, cwd, env, en_direct=False):
    """(code, sortie) d'une commande longue, lancée dans son propre groupe
    de processus.

    Le délai expiré tue le groupe entier : les processus git qu'un
    « repo sync » ou un « poetry install » lancent ne lui survivent pas.
    `en_direct` laisse la sortie au terminal (la sortie rendue est alors
    vide). Une commande qui ne démarre pas rend le code 1 et son motif ;
    un délai expiré, le code 124.
    """
    sortie = None if en_direct else subprocess.PIPE
    try:
        proc = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=sortie,
            stderr=subprocess.STDOUT if sortie else None,
            text=True,
            errors="replace",
            start_new_session=True,
        )
    except OSError as exc:
        return 1, str(exc)
    try:
        out, _err = proc.communicate(timeout=delai)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(OSError):
            os.killpg(proc.pid, signal.SIGKILL)
        out, _err = proc.communicate()
        return 124, joindre(out or "", f"timeout after {delai}s")
    return proc.returncode, out or ""


def nom_sauvegarde(branche, horodatage):
    """« <branche>_avant_pull_<horodatage> »."""
    return f"{branche}_avant_pull_{horodatage}"


def branche_de_sauvegarde(branche, attrs):
    """La branche qui nomme la sauvegarde : la branche extraite, sinon celle
    que le manifeste donne au projet, sinon « detache »."""
    if branche:
        return branche
    attrs = attrs or {}
    revision = attrs.get("revision")
    if revision and revision.startswith("refs/heads/"):
        revision = revision[len("refs/heads/") :]
    if revision and revision.startswith("refs/tags/"):
        revision = None
    nom = manifest_freeze.manifest_branch(
        revision, attrs.get("upstream"), attrs.get("dest-branch")
    )
    return nom or "detache"


def operation_en_cours(dossier):
    """Le nom de l'opération git interrompue dans ce dépôt, ou None."""
    if repo_apply.rebase_en_cours(dossier):
        return "rebase"
    for fichier, nom in (
        ("MERGE_HEAD", "merge"),
        ("CHERRY_PICK_HEAD", "cherry-pick"),
        ("REVERT_HEAD", "revert"),
    ):
        out, _err, code = git(["rev-parse", "--git-path", fichier], dossier)
        if code == 0 and os.path.exists(os.path.join(dossier, out.strip())):
            return nom
    return None


def etat_arbre(dossier, delai=DELAI_GIT):
    """(sale, non suivis) : des fichiers suivis modifiés ?, et le nombre de
    fichiers non suivis que rien n'ignore. (None, 0) si git refuse.

    Le contenu modifié d'un sous-module ne compte pas : le tirage du dépôt
    ne touche pas son arbre, et « git stash » ne le garde pas."""
    out, _err, code = git(
        [
            "status",
            "--porcelain",
            "--untracked-files=normal",
            "--ignore-submodules=dirty",
        ],
        dossier,
        delai,
    )
    if code:
        return None, 0
    lignes = [x for x in out.splitlines() if x.strip()]
    hors = [x for x in lignes if x.startswith("??")]
    return len(lignes) > len(hors), len(hors)


def config(dossier, cle):
    out, _err, code = git(["config", "--get", cle], dossier)
    return out.strip() if code == 0 and out.strip() else None


def lire_carte(chemin_xml):
    """{chemin: (nom, remote, revision, upstream, dest-branch)} d'un
    manifeste, les valeurs de « <default> » appliquées ; None illisible."""
    try:
        racine = ET.parse(chemin_xml).getroot()
    except (OSError, ET.ParseError):
        return None
    defaut = racine.find("default")
    defaut = dict(defaut.attrib) if defaut is not None else {}
    carte = {}
    for projet in racine.findall("project"):
        a = projet.attrib
        carte[a.get("path") or a.get("name")] = (
            a.get("name"),
            a.get("remote") or defaut.get("remote"),
            a.get("revision") or defaut.get("revision"),
            a.get("upstream"),
            a.get("dest-branch"),
        )
    return carte


def lire_projets(chemin_xml):
    """(remotes {nom: fetch}, {chemin: attributs}) d'un manifeste, les
    valeurs « remote » et « revision » de « <default> » appliquées."""
    racine = ET.parse(chemin_xml).getroot()
    remotes = {e.get("name"): e.get("fetch") for e in racine.findall("remote")}
    defaut = racine.find("default")
    defaut = dict(defaut.attrib) if defaut is not None else {}
    projets = {}
    for projet in racine.findall("project"):
        attrs = dict(projet.attrib)
        for cle in ("remote", "revision"):
            if cle in defaut:
                attrs.setdefault(cle, defaut[cle])
        projets[repo_state.chemin_projet(attrs)] = attrs
    return remotes, projets


def _liste(carte):
    return {k: list(v) for k, v in (carte or {}).items()}


# ── verrou et enregistrement ────────────────────────────────────────────


def dossier_passes(racine):
    return os.path.join(racine, DOSSIER_PASSES)


def dossier_passe(horodatage, racine=REPO_ROOT):
    return os.path.join(dossier_passes(racine), horodatage)


@contextlib.contextmanager
def verrou(racine):
    """Le verrou du checkout, non bloquant : lève Occupe s'il est pris.

    « fcntl.flock » sur `DOSSIER_PASSES`/.verrou. Le noyau le relâche à la
    fermeture du fichier, y compris quand le processus meurt.
    """
    import fcntl

    os.makedirs(dossier_passes(racine), exist_ok=True)
    fh = open(os.path.join(dossier_passes(racine), FICHIER_VERROU), "a+")
    try:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise Occupe(str(exc)) from exc
        yield
    finally:
        fh.close()


def _ecrire_json(chemin, charge):
    temporaire = chemin + ".tmp"
    with open(temporaire, "w") as fh:
        json.dump(charge, fh, indent=2, ensure_ascii=False, default=sorted)
    os.replace(temporaire, chemin)


def ecrire_passe(dossier, charge):
    """Inscrit `charge` dans `dossier`/passe.json et la sortie git de chaque
    dépôt dans « <chemin, / devenu _>.log ». Rend `dossier`."""
    os.makedirs(dossier, exist_ok=True)
    _ecrire_json(os.path.join(dossier, "passe.json"), charge)
    for res in (charge.get("resultats") or []) + (charge.get("clones") or []):
        if not res.get("sortie"):
            continue
        nom = (res.get("chemin") or "inconnu").replace("/", "_") + ".log"
        if nom == "..log":
            nom = "racine.log"
        with open(os.path.join(dossier, nom), "w") as fh:
            fh.write(res["sortie"] + "\n")
    return dossier


def passes(racine=REPO_ROOT):
    """Les horodatages des passes enregistrées, la plus récente d'abord."""
    dossier = dossier_passes(racine)
    if not os.path.isdir(dossier):
        return []
    return sorted(
        (
            x
            for x in os.listdir(dossier)
            if os.path.isfile(os.path.join(dossier, x, "passe.json"))
        ),
        reverse=True,
    )


def lire_passe(horodatage=None, racine=REPO_ROOT):
    """La passe demandée, ou la dernière. None s'il n'y en a aucune."""
    if horodatage is None:
        lst = passes(racine)
        if not lst:
            return None
        horodatage = lst[0]
    if not MOTIF_HORODATAGE.match(horodatage or ""):
        return None
    try:
        with open(
            os.path.join(dossier_passe(horodatage, racine), "passe.json")
        ) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


# ── cibles ──────────────────────────────────────────────────────────────


def cible_suivie(dossier, branche, attrs):
    """La cible d'un dépôt sur une branche, en mode « branche ».

    dict : « remote », « cible » (la référence), « refspec » (None quand
    rien ne se récupère), « source_cible », ou « motif » seul quand le
    dépôt n'a pas de cible. La branche suivie (« @{u} ») l'emporte ; à
    défaut, le remote et la branche que le manifeste donne au chemin.
    """
    out, _err, code = git(
        ["rev-parse", "--symbolic-full-name", "@{u}"], dossier
    )
    suivie = out.strip() if code == 0 else ""
    if suivie:
        remote = config(dossier, f"branch.{branche}.remote")
        merge = config(dossier, f"branch.{branche}.merge")
        if remote == "." or not remote or not merge:
            return {
                "remote": remote,
                "cible": suivie,
                "refspec": None,
                "source_cible": "suivi",
            }
        return {
            "remote": remote,
            "cible": suivie,
            "refspec": f"+{merge}:{suivie}",
            "source_cible": "suivi",
        }
    if not attrs:
        return {"motif": "no tracked branch and no manifest entry"}
    nom = branche_de_sauvegarde(None, attrs)
    remote = attrs.get("remote")
    if nom == "detache" or not remote:
        return {"motif": "no tracked branch and no branch in the manifest"}
    if not config(dossier, f"remote.{remote}.url"):
        return {"motif": f"remote {remote} is not configured in the clone"}
    cible = f"refs/remotes/{remote}/{nom}"
    return {
        "remote": remote,
        "cible": cible,
        "refspec": f"+refs/heads/{nom}:{cible}",
        "source_cible": "manifeste",
    }


def cible_du_manifeste(dossier, attrs):
    """La cible d'un clone en mode « manifeste », de son entrée `attrs`.

    Une « revision » branche vise « refs/remotes/<remote>/<branche> » ; un
    commit (gelé) se vise lui-même, la récupération apportant sa branche ;
    un tag se récupère sous « ESPACE_TAGS<t> », qu'un tag local du même nom
    ne partage pas. Même forme que `cible_suivie`.
    """
    revision = attrs.get("revision")
    remote = attrs.get("remote")
    if not revision or not remote:
        return {"motif": "no revision or remote in the manifest"}
    if not config(dossier, f"remote.{remote}.url"):
        return {"motif": f"remote {remote} is not configured in the clone"}
    base = {"remote": remote, "source_cible": "manifeste_regenere"}
    if manifest_freeze.is_sha(revision):
        nom = manifest_freeze.manifest_branch(
            revision, attrs.get("upstream"), attrs.get("dest-branch")
        )
        refspec = None
        if nom:
            refspec = f"+refs/heads/{nom}:refs/remotes/{remote}/{nom}"
        return dict(base, cible=revision, refspec=refspec)
    if revision.startswith("refs/tags/"):
        prive = ESPACE_TAGS + revision[len("refs/tags/") :]
        return dict(base, cible=prive, refspec=f"+{revision}:{prive}")
    cible = repo_state.ref_cible(attrs)
    nom = cible[len(f"refs/remotes/{remote}/") :]
    return dict(base, cible=cible, refspec=f"+refs/heads/{nom}:{cible}")


def date_frontiere(dossier, visibles=None):
    """La plus ancienne date de commit (secondes) des frontières de
    l'historique de HEAD d'un clone superficiel, ou None.

    `visibles` est l'ensemble des commits que « rev-list HEAD » atteint. Une
    frontière posée sur une autre référence — la vieille branche qu'une
    cible fusionne — ne fixe pas la borne : sa date tirerait toute
    l'histoire intermédiaire. Sans frontière sur HEAD, toutes comptent.
    """
    frontieres = git_freeze_manifest._frontieres(dossier)
    if not frontieres:
        return None
    frontieres = (frontieres & (visibles or set())) or frontieres
    out, _err, code = git(
        ["show", "-s", "--format=%ct", *sorted(frontieres)], dossier
    )
    dates = [int(x) for x in out.split() if x.isdigit()]
    return min(dates) if code == 0 and dates else None


def fichier_shallow(dossier):
    """Le chemin du fichier « shallow » du clone, ou None."""
    out, _err, code = git(["rev-parse", "--git-path", "shallow"], dossier)
    if code or not out.strip():
        return None
    return os.path.join(dossier, out.strip())


def instantane(dossier, delai=DELAI_GIT):
    """(frontières, commits que « rev-list HEAD » atteint) d'un clone
    superficiel, ou None quand git ne les donne pas."""
    avant = git_freeze_manifest._frontieres(dossier)
    out, _err, code = git(["rev-list", "HEAD"], dossier, delai)
    if avant is None or code:
        return None
    return avant, set(out.split())


def garder_historique(dossier, avant, visibles):
    """Retire du fichier « shallow » les frontières qu'une récupération a
    posées sur l'historique de HEAD. Rend les commits retirés, triés.

    `avant` est l'ensemble des frontières d'avant la récupération,
    `visibles` les commits que « rev-list HEAD » atteignait alors. Une
    frontière nouvelle prise dans `visibles` coupe un commit dont tous les
    parents sont déjà dans le clone, et cohérents : la retirer rend à HEAD
    l'historique qu'il avait. Une frontière nouvelle hors de `visibles`
    borne de l'historique neuf et reste. « --shallow-since » coupe ainsi un
    commit daté avant la borne, et « --deepen » peut poser une frontière
    au-dessus d'une ancienne.
    """
    apres = git_freeze_manifest._frontieres(dossier)
    if not apres:
        return []
    retirees = sorted((apres - avant) & visibles)
    chemin = fichier_shallow(dossier)
    if not retirees or not chemin:
        return []
    temporaire = chemin + ".repo_pull"
    with open(temporaire, "w") as fh:
        fh.writelines(f"{x}\n" for x in sorted(apres - set(retirees)))
    os.replace(temporaire, chemin)
    return retirees


def fetch_superficiel(args, dossier, delai=DELAI_GIT):
    """`git <args>`, un « fetch » d'un clone superficiel, puis
    `garder_historique` sur l'instantané d'avant : l'historique visible de
    HEAD ne raccourcit jamais. Rend (sortie, erreur, code)."""
    vue = instantane(dossier, delai)
    out, err, code = git(args, dossier, delai)
    if vue is not None:
        garder_historique(dossier, *vue)
    return out, err, code


def raccorder(dossier, constat, avant, refs, date_borne, delai=DELAI_GIT):
    """Repousse par « --deepen=1 » les frontières nouvelles de la cible qui
    la séparent de HEAD. Rend le nombre de tours faits.

    `avant` est l'ensemble des frontières d'avant la récupération bornée.
    Une frontière nouvelle plus récente que `date_borne` n'est frontière
    que parce qu'un de ses parents est plus ancien que la borne, et elle
    cache aussi les autres — HEAD, quand la cible fusionne une vieille
    branche par-dessus. Un tour s'arrête dès que HEAD est un ancêtre de la
    cible, ou quand aucune frontière nouvelle de la cible, absente de
    l'historique de HEAD, n'est plus récente que la borne ; RACCORDS_MAX
    tours au plus.
    """
    head, remote = constat.get("head"), constat.get("remote")
    tours = 0
    while tours < RACCORDS_MAX and head and refs:
        cible_sha = repo_state.resoudre(dossier, constat.get("cible"), delai)
        if not cible_sha or repo_apply.est_ancetre(dossier, head, cible_sha):
            return tours
        frontieres = git_freeze_manifest._frontieres(dossier) or set()
        nouvelles = sorted(frontieres - avant)
        if not nouvelles:
            return tours
        out, _err, code = git(
            ["show", "-s", "--format=%H %ct", *nouvelles], dossier, delai
        )
        champs = [x.split() for x in out.splitlines()]
        cachees = [
            x[0]
            for x in champs
            if len(x) == 2
            and x[1].isdigit()
            and int(x[1]) >= date_borne
            and repo_apply.est_ancetre(dossier, x[0], cible_sha) is True
            and repo_apply.est_ancetre(dossier, x[0], head) is not True
        ]
        if code or not cachees:
            return tours
        _out, _err, code = fetch_superficiel(
            ["fetch", "--quiet", "--no-tags", "--deepen=1", remote, *refs],
            dossier,
            delai,
        )
        tours += 1
        if code:
            return tours
    return tours


def recuperer(dossier, constat, delai=DELAI_GIT):
    """Récupère la cible du constat. Rend None, ou le motif d'un échec.

    Un clone superficiel ne reçoit que les commits postérieurs à sa
    frontière la plus ancienne, moins MARGE_FRONTIERE (« --shallow-since ») :
    une divergence reste bornée. Chaque récupération garde l'historique de
    HEAD (`fetch_superficiel`), et `raccorder` relie à HEAD une cible dont
    une frontière nouvelle le cache. Une cible commit absente après la
    récupération de sa branche est demandée par son commit, une fois.
    """
    remote, refspec = constat.get("remote"), constat.get("refspec")
    cible = constat.get("cible")
    if not remote or remote == ".":
        return None
    args = ["fetch", "--quiet", "--no-tags"]
    recuperer_git = git
    avant = date_borne = None
    if constat.get("superficiel"):
        recuperer_git = fetch_superficiel
        vue = instantane(dossier, delai)
        date = date_frontiere(dossier, vue[1] if vue else None)
        avant = vue[0] if vue else None
        if date and avant is not None:
            date_borne = max(0, date - MARGE_FRONTIERE)
            args.append(f"--shallow-since={date_borne}")
    refs = []
    if refspec:
        _out, err, code = recuperer_git(
            args + [remote, refspec], dossier, delai
        )
        if code:
            return premiere_ligne(err, code)
        refs.append(refspec)
    if manifest_freeze.is_sha(cible) and not repo_state.resoudre(
        dossier, cible
    ):
        _out, err, code = recuperer_git(args + [remote, cible], dossier, delai)
        if code and not refspec:
            return premiere_ligne(err, code)
        if not code:
            refs.append(cible)
    if date_borne is not None:
        constat["raccords"] = raccorder(
            dossier, constat, avant, refs, date_borne, delai
        )
    return None


# ── essai à sec ─────────────────────────────────────────────────────────


def constat_vide(chemin, attrs=None):
    attrs = attrs or {}
    return {
        "chemin": chemin,
        "nom": attrs.get("name"),
        "revision": attrs.get("revision"),
        "branche": None,
        "detache": False,
        "remote": None,
        "cible": None,
        "refspec": None,
        "source_cible": None,
        "head": None,
        "cible_sha": None,
        "nos": None,
        "locaux": None,
        "retard": None,
        "base": None,
        "diverge": False,
        "superficiel": False,
        "approfondissement_requis": False,
        "sale": False,
        "non_suivis": 0,
        "ecrases": [],
        "stash_prevu": False,
        "operation_en_cours": None,
        "entrants": [],
        "entrants_total": 0,
        "entrants_tronques": False,
        "verdict": None,
        "applicable": False,
        "sauvegarde_prefixe": None,
        "fetch": "saute",
        "raccords": 0,
        "motif": None,
        "erreur": None,
    }


def constater(
    racine,
    chemin,
    attrs,
    mode_cible,
    strategie,
    delai=DELAI_GIT,
    fetch=True,
    attrs_depart=None,
):
    """Le constat d'un dépôt : sa cible récupérée, et son verdict.

    `mode_cible` vaut « branche » (la branche suivie, voir `cible_suivie`)
    ou « manifeste » (l'entrée `attrs`, voir `cible_du_manifeste`).
    `attrs_depart` est l'entrée du manifeste local actuel quand `attrs`
    vient du manifeste prédit : sa branche porte l'historique de HEAD, que
    l'approfondissement doit aussi allonger. Ne lève jamais. Écrit
    seulement ce qu'un « fetch » écrit : objets, références de suivi,
    frontière d'un clone superficiel.
    """
    c = constat_vide(chemin, attrs)
    c["_attrs"] = attrs
    dossier = os.path.join(racine, chemin)
    if not repo_state.a_un_git(dossier):
        c["verdict"] = "absent"
        return c
    head, branche, erreur = repo_state.lire_tete(dossier, delai)
    if erreur:
        c.update(verdict="erreur", erreur=erreur)
        return c
    c.update(head=head, branche=branche, detache=branche is None)
    c["sale"], c["non_suivis"] = etat_arbre(dossier, delai)
    c["superficiel"] = bool(repo_state.est_superficiel(dossier, delai))
    c["sauvegarde_prefixe"] = nom_sauvegarde(
        branche_de_sauvegarde(branche, attrs), ""
    )
    operation = operation_en_cours(dossier)
    if operation:
        c.update(verdict="operation_en_cours", operation_en_cours=operation)
        return c
    if mode_cible == "manifeste":
        cible = cible_du_manifeste(dossier, attrs or {})
    elif branche is None:
        c["verdict"] = "detache"
        return c
    else:
        cible = cible_suivie(dossier, branche, attrs)
    if cible.get("motif"):
        c.update(verdict="sans_cible", motif=cible["motif"])
        return c
    c.update(
        remote=cible["remote"],
        cible=cible["cible"],
        refspec=cible["refspec"],
        source_cible=cible["source_cible"],
    )
    if mode_cible == "manifeste" and attrs_depart:
        avant = cible_du_manifeste(dossier, attrs_depart)
        if avant.get("refspec") and avant["refspec"] != c["refspec"]:
            c["_refspec_depart"] = avant["refspec"]
        if avant.get("cible") and avant["cible"] != c["cible"]:
            c["_cible_depart"] = avant["cible"]
    if fetch and cible["remote"] and cible["remote"] != ".":
        motif = recuperer(dossier, c, delai)
        c["fetch"] = "echoue" if motif else "ok"
        if motif:
            c.update(verdict="fetch_echoue", motif=motif)
            return c
    c["cible_sha"] = repo_state.resoudre(dossier, c["cible"], delai)
    if not c["cible_sha"]:
        c.update(verdict="cible_absente", motif="target not in the clone")
        return c
    classer(dossier, c, strategie, delai, mode_cible)
    return c


def commits_locaux(dossier, head, cible_sha, delai=DELAI_GIT):
    """Le nombre de commits de HEAD que ni la cible ni une référence de
    suivi (« --remotes ») ne contiennent : le travail que seul ce clone
    porte. None si git refuse."""
    out, _err, code = git(
        ["rev-list", "--count", head, f"^{cible_sha}", "--not", "--remotes"],
        dossier,
        delai,
    )
    return int(out) if not code and out.strip().isdigit() else None


def fichiers_ecrases(dossier, head, cible_sha, delai=DELAI_GIT):
    """Les fichiers ignorés présents dans l'arbre que la cible suit et que
    HEAD ne suit pas : git les écraserait sans rien dire. Triés."""
    out, _err, code = git(
        ["diff", "--name-only", "-z", "--diff-filter=A", head, cible_sha],
        dossier,
        delai,
    )
    if code:
        return []
    presents = [
        x
        for x in out.split("\0")
        if x and os.path.lexists(os.path.join(dossier, x))
    ]
    if not presents:
        return []
    out, _err, code = repo_state.git(
        ["check-ignore", "-z", "--stdin"],
        dossier,
        delai,
        entree="\0".join(presents) + "\0",
    )
    if code not in (0, 1):
        return []
    return sorted(x for x in out.split("\0") if x)


def classer(dossier, c, strategie, delai=DELAI_GIT, mode_cible="branche"):
    """Pose verdict, compteurs, base, fichiers écrasés et commits entrants
    de `c`.

    En mode « manifeste », un clone détaché dont aucun commit n'est à lui
    (`commits_locaux`) prend « bascule » au lieu de « diverge » ou
    « superficiel » : sa cible s'extrait telle quelle, et rien n'est perdu
    que les remotes n'aient déjà.
    """
    head, cible_sha = c["head"], c["cible_sha"]
    c["nos"], c["retard"] = repo_state.avance_retard(
        dossier, cible_sha, head, delai
    )
    out, _err, code = git(["merge-base", head, cible_sha], dossier, delai)
    c["base"] = out.strip() if code == 0 and out.strip() else None
    if mode_cible == "manifeste" and head != cible_sha:
        c["locaux"] = commits_locaux(dossier, head, cible_sha, delai)
    if head == cible_sha:
        c["verdict"] = "a_jour"
    elif repo_apply.est_ancetre(dossier, cible_sha, head) is True:
        c["verdict"] = "en_avance"
    elif repo_apply.est_ancetre(dossier, head, cible_sha) is True:
        c["verdict"] = "avance_rapide"
        c["applicable"] = True
    elif mode_cible == "manifeste" and c["detache"] and c["locaux"] == 0:
        c["verdict"] = "bascule"
        c["applicable"] = True
    else:
        sure = bool(c["base"])
        if c["superficiel"]:
            bases = git_freeze_manifest._bases(dossier, head, cible=cible_sha)
            sure = bool(bases) and git_freeze_manifest._bases_sures(
                dossier, head, bases, cible=cible_sha
            )
        if sure:
            c["verdict"] = "diverge"
            c["diverge"] = True
            c["applicable"] = strategie != "ff"
            if strategie == "ff":
                c["motif"] = "diverged: fast-forward impossible"
        elif c["superficiel"]:
            c["verdict"] = "superficiel"
            c["approfondissement_requis"] = True
        else:
            c["verdict"] = "erreur"
            c["erreur"] = "no common history with the target"
    c["stash_prevu"] = bool(c["sale"]) and (
        c["applicable"] or c["approfondissement_requis"]
    )
    if c["applicable"] or c["approfondissement_requis"]:
        c["ecrases"] = fichiers_ecrases(dossier, head, cible_sha, delai)
    if c["retard"]:
        out, _err, code = git(
            [
                "log",
                f"--format={repo_state.FORMAT_COMMIT}",
                f"--max-count={MAX_ENTRANTS}",
                f"{head}..{cible_sha}",
            ],
            dossier,
            delai,
        )
        c["entrants"] = repo_state.lire_commits(out) if not code else []
    c["entrants_total"] = c["retard"] or 0
    c["entrants_tronques"] = (c["retard"] or 0) > len(c["entrants"])


def _regenerer_par_script(racine, cwd, sortie, geler, delai=DELAI_SYNC):
    """Lance la fusion des manifestes dans `cwd`, vers `sortie`.

    Les mêmes arguments que « make repo_configure_all ». Rend (code,
    sortie du script)."""
    argv = [
        os.path.join(racine, PYTHON_ERPLIBRE),
        os.path.join(racine, SCRIPT_FUSION),
        "--output",
        sortie,
        "--with_OCA",
    ]
    if geler:
        argv.append("--freeze")
    return lancer(argv, delai, cwd, repo_upgrade.env_sans_invite())


def regenerer_defaut(racine, cwd, sortie, geler):
    return _regenerer_par_script(racine, cwd, sortie, geler)


def erreur_de_regeneration(texte, code):
    """« regeneration failed: <dernière ligne> », URL sans secret."""
    ligne = (texte or "").strip().splitlines()[-1:] or [str(code)]
    return f"regeneration failed: {sans_secrets(ligne[0])}"


def racine_bougera(constat, strategie):
    """La racine changera-t-elle d'arbre si la passe l'intègre ?"""
    verdict = constat.get("verdict") if constat else None
    if verdict == "diverge":
        return strategie != "ff"
    return verdict in ("avance_rapide", "superficiel")


def extraire_cible(racine, sha, destination):
    """Pose dans `destination` les dossiers « manifest » et « conf » du
    commit `sha` de la racine, puis les entrées vives de la fusion.
    Rend None, ou le motif d'un échec."""
    archive = os.path.join(destination, "cible.tar")
    _out, err, code = git(
        ["archive", "--format=tar", "-o", archive, sha, "manifest", "conf"],
        racine,
    )
    if code:
        return premiere_ligne(err, code)
    with tarfile.open(archive) as tar:
        tar.extractall(destination, filter="data")
    os.remove(archive)
    for relatif in ENTREES_VIVES:
        source = os.path.join(racine, relatif)
        if os.path.isfile(source):
            cible = os.path.join(destination, relatif)
            os.makedirs(os.path.dirname(cible) or destination, exist_ok=True)
            shutil.copy2(source, cible)
    if os.path.isdir(os.path.join(racine, DOSSIER_MOBILE)):
        os.makedirs(os.path.join(destination, DOSSIER_MOBILE), exist_ok=True)
    return None


def predire_manifeste(racine, constat_racine, strategie, regenerer=None):
    """Le manifeste local que la passe écrirait, et ce qui y change.

    Quand la racine bougera, la fusion tourne sur ses dossiers « manifest »
    et « conf » au commit cible, extraits dans un dossier temporaire avec
    les entrées vives du checkout ; sinon, sur la racine telle qu'elle est.
    Gelé quand le manifeste local l'est déjà. Rend (manifeste, projets) :
    `manifeste` est le bloc JSON (voir la docstring du module), `projets`
    {chemin: attributs} du manifeste prédit, None en cas d'échec.
    """
    regenerer = regenerer or regenerer_defaut
    etat_actuel = repo_state.mode_du_checkout(racine)[0]
    manifeste = {
        "etat_actuel": etat_actuel,
        "regenere": False,
        "ecrit": None,
        "copie_avant": None,
        "changements": [],
        "erreur": None,
    }
    temporaire = tempfile.mkdtemp(prefix="repo_pull_")
    try:
        cwd = racine
        if racine_bougera(constat_racine, strategie) and constat_racine.get(
            "cible_sha"
        ):
            motif = extraire_cible(
                racine, constat_racine["cible_sha"], temporaire
            )
            if motif:
                manifeste["erreur"] = f"prediction failed: {motif}"
                return manifeste, None
            cwd = temporaire
        sortie = os.path.join(temporaire, "out.xml")
        code, texte = regenerer(racine, cwd, sortie, etat_actuel == "frozen")
        if code or not os.path.isfile(sortie):
            manifeste["erreur"] = erreur_de_regeneration(texte, code)
            return manifeste, None
        carte = lire_carte(sortie)
        if carte is None:
            manifeste["erreur"] = "regeneration failed: unreadable output"
            return manifeste, None
        _remotes, projets = lire_projets(sortie)
        manifeste["regenere"] = True
        manifeste["_carte"] = _liste(carte)
        manifeste["_remotes"] = _remotes
        actuelle = (
            lire_carte(os.path.join(racine, repo_state.MANIFESTE_LOCAL)) or {}
        )
        manifeste["changements"] = changements(actuelle, carte)
        return manifeste, projets
    finally:
        shutil.rmtree(temporaire, True)


def changements(avant, apres):
    """[{chemin, genre, avant, apres}] entre deux cartes de manifeste."""
    lst = []
    for chemin in sorted(set(avant) | set(apres)):
        a, b = avant.get(chemin), apres.get(chemin)
        if a is None:
            genre = "ajout"
        elif b is None:
            genre = "retrait"
        elif tuple(a) != tuple(b):
            genre = "change"
        else:
            continue
        lst.append(
            {
                "chemin": chemin,
                "genre": genre,
                "avant": a[2] if a else None,
                "apres": b[2] if b else None,
            }
        )
    return lst


def nouveau(racine, chemin, attrs, remotes):
    """L'entrée d'un projet du manifeste prédit qui n'est pas cloné."""
    dossier = os.path.join(racine, chemin)
    occupe = os.path.isdir(dossier) and bool(os.listdir(dossier))
    occupe = occupe or (
        os.path.lexists(dossier) and not os.path.isdir(dossier)
    )
    return {
        "chemin": chemin,
        "nom": attrs.get("name"),
        "remote": attrs.get("remote"),
        "url": repo_state.sans_identifiants(
            repo_upgrade.url_amont(
                (remotes or {}).get(attrs.get("remote")), attrs.get("name")
            )
        )
        or None,
        "revision": attrs.get("revision"),
        "occupe": occupe,
    }


def dependances(racine, depart, arrivee):
    """Les fichiers de dépendances Python que `depart..arrivee` change dans
    la racine, et ce qu'il faut en faire (voir la docstring du module)."""
    couple = repo_state.lire_fichier(racine, ".erplibre-version") or ""
    venv = f".venv.{couple}"
    bloc = {
        "fichiers": [],
        "changement_de_version": False,
        "a_installer": False,
        "venv": venv,
        "commande": commande_poetry(venv),
        "venv_erplibre_a_revoir": False,
        "requirements_addons": [],
    }
    cibles = []
    for lien in ("pyproject.toml", "poetry.lock"):
        try:
            cibles.append(
                os.path.normpath(os.readlink(os.path.join(racine, lien)))
            )
        except OSError:
            continue
    if not depart or not arrivee or depart == arrivee:
        return bloc
    suivis = list(
        dict.fromkeys(
            cibles
            + list(FICHIERS_DEPENDANCES_FIXES)
            + [
                f"requirement/requirements.{couple}.txt",
                f"requirement/ignore_requirements.{couple}.txt",
            ]
        )
    )
    out, _err, code = git(
        ["diff", "--name-only", depart, arrivee, "--", *suivis], racine
    )
    fichiers = (
        sorted(x for x in out.splitlines() if x.strip()) if not code else []
    )
    bloc["fichiers"] = fichiers
    bloc["changement_de_version"] = any(
        x in fichiers for x in ("pyproject.toml", "poetry.lock")
    )
    bloc["a_installer"] = (
        any(x in fichiers for x in cibles)
        and not bloc["changement_de_version"]
    )
    bloc["venv_erplibre_a_revoir"] = (
        "requirement/erplibre_require-ments.txt" in fichiers
    )
    return bloc


def requirements_touches(racine, constats):
    """Les dépôts dont la cible change un fichier « requirements.txt »."""
    lst = []
    for c in constats:
        if c["chemin"] == "." or not (
            c.get("applicable") or c.get("approfondissement_requis")
        ):
            continue
        out, _err, code = git(
            ["diff", "--name-only", c["head"], c["cible_sha"]],
            os.path.join(racine, c["chemin"]),
        )
        if not code and any(
            os.path.basename(x) == "requirements.txt" for x in out.splitlines()
        ):
            lst.append(c["chemin"])
    return sorted(lst)


def diagnostic(
    racine,
    mode="manifeste",
    strategie="rebase",
    chemin_seul=None,
    regenerer=None,
    jobs=None,
    delai=DELAI_GIT,
):
    """L'essai à sec : (données, code). Récupère, constate, n'intègre rien.

    `chemin_seul` restreint à un dépôt (« . » pour la racine) : un chemin
    inconnu rend EXIT_CIBLE. En mode « manifeste » sans `chemin_seul`, la
    racine passe d'abord, puis le manifeste se prédit et chaque clone se
    constate sur sa nouvelle entrée.
    """
    version = repo_upgrade.version_active(racine)
    donnees = {
        "schema": SCHEMA,
        "command": "dry-run",
        "generated_at": repo_state.maintenant(),
        "root": racine,
        "version": version,
        "mode": mode,
        "strategie": strategie,
        "chemin_seul": chemin_seul,
        "depots": [],
        "manifeste": None,
        "nouveaux": [],
        "retires": [],
        "dependances": dependances(racine, None, None),
        "plan": [],
        "plan_superficiel": [],
        "plan_nouveaux": [],
        "attendus": [],
        "attendus_superficiel": [],
        "counts": {},
        "errors": [],
    }
    projets_locaux, _remotes, _present = repo_state.definitions(racine)
    racine_git = repo_state.a_un_git(racine)
    if chemin_seul is not None:
        chemin_seul = repo_state.normaliser(racine, chemin_seul)
        donnees["chemin_seul"] = chemin_seul
        if (
            chemin_seul is None
            or (chemin_seul != "." and chemin_seul not in projets_locaux)
            or (chemin_seul == "." and not racine_git)
        ):
            donnees["error"] = "unknown path"
            return donnees, EXIT_CIBLE
    jobs = jobs or PARALLELE

    constats = []
    racine_constat = None
    if racine_git and chemin_seul in (None, "."):
        racine_constat = constater(
            racine, ".", projets_locaux.get("."), "branche", strategie, delai
        )
        constats.append(racine_constat)

    a_constater = []  # (chemin, attrs, mode_cible)
    if mode == "manifeste" and chemin_seul is None:
        manifeste, predits = predire_manifeste(
            racine, racine_constat, strategie, regenerer
        )
        donnees["manifeste"] = manifeste
        if predits is None:
            donnees["errors"].append(manifeste["erreur"])
            predits = {}
        remotes = manifeste.pop("_remotes", {})
        for chemin in sorted(predits):
            if chemin == ".":
                continue
            if repo_state.a_un_git(os.path.join(racine, chemin)):
                a_constater.append(
                    (
                        chemin,
                        predits[chemin],
                        "manifeste",
                        projets_locaux.get(chemin),
                    )
                )
            else:
                donnees["nouveaux"].append(
                    nouveau(racine, chemin, predits[chemin], remotes)
                )
        if manifeste["regenere"]:
            donnees["retires"] = sorted(
                x["chemin"]
                for x in manifeste["changements"]
                if x["genre"] == "retrait"
            )
    else:
        mode_cible = "manifeste" if mode == "manifeste" else "branche"
        for chemin in sorted(projets_locaux):
            if chemin == "." or (chemin_seul and chemin != chemin_seul):
                continue
            a_constater.append(
                (chemin, projets_locaux[chemin], mode_cible, None)
            )

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        constats += list(
            pool.map(
                lambda x: constater(
                    racine,
                    x[0],
                    x[1],
                    x[2],
                    strategie,
                    delai,
                    attrs_depart=x[3],
                ),
                a_constater,
            )
        )

    donnees["depots"] = constats
    for c in constats:
        donnees["counts"][c["verdict"]] = (
            donnees["counts"].get(c["verdict"], 0) + 1
        )
        if c.get("erreur"):
            donnees["errors"].append(f"{c['chemin']}: {c['erreur']}")
    donnees["plan"] = sorted(c["chemin"] for c in constats if c["applicable"])
    donnees["plan_superficiel"] = sorted(
        c["chemin"] for c in constats if c["approfondissement_requis"]
    )
    donnees["plan_nouveaux"] = sorted(
        n["chemin"] for n in donnees["nouveaux"] if not n["occupe"]
    )
    par_chemin = {c["chemin"]: c for c in constats}
    donnees["attendus"] = [
        f"{p}={par_chemin[p]['cible_sha']}:{par_chemin[p]['head']}"
        for p in donnees["plan"]
    ]
    donnees["attendus_superficiel"] = [
        f"{p}={par_chemin[p]['cible_sha']}:{par_chemin[p]['head']}"
        for p in donnees["plan_superficiel"]
    ]
    if racine_constat and racine_bougera(racine_constat, strategie):
        donnees["dependances"] = dependances(
            racine, racine_constat["head"], racine_constat["cible_sha"]
        )
    donnees["dependances"]["requirements_addons"] = requirements_touches(
        racine, [c for c in constats if c.get("cible_sha")]
    )
    return donnees, EXIT_OK


def public(donnees):
    """Une copie de `donnees` sans les clés internes (préfixe « _ »)."""
    if isinstance(donnees, dict):
        return {
            k: public(v) for k, v in donnees.items() if not k.startswith("_")
        }
    if isinstance(donnees, list):
        return [public(x) for x in donnees]
    return donnees


# ── intégrer ────────────────────────────────────────────────────────────


def enregistrement(constat):
    return {
        "chemin": constat["chemin"],
        "verdict_avant": constat.get("verdict"),
        "etat": None,
        "branche": constat.get("branche"),
        "detache": bool(constat.get("detache")),
        "cible": constat.get("cible"),
        "cible_sha": constat.get("cible_sha"),
        "depart": constat.get("head"),
        "arrivee": None,
        "sauvegarde": None,
        "stash": {"etat": "aucun", "sha": None, "commande": None},
        "approfondi": None,
        "conflits": [],
        "ecrases": [],
        "copie_ecrases": None,
        "sortie": "",
        "motif": None,
    }


def approfondir_clone(dossier, constat, res, delai=DELAI_GIT, echeance=None):
    """Approfondit un clone superficiel par paliers jusqu'à une base sûre.

    « --deepen » ajoute de l'historique depuis les frontières que les
    références récupérées atteignent, la profondeur doublant de
    PROFONDEUR_DEPART à PROFONDEUR_MAX. Les références sont celles de la
    cible et, quand le manifeste change de branche, celle que le clone
    suivait : sans elle, les frontières de HEAD ne s'allongent pas. Une
    branche de départ que le remote n'a plus est abandonnée au premier
    refus. Rend le verdict trouvé, « avance_rapide » ou « diverge », ou None
    au plafond, ou quand `echeance` passe avant un palier (« motif » vaut
    alors MOTIF_DELAI). Seuls des objets d'historique sont ajoutés.
    """
    faite = 0
    profondeur = git_freeze_manifest.PROFONDEUR_DEPART
    head, cible_sha = res["depart"], res["cible_sha"]
    args = ["fetch", "--quiet", "--no-tags"]
    refs = [constat.get("refspec") or cible_sha]
    if constat.get("_refspec_depart"):
        refs.append(constat["_refspec_depart"])
    while profondeur <= git_freeze_manifest.PROFONDEUR_MAX:
        if echue(echeance):
            res["motif"] = MOTIF_DELAI
            return None
        pas = [f"--deepen={profondeur - faite}", constat["remote"]]
        out, err, code = fetch_superficiel(args + pas + refs, dossier, delai)
        if code and len(refs) > 1:
            refs = refs[:1]
            out, err, code = fetch_superficiel(
                args + pas + refs, dossier, delai
            )
        res["sortie"] = joindre(res["sortie"], out, err)
        if code:
            res["motif"] = premiere_ligne(err, code)
            return None
        faite = profondeur
        res["approfondi"] = {"profondeur": profondeur}
        if repo_apply.est_ancetre(dossier, head, cible_sha) is True:
            return "avance_rapide"
        bases = git_freeze_manifest._bases(dossier, head, cible=cible_sha)
        if bases and git_freeze_manifest._bases_sures(
            dossier, head, bases, cible=cible_sha
        ):
            return "diverge"
        profondeur *= 2
    return None


def remettre_au_depart(dossier, res, branche_depart, hors_suivi, delai):
    """Remet le dépôt sur « depart » après une intégration ratée.

    HEAD et la branche reviennent où la passe les a pris (« checkout -f »
    puis « reset --hard » sur une branche, « checkout -f --detach »
    détaché) ; les fichiers non suivis apparus depuis le relevé
    `hors_suivi` ET présents dans l'arbre de la cible sont effacés, puis
    leurs dossiers devenus vides. Rend (remis, sortie).
    """
    depart = res["depart"]
    sorties = []
    head = repo_apply.sha_de(dossier, "HEAD")
    if (
        head != depart
        or repo_apply.branche_courante(dossier) != branche_depart
    ):
        if branche_depart:
            gestes = [
                ["checkout", "-f", branche_depart],
                ["reset", "--hard", depart],
            ]
        else:
            gestes = [["checkout", "-f", "--detach", depart]]
        for geste in gestes:
            out, err, code = git(geste, dossier, delai, ecrit=True)
            sorties.append(out + err)
            if code:
                manuel = " ".join(["git", "-C", res["chemin"]] + geste)
                sorties.append(f"{t('To run by hand:')} {manuel}")
                return False, joindre(*sorties)
    de_la_cible = set()
    if res.get("cible_sha"):
        out, _err, code = git(
            ["ls-tree", "-r", "--name-only", "-z", res["cible_sha"]], dossier
        )
        de_la_cible = set(out.split("\0")) if not code else set()
    for relatif in sorted(
        repo_apply.fichiers_hors_suivi(dossier) - hors_suivi
    ):
        if relatif not in de_la_cible:
            continue
        try:
            os.remove(os.path.join(dossier, relatif))
        except OSError:
            continue
        parent = os.path.dirname(relatif)
        while parent:
            try:
                os.rmdir(os.path.join(dossier, parent))
            except OSError:
                break
            parent = os.path.dirname(parent)
    return True, joindre(*sorties)


def integrer(
    racine,
    constat,
    horodatage,
    strategie="rebase",
    approfondi=False,
    attrs=None,
    delai=DELAI_GIT,
    echeance=None,
):
    """Intègre la cible d'un dépôt. Rend son enregistrement, ne lève jamais.

    Séquence : sauvegarde de HEAD, stash des fichiers suivis modifiés,
    copie des fichiers ignorés que la cible écrase, avance rapide,
    bascule, rebase ou fusion, puis stash réappliqué. Un échec abandonne
    l'opération et remet le dépôt sur son départ, fichiers écrasés remis ;
    la sauvegarde, alors égale à HEAD, est supprimée. Rien ne commence
    après `echeance` (« saute_delai »).
    """
    res = enregistrement(constat)
    if echue(echeance):
        res.update(etat="saute_delai", motif=MOTIF_DELAI)
        return res
    try:
        return _integrer(
            racine,
            constat,
            res,
            horodatage,
            strategie,
            approfondi,
            attrs,
            delai,
            echeance,
        )
    except Exception as exc:  # un dépôt ne fait pas tomber la passe
        res["etat"] = "erreur"
        res["motif"] = f"internal: {type(exc).__name__}: {exc}"
        return res


def amont_de_depart(dossier, constat, head, cible_sha, delai=DELAI_GIT):
    """Le commit d'où rejouer les commits de HEAD quand le manifeste mène le
    dépôt sur une autre ligne amont, ou None quand un rebase ordinaire
    suffit.

    C'est la base de HEAD et de son ancienne cible (« _cible_depart »),
    quand la nouvelle cible ne la contient pas : « rebase --onto » ne
    rejoue alors que les commits de HEAD qui ne sont pas sur l'ancienne
    ligne, au lieu de toute l'histoire amont qui les sépare de la nouvelle.
    """
    ancienne = repo_state.resoudre(
        dossier, constat.get("_cible_depart"), delai
    )
    if not ancienne or ancienne == cible_sha:
        return None
    out, _err, code = git(["merge-base", head, ancienne], dossier, delai)
    amont = out.strip() if not code else ""
    if (
        not amont
        or repo_apply.est_ancetre(dossier, amont, cible_sha) is not False
    ):
        return None
    return amont


def copier_ecrases(dossier, relatifs, destination):
    """Copie les fichiers `relatifs` de `dossier` sous `destination`, en
    gardant leur chemin. Rend les fichiers copiés."""
    copies = []
    for relatif in relatifs:
        source = os.path.join(dossier, relatif)
        if not os.path.isfile(source) or os.path.islink(source):
            continue
        cible = os.path.join(destination, relatif)
        os.makedirs(os.path.dirname(cible), exist_ok=True)
        shutil.copy2(source, cible)
        copies.append(relatif)
    return copies


def _integrer(
    racine,
    constat,
    res,
    horodatage,
    strategie,
    approfondi,
    attrs,
    delai,
    echeance,
):
    dossier = os.path.join(racine, constat["chemin"])
    sorties = []

    def noter(out, err):
        sorties.append(out + err)

    def finir(etat):
        res["etat"] = etat
        res["sortie"] = queue(joindre(res["sortie"], *sorties))
        return res

    depart = repo_apply.sha_de(dossier, "HEAD")
    branche_depart = repo_apply.branche_courante(dossier)
    res.update(
        depart=depart, branche=branche_depart, detache=branche_depart is None
    )
    if operation_en_cours(dossier):
        return finir("saute_operation")
    verdict = constat.get("verdict")
    if verdict == "detache":
        return finir("saute_detache")
    if verdict == "superficiel":
        if not approfondi:
            return finir("saute_superficiel")
        verdict = approfondir_clone(dossier, constat, res, delai, echeance)
        if verdict is None:
            if res["motif"] == MOTIF_DELAI:
                return finir("saute_delai")
            return finir("superficiel_sans_base")
    if verdict not in ("avance_rapide", "diverge", "bascule"):
        return finir("a_jour" if verdict == "a_jour" else "erreur")
    if verdict == "diverge" and strategie == "ff":
        return finir("refuse_ff")

    nom = nom_sauvegarde(
        branche_de_sauvegarde(branche_depart, attrs or constat.get("_attrs")),
        horodatage,
    )
    if repo_apply.branche_existe(dossier, nom):
        return finir("sauvegarde_existante")
    out, err, code = git(["branch", nom, depart], dossier, delai, ecrit=True)
    noter(out, err)
    if code:
        res["motif"] = premiere_ligne(err, code)
        return finir("erreur")
    res["sauvegarde"] = nom

    def abandonner(motif):
        git(["branch", "-D", nom], dossier, delai, ecrit=True)
        res["sauvegarde"] = None
        res["motif"] = motif
        return finir("erreur")

    sale, _non_suivis = etat_arbre(dossier, delai)
    if sale:
        stash_avant = repo_apply.sha_de(dossier, "refs/stash")
        out, err, code = git(
            ["stash", "push", "--quiet", "-m", f"repo_pull {horodatage}"],
            dossier,
            delai,
            ecrit=True,
        )
        noter(out, err)
        if code:
            return abandonner(premiere_ligne(err, code))
        stash_sha = repo_apply.sha_de(dossier, "refs/stash")
        if stash_sha and stash_sha != stash_avant:
            res["stash"] = {
                "etat": "garde",
                "sha": stash_sha,
                "commande": f"git -C {res['chemin']} stash apply {stash_sha}",
            }
        elif etat_arbre(dossier, delai)[0] is not False:
            return abandonner(
                "modified files that git stash cannot save"
                " (a moved submodule?)"
            )
    hors_suivi = repo_apply.fichiers_hors_suivi(dossier)
    copie = None
    ecrases = fichiers_ecrases(dossier, depart, res["cible_sha"], delai)
    if ecrases:
        copie = os.path.join(
            dossier_passe(horodatage, racine),
            "ecrases",
            (
                res["chemin"].replace("/", "_")
                if res["chemin"] != "."
                else "racine"
            ),
        )
        res["ecrases"] = copier_ecrases(dossier, ecrases, copie)
        res["copie_ecrases"] = os.path.relpath(copie, racine)

    cible_sha = res["cible_sha"]
    if verdict == "avance_rapide":
        geste, etat, abandon = (
            ["merge", "--ff-only", cible_sha],
            "avance",
            None,
        )
    elif verdict == "bascule":
        geste, etat, abandon = (
            ["checkout", "--detach", cible_sha],
            "tire",
            None,
        )
    elif strategie == "rebase":
        amont = amont_de_depart(dossier, constat, depart, cible_sha, delai)
        geste = ["rebase", cible_sha]
        if amont:
            geste = ["rebase", "--onto", cible_sha, amont]
        etat, abandon = "tire", ["rebase", "--abort"]
    else:
        message = (
            f"Merge {res['cible']} ({cible_sha[:12]})"
            f" into {branche_depart or 'HEAD'}"
        )
        geste = ["merge", "--no-edit", "-m", message, cible_sha]
        etat, abandon = "tire", ["merge", "--abort"]
    out, err, code = git(geste, dossier, delai, ecrit=True)
    noter(out, err)
    if code:
        res["conflits"] = repo_apply.fichiers_en_conflit(dossier)
        en_cours = operation_en_cours(dossier)
        if abandon and en_cours:
            out, err, code_abandon = git(abandon, dossier, delai, ecrit=True)
            noter(out, err)
            if code_abandon:
                manuel = " ".join(["git", "-C", res["chemin"]] + abandon)
                sorties.append(f"{t('To run by hand:')} {manuel}")
                return finir("restauration_echouee")
        remis, sortie = remettre_au_depart(
            dossier, res, branche_depart, hors_suivi, delai
        )
        sorties.append(sortie)
        if not remis:
            return finir("restauration_echouee")
        if copie and res["ecrases"]:
            copier_ecrases(copie, res["ecrases"], dossier)
        etat = "conflit_annule" if res["conflits"] or en_cours else "erreur"
        if etat == "erreur":
            res["motif"] = premiere_ligne(err, code)
        git(["branch", "-D", nom], dossier, delai, ecrit=True)
        res["sauvegarde"] = None

    if res["stash"]["sha"]:
        out, err, code = git(
            ["stash", "pop", "--quiet"], dossier, delai, ecrit=True
        )
        noter(out, err)
        if code:
            out, err, _c = git(
                ["reset", "--hard", "HEAD"], dossier, delai, ecrit=True
            )
            noter(out, err)
            if etat in ("avance", "tire"):
                etat = "stash_garde"
        else:
            res["stash"].update(etat="reapplique", commande=None)
    res["arrivee"] = repo_apply.sha_de(dossier, "HEAD")
    return finir(etat)


# ── manifeste régénéré et nouveaux dépôts ───────────────────────────────


def regenerer_manifeste(racine, donnees, dossier, regenerer=None):
    """Régénère le manifeste local après la racine, et l'écrit s'il est
    celui que l'essai à sec a prédit.

    La fusion écrit dans `dossier`/erplibre_manifest.apres.xml ; sa carte
    doit être la carte prédite, sinon rien n'est écrit (« erreur »
    « manifeste_different »). Le manifeste local d'avant est copié dans
    `dossier`/erplibre_manifest.avant.xml, puis remplacé d'un coup
    (« os.replace »). Modifie et rend `donnees["manifeste"]`.
    """
    regenerer = regenerer or regenerer_defaut
    manifeste = donnees["manifeste"]
    sortie = os.path.join(dossier, "erplibre_manifest.apres.xml")
    code, texte = regenerer(
        racine, racine, sortie, manifeste["etat_actuel"] == "frozen"
    )
    carte = lire_carte(sortie) if not code else None
    if carte is None:
        manifeste.update(
            ecrit=False, erreur=erreur_de_regeneration(texte, code)
        )
        return manifeste
    if _liste(carte) != manifeste.get("_carte"):
        manifeste.update(ecrit=False, erreur="manifeste_different")
        return manifeste
    local = os.path.join(racine, repo_state.MANIFESTE_LOCAL)
    if os.path.isfile(local):
        copie = os.path.join(dossier, "erplibre_manifest.avant.xml")
        shutil.copy2(local, copie)
        manifeste["copie_avant"] = os.path.relpath(copie, racine)
    os.makedirs(os.path.dirname(local), exist_ok=True)
    temporaire = os.path.join(
        os.path.dirname(local), ".erplibre_manifest.xml.tmp"
    )
    shutil.copyfile(sortie, temporaire)
    os.replace(temporaire, local)
    manifeste["ecrit"] = True
    return manifeste


def lancer_repo(racine, args, delai, env=None):
    """(code, sortie) du lanceur git-repo, lancé depuis la racine : son
    shebang relatif ne trouve son interpréteur que de là."""
    environ = repo_upgrade.env_sans_invite()
    environ["REPO_SKIP_SELF_UPDATE"] = "1"
    environ.update(env or {})
    return lancer([REPO_BIN, *args], delai, racine, environ)


def cloner_nouveaux(racine, nouveaux, chemins, jobs=None, echeance=None):
    """Clone les nouveaux dépôts `chemins` par un « repo sync » restreint.

    Refusé quand « .repo/project.list » nomme un chemin que « repo list
    -p » ne connaît plus : git-repo supprimerait son arbre. Rien ne
    commence après `echeance` (« saute_delai »), et le « repo sync » ne
    dure pas au-delà. Rend un enregistrement par chemin.
    """
    par_chemin = {n["chemin"]: n for n in nouveaux}
    resultats = []
    a_cloner = []
    for chemin in sorted(chemins):
        n = par_chemin.get(chemin, {"chemin": chemin})
        res = {
            "chemin": chemin,
            "nom": n.get("nom"),
            "etat": None,
            "arrivee": None,
            "sortie": "",
            "motif": None,
        }
        dossier = os.path.join(racine, chemin)
        if os.path.lexists(dossier) and (
            not os.path.isdir(dossier) or os.listdir(dossier)
        ):
            res["etat"] = "clone_chemin_occupe"
        else:
            a_cloner.append(res)
        resultats.append(res)
    if not a_cloner:
        return resultats
    if echue(echeance):
        for res in a_cloner:
            res.update(etat="saute_delai", motif=MOTIF_DELAI)
        return resultats
    code, sortie = lancer_repo(racine, ["list", "-p"], borne(300, echeance))
    connus = set(x.strip() for x in sortie.splitlines() if x.strip())
    anciens = set()
    try:
        with open(os.path.join(racine, ".repo", "project.list")) as fh:
            anciens = set(x.strip() for x in fh if x.strip())
    except OSError:
        pass
    sortants = anciens - connus
    if code or sortants:
        motif = (
            f"the manifest drops {len(sortants)} projects: git-repo would"
            " delete their worktrees; run make repo_configure_all by hand"
            if not code
            else f"repo list failed: {queue(sortie)[-200:]}"
        )
        for res in a_cloner:
            res.update(etat="clone_refuse", motif=motif)
        return resultats
    code, sortie = lancer_repo(
        racine,
        [
            "sync",
            "-c",
            "--no-manifest-update",
            "--no-repo-verify",
            "--fail-fast",
            "-j",
            str(jobs or 4),
            *[r["chemin"] for r in a_cloner],
        ],
        borne(DELAI_SYNC, echeance),
    )
    for res in a_cloner:
        dossier = os.path.join(racine, res["chemin"])
        head = None
        if repo_state.a_un_git(dossier):
            head, _b, _e = repo_state.lire_tete(dossier)
        res["etat"] = "clone" if head else "clone_echoue"
        res["arrivee"] = head
        res["sortie"] = queue(sortie)
    return resultats


# ── dépendances ─────────────────────────────────────────────────────────


def commande_poetry(venv):
    """La commande « poetry install » à lancer à la main dans `venv` : le
    venv activé, sans quoi Poetry installe dans l'interpréteur de base (voir
    `_installer`)."""
    return f"source {venv}/bin/activate && poetry install --no-root"


def _installer(racine, horodatage=None, en_direct=False, echeance=None):
    """« poetry install --no-root » dans le venv Odoo. Rend (charge, code).

    « VIRTUAL_ENV » est indispensable : « poetry.toml » coupe la création
    de venv, et sans activation Poetry installe dans l'interpréteur de base.
    Le dossier « artifacts » qu'un pip laisse fait échouer le « poetry
    install » suivant : il est retiré s'il n'existait pas avant. La sortie
    va dans « deps.log » du dossier de la passe, URL sans secret ; le délai
    est DELAI_DEPS, borné par `echeance`.
    """
    couple = repo_state.lire_fichier(racine, ".erplibre-version") or ""
    venv = os.path.join(racine, f".venv.{couple}")
    poetry = os.path.join(venv, "bin", "poetry")
    horodatage = horodatage or maintenant_horodatage()
    dossier = dossier_passe(horodatage, racine)
    charge = {
        "schema": SCHEMA,
        "command": "install-deps",
        "venv": os.path.relpath(venv, racine),
        "commande": commande_poetry(f".venv.{couple}"),
        "code": None,
        "sortie": "",
        "dossier": os.path.relpath(dossier, racine),
        "error": None,
    }
    if not couple or not os.path.isfile(poetry):
        charge["error"] = (
            f"poetry not found: {os.path.relpath(poetry, racine)}"
        )
        return charge, EXIT_DEPS
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP")
    }
    env.update(
        VIRTUAL_ENV=venv,
        PATH=os.path.join(venv, "bin") + os.pathsep + env.get("PATH", ""),
        PYTHON_KEYRING_BACKEND="keyring.backends.null.Keyring",
        POETRY_NO_INTERACTION="1",
        GIT_TERMINAL_PROMPT="0",
    )
    artifacts = os.path.join(racine, "artifacts")
    artifacts_avant = os.path.exists(artifacts)
    argv = [poetry, "install", "--no-root", "--no-interaction"]
    try:
        charge["code"], sortie = lancer(
            argv,
            borne(DELAI_DEPS, echeance),
            racine,
            env,
            en_direct=en_direct,
        )
    finally:
        if not artifacts_avant and os.path.isdir(artifacts):
            shutil.rmtree(artifacts, True)
    charge["sortie"] = queue(sortie)
    os.makedirs(dossier, exist_ok=True)
    with open(os.path.join(dossier, "deps.log"), "w") as fh:
        fh.write(sans_secrets(sortie) + "\n")
    if charge["code"]:
        charge["error"] = "poetry install failed"
        return charge, EXIT_DEPS
    return charge, EXIT_OK


def installer_dependances(
    racine, version=None, horodatage=None, en_direct=False
):
    """`_installer` sous le verrou du checkout. Rend (charge, code)."""
    try:
        with verrou(racine):
            return _installer(racine, horodatage, en_direct)
    except Occupe:
        return {"command": "install-deps", "error": "busy"}, EXIT_OCCUPE


# ── la passe ────────────────────────────────────────────────────────────


def passe(
    racine,
    version,
    mode="manifeste",
    strategie="rebase",
    attendus=(),
    epingles=None,
    approfondir=False,
    cloner=False,
    attendus_clone=(),
    approuver_deps=False,
    chemin_seul=None,
    horodatage=None,
    regenerer=None,
    jobs=None,
    delai=DELAI_GIT,
    budget=None,
):
    """Refait l'essai à sec, vérifie le consentement, intègre, inscrit.

    `attendus` sont les chemins consentis, `epingles` {chemin: {cible_sha,
    head}} l'état montré de chacun (voir `repo_apply.lire_attendu`),
    `attendus_clone` les nouveaux dépôts consentis, `budget` les secondes
    après lesquelles plus rien ne commence (voir la docstring du module).
    Rend (charge, code) ; rien n'est écrit avant que le consentement ne
    tienne.
    """
    echeance = echeance_de(budget)
    horodatage = horodatage or maintenant_horodatage()
    charge = {
        "schema": SCHEMA,
        "command": "apply",
        "version": version,
        "mode": mode,
        "strategie": strategie,
        "chemin_seul": chemin_seul,
        "horodatage": None,
        "dossier": None,
        "plan": [],
        "attendus": sorted(set(attendus)),
        "derives": [],
        "approuve": {
            "approfondir": bool(approfondir),
            "cloner": bool(cloner),
            "dependances": bool(approuver_deps),
        },
        "resultats": [],
        "manifeste": None,
        "clones": [],
        "dependances": None,
        "deps": None,
        "budget_epuise": False,
        "error": None,
    }
    if not version or repo_upgrade.version_active(racine) != version:
        charge["error"] = "confirm_mismatch"
        return charge, EXIT_USAGE
    try:
        with verrou(racine):
            return _passe(
                racine,
                charge,
                horodatage,
                epingles,
                attendus_clone,
                regenerer,
                jobs,
                delai,
                echeance,
            )
    except Occupe:
        charge["error"] = "busy"
        return charge, EXIT_OCCUPE


def _passe(
    racine,
    charge,
    horodatage,
    epingles,
    attendus_clone,
    regenerer,
    jobs,
    delai,
    echeance,
):
    dossier = dossier_passe(horodatage, racine)
    if os.path.exists(dossier):
        charge["error"] = "stamp_taken"
        return charge, EXIT_USAGE
    approuve = charge["approuve"]
    donnees, code = diagnostic(
        racine,
        charge["mode"],
        charge["strategie"],
        charge["chemin_seul"],
        regenerer,
        jobs,
        delai,
    )
    if code:
        charge["error"] = donnees.get("error")
        return charge, code
    par_chemin = {c["chemin"]: c for c in donnees["depots"]}
    plan = list(donnees["plan"])
    if approuve["approfondir"]:
        plan += donnees["plan_superficiel"]
    plan = sorted(plan)
    charge["plan"] = plan
    charge["dependances"] = donnees["dependances"]
    if plan != charge["attendus"]:
        charge["error"] = "plan_changed"
        return charge, EXIT_PLAN_CHANGE
    charge["derives"] = repo_apply.derives(
        [par_chemin[p] for p in plan], epingles
    )
    if charge["derives"]:
        charge["error"] = "plan_changed"
        return charge, EXIT_PLAN_CHANGE
    if approuve["cloner"] and sorted(donnees["plan_nouveaux"]) != sorted(
        set(attendus_clone)
    ):
        charge["error"] = "plan_changed"
        charge["derives"] = [
            {
                "chemin": None,
                "cle": "clones",
                "attendu": sorted(set(attendus_clone)),
                "trouve": donnees["plan_nouveaux"],
            }
        ]
        return charge, EXIT_PLAN_CHANGE
    manifeste_change = bool(
        donnees.get("manifeste") and donnees["manifeste"].get("changements")
    )
    if (
        not plan
        and not manifeste_change
        and not (approuve["cloner"] and donnees["plan_nouveaux"])
    ):
        charge["manifeste"] = public(donnees.get("manifeste"))
        return charge, EXIT_OK

    os.makedirs(dossier)
    charge["horodatage"] = horodatage
    charge["dossier"] = os.path.relpath(dossier, racine)
    resultats = []
    ecriture = threading.Lock()

    def inscrire(termine=False):
        """Inscrit la passe telle qu'elle est : après chaque dépôt, puis à
        la fin (« termine »)."""
        with ecriture:
            ecrire_passe(
                dossier,
                {
                    "horodatage": horodatage,
                    "termine": termine,
                    "version": charge["version"],
                    "mode": charge["mode"],
                    "strategie": charge["strategie"],
                    "chemin_seul": charge["chemin_seul"],
                    "approuve": approuve,
                    "diagnostic": public(donnees),
                    "resultats": list(resultats),
                    "manifeste": charge["manifeste"],
                    "clones": charge["clones"],
                    "dependances": charge["dependances"],
                    "budget_epuise": charge["budget_epuise"],
                },
            )

    def integrer_inscrit(chemin, attrs=None):
        res = integrer(
            racine,
            par_chemin[chemin],
            horodatage,
            charge["strategie"],
            approuve["approfondir"],
            attrs=attrs,
            delai=delai,
            echeance=echeance,
        )
        with ecriture:
            resultats.append(res)
        inscrire()
        return res

    inscrire()
    superficiels_sautes = [
        p for p in donnees["plan_superficiel"] if p not in plan
    ]
    if "." in plan:
        integrer_inscrit(".")
    clones = [p for p in plan if p != "."]
    regeneration = (
        charge["mode"] == "manifeste"
        and charge["chemin_seul"] is None
        and donnees.get("manifeste")
        and donnees["manifeste"].get("regenere")
    )
    integrer_clones = True
    if charge["mode"] == "manifeste" and charge["chemin_seul"] is None:
        if regeneration:
            regenerer_manifeste(racine, donnees, dossier, regenerer)
            integrer_clones = bool(donnees["manifeste"].get("ecrit"))
        else:
            integrer_clones = False
        charge["manifeste"] = public(donnees["manifeste"])
        inscrire()
    attrs_ecrits = {}
    if integrer_clones and regeneration:
        _r, attrs_ecrits = lire_projets(
            os.path.join(racine, repo_state.MANIFESTE_LOCAL)
        )
    if integrer_clones and clones:
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(
                pool.map(
                    lambda p: integrer_inscrit(p, attrs_ecrits.get(p)),
                    clones,
                )
            )
    for p in superficiels_sautes:
        res = enregistrement(par_chemin[p])
        res["etat"] = "saute_superficiel"
        resultats.append(res)
    ordre = {p: i for i, p in enumerate(plan + superficiels_sautes)}
    resultats.sort(key=lambda r: ordre.get(r["chemin"], len(ordre)))
    charge["resultats"] = resultats
    if approuve["cloner"] and integrer_clones and donnees["plan_nouveaux"]:
        charge["clones"] = cloner_nouveaux(
            racine,
            donnees["nouveaux"],
            donnees["plan_nouveaux"],
            jobs,
            echeance,
        )
        inscrire()
    racine_res = next((r for r in resultats if r["chemin"] == "."), None)
    if racine_res and racine_res.get("arrivee"):
        charge["dependances"] = dependances(
            racine, racine_res["depart"], racine_res["arrivee"]
        )
    else:
        charge["dependances"] = dependances(racine, None, None)
    charge["dependances"]["requirements_addons"] = donnees["dependances"][
        "requirements_addons"
    ]
    bloque = any(r["etat"] == "restauration_echouee" for r in resultats)
    code_deps = EXIT_OK
    if (
        approuve["dependances"]
        and charge["dependances"]["a_installer"]
        and not bloque
    ):
        if echue(echeance):
            charge["budget_epuise"] = True
        else:
            charge["deps"], code_deps = _installer(
                racine, horodatage, echeance=echeance
            )
    charge["budget_epuise"] = charge["budget_epuise"] or any(
        r.get("etat") == "saute_delai"
        for r in resultats + (charge["clones"] or [])
    )
    inscrire(termine=True)
    return charge, code_deps


# ── sauvegardes ─────────────────────────────────────────────────────────


def chemins_du_checkout(racine):
    """« . » puis les clones du manifeste local présents sur le disque."""
    projets, _r, _p = repo_state.definitions(racine)
    lst = ["."] if repo_state.a_un_git(racine) else []
    lst += sorted(
        p
        for p in projets
        if p != "." and repo_state.a_un_git(os.path.join(racine, p))
    )
    return lst


def lister_sauvegardes(racine, chemin_seul=None):
    """{"command": "list-backups", "sauvegardes": [...]}, en lecture seule.

    « branche » et « detache » viennent de l'enregistrement de la passe qui
    a posé la sauvegarde, None quand il ne la nomme pas."""
    lst = []
    passes_lues = {}
    for chemin in chemins_du_checkout(racine):
        if chemin_seul and chemin != chemin_seul:
            continue
        dossier = os.path.join(racine, chemin)
        out, _err, code = git(
            [
                "for-each-ref",
                "--format=%(refname:short)%09%(objectname)",
                "refs/heads/",
            ],
            dossier,
        )
        if code:
            continue
        head = repo_apply.sha_de(dossier, "HEAD")
        for ligne in out.splitlines():
            nom, _tab, sha = ligne.partition("\t")
            m = MOTIF_SAUVEGARDE.match(nom.strip())
            if not m:
                continue
            horodatage = m.group("horodatage")
            if horodatage not in passes_lues:
                passes_lues[horodatage] = lire_passe(horodatage, racine)
            record = enregistrement_de(
                passes_lues[horodatage], chemin, nom.strip()
            )
            lst.append(
                {
                    "chemin": chemin,
                    "nom": nom.strip(),
                    "sha": sha.strip(),
                    "horodatage": horodatage,
                    "actuel": head == sha.strip(),
                    "branche": (record or {}).get("branche"),
                    "detache": (record or {}).get("detache"),
                }
            )
    return {"schema": SCHEMA, "command": "list-backups", "sauvegardes": lst}


def enregistrement_de(passe_lue, chemin, nom):
    """L'enregistrement du dépôt `chemin` qui a posé la sauvegarde `nom`
    dans la passe `passe_lue`, ou None."""
    return next(
        (
            r
            for r in (passe_lue or {}).get("resultats") or []
            if r.get("chemin") == chemin and r.get("sauvegarde") == nom
        ),
        None,
    )


def lire_designation(racine, texte):
    """(chemin, nom) d'un « CHEMIN=NOM ». Lève ValueError sur un nom qui
    n'est pas une sauvegarde, LookupError sur un chemin inconnu."""
    chemin, egal, nom = (texte or "").partition("=")
    if not egal or not MOTIF_SAUVEGARDE.match(nom):
        raise ValueError(f"{texte}: expected PATH=<branch>_avant_pull_<stamp>")
    chemin = repo_state.normaliser(racine, chemin or ".")
    if chemin is None or chemin not in chemins_du_checkout(racine):
        raise LookupError(f"{texte}: unknown path")
    return chemin, nom


def restaurer_sauvegarde(racine, chemin, nom, delai=DELAI_GIT):
    """Ramène le dépôt `chemin` sur sa sauvegarde `nom`. Rend (charge, code).

    La passe de l'horodatage donne la branche ou la HEAD détachée où le
    dépôt se trouvait, et le commit où elle l'a laissé. Le retour exige la
    même branche, ou la HEAD détachée, un arbre sans modification suivie,
    et qu'aucun commit fait depuis ne quitte la branche (« head_deplacee »,
    voir `head_inchangee`). La branche de sauvegarde reste.
    """
    try:
        with verrou(racine):
            return _restaurer(racine, chemin, nom, delai)
    except Occupe:
        return {"command": "restore-backup", "error": "busy"}, EXIT_OCCUPE


def _restaurer(racine, chemin, nom, delai):
    dossier = os.path.join(racine, chemin)
    m = MOTIF_SAUVEGARDE.match(nom)
    res = {
        "chemin": chemin,
        "etat": None,
        "depart": repo_apply.sha_de(dossier, "HEAD"),
        "arrivee": None,
        "sauvegarde": nom,
        "manifeste_restaure": False,
    }
    charge = {
        "schema": SCHEMA,
        "command": "restore-backup",
        "resultats": [res],
    }
    sha = repo_apply.sha_de(dossier, f"refs/heads/{nom}")
    if not sha:
        res["etat"] = "sauvegarde_absente"
        return charge, EXIT_CIBLE
    passe_lue = lire_passe(m.group("horodatage"), racine)
    record = enregistrement_de(passe_lue, chemin, nom)
    sale, _n = etat_arbre(dossier, delai)
    if sale is not False:
        res["etat"] = "refuse_sale"
        return charge, EXIT_OK
    courante = repo_apply.branche_courante(dossier)
    if record is not None:
        attendue = None if record.get("detache") else record.get("branche")
    else:
        attendue = courante if courante == m.group("branche") else None
        if courante is not None and attendue is None:
            res["etat"] = "branche_changee"
            return charge, EXIT_OK
    if courante != attendue:
        res["etat"] = "branche_changee"
        return charge, EXIT_OK
    if not head_inchangee(dossier, res["depart"], sha, record, delai):
        res["etat"] = "head_deplacee"
        return charge, EXIT_OK
    if courante:
        geste = ["reset", "--keep", sha]
    else:
        geste = ["checkout", "--detach", sha]
    out, err, code = git(geste, dossier, delai, ecrit=True)
    if code:
        res["etat"] = "erreur"
        res["sortie"] = queue(out + err)
        return charge, EXIT_OK
    res.update(etat="revenu", arrivee=sha)
    manifeste = (passe_lue or {}).get("manifeste") or {}
    if (
        chemin == "."
        and manifeste.get("ecrit")
        and manifeste.get("copie_avant")
    ):
        copie = os.path.join(racine, manifeste["copie_avant"])
        if os.path.isfile(copie):
            local = os.path.join(racine, repo_state.MANIFESTE_LOCAL)
            temporaire = os.path.join(
                os.path.dirname(local), ".erplibre_manifest.xml.tmp"
            )
            shutil.copyfile(copie, temporaire)
            os.replace(temporaire, local)
            res["manifeste_restaure"] = True
    if passe_lue is not None:
        passe_lue.setdefault("retours", []).append(
            dict(res, date=repo_state.maintenant())
        )
        _ecrire_json(
            os.path.join(
                dossier_passe(m.group("horodatage"), racine), "passe.json"
            ),
            passe_lue,
        )
    return charge, EXIT_OK


def head_inchangee(dossier, head, sha, record, delai=DELAI_GIT):
    """Vrai quand revenir de `head` sur la sauvegarde `sha` n'ôte aucun
    commit de la branche : HEAD est le commit où la passe (`record`) a
    laissé le dépôt, ou `sha` est un ancêtre de HEAD et tout commit de
    « sha..HEAD » est sur une référence de suivi — un commit local fait
    depuis, ou rejoué par un rebase, n'y est pas."""
    if head and head == (record or {}).get("arrivee"):
        return True
    if not head or repo_apply.est_ancetre(dossier, sha, head) is not True:
        return False
    out, _err, code = git(
        ["rev-list", "--count", f"{sha}..{head}", "--not", "--remotes"],
        dossier,
        delai,
    )
    return not code and out.strip() == "0"


def supprimer_sauvegarde(racine, chemin, nom, delai=DELAI_GIT):
    """Supprime la branche de sauvegarde `nom` du dépôt `chemin`, sauf
    quand elle est la branche extraite. Rend (charge, code)."""
    try:
        with verrou(racine):
            dossier = os.path.join(racine, chemin)
            res = {"chemin": chemin, "sauvegarde": nom, "etat": None}
            charge = {
                "schema": SCHEMA,
                "command": "delete-backup",
                "resultats": [res],
            }
            if not repo_apply.branche_existe(dossier, nom):
                res["etat"] = "sauvegarde_absente"
                return charge, EXIT_CIBLE
            if repo_apply.branche_courante(dossier) == nom:
                res["etat"] = "refuse_courante"
                return charge, EXIT_OK
            out, err, code = git(
                ["branch", "-D", nom], dossier, delai, ecrit=True
            )
            res["etat"] = "erreur" if code else "supprime"
            if code:
                res["sortie"] = queue(out + err)
            return charge, EXIT_OK
    except Occupe:
        return {"command": "delete-backup", "error": "busy"}, EXIT_OCCUPE


# ── rendu pour le menu ──────────────────────────────────────────────────

LIBELLES_VERDICT = {
    "a_jour": ("up to date", "dim"),
    "en_avance": ("ahead of the target", "dim"),
    "avance_rapide": ("fast-forward possible", "ok"),
    "diverge": ("diverged", "watch"),
    "bascule": ("switch to the manifest target", "ok"),
    "superficiel": ("shallow: deepening needed", "watch"),
    "detache": ("detached HEAD: skipped", "dim"),
    "sans_cible": ("no target", "dim"),
    "cible_absente": ("target missing", "broken"),
    "fetch_echoue": ("fetch failed", "broken"),
    "operation_en_cours": ("operation in progress: skipped", "broken"),
    "absent": ("not cloned", "dim"),
    "erreur": ("error", "broken"),
}

LIBELLES_ETAT = {
    "avance": ("fast-forwarded (one)", "ok"),
    "tire": ("pulled", "ok"),
    "a_jour": ("up to date", "dim"),
    "conflit_annule": ("conflict: put back", "watch"),
    "stash_garde": ("stash kept", "watch"),
    "refuse_ff": ("diverged: fast-forward refused", "watch"),
    "saute_detache": ("detached HEAD: skipped", "dim"),
    "saute_superficiel": ("shallow: not deepened", "dim"),
    "saute_operation": ("operation in progress: skipped", "broken"),
    "saute_delai": ("not started: time budget exhausted", "watch"),
    "superficiel_sans_base": ("shallow: no base found", "watch"),
    "sauvegarde_existante": ("backup already exists", "watch"),
    "restauration_echouee": ("restore failed: fix by hand", "broken"),
    "erreur": ("error", "broken"),
    "clone": ("cloned", "ok"),
    "clone_echoue": ("clone failed", "broken"),
    "clone_refuse": ("clone refused", "watch"),
    "clone_chemin_occupe": ("path already occupied", "watch"),
}

LIBELLES_MODE = {"manifeste": "manifest", "branche": "branches"}

# Les codes d'erreur d'une passe que le menu peut afficher.
LIBELLES_ERREUR = {
    "manifeste_different": (
        "The regenerated manifest differs from the dry run: it was not"
        " written and no clone was integrated."
    ),
    "busy": "Another pull is running on this checkout.",
    "stamp_taken": "A pass with this stamp already exists: retry in a minute.",
    "confirm_mismatch": "The version typed does not match the active one.",
    "plan_changed": "The remote moved since the dry run: nothing was written.",
    "bad stamp": "The stamp of the pass is not YYYYMMDDTHHMM.",
    "poetry install failed": "poetry install failed.",
}


def _libelle(table, cle, colour):
    texte, genre = table.get(cle, (cle, "dim"))
    return paint(t(texte), genre, colour)


def libelle_erreur(code):
    """Le texte traduit d'un code d'erreur de la passe : une régénération
    ratée garde sa ligne, un code inconnu reste tel quel."""
    if not code:
        return ""
    prefixe = "regeneration failed: "
    if code.startswith(prefixe):
        return f"{t('Manifest regeneration failed:')} {code[len(prefixe):]}"
    if code.startswith("poetry not found: "):
        return f"{t('poetry not found:')} {code[len('poetry not found: '):]}"
    return t(LIBELLES_ERREUR.get(code, code))


def render_diagnostic(donnees, colour=True):
    """L'essai à sec en texte : une ligne par dépôt, puis les sections."""
    mode = donnees.get("mode")
    lignes = [
        f"⬇️  {t('Pull the repositories')} — Odoo {donnees.get('version')}"
        f" · {t(LIBELLES_MODE.get(mode, mode or ''))}"
        f" · {donnees.get('strategie')}"
    ]
    depots = donnees.get("depots") or []
    largeur = max([len(c["chemin"]) for c in depots] + [10])
    for c in depots:
        cible = (c.get("cible") or "").replace("refs/remotes/", "")
        cible = cible.replace(ESPACE_TAGS, "")
        if manifest_freeze.is_sha(cible):
            cible = cible[:12]
        origine = c.get("branche") or "HEAD"
        ligne = (
            f"  {c['chemin']:<{largeur}}  {origine} → {cible or '-'}"
            f"  {_libelle(LIBELLES_VERDICT, c['verdict'], colour)}"
        )
        nos = c.get("locaux") if c.get("locaux") is not None else c.get("nos")
        if nos is not None and c.get("retard") is not None:
            ligne += f"  +{nos}/-{c['retard']}"
        drapeaux = []
        if c.get("sale"):
            drapeaux.append(t("stash") if c.get("stash_prevu") else t("dirty"))
        if c.get("superficiel"):
            drapeaux.append(t("shallow"))
        if drapeaux:
            ligne += f"  [{', '.join(drapeaux)}]"
        if c.get("motif") or c.get("erreur"):
            ligne += (
                f"  {paint(c.get('motif') or c.get('erreur'), 'dim', colour)}"
            )
        lignes.append(ligne)
        for commit in (c.get("entrants") or [])[:10]:
            lignes.append(
                f"  {'':<{largeur}}    {commit['sha'][:12]} {commit['subject']}"
            )
        if c.get("entrants_total", 0) > 10:
            lignes.append(
                f"  {'':<{largeur}}    … {c['entrants_total']}"
                f" {t('Incoming commits')}"
            )
        if c.get("ecrases"):
            avis = t(
                "Ignored local files the target overwrites (copied first):"
            )
            lignes.append(
                f"  {'':<{largeur}}    ⚠  {paint(avis, 'watch', colour)}"
            )
            lignes += [f"  {'':<{largeur}}       {x}" for x in c["ecrases"]]
    manifeste = donnees.get("manifeste") or {}
    if manifeste.get("changements"):
        lignes.append("")
        lignes.append(f"  {t('Regenerated manifest')}:")
        genres = {
            "ajout": "entry added",
            "retrait": "entry removed",
            "change": "entry changed",
        }
        for x in manifeste["changements"]:
            genre = t(genres.get(x["genre"], x["genre"]))
            lignes.append(
                f"    {genre:<15} {x['chemin']}  {x['avant'] or '-'}"
                f" → {x['apres'] or '-'}"
            )
    if manifeste.get("erreur"):
        lignes.append(
            f"  ⚠  {paint(libelle_erreur(manifeste['erreur']), 'broken', colour)}"
        )
    if donnees.get("nouveaux"):
        lignes.append("")
        lignes.append(f"  {t('New repositories')}:")
        for n in donnees["nouveaux"]:
            occupe = f"  ({t('path already occupied')})" if n["occupe"] else ""
            lignes.append(f"    {n['chemin']}  {n.get('url') or ''}{occupe}")
        avis = t(
            "Cloned by a repo sync restricted to their paths, only when"
            " asked."
        )
        lignes.append(f"    {paint(avis, 'dim', colour)}")
    if donnees.get("retires"):
        lignes.append("")
        lignes.append(f"  {t('Retired from the manifest (kept on disk)')}:")
        lignes += [f"    {x}" for x in donnees["retires"]]
    deps = donnees.get("dependances") or {}
    if deps.get("fichiers"):
        lignes.append("")
        lignes.append(f"  {t('Python dependencies changed')}:")
        lignes += [f"    {x}" for x in deps["fichiers"]]
        if deps.get("changement_de_version"):
            avis = t("The Python/Odoo couple changes: run make install.")
            lignes.append(f"    ⚠  {avis}")
        else:
            lignes.append(f"    {deps.get('commande')}")
    if donnees.get("plan_superficiel"):
        lignes.append("")
        avis = t("Shallow clones: deepening downloads history (network).")
        lignes.append(f"  ⚠  {avis}")
        lignes += [f"    {x}" for x in donnees["plan_superficiel"]]
    return "\n".join(lignes)


def render_passe(charge, colour=True):
    """Le résultat d'une passe en texte : une ligne par dépôt."""
    lignes = []
    if charge.get("error"):
        lignes.append(
            f"⚠  {paint(libelle_erreur(charge['error']), 'broken', colour)}"
        )
    for res in charge.get("resultats") or []:
        ligne = (
            f"  {res['chemin']:<44} "
            f"{_libelle(LIBELLES_ETAT, res['etat'], colour)}"
        )
        if res.get("sauvegarde"):
            ligne += f"  [{res['sauvegarde']}]"
        lignes.append(ligne)
        for fichier in res.get("conflits") or []:
            lignes.append(f"      {fichier}")
        if (res.get("stash") or {}).get("commande"):
            lignes.append(f"      {res['stash']['commande']}")
        if res.get("ecrases") and res.get("copie_ecrases"):
            lignes.append(
                f"      {t('Overwritten ignored files copied to')}"
                f" {res['copie_ecrases']}"
            )
        if res.get("motif"):
            lignes.append(f"      {res['motif']}")
    manifeste = charge.get("manifeste") or {}
    if manifeste.get("ecrit"):
        lignes.append(f"  {t('Regenerated manifest')}: ✅")
    elif manifeste.get("erreur"):
        lignes.append(
            f"  {t('Regenerated manifest')}:"
            f" {paint(libelle_erreur(manifeste['erreur']), 'broken', colour)}"
        )
    for res in charge.get("clones") or []:
        lignes.append(
            f"  {res['chemin']:<44} "
            f"{_libelle(LIBELLES_ETAT, res['etat'], colour)}"
        )
        if res.get("motif"):
            lignes.append(f"      {res['motif']}")
    if charge.get("budget_epuise"):
        avis = t(
            "The time budget ran out: the steps not started are listed;"
            " run a new pull for them."
        )
        lignes.append(f"  ⚠  {paint(avis, 'watch', colour)}")
    return "\n".join(lignes)


# ── ligne de commande ───────────────────────────────────────────────────


def analyser(argv):
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Pull the deployed code: a pinned git pull of every repository"
            " (JSON output). Nothing is ever pushed."
        )
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument(
        "--dry-run",
        action="store_true",
        help="fetch and show what a pull would do; nothing moves",
    )
    action.add_argument(
        "--apply",
        action="store_true",
        help="pull the repositories consented with --expect",
    )
    action.add_argument(
        "--list-backups", action="store_true", help="list the backup branches"
    )
    action.add_argument(
        "--restore-backup",
        metavar="PATH=NAME",
        help="move a repository back to one of its backup branches",
    )
    action.add_argument(
        "--delete-backup", metavar="PATH=NAME", help="delete a backup branch"
    )
    action.add_argument(
        "--install-deps",
        action="store_true",
        help="poetry install --no-root in the Odoo virtual environment",
    )
    parser.add_argument("--mode", choices=MODES, default="manifeste")
    parser.add_argument("--strategy", choices=STRATEGIES, default="rebase")
    parser.add_argument(
        "--path",
        metavar="PATH",
        help="one repository, relative to the root; '.' is the ERPLibre root",
    )
    parser.add_argument(
        "--confirm",
        metavar="VERSION",
        default="",
        help="the active Odoo version, typed again (every writing action)",
    )
    parser.add_argument(
        "--expect",
        metavar="PATH[=TARGET_SHA:HEAD_SHA]",
        action="append",
        default=[],
        help="a repository of the plan shown by the dry run, optionally"
        " pinned to the target and the HEAD it showed (repeatable)",
    )
    parser.add_argument(
        "--expect-clone",
        metavar="PATH",
        action="append",
        default=[],
        help="a new repository shown by the dry run (repeatable)",
    )
    parser.add_argument(
        "--approve-deepen",
        action="store_true",
        help="deepen the shallow clones (network)",
    )
    parser.add_argument(
        "--approve-clone",
        action="store_true",
        help="clone the new repositories of the manifest",
    )
    parser.add_argument(
        "--approve-deps",
        action="store_true",
        help="run poetry install when the Python dependencies changed",
    )
    parser.add_argument(
        "--pass",
        dest="passe",
        metavar="STAMP",
        help="apply: the stamp of the pass (YYYYMMDDTHHMM, default now);"
        " install-deps: record into that pass directory",
    )
    parser.add_argument(
        "--budget",
        type=int,
        default=None,
        metavar="SECONDS",
        help="apply: start no repository, deepening, clone or install"
        " after that many seconds",
    )
    parser.add_argument("--root", default=REPO_ROOT)
    parser.add_argument("--timeout", type=int, default=DELAI_GIT)
    parser.add_argument("--jobs", type=int, default=None)
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument(
        "--json",
        action="store_true",
        help="accepted for compatibility: the output is always JSON",
    )
    return parser.parse_args(argv)


def executer(args, racine):
    """(charge, code) de l'action demandée par `args`."""
    version = repo_upgrade.version_active(racine)
    ecrit = not (args.dry_run or args.list_backups)
    if ecrit and (not version or args.confirm != version):
        return {"version": version, "error": "confirm_mismatch"}, EXIT_USAGE
    if args.list_backups:
        chemin = (
            repo_state.normaliser(racine, args.path) if args.path else None
        )
        return lister_sauvegardes(racine, chemin), EXIT_OK
    if args.dry_run:
        try:
            with verrou(racine):
                donnees, code = diagnostic(
                    racine,
                    args.mode,
                    args.strategy,
                    args.path,
                    jobs=args.jobs,
                    delai=args.timeout,
                )
        except Occupe:
            return {"command": "dry-run", "error": "busy"}, EXIT_OCCUPE
        return public(donnees), code
    if args.passe and not MOTIF_HORODATAGE.match(args.passe):
        commande = "install-deps" if args.install_deps else "apply"
        return {"command": commande, "error": "bad stamp"}, EXIT_USAGE
    if args.install_deps:
        return installer_dependances(racine, version, args.passe)
    if args.restore_backup or args.delete_backup:
        texte = args.restore_backup or args.delete_backup
        commande = "restore-backup" if args.restore_backup else "delete-backup"
        try:
            chemin, nom = lire_designation(racine, texte)
        except ValueError as exc:
            return {"command": commande, "error": str(exc)}, EXIT_USAGE
        except LookupError as exc:
            return {"command": commande, "error": str(exc)}, EXIT_CIBLE
        if args.restore_backup:
            return restaurer_sauvegarde(racine, chemin, nom, args.timeout)
        return supprimer_sauvegarde(racine, chemin, nom, args.timeout)
    try:
        lus = [repo_apply.lire_attendu(x) for x in args.expect]
    except ValueError as exc:
        return {"command": "apply", "error": str(exc)}, EXIT_USAGE
    chemin_seul = None
    if args.path:
        chemin_seul = repo_state.normaliser(racine, args.path)
        if chemin_seul is None:
            return {"command": "apply", "error": "unknown path"}, EXIT_CIBLE
    return passe(
        racine,
        version,
        args.mode,
        args.strategy,
        attendus=[c for c, _e in lus],
        epingles={c: e for c, e in lus if e},
        approfondir=args.approve_deepen,
        cloner=args.approve_clone,
        attendus_clone=args.expect_clone,
        approuver_deps=args.approve_deps,
        chemin_seul=chemin_seul,
        horodatage=args.passe,
        jobs=args.jobs,
        delai=args.timeout,
        budget=args.budget,
    )


def main(argv=None):
    args = analyser(sys.argv[1:] if argv is None else argv)
    racine = os.path.realpath(args.root)
    try:
        charge, code = executer(args, racine)
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        charge = {"error": f"internal: {type(exc).__name__}: {exc}"}
        code = EXIT_INTERNE
    charge = dict(public(charge))
    charge.setdefault("schema", SCHEMA)
    charge.setdefault(
        "command",
        (
            "dry-run"
            if args.dry_run
            else (
                "apply"
                if args.apply
                else (
                    "list-backups"
                    if args.list_backups
                    else (
                        "install-deps"
                        if args.install_deps
                        else (
                            "restore-backup"
                            if args.restore_backup
                            else "delete-backup"
                        )
                    )
                )
            )
        ),
    )
    json.dump(
        charge,
        sys.stdout,
        ensure_ascii=False,
        indent=2 if args.pretty else None,
        default=sorted,
    )
    sys.stdout.write("\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
