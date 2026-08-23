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


def piece(store, model="", field="", res_id="1", name="x", size=1024, pid="7"):
    return {
        "store_fname": store,
        "model": model,
        "id": pid,
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
        ailleurs, _n, _p = fs.scan_filestores(self.racine, sauf="ma_base")
        self.assertEqual(ailleurs.get("bb/ailleurs"), "autre")
        self.assertNotIn("aa/present", ailleurs)

    def test_nested_files_are_indexed_under_their_logical_name(self):
        # C'est sous « cc/niche » qu'on les cherchera, pas sous
        # « filestore/cc/niche ».
        _a, niches, _p = fs.scan_filestores(self.racine, sauf=None)
        self.assertEqual(niches.get("cc/niche"), "ma_base")

    def test_the_same_nested_file_in_two_databases_counts_in_BOTH(self):
        # Le clone recopie le nichage : un même fichier dort dans
        # plusieurs bases. L'index n'en retient qu'une — le premier
        # `setdefault` gagne, et l'ordre est alphabétique — donc la 17
        # s'entendait dire que le problème était chez les voisines.
        for base in ("aaa_base", "zzz_base"):
            complet = os.path.join(self.racine, base, "filestore", "ee", "x")
            os.makedirs(os.path.dirname(complet), exist_ok=True)
            with open(complet, "w", encoding="utf-8") as handle:
                handle.write("x")
        _a, _n, par_base = fs.scan_filestores(self.racine, sauf=None)
        self.assertEqual(par_base.get("aaa_base"), 1)
        self.assertEqual(par_base.get("zzz_base"), 1)

    def test_a_missing_root_is_empty_not_a_crash(self):
        self.assertEqual(fs.scan_filestores("/nulle/part"), ({}, {}, {}))

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
        fs.scan_filestores = lambda racine, sauf=None: ({}, {}, {})
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

    def test_every_row_sharing_a_dead_file_is_listed_for_deletion(self):
        # Vingt-deux lignes partageaient deux fichiers : la purge n'en
        # offrait qu'une à la fois, et il fallait la relancer vingt-deux
        # fois. Compter des FICHIERS et effacer des LIGNES ne sont pas la
        # même opération.
        fs.attachments = lambda base: [
            piece("aa/bb", "res.country", "image", res_id="1", pid="10"),
            piece("aa/bb", "res.country", "image", res_id="2", pid="11"),
            piece("cc/dd", "res.country", "image", res_id="3", pid="12"),
        ]
        rapport = fs.audit("db")
        self.assertEqual(rapport["missing"], 2)
        self.assertEqual(len(rapport["groups"]["dead_field"]), 2)
        self.assertEqual(sorted(rapport["dead_ids"]), [10, 11, 12])
        self.assertIn("(10, 11, 12)", fs.purge_dead_sql(rapport))

    def test_a_live_row_sharing_a_file_is_never_swept_along(self):
        # Deux lignes, un seul fichier, mais un seul champ mort : effacer
        # les deux emporterait une pièce jointe bien vivante.
        fs.live_fields = lambda base: {"project.task.attachment"}
        fs.attachments = lambda base: [
            piece("aa/bb", "res.country", "image", pid="10"),
            piece("aa/bb", "project.task", "attachment", pid="11"),
        ]
        rapport = fs.audit("db")
        self.assertEqual(rapport["dead_ids"], [10])

    def test_the_root_points_at_this_database_directory(self):
        # Y mettre la racine de tous les filestores faisait chercher le
        # dossier imbriqué à `<data_dir>/filestore/filestore` : l'outil
        # répondait « rien à ranger » devant 1168 fichiers échoués.
        fs.attachments = lambda base: []
        self.assertEqual(fs.audit("ma_base")["root"], "/nulle/part/ma_base")

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

    def test_limit_zero_shows_EVERYTHING(self):
        # « Tout afficher » passe limit=0. Une tranche [:0] est vide :
        # l'écran annonçait « … 3 de plus » et ne montrait rien du tout.
        groupes = {v: [] for v in fs.VERDICTS}
        groupes["lost"] = [
            piece(f"a/{i}", "project.task", name=f"perdu{i}.png")
            for i in range(3)
        ]
        texte = "\n".join(
            fs.render(self.rapport(missing=3, groups=groupes), limit=0)
        )
        for i in range(3):
            self.assertIn(f"perdu{i}.png", texte)
        self.assertNotIn(todo_i18n.t("more"), texte)

    def test_a_limit_still_caps_and_says_how_many_were_hidden(self):
        groupes = {v: [] for v in fs.VERDICTS}
        groupes["lost"] = [
            piece(f"a/{i}", "project.task", name=f"perdu{i}.png")
            for i in range(5)
        ]
        texte = "\n".join(
            fs.render(self.rapport(missing=5, groups=groupes), limit=2)
        )
        self.assertIn("perdu0.png", texte)
        self.assertNotIn("perdu4.png", texte)
        self.assertIn(f"3 {todo_i18n.t('more')}", texte)

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


class TestTheLivingRecord(unittest.TestCase):
    """Une image perdue sur un enregistrement supprimé n'est pas perdue."""

    def setUp(self):
        self.vrai = fs.run_psql
        self.demandes = []

    def tearDown(self):
        fs.run_psql = self.vrai

    def branche(self, tables, ids):
        def faux(base, sql):
            self.demandes.append(sql)
            if "to_regclass" in sql:
                return [["t" if any(x in sql for x in tables) else "f"]]
            return [[str(i)] for i in ids]

        fs.run_psql = faux

    def test_a_living_record_is_reported_as_such(self):
        self.branche(["project_task"], [15])
        vivants = fs.resources_alive(
            "db", [piece("a/1", "project.task", res_id="15")]
        )
        self.assertIs(vivants[("project.task", "15")], True)

    def test_a_deleted_record_is_reported_as_gone(self):
        self.branche(["project_task"], [])
        vivants = fs.resources_alive(
            "db", [piece("a/1", "project.task", res_id="15")]
        )
        self.assertIs(vivants[("project.task", "15")], False)

    def test_a_model_without_a_table_is_left_UNKNOWN(self):
        # « on n'a pas pu vérifier » ne doit pas se lire « il a disparu » :
        # une vraie perte serait classée en fausse alerte.
        self.branche([], [])
        vivants = fs.resources_alive(
            "db", [piece("a/1", "un.abstrait", res_id="1")]
        )
        self.assertEqual(vivants, {})

    def test_an_attachment_without_a_record_is_not_queried(self):
        self.branche([], [])
        fs.resources_alive("db", [piece("a/1")])
        self.assertEqual(self.demandes, [])

    def test_the_mark_says_all_three_states(self):
        self.assertIn(
            todo_i18n.t("record still exists"), fs.alive_mark({"alive": True})
        )
        self.assertIn(
            todo_i18n.t("record is gone — nothing will miss it"),
            fs.alive_mark({"alive": False}),
        )
        self.assertEqual(fs.alive_mark({"alive": None}), "")


class TestTheRepairs(unittest.TestCase):
    def rapport(self, ids=(), racine="/fs/db"):
        base = {v: [] for v in fs.VERDICTS}
        return {"root": racine, "groups": base, "dead_ids": list(ids)}

    def test_the_purge_deletes_by_id_only(self):
        # Par IDENTIFIANT, jamais par un domaine reconstruit : rejouer le
        # raisonnement en SQL ouvrirait la porte à effacer autre chose
        # que ce qui a été montré.
        sql = fs.purge_dead_sql(self.rapport([9, 3]))
        self.assertIn("WHERE id IN (3, 9)", sql)
        self.assertNotIn("res_model", sql)

    def test_nothing_dead_gives_no_sql(self):
        self.assertEqual(fs.purge_dead_sql(self.rapport()), "")

    def test_a_report_without_the_key_gives_no_sql(self):
        self.assertEqual(fs.purge_dead_sql({"groups": {}}), "")


class TestReadingWhatPostgresSaid(unittest.TestCase):
    def test_it_reads_the_count(self):
        self.assertEqual(fs.rows_deleted(["DELETE 250"]), 250)

    def test_zero_is_zero_not_success(self):
        # « DELETE 0 » se félicitait d'avoir supprimé : rejouer une purge
        # déjà faite annonçait un travail qui n'avait pas eu lieu.
        self.assertEqual(fs.rows_deleted(["DELETE 0"]), 0)

    def test_it_takes_the_LAST_word(self):
        self.assertEqual(fs.rows_deleted(["DELETE 5", "bruit", "DELETE 7"]), 7)

    def test_silence_is_not_zero(self):
        # « rien annoncé » et « rien supprimé » appellent des mots
        # différents : les confondre tait une panne.
        self.assertIsNone(fs.rows_deleted(["ERROR: boom"]))
        self.assertIsNone(fs.rows_deleted([]))

    def test_a_plain_string_works_too(self):
        self.assertEqual(fs.rows_deleted("DELETE 3\n"), 3)


class TestTidyingTheNested(unittest.TestCase):
    def setUp(self):
        self.racine = tempfile.mkdtemp()
        self.base = os.path.join(self.racine, "ma_base")
        for chemin in ("aa/deja", "filestore/aa/deja", "filestore/bb/absent"):
            complet = os.path.join(self.base, chemin)
            os.makedirs(os.path.dirname(complet), exist_ok=True)
            with open(complet, "w", encoding="utf-8") as handle:
                handle.write("x")

    def tearDown(self):
        shutil.rmtree(self.racine)

    def test_it_separates_what_to_move_from_pure_duplicates(self):
        # Écraser un fichier présent par une copie identique ne gagne
        # rien et brouille la trace : les deux tas restent distincts.
        remonter, doublons = fs.tidy_nested_plan({"root": self.base})
        self.assertEqual(
            [os.path.basename(a) for a, _b in remonter], ["absent"]
        )
        self.assertEqual([os.path.basename(a) for a, _b in doublons], ["deja"])

    def test_the_destination_is_the_right_level(self):
        remonter, _d = fs.tidy_nested_plan({"root": self.base})
        self.assertEqual(
            remonter[0][1], os.path.join(self.base, "bb", "absent")
        )

    def test_no_nested_directory_gives_an_empty_plan(self):
        shutil.rmtree(os.path.join(self.base, "filestore"))
        self.assertEqual(fs.tidy_nested_plan({"root": self.base}), ([], []))
        self.assertEqual(fs.nested_dir({"root": self.base}), "")


class TestTheRepairMenu(unittest.TestCase):
    """Les réparations ÉCRIVENT. On éprouve ce qui part, pas les appels.

    Un test qui constate qu'une fonction a été appelée n'aurait pas vu
    que `exec_command` n'existe pas — seul `exec_command_live` est
    offert. C'est arrivé ici : le code aurait planté au premier usage.
    """

    def setUp(self):
        from script.todo import auto_ask
        from script.todo import todo as todo_module

        self.auto_ask = auto_ask
        self.vrai_ask = auto_ask.ask
        self.lancees = []
        self.obj = todo_module.TODO.__new__(todo_module.TODO)

        def faux_exec(_self, cmd, **kw):
            self.lancees.append(cmd)
            if kw.get("return_status_and_output"):
                return 0, ["DELETE 1"]
            return 0

        self.obj.execute = type("E", (), {"exec_command_live": faux_exec})()

    def tearDown(self):
        self.auto_ask.ask = self.vrai_ask

    def repond(self, *reponses):
        file = list(reponses)

        def faux(prompt, default="", seconds=None):
            reponse = file.pop(0) if file else ""
            return reponse or default

        self.auto_ask.ask = faux

    def rapport(self, morts=(), ids=()):
        groupes = {v: [] for v in fs.VERDICTS}
        groupes["dead_field"] = list(morts)
        return {"root": "/fs/db", "groups": groupes, "dead_ids": list(ids)}

    def test_saying_no_deletes_nothing(self):
        self.repond("n")
        with redirect_stdout(io.StringIO()):
            self.obj._filestore_purge_dead(
                "db", self.rapport([piece("a/1")], [3])
            )
        self.assertEqual(self.lancees, [])

    def test_pressing_enter_deletes_nothing(self):
        # Le défaut d'une SUPPRESSION doit être de ne rien faire.
        self.repond("")
        with redirect_stdout(io.StringIO()):
            self.obj._filestore_purge_dead(
                "db", self.rapport([piece("a/1")], [3])
            )
        self.assertEqual(self.lancees, [])

    def test_accepting_runs_a_command_that_actually_exists(self):
        self.repond("y")
        with redirect_stdout(io.StringIO()):
            self.obj._filestore_purge_dead(
                "db", self.rapport([piece("a/1")], [3])
            )
        self.assertEqual(len(self.lancees), 1)
        self.assertIn("psql -d db", self.lancees[0])
        self.assertIn("WHERE id IN (3)", self.lancees[0])

    def test_nothing_dead_asks_nothing(self):
        demandes = []
        self.auto_ask.ask = lambda p, default="", seconds=None: (
            demandes.append(p) or "y"
        )
        with redirect_stdout(io.StringIO()):
            self.obj._filestore_purge_dead("db", self.rapport())
        self.assertEqual(demandes, [])
        self.assertEqual(self.lancees, [])

    def test_the_menu_offers_both_repairs(self):
        racine = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..")
        )
        with io.open(
            os.path.join(racine, "script", "todo", "todo.py"), encoding="utf-8"
        ) as handle:
            src = handle.read()
        self.assertIn("_filestore_purge_dead", src)
        self.assertIn("_filestore_tidy_nested", src)
        # Le garde du défaut doit rester collé à la question : c'est lui
        # qui empêche Entrée de supprimer.
        self.assertIn('auto_ask.ask(question, default="n")', src)

    def test_a_delete_that_changed_nothing_is_NOT_a_success(self):
        # « DELETE 0 » se félicitait d'avoir supprimé. Rejouer une purge
        # déjà faite annonçait donc un travail qui n'avait pas eu lieu.
        def rien(_self, cmd, **kw):
            self.lancees.append(cmd)
            return (
                (0, ["DELETE 0"]) if kw.get("return_status_and_output") else 0
            )

        self.obj.execute = type("E", (), {"exec_command_live": rien})()
        self.repond("y")
        tampon = io.StringIO()
        with redirect_stdout(tampon):
            self.obj._filestore_purge_dead(
                "db", self.rapport([piece("a/1")], [3])
            )
        self.assertIn("0 ", tampon.getvalue())
        self.assertNotIn("✅ 1 ", tampon.getvalue())

    def test_a_silent_command_is_flagged_not_counted(self):
        def muet(_self, cmd, **kw):
            self.lancees.append(cmd)
            return (
                (0, ["rien du tout"])
                if kw.get("return_status_and_output")
                else 0
            )

        self.obj.execute = type("E", (), {"exec_command_live": muet})()
        self.repond("y")
        tampon = io.StringIO()
        with redirect_stdout(tampon):
            self.obj._filestore_purge_dead(
                "db", self.rapport([piece("a/1")], [3])
            )
        self.assertIn(
            todo_i18n.t("The purge ran but said nothing."), tampon.getvalue()
        )

    def test_a_repair_reports_whether_it_did_something(self):
        # C'est ce booléen qui déclenche la relecture du rapport : sans
        # lui, « Tout afficher » rejouerait l'état d'avant la purge.
        self.repond("n")
        with redirect_stdout(io.StringIO()):
            refus = self.obj._filestore_purge_dead(
                "db", self.rapport([piece("a/1")], [3])
            )
        self.repond("y")
        with redirect_stdout(io.StringIO()):
            fait = self.obj._filestore_purge_dead(
                "db", self.rapport([piece("a/1")], [3])
            )
        self.assertFalse(refus)
        self.assertTrue(fait)


