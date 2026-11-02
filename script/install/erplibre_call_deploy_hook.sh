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
#   1. coturn inscrit dans l'etat avec un certificat Let's Encrypt
#      (settings.tls) et TLS_DIR present : fullchain.pem et privkey.pem
#      deviennent turn.crt et turn.key (voir copy_pair) ;
#      coturn actif recoit SIGUSR2, qui lui fait relire certificat et cle
#      sans couper les allocations en cours (aucun redemarrage) : par
#      « systemctl kill » pour un coturn de paquet, par le moteur pour un
#      coturn en conteneur (voir container_engine) ; puis APPLIED_FILE
#      recoit l'empreinte qu'install_coturn.sh calcule, pour qu'une relance
#      de l'installation ne redemarre pas coturn.
#   2. nginx actif : « nginx -t » puis « systemctl reload nginx ». nginx lit
#      la lignee elle-meme : il est recharge meme quand coturn echoue.
#
# ERPLIBRE_CALL_ROOT, vide en service, prefixe chaque chemin du systeme :
# les tests y mettent une racine temporaire.
#
# Sortie : une ligne « @@HOOK <action> » par etape. Code de sortie 2 quand
# l'etat est illisible ou hors de ce que l'outil ecrit (aucune commande de
# coturn n'est lancee, nginx est recharge quand meme), 1 quand une copie,
# le signal ou nginx echoue.

set -uo pipefail

R="${ERPLIBRE_CALL_ROOT:-}"
LINEAGE="erplibre-call"
TLS_DIR="$R/etc/erplibre-call/tls"
STATE_FILE="$R/etc/erplibre-call/state.json"
APPLIED_FILE="$R/etc/erplibre-call/coturn.applied"
# Empreinte en attente qu'install_coturn.sh ecrit en conteneurs, et que
# l'installation fait passer en APPLIED_FILE une fois le conteneur en
# marche.
PENDING_FILE="$APPLIED_FILE.erplibre-pending"
RENEWED_LINEAGE="${RENEWED_LINEAGE:-}"
FAILED=0
REFUSED=0

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

# coturn_record : imprime, pour coturn lu dans STATE_FILE,
# « <unite> <configuration> » par paquets, ou « container <moteur> <nom>
# <0|1> <compte> <uid> <configuration> » en conteneurs (1 : rootless ;
# compte et uid de la session rootless, « - » en root) ; rien quand l'etat
# n'existe pas ou ne nomme pas coturn, « not-letsencrypt » quand coturn
# sert un autre certificat (fourni, ou aucun) : la paire en place n'est pas
# celle de la lignee. Code 2 pour un etat illisible, une methode qui ne va
# pas avec la version, ou une valeur hors de ce que l'outil ecrit : unite,
# chemin, moteur, nom, compte et uid finissent dans des commandes lancees
# en root. En conteneurs, tout l'etat passe d'abord les regles de
# container_block_problem (script/todo/call_infra_container.py), recopiees
# ici en stdlib : un test fait juger les deux sur la meme liste d'etats.
# python3 est la, certbot en depend.
coturn_record() {
    [ -e "$STATE_FILE" ] || return 0
    python3 -I - "$STATE_FILE" <<'EOF'
import json
import re
import sys

ENGINES = ("docker", "podman")
COMPOSE_PROVIDERS = {
    "docker": (("docker", "compose"), ("docker-compose",)),
    "podman": (("podman-compose",),),
}
CONTAINERS = {"coturn": "erplibre-call-coturn", "ntfy": "erplibre-call-ntfy"}
COMPOSE_FILE = "/etc/erplibre-call/compose.yml"
PROJECT = "erplibre-call"
ACCOUNT_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}\Z")
MAX_ID = 2**31 - 1
METHODS = ("packages", "container")
CONTAINER_VERSION = 2


def valid_id(value):
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 1 <= value <= MAX_ID
    )


def valid_account(value):
    return (
        isinstance(value, str)
        and bool(ACCOUNT_RE.match(value))
        and value != "root"
    )


def block_valid(block):
    if not isinstance(block, dict) or block.get("engine") not in ENGINES:
        return False
    engine, rootless = block["engine"], block.get("rootless")
    if not isinstance(rootless, bool) or (rootless and engine != "podman"):
        return False
    if rootless:
        if not valid_account(block.get("account")):
            return False
        if not valid_id(block.get("uid")):
            return False
    elif block.get("account") is not None or block.get("uid") is not None:
        return False
    compose = block.get("compose")
    if not isinstance(compose, (list, tuple)):
        return False
    return (
        tuple(compose) in COMPOSE_PROVIDERS[engine]
        and block.get("compose_file", COMPOSE_FILE) == COMPOSE_FILE
        and block.get("project", PROJECT) == PROJECT
    )


def state_valid(state):
    if not block_valid(state.get("container")):
        return False
    services = state.get("services", {})
    if not isinstance(services, dict):
        return False
    for svc, record in services.items():
        if svc not in CONTAINERS or not isinstance(record, dict):
            return False
        if record.get("container") != CONTAINERS[svc]:
            return False
        if not valid_account(record.get("account")):
            return False
        if not (valid_id(record.get("uid")) and valid_id(record.get("gid"))):
            return False
    return True


try:
    with open(sys.argv[1], encoding="utf-8") as handle:
        state = json.load(handle)
    method = state.get("method", "packages")
    if method not in METHODS or (method == "container") != (
        state.get("version") == CONTAINER_VERSION
    ):
        sys.exit(2)
    if method == "container" and not state_valid(state):
        sys.exit(2)
    services = state.get("services") or {}
    record = services.get("coturn")
    if record is None:
        sys.exit(0)
    unit, config = record.get("unit"), record.get("config")
    settings = record.get("settings") or {}
    tls = settings.get("tls")
