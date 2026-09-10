#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'agrégat d'une transcription : ce qui s'additionne, et ce qui ne peut pas.

Deux fautes d'arithmétique sont possibles ici, et elles mentiraient sans rien
casser — c'est pour ça que ces tests existent plutôt que pour vérifier des
additions.

**Additionner les `cost-state`.** Une transcription en porte plusieurs, non
monotones : une compaction remet le compteur à zéro. Sur une transcription
réelle mesurée, la durée d'horloge grandit d'un segment au suivant pendant que
les lignes de code ajoutées diminuent — donc les champs ne se composent pas,
et une somme donnerait un coût inventé. Le dernier segment est retenu, et
`segments` dit combien il y en a eu.

**Lever sur une ligne tronquée.** Une session écrit sa transcription pendant
qu'on la lit, donc la dernière ligne est régulièrement incomplète. Un agrégat
qui lèverait là rendrait l'écran noir sur la session la plus intéressante,
celle qui travaille.

Les fixtures reprennent la forme d'une vraie transcription — les noms de champ
viennent de là, pas d'une supposition. Un test en lit une en entier quand la
machine en porte une, et se saute sinon : une machine d'intégration n'a pas de
sessions Claude Code.
"""

import json
import os
import tempfile
import unittest

from script.todo.assistant.agents import statistiques as st


def _assistant(entree=0, sortie=0, lu=0, cree=0, reflexion=0):
    """Un message d'assistant, dans la forme que porte une transcription."""
    usage = {
        "input_tokens": entree,
        "output_tokens": sortie,
        "cache_read_input_tokens": lu,
        "cache_creation_input_tokens": cree,
        "output_tokens_details": {"thinking_tokens": reflexion},
    }
    return {"type": "assistant", "message": {"usage": usage}}


def _cout(dollars, horloge=0, api=0, outils=0, plus=0, moins=0, modeles=None):
    return {
        "type": "cost-state",
        "totalCostUSD": dollars,
        "totalDuration": horloge,
        "totalAPIDuration": api,
        "totalToolDuration": outils,
        "totalLinesAdded": plus,
        "totalLinesRemoved": moins,
        "modelUsage": modeles if modeles is not None else {},
    }


class TestLesJetonsSAdditionnent(unittest.TestCase):
    def test_two_turns_add_up(self):
        a = st.Agregat()
        a = st.replier(a, _assistant(entree=10, sortie=100, lu=500, cree=20))
        a = st.replier(a, _assistant(entree=2, sortie=50, lu=700, cree=5))
        self.assertEqual(a.tours, 2)
        self.assertEqual(a.entree, 12)
        self.assertEqual(a.sortie, 150)
        self.assertEqual(a.cache_lu, 1200)
        self.assertEqual(a.cache_cree, 25)
        self.assertEqual(a.total_jetons, 12 + 150 + 1200 + 25)

    def test_thinking_tokens_are_kept_apart(self):
        """Ils sont DANS la sortie ; les compter deux fois gonflerait le total."""
        a = st.replier(st.Agregat(), _assistant(sortie=100, reflexion=30))
        self.assertEqual(a.sortie, 100)
        self.assertEqual(a.reflexion, 30)

    def test_a_missing_usage_field_is_zero(self):
        a = st.replier(
            st.Agregat(), {"type": "assistant", "message": {"usage": {}}}
        )
        self.assertEqual(a.tours, 1)
        self.assertEqual(a.total_jetons, 0)

    def test_a_null_field_does_not_raise(self):
        usage = {"input_tokens": None, "output_tokens": 5}
        a = st.replier(
            st.Agregat(), {"type": "assistant", "message": {"usage": usage}}
        )
        self.assertEqual(a.entree, 0)
        self.assertEqual(a.sortie, 5)

    def test_a_boolean_is_not_a_count(self):
        """`True` est un entier en Python : le laisser passer compterait 1."""
        usage = {"input_tokens": True}
        a = st.replier(
            st.Agregat(), {"type": "assistant", "message": {"usage": usage}}
        )
        self.assertEqual(a.entree, 0)


class TestLeCoutNeSAdditionnePas(unittest.TestCase):
    def test_the_last_segment_wins(self):
        """Trois segments, dont un remis à zéro : le dernier est l'état."""
        a = st.Agregat()
        a = st.replier(a, _cout(115.89, horloge=91_000, plus=8723))
        a = st.replier(a, _cout(0.0))
        a = st.replier(a, _cout(120.85, horloge=159_000, plus=2446))
        self.assertAlmostEqual(a.cout, 120.85)
        self.assertEqual(a.duree_horloge, 159_000)
        self.assertEqual(a.lignes_ajoutees, 2446)

    def test_the_segments_are_counted(self):
        """Le compte dit à l'écran que ce chiffre n'est qu'un segment."""
        a = st.Agregat()
        for _ in range(3):
            a = st.replier(a, _cout(1.0))
        self.assertEqual(a.segments, 3)

    def test_the_models_come_from_the_last_segment_only(self):
        a = st.Agregat()
        a = st.replier(a, _cout(1.0, modeles={"un-modele": {"costUSD": 1.0}}))
        a = st.replier(a, _cout(2.0, modeles={"autre-modele": {"costUSD": 2}}))
        self.assertEqual(list(a.par_modele), ["autre-modele"])

    def test_a_cost_state_is_not_a_turn(self):
        """Il rapporte des totaux, il n'est pas un échange."""
        a = st.replier(st.Agregat(), _cout(1.0))
        self.assertEqual(a.tours, 0)


