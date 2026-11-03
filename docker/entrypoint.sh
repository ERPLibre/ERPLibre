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

# The PostgreSQL host, port, user and password come from the environment,
# unless the configuration file already sets them.
: ${HOST:=${DB_PORT_5432_TCP_ADDR:='db'}}
: ${PORT:=${DB_PORT_5432_TCP_PORT:=5432}}
: ${USER:=${DB_ENV_POSTGRES_USER:=${POSTGRES_USER:='odoo'}}}
: ${PASSWORD:=${DB_ENV_POSTGRES_PASSWORD:=${POSTGRES_PASSWORD:='odoo'}}}

cd /ERPLibre
source .venv.$(cat ".erplibre-version" | xargs)/bin/activate

# They reach Odoo and wait-for-psql.py through a private copy of the
# configuration (0600, in the container's temporary directory), never through
# their arguments: any account on the container's host reads a process's
# arguments with ps, Odoo's for its whole life. The copy is written from the
# environment, so the password crosses no command line on the way either.
RUNTIME_ODOO_RC="${TMPDIR:-/tmp}/odoo_runtime.conf"
ERPLIBRE_DB_HOST="$HOST" ERPLIBRE_DB_PORT="$PORT" ERPLIBRE_DB_USER="$USER" \
  ERPLIBRE_DB_PASSWORD="$PASSWORD" \
  python3 /ERPLibre/docker/odoo_rc_db.py "$ODOO_RC" "$RUNTIME_ODOO_RC"
export ODOO_RC="$RUNTIME_ODOO_RC"

# start_warmup ODOO_ARGS... : runs script/odoo/warmup_http.py in the
# background, as run.sh does. Odoo loads a database registry on the first
# request for it, tens of seconds on a migrated database; the probe takes that
# wait instead of the first visitor. It reads the port from ODOO_ARGS, then
# from ODOO_RC, stops at the first HTTP answer or after two minutes, and ends
# with the container at the latest. Skipped with
# ERPLIBRE_DISABLE_WARMUP_HTTP=True, or when Odoo serves no HTTP.
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

# run_odoo ODOO_ARGS... : waits for PostgreSQL, then replaces this shell with
# Odoo, the probe beside it. Odoo becomes the container's PID 1: it receives
# the SIGTERM of "docker stop" itself and shuts down gracefully, where a shell
# in PID 1 ignores it and the container is killed after the stop timeout.
# Odoo's exit status is the container's. The probe, now Odoo's child, is
# reaped by the prefork master; under --workers=0 it stays a zombie entry
# until the container ends.
run_odoo() {
  cd $ODOO_PREFIX
  if [[ "${STOP_BEFORE_INIT}" == "True" ]]; then
    sleep 999999
  fi
  python3 ./docker/wait-for-psql.py --config "$ODOO_RC" --timeout=30
  local odoo_args=("$@")
  if [[ "${UPDATE_ALL_DB}" == "True" ]]; then
    odoo_args+=(-u all -d "${DB_NAME}")
  fi
  start_warmup "${odoo_args[@]}"
  exec python3 "$ODOO_EXEC_BIN" "${odoo_args[@]}" -c "$ODOO_RC"
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
