#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce que le chargeur de gpts doit refuser, et ce qu'il ne doit jamais taire.

`yaml.safe_load` n'est pas un validateur, et c'est là que ce chargeur se
joue : un en-tête qui est une liste rend une `list`, un scalaire nu une `str`,
un fichier vide `None`, et une clé RÉPÉTÉE est résolue sans un mot sur la
dernière. Aucun des quatre ne lève. Un chargeur qui n'attraperait que
`yaml.YAMLError` admettrait donc trois formes malformées et tomberait plus
loin, sur un attribut manquant.

La clé répétée est le cas qui coûte le plus cher : deux blocs `requires` font
passer un gpt de « boucle locale seulement » à « n'importe où », donc changent
sa classe de sûreté en silence. C'est pourquoi l'en-tête est relu en TEXTE
BRUT avant d'être analysé.

Les cas malformés viennent avant le cas heureux, dans ce fichier comme dans
l'ordre d'écriture : un chargeur se juge sur ce qu'il refuse.

Aucun test ne lit le disque de la machine : les racines sont des répertoires
temporaires, et le répertoire personnel est détourné là où il compte.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from script.todo.assistant import gpt as G  # noqa: E402

# Le corps minimal acceptable : le marqueur de question est obligatoire.
CORPS = "\n<!-- [question] -->\nRéécris : {phrase}\n"

# Un en-tête complet, dont chaque champ est exercé quelque part plus bas.
ENTETE = """---
gpt: 1
name: Comment hygiene - rewrite narrative as mechanism
description: Rewrite each flagged sentence so the code is the subject
requires:
  hosting: lan
  context_window: 8000
  parameters: 12
params:
  temperature: 0.2
  max_tokens: 700
inputs:
  - name: path
    type: repo_path
    required: true
context:
  files:
    - .claude/rules/04-code-conventions.md
---"""


def cles(problemes):
    """Les clés de problème, pour affirmer sans dépendre d'un libellé."""
    return [souci.key for souci in problemes]


