#!/usr/bin/env bash
. ./env_var.sh
Red='\033[0;31m'    # Red
Color_Off='\033[0m' # Text Reset

ERPLIBRE_IMAGE_NAME=$(cat .erplibre-semver-version | xargs)
ERPLIBRE_VERSION_MAIN=$(cat .erplibre-version | xargs)
ODOO_VERSION=$(cat .odoo-version | xargs)
PYTHON_VERSION=$(cat .python-odoo-version | xargs)
POETRY_VERSION=$(cat .poetry-version | xargs)

ARGS=""
IS_RELEASE=false
IS_RELEASE_ALPHA=false
IS_RELEASE_BETA=false
ERPLIBRE_DOCKER_BASE="technolibre/erplibre-base"
ERPLIBRE_DOCKER_PROD="technolibre/erplibre"

output_version=""

for arg in "$@"; do
  if [ "$arg" == "--no-cache" ]; then
    ARGS="${ARGS} --no-cache"
  elif [ "$arg" == "--release" ]; then
    IS_RELEASE=true
  elif [ "$arg" == "--release_alpha" ]; then
    IS_RELEASE_ALPHA=true
  elif [ "$arg" == "--release_beta" ]; then
    IS_RELEASE_BETA=true
  elif [ "$arg" == "--odoo_18" ]; then
    output_version=$(python ./script/version/get_version.py --odoo_version 18.0)
  elif [ "$arg" == "--odoo_17" ]; then
    output_version=$(python ./script/version/get_version.py --odoo_version 17.0)
  elif [ "$arg" == "--odoo_16" ]; then
    output_version=$(python ./script/version/get_version.py --odoo_version 16.0)
  elif [ "$arg" == "--odoo_15" ]; then
    output_version=$(python ./script/version/get_version.py --odoo_version 15.0)
  elif [ "$arg" == "--odoo_14" ]; then
    output_version=$(python ./script/version/get_version.py --odoo_version 14.0)
  elif [ "$arg" == "--odoo_13" ]; then
    output_version=$(python ./script/version/get_version.py --odoo_version 13.0)
  elif [ "$arg" == "--odoo_12" ]; then
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

if [ "$IS_RELEASE_ALPHA" == true ]; then
  # Add commit hash when release alpha
  ERPLIBRE_VERSION="${ERPLIBRE_VERSION}_ALPHA_odoo_${ODOO_VERSION}_$(git rev-parse --short HEAD)"
elif [ "$IS_RELEASE_BETA" == true ]; then
  # Add commit hash when release beta
  ERPLIBRE_VERSION="${ERPLIBRE_VERSION}_BETA_odoo_${ODOO_VERSION}_$(git rev-parse --short HEAD)"
elif [ "$IS_RELEASE" == false ]; then
  # Add commit hash when not a release
  ERPLIBRE_VERSION="${ERPLIBRE_VERSION}_odoo_${ODOO_VERSION}_$(git rev-parse --short HEAD)"
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

ARGS="${ARGS} --build-arg WORKING_BRANCH=$(git rev-parse --abbrev-ref HEAD) --build-arg WORKING_HASH=$(git rev-parse --verify HEAD)"

# UNE seule base, bookworm, pour toutes les versions d'Odoo.
#
# La base est « python:<version>-slim-<nom> » : le Python vient de l'image
# officielle, jamais de Debian. Changer de nom de version ne change donc pas
# l'interpréteur, et les variantes bookworm existent jusqu'à 3.7.17 — vérifié
# sur le registre. Rien n'obligeait les vieux Odoo à rester sur bullseye, dont
# le dépôt de sécurité est aujourd'hui démantelé.
#
# Le build de wkhtmltopdf suit la version : celui de bullseye réclame
# libssl1.1, absente de bookworm ; celui de bookworm réclame libssl3, et ses
# quinze dépendances y sont toutes — vérifié dans l'index.
ARGS="${ARGS} --build-arg DEBIAN_NAME=bookworm --build-arg URL_WKHTMLTOX=github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-3/wkhtmltox_0.12.6.1-3.bookworm_amd64.deb --build-arg SHA1SUM_WKTHMLTOX=e9f95436298c77cc9406bd4bbd242f4771d0a4b2"
set -e

# Build base
echo "docker build ${ARGS} -f Dockerfile.base -t ${ERPLIBRE_DOCKER_BASE_VERSION} ."
docker build ${ARGS} -f Dockerfile.base -t ${ERPLIBRE_DOCKER_BASE_VERSION} .

# Build prod
echo "docker build ${ARGS} -f Dockerfile.prod.pkg -t ${ERPLIBRE_DOCKER_PROD_VERSION} ."
docker build ${ARGS} -f Dockerfile.prod.pkg -t ${ERPLIBRE_DOCKER_PROD_VERSION} .

cd -
docker compose up -d
