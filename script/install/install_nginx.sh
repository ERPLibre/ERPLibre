#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Pose le site nginx de l'infrastructure d'appel ERPLibre : le port 80 qui
# repond au defi ACME (HTTP-01, webroot) et renvoie tout le reste en https,
# puis, a l'etape « full », le port 443 qui relaie ntfy, ecoutant sur la
# boucle locale. Supporte : Debian, Ubuntu, Arch Linux (et derives), sous
# systemd. Aucun autre site n'est modifie.
#
# Usage, deja root, les variables exportees par le script appelant :
#   export NGINX_STAGE=acme NGINX_NAMES="ntfy.exemple.test turn.exemple.test"
#   bash install_nginx.sh
#
# Entrees (environnement) :
#   NGINX_STAGE          obligatoire : « acme » (port 80 seul : defi ACME et
#                        renvoi en https) ou « full » (le port 80 de acme et
#                        le port 443 qui relaie ntfy)
#   NGINX_NAMES          obligatoire : noms servis sur le port 80, separes
#                        par des espaces ; noms exacts, sans joker
#   NGINX_NTFY_NAME      nom servi en https sur 443, l'un de NGINX_NAMES ;
#                        vide sur un hote sans ntfy (coturn seul) : « full »
#                        n'ecrit alors que le port 80
#   NGINX_UPSTREAM_PORT  port http de ntfy sur 127.0.0.1 (etape full)
#   NGINX_CERT_FILE      certificat et cle sur l'hote (etape full) : ceux de
#   NGINX_KEY_FILE       la lignee live/erplibre-call de certbot, ou
#                        /etc/erplibre-call/tls/site.{crt,key} pour un
#                        certificat fourni
#   NGINX_ACME_ROOT      dossier du defi ACME (/var/lib/erplibre-call/acme) ;
#                        vide : aucune location ACME (certificat fourni)
#   NGINX_INSTALL=1      installe nginx quand il est absent ; sans lui, un
#                        nginx absent arrete le script
#   NGINX_ADOPT_INCLUDE=1
#                        nginx.conf n'inclut aucun dossier de sites (Arch) :
#                        l'appelant a fait accepter la ligne « include »
#                        ajoutee dans http {}. Sans lui, le changement est
#                        montre en diff et le script s'arrete, nginx.conf
#                        intact.
#
# Sortie lisible par un programme :
#   @@NGINX_INSTALLED 1  ce passage a installe le paquet nginx
#   @@NGINX_LAYOUT <d>   debian (sites-enabled inclus), confd (conf.d/*.conf
#                        inclus) ou arch-include (dossier erplibre-call.d,
#                        inclus par une ligne ajoutee a nginx.conf)
#   @@NGINX_ADOPT_NEEDED <nginx.conf>
#                        la ligne include manque et NGINX_ADOPT_INCLUDE n'est
#                        pas donne
#   @@NGINX_INCLUDE <nginx.conf>, @@NGINX_BACKUP <copie>
#                        la ligne include vient d'etre ajoutee ; la copie est
#                        le fichier d'avant
#   @@NGINX_SITE <chemin>, @@NGINX_LINK <chemin>
#                        le site, et son lien dans sites-enabled (debian)
#   @@NGINX active | @@NGINX failed <ligne>
#                        derniere ligne ; code de sortie non nul sur failed
#
# Tout changement est suivi de « nginx -t » ; un test en echec remet les
# fichiers touches (site, lien, nginx.conf) dans leur etat precedent avant
# tout rechargement, et rien n'est recharge. nginx est recharge (reload),
# jamais redemarre : les flux ntfy ouverts restent sur les anciens
# processus jusqu'a leur fin.

set -euo pipefail