class CeQuiEstRefuse(unittest.TestCase):
    """Les formes qu'un analyseur YAML laisse passer sans lever."""

    def test_un_fichier_vide_est_refuse(self):
        gpt, problemes = G.parse("", stem="essai")
        self.assertIsNone(gpt)
        self.assertEqual(cles(problemes), [G.SANS_ENTETE])

    def test_sans_en_tete_est_un_probleme_liste(self):
        gpt, problemes = G.parse("juste un corps\n", stem="essai")
        self.assertIsNone(gpt)
        self.assertEqual(cles(problemes), [G.SANS_ENTETE])

    def test_un_en_tete_non_ferme_est_refuse(self):
        gpt, problemes = G.parse("---\ngpt: 1\n" + CORPS, stem="essai")
        self.assertIsNone(gpt)
        self.assertEqual(cles(problemes), [G.ENTETE_NON_FERMEE])

    def test_un_en_tete_qui_est_une_liste_est_refuse(self):
        """`safe_load` rend une `list` sans lever : le type est donc contrôlé
        avant toute lecture de champ."""
        gpt, problemes = G.parse(
            "---\n- un\n- deux\n---" + CORPS, stem="essai"
        )
        self.assertIsNone(gpt)
        self.assertEqual(cles(problemes), [G.ENTETE_PAS_UN_DICTIONNAIRE])
        self.assertEqual(problemes[0].detail, "list")

    def test_un_en_tete_scalaire_est_refuse(self):
        gpt, problemes = G.parse("---\ndu texte\n---" + CORPS, stem="essai")
        self.assertIsNone(gpt)
        self.assertEqual(problemes[0].detail, "str")

    def test_un_en_tete_indente_par_tabulation_est_un_probleme_liste(self):
        """La tabulation est l'un des deux seuls cas où `safe_load` lève ;
        il ne doit pas remonter en trace."""
        gpt, problemes = G.parse("---\ngpt:\t1\n---" + CORPS, stem="essai")
        self.assertIsNone(gpt)
        self.assertEqual(cles(problemes), [G.ENTETE_ILLISIBLE])

    def test_une_cle_dupliquee_est_signalee_pas_perdue(self):
        """Le cas qui coûte le plus cher : `safe_load` garde la DERNIÈRE, donc
        un second bloc `requires` change la classe de sûreté sans un mot."""
        texte = (
            "---\ngpt: 1\nname: N\ndescription: D\n"
            "requires:\n  hosting: loopback\n"
            "requires:\n  hosting: any\n---" + CORPS
        )
        gpt, problemes = G.parse(texte, stem="essai")
        self.assertIsNone(gpt)
        self.assertEqual(cles(problemes), [G.CLE_REPETEE])
        self.assertEqual(problemes[0].detail, "requires")

    def test_un_nom_absent_est_un_probleme_liste(self):
        texte = "---\ngpt: 1\ndescription: D\n---" + CORPS
        gpt, problemes = G.parse(texte, stem="essai")
        self.assertIsNone(gpt)
        self.assertEqual(cles(problemes), [G.NOM_ABSENT])

    def test_une_description_absente_est_un_probleme_liste(self):
        texte = "---\ngpt: 1\nname: N\n---" + CORPS
        gpt, problemes = G.parse(texte, stem="essai")
        self.assertIsNone(gpt)
        self.assertEqual(cles(problemes), [G.DESCRIPTION_ABSENTE])

    def test_un_schema_absent_est_refuse(self):
        texte = "---\nname: N\ndescription: D\n---" + CORPS
        gpt, problemes = G.parse(texte, stem="essai")
        self.assertIsNone(gpt)
        self.assertEqual(cles(problemes), [G.SCHEMA_ABSENT])

    def test_une_version_de_schema_inconnue_grise_au_lieu_de_deviner(self):
        """Deviner le sens d'un champ inconnu est la façon la plus sûre de
        trahir un gpt : la version trop récente se refuse en le disant."""
        texte = "---\ngpt: 99\nname: N\ndescription: D\n---" + CORPS
        gpt, problemes = G.parse(texte, stem="essai")
        self.assertIsNone(gpt)
        self.assertEqual(cles(problemes), [G.SCHEMA_TROP_RECENT])
        self.assertEqual(problemes[0].detail, "99")

    def test_un_marqueur_question_absent_est_un_probleme_liste(self):
        texte = (
            "---\ngpt: 1\nname: N\ndescription: D\n---\n"
            "<!-- [system] -->\nUne invite, et rien à demander.\n"
        )
        gpt, problemes = G.parse(texte, stem="essai")
        self.assertIsNone(gpt)
        self.assertEqual(cles(problemes), [G.MARQUEUR_QUESTION_ABSENT])

    def test_un_requires_qui_n_est_pas_un_dictionnaire_est_jete(self):
        """Une liste sous `requires` vient d'une indentation fautive. En
        tirer des exigences inventerait une classe de sûreté."""
        texte = (
            "---\ngpt: 1\nname: N\ndescription: D\n"
            "requires:\n  - hosting\n---" + CORPS
        )
        gpt, problemes = G.parse(texte, stem="essai")
        self.assertIsNotNone(gpt)
        self.assertEqual(gpt.requires, {})


class CeQuiEstSignaleSansEtreFatal(unittest.TestCase):
    """Un gpt utilisable peut porter quelque chose à relire."""

    def test_une_cle_inconnue_est_signalee_et_le_gpt_reste(self):
        """Une faute de frappe sur « requires » retirerait toutes les
        exigences en silence, donc la clé inconnue se dit."""
        texte = (
            "---\ngpt: 1\nname: N\ndescription: D\nrequiers: {}\n---" + CORPS
        )
        gpt, problemes = G.parse(texte, stem="essai")
        self.assertIsNotNone(gpt)
        self.assertEqual(cles(problemes), [G.CLE_INCONNUE])
        self.assertEqual(problemes[0].detail, "requiers")
        self.assertFalse(problemes[0].fatal)

    def test_name_fr_dans_le_depot_est_signale(self):
        """Le fichier des traductions est la source unique ; un `name_fr` ici
        en créerait une seconde."""
        texte = (
            "---\ngpt: 1\nname: N\ndescription: D\nname_fr: Nom\n---" + CORPS
        )
        gpt, problemes = G.parse(texte, stem="essai", from_repo=True)
        self.assertIsNotNone(gpt)
        self.assertEqual(cles(problemes), [G.NAME_FR_HORS_PLACE])
        self.assertFalse(problemes[0].fatal)


