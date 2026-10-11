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

if command -v nproc >/dev/null 2>&1; then
  JOBS="$(nproc --all)"
else
  JOBS="$(sysctl -n hw.ncpu)"
fi

# Generate local manifest
.venv.erplibre/bin/python ./script/git/git_merge_repo_manifest.py --output .repo/local_manifests/erplibre_manifest.xml --with_OCA

# Révision du manifeste : un NOM DE BRANCHE, jamais un SHA nu.
#
# « repo init -b <sha> » échoue sur un espace de travail NEUF : repo doit y
# cloner .repo/manifests et ne sait pas résoudre un commit en révision de
# manifeste. Même résolution que update_manifest_local_dev.sh ; la branche
# doit ici exister sur le dépôt distant passé à -u.
MANIFEST_REV=$(git symbolic-ref --quiet --short HEAD || true)
if [ -z "${MANIFEST_REV}" ]; then
  # HEAD détaché : prendre une branche qui contient ce commit plutôt que de
  # retomber sur le SHA, qui ne marcherait pas.
  MANIFEST_REV=$(git branch --contains HEAD --format='%(refname:short)' 2>/dev/null | grep -v '[()]' | head -1)
fi
if [ -z "${MANIFEST_REV}" ]; then
  echo "Erreur : impossible de déterminer une branche pour repo init." >&2
  echo "  HEAD est détaché et aucune branche ne contient ce commit." >&2
  exit 1
fi

# Update git-repo. Sans -m, repo init prendrait default.xml, absent du dépôt.
.venv.erplibre/bin/repo init -u https://github.com/ERPLibre/ERPLibre -b "${MANIFEST_REV}" -m "${EL_MANIFEST_DEV}"
.venv.erplibre/bin/repo sync ${REPO_VERBOSE} -j "$JOBS"
