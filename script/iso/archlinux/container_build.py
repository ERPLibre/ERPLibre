#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""build_iso.py dans un conteneur Arch à jour : image, moteur, commandes.

Ce module rend des DONNÉES — le moteur retenu, les argv de « build » et de
« run » — et n'exécute rien lui-même : build_iso.main les affiche (plan,
--dry-run) puis les lance. Seules `image_tags` et `pick_runtime` consultent
le moteur, par un lanceur injectable.

Le conteneur relance build_iso.py avec « --builder host » : le dépôt y est
monté en lecture seule sur /src, le répertoire de sortie sur /out, le cache
pacman persistant sur /var/cache/pacman/pkg. Deux façons d'y faire tourner
mkarchiso, selon que le moteur isole ou non les UID :

- « userns » (Podman sans root) : la racine du conteneur n'est que le
  compte de l'appelant, et devtmpfs ne se monte pas dans un espace de noms
  utilisateur — mkarchiso lancé en root y échoue sur /dev, même avec
  --privileged. Il tourne donc en SIMPLE UTILISATEUR (UID CONTAINER_UID,
  qui est l'appelant par --userns=keep-id) et passe par « unshare
  --map-auto », comme sur un hôte. Il faut pour cela :
    * newuidmap/newgidmap porteurs de leurs capacités de fichier et une
      plage /etc/subuid pour CONTAINER_UID, posés par le Containerfile ;
    * --security-opt unmask=/proc/* : les chemins de /proc que Podman masque
      rendent tout montage d'un nouveau /proc « trop révélateur » dans
      l'espace de noms imbriqué.
  Aucune capacité ajoutée. Les fichiers produits appartiennent à
  l'appelant.
- « root » (Docker, ou Podman lancé par root) : la racine du conteneur est
  root. mkarchiso monte proc, sysfs et devtmpfs dans son chroot ; seul
  CAP_SYS_ADMIN manque à la liste par défaut, et le profil seccomp par
  défaut autorise mount/unshare dès qu'il est présent. --privileged n'est
  pas nécessaire. Les fichiers produits appartiennent à root : build_iso
  intérieur les rend à l'appelant (--chown).

Les deux stratégies ajoutent HOST_SECURITY_OPTS : le profil AppArmor par
défaut des moteurs (« docker-default », celui de Podman) porte
« deny mount », qui refuse les montages de mkarchiso même avec
CAP_SYS_ADMIN ; l'étiquette SELinux d'un conteneur l'empêche de lire les
volumes montés sans relabel (/src en lecture seule, qu'on ne relabellise
pas). Sur un hôte sans AppArmor ni SELinux, les moteurs les acceptent et
les ignorent.

Docker sans root est refusé : sa racine de conteneur est elle aussi
l'appelant (devtmpfs impossible) et il n'a pas d'équivalent de keep-id.
"""

import datetime
import os
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONTAINER_DIR = HERE / "container"
CONTAINERFILE = CONTAINER_DIR / "Containerfile"

IMAGE_REPO = "erplibre-isobuilder"
LATEST_TAG = "latest"
# Une image dont l'étiquette-date a plus de IMAGE_MAX_AGE_DAYS jours est
# reconstruite. mkarchiso télécharge les paquets de l'ISO lui-même, à jour,
# quel que soit l'âge de l'image : celle-ci ne fige que mkarchiso et le
# profil releng, qui changent au rythme des versions d'archiso.
IMAGE_MAX_AGE_DAYS = 14
DATE_TAG_RE = re.compile(r"^\d{8}$")

# Ordre de préférence quand aucun moteur n'est imposé.
RUNTIME_ORDER = ("podman", "docker")

# UID et GID de l'appelant DANS le conteneur en mode « userns ». Le
# Containerfile donne à cet UID la plage subuid CONTAINER_UID+1 et suivantes
# — les deux valeurs vont ensemble.
CONTAINER_UID = 1000

SRC = "/src"
OUT = "/out"
PKG_CACHE = "/var/cache/pacman/pkg"
WORK_MOUNT = "/work"
# Répertoire de travail sans --keep-work : dans la couche inscriptible du
# conteneur, effacée avec lui (--rm). /var/tmp plutôt que /tmp, qu'un
# moteur peut monter en tmpfs.
INNER_WORK = "/var/tmp/erplibre-iso/work"
INNER_SCRIPT = f"{SRC}/script/iso/archlinux/build_iso.py"

STRATEGY_USERNS = "userns"
STRATEGY_ROOT = "root"

HOST_SECURITY_OPTS = (
    "--security-opt",
    "label=disable",
    "--security-opt",
    "apparmor=unconfined",
)


def date_tag(day):
    """Étiquette-date d'une image : AAAAMMJJ."""
    return day.strftime("%Y%m%d")


def image_ref(tag):
    return f"{IMAGE_REPO}:{tag}"


def parse_image_lines(text):
    """Étiquettes-date de IMAGE_REPO dans la sortie de « images --format
    {{.Repository}}:{{.Tag}} ». Podman préfixe le dépôt de « localhost/ » ;
    les autres étiquettes (latest, ou posées à la main) sont ignorées."""
    tags = set()
    for line in text.splitlines():
        repo, _, tag = line.strip().rpartition(":")
        if repo.rsplit("/", 1)[-1] == IMAGE_REPO and DATE_TAG_RE.match(tag):
            tags.add(tag)
    return sorted(tags)


def fresh_tag(tags, today, max_age_days=IMAGE_MAX_AGE_DAYS):
    """La plus récente des étiquettes-date de moins de `max_age_days`
    jours, ou None. Une date future (horloge reculée) compte pour fraîche :
    l'image existe, seule son âge est incertain."""
    for tag in sorted(tags, reverse=True):
        try:
            day = datetime.datetime.strptime(tag, "%Y%m%d").date()
        except ValueError:
            continue
        if (today - day).days <= max_age_days:
            return tag
    return None


def strategy(fiche):
    """STRATEGY_USERNS, STRATEGY_ROOT ou None (moteur non pris en charge),
    d'après la fiche de container_runtime.etat."""
    if fiche["moteur"] == "podman":
        # sudo devant podman en fait un podman de root.
        if fiche["sans_sudo"] and fiche.get("rootless") is not False:
            return STRATEGY_USERNS
        return STRATEGY_ROOT
    if fiche["moteur"] == "docker":
        if fiche["sans_sudo"] and fiche.get("rootless"):
            return None
        return STRATEGY_ROOT
    return None


def pick_runtime(fiches, forced=None):
    """La fiche du moteur à utiliser, ou None. `forced` impose le moteur ;
    sinon RUNTIME_ORDER, et un moteur qui répond sans sudo passe avant un
    moteur qui ne répond que par sudo."""
    usable = {
        f["moteur"]: f
        for f in fiches
        if (f["sans_sudo"] or f["avec_sudo"]) and strategy(f)
    }
    if forced:
        return usable.get(forced)
    for need_no_sudo in (True, False):
        for name in RUNTIME_ORDER:
            fiche = usable.get(name)
            if fiche and (fiche["sans_sudo"] or not need_no_sudo):
                return fiche
    return None


def images_argv(fiche, commande):
    """« images » restreint au dépôt IMAGE_REPO. `commande` est
    container_runtime.commande (préfixe sudo / DOCKER_HOST)."""
    return commande(
        fiche,
        ["images", "--format", "{{.Repository}}:{{.Tag}}", IMAGE_REPO],
    )


def build_argv(fiche, commande, tag):
    """Construit l'image sous `tag` et LATEST_TAG. --no-cache : la couche
    « pacman -Syu » serait sinon reprise du cache tant que l'image de base
    n'a pas changé, et la reconstruction ne mettrait rien à jour."""
    pull = "--pull=always" if fiche["moteur"] == "podman" else "--pull"
    return commande(
        fiche,
        [
            "build",
            pull,
            "--no-cache",
            "-t",
            image_ref(tag),
            "-t",
            image_ref(LATEST_TAG),
            "-f",
            str(CONTAINERFILE),
            str(CONTAINER_DIR),
        ],
    )


def rmi_argv(fiche, commande, tag):
    return commande(fiche, ["rmi", image_ref(tag)])


def inner_argv(
    passthrough, epoch, work_name=None, keep_work=False, owner=None
):
    """build_iso.py tel que lancé DANS le conteneur. `passthrough` porte
    les options qui ne touchent pas aux chemins (--branch, --lang…).

    `work_name` : nom du répertoire de travail sous WORK_MOUNT, quand il
    vit sur l'hôte (--work-dir ou --keep-work) ; sinon INNER_WORK. `epoch`
    fixe le nom de l'ISO, que l'hôte connaît ainsi d'avance. `owner`
    (« uid:gid ») n'est donné qu'en mode root : build_iso intérieur rend
    alors l'ISO, son empreinte, le travail et le cache pacman à
    l'appelant."""
    work = f"{WORK_MOUNT}/{work_name}" if work_name else INNER_WORK
    argv = [
        "python3",
        INNER_SCRIPT,
        "--builder",
        "host",
        "--output-dir",
        OUT,
        "--work-dir",
        work,
        "--source-date-epoch",
        str(epoch),
    ]
    if keep_work:
        argv.append("--keep-work")
    if owner:
        argv += ["--chown", owner, "--chown-tree", PKG_CACHE]
    return argv + list(passthrough)


def run_argv(
    fiche,
    commande,
    image,
    repo,
    output_dir,
    pkg_cache,
    inner,
    work_parent=None,
):
    """« run » complet du conteneur de construction (voir la docstring du
    module pour les options de chaque stratégie)."""
    mode = strategy(fiche)
    if mode is None:
        raise ValueError(f"unsupported container runtime: {fiche['moteur']}")
    # « -v source:cible[:options] » : un deux-points dans un chemin de
    # l'hôte déplacerait la frontière des champs.
    for path in (repo, output_dir, pkg_cache, work_parent):
        if path is not None and ":" in str(path):
            raise ValueError(f"path not mountable (contains ':'): {path}")
    args = ["run", "--rm"]
    if mode == STRATEGY_USERNS:
        uid = CONTAINER_UID
        args += [
            f"--userns=keep-id:uid={uid},gid={uid}",
            "--security-opt",
            "unmask=/proc/*",
        ]
    else:
        args += ["--cap-add", "SYS_ADMIN"]
    args += list(HOST_SECURITY_OPTS)
    args += [
        "-e",
        "PYTHONDONTWRITEBYTECODE=1",
        "-e",
        "PYTHONUNBUFFERED=1",
        "-v",
        f"{repo}:{SRC}:ro",
        "-v",
        f"{output_dir}:{OUT}",
        "-v",
        f"{pkg_cache}:{PKG_CACHE}",
    ]
    if work_parent:
        args += ["-v", f"{work_parent}:{WORK_MOUNT}"]
    return commande(fiche, args + [image] + list(inner))


def owner_of_caller():
    """« uid:gid » de l'appelant."""
    return f"{os.getuid()}:{os.getgid()}"
