#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Point d'entrée du service erplibre-home-streamdeck.service : lance, sous
# .venv.streamdeck, le programme du deck que nomme DECK_PROGRAM dans
# ~/.config/erplibre-home/streamdeck.conf (tiler par défaut).
#
#   ./script/install/erplibre_home_deck.sh            lance le programme
#   ./script/install/erplibre_home_deck.sh --check    ExecCondition du service
#
# --check rend 0 quand un programme est choisi (pas « none »), que le venv
# existe et qu'un deck est branché ; 1 sinon, avec la raison sur une ligne
# de la sortie d'erreur. systemd saute alors le démarrage au lieu de boucler
# sur un programme qui sort aussitôt sans deck.
#
# Sans option, le script REMPLACE son processus par le programme (exec) :
# le verrou du deck appartient à la description de fichier que le programme
# ouvre lui-même, et un parent qui le tiendrait aussi le lui refuserait.
#
# Une valeur inconnue de DECK_PROGRAM sort en 1 avec une ligne. Le script se
# place à la racine du dépôt qui le contient.
set -euo pipefail

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${RACINE}"
# shellcheck source=script/install/erplibre_home_settings.sh
. "${RACINE}/script/install/erplibre_home_settings.sh"

VENV_PYTHON="${RACINE}/.venv.streamdeck/bin/python"

fail() {
    echo "[ERPLibre Home] $*" >&2
    exit 1
}

PROGRAM="$(deck_setting DECK_PROGRAM tiler)"
SCRIPT="$(deck_program_path "${PROGRAM}")" \
    || fail "unknown DECK_PROGRAM=${PROGRAM} in $(deck_settings_file);" \
        "expected tiler, controller or none"

case "${1:-}" in
    --check)
        [ "${PROGRAM}" != none ] || fail "DECK_PROGRAM=none: no deck program"
        [ -x "${VENV_PYTHON}" ] \
            || fail "${VENV_PYTHON} missing: make erplibre_home_streamdeck_install"
        deck_present || fail "no Stream Deck plugged in (USB vendor 0fd9)"
        exit 0
        ;;
    "") ;;
    *) fail "unknown option: $1 (expected --check or nothing)" ;;
esac

if [ "${PROGRAM}" = none ]; then
    echo "[ERPLibre Home] DECK_PROGRAM=none: nothing to run"
    exit 0
fi
[ -x "${VENV_PYTHON}" ] \
    || fail "${VENV_PYTHON} missing: make erplibre_home_streamdeck_install"
exec "${VENV_PYTHON}" "${RACINE}/${SCRIPT}"
