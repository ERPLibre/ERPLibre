#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La mémoire de chaque carte graphique, et ce qu'en tient chaque processus.

Deux sources, selon le pilote de la carte :

- NVIDIA (pilote propriétaire « nvidia ») : nvidia-smi. Sa sortie XML
  (« nvidia-smi -q -x ») liste les processus de calcul (C) ET graphiques
  (G) ; la requête CSV « --query-compute-apps » ne voit que les premiers,
  et ne sert que de repli quand le XML ne se lit pas.
- Tout autre pilote DRM (amdgpu, i915, xe, msm, panfrost…) :
  /proc/<pid>/fdinfo de chaque descripteur ouvert sur /dev/dri, où le
  noyau publie « drm-client-id » et la mémoire par région (vram, gtt,
  system0, local0…). Un pilote qui n'y publie rien, virtio_gpu par
  exemple, laisse des processus qui tiennent la carte sans chiffre.

Lecture seule. Le fdinfo d'un processus d'un autre compte ne se lit qu'en
root : ces processus sont COMPTÉS, pour que l'appelant dise ce qu'il ne
voit pas au lieu de laisser croire que la carte est vide, et propose
drm_sudo(), qui refait la même lecture en root. nvidia-smi, lui, rend la
mémoire des processus de tous les comptes sans privilège.

Ce module ne rend que des faits — octets, PID, noms —, la mise en forme
appartient au menu.
"""

import csv
import inspect
import json
import os
import pwd
import shutil
import subprocess
import xml.etree.ElementTree as ET

from script.todo.system_diagnostic import commande, lire

# Identifiant PCI du fabricant -> nom, pour la carte comme pour le choix de
# la source.
FABRICANTS = {
    "0x10de": "NVIDIA",
    "0x1002": "AMD",
    "0x8086": "Intel",
    "0x1af4": "Virtio",
    "0x1b36": "QEMU",
    "0x1234": "QEMU",
    "0x15ad": "VMware",
    "0x80ee": "VirtualBox",
    "0x1a03": "ASPEED",
    "0x102b": "Matrox",
}

UNITES = {"": 1, "B": 1, "KiB": 1024, "MiB": 1024**2, "GiB": 1024**3}

# Dans fdinfo, la même région peut paraître sous plusieurs familles. La
# première trouvée dans cet ordre donne la valeur : « resident » est ce qui
# occupe réellement la région, « memory » son ancien nom chez amdgpu,
# « total » ce qui est alloué, résident ou non.
FAMILLES = ("drm-resident-", "drm-memory-", "drm-total-")

TIMEOUT_NVIDIA = 15


def taille(texte, unite_defaut=""):
    """« 812 MiB », « 4096 KiB », « 0 » -> octets ; None si ce n'est pas
    un nombre (« N/A », « [Not Supported] »)."""
    if texte is None:
        return None
    morceaux = texte.strip().split()
    if not morceaux:
        return None
    unite = morceaux[1] if len(morceaux) > 1 else unite_defaut
    if unite not in UNITES:
        return None
    try:
        return int(morceaux[0]) * UNITES[unite]
    except ValueError:
        return None


def proprietaire(pid, proc="/proc"):
    """Le compte qui possède le processus, ou None s'il a disparu."""
    try:
        uid = os.stat(os.path.join(proc, str(pid))).st_uid
    except OSError:
        return None
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return str(uid)


def ligne_commande(pid, proc="/proc"):
    """La ligne de commande entière du processus, ou None. Elle n'est pas
    coupée : ce qui distingue deux processus — la VM d'un qemu, le profil
    d'un navigateur — se trouve souvent en fin de ligne."""
    brut = lire(os.path.join(proc, str(pid), "cmdline"))
    if not brut:
        return None
    return " ".join(brut.rstrip("\0").split("\0"))


def nom_processus(pid, proc="/proc"):
    """Le nom court (comm) du processus, ou None."""
    brut = lire(os.path.join(proc, str(pid), "comm"))
    return brut.strip() if brut else None


