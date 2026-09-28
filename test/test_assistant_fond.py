#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les agents détachés : ce qui tourne, ce qui est revenu, ce qui est parti.

Aucun test ne lance de vrai agent : le lanceur est INJECTÉ, et la liveness
d'un processus avec lui. Ce qui est éprouvé est la décision — quel état porte
une course — et non la capacité du noyau à détacher, qui ne se vérifie pas en
une seconde.

Trois régressions sont visées par leur nom.

**Le pid qui ment.** Un identifiant de processus se recycle : interroger celui
d'un agent fini peut désigner un inconnu bien vivant, et la course paraîtrait
tourner encore des heures après son retour. La sortie l'emporte donc sur le
pid, et l'ordre des deux tests EST le correctif.

**Le coût nul par défaut.** Une enveloppe qui ne dit pas ce qu'elle a coûté
n'a pas coûté zéro. Un zéro affiché se lit comme une mesure.

**La question dans l'argv.** Une ligne de commande se lit par tout compte de
la machine. La question part sur l'entrée standard, et un test vérifie
qu'aucun argument ne la porte.

Les agents, les questions et les clés sont INVENTÉS.
"""

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.todo.assistant.agents import fond  # noqa: E402

CLE = "2026-03-04-aaa11122"
ARGV = ["claude", "-p", "--output-format", "json", "--agent", "invente"]
QUESTION = "une question inventée"


class LEnveloppeDuResultat(unittest.TestCase):
    def test_la_derniere_ligne_analysable_fait_le_resultat(self):
        """La sortie porte des lignes de diagnostic avant le JSON ; elles ne
        sont pas le résultat."""
        texte = (
            "un avertissement\n"
            '{"result": "un essai"}\n'
            '{"result": "le vrai", "total_cost_usd": 0.5}\n'
        )
        self.assertEqual("le vrai", fond.enveloppe(texte)["result"])

    def test_une_sortie_sans_json_ne_rend_rien(self):
        for rien in ("", None, "pas de json ici", "{ casse", "[1, 2]"):
            with self.subTest(rien=rien):
                self.assertEqual({}, fond.enveloppe(rien))


class LEtatDUneCourse(unittest.TestCase):
    ENVELOPPE = '{"result": "fini"}'

    def test_une_sortie_complete_l_emporte_sur_un_pid_vivant(self):
        """Un pid se recycle : celui d'un agent fini peut désigner un
        inconnu, et la course paraîtrait tourner des heures après son
        retour."""
        self.assertEqual(fond.FINI, fond.etat_de(self.ENVELOPPE, True))
        self.assertEqual(fond.FINI, fond.etat_de(self.ENVELOPPE, False))

    def test_sans_sortie_le_pid_distingue_en_cours_de_perdu(self):
        self.assertEqual(fond.EN_COURS, fond.etat_de("", True))
        self.assertEqual(fond.PERDU, fond.etat_de("", False))

    def test_une_sortie_partielle_ne_vaut_pas_une_fin(self):
        """Un agent tué en route laisse du bruit : le lire comme une fin
        ferait croire à une réponse qui n'est jamais venue."""
        self.assertEqual(fond.EN_COURS, fond.etat_de("moitié de {", True))


