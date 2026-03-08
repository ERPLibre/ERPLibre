"""
ERPLibre - Main pyinfra entry point.

Replaces: make install_os + install_dev
Usage:
    pyinfra @local pyinfra/deploy.py              # Full installation
    pyinfra @local pyinfra/deploy.py --dry         # Preview changes
    pyinfra inventory.py pyinfra/deploy.py         # On remote servers
"""

import os
import sys

# Add pyinfra/ directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from deploys.system import install_system_dependencies
from deploys.nodejs import install_nodejs
from deploys.wkhtmltopdf import install_wkhtmltopdf
from deploys.python_env import install_python_env

# Phase 1: System dependencies (replaces install_debian_dependency.sh)
install_system_dependencies()

# Phase 2: Node.js + npm packages
install_nodejs()

# Phase 3: wkhtmltopdf
install_wkhtmltopdf()

# Phase 4: Python environments + Poetry (replaces install_locally.sh)
install_python_env()
