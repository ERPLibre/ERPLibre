#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'espace qu'on peut récupérer sur un poste de développement, et son
effacement sous garde-fous.

`candidats()` cherche, sans rien toucher, quatre sortes de choses :
 - des CACHES qui se reconstruisent seuls : pip, Poetry, npm, go-build, et
   dans le dépôt les __pycache__, htmlcov/ et .coverage.* ;
 - des RESTES dans /tmp : ce qu'un lanceur ou un montage interrompu y a
   laissé, à soi, inactif depuis `jours` jours ;
 - des FILESTORES d'Odoo dont la base n'existe plus, et les sessions web
   périmées ;
 - des VENVS d'une autre version d'Odoo que celle du checkout.

`effacer()` n'efface que ce qu'on lui passe, et REVÉRIFIE chaque chemin
juste avant : entre la liste et la confirmation, un fichier a pu changer de
propriétaire, devenir un lien, ou un filestore retrouver sa base.

Les garde-fous (`refus()`) : un chemin effaçable est à l'utilisateur
courant, n'est pas un lien et n'en traverse aucun, se trouve SOUS une des
racines permises sans en être une, et n'est jamais dans private/ ni dans
tasks/ du dépôt. private/ porte les seules données de client du dépôt, et
tasks/ le travail en cours : ni l'un ni l'autre ne se reconstruit.

