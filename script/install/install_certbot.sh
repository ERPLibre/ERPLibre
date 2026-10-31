#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Obtient le certificat Let's Encrypt de l'infrastructure d'appel ERPLibre
# (lignee certbot « erplibre-call », un seul certificat pour tous les noms
# donnes) et s'assure qu'un minuteur systemd le renouvelle. Supporte :
# Debian, Ubuntu, Arch Linux (et derives), sous systemd.
#
# Usage, deja root, les variables exportees par le script appelant :
#   export CERTBOT_NAMES="ntfy.exemple.test turn.exemple.test"
#   export CERTBOT_METHOD=webroot CERTBOT_WEBROOT=/var/lib/erplibre-call-acme
#   bash install_certbot.sh
#
# Entrees (environnement) :
#   CERTBOT_NAMES        obligatoire : noms du certificat, separes par des
#                        espaces ; noms exacts, sans joker
#   CERTBOT_METHOD       obligatoire : webroot (HTTP-01 par le dossier que
#                        sert nginx), standalone (HTTP-01, certbot ecoute
#                        lui-meme sur 80) ou dns (DNS-01 par un greffon)
#   CERTBOT_WEBROOT      dossier du defi pour webroot, deja servi par nginx
#                        (/var/lib/erplibre-call-acme par defaut)
#   CERTBOT_DNS_PLUGIN   greffon DNS pour dns : cloudflare, digitalocean,
#                        dnsimple, google, linode, luadns, nsone, ovh, rfc2136
#   CERTBOT_DNS_CREDENTIALS
#                        fichier d'identifiants du greffon sur l'hote, mode
#                        0600 (/etc/erplibre-call/dns/<greffon>.ini par
#                        defaut) ; jamais lu ni imprime ici, certbot le lit
#   CERTBOT_EMAIL        courriel du compte Let's Encrypt ; vide : compte
#                        sans courriel (--register-unsafely-without-email),
#                        aucun avis d'expiration ne partira
#   CERTBOT_SKIP_STAGING=1
#                        l'appelant a constate que la lignee porte deja
#                        exactement ces noms : pas d'essai a blanc, la
#                        delivrance garde le certificat tant qu'il n'est pas
#                        a echeance. Sans lignee sur le disque, l'essai a
#                        lieu quand meme.
#
# Sortie lisible par un programme :
#   @@CERTBOT_INSTALLED 1           ce passage a installe le paquet certbot
#   @@CERTBOT_PLUGIN_INSTALLED <p>  ce passage a installe le paquet du greffon
#   @@CERTBOT_UNHELD <fichier>      le fichier de renouvellement mis de cote
#                                   par une desinstallation est remis
#   @@CERTBOT staging-ok            l'essai a blanc a reussi
#   @@CERTBOT_TIMER <unite> added   minuteur active ou pose par l'outil (ce
#                                   passage ou un precedent) : la
#                                   desinstallation l'arrete
#   @@CERTBOT_TIMER <unite> present minuteur du paquet, deja actif
#   @@CERTBOT issued <lignee> | @@CERTBOT unchanged <lignee>
#   @@CERTBOT failed <ligne>
#                                   derniere ligne ; code de sortie non nul
#                                   sur failed, la ligne etant l'erreur de
#                                   certbot (voir last_error_line)
#
# Un essai a blanc (--dry-run, sur le serveur de test de Let's Encrypt)
# precede toute delivrance, avec les memes arguments : un nom qui ne pointe
# pas sur l'hote, un port 80 ferme ou de mauvais identifiants DNS echouent
# la, sans entamer la limite de debit du vrai serveur, et aucune delivrance
# n'est tentee. Jamais le greffon --nginx : il reecrit les sites.

set -euo pipefail

