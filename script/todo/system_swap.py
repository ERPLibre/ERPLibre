#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La mémoire d'échange : swap sur disque (fichier ou partition) et zram.

Deux moitiés.

La LECTURE rend des faits : /proc/swaps, /proc/meminfo, /sys/block/zram*,
/proc/cmdline, /proc/self/mountinfo, la configuration de zram-generator ou
de zram-tools, la sortie de dmidecode. Chaque analyseur prend un texte ou
un chemin, et etat() les assemble en lisant sous une racine, « / » par
défaut : un test fabrique son arborescence et la lui donne.

Les PLANS rendent des listes d'arguments, jamais exécutées ici. Le menu
les montre, demande confirmation, puis les lance une à une et s'arrête à
la première qui échoue. Un plan est un dict :

    {"ok": bool, "reason": code ou None, "details": {...},
     "plan": [[argv], ...], "files": {fichier temporaire: contenu},
     "warnings": [{"code": ..., ...}], "nix": texte ou None}

« files » est à écrire par le menu AVANT le plan : un fichier de root se
remplace par « sudo install » depuis un fichier temporaire de
l'utilisateur, montré avant d'être lancé. « nix » porte, sur NixOS,
l'extrait de configuration.nix qui remplace tout changement impératif.

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
# Plus petite zram ; au-delà de deux fois la RAM, une zram pleine coûte
# plus de mémoire qu'elle n'en libère, même bien compressée.
PLANCHER_ZRAM = 64 * MIO
FACTEUR_MAX_ZRAM = 2
# Une taille au-delà est une faute de frappe.
TAILLE_MAX = 64 * TIO

PRIORITE_ZRAM = 100
ALGORITHME_ZRAM = "zstd"

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
# Où vivent les modules du noyau, dans l'ordre de recherche : /lib/modules
# est souvent un lien vers /usr/lib/modules, qui sert de repli.
DOSSIERS_MODULES = ("/lib/modules", "/usr/lib/modules")
ZRAM_GENERATOR_ETC = "/etc/systemd/zram-generator.conf"
ZRAM_GENERATOR_ETC_D = "/etc/systemd/zram-generator.conf.d"
BINAIRES_ZRAM_GENERATOR = (
    "/usr/lib/systemd/system-generators/zram-generator",
    "/lib/systemd/system-generators/zram-generator",
    "/usr/local/lib/systemd/system-generators/zram-generator",
)
PAQUETS_ZRAM_GENERATOR = {
    "pacman": "zram-generator",
    "dnf": "zram-generator",
    "apt": "systemd-zram-generator",
    "zypper": "zram-generator",
}
# zram-tools, chez Debian et Ubuntu : un service et un fichier de variables.
ZRAMSWAP_DEFAULT = "/etc/default/zramswap"
ZRAMSWAP_BINAIRES = ("/usr/sbin/zramswap", "/sbin/zramswap")
ZRAMSWAP_SERVICE = "zramswap.service"
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

# dmidecode vit dans un sbin, hors du PATH d'un compte ordinaire chez
# Debian : shutil.which() seul le dirait absent.
BINAIRES_DMIDECODE = (
    "/usr/sbin/dmidecode",
    "/sbin/dmidecode",
    "/usr/bin/dmidecode",
)

# Facteur de forme d'une mémoire soudée à la carte : pas de module à
# ajouter ni à remplacer.
FORMES_SOUDEES = {"row of chips", "chip"}

# Le pilote de ballon virtio de l'invité : présent, l'hôte peut changer la
# RAM d'une VM allumée, jusqu'au maximum de sa définition.
CHEMINS_BALLON = (
    "/sys/bus/virtio/drivers/virtio_balloon",
    "/sys/module/virtio_balloon",
)

# Les hyperviseurs, tels que systemd-detect-virt les nomme, dont l'invité
# reçoit un ballon virtio. Ailleurs le ballon a un autre pilote (VMware,
# Hyper-V) ou n'existe pas (conteneur) : ni sa présence ni son absence ne
# disent alors quoi que ce soit.
HYPERVISEURS_VIRTIO = {"kvm", "qemu"}

# sysctl.d : les répertoires par ordre de priorité. Un fichier masque celui
# du même nom dans un répertoire plus bas ; les survivants s'appliquent par
# ordre de nom, quel que soit leur répertoire, et la dernière affectation
# d'une clé l'emporte. systemd-sysctl lit les quatre premiers au démarrage
# (et /lib/sysctl.d sur un système à /usr séparé) ; « sysctl --system » de
# procps lit les cinq, puis /etc/sysctl.conf en dernier.
DOSSIERS_SYSCTL = (
    "/etc/sysctl.d",
    "/run/sysctl.d",
    "/usr/local/lib/sysctl.d",
    "/usr/lib/sysctl.d",
    "/lib/sysctl.d",
)
SYSCTL_D_ETC = "/etc/sysctl.d"
# systemd-sysctl ne lit pas /etc/sysctl.conf : plusieurs distributions le
# relient en /etc/sysctl.d/99-sysctl.conf pour qu'il s'applique au
# démarrage. Sans systemd-sysctl, procps l'applique en dernier.
SYSCTL_CONF = "/etc/sysctl.conf"
BINAIRES_SYSTEMD_SYSCTL = (
    "/usr/lib/systemd/systemd-sysctl",
    "/lib/systemd/systemd-sysctl",
)
SWAPPINESS = "vm.swappiness"
PAGE_CLUSTER = "vm.page-cluster"
CLES_SYSCTL = (SWAPPINESS, PAGE_CLUSTER)
# Le fichier créé quand aucun fichier de /etc ne porte déjà la clé : « 99- »
# le classe après ceux des paquets, « zz- » après les autres « 99- ».
NOM_SYSCTL = "99-zz-swap.conf"
# La valeur par défaut du noyau. Sous elle, le noyau préfère jeter le cache
# de pages plutôt que de swapper, et une zram reste presque vide.
SWAPPINESS_DEFAUT = 60
# Avec une zram, swapper coûte une compression en RAM, moins que de relire
# depuis le disque le cache de pages évincé : 100 pèse les deux à égalité.
SWAPPINESS_ZRAM = 100
# Swap sur disque et PostgreSQL : ses processus restent en RAM, le swap ne
# sert qu'en dernier recours.
SWAPPINESS_POSTGRESQL = 10
# Une zram lit une page seule plus vite qu'une grappe : pas de lecture
# anticipée (2^0 = 1 page).
PAGE_CLUSTER_ZRAM = 0
# vm.swappiness accepte 0 à 200 depuis Linux 5.8, 0 à 100 avant.
SWAPPINESS_MAX = 200
SWAPPINESS_MAX_ANCIEN = 100
NOYAU_SWAPPINESS_200 = (5, 8)
PAGE_CLUSTER_MAX = 31
# Le nom de processus (/proc/<pid>/comm) du serveur PostgreSQL et de ses
# processus fils ; « postmaster » chez les versions anciennes.
COMMS_POSTGRESQL = {"postgres", "postmaster"}

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


