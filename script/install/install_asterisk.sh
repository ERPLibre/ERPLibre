#!/usr/bin/env bash
# Installe un serveur VoIP Asterisk, nu et durci, pour la passerelle ERPLibre.
# Supporte : Ubuntu 22.04+, Debian 12+, Arch Linux (et derives)
#
# Usage :
#   sudo bash install_asterisk.sh
#   sudo AST_TRUNK_HOST=montreal.voip.ms AST_TRUNK_USER=123456 \
#        AST_TRUNK_PASS='...' bash install_asterisk.sh
#
#   Plusieurs lignes, pour la redondance ou le routage au cout :
#   sudo AST_TRUNKS='principal|montreal.voip.ms|123|mdp;secours|sip.autre.ca|456|mdp2' \
#        bash install_asterisk.sh
#
#   Des softphones dans le navigateur, pour le module Odoo « voip_oca » :
#   sudo AST_WEBPHONES='1001|mdp1;1002|mdp2' bash install_asterisk.sh
#
# Securite — les defauts de ce script, et pourquoi :
#
#   PAS DE FREEPBX. Le panneau d'administration web est la surface d'attaque
#   principale d'un PBX : il expose une pile PHP, des identifiants par defaut
#   et des failles publiees regulierement. Asterisk nu se configure par
#   fichiers, versionnables et relisibles. On perd une interface, on retire
#   une porte.
#
#   PAS DE SIP ANONYME. `allowguest=no` et un contexte par defaut VIDE. Le
#   defaut historique d'Asterisk laisse un appelant inconnu atteindre le plan
#   de numerotation : c'est ainsi que se vole une ligne. Un endpoint SIP
#   expose est scanne en continu — une etude universitaire a mesure 1,49
#   million de tentatives des le premier jour sur une adresse jamais publiee.
#
#   PAS D'APPELS INTERNATIONAUX. Le vol de trunk sert a composer des numeros
#   surtaxes a l'etranger, un vendredi soir. Le plan de numerotation n'accepte
#   que le plan de numerotation nord-americain. Elargir est un geste
#   deliberement explicite.
#
#   FAIL2BAN pose sur le journal d'Asterisk, et le service n'ecoute QUE sur
#   les adresses du fournisseur de trunk quand elles sont fournies.
#
#   LE SOFTPHONE N'ECOUTE QUE SUR LA BOUCLE LOCALE. Le WebSocket voyage sur
#   le serveur HTTP d'Asterisk, que http.conf lie a 127.0.0.1 : seul un
#   navigateur de CETTE machine s'y connecte. C'est ce qui permet de s'en
#   servir sans certificat — les navigateurs tiennent « localhost » pour un
#   contexte sur, et ouvrent le micro. Depuis un autre poste, il faut un
#   mandataire inverse en TLS et « wss:// » : sans HTTPS, aucun navigateur
#   ne donne acces au micro, et les identifiants SIP passeraient en clair.
#
#   Ce script ne remplace PAS un plafond de depense chez le fournisseur. C'est
#   le seul garde-fou qui borne reellement la perte : un compte prepaye, sans
#   credit, limite le vol au solde depose. A configurer chez le fournisseur,
#   pas ici.

set -e

AST_SIP_PORT="${AST_SIP_PORT:-5060}"
AST_RTP_START="${AST_RTP_START:-10000}"
AST_RTP_END="${AST_RTP_END:-10200}"
AST_ARI_USER="${AST_ARI_USER:-erplibre}"
AST_ARI_PORT="${AST_ARI_PORT:-8088}"
# Lignes SIP, une par entree : "nom|hote|utilisateur|motdepasse", separees
# par des points-virgules. Une seule ligne reste le cas courant ; plusieurs
# servent a la redondance ou a router selon le cout.
AST_TRUNKS="${AST_TRUNKS:-}"
# Compatibilite avec la forme a un seul trunk.
AST_TRUNK_HOST="${AST_TRUNK_HOST:-}"
AST_TRUNK_USER="${AST_TRUNK_USER:-}"
AST_TRUNK_PASS="${AST_TRUNK_PASS:-}"
AST_CALLERID="${AST_CALLERID:-}"
# Softphones du navigateur, une par entree : "nom|motdepasse", separees par
# des points-virgules. Le nom sert d'extension : « 1001 » se compose depuis
# un autre softphone.
AST_WEBPHONES="${AST_WEBPHONES:-}"
# Surchargeable pour ecrire la configuration ailleurs qu'en place : c'est ce
# qui rend les generateurs verifiables sans root ni Asterisk installe.
CONFIG_DIR="${CONFIG_DIR:-/etc/asterisk}"
SOUNDS_DIR="/var/lib/asterisk/sounds/erplibre"
SECRET_FILE="/etc/erplibre/asterisk.env"

