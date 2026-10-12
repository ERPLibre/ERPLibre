#!/bin/bash
# Launch a Stream Deck game from the HTML gallery
# Usage: launch_game.sh game_name
# Example: launch_game.sh snake

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ERPLIBRE_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
GAME="$1"

if [ -z "$GAME" ]; then
    echo "Usage: $0 <game_name>"
    exit 1
fi

GAME_FILE="$SCRIPT_DIR/game_${GAME}.py"

if [ ! -f "$GAME_FILE" ]; then
    echo "Game not found: $GAME_FILE"
    exit 1
fi

cd "$ERPLIBRE_DIR"
exec python3 "$GAME_FILE"
