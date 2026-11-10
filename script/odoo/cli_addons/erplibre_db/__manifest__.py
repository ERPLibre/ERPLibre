# -*- coding: utf-8 -*-
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
{
    "name": "ERPLibre db command",
    "summary": "odoo-bin erplibre_db, erplibre_uninstall, erplibre_shell for upstream Odoo",
    "version": "1.0.0",
    "category": "Tools",
    "author": "TechnoLibre",
    "website": "https://github.com/ERPLibre/ERPLibre",
    "license": "AGPL-3",
    "depends": [],
    # Rien à installer : seul son dossier cli/ sert, découvert par le lanceur
    # quand ce dossier est dans --addons-path. Odoo 8 et 9 ne lisent que
    # __openerp__.py, un lien vers ce fichier.
    "installable": False,
}
