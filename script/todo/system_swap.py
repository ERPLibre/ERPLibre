#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La mémoire d'échange : swap sur disque (fichier ou partition) et zram.

La LECTURE rend des faits : /proc/swaps, /proc/meminfo, /sys/block/zram*,
/proc/cmdline, /proc/self/mountinfo, la configuration de zram-generator ou
de zram-tools. Chaque analyseur prend un texte ou un chemin, et etat() les
assemble en lisant sous une racine, « / » par défaut : un test fabrique
son arborescence et la lui donne.

Ce module ne rend que des codes et des nombres (octets) ; la phrase et la
langue appartiennent au menu.

zram et swap sur disque coexistent : la zram reçoit la priorité
PRIORITE_ZRAM, le disque garde la sienne, plus basse, et le noyau remplit
toujours la plus haute priorité d'abord.
"""

import math
import os
import re
import shutil

from script.todo import system_cpu
from script.todo.system_diagnostic import desechapper, lire, memoire

KIO = 1024
MIO = 1024**2
GIO = 1024**3

# L'espace laissé libre sur le système de fichiers après un agrandissement.
MARGE_DISQUE = GIO

PRIORITE_ZRAM = 100

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


# ── Lecture ─────────────────────────────────────────────────────────────


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


def _libre(racine, point):
    try:
        return shutil.disk_usage(_sous(racine, point)).free
    except OSError:
        return None


def etat(racine="/"):
    """Tout l'état de la mémoire d'échange, lu sous `racine`.

    {memory, swaps, zram, persistence, hibernation, mounts, root_fs,
    root_free, os_id, recommendation, racine}. Chaque swap porte, en plus
    de lire_swaps() : fs (son montage, pour un fichier), free (l'espace
    libre de ce montage) et hibernation (resume= le vise peut-être)."""
    hib = lire_cmdline(lire(_sous(racine, "/proc/cmdline")))
    montages = lire_mountinfo(lire(_sous(racine, "/proc/self/mountinfo")))
    swaps = lire_swaps(lire(_sous(racine, "/proc/swaps")))
    for s in swaps:
        s["fs"] = s["free"] = None
        if s["type"] == "file":
            s["fs"] = montage_de(s["path"], montages)
            if s["fs"]:
                s["free"] = _libre(racine, s["fs"]["mountpoint"])
        s["hibernation"] = vise_hibernation(s, hib)
    os_release = _sous(racine, "/etc/os-release")
    os_id, _ = system_cpu.systeme(os_release)
    racine_fs = montage_de("/", montages)
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
        "os_id": os_id,
        "recommendation": recommandation(
            mem.get("total"), hibernation=bool(hib["resume"])
        ),
        "racine": racine,
    }


def cibles_disque(etat):
    """Les swaps sur disque actifs (fichiers et partitions), sans la
    zram."""
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
