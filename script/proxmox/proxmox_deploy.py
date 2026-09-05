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

import ipaddress
import json
import re
import shlex

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


# Le transport ssh vit dans script/remote/ : il ne sait rien de Proxmox, et
# une seconde appliance en aurait fait une copie. Ces noms restent lisibles
# ici — une quarantaine d'appels et leurs tests les nomment ainsi, et un test
# qui REMPLACE `run` le fait sur ce module.
from script.remote.appliance_ssh import (  # noqa: E402,F401
    collapse_progress,
    run,
    ssh_argv,
    strip_ssh_noise,
    wrap_privilege,
)


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


# D'abord le fichier de systemd-resolved, qui porte les serveurs RÉELS :
# /etc/resolv.conf n'y renvoie qu'un stub sur 127.0.0.53, inutilisable pour un
# invité. On tente les deux, dans cet ordre.
RESOLV_CMD = (
    "cat /run/systemd/resolve/resolv.conf 2>/dev/null || cat /etc/resolv.conf"
)


def parse_nameservers(text: str) -> list:
    """Résolveurs UTILISABLES PAR UN INVITÉ, tirés d'un resolv.conf.

    Les adresses de boucle sont écartées : « nameserver 127.0.0.53 » est le
    stub de systemd-resolved, qui n'existe que sur l'hôte. Une VM qui le
    reçoit n'a pas de DNS — mesuré, la VM d'essai ne résolvait rien alors que
    le NAT marchait, et « apt update » aurait échoué sans rien expliquer.
    """
    serveurs = []
    for ligne in (text or "").splitlines():
        parts = ligne.split()
        if len(parts) >= 2 and parts[0] == "nameserver":
            adresse = parts[1].strip()
            if adresse.startswith("127.") or adresse in ("::1", "localhost"):
                continue
            if adresse not in serveurs:
                serveurs.append(adresse)
    return serveurs


def parse_kernel(text: str) -> str:
    """Noyau ANNONCÉ par pveversion, ou ''.

    « pve-manager/9.2.11/abc (running kernel: 6.12.95+deb13-cloud-amd64) » ->
    « 6.12.95+deb13-cloud-amd64 ». Ce n'est pas un détail : tant que l'hôte
    tourne le noyau de la distribution, il n'a ni le module bridge ni la table
    NAT, donc pas de pont et pas de VM.
    """
    trouve = re.search(r"running kernel:\s*([^)\s]+)", text or "")
    return trouve.group(1) if trouve else ""


# Ce qu'il faut savoir AVANT d'écrire un pont NAT, en un aller-retour.
#
# Le noyau seul ne suffit pas à juger : « -pve » dans son nom est un indice,
# pas une preuve, et l'inverse non plus — c'est la table NAT elle-même qu'on
# interroge. « iptables -t nat -S » échoue avec « Table does not exist » quand
# aucun module netfilter n'est chargeable, et réussit sinon.
NAT_CHECK_CMD = (
    "uname -r; echo '---ERPLIBRE-NAT---'; "
    "iptables -t nat -S >/dev/null 2>&1 && echo NAT-OK || echo NAT-KO; "
    "echo '---ERPLIBRE-PVE-KERNEL---'; "
    "ls -1 /lib/modules 2>/dev/null | grep -- -pve | sort -V | tail -1"
)


def parse_nat_check(text: str) -> dict:
    """{"kernel": …, "nat": bool, "pve_kernel": …} depuis NAT_CHECK_CMD.

    `nat` à False sans `pve_kernel` veut dire que l'installation Proxmox n'est
    pas allée au bout ; avec, qu'elle attend un redémarrage."""
    brut = strip_ssh_noise(text or "")
    parts = brut.split("---ERPLIBRE-NAT---")
    kernel = parts[0].strip().splitlines()
    reste = parts[1] if len(parts) > 1 else ""
    suite = reste.split("---ERPLIBRE-PVE-KERNEL---")
    pve_kernel = suite[1].strip().splitlines() if len(suite) > 1 else []
    return {
        "kernel": kernel[-1].strip() if kernel else "",
        "nat": "NAT-OK" in (suite[0] if suite else ""),
        "pve_kernel": pve_kernel[-1].strip() if pve_kernel else "",
    }


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