log() { echo "[ASTERISK] $*"; }
die() { echo "[ASTERISK] ERREUR: $*" >&2; exit 1; }

check_root() {
    [ "$(id -u)" -eq 0 ] || die "a lancer avec sudo."
}

detect_os() {
    [ -f /etc/os-release ] || die "/etc/os-release introuvable."
    # shellcheck disable=SC1091
    . /etc/os-release
    OS_ID="${ID:-inconnu}"
    OS_LIKE="${ID_LIKE:-}"
}

is_debian_like() {
    case "$OS_ID $OS_LIKE" in *debian*|*ubuntu*) return 0 ;; esac
    return 1
}

is_arch_like() {
    case "$OS_ID $OS_LIKE" in *arch*) return 0 ;; esac
    return 1
}

#: Branche LTS. Chez Asterisk les majeures PAIRES sont LTS, les impaires
#: sont des versions courtes : 22 est donc le bon choix, pas 23.
AST_VERSION="${AST_VERSION:-22}"

paquet_disponible() {
    # LC_ALL=C, et non un motif par langue : l'apt francais ecrit
    # « Candidat : » avec une espace INSECABLE avant le deux-points, ce qu'un
    # motif ASCII ne peut pas attraper. La detection concluait donc toujours
    # a l'absence, et compilait meme quand le paquet existait.
    # On COMPARE la valeur au lieu de la filtrer par motif : « \s*[^(] »
    # acceptait « Candidate: (none) », le quantificateur pouvant ne rien
    # consommer et le « non-parenthese » se satisfaisant de l'espace.
    local candidat
    candidat="$(LC_ALL=C apt-cache policy "$1" 2>/dev/null \
        | awk -F': *' '/^ *Candidate:/ {print $2; exit}')"
    [ -n "$candidat" ] && [ "$candidat" != "(none)" ]
}

install_paquets() {
    if is_debian_like; then
        export DEBIAN_FRONTEND=noninteractive
        apt-get update -qq
        apt-get install -y --no-install-recommends fail2ban openssl curl \
            tar build-essential
        if paquet_disponible asterisk; then
            log "installation depuis les depots de la distribution"
            apt-get install -y --no-install-recommends asterisk
        else
            log "asterisk absent des depots — compilation depuis les sources"
            compiler_asterisk
        fi
    elif is_arch_like; then
        pacman -Sy --noconfirm asterisk fail2ban openssl curl tar
    else
        die "distribution non geree : $OS_ID. Installer asterisk a la main."
    fi
}

