#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les profils de VM : un nom qu'on reconnaît, et ce qu'il tient VRAIMENT.

CE QUE CE MODULE EXISTE POUR EMPÊCHER. Le registre s'interdit un « nom
rassurant » — il a retiré une posture qui déclarait une liste blanche sans
liste, parce qu'elle « donnait l'assurance du contraire ». Un profil qui
afficherait « VM Connecté » sans dire que rien n'applique sa politique
vendrait exactement cette assurance-là, un étage plus haut.

`rules.unenforced()` est le mécanisme que le dépôt a bâti contre ça, et rien
ne le lisait. Ces épreuves tiennent qu'un profil le LIT et le DIT.

Ni réseau, ni VM : tout est pur.
"""

import os
import sys
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

from script.posture import registry as R  # noqa: E402
from script.posture import rules  # noqa: E402
from script.todo import todo_i18n  # noqa: E402
from script.todo import vm_profiles as V  # noqa: E402


class CasDeProfil(unittest.TestCase):
    """La langue est ÉPINGLÉE : les clés SONT les chaînes anglaises."""

    def setUp(self):
        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = "en"


class TestLesQuatreNomsDemandes(CasDeProfil):
    ATTENDUS = {
        "Sandbox": "open",
        "VM Connecté": "connected",
        "VM paranoid": "paranoid",
        "local-webui": "local-only",
    }

    def test_the_four_labels_exist(self):
        self.assertEqual(set(self.ATTENDUS), {p.label for p in V.profiles()})

    def test_each_label_names_its_own_posture(self):
        for libelle, posture in self.ATTENDUS.items():
            with self.subTest(libelle=libelle):
                self.assertEqual(posture, V.by_label(libelle).posture)

    def test_every_posture_of_the_registry_has_a_profile(self):
        """Une posture sans profil disparaîtrait du sélecteur, et deviendrait
        indéployable sans qu'on sache pourquoi."""
        self.assertEqual(
            set(R.posture_names()), {p.posture for p in V.profiles()}
        )

    def test_no_profile_names_a_posture_the_registry_does_not_have(self):
        """« restricted » a été retiré du registre EXPRÈS : un profil qui le
        nommerait le ferait revenir par la porte de l'écran."""
        for profil in V.profiles():
            with self.subTest(profil=profil.label):
                self.assertIsNotNone(R.get_posture(profil.posture))

    def test_the_order_goes_from_the_freest_to_the_most_constrained(self):
        """« On descend vers la contrainte, on n'y tombe pas par défaut. »"""
        self.assertEqual(
            list(R.posture_names()), [p.posture for p in V.profiles()]
        )

    def test_the_first_one_is_the_registry_default(self):
        self.assertEqual(R.DEFAULT_POSTURE, V.profiles()[0].posture)


class TestLeQuatriemeNEstPasUnePosture(CasDeProfil):
    """Le registre le dit : « c'est la moitié « réseau » de ce qu'on
    appelait « local-webui » ; l'autre moitié est un profil d'installation,
    et les séparer est ce qui permet de servir autre chose sur la même
    posture »."""

    def test_no_posture_carries_that_name(self):
        self.assertIsNone(R.get_posture("local-webui"))

    def test_the_profile_says_which_half_is_missing(self):
        """Le taire laisserait croire qu'un profil nommé « webui » sert une
        interface."""
        profil = V.by_label("local-webui")
        self.assertTrue(profil.install_half)

    def test_the_three_others_are_whole(self):
        """Contrôle positif : déclarer une moitié manquante partout ne
        dirait plus rien."""
        for libelle in ("Sandbox", "VM Connecté", "VM paranoid"):
            with self.subTest(libelle=libelle):
                self.assertEqual("", V.by_label(libelle).install_half)


