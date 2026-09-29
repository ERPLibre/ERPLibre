#!/usr/bin/env bash
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Quel fichier de configuration Odoo doit lire, quand personne ne le dit.
#
# Sans cela, Odoo retombe sur ~/.odoorc — un fichier PERSONNEL, hors du
# dépôt, que rien ne synchronise avec `config.conf`. Un ~/.odoorc qui porte
# un mot de passe maître haché fait échouer « odoo_bin.sh db --drop » par
# AccessDenied, alors que db_restore.py lit `admin_passwd = admin` dans
# config.conf et en conclut qu'aucun mot de passe n'est nécessaire : les
# deux ne parlent pas du même fichier.
#
# La précédence d'Odoo est la même en 12 et en 18 (tools/config.py) :
#
#     self.config_file or opt.config or ODOO_RC or OPENERP_SERVER or ~/.odoorc
#
# Poser ODOO_RC ne retire donc rien à personne : un « -c » explicite
# l'emporte toujours, et un ODOO_RC déjà posé n'est pas écrasé.
#
# Odoo 8 et 9 ne lisent pas ODOO_RC : seulement OPENERP_SERVER, puis
# ~/.openerp_serverrc. OPENERP_SERVER désigne alors le même fichier, et
# n'est posé que pour eux : Odoo 19 le signale comme obsolète, pile
# d'appels comprise, à chaque démarrage.
#
# L'ordre des candidats est celui de db_restore.py, pour que la
# vérification qu'il fait porte sur le fichier qu'Odoo lira vraiment.

# el_odoo_rc_openerp <racine> : l'Odoo actif de ce checkout nomme-t-il
# encore son paquet « openerp » (Odoo 8 et 9) ?
el_odoo_rc_openerp() {
    local version
    version="$(cat "$1/.odoo-version" 2> /dev/null)"
    [[ -n "${version}" && -d "$1/odoo${version}/odoo/openerp" ]]
}

odoo_rc_resolve() {
    local racine="${1:-$(pwd)}"
    local candidat
    if [[ -z "${ODOO_RC:-}" ]]; then
        for candidat in "${racine}/config.conf" /etc/odoo/odoo.conf; do
            if [[ -f "${candidat}" ]]; then
                export ODOO_RC="${candidat}"
                break
            fi
        done
    fi
    if [[ -n "${ODOO_RC:-}" ]] && el_odoo_rc_openerp "${racine}"; then
        export OPENERP_SERVER="${OPENERP_SERVER:-${ODOO_RC}}"
    fi
    return 0
}
