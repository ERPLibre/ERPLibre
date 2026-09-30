#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'espace qu'on peut récupérer sur un poste de développement, et son
effacement sous garde-fous.

`candidats()` cherche, sans rien toucher, ces sortes de choses :
 - des CACHES qui se reconstruisent seuls : pip, Poetry, npm, go-build,
   yay…, et dans le dépôt les __pycache__, htmlcov/ et .coverage.* ; ceux
   qui se RETÉLÉCHARGENT en gigaoctets (modèles, images de VM) sont
   proposés décochés ;
 - les répertoires INCONNUS de ~/.cache de plus de `SEUIL_INCONNU`,
   décochés, sauf ceux qu'un processus tient ouverts ;
 - la CORBEILLE du bureau, décochée ;
 - des RESTES dans /tmp : ce qu'un lanceur ou un montage interrompu y a
   laissé, à soi, inactif depuis `jours` jours ;
 - des FILESTORES d'Odoo dont la base n'existe plus, et les sessions web
   périmées ;
 - des VENVS d'une autre version d'Odoo que celle du checkout, et ceux des
   AUTRES checkouts ERPLibre voisins, décochés, sauf s'ils sont en usage.

`effacer()` n'efface que ce qu'on lui passe, et REVÉRIFIE chaque chemin
juste avant : entre la liste et la confirmation, un fichier a pu changer de
propriétaire, devenir un lien, ou un filestore retrouver sa base.

Les garde-fous (`refus()`) : un chemin effaçable est à l'utilisateur
courant, n'est pas un lien et n'en traverse aucun, se trouve SOUS une des
racines permises sans en être une, et n'est jamais dans private/ ni dans
tasks/ d'un dépôt. private/ porte les seules données de client du dépôt, et
tasks/ le travail en cours : ni l'un ni l'autre ne se reconstruit.

Ce module ne rend que des faits ; les phrases appartiennent au menu.
"""

import os
import shutil
import stat
import subprocess
import time
from dataclasses import dataclass, field

CACHE = "cache"
TMP = "tmp"
FILESTORE = "filestore"
SESSIONS = "sessions"
VENV = "venv"
VENV_AUTRE = "venv-other"
INCONNU = "unknown"
CORBEILLE = "trash"

# Les caches de l'utilisateur, sous $HOME. pypoetry/cache et non pypoetry :
# à côté vivent virtualenvs/, qui sont des environnements, pas un cache.
CACHES_HOME = (
    ".cache/pip",
    ".cache/pypoetry/cache",
    ".npm/_cacache",
    ".cache/go-build",
    ".cache/yay",
    ".cache/selenium",
    ".cache/yarn",
    ".cache/uv",
    ".cache/mise",
    ".cache/thumbnails",
    ".cargo/registry/cache",
)

# Des caches aussi, mais qui se retéléchargent en gigaoctets — modèles,
# images de VM, navigateurs, dépôts Maven : décochés, avec la mise en garde.
CACHES_TELECHARGES = (
    ".cache/huggingface",
    ".cache/lima",
    ".cache/ms-playwright",
    ".m2/repository",
    ".gradle/caches",
)

# Sous ~/.cache, ce qui n'est pas un cache au sens effaçable : Poetry y range
# ses virtualenvs.
CACHE_JAMAIS = {"pypoetry"}

# Un répertoire inconnu de ~/.cache n'est proposé qu'au-delà de ce poids :
# en deçà, le regarder coûte plus que ce qu'il rend.
SEUIL_INCONNU = 100 * 1024 * 1024

CORBEILLE_REL = ".local/share/Trash"

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


def usages(uid=None, proc="/proc"):
    """Ce que les processus tiennent : (chemins, lignes de commande).

    Les chemins — répertoire courant, fichiers ouverts, bibliothèques
    chargées — ne se lisent que pour les processus de `uid`. Les lignes de
    commande se lisent pour TOUS : une VM lancée par un autre compte ne
    montre pas ses descripteurs, mais nomme son disque dans ses arguments."""
    uid = os.getuid() if uid is None else uid
    chemins = set()
    commandes = []
    try:
        pids = [p for p in os.listdir(proc) if p.isdigit()]
    except OSError:
        return chemins, commandes
    for pid in pids:
        base = os.path.join(proc, pid)
        try:
            with open(os.path.join(base, "cmdline"), "rb") as fh:
                ligne = fh.read().replace(b"\0", b" ").decode(errors="replace")
            if ligne:
                commandes.append(ligne)
            if os.stat(base).st_uid != uid:
                continue
        except OSError:
            continue
        for lien in ("cwd", "exe"):
            try:
                chemins.add(os.readlink(os.path.join(base, lien)))
            except OSError:
                pass
        try:
            for fd in os.listdir(os.path.join(base, "fd")):
                try:
                    chemins.add(os.readlink(os.path.join(base, "fd", fd)))
                except OSError:
                    pass
        except OSError:
            pass
        try:
            with open(os.path.join(base, "maps"), encoding="utf-8") as fh:
                for ligne in fh:
                    morceaux = ligne.split(None, 5)
                    if len(morceaux) == 6 and morceaux[5].startswith("/"):
                        chemins.add(morceaux[5].rstrip("\n"))
        except OSError:
            pass
    return chemins, commandes


def en_usage(chemin, utilises):
    """Vrai si un processus tient quelque chose sous `chemin` ou le nomme
    dans ses arguments. `utilises` est le rendu de `usages()`."""
    chemins, commandes = utilises
    absolu = os.path.realpath(chemin)
    prefixe = absolu.rstrip(os.sep) + os.sep
    if any(c == absolu or c.startswith(prefixe) for c in chemins):
        return True
    return any(absolu in ligne for ligne in commandes)


def caches_telecharges(home):
    """Les caches qui se retéléchargent cher : décochés, mis en garde."""
    maintenant = time.time()
    trouves = []
    for rel in CACHES_TELECHARGES:
        chemin = os.path.join(home, rel)
        if os.path.isdir(chemin) and not os.path.islink(chemin):
            trouves.append(
                _candidat(
                    CACHE, rel, [chemin], maintenant, mise_en_garde="download"
                )
            )
    return trouves


def caches_inconnus(home, utilises, seuil=SEUIL_INCONNU):
    """Les répertoires de ~/.cache qu'aucune liste ne connaît, au-delà de
    `seuil` octets, et que personne ne tient ouverts. Décochés : ce qu'ils
    contiennent n'est pas garanti de se reconstruire."""
    maintenant = time.time()
    cache = os.path.join(home, ".cache")
    connus = CACHE_JAMAIS | {
        rel.split("/")[1]
        for rel in CACHES_HOME + CACHES_TELECHARGES
        if rel.startswith(".cache/")
    }
    trouves = []
    try:
        noms = sorted(os.listdir(cache))
    except OSError:
        return trouves
    for nom in noms:
        chemin = os.path.join(cache, nom)
        if nom in connus or os.path.islink(chemin):
            continue
        if not os.path.isdir(chemin):
            continue
        candidat = _candidat(
            INCONNU,
            f".cache/{nom}",
            [chemin],
            maintenant,
            mise_en_garde="unknown",
        )
        if candidat.taille < seuil or en_usage(chemin, utilises):
            continue
        trouves.append(candidat)
    return trouves


