#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Disable DNS lookup for SSH"
Vérifie 'UseDNS no'.
"""

import sys

def check_measure():
    p = "/etc/ssh/sshd_config"
    try:
        with open(p) as f:
            if "UseDNS no" in f.read():
                return (0, "OK - UseDNS no configuré")
            else:
                return (2, "CRITICAL - UseDNS no absent")
    except Exception as e:
        return (3, f"UNKNOWN - {e}")

def main():
    c,m=check_measure()
    print(m)
    sys.exit(c)

if __name__=="__main__":
    main()

