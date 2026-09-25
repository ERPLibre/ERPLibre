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

# get_version.py ne lit qu'un JSON : n'importe quel python3 le fait tourner.
# « python » nu n'existe pas sur Debian sans python-is-python3, et l'appel
# muet laissait output_version VIDE : la construction repartait alors sur les
# versions du checkout, donc une image d'Odoo 18 publiee sous le nom de celle
# qu'on avait demandee. L'echec s'arrete ici plutot que de se taire.
EL_PY=""
for candidat in "./.venv.erplibre/bin/python" python3 python; do
  if command -v "${candidat}" >/dev/null 2>&1; then
    EL_PY="${candidat}"
    break
  fi
done

for arg in "$@"; do
  if [ "$arg" == "--no-cache" ]; then
    ARGS="${ARGS} --no-cache"
  elif [ "$arg" == "--release" ]; then
    IS_RELEASE=true
  elif [ "$arg" == "--release_alpha" ]; then
    IS_RELEASE_ALPHA=true
  elif [ "$arg" == "--release_beta" ]; then
    IS_RELEASE_BETA=true
  elif [[ "$arg" == --odoo_* ]]; then
    # « --odoo_15 » designe la version 15.0 du catalogue.
    odoo_demande="${arg#--odoo_}.0"
    if [ -z "${EL_PY}" ]; then
      echo -e "${Red}Error${Color_Off} aucun python pour lire conf/supported_version_erplibre.json"
      exit 1
    fi
    if ! output_version=$("${EL_PY}" ./script/version/get_version.py --odoo_version "${odoo_demande}") || [ -z "${output_version}" ]; then
      echo -e "${Red}Error${Color_Off} version Odoo inconnue : ${odoo_demande}"
      exit 1
    fi
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

# Le conteneur CLONE le depot public et se place sur ce commit. Un commit qui
# n'y est pas encore n'existe pas pour lui : la construction s'arrete deux
# minutes plus tard, apres le clone, sur « fatal: reference is not a tree » --
# un message qui ne nomme ni le commit manquant ni le geste qui manque.
EL_BRANCHE=$(git rev-parse --abbrev-ref HEAD)
EL_HASH=$(git rev-parse --verify HEAD)
# Les deux ecritures de ENV : « ENV cle valeur », le format herite dont
# buildkit se plaint, et « ENV cle=valeur ». Lire les deux evite que passer de
# l'une a l'autre vide cette variable -- et un EL_DEPOT vide ne faisait pas
# echouer la verification, il la SAUTAIT.
EL_DEPOT=$(sed -n \
  's/^ENV[[:space:]]\+REPO_MANIFEST_URL[[:space:]=]\+"\?\([^"[:space:]]\+\)"\?.*/\1/p' \
  docker/Dockerfile.prod.pkg | head -1)

verifier_commit_publie() {
  local sortie rc distant
  if [ -z "${EL_DEPOT}" ]; then
    echo -e "${Red}Error${Color_Off} REPO_MANIFEST_URL illisible dans docker/Dockerfile.prod.pkg"
    echo "  Sans elle, rien ne verifie que le commit bati est publie."
    exit 1
  fi
  sortie=$(git ls-remote --heads "${EL_DEPOT}" "${EL_BRANCHE}" 2>/dev/null)
  rc=$?
  if [ ${rc} -ne 0 ]; then
    # Hors ligne : on ne refuse pas sur une ignorance.
    echo "Depot injoignable, verification du commit publie sautee."
    return 0
  fi
  distant=$(echo "${sortie}" | cut -f1)
  if [ -z "${distant}" ]; then
    echo -e "${Red}Error${Color_Off} la branche ${EL_BRANCHE} n'est pas sur ${EL_DEPOT}"
    echo "  L'image la clone par son nom : la publier d'abord."
    echo "  git push -u origin ${EL_BRANCHE}"
    exit 1
  fi
  [ "${distant}" = "${EL_HASH}" ] && return 0
  # La tete distante est un objet LOCAL des que la branche locale est en
  # avance, le seul cas qui nous occupe : l'ancetre se verifie alors sans
  # reseau. Quand elle ne l'est pas, on ne sait pas, et on laisse passer.
  if git cat-file -e "${distant}^{commit}" 2>/dev/null; then
    if ! git merge-base --is-ancestor "${EL_HASH}" "${distant}"; then
      echo -e "${Red}Error${Color_Off} le commit ${EL_HASH} n'est pas publie"
      echo "  L'image clone ${EL_DEPOT} et se place sur ce commit."
      echo "  git push origin ${EL_BRANCHE}"
      exit 1
    fi
  fi
}
verifier_commit_publie

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

ARGS="${ARGS} --build-arg WORKING_BRANCH=${EL_BRANCHE} --build-arg WORKING_HASH=${EL_HASH}"

# Bookworm pour tout Python 3, buster pour Python 2.
#
# La base est « python:<version>-slim-<nom> » : le Python vient de l'image
# officielle, jamais de Debian. Changer de nom de version ne change donc pas
# l'interpréteur, et les variantes bookworm existent jusqu'à 3.7.17 — vérifié
# sur le registre. Rien n'obligeait les vieux Odoo à rester sur bullseye, dont
# le dépôt de sécurité est aujourd'hui démantelé.
#
# Python 2.7 n'a d'image que sur buster, archivée : son client PostgreSQL
# vient d'apt-archive, où le plus récent est le 16.
#
# Le build de wkhtmltopdf suit la version : celui de bullseye réclame
# libssl1.1, absente de bookworm ; celui de bookworm réclame libssl3, et ses
# quinze dépendances y sont toutes — vérifié dans l'index. La série 0.12.6.1
# n'a pas de build buster : c'est la 0.12.6-1.
if [[ "${PYTHON_VERSION}" == 2.* ]]; then
  ARGS="${ARGS} --build-arg DEBIAN_NAME=buster --build-arg URL_WKHTMLTOX=github.com/wkhtmltopdf/packaging/releases/download/0.12.6-1/wkhtmltox_0.12.6-1.buster_amd64.deb --build-arg SHA1SUM_WKTHMLTOX=d9f259a67e05e1c221d48b504453645e6c491fab --build-arg PGDG_URL=http://apt-archive.postgresql.org/pub/repos/apt/ --build-arg PG_CLIENT_VERSION=16"
else
  ARGS="${ARGS} --build-arg DEBIAN_NAME=bookworm --build-arg URL_WKHTMLTOX=github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1-3/wkhtmltox_0.12.6.1-3.bookworm_amd64.deb --build-arg SHA1SUM_WKTHMLTOX=e9f95436298c77cc9406bd4bbd242f4771d0a4b2"
fi
set -e

# Build base
echo "docker build ${ARGS} -f Dockerfile.base -t ${ERPLIBRE_DOCKER_BASE_VERSION} ."
docker build ${ARGS} -f Dockerfile.base -t ${ERPLIBRE_DOCKER_BASE_VERSION} .

# Build prod
echo "docker build ${ARGS} -f Dockerfile.prod.pkg -t ${ERPLIBRE_DOCKER_PROD_VERSION} ."
docker build ${ARGS} -f Dockerfile.prod.pkg -t ${ERPLIBRE_DOCKER_PROD_VERSION} .

cd -
docker compose up -d
