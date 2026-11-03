#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Efface les volumes du projet docker compose de ce dépôt : les bases
# PostgreSQL, le filestore d'Odoo et sa configuration, sans retour possible.
#
# Deux confirmations, dans l'ordre : un « y », puis le nom du projet retapé.
# Recopier un nom oblige à regarder ce qu'on détruit, là où « y » se tape par
# réflexe. Toute autre réponse, ou une entrée fermée, arrête tout sans rien
# toucher.
#
# `docker compose down -v` retire les conteneurs du projet, ses volumes nommés
# et les volumes anonymes de ses conteneurs. Un volume qui porte encore le
# nom du projet sans figurer dans docker-compose.yml, laissé par une version
# précédente du fichier, est retiré ensuite par son nom.

set -euo pipefail

cd "$(dirname "$0")/../.."

if ! projet=$(docker compose config --format json 2>/dev/null |
  python3 -c 'import json, sys; print(json.load(sys.stdin)["name"])'); then
  echo "docker compose config is unreadable: run this from an ERPLibre checkout with docker-compose.yml."
  exit 1
fi

volumes=()
while IFS= read -r volume; do
  [ -n "${volume}" ] && volumes+=("${volume}")
done < <(docker volume ls -q --filter "label=com.docker.compose.project=${projet}")

if [ ${#volumes[@]} -eq 0 ]; then
  echo "No volume for the docker compose project ${projet}: nothing to delete."
  exit 0
fi

echo "The docker compose project ${projet} will be stopped, and these volumes deleted for good:"
for volume in "${volumes[@]}"; do
  echo "  - ${volume}"
done
echo "Every database, the Odoo filestore and its configuration go with them."

reponse=""
read -r -p "Delete them all? (y/N): " reponse || true
if [[ ! "${reponse}" =~ ^[yYoO]$ ]]; then
  echo "Cancelled: nothing was deleted."
  exit 1
fi

reponse=""
read -r -p "Type the project name ${projet} to confirm: " reponse || true
if [ "${reponse}" != "${projet}" ]; then
  echo "Cancelled: the name differs, nothing was deleted."
  exit 1
fi

docker compose down -v --remove-orphans

restants=()
while IFS= read -r volume; do
  [ -n "${volume}" ] && restants+=("${volume}")
done < <(docker volume ls -q --filter "label=com.docker.compose.project=${projet}")
if [ ${#restants[@]} -gt 0 ]; then
  docker volume rm "${restants[@]}"
fi

echo "Volumes of ${projet} deleted. docker compose up -d starts again on empty volumes."