class TestTheReportIsRereadAfterARepair(unittest.TestCase):
    """« Tout afficher » doit montrer l'APRÈS, pas l'avant.

    Sans relecture on purgeait, on relisait, et l'on voyait encore ce
    qui venait de disparaître — puis on repurgeait des lignes déjà
    effacées en croyant le travail inachevé. C'est arrivé en vrai.
    """

    def setUp(self):
        from script.todo import auto_ask
        from script.todo import todo as todo_module

        self.auto_ask = auto_ask
        self.vrai_ask = auto_ask.ask
        self.vrai_audit = fs.audit
        self.appels = []
        self.obj = todo_module.TODO.__new__(todo_module.TODO)
        self.obj._analyse_select_database = lambda: "db"
        self.obj._filestore_purge_dead = lambda base, rapport: True
        self.obj._filestore_tidy_nested = lambda rapport: True

        def audit(base, *a, **k):
            self.appels.append(base)
            return {
                "database": base,
                "attachments": 1,
                "files_present": 1,
                "missing": 0,
                "nested_total": 0,
                "root": "/fs/db",
                "groups": {v: [] for v in fs.VERDICTS},
                "dead_ids": [],
            }

        fs.audit = audit
        self.auto_ask.ask = lambda p, default="", seconds=None: "n"

    def tearDown(self):
        self.auto_ask.ask = self.vrai_ask
        fs.audit = self.vrai_audit

    def joue(self, rang):
        self.obj._analyse_follow_up = lambda choix, handler: handler(rang)
        with redirect_stdout(io.StringIO()):
            self.obj.execute_analyse_filestore()

    def test_a_purge_triggers_a_fresh_read(self):
        self.joue(2)
        self.assertEqual(len(self.appels), 2)

    def test_a_tidy_triggers_a_fresh_read(self):
        self.joue(3)
        self.assertEqual(len(self.appels), 2)

    def test_merely_displaying_does_not(self):
        # Relire pour afficher coûterait un balayage complet des
        # filestores et des zips à chaque coup d'œil.
        self.joue(1)
        self.assertEqual(len(self.appels), 1)

    def test_a_refused_repair_does_not_reread(self):
        self.obj._filestore_purge_dead = lambda base, rapport: False
        self.joue(2)
        self.assertEqual(len(self.appels), 1)


