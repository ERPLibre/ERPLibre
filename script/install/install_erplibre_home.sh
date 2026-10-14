#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Installe ERPLibre Home sans Odoo, à deux niveaux. La base : l'extension
# GNOME liée au dépôt, ses schémas et ses traductions, puis activée ; ni
# accès au périphérique ni venv. --stream-deck ajoute le niveau Stream Deck
# par-dessus la base : paquets USB, règle udev, venv dédié .venv.streamdeck.
# Le niveau Stream Deck inclut toujours la base ; la base s'installe seule.
#
#   ./script/install/install_erplibre_home.sh [--stream-deck] [--no-enable]
#       [--extension-only] [--with-extras] [--uninstall] [--dry-run] [--help]
#
# Codes de sortie : 0 fait (installé ou désinstallé) ; 2 système non
# supporté, avec UNE ligne « UNSUPPORTED: <raison> » sur la sortie
# d'erreur ; 1 tout autre échec.
#
# Tourne sous le compte de l'utilisateur et refuse root : le venv,
# l'extension et les clés gsettings lui appartiennent. sudo ne sert qu'aux
# paquets système et à la règle udev. Se lance de n'importe où : le script
# se place à la racine du dépôt qui le contient.
#
# Trois variables remplacent une lecture du système, pour les tests :
#   ERPLIBRE_HOME_OS_RELEASE     fichier lu à la place de /etc/os-release
#   ERPLIBRE_HOME_GNOME_VERSION  version lue à la place de « gnome-shell
#                                --version » ; « none » : pas de GNOME Shell
#   ERPLIBRE_HOME_UID            remplace « id -u »
set -euo pipefail

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${RACINE}"

UUID="erplibre-home@technolibre.ca"
EXT_SRC="${RACINE}/script/gnome-extension/erplibre_home"
EXT_LINK="${HOME}/.local/share/gnome-shell/extensions/${UUID}"
METADATA="${EXT_SRC}/metadata.json"
UDEV_RULE="/etc/udev/rules.d/70-streamdeck.rules"
VENV="${RACINE}/.venv.streamdeck"
OS_RELEASE="${ERPLIBRE_HOME_OS_RELEASE:-/etc/os-release}"

STREAM_DECK=0
NO_ENABLE=0
EXTENSION_ONLY=0
WITH_EXTRAS=0
UNINSTALL=0
DRY_RUN=0

OS=""
OS_LIKE=""
FAMILY=""
GNOME_VERSION=""

log() { echo "[ERPLibre Home] $*"; }
die() {
    echo "[ERPLibre Home] ERREUR : $*" >&2
    exit 1
}
# Le code 2 et la ligne « UNSUPPORTED: » sont lus par TODO et par le test
# long : la raison tient sur une ligne, en anglais, et rien d'autre ne part
# sur la sortie d'erreur avant elle.
unsupported() {
    echo "UNSUPPORTED: $*" >&2
    exit 2
}

usage() {
    cat <<'USAGE'
Usage : ./script/install/install_erplibre_home.sh [options]

Installe ERPLibre Home sans Odoo : l'extension GNOME erplibre-home, ses
schémas et ses traductions, activée. --stream-deck y ajoute le Stream Deck.

  --stream-deck     ajoute le niveau Stream Deck : paquets USB, règle udev,
                    .venv.streamdeck ; la base s'installe aussi, au besoin
  --no-enable       n'active pas l'extension ; un poste où l'ancienne
                    extension était active garde cet état sous le
                    nouveau nom (migration)
  --extension-only  migration de l'ancienne identité, lien, schémas et
                    traductions de l'extension seulement, sans sudo ni
                    vérification du système ; ne se combine ni avec
                    --stream-deck ni avec --uninstall
  --with-extras     ajoute mpv, yt-dlp, nmap, keepassxc, xdotool et le
                    module Python lz4 du système ; un paquet absent est
                    signalé, jamais fatal
  --uninstall       retire tout : extension, règle udev, .venv.streamdeck ;
                    avec --stream-deck, la règle et le venv seulement, et
                    l'extension reste active ; les paquets système restent
  --dry-run         affiche ce qui serait fait, sans rien changer ni
                    appeler sudo
  -h, --help        cette aide

Codes de sortie : 0 fait ; 2 système non supporté (une ligne
« UNSUPPORTED: <raison> » sur la sortie d'erreur) ; 1 autre échec.
USAGE
}

parse_args() {
    while [ $# -gt 0 ]; do
        case "$1" in
            --stream-deck) STREAM_DECK=1 ;;
            --no-enable) NO_ENABLE=1 ;;
            --extension-only) EXTENSION_ONLY=1 ;;
            --with-extras) WITH_EXTRAS=1 ;;
            --uninstall) UNINSTALL=1 ;;
            --dry-run) DRY_RUN=1 ;;
            -h | --help)
                usage
                exit 0
                ;;
            *)
                usage >&2
                die "option inconnue : $1"
                ;;
        esac
        shift
    done
    # --extension-only est l'entrée étroite de
    # « make erplibre_home_install_extension » : l'étape de l'extension
    # seule, que le niveau Stream Deck et la désinstallation dépassent.
    if [ "${EXTENSION_ONLY}" = 1 ] \
        && [ $((STREAM_DECK + UNINSTALL)) -gt 0 ]; then
        die "--extension-only ne se combine ni avec --stream-deck ni avec" \
            "--uninstall"
    fi
    if [ "${UNINSTALL}" = 1 ] \
        && [ $((NO_ENABLE + WITH_EXTRAS)) -gt 0 ]; then
        die "--uninstall ne se combine qu'avec --stream-deck et --dry-run"
    fi
}

