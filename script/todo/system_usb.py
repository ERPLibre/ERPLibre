#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La clé USB amorçable : quelles clés sont branchées, laquelle peut
recevoir une image, et par quelles commandes.

Deux moitiés, comme system_swap.

La LECTURE rend des faits : la sortie JSON de lsblk, lue par lire_lsblk(),
devient une liste de disques par disques(), et disques_systeme() dit
lesquels portent le système. Chaque analyseur prend le JSON déjà lu : un
test lui donne le sien.

Les PLANS rendent des listes d'arguments, jamais exécutées ici. Le menu
les montre, demande confirmation, relit lsblk, puis les lance une à une
et s'arrête à la première qui échoue. Un plan est un dict :

    {"ok": bool, "reason": code ou None, "details": {...},
     "plan": [[argv], ...], "warnings": [{"code": ..., ...}]}

Le catalogue des images prises en charge vit ici aussi : chaque entrée
porte une clé de traduction pour son libellé et, si elle n'est pas
disponible, une autre pour la raison.

Les profils machine (script/iso/archlinux/machine) se rangent ici côté
TODO : ceux du dépôt, puis ceux de private/iso/machine, que ce module
écrit en 0600. Une ISO ERPLibre écrite avec un profil passe d'abord par
plan_remaster(), qui en tire une ISO dérivée portant le profil ; le plan
d'écriture s'applique ensuite à elle sans changer.

Une ISO ERPLibre peut aussi partir avec un paquet hors ligne : l'image
ext4 LABEL=ERPLIBRE_DATA que la fabrique (offline_payload.py) range sous
DOSSIER_PAQUETS. plan_remaster() l'ajoute à l'ISO dérivée comme 3e
partition (xorriso -append_partition), le live la trouve par son
étiquette. paquets_hors_ligne() les liste avec ce qui empêche chacun de
partir, defauts_derive() vérifie que l'ISO dérivée démarre toujours en
BIOS et en UEFI, sous le même UUID.

Ce module ne rend que des codes, des chemins et des nombres (octets) ; la
phrase et la langue appartiennent au menu. Il ne lance que des commandes
de lecture.
"""

import fnmatch
import functools
import glob
import hashlib
import importlib.util
import json
import os
import re
import shutil
import tempfile

from script.iso.archlinux.machine import machine_profile as mp
from script.todo.system_diagnostic import commande

GIO = 1024**3

# Au-delà, le périphérique est un disque externe plutôt qu'une clé : son
# contenu a toutes les chances d'être une sauvegarde, et l'écraser par
# erreur coûte trop cher pour qu'on le propose sans qu'on relève le seuil.
PLAFOND = 512 * GIO

COLONNES = (
    "NAME,PATH,TYPE,TRAN,RM,HOTPLUG,RO,SIZE,VENDOR,MODEL,SERIAL,LABEL,"
    "FSTYPE,MOUNTPOINTS,PKNAME"
)
COMMANDE_LSBLK = ["lsblk", "-J", "-b", "-o", COLONNES]

# Les lsblk antérieurs à 2.37 refusent la colonne MOUNTPOINTS, et ceux
# antérieurs à 2.33 la colonne PATH : une colonne inconnue fait sortir
# lsblk en erreur. Ce jeu-ci ne garde que des colonnes connues de tous ;
# le chemin se reconstruit alors depuis NAME, et MOUNTPOINT n'annonce
# qu'un montage par nœud.
COLONNES_ANCIENNES = (
    "NAME,TYPE,TRAN,RM,HOTPLUG,RO,SIZE,VENDOR,MODEL,SERIAL,LABEL,"
    "FSTYPE,MOUNTPOINT,PKNAME"
)
COMMANDE_LSBLK_ANCIENNE = ["lsblk", "-J", "-b", "-o", COLONNES_ANCIENNES]

# Un disque qui porte l'un de ces montages, à n'importe quelle profondeur
# de son arbre, est un disque système. « [SWAP] » est la façon dont lsblk
# nomme un swap actif dans la colonne des montages. /run/archiso/bootmnt
# est le support d'un live archiso (la clé ERPLibre elle-même, quand le
# TODO tourne depuis elle) : sa racine est un overlay que lsblk ne
# rattache à aucun disque, et la clé passerait sinon pour une cible.
MONTAGES_CRITIQUES = (
    "/",
    "/boot",
    "/boot/efi",
    "/home",
    "[SWAP]",
    "/run/archiso/bootmnt",
)

# La racine du dépôt : le disque qui la porte est exclu, même s'il est
# branché en USB, puisque le menu qui écrirait tourne depuis lui.
RACINE_DEPOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

# Les transports d'un disque interne. Un tiroir SATA ou NVMe à chaud
# annonce hotplug=1, et un lecteur de carte intégré annonce rm=1 sans
# transport : ni l'un ni l'autre ne fait d'un disque une clé. Seul
# tran == "usb" en fait une, que rm vaille 0 (SSD USB) ou 1 (clé, lecteur
# de carte USB).
TRANSPORT_CLE = "usb"

DOSSIER_BY_ID = os.path.join("disk", "by-id")
PREFIXE_BY_ID = "usb-"

ISO_DIR = "~/.erplibre/iso"
MOTIF_ISO_ERPLIBRE = "erplibre-archlinux-*-x86_64.iso"
SCRIPT_CONSTRUCTION = os.path.join(
    "script", "iso", "archlinux", "build_iso.py"
)

URL_ARCH = "https://geo.mirror.pkgbuild.com/iso/latest/archlinux-x86_64.iso"
URL_ARCH_SOMMES = "https://geo.mirror.pkgbuild.com/iso/latest/sha256sums.txt"
FICHIER_ARCH = "archlinux-x86_64.iso"
FICHIER_SOMMES_ARCH = "archlinux-sha256sums.txt"

EXTENSIONS_IMAGE = (".iso", ".img")

TAILLE_BLOC_HASH = 4 * 1024**2

# Toute ISO ERPLibre Arch Linux, variantes comprises : celles-là seules
# savent lire un profil machine.
MOTIF_ISO_ERPLIBRE_TOUTES = "erplibre-archlinux-*.iso"
# La variante de test de build_iso.py : son entrée par défaut efface le
# premier disque sans rien demander, un profil n'y a pas de sens.
MOTIF_ISO_AUTOTEST = "erplibre-archlinux-autotest-*.iso"

# Les profils machine propres à cette installation : ils nomment un
# utilisateur et un hôte, d'où private/, ignoré par private/.gitignore.
DOSSIER_PROFILS_PRIVES = os.path.join(
    RACINE_DEPOT, "private", "iso", "machine"
)

# Les ISO dérivées, une par triplet (image de base, profil, paquet hors
# ligne) : leur nom porte les empreintes, un même triplet retombe sur le
# même fichier.
DOSSIER_DERIVES = "~/.erplibre/iso/derived"
CHEMIN_PROFIL_ISO = "/erplibre/machine.json"
LONGUEUR_EMPREINTE = 12
# La place du profil dans le nom d'une ISO dérivée qui n'en porte aucun.
SANS_PROFIL = "none"
# Le nom d'un fichier que le remastering écrit dans DOSSIER_DERIVES :
# l'ISO, sa somme, le profil en entrée de xorriso, et le temporaire
# d'ecrire_atomique. Le 3e segment, l'empreinte du paquet hors ligne,
# n'existe que si l'ISO en porte un ; SANS_PROFIL ne va jamais sans lui.
_HEX = "[0-9a-f]{%d}" % LONGUEUR_EMPREINTE
DERIVE_RE = re.compile(
    rf"^{_HEX}-(?:{_HEX}(?:-{_HEX})?|{SANS_PROFIL}-{_HEX})"
    r"\.(iso|iso\.sha256|json)(\.tmp)?$"
)
# Ce que xorriso ajoute à la taille de la base et du paquet : la table GPT
# de secours et l'alignement des partitions ajoutées, quelques Kio. Le
# remastering rejoue la base, et l'ISO dérivée est d'ordinaire un peu plus
# petite que cette somme.
MARGE_DERIVE = 4 * 1024**2

# Paquets hors ligne

# La fabrique (script/iso/archlinux/offline_payload.py) range chaque
# paquet sous DOSSIER_PAQUETS/<profil>-<horodatage>/ : l'image ext4 et son
# .sha256, payload/ (le répertoire dont l'image est faite), report.json et
# work/ (l'enregistrement).
DOSSIER_PAQUETS = "~/.erplibre/iso/offline"
MOTIF_IMAGE_PAQUET = "erplibre-offline-*.img"
SCRIPT_FABRIQUE = os.path.join(
    "script", "iso", "archlinux", "offline_payload.py"
)
# Le module du live qui valide un manifeste (erplibre_offline.py) : son
# dossier n'est pas un paquet Python, il se charge par son chemin.
MODULE_HORS_LIGNE = os.path.join(
    RACINE_DEPOT,
    "script",
    "iso",
    "archlinux",
    "profile",
    "airootfs",
    "usr",
    "local",
    "share",
    "erplibre-install",
    "erplibre_offline.py",
)
MANIFESTE_PAQUET = "manifest.json"
# L'étiquette que le live cherche (erplibre_offline.DATA_LABEL), le
# numéro de la partition et son type MBR (Linux).
LABEL_PAQUET = "ERPLIBRE_DATA"
NUMERO_PARTITION_PAQUET = 3
TYPE_PARTITION_PAQUET = "0x83"
# Le magasin git du service de cache de l'hôte : la fabrique y copie les
# miroirs que l'installation de référence clonerait sinon
# (offline_payload.SEED_DEFAULT).
GRAINE_GIT = "/var/cache/erplibre_go_qemu_cache/git"
# Ce qu'une fabrication demande, par profil ERPLibre : la durée en minutes
# avec et sans miroirs git amorcés, et la place libre exigée sous
# DOSSIER_PAQUETS (image, paquet et enregistrement). Ordres de grandeur :
# un profil sans étape ERPLibre ne tire que des paquets Arch (image de
# 2 à 3 Gio) ; un profil Odoo clone les dépôts d'addons avec leur
# historique (image d'environ 26 Gio, plus de 40 Gio en tout).
FABRIQUE = {
    "gnome": {"minutes": 10, "minutes_sans_graine": 10, "espace": 8 * GIO},
    "home": {"minutes": 20, "minutes_sans_graine": 60, "espace": 64 * GIO},
    "odoo18": {"minutes": 15, "minutes_sans_graine": 90, "espace": 64 * GIO},
    "dev": {"minutes": 20, "minutes_sans_graine": 90, "espace": 64 * GIO},
}
PROFILS_ERPLIBRE = tuple(FABRIQUE)
# Les tailles de clé du commerce, en Go décimaux. Une clé vendue N Go en
# offre un peu moins (Go de 10⁹ octets, zone réservée du contrôleur) :
# CAPACITE_UTILE de N·10⁹ couvre les clés courantes.
TAILLES_CLE_GO = (4, 8, 16, 32, 64, 128, 256, 512)
CAPACITE_UTILE = 0.9

# Le paquet qui fournit xorriso, par gestionnaire (voir
# qemu_privilege.install_cmd_for) : libisoburn chez Arch Linux.
PAQUETS_XORRISO = {
    "pacman": "libisoburn",
    "apt": "xorriso",
    "dnf": "xorriso",
    "zypper": "xorriso",
}


def dossier_iso():
    """ISO_DIR, le « ~ » résolu à l'appel : un test change HOME."""
    return os.path.expanduser(ISO_DIR)