class TestCeQueChaqueProfilApplique(CasDeProfil):
    def test_the_free_one_says_nothing_is_confined(self):
        """Et ce n'est pas un aveu : il n'y a pas de politique à tenir."""
        phrase = V.enforcement("open")
        self.assertIn("Nothing is confined", phrase)

    def test_the_one_nothing_applies_says_INTENTION_ONLY(self):
        """LE PIRE DES DEUX MONDES, et ce que ce module existe pour
        montrer : une politique déclarée sans mécanisme se comporte comme
        l'absence de politique, en donnant l'assurance du contraire."""
        phrase = V.enforcement("connected")
        self.assertIn("INTENTION ONLY", phrase)
        self.assertIn("free egress", phrase)

    def test_the_two_that_install_rules_say_so(self):
        for nom in ("paranoid", "local-only"):
            with self.subTest(posture=nom):
                self.assertIn("Rules are written", V.enforcement(nom))

    def test_the_three_answers_do_not_collide(self):
        """Trois états, et les confondre est tout le défaut."""
        phrases = {V.enforcement(n) for n in R.posture_names()}
        self.assertEqual(3, len(phrases), phrases)

    def test_an_unknown_posture_deploys_nothing_and_says_it(self):
        self.assertIn("Unknown posture", V.enforcement("jamais-vue"))

    def test_what_it_says_agrees_with_what_the_renderer_does(self):
        """L'ACCORD qui empêche la phrase de dériver : « des règles sont
        posées » exactement là où le rendu accepte d'en produire."""
        for nom in R.posture_names():
            with self.subTest(posture=nom):
                posture = R.get_posture(nom)
                dit_regles = "Rules are written" in V.enforcement(nom)
                self.assertEqual(rules.wants_rules(posture), dit_regles)


class TestLesEcartsSontDitsEtNonTus(CasDeProfil):
    def test_every_token_of_the_vocabulary_has_a_sentence(self):
        self.assertTrue(rules.UNENFORCED_TOKENS, "vocabulaire vidé")
        for jeton in rules.UNENFORCED_TOKENS:
            with self.subTest(jeton=jeton):
                self.assertTrue(V.gap_sentence(jeton).strip())

    def test_the_table_has_no_stale_entry(self):
        self.assertEqual(
            set(), set(V.GAP_SENTENCES) - set(rules.UNENFORCED_TOKENS)
        )

    def test_an_unknown_token_raises_rather_than_prints_nothing(self):
        """Une ligne vide se lirait comme « rien à signaler » — le
        contraire d'un écart."""
        with self.assertRaises(KeyError):
            V.gap_sentence("jeton-jamais-declare")

    def test_the_posture_nothing_applies_has_a_gap(self):
        self.assertIn(rules.NO_RENDERING, V.gaps("connected"))

    def test_the_bounded_allowlist_has_the_two_of_its_mechanism(self):
        ecarts = V.gaps("paranoid")
        self.assertIn(rules.RELOAD_FAILURE_UNSEEN, ecarts)
        self.assertIn(rules.CONTAINERS_UNPROVEN, ecarts)

    def test_the_free_one_has_none(self):
        """Contrôle positif : tout déclarer en écart ne dirait plus rien."""
        self.assertEqual((), V.gaps("open"))

    def test_the_gaps_come_from_the_posture_package(self):
        """Une recopie ici divergerait au premier écart comblé."""
        for nom in R.posture_names():
            with self.subTest(posture=nom):
                self.assertEqual(
                    rules.unenforced(R.get_posture(nom)), V.gaps(nom)
                )


class TestCeQueLeSelecteurOffre(CasDeProfil):
    def test_the_value_stays_the_posture_name(self):
        """C'est lui que la spec porte. Un libellé stocké obligerait à le
        retraduire, et une spec relue dans une autre langue ne se
        retrouverait plus."""
        for libelle, valeur in V.choices():
            with self.subTest(libelle=libelle):
                self.assertIn(valeur, R.posture_names())

    def test_the_label_is_what_a_human_reads(self):
        libelles = [libelle for libelle, _v in V.choices()]
        self.assertIn("Sandbox", libelles)
        self.assertNotIn("open", libelles)

    def test_the_round_trip_finds_the_label_again(self):
        """Une spec relue porte un nom de posture : l'écran doit retrouver
        sous quel libellé elle a été choisie."""
        for libelle, valeur in V.choices():
            with self.subTest(libelle=libelle):
                self.assertEqual(libelle, V.label_of(valeur))

    def test_a_posture_without_a_profile_keeps_its_raw_name(self):
        """Elle doit rester choisissable et lisible, pas disparaître."""
        self.assertEqual("jamais-vue", V.label_of("jamais-vue"))

    def test_nothing_is_an_empty_label_and_not_a_crash(self):
        self.assertEqual("", V.label_of(""))
        self.assertEqual("", V.label_of(None))

    def test_an_unknown_label_is_none_and_not_a_guess(self):
        self.assertIsNone(V.by_label("Jamais vu"))


