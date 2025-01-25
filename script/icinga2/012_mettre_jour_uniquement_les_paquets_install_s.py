#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Mettre à jour uniquement les paquets installés"
Contrôle indicatif : on vérifie un log ou on déclare UNKNOWN faute de mieux.
"""

import sys

def check_measure():
    # Ex. : On pourrait parser /var/log/apt/history.log, etc.
    return (3, "UNKNOWN - Pas de vérification précise implémentée pour apt upgrade.")

def main():
    code, message = check_measure()
    print(message)
    sys.exit(code)

if __name__ == "__main__":
    main()

