#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Fonctions communes aux scripts de script/docker/, à sourcer :
#   source "$(dirname "$0")/lib_conteneur.sh"

# conteneur_erplibre : écrit le nom du conteneur ERPLibre du projet docker
# compose du répertoire courant, celui qui existe des deux noms possibles ;
# sinon, les nomme sur la sortie d'erreur et rend 1.
#
# Le projet porte le nom du répertoire, sans point et en minuscules, comme
# le dérive compose. compose v2 en sépare les parties par « - », la v1 par
# « _ ». Le nom se choisit avant toute commande : un appelant qui lançait la
# commande vers l'un puis, sur un code non nul, vers l'autre la relançait
# aussi quand c'était ELLE qui échouait, un test rouge par exemple.
conteneur_erplibre() {
  local base candidat
  base=$(basename "$(pwd)")
  base="${base//./}"
  base="${base,,}"
  for candidat in "${base}-ERPLibre-1" "${base}_ERPLibre_1"; do
    if docker inspect "${candidat}" >/dev/null 2>&1; then
      echo "${candidat}"
      return 0
    fi
  done
  echo "No ERPLibre container: neither ${base}-ERPLibre-1 nor" \
    "${base}_ERPLibre_1. Run this from the docker compose directory." >&2
  return 1
}
