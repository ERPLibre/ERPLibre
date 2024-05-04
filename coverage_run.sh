#!/usr/bin/env bash
source ./.venv/bin/activate
Red='\033[0;31m'         # Red
Color_Off='\033[0m'      # Text Reset

CONFIG_PATH="./config.conf"
ORIGIN_CONFIG_PATH=CONFIG_PATH
if [ ! -f "${CONFIG_PATH}" ]; then
  CONFIG_PATH="/etc/odoo/odoo.conf"
  if [ ! -f "${CONFIG_PATH}" ]; then
    echo "${Red}Cannot find${Color_Off} ERPLibre configuration ${ORIGIN_CONFIG_PATH}, did you install ERPLibre? > make install"
    exit 1
  fi
fi

coverage run -p ./odoo/odoo-bin -c "${CONFIG_PATH}" --limit-time-real 99999 --limit-time-cpu 99999 "$@"
retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo "${Red}Error${Color_Off} run.sh"
  exit 1
fi
