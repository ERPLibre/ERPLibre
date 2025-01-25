#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Ensure AppArmor is enabled and running"
Vérifie le statut du service 'apparmor'.
"""

import sys
import subprocess

def check_measure():
    try:
        cmd_enabled = subprocess.run(["systemctl", "is-enabled", "apparmor"], capture_output=True, text=True)
        cmd_active = subprocess.run(["systemctl", "is-active", "apparmor"], capture_output=True, text=True)
        if cmd_enabled.stdout.strip() == "enabled" and cmd_active.stdout.strip() == "active":
            return (0, "OK - AppArmor est enable + running")
        else:
            return (2, f"CRITICAL - AppArmor (enabled={cmd_enabled.stdout.strip()}, active={cmd_active.stdout.strip()})")
    except Exception as e:
        return (3, f"UNKNOWN - {e}")

def main():
    code, msg = check_measure()
    print(msg)
    sys.exit(code)

if __name__ == "__main__":
    main()