# Premiere ligne du site ecrit ici : un fichier au meme nom qui ne la porte
# pas est etranger, et n'est jamais remplace.
MARKER="# erplibre-call: managed"
# Prefixe de chaque chemin de l'hote lu ou ecrit, vide hors des tests ; les
# textes ecrits (site, lien, include) portent toujours le chemin sans lui.
ROOT=""
OS_RELEASE="/etc/os-release"
NGINX_DIR="/etc/nginx"
NGINX_CONF="/etc/nginx/nginx.conf"
INCLUDE_DIR="/etc/nginx/erplibre-call.d"
SITE_FILE="erplibre-call-ntfy.conf"
CALL_DIR="/etc/erplibre-call"
# Empreinte du site que nginx a charge, ecrite seulement apres un
# rechargement suivi de l'etat « active » (voir test_and_reload).
APPLIED_FILE="/etc/erplibre-call/nginx.applied"
# Present quand le noyau a IPv6 : les ecoutes [::] n'y sont ecrites qu'alors.
INET6_FILE="/proc/net/if_inet6"

NGINX_STAGE="${NGINX_STAGE:-}"
NGINX_NAMES="${NGINX_NAMES:-}"
NGINX_NTFY_NAME="${NGINX_NTFY_NAME:-}"
NGINX_UPSTREAM_PORT="${NGINX_UPSTREAM_PORT:-}"
NGINX_CERT_FILE="${NGINX_CERT_FILE:-}"
NGINX_KEY_FILE="${NGINX_KEY_FILE:-}"
# Sans « : » : une valeur vide, donnee expres, retire la location ACME.
NGINX_ACME_ROOT="${NGINX_ACME_ROOT-/var/lib/erplibre-call/acme}"
NGINX_INSTALL="${NGINX_INSTALL:-}"
NGINX_ADOPT_INCLUDE="${NGINX_ADOPT_INCLUDE:-}"

log() { echo "[NGINX] $*"; }
# Le marqueur part sur le descripteur 3, la sortie du script (ouvert par
# main) : un die dans une substitution $(...) le rend quand meme a
# l'appelant.
die() {
    echo "[NGINX] ERREUR : $*" >&2
    echo "@@NGINX failed $*" >&3
    exit 1
}

check_root() {
    if [ "$EUID" -ne 0 ]; then
        die "ce script doit tourner en root : sudo bash $0"
    fi
}

# valid_port <valeur> : vrai pour un entier de 1 a 65535 ecrit en chiffres.
valid_port() {
    case "$1" in
        ''|*[!0-9]*) return 1 ;;
    esac
    [ "${#1}" -le 5 ] && [ "$1" -ge 1 ] && [ "$1" -le 65535 ]
}

# Un nom exact : lettres, chiffres, point et tiret. Ni joker, ni espace, ni
# point-virgule : le nom finit dans une directive server_name.
valid_name() {
    [[ "$1" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]]
}

# Un chemin absolu sans espace ni point-virgule ni « .. » : il finit dans
# une directive de la configuration.
valid_path() {
    case "$1" in
        *..*) return 1 ;;
    esac
    [[ "$1" =~ ^/[A-Za-z0-9._/-]+$ ]]
}

