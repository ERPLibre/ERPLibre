#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Set UsePAM to yes"
Vérifie 'UsePAM yes'.
"""

import sys

def check_measure():
    path = "/etc/ssh/sshd_config"
    try:
        with open(path) as f:
            if "UsePAM yes" in f.read():
                return (0, "OK - UsePAM yes configuré")
            else:
                return (2, "CRITICAL - UsePAM yes absent")
    except Exception as e:
        return (3, f"UNKNOWN - {e}")

def main():
    c,m=check_measure()
    print(m)
    sys.exit(c)

if __name__=="__main__":
    main()