def noyau_en_marche(racine="/"):
    """La version du noyau en marche (/proc/sys/kernel/osrelease) ; sous
    la vraie racine, os.uname() la donne quand /proc ne se lit pas."""
    running = (lire(_sous(racine, "/proc/sys/kernel/osrelease")) or "").strip()
    if not running and racine == "/":
        running = os.uname().release
    return running


def module_zram(racine="/"):
    """{state, running, installed} : si le noyau en marche peut porter une
    zram, avant qu'un plan ne l'attende.

    running est la version du noyau en marche (/proc/sys/kernel/osrelease),
    installed les versions qui ont un dossier de modules. state vaut :
    loaded (/sys/class/zram-control ou /sys/module/zram existe), builtin
    (zram dans modules.builtin), available (zram.ko* dans les modules du
    noyau en marche, que modprobe charge), reboot (le noyau en marche n'a
    plus de dossier de modules mais d'autres versions en ont : le paquet
    du noyau a été mis à jour sur disque, et aucun module ne se charge
    avant un redémarrage), missing (le noyau en marche n'a pas de zram),
    unknown (aucun dossier de modules lisible, NixOS par exemple).

    Sans ce contrôle, zram-generator écrit dev-zram0.swap même quand le
    module ne se charge pas, et systemd attend /dev/zram0 jusqu'à son délai
    de 90 secondes avant d'annoncer une dépendance en échec."""
    running = noyau_en_marche(racine)
    resultat = {"state": "unknown", "running": running, "installed": []}
    for chemin in ("/sys/class/zram-control", "/sys/module/zram"):
        if os.path.exists(_sous(racine, chemin)):
            resultat["state"] = "loaded"
            return resultat
    for base in DOSSIERS_MODULES:
        dossier = _sous(racine, base)
        try:
            versions = sorted(os.listdir(dossier))
        except OSError:
            continue
        resultat["installed"] = [v for v in versions if v != running]
        if not running or running not in versions:
            if resultat["installed"]:
                resultat["state"] = "reboot"
            continue
        noyau = os.path.join(dossier, running)
        builtin = lire(os.path.join(noyau, "modules.builtin")) or ""
        dep = lire(os.path.join(noyau, "modules.dep")) or ""
        if re.search(r"/zram\.ko\b", builtin):
            resultat["state"] = "builtin"
        elif re.search(r"/zram\.ko(\.\w+)?:", dep) or os.path.isdir(
            os.path.join(noyau, "kernel", "drivers", "block", "zram")
        ):
            resultat["state"] = "available"
        else:
            resultat["state"] = "missing"
        return resultat
    return resultat


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


