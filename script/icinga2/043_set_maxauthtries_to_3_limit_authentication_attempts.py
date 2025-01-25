#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Set MaxAuthTries to 3"
Vérifie 'MaxAuthTries 3' dans /etc/ssh/sshd_config.
"""

import sys

def check_measure():
    path = "/etc/ssh/sshd_config"
    try:
        with open(path) as f:
            if "MaxAuthTries 3" in f.read():
                return (0, "OK - MaxAuthTries=3")
            else:
                return (2, "CRITICAL - MaxAuthTries 3 absent")
    except Exception as e:
        return (3, f"UNKNOWN - {e}")

def main():
    c,m = check_measure()
    print(m)
    sys.exit(c)

if __name__ == "__main__":
    main()

