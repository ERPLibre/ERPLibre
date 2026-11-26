#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Installe, sur l'hôte d'une forge posée par install_forgejo.sh, le minuteur
# systemd qui avance chaque dépôt de travail jusqu'à son miroir, en
# fast-forward seulement (forge_sync.py, à côté de ce script).
#
# Il n'appelle PAS env_var.sh : comme install_forgejo.sh, il doit rester
# utilisable hors d'un checkout. Rejouable : un fichier identique n'est pas
# réécrit, et le minuteur ne redémarre que si quelque chose a changé.
#
# Réglages, tous par variables d'environnement :
#   FORGE_SYNC_ACCOUNT    compte Forgejo qui reçoit le jeton      (requis)
#   FORGE_SYNC_CALENDAR   OnCalendar du minuteur          (défaut : hourly)
#   FORGE_SYNC_NEW_TOKEN  à 1, remplace le jeton existant
#
# Le jeton se crée ICI, par la CLI d'administration de Forgejo, et ne quitte
# jamais l'hôte : il vit dans /etc/erplibre-forge-sync/token (root, 0600) et
# n'atteint le service que par LoadCredential=. Un ancien jeton n'est pas
# révoqué (la CLI ne le sait pas) : l'interface web de la forge le fait.
set -euo pipefail

Red='\033[0;31m'
Green='\033[0;32m'
Color_Off='\033[0m'

ACCOUNT="${FORGE_SYNC_ACCOUNT:-}"
CALENDAR="${FORGE_SYNC_CALENDAR:-hourly}"
NEW_TOKEN="${FORGE_SYNC_NEW_TOKEN:-0}"

BIN=/usr/local/bin/forgejo
CONF=/etc/forgejo/app.ini
LIB=/usr/local/lib/erplibre-forge-sync
ETC=/etc/erplibre-forge-sync
TOKEN="$ETC/token"
ENVFILE="$ETC/environment"
SERVICE=/etc/systemd/system/erplibre-forge-sync.service
TIMER=/etc/systemd/system/erplibre-forge-sync.timer

# Ce qui a changé sur le disque pendant ce passage : le minuteur ne redémarre
# que dans ce cas.
CHANGED=0

say() { echo -e "   $*"; }
die() { echo -e "   ${Red}✗ $*${Color_Off}" >&2; exit 1; }

case "${1:-}" in
    -h|--help) sed -n '5,21p' "$0" | sed 's/^# \?//'; exit 0 ;;
esac

# --- 1. Prérequis ----------------------------------------------------------
src="$(dirname "$0")/forge_sync.py"
[ -f "$src" ] || die "forge_sync.py absent à côté de ce script"
[[ $ACCOUNT =~ ^[A-Za-z0-9][-.A-Za-z0-9_]{0,39}$ ]] \
    || die "FORGE_SYNC_ACCOUNT invalide ou absent"
[[ $CALENDAR =~ ^[-A-Za-z0-9\ :*/,.~]+$ ]] \
    || die "FORGE_SYNC_CALENDAR invalide"
[ -x "$BIN" ] && sudo test -f "$CONF" \
    || die "Forgejo installé par ERPLibre attendu ($BIN, $CONF)"

