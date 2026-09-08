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

import datetime
import json
import os
import random
import re
import shutil
import subprocess
import tempfile
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

    def test_la_ligne_1_gardee_est_nommee(self):
        """Un CSV sans en-tête met un enregistrement complet en ligne 1."""
        source = self._ecrire("sans.csv", "Alpha,1200\nBeta,830\n")
        apercu = formats.plan(source, {"graine": "3"})
        valeurs = [c["valeur"] for c in apercu["entete_gardee"]]
        self.assertIn("Alpha", valeurs)

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
        ecrites, nues = noyau._chaines_distinctes(
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
    from openpyxl.styles import PatternFill
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
        self.assertEqual(len(TOUS_MARQUEURS), 34)
        self.assertEqual(len(efface), 29)

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
