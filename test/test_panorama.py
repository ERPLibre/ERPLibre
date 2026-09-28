#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le panorama, et surtout sa date.

Un catalogue de modèles périme en semaines. Ce que ces tests gardent n'est donc
pas l'exactitude d'une taille — aucun test ne peut la vérifier hors ligne —
mais le fait que le relevé DISE son âge et qu'il le dise juste aux bornes.

AUCUN test d'ici n'échoue par le seul passage du temps. Les seuils se
vérifient avec des dates INJECTÉES, et la seule assertion sur le calendrier
réel est que le relevé ne soit pas daté du futur. Un banc qui rougit sans
qu'une ligne de code ait bougé use la confiance qu'on lui porte, et finit
désarmé.
"""

import re
import unittest
from datetime import date, timedelta
from pathlib import Path

from script.todo.assistant import panorama


class LaDateDuReleve(unittest.TestCase):
    def test_le_releve_n_est_pas_date_du_futur(self):
        """La seule assertion sur le calendrier réel, et elle est sûre.

        Un relevé daté de demain rendrait un âge négatif et afficherait
        « frais » pour toujours.
        """
        self.assertLessEqual(panorama.DATE_RELEVE, date.today())

    def test_l_age_se_compte_depuis_la_date_du_releve(self):
        for jours in (0, 1, 17, 365):
            with self.subTest(jours=jours):
                self.assertEqual(
                    jours,
                    panorama.age_jours(
                        panorama.DATE_RELEVE + timedelta(days=jours)
                    ),
                )

    def test_les_seuils_basculent_au_bon_jour(self):
        """Aux BORNES, pas autour : un seuil qui glisse d'un jour ne se voit
        jamais à l'usage et fausse pourtant le verdict pendant 24 heures."""
        cas = [
            (0, panorama.FRAIS),
            (panorama.AGE_TIEDE, panorama.FRAIS),
            (panorama.AGE_TIEDE + 1, panorama.TIEDE),
            (panorama.AGE_FROID, panorama.TIEDE),
            (panorama.AGE_FROID + 1, panorama.FROID),
            (10_000, panorama.FROID),
        ]
        for jours, attendu in cas:
            with self.subTest(jours=jours):
                self.assertEqual(
                    attendu,
                    panorama.fraicheur(
                        panorama.DATE_RELEVE + timedelta(days=jours)
                    ),
                )

    def test_les_seuils_sont_ordonnes(self):
        self.assertLess(panorama.AGE_TIEDE, panorama.AGE_FROID)

    def test_les_trois_verdicts_sont_des_cles_declarees(self):
        """Le module DÉSIGNE une traduction, il ne traduit pas."""
        from script.todo.todo_i18n import TRANSLATIONS

        for verdict in (panorama.FRAIS, panorama.TIEDE, panorama.FROID):
            with self.subTest(verdict=verdict):
                self.assertIn(verdict, TRANSLATIONS)

    def test_le_module_n_appelle_pas_l_horloge_de_lui_meme(self):
        """Le jour courant est un ARGUMENT partout où il compte.

        Une horloge appelée au fond du module rendrait les seuils intestables
        et ferait dépendre le menu de la date de qui le lance.
        """
        import inspect

        source = inspect.getsource(panorama.fraicheur)
        self.assertNotIn("today()", source)


