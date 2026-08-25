#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Installe Proxmox VE — https://www.proxmox.com — SUR UNE DEBIAN existante.
#
# Pourquoi sur Debian : Proxmox ne publie aucune image cloud. Son ISO est un
# installateur qui formate le disque, ce qui ne se pilote pas depuis un
# déploiement cloud-init. La voie que l'amont documente lui-même pour ce cas
# est « Install Proxmox VE on Debian » : on part de l'image cloud Debian, on
# ajoute le dépôt pve, et les paquets font le reste. Le résultat est le même
# hyperviseur, avec le noyau Proxmox et l'interface web sur :8006.
#
# Architectures : amd64 et arm64 (arm64 officiel depuis PVE 9 — le Release de
# trixie annonce « amd64 arm64 »). PAS s390x : l'index « binary-s390x » du
# dépôt répond 404, le port n'existe pas.
#
# Réglages, par variables d'environnement :
#   PVE_SUITE        suite Debian visée              (défaut : trixie, = PVE 9)
#   PVE_REBOOT       à 1, redémarre à la fin (défaut : ne redémarre PAS —
#                    lancé par SSH, un reboot couperait la session et ferait
#                    passer une installation réussie pour un échec)
#   PVE_KEEP_DEBIAN_KERNEL  à 1, garde le noyau Debian à côté du noyau pve
#   PVE_OS_RELEASE   fichier os-release à lire (défaut : /etc/os-release) ;
#                    sert à vérifier le script depuis une autre distribution
set -euo pipefail

Red='\033[0;31m'
Green='\033[0;32m'
Yellow='\033[0;33m'
Color_Off='\033[0m'

SUITE="${PVE_SUITE:-trixie}"
KEYRING=/usr/share/keyrings/proxmox-archive-keyring.gpg
SOURCES=/etc/apt/sources.list.d/pve-install-repo.sources

# Somme relevée sur la page amont « Install Proxmox VE on Debian 13 Trixie »,
# et VÉRIFIÉE contre le fichier servi. Elle vaut ceinture ET bretelle : c'est
# la clé qui authentifiera tout le reste, et la télécharger sans la contrôler
# reviendrait à faire confiance au seul transport.
KEY_URL="https://enterprise.proxmox.com/debian/proxmox-archive-keyring-${SUITE}.gpg"
KEY_SHA256_trixie=136673be77aba35dcce385b28737689ad64fd785a797e57897589aed08db6e45

# Ce qui a changé : décide du redémarrage final. Une installation déjà faite ne
# doit pas redémarrer la machine pour rien.
CHANGED=0

say() { echo -e "$@"; }
die() { say "${Red}✗${Color_Off} $*"; exit 1; }

DRY=0
usage() {
    cat <<EOF
Installe Proxmox VE sur une Debian existante (amd64, arm64).

  --dry-run   dit ce qu'il ferait, sans rien changer
  --help      cette aide

Variables : PVE_SUITE (défaut trixie), PVE_REBOOT, PVE_KEEP_DEBIAN_KERNEL,
            PVE_OS_RELEASE
EOF
}
while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run) DRY=1 ;;
        -h | --help) usage; exit 0 ;;
        *) die "option inconnue : $1" ;;
    esac
    shift
done

# Toute action qui MODIFIE la machine passe par ici. En dry-run elle est
# annoncée, pas exécutée : c'est ce qui rend le script vérifiable de bout en
# bout sans hyperviseur ni dépôt à disposition.
run() {
    if [ "${DRY}" = "1" ]; then
        say "  ${Yellow}[dry-run]${Color_Off} $*"
        return 0
    fi
    "$@"
}

# --- 1. Architecture --------------------------------------------------------
case "$(uname -m)" in
    x86_64) ARCH=amd64 ;;
    aarch64 | arm64) ARCH=arm64 ;;
    *)
        die "Proxmox VE n'existe pas pour $(uname -m) :" \
            "le dépôt ne publie que amd64 et arm64."
        ;;
esac

