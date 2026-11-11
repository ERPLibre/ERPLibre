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
racines permises sans en être une, ne porte aucun point de montage — ni sur
lui ni sous lui —, et n'est jamais dans private/ ni dans tasks/ d'un dépôt.
private/ porte les seules données de client du dépôt, et tasks/ le travail
en cours : ni l'un ni l'autre ne se reconstruit. Un montage sous un
candidat ferait effacer le système de fichiers monté — la machine distante
d'un sshfs, la source d'un bind —, rmtree traversant les montages.

Les chemins sous $HOME se proposent par leur chemin RÉEL : un ~/.cache qui
est un lien vers un autre disque se nettoie là où il vit, et refus() n'y
voit plus de lien traversé. Seul le dernier élément, s'il est lui-même un
lien, est écarté — sauf dans la corbeille, où un lien mis à la corbeille
s'efface comme un lien, sans toucher à sa cible.

Ce module ne rend que des faits ; les phrases appartiennent au menu.
"""

import os
import re
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


def _octets(st):
    return st.st_blocks * 512 if hasattr(st, "st_blocks") else st.st_size


def mesurer(chemin):
    """(octets que libérerait l'effacement, date de modification la plus
    récente) sous `chemin`, sans suivre aucun lien ni franchir un point de
    montage. Un fichier illisible compte pour zéro.

    Un fichier à plusieurs liens durs ne compte que si TOUS ses liens sont
    sous `chemin` : uv installe un venv en liens durs vers son cache, et
    effacer le cache seul ne libère rien de ce que le venv partage. Sur un
    btrfs compressé, st_blocks dit la taille avant compression : le chiffre
    y reste un majorant."""
    try:
        st = os.lstat(chemin)
    except OSError:
        return 0, 0.0
    total = _octets(st)
    recent = st.st_mtime
    if not stat.S_ISDIR(st.st_mode):
        if st.st_nlink > 1 and not stat.S_ISLNK(st.st_mode):
            return 0, recent
        return total, recent
    appareil = st.st_dev
    # inode -> [octets, liens vus, liens en tout]
    partages = {}
    for dossier, sous, fichiers in os.walk(chemin, followlinks=False):
        gardes = []
        for nom in sous:
            try:
                st = os.lstat(os.path.join(dossier, nom))
            except OSError:
                continue
            # Un autre système de fichiers monté dessous ne part pas avec
            # le répertoire : refus() l'interdit, il ne se compte pas.
            if st.st_dev != appareil:
                continue
            gardes.append(nom)
            total += _octets(st)
            recent = max(recent, st.st_mtime)
        sous[:] = gardes
        for nom in fichiers:
            try:
                st = os.lstat(os.path.join(dossier, nom))
            except OSError:
                continue
            recent = max(recent, st.st_mtime)
            if st.st_nlink > 1 and not stat.S_ISLNK(st.st_mode):
                cle = (st.st_dev, st.st_ino)
                entree = partages.setdefault(
                    cle, [_octets(st), 0, st.st_nlink]
                )
                entree[1] += 1
                continue
            total += _octets(st)
    total += sum(o for o, vus, tous in partages.values() if vus >= tous)
    return total, recent


def montages(chemin_mountinfo="/proc/self/mountinfo"):
    """Les points de montage du système, échappements octaux décodés.
    mountinfo liste aussi les bind mounts d'un même système de fichiers,
    que os.path.ismount ne voit pas."""
    points = set()
    try:
        with open(chemin_mountinfo, "rb") as fh:
            for ligne in fh:
                champs = ligne.split()
                if len(champs) > 4:
                    # Décodé comme os.listdir décode : un nom qui n'est pas
                    # de l'UTF-8 garde ses octets (surrogateescape), et se
                    # compare au chemin du candidat.
                    point = re.sub(
                        rb"\\([0-7]{3})",
                        lambda m: bytes([int(m.group(1), 8)]),
                        champs[4],
                    )
                    points.add(os.path.normpath(os.fsdecode(point)))
    except OSError:
        pass
    return points


def porte_un_montage(chemin, points):
    """Vrai si un point de montage est `chemin` ou se trouve sous lui."""
    absolu = os.path.normpath(os.path.abspath(chemin))
    prefixe = absolu.rstrip(os.sep) + os.sep
    return any(p == absolu or p.startswith(prefixe) for p in points)


def reel(home, rel):
    """Le chemin réel de `home`/`rel`, ses répertoires parents résolus, ou
    None si le dernier élément est lui-même un lien."""
    chemin = os.path.join(home, rel)
    if os.path.islink(chemin):
        return None
    return os.path.join(
        os.path.realpath(os.path.dirname(chemin)), os.path.basename(chemin)
    )


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
        chemin = reel(home, rel)
        if chemin and os.path.isdir(chemin):
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


def restes_tmp(tmp, uid, jours, utilises=None, points=None):
    """Ce que des outils ont laissé dans `tmp`, à `uid`, inactif depuis
    `jours` jours, et que personne n'emploie.

    Une entrée qui porte un point de montage, sur elle ou dessous, n'est
    jamais mesurée ni proposée : la parcourir lirait — ou figerait, sur un
    sshfs mort — la machine distante. Un répertoire sshfs_ ne compte que
    VIDE ; un fichier sshfs_ (un journal) est un reste comme un autre."""
    maintenant = time.time()
    points = montages() if points is None else points
    utilises = (set(), []) if utilises is None else utilises
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
        # Avant tout stat : celui d'un sshfs mort attendrait le démon.
        if porte_un_montage(chemin, points):
            continue
        try:
            st = os.lstat(chemin)
        except OSError:
            continue
        if st.st_uid != uid or stat.S_ISLNK(st.st_mode):
            continue
        if nom.startswith("sshfs_") and stat.S_ISDIR(st.st_mode):
            try:
                if os.listdir(chemin):
                    continue
            except OSError:
                continue
        if en_usage(chemin, utilises):
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
    data_dir = os.path.realpath(data_dir)
    filestore = os.path.join(data_dir, "filestore")
    try:
        noms_filestore = (
            sorted(os.listdir(filestore)) if bases is not None else []
        )
    except OSError:
        noms_filestore = []
    if noms_filestore:
        for nom in noms_filestore:
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


def venvs(racine, actif, utilises=None):
    """Les venvs d'une autre version d'Odoo que `actif`, que personne
    n'emploie ; jamais .venv.erplibre, qui fait tourner TODO lui-même.
    Sans `actif` connu (.erplibre-version absent), aucun : le venv actif ne
    se distinguerait pas des autres."""
    maintenant = time.time()
    trouves = []
    if not actif:
        return trouves
    utilises = (set(), []) if utilises is None else utilises
    for nom in sorted(os.listdir(racine)):
        chemin = os.path.join(racine, nom)
        if not nom.startswith(".venv.odoo") or nom == actif:
            continue
        if en_usage(chemin, utilises):
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
    chargées, arguments relatifs résolus contre le répertoire courant,
    VIRTUAL_ENV — ne se lisent que pour les processus de `uid`. Les lignes
    de commande se lisent pour TOUS : une VM lancée par un autre compte ne
    montre pas ses descripteurs, mais nomme son disque dans ses arguments.

    L'argument relatif compte : « ./.venv.erplibre/bin/python » ne charge
    parfois rien du venv que /proc/<pid>/maps montrerait, et son exe est
    l'interpréteur de base, hors du venv, le python du venv étant un lien."""
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
                brut = fh.read()
            ligne = brut.replace(b"\0", b" ").decode(errors="replace")
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
        environ = {}
        try:
            with open(os.path.join(base, "environ"), "rb") as fh:
                for var in fh.read().split(b"\0"):
                    cle, egal, valeur = var.partition(b"=")
                    if egal and cle in (b"VIRTUAL_ENV", b"PWD", b"PATH"):
                        environ[cle] = os.fsdecode(valeur)
        except OSError:
            pass
        if environ.get(b"VIRTUAL_ENV"):
            chemins.add(os.path.normpath(environ[b"VIRTUAL_ENV"]))
        # Un venv dont bin/ est dans le PATH sert à ce processus, activé
        # ou non : « python » y trouve le sien.
        for entree in environ.get(b"PATH", "").split(os.pathsep):
            if entree.endswith("/bin") and os.path.isfile(
                os.path.join(os.path.dirname(entree), "pyvenv.cfg")
            ):
                chemins.add(os.path.normpath(os.path.dirname(entree)))
        # Un argument relatif se résout contre le répertoire courant ET
        # contre celui du lancement (PWD) : le processus a pu changer de
        # répertoire depuis.
        bases_relatives = []
        try:
            bases_relatives.append(os.readlink(os.path.join(base, "cwd")))
        except OSError:
            pass
        if environ.get(b"PWD"):
            bases_relatives.append(environ[b"PWD"])
        for arg in os.fsdecode(brut).split("\0"):
            if "/" not in arg or arg.startswith("-"):
                continue
            if os.path.isabs(arg):
                chemins.add(os.path.normpath(arg))
                continue
            for depart in bases_relatives:
                chemins.add(os.path.normpath(os.path.join(depart, arg)))
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
    formes = {
        os.path.realpath(chemin),
        os.path.normpath(os.path.abspath(chemin)),
    }
    for absolu in formes:
        prefixe = absolu.rstrip(os.sep) + os.sep
        if any(c == absolu or c.startswith(prefixe) for c in chemins):
            return True
        if any(absolu in ligne for ligne in commandes):
            return True
    return False


