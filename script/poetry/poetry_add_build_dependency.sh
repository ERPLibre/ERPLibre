#!/usr/bin/env bash
Red='\033[0;31m'         # Red
Color_Off='\033[0m'      # Text Reset

VENV="./.venv.$(cat ".erplibre-version" | xargs)"
BUILD="${VENV}/build_dependency.txt"

# Chaque ligne devient UN argument, jamais plusieurs.
#
# L'expansion « $(...) » non quotée découpait sur les espaces : une ligne
# portant un marqueur — « factur-x>=4.2 ; platform_machine != "s390x" » —
# arrivait à poetry en cinq arguments. D'où le « grep -v ';' » historique, qui
# écartait purement et simplement ces lignes : la dépendance n'était jamais
# ajoutée. Or « poetry add » sait lire une chaîne PEP 508 complète, marqueur
# compris — vérifié avec son propre parseur.
#
# On garde le filtre sur « * » : une contrainte joker n'apporte rien à poetry.
mapfile -t DEPS < <(grep -v '\*' "${BUILD}" | grep -v '^[[:space:]]*$')

if [[ ${#DEPS[@]} -eq 0 ]]; then
    echo "Aucune dépendance à ajouter depuis ${BUILD}."
    exit 0
fi

"${VENV}/bin/poetry" add -vv "${DEPS[@]}"
retVal=$?
if [[ $retVal -ne 0 ]]; then
    echo -e "${Red}Error${Color_Off} ./script/poetry/poetry_add_build_dependency.sh"
    exit 1
fi
