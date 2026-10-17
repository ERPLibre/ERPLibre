#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Passe le Stream Deck du service à une commande (un jeu), puis le lui rend.
#
#   ./script/install/erplibre_home_handover.sh <commande> [arguments…]
#
# 0. si GAMES ne vaut pas « on » (voir erplibre_home_settings.sh), le script
#    sort en 4 sans rien arrêter ni lancer ;
# 1. si erplibre-home-streamdeck.service est actif, ou attend de redémarrer
#    (« activating » pendant RestartSec), il est arrêté ;
# 2. la commande tourne au premier plan sous le verrou du deck, tenu au nom
#    de « game » par script/stream_deck/deck_lock.py pendant toute la
#    commande ; son code est gardé ;
# 3. si le service était actif et que RESTART_AFTER_GAME vaut yes (défaut),
#    il est relancé, son compteur de démarrages (StartLimitBurst) remis à
#    zéro : des parties enchaînées ne l'épuisent pas ;
# 4. le script sort avec le code de la commande. Le code 4 peut aussi venir
#    du jeu lui-même : la ligne sur stderr est le signal sûr.
#
# Tant que le verrou est tenu, le service, et tout autre programme du deck
# lancé hors de la commande, sort en 2 en nommant « game ». Dans la
# commande, un seul programme du deck tourne à la fois : le second sort en 2
# en nommant le premier (deck.inner, voir deck_lock.py). Un deck déjà pris
# ne lance pas la commande : le script sort en 2.
#
# Sans fichier d'unité (niveau de base, ou installation à la main), seule
# la commande tourne, sous le verrou : systemctl n'est pas appelé.
#
# Un Ctrl-C au terminal frappe tout le groupe de processus, la commande
# comprise : elle meurt, et le script reprend après elle pour rendre le
# deck au service. Un signal envoyé au seul PID du script, lui, attend :
# bash ne traite son trap qu'à la fin de la commande, qui continue. Le PID
# que le verrou nomme est celui de deck_lock.py : un SIGTERM qui le vise
# atteint chaque processus du jeu, puis deck_lock.py attend leur fin. Le
# deck reste pris tant qu'un processus du jeu vit : un service relancé trop
# tôt sort en 2. RESTART_AFTER_GAME se lit APRÈS la commande : un réglage
# changé pendant la partie compte.
set -uo pipefail

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=script/install/erplibre_home_settings.sh
. "${RACINE}/script/install/erplibre_home_settings.sh"

if [ $# -eq 0 ]; then
    echo "usage: $0 <command> [arguments…]" >&2
    exit 1
fi

# GAMES=off, ou une valeur inconnue, refuse tout jeu avant d'arrêter quoi
# que ce soit : le service garde le deck, la commande ne tourne pas.
if ! deck_games_enabled; then
    deck_games_message >&2
    exit 4
fi

was_active=0
if [ -e "$(deck_unit_file)" ]; then
    # is-active ne réussit que pour « active » : l'état se lit en clair.
    case "$(systemctl --user is-active "${DECK_UNIT_NAME}")" in
        active | activating | reloading)
            if systemctl --user stop "${DECK_UNIT_NAME}"; then
                was_active=1
            else
                echo "[ERPLibre Home] could not stop ${DECK_UNIT_NAME};" \
                    "the game may find the deck taken" >&2
            fi
            ;;
    esac
fi

# Une action vide (et non « '' », qui ignorerait le signal et le léguerait
# ignoré à la commande) : le signal interrompt la commande, puis le script
# reprend après elle.
trap ':' INT TERM HUP
python3 -I "${RACINE}/script/stream_deck/deck_lock.py" game "$@"
rc=$?

if [ "${was_active}" = 1 ] \
    && [ "$(deck_setting RESTART_AFTER_GAME yes)" = yes ]; then
    systemctl --user reset-failed "${DECK_UNIT_NAME}"
    systemctl --user start "${DECK_UNIT_NAME}" \
        || echo "[ERPLibre Home] could not start ${DECK_UNIT_NAME} again" >&2
fi
exit "${rc}"