Ce module ne rend que des faits ; les phrases appartiennent au menu.
"""

import os
import shutil
import stat
import time
from dataclasses import dataclass, field

CACHE = "cache"
TMP = "tmp"
FILESTORE = "filestore"
SESSIONS = "sessions"
VENV = "venv"

# Les caches de l'utilisateur, sous $HOME. pypoetry/cache et non pypoetry :
# à côté vivent virtualenvs/, qui sont des environnements, pas un cache.
CACHES_HOME = (
    ".cache/pip",
    ".cache/pypoetry/cache",
    ".npm/_cacache",
    ".cache/go-build",
)

# Les restes de /tmp : un nom posé par un outil connu, jamais un motif large.
PREFIXES_TMP = ("run_unit_test.", "tmp", "sshfs_")

# En deçà, un filestore sans base est signalé comme peut-être en création.
RECENT = 86400

# Ce que le parcours du dépôt n'ouvre pas : ce qui n'est pas un résidu, ou
# ce qui ne se touche jamais.
ELAGUES_DEPOT = {".git", ".repo", "private", "tasks", "node_modules"}


@dataclass
class Candidat:
    """Une chose effaçable : une catégorie, un ou plusieurs chemins."""

    categorie: str
    nom: str
    chemins: list = field(default_factory=list)
    taille: int = 0
    # Secondes depuis la dernière modification de ce qu'il contient.
    age: float = 0.0
    # Coché d'avance dans le formulaire : seulement ce qui se reconstruit.
    coche: bool = False
    # Ce qu'il en coûte d'effacer, quand ce n'est pas rien.
    mise_en_garde: str = ""


def mesurer(chemin):
    """(octets, date de modification la plus récente) sous `chemin`, sans
    suivre aucun lien. Un fichier illisible compte pour zéro."""
    total = 0
    recent = 0.0
    try:
        st = os.lstat(chemin)
    except OSError:
        return 0, 0.0
    total += st.st_blocks * 512 if hasattr(st, "st_blocks") else st.st_size
    recent = st.st_mtime
    if not stat.S_ISDIR(st.st_mode):
        return total, recent
    for dossier, sous, fichiers in os.walk(chemin, followlinks=False):
        for nom in sous + fichiers:
            try:
                st = os.lstat(os.path.join(dossier, nom))
            except OSError:
                continue
            total += (
                st.st_blocks * 512 if hasattr(st, "st_blocks") else st.st_size
            )
            recent = max(recent, st.st_mtime)
    return total, recent


def _candidat(categorie, nom, chemins, maintenant, **kw):
    taille = 0
    recent = 0.0
    for c in chemins:
        octets, date = mesurer(c)
        taille += octets
        recent = max(recent, date)
    return Candidat(
        categorie,
        nom,
        list(chemins),
        taille,
        max(0.0, maintenant - recent) if recent else 0.0,
        **kw,
    )


def caches(racine, home):
    """Les caches de l'utilisateur, puis les résidus de construction du
    dépôt : __pycache__, htmlcov/, .coverage.*."""
    maintenant = time.time()
    trouves = []
    for rel in CACHES_HOME:
        chemin = os.path.join(home, rel)
        if os.path.isdir(chemin) and not os.path.islink(chemin):
            trouves.append(
                _candidat(CACHE, rel, [chemin], maintenant, coche=True)
            )
    pycaches = []
    for dossier, sous, _fichiers in os.walk(racine):
        # Un venv porte ses propres __pycache__ : ils partent avec lui.
        sous[:] = [
            s
            for s in sous
            if s not in ELAGUES_DEPOT
            and not s.startswith(".venv")
            and not os.path.islink(os.path.join(dossier, s))
        ]
        if "__pycache__" in sous:
            pycaches.append(os.path.join(dossier, "__pycache__"))
            sous.remove("__pycache__")
    if pycaches:
        trouves.append(
            _candidat(CACHE, "__pycache__", pycaches, maintenant, coche=True)
        )
    couverture = [
        os.path.join(racine, n)
        for n in sorted(os.listdir(racine))
        if n == "htmlcov" or n.startswith(".coverage.")
    ]
    if couverture:
        trouves.append(
            _candidat(CACHE, "coverage", couverture, maintenant, coche=True)
        )
    return trouves


def restes_tmp(tmp, uid, jours):
    """Ce que des outils ont laissé dans `tmp`, à `uid`, inactif depuis
    `jours` jours. Un point de montage sshfs ne compte que VIDE et démonté :
    effacer sous un montage actif effacerait sur la machine distante."""
    maintenant = time.time()
    seuil = jours * 86400
    trouves = []
    try:
        noms = sorted(os.listdir(tmp))
    except OSError:
        return trouves
    for nom in noms:
        if not nom.startswith(PREFIXES_TMP):
            continue
        chemin = os.path.join(tmp, nom)
        try:
            st = os.lstat(chemin)
        except OSError:
            continue
        if st.st_uid != uid or stat.S_ISLNK(st.st_mode):
            continue
        if nom.startswith("sshfs_"):
            if os.path.ismount(chemin) or os.listdir(chemin):
                continue
        candidat = _candidat(TMP, nom, [chemin], maintenant)
        if candidat.age >= seuil:
            trouves.append(candidat)
    return trouves


def odoo(data_dir, bases, jours):
    """Les filestores dont la base n'existe plus, et les sessions web
    inactives depuis `jours` jours.

    `bases` est la liste des bases que PostgreSQL connaît. None — base
    injoignable — ne propose AUCUN filestore : sans la liste, un filestore
    vivant ne se distingue pas d'un orphelin."""
    maintenant = time.time()
    trouves = []
    if not data_dir:
        return trouves
    filestore = os.path.join(data_dir, "filestore")
    if bases is not None and os.path.isdir(filestore):
        for nom in sorted(os.listdir(filestore)):
            chemin = os.path.join(filestore, nom)
            if nom in bases or not os.path.isdir(chemin):
                continue
            if os.path.islink(chemin):
                continue
            candidat = _candidat(FILESTORE, nom, [chemin], maintenant)
            # Un filestore récent peut précéder sa base de quelques instants :
            # celle-ci se crée peut-être en ce moment même.
            if candidat.age < RECENT:
                candidat.mise_en_garde = "recent"
            trouves.append(candidat)
    sessions = os.path.join(data_dir, "sessions")
    if os.path.isdir(sessions):
        seuil = jours * 86400
        vieilles = []
        for dossier, _sous, fichiers in os.walk(sessions):
            for nom in fichiers:
                chemin = os.path.join(dossier, nom)
                try:
                    st = os.lstat(chemin)
                except OSError:
                    continue
                if maintenant - st.st_mtime >= seuil:
                    vieilles.append(chemin)
        if vieilles:
            trouves.append(
                _candidat(SESSIONS, "sessions", vieilles, maintenant)
            )
    return trouves


