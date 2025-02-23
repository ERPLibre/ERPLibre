#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Run immediate chkrootkit scan"
Vérifie éventuellement la date/présence d'un scan, ou placeholder.
"""

import sys
import os

def check_measure():
    # Par exemple, vérifier /var/log/chkrootkit/chkrootkit.log
    logpath = "/var/log/chkrootkit/chkrootkit.log"
    if os.path.exists(logpath):
        return (0, f"OK - Un log de chkrootkit existe : {logpath}")
    else:
        return (1, f"WARNING - Pas de log {logpath}, scan immédiat non tracé ?")

def main():
    c,m=check_measure()
    print(m)
    sys.exit(c)

if __name__=="__main__":
    main()

