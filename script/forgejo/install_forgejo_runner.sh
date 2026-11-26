#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Installe forgejo-runner — https://code.forgejo.org/forgejo/runner — en mode
# HÔTE, sans Docker, à côté d'une forge posée par install_forgejo.sh, et
# l'enregistre auprès d'elle. Les jobs tournent sous un compte système dédié,
# sans conteneur : ce mode convient à une forge privée et jetable dont les
# seuls auteurs de pull requests sont ses opérateurs.
#
# Le binaire est statique, et env_var.sh n'est pas appelé. La somme de
# contrôle publiée est OBLIGATOIRE. Le gestionnaire de paquets du système
# (apt-get, dnf, zypper ou pacman) ne sert qu'aux outils dont les jobs ont
# besoin — make, psql, openssl, git —, installés seulement s'ils manquent.
#
# app.ini s'édite clé par clé (lib_app_ini.sh) : [actions] ENABLED = true, et
# [repository] DEFAULT_REPO_UNITS sans « repo.actions », pour que seul un
# dépôt dont on active Actions exprès lance des jobs sur cet hôte. Ce réglage
# ne vaut que pour les dépôts créés ensuite.
#
# Réglages, tous par variables d'environnement :
#   FORGEJO_RUNNER_VERSION   version à poser (défaut : la dernière publiée)
#   FORGEJO_RUNNER_NAME      nom du runner sur la forge (défaut : <hôte>-host)
#   FORGEJO_RUNNER_LABEL     étiquette des jobs, « runs-on: »
#                            (défaut : erplibre-host ; la config porte
#                            « <étiquette>:host »)
#   FORGEJO_RUNNER_USER      compte système du démon et des jobs
#                            (défaut : forgejo-runner)
#   FORGEJO_RUNNER_SCOPE     portée « propriétaire[/dépôt] »
#                            (défaut : vide, toute l'instance)
#   FORGEJO_RUNNER_CAPACITY  jobs à la fois : 1 seulement (ci_venv.sh
#                            élague des venvs partagés qu'un job
#                            concurrent utiliserait encore)
#   FORGEJO_RUNNER_UNITS     DEFAULT_REPO_UNITS écrit dans app.ini (défaut :
#                            les unités usuelles sans repo.actions ; vide :
#                            la clé n'est pas touchée)
#   FORGEJO_RUNNER_PACKAGES  paquets que les jobs demandent à l'hôte, séparés
#                            par des espaces (défaut : make, le client
#                            PostgreSQL, openssl et git, sous leur nom pour
#                            le gestionnaire trouvé ; vide : aucun paquet)
#   FORGEJO_HTTP_PORT        port local de la forge (défaut : 3000)
#   FORGEJO_USER             compte système de Forgejo (défaut : git)
# Rejouer le script est sûr : le secret, l'enregistrement, la configuration
# et l'unité sont repris tels quels, et chaque service ne redémarre que si
# ce qui le concerne a changé, ou que le runner actif exécute encore un
# binaire remplacé depuis.

# --- 0. Fonctions sans effet ----------------------------------------------
# Définies AVANT tout le reste : sourcé avec EL_RUNNER_LIB_ONLY=1, le script
# s'arrête après elles, ce qui permet de les éprouver seules.

# Vrai pour un secret d'enregistrement valide : 40 hexadécimaux minuscules,
# la forme qu'attend « forgejo-cli actions register ».
secret_valide() {
    [[ "${1:-}" =~ ^[0-9a-f]{40}$ ]]
}

# « config_runner URL UUID SECRET ETIQUETTE CAPACITE HOME » : la
# configuration YAML du démon, en style bloc. uuid et token sont entre
# guillemets : un secret fait de chiffres seuls, ou de chiffres et d'un
# « e », se lirait sinon comme un nombre. Le secret ne passe par aucune
# ligne de commande : cat le reçoit par le document en ligne.
config_runner() {
    local url="$1" uuid="$2" secret="$3" etiquette="$4" capacite="$5"
    local home="$6"
    cat <<CONFEOF
log:
  level: info
runner:
  capacity: $capacite
  timeout: 2h
  envs:
    EL_CI_CACHE: $home/cache
  labels:
    - "$etiquette:host"
cache:
  enabled: false
host:
  workdir_parent: $home/work
server:
  connections:
    forgejo:
      url: "$url"
      uuid: "$uuid"
      token: "$secret"
CONFEOF
}