class TestTidyingForReal(unittest.TestCase):
    def setUp(self):
        from script.todo import auto_ask
        from script.todo import todo as todo_module

        self.auto_ask = auto_ask
        self.vrai_ask = auto_ask.ask
        self.racine = tempfile.mkdtemp()
        self.base = os.path.join(self.racine, "ma_base")
        for chemin, contenu in (
            ("aa/deja", "bon"),
            ("filestore/aa/deja", "copie"),
            ("filestore/bb/absent", "utile"),
        ):
            complet = os.path.join(self.base, chemin)
            os.makedirs(os.path.dirname(complet), exist_ok=True)
            with open(complet, "w", encoding="utf-8") as handle:
                handle.write(contenu)
        self.obj = todo_module.TODO.__new__(todo_module.TODO)

    def tearDown(self):
        self.auto_ask.ask = self.vrai_ask
        shutil.rmtree(self.racine, ignore_errors=True)

    def test_refusing_leaves_every_file_where_it_was(self):
        self.auto_ask.ask = lambda p, default="", seconds=None: "n"
        with redirect_stdout(io.StringIO()):
            self.obj._filestore_tidy_nested({"root": self.base})
        self.assertTrue(
            os.path.isfile(
                os.path.join(self.base, "filestore", "bb", "absent")
            )
        )

    def test_accepting_moves_up_and_removes_the_nest(self):
        self.auto_ask.ask = lambda p, default="", seconds=None: "y"
        with redirect_stdout(io.StringIO()):
            self.obj._filestore_tidy_nested({"root": self.base})
        self.assertTrue(
            os.path.isfile(os.path.join(self.base, "bb", "absent"))
        )
        self.assertFalse(os.path.isdir(os.path.join(self.base, "filestore")))
        # Le fichier déjà présent n'a pas été ÉCRASÉ par sa copie :
        # vérifier sa seule existence laisserait passer l'écrasement.
        with io.open(
            os.path.join(self.base, "aa", "deja"), encoding="utf-8"
        ) as handle:
            self.assertEqual(handle.read(), "bon")