def venvs(racine, actif):
    """Les venvs d'une autre version d'Odoo que `actif` ; jamais
    .venv.erplibre, qui fait tourner TODO lui-même."""
    maintenant = time.time()
    trouves = []
    for nom in sorted(os.listdir(racine)):
        chemin = os.path.join(racine, nom)
        if not nom.startswith(".venv.odoo") or nom == actif:
            continue
        if os.path.isdir(chemin) and not os.path.islink(chemin):
            trouves.append(
                _candidat(
                    VENV,
                    nom,
                    [chemin],
                    maintenant,
                    mise_en_garde="reinstall",
                )
            )
    return trouves


def racines_permises(racine, home, tmp, data_dir):
    """Les seuls répertoires sous lesquels on efface."""
    permises = [os.path.join(home, rel) for rel in CACHES_HOME]
    permises += [racine, tmp]
    if data_dir:
        permises += [
            os.path.join(data_dir, "filestore"),
            os.path.join(data_dir, "sessions"),
        ]
    return [os.path.realpath(p) for p in permises]


def refus(chemin, racine, racines, uid):
    """None si `chemin` peut être effacé, sinon la raison, en un mot."""
    absolu = os.path.abspath(chemin)
    # Un lien N'IMPORTE OÙ sur le chemin le ferait mener ailleurs que là
    # où on croit effacer.
    if os.path.realpath(absolu) != absolu:
        return "link"
    try:
        st = os.lstat(absolu)
    except OSError:
        return "missing"
    if st.st_uid != uid:
        return "owner"
    racine = os.path.realpath(racine)
    for garde in ("private", "tasks"):
        protege = os.path.join(racine, garde)
        if absolu == protege or absolu.startswith(protege + os.sep):
            return "protected"
    if not any(absolu.startswith(r.rstrip(os.sep) + os.sep) for r in racines):
        return "outside"
    return None


def effacer(candidats, racine, racines, uid, bases=None):
    """Efface les chemins des `candidats`, chacun revérifié juste avant.

    `bases` est la liste des bases relue JUSTE AVANT l'appel : un filestore
    dont la base est apparue depuis la recherche est laissé. Sans elle
    (None), aucun filestore n'est effacé.

    Rend (octets libérés, [(chemin, raison)] des chemins laissés)."""
    liberes = 0
    laisses = []
    for candidat in candidats:
        for chemin in candidat.chemins:
            raison = refus(chemin, racine, racines, uid)
            if not raison and candidat.categorie == FILESTORE:
                if bases is None:
                    raison = "no-database-list"
                elif os.path.basename(chemin) in bases:
                    raison = "database"
            if raison:
                laisses.append((chemin, raison))
                continue
            octets, _ = mesurer(chemin)
            try:
                if os.path.isdir(chemin):
                    shutil.rmtree(chemin)
                else:
                    os.remove(chemin)
            except OSError as exc:
                laisses.append((chemin, str(exc)))
                continue
            liberes += octets
    return liberes, laisses


def candidats(
    racine=".",
    home=None,
    tmp="/tmp",
    data_dir=None,
    bases=None,
    actif=None,
    jours=2,
    uid=None,
):
    """Tous les candidats, les plus gros d'abord."""
    racine = os.path.realpath(racine)
    home = home or os.path.expanduser("~")
    uid = os.getuid() if uid is None else uid
    trouves = (
        caches(racine, home)
        + restes_tmp(tmp, uid, jours)
        + odoo(data_dir, bases, jours)
        + venvs(racine, actif)
    )
    return sorted(
        (c for c in trouves if c.taille > 0 or c.categorie == TMP),
        key=lambda c: -c.taille,
    )
