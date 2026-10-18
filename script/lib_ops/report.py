# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le rapport d'une opération : étapes numérotées et verdicts.

Cinq formes de ligne, une par nature de message :

    ▶ [2/5] titre        une étape commence
      ✔ message          ce qui a réussi
      ⚠ [ATTN] message   ce qui mérite un regard sans faire échouer
      ✖ [FAIL] message   ce qui fait échouer l'opération
      – [SKIP] message   ce qui n'a pas été vérifié, et pourquoi

`[ATTN]`, `[FAIL]` et `[SKIP]` sont écrits en toutes lettres et pas seulement en
couleur : une sortie lue dans un journal, un courriel ou un terminal sans
couleur doit dire la même chose. La couleur n'est émise que vers un
terminal, et `NO_COLOR` l'éteint (https://no-color.org).

Tout part sur le flux donné (stdout par défaut), y compris les échecs :
c'est le déroulé de l'opération, lu d'un seul tenant. Seules les erreurs
d'usage, qui empêchent l'opération de commencer, vont sur stderr.

L'écriture est au mieux : un flux qui ne reçoit plus (terminal raccroché,
qui rend EIO ; tube refermé, BrokenPipeError ; flux fermé, ValueError)
fait perdre la ligne sans lever. Un rapport ne doit jamais interrompre ce
qu'il décrit — un service arrêté resterait arrêté.

Bibliothèque standard seulement.
"""

from __future__ import annotations

import os
import sys

GRAS_CYAN = "\033[1;36m"
VERT = "\033[1;32m"
JAUNE = "\033[1;33m"
ROUGE = "\033[1;31m"
GRIS = "\033[0;90m"
FIN = "\033[0m"

# Largeur des étiquettes de champ : aligne les valeurs en colonne.
LARGEUR_CHAMP = 13


def couleur_permise(flux):
    """True si `flux` est un terminal et que NO_COLOR n'est pas posé."""
    if os.environ.get("NO_COLOR"):
        return False
    isatty = getattr(flux, "isatty", None)
    try:
        return bool(isatty and isatty())
    except (OSError, ValueError):
        return False


class Rapport:
    """Écrit les lignes d'une opération sur un flux.

    `total` est le nombre d'étapes annoncé dans `[i/total]` ; il peut être
    fixé après coup (`total = n`), quand le nombre d'étapes dépend d'un
    état lu au début de l'exécution.
    """

    def __init__(self, flux=None, couleur=None, total=0, erreurs=None):
        self.flux = flux if flux is not None else sys.stdout
        self.erreurs = erreurs if erreurs is not None else sys.stderr
        self.couleur = (
            couleur_permise(self.flux) if couleur is None else bool(couleur)
        )
        self.total = total
        self.rang = 0

    def _peindre(self, code, texte):
        if not self.couleur:
            return texte
        return f"{code}{texte}{FIN}"

    def _ecrire(self, ligne, flux=None):
        """Écrit `ligne` ; une erreur du flux est avalée (voir l'en-tête)."""
        flux = flux if flux is not None else self.flux
        try:
            print(ligne, file=flux, flush=True)
        except (OSError, ValueError):
            pass

    def etape(self, titre):
        """Ouvre l'étape suivante et rend son rang."""
        self.rang += 1
        total = self.total if self.total >= self.rang else self.rang
        self._ecrire(
            self._peindre(GRAS_CYAN, f"▶ [{self.rang}/{total}] {titre}")
        )
        return self.rang

    def ok(self, message):
        self._ecrire(f"  {self._peindre(VERT, '✔')} {message}")

    def attn(self, message):
        self._ecrire(self._peindre(JAUNE, f"  ⚠ [ATTN] {message}"))

    def fail(self, message):
        self._ecrire(self._peindre(ROUGE, f"  ✖ [FAIL] {message}"))

    def skip(self, message):
        self._ecrire(self._peindre(GRIS, f"  – [SKIP] {message}"))

    def detail(self, message):
        self._ecrire(self._peindre(GRIS, f"    {message}"))

    def extrait(self, lignes, limite=10, largeur=300):
        """Montre au plus `limite` lignes, chacune coupée à `largeur`."""
        for ligne in list(lignes)[:limite]:
            self._ecrire(f"        {ligne.rstrip()[:largeur]}")

    def sim(self, message):
        self._ecrire(f"  (simulation) {message}")

    def champ(self, etiquette, valeur):
        self._ecrire(f"  {etiquette:<{LARGEUR_CHAMP}} {valeur}")

    def texte(self, message=""):
        self._ecrire(message)

    def erreur(self, message):
        """Erreur d'usage, sur stderr : l'opération n'a pas commencé."""
        self._ecrire(f"❌ {message}", flux=self.erreurs)