# Prefixe de chaque chemin de l'hote lu ou ecrit, vide hors des tests ; les
# chemins passes a certbot et ecrits dans les unites n'en portent jamais.
ROOT=""
OS_RELEASE="/etc/os-release"
CERT_NAME="erplibre-call"
LINEAGE="/etc/letsencrypt/live/erplibre-call"
RENEWAL_FILE="/etc/letsencrypt/renewal/erplibre-call.conf"
# Suffixe du fichier de renouvellement mis de cote par la desinstallation
# qui garde le certificat : sans ce fichier, « certbot renew » ignore la
# lignee.
HOLD_SUFFIX=".erplibre-hold"
CALL_DIR="/etc/erplibre-call"
# Nom du minuteur du paquet que ce script a active ; la repasse le relit
# pour continuer a le dire « added ».
TIMER_RECORD="/etc/erplibre-call/certbot-timer.added"
SYSTEMD_DIR="/etc/systemd/system"
PACKAGED_UNIT_DIRS="/usr/lib/systemd/system /lib/systemd/system"
# Debian et Ubuntu livrent certbot.timer, deja actif ; Arch livre
# certbot-renew.timer, inactif.
PACKAGED_TIMERS="certbot.timer certbot-renew.timer"
OWN_UNIT="erplibre-call-certbot"
# Premiere ligne des unites ecrites ici : une unite au meme nom qui ne la
# porte pas est etrangere, et n'est jamais remplacee.
MARKER="# erplibre-call: managed"
DNS_PLUGINS="cloudflare digitalocean dnsimple google linode luadns nsone ovh rfc2136"

CERTBOT_NAMES="${CERTBOT_NAMES:-}"
CERTBOT_METHOD="${CERTBOT_METHOD:-}"
CERTBOT_WEBROOT="${CERTBOT_WEBROOT:-/var/lib/erplibre-call-acme}"
CERTBOT_DNS_PLUGIN="${CERTBOT_DNS_PLUGIN:-}"
CERTBOT_DNS_CREDENTIALS="${CERTBOT_DNS_CREDENTIALS:-}"
CERTBOT_EMAIL="${CERTBOT_EMAIL:-}"
CERTBOT_SKIP_STAGING="${CERTBOT_SKIP_STAGING:-}"

log() { echo "[CERTBOT] $*"; }
# Le marqueur part sur le descripteur 3, la sortie du script (ouvert par
# main) : un die dans une substitution $(...) le rend quand meme a
# l'appelant.
die() {
    echo "[CERTBOT] ERREUR : $*" >&2
    echo "@@CERTBOT failed $*" >&3
    exit 1
}

check_root() {
    if [ "$EUID" -ne 0 ]; then
        die "ce script doit tourner en root : sudo bash $0"
    fi
}

# Un nom exact : lettres, chiffres, point et tiret ; ni joker ni espace.
valid_name() {
    [[ "$1" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]]
}

# Un chemin absolu sans espace ni « .. ».
valid_path() {
    case "$1" in
        *..*) return 1 ;;
    esac
    [[ "$1" =~ ^/[A-Za-z0-9._/-]+$ ]]
}

