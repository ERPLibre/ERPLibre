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
PLATEFORMES=""
POUSSER=false
SUR_BRANCHES=false
SANS_EXTRA=false
AFFICHER_PLATEFORMES=false
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
  elif [[ "$arg" == --platform=* ]]; then
    # « --platform=amd64,arm64 » : les architectures à construire.
    PLATEFORMES="${arg#--platform=}"
  elif [ "$arg" == "--branches" ]; then
    # Les dépôts suivent la tête de leur branche au lieu de leur
    # freeze-revision : une image de développement.
    SUR_BRANCHES=true
  elif [ "$arg" == "--without_extra" ]; then
    # L'installation standard, sans les modules extra que l'image porte
    # par défaut.
    SANS_EXTRA=true
  elif [ "$arg" == "--push" ]; then
    POUSSER=true
  elif [ "$arg" == "--print-platforms" ]; then
    AFFICHER_PLATEFORMES=true
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

# trixie pour Odoo 16 et plus, bookworm avant : aucune image Python 3.7 ou
# 3.8 n'existe sur trixie. La base est « python:<version>-slim-<nom> » : le
# Python vient de l'image officielle, jamais de Debian, et le nom de version
# ne change que les paquets du système.
if [ "${ODOO_VERSION%%.*}" -ge 16 ]; then
  DEBIAN_NAME=trixie
else
  DEBIAN_NAME=bookworm
fi
IMAGE_PYTHON="python:${PYTHON_VERSION}-slim-${DEBIAN_NAME}"

# Les architectures que l'image Python publie, parmi celles qu'ERPLibre
# construit. Le registre fait foi : python:3.12.16-slim-bookworm, par exemple,
# ne publie pas s390x quand sa variante trixie le fait.
plateformes_publiees() {
  docker buildx imagetools inspect "${IMAGE_PYTHON}" 2>/dev/null |
    awk '/Platform:/ {print $2}' |
    sed -E 's#^linux/##; s#/v[0-9]+$##' |
    grep -xE 'amd64|arm64|s390x' | sort -u
}

if [ "${AFFICHER_PLATEFORMES}" == true ]; then
  publiees=$(plateformes_publiees | xargs)
  if [ -z "${publiees}" ]; then
    echo -e "${Red}Error${Color_Off} ${IMAGE_PYTHON} illisible sur le registre" >&2
    exit 1
  fi
  echo "${publiees}"
  exit 0
fi

# L'architecture du démon, celle qu'une construction sans --platform produit.
ARCH_HOTE=$(docker version --format '{{.Server.Arch}}' 2>/dev/null)
if [ -z "${ARCH_HOTE}" ]; then
  case "$(uname -m)" in
    x86_64) ARCH_HOTE=amd64 ;;
    aarch64 | arm64) ARCH_HOTE=arm64 ;;
    *) ARCH_HOTE=$(uname -m) ;;
  esac
fi
PLATEFORMES="${PLATEFORMES:-${ARCH_HOTE}}"
PLATEFORMES="${PLATEFORMES//,/ }"

# Une architecture étrangère se construit sous émulation QEMU : sans elle,
# la première commande RUN échoue sur « exec format error », loin de sa
# cause. La refuser ici nomme le geste qui manque.
# « linux/amd64, linux/amd64/v2, linux/arm64… » devient une plateforme par
# ligne, sans la variante, pour une comparaison exacte.
EMULEES=$(docker buildx inspect default 2>/dev/null |
  awk -F': *' '/^Platforms:/ {print $2}' |
  tr ',' '\n' | sed -E 's/^ +//; s#/v[0-9]+$##' | sort -u)
publiees=$(plateformes_publiees | xargs)
for arch in ${PLATEFORMES}; do
  case "${arch}" in
    amd64 | arm64 | s390x) ;;
    *)
      echo -e "${Red}Error${Color_Off} architecture inconnue : ${arch} (amd64, arm64, s390x)"
      exit 1
      ;;
  esac
  if [ -n "${publiees}" ] && [[ " ${publiees} " != *" ${arch} "* ]]; then
    echo -e "${Red}Error${Color_Off} ${IMAGE_PYTHON} ne publie pas ${arch} (publie : ${publiees})"
    exit 1
  fi
  if [ "${arch}" != "${ARCH_HOTE}" ] && ! grep -qx "linux/${arch}" <<<"${EMULEES}"; then
    echo -e "${Red}Error${Color_Off} aucune émulation de linux/${arch} pour docker buildx"
    echo "  sudo bash script/install/install_container.sh --multiarch"
    exit 1
  fi
