# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Traduire les chaînes du noyau dans la langue que choisit l'appelant.

La langue est un paramètre, jamais lue dans un fichier ni dans
l'environnement : `t(key, lang)` pour un appel, `using_lang(lang)` pour un
bloc, sinon la langue par défaut que pose `configure`, le français
(DEFAULT_LANG) tant que rien n'est configuré. Les textes viennent de
`catalog.CATALOG` ; un traducteur injecté par `configure` peut les
remplacer.
"""

import contextlib
import contextvars
from collections.abc import Callable, Iterator

from erplibre_mail_core.catalog import CATALOG  # noqa: F401

LANGS: tuple[str, ...] = ("fr", "en")
# La langue sans configuration ni contexte, et celle d'un code vide ou
# inconnu.
DEFAULT_LANG = "fr"
# La langue d'une entrée privée de celle qu'on demande.
FALLBACK_LANG = "fr"
Translator = Callable[[str, str], "str | None"]

# Marque d'un argument omis de `configure`, distinct de None (qui remet le
# défaut).
_KEEP = object()

# La langue du bloc `using_lang` en cours, propre à chaque fil et à chaque
# tâche asyncio ; None hors de tout bloc.
_LANG: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "erplibre_mail_core_lang", default=None
)
# Réglages du processus : la langue par défaut (un code, ou une fonction
# sans argument relue à chaque appel) et le traducteur injecté.
_default: "str | Callable[[], str]" = DEFAULT_LANG
_translator: Translator | None = None


def normalize_lang(code: str | None) -> str:
    """Le code de langue du catalogue pour `code` : la partie avant le
    premier `_`, `-` ou `.`, en minuscules (`fr_CA`, `fr-CA`, `FR`,
    `fr_FR.UTF-8` → `fr`) ; DEFAULT_LANG pour un code vide ou inconnu."""
    if not code:
        return DEFAULT_LANG
    base = str(code)
    for sep in ("_", "-", "."):
        base = base.split(sep, 1)[0]
    base = base.lower()
    return base if base in LANGS else DEFAULT_LANG


def lookup(key: str, lang: str) -> str:
    """Le texte de `key` dans `lang`, lu dans le catalogue seul : celui de
    FALLBACK_LANG quand l'entrée n'a pas `lang`, la clé elle-même quand le
    catalogue ne la connaît pas."""
    entry = CATALOG.get(key)
    if entry is None:
        return key
    return entry.get(lang, entry.get(FALLBACK_LANG, key))


def current_lang() -> str:
    """La langue en vigueur : celle du bloc `using_lang` en cours, sinon la
    langue par défaut configurée (une fonction est appelée à chaque fois),
    normalisée."""
    lang = _LANG.get()
    if lang is None:
        lang = _default() if callable(_default) else _default
    return normalize_lang(lang)


def t(key: str, lang: str | None = None) -> str:
    """Le texte de `key` dans `lang`, ou dans la langue en vigueur.

    Un traducteur configuré répond d'abord ; s'il rend None, le catalogue
    répond. Une exception du traducteur traverse.
    """
    code = normalize_lang(lang) if lang else current_lang()
    if _translator is not None:
        rendu = _translator(key, code)
        if rendu is not None:
            return rendu
    return lookup(key, code)


@contextlib.contextmanager
def using_lang(lang: str | None) -> Iterator[str]:
    """Pose la langue de `t` pour la durée du bloc et cède son code
    normalisé ; les blocs s'imbriquent, chaque fil et chaque tâche asyncio
    garde la sienne."""
    code = normalize_lang(lang)
    jeton = _LANG.set(code)
    try:
        yield code
    finally:
        _LANG.reset(jeton)


def configure(*, default_lang=_KEEP, translator=_KEEP) -> dict:
    """Règle la langue par défaut et le traducteur du processus.

    Un argument omis reste tel quel ; None remet le défaut (DEFAULT_LANG,
    aucun traducteur). `default_lang` est un code ou une fonction sans
    argument, relue à chaque traduction. Rend le réglage précédent, que
    `configure(**precedent)` repose tel quel.
    """
    global _default, _translator
    precedent = {"default_lang": _default, "translator": _translator}
    if default_lang is not _KEEP:
        _default = DEFAULT_LANG if default_lang is None else default_lang
    if translator is not _KEEP:
        _translator = translator
    return precedent
