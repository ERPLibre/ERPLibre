#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La mémoire d'échange : swap sur disque (fichier ou partition) et zram.

Deux moitiés.

La LECTURE rend des faits : /proc/swaps, /proc/meminfo, /sys/block/zram*,
/proc/cmdline, /proc/self/mountinfo, la configuration de zram-generator ou
de zram-tools. Chaque analyseur prend un texte ou un chemin, et etat() les
assemble en lisant sous une racine, « / » par défaut : un test fabrique
son arborescence et la lui donne.

Les PLANS rendent des listes d'arguments, jamais exécutées ici. Le menu
les montre, demande confirmation, puis les lance une à une et s'arrête à
la première qui échoue. Un plan est un dict :

    {"ok": bool, "reason": code ou None, "details": {...},
     "plan": [[argv], ...], "warnings": [{"code": ..., ...}],
     "nix": texte ou None}

« nix » porte, sur NixOS, l'extrait de configuration.nix qui remplace
tout changement impératif.

Ce module ne rend que des codes et des nombres (octets) ; la phrase et la
langue appartiennent au menu.

zram et swap sur disque coexistent : la zram reçoit la priorité
PRIORITE_ZRAM, le disque garde la sienne, plus basse, et le noyau remplit
toujours la plus haute priorité d'abord.
"""

import math
import os
import re
import shlex
import shutil
import time

from script.todo import system_cpu
from script.todo.system_diagnostic import commande, desechapper, lire, memoire

KIO = 1024
MIO = 1024**2
GIO = 1024**3
TIO = 1024**4

# Ce que la mémoire disponible doit garder après un swapoff : sous ce
# seuil, le noyau tue des processus plutôt que de rendre la main.
MARGE_MEMOIRE = 512 * MIO
# L'espace laissé libre sur le système de fichiers après un agrandissement.
MARGE_DISQUE = GIO
# Plus petit swap sur disque qu'on accepte de créer ou de réduire.
PLANCHER_SWAP = 256 * MIO
# Une taille au-delà est une faute de frappe.
TAILLE_MAX = 64 * TIO

PRIORITE_ZRAM = 100

CHEMIN_SWAPFILE = "/swapfile"
# Sur btrfs, un fichier d'échange interdit tout instantané du sous-volume
# qui le contient : il vit dans un sous-volume à lui, que les instantanés
# de la racine n'emportent pas.
CHEMIN_SWAPFILE_BTRFS = "/swap/swapfile"

# Les systèmes de fichiers qui acceptent un fichier d'échange.
FS_SWAP = {"ext2", "ext3", "ext4", "xfs", "btrfs", "f2fs", "jfs", "reiserfs"}
# Ceux où un fichier préalloué par fallocate n'a pas de trou aux yeux de
# swapon (xfs depuis Linux 4.18). Ailleurs, dd écrit chaque bloc.
FS_FALLOCATE = {"ext4", "xfs"}
# « btrfs filesystem mkswapfile » paraît avec btrfs-progs 6.1.
BTRFS_MKSWAPFILE = (6, 1)

FSTAB = "/etc/fstab"

# zram-generator : le fichier principal de plus haute priorité masque les
# autres ; puis les fichiers *.conf des répertoires conf.d s'appliquent par
# ordre de nom, un même nom pris dans le répertoire le plus prioritaire.
DOSSIERS_ZRAM_GENERATOR = (
    "/etc/systemd",
    "/run/systemd",
    "/usr/local/lib/systemd",
    "/usr/lib/systemd",
)
ZRAM_GENERATOR_ETC_D = "/etc/systemd/zram-generator.conf.d"
BINAIRES_ZRAM_GENERATOR = (
    "/usr/lib/systemd/system-generators/zram-generator",
    "/lib/systemd/system-generators/zram-generator",
    "/usr/local/lib/systemd/system-generators/zram-generator",
)
# zram-tools, chez Debian et Ubuntu : un service et un fichier de variables.
ZRAMSWAP_DEFAULT = "/etc/default/zramswap"
ZRAMSWAP_BINAIRES = ("/usr/sbin/zramswap", "/sbin/zramswap")
# Les autres services qui montent la zram au démarrage, chacun reconnu à
# ses fichiers : zram-config chez Ubuntu (init-zram-swapping), et
# systemd-zram-service chez openSUSE, dont le service porte le même nom
# que celui de zram-tools mais que seul zramswapon distingue.
SERVICES_ZRAM = (
    (
        "zram-config.service",
        (
            "/usr/bin/init-zram-swapping",
            "/usr/sbin/init-zram-swapping",
            "/usr/lib/systemd/system/zram-config.service",
            "/lib/systemd/system/zram-config.service",
            "/etc/systemd/system/zram-config.service",
        ),
    ),
    ("zramswap.service", ("/usr/sbin/zramswapon", "/usr/bin/zramswapon")),
)

# Les suffixes anglais (K, KB, KiB) et français (Ko, Kio) : le menu écrit
# ses tailles en « Gio », et une taille recopiée de son affichage se relit.
SUFFIXES = {
    "": MIO,
    **{
        lettre + fin: facteur
        for lettre, facteur in (("k", KIO), ("m", MIO), ("g", GIO), ("t", TIO))
        for fin in ("", "b", "i", "ib", "o", "io")
    },
}

# Ce que systemd-detect-virt nomme quand il reconnaît un conteneur. Le swap
# et la zram y appartiennent à l'hôte : swapon et la configuration d'une
# zram exigent des droits que le conteneur n'a pas.
CONTENEURS = {
    "openvz",
    "lxc",
    "lxc-libvirt",
    "systemd-nspawn",
    "docker",
    "podman",
    "rkt",
    "wsl",
    "proot",
    "pouch",
}


# ── Lecture ─────────────────────────────────────────────────────────────


def parse_taille(texte):
    """« 4G », « 512M », « 1.5G », « 8.0 Gio », « 2048 » (Mio) -> octets,
    arrondis au Mio inférieur ; None pour ce qui n'est pas une taille
    positive."""
    if texte is None:
        return None
    m = re.fullmatch(
        r"\s*(\d+(?:[.,]\d+)?)\s*([kmgt](?:ib|io|b|o|i)?)?\s*",
        str(texte).lower(),
    )
    if not m:
        return None
    nombre = float(m.group(1).replace(",", "."))
    unite = SUFFIXES.get(m.group(2) or "")
    if unite is None:
        return None
    octets = int(nombre * unite) // MIO * MIO
    if octets <= 0 or octets > TAILLE_MAX:
        return None
    return octets


def mio(octets):
    """Octets -> Mio entiers, arrondis au plus proche."""
    return (octets + MIO // 2) // MIO


def type_swap(chemin, type_noyau):
    """« zram » pour /dev/zramN, que le noyau dit « partition » ; sinon
    « file » ou « partition », tel que /proc/swaps le donne."""
    if re.fullmatch(r"/dev/zram\d+", chemin):
        return "zram"
    return "file" if type_noyau == "file" else "partition"


def lire_swaps(texte):
    """/proc/swaps -> [{path, type, size, used, priority}], tailles en
    octets. Le chemin est désechappé (« \\040 » -> espace)."""
    swaps = []
    for ligne in (texte or "").splitlines()[1:]:
        champs = ligne.split()
        if len(champs) < 5:
            continue
        try:
            taille = int(champs[-3]) * KIO
            utilise = int(champs[-2]) * KIO
            priorite = int(champs[-1])
        except ValueError:
            continue
        chemin = desechapper(champs[0])
        swaps.append(
            {
                "path": chemin,
                "type": type_swap(chemin, champs[-4]),
                "size": taille,
                "used": utilise,
                "priority": priorite,
            }
        )
    return swaps


def lire_cmdline(texte):
    """/proc/cmdline -> {resume, resume_offset} ; None pour ce qui manque.
    Les deux disent où l'hibernation relit l'image de la mémoire."""
    resume = offset = None
    for mot in (texte or "").split():
        cle, egal, valeur = mot.partition("=")
        if not egal:
            continue
        if cle == "resume" and valeur:
            resume = valeur
        elif cle == "resume_offset":
            try:
                offset = int(valeur)
            except ValueError:
                pass
    return {"resume": resume, "resume_offset": offset}


def lire_mountinfo(texte):
    """/proc/self/mountinfo -> [{mountpoint, fstype, source, root}]. Un
    point monté deux fois garde la dernière ligne, celle qui recouvre."""
    montages = {}
    for ligne in (texte or "").splitlines():
        avant, tiret, apres = ligne.partition(" - ")
        champs = avant.split()
        fin = apres.split()
        if not tiret or len(champs) < 5 or len(fin) < 2:
            continue
        point = desechapper(champs[4])
        montages[point] = {
            "mountpoint": point,
            "fstype": fin[0],
            "source": desechapper(fin[1]),
            "root": desechapper(champs[3]),
        }
    return list(montages.values())


def montage_de(chemin, montages):
    """Le montage qui contient `chemin` (le plus long préfixe), ou None."""
    meilleur = None
    for m in montages:
        point = m["mountpoint"]
        if chemin == point or chemin.startswith(point.rstrip("/") + "/"):
            if meilleur is None or len(point) > len(meilleur["mountpoint"]):
                meilleur = m
    return meilleur


def lire_algorithme(texte):
    """« lzo lzo-rle [zstd] » -> ("zstd", ["lzo", "lzo-rle", "zstd"])."""
    choisi = None
    tous = []
    for mot in (texte or "").split():
        if mot.startswith("[") and mot.endswith("]"):
            mot = mot[1:-1]
            choisi = mot
        tous.append(mot)
    return choisi, tous


def lire_mm_stat(texte):
    """mm_stat d'une zram -> {orig_data, compr_data, mem_used}, en octets,
    ou {} s'il ne se lit pas. La première colonne est ce que la zram tient
    avant compression, la troisième ce qu'elle coûte en RAM."""
    champs = (texte or "").split()
    try:
        orig, compr, utilise = (int(x) for x in champs[:3])
    except ValueError:
        return {}
    return {"orig_data": orig, "compr_data": compr, "mem_used": utilise}