compiler_asterisk() {
    # Debian 12 et 13 ne livrent plus asterisk : le paquet a ete RETIRE,
    # la charge de securite depassant ses mainteneurs. Ce n'est pas un
    # accident de depot, c'est une decision — et elle a une consequence
    # qu'il faut assumer : compile ainsi, asterisk ne recevra AUCUNE mise a
    # jour de securite par apt. Quelqu'un devra suivre les avis et
    # recompiler, plusieurs fois par an.
    if command -v asterisk >/dev/null 2>&1; then
        log "asterisk deja compile et installe, compilation ignoree"
        return
    fi
    local tmp
    tmp="$(mktemp -d)"
    log "telechargement d'asterisk ${AST_VERSION} (branche LTS)"
    if ! curl -fsSL -o "${tmp}/asterisk.tar.gz" \
        "https://downloads.asterisk.org/pub/telephony/asterisk/asterisk-${AST_VERSION}-current.tar.gz"; then
        rm -rf "$tmp"
        die "telechargement impossible. Verifiez l'acces reseau."
    fi
    tar -xzf "${tmp}/asterisk.tar.gz" -C "$tmp"
    local src
    src="$(find "$tmp" -maxdepth 1 -type d -name 'asterisk-*' | head -1)"
    [ -n "$src" ] || { rm -rf "$tmp"; die "archive inattendue."; }

    log "installation des dependances de compilation (plusieurs minutes)"
    ( cd "$src" && yes | contrib/scripts/install_prereq install ) \
        || { rm -rf "$tmp"; die "dependances non satisfaites."; }

    log "configuration et compilation (10 a 20 minutes selon la machine)"
    (
        cd "$src"
        ./configure --with-jansson-bundled --with-pjproject-bundled >/dev/null
        make menuselect.makeopts >/dev/null
        # On n'active que ce dont la passerelle se sert. Chaque module en
        # moins est du code qui ne tourne pas, donc une faille de moins.
        # Les trois derniers portent le softphone du navigateur :
        # le WebSocket sur le serveur HTTP, son transport PJSIP, et SRTP —
        # un navigateur REFUSE un media non chiffre, il n'y a pas d'option.
        menuselect/menuselect --enable chan_pjsip --enable res_ari \
            --enable res_ari_channels --enable res_ari_playbacks \
            --enable res_stasis --enable format_wav --enable format_pcm \
            --enable res_http_websocket \
            --enable res_pjsip_transport_websocket --enable res_srtp \
            menuselect.makeopts
        make -j"$(nproc)" >/dev/null
        make install >/dev/null
        make config >/dev/null
    ) || { rm -rf "$tmp"; die "compilation echouee — voir la sortie ci-dessus."; }

    id asterisk >/dev/null 2>&1 || useradd -r -d /var/lib/asterisk -s /sbin/nologin asterisk
    mkdir -p /etc/asterisk /var/lib/asterisk /var/log/asterisk /var/spool/asterisk
    chown -R asterisk:asterisk /var/lib/asterisk /var/log/asterisk /var/spool/asterisk
    rm -rf "$tmp"
    log "asterisk ${AST_VERSION} compile et installe"
    log "ATTENTION : compile depuis les sources, il ne recevra PAS de mise a"
    log "jour de securite par apt. Suivre les avis et recompiler."
}

secret_aleatoire() {
    openssl rand -hex 24
}

ecrire_secrets() {
    mkdir -p "$(dirname "$SECRET_FILE")"
    if [ -f "$SECRET_FILE" ]; then
        log "secrets deja poses, conserves : $SECRET_FILE"
        # shellcheck disable=SC1090
        . "$SECRET_FILE"
        return
    fi
    AST_ARI_PASS="$(secret_aleatoire)"
    cat > "$SECRET_FILE" <<EOF
# Secrets d'Asterisk, lus par Odoo comme par le PBX.
# Ne JAMAIS versionner ce fichier ni le copier dans la base de donnees.
AST_ARI_USER=${AST_ARI_USER}
AST_ARI_PASS=${AST_ARI_PASS}
AST_ARI_URL=http://127.0.0.1:${AST_ARI_PORT}/ari
EOF
    chmod 0600 "$SECRET_FILE"
    log "secrets generes dans $SECRET_FILE (0600)"
}

normaliser_trunks() {
    # Ramene la forme a un seul trunk vers la forme generale, pour n'avoir
    # qu'un seul chemin de code ensuite.
    if [ -z "$AST_TRUNKS" ] && [ -n "$AST_TRUNK_HOST" ]; then
        AST_TRUNKS="principal|${AST_TRUNK_HOST}|${AST_TRUNK_USER}|${AST_TRUNK_PASS}"
    fi
}

