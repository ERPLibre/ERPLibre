# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Bibliothèque sourcée par l'installateur, le point d'entrée du service et
# l'outil de passation : les noms et les chemins du service Stream Deck, et
# la lecture de ses réglages. Elle ne lance rien et ne pose que des
# fonctions et les constantes DECK_UNIT_NAME, DECK_REPO_DIR,
# DECK_CONTRACT_FILE, DECK_GAMES_DIR et ERPLIBRE_HOME_EXT_DIR.
#
# Les réglages sont des lignes « CLÉ=valeur » ; une ligne qui ne commence pas
# par « CLÉ= » est ignorée, si bien qu'un commentaire « # … » est permis.
# Rien n'est sourcé : un fichier de réglages n'exécute jamais de code.

DECK_UNIT_NAME="erplibre-home-streamdeck.service"

# Le programme du deck, relatif à la racine du dépôt : un dépôt à part, que
# Google Repo amène là ; le niveau Stream Deck de l'installateur ajoute son
# projet au manifeste local et le synchronise. Il porte
# le paquet erplibre_streamdeck, le contrôleur, le verrou du deck, le
# traducteur et requirements.txt, celui de .venv.streamdeck.
DECK_REPO_DIR="script/stream_deck/deck"

# Les jeux, relatifs à la racine du dépôt : un dépôt à part, que Google Repo
# amène là ; le niveau Stream Deck de l'installateur ajoute son projet au
# manifeste local et le synchronise. Le programme du deck, le contrôleur et
# le service n'en dépendent pas.
DECK_GAMES_DIR="script/stream_deck/games"

# L'extension GNOME, relative à la racine du dépôt : un dépôt à part, que
# Google Repo amène là ; la base de l'installateur ajoute son projet au
# manifeste local et le synchronise.
ERPLIBRE_HOME_EXT_DIR="script/gnome-extension/erplibre_home"

# Le répertoire de configuration de l'utilisateur : $XDG_CONFIG_HOME, ou
# ~/.config quand il est vide ou absent, comme systemd --user le lit.
deck_config_home() {
    echo "${XDG_CONFIG_HOME:-${HOME}/.config}"
}

deck_settings_file() {
    echo "$(deck_config_home)/erplibre-home/streamdeck.conf"
}

deck_unit_file() {
    echo "$(deck_config_home)/systemd/user/${DECK_UNIT_NAME}"
}

# deck_setting CLÉ DÉFAUT rend la valeur de la dernière ligne « CLÉ=… » du
# fichier de réglages, ou DÉFAUT quand le fichier ou la clé manque. Une
# valeur vide est rendue vide : c'est à l'appelant de la refuser.
# Le fichier se lit octet par octet (LC_ALL=C local) : sous une locale
# UTF-8, le « read » de bash joint à un octet invalide le saut de ligne qui
# le suit, et la clé de la ligne suivante disparaît dans cette valeur.
deck_setting() {
    local LC_ALL=C
    local key="$1" value="$2" file line
    file="$(deck_settings_file)"
    if [ -f "${file}" ]; then
        while IFS= read -r line || [ -n "${line}" ]; do
            case "${line}" in
                "${key}="*) value="${line#*=}" ;;
            esac
        done <"${file}"
    fi
    echo "${value}"
}

# deck_program_path PROGRAMME rend le script, relatif à la racine du dépôt,
# que lance DECK_PROGRAM=PROGRAMME, dans le checkout du deck ; rien pour
# « none » ; code 1 pour une valeur inconnue.
deck_program_path() {
    case "$1" in
        tiler) echo "${DECK_REPO_DIR}/erplibre_streamdeck" ;;
        controller) echo "${DECK_REPO_DIR}/erplibre_controller.py" ;;
        none) echo "" ;;
        *) return 1 ;;
    esac
}

# deck_games_enabled sort en 0 quand GAMES vaut « on » ou manque, en 1 pour
# « off », en 2 pour toute autre valeur, « GAMES= » compris : une valeur
# inconnue coupe les jeux, comme un DECK_PROGRAM inconnu coupe le service.
deck_games_enabled() {
    case "$(deck_setting GAMES on)" in
        on) return 0 ;;
        off) return 1 ;;
        *) return 2 ;;
    esac
}

