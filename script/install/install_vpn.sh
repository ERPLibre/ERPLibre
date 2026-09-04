#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Paquets client VPN, par pilote de script/vpn/drivers/.
#
#   sudo bash script/install/install_vpn.sh l2tp_ipsec
#
# Un groupe de paquets par pilote : le nom passé en argument est le `name` du
# pilote, et non un nom de paquet. C'est le CLI (script/vpn/vpn.py install)
# qui appelle ce script, et il ne connaît que les noms de pilotes.
#
# Ce script INSTALLE et ne configure rien : la configuration est rendue au
# montage du tunnel, dans un tmpfs, par le pilote. Il désactive tout de même
# le démarrage automatique des services — un strongSwan ou un xl2tpd lancé au
# boot tiendrait UDP 500/1701 et empêcherait l'instance dédiée au profil de
# s'attacher.
set -euo pipefail

log() { echo "[VPN] $*"; }
die() { echo "[VPN] ERREUR: $*" >&2; exit 1; }

usage() {
    cat <<'USAGE'
Usage : sudo bash script/install/install_vpn.sh <pilote>

Pilotes connus :
  l2tp_ipsec    strongSwan + xl2tpd + pppd (L2TP/IPsec à clé pré-partagée)
  wireguard     wireguard-tools
  openvpn       openvpn
  openconnect   openconnect + vpnc-scripts
  sshuttle      sshuttle (sur RHEL/Rocky/Alma : dépôt EPEL requis)

Sans argument : tous les pilotes.
USAGE
}

check_root() {
    [ "$(id -u)" -eq 0 ] || die "à lancer en root : sudo bash $0 $*"
}

detect_os() {
    [ -f /etc/os-release ] || die "OS indéterminable (pas de /etc/os-release)"
    # shellcheck disable=SC1091
    . /etc/os-release
    OS="${ID}"
    OS_LIKE="${ID_LIKE:-}"
    log "OS détecté : ${OS}"
}

family() {
    case "$OS" in
        ubuntu|debian|linuxmint|pop|elementary|raspbian) echo debian; return ;;
        arch|manjaro|endeavouros|artix|garuda) echo arch; return ;;
        fedora|rhel|centos|almalinux|rocky) echo rhel; return ;;
        opensuse*|sles|sled) echo suse; return ;;
    esac
    case "$OS_LIKE" in
        *debian*|*ubuntu*) echo debian; return ;;
        *arch*)            echo arch;   return ;;
        *rhel*|*fedora*)   echo rhel;   return ;;
        *suse*)            echo suse;   return ;;
    esac
    die "famille de distribution inconnue : ${OS} (ID_LIKE=${OS_LIKE})"
}

# Les paquets, par pilote puis par famille. `strongswan-starter` fournit la
# commande `ipsec` et le démon starter, que le pilote L2TP utilise ; les
# paquets `charon-systemd`/`swanctl` seuls ne la fournissent PAS.
packages_for() {
    local driver="$1" fam="$2"
    case "${driver}:${fam}" in
        # libstrongswan-standard-plugins apporte le greffon openssl, et
        # avec lui 3DES. Sans ce paquet, charon ANNONCE 3DES, le
        # concentrateur le choisit — c'est souvent le seul qu'il connaisse —
        # et la négociation meurt sur « ENCRYPTION_ALGORITHM 3DES_CBC not
        # supported! ». Mesuré sur Ubuntu 24.04 : greffons chargés sans lui,
        # « aes md5 rc2 sha1 », donc pas de 3DES.
        l2tp_ipsec:debian)
            echo "strongswan strongswan-starter libstrongswan-standard-plugins libcharon-extra-plugins xl2tpd ppp" ;;
        l2tp_ipsec:arch)   echo "strongswan xl2tpd ppp" ;;
        l2tp_ipsec:rhel)   echo "strongswan xl2tpd ppp" ;;
        l2tp_ipsec:suse)   echo "strongswan xl2tpd ppp" ;;

        # wireguard-tools fournit wg ET wg-quick. Le module noyau est dans
        # Linux depuis 5.6 : rien à compiler sur les distributions visées.
        wireguard:*)       echo "wireguard-tools" ;;

        openvpn:*)         echo "openvpn" ;;

        # vpnc-scripts porte le script que openconnect appelle pour poser
        # les routes et le DNS. Sans lui, la session s'ouvre et la machine
        # ne voit rien passer.
        openconnect:debian) echo "openconnect vpnc-scripts" ;;
        openconnect:*)     echo "openconnect" ;;

        sshuttle:*)        echo "sshuttle" ;;

        *) die "pilote inconnu : ${driver}. Voir --help." ;;
    esac
}

install_packages() {
    local fam="$1"; shift
    log "Installation : $*"
    case "$fam" in
        debian)
            export DEBIAN_FRONTEND=noninteractive
            apt-get update -qq
            # shellcheck disable=SC2086
            apt-get install -y --no-install-recommends $*
            ;;
        arch)
            # shellcheck disable=SC2086
            pacman -Sy --needed --noconfirm $*
            ;;
        rhel)
            # shellcheck disable=SC2086
            { command -v dnf >/dev/null && dnf install -y $*; } \
                || yum install -y $*
            ;;
        suse)
            # shellcheck disable=SC2086
            zypper --non-interactive install $*
            ;;
    esac
}

disable_autostart() {
    # Un service lancé au boot tient le port et fait échouer l'instance
    # dédiée au profil. On les arrête et on les désactive : le pilote
    # démarre ce dont il a besoin, quand il en a besoin.
    command -v systemctl >/dev/null || return 0
    for unit in xl2tpd strongswan-starter strongswan ipsec; do
        if systemctl list-unit-files "${unit}.service" >/dev/null 2>&1 \
            && systemctl is-enabled "${unit}.service" >/dev/null 2>&1; then
            log "désactivation de ${unit}.service (le pilote le pilote)"
            systemctl disable --now "${unit}.service" >/dev/null 2>&1 || true
        fi
    done
}

# Les binaires que chaque pilote exige, en miroir de `binaries` dans
# script/vpn/drivers/. Un paquet installé sans son binaire (nom changé,
# dépôt incomplet) doit être vu ICI, pas au premier montage.
binaries_for() {
    case "$1" in
        l2tp_ipsec)  echo "ipsec xl2tpd pppd ip" ;;
        wireguard)   echo "wg wg-quick ip" ;;
        openvpn)     echo "openvpn ip" ;;
        openconnect) echo "openconnect ip" ;;
        sshuttle)    echo "sshuttle ssh" ;;
    esac
}

verify() {
    local driver="$1" missing=""
    for b in $(binaries_for "$driver"); do
        command -v "$b" >/dev/null || missing="${missing} ${b}"
    done
    if [ -n "$missing" ]; then
        die "toujours absents après installation :${missing}"
    fi
    log "vérifié : tout est en place pour ${driver}"
}

ALL_DRIVERS="l2tp_ipsec wireguard openvpn openconnect sshuttle"

main() {
    case "${1:-}" in
        -h|--help) usage; exit 0 ;;
    esac
    check_root "$@"
    detect_os
    local fam drivers
    fam="$(family)"
    # Sans argument : tout. C'est ce que « [8] Installer les paquets
    # client » demande quand on ne choisit pas de technologie.
    drivers="${*:-${ALL_DRIVERS}}"
    for driver in ${drivers}; do
        log "── ${driver} ──"
        install_packages "$fam" "$(packages_for "$driver" "$fam")"
        verify "$driver"
    done
    disable_autostart
    log "Terminé. Monter un tunnel : ./script/vpn/vpn.py up --profile <nom>"
}

main "$@"
