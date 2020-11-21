#!/usr/bin/env bash
. ./env_var.sh

ARGS=""
IS_RELEASE=false
ERPLIBRE_DOCKER_BASE="technolibre/erplibre-base"
ERPLIBRE_DOCKER_PROD="technolibre/erplibre"

for arg in "$@"
do
    if [ "$arg" == "--no-cache" ]
    then
        ARGS="${ARGS} --no-cache"
    elif [ "$arg" == "--release" ]
    then
        IS_RELEASE=true
    fi
done

if [ "$IS_RELEASE" == false ]
then
  # Add commit hash when not a release
  ERPLIBRE_VERSION="${ERPLIBRE_VERSION}_$(git rev-parse --short HEAD)"
fi

ERPLIBRE_DOCKER_BASE_VERSION="${ERPLIBRE_DOCKER_BASE}:${ERPLIBRE_VERSION}"
ERPLIBRE_DOCKER_PROD_VERSION="${ERPLIBRE_DOCKER_PROD}:${ERPLIBRE_VERSION}"

echo "Create docker ${ERPLIBRE_DOCKER_PROD_VERSION}"

# Rewrite docker-compose
./script/docker_update_version.py --version=${ERPLIBRE_VERSION} --base=${ERPLIBRE_DOCKER_BASE} --prod=${ERPLIBRE_DOCKER_PROD}

cd docker

ARGS="${ARGS} --build-arg=WORKING_BRANCH=$(git rev-parse --abbrev-ref HEAD) --build-arg=WORKING_HASH=$(git rev-parse --verify HEAD)"

set -e

# Build base
docker build ${ARGS} -f Dockerfile.base -t ${ERPLIBRE_DOCKER_BASE_VERSION} .

# Build prod
docker build ${ARGS} -f Dockerfile.prod.pkg -t ${ERPLIBRE_DOCKER_PROD_VERSION} .

cd -
docker-compose up -d