def cartes(sys_drm="/sys/class/drm"):
    """Les cartes DRM du poste : [{carte, pci, fabricant, pilote, modele,
    vram_totale, vram_utilisee}]. Les deux dernières ne viennent que
    d'amdgpu, qui les publie dans sysfs ; None ailleurs."""
    try:
        noms = sorted(os.listdir(sys_drm))
    except OSError:
        return []
    res = []
    for nom in noms:
        if not (nom.startswith("card") and nom[4:].isdigit()):
            continue
        appareil = os.path.join(sys_drm, nom, "device")
        if not os.path.isdir(appareil):
            continue
        fabricant = (lire(os.path.join(appareil, "vendor")) or "").strip()
        pilote = os.path.basename(
            os.path.realpath(os.path.join(appareil, "driver"))
        )
        pci = os.path.basename(os.path.realpath(appareil))
        modele = None
        sortie = commande(["lspci", "-s", pci])
        if sortie:
            modele = sortie.splitlines()[0].split(": ", 1)[-1].strip()

        def nombre(fichier):
            brut = lire(os.path.join(appareil, fichier))
            try:
                return int(brut) if brut is not None else None
            except ValueError:
                return None

        res.append(
            {
                "carte": nom,
                "pci": pci,
                "fabricant": FABRICANTS.get(fabricant, fabricant or None),
                "pilote": pilote,
                "modele": modele,
                "vram_totale": nombre("mem_info_vram_total"),
                "vram_utilisee": nombre("mem_info_vram_used"),
            }
        )
    return res


def nvidia_xml(sortie):
    """Les cartes et leurs processus, depuis « nvidia-smi -q -x » ; None si
    le XML ne se lit pas."""
    try:
        racine = ET.fromstring(sortie)
    except ET.ParseError:
        return None
    gpus = []
    for index, gpu in enumerate(racine.findall("gpu")):
        processus = []
        for p in gpu.findall("processes/process_info"):
            try:
                pid = int(p.findtext("pid", ""))
            except ValueError:
                continue
            processus.append(
                {
                    "pid": pid,
                    "type": (p.findtext("type") or "").strip() or None,
                    "nom": (p.findtext("process_name") or "").strip() or None,
                    "memoire": taille(p.findtext("used_memory")),
                }
            )
        gpus.append(
            {
                "index": index,
                "uuid": (gpu.findtext("uuid") or "").strip() or None,
                "nom": (gpu.findtext("product_name") or "").strip() or None,
                "pci": gpu.get("id"),
                "utilisee": taille(gpu.findtext("fb_memory_usage/used")),
                "totale": taille(gpu.findtext("fb_memory_usage/total")),
                "processus": processus,
            }
        )
    return gpus


def nvidia_csv(sortie_gpus, sortie_apps):
    """Les cartes et leurs processus de CALCUL seulement, depuis les
    requêtes CSV (« noheader,nounits » : la mémoire est en MiB)."""
    gpus, par_uuid = [], {}
    for champs in csv.reader(sortie_gpus.splitlines(), skipinitialspace=True):
        if len(champs) < 5:
            continue
        try:
            index = int(champs[0])
        except ValueError:
            continue
        gpu = {
            "index": index,
            "uuid": champs[1],
            "nom": champs[2],
            "pci": None,
            "utilisee": taille(champs[3], "MiB"),
            "totale": taille(champs[4], "MiB"),
            "processus": [],
        }
        gpus.append(gpu)
        par_uuid[champs[1]] = gpu
    for ligne in sortie_apps.splitlines():
        # Le nom du processus peut porter une virgule : le PID se prend au
        # début, la mémoire et l'UUID à la fin.
        tete, _, reste = ligne.partition(",")
        morceaux = reste.rsplit(",", 2)
        if len(morceaux) != 3:
            continue
        try:
            pid = int(tete.strip())
        except ValueError:
            continue
        gpu = par_uuid.get(morceaux[2].strip())
        if gpu is None:
            continue
        gpu["processus"].append(
            {
                "pid": pid,
                "type": "C",
                "nom": morceaux[0].strip() or None,
                "memoire": taille(morceaux[1], "MiB"),
            }
        )
    return gpus


