#!/usr/bin/env bash

. ./env_var.sh

# Verbosité de l'installation (git-repo). Silencieuse par défaut ;
# EL_VERBOSE=1 rétablit les logs détaillés (repo sync, git daemon).
if [ "${EL_VERBOSE:-0}" = "1" ]; then
  REPO_VERBOSE="-v"; DAEMON_VERBOSE="--verbose"
else
  REPO_VERBOSE="-q"; DAEMON_VERBOSE=""
fi
#EL_MANIFEST_PROD="./default.xml"
#EL_MANIFEST_DEV="./manifest/default.dev.xml"

# Update git-repo : local git daemon serving the repo over git://127.0.0.1:9418.
# Kill any leftover daemon from a previous (interrupted) run first: otherwise the
# stale server keeps port 9418, the new daemon fails to bind ("Address already in
# use"), and the cleanup kill below fails on an already-dead PID -> script exit 1.
# Match on the stable arguments, not "git daemon": « git daemon » execs into
# « git-daemon » (hyphen, /usr/lib/git-core/git-daemon), so "git daemon" (space)
# never matches the actual running process.
if pkill -f "daemon --base-path=. --export-all" 2>/dev/null; then
  sleep 1  # let the kernel release port 9418 before we rebind
fi

git daemon --base-path=. --export-all --reuseaddr --informative-errors ${DAEMON_VERBOSE} &
DAEMON_PID=$!
# Always stop the daemon we started, whatever happens next (success or error),
# without ever failing the script if it is already gone.
trap 'kill "${DAEMON_PID}" 2>/dev/null || true' EXIT

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
.venv.erplibre/bin/python ./script/git/git_merge_repo_manifest.py --output .repo/local_manifests/erplibre_manifest.xml --with_OCA

.venv.erplibre/bin/repo init -u git://127.0.0.1:9418/ -b $(git rev-parse --verify HEAD) -m ${MANIFEST_TARGET} "$@"
.venv.erplibre/bin/repo sync -c -j "$JOBS" ${REPO_VERBOSE} -m ${MANIFEST_TARGET}

# Daemon cleanup handled by the EXIT trap above (tolerant of an already-dead PID).
