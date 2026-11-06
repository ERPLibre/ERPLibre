#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Rend le noyau des règles importable et le branche sur le client :
chemin, catalogue, langue et traducteur. Idempotent ; l'importer AVANT tout
module du noyau.
"""

import sys
from pathlib import Path

# Le noyau est un projet à part, `script/lib/erplibre_mail_core`, pour
# s'installer aussi dans le venv d'Odoo. Il s'importe par ce répertoire,
# sous le nom `erplibre_mail_core`, jamais comme `script.lib.…` : ce
# second nom chargerait une seconde copie de chaque module, et un
# `mock.patch` posé sur l'une manquerait l'autre. Le répertoire passe EN
# TÊTE de `sys.path` : le client prend toujours le noyau de son propre
# checkout, même si une autre copie est installée dans le venv.
_NOYAU = str(
    Path(__file__).resolve().parents[2] / "lib" / "erplibre_mail_core"
)
if _NOYAU not in sys.path:
    sys.path.insert(0, _NOYAU)

from erplibre_mail_core import i18n as _noyau_i18n  # noqa: E402

from script.todo import todo_i18n as _todo_i18n  # noqa: E402


def _traduire(key: str, lang: str) -> str | None:
    """Le texte de `key` dans `lang` lu dans `TRANSLATIONS` à chaque
    appel, sous la forme exacte de `todo_i18n.t` ; None pour une clé
    absente, que le catalogue du noyau sert alors."""
    entry = _todo_i18n.TRANSLATIONS.get(key)
    if entry is None:
        return None
    return entry.get(lang, entry.get("fr", key))


# Le catalogue du noyau rejoint celui du client ; le noyau parle la langue
# du client et lit ses textes, l'une et les autres relus à chaque
# traduction. Un client ouvert avant la mise à jour garde en mémoire un
# `todo_i18n` sans `register_catalog` : le catalogue n'y ajoute alors que
# ses clés absentes, sans remplacer un texte du client.
_enregistrer = getattr(_todo_i18n, "register_catalog", None)
if _enregistrer is not None:
    _enregistrer(_noyau_i18n.CATALOG)
else:
    for _cle, _entree in _noyau_i18n.CATALOG.items():
        _todo_i18n.TRANSLATIONS.setdefault(_cle, _entree)
_noyau_i18n.configure(
    default_lang=lambda: _todo_i18n.get_lang(), translator=_traduire
)