def caches_telecharges(home):
    """Les caches qui se retéléchargent cher : décochés, mis en garde."""
    maintenant = time.time()
    trouves = []
    for rel in CACHES_TELECHARGES:
        chemin = reel(home, rel)
        if chemin and os.path.isdir(chemin):
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
    # La racine de la liste se résout en entier : un ~/.cache lien vers un
    # autre disque se parcourt là où il vit.
    cache = os.path.realpath(os.path.join(home, ".cache"))
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
    base = os.path.realpath(os.path.join(home, CORBEILLE_REL))
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


# Le data_dir d'Odoo quand config.conf n'en donne pas.
DATA_DIR_ODOO = "~/.local/share/Odoo"


def configs_partageant(racine, data_dir, lire_config):
    """Les config.conf qui écrivent dans le même `data_dir` que ce
    checkout : le sien (None, que `lire_config` résout comme run.sh) et
    ceux des checkouts voisins qui y pointent, leur data_dir absent valant
    celui d'Odoo par défaut.

    Les filestores de ce data_dir appartiennent aux bases de TOUS ces
    clusters PostgreSQL : un filestore n'est orphelin que si aucun d'eux ne
    connaît sa base. `lire_config(chemin)` rend le dict [options]."""
    cible = os.path.realpath(os.path.expanduser(data_dir))
    trouves = [None]
    parent = os.path.dirname(os.path.realpath(racine))
    try:
        voisins = sorted(os.listdir(parent))
    except OSError:
        voisins = []
    # Les liens comptent ici, contrairement à depots_voisins() : on ne fait
    # que LIRE leur configuration.
    for nom in voisins:
        depot = os.path.join(parent, nom)
        if os.path.realpath(depot) == os.path.realpath(racine):
            continue
        if not os.path.isfile(os.path.join(depot, ".erplibre-version")):
            continue
        chemin = os.path.join(depot, "config.conf")
        if not os.path.isfile(chemin):
            continue
        valeur = str(lire_config(chemin).get("data_dir", "")).strip()
        if valeur.lower() in ("", "false", "none"):
            valeur = DATA_DIR_ODOO
        if os.path.realpath(os.path.expanduser(valeur)) == cible:
            trouves.append(chemin)
    return trouves


