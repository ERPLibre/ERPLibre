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

import base64
import ipaddress
import json
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
    masque="255.255.255.0",
):
    """Les réponses écrites de l'installateur, ou `()`.

    Rend `()` — et non une liste incomplète — dès qu'un paramètre manque : un
    preseed amputé n'échoue pas, il POSE LA QUESTION à l'écran, et
    l'installation s'arrête sur une console que personne ne regarde.

    L'adresse est fixe parce qu'aucun DHCP n'est supposé sur le pont de
    fabrication. Sans elle, netcfg demande l'adresse et attend.
    """
    vus = (hote, adresse, passerelle, dns, disque, masque)
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
        f"d-i netcfg/get_netmask string {masque.strip()}",
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
    masque="255.255.255.0",
):
    """Le preseed complet, ou « » si un paramètre manque."""
    lignes = lignes_preseed(
        hote, adresse, passerelle, dns, hachage_root, disque, masque
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
        # SANS FORMAT IMPOSÉ : chaque stockage prend le sien par défaut, et
        # un LVM-thin ou un ZFS refuse un qcow2. Le moteur clone en copie
        # complète, donc le format de la source n'importe pas au clonage.
        f"{lieu}:{taille},iothread=1",
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
        # UNE EXTINCTION PROPRE D'ABORD : le nettoyage vient d'écrire, et une
        # coupure de courant peut perdre ce qui n'est pas encore sur le
        # disque. L'arrêt brutal n'est qu'un repli, pour un système qui ne
        # répond plus à l'ACPI dans la borne.
        f"qm shutdown {numero} --timeout {EXTINCTION} || qm stop {numero}",
        f"qm template {numero}",
    )


# Borne, en secondes, d'une extinction propre avant le repli brutal.
EXTINCTION = 180

# L'argv qui hache un secret lu sur l'entrée standard, au format crypt(3)
# SHA-512 que d-i accepte. Le secret ne passe JAMAIS sur la ligne de
# commande, qui se lit dans la table des processus par tout compte.
ARGV_HACHAGE = ("openssl", "passwd", "-6", "-stdin")

# La forme d'une clé publique OpenSSH, sur UNE ligne : un type, un corps en
# base64, un commentaire facultatif. Ce qui n'en a pas la forme — une clé
# PRIVÉE en premier lieu — n'est jamais déposé sur le nœud.
FORME_CLE_PUBLIQUE = re.compile(
    r"^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(256|384|521))"
    r" [A-Za-z0-9+/]+={0,3}( [^\n]*)?$"
)


def reseau_de_fabrique(cidr):
    """(adresse, préfixe, passerelle, masque) du gabarit sur `cidr`, ou ().

    `cidr` est l'adresse de la PASSERELLE sur son réseau, telle que le pont
    la porte. Le gabarit prend la DERNIÈRE adresse d'hôte, ou l'avant-
    dernière quand la passerelle tient la dernière : loin du début de la
    plage, où se posent d'ordinaire les adresses qu'on attribue à la main.
    """
    try:
        interface = ipaddress.ip_interface((cidr or "").strip())
    except (TypeError, ValueError):
        return ()
    reseau = interface.network
    if interface.version != 4 or reseau.num_addresses < 4:
        return ()
    adresse = reseau.broadcast_address - 1
    if adresse == interface.ip:
        adresse -= 1
    return (
        str(adresse),
        reseau.prefixlen,
        str(interface.ip),
        str(reseau.netmask),
    )


def chemins_installateur(dossier):
    """Les chemins du nœud où l'installateur est déposé, ou ().

    Rend (noyau, initrd d'origine, initrd porteur du preseed, journal
    série). UNE SEULE SOURCE pour le dépôt et pour l'amorçage : deux listes
    de chemins dérivent, et la VM amorce alors un initrd qui n'est pas
    celui qu'on a préparé.
    """
    base = (dossier or "").strip().rstrip("/")
    if not base.startswith("/"):
        return ()
    return (
        f"{base}/linux",
        f"{base}/initrd.gz",
        f"{base}/initrd-preseed.gz",
        f"{base}/installation.log",
    )


