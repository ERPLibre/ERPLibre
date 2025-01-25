#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Create directory for chkrootkit logs"
Vérifie l'existence de /var/log/chkrootkit
"""

import sys
import os

def check_measure():
    path = "/var/log/chkrootkit"
    if os.path.isdir(path):
        return (0, f"OK - Répertoire {path} existe")
    else:
        return (2, f"CRITICAL - Répertoire {path} inexistant")

def main():
    c,m=check_measure()
    print(m)
    sys.exit(c)

if __name__=="__main__":
    main()

