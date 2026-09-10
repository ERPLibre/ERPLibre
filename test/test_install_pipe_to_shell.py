#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Ce qui est téléchargé puis EXÉCUTÉ doit d'abord avoir été obtenu.

« curl … | bash » est l'idiome de la moitié des installateurs. Sans « -f »,
curl rend 0 sur une erreur HTTP et livre le CORPS de l'erreur à bash, qui
l'exécute : une page de miroir en panne, un portail captif ou le 504 d'un
cache hors ligne devient une suite de commandes. Le lecteur reçoit alors
« command not found » et la cause véritable ne se lit plus nulle part.

Le contrôle porte sur la PROPRIÉTÉ et non sur un fichier : tout script du
dépôt qui tube un téléchargement dans un interpréteur doit demander à curl
d'échouer.
"""

import re
import sys
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

# « curl » suivi de ce qui n'est pas une nouvelle commande, jusqu'à un tube
# vers un interpréteur. Le « \\ » de continuation de ligne est traversé.
TUBE = re.compile(r"curl\s+((?:[^\n|;&]|\\\n)*?)\|\s*(?:sudo\s+)?(?:ba)?sh\b")


def demande_lechec(options: str) -> bool:
    """« -f » y est-il demandé, sous l'une de ses formes ?

    Les options courtes se GROUPENT : « -sSf » vaut « -s -S -f », et
    chercher le seul jeton « -f » manquerait la moitié des appels du dépôt.
    """
    for mot in options.split():
        if mot == "--fail" or mot.startswith("--fail-"):
            return True
        if mot.startswith("-") and not mot.startswith("--") and "f" in mot[1:]:
            return True
    return False


def scripts():
    for chemin in sorted(RACINE.glob("script/**/*.sh")):
        yield chemin, chemin.read_text(encoding="utf-8", errors="replace")


class TestUnTelechargementTubeDansUnShell(unittest.TestCase):
    def test_curl_doit_echouer_sur_une_erreur_http(self):
        fautifs = []
        for chemin, src in scripts():
            for options in TUBE.findall(src):
                if not demande_lechec(options):
                    fautifs.append(
                        f"{chemin.relative_to(RACINE)} : curl {options.strip()}"
                    )
        self.assertEqual(
            fautifs,
            [],
            "le corps d'une erreur HTTP y serait exécuté :\n  "
            + "\n  ".join(fautifs),
        )

    def test_les_options_groupees_sont_reconnues(self):
        """« -sSf » vaut « -s -S -f » : les traiter comme un seul jeton
        signalerait à tort la moitié des appels du dépôt."""
        for bon in ("-fsSL", "-sSf", "-f", "--fail", "--fail-with-body"):
            self.assertTrue(demande_lechec(f"{bon} https://x"), bon)
        for mauvais in ("-L", "-sSL", "", "--silent"):
            self.assertFalse(demande_lechec(f"{mauvais} https://x"), mauvais)

    def test_le_motif_trouve_bien_les_tubes_existants(self):
        """Une expression qui ne trouve rien passerait tous les contrôles.

        Le dépôt en porte plusieurs : si ce compte tombe à zéro, c'est
        l'expression qu'il faut relire, pas le dépôt qu'il faut féliciter.
        """
        trouves = sum(len(TUBE.findall(src)) for _c, src in scripts())
        self.assertGreaterEqual(trouves, 3, f"seulement {trouves} trouvés")


if __name__ == "__main__":
    unittest.main()