class TestTheDeadRowsThatKeptTheirFile(unittest.TestCase):
    """1860 lignes, 30 Mo, que l'outil ne voyait pas.

    Il s'appelle « fichiers absents » et ne regardait donc que les
    fichiers absents. Or une ligne dont le champ a disparu retient son
    fichier tant qu'elle existe : le ramasse-miettes d'Odoo ne retire
    que ce qui n'est plus référencé.
    """

    def setUp(self):
        self.vrais = (
            fs.attachments,
            fs.live_fields,
            fs.scan_filestores,
            fs.scan_backups,
            fs.filestore_root,
        )
        fs.live_fields = lambda base: {"res.partner.image_1920"}
        fs.scan_filestores = lambda racine, sauf=None: ({}, {}, {})
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

    def pose_fichier(self, chemin):
        """Un VRAI fichier : c'est la présence qui distingue les deux cas."""
        complet = os.path.join(self.racine, "db", chemin)
        os.makedirs(os.path.dirname(complet), exist_ok=True)
        with open(complet, "w", encoding="utf-8") as handle:
            handle.write("x")

    def test_a_dead_row_WITH_its_file_lands_in_dead_kept(self):
        self.racine = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.racine, True)
        fs.filestore_root = lambda config=None: self.racine
        self.pose_fichier("aa/bb")
        fs.attachments = lambda base: [
            piece("aa/bb", "res.partner", "image", size=4096, pid="5")
        ]
        rapport = fs.audit("db")
        # Fichier présent : ce n'est PAS un fichier manquant…
        self.assertEqual(rapport["missing"], 0)
        # …mais la ligne est morte, et son fichier occupe le disque.
        self.assertEqual(len(rapport["dead_kept"]), 1)
        self.assertEqual(rapport["dead_kept_size"], 4096)
        self.assertEqual(rapport["dead_ids"], [5])

    def test_a_living_row_with_its_file_is_left_alone(self):
        self.racine = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.racine, True)
        fs.filestore_root = lambda config=None: self.racine
        self.pose_fichier("aa/bb")
        fs.attachments = lambda base: [
            piece("aa/bb", "res.partner", "image_1920", size=4096, pid="5")
        ]
        rapport = fs.audit("db")
        self.assertEqual(rapport["dead_kept"], [])
        self.assertEqual(rapport["dead_ids"], [])

    def test_the_size_is_summed_by_the_audit_itself(self):
        self.racine = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.racine, True)
        fs.filestore_root = lambda config=None: self.racine
        for chemin in ("aa/bb", "cc/dd"):
            self.pose_fichier(chemin)
        fs.attachments = lambda base: [
            piece("aa/bb", "res.partner", "image", size=1024, pid="5"),
            piece("cc/dd", "res.partner", "image", size=1024, pid="6"),
        ]
        self.assertEqual(fs.audit("db")["dead_kept_size"], 2048)

    def test_the_report_shows_the_weight(self):
        gardees = [piece("a/1", "res.partner", "image", size=2048)]
        texte = "\n".join(
            fs.render_dead_kept({"dead_kept": gardees, "dead_kept_size": 2048})
        )
        self.assertIn("2 ko", texte)
        self.assertIn("res.partner / image", texte)

    def test_nothing_kept_says_nothing(self):
        self.assertEqual(fs.render_dead_kept({"dead_kept": []}), [])

    def test_a_living_field_is_never_counted(self):
        self.assertFalse(
            fs.is_dead_field(
                piece("a/1", "res.partner", "image_1920"),
                {"res.partner.image_1920"},
            )
        )

    def test_an_uploaded_document_has_no_field_so_is_never_dead(self):
        self.assertFalse(fs.is_dead_field(piece("a/1", "project.task"), set()))