# Lecture


def lire_lsblk():
    """Le JSON de lsblk sur les COLONNES, ou None si lsblk manque, échoue
    ou rend autre chose que du JSON. Un premier échec relance lsblk sur
    COLONNES_ANCIENNES."""
    for args in (COMMANDE_LSBLK, COMMANDE_LSBLK_ANCIENNE):
        sortie = commande(args)
        if not sortie:
            continue
        try:
            return json.loads(sortie)
        except ValueError:
            continue
    return None


def booleen(valeur):
    """true/false, 1/0 ou "1"/"0" selon la version de lsblk ; None faux."""
    if isinstance(valeur, str):
        return valeur.strip().lower() in ("1", "true", "yes")
    return bool(valeur)


def entier(valeur):
    """La taille en octets : un nombre, ou une chaîne de chiffres chez les
    lsblk anciens ; None si illisible."""
    if isinstance(valeur, bool):
        return None
    if isinstance(valeur, int):
        return valeur
    if isinstance(valeur, str) and valeur.strip().isdigit():
        return int(valeur.strip())
    return None


def texte(valeur):
    """Une chaîne sans les espaces de remplissage que certains contrôleurs
    USB laissent dans VENDOR, MODEL et SERIAL ; None si vide."""
    if valeur is None:
        return None
    valeur = str(valeur).strip()
    return valeur or None


def montages(noeud):
    """Les points de montage d'un nœud. MOUNTPOINTS est une liste qui
    peut contenir null ; COLONNES_ANCIENNES donne MOUNTPOINT, une seule
    chaîne."""
    if "mountpoints" in noeud:
        liste = noeud.get("mountpoints") or []
    else:
        liste = [noeud.get("mountpoint")]
    return [m for m in liste if m]


def _descendants(noeud):
    """Chaque nœud sous `noeud`, à toute profondeur, lui exclu."""
    for enfant in noeud.get("children") or []:
        yield enfant
        yield from _descendants(enfant)


def _sous_montage(chemin, montage):
    """Vrai si `chemin` est `montage` ou se trouve sous lui."""
    if not montage.startswith("/"):
        return False
    if montage == "/":
        return chemin.startswith("/")
    return chemin == montage or chemin.startswith(montage.rstrip("/") + "/")


