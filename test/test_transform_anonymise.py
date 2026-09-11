#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""« Anonymiser une base Odoo ou une sauvegarde » : le DIALOGUE.

Ce qui est éprouvé ici est l'ORCHESTRATION, non PostgreSQL : quelle
provenance mène à quoi, dans quel ordre les trois gestes s'enchaînent —
restaurer, anonymiser, réexporter — et ce qu'un refus n'appelle pas.

`anonymize.py` a ses propres 79 tests, `_monitoring_write_flow` son
dialogue de confirmation. Les rejouer ici ferait deux endroits pour la
même règle. Ce fichier bouchonne donc tout ce qui touche le serveur, et
ne garde que les décisions du menu.
"""

import builtins
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from script.todo import todo_i18n  # noqa: E402


def _tm():
    """Le module du menu, importé au premier appel."""
    from script.todo import transform_menu

    return transform_menu


class _Execute:
    """`exec_command_live` bouchonné, et la trace des commandes."""

    def __init__(self, statut=0, sortie=()):
        self.commandes = []
        self.statut = statut
        self.sortie = list(sortie)

    def exec_command_live(self, commande, **_kw):
        self.commandes.append(commande)
        return self.statut, self.sortie


class _Bases:
    """Le gestionnaire de bases, réduit à ce que l'entrée lui demande."""

    def __init__(self, base="", zip_local="", distant=(1, "", "")):
        self.base = base
        self.zip_local = zip_local
        self.distant = distant
        self.appels = []

    def select_database(self):
        self.appels.append("select_database")
        return self.base

    def select_backup_path(self, start=None):
        self.appels.append("select_backup_path")
        return self.zip_local

    def download_database_backup_cli(self):
        self.appels.append("download")
        return self.distant


def _menu(**kw):
    """Le mixin, monté sur les aides que `TODO` lui fournit.

    Les aides d'oui/non sont PRISES sur la vraie classe : « o », « oui »,
    « y » et la différence entre un défaut oui et un défaut non sont sa
    règle, et une copie dériverait sans qu'un test le voie.
    """
    from script.todo.todo import TODO

    class Bouchon(_tm().TransformMenuMixin):
        _is_yes = staticmethod(TODO._is_yes)
        _is_yes_default_yes = staticmethod(TODO._is_yes_default_yes)

        def __init__(self):
            self.execute = kw.get("execute") or _Execute()
            self.db_manager = kw.get("db_manager") or _Bases()
            self.restaurations = []
            self.flots = []

        # Les deux emprunts à `TODO`, bouchonnés : ce qu'ils font est
        # éprouvé chez eux, ce qui compte ici est QUAND ils sont appelés.
        def _monitoring_restore(self, chemin):
            self.restaurations.append(chemin)
            return kw.get("restaure", "base_restauree")

        def _monitoring_write_flow(self, analyse, base):
            self.flots.append((analyse["key"], base))
            return kw.get("ecrit", True)

    return Bouchon()


class _Entrees:
    """`input()` bouchonné. Une question sans réponse LÈVE."""

    def __init__(self, *reponses):
        self.reponses = list(reponses)
        self.demandes = []

    def __call__(self, invite=""):
        self.demandes.append(invite)
        if not self.reponses:
            raise AssertionError(
                "question sans réponse : %r après %d"
                % (invite, len(self.demandes) - 1)
            )
        return self.reponses.pop(0)


class BaseDialogue(unittest.TestCase):
    """De quoi piloter le dialogue sans terminal."""

    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.base, True)
        self.sortie = io.StringIO()
        vrai = sys.stdout
        sys.stdout = self.sortie
        self.addCleanup(setattr, sys, "stdout", vrai)
        self.vrai_input = builtins.input
        self.addCleanup(setattr, builtins, "input", self.vrai_input)
        # Le registre vit sous `private/transform/` : le détourner évite
        # d'écrire dans le dépôt en lançant les tests.
        self.vraie_sortie = _tm().SORTIE_PAR_DEFAUT
        _tm().SORTIE_PAR_DEFAUT = os.path.join(self.base, "transform")
        self.addCleanup(setattr, _tm(), "SORTIE_PAR_DEFAUT", self.vraie_sortie)

    def _repondre(self, *reponses):
        entrees = _Entrees(*reponses)
        builtins.input = entrees
        return entrees

    def _prompt(self, *reponses):
        """`click.prompt` bouchonné : le choix de la provenance."""
        restes = list(reponses)
        vrai = _tm().click.prompt
        _tm().click.prompt = lambda *a, **k: restes.pop(0)
        self.addCleanup(setattr, _tm().click, "prompt", vrai)


