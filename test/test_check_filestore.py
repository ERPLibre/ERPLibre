#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Séparer ce qui est perdu de ce qui dort quelque part.

Deux propriétés portent l'outil. La première : un fichier retrouvé
ailleurs n'est PAS une perte, et le dire évite de pleurer sur 266
fichiers quand trois seulement ont disparu. La seconde : une pièce jointe
dont le champ n'existe plus n'a rien à récupérer — la ranger avec les
pertes serait faux dans l'autre sens.
"""

import io
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.analyse import check_filestore as fs  # noqa: E402
from script.todo import todo_i18n  # noqa: E402


def piece(store, model="", field="", res_id="1", name="x", size=1024):
    return {
        "store_fname": store,
        "model": model,
        "field": field,
        "res_id": res_id,
        "name": name,
        "size": size,
        "mimetype": "image/png",
        "created": "2019-11-30",
    }


class TestClassify(unittest.TestCase):
    VIVANTS = {"res.partner.image_1920"}

    def juge(self, p, present=(), ailleurs=None, niches=None, zips=None):
        return fs.classify(
            p,
            set(present),
            ailleurs or {},
            niches or {},
            zips or {},
            self.VIVANTS,
        )

    def test_a_present_file_is_not_a_finding(self):
        self.assertIsNone(self.juge(piece("aa/bb"), present=["aa/bb"]))

    def test_a_file_found_nowhere_is_lost(self):
        self.assertEqual(self.juge(piece("aa/bb")), ("lost", None))

    def test_a_file_in_another_filestore_is_recoverable(self):
        self.assertEqual(
            self.juge(piece("aa/bb"), ailleurs={"aa/bb": "autre_base"}),
            ("in_other_filestore", "autre_base"),
        )

    def test_a_file_in_a_backup_is_recoverable(self):
        self.assertEqual(
            self.juge(piece("aa/bb"), zips={"aa/bb": "sauvegarde.zip"}),
            ("in_backup", "sauvegarde.zip"),
        )

    def test_a_nested_file_is_named_as_such(self):
        # Le remettre en place est un DÉPLACEMENT, pas une copie depuis
        # une autre base : le geste diffère, la catégorie aussi.
        self.assertEqual(
            self.juge(piece("aa/bb"), niches={"aa/bb": "ma_base"}),
            ("nested", "ma_base"),
        )

    def test_a_dead_field_is_judged_BEFORE_looking_anywhere(self):
        # Rien ne lit cette ligne : proposer de la récupérer ferait
        # travailler pour rien. Testé d'abord, donc, même si le fichier
        # traîne dans une sauvegarde.
        verdict = self.juge(
            piece("aa/bb", model="res.country", field="image"),
            zips={"aa/bb": "sauvegarde.zip"},
        )
        self.assertEqual(verdict[0], "dead_field")

    def test_a_living_field_is_not_mistaken_for_a_dead_one(self):
        verdict = self.juge(
            piece("aa/bb", model="res.partner", field="image_1920")
        )
        self.assertEqual(verdict, ("lost", None))

    def test_an_attachment_without_a_field_is_never_dead(self):
        # Un document téléversé n'a pas de `res_field` : le juger sur un
        # champ absent le ferait disparaître du rapport.
        self.assertEqual(
            self.juge(piece("aa/bb", model="project.task"))[0], "lost"
        )

    def test_every_verdict_has_an_icon_and_a_wording(self):
        for verdict in fs.VERDICTS:
            self.assertIn(verdict, fs.ICONE)
            self.assertIn(verdict, fs.EXPLICATION)

    def test_the_lost_come_first_in_the_order(self):
        # L'ordre EST la gravité : ce qu'on ne peut pas récupérer se lit
        # d'abord.
        self.assertEqual(fs.VERDICTS[0], "lost")


class TestTheDataDir(unittest.TestCase):
    def test_it_is_read_from_the_config(self):
        with tempfile.NamedTemporaryFile(
            "w", suffix=".conf", delete=False, encoding="utf-8"
        ) as handle:
            handle.write("[options]\ndata_dir = /chemin/a/moi\n")
            chemin = handle.name
        try:
            self.assertEqual(fs.data_dir(chemin), "/chemin/a/moi")
        finally:
            os.unlink(chemin)

    def test_a_missing_config_falls_back_instead_of_crashing(self):
        # Deviner mal ferait déclarer TOUT perdu : le pire diagnostic.
        self.assertTrue(fs.data_dir("/nulle/part.conf"))


class TestScanning(unittest.TestCase):
    def setUp(self):
        self.racine = tempfile.mkdtemp()
        for base, chemin in (
            ("ma_base", "aa/present"),
            ("autre", "bb/ailleurs"),
            ("ma_base", "filestore/cc/niche"),
        ):
            complet = os.path.join(self.racine, base, chemin)
            os.makedirs(os.path.dirname(complet), exist_ok=True)
            with open(complet, "w", encoding="utf-8") as handle:
                handle.write("x")

    def tearDown(self):
        shutil.rmtree(self.racine)

    def test_other_filestores_are_indexed_and_mine_is_skipped(self):
        ailleurs, _n = fs.scan_filestores(self.racine, sauf="ma_base")
        self.assertEqual(ailleurs.get("bb/ailleurs"), "autre")
        self.assertNotIn("aa/present", ailleurs)

    def test_nested_files_are_indexed_under_their_logical_name(self):
        # C'est sous « cc/niche » qu'on les cherchera, pas sous
        # « filestore/cc/niche ».
        _a, niches = fs.scan_filestores(self.racine, sauf=None)
        self.assertEqual(niches.get("cc/niche"), "ma_base")

    def test_a_missing_root_is_empty_not_a_crash(self):
        self.assertEqual(fs.scan_filestores("/nulle/part"), ({}, {}))

    def test_backups_are_read_from_the_central_directory(self):
        dossier = tempfile.mkdtemp()
        try:
            chemin = os.path.join(dossier, "sauv.zip")
            with zipfile.ZipFile(chemin, "w") as archive:
                archive.writestr("filestore/dd/dedans", "x")
                archive.writestr("dump.sql", "x")
            trouves = fs.scan_backups(dossier)
            self.assertEqual(trouves.get("dd/dedans"), "sauv.zip")
            self.assertNotIn("dump.sql", trouves)
        finally:
            shutil.rmtree(dossier)

    def test_a_corrupt_zip_is_skipped_not_fatal(self):
        dossier = tempfile.mkdtemp()
        try:
            with open(os.path.join(dossier, "casse.zip"), "w") as handle:
                handle.write("pas un zip")
            self.assertEqual(fs.scan_backups(dossier), {})
        finally:
            shutil.rmtree(dossier)


class TestTheAudit(unittest.TestCase):
    """`audit` sans PostgreSQL ni disque : on éprouve la LOGIQUE."""

    def setUp(self):
        self.vrais = (
            fs.attachments,
            fs.live_fields,
            fs.scan_filestores,
            fs.scan_backups,
            fs.filestore_root,
        )
        fs.live_fields = lambda base: set()
        fs.scan_filestores = lambda racine, sauf=None: ({}, {})
        fs.scan_backups = lambda dossier: {}
        fs.filestore_root = lambda config=None: "/nulle/part"

    def tearDown(self):
        (
            fs.attachments,
            fs.live_fields,
            fs.scan_filestores,
            fs.scan_backups,
            fs.filestore_root,
        ) = self.vrais

    def test_two_attachments_sharing_a_file_count_once(self):
        # Odoo déduplique par empreinte : deux pièces jointes au contenu
        # identique partagent un `store_fname`. Les compter deux fois
        # gonflerait « fichiers absents » sans qu'un seul fichier de plus
        # soit à retrouver.
        fs.attachments = lambda base: [
            piece("aa/bb", "project.task", res_id="1"),
            piece("aa/bb", "project.task", res_id="2"),
        ]
        rapport = fs.audit("db")
        self.assertEqual(rapport["missing"], 1)
        self.assertEqual(len(rapport["groups"]["lost"]), 1)

    def test_distinct_files_are_counted_apart(self):
        fs.attachments = lambda base: [piece("aa/bb"), piece("cc/dd")]
        self.assertEqual(fs.audit("db")["missing"], 2)

    def test_a_silent_database_is_unavailable(self):
        fs.attachments = lambda base: None
        self.assertTrue(fs.audit("db")["unavailable"])

    def test_a_dead_field_never_lands_in_lost(self):
        # Le garde du champ disparu doit VRAIMENT couper : sans lui, ces
        # lignes gonfleraient les pertes réelles.
        fs.attachments = lambda base: [piece("aa/bb", "res.country", "image")]
        rapport = fs.audit("db")
        self.assertEqual(rapport["groups"]["lost"], [])
        self.assertEqual(len(rapport["groups"]["dead_field"]), 1)


class TestTheReport(unittest.TestCase):
    def rapport(self, **extra):
        base = {
            "database": "db",
            "attachments": 10,
            "files_present": 8,
            "missing": 0,
            "nested_total": 0,
            "root": "/x",
            "groups": {v: [] for v in fs.VERDICTS},
        }
        base.update(extra)
        return base

    def test_a_clean_filestore_says_so(self):
        texte = "\n".join(fs.render(self.rapport()))
        self.assertIn(todo_i18n.t("every attachment file is present"), texte)

    def test_only_the_lost_are_named_one_by_one(self):
        groupes = {v: [] for v in fs.VERDICTS}
        groupes["lost"] = [piece("a/1", "project.task", name="perdu.png")]
        groupes["in_backup"] = [
            piece("b/1", "res.country", "image", name="recuperable.png")
        ]
        texte = "\n".join(fs.render(self.rapport(missing=2, groups=groupes)))
        self.assertIn("perdu.png", texte)
        # Le récupérable est RÉSUMÉ, pas listé : trois cents lignes de
        # noms qu'on n'a pas à lire cacheraient les trois qui comptent.
        self.assertNotIn("recuperable.png", texte)
        self.assertIn("res.country / image", texte)

    def test_the_nested_pile_is_reported(self):
        texte = "\n".join(fs.render(self.rapport(nested_total=1168)))
        self.assertIn("1168", texte)

    def test_an_unreadable_database_renders_without_crashing(self):
        texte = "\n".join(fs.render({"unavailable": True, "database": "x"}))
        self.assertIn("x", texte)

    def test_summarise_groups_by_model_and_field(self):
        resume = fs.summarise(
            [
                piece("a/1", "res.country", "image"),
                piece("a/2", "res.country", "image"),
                piece("a/3", "project.task"),
            ]
        )
        self.assertIn("res.country / image × 2", resume)


class TestVerifyingARestore(unittest.TestCase):
    """Le contrôle d'après-restauration, celui qui aurait vu le nichage."""

    def setUp(self):
        self.racine = tempfile.mkdtemp()
        self.zip = os.path.join(self.racine, "sauv.zip")
        with zipfile.ZipFile(self.zip, "w") as archive:
            for nom in ("aa/un", "bb/deux", "cc/trois"):
                archive.writestr(f"filestore/{nom}", "x")
            archive.writestr("dump.sql", "x")
        self.fs = os.path.join(self.racine, "fs")
        self.vrai = fs.filestore_root
        fs.filestore_root = lambda config=None: self.fs

    def tearDown(self):
        fs.filestore_root = self.vrai
        shutil.rmtree(self.racine)

    def pose(self, chemins):
        for chemin in chemins:
            complet = os.path.join(self.fs, "ma_base", chemin)
            os.makedirs(os.path.dirname(complet), exist_ok=True)
            with open(complet, "w", encoding="utf-8") as handle:
                handle.write("x")

    def test_a_clean_restore_reports_everything_in_place(self):
        self.pose(["aa/un", "bb/deux", "cc/trois"])
        r = fs.verify_restore("ma_base", self.zip)
        self.assertEqual((r["expected"], r["placed"]), (3, 3))
        self.assertEqual((r["nested"], r["missing"]), (0, 0))

    def test_a_nested_restore_is_caught(self):
        # Le défaut exact qui a coûté 133 Mo par base, sept fois.
        self.pose(
            ["filestore/aa/un", "filestore/bb/deux", "filestore/cc/trois"]
        )
        r = fs.verify_restore("ma_base", self.zip)
        self.assertEqual(r["nested"], 3)
        self.assertEqual(r["placed"], 0)

    def test_a_half_nested_restore_counts_both_sides(self):
        self.pose(["aa/un", "filestore/bb/deux"])
        r = fs.verify_restore("ma_base", self.zip)
        self.assertEqual((r["placed"], r["nested"], r["missing"]), (1, 1, 1))

    def test_files_that_never_landed_are_counted(self):
        self.pose(["aa/un"])
        self.assertEqual(fs.verify_restore("ma_base", self.zip)["missing"], 2)

    def test_a_zip_without_a_filestore_says_nothing(self):
        # Se taire quand il n'y a rien à contrôler : un contrôle bavard
        # à chaque restauration finit par ne plus être lu.
        vide = os.path.join(self.racine, "vide.zip")
        with zipfile.ZipFile(vide, "w") as archive:
            archive.writestr("dump.sql", "x")
        r = fs.verify_restore("ma_base", vide)
        self.assertEqual(r["expected"], 0)
        self.assertEqual(fs.render_verify(r), [])

    def test_the_fix_command_names_the_real_directory(self):
        self.pose(["filestore/aa/un"])
        texte = "\n".join(
            fs.render_verify(fs.verify_restore("ma_base", self.zip))
        )
        self.assertIn(os.path.join(self.fs, "ma_base"), texte)
        self.assertIn(todo_i18n.t("To fix:"), texte)

    def test_a_clean_restore_still_says_so_briefly(self):
        self.pose(["aa/un", "bb/deux", "cc/trois"])
        texte = "\n".join(
            fs.render_verify(fs.verify_restore("ma_base", self.zip))
        )
        self.assertIn(todo_i18n.t("Filestore restored:"), texte)
        self.assertNotIn(todo_i18n.t("To fix:"), texte)


