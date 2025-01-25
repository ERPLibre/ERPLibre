#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Allow OpenVPN port"
Vérifie si le port 1194/udp est autorisé dans UFW.
"""

import sys
import subprocess

def check_measure():
    try:
        cmd = subprocess.run(["ufw", "status"], text=True, capture_output=True, check=True)
        output = cmd.stdout.lower()
        if "1194/udp" in output and "allow" in output:
            return (0, "OK - Port 1194/udp est autorisé (OpenVPN)")
        else:
            return (2, "CRITICAL - Port 1194/udp non autorisé")
    except Exception as e:
        return (3, f"UNKNOWN - Erreur : {e}")

def main():
    code, message = check_measure()
    print(message)
    sys.exit(code)

if __name__ == "__main__":
    main()

