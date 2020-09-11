#!/usr/bin/env bash
. ./env_var.sh

cd docker

ARGS=--build-arg=WORKING_BRANCH=$(git rev-parse --abbrev-ref HEAD)
set -e
# Build base
docker build ${ARGS} -f Dockerfile.base -t ${ERPLIBRE_DOCKER_BASE_VERSION} .

# Build prod
docker build ${ARGS} -f Dockerfile.prod.pkg -t ${ERPLIBRE_DOCKER_PROD_VERSION} .

cd -
# Rewrite docker-compose
./script/docker_update_version.py --version=${ERPLIBRE_VERSION} --base=${ERPLIBRE_DOCKER_BASE} --prod=${ERPLIBRE_DOCKER_PROD}
docker-compose up -d
