#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Installer Lynis"
Vérifie la présence du package lynis.
"""

import sys
import subprocess

def check_measure():
    try:
        subprocess.run(["dpkg", "-s", "lynis"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return (0, "OK - lynis installé")
    except subprocess.CalledProcessError:
        return (2, "CRITICAL - lynis non installé")
    except Exception as e:
        return (3, f"UNKNOWN - {e}")

def main():
    c,m=check_measure()
    print(m)
    sys.exit(c)

if __name__=="__main__":
    main()