# Remplit NAMES (tableau) depuis CERTBOT_NAMES ; read -a ne developpe aucun
# joker, un « * » reste un mot que valid_name refuse. Verifie aussi les
# fichiers de la methode, avant toute installation : le dossier du defi
# pour webroot, le fichier d'identifiants pour dns (fichier ordinaire, ni
# groupe ni autres n'y ont droit). Le contenu des identifiants n'est
# jamais lu.
check_inputs() {
    read -r -a NAMES <<< "$CERTBOT_NAMES"
    [ "${#NAMES[@]}" -gt 0 ] || die "CERTBOT_NAMES manque (noms du certificat)."
    local name
    for name in "${NAMES[@]}"; do
        valid_name "$name" || die "nom invalide : ${name}"
    done
    if [ -n "$CERTBOT_EMAIL" ]; then
        [[ "$CERTBOT_EMAIL" =~ ^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$ ]] \
            || die "CERTBOT_EMAIL invalide : ${CERTBOT_EMAIL}"
    fi
    case "$CERTBOT_SKIP_STAGING" in
        ''|0|1) ;;
        *) die "CERTBOT_SKIP_STAGING vaut 1, 0 ou vide : ${CERTBOT_SKIP_STAGING}" ;;
    esac
    case "$CERTBOT_METHOD" in
        webroot)
            valid_path "$CERTBOT_WEBROOT" \
                || die "CERTBOT_WEBROOT invalide : ${CERTBOT_WEBROOT}"
            [ -d "${ROOT}${CERTBOT_WEBROOT}" ] \
                || die "dossier du defi absent : ${CERTBOT_WEBROOT} (install_nginx.sh le cree a l'etape acme)."
            ;;
        standalone) ;;
        dns)
            case " ${DNS_PLUGINS} " in
                *" ${CERTBOT_DNS_PLUGIN} "*) [ -n "$CERTBOT_DNS_PLUGIN" ] ;;
                *) false ;;
            esac || die "greffon DNS non propose : ${CERTBOT_DNS_PLUGIN:-vide} (${DNS_PLUGINS})."
            CERTBOT_DNS_CREDENTIALS="${CERTBOT_DNS_CREDENTIALS:-${CALL_DIR}/dns/${CERTBOT_DNS_PLUGIN}.ini}"
            valid_path "$CERTBOT_DNS_CREDENTIALS" \
                || die "CERTBOT_DNS_CREDENTIALS invalide : ${CERTBOT_DNS_CREDENTIALS}"
            local creds="${ROOT}${CERTBOT_DNS_CREDENTIALS}" mode
            if [ -L "$creds" ] || [ ! -f "$creds" ]; then
                die "fichier d'identifiants absent ou pas un fichier ordinaire : ${CERTBOT_DNS_CREDENTIALS}"
            fi
            mode=$(stat -c %a "$creds")
            if (( 8#$mode & 8#077 )); then
                die "${CERTBOT_DNS_CREDENTIALS} est lisible par d'autres comptes (mode ${mode}) ; il doit etre en 0600."
            fi
            ;;
        *) die "CERTBOT_METHOD invalide : ${CERTBOT_METHOD:-vide} (webroot, standalone ou dns)." ;;
    esac
}

# Lit ID et ID_LIKE dans un sous-shell : les autres variables d'os-release
# ne viennent pas remplacer celles du script.
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

# Vrai quand le paquet est installe, d'apres le gestionnaire de FAMILY.
pkg_installed() {
    case "$FAMILY" in
        debian) dpkg-query -W -f='${Status}' "$1" 2>/dev/null | grep -q 'ok installed' ;;
        arch) pacman -Q "$1" >/dev/null 2>&1 ;;
    esac
}

# Debian : reprend une operation dpkg coupee, puis relit les depots, une
# seule fois par passage. --force-confold : une question de dpkg sur un
# fichier de configuration resterait sans reponse au bout d'un ssh.
apt_prepare() {
    [ "$APT_READY" = 1 ] && return 0
    export DEBIAN_FRONTEND=noninteractive
    dpkg --configure -a --force-confdef --force-confold \
        || die "dpkg --configure -a a echoue."
    apt-get update -qq || die "apt-get update a echoue."
    APT_READY=1
}

# Vrai quand les depots Debian proposent une version du paquet : Debian 13
# ne livre que trois des neuf greffons DNS.
apt_has_candidate() {
    local candidate
    candidate=$(apt-cache policy "$1" 2>/dev/null | awk '/Candidate:/ { print $2; exit }')
    [ -n "$candidate" ] && [ "$candidate" != "(none)" ]
}

# pkg_install <paquet> : installe un paquet, sans les recommandations sous
# Debian ; un echec arrete le script.
pkg_install() {
    case "$FAMILY" in
        debian)
            apt_prepare
            apt-get install -y --no-install-recommends \
                -o Dpkg::Options::=--force-confdef \
                -o Dpkg::Options::=--force-confold \
                "$1" || die "apt-get install $1 a echoue."
            ;;
        arch)
            pacman -S --noconfirm --needed "$1" || die "pacman -S $1 a echoue."
            ;;
    esac
}

