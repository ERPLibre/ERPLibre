# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Bibliothèque sourcée par l'installateur, le point d'entrée du service et
# l'outil de passation : les noms et les chemins du service Stream Deck, et
# la lecture de ses réglages. Elle ne lance rien et ne pose que des
# fonctions et les constantes DECK_UNIT_NAME et DECK_GAMES_DIR.
#
# Les réglages sont des lignes « CLÉ=valeur » ; une ligne qui ne commence pas
# par « CLÉ= » est ignorée, si bien qu'un commentaire « # … » est permis.
# Rien n'est sourcé : un fichier de réglages n'exécute jamais de code.

DECK_UNIT_NAME="erplibre-home-streamdeck.service"

# Les jeux, relatifs à la racine du dépôt : un dépôt à part, que Google Repo
# ou le niveau Stream Deck de l'installateur clone là. Le programme du deck,
# le contrôleur et le service n'en dépendent pas.
DECK_GAMES_DIR="script/stream_deck/games"

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
# que lance DECK_PROGRAM=PROGRAMME ; rien pour « none » ; code 1 pour une
# valeur inconnue.
deck_program_path() {
    case "$1" in
        tiler) echo "script/stream_deck/erplibre_streamdeck" ;;
        controller) echo "script/stream_deck/erplibre_controller.py" ;;
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
        "enable them from TODO › Stream Deck › Games on/off, or set GAMES=on"
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
        "(${DECK_GAMES_DIR}/ is missing);" \
        "install them with make erplibre_home_streamdeck_install"
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
