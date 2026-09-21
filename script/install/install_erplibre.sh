#!/usr/bin/env bash
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Pose le venv d'OUTILLAGE d'ERPLibre, sans qu'une version d'Odoo soit
# choisie : chemin et version se lisent dans conf/, versionné, et non par
# env_var.sh, qui exige .python-odoo-version. Se lance depuis la racine du
# dépôt.

CONF_VENV="conf/python-erplibre-venv"
CONF_PYTHON_VERSION="conf/python-erplibre-version"

for conf_file in "${CONF_VENV}" "${CONF_PYTHON_VERSION}"; do
  if [[ ! -f "${conf_file}" ]]; then
    echo "Configuration introuvable : ${conf_file}"
    echo "  Ce script se lance depuis la racine du depot :"
    echo "    cd <racine du depot> && ./script/install/install_erplibre.sh"
    exit 1
  fi
done

# « xargs » retire espaces et retour de ligne autour de la valeur.
VENV_ERPLIBRE_PATH=$(xargs < "${CONF_VENV}")
PYTHON_ERPLIBRE_VERSION=$(xargs < "${CONF_PYTHON_VERSION}")

echo -e "Install ${VENV_ERPLIBRE_PATH} with ${PYTHON_ERPLIBRE_VERSION}"
if ! ./script/install/install_venv.sh \
  "ERPLibre" "${VENV_ERPLIBRE_PATH}" "${PYTHON_ERPLIBRE_VERSION}"; then
  echo "Echec de creation de ${VENV_ERPLIBRE_PATH}, arret."
  exit 1
fi

# Un venv rebâti n'a plus bin/repo ; install_git_repo.sh ne le pose que s'il
# manque. TODO s'en passe : seules les synchronisations de dépôts l'exigent,
# donc un échec (hors ligne) est signalé sans arrêter l'installation.
if ! ./script/install/install_git_repo.sh; then
  echo "git-repo n'est pas pose dans ${VENV_ERPLIBRE_PATH} : 'repo sync' en a besoin."
  echo "  Rejouez quand le reseau le permet : ./script/install/install_git_repo.sh"
fi

# el_pip_install vise le venv par son chemin : aucune activation n'est requise.
# shellcheck source=script/install/lib_pip_provider.sh
. ./script/install/lib_pip_provider.sh
if ! el_pip_install "${VENV_ERPLIBRE_PATH}" \
  -r requirement/erplibre_require-ments.txt; then
  echo "Echec d'installation des dependances Python dans ${VENV_ERPLIBRE_PATH}."
  echo "  Relancez : ./script/install/install_erplibre.sh"
  exit 1
fi

# Prettier ne sert qu'au formatage XML (« make format ») : son échec est
# signalé sans faire échouer une installation Python complète.
if ! npm install; then
  echo "npm install a echoue : prettier et son greffon XML ne sont pas poses."
  echo "  ${VENV_ERPLIBRE_PATH} est utilisable ; seul 'make format' les reclame."
  echo "  Rejouez quand le reseau le permet : npm install"
fi
exit 0
