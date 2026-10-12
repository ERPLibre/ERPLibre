#!/usr/bin/env bash
# Capture the canonical screenshots referenced by README.md. Designed
# to be re-runnable: existing files are overwritten so a screenshot
# refresh is `./capture.sh` and that's it.
#
# Requires:
#   - grim + slurp (Wayland) OR gnome-screenshot (X11) on PATH.
#   - The streamdeck-tiler@technolibre.ca extension enabled in
#     gnome-shell so the indicators are mounted.
#   - A Stream Deck plugged in for the deck-* shots (the script
#     skips them gracefully if no device is detected).

set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

is_wayland() { [[ "${XDG_SESSION_TYPE:-}" == "wayland" ]]; }

shoot_window() {
    local out="$1" hint="$2"
    if is_wayland; then
        if ! command -v grim >/dev/null; then
            echo "skip $out: install grim + slurp for Wayland" >&2
            return
        fi
        echo ">>> $out: drag a rectangle around the $hint"
        grim -g "$(slurp -d)" "$out"
    else
        if ! command -v gnome-screenshot >/dev/null; then
            echo "skip $out: install gnome-screenshot for X11" >&2
            return
        fi
        echo ">>> $out: select the $hint window"
        gnome-screenshot --window --file="$out"
    fi
}

shoot_top_bar() {
    if is_wayland && command -v grim >/dev/null; then
        echo ">>> top-bar.png: capturing the top 32 px of the primary monitor"
        grim -g "0,0 1920x32" top-bar.png || \
            shoot_window top-bar.png "GNOME top bar"
    else
        shoot_window top-bar.png "GNOME top bar"
    fi
}

# Indicator dropdowns
shoot_dropdown() {
    local out="$1" hint="$2"
    echo ">>> open the $hint indicator now (you have 3 s)"
    sleep 3
    shoot_window "$out" "$hint dropdown"
}

# Prefs pages
shoot_prefs() {
    local page="$1" out="$2"
    echo ">>> switch the prefs window to '$page' now (you have 3 s)"
    sleep 3
    shoot_window "$out" "prefs $page"
}

# Stream Deck physical button matrix
shoot_deck() {
    local out="$1"
    if [[ -x "$DIR/../streamdeck_screenshot.py" ]]; then
        echo ">>> $out: reading deck framebuffer"
        python3 "$DIR/../streamdeck_screenshot.py" --output "$out" \
            || echo "skip $out: deck not detected"
    else
        echo "skip $out: streamdeck_screenshot.py not implemented yet"
    fi
}

main() {
    if ! gnome-extensions info streamdeck-tiler@technolibre.ca 2>/dev/null \
            | grep -qi 'enabled'; then
        echo "warning: streamdeck-tiler extension is not enabled" >&2
    fi

    shoot_top_bar
    shoot_dropdown pencil-dropdown.png pencil
    shoot_dropdown pencil-filtered.png "pencil (after clicking awaiting badge)"
    shoot_dropdown media-dropdown.png media

    gnome-extensions prefs streamdeck-tiler@technolibre.ca &
    sleep 2
    shoot_prefs Buttons prefs-buttons.png
    shoot_prefs Help    prefs-help.png
    shoot_prefs About   prefs-about.png

    shoot_deck deck-idle.png
    shoot_deck deck-tile-grid.png
    shoot_deck deck-claude-session.png
}

main "$@"
