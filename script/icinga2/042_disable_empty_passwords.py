#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Disable empty passwords"
Vérifie 'PermitEmptyPasswords no' dans sshd_config.
"""

import sys

def check_measure():
    path = "/etc/ssh/sshd_config"
    try:
        with open(path) as f:
            content = f.read()
            if "PermitEmptyPasswords no" in content:
                return (0, "OK - Empty passwords désactivés")
            else:
                return (2, "CRITICAL - PermitEmptyPasswords no absent")
    except Exception as e:
        return (3, f"UNKNOWN - {e}")

def main():
    c, m = check_measure()
    print(m)
    sys.exit(c)

if __name__ == "__main__":
    main()