# De quoi savoir POURQUOI il n'y a aucun stockage, en un aller-retour.
#
# « pvesm » ne parle qu'à travers /etc/pve, un système de fichiers monté par
# pmxcfs. pmxcfs à terre, la commande répond « Connection refused » et la liste
# est vide — l'écran conclut « il manque le stockage » alors que le défaut est
# trois étages plus bas.
CLUSTER_CHECK_CMD = (
    "systemctl is-active pve-cluster 2>/dev/null || true; "
    "echo '---ERPLIBRE-PVE-FS---'; "
    # « .version » et non « storage.cfg » : ce dernier N'EXISTE PAS sur une
    # installation neuve — Proxmox se contente alors de ses stockages par
    # défaut, et « local » répond parfaitement. Le tester revenait à déclarer
    # /etc/pve absent sur un hôte sain. « .version » est un fichier virtuel de
    # pmxcfs : il est là si et seulement si le montage est là.
    "test -e /etc/pve/.version && echo MONTE || echo ABSENT; "
    "echo '---ERPLIBRE-HOSTNAME-IP---'; "
    "hostname --ip-address 2>/dev/null || true"
)


def _usable_address(adresse: str) -> bool:
    """Cette adresse permet-elle à pmxcfs de s'identifier ?

    Ni bouclage, ni LIEN-LOCAL. Le lien-local est le piège : mesuré,
    « hostname --ip-address » peut ne rendre QUE des fe80::, et une adresse
    APIPA en 169.254 passait le seul test « ne commence pas par 127. ». Dans
    les deux cas pmxcfs n'a rien d'utilisable, mais le diagnostic concluait
    « le nom résout vers une adresse routable » — et renvoyait vers
    journalctl au lieu de /etc/hosts, sur un hôte qu'on ne peut inspecter que
    par ssh."""
    try:
        adr = ipaddress.ip_address(adresse)
    except ValueError:
        return False
    return not (adr.is_loopback or adr.is_link_local)


def parse_cluster_check(text: str) -> dict:
    """{"actif", "monte", "adresses", "routables", "lu"} depuis
    CLUSTER_CHECK_CMD.

    `routables` vide est la cause la plus fréquente : pmxcfs parcourt les
    adresses du nom d'hôte jusqu'à en trouver une qui ne soit pas de
    bouclage, et l'entrée « 127.0.1.1 <nom> » de l'image cloud le mène dans
    le mur.

    `lu` dit si la sonde a RÉPONDU — les deux sentinelles sont là. Sans lui,
    un simple dépassement de délai rendait « monte: False, adresses: [] », et
    l'appelant affirmait « le nom d'hôte ne résout que vers ? » sans avoir
    rien mesuré. Affirmer une cause qu'on n'a pas constatée est pire que se
    taire : cela envoie réécrire /etc/hosts sur une machine peut-être
    saine."""
    brut = strip_ssh_noise(text or "")
    tete, sep1, reste = brut.partition("---ERPLIBRE-PVE-FS---")
    milieu, sep2, queue = reste.partition("---ERPLIBRE-HOSTNAME-IP---")
    # Filtré sur ce qu'EST une adresse, pas sur sa ponctuation. run() colle
    # stderr après stdout, donc tout ce que sudo écrit atterrit dans cette
    # queue — et « sudo: unable to resolve host pve: … » se produit
    # précisément dans la panne qu'on diagnostique. Mesuré : l'écran affichait
    # « le nom d'hôte ne résout que vers 127.0.1.1 sudo: pve: ». Il affirmait
    # des adresses là où la sonde n'avait rien mesuré.
    adresses = []
    for jeton in queue.split():
        try:
            ipaddress.ip_address(jeton)
        except ValueError:
            continue
        adresses.append(jeton)
    return {
        "lu": bool(sep1 and sep2),
        "actif": "active" in tete and "inactive" not in tete,
        "monte": "MONTE" in milieu,
        "adresses": adresses,
        "routables": [a for a in adresses if _usable_address(a)],
    }


