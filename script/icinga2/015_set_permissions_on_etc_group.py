#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Set permissions on /etc/group"
Doit être 0644 root:root.
"""

import sys
import os
import stat

def check_measure():
    path = "/etc/group"
    try:
        st = os.stat(path)
        mode = stat.S_IMODE(st.st_mode)
        if mode != 0o644 or st.st_uid != 0 or st.st_gid != 0:
            return (2, "CRITICAL - /etc/group n'est pas en 0644 root:root")
        return (0, "OK - /etc/group est en 0644 root:root")
    except Exception as e:
        return (3, f"UNKNOWN - Erreur : {e}")

def main():
    code, message = check_measure()
    print(message)
    sys.exit(code)

if __name__ == "__main__":
    main()