check_not_root() {
    local uid="${ERPLIBRE_HOME_UID:-$(id -u)}"
    if [ "${uid}" = 0 ]; then
        die "à lancer sous votre compte, pas en root : le venv, l'extension" \
            "et gsettings appartiennent à l'utilisateur, et le script appelle" \
            "sudo lui-même pour les paquets et la règle udev"
    fi
}

# ID et ID_LIKE sont lus dans un sous-shell : sourcer os-release dans le
# script même y déposerait NAME, VERSION et le reste parmi ses variables.
detect_os() {
    if [ "$(uname -s)" = Darwin ]; then
        unsupported "macOS is not handled"
    fi
    [ -r "${OS_RELEASE}" ] || unsupported "unknown system (no ${OS_RELEASE})"
    # Un fichier qui ne se source pas ferait sortir le script avec le code
    # du sous-shell et un message de bash : il finit en « unsupported ».
    # shellcheck disable=SC1090
    OS="$(. "${OS_RELEASE}" 2>/dev/null && echo "${ID:-}")" \
        || unsupported "unreadable ${OS_RELEASE}"
    # shellcheck disable=SC1090
    OS_LIKE="$(. "${OS_RELEASE}" 2>/dev/null && echo "${ID_LIKE:-}")" \
        || unsupported "unreadable ${OS_RELEASE}"
}

# Pose FAMILY plutôt que de l'écrire sur la sortie : appelée dans « $(…) »,
# le code 2 de unsupported se perdrait dans le sous-shell. L'ID exact passe
# avant ID_LIKE ; un dérivé inconnu est rattaché par son ID_LIKE.
detect_family() {
    case "${OS}" in
        nixos)
            unsupported "NixOS is not handled: its packages are declared" \
                "in the system configuration, not installed"
            ;;
        ubuntu | debian | linuxmint | pop | elementary | raspbian)
            FAMILY=debian
            return
            ;;
        arch | manjaro | endeavouros | artix | garuda)
            FAMILY=arch
            return
            ;;
        fedora | rhel | centos | almalinux | rocky)
            FAMILY=rhel
            return
            ;;
        opensuse* | sles | sled)
            FAMILY=suse
            return
            ;;
    esac
    case "${OS_LIKE}" in
        *debian* | *ubuntu*) FAMILY=debian ;;
        *arch*) FAMILY=arch ;;
        *rhel* | *fedora*) FAMILY=rhel ;;
        *suse*) FAMILY=suse ;;
        *) unsupported "unknown distribution ${OS} (ID_LIKE=${OS_LIKE})" ;;
    esac
}

# wmctrl, un paquet du niveau Stream Deck, n'est pas dans les dépôts de base
# d'AlmaLinux et de Rocky Linux : EPEL le porte. Fedora l'a dans les siens,
# et EPEL n'y existe pas. L'appelant n'active EPEL qu'avec --stream-deck.
needs_epel() {
    case "${OS}" in
        almalinux | rocky) return 0 ;;
    esac
    return 1
}

# Les versions de « shell-version » dans metadata.json, séparées par une
# espace. tr, grep et sed, et non python3 : le python3 du système est un
# paquet de base que l'étape des paquets installe, APRÈS cette lecture. Les
# sauts de ligne sont retirés d'abord, si bien que le tableau se lit qu'il
# tienne sur une ligne ou sur plusieurs. Ne rend rien quand la clé manque.
shell_versions() {
    tr -d '\n\r' <"${METADATA}" \
        | grep -o '"shell-version"[^]]*' \
        | grep -o '"[0-9][^"]*"' \
        | tr -d '"' | tr '\n' ' ' | sed 's/ *$//'
}

