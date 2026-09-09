#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Transformer un fichier externe : ce qui compte est ce qui NE sort PAS.

Remplacer une cellule est facile. Ce qui produit un fichier faussement
propre, c'est de croire qu'un classeur ne porte de la donnée que dans ses
cellules. Un `.xlsx` en porte dans une douzaine d'autres endroits, et deux
d'entre eux — le cache d'un tableau croisé et un lien externe — en portent
une COPIE entière.

Le test de fuite est donc le cœur de ce fichier. Il pose 24 marqueurs
inventés, un par vecteur : 19 disparaissent, et 5 restent — ces cinq étant
référencés par des formules que la règle préserve, et qu'on ne peut donc
pas supprimer sans casser ce qu'on vient de garantir. Il assert la liste
EXACTE des survivants et non « rien d'autre » : c'est ce qui le fait tomber
quand une montée de version d'openpyxl rouvre un vecteur.

Trois pièges que seule l'exécution a donnés, et que ce fichier fige :
`isinstance(True, int)` vaut True, donc une case à cocher deviendrait un
montant ; `xlrd` stocke une erreur par son CODE ENTIER, donc `#REF!`
deviendrait un montant plausible et `#NULL!` un zéro légitime ; et
`csv.reader` ne rend que des chaînes, donc une colonne de montants
deviendrait des mots.

La suite tourne sous `.venv.erplibre`, qui n'a pas openpyxl : tout ce qui
en dépend est derrière `skipUnless` et se DIT ignoré, jamais vert en
silence.
"""

import builtins
import datetime
import io
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
import zipfile

from script.data import external_file as noyau
from script.data import external_file_formats as formats
from script.todo import todo_i18n, transform_setup

VIVIER = noyau.vivier_de_mots()


def _options(**extra):
    base = {
        "vivier": VIVIER,
        "nombres": True,
        "texte": True,
        "entetes": False,
        "feuilles": None,
        "etiquettes": {},
        "colonnes_intactes": set(),
        "bornes": {},
    }
    base.update(extra)
    return base


# `transform_menu` et `todo.py` importent `click`, que le venv dédié n'a
# pas — et la fixture du test de fuite importe CE module sous cet
# interprète-là pour bâtir un classeur. Les imports du menu sont donc
# PARESSEUX, comme ceux du moteur : sans cela, tout le test de fuite tombe
# sur un `ModuleNotFoundError` sans rapport avec ce qu'il éprouve.
def _tm():
    """Le module du menu, importé au premier appel."""
    from script.todo import transform_menu

    return transform_menu


def _MenuBouchon():
    """Le mixin, monté sur les aides que `TODO` lui fournit.

    Les aides sont PRISES sur la vraie classe et non recopiées : « o »,
    « oui », « y », « yes » et la différence entre un défaut oui et un
    défaut non sont sa règle, et une copie dériverait sans qu'un test le
    voie.
    """
    from script.todo.todo import TODO

    class Bouchon(_tm().TransformMenuMixin):
        _is_yes = staticmethod(TODO._is_yes)
        _is_yes_default_yes = staticmethod(TODO._is_yes_default_yes)

    return Bouchon()


class _Entrees:
    """`input()` bouchonné, et la trace de ce qui a été demandé.

    Rend les réponses dans l'ordre. Une question de plus que de réponses
    lève : un test qui répondrait « à côté » passerait sinon en silence.
    """

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


class TestMenuFonctionsPures(unittest.TestCase):
    """Ce que le menu décide sans rien demander."""

    def setUp(self):
        self.menu = _MenuBouchon()

    def test_le_format_vient_de_l_extension(self):
        for nom, attendu in (
            ("a.xlsx", "xlsx"),
            ("a.XLSM", "xlsx"),
            ("a.xlsb", "xlsx"),
            ("a.xls", "xls"),
            ("a.mdb", "access"),
            ("a.accdb", "access"),
            ("a.csv", "csv"),
            ("a.xml", "xml"),
            ("a.json", "json"),
        ):
            with self.subTest(nom=nom):
                self.assertEqual(self.menu._transform_format(nom), attendu)

    def test_une_extension_inconnue_tombe_sur_le_venv_dedie(self):
        """Le repli doit être le venv qui sait TOUT lire : celui du CLI
        ferait lever un import sur un classeur mal nommé."""
        self.assertEqual(self.menu._transform_format("a.dat"), "xlsx")
        self.assertEqual(self.menu._transform_format("sans_extension"), "xlsx")

    def test_l_interpreteur_suit_l_union_des_bibliotheques(self):
        """Le processus lit la source ET écrit la cible.

        La source seule laissait csv→xlsx importer openpyxl sous
        l'interpréteur du CLI, qui ne l'a pas ; la cible seule enverrait
        un classeur au même interpréteur, qui ne sait pas le lire.
        """
        self.assertEqual(
            self.menu._transform_fmt_moteur("csv", "xlsx"), "xlsx"
        )
        self.assertEqual(self.menu._transform_fmt_moteur("xls", "csv"), "xls")
        self.assertEqual(
            self.menu._transform_fmt_moteur("csv", "json"), "json"
        )
        self.assertEqual(
            self.menu._transform_fmt_moteur("access", "xlsx"), "access"
        )

    def test_la_table_va_TOUJOURS_sous_private(self):
        """Elle ré-identifie la copie à elle seule : la poser à côté du
        fichier à transmettre fait partir la clé avec le chiffré."""
        for destination in (
            "/tmp/livraison/copie.xlsx",
            os.path.join("private", "transform", "c.xlsx"),
            "c.csv",
        ):
            with self.subTest(destination=destination):
                table = self.menu._transform_table_par_defaut(destination)
                self.assertTrue(
                    table.startswith(_tm().SORTIE_PAR_DEFAUT), table
                )
                self.assertTrue(table.endswith(".table.json"), table)

    def test_private_se_reconnait_par_realpath(self):
        """Un test de préfixe sur le chemin TAPÉ taisait l'avertissement
        pour le chemin absolu du navigateur, et le levait pour
        « privateer/ »."""
        racine = transform_setup.racine()
        self.assertTrue(
            self.menu._transform_sous_private(
                os.path.join(racine, "private", "transform", "c.xlsx")
            )
        )
        self.assertTrue(
            self.menu._transform_sous_private(os.path.join(racine, "private"))
        )
        self.assertFalse(
            self.menu._transform_sous_private(
                os.path.join(racine, "privateer", "c.xlsx")
            )
        )
        self.assertFalse(self.menu._transform_sous_private("/tmp/c.xlsx"))


class TestMenuQuestions(unittest.TestCase):
    """Les douze questions, et la sortie qui doit exister à chacune.

    S'apercevoir à la onzième qu'on a ouvert le mauvais fichier ne doit
    pas obliger à répondre à tout puis à refuser un nom de fichier.
    """

    RAPPORT = {
        "format": "xlsx",
        "feuilles": [{"nom": "Ventes"}, {"nom": "Achats"}],
        "hors_cellules": {},
    }

    def setUp(self):
        self.menu = _MenuBouchon()
        # L'écran réel prendrait le terminal : ce qu'on éprouve ici est le
        # chemin TEXTUEL, dont l'écran est le repli. `{}` veut dire
        # « pose-moi les questions ».
        self.menu._transform_ecran = lambda *args: {}
        self.vrai_input = builtins.input
        self.addCleanup(setattr, builtins, "input", self.vrai_input)
        self.sortie = io.StringIO()
        self.vrai_stdout = sys.stdout
        sys.stdout = self.sortie
        self.addCleanup(setattr, sys, "stdout", self.vrai_stdout)

    def _repondre(self, *reponses):
        entrees = _Entrees(*reponses)
        builtins.input = entrees
        return entrees

    # -- le chemin qui aboutit -----------------------------------------
    def test_le_chemin_complet_rend_les_douze_reponses(self):
        self._repondre(
            "o",  # anonymiser
            "csv",  # convertir
            "",  # table du lot — posée AVANT l'écran
            "Ventes",  # feuilles
            "id, ref",  # colonnes intactes
            "",  # nombres, défaut oui
            "",  # texte, défaut oui
            "",  # en-têtes, défaut non
            "42",  # graine
        )
        options = self.menu._transform_ask_options(self.RAPPORT)
        self.assertEqual(options["conversion"], "csv")
        self.assertEqual(options["feuilles"], ["Ventes"])
        self.assertEqual(options["colonnes_intactes"], ["id", "ref"])
        self.assertTrue(options["nombres"])
        self.assertTrue(options["texte"])
        self.assertFalse(options["entetes"])
        self.assertEqual(options["graine"], "42")
        self.assertEqual(options["table_chemin"], "")

    def test_un_defaut_vide_ne_convertit_ni_ne_restreint(self):
        self._repondre("oui", "", "", "", "", "n", "n", "o", "")
        options = self.menu._transform_ask_options(self.RAPPORT)
        self.assertEqual(options["conversion"], "")
        self.assertEqual(options["feuilles"], [])
        self.assertFalse(options["nombres"])
        self.assertFalse(options["texte"])
        self.assertTrue(options["entetes"])

    # -- les sorties ---------------------------------------------------
    def test_refuser_d_anonymiser_ne_pose_aucune_autre_question(self):
        entrees = self._repondre("n")
        self.assertIsNone(self.menu._transform_ask_options(self.RAPPORT))
        self.assertEqual(len(entrees.demandes), 1)

    def test_zero_annule_a_CHAQUE_question(self):
        """Une réponse valide jusqu'au rang N, puis « 0 »."""
        # L'ordre du dialogue, la table venant maintenant en troisième.
        valides = ["o", "csv", "", "Ventes", "", "", "", "", "42"]
        for rang in range(len(valides)):
            with self.subTest(rang=rang):
                entrees = self._repondre(*(valides[:rang] + ["0"]))
                self.assertIsNone(
                    self.menu._transform_ask_options(self.RAPPORT)
                )
                self.assertEqual(len(entrees.demandes), rang + 1)

    def test_une_cible_inconnue_est_refusee(self):
        entrees = self._repondre("o", "parquet")
        self.assertIsNone(self.menu._transform_ask_options(self.RAPPORT))
        self.assertEqual(len(entrees.demandes), 2)

    def test_les_quatre_cibles_sont_acceptees(self):
        for cible in _tm().CIBLES:
            with self.subTest(cible=cible):
                self._repondre("o", cible, "", "", "", "", "", "", "")
                options = self.menu._transform_ask_options(self.RAPPORT)
                self.assertEqual(options["conversion"], cible)

    # -- les feuilles --------------------------------------------------
    def test_une_feuille_inconnue_est_refusee_AVANT_d_ecrire(self):
        entrees = self._repondre("o", "", "", "Trésorerie")
        self.assertIsNone(self.menu._transform_ask_options(self.RAPPORT))
        self.assertEqual(len(entrees.demandes), 4)

    def test_le_nom_de_feuille_se_resout_sans_la_casse(self):
        """Le nom rendu est celui du CLASSEUR, non celui tapé : la portée
        s'apparie ensuite par égalité exacte."""
        self._repondre("o", "", "", "  ventes , ACHATS ", "", "", "", "", "")
        options = self.menu._transform_ask_options(self.RAPPORT)
        self.assertEqual(options["feuilles"], ["Ventes", "Achats"])

    def test_une_source_d_une_seule_feuille_ne_pose_pas_la_question(self):
        entrees = self._repondre("o", "", "", "", "", "", "", "")
        rapport = dict(self.RAPPORT, feuilles=[{"nom": "F"}])
        options = self.menu._transform_ask_options(rapport)
        self.assertNotIn("feuilles", options)
        self.assertEqual(len(entrees.demandes), 8)

    # -- macros et graphiques ------------------------------------------
    def test_les_macros_ne_se_demandent_que_si_le_fichier_en_a(self):
        entrees = self._repondre("o", "", "", "", "", "", "", "", "", "o", "n")
        rapport = dict(
            self.RAPPORT, hors_cellules={"macros": 1, "graphiques": 2}
        )
        options = self.menu._transform_ask_options(rapport)
        self.assertTrue(options["garder_macros"])
        self.assertFalse(options["garder_graphiques"])
        self.assertEqual(len(entrees.demandes), 11)

    def test_une_conversion_hors_xlsx_ne_les_demande_pas(self):
        """Un csv ne porte ni macro ni graphique : poser la question
        laisserait croire que la réponse change quelque chose."""
        entrees = self._repondre("o", "csv", "", "", "", "", "", "", "")
        rapport = dict(
            self.RAPPORT, hors_cellules={"macros": 1, "graphiques": 2}
        )
        options = self.menu._transform_ask_options(rapport)
        self.assertNotIn("garder_macros", options)
        self.assertEqual(len(entrees.demandes), 9)


class _Acheve:
    """Ce que `subprocess.run` rend, réduit à ce que le menu en lit."""

    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class TestMenuMoteurEnSousProcessus(unittest.TestCase):
    """stdout ne porte qu'un objet JSON, stderr la progression.

    Un stdout vide ou inanalysable est traité comme une ERREUR et non
    relayé en exception, pour que le menu affiche les dernières lignes de
    stderr plutôt que de tomber à son tour.
    """

    def setUp(self):
        self.menu = _MenuBouchon()
        self.sortie = io.StringIO()
        vrai = sys.stdout
        sys.stdout = self.sortie
        self.addCleanup(setattr, sys, "stdout", vrai)
        self.vrai_run = _tm().subprocess.run
        self.addCleanup(setattr, _tm().subprocess, "run", self.vrai_run)

    def _rendre(self, acheve):
        _tm().subprocess.run = lambda *a, **k: acheve

    def test_un_objet_json_traverse(self):
        self._rendre(_Acheve(stdout='{"format": "csv", "taille": 12}'))
        self.assertEqual(
            self.menu._transform_run(["--report", "a.csv"], "csv"),
            {"format": "csv", "taille": 12},
        )

    def test_la_progression_de_stderr_s_affiche_sans_son_diese(self):
        self._rendre(
            _Acheve(stdout="{}", stderr="# lecture en cours\nbruit interne")
        )
        self.menu._transform_run(["--report", "a.csv"], "csv")
        rendu = self.sortie.getvalue()
        self.assertIn("lecture en cours", rendu)
        self.assertNotIn("bruit interne", rendu)

    def test_un_stdout_vide_ne_leve_pas_et_montre_stderr(self):
        """Le menu doit afficher la cause, non tomber à son tour."""
        self._rendre(_Acheve(stdout="", stderr="Traceback ligne 1"))
        self.assertIsNone(
            self.menu._transform_run(["--report", "a.csv"], "csv")
        )
        self.assertIn("Traceback ligne 1", self.sortie.getvalue())

    def test_un_stdout_inanalysable_est_traite_comme_une_erreur(self):
        self._rendre(_Acheve(stdout="pas du json"))
        self.assertIsNone(
            self.menu._transform_run(["--report", "a.csv"], "csv")
        )

    def test_une_erreur_du_moteur_s_affiche_avec_son_detail(self):
        self._rendre(
            _Acheve(
                stdout=json.dumps(
                    {"erreur": "Nothing to do.", "detail": " ici"}
                )
            )
        )
        self.assertIsNone(
            self.menu._transform_run(["--apply", "a.csv"], "csv")
        )
        self.assertIn("ici", self.sortie.getvalue())

    def test_le_CONSEIL_s_affiche_quand_le_refus_en_porte_un(self):
        """Le détail nomme une partie du format ; le conseil dit quoi
        répondre à la prochaine exécution."""
        avis = (
            "The kept VBA project quotes a source value;"
            " answer no to the macro question to write the copy."
        )
        self._rendre(
            _Acheve(
                stdout=json.dumps(
                    {"erreur": "Nothing to do.", "conseil": avis}
                )
            )
        )
        self.assertIsNone(
            self.menu._transform_run(["--apply", "a.xlsm"], "xlsx")
        )
        rendu = self.sortie.getvalue()
        self.assertIn("→", rendu)
        self.assertIn(todo_i18n.TRANSLATIONS[avis]["fr"][:30], rendu)

    def test_un_interpreteur_introuvable_ne_leve_pas(self):
        def tombe(*a, **k):
            raise OSError("introuvable")

        _tm().subprocess.run = tombe
        self.assertIsNone(
            self.menu._transform_run(["--report", "a.csv"], "csv")
        )


class TestMenuApercu(unittest.TestCase):
    """Montrer, PUIS demander. La convention du dépôt pour ce qui écrit."""

    def setUp(self):
        self.menu = _MenuBouchon()
        self.sortie = io.StringIO()
        vrai = sys.stdout
        sys.stdout = self.sortie
        self.addCleanup(setattr, sys, "stdout", vrai)
        vrai_input = builtins.input
        self.addCleanup(setattr, builtins, "input", vrai_input)

    def _repondre(self, reponse):
        builtins.input = lambda invite="": reponse

    def test_une_reponse_vide_ECRIT(self):
        """Le défaut de la dernière question est oui : l'opérateur vient
        de lire l'aperçu."""
        self._repondre("")
        self.assertTrue(self.menu._transform_preview({"remplacees": 3}))

    def test_un_non_n_ecrit_pas(self):
        self._repondre("n")
        self.assertFalse(self.menu._transform_preview({"remplacees": 3}))

    def test_l_intact_est_ANNONCE_avant_le_consentement(self):
        """Une date et un booléen traversent par RÈGLE et sont de vraies
        valeurs du client : les taire faisait signer un consentement sur
        un fichier dont une colonne part en clair."""
        self._repondre("")
        self.menu._transform_preview(
            {"remplacees": 3, "intactes": {"date": 7, "booleen": 2}}
        )
        rendu = self.sortie.getvalue()
        self.assertIn("7", rendu)
        self.assertIn(todo_i18n.t("date(s)"), rendu)

    def test_la_ligne_1_gardee_est_montree_cellule_par_cellule(self):
        """Un compteur ne dirait pas qu'un nom est dedans."""
        self._repondre("")
        self.menu._transform_preview(
            {
                "remplacees": 1,
                "entete_gardee": [{"cellule": "L1C1", "valeur": "aboulie"}],
            }
        )
        rendu = self.sortie.getvalue()
        self.assertIn("L1C1", rendu)
        self.assertIn("aboulie", rendu)

    def test_les_avertissements_sont_traduits(self):
        self._repondre("")
        avis = "The copy is written in UTF-8, whatever the source was."
        self.menu._transform_preview(
            {"remplacees": 1, "avertissements": [avis]}
        )
        self.assertIn(
            todo_i18n.TRANSLATIONS[avis]["fr"][:30], self.sortie.getvalue()
        )

    def test_les_fichiers_prevus_sont_montres(self):
        """Ce sur quoi l'opérateur consent inclut OÙ ça va."""
        self._repondre("")
        self.menu._transform_preview(
            {"remplacees": 1, "fichiers": ["/tmp/a.csv", "/tmp/b.csv"]}
        )
        rendu = self.sortie.getvalue()
        self.assertIn("/tmp/a.csv", rendu)
        self.assertIn("/tmp/b.csv", rendu)


class TestMenuDestination(unittest.TestCase):
    """Le défaut NE REPREND PAS le nom source : il porte le client."""

    def setUp(self):
        self.menu = _MenuBouchon()
        self.sortie = io.StringIO()
        vrai = sys.stdout
        sys.stdout = self.sortie
        self.addCleanup(setattr, sys, "stdout", vrai)
        vrai_input = builtins.input
        self.addCleanup(setattr, builtins, "input", vrai_input)

    def _repondre(self, reponse):
        builtins.input = lambda invite="": reponse

    def test_le_defaut_ne_reprend_pas_le_nom_source(self):
        self._repondre("")
        rendu = self.menu._transform_select_destination(
            "/tmp/Cabinet_Lavigne_2024.xlsx", "xlsx"
        )
        self.assertNotIn("Lavigne", rendu)
        self.assertTrue(rendu.endswith(".xlsx"), rendu)
        self.assertTrue(rendu.startswith(_tm().SORTIE_PAR_DEFAUT), rendu)

    def test_l_extension_suit_le_format_de_SORTIE(self):
        for fmt, extension in (
            ("xlsx", ".xlsx"),
            ("csv", ".csv"),
            ("json", ".json"),
            ("xml", ".xml"),
            ("xls", ".xlsx"),
            ("access", ".xlsx"),
        ):
            with self.subTest(fmt=fmt):
                self._repondre("")
                rendu = self.menu._transform_select_destination("s", fmt)
                self.assertTrue(rendu.endswith(extension), rendu)

    def test_garder_les_macros_nomme_la_copie_xlsm(self):
        """Excel lie l'extension au contenu et refuse d'ouvrir un .xlsx
        qui porte un projet VBA : la copie était juste et n'ouvrait pas."""
        self._repondre("")
        rendu = self.menu._transform_select_destination(
            "s.xlsm", "xlsx", macros=True
        )
        self.assertTrue(rendu.endswith(".xlsm"), rendu)
        self.assertIn(".xlsm", self.sortie.getvalue())

    def test_les_macros_ne_changent_rien_hors_xlsx(self):
        self._repondre("")
        rendu = self.menu._transform_select_destination(
            "s.csv", "csv", macros=True
        )
        self.assertTrue(rendu.endswith(".csv"), rendu)

    def test_un_chemin_tape_est_pris_et_developpe(self):
        self._repondre("~/copie.xlsx")
        self.assertEqual(
            self.menu._transform_select_destination("s", "xlsx"),
            os.path.expanduser("~/copie.xlsx"),
        )

    def test_zero_renonce(self):
        self._repondre("0")
        self.assertIsNone(self.menu._transform_select_destination("s", "xlsx"))


class TestMenuEcrasement(unittest.TestCase):
    """Le nom tapé EN ENTIER, comme le reste du dépôt l'exige."""

    def setUp(self):
        self.menu = _MenuBouchon()
        self.base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.base, True)
        self.sortie = io.StringIO()
        vrai = sys.stdout
        sys.stdout = self.sortie
        self.addCleanup(setattr, sys, "stdout", vrai)
        vrai_input = builtins.input
        self.addCleanup(setattr, builtins, "input", vrai_input)
        self.existant = os.path.join(self.base, "copie.xlsx")
        with open(self.existant, "w", encoding="utf-8") as flux:
            flux.write("x")

    def test_rien_a_ecraser_ne_demande_rien(self):
        def refuse(invite=""):
            raise AssertionError("aucune question ne devait être posée")

        builtins.input = refuse
        absent = os.path.join(self.base, "neuf.xlsx")
        self.assertTrue(self.menu._transform_confirm_overwrite([absent]))

    def test_le_nom_exact_autorise(self):
        builtins.input = lambda invite="": "copie.xlsx"
        self.assertTrue(
            self.menu._transform_confirm_overwrite([self.existant])
        )

    def test_un_nom_approchant_refuse(self):
        for reponse in ("copie", "copie.xls", "o", "", self.existant):
            with self.subTest(reponse=reponse):
                builtins.input = lambda invite="", r=reponse: r
                self.assertFalse(
                    self.menu._transform_confirm_overwrite([self.existant])
                )

    def test_les_cibles_existantes_sont_TOUTES_nommees(self):
        second = os.path.join(self.base, "autre.csv")
        with open(second, "w", encoding="utf-8") as flux:
            flux.write("y")
        builtins.input = lambda invite="": "copie.xlsx"
        self.menu._transform_confirm_overwrite([self.existant, second, None])
        rendu = self.sortie.getvalue()
        self.assertIn("copie.xlsx", rendu)
        self.assertIn("autre.csv", rendu)


class TestMenuInventaire(unittest.TestCase):
    """Ce que l'outil a produit se reconnaît à son NOM.

    Le navigateur ouvre son parcours dans ce même répertoire : ce qui s'y
    trouve n'est pas toujours une copie produite ici, et l'effacement en
    bloc l'emportait aussi.
    """

    def setUp(self):
        self.menu = _MenuBouchon()
        self.base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.base, True)
        vrai = _tm().SORTIE_PAR_DEFAUT
        _tm().SORTIE_PAR_DEFAUT = self.base
        self.addCleanup(setattr, _tm(), "SORTIE_PAR_DEFAUT", vrai)

    def _poser(self, nom, contenu="x"):
        chemin = os.path.join(self.base, nom)
        with open(chemin, "w", encoding="utf-8") as flux:
            flux.write(contenu)
        return chemin

    def test_les_copies_et_les_tables_sont_dites_produites(self):
        self._poser("20260101-000000.anon.xlsx")
        self._poser("20260101-000000.table.json")
        produites, etrangeres = self.menu._transform_inventaire()
        self.assertEqual(
            [n for n, _ in produites],
            ["20260101-000000.anon.xlsx", "20260101-000000.table.json"],
        )
        self.assertEqual(etrangeres, [])

    def test_un_fichier_depose_par_quelqu_un_d_autre_est_ETRANGER(self):
        """Il n'est pas à effacer : le parcours ouvre ici."""
        self._poser("export_du_client.xlsx")
        produites, etrangeres = self.menu._transform_inventaire()
        self.assertEqual(produites, [])
        self.assertEqual([n for n, _ in etrangeres], ["export_du_client.xlsx"])

    def test_un_repertoire_de_conversion_pese_la_somme_de_ses_fichiers(self):
        """Une source à plusieurs feuilles convertie en csv écrit un
        RÉPERTOIRE. Il était compté à la taille de son inode."""
        dossier = os.path.join(self.base, "20260101.anon.csv")
        os.makedirs(os.path.join(dossier, "sous"))
        for chemin, contenu in (
            (os.path.join(dossier, "a.csv"), "12345"),
            (os.path.join(dossier, "sous", "b.csv"), "678"),
        ):
            with open(chemin, "w", encoding="utf-8") as flux:
                flux.write(contenu)
        produites, _etrangeres = self.menu._transform_inventaire()
        self.assertEqual(produites, [("20260101.anon.csv", 8)])

    def test_un_repertoire_vide_pese_zero_et_reste_liste(self):
        os.makedirs(os.path.join(self.base, "20260101.anon.csv"))
        produites, _e = self.menu._transform_inventaire()
        self.assertEqual(produites, [("20260101.anon.csv", 0)])


class TestMenuFichierEntree(unittest.TestCase):
    """Le parcours d'abord, la saisie en repli.

    La garde d'import est celle de `database_manager` : urwid peut
    manquer, et sans elle « p » lèverait sur None.
    """

    def setUp(self):
        self.menu = _MenuBouchon()
        self.base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.base, True)
        self.sortie = io.StringIO()
        vrai_out = sys.stdout
        sys.stdout = self.sortie
        self.addCleanup(setattr, sys, "stdout", vrai_out)
        vrai_input = builtins.input
        self.addCleanup(setattr, builtins, "input", vrai_input)
        # Sans navigateur, la saisie répond : c'est le chemin qu'on teste,
        # et lancer urwid dans une suite unitaire n'a pas de sens.
        vrai_nav = _tm().todo_file_browser
        _tm().todo_file_browser = None
        self.addCleanup(setattr, _tm(), "todo_file_browser", vrai_nav)

    def _repondre(self, reponse):
        builtins.input = lambda invite="": reponse

    def test_un_fichier_ordinaire_est_pris(self):
        chemin = os.path.join(self.base, "s.csv")
        with open(chemin, "w", encoding="utf-8") as flux:
            flux.write("a\n")
        self._repondre(chemin)
        self.assertEqual(self.menu._transform_select_file(), chemin)

    def test_un_repertoire_est_refuse(self):
        """`--report` sur un répertoire ferait lever le moteur."""
        self._repondre(self.base)
        self.assertIsNone(self.menu._transform_select_file())

    def test_un_chemin_absent_est_refuse(self):
        self._repondre(os.path.join(self.base, "absent.csv"))
        self.assertIsNone(self.menu._transform_select_file())

    def test_une_reponse_vide_ou_zero_renonce(self):
        for reponse in ("", "0", "   "):
            with self.subTest(reponse=reponse):
                self._repondre(reponse)
                self.assertIsNone(self.menu._transform_select_file())


