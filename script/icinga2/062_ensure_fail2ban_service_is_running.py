#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Ensure fail2ban service is running"
Vérifie service fail2ban (actif + enabled).
"""

import sys
import subprocess

def check_measure():
    try:
        cmd_active = subprocess.run(["systemctl", "is-active", "fail2ban"], capture_output=True, text=True)
        cmd_enabled = subprocess.run(["systemctl", "is-enabled", "fail2ban"], capture_output=True, text=True)
        if cmd_active.stdout.strip() == "active" and cmd_enabled.stdout.strip() in ["enabled", "static"]:
            return (0, "OK - fail2ban est actif et enabled")
        else:
            return (2, f"CRITICAL - fail2ban (active={cmd_active.stdout.strip()}, enabled={cmd_enabled.stdout.strip()})")
    except Exception as e:
        return (3, f"UNKNOWN - {e}")

def main():
    c,m = check_measure()
    print(m)
    sys.exit(c)

if __name__=="__main__":
    main()

