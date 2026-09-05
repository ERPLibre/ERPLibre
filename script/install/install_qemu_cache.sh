#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Pose erplibre_go_qemu_cache : le miroir de téléchargement des VM QEMU
# locales. Compile depuis les sources du dépôt, installe une unité systemd,
# et laisse le service poser lui-même ses règles de détournement.
#
# Les règles de pare-feu ne sont PAS écrites par ce script. L'unité les pose
# à son démarrage et les retire à son arrêt, en tubant « --print-nft » dans
# nft : une VM ne peut donc pas rester détournée vers un cache éteint, et le
# jeu de règles vient du code Go que les tests vérifient, jamais d'une copie.
#
# Usage :
#   sudo bash install_qemu_cache.sh
#   sudo EL_HTTP_PORT=8898 EL_TLS_PORT=8899 EL_BRIDGE=virbr0 \
#        EL_SUBNET=192.168.122.0/24 bash install_qemu_cache.sh

set -e

EL_HTTP_PORT="${EL_HTTP_PORT:-8898}"
EL_TLS_PORT="${EL_TLS_PORT:-8899}"
# Vides par défaut : le pont et le sous-réseau sont LUS dans libvirt plus bas.
# Les supposer est le défaut qui rend l'installation silencieusement inutile —
# un hôte dont le réseau par défaut a été déplacé sur un /24 libre, ce qui
# arrive dès que 192.168.122 entre en collision, voit ses VM échapper au
# détournement sans que rien ne le signale.
EL_BRIDGE="${EL_BRIDGE:-}"
EL_SUBNET="${EL_SUBNET:-}"
EL_NET="${EL_NET:-default}"
EL_CACHE_DIR="${EL_CACHE_DIR:-/var/cache/erplibre_go_qemu_cache}"
EL_CA_DIR="${EL_CA_DIR:-/var/lib/erplibre_go_qemu_cache}"
EL_ACCESS_LOG="${EL_ACCESS_LOG:-/var/log/erplibre_go_qemu_cache.jsonl}"
EL_EXCLUDE="${EL_EXCLUDE:-}"
EL_BYPASS_FILE="${EL_BYPASS_FILE:-/etc/erplibre_go_qemu_cache/bypass}"

BIN="/usr/local/bin/erplibre_go_qemu_cache"
CONF_DIR="/etc/erplibre_go_qemu_cache"
UNIT="/etc/systemd/system/erplibre-go-qemu-cache.service"
SERVICE_USER="elqcache"
GO_MIN_MAJOR=1
GO_MIN_MINOR=21

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# EL_SRC_DIR passe outre la déduction : le script se retrouve ainsi lançable
# depuis un chemin copié, et une vérification peut appeler UNE de ses
# fonctions sans que la déduction échoue faute de dépôt autour.
SRC_DIR="${EL_SRC_DIR:-$(cd "${SCRIPT_DIR}/../qemu_cache" && pwd)}"

log() { echo "[cache QEMU] $*"; }
die() {
  echo "[cache QEMU] ERREUR : $*" >&2
  exit 1
}

check_root() {
  if [ "$EUID" -ne 0 ]; then
    die "à lancer en root : sudo bash $0"
  fi
}

detect_os() {
  [ -f /etc/os-release ] || die "système inconnu (pas de /etc/os-release)"
  # shellcheck disable=SC1091
  . /etc/os-release
  OS="${ID}"
  OS_LIKE="${ID_LIKE:-}"
  log "système : ${OS}"
}

is_arch_like() {
  case "$OS" in
    arch | manjaro | endeavouros | artix | garuda) return 0 ;;
    *) echo "$OS_LIKE" | grep -q "arch" && return 0 || return 1 ;;
  esac
}

is_debian_like() {
  case "$OS" in
    ubuntu | debian | linuxmint | pop | elementary | raspbian) return 0 ;;
    *) echo "$OS_LIKE" | grep -qE "debian|ubuntu" && return 0 || return 1 ;;
  esac
}