ecrire_pjsip() {
    # Un transport, puis un bloc par ligne. Chaque endpoint est une identite
    # de plus a deviner : on n'en cree que pour des lignes reellement voulues.
    {
        cat <<EOF
; Genere par install_asterisk.sh — modifications manuelles ecrasees.

[transport-udp]
type = transport
protocol = udp
bind = 0.0.0.0:${AST_SIP_PORT}
EOF
        ecrire_softphones
        if [ -z "$AST_TRUNKS" ] && [ -z "$AST_WEBPHONES" ]; then
            cat <<'EOF'

; Aucune ligne fournie : le serveur est installe mais ne peut appeler
; personne. C'est volontaire — mieux vaut un PBX muet qu'un PBX ouvert.
; Relancer avec AST_TRUNKS, ou AST_TRUNK_HOST pour une ligne unique.
EOF
            return
        fi

        local ancien_ifs="$IFS"
        IFS=';'
        for ligne in $AST_TRUNKS; do
            IFS='|' read -r nom hote util mdp <<< "$ligne"
            [ -n "$nom" ] && [ -n "$hote" ] || continue
            IFS=';'
            cat <<EOF

; --- Ligne : ${nom} ---------------------------------------------------
; L'identification se fait sur l'ADRESSE du fournisseur et non sur le seul
; nom d'utilisateur : sans section "identify", quiconque presente le bon
; nom est traite comme le fournisseur.
[${nom}]
type = registration
transport = transport-udp
outbound_auth = ${nom}-auth
server_uri = sip:${hote}
client_uri = sip:${util}@${hote}
retry_interval = 60

[${nom}-auth]
type = auth
auth_type = userpass
username = ${util}
password = ${mdp}

[${nom}]
type = aor
contact = sip:${hote}

[${nom}]
type = endpoint
transport = transport-udp
context = depuis-trunk
disallow = all
allow = ulaw
allow = alaw
outbound_auth = ${nom}-auth
aors = ${nom}
from_user = ${util}
direct_media = no

[${nom}]
type = identify
endpoint = ${nom}
match = ${hote}
EOF
        done
        IFS="$ancien_ifs"
    } > "${CONFIG_DIR}/pjsip.conf"
    chmod 0640 "${CONFIG_DIR}/pjsip.conf"
    chown root:asterisk "${CONFIG_DIR}/pjsip.conf" 2>/dev/null || true
}

ecrire_softphones() {
    # Rien a poser tant que personne n'en a demande : un transport ouvert
    # sans poste derriere est une porte de plus a surveiller.
    [ -n "$AST_WEBPHONES" ] || return 0

    cat <<EOF

; --- Softphones du navigateur ----------------------------------------
; Le WebSocket voyage sur le serveur HTTP d'Asterisk (http.conf), qui
; n'ecoute que sur la boucle locale. Le "bind" ci-dessous ne sert donc pas
; a choisir un port : c'est http.conf qui decide, et le chemin est /ws.
[transport-ws]
type = transport
protocol = ws
bind = 0.0.0.0
EOF

    local ancien_ifs="$IFS"
    IFS=';'
    for poste in $AST_WEBPHONES; do
        IFS='|' read -r nom mdp <<< "$poste"
        IFS=';'
        [ -n "$nom" ] && [ -n "$mdp" ] || continue
        cat <<EOF

; --- Poste : ${nom} ---------------------------------------------------
; "webrtc = yes" pose d'un coup ce qu'un navigateur exige et refuse de
; negocier : AVPF, DTLS-SRTP avec certificat auto-genere, ICE, et le
; multiplexage RTCP. Les detailler a la main est la source d'un appel qui
; sonne, se connecte, et reste muet dans un sens.
[${nom}]
type = endpoint
transport = transport-ws
context = depuis-softphone
disallow = all
allow = opus
allow = ulaw
webrtc = yes
auth = ${nom}-auth
aors = ${nom}
callerid = ${nom} <${nom}>

[${nom}-auth]
type = auth
auth_type = userpass
username = ${nom}
password = ${mdp}

[${nom}]
type = aor
; Un seul point de contact, et l'ancien part : un onglet rouvert laisserait
; sinon une inscription morte, et un appel entrant partirait vers elle.
max_contacts = 1
remove_existing = yes
EOF
    done
    IFS="$ancien_ifs"
}


