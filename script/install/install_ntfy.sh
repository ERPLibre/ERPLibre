#!/usr/bin/env bash
# Install NTFY self-hosted push notification server
# https://github.com/binwiederhier/ntfy
# Supports: Ubuntu 20.04+, Debian 11+, Arch Linux (and derivatives)
#
# Usage:
#   sudo bash install_ntfy.sh
#   sudo NTFY_PORT=8080 NTFY_BASE_URL=http://ntfy.exemple.org:8080 \
#        bash install_ntfy.sh
#
# Variables d'entree (toutes facultatives) :
#   NTFY_PORT            port http (8080), sur toutes les interfaces
#   NTFY_BASE_URL        URL publique (http://localhost:$NTFY_PORT)
#   NTFY_CERT_FILE, NTFY_KEY_FILE
#                        certificat et cle : ajoutent l'ecoute https
#   NTFY_HTTPS_PORT      port https quand un certificat est fourni (8443)
#   NTFY_PUBLIC=1        acces anonyme en lecture et ecriture (voir plus bas)
#   NTFY_ADMIN_USER      compte administrateur cree au besoin (erplibre)
#   NTFY_GARDER_CONFIG=1 garde une configuration en place sans controle
#                        d'acces
#   NTFY_NON_INTERACTIVE=1
#                        aucune question : ni assistant AUR, ni question de
#                        dpkg sur un fichier de configuration modifie. C'est
#                        le mode d'un lancement a distance, ou rien ne
#                        repond au terminal.
#
# Sortie lisible par un programme :
#   @@ADMIN_PASSWORD <mot de passe>
#                        seulement quand le compte administrateur vient
#                        d'etre cree ; affiche une fois, ecrit nulle part
#   @@ACTIVE ntfy <etat> derniere ligne : l'etat systemd du service
# Le code de sortie est non nul des que le service n'est pas « active ».
#
# Securite — les defauts de ce script, et pourquoi :
#
#   L'acces est REFUSE par defaut (auth-default-access: deny-all). Le defaut
#   de ntfy en l'absence de cette directive est un acces anonyme en lecture
#   ET en ecriture : quiconque apprend un nom de sujet lit tout ce qui y
#   transite, indefiniment. Or un nom de sujet finit toujours par etre tape
#   dans un ecran de configuration, colle dans un courriel, ou ecrit dans un
#   fichier. Un serveur de notifications transporte des donnees personnelles.
#
#   NTFY_PUBLIC=1 retablit l'ancien comportement, pour un usage ou tout est
#   volontairement public. C'est un choix, plus un oubli.
#
#   TLS s'active en fournissant un certificat :
#     sudo NTFY_CERT_FILE=/etc/ssl/ntfy.crt NTFY_KEY_FILE=/etc/ssl/ntfy.key \
#          NTFY_BASE_URL=https://ntfy.exemple.org bash install_ntfy.sh

set -e

NTFY_PORT="${NTFY_PORT:-8080}"
NTFY_BASE_URL="${NTFY_BASE_URL:-http://localhost:${NTFY_PORT}}"
INSTALL_DIR="/usr/local/bin"
CONFIG_DIR="/etc/ntfy"
CACHE_DIR="/var/cache/ntfy"
SYSTEMD_UNIT="/etc/systemd/system/ntfy.service"
# La base des comptes vit SOUS /var/lib et non sous /etc : le service tourne
# sous le compte « ntfy », et /etc/ntfy appartient a root. ntfy y creerait sa
# base au premier demarrage, n'y arriverait pas, et sortirait en erreur — un
# serveur qui refuse tout acces et ne demarre pas se lit comme une panne de
# reseau.
DATA_DIR="/var/lib/ntfy"
AUTH_FILE="${DATA_DIR}/user.db"
NTFY_PUBLIC="${NTFY_PUBLIC:-0}"
NTFY_CERT_FILE="${NTFY_CERT_FILE:-}"
NTFY_KEY_FILE="${NTFY_KEY_FILE:-}"
NTFY_HTTPS_PORT="${NTFY_HTTPS_PORT:-}"
NTFY_ADMIN_USER="${NTFY_ADMIN_USER:-erplibre}"
NTFY_NON_INTERACTIVE="${NTFY_NON_INTERACTIVE:-0}"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

