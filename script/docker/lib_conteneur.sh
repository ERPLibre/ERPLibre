#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Fonctions communes aux scripts de script/docker/, à sourcer :
#   source "$(dirname "$0")/lib_conteneur.sh"

# projet_compose : écrit le nom du projet docker compose du répertoire
# courant. Le nom vient de « docker compose config », qui applique
# COMPOSE_PROJECT_NAME, le .env et la clé name: du fichier ; la commande lit
# les fichiers sans joindre le moteur. Quand compose ne répond pas, le nom se
# dérive du répertoire comme compose le fait : en minuscules, réduit aux
# caractères [a-z0-9_-], sans « _ » ni « - » en tête.
projet_compose() {
  local projet
  projet=$(docker compose config --format json 2>/dev/null |
    python3 -c 'import json, sys; print(json.load(sys.stdin)["name"])' \
      2>/dev/null) || projet=""
  if [ -z "${projet}" ]; then
    projet=$(basename "$(pwd)")
    projet="${projet,,}"
    projet="${projet//[^a-z0-9_-]/}"
    while [[ "${projet}" == [_-]* ]]; do
      projet="${projet:1}"
    done
  fi
  echo "${projet}"
}

# conteneur_erplibre : écrit le nom du conteneur ERPLibre EN MARCHE du projet
# docker compose du répertoire courant et rend 0 ; sinon, explique pourquoi
# sur la sortie d'erreur et rend 1, sans rien écrire sur la sortie standard.
#
# Deux noms sont possibles, compose v2 séparant les parties par « - » et la
# v1 par « _ » ; le premier en marche est retenu. Seul un objet de type
# conteneur compte, et seulement s'il tourne : un conteneur arrêté se signale
# comme tel, avec la commande qui le démarre.
#
# Le moteur est interrogé d'abord, et son erreur passe telle quelle : un
# démon arrêté ou un DOCKER_HOST faux ne se confond pas avec un conteneur
# absent. Le nom se choisit avant toute commande dans le conteneur, de sorte
# qu'une commande en échec n'est jamais relancée vers l'autre nom.
conteneur_erplibre() {
  local erreur projet candidat etat
  local arretes=()
  if ! erreur=$(docker version --format '{{.Server.Version}}' 2>&1 >/dev/null); then
    echo "The docker engine does not answer: ${erreur:-no error message}" >&2
    return 1
  fi
  projet=$(projet_compose)
  for candidat in "${projet}-ERPLibre-1" "${projet}_ERPLibre_1"; do
    etat=$(docker inspect --type container -f '{{.State.Running}}' \
      "${candidat}" 2>/dev/null) || continue
    if [ "${etat}" = "true" ]; then
      echo "${candidat}"
      return 0
    fi
    arretes+=("${candidat}")
  done
  if [ ${#arretes[@]} -gt 0 ]; then
    echo "The ERPLibre container ${arretes[0]} is stopped: start it with" \
      "docker compose up -d from the docker compose directory." >&2
    return 1
  fi
  echo "No ERPLibre container: neither ${projet}-ERPLibre-1 nor" \
    "${projet}_ERPLibre_1. Run this from the docker compose directory," \
    "once docker compose up -d has started the project." >&2
  return 1
}

# proprietaire_code CONTENEUR : écrit l'uid du propriétaire de /ERPLibre dans
# CONTENEUR et rend 0 ; sinon, explique pourquoi sur la sortie d'erreur et
# rend 1. C'est le compte qui peut réécrire le code, le Makefile et les venvs :
# une commande qui en exécute s'y lance sous ce compte, jamais sous root,
# faute de quoi un Odoo compromis obtient root par elle. stat tourne sous
# l'uid 65534 : la recherche dans « / » suffit à lire le propriétaire de
# /ERPLibre, sans rien exécuter en root. La sortie n'est retenue que si elle
# est un entier.
proprietaire_code() {
  local uid
  uid=$(docker exec -u 65534:65534 "$1" stat -c %u /ERPLibre) || uid=""
  if [[ ! "${uid}" =~ ^[0-9]+$ ]]; then
    echo "Cannot read the owner of /ERPLibre in the container $1." >&2
    return 1
  fi
  echo "${uid}"
}
