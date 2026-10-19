#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Ce qui limite les performances d'un hôte Proxmox VE, ou de tout serveur
Linux : processeur, mémoire, disques, réseau, ZFS et invités, mesurés sur
une durée choisie, puis un verdict par ressource, la réponse à « des
disques SSD sont-ils justifiés ? » et les réglages à envisager.

Lecture seule
-------------
L'outil ne change rien : chaque réglage proposé est AFFICHÉ, avec la
commande qui le ferait et la raison, et n'est jamais exécuté. Il lit
`/proc` et `/sys` à chaque échantillon (quelques petits fichiers), et ne
lance qu'UNE fois chacune des commandes `pveversion`, `zpool`, `zfs` et
`smartctl` (celle-ci seulement en root), avec un délai.

Un seul fichier
---------------
Bibliothèque standard seulement, aucun import local, syntaxe Python 3.7 :
le fichier s'envoie tel quel au python3 d'un hôte, sans rien y copier :

    ssh -T hote python3 -I - --duration 10m < host_perf_audit.py

Les messages sont en anglais ; le menu qui le lance est traduit.

Déroulement
-----------
1. L'outil baisse sa propre priorité (`os.nice(10)`, classe d'E/S idle par
   `ionice` s'il existe) ; rien de cela n'est fatal.
2. Les faits lus une fois : noyau, processeur, mémoire, disques (type,
   modèle, ordonnanceur), pools ZFS et leurs disques, santé SMART, noms
   des invités dans `/etc/pve`.
3. Un échantillon toutes les `--interval` secondes pendant `--duration` :
   deux instantanés successifs donnent des taux. Ctrl-C arrête la mesure
   et le rapport porte sur les échantillons pris.
4. Le rapport (texte, ou `--json` aux clés stables) ; `--csv FICHIER`
   garde aussi les échantillons bruts.

La progression part sur stderr au moins chaque minute, même sans
terminal : par `ssh -T`, elle garde la connexion vivante, et un processus
distant dont le client est parti reçoit EPIPE à l'écriture suivante et
s'arrête.

Codes de sortie : 0 audit mené à terme (y compris interrompu par Ctrl-C,
même sans échantillon) ; 2 impossible (pas un `/proc` Linux, arguments,
CSV non inscriptible) ; 130 Ctrl-C avant le début de la mesure.

L'option cachée `--root DOSSIER` préfixe chaque chemin lu (`/proc`, `/sys`,
`/etc/pve`, `/dev`, `/run`) : elle sert aux tests, qui bâtissent une
arborescence inventée.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import glob
import json
import math
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import time

OUTIL = "host_perf_audit"
SCHEMA = 1

# Durée de mesure admise, en secondes : une seconde suffit à un essai, sept
# jours couvrent un cycle hebdomadaire (sauvegardes du dimanche comprises).
DUREE_MIN_S = 1
DUREE_MAX_S = 7 * 86400
INTERVALLE_DEFAUT_S = 5.0
# Nombre d'échantillons gardés en mémoire au plus : l'intervalle est relevé
# pour que la durée demandée tienne dans cette borne.
ECHANTILLONS_MAX = 2880
# Écart minimal entre deux lignes de progression sur stderr.
PROGRES_MIN_S = 60.0
# Sous cette durée, le rapport rappelle que les pointes quotidiennes
# (sauvegardes, heures chargées) n'ont pas pu être vues.
MESURE_COURTE_S = 1800
DELAI_COMMANDE_S = 20
DELAI_SMART_S = 15
DELAI_IONICE_S = 5
# Attente d'une commande tuée à son délai : au-delà, elle est abandonnée.
ATTENTE_KILL_S = 1
# Ajoutés au PATH hérité pour trouver une commande : Debian et Proxmox
# installent zpool, zfs et smartctl dans /usr/sbin ou /sbin, absents du
# PATH d'un compte non root et de celui que sshd donne par défaut.
CHEMINS_ADMIN = ("/usr/sbin", "/sbin")

# --- Seuils du verdict --------------------------------------------------
# PSI « some » : % du temps où au moins une tâche attendait la ressource.
# PSI « full » : % du temps où TOUTES les tâches attendaient.
CPU_PSI_ATTN = 10.0  # attente d'un processeur, moyenne
CPU_PSI_LIMITE = 25.0
CPU_OCCUPE_ATTN = 90.0  # % d'occupation au 95e centile
# Charge Linux (loadavg) par cœur, au 95e centile. Elle compte aussi les
# tâches bloquées sur une E/S : signal secondaire, qui ne mène à
# « limiting » que si PSI manque.
CHARGE_PAR_COEUR_ATTN = 1.0
CHARGE_PAR_COEUR_LIMITE = 2.0
VOL_LIMITE = 5.0  # « steal » : temps pris par un autre hyperviseur, %
MEM_PSI_ATTN = 2.0
MEM_PSI_LIMITE = 10.0
MEM_DISPO_MIN_PCT = 5.0  # MemAvailable minimal, en % de MemTotal
# Échange actif : pages lues ET écrites dans le swap, moyenne en Kio/s.
SWAP_ACTIF_KIB_S = 256.0
SWAP_UTILISE_CONSEIL_KIB = 512 * 1024
SWAPPINESS_CIBLE = 10
IO_PSI_ATTN = 5.0
IO_PSI_LIMITE = 15.0
IO_FULL_LIMITE = 5.0
# Utilisation d'un disque ROTATIF au 95e centile. Un SSD ou un NVMe sert
# plusieurs requêtes à la fois : 100 % d'utilisation n'y dit pas la
# saturation, il n'est jugé que sur son attente et sur PSI.
UTIL_ATTN = 60.0
UTIL_LIMITE = 85.0
ATTENTE_HDD_LENTE_MS = 25.0  # attente par opération, 95e centile
ATTENTE_SSD_LENTE_MS = 5.0
# Une attente n'est comptée que dans un échantillon qui a eu au moins ce
# nombre d'opérations par seconde : sur une opération isolée elle ne dit
# rien.
OPS_MIN_ATTENTE = 0.5
# Un disque rotatif « porte de la charge » s'il est dans les données d'un
# pool, ou si son utilisation au 95e centile atteint ce seuil.
ACTIVITE_UTIL_P95_MIN = 5.0
# Part de l'utilisation (ou du débit) mesurée que les disques rotatifs
# doivent porter pour que la pression d'E/S de l'hôte leur soit imputée.
PART_ROTATIFS_MAJORITE = 0.5
# ARC de ZFS : part maximale de la RAM quand la mémoire est tendue, cible
# d'une réduction, taux de succès bas, RAM libre jugée large.
ARC_PART_MAX_SI_TENDU = 0.5
ARC_PART_CIBLE_BAISSE = 0.25
ARC_SUCCES_BAS_PCT = 85.0
ARC_DISPO_LARGE = 0.3
ARC_PART_CIBLE_HAUSSE = 0.5
POOL_PLEIN_ATTN = 80  # % utilisé : l'allocation ralentit au-delà
POOL_PLEIN_HAUT = 90
POOL_FRAG_CONSEIL = 50
SYNCQ_LENTE_MS = 20.0  # attente des écritures synchrones d'un pool
# Utilisation d'un lien réseau au 95e centile, en % de sa vitesse.
RESEAU_ATTN_PCT = 70.0
RESEAU_LIMITE_PCT = 90.0
# Au plus ce nombre de conseils de dataset (compression, atime).
CONSEILS_DATASETS_MAX = 6

NIVEAUX = ("ok", "watch", "limiting")
PRIORITES = ("high", "medium", "low")
CHAMPS_CPU = (
    "user",
    "nice",
    "system",
    "idle",
    "iowait",
    "irq",
    "softirq",
    "steal",
)
EXCLUS = ("loop", "ram", "zram", "sr", "fd", "nbd")
VIRTUELS = ("dm-", "md", "zd")
DANS_UNE_VM = ("vd", "xvd")
RE_NVME_CHEMIN = re.compile(r"^nvme\d+c\d+n\d+$")
RE_PARTITION_P = re.compile(r"^(nvme\d+n\d+|mmcblk\d+)p\d+$")
RE_PARTITION = re.compile(r"^([a-z]+)\d+$")
INVITES_RESEAU = ("tap", "veth", "fwbr", "fwpr", "fwln")
GROUPE_INVITES = "guest_interfaces"
RE_PSI = re.compile(
    r"^(some|full) avg10=([\d.]+) avg60=([\d.]+) avg300=([\d.]+)"
    r" total=(\d+)",
    re.M,
)
# Le verdict en lettres seules : smartctl écrit « FAILED! » pour un ATA.
RE_SMART = re.compile(
    r"(?:overall-health self-assessment test result|SMART Health"
    r" Status):\s*(\w+)"
)
RE_SMART_VEILLE = re.compile(r"\bin (?:STANDBY|SLEEP)\b", re.I)
RE_DUREE = re.compile(r"(?:(\d+)h)?(?:(\d+)m(?:in)?)?(?:(\d+)s)?")
RE_VDEV_INTERNE = re.compile(
    r"^(mirror|raidz[123]?|draid[123]?|replacing|spare)(?::[^-\s]+)?-\d+$"
)
SECTIONS_VDEV = {
    "logs": "log",
    "cache": "cache",
    "spares": "spare",
    "special": "special",
    "dedup": "special",
}
COLONNES_CSV = (
    "time",
    "epoch",
    "cpu_busy",
    "iowait",
    "steal",
    "psi_cpu",
    "psi_io_some",
    "psi_io_full",
    "psi_mem",
    "mem_available_mb",
    "swap_in_kib_s",
    "swap_out_kib_s",
    "arc_mb",
    "arc_hit",
)
CLES_JSON = (
    "schema",
    "tool",
    "host",
    "started",
    "duration_s",
    "interval_s",
    "samples",
    "interrupted",
    "cost_cpu_s",
    "notes",
    "facts",
    "cpu",
    "memory",
    "disks",
    "io_psi",
    "network",
    "zfs",
    "guests",
    "guests_skipped",
    "verdicts",
    "ssd",
    "suggestions",
)


# ----------------------------------------------------------------------- #
# Petits outils
# ----------------------------------------------------------------------- #
def chemin(racine, absolu):
    """`absolu` sous `racine` : "" en production, un dossier de test
    sinon."""
    return racine + absolu if racine else absolu


def lire(racine, absolu):
    """Le texte du fichier, ou None s'il est absent ou illisible. PSI
    désactivé au démarrage lève EOPNOTSUPP à la lecture : même None."""
    try:
        with open(
            chemin(racine, absolu), encoding="utf-8", errors="replace"
        ) as f:
            return f.read()
    except (OSError, ValueError):
        return None


def avg(valeurs):
    """Moyenne des valeurs non None, ou None."""
    v = [x for x in valeurs if x is not None]
    return sum(v) / len(v) if v else None


def pct(valeurs, p):
    """Centile `p` au rang le plus proche (rang = ceil(p·n/100), au moins
    1), None ignorés ; None pour une liste vide."""
    v = sorted(x for x in valeurs if x is not None)
    if not v:
        return None
    rang = max(1, int(math.ceil(p * len(v) / 100.0)))
    return v[min(rang, len(v)) - 1]


def maxi(valeurs):
    v = [x for x in valeurs if x is not None]
    return max(v) if v else None


def borner(x, bas=0.0, haut=100.0):
    return max(bas, min(haut, x))


def arrondi(x, chiffres=2):
    return None if x is None else round(x, chiffres)


def fmt(x, motif="{:.1f}", vide="-"):
    return vide if x is None else motif.format(x)


def pire(a, b):
    """Le plus grave de deux niveaux."""
    return a if NIVEAUX.index(a) >= NIVEAUX.index(b) else b