log()  { echo "[NTFY] $*"; }
die()  { echo "[NTFY] ERROR: $*" >&2; exit 1; }

non_interactive() {
    [ "${NTFY_NON_INTERACTIVE:-0}" = "1" ]
}

check_root() {
    if [ "$EUID" -ne 0 ]; then
        die "This script must be run as root. Use: sudo bash $0"
    fi
}

detect_os() {
    if [ -f /etc/os-release ]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        OS="${ID}"
        OS_LIKE="${ID_LIKE:-}"
    else
        die "Cannot detect OS (no /etc/os-release)"
    fi
    log "Detected OS: ${OS}"
}

is_ubuntu_like() {
    case "$OS" in
        ubuntu|debian|linuxmint|pop|elementary|raspbian) return 0 ;;
        *) echo "$OS_LIKE" | grep -qE "debian|ubuntu" && return 0 || return 1 ;;
    esac
}

is_arch_like() {
    case "$OS" in
        arch|manjaro|endeavouros|artix|garuda) return 0 ;;
        *) echo "$OS_LIKE" | grep -q "arch" && return 0 || return 1 ;;
    esac
}

# ---------------------------------------------------------------------------
# Get latest ntfy version from GitHub
# ---------------------------------------------------------------------------

get_latest_version() {
    local ver
    ver=$(curl -fsSL \
        "https://api.github.com/repos/binwiederhier/ntfy/releases/latest" \
        2>/dev/null | grep '"tag_name"' | sed 's/.*"v\([^"]*\)".*/\1/' | head -1)
    if [ -z "$ver" ]; then
        # Fallback to a known stable version if GitHub API is unreachable
        ver="2.11.0"
        log "Warning: could not reach GitHub API, falling back to v${ver}"
    fi
    echo "$ver"
}

# ---------------------------------------------------------------------------
# Installation methods
# ---------------------------------------------------------------------------

install_deb() {
    local version="$1"
    local arch
    arch=$(dpkg --print-architecture)  # amd64, arm64, armhf, ...

    local deb_file="ntfy_${version}_linux_${arch}.deb"
    local url="https://github.com/binwiederhier/ntfy/releases/download/v${version}/${deb_file}"
    local tmp
    tmp=$(mktemp -d)

    log "Downloading ${deb_file}..."
    if ! curl -fsSL "$url" -o "${tmp}/${deb_file}"; then
        log "Warning: .deb not found for arch=${arch}, trying binary install..."
        rm -rf "$tmp"
        install_binary "$version"
        return
    fi

    log "Installing .deb package..."
    if non_interactive; then
        # Un fichier de configuration modifie sur place fait poser a dpkg une
        # question sur le terminal ; ces options gardent celui en place.
        DEBIAN_FRONTEND=noninteractive dpkg --force-confdef --force-confold \
            -i "${tmp}/${deb_file}" \
            || DEBIAN_FRONTEND=noninteractive apt-get install -f -y
    else
        dpkg -i "${tmp}/${deb_file}" || apt-get install -f -y
    fi
    rm -rf "$tmp"
}

install_binary() {
    local version="$1"
    local machine
    machine=$(uname -m)
    local arch_str="amd64"
    case "$machine" in
        aarch64|arm64) arch_str="arm64" ;;
        armv7l|armhf)  arch_str="armv7" ;;
    esac

    local tarball="ntfy_${version}_linux_${arch_str}.tar.gz"
    local url="https://github.com/binwiederhier/ntfy/releases/download/v${version}/${tarball}"
    local tmp
    tmp=$(mktemp -d)

    log "Downloading ${tarball}..."
    curl -fsSL "$url" -o "${tmp}/${tarball}" || \
        die "Failed to download ntfy from GitHub. Check your internet connection."
    tar -xzf "${tmp}/${tarball}" -C "$tmp"

    local binary
    binary=$(find "$tmp" -name "ntfy" -type f | head -1)
    [ -n "$binary" ] || die "Binary not found in archive"

    install -m 755 "$binary" "${INSTALL_DIR}/ntfy"
    log "ntfy binary installed to ${INSTALL_DIR}/ntfy"
    rm -rf "$tmp"

    # Install systemd service manually
    create_systemd_service
}