def lire_zram(racine_sys="/sys/block"):
    """[{name, device, disksize, algorithm, algorithms, orig_data,
    compr_data, mem_used, ratio}] pour chaque /sys/block/zramN. disksize
    vaut 0 pour un appareil créé mais pas configuré ; ratio vaut None tant
    que rien n'est compressé."""
    try:
        noms = sorted(
            n for n in os.listdir(racine_sys) if re.fullmatch(r"zram\d+", n)
        )
    except OSError:
        return []
    appareils = []
    for nom in noms:
        dossier = os.path.join(racine_sys, nom)
        try:
            taille = int((lire(os.path.join(dossier, "disksize")) or "0"))
        except ValueError:
            taille = 0
        choisi, tous = lire_algorithme(
            lire(os.path.join(dossier, "comp_algorithm"))
        )
        stats = lire_mm_stat(lire(os.path.join(dossier, "mm_stat")))
        ratio = None
        if stats.get("compr_data"):
            ratio = stats["orig_data"] / stats["compr_data"]
        appareils.append(
            {
                "name": nom,
                "device": f"/dev/{nom}",
                "disksize": taille,
                "algorithm": choisi,
                "algorithms": tous,
                "orig_data": stats.get("orig_data"),
                "compr_data": stats.get("compr_data"),
                "mem_used": stats.get("mem_used"),
                "ratio": ratio,
            }
        )
    return appareils