def corbeille(home):
    """Le contenu de la corbeille du bureau, les fichiers et leurs fiches."""
    maintenant = time.time()
    base = os.path.join(home, CORBEILLE_REL)
    chemins = []
    for sous in ("files", "info", "expunged"):
        dossier = os.path.join(base, sous)
        try:
            noms = sorted(os.listdir(dossier))
        except OSError:
            continue
        chemins += [os.path.join(dossier, n) for n in noms]
    if not chemins:
        return []
    return [_candidat(CORBEILLE, "Trash", chemins, maintenant)]


def depots_voisins(racine):
    """Les autres checkouts ERPLibre à côté de `racine` : un répertoire qui
    porte .erplibre-version."""
    parent = os.path.dirname(os.path.realpath(racine))
    trouves = []
    try:
        noms = sorted(os.listdir(parent))
    except OSError:
        return trouves
    for nom in noms:
        chemin = os.path.join(parent, nom)
        if chemin == os.path.realpath(racine) or os.path.islink(chemin):
            continue
        if os.path.isfile(os.path.join(chemin, ".erplibre-version")):
            trouves.append(chemin)
    return trouves


def venvs_voisins(racine, utilises):
    """Les venvs des autres checkouts ERPLibre, décochés ; jamais un venv
    qu'un processus emploie — un Odoo lancé de ce checkout-là."""
    maintenant = time.time()
    trouves = []
    for depot in depots_voisins(racine):
        for nom in sorted(os.listdir(depot)):
            chemin = os.path.join(depot, nom)
            if not nom.startswith(".venv."):
                continue
            if not os.path.isdir(chemin) or os.path.islink(chemin):
                continue
            if en_usage(chemin, utilises):
                continue
            trouves.append(
                _candidat(
                    VENV_AUTRE,
                    f"{os.path.basename(depot)}/{nom}",
                    [chemin],
                    maintenant,
                    mise_en_garde="reinstall-checkout",
                )
            )
    return trouves


def racines_permises(racine, home, tmp, data_dir):
    """Les seuls répertoires sous lesquels on efface."""
    permises = [
        os.path.join(home, rel) for rel in CACHES_HOME + CACHES_TELECHARGES
    ]
    permises += [
        os.path.join(home, ".cache"),
        os.path.join(home, CORBEILLE_REL),
    ]
    permises += depots_voisins(racine)
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
    # private/ et tasks/ se protègent sous TOUTES les racines : celle du
    # dépôt, et celles des checkouts voisins dont on efface les venvs.
    for r in [os.path.realpath(racine)] + list(racines):
        for garde in ("private", "tasks"):
            protege = os.path.join(r, garde)
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
    utilises=None,
):
    """Tous les candidats, les plus gros d'abord. `utilises` est le rendu
    de `usages()` ; lu ici quand il n'est pas fourni."""
    racine = os.path.realpath(racine)
    home = home or os.path.expanduser("~")
    uid = os.getuid() if uid is None else uid
    if utilises is None:
        utilises = usages(uid)
    trouves = (
        caches(racine, home)
        + caches_telecharges(home)
        + caches_inconnus(home, utilises)
        + corbeille(home)
        + restes_tmp(tmp, uid, jours)
        + odoo(data_dir, bases, jours)
        + venvs(racine, actif)
        + venvs_voisins(racine, utilises)
    )
    return sorted(
        (c for c in trouves if c.taille > 0 or c.categorie == TMP),
        key=lambda c: -c.taille,
    )