# Marqueur de NOTRE ligne dans /etc/hosts. Il rend la réécriture exactement
# idempotente : on retire ce qui porte la marque, puis on ajoute. Sans lui, la
# garde devait s'indexer sur l'ADRESSE — et en DHCP une adresse qui change
# ajoutait une ligne de plus à chaque passage sans retirer la précédente.
HOSTS_MARK = "erplibre-hosts"

# Services relancés par la réparation. pve-firewall n'y est PAS : sa
# configuration vit dans /var/lib/pve-cluster/config.db, invisible tant que
# /etc/pve n'est pas monté — c'est-à-dire exactement l'état qu'on répare. Le
# démarrer appliquerait des règles illisibles sur la seule voie d'accès à la
# machine.
#
# rrdcached d'abord : pve-cluster le requiert, et une limite de démarrage
# atteinte sur lui fait échouer pve-cluster sur « dependency » sans que
# reset-failed sur pve-cluster n'y change quoi que ce soit.
PVE_UNITS = ("rrdcached", "pve-cluster", "pvestatd", "pvedaemon", "pveproxy")


def ssh_server_ip(text: str) -> str:
    """Adresse de l'hôte telle que NOTRE ssh l'atteint, depuis $SSH_CONNECTION.

    « client_ip client_port SERVER_ip server_port » : le troisième champ. C'est
    la seule adresse dont on SAIT qu'elle mène à la machine, rebond compris.

    Les candidats habituels se trompent ici. Mesuré sur une Proxmox imbriquée :
    « hostname -I » rend « 10.10.10.150 10.10.20.1 », et la seconde est le pont
    interne que notre propre code vient de créer. La poser dans /etc/hosts
    ferait s'identifier le nœud par une adresse que personne ne joint.
    """
    champs = strip_ssh_noise(text or "").split()
    return champs[2] if len(champs) >= 4 and _usable_address(champs[2]) else ""


# Deux sources pour les noms, dans cet ordre. La seconde est indispensable au
# REJEU : au second passage il n'y a plus de ligne 127.0.1.1 — c'est nous qui
# l'avons retirée — et sans elle un vrai FQDN était remplacé par
# « <court>.local ». La commande n'était donc pas idempotente sur ce qu'elle
# avait elle-même préservé. Attrapé par un test qui la rejoue deux fois.
_NOMS_DEPUIS_LOOPBACK = (
    r"sed -nE 's/^[[:space:]]*127\.0\.1\.1[[:space:]]+([^#]*).*$/\1/p'"
)
_NOMS_DEPUIS_MARQUE = (
    r"sed -nE 's/^[^[:space:]]+[[:space:]]+([^#]*)#[[:space:]]*"
    + HOSTS_MARK
    + r"[[:space:]]*$/\1/p'"
)
# Normalise les séparateurs. L'installeur Debian écrit /etc/hosts avec des
# TABULATIONS, et le test du nom court cherchait des ESPACES : au rejeu, la
# ligne écrite gagnait un « srv » de plus.
_ROGNE = r"sed -E 's/[[:space:]]+/ /g; s/^ //; s/ $//'"


