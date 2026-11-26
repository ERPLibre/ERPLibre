# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Rendu d'une spec résolue en document `.tf.json` pour `bpg/proxmox`.

`rendre` est pure : pas d'E/S, pas de secret. Le jeton d'API et la phrase
d'état passent par l'environnement du sous-processus `tofu`, jamais par le
document. Syntaxe JSON d'OpenTofu : les blocs imbriqués répétables (`disk`,
`network_device`, `ip_config`) sont des tableaux d'objets, les blocs uniques
des objets, et une référence entre ressources une chaîne `${...}`.
"""

import re
from urllib.parse import urlsplit

from script.todo.todo_i18n import t

_RE_NOM = re.compile(r"[^A-Za-z0-9_]")


_CLES_CARTE_RESEAU = (
    "bridge",
    "disconnected",
    "enabled",
    "firewall",
    "mac_address",
    "model",
    "mtu",
    "queues",
    "rate_limit",
    "trunks",
    "vlan_id",
)


def _assainir(nom):
    """Nom utilisable comme identifiant de ressource OpenTofu."""
    return _RE_NOM.sub("_", nom)


def _taille_gio(disque):
    """Entier de Gio d'une taille « 20G »."""
    return int(disque[:-1])


def _ssh(cible):
    """Bloc `ssh` du fournisseur : agent, compte et port de l'hôte, adresse
    du nœud.

    Le compte et le port sont ceux que `ssh -G` donne pour la cible de
    l'hôte (`ssh_user`, `ssh_port`), pas le compte des VM : bpg se connecte
    au nœud Proxmox. L'adresse est l'hôte de `api_url`, celle que
    l'opérateur joint déjà. Sans bloc `node`, bpg prend la première
    interface du nœud qui porte une IPv4, et un pont interne sans passerelle
    est de celles-là : l'écriture des snippets partirait vers une adresse
    injoignable de l'opérateur.
    """
    ssh = {"agent": True, "username": cible.get("ssh_user") or ""}
    adresse = urlsplit(cible.get("api_url") or "").hostname
    if adresse and cible.get("noeud"):
        noeud = {"name": cible["noeud"], "address": adresse}
        if cible.get("ssh_port"):
            noeud["port"] = int(cible["ssh_port"])
        ssh["node"] = [noeud]
    return ssh


def _image(cible, donnees):
    """Ressource de téléchargement d'une image dans le stockage `import`.

    `stockage_snippets` désigne le stockage de type dossier qui porte les
    contenus `snippets` et `import` ; le `import_from` des disques référence
    ce même identifiant.
    """
    res = {
        "content_type": "import",
        "datastore_id": cible["stockage_snippets"],
        "node_name": cible["noeud"],
        "url": donnees["url"],
        "file_name": donnees["fichier"],
        "overwrite_unmanaged": True,
    }
    if donnees.get("sha256"):
        res["checksum"] = donnees["sha256"]
        res["checksum_algorithm"] = "sha256"
    return res


def _initialisation(cible, vm, nom_ud):
    """Bloc cloud-init : lecteur scsi1, réseau fixe ou DHCP, user-data."""
    ipv4 = {"address": "dhcp"}
    if vm["ip"] != "dhcp":
        ipv4 = {"address": vm["ip"], "gateway": vm["passerelle"]}
    init = {
        "interface": "scsi1",
        "datastore_id": cible["stockage"],
        "ip_config": [{"ipv4": ipv4}],
        "user_data_file_id": f"${{proxmox_virtual_environment_file.{nom_ud}.id}}",
    }
    # Le DNS ne se pose qu'en adresse fixe : en DHCP le bail le fournit.
    if vm["ip"] != "dhcp" and vm.get("dns"):
        init["dns"] = {"servers": list(vm["dns"])}
    return init


def _carte_reseau(pont):
    """Carte réseau virtio sur `pont`.

    Chez bpg, `network_device` est un ATTRIBUT `list(object)` et non un bloc :
    la syntaxe JSON exige chaque clé de l'objet, `null` valant le défaut du
    fournisseur.
    """
    carte = dict.fromkeys(_CLES_CARTE_RESEAU)
    carte.update({"bridge": pont, "model": "virtio"})
    return carte