class TestQuiDemandeUnCarnetDAdresses(CasDeProfil):
    """Un carnet vide fait REFUSER le déploiement, et le dire devant
    l'écran vaut mieux que de le découvrir sur la machine."""

    def test_only_the_bounded_allowlist_asks_for_one(self):
        demandeurs = [
            nom for nom in R.posture_names() if V.bounded_addresses(nom)
        ]
        self.assertEqual(["paranoid"], demandeurs)

    def test_the_cut_egress_asks_for_none(self):
        """Elle ne joint rien : lui demander des adresses serait absurde."""
        self.assertFalse(V.bounded_addresses("local-only"))


class TestLeModuleNAfficheRien(CasDeProfil):
    """Il rend des phrases ; c'est l'écran qui les écrit."""

    def test_it_neither_prints_nor_prompts(self):
        import ast

        chemin = os.path.join(RACINE, "script", "todo", "vm_profiles.py")
        with open(chemin, encoding="utf-8") as fichier:
            arbre = ast.parse(fichier.read())
        noms = [
            n.func.id
            for n in ast.walk(arbre)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        ]
        self.assertTrue(noms, "aucun appel lu : rien n'est prouvé")
        for interdit in ("print", "input"):
            self.assertNotIn(interdit, noms)

    def test_it_does_not_reimplement_the_posture_package(self):
        """Les deux prédicats viennent de là-bas : recopiés, ils
        divergeraient du rendu qu'ils décrivent."""
        chemin = os.path.join(RACINE, "script", "todo", "vm_profiles.py")
        with open(chemin, encoding="utf-8") as fichier:
            source = fichier.read()
        self.assertIn("rules.wants_rules(", source)
        self.assertIn("rules.unenforced(", source)
        self.assertNotIn("destinations_bounded and", source)


class TestLaLigneQuUnEcranEcrit(CasDeProfil):
    """La COMPOSITION vit ici, pas dans le formulaire.

    Celui-ci est du Textual, qu'aucune épreuve unitaire ne pilote : ce qui
    y reste est une affectation. Tout ce qui décide de la ligne se relit
    donc sans terminal.
    """

    def test_it_always_says_what_is_enforced(self):
        for nom in R.posture_names():
            with self.subTest(posture=nom):
                self.assertIn(V.enforcement(nom), V.screen_line(nom))

    def test_the_gaps_follow_on_the_same_line(self):
        """Un écart lu séparément de ce qu'il nuance se prend pour une
        panne."""
        ligne = V.screen_line("paranoid")
        self.assertIn("Rules are written", ligne)
        self.assertIn("⚠", ligne)

    def test_a_posture_without_gaps_carries_no_warning_mark(self):
        """Une marque permanente ne marque plus rien."""
        for nom in ("open", "local-only"):
            with self.subTest(posture=nom):
                self.assertNotIn("⚠", V.screen_line(nom))

    def test_every_gap_of_the_posture_appears(self):
        for nom in R.posture_names():
            for jeton in V.gaps(nom):
                with self.subTest(posture=nom, jeton=jeton):
                    self.assertIn(V.gap_sentence(jeton), V.screen_line(nom))

    def test_the_line_that_matters_most_says_it_plainly(self):
        """« VM Connecté » est le seul profil dont le nom rassure et dont
        rien ne tient la promesse."""
        self.assertIn("INTENTION ONLY", V.screen_line("connected"))

    def test_it_reads_in_both_languages(self):
        """Une phrase non traduite passerait inaperçue en anglais et
        laisserait un écran mi-français mi-anglais."""
        for langue in ("fr", "en"):
            todo_i18n._current_lang = langue
            for nom in R.posture_names():
                with self.subTest(langue=langue, posture=nom):
                    self.assertTrue(V.screen_line(nom).strip())

    def test_every_posture_reads_differently_in_the_two_languages(self):
        """Contrôle positif, POSTURE PAR POSTURE. Une clé sans traduction
        rend la clé : comparer une seule posture laisserait passer une
        phrase non traduite ailleurs, puisque l'autre moitié de la ligne
        suffirait à faire différer le tout."""
        for nom in R.posture_names():
            with self.subTest(posture=nom):
                todo_i18n._current_lang = "fr"
                francais = V.screen_line(nom)
                todo_i18n._current_lang = "en"
                anglais = V.screen_line(nom)
                self.assertNotEqual(francais, anglais, nom)

    def test_every_gap_sentence_is_translated(self):
        """Elles sont la moitié qu'un écran lit en dernier, et une seule
        non traduite laisserait un écran mi-français mi-anglais."""
        for jeton in rules.UNENFORCED_TOKENS:
            with self.subTest(jeton=jeton):
                todo_i18n._current_lang = "fr"
                francais = V.gap_sentence(jeton)
                todo_i18n._current_lang = "en"
                self.assertNotEqual(francais, V.gap_sentence(jeton), jeton)

    def test_every_enforcement_sentence_is_translated(self):
        for nom in R.posture_names():
            with self.subTest(posture=nom):
                todo_i18n._current_lang = "fr"
                francais = V.enforcement(nom)
                todo_i18n._current_lang = "en"
                self.assertNotEqual(francais, V.enforcement(nom), nom)


