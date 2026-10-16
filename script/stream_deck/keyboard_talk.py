#!/usr/bin/env python3
# © 2021-2024 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import subprocess
import sys
import time

import keyboard

try:
    result = subprocess.run(
        ["wmctrl", "-l"], capture_output=True, text=True, check=True
    )
    lines = result.stdout.splitlines()
    for line in lines:
        if "Terminal" in line:
            window_id = line.split()[0]
            subprocess.run(["wmctrl", "-i", "-a", window_id], check=True)
            # return
            break
except subprocess.CalledProcessError as e:
    print(f"Error: {e}")
    sys.exit(0)
# time.sleep(1)
# modifiers = ['ctrl', 'alt', 'shift', 'windows']
# keyboard.send('windows+esc')
time.sleep(1)
keyboard.write(
    """
1
1
1
y
""",
    delay=0.5,
)
