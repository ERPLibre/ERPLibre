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
# d'argument : le Makefile l'exporte quand une cible reçoit FREEZE=1.
# L'argument est retiré de "$@" ; les autres sont gardés dans leur ordre.
MERGE_FREEZE=()
if [ "${EL_FREEZE:-0}" = "1" ]; then
  MERGE_FREEZE=(--freeze)
fi
FORWARD_ARGS=()
for arg in "$@"; do
  if [ "${arg}" = "--freeze" ]; then
    MERGE_FREEZE=(--freeze)
  else
    FORWARD_ARGS+=("${arg}")
  fi
done
set -- "${FORWARD_ARGS[@]}"

#EL_MANIFEST_PROD="./default.xml"
#EL_MANIFEST_DEV="./manifest/default.dev.xml"

if command -v nproc >/dev/null 2>&1; then
  JOBS="$(nproc --all)"
else
  JOBS="$(sysctl -n hw.ncpu)"
fi

# Generate local manifest
.venv.erplibre/bin/python ./script/git/git_merge_repo_manifest.py --output .repo/local_manifests/erplibre_manifest.xml --with_OCA "${MERGE_FREEZE[@]}"

# Update git-repo
.venv.erplibre/bin/repo init -u https://github.com/ERPLibre/ERPLibre -b $(git rev-parse --verify HEAD)
.venv.erplibre/bin/repo sync ${REPO_VERBOSE} -j "$JOBS"
