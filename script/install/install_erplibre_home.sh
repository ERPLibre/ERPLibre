#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Installe ERPLibre Home sans Odoo, à deux niveaux. La base : l'extension
# GNOME liée au dépôt, ses schémas et ses traductions, puis activée ; ni
# accès au périphérique ni venv. --stream-deck ajoute le niveau Stream Deck
# par-dessus la base : paquets USB, règle udev, venv dédié .venv.streamdeck,
# les jeux, clonés quand ils manquent et amenés au dernier commit de main à
# chaque exécution, et le service systemd --user
# erplibre-home-streamdeck.service avec ses réglages. Le niveau Stream Deck inclut toujours la base ; la base
# s'installe seule.
#
#   ./script/install/install_erplibre_home.sh [--stream-deck] [--no-enable]
#       [--extension-only] [--with-extras] [--uninstall] [--dry-run] [--help]
#       [--deck-program=tiler|controller|none] [--autostart]
#       [--restart-after-game | --no-restart-after-game]
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
# shellcheck source=script/install/erplibre_home_settings.sh
. "${RACINE}/script/install/erplibre_home_settings.sh"

UUID="erplibre-home@technolibre.ca"
EXT_SRC="${RACINE}/script/gnome-extension/erplibre_home"
EXT_LINK="${HOME}/.local/share/gnome-shell/extensions/${UUID}"
METADATA="${EXT_SRC}/metadata.json"
UDEV_RULE="/etc/udev/rules.d/70-streamdeck.rules"
# Le nom stable que la règle udev donne au deck branché, et l'unité .device
# que systemd en tire : l'unité du service la nomme dans WantedBy=.
DECK_DEVICE_ALIAS="/sys/subsystem/erplibre/streamdeck"
DECK_DEVICE_UNIT="sys-subsystem-erplibre-streamdeck.device"
VENV="${RACINE}/.venv.streamdeck"
UNIT_FILE="$(deck_unit_file)"
SETTINGS_FILE="$(deck_settings_file)"
OS_RELEASE="${ERPLIBRE_HOME_OS_RELEASE:-/etc/os-release}"

STREAM_DECK=0
NO_ENABLE=0
EXTENSION_ONLY=0
WITH_EXTRAS=0
UNINSTALL=0
DRY_RUN=0
# Les options du service, au niveau Stream Deck seulement. DECK_PROGRAM et
# RESTART_AFTER_GAME restent vides quand l'option manque : la valeur déjà
# dans les réglages est alors gardée (voir service_setting). SERVICE_OPTIONS
# compte les options données, pour refuser leur emploi ailleurs.
DECK_PROGRAM=""
AUTOSTART=0
RESTART_AFTER_GAME=""
SERVICE_OPTIONS=0

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
    UNSUPPORTED_EXIT=1
    echo "UNSUPPORTED: $*" >&2
    exit 2
}

usage() {
    cat <<'USAGE'
Usage : ./script/install/install_erplibre_home.sh [options]

Installe ERPLibre Home sans Odoo : l'extension GNOME erplibre-home, ses
schémas et ses traductions, activée. --stream-deck y ajoute le Stream Deck.

  --stream-deck     ajoute le niveau Stream Deck : paquets USB, règle udev,
                    .venv.streamdeck, et les jeux de
                    script/stream_deck/games/ : clonés quand ils manquent,
                    amenés au dernier commit de main à chaque exécution
                    (une branche ou du travail local les retient) ; la
                    base s'installe aussi, au besoin
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
  --deck-program=tiler|controller|none
                    avec --stream-deck : le programme que lance le service
                    erplibre-home-streamdeck.service (défaut : tiler)
  --autostart       avec --stream-deck : active le service à l'ouverture de
                    session (défaut : non activé)
  --restart-after-game, --no-restart-after-game
                    avec --stream-deck : le service revient, ou non, après
                    un jeu (défaut : il revient)
                    Une option du service absente garde la valeur déjà
                    dans les réglages ; le défaut ne vaut que pour une clé
                    qui n'y est pas.
  --uninstall       retire tout : extension, règle udev, .venv.streamdeck,
                    service et réglages ; avec --stream-deck, tout sauf
                    l'extension, qui reste active ; les paquets système
                    et les jeux restent
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
            --deck-program=*)
                DECK_PROGRAM="${1#*=}"
                deck_program_path "${DECK_PROGRAM}" >/dev/null \
                    || die "--deck-program=${DECK_PROGRAM} : tiler," \
                        "controller ou none"
                SERVICE_OPTIONS=$((SERVICE_OPTIONS + 1))
                ;;
            --autostart)
                AUTOSTART=1
                SERVICE_OPTIONS=$((SERVICE_OPTIONS + 1))
                ;;
            --restart-after-game | --no-restart-after-game)
                set_restart_after_game "$1"
                SERVICE_OPTIONS=$((SERVICE_OPTIONS + 1))
                ;;
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
        && [ $((NO_ENABLE + WITH_EXTRAS + SERVICE_OPTIONS)) -gt 0 ]; then
        die "--uninstall ne se combine qu'avec --stream-deck et --dry-run"
    fi
    if [ "${SERVICE_OPTIONS}" -gt 0 ] && [ "${STREAM_DECK}" = 0 ]; then
        die "--deck-program, --autostart et --[no-]restart-after-game" \
            "demandent --stream-deck"
    fi
}

# --restart-after-game pose RESTART_AFTER_GAME=yes, --no-restart-after-game
# =no ; les deux ensemble se contredisent et sont une erreur d'usage.
set_restart_after_game() {
    local value=yes
    [ "$1" = --restart-after-game ] || value=no
    if [ -n "${RESTART_AFTER_GAME}" ] \
        && [ "${RESTART_AFTER_GAME}" != "${value}" ]; then
        die "--restart-after-game et --no-restart-after-game s'excluent"
    fi
    RESTART_AFTER_GAME="${value}"
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
# les traductions (msgfmt, de gettext), le python3 du système, qui lance la
# migration de l'ancienne identité de l'extension, et make. Un bureau neuf
# n'a pas toujours make, alors que les cibles erplibre_home_* et le message
# des indicateurs du deck sans venv le nomment.
packages_for() {
    case "$1" in
        debian) echo "libglib2.0-bin gettext python3 make" ;;
        rhel) echo "glib2 gettext python3 make" ;;
        suse) echo "glib2-tools gettext-tools python3 make" ;;
        arch) echo "glib2 gettext python make" ;;
        *) die "famille inconnue : $1" ;;
    esac
}

