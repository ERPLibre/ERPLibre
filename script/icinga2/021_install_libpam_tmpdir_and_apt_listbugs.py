#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Install libpam-tmpdir and apt-listbugs"
Vérifie la présence des paquets libpam-tmpdir et apt-listbugs.
"""

import sys
import subprocess

def check_package(pkg):
    try:
        subprocess.run(["dpkg", "-s", pkg], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True
    except subprocess.CalledProcessError:
        return False

def check_measure():
    missing = []
    for p in ["libpam-tmpdir", "apt-listbugs"]:
        if not check_package(p):
            missing.append(p)
    if missing:
        return (2, f"CRITICAL - Paquets manquants: {missing}")
    else:
        return (0, "OK - libpam-tmpdir et apt-listbugs sont installés")

def main():
    code, message = check_measure()
    print(message)
    sys.exit(code)

if __name__ == "__main__":
    main()

