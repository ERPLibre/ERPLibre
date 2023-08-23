#!/usr/bin/env bash
. ./env_var.sh

ARGS=""
IS_RELEASE=false
IS_RELEASE_ALPHA=false
IS_RELEASE_BETA=false
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
    elif [ "$arg" == "--release_alpha" ]
    then
        IS_RELEASE_ALPHA=true
    elif [ "$arg" == "--release_beta" ]
    then
        IS_RELEASE_BETA=true
    fi
done

if [ "$IS_RELEASE_ALPHA" == true ]
then
  # Add commit hash when release alpha
  ERPLIBRE_VERSION="${ERPLIBRE_VERSION}_ALPHA_$(git rev-parse --short HEAD)"
elif [ "$IS_RELEASE_BETA" == true ]
then
  # Add commit hash when release beta
  ERPLIBRE_VERSION="${ERPLIBRE_VERSION}_BETA_$(git rev-parse --short HEAD)"
elif [ "$IS_RELEASE" == false ]
then
  # Add commit hash when not a release
  ERPLIBRE_VERSION="${ERPLIBRE_VERSION}_odoo14_$(git rev-parse --short HEAD)"
fi


ERPLIBRE_DOCKER_BASE_VERSION="${ERPLIBRE_DOCKER_BASE}:${ERPLIBRE_VERSION}"
ERPLIBRE_DOCKER_PROD_VERSION="${ERPLIBRE_DOCKER_PROD}:${ERPLIBRE_VERSION}"

echo "Create docker ${ERPLIBRE_DOCKER_PROD_VERSION}"

# Rewrite docker-compose
./script/docker/docker_update_version.py --version=${ERPLIBRE_VERSION} --base=${ERPLIBRE_DOCKER_BASE} --prod=${ERPLIBRE_DOCKER_PROD}

retVal=$?
if [[ $retVal -ne 0 ]]; then
    echo "Error ./script/docker/docker_build.sh when execute docker_update_version.py"
    exit 1
fi

cd docker

ARGS="${ARGS} --build-arg=WORKING_BRANCH=$(git rev-parse --abbrev-ref HEAD) --build-arg=WORKING_HASH=$(git rev-parse --verify HEAD)"

set -e

# Build base
docker build ${ARGS} -f Dockerfile.base -t ${ERPLIBRE_DOCKER_BASE_VERSION} .

# Build prod
docker build ${ARGS} -f Dockerfile.prod.pkg -t ${ERPLIBRE_DOCKER_PROD_VERSION} .

cd -
docker-compose up -d
