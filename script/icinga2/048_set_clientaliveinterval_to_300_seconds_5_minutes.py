#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Set ClientAliveInterval to 300"
Vérifie 'ClientAliveInterval 300'.
"""

import sys

def check_measure():
    path = "/etc/ssh/sshd_config"
    try:
        with open(path) as f:
            if "ClientAliveInterval 300" in f.read():
                return (0, "OK - ClientAliveInterval=300")
            else:
                return (2, "CRITICAL - ClientAliveInterval 300 absent")
    except Exception as e:
        return (3, f"UNKNOWN - {e}")

def main():
    c,m=check_measure()
    print(m)
    sys.exit(c)

if __name__=="__main__":
    main()