def cmds_preparer_installateur(dossier, urls, texte_preseed):
    """Les commandes qui déposent l'installateur et glissent le preseed dans
    son initrd, ou ().

    LE PRESEED VOYAGE SUR L'ENTRÉE STANDARD, EN BASE64 : il porte le hachage
    root, que sudo journaliserait s'il passait sur la ligne de commande, et
    des « $ » qu'aucun shell ne doit interpréter. Cette étape est donc un
    couple (commande, entrée), que l'appelant joue en passant l'entrée.

    AJOUTÉ À UNE COPIE de l'initrd, qui reste intact : un cpio concaténé
    est lu par le noyau à la suite du premier, et rejouer la préparation
    repart d'un initrd propre plutôt que d'empiler les preseeds.

    LE TÉLÉCHARGEMENT SE REJOUE : wget tient un échec de résolution et un
    refus de connexion pour définitifs, quel que soit --tries.
    """
    chemins = chemins_installateur(dossier)
    if not chemins or len(urls or ()) != 2 or not (texte_preseed or ""):
        return ()
    noyau, initrd, porteur, journal = chemins
    base = shlex.quote(dossier.strip().rstrip("/"))
    racine = f"{base}/racine"
    corps = base64.b64encode(texte_preseed.encode()).decode()
    wget = (
        "wget -nv --tries=5 --waitretry=5 --timeout=30"
        " --retry-on-host-error --retry-connrefused"
    )
    return (
        f"mkdir -p {racine} && chmod 700 {base}",
        f"{wget} -O {shlex.quote(noyau)} {shlex.quote(urls[0])}",
        f"{wget} -O {shlex.quote(initrd)} {shlex.quote(urls[1])}",
        (f"base64 -d > {racine}/preseed.cfg", corps),
        f"cp {shlex.quote(initrd)} {shlex.quote(porteur)}",
        f"cd {racine} && echo preseed.cfg | cpio -H newc -o 2>/dev/null"
        f" | gzip >> {shlex.quote(porteur)}",
        f"rm -f {racine}/preseed.cfg {shlex.quote(journal)}",
    )


def cmds_amorcer(vmid, argv_creation, args):
    """Créer la VM, lui donner les arguments d'amorçage, la démarrer, ou ().

    Les arguments sont CITÉS UNE SECONDE FOIS pour le shell du nœud : voir
    `args_amorce`.
    """
    try:
        numero = int(vmid)
    except (TypeError, ValueError):
        return ()
    if numero < 1 or not argv_creation or not (args or "").strip():
        return ()
    return (
        shlex.join(argv_creation),
        f"qm set {numero} --args {shlex.quote(args)}",
        f"qm start {numero}",
    )


def cmd_statut(vmid):
    """La commande qui dit si la VM tourne, ou « »."""
    try:
        numero = int(vmid)
    except (TypeError, ValueError):
        return ""
    return f"qm status {numero}" if numero >= 1 else ""


def lit_statut(sortie):
    """« running », « stopped », ou None si la sortie ne le dit pas.

    LU PAR SON CHAMP et non cherché dans le texte : « stopped » se trouve
    aussi dans un message d'erreur qui parle d'une VM arrêtée.
    """
    for ligne in (sortie or "").splitlines():
        mots = ligne.split()
        if mots[:1] == ["status:"] and len(mots) == 2:
            return mots[1] if mots[1] in ("running", "stopped") else None
    return None


def cmds_identite(
    vmid, utilisateur, cle, dossier, adresse, prefixe, passerelle, dns
):
    """Les commandes qui donnent au gabarit son compte, sa clé et son
    adresse par Cloud-Init, puis le démarrent. Ou ().

    LA CLÉ EST CELLE PAR LAQUELLE LE MOTEUR ENTRE : il ne pose aucune clé
    au clonage, chaque clone hérite du compte et de la clé du gabarit. Elle
    est refusée si elle n'a pas la forme d'une clé PUBLIQUE sur une ligne.
    """
    try:
        numero, bits = int(vmid), int(prefixe)
    except (TypeError, ValueError):
        return ()
    cle = (cle or "").strip()
    vus = (utilisateur, adresse, passerelle, dns)
    if numero < 1 or not all((vu or "").strip() for vu in vus):
        return ()
    if not FORME_CLE_PUBLIQUE.match(cle) or not 0 < bits <= 32:
        return ()
    chemins = chemins_installateur(dossier)
    if not chemins:
        return ()
    fichier = shlex.quote(dossier.strip().rstrip("/") + "/cle.pub")
    corps = base64.b64encode((cle + "\n").encode()).decode()
    return (
        f"echo {corps} | base64 -d > {fichier}",
        f"qm set {numero} --ciuser {shlex.quote(utilisateur.strip())}"
        f" --sshkeys {fichier}"
        f" --ipconfig0 ip={adresse.strip()}/{bits},gw={passerelle.strip()}"
        f" --nameserver {shlex.quote(dns.strip())}",
        f"qm start {numero}",
    )


