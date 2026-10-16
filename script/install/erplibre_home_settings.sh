# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Bibliothèque sourcée par l'installateur, le point d'entrée du service et
# l'outil de passation : les noms et les chemins du service Stream Deck, et
# la lecture de ses réglages. Elle ne lance rien et ne pose que des
# fonctions et la constante DECK_UNIT_NAME.
#
# Les réglages sont des lignes « CLÉ=valeur » ; une ligne qui ne commence pas
# par « CLÉ= » est ignorée, si bien qu'un commentaire « # … » est permis.
# Rien n'est sourcé : un fichier de réglages n'exécute jamais de code.

DECK_UNIT_NAME="erplibre-home-streamdeck.service"

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
deck_setting() {
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
        tiler) echo "script/stream_deck/game_tiler.py" ;;
        controller) echo "script/stream_deck/erplibre_controller.py" ;;
        none) echo "" ;;
        *) return 1 ;;
    esac
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