# Installe certbot quand son binaire ne repond pas au PATH, et le paquet du
# greffon DNS quand la methode est dns et qu'il manque (Debian
# python3-certbot-dns-<p>, Arch certbot-dns-<p>). Sous Debian, un greffon
# absent des depots arrete le script avant toute installation.
ensure_packages() {
    local need_certbot=0 plugin_pkg=""
    if ! command -v certbot >/dev/null 2>&1; then
        need_certbot=1
    fi
    if [ "$CERTBOT_METHOD" = dns ]; then
        case "$FAMILY" in
            debian) plugin_pkg="python3-certbot-dns-${CERTBOT_DNS_PLUGIN}" ;;
            arch) plugin_pkg="certbot-dns-${CERTBOT_DNS_PLUGIN}" ;;
        esac
        if pkg_installed "$plugin_pkg"; then
            plugin_pkg=""
        fi
    fi
    if [ -n "$plugin_pkg" ] && [ "$FAMILY" = debian ]; then
        apt_prepare
        apt_has_candidate "$plugin_pkg" \
            || die "paquet ${plugin_pkg} absent des depots de ce systeme : choisir un autre greffon DNS ou le defi HTTP-01."
    fi
    if [ "$need_certbot" = 1 ]; then
        pkg_install certbot
        echo "@@CERTBOT_INSTALLED 1"
        command -v certbot >/dev/null 2>&1 \
            || die "certbot installe, mais introuvable au PATH."
    fi
    if [ -n "$plugin_pkg" ]; then
        pkg_install "$plugin_pkg"
        echo "@@CERTBOT_PLUGIN_INSTALLED ${plugin_pkg}"
    fi
}

# Remet en place le fichier de renouvellement mis de cote par une
# desinstallation, pour que certbot retrouve la lignee et que le minuteur
# la renouvelle de nouveau. Quand certbot a deja un fichier actif, c'est
# lui qui fait foi : la copie mise de cote est retiree.
unhold_renewal() {
    local active="${ROOT}${RENEWAL_FILE}" held="${ROOT}${RENEWAL_FILE}${HOLD_SUFFIX}"
    [ -e "$held" ] || return 0
    if [ -e "$active" ]; then
        rm -f "$held"
        log "${RENEWAL_FILE} deja actif ; la copie mise de cote est retiree."
        return 0
    fi
    mv -f "$held" "$active"
    echo "@@CERTBOT_UNHELD ${RENEWAL_FILE}"
}

# Imprime, depuis une sortie de certbot lue sur l'entree, la ligne qui dit
# pourquoi il a echoue : la premiere ligne « Detail: » (le motif donne par
# l'autorite, un domaine a la fois), a defaut la derniere ligne non vide.
# Les lignes d'aide que certbot ajoute a chaque echec (« Ask for help... »,
# « See the logfile... ») ne disent rien de la cause et sont sautees.
last_error_line() {
    awk '
        {
            line = $0
            sub(/\r$/, "", line)
            sub(/^[[:space:]]+/, "", line)
            sub(/[[:space:]]+$/, "", line)
        }
        line == "" { next }
        line ~ /^(Ask for help|See the logfile)/ { next }
        detail == "" && line ~ /^Detail:/ { detail = line }
        { last = line }
        END { print (detail != "" ? detail : last) }
    '
}

# run_certbot <argument>... : lance certbot ; sa sortie (stdout et stderr)
# part sur stderr au fil de l'eau, la sortie du script ne portant que les
# marqueurs. En echec, CERTBOT_ERROR recoit last_error_line et le code de
# retour est 1.
run_certbot() {
    local out rc
    out=$(mktemp)
    TMP_FILES+=("$out")
    set +e
    certbot "$@" 2>&1 | tee "$out" >&2
    rc=${PIPESTATUS[0]}
    set -e
    if [ "$rc" -ne 0 ]; then
        CERTBOT_ERROR=$(last_error_line < "$out")
        CERTBOT_ERROR="${CERTBOT_ERROR:-certbot a echoue (code ${rc}) sans message}"
        return 1
    fi
}

# Remplit les arguments communs a l'essai et a la delivrance, que leurs
# drapeaux propres separent : HEAD_ARGS (mode sans question, conditions
# acceptees, lignee) et TAIL_ARGS (methode, compte, noms ; le premier nom
# donne le CN).
build_args() {
    HEAD_ARGS=(--non-interactive --agree-tos --cert-name "$CERT_NAME")
    TAIL_ARGS=()
    case "$CERTBOT_METHOD" in
        webroot) TAIL_ARGS+=(--webroot -w "$CERTBOT_WEBROOT") ;;
        standalone) TAIL_ARGS+=(--standalone) ;;
        dns) TAIL_ARGS+=("--dns-${CERTBOT_DNS_PLUGIN}"
                    "--dns-${CERTBOT_DNS_PLUGIN}-credentials" "$CERTBOT_DNS_CREDENTIALS") ;;
    esac
    if [ -n "$CERTBOT_EMAIL" ]; then
        TAIL_ARGS+=(--email "$CERTBOT_EMAIL" --no-eff-email)
    else
        log "Compte Let's Encrypt sans courriel : aucun avis d'expiration ni de revocation ne sera envoye."
        TAIL_ARGS+=(--register-unsafely-without-email)
    fi
    local name
    for name in "${NAMES[@]}"; do
        TAIL_ARGS+=(-d "$name")
    done
}