class TestMenuRendus(unittest.TestCase):
    """Le rapport et le bilan : ce que l'opérateur lit pour décider."""

    def setUp(self):
        self.menu = _MenuBouchon()
        self.sortie = io.StringIO()
        vrai = sys.stdout
        sys.stdout = self.sortie
        self.addCleanup(setattr, sys, "stdout", vrai)

    def test_le_rapport_nomme_le_fichier_sa_taille_et_son_format(self):
        rendu = self.menu._transform_render_report(
            {"chemin": "/tmp/s.csv", "taille": 42, "format": "csv"}
        )
        self.assertIn("s.csv", rendu)
        self.assertIn("42", rendu)
        self.assertIn("csv", rendu)

    def test_une_divergence_entre_octets_et_extension_est_DITE(self):
        """Un export d'ERP en HTML sous une extension .csv se lit comme
        du HTML : le taire ferait consentir sur un format supposé."""
        rendu = self.menu._transform_render_report(
            {
                "chemin": "s.csv",
                "taille": 1,
                "format": "xml",
                "divergence": True,
            }
        )
        self.assertIn(
            todo_i18n.t("Contents do not match the extension: read as "),
            rendu,
        )

    def test_l_encodage_et_le_delimiteur_disent_QUI_les_a_decides(self):
        rendu = self.menu._transform_render_report(
            {
                "chemin": "s.csv",
                "taille": 1,
                "format": "csv",
                "encodage": "cp1252",
                "encodage_source": "chardet",
                "delimiteur": ";",
                "delimiteur_source": "sniffer",
            }
        )
        self.assertIn("cp1252", rendu)
        self.assertIn(todo_i18n.t("chardet"), rendu)
        self.assertIn(todo_i18n.t("sniffer"), rendu)

    def test_le_bilan_nomme_CHAQUE_fichier_ecrit(self):
        """Une conversion à plusieurs feuilles en écrit plusieurs."""
        self.menu._transform_render_bilan(
            {"fichiers": ["/tmp/a.csv", "/tmp/b.csv"], "remplacees": 4},
            "/tmp/ignore",
        )
        rendu = self.sortie.getvalue()
        self.assertIn("/tmp/a.csv", rendu)
        self.assertIn("/tmp/b.csv", rendu)
        self.assertNotIn("ignore", rendu)

    def test_sans_liste_le_bilan_retombe_sur_la_destination(self):
        self.menu._transform_render_bilan({"remplacees": 1}, "/tmp/seul.xlsx")
        self.assertIn("/tmp/seul.xlsx", self.sortie.getvalue())


class TestMenuEffacement(unittest.TestCase):
    """L'effacement en bloc n'emporte QUE ce que l'outil a produit."""

    def setUp(self):
        self.menu = _MenuBouchon()
        self.base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.base, True)
        vrai_sortie = _tm().SORTIE_PAR_DEFAUT
        _tm().SORTIE_PAR_DEFAUT = self.base
        self.addCleanup(setattr, _tm(), "SORTIE_PAR_DEFAUT", vrai_sortie)
        self.ecran = io.StringIO()
        vrai_out = sys.stdout
        sys.stdout = self.ecran
        self.addCleanup(setattr, sys, "stdout", vrai_out)
        vrai_input = builtins.input
        self.addCleanup(setattr, builtins, "input", vrai_input)
        self.copie = os.path.join(self.base, "20260101.anon.xlsx")
        self.table = os.path.join(self.base, "20260101.table.json")
        self.etranger = os.path.join(self.base, "export_du_client.xlsx")
        for chemin in (self.copie, self.table, self.etranger):
            with open(chemin, "w", encoding="utf-8") as flux:
                flux.write("x")
        self.dossier = os.path.join(self.base, "20260102.anon.csv")
        os.makedirs(self.dossier)
        with open(os.path.join(self.dossier, "a.csv"), "w") as flux:
            flux.write("y")

    def test_oui_efface_les_copies_et_LAISSE_l_etranger(self):
        builtins.input = lambda invite="": "o"
        self.menu._transform_copies()
        self.assertFalse(os.path.exists(self.copie))
        self.assertFalse(os.path.exists(self.table))
        self.assertFalse(os.path.exists(self.dossier))
        self.assertTrue(os.path.exists(self.etranger))

    def test_non_n_efface_rien(self):
        for reponse in ("n", "", "0", "x"):
            with self.subTest(reponse=reponse):
                builtins.input = lambda invite="", r=reponse: r
                self.menu._transform_copies()
                self.assertTrue(os.path.exists(self.copie))
                self.assertTrue(os.path.exists(self.dossier))

    def test_l_etranger_est_NOMME_a_l_ecran(self):
        """Le parcours ouvre dans ce répertoire : ce qui s'y trouve n'est
        pas toujours une copie produite ici."""
        builtins.input = lambda invite="": "n"
        self.menu._transform_copies()
        rendu = self.ecran.getvalue()
        self.assertIn("export_du_client.xlsx", rendu)
        self.assertIn(todo_i18n.t("Not produced here, left alone:"), rendu)

    def test_un_repertoire_absent_ne_leve_pas(self):
        _tm().SORTIE_PAR_DEFAUT = os.path.join(self.base, "absent")

        def refuse(invite=""):
            raise AssertionError("rien à effacer, rien à demander")

        builtins.input = refuse
        self.menu._transform_copies()

    def test_sans_copie_produite_aucune_question_n_est_posee(self):
        os.remove(self.copie)
        os.remove(self.table)
        shutil.rmtree(self.dossier)

        def refuse(invite=""):
            raise AssertionError("rien à effacer, rien à demander")

        builtins.input = refuse
        self.menu._transform_copies()
        self.assertTrue(os.path.exists(self.etranger))


class TestMenuDerouleComplet(unittest.TestCase):
    """L'ordre du dialogue EST la règle : rapport, questions, marche à
    blanc, écriture. Une question posée avant de savoir ce qui sera touché
    n'est pas un consentement.

    Le moteur est bouchonné : ce qu'on éprouve ici est le CÂBLAGE — quels
    arguments partent, dans quel ordre, et ce qui arrête le déroulé.
    """

    def setUp(self):
        self.menu = _MenuBouchon()
        self.base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.base, True)
        self.source = os.path.join(self.base, "s.csv")
        with open(self.source, "w", encoding="utf-8") as flux:
            flux.write("etiquette\naboulie\n")
        self.ecran = io.StringIO()
        vrai_out = sys.stdout
        sys.stdout = self.ecran
        self.addCleanup(setattr, sys, "stdout", vrai_out)
        vrai_input = builtins.input
        self.addCleanup(setattr, builtins, "input", vrai_input)
        vrai_nav = _tm().todo_file_browser
        _tm().todo_file_browser = None
        self.addCleanup(setattr, _tm(), "todo_file_browser", vrai_nav)
        # `ensure` installerait un venv : ici le format est du pur stdlib.
        self.appels = []
        self.rendus = []
        self.menu._transform_run = self._run
        # Comme ci-dessus : l'écran réel bloquerait la suite.
        self.menu._transform_ecran = lambda *args: {}
        # Le rapport est un VRAI rapport, non une main écrite : la forme
        # que le rendu attend change avec le moteur, et une fixture à la
        # main dériverait sans qu'un test le voie.
        self.rapport = formats.report(self.source)

    def _run(self, arguments, fmt=None):
        self.appels.append((list(arguments), fmt))
        return self.rendus.pop(0) if self.rendus else None

    def _dialogue(self, *reponses):
        builtins.input = _Entrees(*reponses)

    def test_le_deroule_qui_aboutit_appelle_plan_PUIS_apply(self):
        self.rendus = [
            self.rapport,
            {"remplacees": 1, "fichiers": [os.path.join(self.base, "o.csv")]},
            {"remplacees": 1, "fichiers": [os.path.join(self.base, "o.csv")]},
        ]
        self._dialogue(
            self.source,  # le fichier
            "o",
            "",
            "",
            "",
            "",
            "",
            "",
            "",  # les questions
            os.path.join(self.base, "o.csv"),  # la destination
            "",  # écrire ? défaut oui
        )
        self.menu._transform_open_and_report()
        etapes = [a[0][0] for a in self.appels]
        self.assertEqual(etapes, ["--report", "--plan", "--apply"])

    def test_un_arret_annonce_par_le_moteur_stoppe_avant_les_questions(self):
        """Un `.xlsb` reconnu et illisible ici s'arrête là : poser les
        douze questions pour finir sur un refus est une perte de temps."""
        self.rendus = [dict(self.rapport, arret="Nothing to do.")]
        # L'arrêt vient du moteur : le rapport est complet, mais il dit
        # que rien ne peut être écrit.

        posees = []

        def refuse(invite=""):
            posees.append(invite)
            if len(posees) == 1:
                return self.source
            raise AssertionError("aucune question ne devait suivre l'arrêt")

        builtins.input = refuse
        self.menu._transform_open_and_report()
        self.assertEqual([a[0][0] for a in self.appels], ["--report"])

    def test_refuser_l_apercu_n_appelle_PAS_apply(self):
        self.rendus = [self.rapport, {"remplacees": 1}]
        self._dialogue(
            self.source,
            "o",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            os.path.join(self.base, "o.csv"),
            "n",
        )
        self.menu._transform_open_and_report()
        self.assertEqual(
            [a[0][0] for a in self.appels], ["--report", "--plan"]
        )

    def test_renoncer_aux_questions_n_appelle_ni_plan_ni_apply(self):
        self.rendus = [self.rapport]
        self._dialogue(self.source, "n")
        self.menu._transform_open_and_report()
        self.assertEqual([a[0][0] for a in self.appels], ["--report"])

    def test_la_table_par_defaut_est_passee_au_moteur(self):
        """Sans elle, un lot ne donne pas le même mot au même client."""
        self.rendus = [self.rapport, {"remplacees": 1}, {"remplacees": 1}]
        self._dialogue(
            self.source,
            "o",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            os.path.join(self.base, "o.csv"),
            "",
        )
        self.menu._transform_open_and_report()
        plan = self.appels[1][0]
        self.assertIn("--table", plan)
        table = plan[plan.index("--table") + 1]
        self.assertTrue(table.endswith(".table.json"), table)
        self.assertTrue(table.startswith(_tm().SORTIE_PAR_DEFAUT), table)

    def test_l_ecrasement_est_confirme_sur_les_fichiers_du_PLAN(self):
        """La marche à blanc dit les chemins réels ; confirmer sur la
        seule destination manquait ceux d'une conversion par feuille."""
        deja = os.path.join(self.base, "deja.csv")
        with open(deja, "w", encoding="utf-8") as flux:
            flux.write("z")
        self.rendus = [self.rapport, {"remplacees": 1, "fichiers": [deja]}]
        self._dialogue(
            self.source,
            "o",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            os.path.join(self.base, "o.csv"),
            "",
            "pas-le-bon-nom",
        )
        self.menu._transform_open_and_report()
        self.assertEqual(
            [a[0][0] for a in self.appels], ["--report", "--plan"]
        )
        self.assertIn(
            todo_i18n.t("Name does not match, nothing was written."),
            self.ecran.getvalue(),
        )

    def test_les_options_partent_en_json_analysable(self):
        self.rendus = [self.rapport, {"remplacees": 1}, {"remplacees": 1}]
        # Une source d'UNE feuille ne pose pas la question des feuilles.
        self._dialogue(
            self.source,
            "o",  # anonymiser
            "json",  # convertir
            "",  # table du lot — posée AVANT l'écran
            "id",  # colonnes intactes
            "",  # nombres
            "",  # texte
            "",  # en-têtes
            "7",  # graine
            os.path.join(self.base, "o.json"),
            "",  # écrire
        )
        self.menu._transform_open_and_report()
        plan = self.appels[1][0]
        options = json.loads(plan[plan.index("--options") + 1])
        self.assertEqual(options["conversion"], "json")
        self.assertEqual(options["colonnes_intactes"], ["id"])
        self.assertEqual(options["graine"], "7")
        self.assertTrue(options["destination"].endswith("o.json"))


def _colonne(
    etiquette, mini, maxi, distinctes, entiere=True, plancher=False, index=1
):
    return {
        "index": index,
        "etiquette": etiquette,
        "type": "nombre",
        "remplies": distinctes,
        "distinctes": distinctes,
        "min": mini,
        "max": maxi,
        "entiere": entiere,
        "plancher": plancher,
    }


def _rapport(colonnes, nom="F", format_lu="xlsx"):
    return {
        "format": format_lu,
        "feuilles": [{"nom": nom, "colonnes": colonnes}],
        "hors_cellules": {},
    }


class TestColonneSaturee(unittest.TestCase):
    """Une colonne d'entiers pleine ressort PERMUTÉE.

    Le tirage est sans remise et reste dans l'étendue mesurée : avec
    autant de valeurs distinctes que l'étendue compte d'entiers,
    l'ensemble de sortie EST l'ensemble d'entrée. Ce n'est pas une fuite —
    la permutation ne s'inverse pas sans la table — mais l'écran annonce
    « N nombres remplacés » et une comparaison d'ensembles ne montrerait
    rien.
    """

    OPTIONS = {"nombres": True, "colonnes_intactes": []}

    def _saturees(self, colonnes, **surcharges):
        options = dict(self.OPTIONS, **surcharges)
        return formats._colonnes_saturees(_rapport(colonnes), options)

    def test_une_etendue_pleine_est_signalee(self):
        """830 valeurs distinctes dans 830 entiers : aucune liberté."""
        self.assertEqual(
            self._saturees([_colonne("OrderID", 10248, 11077, 830)]),
            [("F", "OrderID")],
        )

    def test_une_etendue_large_ne_l_est_pas(self):
        self.assertEqual(
            self._saturees([_colonne("montant", 1, 100000, 830)]), []
        )

    def test_neuf_dixiemes_suffisent(self):
        """La copie porte déjà presque le même ensemble."""
        self.assertTrue(self._saturees([_colonne("k", 1, 100, 90)]))
        self.assertFalse(self._saturees([_colonne("k", 1, 100, 89)]))

    def test_une_colonne_decimale_n_est_jamais_saturee(self):
        """Entre deux entiers, un décimal a une infinité de places."""
        self.assertEqual(
            self._saturees([_colonne("taux", 1, 30, 30, entiere=False)]),
            [],
        )

    def test_une_petite_colonne_pleine_ne_dit_rien_de_personne(self):
        """Un drapeau à deux états, un mois sur douze : l'avertissement y
        serait du bruit, et le bruit finit par se lire comme du fond."""
        for etendue in (2, 12, 19):
            with self.subTest(etendue=etendue):
                self.assertEqual(
                    self._saturees([_colonne("m", 1, etendue, etendue)]), []
                )
        self.assertTrue(self._saturees([_colonne("m", 1, 20, 20)]))

    def test_une_colonne_plancheiee_n_entre_pas(self):
        """Elle n'est pas remplacée du tout, et `colonnes_ecartees` la
        nomme déjà."""
        self.assertEqual(
            self._saturees(
                [_colonne("partner_id", 1, 830, 830, plancher=True)]
            ),
            [],
        )

    def test_une_colonne_laissee_intacte_n_entre_pas(self):
        self.assertEqual(
            self._saturees(
                [_colonne("OrderID", 1, 830, 830)],
                colonnes_intactes={"OrderID"},
            ),
            [],
        )

    def test_sans_remplacement_des_nombres_rien_n_est_dit(self):
        self.assertEqual(
            self._saturees([_colonne("k", 1, 830, 830)], nombres=False), []
        )

    def test_un_compte_au_PLAFOND_ne_conclut_rien(self):
        """`_stats_colonnes` cesse de compter au-delà : le nombre ne dit
        plus combien la colonne porte, et rien n'en découle."""
        plafond = formats.PLAFOND_DISTINCTES
        self.assertEqual(
            self._saturees([_colonne("k", 1, plafond, plafond)]), []
        )

    def test_une_feuille_hors_selection_n_entre_pas(self):
        rapport = _rapport([_colonne("k", 1, 830, 830)], nom="Achats")
        options = dict(self.OPTIONS, feuilles=["Ventes"])
        self.assertEqual(formats._colonnes_saturees(rapport, options), [])

    def test_l_avertissement_est_dit_une_seule_fois(self):
        colonnes = [
            _colonne("a", 1, 830, 830, index=1),
            _colonne("b", 1, 830, 830, index=2),
        ]
        dits = formats._avertissements(_rapport(colonnes), self.OPTIONS)
        avis = [d for d in dits if "saturated" in d]
        self.assertEqual(len(avis), 1)
        self.assertIn(avis[0], todo_i18n.TRANSLATIONS)


class TestAvertissementDesNomsDeFeuille(unittest.TestCase):
    """Il ne vaut QUE pour le chemin qui les recopie tels quels.

    Toute conversion passe par un classeur neuf dont les onglets
    reçoivent un nom de la table, et `.xls` comme Access n'ont pas de
    graveur — leur copie repart par cette même conversion. Le dire quand
    ce n'est pas vrai apprend à ne plus lire la liste, qui EST la surface
    du consentement.
    """

    AVIS = "Sheet names are kept so formulas resolve; they may identify."

    def _dits(self, format_lu, conversion=""):
        return formats._avertissements(
            {"format": format_lu, "hors_cellules": {}, "feuilles": []},
            {"conversion": conversion},
        )

    def test_un_xlsx_sans_conversion_les_garde(self):
        self.assertIn(self.AVIS, self._dits("xlsx"))
        self.assertIn(self.AVIS, self._dits("xlsx", "xlsx"))

    def test_une_conversion_les_anonymise(self):
        for cible in ("csv", "json", "xml"):
            with self.subTest(cible=cible):
                self.assertNotIn(self.AVIS, self._dits("xlsx", cible))

    def test_xls_et_access_n_ont_pas_de_graveur(self):
        """Leur copie repart en .xlsx par la conversion, qui renomme."""
        for format_lu in ("xls", "access"):
            with self.subTest(format_lu=format_lu):
                self.assertNotIn(self.AVIS, self._dits(format_lu))

    def test_les_plages_nommees_suivent_la_meme_condition(self):
        avis = (
            "Range and table names are kept so formulas resolve;"
            " they may hold identifying strings."
        )
        garde = formats._avertissements(
            {
                "format": "xlsx",
                "hors_cellules": {"plages_nommees": 2},
                "feuilles": [],
            },
            {"conversion": ""},
        )
        convertit = formats._avertissements(
            {
                "format": "xlsx",
                "hors_cellules": {"plages_nommees": 2},
                "feuilles": [],
            },
            {"conversion": "csv"},
        )
        self.assertIn(avis, garde)
        self.assertNotIn(avis, convertit)


class _NavigateurBouchon:
    """Le navigateur de fichiers, réduit à son CONTRAT.

    Il appelle le rappel avec un chemin, puis sort de sa boucle — ce que
    le vrai fait aussi, `exit_program()` suivant l'appel dans son code.
    Le bouchonner à `None` sautait la branche entière, et c'est ainsi
    qu'un rappel introuvable a atteint le premier usage de l'entrée.
    """

    def __init__(self, rendu):
        self.rendu = rendu
        self.appele_avec = None

    def FileBrowser(self, depart, rappel, open_dir=False):
        self.depart = depart
        self.open_dir = open_dir
        navigateur = self

        class Fenetre:
            def run_main_frame(self):
                navigateur.appele_avec = navigateur.rendu
                rappel(navigateur.rendu)

        return Fenetre()


class TestMenuNavigateurDeFichiers(unittest.TestCase):
    """Le rappel que le navigateur appelle doit EXISTER sur la classe.

    Ce mixin fournit le sien : `TODO` nomme le sien `on_dir_selected`, et
    le préfixé vit sur le gestionnaire de bases, qui n'est pas un mixin.
    L'emprunter faisait lever `AttributeError` à l'ouverture du
    navigateur — donc sur la première ligne du menu, au premier usage.
    """

    def setUp(self):
        self.menu = _MenuBouchon()
        self.base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.base, True)
        self.ecran = io.StringIO()
        vrai_out = sys.stdout
        sys.stdout = self.ecran
        self.addCleanup(setattr, sys, "stdout", vrai_out)
        vrai_input = builtins.input
        self.addCleanup(setattr, builtins, "input", vrai_input)
        self.vrai_nav = _tm().todo_file_browser
        self.addCleanup(setattr, _tm(), "todo_file_browser", self.vrai_nav)

    def _navigateur(self, rendu):
        bouchon = _NavigateurBouchon(rendu)
        _tm().todo_file_browser = bouchon
        return bouchon

    def test_le_rappel_existe_sur_la_classe_d_accueil(self):
        """La vraie classe, non le bouchon : c'est `TODO` qui reçoit le
        mixin, et c'est là que le rappel manquait."""
        from script.todo.todo import TODO

        self.assertTrue(hasattr(TODO, "_on_dir_selected"))
        hote = TODO.__new__(TODO)
        hote._on_dir_selected("/tmp/choisi")
        self.assertEqual(hote._dir_path, "/tmp/choisi")

    def test_un_fichier_choisi_au_navigateur_est_rendu(self):
        chemin = os.path.join(self.base, "s.csv")
        with open(chemin, "w", encoding="utf-8") as flux:
            flux.write("a\n")
        self._navigateur(chemin)
        self.assertEqual(self.menu._transform_select_file(), chemin)

    def test_un_choix_qui_n_est_pas_un_fichier_retombe_sur_la_saisie(self):
        """Le navigateur peut rendre un répertoire : la saisie tranche."""
        self._navigateur(self.base)
        chemin = os.path.join(self.base, "s.csv")
        with open(chemin, "w", encoding="utf-8") as flux:
            flux.write("a\n")
        builtins.input = lambda invite="": chemin
        self.assertEqual(self.menu._transform_select_file(), chemin)

    def test_la_destination_passe_aussi_par_le_rappel(self):
        """Second appel du navigateur, en mode répertoire."""
        bouchon = self._navigateur(self.base)
        builtins.input = lambda invite="": "p"
        rendu = self.menu._transform_select_destination("s.xlsx", "xlsx")
        self.assertTrue(bouchon.open_dir)
        self.assertEqual(os.path.dirname(rendu), self.base)
        self.assertTrue(rendu.endswith(".xlsx"), rendu)

    def test_un_navigateur_absent_ne_leve_pas(self):
        """urwid peut manquer : « p » lèverait alors sur None."""
        _tm().todo_file_browser = None
        builtins.input = lambda invite="": "p"
        self.assertTrue(
            self.menu._transform_select_destination("s.xlsx", "xlsx")
        )


class TestGardeeSousSesDeuxFormes(unittest.TestCase):
    """Le filet cherche la valeur telle que la TABLE la porte.

    Un en-tête qui finit par une espace est annoncé remplacé sous sa forme
    brute — là où il est en portée — et n'était excusé que sous sa forme
    dépouillée là où il est gardé. Un fichier ordinaire dont une colonne
    s'intitule « Montant » avec une espace finale se faisait refuser.
    """

    def test_les_deux_formes_sont_notees(self):
        gardees = {}
        formats._noter_gardee(gardees, "F", "aboulie ")
        self.assertEqual(gardees["F"], {"aboulie ", "aboulie"})

    def test_une_valeur_sans_espace_n_est_notee_qu_une_fois(self):
        gardees = {}
        formats._noter_gardee(gardees, "F", "aboulie")
        self.assertEqual(gardees["F"], {"aboulie"})

    def test_le_seuil_du_filet_s_applique_aux_deux(self):
        """Sous le seuil, le filet ne cherche pas : le noter serait
        tolérer une chaîne qu'il n'examine jamais."""
        gardees = {}
        formats._noter_gardee(gardees, "F", " ab ")
        self.assertEqual(gardees.get("F"), {" ab "})

    def test_une_valeur_non_texte_traverse_sans_lever(self):
        gardees = {}
        formats._noter_gardee(gardees, "F", 12345)
        formats._noter_gardee(gardees, "F", None)
        self.assertEqual(gardees.get("F"), {"12345"})


class TestNomsDeColonneDeTableau(unittest.TestCase):
    """OOXML exige que `tableColumn.name` égale sa cellule d'en-tête, et
    que les noms d'un tableau soient DISTINCTS.

    Deux manquements, chacun grave à sa façon : un nom qu'aucune cellule
    ne porte laissait sortir le texte d'origine SANS que le filet puisse
    le voir — il n'a jamais été lu d'une cellule, donc jamais annoncé — et
    un en-tête de deux lignes donnait deux fois le même nom, ce qu'Excel
    annonce comme un fichier à réparer.
    """

    # La fonction ne touche que des ATTRIBUTS : un bouchon suffit, et le
    # test tourne alors sous l'interpréteur du CLI, qui n'a pas openpyxl.
    # Le faire par un vrai classeur l'aurait exclu de la suite.
    @staticmethod
    def _classeur(lignes, hauteur_entete=1, noms=("a", "b")):
        class Colonne:
            def __init__(self, nom):
                self.name = nom
                self.totalsRowLabel = None

        class Cellule:
            def __init__(self, ligne, colonne, valeur):
                self.row = ligne
                self.column = colonne
                self.value = valeur

        class Tableau:
            def __init__(self):
                self.ref = "A1:B%d" % len(lignes)
                self.headerRowCount = hauteur_entete
                self.tableColumns = [Colonne(n) for n in noms]

        class Onglet:
            tables = {}

            def __getitem__(self, adresse):
                assert adresse == "A1", adresse
                return Cellule(1, 1, None)

            def cell(self, row, column):
                ligne = lignes[row - 1] if row <= len(lignes) else []
                valeur = ligne[column - 1] if column <= len(ligne) else None
                return Cellule(row, column, valeur)

        class Classeur:
            def __init__(self, onglet):
                self.worksheets = [onglet]

        onglet = Onglet()
        tableau = Tableau()
        onglet.tables = {"T1": tableau}
        return Classeur(onglet), onglet, tableau

    def _noms(self, *args, **kwargs):
        classeur, _onglet, tableau = self._classeur(*args, **kwargs)
        formats._resynchroniser_tableaux(classeur)
        return [c.name for c in tableau.tableColumns]

    def test_le_nom_suit_la_cellule_d_en_tete(self):
        self.assertEqual(
            self._noms([["acai", "acanthe"], [1, 2]], noms=("vieux", "vieil")),
            ["acai", "acanthe"],
        )

    def test_un_en_tete_de_DEUX_lignes_prend_la_derniere(self):
        """La ligne de catégorie se répète souvent d'une colonne à
        l'autre : la prendre donnait deux noms identiques."""
        self.assertEqual(
            self._noms(
                [["cat", "cat"], ["acai", "acanthe"], [1, 2]],
                hauteur_entete=2,
                noms=("vieux", "vieil"),
            ),
            ["acai", "acanthe"],
        )

    def test_un_nom_sans_cellule_est_remplace_positionnellement(self):
        """Il sortait tel quel dans `xl/tables/`, hors d'atteinte du
        filet."""
        noms = self._noms(
            [[None, "acanthe"], [1, 2]], noms=("aboulie", "acai")
        )
        self.assertEqual(noms, ["colonne_1", "acanthe"])
        self.assertNotIn("aboulie", noms)

    def test_une_cellule_non_texte_ne_nomme_pas_une_colonne(self):
        noms = self._noms([[2024, "acanthe"], [1, 2]], noms=("aboulie", "x"))
        self.assertEqual(noms[0], "colonne_1")

    def test_deux_en_tetes_IDENTIQUES_se_distinguent(self):
        """Sans quoi le tableau porte deux fois le même nom."""
        noms = self._noms([["acai", "acai"], [1, 2]], noms=("v", "w"))
        self.assertEqual(len(set(noms)), 2, noms)
        self.assertEqual(noms[0], "acai")

    def test_le_libelle_de_ligne_de_total_part(self):
        """Il n'est jamais une cellule et survivait quelles que soient
        les options."""
        classeur, _o, tableau = self._classeur([["acai", "acanthe"], [1, 2]])
        tableau.tableColumns[0].totalsRowLabel = "aboulie"
        formats._resynchroniser_tableaux(classeur)
        self.assertIsNone(tableau.tableColumns[0].totalsRowLabel)


