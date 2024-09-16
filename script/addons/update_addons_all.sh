#!/usr/bin/env bash

echo "Update all on BD '$1'"

./run.sh --no-http --stop-after-init -d "$1" -u all

retVal=$?
if [[ $retVal -ne 0 ]]; then
  echo "Error run.sh into update_addons_all.sh"
  exit 1
fi
