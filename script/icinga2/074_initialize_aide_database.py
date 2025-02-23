#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Initialize AIDE database"
Vérifie l'existence de /var/lib/aide/aide.db.new.gz après init.
"""

import sys
import os

def check_measure():
    newdb = "/var/lib/aide/aide.db.new.gz"
    if os.path.exists(newdb):
        return (0, f"OK - La base initiale {newdb} existe")
    else:
        return (2, f"CRITICAL - {newdb} introuvable après initialisation")

def main():
    c,m=check_measure()
    print(m)
    sys.exit(c)

if __name__=="__main__":
    main()