def venvs_voisins(racine, utilises):
    """Les venvs des autres checkouts ERPLibre, décochés ; jamais un venv
    qu'un processus emploie — un Odoo lancé de ce checkout-là."""
    maintenant = time.time()
    trouves = []
    for depot in depots_voisins(racine):
        try:
            noms = sorted(os.listdir(depot))
        except OSError:
            continue
        for nom in noms:
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


def refus(chemin, racine, racines, uid, points=None, lien_permis=False):
    """None si `chemin` peut être effacé, sinon la raison, en un mot.

    `points` : les points de montage, relus par l'appelant juste avant
    l'effacement. `lien_permis` : le DERNIER élément peut être un lien, qui
    s'effacera comme lien (la corbeille) ; un lien plus haut sur le chemin
    reste refusé."""
    absolu = os.path.abspath(chemin)
    # Un lien N'IMPORTE OÙ sur le chemin le ferait mener ailleurs que là
    # où on croit effacer.
    parent = os.path.dirname(absolu)
    if os.path.realpath(parent) != parent:
        return "link"
    if not lien_permis and os.path.realpath(absolu) != absolu:
        return "link"
    try:
        st = os.lstat(absolu)
    except OSError:
        return "missing"
    if st.st_uid != uid:
        return "owner"
    if porte_un_montage(absolu, montages() if points is None else points):
        return "mount"
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


