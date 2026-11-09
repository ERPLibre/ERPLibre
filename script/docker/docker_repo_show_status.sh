#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Affiche l'état git des dépôts du conteneur ERPLibre.
#
# La commande tourne sous le propriétaire de /ERPLibre (proprietaire_code
# de lib_conteneur.sh), jamais sous root : elle exécute du code que ce compte
# peut réécrire.

set -euo pipefail

source "$(dirname "$0")/lib_conteneur.sh"
conteneur=$(conteneur_erplibre)
proprietaire=$(proprietaire_code "${conteneur}")

exec docker exec -u "${proprietaire}" -ti "${conteneur}" /bin/bash -c "\
cd /ERPLibre; \
.venv.erplibre/bin/repo forall -pc 'git status -s'; \
echo ''; \
git status -s; \
"