# --- 2. Debian, et la bonne suite ------------------------------------------
OS_RELEASE="${PVE_OS_RELEASE:-/etc/os-release}"
[ -r "${OS_RELEASE}" ] || die "${OS_RELEASE} illisible : Debian attendue."
# shellcheck disable=SC1090
. "${OS_RELEASE}"
if [ "${ID:-}" != "debian" ]; then
    die "Proxmox VE s'installe sur Debian, pas sur « ${ID:-inconnu} »." \
        "\n  Redéployer la VM avec --distro proxmox (base Debian ${SUITE})."
fi
CODENAME="${VERSION_CODENAME:-}"
if [ -n "${CODENAME}" ] && [ "${CODENAME}" != "${SUITE}" ]; then
    say "${Yellow}⚠${Color_Off} Debian « ${CODENAME} » alors que le dépôt visé" \
        "est « ${SUITE} » : PVE_SUITE=${CODENAME} si c'est voulu."
fi

# --- 3. /etc/hosts : le nom d'hôte doit résoudre vers une IP ROUTABLE -------
# Ce n'est pas un détail de confort. Le système de grappe de Proxmox parcourt
# toutes les adresses du nom d'hôte jusqu'à en trouver une qui ne soit pas de
# bouclage ; l'entrée « 127.0.1.1 <nom> » que pose l'image cloud Debian le
# mène droit dans le mur, et pveproxy comme pvecm s'en trouvent mal.
# « hostname --ip-address » est le test que l'amont donne lui-même.
host_ip() {
    local ip=""
    for ip in \
        "$(ip -4 route get 1 2>/dev/null | awk '{print $7; exit}')" \
        "$(hostname -I 2>/dev/null | awk '{print $1}')" \
        "$(ip -4 -o addr show scope global 2>/dev/null \
            | awk '{split($4, a, "/"); print a[1]; exit}')"
    do
        case "$ip" in
            127.*) continue ;;
            [0-9]*.[0-9]*.[0-9]*.[0-9]*) echo "$ip"; return 0 ;;
        esac
    done
    return 1
}

# Sans ceci, tout ce que fait fix_hosts est ANNULÉ au prochain démarrage.
# L'image cloud Debian règle « manage_etc_hosts: True » : cloud-init réécrit
# alors /etc/hosts depuis son gabarit à chaque boot, et y remet
# « 127.0.1.1 <nom> ». pmxcfs, qui cherche une adresse non-bouclage pour le
# nom d'hôte, ne démarre plus — /etc/pve n'est pas monté, « pvesm » répond
# « Connection refused », et l'écran de déploiement conclut « il manque le
# stockage ». Le vrai défaut est trois étages plus bas.
#
# Vécu, et révélé par le redémarrage désormais automatique : l'installation
# corrigeait /etc/hosts, le reboot amorçait le noyau Proxmox, et cloud-init
# défaisait la correction dans le même mouvement.
#
# Un fichier de surcharge plutôt qu'une édition de cloud.cfg : c'est la voie
# que cloud-init documente, et une mise à jour du paquet ne l'écrase pas.
freeze_cloud_hosts() {
    local dossier=/etc/cloud/cloud.cfg.d
    local fichier="${dossier}/99-erplibre-hosts.cfg"
    [ -d /etc/cloud ] || return 0
    if [ -f "${fichier}" ]; then
        say "  cloud-init ne touche déjà plus à /etc/hosts"
        return 0
    fi
    say "  cloud-init : gel de /etc/hosts (${fichier})"
    if [ "${DRY}" = "1" ]; then
        say "  ${Yellow}[dry-run]${Color_Off} manage_etc_hosts: false" \
            "> ${fichier}"
        return 0
    fi
    sudo mkdir -p "${dossier}"
    printf '%s\n' \
        "# Posé par ERPLibre : Proxmox exige que le nom d'hôte résolve vers" \
        "# une adresse ROUTABLE. cloud-init y remettait 127.0.1.1 à chaque" \
        "# démarrage, et pmxcfs ne démarrait plus." \
        "manage_etc_hosts: false" \
        | sudo tee "${fichier}" >/dev/null
    CHANGED=1
}

