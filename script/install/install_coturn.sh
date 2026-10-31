#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Installe coturn (serveur STUN/TURN) par les paquets du systeme, sous
# systemd, pour l'infrastructure d'appel ERPLibre.
# Supporte : Debian, Ubuntu, Arch Linux (et derives). Tout autre systeme
# arrete le script avant qu'il ne touche a quoi que ce soit.
#
# Usage, deja root, les variables exportees par le script appelant :
#   export TURN_REALM=turn.exemple.test TURN_CHECK_PASSWORD=...
#   bash install_coturn.sh
#
# Entrees (environnement) :
#   TURN_REALM            obligatoire : nom public du service, realm TURN
#   TURN_PORT             3478, udp et tcp
#   TURN_TLS_PORT         5349, tcp, ecoute seulement avec un certificat
#   TURN_MIN_PORT         49152 } plage udp des relais
#   TURN_MAX_PORT         49252 }
#   TURN_CERT_FILE        certificat et cle, les deux ou aucun ; copies dans
#   TURN_KEY_FILE         /etc/erplibre-call/tls, lisibles du compte coturn
#   TURN_EXTERNAL_IP      optionnel : adresse publique, derriere un NAT
#   TURN_CHECK_PASSWORD   obligatoire : mot de passe du compte de controle
#                         « erplibre-check ». Lu de l'environnement, jamais
#                         d'un argument ; main le retire de l'environnement
#                         des commandes lancees ensuite.
#   TURN_GARDER_CONFIG=1  une configuration coturn deja en place, que ce
#                         script n'a pas ecrite, est remplacee : l'appelant
#                         en garde une copie et a fait accepter le
#                         changement. Sans lui, elle arrete le script avant
#                         toute installation.
#
# Les comptes vivent dans la base SQLite de coturn (userdb), jamais dans
# turnserver.conf : coturn la relit a chaque allocation, un compte ajoute ou
# retire prend effet sans redemarrage. La configuration porte lt-cred-mech
# et PAS use-auth-secret : avec use-auth-secret, coturn 4.6 refuse tout
# compte long terme, meme quand la base ne contient aucun secret.
#
# Le compte de controle est ecrit par sqlite3, la requete sur l'entree
# standard, et non par « turnadmin -p » : un argument se lit de tout compte
# local (ps, /proc/<pid>/cmdline), le temps que la commande tourne.
#
# Sortie : « @@UNIT <unite> », « @@USER <compte> », « @@CONFIG <chemin> »,
# puis en derniere ligne « @@ACTIVE coturn <etat> ». Code de sortie non nul
# quand l'etat n'est pas « active ».

set -euo pipefail

# Premiere ligne de toute configuration ecrite ici : une configuration qui
# la porte se reecrit sans demander, une autre est etrangere.
MARKER="# erplibre-call: managed"
CALL_DIR="/etc/erplibre-call"
TLS_DIR="/etc/erplibre-call/tls"
DB_DIR="/var/lib/erplibre-call"
DB_FILE="/var/lib/erplibre-call/turndb"
CHECK_USER="erplibre-check"
OS_RELEASE="/etc/os-release"
# Chemins des paquets quand l'unite ne nomme pas sa configuration (-c).
DEBIAN_CONF="/etc/turnserver.conf"
ARCH_CONF="/etc/turnserver/turnserver.conf"
DEFAULT_FILE="/etc/default/coturn"
# Empreinte de la configuration et du certificat que coturn a charges, ecrite
# seulement apres un redemarrage reussi (voir main).
APPLIED_FILE="/etc/erplibre-call/coturn.applied"

