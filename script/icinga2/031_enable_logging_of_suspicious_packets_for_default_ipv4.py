#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Enable logging of suspicious packets for default IPv4"
Vérifie net.ipv4.conf.default.log_martians == 1
"""

import sys
import subprocess

def check_measure():
    try:
        cmd = subprocess.run(["sysctl", "-n", "net.ipv4.conf.default.log_martians"], capture_output=True, text=True, check=True)
        val = cmd.stdout.strip()
        if val == "1":
            return (0, "OK - net.ipv4.conf.default.log_martians=1")
        else:
            return (2, f"CRITICAL - log_martians={val} (au lieu de 1)")
    except Exception as e:
        return (3, f"UNKNOWN - {e}")

def main():
    code, msg = check_measure()
    print(msg)
    sys.exit(code)

if __name__ == "__main__":
    main()

