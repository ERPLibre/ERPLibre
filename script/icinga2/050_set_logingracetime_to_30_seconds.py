#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Set LoginGraceTime to 30"
Vérifie 'LoginGraceTime 30'.
"""

import sys

def check_measure():
    config = "/etc/ssh/sshd_config"
    try:
        with open(config) as f:
            if "LoginGraceTime 30" in f.read():
                return (0, "OK - LoginGraceTime=30")
            else:
                return (2, "CRITICAL - LoginGraceTime 30 absent")
    except Exception as e:
        return (3, f"UNKNOWN - {e}")

def main():
    c,m = check_measure()
    print(m)
    sys.exit(c)

if __name__=="__main__":
    main()