TURN_REALM="${TURN_REALM:-}"
TURN_PORT="${TURN_PORT:-3478}"
TURN_TLS_PORT="${TURN_TLS_PORT:-5349}"
TURN_MIN_PORT="${TURN_MIN_PORT:-49152}"
TURN_MAX_PORT="${TURN_MAX_PORT:-49252}"
TURN_CERT_FILE="${TURN_CERT_FILE:-}"
TURN_KEY_FILE="${TURN_KEY_FILE:-}"
TURN_EXTERNAL_IP="${TURN_EXTERNAL_IP:-}"
TURN_CHECK_PASSWORD="${TURN_CHECK_PASSWORD:-}"
TURN_GARDER_CONFIG="${TURN_GARDER_CONFIG:-}"

log() { echo "[COTURN] $*"; }
die() { echo "[COTURN] ERREUR : $*" >&2; exit 1; }

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

has_cert() {
    [ -n "$TURN_CERT_FILE" ] && [ -n "$TURN_KEY_FILE" ]
}

# Chaque entree finit dans turnserver.conf ou dans une requete SQL : le
# realm et l'adresse externe sont limites a des caracteres qui ne peuvent
# ni ouvrir une ligne de configuration ni fermer une chaine SQL.
check_inputs() {
    [ -n "$TURN_REALM" ] || die "TURN_REALM manque (nom public du service)."
    if ! [[ "$TURN_REALM" =~ ^[A-Za-z0-9]([A-Za-z0-9.:-]*[A-Za-z0-9])?$ ]]; then
        die "TURN_REALM invalide : lettres, chiffres, point, deux-points et tiret seulement."
    fi
    [ -n "$TURN_CHECK_PASSWORD" ] || die "TURN_CHECK_PASSWORD manque (compte de controle)."
    local port
    for port in "$TURN_PORT" "$TURN_TLS_PORT" "$TURN_MIN_PORT" "$TURN_MAX_PORT"; do
        valid_port "$port" || die "port invalide : ${port} (1 a 65535)."
    done
    [ "$TURN_MIN_PORT" -le "$TURN_MAX_PORT" ] \
        || die "plage de relais inversee : ${TURN_MIN_PORT}-${TURN_MAX_PORT}."
    if [ -n "$TURN_CERT_FILE" ] || [ -n "$TURN_KEY_FILE" ]; then
        has_cert || die "TURN_CERT_FILE et TURN_KEY_FILE vont ensemble."
        [ -f "$TURN_CERT_FILE" ] && [ -r "$TURN_CERT_FILE" ] \
            || die "certificat illisible : ${TURN_CERT_FILE}"
        [ -f "$TURN_KEY_FILE" ] && [ -r "$TURN_KEY_FILE" ] \
            || die "cle illisible : ${TURN_KEY_FILE}"
        [ "$TURN_PORT" != "$TURN_TLS_PORT" ] \
            || die "TURN_PORT et TURN_TLS_PORT doivent differer."
    fi
    if [ -n "$TURN_EXTERNAL_IP" ] && ! [[ "$TURN_EXTERNAL_IP" =~ ^[0-9A-Fa-f:./]+$ ]]; then
        die "TURN_EXTERNAL_IP invalide : ${TURN_EXTERNAL_IP}"
    fi
}

# Lit ID et ID_LIKE dans un sous-shell : les autres variables d'os-release
# (NAME, VERSION...) ne viennent pas remplacer celles du script.
detect_os() {
    [ -f "$OS_RELEASE" ] || die "systeme non identifie (pas de ${OS_RELEASE})."
    OS=$(. "$OS_RELEASE" && echo "${ID:-}")
    OS_LIKE=$(. "$OS_RELEASE" && echo "${ID_LIKE:-}")
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

unit_name() {
    case "$FAMILY" in
        debian) echo coturn ;;
        arch) echo turnserver ;;
    esac
}

# Texte de l'unite installee, fragments compris ; vide quand elle n'existe
# pas encore.
unit_text() {
    systemctl cat "$UNIT" 2>/dev/null || true
}