def lien_by_id(chemin, racine_dev="/dev"):
    """Le lien /dev/disk/by-id/usb-… qui désigne `chemin`, ou None.

    Les liens « -partN » désignent des partitions et sont écartés. Le nom
    de lien porte le fabricant, le modèle et le numéro de série : un
    périphérique renuméroté entre deux commandes (sdb devenu sdc) ne le
    porte plus, et dd échoue au lieu d'écrire sur un autre disque.
    """
    dossier = os.path.join(racine_dev, DOSSIER_BY_ID)
    try:
        noms = sorted(os.listdir(dossier))
    except OSError:
        return None
    relatif = os.path.relpath(chemin, "/dev")
    cible = os.path.realpath(os.path.join(racine_dev, relatif))
    for nom in noms:
        if not nom.startswith(PREFIXE_BY_ID) or "-part" in nom:
            continue
        lien = os.path.join(dossier, nom)
        if os.path.realpath(lien) == cible:
            return lien
    return None


def _partition(noeud):
    return {
        "path": noeud.get("path") or "/dev/" + str(noeud.get("name")),
        "nom": noeud.get("name"),
        "type": noeud.get("type"),
        "taille": entier(noeud.get("size")),
        "label": texte(noeud.get("label")),
        "fstype": texte(noeud.get("fstype")),
        "mountpoints": montages(noeud),
        # Ce qui est ouvert PAR-DESSUS la partition : LUKS, LVM, md.
        "mappes": [
            d.get("path") or d.get("name") for d in _descendants(noeud)
        ],
    }


def disques(donnees, racine_dev="/dev"):
    """Les disques (type « disk ») du JSON de lsblk, chacun avec ses
    partitions directes et le lien by-id USB qui le désigne."""
    resultat = []
    for noeud in (donnees or {}).get("blockdevices") or []:
        if noeud.get("type") != "disk":
            continue
        chemin = noeud.get("path") or "/dev/" + str(noeud.get("name"))
        resultat.append(
            {
                "path": chemin,
                "nom": noeud.get("name"),
                "type": noeud.get("type"),
                "taille": entier(noeud.get("size")),
                "tran": texte(noeud.get("tran")),
                "rm": booleen(noeud.get("rm")),
                "hotplug": booleen(noeud.get("hotplug")),
                "ro": booleen(noeud.get("ro")),
                "vendor": texte(noeud.get("vendor")),
                "model": texte(noeud.get("model")),
                "serial": texte(noeud.get("serial")),
                "label": texte(noeud.get("label")),
                "fstype": texte(noeud.get("fstype")),
                # Une image ISO écrite sur tout le disque se monte sans
                # partition : le disque lui-même a alors un montage.
                "mountpoints": montages(noeud),
                "partitions": [
                    _partition(e) for e in noeud.get("children") or []
                ],
                "by_id": lien_by_id(chemin, racine_dev),
            }
        )
    return resultat


def _tous_montages(donnees):
    """[(nom du disque, point de montage)] de tout l'arbre."""
    paires = []
    for noeud in (donnees or {}).get("blockdevices") or []:
        if noeud.get("type") != "disk":
            continue
        for n in [noeud, *_descendants(noeud)]:
            for m in montages(n):
                paires.append((noeud.get("name"), m))
    return paires


def disques_systeme(
    donnees,
    montages_critiques=MONTAGES_CRITIQUES,
    chemins_extra=(RACINE_DEPOT,),
):
    """Les noms des disques qui portent le système.

    lsblk -J imbrique les enfants : une partition, puis le conteneur LUKS
    ouvert dessus, puis les volumes LVM, chacun sous le précédent. Un
    volume réparti sur deux disques, ou un md en miroir, apparaît sous
    chacun d'eux. Un disque est donc système dès que son arbre contient un
    montage critique, quelle que soit la profondeur.

    Pour chaque chemin de `chemins_extra`, le disque retenu est celui du
    plus long point de montage qui le contient : un dépôt sous /home
    pointe vers le disque de /home s'il existe, vers celui de / sinon. Un
    chemin sur un système de fichiers que lsblk ne voit pas (réseau,
    tmpfs) ne désigne aucun disque.
    """
    critiques = set(montages_critiques)
    paires = _tous_montages(donnees)
    systeme = {disque for disque, m in paires if m in critiques}
    for chemin in chemins_extra:
        if not chemin:
            continue
        chemin = os.path.realpath(chemin)
        meilleur = None
        for disque, m in paires:
            if _sous_montage(chemin, m) and (
                meilleur is None or len(m) > len(meilleur[1])
            ):
                meilleur = (disque, m)
        if meilleur:
            systeme.add(meilleur[0])
    return systeme


def est_cle(disque):
    """Vrai si le disque passe par le transport USB. rm et hotplug ne
    suffisent pas : voir TRANSPORT_CLE."""
    return disque.get("type") == "disk" and disque.get("tran") == (
        TRANSPORT_CLE
    )


def cles_usb(
    donnees,
    montages_critiques=MONTAGES_CRITIQUES,
    chemins_extra=(RACINE_DEPOT,),
    racine_dev="/dev",
    systeme=None,
):
    """Les clés candidates : disques USB qui ne portent pas le système et
    contiennent un support (un lecteur de carte vide annonce 0 octet)."""
    if systeme is None:
        systeme = disques_systeme(donnees, montages_critiques, chemins_extra)
    return [
        d
        for d in disques(donnees, racine_dev)
        if est_cle(d) and d["nom"] not in systeme and (d["taille"] or 0) > 0
    ]


def trouver(liste, chemin):
    """Le disque de `liste` dont le chemin est `chemin`, ou None."""
    return next((d for d in liste if d["path"] == chemin), None)


def meme_cle(avant, apres):
    """Vrai si `apres`, relu juste avant d'écrire, est bien la clé
    confirmée : même chemin, même numéro de série, même taille, même
    modèle. Une clé débranchée puis remplacée par une autre reprend
    souvent le même /dev/sdX."""
    if not avant or not apres:
        return False
    return all(
        avant.get(c) == apres.get(c)
        for c in ("path", "serial", "taille", "model")
    )


# Plans


def _resultat(ok, reason=None, plan=None, warnings=None, **d):
    return {
        "ok": ok,
        "reason": reason,
        "details": d,
        "plan": plan or [],
        "warnings": warnings or [],
    }


def _refus(reason, **details):
    return _resultat(False, reason, **details)


def refus_ecriture(cle, iso_taille, systeme=frozenset()):
    """None si `cle` peut recevoir une image de `iso_taille` octets ;
    sinon (code, détails). Les codes, dans l'ordre où on les teste :
    not-disk, system, not-usb, read-only, too-small, too-large, mapped."""
    if not cle or cle.get("type") != "disk":
        return "not-disk", {"device": (cle or {}).get("path")}
    details = {
        "device": cle["path"],
        "size": cle.get("taille"),
        "iso_size": iso_taille,
        "limit": PLAFOND,
    }
    if cle.get("nom") in systeme:
        return "system", details
    if cle.get("tran") != TRANSPORT_CLE:
        return "not-usb", dict(details, transport=cle.get("tran"))
    if cle.get("ro"):
        return "read-only", details
    if not cle.get("taille") or cle["taille"] < iso_taille:
        return "too-small", details
    if cle["taille"] > PLAFOND:
        return "too-large", details
    # Un conteneur LUKS ou un volume LVM ouvert sur la clé la tient
    # occupée : wipefs et dd échoueraient au milieu du plan, après les
    # démontages. On le fait fermer d'abord.
    mappes = mappages(cle)
    if mappes:
        return "mapped", dict(details, mapped=", ".join(mappes))
    return None