# Paquets du niveau Stream Deck, par famille : hidapi et libusb pour parler
# au deck, le module venv, et wmctrl pour keyboard_talk.py. opencv-python
# arrive en roue manylinux par pip ; elle lie libgthread, que openSUSE
# empaquette à part de glib2 (les autres familles l'ont avec glib2).
streamdeck_packages_for() {
    case "$1" in
        debian) echo "libhidapi-libusb0 libusb-1.0-0 python3-venv wmctrl" ;;
        rhel) echo "hidapi libusb1 python3 wmctrl" ;;
        suse) echo "libhidapi-libusb0 libusb-1_0-0 libgthread-2_0-0 python3 wmctrl" ;;
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
# sauté par le gestionnaire lui-même. « -o DPkg::Lock::Timeout=600 » fait
# attendre apt-get jusqu'à dix minutes le verrou de dpkg, qu'une mise à
# jour automatique tient souvent dans les premières minutes d'une session
# neuve, au lieu d'échouer aussitôt.
package_cmd() {
    local fam="$1"
    shift
    case "${fam}" in
        debian)
            echo "sudo apt-get -o DPkg::Lock::Timeout=600 update -qq &&" \
                "sudo env DEBIAN_FRONTEND=noninteractive apt-get" \
                "-o DPkg::Lock::Timeout=600 install -y" \
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

# ---------- Installation ----------

REQUIREMENTS="${RACINE}/script/stream_deck/requirements.txt"

# Ce que l'exécution a réellement changé, une ligne par effet, pour le bilan.
DONE=()

# EPEL au besoin (--stream-deck sur AlmaLinux et Rocky Linux), les paquets
# du niveau, puis chaque extra seul. Chaque ligne est celle de package_cmd,
# celle même que --dry-run affiche ; eval l'exécute, et chacun de ses mots
# est un littéral de packages_for, streamdeck_packages_for, extras_for ou
# « epel-release ». L'échec des paquets du niveau arrête l'installation
# (set -e) ; celui d'un extra n'est qu'un avertissement, et un extra absent
# du dépôt ne fait échouer que sa propre commande.
install_packages() {
    local level pkg
    if [ "${STREAM_DECK}" = 1 ] && needs_epel; then
        eval "$(package_cmd "${FAMILY}" epel-release)"
    fi
    level="$(level_packages "${FAMILY}")"
    # shellcheck disable=SC2086
    eval "$(package_cmd "${FAMILY}" ${level})"
    DONE+=("system packages: ${level}")
    [ "${WITH_EXTRAS}" = 1 ] || return 0
    for pkg in $(extras_for "${FAMILY}"); do
        if eval "$(package_cmd "${FAMILY}" "${pkg}")"; then
            DONE+=("optional package: ${pkg}")
        else
            log "WARNING: optional package ${pkg} not installed, skipped"
        fi
    done
}

# ---------- Règle udev ----------

# Le contenu exact de la règle. « uaccess » donne l'accès à l'utilisateur
# assis devant le poste sur toutes les familles, là où le groupe plugdev
# n'existe que sur Debian et Ubuntu. Le préfixe 70- passe avant
# 73-seat-late.rules, qui applique uaccess.
# La troisième ligne fait du deck branché l'unité DECK_DEVICE_UNIT dans
# chaque gestionnaire systemd --user (tag « systemd » et alias). L'unité du
# service la nomme dans WantedBy= : « enable » démarre alors le service au
# branchement comme à l'ouverture de session, et « disable » coupe les deux.
# La ligne ne vise que le périphérique entier (usb_device), pas ses
# interfaces ni son hidraw. Un service déjà actif n'est pas relancé ; hors
# de la session graphique, --check saute le démarrage.
udev_rule_content() {
    printf '%s\n' \
        'SUBSYSTEM=="usb", ATTRS{idVendor}=="0fd9", TAG+="uaccess"' \
        'KERNEL=="hidraw*", ATTRS{idVendor}=="0fd9", TAG+="uaccess"'
    printf '%s, %s, %s\n' \
        'SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device"' \
        'ATTR{idVendor}=="0fd9", TAG+="systemd"' \
        "ENV{SYSTEMD_ALIAS}=\"${DECK_DEVICE_ALIAS}\""
}

# Écrit la règle seulement si le fichier en place diffère (cmp), et ne
# recharge udev que dans ce cas : une seconde exécution ne touche ni au
# fichier ni à son mtime.
write_udev_rule() {
    if cmp -s <(udev_rule_content) "${UDEV_RULE}"; then
        log "udev rule already in place: ${UDEV_RULE}"
        return 0
    fi
    udev_rule_content | sudo tee "${UDEV_RULE}" >/dev/null
    sudo udevadm control --reload-rules
    sudo udevadm trigger
    DONE+=("udev rule: ${UDEV_RULE}")
}

# ---------- venv ----------

# Crée le venv avec le python3 du système s'il manque, puis y installe les
# dépendances du deck et, quand les jeux sont là, les leurs : leur dépôt les
# liste dans son requirements.txt. Celles des jeux passent par un second
# appel, dont l'échec est dit au bilan sans arrêter l'installation : le
# programme du deck et le service n'en dépendent pas. pip ne réinstalle pas
# ce qui est déjà satisfait : le venv existant garde son contenu.
make_venv() {
    if [ ! -x "${VENV}/bin/python" ]; then
        python3 -m venv "${VENV}"
        DONE+=("venv created: ${VENV}")
    fi
    "${VENV}/bin/python" -m pip install --quiet --disable-pip-version-check \
        -r "${REQUIREMENTS}"
    if [ -f "${GAMES_DIR}/requirements.txt" ] \
        && ! "${VENV}/bin/python" -m pip install --quiet \
            --disable-pip-version-check -r "${GAMES_DIR}/requirements.txt"; then
        DONE+=("games requirements NOT installed: ${GAMES_DIR}/requirements.txt")
    fi
}

# ---------- Jeux ----------

# Les jeux sont un dépôt à part, que Google Repo clone dans un checkout qu'il
# gère. Un checkout cloné par git ne les a pas : le niveau Stream Deck les
# clone alors lui-même, à la révision que le manifeste nomme : une branche,
# que chaque installation suit, une étiquette ou un commit.
GAMES_DIR="${RACINE}/${DECK_GAMES_DIR}"
GAMES_MANIFEST="${RACINE}/manifest/git_manifest_streamdeck_game.xml"

