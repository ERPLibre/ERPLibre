#!/bin/bash

set -e
if [[ "$ENV" == "dev" ]] &&  [ ! -z ${CURRENT_UID} ]
then
    export HOME=/ERPLibre
    cd $HOME


    git daemon --base-path=. --export-all --reuseaddr --informative-errors --verbose &
    GIT_PID=$!
    echo "my repo"  $(git rev-parse --abbrev-ref HEAD)
    repo init -u  git://127.0.0.1:9418/  -b $(git rev-parse --abbrev-ref HEAD)

    repo sync

    kill -9 $GIT_PID
elif [[ "$ENV" == "dev" ]] && [  -z ${CURRENT_UID} ]
then
    echo 'Please run as follows : CURRENT_UID=$(id -u):$(id -g) docker-compose up'
    exit 1
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
            exec odoo "$@"
        else
            wait-for-psql.py ${DB_ARGS[@]} --timeout=30
            exec odoo "$@" "${DB_ARGS[@]}"
        fi
        ;;
    -*)
        wait-for-psql.py ${DB_ARGS[@]} --timeout=30
        exec odoo "$@" "${DB_ARGS[@]}"
        ;;
    *)
        exec "$@"
esac

exit 1
