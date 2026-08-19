#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Installe Forgejo — https://forgejo.org — depuis le binaire statique officiel
# publié sur https://codeberg.org/forgejo/forgejo.
#
# Le binaire est statique et sans dépendance : le même fichier sert Debian,
# Ubuntu, AlmaLinux, Rocky, openSUSE et Arch. Ce script ne touche donc à AUCUN
# gestionnaire de paquets — c'est ce qui le rend portable sur les plateformes
# ERPLibre sans une branche par distribution.
#
# Il n'appelle PAS env_var.sh, à la différence des scripts d'installation
# ERPLibre : Forgejo ne dépend ni du dépôt ni de son venv, et le script doit
# rester utilisable hors d'un checkout.
#
# Réglages, tous par variables d'environnement :
#   FORGEJO_VERSION        version à poser (défaut : la dernière publiée)
#   FORGEJO_HTTP_PORT      port web                       (défaut : 3000)
#   FORGEJO_SSH_PORT       port SSH interne de Forgejo    (défaut : 2222)
#   FORGEJO_ADMIN_USER     compte administrateur créé  (défaut : erplibre)
#   FORGEJO_ADMIN_PASSWORD son mot de passe               (défaut : erplibre)
#   FORGEJO_ADMIN_EMAIL    son courriel     (défaut : admin@erplibre.local)
#   FORGEJO_USER           compte système propriétaire    (défaut : git)
#   FORGEJO_SKIP_ADMIN     à 1, ne crée aucun compte (installateur web)
set -euo pipefail

Red='\033[0;31m'
Green='\033[0;32m'
Yellow='\033[0;33m'
Color_Off='\033[0m'

VERSION="${FORGEJO_VERSION:-}"
HTTP_PORT="${FORGEJO_HTTP_PORT:-3000}"
SSH_PORT="${FORGEJO_SSH_PORT:-2222}"
# « admin » est REFUSÉ par Forgejo — « CreateUser: name is reserved », mesuré.
# La liste des noms réservés couvre aussi api, assets, avatars, explore, user…
ADMIN_USER="${FORGEJO_ADMIN_USER:-erplibre}"
ADMIN_PASSWORD="${FORGEJO_ADMIN_PASSWORD:-erplibre}"
ADMIN_EMAIL="${FORGEJO_ADMIN_EMAIL:-admin@erplibre.local}"
RUN_USER="${FORGEJO_USER:-git}"
SKIP_ADMIN="${FORGEJO_SKIP_ADMIN:-0}"

BIN=/usr/local/bin/forgejo
CONF_DIR=/etc/forgejo
CONF="$CONF_DIR/app.ini"
DATA=/var/lib/forgejo
UNIT=/etc/systemd/system/forgejo.service
API=https://codeberg.org/api/v1/repos/forgejo/forgejo/releases
DL=https://codeberg.org/forgejo/forgejo/releases/download

usage() {
    sed -n '5,26p' "$0" | sed 's/^# \?//'
    exit 0
}
case "${1:-}" in
    -h|--help) usage ;;
esac

say() { echo -e "   $*"; }
die() { echo -e "   ${Red}✗ $*${Color_Off}" >&2; exit 1; }

# --- 1. Architecture -------------------------------------------------------
# Forgejo publie amd64, arm64 et arm-6. PAS de s390x : sur cette architecture
# il faudrait le bâtir depuis les sources en Go, ce que ce script ne fait pas —
# il le dit plutôt que de télécharger un binaire qui ne s'exécutera pas.
case "$(uname -m)" in
    x86_64)         ARCH=amd64 ;;
    aarch64|arm64)  ARCH=arm64 ;;
    armv6l|armv7l)  ARCH=arm-6 ;;
    *) die "Forgejo ne publie pas de binaire pour $(uname -m)" \
           "(amd64, arm64 et arm-6 seulement)." ;;
esac