class LesDeuxTables(unittest.TestCase):
    def test_les_moteurs_existent_et_sont_cles_par_leur_cle(self):
        self.assertTrue(panorama.MOTEURS)
        for cle, moteur in panorama.MOTEURS.items():
            with self.subTest(moteur=cle):
                self.assertEqual(cle, moteur.cle)

    def test_les_modeles_existent_et_sont_cles_par_leur_cle(self):
        self.assertTrue(panorama.MODELES)
        for cle, modele in panorama.MODELES.items():
            with self.subTest(modele=cle):
                self.assertEqual(cle, modele.cle)

    def test_aucune_colonne_neutre_n_est_vide(self):
        """Une case vide dans une fiche ne renseigne pas, elle inquiète."""
        for cle, moteur in panorama.MOTEURS.items():
            for colonne in panorama.COLONNES_MOTEUR:
                with self.subTest(moteur=cle, colonne=colonne):
                    self.assertTrue(str(getattr(moteur, colonne)).strip())
        for cle, modele in panorama.MODELES.items():
            for colonne in panorama.COLONNES_MODELE:
                with self.subTest(modele=cle, colonne=colonne):
                    self.assertTrue(str(getattr(modele, colonne)).strip())

    def test_chaque_prose_porte_les_deux_langues(self):
        """Une moitié de langue manquante s'affiche en clé brute au lecteur."""
        paires = [
            (panorama.MOTEURS, ("force", "faiblesse")),
            (panorama.MODELES, ("forces", "faiblesses")),
        ]
        for table, champs in paires:
            for cle, ligne in table.items():
                for champ in champs:
                    valeur = getattr(ligne, champ)
                    with self.subTest(ligne=cle, champ=champ):
                        self.assertEqual({"fr", "en"}, set(valeur))
                        self.assertTrue(valeur["fr"].strip())
                        self.assertTrue(valeur["en"].strip())

    def test_une_note_absente_est_vide_dans_les_deux_langues(self):
        """Rien à signaler se dit dans les deux langues ou dans aucune."""
        for cle, modele in panorama.MODELES.items():
            with self.subTest(modele=cle):
                self.assertEqual({"fr", "en"}, set(modele.note))
                vides = [not modele.note[l].strip() for l in ("fr", "en")]
                self.assertEqual(vides[0], vides[1], modele.note)

    def test_un_moteur_decrit_n_est_pas_aussi_dit_non_releve(self):
        for nom in panorama.NON_RELEVES:
            with self.subTest(moteur=nom):
                self.assertNotIn(nom.lower(), panorama.MOTEURS)

    def test_le_tableau_rend_une_ligne_par_entree(self):
        lignes = panorama.tableau(
            panorama.MOTEURS.values(), panorama.COLONNES_MOTEUR
        )
        self.assertEqual(len(panorama.MOTEURS), len(lignes))
        for ligne in lignes:
            self.assertEqual(len(panorama.COLONNES_MOTEUR), len(ligne))
            for cellule in ligne:
                self.assertIsInstance(cellule, str)


class CeQueLesFichesPromettent(unittest.TestCase):
    """Les colonnes tiennent dans un terminal, et disent ce qu'elles savent."""

    LARGEURS = {
        "parametres": 60,
        "architecture": 70,
        "contexte": 60,
        "licence": 60,
        "poids": 70,
        "kv_par_jeton": 70,
        "moteurs": 55,
        "codage": 70,
    }

    def test_les_colonnes_tiennent_dans_une_fiche(self):
        """Une valeur trop longue déborde de la largeur d'un terminal et
        casse l'alignement de toute la fiche."""
        for cle, modele in panorama.MODELES.items():
            for champ, largeur in self.LARGEURS.items():
                valeur = getattr(modele, champ)
                with self.subTest(modele=cle, champ=champ):
                    self.assertLessEqual(len(valeur), largeur, valeur)

    def test_une_phrase_de_prose_reste_une_phrase(self):
        for table, champs in [
            (panorama.MOTEURS, ("force", "faiblesse")),
            (panorama.MODELES, ("forces", "faiblesses")),
        ]:
            for cle, ligne in table.items():
                for champ in champs:
                    for langue, texte in getattr(ligne, champ).items():
                        with self.subTest(ligne=cle, champ=champ, l=langue):
                            self.assertLessEqual(len(texte), 220, texte)

    # Ce qui a le droit de paraître dans une colonne sans langue : des unités,
    # des formats, des sigles, des noms propres. Une LISTE BLANCHE et non une
    # liste noire — une liste de mots français interdits est forcément
    # incomplète, et la première version de ce test laissait passer
    # « couches », « actifs » et « non calculé » en croyant vérifier.
    LEXIQUE = {
        w.lower()
        for w in """
        Go Gio Kio Mio bf16 FP8 FP16 INT2 INT3 INT4 INT6 NVFP NVFP4 MXFP MXFP4
        GGUF safetensors MLA GQA MoE YaRN config gated dense bits multimodal
        calc inf act via backends health readyz api version int avx custom
        other Open Model License Licence Apache MIT Modified community
        Linux macOS Windows CPU CUDA Vulkan Metal SYCL ROCm Apple Silicon ARM
        Small Instruct Mini Super Nano Linear Flash Next Code Coder Max
        Apertus Qwen Kimi DeepSeek MiniMax GLM Mistral Nemotron NVIDIA Alibaba
        Moonshot Swiss Initiative EPFL ETH CSCS OpenAI Zhipu Devstral
        vLLM llama cpp Ollama LocalAI MLX SGLang mlx lm gpt oss zai org
        Mamba DeltaNet KDA MoonViT IQ UD XXS XS
        Terminal Bench SWE HumanEval MBPP LiveCodeBench DeepSWE ATLAS
        USAGE POLICY datacentre indépendant auto déclaré publié aucun
        couches jeton
        """.split()
    }

    def test_une_colonne_dite_neutre_ne_porte_aucune_langue(self):
        """Le postulat de la conception, et il se viole tout seul.

        Les colonnes de chiffres ne sont pas traduites parce qu'un nombre de
        gigaoctets se lit pareil partout. Mais « 80 couches », « 18 G actifs »
        ou « non calculé » y glissent du français, qui s'affiche tel quel au
        lecteur anglophone — et c'est arrivé quatorze fois à la première
        écriture.

        Le contrôle est une liste BLANCHE : tout mot d'au moins trois lettres
        doit être une unité, un format, un sigle ou un nom propre. Un mot
        nouveau fait échouer le test, ce qui force à trancher — l'ajouter au
        lexique s'il est vraiment sans langue, ou l'écrire autrement. Une
        arithmétique dit d'ailleurs mieux que des mots : « 2·80·8·128·2 »
        remplace « 80 couches × 8 têtes KV » et se lit partout.
        """
        mots = re.compile(r"[A-Za-zÀ-ÿ]{3,}")
        for table, colonnes in [
            (panorama.MOTEURS, panorama.COLONNES_MOTEUR),
            (panorama.MODELES, panorama.COLONNES_MODELE),
        ]:
            for cle, ligne in table.items():
                for colonne in colonnes:
                    valeur = str(getattr(ligne, colonne))
                    for mot in mots.findall(valeur):
                        with self.subTest(ligne=cle, colonne=colonne, mot=mot):
                            self.assertIn(
                                mot.lower(),
                                self.LEXIQUE,
                                f"mot hors lexique dans une colonne neutre :"
                                f" {mot!r} dans {valeur!r}",
                            )

    def test_un_chiffre_absent_se_dit_plutot_que_de_se_deviner(self):
        """Le catalogue admet ce qu'il ignore.

        « non calculé » et « non relevé » sont des réponses ; une case
        inventée n'en est pas une, et c'est elle qui se propage.
        """
        aveux = ("non calculé", "non relevé", "aucun publié")
        avoue = [
            m.cle
            for m in panorama.MODELES.values()
            if any(a in m.kv_par_jeton or a in m.codage for a in aveux)
        ]
        self.assertTrue(
            avoue, "aucun modèle n'admet de trou : suspect sur 24 entrées"
        )


