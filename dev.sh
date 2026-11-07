#!/usr/bin/env bash
# Usage, ./dev.sh -d ma_base
#
# run.sh en mode développement : HTTP actif et workers de config.conf,
# contrairement à test.sh qui coupe HTTP et force --workers 0. Seules les
# limites de temps et de mémoire sont levées, pour qu'une requête suspendue
# sur un point d'arrêt ne soit pas tuée ; run.sh, en production, laisse
# ces limites à config.conf.

ODOO_MODE_DEV="true" ./run.sh "$@"
