#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Disable agent forwarding"
Vérifie 'AllowAgentForwarding no'.
"""

import sys

def check_measure():
    path = "/etc/ssh/sshd_config"
    try:
        with open(path) as f:
            if "AllowAgentForwarding no" in f.read():
                return (0, "OK - Agent forwarding désactivé")
            else:
                return (2, "CRITICAL - AllowAgentForwarding no absent")
    except Exception as e:
        return (3, f"UNKNOWN - {e}")

def main():
    c,m=check_measure()
    print(m)
    sys.exit(c)

if __name__=="__main__":
    main()

