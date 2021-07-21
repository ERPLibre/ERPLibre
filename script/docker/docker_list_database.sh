#!/usr/bin/env bash

CURRENT=$(pwd)
BASENAME=$(basename "${CURRENT}")

docker exec -u root -ti ${BASENAME}_ERPLibre_1 /bin/bash -c "\
cd /ERPLibre; \
time make db_list; \
"
