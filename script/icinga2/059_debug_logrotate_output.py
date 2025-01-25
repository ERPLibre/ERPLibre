#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Debug logrotate output"
Placeholder. Vérifie éventuellement un log ou renvoie OK par défaut.
"""

import sys

def check_measure():
    # Implémentez votre logique si besoin
    return (0, "OK - Debug logrotate output (placeholder)")

def main():
    c,m=check_measure()
    print(m)
    sys.exit(c)

if __name__=="__main__":
    main()