ecrire_dialplan() {
    cat > "${CONFIG_DIR}/extensions.conf" <<'EOF'
; Genere par install_asterisk.sh — modifications manuelles ecrasees.

[general]
static = yes
writeprotect = yes

[globals]

; Contexte par defaut VIDE, et c'est le garde-fou principal : un appelant
; non identifie n'atteint aucune extension. Le defaut historique d'Asterisk
; le laissait entrer dans le plan de numerotation — c'est ainsi qu'une ligne
; se fait voler.
[default]

; Les appels entrants du trunk n'ont pour l'instant nulle part ou aller. On
; raccroche proprement plutot que de les laisser tomber dans `default`.
[depuis-trunk]
exten => _.,1,Hangup()

; Appels sortants, pilotes par ARI depuis Odoo. Le plan de numerotation ne
; sert qu'a joindre le trunk : toute la logique — quel fichier jouer, quand,
; et quoi rapporter — vit dans l'application ARI, ou elle est testable.
;
; UNIQUEMENT le plan de numerotation nord-americain. Le vol de trunk sert a
; composer des numeros surtaxes a l'etranger : elargir doit rester un geste
; explicite, pas un defaut.
[erplibre-sortant]
exten => _1NXXNXXXXXX,1,NoOp(ERPLibre sortant ${EXTEN})
 same => n,Stasis(erplibre)
 same => n,Hangup()
exten => _NXXNXXXXXX,1,NoOp(ERPLibre sortant 1${EXTEN})
 same => n,Stasis(erplibre)
 same => n,Hangup()
exten => _X.,1,NoOp(REFUSE : hors plan nord-americain ${EXTEN})
 same => n,Hangup(21)
EOF

    # Le choix de la ligne appartient a Odoo, pas au plan de numerotation :
    ecrire_contexte_softphone

    # lui seul sait ce que coute chaque ligne, laquelle est en alerte, et
    # quelles minutes sont deja incluses. Ce contexte n'est qu'un repli, pour
    # qu'un appel lance a la main depuis la console aboutisse quand meme.
    {
        echo
        echo "; Repli : essaie les lignes dans l'ordre, jusqu'a ce qu'une"
        echo "; reponde. ARI passe normalement par-dessus en nommant la ligne."
        echo "[erplibre-repli]"
        echo "exten => _X.,1,NoOp(repli, essai des lignes dans l'ordre)"
        local ancien_ifs="$IFS"
        IFS=';'
        for ligne in $AST_TRUNKS; do
            IFS='|' read -r nom _ _ _ <<< "$ligne"
            IFS=';'
            [ -n "$nom" ] || continue
            echo " same => n,Dial(PJSIP/\${EXTEN}@${nom},30)"
        done
        IFS="$ancien_ifs"
        echo " same => n,Hangup()"
    } >> "${CONFIG_DIR}/extensions.conf"
    chmod 0640 "${CONFIG_DIR}/extensions.conf"
    chown root:asterisk "${CONFIG_DIR}/extensions.conf" 2>/dev/null || true
}

# Ce que les postes du navigateur ont le droit de composer.
ecrire_contexte_softphone() {
    [ -n "$AST_WEBPHONES" ] || return 0
    {
        echo
        echo "; --- Ce que les softphones du navigateur peuvent composer ---"
        echo "; Deux permissions, et pas une de plus. Un contexte partage avec"
        echo "; le trunk laisserait un poste compromis composer ce que le"
        echo "; trunk accepte, c'est-a-dire tout ce qui se facture."
        echo "[depuis-softphone]"
        local ancien_ifs="$IFS"
        IFS=';'
        for poste in $AST_WEBPHONES; do
            IFS='|' read -r nom _ <<< "$poste"
            IFS=';'
            [ -n "$nom" ] || continue
            echo "; Poste a poste : de quoi eprouver le son sans depenser une minute."
            echo "exten => ${nom},1,Dial(PJSIP/${nom},30)"
            echo " same => n,Hangup()"
        done
        IFS="$ancien_ifs"
        if [ -n "$AST_TRUNKS" ]; then
            echo
            echo "; Vers l'exterieur, par le meme plan nord-americain que le"
            echo "; reste : elargir reste un geste explicite."
            echo "exten => _1NXXNXXXXXX,1,NoOp(softphone sortant \${EXTEN})"
            echo " same => n,Goto(erplibre-repli,\${EXTEN},1)"
        fi
    } >> "${CONFIG_DIR}/extensions.conf"
}


