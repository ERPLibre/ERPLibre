#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'adaptateur d'Open Code : ce qu'il construit, et ce qu'il refuse.

Les FORMES de ces jeux d'essai sont celles de la sortie réelle de l'outil ;
les VALEURS sont inventées. C'est l'ordre qui compte : un jeu d'essai qui
invente aussi la forme valide le défaut au lieu de le trouver — le dépôt l'a
payé une fois, sur deux champs qu'il croyait être des chaînes et qui sont des
entiers.

Trois pièges sont vérifiés ici parce qu'aucun ne se devine en lisant l'outil :

**Un listage vide n'est pas `[]`.** C'est une sortie VIDE, que `json.loads`
refuse. Une installation neuve ressemble alors à une panne.

**Un export commence par une ligne de préambule.** Décoder la sortie entière
lève ; le décodage part de la première accolade.

**Le titre d'une séance est du contenu**, engendré par le modèle à partir de
la conversation. Il a la forme d'un champ structurel et n'en est pas un. Le
témoin planté dans chaque entrée est ce qui prouve qu'il ne ressort pas.
"""

import json
import unittest

from script.todo.assistant.harness import opencode as oc

# Le titre que le modèle aurait écrit. Sa présence dans l'entrée est ce qui
# prouve qu'aucune structure décodée ne le porte.
TEMOIN = "titre-engendre-qui-ne-doit-pas-sortir"

SEANCE = "ses_aaaabbbbccccddddeeeeffff"


def _liste(entrees):
    return json.dumps(entrees)


def _export(**info):
    """La forme réelle : une ligne de préambule, puis le JSON."""
    charge = {
        "info": {
            "id": SEANCE,
            "title": TEMOIN,
            "agent": "build",
            "version": "1.2.3",
            "model": {"id": "un-modele", "providerID": "un-fournisseur"},
            "summary": {"additions": 12, "deletions": 3, "files": 2},
            "cost": 0.25,
            "tokens": {
                "input": 100,
                "output": 20,
                "reasoning": 5,
                "cache": {"read": 400, "write": 50},
            },
        }
    }
    charge["info"].update(info)
    return f"Exporting session: {SEANCE}\n{json.dumps(charge)}"


class TestCeQuiEstConstruit(unittest.TestCase):
    def test_the_listing_asks_for_json(self):
        self.assertEqual(
            oc.argv_lister(),
            ["opencode", "session", "list", "--format", "json"],
        )

    def test_the_listing_can_be_bounded(self):
        self.assertEqual(oc.argv_lister(maximum=5)[-2:], ["-n", "5"])

    def test_a_bound_that_is_not_a_count_is_refused(self):
        for mauvais in (0, -1, "5", 2.5, True):
            with self.assertRaises(ValueError, msg=repr(mauvais)):
                oc.argv_lister(maximum=mauvais)

    def test_the_export_names_one_session(self):
        self.assertEqual(
            oc.argv_exporter(SEANCE), ["opencode", "export", SEANCE]
        )

    def test_the_statistics_ask_for_tools_and_models(self):
        argv = oc.argv_statistiques()
        self.assertIn("--tools", argv)
        self.assertIn("--models", argv)
        self.assertNotIn("--days", argv)

    def test_the_statistics_can_be_bounded_in_days(self):
        self.assertEqual(oc.argv_statistiques(jours=7)[-2:], ["--days", "7"])

    def test_a_day_count_that_is_not_one_is_refused(self):
        for mauvais in (0, -3, "7", True):
            with self.assertRaises(ValueError, msg=repr(mauvais)):
                oc.argv_statistiques(jours=mauvais)


class TestCeQuiNEstPasConstruit(unittest.TestCase):
    """Rien de ce qui dépense ou change l'installation."""

    def test_no_builder_beyond_the_three_reads(self):
        construits = {n for n in dir(oc) if n.startswith("argv_")}
        self.assertEqual(
            construits, {"argv_lister", "argv_exporter", "argv_statistiques"}
        )

    def test_the_source_names_no_writing_subcommand(self):
        """`run` écrit dans l'arbre de travail sans demander ; `delete`,
        `uninstall` et `upgrade` changent l'installation. Les proposer à côté
        d'une lecture invite à en lancer une par erreur."""
        with open(oc.__file__, encoding="utf-8") as fh:
            source = fh.read()
        for interdit in ('"run"', '"delete"', '"uninstall"', '"upgrade"'):
            self.assertNotIn(interdit, source, interdit)