# Remplit NAMES (tableau) depuis NGINX_NAMES ; read -a ne developpe aucun
# joker, un « * » reste un mot que valid_name refuse.
check_inputs() {
    case "$NGINX_STAGE" in
        acme|full) ;;
        *) die "NGINX_STAGE invalide : ${NGINX_STAGE:-vide} (acme ou full)." ;;
    esac
    read -r -a NAMES <<< "$NGINX_NAMES"
    [ "${#NAMES[@]}" -gt 0 ] || die "NGINX_NAMES manque (noms servis sur le port 80)."
    local name found=0
    for name in "${NAMES[@]}"; do
        valid_name "$name" || die "nom invalide : ${name}"
        if [ "$name" = "$NGINX_NTFY_NAME" ]; then
            found=1
        fi
    done
    if [ -n "$NGINX_NTFY_NAME" ]; then
        valid_name "$NGINX_NTFY_NAME" || die "NGINX_NTFY_NAME invalide : ${NGINX_NTFY_NAME}"
        [ "$found" = 1 ] || die "NGINX_NTFY_NAME (${NGINX_NTFY_NAME}) doit figurer dans NGINX_NAMES : le renouvellement passe par son port 80."
    fi
    if serves_ntfy; then
        valid_port "$NGINX_UPSTREAM_PORT" \
            || die "NGINX_UPSTREAM_PORT invalide : ${NGINX_UPSTREAM_PORT:-vide} (1 a 65535)."
        [ -n "$NGINX_CERT_FILE" ] && [ -n "$NGINX_KEY_FILE" ] \
            || die "l'etape full demande NGINX_CERT_FILE et NGINX_KEY_FILE."
        local file
        for file in "$NGINX_CERT_FILE" "$NGINX_KEY_FILE"; do
            valid_path "$file" || die "chemin invalide : ${file}"
            [ -f "${ROOT}${file}" ] || die "fichier introuvable : ${file}"
        done
    fi
    if [ -n "$NGINX_ACME_ROOT" ]; then
        valid_path "$NGINX_ACME_ROOT" || die "NGINX_ACME_ROOT invalide : ${NGINX_ACME_ROOT}"
    fi
    local flag
    for flag in "$NGINX_INSTALL" "$NGINX_ADOPT_INCLUDE"; do
        case "$flag" in
            ''|0|1) ;;
            *) die "NGINX_INSTALL et NGINX_ADOPT_INCLUDE valent 1, 0 ou vide : ${flag}" ;;
        esac
    done
}

# Vrai quand le site porte le port 443 : etape full avec un nom ntfy.
serves_ntfy() {
    [ "$NGINX_STAGE" = full ] && [ -n "$NGINX_NTFY_NAME" ]
}

# Lit ID et ID_LIKE dans un sous-shell : les autres variables d'os-release
# (NAME, VERSION...) ne viennent pas remplacer celles du script.
detect_os() {
    [ -f "${ROOT}${OS_RELEASE}" ] || die "systeme non identifie (pas de ${OS_RELEASE})."
    OS=$(. "${ROOT}${OS_RELEASE}" && echo "${ID:-}")
    OS_LIKE=$(. "${ROOT}${OS_RELEASE}" && echo "${ID_LIKE:-}")
    log "Systeme detecte : ${OS}"
}

# Imprime debian ou arch d'apres OS et OS_LIKE ; tout autre systeme arrete
# le script en nommant ce qui est supporte.
family() {
    case "$OS" in
        debian|ubuntu|linuxmint|pop|raspbian) echo debian; return 0 ;;
        arch|manjaro|endeavouros|artix|garuda) echo arch; return 0 ;;
    esac
    case " ${OS_LIKE} " in
        *" debian "*|*" ubuntu "*) echo debian ;;
        *" arch "*) echo arch ;;
        *) die "systeme non supporte : ${OS:-inconnu} (supportes : Debian, Ubuntu, Arch Linux)." ;;
    esac
}

# nginx est tenu pour present quand son binaire repond au PATH et que
# nginx.conf existe : un paquet retire sans purge laisse sa configuration,
# pas son binaire. Absent, il est installe avec NGINX_INSTALL=1, sinon le
# script s'arrete. --force-confold : une question de dpkg sur un fichier de
# configuration resterait sans reponse au bout d'un ssh ; dpkg --configure
# -a reprend d'abord une operation coupee, sans rien faire quand rien n'est
# en attente. Le paquet Debian demarre nginx avec son site par defaut, celui
# d'Arch ne le demarre pas : test_and_reload le demarre.
ensure_package() {
    if [ -f "${ROOT}${NGINX_CONF}" ] && command -v nginx >/dev/null 2>&1; then
        return 0
    fi
    [ "$NGINX_INSTALL" = 1 ] || die "nginx absent ; NGINX_INSTALL=1 l'installe."
    case "$FAMILY" in
        debian)
            export DEBIAN_FRONTEND=noninteractive
            dpkg --configure -a --force-confdef --force-confold \
                || die "dpkg --configure -a a echoue."
            apt-get update -qq || die "apt-get update a echoue."
            apt-get install -y --no-install-recommends \
                -o Dpkg::Options::=--force-confdef \
                -o Dpkg::Options::=--force-confold \
                nginx || die "apt-get install nginx a echoue."
            ;;
        arch)
            pacman -S --noconfirm --needed nginx \
                || die "pacman -S nginx a echoue."
            ;;
    esac
    echo "@@NGINX_INSTALLED 1"
    [ -f "${ROOT}${NGINX_CONF}" ] || die "nginx installe, mais ${NGINX_CONF} manque."
}