def hosts_repair_cmd(ip: str) -> str:
    """UNE écriture ATOMIQUE de /etc/hosts, ou "" sans adresse utilisable.

    La première version promettait « une seule commande » et n'en tenait rien :
    « sed -i » puis « printf >> » sont DEUX écritures, sans set -e et sans
    retour en arrière. Une attaque adversariale l'a mesuré sur trois états
    réels — /etc en lecture seule, fichier rendu immuable par chattr, quota
    atteint :

    * sed refusé, ajout réussi -> la ligne 127.0.1.1 survit et reste PREMIÈRE,
      donc gagnante, et notre ligne s'ajoute UNE FOIS PAR TENTATIVE. Le
      marqueur, censé rendre l'opération idempotente, ne retirait rien puisque
      c'est le sed qui portait la suppression.
    * sed réussi, ajout refusé -> l'hôte n'a PLUS d'entrée pour son nom. Sur
      une machine qu'on ne joint que par ssh, chaque sudo attend ensuite le
      résolveur puis répond « unable to resolve host ». C'est exactement l'état
      « pire qu'avant » que la docstring prétendait écarter.

    Donc : on construit le fichier ENTIER dans un temporaire du même
    répertoire, on vérifie ce qu'il contient, et on ne le recopie qu'ensuite.
    « cat > » et non « mv » : le renommage remplace l'inode et perdrait mode,
    propriétaire et contexte SELinux de /etc/hosts.

    Bénéfice supplémentaire : « sed » sans -i ajoute le saut de ligne final
    manquant. Sans lui, un /etc/hosts non terminé par \\n — cloud-init
    « write_files » n'en met pas — voyait notre ligne se coller à la
    précédente, et le nom du nœud partait sur l'adresse d'une AUTRE machine.

    POSIX seulement (dash), et aucun « sudo » dedans : c'est wrap_privilege
    qui porte le privilège, et sur un hôte root@ il n'enrobe rien.
    """
    if not _usable_address(ip):
        return ""
    tmp = "/etc/hosts.erplibre.$$"
    return (
        "short=$(hostname -s); "
        f"noms=$({_NOMS_DEPUIS_LOOPBACK} /etc/hosts | head -1 | {_ROGNE}); "
        f'[ -n "$noms" ] || noms=$({_NOMS_DEPUIS_MARQUE} /etc/hosts'
        f" | head -1 | {_ROGNE}); "
        '[ -n "$noms" ] || noms="$short.local $short"; '
        # Le nom court DOIT y être : c'est lui que pmxcfs résout. Le test se
        # fait sur des séparateurs NORMALISÉS — l'installeur Debian écrit des
        # tabulations, et « case " $noms " in *" $short "* » ne les voyait pas,
        # d'où un « srv srv » au rejeu.
        'case " $noms " in *" $short "*) ;; *) noms="$noms $short";; esac; '
        # Le fichier complet d'abord, dans le MÊME répertoire : un temporaire
        # ailleurs ne se recopierait pas forcément (montages séparés).
        "{ "
        # awk et non sed : « print » émet un saut de ligne par
        # enregistrement, donc un /etc/hosts non terminé par \n est
        # NORMALISÉ. sed, lui, préserve l'absence — vérifié — et notre ligne
        # se collait alors à la précédente : le nom du nœud partait sur
        # l'adresse d'une autre machine. mawk 1.3.4, celui de Debian, fait
        # bien ce qu'on attend.
        r"awk '!/^[ \t]*127\.0\.1\.1[ \t]/"
        f" && !/#[ \\t]*{HOSTS_MARK}[ \\t]*$/' /etc/hosts"
        f" && printf '%s\\t%s\\t# {HOSTS_MARK}\\n' {shlex.quote(ip)} \"$noms\""
        f" ; }} > {tmp} || {{ rm -f {tmp}; echo HOSTS-KO; exit 0; }}; "
        # On vérifie le TEMPORAIRE avant de toucher à l'original : notre ligne
        # présente une seule fois, et plus aucune 127.0.1.1.
        f"vu=$(sed -nE 's/^([^#[:space:]]+)[[:space:]].*#[[:space:]]*"
        f"{HOSTS_MARK}[[:space:]]*$/\\1/p' {tmp}); "
        f'if [ "$vu" != {shlex.quote(ip)} ] '
        rf"|| grep -qE '^[[:space:]]*127\.0\.1\.1[[:space:]]' {tmp}; then "
        f"rm -f {tmp}; echo HOSTS-KO; exit 0; fi; "
        # La seule écriture destructive, et elle est la dernière.
        f"cat {tmp} > /etc/hosts || {{ rm -f {tmp}; echo HOSTS-KO; exit 0; }}; "
        f"rm -f {tmp}; echo HOSTS-OK"
    )


