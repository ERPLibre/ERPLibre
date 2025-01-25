#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Allow ICINGA2 ports"
Vérifie si le port 5665/tcp est autorisé dans UFW.
"""

import sys
import subprocess

def check_measure():
    try:
        cmd = subprocess.run(["ufw", "status"], text=True, capture_output=True, check=True)
        output = cmd.stdout.lower()
        if "5665/tcp" in output and "allow" in output:
            return (0, "OK - Port 5665/tcp pour Icinga2 autorisé")
        else:
            return (2, "CRITICAL - Port 5665/tcp non autorisé")
    except Exception as e:
        return (3, f"UNKNOWN - Erreur : {e}")

def main():
    code, message = check_measure()
    print(message)
    sys.exit(code)

if __name__ == "__main__":
    main()

