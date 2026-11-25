#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Étape disque de l'installateur ERPLibre : partitionne, chiffre, crée
les volumes, formate et monte la cible AVANT archinstall, qui l'installe
ensuite en mode pré-monté (« pre_mounted_config »).

archinstall 4.5 ne sait exprimer ni la taille de secteur LUKS, ni les
discards persistants, ni le type GPT 8309, ni un volume secret chiffré à
part, ni l'espace libre laissé dans le groupe de volumes : ce module
prend donc le disque en entier, et archinstall ne voit qu'un /mnt prêt.

Trois moitiés :
- plan(settings, confirm) est pure : elle rend la liste des commandes,
  chacune un argv. Une phrase secrète n'y figure jamais : l'étape porte
  le NOM du secret (« luks », « secret_lv ») dans « stdin », et seul
  execute() le remplace par sa valeur, passée sur l'entrée standard de
  cryptsetup (--key-file=-). Le plan s'affiche et se journalise tel quel.
- preflight(disque, lsblk) est pure : elle relit l'état du disque juste
  avant de l'effacer et refuse s'il a changé, s'il porte le support de
  démarrage ou s'il est en service.
- execute(), read_uuids() et teardown() touchent la machine, par un
  `run` injecté.

Les tailles sont en MiB relatives (« +N M » de sgdisk, départ « 0 » = le
premier secteur aligné libre) : le plan ne dépend pas de la taille du
secteur logique, que le formatage NVMe 4 KiB change en cours de route.

