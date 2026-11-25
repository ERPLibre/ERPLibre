#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le formulaire Textual des réglages : logique pure, puis l'application.

La logique (`lire_saisie`, `assembler`) rend le profil et les erreurs
sans Textual. L'application est pilotée dans un terminal simulé
(`run_test`) : une saisie refusée affiche son erreur et rend
« Enregistrer » inactif, `ctrl+s` rend le document, `esc` annule, et un
champ secret n'a AUCUN widget de saisie — seulement son état et deux
cases. Les valeurs sont inventées (`odoo-exemple.service`, `exemple_db`).
"""

import os
import sys
import unittest
from pathlib import Path

RACINE_DEPOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE_DEPOT))
sys.path.insert(0, str(RACINE_DEPOT / "test"))
sys.argv = ["todo.py"]

from async_case import AsyncCase  # noqa: E402
from profil_isole import profil_isole  # noqa: E402

from script.lib_ops import profil  # noqa: E402
from script.todo import ops_settings, todo_i18n  # noqa: E402
from script.todo.ops_settings_form import (  # noqa: E402
    Contexte,
    assembler,
    entrees,
    lire_saisie,
    run_settings_form,
    valeur_initiale,
)

SERVICE = "odoo-exemple.service"
REFERENCE = f"ERPLibre/Production/{SERVICE}/warmup.api_key"
CATALOGUE = None


def setUpModule():
    global CATALOGUE
    profil_isole()
    CATALOGUE = ops_settings.charger_catalogue()


def contexte(doc=None, coffre=True, etats=None):
    base = {"version": profil.VERSION, "service": SERVICE}
    base.update(doc or {})
    return Contexte(
        catalogue=CATALOGUE,
        doc=base,
        chemin=os.path.join("/srv/exemple", SERVICE + ".json"),
        nom=SERVICE,
        etats_secrets=etats or {},
        coffre_configure=coffre,
    )


def index_de(ctx, groupe, cle):
    for index, champ in entrees(ctx):
        if (champ.groupe, champ.cle) == (groupe, cle):
            return index
    raise KeyError((groupe, cle))


def saisies_initiales(ctx):
    return {
        index: valeur_initiale(champ, ctx.doc)
        for index, champ in entrees(ctx)
        if not champ.secret
    }


class TestLogique(unittest.TestCase):
    def test_une_entree_par_champ(self):
        ctx = contexte()
        self.assertEqual(
            len(entrees(ctx)),
            sum(len(c) for c in CATALOGUE.champs.values()),
        )

    def test_valeurs_initiales(self):
        ctx = contexte(
            {
                "backup": {"keep_daily": 10},
                "update_module": {"verbose": True, "ignore_error": ["a: b"]},
            }
        )
        self.assertEqual(
            valeur_initiale(
                ops_settings.champ_cible(CATALOGUE, "backup", "keep_daily"),
                ctx.doc,
            ),
            "10",
        )
        self.assertIs(
            valeur_initiale(
                ops_settings.champ_cible(
                    CATALOGUE, "update_module", "verbose"
                ),
                ctx.doc,
            ),
            True,
        )
        self.assertEqual(
            valeur_initiale(
                ops_settings.champ_cible(
                    CATALOGUE, "update_module", "ignore_error"
                ),
                ctx.doc,
            ),
            "a: b",
        )

    def test_lire_saisie(self):
        keep = ops_settings.champ_cible(CATALOGUE, "backup", "keep_daily")
        self.assertEqual(lire_saisie(keep, "10"), (10, None))
        self.assertEqual(lire_saisie(keep, " "), (None, None))
        brut, erreur = lire_saisie(keep, "²")
        self.assertIsNone(brut)
        self.assertTrue(erreur)
        motifs = ops_settings.champ_cible(CATALOGUE, "log_check", "ignore")
        self.assertEqual(
            lire_saisie(motifs, "a: b\n\nc: d\n"), (["a: b", "c: d"], None)
        )
        self.assertTrue(lire_saisie(motifs, ".*")[1])

    def test_assembler_sans_changement_rend_le_document(self):
        ctx = contexte(
            {"backup": {"keep_daily": 10}, "instance": {"db": "exemple_db"}}
        )
        doc, erreurs, a_definir, a_retirer = assembler(
            ctx, saisies_initiales(ctx), {}
        )
        self.assertEqual(doc, ctx.doc)
        self.assertEqual((erreurs, a_definir, a_retirer), ({}, [], []))

    def test_secret_defini_ou_retire_par_reference(self):
        ctx = contexte({"warmup": {"api_key_file": {"kdbx": REFERENCE}}})
        secret = index_de(ctx, "warmup", "api_key_file")
        doc, _e, a_definir, a_retirer = assembler(
            ctx, saisies_initiales(ctx), {secret: (False, True)}
        )
        self.assertNotIn("warmup", doc)
        self.assertEqual(a_retirer, [REFERENCE])
        ctx = contexte()
        doc, _e, a_definir, _r = assembler(
            ctx, saisies_initiales(ctx), {secret: (True, False)}
        )
        self.assertEqual(doc["warmup"], {"api_key_file": {"kdbx": REFERENCE}})
        self.assertEqual(a_definir, [REFERENCE])

    def test_somme_des_retentions(self):
        ctx = contexte()
        saisies = saisies_initiales(ctx)
        for cle, valeur in (
            ("keep_daily", "1"),
            ("keep_weekly", "0"),
            ("keep_monthly", "0"),
            ("keep_recent_days", "0"),
        ):
            saisies[index_de(ctx, "backup", cle)] = valeur
        _doc, erreurs, _d, _r = assembler(ctx, saisies, {})
        self.assertIn(index_de(ctx, "backup", "keep_daily"), erreurs)


class TestFormulaire(AsyncCase):
    def setUp(self):
        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = "en"

    async def test_saisie_erreur_puis_enregistrement(self):
        from textual.widgets import Button, Input, Static

        ctx = contexte({"instance": {"db": "exemple_db"}})
        index = index_de(ctx, "backup", "keep_daily")
        app = run_settings_form(ctx, run_app=False)
        async with app.run_test(size=(160, 50)) as pilote:
            app._afficher_groupe(list(CATALOGUE.champs).index("backup"))
            champ = app.query_one(f"#w-{index}", Input)
            champ.focus()
            await pilote.press(*"²")
            await pilote.press("tab")
            await pilote.pause()
            erreur = app.query_one(f"#e-{index}", Static)
            self.assertTrue(str(erreur.render()).strip())
            self.assertTrue(app.query_one("#enregistrer", Button).disabled)
            champ.focus()
            await pilote.press("backspace", *"10", "tab")
            await pilote.pause()
            self.assertFalse(str(erreur.render()).strip())
            self.assertFalse(app.query_one("#enregistrer", Button).disabled)
            await pilote.press("ctrl+s")
            await pilote.pause()
        self.assertIsNotNone(app.resultat)
        self.assertEqual(app.resultat.doc["backup"], {"keep_daily": 10})
        self.assertEqual(app.resultat.doc["instance"], {"db": "exemple_db"})

    async def test_echap_annule(self):
        app = run_settings_form(contexte(), run_app=False)
        async with app.run_test(size=(160, 50)) as pilote:
            await pilote.press("escape")
            await pilote.pause()
        self.assertIsNone(app.resultat)

    async def test_ctrl_r_remet_le_defaut(self):
        from textual.widgets import Input

        ctx = contexte({"log_check": {"days": 3}})
        index = index_de(ctx, "log_check", "days")
        app = run_settings_form(ctx, run_app=False)
        async with app.run_test(size=(160, 50)) as pilote:
            app._afficher_groupe(list(CATALOGUE.champs).index("log_check"))
            champ = app.query_one(f"#w-{index}", Input)
            champ.focus()
            await pilote.pause()
            await pilote.press("ctrl+r")
            await pilote.press("ctrl+s")
            await pilote.pause()
        self.assertNotIn("log_check", app.resultat.doc)

    async def test_aucun_widget_de_saisie_de_secret(self):
        from textual.widgets import Checkbox, Input, TextArea

        ctx = contexte(
            {"warmup": {"api_key_file": {"kdbx": REFERENCE}}},
            etats={("warmup", "api_key_file"): "kdbx"},
        )
        secrets = [i for i, c in entrees(ctx) if c.secret]
        self.assertTrue(secrets)
        app = run_settings_form(ctx, run_app=False)
        async with app.run_test(size=(160, 50)) as pilote:
            for index in secrets:
                ligne = app.query_one(f"#l-{index}")
                self.assertEqual(list(ligne.query(Input)), [])
                self.assertEqual(list(ligne.query(TextArea)), [])
                self.assertEqual(len(list(ligne.query(Checkbox))), 2)
            self.assertFalse(any(w.password for w in app.query(Input)))
            app.query_one(f"#d-{secrets[0]}", Checkbox).value = True
            await pilote.pause()
            await pilote.press("ctrl+s")
            await pilote.pause()
        self.assertEqual(app.resultat.secrets_a_definir, [REFERENCE])
        self.assertEqual(
            app.resultat.doc["warmup"], {"api_key_file": {"kdbx": REFERENCE}}
        )

    async def test_coffre_non_configure_case_inactive(self):
        from textual.widgets import Checkbox

        ctx = contexte(coffre=False)
        index = index_de(ctx, "warmup", "api_key_file")
        app = run_settings_form(ctx, run_app=False)
        async with app.run_test(size=(160, 50)):
            self.assertTrue(app.query_one(f"#d-{index}", Checkbox).disabled)


if __name__ == "__main__":
    unittest.main()