# « apres » quand « forgejo-cli actions register --help » liste --config (les
# drapeaux de configuration suivent alors « register »), « avant » sinon (ils
# précèdent « forgejo-cli »). La sortie est lue en entier, puis comparée : un
# « grep -q » en fin de tube ferait échouer le tube sous pipefail.
position_config() {
    local aide
    aide=$(sudo -u "$FORGEJO_USER" "$FORGEJO_BIN" forgejo-cli actions \
        register --help 2>&1 || true)
    case "$aide" in
        *--config*) echo apres ;;
        *) echo avant ;;
    esac
}

# Vrai quand le démon actif n'exécute pas le binaire « $1 » : la cible de
# /proc/<MainPID>/exe, lue par root, diffère de ce chemin ou porte le
# suffixe « (deleted) » que le noyau ajoute quand le fichier a été remplacé
# depuis le lancement. Un service arrêté (MainPID 0) ou illisible rend faux.
runner_perime() {
    local bin="$1" pid exe
    pid=$(systemctl show -p MainPID --value forgejo-runner.service \
        2>/dev/null || true)
    [[ "$pid" =~ ^[1-9][0-9]*$ ]] || return 1
    exe=$(sudo readlink "/proc/$pid/exe" 2>/dev/null || true)
    [ -n "$exe" ] || return 1
    [ "$exe" != "$bin" ]
}

# Le gestionnaire de paquets du système, le premier trouvé parmi apt-get,
# dnf, zypper et pacman ; rien quand il n'y en a aucun.
gestionnaire_paquets() {
    local g
    for g in apt-get dnf zypper pacman; do
        if command -v "$g" >/dev/null 2>&1; then
            echo "$g"
            return 0
        fi
    done
}

# « paquets_ci GESTIONNAIRE » : les paquets des outils que les jobs
# appellent — make, psql, openssl, git —, sous leur nom pour ce
# gestionnaire. psql vient de postgresql-client chez Debian et Ubuntu, du
# paquet postgresql ailleurs.
paquets_ci() {
    case "${1:-}" in
        apt-get) echo "make postgresql-client openssl git" ;;
        dnf|zypper|pacman) echo "make postgresql openssl git" ;;
    esac
}

# « paquet_present GESTIONNAIRE PAQUET » : vrai quand PAQUET est installé,
# selon la base du gestionnaire (dpkg, rpm ou pacman).
paquet_present() {
    case "$1" in
        apt-get)
            [ "$(dpkg-query -W -f='${Status}' "$2" 2>/dev/null)" \
                = "install ok installed" ] ;;
        dnf|zypper) rpm -q "$2" >/dev/null 2>&1 ;;
        pacman) pacman -Q "$2" >/dev/null 2>&1 ;;
        *) return 1 ;;
    esac
}

# « prerequis_ci GESTIONNAIRE PAQUET... » : installe par sudo ceux des
# PAQUETS qui manquent, et n'appelle pas le gestionnaire quand tous sont
# là. apt-get relit d'abord ses index, vides sur une image neuve. Écrit
# sur la sortie la liste installée ; rend le code du gestionnaire.
prerequis_ci() {
    local g="$1" p
    local manquants=()
    shift
    for p in "$@"; do
        paquet_present "$g" "$p" || manquants+=("$p")
    done
    [ "${#manquants[@]}" -gt 0 ] || return 0
    echo "${manquants[*]}"
    case "$g" in
        apt-get)
            sudo env DEBIAN_FRONTEND=noninteractive apt-get -q \
                -o DPkg::Lock::Timeout=600 update >/dev/null \
                && sudo env DEBIAN_FRONTEND=noninteractive apt-get -q \
                -o DPkg::Lock::Timeout=600 install -y \
                --no-install-recommends "${manquants[@]}" >/dev/null ;;
        dnf) sudo dnf install -y -q "${manquants[@]}" >/dev/null ;;
        zypper)
            sudo zypper --non-interactive --quiet install \
                "${manquants[@]}" >/dev/null ;;
        pacman)
            sudo pacman -S --needed --noconfirm "${manquants[@]}" \
                >/dev/null ;;
        *) return 1 ;;
    esac
}

