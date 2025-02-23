#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Display UFW configuration"
Vérifie qu'on peut récupérer la configuration (status verbose).
"""

import sys
import subprocess

def check_measure():
    try:
        cmd = subprocess.run(["ufw", "status", "verbose"], text=True, capture_output=True, check=True)
        if cmd.returncode == 0:
            return (0, "OK - Configuration UFW:\n" + cmd.stdout)
        else:
            return (2, "CRITICAL - Impossible d'afficher la configuration UFW")
    except Exception as e:
        return (3, f"UNKNOWN - Erreur : {e}")

def main():
    code, message = check_measure()
    print(message)
    sys.exit(code)

if __name__ == "__main__":
    main()