def cloud_hosts_freeze_cmd() -> str:
    """Empêche cloud-init de réécrire /etc/hosts au prochain démarrage.

    Gardé sur le CONTENU et non sur l'existence : « printf … > » TRONQUE avant
    d'écrire, donc une coupure laisse zéro octet et une garde à l'existence
    annonce « déjà gelé » pour toujours. Une redirection est de toute façon
    idempotente : il n'y a rien d'autre à protéger.
    """
    fichier = "/etc/cloud/cloud.cfg.d/99-erplibre-hosts.cfg"
    return (
        "[ -d /etc/cloud ] || { echo FREEZE-SANS-OBJET; exit 0; }; "
        f"grep -qE '^[[:space:]]*manage_etc_hosts:[[:space:]]*false' {fichier}"
        " 2>/dev/null && { echo FREEZE-DEJA; exit 0; }; "
        "mkdir -p /etc/cloud/cloud.cfg.d; "
        "printf '%s\\n' "
        "'# Posé par ERPLibre : pmxcfs exige une adresse routable.' "
        "'manage_etc_hosts: false' "
        f"> {fichier} && echo FREEZE-OK || echo FREEZE-KO"
    )


def pve_unit_cmd(unite: str, remonte: bool = False) -> str:
    """Relance UNE unité, sans jamais être fatale.

    Par unité et non toutes ensemble : « systemctl start » BLOQUE jusqu'à
    TimeoutStartSec (90 s par défaut), et cinq unités groupées dépassent le
    délai de l'appel — on recevrait « timeout » sans savoir laquelle.

    « restart » quand pve-cluster est ACTIF mais /etc/pve absent : le montage
    FUSE est alors périmé (pmxcfs tué par l'OOM killer), et « start » sur une
    unité active est un no-op qui rend 0 — la réparation ne convergeait jamais
    et ne nommait rien.

    Le journal accompagne un échec : c'est la seule façon de dire la cause à
    quelqu'un dont le seul accès à l'hôte est cet outil.
    """
    u = shlex.quote(unite)
    # « active » ne prouve RIEN sur le lien à pmxcfs. Pour pve-cluster c'était
    # déjà admis : actif sans /etc/pve, le montage FUSE est périmé et « start »
    # est un no-op qui rend 0. Le même raisonnement vaut pour ses dépendants —
    # pvestatd, pvedaemon et pveproxy tournaient pendant toute la panne, en
    # échouant sur ipcc_send_rec. Les laisser en place après avoir remonté
    # /etc/pve donnait une GUI qui répond « communication failure » juste
    # après notre ✓. `remonte` dit que le montage était absent au diagnostic.
    if unite == "pve-cluster":
        actif = (
            "[ -e /etc/pve/.version ] "
            f'&& {{ echo "DEJA {unite}"; exit 0; }}; '
            f"systemctl restart {u}"
        )
    elif remonte:
        actif = f"systemctl restart {u}"
    else:
        actif = f'echo "DEJA {unite}"; exit 0'
    return (
        f"systemctl list-unit-files {u}.service >/dev/null 2>&1"
        f' || {{ echo "SKIP {unite}"; exit 0; }}; '
        f"etat=$(systemctl is-active {u} 2>/dev/null || true); "
        f'if [ "$etat" = active ]; then {actif}; else '
        f"systemctl reset-failed {u} 2>/dev/null || true; "
        f"systemctl start {u}; fi "
        f'|| {{ echo "KO {unite}"; '
        f"journalctl -u {u} -n 20 --no-pager -o cat 2>/dev/null; }}"
    )


