#!/usr/bin/env bash
# End-to-end smoke test: start a headless gnome-shell on a private
# session bus with the extension enabled, then check that the Shell
# reports it ACTIVE, that it answers a D-Bus method, and that every
# indicator mounted.
#
# Headless mode needs no parent compositor, so the test runs from a
# desktop terminal, over ssh, or on a host with no session at all.
# Nothing touches the user's session: data, config, cache and the
# runtime directory all live in a throwaway sandbox.
#
# Exit codes:
#   0  - ACTIVE, D-Bus answered, every indicator mounted
#   1  - precondition missing (gnome-shell / dbus-launch / gdbus)
#   2  - the shell exited, the extension never reached ACTIVE, or an
#        indicator failed to mount
#
# This is opt-in. Tests that must run on every host (unit + lint)
# stay in test/unit/ and Makefile targets that don't depend on a
# gnome-shell binary.

set -euo pipefail

UUID="erplibre-home@technolibre.ca"
SRC_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TIMEOUT_SEC="${TIMEOUT_SEC:-40}"

for bin in gnome-shell dbus-launch gdbus glib-compile-schemas; do
    if ! command -v "$bin" >/dev/null 2>&1; then
        echo "skip: missing $bin on PATH" >&2
        exit 1
    fi
done

# Mutter puts its Wayland socket in XDG_RUNTIME_DIR, and a Unix socket
# path is capped at 108 bytes: the sandbox stays under a short /tmp path.
SANDBOX="$(mktemp -d /tmp/erh-e2e.XXXXXX)"
chmod 700 "$SANDBOX"
mkdir -p \
    "$SANDBOX/data/gnome-shell/extensions" \
    "$SANDBOX/config" \
    "$SANDBOX/cache" \
    "$SANDBOX/run"
chmod 700 "$SANDBOX/run"

ln -sfn "$SRC_DIR" "$SANDBOX/data/gnome-shell/extensions/$UUID"
glib-compile-schemas "$SRC_DIR/schemas/" 2>/dev/null || true

unset WAYLAND_DISPLAY DISPLAY
export XDG_RUNTIME_DIR="$SANDBOX/run"
export XDG_DATA_HOME="$SANDBOX/data"
export XDG_CONFIG_HOME="$SANDBOX/config"
export XDG_CACHE_HOME="$SANDBOX/cache"
export GSETTINGS_BACKEND=keyfile

cleanup() {
    [[ -n "${SHELL_PID:-}" ]] && kill -TERM "$SHELL_PID" 2>/dev/null
    [[ -n "${SHELL_PID:-}" ]] && wait "$SHELL_PID" 2>/dev/null
    [[ -n "${DBUS_SESSION_BUS_PID:-}" ]] && \
        kill -TERM "$DBUS_SESSION_BUS_PID" 2>/dev/null
    [[ -n "${KEEP_SANDBOX:-}" ]] && return 0
    # The document portal the shell activates mounts a FUSE file system
    # on $XDG_RUNTIME_DIR/doc, which rm cannot cross while it is mounted.
    if mountpoint -q "$SANDBOX/run/doc" 2>/dev/null; then
        # Either helper may be absent or refuse; the `|| true` keeps the
        # unmount from ending the function under `set -e`, so rm still runs.
        fusermount3 -uz "$SANDBOX/run/doc" 2>/dev/null \
            || fusermount -uz "$SANDBOX/run/doc" 2>/dev/null \
            || true
    fi
    rm -rf "$SANDBOX" 2>/dev/null \
        || echo "warning: could not remove $SANDBOX" >&2
    return 0
}

eval "$(dbus-launch --sh-syntax)"
trap cleanup EXIT

gsettings set org.gnome.shell disable-user-extensions false
gsettings set org.gnome.shell enabled-extensions "['$UUID']"

LOG="$SANDBOX/shell.log"
gnome-shell --headless --virtual-monitor 1280x800 --no-x11 \
    --wayland-display erh-e2e >"$LOG" 2>&1 &
SHELL_PID=$!

fail() {
    echo "fail: $1" >&2
    grep -E 'ERPLibreHome|JS ERROR' "$LOG" >&2 || true
    exit 2
}

info=""
for ((i = 0; i < TIMEOUT_SEC; i++)); do
    kill -0 "$SHELL_PID" 2>/dev/null || fail "gnome-shell exited early"
    info="$(gdbus call --session \
            --dest org.gnome.Shell.Extensions \
            --object-path /org/gnome/Shell/Extensions \
            --method org.gnome.Shell.Extensions.GetExtensionInfo \
            "$UUID" 2>/dev/null || true)"
    if [[ "$info" == *"'state': <1.0>"* ]] && gdbus call --session \
            --dest org.gnome.Shell \
            --object-path /org/gnome/Shell/Extensions/ERPLibreHome \
            --method org.gnome.Shell.Extensions.ERPLibreHome.DebugClaudeIndex \
            >/dev/null 2>&1; then
        break
    fi
    info=""
    sleep 1
done

[[ -n "$info" ]] || fail "extension never reached ACTIVE with D-Bus up"
# extension.js logs "mount <name> failed" for an indicator whose
# constructor threw, and keeps the others running: ACTIVE alone does
# not prove the panel is whole.
if grep -E '\[ERPLibreHome\] mount .* failed' "$LOG" >&2; then
    fail "an indicator failed to mount"
fi

echo "ok: $(gnome-shell --version): ACTIVE, D-Bus up, every indicator mounted"