install_arch() {
    local aur_pkg="ntfy"

    # Le paquet des depots officiels passe avant tout : pacman l'installe et
    # le met a jour sans assistant ni compte utilisateur.
    if pacman -Si ntfy >/dev/null 2>&1; then
        log "Installing ntfy from the Arch repositories (pacman)..."
        pacman -S --noconfirm ntfy
        # Le service est demarre par son nom : un paquet sans unite en
        # recoit une, qui lance le binaire du paquet.
        if ! systemctl cat ntfy.service >/dev/null 2>&1; then
            create_systemd_service "$(command -v ntfy || echo /usr/bin/ntfy)"
        fi
        return
    fi

    # Un assistant AUR construit en tant qu'utilisateur et peut poser des
    # questions : sans personne au terminal, c'est le binaire officiel.
    if non_interactive; then
        log "ntfy absent des depots, mode non interactif : binaire officiel."
        local version
        version=$(get_latest_version)
        install_binary "$version"
        return
    fi

    if command -v yay &>/dev/null; then
        log "Installing via yay (AUR)..."
        sudo -u "${SUDO_USER:-$USER}" yay -S --noconfirm "$aur_pkg"
    elif command -v paru &>/dev/null; then
        log "Installing via paru (AUR)..."
        sudo -u "${SUDO_USER:-$USER}" paru -S --noconfirm "$aur_pkg"
    else
        log "No AUR helper found (yay/paru). Falling back to binary install..."
        local version
        version=$(get_latest_version)
        install_binary "$version"
    fi
}

# Ecrit l'unite systemd de ntfy. $1 : le binaire lance (defaut
# $INSTALL_DIR/ntfy). ProtectSystem=strict met tout le systeme en lecture
# seule pour le service, sauf ReadWritePaths : le cache ET la base des comptes
# (DATA_DIR, ou vit user.db) doivent y figurer, et exister au demarrage —
# configure_ntfy les cree avant enable_service.
create_systemd_service() {
    local binary="${1:-${INSTALL_DIR}/ntfy}"
    cat > "${SYSTEMD_UNIT}" <<SYSTEMD
[Unit]
Description=ntfy push notification server
After=network.target

[Service]
Type=simple
ExecStart=${binary} serve
Restart=on-failure
RestartSec=5
User=ntfy
Group=ntfy
AmbientCapabilities=CAP_NET_BIND_SERVICE
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=${CACHE_DIR} ${DATA_DIR} ${CONFIG_DIR}

[Install]
WantedBy=multi-user.target
SYSTEMD

    # Create dedicated system user if it doesn't exist
    if ! id ntfy &>/dev/null; then
        useradd --system --no-create-home --shell /usr/sbin/nologin ntfy
    fi

    log "Systemd service created."
}

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