# --- 2. Ce que la forge déclare dans app.ini ------------------------------
# « ini SECTION CLE » : la valeur de CLE dans [SECTION], ou au niveau
# supérieur pour une section vide. app.ini n'est lisible que par root et le
# compte de Forgejo, d'où « sudo awk ».
ini() {
    sudo awk -v s="$1" -v k="$2" '
        /^[[:space:]]*\[/ {
            sec = $0; gsub(/^[[:space:]]*\[|\][[:space:]]*$/, "", sec); next
        }
        sec == s {
            line = $0; sub(/^[[:space:]]*/, "", line)
            n = index(line, "=")
            if (n == 0) next
            key = substr(line, 1, n - 1); sub(/[[:space:]]+$/, "", key)
            if (key != k) next
            val = substr(line, n + 1); gsub(/^[[:space:]]+|[[:space:]]+$/, "", val)
            print val; exit
        }' "$CONF"
}
RUN_USER="$(ini "" RUN_USER)"; RUN_USER="${RUN_USER:-git}"
PROTOCOL="$(ini server PROTOCOL)"
HTTP_PORT="$(ini server HTTP_PORT)"; HTTP_PORT="${HTTP_PORT:-3000}"
HTTP_ADDR="$(ini server HTTP_ADDR)"
ROOT="$(ini repository ROOT)"
case "$PROTOCOL" in
    ""|http) ;;
    *) die "[server] PROTOCOL=$PROTOCOL : seul http local est pris en charge" ;;
esac
case "$HTTP_ADDR" in
    ""|0.0.0.0|::|127.0.0.1|localhost) ;;
    *) die "[server] HTTP_ADDR=$HTTP_ADDR : la forge doit écouter en local" ;;