except (OSError, ValueError, AttributeError):
    sys.exit(2)
if tls != "letsencrypt":
    print("not-letsencrypt")
    sys.exit(0)
safe = (
    isinstance(config, str)
    and re.fullmatch(r"(/[A-Za-z0-9._@+-]+)+", config)
    and not {".", ".."} & set(config.split("/"))
)
if not safe:
    sys.exit(2)
if method == "container":
    block = state["container"]
    print(
        "container",
        block["engine"],
        CONTAINERS["coturn"],
        1 if block["rootless"] else 0,
        block["account"] if block["rootless"] else "-",
        block["uid"] if block["rootless"] else "-",
        config,
    )
    sys.exit(0)
if unit not in ("coturn", "turnserver"):
    sys.exit(2)
print(unit, config)
EOF
}

# container_engine <argument>... : lance le moteur de l'etat avec ces
# arguments, directement en root ; en rootless, depuis root, sous le compte
# rootless et dans sa session (XDG_RUNTIME_DIR, bus D-Bus), ou Podman
# trouve les conteneurs de ce compte, depuis « / » : Podman rootless
# s'arrete quand le compte ne peut pas ouvrir le dossier courant, celui de
# qui lance certbot. Le meme prefixe que rootless_prefix de
# call_infra_container.py, qu'un test garde egal. Lit ENGINE, ROOTLESS,
# ACCOUNT et RUID, que coturn_renew pose a partir de coturn_record, donc
# deja valides.
container_engine() {
    if [ "$ROOTLESS" = 1 ]; then
        runuser -u "$ACCOUNT" -- env -C / "XDG_RUNTIME_DIR=/run/user/$RUID" \
            "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$RUID/bus" \
            "$ENGINE" "$@"
    else
        "$ENGINE" "$@"
    fi
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

# record_applied <empreinte> [fichier] : ecrit APPLIED_FILE (ou fichier),
# root 0600, par un fichier voisin renomme ; le dossier appartient a root,
# aucun autre compte n'y pose de lien.
record_applied() {
    local target="${2:-$APPLIED_FILE}"
    (
        umask 077
        printf '%s\n' "$1" > "$target.erplibre-new"
    ) && mv -f "$target.erplibre-new" "$target"
}

# coturn_renew : etape 1. APPLIED_FILE n'est reecrit que s'il disait deja
# chargee la paire en place avec la configuration du disque : SIGUSR2 ne
# relit que certificat et cle, et un coturn sur une configuration perimee
# doit rester signale a l'installation, qui le redemarrera. PENDING_FILE
# suit la meme regle : quand une installation en conteneurs vient de
# recreer coturn sur la configuration du disque, l'empreinte en attente
# dit l'ancienne paire, et c'est la nouvelle que coturn sert apres le
# signal ; l'installation fait ensuite passer la bonne. En conteneurs,
# « inspect » dit si le conteneur tourne : arrete ou absent, il lira la
# paire copiee a son prochain demarrage. Code 2 pour un etat refuse, avant
# toute commande de coturn.
coturn_renew() {
    local record kind=packages unit config group before
    if ! record=$(coturn_record); then
        hook "failed state"
        warn "${STATE_FILE} illisible ou hors de ce que l'outil ecrit."
        return 2
    fi
    if [ -z "$record" ]; then
        hook "coturn-skip not-in-state"
        return 0
    fi
    if [ "$record" = not-letsencrypt ]; then
        hook "coturn-skip not-letsencrypt"
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
    if [ "${record%% *}" = container ]; then
        # unit porte ici le nom du conteneur, celui des marqueurs.
        read -r kind ENGINE unit ROOTLESS ACCOUNT RUID config <<<"$record"
        config="$R$config"
    else
        unit=${record%% *}
        config="$R${record#* }"
    fi
    group=$(stat -c %g "$TLS_DIR") || return 1
    before=$(applied_digest "$config" 2>/dev/null) || before=""

    if ! copy_pair "$group"; then
        hook "failed copy"
        return 1
    fi
    hook "copied $TLS_DIR/turn.crt $TLS_DIR/turn.key"

    if [ "$kind" = container ]; then
        if [ "$(container_engine inspect -f '{{.State.Running}}' "$unit" \
            2>/dev/null)" != true ]; then
            hook "coturn-inactive $unit"
            return 0
        fi
        if ! container_engine kill --signal SIGUSR2 "$unit"; then
            hook "failed signal $unit"
            return 1
        fi
    else
        if ! systemctl is-active --quiet "$unit"; then
            hook "coturn-inactive $unit"
            return 0
        fi
        if ! systemctl kill -s SIGUSR2 "$unit"; then
            hook "failed signal $unit"
            return 1
        fi
    fi
    hook "signal $unit"

    if [ -n "$before" ] && [ "$(cat "$PENDING_FILE" 2>/dev/null)" = "$before" ]; then
        record_applied "$(applied_digest "$config")" "$PENDING_FILE" \
            || { hook "failed pending"; return 1; }
        hook "pending"
    fi
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
    coturn_renew
    case $? in
        0) ;;
        2) REFUSED=1 ;;
        *) FAILED=1 ;;
    esac
    nginx_reload || FAILED=1
    [ "$REFUSED" = 0 ] || return 2
    [ "$FAILED" = 0 ]
}

main "$@"
