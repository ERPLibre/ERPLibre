#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Ensure core dumps are disabled via sysctl"
Vérifie que fs.suid_dumpable == 0.
"""

import sys
import subprocess

def check_measure():
    try:
        cmd = subprocess.run(["sysctl", "-n", "fs.suid_dumpable"], capture_output=True, text=True, check=True)
        value = cmd.stdout.strip()
        if value == "0":
            return (0, "OK - fs.suid_dumpable=0 (core dumps désactivés)")
        else:
            return (2, f"CRITICAL - fs.suid_dumpable={value} (au lieu de 0)")
    except Exception as e:
        return (3, f"UNKNOWN - Erreur sysctl : {e}")

def main():
    code, message = check_measure()
    print(message)
    sys.exit(code)

if __name__ == "__main__":
    main()

