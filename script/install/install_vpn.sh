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

  --sso   installe EN PLUS le greffon d'authentification par formulaire web
          (openconnect-sso). Voir la section « greffon SSO » plus bas.
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

# Le script que openconnect appelle pour poser routes et DNS. Il vient d'un
# paquet à part, dont le nom change de famille en famille, et il s'installe à
# des endroits différents : c'est un FICHIER qu'on cherche, pas un binaire du
# PATH, donc `binaries_for` ne peut pas le voir.
#
# Sans lui, la session s'ouvre, openconnect se lance, et l'interface tun
# n'apparaît jamais : le montage échoue trois étages plus haut, sur un
# symptôme qui n'accuse pas le paquet manquant.
VPNC_SCRIPT_PATHS="
/etc/vpnc/vpnc-script
/usr/share/vpnc-scripts/vpnc-script
/usr/libexec/openconnect/vpnc-script
/usr/lib/openconnect/vpnc-script
"

verify_vpnc_script() {
    local fam="$1" path package
    for path in ${VPNC_SCRIPT_PATHS}; do
        if [ -x "$path" ]; then
            log "vpnc-script : ${path}"
            return 0
        fi
    done
    case "$fam" in
        rhel|suse) package="vpnc-script" ;;
        *)         package="vpnc-scripts" ;;
    esac
    die "vpnc-script introuvable — installer le paquet ${package}"
}

verify() {
    local driver="$1" fam="$2" missing=""
    for b in $(binaries_for "$driver"); do
        command -v "$b" >/dev/null || missing="${missing} ${b}"
    done
    if [ -n "$missing" ]; then
        die "toujours absents après installation :${missing}"
    fi
    if [ "$driver" = "openconnect" ]; then
        verify_vpnc_script "$fam"
    fi
    log "vérifié : tout est en place pour ${driver}"
}

# ----------------------------------------------------------------------
# Greffon SSO — authentification par formulaire web (SAML)
#
# Un bloc à part, et supprimable d'un seul geste, parce qu'il porte une
# dette qu'aucun paquet de distribution ne porte pour nous.
#
# openconnect refuse les passerelles qui exigent un navigateur INTÉGRÉ
# (« No SSO handler ») : les distributions le bâtissent sans webview.
# openconnect-sso pilote un vrai navigateur et rend un cookie de session,
# que le pilote monte ensuite lui-même.
#
# Son amont est ARRÊTÉ depuis 2023. Trois conséquences qui ne se
# résoudront pas d'elles-mêmes, et que ce bloc assume :
#
# · ses épingles de version sont intenables sur un Python récent — lxml
#   d'avant la 5 ne COMPILE pas — d'où `--no-deps` et des dépendances
#   choisies à la main ;
# · Qt et lxml viennent de la DISTRIBUTION, pas de PyPI, qui n'a pas de
#   roues pour les Python les plus récents ;
# · il appelle `asyncio.get_event_loop()`, qui lève depuis Python 3.12
#   quand aucune boucle n'est courante. Le correctif ci-dessous est REJOUÉ
#   à chaque installation, car toute réinstallation l'effacerait.
#
# Les noms de paquets ne sont VÉRIFIÉS que sur debian et ubuntu. Sur les
# autres familles ils sont donnés au mieux : une erreur ici se lit
# « paquet introuvable » et ne casse rien d'autre.
sso_packages_for() {
    case "$1" in
        debian) echo "python3-pyqt6 python3-pyqt6.qtwebengine python3-lxml libxcb-cursor0 python3-venv" ;;
        arch)   echo "python-pyqt6 python-pyqt6-webengine python-lxml xcb-util-cursor" ;;
        rhel)   echo "python3-pyqt6 python3-pyqt6-webengine python3-lxml xcb-util-cursor" ;;
        suse)   echo "python3-qt6 python3-lxml xcb-util-cursor" ;;
    esac
}

# Les dépendances RÉELLES du greffon, ses épingles retirées. Qt et lxml
# sont volontairement absents : ils viennent du système, vus par le venv
# grâce à `--system-site-packages`.
SSO_PIP_DEPS="attrs colorama keyring prompt-toolkit pyxdg requests structlog toml PySocks pyotp"

