#!/usr/bin/env bash
. ./env_var.sh
Red='\033[0;31m'         # Red
Color_Off='\033[0m'      # Text Reset

ERPLIBRE_IMAGE_NAME=$(cat .erplibre-semver-version|xargs)
ERPLIBRE_VERSION_MAIN=$(cat .erplibre-version|xargs)
ODOO_VERSION=$(cat .odoo-version|xargs)
PYTHON_VERSION=$(cat .python-version|xargs)
POETRY_VERSION=$(cat .poetry-version|xargs)

ARGS=""
IS_RELEASE=false
IS_RELEASE_ALPHA=false
IS_RELEASE_BETA=false
ERPLIBRE_DOCKER_BASE="technolibre/erplibre-base"
ERPLIBRE_DOCKER_PROD="technolibre/erplibre"

output_version=""

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
    elif [ "$arg" == "--odoo_16" ]
    then
        output_version=$(python ./script/version/get_version.py --odoo_version 16.0)
    elif [ "$arg" == "--odoo_14" ]
    then
        output_version=$(python ./script/version/get_version.py --odoo_version 14.0)
    elif [ "$arg" == "--odoo_12" ]
    then
        output_version=$(python ./script/version/get_version.py --odoo_version 12.0)
    fi
done

if [ "$output_version" != "" ]; then
    ODOO_VERSION=$(echo "$output_version" | awk 'NR==1')
    POETRY_VERSION=$(echo "$output_version" | awk 'NR==2')
    PYTHON_VERSION=$(echo "$output_version" | awk 'NR==3')
    ERPLIBRE_VERSION_MAIN=$(echo "$output_version" | awk 'NR==4')
fi

echo "Build with"
echo $ERPLIBRE_VERSION_MAIN
echo $ODOO_VERSION
echo $PYTHON_VERSION
echo $POETRY_VERSION

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
  ERPLIBRE_VERSION="${ERPLIBRE_VERSION}_$(git rev-parse --short HEAD)"
fi


ERPLIBRE_DOCKER_BASE_VERSION="${ERPLIBRE_DOCKER_BASE}:${ERPLIBRE_VERSION}"
ERPLIBRE_DOCKER_PROD_VERSION="${ERPLIBRE_DOCKER_PROD}:${ERPLIBRE_VERSION}"
ERPLIBRE_VERSION_MAIN="odoo${ODOO_VERSION}_python${PYTHON_VERSION}"

echo "Create docker ${ERPLIBRE_DOCKER_PROD_VERSION}"

# Rewrite docker-compose
./script/docker/docker_update_version.py --version=${ERPLIBRE_VERSION} --base=${ERPLIBRE_DOCKER_BASE} --prod=${ERPLIBRE_DOCKER_PROD} --ignore_edit_docker

ARGS="${ARGS} --build-arg ERPLIBRE_VERSION=${ERPLIBRE_VERSION_MAIN} --build-arg ODOO_VERSION=${ODOO_VERSION} --build-arg POETRY_VERSION=${POETRY_VERSION} --build-arg ERPLIBRE_IMAGE_NAME=${ERPLIBRE_VERSION} --build-arg PYTHON_VERSION=${PYTHON_VERSION}"

retVal=$?
if [[ $retVal -ne 0 ]]; then
    echo -e "${Red}Error${Color_Off} ./script/docker/docker_build.sh when execute docker_update_version.py"
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
docker compose up -d
