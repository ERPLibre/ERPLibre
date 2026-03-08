"""
ERPLibre - pyinfra inventory.

Defines target hosts and their data.
"""

# Local deployment (current machine)
local = ["@local"]

# Example for remote servers:
# production = [
#     ("prod1.erplibre.ca", {"odoo_version": "18.0"}),
#     ("prod2.erplibre.ca", {"odoo_version": "17.0"}),
# ]

# staging = [
#     ("staging.erplibre.ca", {
#         "ssh_user": "erplibre",
#         "odoo_version": "18.0",
#     }),
# ]