def nvidia():
    """{source, gpus} lus par nvidia-smi, ou None s'il manque ou échoue."""
    sortie = commande(["nvidia-smi", "-q", "-x"], timeout=TIMEOUT_NVIDIA)
    gpus = nvidia_xml(sortie) if sortie else None
    if gpus is not None:
        return {"source": "nvidia-smi -q -x", "gpus": gpus}
    sortie_gpus = commande(
        [
            "nvidia-smi",
            "--query-gpu=index,uuid,name,memory.used,memory.total",
            "--format=csv,noheader,nounits",
        ],
        timeout=TIMEOUT_NVIDIA,
    )
    if sortie_gpus is None:
        return None
    sortie_apps = commande(
        [
            "nvidia-smi",
            "--query-compute-apps=pid,process_name,used_memory,gpu_uuid",
            "--format=csv,noheader,nounits",
        ],
        timeout=TIMEOUT_NVIDIA,
    )
    return {
        "source": "nvidia-smi --query-compute-apps",
        "gpus": nvidia_csv(sortie_gpus, sortie_apps or ""),
    }


def lire_fdinfo(texte):
    """Les clés « drm-* » d'un fdinfo, valeurs brutes."""
    res = {}
    for ligne in (texte or "").splitlines():
        cle, sep, valeur = ligne.partition(":")
        if sep and cle.startswith("drm-"):
            res[cle.strip()] = valeur.strip()
    return res


def regions(cles):
    """{région: octets} d'un client DRM, une valeur par région selon
    FAMILLES."""
    res = {}
    for famille in FAMILLES:
        for cle, valeur in cles.items():
            if not cle.startswith(famille):
                continue
            region = cle[len(famille) :]
            if region in res:
                continue
            octets = taille(valeur)
            if octets is not None:
                res[region] = octets
    return res


def drm(proc="/proc"):
    """Les clients DRM visibles par /proc/<pid>/fdinfo.

    Rend {"processus": [{pid, pci, pilote, regions}], "sans_stats": [{pid,
    nom}],
    "illisibles": n}. Un client (drm-client-id) partagé par plusieurs
    descripteurs ou processus, après un fork, n'est compté qu'une fois,
    au premier PID qui le montre. `sans_stats` : les processus qui tiennent
    /dev/dri sans que le pilote publie de mémoire. `illisibles` : les
    processus dont les descripteurs ne se lisent pas, ceux d'un autre
    compte sans root, fils du noyau exclus."""
    vus, par_pid, sans_stats, illisibles = set(), {}, [], 0
    try:
        pids = sorted(int(n) for n in os.listdir(proc) if n.isdigit())
    except OSError:
        return {"processus": [], "sans_stats": [], "illisibles": 0}
    for pid in pids:
        dossier_fd = os.path.join(proc, str(pid), "fd")
        try:
            fds = os.listdir(dossier_fd)
        except PermissionError:
            # Un fil du noyau (cmdline vide) n'ouvre jamais /dev/dri : seul
            # un vrai processus d'un autre compte est un angle mort.
            if lire(os.path.join(proc, str(pid), "cmdline")):
                illisibles += 1
            continue
        except OSError:
            continue
        tient_dri = client_vu = False
        for fd in fds:
            try:
                cible = os.readlink(os.path.join(dossier_fd, fd))
            except OSError:
                continue
            if not cible.startswith("/dev/dri/"):
                continue
            tient_dri = True
            cles = lire_fdinfo(
                lire(os.path.join(proc, str(pid), "fdinfo", fd))
            )
            client = cles.get("drm-client-id")
            if client is None:
                continue
            client_vu = True
            pci = cles.get("drm-pdev")
            pilote = cles.get("drm-driver")
            if (pci or pilote, client) in vus:
                continue
            vus.add((pci or pilote, client))
            entree = par_pid.setdefault(
                (pid, pci),
                {"pid": pid, "pci": pci, "pilote": pilote, "regions": {}},
            )
            for region, octets in regions(cles).items():
                entree["regions"][region] = (
                    entree["regions"].get(region, 0) + octets
                )
        if tient_dri and not client_vu:
            sans_stats.append({"pid": pid, "nom": nom_processus(pid, proc)})
    return {
        "processus": list(par_pid.values()),
        "sans_stats": sans_stats,
        "illisibles": illisibles,
    }