def lire_ini(texte):
    """Le format de zram-generator -> {section: {clé: valeur}}. Les
    commentaires (# ou ;) et les lignes hors section sont ignorés."""
    sections = {}
    courante = None
    for ligne in (texte or "").splitlines():
        ligne = ligne.strip()
        if not ligne or ligne[0] in "#;":
            continue
        m = re.fullmatch(r"\[([^\]]+)\]", ligne)
        if m:
            courante = sections.setdefault(m.group(1).strip(), {})
            continue
        cle, egal, valeur = ligne.partition("=")
        if egal and courante is not None:
            courante[cle.strip()] = valeur.strip()
    return sections


def _sous(racine, chemin):
    """`chemin` absolu, lu sous `racine`."""
    return os.path.join(racine, chemin.lstrip("/"))


def config_zram_generator(racine="/"):
    """La configuration effective de zram-generator.

    Rend {main, dropins, sections, etc_dropins, usr_dropins} : main est le
    fichier principal retenu (le premier trouvé de /etc à /usr/lib), None
    s'il n'y en a pas ; dropins la liste des conf.d appliqués dans
    l'ordre ; sections le résultat de leur fusion. etc_dropins sont ceux
    que l'administrateur a posés dans /etc, usr_dropins ceux qu'un paquet
    livre ailleurs et qu'un fichier vide du même nom dans /etc masque."""
    principal = None
    for dossier in DOSSIERS_ZRAM_GENERATOR:
        chemin = f"{dossier}/zram-generator.conf"
        if os.path.isfile(_sous(racine, chemin)):
            principal = chemin
            break
    par_nom = {}
    for dossier in reversed(DOSSIERS_ZRAM_GENERATOR):
        conf_d = f"{dossier}/zram-generator.conf.d"
        try:
            noms = os.listdir(_sous(racine, conf_d))
        except OSError:
            continue
        for nom in noms:
            if nom.endswith(".conf"):
                par_nom[nom] = f"{conf_d}/{nom}"
    dropins = [par_nom[n] for n in sorted(par_nom)]
    sections = {}
    for chemin in ([principal] if principal else []) + dropins:
        for nom, cles in lire_ini(lire(_sous(racine, chemin))).items():
            sections.setdefault(nom, {}).update(cles)
    return {
        "main": principal,
        "dropins": dropins,
        "sections": sections,
        "etc_dropins": [
            d for d in dropins if d.startswith(ZRAM_GENERATOR_ETC_D + "/")
        ],
        "usr_dropins": [
            d for d in dropins if not d.startswith(ZRAM_GENERATOR_ETC_D + "/")
        ],
    }


