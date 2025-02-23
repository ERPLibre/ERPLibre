#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Apply recommended sysctl settings"
Vérifie un ensemble de clés sysctl et leurs valeurs attendues.
"""

import sys
import subprocess

REQUIRED = {
    "fs.protected_fifos": "2",
    "kernel.kptr_restrict": "2",
    "kernel.sysrq": "0",
    "net.ipv4.conf.all.accept_redirects": "0",
    "net.ipv4.conf.all.log_martians": "1",
    "net.ipv4.tcp_syncookies": "1",
    "net.ipv6.conf.all.accept_redirects": "0"
}

def check_measure():
    msgs = []
    exit_code = 0
    for key, expected in REQUIRED.items():
        try:
            cmd = subprocess.run(["sysctl", "-n", key], capture_output=True, text=True, check=True)
            val = cmd.stdout.strip()
            if val != expected:
                msgs.append(f"{key}={val} (au lieu de {expected})")
                exit_code = 2
        except Exception as e:
            msgs.append(f"{key} inaccessible ({e})")
            exit_code = max(exit_code, 3)
    if exit_code == 0:
        return (0, "OK - Tous les paramètres sysctl sont conformes")
    elif exit_code == 2:
        return (2, "CRITICAL - Paramètres non conformes: " + ", ".join(msgs))
    else:
        return (3, "UNKNOWN - Erreurs : " + ", ".join(msgs))

def main():
    c,m=check_measure()
    print(m)
    sys.exit(c)

if __name__=="__main__":
    main()

