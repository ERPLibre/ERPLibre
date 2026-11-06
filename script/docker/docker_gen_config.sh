#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Régénère les addons_path de /etc/odoo/odoo.conf dans le conteneur ERPLibre,
# pour la version d'Odoo du checkout courant (.odoo-version).

set -euo pipefail

source "$(dirname "$0")/lib_conteneur.sh"
conteneur=$(conteneur_erplibre)

version=$(xargs <.odoo-version)
exec docker exec -u root -ti "${conteneur}" /bin/bash -c "\
cd /ERPLibre; \
./docker/repo_manifest_gen_org_prefix_path.py /ERPLibre/odoo${version}/addons /etc/odoo/odoo.conf /etc/odoo/odoo.conf; \
"
