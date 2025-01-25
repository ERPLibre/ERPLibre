#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Disable SSH version 1 (only use version 2)"
Vérifie 'Protocol 2'.
"""

import sys

def check_measure():
    p = "/etc/ssh/sshd_config"
    try:
        with open(p) as f:
            if "Protocol 2" in f.read():
                return (0, "OK - Protocol 2 only")
            else:
                return (2, "CRITICAL - Protocol 2 non configuré")
    except Exception as e:
        return (3, f"UNKNOWN - {e}")

def main():
    c,m = check_measure()
    print(m)
    sys.exit(c)

if __name__=="__main__":
    main()

