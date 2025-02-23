#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Ensure /etc/cron.allow exists and has correct permissions"
Doit exister, 0640 root:root.
"""

import sys
import os
import stat

def check_measure():
    path = "/etc/cron.allow"
    if not os.path.exists(path):
        return (2, f"CRITICAL - {path} n'existe pas")
    try:
        st = os.stat(path)
        mode = stat.S_IMODE(st.st_mode)
        if mode != 0o640 or st.st_uid != 0 or st.st_gid != 0:
            return (2, f"CRITICAL - {path} n'est pas 0640 root:root")
        return (0, f"OK - {path} est 0640 root:root")
    except Exception as e:
        return (3, f"UNKNOWN - Erreur : {e}")

def main():
    code, message = check_measure()
    print(message)
    sys.exit(code)

if __name__ == "__main__":
    main()

