#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Install fail2ban"
Vérifie le package fail2ban.
"""

import sys
import subprocess

def check_measure():
    try:
        subprocess.run(["dpkg", "-s", "fail2ban"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return (0, "OK - fail2ban est installé")
    except subprocess.CalledProcessError:
        return (2, "CRITICAL - fail2ban n'est pas installé")
    except Exception as e:
        return (3, f"UNKNOWN - {e}")

def main():
    c,m=check_measure()
    print(m)
    sys.exit(c)

if __name__=="__main__":
    main()

