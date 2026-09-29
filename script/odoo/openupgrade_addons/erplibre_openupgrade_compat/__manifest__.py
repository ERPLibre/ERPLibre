# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
{
    "name": "ERPLibre OpenUpgrade compatibility",
    "summary": "Fixes applied to openupgradelib while OpenUpgrade runs",
    "version": "1.0.0",
    "category": "Hidden",
    "author": "TechnoLibre",
    "website": "https://github.com/ERPLibre/ERPLibre",
    "license": "AGPL-3",
    "depends": [],
    # Chargé par --load pendant une montée OpenUpgrade, jamais installé :
    # le code de __init__.py agit à l'import.
    "installable": False,
}