# Imprime la cible du lien cert.pem de la lignee (archive/.../certN.pem),
# vide sans lignee : une delivrance avance N, un certificat garde le laisse.
lineage_version() {
    readlink "${ROOT}${LINEAGE}/cert.pem" 2>/dev/null || true
}

# Imprime le premier minuteur livre par le paquet certbot, vide sans.
packaged_timer() {
    local unit dir
    for unit in $PACKAGED_TIMERS; do
        for dir in $PACKAGED_UNIT_DIRS; do
            if [ -f "${ROOT}${dir}/${unit}" ]; then
                echo "$unit"
                return 0
            fi
        done
    done
}

# Imprime le chemin absolu de certbot pour ExecStart, /usr/bin/certbot
# quand celui du PATH porte un caractere qu'une unite lirait autrement.
certbot_bin() {
    local bin
    bin=$(command -v certbot 2>/dev/null || true)
    if [[ "$bin" =~ ^/[A-Za-z0-9._/+-]+$ ]]; then
        echo "$bin"
    else
        echo /usr/bin/certbot
    fi
}

own_service_text() {
    cat <<EOF
${MARKER}
# Ecrit par install_certbot.sh : le paquet certbot ne livre aucun minuteur.
[Unit]
Description=Renouvellement des certificats Let's Encrypt (erplibre-call)
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
ExecStart=$(certbot_bin) renew --quiet
PrivateTmp=true
EOF
}

# Deux fois par jour, comme les minuteurs des paquets, decale au hasard
# sur 12 h pour etaler la charge de Let's Encrypt ; Persistent rattrape un
# passage manque pendant un arret.
own_timer_text() {
    cat <<EOF
${MARKER}
# Ecrit par install_certbot.sh : le paquet certbot ne livre aucun minuteur.
[Unit]
Description=Renouvellement Let's Encrypt deux fois par jour (erplibre-call)

[Timer]
OnCalendar=*-*-* 00,12:00:00
RandomizedDelaySec=12h
Persistent=true

[Install]
WantedBy=timers.target
EOF
}

# write_unit <nom> <texte> : ecrit l'unite 0644 par un voisin renomme ; un
# texte identique laisse le fichier tel quel. UNITS_CHANGED passe a 1 a
# toute ecriture.
write_unit() {
    local path="${ROOT}${SYSTEMD_DIR}/$1" tmp
    mkdir -p "$(dirname "$path")"
    tmp=$(mktemp "$(dirname "$path")/.$1.XXXXXX")
    TMP_FILES+=("$tmp")
    printf '%s\n' "$2" > "$tmp"
    chmod 0644 "$tmp"
    if cmp -s "$tmp" "$path"; then
        rm -f "$tmp"
        return 0
    fi
    mv -f "$tmp" "$path"
    UNITS_CHANGED=1
    log "Unite ecrite : ${SYSTEMD_DIR}/$1"
}

# record_timer <unite> : note dans TIMER_RECORD le minuteur du paquet que
# ce passage vient d'activer.
record_timer() {
    [ -d "${ROOT}${CALL_DIR}" ] || install -d -m 0755 "${ROOT}${CALL_DIR}"
    printf '%s\n' "$1" > "${ROOT}${TIMER_RECORD}.erplibre-new"
    mv -f "${ROOT}${TIMER_RECORD}.erplibre-new" "${ROOT}${TIMER_RECORD}"
}