fix_hosts() {
    local ip fqdn short
    ip="$(host_ip)" || die "aucune adresse IPv4 routable : réseau absent ?"
    freeze_cloud_hosts
    short="$(hostname -s)"
    fqdn="$(hostname -f 2>/dev/null || echo "${short}")"
    [ "${fqdn}" = "${short}" ] && fqdn="${short}.local"
    if grep -qE "^[[:space:]]*127\.0\.1\.1[[:space:]]" /etc/hosts; then
        say "  retrait de l'entrée 127.0.1.1 (bouclage) pour ${short}"
        run sudo sed -i -E "/^[[:space:]]*127\.0\.1\.1[[:space:]]/d" \
            /etc/hosts
        CHANGED=1
    fi
    if ! grep -qE "^[[:space:]]*${ip//./\\.}[[:space:]]+.*\b${short}\b" \
        /etc/hosts; then
        say "  ${short} -> ${ip} dans /etc/hosts"
        if [ "${DRY}" = "1" ]; then
            say "  ${Yellow}[dry-run]${Color_Off} ${ip} ${fqdn} ${short}" \
                ">> /etc/hosts"
        else
            printf '%s\t%s %s\n' "${ip}" "${fqdn}" "${short}" \
                | sudo tee -a /etc/hosts >/dev/null
        fi
        CHANGED=1
    fi
    # Le test de l'amont, mot pour mot : au moins une adresse non-bouclage.
    local vu routables
    vu="$(hostname --ip-address 2>/dev/null || true)"
    routables="$(printf '%s\n' ${vu} | grep -vE '^(127\.|::1$)' || true)"
    [ -n "${routables}" ] || die \
        "« hostname --ip-address » rend « ${vu:-rien} » : le nom d'hôte ne" \
        "résout toujours pas vers une adresse routable."
    say "  hostname --ip-address : $(printf '%s ' ${routables})"
    revive_pmxcfs
}

# pmxcfs abandonne après cinq essais rapprochés : systemd marque l'unité
# « failed » et n'y revient JAMAIS de lui-même — « Start request repeated too
# quickly ». Corriger /etc/hosts ne suffit donc pas ; sans ce coup de pouce,
# l'hôte reste sans /etc/pve, donc sans stockage, et l'écran de déploiement
# s'arrête sur « il manque le stockage ».
#
# « reset-failed » d'abord, sinon le démarrage est refusé sans même être tenté.
revive_pmxcfs() {
    command -v systemctl >/dev/null 2>&1 || return 0
    [ -e /etc/pve/.version ] && return 0
    say "  pve-cluster : /etc/pve n'est pas monté, relance"
    if [ "${DRY}" = "1" ]; then
        say "  ${Yellow}[dry-run]${Color_Off} systemctl reset-failed" \
            "pve-cluster && systemctl start pve-cluster"
        return 0
    fi
    sudo systemctl reset-failed pve-cluster 2>/dev/null || true
    if sudo systemctl start pve-cluster 2>&1; then
        CHANGED=1
    fi
    # Le montage n'est pas instantané : on le CONSTATE plutôt que de le
    # supposer, et on le dit quand il n'arrive pas.
    local i
    for i in 1 2 3 4 5 6 7 8 9 10; do
        [ -e /etc/pve/.version ] && break
        sleep 1
    done
    if [ -e /etc/pve/.version ]; then
        say "  ${Green}✓${Color_Off} /etc/pve monté"
    else
        say "  ${Yellow}⚠${Color_Off} /etc/pve toujours absent :" \
            "journalctl -u pve-cluster -n 30"
    fi
}