def _vm(cible, vm, donnees_vm, nom_img, nom_ud):
    """Ressource VM : mêmes réglages que la séquence `qm` du chemin SSH."""
    res = {
        "node_name": cible["noeud"],
        "vm_id": vm["vmid"],
        "name": vm["nom"],
        "started": bool(vm["demarrer"]),
        "stop_on_destroy": True,
        "cpu": {"type": "host", "cores": vm["vcpus"]},
        "memory": {"dedicated": vm["ram"]},
        "operating_system": {"type": "l26"},
        "scsi_hardware": "virtio-scsi-single",
        "network_device": [_carte_reseau(cible["pont"])],
        "serial_device": [{"device": "socket"}],
        "vga": {"type": "serial0"},
        # Le disque est importé par l'API depuis le stockage `import`, sans SSH.
        "disk": [
            {
                "interface": "scsi0",
                "datastore_id": cible["stockage"],
                # Forme littérale `<stockage>:import/<fichier>` plus
                # `depends_on`, éprouvée par un apply sur un vrai PVE ; la doc
                # bpg montre aussi `import_from = <download_file>.id`.
                "import_from": (
                    f"{cible['stockage_snippets']}:import/{donnees_vm['fichier']}"
                ),
                "size": _taille_gio(vm["disque"]),
                "discard": "on",
                "ssd": True,
                "iothread": True,
            }
        ],
        "initialization": _initialisation(cible, vm, nom_ud),
        # L'image n'a pas l'agent au premier démarrage : ne pas l'attendre.
        "agent": {
            "enabled": True,
            "timeout": "2m",
            "wait_for_ip": {"disabled": True},
        },
        "boot_order": ["scsi0"],
        "depends_on": [
            f"proxmox_download_file.{nom_img}",
            f"proxmox_virtual_environment_file.{nom_ud}",
        ],
    }
    if donnees_vm.get("uefi"):
        res["bios"] = "ovmf"
        res["efi_disk"] = {
            "datastore_id": cible["stockage"],
            "type": "4m",
            "pre_enrolled_keys": False,
        }
    return res


def rendre(spec, donnees, conf):
    """Document `.tf.json` de `spec` ; `donnees` est indexé par nom de VM."""
    cible = spec["cible"]
    telechargements = {}
    fichiers = {}
    machines = {}
    sorties = {}
    for vm in spec["vms"]:
        d = donnees[vm["nom"]]
        nom_img = "img_" + _assainir(d["fichier"])
        nom_ud = "ud_" + _assainir(vm["nom"])
        nom_vm = "vm_" + _assainir(vm["nom"])
        image = _image(cible, d)
        # Un même nom de fichier avec une autre source ferait écraser l'image
        # d'une VM par celle d'une autre dans le stockage.
        if telechargements.setdefault(nom_img, image) != image:
            raise ValueError(
                t("Image {fichier} has two different sources.").format(
                    fichier=d["fichier"]
                )
            )
        fichiers[nom_ud] = {
            "content_type": "snippets",
            "datastore_id": cible["stockage_snippets"],
            "node_name": cible["noeud"],
            "source_raw": {
                "data": d["user_data"],
                # Le parc dans le nom : deux parcs sur un même hôte et
                # stockage ont chacun leur fichier pour une VM homonyme.
                "file_name": f"erplibre-{spec['nom']}-{vm['nom']}.yml",
            },
        }
        machines[nom_vm] = _vm(cible, vm, d, nom_img, nom_ud)
        sorties[vm["nom"]] = {
            "vmid": vm["vmid"],
            "ipv4": f"${{proxmox_virtual_environment_vm.{nom_vm}.ipv4_addresses}}",
        }
    return {
        "terraform": {
            "required_version": conf["required_version"],
            "required_providers": {
                "proxmox": {
                    "source": "bpg/proxmox",
                    "version": conf["providers"]["bpg/proxmox"],
                }
            },
        },
        "provider": {
            "proxmox": {
                "endpoint": cible["api_url"],
                "insecure": cible["insecure"],
                "ssh": _ssh(cible),
            }
        },
        "resource": {
            "proxmox_download_file": telechargements,
            "proxmox_virtual_environment_file": fichiers,
            "proxmox_virtual_environment_vm": machines,
        },
        "output": {"vms": {"value": sorties}},
    }
