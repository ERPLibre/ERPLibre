# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Résolution d'une spec sur l'hôte Proxmox, et données éphémères par VM.

`resoudre` remplit, depuis l'hôte vivant, les seuls champs que la spec laisse
vides ; un champ renseigné n'est jamais relu ni écrasé, donc une deuxième
résolution ne change rien. `donnees_vm` calcule ce qui ne se sauve pas (URL
d'image, user-data) et que le moteur consomme au rendu.

Toute lecture distante qui échoue lève `ResolutionImpossible` : un code de
retour non nul distingue une lecture impossible d'une lecture qui ne rend rien, et
conclure le second du premier ferait inventer un état à l'hôte.
"""

import copy
import importlib.util
import os
import subprocess
from pathlib import Path
from typing import Callable

from script.proxmox import proxmox_deploy as pve
from script.todo.todo_i18n import t

Executer = Callable[[str], tuple]

_DEPLOY_QEMU = Path(__file__).resolve().parent.parent / "qemu" / "deploy_qemu.py"
_VMID_MIN = 100
_cache_qemu = None


class ResolutionImpossible(Exception):
    """Lecture de l'hôte ou donnée de VM impossible ; message traduit."""


def adresse_hote(target):
    """Valeur `hostname` de `ssh -G <target>` : l'adresse réelle de l'alias."""
    try:
        res = subprocess.run(
            ["ssh", "-G", target], capture_output=True, text=True, timeout=15
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ResolutionImpossible(
            t("Cannot run ssh -G {cible}: {err}").format(cible=target, err=exc)
        )
    if res.returncode == 0:
        for ligne in res.stdout.splitlines():
            cle, _, valeur = ligne.partition(" ")
            if cle == "hostname" and valeur.strip():
                return valeur.strip()
    raise ResolutionImpossible(
        t("ssh -G {cible} gave no host address.").format(cible=target)
    )


def executer_ssh(hote, timeout=120):
    """Exécuteur de commandes distantes pour `hote`, élevées par son sudo.

    L'élévation est faite ici, une seule fois : l'hôte passé à `pve.run` a un
    `sudo` vide, sans quoi la commande serait enrobée deux fois.
    """
    sudo = hote.get("sudo", "")
    brut = {
        "target": hote.get("target", ""),
        "jump": hote.get("jump", ""),
        "port": hote.get("port", ""),
        "sudo": "",
    }

    def executer(cmd):
        return pve.run(brut, pve.wrap_privilege(cmd, sudo), timeout)

    return executer


def charger_deploy_qemu():
    """Le module `deploy_qemu`, chargé une fois par fichier puis mémorisé."""
    global _cache_qemu
    if _cache_qemu is None:
        spec = importlib.util.spec_from_file_location("deploy_qemu", _DEPLOY_QEMU)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _cache_qemu = mod
    return _cache_qemu


def _lire(executer, cmd):
    """Sortie de `cmd`, ou `ResolutionImpossible` nommant la commande."""
    code, sortie = executer(cmd)
    if code != 0:
        raise ResolutionImpossible(
            t("Reading the host failed (exit {code}): {cmd}").format(code=code, cmd=cmd)
        )
    return sortie


def _stockage(executer, contenu, voulu=""):
    return pve.pick_storage(
        pve.parse_storages(_lire(executer, f"pvesm status --content {contenu}")),
        voulu,
    )


def _vmid_libre(pris):
    vmid = _VMID_MIN
    while vmid in pris:
        vmid += 1
    return vmid


def resoudre(spec, executer, adresse):
    """(spec_neuve, change) : la spec avec ses champs vides remplis.

    N'écrit que les champs vides, ne mute pas `spec`, ne lit l'hôte que pour
    ce qui manque. `ip` "auto" devient "dhcp" sur un pont qui donne sur le
    LAN, sinon une adresse fixe dérivée du VMID avec sa passerelle et les
    résolveurs de l'hôte.
    """
    neuve = copy.deepcopy(spec)
    cible = neuve["cible"]
    if not cible.get("api_url"):
        cible["api_url"] = f"https://{adresse}:8006/"
    if not cible.get("noeud"):
        cible["noeud"] = _lire(executer, "hostname").strip()
    if not cible.get("stockage"):
        cible["stockage"] = _stockage(executer, "images")
        if not cible["stockage"]:
            raise ResolutionImpossible(
                t("No active storage accepts disk images on the host.")
            )
    if not cible.get("stockage_snippets"):
        cible["stockage_snippets"] = _stockage(executer, "snippets")
        if not cible["stockage_snippets"]:
            raise ResolutionImpossible(
                t(
                    "No storage accepts snippets: run Prepare the host "
                    "(Préparer l'hôte) first."
                )
            )
    if not cible.get("pont"):
        ponts = pve.parse_bridges(_lire(executer, "ip -o link show type bridge"))
        cible["pont"] = pve.pick_bridge(ponts)
        if not cible["pont"]:
            raise ResolutionImpossible(t("The host has no network bridge."))
    vms = neuve["vms"]
    if any(vm.get("vmid") is None for vm in vms):
        pris = {v["vmid"] for v in pve.parse_qm_list(_lire(executer, "qm list"))}
        pris |= {vm["vmid"] for vm in vms if vm.get("vmid") is not None}
        for vm in vms:
            if vm.get("vmid") is None:
                vm["vmid"] = _vmid_libre(pris)
                pris.add(vm["vmid"])
    if any(vm.get("ip") == "auto" for vm in vms):
        infos = pve.parse_bridge_config(_lire(executer, "cat /etc/network/interfaces"))
        serveurs = pve.parse_nameservers(_lire(executer, pve.RESOLV_CMD))
        for vm in vms:
            if vm.get("ip") != "auto":
                continue
            ipconfig = pve.ipconfig_for(infos.get(cible["pont"], {}), vm["vmid"])
            if ipconfig == "ip=dhcp":
                vm["ip"] = "dhcp"
                continue
            adresse_ip, _, passerelle = ipconfig[len("ip=") :].partition(",gw=")
            vm["ip"] = adresse_ip
            vm["passerelle"] = passerelle
            vm["dns"] = list(serveurs)
    return neuve, neuve != spec


def _cle_publique(chemin):
    try:
        with open(os.path.expanduser(chemin), encoding="utf-8") as fh:
            cle = fh.read().strip()
    except OSError as exc:
        raise ResolutionImpossible(
            t("SSH public key unreadable: {err}").format(err=exc)
        )
    if not cle:
        raise ResolutionImpossible(
            t("SSH public key is empty: {chemin}").format(chemin=chemin)
        )
    return cle


def donnees_vm(spec, vm, mod_qemu):
    """Données éphémères d'une VM : image source et user-data cloud-init.

    Jamais sauvées dans la spec. `fichier` garde le nom du catalogue avec
    l'extension `.qcow2`, la seule que le contenu `import` de PVE accepte
    pour une image disque.
    """
    distro, version, arch = vm["distro"], vm["version"], vm["arch"]
    code = mod_qemu.DISTROS[distro][0][version][0]
    url = mod_qemu.image_url(distro, code, arch, version)
    if "<" in url:
        raise ResolutionImpossible(
            t("Image URL of {distro} {version} is not resolved: {url}").format(
                distro=distro, version=version, url=url
            )
        )
    fichier = mod_qemu.default_image_name(distro, code, arch, version)
    if fichier.endswith(".img"):
        fichier = fichier[: -len(".img")] + ".qcow2"
    cle = _cle_publique(spec["compte"]["ssh_key"])
    args = mod_qemu.build_parser().parse_args(
        [
            "--distro",
            distro,
            "--hostname",
            vm["nom"],
            "--user",
            spec["compte"]["user"],
        ]
    )
    return {
        "url": url,
        "fichier": fichier,
        "sha256": mod_qemu.pinned_sha256(distro),
        "uefi": mod_qemu.requiert_uefi(distro),
        "user_data": mod_qemu.build_cloud_config(args, None, [cle]),
    }