if [ "${EL_RUNNER_LIB_ONLY:-}" = 1 ]; then
    return 0 2>/dev/null || exit 0
fi

set -euo pipefail

Red='\033[0;31m'
Green='\033[0;32m'
Color_Off='\033[0m'

usage() {
    # L'en-tête : de la ligne 5 à la première ligne vide.
    sed -n '5,/^$/{/^#/s/^# \?//p}' "$0"
    exit 0
}
case "${1:-}" in
    -h|--help) usage ;;
esac

say() { echo -e "   $*"; }
die() { echo -e "   ${Red}✗ $*${Color_Off}" >&2; exit 1; }

# shellcheck source=script/forgejo/lib_app_ini.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib_app_ini.sh"

VERSION="${FORGEJO_RUNNER_VERSION:-}"
NAME="${FORGEJO_RUNNER_NAME:-${HOSTNAME:-forge}-host}"
LABEL="${FORGEJO_RUNNER_LABEL:-erplibre-host}"
RUNNER_USER="${FORGEJO_RUNNER_USER:-forgejo-runner}"
SCOPE="${FORGEJO_RUNNER_SCOPE:-}"
CAPACITY="${FORGEJO_RUNNER_CAPACITY:-1}"
UNITS="${FORGEJO_RUNNER_UNITS-repo.code,repo.releases,repo.issues,repo.pulls,repo.wiki,repo.projects,repo.packages}"
# Non définie, la liste se déduit du gestionnaire trouvé ; vide, aucun
# paquet n'est installé.
PACKAGES_SET="${FORGEJO_RUNNER_PACKAGES+1}"
PACKAGES="${FORGEJO_RUNNER_PACKAGES-}"
HTTP_PORT="${FORGEJO_HTTP_PORT:-3000}"
FORGEJO_USER="${FORGEJO_USER:-git}"

BIN=/usr/local/bin/forgejo-runner
FORGEJO_BIN=/usr/local/bin/forgejo
FORGEJO_CONF=/etc/forgejo/app.ini
FORGEJO_DATA=/var/lib/forgejo
HOME_RUNNER=/var/lib/forgejo-runner
CONF_DIR=/etc/forgejo-runner
CONF="$CONF_DIR/config.yml"
UNIT=/etc/systemd/system/forgejo-runner.service
API=https://code.forgejo.org/api/v1/repos/forgejo/runner/releases/latest
DL=https://code.forgejo.org/forgejo/runner/releases/download

# Ce qui a changé pendant ce passage : chaque service ne redémarre que si ce
# qui le concerne a bougé.
CHANGED_RUNNER=0
CHANGED_FORGEJO=0

# Les réglages finissent dans du YAML, dans app.ini et dans des lignes de
# commande : leur forme est vérifiée avant le premier geste.
[[ "$LABEL" =~ ^[A-Za-z0-9][-A-Za-z0-9_.]*$ ]] \
    || die "FORGEJO_RUNNER_LABEL invalide : $LABEL"
[[ "$NAME" =~ ^[A-Za-z0-9][-A-Za-z0-9_.]*$ ]] \
    || die "FORGEJO_RUNNER_NAME invalide : $NAME"
[[ "$RUNNER_USER" =~ ^[a-z_][-a-z0-9_]*$ ]] \
    || die "FORGEJO_RUNNER_USER invalide : $RUNNER_USER"
[[ -z "$SCOPE" || "$SCOPE" =~ ^[-.A-Za-z0-9_]+(/[-.A-Za-z0-9_]+)?$ ]] \
    || die "FORGEJO_RUNNER_SCOPE invalide : $SCOPE"
