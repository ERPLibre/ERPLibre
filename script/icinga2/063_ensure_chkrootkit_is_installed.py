#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Ensure chkrootkit is installed"
Vérifie le package chkrootkit.
"""

import sys
import subprocess

def check_measure():
    try:
        subprocess.run(["dpkg", "-s", "chkrootkit"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return (0, "OK - chkrootkit est installé")
    except subprocess.CalledProcessError:
        return (2, "CRITICAL - chkrootkit n'est pas installé")
    except Exception as e:
        return (3, f"UNKNOWN - {e}")

def main():
    c,m=check_measure()
    print(m)
    sys.exit(c)

if __name__=="__main__":
    main()