class TestLitterauxDeFormule(unittest.TestCase):
    """Ce qu'une formule PRÉSERVE, et que le filet doit donc excuser.

    Les guillemets ne suffisent pas : une référence structurée de tableau
    porte le nom de colonne entre CROCHETS et sans guillemets. Toutes les
    cellules d'une colonne calculée partagent le même texte, si bien que
    le bloc toléré ne l'excuse qu'une fois là où la copie le porte deux
    fois — dans la feuille et dans `xl/tables/`.
    """

    def test_une_reference_structuree_rend_le_nom_de_colonne(self):
        rendu = set(
            formats._litteraux_de_formule("=T1[[#This Row],[Montant]]*S$5")
        )
        self.assertIn("Montant", rendu)
        self.assertIn("#This Row", rendu)

    def test_un_littéral_entre_guillemets_reste_rendu(self):
        self.assertIn(
            "aboulie",
            formats._litteraux_de_formule('=IF(A1="aboulie",1,0)'),
        )

    def test_le_texte_ENTIER_est_rendu_aussi(self):
        """La tolérance d'origine : le filet compte les occurrences dans
        le bloc joint, et le texte complet y participe."""
        self.assertIn("=A1+1", formats._litteraux_de_formule("=A1+1"))

    def test_une_valeur_texte_NUE_ne_tolère_rien(self):
        """La garde sur « = » porte tout le filet : sans elle, la
        fonction étant appelée sur chaque cellule, toute valeur texte
        serait tolérée et plus rien ne serait refusé."""
        for valeur in ("Montant", "aboulie", "", "  ", "A1+1"):
            with self.subTest(valeur=valeur):
                self.assertEqual(
                    set(formats._litteraux_de_formule(valeur)), set()
                )

    def test_un_nom_a_espace_finale_garde_son_espace(self):
        """Le nom réel est celui que la formule porte, espaces compris :
        le dépouiller ne l'aurait jamais fait correspondre."""
        self.assertIn(
            "expected 1 ",
            formats._litteraux_de_formule("=T[[#This Row],[expected 1 ]]"),
        )

    def test_l_apostrophe_d_echappement_est_retirée(self):
        """Excel échappe `[`, `]`, `#` et l'apostrophe par une
        apostrophe : le nom réel est la forme déséchappée."""
        rendu = formats._litteraux_de_formule("=T[[#This Row],[a'#b]]")
        self.assertIn("a#b", rendu)

    def test_une_formule_matricielle_n_est_pas_une_chaine(self):
        """Un objet à `text` : le tester par `startswith` la faisait
        passer inaperçue."""

        class Matricielle:
            text = "=T[[#This Row],[acanthe]]"

        self.assertIn("acanthe", formats._litteraux_de_formule(Matricielle()))

    def test_sans_egal_pour_un_texte_que_l_appelant_SAIT_etre_une_formule(
        self,
    ):
        """OOXML omet le « = » dans `calculatedColumnFormula`. Le drapeau
        est réservé aux appelants qui lisent une partie de FORMULE : le
        passer sur une cellule rouvrirait le trou que la garde ferme."""
        self.assertIn(
            "acanthe",
            formats._litteraux_de_formule(
                "T[[#This Row],[acanthe]]", sans_egal=True
            ),
        )
        self.assertEqual(
            set(formats._litteraux_de_formule("T[[#This Row],[acanthe]]")),
            set(),
        )

    def test_ni_none_ni_un_nombre_ne_lèvent(self):
        for valeur in (None, 12345, 3.5, True):
            with self.subTest(valeur=valeur):
                self.assertEqual(
                    set(formats._litteraux_de_formule(valeur)), set()
                )


class TestValeursGardeesDesFormules(unittest.TestCase):
    """La collecte doit appeler la fonction là où les formules vivent.

    Deux endroits : la grille, et la formule PROPRE d'une colonne de
    tableau — celle-là vit dans `xl/tables/`, ne passe par aucune cellule,
    et son nom de colonne n'était excusé par personne.
    """

    @staticmethod
    def _classeur(valeurs_de_cellule=(), formule_de_colonne=None):
        """Un bouchon : la fonction ne lit que des attributs, si bien que
        le test tourne sous l'interpréteur du CLI, sans openpyxl."""

        class Cellule:
            def __init__(self, valeur):
                self.value = valeur

        class Colonne:
            def __init__(self, formule):
                self.calculatedColumnFormula = formule
                self.totalsRowFormula = None

        class Tableau:
            def __init__(self, formule):
                self.tableColumns = [Colonne(formule)]

        class Noms(dict):
            pass

        class Onglet:
            title = "T"
            defined_names = Noms()

            def __init__(self):
                self.tables = (
                    {"T1": Tableau(formule_de_colonne)}
                    if formule_de_colonne is not None
                    else {}
                )

            def iter_rows(self):
                yield [Cellule(v) for v in valeurs_de_cellule]

        class Classeur:
            defined_names = Noms()

            def __init__(self, onglet):
                self.worksheets = [onglet]

        return Classeur(Onglet())

    def _gardees(self, **kwargs):
        return formats._valeurs_gardees(self._classeur(**kwargs), [], "xlsx")

    def test_une_formule_de_CELLULE_est_dépouillée(self):
        gardees = self._gardees(
            valeurs_de_cellule=("=T1[[#This Row],[Montant]]*2",)
        )
        self.assertIn("Montant", gardees)

    def test_une_formule_de_COLONNE_de_tableau_aussi(self):
        """Elle vit dans `xl/tables/` et ne passe par aucune cellule."""

        class Formule:
            text = "T1[[#This Row],[acanthe]]*2"

        gardees = self._gardees(formule_de_colonne=Formule())
        self.assertIn("acanthe", gardees)

    def test_une_valeur_texte_de_cellule_n_est_PAS_tolérée(self):
        """Sinon le filet ne refuserait plus rien."""
        gardees = self._gardees(valeurs_de_cellule=("aboulie", "acai"))
        self.assertNotIn("aboulie", gardees)
        self.assertNotIn("acai", gardees)

    def test_un_classeur_sans_tableau_ne_lève_pas(self):
        self.assertIsInstance(self._gardees(), set)


def _corps(hauteur=8):
    """Un corps de tableau réaliste : trois formes de colonne distinctes."""
    return [
        ["IN%06d" % (137784 + i), 1028 + i, 100.5 + i] for i in range(hauteur)
    ]


class TestLigneDeChamps(unittest.TestCase):
    """La ligne d'en-tête est MESURÉE, non présumée.

    La présumer en ligne 1 est faux dans les deux sens : un rapport dont
    A1 porte un titre a son en-tête plus bas, et une feuille sans en-tête
    voyait sa première ligne de DONNÉES recopiée en clair.
    """

    ENTETE = ["N° facture", "N° magasin", "Montant"]

    def test_un_en_tete_en_ligne_1_est_trouve(self):
        empan, champs = formats.lignes_entete([self.ENTETE] + _corps())
        self.assertEqual(empan, {1})
        self.assertEqual(champs, 1)

    def test_un_titre_en_A1_repousse_l_en_tete(self):
        """Le cas qui motive la mesure : la ligne 1 n'est pas l'en-tête."""
        lignes = [
            ["Rapport annuel", None, None],
            [None, None, None],
            self.ENTETE,
        ] + _corps()
        empan, champs = formats.lignes_entete(lignes)
        self.assertEqual(champs, 3)
        self.assertEqual(empan, {1, 2, 3})

    def test_une_feuille_SANS_en_tete_n_en_invente_pas(self):
        """Sa ligne 1 est de la donnée : la garder la recopiait en clair."""
        empan, champs = formats.lignes_entete(_corps())
        self.assertEqual(empan, set())
        self.assertIsNone(champs)

    def test_une_ligne_de_categorie_ne_nomme_pas_les_colonnes(self):
        """Elle répète un mot sur plusieurs colonnes : la retenir donnait
        deux colonnes de même nom, ce qu'OOXML refuse."""
        lignes = [["Bloc", "Bloc", "Bloc"], self.ENTETE] + _corps()
        empan, champs = formats.lignes_entete(lignes)
        self.assertEqual(champs, 2)
        self.assertEqual(empan, {1, 2})

    def test_l_empan_s_arrete_a_la_premiere_ligne_de_donnees(self):
        """Ce qui surmonte la ligne de champs sans être des données est de
        la mise en page ; une ligne de données borne la remontée."""
        lignes = [self.ENTETE] + _corps()
        empan, _champs = formats.lignes_entete(lignes)
        self.assertEqual(empan, {1})

    def test_au_dela_des_lignes_sondees_on_ne_cherche_plus(self):
        """Un en-tête plus bas n'est pas un tableau, c'est une mise en
        page — et l'opérateur corrige mieux qu'une mesure."""
        bourrage = [[None, None, None]] * formats.LIGNES_SONDEES
        empan, champs = formats.lignes_entete(
            bourrage + [self.ENTETE] + _corps()
        )
        self.assertEqual(empan, set())
        self.assertIsNone(champs)

    def test_une_feuille_vide_ou_d_une_ligne_ne_leve_pas(self):
        for lignes in ([], [self.ENTETE], [[]]):
            with self.subTest(lignes=lignes):
                self.assertEqual(formats.lignes_entete(lignes), (set(), None))


class TestFormeDeValeur(unittest.TestCase):
    """La signature de forme : ce qui sépare un nom de champ d'une donnée
    là où le TYPE ne dit rien, les deux étant du texte."""

    def test_deux_valeurs_du_meme_moule_ont_une_seule_forme(self):
        self.assertEqual(
            formats._forme_de_valeur("IN137784"),
            formats._forme_de_valeur("ORD154711"),
        )

    def test_les_longueurs_ne_distinguent_pas(self):
        """Les répétitions sont écrasées : « 99999 » et « 999999 » sont
        une forme, sinon chaque longueur ferait une forme à part."""
        self.assertEqual(
            formats._forme_de_valeur(12345),
            formats._forme_de_valeur(1234567),
        )

    def test_un_nom_de_champ_se_distingue_de_ses_donnees(self):
        self.assertNotEqual(
            formats._forme_de_valeur("N° facture"),
            formats._forme_de_valeur("IN137784"),
        )

    def test_une_date_et_un_nombre_ne_se_confondent_pas(self):
        self.assertNotEqual(
            formats._forme_de_valeur("2023-04-21"),
            formats._forme_de_valeur(20230421),
        )

    def test_none_rend_la_forme_vide(self):
        self.assertEqual(formats._forme_de_valeur(None), "")

    def test_l_accord_est_HAUT_sur_une_ligne_de_donnees(self):
        """C'est le sens du signal : ressembler à ses données, c'en être."""
        lignes = _corps()
        self.assertGreaterEqual(formats._accord_de_forme(lignes, 1), 0.9)

    def test_l_accord_est_BAS_sur_une_ligne_de_champs(self):
        lignes = [["N° facture", "N° magasin", "Montant"]] + _corps()
        self.assertLessEqual(
            formats._accord_de_forme(lignes, 1),
            formats.ACCORD_DE_DONNEE,
        )

    def test_sans_corps_sous_la_ligne_il_n_y_a_pas_de_verdict(self):
        """Rien à comparer n'est pas « c'est un en-tête »."""
        self.assertIsNone(formats._accord_de_forme([["a", "b"]], 1))
        self.assertIsNone(formats._signaux_entete([["a", "b"]], 1))


class TestEtiquettesDeLaLigneDeChamps(unittest.TestCase):
    """`Feuille.etiquettes` suit la ligne de champs, non la ligne 1."""

    def test_les_etiquettes_viennent_de_la_ligne_de_champs(self):
        feuille = formats.Feuille(
            "F", [["titre", None], ["nom", "montant"], ["x", 1]]
        )
        feuille.ligne_champs = 2
        self.assertEqual(feuille.etiquettes, ["nom", "montant"])

    def test_sans_ligne_de_champs_il_n_y_a_pas_d_etiquette(self):
        """Le plancher répond alors par l'INDEX : les prendre sur une
        ligne de données faisait planchéier au hasard."""
        feuille = formats.Feuille("F", [["x", 1], ["y", 2]])
        feuille.ligne_champs = None
        self.assertEqual(feuille.etiquettes, [])

    def test_la_ligne_1_reste_le_defaut(self):
        """Les lecteurs qui FABRIQUENT leur ligne 1 la connaissent
        d'avance : Access, JSON et XML n'ont rien à mesurer."""
        feuille = formats.Feuille("F", [["cle", "valeur"], ["a", 1]])
        self.assertEqual(feuille.ligne_champs, 1)
        self.assertEqual(feuille.etiquettes, ["cle", "valeur"])

    def test_une_ligne_de_champs_hors_des_lignes_ne_leve_pas(self):
        feuille = formats.Feuille("F", [["a"]])
        feuille.ligne_champs = 9
        self.assertEqual(feuille.etiquettes, [])


class TestUniciteDesClesI18n(unittest.TestCase):
    """Une clé dupliquée dans un littéral de dict Python écrase la
    précédente, sans erreur ni avertissement.

    Les deux entrées peuvent être identiques aujourd'hui : le jour où l'on
    corrige l'une, la correction se perd en silence, et aucun test
    d'intégrité existant ne regarde les DOUBLONS — ils lisent le dict
    déjà construit, où le doublon a déjà disparu. D'où la lecture par AST
    du fichier SOURCE.
    """

    @staticmethod
    def _cles_du_source():
        import ast

        chemin = os.path.join(
            os.path.dirname(__file__),
            "..",
            "script",
            "todo",
            "todo_i18n.py",
        )
        with open(chemin, encoding="utf-8") as flux:
            arbre = ast.parse(flux.read())
        for noeud in ast.walk(arbre):
            if not isinstance(noeud, ast.Assign):
                continue
            if getattr(noeud.targets[0], "id", "") != "TRANSLATIONS":
                continue
            return [
                cle.value
                for cle in noeud.value.keys
                if isinstance(cle, ast.Constant) and isinstance(cle.value, str)
            ]
        return []

    def test_le_dict_source_a_bien_ete_lu(self):
        """Si la forme du fichier change, ce test doit tomber ici plutôt
        que de déclarer « aucun doublon » sur une liste vide."""
        self.assertGreater(len(self._cles_du_source()), 1000)

    def test_aucune_cle_n_est_declaree_deux_fois(self):
        import collections

        compte = collections.Counter(self._cles_du_source())
        doubles = sorted(k for k, n in compte.items() if n > 1)
        self.assertEqual(doubles, [], "clés déclarées deux fois")


class TestPorteeDeLEmpanDEnTete(unittest.TestCase):
    """La portée obéit à l'empan mesuré — l'endroit où une erreur laisse
    sortir de la donnée.

    Le défaut de l'ABSENCE porte tout : un appelant qui ne mesure pas
    mettrait la ligne de champs en portée, ses libellés remplacés et la
    copie illisible. Une clé PRÉSENTE et vide veut dire « pas d'en-tête ».
    """

    BASE = {"entetes": False, "colonnes_intactes": set()}

    def test_la_cle_ABSENTE_garde_la_ligne_1(self):
        """Le comportement d'avant la mesure : le gabarit d'options des
        tests de portée ne porte que quelques clés."""
        self.assertFalse(noyau.cellule_en_portee("F", 1, 1, dict(self.BASE)))
        self.assertTrue(noyau.cellule_en_portee("F", 2, 1, dict(self.BASE)))

    def test_la_cle_PRESENTE_ET_VIDE_met_la_ligne_1_en_portee(self):
        """C'est le correctif de la fuite : une feuille sans en-tête voit
        sa première ligne de DONNÉES anonymisée."""
        options = dict(self.BASE, lignes_entete=set())
        self.assertTrue(noyau.cellule_en_portee("F", 1, 1, options))

    def test_un_empan_de_deux_lignes_les_garde_toutes_les_deux(self):
        options = dict(self.BASE, lignes_entete={("F", 1), ("F", 2)})
        self.assertFalse(noyau.cellule_en_portee("F", 1, 1, options))
        self.assertFalse(noyau.cellule_en_portee("F", 2, 1, options))
        self.assertTrue(noyau.cellule_en_portee("F", 3, 1, options))

    def test_l_empan_est_PAR_FEUILLE(self):
        """Garder la ligne 3 d'une feuille ne garde pas la ligne 3 des
        autres : l'empan est mesuré feuille par feuille."""
        options = dict(self.BASE, lignes_entete={("A", 3)})
        self.assertFalse(noyau.cellule_en_portee("A", 3, 1, options))
        self.assertTrue(noyau.cellule_en_portee("B", 3, 1, options))

    def test_repondre_oui_a_l_en_tete_met_tout_en_portee(self):
        """L'option existante garde sa parole : l'empan ne la contredit
        pas."""
        options = dict(
            self.BASE, entetes=True, lignes_entete={("F", 1), ("F", 2)}
        )
        self.assertTrue(noyau.cellule_en_portee("F", 1, 1, options))

    def test_preparer_pose_TOUJOURS_la_cle(self):
        """Sinon l'absence — qui veut dire « ligne 1 » — s'appliquerait à
        une feuille dont l'en-tête est ailleurs."""
        base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, base, True)
        source = os.path.join(base, "s.csv")
        with open(source, "w", encoding="utf-8") as flux:
            flux.write("etiquette,montant,date\n")
            flux.write("aboulie,12,2019-01-02\n")
            flux.write("acai,13,2019-01-03\n")
        _f, _feuilles, _c, _r, options = formats._preparer(source, {})
        self.assertIn("lignes_entete", options)
        # Le nom vient du module : un csv n'a pas d'onglet, et coder son
        # nom en dur dans le test ferait tomber au premier renommage.
        self.assertEqual(
            options["lignes_entete"],
            {(formats.NOM_FEUILLE_NEUTRE, 1)},
        )


class TestMesurerEntetes(unittest.TestCase):
    """Quatre sources, dans un ordre qui n'est pas négociable."""

    ENTETE = ["etiquette", "montant", "date", "code"]
    CORPS = [
        ["aboulie", 1200, "2019-01-02", "A1"],
        ["acai", 830, "2019-01-03", "B2"],
        ["adobe", 940, "2019-01-04", "C3"],
    ]

    @classmethod
    def _feuille(cls, nom="F", lignes=None):
        """Types MÊLÉS : le régime où la mesure tranche. Une grille
        étroite et tout-alphabétique ne se décide pas."""
        return formats.Feuille(
            nom, lignes if lignes is not None else [cls.ENTETE] + cls.CORPS
        )

    def test_la_correction_de_l_operateur_passe_avant_tout(self):
        feuille = self._feuille()
        feuille.entete_declaree = {1}
        formats.mesurer_entetes([feuille], "xlsx", {"F": [2, 3]})
        self.assertEqual(feuille.lignes_entete, {2, 3})
        self.assertEqual(feuille.ligne_champs, 3)

    def test_la_DECLARATION_du_fichier_passe_avant_la_mesure(self):
        """`_resynchroniser_tableaux` lit déjà `headerRowCount` pour
        nommer les colonnes d'un tableau : deux notions d'en-tête qui se
        contredisent feraient renommer depuis une ligne anonymisée."""
        feuille = self._feuille(lignes=[["cat"] * 4, self.ENTETE] + self.CORPS)
        feuille.entete_declaree = {1, 2}
        formats.mesurer_entetes([feuille], "xlsx")
        self.assertEqual(feuille.lignes_entete, {1, 2})
        self.assertEqual(feuille.ligne_champs, 2)

    def test_un_lecteur_qui_FABRIQUE_sa_ligne_1_ne_mesure_rien(self):
        for format_lu in formats.FORMATS_ENTETE_FABRIQUEE:
            with self.subTest(format_lu=format_lu):
                # Une grille SANS en-tête : la mesure rendrait
                # `set()`, et le défaut du lecteur doit l'emporter.
                feuille = self._feuille(lignes=self.CORPS)
                formats.mesurer_entetes([feuille], format_lu)
                self.assertEqual(feuille.lignes_entete, {1})

    def test_une_correction_vide_veut_dire_PAS_d_en_tete(self):
        feuille = self._feuille()
        formats.mesurer_entetes([feuille], "csv", {"F": []})
        self.assertEqual(feuille.lignes_entete, set())
        self.assertIsNone(feuille.ligne_champs)

    def test_une_correction_ne_touche_pas_les_autres_feuilles(self):
        une, deux = self._feuille("A"), self._feuille("B")
        formats.mesurer_entetes([une, deux], "csv", {"A": []})
        self.assertEqual(une.lignes_entete, set())
        self.assertEqual(deux.ligne_champs, 1)


class TestCorpsSousLEmpan(unittest.TestCase):
    """Les lignes de DONNÉES : ce qui suit la dernière ligne d'en-tête."""

    def test_le_corps_saute_tout_l_empan(self):
        feuille = formats.Feuille(
            "F", [["cat", "cat"], ["a", "b"], ["x", 1], ["y", 2]]
        )
        feuille.lignes_entete = {1, 2}
        self.assertEqual(formats.corps(feuille), [["x", 1], ["y", 2]])

    def test_sans_en_tete_le_corps_est_TOUTE_la_grille(self):
        """Sinon la première ligne de données devient les noms de clé :
        en clair dans la copie, et perdue comme donnée."""
        feuille = formats.Feuille("F", [["x", 1], ["y", 2]])
        feuille.lignes_entete = set()
        self.assertEqual(formats.corps(feuille), [["x", 1], ["y", 2]])

    def test_des_noms_neutres_remplacent_l_en_tete_absent(self):
        feuille = formats.Feuille("F", [["x", 1, 2], ["y", 3, 4]])
        self.assertEqual(
            formats._noms_neutres(feuille),
            ["colonne_1", "colonne_2", "colonne_3"],
        )


class TestValeurDExemple(unittest.TestCase):
    """Une valeur montrable : toujours une `str`, toujours bornée.

    C'est la seule colonne du rapport qui porte de la donnée du client à
    l'écran, et la charge utile traverse un `json.dump` en
    `allow_nan=False` : ce qui échoue là échoue APRÈS tout le travail du
    moteur, et l'écran n'affiche alors qu'une trace.
    """

    def test_tout_rendu_est_une_chaine(self):
        import datetime

        for valeur in (
            None,
            0,
            0.0,
            False,
            True,
            1200,
            "aboulie",
            datetime.date(2019, 1, 2),
            b"\x00\xff",
        ):
            with self.subTest(valeur=valeur):
                self.assertIsInstance(formats.valeur_d_exemple(valeur), str)

    def test_le_zero_et_le_faux_ne_s_effacent_pas(self):
        """`or ""` les écrasait : une colonne de montants nuls montrait
        des exemples vides."""
        self.assertEqual(formats.valeur_d_exemple(0), "0")
        self.assertEqual(formats.valeur_d_exemple(0.0), "0.0")
        self.assertEqual(formats.valeur_d_exemple(False), "False")

    def test_des_octets_ne_sortent_pas_en_clair(self):
        """`valeur_hors_tableur` tomberait sur son `str()` final et
        rendrait le `repr` d'un `bytes` — du binaire lisible."""
        rendu = formats.valeur_d_exemple(b"\x00\xff\x00")
        self.assertNotIn("\\x", rendu)
        self.assertIn("3", rendu)

    def test_un_flottant_non_fini_ne_casse_pas_la_serialisation(self):
        """`allow_nan=False` lèverait, et le moteur aurait tout fait."""
        for valeur in (float("nan"), float("inf"), -float("inf")):
            with self.subTest(valeur=valeur):
                self.assertEqual(formats.valeur_d_exemple(valeur), "")

    def test_une_valeur_longue_est_bornee_et_le_dit(self):
        rendu = formats.valeur_d_exemple("x" * 5000)
        self.assertEqual(len(rendu), formats.EXEMPLE_LONGUEUR)
        self.assertTrue(rendu.endswith("…"))


