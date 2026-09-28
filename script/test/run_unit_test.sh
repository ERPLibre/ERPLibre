#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Tests unitaires python du dépôt : ni base de données, ni Odoo, ni VM.
#
# Ils lisent le code et exécutent les fragments de shell que todo.py génère,
# avec « sudo », « pgrep » et « pkill » bouchonnés — c'est ce qui les rend
# lançables partout, là où « make test » demande une base et plusieurs
# minutes.
#
# DÉPENDANCE DÉCLARÉE : les tests du transfert mobile lisent
# mobile/erplibre_home_mobile. Absent, ils se disent ignorés plutôt que de
# passer en silence — un test vert sans son dépôt ne prouve rien. Ce script
# l'annonce donc avant de commencer.
#
#   ./script/test/run_unit_test.sh [fichiers...]
#   UNIT_JOBS=1 ./script/test/run_unit_test.sh      # en série
#   UNIT_TIMEOUT=600 UNIT_SIGNAL=30 ...             # délai, rappel (s)
#
# L'exécution — parallèle, isolée de l'hôte, bornée dans le temps — est
# dans run_unit_test.py, qui en décrit les garanties.
#
# TOUT test/test_*.py, et non une liste de préfixes : une liste oublie les
# familles qu'elle ne nomme pas, un glob n'oublie personne. La frontière de
# la suite est donc un RÉPERTOIRE, pas un nom : ce qui doit rester hors de la
# suite vit ailleurs que dans test/.
#
# Un fichier n'est vu que s'il finit par le bloc habituel, EN DERNIER — tout
# ce qui suit l'appel est défini trop tard et ne tourne jamais :
#
#     if __name__ == "__main__":
#         unittest.main()
set -uo pipefail

Red='\033[0;31m'
Green='\033[0;32m'
Yellow='\033[0;33m'
Color_Off='\033[0m'

cd "$(dirname "$0")/../.." || exit 1

PY=./.venv.erplibre/bin/python
if [[ ! -x "${PY}" ]]; then
    echo -e "${Red}✗ ${PY} absent : lancer l'installation ERPLibre d'abord.${Color_Off}"
    exit 1
fi

MOBILE=mobile/erplibre_home_mobile
if [[ -d "${MOBILE}" ]]; then
    echo -e "  dépendance ${MOBILE} : ${Green}présente${Color_Off}"
else
    echo -e "  dépendance ${MOBILE} : ${Yellow}absente${Color_Off}"
    echo "    (les tests du transfert mobile s'en passeront et le diront)"
fi

OPTIONS=()
FILES=()
for arg in "$@"; do
    case "${arg}" in
        --*) OPTIONS+=("${arg}") ;;
        *) FILES+=("${arg}") ;;
    esac
done
if [[ ${#FILES[@]} -eq 0 ]]; then
    # Aucun fichier : tout le répertoire.
    mapfile -t FILES < <(ls test/test_*.py 2>/dev/null)
fi

exec "${PY}" script/test/run_unit_test.py "${OPTIONS[@]}" "${FILES[@]}"