# --- 2. Version ------------------------------------------------------------
if [ -z "$VERSION" ]; then
    # La liste des versions est en JSON : on la lit avec python3, présent dans
    # toutes les images cloud visées. Sans lui, on retombe sur grep — mieux
    # qu'un abandon, et le motif est celui d'un champ JSON, pas d'une page web.
    if command -v python3 >/dev/null 2>&1; then
        VERSION=$(curl -fsSL --max-time 30 "$API?limit=1" 2>/dev/null \
            | python3 -c 'import json,sys
try:
    print(json.load(sys.stdin)[0]["tag_name"].lstrip("v"))
except Exception:
    pass' || true)
    else
        VERSION=$(curl -fsSL --max-time 30 "$API?limit=1" 2>/dev/null \
            | grep -o '"tag_name":"v[^"]*"' | head -1 \
            | sed 's/.*"v//;s/"//' || true)
    fi
fi
[ -n "$VERSION" ] || die "Version de Forgejo introuvable (réseau ? $API)"
say "Forgejo $VERSION pour $ARCH"

# --- 3. Déjà posé ? --------------------------------------------------------
# Rejouer une installation est le cas normal. Comparer la version évite de
# retélécharger 34 Mo pour rien, et de redémarrer un service qui va bien.
if [ -x "$BIN" ] && "$BIN" --version 2>/dev/null | grep -q "version $VERSION"; then
    say "${Green}binaire déjà en version $VERSION, téléchargement évité${Color_Off}"
else
    # L'archive .xz pèse 34 Mo contre 114 Mo pour le binaire nu. On la prend
    # quand xz est là, sans jamais l'installer : le binaire nu est le repli.
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' EXIT
    if command -v xz >/dev/null 2>&1; then
        asset="forgejo-$VERSION-linux-$ARCH.xz"
    else
        asset="forgejo-$VERSION-linux-$ARCH"
    fi
    say "téléchargement de $asset"
    curl -fsSL --retry 3 --max-time 900 "$DL/v$VERSION/$asset" \
        -o "$tmp/$asset" || die "téléchargement impossible : $DL/v$VERSION/$asset"
    # Somme de contrôle publiée à côté du fichier : une archive tronquée par une
    # coupure réseau donne un binaire qui ne s'exécute pas, et l'erreur arrive
    # alors dix étapes plus loin.
    if curl -fsSL --max-time 60 "$DL/v$VERSION/$asset.sha256" \
            -o "$tmp/$asset.sha256" 2>/dev/null; then
        (cd "$tmp" && sha256sum -c "$asset.sha256" >/dev/null) \
            || die "somme de contrôle invalide pour $asset"
        say "somme de contrôle vérifiée"
    else
        say "${Yellow}⚠ somme de contrôle indisponible, non vérifiée${Color_Off}"
    fi
    case "$asset" in
        *.xz) xz -d "$tmp/$asset"; src="$tmp/${asset%.xz}" ;;
        *)    src="$tmp/$asset" ;;
    esac
    chmod +x "$src"
    sudo install -m 0755 "$src" "$BIN"
    say "${Green}binaire posé : $BIN${Color_Off}"
    rm -rf "$tmp"
    trap - EXIT
fi

# --- 4. Compte système et répertoires --------------------------------------
if ! id "$RUN_USER" >/dev/null 2>&1; then
    sudo useradd --system --create-home --home-dir "/home/$RUN_USER" \
        --shell /bin/bash --comment "Forgejo" "$RUN_USER"
    say "compte système créé : $RUN_USER"
fi
sudo mkdir -p "$DATA"/{custom,data,log} "$CONF_DIR"
sudo chown -R "$RUN_USER:$RUN_USER" "$DATA"
sudo chmod 750 "$DATA"
# Le fichier de configuration appartient à root et se LIT par le groupe : le
# service en a besoin, et Forgejo y écrit ses secrets au premier démarrage si
# on ne les pose pas soi-même — ce que fait l'étape suivante.
sudo chown root:"$RUN_USER" "$CONF_DIR"
sudo chmod 770 "$CONF_DIR"

# --- 5. Configuration ------------------------------------------------------
# JAMAIS réécrite si elle existe : elle porte les secrets, et un utilisateur a
# pu l'ajuster. C'est aussi ce qui rend ce script rejouable.
# « sudo test », et non « [ -f ] » : /etc/forgejo appartient à root:git en 770,
# donc l'utilisateur qui lance le script ne peut même pas y statuer un fichier.
# Le test échouait toujours, et CHAQUE passage réécrivait la configuration avec
# des secrets neufs — ce qui invalide les sessions et les jetons existants.
if sudo test -f "$CONF"; then
    say "configuration conservée : $CONF"
else
    host=$(hostname -I 2>/dev/null | awk '{print $1}')
    [ -n "$host" ] || host=localhost
    # Les QUATRE secrets, et pas seulement les deux évidents. Vécu : sans
    # « oauth2.JWT_SECRET », Forgejo tente de l'écrire dans app.ini au
    # démarrage, n'y arrive pas — le fichier appartient à root — et s'arrête
    # sur « [F] save oauth2.JWT_SECRET failed ». Le service redémarrait en
    # boucle, 25 fois, sans jamais écouter le port.
    #
    # Les poser ici garde app.ini NON inscriptible par le service : c'est la
    # bonne posture, et ça évite un fichier de configuration qui se réécrit
    # tout seul.
    secret=$("$BIN" generate secret SECRET_KEY)
    token=$("$BIN" generate secret INTERNAL_TOKEN)
    jwt=$("$BIN" generate secret JWT_SECRET)
    lfs_jwt=$("$BIN" generate secret JWT_SECRET)
    # « INSTALL_LOCK = true » verrouille l'installateur web : la machine est
    # utilisable sans passer par un formulaire, ce qui est tout l'intérêt d'une
    # option cochée au déploiement. SQLite, pour ne pas disputer PostgreSQL à
    # Odoo, qui vit sur la même VM.
    sudo tee "$CONF" >/dev/null <<CONFEOF