class TestTheNestedCountIsPerDatabase(unittest.TestCase):
    """« 1168 fichiers échoués » devant une base qu'on vient de ranger.

    Le compte agrégeait tous les filestores de la machine : on rangeait,
    le rapport affichait le même chiffre, et l'on rangeait à nouveau.
    """

    def setUp(self):
        self.vrais = (
            fs.attachments,
            fs.live_fields,
            fs.scan_filestores,
            fs.scan_backups,
            fs.filestore_root,
        )
        fs.attachments = lambda base: []
        fs.live_fields = lambda base: set()
        fs.scan_backups = lambda dossier: {}
        fs.filestore_root = lambda config=None: "/nulle/part"
        fs.scan_filestores = lambda racine, sauf=None: (
            {},
            {"a/1": "ma_base", "b/2": "voisine", "c/3": "voisine"},
            {"ma_base": 1, "voisine": 2},
        )

    def tearDown(self):
        (
            fs.attachments,
            fs.live_fields,
            fs.scan_filestores,
            fs.scan_backups,
            fs.filestore_root,
        ) = self.vrais

    def test_only_this_database_counts_as_nested(self):
        rapport = fs.audit("ma_base")
        self.assertEqual(rapport["nested_total"], 1)
        self.assertEqual(rapport["nested_elsewhere"], 2)

    def test_a_tidy_database_is_not_told_it_has_work(self):
        fs.scan_filestores = lambda racine, sauf=None: (
            {},
            {"b/2": "voisine"},
            {"voisine": 1},
        )
        rapport = fs.audit("ma_base")
        texte = "\n".join(fs.render_nested(rapport))
        self.assertNotIn(
            todo_i18n.t("file(s) sit in a nested filestore Odoo never reads."),
            texte,
        )
        self.assertIn(
            todo_i18n.t("such file(s) sit in OTHER databases filestores."),
            texte,
        )