def lire_variables(texte):
    """Un fichier de variables shell (/etc/default/zramswap) -> {CLÉ:
    valeur} des lignes actives, guillemets ôtés."""
    valeurs = {}
    for ligne in (texte or "").splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#"):
            continue
        cle, egal, valeur = ligne.partition("=")
        if egal and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", cle.strip()):
            valeurs[cle.strip()] = valeur.strip().strip("\"'")
    return valeurs


def persistance_zram(racine="/", os_id=None):
    """Comment la zram revient au démarrage.

    mode vaut « nixos » (configuration.nix décide), « zram-generator »
    (installé et une section [zramN] le configure), « zram-tools » (son
    fichier ou son programme est présent), « service » (un autre service de
    SERVICES_ZRAM, que service nomme), ou None. Les deux outils installés
    ensemble se disputent /dev/zram0 : both le signale."""
    generateur = any(
        os.path.exists(_sous(racine, b)) for b in BINAIRES_ZRAM_GENERATOR
    )
    config = config_zram_generator(racine)
    sections_zram = sorted(
        s for s in config["sections"] if re.fullmatch(r"zram\d+", s)
    )
    texte_tools = lire(_sous(racine, ZRAMSWAP_DEFAULT))
    tools = texte_tools is not None or any(
        os.path.exists(_sous(racine, b)) for b in ZRAMSWAP_BINAIRES
    )
    service = next(
        (
            nom
            for nom, fichiers in SERVICES_ZRAM
            if any(os.path.exists(_sous(racine, f)) for f in fichiers)
        ),
        None,
    )
    if os_id == "nixos":
        mode = "nixos"
    elif generateur and sections_zram:
        mode = "zram-generator"
    elif tools:
        mode = "zram-tools"
    elif service:
        mode = "service"
    else:
        mode = None
    return {
        "mode": mode,
        "service": service if mode == "service" else None,
        "generator_installed": generateur,
        "generator": config,
        "generator_devices": sections_zram,
        "zram_tools_installed": tools,
        "zram_tools": lire_variables(texte_tools) if tools else None,
        "both": generateur and bool(sections_zram) and tools,
    }


def vise_hibernation(swap, hibernation):
    """Vrai si resume= peut désigner ce swap. Sans blkid, un UUID ou un
    LABEL ne se résout pas : une partition est alors présumée visée. Un
    fichier l'est quand resume_offset est donné."""
    resume = hibernation.get("resume")
    if not resume or swap["type"] == "zram":
        return False
    if swap["type"] == "file":
        return hibernation.get("resume_offset") is not None
    if resume.startswith("/dev/") and not resume.startswith("/dev/disk/"):
        return resume == swap["path"]
    return True


