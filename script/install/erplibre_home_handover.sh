#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Passe le Stream Deck du service à une commande (un jeu), puis le lui rend.
#
#   ./script/install/erplibre_home_handover.sh <commande> [arguments…]
#
# 1. si erplibre-home-streamdeck.service est actif, il est arrêté ;
# 2. la commande tourne au premier plan, son code est gardé ;
# 3. si le service était actif et que RESTART_AFTER_GAME vaut yes (défaut),
#    il est relancé ;
# 4. le script sort avec le code de la commande.
#
# Sans fichier d'unité (niveau de base, ou installation à la main), seule la
# commande tourne : systemctl n'est pas appelé. Un Ctrl-C ou un SIGTERM
# pendant la commande arrive aussi à elle ; le script attend sa fin puis
# rend le deck au service, au lieu de mourir avec elle et de le garder
# arrêté. RESTART_AFTER_GAME se lit APRÈS la commande : un réglage changé
# pendant la partie compte.
set -uo pipefail

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=script/install/erplibre_home_settings.sh
. "${RACINE}/script/install/erplibre_home_settings.sh"

if [ $# -eq 0 ]; then
    echo "usage: $0 <command> [arguments…]" >&2
    exit 1
fi

was_active=0
if [ -e "$(deck_unit_file)" ] \
    && systemctl --user is-active --quiet "${DECK_UNIT_NAME}"; then
    if systemctl --user stop "${DECK_UNIT_NAME}"; then
        was_active=1
    else
        echo "[ERPLibre Home] could not stop ${DECK_UNIT_NAME};" \
            "the game may find the deck taken" >&2
    fi
fi

# Une action vide (et non « '' », qui ignorerait le signal) : le signal
# interrompt la commande, puis le script reprend après elle.
trap ':' INT TERM HUP
"$@"
rc=$?

if [ "${was_active}" = 1 ] \
    && [ "$(deck_setting RESTART_AFTER_GAME yes)" = yes ]; then
    systemctl --user start "${DECK_UNIT_NAME}" \
        || echo "[ERPLibre Home] could not start ${DECK_UNIT_NAME} again" >&2
fi
exit "${rc}"