configure_ntfy() {
    log "Configuring NTFY..."
    mkdir -p "$CONFIG_DIR" "$CACHE_DIR" "$DATA_DIR"

    # Set ownership for cache dir if ntfy user exists
    if id ntfy &>/dev/null; then
        chown ntfy:ntfy "$CACHE_DIR" "$DATA_DIR"
    fi

    # Une configuration deja en place est RESPECTEE — elle peut porter des
    # reglages d'exploitation que ce script ignore — mais seulement si elle
    # declare son controle d'acces. Celle d'une distribution n'en declare
    # aucun : lecture ET ecriture anonymes sur tous les sujets, sur toutes
    # les interfaces, alors que ce script annonce le contraire. Une posture
    # annoncee et non appliquee est pire que pas de script. Les reglages
    # d'une configuration gardee (port, certificat) ne sont pas modifies ici.
    if [ -f "${CONFIG_DIR}/server.yml" ]; then
        if grep -qE '^[[:space:]]*auth-default-access:' "${CONFIG_DIR}/server.yml"; then
            log "Config already exists at ${CONFIG_DIR}/server.yml — skipping."
            return
        fi
        echo
        echo "  La configuration en place ne declare AUCUN controle d'acces." >&2
        echo "  ntfy autorise alors la lecture et l'ecriture anonymes sur tous" >&2
        echo "  les sujets : qui apprend un nom de sujet lit tout ce qui y" >&2
        echo "  transite. Ce script ne la remplace pas en silence." >&2
        echo >&2
        echo "  Ecartez-la, puis relancez :" >&2
        echo "    sudo mv ${CONFIG_DIR}/server.yml ${CONFIG_DIR}/server.yml.origine" >&2
        echo "    sudo bash \$0" >&2
        echo >&2
        echo "  Ou gardez-la en connaissance de cause : NTFY_GARDER_CONFIG=1" >&2
        if [ "${NTFY_GARDER_CONFIG:-0}" = "1" ]; then
            log "NTFY_GARDER_CONFIG=1 — configuration permissive conservee."
            return
        fi
        die "configuration en place sans controle d'acces"
    fi

    if [ -n "${NTFY_CERT_FILE}" ] && [ -n "${NTFY_KEY_FILE}" ]; then
        # 8443 par defaut et non 443 : 443 est le port de nginx sur un hote
        # de production, et un port sous 1024 exige CAP_NET_BIND_SERVICE,
        # que l'unite des paquets ne donne pas toujours.
        local https_port="${NTFY_HTTPS_PORT:-8443}"
        case "${https_port}" in
            ''|*[!0-9]*) die "NTFY_HTTPS_PORT invalide : ${https_port}" ;;
        esac
        if [ "${https_port}" -lt 1 ] || [ "${https_port}" -gt 65535 ]; then
            die "NTFY_HTTPS_PORT hors limites : ${https_port}"
        fi
        [ -f "${NTFY_CERT_FILE}" ] || die "Certificat introuvable : ${NTFY_CERT_FILE}"
        [ -f "${NTFY_KEY_FILE}" ]  || die "Cle introuvable : ${NTFY_KEY_FILE}"
        TLS_BLOCK=$(printf 'listen-https: ":%s"\ncert-file: "%s"\nkey-file: "%s"' \
            "${https_port}" "${NTFY_CERT_FILE}" "${NTFY_KEY_FILE}")
        log "TLS active sur le port ${https_port}."
    else
        TLS_BLOCK="# Pas de TLS : aucun certificat fourni (NTFY_CERT_FILE / NTFY_KEY_FILE)."
        log "AVERTISSEMENT : aucun TLS. Le trafic circule en clair."
    fi

    if [ "${NTFY_PUBLIC}" = "1" ]; then
        DEFAULT_ACCESS="read-write"
        log "AVERTISSEMENT : NTFY_PUBLIC=1 — acces anonyme en lecture et ecriture."
    else
        DEFAULT_ACCESS="deny-all"
    fi

    cat > "${CONFIG_DIR}/server.yml" <<YAML
# NTFY Server configuration
# Documentation: https://ntfy.sh/docs/config/

# Public URL of this server (used in notification links)
base-url: "${NTFY_BASE_URL}"

# Listening address
listen-http: ":${NTFY_PORT}"
${TLS_BLOCK}

# Message cache (enables message history for reconnecting subscribers)
cache-file: "${CACHE_DIR}/cache.db"
cache-duration: "12h"

log-level: info

# Attachment support
attachment-cache-dir: "${CACHE_DIR}/attachments"
attachment-total-size-limit: "5G"
attachment-file-size-limit: "15M"
attachment-expiry-duration: "3h"

# ─── Authentification ────────────────────────────────────────────────────────
# ACTIVE par defaut. Sans ces deux lignes, ntfy autorise la lecture ET
# l'ecriture anonymes sur tout sujet : connaitre le nom suffit.
auth-file: "${AUTH_FILE}"
auth-default-access: "${DEFAULT_ACCESS}"
YAML
    log "Configuration written to ${CONFIG_DIR}/server.yml"
}

# ---------------------------------------------------------------------------
# Enable & start service
# ---------------------------------------------------------------------------

