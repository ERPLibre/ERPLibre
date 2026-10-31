#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Hook de deploiement certbot de l'infrastructure d'appel ERPLibre, pose en
# /etc/letsencrypt/renewal-hooks/deploy/erplibre-call (root 0755). certbot
# le lance en root apres chaque certificat emis ou renouvele, pour toute
# lignee, avec RENEWED_LINEAGE=/etc/letsencrypt/live/<nom>.
#
# Pour la lignee « erplibre-call » seulement, une autre ne change rien :
#   1. coturn inscrit dans l'etat et TLS_DIR present : fullchain.pem et
#      privkey.pem deviennent turn.crt et turn.key (voir copy_pair) ;
#      coturn actif recoit SIGUSR2, qui lui fait relire certificat et cle
#      sans couper les allocations en cours (aucun redemarrage) ; puis
#      APPLIED_FILE recoit l'empreinte qu'install_coturn.sh calcule, pour
#      qu'une relance de l'installation ne redemarre pas coturn.
#   2. nginx actif : « nginx -t » puis « systemctl reload nginx ». nginx lit
#      la lignee elle-meme : il est recharge meme quand coturn echoue.
#
# ERPLIBRE_CALL_ROOT, vide en service, prefixe chaque chemin du systeme :
# les tests y mettent une racine temporaire.
#
# Sortie : une ligne « @@HOOK <action> » par etape. Code de sortie non nul
# quand l'etat est illisible, qu'une copie, le signal ou nginx echoue.

set -uo pipefail

R="${ERPLIBRE_CALL_ROOT:-}"
LINEAGE="erplibre-call"
TLS_DIR="$R/etc/erplibre-call/tls"
STATE_FILE="$R/etc/erplibre-call/state.json"
APPLIED_FILE="$R/etc/erplibre-call/coturn.applied"
RENEWED_LINEAGE="${RENEWED_LINEAGE:-}"
FAILED=0

hook() { echo "@@HOOK $*"; }
warn() { echo "[ERPLIBRE-CALL] $*" >&2; }

# applied_digest <chemin> : copie, au caractere pres, de celle
# d'install_coturn.sh (un test compare les deux textes) : l'empreinte sha256
# de la configuration puis, quand TLS_DIR porte une copie, du certificat et
# de la cle ; une ligne par fichier. APPLIED_FILE ecrit ici est donc celui
# qu'une relance de l'installateur s'attend a trouver.
applied_digest() {
    if [ -e "$TLS_DIR/turn.crt" ] || [ -e "$TLS_DIR/turn.key" ]; then
        sha256sum "$1" "$TLS_DIR/turn.crt" "$TLS_DIR/turn.key"
    else
        sha256sum "$1"
    fi
}

# coturn_record : imprime « <unite> <configuration> » de coturn lus dans
# STATE_FILE, rien quand l'etat n'existe pas ou ne nomme pas coturn. Code
# non nul pour un etat illisible, ou une unite ou un chemin hors de ce que
# l'outil ecrit : les deux finissent dans des commandes lancees en root.
# python3 est la, certbot en depend.
coturn_record() {
    [ -e "$STATE_FILE" ] || return 0
    python3 -I - "$STATE_FILE" <<'EOF'
import json
import re
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as handle:
        services = json.load(handle).get("services") or {}
    record = services.get("coturn")
    if record is None:
        sys.exit(0)
    unit, config = record.get("unit"), record.get("config")
except (OSError, ValueError, AttributeError):
    sys.exit(2)
safe = (
    isinstance(config, str)
    and re.fullmatch(r"(/[A-Za-z0-9._@+-]+)+", config)
    and not {".", ".."} & set(config.split("/"))
)
if unit not in ("coturn", "turnserver") or not safe:
    sys.exit(2)
print(unit, config)
EOF
}