class TestTheMigrationWiring(unittest.TestCase):
    RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))

    def source(self, chemin):
        with io.open(
            os.path.join(self.RACINE, chemin), encoding="utf-8"
        ) as handle:
            return handle.read()

    def test_the_purge_runs_ONCE_at_the_end_not_between_bumps(self):
        # Entre deux paliers, deux à onze champs disparaissent puis
        # REVIENNENT : purger là trancherait sur du transitoire.
        src = self.source("script/todo/todo_upgrade.py")
        self.assertIn("prompt_purge_dead_attachments", src)
        appel = "self.prompt_purge_dead_attachments(database_name_upgrade)"
        self.assertEqual(src.count(appel), 1)
        boucle = src.index("for index, next_version in enumerate(")
        self.assertGreater(
            src.index(appel), boucle, "l'appel doit suivre la boucle"
        )
        etape = src.index('"5 - Cleaning up database after upgrade"')
        self.assertGreater(src.index(appel), etape)

    def test_the_purge_runs_BEFORE_the_final_backup(self):
        # Qui veut garder l'état d'avant refuse la purge ; la sauvegarde
        # qui suit doit capturer l'état nettoyé.
        src = self.source("script/todo/todo_upgrade.py")
        appel = "self.prompt_purge_dead_attachments(database_name_upgrade)"
        self.assertLess(src.index(appel), src.index("cmd_backup_template"))

    def test_the_restore_offers_to_tidy_where_the_fault_is_born(self):
        # L'APPEL, pas le nom : `pass` à sa place laisse la fonction
        # définie et le test passerait sur du code mort.
        src = self.source("script/database/db_restore.py")
        self.assertIn("tidy_nested_plan", src)
        self.assertIn(
            'if rapport.get("nested"):\n        offer_tidy(',
            src,
            "le rangement n'est plus proposé après la vérification",
        )

    def test_the_restore_never_asks_without_a_terminal(self):
        # Ce script tourne aussi sans personne devant : une question
        # posée à un stdin fermé arrêterait la migration.
        src = self.source("script/database/db_restore.py")
        debut = src.index("def offer_tidy")
        fin = src.index("input(", debut)
        self.assertIn("sys.stdin.isatty()", src[debut:fin])

    def test_the_clone_path_still_offers_nothing(self):
        src = self.source("script/database/db_restore.py")
        debut = src.index("--clone --from_database")
        fin = src.index("verify_filestore(config.database", debut)
        self.assertNotIn("offer_tidy", src[debut:fin])


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


