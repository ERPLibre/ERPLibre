#!/usr/bin/env bash

if [[ ! -d "./mobile/technolibre_home_mobile" ]]; then
  echo "Please, run installation ./mobile/install_mobile_dev.sh before run this script ./mobile/compile_and_run.sh"
  exit 1
fi

if [[ ! -d "./mobile/technolibre_home_mobile/technolibre_home" ]]; then
  echo "Please, check repo is working."
  exit 1
fi

cd mobile/technolibre_home_mobile/technolibre_home

npm install
npm run build && npx cap sync
npx cap run android

cd -
