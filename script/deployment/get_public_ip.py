#!./.venv/bin/python
import requests

r = requests.get(r'https://api.ipify.org')
ip = r.text
print(ip)