is_fedora_like() {
  case "$OS" in
    fedora | rhel | centos | almalinux | rocky) return 0 ;;
    *) echo "$OS_LIKE" | grep -qE "fedora|rhel" && return 0 || return 1 ;;
  esac
}

# ---------------------------------------------------------------------------
# Le réseau que les VM utilisent VRAIMENT
# ---------------------------------------------------------------------------

# detecter_reseau remplit EL_BRIDGE et EL_SUBNET depuis libvirt.
#
# Le réseau « default » ne sert pas toujours 192.168.122.0/24 : il est déplacé
# sur un /24 libre quand ce préfixe entre en collision avec ce que l'hôte
# route déjà — le cas de tout orchestrateur qui est lui-même une VM. Poser des
# règles sur le mauvais préfixe laisse une installation qui réussit, des
# règles bien présentes dans le noyau, et un cache que personne ne traverse.
detecter_reseau() {
  local xml adresse masque
  xml="$(virsh -c qemu:///system net-dumpxml "$EL_NET" 2>/dev/null)" || {
    die "réseau libvirt « ${EL_NET} » introuvable — virsh -c qemu:///system net-list"
  }
  [ -n "$EL_BRIDGE" ] || EL_BRIDGE="$(echo "$xml" |
    sed -n "s/.*<bridge name='\([^']*\)'.*/\1/p" | head -1)"
  if [ -z "$EL_SUBNET" ]; then
    adresse="$(echo "$xml" | sed -n "s/.*<ip address='\([^']*\)'.*/\1/p" | head -1)"
    masque="$(echo "$xml" | sed -n "s/.*netmask='\([^']*\)'.*/\1/p" | head -1)"
    [ "$masque" = "255.255.255.0" ] || die \
      "le réseau « ${EL_NET} » ne sert pas un /24 (masque ${masque:-inconnu}) :" \
      "passer EL_SUBNET à la main"
    EL_SUBNET="${adresse%.*}.0/24"
  fi
  [ -n "$EL_BRIDGE" ] && [ -n "$EL_SUBNET" ] || die \
    "pont ou sous-réseau illisibles dans le réseau « ${EL_NET} »"
  log "réseau lu dans libvirt : ${EL_BRIDGE}, ${EL_SUBNET}"
}

# ---------------------------------------------------------------------------
# Go
# ---------------------------------------------------------------------------

# find_go cherche au-delà du PATH de root : un Go posé par mise ou par un
# gestionnaire de versions vit dans le compte de l'opérateur, que sudo ne
# traverse pas.
find_go() {
  local candidat
  for candidat in \
    "$(command -v go 2>/dev/null || true)" \
    /usr/local/go/bin/go \
    /usr/lib/go/bin/go; do
    [ -n "$candidat" ] && [ -x "$candidat" ] && echo "$candidat" && return 0
  done
  return 1
}

go_assez_recent() {
  local go_bin="$1" v major minor
  v="$("$go_bin" version 2>/dev/null | sed -n 's/.*go\([0-9]*\)\.\([0-9]*\).*/\1 \2/p')"
  [ -z "$v" ] && return 1
  major="${v% *}"
  minor="${v#* }"
  [ "$major" -gt "$GO_MIN_MAJOR" ] && return 0
  [ "$major" -eq "$GO_MIN_MAJOR" ] && [ "$minor" -ge "$GO_MIN_MINOR" ] && return 0
  return 1
}

installer_go() {
  log "Go absent ou trop ancien : installation par le gestionnaire de paquets"
  if is_arch_like; then
    pacman -S --needed --noconfirm go
  elif is_debian_like; then
    DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=600 update -qq
    DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=600 \
      install -y golang-go
  elif is_fedora_like; then
    dnf install -y golang
  else
    die "distribution non prévue : installer Go ${GO_MIN_MAJOR}.${GO_MIN_MINOR}+ à la main"
  fi
}

