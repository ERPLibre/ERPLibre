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

Ce module ne rend que des codes, des chemins et des nombres (octets) ; la
phrase et la langue appartiennent au menu. Il ne lance que des commandes
de lecture.
"""

import fnmatch
import glob
import hashlib
import json
import os
import re
import shutil

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

# Les ISO dérivées, une par couple (image de base, profil) : leur nom
# porte les deux empreintes, une même paire retombe sur le même fichier.
DOSSIER_DERIVES = "~/.erplibre/iso/derived"
CHEMIN_PROFIL_ISO = "/erplibre/machine.json"
LONGUEUR_EMPREINTE = 12
# Le nom d'un fichier que le remastering écrit dans DOSSIER_DERIVES :
# l'ISO, sa somme, le profil en entrée de xorriso, et le temporaire
# d'ecrire_atomique.
DERIVE_RE = re.compile(
    r"^[0-9a-f]{%d}-[0-9a-f]{%d}\.(iso|iso\.sha256|json)(\.tmp)?$"
    % (LONGUEUR_EMPREINTE, LONGUEUR_EMPREINTE)
)

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


def chemin_derive(dossier, sha_base, sha_profil):
    """<dossier>/<12 premiers de l'empreinte de base>-<12 du profil>.iso"""
    n = LONGUEUR_EMPREINTE
    return os.path.join(dossier, f"{sha_base[:n]}-{sha_profil[:n]}.iso")


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


def plan_remaster(base, profil_json, derive, volume_date, reutiliser=False):
    """Le plan qui fabrique `derive`, copie de l'ISO `base` portant le
    profil `profil_json` en CHEMIN_PROFIL_ISO.

    xorriso relit `base` (-indev) et écrit une image neuve (-outdev) : le
    démarrage BIOS et UEFI est rejoué tel quel (-boot_image any replay),
    la date de volume reprend celle de `base` pour que l'UUID que cherche
    archiso ne change pas, et -map ajoute le fichier. Le rejeu ne reprend
    pas les GUID de la table GPT : sans gpt_disk_guid=volume_date_uuid ils
    seraient tirés au hasard, alors qu'avec lui ils se dérivent de la date
    de volume comme ceux que mkarchiso écrit. `reutiliser` vrai
    (voir derive_valide) rend un plan vide.

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
    return _resultat(
        True,
        plan=[
            [
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
                "-map",
                profil_json,
                CHEMIN_PROFIL_ISO,
                "-commit",
            ]
        ],
        derived=derive,
        reuse=False,
        base=base,
        profile=profil_json,
    )