class TestRapportDeLEnTete(unittest.TestCase):
    """Ce que le rapport DIT de la mesure, pour qu'une invention se lise
    avant d'être consentie."""

    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.base, True)

    def _rapport(self, contenu, nom="s.csv"):
        chemin = os.path.join(self.base, nom)
        with open(chemin, "w", encoding="utf-8") as flux:
            flux.write(contenu)
        return formats.report(chemin)

    AVEC = (
        "etiquette,montant,date,code\n"
        "aboulie,1200,2019-01-02,A1\n"
        "acai,830,2019-01-03,B2\n"
        "adobe,940,2019-01-04,C3\n"
    )
    SANS = (
        "IN137784,1028,100.5\n" "IN137785,1029,101.5\n" "IN137786,1030,102.5\n"
    )

    def test_l_empan_est_une_LISTE_serialisable(self):
        """Un set ne passe pas `json.dump`, et ce rapport traverse un
        sous-processus."""
        feuille = self._rapport(self.AVEC)["feuilles"][0]
        self.assertEqual(feuille["lignes_entete"], [1])
        self.assertEqual(feuille["ligne_champs"], 1)
        json.dumps(feuille, allow_nan=False)

    def test_sans_en_tete_le_rapport_le_dit(self):
        feuille = self._rapport(self.SANS)["feuilles"][0]
        self.assertEqual(feuille["lignes_entete"], [])
        self.assertIsNone(feuille["ligne_champs"])
        self.assertIsNone(feuille["entete_mesure"])

    def test_les_cinq_mesures_sont_affichables(self):
        """L'opérateur voit POURQUOI la mesure a tranché avant de la
        contredire."""
        mesure = self._rapport(self.AVEC)["feuilles"][0]["entete_mesure"]
        self.assertEqual(
            sorted(mesure),
            ["accord", "contraste", "distinct", "hors_colonne", "rempli"],
        )
        for cle, valeur in mesure.items():
            with self.subTest(cle=cle):
                self.assertIsInstance(valeur, float)
                self.assertLessEqual(valeur, 1.0)

    def test_chaque_colonne_montre_des_exemples(self):
        """CE qui distingue deux colonnes sans libellé : ni le type, ni le
        compte, ni les bornes n'y suffisent."""
        colonnes = self._rapport(self.AVEC)["feuilles"][0]["colonnes"]
        for colonne in colonnes:
            with self.subTest(colonne=colonne["index"]):
                self.assertTrue(colonne["exemples"])
                self.assertLessEqual(
                    len(colonne["exemples"]), formats.EXEMPLES_PAR_COLONNE
                )

    def test_les_exemples_sont_des_valeurs_DISTINCTES(self):
        """Trois fois la même ne montre rien de la colonne."""
        rapport = self._rapport(
            "etiquette,constante,date\n"
            "aboulie,7,2019-01-02\n"
            "acai,7,2019-01-03\n"
            "adobe,7,2019-01-04\n"
        )
        par_index = {
            c["index"]: c["exemples"]
            for c in rapport["feuilles"][0]["colonnes"]
        }
        self.assertEqual(par_index[2], ["7"])
        self.assertEqual(len(par_index[1]), 3)

    def test_l_en_tete_de_la_ligne_de_champs_n_est_pas_un_exemple(self):
        """Les statistiques sautent l'empan : le libellé n'est pas une
        valeur de sa colonne."""
        colonnes = self._rapport(self.AVEC)["feuilles"][0]["colonnes"]
        self.assertNotIn("etiquette", colonnes[0]["exemples"])


class TestColonneRepondue(unittest.TestCase):
    """La règle des colonnes laissées intactes, en UN endroit.

    Elle vivait en trois copies — la portée, les colonnes écartées, les
    colonnes saturées — donc trois occasions de divergence. Et l'ensemble
    était GLOBAL : répondre « 3 » gelait la colonne 3 des dix feuilles
    d'un classeur, si bien qu'un écran laissant cocher la colonne 3 de la
    septième feuille aurait tenu une promesse fausse.
    """

    def test_l_ensemble_plat_reste_global(self):
        """La question textuelle répond comme avant : elle ne sait pas de
        quelle feuille elle parle."""
        options = {"colonnes_intactes": {"3"}}
        self.assertTrue(noyau.colonne_repondue("A", 3, None, options))
        self.assertTrue(noyau.colonne_repondue("B", 3, None, options))

    def test_l_ensemble_par_feuille_ne_vaut_QUE_pour_elle(self):
        options = {"colonnes_intactes_par_feuille": {"A": {"ref"}}}
        self.assertTrue(noyau.colonne_repondue("A", 5, "ref", options))
        self.assertFalse(noyau.colonne_repondue("B", 5, "ref", options))

    def test_l_index_ne_repond_que_sans_etiquette(self):
        """Sinon « 1 » désigne à la fois la colonne étiquetée « 1 » et la
        première colonne, et une réponse en épargne deux."""
        options = {"colonnes_intactes": {"3"}}
        self.assertFalse(noyau.colonne_repondue("A", 3, "nom", options))
        self.assertTrue(noyau.colonne_repondue("A", 3, None, options))
        self.assertTrue(noyau.colonne_repondue("A", 3, "   ", options))

    def test_les_deux_ensembles_se_cumulent(self):
        options = {
            "colonnes_intactes": {"nom"},
            "colonnes_intactes_par_feuille": {"A": {"ref"}},
        }
        self.assertTrue(noyau.colonne_repondue("A", 1, "nom", options))
        self.assertTrue(noyau.colonne_repondue("A", 2, "ref", options))
        self.assertTrue(noyau.colonne_repondue("B", 1, "nom", options))
        self.assertFalse(noyau.colonne_repondue("B", 2, "ref", options))

    def test_sans_aucune_reponse_rien_n_est_gele(self):
        for options in (
            {},
            {"colonnes_intactes": set()},
            {"colonnes_intactes_par_feuille": {}},
        ):
            with self.subTest(options=options):
                self.assertFalse(
                    noyau.colonne_repondue("A", 1, "nom", options)
                )

    def test_la_portee_reprend_la_meme_regle(self):
        """Le test qui lie les deux : une divergence entre la portée et
        cette règle laisserait sortir une colonne annoncée gelée."""
        options = {
            "entetes": False,
            "lignes_entete": {("A", 1)},
            "colonnes_intactes_par_feuille": {"A": {"ref"}},
            "etiquettes": {("A", 2): "ref"},
        }
        self.assertFalse(noyau.cellule_en_portee("A", 2, 2, options))
        self.assertTrue(noyau.cellule_en_portee("B", 2, 2, options))

    def test_preparer_normalise_le_par_feuille(self):
        """Un dict {nom: [str]} traverse le sous-processus ; l'espace
        autour d'une réponse tapée à la main ne doit pas la manquer."""
        base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, base, True)
        source = os.path.join(base, "s.csv")
        with open(source, "w", encoding="utf-8") as flux:
            flux.write("etiquette,montant,date\n")
            flux.write("aboulie,12,2019-01-02\n")
            flux.write("acai,13,2019-01-03\n")
        _f, _fe, _c, _r, options = formats._preparer(
            source,
            {
                "colonnes_intactes_par_feuille": {
                    formats.NOM_FEUILLE_NEUTRE: [" montant ", ""]
                }
            },
        )
        self.assertEqual(
            options["colonnes_intactes_par_feuille"],
            {formats.NOM_FEUILLE_NEUTRE: {"montant"}},
        )


class TestMenuEcranDePerimetre(unittest.TestCase):
    """L'ouverture de l'écran, et ses TROIS issues.

    La spec porte le périmètre, `{}` demande les invites, `None`
    annule. Confondre les deux dernières supprimerait le repli textuel en
    silence.
    """

    RAPPORT = {"feuilles": [{"nom": "F", "colonnes": []}]}

    def setUp(self):
        self.menu = _MenuBouchon()
        self.ecran = io.StringIO()
        vrai_out = sys.stdout
        sys.stdout = self.ecran
        self.addCleanup(setattr, sys, "stdout", vrai_out)
        vrai_input = builtins.input
        self.addCleanup(setattr, builtins, "input", vrai_input)

    def _repondre(self, reponse):
        builtins.input = lambda invite="": reponse

    def test_refuser_l_ecran_rend_un_dict_VIDE(self):
        """Et non None : l'appelant enchaîne sur les invites."""
        self._repondre("n")
        self.assertEqual(self.menu._transform_ecran(self.RAPPORT), {})

    def test_zero_annule_tout(self):
        self._repondre("0")
        self.assertIsNone(self.menu._transform_ecran(self.RAPPORT))

    def test_un_rapport_sans_feuille_ne_pose_pas_la_question(self):
        def refuse(invite=""):
            raise AssertionError("rien à montrer, rien à demander")

        builtins.input = refuse
        self.assertEqual(self.menu._transform_ecran({"feuilles": []}), {})

    def _bouchonner(self, ecran, contexte=None):
        """Remplacer la fonction SUR le vrai module.

        Injecter un faux module dans `sys.modules` n'a aucun effet dès
        que le vrai a été importé : `from script.todo import
        transform_form` lit l'attribut du PAQUET, déjà posé. Le test
        lançait alors le VRAI écran, qui attend un terminal — et la suite
        se bloquait dès qu'un autre fichier avait importé le module.
        """
        from script.todo import transform_form

        for nom, valeur in (
            ("run_transform_form", ecran),
            (
                "contexte_depuis_rapport",
                contexte or (lambda *args: {}),
            ),
        ):
            vrai = getattr(transform_form, nom)
            setattr(transform_form, nom, valeur)
            self.addCleanup(setattr, transform_form, nom, vrai)

    def test_le_defaut_est_OUI(self):
        """L'écran est la réponse aux deux questions qu'une invite ne sait
        pas poser : le proposer par défaut est le sens de l'entrée."""
        appels = []
        self._repondre("")

        def faux_ecran(ctx):
            appels.append(ctx)
            return {"colonnes_intactes_par_feuille": {}}

        self._bouchonner(faux_ecran, lambda *args: {"vu": True})
        rendu = self.menu._transform_ecran(self.RAPPORT)
        self.assertEqual(appels, [{"vu": True}])
        self.assertEqual(rendu, {"colonnes_intactes_par_feuille": {}})

    def test_un_ecran_qui_leve_ne_perd_pas_le_travail(self):
        """Sans terminal, il ne peut pas s'ouvrir : les invites savent
        tout demander, et emporter le travail serait pire."""
        self._repondre("o")

        def tombe(ctx):
            raise RuntimeError("pas de terminal")

        self._bouchonner(tombe)
        self.assertEqual(self.menu._transform_ecran(self.RAPPORT), {})
        self.assertIn("pas de terminal", self.ecran.getvalue())


class TestMemoireDesEntetes(unittest.TestCase):
    """La table de lot se rappelle les lignes d'en-tête corrigées.

    Le deuxième fichier d'un même export porte les mêmes feuilles : la
    correction n'est à faire qu'une fois. Ce qui est retenu est la
    RÉPONSE de l'opérateur et rien d'autre — retenir une mesure ferait
    propager son erreur à tout le lot, alors qu'elle se refait à
    l'identique sur chaque fichier.
    """

    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.base, True)
        self.table = os.path.join(self.base, "t.json")

    def _csv(self, nom):
        chemin = os.path.join(self.base, nom)
        with open(chemin, "w", encoding="utf-8") as flux:
            flux.write("IN137784,1028,100.5\n")
            flux.write("IN137785,1029,101.5\n")
            flux.write("IN137786,1030,102.5\n")
        return chemin

    OPTIONS = {"nombres": True, "textes": True, "graine": 7, "feuilles": []}

    def test_la_table_se_rappelle_ce_que_l_operateur_a_repondu(self):
        source = self._csv("un.csv")
        formats.ecrire(
            source,
            os.path.join(self.base, "a.csv"),
            dict(
                self.OPTIONS,
                table_chemin=self.table,
                entetes_par_feuille={formats.NOM_FEUILLE_NEUTRE: [1]},
            ),
        )
        relue = noyau.Correspondance.charger(self.table)
        self.assertEqual(relue.entetes, {formats.NOM_FEUILLE_NEUTRE: [1]})

    def test_le_fichier_suivant_du_lot_herite_de_la_correction(self):
        """Sans qu'on redise rien : c'est tout l'objet de la mémoire."""
        table = noyau.Correspondance(entetes={formats.NOM_FEUILLE_NEUTRE: [1]})
        table.ecrire(self.table)
        apercu = formats.plan(
            self._csv("deux.csv"),
            dict(
                self.OPTIONS,
                table_chemin=self.table,
                destination=os.path.join(self.base, "b.csv"),
            ),
        )
        valeurs = [c["valeur"] for c in apercu["entete_gardee"]]
        self.assertIn("IN137784", valeurs)

    def test_sans_memoire_la_mesure_tranche_et_la_ligne_1_est_en_portee(self):
        apercu = formats.plan(
            self._csv("trois.csv"),
            dict(
                self.OPTIONS,
                destination=os.path.join(self.base, "c.csv"),
            ),
        )
        self.assertEqual(apercu["entete_gardee"], [])

    def test_la_reponse_de_CE_passage_passe_avant_la_memoire(self):
        """L'opérateur peut toujours contredire ce que le lot a établi."""
        feuille = formats.Feuille(
            "F", [["a", "b"], ["x", 1], ["y", 2], ["z", 3]]
        )
        formats.mesurer_entetes([feuille], "csv", {"F": [2]}, {"F": [1]})
        self.assertEqual(feuille.lignes_entete, {2})

    def test_la_memoire_passe_avant_ce_que_le_FICHIER_declare(self):
        """C'est une réponse d'opérateur elle aussi, faite sur un autre
        fichier du même lot."""
        feuille = formats.Feuille(
            "F", [["a", "b"], ["x", 1], ["y", 2], ["z", 3]]
        )
        feuille.entete_declaree = {1}
        formats.mesurer_entetes([feuille], "xlsx", None, {"F": [1, 2]})
        self.assertEqual(feuille.lignes_entete, {1, 2})

    def test_une_memoire_qui_ne_nomme_pas_la_feuille_ne_fait_rien(self):
        feuille = formats.Feuille(
            "F", [["a", "b"], ["x", 1], ["y", 2], ["z", 3]]
        )
        feuille.entete_declaree = {1}
        formats.mesurer_entetes([feuille], "xlsx", None, {"Autre": [9]})
        self.assertEqual(feuille.lignes_entete, {1})


class TestTableVersion2(unittest.TestCase):
    """La table porte un troisième dictionnaire, sans casser l'ancienne."""

    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.base, True)
        self.chemin = os.path.join(self.base, "t.json")

    def test_une_table_de_version_1_se_charge_toujours(self):
        """Sinon le deuxième fichier d'un lot commencé avant refuserait
        la table du premier."""
        with open(self.chemin, "w", encoding="utf-8") as flux:
            json.dump(
                {"version": 1, "mots": {"a": "aboulie"}, "nombres": {}}, flux
            )
        relue = noyau.Correspondance.charger(self.chemin)
        self.assertEqual(relue.mots, {"a": "aboulie"})
        self.assertEqual(relue.entetes, {})

    def test_l_ecriture_reste_en_0600(self):
        """Ce fichier porte chaque valeur d'origine en clair."""
        noyau.Correspondance(entetes={"F": [1]}).ecrire(self.chemin)
        self.assertEqual(os.stat(self.chemin).st_mode & 0o777, 0o600)

    def test_les_lignes_sont_normalisees_et_triees(self):
        """Une réponse tapée à la main, ou relue d'un JSON, arrive en
        chaînes et dans n'importe quel ordre."""
        table = noyau.Correspondance(entetes={"F": ["3", 1, "1", 0, -2]})
        self.assertEqual(table.entetes, {"F": [1, 3]})

    def test_en_dict_porte_les_trois_dictionnaires(self):
        rendu = noyau.Correspondance(
            mots={"a": "b"}, nombres={"i:1": 2}, entetes={"F": [1]}
        ).en_dict()
        self.assertEqual(sorted(rendu), ["entetes", "mots", "nombres"])
        json.dumps(rendu, allow_nan=False)


class TestNombre(unittest.TestCase):
    """Le signe, le zéro, le type, et l'étendue mesurée."""

    def setUp(self):
        self.rng = random.Random(1234)

    def test_positif_reste_positif(self):
        for _ in range(50):
            self.assertGreater(noyau.nouveau_nombre(7, self.rng), 0)

    def test_negatif_reste_negatif(self):
        for _ in range(50):
            self.assertLess(noyau.nouveau_nombre(-7, self.rng), 0)

    def test_zero_reste_zero(self):
        # Zéro n'a pas de signe à préserver, et un zéro qui devient 743
        # fabrique de la donnée là où il n'y en avait pas.
        self.assertEqual(noyau.nouveau_nombre(0, self.rng), 0)
        self.assertEqual(noyau.nouveau_nombre(0.0, self.rng), 0.0)

    def test_entier_rend_entier(self):
        valeur = noyau.nouveau_nombre(5, self.rng)
        self.assertIsInstance(valeur, int)
        self.assertNotIsInstance(valeur, bool)

    def test_flottant_rend_flottant(self):
        self.assertIsInstance(noyau.nouveau_nombre(5.5, self.rng), float)

    def test_repli_zero_mille_sans_bornes(self):
        for _ in range(200):
            self.assertLessEqual(abs(noyau.nouveau_nombre(5, self.rng)), 1000)

    def test_tirage_dans_les_bornes(self):
        for _ in range(200):
            valeur = noyau.nouveau_nombre(2024, self.rng, bornes=(2000, 2030))
            self.assertGreaterEqual(valeur, 2000)
            self.assertLessEqual(valeur, 2030)

    def test_colonne_zero_un_ne_rend_jamais_743(self):
        """La leçon d'anonymize.py : un taux à 743 fait lever l'ORM."""
        for _ in range(200):
            valeur = noyau.nouveau_nombre(0.15, self.rng, bornes=(0.0, 1.0))
            self.assertGreaterEqual(valeur, 0.0)
            self.assertLessEqual(valeur, 1.0)

    def test_bornes_negatives_gardent_le_signe_et_l_etendue(self):
        for _ in range(200):
            valeur = noyau.nouveau_nombre(-3, self.rng, bornes=(-50, 200))
            self.assertLess(valeur, 0)
            self.assertGreaterEqual(valeur, -50)

    def test_meme_valeur_meme_sortie(self):
        """Sans table, une clé de jointure se désagrège ligne à ligne."""
        table = noyau.Correspondance()
        premier = noyau.nouveau_nombre(4711, self.rng, table=table)
        for _ in range(20):
            self.assertEqual(
                noyau.nouveau_nombre(4711, self.rng, table=table),
                premier,
            )

    def test_types_distincts_ne_se_confondent_pas(self):
        table = noyau.Correspondance()
        noyau.nouveau_nombre(5, self.rng, table=table)
        noyau.nouveau_nombre(5.0, self.rng, table=table)
        self.assertEqual(len(table.nombres), 2)


class TestPiegesDeType(unittest.TestCase):
    """Les gardes, dans l'ordre où ils doivent se déclencher."""

    def setUp(self):
        self.rng = random.Random(7)
        self.table = noyau.Correspondance()
        self.options = _options()

    def _anon(self, valeur, **extra):
        options = _options(**extra)
        return noyau.anonymise_cellule(valeur, options, self.table, self.rng)

    def test_booleen_traverse_intact(self):
        # isinstance(True, int) vaut True : sans garde explicite, toute
        # case à cocher deviendrait un montant.
        self.assertIs(self._anon(True), noyau._INTACTE)
        self.assertIs(self._anon(False), noyau._INTACTE)

    def test_date_traverse_intacte(self):
        for valeur in (
            datetime.datetime(2020, 1, 2, 3, 4),
            datetime.date(2020, 1, 2),
            datetime.time(3, 4),
        ):
            self.assertIs(self._anon(valeur), noyau._INTACTE)

    def test_vide_traverse_intact(self):
        self.assertIs(self._anon(None), noyau._INTACTE)
        self.assertIs(self._anon(""), noyau._INTACTE)

    def test_formule_traverse_intacte(self):
        self.assertIs(self._anon('=IF(A1="x",1,0)'), noyau._INTACTE)

    def test_les_sept_valeurs_erreur_traversent_intactes(self):
        for erreur in noyau.VALEURS_ERREUR:
            self.assertIs(
                self._anon(erreur),
                noyau._INTACTE,
                f"{erreur} doit rester intacte",
            )

    def test_il_y_a_bien_sept_valeurs_erreur(self):
        self.assertEqual(len(noyau.VALEURS_ERREUR), 7)

    def test_binaire_est_vide_pas_recopie(self):
        # Une colonne OLE d'Access peut porter un document entier.
        self.assertIsNone(self._anon(b"\x00document"))
        self.assertIsNone(self._anon(bytearray(b"\x01")))

    def test_texte_refuse_ne_touche_rien(self):
        self.assertIs(self._anon("Alpha", texte=False), noyau._INTACTE)

    def test_nombres_refuses_ne_touchent_rien(self):
        self.assertIs(self._anon(42, nombres=False), noyau._INTACTE)


class TestNormalisationXls(unittest.TestCase):
    """xlrd porte le type dans ctype, jamais dans la valeur."""

    def test_code_23_rend_ref(self):
        self.assertEqual(noyau.normaliser_xls(5, 23, 0), "#REF!")

    def test_code_0_rend_null(self):
        """Le piège : « 0 reste 0 » en ferait un zéro légitime."""
        self.assertEqual(noyau.normaliser_xls(5, 0, 0), "#NULL!")

    def test_les_sept_codes_sont_couverts(self):
        self.assertEqual(
            set(noyau.CODES_ERREUR_XLS.values()), set(noyau.VALEURS_ERREUR)
        )

    def test_booleen_rend_un_vrai_booleen(self):
        self.assertIs(noyau.normaliser_xls(4, 1, 0), True)
        self.assertIs(noyau.normaliser_xls(4, 0, 0), False)

    def test_vide_rend_none(self):
        self.assertIsNone(noyau.normaliser_xls(0, "", 0))
        self.assertIsNone(noyau.normaliser_xls(6, "", 0))

    def test_texte_traverse(self):
        self.assertEqual(noyau.normaliser_xls(1, "Alpha", 0), "Alpha")


class TestUniciteNumerique(unittest.TestCase):
    """Le tirage seul collisionne, et détruit les clés.

    C'est l'intégrité que la table apporte au texte, et qu'elle refusait en
    silence aux nombres : deux clés primaires distinctes recevaient le même
    nombre, et la fixture ne se réimportait plus.
    """

    def test_cent_valeurs_rendent_cent_sorties(self):
        table = noyau.Correspondance()
        rng = random.Random(1)
        sorties = [
            noyau.nouveau_nombre(v, rng, bornes=(1, 100), table=table)
            for v in range(1, 101)
        ]
        # Mesuré avant correctif : 66 sorties distinctes sur 100.
        self.assertEqual(len(set(sorties)), 100)

    def test_etendue_etroite_sans_doublon(self):
        for graine in (7, 11, 42):
            table = noyau.Correspondance()
            rng = random.Random(graine)
            sorties = [
                noyau.nouveau_nombre(v, rng, bornes=(1, 6), table=table)
                for v in range(1, 7)
            ]
            self.assertEqual(len(set(sorties)), 6, graine)

    def test_l_elargissement_garde_le_signe(self):
        table = noyau.Correspondance()
        rng = random.Random(2)
        sorties = [
            noyau.nouveau_nombre(-v, rng, bornes=(-50, 200), table=table)
            for v in range(1, 51)
        ]
        self.assertEqual(len(set(sorties)), 50)
        self.assertTrue(all(x < 0 for x in sorties))

    def test_une_plage_saturee_reste_dans_ses_bornes(self):
        """Élargir dès le premier échec sortait de la plage mesurée.

        Une heure de la journée devenait 189, un taux dépassait l'unité,
        alors que la plage avait encore des places libres.
        """
        table = noyau.Correspondance()
        rng = random.Random(1)
        sorties = [
            noyau.nouveau_nombre(
                round(0.15 + i * 0.01, 2),
                rng,
                bornes=(0.15, 0.2),
                table=table,
            )
            for i in range(6)
        ]
        self.assertEqual(len(set(sorties)), 6)
        for valeur in sorties:
            self.assertGreaterEqual(valeur, 0.15)
            # Six valeurs dans six places, l'identité interdite : la
            # dernière place libre EST parfois l'identité. On grandit
            # alors d'un PAS, pas d'un facteur dix — un taux reste un
            # taux.
            self.assertLessEqual(valeur, 0.25)

    def test_une_heure_reste_une_heure(self):
        table = noyau.Correspondance()
        rng = random.Random(2)
        sorties = [
            noyau.nouveau_nombre(v, rng, bornes=(0, 23), table=table)
            for v in range(1, 24)
        ]
        self.assertEqual(len(set(sorties)), 23)
        self.assertLessEqual(max(sorties), 23)

    def test_aucun_nombre_n_est_rendu_a_lui_meme(self):
        """Il serait compté et annoncé comme remplacé sans l'être."""
        table = noyau.Correspondance()
        rng = random.Random(3)
        for v in range(1, 7):
            self.assertNotEqual(
                noyau.nouveau_nombre(v, rng, bornes=(1, 6), table=table), v
            )

    def test_l_elargissement_ne_sert_qu_en_dernier_recours(self):
        """Plus de places que de valeurs : aucune sortie hors plage."""
        table = noyau.Correspondance()
        rng = random.Random(4)
        sorties = [
            noyau.nouveau_nombre(v, rng, bornes=(1, 10), table=table)
            for v in range(1, 10)
        ]
        self.assertTrue(all(1 <= x <= 10 for x in sorties), sorties)

    def test_sans_table_le_tirage_reste_borne(self):
        rng = random.Random(3)
        for _ in range(50):
            self.assertLessEqual(
                noyau.nouveau_nombre(5, rng, bornes=(1, 10)), 10
            )

    def test_une_table_rechargee_garde_l_unicite(self):
        """Le lot entier, pas seulement le fichier courant."""
        table = noyau.Correspondance(nombres={"i:1": 4, "i:2": 5})
        self.assertEqual(table.nombres_pris, {4, 5})
        rng = random.Random(4)
        for v in range(3, 7):
            self.assertNotIn(
                noyau.nouveau_nombre(v, rng, bornes=(1, 6), table=table),
                (4, 5),
            )


class TestMotSansRemise(unittest.TestCase):
    """Deux valeurs distinctes ne peuvent PAS partager un mot."""

    def test_le_saut_d_identite_ne_reprend_pas_un_mot_donne(self):
        """Le saut avance d'un rang : il pouvait retomber sur un mot pris.

        Deux clients fusionnaient alors sur un seul mot — la RECHERCHEV
        résout encore, mais sur la mauvaise ligne.
        """
        table = noyau.Correspondance()
        # La première valeur EST un mot du vivier : le saut se déclenche.
        sorties = [
            noyau.nouveau_mot(v, table, VIVIER)
            for v in (VIVIER[1], "Alpha", "Beta", VIVIER[0], "Gamma")
        ]
        self.assertEqual(len(set(sorties)), len(sorties))
        for source, mot in table.mots.items():
            self.assertNotEqual(source, mot)

    def test_une_table_rechargee_ne_recolle_pas(self):
        premiere = noyau.Correspondance()
        for v in ("Alpha", "Beta"):
            noyau.nouveau_mot(v, premiere, VIVIER)
        seconde = noyau.Correspondance(mots=dict(premiere.mots))
        for v in ("Gamma", "Delta"):
            noyau.nouveau_mot(v, seconde, VIVIER)
        self.assertEqual(len(set(seconde.mots.values())), len(seconde.mots))

    def test_mots_pris_est_reconstruit_au_chargement(self):
        table = noyau.Correspondance(mots={"Alpha": "aboulie"})
        self.assertEqual(table.mots_pris, {"aboulie"})