# --- 4. Dépôt et clé --------------------------------------------------------
add_repo() {
    local attendu="KEY_SHA256_${SUITE}"
    attendu="${!attendu:-}"
    if [ ! -s "${KEYRING}" ]; then
        say "  clé du dépôt -> ${KEYRING}"
        run sudo mkdir -p "$(dirname "${KEYRING}")"
        run sudo wget -q "${KEY_URL}" -O "${KEYRING}" \
            || die "téléchargement de la clé impossible : ${KEY_URL}"
        # Un wget qui rend 0 sans laisser de fichier — proxy captif, disque
        # plein — ferait mourir la suite sur un message de sha256sum au lieu
        # d'un diagnostic.
        if [ "${DRY}" != "1" ]; then
            sudo test -s "${KEYRING}" \
                || die "clé absente ou vide après téléchargement : ${KEYRING}"
        fi
        CHANGED=1
    fi
    if [ -n "${attendu}" ] && [ "${DRY}" = "1" ]; then
        say "  clé à vérifier contre sha256 ${attendu:0:16}…"
    elif [ -n "${attendu}" ]; then
        local vu
        vu="$(sudo sha256sum "${KEYRING}" 2>/dev/null | awk '{print $1}')" \
            || true
        [ -n "${vu}" ] || die "somme de la clé illisible : ${KEYRING}"
        if [ "${vu}" != "${attendu}" ]; then
            # On efface la clé douteuse : la laisser en place ferait passer la
            # prochaine exécution pour bonne, le fichier étant non vide.
            run sudo rm -f "${KEYRING}"
            die "somme de la clé inattendue :\n    vue     ${vu}\n" \
                "   attendue ${attendu}"
        fi
        say "  clé vérifiée (sha256 ${vu:0:16}…)"
    else
        say "${Yellow}⚠${Color_Off} aucune somme connue pour « ${SUITE} » :" \
            "clé acceptée sans contrôle."
    fi
    # Format deb822, celui que l'amont recommande sur Debian 13.
    local voulu
    voulu="$(printf 'Types: deb\nURIs: http://download.proxmox.com/debian/pve\nSuites: %s\nComponents: pve-no-subscription\nSigned-By: %s\n' \
        "${SUITE}" "${KEYRING}")"
    if [ "$(cat "${SOURCES}" 2>/dev/null || true)" != "${voulu}" ]; then
        say "  dépôt pve-no-subscription -> ${SOURCES}"
        if [ "${DRY}" = "1" ]; then
            say "  ${Yellow}[dry-run]${Color_Off} ${SOURCES} :" \
                "$(printf '%s' "${voulu}" | tr '\n' '|')"
        else
            printf '%s\n' "${voulu}" | sudo tee "${SOURCES}" >/dev/null
        fi
        CHANGED=1
    fi
}

# --- 6. Dépôt entreprise ----------------------------------------------------
# « proxmox-ve » installe SON dépôt entreprise (pve-enterprise.sources), qui
# exige un abonnement payant. Sans lui, tout « apt update » ultérieur échoue :
# « 401 Unauthorized » puis « The repository is not signed », et la machine ne
# peut plus rien installer — pas même une mise à jour de sécurité. Mesuré sur
# la VM d'essai, au deuxième passage du script.
#
# On le désactive au lieu de l'effacer : « Enabled: false » est la forme deb822
# prévue pour cela, elle survit aux mises à jour du paquet, et il suffit de
# retirer la ligne le jour où un abonnement existe.
disable_enterprise() {
    local f
    for f in /etc/apt/sources.list.d/pve-enterprise.sources \
        /etc/apt/sources.list.d/ceph.sources; do
        [ -e "${f}" ] || continue
        if sudo grep -qiE '^[[:space:]]*Enabled:[[:space:]]*(false|no)' \
            "${f}"; then
            continue
        fi
        say "  dépôt entreprise désactivé : $(basename "${f}")"
        if [ "${DRY}" = "1" ]; then
            say "  ${Yellow}[dry-run]${Color_Off} Enabled: false >> ${f}"
        else
            printf 'Enabled: false\n' | sudo tee -a "${f}" >/dev/null
        fi
        CHANGED=1
    done
    # Les anciennes formes « .list », au cas où une mise à jour les remette.
    for f in /etc/apt/sources.list.d/pve-enterprise.list; do
        [ -e "${f}" ] || continue
        sudo grep -qE '^[[:space:]]*#' "${f}" && continue
        say "  dépôt entreprise commenté : $(basename "${f}")"
        run sudo sed -i -E 's/^([[:space:]]*deb)/#\1/' "${f}"
        CHANGED=1
    done
}

# --- 5. Les paquets ---------------------------------------------------------
# Disque d'amorçage, pour la préréponse de grub-pc.
boot_disk() {
    local src
    src="$(findmnt -no SOURCE /boot 2>/dev/null \
        || findmnt -no SOURCE / 2>/dev/null)"
    [ -n "${src}" ] || return 1
    local dq
    dq="$(lsblk -no pkname "${src}" 2>/dev/null | head -1)"
    [ -n "${dq}" ] || return 1
    printf '/dev/%s\n' "${dq}"
}