# Debian cree le compte « turnserver » ; Arch le declare dans l'unite du
# paquet (User=), relue pour suivre un changement de nom.
service_user() {
    local user=""
    if [ "$FAMILY" = arch ]; then
        user=$(unit_text | sed -n 's/^[[:space:]]*User=[[:space:]]*//p' | tail -n 1)
    fi
    echo "${user:-turnserver}"
}

# Le fichier que coturn lit : celui que l'unite passe en -c, sinon celui du
# paquet de la famille.
config_path() {
    local path
    path=$(unit_text | sed -n -E 's/^ExecStart=.*[[:space:]](-c|--conf-file)[[:space:]=]+([^[:space:]]+).*/\2/p' | tail -n 1)
    if [ -z "$path" ]; then
        case "$FAMILY" in
            debian) path="$DEBIAN_CONF" ;;
            arch) path="$ARCH_CONF" ;;
        esac
    fi
    echo "$path"
}

# config_is_foreign <chemin> : vrai pour un fichier non vide dont la
# premiere ligne n'est pas MARKER.
config_is_foreign() {
    [ -s "$1" ] && [ "$(head -n 1 "$1")" != "$MARKER" ]
}

# Vrai quand coturn et sqlite3 sont deja installes : rien n'est alors mis a
# jour, une relance ne change pas la version en service (sur Arch, une mise
# a jour isolee d'un paquet est une mise a jour partielle).
packages_present() {
    case "$FAMILY" in
        debian)
            [ "$(dpkg-query -W -f='${Status}\n' coturn sqlite3 2>/dev/null \
                | grep -c 'install ok installed')" = 2 ]
            ;;
        arch)
            pacman -Q coturn sqlite >/dev/null 2>&1
            ;;
    esac
}

# --force-confold : un fichier de configuration modifie ferait poser une
# question a dpkg sur le terminal, sans reponse au bout d'un ssh.
install_packages() {
    if packages_present; then
        log "coturn et sqlite3 deja installes."
        return 0
    fi
    case "$FAMILY" in
        debian)
            export DEBIAN_FRONTEND=noninteractive
            apt-get update -qq
            apt-get install -y --no-install-recommends \
                -o Dpkg::Options::=--force-confdef \
                -o Dpkg::Options::=--force-confold \
                coturn sqlite3
            ;;
        arch)
            pacman -S --noconfirm --needed coturn sqlite
            ;;
    esac
}

# Copie certificat et cle dans TLS_DIR, root:<groupe coturn> 0640 : le
# compte coturn ne lit ni /home (unite Debian) ni les cles de Let's Encrypt.
# Sans certificat, les copies d'une installation precedente sont retirees.
# CONFIG_CHANGED passe a 1 quand le contenu servi change.
install_certificate() {
    local crt="$TLS_DIR/turn.crt" key="$TLS_DIR/turn.key"
    if ! has_cert; then
        if [ -e "$crt" ] || [ -e "$key" ]; then
            rm -f "$crt" "$key"
            CONFIG_CHANGED=1
        fi
        return 0
    fi
    install -d -m 0755 -o root -g root "$CALL_DIR"
    install -d -m 0750 -o root -g "$SERVICE_GROUP" "$TLS_DIR"
    if ! cmp -s "$TURN_CERT_FILE" "$crt" || ! cmp -s "$TURN_KEY_FILE" "$key"; then
        CONFIG_CHANGED=1
    fi
    install -m 0640 -o root -g "$SERVICE_GROUP" "$TURN_CERT_FILE" "$crt"
    install -m 0640 -o root -g "$SERVICE_GROUP" "$TURN_KEY_FILE" "$key"
}

# refuse_linked_config <chemin> : arrete le script quand la configuration
# est un lien symbolique. Le fichier vise n'est pas celui que l'outil gere,
# et le renommage final remplacerait le lien sans toucher sa cible.
refuse_linked_config() {
    if [ -L "$1" ]; then
        die "${1} est un lien symbolique ; rien n'est ecrit."
    fi
}

