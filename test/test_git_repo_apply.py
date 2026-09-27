#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""L'application d'une mise à niveau : branche datée, rebase, file.

« git » est remplacé par une table de réponses : ces fonctions ÉCRIVENT, et
les éprouver sur de vrais dépôts rendrait la suite unitaire dépendante d'un
plan de travail synchronisé. Ce qui se vérifie ici est la DÉCISION — quelle
commande part, avec quel drapeau, et dans quel ordre.
"""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from script.git import repo_apply


class GitSimule:
    def __init__(self, **reponses):
        self.reponses = reponses
        self.vues = []

    def __call__(self, args, cwd, delai=None):
        self.vues.append(list(args))
        nom = args[0]
        if nom == "rev-parse" and "--verify" in args:
            return "", "", 0 if self.reponses.get("branche_existe") else 1
        if nom == "rev-parse" and "--git-path" in args:
            return "absent/" + args[-1], "", 0
        if nom == "rev-parse":
            return self.reponses.get("head", "aaaa1111") + "\n", "", 0
        if nom == "checkout":
            return "", "", self.reponses.get("checkout_code", 0)
        if nom == "rebase":
            return "", "", self.reponses.get("rebase_code", 0)
        if nom == "diff":
            return self.reponses.get("conflits", ""), "", 0
        return "", "", 0

    def commandes(self, nom):
        return [a for a in self.vues if a and a[0] == nom]


def constat(verdict="a_rebaser", revision="18.0_dev"):
    return {
        "chemin": "odooX/addons/A_d",
        "revision": revision,
        "verdict": verdict,
    }


def appliquer_simule(c, simule, horodatage="20260927T0800"):
    with patch.object(repo_apply, "git", simule), patch(
        "os.path.isdir", return_value=False
    ):
        return repo_apply.appliquer(c, horodatage)


class TestNomBranche(unittest.TestCase):
    def test_forme(self):
        self.assertEqual(
            repo_apply.nom_branche("18.0_dev", "20260927T0800"),
            "18.0_dev_maj_20260927",
        )

    def test_l_heure_ne_compte_pas(self):
        """Deux passes du même jour visent le même nom, et la seconde se
        voit refuser la création au lieu d'écraser la première."""
        a = repo_apply.nom_branche("18.0", "20260927T0800")
        b = repo_apply.nom_branche("18.0", "20260927T2300")
        self.assertEqual(a, b)


class TestAppliquer(unittest.TestCase):
    def test_verdict_hors_champ_ignore(self):
        for verdict in ("a_jour", "en_retard", "non_comparable"):
            simule = GitSimule()
            res = appliquer_simule(constat(verdict), simule)
            self.assertEqual(res["etat"], "ignore")
            self.assertEqual(simule.commandes("checkout"), [])
            self.assertEqual(simule.commandes("rebase"), [])

    def test_rebase_propre(self):
        simule = GitSimule(rebase_code=0)
        res = appliquer_simule(constat(), simule)
        self.assertEqual(res["etat"], "rebase")
        self.assertEqual(res["branche"], "18.0_dev_maj_20260927")
        self.assertTrue(res["arrivee"])

    def test_la_branche_part_de_la_position_courante(self):
        simule = GitSimule()
        appliquer_simule(constat(), simule)
        self.assertEqual(
            simule.commandes("checkout")[0],
            ["checkout", "-b", "18.0_dev_maj_20260927"],
        )

    def test_le_rebase_vise_l_amont(self):
        simule = GitSimule()
        appliquer_simule(constat(), simule)
        self.assertEqual(
            simule.commandes("rebase")[0], ["rebase", "FETCH_HEAD"]
        )

    def test_une_branche_existante_n_est_jamais_ecrasee(self):
        """Une passe précédente du même jour peut porter des conflits
        résolus à la main ; les effacer serait irrattrapable."""
        simule = GitSimule(branche_existe=True)
        res = appliquer_simule(constat(), simule)
        self.assertEqual(res["etat"], "branche_existante")
        self.assertEqual(simule.commandes("checkout"), [])

    def test_conflit_laisse_le_rebase_en_cours(self):
        """Le rebase N'EST PAS abandonné : c'est dans cet état que la
        résolution se fera, et l'annuler obligerait à tout refaire."""
        simule = GitSimule(
            rebase_code=1, conflits="m/models/a.py\nm/views/v.xml\n"
        )
        res = appliquer_simule(constat(), simule)
        self.assertEqual(res["etat"], "conflit")
        self.assertEqual(res["conflits"], ["m/models/a.py", "m/views/v.xml"])
        self.assertNotIn(["rebase", "--abort"], simule.vues)

    def test_branche_refusee(self):
        simule = GitSimule(checkout_code=1)
        res = appliquer_simule(constat(), simule)
        self.assertEqual(res["etat"], "branche_refusee")
        self.assertEqual(simule.commandes("rebase"), [])

    def test_le_point_de_depart_est_releve_avant_tout(self):
        """Sans lui, aucun retour à l'état que git-repo attend."""
        simule = GitSimule(head="bbbb2222")
        res = appliquer_simule(constat(), simule)
        self.assertEqual(res["depart"], "bbbb2222")