class TestLaBaseNeSeLitQueLaOuElleDoit(unittest.TestCase):
    """Le fichier qu'on ouvre porte des secrets, et pas qu'un peu.

    `opencode.db` tient dans la même base les jetons d'accès et de
    rafraîchissement du compte, son adresse, la valeur des identifiants
    enregistrés, et les invites tapées par l'utilisateur. Lire une colonne de
    coût dans ce fichier n'est acceptable que si la portée est CLOSE et
    vérifiée mécaniquement : sans ce test, une requête ajoutée un mardi
    atteint `account.access_token` sans que rien ne lève.
    """

    TABLES_INTERDITES = (
        "account",
        "account_state",
        "control_account",
        "credential",
        "session_input",
        "session_message",
        "session_share",
        "message",
        "part",
        "todo",
        "permission",
        "event",
    )
    COLONNES_INTERDITES = (
        "access_token",
        "refresh_token",
        "token_expiry",
        "email",
        "secret",
        "prompt",
        "title",
    )

    @classmethod
    def setUpClass(cls):
        with open(oc.__file__, encoding="utf-8") as fh:
            cls.source = fh.read()

    def test_only_one_table_is_named(self):
        self.assertEqual(oc.TABLE, "session")
        for interdite in self.TABLES_INTERDITES:
            self.assertNotIn(
                f'"{interdite}"', self.source, f"table {interdite}"
            )
            self.assertNotIn(
                f"'{interdite}'", self.source, f"table {interdite}"
            )

    def test_no_authenticating_column_is_named(self):
        """`title` est dans la liste pour la même raison que le reste : c'est
        du contenu engendré par le modèle, et il ne sort pas."""
        for interdite in self.COLONNES_INTERDITES:
            self.assertNotIn(f'"{interdite}"', self.source, interdite)
            self.assertNotIn(f"'{interdite}'", self.source, interdite)

    def test_the_query_names_its_columns_one_by_one(self):
        """Un « SELECT * » ramènerait le titre et tout ce qui s'ajoutera."""
        sql, _ = oc.requete()
        self.assertNotIn("*", sql)
        for colonne in oc.COLONNES:
            self.assertIn(colonne, sql)

    def test_a_directory_filter_is_bound_and_never_interpolated(self):
        sql, parametres = oc.requete(repertoire="/un; DROP TABLE session")
        self.assertIn("?", sql)
        self.assertNotIn("DROP", sql)
        self.assertEqual(parametres, ("/un; DROP TABLE session",))

    def test_the_database_is_opened_read_only(self):
        self.assertIn("mode=ro", oc.uri())

    def test_the_database_is_never_opened_immutable(self):
        """`immutable=1` fait ignorer le journal d'écriture anticipée, qui
        pèse plusieurs mégaoctets : la lecture rend alors ZÉRO ligne sur une
        base qui en porte, en silence. C'est une réponse fausse, pas une
        erreur — la pire des deux."""
        self.assertNotIn("immutable", oc.uri())
        self.assertNotIn("immutable", oc.uri("/une/autre/base.db"))

    def test_only_one_place_builds_the_uri(self):
        """La garde précédente ne vaut que si `uri()` est le SEUL endroit qui
        compose une URI : une seconde, ailleurs, échapperait à tout.

        Le mot « immutable » n'est pas cherché dans la source : il y figure
        exprès, dans la prose qui explique le piège, et une garde qui
        interdirait d'en parler pousserait à taire ce qu'on vient d'apprendre.
        """
        self.assertEqual(self.source.count("file:"), 1)


