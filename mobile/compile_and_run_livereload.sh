#!/usr/bin/env bash
# Capacitor livereload mode: install the APK once with the WebView pointed at
# a Vite dev server on this machine, then iterate on src/**.{ts,scss,html}
# with HMR / hot reload — no rebuild, no reinstall on every change.
#
# Capacitor 8 dropped the --external flag from previous versions. The
# supported equivalents are --live-reload + --host + --port (+ optional
# --forwardPorts to enable 'adb reverse' so the phone can hit localhost
# over USB).
#
# This script defaults to the USB-tethering path (--forwardPorts) which
# uses `adb reverse` to route the phone's localhost:5173 back to this
# machine. No WiFi config required, works on any network, only USB cable
# + adb.
#
# Set LIVERELOAD_HOST=auto (or any LAN IP) to switch to WiFi mode — the
# phone hits the dev machine over the LAN at the chosen IP. Phone and
# dev machine must then share the same network.
#
# Override examples:
#   LIVERELOAD_HOST=auto       ./mobile/compile_and_run_livereload.sh
#       Auto-detect LAN IP via `hostname -I`. Phone connects over WiFi.
#
#   LIVERELOAD_HOST=10.0.0.42  ./mobile/compile_and_run_livereload.sh
#       Explicit LAN IP. Useful when `hostname -I` returns the wrong
#       interface (multiple NICs, VPN, etc.).
#
#   LIVERELOAD_PORT=5174       ./mobile/compile_and_run_livereload.sh
#       Use port 5174 instead of the default 5173. Both the dev server
#       and the adb-reverse port are remapped together.
#
#   LIVERELOAD_HOST=auto LIVERELOAD_PORT=5174 \
#       ./mobile/compile_and_run_livereload.sh
#       Stack overrides as expected.
#
# Trade-offs vs compile_and_run.sh:
#   ✓ ~500 ms iteration on TS / SCSS / template changes
#   ✗ Native code changes (Java, Gradle, AndroidManifest, migrations)
#     still need a full rebuild via compile_and_run.sh
#   ✗ Asset URLs differ from prod — final QA must happen against the
#     regular build.

if [[ ! -d "./mobile/erplibre_home_mobile" ]]; then
  echo "Please, run installation ./mobile/install_mobile_dev.sh before run this script ./mobile/compile_and_run_livereload.sh"
  exit 1
fi

cd mobile/erplibre_home_mobile

npm install

PORT="${LIVERELOAD_PORT:-5173}"
HOST="${LIVERELOAD_HOST:-localhost}"

if [[ "$HOST" == "auto" ]]; then
  # First non-loopback IPv4 on this machine.
  HOST="$(hostname -I 2>/dev/null | awk '{print $1}')"
  if [[ -z "$HOST" ]]; then
    echo "[livereload] could not detect LAN IP via 'hostname -I' — falling back to localhost"
    HOST="localhost"
  fi
fi

if [[ "$HOST" == "localhost" || "$HOST" == "127.0.0.1" ]]; then
  echo "[livereload] USB tethering mode: phone reaches dev server via 'adb reverse'."
  exec npx cap run android \
    --live-reload \
    --host="$HOST" \
    --port="$PORT" \
    --forwardPorts="${PORT}:${PORT}"
else
  echo "[livereload] WiFi mode: phone reaches dev server at http://${HOST}:${PORT}"
  echo "             Make sure phone and this machine share the same network."
  exec npx cap run android \
    --live-reload \
    --host="$HOST" \
    --port="$PORT"
fi