def mappages(cle):
    """Ce qui est ouvert sur la clé et n'est pas une partition : ce qui
    s'empile sur une partition (LUKS, LVM, md), et tout enfant direct du
    disque d'un autre type que « part » : un mappage (crypt, lvm, raid…)
    ouvert sur le disque entier, que disques() range parmi les
    partitions."""
    resultat = []
    for p in cle.get("partitions") or []:
        if p.get("type") != "part":
            resultat.append(p["path"])
        resultat.extend(p["mappes"])
    return resultat


def occupation(cle):
    """Les montages et mappages de la clé et de chaque partition, pour
    comparer l'état confirmé à celui relu juste avant d'écrire. Le plan
    ne nomme que la partition : un montage de plus sur une partition déjà
    montée le laisse identique, mais change cette valeur."""
    return [
        (cle.get("path"), tuple(cle.get("mountpoints") or ())),
        *(
            (p["path"], tuple(p["mountpoints"]), tuple(p["mappes"]))
            for p in cle.get("partitions") or []
        ),
    ]


def iso_sur_cle(cle, iso_path):
    """Le point de montage de la clé qui contient `iso_path`, ou None :
    dd écraserait l'image pendant qu'il la lit."""
    chemin = os.path.realpath(iso_path)
    points = list(cle.get("mountpoints") or [])
    for p in cle.get("partitions") or []:
        points.extend(p["mountpoints"])
    for m in points:
        if m != "/" and _sous_montage(chemin, m):
            return m
    return None


def plan_ecriture(cle, iso_path, iso_taille, systeme=frozenset(), eject=None):
    """Le plan qui écrit `iso_path` sur `cle` puis le vérifie.

    Chaque partition montée se démonte de tous ses points de montage
    (umount -A ; un umount sans -A ne retire que le dernier montage d'un
    périphérique monté deux fois), un swap s'éteint,
    wipefs efface les signatures que dd ne recouvrirait pas en fin de clé,
    dd écrit en contournant le cache (oflag=direct) et rend la main après
    la synchronisation (conv=fsync), cmp relit les `iso_taille` premiers
    octets, et eject prépare le retrait. Le périphérique visé par dd est
    le lien by-id quand il existe.

    `eject` dit si la commande eject existe ; None la cherche dans le
    PATH. Absente, le plan s'en passe et le dit dans une mise en garde.
    """
    refus = refus_ecriture(cle, iso_taille, systeme)
    if refus:
        code, details = refus
        return _refus(code, **details)
    sur_cle = iso_sur_cle(cle, iso_path)
    if sur_cle:
        return _refus(
            "iso-on-key", device=cle["path"], mountpoint=sur_cle, path=iso_path
        )
    cible = cle.get("by_id") or cle["path"]
    plan = []
    noeuds = [*(cle.get("partitions") or []), cle]
    for n in noeuds:
        points = n.get("mountpoints") or []
        if "[SWAP]" in points:
            plan.append(["sudo", "swapoff", n["path"]])
        if any(m != "[SWAP]" for m in points):
            plan.append(["sudo", "umount", "-A", n["path"]])
    plan += [
        ["sudo", "wipefs", "--all", cible],
        [
            "sudo",
            "dd",
            f"if={iso_path}",
            f"of={cible}",
            "bs=4M",
            "conv=fsync",
            "oflag=direct",
            "status=progress",
        ],
        ["sync"],
        ["sudo", "cmp", "-n", str(iso_taille), iso_path, cible],
    ]
    alertes = []
    if eject is None:
        eject = shutil.which("eject") is not None
    if eject:
        plan.append(["sudo", "eject", cible])
    else:
        alertes.append({"code": "no-eject", "device": cle["path"]})
    return _resultat(
        True,
        plan=plan,
        warnings=alertes,
        device=cle["path"],
        target=cible,
        size=cle.get("taille"),
        iso_size=iso_taille,
    )


# Catalogue des images


def iso_erplibre_locale(dossier=None):
    """La plus récente ISO ERPLibre construite dans `dossier` (ISO_DIR par
    défaut), par date de modification puis par nom ; None sinon."""
    dossier = dossier or dossier_iso()
    fichiers = [
        f
        for f in glob.glob(os.path.join(dossier, MOTIF_ISO_ERPLIBRE))
        if os.path.isfile(f)
    ]
    if not fichiers:
        return None
    return max(fichiers, key=lambda f: (os.path.getmtime(f), f))


def catalogue(dossier=None):
    """Les images que le menu sait proposer, disponibles ou non.

    Chaque entrée : cle, libelle_key, arch, source (« local » ou « url »),
    disponible, raison_key (None si disponible) et chemin (le fichier
    local, existant ou à télécharger ; None si sans objet).
    """
    dossier = dossier or dossier_iso()
    locale = iso_erplibre_locale(dossier)
    return [
        {
            "cle": "erplibre-archlinux-amd64",
            "libelle_key": "ERPLibre Arch Linux GNOME (amd64)",
            "arch": "x86_64",
            "source": "local",
            "disponible": locale is not None,
            "raison_key": None
            if locale
            else "Not built yet: use « Build the ERPLibre Arch Linux ISO ».",
            "chemin": locale,
        },
        {
            "cle": "archlinux-amd64",
            "libelle_key": "Arch Linux official (amd64)",
            "arch": "x86_64",
            "source": "url",
            "disponible": True,
            "raison_key": None,
            "url": URL_ARCH,
            "sha256_url": URL_ARCH_SOMMES,
            "fichier": FICHIER_ARCH,
            "chemin": os.path.join(dossier, FICHIER_ARCH),
            "sommes": os.path.join(dossier, FICHIER_SOMMES_ARCH),
        },
        {
            "cle": "erplibre-archlinux-arm64",
            "libelle_key": "ERPLibre Arch Linux (arm64)",
            "arch": "aarch64",
            "source": "local",
            "disponible": False,
            "raison_key": "Planned: archiso builds aarch64 only on an aarch64 host, and Arch Linux has no official aarch64 repository.",
            "chemin": None,
        },
        {
            "cle": "erplibre-archlinux-s390x",
            "libelle_key": "ERPLibre Arch Linux (s390x)",
            "arch": "s390x",
            "source": "local",
            "disponible": False,
            "raison_key": "Not possible: Arch Linux has no s390x port, and a mainframe does not boot from a USB key.",
            "chemin": None,
        },
    ]