# Deux paquets posent des questions debconf, et une seule sans réponse suffit à
# faire échouer TOUTE la transaction apt :
#
# - postfix demande son type et son nom de courrier. Sans préréponse,
#   l'installation attend une saisie que personne ne verra — un déploiement
#   par SSH y reste pendu.
# - grub-pc demande SUR QUEL DISQUE s'installer. C'est le piège propre à
#   l'image cloud : elle amorce en EFI (grub-cloud-amd64), les paquets pve
#   tirent grub-pc par-dessus, et sa post-installation refuse de deviner —
#   « You must correct your GRUB install devices before proceeding », mesuré,
#   dpkg s'arrête et le noyau Proxmox reste à moitié configuré.
preseed_debconf() {
    command -v debconf-set-selections >/dev/null 2>&1 || return 0
    local lignes disque
    lignes="$(printf '%s\n' \
        "postfix postfix/main_mailer_type select Local only" \
        "postfix postfix/mailname string $(hostname -f 2>/dev/null \
            || hostname -s)")"
    if disque="$(boot_disk)"; then
        lignes="$(printf '%s\n%s\n' "${lignes}" \
            "grub-pc grub-pc/install_devices multiselect ${disque}")"
    else
        say "${Yellow}⚠${Color_Off} disque d'amorçage introuvable :" \
            "grub-pc pourrait demander où s'installer."
    fi
    # Pas de tube vers « run » : en dry-run il ne lirait pas son entrée, le
    # printf recevrait SIGPIPE, et « set -o pipefail » emporterait le script —
    # mort silencieuse sur un code 141. Vécu.
    if [ "${DRY}" = "1" ]; then
        say "  ${Yellow}[dry-run]${Color_Off} debconf-set-selections :" \
            "$(printf '%s' "${lignes}" | tr '\n' '|')"
        return 0
    fi
    printf '%s\n' "${lignes}" | sudo debconf-set-selections
}

# « DPkg::Lock::Timeout » : sur une VM fraîchement déployée, cloud-init tient
# encore le verrou d'apt — mesuré, « E: Could not get lock
# /var/lib/apt/lists/lock. It is held by process 996 (apt-get) », et le script
# mourait 40 secondes après le démarrage. apt sait ATTENDRE son tour depuis la
# 1.9 ; sans cette option il abandonne immédiatement.
apt_get() {
    run sudo env DEBIAN_FRONTEND=noninteractive \
        apt-get -o Dpkg::Options::=--force-confold \
        -o DPkg::Lock::Timeout=600 -y "$@"
}

# Attendre la fin de cloud-init AVANT de toucher à apt : c'est lui qui pose les
# paquets de la première mise en route. Son état final n'est PAS un critère —
# vérifié sur l'image Debian 13, où il rend « error » pour deux modules sans
# rapport (console-setup absent, update-locale) tout en ayant terminé son
# travail. On attend qu'il ait fini, pas qu'il soit content.
wait_cloud_init() {
    command -v cloud-init >/dev/null 2>&1 || return 0
    say "  attente de la fin de cloud-init…"
    if [ "${DRY}" = "1" ]; then
        say "  ${Yellow}[dry-run]${Color_Off} cloud-init status --wait"
        return 0
    fi
    timeout 600 cloud-init status --wait >/dev/null 2>&1 || true
    return 0
}

