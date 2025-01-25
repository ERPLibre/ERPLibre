#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Backup the current sshd_config"
Vérifie l'existence de /etc/ssh/sshd_config.bak
"""

import sys
import os

def check_measure():
    bak_path = "/etc/ssh/sshd_config.bak"
    if os.path.exists(bak_path):
        return (0, "OK - /etc/ssh/sshd_config.bak existe")
    else:
        return (2, f"CRITICAL - {bak_path} introuvable")

def main():
    code, msg = check_measure()
    print(msg)
    sys.exit(code)

if __name__ == "__main__":
    main()

