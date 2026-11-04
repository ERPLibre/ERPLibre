#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les couleurs du TODO, et l'entrée « [0] Retour » de ses menus.

La couleur ne s'écrit que vers un terminal qui la montre : pas quand
NO_COLOR est défini (https://no-color.org), ni sous TERM=dumb, ni quand la
sortie n'est pas un terminal — un tube, un fichier, la capture d'un test y
reçoivent le texte nu. Le journal de session retire de toute façon les
séquences ANSI.
"""

import os
import sys

from script.todo.todo_i18n import t

# Bleu poudre (#B0E0E6) en couleur vraie ; le plus proche des 256 couleurs
# (152, #AFD7D7) pour un terminal qui n'annonce pas la couleur vraie.
BLEU_POUDRE_VRAI = "\x1b[38;2;176;224;230m"
BLEU_POUDRE_256 = "\x1b[38;5;152m"
FIN = "\x1b[0m"


def couleurs_actives(flux=None, environ=None):
    """Vrai quand `flux` (sys.stdout par défaut) montrera la couleur."""
    environ = os.environ if environ is None else environ
    if "NO_COLOR" in environ or environ.get("TERM") == "dumb":
        return False
    flux = sys.stdout if flux is None else flux
    try:
        return bool(flux.isatty())
    except (AttributeError, ValueError):
        return False


def bleu_poudre(texte, flux=None, environ=None):
    """`texte` en bleu poudre, ou tel quel quand la couleur ne s'affiche pas."""
    environ = os.environ if environ is None else environ
    if not couleurs_actives(flux, environ):
        return texte
    vraie = environ.get("COLORTERM", "").lower() in ("truecolor", "24bit")
    debut = BLEU_POUDRE_VRAI if vraie else BLEU_POUDRE_256
    return f"{debut}{texte}{FIN}"


def retour(libelle=None, flux=None, environ=None):
    """L'entrée « [0] 🔙 Retour » d'un menu, en bleu poudre.

    `libelle` vient du `t` de l'appelant : un module qui a son propre repli
    de traduction, ou un test qui remplace ce `t`, le voit respecté.
    """
    texte = f"[0] {t('Back') if libelle is None else libelle}"
    return bleu_poudre(texte, flux, environ)