class TestLeFormulaireOffreLesLibelles(CasDeProfil):
    """Le sélecteur montrait les noms BRUTS du registre."""

    @staticmethod
    def source(nom):
        chemin = os.path.join(RACINE, "script", "todo", nom)
        with open(chemin, encoding="utf-8") as fichier:
            return fichier.read()

    def test_the_context_carries_the_labelled_choices(self):
        self.assertIn("vm_profiles.choices()", self.source("qemu_deploy.py"))

    def test_the_context_carries_what_each_one_enforces(self):
        """Les clés EXACTES, guillemets compris : « posture_gaps_retire »
        contient « posture_gaps », et une recherche de sous-chaîne
        laisserait passer une clé renommée."""
        source = self.source("qemu_deploy.py")
        self.assertIn('"posture_enforcement": {', source)
        self.assertIn('"posture_gaps": {', source)

    def test_the_form_reads_those_very_keys(self):
        """Une clé écrite d'un côté et lue de l'autre sous un autre nom
        laisserait la ligne vide, sans rien dire."""
        source = self.source("qemu_deploy_form.py")
        self.assertIn('ctx.get("posture_enforcement")', source)
        self.assertIn('ctx.get("posture_gaps")', source)

    def test_the_form_uses_them(self):
        source = self.source("qemu_deploy_form.py")
        self.assertIn('ctx.get("posture_choices")', source)

    def test_the_form_actually_yields_the_effect_line(self):
        """Le NOM du widget suffit à apparaître dans le code qui l'écrit :
        c'est le `yield` qui le fait exister à l'écran."""
        source = self.source("qemu_deploy_form.py")
        self.assertIn('yield Static("", id="t_posture_effet"', source)

    def test_the_form_refreshes_it_when_the_choice_changes(self):
        """Écrite une fois au montage, elle décrirait la posture de départ
        quel que soit le choix — le pire message possible ici."""
        source = self.source("qemu_deploy_form.py")
        self.assertIn('if wid == "f_posture":', source)
        self.assertIn("self._sync_posture()", source)

    def test_the_form_keeps_a_fallback_to_the_raw_names(self):
        """Un contexte plus ancien qui ne porte pas les choix doit laisser
        l'écran utilisable, pas vide."""
        source = self.source("qemu_deploy_form.py")
        self.assertIn(
            'or [(nom, nom) for nom in ctx.get("postures", ())]', source
        )

    def test_the_spec_still_carries_the_posture_name(self):
        """Le libellé est de l'affichage : le stocker obligerait à le
        retraduire, et une spec relue ailleurs ne se retrouverait plus."""
        source = self.source("qemu_deploy_form.py")
        self.assertIn(
            '"posture": self.query_one("#f_posture", Select).value', source
        )


if __name__ == "__main__":
    unittest.main()
