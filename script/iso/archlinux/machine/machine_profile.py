#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le profil machine de l'installateur ERPLibre Arch Linux : ce que la
machine cible recevra — disque, noyaux, système, utilisateur, bureau —
écrit en JSON versionné.

Ce module sert deux côtés : le menu TODO, qui édite les profils et les
place sur la clé, et l'installateur du live, qui les applique. Il est
copié tel quel dans l'ISO, d'où deux contraintes : la bibliothèque
standard seulement (Python 3.11 ou plus), et aucun import de script.todo.
Il ne lit et n'écrit que les fichiers qu'on lui nomme ; les chemins
privés appartiennent à l'appelant.

Chaque champ prend un littéral, « auto » (décidé par resolve() depuis les
faits du matériel) ou « ask » (demandé à l'installation). FIELDS dit, champ
par champ, ce qui est accepté ; validate() rend des codes, jamais des
phrases, et l'appelant les traduit.

Un profil peut en étendre un autre par son nom (« extends ») : effective()
superpose DEFAULTS, puis chaque ancêtre, puis le profil, le dernier gagnant
champ par champ. Les listes se remplacent en bloc, elles ne se fusionnent
pas.

Aucun secret n'est accepté, ni en clair ni haché : validate() refuse toute
clé dont le nom évoque un mot de passe, une clé secrète ou un hash, et
toute valeur qui a la forme d'un hash crypt(3). Un profil voyage sur une
clé USB qui peut se perdre, et un hash s'y casse hors ligne. Les phrases
LUKS et les mots de passe se saisissent à l'installation.
"""

import copy
import json
import math
import os
import re

SCHEMA_VERSION = 1

AUTO = "auto"
ASK = "ask"

MIB = 1024**2
GIB = 1024**3

# Un disque plus petit ne reçoit pas d'installation : la même borne que
# l'installateur du live applique à son choix automatique.
MIN_DISK_BYTES = 20 * GIB

# Le transport que lsblk donne aux disques branchés en USB.
TRANSPORT_USB = "usb"

# La swap demandée « ram » est plafonnée au quart du disque cible : au-delà
# elle mange la racine d'un petit disque. Plafonnée, elle ne contient plus
# toute la mémoire, et l'hibernation est coupée.
SWAP_DISK_DIVISOR = 4

REPO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profiles")
EXTENSION = ".json"

KERNELS = ("linux", "linux-lts", "linux-zen", "linux-hardened")
LAYOUTS = ("plain", "lvm_on_luks")

# Un nom de clé qui correspond est refusé, à toute profondeur. secret_lv
# nomme un volume logique, pas un secret : il est la seule exception.
SECRET_KEY_RE = re.compile(r"pass|secret_key|hash|enc_password", re.I)
SECRET_KEYS_ALLOWED = frozenset({"secret_lv"})
# La forme d'un hash crypt(3) : « $1$ », « $5$ », « $6$ », « $y$ »,
# « $2b$ », « $argon2id$ »…
SECRET_VALUE_RE = re.compile(r"^\$(1|2[aby]?|5|6|7|y|gy|argon2(id|i|d)?)\$")

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
DEVICE_RE = re.compile(r"^/dev/[A-Za-z0-9/._:-]+$")
KEYMAP_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,31}$")
COUNTRY_RE = re.compile(r"^[A-Za-z][A-Za-z .'-]{1,47}$")
TIMEZONE_RE = re.compile(r"^(UTC|[A-Z][A-Za-z_+-]*(/[A-Za-z0-9_+-]+){1,2})$")
LOCALE_RE = re.compile(
    r"^([a-z]{2,3}(_[A-Z]{2})?|C)\.[A-Za-z0-9-]+(@[a-z]+)?$"
)
PACKAGE_RE = re.compile(r"^[a-z0-9@_+][a-z0-9@._+-]{0,99}$")
UNIT_RE = re.compile(r"^[A-Za-z0-9@_.:-]{1,128}$")
VG_RE = re.compile(r"^[A-Za-z0-9_+][A-Za-z0-9_.+-]{0,63}$")
USER_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
HOST_LABEL_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
# La grammaire de zram-generator que resolve() sait aussi évaluer : un
# nombre de MiB, « ram / N », ou « min(ram / N, M) ».
ZRAM_RE = re.compile(
    r"^\s*(?:(?P<mib>\d+)|ram\s*/\s*(?P<div>\d+)"
    r"|min\(\s*ram\s*/\s*(?P<mdiv>\d+)\s*,\s*(?P<max>\d+)\s*\))\s*$"
)

# Comptes que le système possède déjà : les choisir pour l'utilisateur
# casserait useradd ou le paquet qui les crée.
RESERVED_USERS = frozenset(
    {
        "root",
        "bin",
        "daemon",
        "mail",
        "ftp",
        "http",
        "nobody",
        "dbus",
        "polkitd",
        "avahi",
        "colord",
        "gdm",
        "git",
        "rtkit",
        "systemd-network",
        "systemd-resolve",
        "systemd-timesync",
        "uuidd",
    }
)

DEFAULTS = {
    "schema": SCHEMA_VERSION,
    "name": "generic",
    "extends": None,
    "erplibre": {"profile": "odoo18"},
    "live": {"keymap": ASK, "mirrors_country": AUTO},
    "disk": {
        "target": AUTO,
        "nvme_lba_4k": AUTO,
        "layout": "plain",
        "esp_mib": 1024,
        "luks": {"sector_size": AUTO, "iter_time_ms": 2000, "discards": AUTO},
        "lvm": {
            "vg": "vg0",
            "swap": "ram",
            "secret_lv": None,
            "root_fs": "ext4",
            "vg_free_mib": 1024,
        },
    },
    "system": {
        "kernels": ["linux"],
        "kernel_headers": False,
        "dkms": False,
        "microcode": AUTO,
        "hostname": "erplibre",
        "timezone": ASK,
        "locales": ["en_US.UTF-8"],
        "lang": "en_US.UTF-8",
        "lc_collate": None,
        "console_keymap": ASK,
        "zram": {
            "enabled": True,
            "size": "min(ram / 4, 32768)",
            "algorithm": "zstd",
            "sysctl_tuning": False,
        },
        "e2scrub": False,
        "services": ["NetworkManager", "fstrim.timer"],
        "extra_packages": [],
    },
    "boot": {
        "loader": AUTO,
        "timeout": 3,
        "editor": False,
        "uki": False,
        "hibernation": AUTO,
    },
    "user": {"name": ASK, "shell": "bash", "sudo": True},
    "desktop": {
        "env": "gnome",
        "extra": False,
        "apps": [],
        "printing": True,
        "power": AUTO,
    },
    "gpu": {"driver": AUTO},
    "firstboot": {"aur_helper": None, "makepkg_native": False},
    "security": {
        "apparmor": False,
        "header_backup": ASK,
        "recovery_key_to_key": False,
    },
}

# Les sections que le menu édite, dans l'ordre où il les propose.
SECTIONS = (
    "erplibre",
    "live",
    "disk",
    "system",
    "boot",
    "user",
    "desktop",
    "gpu",
    "firstboot",
    "security",
)

# Paquets par pilote graphique. mesa sert AMD et Intel ; « nouveau » est le
# pilote libre des cartes NVIDIA, qu'auto retient pour toute carte NVIDIA.
GPU_PACKAGES = {
    "amd": ("mesa", "vulkan-radeon"),
    "intel": ("mesa", "vulkan-intel", "intel-media-driver"),
    "nouveau": ("mesa", "vulkan-nouveau"),
    "nvidia-open": ("nvidia-open-dkms", "nvidia-utils"),
    "mesa": ("mesa",),
}

# La plateforme de grub-install selon le micrologiciel de la cible.
GRUB_TARGETS = {
    "uefi64": "x86_64-efi",
    "uefi32": "i386-efi",
    "bios": "i386-pc",
}

POWER_PACKAGES = {
    "tlp": ("tlp", "tlp-rdw"),
    "power-profiles-daemon": ("power-profiles-daemon",),
    "none": (),
}
POWER_SERVICES = {"tlp": ("tlp.service",)}

SHELL_PACKAGES = {"zsh": ("zsh",), "fish": ("fish",)}

# Les libellés de plan_summary(), clés de traduction stables : l'appelant
# les passe à sa fonction de traduction. Les valeurs « yes », « no »,
# « ask », « auto » et « none » sont aussi des jetons à traduire ; les
# autres sont des données.
SUMMARY_LABELS = (
    "Profile",
    "Target disk",
    "Disk layout",
    "LUKS sector size",
    "TRIM (discards)",
    "Swap",
    "Hibernation",
    "Secret volume",
    "Boot loader",
    "Kernels",
    "Microcode",
    "Host name",
    "User",
    "Shell",
    "Time zone",
    "Locales",
    "Keyboard",
    "Desktop",
    "GPU driver",
    "Power management",
    "zram",
    "AppArmor",
    "Extra packages",
    "Services",
)
SUMMARY_TOKENS = ("yes", "no", ASK, AUTO, "none")


class ProfileError(Exception):
    """Un profil illisible ou une chaîne « extends » qui ne se résout pas.
    `code` est stable, `details` porte les valeurs de la phrase."""

    def __init__(self, code, **details):
        super().__init__(code)
        self.code = code
        self.details = details


# Vérificateurs : chacun prend la valeur et rend une liste de
# (code, détails). Le parcours ajoute « path » et « value » aux détails.


def _bool(valeur):
    if not isinstance(valeur, bool):
        return [("type", {"expected": "boolean"})]
    return []


def _int(minimum):
    def verifier(valeur):
        if isinstance(valeur, bool) or not isinstance(valeur, int):
            return [("type", {"expected": "integer"})]
        if valeur < minimum:
            return [("size", {"minimum": minimum})]
        return []

    return verifier


def _choice(*choix):
    """Une valeur parmi `choix`, type compris : 0 n'est pas False."""

    def verifier(valeur):
        for c in choix:
            if type(c) is type(valeur) and c == valeur:
                return []
        return [("choice", {"allowed": ", ".join(map(display_value, choix))})]

    return verifier


def _pattern(motif, code):
    def verifier(valeur):
        if not isinstance(valeur, str):
            return [("type", {"expected": "string"})]
        if not motif.match(valeur):
            return [(code, {})]
        return []

    return verifier


def _nullable(autre):
    def verifier(valeur):
        return [] if valeur is None else autre(valeur)

    return verifier


def _list(element, vide_permis=True):
    def verifier(valeur):
        if not isinstance(valeur, list):
            return [("type", {"expected": "list"})]
        if not valeur and not vide_permis:
            return [("empty", {})]
        erreurs = []
        for item in valeur:
            if isinstance(item, str) and item in (AUTO, ASK):
                # « auto » et « ask » valent pour un champ entier, jamais
                # pour un élément : le motif d'un paquet les accepterait.
                erreurs.append(("special", {"item": item}))
                continue
            for code, det in element(item):
                erreurs.append((code, dict(det, item=display_value(item))))
        return erreurs

    return verifier


def _hostname(valeur):
    if not isinstance(valeur, str):
        return [("type", {"expected": "string"})]
    if len(valeur) > 253 or not all(
        HOST_LABEL_RE.match(e) for e in valeur.split(".")
    ):
        return [("hostname", {})]
    return []


def _user_name(valeur):
    if not isinstance(valeur, str):
        return [("type", {"expected": "string"})]
    if not USER_RE.match(valeur) or valeur in RESERVED_USERS:
        return [("user-name", {})]
    return []


def _kernels(valeur):
    if not isinstance(valeur, list) or not all(
        isinstance(k, str) for k in valeur
    ):
        return [("type", {"expected": "list"})]
    if not valeur or len(set(valeur)) != len(valeur):
        return [("kernels", {"allowed": ", ".join(KERNELS)})]
    if any(k not in KERNELS for k in valeur):
        return [("kernels", {"allowed": ", ".join(KERNELS)})]
    return []


def _swap(valeur):
    if valeur in ("ram", "none"):
        return []
    if isinstance(valeur, bool) or not isinstance(valeur, int):
        return [("choice", {"allowed": "ram, none, GiB"})]
    if valeur < 1:
        return [("size", {"minimum": 1})]
    return []


def _zram_size(valeur):
    if not isinstance(valeur, str) or not ZRAM_RE.match(valeur):
        return [("zram-size", {})]
    return []


# path → (vérificateur, valeurs spéciales permises, sorte de saisie). La
# sorte dit au menu comment lire une réponse tapée : voir parse_value().
FIELDS = {
    "erplibre.profile": (_pattern(NAME_RE, "name"), {ASK}, "str"),
    "live.keymap": (_pattern(KEYMAP_RE, "keymap"), {ASK}, "str"),
    "live.mirrors_country": (_pattern(COUNTRY_RE, "country"), {AUTO}, "str"),
    "disk.target": (_pattern(DEVICE_RE, "device"), {AUTO, ASK}, "str"),
    "disk.nvme_lba_4k": (_choice(False), {AUTO}, "bool"),
    "disk.layout": (_choice(*LAYOUTS), {ASK}, "str"),
    "disk.esp_mib": (_int(256), set(), "int"),
    "disk.luks.sector_size": (_choice(512, 4096), {AUTO}, "int"),
    "disk.luks.iter_time_ms": (_int(1), set(), "int"),
    "disk.luks.discards": (_bool, {AUTO}, "bool"),
    "disk.lvm.vg": (_pattern(VG_RE, "name"), set(), "str"),
    "disk.lvm.swap": (_swap, set(), "scalar"),
    "disk.lvm.secret_lv": (None, set(), "secret_lv"),
    "disk.lvm.secret_lv.size_gib": (_int(1), set(), "int"),
    "disk.lvm.secret_lv.optional": (_bool, set(), "bool"),
    "disk.lvm.root_fs": (_choice("ext4", "xfs"), set(), "str"),
    "disk.lvm.vg_free_mib": (_int(0), set(), "int"),
    "system.kernels": (_kernels, set(), "list"),
    "system.kernel_headers": (_bool, set(), "bool"),
    "system.dkms": (_bool, set(), "bool"),
    "system.microcode": (
        _choice("none", "amd-ucode", "intel-ucode"),
        {AUTO},
        "str",
    ),
    "system.hostname": (_hostname, {ASK}, "str"),
    "system.timezone": (_pattern(TIMEZONE_RE, "timezone"), {ASK}, "str"),
    "system.locales": (
        _list(_pattern(LOCALE_RE, "locale"), vide_permis=False),
        {ASK},
        "list",
    ),
    "system.lang": (_pattern(LOCALE_RE, "locale"), {ASK}, "str"),
    "system.lc_collate": (
        _nullable(_pattern(re.compile(r"^C$|" + LOCALE_RE.pattern), "locale")),
        set(),
        "nullable",
    ),
    "system.console_keymap": (_pattern(KEYMAP_RE, "keymap"), {ASK}, "str"),
    "system.zram.enabled": (_bool, set(), "bool"),
    "system.zram.size": (_zram_size, set(), "str"),
    "system.zram.algorithm": (
        _choice("zstd", "lz4", "lzo-rle", "lzo"),
        set(),
        "str",
    ),
    "system.zram.sysctl_tuning": (_bool, set(), "bool"),
    "system.e2scrub": (_bool, set(), "bool"),
    "system.services": (_list(_pattern(UNIT_RE, "service")), set(), "list"),
    "system.extra_packages": (
        _list(_pattern(PACKAGE_RE, "package")),
        set(),
        "list",
    ),
    "boot.loader": (_choice("systemd-boot", "grub"), {AUTO}, "str"),
    "boot.timeout": (_int(0), set(), "int"),
    "boot.editor": (_bool, set(), "bool"),
    "boot.uki": (_bool, set(), "bool"),
    "boot.hibernation": (_bool, {AUTO}, "bool"),
    "user.name": (_user_name, {ASK}, "str"),
    "user.shell": (_choice("bash", "zsh", "fish"), set(), "str"),
    "user.sudo": (_bool, set(), "bool"),
    "desktop.env": (_choice("gnome", "none"), set(), "str"),
    "desktop.extra": (_bool, set(), "bool"),
    "desktop.apps": (_list(_pattern(PACKAGE_RE, "package")), set(), "list"),
    "desktop.printing": (_bool, set(), "bool"),
    "desktop.power": (
        _choice("tlp", "power-profiles-daemon", "none"),
        {AUTO},
        "str",
    ),
    "gpu.driver": (_choice("mesa", "nouveau", "nvidia-open"), {AUTO}, "str"),
    "firstboot.aur_helper": (
        _nullable(_choice("yay", "paru")),
        set(),
        "nullable",
    ),
    "firstboot.makepkg_native": (_bool, set(), "bool"),
    "security.apparmor": (_bool, set(), "bool"),
    "security.header_backup": (_bool, {ASK}, "bool"),
    "security.recovery_key_to_key": (_bool, set(), "bool"),
}

# Les champs qui sont des objets : le parcours descend dedans. secret_lv
# vaut null (pas de volume secret) ou un objet.
OBJECTS = frozenset(
    {
        "erplibre",
        "live",
        "disk",
        "disk.luks",
        "disk.lvm",
        "disk.lvm.secret_lv",
        "system",
        "system.zram",
        "boot",
        "user",
        "desktop",
        "gpu",
        "firstboot",
        "security",
    }
)
TOP_LEVEL = frozenset({"schema", "name", "extends"})


def display_value(valeur):
    """Une valeur pour l'affichage : telle quelle pour une chaîne, en JSON
    pour le reste (listes, booléens, null)."""
    if isinstance(valeur, str):
        return valeur
    return json.dumps(valeur, ensure_ascii=False)


# Chargement et fusion


def slug(name):
    """Un nom de fichier sûr tiré de `name` : minuscules, chiffres et
    tirets, 48 caractères au plus ; « machine » si rien ne reste. Le nom
    finit dans un chemin : « ../ » n'y arrive pas."""
    propre = re.sub(r"[^a-z0-9]+", "-", str(name or "").lower()).strip("-")
    return propre[:48].strip("-") or "machine"


def load(path):
    """Le dict JSON du fichier `path`. ProfileError « json » s'il est
    illisible, « not-object » s'il n'est pas un objet."""
    try:
        with open(path, encoding="utf-8") as fh:
            donnees = json.load(fh)
    except (OSError, ValueError) as exc:
        raise ProfileError("json", path=path, error=str(exc)) from exc
    if not isinstance(donnees, dict):
        raise ProfileError("not-object", path=path)
    return donnees


def dump(profile):
    """Le JSON canonique d'un profil : clés triées, indentation 2, fin de
    ligne finale. Deux profils égaux donnent le même texte, donc la même
    empreinte."""
    return (
        json.dumps(profile, sort_keys=True, indent=2, ensure_ascii=False)
        + "\n"
    )


def merge(base, override):
    """Une copie de `base` où chaque clé de `override` remplace la sienne ;
    deux dicts se fusionnent récursivement, tout le reste (listes, null
    compris) se remplace. Ni `base` ni `override` ne sont modifiés."""
    resultat = copy.deepcopy(base)
    for cle, valeur in (override or {}).items():
        if isinstance(valeur, dict) and isinstance(resultat.get(cle), dict):
            resultat[cle] = merge(resultat[cle], valeur)
        else:
            resultat[cle] = copy.deepcopy(valeur)
    return resultat


def find(name, dirs):
    """Le chemin du profil `name` : <slug>.json dans le dernier dossier de
    `dirs` qui le contient, ou None. Le dernier gagne : un profil privé
    du même nom masque celui du dépôt."""
    trouve = None
    for dossier in dirs:
        chemin = os.path.join(dossier, slug(name) + EXTENSION)
        if os.path.isfile(chemin):
            trouve = chemin
    return trouve


def effective(profile, dirs):
    """Le profil complet : DEFAULTS, puis chaque ancêtre nommé par
    « extends » cherché dans `dirs`, puis `profile`. Le résultat porte le
    nom de `profile` et « extends » à null, car tout y est déjà.

    ProfileError « extends-missing » si un ancêtre n'existe pas,
    « extends-cycle » si la chaîne revient sur un nom déjà vu.
    """
    couches = [profile]
    vus = [profile.get("name")]
    courant = profile
    while courant.get("extends"):
        nom = courant["extends"]
        if not isinstance(nom, str):
            raise ProfileError("extends-missing", name=display_value(nom))
        if nom in vus:
            raise ProfileError(
                "extends-cycle", chain=" → ".join(map(str, [*vus, nom]))
            )
        chemin = find(nom, dirs)
        if chemin is None:
            raise ProfileError("extends-missing", name=nom)
        courant = load(chemin)
        vus.append(nom)
        couches.append(courant)
    resultat = copy.deepcopy(DEFAULTS)
    for couche in reversed(couches):
        resultat = merge(resultat, couche)
    resultat["name"] = profile.get("name", resultat["name"])
    resultat["extends"] = None
    return resultat


def list_profiles(dirs):
    """Chaque fichier .json de `dirs`, dans l'ordre des dossiers puis des
    noms : {"name", "path", "dir", "raw", "effective", "errors"}. Un
    fichier illisible a raw et effective à None et son erreur dans
    errors ; un profil lisible y a les codes de validate()."""
    entrees = []
    for index, dossier in enumerate(dirs):
        try:
            noms = sorted(os.listdir(dossier))
        except OSError:
            continue
        for fichier in noms:
            if not fichier.endswith(EXTENSION):
                continue
            chemin = os.path.join(dossier, fichier)
            entree = {
                "name": fichier[: -len(EXTENSION)],
                "path": chemin,
                "dir": index,
                "raw": None,
                "effective": None,
                "errors": [],
            }
            try:
                brut = load(chemin)
                entree["raw"] = brut
                entree["name"] = str(brut.get("name") or entree["name"])
                complet = effective(brut, dirs)
                entree["effective"] = complet
                entree["errors"] = validate(brut) + validate(complet)
            except ProfileError as exc:
                entree["errors"].append((exc.code, exc.details))
            entree["errors"] = _uniques(entree["errors"])
            entrees.append(entree)
    return entrees


def _uniques(erreurs):
    vus, resultat = set(), []
    for code, det in erreurs:
        cle = (code, json.dumps(det, sort_keys=True, default=str))
        if cle not in vus:
            vus.add(cle)
            resultat.append((code, det))
    return resultat


# Validation


def _secrets(donnees, prefixe=""):
    """Les chemins des clés et des valeurs qui ressemblent à un secret, à
    toute profondeur, connues du schéma ou non."""
    trouves = []
    if isinstance(donnees, dict):
        for cle, valeur in donnees.items():
            chemin = f"{prefixe}{cle}"
            if (
                SECRET_KEY_RE.search(str(cle))
                and str(cle) not in SECRET_KEYS_ALLOWED
            ):
                trouves.append(chemin)
                continue
            trouves.extend(_secrets(valeur, chemin + "."))
    elif isinstance(donnees, list):
        for i, valeur in enumerate(donnees):
            trouves.extend(_secrets(valeur, f"{prefixe}{i}."))
    elif isinstance(donnees, str) and SECRET_VALUE_RE.match(donnees):
        trouves.append(prefixe.rstrip("."))
    return trouves


def validate(profile):
    """La liste des (code, détails) d'un profil ; vide s'il est valide.

    Un profil partiel est permis : un champ absent prendra la valeur de
    son ancêtre ou de DEFAULTS, seul ce qui est écrit est vérifié. Les
    détails portent toujours « path ». Codes : not-object, secret,
    unknown-key, schema, name, type, choice, size, empty, special,
    hostname, user-name, locale, keymap, country, timezone, device,
    package, service, kernels, zram-size, required,
    lang-not-in-locales, hibernation-without-swap, secret-lv-needs-luks.
    """
    if not isinstance(profile, dict):
        return [("not-object", {"path": ""})]
    erreurs = [("secret", {"path": p}) for p in _secrets(profile)]
    secrets = {d["path"] for _c, d in erreurs}
    if "schema" in profile and profile["schema"] != SCHEMA_VERSION:
        erreurs.append(
            (
                "schema",
                {
                    "path": "schema",
                    "value": display_value(profile["schema"]),
                    "expected": SCHEMA_VERSION,
                },
            )
        )
    if "name" in profile:
        erreurs += _verifier(
            "name", profile["name"], _pattern(NAME_RE, "name")
        )
    if profile.get("extends") is not None:
        erreurs += _verifier(
            "extends", profile["extends"], _pattern(NAME_RE, "name")
        )
    for cle, valeur in profile.items():
        if cle in TOP_LEVEL or cle in secrets:
            continue
        erreurs += _parcourir(cle, valeur, secrets)
    erreurs += _croisees(profile)
    return erreurs


def _verifier(chemin, valeur, verificateur, speciaux=()):
    if isinstance(valeur, str) and valeur in (AUTO, ASK):
        if valeur in speciaux:
            return []
        return [("special", {"path": chemin, "value": valeur})]
    return [
        (code, dict(det, path=chemin, value=display_value(valeur)))
        for code, det in verificateur(valeur)
    ]


def _parcourir(chemin, valeur, secrets):
    if chemin in secrets:
        return []
    if chemin in OBJECTS:
        if valeur is None and chemin == "disk.lvm.secret_lv":
            return []
        if not isinstance(valeur, dict):
            return [
                (
                    "type",
                    {
                        "path": chemin,
                        "value": display_value(valeur),
                        "expected": "object",
                    },
                )
            ]
        erreurs = []
        for cle, sous in valeur.items():
            erreurs += _parcourir(f"{chemin}.{cle}", sous, secrets)
        return erreurs
    if chemin not in FIELDS:
        return [("unknown-key", {"path": chemin})]
    verificateur, speciaux, _sorte = FIELDS[chemin]
    return _verifier(chemin, valeur, verificateur, speciaux)


def _croisees(profile):
    """Les règles qui lient deux champs, vérifiées quand les deux sont
    écrits. La taille du volume secret n'est exigée que d'un profil sans
    « extends » : un profil qui en étend un autre peut la recevoir de son
    ancêtre, et effective() rend un profil sans « extends » que validate()
    vérifie alors en entier."""
    erreurs = []
    systeme = profile.get("system")
    if isinstance(systeme, dict):
        locales, lang = systeme.get("locales"), systeme.get("lang")
        if (
            isinstance(locales, list)
            and isinstance(lang, str)
            and lang != ASK
            and lang not in locales
        ):
            erreurs.append(
                ("lang-not-in-locales", {"path": "system.lang", "value": lang})
            )
    disque = profile.get("disk")
    boot = profile.get("boot")
    if isinstance(disque, dict) and isinstance(boot, dict):
        lvm = disque.get("lvm") if isinstance(disque.get("lvm"), dict) else {}
        # La disposition plain n'a pas de volume de swap.
        if boot.get("hibernation") is True and (
            lvm.get("swap") == "none" or disque.get("layout") == "plain"
        ):
            erreurs.append(
                ("hibernation-without-swap", {"path": "boot.hibernation"})
            )
    if isinstance(disque, dict):
        lvm = disque.get("lvm") if isinstance(disque.get("lvm"), dict) else {}
        secret = lvm.get("secret_lv")
        if isinstance(secret, dict):
            if "size_gib" not in secret and profile.get("extends") is None:
                erreurs.append(
                    ("required", {"path": "disk.lvm.secret_lv.size_gib"})
                )
            if disque.get("layout") == "plain":
                erreurs.append(
                    ("secret-lv-needs-luks", {"path": "disk.lvm.secret_lv"})
                )
    return erreurs


# Édition


def get(profile, path, default=None):
    """La valeur au chemin pointé `path`, ou `default`."""
    courant = profile
    for morceau in path.split("."):
        if not isinstance(courant, dict) or morceau not in courant:
            return default
        courant = courant[morceau]
    return courant


def put(profile, path, value):
    """Écrit `value` au chemin pointé `path` dans `profile`, en créant les
    objets intermédiaires ; rend `profile`."""
    morceaux = path.split(".")
    courant = profile
    for morceau in morceaux[:-1]:
        if not isinstance(courant.get(morceau), dict):
            courant[morceau] = {}
        courant = courant[morceau]
    courant[morceaux[-1]] = value
    return profile


def section_fields(section):
    """Les chemins éditables d'une section, dans l'ordre de FIELDS. Les
    sous-champs de secret_lv n'y sont pas : le volume secret se saisit
    d'un bloc (voir parse_value)."""
    return [
        p
        for p in FIELDS
        if p.split(".")[0] == section
        and not p.startswith("disk.lvm.secret_lv.")
    ]


_OUI = {"yes", "y", "true", "1", "oui", "o"}
_NON = {"no", "n", "false", "0", "non"}


def parse_value(path, text):
    """La valeur que représente `text`, tapé pour le champ `path`.

    « auto » et « ask » restent des chaînes : validate() dit si le champ
    les accepte. « null » vide un champ qui le permet. Un booléen se tape
    oui/non (yes/no, o/n, 1/0), une liste se sépare par des virgules (« []
    » pour la vider), secret_lv se tape comme sa taille en GiB (le volume
    est alors facultatif à l'installation). ValueError si `text` ne se lit
    pas dans la sorte du champ.
    """
    s = text.strip()
    if s.lower() in (AUTO, ASK):
        return s.lower()
    sorte = FIELDS[path][2] if path in FIELDS else "str"
    if s.lower() == "null" and sorte in ("nullable", "secret_lv"):
        return None
    if sorte == "bool":
        if s.lower() in _OUI:
            return True
        if s.lower() in _NON:
            return False
        raise ValueError(s)
    if sorte == "int":
        return int(s)
    if sorte == "scalar":
        return int(s) if s.isdigit() else s
    if sorte == "list":
        if s == "[]":
            return []
        return [x.strip() for x in s.split(",") if x.strip()]
    if sorte == "secret_lv":
        return {"size_gib": int(s), "optional": True}
    return s


# Résolution


def _ram_gib(ram_mib):
    return math.ceil(ram_mib / 1024) if ram_mib else 0


def zram_mib(expression, ram_mib):
    """La taille en MiB que zram-generator tire de `expression` pour
    `ram_mib` de mémoire ; None si l'expression sort de ZRAM_RE."""
    m = ZRAM_RE.match(expression or "")
    if not m:
        return None
    if m.group("mib"):
        return int(m.group("mib"))
    if m.group("div"):
        return ram_mib // max(1, int(m.group("div")))
    return min(ram_mib // max(1, int(m.group("mdiv"))), int(m.group("max")))


def _candidats(facts):
    """Les disques qui peuvent recevoir l'installation : ni amovibles, ni
    branchés en USB, ni support de démarrage, ni en lecture seule, ni trop
    petits. Un boîtier USB annonce souvent RM=0 : seul le transport le
    distingue d'un disque interne, et c'est souvent le disque de
    sauvegarde."""
    return [
        d
        for d in facts.get("disks") or []
        if not d.get("removable")
        and d.get("tran") != TRANSPORT_USB
        and not d.get("boot_medium")
        and not d.get("ro")
        and (d.get("size") or 0) >= MIN_DISK_BYTES
    ]


def _disque_cible(p, facts, answers, questions, alertes):
    """Le disque retenu (fiche de facts) ou None, écrit dans disk.target.

    « auto » sans candidat devient une question : la réponse est lue dans
    `answers` au même titre qu'un « ask », sans quoi la cible reste null
    et la question revient à chaque appel. Avec des candidats, une
    réponse valide l'emporte sur le plus grand : c'est le choix fait à
    l'écran quand plusieurs disques conviennent. Un disque nommé, par le
    profil ou par la réponse, est cherché parmi tous les disques, et une
    mise en garde dit s'il est absent, s'il est le support de démarrage ou
    s'il est branché en USB.

    Sur un live dont le support de démarrage n'est pas reconnu
    (facts["boot_medium_unknown"]), « auto » ne retient aucun disque de
    lui-même : le support pourrait passer pour un disque fixe. La mise en
    garde « boot-medium-unknown » s'ajoute, et seule une réponse
    « disk.target » désigne le disque."""
    cible = get(p, "disk.target")
    disques = facts.get("disks") or []
    if cible == AUTO:
        candidats = _candidats(facts)
        if facts.get("boot_medium_unknown"):
            alertes.append({"code": "boot-medium-unknown"})
        if (
            candidats
            and "disk.target" not in answers
            and not facts.get("boot_medium_unknown")
        ):
            disque = max(candidats, key=lambda d: d.get("size") or 0)
            put(p, "disk.target", disque["path"])
            return disque
        if not candidats:
            alertes.append({"code": "no-disk"})
        if not _repondre(p, "disk.target", answers, alertes):
            put(p, "disk.target", None)
            questions.append("disk.target")
            return None
        cible = get(p, "disk.target")
    if cible in (ASK, None):
        return None
    disque = next((d for d in disques if d.get("path") == cible), None)
    if disque is None:
        alertes.append({"code": "disk-not-found", "device": cible})
    elif disque.get("boot_medium"):
        alertes.append({"code": "disk-is-boot-medium", "device": cible})
    elif disque.get("tran") == TRANSPORT_USB:
        alertes.append({"code": "disk-is-usb", "device": cible})
    return disque


def _repondre(p, chemin, answers, alertes):
    """Écrit dans `p` la réponse de `answers` au champ `chemin` si elle
    passe le vérificateur du champ ; rend vrai alors. Une réponse ne peut
    valoir ni « auto » ni « ask ». Refusée, elle laisse le champ tel quel
    et ajoute une mise en garde « answer-invalid » : la question reste
    posée."""
    verificateur = FIELDS[chemin][0]
    if chemin not in answers or verificateur is None:
        return False
    valeur = answers[chemin]
    erreurs = _verifier(chemin, valeur, verificateur)
    if erreurs:
        alertes.append(
            {
                "code": "answer-invalid",
                "path": chemin,
                "value": display_value(valeur),
                "reason": erreurs[0][0],
            }
        )
        return False
    put(p, chemin, valeur)
    return True


def _secteur_4k(disque):
    if not disque:
        return False
    if 4096 in (disque.get("log_sec"), disque.get("phy_sec")):
        return True
    nvme = disque.get("nvme") or {}
    courant = next(
        (
            f
            for f in nvme.get("formats") or []
            if f.get("id") == nvme.get("current")
        ),
        None,
    )
    return bool(courant and courant.get("ds") == 12)


def _nvme_voisins(disque, facts):
    """Les autres espaces de noms NVMe du sous-système de `disque`
    (« nvme0n2 » à côté de « nvme0n1 »), parmi les disques de `facts`."""
    m = re.match(r"^(nvme\d+)n\d+$", str((disque or {}).get("name") or ""))
    if not m:
        return []
    return [
        d["name"]
        for d in facts.get("disks") or []
        if d.get("name") != disque["name"]
        and re.match(rf"^{m.group(1)}n\d+$", str(d.get("name") or ""))
    ]


def _format_nvme_4k(disque):
    """L'indice du format 4 KiB (ds 12) le plus performant (rp le plus
    bas) d'un espace de noms NVMe formaté en 512 o, ou False."""
    nvme = (disque or {}).get("nvme") or {}
    formats = nvme.get("formats") or []
    courant = next(
        (f for f in formats if f.get("id") == nvme.get("current")), None
    )
    if not courant or courant.get("ds") != 9:
        return False
    quatre_k = [f for f in formats if f.get("ds") == 12 and not f.get("ms")]
    if not quatre_k:
        return False
    return min(quatre_k, key=lambda f: (f.get("rp", 99), f["id"]))["id"]


def _unique(elements):
    vus, resultat = set(), []
    for e in elements:
        if e and e not in vus:
            vus.add(e)
            resultat.append(e)
    return resultat


def resolve(profile, facts, answers=None):
    """(settings, questions) : `profile` appliqué aux faits du matériel.

    Chaque « ask » prend sa valeur dans `answers` (chemin pointé → valeur)
    s'il y est et que le vérificateur du champ l'accepte ; sinon il reste
    « ask » et son chemin entre dans `questions`, avec une mise en garde
    « answer-invalid » si une réponse a été refusée. Un volume secret
    « optional » d'une disposition chiffrée est une question aussi : sa
    réponse vraie le crée, fausse le retire. Chaque « auto » devient une
    valeur concrète :

    - microcode : amd-ucode ou intel-ucode selon le fabricant du
      processeur, « none » sous un hyperviseur ;
    - chargeur : systemd-boot en UEFI 64 bits, GRUB sinon ; derived
      porte la cible de GRUB (x86_64-efi, i386-efi ou i386-pc), et l'UEFI
      32 bits donne une mise en garde ;
    - disque : le plus grand disque fixe, interne (pas en USB), qui n'est
      pas le support de démarrage ; aucun, ou un live dont le support
      n'est pas reconnu → question « disk.target », à laquelle `answers`
      répond comme à un « ask ». Une réponse « disk.target » donnée
      l'emporte aussi sur le plus grand ;
    - secteur LUKS : 4096 si le disque annonce des secteurs logiques ou
      physiques de 4 KiB, ou un format NVMe 4 KiB en service ; 512 sinon ;
    - discards : vrai sur un disque non rotatif dont la granularité de
      TRIM est non nulle ;
    - format NVMe 4 KiB : l'indice à PROPOSER (jamais appliqué sans
      confirmation), ou false, et false aussi quand d'autres espaces de
      noms partagent le contrôleur ;
    - swap « ram » : MemTotal arrondie au GiB supérieur, plafonnée au
      quart du disque, ce qui coupe alors l'hibernation ; mémoire
      inconnue → pas de volume de swap, avec une mise en garde ;
    - hibernation : vraie si la swap contient toute la mémoire ;
    - énergie : TLP sur un portable, power-profiles-daemon sinon ;
    - pilote graphique : « nouveau » dès qu'une carte NVIDIA est là,
      mesa sinon ; les paquets suivent chaque fabricant présent ;
    - miroirs : null, c'est-à-dire sans filtre de pays.

    La disposition plain garde la disposition native d'archinstall, qui
    n'a pas de volume de swap : swap 0 et hibernation coupée, quoi que
    dise disk.lvm. Une swap en GiB écrite en clair n'est jamais plafonnée,
    mais plus du quart du disque donne une mise en garde.

    Un disque inconnu (« ask » sans réponse) laisse les valeurs qui en
    dépendent à leur repli prudent (512, sans discards, swap non
    plafonnée) ; l'installateur rappelle resolve() avec la réponse.

    settings est le profil complet ainsi résolu, plus « derived »
    (paquets, services, disque retenu, tailles calculées, swap_gib 0 pour
    « pas de volume de swap ») et « warnings » (liste de {"code", ...}).
    """
    p = merge(DEFAULTS, profile)
    facts = facts or {}
    answers = answers or {}
    questions = []
    alertes = []
    for chemin in FIELDS:
        if get(p, chemin) == ASK and not _repondre(
            p, chemin, answers, alertes
        ):
            questions.append(chemin)
    secret = get(p, "disk.lvm.secret_lv")
    if (
        isinstance(secret, dict)
        and secret.get("optional")
        and get(p, "disk.layout") == "lvm_on_luks"
    ):
        if "disk.lvm.secret_lv" in answers:
            put(
                p,
                "disk.lvm.secret_lv",
                dict(secret, optional=False)
                if answers["disk.lvm.secret_lv"]
                else None,
            )
        else:
            questions.append("disk.lvm.secret_lv")
    disque = _disque_cible(p, facts, answers, questions, alertes)
    if disque is None and get(p, "disk.target") is not None:
        alertes.append({"code": "disk-unknown"})

    if get(p, "disk.luks.sector_size") == AUTO:
        put(p, "disk.luks.sector_size", 4096 if _secteur_4k(disque) else 512)
    if get(p, "disk.luks.discards") == AUTO:
        put(
            p,
            "disk.luks.discards",
            bool(
                disque
                and not disque.get("rotational")
                and (disque.get("disc_gran") or 0) > 0
            ),
        )
    if get(p, "disk.nvme_lba_4k") == AUTO:
        indice = _format_nvme_4k(disque)
        # Un formatage peut s'appliquer à tout le contrôleur : jamais
        # proposé quand un autre espace de noms y est visible.
        if indice is not False and _nvme_voisins(disque, facts):
            alertes.append(
                {"code": "nvme-format-shared", "device": disque["path"]}
            )
            indice = False
        put(p, "disk.nvme_lba_4k", indice)

    ram_mib = facts.get("ram_mib") or 0
    swap = get(p, "disk.lvm.swap")
    plafonnee = False
    chiffre = get(p, "disk.layout") == "lvm_on_luks"
    if not chiffre:
        swap_gib = 0
    elif swap == "ram" and not ram_mib:
        alertes.append({"code": "ram-unknown"})
        swap_gib = 0
    elif swap == "ram":
        swap_gib = _ram_gib(ram_mib)
        if disque and swap_gib * GIB > disque["size"] / SWAP_DISK_DIVISOR:
            plafond = max(1, int(disque["size"] // SWAP_DISK_DIVISOR // GIB))
            alertes.append(
                {
                    "code": "swap-capped",
                    "requested": swap_gib,
                    "capped": plafond,
                }
            )
            swap_gib, plafonnee = plafond, True
    elif swap == "none":
        swap_gib = 0
    else:
        swap_gib = swap
        if disque and swap_gib * GIB > disque["size"] / SWAP_DISK_DIVISOR:
            alertes.append(
                {
                    "code": "swap-large",
                    "swap": swap_gib,
                    "disk": disque["size"] // GIB,
                }
            )
    put(p, "disk.lvm.swap", swap_gib)

    hibernation = get(p, "boot.hibernation")
    contient = bool(ram_mib) and swap_gib * 1024 >= ram_mib
    if hibernation == AUTO:
        hibernation = contient and not plafonnee
    elif hibernation is True and not chiffre:
        alertes.append({"code": "hibernation-needs-lvm"})
        hibernation = False
    elif hibernation is True and (plafonnee or not contient):
        alertes.append({"code": "hibernation-off"})
        hibernation = False
    put(p, "boot.hibernation", hibernation)

    cpu = facts.get("cpu") or {}
    virtuel = bool(facts.get("virtual"))
    if get(p, "system.microcode") == AUTO:
        put(
            p,
            "system.microcode",
            "none"
            if virtuel
            else {"amd": "amd-ucode", "intel": "intel-ucode"}.get(
                cpu.get("vendor"), "none"
            ),
        )

    firmware = facts.get("firmware") or {}
    if firmware.get("mode") != "uefi":
        amorce = "bios"
    elif firmware.get("bits") == 32:
        amorce = "uefi32"
        alertes.append({"code": "uefi-32bit"})
    else:
        amorce = "uefi64"
    if get(p, "boot.loader") == AUTO:
        put(p, "boot.loader", "systemd-boot" if amorce == "uefi64" else "grub")
    elif get(p, "boot.loader") == "systemd-boot" and amorce != "uefi64":
        alertes.append({"code": "loader-needs-uefi"})

    if get(p, "desktop.power") == AUTO:
        put(
            p,
            "desktop.power",
            "tlp" if facts.get("laptop") else "power-profiles-daemon",
        )

    fabricants = {g.get("vendor") for g in facts.get("gpus") or []}
    if get(p, "gpu.driver") == AUTO:
        put(p, "gpu.driver", "nouveau" if "nvidia" in fabricants else "mesa")
    pilote = get(p, "gpu.driver")
    if pilote in ("nouveau", "nvidia-open") and "nvidia" not in fabricants:
        alertes.append({"code": "gpu-no-nvidia", "driver": pilote})
    paquets_gpu = []
    if pilote in ("nouveau", "nvidia-open"):
        paquets_gpu += GPU_PACKAGES[pilote]
    for fabricant in ("amd", "intel"):
        if fabricant in fabricants:
            paquets_gpu += GPU_PACKAGES[fabricant]
    if not paquets_gpu:
        paquets_gpu += GPU_PACKAGES["mesa"]

    if get(p, "live.mirrors_country") == AUTO:
        put(p, "live.mirrors_country", None)

    noyaux = get(p, "system.kernels") or []
    entetes = get(p, "system.kernel_headers") or pilote == "nvidia-open"
    dkms = get(p, "system.dkms") or pilote == "nvidia-open"
    microcode = get(p, "system.microcode")
    power = get(p, "desktop.power")
    paquets = _unique(
        [
            *noyaux,
            *([f"{k}-headers" for k in noyaux] if entetes else []),
            "dkms" if dkms else None,
            microcode if microcode not in (None, "none") else None,
            *(("lvm2", "cryptsetup") if chiffre else ()),
            *paquets_gpu,
            *POWER_PACKAGES.get(power, ()),
            *SHELL_PACKAGES.get(get(p, "user.shell"), ()),
            "apparmor" if get(p, "security.apparmor") else None,
            "gnome-extra" if get(p, "desktop.extra") else None,
            *(get(p, "system.extra_packages") or []),
            *(get(p, "desktop.apps") or []),
        ]
    )
    services = _unique(
        [
            *(get(p, "system.services") or []),
            *POWER_SERVICES.get(power, ()),
            "apparmor.service" if get(p, "security.apparmor") else None,
            "e2scrub_all.timer" if get(p, "system.e2scrub") else None,
            "systemd-boot-update.service"
            if get(p, "boot.loader") == "systemd-boot"
            else None,
        ]
    )
    zram = get(p, "system.zram") or {}
    p["derived"] = {
        "disk": copy.deepcopy(disque),
        "firmware": amorce,
        "grub_target": GRUB_TARGETS[amorce]
        if get(p, "boot.loader") == "grub"
        else None,
        "ram_mib": ram_mib,
        "swap_gib": swap_gib,
        "zram_mib": zram_mib(zram.get("size"), ram_mib)
        if zram.get("enabled")
        else 0,
        "packages": paquets,
        "services": services,
    }
    p["warnings"] = alertes
    return p, questions


# Résumé


def _oui_non(valeur):
    if valeur in (AUTO, ASK):
        return valeur
    return "yes" if valeur else "no"


def _valeur(valeur):
    if valeur is None:
        return "none"
    if isinstance(valeur, bool):
        return _oui_non(valeur)
    if isinstance(valeur, list):
        return ", ".join(map(str, valeur)) if valeur else "none"
    return str(valeur)


SUMMARY_LIST_MAX = 6


def _apercu(elements):
    """Une longue liste en une ligne : son compte, puis ses premiers
    éléments."""
    if len(elements) <= SUMMARY_LIST_MAX:
        return _valeur(elements)
    debut = ", ".join(elements[:SUMMARY_LIST_MAX])
    return f"{len(elements)}: {debut}, …"


def _secret_texte(secret):
    if not isinstance(secret, dict):
        return "none"
    texte = f"{secret.get('size_gib')} GiB"
    return f"{texte}, {ASK}" if secret.get("optional") else texte


def plan_summary(settings):
    """Le profil en lignes courtes : [(libellé, valeur)], le libellé pris
    dans SUMMARY_LABELS, la valeur en texte. Accepte un profil résolu par
    resolve() comme un profil brut : « auto » et « ask » s'y montrent
    tels quels, à traduire avec les autres SUMMARY_TOKENS."""
    s = merge(DEFAULTS, settings)
    derive = s.get("derived") or {}
    chiffre = get(s, "disk.layout") == "lvm_on_luks"
    disque = derive.get("disk")
    cible = get(s, "disk.target")
    if disque:
        cible = f"{disque['path']} ({disque.get('size', 0) // GIB} GiB)"
    swap = get(s, "disk.lvm.swap")
    lignes = [
        ("Profile", _valeur(get(s, "name"))),
        ("Target disk", _valeur(cible)),
        ("Disk layout", _valeur(get(s, "disk.layout"))),
    ]
    if chiffre:
        lignes += [
            ("LUKS sector size", _valeur(get(s, "disk.luks.sector_size"))),
            ("TRIM (discards)", _valeur(get(s, "disk.luks.discards"))),
            (
                "Swap",
                f"{swap} GiB" if isinstance(swap, int) else _valeur(swap),
            ),
            ("Hibernation", _valeur(get(s, "boot.hibernation"))),
            ("Secret volume", _secret_texte(get(s, "disk.lvm.secret_lv"))),
        ]
    zram = get(s, "system.zram") or {}
    if zram.get("enabled"):
        taille = derive.get("zram_mib")
        zram_texte = (
            f"{taille} MiB {zram.get('algorithm')}"
            if taille is not None and derive
            else f"{zram.get('size')} {zram.get('algorithm')}"
        )
    else:
        zram_texte = "no"
    utilisateur = get(s, "user.name")
    extras = (get(s, "system.extra_packages") or []) + (
        get(s, "desktop.apps") or []
    )
    lignes += [
        ("Boot loader", _valeur(get(s, "boot.loader"))),
        ("Kernels", _valeur(get(s, "system.kernels"))),
        ("Microcode", _valeur(get(s, "system.microcode"))),
        ("Host name", _valeur(get(s, "system.hostname"))),
        ("User", _valeur(utilisateur)),
        ("Shell", _valeur(get(s, "user.shell"))),
        ("Time zone", _valeur(get(s, "system.timezone"))),
        ("Locales", _valeur(get(s, "system.locales"))),
        ("Keyboard", _valeur(get(s, "system.console_keymap"))),
        ("Desktop", _valeur(get(s, "desktop.env"))),
        ("GPU driver", _valeur(get(s, "gpu.driver"))),
        ("Power management", _valeur(get(s, "desktop.power"))),
        ("zram", zram_texte),
        ("AppArmor", _valeur(get(s, "security.apparmor"))),
        ("Extra packages", _apercu(extras)),
        (
            "Services",
            _valeur(derive.get("services") or get(s, "system.services")),
        ),
    ]
    return lignes