def mount_wait_cmd(tours: int = 20, repos: int = 5) -> str:
    """Attend le montage de /etc/pve, puis le RECONFIRME.

    En une seule commande : une boucle côté Python rouvrirait une connexion
    par tour — deux poignées de main à travers un rebond, vingt fois — et si
    le chemin vient d'être perdu, tous les tours rendraient « timeout » et on
    accuserait pmxcfs de ce qui est une perte de contact.

    Reconfirmé après une pause, parce qu'une seule observation ne prouve rien :
    reset-failed vient d'effacer la limite de relance, donc un pmxcfs qui
    battait repart pour une salve entière. Le voir monter puis mourir se lit
    dans NRestarts, qu'on rend aussi.
    """
    return (
        f"i=0; while [ $i -lt {int(tours)} ]; do "
        "[ -e /etc/pve/.version ] && break; sleep 1; i=$((i+1)); done; "
        "if [ -e /etc/pve/.version ]; then "
        f"sleep {int(repos)}; "
        "if [ -e /etc/pve/.version ]; then echo MONTE; "
        "else echo BATTEMENT; fi; "
        "else echo ABSENT; fi; "
        "printf 'NRESTARTS %s\\n' "
        '"$(systemctl show -p NRestarts --value pve-cluster 2>/dev/null)"'
    )


def parse_mount_wait(text: str) -> dict:
    """{"verdict": MONTE|BATTEMENT|ABSENT|INCONNU, "relances": int|None}.

    INCONNU quand rien de lisible n'est revenu — délai dépassé, coupure. Ce
    n'est pas « absent » : conclure « /etc/pve n'est pas monté » d'une perte
    de contact envoie chercher dans journalctl une panne qui n'existe pas.
    """
    brut = strip_ssh_noise(text or "")
    verdict = "INCONNU"
    for mot in ("BATTEMENT", "MONTE", "ABSENT"):
        if mot in brut:
            verdict = mot
            break
    trouve = re.search(r"NRESTARTS\s+(\d+)", brut)
    return {
        "verdict": verdict,
        "relances": int(trouve.group(1)) if trouve else None,
    }


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


# « 2: vmbr0: <BROADCAST,MULTICAST,UP> mtu 1500 … » — l'index, le nom, les
# drapeaux. Exiger cette forme, et pas « quelque chose avant deux-points » :
# n'importe quelle ligne de bruit devenait sinon un nom de pont.
_RE_LIEN = re.compile(r"^\s*\d+:\s*([A-Za-z0-9][A-Za-z0-9._@-]*):\s*<")


def parse_bridges(text: str) -> list:
    """Sortie de « ip -o link show type bridge » -> ['vmbr0', …].

    Rien d'autre ne passe : un avertissement de ssh a déjà été pris pour un
    pont, et son « (ED25519) » a fait échouer le « qm create » qui suivait sur
    une erreur de syntaxe shell incompréhensible.
    """
    ponts = []
    for ligne in (text or "").splitlines():
        trouve = _RE_LIEN.match(ligne)
        if trouve:
            ponts.append(trouve.group(1).split("@")[0])
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

# Le réseau interne ne peut PAS être une constante : un Proxmox dans un
# Proxmox hérite du réseau interne de son parent, et 10.10.10.1 y est
# l'adresse de sa propre PASSERELLE. La poser sur son pont rend tout le /24
# local — la passerelle devient injoignable et la machine s'isole
# instantanément, au milieu de la commande qui la configure. Vécu : « ifup »
# n'a jamais rendu la main et la VM ne répondait plus, ni en ssh ni en ping.
#
# On choisit donc un /24 que l'hôte ne connaît pas encore. La liste va du plus
# attendu au plus improbable : un parc imbriqué descend d'un cran par étage.
INTERNAL_CANDIDATES = (
    "10.10.10.1/24",
    "10.10.20.1/24",
    "10.10.30.1/24",
    "10.10.40.1/24",
    "10.20.10.1/24",
    "10.30.10.1/24",
    "172.31.10.1/24",
    "192.168.210.1/24",
)

