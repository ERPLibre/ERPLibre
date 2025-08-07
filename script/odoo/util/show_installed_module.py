#!/usr/bin/env python3
# © 2021-2025 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

installed_modules = env["ir.module.module"].search([('state', '=', 'installed')])

print("Installed modules:")

for module in installed_modules:
    print(module.name)
