#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Disable core dumps"
Vérifie la présence de la ligne '* hard core 0' dans /etc/security/limits.conf (ou un fichier .d).
"""

import sys

def check_measure():
    path = "/etc/security/limits.conf"
    try:
        with open(path, "r") as f:
            content = f.read()
            if "* hard core 0" in content:
                return (0, "OK - core dumps désactivés via limits.conf")
            else:
                return (2, "CRITICAL - Pas de '* hard core 0' dans limits.conf")
    except FileNotFoundError:
        return (2, f"CRITICAL - Fichier {path} introuvable")
    except Exception as e:
        return (3, f"UNKNOWN - Erreur : {e}")

def main():
    code, message = check_measure()
    print(message)
    sys.exit(code)

if __name__ == "__main__":
    main()