class TestCeQueLaBaseRend(unittest.TestCase):
    """Le repli et l'absence, vérifiés sans toucher à une vraie base."""

    LIGNE = {
        "id": SEANCE,
        "directory": "/un/depot",
        "agent": "build",
        "model": '{"id":"un-modele","providerID":"un-fournisseur"}',
        "version": "1.2.3",
        "cost": 0.25,
        "tokens_input": 100,
        "tokens_output": 20,
        "tokens_reasoning": 5,
        "tokens_cache_read": 400,
        "tokens_cache_write": 50,
        "summary_additions": 12,
        "summary_deletions": 3,
        "summary_files": 2,
        "time_created": 111,
        "time_updated": 222,
    }

    def _connecter(self, *, colonnes=None, lignes=None, leve=None):
        """Un faux lien : ni fichier, ni socket, ni base réelle."""
        presentes = oc.COLONNES if colonnes is None else colonnes
        rangs = [self.LIGNE] if lignes is None else lignes

        class Faux:
            def execute(interne, sql, parametres=()):
                if leve is not None:
                    raise leve
                if sql.startswith("PRAGMA"):
                    return [(i, n) for i, n in enumerate(presentes)]
                return interne

            def fetchall(interne):
                return [tuple(r.get(c) for c in oc.COLONNES) for r in rangs]

            def close(interne):
                pass

        return lambda chemin: Faux()

    def test_a_row_carries_its_whole_summary(self):
        (seance,) = oc.lire_base(connecter=self._connecter())
        self.assertEqual(seance.identifiant, SEANCE)
        self.assertEqual(seance.repertoire, "/un/depot")
        self.assertEqual(seance.modifie, 222)
        self.assertEqual(seance.resume.modele, "un-modele")
        self.assertEqual(seance.resume.fournisseur, "un-fournisseur")
        self.assertEqual(seance.resume.cout, 0.25)
        self.assertEqual(seance.resume.jetons, 575)
        self.assertEqual(seance.resume.lignes_ajoutees, 12)

    def test_a_model_that_is_not_json_leaves_two_empty_fields(self):
        ligne = dict(self.LIGNE, model="pas du json")
        (seance,) = oc.lire_base(connecter=self._connecter(lignes=[ligne]))
        self.assertEqual(seance.resume.modele, "")
        self.assertEqual(seance.resume.fournisseur, "")

    def test_a_schema_without_a_needed_column_falls_back(self):
        """Le schéma est celui d'un logiciel tiers, promis par personne : une
        colonne qui disparaît doit rendre la main au CLI, pas lever."""
        amputee = tuple(c for c in oc.COLONNES if c != "cost")
        self.assertIsNone(
            oc.lire_base(connecter=self._connecter(colonnes=amputee))
        )

    def test_an_unreadable_base_is_none_and_not_an_empty_list(self):
        """« La base manque » et « elle ne porte aucune séance » se
        ressemblent à l'écran et disent le contraire."""
        import sqlite3

        def refuser(chemin):
            raise sqlite3.OperationalError("unable to open database file")

        self.assertIsNone(oc.lire_base(connecter=refuser))

    def test_a_base_with_no_session_is_an_empty_list(self):
        self.assertEqual(
            oc.lire_base(connecter=self._connecter(lignes=[])), []
        )

    def test_a_query_that_raises_falls_back_rather_than_propagates(self):
        import sqlite3

        self.assertIsNone(
            oc.lire_base(
                connecter=self._connecter(leve=sqlite3.DatabaseError("x"))
            )
        )


class TestLIdentifiantNeVaPasDansUnShell(unittest.TestCase):
    """L'appelant recolle l'argv en une ligne de shell."""

    def test_a_name_a_shell_would_read_is_refused(self):
        for mauvais in (
            "",
            "ses_abcdefgh; echo pris",
            "ses_abcdefgh && echo pris",
            "$(echo pris)",
            "`echo pris`",
            "ses_abcdefgh | cat",
            "ses_abcdefgh > /tmp/pris",
            "../ses_abcdefgh",
            "--help",
            "autre_prefixe_abcdefgh",
            "ses_court",
        ):
            with self.assertRaises(ValueError, msg=mauvais):
                oc.argv_exporter(mauvais)

    def test_a_real_identifier_passes(self):
        """Refuser trop refuserait la fonctionnalité : la forme que
        l'outil emploie passe."""
        self.assertEqual(oc.argv_exporter(SEANCE)[-1], SEANCE)