class TestPasseAppliquer(unittest.TestCase):
    def test_seuls_les_depots_concernes_sont_touches(self):
        lst = [
            constat("a_rebaser"),
            constat("a_jour"),
            constat("en_conflit"),
            constat("non_comparable"),
        ]
        with patch.object(repo_apply, "git", GitSimule()), patch(
            "os.path.isdir", return_value=False
        ):
            res = repo_apply.passe_appliquer(lst, "20260927T0800")
        self.assertEqual(len(res), 2)

    def test_rien_a_faire_rend_une_liste_vide(self):
        with patch.object(repo_apply, "git", GitSimule()):
            self.assertEqual(
                repo_apply.passe_appliquer(
                    [constat("a_jour")], "20260927T0800"
                ),
                [],
            )


class TestInversionDuRebase(unittest.TestCase):
    """Le piège qui coûte le contraire de ce qu'on voulait garder.

    Pendant un rebase, git rejoue NOS commits par-dessus l'amont : c'est
    donc l'amont qui occupe la place de « ours », et notre commit celle de
    « theirs ». Une résolution écrite d'après l'intuition garde l'inverse
    de ce que le libellé annonce, et rien ne le signale.
    """

    def test_garder_le_notre_passe_theirs(self):
        simule = GitSimule()
        with patch.object(repo_apply, "git", simule):
            repo_apply.garder_le_notre("/x", ["a.py"])
        self.assertIn("--theirs", simule.vues[0])
        self.assertNotIn("--ours", simule.vues[0])

    def test_prendre_l_amont_passe_ours(self):
        simule = GitSimule()
        with patch.object(repo_apply, "git", simule):
            repo_apply.prendre_l_amont("/x", ["a.py"])
        self.assertIn("--ours", simule.vues[0])
        self.assertNotIn("--theirs", simule.vues[0])


class TestReprendreLaMain(unittest.TestCase):
    def test_continuer_neutralise_l_editeur(self):
        """git ouvrirait un éditeur pour le message du commit rejoué, et
        un menu n'a pas de terminal à lui prêter."""
        simule = GitSimule()
        with patch.object(repo_apply, "git", simule):
            repo_apply.continuer_rebase("/x")
        self.assertIn("core.editor=true", simule.vues[0])

    def test_revenir_vise_le_point_de_depart(self):
        """Détacher sur FETCH_HEAD poserait le dépôt sur l'amont, soit
        précisément là où la mise à niveau voulait l'emmener."""
        simule = GitSimule()
        with patch.object(repo_apply, "git", simule), patch(
            "os.path.isdir", return_value=False
        ):
            repo_apply.revenir_a_repo("/x", "cccc3333")
        self.assertEqual(simule.vues[-1], ["checkout", "--detach", "cccc3333"])

    def test_revenir_sans_depart_refuse(self):
        simule = GitSimule()
        with patch.object(repo_apply, "git", simule):
            _out, _err, code = repo_apply.revenir_a_repo("/x", "")
        self.assertEqual(code, 1)
        self.assertEqual(simule.vues, [])


class TestEnregistrement(unittest.TestCase):
    def setUp(self):
        self.racine = tempfile.mkdtemp()

    def test_aller_retour(self):
        resultats = [
            {"chemin": "a/b", "etat": "rebase", "sortie": "tout va bien"}
        ]
        repo_apply.ecrire_passe(
            "20260927T0800",
            "18.0",
            [{"chemin": "a/b"}],
            resultats,
            racine=self.racine,
        )
        lue = repo_apply.lire_passe(racine=self.racine)
        self.assertEqual(lue["version"], "18.0")
        self.assertEqual(lue["resultats"][0]["etat"], "rebase")

    def test_le_diagnostic_est_garde_avec_les_resultats(self):
        """Un conflit repris trois jours plus tard ne dit plus de quel
        amont il vient si le diagnostic n'a pas été conservé."""
        repo_apply.ecrire_passe(
            "20260927T0800",
            "18.0",
            [{"chemin": "a/b", "amont": {"branche": "18.0"}}],
            [],
            racine=self.racine,
        )
        lue = repo_apply.lire_passe(racine=self.racine)
        self.assertEqual(lue["diagnostic"][0]["amont"]["branche"], "18.0")

    def test_la_sortie_brute_va_dans_un_journal(self):
        repo_apply.ecrire_passe(
            "20260927T0800",
            "18.0",
            [],
            [{"chemin": "a/b", "etat": "conflit", "sortie": "CONFLIT ici"}],
            racine=self.racine,
        )
        journal = os.path.join(
            repo_apply.dossier_passe("20260927T0800", self.racine), "a_b.log"
        )
        with open(journal) as fh:
            self.assertIn("CONFLIT ici", fh.read())

    def test_la_plus_recente_d_abord(self):
        for h in ("20260101T0000", "20260927T0800", "20260501T0000"):
            repo_apply.ecrire_passe(h, "18.0", [], [], racine=self.racine)
        self.assertEqual(repo_apply.passes(self.racine)[0], "20260927T0800")

    def test_aucune_passe_rend_none(self):
        self.assertIsNone(repo_apply.lire_passe(racine=tempfile.mkdtemp()))

    def test_les_passes_vivent_hors_du_depot_versionne(self):
        """Une trace d'exécution n'a rien à faire dans l'historique."""
        self.assertTrue(
            repo_apply.DOSSIER_PASSES.startswith("tasks" + os.sep)
            or repo_apply.DOSSIER_PASSES.startswith("tasks/")
        )


if __name__ == "__main__":
    unittest.main()
