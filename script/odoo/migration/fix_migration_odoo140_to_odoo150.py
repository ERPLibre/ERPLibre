#!/usr/bin/env python3
# © 2021-2025 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

# This script need to be run when upgrade 14 to 15 when database is created from ERPLibre.
print("Running a script in the Odoo shell!")

i = 0
print(
    f"{i}. Remove project_type because OCA project_category migrating to OCA project_type and conflict with odoo14.0/addons/Numigi_odoo-project-addons"
)
# TODO do a migration, copy data to another temporary table
env["ir.module.module"].search([("name", "=", "project_type")]).unlink()
i += 1

# print(
#     f"{i}. Remove project_type because OCA project_category migrating to OCA project_type"
# )
# env["ir.module.module"].search([("name", "=", "l10n_eu_oss_oca")]).unlink()
# i += 1

env.cr.commit()

print("End fix migration Odoo 14.0 to Odoo 15.0")
