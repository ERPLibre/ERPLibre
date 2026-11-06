#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ancien chemin de `erplibre_mail_core.rules.regex_worker`.

Le module se remplace, dans `sys.modules`, par celui du noyau :
`script.todo.mail.rules.regex_worker` et
`erplibre_mail_core.rules.regex_worker` sont le même objet, et un
`mock.patch` posé sur l'un vaut pour l'autre.
"""

import sys

from script.todo.mail import _core_path  # noqa: F401

# isort: split
from erplibre_mail_core.rules import regex_worker

sys.modules[__name__] = regex_worker
