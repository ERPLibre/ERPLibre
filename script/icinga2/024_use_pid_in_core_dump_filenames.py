#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Use PID in core dump filenames"
Vérifie kernel.core_uses_pid == 1
"""

import sys
import subprocess

def check_measure():
    try:
        cmd = subprocess.run(["sysctl", "-n", "kernel.core_uses_pid"], capture_output=True, text=True, check=True)
        val = cmd.stdout.strip()
        if val == "1":
            return (0, "OK - kernel.core_uses_pid=1")
        else:
            return (2, f"CRITICAL - kernel.core_uses_pid={val} (au lieu de 1)")
    except Exception as e:
        return (3, f"UNKNOWN - Erreur : {e}")

def main():
    code, msg = check_measure()
    print(msg)
    sys.exit(code)

if __name__ == "__main__":
    main()

