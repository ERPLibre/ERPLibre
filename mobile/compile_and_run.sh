#!/usr/bin/env bash
# Build + sync + cap run for the ERPLibre mobile app.
#
# Defaults: full release-quality build (every ABI for whisper.cpp, every
# manifest tar.gz, the workspace-root bundle, etc). Drop in any of these
# env vars to trim the dev iteration cycle. Stack as needed.
#
# ── 1. Skip the 138-repo manifest bundle ─────────────────────────────────
# Saves ~15 s of vite build + ~180 MB of APK assets. The Code tool's
# 'browse a manifest repo' flow fail-softs (BundleNotShippedError) until
# you rebuild without this flag.
#
#   BUNDLE_SKIP_REPOS=1 ./mobile/compile_and_run.sh
#
# ── 2. Skip the workspace-root bundle ────────────────────────────────────
# Saves ~3 s of vite build + ~28 MB of APK assets. The Code tool's
# 🏠 ERPLibre racine button fail-softs the same way.
#
#   BUNDLE_SKIP_ERPLIBRE=1 ./mobile/compile_and_run.sh
#
# ── 3. Skip the whisper.cpp native build ─────────────────────────────────
# Saves ~5 min of NDK compile the first time and ~3.5 MB of APK lib/.
# Transcription becomes a no-op at runtime; everything else works.
# MainActivity gates the WhisperPlugin registration on BuildConfig.SKIP_WHISPER.
#
#   BUNDLE_SKIP_WHISPER=1 ./mobile/compile_and_run.sh
#
# ── 4. Strip ABI variants ────────────────────────────────────────────────
# By default the APK only ships arm64-v8a (modern phones — saves ~50%
# of the native libs section). Set ALL_ABIS=1 to package every ABI
# (arm64-v8a + armeabi-v7a + x86 + x86_64) — needed when you run on an
# emulator or want to keep options open.
#
#   ALL_ABIS=1 ./mobile/compile_and_run.sh
#
# ── 5. Tune the manifest bundle parallelism ──────────────────────────────
# Defaults to nproc (logical CPUs). Override the worker pool size if
# disk I/O becomes the bottleneck on slower drives.
#
#   BUNDLE_PARALLEL=4 ./mobile/compile_and_run.sh
#
# ── Combos pratiques ─────────────────────────────────────────────────────
# Tightest dev loop (no manifest, no workspace, no whisper, arm64 only):
#
#   BUNDLE_SKIP_REPOS=1 BUNDLE_SKIP_WHISPER=1 BUNDLE_SKIP_ERPLIBRE=1 \
#       ./mobile/compile_and_run.sh
#   → APK ~25 MB, install ≈ 5 s, build ≈ 5 s
#
# Emulator dev (everything but for x86_64):
#
#   ALL_ABIS=1 ./mobile/compile_and_run.sh
#
# For TS / SCSS only iterations, prefer ./mobile/compile_and_run_livereload.sh
# instead — it installs the APK once, then HMR-reloads on every save.

if [[ ! -d "./mobile/erplibre_home_mobile" ]]; then
  echo "Please, run installation ./mobile/install_mobile_dev.sh before run this script ./mobile/compile_and_run.sh"
  exit 1
fi

cd mobile/erplibre_home_mobile

npm install
npm run build && npx cap sync
npx cap run android

cd -