install_pve() {
    wait_cloud_init
    preseed_debconf
    # Réparer une transaction laissée à moitié par une exécution précédente :
    # sans réponse à grub-pc, dpkg s'arrête au milieu et tout apt suivant
    # refuse de travailler. Inoffensif quand rien n'est cassé.
    if ! sudo dpkg -C >/dev/null 2>&1; then
        say "  paquets à moitié configurés : dpkg --configure -a"
        run sudo env DEBIAN_FRONTEND=noninteractive dpkg --configure -a \
            || true
    fi
    # AVANT le premier apt : sur un second passage, le dépôt entreprise posé
    # par proxmox-ve ferait échouer « apt update » (401) et rien n'irait plus
    # loin — pas même la désactivation, si elle attendait la fin.
    disable_enterprise
    say "\n---- apt update ----"
    apt_get update
    # Le noyau d'abord, comme l'amont le prescrit : c'est lui qui porte les
    # modules dont pve a besoin, et l'installer seul laisse une machine qui
    # redémarre proprement même si la suite échoue.
    if ! dpkg -s proxmox-default-kernel >/dev/null 2>&1; then
        say "\n---- noyau Proxmox ----"
        apt_get install proxmox-default-kernel
        CHANGED=1
    else
        say "  noyau Proxmox déjà posé"
    fi
    if ! dpkg -s proxmox-ve >/dev/null 2>&1; then
        say "\n---- proxmox-ve, postfix, open-iscsi, chrony ----"
        apt_get install proxmox-ve postfix open-iscsi chrony
        CHANGED=1
        # C'est CETTE installation qui vient de poser le dépôt entreprise :
        # le désactiver tout de suite, avant que le ménage ne rappelle apt.
        disable_enterprise
    else
        say "  proxmox-ve déjà posé"
    fi
}

# --- 6. Ménage --------------------------------------------------------------
# os-prober ajoute au menu d'amorçage les systèmes trouvés sur les disques des
# VM invitées : sur un hyperviseur, c'est une liste de faux départs.
# Le noyau Debian, lui, n'a plus de raison d'être une fois celui de pve en
# place — et laissé par défaut, grub peut y revenir.
cleanup() {
    if dpkg -s os-prober >/dev/null 2>&1; then
        say "  retrait d'os-prober"
        apt_get remove os-prober
        CHANGED=1
    fi
    [ "${PVE_KEEP_DEBIAN_KERNEL:-0}" = "1" ] && return 0
    # Ne JAMAIS retirer le noyau Debian si celui de Proxmox n'est pas posé :
    # la machine ne redémarrerait plus. Vérifié, pas supposé — une étape apt
    # peut avoir échoué plus haut sans arrêter le reste.
    if ! dpkg -s proxmox-default-kernel >/dev/null 2>&1; then
        say "  noyau Proxmox absent : le noyau Debian reste en place."
        return 0
    fi
    local metas
    # Tout « linux-image-* » SAUF ceux de Proxmox. L'amont écrit
    # « linux-image-6.12* », la version de trixie ; le motif large couvre les
    # versions suivantes, et l'exclusion protège le noyau qu'on vient de
    # poser — le retirer laisserait une VM qui n'amorce plus.
    # « db:Status-Status » filtre les paquets RÉELLEMENT installés : dpkg
    # connaît aussi ceux qu'il a désinstallés (« config-files »,
    # « not-installed »), et les passer à apt donnait « is not installed, so
    # not removed » — puis un CHANGED=1 qui réclamait un redémarrage inutile.
    metas="$(dpkg-query -W -f '${Package} ${db:Status-Status}\n' \
        'linux-image-*' 2>/dev/null \
        | awk '$2 == "installed" {print $1}' \
        | grep -vE 'pve|proxmox' || true)"
    if [ -n "${metas}" ]; then
        say "  retrait du noyau Debian : $(echo "${metas}" | tr '\n' ' ')"
        # shellcheck disable=SC2086
        apt_get remove ${metas}
        run sudo update-grub 2>/dev/null || true
        CHANGED=1
    fi
    return 0
}

