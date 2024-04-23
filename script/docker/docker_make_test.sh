#!/usr/bin/env bash

CURRENT=$(pwd)
BASENAME=$(basename "${CURRENT}")
# Docker remove dot
BASENAME="${BASENAME//./}"
# Lowercase
BASENAME="${BASENAME,,}"

docker exec -u root -ti ${BASENAME}-ERPLibre-1 /bin/bash -c "\
cd /ERPLibre; \
time make test; \
"

retVal=$?
if [[ $retVal -ne 0 ]]; then
  docker exec -u root -ti ${BASENAME}_ERPLibre_1 /bin/bash -c "\
  cd /ERPLibre; \
  time make test; \
  "
fi