def duree_humaine(secondes):
    s = int(round(secondes))
    if s >= 3600:
        return "%d h %02d min" % (s // 3600, s % 3600 // 60)
    if s >= 60:
        return "%d min %02d s" % (s // 60, s % 60)
    return "%d s" % s


def parse_duration(texte):
    """« 90 », « 90.5 » (tronqué), « 30s », « 10m », « 10min », « 2h »,
    « 1h30m » → secondes (int). ValueError pour toute autre forme."""
    brut = str(texte).strip().lower()
    if re.fullmatch(r"\d+(?:\.\d+)?", brut):
        return int(float(brut))
    m = RE_DUREE.fullmatch(brut)
    if not brut or m is None or not any(m.groups()):
        raise ValueError("unreadable duration: %r" % (texte,))
    heures, minutes, secondes = (int(g or 0) for g in m.groups())
    return heures * 3600 + minutes * 60 + secondes


def duree_valide(texte):
    """Secondes entre DUREE_MIN_S et DUREE_MAX_S, ValueError sinon."""
    secondes = parse_duration(texte)
    if not DUREE_MIN_S <= secondes <= DUREE_MAX_S:
        raise ValueError(
            "duration out of range: %s (1 second to 7 days)" % (texte,)
        )
    return secondes


def choisir_intervalle(duree, demande):
    """(intervalle, note ou None). 5 s par défaut, relevé pour garder au
    plus ECHANTILLONS_MAX échantillons, puis borné entre 1 s et la durée.
    La borne vaut aussi pour un intervalle demandé : elle protège la
    mémoire d'une mesure de plusieurs jours."""
    intervalle = INTERVALLE_DEFAUT_S if demande is None else float(demande)
    note = None
    plancher = float(math.ceil(duree / float(ECHANTILLONS_MAX)))
    if intervalle < plancher:
        note = (
            "interval raised from %g s to %g s so the audit keeps at most"
            " %d samples" % (intervalle, plancher, ECHANTILLONS_MAX)
        )
        intervalle = plancher
    return max(1.0, min(intervalle, float(duree))), note


# ----------------------------------------------------------------------- #
# Lecteurs purs : un texte de /proc ou /sys → des nombres
# ----------------------------------------------------------------------- #
def analyser_stat(texte):
    """Les 8 premiers compteurs de la ligne « cpu » de /proc/stat (une
    ligne courte est complétée par des zéros ; guest et guest_nice sont
    déjà comptés dans user) et « n », le nombre de lignes cpuN. None si
    la première ligne n'est pas « cpu »."""
    if not texte:
        return None
    premiere = texte.split("\n", 1)[0].split()
    if not premiere or premiere[0] != "cpu":
        return None
    try:
        valeurs = [int(x) for x in premiere[1:9]]
    except ValueError:
        return None
    valeurs += [0] * (8 - len(valeurs))
    res = dict(zip(CHAMPS_CPU, valeurs))
    res["n"] = len(re.findall(r"^cpu\d+\s", texte, re.M)) or 1
    return res


def analyser_pression(texte):
    """{"some"|"full": {avg10, avg60, avg300, total (µs)}} d'un fichier de
    /proc/pressure, ou None. Le fichier cpu des noyaux anciens n'a que
    « some »."""
    res = {}
    for m in RE_PSI.finditer(texte or ""):
        res[m.group(1)] = {
            "avg10": float(m.group(2)),
            "avg60": float(m.group(3)),
            "avg300": float(m.group(4)),
            "total": int(m.group(5)),
        }
    return res or None


def analyser_diskstats(texte):
    """{périphérique: compteurs} de /proc/diskstats. Seuls les 14 premiers
    champs sont lus : les noyaux récents en ajoutent (discard, flush)."""
    res = {}
    for ligne in (texte or "").splitlines():
        c = ligne.split()
        if len(c) < 14:
            continue
        try:
            v = [int(x) for x in c[3:14]]
        except ValueError:
            continue
        res[c[2]] = {
            "reads": v[0],
            "rd_sectors": v[2],
            "rd_ms": v[3],
            "writes": v[4],
            "wr_sectors": v[6],
            "wr_ms": v[7],
            "io_ms": v[9],
            "weighted_ms": v[10],
        }
    return res


def analyser_meminfo(texte):
    """{clé: valeur en kB} de /proc/meminfo ; les lignes illisibles sont
    sautées."""
    res = {}
    for ligne in (texte or "").splitlines():
        cle, _, reste = ligne.partition(":")
        try:
            res[cle.strip()] = int(reste.split()[0])
        except (ValueError, IndexError):
            continue
    return res


def analyser_vmstat(texte):
    """pswpin et pswpout (pages lues et écrites dans le swap depuis le
    démarrage) de /proc/vmstat."""
    res = {}
    for ligne in (texte or "").splitlines():
        c = ligne.split()
        if len(c) == 2 and c[0] in ("pswpin", "pswpout") and c[1].isdigit():
            res[c[0]] = int(c[1])
    return res


def analyser_net_dev(texte):
    """{interface: (octets reçus, émis, erreurs, pertes)} de /proc/net/dev,
    deux lignes d'en-tête sautées, lo exclue."""
    res = {}
    for ligne in (texte or "").splitlines()[2:]:
        nom, _, reste = ligne.partition(":")
        nom = nom.strip()
        c = reste.split()
        if len(c) < 16 or nom == "lo":
            continue
        try:
            res[nom] = (
                int(c[0]),
                int(c[8]),
                int(c[2]) + int(c[10]),
                int(c[3]) + int(c[11]),
            )
        except ValueError:
            continue
    return res


def analyser_arcstats(texte):
    """Compteurs de l'ARC (/proc/spl/kstat/zfs/arcstats) : lignes « nom
    type valeur » à valeur entière, en-têtes sautés. None sans ZFS."""
    res = {}
    for ligne in (texte or "").splitlines():
        c = ligne.split()
        if len(c) == 3 and c[2].isdigit():
            res[c[0]] = int(c[2])
    return res or None


def analyser_loadavg(texte):
    try:
        return float(texte.split()[0]) if texte else None
    except (ValueError, IndexError):
        return None


def analyser_cgroup(textes):
    """Compteurs d'un cgroup v2 d'invité à partir de ses fichiers
    {nom: texte} : cpu_usec, mem, mem_max (None pour « max »), octets lus
    et écrits sommés sur tous les périphériques, et « some total » des
    pressions io, cpu et memory."""
    res = {}
    m = re.search(r"usage_usec (\d+)", textes.get("cpu.stat") or "")
    res["cpu_usec"] = int(m.group(1)) if m else None
    courant = (textes.get("memory.current") or "").strip()
    res["mem"] = int(courant) if courant.isdigit() else None
    plafond = (textes.get("memory.max") or "").strip()
    res["mem_max"] = int(plafond) if plafond.isdigit() else None
    lus = ecrits = 0
    for cle, valeur in re.findall(
        r"(rbytes|wbytes)=(\d+)", textes.get("io.stat") or ""
    ):
        if cle == "rbytes":
            lus += int(valeur)
        else:
            ecrits += int(valeur)
    res["io_rbytes"], res["io_wbytes"] = lus, ecrits
    for genre in ("io", "cpu", "memory"):
        m = re.search(
            r"^some .*total=(\d+)", textes.get(genre + ".pressure") or "", re.M
        )
        res[genre + "_some_us"] = int(m.group(1)) if m else None
    return res


# ----------------------------------------------------------------------- #
# Disques : classement, parenté, chemins des vdev ZFS
# ----------------------------------------------------------------------- #
class Blocs:
    """Classement des périphériques de /sys/block, gardé en cache.

    `info(nom)` rend None pour ce qui n'est pas un disque entier (loop,
    RAM, CD-ROM, réseau, chemin multiple NVMe, partition), sinon
    {kind, physical, rotational} :
    - dm-, md et zd : « virtual », non physiques ;
    - vd* et xvd* (disques vus DEPUIS une VM) : « virtual » quel que soit
      rotational, que virtio annonce à 1 ;
    - sinon physique s'il a une entrée `device` ; NVMe par son nom, HDD
      ou SSD par queue/rotational, « ? » s'il manque.
    """

    def __init__(self, racine):
        self.racine = racine
        self.cache = {}

    def info(self, nom):
        if nom not in self.cache:
            self.cache[nom] = self._classer(nom)
        return self.cache[nom]

    def _classer(self, nom):
        if nom.startswith(EXCLUS) or RE_NVME_CHEMIN.match(nom):
            return None
        base = chemin(self.racine, "/sys/block/" + nom)
        if not os.path.isdir(base):
            return None
        if nom.startswith(VIRTUELS):
            return {"kind": "virtual", "physical": False, "rotational": None}
        physique = os.path.isdir(os.path.join(base, "device"))
        texte = lire(self.racine, "/sys/block/%s/queue/rotational" % nom)
        rotatif = None if texte is None else texte.strip() == "1"
        if nom.startswith(DANS_UNE_VM) or not physique:
            genre = "virtual"
        elif nom.startswith("nvme"):
            genre = "NVMe"
        elif rotatif is None:
            genre = "?"
        else:
            genre = "HDD" if rotatif else "SSD"
        return {"kind": genre, "physical": physique, "rotational": rotatif}

    def parent(self, nom):
        """Le disque entier qui porte la partition `nom`, ou None : par
        /sys/block/*/<nom>/partition, sinon par la forme du nom (nvme0n1p3
        → nvme0n1, sda3 → sda) si ce disque existe."""
        motif = chemin(self.racine, "/sys/block/*/%s/partition" % nom)
        for trouve in glob.glob(motif):
            return os.path.basename(os.path.dirname(os.path.dirname(trouve)))
        m = RE_PARTITION_P.match(nom) or RE_PARTITION.match(nom)
        if m and os.path.isdir(
            chemin(self.racine, "/sys/block/" + m.group(1))
        ):
            return m.group(1)
        return None

    def physiques(self, nom, profondeur=0):
        """Les disques physiques sous `nom` (liste triée) : une partition
        mène à son disque, dm- et md à leurs `slaves`, suivis jusqu'au
        bout."""
        if not nom or profondeur > 8:
            return []
        info = self.info(nom)
        if info is None:
            return self.physiques(self.parent(nom), profondeur + 1)
        if nom.startswith(("dm-", "md")):
            res = set()
            motif = chemin(self.racine, "/sys/block/%s/slaves/*" % nom)
            for esclave in glob.glob(motif):
                res.update(
                    self.physiques(os.path.basename(esclave), profondeur + 1)
                )
            return sorted(res)
        return [nom] if info["physical"] else []

    def vdev(self, chemin_vdev):
        """Les disques physiques d'un vdev de « zpool status -P -L » : un
        chemin /dev (un lien by-id restant est résolu sous la racine) ou
        un nom nu. [] pour un vdev fichier ou un chemin inconnu."""
        if "/" not in chemin_vdev:
            return self.physiques(chemin_vdev)
        if not chemin_vdev.startswith("/dev/"):
            return []
        complet = chemin(self.racine, chemin_vdev)
        if os.path.lexists(complet):
            nom = os.path.basename(os.path.realpath(complet))
        else:
            nom = os.path.basename(chemin_vdev)
        return self.physiques(nom)


# ----------------------------------------------------------------------- #
# Le monde extérieur, remplacé par les tests
# ----------------------------------------------------------------------- #
def trouver_binaire(nom, path=None):
    """Chemin absolu de la commande `nom`, ou None. Cherche dans `path`
    (le PATH hérité par défaut) puis dans CHEMINS_ADMIN : la commande
    trouvée là est lancée par ce chemin absolu, sans dépendre du PATH."""
    if path is None:
        path = os.environ.get("PATH", "")
    dossiers = [d for d in path.split(os.pathsep) if d]
    for admin in CHEMINS_ADMIN:
        if admin not in dossiers:
            dossiers.append(admin)
    return shutil.which(nom, path=os.pathsep.join(dossiers))


def baisser_priorite(nice=None, which=None, run=None, pid=None):
    """nice 10, puis classe d'E/S idle par le binaire `ionice` s'il existe.
    Chaque étape ignore ses erreurs et `ionice` a un délai : la mesure ne
    doit jamais échouer pour avoir voulu se faire discrète."""
    nice = nice or os.nice
    which = which or trouver_binaire
    run = run or subprocess.run
    try:
        nice(10)
    except OSError:
        pass
    ionice = which("ionice")
    if not ionice:
        return
    try:
        run(
            [ionice, "-c3", "-p", str(pid or os.getpid())],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=DELAI_IONICE_S,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def abandonner(proc):
    """KILL, puis une attente bornée à ATTENTE_KILL_S : un enfant en
    sommeil non interruptible survit au KILL et serait attendu sans fin.
    Le tube est fermé de notre côté dans tous les cas."""
    try:
        proc.kill()
    except OSError:
        pass
    try:
        proc.wait(timeout=ATTENTE_KILL_S)
    except (subprocess.TimeoutExpired, OSError):
        pass
    for tube in (proc.stdout, proc.stderr):
        if tube is not None:
            try:
                tube.close()
            except OSError:
                pass


class Systeme:
    """Commandes, horloges, identité et priorité du processus. Les tests
    en donnent un faux : aucune commande réelle, aucun sommeil, aucune
    baisse de priorité du lanceur de tests.

    `sans_reponse` liste les commandes abandonnées à leur délai, pour une
    note du rapport. `popen` remplace subprocess.Popen dans les tests."""

    def __init__(self, bavard=False, erreur=None, popen=None):
        self.bavard = bavard
        self.erreur = erreur or sys.stderr
        self.popen = popen or subprocess.Popen
        self.sans_reponse = []

    def which(self, nom):
        return trouver_binaire(nom)

    def lancer(self, argv, delai=DELAI_COMMANDE_S):
        """(code, sortie et erreurs mêlées) ; (None, "") si le binaire
        manque, échoue à démarrer ou dépasse son délai.

        Le délai tient même pour un enfant en sommeil non interruptible
        (`zpool status` d'un pool suspendu, `smartctl` d'un disque qui
        lâche) : SIGKILL ne l'atteint pas et il garde le tube ouvert, là
        où `subprocess.run` attendrait sa fin sans limite après l'avoir
        tué. Ici, après le KILL, l'attente est bornée à ATTENTE_KILL_S,
        puis l'enfant est laissé derrière.

        argv[0] est résolu par trouver_binaire et lancé par son chemin
        absolu ; `sans_reponse` garde l'argv tel que donné."""
        binaire = self.which(argv[0])
        if not binaire:
            return None, ""
        absolu = [binaire] + list(argv[1:])
        if self.bavard:
            print(
                "+ " + " ".join(shlex.quote(a) for a in absolu),
                file=self.erreur,
            )
        try:
            proc = self.popen(
                absolu,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                universal_newlines=True,
                errors="replace",
            )
        except (OSError, ValueError, subprocess.SubprocessError):
            return None, ""
        try:
            sortie, _rien = proc.communicate(timeout=delai)
        except subprocess.TimeoutExpired:
            abandonner(proc)
            self.sans_reponse.append((list(argv), delai))
            return None, ""
        except (OSError, ValueError, subprocess.SubprocessError):
            abandonner(proc)
            return None, ""
        return proc.returncode, sortie or ""

    def euid(self):
        return os.geteuid()

    def horloge(self):
        return time.monotonic()

    def maintenant(self):
        return time.time()

    def dormir(self, secondes):
        time.sleep(secondes)

    def temps_cpu(self):
        """Processeur consommé par l'outil et ses enfants, en secondes."""
        t = os.times()
        return t.user + t.system + t.children_user + t.children_system

    def nom_hote(self):
        return socket.gethostname()

    def noyau(self):
        return os.uname().release

    def page_kib(self):
        try:
            return os.sysconf("SC_PAGE_SIZE") / 1024.0
        except (ValueError, OSError, AttributeError):
            return 4.0

    def baisser_priorite(self):
        baisser_priorite()


# ----------------------------------------------------------------------- #
# Faits lus une fois
# ----------------------------------------------------------------------- #
def faits_hote(racine, systeme, blocs):
    """Noyau, Proxmox, processeur, mémoire, réglages, et les disques
    entiers (sans les zd, trop nombreux et décrits par leur pool)."""
    stat = analyser_stat(lire(racine, "/proc/stat")) or {}
    mem = analyser_meminfo(lire(racine, "/proc/meminfo"))
    code, sortie = systeme.lancer(["pveversion"])
    pve = ""
    if code == 0 and sortie.strip():
        pve = sortie.strip().splitlines()[0]
    m = re.search(
        r"^model name\s*:\s*(.+)$", lire(racine, "/proc/cpuinfo") or "", re.M
    )
    thp = re.search(
        r"\[(\w+)\]",
        lire(racine, "/sys/kernel/mm/transparent_hugepage/enabled") or "",
    )
    ksm_run = (lire(racine, "/sys/kernel/mm/ksm/run") or "").strip()
    partage = (lire(racine, "/sys/kernel/mm/ksm/pages_sharing") or "").strip()
    disques = {}
    for trouve in sorted(glob.glob(chemin(racine, "/sys/block/*"))):
        nom = os.path.basename(trouve)
        info = blocs.info(nom)
        if info is None or nom.startswith("zd"):
            continue
        base = "/sys/block/" + nom
        ordo = re.search(
            r"\[(\S+)\]", lire(racine, base + "/queue/scheduler") or ""
        )
        taille = (lire(racine, base + "/size") or "").strip()
        modele = lire(racine, base + "/device/model") or ""
        disques[nom] = {
            "kind": info["kind"],
            "rotational": info["rotational"],
            "model": " ".join(modele.split()),
            "scheduler": ordo.group(1) if ordo else "",
            "size_bytes": int(taille) * 512 if taille.isdigit() else None,
            "smart": "",
            "physical": info["physical"],
        }
    arc_max = (
        lire(racine, "/sys/module/zfs/parameters/zfs_arc_max") or ""
    ).strip()
    return {
        "kernel": systeme.noyau(),
        "pve": pve,
        "cpu_model": " ".join(m.group(1).split()) if m else "",
        "cores": stat.get("n") or os.cpu_count() or 1,
        "mem_total_kib": mem.get("MemTotal"),
        "swappiness": (lire(racine, "/proc/sys/vm/swappiness") or "").strip(),
        "governor": (
            lire(
                racine, "/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"
            )
            or ""
        ).strip(),
        "thp": thp.group(1) if thp else "",
        "ksm": {
            "run": ksm_run == "1" if ksm_run else None,
            "shared_mib": (
                int(partage) * 4 // 1024 if partage.isdigit() else None
            ),
        },
        "arc_max_param": int(arc_max) if arc_max.isdigit() else None,
        "zfs_loaded": zfs_charge(racine),
        "in_container": os.path.exists(
            chemin(racine, "/run/systemd/container")
        ),
        "cgroup_v2": os.path.exists(
            chemin(racine, "/sys/fs/cgroup/cgroup.controllers")
        ),
        "root": systeme.euid() == 0,
        "disks": disques,
    }


def sante_smart(systeme, disques):
    """`smartctl -n standby -H` de chaque disque physique, seulement en
    root et si smartctl existe : sans root, chaque appel échoue après une
    attente. `-n standby` laisse dormir un disque en veille : sans lui,
    la question réveille un HDD arrêté. Écrit PASSED, FAILED, OK,
    STANDBY (disque en veille, non interrogé) ou "" dans
    disques[nom]["smart"]."""
    if systeme.euid() != 0 or not systeme.which("smartctl"):
        return
    for nom, info in sorted(disques.items()):
        if not info["physical"] or info["kind"] == "virtual":
            continue
        code, sortie = systeme.lancer(
            ["smartctl", "-n", "standby", "-H", "/dev/" + nom], DELAI_SMART_S
        )
        m = RE_SMART.search(sortie)
        if m:
            info["smart"] = m.group(1).upper()
        elif code is not None and code & 2 and RE_SMART_VEILLE.search(sortie):
            # Bit 1 du code : ouverture impossible OU disque en veille ;
            # seul le message de smartctl distingue le mode veille.
            info["smart"] = "STANDBY"
        else:
            info["smart"] = ""


def analyser_zpool_list(texte):
    """Pools de « zpool list -H -p -o name,size,alloc,free,frag,cap,health ».
    frag vaut None pour « - »."""
    pools = {}
    for ligne in (texte or "").splitlines():
        c = ligne.split("\t")
        if len(c) < 7:
            continue
        frag = c[4].rstrip("%")
        cap = c[5].rstrip("%")
        pools[c[0]] = {
            "size_bytes": int(c[1]) if c[1].isdigit() else None,
            "cap_pct": int(cap) if cap.isdigit() else None,
            "frag_pct": int(frag) if frag.isdigit() else None,
            "health": c[6].strip(),
        }
    return pools


def analyser_zpool_status(texte):
    """Par pool : la ligne de scrub ou de resilver en cours, les types de
    vdev de données, et les feuilles (chemins ou noms) de chaque section :
    data (vdev de données, miroir, raidz, draid ou disque seul), log,
    cache, special (dedup compris) et spare.

    La configuration commence après la ligne « NAME STATE ». La première
    ligne est le pool, jamais une section : un pool peut s'appeler
    « cache » ou « logs ». Une ligne suivante à SA hauteur ouvre une
    section (logs, cache…) ; plus bas, un nom comme mirror-0 est un vdev
    intérieur, tout le reste une feuille."""
    pools = {}
    courant = None
    nom_pool = ""
    dans_config = False
    marge_pool = None
    section = "data"
    for ligne in (texte or "").splitlines():
        m = re.match(r"^\s*pool:\s*(\S+)", ligne)
        if m:
            nom_pool = m.group(1)
            courant = {
                "scrub": "",
                "vdev_types": [],
                "feuilles": {
                    "data": [],
                    "log": [],
                    "cache": [],
                    "special": [],
                    "spare": [],
                },
                "sections": [],
            }
            pools[nom_pool] = courant
            dans_config, marge_pool, section = False, None, "data"
            continue
        if courant is None:
            continue
        if re.search(r"(scrub|resilver) in progress", ligne):
            courant["scrub"] = ligne.strip()
            continue
        if re.match(r"^\s*errors:", ligne):
            dans_config = False
            continue
        if re.match(r"^\s*NAME\s+STATE", ligne):
            dans_config = True
            continue
        if not dans_config or not ligne.strip():
            continue
        etendue = ligne.expandtabs(8)
        marge = len(etendue) - len(etendue.lstrip())
        jeton = etendue.split()[0]
        if marge_pool is None:
            marge_pool, section = marge, "data"
            continue
        if marge <= marge_pool:
            if jeton in SECTIONS_VDEV:
                section = SECTIONS_VDEV[jeton]
                courant["sections"].append(section)
            else:
                section = "data"
            continue
        m = RE_VDEV_INTERNE.match(jeton)
        if m:
            genre = m.group(1)
            if genre in ("raidz", "draid"):
                genre += "1"
            if section == "data" and genre not in ("replacing", "spare"):
                courant["vdev_types"].append(genre)
            continue
        courant["feuilles"][section].append(jeton)
    return pools


def analyser_iostat(texte):
    """Attentes moyennes depuis l'import, en ms, de « zpool iostat -l -H -p »
    (ns) : colonnes 7 à 14, au moins 15 colonnes (0.8 ajoute trim)."""
    res = {}

    def ms(x):
        return int(x) / 1e6 if x.isdigit() else None

    for ligne in (texte or "").splitlines():
        c = ligne.split("\t")
        if len(c) < 15:
            continue
        res[c[0]] = {
            "total_r": ms(c[7]),
            "total_w": ms(c[8]),
            "disk_r": ms(c[9]),
            "disk_w": ms(c[10]),
            "syncq_w": ms(c[12]),
            "asyncq_w": ms(c[14]),
        }
    return res


def analyser_zfs_get(texte):
    """{dataset: {propriété: (valeur, source)}} de « zfs get -H -p -o
    name,property,value,source »."""
    res = {}
    for ligne in (texte or "").splitlines():
        c = ligne.split("\t")
        if len(c) == 4:
            res.setdefault(c[0], {})[c[1]] = (c[2], c[3])
    return res


def zfs_charge(racine):
    """Vrai si le module noyau ZFS est chargé : /sys/module/zfs ou les
    compteurs de l'ARC existent, que zpool soit utilisable ou non."""
    return os.path.isdir(chemin(racine, "/sys/module/zfs")) or os.path.exists(
        chemin(racine, "/proc/spl/kstat/zfs/arcstats")
    )


def faits_zfs(racine, systeme, blocs, notes):
    """Pools (taille, remplissage, fragmentation, santé, ashift, attentes)
    et leurs disques, dérivés des chemins de vdev de « zpool status -P
    -L » : un disque de l'hôte n'est un disque du pool que s'il y figure.
    Chaque commande tourne une fois. None sans zpool, avec une note si
    le module ZFS est chargé ; une note aussi si zpool existe mais refuse
    (droits)."""
    if not systeme.which("zpool"):
        if zfs_charge(racine):
            notes.append(
                "ZFS is loaded but zpool was not found (PATH, %s): pools"
                " and their disks are not reported, the ARC from /proc"
                " still is" % ", ".join(CHEMINS_ADMIN)
            )
        return None
    code, sortie = systeme.lancer(
        [
            "zpool",
            "list",
            "-H",
            "-p",
            "-o",
            "name,size,alloc,free,frag,cap,health",
        ]
    )
    if code != 0:
        notes.append(
            "zpool not usable (root?): pools are not reported, the ARC"
            " from /proc still is"
        )
        return None
    pools = analyser_zpool_list(sortie)
    _code, status = systeme.lancer(["zpool", "status", "-P", "-L"])
    _code, resume = systeme.lancer(["zpool", "status", "-x"])
    _code, ashifts = systeme.lancer(
        ["zpool", "get", "-H", "-p", "-o", "name,value", "ashift"]
    )
    _code, iostat = systeme.lancer(["zpool", "iostat", "-l", "-H", "-p"])
    zget = ""
    if systeme.which("zfs"):
        _code, zget = systeme.lancer(
            [
                "zfs",
                "get",
                "-H",
                "-p",
                "-o",
                "name,property,value,source",
                "-t",
                "filesystem,volume",
                "type,compression,atime,relatime,sync",
            ]
        )
    etats = analyser_zpool_status(status)
    attentes = analyser_iostat(iostat)
    valeurs_ashift = {}
    for ligne in (ashifts or "").splitlines():
        c = ligne.split("\t")
        if len(c) == 2:
            valeurs_ashift[c[0]] = "auto" if c[1] == "0" else c[1]
    for nom, pool in pools.items():
        etat = etats.get(nom) or {
            "scrub": "",
            "vdev_types": [],
            "feuilles": {},
            "sections": [],
        }
        disques = {
            "data": set(),
            "log": set(),
            "cache": set(),
            "special": set(),
            "spare": set(),
        }
        non_resolus = []
        for section, feuilles in etat["feuilles"].items():
            for feuille in feuilles:
                trouves = blocs.vdev(feuille)
                if trouves:
                    disques[section].update(trouves)
                else:
                    non_resolus.append(feuille)
        medias = set()
        for disque in disques["data"]:
            info = blocs.info(disque) or {}
            medias.add(info.get("kind", "?"))
        pool.update(
            {
                "ashift": valeurs_ashift.get(nom, ""),
                "scrub": etat["scrub"],
                "vdev_types": sorted(set(etat["vdev_types"])),
                "data_disks": sorted(disques["data"]),
                "log_disks": sorted(disques["log"]),
                "cache_disks": sorted(disques["cache"]),
                "special_disks": sorted(disques["special"]),
                "spare_disks": sorted(disques["spare"]),
                "has_log": "log" in etat["sections"],
                "has_special": "special" in etat["sections"],
                "unresolved_vdevs": non_resolus,
                "media": sorted(medias),
                "latency_ms": attentes.get(nom, {}),
            }
        )
    lignes = [x for x in (resume or "").splitlines() if x.strip()]
    return {
        "pools": pools,
        "summary": lignes[0].strip() if lignes else "",
        "datasets": analyser_zfs_get(zget),
    }


def noms_invites(racine):
    """{vmid: (genre « lxc » | « vm », nom, texte principal)} de /etc/pve.
    Seule la partie avant la première section « [instantané] » est lue :
    un instantané garde l'ancien nom."""
    res = {}
    for genre, dossier, cle in (
        ("lxc", "lxc", "hostname"),
        ("vm", "qemu-server", "name"),
    ):
        motif = chemin(racine, "/etc/pve/%s/*.conf" % dossier)
        for trouve in sorted(glob.glob(motif)):
            vmid = os.path.basename(trouve)[: -len(".conf")]
            try:
                with open(trouve, encoding="utf-8", errors="replace") as f:
                    texte = f.read()
            except OSError:
                continue
            principal = texte.split("\n[", 1)[0]
            m = re.search(r"^%s:\s*(\S+)" % cle, principal, re.M)
            res[vmid] = (genre, m.group(1) if m else "", principal)
    return res


def cgroups_invites(racine):
    """{vmid: (genre, dossier)} des invités EN MARCHE (cgroup v2) :
    /sys/fs/cgroup/lxc/<id> et /sys/fs/cgroup/qemu.slice/<id>.scope. Relu
    à chaque échantillon : un invité démarré pendant la mesure y entre,
    un invité arrêté en sort."""
    res = {}
    base = chemin(racine, "/sys/fs/cgroup")
    for trouve in glob.glob(os.path.join(base, "lxc", "*")):
        nom = os.path.basename(trouve)
        if nom.isdigit():
            res[nom] = ("lxc", trouve)
    for trouve in glob.glob(os.path.join(base, "qemu.slice", "*.scope")):
        vmid = os.path.basename(trouve)[: -len(".scope")]
        if vmid.isdigit():
            res[vmid] = ("vm", trouve)
    return res


def compteurs_cgroup(dossier):
    textes = {}
    for nom in (
        "cpu.stat",
        "memory.current",
        "memory.max",
        "io.stat",
        "io.pressure",
        "cpu.pressure",
        "memory.pressure",
    ):
        textes[nom] = lire("", os.path.join(dossier, nom))
    return analyser_cgroup(textes)


# ----------------------------------------------------------------------- #
# Instantanés et taux
# ----------------------------------------------------------------------- #
def instantane(racine, systeme, blocs, avec_invites):
    """Tous les compteurs à cet instant. Les disques gardés sont ceux que
    `blocs` classe (disques entiers, physiques ou virtuels)."""
    pressions = {}
    for genre in ("cpu", "io", "memory"):
        valeur = analyser_pression(lire(racine, "/proc/pressure/" + genre))
        if valeur:
            pressions[genre] = valeur
    disques = {
        nom: c
        for nom, c in analyser_diskstats(
            lire(racine, "/proc/diskstats")
        ).items()
        if blocs.info(nom) is not None
    }
    vm = analyser_vmstat(lire(racine, "/proc/vmstat"))
    invites = {}
    if avec_invites:
        for vmid, (genre, dossier) in cgroups_invites(racine).items():
            compteurs = compteurs_cgroup(dossier)
            compteurs["kind"] = genre
            invites[vmid] = compteurs
    return {
        "t": systeme.horloge(),
        "wall": systeme.maintenant(),
        "cpu": analyser_stat(lire(racine, "/proc/stat")),
        "psi": pressions,
        "disks": disques,
        "mem": analyser_meminfo(lire(racine, "/proc/meminfo")),
        "swap": vm,
        "net": analyser_net_dev(lire(racine, "/proc/net/dev")),
        "arc": analyser_arcstats(lire(racine, "/proc/spl/kstat/zfs/arcstats")),
        "load": analyser_loadavg(lire(racine, "/proc/loadavg")),
        "guests": invites,
    }


def _taux_cpu(ca, cb):
    """% de chaque état du processeur ; None si aucun tick n'a passé (pas
    de faux 100 %) ou si un compteur recule."""
    if not ca or not cb:
        return None
    deltas = {f: cb[f] - ca[f] for f in CHAMPS_CPU}
    total = sum(deltas.values())
    if total <= 0 or min(deltas.values()) < 0:
        return None
    d = {f: 100.0 * deltas[f] / total for f in CHAMPS_CPU}
    return {
        "busy": 100.0 - d["idle"] - d["iowait"],
        "user": d["user"] + d["nice"],
        "system": d["system"] + d["irq"] + d["softirq"],
        "iowait": d["iowait"],
        "steal": d["steal"],
    }


def _taux_psi(pa, pb, dt):
    """{genre: {"some", "full"}} en % du temps : Δtotal (µs) / dt, borné
    entre 0 et 100."""
    res = {}
    for genre, vb in pb.items():
        va = pa.get(genre) or {}
        r = {}
        for cle in ("some", "full"):
            if cle in va and cle in vb:
                delta = vb[cle]["total"] - va[cle]["total"]
                if delta >= 0:
                    r[cle] = borner(delta / 1e6 / dt * 100.0)
        if r:
            res[genre] = r
    return res


def _taux_disques(da, db, dt):
    """Utilisation = Δio_ms / (dt·10) ; Kio/s = Δsecteurs / 2 / dt ;
    attente = Δms / Δopérations quand il y en a eu."""
    res = {}
    for dev, vb in db.items():
        va = da.get(dev)
        if not va:
            continue
        d = {cle: vb[cle] - va[cle] for cle in vb}
        if min(d.values()) < 0:
            continue
        res[dev] = {
            "util": borner(d["io_ms"] / (dt * 10.0)),
            "r_s": d["reads"] / dt,
            "w_s": d["writes"] / dt,
            "rkb_s": d["rd_sectors"] / 2.0 / dt,
            "wkb_s": d["wr_sectors"] / 2.0 / dt,
            "r_await": d["rd_ms"] / d["reads"] if d["reads"] > 0 else None,
            "w_await": d["wr_ms"] / d["writes"] if d["writes"] > 0 else None,
            "queue": d["weighted_ms"] / (dt * 1000.0),
        }
    return res


def _taux_reseau(na, nb, dt):
    """{interface: {rx_kib_s, tx_kib_s, errors, pertes}} sur l'intervalle.

    Les interfaces d'invités (INVITES_RESEAU, une à quatre par carte
    d'invité) sont sommées dès l'échantillon dans la seule ligne
    GROUPE_INVITES : sur un hyperviseur chargé, elles se comptent par
    centaines, et chaque échantillon garde ainsi une taille bornée par
    les interfaces de l'hôte. Le nom du groupe dépasse les 15 caractères
    d'un nom d'interface Linux : aucune ne le porte. Une interface dont
    un compteur recule est retirée avant la somme."""
    res = {}
    groupe = None
    for nom, vb in nb.items():
        va = na.get(nom)
        if not va:
            continue
        d = [vb[i] - va[i] for i in range(4)]
        if min(d) < 0:
            continue
        ligne = {
            "rx_kib_s": d[0] / 1024.0 / dt,
            "tx_kib_s": d[1] / 1024.0 / dt,
            "errors": d[2],
            "drops": d[3],
        }
        if not nom.startswith(INVITES_RESEAU):
            res[nom] = ligne
            continue
        if groupe is None:
            groupe = dict.fromkeys(ligne, 0)
        for cle in groupe:
            groupe[cle] += ligne[cle]
    if groupe is not None:
        res[GROUPE_INVITES] = groupe
    return res


def _rapport_succes(succes, echecs):
    """% de succès, ou None sans activité ou si un compteur recule."""
    if succes < 0 or echecs < 0 or succes + echecs <= 0:
        return None
    return 100.0 * succes / (succes + echecs)


def _taux_arc(aa, ab):
    """Taux de succès de l'ARC (et du L2ARC) sur l'intervalle ; tailles
    lues au second instantané."""
    if not aa or not ab:
        return None

    def delta(cle):
        return ab.get(cle, 0) - aa.get(cle, 0)

    return {
        "hit": _rapport_succes(delta("hits"), delta("misses")),
        "size": ab.get("size", 0),
        "c_max": ab.get("c_max", 0),
        "c_min": ab.get("c_min", 0),
        "throttle": max(0, delta("memory_throttle_count")),
        "l2_hit": _rapport_succes(delta("l2_hits"), delta("l2_misses")),
    }


def _taux_invites(ia, ib, dt):
    """Par invité : processeur (100 % = un cœur), débit disque, attente
    du disque (PSI de son cgroup) ; mémoire lue au second instantané."""
    res = {}
    for vmid, gb in ib.items():
        ga = ia.get(vmid)
        if not ga or gb.get("cpu_usec") is None or ga.get("cpu_usec") is None:
            continue
        dcpu = gb["cpu_usec"] - ga["cpu_usec"]
        dlu = gb["io_rbytes"] - ga["io_rbytes"]
        decrit = gb["io_wbytes"] - ga["io_wbytes"]
        if dcpu < 0 or dlu < 0 or decrit < 0:
            continue
        attente = None
        if (
            gb.get("io_some_us") is not None
            and ga.get("io_some_us") is not None
            and gb["io_some_us"] >= ga["io_some_us"]
        ):
            delta = gb["io_some_us"] - ga["io_some_us"]
            attente = borner(delta / 1e6 / dt * 100.0)
        res[vmid] = {
            "kind": gb.get("kind", "?"),
            "cpu": dcpu / 1e6 / dt * 100.0,
            "mem": gb.get("mem"),
            "mem_max": gb.get("mem_max"),
            "io": (dlu + decrit) / dt,
            "io_some": attente,
        }
    return res


def taux(a, b, page_kib=4.0):
    """Différence de deux instantanés (b après a) : pourcentages et taux
    sur l'intervalle, ressource par ressource.

    Un compteur qui RECULE (invité relancé, tap recréée sous le même nom,
    disque rebranché) retire ce périphérique ou cet invité de
    l'échantillon : jamais de taux négatif.
    """
    dt = max(b["t"] - a["t"], 1e-6)
    res = {
        "dt": dt,
        "wall": b["wall"],
        "cpu": _taux_cpu(a.get("cpu"), b.get("cpu")),
        "psi": _taux_psi(a.get("psi") or {}, b.get("psi") or {}, dt),
        "disks": _taux_disques(a.get("disks") or {}, b.get("disks") or {}, dt),
        "net": _taux_reseau(a.get("net") or {}, b.get("net") or {}, dt),
        "arc": _taux_arc(a.get("arc"), b.get("arc")),
        "mem": b.get("mem") or {},
        "load": b.get("load"),
        "swap_in": None,
        "swap_out": None,
        "guests": _taux_invites(
            a.get("guests") or {}, b.get("guests") or {}, dt
        ),
    }
    sa, sb = a.get("swap") or {}, b.get("swap") or {}
    for cle, sortie in (("pswpin", "swap_in"), ("pswpout", "swap_out")):
        if cle in sa and cle in sb and sb[cle] >= sa[cle]:
            res[sortie] = (sb[cle] - sa[cle]) * page_kib / dt
    return res


def disque_le_plus_occupe(r):
    """(périphérique, % d'utilisation) le plus occupé d'un taux, ou
    (None, 0.0)."""
    if not r.get("disks"):
        return None, 0.0
    dev = max(r["disks"], key=lambda d: r["disks"][d]["util"])
    return dev, r["disks"][dev]["util"]


class CumulVirtuels:
    """Les périphériques virtuels non physiques (zd, dm-, md) résumés au
    fil de la mesure : nombre d'échantillons, sommes et maximum, et non
    un taux par échantillon. Un hyperviseur en porte un par disque
    d'invité, des centaines parfois : gardés échantillon par échantillon,
    ils feraient grossir l'outil sur l'hôte même dont il mesure la
    mémoire. Leurs E/S sont déjà comptées sur les disques physiques et
    par invité, et ils ne sont jamais jugés.

    `retirer(r)` les enlève de r["disks"] et les cumule. Un centile
    demande toutes les valeurs : leurs colonnes de 95e centile (util,
    attentes) restent None."""

    CLES = ("util", "r_s", "w_s", "rkb_s", "wkb_s")

    def __init__(self, blocs):
        self.blocs = blocs
        self.cumuls = {}

    def _resume(self, dev):
        info = self.blocs.info(dev)
        return (
            info is not None
            and info["kind"] == "virtual"
            and not info["physical"]
        )

    def retirer(self, r):
        disques = r.get("disks") or {}
        for dev in [d for d in disques if self._resume(d)]:
            v = disques.pop(dev)
            c = self.cumuls.get(dev)
            if c is None:
                c = dict.fromkeys(self.CLES, 0.0)
                c.update({"n": 0, "util_max": 0.0})
                self.cumuls[dev] = c
            c["n"] += 1
            for cle in self.CLES:
                c[cle] += v[cle]
            c["util_max"] = max(c["util_max"], v["util"])

    def lignes(self):
        """{dev: ligne d'analyser_disques} des périphériques restés à 1 %
        d'utilisation ou plus à un moment de la mesure."""
        res = {}
        for dev, c in sorted(self.cumuls.items()):
            if c["util_max"] < 1:
                continue
            n = float(c["n"])
            res[dev] = {
                "kind": "virtual",
                "util_avg": c["util"] / n,
                "util_p95": None,
                "util_max": c["util_max"],
                "r_s_avg": c["r_s"] / n,
                "w_s_avg": c["w_s"] / n,
                "rkb_s_avg": c["rkb_s"] / n,
                "wkb_s_avg": c["wkb_s"] / n,
                "r_await_p95": None,
                "w_await_p95": None,
                "level": None,
            }
        return res


# ----------------------------------------------------------------------- #
# CSV des échantillons bruts
# ----------------------------------------------------------------------- #
def entete_csv(disques):
    return (
        list(COLONNES_CSV)
        + [d + "_util" for d in disques]
        + [d + "_r_await" for d in disques]
        + [d + "_w_await" for d in disques]
    )


def ligne_csv(r, disques):
    """Une ligne par échantillon. Les colonnes de disques sont fixées
    avant la mesure : une valeur absente est une cellule vide."""

    def v(x, motif="{:.2f}"):
        return "" if x is None else motif.format(x)

    c = r.get("cpu") or {}
    psi = r.get("psi") or {}
    arc = r.get("arc")
    dispo = (r.get("mem") or {}).get("MemAvailable")
    horodatage = datetime.datetime.fromtimestamp(r["wall"]).astimezone()
    disques_r = r.get("disks") or {}
    return (
        [
            horodatage.isoformat(timespec="seconds"),
            str(int(r["wall"])),
            v(c.get("busy")),
            v(c.get("iowait")),
            v(c.get("steal")),
            v(psi.get("cpu", {}).get("some")),
            v(psi.get("io", {}).get("some")),
            v(psi.get("io", {}).get("full")),
            v(psi.get("memory", {}).get("some")),
            v(dispo / 1024.0 if dispo is not None else None, "{:.0f}"),
            v(r.get("swap_in")),
            v(r.get("swap_out")),
            v(arc["size"] / 1048576.0 if arc else None, "{:.0f}"),
            v(arc.get("hit") if arc else None),
        ]
        + [v((disques_r.get(d) or {}).get("util")) for d in disques]
        + [v((disques_r.get(d) or {}).get("r_await")) for d in disques]
        + [v((disques_r.get(d) or {}).get("w_await")) for d in disques]
    )


class EcrivainCsv:
    """Les échantillons bruts dans `fichier`, une ligne écrite et vidée
    par échantillon.

    Une erreur d'écriture (disque plein, quota, E/S) ne remonte jamais :
    elle part en une ligne sur `erreur`, est gardée dans `panne`, et les
    écritures suivantes sont sautées. La mesure continue et le rapport
    sort ; le fichier garde les lignes écrites avant la panne."""

    def __init__(self, fichier, disques, erreur=None):
        self.fichier = fichier
        self.disques = list(disques)
        self.erreur = erreur or sys.stderr
        self.panne = None
        self.ecrivain = csv.writer(fichier)
        self._ecrire(entete_csv(self.disques))

    def _ecrire(self, ligne):
        if self.panne is not None:
            return
        try:
            self.ecrivain.writerow(ligne)
            self.fichier.flush()
        except OSError as err:
            self._en_panne(err)

    def _en_panne(self, err):
        self.panne = str(err)
        print(
            "CSV disabled: %s (the measurement goes on)" % self.panne,
            file=self.erreur,
            flush=True,
        )

    def ecrire(self, r):
        self._ecrire(ligne_csv(r, self.disques))

    def fermer(self):
        """Ferme le fichier ; une erreur au dernier vidage devient la
        panne, si aucune ne l'a précédée. Un fichier déjà en panne garde
        des données non vidées : sa fermeture échoue de nouveau, et
        l'erreur est la même."""
        try:
            self.fichier.close()
        except OSError as err:
            if self.panne is None:
                self._en_panne(err)


# ----------------------------------------------------------------------- #
# Boucle d'échantillonnage
# ----------------------------------------------------------------------- #
def echantillonner(
    racine,
    systeme,
    blocs,
    duree,
    intervalle,
    avec_invites,
    ecrivain,
    erreur,
    cumul=None,
):
    """(échantillons, interrompu, début mur). Un échantillon toutes les
    `intervalle` secondes jusqu'à `duree` ; Ctrl-C arrête la mesure et
    garde ce qui a été pris. Une ligne de progression part sur stderr
    toutes les max(PROGRES_MIN_S, intervalle) secondes. Avec `cumul`
    (CumulVirtuels), les périphériques virtuels quittent chaque
    échantillon pour leur résumé."""
    echantillons = []
    interrompu = False
    page_kib = systeme.page_kib()
    precedent = instantane(racine, systeme, blocs, avec_invites)
    debut, debut_mur = precedent["t"], precedent["wall"]
    fin = debut + duree
    pas_progres = max(PROGRES_MIN_S, intervalle)
    dernier_progres = debut
    try:
        while True:
            reste = fin - systeme.horloge()
            if reste <= 0:
                break
            systeme.dormir(min(intervalle, reste))
            courant = instantane(racine, systeme, blocs, avec_invites)
            r = taux(precedent, courant, page_kib)
            precedent = courant
            if cumul is not None:
                cumul.retirer(r)
            echantillons.append(r)
            if ecrivain is not None:
                ecrivain.ecrire(r)
            if courant["t"] - dernier_progres >= pas_progres:
                dernier_progres = courant["t"]
                dev, util = disque_le_plus_occupe(r)
                psi = r["psi"]
                print(
                    "  [%s / %s] sample %d: CPU %s %% - busiest disk %s %.0f %%"
                    " - I/O wait %s %% - memory wait %s %%"
                    % (
                        duree_humaine(courant["t"] - debut),
                        duree_humaine(duree),
                        len(echantillons),
                        fmt((r["cpu"] or {}).get("busy"), "{:.0f}"),
                        dev or "-",
                        util,
                        fmt(psi.get("io", {}).get("some")),
                        fmt(psi.get("memory", {}).get("some")),
                    ),
                    file=erreur,
                    flush=True,
                )
    except KeyboardInterrupt:
        interrompu = True
        print(
            "\nMeasurement interrupted (Ctrl-C) after %d sample(s): the"
            " report covers what was measured." % len(echantillons),
            file=erreur,
            flush=True,
        )
    return echantillons, interrompu, debut_mur


# ----------------------------------------------------------------------- #
# Analyse
# ----------------------------------------------------------------------- #
class Conseils:
    """Réglages suggérés : priorité, identifiant stable, texte, et les
    commandes qui les feraient — affichées, jamais exécutées."""

    def __init__(self):
        self.liste = []

    def ajouter(self, priorite, ident, texte, commandes=()):
        self.liste.append(
            {
                "priority": priorite,
                "id": ident,
                "text": texte,
                "commands": list(commandes),
            }
        )

    def tries(self):
        return sorted(self.liste, key=lambda c: PRIORITES.index(c["priority"]))


def choisir(candidats):
    """(niveau, raison) le plus grave d'une liste, le premier à égalité."""
    retenu = candidats[0]
    for niveau, raison in candidats:
        if NIVEAUX.index(niveau) > NIVEAUX.index(retenu[0]):
            retenu = (niveau, raison)
    return retenu


def analyser_cpu(ech, faits, conseils):
    occupe = [s["cpu"]["busy"] for s in ech if s["cpu"]]
    vol = [s["cpu"]["steal"] for s in ech if s["cpu"]]
    iowait = [s["cpu"]["iowait"] for s in ech if s["cpu"]]
    psi = [s["psi"].get("cpu", {}).get("some") for s in ech]
    charge = [s.get("load") for s in ech]
    coeurs = faits.get("cores") or 1
    par_coeur = [x / coeurs for x in charge if x is not None]
    res = {
        "busy_avg": avg(occupe),
        "busy_p95": pct(occupe, 95),
        "busy_max": maxi(occupe),
        "iowait_avg": avg(iowait),
        "steal_avg": avg(vol),
        "load_avg": avg(charge),
        "load_p95": pct(charge, 95),
        "load_per_core_p95": pct(par_coeur, 95),
        "psi_some_avg": avg(psi),
        "psi_some_p95": pct(psi, 95),
    }
    candidats = [("ok", "processors are not a limit")]
    a_psi = res["psi_some_avg"]
    if a_psi is not None and a_psi >= CPU_PSI_LIMITE:
        candidats.append(
            (
                "limiting",
                "tasks wait for a processor %.0f %% of the time" % a_psi,
            )
        )
    elif a_psi is not None and a_psi >= CPU_PSI_ATTN:
        candidats.append(
            (
                "watch",
                "tasks wait for a processor %.0f %% of the time" % a_psi,
            )
        )
    if (res["busy_p95"] or 0) >= CPU_OCCUPE_ATTN:
        candidats.append(
            (
                "watch",
                "processors are %.0f %% busy at peaks (95th percentile)"
                % res["busy_p95"],
            )
        )
    par_coeur_p95 = res["load_per_core_p95"]
    if par_coeur_p95 is not None:
        motif = (
            "load %.1f per core at peaks (Linux load also counts tasks"
            " waiting for the disk)" % par_coeur_p95
        )
        if a_psi is None and par_coeur_p95 >= CHARGE_PAR_COEUR_LIMITE:
            candidats.append(("limiting", motif + ", PSI unavailable"))
        elif par_coeur_p95 >= CHARGE_PAR_COEUR_ATTN:
            candidats.append(("watch", motif))
    if (res["steal_avg"] or 0) >= VOL_LIMITE:
        candidats.append(
            (
                "limiting",
                "%.0f %% of processor time is stolen by another hypervisor"
                % res["steal_avg"],
            )
        )
        conseils.ajouter(
            "high",
            "steal",
            "Processor time stolen by another hypervisor (steal %.0f %%):"
            " this host is itself virtualised or overbooked; ask the"
            " provider or move it." % res["steal_avg"],
        )
    niveau, raison = choisir(candidats)
    if faits.get("governor") in ("powersave", "conservative", "ondemand") and (
        niveau != "ok"
    ):
        conseils.ajouter(
            "medium",
            "governor",
            "CPU frequency governor '%s' while the processors are busy:"
            " 'performance' keeps the frequency up (more power used)."
            " Make it permanent with cpufrequtils or a systemd unit."
            % faits["governor"],
            [
                "echo performance | tee"
                " /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor"
            ],
        )
    return res, {"level": niveau, "reason": raison}


def analyser_memoire(ech, faits, conseils):
    """Section mémoire, verdict, conseils swappiness et ARC."""
    total = faits.get("mem_total_kib") or 0
    dispo = [s["mem"].get("MemAvailable") for s in ech]
    swap_utilise = [
        s["mem"]["SwapTotal"] - s["mem"]["SwapFree"]
        for s in ech
        if "SwapTotal" in s["mem"] and "SwapFree" in s["mem"]
    ]
    entree = [s.get("swap_in") for s in ech]
    sortie = [s.get("swap_out") for s in ech]
    echange = [
        (x or 0) + (y or 0)
        for x, y in zip(entree, sortie)
        if x is not None or y is not None
    ]
    psi = [s["psi"].get("memory", {}).get("some") for s in ech]
    psi_full = [s["psi"].get("memory", {}).get("full") for s in ech]
    dispo_valides = [x for x in dispo if x is not None]
    dispo_min = min(dispo_valides) if dispo_valides else None
    res = {
        "total_kib": total or None,
        "available_min_kib": dispo_min,
        "available_avg_kib": avg(dispo),
        "swap_used_kib": maxi(swap_utilise),
        "swap_in_kib_s_avg": avg(entree),
        "swap_out_kib_s_avg": avg(sortie),
        "psi_some_avg": avg(psi),
        "psi_full_avg": avg(psi_full),
    }
    candidats = [("ok", "memory is not a limit")]
    a_psi = res["psi_some_avg"]
    if a_psi is not None and a_psi >= MEM_PSI_LIMITE:
        candidats.append(
            (
                "limiting",
                "tasks wait for memory (reclaim, swap) %.0f %% of the time"
                % a_psi,
            )
        )
    elif a_psi is not None and a_psi >= MEM_PSI_ATTN:
        candidats.append(
            ("watch", "tasks wait for memory %.1f %% of the time" % a_psi)
        )
    if (
        dispo_min is not None
        and total
        and dispo_min < total * MEM_DISPO_MIN_PCT / 100.0
    ):
        candidats.append(
            (
                "watch",
                "available memory fell under %.0f %% of the RAM"
                % MEM_DISPO_MIN_PCT,
            )
        )
    if (avg(echange) or 0) >= SWAP_ACTIF_KIB_S:
        candidats.append(
            (
                "watch",
                "active swapping (%.0f KiB/s in and out on average)"
                % avg(echange),
            )
        )
    niveau, raison = choisir(candidats)
    swappiness = faits.get("swappiness") or ""
    if (
        (res["swap_used_kib"] or 0) > SWAP_UTILISE_CONSEIL_KIB
        and swappiness.isdigit()
        and int(swappiness) > SWAPPINESS_CIBLE
    ):
        conseils.ajouter(
            "medium",
            "swappiness",
            "Swap in use (%.1f GiB) with vm.swappiness=%s: on a ZFS host, %d"
            " keeps the guests in RAM."
            % (res["swap_used_kib"] / 1048576.0, swappiness, SWAPPINESS_CIBLE),
            [
                "sysctl -w vm.swappiness=%d" % SWAPPINESS_CIBLE,
                "echo 'vm.swappiness = %d' > /etc/sysctl.d/90-swappiness.conf"
                % SWAPPINESS_CIBLE,
            ],
        )
    return res, {"level": niveau, "reason": raison}


def commandes_arc(octets):
    return [
        "echo %d > /sys/module/zfs/parameters/zfs_arc_max" % octets,
        "echo 'options zfs zfs_arc_max=%d' > /etc/modprobe.d/zfs.conf"
        % octets,
        "update-initramfs -u -k all",
    ]


def analyser_arc(ech, memoire, niveau_memoire, conseils):
    """Section ARC et conseils de taille maximale. Réduire quand la
    mémoire est tendue et que l'ARC peut en prendre plus de la moitié ;
    agrandir quand tout va bien, que le taux de succès est bas et que la
    RAM reste largement libre."""
    arcs = [s["arc"] for s in ech if s.get("arc")]
    if not arcs:
        return None
    succes = [x["hit"] for x in arcs]
    res = {
        "size_bytes": arcs[-1]["size"],
        "c_max_bytes": arcs[-1]["c_max"],
        "hit_avg": avg(succes),
        "hit_p5": pct(succes, 5),
        "throttle": sum(x.get("throttle", 0) for x in arcs),
    }
    total_kib = memoire.get("total_kib") or 0
    total_gib = total_kib / 1048576.0
    cmax_gib = res["c_max_bytes"] / float(2**30)
    plafond = (
        "The second command replaces /etc/modprobe.d/zfs.conf: merge it by"
        " hand if that file holds other options. The last one is needed"
        " when the root file system is on ZFS."
    )
    if (
        niveau_memoire != "ok"
        and total_gib
        and cmax_gib > total_gib * ARC_PART_MAX_SI_TENDU
    ):
        cible = max(2, int(total_gib * ARC_PART_CIBLE_BAISSE))
        conseils.ajouter(
            "high",
            "arc_max_lower",
            "Memory is short while the ZFS ARC may take up to %.0f GiB:"
            " limit it to about %d GiB so the guests keep their memory. %s"
            % (cmax_gib, cible, plafond),
            commandes_arc(cible * 2**30),
        )
    elif (
        niveau_memoire == "ok"
        and res["hit_avg"] is not None
        and res["hit_avg"] < ARC_SUCCES_BAS_PCT
        and (memoire.get("available_avg_kib") or 0)
        > total_kib * ARC_DISPO_LARGE
    ):
        cible = int(min(total_gib * ARC_PART_CIBLE_HAUSSE, cmax_gib * 2 + 2))
        if cible > cmax_gib + 1:
            conseils.ajouter(
                "high",
                "arc_max_raise",
                "ARC hit ratio only %.0f %% while %.1f GiB of RAM stay free:"
                " a larger ARC (%d GiB) serves more reads from RAM, the"
                " cheapest way to make rotational disks feel faster. %s"
                % (
                    res["hit_avg"],
                    (memoire.get("available_avg_kib") or 0) / 1048576.0,
                    cible,
                    plafond,
                ),
                commandes_arc(cible * 2**30),
            )
    return res


def juger_disque(genre, u95, r95, w95):
    """Niveau d'un disque. Rotatif : utilisation et attente. SSD, NVMe :
    attente seulement. Type inconnu : attente, au seuil des rotatifs.
    Virtuel : None, jamais jugé."""
    if genre == "virtual":
        return None
    lente = max(r95 or 0, w95 or 0)
    if genre == "HDD":
        lent = lente >= ATTENTE_HDD_LENTE_MS
        u95 = u95 or 0
        if u95 >= UTIL_LIMITE or (u95 >= UTIL_ATTN and lent):
            return "limiting"
        if u95 >= UTIL_ATTN or lent:
            return "watch"
        return "ok"
    seuil = ATTENTE_HDD_LENTE_MS if genre == "?" else ATTENTE_SSD_LENTE_MS
    return "watch" if lente >= seuil else "ok"


def analyser_disques(ech, faits, blocs, conseils, cumul=None):
    """Par disque vu dans les échantillons : utilisation, opérations,
    débits, attente au 95e centile (échantillons actifs seulement) et
    niveau. Un périphérique virtuel resté sous 1 % est caché. Les
    périphériques résumés par `cumul` (CumulVirtuels) s'y ajoutent."""
    res = cumul.lignes() if cumul is not None else {}
    for dev in sorted({d for s in ech for d in s["disks"]}):
        valeurs = [s["disks"][dev] for s in ech if dev in s["disks"]]
        info = blocs.info(dev) or {"kind": "?", "physical": False}
        util = [v["util"] for v in valeurs]
        if info["kind"] == "virtual" and not info["physical"]:
            if (maxi(util) or 0) < 1:
                continue
        lect = [
            v["r_await"]
            for v in valeurs
            if v["r_await"] is not None and v["r_s"] >= OPS_MIN_ATTENTE
        ]
        ecr = [
            v["w_await"]
            for v in valeurs
            if v["w_await"] is not None and v["w_s"] >= OPS_MIN_ATTENTE
        ]
        ligne = {
            "kind": info["kind"],
            "util_avg": avg(util),
            "util_p95": pct(util, 95),
            "util_max": maxi(util),
            "r_s_avg": avg([v["r_s"] for v in valeurs]),
            "w_s_avg": avg([v["w_s"] for v in valeurs]),
            "rkb_s_avg": avg([v["rkb_s"] for v in valeurs]),
            "wkb_s_avg": avg([v["wkb_s"] for v in valeurs]),
            "r_await_p95": pct(lect, 95),
            "w_await_p95": pct(ecr, 95),
        }
        ligne["level"] = juger_disque(
            info["kind"],
            ligne["util_p95"],
            ligne["r_await_p95"],
            ligne["w_await_p95"],
        )
        res[dev] = ligne
    for nom, info in sorted(faits["disks"].items()):
        if info.get("smart") == "FAILED":
            conseils.ajouter(
                "high",
                "smart_failed",
                "%s: SMART health FAILED; replace this disk before anything"
                " else (a failing disk retries and slows its whole pool)."
                % nom,
                ["smartctl -a /dev/%s" % nom],
            )
        if info.get("scheduler") in ("cfq", "bfq") and info["kind"] in (
            "SSD",
            "NVMe",
        ):
            conseils.ajouter(
                "low",
                "scheduler",
                "%s (%s) uses the '%s' I/O scheduler: 'none' or"
                " 'mq-deadline' suit flash storage better."
                % (nom, info["kind"], info["scheduler"]),
                ["echo none > /sys/block/%s/queue/scheduler" % nom],
            )
    return res


def analyser_io_psi(ech):
    some = [s["psi"].get("io", {}).get("some") for s in ech]
    full = [s["psi"].get("io", {}).get("full") for s in ech]
    return {
        "some_avg": avg(some),
        "some_p95": pct(some, 95),
        "some_max": maxi(some),
        "full_avg": avg(full),
    }


def verdict_disques(disques, io_psi):
    some = io_psi["some_avg"]
    full = io_psi["full_avg"]
    candidats = [("ok", "disks are not a limit")]
    if some is not None and some >= IO_PSI_LIMITE:
        candidats.append(
            (
                "limiting",
                "tasks wait for the disks %.0f %% of the time" % some,
            )
        )
    elif some is not None and some >= IO_PSI_ATTN:
        candidats.append(
            ("watch", "tasks wait for the disks %.1f %% of the time" % some)
        )
    if full is not None and full >= IO_FULL_LIMITE:
        candidats.append(
            (
                "limiting",
                "all tasks wait for the disks %.0f %% of the time" % full,
            )
        )
    for dev, ligne in sorted(disques.items()):
        if ligne["level"] in ("watch", "limiting"):
            candidats.append(
                (
                    ligne["level"],
                    "%s (%s) is %s"
                    % (
                        dev,
                        ligne["kind"],
                        "saturated"
                        if ligne["level"] == "limiting"
                        else "busy or slow at times",
                    ),
                )
            )
    niveau, raison = choisir(candidats)
    return {"level": niveau, "reason": raison}


def analyser_zfs(zfs, io_psi, conseils):
    """Conseils par pool (scrub, santé, remplissage, fragmentation, ashift,
    SLOG, special) et par dataset (compression, atime, sync). Le support
    d'un pool est celui de SES disques de données. Chaque nom de pool ou
    de dataset passe par shlex.quote dans les commandes : ZFS admet une
    espace dans un nom, et `zfs set` prend plusieurs datasets."""
    if not zfs:
        return
    some = io_psi.get("some_avg") or 0
    for nom, p in sorted(zfs["pools"].items()):
        if p["scrub"]:
            conseils.ajouter(
                "medium",
                "scrub_running",
                "Pool %s: scrub or resilver in progress during the"
                " measurement (%s); it slows everything down, measure again"
                " after it ends." % (nom, p["scrub"]),
                ["zpool status %s" % shlex.quote(nom)],
            )
        if p["health"] != "ONLINE":
            conseils.ajouter(
                "high",
                "pool_health",
                "Pool %s is %s: find and replace the faulty device first."
                % (nom, p["health"]),
                ["zpool status -v %s" % shlex.quote(nom)],
            )
        cap = p["cap_pct"]
        if cap is not None and cap >= POOL_PLEIN_ATTN:
            conseils.ajouter(
                "high" if cap >= POOL_PLEIN_HAUT else "medium",
                "pool_capacity",
                "Pool %s is %d %% full: ZFS slows down strongly beyond %d %%"
                " (block allocation); free space or add disks."
                % (nom, cap, POOL_PLEIN_ATTN),
                ["zfs list -o space -r %s" % shlex.quote(nom)],
            )
        frag = p["frag_pct"]
        if frag is not None and frag >= POOL_FRAG_CONSEIL:
            conseils.ajouter(
                "low",
                "pool_fragmentation",
                "Pool %s: free space fragmentation %d %%; writes get slower,"
                " and only a copy to a new pool (zfs send / receive) removes"
                " it." % (nom, frag),
            )
        if p["ashift"] == "9" and set(p["media"]) & {"HDD", "SSD"}:
            conseils.ajouter(
                "medium",
                "pool_ashift",
                "Pool %s: ashift=9 (512-byte sectors) on disks with 4K"
                " sectors; each small write costs a read-modify-write, and"
                " only a new pool (ashift=12) fixes it." % nom,
            )
        attente = (p.get("latency_ms") or {}).get("syncq_w")
        if (
            attente is not None
            and attente >= SYNCQ_LENTE_MS
            and not p["log_disks"]
            and not p.get("has_log")
        ):
            conseils.ajouter(
                "medium",
                "slog",
                "Pool %s: synchronous writes wait %.0f ms on average"
                " (PostgreSQL commits, NFS): a small mirrored SSD log device"
                " (SLOG) makes them fast without replacing the data disks."
                " Replace the placeholders with the SSD devices."
                % (nom, attente),
                ["zpool add %s log mirror <ssd-1> <ssd-2>" % shlex.quote(nom)],
            )
        if (
            "HDD" in p["media"]
            and not p["special_disks"]
            and not p.get("has_special")
            and some >= IO_PSI_ATTN
        ):
            conseils.ajouter(
                "medium",
                "special_vdev",
                "Pool %s stores its data on rotational disks without a"
                " special device: two small mirrored SSD as special vdev"
                " hold the metadata and small blocks, so most random reads"
                " of PostgreSQL hit flash; an intermediate step before"
                " replacing the disks. Replace the placeholders with the"
                " SSD devices." % nom,
                [
                    "zpool add %s special mirror <ssd-1> <ssd-2>"
                    % shlex.quote(nom),
                    "zfs set special_small_blocks=16K %s" % shlex.quote(nom),
                ],
            )
    analyser_datasets(zfs, conseils)


def _signale(datasets, nom, propriete, mauvaise):
    """True si `nom` porte `mauvaise` pour `propriete` et en est la source :
    valeur locale, ou plus haut dataset d'une chaîne (son parent n'a pas
    cette valeur). Un héritier n'est jamais signalé : le conseil porte
    sur la source."""
    valeur, source = datasets[nom].get(propriete, ("", ""))
    if valeur != mauvaise or source.startswith("inherited"):
        return False
    if source == "local":
        return True
    parent = nom.rsplit("/", 1)[0] if "/" in nom else ""
    if parent and parent in datasets:
        return datasets[parent].get(propriete, ("", ""))[0] != mauvaise
    return True


def analyser_datasets(zfs, conseils):
    datasets = zfs.get("datasets") or {}
    signales = []
    nombre = 0
    for nom in sorted(datasets):
        genre = datasets[nom].get("type", ("", ""))[0]
        if _signale(datasets, nom, "compression", "off"):
            signales.append(
                {"dataset": nom, "property": "compression", "value": "off"}
            )
            if nombre < CONSEILS_DATASETS_MAX:
                nombre += 1
                conseils.ajouter(
                    "medium",
                    "zfs_compression",
                    "Dataset %s: compression off; lz4 costs almost no"
                    " processor and reduces disk reads and writes (new data"
                    " only)." % nom,
                    ["zfs set compression=lz4 %s" % shlex.quote(nom)],
                )
        if (
            genre == "filesystem"
            and _signale(datasets, nom, "atime", "on")
            and datasets[nom].get("relatime", ("", ""))[0] != "on"
        ):
            signales.append(
                {"dataset": nom, "property": "atime", "value": "on"}
            )
            if nombre < CONSEILS_DATASETS_MAX:
                nombre += 1
                conseils.ajouter(
                    "medium",
                    "zfs_atime",
                    "Dataset %s: atime=on without relatime; every read"
                    " writes the access time, atime=off removes these"
                    " writes." % nom,
                    ["zfs set atime=off %s" % shlex.quote(nom)],
                )
        if _signale(datasets, nom, "sync", "disabled"):
            signales.append(
                {"dataset": nom, "property": "sync", "value": "disabled"}
            )
            conseils.ajouter(
                "high",
                "sync_disabled",
                "Dataset %s: sync=disabled; fast, but an outage can lose"
                " the last seconds of committed transactions (PostgreSQL)."
                " Use 'standard' unless this is deliberate." % nom,
                ["zfs set sync=standard %s" % shlex.quote(nom)],
            )
    zfs["datasets_flagged"] = signales


def genre_interface(racine, nom):
    """guest (tap, veth, pare-feu Proxmox), bridge, physical, bond ou
    other, d'après /sys/class/net."""
    if nom.startswith(INVITES_RESEAU):
        return "guest"
    base = chemin(racine, "/sys/class/net/" + nom)
    if os.path.isdir(os.path.join(base, "bridge")):
        return "bridge"
    if os.path.exists(os.path.join(base, "device")):
        return "physical"
    if os.path.isdir(os.path.join(base, "bonding")):
        return "bond"
    return "other"


def vitesse_lien(racine, nom):
    """Vitesse du lien en Mb/s, ou None (-1, lien coupé, illisible)."""
    texte = (lire(racine, "/sys/class/net/%s/speed" % nom) or "").strip()
    try:
        valeur = int(texte)
    except ValueError:
        return None
    return valeur if valeur > 0 else None


def analyser_reseau(ech, racine):
    """Par interface physique, pont ou lien agrégé, et un total des
    interfaces d'invités : débits, erreurs, pertes, vitesse et niveau.
    Une interface restée sous 1 Kio/s sans erreur ni perte est cachée.

    Niveau : utilisation du lien au 95e centile (le plus grand de
    réception et émission) contre sa vitesse ; des erreurs pendant la
    mesure → watch. Les pertes sont une information."""
    genres = {GROUPE_INVITES: "guest"}
    series = {}
    for s in ech:
        groupe = None
        for nom, v in s.get("net", {}).items():
            if nom not in genres:
                genres[nom] = genre_interface(racine, nom)
            if genres[nom] == "guest":
                if groupe is None:
                    groupe = {
                        "rx_kib_s": 0.0,
                        "tx_kib_s": 0.0,
                        "errors": 0,
                        "drops": 0,
                    }
                for cle in groupe:
                    groupe[cle] += v[cle]
                continue
            series.setdefault(nom, []).append(v)
        if groupe is not None:
            series.setdefault(GROUPE_INVITES, []).append(groupe)
    res = {}
    candidats = [("ok", "network links are not a limit")]
    for nom in sorted(series):
        valeurs = series[nom]
        rx = [v["rx_kib_s"] for v in valeurs]
        tx = [v["tx_kib_s"] for v in valeurs]
        erreurs = sum(v["errors"] for v in valeurs)
        pertes = sum(v["drops"] for v in valeurs)
        if max(rx + tx + [0]) < 1 and not erreurs and not pertes:
            continue
        genre = genres.get(nom, "other")
        vitesse = vitesse_lien(racine, nom) if genre == "physical" else None
        niveau = "ok"
        utilisation = None
        if vitesse:
            pic = pct([max(x, y) for x, y in zip(rx, tx)], 95) or 0
            utilisation = pic * 1024 * 8 / 1e6 / vitesse * 100.0
            if utilisation >= RESEAU_LIMITE_PCT:
                niveau = "limiting"
            elif utilisation >= RESEAU_ATTN_PCT:
                niveau = "watch"
            if niveau != "ok":
                candidats.append(
                    (
                        niveau,
                        "%s uses %.0f %% of its %d Mb/s link at peaks"
                        % (nom, utilisation, vitesse),
                    )
                )
        if erreurs and genre != "guest":
            niveau = pire(niveau, "watch")
            candidats.append(
                (
                    "watch",
                    "%s counted %d error(s) during the measurement"
                    % (nom, erreurs),
                )
            )
        res[nom] = {
            "kind": genre,
            "rx_kib_s_avg": avg(rx),
            "rx_kib_s_max": maxi(rx),
            "tx_kib_s_avg": avg(tx),
            "tx_kib_s_max": maxi(tx),
            "errors": erreurs,
            "drops": pertes,
            "speed_mbps": vitesse,
            "link_util_p95": utilisation,
            "level": niveau,
        }
    niveau, raison = choisir(candidats)
    return res, {"level": niveau, "reason": raison}


def analyser_invites(ech, noms):
    """Une ligne par invité mesuré : processeur (100 % = un cœur),
    mémoire, débit disque et attente du disque vue DE L'INTÉRIEUR."""
    lignes = []
    for vmid in sorted(
        {g for s in ech for g in s.get("guests", {})},
        key=lambda x: int(x) if x.isdigit() else 0,
    ):
        valeurs = [
            s["guests"][vmid] for s in ech if vmid in s.get("guests", {})
        ]
        genre, nom, _texte = noms.get(
            vmid, (valeurs[-1].get("kind", "?"), "", "")
        )
        cpu = [v["cpu"] for v in valeurs]
        attente = [v["io_some"] for v in valeurs]
        lignes.append(
            {
                "vmid": vmid,
                "kind": genre,
                "name": nom,
                "cpu_avg": avg(cpu),
                "cpu_max": maxi(cpu),
                "mem_bytes": valeurs[-1].get("mem"),
                "mem_max_bytes": valeurs[-1].get("mem_max"),
                "io_bytes_s_avg": avg([v["io"] for v in valeurs]),
                "io_psi_some_avg": avg(attente),
                "io_psi_some_max": maxi(attente),
            }
        )
    lignes.sort(key=lambda g: -(g["io_bytes_s_avg"] or 0))
    return lignes


def conseils_config_vm(noms, conseils):
    """Conseils tirés des configurations de VM de /etc/pve, jamais
    appliqués (un redémarrage de la VM est nécessaire)."""
    for vmid, (genre, nom, texte) in sorted(
        noms.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 0
    ):
        if genre != "vm":
            continue
        qui = "VM %s (%s)" % (vmid, nom or "?")
        for m in re.finditer(
            r"^((scsi|virtio|sata|ide)\d+):\s*(\S+)\s*$", texte, re.M
        ):
            disque, bus, options = m.group(1), m.group(2), m.group(3)
            if "media=cdrom" in options:
                continue
            if bus in ("sata", "ide"):
                conseils.ajouter(
                    "medium",
                    "vm_bus",
                    "%s: disk %s on the emulated %s bus, which is slow;"
                    " VirtIO SCSI single with iothread=1 is faster (the"
                    " guest needs the driver)." % (qui, disque, bus.upper()),
                )
            if bus == "scsi" and "iothread=1" not in options:
                conseils.ajouter(
                    "low",
                    "vm_iothread",
                    "%s: SCSI disk %s without iothread=1; with the 'VirtIO"
                    " SCSI single' controller each disk gets its own I/O"
                    " thread. Takes effect after a VM restart."
                    % (qui, disque),
                    [
                        "qm set %s --%s %s"
                        % (vmid, disque, shlex.quote(options + ",iothread=1"))
                    ],
                )
            cache = re.search(r"cache=(\w+)", options)
            if cache and cache.group(1) in ("writeback", "unsafe"):
                conseils.ajouter(
                    "low",
                    "vm_cache",
                    "%s: disk %s uses cache '%s'; on ZFS it doubles the"
                    " ARC, 'none' is the usual choice."
                    % (qui, disque, cache.group(1)),
                    [
                        "qm set %s --%s %s"
                        % (
                            vmid,
                            disque,
                            shlex.quote(
                                options.replace(
                                    "cache=" + cache.group(1), "cache=none"
                                )
                            ),
                        )
                    ],
                )
        if re.search(r"^cpu:\s*kvm64\b", texte, re.M):
            conseils.ajouter(
                "low",
                "vm_cpu_type",
                "%s: CPU type kvm64 hides the instructions of the real"
                " processor; 'host' is faster when live migration to a"
                " different processor is not needed." % qui,
                ["qm set %s --cpu host" % vmid],
            )


def reponse_ssd(faits, disques, zfs, io_psi, invites):
    """« Des disques SSD sont-ils justifiés ? »

    Candidats : les disques physiques rotatifs qui PORTENT de la charge
    (dans les données d'un pool, ou actifs au 95e centile). Aucun →
    not_applicable. yes : un candidat à « limiting », ou une pression
    d'E/S forte alors que les rotatifs portent la majorité de
    l'utilisation ou du débit mesurés ; une pression due à un pool SSD
    ne vise donc pas un disque rotatif oisif. not_yet : un candidat à
    « watch », ou une pression modérée imputable aux rotatifs. no sinon.

    `zfs` à None alors que faits["zfs_loaded"] est vrai : les pools n'ont
    pas pu être lus, l'appartenance d'un disque à un pool est inconnue et
    la raison le dit au lieu d'affirmer qu'il n'en a aucun.
    """
    rotatifs = sorted(
        nom
        for nom, info in faits["disks"].items()
        if info["physical"] and info["kind"] == "HDD"
    )
    dans_pools = set()
    for p in ((zfs or {}).get("pools") or {}).values():
        dans_pools.update(p["data_disks"])
    actifs = [
        d
        for d in rotatifs
        if d in dans_pools
        or ((disques.get(d) or {}).get("util_p95") or 0)
        >= ACTIVITE_UTIL_P95_MIN
    ]
    res = {
        "answer": "not_applicable",
        "rotational_disks": actifs,
        "reason": "",
        "steps": [],
    }
    if not rotatifs:
        res["reason"] = "no rotational (HDD) disk on this host"
        return res
    if not actifs:
        if zfs is None and faits.get("zfs_loaded"):
            res["reason"] = (
                "the rotational disks (%s) carry no measured load; whether"
                " they belong to a ZFS pool is unknown, the pools could not"
                " be read (see notes)" % ", ".join(rotatifs)
            )
        else:
            res["reason"] = (
                "the rotational disks (%s) carry no measured load and belong"
                " to no ZFS pool" % ", ".join(rotatifs)
            )
        return res
    physiques = [
        d
        for d, ligne in disques.items()
        if (faits["disks"].get(d) or {}).get("physical")
        and ligne["kind"] != "virtual"
    ]

    def part(cles):
        total = sum(sum(disques[d][c] or 0 for c in cles) for d in physiques)
        rot = sum(
            sum(disques[d][c] or 0 for c in cles)
            for d in actifs
            if d in disques
        )
        return rot / total if total > 0 else 0.0

    majorite = (
        part(("util_avg",)) >= PART_ROTATIFS_MAJORITE
        or part(("rkb_s_avg", "wkb_s_avg")) >= PART_ROTATIFS_MAJORITE
    )
    some = io_psi.get("some_avg") or 0
    full = io_psi.get("full_avg") or 0
    limites = [
        d for d in actifs if (disques.get(d) or {}).get("level") == "limiting"
    ]
    surveilles = [
        d for d in actifs if (disques.get(d) or {}).get("level") == "watch"
    ]
    if limites or (
        majorite and (some >= IO_PSI_LIMITE or full >= IO_FULL_LIMITE)
    ):
        res["answer"] = "yes"
        res["reason"] = (
            "the rotational disks (%s) are a measured bottleneck: tasks"
            " waited for the disks %.1f %% of the time (all tasks %.1f %%)"
            % (", ".join(actifs), some, full)
        )
        if limites:
            ligne = disques[limites[0]]
            res["reason"] += ", %s busy %s %% with %s ms per operation" % (
                limites[0],
                fmt(ligne["util_p95"], "{:.0f}"),
                fmt(
                    max(ligne["r_await_p95"] or 0, ligne["w_await_p95"] or 0),
                    "{:.0f}",
                ),
            )
        etapes = []
        if zfs:
            etapes.append("a larger ZFS ARC if the RAM allows it")
            if any("HDD" in p["media"] for p in zfs["pools"].values()):
                etapes.append(
                    "a mirrored SSD 'special' vdev (metadata and small blocks)"
                )
                etapes.append(
                    "a mirrored SSD log device (SLOG) for synchronous writes"
                )
        etapes.append(
            "then SSD storage for the busiest guest%s"
            % (" (%s)" % invites[0]["vmid"] if invites else "")
        )
        res["steps"] = etapes
    elif surveilles or (majorite and some >= IO_PSI_ATTN):
        res["answer"] = "not_yet"
        res["reason"] = (
            "the rotational disks slow things down only at peaks (disk wait"
            " %.1f %% on average); measure over a full day (--duration 24h)"
            " including backups and busy hours" % some
        )
    else:
        res["answer"] = "no"
        res["reason"] = (
            "the rotational disks are not a limit for this load (disk wait"
            " %.1f %% on average, no disk saturated); slow first page loads"
            " after a restart come from a cold cache, not the disk type" % some
        )
    return res


def analyser(
    ech, faits, zfs, blocs, noms, racine, invites_ignores, cumul=None
):
    """Toutes les sections du rapport, au format du JSON (sans l'en-tête)."""
    conseils = Conseils()
    cpu, v_cpu = analyser_cpu(ech, faits, conseils)
    memoire, v_mem = analyser_memoire(ech, faits, conseils)
    arc = analyser_arc(ech, memoire, v_mem["level"], conseils)
    disques = analyser_disques(ech, faits, blocs, conseils, cumul)
    io_psi = analyser_io_psi(ech)
    v_disques = verdict_disques(disques, io_psi)
    reseau, v_reseau = analyser_reseau(ech, racine)
    analyser_zfs(zfs, io_psi, conseils)
    invites = None if invites_ignores else analyser_invites(ech, noms)
    conseils_config_vm(noms, conseils)
    section_zfs = None
    if zfs is not None or arc is not None:
        section_zfs = {
            "arc": arc,
            "pools": (zfs or {}).get("pools") or {},
            "summary": (zfs or {}).get("summary", ""),
            "datasets_flagged": (zfs or {}).get("datasets_flagged") or [],
        }
    ssd = reponse_ssd(faits, disques, zfs, io_psi, invites or [])
    verdicts = {
        "cpu": v_cpu,
        "memory": v_mem,
        "disks": v_disques,
        "network": v_reseau,
    }
    if not ech:
        verdicts = {}
        ssd = {
            "answer": "not_applicable",
            "rotational_disks": [],
            "reason": "no sample taken",
            "steps": [],
        }
    return {
        "cpu": cpu,
        "memory": memoire,
        "disks": disques,
        "io_psi": io_psi,
        "network": reseau,
        "zfs": section_zfs,
        "guests": invites,
        "verdicts": verdicts,
        "ssd": ssd,
        "suggestions": conseils.tries(),
    }


def arrondir(objet):
    """Les flottants du rapport à deux décimales, récursivement."""
    if isinstance(objet, float):
        return round(objet, 2)
    if isinstance(objet, dict):
        return {k: arrondir(v) for k, v in objet.items()}
    if isinstance(objet, (list, tuple)):
        return [arrondir(v) for v in objet]
    return objet


# ----------------------------------------------------------------------- #
# Rapport texte
# ----------------------------------------------------------------------- #
class Rendu:
    """Étiquettes de niveau, en couleur sur un terminal sans NO_COLOR."""

    COULEURS = {"ok": "32", "watch": "33", "limiting": "31"}

    def __init__(self, couleur):
        self.couleur = couleur

    def colorer(self, code, texte):
        return "\x1b[%sm%s\x1b[0m" % (code, texte) if self.couleur else texte

    def etiquette(self, niveau):
        if niveau is None:
            return "[-]"
        return self.colorer(self.COULEURS[niveau], "[%s]" % niveau.upper())


def go(octets):
    return "-" if octets is None else "%.1f GiB" % (octets / float(2**30))


def _texte_entete(r, faits):
    plateforme = faits["pve"] or "Linux " + faits["kernel"]
    out = [
        "PERFORMANCE OF %s - %s - %d sample(s) from %s over %s"
        % (
            r["host"],
            plateforme,
            r["samples"],
            r["started"],
            duree_humaine(r["duration_s"]),
        )
    ]
    avec_psi = (
        r["cpu"]["psi_some_avg"] is not None
        or r["io_psi"]["some_avg"] is not None
    )
    out.append(
        "  (waiting times from %s; this program used %.2f s of processor in"
        " all)"
        % ("/proc/pressure" if avec_psi else "unavailable", r["cost_cpu_s"])
    )
    out.extend("  Note: " + note for note in r["notes"])
    out.append("")
    if not r["samples"]:
        out.append(
            "No sample taken: nothing to analyse (interrupted too early)."
        )
    return out


def _texte_cpu(c, faits):
    out = [
        "PROCESSOR - %s, %s logical core(s), governor %s"
        % (
            faits["cpu_model"] or "?",
            faits["cores"],
            faits["governor"] or "?",
        ),
        "  busy: average %s %%, 95 %% of the time under %s %%, peak %s %%"
        " - iowait %s %% - steal %s %%"
        % (
            fmt(c["busy_avg"], "{:.0f}"),
            fmt(c["busy_p95"], "{:.0f}"),
            fmt(c["busy_max"], "{:.0f}"),
            fmt(c["iowait_avg"]),
            fmt(c["steal_avg"]),
        ),
        "  load: average %s, 95th percentile %s (%s per core); Linux load"
        " also counts tasks waiting for the disk"
        % (
            fmt(c["load_avg"]),
            fmt(c["load_p95"]),
            fmt(c["load_per_core_p95"], "{:.2f}"),
        ),
    ]
    if c["psi_some_avg"] is not None:
        out.append(
            "  waiting for a processor (PSI cpu some): average %s %%, 95 %% of"
            " the time under %s %%"
            % (fmt(c["psi_some_avg"]), fmt(c["psi_some_p95"]))
        )
    out.append("")
    return out


def _kio_en_octets(x):
    return None if x is None else x * 1024


def _texte_memoire(m, arc, faits, rendu):
    out = [
        "MEMORY - %s total, available at least %s (average %s) - swap used"
        " %s - swappiness %s - KSM %s"
        % (
            go(_kio_en_octets(m["total_kib"])),
            go(_kio_en_octets(m["available_min_kib"])),
            go(_kio_en_octets(m["available_avg_kib"])),
            go(_kio_en_octets(m["swap_used_kib"])),
            faits["swappiness"] or "?",
            "on" if faits["ksm"].get("run") else "off",
        ),
        "  swap in %s KiB/s, swap out %s KiB/s on average"
        % (fmt(m["swap_in_kib_s_avg"]), fmt(m["swap_out_kib_s_avg"])),
    ]
    if m["psi_some_avg"] is not None:
        out.append(
            "  waiting for memory (PSI memory): some %s %%, full %s %% on"
            " average (reclaim, swap)"
            % (fmt(m["psi_some_avg"]), fmt(m["psi_full_avg"]))
        )
    if arc:
        part = None
        if m["total_kib"]:
            part = 100.0 * arc["c_max_bytes"] / (m["total_kib"] * 1024)
        out.append(
            "  ZFS ARC: %s used, maximum %s (%s %% of the RAM) - hit ratio"
            " %s %% (95 %% of the samples above %s %%)"
            % (
                go(arc["size_bytes"]),
                go(arc["c_max_bytes"]),
                fmt(part, "{:.0f}"),
                fmt(arc["hit_avg"]),
                fmt(arc["hit_p5"], "{:.0f}"),
            )
        )
        if arc["throttle"]:
            out.append(
                "  %s ARC memory throttle: %d time(s), the ARC had to give"
                " memory back under pressure"
                % (rendu.etiquette("watch"), arc["throttle"])
            )
    out.append("")
    return out


def _mo(kio):
    return None if kio is None else kio / 1024.0


def _texte_disques(disques, io_psi, faits, rendu):
    gabarit = "  %-10s %-7s %8s %5s %5s  %7s %7s  %6s %6s  %7s %7s  %-10s %s"
    out = [
        "DISKS - % of the time busy, operations and throughput per second,"
        " wait per operation (ms)",
        gabarit
        % (
            "disk",
            "type",
            "util avg",
            "p95",
            "max",
            "read/s",
            "write/s",
            "MB/s r",
            "MB/s w",
            "wait r",
            "wait w",
            "level",
            "model",
        ),
    ]
    for dev, d in sorted(disques.items()):
        info = faits["disks"].get(dev) or {}
        out.append(
            gabarit
            % (
                dev,
                d["kind"],
                fmt(d["util_avg"], "{:.0f}%"),
                fmt(d["util_p95"], "{:.0f}%"),
                fmt(d["util_max"], "{:.0f}%"),
                fmt(d["r_s_avg"]),
                fmt(d["w_s_avg"]),
                fmt(_mo(d["rkb_s_avg"])),
                fmt(_mo(d["wkb_s_avg"])),
                fmt(d["r_await_p95"]),
                fmt(d["w_await_p95"]),
                rendu.etiquette(d["level"]),
                info.get("model", ""),
            )
        )
        if info.get("smart") == "FAILED":
            out.append(
                "  %s %s: SMART health FAILED"
                % (rendu.etiquette("limiting"), dev)
            )
    out.append(
        "  (wait = 95th percentile of the samples with activity; utilisation"
        " is judged on rotational disks only, flash serves requests in"
        " parallel)"
    )
    if io_psi["some_avg"] is not None:
        out.append(
            "  waiting for the disks (PSI io): some %s %% (95 %% under %s %%,"
            " peak %s %%), full %s %%"
            % (
                fmt(io_psi["some_avg"]),
                fmt(io_psi["some_p95"]),
                fmt(io_psi["some_max"], "{:.0f}"),
                fmt(io_psi["full_avg"]),
            )
        )
    out.append("")
    return out


LIBELLES_ATTENTE = (
    ("total_r", "total read"),
    ("total_w", "total write"),
    ("disk_r", "disk read"),
    ("disk_w", "disk write"),
    ("syncq_w", "sync queue write"),
    ("asyncq_w", "async queue write"),
)


def _texte_pool(nom, pool, rendu):
    taille = pool["size_bytes"] / 1e12 if pool["size_bytes"] else None
    out = [
        "  pool %s - %s TB, used %s %%, fragmentation %s %%, %s, ashift %s,"
        " vdevs %s"
        % (
            nom,
            fmt(taille, "{:.2f}"),
            fmt(pool["cap_pct"], "{}"),
            fmt(pool["frag_pct"], "{}"),
            pool["health"],
            pool["ashift"] or "?",
            ", ".join(pool["vdev_types"]) or "single disk(s)",
        ),
        "    data disks: %s (%s) - log: %s - cache: %s - special: %s"
        % (
            ", ".join(pool["data_disks"]) or "-",
            ", ".join(pool["media"]) or "?",
            ", ".join(pool["log_disks"]) or "-",
            ", ".join(pool["cache_disks"]) or "-",
            ", ".join(pool["special_disks"]) or "-",
        ),
    ]
    if pool["unresolved_vdevs"]:
        out.append(
            "    vdevs not mapped to a disk: "
            + ", ".join(pool["unresolved_vdevs"])
        )
    attentes = pool.get("latency_ms") or {}
    parties = [
        "%s %.1f ms" % (libelle, attentes[cle])
        for cle, libelle in LIBELLES_ATTENTE
        if attentes.get(cle) is not None
    ]
    if parties:
        out.append(
            "    average waits since the pool was imported: "
            + ", ".join(parties)
        )
    if pool["scrub"]:
        out.append("    %s %s" % (rendu.etiquette("watch"), pool["scrub"]))
    return out


def _texte_zfs(z, rendu):
    if z is None:
        return []
    out = ["ZFS" + (" - " + z["summary"] if z.get("summary") else "")]
    for nom, pool in sorted(z["pools"].items()):
        out.extend(_texte_pool(nom, pool, rendu))
    out.append(
        "  (a PostgreSQL dataset suits recordsize=16K for its 8 KiB pages;"
        " it applies to new files only, so set it before a restore)"
    )
    out.append("")
    return out


def _texte_reseau(reseau, rendu):
    out = ["NETWORK"]
    if not reseau:
        out.append("  no traffic measured")
    for nom, n in sorted(reseau.items()):
        ligne = (
            "  %-16s %-8s received %s MB/s (peak %s), sent %s MB/s (peak %s)"
            % (
                "guest interfaces" if nom == GROUPE_INVITES else nom,
                n["kind"],
                fmt(_mo(n["rx_kib_s_avg"]), "{:.2f}"),
                fmt(_mo(n["rx_kib_s_max"]), "{:.2f}"),
                fmt(_mo(n["tx_kib_s_avg"]), "{:.2f}"),
                fmt(_mo(n["tx_kib_s_max"]), "{:.2f}"),
            )
        )
        if n["speed_mbps"]:
            ligne += ", link %d Mb/s, %s %% used at peaks" % (
                n["speed_mbps"],
                fmt(n["link_util_p95"], "{:.0f}"),
            )
        if n["errors"] or n["drops"]:
            ligne += ", errors %d, drops %d" % (n["errors"], n["drops"])
        if n["level"] != "ok":
            ligne += " " + rendu.etiquette(n["level"])
        out.append(ligne)
    out.append("")
    return out


def _texte_invites(invites, ignores, top):
    if ignores == "cgroup_v1":
        return [
            "GUESTS - skipped: this host uses cgroup v1, read here as v2 only",
            "",
        ]
    if not invites:
        return []
    gabarit = "  %5s %-4s %-22s %8s %6s  %10s  %9s  %9s %6s"
    out = [
        "GUESTS - the %d busiest on the disks (cgroup of each running"
        " container or VM)" % min(top, len(invites)),
        gabarit
        % (
            "id",
            "type",
            "name",
            "CPU avg",
            "peak",
            "memory",
            "disk MB/s",
            "disk wait",
            "peak",
        ),
    ]
    for g in invites[:top]:
        debit = g["io_bytes_s_avg"]
        out.append(
            gabarit
            % (
                g["vmid"],
                g["kind"],
                (g["name"] or "")[:22],
                fmt(g["cpu_avg"], "{:.0f}%"),
                fmt(g["cpu_max"], "{:.0f}%"),
                go(g["mem_bytes"]),
                fmt(None if debit is None else debit / 1048576.0, "{:.2f}"),
                fmt(g["io_psi_some_avg"], "{:.1f}%"),
                fmt(g["io_psi_some_max"], "{:.0f}%"),
            )
        )
    out.append(
        "  (CPU: 100 % = one full core; disk wait: % of the time the"
        " guest's tasks waited for the disk, the latency felt inside it)"
    )
    out.append("")
    return out


TITRES_SSD = {
    "yes": ("1;31", "YES"),
    "not_yet": ("1;33", "NOT YET"),
    "no": ("1;32", "NO"),
    "not_applicable": ("0", "NOT APPLICABLE"),
}


def _texte_verdict_ssd(r, rendu):
    out = ["VERDICT - what limits the performance"]
    if not r["verdicts"]:
        out.append("  no verdict without samples")
    for cle, libelle in (
        ("cpu", "Processors"),
        ("memory", "RAM"),
        ("disks", "Disks"),
        ("network", "Network"),
    ):
        v = r["verdicts"].get(cle)
        if v:
            out.append(
                "  %-11s %-11s %s"
                % (rendu.etiquette(v["level"]), libelle, v["reason"])
            )
    out.append("")
    s = r["ssd"]
    code, titre = TITRES_SSD[s["answer"]]
    out.append("ARE SSD DISKS JUSTIFIED?")
    out.append("  %s: %s." % (rendu.colorer(code, titre), s["reason"]))
    if s.get("steps"):
        out.append(
            "  Cheaper steps first, in order: " + "; ".join(s["steps"]) + "."
        )
    attentes = [g for g in (r["guests"] or []) if g["io_psi_some_avg"]]
    if attentes:
        g = max(attentes, key=lambda x: x["io_psi_some_avg"])
        out.append(
            "  Guest that waited most for the disk: %s %s (%.1f %% of its"
            " time)." % (g["vmid"], g["name"], g["io_psi_some_avg"])
        )
    out.append("")
    return out


def _texte_conseils(r):
    out = ["SUGGESTED SETTINGS (read-only audit: nothing below was run)"]
    if not r["suggestions"]:
        out.append(
            "  none: nothing to change according to these measurements."
        )
    for i, c in enumerate(r["suggestions"], 1):
        out.append("  %d. [%s] %s" % (i, c["priority"].upper(), c["text"]))
        out.extend("       $ " + commande for commande in c["commands"])
    if r["duration_s"] < MESURE_COURTE_S:
        out.append("")
        out.append(
            "  Short measurement (%s): to see the daily peaks (backups, busy"
            " hours), run it for hours, e.g. --duration 24h."
            % duree_humaine(r["duration_s"])
        )
    return out


def rapport_texte(r, faits, rendu, top=8):
    """Les lignes du rapport texte, depuis le dictionnaire du JSON ; `top`
    borne le tableau des invités. Chaque commande suggérée a sa ligne."""
    return (
        _texte_entete(r, faits)
        + _texte_cpu(r["cpu"], faits)
        + _texte_memoire(
            r["memory"], (r["zfs"] or {}).get("arc"), faits, rendu
        )
        + _texte_disques(r["disks"], r["io_psi"], faits, rendu)
        + _texte_zfs(r["zfs"], rendu)
        + _texte_reseau(r["network"], rendu)
        + _texte_invites(r["guests"], r["guests_skipped"], top)
        + _texte_verdict_ssd(r, rendu)
        + _texte_conseils(r)
    )


# ----------------------------------------------------------------------- #
# Ligne de commande
# ----------------------------------------------------------------------- #
def _type_duree(texte):
    try:
        return duree_valide(texte)
    except ValueError as err:
        raise argparse.ArgumentTypeError(str(err))


def _type_positif(texte):
    try:
        valeur = int(texte)
    except ValueError:
        raise argparse.ArgumentTypeError("expected a whole number: %r" % texte)
    if valeur < 1:
        raise argparse.ArgumentTypeError("expected at least 1: %r" % texte)
    return valeur


def construire_parseur():
    parseur = argparse.ArgumentParser(
        prog="host_perf_audit.py",
        description=(
            "Read-only audit of what limits the performance of a Proxmox VE"
            " host or any Linux server: processor, memory, disks, network,"
            " ZFS and guests, measured over a chosen duration, with a"
            " verdict per resource, the answer to 'are SSD disks"
            " justified?' and the settings to consider, printed as"
            " commands and never run."
        ),
        epilog=(
            "Exit codes: 0 audit completed (also when stopped by Ctrl-C),"
            " 2 could not run, 130 interrupted before measuring. Remote"
            " use: ssh -T HOST python3 -I - --duration 10m <"
            " host_perf_audit.py"
        ),
    )
    parseur.add_argument(
        "--duration",
        type=_type_duree,
        default=60,
        metavar="TIME",
        help="length of the measurement: 90 (seconds), 30s, 10m, 2h, 1h30m;"
        " 1 second to 7 days (default: 60)",
    )
    parseur.add_argument(
        "--interval",
        type=float,
        default=None,
        metavar="SECONDS",
        help="seconds between two samples (default: 5, raised so that at"
        " most %d samples are kept)" % ECHANTILLONS_MAX,
    )
    parseur.add_argument(
        "--csv",
        metavar="FILE",
        help="also write every raw sample to this CSV file",
    )
    parseur.add_argument(
        "--json",
        action="store_true",
        help="print the report as JSON on stdout (messages go to stderr)",
    )
    parseur.add_argument(
        "--no-guests",
        action="store_true",
        help="do not measure each container and VM",
    )
    parseur.add_argument(
        "--top",
        type=_type_positif,
        default=8,
        metavar="N",
        help="number of guests shown in the text report, busiest on the"
        " disks first (default: 8)",
    )
    parseur.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="show each external command run",
    )
    parseur.add_argument("--root", default="", help=argparse.SUPPRESS)
    return parseur


def _silencer_sortie():
    """Après un tube rompu : la sortie standard pointe sur /dev/null, pour
    que la fermeture de l'interpréteur n'écrive plus rien."""
    try:
        nul = os.open(os.devnull, os.O_WRONLY)
        os.dup2(nul, sys.stdout.fileno())
    except (OSError, ValueError, AttributeError):
        pass


def main(
    argv=None, systeme=None, sortie=None, erreur=None, priorite_basse=True
):
    """Code de sortie. `systeme`, `sortie` et `erreur` sont remplacés par
    les tests ; `priorite_basse=False` évite de toucher à la priorité du
    processus qui appelle."""
    sortie = sortie or sys.stdout
    erreur = erreur or sys.stderr
    try:
        return _main(argv, systeme, sortie, erreur, priorite_basse)
    except BrokenPipeError:
        if sortie is sys.stdout:
            _silencer_sortie()
        return 0
    except KeyboardInterrupt:
        # Hors de la boucle de mesure (qui garde ses échantillons), un
        # Ctrl-C arrête tout sans trace.
        print("\nInterrupted (Ctrl-C).", file=erreur)
        return 130


def _collecter_faits(racine, systeme, blocs, notes):
    """(faits, zfs, noms des invités) : tout ce qui se lit une fois."""
    faits = faits_hote(racine, systeme, blocs)
    zfs = faits_zfs(racine, systeme, blocs, notes)
    sante_smart(systeme, faits["disks"])
    noms = {}
    if os.path.isdir(chemin(racine, "/etc/pve")):
        noms = noms_invites(racine)
    return faits, zfs, noms


def _noter(args, racine, faits, notes, systeme):
    """Ajoute les notes de contexte et rend la raison pour laquelle les
    invités ne sont pas mesurés (None s'ils le sont)."""
    for argv_lent, delai in systeme.sans_reponse:
        notes.append(
            "%s did not answer within %d s and was abandoned (suspended"
            " pool or failing disk?): its results are missing"
            % (" ".join(shlex.quote(x) for x in argv_lent), delai)
        )
    if not faits["root"]:
        notes.append(
            "not root: SMART health and some ZFS details are unavailable"
            " (sudo for a complete report)"
        )
    if not faits["pve"]:
        notes.append("not a Proxmox VE host (pveversion not found)")
    if faits["in_container"]:
        notes.append(
            "running inside a container: the disks shown are not the real"
            " ones, run it on the host"
        )
    if analyser_pression(lire(racine, "/proc/pressure/io")) is None:
        notes.append(
            "PSI unavailable (/proc/pressure missing or disabled): the"
            " verdicts rely on the other signals"
        )
    if args.no_guests:
        return "disabled"
    if not os.path.isdir(chemin(racine, "/etc/pve")):
        return "no_pve"
    if not faits["cgroup_v2"]:
        notes.append(
            "guests skipped: the host uses cgroup v1 (or hybrid), the"
            " per-guest counters are read from cgroup v2 only"
        )
        return "cgroup_v1"
    return None


def _noter_fin(args, notes, interrompu, nombre, panne_csv):
    """Les notes que seule la fin de la mesure connaît : CSV en panne,
    Ctrl-C, aucun échantillon."""
    if panne_csv:
        notes.append(
            "CSV file %s incomplete: writing failed (%s); the report still"
            " covers every sample" % (args.csv, panne_csv)
        )
    if interrompu:
        notes.append(
            "measurement interrupted (Ctrl-C) after %d sample(s)" % nombre
        )
    if not nombre:
        notes.append("no sample: nothing measured")


def _mesurer(args, racine, systeme, blocs, contexte, fichier_csv, erreur):
    """(échantillons, interrompu, début mur, panne du CSV ou None) ; le
    CSV est fermé à la fin, quelle qu'elle soit, sans que son erreur
    n'empêche le rapport."""
    faits, zfs, invites_ignores, intervalle, cumul = contexte
    disques_csv = sorted(n for n, i in faits["disks"].items() if i["physical"])
    pools = sorted((zfs or {}).get("pools") or {})
    ecrivain = None
    if fichier_csv is not None:
        ecrivain = EcrivainCsv(fichier_csv, disques_csv, erreur)
    try:
        print(
            "Measuring for %s, one sample every %g s (%d disk(s)%s) - Ctrl-C"
            " stops early and still gives the report."
            % (
                duree_humaine(args.duration),
                intervalle,
                len(disques_csv),
                ", ZFS pool(s): " + ", ".join(pools) if pools else "",
            ),
            file=erreur,
            flush=True,
        )
        ech, interrompu, debut_mur = echantillonner(
            racine,
            systeme,
            blocs,
            args.duration,
            intervalle,
            invites_ignores is None,
            ecrivain,
            erreur,
            cumul,
        )
    finally:
        if ecrivain is not None:
            ecrivain.fermer()
    return ech, interrompu, debut_mur, ecrivain and ecrivain.panne


def _publier(args, resultat, faits, sortie, csv_complet=True):
    """Le rapport sur `sortie` : le JSON seul, ou le texte."""
    if args.json:
        sortie.write(json.dumps(resultat, indent=2) + "\n")
    else:
        couleur = (
            hasattr(sortie, "isatty")
            and sortie.isatty()
            and not os.environ.get("NO_COLOR")
        )
        for ligne in rapport_texte(resultat, faits, Rendu(couleur), args.top):
            sortie.write(ligne + "\n")
        if args.csv and csv_complet:
            sortie.write("\nSamples written to %s.\n" % args.csv)
    sortie.flush()


def _main(argv, systeme, sortie, erreur, priorite_basse):
    parseur = construire_parseur()
    try:
        args = parseur.parse_args(argv)
    except SystemExit as fin:
        return fin.code if isinstance(fin.code, int) else 2
    racine = args.root
    systeme = systeme or Systeme(bavard=args.verbose, erreur=erreur)
    intervalle, note_intervalle = choisir_intervalle(
        args.duration, args.interval
    )
    if analyser_stat(lire(racine, "/proc/stat")) is None:
        print(
            "Cannot run: %s is unreadable or is not a Linux processor"
            " counter file (not Linux /proc?)." % chemin(racine, "/proc/stat"),
            file=erreur,
        )
        return 2
    notes = []
    if note_intervalle:
        notes.append(note_intervalle)
        print("Note: " + note_intervalle, file=erreur)
    fichier_csv = None
    if args.csv:
        try:
            fichier_csv = open(args.csv, "w", encoding="utf-8", newline="")
        except OSError as err:
            print(
                "Cannot write the CSV file %s: %s" % (args.csv, err),
                file=erreur,
            )
            return 2
    blocs = Blocs(racine)
    try:
        if priorite_basse:
            systeme.baisser_priorite()
        debut_cpu = systeme.temps_cpu()
        faits, zfs, noms = _collecter_faits(racine, systeme, blocs, notes)
    except KeyboardInterrupt:
        if fichier_csv is not None:
            fichier_csv.close()
        print(
            "\nInterrupted (Ctrl-C) before the measurement started.",
            file=erreur,
        )
        return 130
    invites_ignores = _noter(args, racine, faits, notes, systeme)
    cumul = CumulVirtuels(blocs)
    echantillons, interrompu, debut_mur, panne_csv = _mesurer(
        args,
        racine,
        systeme,
        blocs,
        (faits, zfs, invites_ignores, intervalle, cumul),
        fichier_csv,
        erreur,
    )
    cout = systeme.temps_cpu() - debut_cpu
    _noter_fin(args, notes, interrompu, len(echantillons), panne_csv)
    try:
        sections = analyser(
            echantillons,
            faits,
            zfs,
            blocs,
            noms,
            racine,
            invites_ignores,
            cumul,
        )
    except KeyboardInterrupt:
        print("\nInterrupted (Ctrl-C) while analysing.", file=erreur)
        return 130
    resultat = {
        "schema": SCHEMA,
        "tool": OUTIL,
        "host": systeme.nom_hote(),
        "started": datetime.datetime.fromtimestamp(debut_mur)
        .astimezone()
        .isoformat(timespec="seconds"),
        "duration_s": round(
            echantillons[-1]["wall"] - debut_mur if echantillons else 0.0, 1
        ),
        "interval_s": intervalle,
        "samples": len(echantillons),
        "interrupted": interrompu,
        "cost_cpu_s": round(cout, 2),
        "notes": notes,
        "facts": faits,
        "guests_skipped": invites_ignores,
    }
    resultat.update(sections)
    _publier(
        args,
        arrondir({cle: resultat[cle] for cle in CLES_JSON}),
        faits,
        sortie,
        not panne_csv,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
