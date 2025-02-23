#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Set permissions on /etc/gshadow"
Doit être 0640 root:shadow.
"""

import sys
import os
import stat
import grp

def check_measure():
    path = "/etc/gshadow"
    try:
        st = os.stat(path)
        mode = stat.S_IMODE(st.st_mode)
        gr_name = grp.getgrgid(st.st_gid).gr_name
        if mode != 0o640 or st.st_uid != 0 or gr_name != "shadow":
            return (2, "CRITICAL - /etc/gshadow n'est pas en 0640 root:shadow")
        return (0, "OK - /etc/gshadow est en 0640 root:shadow")
    except Exception as e:
        return (3, f"UNKNOWN - Erreur : {e}")

def main():
    code, message = check_measure()
    print(message)
    sys.exit(code)

if __name__ == "__main__":
    main()