def recommandation(ram, hibernation=False):
    """{swap, zram, basis} en octets, arrondis au Mio.

    Sans hibernation, le swap vaut la RAM, au moins 2×RAM jusqu'à 4 Gio et
    au plus 8 Gio : courbe continue qui suit les tables usuelles des
    distributions. Avec, il doit recevoir toute la RAM : RAM + √RAM
    (en Gio). La zram vaut la moitié de la RAM, au plus 8 Gio."""
    if not ram:
        return {"swap": None, "zram": None, "basis": None}
    if hibernation:
        swap = ram + math.ceil(math.sqrt(ram / GIO)) * GIO
        base = "hibernation"
    else:
        swap = min(max(ram, min(2 * ram, 4 * GIO)), 8 * GIO)
        base = "ram"
    zram = min(ram // 2, 8 * GIO)
    return {
        "swap": swap // MIO * MIO,
        "zram": zram // MIO * MIO,
        "basis": base,
    }


def version_btrfs(texte):
    """« btrfs-progs v6.6.3 » -> (6, 6) ; None sinon."""
    m = re.search(r"v(\d+)\.(\d+)", texte or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def _libre(racine, point):
    try:
        return shutil.disk_usage(_sous(racine, point)).free
    except OSError:
        return None


def etat(racine="/"):
    """Tout l'état de la mémoire d'échange, lu sous `racine`.

    {memory, swaps, zram, persistence, hibernation, mounts, root_fs,
    root_free, fstab, manager, os_id, btrfs_mkswapfile,
    virtualization, container, recommendation, racine}. container est vrai
    quand systemd-detect-virt nomme un conteneur. Chaque swap porte, en plus
    de lire_swaps() : fs (son montage, pour un fichier), free (l'espace
    libre de ce montage), max_size (la taille que l'espace libre permet,
    marge déduite) et hibernation (resume= le vise peut-être)."""
    hib = lire_cmdline(lire(_sous(racine, "/proc/cmdline")))
    montages = lire_mountinfo(lire(_sous(racine, "/proc/self/mountinfo")))
    swaps = lire_swaps(lire(_sous(racine, "/proc/swaps")))
    for s in swaps:
        s["fs"] = s["free"] = s["max_size"] = None
        if s["type"] == "file":
            s["fs"] = montage_de(s["path"], montages)
            if s["fs"]:
                s["free"] = _libre(racine, s["fs"]["mountpoint"])
            if s["free"] is not None:
                s["max_size"] = max(
                    s["size"], s["size"] + s["free"] - MARGE_DISQUE
                )
        s["hibernation"] = vise_hibernation(s, hib)
    os_release = _sous(racine, "/etc/os-release")
    os_id, _ = system_cpu.systeme(os_release)
    racine_fs = montage_de("/", montages)
    mkswapfile = False
    if shutil.which("btrfs"):
        version = version_btrfs(commande(["btrfs", "--version"]))
        mkswapfile = bool(version and version >= BTRFS_MKSWAPFILE)
    virt = (commande(["systemd-detect-virt"], codes_ok=(0, 1)) or "").strip()
    virt = None if virt in ("", "none") else virt
    mem = memoire(_sous(racine, "/proc/meminfo"))
    actives = {s["path"] for s in swaps}
    zram = lire_zram(_sous(racine, "/sys/block"))
    for z in zram:
        z["active"] = z["device"] in actives
    return {
        "memory": mem,
        "swaps": swaps,
        "zram": zram,
        "persistence": persistance_zram(racine, os_id),
        "hibernation": hib,
        "mounts": montages,
        "root_fs": racine_fs,
        "root_free": _libre(racine, racine_fs["mountpoint"])
        if racine_fs
        else None,
        "fstab": lire(_sous(racine, FSTAB)),
        "manager": system_cpu.gestionnaire(os_release),
        "os_id": os_id,
        "btrfs_mkswapfile": mkswapfile,
        "virtualization": virt,
        "container": virt in CONTENEURS,
        "recommendation": recommandation(
            mem.get("total"), hibernation=bool(hib["resume"])
        ),
        "racine": racine,
    }


def cibles_disque(etat):
    """Les swaps sur disque actifs (fichiers et partitions), ceux qu'on
    agrandit ou réduit, sans la zram."""
    return [s for s in etat["swaps"] if s["type"] != "zram"]


def croissance_swap(etat):
    """Les octets que l'espace libre permet d'ajouter au swap : sur le
    système de fichiers du plus grand fichier d'échange actif, ou de la
    racine s'il n'y en a pas ; marge déduite, jamais négatif. None si
    l'espace libre ne se lit pas."""
    fichiers = [s for s in etat["swaps"] if s["type"] == "file"]
    if fichiers:
        libre = max(fichiers, key=lambda s: s["size"]).get("free")
    else:
        libre = etat.get("root_free")
    if libre is None:
        return None
    return max(0, libre - MARGE_DISQUE) // MIO * MIO


def chemin_par_defaut(etat):
    """{path, reason} du fichier d'échange à créer : reason vaut
    « btrfs_subvolume » quand la racine est en btrfs."""
    racine_fs = etat.get("root_fs") or {}
    if racine_fs.get("fstype") == "btrfs":
        return {"path": CHEMIN_SWAPFILE_BTRFS, "reason": "btrfs_subvolume"}
    return {"path": CHEMIN_SWAPFILE, "reason": None}


# ── Plans ───────────────────────────────────────────────────────────────


def _resultat(ok, reason=None, plan=None, warnings=None, **d):
    return {
        "ok": ok,
        "reason": reason,
        "details": d,
        "plan": plan or [],
        "warnings": warnings or [],
        "nix": None,
    }


def _refus(reason, **details):
    return _resultat(False, reason, **details)


def _horodatage(valeur):
    return valeur or time.strftime("%Y%m%d-%H%M%S")


def _capacite(etat, sauf=()):
    """Ce que le système absorbe quand un swap s'éteint : la mémoire
    disponible moins la marge, plus la place libre des AUTRES swaps sur
    disque. La place libre d'une zram ne compte pas : la remplir coûte de
    la RAM."""
    dispo = etat["memory"].get("available") or 0
    autres = sum(
        s["size"] - s["used"]
        for s in etat["swaps"]
        if s["type"] != "zram" and s["path"] not in sauf
    )
    return {
        "available": dispo,
        "margin": MARGE_MEMOIRE,
        "other_swap_free": autres,
        "capacity": dispo - MARGE_MEMOIRE + autres,
    }


def refus_conteneur(etat):
    """Le refus « container » quand etat vient d'un conteneur, sinon None :
    swapon, swapoff et la zram y échouent faute de droits sur l'hôte."""
    if etat.get("container"):
        return _refus("container", virtualization=etat.get("virtualization"))
    return None


def _existe(etat, chemin):
    return os.path.lexists(_sous(etat.get("racine", "/"), chemin))


# Sur btrfs, le répertoire racine de chaque sous-volume porte cet inode.
INODE_SOUS_VOLUME = 256


def _est_racine_sous_volume(chemin_reel):
    """Vrai si `chemin_reel` (déjà sous la racine) est la racine d'un
    sous-volume btrfs ; faux s'il ne se lit pas."""
    try:
        return os.stat(chemin_reel).st_ino == INODE_SOUS_VOLUME
    except OSError:
        return False


def sous_volume_de(etat, chemin, point):
    """Le sous-volume btrfs qui contient le répertoire existant `chemin` :
    le premier ancêtre, `chemin` compris, qui en est une racine, en
    remontant jusqu'au point de montage `point`, rendu s'il n'y en a
    aucun."""
    racine = etat.get("racine", "/")
    courant = chemin
    while courant != point and courant != "/":
        if _est_racine_sous_volume(_sous(racine, courant)):
            return courant
        courant = os.path.dirname(courant)
    return point


def _vide(etat, chemin):
    """Vrai si le répertoire `chemin` est lisible et vide."""
    try:
        return not os.listdir(_sous(etat.get("racine", "/"), chemin))
    except OSError:
        return False


def _creation(chemin, taille, fstype, mkswapfile):
    """Les commandes qui créent un fichier d'échange formaté, absent au
    départ, sans l'activer.

    btrfs : « btrfs filesystem mkswapfile » pose NOCOW et formate ; sans
    lui, chattr +C sur le fichier encore vide, puis fallocate. ext4 et
    xfs : fallocate. Ailleurs dd, qui écrit chaque bloc et ne laisse pas
    de trou que swapon refuserait."""
    n = taille // MIO
    if fstype == "btrfs" and mkswapfile:
        return [
            [
                "sudo",
                "btrfs",
                "filesystem",
                "mkswapfile",
                "--size",
                f"{n}m",
                chemin,
            ],
            ["sudo", "chmod", "600", chemin],
        ]
    if fstype == "btrfs":
        cree = [
            ["sudo", "truncate", "-s", "0", chemin],
            ["sudo", "chattr", "+C", chemin],
            ["sudo", "fallocate", "-l", f"{n}MiB", chemin],
        ]
    elif fstype in FS_FALLOCATE:
        cree = [["sudo", "fallocate", "-l", f"{n}MiB", chemin]]
    else:
        cree = [
            [
                "sudo",
                "dd",
                "if=/dev/zero",
                f"of={chemin}",
                "bs=1M",
                f"count={n}",
                "status=progress",
            ]
        ]
    return cree + [
        ["sudo", "chmod", "600", chemin],
        ["sudo", "mkswap", chemin],
    ]


def echapper_fstab(chemin):
    """Un chemin tel que fstab l'écrit : espace, tabulation, saut de ligne
    et barre oblique inverse en octal."""
    return "".join(f"\\{ord(c):03o}" if c in " \t\n\\" else c for c in chemin)


def dans_fstab(texte, chemin):
    """Vrai si une ligne active de fstab monte déjà `chemin`."""
    for ligne in (texte or "").splitlines():
        champs = ligne.split()
        if champs and not champs[0].startswith("#"):
            if desechapper(champs[0]) == chemin:
                return True
    return False


def extrait_nix(swap):
    """L'extrait de configuration.nix. swap : (chemin, octets) d'un
    swapDevices."""
    chemin, taille = swap
    lignes = [
        f'swapDevices = [ {{ device = "{chemin}";'
        f" size = {taille // MIO}; }} ];",
        "# sudo nixos-rebuild switch",
    ]
    return "\n".join(lignes) + "\n"


def _nix(resultat, texte):
    resultat["nix"] = texte
    resultat["reason"] = "nixos"
    return resultat


def plan_redimensionner(etat, chemin, taille, sens=None):
    """Agrandir ou réduire le fichier d'échange actif `chemin` à `taille`
    octets : swapoff, rm, recréation, chmod 600, mkswap, swapon.

    sens vaut « grow », « shrink » ou None (l'un ou l'autre). Refus
    (reason) : container, not_active, zram, partition (details.suggestion :
    le fichier à créer à la place), partition_shrink (réduire une
    partition), below_floor, not_larger, not_smaller, same_size,
    fs_unsupported, ram_cannot_absorb, disk_unknown, disk_full. warnings :
    hibernation (resume= le vise : l'offset change avec le fichier).
    details : path, old, new, recovery_from, et les chiffres du refus.

    recovery_from est l'indice de l'étape rm : une fois le swapoff passé,
    une étape qui échoue laisse le swap éteint et son fichier absent ou
    incomplet, et plan[recovery_from:] le reconstruit depuis zéro."""
    conteneur = refus_conteneur(etat)
    if conteneur:
        return conteneur
    swap = next((s for s in etat["swaps"] if s["path"] == chemin), None)
    if swap is None:
        return _refus("not_active", path=chemin)
    if swap["type"] == "zram":
        return _refus("zram", path=chemin)
    if swap["type"] != "file" and sens == "shrink":
        return _refus("partition_shrink", path=chemin)
    if swap["type"] != "file":
        return _refus(
            "partition",
            path=chemin,
            suggestion=chemin_par_defaut(etat)["path"],
        )
    taille = taille // MIO * MIO
    ancienne = swap["size"]
    if taille < PLANCHER_SWAP:
        return _refus("below_floor", floor=PLANCHER_SWAP, new=taille)
    if mio(taille) == mio(ancienne):
        return _refus("same_size", old=ancienne, new=taille)
    if sens == "grow" and taille < ancienne:
        return _refus("not_larger", old=ancienne, new=taille)
    if sens == "shrink" and taille > ancienne:
        return _refus("not_smaller", old=ancienne, new=taille)
    fs = swap.get("fs")
    if not fs or fs["fstype"] not in FS_SWAP:
        return _refus("fs_unsupported", fstype=fs and fs["fstype"])
    if etat.get("manager") == "nix":
        return _nix(
            _resultat(True, old=ancienne, new=taille),
            extrait_nix(swap=(chemin, taille)),
        )
    cap = _capacite(etat, sauf=(chemin,))
    if swap["used"] > cap["capacity"]:
        return _refus("ram_cannot_absorb", used=swap["used"], **cap)
    if taille > ancienne:
        libre = swap.get("free")
        if libre is None:
            return _refus("disk_unknown", mountpoint=fs["mountpoint"])
        besoin = taille - ancienne + MARGE_DISQUE
        if besoin > libre:
            return _refus(
                "disk_full",
                needed=besoin,
                free=libre,
                max_size=swap.get("max_size"),
            )
    swapon = ["sudo", "swapon"]
    if swap["priority"] >= 0:
        swapon += ["-p", str(swap["priority"])]
    plan = (
        [["sudo", "swapoff", chemin], ["sudo", "rm", "-f", chemin]]
        + _creation(chemin, taille, fs["fstype"], etat.get("btrfs_mkswapfile"))
        + [swapon + [chemin]]
    )
    alertes = []
    if swap.get("hibernation"):
        alertes.append(
            {"code": "hibernation", "resume": etat["hibernation"]["resume"]}
        )
    return _resultat(
        True,
        plan=plan,
        warnings=alertes,
        path=chemin,
        old=ancienne,
        new=taille,
        recovery_from=1,
    )


def plan_creer(etat, chemin, taille, horodatage=None):
    """Créer et activer un fichier d'échange de `taille` octets, et
    l'inscrire dans /etc/fstab (copie de sauvegarde d'abord) s'il n'y est
    pas déjà.

    Refus : container, invalid_path, already_active, exists,
    below_floor, fs_unsupported, disk_unknown, disk_full, parent_missing.
    Sur btrfs, un répertoire parent absent devient un sous-volume (btrfs
    subvolume create). warnings : btrfs_snapshot (le fichier rejoint un
    sous-volume qui porte autre chose que lui : il en bloque les
    instantanés ; seul un répertoire parent qui est lui-même la racine
    d'un sous-volume vide y échappe). details : new, fstab (« added » ou « present »), backup.
    Sur NixOS, plan vide et nix donne swapDevices.

    La première étape, « sudo test ! -e », refuse un fichier qui existe :
    lexists, lancé sans droits, voit absent ce qui dort dans un répertoire
    qu'on ne peut pas traverser, et dd ou mkswap l'écraseraient.

    La ligne de fstab s'ajoute après un saut de ligne quand le fichier
    n'en finit pas par un : collée à la dernière ligne, elle la rendrait
    illisible au démarrage, montage compris."""
    conteneur = refus_conteneur(etat)
    if conteneur:
        return conteneur
    if (
        not chemin.startswith("/")
        or ".." in chemin.split("/")
        or chemin.endswith("/")
        or "\x00" in chemin
    ):
        return _refus("invalid_path", path=chemin)
    if any(s["path"] == chemin for s in etat["swaps"]):
        return _refus("already_active", path=chemin)
    taille = taille // MIO * MIO
    if taille < PLANCHER_SWAP:
        return _refus("below_floor", floor=PLANCHER_SWAP, new=taille)
    if etat.get("manager") == "nix":
        return _nix(
            _resultat(True, new=taille), extrait_nix(swap=(chemin, taille))
        )
    if _existe(etat, chemin):
        return _refus("exists", path=chemin)
    fs = montage_de(chemin, etat.get("mounts") or [])
    if not fs or fs["fstype"] not in FS_SWAP:
        return _refus("fs_unsupported", fstype=fs and fs["fstype"])
    libre = _libre(etat.get("racine", "/"), fs["mountpoint"])
    if libre is None:
        return _refus("disk_unknown", mountpoint=fs["mountpoint"])
    if taille + MARGE_DISQUE > libre:
        return _refus(
            "disk_full",
            needed=taille + MARGE_DISQUE,
            free=libre,
            max_size=max(0, (libre - MARGE_DISQUE) // MIO * MIO),
        )
    plan = [["sudo", "test", "!", "-e", chemin]]
    alertes = []
    parent = os.path.dirname(chemin)
    if not _existe(etat, parent):
        if fs["fstype"] != "btrfs" or not _existe(
            etat, os.path.dirname(parent)
        ):
            return _refus("parent_missing", parent=parent)
        plan.append(["sudo", "btrfs", "subvolume", "create", parent])
    elif fs["fstype"] == "btrfs":
        sous_volume = sous_volume_de(etat, parent, fs["mountpoint"])
        if sous_volume != parent or not _vide(etat, parent):
            alertes.append(
                {"code": "btrfs_snapshot", "subvolume": sous_volume}
            )
    plan += _creation(
        chemin, taille, fs["fstype"], etat.get("btrfs_mkswapfile")
    )
    plan.append(["sudo", "swapon", chemin])
    details = {"new": taille, "fstab": "present", "backup": None}
    if not dans_fstab(etat.get("fstab"), chemin):
        copie = f"{FSTAB}.bak-{_horodatage(horodatage)}"
        ligne = f"{echapper_fstab(chemin)} none swap defaults 0 0"
        plan += [
            ["sudo", "cp", "-a", FSTAB, copie],
            [
                "sudo",
                "sh",
                "-c",
                f'[ -z "$(tail -c 1 {FSTAB})" ] || echo >> {FSTAB}; '
                f"printf '%s\\n' {shlex.quote(ligne)} >> {FSTAB}",
            ],
        ]
        details.update(fstab="added", backup=copie, line=ligne)
    return _resultat(True, plan=plan, warnings=alertes, **details)