# Tout ce que l'hôte sait déjà d'IPv4 : ses adresses ET ses routes. Les deux,
# parce qu'une route sans adresse locale suffit à créer le conflit — la route
# par défaut « via 10.10.10.1 » en est l'exemple exact.
USED_NETS_CMD = "ip -o -4 addr show; ip -4 route show"


def parse_used_nets(text: str) -> set:
    """Réseaux IPv4 lus dans la sortie de USED_NETS_CMD.

    Une adresse nue compte pour un /32 : c'est honnête, et le
    chevauchement avec un /24 candidat se calcule pareil. Un préfixe plus
    large qu'un /24 — « 10.0.0.0/8 » — écarte donc bien tous nos candidats
    en 10.x, ce qu'un test sur les trois premiers octets aurait raté."""
    import ipaddress

    nets = set()
    motif = r"\b(\d{1,3}(?:\.\d{1,3}){3})(?:/(\d{1,2}))?\b"
    for adresse, prefixe in re.findall(motif, text or ""):
        try:
            nets.add(
                ipaddress.ip_network(
                    f"{adresse}/{prefixe or 32}", strict=False
                )
            )
        except ValueError:
            continue
    return nets


def pick_internal_cidr(text: str, candidats=INTERNAL_CANDIDATES) -> str:
    """Le premier candidat qui ne chevauche RIEN de ce que l'hôte connaît.

    Chaîne vide quand tous sont pris : le dire, plutôt que d'en écraser un.
    Écraser, ici, c'est couper la seule voie d'accès à la machine."""
    import ipaddress

    utilises = parse_used_nets(text)
    for candidat in candidats:
        reseau = ipaddress.ip_network(candidat, strict=False)
        if not any(reseau.overlaps(u) for u in utilises):
            return candidat
    return ""


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
    #
    # « mkdir -p /run/network » d'abord : ifupdown2 y pose son verrou, et
    # quand le répertoire manque il annonce « Another instance of this program
    # is already running » — son lockFile() attrape aussi le fichier
    # introuvable. Le message est un MENSONGE, et il a caché deux heures la
    # vraie panne. Sur une Debian installée en image cloud, networking.service
    # n'a jamais démarré, donc personne n'a créé le répertoire.
    #
    # Et l'erreur d'ifup n'est PAS masquée : « 2>/dev/null » cachait
    # « operation failed with 'Operation not supported' » — le noyau cloud n'a
    # pas le module bridge, et c'est ce qu'il fallait lire.
    # Et SURTOUT pas « ifreload -a » en repli : il recharge TOUTES les
    # interfaces, y compris celle qui porte la session ssh, et sur une image
    # cloud l'interface principale est décrite ailleurs (interfaces.d, ou
    # netplan) — ifupdown2 la descend alors sans la remonter. Le repli est
    # donc CHIRURGICAL : on monte le pont à la main, sans toucher à rien
    # d'autre. La strophe, elle, le rend persistant au prochain démarrage.
    manuel = [
        f"ip link show {nom} >/dev/null 2>&1 || ip link add {nom} type bridge",
        f"ip addr add {cidr} dev {nom} 2>/dev/null || true",
        f"ip link set {nom} up",
    ]
    if uplink:
        regle = f"POSTROUTING -s {reseau} -o {uplink} -j MASQUERADE"
        manuel.append(
            f"iptables -t nat -C {regle} 2>/dev/null"
            f" || iptables -t nat -A {regle}"
        )
    cmds.append(
        f"mkdir -p /run/network; ifup {nom} || {{ " + "; ".join(manuel) + "; }"
    )
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
        f"wget -nv -O {shlex.quote(cible)} {shlex.quote(url)}; "
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
    # « --ipconfig0 » ne porte PAS le DNS : une VM en adresse fixe n'a alors
    # aucun résolveur, et rien ne le dit. En DHCP le bail s'en charge.
    serveurs = [s for s in (spec.get("nameservers") or ()) if s]
    if serveurs and "dhcp" not in (spec.get("ipconfig") or "dhcp"):
        ci += f" --nameserver {shlex.quote(' '.join(serveurs))}"
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
