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
#
# PARALLÈLE. Chaque fichier tourne dans son propre processus, UNIT_JOBS à la
# fois (par défaut un par cœur) : la durée totale devient celle du fichier le
# plus long plutôt que la somme de tous. Une ligne s'affiche quand un fichier
# FINIT, donc dans le désordre ; les sorties des échecs suivent, dans l'ordre
# des noms.
#
# Les plus LONGS partent en premier, d'après les durées du passage précédent
# gardées hors du dépôt (DURATIONS). Lancé en dernier, un fichier long
# allonge la suite de toute l'attente qui a précédé son départ ; lancé en
# premier, il tourne pendant que les courts se partagent les autres cœurs.
# Un fichier sans durée connue passe devant : on ignore s'il est court.
#
# HERMÉTIQUE. Un test unitaire ne touche pas l'hôte :
#  - l'entrée standard est /dev/null. Un input() oublié par un test échoue
#    sur EOFError au lieu d'attendre une réponse que personne ne donnera, et
#    le code qui demande « sys.stdin.isatty() » voit la même chose sur tous
#    les postes ;
#  - sudo, pkexec, doas, virsh et ssh sont remplacés, en tête du PATH, par
#    une commande qui refuse. Sans cela, un appel non bouchonné interroge les
#    VM réelles du poste, ou demande un mot de passe là où libvirt n'est
#    joignable qu'en root. Le refus rend le résultat identique d'un poste à
#    l'autre : un test qui en dépend échoue partout, pas seulement ailleurs ;
#  - UNIT_TIMEOUT secondes par fichier (300 par défaut) : un fichier qui
#    attend quelque chose échoue en le disant, sans bloquer la suite.
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
    # Aucun argument : tout le répertoire.
    mapfile -t FILES < <(ls test/test_*.py 2>/dev/null)
fi

JOBS=${UNIT_JOBS:-$(nproc 2>/dev/null || echo 4)}
TIMEOUT=${UNIT_TIMEOUT:-300}
DURATIONS=${XDG_CACHE_HOME:-${HOME}/.cache}/erplibre/run_unit_test.durations

WORK=$(mktemp -d)
trap 'rm -rf "${WORK}"' EXIT

# L'ordre de lancement : durée connue décroissante, inconnue d'abord. Une
# ligne « secondes nom » par fichier dans DURATIONS.
mapfile -t ORDER < <(
    for f in "${FILES[@]}"; do
        d=$(awk -v n="$(basename "${f}")" '$2 == n {print $1}' \
            "${DURATIONS}" 2>/dev/null)
        echo "${d:-999999} ${f}"
    done | sort -rn | cut -d' ' -f2-
)

# Les commandes refusées : chacune écrit pourquoi, sur la sortie d'erreur du
# test qui l'a appelée, et rend le code d'échec que son appelant attend
# d'elle (255 pour ssh, 1 pour les autres).
mkdir -p "${WORK}/bin" "${WORK}/out"
for cmd in sudo pkexec doas virsh ssh; do
    code=1
    [[ ${cmd} == ssh ]] && code=255
    cat >"${WORK}/bin/${cmd}" <<EOF
#!/bin/sh
echo "run_unit_test : « ${cmd} \$* » refusé, un test unitaire ne touche pas l'hôte" >&2
exit ${code}
EOF
    chmod +x "${WORK}/bin/${cmd}"
done

# Un fichier : sa sortie dans out/<nom>.log, son verdict dans out/<nom>.rc,
# puis sa ligne de résumé. Lancée par xargs, d'où l'export.
run_one() {
    local f=$1 name out rc ran skipped state debut
    name=$(basename "${f}")
    out="${WORK}/out/${name}"
    debut=${SECONDS}
    PATH="${WORK}/bin:${PATH}" PYTHONPATH=. \
        timeout "${TIMEOUT}" "${PY}" "${f}" </dev/null >"${out}.log" 2>&1
    rc=$?
    echo "$((SECONDS - debut)) ${name}" >"${out}.duree"
    ran=$(grep -oE 'Ran [0-9]+' "${out}.log" | grep -oE '[0-9]+' | tail -1)
    skipped=$(grep -oE 'skipped=[0-9]+' "${out}.log" | tail -1)
    if [[ ${rc} -eq 124 ]]; then
        state="${Red}DÉLAI ${TIMEOUT}s${Color_Off}"
    elif [[ ${rc} -eq 0 ]] && grep -qE '^OK' "${out}.log"; then
        state="${Green}OK${Color_Off}"
    else
        state="${Red}ÉCHEC${Color_Off}"
    fi
    echo "${rc} ${ran:-0}" >"${out}.rc"
    printf "  %-42s %5s tests %-14s %b\n" \
        "${name}" "${ran:-?}" "${skipped:-}" "${state}"
}
export -f run_one
export WORK PY TIMEOUT Red Green Color_Off

start=${SECONDS}
printf '%s\0' "${ORDER[@]}" |
    xargs -0 -P "${JOBS}" -I{} bash -c 'run_one "$1"' _ {}

# Les durées de ce passage remplacent celles des mêmes fichiers ; celles des
# fichiers qui n'ont pas tourné cette fois restent.
mkdir -p "$(dirname "${DURATIONS}")"
{
    cat "${WORK}"/out/*.duree 2>/dev/null
    # Absent au premier passage : sous pipefail, son échec annulerait
    # l'écriture du fichier même qu'il attend.
    cat "${DURATIONS}" 2>/dev/null || true
} | awk '!vu[$2]++' >"${WORK}/durations" &&
    mv "${WORK}/durations" "${DURATIONS}"

fail=0
total=0
for f in "${FILES[@]}"; do
    name=$(basename "${f}")
    read -r rc ran <"${WORK}/out/${name}.rc" 2>/dev/null || rc=1 ran=0
    total=$((total + ran))
    if [[ ${rc} -ne 0 ]] || ! grep -qE '^OK' "${WORK}/out/${name}.log"; then
        fail=1
        echo -e "\n  ${Red}── ${name}${Color_Off}"
        tail -12 "${WORK}/out/${name}.log"
    fi
done

echo "  ─────"
duree="$((SECONDS - start)) s, ${JOBS} en parallèle"
if [[ ${fail} -eq 0 ]]; then
    echo -e "  ${Green}${total} tests, tout vert${Color_Off} (${duree})"
else
    echo -e "  ${Red}des échecs ci-dessus${Color_Off} (${duree})"
fi
exit ${fail}
