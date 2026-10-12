#!/usr/bin/env bash
# End-to-end smoke test that launches a nested gnome-shell with the
# extension enabled and verifies it answers a D-Bus method, proving
# the extension loaded and registered its interface.
#
# Requires a running Wayland session (Mutter or compatible) on the
# host — nested gnome-shell needs a parent wayland compositor and
# cannot run on a headless CI without an Xvfb/wayland surrogate.
#
# Exit codes:
#   0  - extension answered DebugClaudeIndex within the timeout
#   1  - precondition missing (gnome-shell / dbus-launch / gdbus)
#   2  - nested shell never exposed the extension's D-Bus method
#
# This is opt-in. Tests that must run on every host (unit + lint)
# stay in test/unit/ and Makefile targets that don't depend on a
# graphical session.

set -euo pipefail

UUID="streamdeck-tiler@technolibre.ca"
SRC_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TIMEOUT_SEC="${TIMEOUT_SEC:-30}"

for bin in gnome-shell dbus-launch gdbus glib-compile-schemas; do
    if ! command -v "$bin" >/dev/null 2>&1; then
        echo "skip: missing $bin on PATH" >&2
        exit 1
    fi
done

if [[ -z "${WAYLAND_DISPLAY:-}" ]]; then
    echo "skip: WAYLAND_DISPLAY not set — nested shell needs a Wayland host" >&2
    exit 1
fi

SANDBOX="${XDG_RUNTIME_DIR:-/tmp}/streamdeck-tiler-e2e"
rm -rf "$SANDBOX"
mkdir -p \
    "$SANDBOX/data/gnome-shell/extensions" \
    "$SANDBOX/config" \
    "$SANDBOX/cache"

DEST="$SANDBOX/data/gnome-shell/extensions/$UUID"
ln -sfn "$SRC_DIR" "$DEST"
glib-compile-schemas "$SRC_DIR/schemas/" 2>/dev/null || true

export MUTTER_DEBUG_DUMMY_MONITOR_SPECS="${MUTTER_DEBUG_DUMMY_MONITOR_SPECS:-1280x800}"
export XDG_DATA_HOME="$SANDBOX/data"
export XDG_CONFIG_HOME="$SANDBOX/config"
export XDG_CACHE_HOME="$SANDBOX/cache"
export GSETTINGS_SCHEMA_DIR="$SRC_DIR/schemas"

# Start an isolated session bus so gdbus and the nested shell agree.
eval "$(dbus-launch --sh-syntax)"
trap '
    [[ -n "${SHELL_PID:-}" ]] && kill -TERM "$SHELL_PID" 2>/dev/null || true
    [[ -n "${DBUS_SESSION_BUS_PID:-}" ]] && \
        kill -TERM "$DBUS_SESSION_BUS_PID" 2>/dev/null || true
' EXIT

gsettings set org.gnome.shell disable-user-extensions false || true
gsettings set org.gnome.shell enabled-extensions "['$UUID']" || true

gnome-shell --nested --wayland >"$SANDBOX/shell.log" 2>&1 &
SHELL_PID=$!

ok=false
for ((i = 0; i < TIMEOUT_SEC; i++)); do
    if ! kill -0 "$SHELL_PID" 2>/dev/null; then
        echo "fail: nested gnome-shell exited early — see $SANDBOX/shell.log" >&2
        exit 2
    fi
    if gdbus call --session \
            --dest org.gnome.Shell \
            --object-path /org/gnome/Shell/Extensions/StreamDeckTiler \
            --method org.gnome.Shell.Extensions.StreamDeckTiler.DebugClaudeIndex \
            >/dev/null 2>&1; then
        ok=true
        break
    fi
    sleep 1
done

if ! $ok; then
    echo "fail: DebugClaudeIndex never answered — see $SANDBOX/shell.log" >&2
    exit 2
fi

echo "ok: extension exposed D-Bus interface in nested shell"