class TestTheRestoreWiring(unittest.TestCase):
    RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))

    def source(self, chemin):
        with io.open(
            os.path.join(self.RACINE, chemin), encoding="utf-8"
        ) as handle:
            return handle.read()

    def test_db_restore_checks_after_a_real_restore(self):
        src = self.source("script/database/db_restore.py")
        self.assertEqual(src.count("verify_filestore("), 3)
        self.assertIn(
            "if config.ignore_cache:\n        verify_filestore("
            "config.database",
            src,
            "le contrôle d'après-restauration directe n'est plus gardé"
            " par ignore_cache",
        )
        self.assertIn(
            "not config.ignore_cache:",
            src,
            "la création du cache n'est plus conditionnée",
        )

    def test_the_clone_path_is_NOT_checked(self):
        # Le miroir recopie sa source, défauts compris : contrôler là
        # dirait deux fois la même chose, et au mauvais endroit.
        src = self.source("script/database/db_restore.py")
        self.assertIn("--clone --from_database", src)
        debut = src.index("--clone --from_database")
        marque = "verify_filestore(config.database"
        self.assertIn(
            marque, src, "le contrôle d'après-restauration a disparu"
        )
        fin = src.index(marque, debut)
        self.assertNotIn("verify_filestore", src[debut:fin])

    def test_the_analyse_menu_offers_the_tool(self):
        src = self.source("script/todo/todo.py")
        self.assertIn("Attachment files missing from the filestore", src)
        self.assertIn("self.execute_analyse_filestore()", src)
        self.assertIn("def execute_analyse_filestore", src)

    def test_the_menu_has_as_many_entries_as_branches(self):
        src = self.source("script/todo/todo.py")
        debut = src.index("def prompt_execute_analyse")
        fin = src.index('print(t("Command not found !"))', debut)
        bloc = src[debut:fin]
        entrees = bloc.count('"prompt_description"')
        branches = sum(
            f'status == "{n}"' in bloc for n in range(1, entrees + 2)
        )
        self.assertEqual(entrees, branches)