# Un seul job à la fois : ci_venv.sh élague les venvs les moins récents du
# cache partagé, et un job concurrent qui se sert encore de l'un d'eux le
# perdrait en pleine exécution.
[ "$CAPACITY" = 1 ] \
    || die "FORGEJO_RUNNER_CAPACITY=$CAPACITY refusé : 1 seulement, les" \
           "jobs partagent les venvs que ci_venv.sh élague"
[[ "$UNITS" =~ ^[a-z.,]*$ ]] || die "FORGEJO_RUNNER_UNITS invalide : $UNITS"
[[ "$PACKAGES" =~ ^[-A-Za-z0-9.+_\ ]*$ ]] \
    || die "FORGEJO_RUNNER_PACKAGES invalide : $PACKAGES"
[[ "$HTTP_PORT" =~ ^[0-9]+$ ]] || die "FORGEJO_HTTP_PORT invalide : $HTTP_PORT"

# Un seul piège EXIT, posé une fois : un second l'écraserait. Il retire le
# dossier de téléchargement, le fichier du secret lu par Forgejo et les
# copies temporaires de root, qui portent des secrets.
tmp=""
f=""
temps_root=()
nettoyer() {
    [ -n "$tmp" ] && rm -rf "$tmp"
    [ -n "$f" ] && sudo -u "$FORGEJO_USER" rm -f "$f"
    if [ "${#temps_root[@]}" -gt 0 ]; then
        sudo rm -f "${temps_root[@]}"
    fi
    return 0
}
trap nettoyer EXIT

# Une copie temporaire créée par root, en 0600 : elle reçoit app.ini ou la
# configuration du runner, que l'utilisateur qui lance le script ne doit pas
# pouvoir lire.
temp_root() {
    local t
    t=$(sudo mktemp)
    temps_root+=("$t")
    echo "$t"
}

# --- 1. Architecture -------------------------------------------------------
case "$(uname -m)" in
    x86_64)         ARCH=amd64 ;;
    aarch64|arm64)  ARCH=arm64 ;;
    *) die "forgejo-runner ne publie pas de binaire pour $(uname -m)" \
           "(amd64 et arm64 seulement)." ;;
esac

# --- 2. Version ------------------------------------------------------------
if [ -z "$VERSION" ]; then
    if command -v python3 >/dev/null 2>&1; then
        VERSION=$(curl -fsSL --max-time 30 "$API" 2>/dev/null \
            | python3 -c 'import json,sys
try:
    print(json.load(sys.stdin)["tag_name"].lstrip("v"))
except Exception:
    pass' || true)
    else
        VERSION=$(curl -fsSL --max-time 30 "$API" 2>/dev/null \
            | grep -o '"tag_name":"v[^"]*"' | head -1 \
            | sed 's/.*"v//;s/"//' || true)
    fi
fi
[ -n "$VERSION" ] || die "Version de forgejo-runner introuvable (réseau ? $API)"
[[ "$VERSION" =~ ^[0-9]+(\.[0-9]+)*$ ]] \
    || die "Version de forgejo-runner invalide : $VERSION"
say "forgejo-runner $VERSION pour $ARCH"

# --- 3. Binaire ------------------------------------------------------------
# La version se compare EXACTEMENT, dernier mot de « --version » sans « v » :
# une recherche de sous-chaîne prendrait 13.2.20 pour 13.2.2.
if [ -x "$BIN" ] && [ "$("$BIN" --version 2>/dev/null | awk '{print $NF}' \
        | sed 's/^v//')" = "$VERSION" ]; then
    say "${Green}binaire déjà en version $VERSION${Color_Off}"
else
    tmp=$(mktemp -d)
    if command -v xz >/dev/null 2>&1; then
        asset="forgejo-runner-$VERSION-linux-$ARCH.xz"
    else
        asset="forgejo-runner-$VERSION-linux-$ARCH"
    fi
    say "téléchargement de $asset"
    curl -fsSL --retry 3 --max-time 900 "$DL/v$VERSION/$asset" \
        -o "$tmp/$asset" || die "téléchargement impossible : $DL/v$VERSION/$asset"
    # La somme de contrôle est obligatoire : ce binaire exécute le code des
    # pull requests, une archive tronquée ou substituée ne s'installe pas.
    curl -fsSL --max-time 60 "$DL/v$VERSION/$asset.sha256" \
        -o "$tmp/$asset.sha256" 2>/dev/null \
        || die "somme de contrôle introuvable pour $asset"
    (cd "$tmp" && sha256sum -c "$asset.sha256" >/dev/null 2>&1) \
        || die "somme de contrôle invalide pour $asset"
    say "somme de contrôle vérifiée"
    case "$asset" in
        *.xz) xz -d "$tmp/$asset"; src="$tmp/${asset%.xz}" ;;
        *)    src="$tmp/$asset" ;;
    esac
    chmod +x "$src"
    sudo install -m 0755 "$src" "$BIN"
    CHANGED_RUNNER=1
    say "${Green}binaire posé : $BIN${Color_Off}"