# ensure_timer : le minuteur du paquet quand il en livre un, active et
# demarre s'il ne l'est pas (« added » quand l'outil l'a active, ce
# passage ou un precedent d'apres TIMER_RECORD ; « present » sinon). Sans
# minuteur du paquet, OWN_UNIT.{service,timer} dans SYSTEMD_DIR, toujours
# « added » : une unite qui ne porte pas MARKER arrete le script avant
# toute ecriture.
ensure_timer() {
    local unit enabled=0 active=0
    unit=$(packaged_timer)
    if [ -n "$unit" ]; then
        if systemctl is-enabled --quiet "$unit"; then
            enabled=1
        fi
        if systemctl is-active --quiet "$unit"; then
            active=1
        fi
        if [ "$enabled" = 0 ]; then
            systemctl enable --now "$unit" \
                || die "systemctl enable --now ${unit} a echoue."
            record_timer "$unit"
        elif [ "$active" = 0 ]; then
            systemctl start "$unit" || die "systemctl start ${unit} a echoue."
        fi
        if [ "$(cat "${ROOT}${TIMER_RECORD}" 2>/dev/null)" = "$unit" ]; then
            echo "@@CERTBOT_TIMER ${unit} added"
        else
            echo "@@CERTBOT_TIMER ${unit} present"
        fi
        return 0
    fi
    unit="${OWN_UNIT}.timer"
    local name path
    for name in "${OWN_UNIT}.service" "$unit"; do
        path="${ROOT}${SYSTEMD_DIR}/${name}"
        if [ -L "$path" ] || { [ -e "$path" ] && [ "$(head -n 1 "$path")" != "$MARKER" ]; }; then
            die "${SYSTEMD_DIR}/${name} existe et n'a pas ete ecrit par erplibre-call ; rien n'est ecrit."
        fi
    done
    UNITS_CHANGED=0
    write_unit "${OWN_UNIT}.service" "$(own_service_text)"
    write_unit "$unit" "$(own_timer_text)"
    if [ "$UNITS_CHANGED" = 1 ]; then
        systemctl daemon-reload || die "systemctl daemon-reload a echoue."
    fi
    if systemctl is-enabled --quiet "$unit"; then
        enabled=1
    fi
    if systemctl is-active --quiet "$unit"; then
        active=1
    fi
    if [ "$enabled" = 0 ] || [ "$active" = 0 ]; then
        systemctl enable --now "$unit" \
            || die "systemctl enable --now ${unit} a echoue."
    fi
    echo "@@CERTBOT_TIMER ${unit} added"
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
    APT_READY=0
    CERTBOT_ERROR=""
    trap cleanup EXIT
    check_root
    # Tous les refus avant la premiere installation.
    check_inputs
    detect_os
    FAMILY=$(family)
    ensure_packages
    unhold_renewal
    build_args

    local before after verdict
    before=$(lineage_version)
    if [ "$CERTBOT_SKIP_STAGING" = 1 ] && [ -n "$before" ]; then
        log "Lignee deja en place avec ces noms : pas d'essai a blanc."
    else
        if [ "$CERTBOT_SKIP_STAGING" = 1 ]; then
            log "Aucune lignee ${LINEAGE} : l'essai a blanc a lieu quand meme."
        fi
        log "Essai a blanc sur le serveur de test de Let's Encrypt..."
        run_certbot certonly --dry-run "${HEAD_ARGS[@]}" "${TAIL_ARGS[@]}" \
            || die "$CERTBOT_ERROR"
        echo "@@CERTBOT staging-ok"
    fi
    log "Delivrance du certificat ${CERT_NAME}..."
    run_certbot certonly "${HEAD_ARGS[@]}" --keep-until-expiring --expand \
        "${TAIL_ARGS[@]}" || die "$CERTBOT_ERROR"
    if [ ! -e "${ROOT}${LINEAGE}/fullchain.pem" ] || [ ! -e "${ROOT}${LINEAGE}/privkey.pem" ]; then
        die "certbot a reussi, mais ${LINEAGE}/fullchain.pem ou privkey.pem manque."
    fi
    after=$(lineage_version)
    if [ "$after" != "$before" ]; then
        verdict=issued
    else
        verdict=unchanged
    fi

    ensure_timer
    # Derniere ligne et code de sortie : l'appelant distant ne lit que ca.
    echo "@@CERTBOT ${verdict} ${LINEAGE}"
}

main "$@"