class TestNomDeFeuilleEnConversion(unittest.TestCase):
    """Une table Access porte souvent le nom du client.

    La conversion l'écrivait tel quel — nom d'onglet, clé de premier
    niveau d'un JSON, nom de fichier — alors que RIEN ne le résout dans
    une conversion, contrairement au classeur d'où une formule le
    référence. Le tolérer aurait laissé le nom dans la copie tout en
    faisant refuser le fichier au filet.
    """

    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.base, True)
        self.options = {"vivier": VIVIER, "feuilles": None}

    def test_le_nom_passe_par_la_MEME_table_que_les_cellules(self):
        table = noyau.Correspondance()
        feuille = formats.Feuille("Alpha", [["client"], ["Alpha"]])
        nom = formats._nom_de_feuille_anonyme(feuille, table, self.options)
        self.assertNotEqual(nom, "Alpha")
        # La feuille et la cellule qui la nomme reçoivent le même mot.
        self.assertEqual(nom, noyau.nouveau_mot("Alpha", table, VIVIER))

    def test_sans_table_le_nom_ne_bouge_pas(self):
        feuille = formats.Feuille("Alpha", [["c"], ["x"]])
        self.assertEqual(
            formats._nom_de_feuille_anonyme(feuille, None, self.options),
            "Alpha",
        )

    def test_la_conversion_vers_json_anonymise_la_cle(self):
        table = noyau.Correspondance()
        feuille = formats.Feuille("Alpha", [["c"], ["Beta"]])
        sortie = os.path.join(self.base, "o.json")
        formats.convertir(
            os.path.join(self.base, "s.csv"),
            sortie,
            "json",
            self.options,
            feuilles=[feuille],
            table=table,
        )
        arbre = json.load(open(sortie, encoding="utf-8"))
        self.assertNotIn("Alpha", arbre)


class TestExternalIdContreLogin(unittest.TestCase):
    """Un external ID et un login pointé ont la même FORME.

    « base.res_partner_7 » et « jean.tremblay » sont tous deux des jetons
    minuscules pointés : la forme seule ne les sépare pas, et une colonne
    « user_id » de logins passait pour une colonne de relations, donc
    partait en clair. Ce qui les sépare est le PRÉFIXE : un external ID
    partage son module avec ses voisins, des noms de personnes non.
    """

    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.base, True)

    def _ecrire(self, contenu):
        chemin = os.path.join(self.base, "e.csv")
        with open(chemin, "w", encoding="utf-8") as fh:
            fh.write(contenu)
        return chemin

    def test_un_external_id_reste_au_plancher(self):
        source = self._ecrire(
            "id,partner_id/id,montant\n"
            "7,base.res_partner_7,1200\n"
            "8,base.res_partner_8,830\n"
        )
        sortie = os.path.join(self.base, "o.csv")
        formats.ecrire(source, sortie, {"graine": "3"})
        rendu = open(sortie, encoding="utf-8").read()
        self.assertIn("base.res_partner_7", rendu)

    def test_un_login_pointe_est_remplace(self):
        source = self._ecrire(
            "id,user_id,montant\n"
            "7,jean.tremblay,1200\n"
            "8,marie.roy,830\n"
            "9,paul.gagne,410\n"
        )
        sortie = os.path.join(self.base, "o.csv")
        formats.ecrire(source, sortie, {"graine": "3"})
        rendu = open(sortie, encoding="utf-8").read()
        for login in ("jean.tremblay", "marie.roy", "paul.gagne"):
            self.assertNotIn(login, rendu, login)

    def test_l_annonce_suit_la_portee(self):
        """L'écran annonçait une colonne écartée que le moteur remplace."""
        source = self._ecrire(
            "id,partner_id/id,user_id,montant\n"
            "7,base.res_partner_7,jean.tremblay,1200\n"
            "8,base.res_partner_8,marie.roy,830\n"
        )
        apercu = formats.plan(source, {"graine": "3"})
        ecartees = {c["etiquette"] for c in apercu["colonnes_ecartees"]}
        self.assertIn("partner_id/id", ecartees)
        self.assertNotIn("user_id", ecartees)


class TestNormalisationAccess(unittest.TestCase):
    """`access-parser` rend une date et un montant en CHAÎNE.

    Comme pour `.xls`, c'est le TYPE déclaré qui décide et jamais la forme
    de la valeur : une colonne de texte peut légitimement porter
    « 2021-12-02 00:00:00 », et la convertir la mettrait hors d'atteinte de
    la règle du texte.
    """

    def test_une_date_devient_une_date(self):
        valeur = noyau.normaliser_access(
            "2021-12-02 00:00:00", noyau.ACCESS_DATETIME
        )
        self.assertIsInstance(valeur, datetime.datetime)
        self.assertEqual(valeur.year, 2021)

    def test_la_date_invalide_est_videe(self):
        """Le marqueur d'Access ne porte aucune donnée."""
        self.assertIsNone(
            noyau.normaliser_access("(Invalid Date)", noyau.ACCESS_DATETIME)
        )

    def test_un_montant_devient_un_nombre(self):
        self.assertEqual(noyau.normaliser_access("$1,995.50", 5), 1995.50)
        self.assertEqual(noyau.normaliser_access("($1,995.50)", 5), -1995.50)

    def test_un_montant_illisible_reste_du_texte(self):
        self.assertEqual(noyau.normaliser_access("sur devis", 5), "sur devis")

    def test_le_texte_qui_RESSEMBLE_a_une_date_reste_du_texte(self):
        """Le type décide, pas la forme."""
        self.assertEqual(
            noyau.normaliser_access("2021-12-02 00:00:00", 10),
            "2021-12-02 00:00:00",
        )

    def test_les_types_couverts(self):
        self.assertEqual(noyau.ACCESS_DATETIME, 8)
        self.assertIn(5, noyau.ACCESS_MONETAIRE)


class TestFiletSurUneValeurNumerique(unittest.TestCase):
    """Une valeur de chiffres ne se cherche pas comme un mot.

    Sur une base ordinaire, le filet refusait seize valeurs dont aucune
    ne fuyait. Un code postal « 0512 » se retrouve dans l'identifiant
    10512 ; « 1203 » est le numéro de ligne que
    `<row r="1203">` porte dans toute feuille de plus de mille lignes ; et
    un nombre TIRÉ pour une colonne peut égaler, chiffre pour chiffre, une
    valeur texte d'une autre.

    Refuser toute copie d'un fichier ordinaire rend le filet inutile aussi
    sûrement que ne rien refuser.
    """

    def test_une_valeur_noyee_dans_un_nombre_plus_long_ne_compte_pas(self):
        motif = noyau._motif_borne("0512")
        self.assertFalse(motif.search("10512"))
        self.assertFalse(motif.search("105120"))
        self.assertFalse(motif.search("0512.7"))

    def test_une_vraie_survivance_reste_vue(self):
        """Bordée de ce qui n'est pas un chiffre, elle est toujours là."""
        motif = noyau._motif_borne("0512")
        for foin in ("<v>0512</v>", '"0512"', "a,0512,b", "0512", ">0512<"):
            with self.subTest(foin=foin):
                self.assertTrue(motif.search(foin))

    def test_la_virgule_borne_un_champ_de_csv(self):
        """L'exclure aveuglait le filet sur le format le plus simple, là
        où un séparateur de milliers coupe déjà la suite de chiffres."""
        self.assertTrue(noyau._motif_borne("1203").search("x,1203,y"))
        self.assertEqual("1,203".count("1203"), 0)

    def test_une_lettre_collee_borne_aussi(self):
        """`r="A1010"` met un numéro de ligne contre une lettre de
        colonne, et des chiffres collés à une lettre font un seul jeton."""
        self.assertFalse(noyau._motif_borne("1010").search('r="A1010"'))
        self.assertFalse(noyau._motif_borne("1203").search("SKU1203"))

    def test_une_valeur_a_lettres_se_borne_par_les_seuls_mots(self):
        """Elle se borne aussi, mais pas sur le point.

        « Document » vit dans l'URI `officeDocument` que tout classeur
        écrit, et le socle du graveur ne l'excuse pas : il est MINIMAL, si
        bien que chaque type de partie que la source a en plus apporte une
        URI distincte de plus. Le point ne borne pas ici — il suit un mot
        en fin de phrase sans en faire un autre mot.
        """
        motif = noyau._motif_borne("Document")
        self.assertIsNotNone(motif)
        self.assertFalse(motif.search("officeDocument"))
        self.assertFalse(motif.search("Documentation"))
        self.assertTrue(motif.search("<t>Document</t>"))
        self.assertTrue(motif.search("Document."))

    def test_un_nom_dans_un_cache_ou_un_litteral_reste_trouvable(self):
        """Ce que le bornage NE doit pas coûter : une survivance vraie est
        bordée de balisage ou de guillemets, jamais collée à un mot."""
        motif = noyau._motif_borne("aboulie")
        for foin in (
            "<c:v>aboulie</c:v>",
            '="aboulie"',
            '="Pre"&"aboulie"',
            "a,aboulie,b",
            "aboulie-2024",
        ):
            with self.subTest(foin=foin):
                self.assertTrue(motif.search(foin))

    def test_un_autre_mot_qui_contient_la_valeur_n_en_est_pas_une(self):
        """« Bellevue » n'est pas une survivance de « Belle »."""
        self.assertFalse(noyau._motif_borne("Belle").search("Bellevue"))

    def test_les_attributs_ne_portent_pas_de_valeur_numerique(self):
        """Un XML porte ses index dans les ATTRIBUTS et ses valeurs de
        cellule dans les nœuds de texte : la matière est séparée."""
        brut = '<row r="1203"><c r="A1203"><v>7</v></c></row>'
        _e, _n, texte, _tn = noyau._chaines_distinctes(brut)
        self.assertIn("7", texte)
        self.assertNotIn("1203", texte)
        self.assertNotIn("A1203", texte)

    def test_une_partie_plate_reste_fouillee_ENTIERE(self):
        """Les deux derniers blocs valent les deux premiers hors XML : un
        champ de csv est de la donnée où qu'il soit."""
        blocs = noyau._matiere("o.csv", "a,0512,b", reductible=False)
        self.assertEqual(len(blocs), 4)
        self.assertEqual(blocs[0], blocs[2])
        self.assertEqual(blocs[1], blocs[3])

    def test_un_nombre_tire_est_tolere_comme_un_mot_l_est(self):
        """Sa présence est expliquée par le tirage, non par une
        survivance : un identifiant tiré à 10785 et un code postal
        « 10785 » sont les mêmes chiffres pour des raisons différentes."""
        base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, base, True)
        copie = os.path.join(base, "o.csv")
        with open(copie, "w", encoding="utf-8") as flux:
            flux.write("aboulie,10785\n")
        table = noyau.Correspondance()
        table.mots["10785"] = "aboulie"
        table.nombres[42] = 10785
        fuites, _non = noyau.verifier_copie([copie], table)
        self.assertEqual(fuites, {})

    def test_l_identite_d_un_nombre_reste_un_refus(self):
        """Un nombre rendu à lui-même est annoncé remplacé et ne l'est
        pas : c'est le cas que la tolérance ne doit PAS couvrir."""
        base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, base, True)
        copie = os.path.join(base, "o.csv")
        with open(copie, "w", encoding="utf-8") as flux:
            flux.write("10785,x\n")
        table = noyau.Correspondance()
        table.mots["10785"] = "aboulie"
        table.nombres[10785] = 10785
        fuites, _non = noyau.verifier_copie([copie], table)
        self.assertIn("10785", fuites)


class TestResolutionDeLaColonne(unittest.TestCase):
    """L'intégralité vient de la COLONNE, non du type d'une valeur.

    `isinstance(valeur, int)` ne peut pas en répondre : le format `.xls`
    ne stocke que des doubles, si bien que son lecteur rend 100 en
    « 100.0 ». Toute colonne d'entiers d'un `.xls` ressortait donc
    décimale, et la copie ne se réimportait plus dans un champ entier.
    """

    def setUp(self):
        self.rng = random.Random(7)

    def test_une_colonne_entiere_rend_des_entiers(self):
        """Même quand le lecteur a rendu des flottants."""
        for valeur in (100.0, 256.0, 101.0):
            with self.subTest(valeur=valeur):
                tire = noyau.nouveau_nombre(
                    valeur, self.rng, bornes=(100.0, 256.0, True)
                )
                self.assertTrue(float(tire).is_integer(), tire)

    def test_une_colonne_decimale_garde_ses_decimales(self):
        vus = [
            noyau.nouveau_nombre(
                v, random.Random(v), bornes=(0.02, 1007.64, False)
            )
            for v in (32.38, 47.42, 126.38)
        ]
        self.assertFalse(all(float(v).is_integer() for v in vus), vus)

    def test_sans_troisieme_terme_le_type_decide_encore(self):
        """Les bornes à deux termes restent valides : la fonction sert
        aussi hors du parcours de colonnes."""
        self.assertTrue(
            float(
                noyau.nouveau_nombre(5, self.rng, bornes=(1, 100))
            ).is_integer()
        )
        self.assertIsInstance(
            noyau.nouveau_nombre(5.5, self.rng, bornes=(1.0, 100.0)), float
        )

    def test_la_cle_de_la_table_ne_depend_PAS_de_la_colonne(self):
        """Sinon un même nombre vu dans deux colonnes de résolutions
        différentes recevrait deux remplacements, et la jointure qui les
        relie se désagrégerait."""
        table = noyau.Correspondance()
        premier = noyau.nouveau_nombre(
            10248, random.Random(1), bornes=(10248, 11077, True), table=table
        )
        second = noyau.nouveau_nombre(
            10248, random.Random(2), bornes=(1, 99999, False), table=table
        )
        self.assertEqual(premier, second)

    def test_une_seule_decimale_suffit_a_decimaliser_la_colonne(self):
        """La mesure porte sur TOUTE la colonne."""
        feuille = formats.Feuille(
            "F", [["montant"], [1.0], [2.0], [3.5], [4.0]]
        )
        colonne = formats._stats_colonnes(feuille)[0]
        self.assertFalse(colonne["entiere"])
        entiere = formats._stats_colonnes(
            formats.Feuille("F", [["m"], [1.0], [2.0], [3.0]])
        )[0]
        self.assertTrue(entiere["entiere"])

    def test_une_colonne_sans_nombre_n_est_pas_dite_entiere(self):
        """Vraie par vacuité, elle aurait forcé un arrondi ailleurs."""
        colonne = formats._stats_colonnes(
            formats.Feuille("F", [["nom"], ["aboulie"], ["acai"]])
        )[0]
        self.assertFalse(colonne["entiere"])


class TestEchelleMonetaireAccess(unittest.TestCase):
    """`access-parser` a DEUX sorties pour une colonne monétaire.

    Reconnaît-il le format déclaré de la colonne, il place le point décimal
    et rend « $14.00 ». Ne le reconnaît-il pas, il rend l'entier de
    stockage TEL QUEL — et Access garde un Currency en entier multiplié par
    dix mille. Les deux formes cohabitent dans un MÊME fichier : une
    colonne de prix en sort juste et une colonne de fret gonflée de quatre
    ordres de grandeur.

    Le point décimal tranche sans deviner : toutes les branches de la
    bibliothèque qui aboutissent en insèrent un, celle qui renonce n'en
    met pas.
    """

    def _cas(self, brut, attendu):
        """Éprouvé sur CHAQUE code monétaire, non sur un seul."""
        for code in sorted(noyau.ACCESS_MONETAIRE):
            with self.subTest(code=code, brut=brut):
                rendu = noyau.normaliser_access(brut, code)
                self.assertAlmostEqual(rendu, attendu, places=6)

    def test_l_entier_de_stockage_est_divise(self):
        self._cas("474200", 47.42)
        self._cas("1263800", 126.38)
        self._cas("54500", 5.45)
        self._cas("0", 0.0)

    def test_la_forme_localisee_ne_l_est_pas(self):
        self._cas("$14.00", 14.0)
        self._cas("$1,995.50", 1995.5)
        self._cas("\u20ac5.00", 5.0)

    def test_le_signe_survit_aux_deux_formes(self):
        """Access écrit un négatif entre parenthèses."""
        self._cas("(474200)", -47.42)
        self._cas("-474200", -47.42)

    def test_l_exposant_n_est_pas_ampute(self):
        """La branche scientifique rend « 3.24e+01 » : retirer le « e » en
        faisait 3,2401, soit un facteur dix sur la borne de la colonne."""
        self._cas("3.24e+01", 32.4)
        self._cas("3.24e-01", 0.324)

    def test_le_pourcentage_garde_son_echelle(self):
        """Sa branche coupe deux chiffres, pas quatre, et pose le point."""
        self._cas("12.34%", 12.34)


class TestCoercition(unittest.TestCase):
    """Un champ CSV ou un attribut XML arrive sans type."""

    def test_nombres_reconnus(self):
        self.assertEqual(noyau.coercer_texte("4711"), 4711)
        self.assertEqual(noyau.coercer_texte("-320"), -320)
        self.assertEqual(noyau.coercer_texte("0.15"), 0.15)
        self.assertEqual(noyau.coercer_texte("0"), 0)

    def test_zeros_de_tete_restent_du_texte(self):
        # « 007 » est un code, pas une quantité.
        self.assertEqual(noyau.coercer_texte("007"), "007")

    def test_ce_que_float_accepterait_a_tort(self):
        for texte in ("1e5", "NaN", "inf", "-inf", "1,5", " 1 2 "):
            self.assertEqual(noyau.coercer_texte(texte), texte)

    def test_non_chaine_traverse(self):
        self.assertEqual(noyau.coercer_texte(5), 5)
        self.assertIsNone(noyau.coercer_texte(None))


class TestVivierEtMots(unittest.TestCase):
    """L'attribution est indexée, jamais tirée."""

    def test_vivier_mesure(self):
        # 1404 mots dans randomwordfr, 1366 après translittération des
        # accents et rejet de ce qui n'est pas un mot simple.
        self.assertEqual(len(VIVIER), 1366)

    def test_vivier_sans_accent_ni_espace(self):
        for mot in VIVIER:
            self.assertRegex(mot, r"^[a-z_]+$")

    def test_vivier_trie_et_dedoublonne(self):
        # TRIÉ : l'ordre d'un set varie d'un processus à l'autre, et une
        # table réutilisée rendrait d'autres mots pour les mêmes valeurs.
        self.assertEqual(list(VIVIER), sorted(VIVIER))
        self.assertEqual(len(VIVIER), len(set(VIVIER)))

    def test_deux_appels_rendent_la_meme_sequence(self):
        self.assertEqual(noyau.vivier_de_mots(), noyau.vivier_de_mots())

    def test_meme_source_meme_mot(self):
        table = noyau.Correspondance()
        premier = noyau.nouveau_mot("Alpha", table, VIVIER)
        self.assertEqual(noyau.nouveau_mot("Alpha", table, VIVIER), premier)

    def test_valeurs_distinctes_rendent_mots_distincts(self):
        """La propriété que le tirage ne donnait pas.

        Sur 20 mots tirés au hasard, six valeurs distinctes ont déjà 56 %
        de chance d'en partager un, et deux clients qui partagent un mot
        fusionnent en une seule clé.
        """
        table = noyau.Correspondance()
        sorties = {
            noyau.nouveau_mot(f"valeur-{i}", table, VIVIER)
            for i in range(len(VIVIER) + 1)
        }
        self.assertEqual(len(sorties), len(VIVIER) + 1)

    def test_au_dela_du_vivier_ce_sont_des_PAIRES(self):
        table = noyau.Correspondance()
        for i in range(len(VIVIER) + 3):
            dernier = noyau.nouveau_mot(f"v{i}", table, VIVIER)
        self.assertIn("_", dernier)
        self.assertFalse(dernier.startswith("mot_"))
        gauche, droite = dernier.split("_", 1)
        self.assertIn(gauche, VIVIER)
        self.assertIn(droite, VIVIER)

    def test_repli_a_vingt_mots_annonce(self):
        capacites = formats.capabilities()
        self.assertIn("mots", capacites)


class TestGraine(unittest.TestCase):
    def test_meme_graine_meme_passage(self):
        sorties = []
        for _ in range(2):
            rng = random.Random(42)
            table = noyau.Correspondance()
            sorties.append(
                [
                    noyau.anonymise_cellule(v, _options(), table, rng)
                    for v in (10, -10, "Alpha", 3.5, "Beta", 77)
                ]
            )
        self.assertEqual(sorties[0], sorties[1])


class TestPortee(unittest.TestCase):
    """La portée se décide sur les coordonnées, jamais sur la valeur."""

    def test_ligne_un_hors_portee_par_defaut(self):
        self.assertFalse(noyau.cellule_en_portee("F", 1, 1, _options()))
        self.assertTrue(
            noyau.cellule_en_portee("F", 1, 1, _options(entetes=True))
        )

    def test_feuille_non_listee_hors_portee(self):
        options = _options(feuilles=["Autre"])
        self.assertFalse(noyau.cellule_en_portee("F", 2, 1, options))
        self.assertTrue(noyau.cellule_en_portee("Autre", 2, 1, options))

    def test_colonne_exclue_sur_toutes_ses_lignes(self):
        options = _options(
            etiquettes={("F", 2): "montant"},
            colonnes_intactes={"montant"},
        )
        for ligne in (2, 3, 900):
            self.assertFalse(noyau.cellule_en_portee("F", ligne, 2, options))

    def test_colonne_par_index_en_repli(self):
        options = _options(colonnes_intactes={"3"})
        self.assertFalse(noyau.cellule_en_portee("F", 2, 3, options))


class TestPlancherStructurel(unittest.TestCase):
    """anonymize.py refuse par le NOM avant de lire une valeur."""

    def test_id_nu(self):
        self.assertTrue(noyau.colonne_plancher("id"))
        self.assertTrue(noyau.colonne_plancher("ID"))

    def test_suffixes_structurels_au_nom_seul(self):
        """« /id » et « /.id » ne portent JAMAIS de texte libre."""
        for etiquette in ("partner_id/id", "partner_id/.id"):
            self.assertTrue(noyau.colonne_plancher(etiquette), etiquette)

    def test_suffixe_de_relation_exige_la_forme_d_une_CIBLE(self):
        """Un export import-compatible met un NOM dans « partner_id ».

        Et un mot en minuscules — un login, un nom de service — n'est pas
        la cible d'une relation : l'exiger seulement « identifiant »
        recopiait « jtremblay » et « comptabilite » en clair.
        """
        for etiquette in ("partner_id", "partner_ids"):
            self.assertFalse(noyau.colonne_plancher(etiquette), etiquette)
            self.assertFalse(
                noyau.colonne_plancher(etiquette, forme_identifiant=True),
                etiquette,
            )
            self.assertTrue(
                noyau.colonne_plancher(etiquette, forme_relation=True),
                etiquette,
            )

    def test_champs_structurels_au_nom_seul(self):
        for etiquette in ("sequence", "active", "create_uid"):
            self.assertTrue(noyau.colonne_plancher(etiquette), etiquette)

    def test_une_selection_exige_AUSSI_peu_de_valeurs(self):
        """La forme seule accepte n'importe quel mot minuscule.

        Une colonne de provinces, ou de créneaux nommés par des
        personnes, passait pour une sélection sur ce seul fait.
        """
        self.assertFalse(
            noyau.colonne_plancher("state", forme_identifiant=True)
        )
        self.assertTrue(
            noyau.colonne_plancher(
                "state", forme_identifiant=True, selection=True
            )
        )

    def test_une_etiquette_pointee_exige_la_preuve_d_un_external_id(self):
        """« key », « model », « res_model » portent un jeton pointé.

        La forme d'un mot minuscule ne suffit pas : une colonne « Key » de
        identifiants de personnes en minuscules partait en clair.
        """
        for etiquette in ("key", "model", "res_model", "arch_db"):
            self.assertFalse(
                noyau.colonne_plancher(etiquette, forme_identifiant=True),
                etiquette,
            )
            self.assertTrue(
                noyau.colonne_plancher(etiquette, forme_relation=True),
                etiquette,
            )

    def test_un_external_id_se_PROUVE(self):
        """Compter les préfixes communs ne tranchait pas.

        Une équipe entière de logins partage son domaine, et une colonne à
        une seule valeur n'a aucun préfixe à comparer. Ce qui prouve un
        external ID est le NUMÉRO de son local, ou le module sentinelle de
        l'export.
        """
        for valeur in (
            "base.res_partner_7",
            "__export__.res_partner_42",
            "__import__.sale_order_1",
        ):
            self.assertTrue(noyau.valeur_forme_relation(valeur), valeur)
        for valeur in (
            "jean.tremblay",
            "tremblay.jean",
            "clinique.exemple.com",
            "account.move",
        ):
            self.assertFalse(noyau.valeur_forme_relation(valeur), valeur)

    def test_une_liste_de_relations_prouve_chaque_membre(self):
        self.assertTrue(noyau.valeur_forme_relation("base.tag_1,base.tag_2"))
        self.assertFalse(
            noyau.valeur_forme_relation("base.tag_1,jean.tremblay")
        )

    def test_display_name_n_est_JAMAIS_au_plancher(self):
        """Dans un fichier plat, cette colonne EST la donnée.

        Le serveur la recalcule depuis `name`, ce qui la rend structurelle
        dans une base ; un fichier ne recalcule rien. Aucune forme mesurée
        ne doit la sauver.
        """
        for forme in (False, True):
            self.assertFalse(
                noyau.colonne_plancher(
                    "display_name",
                    forme_identifiant=forme,
                    forme_relation=forme,
                ),
                forme,
            )

    def test_forme_relation_est_plus_etroite(self):
        """Un login ou un nom de service n'est pas une cible de relation."""
        for valeur in (7, 7.0, "", "42/7/", "base.res_partner_7"):
            self.assertTrue(noyau.valeur_forme_relation(valeur), repr(valeur))
        for valeur in ("jtremblay", "comptabilite", "Paie_Zeta.pdf"):
            self.assertFalse(noyau.valeur_forme_relation(valeur), repr(valeur))
            # Et le nom de fichier n'est pas non plus un identifiant.
        self.assertFalse(noyau.valeur_forme_identifiant("Paie_Zeta.pdf"))

    def test_forme_identifiant(self):
        for valeur in (
            7,
            7.0,
            "",
            "base.res_partner_7",
            "sale",
            "1/2/",
            "base.p1,base.p2",
        ):
            self.assertTrue(
                noyau.valeur_forme_identifiant(valeur), repr(valeur)
            )
        for valeur in (
            "Boulangerie Tremblay inc.",
            "Jean Tremblay",
            "Quebec",
            "Freightliner M2 106",
            7.5,
        ):
            self.assertFalse(
                noyau.valeur_forme_identifiant(valeur), repr(valeur)
            )

    def test_une_colonne_ordinaire_passe(self):
        for etiquette in ("montant", "nom", "identifiant_client", ""):
            self.assertFalse(noyau.colonne_plancher(etiquette), etiquette)

    def test_plancher_actif_avec_les_reponses_par_defaut(self):
        """Appuyer sur Entrée ne doit pas détruire partner_id/id."""
        options = _options(etiquettes={("F", 1): "partner_id/id"})
        self.assertFalse(noyau.cellule_en_portee("F", 2, 1, options))


class TestSerialisationHorsTableur(unittest.TestCase):
    def test_dates_en_iso(self):
        self.assertEqual(
            noyau.valeur_hors_tableur(datetime.date(2020, 1, 2)),
            "2020-01-02",
        )

    def test_none_reste_none(self):
        self.assertIsNone(noyau.valeur_hors_tableur(None))

    def test_objet_a_texte_rend_son_texte(self):
        """Un ArrayFormula ne définit pas __str__ : un csv.writer naïf
        graverait son adresse mémoire dans le fichier."""

        class FausseFormule:
            text = "=SUM(A1:A2)"

        self.assertEqual(
            noyau.valeur_hors_tableur(FausseFormule()), "=SUM(A1:A2)"
        )

    def test_booleen_et_erreur_traversent(self):
        self.assertIs(noyau.valeur_hors_tableur(True), True)
        self.assertEqual(noyau.valeur_hors_tableur("#REF!"), "#REF!")


