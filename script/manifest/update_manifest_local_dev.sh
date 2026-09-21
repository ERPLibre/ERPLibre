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

# --freeze : chaque dépôt est installé sur le SHA de son freeze-revision
# plutôt que sur la tête de sa branche ; un projet sans freeze-revision suit
# sa branche. Le choix vaut pour cet appel et n'est conservé nulle part.
# EL_FREEZE=1 fait le même choix pour un appelant qui ne transmet pas
# d'argument (update_env_version.py, lancé par « make install_dev FREEZE=1 »).
# --with_extra (update_env_version.py) va lui aussi à la fusion : repo init
# refuse une option qu'il ne connaît pas.
# Ces arguments sont retirés de "$@" ; les autres vont à repo init, dans
# leur ordre.
MERGE_FREEZE=()
if [ "${EL_FREEZE:-0}" = "1" ]; then
  MERGE_FREEZE=(--freeze)
fi
MERGE_EXTRA=()
FORWARD_ARGS=()
for arg in "$@"; do
  if [ "${arg}" = "--freeze" ]; then
    MERGE_FREEZE=(--freeze)
  elif [ "${arg}" = "--with_extra" ]; then
    MERGE_EXTRA=(--with_extra)
  else
    FORWARD_ARGS+=("${arg}")
  fi
done
set -- "${FORWARD_ARGS[@]}"

# Update git-repo : local git daemon serving the repo over git://127.0.0.1:9418.
# --listen binds the loopback only. Without it the daemon binds every
# interface, and --export-all then offers every repository under the base
# path for reading to whatever reaches the port: the git protocol asks for
# no credential. It goes AFTER --export-all, because the pkill pattern
# below matches "--base-path=. --export-all" as one contiguous string.
# Kill any leftover daemon from a previous (interrupted) run first: otherwise the
# stale server keeps port 9418, the new daemon fails to bind ("Address already in
# use"), and the cleanup kill below fails on an already-dead PID -> script exit 1.
# Match on the stable arguments, not "git daemon": « git daemon » execs into
# « git-daemon » (hyphen, /usr/lib/git-core/git-daemon), so "git daemon" (space)
# never matches the actual running process.
if pkill -f "daemon --base-path=. --export-all" 2>/dev/null; then
  sleep 1  # let the kernel release port 9418 before we rebind
fi

git daemon --base-path=. --export-all --listen=127.0.0.1 --reuseaddr --informative-errors ${DAEMON_VERBOSE} &
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
.venv.erplibre/bin/python ./script/git/git_merge_repo_manifest.py --output .repo/local_manifests/erplibre_manifest.xml --with_OCA "${MERGE_FREEZE[@]}" "${MERGE_EXTRA[@]}"

. ./script/manifest/manifest_revision.sh
MANIFEST_REV=$(manifest_revision) || exit 1

.venv.erplibre/bin/repo init -u git://127.0.0.1:9418/ -b "${MANIFEST_REV}" -m ${MANIFEST_TARGET} "$@"
.venv.erplibre/bin/repo sync -c -j "$JOBS" ${REPO_VERBOSE} -m ${MANIFEST_TARGET}

# Daemon cleanup handled by the EXIT trap above (tolerant of an already-dead PID).