class TestProvenance(BaseDialogue):
    """Quelle provenance mène à quoi."""

    def test_une_base_locale_ne_passe_PAS_par_une_restauration(self):
        """La base même est modifiée : rien à restaurer."""
        menu = _menu(db_manager=_Bases(base="prod_copie"))
        self._prompt("1")
        self.assertEqual(
            menu._transform_anonymise_source(), ("prod_copie", False)
        )
        self.assertEqual(menu.restaurations, [])

    def test_un_zip_local_passe_par_la_restauration(self):
        menu = _menu(
            db_manager=_Bases(zip_local="/tmp/sauvegarde.zip"),
            restaure="sauvegarde_neutralize",
        )
        self._prompt("2")
        self.assertEqual(
            menu._transform_anonymise_source(),
            ("sauvegarde_neutralize", True),
        )
        self.assertEqual(menu.restaurations, ["/tmp/sauvegarde.zip"])

    def test_un_telechargement_qui_ne_rend_rien_ne_restaure_pas(self):
        """Le refus vient AVANT la restauration : restaurer un fichier
        absent produirait une trace au lieu d'un message."""
        menu = _menu(db_manager=_Bases(distant=(0, "", "")))
        self._prompt("3")
        self.assertIsNone(menu._transform_anonymise_source())
        self.assertEqual(menu.restaurations, [])

    def test_zero_renonce(self):
        menu = _menu()
        self._prompt("0")
        self.assertIsNone(menu._transform_anonymise_source())

    def test_renoncer_au_choix_de_la_base_renonce_tout(self):
        menu = _menu(db_manager=_Bases(base=""))
        self._prompt("1")
        self.assertIsNone(menu._transform_anonymise_source())


class TestOrdreDesGestes(BaseDialogue):
    """Restaurer, anonymiser, réexporter — dans cet ordre et pas un autre."""

    def test_un_zip_est_restaure_PUIS_anonymise_PUIS_reexporte(self):
        execute = _Execute()
        menu = _menu(
            execute=execute,
            db_manager=_Bases(zip_local="/tmp/s.zip"),
            restaure="s_neutralize",
        )
        self._prompt("2")
        self._repondre("")  # le nom de la sauvegarde : le défaut
        menu._transform_anonymise_base()
        self.assertEqual(menu.restaurations, ["/tmp/s.zip"])
        self.assertEqual(menu.flots, [("anonymize", "s_neutralize")])
        self.assertEqual(len(execute.commandes), 1)
        self.assertIn("--backup", execute.commandes[0])
        self.assertIn("s_neutralize", execute.commandes[0])

    def test_une_base_locale_n_est_PAS_reexportee(self):
        """La base même est le résultat : il n'y a pas de zip à écrire."""
        execute = _Execute()
        menu = _menu(execute=execute, db_manager=_Bases(base="prod_copie"))
        self._prompt("1")
        menu._transform_anonymise_base()
        self.assertEqual(menu.flots, [("anonymize", "prod_copie")])
        self.assertEqual(execute.commandes, [])

    def test_une_base_locale_est_AVERTIE_avant_le_travail(self):
        menu = _menu(db_manager=_Bases(base="prod_copie"))
        self._prompt("1")
        menu._transform_anonymise_base()
        self.assertIn(
            todo_i18n.t("The database ITSELF is modified; no copy."),
            self.sortie.getvalue(),
        )

    def test_un_renoncement_ne_tire_AUCUNE_sauvegarde(self):
        """C'était le pire des deux mondes : l'opérateur croyait tenir
        une copie transmissible et tenait l'original.

        `_monitoring_write_flow` rend faux quand rien n'a été écrit — mode
        refusé, marche à blanc en erreur, nom mal retapé — et la
        sauvegarde ne se tire que sur un vrai.
        """
        execute = _Execute()
        menu = _menu(
            execute=execute,
            db_manager=_Bases(zip_local="/tmp/s.zip"),
            restaure="s_neutralize",
            ecrit=False,
        )
        self._prompt("2")
        menu._transform_anonymise_base()
        self.assertEqual(menu.flots, [("anonymize", "s_neutralize")])
        self.assertEqual(execute.commandes, [])
        rendu = self.sortie.getvalue()
        self.assertIn(
            todo_i18n.t("Nothing was written; no backup was drawn."), rendu
        )
        self.assertIn(todo_i18n.t("Database kept: "), rendu)

    def test_la_base_restauree_est_INSCRITE_meme_sur_un_renoncement(self):
        """Elle existe sur le serveur : c'est précisément celle-là qu'il
        faut pouvoir retrouver."""
        menu = _menu(
            db_manager=_Bases(zip_local="/tmp/s.zip"),
            restaure="s_neutralize",
            ecrit=False,
        )
        self._prompt("2")
        menu._transform_anonymise_base()
        self.assertEqual(
            [b["base"] for b in menu._transform_bases_lues()],
            ["s_neutralize"],
        )

    def test_renoncer_a_la_provenance_n_appelle_RIEN(self):
        execute = _Execute()
        menu = _menu(execute=execute)
        self._prompt("0")
        menu._transform_anonymise_base()
        self.assertEqual(menu.flots, [])
        self.assertEqual(execute.commandes, [])


