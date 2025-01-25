#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Set default policy to allow outgoing traffic"
Vérifie si UFW a une politique par défaut en ALLOW pour outgoing.
"""

import sys
import subprocess

def check_measure():
    try:
        cmd = subprocess.run(["ufw", "status", "verbose"], text=True, capture_output=True, check=True)
        output = cmd.stdout.lower()
        if "default: allow (outgoing)" in output:
            return (0, "OK - Politique par défaut sortante : ALLOW")
        else:
            return (2, "CRITICAL - La politique par défaut sortante n'est pas ALLOW")
    except Exception as e:
        return (3, f"UNKNOWN - Erreur : {e}")

def main():
    code, message = check_measure()
    print(message)
    sys.exit(code)

if __name__ == "__main__":
    main()

