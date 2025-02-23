#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Ensure the PermitRootLogin is set to no"
Vérifie la présence de 'PermitRootLogin no' dans /etc/ssh/sshd_config.
"""

import sys

def check_measure():
    path = "/etc/ssh/sshd_config"
    try:
        with open(path) as f:
            content = f.read()
            if "PermitRootLogin no" in content:
                return (0, "OK - PermitRootLogin est configuré à no")
            else:
                return (2, "CRITICAL - PermitRootLogin no absent")
    except Exception as e:
        return (3, f"UNKNOWN - {e}")

def main():
    c, m = check_measure()
    print(m)
    sys.exit(c)

if __name__ == "__main__":
    main()

