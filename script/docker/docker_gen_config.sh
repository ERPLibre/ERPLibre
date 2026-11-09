#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Régénère les addons_path de /etc/odoo/odoo.conf dans le conteneur ERPLibre,
# pour la version d'Odoo du checkout courant (.odoo-version).
#
# La commande tourne sous le propriétaire de /ERPLibre (proprietaire_code
# de lib_conteneur.sh), jamais sous root : elle exécute du code que ce compte
# peut réécrire. odoo.conf appartient à ce compte, qui le réécrit en place
# sans avoir à créer de fichier dans /etc/odoo.

set -euo pipefail

source "$(dirname "$0")/lib_conteneur.sh"
conteneur=$(conteneur_erplibre)
proprietaire=$(proprietaire_code "${conteneur}")

version=$(xargs <.odoo-version)
exec docker exec -u "${proprietaire}" -ti "${conteneur}" /bin/bash -c "\
cd /ERPLibre; \
./docker/repo_manifest_gen_org_prefix_path.py /ERPLibre/odoo${version}/addons /etc/odoo/odoo.conf /etc/odoo/odoo.conf; \
"