# write_config <chemin> : ecrit la configuration complete, root:<groupe
# coturn> 0640, par un fichier voisin renomme (coturn ne lit jamais un
# fichier a moitie ecrit). Le voisin vient de mktemp : un nom neuf, cree en
# exclusif et 0600, qu'aucun lien pose d'avance ne peut detourner vers un
# autre fichier. CONFIG_CHANGED passe a 1 quand le contenu change.
# Sans certificat, no-tls et no-dtls : aucun port TLS n'ecoute. Les quatre
# dernieres lignes sont celles du fichier livre par Debian, qu'il remplace :
# journal systeme, et pas de reponses STUN plus grosses que les requetes
# (amplification).
write_config() {
    local conf="$1" dir tmp
    refuse_linked_config "$conf"
    dir=$(dirname "$conf")
    mkdir -p "$dir"
    tmp=$(mktemp "${dir}/.$(basename "$conf").XXXXXX")
    {
        echo "$MARKER"
        echo "# Comptes dans userdb, pas ici. Ecrit par install_coturn.sh."
        echo "listening-port=${TURN_PORT}"
        if has_cert; then
            echo "tls-listening-port=${TURN_TLS_PORT}"
            echo "cert=${TLS_DIR}/turn.crt"
            echo "pkey=${TLS_DIR}/turn.key"
        else
            echo "no-tls"
            echo "no-dtls"
        fi
        echo "min-port=${TURN_MIN_PORT}"
        echo "max-port=${TURN_MAX_PORT}"
        echo "fingerprint"
        echo "lt-cred-mech"
        echo "realm=${TURN_REALM}"
        echo "userdb=${DB_FILE}"
        echo "no-cli"
        echo "no-multicast-peers"
        if [ -n "$TURN_EXTERNAL_IP" ]; then
            echo "external-ip=${TURN_EXTERNAL_IP}"
        fi
        echo "syslog"
        echo "no-rfc5780"
        echo "no-stun-backward-compatibility"
        echo "response-origin-only-with-rfc5780"
    } > "$tmp"
    chown "root:${SERVICE_GROUP}" "$tmp"
    chmod 0640 "$tmp"
    if ! cmp -s "$tmp" "$conf"; then
        CONFIG_CHANGED=1
    fi
    mv -f "$tmp" "$conf"
    log "Configuration ecrite : ${conf}"
}

# L'ancien script d'init Debian ne demarre coturn qu'avec cette ligne ;
# l'unite systemd l'ignore, la poser garde les deux d'accord.
enable_default() {
    [ "$FAMILY" = debian ] || return 0
    [ -f "$DEFAULT_FILE" ] || return 0
    if grep -qE '^[[:space:]]*#?[[:space:]]*TURNSERVER_ENABLED=' "$DEFAULT_FILE"; then
        sed -i -E 's/^[[:space:]]*#?[[:space:]]*TURNSERVER_ENABLED=.*/TURNSERVER_ENABLED=1/' "$DEFAULT_FILE"
    else
        echo "TURNSERVER_ENABLED=1" >> "$DEFAULT_FILE"
    fi
}

# Le dossier de la base appartient au compte coturn : SQLite y cree son
# journal, et un lecteur qui trouve un journal laisse par une ecriture
# interrompue doit pouvoir y ecrire. Ce compte peut donc y poser un lien :
# une base qui est un lien est refusee, et chown -h ne suit rien.
prepare_database() {
    install -d -m 0750 -o "$SERVICE_USER" -g "$SERVICE_GROUP" "$DB_DIR"
    if [ -L "$DB_FILE" ] || { [ -e "$DB_FILE" ] && [ ! -f "$DB_FILE" ]; }; then
        die "${DB_FILE} n'est pas un fichier ordinaire ; rien n'est ecrit."
    fi
    if [ -f "$DB_FILE" ]; then
        chown -h "${SERVICE_USER}:${SERVICE_GROUP}" "$DB_FILE"
    fi
}