Bibliothèque standard seulement ; facts vient du dossier machine/ que
build_iso.py copie à côté de ce fichier dans l'ISO.
"""

import os
import re
import shlex
import subprocess

import facts as facts_mod

MIB = 1024**2
GIB = 1024**3

TARGET = "/mnt/archinstall"
LUKS_MAPPER = "cryptlvm"
SECRET_MAPPER = "erplibre-secret"

# Noms des secrets qu'une étape attend sur son entrée standard : les clés
# du dict `secrets` d'execute().
SECRET_LUKS = "luks"
SECRET_LV = "secret_lv"

# La GPT occupe le premier MiB (départ aligné des partitions) et garde sa
# copie de secours dans les derniers secteurs : la fin de la racine est
# arrondie au MiB inférieur, un MiB avant la fin du disque.
HEAD_MIB = 1
TAIL_MIB = 1
BIOS_GRUB_MIB = 1
# En-tête LUKS2 (16 MiB par défaut) et métadonnées LVM, retranchés de
# l'estimation de la racine.
LUKS_OVERHEAD_MIB = 16
LVM_OVERHEAD_MIB = 4
# Sous ce seuil la racine ne contient pas GNOME, ERPLibre et un Odoo.
MIN_ROOT_MIB = 10 * 1024

GPT_ESP = "ef00"
GPT_BIOS_GRUB = "ef02"
GPT_LINUX = "8300"
GPT_LUKS = "8309"

# Cible GRUB qui démarre par le MBR : elle exige une partition bios_grub
# sur un disque GPT, et une /boot lisible sans phrase secrète.
GRUB_BIOS_TARGET = "i386-pc"

# Sous un disque, lsblk ne montre que ses partitions et ce qui s'y empile :
# LVM, LUKS, md (raid0 à raid10, linear, multipath…), mpath, dmraid, dm
# générique. Tout descendant d'un autre type que PARTITION_TYPES retient
# donc le disque, et sgdisk ou nvme format effaceraient sous lui ; une
# liste blanche ne manque aucun type que lsblk ajouterait plus tard.
PARTITION_TYPES = frozenset({"part"})

# Un espace de noms NVMe : « nvme<sous-système>n<espace> ». Deux espaces
# du même sous-système partagent un contrôleur, et « nvme format » peut
# s'appliquer à tous (bit 0 de FNA dans id-ctrl).
NVME_NAMESPACE_RE = re.compile(r"^(nvme\d+)n\d+$")


def partition_path(disk, number):
    """Le nœud de la partition `number` de `disk` : un nom de disque qui
    finit par un chiffre (nvme0n1, mmcblk0, loop0) prend « p » devant le
    numéro."""
    sep = "p" if disk[-1:].isdigit() else ""
    return f"{disk}{sep}{number}"


def _get(settings, path, default=None):
    courant = settings
    for morceau in path.split("."):
        if not isinstance(courant, dict) or morceau not in courant:
            return default
        courant = courant[morceau]
    return courant


def _result(ok, reason=None, plan=None, warnings=None, layout=None, **d):
    return {
        "ok": ok,
        "reason": reason,
        "details": d,
        "plan": plan or [],
        "warnings": warnings or [],
        "layout": layout,
    }


def _step(*argv, stdin=None):
    return {"argv": [str(a) for a in argv], "stdin": stdin}


def layout(settings):
    """La disposition que plan() crée, tirée des réglages résolus :

    {"disk", "size_mib", "luks", "bios", "partitions": [{"number",
    "role", "code", "name", "mib", "path"}], "root_mib", "root_dev",
    "boot_dev", "boot_fs", "swap_dev", "secret_dev", "vg", "swap_gib",
    "secret_gib", "vg_free_mib", "root_fs"}.

    UEFI : ESP (esp_mib, ef00, FAT32 sur /boot), puis la racine. BIOS
    (GRUB i386-pc) : bios_grub (1 MiB, ef02), /boot en ext4 de esp_mib
    hors de LUKS, puis la racine. La racine prend le reste, 8309 quand
    elle porte LUKS, 8300 sinon. root_mib est une estimation de la
    racine finale, en-têtes LUKS et LVM, swap, volume secret et espace
    libre du groupe déduits."""
    derive = settings.get("derived") or {}
    disque = derive.get("disk") or {}
    chemin = disque.get("path") or _get(settings, "disk.target")
    size_mib = (disque.get("size") or 0) // MIB
    luks = _get(settings, "disk.layout") == "lvm_on_luks"
    bios = derive.get("grub_target") == GRUB_BIOS_TARGET
    esp_mib = int(_get(settings, "disk.esp_mib") or 1024)
    vg = _get(settings, "disk.lvm.vg") or "vg0"
    swap_gib = int(derive.get("swap_gib") or 0) if luks else 0
    secret = _get(settings, "disk.lvm.secret_lv")
    secret_gib = (
        int(secret.get("size_gib") or 0)
        if luks and isinstance(secret, dict)
        else 0
    )
    vg_free_mib = int(_get(settings, "disk.lvm.vg_free_mib") or 0)
    root_fs = _get(settings, "disk.lvm.root_fs") or "ext4"

    parties = []
    if bios:
        parties.append(("bios_grub", GPT_BIOS_GRUB, "BIOS", BIOS_GRUB_MIB))
        parties.append(("boot", GPT_LINUX, "boot", esp_mib))
    else:
        parties.append(("esp", GPT_ESP, "ESP", esp_mib))
    occupe = HEAD_MIB + TAIL_MIB + sum(p[3] for p in parties)
    racine_mib = size_mib - occupe
    parties.append(
        ("root", GPT_LUKS if luks else GPT_LINUX, "root", racine_mib)
    )
    partitions = [
        {
            "number": i,
            "role": role,
            "code": code,
            "name": nom,
            "mib": mib,
            "path": partition_path(chemin, i) if chemin else None,
        }
        for i, (role, code, nom, mib) in enumerate(parties, 1)
    ]
    par_role = {p["role"]: p for p in partitions}
    root_part = par_role["root"]["path"]
    boot_part = (par_role.get("esp") or par_role.get("boot"))["path"]

    if luks:
        estimation = (
            racine_mib
            - LUKS_OVERHEAD_MIB
            - LVM_OVERHEAD_MIB
            - swap_gib * 1024
            - secret_gib * 1024
            - vg_free_mib
        )
        root_dev = f"/dev/{vg}/root"
    else:
        estimation = racine_mib
        root_dev = root_part
    return {
        "disk": chemin,
        "size_mib": size_mib,
        "luks": luks,
        "bios": bios,
        "partitions": partitions,
        "root_part": root_part,
        "root_mib": estimation,
        "root_dev": root_dev,
        "root_fs": root_fs,
        "boot_dev": boot_part,
        "boot_fs": "ext4" if bios else "vfat",
        "vg": vg if luks else None,
        "swap_gib": swap_gib,
        "swap_dev": f"/dev/{vg}/swap" if swap_gib else None,
        "secret_gib": secret_gib,
        "secret_dev": f"/dev/{vg}/secret" if secret_gib else None,
        "vg_free_mib": vg_free_mib if luks else 0,
    }


def _mkfs(fs, dev, label):
    if fs == "xfs":
        return _step("mkfs.xfs", "-f", "-L", label, dev)
    return _step("mkfs.ext4", "-F", "-L", label, dev)


def _luks_format(dev, sector, iter_ms, secret):
    return _step(
        "cryptsetup",
        "luksFormat",
        "--type",
        "luks2",
        "--sector-size",
        sector,
        "--iter-time",
        iter_ms,
        "--batch-mode",
        "--key-file=-",
        dev,
        stdin=secret,
    )


def plan(settings, confirm=None):
    """{"ok", "reason", "details", "plan", "warnings", "layout"} : les
    commandes qui préparent le disque de `settings` (résolus par
    machine_profile.resolve) et le montent sur TARGET.

    `confirm` porte les confirmations explicites : {"nvme_format": bool}.
    Le formatage NVMe 4 KiB n'entre au plan que si les réglages le
    proposent (un indice de format) ET que confirm["nvme_format"] est
    vrai ; proposé sans confirmation, il donne la mise en garde
    « nvme-format-skipped ». Un espace de noms reformaté en 4 KiB exige
    des secteurs LUKS de 4096 : la taille résolue sur l'ancien format est
    alors relevée.

    Réussi, details["sector_size"] est la taille de secteur LUKS que le
    plan emploie vraiment, relevée ou non.

    Refus : « no-target » (aucun disque retenu), « disk-too-small » (la
    racine estimée passe sous MIN_ROOT_MIB)."""
    confirm = confirm or {}
    derive = settings.get("derived") or {}
    disque = derive.get("disk")
    if not disque or not disque.get("path"):
        return _result(False, "no-target")
    lay = layout(settings)
    if lay["root_mib"] < MIN_ROOT_MIB:
        return _result(
            False,
            "disk-too-small",
            layout=lay,
            root_mib=lay["root_mib"],
            minimum_mib=MIN_ROOT_MIB,
        )
    alertes = []
    etapes = []
    chemin = lay["disk"]

    lbaf = _get(settings, "disk.nvme_lba_4k")
    secteur = int(_get(settings, "disk.luks.sector_size") or 512)
    if isinstance(lbaf, int) and not isinstance(lbaf, bool):
        if confirm.get("nvme_format") is True:
            etapes += [
                _step("nvme", "format", chemin, f"--lbaf={lbaf}", "--force"),
                _step("udevadm", "settle"),
            ]
            secteur = 4096
        else:
            alertes.append({"code": "nvme-format-skipped", "lbaf": lbaf})

    etapes += [
        _step("wipefs", "--all", chemin),
        _step("sgdisk", "--zap-all", chemin),
    ]
    creation = ["sgdisk"]
    for p in lay["partitions"]:
        n = p["number"]
        creation += [
            "-n",
            f"{n}:0:+{p['mib']}M",
            "-t",
            f"{n}:{p['code']}",
            "-c",
            f"{n}:{p['name']}",
        ]
    creation.append(chemin)
    etapes += [
        _step(*creation),
        _step("partprobe", chemin),
        _step("udevadm", "settle"),
    ]

    if lay["luks"]:
        etapes += _luks_steps(settings, lay, secteur)
    else:
        etapes.append(_mkfs(lay["root_fs"], lay["root_dev"], "root"))

    if lay["bios"]:
        etapes.append(_step("mkfs.ext4", "-F", "-L", "boot", lay["boot_dev"]))
    else:
        etapes.append(
            _step("mkfs.fat", "-F", "32", "-n", "ESP", lay["boot_dev"])
        )
    etapes += mount_steps(lay)
    return _result(
        True, plan=etapes, warnings=alertes, layout=lay, sector_size=secteur
    )


def _luks_steps(settings, lay, secteur):
    """LUKS2 sur la partition racine, LVM dedans : swap, volume secret,
    racine sur le reste moins vg_free_mib, puis les systèmes de
    fichiers. La phrase passe par l'entrée standard (--key-file=-), lue
    telle quelle jusqu'à sa fin : l'appelant ne doit pas y ajouter de fin
    de ligne, sans quoi elle ferait partie de la clé et la phrase tapée
    au démarrage ne l'ouvrirait plus."""
    iter_ms = int(_get(settings, "disk.luks.iter_time_ms") or 2000)
    discards = _get(settings, "disk.luks.discards") is True
    vg = lay["vg"]
    mapper = f"/dev/mapper/{LUKS_MAPPER}"
    ouvrir = ["cryptsetup", "open", "--key-file=-"]
    if discards:
        # --persistent écrit le drapeau dans l'en-tête LUKS2 : l'initramfs
        # le reprend à chaque ouverture, sans option sur la ligne noyau.
        ouvrir += ["--allow-discards", "--persistent"]
    etapes = [
        _luks_format(lay["root_part"], secteur, iter_ms, SECRET_LUKS),
        _step(*ouvrir, lay["root_part"], LUKS_MAPPER, stdin=SECRET_LUKS),
        _step("pvcreate", "--yes", mapper),
        _step("vgcreate", "--yes", vg, mapper),
    ]
    if lay["swap_gib"]:
        etapes.append(
            _step(
                "lvcreate",
                "--yes",
                "-L",
                f"{lay['swap_gib']}G",
                "-n",
                "swap",
                vg,
            )
        )
    if lay["secret_gib"]:
        etapes.append(
            _step(
                "lvcreate",
                "--yes",
                "-L",
                f"{lay['secret_gib']}G",
                "-n",
                "secret",
                vg,
            )
        )
    etapes.append(
        _step("lvcreate", "--yes", "-l", "100%FREE", "-n", "root", vg)
    )
    if lay["vg_free_mib"]:
        etapes.append(
            _step(
                "lvreduce",
                "--yes",
                "-L",
                f"-{lay['vg_free_mib']}M",
                f"{vg}/root",
            )
        )
    if lay["secret_gib"]:
        secret_mapper = f"/dev/mapper/{SECRET_MAPPER}"
        etapes += [
            _luks_format(lay["secret_dev"], secteur, iter_ms, SECRET_LV),
            _step(
                "cryptsetup",
                "open",
                "--key-file=-",
                lay["secret_dev"],
                SECRET_MAPPER,
                stdin=SECRET_LV,
            ),
            _step("mkfs.ext4", "-F", "-L", "secret", secret_mapper),
            _step("cryptsetup", "close", SECRET_MAPPER),
        ]
    if lay["swap_dev"]:
        etapes.append(_step("mkswap", "-L", "swap", lay["swap_dev"]))
    etapes.append(_mkfs(lay["root_fs"], lay["root_dev"], "root"))
    return etapes


