#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Traduction de l'interface de l'installateur ERPLibre (fr, en).

Les phrases sont écrites en anglais dans le code, et l'anglais sert de
clé, comme dans script/todo/todo_i18n.py. Le français vient du catalogue
CATALOGUE_FILE, que build_iso.py écrit à côté de ce fichier : il y
recopie, depuis todo_i18n, la traduction de chaque phrase passée à tr()
ou marquée par N_() dans les modules de l'interface, plus celles du
profil machine (profile_messages, libellés et jetons de plan_summary).
todo_i18n reste ainsi la seule source des traductions.

Sans catalogue (dépôt non construit, fichier illisible), l'interface
parle anglais : une phrase manquante n'empêche jamais d'installer.

Bibliothèque standard seulement.
"""

import json
import os

LANGS = ("fr", "en")
DEFAULT_LANG = "fr"
CATALOGUE_FILE = "messages.fr.json"
CATALOGUE_VERSION = 1


def N_(text):
    """Marque `text` pour le catalogue sans le traduire : sert aux
    phrases rangées dans une table, traduites plus tard par tr()."""
    return text


def load_catalogue(path):
    """Le dict anglais → français du fichier `path` ; vide s'il manque,
    ne se lit pas ou n'a pas la version attendue."""
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return {}
    if not isinstance(doc, dict) or doc.get("version") != CATALOGUE_VERSION:
        return {}
    fr = doc.get("fr")
    return fr if isinstance(fr, dict) else {}


def pick_lang(*candidates):
    """La première langue reconnue parmi `candidates`, DEFAULT_LANG
    sinon."""
    for lang in candidates:
        if lang in LANGS:
            return lang
    return DEFAULT_LANG


class Translator:
    """tr(text, **champs) : `text` dans la langue courante, ses « {champ} »
    remplis. Un champ que la phrase nomme sans qu'on le donne vaut « ? »
    plutôt que de lever KeyError : une phrase de profil reçoit les
    détails tels que le code les porte."""

    def __init__(self, lang=DEFAULT_LANG, catalogue=None):
        self.lang = pick_lang(lang)
        self.catalogue = catalogue or {}

    def __call__(self, text, **champs):
        phrase = text
        if self.lang == "fr":
            phrase = self.catalogue.get(text) or text
        if champs:
            return phrase.format_map(_Default(champs))
        return phrase

    def toggled(self):
        """Le même catalogue dans l'autre langue."""
        autre = "en" if self.lang == "fr" else "fr"
        return Translator(autre, self.catalogue)


class _Default(dict):
    def __missing__(self, cle):
        return "?"


def translator(share_dir, lang):
    """Le Translator de `lang` avec le catalogue de `share_dir`."""
    return Translator(
        lang, load_catalogue(os.path.join(share_dir, CATALOGUE_FILE))
    )
