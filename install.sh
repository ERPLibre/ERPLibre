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
# La version est lue par du code exécuté, et non par « -V » : celui-ci répond
# avant le chargement de la bibliothèque standard, si bien qu'un interpréteur
# qui ne la trouve pas rend sa version puis meurt au premier vrai lancement.
# Rien n'est rendu quand la sortie n'a pas la forme X.Y : un interpréteur en
# panne écrit son diagnostic, et le premier mot venu passerait sinon pour un
# numéro de version que « sort -V » jugerait assez récent.
el_mineure() {
  "$1" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2> /dev/null \
    | awk '/^[0-9]+\.[0-9]+$/ { print; exit }'
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

# Un venv dont l'interpréteur ne rend pas sa version ne démarrera pas
# davantage TODO : c'est le cas d'un checkout monté depuis une autre machine,
# dont le venv cherche sa bibliothèque standard là où elle n'est pas. Le dire,
# et couper la relance de todo.py, qui sinon se remplacerait par ce python mort
# et rendrait son pavé d'initialisation au lieu d'un message.
if [ -x "${PYTHON_VENV}" ] && [ -z "$(el_mineure "${PYTHON_VENV}")" ]; then
  echo "${PYTHON_VENV} ne demarre pas : ce venv a ete bati ailleurs."
  echo "  Rebatissez-le ici : ./script/install/install_erplibre.sh"
  export EL_TODO_VENV_RELAUNCHED=1
fi

if command -v python3 > /dev/null 2>&1 \
  && el_assez_recent "$(el_mineure python3)"; then
  exec ./script/todo/todo.py "$@"
fi

echo "Python ${VOULUE:-du depot} est requis pour lire le code de TODO ;"
echo "  ce systeme livre $(el_mineure python3 2> /dev/null || echo 'aucun python3')."
echo "  Installation du venv d'outillage, qui le pose :"
exec ./script/todo/source_todo.sh "$@"
