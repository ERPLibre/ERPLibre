#!/usr/bin/env bash

CURRENT=$(pwd)
BASENAME=$(basename "${CURRENT}")
# Docker remove dot
BASENAME="${BASENAME//./}"

docker exec -u root -ti ${BASENAME}_ERPLibre_1 bash