# copy_pair <groupe> : remplace turn.crt et turn.key de TLS_DIR par
# fullchain.pem et privkey.pem de la lignee, root:<groupe> 0640. Chaque copie
# passe par un fichier neuf de mktemp dans TLS_DIR, renomme ensuite : coturn
# ne lit jamais un fichier a moitie ecrit. Une cible en lien symbolique, ou
# qui n'est pas un fichier ordinaire, arrete tout avant la premiere copie :
# le renommage remplacerait le lien sans toucher le fichier vise. Les deux
# renommages suivent les deux copies ; un echec ne laisse aucun temporaire.
copy_pair() {
    local group="$1" name target tmp_crt="" tmp_key="" ok=1
    for name in turn.crt turn.key; do
        target="$TLS_DIR/$name"
        if [ -L "$target" ] || { [ -e "$target" ] && [ ! -f "$target" ]; }; then
            hook "refused $target"
            warn "${target} n'est pas un fichier ordinaire ; rien n'est copie."
            return 1
        fi
    done
    tmp_crt=$(mktemp "$TLS_DIR/.turn.crt.XXXXXX") || return 1
    tmp_key=$(mktemp "$TLS_DIR/.turn.key.XXXXXX") || { rm -f "$tmp_crt"; return 1; }
    cat "$RENEWED_LINEAGE/fullchain.pem" > "$tmp_crt" || ok=0
    cat "$RENEWED_LINEAGE/privkey.pem" > "$tmp_key" || ok=0
    if [ "$ok" = 1 ]; then
        chown "root:${group}" "$tmp_crt" "$tmp_key" || ok=0
    fi
    if [ "$ok" = 1 ]; then
        chmod 0640 "$tmp_crt" "$tmp_key" || ok=0
    fi
    if [ "$ok" = 1 ]; then
        mv -f "$tmp_crt" "$TLS_DIR/turn.crt" && mv -f "$tmp_key" "$TLS_DIR/turn.key" \
            || ok=0
    fi
    rm -f "$tmp_crt" "$tmp_key"
    [ "$ok" = 1 ]
}

# record_applied <empreinte> : ecrit APPLIED_FILE, root 0600, par un fichier
# voisin renomme ; le dossier appartient a root, aucun autre compte n'y pose
# de lien.
record_applied() {
    (
        umask 077
        printf '%s\n' "$1" > "$APPLIED_FILE.erplibre-new"
    ) && mv -f "$APPLIED_FILE.erplibre-new" "$APPLIED_FILE"
}

# coturn_renew : etape 1. APPLIED_FILE n'est reecrit que s'il disait deja
# chargee la paire en place avec la configuration du disque : SIGUSR2 ne
# relit que certificat et cle, et un coturn sur une configuration perimee
# doit rester signale a l'installation, qui le redemarrera.
coturn_renew() {
    local record unit config group before
    if ! record=$(coturn_record); then
        hook "failed state"
        warn "${STATE_FILE} illisible ou hors de ce que l'outil ecrit."
        return 1
    fi
    if [ -z "$record" ]; then
        hook "coturn-skip not-in-state"
        return 0
    fi
    if [ -L "$TLS_DIR" ]; then
        hook "refused $TLS_DIR"
        warn "${TLS_DIR} est un lien symbolique ; rien n'est copie."
        return 1
    fi
    if [ ! -d "$TLS_DIR" ]; then
        hook "coturn-skip no-tls-dir"
        return 0
    fi
    unit=${record%% *}
    config="$R${record#* }"
    group=$(stat -c %g "$TLS_DIR") || return 1
    before=$(applied_digest "$config" 2>/dev/null) || before=""

    if ! copy_pair "$group"; then
        hook "failed copy"
        return 1
    fi
    hook "copied $TLS_DIR/turn.crt $TLS_DIR/turn.key"

    if ! systemctl is-active --quiet "$unit"; then
        hook "coturn-inactive $unit"
        return 0
    fi
    if ! systemctl kill -s SIGUSR2 "$unit"; then
        hook "failed signal $unit"
        return 1
    fi
    hook "signal $unit"

    if [ -n "$before" ] && [ "$(cat "$APPLIED_FILE" 2>/dev/null)" = "$before" ]; then
        record_applied "$(applied_digest "$config")" || { hook "failed applied"; return 1; }
        hook "applied"
    else
        hook "applied-stale"
    fi
}

# nginx_reload : etape 2. Un « nginx -t » en echec ne recharge rien et rend
# son message.
nginx_reload() {
    local out
    if ! systemctl is-active --quiet nginx; then
        hook "nginx-inactive"
        return 0
    fi
    if ! out=$(nginx -t 2>&1); then
        hook "nginx-failed"
        warn "nginx -t : $(printf '%s\n' "$out" | tail -n 1)"
        return 1
    fi
    if ! systemctl reload nginx; then
        hook "nginx-failed"
        return 1
    fi
    hook "nginx-reloaded"
}

main() {
    local name=""
    if [ -n "$RENEWED_LINEAGE" ]; then
        name=$(basename "$RENEWED_LINEAGE")
    fi
    if [ "$name" != "$LINEAGE" ]; then
        hook "skip${name:+ $name}"
        return 0
    fi
    coturn_renew || FAILED=1
    nginx_reload || FAILED=1
    [ "$FAILED" = 0 ]
}

main "$@"
