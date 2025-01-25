#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Ensure banner is displayed on SSH login"
Vérifie la présence de 'Banner /etc/motd' dans /etc/ssh/sshd_config.
"""

import sys

def check_measure():
    path = "/etc/ssh/sshd_config"
    try:
        with open(path, "r") as f:
            content = f.read()
            if "Banner /etc/motd" in content:
                return (0, "OK - Banner /etc/motd est configuré dans sshd_config")
            else:
                return (2, "CRITICAL - Pas de 'Banner /etc/motd' dans sshd_config")
    except Exception as e:
        return (3, f"UNKNOWN - {e}")

def main():
    code, msg = check_measure()
    print(msg)
    sys.exit(code)

if __name__ == "__main__":
    main()