def plan_telechargement(entree):
    """Le plan qui télécharge une entrée « url » du catalogue dans son
    dossier : la liste des sommes SHA-256, puis l'image vers un fichier
    « .part » que curl reprend là où il s'était arrêté (-C -). Le menu
    vérifie la somme et renomme ; une somme fausse supprime le .part, car
    « latest » change de contenu à chaque publication et une reprise sur
    l'ancien fichier ne donnerait jamais la bonne somme."""
    if entree.get("source") != "url" or not entree.get("disponible"):
        return _refus("not-downloadable", key=entree.get("cle"))
    partiel = entree["chemin"] + ".part"
    return _resultat(
        True,
        plan=[
            [
                "curl",
                "-fsSL",
                "--retry",
                "3",
                "-o",
                entree["sommes"],
                entree["sha256_url"],
            ],
            [
                "curl",
                "-fL",
                "--retry",
                "3",
                "-C",
                "-",
                "-o",
                partiel,
                entree["url"],
            ],
        ],
        path=entree["chemin"],
        partial=partiel,
        sums=entree["sommes"],
        file=entree["fichier"],
    )


def parse_sha256sums(texte_sommes, nom):
    """La somme SHA-256 (64 chiffres hexadécimaux, en minuscules) de `nom`
    dans un fichier au format de sha256sum, ou None. Le nom peut être
    précédé de « * » (mode binaire) ou d'un chemin relatif « ./ »."""
    for ligne in (texte_sommes or "").splitlines():
        morceaux = ligne.strip().split(None, 1)
        if len(morceaux) != 2:
            continue
        somme, fichier = morceaux
        fichier = fichier.strip().lstrip("*")
        if fichier.startswith("./"):
            fichier = fichier[2:]
        if fichier != nom:
            continue
        somme = somme.lower()
        if len(somme) == 64 and all(c in "0123456789abcdef" for c in somme):
            return somme
    return None


def sha256_fichier(chemin):
    """La somme SHA-256 d'un fichier, lu par blocs ; None s'il est
    illisible."""
    h = hashlib.sha256()
    try:
        with open(chemin, "rb") as fh:
            for bloc in iter(lambda: fh.read(TAILLE_BLOC_HASH), b""):
                h.update(bloc)
    except OSError:
        return None
    return h.hexdigest()


def extension_image(chemin):
    """Vrai si `chemin` porte une extension d'image connue."""
    return chemin.lower().endswith(EXTENSIONS_IMAGE)


# Profils machine


def dossiers_profils(prive=None):
    """Les dossiers de profils, dans l'ordre où le dernier gagne : le
    dépôt, puis le dossier privé."""
    return [mp.REPO_DIR, prive or DOSSIER_PROFILS_PRIVES]


def dossier_prive(dossier):
    """Crée `dossier` et chacun de ses parents manquants en 0700, puis
    ramène `dossier` à 0700 s'il existait déjà plus ouvert : os.makedirs
    n'applique son mode qu'au dernier niveau créé, et jamais à un dossier
    existant. Les parents déjà là ne sont pas touchés. Rend `dossier`."""
    manquants = []
    courant = os.path.abspath(dossier)
    while not os.path.isdir(courant):
        manquants.append(courant)
        parent = os.path.dirname(courant)
        if parent == courant:
            break
        courant = parent
    for chemin in reversed(manquants):
        try:
            os.mkdir(chemin, 0o700)
        except FileExistsError:
            pass
    os.chmod(dossier, 0o700)
    return dossier


def ecrire_atomique(chemin, texte, mode=0o600):
    """Écrit `texte` dans `chemin` par un fichier temporaire renommé : un
    lecteur voit l'ancien contenu ou le nouveau, jamais un fichier à
    moitié écrit. Le dossier passe en 0700 (dossier_prive), le fichier
    naît en `mode`. Une écriture qui échoue (disque plein, quota) retire
    le temporaire et laisse passer l'OSError."""
    dossier_prive(os.path.dirname(chemin))
    temporaire = f"{chemin}.tmp"
    descripteur = os.open(
        temporaire, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode
    )
    try:
        with os.fdopen(descripteur, "w", encoding="utf-8") as fh:
            fh.write(texte)
        os.chmod(temporaire, mode)
        os.replace(temporaire, chemin)
    except OSError:
        try:
            os.remove(temporaire)
        except OSError:
            pass
        raise
    return chemin


def enregistrer_profil(profil, prive=None, chemin=None):
    """Écrit `profil` en 0600 dans `chemin`, ou à défaut dans le dossier
    privé sous <slug du nom>.json. L'édition passe le fichier ouvert : un
    profil dont le nom ne donne pas son nom de fichier est réécrit sur
    place, pas copié à côté. Refuse (ValueError, avec les codes) un profil
    que validate() rejette : un secret n'atteint jamais le disque."""
    erreurs = mp.validate(profil)
    if erreurs:
        raise ValueError(erreurs)
    if chemin is None:
        chemin = os.path.join(
            prive or DOSSIER_PROFILS_PRIVES,
            mp.slug(profil.get("name")) + ".json",
        )
    return ecrire_atomique(chemin, mp.dump(profil))


def est_iso_erplibre(chemin):
    """Vrai si le nom du fichier est celui d'une ISO ERPLibre Arch Linux
    qui accepte un profil machine : toutes, sauf la variante autotest."""
    nom = os.path.basename(chemin or "")
    return fnmatch.fnmatch(
        nom, MOTIF_ISO_ERPLIBRE_TOUTES
    ) and not fnmatch.fnmatch(nom, MOTIF_ISO_AUTOTEST)


def dossier_derives():
    """DOSSIER_DERIVES, le « ~ » résolu à l'appel."""
    return os.path.expanduser(DOSSIER_DERIVES)


def sha256_texte(texte):
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()


def chemin_derive(dossier, sha_base, sha_profil=None, sha_paquet=None):
    """<dossier>/<12 de l'empreinte de base>-<12 du profil>[-<12 du
    paquet>].iso ; SANS_PROFIL tient la place d'un profil absent."""
    n = LONGUEUR_EMPREINTE
    nom = f"{sha_base[:n]}-{sha_profil[:n] if sha_profil else SANS_PROFIL}"
    if sha_paquet:
        nom += f"-{sha_paquet[:n]}"
    return os.path.join(dossier, nom + ".iso")


def chemin_somme(derive):
    """Le fichier de somme d'une ISO dérivée, écrit une fois le
    remastering réussi : sans lui, ou s'il ne correspond plus, l'ISO est
    à refaire."""
    return derive + ".sha256"


def derives_perimes(dossier, garder):
    """Les fichiers de `dossier` nés d'un remastering (DERIVE_RE) autres
    que ceux de l'ISO dérivée `garder` : chaque édition d'un profil change
    son empreinte, donc le nom de l'ISO suivante, et les anciennes ne
    servent plus. Le dossier n'est qu'un cache : une ISO retirée se refait
    à la prochaine écriture. Un fichier qui ne suit pas le motif n'est
    jamais rendu."""
    base = os.path.splitext(os.path.basename(garder))[0]
    try:
        noms = sorted(os.listdir(dossier))
    except OSError:
        return []
    return [
        os.path.join(dossier, nom)
        for nom in noms
        if DERIVE_RE.match(nom)
        and not nom.startswith(base + ".")
        and os.path.isfile(os.path.join(dossier, nom))
    ]


