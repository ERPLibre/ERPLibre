#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Remove any existing AIDE database (if any)"
Vérifie que /var/lib/aide/aide.db.gz est absent.
"""

import sys
import os

def check_measure():
    db = "/var/lib/aide/aide.db.gz"
    if os.path.exists(db):
        return (2, f"CRITICAL - La base AIDE {db} est toujours présente")
    else:
        return (0, f"OK - Pas de base AIDE existante")

def main():
    c,m=check_measure()
    print(m)
    sys.exit(c)

if __name__=="__main__":
    main()