esac
[[ $HTTP_PORT =~ ^[0-9]{1,5}$ ]] || die "[server] HTTP_PORT invalide"
[[ $RUN_USER =~ ^[a-z_][-a-z0-9_]{0,31}$ ]] || die "RUN_USER invalide"
case "$ROOT" in
    /*) ;;
    *) die "[repository] ROOT doit être un chemin absolu" ;;
esac
# L'unité pose ProtectHome=true : /home, /root et /run/user y sont vides.
# Des dépôts rangés là y seraient tous « depot_absent », une passe qui
# réussit sans jamais rien avancer.
case "$ROOT" in
    /home|/home/*|/root|/root/*|/run/user|/run/user/*)
        die "[repository] ROOT=$ROOT : invisible du service (ProtectHome)," \
            "les dépôts doivent vivre hors de /home, /root et /run/user" ;;
esac

# --- 3. Le script ----------------------------------------------------------
sudo install -d -m 0755 -o root -g root "$LIB"
if ! sudo cmp -s "$src" "$LIB/forge_sync.py"; then
    sudo install -m 0755 -o root -g root "$src" "$LIB/forge_sync.py"
    CHANGED=1
    say "script posé : $LIB/forge_sync.py"
fi
sudo install -d -m 0755 -o root -g root "$ETC"

# --- 4. Le jeton -----------------------------------------------------------
# Un compte différent de celui du fichier d'environnement exige un jeton
# neuf : l'en-tête de git nomme le compte, qui doit être celui du jeton.
ancien=""
if sudo test -f "$ENVFILE"; then
    ancien="$(sudo sed -n 's/^FORGE_SYNC_ACCOUNT=//p' "$ENVFILE")"
fi
if ! sudo test -s "$TOKEN" || [ "$NEW_TOKEN" = 1 ] \
        || [ "$ancien" != "$ACCOUNT" ]; then
    # La valeur ne vit que dans des variables du shell et des builtins :
    # jamais dans une ligne de commande, jamais affichée. pipefail fait
    # échouer la création au lieu d'enregistrer un message d'erreur comme
    # jeton, et le motif hexadécimal le vérifie.
    sudo bash -c 'set -euo pipefail; umask 077; cd /
        out=$(runuser -u "$1" -- "$2" admin user generate-access-token \
            --username "$3" --token-name "$4" --scopes write:repository \
            --raw --config "$5")
        tok=$(printf %s "$out" | tail -n 1)
        if ! [[ $tok =~ ^[0-9a-f]{40}$ ]]; then
            echo "no token returned" >&2; exit 3
        fi
        printf %s "$tok" > "$6.tmp" && mv "$6.tmp" "$6"' \
        _ "$RUN_USER" "$BIN" "$ACCOUNT" \
        "erplibre-forge-sync-$(date +%Y%m%d-%H%M%S)" "$CONF" "$TOKEN" \
        || die "création du jeton impossible pour $ACCOUNT"
    sudo chown root:root "$TOKEN"
    sudo chmod 0600 "$TOKEN"
    CHANGED=1
    say "jeton créé pour $ACCOUNT"
fi

# --- 5. L'environnement, sans secret ---------------------------------------
# « installer » écrit un fichier temporaire, le compare, puis le pose en
# 0644 s'il diffère.
installer() {
    local tmp="$1" cible="$2"
    if ! sudo cmp -s "$tmp" "$cible" 2>/dev/null; then
        sudo install -m 0644 -o root -g root "$tmp" "$cible"
        CHANGED=1
        say "écrit : $cible"
    fi
    rm -f "$tmp"
}
tmp=$(mktemp)
printf 'FORGE_SYNC_URL=http://127.0.0.1:%s\nFORGE_SYNC_REPOS=%s\nFORGE_SYNC_ACCOUNT=%s\n' \
    "$HTTP_PORT" "$ROOT" "$ACCOUNT" > "$tmp"
installer "$tmp" "$ENVFILE"

# --- 6. Les unités ---------------------------------------------------------
# ProtectSystem=strict rend /var/lib/forgejo en lecture seule pour ce
# service : il lit les dépôts nus sur le disque et n'écrit qu'en poussant
# par la forge. Seul son StateDirectory lui est ouvert en écriture.
# After= ordonne sans démarrer : une passe pendant que Forgejo est arrêté
# exprès note ses pushes refusés, au lieu de relancer la forge comme le
# ferait Wants=.
unites=0
tmp=$(mktemp)
cat > "$tmp" <<UNITEOF
[Unit]
Description=ERPLibre: fast-forward the forge repositories from their mirrors
After=forgejo.service
ConditionPathExists=/etc/erplibre-forge-sync/config.json
ConditionPathExists=/etc/erplibre-forge-sync/token

[Service]
Type=oneshot
User=$RUN_USER
Group=$RUN_USER
EnvironmentFile=/etc/erplibre-forge-sync/environment
LoadCredential=token:/etc/erplibre-forge-sync/token
ExecStart=/usr/bin/python3 -I /usr/local/lib/erplibre-forge-sync/forge_sync.py passe
StateDirectory=erplibre-forge-sync
StateDirectoryMode=0755
TimeoutStartSec=2h
Nice=10
IOSchedulingClass=idle
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
NoNewPrivileges=true
UNITEOF
avant=$CHANGED; installer "$tmp" "$SERVICE"; [ "$CHANGED" = "$avant" ] || unites=1

tmp=$(mktemp)
cat > "$tmp" <<UNITEOF
[Unit]
Description=ERPLibre: fast-forward the forge repositories, periodically

[Timer]
OnCalendar=$CALENDAR
RandomizedDelaySec=300
Persistent=true

[Install]
WantedBy=timers.target
UNITEOF
avant=$CHANGED; installer "$tmp" "$TIMER"; [ "$CHANGED" = "$avant" ] || unites=1
[ "$unites" = 0 ] || sudo systemctl daemon-reload

# --- 7. Le minuteur --------------------------------------------------------
sudo systemctl enable --now erplibre-forge-sync.timer >/dev/null 2>&1 \
    || die "le minuteur refuse de démarrer : sudo journalctl -u erplibre-forge-sync"
if [ "$CHANGED" = 1 ]; then
    sudo systemctl restart erplibre-forge-sync.timer
fi

# --- 8. Résumé -------------------------------------------------------------
say "${Green}minuteur prêt${Color_Off} : $CALENDAR, compte $ACCOUNT"
systemctl list-timers erplibre-forge-sync.timer --no-pager || true
say "  une passe  : sudo systemctl start erplibre-forge-sync.service"
say "  journal    : sudo journalctl -u erplibre-forge-sync"
say "  désactiver : sudo systemctl disable --now erplibre-forge-sync.timer"