assurer_go() {
  local go_bin
  if go_bin="$(find_go)" && go_assez_recent "$go_bin"; then
    GO="$go_bin"
    log "Go : $("$GO" version)"
    return
  fi
  installer_go
  go_bin="$(find_go)" || die "Go reste introuvable après installation"
  go_assez_recent "$go_bin" ||
    die "le Go de la distribution est plus ancien que ${GO_MIN_MAJOR}.${GO_MIN_MINOR} ; poser une version récente à la main"
  GO="$go_bin"
  log "Go : $("$GO" version)"
}

# ---------------------------------------------------------------------------
# Compilation
# ---------------------------------------------------------------------------

compiler() {
  [ -f "${SRC_DIR}/go.mod" ] || die "sources absentes : ${SRC_DIR}"
  log "compilation depuis ${SRC_DIR}"
  # Le cache de compilation dans un temporaire : root n'a pas à laisser
  # d'état dans son compte pour une compilation unique.
  local gocache
  gocache="$(mktemp -d)"
  (
    cd "$SRC_DIR"
    GOCACHE="$gocache" GOFLAGS=-mod=mod "$GO" build -o "$BIN" .
  )
  rm -rf "$gocache"
  chmod 0755 "$BIN"
  log "posé : ${BIN} ($("$BIN" --version))"
}

# ---------------------------------------------------------------------------
# Compte, répertoires, autorité
# ---------------------------------------------------------------------------

preparer_etat() {
  if ! id "$SERVICE_USER" >/dev/null 2>&1; then
    useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER" \
      2>/dev/null ||
      useradd --system --no-create-home --shell /sbin/nologin "$SERVICE_USER"
    log "compte de service créé : ${SERVICE_USER}"
  fi
  mkdir -p "$EL_CACHE_DIR" "$EL_CA_DIR" "$CONF_DIR"
  touch "$EL_ACCESS_LOG"
  # La liste des exceptions appartient à root : elle décide qui échappe au
  # cache, et le compte du service ne doit pas pouvoir s'y ajouter.
  mkdir -p "$(dirname "$EL_BYPASS_FILE")"
  [ -f "$EL_BYPASS_FILE" ] || cat >"$EL_BYPASS_FILE" <<'BYPASS'
# Exceptions du cache de téléchargement des VM QEMU.
# Une ligne « <MAC> <nom de la VM> » par machine que le détournement doit
# ignorer. Relu à chaque démarrage du service.
BYPASS
  chmod 0644 "$EL_BYPASS_FILE"
  chown -R "${SERVICE_USER}:${SERVICE_USER}" "$EL_CACHE_DIR" "$EL_CA_DIR" "$EL_ACCESS_LOG"
  chmod 0755 "$EL_CACHE_DIR" "$EL_CA_DIR"
}

# L'autorité est créée ICI plutôt qu'au premier démarrage : l'installation
# doit pouvoir en dire l'empreinte, que l'opérateur compare ensuite dans la VM.
creer_autorite() {
  runuser -u "$SERVICE_USER" -- "$BIN" --init-ca --ca-dir "$EL_CA_DIR" ||
    die "l'autorité n'a pas pu être créée dans ${EL_CA_DIR}"
}

# ---------------------------------------------------------------------------
# Configuration et unité
# ---------------------------------------------------------------------------

ecrire_config() {
  cat >"${CONF_DIR}/env" <<CONF
# Réglages du cache de téléchargement des VM QEMU.
# Changer une valeur puis : systemctl restart erplibre-go-qemu-cache
EL_CACHE_DIR=${EL_CACHE_DIR}
EL_CA_DIR=${EL_CA_DIR}
EL_HTTP_PORT=${EL_HTTP_PORT}
EL_TLS_PORT=${EL_TLS_PORT}
EL_BRIDGE=${EL_BRIDGE}
EL_SUBNET=${EL_SUBNET}
EL_ACCESS_LOG=${EL_ACCESS_LOG}
EL_EXCLUDE=${EL_EXCLUDE}
EL_BYPASS_FILE=${EL_BYPASS_FILE}
CONF
  chmod 0644 "${CONF_DIR}/env"
}