def cmd_agent(vmid):
    """La commande qui répond quand l'agent invité est debout, ou « »."""
    try:
        numero = int(vmid)
    except (TypeError, ValueError):
        return ""
    return f"qm guest cmd {numero} ping" if numero >= 1 else ""


def cmd_dans_l_invite(vmid, commande, delai=60):
    """La commande du nœud qui joue `commande` DANS le gabarit, par l'agent.
    Ou « ».

    `qm guest exec` rend son propre code, pas celui de la commande : le
    verdict de celle-ci est dans le JSON qu'il imprime, que `lit_invite`
    lit.
    """
    try:
        numero, borne = int(vmid), int(delai)
    except (TypeError, ValueError):
        return ""
    if numero < 1 or borne < 1 or not (commande or "").strip():
        return ""
    return shlex.join(
        [
            "qm",
            "guest",
            "exec",
            str(numero),
            "--timeout",
            str(borne),
            "--",
            "/bin/sh",
            "-c",
            commande,
        ]
    )


def lit_invite(sortie):
    """(code, sortie) de la commande jouée dans l'invité, ou None.

    FERMÉ PAR DÉFAUT : une commande qui n'a pas fini dans la borne rend un
    JSON sans « exitcode », et se lit comme un doute, jamais comme un
    succès.
    """
    texte = sortie or ""
    debut = texte.find("{")
    if debut < 0:
        return None
    try:
        lu, _fin = json.JSONDecoder().raw_decode(texte[debut:])
    except ValueError:
        return None
    if not isinstance(lu, dict) or not lu.get("exited"):
        return None
    code = lu.get("exitcode")
    if isinstance(code, bool) or not isinstance(code, int):
        return None
    return code, str(lu.get("out-data") or "")


# Ce qu'il faut attendre avant de nettoyer : la fin du premier Cloud-Init,
# puis un apt au repos. Le premier démarrage lance Cloud-Init et les
# minuteurs apt-daily, qui tiennent le verrou de dpkg ; un nettoyage joué
# pendant ce temps échoue sur son « apt-get clean ». ON ATTEND LA FIN, PAS
# LE VERDICT : Cloud-Init peut rendre une erreur pour un module sans rapport
# avec le compte et la clé. La boucle rend 3 si apt ne se tait pas dans sa
# borne, et la commande dit alors pourquoi.
ATTENTE_PREMIER_DEMARRAGE = (
    "cloud-init status --wait >/dev/null 2>&1; i=0;"
    " while systemctl is-active --quiet apt-daily.service"
    " || systemctl is-active --quiet apt-daily-upgrade.service"
    " || pgrep -x 'apt|apt-get|dpkg' >/dev/null;"
    " do i=$((i+1)); [ $i -gt 120 ] && { echo 'apt toujours actif'; exit 3; };"
    " sleep 5; done; cloud-init status || true"
)


# Ce que le système posé dit de lui-même, une ligne « clé=valeur » par
# fait. C'est ce que la procédure du moteur fait vérifier avant de remettre
# le gabarit : une racine ext4 seule, aucun échange, un amorçage EFI, et les
# paquets par lesquels le moteur prend le relais.
CONSTATS_SYSTEME = (
    "printf 'racine=%s\\n' \"$(findmnt -n -o FSTYPE /)\";"
    " printf 'echange=%s\\n' \"$(swapon --show --noheadings | wc -l)\";"
    " [ -d /sys/firmware/efi ] && echo efi=oui || echo efi=non;"
    " for p in " + PAQUETS + "; do"
    " dpkg-query -W -f='${Status}' \"$p\" 2>/dev/null"
    " | grep -q 'install ok installed' || echo \"manque=$p\"; done"
)