def code_sudo():
    """Le programme que drm_sudo() fait lancer en root : drm() et ce qu'elle
    appelle, recopiés depuis ce module, qui écrit son résultat en JSON.

    Le programme se suffit à lui-même — os, json et sys seulement —, pour
    que « python3 -I » le lance sans le venv ni le dépôt dans son chemin
    d'import : root n'importe rien d'autre que ce texte."""
    morceaux = [
        "import json, os, sys",
        f"UNITES = {UNITES!r}",
        f"FAMILLES = {FAMILLES!r}",
    ]
    for fonction in (lire, taille, lire_fdinfo, regions, nom_processus, drm):
        morceaux.append(inspect.getsource(fonction))
    morceaux.append("print(json.dumps(drm(*sys.argv[1:2])))")
    return "\n\n".join(morceaux)


def drm_sudo(proc=None):
    """drm() relue en root par sudo, ou None si sudo échoue, est refusé ou
    interrompu (Ctrl-C au mot de passe).

    sudo demande le mot de passe sur le terminal lui-même : l'entrée et la
    sortie d'erreur restent celles de l'appelant, seule la sortie standard,
    le JSON, est capturée. Pas de délai : la saisie du mot de passe a celui
    de sudo. L'interpréteur est le python3 du secure_path de sudo, pas
    celui du venv."""
    args = ["sudo", "--", "python3", "-I", "-c", code_sudo()]
    if proc:
        args.append(proc)
    try:
        res = subprocess.run(args, stdout=subprocess.PIPE, text=True)
    except (OSError, KeyboardInterrupt):
        return None
    if res.returncode != 0:
        return None
    try:
        lu = json.loads(res.stdout)
    except ValueError:
        return None
    if not isinstance(lu, dict) or "processus" not in lu:
        return None
    lu["sudo"] = True
    return lu


def completer(processus, proc="/proc"):
    """Ajoute à chaque processus son compte, son nom court s'il manque, et
    sa ligne de commande."""
    for p in processus:
        p["compte"] = proprietaire(p["pid"], proc)
        if not p.get("nom"):
            p["nom"] = nom_processus(p["pid"], proc)
        p["commande"] = ligne_commande(p["pid"], proc)
    return processus


def collecter(proc="/proc", sys_drm="/sys/class/drm"):
    """La mémoire GPU, carte par carte et processus par processus.

    Rend {"cartes", "nvidia", "drm", "nvidia_sans_reponse"}. nvidia-smi
    est interrogé dès qu'il est installé ou qu'une carte tourne sous le
    pilote « nvidia » ; `nvidia_sans_reponse` dit qu'une telle carte est là
    mais que nvidia-smi manque ou échoue. fdinfo est lu dès qu'une carte tourne sous un autre pilote — ou
    quand aucune carte n'est vue, pour ne rien manquer."""
    liste = cartes(sys_drm)
    pilotes = {c["pilote"] for c in liste}
    res = {
        "cartes": liste,
        "nvidia": None,
        "drm": None,
        "nvidia_sans_reponse": False,
    }
    if "nvidia" in pilotes or shutil.which("nvidia-smi"):
        res["nvidia"] = nvidia()
        if res["nvidia"] is None and "nvidia" in pilotes:
            res["nvidia_sans_reponse"] = True
        for gpu in (res["nvidia"] or {}).get("gpus", []):
            completer(gpu["processus"], proc)
    if not liste or pilotes - {"nvidia"}:
        res["drm"] = drm(proc)
        completer(res["drm"]["processus"], proc)
    return res