# Pose le compte de controle, idempotent : la ligne de CHECK_USER est
# effacee (quel que soit son realm) puis recreee, dans une transaction.
# hmackey = MD5 hex de « utilisateur:realm:mot de passe », la cle long
# terme que turnadmin -a ecrirait. printf est une commande interne : le
# mot de passe n'atteint md5sum que par le tube. La requete passe sur
# l'entree standard de sqlite3, lance sous le compte coturn (runuser) :
# root n'ouvre aucun fichier du dossier de ce compte. Le schema est celui
# que coturn 4.6 cree lui-meme ; IF NOT EXISTS laisse en place une base
# deja creee par coturn.
ensure_check_user() {
    local key
    key=$(printf '%s:%s:%s' "$CHECK_USER" "$TURN_REALM" "$TURN_CHECK_PASSWORD" | md5sum | cut -d ' ' -f 1)
    [[ "$key" =~ ^[0-9a-f]{32}$ ]] || die "cle du compte de controle non calculee."
    runuser -u "$SERVICE_USER" -- sqlite3 -bail -init /dev/null "$DB_FILE" <<EOF
.timeout 5000
CREATE TABLE IF NOT EXISTS turnusers_lt ( realm varchar(127) default '', name varchar(512), hmackey char(128), PRIMARY KEY (realm,name));
CREATE TABLE IF NOT EXISTS turn_secret (realm varchar(127) default '', value varchar(127), primary key (realm,value));
CREATE TABLE IF NOT EXISTS allowed_peer_ip (realm varchar(127) default '', ip_range varchar(256), primary key (realm,ip_range));
CREATE TABLE IF NOT EXISTS denied_peer_ip (realm varchar(127) default '', ip_range varchar(256), primary key (realm,ip_range));
CREATE TABLE IF NOT EXISTS turn_origin_to_realm (origin varchar(127),realm varchar(127),primary key (origin));
CREATE TABLE IF NOT EXISTS turn_realm_option (realm varchar(127) default '', opt varchar(32), value varchar(128), primary key (realm,opt));
CREATE TABLE IF NOT EXISTS oauth_key (kid varchar(128),ikm_key varchar(256),timestamp bigint default 0,lifetime integer default 0,as_rs_alg varchar(64) default '',realm varchar(127) default '',primary key (kid));
CREATE TABLE IF NOT EXISTS admin_user (name varchar(32), realm varchar(127), password varchar(127), primary key (name));
BEGIN;
DELETE FROM turnusers_lt WHERE name='${CHECK_USER}';
INSERT INTO turnusers_lt (realm, name, hmackey) VALUES ('${TURN_REALM}', '${CHECK_USER}', '${key}');
COMMIT;
EOF
    log "Compte de controle ${CHECK_USER} pose dans ${DB_FILE} (realm ${TURN_REALM})."
}

# applied_digest <chemin> : imprime l'empreinte sha256 de ce que coturn
# charge au demarrage, la configuration puis, avec un certificat, le
# certificat et la cle copies dans TLS_DIR ; une ligne par fichier.
applied_digest() {
    if has_cert; then
        sha256sum "$1" "$TLS_DIR/turn.crt" "$TLS_DIR/turn.key"
    else
        sha256sum "$1"
    fi
}

# record_applied <empreinte> : ecrit APPLIED_FILE, root 0600, par un fichier
# voisin renomme ; le dossier appartient a root, aucun autre compte n'y pose
# de lien.
record_applied() {
    install -d -m 0755 -o root -g root "$CALL_DIR"
    (
        umask 077
        printf '%s\n' "$1" > "$APPLIED_FILE.erplibre-new"
    )
    mv -f "$APPLIED_FILE.erplibre-new" "$APPLIED_FILE"
}

