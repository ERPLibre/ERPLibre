#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Disable accepting of ICMP redirects by default for IPv6"
Vérifie net.ipv6.conf.default.accept_redirects == 0
"""

import sys
import subprocess

def check_measure():
    try:
        cmd = subprocess.run(["sysctl", "-n", "net.ipv6.conf.default.accept_redirects"], capture_output=True, text=True, check=True)
        val = cmd.stdout.strip()
        if val == "0":
            return (0, "OK - net.ipv6.conf.default.accept_redirects=0")
        else:
            return (2, f"CRITICAL - net.ipv6.conf.default.accept_redirects={val}")
    except Exception as e:
        return (3, f"UNKNOWN - {e}")

def main():
    code, msg = check_measure()
    print(msg)
    sys.exit(code)

if __name__ == "__main__":
    main()