def version_noyau(release):
    """« 6.12.4-arch1-1 » -> (6, 12) ; None sinon."""
    m = re.match(r"\s*(\d+)\.(\d+)", release or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def swappiness_max(release):
    """La plus grande vm.swappiness que le noyau `release` accepte. Un
    noyau inconnu reçoit la borne des anciens : 0 à 100 vaut partout."""
    version = version_noyau(release)
    if version and version >= NOYAU_SWAPPINESS_200:
        return SWAPPINESS_MAX
    return SWAPPINESS_MAX_ANCIEN


def chemin_sysctl(cle):
    """Le nom d'une clé de sysctl sous sa forme de chemin sous /proc/sys :
    « vm.swappiness » et « vm/swappiness » -> « vm/swappiness ». Si le
    premier séparateur est « / », les points suivants font partie d'un nom
    et restent ; si c'est « . », points et barres s'échangent."""
    cle = cle.strip()
    m = re.search(r"[./]", cle)
    if not m or m.group() == "/":
        return cle
    return cle.translate(str.maketrans("./", "/."))


def lire_sysctl_conf(texte):
    """Un fichier de sysctl.d -> {chemin sous /proc/sys: valeur}, la
    dernière affectation d'une clé l'emportant. Les lignes vides, # et ;
    sont ignorées ; le « - » de tête (un échec toléré) ne change pas la
    clé ; une ligne sans « = » (l'exclusion d'un glob) n'affecte rien."""
    valeurs = {}
    for ligne in (texte or "").splitlines():
        ligne = ligne.strip()
        if not ligne or ligne[0] in "#;":
            continue
        cle, egal, valeur = ligne.partition("=")
        if not egal:
            continue
        cle = cle.strip()
        if cle.startswith("-"):
            cle = cle[1:]
        valeurs[chemin_sysctl(cle)] = valeur.strip()
    return valeurs


def _cible_lien(racine, chemin, sauts=8):
    """Le chemin, absolu sous `racine`, que le lien symbolique `chemin`
    désigne au bout de sa chaîne ; `chemin` lui-même s'il n'est pas un
    lien. Une cible absolue se résout sous `racine`, pas sur la machine
    qui exécute."""
    for _ in range(sauts):
        try:
            cible = os.readlink(_sous(racine, chemin))
        except OSError:
            return chemin
        chemin = os.path.normpath(os.path.join(os.path.dirname(chemin), cible))
    return chemin


def lire_sysctl(racine="/"):
    """vm.swappiness et vm.page-cluster : leur valeur et qui les fixe au
    démarrage.

    Rend {SWAPPINESS: {...}, PAGE_CLUSTER: {...}, systemd, names}. names
    liste les noms de tous les fichiers de sysctl.d, systemd dit si
    systemd-sysctl est installé. Pour chaque clé : value (l'entier lu dans
    /proc/sys, None s'il ne se lit pas) ; setters, les fichiers qui
    l'affectent dans l'ordre où ils s'appliquent, chacun {path, link, name,
    value} : path le fichier réel, link l'entrée de sysctl.d qui y mène par
    un lien (None sinon), name le nom qui le classe (None pour
    /etc/sysctl.conf lu en dernier) ; source et source_value, le dernier
    setter, qui l'emporte (None : la valeur du noyau) ; dead, les setters
    qu'il écrase ; outside_boot, {path, value} quand /etc/sysctl.conf
    affecte la clé sans être relié dans sysctl.d alors que systemd-sysctl
    est là : seul « sysctl --system » l'applique, pas le démarrage.

    /etc/sysctl.d/99-sysctl.conf, lien vers ../sysctl.conf, compte une
    fois, à la place de son nom."""
    systemd = any(
        os.path.exists(_sous(racine, b)) for b in BINAIRES_SYSTEMD_SYSCTL
    )
    par_nom = {}
    for dossier in DOSSIERS_SYSCTL:
        try:
            noms = os.listdir(_sous(racine, dossier))
        except OSError:
            continue
        for nom in noms:
            if nom.endswith(".conf") and not nom.startswith("."):
                par_nom.setdefault(nom, f"{dossier}/{nom}")
    fichiers = []
    for nom in sorted(par_nom):
        entree = par_nom[nom]
        reel = _cible_lien(racine, entree)
        fichiers.append((nom, entree, reel))
    relie = any(reel == SYSCTL_CONF for _, _, reel in fichiers)
    conf_a_part = not relie and os.path.isfile(_sous(racine, SYSCTL_CONF))
    if conf_a_part and not systemd:
        fichiers.append((None, SYSCTL_CONF, SYSCTL_CONF))
    lus = {}
    for _, _, reel in fichiers:
        if reel not in lus:
            lus[reel] = lire_sysctl_conf(lire(_sous(racine, reel)))
    conf = (
        lire_sysctl_conf(lire(_sous(racine, SYSCTL_CONF)))
        if conf_a_part and systemd
        else {}
    )
    resultat = {"systemd": systemd, "names": sorted(par_nom)}
    for cle in CLES_SYSCTL:
        proc = chemin_sysctl(cle)
        try:
            valeur = int(
                (lire(_sous(racine, f"/proc/sys/{proc}")) or "").strip()
            )
        except ValueError:
            valeur = None
        setters = [
            {
                "path": reel,
                "link": entree if entree != reel else None,
                "name": nom,
                "value": lus[reel][proc],
            }
            for nom, entree, reel in fichiers
            if proc in lus[reel]
        ]
        dernier = setters[-1] if setters else None
        resultat[cle] = {
            "value": valeur,
            "setters": setters,
            "source": dernier and dernier["path"],
            "source_value": dernier and dernier["value"],
            "dead": setters[:-1],
            "outside_boot": (
                {"path": SYSCTL_CONF, "value": conf[proc]}
                if proc in conf
                else None
            ),
        }
    return resultat


def postgresql_actif(racine="/"):
    """Vrai si un processus PostgreSQL tourne : un /proc/<pid>/comm vaut
    un nom de COMMS_POSTGRESQL."""
    dossier = _sous(racine, "/proc")
    try:
        noms = os.listdir(dossier)
    except OSError:
        return False
    for nom in noms:
        if nom.isdigit():
            comm = (lire(os.path.join(dossier, nom, "comm")) or "").strip()
            if comm in COMMS_POSTGRESQL:
                return True
    return False


def ballon_virtio(racine="/"):
    """Vrai si le pilote virtio_balloon de l'invité est chargé ou intégré
    au noyau."""
    return any(os.path.exists(_sous(racine, c)) for c in CHEMINS_BALLON)


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

    {memory, swaps, zram, zram_module, persistence, hibernation, mounts,
    root_fs, root_free, fstab, manager, os_id, btrfs_mkswapfile,
    virtualization, container, recommendation, sysctl, kernel, postgresql,
    balloon, racine}. container est vrai quand systemd-detect-virt nomme un
    conteneur ; sysctl vient de lire_sysctl(), kernel est la version du
    noyau en marche, postgresql dit si PostgreSQL tourne, balloon si le
    pilote virtio_balloon est là. Chaque swap porte, en plus
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
    module = module_zram(racine)
    return {
        "memory": mem,
        "swaps": swaps,
        "zram": zram,
        "zram_module": module,
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
        "sysctl": lire_sysctl(racine),
        "kernel": module["running"],
        "postgresql": postgresql_actif(racine),
        "balloon": ballon_virtio(racine),
        "racine": racine,
    }


def swaps_fstab(texte):
    """Les sources (premier champ, déséchappé) des lignes actives de fstab
    dont le type est « swap » : le swap configuré au démarrage, actif ou
    non."""
    sources = []
    for ligne in (texte or "").splitlines():
        champs = ligne.split()
        if len(champs) >= 3 and not champs[0].startswith("#"):
            if champs[2] == "swap":
                sources.append(desechapper(champs[0]))
    return sources


def cibles_disque(etat):
    """Les swaps sur disque actifs (fichiers et partitions), ceux qu'on
    agrandit ou réduit ; la zram a ses propres plans."""
    return [s for s in etat["swaps"] if s["type"] != "zram"]


def chemin_par_defaut(etat):
    """{path, reason} du fichier d'échange à créer : reason vaut
    « btrfs_subvolume » quand la racine est en btrfs."""
    racine_fs = etat.get("root_fs") or {}
    if racine_fs.get("fstype") == "btrfs":
        return {"path": CHEMIN_SWAPFILE_BTRFS, "reason": "btrfs_subvolume"}
    return {"path": CHEMIN_SWAPFILE, "reason": None}


# ── Plans ───────────────────────────────────────────────────────────────


def _resultat(ok, reason=None, plan=None, warnings=None, files=None, **d):
    return {
        "ok": ok,
        "reason": reason,
        "details": d,
        "plan": plan or [],
        "files": files or {},
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


def extrait_nix(zram_pourcent=None, swap=None, zram=True):
    """L'extrait de configuration.nix. zram_pourcent : la zram en
    pourcentage de la RAM ; swap : (chemin, octets) d'un swapDevices ;
    zram=False écrit zramSwap.enable = false."""
    lignes = []
    if not zram:
        lignes.append("zramSwap.enable = false;")
    elif zram_pourcent is not None:
        lignes += [
            "zramSwap.enable = true;",
            f'zramSwap.algorithm = "{ALGORITHME_ZRAM}";',
            f"zramSwap.memoryPercent = {zram_pourcent};",
            f"zramSwap.priority = {PRIORITE_ZRAM};",
        ]
    if swap:
        chemin, taille = swap
        lignes.append(
            f'swapDevices = [ {{ device = "{chemin}";'
            f" size = {taille // MIO}; }} ];"
        )
    lignes.append("# sudo nixos-rebuild switch")
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


def _remplacer_cles(lignes, debut, fin, valeurs):
    """Dans lignes[debut:fin], remplace la ligne active de chaque clé de
    `valeurs` ; ajoute après la dernière ligne non vide celles qui
    manquent. Rend la nouvelle liste."""
    vues = set()
    section = lignes[debut:fin]
    for i, ligne in enumerate(section):
        cle = ligne.partition("=")[0].strip()
        actif = ligne.lstrip()[:1] not in ("#", ";")
        if "=" in ligne and cle in valeurs and actif:
            section[i] = f"{cle} = {valeurs[cle]}"
            vues.add(cle)
    manque = [f"{c} = {v}" for c, v in valeurs.items() if c not in vues]
    dernier = len(section)
    while dernier and not section[dernier - 1].strip():
        dernier -= 1
    section[dernier:dernier] = manque
    return lignes[:debut] + section + lignes[fin:]


def contenu_zram_generator(
    texte, taille, algorithme=ALGORITHME_ZRAM, priorite=PRIORITE_ZRAM
):
    """`texte` (le zram-generator.conf de départ, ou "") dont la section
    [zram0] fixe zram-size (en Mio), compression-algorithm et
    swap-priority. Les commentaires et les autres sections restent."""
    valeurs = {
        "zram-size": str(taille // MIO),
        "compression-algorithm": algorithme,
        "swap-priority": str(priorite),
    }
    lignes = (texte or "").splitlines()
    debut = next(
        (i for i, lg in enumerate(lignes) if lg.strip() == "[zram0]"), None
    )
    if debut is None:
        while lignes and not lignes[-1].strip():
            lignes.pop()
        if lignes:
            lignes.append("")
        lignes.append("[zram0]")
        lignes += [f"{c} = {v}" for c, v in valeurs.items()]
        return "\n".join(lignes) + "\n"
    fin = next(
        (
            i
            for i in range(debut + 1, len(lignes))
            if lignes[i].strip().startswith("[")
        ),
        len(lignes),
    )
    return "\n".join(_remplacer_cles(lignes, debut + 1, fin, valeurs)) + "\n"


def contenu_zramswap(
    texte, taille, algorithme=ALGORITHME_ZRAM, priorite=PRIORITE_ZRAM
):
    """/etc/default/zramswap avec SIZE (Mio), ALGO et PRIORITY fixés.
    PERCENT l'emporte sur SIZE dans zramswap : sa ligne active passe en
    commentaire."""
    valeurs = {
        "ALGO": algorithme,
        "SIZE": str(taille // MIO),
        "PRIORITY": str(priorite),
    }
    sortie = []
    vues = set()
    for ligne in (texte or "").splitlines():
        cle = ligne.partition("=")[0].strip()
        if "=" in ligne and not ligne.lstrip().startswith("#"):
            if cle == "PERCENT":
                sortie.append("#" + ligne)
                continue
            if cle in valeurs:
                sortie.append(f"{cle}={valeurs[cle]}")
                vues.add(cle)
                continue
        sortie.append(ligne)
    sortie += [f"{c}={v}" for c, v in valeurs.items() if c not in vues]
    return "\n".join(sortie) + "\n"


def _installer_fichier(etat, dossier_tmp, nom_tmp, dest, contenu, stamp):
    """(plan, files) qui remplacent le fichier de root `dest` par
    `contenu` : une copie de sauvegarde s'il existe, puis « sudo install »
    depuis un fichier temporaire de l'utilisateur."""
    tmp = os.path.join(dossier_tmp, nom_tmp)
    plan = []
    if _existe(etat, dest):
        plan.append(["sudo", "cp", "-a", dest, f"{dest}.bak-{stamp}"])
    plan.append(["sudo", "install", "-D", "-m", "0644", tmp, dest])
    return plan, {tmp: contenu}


def _plan_paquet(etat, paquets):
    """Les commandes qui installent le paquet de `paquets` (gestionnaire
    -> nom) avec le gestionnaire de etat, ou None."""
    cle = etat.get("manager")
    paquet = paquets.get(cle)
    if not paquet:
        return None
    install = {c: cmd for c, _, cmd in system_cpu.GESTIONNAIRES}[cle]
    plan = [list(c) for c in system_cpu.AVANT.get(cle, [])]
    plan.append(install + [paquet])
    return plan


def refus_zram(etat):
    """Le refus qui précède toute question sur la taille d'une zram, sinon
    None : container ; zram_reboot_required quand le noyau en marche a
    perdu ses modules au profit d'une version plus récente, et
    zram_unavailable quand il n'a pas de zram (voir module_zram) ; ou
    zram_service quand un autre service de SERVICES_ZRAM la tient et que
    zram-generator s'y ajouterait."""
    conteneur = refus_conteneur(etat)
    if conteneur:
        return conteneur
    module = etat.get("zram_module") or {}
    if module.get("state") == "reboot":
        return _refus(
            "zram_reboot_required",
            running=module["running"],
            installed=", ".join(module["installed"]),
        )
    if module.get("state") == "missing":
        return _refus("zram_unavailable", running=module["running"])
    pers = etat["persistence"]
    if pers.get("mode") == "service":
        return _refus("zram_service", service=pers.get("service"))
    return None


def _zram_actives(etat):
    return [s for s in etat["swaps"] if s["type"] == "zram"]


def plan_zram(etat, taille, dossier_tmp, horodatage=None):
    """Activer la zram, ou la redimensionner, à `taille` octets.

    Outil retenu : zram-generator s'il configure déjà la zram ou s'il est
    installé seul ; zram-tools s'il est seul présent ; sinon zram-generator,
    installé d'abord. details.tool le dit, details.install vaut True quand
    le plan installe le paquet. Refus : container, below_floor,
    zram_too_large, zram_service (un autre service de SERVICES_ZRAM tient
    la zram), ram_cannot_absorb (la zram active se vide en RAM au
    redémarrage du service), no_package_manager, et ceux de refus_zram.
    Quand le module zram est disponible sans être chargé, « modprobe zram »
    précède le daemon-reload. warnings : zram_over_ram
    (plus grande que la RAM), dropin_overrides (un conf.d redéfinit ce
    qu'on écrit ; paths), zram_tools_conflict (les deux outils visent
    /dev/zram0), disk_priority (un swap sur disque a une priorité ≥ celle
    de la zram ; paths), low_swappiness (vm.swappiness sous
    SWAPPINESS_DEFAUT : le noyau se sert à peine de la zram ; value). Sur
    NixOS, plan vide et nix donne zramSwap.

    Avec zram-generator, une zram active que rien ne rend persistante est
    éteinte et remise à zéro d'abord : le générateur n'écrit pas la taille
    d'un appareil occupé. Le redémarrage de systemd-zram-setup@zram0
    n'atteint dev-zram0.swap que si ce swap tourne déjà ; « systemctl
    start dev-zram0.swap » l'active la première fois et ne change rien
    ensuite."""
    refus = refus_zram(etat)
    if refus:
        return refus
    ram = etat["memory"].get("total") or 0
    taille = taille // MIO * MIO
    if taille < PLANCHER_ZRAM:
        return _refus("below_floor", floor=PLANCHER_ZRAM, new=taille)
    if ram and taille > FACTEUR_MAX_ZRAM * ram:
        return _refus("zram_too_large", new=taille, max=FACTEUR_MAX_ZRAM * ram)
    alertes = []
    if ram and taille > ram:
        alertes.append({"code": "zram_over_ram", "ram": ram})
    prioritaires = [
        s["path"]
        for s in cibles_disque(etat)
        if s["priority"] >= PRIORITE_ZRAM
    ]
    if prioritaires:
        alertes.append({"code": "disk_priority", "paths": prioritaires})
    swappiness = swappiness_actuelle(etat)
    if swappiness is not None and swappiness < SWAPPINESS_DEFAUT:
        alertes.append({"code": "low_swappiness", "value": swappiness})
    pers = etat["persistence"]
    if pers["mode"] == "nixos" or etat.get("manager") == "nix":
        pourcent = max(1, round(taille * 100 / ram)) if ram else 50
        res = _resultat(True, warnings=alertes, new=taille, tool="nixos")
        return _nix(res, extrait_nix(zram_pourcent=pourcent))
    utilise = sum(s["used"] for s in _zram_actives(etat))
    cap = _capacite(etat)
    if utilise > cap["capacity"]:
        return _refus("ram_cannot_absorb", used=utilise, **cap)
    stamp = _horodatage(horodatage)
    racine = etat.get("racine", "/")
    if pers["mode"] == "zram-tools" or (
        pers["mode"] is None
        and pers["zram_tools_installed"]
        and not pers["generator_installed"]
    ):
        texte = lire(_sous(racine, ZRAMSWAP_DEFAULT)) or ""
        plan, files = _installer_fichier(
            etat,
            dossier_tmp,
            "zramswap",
            ZRAMSWAP_DEFAULT,
            contenu_zramswap(texte, taille),
            stamp,
        )
        plan += [
            ["sudo", "systemctl", "enable", ZRAMSWAP_SERVICE],
            ["sudo", "systemctl", "restart", ZRAMSWAP_SERVICE],
        ]
        return _resultat(
            True,
            plan=plan,
            files=files,
            warnings=alertes,
            new=taille,
            tool="zram-tools",
            install=False,
        )
    plan = []
    installer = not pers["generator_installed"]
    if installer:
        paquet = _plan_paquet(etat, PAQUETS_ZRAM_GENERATOR)
        if paquet is None:
            return _refus("no_package_manager", manager=etat.get("manager"))
        plan += paquet
    if pers["zram_tools_installed"]:
        alertes.append({"code": "zram_tools_conflict"})
    config = pers["generator"]
    # Écrire dans /etc masque le fichier principal livré ailleurs (les
    # valeurs par défaut de Fedora) : on part de son contenu.
    base = lire(_sous(racine, config["main"])) if config["main"] else ""
    cles = {"zram-size", "compression-algorithm", "swap-priority"}
    ecrases = [
        d
        for d in config["dropins"]
        if cles & set(lire_ini(lire(_sous(racine, d))).get("zram0", {}))
    ]
    if ecrases:
        alertes.append({"code": "dropin_overrides", "paths": ecrases})
    etapes, files = _installer_fichier(
        etat,
        dossier_tmp,
        "zram-generator.conf",
        ZRAM_GENERATOR_ETC,
        contenu_zram_generator(base or "", taille),
        stamp,
    )
    # Chargé avant le daemon-reload, le module donne au générateur
    # /sys/class/zram-control, et son échec arrête le plan en une seconde
    # au lieu des 90 secondes où systemd attend /dev/zram0.
    if (etat.get("zram_module") or {}).get("state") == "available":
        etapes.append(["sudo", "modprobe", "zram"])
    plan += etapes + [["sudo", "systemctl", "daemon-reload"]]
    if pers["mode"] != "zram-generator":
        for s in _zram_actives(etat):
            plan += [
                ["sudo", "swapoff", s["path"]],
                ["sudo", "zramctl", "--reset", s["path"]],
            ]
    plan += [
        ["sudo", "systemctl", "restart", "systemd-zram-setup@zram0.service"],
        ["sudo", "systemctl", "start", "dev-zram0.swap"],
    ]
    return _resultat(
        True,
        plan=plan,
        files=files,
        warnings=alertes,
        new=taille,
        tool="zram-generator",
        install=installer,
    )


def plan_zram_desactiver(etat, dossier_tmp, horodatage=None):
    """Désactiver la zram, maintenant et au démarrage.

    zram-generator : l'arrêt de dev-zramN.swap et de
    systemd-zram-setup@zramN d'abord, tant que le générateur produit encore
    le swap qui dépend du service ; puis un /etc/systemd/zram-generator.conf
    sans section [zramN] (il n'en crée alors aucune), un fichier vide dans
    /etc pour masquer chaque conf.d livré ailleurs, et daemon-reload. Dans
    l'ordre inverse, le swap rechargé sans sa dépendance reste actif, et
    la remise à zéro de l'appareil occupé échoue. zram-tools et les autres
    services : « systemctl disable --now ». zram montée à la main :
    swapoff puis zramctl --reset. details.tool le dit. Refus : container,
    no_zram, ram_cannot_absorb. warnings : dropin_etc (un conf.d de /etc la
    configure encore ; paths)."""
    conteneur = refus_conteneur(etat)
    if conteneur:
        return conteneur
    actives = _zram_actives(etat)
    pers = etat["persistence"]
    if pers["mode"] == "nixos" or etat.get("manager") == "nix":
        res = _resultat(True, tool="nixos")
        return _nix(res, extrait_nix(zram=False))
    if not actives and pers["mode"] is None:
        return _refus("no_zram")
    utilise = sum(s["used"] for s in actives)
    cap = _capacite(etat)
    if utilise > cap["capacity"]:
        return _refus("ram_cannot_absorb", used=utilise, **cap)
    stamp = _horodatage(horodatage)
    racine = etat.get("racine", "/")
    if pers["mode"] == "zram-generator":
        actifs = {z["path"].rsplit("/", 1)[-1] for z in actives}
        noms = sorted(actifs | set(pers["generator_devices"]))
        plan = [
            ["sudo", "systemctl", "stop"]
            + ([f"dev-{n}.swap"] if n in actifs else [])
            + [f"systemd-zram-setup@{n}.service"]
            for n in noms
        ]
        contenu = (
            "# zram disabled: without a [zramN] section, zram-generator"
            " creates no device.\n"
        )
        etapes, files = _installer_fichier(
            etat,
            dossier_tmp,
            "zram-generator.conf",
            ZRAM_GENERATOR_ETC,
            contenu,
            stamp,
        )
        plan += etapes
        for d in pers["generator"]["usr_dropins"]:
            nom = os.path.basename(d)
            etapes, f = _installer_fichier(
                etat,
                dossier_tmp,
                f"dropin-{nom}",
                f"{ZRAM_GENERATOR_ETC_D}/{nom}",
                "",
                stamp,
            )
            plan += etapes
            files.update(f)
        alertes = []
        encore = [
            d
            for d in pers["generator"]["etc_dropins"]
            if any(
                re.fullmatch(r"zram\d+", s)
                for s in lire_ini(lire(_sous(racine, d)))
            )
        ]
        if encore:
            alertes.append({"code": "dropin_etc", "paths": encore})
        plan.append(["sudo", "systemctl", "daemon-reload"])
        return _resultat(
            True,
            plan=plan,
            files=files,
            warnings=alertes,
            tool="zram-generator",
        )
    if pers["mode"] in ("zram-tools", "service"):
        service = pers.get("service") or ZRAMSWAP_SERVICE
        return _resultat(
            True,
            plan=[["sudo", "systemctl", "disable", "--now", service]],
            tool=pers["mode"],
            service=service,
        )
    plan = []
    for s in actives:
        plan += [
            ["sudo", "swapoff", s["path"]],
            ["sudo", "zramctl", "--reset", s["path"]],
        ]
    return _resultat(True, plan=plan, tool="manual")


# ── Swappiness ──────────────────────────────────────────────────────────


def swappiness_actuelle(etat):
    """La vm.swappiness lue dans /proc/sys, ou None."""
    return ((etat.get("sysctl") or {}).get(SWAPPINESS) or {}).get("value")


def zram_presente(etat):
    """Vrai si une zram sert de swap, ou si zram-generator, zram-tools ou
    un autre service de SERVICES_ZRAM la monte au démarrage."""
    if _zram_actives(etat):
        return True
    mode = (etat.get("persistence") or {}).get("mode")
    return mode in ("zram-generator", "zram-tools", "service")


def recommandation_swappiness(etat):
    """{swappiness, page_cluster, reason} : la valeur conseillée et le code
    de sa raison.

    reason vaut « zram » (une zram active ou configurée : SWAPPINESS_ZRAM,
    et page_cluster PAGE_CLUSTER_ZRAM), « no_swap » (aucun swap actif ni
    inscrit dans fstab : la swappiness n'a pas d'effet, et la valeur rendue
    est celle du noyau),
    « postgresql » (swap sur disque seulement et PostgreSQL tourne :
    SWAPPINESS_POSTGRESQL) ou « default » (SWAPPINESS_DEFAUT). page_cluster
    vaut None hors zram : rien à changer."""
    if zram_presente(etat):
        return {
            "swappiness": SWAPPINESS_ZRAM,
            "page_cluster": PAGE_CLUSTER_ZRAM,
            "reason": "zram",
        }
    if not cibles_disque(etat) and not swaps_fstab(etat.get("fstab")):
        reason, valeur = "no_swap", SWAPPINESS_DEFAUT
    elif etat.get("postgresql"):
        reason, valeur = "postgresql", SWAPPINESS_POSTGRESQL
    else:
        reason, valeur = "default", SWAPPINESS_DEFAUT
    return {"swappiness": valeur, "page_cluster": None, "reason": reason}


def nom_fichier_sysctl(noms, existants=()):
    """Le nom du fichier à créer dans /etc/sysctl.d : il se classe après
    chaque nom de `noms` (les fichiers qui affectent déjà la clé) et
    n'existe dans aucun répertoire de sysctl.d (`existants`), qu'il
    masquerait.

    NOM_SYSCTL d'abord ; sinon le plus grand nom en jeu, « .conf » ôté,
    suivi de « _zz-swap.conf » : « _ » se classe après « . », donc
    « 99-x_zz-swap.conf » après « 99-x.conf ». Chaque tour rend un nom plus
    grand que le précédent : la boucle s'arrête."""
    nom = NOM_SYSCTL
    dernier = max(noms, default="")
    while nom <= dernier or nom in existants:
        base = max(nom, dernier)
        nom = base[: -len(".conf")] + "_zz-swap.conf"
    return nom


def _modifiable(chemin):
    """Vrai pour un fichier que l'administrateur tient : /etc/sysctl.conf
    ou un fichier de /etc/sysctl.d. Ceux de /run, /usr/lib et /lib
    appartiennent à systemd ou aux paquets, qui les réécrivent."""
    return chemin == SYSCTL_CONF or chemin.startswith(SYSCTL_D_ETC + "/")


def expression_sed(cle, valeur):
    """L'expression de « sed -E » qui remplace la valeur de `cle` sur
    chaque ligne active qui l'affecte, sous la forme pointée ou en chemin,
    avec ou sans « - » de tête ; les espaces autour du « = » restent."""
    nom = cle.split(".", 1)[1]
    return (
        rf"s/^([[:space:]]*-?[[:space:]]*vm[./]{nom}"
        rf"[[:space:]]*=[[:space:]]*).*$/\1{valeur}/"
    )


def extrait_nix_sysctl(valeurs):
    """L'extrait de configuration.nix qui fixe chaque clé de `valeurs`."""
    lignes = [f'boot.kernel.sysctl."{c}" = {v};' for c, v in valeurs.items()]
    lignes.append("# sudo nixos-rebuild switch")
    return "\n".join(lignes) + "\n"


def plan_swappiness(etat, valeur, page_cluster=None, horodatage=None):
    """Fixer vm.swappiness à `valeur`, et vm.page-cluster à `page_cluster`
    s'il est donné : maintenant, puis au démarrage.

    « sudo sysctl -w » change la valeur en marche. Pour chaque clé, le
    fichier qui l'emporte (source de lire_sysctl) est modifié sur place
    s'il est dans /etc (une copie de sauvegarde d'abord, puis sed -i) ;
    sinon la clé va dans un nouveau fichier de /etc/sysctl.d dont le nom
    se classe après chaque fichier qui l'affecte (nom_fichier_sysctl),
    écrit par « sudo tee ». Un fichier de /run, /usr/lib ou /lib n'est
    jamais modifié. /etc/sysctl.conf, que « sysctl --system » applique en
    dernier, est aussi modifié sur place quand il affecte la clé : le
    démarrage et « sysctl --system » donnent alors la même valeur.

    Refus : container, swappiness_range (hors de 0 à 200, ou à 100 sous
    Linux 5.8 ; la version vient de etat["kernel"], lue et ajoutée à etat
    si elle manque), page_cluster_range. warnings : sysctl_dead (des
    fichiers affectent encore la clé mais sont écrasés ; key, paths).
    details : changes ({clé: [avant, après]}), edited ([{path, backup}]),
    created et content (le nouveau fichier, ou None). Sur NixOS, plan vide
    et nix donne boot.kernel.sysctl."""
    conteneur = refus_conteneur(etat)
    if conteneur:
        return conteneur
    if "kernel" not in etat:
        etat["kernel"] = noyau_en_marche(etat.get("racine", "/"))
    limite = swappiness_max(etat["kernel"])
    if (
        isinstance(valeur, bool)
        or not isinstance(valeur, int)
        or not 0 <= valeur <= limite
    ):
        return _refus(
            "swappiness_range",
            value=valeur,
            limit=limite,
            running=etat["kernel"] or None,
        )
    if page_cluster is not None and (
        isinstance(page_cluster, bool)
        or not isinstance(page_cluster, int)
        or not 0 <= page_cluster <= PAGE_CLUSTER_MAX
    ):
        return _refus(
            "page_cluster_range", value=page_cluster, limit=PAGE_CLUSTER_MAX
        )
    voulues = {SWAPPINESS: valeur}
    if page_cluster is not None:
        voulues[PAGE_CLUSTER] = page_cluster
    sysctl = etat.get("sysctl") or {}
    changes = {
        c: [(sysctl.get(c) or {}).get("value"), v] for c, v in voulues.items()
    }
    if etat.get("manager") == "nix":
        return _nix(
            _resultat(True, changes=changes), extrait_nix_sysctl(voulues)
        )
    plan = [
        ["sudo", "sysctl", "-w"] + [f"{c}={v}" for c, v in voulues.items()]
    ]
    editions = {}
    nouvelles = {}
    apres = []
    for cle, v in voulues.items():
        info = sysctl.get(cle) or {}
        setters = info.get("setters") or []
        if setters and _modifiable(setters[-1]["path"]):
            editions.setdefault(setters[-1]["path"], {})[cle] = v
        else:
            nouvelles[cle] = v
            apres += [s["name"] for s in setters if s["name"]]
        if info.get("outside_boot") or any(
            s["path"] == SYSCTL_CONF for s in setters
        ):
            editions.setdefault(SYSCTL_CONF, {})[cle] = v
    stamp = _horodatage(horodatage)
    edites = []
    for chemin, cles in editions.items():
        copie = f"{chemin}.bak-{stamp}"
        sed = ["sudo", "sed", "-i", "-E"]
        for cle, v in cles.items():
            sed += ["-e", expression_sed(cle, v)]
        plan += [["sudo", "cp", "-a", chemin, copie], sed + [chemin]]
        edites.append({"path": chemin, "backup": copie})
    cree = contenu = None
    if nouvelles:
        nom = nom_fichier_sysctl(apres, sysctl.get("names") or ())
        cree = f"{SYSCTL_D_ETC}/{nom}"
        contenu = "".join(f"{c} = {v}\n" for c, v in nouvelles.items())
        plan.append(
            [
                "sudo",
                "sh",
                "-c",
                f"mkdir -p {SYSCTL_D_ETC} && printf %s {shlex.quote(contenu)}"
                f" | tee {shlex.quote(cree)} > /dev/null",
            ]
        )
    alertes = []
    for cle in voulues:
        morts = [
            f"{s['path']} ({s['value']})"
            for s in (sysctl.get(cle) or {}).get("setters") or []
            if cle not in editions.get(s["path"], {})
        ]
        if morts:
            alertes.append({"code": "sysctl_dead", "key": cle, "paths": morts})
    return _resultat(
        True,
        plan=plan,
        warnings=alertes,
        changes=changes,
        edited=edites,
        created=cree,
        content=contenu,
    )


# ── Ajout de mémoire vive ───────────────────────────────────────────────


def taille_dmi(texte):
    """« 16 GB », « 8192 MB », « 2 TB » -> octets ; None pour « No Module
    Installed », « Unknown », « Not Provided » ou 0. dmidecode écrit GB et
    MB pour des puissances de 1024."""
    m = re.fullmatch(r"\s*(\d+)\s*(kB|KB|MB|GB|TB)\s*", texte or "")
    if not m:
        return None
    facteur = {"KB": KIO, "MB": MIO, "GB": GIO, "TB": TIO}[m.group(2).upper()]
    return int(m.group(1)) * facteur or None


def analyser_dmidecode(texte):
    """Sortie de « dmidecode -t memory » -> {arrays, devices}.

    arrays : [{handle, use, max_capacity, slots}] des Physical Memory
    Array ; devices : [{array, size, empty, locator, bank, form_factor,
    type, speed}] des Memory Device. Les matrices qui ne servent pas de
    mémoire système (vidéo, flash) et leurs modules sont écartés."""
    blocs = []
    courant = None
    for ligne in (texte or "").splitlines():
        m = re.match(r"Handle (0x[0-9A-Fa-f]+), DMI type (\d+)", ligne)
        if m:
            courant = {"handle": m.group(1), "dmi": int(m.group(2))}
            blocs.append(courant)
            continue
        if courant is None:
            continue
        if ligne and not ligne[0].isspace() and "titre" not in courant:
            courant["titre"] = ligne.strip()
            continue
        cle, deux, valeur = ligne.strip().partition(":")
        if deux and ligne.startswith("\t") and not ligne.startswith("\t\t"):
            courant[cle.strip()] = valeur.strip()
    matrices = []
    for b in blocs:
        if b.get("titre") != "Physical Memory Array":
            continue
        if b.get("Use", "System Memory") != "System Memory":
            continue
        try:
            slots = int(b.get("Number Of Devices", ""))
        except ValueError:
            slots = None
        matrices.append(
            {
                "handle": b["handle"],
                "use": b.get("Use"),
                "max_capacity": taille_dmi(b.get("Maximum Capacity")),
                "slots": slots,
            }
        )
    systeme = {m["handle"] for m in matrices}
    modules = []
    for b in blocs:
        if b.get("titre") != "Memory Device":
            continue
        matrice = b.get("Array Handle")
        if matrices and matrice not in systeme:
            continue
        taille = taille_dmi(b.get("Size"))
        modules.append(
            {
                "array": matrice,
                "size": taille,
                "empty": taille is None,
                "locator": b.get("Locator"),
                "bank": b.get("Bank Locator"),
                "form_factor": b.get("Form Factor"),
                "type": b.get("Type"),
                "speed": b.get("Speed"),
            }
        )
    return {"arrays": matrices, "devices": modules}


def verdict_memoire(etat, dmi=None):
    """Peut-on ajouter de la RAM ?

    verdict : « vm » (l'hyperviseur la fixe : l'augmenter depuis l'hôte),
    « container » (l'hôte fixe la limite de mémoire du conteneur),
    « unknown » (pas de dmidecode lisible), « free_slots » (des
    emplacements vides), « replace » (emplacements pleins, la capacité
    maximale dépasse l'installé : remplacer des modules), « max » (au
    maximum), « soldered » (mémoire soudée, aucun emplacement).

    Rend aussi installed, max_capacity, slots, used_slots, free_slots,
    max_addable (octets ajoutables, None si inconnu), form_factors, types,
    partially_soldered, max_understated (l'installé dépasse le maximum que
    le micrologiciel annonce, donc ce maximum est faux), firmware_note
    (max_capacity vient du micrologiciel et peut être sous-estimé),
    swap_growth (ce que l'espace disque libre permet d'ajouter au swap),
    virtualization et balloon : dans une VM de HYPERVISEURS_VIRTIO, vrai
    si le pilote virtio_balloon de l'invité est là (l'hôte peut alors
    changer sa RAM pendant qu'elle tourne), faux sinon ; None ailleurs,
    conteneur et autres hyperviseurs compris."""
    ram = etat["memory"].get("total")
    res = {
        "verdict": "unknown",
        "ram": ram,
        "installed": None,
        "max_capacity": None,
        "slots": None,
        "used_slots": None,
        "free_slots": None,
        "max_addable": None,
        "form_factors": [],
        "types": [],
        "partially_soldered": False,
        "max_understated": False,
        "firmware_note": False,
        "swap_growth": croissance_swap(etat),
        "virtualization": etat.get("virtualization"),
        "balloon": None,
    }
    virt = etat.get("virtualization")
    if virt:
        res["verdict"] = "container" if etat.get("container") else "vm"
        if virt in HYPERVISEURS_VIRTIO and not etat.get("container"):
            res["balloon"] = bool(etat.get("balloon"))
        return res
    if not dmi or not dmi.get("devices"):
        return res
    modules = dmi["devices"]
    pleins = [m for m in modules if not m["empty"]]
    vides = [m for m in modules if m["empty"]]
    soudes = [
        m for m in pleins if (m["form_factor"] or "").lower() in FORMES_SOUDEES
    ]
    installe = sum(m["size"] for m in pleins)
    capacites = [a["max_capacity"] for a in dmi["arrays"]]
    maximum = sum(capacites) if capacites and None not in capacites else None
    res.update(
        installed=installe,
        slots=len(modules),
        used_slots=len(pleins),
        free_slots=len(vides),
        form_factors=sorted(
            {m["form_factor"] for m in pleins if m["form_factor"]}
        ),
        types=sorted({m["type"] for m in pleins if m["type"]}),
        partially_soldered=bool(soudes) and len(soudes) < len(pleins),
        firmware_note=maximum is not None,
    )
    if maximum is not None and installe > maximum:
        res["max_understated"] = True
        maximum = None
    res["max_capacity"] = maximum
    ajout = None if maximum is None else max(0, maximum - installe)
    res["max_addable"] = ajout
    if soudes and len(soudes) == len(pleins) and not vides:
        res["verdict"] = "soldered"
    elif vides:
        res["verdict"] = "max" if ajout == 0 else "free_slots"
    elif ajout and len(soudes) < len(pleins):
        res["verdict"] = "replace"
    else:
        res["verdict"] = "max"
    return res


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


def commande_dmidecode(manager=None):
    """La commande qui lit la mémoire installée. dmidecode exige root ; sur
    NixOS il se lance dans un nix-shell éphémère."""
    if manager == "nix":
        return [
            "nix-shell",
            "-p",
            "dmidecode",
            "--run",
            "sudo dmidecode -t memory",
        ]
    return ["sudo", "dmidecode", "-t", "memory"]


def plan_installer_dmidecode(etat):
    """Les commandes qui installent dmidecode, [] s'il est déjà là ou sur
    NixOS (commande_dmidecode() le lance sans l'installer), None si le
    gestionnaire de paquets est inconnu."""
    racine = etat.get("racine", "/")
    if (
        etat.get("manager") == "nix"
        or shutil.which("dmidecode")
        or any(os.path.exists(_sous(racine, b)) for b in BINAIRES_DMIDECODE)
    ):
        return []
    return _plan_paquet(
        etat, dict.fromkeys(("apt", "dnf", "pacman", "zypper"), "dmidecode")
    )
