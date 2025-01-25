#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Allow HTTP and HTTPS"
Vérifie si les ports 80/tcp et 443/tcp sont autorisés.
"""

import sys
import subprocess

def check_measure():
    ports_to_check = ["80/tcp", "443/tcp"]
    try:
        cmd = subprocess.run(["ufw", "status"], text=True, capture_output=True, check=True)
        output = cmd.stdout.lower()
        missing = []
        for p in ports_to_check:
            # Vérifie si la ligne existe et contient "allow"
            if p not in output or ("allow" not in [l for l in output.splitlines() if p in l][0]):
                missing.append(p)
        if not missing:
            return (0, "OK - HTTP(80) et HTTPS(443) autorisés")
        else:
            return (2, f"CRITICAL - Ports non autorisés: {missing}")
    except Exception as e:
        return (3, f"UNKNOWN - Erreur : {e}")

def main():
    code, message = check_measure()
    print(message)
    sys.exit(code)

if __name__ == "__main__":
    main()

