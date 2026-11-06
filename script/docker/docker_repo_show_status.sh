#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Affiche l'état git des dépôts du conteneur ERPLibre.

set -euo pipefail

source "$(dirname "$0")/lib_conteneur.sh"
conteneur=$(conteneur_erplibre)

exec docker exec -u root -ti "${conteneur}" /bin/bash -c "\
cd /ERPLibre; \
.venv.erplibre/bin/repo forall -pc 'git status -s'; \
echo ''; \
git status -s; \
"