class TestTheFollowUpIcons(unittest.TestCase):
    """Chaque entrée « Aller plus loin » porte une icône, ou aucune.

    Une seule entrée nue au milieu d'entrées ornées se lit comme un
    oubli — et c'en est un. Le garde vaut mieux qu'une relecture : la
    prochaine entrée ajoutée sans icône tombera ici, pas dans l'œil de
    quelqu'un six mois plus tard.
    """

    RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))

    def libelles(self):
        """Les clés passées en `prompt_description` à `_analyse_follow_up`."""
        import ast

        with io.open(
            os.path.join(self.RACINE, "script", "todo", "todo.py"),
            encoding="utf-8",
        ) as handle:
            arbre = ast.parse(handle.read())
        trouves = []
        for node in ast.walk(arbre):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_analyse_follow_up"
                and node.args
            ):
                continue
            for element in ast.walk(node.args[0]):
                if (
                    isinstance(element, ast.Call)
                    and isinstance(element.func, ast.Name)
                    and element.func.id == "t"
                    and element.args
                    and isinstance(element.args[0], ast.Constant)
                ):
                    trouves.append(element.args[0].value)
        return trouves

    def test_there_are_follow_up_entries_to_check(self):
        # Sans cette borne, un jour où l'extraction ne trouve plus rien,
        # le test suivant passerait en ne vérifiant rien du tout.
        self.assertGreater(len(self.libelles()), 5)

    def test_every_follow_up_entry_carries_an_icon(self):
        for cle in self.libelles():
            for langue in ("fr", "en"):
                texte = todo_i18n.TRANSLATIONS.get(cle, {}).get(langue, cle)
                self.assertGreaterEqual(
                    ord(texte[0]),
                    0x1F300,
                    f"entrée sans icône [{langue}] : {texte!r}",
                )


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
