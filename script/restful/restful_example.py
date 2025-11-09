#!/usr/bin/env python3
# © 2021-2025 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import json

import requests

headers = {
    "content-type": "application/x-www-form-urlencoded",
    "charset": "utf-8",
}

data = {"login": "admin", "password": "admin", "db": "test"}

base_url = "http://127.0.0.1:8069"

req = requests.get(f"{base_url}/api/auth/token", data=data, headers=headers)

response = req.content.decode("utf-8")

print(response)

content = json.loads(response)

headers["access-token"] = content.get("access_token")
# add the access token to the header

print(headers)

model_name = "helpdesk.ticket"
req = requests.get(
    f"{base_url}/api/{model_name}/",
    headers=headers,
    data={"limit": 10, "domain": []},
)

# ***Pass optional parameter like this, with data = ***
# {
#     "limit": 10,
#     "domain": "[('supplier','=',True),('parent_id','=', False)]",
#     "order": "name asc",
#     "offset": 10,
# }

print(req.content)
