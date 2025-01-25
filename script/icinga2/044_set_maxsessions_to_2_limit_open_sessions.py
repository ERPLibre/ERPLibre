#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Set MaxSessions to 2"
Vérifie 'MaxSessions 2'.
"""

import sys

def check_measure():
    path = "/etc/ssh/sshd_config"
    try:
        with open(path) as f:
            if "MaxSessions 2" in f.read():
                return (0, "OK - MaxSessions=2")
            else:
                return (2, "CRITICAL - MaxSessions 2 absent")
    except Exception as e:
        return (3, f"UNKNOWN - {e}")

def main():
    c,m = check_measure()
    print(m)
    sys.exit(c)

if __name__ == "__main__":
    main()

