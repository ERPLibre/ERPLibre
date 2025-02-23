#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Create logrotate configuration for rsyslog"
Vérifie la présence du fichier /etc/logrotate.d/rsyslog.
"""

import sys
import os

def check_measure():
    path = "/etc/logrotate.d/rsyslog"
    if os.path.exists(path):
        return (0, f"OK - {path} existe")
    else:
        return (2, f"CRITICAL - {path} n'existe pas")

def main():
    c,m=check_measure()
    print(m)
    sys.exit(c)

if __name__=="__main__":
    main()

