#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Exécuter un audit de sécurité"
Placeholder : Vérifie la présence d'un rapport Lynis ? 
"""

import sys
import os

def check_measure():
    # Par exemple, /var/log/lynis.log
    report = "/var/log/lynis.log"
    if os.path.exists(report):
        return (0, f"OK - Rapport Lynis trouvé : {report}")
    else:
        return (1, f"WARNING - Pas de rapport {report}, audit non confirmé")

def main():
    c,m=check_measure()
    print(m)
    sys.exit(c)

if __name__=="__main__":
    main()