class UnLancement(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.TemporaryDirectory()
        self.base = self.dossier.name
        self.addCleanup(self.dossier.cleanup)
        self.vus = []

    def _demarrer(self, pid=4242, ecrit=""):
        def demarrer(argv, question, chemin_sortie):
            self.vus.append((argv, question, str(chemin_sortie)))
            Path(chemin_sortie).write_text(ecrit, encoding="utf-8")
            return pid

        return demarrer

    def test_la_course_est_fichee_avec_ce_qu_on_sait(self):
        course = fond.lancer(
            CLE,
            "agent-invente",
            QUESTION,
            ARGV,
            cwd="/chemin-invente",
            outils=("Read", "Write"),
            base=self.base,
            demarrer=self._demarrer(),
        )
        self.assertEqual(fond.EN_COURS, course.etat)
        self.assertEqual(4242, course.pid)
        fiche = json.loads(
            (Path(self.base) / f"{CLE}{fond.META}").read_text("utf-8")
        )
        self.assertEqual("agent-invente", fiche["agent"])
        self.assertEqual(["Read", "Write"], fiche["outils"])

    def test_la_question_ne_passe_jamais_par_l_argv(self):
        """Une ligne de commande se lit par tout compte de la machine."""
        fond.lancer(
            CLE,
            "agent-invente",
            QUESTION,
            ARGV,
            base=self.base,
            demarrer=self._demarrer(),
        )
        (argv, question, _sortie) = self.vus[0]
        self.assertNotIn(QUESTION, argv)
        self.assertNotIn(QUESTION, " ".join(argv))
        self.assertEqual(QUESTION, question)

    def test_la_fiche_ne_se_lit_que_par_son_auteur(self):
        """La fiche est écrite par le lanceur ; la SORTIE l'est par le vrai
        démarreur, et c'est lui qu'éprouve le test d'à côté."""
        fond.lancer(
            CLE,
            "agent-invente",
            QUESTION,
            ARGV,
            base=self.base,
            demarrer=self._demarrer(),
        )
        cible = Path(self.base) / f"{CLE}{fond.META}"
        self.assertEqual(0o600, stat.S_IMODE(os.stat(cible).st_mode))

    def test_le_vrai_demarreur_ouvre_la_sortie_en_0600(self):
        """Le dossier personnel est lisible par tous les comptes de la
        machine, et une réponse porte ce qu'on a demandé. Un `open`
        ordinaire la créerait avec le masque du compte."""
        cible = Path(self.base) / "sortie-inventee.out"
        pid = fond._demarrer(
            [sys.executable, "-c", "import sys; sys.stdin.read()"],
            "rien",
            cible,
        )
        self.assertTrue(pid)
        self.assertEqual(0o600, stat.S_IMODE(os.stat(cible).st_mode))

    def test_un_lanceur_qui_ne_rend_aucun_pid_ne_fiche_rien(self):
        course = fond.lancer(
            CLE,
            "agent-invente",
            QUESTION,
            ARGV,
            base=self.base,
            demarrer=lambda *a: 0,
        )
        self.assertIsNone(course)
        self.assertEqual([], fond.courses(base=self.base))

    def test_un_lanceur_qui_leve_ne_tue_pas_le_menu(self):
        def refuse(*_a):
            raise OSError("binaire introuvable")

        self.assertIsNone(
            fond.lancer(
                CLE, "a", QUESTION, ARGV, base=self.base, demarrer=refuse
            )
        )


class LaListeDesCourses(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.TemporaryDirectory()
        self.base = self.dossier.name
        self.addCleanup(self.dossier.cleanup)

    def _poser(self, cle, agent="agent-invente", sortie="", pid=4242):
        def demarrer(argv, question, chemin_sortie):
            Path(chemin_sortie).write_text(sortie, encoding="utf-8")
            return pid

        return fond.lancer(
            cle, agent, QUESTION, ARGV, base=self.base, demarrer=demarrer
        )

    def test_le_resultat_et_le_cout_se_relisent(self):
        self._poser(
            CLE,
            sortie='{"result": "la réponse", "total_cost_usd": 0.0125}',
        )
        (vue,) = fond.courses(base=self.base, en_vie=lambda _pid: False)
        self.assertEqual(fond.FINI, vue.etat)
        self.assertEqual("la réponse", vue.resultat)
        self.assertEqual(0.0125, vue.cout)

    def test_un_cout_absent_vaut_inconnu_et_non_zero(self):
        """Un zéro affiché se lit comme une mesure."""
        self._poser(CLE, sortie='{"result": "sans prix"}')
        (vue,) = fond.courses(base=self.base, en_vie=lambda _pid: False)
        self.assertIsNone(vue.cout)

    def test_un_cout_qui_n_est_pas_un_nombre_vaut_inconnu(self):
        self._poser(CLE, sortie='{"result": "x", "total_cost_usd": "cher"}')
        (vue,) = fond.courses(base=self.base, en_vie=lambda _pid: False)
        self.assertIsNone(vue.cout)

    def test_la_plus_recente_sort_en_tete(self):
        self._poser("2026-03-01-aaa11122")
        self._poser("2026-03-09-bbb33344")
        cles = [
            vue.cle
            for vue in fond.courses(base=self.base, en_vie=lambda _p: True)
        ]
        self.assertEqual("2026-03-09-bbb33344", cles[0])

    def test_une_fiche_abimee_n_emporte_pas_les_voisines(self):
        self._poser(CLE)
        abimee = Path(self.base) / f"2026-03-09-cccc4444{fond.META}"
        abimee.write_text("{ pas du json", encoding="utf-8")
        vues = fond.courses(base=self.base, en_vie=lambda _pid: True)
        self.assertEqual([CLE], [vue.cle for vue in vues])

    def test_un_dossier_absent_se_lit_comme_aucune_course(self):
        self.assertEqual([], fond.courses(base="/chemin-invente/absent"))

    def test_le_signal_zero_ne_tue_rien_et_ne_leve_jamais(self):
        """Il demande seulement si le noyau connaît ce processus."""
        self.assertTrue(fond.vivant(os.getpid()))
        for absurde in (0, -1, None, "pas un pid", 2**31):
            with self.subTest(absurde=absurde):
                self.assertIsInstance(fond.vivant(absurde), bool)


if __name__ == "__main__":
    unittest.main()