class TestTheExitCodes(unittest.TestCase):
    def setUp(self):
        self.vrai = fs.audit

    def tearDown(self):
        fs.audit = self.vrai

    def lance(self, rapport):
        fs.audit = lambda *a, **k: rapport
        tampon = io.StringIO()
        with redirect_stdout(tampon):
            code = fs.main(["-d", "db"])
        return code, tampon.getvalue()

    def propre(self, **extra):
        base = {
            "database": "db",
            "attachments": 1,
            "files_present": 1,
            "missing": 0,
            "nested_total": 0,
            "root": "/x",
            "groups": {v: [] for v in fs.VERDICTS},
        }
        base.update(extra)
        return base

    def test_nothing_lost_exits_zero(self):
        code, _ = self.lance(self.propre())
        self.assertEqual(code, 0)

    def test_recoverable_only_still_exits_zero(self):
        # Rien à décider : tout se récupère. Sortir 1 ferait échouer une
        # chaîne make pour une situation saine.
        groupes = {v: [] for v in fs.VERDICTS}
        groupes["in_backup"] = [piece("a/1")]
        code, _ = self.lance(self.propre(missing=1, groups=groupes))
        self.assertEqual(code, 0)

    def test_a_real_loss_exits_one(self):
        groupes = {v: [] for v in fs.VERDICTS}
        groupes["lost"] = [piece("a/1")]
        code, _ = self.lance(self.propre(missing=1, groups=groupes))
        self.assertEqual(code, 1)

    def test_an_unreadable_database_exits_two(self):
        code, _ = self.lance({"unavailable": True, "database": "db"})
        self.assertEqual(code, 2)


class TestTranslations(unittest.TestCase):
    def test_every_key_exists(self):
        import ast

        with io.open(fs.__file__, encoding="utf-8") as handle:
            arbre = ast.parse(handle.read())
        cles = set(fs.EXPLICATION.values())
        for node in ast.walk(arbre):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "t"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                cles.add(node.args[0].value)
        for cle in cles:
            self.assertTrue(
                cle in todo_i18n.TRANSLATIONS, f"clé sans traduction : {cle!r}"
            )


if __name__ == "__main__":
    unittest.main()
