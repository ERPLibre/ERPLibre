#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Harden BPF JIT compilation"
Vérifie net.core.bpf_jit_harden == 2
"""

import sys
import subprocess

def check_measure():
    try:
        cmd = subprocess.run(["sysctl", "-n", "net.core.bpf_jit_harden"], capture_output=True, text=True, check=True)
        val = cmd.stdout.strip()
        if val == "2":
            return (0, "OK - net.core.bpf_jit_harden=2")
        else:
            return (2, f"CRITICAL - net.core.bpf_jit_harden={val} (au lieu de 2)")
    except Exception as e:
        return (3, f"UNKNOWN - Erreur : {e}")

def main():
    code, msg = check_measure()
    print(msg)
    sys.exit(code)

if __name__ == "__main__":
    main()

