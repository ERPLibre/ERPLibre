#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Set ClientAliveCountMax to 0"
Vérifie 'ClientAliveCountMax 0'.
"""

import sys

def check_measure():
    p = "/etc/ssh/sshd_config"
    try:
        with open(p) as f:
            if "ClientAliveCountMax 0" in f.read():
                return (0, "OK - ClientAliveCountMax=0")
            else:
                return (2, "CRITICAL - ClientAliveCountMax 0 absent")
    except Exception as e:
        return (3, f"UNKNOWN - {e}")

def main():
    c,m=check_measure()
    print(m)
    sys.exit(c)

if __name__=="__main__":
    main()

