#!/usr/bin/env bash
source ./.venv/bin/activate

CONFIG_PATH="./config.conf"
ORIGIN_CONFIG_PATH=CONFIG_PATH
if [ ! -f "${CONFIG_PATH}" ]; then
  CONFIG_PATH="/etc/odoo/odoo.conf"
  if [ ! -f "${CONFIG_PATH}" ]; then
    echo "Cannot find ERPLibre configuration ${ORIGIN_CONFIG_PATH}, did you install ERPLibre? > make install"
    exit 1
  fi
fi

python3 ./odoo/odoo-bin -c ${CONFIG_PATH} --limit-time-real 99999 --limit-time-cpu 99999 --limit-memory-soft=8589934592 --limit-memory-hard=10737418240 $@
retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo "Error run.sh"
  exit 1
fi
