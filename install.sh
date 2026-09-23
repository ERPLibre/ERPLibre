#!/usr/bin/env bash
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Point d'entrée de TODO : choisir un interpréteur capable de LIRE le code
# avant de le lui donner.
#
# todo.py porte le hashbang « python3 », donc le Python du système. Celui-ci
# est libre d'être plus vieux que conf/python-erplibre-version, qui est la
# seule version que le dépôt vise : une syntaxe qu'il ne connaît pas l'arrête
# en SyntaxError au chargement, AVANT le garde de todo.py qui aurait su nommer
# le geste. Un système hors d'âge n'a alors plus aucun moyen de lancer
# l'installation qui le tirerait de là.
#
# D'où l'ordre : le venv d'outillage, qui porte la bonne version ; sinon le
# Python du système s'il est assez récent pour lire le code, et le garde de
# todo.py prend le relais ; sinon l'installation, seule issue.

cd "$(dirname "$0")" || exit 1

VENV="$(xargs < conf/python-erplibre-venv 2> /dev/null)"
VOULUE="$(xargs < conf/python-erplibre-version 2> /dev/null)"
ATTENDUE="${VOULUE%.*}"

# Majeure.mineure de l'exécutable : elle seule décide de la grammaire acceptée.
el_mineure() {
  "$1" -V 2>&1 | awk '{split($2, v, "."); print v[1] "." v[2]}'
}

# Vrai si la version lue atteint au moins celle attendue, comparée en version
# et non en chaîne : « 3.9 » est une chaîne plus grande que « 3.14 ».
el_assez_recent() {
  [ -n "$1" ] && [ -n "${ATTENDUE}" ] \
    && [ "$(printf '%s\n%s\n' "${ATTENDUE}" "$1" | sort -V | head -1)" \
      = "${ATTENDUE}" ]
}

PYTHON_VENV="./${VENV}/bin/python"
if [ -n "${VENV}" ] && [ -x "${PYTHON_VENV}" ] \
  && el_assez_recent "$(el_mineure "${PYTHON_VENV}")"; then
  exec "${PYTHON_VENV}" ./script/todo/todo.py "$@"
fi

if command -v python3 > /dev/null 2>&1 \
  && el_assez_recent "$(el_mineure python3)"; then
  exec ./script/todo/todo.py "$@"
fi

echo "Python ${VOULUE:-du depot} est requis pour lire le code de TODO ;"
echo "  ce systeme livre $(el_mineure python3 2> /dev/null || echo 'aucun python3')."
echo "  Installation du venv d'outillage, qui le pose :"
exec ./script/todo/source_todo.sh "$@"