class TestLeContexte(unittest.TestCase):
    def test_the_series_follows_the_prompt_size(self):
        a = st.Agregat()
        a = st.replier(a, _assistant(entree=2, lu=1000, cree=100, sortie=999))
        a = st.replier(a, _assistant(entree=1, lu=2000, cree=50, sortie=999))
        self.assertEqual(a.serie, (1102, 2051))
        self.assertEqual(a.contexte, 2051)
        self.assertEqual(a.pointe, 2051)

    def test_the_output_is_not_part_of_the_prompt(self):
        """Ce qui SORT n'est pas dans ce qui a été envoyé."""
        a = st.replier(st.Agregat(), _assistant(entree=10, sortie=100_000))
        self.assertEqual(a.contexte, 10)

    def test_a_compaction_shows_as_a_drop(self):
        """La pointe reste au-dessus du courant : c'est le décrochement."""
        a = st.Agregat()
        a = st.replier(a, _assistant(lu=500_000))
        a = st.replier(a, _assistant(lu=20_000))
        self.assertEqual(a.contexte, 20_000)
        self.assertEqual(a.pointe, 500_000)

    def test_the_series_is_bounded(self):
        """Une TUI trace une pente, pas dix mille points."""
        a = st.Agregat()
        for i in range(st.SERIE_MAX + 50):
            a = st.replier(a, _assistant(entree=i))
        self.assertEqual(len(a.serie), st.SERIE_MAX)
        self.assertEqual(a.serie[-1], st.SERIE_MAX + 49)

    def test_the_cache_reuse(self):
        a = st.replier(st.Agregat(), _assistant(entree=100, lu=900))
        self.assertAlmostEqual(a.reutilisation, 0.9)

    def test_no_turn_means_no_reuse_and_not_zero(self):
        """Zéro dirait « aucune réutilisation » là où rien n'a été mesuré."""
        self.assertIsNone(st.Agregat().reutilisation)
        self.assertEqual(st.Agregat().contexte, 0)


class TestLesCompactions(unittest.TestCase):
    def test_a_compact_summary_is_counted(self):
        a = st.replier(
            st.Agregat(),
            {"type": "user", "message": {"isCompactSummary": True}},
        )
        self.assertEqual(a.compactions, 1)

    def test_the_marker_is_also_read_at_the_top_level(self):
        a = st.replier(
            st.Agregat(),
            {"type": "user", "isCompactSummary": True, "message": {}},
        )
        self.assertEqual(a.compactions, 1)


class TestCeQuiEstIgnoreSansBruit(unittest.TestCase):
    def test_the_twelve_other_line_types(self):
        """Une transcription porte quinze types ; le paquet en connaît trois."""
        a = st.Agregat()
        for genre in (
            "custom-title",
            "agent-name",
            "mode",
            "attachment",
            "file-history-delta",
            "queue-operation",
        ):
            a = st.replier(a, {"type": genre, "quoi": "que ce soit"})
        self.assertEqual(a, st.Agregat())

    def test_a_line_that_is_not_an_object(self):
        for objet in ([], "texte", 12, None):
            self.assertEqual(st.replier(st.Agregat(), objet), st.Agregat())

    def test_a_broken_line_is_skipped(self):
        """Une transcription en cours d'écriture finit sur une ligne coupée."""
        texte = (
            json.dumps(_assistant(sortie=10))
            + "\n{ ceci n'est pas du JSON\n"
            + json.dumps(_assistant(sortie=5))
            + "\n"
        )
        a = st.replier_texte(st.Agregat(), texte)
        self.assertEqual(a.tours, 2)
        self.assertEqual(a.sortie, 15)