class HorsDuDepot(unittest.TestCase):
    """Un fichier que personne n'a relu est de la configuration, pas une
    donnée."""

    BASE = "---\ngpt: 1\nname: N\ndescription: D\n"

    def test_un_gpt_hors_du_depot_est_force_a_loopback(self):
        texte = self.BASE + "requires:\n  hosting: any\n---" + CORPS
        gpt, _ = G.parse(texte, stem="essai", from_repo=False)
        self.assertIsNotNone(gpt)
        self.assertEqual(gpt.requires["hosting"], "loopback")

    def test_un_gpt_du_depot_garde_son_hosting(self):
        texte = self.BASE + "requires:\n  hosting: any\n---" + CORPS
        gpt, _ = G.parse(texte, stem="essai", from_repo=True)
        self.assertEqual(gpt.requires["hosting"], "any")

    def test_un_gpt_hors_du_depot_ne_peut_declarer_aucune_commande(self):
        texte = (
            self.BASE
            + "context:\n  commands:\n    - argv: [echo, salut]\n---"
            + CORPS
        )
        gpt, problemes = G.parse(texte, stem="essai", from_repo=False)
        self.assertIsNone(gpt)
        self.assertEqual(
            cles(problemes),
            [G.HORS_DEPOT_SANS_COMMANDE],
        )

    def test_un_gpt_hors_du_depot_garde_son_name_fr(self):
        """Un fichier hors du dépôt ne peut pas ajouter une clé à un fichier
        versionné : l'exception est structurelle, non stylistique."""
        texte = self.BASE + "name_fr: Mon outil\n---" + CORPS
        gpt, problemes = G.parse(texte, stem="essai", from_repo=False)
        self.assertIsNotNone(gpt)
        self.assertEqual(gpt.name_fr, "Mon outil")
        self.assertEqual(problemes, [])


class LeCasHeureux(unittest.TestCase):
    """Ce qu'un gpt bien formé rend, une fois tout le reste écarté."""

    def setUp(self):
        self.gpt, self.problemes = G.parse(
            ENTETE + "\n\n<!-- [system] -->\nTu réécris." + CORPS,
            stem="comment-hygiene",
        )

    def test_un_gpt_bien_forme_ne_porte_aucun_probleme(self):
        self.assertEqual(self.problemes, [])
        self.assertIsNotNone(self.gpt)

    def test_le_radical_du_nom_de_fichier_est_l_identite(self):
        """Il n'y a pas de champ `id` : deux sources de vérité pour un nom
        finissent par diverger."""
        self.assertEqual(self.gpt.stem, "comment-hygiene")

    def test_le_corps_se_coupe_en_systeme_et_question(self):
        self.assertEqual(self.gpt.system, "Tu réécris.")
        self.assertEqual(self.gpt.question, "Réécris : {phrase}")

    def test_les_exigences_et_les_parametres_sont_lus(self):
        self.assertEqual(self.gpt.requires["hosting"], "lan")
        self.assertEqual(self.gpt.requires["context_window"], 8000)
        self.assertEqual(self.gpt.params["temperature"], 0.2)

    def test_une_entree_sans_nom_est_ecartee(self):
        """Elle ne pourrait ni se demander ni se substituer au gabarit."""
        texte = (
            "---\ngpt: 1\nname: N\ndescription: D\n"
            "inputs:\n  - type: repo_path\n  - name: chemin\n---" + CORPS
        )
        gpt, _ = G.parse(texte, stem="essai")
        self.assertEqual([e["name"] for e in gpt.inputs], ["chemin"])


