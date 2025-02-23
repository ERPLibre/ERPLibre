#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Ensure logrotate is installed"
Vérifie 'logrotate' est présent.
"""

import sys
import subprocess

def check_measure():
    try:
        subprocess.run(["dpkg", "-s", "logrotate"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return (0, "OK - logrotate est installé")
    except subprocess.CalledProcessError:
        return (2, "CRITICAL - logrotate n'est pas installé")
    except Exception as e:
        return (3, f"UNKNOWN - {e}")

def main():
    c,m=check_measure()
    print(m)
    sys.exit(c)

if __name__=="__main__":
    main()

