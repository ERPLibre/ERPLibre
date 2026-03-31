#!/usr/bin/env bash

. ./env_var.sh

Red='\033[0;31m'         # Red
Green='\033[0;32m'       # Green
Yellow='\033[0;33m'      # Yellow
Color_Off='\033[0m'      # Text Reset

# EL_PARALLEL_INSTALL=1 (default): run repo sync in parallel with poetry install
# EL_PARALLEL_INSTALL=0: legacy sequential behavior (set to debug or force order)
EL_PARALLEL_INSTALL=${EL_PARALLEL_INSTALL:-1}

if [[ ${EL_PARALLEL_INSTALL} -eq 1 ]]; then

    # ── Phase 1 : common prereqs (~1-3 min) ──────────────────────────────────
    # Create venvs, pip-erplibre, install git-repo.  Must finish before both
    # repo sync (.venv.erplibre/bin/repo) and poetry (.venv.odooXX) can start.
    echo ""
    echo "RUN ./script/install/install_locally.sh [phase: setup]"
    echo ""
    EL_PHASE=setup ./script/install/install_locally.sh
    retVal=$?
    if [[ $retVal -ne 0 ]]; then
        echo -e "${Red}Error${Color_Off} ./script/install/install_locally.sh [setup]"
        exit 1
    fi

    # ── Phase 2 : parallel — repo sync (bg) + poetry (fg) ───────────────────
    REPO_SYNC_LOG="/tmp/el_repo_sync_$$.log"
    echo ""
    echo -e "${Yellow}Starting repo sync in background → ${REPO_SYNC_LOG}${Color_Off}"
    echo -e "${Yellow}  Follow live: tail -f ${REPO_SYNC_LOG}${Color_Off}"
    echo ""
    ./script/manifest/update_manifest_local_dev.sh >"${REPO_SYNC_LOG}" 2>&1 &
    PID_REPO=$!
    # Safety: kill background job if this script exits unexpectedly
    trap "kill ${PID_REPO} 2>/dev/null; wait ${PID_REPO} 2>/dev/null; rm -f ${REPO_SYNC_LOG}" EXIT

    echo ""
    echo "RUN ./script/install/install_locally.sh [phase: poetry]"
    echo ""
    EL_PHASE=poetry ./script/install/install_locally.sh
    retVal=$?
    if [[ $retVal -ne 0 ]]; then
        echo -e "${Red}Error${Color_Off} ./script/install/install_locally.sh [poetry]"
        exit 1
    fi

    # ── Wait for repo sync ────────────────────────────────────────────────────
    trap - EXIT
    echo ""
    echo "Waiting for repo sync to complete (pid ${PID_REPO})..."
    wait ${PID_REPO}
    REPO_STATUS=$?
    if [[ ${REPO_STATUS} -ne 0 ]]; then
        echo -e "${Red}Error${Color_Off} manifest update (repo sync) failed."
        echo -e "Last 50 lines of ${REPO_SYNC_LOG}:"
        tail -n 50 "${REPO_SYNC_LOG}"
        rm -f "${REPO_SYNC_LOG}"
        exit 1
    fi
    echo -e "${Green}Repo sync completed successfully.${Color_Off}"
    rm -f "${REPO_SYNC_LOG}"

else

    # ── Sequential mode (legacy) ──────────────────────────────────────────────
    echo ""
    echo "RUN ./script/install/install_locally.sh"
    echo ""
    ./script/install/install_locally.sh
    retVal=$?
    if [[ $retVal -ne 0 ]]; then
        echo -e "${Red}Error${Color_Off} ./script/install/install_locally.sh"
        exit 1
    fi

    # Update git-repo
    echo ""
    echo "RUN ./script/manifest/update_manifest_local_dev.sh"
    echo ""
    ./script/manifest/update_manifest_local_dev.sh
    retVal=$?
    if [[ $retVal -ne 0 ]]; then
        echo -e "${Red}Error${Color_Off} manifest update, check git-repo."
        exit 1
    fi

fi

npm install

## Install maintainer-tools
#cd script/OCA_maintainer-tools || exit
## virtualenv is not installed by default
##virtualenv env
#../../.venv.erplibre/bin/python -m venv env
#. env/bin/activate
#pip install setuptools-rust
## Delete all tag before installing, or break installation, will generate a new one after
#git tag | xargs git tag -d
#python setup.py install
#git tag ERPLibre/v1.4.0
##${VENV_PATH}/bin/pip install ./script/OCA_maintainer-tools/
#cd -
