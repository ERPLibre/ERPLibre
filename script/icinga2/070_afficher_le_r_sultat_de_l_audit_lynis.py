#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Afficher le résultat de l'audit Lynis"
Placeholder : Idem, on peut lire /var/log/lynis.log
"""

import sys
import os

def check_measure():
    path = "/var/log/lynis.log"
    if not os.path.exists(path):
        return (1, f"WARNING - Fichier {path} introuvable, impossible d'afficher le résultat")
    try:
        with open(path) as f:
            # Juste un check minimal
            content = f.read()
            if "warning" in content.lower():
                return (1, "WARNING - Le rapport Lynis contient des alertes")
            else:
                return (0, "OK - Rapport Lynis sans 'warning' explicite")
    except Exception as e:
        return (3, f"UNKNOWN - {e}")

def main():
    c,m=check_measure()
    print(m)
    sys.exit(c)

if __name__=="__main__":
    main()