fi
# Vérifié avant toute édition d'app.ini et tout enregistrement : un binaire
# qui ne sait pas écrire server.connections arrête le script avant qu'un
# secret neuf, jamais sauvegardé, n'enregistre un runner sur la forge.
"$BIN" generate-config 2>/dev/null | grep 'connections:' >/dev/null \
    || die "forgejo-runner $VERSION ne connaît pas server.connections"
# Un passage précédent interrompu après la pose du binaire n'a pas relancé
# le démon : celui-ci exécute encore l'ancien fichier, et le redémarrage
# reste dû.
if [ "$CHANGED_RUNNER" = 0 ] && runner_perime "$BIN"; then
    CHANGED_RUNNER=1
    say "le runner actif exécute un ancien binaire : redémarrage dû"
fi

# --- 4. Outils des jobs ----------------------------------------------------
# Les jobs lancent make, psql, openssl et git directement sur l'hôte : un
# outil absent fait échouer les tests qui l'appellent, pas l'installation.
GESTIONNAIRE=$(gestionnaire_paquets)
if [ -z "$PACKAGES_SET" ]; then
    [ -n "$GESTIONNAIRE" ] \
        || die "aucun gestionnaire de paquets reconnu (apt-get, dnf, zypper," \
               "pacman) : installer make, psql, openssl et git, puis relancer" \
               "avec FORGEJO_RUNNER_PACKAGES=\"\""
    PACKAGES=$(paquets_ci "$GESTIONNAIRE")
fi
if [ -n "$PACKAGES" ]; then
    [ -n "$GESTIONNAIRE" ] \
        || die "FORGEJO_RUNNER_PACKAGES demande un gestionnaire de paquets" \
               "(apt-get, dnf, zypper ou pacman), introuvable ici"
    read -ra liste_paquets <<< "$PACKAGES"
    poses=$(prerequis_ci "$GESTIONNAIRE" "${liste_paquets[@]}") \
        || die "$GESTIONNAIRE refuse d'installer : $PACKAGES"
    if [ -n "$poses" ]; then
        say "${Green}paquets installés${Color_Off} : $poses"
    else
        say "paquets des jobs déjà présents : $PACKAGES"
    fi
fi

# --- 5. Compte et dossiers -------------------------------------------------
# Le compte n'entre ni dans sudo ni dans le groupe de Forgejo : un job ne
# lit ni les dépôts nus ni app.ini.
if ! id "$RUNNER_USER" >/dev/null 2>&1; then
    sudo useradd --system --create-home --home-dir "$HOME_RUNNER" \
        --shell /bin/bash --comment "Forgejo runner" "$RUNNER_USER"
    say "compte système créé : $RUNNER_USER"
fi
sudo install -d -m 0750 -o "$RUNNER_USER" -g "$RUNNER_USER" \
    "$HOME_RUNNER" "$HOME_RUNNER/work" "$HOME_RUNNER/cache"
sudo install -d -m 0750 -o root -g "$RUNNER_USER" "$CONF_DIR"

