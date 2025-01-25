#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Create chkrootkit daily scan script"
Vérifie l'existence de /etc/cron.daily/chkrootkit
"""

import sys
import os

def check_measure():
    script = "/etc/cron.daily/chkrootkit"
    if os.path.isfile(script):
        return (0, f"OK - Script {script} présent")
    else:
        return (2, f"CRITICAL - {script} absent")

def main():
    c,m=check_measure()
    print(m)
    sys.exit(c)

if __name__=="__main__":
    main()