class LesRacines(unittest.TestCase):
    """Deux racines, deux niveaux de confiance, et un recouvrement par nom."""

    BON = "---\ngpt: 1\nname: N\ndescription: D\n---" + CORPS

    def setUp(self):
        self.depot = tempfile.TemporaryDirectory()
        self.maison = tempfile.TemporaryDirectory()
        self.addCleanup(self.depot.cleanup)
        self.addCleanup(self.maison.cleanup)

    def _ecrire(self, dossier, nom, texte):
        chemin = Path(dossier) / nom
        chemin.write_text(texte, encoding="utf-8")
        return chemin

    def test_une_racine_absente_n_est_pas_une_erreur(self):
        """Le répertoire de l'utilisateur n'existe d'ordinaire pas."""
        gpts, problemes = G.load_all(
            roots=[(Path(self.depot.name) / "inexistant", True)]
        )
        self.assertEqual(gpts, [])
        self.assertEqual(problemes, [])

    def test_un_fichier_illisible_ne_cache_pas_les_autres(self):
        self._ecrire(self.depot.name, "bon.md", self.BON)
        self._ecrire(self.depot.name, "casse.md", "---\n- liste\n---" + CORPS)
        gpts, problemes = G.load_all(roots=[(self.depot.name, True)])
        self.assertEqual([g.stem for g in gpts], ["bon"])
        self.assertEqual(cles(problemes), [G.ENTETE_PAS_UN_DICTIONNAIRE])

    def test_une_racine_posterieure_ecrase_par_nom_et_le_dit(self):
        self._ecrire(self.depot.name, "outil.md", self.BON)
        self._ecrire(
            self.maison.name,
            "outil.md",
            "---\ngpt: 1\nname: Autre\ndescription: D\n---" + CORPS,
        )
        gpts, problemes = G.load_all(
            roots=[(self.depot.name, True), (self.maison.name, False)]
        )
        self.assertEqual([g.stem for g in gpts], ["outil"])
        self.assertEqual(gpts[0].name, "Autre")
        self.assertIn(G.ECRASE, cles(problemes))

    def test_un_ecrasement_refuse_laisse_le_gpt_du_depot(self):
        """Le refus d'un fichier hors du dépôt ne doit pas emporter avec lui
        celui que le dépôt livrait."""
        self._ecrire(self.depot.name, "outil.md", self.BON)
        self._ecrire(
            self.maison.name,
            "outil.md",
            "---\ngpt: 1\nname: N\ndescription: D\n"
            "context:\n  commands:\n    - argv: [echo]\n---" + CORPS,
        )
        gpts, problemes = G.load_all(
            roots=[(self.depot.name, True), (self.maison.name, False)]
        )
        self.assertEqual([g.stem for g in gpts], ["outil"])
        self.assertEqual(gpts[0].name, "N")
        self.assertIn(
            G.HORS_DEPOT_SANS_COMMANDE,
            cles(problemes),
        )

    def test_un_nom_de_fichier_base_md_est_refuse(self):
        """`make doc_markdown` ne balaie que les `*.base.md` : un gpt ainsi
        nommé serait réécrit par la chaîne de documentation."""
        self._ecrire(self.depot.name, "outil.base.md", self.BON)
        gpts, problemes = G.load_all(roots=[(self.depot.name, True)])
        self.assertEqual(gpts, [])
        self.assertEqual(cles(problemes), [G.NOM_BASE_MD_REFUSE])

    def test_seuls_les_fichiers_md_sont_lus(self):
        self._ecrire(self.depot.name, "outil.md", self.BON)
        self._ecrire(self.depot.name, "notes.txt", "rien")
        self._ecrire(self.depot.name, "README", "rien")
        gpts, _ = G.load_all(roots=[(self.depot.name, True)])
        self.assertEqual([g.stem for g in gpts], ["outil"])

    def test_le_catalogue_est_trie_par_radical(self):
        for nom in ("zeta.md", "alpha.md", "mu.md"):
            self._ecrire(self.depot.name, nom, self.BON)
        gpts, _ = G.load_all(roots=[(self.depot.name, True)])
        self.assertEqual([g.stem for g in gpts], ["alpha", "mu", "zeta"])

    def test_une_lecture_qui_leve_est_un_probleme_liste(self):
        self._ecrire(self.depot.name, "outil.md", self.BON)

        def refuser(chemin):
            raise OSError("permission refusée")

        gpts, problemes = G.load_all(
            roots=[(self.depot.name, True)], read=refuser
        )
        self.assertEqual(gpts, [])
        self.assertEqual(cles(problemes), [G.FICHIER_ILLISIBLE])

    def test_le_catalogue_s_ouvre_sans_pyyaml(self):
        """Le catalogue est un supplément ; la question libre marche sans
        lui, donc son absence se dit et ne lève pas."""
        with patch.object(G, "_yaml_disponible", return_value=False):
            gpts, problemes = G.load_all(roots=[(self.depot.name, True)])
        self.assertEqual(gpts, [])
        self.assertEqual(
            cles(problemes),
            [G.PYYAML_ABSENT],
        )

    def test_le_repertoire_personnel_est_detournable(self):
        """Sans ce détournement, un test lirait les gpts de la machine qui le
        lance, et son résultat dépendrait de qui l'exécute."""
        racines = G.default_roots(home=self.maison.name)
        chemins = [str(chemin) for chemin, _ in racines]
        self.assertTrue(chemins)
        self.assertTrue(chemins[-1].startswith(self.maison.name))
        self.assertEqual([relu for _, relu in racines], [True, False])


if __name__ == "__main__":
    unittest.main()
