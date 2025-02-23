#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Restart SSH service to apply changes"
Vérifie que le service ssh(d) est 'active'.
"""

import sys
import subprocess

def check_measure():
    for svc in ["ssh", "sshd"]:
        try:
            cmd = subprocess.run(["systemctl", "is-active", svc], capture_output=True, text=True)
            if cmd.returncode == 0 and cmd.stdout.strip() == "active":
                return (0, f"OK - Service {svc} actif")
        except:
            pass
    return (2, "CRITICAL - Le service SSH n'est pas actif ou introuvable")

def main():
    c,m = check_measure()
    print(m)
    sys.exit(c)

if __name__=="__main__":
    main()