# Le majeur de la version doit figurer dans « shell-version » de
# metadata.json, la liste même que GNOME Shell confronte à sa version avant
# de charger l'extension. La lire là, plutôt que d'en tenir une copie ici,
# empêche les deux listes de diverger.
check_gnome() {
    local accepted major
    if [ -n "${ERPLIBRE_HOME_GNOME_VERSION:-}" ]; then
        GNOME_VERSION="${ERPLIBRE_HOME_GNOME_VERSION}"
    elif command -v gnome-shell >/dev/null 2>&1; then
        # Un gnome-shell qui échoue laisse la version vide, et le « die »
        # ci-dessous sort en 1 : son propre code ne doit pas devenir celui
        # du script, que 2 réserve à « unsupported ».
        GNOME_VERSION="$(gnome-shell --version 2>/dev/null \
            | sed -n 's/^GNOME Shell //p')" || GNOME_VERSION=""
        [ -n "${GNOME_VERSION}" ] \
            || die "« gnome-shell --version » ne rend aucune version lisible"
    else
        GNOME_VERSION=none
    fi
    [ "${GNOME_VERSION}" != none ] || unsupported "no GNOME Shell"
    accepted="$(shell_versions)" || accepted=""
    [ -n "${accepted}" ] || die "shell-version illisible dans ${METADATA}"
    major="${GNOME_VERSION%%.*}"
    case " ${accepted} " in
        *" ${major} "*) ;;
        *) unsupported "GNOME ${GNOME_VERSION} not in shell-version (${accepted})" ;;
    esac
}

# Paquets de la base, par famille : de quoi compiler les schémas (glib) et
# les traductions (msgfmt, de gettext), et le python3 du système, qui lance
# la migration de l'ancienne identité de l'extension.
packages_for() {
    case "$1" in
        debian) echo "libglib2.0-bin gettext python3" ;;
        rhel) echo "glib2 gettext python3" ;;
        suse) echo "glib2-tools gettext-tools python3" ;;
        arch) echo "glib2 gettext python" ;;
        *) die "famille inconnue : $1" ;;
    esac
}

# Paquets du niveau Stream Deck, par famille : hidapi et libusb pour parler
# au deck, le module venv, et wmctrl pour keyboard_talk.py. opencv-python
# arrive en roue manylinux par pip et ne demande rien ici.
streamdeck_packages_for() {
    case "$1" in
        debian) echo "libhidapi-libusb0 libusb-1.0-0 python3-venv wmctrl" ;;
        rhel) echo "hidapi libusb1 python3 wmctrl" ;;
        suse) echo "libhidapi-libusb0 libusb-1_0-0 python3 wmctrl" ;;
        arch) echo "hidapi libusb python wmctrl" ;;
        *) die "famille inconnue : $1" ;;
    esac
}

# level_packages FAMILLE rend les paquets du niveau choisi : ceux de la
# base, puis, avec --stream-deck, ceux du deck que la base ne porte pas déjà
# (le python3 du venv est celui de la base sur dnf, zypper et pacman).
level_packages() {
    local pkgs pkg
    pkgs="$(packages_for "$1")"
    if [ "${STREAM_DECK}" = 1 ]; then
        for pkg in $(streamdeck_packages_for "$1"); do
            case " ${pkgs} " in
                *" ${pkg} "*) ;;
                *) pkgs="${pkgs} ${pkg}" ;;
            esac
        done
    fi
    echo "${pkgs}"
}

# Outils facultatifs des indicateurs, donc de la base. lz4 est le module
# Python du SYSTÈME : l'import des onglets Firefox tourne sous le python3 que
# lance prefs.js, et un lz4 posé dans le venv ne le servirait pas.
extras_for() {
    case "$1" in
        debian | rhel | suse) echo "mpv yt-dlp nmap keepassxc xdotool python3-lz4" ;;
        arch) echo "mpv yt-dlp nmap keepassxc xdotool python-lz4" ;;
        *) die "famille inconnue : $1" ;;
    esac
}

# package_cmd FAMILLE PAQUET... rend, sur une ligne, la commande non
# interactive qui installe ces paquets avec le gestionnaire de la famille.
# Fonction pure : --dry-run affiche cette ligne, l'installation exécute la
# même, et les deux ne peuvent pas diverger. Un paquet déjà présent est
# sauté par le gestionnaire lui-même.
package_cmd() {
    local fam="$1"
    shift
    case "${fam}" in
        debian)
            echo "sudo apt-get update -qq && sudo env" \
                "DEBIAN_FRONTEND=noninteractive apt-get install -y" \
                "--no-install-recommends $*"
            ;;
        rhel) echo "sudo dnf install -y $*" ;;
        suse) echo "sudo zypper --non-interactive install $*" ;;
        arch) echo "sudo pacman -S --needed --noconfirm $*" ;;
        *) die "famille inconnue : ${fam}" ;;
    esac
}