# --- 6. app.ini ------------------------------------------------------------
# install_forgejo.sh ne réécrit jamais app.ini ; ici, l'édition se fait clé
# par clé (ini_poser), et les secrets comme les réglages de l'opérateur
# restent tels quels. ENABLED se pose explicitement : la valeur par défaut
# varie selon la version de Forgejo. DEFAULT_REPO_UNITS sans repo.actions :
# un dépôt sans cette unité ne crée jamais de run, donc seul le dépôt où
# elle est activée exprès lance des jobs sur cet hôte — ni un dépôt d'addons
# qui porte .github/workflows, ni un miroir.
sudo test -f "$FORGEJO_CONF" \
    || die "$FORGEJO_CONF introuvable : installer Forgejo d'abord (install_forgejo.sh)"
t_ini=$(temp_root)
sudo cat "$FORGEJO_CONF" | ini_poser actions ENABLED true \
    | { if [ -n "$UNITS" ]; then
            ini_poser repository DEFAULT_REPO_UNITS "$UNITS"
        else
            cat
        fi; } \
    | sudo tee "$t_ini" >/dev/null
if ! sudo cmp -s "$t_ini" "$FORGEJO_CONF"; then
    sudo install -m 0640 -o root -g "$FORGEJO_USER" "$t_ini" "$FORGEJO_CONF"
    CHANGED_FORGEJO=1
    say "app.ini : Actions activé, unités par défaut posées"
fi
if [ "$CHANGED_FORGEJO" = 1 ]; then
    sudo systemctl restart forgejo.service \
        || die "Forgejo refuse de redémarrer : sudo journalctl -u forgejo -n 40"
    pret=0
    for _ in $(seq 1 60); do
        if curl -fs -o /dev/null --max-time 3 \
                "http://127.0.0.1:$HTTP_PORT/api/v1/version"; then
            pret=1
            break
        fi
        sleep 2
    done
    [ "$pret" = 1 ] || die "Forgejo ne répond plus sur le port $HTTP_PORT" \
        "après 120 s (sudo journalctl -u forgejo -n 40)"
fi

# --- 7. Secret partagé -----------------------------------------------------
# Repris de la configuration existante quand il est valide : rejouer le
# script garde le même enregistrement, au lieu de laisser sur la forge un
# second runner hors ligne. Il ne passe jamais par une ligne de commande :
# seuls printf (interne) et les entrées standard le portent.
secret=""
if sudo test -f "$CONF"; then
    secret=$(sudo awk '/^ *token:/{gsub(/["\047]/,"",$2); print $2; exit}' \
        "$CONF" || true)
fi
if ! secret_valide "$secret"; then
    secret=$(od -An -N20 -tx1 /dev/urandom | tr -d ' \n')
fi

# --- 8. Enregistrement -----------------------------------------------------
# Rejoué à chaque passage, idempotent côté Forgejo. Le secret arrive par un
# fichier lisible du seul compte de Forgejo (--secret-file), jamais par
# --secret.
f=$(sudo -u "$FORGEJO_USER" mktemp)
printf '%s' "$secret" | sudo -u "$FORGEJO_USER" tee "$f" >/dev/null
enregistrer=(--name "$NAME" --labels "$LABEL" --secret-file "$f")
if [ -n "$SCOPE" ]; then
    enregistrer+=(--scope "$SCOPE")
fi
if [ "$(position_config)" = apres ]; then
    sortie=$(sudo -u "$FORGEJO_USER" env GITEA_WORK_DIR="$FORGEJO_DATA" \
        HOME="/home/$FORGEJO_USER" "$FORGEJO_BIN" forgejo-cli actions \
        register --config "$FORGEJO_CONF" --work-path "$FORGEJO_DATA" \
        "${enregistrer[@]}" 2>&1 || true)
else
    sortie=$(sudo -u "$FORGEJO_USER" env GITEA_WORK_DIR="$FORGEJO_DATA" \
        HOME="/home/$FORGEJO_USER" "$FORGEJO_BIN" --config "$FORGEJO_CONF" \
        --work-path "$FORGEJO_DATA" forgejo-cli actions register \
        "${enregistrer[@]}" 2>&1 || true)
