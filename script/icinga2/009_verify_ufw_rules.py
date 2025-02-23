#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Verify UFW rules"
Vérifie simplement qu'on peut lister les règles sans erreur.
"""

import sys
import subprocess

def check_measure():
    try:
        subprocess.run(["ufw", "status"], text=True, capture_output=True, check=True)
        return (0, "OK - Les règles UFW sont disponibles")
    except subprocess.CalledProcessError as e:
        return (2, f"CRITICAL - Erreur ufw status : {e}")
    except Exception as e:
        return (3, f"UNKNOWN - Exception : {e}")

def main():
    code, message = check_measure()
    print(message)
    sys.exit(code)

if __name__ == "__main__":
    main()