class TestFormatDeNombre(unittest.TestCase):
    """Le texte libre d'un format, séparé du motif qui l'entoure.

    Excel porte du texte dans un format de quatre façons, dont une SANS
    guillemets ni barre oblique, et traduit ses marques de position dans
    la langue du classeur. Reconnaître le libellé sans abîmer le motif
    n'a donc rien d'un test sur les guillemets : chaque forme ci-dessous
    tranche un cas où l'une des deux moitiés a été perdue.
    """

    @staticmethod
    def _mot_si_long(interieur):
        """Le contrat de mot_si_long : None sous le seuil du filet."""
        if len(interieur.strip()) < noyau.LONGUEUR_VERIFIABLE:
            return None
        return "MOT"

    def _rendu(self, fmt):
        return formats._parcourir_format(fmt, self._mot_si_long)

    def test_motifs_traversent_intacts(self):
        """Un motif ne porte pas de donnée : le toucher abîme la copie.

        Les formes en lettres de locale — « jj/mm/aaaa » en français,
        « tt.mm.jjjj » en allemand, « gg/mm/aaaa » en italien — sont des
        dates au même titre que « dd/mm/yyyy ». Celles sans séparateur
        atteignent le seuil du filet à elles seules.
        """
        for fmt in (
            "0.00%",
            "General",
            "@",
            "0.00E+00",
            "# ??/??",
            "dd/mm/yyyy hh:mm:ss",
            "jj/mm/aaaa",
            "tt.mm.jjjj",
            "aaaa-mm-jj",
            "gg/mm/aaaa",
            "yyyymmdd",
            "aaaammjj",
            "hhmm",
            "mmss",
            "h:mm AM/PM",
            "mmm-yy",
            "jjjj jj mmmm aaaa",
            "0.00_);[Red](0.00)",
            "[Red]#,##0;-#,##0",
            "[h]:mm:ss",
            "[<=9999999]000-0000;000-000-0000",
            "_-* #,##0.00_-;-* #,##0.00_-",
            "0.00;;",
            "\u00a5#,##0.00",
        ):
            with self.subTest(fmt=fmt):
                self.assertEqual(self._rendu(fmt), fmt)

    def test_balise_de_locale_traverse_intacte(self):
        """Une section de devise dont TOUT est de convention.

        Le seul LCID hexadécimal ne les couvre pas, et les remplacer
        détruit le symbole monétaire de la copie ou la forme de ses
        dates.
        """
        for fmt in (
            "[$-en-US]jj/mm/aaaa",
            "[$-x-sysdate]",
            "[$\u20ac-x-euro2]#,##0",
            "[$-409]#,##0",
            "[$R$-pt-BR]#,##0.00",
        ):
            with self.subTest(fmt=fmt):
                self.assertEqual(self._rendu(fmt), fmt)

    def test_libelles_partent_par_leurs_quatre_ecritures(self):
        """Guillemets, barre oblique, section de devise, et texte nu."""
        for fmt, libelle in (
            ('#,##0" aboulie"', "aboulie"),
            ("#,##0.00\\a\\b\\o\\u\\l", "aboul"),
            ("[$aboulie-409]#,##0", "aboulie"),
            ("#,##0 aboulie", "aboulie"),
        ):
            with self.subTest(fmt=fmt):
                rendu = self._rendu(fmt)
                self.assertNotIn(libelle, rendu)
                self.assertIn("MOT", rendu)

    def test_le_motif_survit_au_libelle_nu(self):
        """Le remplacement porte sur le LIBELLÉ, pas sur toute la suite.

        Un libellé nu se lit dans la même course de texte que le motif
        qui le précède : remplacer la course entière rendait « "MOT" »
        seul, et la copie perdait sa forme numérique.
        """
        self.assertEqual(self._rendu("#,##0 aboulie"), '#,##0 "MOT"')
        self.assertEqual(self._rendu("0.0 aboulie %"), '0.0 "MOT" %')
        self.assertEqual(
            self._rendu("#,##0 aboulie;-#,##0 aboulie"),
            '#,##0 "MOT";-#,##0 "MOT"',
        )
        self.assertEqual(
            self._rendu("aboulie jj/mm/aaaa aboulie"),
            '"MOT" jj/mm/aaaa "MOT"',
        )
        self.assertEqual(
            self._rendu("aboulie 0.00E+00 aboulie"),
            '"MOT" 0.00E+00 "MOT"',
        )

    def test_mots_joints_par_un_espace_font_un_libelle(self):
        """« Nom du client » est UN libellé, pas trois mots à remplacer
        un à un : chacun pris seul retombe sous le seuil du filet."""
        self.assertEqual(self._rendu("#,##0 Nom du client"), '#,##0 "MOT"')

    def test_mot_et_marque_se_distinguent_par_la_repetition(self):
        """Une marque vient par groupes d'une même lettre, un mot non."""
        for marque in ("aaaa", "mm", "jjjj", "hhmm", "yyyymmdd", "General"):
            with self.subTest(marque=marque):
                self.assertFalse(formats._est_un_mot(marque))
        for mot in ("aboulie", "Nom", "client", "Total", "ZQXNU"):
            with self.subTest(mot=mot):
                self.assertTrue(formats._est_un_mot(mot))

    def test_les_jetons_entre_crochets_traversent_intacts(self):
        """La grammaire d'Excel ÉNUMÈRE ce qu'un crochet peut porter.

        C'est une spécification, non une devinette : l'énumération est
        légitime ici là où l'alphabet des marques de date a été rejeté.
        Chaque forme documentée est reprise, car en oublier une casse le
        code de format de la copie.
        """
        for fmt in (
            "[Red]#,##0",
            "[Green]0.00",
            "[Black]0",
            "[White]0",
            "[Blue]0",
            "[Cyan]0",
            "[Magenta]0",
            "[Yellow]0",
            "[Color12]0",
            "[COLOR 3]0",
            "[color56]0",
            "[DBNum1]0",
            "[NatNum12]0",
            "[h]:mm",
            "[mm]:ss",
            "[<100]0;[>=100]0.0",
            "[<>1]0",
            "[ENG]jj/mm/aaaa",
            "[THAI]0",
            "[t]0",
        ):
            with self.subTest(fmt=fmt):
                self.assertEqual(self._rendu(fmt), fmt)

    def test_une_section_hors_grammaire_porte_du_texte_libre(self):
        """Excel n'écrit pas une telle section, un producteur tiers si.

        Le remplacement reste NU : un crochet ne porte pas de guillemets,
        et la section était déjà hors grammaire avant qu'on y touche.
        """
        self.assertEqual(self._rendu("[aboulie]#,##0"), "[MOT]#,##0")
        self.assertEqual(self._rendu("[Nom du client]0.00"), "[MOT]0.00")

    def test_un_crochet_non_ferme_ne_boucle_pas(self):
        """`find` rend -1, et l'index repartait à zéro."""
        self.assertEqual(self._rendu("#,##0[aboulie"), "#,##0[aboulie")

    def test_libelle_de_devise_non_conventionnel_reste_un_libelle(self):
        """« [$Cabinet-Lav] » ressemble à une balise de locale et n'en
        est pas : son texte est libre, et un nom y tient."""
        rendu = self._rendu("[$aboulie-Lav]#,##0")
        self.assertNotIn("aboulie", rendu)


class TestNomDeFichier(unittest.TestCase):
    def test_separateur_remplace(self):
        pris = set()
        self.assertNotIn("/", noyau.nom_de_fichier_sur("Ventes/2024", pris))

    def test_nom_vide_numerote(self):
        pris = set()
        self.assertTrue(
            noyau.nom_de_fichier_sur("///", pris).startswith("feuille_")
        )

    def test_deux_noms_reduits_au_meme_se_distinguent(self):
        pris = set()
        premier = noyau.nom_de_fichier_sur("a/b", pris)
        second = noyau.nom_de_fichier_sur("a:b", pris)
        self.assertNotEqual(premier, second)


class TestPorteEntree(unittest.TestCase):
    """Refuser avant qu'une bibliothèque rapporte une exception."""

    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.base, True)

    def _fichier(self, nom, octets=b"x"):
        chemin = os.path.join(self.base, nom)
        with open(chemin, "wb") as fh:
            fh.write(octets)
        return chemin

    def test_repertoire_refuse(self):
        self.assertEqual(noyau.verifier_source(self.base), "pas_un_fichier")

    def test_absent_refuse(self):
        self.assertEqual(
            noyau.verifier_source(os.path.join(self.base, "rien")),
            "pas_un_fichier",
        )

    def test_taille_nulle_refusee(self):
        self.assertEqual(
            noyau.verifier_source(self._fichier("vide.csv", b"")), "vide"
        )

    def test_fichier_ordinaire_accepte(self):
        self.assertIsNone(
            noyau.verifier_source(self._fichier("bon.csv", b"a,b\n"))
        )

    def test_detect_format_par_les_octets(self):
        ole2 = self._fichier(
            "menteur.xlsx", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1rest"
        )
        # Un OLE2 sous une extension OOXML : protégé ou non conforme,
        # jamais passé à openpyxl, qui rendrait le même BadZipFile pour un
        # classeur chiffré et pour un fichier corrompu.
        self.assertEqual(noyau.detect_format(ole2), "protege")

        vrai_xls = self._fichier(
            "vieux.xls", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1rest"
        )
        self.assertEqual(noyau.detect_format(vrai_xls), "xls")

    def test_divergence_signalee(self):
        html = self._fichier("export.xls", b"<html><body>t</body></html>")
        self.assertTrue(
            noyau.format_divergent(html, noyau.detect_format(html))
        )

    def test_has_macros_ne_leve_sur_rien(self):
        """.xlsb passe par cette fonction et par elle seule."""
        for nom, octets in (
            ("ole.xlsb", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"),
            ("tronque.xlsx", b"PK\x03\x04tronque"),
            ("texte.xlsx", b"pas un zip"),
        ):
            self.assertFalse(noyau.has_macros(self._fichier(nom, octets)), nom)

    def test_has_macros_vrai_sur_un_zip_qui_en_porte(self):
        chemin = os.path.join(self.base, "avec.xlsm")
        with zipfile.ZipFile(chemin, "w") as z:
            z.writestr("xl/vbaProject.bin", b"\x00")
        self.assertTrue(noyau.has_macros(chemin))


class TestBoutEnBoutStdlib(unittest.TestCase):
    """CSV, JSON et XML : aucun openpyxl, donc lançables partout."""

    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.base, True)

    def _ecrire(self, nom, contenu):
        chemin = os.path.join(self.base, nom)
        with open(chemin, "w", encoding="utf-8") as fh:
            fh.write(contenu)
        return chemin

    def test_csv_bout_en_bout(self):
        source = self._ecrire(
            "clients.csv",
            "id,nom,montant,taux\n1,Alpha,4711,0.15\n"
            "2,Beta,-320,0.20\n3,Alpha,4711,0.15\n",
        )
        sortie = os.path.join(self.base, "out.csv")
        bilan = formats.ecrire(source, sortie, {"graine": "7"})
        lignes = [
            l.split(",")
            for l in open(sortie, encoding="utf-8").read().splitlines()
        ]
        # L'en-tête est intact par défaut.
        self.assertEqual(lignes[0], ["id", "nom", "montant", "taux"])
        # Le plancher protège « id ».
        self.assertEqual([l[0] for l in lignes[1:]], ["1", "2", "3"])
        # Le même client rend le même mot dans les deux lignes.
        self.assertEqual(lignes[1][1], lignes[3][1])
        self.assertNotEqual(lignes[1][1], lignes[2][1])
        # AUCUNE valeur texte de la source ne survit. Sans cette
        # assertion, un graveur inerte garde toutes les précédentes :
        # elles sont vraies des valeurs SOURCE aussi.
        texte = open(sortie, encoding="utf-8").read()
        self.assertNotIn("Alpha", texte)
        self.assertNotIn("Beta", texte)
        # Un montant reste un nombre, du même signe.
        self.assertGreater(float(lignes[1][2]), 0)
        self.assertLess(float(lignes[2][2]), 0)
        # Le taux reste dans l'étendue mesurée de sa colonne.
        for ligne in lignes[1:]:
            self.assertLessEqual(float(ligne[3]), 0.20)
            self.assertGreaterEqual(float(ligne[3]), 0.15)
        self.assertGreater(bilan["remplacees"], 0)

    def test_csv_la_source_n_est_pas_modifiee(self):
        source = self._ecrire("s.csv", "a,b\n1,Alpha\n")
        avant = (os.path.getmtime(source), os.path.getsize(source))
        formats.ecrire(
            source, os.path.join(self.base, "o.csv"), {"graine": "1"}
        )
        self.assertEqual(
            avant, (os.path.getmtime(source), os.path.getsize(source))
        )

    def test_csv_une_seule_colonne_ne_leve_pas(self):
        """csv.Sniffer lève sur cette forme, la plus courante ici."""
        source = self._ecrire("noms.csv", "nom\nAlpha\nBeta\nGamma\n")
        rapport = formats.report(source)
        self.assertEqual(rapport["delimiteur"], ",")
        self.assertEqual(rapport["delimiteur_source"], "repli")

    def test_csv_dents_de_scie_ne_leve_pas(self):
        source = self._ecrire("scie.csv", "a,b,c\n1,2\n3,4,5,6\n")
        rapport = formats.report(source)
        self.assertTrue(rapport["feuilles"])

    def test_csv_encodage_sans_chardet(self):
        chemin = os.path.join(self.base, "bom.csv")
        with open(chemin, "wb") as fh:
            fh.write("﻿a,b\n1,Alpha\n".encode("utf-8"))
        rapport = formats.report(chemin)
        self.assertEqual(rapport["encodage_source"], "bom")
        self.assertEqual(rapport["encodage"], "utf-8-sig")

    def test_json_cles_preservees_valeurs_anonymisees(self):
        source = self._ecrire(
            "d.json",
            json.dumps(
                [
                    {"id": 1, "nom": "Alpha", "montant": 4711},
                    {"id": 2, "nom": "Beta", "montant": -320},
                ]
            ),
        )
        sortie = os.path.join(self.base, "o.json")
        formats.ecrire(source, sortie, {"graine": "3"})
        arbre = json.load(open(sortie, encoding="utf-8"))
        self.assertEqual(sorted(arbre[0].keys()), ["id", "montant", "nom"])
        self.assertNotEqual(arbre[0]["nom"], "Alpha")
        self.assertGreater(arbre[0]["montant"], 0)
        self.assertLess(arbre[1]["montant"], 0)

    def test_xml_texte_et_attributs_par_la_meme_table(self):
        source = self._ecrire(
            "d.xml",
            '<racine><ligne ref="Alpha"><nom>Alpha</nom>'
            "<n>4711</n></ligne></racine>",
        )
        sortie = os.path.join(self.base, "o.xml")
        formats.ecrire(source, sortie, {"graine": "5"})
        import xml.etree.ElementTree as ET

        racine = ET.parse(sortie).getroot()
        ligne = racine.find("ligne")
        # Balises et noms d'attribut sont de la structure et restent.
        self.assertEqual(racine.tag, "racine")
        self.assertIn("ref", ligne.attrib)
        # Le MÊME identifiant en attribut et en texte rend le même mot,
        # sinon la jointure entre les deux casse.
        self.assertEqual(ligne.attrib["ref"], ligne.find("nom").text)
        self.assertNotEqual(ligne.attrib["ref"], "Alpha")

    def test_plan_n_ecrit_rien(self):
        source = self._ecrire("p.csv", "a,b\n1,Alpha\n")
        avant = (os.path.getmtime(source), os.path.getsize(source))
        apercu = formats.plan(source, {"graine": "1"})
        self.assertEqual(
            avant, (os.path.getmtime(source), os.path.getsize(source))
        )
        self.assertIn("remplacees", apercu)
        self.assertIn("colonnes_ecartees", apercu)

    def test_destination_egale_source_refusee(self):
        source = self._ecrire("s.csv", "a,b\n1,Alpha\n")
        avant = open(source, encoding="utf-8").read()
        with self.assertRaises(formats.ErreurMoteur) as capture:
            formats.ecrire(source, source, {"graine": "1"})
        self.assertEqual(capture.exception.cle, "destination_source")
        self.assertEqual(open(source, encoding="utf-8").read(), avant)

    def test_destination_lien_vers_la_source_refusee(self):
        source = self._ecrire("s.csv", "a,b\n1,Alpha\n")
        lien = os.path.join(self.base, "lien.csv")
        os.symlink(source, lien)
        with self.assertRaises(formats.ErreurMoteur) as capture:
            formats.ecrire(source, lien, {"graine": "1"})
        self.assertEqual(capture.exception.cle, "destination_source")

    def test_feuille_inconnue_refusee(self):
        source = self._ecrire("s.csv", "a,b\n1,Alpha\n")
        with self.assertRaises(formats.ErreurMoteur) as capture:
            formats.ecrire(
                source,
                os.path.join(self.base, "o.csv"),
                {"feuilles": ["Introuvable"]},
            )
        self.assertEqual(capture.exception.cle, "aucune_feuille")

    def test_aucun_temporaire_ne_subsiste_apres_un_echec(self):
        cible = os.path.join(self.base, "sortie", "o.csv")

        def graveur_qui_echoue(_chemin):
            raise OSError("disque plein")

        with self.assertRaises(OSError):
            formats._ecrire_atomique(cible, graveur_qui_echoue)
        restes = [
            n
            for n in os.listdir(os.path.dirname(cible))
            if n.startswith(".transform-")
        ]
        self.assertEqual(restes, [])

    def test_repertoire_de_destination_non_vide_refuse(self):
        plein = os.path.join(self.base, "plein")
        os.makedirs(plein)
        open(os.path.join(plein, "deja"), "w").close()
        with self.assertRaises(formats.ErreurMoteur) as capture:
            formats._preparer_repertoire(plein)
        self.assertEqual(capture.exception.cle, "repertoire_non_vide")

    def test_table_portable_entre_deux_fichiers(self):
        """Le même client doit rendre le même mot dans tout un lot.

        L'attribution étant indexée par ordre de première rencontre, deux
        fichiers listant les mêmes clients dans un ORDRE DIFFÉRENT leur
        donneraient des mots différents sans table partagée.
        """
        premier = self._ecrire("a.csv", "nom\nAlpha\nBeta\n")
        second = self._ecrire("b.csv", "nom\nBeta\nAlpha\n")
        table = os.path.join(self.base, "t.json")
        formats.ecrire(
            premier,
            os.path.join(self.base, "a.out.csv"),
            {"table_chemin": table},
        )
        formats.ecrire(
            second,
            os.path.join(self.base, "b.out.csv"),
            {"table_chemin": table},
        )
        lus = {}
        for nom, fichier in (
            ("a", "a.out.csv"),
            ("b", "b.out.csv"),
        ):
            lignes = (
                open(os.path.join(self.base, fichier), encoding="utf-8")
                .read()
                .splitlines()[1:]
            )
            lus[nom] = lignes
        # a.csv liste Alpha puis Beta ; b.csv l'inverse.
        self.assertEqual(lus["a"][0], lus["b"][1])
        self.assertEqual(lus["a"][1], lus["b"][0])

    def test_la_table_est_en_0600(self):
        source = self._ecrire("s.csv", "nom\nAlpha\n")
        table = os.path.join(self.base, "t.json")
        formats.ecrire(
            source,
            os.path.join(self.base, "o.csv"),
            {"table_chemin": table},
        )
        self.assertEqual(os.stat(table).st_mode & 0o777, 0o600)

    def test_conversion_csv_vers_json(self):
        source = self._ecrire("s.csv", "nom,n\nAlpha,5\n")
        sortie = os.path.join(self.base, "o.json")
        formats.ecrire(source, sortie, {"conversion": "json", "graine": "1"})
        # `assertTrue(arbre)` passait sur une recopie verbatim.
        self.assertNotIn("Alpha", open(sortie, encoding="utf-8").read())

    def test_le_nom_du_fichier_source_ne_sort_pas(self):
        """Le dialogue promet que le nom du fichier n'est pas anonymisé.

        Le recracher comme clé de premier niveau du JSON injectait dans la
        copie un identifiant qui n'était même pas dans la grille.
        """
        source = self._ecrire("Client_Tremblay_2024.csv", "nom\nAlpha\n")
        sortie = os.path.join(self.base, "o.json")
        formats.ecrire(source, sortie, {"conversion": "json", "graine": "1"})
        self.assertNotIn(
            "Client_Tremblay", open(sortie, encoding="utf-8").read()
        )

    def test_json_les_cles_sont_de_la_structure_et_sont_dites(self):
        source = self._ecrire(
            "k.json", '{"Alpha": {"responsable": "Beta", "solde": 1200}}'
        )
        apercu = formats.plan(source, {"graine": "3"})
        for exemple in apercu["apercu"]:
            self.assertNotEqual(exemple["avant"], "Alpha")
        self.assertIn(
            "Object keys are kept as structure; they may identify.",
            apercu["avertissements"],
        )

    def test_xml_la_queue_est_anonymisee(self):
        """Un export d'ERP nommé « .xls » qui est du HTML arrive ici.

        La moitié d'une cellule vit dans la QUEUE d'un élément : « Client
        <b>X</b> Nom » porte « Nom » après la balise fermante.
        """
        source = self._ecrire(
            "h.xml", "<t><td>Client <b>ABC</b> Alpha</td></t>"
        )
        sortie = os.path.join(self.base, "o.xml")
        formats.ecrire(source, sortie, {"graine": "3"})
        rendu = open(sortie, encoding="utf-8").read()
        self.assertNotIn("Alpha", rendu)
        # L'espace d'encadrement survit, sinon deux mots se collent.
        self.assertRegex(rendu, r"\w <b>")

    def test_la_portee_gouverne_aussi_le_json(self):
        """L'écriture passait par un SECOND parcours de l'arbre.

        Il ignorait le plancher et les colonnes intactes, au point de
        détruire l'external ID que le plancher venait de protéger.
        """
        source = self._ecrire(
            "r.json",
            json.dumps(
                [
                    {
                        "id": 7,
                        "partner_id/id": "base.p7",
                        "nom": "Alpha",
                        "ville": "Beta",
                    }
                ]
            ),
        )
        sortie = os.path.join(self.base, "o.json")
        formats.ecrire(
            source, sortie, {"graine": "3", "colonnes_intactes": ["nom"]}
        )
        arbre = json.load(open(sortie, encoding="utf-8"))
        self.assertEqual(arbre[0]["id"], 7)
        self.assertEqual(arbre[0]["partner_id/id"], "base.p7")
        self.assertEqual(arbre[0]["nom"], "Alpha")
        # Et la colonne qui EST en portée bouge, sinon le test passerait
        # sur une recopie verbatim de tout le fichier.
        self.assertNotEqual(arbre[0]["ville"], "Beta")

    def test_un_csv_SANS_en_tete_voit_sa_ligne_1_anonymisee(self):
        """C'était la fuite : la ligne 1 était PRÉSUMÉE d'en-tête, donc
        recopiée en clair, alors qu'elle porte un enregistrement complet.

        La mesure conclut qu'il n'y a pas d'en-tête, et la ligne entre en
        portée. Rien n'est alors gardé, donc rien n'est à nommer — c'est
        ce que l'ancien avertissement compensait de son mieux.
        """
        source = self._ecrire("sans.csv", "aboulie,1200\nacai,830\n")
        apercu = formats.plan(source, {"graine": "3"})
        self.assertEqual(apercu["entete_gardee"], [])
        avant = [c["avant"] for c in apercu["apercu"]]
        self.assertIn("aboulie", avant)

    def test_un_csv_AVEC_en_tete_le_garde_et_le_nomme(self):
        """L'autre sens : la mesure ne doit pas anonymiser un vrai
        en-tête, qui rendrait la copie illisible.

        La grille porte des types MÊLÉS, comme un export réel : c'est le
        régime où la mesure tranche. Une grille étroite et tout-
        alphabétique ne se décide pas, et le test suivant le dit.
        """
        source = self._ecrire(
            "avec.csv",
            "etiquette,montant,date,code\n"
            "aboulie,1200,2019-01-02,A1\n"
            "acai,830,2019-01-03,B2\n"
            "adobe,940,2019-01-04,C3\n",
        )
        apercu = formats.plan(source, {"graine": "3"})
        valeurs = [c["valeur"] for c in apercu["entete_gardee"]]
        self.assertIn("etiquette", valeurs)

    def test_une_grille_tout_alphabetique_ne_se_decide_pas(self):
        """La limite, ÉNONCÉE plutôt que masquée par un seuil ajusté.

        Rien de structurel ne sépare « nom » de « aboulie » : seul un
        vocabulaire le ferait, et une liste de noms de champs connus est
        une classe ouverte. Le verdict est donc « pas d'en-tête », ce qui
        ANONYMISE la ligne — le côté sur lequel pencher — et l'opérateur
        corrige.
        """
        source = self._ecrire(
            "mots.csv",
            "nom,ville\naboulie,acai\nacanthe,acai\nadelphique,acai\n",
        )
        apercu = formats.plan(source, {"graine": "3"})
        self.assertEqual(apercu["entete_gardee"], [])

    def test_la_table_ne_peut_pas_ecraser_la_source(self):
        source = self._ecrire("t.json", '{"client": "Alpha"}')
        avant = open(source, encoding="utf-8").read()
        with self.assertRaises(formats.ErreurMoteur) as capture:
            formats.ecrire(
                source,
                os.path.join(self.base, "o.json"),
                {"table_chemin": source},
            )
        self.assertEqual(capture.exception.cle, "table_source")
        self.assertEqual(open(source, encoding="utf-8").read(), avant)

    def test_la_table_ne_peut_pas_remplacer_la_copie(self):
        source = self._ecrire("s.csv", "nom\nAlpha\n")
        sortie = os.path.join(self.base, "o.csv")
        with self.assertRaises(formats.ErreurMoteur) as capture:
            formats.ecrire(source, sortie, {"table_chemin": sortie})
        self.assertEqual(capture.exception.cle, "table_source")
        self.assertFalse(os.path.exists(sortie))

    def test_la_table_existante_repasse_en_0600(self):
        """`os.open` n'applique son mode QU'À la création.

        Une table arrivée en 0644 par un clone, un `cp` ou un `tar -x` le
        resterait — et c'est le cas normal du flux prévu.
        """
        source = self._ecrire("s.csv", "nom\nAlpha\n")
        table = os.path.join(self.base, "t.json")
        with open(table, "w", encoding="utf-8") as fh:
            fh.write("{}")
        os.chmod(table, 0o644)
        formats.ecrire(
            source,
            os.path.join(self.base, "o.csv"),
            {"table_chemin": table},
        )
        self.assertEqual(os.stat(table).st_mode & 0o777, 0o600)

    def test_le_plancher_ne_recopie_plus_les_noms(self):
        """La fuite qui a motivé tout ce bloc.

        Cinq colonnes sur six d'un export import-compatible étaient
        recopiées mot pour mot, et l'écran l'annonçait comme une
        protection.
        """
        source = self._ecrire(
            "export.csv",
            "id,partner_id,user_id,display_name,state,montant\n"
            "7,Alpha,Beta,Gamma,Delta,1200.50\n",
        )
        sortie = os.path.join(self.base, "o.csv")
        formats.ecrire(source, sortie, {"graine": "3"})
        rendu = open(sortie, encoding="utf-8").read()
        for valeur in ("Alpha", "Beta", "Gamma", "Delta"):
            self.assertNotIn(valeur, rendu, valeur)
        # « id » reste, lui : son contenu a la forme d'un identifiant.
        self.assertIn("7,", rendu)


