#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Ensure auditd service is enabled and running"
Vérifie si 'auditd' est actif et enabled via systemd.
"""

import sys
import subprocess

def check_measure():
    try:
        # Vérifier is-enabled
        cmd_enabled = subprocess.run(["systemctl", "is-enabled", "auditd"], capture_output=True, text=True)
        # Vérifier is-active
        cmd_active = subprocess.run(["systemctl", "is-active", "auditd"], capture_output=True, text=True)
        if cmd_enabled.stdout.strip() == "enabled" and cmd_active.stdout.strip() == "active":
            return (0, "OK - auditd est enable + running")
        else:
            return (2, f"CRITICAL - auditd (enabled={cmd_enabled.stdout.strip()}, active={cmd_active.stdout.strip()})")
    except Exception as e:
        return (3, f"UNKNOWN - {e}")

def main():
    code, msg = check_measure()
    print(msg)
    sys.exit(code)

if __name__ == "__main__":
    main()

