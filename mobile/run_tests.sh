#!/usr/bin/env bash

if [[ ! -d "./mobile/erplibre_home_mobile" ]]; then
  echo "Please, run installation ./mobile/install_mobile_dev.sh before run this script ./mobile/run_tests.sh"
  exit 1
fi

cd mobile/erplibre_home_mobile

npm install
npm test

cd -