def mount_steps(lay, target=TARGET):
    """Racine sur `target`, /boot dessous (FAT : masques 0077, la graine
    aléatoire de systemd-boot n'y est lisible que par root), puis la
    swap, active avant archinstall pour que genfstab la voie.

    Chaque montage nomme son type (-t) : sans lui, mount demande le type
    à libblkid, et une sonde qui ne lit rien juste après mkfs (udev
    retraite encore les événements des étapes précédentes) le fait
    essayer chaque système de /proc/filesystems, squashfs du live en
    tête, puis échouer sur « fmask » ; l'étape disque échoue alors sur
    un système de fichiers pourtant valide. « udevadm settle » laisse ces
    événements se terminer avant le premier montage."""
    boot = os.path.join(target, "boot")
    etapes = [
        _step("udevadm", "settle"),
        _step(
            "mount", "--mkdir", "-t", lay["root_fs"], lay["root_dev"], target
        ),
    ]
    if lay["boot_fs"] == "vfat":
        etapes.append(
            _step(
                "mount",
                "--mkdir",
                "-t",
                "vfat",
                "-o",
                "fmask=0077,dmask=0077",
                lay["boot_dev"],
                boot,
            )
        )
    else:
        etapes.append(
            _step(
                "mount", "--mkdir", "-t", lay["boot_fs"], lay["boot_dev"], boot
            )
        )
    if lay["swap_dev"]:
        etapes.append(_step("swapon", lay["swap_dev"]))
    return etapes