class TestLaLectureIncrementale(unittest.TestCase):
    def _fichier(self, texte):
        fh = tempfile.NamedTemporaryFile(
            "w", suffix=".jsonl", delete=False, encoding="utf-8"
        )
        fh.write(texte)
        fh.close()
        self.addCleanup(os.unlink, fh.name)
        return fh.name

    def test_a_first_read_takes_everything(self):
        chemin = self._fichier(json.dumps(_assistant(sortie=7)) + "\n")
        lecture = st.lire(chemin)
        self.assertEqual(lecture.agregat.sortie, 7)
        self.assertEqual(lecture.offset, os.path.getsize(chemin))

    def test_a_second_read_adds_only_what_grew(self):
        """C'est ce qui rend une TUI à deux secondes tenable sur dix mégaoctets."""
        chemin = self._fichier(json.dumps(_assistant(sortie=7)) + "\n")
        lecture = st.lire(chemin)
        with open(chemin, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(_assistant(sortie=3)) + "\n")
        suite = st.lire(chemin, lecture)
        self.assertEqual(suite.agregat.sortie, 10)
        self.assertEqual(suite.agregat.tours, 2)

    def test_nothing_new_returns_the_same_reading(self):
        chemin = self._fichier(json.dumps(_assistant(sortie=7)) + "\n")
        lecture = st.lire(chemin)
        self.assertIs(st.lire(chemin, lecture), lecture)

    def test_a_shrunk_file_is_read_whole_again(self):
        """Ce n'est plus la même transcription : reprendre à l'ancien offset
        plierait le milieu d'une ligne."""
        chemin = self._fichier(json.dumps(_assistant(sortie=7)) * 3 + "\n")
        lecture = st.lire(chemin)
        with open(chemin, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(_assistant(sortie=1)) + "\n")
        suite = st.lire(chemin, lecture)
        self.assertEqual(suite.agregat.sortie, 1)
        self.assertEqual(suite.agregat.tours, 1)

    def test_an_incomplete_last_line_waits(self):
        """L'offset s'arrête au dernier saut de ligne VU."""
        moitie = json.dumps(_assistant(sortie=7))
        chemin = self._fichier(moitie + "\n" + '{"type": "assist')
        lecture = st.lire(chemin)
        self.assertEqual(lecture.agregat.tours, 1)
        self.assertEqual(lecture.offset, len(moitie) + 1)

    def test_a_file_without_any_newline_yields_nothing(self):
        chemin = self._fichier('{"type": "assist')
        self.assertEqual(st.lire(chemin), st.Lecture())

    def test_a_missing_file_is_not_a_crash(self):
        self.assertEqual(
            st.lire("/introuvable/nulle-part.jsonl"), st.Lecture()
        )


class TestLaSomme(unittest.TestCase):
    def test_the_tokens_of_several_sessions_add_up(self):
        un = st.replier(st.Agregat(), _assistant(sortie=10, lu=100))
        deux = st.replier(st.Agregat(), _assistant(sortie=5, lu=50))
        total = st.somme([un, deux])
        self.assertEqual(total.sortie, 15)
        self.assertEqual(total.cache_lu, 150)
        self.assertEqual(total.tours, 2)

    def test_what_has_no_meaning_aggregated_does_not_come_out(self):
        """Ni série de contexte, ni compte de segments : un total de sessions
        n'a pas de « dernière invite » ni de « nombre de remises à zéro »."""
        un = st.replier(st.Agregat(), _assistant(lu=100))
        un = st.replier(un, _cout(5.0))
        total = st.somme([un, un])
        self.assertEqual(total.serie, ())
        self.assertEqual(total.segments, 0)
        self.assertEqual(total.par_modele, {})

    def test_an_empty_list_sums_to_nothing(self):
        self.assertEqual(st.somme([]), st.Agregat())


class TestContreUneVraieTranscription(unittest.TestCase):
    """La fixture se vérifie contre la chose réelle, quand elle est là.

    Sans ce test, la forme des champs ne serait qu'une supposition recopiée
    dans les fixtures. Avec lui, une transcription réelle doit produire un
    agrégat cohérent — et le test se saute là où il n'y a pas de session,
    plutôt que d'échouer sur l'absence de données d'un tiers.
    """

    def _une_transcription(self):
        import glob

        motif = os.path.expanduser("~/.claude/projects/*/*.jsonl")
        trouves = sorted(glob.glob(motif), key=os.path.getsize, reverse=True)
        return trouves[0] if trouves else None

    def test_a_real_transcript_aggregates(self):
        chemin = self._une_transcription()
        if not chemin:
            self.skipTest("aucune transcription sur cette machine")
        agregat = st.lire(chemin).agregat
        self.assertGreater(agregat.tours, 0, "aucun tour lu")
        self.assertGreater(agregat.sortie, 0, "aucun jeton de sortie")
        self.assertGreater(agregat.contexte, 0, "aucune taille de contexte")
        self.assertLessEqual(agregat.contexte, agregat.pointe)
        if agregat.reutilisation is not None:
            self.assertGreaterEqual(agregat.reutilisation, 0.0)
            self.assertLessEqual(agregat.reutilisation, 1.0)

    def test_reading_it_twice_adds_nothing(self):
        """L'incrémental doit être idempotent sur un fichier au repos."""
        chemin = self._une_transcription()
        if not chemin:
            self.skipTest("aucune transcription sur cette machine")
        une = st.lire(chemin)
        deux = st.lire(chemin, une)
        self.assertEqual(une.agregat.tours, deux.agregat.tours)


if __name__ == "__main__":
    unittest.main()
