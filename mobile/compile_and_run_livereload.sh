#!/usr/bin/env bash
# Capacitor livereload mode: install the APK once with the WebView pointed at
# a Vite dev server on this machine, then iterate on src/**.{ts,scss,html}
# with HMR / hot reload — no rebuild, no reinstall on every change.
#
# Requirements:
#   - Phone and this machine on the same WiFi (or USB tethering)
#   - npm run start script defined in package.json (it is — runs vite)
#
# Capacitor with -l --external auto-spawns `npm run start`, detects the
# host's LAN IP, patches the APK with the dev-server URL, installs it,
# and launches the activity.
#
# Trade-offs vs compile_and_run.sh:
#   ✓ ~500 ms iteration on TS / SCSS / template changes
#   ✗ Native code changes (Java, Gradle, AndroidManifest, migrations)
#     still need a full rebuild via compile_and_run.sh
#   ✗ Closer to dev mode than prod — asset URLs differ; final QA must
#     happen against the regular build.

if [[ ! -d "./mobile/erplibre_home_mobile" ]]; then
  echo "Please, run installation ./mobile/install_mobile_dev.sh before run this script ./mobile/compile_and_run_livereload.sh"
  exit 1
fi

cd mobile/erplibre_home_mobile

npm install

# -l            = livereload (WebView fetches assets from dev server)
# --external    = bind dev server to LAN IP (so the phone can reach it)
npx cap run android -l --external

cd -