def teardown_steps(lay, target=TARGET):
    """Ce qui rend le disque après l'installation, ou après une étape
    disque interrompue ou en échec : swap coupée, cible démontée, volume
    secret fermé (le plan l'ouvre le temps de son mkfs), groupe
    désactivé, LUKS fermé. Chaque étape est tentée même si la précédente
    échoue : un démontage déjà fait, un volume jamais ouvert ne sont pas
    des erreurs."""
    etapes = []
    if lay and lay.get("swap_dev"):
        etapes.append(_step("swapoff", lay["swap_dev"]))
    etapes.append(_step("umount", "--recursive", target))
    if lay and lay.get("luks"):
        if lay.get("secret_gib"):
            etapes.append(_step("cryptsetup", "close", SECRET_MAPPER))
        etapes += [
            _step("vgchange", "--activate", "n", lay["vg"]),
            _step("cryptsetup", "close", LUKS_MAPPER),
        ]
    return etapes


def required_secrets(lay):
    """Les noms des secrets que le plan de `lay` lit sur l'entrée
    standard."""
    noms = []
    if lay and lay.get("luks"):
        noms.append(SECRET_LUKS)
        if lay.get("secret_gib"):
            noms.append(SECRET_LV)
    return noms


# Relecture avant d'effacer


def _subtree(node):
    yield node
    for enfant in node.get("children") or []:
        if isinstance(enfant, dict):
            yield from _subtree(enfant)


