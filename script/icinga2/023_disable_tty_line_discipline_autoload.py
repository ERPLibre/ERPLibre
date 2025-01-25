#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Disable TTY line discipline autoload"
Vérifie dev.tty.ldisc_autoload == 0
"""

import sys
import subprocess

def check_measure():
    try:
        cmd = subprocess.run(["sysctl", "-n", "dev.tty.ldisc_autoload"], capture_output=True, text=True, check=True)
        val = cmd.stdout.strip()
        if val == "0":
            return (0, "OK - dev.tty.ldisc_autoload=0")
        else:
            return (2, f"CRITICAL - dev.tty.ldisc_autoload={val} (au lieu de 0)")
    except Exception as e:
        return (3, f"UNKNOWN - Erreur : {e}")

def main():
    code, msg = check_measure()
    print(msg)
    sys.exit(code)

if __name__ == "__main__":
    main()

