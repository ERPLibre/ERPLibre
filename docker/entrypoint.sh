#!/bin/bash

set -e
if [[ "$ENV" == "dev" ]] &&  [ ! -z ${CURRENT_UID} ]
then
    export HOME=$ODOO_PREFIX
    cd $HOME

    # As it's only possible to fetch git repos manifest from an git url, we create one using git-daemon.
    git daemon --base-path=. --export-all --reuseaddr --informative-errors --verbose &
    GIT_PID=$!
    echo "my repo"  $(git rev-parse --abbrev-ref HEAD)
    repo init -u git://127.0.0.1:9418/ -b $(git rev-parse --abbrev-ref HEAD) -m default.dev.xml

    repo sync

    # After sync, terminate the git checkout. We don't need graceful kill as we don't do commit on the git repo during the operation.
    kill -9 $GIT_PID

    ls $HOME/odoo/odoo-bin
    # $? give the posix return value of the last command. 0 == success
    # then IS_ODOO_FILE_EXIST : 0 == YES
    IS_ODOO_FILE_EXIST=$?

    if [ "$IS_ODOO_FILE_EXIST" -ne "0" ]; then
        echo "The file $HOME/odoo/odoo-bin doesnt exist. Verify entrypoint.sh";
        exit 1;
    fi

    # Add the odoo bins code on $PATH
    echo PATH=$HOME/odoo/:$PATH

    # Configure an alias to use "odoo-bin" as "odoo".
    alias odoo=odoo-bin

    repo_manifest_gen_org_prefix_path.py $ODOO_PREFIX/addons $ODOO_RC $ODOO_PREFIX/odoo/odoo.conf && head $ODOO_PREFIX/odoo/odoo.conf
    export ODOO_RC=$ODOO_PREFIX/odoo/odoo.conf

elif [[ "$ENV" == "dev" ]] && [  -z ${CURRENT_UID} ]
then
    echo 'Please run as follows : CURRENT_UID=$(id -u):$(id -g) docker compose up'
    exit 1
fi

# Fix volumes of odoo.conf if not exist
if [ ! -f "/etc/odoo/odoo.conf" ]; then
    cp /odoo.conf /etc/odoo/odoo.conf
fi

# set the postgres database host, port, user and password according to the environment
# and pass them as arguments to the odoo process if not present in the config file
: ${HOST:=${DB_PORT_5432_TCP_ADDR:='db'}}
: ${PORT:=${DB_PORT_5432_TCP_PORT:=5432}}
: ${USER:=${DB_ENV_POSTGRES_USER:=${POSTGRES_USER:='odoo'}}}
: ${PASSWORD:=${DB_ENV_POSTGRES_PASSWORD:=${POSTGRES_PASSWORD:='odoo'}}}

DB_ARGS=()
function check_config() {
    param="$1"
    value="$2"
    if grep -q -E "^\s*\b${param}\b\s*=" "$ODOO_RC" ; then
        value=$(grep -E "^\s*\b${param}\b\s*=" "$ODOO_RC" |cut -d " " -f3|sed 's/["\n\r]//g')
    fi;
    DB_ARGS+=("--${param}")
    DB_ARGS+=("${value}")
}
check_config "db_host" "$HOST"
check_config "db_port" "$PORT"
check_config "db_user" "$USER"
check_config "db_password" "$PASSWORD"

case "$1" in
    -- | odoo)
        shift
        if [[ "$1" == "scaffold" ]] ; then
            exec odoo  "$@" || exec odoo-bin "$@"
        else
            cd $ODOO_PREFIX
            if [[ "${STOP_BEFORE_INIT}" == "True" ]] ; then
              sleep 999999
            fi
            ./docker/wait-for-psql.py ${DB_ARGS[@]} --timeout=30
            if [[ "${UPDATE_ALL_DB}" == "True" ]] ; then
              # --stop-after-init
              exec ./.venv/bin/python $ODOO_EXEC_BIN "$@" "${DB_ARGS[@]}" -c /etc/odoo/odoo.conf -u all -d "${DB_NAME}"
            else
              exec ./.venv/bin/python $ODOO_EXEC_BIN "$@" "${DB_ARGS[@]}" -c /etc/odoo/odoo.conf
            fi
        fi
        ;;
    -*)
        cd $ODOO_PREFIX
        if [[ "${STOP_BEFORE_INIT}" == "True" ]] ; then
          sleep 999999
        fi
        ./docker/wait-for-psql.py ${DB_ARGS[@]} --timeout=30
        if [[ "${UPDATE_ALL_DB}" == "True" ]] ; then
          exec ./.venv/bin/python $ODOO_EXEC_BIN "$@" "${DB_ARGS[@]}" -c /etc/odoo/odoo.conf -u all -d "${DB_NAME}"
        else
          exec ./.venv/bin/python $ODOO_EXEC_BIN "$@" "${DB_ARGS[@]}" -c /etc/odoo/odoo.conf
        fi
        ;;
    *)
        exec "$@"
esac

exit 1
