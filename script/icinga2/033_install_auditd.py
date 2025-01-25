#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Install auditd"
Vérifie que le package 'auditd' est installé.
"""

import sys
import subprocess

def check_package(pkg):
    try:
        subprocess.run(["dpkg", "-s", pkg], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return True
    except subprocess.CalledProcessError:
        return False

def check_measure():
    if check_package("auditd"):
        return (0, "OK - auditd est installé")
    else:
        return (2, "CRITICAL - auditd n'est pas installé")

def main():
    code, msg = check_measure()
    print(msg)
    sys.exit(code)

if __name__ == "__main__":
    main()