APP_NAME = ERPLibre Forgejo
RUN_USER = $RUN_USER
RUN_MODE = prod
WORK_PATH = $DATA

[server]
PROTOCOL = http
DOMAIN = $host
HTTP_PORT = $HTTP_PORT
ROOT_URL = http://$host:$HTTP_PORT/
APP_DATA_PATH = $DATA/data
DISABLE_SSH = false
START_SSH_SERVER = true
SSH_DOMAIN = $host
SSH_PORT = $SSH_PORT
SSH_LISTEN_PORT = $SSH_PORT
LFS_START_SERVER = true
LFS_JWT_SECRET = $lfs_jwt

[database]
DB_TYPE = sqlite3
PATH = $DATA/data/forgejo.db

[repository]
ROOT = $DATA/data/forgejo-repositories

[security]
INSTALL_LOCK = true
PASSWORD_COMPLEXITY = off
SECRET_KEY = $secret
INTERNAL_TOKEN = $token

[oauth2]
JWT_SECRET = $jwt

[service]
DISABLE_REGISTRATION = false
REQUIRE_SIGNIN_VIEW = false

[lfs]
PATH = $DATA/data/lfs

[log]
ROOT_PATH = $DATA/log
LEVEL = info
CONFEOF
    sudo chown root:"$RUN_USER" "$CONF"
    sudo chmod 640 "$CONF"
    say "${Green}configuration écrite : $CONF${Color_Off}"
fi

# --- 6. Service ------------------------------------------------------------
sudo tee "$UNIT" >/dev/null <<UNITEOF
[Unit]
Description=Forgejo (Beyond coding. We forge.)
After=network.target network-online.target

[Service]
Type=simple
User=$RUN_USER
Group=$RUN_USER
WorkingDirectory=$DATA
ExecStart=$BIN web --config $CONF
Restart=always
RestartSec=5
Environment=USER=$RUN_USER HOME=/home/$RUN_USER GITEA_WORK_DIR=$DATA

[Install]
WantedBy=multi-user.target
UNITEOF
sudo systemctl daemon-reload
sudo systemctl enable --now forgejo.service >/dev/null 2>&1 \
    || die "le service refuse de démarrer : sudo journalctl -u forgejo -n 40"

# --- 7. Attendre qu'il RÉPONDE --------------------------------------------
# Une requête HTTP, pas un « systemctl is-active » : le service est « active »
# bien avant d'écouter, et « activating » en boucle de redémarrage ressemble à
# un démarrage en cours. /api/v1/version prouve que l'application SERT — la
# création du compte administrateur qui suit a besoin de la base migrée.
#
# Et surtout pas « exec 3<>/dev/tcp/... » : « exec » est un builtin spécial, et
# une redirection qui échoue termine le shell. Le script mourait donc en
# silence, au premier tour de la boucle, code 1 sans un mot — vécu.
ready=0
for i in $(seq 1 60); do
    if curl -fsS -o /dev/null --max-time 3 \
            "http://127.0.0.1:$HTTP_PORT/api/v1/version"; then
        ready=1
        break
    fi
    sleep 2
done
[ "$ready" = 1 ] || die "aucune réponse sur le port $HTTP_PORT après 120 s" \
    "(sudo journalctl -u forgejo -n 40)"

# --- 8. Compte administrateur ---------------------------------------------
# Créé seulement s'il n'y a AUCUN compte : rejouer le script ne doit pas
# échouer sur « user already exists », ni écraser un mot de passe choisi.
if [ "$SKIP_ADMIN" = 1 ]; then
    say "aucun compte créé (FORGEJO_SKIP_ADMIN=1)"
elif sudo -u "$RUN_USER" "$BIN" admin user list --config "$CONF" 2>/dev/null \
        | tail -n +2 | grep -q .; then
    say "comptes déjà présents, administrateur non recréé"
else
    sudo -u "$RUN_USER" "$BIN" admin user create --admin \
        --username "$ADMIN_USER" --password "$ADMIN_PASSWORD" \
        --email "$ADMIN_EMAIL" --must-change-password=false \
        --config "$CONF" >/dev/null \
        || die "création de l'administrateur impossible"
    say "${Green}administrateur créé : $ADMIN_USER / $ADMIN_PASSWORD${Color_Off}"
fi

# --- 9. Résumé -------------------------------------------------------------
host=$(hostname -I 2>/dev/null | awk '{print $1}')
[ -n "$host" ] || host=localhost
version=$("$BIN" --version 2>/dev/null | head -1)
say "${Green}Forgejo prêt${Color_Off} : http://$host:$HTTP_PORT/"
say "  $version"
say "  git par SSH : port $SSH_PORT (serveur interne de Forgejo)"
say "  service     : sudo systemctl status forgejo"
say "  journal     : sudo journalctl -u forgejo -f"
