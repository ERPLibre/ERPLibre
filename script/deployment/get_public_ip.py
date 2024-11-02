#!/usr/bin/env python3
# © 2021-2024 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import requests

r = requests.get(r"https://api.ipify.org")
ip = r.text
print(ip)