# Vrai quand une ligne active de nginx.conf inclut INCLUDE_DIR/*.conf.
has_include() {
    local re
    re=$(printf '%s' "$INCLUDE_DIR" | sed 's/[.]/\\./g')
    grep -qE "^[[:space:]]*include[[:space:]]+${re}/\\*\\.conf[[:space:]]*;" \
        "${ROOT}${NGINX_CONF}"
}

# Imprime la disposition d'apres les include actifs de nginx.conf :
# arch-include quand la ligne de ce script y est deja (un dossier inclus
# apres coup ne deplace pas le site, qui laisserait un double du meme
# server_name), debian quand sites-enabled est inclus, confd quand
# conf.d/*.conf l'est, sinon arch-include. Un chemin relatif d'include part
# du dossier de nginx.conf, d'ou le prefixe /etc/nginx/ facultatif ; une
# ligne commentee ne compte pas.
layout() {
    local conf="${ROOT}${NGINX_CONF}"
    if has_include; then
        echo arch-include
    elif grep -qE '^[[:space:]]*include[[:space:]]+(/etc/nginx/)?sites-enabled/\*[[:space:]]*;' "$conf"; then
        echo debian
    elif grep -qE '^[[:space:]]*include[[:space:]]+(/etc/nginx/)?conf\.d/\*\.conf[[:space:]]*;' "$conf"; then
        echo confd
    else
        echo arch-include
    fi
}

# Chemin du site sur l'hote, selon LAYOUT.
site_path() {
    case "$LAYOUT" in
        debian) echo "${NGINX_DIR}/sites-available/${SITE_FILE}" ;;
        confd) echo "${NGINX_DIR}/conf.d/${SITE_FILE}" ;;
        arch-include) echo "${INCLUDE_DIR}/${SITE_FILE}" ;;
    esac
}

# Chemin du lien qui active le site ; vide hors de la disposition debian.
link_path() {
    if [ "$LAYOUT" = debian ]; then
        echo "${NGINX_DIR}/sites-enabled/${SITE_FILE}"
    fi
}

# Arrete le script, avant toute ecriture, quand le site ou son lien
# existent sous une forme que ce script n'a pas posee : un site sans
# MARKER, un site en lien symbolique, un lien vers un autre fichier.
check_site() {
    local site="${ROOT}${SITE}" link
    if [ -L "$site" ]; then
        die "${SITE} est un lien symbolique ; rien n'est ecrit."
    fi
    if [ -e "$site" ] && [ "$(head -n 1 "$site")" != "$MARKER" ]; then
        die "${SITE} existe et n'a pas ete ecrit par erplibre-call ; rien n'est ecrit."
    fi
    [ -n "$LINK" ] || return 0
    link="${ROOT}${LINK}"
    if [ -L "$link" ]; then
        [ "$(readlink "$link")" = "$SITE" ] \
            || die "${LINK} pointe vers $(readlink "$link") ; rien n'est ecrit."
    elif [ -e "$link" ]; then
        die "${LINK} existe et n'est pas le lien de erplibre-call ; rien n'est ecrit."
    fi
}

