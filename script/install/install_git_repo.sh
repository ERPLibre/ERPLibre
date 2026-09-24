#!/usr/bin/env bash

# Se lance depuis la racine du dépôt : ailleurs, le chemin de venv serait vide
# et la cible deviendrait « /bin/repo ».
CONF_VENV="conf/python-erplibre-venv"
if [[ ! -f "${CONF_VENV}" ]]; then
    echo "Configuration introuvable : ${CONF_VENV}"
    echo "  cd <racine du depot> && ./script/install/install_git_repo.sh"
    exit 1
fi
VENV_ERPLIBRE_PATH=$(xargs < "${CONF_VENV}")

VENV_REPO_PATH=${VENV_ERPLIBRE_PATH}/bin/repo
# Install git-repo if missing
if [[ ! -f ${VENV_REPO_PATH} ]]; then
    if [[ ! -d "${VENV_ERPLIBRE_PATH}/bin" ]]; then
        echo "Venv ${VENV_ERPLIBRE_PATH} absent : posez-le avant git-repo."
        echo "  ./script/install/install_erplibre.sh"
        exit 1
    fi
    echo -e "\n---- Install git-repo from Google APIS ----"
    # Téléchargé à côté, contrôlé, puis déplacé : sans « -f », curl écrit la
    # page d'une erreur HTTP et rend 0 ; un corps vide passe le statut.
    REPO_TMP="$(mktemp)" || exit 1
    if ! curl -fsSL -o "${REPO_TMP}" \
      https://storage.googleapis.com/git-repo-downloads/repo \
      || [[ ! -s "${REPO_TMP}" ]]; then
        echo "Telechargement de git-repo impossible ou vide (reseau ou cache) :"
        echo "  ${VENV_REPO_PATH} n'est pas pose."
        rm -f "${REPO_TMP}"
        exit 1
    fi
    # Le hashbang du venv remplace celui du python3 du système.
    sed -i 1d "${REPO_TMP}"
    PYTHON_HASHBANG="#!./${VENV_ERPLIBRE_PATH}/bin/python"
    sed -i "1 i ${PYTHON_HASHBANG}" "${REPO_TMP}"
    if ! mv "${REPO_TMP}" "${VENV_REPO_PATH}"; then
        echo "Mise en place de ${VENV_REPO_PATH} impossible."
        rm -f "${REPO_TMP}"
        exit 1
    fi
    # mktemp crée en 0600.
    chmod 755 "${VENV_REPO_PATH}"
fi