def _cles_du_menu(traduites_seulement=True):
    """Les clés littérales passées à `t()` dans le module du menu."""
    import ast

    chemin = os.path.join(
        os.path.dirname(__file__),
        "..",
        "script",
        "todo",
        "transform_menu.py",
    )
    arbre = ast.parse(open(chemin, encoding="utf-8").read())
    cles = []
    for noeud in ast.walk(arbre):
        if (
            isinstance(noeud, ast.Call)
            and isinstance(noeud.func, ast.Name)
            and noeud.func.id == "t"
            and noeud.args
            and isinstance(noeud.args[0], ast.Constant)
            and isinstance(noeud.args[0].value, str)
        ):
            valeur = noeud.args[0].value
            if valeur in cles:
                continue
            if traduites_seulement and valeur not in (todo_i18n.TRANSLATIONS):
                continue
            cles.append(valeur)
    return cles


class TestConseilDuRefus(unittest.TestCase):
    """Un refus dont l'opérateur ne devinerait pas le remède.

    Une macro cite couramment la valeur d'une cellule, et le projet VBA est
    recopié tel quel : garder les macros rend alors la copie irrecevable au
    filet. Le refus est juste — la valeur sortirait en clair — mais le
    détail nomme une partie du format sans dire quoi en faire, alors que
    l'option qui le cause vient d'être choisie un écran plus tôt.
    """

    def test_le_conseil_est_une_cle_a_part(self):
        """Mêler le remède au détail les rendait intraduisibles tous les
        deux : le détail porte un chemin, le conseil une phrase."""
        exc = formats.ErreurMoteur("fuite_detectee", "1 — x", "conseil")
        self.assertEqual(exc.detail, "1 — x")
        self.assertEqual(exc.conseil, "conseil")

    def test_sans_conseil_l_attribut_existe_quand_meme(self):
        """Le CLI le lit sur toute erreur, pas sur celles qui en ont un."""
        self.assertEqual(formats.ErreurMoteur("format_inconnu").conseil, "")

    def test_le_conseil_est_traduit_dans_les_deux_langues(self):
        avis = (
            "The kept VBA project quotes a source value;"
            " answer no to the macro question to write the copy."
        )
        self.assertIn(avis, todo_i18n.TRANSLATIONS)
        for langue in ("fr", "en"):
            with self.subTest(langue=langue):
                self.assertTrue(todo_i18n.TRANSLATIONS[avis][langue].strip())


class TestPolices(unittest.TestCase):
    """Aucune forme ne sépare une fonte courante d'une fonte de marque.

    Le renommage porte donc sur toutes celles que la liste ne nomme pas, et
    l'erreur penche du côté du dégât cosmétique. La liste est le confort de
    la copie, jamais la propriété de sûreté.
    """

    def test_les_courantes_gardent_leur_nom(self):
        for nom in (
            "Calibri",
            "Liberation Sans",
            "DejaVu Sans",
            "Consolas",
            "Georgia",
            "Wingdings",
            "Noto Sans",
        ):
            with self.subTest(nom=nom):
                self.assertIn(nom, formats.POLICES_COURANTES)

    def test_une_fonte_inconnue_est_renommee(self):
        self.assertNotIn("Aboulie Sans", formats.POLICES_COURANTES)


class TestAvertissementEncodage(unittest.TestCase):
    """Le délimiteur de la source est repris, son encodage NON.

    Le rapport annonce l'encodage détecté, ce qui laissait croire que la
    copie le garde. Elle sort en UTF-8 : un mot du vivier ou un en-tête
    gardé peut ne pas s'encoder dans le jeu d'origine, et l'écriture
    échouerait APRÈS la question du consentement.
    """

    AVIS = "The copy is written in UTF-8, whatever the source was."

    def test_un_encodage_autre_est_annonce(self):
        for encodage in ("cp1252", "latin-1", "ISO-8859-15"):
            with self.subTest(encodage=encodage):
                dits = formats._avertissements(
                    {"format": "csv", "encodage": encodage}, {}
                )
                self.assertIn(self.AVIS, dits)

    def test_utf8_ne_dit_rien(self):
        """Rien ne change, donc rien à dire : un avis sans objet use
        l'attention qu'il faudra ailleurs."""
        for encodage in ("utf-8", "UTF_8", "ascii", None, ""):
            with self.subTest(encodage=encodage):
                dits = formats._avertissements(
                    {"format": "csv", "encodage": encodage}, {}
                )
                self.assertNotIn(self.AVIS, dits)


class TestFichiersPrevus(unittest.TestCase):
    """Les chemins annoncés doivent être ceux qui seront écrits.

    Ce n'est pas qu'un affichage : cette liste est ce que le contrôle
    d'écrasement et celui de la table de correspondance examinent. Prédite
    d'après le nom d'ORIGINE d'une feuille, elle annonçait des chemins qui
    n'existeraient jamais, montrait le nom du client à l'écran, et laissait
    les fichiers réels échapper aux deux contrôles.
    """

    def setUp(self):
        self.feuilles = [
            formats.Feuille("Cabinet Lavigne", [["c"], ["x"]]),
            formats.Feuille("Fournisseurs 2024", [["c"], ["y"]]),
        ]
        self.options = {
            "vivier": VIVIER,
            "feuilles": [],
            "destination": "/tmp/sortie",
            "conversion": "csv",
        }

    def test_les_chemins_portent_le_nom_ANONYMISE(self):
        table = noyau.Correspondance()
        prevus = formats._fichiers_prevus(
            "s.xlsx", self.feuilles, self.options, table
        )
        self.assertEqual(len(prevus), 2)
        for chemin in prevus:
            self.assertNotIn("Lavigne", chemin)
            self.assertNotIn("Fournisseurs", chemin)

    def test_la_prediction_fige_ce_que_la_conversion_retrouvera(self):
        """La table est une correspondance stable : le nom réservé par la
        prédiction est celui que la conversion lira ensuite."""
        table = noyau.Correspondance()
        prevus = formats._fichiers_prevus(
            "s.xlsx", self.feuilles, self.options, table
        )
        attendus = [
            "%s.csv" % formats._nom_de_feuille_anonyme(f, table, self.options)
            for f in self.feuilles
        ]
        self.assertEqual([os.path.basename(c) for c in prevus], attendus)

    def test_sans_table_le_nom_d_origine_reste(self):
        """Rien n'est anonymisé quand rien ne l'est : la prédiction ne
        doit pas inventer un nom que l'écriture ne produira pas."""
        prevus = formats._fichiers_prevus(
            "s.xlsx", self.feuilles, self.options, None
        )
        self.assertIn(
            "Cabinet_Lavigne.csv", [os.path.basename(c) for c in prevus]
        )

    def test_une_seule_feuille_garde_la_destination_telle_quelle(self):
        prevus = formats._fichiers_prevus(
            "s.csv", self.feuilles[:1], self.options, noyau.Correspondance()
        )
        self.assertEqual(prevus, ["/tmp/sortie"])


class TestClesDistinctesEnJson(unittest.TestCase):
    """Un objet JSON écrase la clé qu'il répète, un tableur non.

    L'en-tête d'un tableur n'est qu'une ligne : rien ne l'empêche de
    porter deux fois « montant », ni de laisser deux colonnes sans titre.
    Rendu tel quel en clés d'objet, cela perdait des colonnes ENTIÈRES
    dans la copie, sans qu'une ligne du rapport ne le dise.
    """

    def test_etiquettes_repetees_se_distinguent(self):
        self.assertEqual(
            formats._cles_distinctes(["montant", "montant", "montant"]),
            ["montant", "montant_2", "montant_3"],
        )

    def test_etiquette_vide_n_est_pas_none(self):
        """La chaîne vide et l'espace ne passaient pas par le repli."""
        self.assertEqual(
            formats._cles_distinctes([None, "", "   ", "x"]),
            ["c1", "c2", "c3", "x"],
        )

    def test_l_etiquette_garde_ses_espaces(self):
        """Le test porte sur l'étiquette dépouillée, la clé la garde
        telle quelle : la dépouiller altérerait la copie en silence."""
        self.assertEqual(formats._cles_distinctes([" Nom "]), [" Nom "])

    def test_le_repli_ne_collisionne_pas_avec_une_etiquette(self):
        """Une colonne littéralement intitulée « c2 » existe."""
        self.assertEqual(
            formats._cles_distinctes(["c2", None]), ["c2", "c2_2"]
        )

    def test_autant_de_cles_que_de_colonnes(self):
        for etiquettes in (
            ["a", "a", None, "", "a"],
            [None] * 5,
            ["x"],
            [],
        ):
            with self.subTest(etiquettes=etiquettes):
                cles = formats._cles_distinctes(etiquettes)
                self.assertEqual(len(cles), len(etiquettes))
                self.assertEqual(len(set(cles)), len(etiquettes))


class TestConversion(unittest.TestCase):
    """Les cibles de conversion, qu'aucun test n'exerçait.

    C'est ce trou qui a laissé passer, tour à tour : le nom du fichier
    source recraché comme clé de premier niveau, une date rendue en texte
    ISO dans un classeur, et un nom de balise XML illégal écrit sans
    broncher puis annoncé comme écrit.
    """

    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.base, True)

    def _csv(self, nom, contenu):
        chemin = os.path.join(self.base, nom)
        with open(chemin, "w", encoding="utf-8") as fh:
            fh.write(contenu)
        return chemin

    def test_xml_etiquette_qui_commence_par_un_chiffre(self):
        """XML interdit à un nom d'élément de commencer par un chiffre.

        « 2024 » produisait `<2024>`, écrit, annoncé comme écrit, et refusé
        par tout analyseur.
        """
        import xml.etree.ElementTree as ET

        source = self._csv("mois.csv", "2024,nom\n1200,Alpha\n")
        sortie = os.path.join(self.base, "o.xml")
        formats.ecrire(source, sortie, {"conversion": "xml", "graine": "3"})
        # La seule assertion qui compte : le fichier se relit.
        ET.parse(sortie)

    def test_nom_de_balise_sur(self):
        self.assertEqual(formats._nom_de_balise_sur("nom", 1), "nom")
        self.assertTrue(formats._nom_de_balise_sur("2024", 1)[0].isalpha())
        self.assertEqual(formats._nom_de_balise_sur("", 3), "c3")
        self.assertEqual(formats._nom_de_balise_sur("a b", 1), "a_b")

    def test_un_fichier_par_feuille_au_dela_d_une_seule(self):
        self.assertFalse(
            formats._un_fichier_par_feuille(
                "csv", [formats.Feuille("a", [["x"]])], {"feuilles": None}
            )
        )
        self.assertTrue(
            formats._un_fichier_par_feuille(
                "csv",
                [
                    formats.Feuille("a", [["x"]]),
                    formats.Feuille("b", [["y"]]),
                ],
                {"feuilles": None},
            )
        )

    def test_repertoire_un_fichier_par_feuille(self):
        feuilles = [
            formats.Feuille("Ventes", [["nom"], ["Alpha"]]),
            formats.Feuille("Achats", [["nom"], ["Beta"]]),
        ]
        cible = os.path.join(self.base, "lot")
        ecrits = formats._convertir_vers_repertoire(cible, feuilles, {})
        self.assertEqual(len(ecrits), 2)
        self.assertEqual(os.stat(cible).st_mode & 0o777, 0o700)

    def test_conversion_vers_xml_refuse_plusieurs_feuilles(self):
        feuilles = [
            formats.Feuille("a", [["nom"], ["Alpha"]]),
            formats.Feuille("b", [["nom"], ["Beta"]]),
        ]
        with self.assertRaises(formats.ErreurMoteur):
            formats._convertir_vers_xml(
                os.path.join(self.base, "o.xml"), feuilles
            )

    def test_le_delimiteur_detecte_survit_a_l_ecriture(self):
        """Il servait à LIRE et pas à écrire.

        Un fichier à point-virgule revenait en virgule, et le tableur du
        destinataire le rendait en une seule colonne — après que l'écran
        avait imprimé « délimiteur détecté : ; ».
        """
        source = self._csv("pv.csv", "nom;ville\nAlpha;Beta\n")
        sortie = os.path.join(self.base, "o.csv")
        formats.ecrire(source, sortie, {"graine": "3"})
        rendu = open(sortie, encoding="utf-8").read()
        self.assertIn(";", rendu)
        self.assertNotIn(",", rendu)

    def test_une_cible_impossible_refuse_avant_l_APERCU(self):
        """Le refus venait du graveur, après le consentement.

        Et sous une clé qui accusait le format au lieu de nommer la
        contrainte. `_verifier_conversion` est appelée par `_preparer`,
        donc par `plan` comme par `ecrire` : le même refus aux deux.
        """
        feuilles = [
            formats.Feuille("Une", [["nom"], ["Alpha"]]),
            formats.Feuille("Deux", [["nom"], ["Beta"]]),
        ]
        with self.assertRaises(formats.ErreurMoteur) as capture:
            formats._verifier_conversion(
                "xlsx", feuilles, {"conversion": "xml"}
            )
        self.assertEqual(capture.exception.cle, "conversion_impossible")

    def test_une_seule_feuille_vers_xml_passe(self):
        formats._verifier_conversion(
            "xlsx",
            [formats.Feuille("Une", [["nom"], ["Alpha"]])],
            {"conversion": "xml"},
        )

    def test_la_selection_compte_dans_le_refus(self):
        """Deux feuilles, une seule retenue : la cible redevient possible."""
        feuilles = [
            formats.Feuille("Une", [["nom"], ["Alpha"]]),
            formats.Feuille("Deux", [["nom"], ["Beta"]]),
        ]
        formats._verifier_conversion(
            "xlsx", feuilles, {"conversion": "xml", "feuilles": ["Une"]}
        )

    def test_un_conteneur_ne_fait_pas_lever_openpyxl(self):
        """L'erreur brute ressortait sous « format non reconnu »."""
        rendu = formats._valeur_pour_xlsx({"nom": "aboulie"})
        self.assertIsInstance(rendu, str)
        self.assertIn("aboulie", rendu)
        self.assertIsInstance(formats._valeur_pour_xlsx([1, 2]), str)

    def test_valeur_pour_xlsx_garde_les_types(self):
        """openpyxl porte nativement datetime, int, float et bool.

        `valeur_hors_tableur` est écrite pour csv, json et xml, trois
        formats SANS types : elle rend une date en chaîne ISO, et la copie
        portait du texte là où une date était attendue.
        """
        quand = datetime.datetime(2024, 3, 1)
        self.assertIs(formats._valeur_pour_xlsx(quand), quand)
        self.assertIs(formats._valeur_pour_xlsx(True), True)
        self.assertEqual(formats._valeur_pour_xlsx(5), 5)
        self.assertIsNone(formats._valeur_pour_xlsx(b"\x00"))

        class FausseFormule:
            text = "=SUM(A1:A2)"

        self.assertEqual(
            formats._valeur_pour_xlsx(FausseFormule()), "=SUM(A1:A2)"
        )

    def test_bornes_ignorent_les_flottants_non_finis(self):
        feuille = formats.Feuille(
            "f",
            [["montant"], [1200.0], [float("nan")], [float("inf")]],
        )
        colonne = formats._stats_colonnes(feuille)[0]
        self.assertEqual((colonne["min"], colonne["max"]), (1200.0, 1200.0))


class TestGardeApresEcriture(unittest.TestCase):
    """Le filet : relire les octets écrits.

    Sa valeur est de ne dépendre d'AUCUNE énumération de vecteurs. Un
    endroit du format que personne n'a pensé à nettoyer produit un refus,
    là où une liste de parties à vérifier produirait un silence. Ce sont
    ces tests qui prouvent qu'il tire ; sans eux il pourrait être neutralisé
    sans qu'une ligne ne rougisse.
    """

    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.base, True)

    def _table(self, *valeurs):
        table = noyau.Correspondance()
        for valeur in valeurs:
            noyau.nouveau_mot(valeur, table, VIVIER)
        return table

    def test_ne_regarde_que_ce_qui_a_ete_remplace(self):
        """Ce qui est hors portée reste par DÉCISION, et est annoncé.

        Le mêler ici rendrait la garde bruyante au point d'être
        désactivée, ce qui est la seule manière de la rendre inutile.
        """
        table = self._table("Alpha")
        self.assertEqual(noyau.valeurs_a_verifier(table), {"Alpha"})

    def test_ignore_les_chaines_trop_courtes(self):
        table = self._table("ok", "abc", "Alpha")
        self.assertEqual(noyau.valeurs_a_verifier(table), {"Alpha"})

    def test_detecte_une_valeur_survivante(self):
        cible = os.path.join(self.base, "copie.txt")
        with open(cible, "w", encoding="utf-8") as fh:
            fh.write("rien ici sauf Alpha qui ne devrait pas y etre")
        fuites, ecartees = noyau.verifier_copie([cible], self._table("Alpha"))
        self.assertIn("Alpha", fuites)
        self.assertEqual(ecartees, 0)

    def test_tolere_ce_qui_est_garde_sciemment(self):
        cible = os.path.join(self.base, "copie.txt")
        with open(cible, "w", encoding="utf-8") as fh:
            fh.write("Alpha reste, il est annonce")
        fuites, _ = noyau.verifier_copie(
            [cible], self._table("Alpha"), gardees=["Alpha"]
        )
        self.assertEqual(fuites, {})

    def test_balaie_chaque_partie_d_un_zip(self):
        """Nommer les parties une à une est ce qui a laissé passer, tour à
        tour, un cache de graphique, un titre d'axe, un hyperlien de
        cellule et le nom d'une colonne de tableau."""
        cible = os.path.join(self.base, "copie.xlsx")
        with zipfile.ZipFile(cible, "w") as archive:
            archive.writestr("xl/worksheets/sheet1.xml", "<c>propre</c>")
            archive.writestr("xl/un/coin/inattendu.xml", "<c>Alpha</c>")
        fuites, _ = noyau.verifier_copie([cible], self._table("Alpha"))
        self.assertEqual(
            fuites["Alpha"], ["copie.xlsx:xl/un/coin/inattendu.xml"]
        )

    def test_la_couverture_ne_suit_pas_l_alphabet(self):
        """Le plafond tronquait une liste TRIÉE.

        La couverture était donc un préfixe lexicographique et non un
        échantillon : sur plusieurs colonnes de texte, seule la première
        était relue, à chaque exécution — une reprise n'y changeait rien,
        et l'écran affichait une écriture propre.
        """
        table = noyau.Correspondance()
        for index in range(20005):
            noyau.nouveau_mot(f"aaa-{index:06d}", table, VIVIER)
        # Cette valeur trie APRÈS les vingt mille autres.
        noyau.nouveau_mot("zzz_survivante", table, VIVIER)
        cible = os.path.join(self.base, "copie.txt")
        with open(cible, "w", encoding="utf-8") as fh:
            fh.write("il reste zzz_survivante dans la copie")
        fuites, ecartees = noyau.verifier_copie([cible], table)
        self.assertIn("zzz_survivante", fuites)
        self.assertEqual(ecartees, 0)

    def test_une_copie_plate_est_fouillee_ENTIERE(self):
        """La nature de la partie décide, pas ce que les regex capturent.

        Un seul couple « > … < » — un fragment HTML dans une colonne
        gardée suffit — ramenait le balayage à ce qui les sépare, et toute
        valeur hors de cet intervalle sortait sans refus.
        """
        for nom, contenu in (
            ("plat.csv", "nom,note\naboulie,<b>gras</b>\nzzz_leak,ici\n"),
            ("plat.json", '{"a": "<i>x</i>", "b": "zzz_leak"}'),
            ("plat.txt", "<html>rien</html>\nzzz_leak\n"),
        ):
            cible = os.path.join(self.base, nom)
            with open(cible, "w", encoding="utf-8") as fh:
                fh.write(contenu)
            fuites, _ = noyau.verifier_copie([cible], self._table("zzz_leak"))
            self.assertIn("zzz_leak", fuites, nom)

    def test_une_partie_binaire_est_fouillee_ENTIERE(self):
        """Un projet VBA n'a ni nœud ni attribut."""
        cible = os.path.join(self.base, "avec.xlsm")
        with zipfile.ZipFile(cible, "w") as archive:
            archive.writestr(
                "xl/worksheets/sheet1.xml", "<c><v>aboulie</v></c>"
            )
            archive.writestr("xl/vbaProject.bin", b"\x00\x01 zzz_leak \x02")
        fuites, _ = noyau.verifier_copie([cible], self._table("zzz_leak"))
        self.assertEqual(fuites["zzz_leak"], ["avec.xlsm:xl/vbaProject.bin"])

    def test_une_copie_propre_ne_produit_aucun_refus(self):
        cible = os.path.join(self.base, "propre.csv")
        with open(cible, "w", encoding="utf-8") as fh:
            fh.write("nom\naboulie\nacai\n")
        fuites, _ = noyau.verifier_copie([cible], self._table("Alpha", "Beta"))
        self.assertEqual(fuites, {})

    def test_est_xml_tranche_sur_la_nature(self):
        self.assertTrue(noyau._est_xml("xl/styles.xml", "nimporte"))
        self.assertTrue(noyau._est_xml("_rels/.rels", "x"))
        self.assertTrue(noyau._est_xml("sans_extension", "<?xml v?><a/>"))
        self.assertTrue(noyau._est_xml("bom", "\ufeff<a/>"))
        self.assertFalse(noyau._est_xml("x.bin", "\x00 pas du xml"))
        self.assertFalse(
            noyau._est_xml("plat.csv", "nom\nun <b>gras</b> ici\n")
        )

    def test_les_deux_formes_ne_se_comptent_pas_deux_fois(self):
        """Mêlées dans un ensemble, une chaîne portant « & » pesait deux.

        Le total dépassait alors la tolérance annoncée, et le filet
        refusait du travail légitime.
        """
        ecrites, nues, _t_e, _t_n = noyau._chaines_distinctes(
            "<a>Roy &amp; Fils</a><b>simple</b>"
        )
        self.assertIn("Roy &amp; Fils", ecrites)
        self.assertIn("Roy & Fils", nues)
        # Une valeur gardée qui porte « & » n'est pas refusée.
        cible = os.path.join(self.base, "amp.xml")
        with open(cible, "w", encoding="utf-8") as fh:
            fh.write("<r><a>Roy &amp; Fils</a></r>")
        fuites, _ = noyau.verifier_copie(
            [cible],
            self._table("Roy & Fils"),
            gardees=["Roy & Fils"],
        )
        self.assertEqual(fuites, {})

    def test_la_tolerance_ne_couvre_que_l_EGALITE(self):
        """L'appartenance à un bloc joint est un test de sous-chaîne.

        Toute chaîne tolérée qui CONTIENT la valeur la tolérait, y compris
        là où la valeur fuit — le grain le plus large possible.
        """
        cible = os.path.join(self.base, "c.csv")
        with open(cible, "w", encoding="utf-8") as fh:
            fh.write("nom\naboulie\nRoy et Fils SA\nRoy et Fils\n")
        fuites, _ = noyau.verifier_copie(
            [cible],
            self._table("Roy et Fils"),
            gardees=["Roy et Fils SA"],
        )
        self.assertIn("Roy et Fils", fuites)

    def test_une_valeur_toleree_a_l_identique_peut_paraitre_deux_fois(self):
        """Le cas ordinaire d'une colonne laissée intacte."""
        cible = os.path.join(self.base, "d.csv")
        with open(cible, "w", encoding="utf-8") as fh:
            fh.write("ville\nSainte-Lambda\nSainte-Lambda\n")
        fuites, _ = noyau.verifier_copie(
            [cible],
            self._table("Sainte-Lambda"),
            gardees=["Sainte-Lambda"],
        )
        self.assertEqual(fuites, {})

    def test_le_filet_voit_ce_que_le_graveur_a_ECHAPPE(self):
        """`csv` double le guillemet, `json.dump` le préfixe.

        Chercher les octets bruts d'un nom portant un guillemet n'y
        trouvait alors rien, et la copie partait avec.
        """
        for nom, contenu in (
            ("e.csv", 'nom\naboulie\n"Roy ""et"" Fils"\n'),
            ("f.json", json.dumps({"a": 'Roy "et" Fils'})),
        ):
            cible = os.path.join(self.base, nom)
            with open(cible, "w", encoding="utf-8") as fh:
                fh.write(contenu)
            fuites, _ = noyau.verifier_copie(
                [cible], self._table('Roy "et" Fils')
            )
            self.assertIn('Roy "et" Fils', fuites, nom)

    def test_le_prefiltre_ne_rend_aucun_faux_negatif(self):
        """La propriété sur laquelle tout le balayage repose.

        Le préfiltre n'existe que pour écarter une valeur sans la
        chercher : s'il pouvait écarter une valeur PRÉSENTE, le filet
        deviendrait aveugle en silence, ce qui est exactement le mode de
        défaillance qu'il est là pour empêcher.
        """
        bloc = noyau._joindre(
            {f"chaine_{i}_avec_du_texte" for i in range(500)}
        )
        bits = noyau._prefiltre(bloc)
        for i in range(500):
            for valeur in (
                f"chaine_{i}_avec_du_texte",
                f"aine_{i}_avec",
                "avec_du_texte",
            ):
                self.assertTrue(
                    noyau._peut_contenir(bits, valeur),
                    f"faux négatif sur {valeur!r}",
                )

    def test_le_prefiltre_ecarte_vraiment(self):
        bloc = noyau._joindre({"aboulie", "acai", "acanthe"})
        bits = noyau._prefiltre(bloc)
        ecartees = sum(
            0 if noyau._peut_contenir(bits, f"valeur_{i}_absente") else 1
            for i in range(200)
        )
        self.assertGreater(ecartees, 150)

    def test_une_valeur_plus_courte_que_le_ngramme_passe_toujours(self):
        bits = noyau._prefiltre(noyau._joindre({"aboulie"}))
        self.assertTrue(noyau._peut_contenir(bits, "ab"))

    def test_le_prefiltre_ne_change_pas_le_verdict(self):
        """Au-dessus et en dessous du seuil, le même résultat.

        C'est la seule façon de garder le préfiltre honnête : il accélère,
        il ne décide pas.
        """
        cible = os.path.join(self.base, "copie.txt")
        with open(cible, "w", encoding="utf-8") as fh:
            fh.write("il reste zzz_survivante ici, et rien d'autre")
        table = noyau.Correspondance()
        for i in range(noyau.SEUIL_PREFILTRE + 50):
            noyau.nouveau_mot(f"absente_{i:05d}", table, VIVIER)
        noyau.nouveau_mot("zzz_survivante", table, VIVIER)
        avec, _ = noyau.verifier_copie([cible], table)
        petite = noyau.Correspondance()
        noyau.nouveau_mot("zzz_survivante", petite, VIVIER)
        sans, _ = noyau.verifier_copie([cible], petite)
        self.assertIn("zzz_survivante", avec)
        self.assertEqual(set(avec), set(sans))

    def test_l_octet_nul_empeche_une_valeur_a_cheval(self):
        """Sans séparateur, deux chaînes voisines en fabriqueraient une."""
        bloc = noyau._joindre({"aaabbb", "cccddd"})
        self.assertEqual(bloc.count("bbbccc"), 0)
        self.assertIn("\x00", bloc)

    def test_l_ecriture_refuse_et_n_laisse_aucun_fichier(self):
        """Le refus doit être total : une copie partielle serait livrée."""
        source = os.path.join(self.base, "s.csv")
        with open(source, "w", encoding="utf-8") as fh:
            fh.write("nom\nAlpha\n")
        sortie = os.path.join(self.base, "o.csv")

        # Un graveur qui recopie la source telle quelle : exactement le
        # mutant que la suite laissait passer avant cette garde.
        def graveur_inerte(destination, feuille, options):
            with open(destination, "w", encoding="utf-8") as fh:
                fh.write("nom\nAlpha\n")
            return [destination]

        vrai = formats._ecrire_csv
        formats._ecrire_csv = graveur_inerte
        try:
            with self.assertRaises(formats.ErreurMoteur) as capture:
                formats.ecrire(source, sortie, {"graine": "3"})
        finally:
            formats._ecrire_csv = vrai
        self.assertEqual(capture.exception.cle, "fuite_detectee")
        self.assertFalse(os.path.exists(sortie))


