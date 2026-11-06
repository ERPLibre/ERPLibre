#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Lance « make test » dans le conteneur ERPLibre ; son code de sortie est
# celui des tests.

set -euo pipefail

source "$(dirname "$0")/lib_conteneur.sh"
conteneur=$(conteneur_erplibre)

exec docker exec -u root -ti "${conteneur}" /bin/bash -c "\
cd /ERPLibre; \
time make test; \
"