# Les langues des traductions : une par po/<langue>.po. Le gabarit
# erplibre-home.pot n'en est pas une.
locale_langs() {
    local po
    for po in "${EXT_SRC}"/po/*.po; do
        [ -e "${po}" ] || continue
        basename "${po}" .po
    done
}

# Le .mo que msgfmt écrit pour une langue, là où l'extension le cherche.
mo_file() {
    echo "${EXT_SRC}/locale/$1/LC_MESSAGES/erplibre-home.mo"
}

not_implemented() {
    die "étape pas encore implémentée : $1"
}

# Chaque étape affiche, sous --dry-run, une ligne par effet qu'elle aurait,
# puis rend la main ; elle agit sinon.
step_packages() {
    if [ "${DRY_RUN}" = 1 ]; then
        if [ "${STREAM_DECK}" = 1 ] && needs_epel; then
            echo "packages: $(package_cmd "${FAMILY}" epel-release)"
        fi
        # shellcheck disable=SC2046
        echo "packages: $(package_cmd "${FAMILY}" $(level_packages "${FAMILY}"))"
        if [ "${WITH_EXTRAS}" = 1 ]; then
            # shellcheck disable=SC2046
            echo "packages: $(package_cmd "${FAMILY}" $(extras_for "${FAMILY}"))"
        fi
        return 0
    fi
    not_implemented "paquets système"
}

step_udev() {
    if [ "${DRY_RUN}" = 1 ]; then
        echo "write: ${UDEV_RULE}"
        return 0
    fi
    not_implemented "règle udev"
}

step_venv() {
    if [ "${DRY_RUN}" = 1 ]; then
        echo "venv: ${VENV}"
        return 0
    fi
    not_implemented "venv"
}

step_extension() {
    local lang
    if [ "${DRY_RUN}" = 1 ]; then
        echo "run: ${EXT_SRC}/tools/migrate_legacy.py"
        echo "write: ${EXT_LINK}"
        echo "write: ${EXT_SRC}/schemas/gschemas.compiled"
        for lang in $(locale_langs); do
            echo "run: msgfmt --check -o $(mo_file "${lang}") ${EXT_SRC}/po/${lang}.po"
            echo "write: $(mo_file "${lang}")"
        done
        return 0
    fi
    not_implemented "extension"
}

step_enable() {
    if [ "${DRY_RUN}" = 1 ]; then
        echo "gsettings: org.gnome.shell enabled-extensions +${UUID}"
        echo "gsettings: org.gnome.shell disable-user-extensions false"
        return 0
    fi
    not_implemented "activation"
}

step_summary() {
    not_implemented "résumé"
}

# --uninstall retire tout ; --uninstall --stream-deck ne retire que le
# niveau Stream Deck, la règle et le venv, et laisse l'extension active.
step_uninstall() {
    if [ "${DRY_RUN}" = 1 ]; then
        if [ "${STREAM_DECK}" = 0 ]; then
            echo "gsettings: org.gnome.shell enabled-extensions -${UUID}"
            echo "remove: ${EXT_LINK}"
        fi
        echo "remove: ${UDEV_RULE}"
        echo "remove: ${VENV}"
        return 0
    fi
    not_implemented "désinstallation"
}

# --uninstall et --extension-only ne lisent ni os-release ni la version de
# GNOME : ni l'un ni l'autre n'installe de paquet, et une désinstallation
# doit marcher sur un GNOME sorti de shell-version. La base passe toujours ;
# la règle udev et le venv n'arrivent qu'avec --stream-deck.
main() {
    parse_args "$@"
    check_not_root
    if [ "${UNINSTALL}" = 1 ]; then
        step_uninstall
        return 0
    fi
    if [ "${EXTENSION_ONLY}" = 0 ]; then
        detect_os
        detect_family
        check_gnome
        if [ "${DRY_RUN}" = 1 ]; then
            echo "family=${FAMILY}"
            echo "gnome=${GNOME_VERSION}"
        else
            log "famille ${FAMILY}, GNOME ${GNOME_VERSION}"
        fi
        step_packages
        if [ "${STREAM_DECK}" = 1 ]; then
            step_udev
            step_venv
        fi
    fi
    step_extension
    if [ "${EXTENSION_ONLY}" = 0 ] && [ "${NO_ENABLE}" = 0 ]; then
        step_enable
    fi
    if [ "${DRY_RUN}" = 0 ]; then
        step_summary
    fi
}

main "$@"
