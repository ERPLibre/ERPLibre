#!/usr/bin/env bash
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

if [ "$ODOO_MODE_TEST" = "true" ]; then
  ./odoo_bin.sh -c "${CONFIG_PATH}" --limit-time-real 99999 --limit-time-cpu 99999 --limit-memory-hard=0 --log-level=test --test-enable --no-http --stop-after-init "$@"
else
  ./odoo_bin.sh -c "${CONFIG_PATH}" --limit-time-real 99999 --limit-time-cpu 99999 --limit-memory-hard=0 "$@"
fi
# When need more memory RAM for instance by force
#python3 ./odoo/odoo-bin -c ${CONFIG_PATH} --limit-time-real 99999 --limit-time-cpu 99999 --limit-memory-soft=8589934592 --limit-memory-hard=10737418240 $@

retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo "${Red}Error${Color_Off} run.sh"
  exit 1
fi
