#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Restrict cron jobs to root and authorized users"
Vérifie que /etc/cron.deny n'existe pas (supprimé).
"""

import sys
import os

def check_measure():
    path = "/etc/cron.deny"
    if os.path.exists(path):
        return (2, f"CRITICAL - {path} existe encore, cron n'est pas restreint")
    else:
        return (0, "OK - /etc/cron.deny est absent")

def main():
    code, message = check_measure()
    print(message)
    sys.exit(code)

if __name__ == "__main__":
    main()

