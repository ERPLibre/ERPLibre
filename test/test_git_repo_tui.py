#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""L'écran de parcours d'une mise à niveau.

Sans terminal : l'application se construit mais ne se lance pas. Ce qui se
vérifie ici est ce que l'écran MONTRE et dans quel ORDRE, pas son rendu.
"""

import ast
import os
import unittest

from script.todo import git_repo_tui


def constat(chemin, verdict, **extra):
    base = {
        "chemin": chemin,
        "verdict": verdict,
        "nos": 0,
        "amont_avance": 0,
        "conflits": [],
        "commits": [],
        "modules_repris": [],
        "amont": {"url": "https://exemple.invalide/o/d.git", "branche": "X"},
    }
    base.update(extra)
    return base


class TestOrdre(unittest.TestCase):
    def test_ce_qui_demande_une_decision_vient_en_tete(self):
        """Un écran trié par nom obligerait à traverser quinze dépôts sans
        objet pour trouver le seul qui compte."""
        brut = [
            constat("z", "a_jour"),
            constat("a", "non_comparable"),
            constat("m", "en_conflit"),
            constat("b", "a_rebaser"),
            constat("c", "absorbe"),
        ]
        self.assertEqual(
            [x["verdict"] for x in git_repo_tui.lignes(brut)],
            ["en_conflit", "absorbe", "a_rebaser", "non_comparable", "a_jour"],
        )

    def test_a_verdict_egal_le_chemin_departage(self):
        brut = [constat("z", "a_jour"), constat("a", "a_jour")]
        self.assertEqual(
            [x["chemin"] for x in git_repo_tui.lignes(brut)], ["a", "z"]
        )

    def test_un_verdict_inconnu_finit_la_liste(self):
        brut = [constat("a", "quelque_chose"), constat("b", "a_jour")]
        self.assertEqual(
            git_repo_tui.lignes(brut)[-1]["verdict"], "quelque_chose"
        )


class TestResume(unittest.TestCase):
    def test_les_trois_chiffres(self):
        c = constat(
            "a",
            "en_conflit",
            nos=2,
            amont_avance=545,
            conflits=["x", "y", "z"],
        )
        self.assertEqual(git_repo_tui.resume(c), ("+2", "−545", "3"))


class TestDetail(unittest.TestCase):
    def test_les_commits_du_fork_sont_nommes(self):
        c = constat("a", "a_rebaser", commits=[("abc1234", "[ADD] truc")])
        texte = git_repo_tui.detail(c)
        self.assertIn("abc1234", texte)
        self.assertIn("[ADD] truc", texte)

    def test_les_modules_repris_sont_nommes(self):
        c = constat("a", "absorbe", modules_repris=["mon_module"])
        self.assertIn("mon_module", git_repo_tui.detail(c))

    def test_le_motif_d_un_depot_non_comparable_apparait(self):
        c = constat("a", "non_comparable", motif="dépôt superficiel")
        self.assertIn("dépôt superficiel", git_repo_tui.detail(c))

    def test_une_longue_liste_de_conflits_est_bornee(self):
        """Quarante lignes suffisent à décider ; le reste chasserait de
        l'écran ce qui vient après."""
        c = constat(
            "a", "en_conflit", conflits=[f"f{i}.py" for i in range(120)]
        )
        texte = git_repo_tui.detail(c)
        self.assertIn("f0.py", texte)
        self.assertNotIn("f119.py", texte)
        self.assertIn("80", texte)

    def test_les_chiffres_de_l_amont(self):
        c = constat(
            "a",
            "a_rebaser",
            stats_amont={"langages": {"Python": {"ajouts": 7, "retraits": 2}}},
            modules_amont_doc=["d1", "d2"],
            modules_amont_code=["c1"],
        )
        texte = git_repo_tui.detail(c)
        self.assertIn("Python", texte)
        self.assertIn("+7", texte)

    def test_un_constat_minimal_ne_casse_pas(self):
        self.assertIn("a", git_repo_tui.detail({"chemin": "a"}))


class TestApplication(unittest.TestCase):
    def data(self):
        return {
            "version": "X",
            "forks": [
                constat("a/un", "en_conflit", conflits=["x"]),
                constat("a/deux", "a_jour"),
                constat("a/trois", "a_rebaser"),
            ],
        }

    def test_se_construit_sans_terminal(self):
        app = git_repo_tui.run_git_repo_tui(self.data(), run_app=False)
        self.assertEqual(len(app.tout), 3)
        self.assertIsNone(app.intent)

    def test_le_filtre_ne_garde_que_les_decisions(self):
        app = git_repo_tui.run_git_repo_tui(self.data(), run_app=False)
        self.assertEqual(len(app.visibles), 3)
        app.filtre = True
        self.assertEqual(
            [x["verdict"] for x in app.visibles],
            ["en_conflit", "a_rebaser"],
        )


class TestLectureSeule(unittest.TestCase):
    """L'écran ne doit émettre aucune commande qui écrive.

    Il sert à décider, et décider suppose d'avoir lu. Les gestes qui
    écrivent vivent dans le menu, derrière une confirmation.
    """

    SOURCE = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "script",
        "todo",
        "git_repo_tui.py",
    )

    def lire(self):
        with open(self.SOURCE, encoding="utf-8") as fh:
            return fh.read()

    def test_aucun_appel_a_un_moteur_qui_ecrit(self):
        source = self.lire()
        for interdit in (
            "repo_apply",
            "subprocess",
            "os.system",
            "exec_command",
        ):
            self.assertNotIn(interdit, source)

    def test_textual_est_importe_dans_la_fonction(self):
        """Le module doit rester importable — donc testable — sur une
        machine sans Textual."""
        source = self.lire()
        arbre = ast.parse(source)
        au_sommet = [
            n
            for n in arbre.body
            if isinstance(n, (ast.Import, ast.ImportFrom))
        ]
        for noeud in au_sommet:
            nom = getattr(noeud, "module", "") or ""
            noms = [a.name for a in noeud.names]
            self.assertNotIn("textual", nom)
            self.assertFalse(any("textual" in x for x in noms))


if __name__ == "__main__":
    unittest.main()
