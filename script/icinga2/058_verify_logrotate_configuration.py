#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Verify logrotate configuration"
Exécute logrotate -d /etc/logrotate.conf et regarde le code retour.
"""

import sys
import subprocess

def check_measure():
    try:
        cmd = subprocess.run(["logrotate", "-d", "/etc/logrotate.conf"], capture_output=True, text=True)
        # logrotate -d renvoie 0 en mode "debug" si OK
        if cmd.returncode == 0:
            return (0, "OK - logrotate -d ne signale pas d'erreur")
        else:
            return (1, f"WARNING - logrotate debug code={cmd.returncode} : {cmd.stderr}")
    except Exception as e:
        return (3, f"UNKNOWN - {e}")

def main():
    c,m=check_measure()
    print(m)
    sys.exit(c)

if __name__=="__main__":
    main()

