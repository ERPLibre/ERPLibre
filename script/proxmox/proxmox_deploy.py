#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Déploiement de VM SUR un hôte Proxmox VE, piloté à distance par SSH.

Différence de nature avec `script/qemu/deploy_qemu.py` : là-bas, l'hyperviseur
est la machine qui exécute le script. Ici, il est AILLEURS — « on n'exécute pas
dessus ». Tout ce que ce module produit part donc sur l'hôte choisi, et rien
n'exige de privilège local.

Pourquoi SSH et `qm` plutôt que l'API REST : l'API demande un jeton ou un
ticket à créer et à renouveler, quand `qm` est la voie que tout administrateur
Proxmox connaît, et que le dépôt sait déjà gérer des accès SSH (~/.ssh/config,
ProxyJump, clés). Les commandes restent lisibles dans le journal, donc
rejouables à la main — c'est ce qui a permis de diagnostiquer chaque panne de
ce module.

Découpage voulu : TOUT ce qui construit une commande ou lit une sortie est une
fonction PURE, vérifiable sans hôte Proxmox. Seul `run()` parle au réseau.
"""
from __future__ import annotations

import json
import re
import shlex
import subprocess

# Réglages par défaut d'une VM Proxmox. Chacun a sa raison :
#
# - virtio-scsi-single : le contrôleur que Proxmox recommande depuis PVE 7, et
#   le seul qui donne l'iothread par disque.
# - agent enabled=1 : sans l'agent invité, « qm guest cmd » ne rend aucune
#   adresse IP et le menu ne peut pas dire où joindre la VM.
# - serial0 socket + vga serial0 : c'est ce qui rend « qm terminal » utilisable.
#   Une console graphique seule obligerait à passer par l'interface web.
# - ostype l26 : Linux 2.6+, ce qui règle les horloges et les pilotes.
DEFAULT_BRIDGE = "vmbr0"
DEFAULT_STORAGE = ""  # vide = on choisit d'après « pvesm status »
IMAGE_DIR = "/var/lib/vz/template/iso"
VMID_MIN = 100

# Stockages qui savent héberger un disque de VM. « pvesm status » liste aussi
# des stockages de sauvegarde ou d'ISO, où un disque ne peut PAS aller : les
# proposer produirait un « qm set » refusé après le téléchargement de l'image.
DISK_CONTENT = ("images", "rootdir")


def ssh_argv(host: dict, remote: str, tty: bool = False) -> list:
    """Commande ssh complète pour exécuter `remote` sur l'hôte Proxmox.

    `host` : {"target": "root@10.0.0.5", "jump": "rebond", "port": "22"} —
    « target » suffit quand l'alias vient de ~/.ssh/config, qui porte déjà
    l'utilisateur, le port et le ProxyJump.
    """
    argv = ["ssh"]
    if not tty:
        argv += ["-o", "BatchMode=yes"]
    argv += ["-o", "ConnectTimeout=10"]
    if host.get("port"):
        argv += ["-p", str(host["port"])]
    if host.get("jump"):
        argv += ["-J", host["jump"]]
    if tty:
        argv.append("-t")
    argv += [host["target"], remote]
    return argv


def wrap_privilege(remote: str, prefix: str) -> str:
    """Enveloppe la commande pour qu'elle tourne en root, si nécessaire.

    « sudo sh -c '<tout>' » et non « sudo <tout> » : les commandes de ce module
    sont des SUITES (« mkdir && if … fi », une boucle for, une redirection).
    Préfixer par sudo n'élèverait que le premier mot, et la redirection
    resterait celle du shell non privilégié — donc « permission denied » sur
    /root ou /boot/efi.
    """
    if not prefix:
        return remote
    return "sudo sh -c " + shlex.quote(remote)


def run(host: dict, remote: str, timeout: int = 120) -> tuple:
    """(code, sortie) de `remote` exécuté sur l'hôte. Ne lève jamais.

    `host["sudo"]` non vide -> la commande passe par sudo : « qm » exige les
    privilèges, et l'accès offert par une VM du parc est celui d'`erplibre`.
    """
    remote = wrap_privilege(remote, host.get("sudo") or "")
    try:
        res = subprocess.run(
            ssh_argv(host, remote),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return 255, "timeout"
    except (OSError, subprocess.SubprocessError) as exc:
        return 255, str(exc)
    return res.returncode, (res.stdout or "") + (res.stderr or "")


# --------------------------------------------------------------------------- #
# Lecture des sorties de l'hôte — fonctions pures
# --------------------------------------------------------------------------- #
def parse_pveversion(text: str) -> str:
    """« pve-manager/9.2.11/f6997e69 (running kernel: 7.0.14-12-pve) » -> 9.2.11.

    Sert de PREUVE que l'hôte est bien un Proxmox : une adresse saisie à la
    main peut être n'importe quoi, et la première commande `qm` échouerait
    alors sur un message qui ne dit pas pourquoi.
    """
    m = re.search(r"pve-manager/(\d[\w.]*)", text or "")
    return m.group(1) if m else ""


def parse_qm_list(text: str) -> list:
    """Sortie de « qm list » -> [{vmid, name, status, mem, disk}].

    L'en-tête et les lignes vides sont écartés. Les colonnes sont séparées par
    des espaces, mais un NOM peut en contenir : on découpe donc par la
    GAUCHE (vmid) et par la DROITE (status, mem, bootdisk, pid), et ce qui
    reste au milieu est le nom.
    """
    out = []
    for ligne in (text or "").splitlines():
        parts = ligne.split()
        if len(parts) < 6 or not parts[0].isdigit():
            continue
        vmid = parts[0]
        pid = parts[-1]
        bootdisk = parts[-2]
        mem = parts[-3]
        status = parts[-4]
        nom = " ".join(parts[1:-4])
        out.append(
            {
                "vmid": int(vmid),
                "name": nom,
                "status": status,
                "mem": mem,
                "disk": bootdisk,
                "pid": pid,
            }
        )
    return out


def parse_storages(text: str) -> list:
    """Sortie de « pvesm status --content images » -> [{name, type, avail}]."""
    out = []
    for ligne in (text or "").splitlines():
        parts = ligne.split()
        if len(parts) < 6 or parts[0] == "Name":
            continue
        try:
            avail = int(parts[5])
        except ValueError:
            continue
        out.append(
            {
                "name": parts[0],
                "type": parts[1],
                "actif": parts[2] == "active",
                "avail": avail * 1024,  # pvesm compte en Kio
            }
        )
    return out


def parse_bridges(text: str) -> list:
    """Sortie de « ip -o link show type bridge » -> ['vmbr0', …]."""
    ponts = []
    for ligne in (text or "").splitlines():
        parts = ligne.split(":")
        if len(parts) > 1:
            nom = parts[1].strip().split("@")[0]
            if nom:
                ponts.append(nom)
    return ponts


def parse_guest_ips(text: str) -> list:
    """Adresses IPv4 rendues par « qm guest cmd <id> network-get-interfaces ».

    L'agent invité répond du JSON. Les adresses de bouclage sont écartées : la
    question posée est « où joindre cette VM », et 127.0.0.1 n'y répond pas.
    """
    try:
        data = json.loads(text or "")
    except (ValueError, TypeError):
        return []
    ips = []
    for iface in data if isinstance(data, list) else []:
        for addr in iface.get("ip-addresses") or []:
            ip = addr.get("ip-address") or ""
            if addr.get("ip-address-type") == "ipv4" and not ip.startswith(
                "127."
            ):
                ips.append(ip)
    return ips


def mac_from_config(text: str) -> str:
    """MAC de net0 dans « qm config <id> ».

    C'est le seul lien entre une VM Proxmox et son adresse IP quand l'agent
    invité n'est pas là : l'image cloud Debian ne l'embarque PAS, et Proxmox ne
    distribue pas les baux lui-même — il ne peut donc pas répondre.
    """
    m = re.search(
        r"^net0:.*?([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})",
        text or "",
        re.M,
    )
    return m.group(1).lower() if m else ""


def ip_from_neigh(text: str, mac: str) -> str:
    """Adresse vue par le voisinage de l'hôte (« ip neigh »), pour cette MAC.

    Marche dès que la VM a émis un paquet — un bail DHCP suffit. C'est le
    repli quand l'agent invité manque, et il ne demande rien à l'invité.
    """
    if not mac:
        return ""
    cible = mac.lower()
    for ligne in (text or "").splitlines():
        if cible in ligne.lower():
            parts = ligne.split()
            if parts and re.match(r"^\d+\.\d+\.\d+\.\d+$", parts[0]):
                return parts[0]
    return ""


def next_vmid(existing, mini: int = VMID_MIN) -> int:
    """Premier VMID libre à partir de `mini`.

    Proxmox refuse un VMID déjà pris, et le message (« CT/VM 100 already
    exists ») arrive APRÈS le téléchargement de l'image : on choisit donc
    avant, d'après ce que l'hôte déclare.
    """
    pris = {int(v["vmid"]) for v in existing or () if str(v["vmid"]).isdigit()}
    vmid = max(mini, VMID_MIN)
    while vmid in pris:
        vmid += 1
    return vmid


def pick_storage(storages, voulu: str = "") -> str:
    """Stockage où poser le disque : celui demandé, sinon le plus libre.

    Aucun repli sur un nom devinné (« local-lvm » n'existe pas partout) : sans
    stockage utilisable, on rend une chaîne vide et l'appelant le dit.
    """
    utiles = [s for s in storages or () if s.get("actif")]
    if voulu:
        return voulu if any(s["name"] == voulu for s in utiles) else ""
    if not utiles:
        return ""
    return max(utiles, key=lambda s: s.get("avail") or 0)["name"]


def pick_bridge(bridges, voulu: str = "") -> str:
    """Pont réseau : celui demandé, sinon vmbr0, sinon le premier déclaré."""
    ponts = list(bridges or ())
    if voulu:
        return voulu if voulu in ponts else ""
    if DEFAULT_BRIDGE in ponts:
        return DEFAULT_BRIDGE
    return ponts[0] if ponts else ""


# --------------------------------------------------------------------------- #
# Construction des commandes — fonctions pures
# --------------------------------------------------------------------------- #
# Réseau interne proposé quand l'hôte n'a AUCUN pont. Choisi pour être sûr :
# un pont sans port physique ne peut pas couper l'accès SSH à l'hôte, alors
# qu'ajouter « bridge-ports enp1s0 » déplace l'adresse et coupe la session en
# cours — sur une machine distante, c'est un aller sans retour.
INTERNAL_BRIDGE = "vmbr0"
INTERNAL_CIDR = "10.10.10.1/24"


def parse_bridge_config(text: str) -> dict:
    """/etc/network/interfaces -> {pont: {ports, address}}.

    Sert à savoir si un pont donne sur le LAN (il a des ports) ou s'il est
    interne (« bridge-ports none ») : les VM du premier prennent leur adresse
    en DHCP, celles du second n'en auraient aucune et doivent recevoir une
    adresse fixe.
    """
    ponts = {}
    courant = ""
    for ligne in (text or "").splitlines():
        nu = ligne.strip()
        m = re.match(r"^iface\s+(\S+)\s", nu)
        if m:
            courant = m.group(1)
            continue
        if not courant:
            continue
        if nu.startswith("bridge-ports") or nu.startswith("bridge_ports"):
            ports = nu.split(None, 1)[1].strip() if " " in nu else ""
            ponts.setdefault(courant, {})["ports"] = (
                "" if ports in ("none", "") else ports
            )
        elif nu.startswith("address"):
            ponts.setdefault(courant, {})["address"] = nu.split()[1]
    return ponts


def bridge_setup_cmds(
    nom: str = INTERNAL_BRIDGE,
    cidr: str = INTERNAL_CIDR,
    uplink: str = "",
) -> list:
    """Crée un pont INTERNE, et le masque derrière l'uplink si demandé.

    « bridge-ports none » : aucune interface physique n'est touchée, donc
    l'accès à l'hôte survit. Les lignes post-up/post-down de masquerading sont
    celles que documente Proxmox pour un hôte à une seule adresse routée : sans
    elles les VM se parlent entre elles mais ne sortent pas.
    """
    reseau = cidr.rsplit(".", 1)[0] + ".0/" + cidr.split("/")[1]
    bloc = [
        "",
        f"auto {nom}",
        f"iface {nom} inet static",
        f"    address {cidr}",
        "    bridge-ports none",
        "    bridge-stp off",
        "    bridge-fd 0",
    ]
    if uplink:
        bloc += [
            f"    post-up   iptables -t nat -A POSTROUTING -s '{reseau}'"
            f" -o {uplink} -j MASQUERADE",
            f"    post-down iptables -t nat -D POSTROUTING -s '{reseau}'"
            f" -o {uplink} -j MASQUERADE",
        ]
    texte = "\n".join(bloc) + "\n"
    cmds = [
        # Idempotent : on n'ajoute la strophe que si le pont n'y est pas déjà.
        f"grep -qE '^(auto|iface) {nom}( |$)' /etc/network/interfaces"
        f" || printf '%s' {shlex.quote(texte)} >> /etc/network/interfaces",
    ]
    if uplink:
        cmds.append(
            "printf 'net.ipv4.ip_forward=1\\n' >"
            " /etc/sysctl.d/99-erplibre-nat.conf && sysctl -q -p"
            " /etc/sysctl.d/99-erplibre-nat.conf"
        )
    # ifup plutôt qu'« ifreload -a » : recharger TOUTE la configuration d'un
    # hôte distant peut emporter l'interface qui porte la session.
    cmds.append(f"ifup {nom} 2>/dev/null || ifreload -a")
    return cmds


def ipconfig_for(pont_info: dict, vmid: int) -> str:
    """« ip=dhcp » sur un pont qui donne sur le LAN, adresse FIXE sur un pont
    interne — où aucun serveur DHCP ne répondrait.

    L'adresse est dérivée du VMID : deux VM déployées à la suite ne peuvent pas
    se retrouver avec la même, et le lien entre les deux reste lisible.
    """
    info = pont_info or {}
    adresse = info.get("address") or ""
    if info.get("ports") or not adresse:
        return "ip=dhcp"
    base, _, masque = adresse.partition("/")
    tronc = base.rsplit(".", 1)[0]
    hote = 50 + (int(vmid) % 200)
    return f"ip={tronc}.{hote}/{masque or '24'},gw={base}"


def ip_from_ipconfig(ipconfig: str) -> str:
    """Adresse fixe d'un « ip=10.10.10.150/24,gw=… », ou '' si c'est du DHCP.

    Quand c'est NOUS qui avons attribué l'adresse, la chercher ensuite est
    absurde : elle est connue avant que la VM ne démarre. La découverte (agent
    invité, voisinage de l'hôte) ne sert qu'au DHCP.
    """
    m = re.search(r"ip=(\d+\.\d+\.\d+\.\d+)", ipconfig or "")
    return m.group(1) if m else ""


def image_fetch_cmd(url: str, nom: str, repertoire: str = IMAGE_DIR) -> str:
    """Télécharge l'image cloud SUR l'hôte Proxmox, une seule fois.

    C'est là que le disque de la VM sera écrit : faire descendre l'image chez
    soi pour la renvoyer ensuite doublerait le transfert. Le test de présence
    évite de retélécharger 325 Mio à chaque VM.
    """
    cible = f"{repertoire}/{nom}"
    return (
        f"mkdir -p {shlex.quote(repertoire)} && "
        f"if [ -s {shlex.quote(cible)} ]; then "
        f'echo "image déjà présente : {cible}"; else '
        f"wget -q --show-progress -O {shlex.quote(cible)} {shlex.quote(url)}; "
        f"fi"
    )


def create_cmds(vmid: int, spec: dict) -> list:
    """Séquence complète de création d'une VM, dans l'ordre.

    Une liste et non une seule commande : chaque étape est lisible dans le
    journal, et un échec nomme celle qui a échoué. C'est le contraire d'un
    « qm create » géant dont on ne sait pas quel morceau a cédé.
    """
    nom = spec["name"]
    stockage = spec["storage"]
    image = f"{spec.get('image_dir', IMAGE_DIR)}/{spec['image']}"
    cmds = [
        # 1. La coquille : processeur, mémoire, réseau, contrôleur, agent.
        "qm create {id} --name {nom} --memory {mem} --cores {cpu}"
        " --cpu host --ostype l26 --scsihw virtio-scsi-single"
        " --net0 virtio,bridge={pont} --agent enabled=1"
        " --serial0 socket --vga serial0".format(
            id=vmid,
            nom=shlex.quote(nom),
            mem=int(spec["memory"]),
            cpu=int(spec["vcpus"]),
            pont=spec["bridge"],
        ),
        # 2. Le disque, importé DEPUIS l'image cloud. « import-from » (PVE 8+)
        #    remplace l'ancien « qm importdisk » en une seule étape et attache
        #    le disque du même coup.
        f"qm set {vmid} --scsi0"
        f" {stockage}:0,import-from={shlex.quote(image)},discard=on,ssd=1",
        # 3. Le lecteur cloud-init, et l'ordre d'amorçage. Sans « boot order »,
        #    Proxmox laisse le disque importé hors de la liste et la VM démarre
        #    sur le réseau.
        f"qm set {vmid} --ide2 {stockage}:cloudinit"
        f" --boot order=scsi0 --bootdisk scsi0",
    ]
    # 4. cloud-init : utilisateur, clé, réseau. La clé est un FICHIER sur
    #    l'hôte — « --sshkeys » n'accepte pas la clé en ligne.
    ci = (
        f"qm set {vmid} --ciuser {shlex.quote(spec.get('user') or 'erplibre')}"
    )
    if spec.get("sshkey_path"):
        ci += f" --sshkeys {shlex.quote(spec['sshkey_path'])}"
    if spec.get("password"):
        ci += f" --cipassword {shlex.quote(spec['password'])}"
    ci += f" --ipconfig0 {spec.get('ipconfig') or 'ip=dhcp'}"
    cmds.append(ci)
    # 5. La taille. L'image cloud fait 2 Gio : sans agrandissement, il ne reste
    #    rien pour installer quoi que ce soit.
    if spec.get("disk"):
        cmds.append(f"qm resize {vmid} scsi0 {spec['disk']}")
    if spec.get("start", True):
        cmds.append(f"qm start {vmid}")
    return cmds


def destroy_cmds(vmid: int, purge: bool = True) -> list:
    """Arrêt puis suppression. « --purge » retire aussi les disques et les
    entrées de sauvegarde : sans lui, le stockage garde des volumes orphelins
    que rien ne réclame plus."""
    return [
        f"qm stop {vmid} --skiplock 1 || true",
        f"qm destroy {vmid} --purge {1 if purge else 0}"
        " --destroy-unreferenced-disks 1",
    ]


def resize_cmd(vmid: int, taille: str, disque: str = "scsi0") -> str:
    """« +10G » agrandit, « 40G » fixe. Proxmox REFUSE de rétrécir un disque —
    le dire ici évite de croire à un bug de l'outil."""
    return f"qm resize {vmid} {disque} {taille}"


def status_cmd(vmid: int) -> str:
    return f"qm status {vmid} --verbose"


def guest_ip_cmd(vmid: int) -> str:
    return f"qm guest cmd {vmid} network-get-interfaces"


def console_cmd(vmid: int) -> str:
    """Console série. `qm terminal` demande serial0, que create_cmds pose."""
    return f"qm terminal {vmid}"


def orphan_disks_cmd() -> str:
    """Volumes de disque qui n'appartiennent à aucune VM déclarée.

    Proxmox ne les efface pas tout seul : un « qm destroy » sans « --purge »,
    ou une création interrompue, en laisse. On les LISTE, on n'efface rien
    sans demander.
    """
    return (
        "for s in $(pvesm status --content images | awk 'NR>1 {print $1}'); "
        'do pvesm list "$s" 2>/dev/null; done'
    )


def parse_orphans(text: str, vmids) -> list:
    """[(volid, taille)] des volumes dont le VMID n'existe plus."""
    connus = {str(v) for v in vmids or ()}
    out = []
    for ligne in (text or "").splitlines():
        parts = ligne.split()
        if len(parts) < 5 or parts[0] == "Volid":
            continue
        volid, vmid = parts[0], parts[-1]
        if vmid.isdigit() and vmid not in connus:
            try:
                taille = int(parts[3])
            except ValueError:
                taille = 0
            out.append((volid, taille))
    return out