# Redemarre seulement quand CONFIG_CHANGED vaut 1 : un redemarrage coupe les
# appels en cours, et un compte change dans la base n'en demande pas. Sinon
# « start », sans effet sur un service actif. Un echec n'arrete pas le
# script : service_state dit ensuite l'etat reel.
enable_service() {
    systemctl enable "$UNIT" || log "AVERTISSEMENT : systemctl enable ${UNIT} a echoue."
    if [ "$CONFIG_CHANGED" = 1 ]; then
        systemctl restart "$UNIT" || log "AVERTISSEMENT : systemctl restart ${UNIT} a echoue."
    else
        log "Configuration inchangee : ${UNIT} n'est pas redemarre."
        systemctl start "$UNIT" || log "AVERTISSEMENT : systemctl start ${UNIT} a echoue."
    fi
    sleep 1
}

# Imprime l'etat systemd de l'unite (active, failed, inactive...). Un etat
# transitoire (activating, reloading) est relu chaque seconde, dix fois au
# plus : un service qui plante et que systemd relance reste « activating »
# et finit rendu tel quel, donc en echec.
service_state() {
    local state tries=0
    while :; do
        state=$(systemctl is-active "$UNIT" 2>/dev/null) || true
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

main() {
    # Le mot de passe reste une variable du shell : aucune commande lancee
    # ensuite ne le recoit dans son environnement.
    export -n TURN_CHECK_PASSWORD
    check_root
    check_inputs
    detect_os
    FAMILY=$(family)
    UNIT=$(unit_name)

    local conf state
    conf=$(config_path)
    refuse_linked_config "$conf"
    if config_is_foreign "$conf" && [ "$TURN_GARDER_CONFIG" != 1 ]; then
        die "${conf} existe et n'a pas ete ecrit par erplibre-call ; le garder de cote puis relancer avec TURN_GARDER_CONFIG=1."
    fi

    install_packages
    SERVICE_USER=$(service_user)
    id -u "$SERVICE_USER" >/dev/null 2>&1 \
        || die "compte de service introuvable : ${SERVICE_USER}"
    SERVICE_GROUP=$(id -gn "$SERVICE_USER")
    # L'unite du paquet existe maintenant : elle dit quel fichier coturn lit.
    conf=$(config_path)

    CONFIG_CHANGED=0
    install_certificate
    write_config "$conf"
    enable_default
    # Le compte AVANT le demarrage : le service lit une base deja prete.
    prepare_database
    ensure_check_user

    # Le fichier sur disque n'est pas forcement celui que coturn a charge : un
    # passage interrompu entre write_config et le redemarrage laisse la
    # nouvelle configuration en place et coturn sur l'ancienne. APPLIED_FILE
    # n'existe, avec l'empreinte du disque, qu'apres un redemarrage suivi de
    # l'etat « active » ; tout ecart redemarre. Il est retire AVANT le
    # redemarrage : une coupure pendant celui-ci ne laisse aucune empreinte.
    local applied
    applied=$(applied_digest "$conf")
    if [ "$(cat "$APPLIED_FILE" 2>/dev/null)" != "$applied" ]; then
        CONFIG_CHANGED=1
    fi
    if [ "$CONFIG_CHANGED" = 1 ]; then
        rm -f "$APPLIED_FILE"
    fi
    enable_service
    state=$(service_state)
    if [ "$state" = active ] && [ "$CONFIG_CHANGED" = 1 ]; then
        record_applied "$applied"
    fi

    echo "@@UNIT ${UNIT}"
    echo "@@USER ${SERVICE_USER}"
    echo "@@CONFIG ${conf}"
    if [ "$state" != active ]; then
        log "coturn installe mais non demarre (${state}) : systemctl status ${UNIT} ; journalctl -u ${UNIT} -n 30"
    fi
    # Derniere ligne et code de sortie : l'appelant distant ne lit que ca.
    echo "@@ACTIVE coturn ${state}"
    [ "$state" = active ]
}

main "$@"