class LaDocumentationNeDerivePas(unittest.TestCase):
    """Les tableaux du guide sont RÉGÉNÉRÉS, jamais recopiés.

    Un tableau de chiffres recopié à la main s'écarte de la table qui fait
    autorité, et c'est dans une documentation que l'écart se voit le moins :
    personne ne relit une colonne de gigaoctets pour vérifier qu'elle dit
    encore vrai. Ce test régénère et compare.
    """

    GUIDE = Path(__file__).resolve().parents[1] / "doc" / "LLM_OUVERTS.base.md"

    def _entre_marqueurs(self, texte, nom):
        ouvre, ferme = f"<!-- {nom} -->", f"<!-- /{nom} -->"
        self.assertIn(ouvre, texte, f"marqueur {nom} absent du guide")
        self.assertIn(ferme, texte, f"marqueur /{nom} absent du guide")
        debut = texte.index(ouvre) + len(ouvre)
        return texte[debut : texte.index(ferme)].strip()

    def test_les_quatre_tableaux_sont_ceux_du_module(self):
        if not self.GUIDE.exists():
            self.skipTest("le guide n'est pas encore écrit")
        texte = self.GUIDE.read_text(encoding="utf-8")
        attendus = {
            "PANORAMA:moteurs:fr": panorama.markdown(
                panorama.MOTEURS.values(), panorama.COLONNES_MOTEUR, "fr"
            ),
            "PANORAMA:moteurs:en": panorama.markdown(
                panorama.MOTEURS.values(), panorama.COLONNES_MOTEUR, "en"
            ),
            "PANORAMA:modeles:fr": panorama.markdown(
                panorama.MODELES.values(), panorama.COLONNES_MODELE, "fr"
            ),
            "PANORAMA:modeles:en": panorama.markdown(
                panorama.MODELES.values(), panorama.COLONNES_MODELE, "en"
            ),
        }
        for nom, attendu in attendus.items():
            with self.subTest(tableau=nom):
                self.assertEqual(
                    attendu,
                    self._entre_marqueurs(texte, nom),
                    f"{nom} a dérivé : régénérer depuis panorama.markdown()",
                )

    def test_le_guide_porte_la_date_du_releve(self):
        """Un lecteur doit pouvoir juger l'âge sans lancer le CLI."""
        if not self.GUIDE.exists():
            self.skipTest("le guide n'est pas encore écrit")
        texte = self.GUIDE.read_text(encoding="utf-8")
        self.assertIn(panorama.DATE_RELEVE.isoformat(), texte)


if __name__ == "__main__":
    unittest.main()