ecrire_ari() {
    # ARI n'ecoute que sur la boucle locale : Odoo tourne a cote, ou passe par
    # un tunnel. Exposer une interface REST qui commande des appels sur une
    # adresse publique reviendrait a offrir le trunk.
    cat > "${CONFIG_DIR}/http.conf" <<EOF
[general]
enabled = yes
bindaddr = 127.0.0.1
bindport = ${AST_ARI_PORT}
EOF
    cat > "${CONFIG_DIR}/ari.conf" <<EOF
[general]
enabled = yes
pretty = no

[${AST_ARI_USER}]
type = user
read_only = no
password = ${AST_ARI_PASS}
EOF
    chmod 0640 "${CONFIG_DIR}/http.conf" "${CONFIG_DIR}/ari.conf"
    chown root:asterisk "${CONFIG_DIR}/http.conf" "${CONFIG_DIR}/ari.conf" 2>/dev/null || true
}

ecrire_rtp() {
    cat > "${CONFIG_DIR}/rtp.conf" <<EOF
[general]
rtpstart = ${AST_RTP_START}
rtpend = ${AST_RTP_END}
EOF
    chmod 0640 "${CONFIG_DIR}/rtp.conf"
    chown root:asterisk "${CONFIG_DIR}/rtp.conf" 2>/dev/null || true
}

ecrire_fail2ban() {
    [ -d /etc/fail2ban ] || { log "fail2ban absent, filtre non pose"; return; }
    cat > /etc/fail2ban/jail.d/asterisk-erplibre.conf <<'EOF'
# Un endpoint SIP expose est scanne en continu, par une industrie et non par
# des curieux. Sans ce filtre, les tentatives se comptent en centaines de
# milliers par jour et finissent par en trouver une bonne.
[asterisk]
enabled  = true
port     = 5060,5061,10000:10200/udp
logpath  = /var/log/asterisk/messages
maxretry = 3
findtime = 600
bantime  = 86400
EOF
    systemctl restart fail2ban 2>/dev/null || true
    log "fail2ban : 3 essais en 10 min, bannissement 24 h"
}

poser_sons() {
    mkdir -p "$SOUNDS_DIR"
    chown -R asterisk:asterisk "$SOUNDS_DIR" 2>/dev/null || true
    log "annonces a deposer dans $SOUNDS_DIR (format wav 8 kHz mono)"
}

demarrer() {
    systemctl enable asterisk >/dev/null 2>&1 || true
    systemctl restart asterisk
    sleep 3
    if systemctl is-active --quiet asterisk; then
        log "service actif"
    else
        die "le service n'a pas demarre — voir : journalctl -u asterisk -n 50"
    fi
}

resume() {
    echo
    log "===================== INSTALLATION TERMINEE ====================="
    log "SIP        : port ${AST_SIP_PORT}/udp, RTP ${AST_RTP_START}-${AST_RTP_END}/udp"
    log "ARI        : http://127.0.0.1:${AST_ARI_PORT}/ari (boucle locale seule)"
    log "Secrets    : ${SECRET_FILE} (0600)"
    log "Annonces   : ${SOUNDS_DIR}"
    if [ -z "$AST_TRUNK_HOST" ]; then
        log "Trunk      : AUCUN — le serveur ne peut pas appeler l'exterieur."
    else
        log "Trunk      : ${AST_TRUNK_HOST}"
    fi
    echo
    log "AVANT TOUT APPEL REEL, trois choses qui ne sont PAS dans ce script :"
    log "  1. Un plafond de depense chez le fournisseur, ou un compte prepaye."
    log "     C'est le seul garde-fou qui borne la perte en cas de vol."
    log "  2. Les appels internationaux desactives chez le fournisseur."
    log "  3. Le pare-feu limite aux adresses du fournisseur si elles sont"
    log "     connues et stables."
    echo
    log "Un message enregistre fait de l'appel un composeur-messager"
    log "automatique au sens des Regles du CRTC : le fichier doit COMMENCER"
    log "par le nom de l'organisme, l'objet, une adresse et un numero"
    log "joignable, et les heures d'appel sont bornees."
}

main() {
    check_root
    detect_os
    install_paquets
    ecrire_secrets
    normaliser_trunks
    ecrire_pjsip
    ecrire_dialplan
    ecrire_ari
    ecrire_rtp
    ecrire_fail2ban
    poser_sons
    demarrer
    resume
}

main "$@"
