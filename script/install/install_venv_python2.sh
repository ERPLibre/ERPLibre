#!/usr/bin/env bash
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Venv d'Odoo en Python 2, et le Poetry qui le gère.
#
# Usage : install_venv_python2.sh <Venv_Path> <Python2_Exec> <Poetry_Version>
# Lancé depuis la racine du dépôt. Idempotent : ce qui existe est gardé.
#
# Trois pièces, parce qu'aucun outil du flux Python 3 ne sert tel quel :
#
#   .venv.poetry<version>   venv Python 3 qui porte Poetry et virtualenv.
#                           Poetry 1.1, le dernier à gérer un projet Python 2,
#                           ne s'installe pas DANS un venv 2.7 et ne démarre
#                           pas au-delà de Python 3.11 (six.moves introuvable).
#                           virtualenv est borné sous 20.22, première version
#                           à ne plus savoir créer un environnement Python 2.
#   <Venv_Path>             le venv 2.7 d'Odoo, créé par ce virtualenv :
#                           Python 2 n'a pas de module venv.
#   <Venv_Path>/bin/poetry  une enveloppe, au chemin où tout le dépôt appelle
#                           Poetry (install_locally.sh, poetry_update.py,
#                           poetry_add_build_dependency.sh, Dockerfile). Elle
#                           épingle VIRTUAL_ENV : avec « virtualenvs.create =
#                           false », Poetry installerait sinon dans le venv
#                           Python 3 qui le fait tourner.
#
# EL_PY2_HELPER_PYTHON désigne l'interpréteur Python 3 du venv de Poetry ;
# sans lui, lib_python_provider.sh fournit EL_PY2_HELPER_PYTHON_VERSION.

if [ -z "$1" ] || [ -z "$2" ] || [ -z "$3" ]; then
  echo "Usage: $0 <Venv_Path> <Python2_Exec> <Poetry_Version>"
  exit 1
fi

VENV_PATH="${1%/}"
PYTHON2_EXEC="$2"
POETRY_VERSION="$3"
HELPER_PATH=".venv.poetry${POETRY_VERSION}"
EL_PY2_HELPER_PYTHON_VERSION="${EL_PY2_HELPER_PYTHON_VERSION:-3.11.16}"

if [[ ! -x "${HELPER_PATH}/bin/poetry" ]] \
  || [[ ! -x "${HELPER_PATH}/bin/virtualenv" ]]; then
  HELPER_PYTHON="${EL_PY2_HELPER_PYTHON:-}"
  if [[ -z "${HELPER_PYTHON}" ]]; then
    # shellcheck source=script/install/lib_python_provider.sh
    . ./script/install/lib_python_provider.sh
    HELPER_PYTHON="$(el_python_exec "${EL_PY2_HELPER_PYTHON_VERSION}" mineure)"
  fi
  if [[ -z "${HELPER_PYTHON}" ]] || [[ ! -x "${HELPER_PYTHON}" ]]; then
    echo "Aucun Python ${EL_PY2_HELPER_PYTHON_VERSION} pour faire tourner Poetry ${POETRY_VERSION}."
    echo "  Voir : mise install python@${EL_PY2_HELPER_PYTHON_VERSION}"
    exit 1
  fi
  echo "---- Poetry ${POETRY_VERSION} dans ${HELPER_PATH} ($("${HELPER_PYTHON}" -V 2>&1)) ----"
  rm -rf "${HELPER_PATH}"
  if ! "${HELPER_PYTHON}" -m venv "${HELPER_PATH}" \
    || ! "${HELPER_PATH}/bin/pip" install -q --upgrade pip \
    || ! "${HELPER_PATH}/bin/pip" install -q \
      "poetry==${POETRY_VERSION}" "virtualenv<20.22"; then
    echo "Echec de creation de ${HELPER_PATH}."
    exit 1
  fi
fi

if [[ ! -f "${VENV_PATH}/pyvenv.cfg" ]]; then
  echo "---- Venv Python 2 ${VENV_PATH} ----"
  if ! "${HELPER_PATH}/bin/virtualenv" -q -p "${PYTHON2_EXEC}" "${VENV_PATH}"; then
    echo "Echec de creation de ${VENV_PATH}."
    exit 1
  fi
fi

# Chemins calculés à l'exécution depuis l'emplacement de l'enveloppe : le
# dépôt reste déplaçable. POETRY_CACHE_DIR est le « cache-dir = "./" » de
# poetry.toml rendu absolu, forme que Poetry 1.1 exige pour ses URI de cache.
#
# -fpermissive : les paquets épinglés par Odoo 10 précèdent souvent les roues
# manylinux et se compilent. Leur C, écrit pour GCC 4 à 6, heurte des
# diagnostics que GCC 14 a rendus bloquants (types de pointeurs
# incompatibles) ; le drapeau les ramène à des avertissements. Un GCC
# antérieur l'ignore en C, avec un simple avertissement.
#
# libldap_r : voir script/install/lib_ldap_compat.sh.
cat > "${VENV_PATH}/bin/poetry" << EOF
#!/usr/bin/env bash
VENV="\$(cd "\$(dirname "\$0")/.." && pwd)"
export VIRTUAL_ENV="\${VENV}"
export POETRY_CACHE_DIR="\$(dirname "\${VENV}")/"
export CFLAGS="\${CFLAGS:+\${CFLAGS} }-fpermissive"
. "\$(dirname "\${VENV}")/script/install/lib_ldap_compat.sh" \\
  && el_ldap_r_compat "\${VENV}/lib/ldap_r_compat"
exec "\$(dirname "\${VENV}")/${HELPER_PATH}/bin/poetry" "\$@"
EOF
chmod +x "${VENV_PATH}/bin/poetry"
echo "Venv ${VENV_PATH} pret, Poetry ${POETRY_VERSION} par ${HELPER_PATH}."