# deck_games_message écrit, sur une ligne, pourquoi un jeu ne démarre pas :
# la valeur de GAMES, le fichier qui la porte, et comment les réactiver.
# Les caractères de contrôle de la valeur sont rendus visibles : un « \r »
# brut ramènerait le curseur en début de ligne et masquerait le message.
deck_games_message() {
    local value
    value="$(deck_setting GAMES on)"
    value="${value//$'\r'/\\r}"
    value="${value//$'\t'/\\t}"
    value="${value//$'\033'/\\e}"
    echo "[ERPLibre Home] Stream Deck games are disabled" \
        "(GAMES=${value} in $(deck_settings_file));" \
        "enable them from TODO › ERPLibre Home › Games on/off, or set GAMES=on"
}

# deck_games_present [RACINE] sort en 0 quand les jeux sont installés sous
# RACINE, le répertoire courant par défaut : games_cli.py, que chaque jeu
# importe, en est le témoin, un répertoire vide ne suffit pas.
deck_games_present() {
    [ -f "${1:-.}/${DECK_GAMES_DIR}/games_cli.py" ]
}

# deck_games_absent_message écrit, sur une ligne, que les jeux manquent et
# la commande qui les installe.
deck_games_absent_message() {
    echo "[ERPLibre Home] Stream Deck games are not installed" \
        "(no games_cli.py in ${DECK_GAMES_DIR}/);" \
        "install them with make erplibre_home_streamdeck_install"
}

# deck_repo_present [RACINE] sort en 0 quand le programme du deck est posé
# sous RACINE, le répertoire courant par défaut : erplibre_streamdeck/
# __main__.py en est le témoin. Un répertoire qui ne garde que des caches
# Python ne suffit pas.
deck_repo_present() {
    [ -f "${1:-.}/${DECK_REPO_DIR}/erplibre_streamdeck/__main__.py" ]
}

# deck_repo_absent_message écrit, sur une ligne, que le programme du deck
# manque et la commande qui le pose (repo sync).
deck_repo_absent_message() {
    echo "[ERPLibre Home] the deck program is not installed" \
        "(no erplibre_streamdeck/__main__.py in ${DECK_REPO_DIR}/);" \
        "install it with make erplibre_home_streamdeck_install"
}

# Le contrat qu'ERPLibre attend du programme du deck, relatif à la racine
# du dépôt : une ligne « MAJEURE.MINEURE ».
DECK_CONTRACT_FILE="script/stream_deck/deck_contract"

# deck_contract_expected [RACINE] écrit la version de DECK_CONTRACT_FILE
# sous RACINE, blancs retirés ; sort en 1, sans rien écrire, quand le
# fichier manque ou ne porte pas « MAJEURE.MINEURE ».
deck_contract_expected() {
    local version
    version="$(tr -d '[:space:]' <"${1:-.}/${DECK_CONTRACT_FILE}" \
        2>/dev/null)" || return 1
    [[ "${version}" =~ ^[0-9]+\.[0-9]+$ ]] || return 1
    echo "${version}"
}

# deck_contract_cloned [RACINE] écrit la version du CONTRACT.md du clone,
# celle de sa ligne « **Contract version: X.Y** » ; sort en 1, sans rien
# écrire, quand le fichier manque ou ne porte pas exactement une telle
# ligne.
deck_contract_cloned() {
    local versions
    versions="$(sed -n \
        's/^\*\*Contract version: \([0-9][0-9]*\.[0-9][0-9]*\)\*\*$/\1/p' \
        "${1:-.}/${DECK_REPO_DIR}/CONTRACT.md" 2>/dev/null)" || return 1
    [[ "${versions}" =~ ^[0-9]+\.[0-9]+$ ]] || return 1
    echo "${versions}"
}

