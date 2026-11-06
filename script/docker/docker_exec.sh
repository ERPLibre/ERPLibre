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

source "$(dirname "$0")/lib_conteneur.sh"
conteneur=$(conteneur_erplibre)

exec docker exec --privileged -u root -ti "${conteneur}" bash
