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
#
# La fusion réécrit le manifeste local de TOUS les projets : sans EL_FREEZE
# ni --freeze, elle garde donc le mode du checkout, gelé ou branches, que
# repo_state.mode_du_checkout lit dans ce manifeste. Un EL_FREEZE posé par
# l'appelant, même à 0, l'emporte.

if [ -z "${EL_FREEZE+x}" ]; then
  MODE=$(.venv.erplibre/bin/python -c \
    'from script.git import repo_state; print(repo_state.mode_du_checkout(".")[0] or "")')
  if [ "${MODE}" = "frozen" ]; then
    export EL_FREEZE=1
  fi
fi

EL_MANIFEST_MERGE_FLAGS="--with_dolibarr" \
  EL_REPO_SYNC_PROJECTS="dolibarr/dolibarr" \
  exec ./script/manifest/update_manifest_local_dev.sh "$@"
