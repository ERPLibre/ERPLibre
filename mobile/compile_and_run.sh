#!/usr/bin/env bash

if [[ ! -d "./mobile/erplibre_home_mobile" ]]; then
  echo "Please, run installation ./mobile/install_mobile_dev.sh before run this script ./mobile/compile_and_run.sh"
  exit 1
fi

cd mobile/erplibre_home_mobile

npm install
npm run build && npx cap sync
npx cap run android

cd -
