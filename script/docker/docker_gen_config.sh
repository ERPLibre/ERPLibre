#!/usr/bin/env bash

CURRENT=$(pwd)
BASENAME=$(basename "${CURRENT}")

docker exec -u root -ti ${BASENAME}_ERPLibre_1 /bin/bash -c "\
cd /ERPLibre; \
./docker/repo_manifest_gen_org_prefix_path.py /ERPLibre/addons /etc/odoo/odoo.conf /etc/odoo/odoo.conf; \
"