def nvme_siblings(name, disques):
    """Les noms des autres espaces de noms NVMe du même sous-système que
    le disque `name`, parmi les fiches `disques` (facts.disks_from) ;
    vide si `name` n'est pas un espace de noms NVMe."""
    m = NVME_NAMESPACE_RE.match(str(name or ""))
    if not m:
        return []
    voisins = []
    for d in disques:
        autre = NVME_NAMESPACE_RE.match(str(d.get("name") or ""))
        if autre and autre.group(1) == m.group(1) and d.get("name") != name:
            voisins.append(d["name"])
    return sorted(voisins)


def plan_formats_nvme(steps):
    """Vrai si le plan `steps` contient un « nvme format »."""
    return any(s["argv"][:2] == ["nvme", "format"] for s in steps or [])


def preflight(expected, lsblk_text, cmdline=None, nvme_format=False):
    """None si le disque `expected` (fiche de facts) est toujours là, tel
    quel, et libre ; sinon (code, détails).

    `nvme_format` vrai (le plan reformate l'espace de noms) refuse aussi
    quand un autre espace de noms du même sous-système est visible
    (« nvme-shared-controller ») : sur un contrôleur dont le formatage
    s'applique à tous les espaces, il effacerait un disque que personne
    n'a confirmé, et dont l'arbre n'est relu par aucune autre règle.

    Relu dans `lsblk_text` (JSON de facts.LSBLK_COMMAND) juste avant
    l'effacement : même chemin, même taille, même modèle (un disque
    débranché puis remplacé reprend souvent le même nœud). Refus aussi
    s'il porte le support de démarrage, s'il est en lecture seule, si
    une de ses partitions est montée ou sert de swap, ou si un LUKS ou un
    LVM y est ouvert : sgdisk effacerait la table sous un périphérique
    encore utilisé."""
    chemin = (expected or {}).get("path")
    disques = facts_mod.disks_from(lsblk_text, cmdline=cmdline)
    actuel = next((d for d in disques if d.get("path") == chemin), None)
    if actuel is None:
        return ("target-gone", {"device": chemin})
    for champ in ("size", "model"):
        if actuel.get(champ) != expected.get(champ):
            return ("target-changed", {"device": chemin, "field": champ})
    if actuel.get("boot_medium"):
        return ("target-is-boot-medium", {"device": chemin})
    if actuel.get("ro"):
        return ("target-read-only", {"device": chemin})
    if nvme_format:
        voisins = nvme_siblings(actuel.get("name"), disques)
        if voisins:
            return (
                "nvme-shared-controller",
                {"device": chemin, "namespaces": voisins},
            )
    noeud = next(
        (
            n
            for n in facts_mod._blockdevices(lsblk_text)
            if (n.get("path") or "/dev/" + str(n.get("name"))) == chemin
        ),
        {},
    )
    montes, porteurs = [], []
    for n in _subtree(noeud):
        for m in n.get("mountpoints") or [n.get("mountpoint")]:
            if m:
                montes.append(m)
        if n is not noeud and n.get("type") not in PARTITION_TYPES:
            porteurs.append(str(n.get("name")))
    if montes:
        return ("target-in-use", {"device": chemin, "mounts": montes})
    if porteurs:
        return ("target-has-holders", {"device": chemin, "holders": porteurs})
    return None


