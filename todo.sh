#!/usr/bin/env bash
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Lancer TODO.
#
# Le travail est dans install.sh, qui choisit un interpréteur capable de LIRE
# le code avant de le lui donner. Ce fichier n'ajoute qu'un NOM, et c'est sa
# seule raison d'être : make affiche la recette qu'il exécute, et « ./install.sh »
# y donnait à lire une installation là où l'on ouvre un menu. Deux gestes
# distincts méritent deux noms, même quand ils mènent au même endroit.
#
# Les arguments passent tels quels : « ./todo.sh --help » vaut « ./install.sh
# --help ».

cd "$(dirname "$0")" || exit 1

exec ./install.sh "$@"
