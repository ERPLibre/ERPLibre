#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Synchronise le checkout Dolibarr épinglé (manifest/git_manifest_dolibarr.xml)
# dans dolibarr/dolibarr, et lui seul : la fusion garde tous les projets
# présents, la synchronisation ne touche que Dolibarr. Même démon git local,
# même initialisation que update_manifest_local_dev.sh, qu'il appelle.
#
#   ./script/manifest/update_manifest_local_dolibarr.sh

EL_MANIFEST_MERGE_FLAGS="--with_dolibarr" \
  EL_REPO_SYNC_PROJECTS="dolibarr/dolibarr" \
  exec ./script/manifest/update_manifest_local_dev.sh "$@"