class TestI18n(unittest.TestCase):
    """Aucune clé ne doit s'afficher en anglais faute de traduction."""

    def test_chaque_cle_erreur_du_moteur_est_traduite(self):
        """Le garde AST ne peut pas couvrir le moteur.

        Les clés du moteur sont des constantes dans un dict JSON, jamais
        passées à `t()` chez lui — c'est le menu qui traduit. Et `t()`
        rend la clé quand elle manque, sans lever : sans cette
        vérification, un francophone lirait de l'anglais et aucun test ne
        tomberait.
        """
        manquantes = [
            valeur
            for valeur in noyau.ERREURS.values()
            if valeur not in todo_i18n.TRANSLATIONS
        ]
        self.assertEqual(manquantes, [])

    def test_chaque_cle_du_menu_est_traduite(self):
        manquantes = [
            cle
            for cle in _cles_du_menu(traduites_seulement=False)
            if cle not in todo_i18n.TRANSLATIONS
        ]
        self.assertEqual(manquantes, [])

    def test_les_deux_langues_sont_remplies(self):
        for cle in list(noyau.ERREURS.values()):
            entree = todo_i18n.TRANSLATIONS[cle]
            self.assertTrue(entree.get("fr"), cle)
            self.assertTrue(entree.get("en"), cle)

    def test_les_libelles_correspondent_a_leur_parseur(self):
        """Un « (O/n) » lu par _is_yes promet oui et vaut non.

        La convention du dépôt : `(Y/n)` / `(O/n)` se lit par
        `_is_yes_default_yes`, `(y/N)` / `(o/N)` par `_is_yes`.
        """
        # SEULEMENT les clés de ce module : le dépôt en compte des
        # milliers, et d'autres menus formulent légitimement autrement.
        verifiees = 0
        for cle in _cles_du_menu():
            entree = todo_i18n.TRANSLATIONS[cle]
            if "(Y/n)" in cle:
                self.assertIn("(O/n)", entree["fr"], cle)
                verifiees += 1
            if "(y/N)" in cle:
                self.assertIn("(o/N)", entree["fr"], cle)
                verifiees += 1
        self.assertGreater(verifiees, 4, "le test ne vérifie rien")


class TestEnvironnement(unittest.TestCase):
    def test_formats_stdlib_disponibles_sans_venv(self):
        for fmt in ("csv", "json", "xml", "macros"):
            self.assertTrue(transform_setup.available(fmt), fmt)

    def test_interpreteur_toujours_executable(self):
        for fmt in ("csv", "xlsx", None):
            self.assertTrue(
                os.path.isfile(transform_setup.engine_python(fmt)), fmt
            )

    def test_paquet_systeme_delegue_a_todo_install(self):
        """Aucune cascade apt/dnf/pacman/zypper de plus ici.

        Et pas d'entrée `pacman` : mdbtools n'est pas dans les dépôts
        officiels d'Arch, seulement l'AUR. `install_command` doit alors
        rendre None plutôt qu'une commande qui échoue APRÈS le mot de
        passe sudo.
        """
        self.assertNotIn("pacman", transform_setup.PAQUETS_ACCESS)
        commande = transform_setup.system_packages_cmd()
        self.assertTrue(commande is None or "mdbtools" in commande)

    def test_creation_refusee_n_installe_rien(self):
        lances = []
        fait = transform_setup.create(
            ask=lambda _: "n", executeur=lances.append
        )
        self.assertFalse(fait)
        self.assertEqual(lances, [])

    def test_capabilities_nomme_xlsb_illisible(self):
        self.assertFalse(transform_setup.capabilities()["xlsb"])


# ----------------------------------------------------------------------
# Ce qui exige openpyxl. Ignoré et DIT quand il manque.
# ----------------------------------------------------------------------
MARQUEURS = {
    "props_creator": "ZQXCREATOR",
    "props_modif": "ZQXMODIF",
    "props_title": "ZQXTITLE",
    "props_keywords": "ZQXKEYWORD",
    "custom_prop": "ZQXCUSTOM",
    "comment_text": "ZQXCOMTEXT",
    "comment_author": "ZQXCOMAUTH",
    "hyperlink": "ZQXHYPER",
    "header": "ZQXHEADER",
    "footer": "ZQXFOOTER",
    "validation": "ZQXVALID",
    "condformat": "ZQXCONDF",
    "chart_title": "ZQXCHTITLE",
    "axis_x_title": "ZQXAXISX",
    "axis_y_title": "ZQXAXISY",
    "series_name": "ZQXSERIES",
    "cat_cache": "ZQXCATCACHE",
    "cell_value": "ZQXCELL",
    "defined_value": "ZQXNAMEVAL",
    # Les trois vecteurs qui portent une COPIE ENTIÈRE de la source. La
    # fixture ne les portait pas, si bien que les assertions d'absence
    # portaient sur des parties JAMAIS présentes : `ws._pivots = []`,
    # `ws._images = []` et `keep_links=False` pouvaient chacun disparaître
    # sans qu'une ligne ne rougisse.
    "pivot_cache": "ZQXPIVOT",
    "lien_externe": "ZQXEXTLINK",
    "image": "ZQXIMAGE",
    "filtre": "ZQXFILTRE",
    # Une feuille GRAPHIQUE n'a aucune cellule : la passe sur la grille ne
    # la voit pas, `worksheets` l'exclut par construction, et son titre
    # comme son en-tête ne passent par aucune règle.
    "titre_feuille_graph": "ZQXCHSHEET",
    "entete_feuille_graph": "ZQXCHHEAD",
    # Le littéral d'un format de nombre personnalisé et le nom d'un style
    # nommé : tous deux vivent dans xl/styles.xml, hors de toute cellule.
    "format_nombre": "ZQXNUMFMT",
    "style_nomme": "ZQXSTYLE",
    # Un axe et une étiquette de données portent leur PROPRE format, dans
    # la partie graphique. Vider les titres et les caches les laisse, et
    # le filet ne les rattrape pas : il ne refuse que ce qui a été annoncé
    # remplacé, et un libellé qui n'a jamais été lu d'une cellule n'est
    # annoncé par personne.
    "format_axe": "ZQXAXISFMT",
    "format_etiquette": "ZQXLBLFMT",
    # Un style différentiel porte sa police EN LIGNE : elle n'est pas dans
    # la liste des polices du classeur, que la passe de renommage
    # parcourt. Une fonte de marque nommée par une seule mise en forme
    # conditionnelle traversait.
    "police_dxf": "ZQXFONTDXF",
}

# Les quatre familles référencées par une formule. On ne peut pas les
# supprimer sans casser ce que la règle de la formule vient de préserver :
# elles sont RAPPORTÉES, pas effacées.
MARQUEURS_CLASSE_B = {
    "defined_global": "ZQXNAMEGLOB",
    "defined_local": "ZQXNAMELOC",
    "table_name": "ZQXTABLE",
    "formula_literal": "ZQXFORMULA",
    "sheet_name": "ZQXSHEET",
}

TOUS_MARQUEURS = dict(MARQUEURS)
TOUS_MARQUEURS.update(MARQUEURS_CLASSE_B)


def _fabriquer_fixture(chemin):
    """Un classeur portant un marqueur inventé dans chaque vecteur.

    Le graphique DOIT être bâti par `add_data()` + `set_categories()` : un
    `Series()` construit à la main puis appendu n'écrit ni `<cat>`, ni
    `<val>`, ni `strRef` : les balises de `<ser>` se limitent alors à
    `idx`, `order`, `tx`, `spPr`. Une fixture bâtie ainsi ne porte pas le
    vecteur de cache, et le test rapporterait « effacé » sur un marqueur
    qui n'a jamais été écrit.
    """
    from openpyxl import Workbook
    from openpyxl.chart import BarChart, Reference, Series
    from openpyxl.chart.label import DataLabelList
    from openpyxl.comments import Comment
    from openpyxl.formatting.rule import CellIsRule
    from openpyxl.packaging.custom import (
        CustomPropertyList,
        StringProperty,
    )
    from openpyxl.styles import Font, PatternFill
    from openpyxl.workbook.defined_name import DefinedName
    from openpyxl.worksheet.datavalidation import DataValidation
    from openpyxl.worksheet.table import Table, TableStyleInfo

    M = TOUS_MARQUEURS
    classeur = Workbook()
    onglet = classeur.active
    onglet.title = M["sheet_name"]

    onglet["A1"] = "etiquette"
    onglet["B1"] = "montant"
    onglet["A2"] = M["cell_value"]
    onglet["B2"] = 4711
    onglet["A3"] = "autre"
    onglet["B3"] = 12
    onglet["C2"] = f'=IF(A2="{M["formula_literal"]}",1,0)'

    classeur.properties.creator = M["props_creator"]
    classeur.properties.lastModifiedBy = M["props_modif"]
    classeur.properties.title = M["props_title"]
    classeur.properties.keywords = M["props_keywords"]

    proprietes = CustomPropertyList()
    proprietes.append(StringProperty(name="client", value=M["custom_prop"]))
    classeur.custom_doc_props = proprietes

    onglet["A2"].comment = Comment(M["comment_text"], M["comment_author"])
    onglet["A3"].hyperlink = f"https://{M['hyperlink']}.example/rapport.xlsx"
    onglet.oddHeader.center.text = M["header"]
    onglet.oddFooter.left.text = M["footer"]

    validation = DataValidation(
        type="list", formula1=f'"{M["validation"]},autre"'
    )
    onglet.add_data_validation(validation)
    validation.add("D2:D10")

    onglet.conditional_formatting.add(
        "E2:E10",
        CellIsRule(
            operator="equal",
            formula=[f'"{M["condformat"]}"'],
            fill=PatternFill(start_color="FFEE1111", end_color="FFEE1111"),
            font=Font(name=M["police_dxf"]),
        ),
    )
    onglet.auto_filter.ref = "A1:B3"

    classeur.defined_names.add(
        DefinedName(M["defined_global"], attr_text=f'"{M["defined_value"]}"')
    )
    onglet.defined_names.add(
        DefinedName(M["defined_local"], attr_text=f"'{onglet.title}'!$A$1")
    )

    onglet["G1"] = M["table_name"]
    onglet["G2"] = "x"
    tableau = Table(displayName=M["table_name"], ref="G1:G2")
    tableau.tableStyleInfo = TableStyleInfo(name="TableStyleMedium9")
    onglet.add_table(tableau)

    graphique = BarChart()
    graphique.title = M["chart_title"]
    graphique.x_axis.title = M["axis_x_title"]
    graphique.y_axis.title = M["axis_y_title"]
    graphique.add_data(
        Reference(onglet, min_col=2, min_row=1, max_row=3),
        titles_from_data=True,
    )
    graphique.set_categories(
        Reference(onglet, min_col=1, min_row=2, max_row=3)
    )
    graphique.series.append(
        Series(
            Reference(onglet, min_col=2, min_row=2, max_row=3),
            title=M["series_name"],
        )
    )
    graphique.y_axis.numFmt = '#,##0" %s"' % M["format_axe"]
    if graphique.dLbls is None:
        graphique.dLbls = DataLabelList()
    graphique.dLbls.numFmt = '#,##0" %s"' % M["format_etiquette"]
    onglet.add_chart(graphique, "J2")

    # Un filtre automatique AVEC une valeur : `auto_filter.ref` seul ne
    # pose aucun `filterColumn`, donc l'effacement n'était pas exercé.
    onglet.auto_filter.add_filter_column(
        0, [M["filtre"], "autre"], blank=False
    )

    # Une image dont le marqueur vit dans un chunk PNG tEXt : openpyxl ne
    # recopie xl/media/ que si Pillow est là, et c'est le vecteur le plus
    # dense qu'un classeur puisse porter.
    from openpyxl.drawing.image import Image as XLImage
    from PIL import Image as PILImage
    from PIL import PngImagePlugin

    png = os.path.join(os.path.dirname(chemin), "img.png")
    info = PngImagePlugin.PngInfo()
    info.add_text("Comment", M["image"])
    PILImage.new("RGB", (4, 4), (200, 10, 10)).save(png, pnginfo=info)
    onglet.add_image(XLImage(png), "L2")

    onglet["B2"].number_format = '#,##0" %s"' % M["format_nombre"]
    onglet["B3"].number_format = '#,##0" kg"'
    from openpyxl.styles import Font, NamedStyle

    style = NamedStyle(name=M["style_nomme"], font=Font(bold=True))
    classeur.add_named_style(style)
    onglet["A3"].style = M["style_nomme"]

    feuille_graph = classeur.create_chartsheet(M["titre_feuille_graph"])
    feuille_graph.oddHeader.center.text = M["entete_feuille_graph"]
    # Un graphique attaché, comme Excel en produit toujours : openpyxl
    # 3.1.2 ne RELIT pas une feuille graphique qui n'en a pas — son
    # lecteur de relations lève `AttributeError`. Une fixture sans
    # graphique éprouverait ce défaut de la bibliothèque, pas le nôtre.
    graphique_feuille = BarChart()
    graphique_feuille.add_data(
        Reference(onglet, min_col=2, min_row=1, max_row=3),
        titles_from_data=True,
    )
    feuille_graph.add_chart(graphique_feuille)

    classeur.save(chemin)
    _injecter_cache(chemin)
    _injecter_parties_de_copie(chemin)
    return chemin


def _injecter_parties_de_copie(chemin):
    """Poser un cache de tableau croisé et un lien externe.

    openpyxl sait les LIRE et non les écrire : sans injection au niveau du
    zip, la fixture ne porte pas les deux parties dont le message de
    commit dit qu'elles contiennent « une copie entière » de la source.
    """
    temporaire = chemin + ".tmp"
    parties = {
        "xl/pivotCache/pivotCacheRecords1.xml": (
            '<?xml version="1.0"?><pivotCacheRecords count="1">'
            f"<r><s v=\"{TOUS_MARQUEURS['pivot_cache']}\"/></r>"
            "</pivotCacheRecords>"
        ),
        "xl/externalLinks/externalLink1.xml": (
            '<?xml version="1.0"?><externalLink><externalBook>'
            f"<sheetNames><sheetName val=\"{TOUS_MARQUEURS['lien_externe']}\"/>"
            "</sheetNames></externalBook></externalLink>"
        ),
    }
    with zipfile.ZipFile(chemin) as entree, zipfile.ZipFile(
        temporaire, "w", zipfile.ZIP_DEFLATED
    ) as sortie:
        for item in entree.infolist():
            # Les membres NON XML passent en octets : décoder
            # xl/media/image1.png lèverait UnicodeDecodeError.
            sortie.writestr(item, entree.read(item.filename))
        for nom, contenu in parties.items():
            sortie.writestr(nom, contenu)
    os.replace(temporaire, chemin)


def _injecter_cache(chemin):
    """Poser un cache de catégories, qu'openpyxl n'écrit pas lui-même.

    C'est Excel qui remplit `strCache`, et les balises du graphique sont
    écrites SANS préfixe « c: » — mesuré. Viser `<c:cat>` ne trouverait
    rien, et le vecteur resterait absent de la fixture.
    """
    temporaire = chemin + ".tmp"
    cache = (
        "<cat><strRef><f>ref</f><strCache>"
        '<ptCount val="1"/><pt idx="0"><v>'
        + TOUS_MARQUEURS["cat_cache"]
        + "</v></pt></strCache></strRef></cat>"
    )
    injecte = False
    with zipfile.ZipFile(chemin) as entree, zipfile.ZipFile(
        temporaire, "w", zipfile.ZIP_DEFLATED
    ) as sortie:
        for item in entree.infolist():
            octets = entree.read(item.filename)
            # Le classeur porte plusieurs graphiques : viser le PREMIER qui
            # a des catégories. Exiger « <cat> » dans chacun ferait tomber
            # la fabrication sur le graphique de la feuille graphique, qui
            # n'en a pas.
            if (
                not injecte
                and item.filename.startswith("xl/charts/chart")
                and b"<cat>" in octets
            ):
                texte = octets.decode("utf-8")
                debut = texte.index("<cat>")
                fin = texte.index("</cat>") + len("</cat>")
                octets = (texte[:debut] + cache + texte[fin:]).encode("utf-8")
                injecte = True
            sortie.writestr(item, octets)
    # Sans cache injecté, la mesure serait creuse : le test rapporterait
    # « effacé » sur un marqueur jamais écrit.
    assert injecte, "aucun graphique ne porte <cat>"
    os.replace(temporaire, chemin)


# Le processus de test tourne sous `.venv.erplibre`, qui n'a PAS openpyxl :
# c'est la contrainte de `run_unit_test.sh`. La fabrication de la fixture et
# l'écriture passent donc par le venv dédié, en SOUS-PROCESSUS — ce qui
# éprouve du même coup le protocole JSON du moteur. Le balayage, lui, reste
# ici : il ne demande que `zipfile`.
_AMORCE = (
    "import importlib.util, sys;"
    "s = importlib.util.spec_from_file_location('fx', sys.argv[1]);"
    "m = importlib.util.module_from_spec(s);"
    "s.loader.exec_module(m);"
    "m._fabriquer_fixture(sys.argv[2])"
)


def _racine():
    return os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))


def _sous_processus(arguments):
    """Lancer sous l'interpréteur du venv dédié. Rend le CompletedProcess."""
    environnement = dict(os.environ)
    environnement["PYTHONPATH"] = _racine()
    return subprocess.run(
        [transform_setup.engine_python("xlsx")] + list(arguments),
        capture_output=True,
        text=True,
        cwd=_racine(),
        env=environnement,
    )


def _fabriquer_par_sous_processus(chemin):
    acheve = _sous_processus(
        ["-c", _AMORCE, os.path.abspath(__file__), chemin]
    )
    if acheve.returncode:
        raise AssertionError(
            "la fixture n'a pas pu être fabriquée :\n" + acheve.stderr
        )
    return chemin


def _ecrire_par_sous_processus(source, destination, options):
    acheve = _sous_processus(
        [
            os.path.join("script", "data", "external_file.py"),
            "--apply",
            source,
            "--out",
            destination,
            "--options",
            json.dumps(options),
        ]
    )
    try:
        resultat = json.loads(acheve.stdout or "")
    except ValueError:
        raise AssertionError(
            "stdout ne porte pas de JSON :\n"
            + (acheve.stdout or "")[:400]
            + "\n"
            + acheve.stderr[-800:]
        )
    if "erreur" in resultat:
        raise AssertionError(f"{resultat['erreur']} {resultat.get('detail')}")
    return resultat


def _balayer(chemin):
    """{clé de marqueur: [parties du zip]} — TOUTES les parties."""
    trouves = {}
    with zipfile.ZipFile(chemin) as archive:
        for nom in archive.namelist():
            texte = archive.read(nom).decode("utf-8", "ignore")
            for cle, marqueur in TOUS_MARQUEURS.items():
                if marqueur in texte:
                    trouves.setdefault(cle, []).append(nom)
    return trouves


@unittest.skipUnless(
    transform_setup.available("xlsx"),
    "openpyxl absent : bâtir .venv.todo.external_data"
    " (TODO › Transform data › Install the reading environment)",
)
class TestFuiteXlsx(unittest.TestCase):
    """Le test qui garde toute la fonctionnalité.

    Son résultat est MESURÉ, pas espéré. La version précédente de ce
    nettoyage était annoncée « vérifiée » et laissait passer trois
    vecteurs sur quatre : les caches de graphique, les titres d'axes et
    les hyperliens de cellule.
    """

    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.base, True)
        self.source = _fabriquer_par_sous_processus(
            os.path.join(self.base, "source.xlsx")
        )

    def test_la_fixture_porte_bien_tous_les_marqueurs(self):
        """Sans cette garde, un « effacé » peut ne rien prouver."""
        presents = set(_balayer(self.source))
        manquants = sorted(set(TOUS_MARQUEURS) - presents)
        self.assertEqual(manquants, [])

    def _anonymiser(self, **options):
        sortie = os.path.join(self.base, "sortie.xlsx")
        _ecrire_par_sous_processus(
            self.source, sortie, {"graine": "11", **options}
        )
        return sortie

    def test_les_seuls_survivants_sont_les_quatre_familles(self):
        survivants = set(_balayer(self._anonymiser()))
        self.assertEqual(
            survivants,
            set(MARQUEURS_CLASSE_B),
            "la liste EXACTE : un vecteur rouvert doit faire tomber ce"
            " test, pas passer inaperçu",
        )

    def test_le_compte_des_effaces(self):
        efface = set(TOUS_MARQUEURS) - set(_balayer(self._anonymiser()))
        self.assertEqual(len(TOUS_MARQUEURS), 35)
        self.assertEqual(len(efface), 30)

    def test_la_constante_d_une_plage_nommee_passe_par_la_table(self):
        """Le NOM survit par nécessité, la VALEUR doit partir.

        Mesurée comme survivante tant qu'on ne remplace pas la constante :
        c'est ce que la classe (b) exige, et le nom reste résolvable.
        """
        survivants = _balayer(self._anonymiser())
        self.assertNotIn("defined_value", survivants)
        self.assertIn("defined_global", survivants)

    def test_les_proprietes_du_document_sont_videes(self):
        sortie = self._anonymiser()
        with zipfile.ZipFile(sortie) as archive:
            coeur = archive.read("docProps/core.xml").decode("utf-8")
        # `creator` vaut « openpyxl » par DÉFAUT : sans creator=None,
        # l'élément ne disparaît pas, il est rempli.
        self.assertNotIn("dc:creator", coeur)
        self.assertNotIn("cp:lastModifiedBy", coeur)

    def test_les_parties_qui_portent_une_copie_disparaissent(self):
        with zipfile.ZipFile(self._anonymiser()) as archive:
            noms = archive.namelist()
        for prefixe in (
            "xl/pivotCache",
            "xl/externalLinks",
            "xl/comments/",
            "xl/media/",
        ):
            self.assertFalse(
                [n for n in noms if n.startswith(prefixe)], prefixe
            )

    def test_la_feuille_graphique_part_toujours(self):
        """Rien ne peut l'anonymiser : elle n'a pas de cellule.

        La retirer seulement quand une sélection de feuilles existe faisait
        mentir l'avertissement dans tous les autres cas.
        """
        survivants = _balayer(self._anonymiser())
        self.assertNotIn("titre_feuille_graph", survivants)
        self.assertNotIn("entete_feuille_graph", survivants)

    def test_les_graphiques_partent_par_defaut(self):
        with zipfile.ZipFile(self._anonymiser()) as archive:
            noms = archive.namelist()
        self.assertFalse([n for n in noms if n.startswith("xl/charts")])

    def test_graphiques_gardes_le_nom_de_serie_part_quand_meme(self):
        """`s.tx = None` est indispensable : le nom a DEUX formes.

        `<tx><v>littéral</v>` quand il est tapé,
        `<tx><strRef><f>réf</f>` quand il vient des données. Ni l'une ni
        l'autre n'est un cache : vider strCache/numCache les laisserait
        toutes deux en place.
        """
        sortie = self._anonymiser(garder_graphiques=True)
        survivants = _balayer(sortie)
        self.assertNotIn("series_name", survivants)
        self.assertNotIn("cat_cache", survivants)
        self.assertNotIn("chart_title", survivants)
        self.assertNotIn("axis_x_title", survivants)

    def test_graphiques_gardes_le_nom_de_feuille_fuit_en_plus(self):
        """La référence <f> d'une série porte 'feuille'!$B$1.

        Le chemin par défaut l'évite : c'est une raison de plus d'en
        faire le défaut.
        """
        sortie = self._anonymiser(garder_graphiques=True)
        parties = _balayer(sortie).get("sheet_name", [])
        self.assertTrue([p for p in parties if p.startswith("xl/charts")])

    def test_les_formules_survivent_et_les_valeurs_changent(self):
        """Lu par zipfile : le processus de test n'a pas openpyxl."""
        with zipfile.ZipFile(self._anonymiser()) as archive:
            feuille = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
        # La formule est conservée telle quelle par la règle.
        self.assertIn(TOUS_MARQUEURS["formula_literal"], feuille)
        # La valeur de cellule, elle, a changé — les chaînes vivent dans
        # sharedStrings.xml, qui est balayé par _balayer().
        self.assertNotIn("cell_value", _balayer(self._anonymiser()))

    def test_le_littéral_d_un_format_de_nombre_est_assaini(self):
        """Excel laisse suffixer un nombre d'un libellé.

        Ce libellé vit dans `xl/styles.xml`, hors de toute cellule : aucune
        règle ne le voyait, et le filet refusait le classeur sans jamais
        l'assainir. Un littéral COURT — une devise, une unité — reste : il
        ne porte aucune donnée et le remplacer abîmerait le classeur.
        """
        sortie = self._anonymiser()
        with zipfile.ZipFile(sortie) as archive:
            styles = archive.read("xl/styles.xml").decode("utf-8")
        self.assertNotIn(TOUS_MARQUEURS["format_nombre"], styles)
        self.assertNotIn(TOUS_MARQUEURS["style_nomme"], styles)
        # L'unité survit, et la structure du format avec elle.
        self.assertIn("kg", styles)
        self.assertIn("#,##0", styles)

    def test_la_source_n_est_pas_modifiee(self):
        avant = (
            os.path.getmtime(self.source),
            os.path.getsize(self.source),
        )
        self._anonymiser()
        self.assertEqual(
            avant,
            (
                os.path.getmtime(self.source),
                os.path.getsize(self.source),
            ),
        )


if __name__ == "__main__":
    unittest.main()