fi
uuid=$(printf '%s\n' "$sortie" \
    | grep -Eo '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' \
    | tail -1 || true)
[ -n "$uuid" ] || die "enregistrement du runner refusé par Forgejo"
sudo -u "$FORGEJO_USER" rm -f "$f"
f=""

# --- 9. Configuration du runner --------------------------------------------
t_conf=$(temp_root)
config_runner "http://127.0.0.1:$HTTP_PORT/" "$uuid" "$secret" "$LABEL" \
    "$CAPACITY" "$HOME_RUNNER" | sudo tee "$t_conf" >/dev/null
if ! sudo cmp -s "$t_conf" "$CONF"; then
    sudo install -m 0640 -o root -g "$RUNNER_USER" "$t_conf" "$CONF"
    CHANGED_RUNNER=1
    say "configuration écrite : $CONF"
fi

# --- 10. Service -----------------------------------------------------------
# ProtectHome cache au code des pull requests le checkout de l'opérateur et
# ses clés SSH ; NoNewPrivileges tient les jobs loin de tout setuid ;
# EnvironmentFile donne aux jobs les variables du cache de téléchargement
# (PIP_CERT, REQUESTS_CA_BUNDLE…), qu'un service systemd ne reçoit pas de
# PAM, à la différence d'une session « sudo -u ».
t_unit=$(mktemp)
temps_root+=("$t_unit")
cat > "$t_unit" <<UNITEOF
[Unit]
Description=Forgejo runner (host mode)
After=network-online.target forgejo.service
Wants=network-online.target

[Service]
User=$RUNNER_USER
Group=$RUNNER_USER
WorkingDirectory=$HOME_RUNNER
Environment=HOME=$HOME_RUNNER
EnvironmentFile=-/etc/environment
ExecStart=$BIN daemon --config $CONF
Restart=on-failure
RestartSec=10
Nice=10
NoNewPrivileges=yes
PrivateTmp=yes
ProtectHome=yes
ProtectSystem=full

[Install]
WantedBy=multi-user.target
UNITEOF
if ! sudo cmp -s "$t_unit" "$UNIT"; then
    sudo install -m 0644 "$t_unit" "$UNIT"
    sudo systemctl daemon-reload
    CHANGED_RUNNER=1
    say "service défini : $UNIT"
fi

sudo systemctl enable forgejo-runner.service >/dev/null 2>&1 || true
# « restart » et non « enable --now » quand quelque chose a changé : « --now »
# ne touche pas un service déjà actif, qui garderait en mémoire son ancienne
# configuration ou son ancien binaire.
if [ "$CHANGED_RUNNER" = 1 ]; then
    sudo systemctl restart forgejo-runner.service \
        || die "le runner refuse de démarrer : sudo journalctl -u forgejo-runner -n 40"
elif ! systemctl is-active --quiet forgejo-runner.service; then
    sudo systemctl start forgejo-runner.service \
        || die "le runner refuse de démarrer : sudo journalctl -u forgejo-runner -n 40"
fi

# --- 11. Disponibilité -----------------------------------------------------
# Actif au bout de 30 s ET sans redémarrage entre-temps : un démon qui ne
# joint pas la forge sort en erreur, et Restart=on-failure le relance en
# boucle, ce qui ressemble à « active » à un instant donné.
redemarrages() {
    systemctl show -p NRestarts --value forgejo-runner.service 2>/dev/null \
        || true
}
n0=$(redemarrages)
for _ in $(seq 1 15); do
    sleep 2
    [ "$(redemarrages)" = "$n0" ] || break
done
if ! systemctl is-active --quiet forgejo-runner.service \
        || [ "$(redemarrages)" != "$n0" ]; then
    die "le runner ne reste pas actif : sudo journalctl -u forgejo-runner -n 40"
fi

# --- 12. Résumé ------------------------------------------------------------
say "${Green}runner prêt${Color_Off} : $NAME, étiquette $LABEL, forgejo-runner $VERSION"
say "  service : sudo systemctl status forgejo-runner"
say "  journal : sudo journalctl -u forgejo-runner -f"