# --- 6bis. Amorçage EFI de secours -----------------------------------------
# Une image cloud amorce par le CHEMIN DE SECOURS de l'UEFI —
# \EFI\BOOT\BOOTX64.EFI — parce qu'aucune entrée NVRAM ne la nomme. Les
# paquets grub de Proxmox y recopient bien leurs binaires, mais PAS le petit
# grub.cfg qui indique où trouver la vraie configuration. GRUB s'arrête alors
# sur son invite de secours « grub> » : ni menu, ni noyau.
#
# Vécu, capture d'écran à l'appui : après le premier redémarrage, la VM brûlait
# 100 % d'un cœur SANS lire une seule fois le disque, et l'écran affichait
# « starting Boot0001 UEFI Misc Device » suivi de « grub> ».
#
# On recopie le stub que Debian a généré pour son propre chemin : il porte
# l'UUID de la racine, donc il fonctionne depuis n'importe quel chargeur.
# « grub-install --removable » ferait la même chose en réécrivant le chargeur ;
# copier un fichier est plus sûr — cela ne touche pas au chemin qui marche.
fix_efi_fallback() {
    local esp="${PVE_ESP:-/boot/efi}"
    local secours="${esp}/EFI/BOOT"
    # sudo sur CHAQUE lecture. /boot/efi est une vfat montée « umask=077 » :
    # root seul y entre, et un « [ -d ] » non privilégié y répond FAUX. Ce
    # correctif ne faisait donc RIEN, en silence, et la VM retombait sur
    # « grub> » au redémarrage suivant — vécu deux fois. Le glob du shell est
    # aveugle pour la même raison : il faut énumérer avec sudo.
    sudo test -d "${secours}" || return 0
    sudo test -e "${secours}/grub.cfg" && return 0
    local stub=""
    # « || true » : quand aucun stub n'existe, grep ne trouve rien et rend 1
    # — avec « set -o pipefail », l'affectation échoue et le script s'arrête
    # AVANT d'avoir dit ce qui manque. Attrapé par un test, pas sur la machine
    # réelle, où un stub existait et masquait le cas.
    stub="$(sudo sh -c "ls ${esp}/EFI/*/grub.cfg 2>/dev/null" \
        | grep -v '/EFI/BOOT/grub.cfg' | head -1 || true)"
    if [ -z "${stub}" ]; then
        say "${Yellow}⚠${Color_Off} aucun grub.cfg à recopier sous ${esp} :" \
            "vérifier l'amorçage avant de redémarrer."
        return 0
    fi
    say "  amorçage de secours : $(dirname "${stub}" | xargs basename)/grub.cfg" \
        "-> EFI/BOOT/"
    run sudo cp "${stub}" "${secours}/grub.cfg"
    CHANGED=1
}

# --- 7. Déroulé -------------------------------------------------------------
say "${Green}==>${Color_Off} Proxmox VE ${SUITE} sur ${ARCH}"
say "\n---- nom d'hôte et /etc/hosts ----"
fix_hosts
say "\n---- dépôt Proxmox ----"
add_repo
install_pve
say "\n---- ménage ----"
cleanup
say "\n---- amorçage ----"
fix_efi_fallback

IP="$(host_ip || echo localhost)"
if [ "${DRY}" = "1" ]; then
    # Ne rien annoncer qui n'ait eu lieu : en dry-run, rien n'a été installé.
    say "\n${Yellow}✓${Color_Off} dry-run terminé : rien n'a été changé."
    say "  Ce qui serait joignable ensuite : https://${IP}:8006"
    exit 0
fi
say "\n${Green}✓${Color_Off} Proxmox VE installé."
say "  Interface web : ${Green}https://${IP}:8006${Color_Off}"
# Proxmox authentifie par PAM : c'est le root du système qui ouvre l'interface.
# Sur une image cloud il est VERROUILLÉ (« passwd -S root » rend « L »), donc
# l'interface est inutilisable tant qu'on ne lui a pas donné un mot de passe.
# Le dire ici plutôt que de laisser chercher devant un formulaire qui refuse.
if [ "$(sudo passwd -S root 2>/dev/null | awk '{print $2}')" = "L" ]; then
    say "  Compte        : root, ${Yellow}sans mot de passe${Color_Off} —" \
        "l'interface le refusera. À faire : ${Green}sudo passwd root${Color_Off}"
else
    say "  Compte        : root (mot de passe du système)"
fi
say "  Une VM Proxmox est un hyperviseur DANS une VM : ses propres invités"
say "  demandent la virtualisation imbriquée à tous les étages."

if [ "${CHANGED}" = "0" ]; then
    say "\n  Rien n'a changé : pas de redémarrage."
    exit 0
fi
if [ "${PVE_REBOOT:-0}" != "1" ]; then
    say "\n${Yellow}⚠${Color_Off} Redémarrage NÉCESSAIRE pour amorcer le" \
        "noyau Proxmox : sudo reboot"
    exit 0
fi
say "\n---- redémarrage pour amorcer le noyau Proxmox ----"
run sudo systemctl reboot