# Un echec ici n'arrete pas le script : service_state dit ensuite l'etat
# reel, et main le rend en derniere ligne et en code de sortie.
enable_service() {
    log "Enabling and starting ntfy service..."
    systemctl daemon-reload || log "AVERTISSEMENT : systemctl daemon-reload a echoue."
    systemctl enable ntfy || log "AVERTISSEMENT : systemctl enable ntfy a echoue."
    systemctl restart ntfy || log "AVERTISSEMENT : systemctl restart ntfy a echoue."
    sleep 1
}

# Imprime l'etat systemd de ntfy (active, failed, inactive...). Un etat
# transitoire (activating, reloading) est relu chaque seconde, dix fois au
# plus : un service qui plante et que systemd relance reste « activating »
# et finit rendu tel quel, donc en echec.
service_state() {
    local state tries=0
    while :; do
        state=$(systemctl is-active ntfy 2>/dev/null) || true
        case "${state}" in
            activating|reloading) ;;
            *) break ;;
        esac
        tries=$((tries + 1))
        if [ "${tries}" -ge 10 ]; then
            break
        fi
        sleep 1
    done
    echo "${state:-unknown}"
}


# ---------------------------------------------------------------------------
# Compte administrateur
# ---------------------------------------------------------------------------

# ntfy_cli [-p <mot de passe>] <commande>... : lance la commande sans aucune
# variable NTFY_* exportee — la CLI ntfy les lit AVANT --config, et celles qui
# pilotent ce script (NTFY_BASE_URL, NTFY_CERT_FILE...) ou un NTFY_AUTH_FILE
# herite viseraient un autre fichier. -p exporte NTFY_PASSWORD pour la seule
# commande lancee. Le retrait et l'export se font par des commandes internes
# dans un sous-shell, puis exec : le mot de passe ne figure dans l'argv
# d'aucun processus (lisible de tout compte local par ps ou
# /proc/<pid>/cmdline), seulement dans l'environnement de la CLI. Les
# arguments d'une fonction shell, eux, restent dans la memoire du shell.
ntfy_cli() {
    local password=""
    if [ "${1:-}" = "-p" ]; then
        password="$2"
        shift 2
    fi
    (
        for var in $(compgen -e); do
            case "${var}" in
                NTFY_*) unset "${var}" ;;
            esac
        done
        if [ -n "${password}" ]; then
            export NTFY_PASSWORD="${password}"
        fi
        exec "$@"
    )
}

# Imprime le chemin de auth-file lu dans la configuration en place (une
# configuration gardee peut le placer ailleurs), AUTH_FILE a defaut.
config_auth_file() {
    local file
    file=$(sed -nE "s/^auth-file:[[:space:]]*[\"']?([^\"'#]*).*/\1/p" \
        "${CONFIG_DIR}/server.yml" 2>/dev/null | head -n 1 \
        | sed 's/[[:space:]]*$//')
    echo "${file:-${AUTH_FILE}}"
}

