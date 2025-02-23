#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Allow SSH immediately"
Vérifie si le port 22/tcp est autorisé via UFW.
"""

import sys
import subprocess

def check_measure():
    try:
        cmd = subprocess.run(["ufw", "status"], text=True, capture_output=True, check=True)
        output = cmd.stdout.lower()
        if "22/tcp" in output and "allow" in output:
            return (0, "OK - SSH (22/tcp) est autorisé")
        else:
            return (2, "CRITICAL - SSH (22/tcp) n'est pas autorisé")
    except Exception as e:
        return (3, f"UNKNOWN - Erreur UFW : {e}")

def main():
    code, message = check_measure()
    print(message)
    sys.exit(code)

if __name__ == "__main__":
    main()

