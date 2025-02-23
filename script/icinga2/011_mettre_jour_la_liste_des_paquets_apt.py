#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Mettre à jour la liste des paquets APT"
Vérifie la présence (et la relative fraîcheur) du fichier /var/lib/apt/periodic/update-success-stamp.
"""

import sys
import os
import time

def check_measure():
    stamp = "/var/lib/apt/periodic/update-success-stamp"
    if not os.path.exists(stamp):
        return (1, f"WARNING - {stamp} n'existe pas. Cache apt non mis à jour ?")
    mtime = os.path.getmtime(stamp)
    age_hours = (time.time() - mtime) / 3600
    if age_hours < 24:
        return (0, "OK - La liste des paquets APT a été mise à jour il y a moins de 24h")
    else:
        return (1, f"WARNING - Le dernier update-cache a plus de 24h (env. {age_hours:.1f}h)")

def main():
    code, message = check_measure()
    print(message)
    sys.exit(code)

if __name__ == "__main__":
    main()