# Le détournement est choisi une fois, à l'installation : nft s'il est là,
# iptables sinon. Les deux jeux de règles viennent du binaire.
regles_apply_cmd() {
  if command -v nft >/dev/null 2>&1; then
    echo "${BIN} --print-nft --bridge \${EL_BRIDGE} --subnet \${EL_SUBNET} --http-port \${EL_HTTP_PORT} --tls-port \${EL_TLS_PORT} --bypass-file \${EL_BYPASS_FILE} | nft -f -"
  else
    echo "${BIN} --print-iptables --bridge \${EL_BRIDGE} --subnet \${EL_SUBNET} --http-port \${EL_HTTP_PORT} --tls-port \${EL_TLS_PORT} --bypass-file \${EL_BYPASS_FILE} | sh -s"
  fi
}

regles_clear_cmd() {
  if command -v nft >/dev/null 2>&1; then
    echo "nft delete table ip erplibre_qemu_cache 2>/dev/null || true"
  else
    echo "${BIN} --print-iptables --bridge \${EL_BRIDGE} --subnet \${EL_SUBNET} --http-port \${EL_HTTP_PORT} --tls-port \${EL_TLS_PORT} --bypass-file \${EL_BYPASS_FILE} | sed 's/ -A / -D /' | sh -s || true"
  fi
}

ecrire_unite() {
  # « + » devant une commande la fait tourner en root même sous User= : poser
  # une règle de pare-feu demande un privilège que le service n'a pas, et ne
  # doit pas avoir, pendant qu'il sert des fichiers.
  cat >"$UNIT" <<UNITE
[Unit]
Description=Cache de téléchargement ERPLibre pour les VM QEMU
After=network.target libvirtd.service
Wants=libvirtd.service

[Service]
Type=simple
EnvironmentFile=${CONF_DIR}/env
User=${SERVICE_USER}
Group=${SERVICE_USER}
ExecStartPre=+/bin/sh -c '$(regles_apply_cmd)'
ExecStart=${BIN} --cache-dir \${EL_CACHE_DIR} --ca-dir \${EL_CA_DIR} --http-port \${EL_HTTP_PORT} --tls-port \${EL_TLS_PORT} --bridge \${EL_BRIDGE} --subnet \${EL_SUBNET} --access-log \${EL_ACCESS_LOG} --exclude \${EL_EXCLUDE}
ExecStopPost=+/bin/sh -c '$(regles_clear_cmd)'
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=${EL_CACHE_DIR} ${EL_CA_DIR} ${EL_ACCESS_LOG}

[Install]
WantedBy=multi-user.target
UNITE
  chmod 0644 "$UNIT"
  systemctl daemon-reload
}

# ---------------------------------------------------------------------------

main() {
  check_root
  detect_os
  detecter_reseau
  assurer_go
  compiler
  preparer_etat
  creer_autorite
  ecrire_config
  ecrire_unite

  systemctl enable erplibre-go-qemu-cache.service >/dev/null 2>&1 || true
  systemctl restart erplibre-go-qemu-cache.service

  # Un service qui ne tient pas doit le dire ici, et non se découvrir au
  # prochain déploiement de VM.
  sleep 2
  if ! systemctl is-active --quiet erplibre-go-qemu-cache.service; then
    systemctl status --no-pager -l erplibre-go-qemu-cache.service || true
    die "le service ne tient pas ; les règles ont été retirées à son arrêt"
  fi

  log ""
  log "cache actif sur ${EL_HTTP_PORT} (http) et ${EL_TLS_PORT} (tls)"
  log "détournement : ${EL_BRIDGE}, depuis ${EL_SUBNET}, sortie du /24 seule"
  log "autorité à faire approuver dans chaque VM :"
  log "  ${EL_CA_DIR}/ca.crt"
  "$BIN" --status --cache-dir "$EL_CACHE_DIR" --ca-dir "$EL_CA_DIR" || true
}

main "$@"