class TestLeDecodageDuListage(unittest.TestCase):
    def test_an_empty_output_is_no_session_and_does_not_raise(self):
        """C'est ce que l'outil imprime pour un répertoire sans séance, et
        `json.loads` refuse la chaîne vide : les confondre ferait passer une
        installation neuve pour une panne."""
        for vide in ("", "   ", "\n", None):
            self.assertEqual(oc.decoder_liste(vide), [])

    def test_a_session_keeps_what_situates_it(self):
        (seance,) = oc.decoder_liste(
            _liste(
                [
                    {
                        "id": SEANCE,
                        "title": TEMOIN,
                        "directory": "/un/depot",
                        "projectId": "global",
                        "created": 111,
                        "updated": 222,
                    }
                ]
            )
        )
        self.assertEqual(seance.identifiant, SEANCE)
        self.assertEqual(seance.repertoire, "/un/depot")
        self.assertEqual(seance.projet, "global")
        self.assertEqual(seance.cree, 111)
        self.assertEqual(seance.modifie, 222)

    def test_the_generated_title_never_comes_out(self):
        seances = oc.decoder_liste(
            _liste([{"id": SEANCE, "title": TEMOIN, "directory": "/d"}])
        )
        self.assertNotIn(TEMOIN, repr(seances))

    def test_an_entry_without_an_identifier_is_dropped(self):
        """Rien ne s'exporte sans identifiant : l'afficher offrirait une
        entrée sur laquelle aucune action ne marche."""
        self.assertEqual(
            oc.decoder_liste(_liste([{"title": TEMOIN}, {"id": SEANCE}])),
            [oc.Seance(identifiant=SEANCE)],
        )

    def test_output_that_is_not_a_list_is_no_session(self):
        for autre in ("{}", '"texte"', "12", "pas du json"):
            self.assertEqual(oc.decoder_liste(autre), [], autre)

    def test_a_field_of_the_wrong_type_does_not_raise(self):
        (seance,) = oc.decoder_liste(
            _liste([{"id": SEANCE, "directory": 12, "updated": "hier"}])
        )
        self.assertEqual(seance.repertoire, "")
        self.assertEqual(seance.modifie, 0)


class TestLeDecodageDUnExport(unittest.TestCase):
    def test_the_preamble_line_does_not_stop_the_decoding(self):
        """L'outil imprime « Exporting session: … » avant son JSON ; décoder
        la sortie entière lève."""
        resume = oc.decoder_export(_export())
        self.assertIsNotNone(resume)
        self.assertEqual(resume.identifiant, SEANCE)

    def test_the_cost_and_the_lines_are_read(self):
        resume = oc.decoder_export(_export())
        self.assertEqual(resume.cout, 0.25)
        self.assertEqual(resume.lignes_ajoutees, 12)
        self.assertEqual(resume.lignes_retirees, 3)
        self.assertEqual(resume.fichiers, 2)

    def test_the_model_and_its_provider_are_read(self):
        resume = oc.decoder_export(_export())
        self.assertEqual(resume.modele, "un-modele")
        self.assertEqual(resume.fournisseur, "un-fournisseur")
        self.assertEqual(resume.agent, "build")

    def test_the_cache_counts_in_the_tokens(self):
        """Le cache LU est facturé : l'ignorer annonce une fraction de ce qui
        a réellement circulé."""
        self.assertEqual(oc.decoder_export(_export()).jetons, 575)

    def test_the_generated_title_never_comes_out(self):
        self.assertNotIn(TEMOIN, repr(oc.decoder_export(_export())))

    def test_nothing_decodable_is_none_and_not_a_zero_summary(self):
        """« Rien n'a pu être lu » et « cette séance n'a rien coûté » se
        ressemblent à l'écran et disent le contraire."""
        for brut in ("", None, "Exporting session: x", "{pas du json"):
            self.assertIsNone(oc.decoder_export(brut), repr(brut))

    def test_a_cut_output_is_told_apart_from_an_empty_one(self):
        """`export` sort avant d'avoir vidé son tampon sur une longue séance :
        trois exécutions du même export rendent trois tailles, toutes coupées
        au milieu. L'écran doit pouvoir dire que l'OUTIL a coupé, et non que
        la séance est illisible ou gratuite."""
        coupe = _export()[: len(_export()) // 2]
        self.assertTrue(oc.semble_tronque(coupe))
        self.assertIsNone(oc.decoder_export(coupe))

    def test_what_is_not_cut_is_not_called_cut(self):
        """Une sortie vide, ou sans la moindre accolade, n'est pas une
        troncature : le dire enverrait chercher un défaut de l'outil là où
        il n'y a simplement rien."""
        for entier in ("", None, "Exporting session: x", _export()):
            self.assertFalse(oc.semble_tronque(entier), repr(entier)[:40])

    def test_an_export_without_an_info_block_is_none(self):
        self.assertIsNone(oc.decoder_export(json.dumps({"autre": 1})))

    def test_a_nested_field_of_the_wrong_type_does_not_raise(self):
        brut = json.dumps(
            {"info": {"id": SEANCE, "tokens": "beaucoup", "model": []}}
        )
        resume = oc.decoder_export(brut)
        self.assertEqual(resume.jetons, 0)
        self.assertEqual(resume.modele, "")


if __name__ == "__main__":
    unittest.main()
