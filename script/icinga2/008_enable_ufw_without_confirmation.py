#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Enable UFW without confirmation"
Vérifie si UFW est actif (status: active).
"""

import sys
import subprocess

def check_measure():
    try:
        cmd = subprocess.run(["ufw", "status"], text=True, capture_output=True, check=True)
        output = cmd.stdout.lower()
        if "status: active" in output:
            return (0, "OK - UFW est actif")
        else:
            return (2, "CRITICAL - UFW n'est pas actif")
    except Exception as e:
        return (3, f"UNKNOWN - Erreur : {e}")

def main():
    code, message = check_measure()
    print(message)
    sys.exit(code)

if __name__ == "__main__":
    main()