def ecarts_systeme(sortie):
    """Ce qui sépare le système posé de ce que la procédure exige, ou None.

    None si la sortie ne porte pas les trois constats : un relevé tronqué ne
    vaut pas un relevé conforme. () si tout est tenu.
    """
    lus, manquants = {}, []
    for ligne in (sortie or "").splitlines():
        cle, egal, valeur = ligne.strip().partition("=")
        if not egal:
            continue
        if cle == "manque":
            manquants.append(valeur)
        else:
            lus.setdefault(cle, valeur)
    if not {"racine", "echange", "efi"} <= set(lus):
        return None
    ecarts = []
    if lus["racine"] != "ext4":
        ecarts.append(f"racine en {lus['racine'] or '?'} et non en ext4")
    if lus["echange"] != "0":
        ecarts.append(f"{lus['echange']} espace(s) d'échange actif(s)")
    if lus["efi"] != "oui":
        ecarts.append("amorcé sans EFI")
    ecarts += [f"paquet absent : {nom}" for nom in manquants]
    return tuple(ecarts)


def ecarts_materiel(config):
    """Ce qui manque à la configuration de la VM AVANT sa conversion, ou None.

    AVANT et non après : convertie, la VM ne démarre plus, et corriger coûte
    un clone. Lu par clé, fermé par défaut — `qm config` n'imprime que ce qui
    diffère du défaut, et une clé absente vaut donc son défaut, que la
    procédure refuse.
    """
    lu = {}
    for ligne in (config or "").splitlines():
        if ":" not in ligne or ligne.startswith((" ", "\t")):
            continue
        cle, valeur = ligne.split(":", 1)
        lu[cle.strip()] = valeur.strip()
    if not lu:
        return None
    ecarts = []
    for cle, voulu in (("machine", MACHINE), ("bios", BIOS)):
        if lu.get(cle) != voulu:
            ecarts.append(f"{cle} : {lu.get(cle) or 'défaut'} et non {voulu}")
    if not lu.get("efidisk0"):
        ecarts.append("aucun disque EFI")
    if "cloudinit" not in lu.get("ide2", ""):
        ecarts.append("aucun lecteur Cloud-Init")
    agent = lu.get("agent", "")
    if agent.split(",")[0] not in ("1", "enabled=1"):
        ecarts.append("agent invité non activé")
    return tuple(ecarts)


def cmds_menage(dossier):
    """Ce qui retire du nœud les pièces de la fabrication, ou ().

    L'initrd porteur du preseed contient le HACHAGE du mot de passe root du
    gabarit : il ne reste pas sur le nœud une fois le gabarit converti.
    """
    if not chemins_installateur(dossier):
        return ()
    return (f"rm -rf {shlex.quote(dossier.strip().rstrip('/'))}",)


# L'AUTORITÉ D'UN CACHE QUI INTERCEPTE, déposée dans le magasin du système.
# Un cache de téléchargement transparent présente SES certificats : un système
# qui ne connaît pas son autorité rejette chaque téléchargement HTTPS sur
# « self-signed certificate in certificate chain ». Déposée dans le gabarit,
# elle vaut pour chacun de ses clones.
CHEMIN_AUTORITE = "/usr/local/share/ca-certificates/erplibre-cache.crt"
FORME_CERTIFICAT = re.compile(
    r"^-----BEGIN CERTIFICATE-----\n"
    r"[A-Za-z0-9+/=\n]+"
    r"-----END CERTIFICATE-----\n?$"
)


def commande_autorite(pem):
    """La commande qui dépose `pem` et reconstruit le magasin, ou « ».

    Ce qui n'a pas la forme d'UN certificat PEM est refusé : une clé privée
    ou un texte quelconque n'a rien à faire dans le magasin d'un modèle.
    """
    texte = (pem or "").strip() + "\n"
    if not FORME_CERTIFICAT.match(texte) or texte.count("BEGIN") != 1:
        return ""
    corps = base64.b64encode(texte.encode()).decode()
    return (
        f"echo {corps} | base64 -d > {CHEMIN_AUTORITE}"
        " && update-ca-certificates"
    )
