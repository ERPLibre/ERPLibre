#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Ensure UFW is installed"
Vérifie si 'ufw' est présent.
"""

import sys
import subprocess

def check_measure():
    try:
        subprocess.run(["which", "ufw"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return (0, "OK - ufw est installé")
    except subprocess.CalledProcessError:
        return (2, "CRITICAL - ufw n'est pas installé")
    except Exception as e:
        return (3, f"UNKNOWN - Erreur : {e}")

def main():
    code, message = check_measure()
    print(message)
    sys.exit(code)

if __name__ == "__main__":
    main()

