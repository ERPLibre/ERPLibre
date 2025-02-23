#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Debug chkrootkit scan results"
Placeholder : vérifie éventuellement un mot-clé dans /var/log/chkrootkit/chkrootkit.log
"""

import sys
import os

def check_measure():
    logpath = "/var/log/chkrootkit/chkrootkit.log"
    if not os.path.exists(logpath):
        return (1, f"WARNING - Fichier {logpath} introuvable, pas de debug possible")
    try:
        with open(logpath, "r") as f:
            content = f.read().lower()
            if "infected" in content:
                return (2, "CRITICAL - 'infected' trouvé dans le log chkrootkit !")
            else:
                return (0, "OK - Pas de 'infected' dans chkrootkit.log")
    except Exception as e:
        return (3, f"UNKNOWN - {e}")

def main():
    c,m=check_measure()
    print(m)
    sys.exit(c)

if __name__=="__main__":
    main()