# nginx sert le defi ACME sous le compte de ses processus de travail, qui
# doit traverser chaque dossier parent de NGINX_ACME_ROOT : un parent ferme
# aux autres comptes (pas de x pour « autres ») ferait echouer chaque
# delivrance sur un 403. Verifie avant toute ecriture ; les parents absents
# seront crees 0755 par create_acme_root.
check_acme_root() {
    [ -n "$NGINX_ACME_ROOT" ] || return 0
    local dir mode
    dir=$(dirname "$NGINX_ACME_ROOT")
    while [ "$dir" != / ]; do
        if [ -e "${ROOT}${dir}" ]; then
            mode=$(stat -c %a "${ROOT}${dir}")
            (( 8#$mode & 1 )) \
                || die "${dir} est ferme aux autres comptes (mode ${mode}) : nginx ne lirait pas le defi ACME sous ${NGINX_ACME_ROOT}."
        fi
        dir=$(dirname "$dir")
    done
}

create_acme_root() {
    [ -n "$NGINX_ACME_ROOT" ] || return 0
    install -d -m 0755 "${ROOT}${NGINX_ACME_ROOT}"
}

# add_include <ligne> : lit nginx.conf sur l'entree, l'ecrit sur la sortie
# avec <ligne> juste avant l'accolade qui ferme http {}. A cette place, les
# serveurs deja declares passent avant ceux du dossier inclus, et le premier
# d'entre eux reste le serveur par defaut de son port. La fin du bloc se
# trouve en comptant les accolades depuis la ligne « http { », hors
# commentaires et hors chaines entre guillemets (une accolade dans une
# expression reguliere de nginx doit y etre). Code 3, sortie incomplete,
# quand l'accolade finale partage sa ligne ou que le bloc ne se ferme pas.
add_include() {
    awk -v add="    $1" '
        BEGIN { depth = -1 }
        depth < 0 && /^[[:space:]]*http[[:space:]]*\{[[:space:]]*(#.*)?$/ {
            print; depth = 1; next
        }
        depth > 0 {
            s = $0
            gsub(/"[^"]*"/, "", s)
            gsub(/\047[^\047]*\047/, "", s)
            sub(/#.*/, "", s)
            o = gsub(/\{/, "", s)
            c = gsub(/\}/, "", s)
            if (depth + o - c <= 0) {
                if (o > 0 || $0 !~ /^[[:space:]]*\}[[:space:]]*(#.*)?$/) {
                    bad = 1
                    exit
                }
                print add
                depth = 0
            } else {
                depth += o - c
            }
        }
        { print }
        END { if (bad || depth != 0) exit 3 }
    '
}

# ensure_include : disposition arch-include seulement. Ajoute la ligne
# « include <INCLUDE_DIR>/*.conf; » a la fin de http {} (add_include), si
# aucune ligne active ne l'inclut deja. Le changement est montre en diff ;
# sans NGINX_ADOPT_INCLUDE=1 le script s'arrete, nginx.conf intact. Avec
# lui, l'ancien fichier est copie en nginx.conf.bak-<date> (INCLUDE_BACKUP,
# que restore remet en place), puis le nouveau, ecrit dans un voisin de
# mktemp aux droits et proprietaire de l'ancien, le remplace par renommage.
# Une ouverture « http { » absente, coupee sur deux lignes ou repetee, ou
# une fin de bloc introuvable, arrete le script : la ligne ne se place pas
# sans deviner.
ensure_include() {
    local conf="${ROOT}${NGINX_CONF}" line tmp count backup
    line="include ${INCLUDE_DIR}/*.conf;"
    if has_include; then
        return 0
    fi
    if [ -L "$conf" ]; then
        die "${NGINX_CONF} est un lien symbolique ; rien n'est ecrit."
    fi
    count=$(grep -cE '^[[:space:]]*http[[:space:]]*\{[[:space:]]*(#.*)?$' "$conf" || true)
    [ "$count" = 1 ] \
        || die "${NGINX_CONF} : aucune ligne « http { » unique ; ajouter a la main « ${line} » dans http {}."
    tmp=$(mktemp "$(dirname "$conf")/.nginx.conf.XXXXXX")
    TMP_FILES+=("$tmp")
    add_include "$line" < "$conf" > "$tmp" \
        || die "${NGINX_CONF} : fin de http {} introuvable sur une ligne a elle seule ; ajouter a la main « ${line} » dans http {}."
    log "nginx.conf n'inclut aucun dossier de sites ; changement propose :"
    diff -u --label "$NGINX_CONF" --label "$NGINX_CONF (erplibre-call)" \
        "$conf" "$tmp" || true
    if [ "$NGINX_ADOPT_INCLUDE" != 1 ]; then
        echo "@@NGINX_ADOPT_NEEDED ${NGINX_CONF}"
        die "${NGINX_CONF} reste intact ; NGINX_ADOPT_INCLUDE=1 accepte la ligne ajoutee."
    fi
    backup="${conf}.bak-$(date +%Y%m%d%H%M%S)"
    if [ -e "$backup" ]; then
        backup="${backup}.$$"
    fi
    cp -p "$conf" "$backup"
    chmod --reference="$conf" "$tmp"
    chown --reference="$conf" "$tmp"
    mv -f "$tmp" "$conf"
    INCLUDE_BACKUP="$backup"
    CHANGED=1
    echo "@@NGINX_INCLUDE ${NGINX_CONF}"
    echo "@@NGINX_BACKUP ${backup#"$ROOT"}"
}

# Imprime le texte complet du site. Le port 80 sert NAMES : la location du
# defi ACME (quand NGINX_ACME_ROOT est donne), et un renvoi en https pour le
# reste. Avec serves_ntfy, un serveur 443 pour NGINX_NTFY_NAME relaie tout
# vers ntfy sur 127.0.0.1 : websocket (Upgrade, Connection par la map, a
# portee http, nommee pour ne heurter aucune autre map), pas de tampon (les
# abonnements sont des flux), 3 h sans donnee avant coupure, 20 Mo par
# requete (pieces jointes de ntfy, 15 Mo au plus). Aucun default_server :
# seuls ces noms exacts arrivent ici, les autres sites gardent les leurs.
site_text() {
    local ipv6=0
    if [ -e "${ROOT}${INET6_FILE}" ]; then
        ipv6=1
    fi
    echo "$MARKER"
    echo "# Ecrit par install_nginx.sh, reecrit a chaque passage."
    if serves_ntfy; then
        cat <<'EOF'

map $http_upgrade $erplibre_call_upgrade {
    default upgrade;
    ''      close;
}
EOF
    fi
    echo
    echo "server {"
    echo "    listen 80;"
    if [ "$ipv6" = 1 ]; then
        echo "    listen [::]:80;"
    fi
    echo "    server_name ${NAMES[*]};"
    if [ -n "$NGINX_ACME_ROOT" ]; then
        echo
        echo "    location ^~ /.well-known/acme-challenge/ {"
        echo "        root ${NGINX_ACME_ROOT};"
        echo "        default_type text/plain;"
        echo "    }"
    fi
    echo
    echo "    location / {"
    echo "        return 301 https://\$host\$request_uri;"
    echo "    }"
    echo "}"
    serves_ntfy || return 0
    echo
    echo "server {"
    echo "    listen 443 ssl;"
    if [ "$ipv6" = 1 ]; then
        echo "    listen [::]:443 ssl;"
    fi
    echo "    server_name ${NGINX_NTFY_NAME};"
    echo
    echo "    ssl_certificate ${NGINX_CERT_FILE};"
    echo "    ssl_certificate_key ${NGINX_KEY_FILE};"
    echo "    ssl_protocols TLSv1.2 TLSv1.3;"
    echo
    echo "    client_max_body_size 20m;"
    echo
    echo "    location / {"
    echo "        proxy_pass http://127.0.0.1:${NGINX_UPSTREAM_PORT};"
    cat <<'EOF'
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $erplibre_call_upgrade;
        proxy_redirect off;
        proxy_buffering off;
        proxy_request_buffering off;
        proxy_connect_timeout 3m;
        proxy_send_timeout 3h;
        proxy_read_timeout 3h;
    }
}
EOF
}

# write_site : ecrit le site 0644 par un voisin de mktemp renomme (nginx ne
# lit jamais un fichier a moitie ecrit) ; le nom du voisin ne finit pas par
# .conf, aucun include ne le lit. Un texte identique laisse le fichier tel
# quel. Avant de remplacer un site existant, sa copie va dans SITE_PREV ;
# un site neuf met SITE_NEW a 1 ; un lien cree met LINK_ADDED a 1 : restore
# defait exactement cela. CHANGED passe a 1 a tout changement.
write_site() {
    local site="${ROOT}${SITE}" dir tmp
    dir=$(dirname "$site")
    mkdir -p "$dir"
    tmp=$(mktemp "${dir}/.${SITE_FILE}.XXXXXX")
    TMP_FILES+=("$tmp")
    site_text > "$tmp"
    chmod 0644 "$tmp"
    if cmp -s "$tmp" "$site"; then
        rm -f "$tmp"
    else
        if [ -e "$site" ]; then
            SITE_PREV=$(mktemp "${dir}/.${SITE_FILE}.prev.XXXXXX")
            TMP_FILES+=("$SITE_PREV")
            cp -p "$site" "$SITE_PREV"
        else
            SITE_NEW=1
        fi
        mv -f "$tmp" "$site"
        CHANGED=1
        log "Site ecrit : ${SITE}"
    fi
    if [ -n "$LINK" ] && [ ! -L "${ROOT}${LINK}" ]; then
        mkdir -p "$(dirname "${ROOT}${LINK}")"
        ln -s "$SITE" "${ROOT}${LINK}"
        LINK_ADDED=1
        CHANGED=1
        log "Site active : ${LINK}"
    fi
}

# Remet les fichiers que ce passage a changes dans leur etat d'avant : le
# site precedent, ou aucun site ; aucun lien s'il vient d'etre cree ;
# nginx.conf d'avant l'ajout de la ligne include. Le dossier
# erplibre-call.d cree pour un premier site est retire s'il est vide.
restore() {
    if [ -n "$SITE_PREV" ]; then
        mv -f "$SITE_PREV" "${ROOT}${SITE}"
    elif [ "$SITE_NEW" = 1 ]; then
        rm -f "${ROOT}${SITE}"
        if [ "$LAYOUT" = arch-include ]; then
            rmdir "${ROOT}${INCLUDE_DIR}" 2>/dev/null || true
        fi
    fi
    if [ "$LINK_ADDED" = 1 ]; then
        rm -f "${ROOT}${LINK}"
    fi
    if [ -n "$INCLUDE_BACKUP" ]; then
        mv -f "$INCLUDE_BACKUP" "${ROOT}${NGINX_CONF}"
    fi
    log "Fichiers remis dans leur etat precedent ; nginx n'est pas recharge."
}

# Imprime l'empreinte de ce que nginx doit avoir charge : le site, la
# disposition et la cible du lien.
applied_digest() {
    {
        cat "${ROOT}${SITE}"
        echo "layout ${LAYOUT}"
        if [ -n "$LINK" ]; then
            readlink "${ROOT}${LINK}"
        fi
    } | sha256sum | cut -d ' ' -f 1
}

# record_applied <empreinte> : ecrit APPLIED_FILE, root 0600, par un
# fichier voisin renomme.
record_applied() {
    install -d -m 0755 "${ROOT}${CALL_DIR}"
    (
        umask 077
        printf '%s\n' "$1" > "${ROOT}${APPLIED_FILE}.erplibre-new"
    )
    mv -f "${ROOT}${APPLIED_FILE}.erplibre-new" "${ROOT}${APPLIED_FILE}"
}

# test_and_reload : rien a faire quand rien n'a change, que APPLIED_FILE
# porte l'empreinte du disque et que nginx est actif. Un passage coupe
# entre l'ecriture et le rechargement laisse le site sur disque et
# APPLIED_FILE ancien ou absent : l'ecart recharge. Sinon « nginx -t », juge
# par son code de sortie (nginx peut avertir sur stderr et reussir) : en
# echec, restore puis code 1 et NGINX_ERROR = la premiere ligne [emerg], a
# defaut la derniere. Reussi, APPLIED_FILE est retire, puis « systemctl
# reload nginx » quand nginx tourne, « systemctl enable --now nginx »
# sinon ; RELOADED passe a 1 et APPLIED_DIGEST garde l'empreinte que main
# enregistre une fois l'etat « active » constate.
test_and_reload() {
    local out active=0
    APPLIED_DIGEST=$(applied_digest)
    if [ "$(cat "${ROOT}${APPLIED_FILE}" 2>/dev/null)" != "$APPLIED_DIGEST" ]; then
        CHANGED=1
    fi
    if systemctl is-active --quiet nginx; then
        active=1
    fi
    if [ "$CHANGED" = 0 ] && [ "$active" = 1 ]; then
        log "Site inchange et deja charge : nginx n'est pas recharge."
        return 0
    fi
    if ! out=$(nginx -t 2>&1); then
        printf '%s\n' "$out" >&2
        NGINX_ERROR=$(grep -m 1 -F '[emerg]' <<< "$out" || tail -n 1 <<< "$out")
        restore
        return 1
    fi
    rm -f "${ROOT}${APPLIED_FILE}"
    if [ "$active" = 1 ]; then
        systemctl reload nginx || { NGINX_ERROR="systemctl reload nginx a echoue"; return 1; }
    else
        systemctl enable --now nginx || { NGINX_ERROR="systemctl enable --now nginx a echoue"; return 1; }
    fi
    RELOADED=1
}

# Imprime l'etat systemd de nginx (active, failed, inactive...). Un etat
# transitoire (activating, reloading) est relu chaque seconde, dix fois au
# plus.
service_state() {
    local state tries=0
    while :; do
        state=$(systemctl is-active nginx 2>/dev/null) || true
        case "$state" in
            activating|reloading) ;;
            *) break ;;
        esac
        tries=$((tries + 1))
        if [ "$tries" -ge 10 ]; then
            break
        fi
        sleep 1
    done
    echo "${state:-unknown}"
}

