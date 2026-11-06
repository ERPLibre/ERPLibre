#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Affiche à l'écran le /etc/odoo/odoo.conf du conteneur ERPLibre, lu dans le
# volume erplibre_conf du projet docker compose de ce dépôt. Le projet n'a pas
# à tourner, ni son conteneur à exister : seul le volume est lu.
#
# Un conteneur jetable de l'image du service ERPLibre monte le volume en
# lecture seule et fait le cat, sans réseau, avec la seule capacité
# DAC_READ_SEARCH, qui lit le fichier quel qu'en soit le propriétaire. L'image
# doit déjà être sur l'hôte : rien ne se télécharge.
#
# Le fichier porte admin_passwd et le mot de passe PostgreSQL : il passe sur
# la sortie standard et n'est écrit nulle part.
#
# Un compte sans accès à la socket docker, hors du groupe docker, passe par
# sudo, qui demande son mot de passe.

set -euo pipefail

cd "$(dirname "$0")/../.."

docker=(docker)
if ! docker info >/dev/null 2>&1 && command -v sudo >/dev/null; then
  echo "The docker socket refuses this account: going through sudo." >&2
  docker=(sudo docker)
fi

# Le nom du projet et l'image du service ERPLibre, selon docker compose ;
# à défaut, le nom que compose dérive du répertoire, et une image ERPLibre
# présente sur l'hôte.
projet=""
image=""
if config=$("${docker[@]}" compose config --format json 2>/dev/null); then
  {
    read -r projet
    read -r image
  } < <(python3 -c '
import json, sys
c = json.load(sys.stdin)
print(c.get("name", ""))
print(c.get("services", {}).get("ERPLibre", {}).get("image", ""))
' <<<"${config}") || true
fi
if [ -z "${projet}" ]; then
  projet=$(basename "$(pwd)")
  projet="${projet//./}"
  projet="${projet,,}"
fi
if [ -z "${image}" ]; then
  image=$("${docker[@]}" images --format '{{.Repository}}:{{.Tag}}' |
    grep -m1 '^technolibre/erplibre:' || true)
fi

# Un refus ici n'arrête rien : le nom dérivé prend le relais, et l'inspect
# qui suit nomme le volume introuvable.
volume=$("${docker[@]}" volume ls -q \
  --filter "label=com.docker.compose.project=${projet}" \
  --filter "label=com.docker.compose.volume=erplibre_conf" | head -n1) || true
volume="${volume:-${projet}_erplibre_conf}"

if ! "${docker[@]}" volume inspect "${volume}" >/dev/null 2>&1; then
  echo "No volume ${volume}: the docker compose project ${projet} never started here." >&2
  exit 1
fi
if [ -z "${image}" ] || ! "${docker[@]}" image inspect "${image}" >/dev/null 2>&1; then
  echo "The ERPLibre image ${image:-(none)} is not on this host: nothing is downloaded." >&2
  exit 1
fi

exec "${docker[@]}" run --rm --pull never --network none \
  -u root --cap-drop ALL --cap-add DAC_READ_SEARCH \
  --security-opt no-new-privileges:true \
  -v "${volume}:/conf:ro" --entrypoint cat "${image}" /conf/odoo.conf
