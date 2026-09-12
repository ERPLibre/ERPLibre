#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le lecteur du journal d'accès : ce qu'il montre, et ce qu'il tait.

La flèche est ce qui se lit sous une coupure : une requête sortie vers
l'internet est la seule chose qu'un déploiement hors ligne ne doit jamais
produire.
"""

import io
import json
import sys
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from script.qemu import cache_journal  # noqa: E402


def _ligne(**kw):
    d = {
        "time": "2026-09-12T04:47:09Z",
        "method": "GET",
        "url": "http://miroir.invalid/ubuntu/pool/main/x/xz_5.6_amd64.deb",
        "class": "immutable",
        "outcome": "hit",
        "status": 200,
        "bytes": 2048,
        "upstream": False,
        "client": "192.168.0.2",
    }
    d.update(kw)
    return json.dumps(d)


class TestLaMiseEnForme(unittest.TestCase):
    def test_une_requete_servie_du_disque_ne_porte_pas_la_fleche(self):
        ligne = cache_journal.ligne_lisible(_ligne())
        self.assertIn("·", ligne)
        self.assertNotIn("↑", ligne)
        self.assertIn("04:47:09", ligne)
        self.assertIn("192.168.0.2", ligne)
        self.assertIn("xz_5.6_amd64.deb", ligne)

    def test_une_requete_sortie_porte_la_fleche(self):
        """La seule chose qu'un déploiement hors ligne ne doit pas produire."""
        self.assertIn("↑", cache_journal.ligne_lisible(_ligne(upstream=True)))

    def test_une_ligne_illisible_est_passee(self):
        """Le journal s'écrit pendant qu'on le lit : sa dernière ligne est
        parfois tronquée."""
        for brut in ('{"time": "2026-09', "", "\n", "[]", None):
            self.assertEqual(cache_journal.ligne_lisible(brut), "")

    def test_sans_corps_la_taille_est_un_tiret(self):
        ligne = cache_journal.ligne_lisible(_ligne(bytes=0, status=504))
        self.assertIn("504", ligne)
        self.assertIn("-", ligne)

    def test_une_ligne_sans_client_reste_lisible(self):
        d = json.loads(_ligne())
        del d["client"]
        self.assertIn("—", cache_journal.ligne_lisible(json.dumps(d)))


class TestLeFiltreDeLAmont(unittest.TestCase):
    def test_amont_ne_garde_que_ce_qui_est_sorti(self):
        self.assertEqual(
            cache_journal.ligne_lisible(_ligne(), amont_seul=True), ""
        )
        self.assertNotEqual(
            cache_journal.ligne_lisible(
                _ligne(upstream=True), amont_seul=True
            ),
            "",
        )

    def test_le_filtre_se_demande_en_ligne_de_commande(self):
        entree = io.StringIO(
            _ligne() + "\n" + _ligne(upstream=True) + "\n" + _ligne() + "\n"
        )
        sortie = io.StringIO()
        self.assertEqual(
            cache_journal.main(["--amont"], entree, sortie),
            0,
        )
        self.assertEqual(len(sortie.getvalue().splitlines()), 1)


class TestLeFluxSansFin(unittest.TestCase):
    """« tail -f » ne rend jamais la main : ce qui est lu doit sortir tout de
    suite, sans quoi l'écran reste vide pendant des minutes."""

    def test_chaque_ligne_est_vidangee_aussitot(self):
        vidanges = []

        class Sortie(io.StringIO):
            def flush(self):
                vidanges.append(self.getvalue().count("\n"))

        sortie = Sortie()
        cache_journal.main(
            [], io.StringIO(_ligne() + "\n" + _ligne() + "\n"), sortie
        )
        self.assertEqual(vidanges, [1, 2])


if __name__ == "__main__":
    unittest.main()
