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
NTFY_PUBLIC="${NTFY_PUBLIC:-0}"
NTFY_CERT_FILE="${NTFY_CERT_FILE:-}"
NTFY_KEY_FILE="${NTFY_KEY_FILE:-}"
NTFY_ADMIN_USER="${NTFY_ADMIN_USER:-erplibre}"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

log()  { echo "[NTFY] $*"; }
die()  { echo "[NTFY] ERROR: $*" >&2; exit 1; }

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
    dpkg -i "${tmp}/${deb_file}" || apt-get install -f -y
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

install_arch_aur() {
    local aur_pkg="ntfy"

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

create_systemd_service() {
    cat > /etc/systemd/system/ntfy.service <<'SYSTEMD'
[Unit]
Description=ntfy push notification server
After=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/ntfy serve
Restart=on-failure
RestartSec=5
User=ntfy
Group=ntfy
AmbientCapabilities=CAP_NET_BIND_SERVICE
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/var/cache/ntfy /etc/ntfy

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
    mkdir -p "$CONFIG_DIR" "$CACHE_DIR"

    # Set ownership for cache dir if ntfy user exists
    if id ntfy &>/dev/null; then
        chown ntfy:ntfy "$CACHE_DIR"
    fi

    if [ -f "${CONFIG_DIR}/server.yml" ]; then
        log "Config already exists at ${CONFIG_DIR}/server.yml — skipping."
        return
    fi

    if [ -n "${NTFY_CERT_FILE}" ] && [ -n "${NTFY_KEY_FILE}" ]; then
        [ -f "${NTFY_CERT_FILE}" ] || die "Certificat introuvable : ${NTFY_CERT_FILE}"
        [ -f "${NTFY_KEY_FILE}" ]  || die "Cle introuvable : ${NTFY_KEY_FILE}"
        TLS_BLOCK=$(printf 'listen-https: ":443"\ncert-file: "%s"\nkey-file: "%s"' \
            "${NTFY_CERT_FILE}" "${NTFY_KEY_FILE}")
        log "TLS active."
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
auth-file: "${CONFIG_DIR}/user.db"
auth-default-access: "${DEFAULT_ACCESS}"
YAML
    log "Configuration written to ${CONFIG_DIR}/server.yml"
}

# ---------------------------------------------------------------------------
# Enable & start service
# ---------------------------------------------------------------------------

enable_service() {
    log "Enabling and starting ntfy service..."
    systemctl daemon-reload
    systemctl enable ntfy
    systemctl restart ntfy
    sleep 1
    systemctl is-active ntfy --quiet && log "ntfy is running." \
        || log "Warning: ntfy may not have started. Run: systemctl status ntfy"
}


# ---------------------------------------------------------------------------
# Compte administrateur
# ---------------------------------------------------------------------------

ensure_admin_user() {
    # `deny-all` sans compte rend le serveur inutilisable : personne ne peut
    # plus ni publier ni lire. Refuser l'acces ET ne donner aucune cle serait
    # une panne, pas une securite.
    if [ "${NTFY_PUBLIC}" = "1" ]; then
        return
    fi
    if ntfy user list 2>/dev/null | grep -q "^user ${NTFY_ADMIN_USER}"; then
        log "Compte ${NTFY_ADMIN_USER} deja present, mot de passe inchange."
        return
    fi

    local motdepasse
    motdepasse=$(head -c 24 /dev/urandom | base64 | tr -d '/+=' | head -c 24)
    if ! NTFY_PASSWORD="${motdepasse}" ntfy user add --role=admin \
            "${NTFY_ADMIN_USER}" >/dev/null 2>&1; then
        log "AVERTISSEMENT : creation du compte impossible."
        log "  A faire a la main : ntfy user add --role=admin ${NTFY_ADMIN_USER}"
        return
    fi

    # Affiche UNE seule fois, et jamais ecrit dans un fichier : un mot de
    # passe laisse sur disque par un script d'installation y reste des annees.
    echo
    echo "=================================================================="
    echo "  COMPTE ADMINISTRATEUR NTFY — note-le maintenant"
    echo "=================================================================="
    echo "  utilisateur : ${NTFY_ADMIN_USER}"
    echo "  mot de passe : ${motdepasse}"
    echo "=================================================================="
    echo "  Il n'est affiche qu'ici et n'est ecrit nulle part."
    echo "  Pour le changer : ntfy user change-pass ${NTFY_ADMIN_USER}"
    echo
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

main() {
    check_root
    detect_os

    if command -v ntfy &>/dev/null && ntfy version &>/dev/null 2>&1; then
        log "ntfy is already installed: $(ntfy version 2>/dev/null | head -1)"
        log "Reconfiguring and restarting..."
        configure_ntfy
        enable_service
        ensure_admin_user
    elif is_ubuntu_like; then
        log "Using Ubuntu/Debian install path..."
        apt-get update -qq
        apt-get install -y --no-install-recommends curl ca-certificates
        local version
        version=$(get_latest_version)
        log "Installing ntfy v${version}..."
        install_deb "$version"
        configure_ntfy
        enable_service
        ensure_admin_user
    elif is_arch_like; then
        log "Using Arch Linux install path..."
        install_arch_aur
        configure_ntfy
        enable_service
        ensure_admin_user
    else
        log "Unknown OS '${OS}', attempting generic binary install..."
        apt-get install -y --no-install-recommends curl ca-certificates 2>/dev/null \
            || pacman -S --noconfirm curl ca-certificates 2>/dev/null \
            || true
        local version
        version=$(get_latest_version)
        install_binary "$version"
        configure_ntfy
        enable_service
        ensure_admin_user
    fi

    local ip
    ip=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "127.0.0.1")

    echo ""
    echo "======================================================="
    echo " NTFY push notification server installed successfully!"
    echo "======================================================="
    echo " Local URL  : http://localhost:${NTFY_PORT}"
    echo " Network URL: http://${ip}:${NTFY_PORT}"
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
}

main "$@"