cleanup() {
    local file
    for file in ${TMP_FILES[@]+"${TMP_FILES[@]}"}; do
        rm -f "$file"
    done
}

main() {
    exec 3>&1
    umask 022
    TMP_FILES=()
    trap cleanup EXIT
    check_root
    check_inputs
    detect_os
    FAMILY=$(family)
    ensure_package
    LAYOUT=$(layout)
    SITE=$(site_path)
    LINK=$(link_path)
    echo "@@NGINX_LAYOUT ${LAYOUT}"

    CHANGED=0
    SITE_PREV=""
    SITE_NEW=0
    LINK_ADDED=0
    INCLUDE_BACKUP=""
    RELOADED=0
    NGINX_ERROR=""
    # Tous les refus avant la premiere ecriture.
    check_site
    check_acme_root
    if [ "$LAYOUT" = arch-include ]; then
        ensure_include
    fi
    create_acme_root
    write_site
    echo "@@NGINX_SITE ${SITE}"
    if [ -n "$LINK" ]; then
        echo "@@NGINX_LINK ${LINK}"
    fi

    if ! test_and_reload; then
        echo "[NGINX] ERREUR : ${NGINX_ERROR}" >&2
        echo "@@NGINX failed ${NGINX_ERROR}"
        exit 1
    fi
    local state
    state=$(service_state)
    if [ "$state" != active ]; then
        log "nginx non demarre (${state}) : systemctl status nginx ; journalctl -u nginx -n 30"
        echo "@@NGINX failed nginx ${state}"
        exit 1
    fi
    if [ "$RELOADED" = 1 ]; then
        record_applied "$APPLIED_DIGEST"
    fi
    # Derniere ligne et code de sortie : l'appelant distant ne lit que ca.
    echo "@@NGINX active"
}

main "$@"