# deck_contract_ok [RACINE] sort en 0 quand le clone du programme du deck
# sous RACINE remplit le contrat attendu : même MAJEURE que
# DECK_CONTRACT_FILE, MINEURE au moins égale. Une MINEURE ajoute ce dont
# ERPLibre se sert, comme la commande « game » de deck_lock.py en 1.1 : un
# clone plus ancien ne l'a pas. Une version absente ou mal formée, d'un
# côté ou de l'autre, sort en 1.
deck_contract_ok() {
    local attendue clone
    attendue="$(deck_contract_expected "${1:-.}")" || return 1
    clone="$(deck_contract_cloned "${1:-.}")" || return 1
    [ "$((10#${clone%%.*}))" -eq "$((10#${attendue%%.*}))" ] \
        && [ "$((10#${clone#*.}))" -ge "$((10#${attendue#*.}))" ]
}

# deck_contract_message [RACINE] écrit, sur une ligne, la version du clone,
# celle qu'ERPLibre attend, et comment mettre le clone à jour.
deck_contract_message() {
    local attendue clone
    attendue="$(deck_contract_expected "${1:-.}")" || attendue="?"
    clone="$(deck_contract_cloned "${1:-.}")" || clone="?"
    echo "[ERPLibre Home] the deck program in ${DECK_REPO_DIR}/ has" \
        "contract ${clone}, ERPLibre needs ${attendue} or a later" \
        "${attendue%%.*}.x; update it with make" \
        "erplibre_home_streamdeck_install"
}

# erplibre_home_extension_present [RACINE] sort en 0 quand l'extension est
# posée sous RACINE, le répertoire courant par défaut : metadata.json en
# est le témoin. Les fichiers ignorés qu'une mise à jour d'ERPLibre laisse
# derrière elle (locale/, schémas compilés, caches) ne suffisent pas.
erplibre_home_extension_present() {
    [ -f "${1:-.}/${ERPLIBRE_HOME_EXT_DIR}/metadata.json" ]
}

# erplibre_home_extension_absent_message écrit, sur une ligne, que
# l'extension manque et la commande qui la pose (repo sync). Cette cible ne
# demande pas GNOME Shell : un serveur de tests sans session GNOME s'en sert
# aussi.
erplibre_home_extension_absent_message() {
    echo "[ERPLibre Home] the GNOME extension is not installed" \
        "(no metadata.json in ${ERPLIBRE_HOME_EXT_DIR}/);" \
        "install it with make erplibre_home_install_extension"
}

# deck_plugins_off écrit, un par ligne, les identifiants de plugins que
# DECK_PLUGINS_OFF coupe : la valeur se coupe aux virgules, chaque morceau
# perd tous ses blancs, un morceau vide est ignoré. Sort toujours en 0, clé
# absente comprise.
deck_plugins_off() {
    local value part
    local -a parts
    value="$(deck_setting DECK_PLUGINS_OFF "")"
    IFS=',' read -r -a parts <<<"${value}"
    for part in "${parts[@]}"; do
        part="${part//[[:space:]]/}"
        [ -n "${part}" ] && echo "${part}"
    done
    return 0
}

# deck_session_refresh_sec écrit la période, en secondes, à laquelle les
# pages de session du deck se rafraîchissent : DECK_SESSION_REFRESH_SEC,
# blancs de bord retirés, quand c'est un nombre décimal de 0.5 à 60 inclus ;
# 1 sinon (clé absente, valeur vide, hors bornes ou pas un nombre). Sort
# toujours en 0.
deck_session_refresh_sec() {
    local value
    value="$(deck_setting DECK_SESSION_REFRESH_SEC 1)"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    if [[ "${value}" =~ ^([0-9]+\.?[0-9]*|\.[0-9]+)$ ]] &&
        awk -v v="${value}" 'BEGIN { exit !(v >= 0.5 && v <= 60) }'; then
        echo "${value}"
    else
        echo 1
    fi
    return 0
}

# Vrai quand un périphérique USB du vendeur 0fd9 (Elgato) est branché, lu
# dans les idVendor de sysfs. ERPLIBRE_HOME_SYSFS remplace /sys, pour les
# tests.
deck_present() {
    local vendor
    for vendor in "${ERPLIBRE_HOME_SYSFS:-/sys}"/bus/usb/devices/*/idVendor; do
        [ -r "${vendor}" ] || continue
        [ "$(cat "${vendor}")" = "0fd9" ] && return 0
    done
    return 1
}
