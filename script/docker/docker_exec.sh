#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Ouvre un shell bash en root, privilégié, dans le conteneur ERPLibre du
# projet docker compose du répertoire courant.
#
# --privileged rend à ce shell les capacités que le compose retire
# (cap_drop: [ALL]) : sans CHOWN, DAC_OVERRIDE ni FOWNER, root ne peut pas
# installer un paquet Debian, apt échoue sur « rename failed, Permission
# denied ». Le privilège ne vaut que pour ce shell et ce qu'il lance ; Odoo
# garde les capacités du compose.

set -euo pipefail

CURRENT=$(pwd)
BASENAME=$(basename "${CURRENT}")
# Docker remove dot
BASENAME="${BASENAME//./}"
# Lowercase
BASENAME="${BASENAME,,}"

# docker compose v2 sépare les parties du nom par « - », la v1 par « _ ». Le
# nom se choisit avant l'exec : un shell quitté sur un code non nul ne relance
# pas un second shell vers l'autre nom.
conteneur="${BASENAME}-ERPLibre-1"
if ! docker inspect "${conteneur}" >/dev/null 2>&1; then
  conteneur="${BASENAME}_ERPLibre_1"
fi

exec docker exec --privileged -u root -ti "${conteneur}" bash