install_sso() {
    local fam="$1" user="${SUDO_USER:-}"
    [ -n "$user" ] || die "greffon SSO : lancer par sudo, pas en root direct
    (le greffon a besoin de l'affichage et du trousseau d'un UTILISATEUR,
     que root n'a pas — d'où \$SUDO_USER)"

    log "── greffon SSO (openconnect-sso) ──"
    log "amont arrêté depuis 2023 : contournements assumés, voir le source"
    # shellcheck disable=SC2086
    install_packages "$fam" $(sso_packages_for "$fam")

    # Le venv appartient à l'UTILISATEUR : root n'a ni son affichage ni son
    # trousseau, et un greffon installé sous root ne lui servirait à rien.
    log "installation sous l'utilisateur ${user}"
    runuser -u "$user" -- sh -s <<'USERPART'
set -eu
VENV="$HOME/.local/share/openconnect-sso-venv"
# `--system-site-packages` : c'est ainsi que le venv voit le Qt et le lxml
# de la distribution, dont PyPI n'a pas de roues pour un Python récent.
[ -x "$VENV/bin/python" ] || /usr/bin/python3 -m venv --system-site-packages "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
# `--no-deps` : les épingles du greffon sont intenables, on choisit nous-mêmes.
"$VENV/bin/pip" install --quiet --no-deps openconnect-sso
USERPART
    # shellcheck disable=SC2086
    runuser -u "$user" -- sh -c \
        "\"\$HOME/.local/share/openconnect-sso-venv/bin/pip\" install --quiet ${SSO_PIP_DEPS}"

    # pip signale ici un conflit sur lxml et keyring. Il est ATTENDU :
    # ce sont les deux épingles qu'on relâche sciemment, l'amont étant
    # arrêté. Le dire, plutôt que de masquer la sortie de pip — une
    # installation qui cache ses erreurs ne se diagnostique plus.
    log "le conflit d'épingles signalé par pip (lxml, keyring) est voulu"
    sso_patch_event_loop "$user"
    sso_verify "$user"
}

sso_patch_event_loop() {
    # `asyncio.get_event_loop()` ne crée plus de boucle implicite quand
    # aucune n'est courante : depuis Python 3.12 il avertit, depuis 3.14 il
    # lève. Le greffon l'appelle à quatre endroits, tous atteints après
    # celui-ci — poser la boucle une fois ici les sert tous.
    runuser -u "$1" -- /usr/bin/python3 - <<'PATCH'
import glob, os, sys

MARK = "# ERPLibre : boucle asyncio explicite"
OLD = """        if os.name == "nt":
            asyncio.set_event_loop(asyncio.ProactorEventLoop())
        auth_response, selected_profile = asyncio.get_event_loop().run_until_complete("""
NEW = """        if os.name == "nt":
            asyncio.set_event_loop(asyncio.ProactorEventLoop())
        else:
            %s : depuis Python 3.12,
            # get_event_loop() n'en crée plus une implicitement.
            asyncio.set_event_loop(asyncio.new_event_loop())
        auth_response, selected_profile = asyncio.get_event_loop().run_until_complete(""" % MARK

root = os.path.expanduser("~/.local/share/openconnect-sso-venv")
found = glob.glob(os.path.join(root, "lib", "python*", "site-packages",
                               "openconnect_sso", "app.py"))
if not found:
    sys.exit("[VPN] ERREUR: app.py du greffon introuvable")
for path in found:
    with open(path) as fh:
        source = fh.read()
    if MARK in source:
        print("[VPN] correctif asyncio : déjà en place")
        continue
    if OLD not in source:
        print("[VPN] correctif asyncio : motif absent, version changée —"
              " à revoir si le greffon ne démarre pas")
        continue
    with open(path, "w") as fh:
        fh.write(source.replace(OLD, NEW, 1))
    print("[VPN] correctif asyncio : appliqué")
PATCH
}

sso_verify() {
    local helper
    helper="$(runuser -u "$1" -- sh -c 'echo "$HOME/.local/share/openconnect-sso-venv/bin/openconnect-sso"')"
    runuser -u "$1" -- "$helper" --help >/dev/null 2>&1 \
        || die "greffon SSO installé mais il ne démarre pas : ${helper}"
    log "vérifié : ${helper}"
    log "le renseigner dans oc_sso_helper si le profil ne le trouve pas"
}

ALL_DRIVERS="l2tp_ipsec wireguard openvpn openconnect sshuttle"

main() {
    case "${1:-}" in
        -h|--help) usage; exit 0 ;;
    esac
    check_root "$@"
    detect_os
    local fam drivers with_sso=0 args=""
    fam="$(family)"
    # `--sso` retiré de la liste avant qu'elle ne serve de liste de
    # pilotes : sans cela il serait pris pour un nom de pilote.
    for arg in "$@"; do
        case "$arg" in
            --sso) with_sso=1 ;;
            *)     args="${args} ${arg}" ;;
        esac
    done
    set -- ${args}
    # Sans argument : tout. C'est ce que « [8] Installer les paquets
    # client » demande quand on ne choisit pas de technologie.
    drivers="${*:-${ALL_DRIVERS}}"
    for driver in ${drivers}; do
        log "── ${driver} ──"
        install_packages "$fam" "$(packages_for "$driver" "$fam")"
        verify "$driver" "$fam"
    done
    disable_autostart
    if [ "$with_sso" -eq 1 ]; then
        install_sso "$fam"
    fi
    log "Terminé. Monter un tunnel : ./script/vpn/vpn.py up --profile <nom>"
}

main "$@"