done

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
if ! ./script/docker/docker_update_version.py --version=${ERPLIBRE_VERSION} --base=${ERPLIBRE_DOCKER_BASE} --prod=${ERPLIBRE_DOCKER_PROD} --ignore_edit_docker; then
  echo -e "${Red}Error${Color_Off} ./script/docker/docker_build.sh when execute docker_update_version.py"
  exit 1
fi

cd docker

# Chaque Dockerfile reçoit ses seuls arguments : Docker avertit sur un
# argument que personne ne lit, et l'avertissement noie celui qui compterait.
ARGS_BASE="--build-arg PYTHON_VERSION=${PYTHON_VERSION} --build-arg DEBIAN_NAME=${DEBIAN_NAME} --build-arg ODOO_VERSION=${ODOO_VERSION}"
ARGS_PROD="--build-arg ERPLIBRE_VERSION=${ERPLIBRE_VERSION_MAIN} --build-arg POETRY_VERSION=${POETRY_VERSION}"
ARGS_PROD="${ARGS_PROD} --build-arg WORKING_BRANCH=${EL_BRANCHE} --build-arg WORKING_HASH=${EL_HASH}"
# ERPLIBRE_CODE_OWNER=root construit une image dont Odoo ne peut pas réécrire
# le code, et donc ne peut pas le tirer ; absent, le Dockerfile prend « odoo ».
if [[ -n "${ERPLIBRE_CODE_OWNER:-}" ]]; then
  ARGS_PROD="${ARGS_PROD} --build-arg ERPLIBRE_CODE_OWNER=${ERPLIBRE_CODE_OWNER}"
fi
# Sans --branches, le Dockerfile clone chaque dépôt sur son freeze-revision.
if [ "${SUR_BRANCHES}" == true ]; then
  ARGS_PROD="${ARGS_PROD} --build-arg EL_FREEZE=0"
fi
# Sans --without_extra, l'image porte les modules extra.
if [ "${SANS_EXTRA}" == true ]; then
  ARGS_PROD="${ARGS_PROD} --build-arg EL_WITH_EXTRA=0"
fi

set -e

# Une étiquette par architecture. Celle de l'hôte garde l'étiquette sans
# suffixe, celle que lance docker-compose.yml ; les autres prennent
# « -<arch> ». Pousser donne à chacune son suffixe, puis l'étiquette sans
# suffixe devient le manifeste qui les réunit : un « docker pull » y prend
# l'architecture de la machine qui tire.
poussees_base=()
poussees_prod=()
hote_bati=false
for arch in ${PLATEFORMES}; do
  suffixe="-${arch}"
  if [ "${POUSSER}" == false ] && [ "${arch}" == "${ARCH_HOTE}" ]; then
    suffixe=""
    hote_bati=true
  fi
  base="${ERPLIBRE_DOCKER_BASE_VERSION}${suffixe}"
  prod="${ERPLIBRE_DOCKER_PROD_VERSION}${suffixe}"

  echo "docker build --platform linux/${arch} ${ARGS} ${ARGS_BASE} -f Dockerfile.base -t ${base} ."
  docker build --platform "linux/${arch}" ${ARGS} ${ARGS_BASE} -f Dockerfile.base -t "${base}" .

  echo "docker build --platform linux/${arch} ${ARGS} ${ARGS_PROD} --build-arg ERPLIBRE_IMAGE_NAME=${ERPLIBRE_VERSION}${suffixe} -f Dockerfile.prod.pkg -t ${prod} ."
  docker build --platform "linux/${arch}" ${ARGS} ${ARGS_PROD} --build-arg ERPLIBRE_IMAGE_NAME="${ERPLIBRE_VERSION}${suffixe}" -f Dockerfile.prod.pkg -t "${prod}" .

  if [ "${POUSSER}" == true ]; then
    docker push "${base}"
    docker push "${prod}"
    poussees_base+=("${base}")
    poussees_prod+=("${prod}")
  fi
done

if [ "${POUSSER}" == true ]; then
  docker buildx imagetools create -t "${ERPLIBRE_DOCKER_BASE_VERSION}" "${poussees_base[@]}"
  docker buildx imagetools create -t "${ERPLIBRE_DOCKER_PROD_VERSION}" "${poussees_prod[@]}"
fi

cd -
if [ "${hote_bati}" == true ]; then
  docker compose up -d
else
  echo "L'architecture de l'hôte (${ARCH_HOTE}) n'est pas bâtie en local : docker compose n'est pas relancé."
fi
