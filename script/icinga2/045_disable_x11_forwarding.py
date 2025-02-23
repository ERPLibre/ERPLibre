#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Disable X11 forwarding"
Vérifie 'X11Forwarding no'.
"""

import sys

def check_measure():
    path = "/etc/ssh/sshd_config"
    try:
        with open(path) as f:
            if "X11Forwarding no" in f.read():
                return (0, "OK - X11Forwarding no")
            else:
                return (2, "CRITICAL - X11Forwarding no absent")
    except Exception as e:
        return (3, f"UNKNOWN - {e}")

def main():
    c,m=check_measure()
    print(m)
    sys.exit(c)

if __name__=="__main__":
    main()

