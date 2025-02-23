#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Disable unprivileged BPF"
Vérifie kernel.unprivileged_bpf_disabled == 1
"""

import sys
import subprocess

def check_measure():
    try:
        cmd = subprocess.run(["sysctl", "-n", "kernel.unprivileged_bpf_disabled"], capture_output=True, text=True, check=True)
        val = cmd.stdout.strip()
        if val == "1":
            return (0, "OK - kernel.unprivileged_bpf_disabled=1")
        else:
            return (2, f"CRITICAL - kernel.unprivileged_bpf_disabled={val} (au lieu de 1)")
    except Exception as e:
        return (3, f"UNKNOWN - Erreur : {e}")

def main():
    code, msg = check_measure()
    print(msg)
    sys.exit(code)

if __name__ == "__main__":
    main()

