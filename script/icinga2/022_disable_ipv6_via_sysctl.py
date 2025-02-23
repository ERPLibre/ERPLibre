#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Disable IPv6 via sysctl"
Vérifie net.ipv6.conf.all.disable_ipv6 == 1.
"""

import sys
import subprocess

def check_measure():
    try:
        cmd = subprocess.run(["sysctl", "-n", "net.ipv6.conf.all.disable_ipv6"], capture_output=True, text=True, check=True)
        val = cmd.stdout.strip()
        if val == "1":
            return (0, "OK - IPv6 est désactivé (net.ipv6.conf.all.disable_ipv6=1)")
        else:
            return (2, f"CRITICAL - IPv6 n'est pas désactivé (valeur={val})")
    except Exception as e:
        return (3, f"UNKNOWN - Erreur : {e}")

def main():
    code, message = check_measure()
    print(message)
    sys.exit(code)

if __name__ == "__main__":
    main()