# Rend « <url> <révision> » du projet du manifeste dont le path est celui des
# jeux ; l'URL est le fetch de son remote suivi de son name. La révision ne
# se lit que là, pour que l'installateur et repo sync clonent la même.
games_source() {
    python3 - "${GAMES_MANIFEST}" "${DECK_GAMES_DIR}" <<'PY'
import sys
import xml.etree.ElementTree as ET

manifeste, chemin = sys.argv[1:]
racine = ET.parse(manifeste).getroot()
remotes = {r.get("name"): r.get("fetch") for r in racine.iter("remote")}
for projet in racine.iter("project"):
    if projet.get("path") == chemin:
        fetch = remotes[projet.get("remote")].rstrip("/")
        print("%s/%s %s" % (fetch, projet.get("name"), projet.get("revision")))
        break
else:
    sys.exit("no project at %s in %s" % (chemin, manifeste))
PY
}

# Les entrées de games/ autres que save/ et __pycache__/, séparées par une
# espace. save/ et __pycache__/ sont les fichiers ignorés qui restent dans
# games/ quand la mise à jour d'ERPLibre qui a cessé de suivre les jeux en
# retire les fichiers ; ils ne comptent que s'ils sont de vrais répertoires.
# Toute autre entrée compte, liens cassés et noms à points compris. Un
# GAMES_DIR qui n'est pas un répertoire est lui-même nommé.
games_strays() {
    local nom
    if [ ! -d "${GAMES_DIR}" ] || [ -L "${GAMES_DIR}" ]; then
        printf '%s ' "${GAMES_DIR}"
        return 0
    fi
    while IFS= read -r -d '' nom; do
        case "${nom}" in
            save | __pycache__)
                if [ -d "${GAMES_DIR}/${nom}" ] \
                    && [ ! -L "${GAMES_DIR}/${nom}" ]; then
                    continue
                fi
                ;;
        esac
        printf '%s ' "${nom}"
    done < <(find "${GAMES_DIR}" -mindepth 1 -maxdepth 1 -printf '%f\0')
}

# Sort en 0 quand les jeux sont à cloner : leur répertoire manque, ou ne
# garde que save/ et __pycache__/. Tout autre contenu est un clone, de ce
# script ou de repo, ou un travail en cours, et reste en place.
games_need_clone() {
    [ -e "${GAMES_DIR}" ] || [ -L "${GAMES_DIR}" ] || return 0
    [ -z "$(games_strays)" ]
}

# Rend, vide quand games/ porte les jeux, la raison pour laquelle un games/
# gardé ne les porte pas : games_cli.py manque, et les entrées qui ont
# empêché le clone sont nommées. Sans elle, l'installation réussirait sans
# jeux, et chaque point d'entrée renverrait à cette même installation.
games_kept_without_games() {
    [ -f "${GAMES_DIR}/games_cli.py" ] && return 0
    echo "no games_cli.py; move away $(games_strays)then run again"
}

# Clone les jeux quand games_need_clone le demande. Le clone se fait dans un
# répertoire voisin, renommé une fois la révision extraite : un échec ne
# laisse pas un games/ à moitié rempli. Les sauvegardes d'un games/ qui n'en
# gardait que des restes passent dans le clone avant qu'il le remplace.
clone_games() {
    local origine url revision partiel raison
    if ! games_need_clone; then
        raison="$(games_kept_without_games)"
        if [ -n "${raison}" ]; then
            DONE+=("games NOT installed, ${GAMES_DIR} kept: ${raison}")
        else
            update_games
        fi
        return 0
    fi
    command -v git >/dev/null \
        || die "git est requis pour cloner les jeux : installez le paquet git"
    origine="$(games_source)" \
        || die "révision des jeux illisible dans ${GAMES_MANIFEST}"
    url="${origine% *}"
    revision="${origine#* }"
    partiel="$(mktemp -d "${GAMES_DIR}.XXXXXX")"
    # HEAD détaché, même sur une branche, et sans la branche locale que
    # git clone crée : update_games et streamdeck_games_to_repo.sh prennent
    # une branche locale pour un travail en cours. refs/erplibre/installed
    # marque le commit installé : un main réécrit en amont ne le fait pas
    # passer pour un commit local.
    # mktemp crée le répertoire en 0700 ; le clone prend le mode qu'un
    # git clone ou repo sync lui donnerait sous le même umask.
    chmod "$(printf '%o' "$((0777 & ~$(umask)))")" "${partiel}"
    if git clone --quiet --no-checkout "${url}" "${partiel}" \
        && git -C "${partiel}" -c advice.detachedHead=false \
            checkout --quiet --detach "$(games_ref "${revision}")" \
        && games_mark_installed "${partiel}"; then
        if [ -d "${GAMES_DIR}/save" ]; then
            mkdir -p "${partiel}/save"
            cp -a "${GAMES_DIR}/save/." "${partiel}/save/"
        fi
        rm -rf "${GAMES_DIR}"
        mv "${partiel}" "${GAMES_DIR}"
        DONE+=("games cloned: ${GAMES_DIR} (${revision})")
    else
        rm -rf "${partiel}"
        die "clone des jeux impossible : ${url} ${revision}"
    fi
}