def derive_valide(derive):
    """Vrai si l'ISO dérivée existe et que sa somme SHA-256 est celle que
    son fichier .sha256 annonce. Un remastering interrompu laisse une ISO
    sans somme, donc à refaire."""
    if not os.path.isfile(derive):
        return False
    try:
        with open(chemin_somme(derive), encoding="utf-8") as fh:
            attendue = parse_sha256sums(fh.read(), os.path.basename(derive))
    except OSError:
        return False
    return attendue is not None and sha256_fichier(derive) == attendue


def ligne_somme(derive):
    """La ligne au format de sha256sum pour l'ISO dérivée, ou None."""
    somme = sha256_fichier(derive)
    if somme is None:
        return None
    return f"{somme}  {os.path.basename(derive)}\n"


def uuid_vers_volume_date(uuid):
    """L'UUID d'une ISO 9660 tel que blkid l'écrit
    (« AAAA-MM-JJ-hh-mm-ss-cc ») en date de volume pour xorriso
    -volume_date uuid (« AAAAMMJJhhmmsscc ») ; None si ce n'est pas un
    tel UUID. archiso retrouve son support par cet UUID
    (archisosearchuuid) : l'ISO dérivée doit garder le même."""
    if not isinstance(uuid, str):
        return None
    morceaux = uuid.strip().split("-")
    if [len(m) for m in morceaux] != [4, 2, 2, 2, 2, 2, 2] or not all(
        m.isdigit() for m in morceaux
    ):
        return None
    return "".join(morceaux)


_PVD_DATE_RE = re.compile(r"^(Modif\. Time|Creation Time)\s*:\s*(\d{16})\s*$")


def volume_date_depuis_pvd(texte):
    """La date de volume de la sortie de xorriso -pvd_info : celle de
    modification, celle de création à défaut, comme blkid. None si
    aucune, ou si elle est nulle."""
    dates = {}
    for ligne in (texte or "").splitlines():
        m = _PVD_DATE_RE.match(ligne.strip())
        if m:
            dates[m.group(1)] = m.group(2)
    for cle in ("Modif. Time", "Creation Time"):
        if dates.get(cle, "0" * 16).strip("0"):
            return dates[cle]
    return None


def lire_volume_date(iso):
    """La date de volume de `iso` pour -volume_date uuid : par blkid,
    sinon par xorriso -pvd_info ; None si aucun ne répond."""
    date = uuid_vers_volume_date(
        (commande(["blkid", "-s", "UUID", "-o", "value", iso]) or "").strip()
    )
    if date:
        return date
    return volume_date_depuis_pvd(
        commande(["xorriso", "-indev", iso, "-pvd_info"], timeout=60)
    )


def plan_remaster(
    base,
    profil_json,
    derive,
    volume_date,
    reutiliser=False,
    image_paquet=None,
):
    """Le plan qui fabrique `derive`, copie de l'ISO `base` portant le
    profil `profil_json` en CHEMIN_PROFIL_ISO et, si `image_paquet` est
    donnée, ce paquet hors ligne comme partition NUMERO_PARTITION_PAQUET.
    L'un ou l'autre peut manquer (None).

    xorriso relit `base` (-indev) et écrit une image neuve (-outdev) : le
    démarrage BIOS et UEFI est rejoué tel quel (-boot_image any replay),
    la date de volume reprend celle de `base` pour que l'UUID que cherche
    archiso ne change pas, et -map ajoute le fichier. Le rejeu ne reprend
    pas les GUID de la table GPT : sans gpt_disk_guid=volume_date_uuid ils
    seraient tirés au hasard, alors qu'avec lui ils se dérivent de la date
    de volume comme ceux que mkarchiso écrit. `reutiliser` vrai
    (voir derive_valide) rend un plan vide.

    Le rejeu recrée la partition 2 (l'ESP) que mkarchiso ajoute ;
    -append_partition, posé après lui, ajoute la 3e derrière elle, dans la
    table MBR que le noyau lit et dans la GPT hybride que lit le
    micrologiciel UEFI. Le paquet est donc écrit avec l'ISO, par le même
    dd : la clé n'est jamais modifiée après coup.

    Refus : no-volume-date si `volume_date` n'est pas une date de volume
    de 16 chiffres.
    """
    if reutiliser:
        return _resultat(True, derived=derive, reuse=True, base=base)
    if not (
        isinstance(volume_date, str)
        and len(volume_date) == 16
        and volume_date.isdigit()
    ):
        return _refus("no-volume-date", path=base)
    argv = [
        "xorriso",
        "-indev",
        base,
        "-outdev",
        derive,
        "-boot_image",
        "any",
        "replay",
        "-boot_image",
        "any",
        "gpt_disk_guid=volume_date_uuid",
        "-volume_date",
        "uuid",
        volume_date,
    ]
    if profil_json:
        argv += ["-map", profil_json, CHEMIN_PROFIL_ISO]
    if image_paquet:
        argv += [
            "-append_partition",
            str(NUMERO_PARTITION_PAQUET),
            TYPE_PARTITION_PAQUET,
            image_paquet,
        ]
    argv.append("-commit")
    return _resultat(
        True,
        plan=[argv],
        derived=derive,
        reuse=False,
        base=base,
        profile=profil_json,
        payload=image_paquet,
        volume_date=volume_date,
    )


# Contrôle de l'ISO dérivée

_ELTORITO_RE = re.compile(
    r"^El Torito boot img\s*:\s*\d+\s+(BIOS|UEFI)\b", re.M
)
_NUMERO_RE = re.compile(r"(\d+)$")


def lire_faits_derive(derive):
    """Ce que defauts_derive() examine, lu sur le fichier `derive` sans
    root : la table de partitions (sfdisk -J), le catalogue El Torito
    (xorriso -report_el_torito) et la date de volume (via blkid). Une
    valeur illisible vaut None."""
    sortie = commande(["sfdisk", "-J", derive], timeout=30)
    try:
        table = json.loads(sortie) if sortie else None
    except ValueError:
        table = None
    return {
        "sfdisk": table,
        "eltorito": commande(
            ["xorriso", "-indev", derive, "-report_el_torito", "plain"],
            timeout=120,
        ),
        "volume_date": lire_volume_date(derive),
    }


