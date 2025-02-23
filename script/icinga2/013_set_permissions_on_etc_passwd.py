#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tâche Ansible : "Set permissions on /etc/passwd"
Vérifie que /etc/passwd est en 0644 root:root.
"""

import sys
import os
import stat

def check_measure():
    path = "/etc/passwd"
    try:
        st = os.stat(path)
        mode = stat.S_IMODE(st.st_mode)
        if mode != 0o644 or st.st_uid != 0 or st.st_gid != 0:
            return (2, "CRITICAL - /etc/passwd n'est pas en 0644 root:root")
        return (0, "OK - /etc/passwd est en 0644 root:root")
    except FileNotFoundError:
        return (2, "CRITICAL - /etc/passwd introuvable")
    except Exception as e:
        return (3, f"UNKNOWN - Erreur : {e}")

def main():
    code, message = check_measure()
    print(message)
    sys.exit(code)

if __name__ == "__main__":
    main()

