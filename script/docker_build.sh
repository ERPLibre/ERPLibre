#!/usr/bin/env bash
. ./env_var.sh

ARGS=""

for arg in "$@"
do
    if [ "$arg" == "--no-cache" ]
    then
        ARGS="${ARGS} --no-cache"
    fi
done

# Rewrite docker-compose
./script/docker_update_version.py --version=${ERPLIBRE_VERSION} --base=${ERPLIBRE_DOCKER_BASE} --prod=${ERPLIBRE_DOCKER_PROD}

cd docker

ARGS="${ARGS} --build-arg=WORKING_BRANCH=$(git rev-parse --abbrev-ref HEAD)"

set -e

# Build base
docker build ${ARGS} -f Dockerfile.base -t ${ERPLIBRE_DOCKER_BASE_VERSION} .

# Build prod
docker build ${ARGS} -f Dockerfile.prod.pkg -t ${ERPLIBRE_DOCKER_PROD_VERSION} .

cd -
docker-compose up -d
