#!/usr/bin/env bash

. ./env_var.sh

# Verbosité de git-repo. Par défaut, repo sync affiche sa barre de
# progression : dépôts terminés, dépôts en cours, temps écoulé. « -q » la
# coupe, et un gros dépôt qui se télécharge en silence passe pour un blocage.
# EL_VERBOSE=1 ajoute les logs détaillés (repo sync -v, git daemon --verbose).
if [ "${EL_VERBOSE:-0}" = "1" ]; then
  REPO_VERBOSE="-v"; DAEMON_VERBOSE="--verbose"
else
  REPO_VERBOSE=""; DAEMON_VERBOSE=""
fi
#EL_MANIFEST_PROD="./default.xml"
#EL_MANIFEST_DEV="./manifest/default.dev.xml"

# Update git-repo
git daemon --base-path=. --export-all --listen=127.0.0.1 --reuseaddr --informative-errors ${DAEMON_VERBOSE} &
DAEMON_PID=$!

if [ -L "$EL_MANIFEST_DEV" ]; then
  MANIFEST_TARGET=$(readlink -f "$EL_MANIFEST_DEV")
else
  MANIFEST_TARGET="$EL_MANIFEST_DEV"
fi

if command -v nproc >/dev/null 2>&1; then
  JOBS="$(nproc --all)"
else
  JOBS="$(sysctl -n hw.ncpu)"
fi

# Generate local manifest
.venv.erplibre/bin/python ./script/git/git_merge_repo_manifest.py --output .repo/local_manifests/erplibre_manifest.xml --with_mobile

.venv.erplibre/bin/repo init -u git://127.0.0.1:9418/ -b $(git rev-parse --verify HEAD) -m ${MANIFEST_TARGET} "$@"
.venv.erplibre/bin/repo sync -c -j "$JOBS" ${REPO_VERBOSE} -m ${MANIFEST_TARGET}

kill ${DAEMON_PID}
