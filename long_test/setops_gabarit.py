#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Bâtir le gabarit doré du banc sans surveillance, sur un nœud Proxmox.

Le clonage du moteur part d'un modèle : sans lui le banc ne commence pas. Ce
module l'installe SANS ÉCRAN — debian-installer amorcé directement par son
noyau et son initrd, le preseed glissé DANS l'initrd, le nœud Proxmox pour
seul exécutant.

CE QUE LA PROCÉDURE DU MOTEUR EXIGE et que ce module produit : `q35` et
`ovmf`, une partition EFI suivie d'une racine ext4, NI swap NI LVM — une
racine qu'on agrandit après clonage ne le peut pas si une partition la suit —
et les paquets par lesquels le moteur prend le relais.

L'IDENTITÉ N'EST PAS POSÉE ICI. Elle vient de Cloud-Init au premier
démarrage, ce qui évite deux méthodes concurrentes pour le même accès. Le
preseed n'installe donc AUCUN COMPTE — mais l'installateur refuse d'avancer
sans voie d'administration, d'où un mot de passe root dont l'appelant tire le
hachage d'un secret qu'il jette. Nul ne le connaît, et l'agent invité reste
la voie d'entrée tant que Cloud-Init n'a pas parlé.

Tout l'adressage est PARAMÈTRE : ce module ne connaît ni fabric ni labo.
"""

import re
import shlex

# Le noyau et l'initrd de l'installateur, par le chemin que Debian tient à
# jour. « current » suit les mises à jour sans figer un numéro qui périmerait.
URL_INSTALLATEUR = (
    "https://deb.debian.org/debian/dists/{code}/main/installer-{arch}"
    "/current/images/netboot/debian-installer/{arch}/{fichier}"
)

# La recette de partitionnement, en UNE ligne : une valeur debconf coupée par
# des continuations se relit mal et se casse à la première indentation
# perdue. ESP d'abord, racine ensuite et jusqu'au bout du disque — `-1` est ce
# qui la rend agrandissable après clonage.
RECETTE = (
    "boot-root :: "
    "512 512 512 fat32 $iflabel{ gpt } $reusemethod{ } "
    "method{ efi } format{ } . "
    "1024 10000 -1 ext4 method{ format } format{ } "
    "use_filesystem{ } filesystem{ ext4 } mountpoint{ / } ."
)

# CE PAR QUOI LE MOTEUR PREND LE RELAIS, et rien de plus : le reste est
# installé ensuite par ses propres rôles. `cloud-guest-utils` porte `growpart`,
# sans quoi la racine d'un clone reste à la taille du gabarit.
PAQUETS = (
    "sudo openssh-server qemu-guest-agent cloud-init "
    "cloud-guest-utils ca-certificates curl vim nano"
)

# Ce que le matériel virtuel doit valoir, et que le gabarit lègue à ses
# clones. `q35` est PCIe là où le défaut est PCI : les noms d'interfaces
# prédictibles en dérivent, et un clone au mauvais chipset démarre sur une
# configuration réseau qui désigne une interface inexistante.
MACHINE = "q35"
BIOS = "ovmf"

# Un type de processeur générique plutôt que `host` : le gabarit doit pouvoir
# se cloner sur un nœud dont le processeur diffère.
CPU = "x86-64-v2-AES"

# La forme d'un hachage crypt(3) : « $ », un identifiant de méthode, « $ ».
# CE QUI N'EN EST PAS UN N'ÉCHOUE PAS — l'installateur le laisse tomber et POSE
# la question du mot de passe, sur une console que personne ne regarde. Un
# marqueur de verrouillage comme « ! » ou « * » est refusé ici pour cela : il
# verrouille un compte DÉJÀ créé, il ne se préconfigure pas.
FORME_CRYPT = re.compile(r"^\$[0-9a-zA-Z]+\$[^\s:]+$")


def urls_installateur(code, arch="amd64"):
    """Les URL du noyau et de l'initrd de l'installateur, ou `()`.

    LES DEUX OU AUCUNE : un noyau amorcé sans son initrd démarre, puis
    s'arrête faute de trouver un système de fichiers racine, et l'écran ne
    dit rien de l'URL qui manquait.
    """
    if not all((vu or "").strip() for vu in (code, arch)):
        return ()
    return tuple(
        URL_INSTALLATEUR.format(
            code=code.strip(), arch=arch.strip(), fichier=fichier
        )
        for fichier in ("linux", "initrd.gz")
    )


def lignes_preseed(
    hote,
    adresse,
    passerelle,
    dns,
    hachage_root,
    disque="/dev/sda",
    trace=False,
):
    """Les réponses écrites de l'installateur, ou `()`.

    Rend `()` — et non une liste incomplète — dès qu'un paramètre manque : un
    preseed amputé n'échoue pas, il POSE LA QUESTION à l'écran, et
    l'installation s'arrête sur une console que personne ne regarde.

    L'adresse est fixe parce qu'aucun DHCP n'est supposé sur le pont de
    fabrication. Sans elle, netcfg demande l'adresse et attend.
    """
    vus = (hote, adresse, passerelle, dns, disque)
    if not all((vu or "").strip() for vu in vus):
        return ()
    if not FORME_CRYPT.match((hachage_root or "").strip()):
        return ()
    return (
        "d-i debian-installer/locale string en_US.UTF-8",
        "d-i keyboard-configuration/xkb-keymap select us",
        "d-i console-setup/ask_detect boolean false",
        "d-i netcfg/choose_interface select auto",
        "d-i netcfg/disable_autoconfig boolean true",
        "d-i netcfg/dhcp_options select Configure network manually",
        f"d-i netcfg/get_ipaddress string {adresse.strip()}",
        "d-i netcfg/get_netmask string 255.255.255.0",
        f"d-i netcfg/get_gateway string {passerelle.strip()}",
        f"d-i netcfg/get_nameservers string {dns.strip()}",
        "d-i netcfg/confirm_static boolean true",
        f"d-i netcfg/get_hostname string {hote.strip()}",
        # Un domaine du TLD réservé aux noms qui ne se résolvent pas : le
        # gabarit n'appartient à aucune zone, et Cloud-Init pose la sienne.
        "d-i netcfg/get_domain string invalid",
        "d-i mirror/country string manual",
        "d-i mirror/http/hostname string deb.debian.org",
        "d-i mirror/http/directory string /debian",
        "d-i mirror/http/proxy string",
        # AUCUN COMPTE N'EST CRÉÉ : l'identité vient de Cloud-Init. Mais d-i
        # refuse d'avancer sans voie d'administration, donc la connexion root
        # est DÉCLARÉE, sur un secret que l'appelant jette après l'avoir haché.
        "d-i passwd/root-login boolean true",
        f"d-i passwd/root-password-crypted password {hachage_root.strip()}",
        "d-i passwd/make-user boolean false",
        "d-i clock-setup/utc boolean true",
        "d-i time/zone string Etc/UTC",
        "d-i clock-setup/ntp boolean true",
        f"d-i partman-auto/disk string {disque.strip()}",
        "d-i partman-auto/method string regular",
        f"d-i partman-auto/expert_recipe string {RECETTE}",
        "d-i partman-auto/choose_recipe select boot-root",
        "d-i partman-partitioning/confirm_write_new_label boolean true",
        "d-i partman/choose_partition select finish",
        "d-i partman/confirm boolean true",
        "d-i partman/confirm_nooverwrite boolean true",
        # Sans partition d'échange, partman propose de revenir au menu. La
        # question A UN DÉFAUT, qui y renvoie : « priority=critical » ne la
        # saute donc pas, et sans cette réponse l'installation s'arrête là.
        "d-i partman-basicfilesystems/no_swap boolean false",
        "d-i partman-md/device_remove_md boolean true",
        "d-i partman-lvm/device_remove_lvm boolean true",
        "d-i partman-lvm/confirm boolean true",
        "d-i partman-lvm/confirm_nooverwrite boolean true",
        "d-i partman/unmount_active boolean true",
        "tasksel tasksel/first multiselect standard, ssh-server",
        f"d-i pkgsel/include string {PAQUETS}",
        "d-i pkgsel/upgrade select none",
        "d-i pkgsel/update-policy select none",
        "d-i apt-setup/services-select multiselect security, updates",
        "popularity-contest popularity-contest/participate boolean false",
        "d-i grub-installer/only_debian boolean true",
        # L'amorceur est aussi écrit au chemin amovible. Un clone reçoit une
        # copie du disque EFI mais peut perdre son entrée NVRAM ; sans ce
        # repli il démarre sur un firmware qui ne trouve rien.
        "d-i grub-installer/force-efi-extra-removable boolean true",
        # Le late_command SE TERMINE PAR UNE COMMANDE QUI REND 0 : d-i
        # s'arrête sur « Failed to run preseeded command » sinon, et le
        # diagnostic devient lui-même le blocage. Il reste MINCE pour la
        # même raison : ce qui se corrige après la pose se corrige après
        # la pose, où l'on peut le vérifier.
        "d-i preseed/late_command string "
        "in-target systemctl enable qemu-guest-agent ; true",
        "d-i finish-install/reboot_in_progress note",
        # L'INSTALLATEUR S'ÉTEINT AU LIEU DE REDÉMARRER. Son noyau est épinglé
        # par les arguments d'amorçage le temps de l'installation ; un
        # redémarrage y retombe et réinstalle, indéfiniment, chaque passe
        # ayant l'air d'une première. L'extinction donne de surcroît la
        # condition d'arrêt que le pilote attend.
        "d-i debian-installer/exit/poweroff boolean true",
    )


def preseed(
    hote,
    adresse,
    passerelle,
    dns,
    hachage_root,
    disque="/dev/sda",
    trace=False,
):
    """Le preseed complet, ou « » si un paramètre manque."""
    lignes = lignes_preseed(
        hote, adresse, passerelle, dns, hachage_root, disque
    )
    return "\n".join(lignes) + "\n" if lignes else ""


def args_amorce(noyau, initrd, console="ttyS0,115200n8", journal=None):
    """Les arguments bruts qui amorcent l'installateur, ou None.

    REFUSE UN INITRD QUI N'EST PAS CELUI QUI PORTE LE PRESEED : amorcer
    l'initrd d'origine donne une installation interactive, qui a l'air de
    fonctionner jusqu'à son premier écran.

    `journal` détourne la console série vers un fichier du nœud, seule trace
    lisible d'une installation qui n'a pas d'écran.

    CE QUI EST RENDU EST UN SEUL ARGUMENT, déjà cité pour l'analyseur de
    `qm` : l'appelant le cite À NOUVEAU pour son propre shell. Sans cela les
    guillemets internes du `-append` le coupent en plusieurs mots, et `qm`
    refuse sur un message qui compte les arguments sans dire lesquels.
    """
    if not all((vu or "").strip() for vu in (noyau, initrd, console)):
        return None
    if noyau.strip() == initrd.strip():
        return None
    morceaux = []
    if (journal or "").strip():
        morceaux += ["-serial", "file:" + journal.strip()]
    morceaux += [
        "-kernel",
        noyau.strip(),
        "-initrd",
        initrd.strip(),
        "-append",
        f"console={console.strip()} priority=critical",
    ]
    return shlex.join(morceaux)


def argv_creation(vmid, nom, stockage, pont, gio=16, memoire=2048, coeurs=2):
    """L'argv de `qm create` pour le gabarit, ou None.

    Fermé par défaut : un VMID illisible, un nom, un stockage ou un pont vide
    font refuser plutôt que créer une VM à laquelle il manque ce qui la rend
    clonable.
    """
    if not all((vu or "").strip() for vu in (nom, stockage, pont)):
        return None
    try:
        numero = int(vmid)
        taille, ram, cpus = int(gio), int(memoire), int(coeurs)
    except (TypeError, ValueError):
        return None
    if numero < 1 or taille < 1 or ram < 1 or cpus < 1:
        return None
    lieu = stockage.strip()
    return [
        "qm",
        "create",
        str(numero),
        "--name",
        nom.strip(),
        "--machine",
        MACHINE,
        "--bios",
        BIOS,
        "--ostype",
        "l26",
        "--cpu",
        CPU,
        "--sockets",
        "1",
        "--cores",
        str(cpus),
        "--memory",
        str(ram),
        "--scsihw",
        "virtio-scsi-single",
        "--scsi0",
        f"{lieu}:{taille},format=qcow2,iothread=1",
        # Le disque EFI est ce qui rend `ovmf` utilisable : sans lui la VM
        # démarre sur un firmware sans stockage de variables, et l'entrée
        # d'amorçage écrite par l'installateur ne survit pas à l'extinction.
        "--efidisk0",
        f"{lieu}:0,efitype=4m,pre-enrolled-keys=0",
        "--net0",
        f"virtio,bridge={pont.strip()}",
        "--agent",
        "enabled=1",
    ]


# Ce que le système posé doit dire de son réseau : RIEN. Il délègue à ce que
# Cloud-Init écrit, et le fichier reste valide.
INTERFACES_DELEGUE = (
    "printf 'source /etc/network/interfaces.d/*\\n\\nauto lo\\n"
    "iface lo inet loopback\\n' > /etc/network/interfaces"
)


def cmds_dans_le_gabarit(vmid):
    """Ce qui se corrige DANS le système posé, par l'agent invité, ou `()`.

    L'ADRESSE DE FABRICATION N'A PLUS RIEN À Y FAIRE. L'installateur écrit
    une strophe statique qui la porte ; Cloud-Init écrit la sienne SOUS UN
    AUTRE NOM D'INTERFACE, donc les deux coexistent, et chaque clone lève la
    sienne sur l'adresse du gabarit sans que rien ne le signale. Le nettoyage
    du moteur vide le résolveur hérité de ce réseau, pas ce fichier.

    PAR L'AGENT ET NON PAR UN HOOK DE L'INSTALLATEUR : ce qui se corrige
    après la pose se VÉRIFIE après la pose. Un hook qui échoue arrête une
    installation que personne ne regarde, sur un écran dont le message ne
    nomme même pas l'étape.

    Rend des argv, que l'appelant cite pour son shell.
    """
    try:
        numero = int(vmid)
    except (TypeError, ValueError):
        return ()
    if numero < 1:
        return ()
    return (
        [
            "qm",
            "guest",
            "exec",
            str(numero),
            "--timeout",
            "30",
            "--",
            "/bin/sh",
            "-c",
            INTERFACES_DELEGUE,
        ],
    )


def cmds_apres_installation(vmid, stockage):
    """Ce qui reste à faire quand l'installateur s'est tu, ou ().

    Retirer les arguments d'amorçage est le geste qui compte : tant qu'ils
    sont là, la VM redémarre dans l'installateur et réinstalle.

    Le lecteur Cloud-Init EST une pièce du modèle et non un réglage du clone :
    il est ce par quoi chaque clone reçoit son compte, sa clé et son adresse.
    Un modèle qui n'en porte pas produit des clones auxquels personne ne peut
    se connecter, et rien dans le clonage ne le signale.
    """
    if not (stockage or "").strip():
        return ()
    try:
        numero = int(vmid)
    except (TypeError, ValueError):
        return ()
    if numero < 1:
        return ()
    return (
        f"qm set {numero} --delete args",
        f"qm set {numero} --boot order=scsi0",
        f"qm set {numero} --ide2 {stockage.strip()}:cloudinit",
    )


def cmds_conversion(vmid):
    """Éteindre la VM, puis la convertir en modèle, ou `()`.

    L'EXTINCTION D'ABORD, et dans la même suite : le nettoyage qui précède
    vide `/etc/machine-id` et retire les clés d'hôte SSH, que le système
    régénère au démarrage suivant. Convertir une VM restée debout fige donc
    un modèle dont chaque clone naîtra avec la MÊME identité de machine.

    Un modèle ne démarre pas. Ce qui est rendu ici est le dernier geste :
    après lui, inspecter coûte un clone.
    """
    try:
        numero = int(vmid)
    except (TypeError, ValueError):
        return ()
    if numero < 1:
        return ()
    return (
        f"qm stop {numero}",
        f"qm template {numero}",
    )
