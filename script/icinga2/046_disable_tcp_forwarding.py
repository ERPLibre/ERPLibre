#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Disable TCP forwarding"
Vérifie 'AllowTcpForwarding no'.
"""

import sys

def check_measure():
    path = "/etc/ssh/sshd_config"
    try:
        with open(path) as f:
            if "AllowTcpForwarding no" in f.read():
                return (0, "OK - TCP forwarding désactivé")
            else:
                return (2, "CRITICAL - AllowTcpForwarding no absent")
    except Exception as e:
        return (3, f"UNKNOWN - {e}")

def main():
    c,m=check_measure()
    print(m)
    sys.exit(c)

if __name__=="__main__":
    main()