# Exécution (impure)


def describe(step):
    """La commande en une ligne, pour l'écran et le journal ; une étape
    qui lit un secret le dit par son nom, jamais par sa valeur."""
    texte = shlex.join(step["argv"])
    if step.get("stdin"):
        texte += f"  < [{step['stdin']}]"
    return texte


def execute(steps, secrets=None, run=subprocess.run, log=print):
    """Lance `steps` dans l'ordre et s'arrête au premier échec. Rend
    (True, None, 0) ou (False, indice de l'étape, code).

    Une étape à « stdin » reçoit secrets[nom] encodé en UTF-8, sans fin
    de ligne ajoutée ; les autres ont une entrée standard vide, pour
    qu'aucun outil n'attende une réponse au clavier. La sortie de chaque
    commande va à `log`, ligne par ligne."""
    secrets = secrets or {}
    for i, step in enumerate(steps):
        log(f"$ {describe(step)}")
        nom = step.get("stdin")
        kwargs = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "check": False,
        }
        if nom:
            if not secrets.get(nom):
                log(f"missing secret: {nom}")
                return False, i, 2
            kwargs["input"] = secrets[nom].encode("utf-8")
        else:
            kwargs["stdin"] = subprocess.DEVNULL
        try:
            res = run(step["argv"], **kwargs)
        except OSError as exc:
            log(f"cannot run {step['argv'][0]}: {exc}")
            return False, i, 127
        for ligne in (
            (res.stdout or b"").decode("utf-8", "replace").splitlines()
        ):
            log(f"  {ligne}")
        if res.returncode != 0:
            log(f"exit code {res.returncode}")
            return False, i, res.returncode
    return True, None, 0


def teardown(lay, run=subprocess.run, log=print, target=TARGET):
    """teardown_steps() exécutées une à une, sans s'arrêter aux échecs."""
    for step in teardown_steps(lay, target):
        execute([step], run=run, log=log)


def blkid_uuid(dev, run=subprocess.run):
    """L'UUID du système de fichiers (ou de l'en-tête LUKS) de `dev`, ou
    None."""
    try:
        res = run(
            ["blkid", "-s", "UUID", "-o", "value", dev],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    valeur = (res.stdout or "").strip()
    return valeur if res.returncode == 0 and valeur else None


def missing_uuids(lay, uuids):
    """Les noms des UUID de `uuids` (read_uuids) sans lesquels la cible ne
    démarre pas : en-tête LUKS de la racine (rd.luks.name) et, s'il y a
    un volume secret, son en-tête (crypttab) ; la racine elle-même
    (root=UUID=) sans LUKS. Un UUID absent s'écrirait « None » dans la
    ligne du noyau, et l'installation réussirait sur une machine qui
    attend à jamais un périphérique inexistant."""
    requis = ["root_uuid"]
    if lay.get("luks"):
        requis = ["luks_uuid"]
        if lay.get("secret_dev"):
            requis.append("secret_luks_uuid")
    return [n for n in requis if not (uuids or {}).get(n)]


def read_uuids(lay, run=subprocess.run):
    """Les UUID dont le chargeur et l'initramfs ont besoin, lus après le
    plan : en-tête LUKS de la racine (rd.luks.name), système racine,
    swap (fstab), en-tête LUKS du volume secret (crypttab)."""
    return {
        "luks_uuid": blkid_uuid(lay["root_part"], run)
        if lay["luks"]
        else None,
        "root_uuid": blkid_uuid(lay["root_dev"], run),
        "boot_uuid": blkid_uuid(lay["boot_dev"], run),
        "swap_uuid": blkid_uuid(lay["swap_dev"], run)
        if lay.get("swap_dev")
        else None,
        "secret_luks_uuid": blkid_uuid(lay["secret_dev"], run)
        if lay.get("secret_dev")
        else None,
    }
