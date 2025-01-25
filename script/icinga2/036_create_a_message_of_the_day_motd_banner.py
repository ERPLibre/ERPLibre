#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Create a message of the day (MOTD) banner"
Vérifie /etc/motd présent et contient un mot-clé identifiable.
"""

import sys
import os

def check_measure():
    path = "/etc/motd"
    if not os.path.exists(path):
        return (2, "CRITICAL - /etc/motd n'existe pas")
    try:
        with open(path, "r") as f:
            content = f.read()
            if "AVERTISSEMENT" in content or "WARNING" in content:
                return (0, "OK - /etc/motd existe et contient le banner")
            else:
                return (1, "WARNING - /etc/motd existe mais le contenu semble incomplet")
    except Exception as e:
        return (3, f"UNKNOWN - {e}")

def main():
    code, msg = check_measure()
    print(msg)
    sys.exit(code)

if __name__ == "__main__":
    main()

