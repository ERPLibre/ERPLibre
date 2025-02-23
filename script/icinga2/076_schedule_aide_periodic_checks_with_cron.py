#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Schedule AIDE periodic checks with cron"
Vérifie la présence d'une tâche cron "aide --check" programmée (ex. /var/spool/cron ou /etc/cron.*).
Ici, on regarde si /etc/cron.daily contient un script ou on fait un placeholder.
"""

import sys
import os

def check_measure():
    # Exemple : /etc/cron.daily/aide ou on lit "crontab -l" etc.
    candidate = "/etc/cron.daily/aide"
    if os.path.exists(candidate):
        return (0, f"OK - Script {candidate} présent pour vérification AIDE")
    else:
        return (1, f"WARNING - Pas de script {candidate}, la vérification AIDE n'est peut-être pas planifiée")

def main():
    c,m=check_measure()
    print(m)
    sys.exit(c)

if __name__=="__main__":
    main()

