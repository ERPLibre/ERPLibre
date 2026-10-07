#!/usr/bin/env bash
# Installe erplibre_sip_go : un service SIP minimal, en Go, qui place un
# appel par un trunk et joue une annonce AU DECROCHE.
#
# Usage :
#   bash install_sip_go.sh                 # compile et installe pour l'utilisateur
#   sudo AST_SYSTEM=1 bash install_sip_go.sh   # installe pour tout le systeme
#
# Pourquoi ce service plutot qu'un PBX :
#
#   Le besoin est etroit — s'enregistrer sur un trunk, composer, savoir quand
#   ca decroche, jouer un fichier, rapporter. Un PBX generaliste apporterait
#   postes, files d'attente, serveur vocal et transferts dont rien n'est
#   utilise, mais qu'il faudrait securiser et maintenir.
#
#   Surtout : Asterisk ET PJSIP ont ete RETIRES de Debian 12 et 13, faute de
#   mainteneurs pour en suivre la charge de securite. Les compiler depuis les
#   sources prive de toute mise a jour par la distribution. Ici l'arbre de
#   dependances est en modules Go, et le resultat est un binaire STATIQUE :
#   ce mode de defaillance ne peut pas se reproduire.
#
#   Ce script n'exige PAS les droits d'administration. Sans eux il installe
#   dans ~/.local/bin, ce qui suffit a tout essayer.

set -e

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../erplibre_sip_go" && pwd)"
SYSTEM="${SIP_GO_SYSTEM:-0}"
GO_MIN="1.21"
GO_LOCAL="$HOME/.local/go"

if [ "$SYSTEM" = "1" ]; then
    BIN_DIR="/usr/local/bin"
    ENV_FILE="/etc/erplibre/sip_go.env"
else
    BIN_DIR="$HOME/.local/bin"
    ENV_FILE="$HOME/.config/erplibre/sip_go.env"
fi

log() { echo "[SIP-GO] $*"; }
die() { echo "[SIP-GO] ERREUR: $*" >&2; exit 1; }

trouver_go() {
    if command -v go >/dev/null 2>&1; then
        GO_BIN="$(command -v go)"
        return
    fi
    if [ -x "${GO_LOCAL}/bin/go" ]; then
        GO_BIN="${GO_LOCAL}/bin/go"
        return
    fi
    GO_BIN=""
}

installer_go() {
    # Installation LOCALE et non par la distribution : elle ne demande aucun
    # droit d'administration, et n'impose pas sa version de Go au reste de la
    # machine.
    log "Go absent — installation locale dans ${GO_LOCAL}"
    local version archive tmp
    version="$(curl -fsSL 'https://go.dev/VERSION?m=text' 2>/dev/null | head -1)"
    [ -n "$version" ] || die "impossible de determiner la version de Go."
    tmp="$(mktemp -d)"
    archive="${tmp}/go.tar.gz"
    log "telechargement de ${version}"
    curl -fsSL -o "$archive" \
        "https://go.dev/dl/${version}.linux-amd64.tar.gz" \
        || { rm -rf "$tmp"; die "telechargement de Go impossible."; }
    mkdir -p "$(dirname "$GO_LOCAL")"
    rm -rf "$GO_LOCAL"
    tar -C "$(dirname "$GO_LOCAL")" -xzf "$archive"
    rm -rf "$tmp"
    GO_BIN="${GO_LOCAL}/bin/go"
    [ -x "$GO_BIN" ] || die "installation de Go echouee."
    log "Go installe : $("$GO_BIN" version)"
}

compiler() {
    log "compilation depuis ${SRC_DIR}"
    ( cd "$SRC_DIR" && CGO_ENABLED=0 "$GO_BIN" build -trimpath \
        -ldflags "-s -w" -o "${tmp_bin}" . ) \
        || die "compilation echouee."
    # CGO_ENABLED=0 n'est pas un detail : il garantit un binaire STATIQUE,
    # donc deployable sans installer la moindre bibliotheque C sur la cible.
    log "binaire : $(du -h "${tmp_bin}" | cut -f1), statique"
}

verifier() {
    "${tmp_bin}" -numero 12345 >/dev/null 2>&1 && \
        die "le binaire accepte un numero invalide — installation refusee."
    log "garde-fou verifie : un numero hors plan est refuse"
}

poser() {
    mkdir -p "$BIN_DIR"
    install -m 0755 "${tmp_bin}" "${BIN_DIR}/erplibre-sip-go"
    log "installe : ${BIN_DIR}/erplibre-sip-go"
    case ":$PATH:" in
        *":${BIN_DIR}:"*) ;;
        *) log "NOTE : ${BIN_DIR} n'est pas dans votre PATH." ;;
    esac
}

modele_env() {
    mkdir -p "$(dirname "$ENV_FILE")"
    if [ -f "$ENV_FILE" ]; then
        log "configuration existante conservee : ${ENV_FILE}"
        return
    fi
    cat > "$ENV_FILE" <<'EOF'
# Ligne SIP d'erplibre_sip_go.
#
# Ce fichier porte un SECRET : il n'est jamais versionne, et jamais copie
# dans la base de donnees. Un trunk vole sert a composer des numeros
# surtaxes a l'etranger, un vendredi soir.
VOIP_TRUNK=
VOIP_USER=
VOIP_PASSWORD=
# Numero presente a l'appele. Vide = VOIP_USER.
VOIP_FROM=
# Ecoute SIP locale. La boucle locale par defaut : un service SIP qui ecoute
# sur toutes les interfaces est scanne en continu.
VOIP_BIND=127.0.0.1:5080
EOF
    chmod 0600 "$ENV_FILE"
    log "modele de configuration : ${ENV_FILE} (0600)"
}

resume() {
    echo
    log "===================== INSTALLATION TERMINEE ====================="
    log "Binaire      : ${BIN_DIR}/erplibre-sip-go"
    log "Configuration: ${ENV_FILE}"
    echo
    log "Renseignez le trunk dans la configuration, puis :"
    log "  set -a; . ${ENV_FILE}; set +a"
    log "  erplibre-sip-go -numero 5551234567 -annonce /chemin/annonce.wav -v"
    echo
    log "AVANT TOUT APPEL REEL, ce que ce script ne peut pas faire pour vous :"
    log "  1. Un plafond de depense chez le fournisseur, ou un compte prepaye."
    log "     C'est le seul garde-fou qui borne la perte en cas de vol."
    log "  2. Les appels internationaux desactives chez le fournisseur."
    echo
    log "Un message enregistre fait de l'appel un composeur-messager"
    log "automatique au sens des Regles du CRTC : l'annonce doit COMMENCER par"
    log "le nom de l'organisme, l'objet, une adresse et un numero joignable."
}

main() {
    [ -d "$SRC_DIR" ] || die "sources introuvables : ${SRC_DIR}"
    command -v curl >/dev/null 2>&1 || die "curl est requis."
    trouver_go
    [ -n "$GO_BIN" ] || installer_go
    tmp_bin="$(mktemp)"
    trap 'rm -f "${tmp_bin}"' EXIT
    compiler
    verifier
    poser
    modele_env
    resume
}

main "$@"
