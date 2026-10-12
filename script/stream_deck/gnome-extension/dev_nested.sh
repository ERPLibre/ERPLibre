#!/usr/bin/env bash
# Launch a nested gnome-shell with the streamdeck-tiler extension
# enabled in an isolated XDG sandbox. Lets the developer reload
# extension code freely (close the window to wipe everything) without
# touching the parent Wayland session.
#
# Requirements:
#   - gnome-shell 45+ (the parent session must be Mutter Wayland)
#   - dbus-run-session (libdbus, packaged on Debian / Ubuntu)
#
# The nested shell still shares the user's session bus for some
# services (notifications, etc.) — that's normal. Extension state,
# dconf, and the extensions directory are isolated under
# $XDG_RUNTIME_DIR/streamdeck-tiler-nested/.

set -euo pipefail

UUID="streamdeck-tiler@technolibre.ca"
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"

if ! command -v gnome-shell >/dev/null 2>&1; then
    echo "error: gnome-shell not on PATH" >&2
    exit 1
fi
if ! command -v dbus-run-session >/dev/null 2>&1; then
    echo "error: dbus-run-session missing — sudo apt install dbus" >&2
    exit 1
fi

SANDBOX="${XDG_RUNTIME_DIR:-/tmp}/streamdeck-tiler-nested"
mkdir -p \
    "$SANDBOX/data/gnome-shell/extensions" \
    "$SANDBOX/config" \
    "$SANDBOX/cache"

DEST="$SANDBOX/data/gnome-shell/extensions/$UUID"
rm -rf "$DEST"
ln -sfn "$SRC_DIR" "$DEST"
glib-compile-schemas "$SRC_DIR/schemas/" 2>/dev/null || true

echo "Sandbox:           $SANDBOX"
echo "Extension symlink: $DEST -> $SRC_DIR"
echo "Launching nested gnome-shell (close the window to exit)…"
echo

# Mutter wants a fake monitor spec when nesting on a session that's
# already a Wayland compositor, otherwise it picks up the host
# resolution and may misbehave on multi-monitor setups.
export MUTTER_DEBUG_DUMMY_MONITOR_SPECS="${MUTTER_DEBUG_DUMMY_MONITOR_SPECS:-1280x800}"
export XDG_DATA_HOME="$SANDBOX/data"
export XDG_CONFIG_HOME="$SANDBOX/config"
export XDG_CACHE_HOME="$SANDBOX/cache"
export GSETTINGS_SCHEMA_DIR="$SRC_DIR/schemas"

dbus-run-session -- bash -c '
    gsettings set org.gnome.shell disable-user-extensions false || true
    gsettings set org.gnome.shell enabled-extensions "['"'"'streamdeck-tiler@technolibre.ca'"'"']" || true
    exec gnome-shell --nested --wayland
'