# Les catégories dont un processus peut employer le contenu au moment même
# de l'effacement : elles sont revérifiées contre les processus vivants.
EN_USAGE_POSSIBLE = {TMP, VENV, VENV_AUTRE, INCONNU}


def effacer(candidats, racine, racines, uid, bases=None, utilises=None):
    """Efface les chemins des `candidats`, chacun revérifié juste avant.

    `bases` est la liste des bases relue JUSTE AVANT l'appel : un filestore
    dont la base est apparue depuis la recherche est laissé. Sans elle
    (None), aucun filestore n'est effacé. Les points de montage et les
    processus (`utilises`, lu ici s'il manque) sont relus de même : la
    confirmation a pu attendre des minutes au formulaire.

    Rend (octets libérés, [(chemin, raison)] des chemins laissés)."""
    liberes = 0
    laisses = []
    points = montages()
    if utilises is None and any(
        c.categorie in EN_USAGE_POSSIBLE for c in candidats
    ):
        utilises = usages(uid)
    for candidat in candidats:
        for chemin in candidat.chemins:
            raison = refus(
                chemin,
                racine,
                racines,
                uid,
                points,
                lien_permis=candidat.categorie == CORBEILLE,
            )
            if not raison and candidat.categorie == FILESTORE:
                if bases is None:
                    raison = "no-database-list"
                elif os.path.basename(chemin) in bases:
                    raison = "database"
            if (
                not raison
                and candidat.categorie in EN_USAGE_POSSIBLE
                and en_usage(chemin, utilises)
            ):
                raison = "in-use"
            if raison:
                laisses.append((chemin, raison))
                continue
            octets, _ = mesurer(chemin)
            try:
                if os.path.islink(chemin) or not os.path.isdir(chemin):
                    os.remove(chemin)
                else:
                    shutil.rmtree(chemin)
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
        + restes_tmp(tmp, uid, jours, utilises)
        + odoo(data_dir, bases, jours)
        + venvs(racine, actif, utilises)
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
    parent = os.path.normpath(parent)
    depots = []
    for chemin, taille in tailles.items():
        # dirname("/") vaut "/" : le parent lui-même n'est pas un dépôt.
        if chemin == parent or os.path.dirname(chemin) != parent:
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


# dnf5 (Fedora 41 et après) garde son cache ailleurs que dnf4, et « dnf
# clean » ne vide que celui de la version installée.
CACHE_DNF5 = "/var/cache/libdnf5"


def cache_dnf(binaire_dnf, defaut):
    """Le cache que nettoie le dnf installé : celui de dnf5 quand `dnf`
    est dnf5 (un lien vers lui), `defaut` sinon."""
    if os.path.basename(os.path.realpath(binaire_dnf)).startswith("dnf5"):
        return CACHE_DNF5
    return defaut


def caches_systeme(caches=CACHES_SYSTEME, which=shutil.which, euid=os.geteuid):
    """Les caches du système présents ici : [{nom, chemin, taille,
    commande}]. Le journal n'est proposé qu'au-delà de ce qu'il garde."""
    trouves = []
    for nom, chemin, binaire, commande in caches:
        trouve = which(binaire)
        if trouve is None:
            continue
        commande = list(commande)
        if euid() == 0:
            # Root dans un conteneur : pas de sudo, et pas besoin.
            commande = [c for c in commande if c != "sudo"]
        elif which("sudo") is None:
            continue
        if nom == "dnf":
            chemin = cache_dnf(trouve, chemin)
        if not os.path.isdir(chemin):
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
