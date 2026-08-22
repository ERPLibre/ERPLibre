#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Tests unitaires python du dépôt : ni base de données, ni Odoo, ni VM.
#
# Ils lisent le code et exécutent les fragments de shell que todo.py génère,
# avec « sudo », « pgrep » et « pkill » bouchonnés — c'est ce qui les rend
# lançables partout et en quelques secondes, là où « make test » demande une
# base et plusieurs minutes.
#
# DÉPENDANCE DÉCLARÉE : les tests du transfert mobile lisent
# mobile/erplibre_home_mobile. Absent, ils se disent ignorés plutôt que de
# passer en silence — un test vert sans son dépôt ne prouve rien. Ce script
# l'annonce donc avant de commencer.
#
#   ./script/test/run_unit_test.sh [fichiers...]
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

FILES=("$@")
if [[ ${#FILES[@]} -eq 0 ]]; then
    # Aucun argument : tout ce que le dépôt sait tester sans base de données.
    mapfile -t FILES < <(ls test/test_qemu_*.py test/test_mobile_*.py \
        test/test_todo_*.py test/test_install_*.py 2>/dev/null)
fi

fail=0
total=0
for f in "${FILES[@]}"; do
    out=$(PYTHONPATH=. "${PY}" "${f}" 2>&1)
    ran=$(echo "${out}" | grep -oE 'Ran [0-9]+' | grep -oE '[0-9]+' | tail -1)
    skipped=$(echo "${out}" | grep -oE 'skipped=[0-9]+' | tail -1)
    if echo "${out}" | grep -qE '^OK'; then
        state="${Green}OK${Color_Off}"
    else
        state="${Red}ÉCHEC${Color_Off}"
        fail=1
    fi
    total=$((total + ${ran:-0}))
    printf "  %-42s %5s tests %-14s %b\n" \
        "$(basename "${f}")" "${ran:-?}" "${skipped:-}" "${state}"
    [[ "${state}" == *"ÉCHEC"* ]] && echo "${out}" | tail -12
done

echo "  ─────"
if [[ ${fail} -eq 0 ]]; then
    echo -e "  ${Green}${total} tests, tout vert${Color_Off}"
else
    echo -e "  ${Red}des échecs ci-dessus${Color_Off}"
fi
exit ${fail}
