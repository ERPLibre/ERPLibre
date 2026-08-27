#!/usr/bin/env bash
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Quel fichier de configuration Odoo doit lire, quand personne ne le dit.
#
# Sans cela, Odoo retombe sur ~/.odoorc — un fichier PERSONNEL, hors du
# dépôt, que rien ne synchronise avec `config.conf`. Mesuré : un ~/.odoorc
# portant un mot de passe maître haché faisait échouer
# « odoo_bin.sh db --drop » par AccessDenied, alors que db_restore.py
# venait de lire `admin_passwd = admin` dans config.conf et d'en conclure
# qu'aucun mot de passe n'était nécessaire. Les deux avaient raison : ils
# ne parlaient pas du même fichier.
#
# La précédence d'Odoo est la même en 12 et en 18 (tools/config.py) :
#
#     self.config_file or opt.config or ODOO_RC or OPENERP_SERVER or ~/.odoorc
#
# Poser ODOO_RC ne retire donc rien à personne : un « -c » explicite
# l'emporte toujours, et un ODOO_RC déjà posé n'est pas écrasé.
#
# L'ordre des candidats est celui de db_restore.py, pour que la
# vérification qu'il fait porte sur le fichier qu'Odoo lira vraiment.

odoo_rc_resolve() {
    if [[ -n "${ODOO_RC:-}" ]]; then
        return 0
    fi
    local racine="${1:-$(pwd)}"
    local candidat
    for candidat in "${racine}/config.conf" /etc/odoo/odoo.conf; do
        if [[ -f "${candidat}" ]]; then
            export ODOO_RC="${candidat}"
            return 0
        fi
    done
    return 0
}