def partitions_table(table):
    """{numéro: {"type", "octets"}} d'une sortie de sfdisk -J. Le numéro
    est le suffixe du nœud (« derive.iso3 » → 3), le type tel que sfdisk
    l'écrit (« ef », « 83 »), sans casse."""
    resultat = {}
    racine = (table or {}).get("partitiontable") or {}
    secteur = racine.get("sectorsize") or 512
    for p in racine.get("partitions") or []:
        m = _NUMERO_RE.search(str(p.get("node") or ""))
        if not m:
            continue
        resultat[int(m.group(1))] = {
            "type": str(p.get("type") or "").lower(),
            "octets": int(p.get("size") or 0) * secteur,
        }
    return resultat


def defauts_derive(faits, volume_date, image_octets=None):
    """Les codes de ce qui manque à une ISO dérivée pour démarrer comme sa
    base ; [] si rien. `faits` vient de lire_faits_derive().

    - unreadable : sfdisk ou xorriso n'a rien rendu ;
    - uuid-changed : la date de volume n'est plus `volume_date`, et
      archiso ne retrouverait pas son support (archisosearchuuid) ;
    - no-bios-boot, no-uefi-boot : une image El Torito manque ;
    - no-esp : plus de partition EFI (type ef) pour une clé en UEFI ;
    - no-data-partition : `image_octets` donné, et la partition
      NUMERO_PARTITION_PAQUET manque, n'est pas de type Linux ou est plus
      petite que l'image.
    """
    if not faits.get("sfdisk") or not faits.get("eltorito"):
        return ["unreadable"]
    defauts = []
    if faits.get("volume_date") != volume_date:
        defauts.append("uuid-changed")
    plateformes = set(_ELTORITO_RE.findall(faits["eltorito"]))
    if "BIOS" not in plateformes:
        defauts.append("no-bios-boot")
    if "UEFI" not in plateformes:
        defauts.append("no-uefi-boot")
    parts = partitions_table(faits["sfdisk"])
    if not any(p["type"] == "ef" for p in parts.values()):
        defauts.append("no-esp")
    if image_octets:
        donnees = parts.get(NUMERO_PARTITION_PAQUET)
        if (
            not donnees
            or donnees["type"] != TYPE_PARTITION_PAQUET[2:]
            or donnees["octets"] < image_octets
        ):
            defauts.append("no-data-partition")
    return defauts


# Paquets hors ligne : liste, validité, compatibilité


def dossier_paquets():
    """DOSSIER_PAQUETS, le « ~ » résolu à l'appel."""
    return os.path.expanduser(DOSSIER_PAQUETS)