class TestExportDuZip(BaseDialogue):
    """Le zip de sortie : son nom, et ce qui n'est jamais écrasé."""

    def test_le_defaut_porte_le_nom_de_la_base_et_l_horodatage(self):
        execute = _Execute()
        menu = _menu(execute=execute)
        self._repondre("")
        menu._transform_export_zip("s_neutralize")
        (commande,) = execute.commandes
        self.assertIn("--database s_neutralize", commande)
        self.assertIn("s_neutralize_anon_", commande)

    def test_un_nom_tape_l_emporte(self):
        execute = _Execute()
        menu = _menu(execute=execute)
        self._repondre("livraison_2026")
        menu._transform_export_zip("s")
        self.assertIn("--restore_image livraison_2026", execute.commandes[0])

    def test_le_suffixe_zip_tape_n_est_pas_doublé(self):
        """`--restore_image` prend un nom, non un chemin : « .zip » y
        ferait un fichier « .zip.zip »."""
        execute = _Execute()
        menu = _menu(execute=execute)
        self._repondre("livraison.zip")
        menu._transform_export_zip("s")
        self.assertIn("--restore_image livraison ", execute.commandes[0] + " ")

    def test_un_echec_de_la_sauvegarde_est_DIT(self):
        execute = _Execute(statut=1)
        menu = _menu(execute=execute)
        self._repondre("")
        menu._transform_export_zip("s")
        self.assertNotIn(
            todo_i18n.t("Backup written: "), self.sortie.getvalue()
        )

    def test_le_bilan_dit_les_trois_choses(self):
        execute = _Execute()
        menu = _menu(execute=execute)
        self._repondre("")
        menu._transform_export_zip("s_neutralize")
        rendu = self.sortie.getvalue()
        self.assertIn(todo_i18n.t("Backup written: "), rendu)
        self.assertIn(todo_i18n.t("The original was not modified."), rendu)
        self.assertIn(todo_i18n.t("Database kept: "), rendu)


class TestRegistreDesBases(BaseDialogue):
    """Le serveur ne dit pas QUI a créé une base : le registre le dit."""

    def test_une_base_produite_est_inscrite(self):
        menu = _menu()
        menu._transform_noter_base("s_neutralize", True)
        (inscrite,) = menu._transform_bases_lues()
        self.assertEqual(inscrite["base"], "s_neutralize")
        self.assertTrue(inscrite["depuis_zip"])
        self.assertTrue(inscrite["date"])

    def test_deux_passages_sur_la_meme_base_n_en_font_qu_une(self):
        menu = _menu()
        menu._transform_noter_base("s", True)
        menu._transform_noter_base("s", False)
        inscrites = menu._transform_bases_lues()
        self.assertEqual(len(inscrites), 1)
        self.assertFalse(inscrites[0]["depuis_zip"])

    def test_un_registre_ABIME_ne_fait_pas_lever(self):
        """Il est un confort, comme la mémoire de lot : le perdre vaut
        mieux que perdre le travail."""
        menu = _menu()
        os.makedirs(_tm().SORTIE_PAR_DEFAUT, exist_ok=True)
        chemin = os.path.join(_tm().SORTIE_PAR_DEFAUT, "bases.json")
        for contenu in ('{"pas": "une liste"', "[1, 2, 3]", ""):
            with self.subTest(contenu=contenu):
                with open(chemin, "w", encoding="utf-8") as flux:
                    flux.write(contenu)
                self.assertEqual(menu._transform_bases_lues(), [])
                menu._transform_noter_base("s", True)

    def test_un_registre_absent_rend_une_liste_vide(self):
        self.assertEqual(_menu()._transform_bases_lues(), [])


class TestBasesProduites(BaseDialogue):
    """L'entrée qui les liste."""

    def _peupler(self, menu, *noms):
        for nom in noms:
            menu._transform_noter_base(nom, True)

    def test_un_registre_vide_le_dit(self):
        _menu()._transform_bases_produites()
        self.assertIn(todo_i18n.t("Empty file."), self.sortie.getvalue())

    def test_une_base_VIVANTE_est_listee(self):
        menu = _menu(execute=_Execute(sortie=["s_neutralize", "autre"]))
        self._peupler(menu, "s_neutralize")
        menu._transform_bases_produites()
        self.assertIn("s_neutralize", self.sortie.getvalue())

    def test_une_base_DISPARUE_est_dite_a_part(self):
        """Détruite ailleurs — par Database, par un db_drop_all — elle ne
        doit pas être proposée à l'effacement."""
        menu = _menu(execute=_Execute(sortie=["autre"]))
        self._peupler(menu, "s_neutralize")
        menu._transform_bases_produites()
        rendu = self.sortie.getvalue()
        self.assertIn(
            todo_i18n.t("Gone already, only in the register:"), rendu
        )

    def test_un_serveur_injoignable_ne_declare_RIEN_disparu(self):
        """Une liste vide et une ignorance ne se confondent pas : sans
        serveur, tout le registre paraîtrait détruit."""
        menu = _menu(execute=_Execute(statut=1))
        self._peupler(menu, "s_neutralize")
        menu._transform_bases_produites()
        rendu = self.sortie.getvalue()
        self.assertIn(
            todo_i18n.t("Gone already, only in the register:"), rendu
        )
        self.assertNotIn(todo_i18n.t("Use Database to drop one."), rendu)


if __name__ == "__main__":
    unittest.main()
