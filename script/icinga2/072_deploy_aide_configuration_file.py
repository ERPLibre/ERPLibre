#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Deploy AIDE configuration file"
Vérifie /etc/aide/aide.conf
"""

import sys
import os

def check_measure():
    path = "/etc/aide/aide.conf"
    if os.path.exists(path):
        return (0, f"OK - Fichier {path} présent")
    else:
        return (2, f"CRITICAL - {path} absent")

def main():
    c,m=check_measure()
    print(m)
    sys.exit(c)

if __name__=="__main__":
    main()