@functools.lru_cache(maxsize=1)
def module_hors_ligne(chemin=MODULE_HORS_LIGNE):
    """erplibre_offline, chargé une fois depuis `chemin` ; sa
    check_manifest() est celle du live, et le TODO refuse donc ce que le
    live refuserait."""
    spec = importlib.util.spec_from_file_location(
        "erplibre_offline_todo", chemin
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _json_objet(texte):
    """Le dict que `texte` encode, ou None."""
    try:
        doc = json.loads(texte or "")
    except ValueError:
        return None
    return doc if isinstance(doc, dict) else None


def _lire_json(chemin):
    try:
        with open(chemin, encoding="utf-8") as fh:
            return _json_objet(fh.read())
    except OSError:
        return None


def lire_manifeste_image(chemin):
    """Le manifeste (dict) à la racine du système ext4 de `chemin`, une
    image ou une partition, lu par debugfs sans montage ni root ; None si
    debugfs manque, si `chemin` est illisible ou si le fichier n'est pas
    un objet JSON. debugfs sort sur 0 même en échec : seul le contenu
    tranche."""
    return _json_objet(
        commande(
            ["debugfs", "-R", f"cat /{MANIFESTE_PAQUET}", chemin], timeout=30
        )
    )


def _uuid_reference(dossier, manifeste):
    """L'UUID de l'ISO qui a enregistré le paquet : celui du manifeste,
    sinon celui du plan de fabrication (work/state.json), qu'un manifeste
    plus ancien ne recopiait pas ; None si aucun."""
    uuid = (manifeste.get("reference") or {}).get("iso_uuid")
    if uuid:
        return uuid
    etat = _lire_json(os.path.join(dossier, "work", "state.json")) or {}
    return (etat.get("plan") or {}).get("iso_uuid")


def paquet_hors_ligne(dossier, lire_manifeste=None):
    """Le paquet rangé dans `dossier`, ou None s'il n'y a aucune image.

    Rend {"dossier", "image", "taille", "sha256", "manifeste", "profil",
    "date", "iso_uuid", "erreurs"}. Le manifeste est lu dans l'image même
    (`lire_manifeste`, lire_manifeste_image par défaut), à défaut dans
    payload/. `erreurs` liste les codes qui empêchent le paquet de partir
    sur une clé, [] sinon :

    - no-sha256 : pas de .sha256, ou sans la ligne de l'image ;
    - manifest-unreadable : aucun manifeste lisible ;
    - manifest-invalid : check_manifest() du live le refuse ;
    - record : manifeste d'enregistrement, qui ne sert pas hors ligne ;
    - report-not-ok : report.json dit qu'un paquet requis manque au
      dépôt ou n'a pas de signature.

    Rien n'est haché ici : la somme d'une image de dizaines de Gio prend
    la minute, elle se vérifie juste avant le remastering.
    """
    lire_manifeste = lire_manifeste or lire_manifeste_image
    images = sorted(
        f
        for f in glob.glob(os.path.join(dossier, MOTIF_IMAGE_PAQUET))
        if os.path.isfile(f)
    )
    if not images:
        return None
    image = images[-1]
    erreurs = []
    try:
        with open(image + ".sha256", encoding="utf-8") as fh:
            somme = parse_sha256sums(fh.read(), os.path.basename(image))
    except OSError:
        somme = None
    if somme is None:
        erreurs.append("no-sha256")
    manifeste = lire_manifeste(image) or _lire_json(
        os.path.join(dossier, "payload", MANIFESTE_PAQUET)
    )
    hl = module_hors_ligne()
    if manifeste is None:
        erreurs.append("manifest-unreadable")
        manifeste = {}
    elif hl.is_record(manifeste):
        erreurs.append("record")
    elif hl.check_manifest(manifeste):
        erreurs.append("manifest-invalid")
    rapport = _lire_json(os.path.join(dossier, "report.json"))
    if rapport is not None and rapport.get("ok") is False:
        erreurs.append("report-not-ok")
    return {
        "dossier": dossier,
        "image": image,
        "taille": os.path.getsize(image),
        "sha256": somme,
        "manifeste": manifeste,
        "profil": manifeste.get("erplibre_profile"),
        "date": str(manifeste.get("created") or "")[:10] or None,
        "iso_uuid": _uuid_reference(dossier, manifeste),
        "erreurs": erreurs,
    }


def paquets_hors_ligne(dossier=None, lire_manifeste=None):
    """Les paquets de `dossier` (DOSSIER_PAQUETS par défaut), un par
    sous-dossier qui porte une image, du plus récent au plus ancien ; les
    invalides y sont, avec leurs erreurs."""
    dossier = dossier or dossier_paquets()
    try:
        noms = sorted(os.listdir(dossier))
    except OSError:
        return []
    paquets = []
    for nom in noms:
        chemin = os.path.join(dossier, nom)
        if os.path.isdir(chemin):
            p = paquet_hors_ligne(chemin, lire_manifeste)
            if p is not None:
                paquets.append(p)
    paquets.sort(
        key=lambda p: (str(p["manifeste"].get("created") or ""), p["image"]),
        reverse=True,
    )
    return paquets


def cle_conseillee(octets):
    """La plus petite taille de clé du commerce (en Go, voir
    TAILLES_CLE_GO) qui reçoit `octets` ; None au-delà de la plus
    grande."""
    return next(
        (
            n
            for n in TAILLES_CLE_GO
            if n * 10**9 * CAPACITE_UTILE >= (octets or 0)
        ),
        None,
    )


def taille_derive(taille_base, taille_image=0):
    """La taille attendue de l'ISO dérivée, par excès (MARGE_DERIVE)."""
    return taille_base + (taille_image or 0) + MARGE_DERIVE


def version_pkglist(texte, paquet="archinstall"):
    """La version (sans le pkgrel) de `paquet` dans un pkglist.x86_64.txt
    d'archiso (« nom version-pkgrel » par ligne), ou None."""
    for ligne in (texte or "").splitlines():
        morceaux = ligne.split()
        if len(morceaux) == 2 and morceaux[0] == paquet:
            return morceaux[1].rsplit("-", 1)[0]
    return None


def _majeur_mineur(version):
    return tuple(int(m) for m in re.findall(r"\d+", str(version or ""))[:2])


def lire_pkglist(iso):
    """Le pkglist.x86_64.txt de `iso` (les paquets du live, versions
    comprises), extrait par xorriso dans un dossier temporaire ; None si
    xorriso manque ou échoue."""
    with tempfile.TemporaryDirectory(prefix="erplibre-pkglist-") as tmp:
        cible = os.path.join(tmp, "pkglist.txt")
        sortie = commande(
            [
                "xorriso",
                "-osirrox",
                "on",
                "-indev",
                iso,
                "-extract",
                "/arch/pkglist.x86_64.txt",
                cible,
            ],
            timeout=60,
        )
        if sortie is None:
            return None
        try:
            with open(cible, encoding="utf-8") as fh:
                return fh.read()
        except OSError:
            return None


def lire_uuid_iso(iso):
    """L'UUID ISO 9660 de `iso` tel que blkid l'écrit
    (« AAAA-MM-JJ-hh-mm-ss-cc »), ou None."""
    sortie = commande(["blkid", "-p", "-s", "UUID", "-o", "value", iso])
    return (sortie or "").strip() or None


def alertes_paquet(paquet, pkglist, uuid_iso):
    """Les mises en garde d'un paquet pour l'ISO qui le recevra.

    - iso-unknown : rien ne dit avec quelle ISO le paquet a été enregistré ;
    - other-iso : il l'a été avec une autre ISO (UUID `uuid`) ;
    - archinstall-mismatch : l'ISO porte un archinstall d'une autre
      version majeure.mineure (`iso`) que celui du paquet (`payload`) ;
      il peut demander des paquets que le dépôt n'a pas.

    Seule l'ISO sait si elle a le mode hors ligne : une ISO plus ancienne
    que lui ignore la partition, et la clé installe alors en ligne.
    """
    alertes = []
    reference = paquet.get("iso_uuid")
    if not reference:
        alertes.append({"code": "iso-unknown"})
    elif uuid_iso and reference != uuid_iso:
        alertes.append({"code": "other-iso", "uuid": reference})
    attendue = (paquet.get("manifeste") or {}).get("archinstall_version")
    sur_iso = version_pkglist(pkglist)
    if (
        attendue
        and sur_iso
        and _majeur_mineur(attendue) != _majeur_mineur(sur_iso)
    ):
        alertes.append(
            {
                "code": "archinstall-mismatch",
                "iso": sur_iso,
                "payload": attendue,
            }
        )
    return alertes


def espace_libre(chemin):
    """Les octets libres du système de fichiers qui porte `chemin`, ou
    son plus proche parent existant ; None si illisible."""
    courant = os.path.abspath(chemin)
    while not os.path.exists(courant):
        parent = os.path.dirname(courant)
        if parent == courant:
            return None
        courant = parent
    try:
        return shutil.disk_usage(courant).free
    except OSError:
        return None


def verdict_espace(besoin, libre, recuperable=0):
    """None si `libre` suffit à `besoin` ; « cleanup » s'il suffit une
    fois `recuperable` octets retirés (les ISO dérivées périmées) ;
    « no-space » sinon. Un `libre` inconnu (None) ne refuse rien."""
    if libre is None or libre >= besoin:
        return None
    if libre + (recuperable or 0) >= besoin:
        return "cleanup"
    return "no-space"


def partition_paquet(cle):
    """La partition ext4 LABEL_PAQUET de `cle` (un disque de disques()),
    ou None : une clé écrite avec un paquet hors ligne la porte."""
    return next(
        (
            p
            for p in cle.get("partitions") or []
            if p.get("label") == LABEL_PAQUET and p.get("fstype") == "ext4"
        ),
        None,
    )


def manifeste_partition(partition, lisible=None):
    """Le manifeste de la partition de paquet, lu par debugfs si l'on a le
    droit de lire le périphérique (groupe disk) ; None sinon, sans sudo."""
    lisible = lisible or (lambda p: os.access(p, os.R_OK))
    if not lisible(partition["path"]):
        return None
    return lire_manifeste_image(partition["path"])


def plan_fabrique(profil, iso, python, dossier, graine=None, libre=None):
    """Le plan qui fabrique un paquet hors ligne du profil ERPLibre
    `profil` depuis l'ISO `iso`, rangé sous `dossier` (offline_payload.py
    build). `graine`, s'il est donné, est le dossier des miroirs git à
    copier d'abord ; un profil sans étape ERPLibre (gnome) n'en clone
    aucun et ne la reçoit pas.

    Refus : unknown-erplibre-profile ; no-space si `libre` (octets libres
    sous `dossier`, None si inconnu) est sous FABRIQUE[profil]["espace"].
    """
    if profil not in FABRIQUE:
        return _refus("unknown-erplibre-profile", profile=profil)
    besoins = FABRIQUE[profil]
    if libre is not None and libre < besoins["espace"]:
        return _refus(
            "no-space", path=dossier, need=besoins["espace"], free=libre
        )
    if profil == "gnome":
        graine = None
    argv = [
        python,
        SCRIPT_FABRIQUE,
        "build",
        "--profile",
        profil,
        "--iso",
        iso,
        "--out",
        dossier,
    ]
    if graine:
        argv += ["--seed-git-mirrors", graine]
    return _resultat(
        True,
        plan=[argv],
        profile=profil,
        minutes=besoins[
            "minutes" if graine or profil == "gnome" else "minutes_sans_graine"
        ],
        need=besoins["espace"],
        free=libre,
        seed=graine,
        path=dossier,
    )
