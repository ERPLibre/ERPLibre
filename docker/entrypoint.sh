#!/bin/bash

set -e
# Fix volumes of odoo.conf if not exist. Before the dev mode, which reads it.
if [ ! -f "/etc/odoo/odoo.conf" ]; then
  cp /odoo.conf /etc/odoo/odoo.conf
fi

if [[ "$ENV" == "dev" ]] && [ ! -z ${CURRENT_UID} ]; then
  export HOME=$ODOO_PREFIX
  cd $HOME

  # Sync the repositories of the mounted checkout, as on the host: the script
  # serves the checkout through git daemon, merges the manifests of the active
  # Odoo version, gives repo init a branch and stops the daemon when done.
  ./script/manifest/update_manifest_local_dev.sh

  # An "if" rather than an exit code: under "set -e", a failing test command
  # would end the script before the message.
  ODOO_VERSION_DIR="$HOME/odoo$(cat ".odoo-version" | xargs)"
  ODOO_BIN="${ODOO_VERSION_DIR}/odoo/odoo-bin"
  if [ ! -f "${ODOO_BIN}" ]; then
    echo "The file ${ODOO_BIN} doesnt exist. Verify entrypoint.sh"
    exit 1
  fi

  # odoo-bin on the PATH. The "odoo" command needs no alias: the case at the
  # end of this script takes it as its first argument.
  export PATH="${ODOO_VERSION_DIR}/odoo:${PATH}"

  # The image configuration with the addons_path of the mounted checkout,
  # written inside the container: the checkout belongs to the host, and
  # /etc/odoo is not writable by CURRENT_UID. Odoo starts on ODOO_RC.
  DEV_ODOO_RC="${TMPDIR:-/tmp}/odoo.conf"
  python3 ./docker/repo_manifest_gen_org_prefix_path.py "${ODOO_VERSION_DIR}/addons" "${ODOO_RC}" "${DEV_ODOO_RC}"
  export ODOO_RC="${DEV_ODOO_RC}"

elif [[ "$ENV" == "dev" ]] && [ -z ${CURRENT_UID} ]; then
  echo 'Please run as follows : CURRENT_UID=$(id -u):$(id -g) docker compose up'
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
  if grep -q -E "^\s*\b${param}\b\s*=" "$ODOO_RC"; then
    value=$(grep -E "^\s*\b${param}\b\s*=" "$ODOO_RC" | cut -d " " -f3 | sed 's/["\n\r]//g')
  fi
  DB_ARGS+=("--${param}")
  DB_ARGS+=("${value}")
}
check_config "db_host" "$HOST"
check_config "db_port" "$PORT"
check_config "db_user" "$USER"
check_config "db_password" "$PASSWORD"

cd /ERPLibre
source .venv.$(cat ".erplibre-version" | xargs)/bin/activate

# start_warmup ODOO_ARGS... : runs script/odoo/warmup_http.py in the
# background, as run.sh does. Odoo loads a database registry on the first
# request for it, tens of seconds on a migrated database; the probe takes that
# wait instead of the first visitor. It reads the port from ODOO_ARGS, then
# from ODOO_RC, stops at the first HTTP answer or after two minutes, and ends
# with the container at the latest. Skipped with
# ERPLIBRE_DISABLE_WARMUP_HTTP=True, or when Odoo serves no HTTP. ODOO_ARGS
# never carries DB_ARGS: the probe has no use for the database password.
start_warmup() {
  if [[ "${ERPLIBRE_DISABLE_WARMUP_HTTP}" == "True" ]] \
    || [ ! -f ./script/odoo/warmup_http.py ]; then
    return 0
  fi
  local arg
  for arg in "$@"; do
    case "${arg}" in
      --no-http | --stop-after-init) return 0 ;;
    esac
  done
  python3 ./script/odoo/warmup_http.py -c "$ODOO_RC" -- "$@" 2>/dev/null &
}

# run_odoo ODOO_ARGS... : waits for PostgreSQL, then runs Odoo in the
# foreground with the probe beside it. Odoo's exit status is the container's:
# under "set -e" a failure ends the script with Odoo's code, and a success,
# such as a --stop-after-init that went through, ends it with 0.
run_odoo() {
  cd $ODOO_PREFIX
  if [[ "${STOP_BEFORE_INIT}" == "True" ]]; then
    sleep 999999
  fi
  python3 ./docker/wait-for-psql.py "${DB_ARGS[@]}" --timeout=30
  local odoo_args=("$@")
  if [[ "${UPDATE_ALL_DB}" == "True" ]]; then
    odoo_args+=(-u all -d "${DB_NAME}")
  fi
  start_warmup "${odoo_args[@]}"
  python3 "$ODOO_EXEC_BIN" "${odoo_args[@]}" "${DB_ARGS[@]}" -c "$ODOO_RC"
}

case "$1" in
  -- | odoo)
    shift
    if [[ "$1" == "scaffold" ]]; then
      exec odoo "$@" || exec odoo-bin "$@"
    else
      run_odoo "$@"
    fi
    ;;
  -*)
    run_odoo "$@"
    ;;
  *)
    exec "$@"
    ;;
esac
