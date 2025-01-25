#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Replace old AIDE database with the new one"
Vérifie la présence de /var/lib/aide/aide.db.gz après le mv.
"""

import sys
import os

def check_measure():
    db = "/var/lib/aide/aide.db.gz"
    if os.path.exists(db):
        return (0, f"OK - {db} est présent (la nouvelle base a remplacé l'ancienne)")
    else:
        return (2, f"CRITICAL - {db} n'existe pas, le mv n'a pas été fait ?")

def main():
    c,m=check_measure()
    print(m)
    sys.exit(c)

if __name__=="__main__":
    main()

