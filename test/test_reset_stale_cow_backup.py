#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La sauvegarde doit pouvoir DÉFAIRE ce que la réinitialisation écrit.

« l'arch précédente est sauvegardée dans … » est une promesse, et la
promesse porte sur la colonne entière. Depuis 16.0, `arch_db` est un jsonb
d'une entrée par langue ; l'outil n'en déplie qu'une pour son analyse — la
structure est la même partout, et la structure est tout ce qu'il regarde —
mais l'UPDATE, lui, remplace la colonne complète. Sauvegarder la chaîne
dépliée annonçait donc une sauvegarde incapable de remettre les autres
langues.

Aucune base : `run_psql` est remplacé, et les épreuves portent sur ce qui
arrive au FICHIER.
"""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock
from unittest.mock import patch

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

from script.odoo.migration import reset_stale_cow_views as R  # noqa: E402

# Deux langues, et la seconde porte un texte que la première n'a pas : sans
# elle au fichier, la perte se voit.
COLONNE = json.dumps(
    {
        "en_US": '<t t-name="x"><div>Ours</div></t>',
        "fr_CA": '<t t-name="x"><div>Le nôtre</div></t>',
    }
)

LIGNE = {
    "id": 42,
    "key": "website_sale.product",
    "inherit_id": None,
    "website_id": 1,
    "active": True,
    "arch": COLONNE,
}


def lignes():
    """Ce que `fetch_views` rend pour cette seule vue."""
    with patch.object(R, "run_psql", lambda *a, **k: json.dumps([LIGNE])):
        return R.fetch_views("base-de-banc")


class TestLaSauvegardeRendLaColonneEntiere(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def sauvegarde(self):
        vue = lignes()[42]
        chemin = R.backup("base-de-banc", vue, self.tmp.name)
        with open(chemin, encoding="utf-8") as fh:
            return json.load(fh)

    def test_the_file_carries_every_language_the_column_held(self):
        """LA PROPRIÉTÉ : ce que le fichier porte doit pouvoir être réécrit
        dans la colonne. Une langue manquante ne se remet pas."""
        rendu = json.loads(self.sauvegarde()["arch_db"])
        self.assertEqual(
            json.loads(COLONNE),
            rendu,
            "la sauvegarde ne rend pas la colonne telle qu'elle était",
        )

    def test_it_also_keeps_the_unwrapped_one_to_be_read(self):
        """Le fichier s'ouvre pour re-appliquer la personnalisation à la
        main : du jsonb brut seul serait illisible."""
        self.assertIn("<t", self.sauvegarde()["arch"])

    def test_the_analysis_still_sees_one_language(self):
        """Contrôle : déplier reste ce que l'analyse attend, et la
        correction ne le change pas."""
        self.assertTrue(lignes()[42]["arch"].startswith("<t"))

    def test_a_text_column_is_saved_unchanged(self):
        """Jusqu'à 15.0 la colonne est du texte : la sauvegarde doit le
        rendre tel quel, sans l'enrober."""
        brut = '<t t-name="x"><div>Ours</div></t>'
        with patch.object(
            R, "run_psql", lambda *a, **k: json.dumps([dict(LIGNE, arch=brut)])
        ):
            vue = R.fetch_views("base-de-banc")[42]
        chemin = R.backup("base-de-banc", vue, self.tmp.name)
        with open(chemin, encoding="utf-8") as fh:
            self.assertEqual(brut, json.load(fh)["arch_db"])


class TestCeQueLeGesteDetruit(unittest.TestCase):
    """Le geste écrit la colonne ENTIÈRE : c'est ce qui rend la propriété
    ci-dessus obligatoire, et non un choix de format."""

    def test_the_reset_assigns_the_whole_column(self):
        lancees = []
        with patch.object(
            R, "run_psql", lambda db, sql: lancees.append(sql) or ""
        ):
            R.reset("base-de-banc", {"id": 42}, {"id": 7})
        (sql,) = lancees
        # La cible de l'affectation, et non l'orthographe de la requête :
        # ce qui compte est QUELLE colonne est remplacée.
        cible = sql.split("SET", 1)[1].split("=", 1)[0].strip()
        self.assertEqual("arch_db", cible)


class TestUneCleDesigneUneCopiePARSITE(unittest.TestCase):
    """`ir_ui_view` porte une ligne par site pour la même clé.

    « --reset <clé> » rendait la copie de plus petit identifiant et
    s'arrêtait là : les autres sites gardaient leur copie périmée et leur
    page restait cassée, sous un message qui nommait la CLÉ — c'est-à-dire
    l'ensemble entier.
    """

    #                 id   website_id   clé
    SITES = ((11, 1), (12, 2), (13, 3))
    CLE = "website_sale.product"

    def vues(self, arch_copie="<t>vieux</t>"):
        lignes = {
            7: {
                "id": 7,
                "key": self.CLE,
                "website_id": None,
                "arch": "<t>module</t>",
                "arch_column": "<t>module</t>",
                "inherit_id": None,
                "active": True,
            }
        }
        for vid, site in self.SITES:
            lignes[vid] = {
                "id": vid,
                "key": self.CLE,
                "website_id": site,
                "arch": arch_copie,
                "arch_column": arch_copie,
                "inherit_id": None,
                "active": True,
            }
        return lignes

    def test_every_site_copy_is_returned(self):
        copies, twin = R.find_copies_by_key(self.vues(), self.CLE)
        self.assertEqual(
            [vid for vid, _s in self.SITES], [c["id"] for c in copies]
        )
        self.assertEqual(7, twin["id"])

    def test_the_module_twin_is_the_one_without_a_site(self):
        _copies, twin = R.find_copies_by_key(self.vues(), self.CLE)
        self.assertIsNone(twin["website_id"])

    def test_an_unknown_key_returns_no_copy(self):
        copies, _twin = R.find_copies_by_key(self.vues(), "nulle.part")
        self.assertEqual([], copies)

    def test_the_order_is_stable(self):
        """L'écran les liste ; un ordre qui bouge ferait relire la liste à
        chaque exécution pour retrouver la même."""
        premier = [
            c["id"] for c in R.find_copies_by_key(self.vues(), self.CLE)[0]
        ]
        self.assertEqual(sorted(premier), premier)

    def test_the_reset_touches_every_one_of_them(self):
        """Le geste, et non seulement le relevé : c'est lui qui laissait
        des sites derrière."""
        import contextlib
        import io

        ecrits = []
        vues = self.vues()
        for nom, remplacant in (
            ("run_psql", lambda db, sql: ecrits.append(sql) or []),
            ("fetch_views", lambda db: vues),
            ("analyse", lambda db: []),
            ("backup", lambda db, c, d: "/dev/null"),
        ):
            avant = getattr(R, nom)
            setattr(R, nom, remplacant)
            self.addCleanup(setattr, R, nom, avant)
        argv = [
            "reset_stale_cow_views.py",
            "-d",
            "base",
            "--reset",
            self.CLE,
            "--apply",
        ]
        with mock.patch.object(sys, "argv", argv):
            with contextlib.redirect_stdout(io.StringIO()):
                R.main()
        # Une écriture par site, et chacune vise SON identifiant.
        for vid, _site in self.SITES:
            self.assertTrue(
                any(f"c.id = {vid}" in sql for sql in ecrits),
                f"le site {vid} n'a pas été réinitialisé",
            )


if __name__ == "__main__":
    unittest.main()