# Sort en 0 quand la révision du manifeste est une branche : refs/heads/<x>,
# ou un nom nu qui n'est pas un commit, comme repo les lit. Les étiquettes
# s'écrivent refs/tags/<x>.
games_is_branch() {
    case "${1}" in
        refs/tags/*) return 1 ;;
        refs/heads/*) return 0 ;;
    esac
    ! [[ "${1}" =~ ^[0-9a-f]{40}$ ]]
}

# La référence du clone ordinaire qui porte la révision du manifeste : celle
# du remote pour une branche, qu'un fetch avance, la révision elle-même
# sinon.
games_ref() {
    if games_is_branch "${1}"; then
        echo "refs/remotes/origin/${1#refs/heads/}"
    else
        echo "${1}"
    fi
}

# Le commit de la révision du manifeste dans le clone ordinaire des jeux,
# vide quand le clone ne la connaît pas (encore).
games_pinned_commit() {
    git -C "${GAMES_DIR}" rev-parse -q --verify \
        "$(games_ref "${1}")^{commit}" 2>/dev/null || true
}

# Retire les branches locales du clone `$1`, détaché, et marque son HEAD
# dans refs/erplibre/installed : games_held_back et
# streamdeck_games_to_repo.sh ne comptent pas ce commit comme local.
games_mark_installed() {
    local ref
    git -C "${1}" for-each-ref --format='%(refname)' refs/heads/ \
        | while IFS= read -r ref; do
            git -C "${1}" update-ref -d "${ref}"
        done
    git -C "${1}" update-ref refs/erplibre/installed HEAD
}

# Sort en 0 quand games/ est un clone ordinaire, celui que clone_games pose :
# un .git répertoire. Celui de repo est un lien, ou, dans son ancienne
# disposition, un répertoire dont objects/ est un lien ; il suit repo sync.
games_plain_clone() {
    [ -d "${GAMES_DIR}/.git" ] && [ ! -L "${GAMES_DIR}/.git" ] \
        && [ ! -L "${GAMES_DIR}/.git/objects" ]
}

# Sort en 0 quand le clone ordinaire des jeux ne doit pas bouger : HEAD sur
# une branche, une modification ou un fichier non suivi, ou un commit que ni
# ses remotes, ni une étiquette, ni refs/erplibre/installed n'atteignent.
# clone_games le laisse en HEAD détaché sans rien de tel.
games_held_back() {
    git -C "${GAMES_DIR}" symbolic-ref -q HEAD >/dev/null \
        || [ -n "$(git -C "${GAMES_DIR}" status --porcelain --untracked-files=normal)" ] \
        || [ -n "$(git -C "${GAMES_DIR}" rev-list HEAD --not --remotes --tags \
            --glob='refs/erplibre/*')" ]
}

# Amène le clone ordinaire des jeux à la révision du manifeste, sauf quand
# games_held_back le retient : le bilan le dit alors. Une branche se
# rafraîchit à chaque appel ; une étiquette ou un commit déjà connus ne
# demandent pas le réseau. Un fetch qui échoue laisse le clone où il est.
update_games() {
    local origine revision voulu=""
    games_plain_clone || return 0
    origine="$(games_source)" \
        || die "révision des jeux illisible dans ${GAMES_MANIFEST}"
    revision="${origine#* }"
    if ! games_is_branch "${revision}"; then
        voulu="$(games_pinned_commit "${revision}")"
    fi
    if [ -z "${voulu}" ]; then
        if ! git -C "${GAMES_DIR}" fetch --quiet --tags origin 2>/dev/null; then
            DONE+=("games NOT updated to ${revision}: fetch from origin failed")
            return 0
        fi
        voulu="$(games_pinned_commit "${revision}")"
    fi
    if [ -z "${voulu}" ]; then
        DONE+=("games NOT updated to ${revision}: unknown to ${GAMES_DIR}")
        return 0
    fi
    [ "$(git -C "${GAMES_DIR}" rev-parse HEAD)" = "${voulu}" ] && return 0
    if games_held_back; then
        DONE+=("games NOT updated to ${revision}: ${GAMES_DIR} holds a branch or local work")
        return 0
    fi
    git -C "${GAMES_DIR}" -c advice.detachedHead=false checkout --quiet \
        --detach "${voulu}"
    games_mark_installed "${GAMES_DIR}"
    DONE+=("games updated: ${GAMES_DIR} (${revision})")
}

# ---------- Service du deck ----------

# Ce que le bilan demande de lancer après la prochaine connexion : les
# commandes systemctl --user qui n'ont pas pu passer faute de gestionnaire
# de l'utilisateur joignable (une installation par ssh sans session).
SERVICE_HINTS=()

# systemd refuse un chemin d'exécutable qui porte une apostrophe, un
# guillemet, une barre oblique inverse ou un caractère de contrôle, même
# cité : l'unité ne se chargerait pas. Le niveau Stream Deck s'arrête donc
# avant de rien installer, en nommant le chemin. Une espace et « % » passent.
check_checkout_path() {
    case "${RACINE}" in
        *\'* | *\"* | *\\*)
            die "${RACINE} : systemd refuse ' \" et \\ dans le chemin du" \
                "service ; déplacer le dépôt"
            ;;
    esac
    if [[ "${RACINE}" == *[[:cntrl:]]* ]]; then
        die "${RACINE} : caractère de contrôle refusé par systemd"
    fi
}

# Le texte de l'unité, pour le dépôt RACINE. Les chemins s'écrivent entiers :
# entre guillemets dans les lignes Exec*, où une espace séparerait sinon les
# arguments, et « % » doublé partout, sans quoi systemd le lit comme un
# spécificateur. « $ » reste tel quel : systemd ne développe les variables
# que dans les arguments d'une ligne Exec*, et le chemin n'y est jamais que
# l'exécutable ou WorkingDirectory, où un « $$ » resterait doublé.
#
# Ce qui borne les redémarrages (Restart=on-failure) :
# - RestartPreventExitStatus=2 3 : le programme sort en 2 quand un autre
#   tient le verrou du deck, en 3 quand le tiler ne trouve aucun deck à
#   écran ; relancer n'y change rien (deck_lock.BUSY_EXIT, NO_DECK_EXIT) ;
# - StartLimitBurst=5 en 60 s : tout autre échec persistant finit en
#   « failed », que la diagnostic signale, au lieu d'un processus toutes les
#   RestartSec pour la session entière ; le défaut de systemd (5 en 10 s)
#   n'est jamais atteint avec RestartSec=3.
# SuccessExitStatus=143 : sur SIGTERM (systemctl stop), le programme remet
# le deck à zéro et sort en 128 + 15 (deck_lock.exit_on_sigterm) ; sans
# cette ligne, l'arrêt laisserait l'unité « failed ». TimeoutStopSec=10 :
# un fil non démon (animation, webcam du contrôleur) retient SystemExit, et
# l'arrêt finit alors en SIGKILL au bout de 10 s au lieu des 90 s par
# défaut, que la passation attendrait avant le jeu. PYTHONUNBUFFERED : la
# sortie va au journal ligne par ligne, et non par blocs à la sortie.
unit_content() {
    local dir entry
    dir="${RACINE//%/%%}"
    entry="\"${dir}/script/install/erplibre_home_deck.sh\""
    printf '%s\n' \
        "[Unit]" \
        "Description=ERPLibre Home Stream Deck program" \
        "PartOf=graphical-session.target" \
        "After=graphical-session.target" \
        "StartLimitIntervalSec=60" \
        "StartLimitBurst=5" \
        "" \
        "[Service]" \
        "Type=simple" \
        "WorkingDirectory=${dir}" \
        "Environment=PYTHONUNBUFFERED=1" \
        "ExecCondition=${entry} --check" \
        "ExecStart=${entry}" \
        "Restart=on-failure" \
        "RestartSec=3" \
        "RestartPreventExitStatus=2 3" \
        "SuccessExitStatus=143" \
        "TimeoutStopSec=10" \
        "" \
        "[Install]" \
        "WantedBy=graphical-session.target ${DECK_DEVICE_UNIT}"
}

# settings_content FICHIER CLÉ=valeur… rend les lignes de FICHIER (rien
# s'il manque), chaque ligne « CLÉ=… » d'une clé donnée remplacée sur place,
# puis les clés données qui n'y étaient pas. Les autres lignes restent
# telles quelles, dans leur ordre. Lu octet par octet (LC_ALL=C local),
# comme deck_setting : un octet hors UTF-8 ne mange pas le saut de ligne.
settings_content() {
    local LC_ALL=C
    local file="$1" line pair seen=" "
    shift
    if [ -f "${file}" ]; then
        while IFS= read -r line || [ -n "${line}" ]; do
            for pair in "$@"; do
                case "${line}" in
                    "${pair%%=*}="*)
                        line="${pair}"
                        seen="${seen}${pair%%=*} "
                        ;;
                esac
            done
            printf '%s\n' "${line}"
        done <"${file}"
    fi
    for pair in "$@"; do
        case "${seen}" in
            *" ${pair%%=*} "*) ;;
            *) printf '%s\n' "${pair}" ;;
        esac
    done
}

# systemctl --user, sur le bus que choisit on_session_bus.
user_systemctl() {
    on_session_bus systemctl --user "$@"
}

# service_setting CLÉ DONNÉE DÉFAUT rend la valeur qu'une installation écrit
# pour CLÉ : DONNÉE quand l'option a été donnée (non vide), sinon la valeur
# déjà dans les réglages, sinon DÉFAUT quand le fichier ou la clé manque, ou
# que sa valeur est vide. Une option absente ne défait donc pas un choix
# antérieur, fait par une installation ou par le menu Stream Deck de TODO.
service_setting() {
    local key="$1" given="$2" default="$3" current
    if [ -n "${given}" ]; then
        echo "${given}"
        return 0
    fi
    current="$(deck_setting "${key}" "")"
    echo "${current:-${default}}"
}

# Les deux lignes « CLÉ=valeur » que l'installation pose, selon
# service_setting.
service_pairs() {
    local program restart
    program="$(service_setting DECK_PROGRAM "${DECK_PROGRAM}" tiler)"
    restart="$(service_setting RESTART_AFTER_GAME "${RESTART_AFTER_GAME}" yes)"
    printf '%s\n' "DECK_PROGRAM=${program}" "RESTART_AFTER_GAME=${restart}"
}

# install_file FICHIER remplace FICHIER par l'entrée standard, par un
# fichier temporaire renommé, seulement quand le contenu diffère : une
# seconde exécution identique n'y touche pas. Rend 1 quand le contenu était
# déjà en place. FICHIER garde son mode, 0644 quand il est neuf. Un
# répertoire ou une écriture qui échoue arrête l'installation en nommant le
# chemin, sans laisser le fichier temporaire : l'appelant teste le code de
# retour, et bash suspend alors set -e dans toute la fonction.
install_file() {
    local file="$1" dir tmp mode=0644
    dir="$(dirname "${file}")"
    mkdir -p "${dir}" || die "${dir} : répertoire non créé"
    tmp="$(mktemp "${file}.XXXXXX")" || die "${dir} : écriture refusée"
    if ! cat >"${tmp}"; then
        rm -f "${tmp}"
        die "${file} : écriture interrompue"
    fi
    if cmp -s "${tmp}" "${file}"; then
        rm -f "${tmp}"
        return 1
    fi
    [ ! -e "${file}" ] || mode="$(stat -c %a "${file}")"
    if ! chmod "${mode}" "${tmp}" || ! mv -f "${tmp}" "${file}"; then
        rm -f "${tmp}"
        die "${file} : non remplacé"
    fi
}

# Écrit les réglages que résout service_pairs, quand ils changent.
write_settings() {
    local pairs
    mapfile -t pairs < <(service_pairs)
    if install_file "${SETTINGS_FILE}" \
        < <(settings_content "${SETTINGS_FILE}" "${pairs[@]}"); then
        DONE+=("settings: ${SETTINGS_FILE}")
    else
        log "settings already in place: ${SETTINGS_FILE}"
    fi
}

# Écrit l'unité seulement quand elle diffère ; vrai quand elle a été écrite.
write_unit() {
    if install_file "${UNIT_FILE}" < <(unit_content); then
        DONE+=("unit: ${UNIT_FILE}")
    else
        log "unit already in place: ${UNIT_FILE}"
        return 1
    fi
}

# Les réglages, l'unité, daemon-reload, et enable avec --autostart
# seulement. Jamais start : le programme demande l'extension chargée, ce
# qu'une installation neuve n'a qu'à la prochaine connexion. daemon-reload
# passe même quand l'unité n'a pas changé : celui qu'une installation
# précédente n'a pas pu faire est ainsi refait. Une unité déjà en place,
# réécrite et activée est réactivée (reenable) : enable ne pose les liens
# que de la section [Install] qu'il lit, et un WantedBy= ajouté resterait
# sans lien. Un systemctl qui échoue n'arrête rien, et sa commande va au
# bilan.
install_service() {
    local changed=1 existed=0
    [ ! -e "${UNIT_FILE}" ] || existed=1
    write_settings
    write_unit || changed=0
    if user_systemctl daemon-reload; then
        [ "${changed}" = 0 ] || DONE+=("systemctl --user daemon-reload")
    else
        SERVICE_HINTS+=("systemctl --user daemon-reload")
    fi
    if [ "${changed}${existed}" = 11 ] \
        && user_systemctl is-enabled --quiet "${DECK_UNIT_NAME}" 2>/dev/null; then
        if user_systemctl reenable "${DECK_UNIT_NAME}"; then
            DONE+=("systemctl --user reenable ${DECK_UNIT_NAME}")
        else
            SERVICE_HINTS+=("systemctl --user reenable ${DECK_UNIT_NAME}")
        fi
    fi
    [ "${AUTOSTART}" = 1 ] || return 0
    if user_systemctl is-enabled --quiet "${DECK_UNIT_NAME}" 2>/dev/null; then
        log "unit already enabled: ${DECK_UNIT_NAME}"
    elif user_systemctl enable "${DECK_UNIT_NAME}"; then
        DONE+=("systemctl --user enable ${DECK_UNIT_NAME}")
    else
        SERVICE_HINTS+=("systemctl --user enable ${DECK_UNIT_NAME}")
    fi
}

# Arrête, désactive et retire l'unité, recharge systemd, puis retire les
# réglages. Les liens de graphical-session.target.wants et du .wants du deck
# partent aussi quand disable n'a pas pu les retirer. Ce qui manque est
# sauté : une seconde exécution n'appelle pas systemctl. Un systemctl qui
# échoue n'arrête rien.
uninstall_service() {
    local wants dir
    dir="$(dirname "${UNIT_FILE}")"
    if [ -e "${UNIT_FILE}" ]; then
        user_systemctl stop "${DECK_UNIT_NAME}" \
            || log "WARNING: systemctl --user stop ${DECK_UNIT_NAME} failed"
        user_systemctl disable "${DECK_UNIT_NAME}" \
            || log "WARNING: systemctl --user disable ${DECK_UNIT_NAME} failed"
        rm -f "${UNIT_FILE}"
        DONE+=("removed ${UNIT_FILE}")
        user_systemctl daemon-reload \
            || log "WARNING: systemctl --user daemon-reload failed"
    fi
    for wants in "${dir}/graphical-session.target.wants" \
        "${dir}/${DECK_DEVICE_UNIT}.wants"; do
        wants="${wants}/${DECK_UNIT_NAME}"
        if [ -L "${wants}" ]; then
            rm -f "${wants}"
            DONE+=("removed ${wants}")
        fi
    done
    if [ -e "${SETTINGS_FILE}" ]; then
        rm -f "${SETTINGS_FILE}"
        DONE+=("removed ${SETTINGS_FILE}")
    fi
}

# ---------- Extension GNOME ----------

# Pose le lien vers le checkout, sauf s'il pointe déjà au bon endroit. Un
# répertoire ou un fichier ordinaire à cette place (une copie posée à la
# main, une extension installée depuis une archive) n'est jamais écrasé :
# l'installation s'arrête en le nommant. « ln -sfn » sur un répertoire
# créerait d'ailleurs le lien DEDANS.
#
# La migration de l'ancienne identité passe d'abord, à chaque exécution :
# elle libère l'ancien UUID, ses réglages et ses données, et reprend au
# passage suivant ce qu'une session absente a laissé. Elle rend toujours
# 0 ; le « || » couvre un bit d'exécution perdu ou un python3 absent, que
# « set -e » changerait sinon en arrêt de l'installation.
link_extension() {
    "${EXT_SRC}/tools/migrate_legacy.py" ||
        log "legacy migration did not run; the install goes on"
    mkdir -p "$(dirname "${EXT_LINK}")"
    if [ "$(readlink "${EXT_LINK}" 2>/dev/null || true)" = "${EXT_SRC}" ]; then
        log "extension link already in place: ${EXT_LINK}"
        return 0
    fi
    if [ -e "${EXT_LINK}" ] && [ ! -L "${EXT_LINK}" ]; then
        die "${EXT_LINK} exists and is not a symlink; move it away and rerun"
    fi
    ln -sfn "${EXT_SRC}" "${EXT_LINK}"
    DONE+=("extension link: ${EXT_LINK} -> ${EXT_SRC}")
}

# --strict refuse un schéma douteux ; son échec arrête l'installation, faute
# de quoi l'extension se chargerait sans réglages.
compile_schemas() {
    glib-compile-schemas --strict "${EXT_SRC}/schemas/"
}

# Le paquet qui porte msgfmt dans la famille. Sous --extension-only, la
# famille n'est pas lue : le message nomme alors les deux noms.
gettext_package() {
    case "$1" in
        suse) echo "gettext-tools" ;;
        debian | rhel | arch) echo "gettext" ;;
        *) echo "gettext (gettext-tools on openSUSE)" ;;
    esac
}

# Un .mo par po/<langue>.po, là où l'extension le cherche, par « msgfmt
# --check » : ni polib ni venv, msgfmt vient du paquet gettext de la base.
# --check refuse un format ou un en-tête faux ; ce refus, comme un msgfmt
# absent, arrête l'installation, faute de quoi l'extension se chargerait
# sans traductions.
compile_locales() {
    local lang mo
    command -v msgfmt >/dev/null 2>&1 \
        || die "msgfmt is missing; install $(gettext_package "${FAMILY}")"
    for lang in $(locale_langs); do
        mo="$(mo_file "${lang}")"
        mkdir -p "$(dirname "${mo}")"
        msgfmt --check -o "${mo}" "${EXT_SRC}/po/${lang}.po"
    done
}

# Lance une commande sur le bus de la session ouverte quand il y en a une :
# celui de l'environnement, sinon le socket du compte (ssh dans une machine
# dont la session graphique tourne). Le dconf-service de cette session garde
# la base qu'il a lue et la réécrit en entier : une écriture faite à côté,
# sous un dbus-run-session, lui échappe et peut être recouverte. Sans
# aucune session (ssh, VM fraîche), dbus-run-session lance un dconf-service
# à part qui écrit le profil de l'utilisateur, que la prochaine session lit.
on_session_bus() {
    local bus
    if bus="$(shell_bus_address)"; then
        DBUS_SESSION_BUS_ADDRESS="${bus}" "$@"
    else
        dbus-run-session -- "$@"
    fi
}

# gsettings, sur le bus que choisit on_session_bus.
gsettings_bus() {
    on_session_bus gsettings "$@"
}

# uuid_list_edit has <liste> <uuid> rend « yes » ou « no » ;
# uuid_list_edit remove <liste> <uuid> rend la liste GVariant « as » sans
# <uuid>, ou l'entrée telle quelle quand il n'y a rien à retirer :
# l'appelant compare pour savoir s'il doit écrire. La liste se lit par
# tools/gsettings_strv.py, le lecteur que partagent les outils de
# l'extension, qui accepte les deux formes que gsettings affiche,
# « @as [] » et « ['a', 'b'] ». Une liste illisible sort en erreur.
uuid_list_edit() {
    python3 -c '
import sys
sys.path.insert(0, sys.argv[1])
from gsettings_strv import format_strv, parse_strv
mode, current, uuid = sys.argv[2:5]
items = parse_strv(current)
if mode == "has":
    print("yes" if uuid in items else "no")
elif uuid in items:
    print(format_strv([item for item in items if item != uuid]))
else:
    print(current.strip())
' "${EXT_SRC}/tools" "$@"
}

# L'adresse d'un bus de session joignable : celle de l'environnement, sinon
# le socket du compte sous /run/user. Rien, et un code 1, quand aucun
# n'existe.
shell_bus_address() {
    if [ -n "${DBUS_SESSION_BUS_ADDRESS:-}" ]; then
        echo "${DBUS_SESSION_BUS_ADDRESS}"
        return 0
    fi
    local sock
    sock="/run/user/$(id -u)/bus"
    [ -S "${sock}" ] || return 1
    echo "unix:path=${sock}"
}

# Active l'extension pour le compte. Les deux listes s'écrivent par
# tools/enable_next_login.py, l'aide de la cible make
# erplibre_home_enable_extension, sur le bus que choisit on_session_bus :
# l'UUID retiré de disabled-extensions, où l'application Extensions le range
# quand on l'y éteint et qui l'emporte sur enabled-extensions, puis ajouté à
# enabled-extensions sans doublon. make et l'installateur activent donc par
# le même code. disable-user-extensions passe ensuite à false. Les trois
# clés sont relues ; une écriture qui n'a pas pris arrête l'installation.
# gnome-extensions enable ne sert que si GNOME Shell tourne déjà sur un bus
# joignable, et son échec n'arrête rien : la prochaine session charge
# l'extension depuis les clés.
enable_extension() {
    local enabled disabled bus
    enabled="$(gsettings_bus get org.gnome.shell enabled-extensions)"
    disabled="$(gsettings_bus get org.gnome.shell disabled-extensions)"
    on_session_bus "${EXT_SRC}/tools/enable_next_login.py" "${UUID}" >/dev/null \
        || die "enabled-extensions not written for ${UUID}"
    if [ "$(uuid_list_edit has "${disabled}" "${UUID}")" = yes ]; then
        DONE+=("disabled-extensions -= ${UUID}")
    fi
    if [ "$(uuid_list_edit has "${enabled}" "${UUID}")" = no ]; then
        DONE+=("enabled-extensions += ${UUID}")
    fi
    if [ "$(gsettings_bus get org.gnome.shell disable-user-extensions)" != "false" ]; then
        gsettings_bus set org.gnome.shell disable-user-extensions false
        DONE+=("disable-user-extensions = false")
    fi
    enabled="$(gsettings_bus get org.gnome.shell enabled-extensions)"
    if [ "$(uuid_list_edit has "${enabled}" "${UUID}")" != yes ]; then
        die "enabled-extensions does not hold ${UUID} after writing it"
    fi
    disabled="$(gsettings_bus get org.gnome.shell disabled-extensions)"
    if [ "$(uuid_list_edit has "${disabled}" "${UUID}")" != no ]; then
        die "disabled-extensions still holds ${UUID} after removing it"
    fi
    if [ "$(gsettings_bus get org.gnome.shell disable-user-extensions)" != "false" ]; then
        die "disable-user-extensions is still true after writing it"
    fi
    bus="$(shell_bus_address || true)"
    if [ -n "${bus}" ] && DBUS_SESSION_BUS_ADDRESS="${bus}" gdbus call --session \
        --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus \
        --method org.freedesktop.DBus.NameHasOwner org.gnome.Shell \
        2>/dev/null | grep -q true; then
        DBUS_SESSION_BUS_ADDRESS="${bus}" gnome-extensions enable "${UUID}" \
            || log "gnome-extensions enable failed; the next session loads the extension"
    fi
}

# ---------- Désinstallation ----------

# Retire le niveau Stream Deck : le service et ses réglages d'abord, pour que
# le programme ne tourne plus quand son venv part, puis la règle udev, la
# relecture des règles, et le venv. Ce qui manque déjà est sauté, si bien
# qu'une seconde exécution n'appelle ni sudo, ni udevadm, ni systemctl.
uninstall_streamdeck() {
    uninstall_service
    if [ -e "${UDEV_RULE}" ]; then
        sudo rm -f "${UDEV_RULE}"
        sudo udevadm control --reload-rules
        DONE+=("removed ${UDEV_RULE}")
    fi
    if [ -e "${VENV}" ]; then
        rm -rf "${VENV}"
        DONE+=("removed ${VENV}")
    fi
}

# Ce qui reste debout après une désinstallation qui a fait tout le reste ;
# step_uninstall le donne pour raison d'un échec, après le bilan.
UNINSTALL_ERROR=""

# Défait tout ce que l'installation pose : l'UUID d'enabled-extensions, le
# lien, puis le niveau Stream Deck, service compris. Jamais de paquet
# système : d'autres logiciels peuvent s'en servir. Un répertoire ordinaire
# à la place du lien n'a pas été posé par ce script et reste en place. Une
# liste enabled-extensions qui ne se lit ou ne s'écrit pas (gsettings
# absent, bus en panne) n'arrête pas le reste, mais pose UNINSTALL_ERROR :
# l'UUID peut y rester, et la désinstallation n'est pas complète.
uninstall() {
    local current wanted
    if current="$(gsettings_bus get org.gnome.shell enabled-extensions 2>/dev/null)" \
        && wanted="$(uuid_list_edit remove "${current}" "${UUID}" 2>/dev/null)"; then
        if [ "${wanted}" != "${current}" ]; then
            if gsettings_bus set org.gnome.shell enabled-extensions "${wanted}"; then
                DONE+=("enabled-extensions -= ${UUID}")
            else
                UNINSTALL_ERROR="enabled-extensions not written; ${UUID} may still be listed"
            fi
        fi
    else
        UNINSTALL_ERROR="enabled-extensions unreadable; ${UUID} may still be listed"
    fi
    if [ -L "${EXT_LINK}" ]; then
        rm -f "${EXT_LINK}"
        DONE+=("removed ${EXT_LINK}")
    elif [ -e "${EXT_LINK}" ]; then
        log "left in place, not a symlink: ${EXT_LINK}"
    fi
    uninstall_streamdeck
}

# ---------- Bilan ----------

summary() {
    local line
    if [ "${#DONE[@]}" -eq 0 ]; then
        log "nothing to change"
    else
        for line in "${DONE[@]}"; do
            log "${line}"
        done
    fi
    for line in "${SERVICE_HINTS[@]}"; do
        log "after the next login, run: ${line}"
    done
    if [ "${UNINSTALL}" = 0 ]; then
        log "log out and back in: GNOME Shell loads a new extension only at session start under Wayland"
    fi
}

# Chaque étape affiche, sous --dry-run, une ligne par effet qu'elle aurait,
# puis rend la main ; elle agit sinon.
step_packages() {
    local pkg
    if [ "${DRY_RUN}" = 1 ]; then
        if [ "${STREAM_DECK}" = 1 ] && needs_epel; then
            echo "packages: $(package_cmd "${FAMILY}" epel-release)"
        fi
        # shellcheck disable=SC2046
        echo "packages: $(package_cmd "${FAMILY}" $(level_packages "${FAMILY}"))"
        if [ "${WITH_EXTRAS}" = 1 ]; then
            for pkg in $(extras_for "${FAMILY}"); do
                echo "packages: $(package_cmd "${FAMILY}" "${pkg}")"
            done
        fi
        return 0
    fi
    install_packages
}

step_udev() {
    if [ "${DRY_RUN}" = 1 ]; then
        echo "write: ${UDEV_RULE}"
        return 0
    fi
    write_udev_rule
}

step_venv() {
    if [ "${DRY_RUN}" = 1 ]; then
        echo "venv: ${VENV}"
        return 0
    fi
    make_venv
}

# Sous --dry-run, « games: clone » quand les jeux sont à cloner, « games:
# keep » sinon, suivi de la raison quand le répertoire gardé n'a pas les
# jeux, ou, pour un clone ordinaire, de ce qu'en ferait l'installation : la
# mise à jour, ou le refus de games_held_back. Le dry-run ne va pas sur le
# réseau : une branche n'y est donc qu'annoncée, l'installation la
# rafraîchit.
step_games() {
    local origine raison revision
    if [ "${DRY_RUN}" = 1 ]; then
        if ! games_need_clone; then
            raison="$(games_kept_without_games)"
            if [ -z "${raison}" ] && games_plain_clone; then
                origine="$(games_source)" \
                    || die "révision des jeux illisible dans ${GAMES_MANIFEST}"
                revision="${origine#* }"
                if games_is_branch "${revision}" \
                    || [ "$(git -C "${GAMES_DIR}" rev-parse HEAD 2>/dev/null)" \
                        != "$(games_pinned_commit "${revision}")" ]; then
                    if games_is_branch "${revision}"; then
                        raison="follow ${revision}: fetched on install"
                        if games_held_back; then
                            raison="${raison}; a branch or local work keeps it"
                        fi
                    elif games_held_back; then
                        raison="not updated to ${revision}: a branch or local work"
                    else
                        raison="update to ${revision}"
                    fi
                fi
            fi
            echo "games: keep ${GAMES_DIR}${raison:+ (${raison})}"
        else
            origine="$(games_source)" \
                || die "révision des jeux illisible dans ${GAMES_MANIFEST}"
            echo "games: clone ${origine% *} at ${origine#* } into ${GAMES_DIR}"
        fi
        return 0
    fi
    clone_games
}

step_service() {
    if [ "${DRY_RUN}" = 1 ]; then
        echo "write: ${UNIT_FILE}"
        echo "write: ${SETTINGS_FILE}"
        service_pairs | sed 's/^/setting: /'
        echo "systemctl: --user daemon-reload"
        if [ "${AUTOSTART}" = 1 ]; then
            echo "systemctl: --user enable ${DECK_UNIT_NAME}"
        fi
        return 0
    fi
    install_service
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
    link_extension
    compile_schemas
    compile_locales
}

step_enable() {
    if [ "${DRY_RUN}" = 1 ]; then
        echo "gsettings: org.gnome.shell enabled-extensions +${UUID}"
        echo "gsettings: org.gnome.shell disable-user-extensions false"
        return 0
    fi
    enable_extension
}

step_summary() {
    summary
}

# --uninstall retire tout ; --uninstall --stream-deck ne retire que le
# niveau Stream Deck, le service, la règle et le venv, et laisse
# l'extension active.
# Le bilan dit ce qui est parti ; UNINSTALL_ERROR, posé par uninstall, fait
# ensuite sortir en 1.
step_uninstall() {
    if [ "${DRY_RUN}" = 1 ]; then
        if [ "${STREAM_DECK}" = 0 ]; then
            echo "gsettings: org.gnome.shell enabled-extensions -${UUID}"
            echo "remove: ${EXT_LINK}"
        fi
        echo "systemctl: --user stop ${DECK_UNIT_NAME}"
        echo "systemctl: --user disable ${DECK_UNIT_NAME}"
        echo "remove: ${UNIT_FILE}"
        echo "systemctl: --user daemon-reload"
        echo "remove: ${SETTINGS_FILE}"
        echo "remove: ${UDEV_RULE}"
        echo "remove: ${VENV}"
        return 0
    fi
    if [ "${STREAM_DECK}" = 1 ]; then
        uninstall_streamdeck
    else
        uninstall
    fi
    summary
    [ -z "${UNINSTALL_ERROR}" ] || die "${UNINSTALL_ERROR}"
}

# --uninstall et --extension-only ne lisent ni os-release ni la version de
# GNOME : ni l'un ni l'autre n'installe de paquet, et une désinstallation
# doit marcher sur un GNOME sorti de shell-version. La base passe toujours ;
# la règle udev, le venv, les jeux et le service n'arrivent qu'avec
# --stream-deck, dont le chemin du dépôt se vérifie avant tout le reste.
main() {
    parse_args "$@"
    check_not_root
    if [ "${STREAM_DECK}" = 1 ] && [ "${UNINSTALL}" = 0 ]; then
        check_checkout_path
    fi
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
            step_games
            step_venv
            step_service
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

# Sourcé avec ERPLIBRE_HOME_SOURCE_ONLY=1, le script définit ses fonctions et
# s'arrête là : les tests unitaires les appellent une à une, sans sudo.
#
# Les codes de sortie sont 0, 2 et 1, rien d'autre. Une commande appelée
# qui arrête le script sous set -e lui laisserait son propre code : 100
# pour apt-get, 104 pour zypper, 127 pour une commande absente, et 2 pour
# pip, msgfmt ou un gestionnaire de paquets, où TODO comme le test long
# liraient un système non supporté. Le piège EXIT ramène à 1 tout code non
# nul que unsupported n'a pas posé.
if [ "${ERPLIBRE_HOME_SOURCE_ONLY:-0}" != "1" ]; then
    trap 'rc=$?; if [ "${rc}" != 0 ] && [ "${UNSUPPORTED_EXIT:-0}" != 1 ]; then exit 1; fi' EXIT
    main "$@"
fi