ensure_admin_user() {
    # `deny-all` sans compte rend le serveur inutilisable : personne ne peut
    # plus ni publier ni lire. Refuser l'acces ET ne donner aucune cle serait
    # une panne, pas une securite.
    if [ "${NTFY_PUBLIC}" = "1" ]; then
        return
    fi
    local config="${CONFIG_DIR}/server.yml"
    local motdepasse auth_file f

    # « user list » ecrit sur la sortie d'erreur.
    if ntfy_cli ntfy user --config "${config}" list 2>&1 \
            | grep -q "^user ${NTFY_ADMIN_USER} "; then
        log "Compte ${NTFY_ADMIN_USER} deja present, mot de passe inchange."
    else
        motdepasse=$(head -c 24 /dev/urandom | base64 | tr -d '/+=' | head -c 24)
        if ntfy_cli -p "${motdepasse}" \
                ntfy user --config "${config}" add --role=admin \
                "${NTFY_ADMIN_USER}" >/dev/null 2>&1; then
            # Affiche UNE seule fois, sur la ligne @@ADMIN_PASSWORD que le
            # menu de todo.py relit, et jamais ecrit dans un fichier : un mot
            # de passe laisse sur disque par un installateur y reste.
            echo
            echo "=================================================================="
            echo "  COMPTE ADMINISTRATEUR NTFY : ${NTFY_ADMIN_USER}"
            echo "  Mot de passe sur la ligne suivante, affiche une seule fois,"
            echo "  ecrit nulle part :"
            echo "@@ADMIN_PASSWORD ${motdepasse}"
            echo "  Pour le changer :"
            echo "    ntfy user --config ${config} change-pass ${NTFY_ADMIN_USER}"
            echo "=================================================================="
            echo
        else
            log "AVERTISSEMENT : creation du compte impossible."
            log "  A faire a la main : ntfy user --config ${config} add --role=admin ${NTFY_ADMIN_USER}"
        fi
    fi

    # La CLI tourne en root : la base qu'elle cree ou ouvre (et ses fichiers
    # -wal / -shm) revient au compte du service, qui doit pouvoir y ecrire.
    auth_file=$(config_auth_file)
    if id ntfy &>/dev/null; then
        for f in "${auth_file}" "${auth_file}-wal" "${auth_file}-shm"; do
            if [ -e "${f}" ]; then
                chown ntfy:ntfy "${f}"
            fi
        done
    fi
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

main() {
    check_root
    detect_os
    if non_interactive; then
        export DEBIAN_FRONTEND=noninteractive
    fi

    if command -v ntfy &>/dev/null && ntfy --version &>/dev/null; then
        log "ntfy is already installed: $(ntfy --version 2>/dev/null | head -1)"
        log "Reconfiguring and restarting..."
    elif is_ubuntu_like; then
        log "Using Ubuntu/Debian install path..."
        apt-get update -qq
        apt-get install -y --no-install-recommends curl ca-certificates
        local version
        version=$(get_latest_version)
        log "Installing ntfy v${version}..."
        install_deb "$version"
    elif is_arch_like; then
        log "Using Arch Linux install path..."
        install_arch
    else
        log "Unknown OS '${OS}', attempting generic binary install..."
        apt-get install -y --no-install-recommends curl ca-certificates 2>/dev/null \
            || pacman -S --noconfirm curl ca-certificates 2>/dev/null \
            || true
        local version
        version=$(get_latest_version)
        install_binary "$version"
    fi

    configure_ntfy
    # Le compte AVANT le demarrage : « deny-all » sans cle donne un serveur
    # que personne ne peut ni lire ni alimenter, et le compte se cree a
    # travers la meme configuration que le service va lire.
    ensure_admin_user
    enable_service

    local state ip
    state=$(service_state)
    ip=$(hostname -I 2>/dev/null | awk '{print $1}')
    ip="${ip:-127.0.0.1}"

    echo ""
    echo "======================================================="
    if [ "${state}" = "active" ]; then
        echo " NTFY push notification server installed successfully!"
    else
        # Annoncer un succes que le service dement envoie chercher la panne
        # partout sauf la ou elle est.
        echo " NTFY INSTALLE MAIS NON DEMARRE (${state}) — voir :"
        echo "   systemctl status ntfy; journalctl -u ntfy -n 30"
    fi
    echo "======================================================="
    echo " Local URL  : http://localhost:${NTFY_PORT}"
    echo " Network URL: http://${ip}:${NTFY_PORT}"
    if [ -n "${NTFY_CERT_FILE}" ] && [ -n "${NTFY_KEY_FILE}" ]; then
        echo " HTTPS URL  : https://${ip}:${NTFY_HTTPS_PORT:-8443}"
    fi
    echo " Config     : ${CONFIG_DIR}/server.yml"
    echo "-------------------------------------------------------"
    echo " Test (send a notification):"
    echo "   curl -d 'Hello World' http://localhost:${NTFY_PORT}/my-topic"
    echo ""
    echo " Subscribe on mobile (ntfy app):"
    echo "   1. Install 'ntfy' from Google Play / F-Droid / App Store"
    echo "   2. Add server: http://${ip}:${NTFY_PORT}"
    echo "   3. Subscribe to topic: my-topic"
    echo "======================================================="
    # Derniere ligne et code de sortie : l'appelant distant ne lit que ca.
    echo "@@ACTIVE ntfy ${state}"
    [ "${state}" = "active" ]
}

main "$@"
