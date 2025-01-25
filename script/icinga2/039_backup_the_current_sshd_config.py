#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Backup the current sshd_config" (deuxième occurrence ?)
Même contrôle : /etc/ssh/sshd_config.bak
"""

import sys
import os

def check_measure():
    bak = "/etc/ssh/sshd_config.bak"
    if os.path.exists(bak):
        return (0, f"OK - Fichier backup {bak} existe")
    else:
        return (2, f"CRITICAL - {bak} n'existe pas")

def main():
    code, msg = check_measure()
    print(msg)
    sys.exit(code)

if __name__ == "__main__":
    main()