# ----------------------------------------------------------------------
# Le rapport des dépôts lourds : ce qui pèse à côté du dépôt, sans rien
# proposer d'effacer d'autre que les venvs vus plus haut.

# Un sous-répertoire n'est détaillé qu'au-delà de ce poids.
SEUIL_DETAIL = 50 * 1024 * 1024


def depots_lourds(parent, lanceur=subprocess.run, seuil=SEUIL_DETAIL):
    """Les répertoires de `parent`, les plus lourds d'abord, chacun avec
    ses sous-répertoires de plus de `seuil` octets et la date de son dernier
    commit (None hors git).

    Un seul `du` sur deux niveaux plutôt qu'un parcours Python : une dizaine
    de checkouts se comptent en centaines de milliers de fichiers. -x ne
    franchit pas un point de montage — un sshfs sous un dépôt ne se compte
    pas."""
    try:
        res = lanceur(
            ["du", "-x", "-B1", "-d", "2", parent],
            capture_output=True,
            text=True,
            timeout=600,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    tailles = {}
    for ligne in res.stdout.splitlines():
        octets, _, chemin = ligne.partition("\t")
        if octets.isdigit() and chemin:
            tailles[chemin] = int(octets)
    parent = parent.rstrip(os.sep)
    depots = []
    for chemin, taille in tailles.items():
        if os.path.dirname(chemin) != parent:
            continue
        enfants = sorted(
            (
                (os.path.basename(c), t)
                for c, t in tailles.items()
                if os.path.dirname(c) == chemin and t >= seuil
            ),
            key=lambda e: -e[1],
        )
        depots.append(
            {
                "nom": os.path.basename(chemin),
                "chemin": chemin,
                "taille": taille,
                "enfants": enfants,
                "erplibre": os.path.isfile(
                    os.path.join(chemin, ".erplibre-version")
                ),
                "commit": dernier_commit(chemin, lanceur),
            }
        )
    return sorted(depots, key=lambda d: -d["taille"])


def dernier_commit(depot, lanceur=subprocess.run):
    """L'horodatage du dernier commit de `depot`, ou None."""
    if not os.path.exists(os.path.join(depot, ".git")):
        return None
    try:
        res = lanceur(
            ["git", "-C", depot, "log", "-1", "--format=%ct"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    valeur = res.stdout.strip()
    return int(valeur) if res.returncode == 0 and valeur.isdigit() else None


# ----------------------------------------------------------------------
# Les caches du système, qui ne s'effacent qu'avec sudo : on les mesure
# ici, la commande est lancée par le menu après confirmation.

# Le journal systemd est réduit à ce poids, pas vidé : les derniers jours
# restent lisibles pour un diagnostic.
JOURNAL_GARDE = "200M"
JOURNAL_GARDE_OCTETS = 200 * 1024 * 1024

# (nom, répertoire mesuré, binaire requis, commande). La commande du
# gestionnaire de paquets est la sienne, jamais un rm : elle sait ce qui est
# installé. « pacman -Sc » garde les paquets des versions installées.
CACHES_SYSTEME = (
    (
        "pacman",
        "/var/cache/pacman/pkg",
        "pacman",
        ["sudo", "pacman", "-Sc", "--noconfirm"],
    ),
    (
        "apt",
        "/var/cache/apt/archives",
        "apt-get",
        ["sudo", "apt-get", "clean"],
    ),
    (
        "dnf",
        "/var/cache/dnf",
        "dnf",
        ["sudo", "dnf", "clean", "packages"],
    ),
    (
        "journal",
        "/var/log/journal",
        "journalctl",
        ["sudo", "journalctl", f"--vacuum-size={JOURNAL_GARDE}"],
    ),
)


def caches_systeme(caches=CACHES_SYSTEME, which=shutil.which):
    """Les caches du système présents ici : [{nom, chemin, taille,
    commande}]. Le journal n'est proposé qu'au-delà de ce qu'il garde."""
    trouves = []
    for nom, chemin, binaire, commande in caches:
        if which(binaire) is None or not os.path.isdir(chemin):
            continue
        taille, _ = mesurer(chemin)
        if nom == "journal" and taille <= JOURNAL_GARDE_OCTETS:
            continue
        trouves.append(
            {
                "nom": nom,
                "chemin": chemin,
                "taille": taille,
                "commande": list(commande),
            }
        )
    return trouves
