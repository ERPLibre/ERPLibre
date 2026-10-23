#!/usr/bin/env bash

. ./env_var.sh

Red='\033[0;31m'         # Red
Green='\033[0;32m'       # Green
Yellow='\033[0;33m'      # Yellow
Color_Off='\033[0m'      # Text Reset

# --freeze : transmis au script de manifeste, qui installe chaque dépôt sur
# le SHA de son freeze-revision (voir update_manifest_local_dev.sh). Les autres
# arguments sont ignorés. EL_FREEZE=1 atteint le script de manifeste par
# l'environnement, sans passer par ici.
MANIFEST_ARGS=()
for arg in "$@"; do
    if [ "${arg}" = "--freeze" ]; then
        MANIFEST_ARGS=(--freeze)
    fi
done

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
    # « set -m » le temps du lancement : le job reçoit son propre groupe de
    # processus, de PGID égal à son PID. « kill -- -PGID » atteint alors toute
    # sa descendance (repo, git fetch, git daemon) ; un « kill PID » ne
    # toucherait que le shell du job, et ses enfants continueraient d'écrire
    # dans le checkout. Le groupe à part le soustrait aussi au Ctrl-C du
    # terminal : c'est le piège EXIT qui l'arrête. Avec le contrôle de job,
    # bash ne redirige plus l'entrée d'un job d'arrière-plan vers /dev/null,
    # d'où la redirection explicite.
    set -m
    ./script/manifest/update_manifest_local_dev.sh "${MANIFEST_ARGS[@]}" </dev/null >"${REPO_SYNC_LOG}" 2>&1 &
    PID_REPO=$!
    set +m

    # Arrête tout le groupe du repo sync et attend qu'il soit vide, SIGKILL
    # après 5 s. Le journal est conservé : il porte la cause de l'arrêt.
    stop_repo_sync() {
        # Groupe déjà vide : le sync avait fini avant l'arrêt, rien à tuer.
        if ! kill -0 -- -"${PID_REPO}" 2>/dev/null; then
            wait "${PID_REPO}" 2>/dev/null
            echo "Repo sync already finished, log kept: ${REPO_SYNC_LOG}"
            return
        fi
        kill -- -"${PID_REPO}" 2>/dev/null
        for _ in 1 2 3 4 5 6 7 8 9 10; do
            kill -0 -- -"${PID_REPO}" 2>/dev/null || break
            sleep 0.5
        done
        kill -KILL -- -"${PID_REPO}" 2>/dev/null
        wait "${PID_REPO}" 2>/dev/null
        echo -e "${Red}Repo sync interrupted${Color_Off}, log kept: ${REPO_SYNC_LOG}"
    }
    trap stop_repo_sync EXIT
    # Un signal fatal passe par exit, donc par le piège EXIT.
    trap 'exit 1' INT TERM HUP

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
    # Le piège reste armé pendant l'attente : un Ctrl-C ici arrête aussi le
    # groupe.
    echo ""
    echo "Waiting for repo sync to complete (pid ${PID_REPO})..."
    wait ${PID_REPO}
    REPO_STATUS=$?
    trap - EXIT INT TERM HUP
    if [[ ${REPO_STATUS} -ne 0 ]]; then
        echo -e "${Red}Error${Color_Off} manifest update (repo sync) failed."
        echo -e "Last 50 lines of ${REPO_SYNC_LOG}:"
        tail -n 50 "${REPO_SYNC_LOG}"
        echo -e "Full log kept: ${REPO_SYNC_LOG}"
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
    echo "RUN ./script/manifest/update_manifest_local_dev.sh ${MANIFEST_ARGS[*]}"
    echo ""
    ./script/manifest/update_manifest_local_dev.sh "${MANIFEST_ARGS[@]}"
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
