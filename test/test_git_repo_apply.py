#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""L'application d'une mise à niveau : branche datée, rebase, file, push.

Deux bancs. « GitSimule » remplace « git » par une table de réponses : ce
qui s'y vérifie est la DÉCISION — quelle commande part, avec quel drapeau,
et dans quel ordre. « TestDepotsReels » monte dans un dossier temporaire
un amont et un fork nus, et un clone dont les remotes sont des chemins
locaux : le rebase, le fast-forward et les push s'y jouent pour de vrai,
sans réseau et sans toucher aux clones du checkout.
"""

import os
import shutil
import subprocess
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
        if nom == "merge-base":
            # « ancetres » : {(ancêtre, descendant): code}, sinon
            # « ancetre_code » pour toute paire.
            paire = (args[-2], args[-1])
            ancetres = self.reponses.get("ancetres", {})
            return (
                "",
                "",
                ancetres.get(paire, self.reponses.get("ancetre_code", 0)),
            )
        if nom == "status":
            return self.reponses.get("status", ""), "", 0
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
        for verdict in ("a_jour", "non_comparable"):
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

    def test_le_rebase_vise_la_cible_du_diagnostic(self):
        """La cible nommée, et non FETCH_HEAD, qu'un fetch suivant peut
        avoir déplacé : le reflog dit alors sur quoi la branche est posée."""
        simule = GitSimule()
        res = appliquer_simule(dict(constat(), cible="U/18.0"), simule)
        self.assertEqual(simule.commandes("rebase")[0], ["rebase", "U/18.0"])
        self.assertEqual(res["cible"], "U/18.0")
        self.assertNotIn(
            "FETCH_HEAD", [x for args in simule.vues for x in args]
        )

    def test_sans_cible_fetch_head(self):
        res = appliquer_simule(constat(), GitSimule())
        self.assertEqual(res["cible"], "FETCH_HEAD")

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

    def test_arbre_sale_refuse_sans_rien_ecrire(self):
        """git refuserait le rebase, et l'échec passerait pour un conflit
        sans rebase en cours, absent de la file."""
        simule = GitSimule(status=" M a.py\n")
        res = appliquer_simule(constat(), simule)
        self.assertEqual(res["etat"], "sale")
        self.assertEqual(simule.commandes("checkout"), [])
        self.assertEqual(simule.commandes("rebase"), [])

    def test_echec_sans_rebase_en_cours_n_est_pas_un_conflit(self):
        simule = GitSimule(rebase_code=1)
        res = appliquer_simule(constat(), simule)
        self.assertEqual(res["etat"], "rebase_refuse")

    def test_rebase_refuse_remet_le_depart(self):
        """HEAD détachée au départ : « checkout -f --detach » sur le départ,
        puis la branche datée supprimée et retirée de l'enregistrement."""
        simule = GitSimule(rebase_code=1)
        res = appliquer_simule(constat(), simule)
        self.assertIn(
            ["checkout", "-f", "--detach", "aaaa1111"],
            simule.commandes("checkout"),
        )
        self.assertIn(
            ["branch", "-D", "18.0_dev_maj_20260927"],
            simule.commandes("branch"),
        )
        self.assertIs(res["restaure"], True)
        self.assertIsNone(res["branche"])

    def test_rebase_refuse_revient_sur_la_branche_de_depart(self):
        simule = GitSimule(rebase_code=1)
        reponse = simule.__call__

        def avec_branche(args, cwd, delai=None):
            if args[0] == "symbolic-ref":
                simule.vues.append(list(args))
                return "18.0_dev\n", "", 0
            return reponse(args, cwd, delai)

        res = appliquer_simule(constat(), avec_branche)
        self.assertIn(
            ["checkout", "-f", "18.0_dev"], simule.commandes("checkout")
        )
        self.assertIs(res["restaure"], True)

    def test_restauration_refusee_garde_la_branche(self):
        """Le retour échoue : la branche datée reste, et la sortie donne la
        commande à lancer à la main."""

        class Simule(GitSimule):
            def __call__(self, args, cwd, delai=None):
                if args[:2] == ["checkout", "-f"]:
                    self.vues.append(list(args))
                    return "", "erreur", 1
                return super().__call__(args, cwd, delai)

        simule = Simule(rebase_code=1)
        res = appliquer_simule(constat(), simule)
        self.assertIs(res["restaure"], False)
        self.assertEqual(res["branche"], "18.0_dev_maj_20260927")
        self.assertEqual(simule.commandes("branch"), [])
        self.assertIn("checkout -f --detach aaaa1111", res["sortie"])

    def test_avance_refusee_remet_le_depart(self):
        simule = GitSimule()
        reponse = simule.__call__

        def ff_refuse(args, cwd, delai=None):
            if args[0] == "merge":
                simule.vues.append(list(args))
                return "", "", 1
            return reponse(args, cwd, delai)

        res = appliquer_simule(constat("en_retard"), ff_refuse)
        self.assertEqual(res["etat"], "avance_refusee")
        self.assertIs(res["restaure"], True)
        self.assertIn(
            ["checkout", "-f", "--detach", "aaaa1111"],
            simule.commandes("checkout"),
        )

    def test_un_conflit_n_est_pas_restaure(self):
        simule = GitSimule(rebase_code=1, conflits="m/a.py\n")
        res = appliquer_simule(constat(), simule)
        self.assertEqual(res["etat"], "conflit")
        self.assertIsNone(res["restaure"])
        self.assertEqual(
            [a for a in simule.commandes("checkout") if "-f" in a], []
        )

    BASE, GEL = "b" * 40, "c" * 40

    def _rebase_avec_base(self, **ancetres):
        """`appliquer` sur un constat qui porte une base et un commit
        gelés ; `ancetres` donne le code de « merge-base --is-ancestor »
        par paire nommée : base_amont (base, FETCH_HEAD), gel_head (gel,
        HEAD), base_gel (base, gel). Une paire omise vaut 0 (ancêtre)."""
        noms = {
            "base_amont": (self.BASE, "FETCH_HEAD"),
            "gel_head": (self.GEL, "HEAD"),
            "base_gel": (self.BASE, self.GEL),
        }
        simule = GitSimule(
            ancetres={noms[k]: code for k, code in ancetres.items()}
        )
        c = dict(constat(), base_gelee=self.BASE, gel=self.GEL)
        return appliquer_simule(c, simule), simule

    def test_amont_reecrit_rebase_onto(self):
        res, simule = self._rebase_avec_base(base_amont=1)
        self.assertEqual(
            simule.commandes("rebase")[0],
            ["rebase", "--onto", "FETCH_HEAD", self.BASE],
        )
        self.assertTrue(res["onto"])
        self.assertEqual(res["base"], self.BASE)
        self.assertEqual(res["mode"], repo_apply.MODE_ONTO)

    def test_chaque_condition_manquante_rend_le_rebase_ordinaire(self):
        """« --onto » perd l'écart par patch-id et, sur une base périmée,
        rejoue des commits amont comme les nôtres : la moindre condition
        manquante rend le rebase ordinaire."""
        cas = [
            ({"base_amont": 0}, repo_apply.MODE_BASE_AMONT),
            ({"base_amont": 128}, repo_apply.MODE_BASE_ABSENTE),
            ({"base_amont": 1, "gel_head": 1}, repo_apply.MODE_GEL_HORS_HEAD),
            ({"base_amont": 1, "base_gel": 1}, repo_apply.MODE_BASE_HORS_GEL),
        ]
        for ancetres, mode in cas:
            with self.subTest(mode=mode):
                res, simule = self._rebase_avec_base(**ancetres)
                self.assertEqual(
                    simule.commandes("rebase")[0], ["rebase", "FETCH_HEAD"]
                )
                self.assertFalse(res["onto"])
                self.assertEqual(res["mode"], mode)

    def test_sans_commit_gele_le_rebase_est_ordinaire(self):
        simule = GitSimule(ancetre_code=1)
        c = dict(constat(), base_gelee=self.BASE)
        res = appliquer_simule(c, simule)
        self.assertEqual(res["mode"], repo_apply.MODE_GEL_HORS_HEAD)
        self.assertFalse(res["onto"])

    def test_la_cible_sert_aussi_a_onto_et_au_fast_forward(self):
        simule = GitSimule(ancetres={(self.BASE, "U/18.0"): 1})
        c = dict(constat(), base_gelee=self.BASE, gel=self.GEL, cible="U/18.0")
        appliquer_simule(c, simule)
        self.assertEqual(
            simule.commandes("rebase")[0],
            ["rebase", "--onto", "U/18.0", self.BASE],
        )
        simule = GitSimule()
        appliquer_simule(dict(constat("en_retard"), cible="U/18.0"), simule)
        self.assertEqual(
            simule.commandes("merge")[0], ["merge", "--ff-only", "U/18.0"]
        )

    def test_en_retard_avance_sans_rebase(self):
        simule = GitSimule()
        res = appliquer_simule(constat("en_retard"), simule)
        self.assertEqual(res["etat"], "avance")
        self.assertEqual(simule.commandes("rebase"), [])
        self.assertEqual(
            simule.commandes("merge")[0], ["merge", "--ff-only", "FETCH_HEAD"]
        )

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

    def test_en_retard_fait_partie_de_la_passe(self):
        with patch.object(repo_apply, "git", GitSimule()), patch(
            "os.path.isdir", return_value=False
        ):
            res = repo_apply.passe_appliquer(
                [constat("en_retard")], "20260927T0800"
            )
        self.assertEqual([r["etat"] for r in res], ["avance"])

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
        self.addCleanup(shutil.rmtree, self.racine, True)

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
        vide = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, vide, True)
        self.assertIsNone(repo_apply.lire_passe(racine=vide))

    def test_mettre_a_jour_un_depot_de_la_passe(self):
        repo_apply.ecrire_passe(
            "20260927T0800",
            "18.0",
            [],
            [
                {"chemin": "a/b", "etat": "conflit", "conflits": ["x.py"]},
                {"chemin": "c/d", "etat": "rebase"},
            ],
            racine=self.racine,
        )
        res = repo_apply.mettre_a_jour_passe(
            "20260927T0800",
            "a/b",
            {"etat": "rebase", "conflits": []},
            racine=self.racine,
        )
        self.assertEqual(res["etat"], "rebase")
        lue = repo_apply.lire_passe(racine=self.racine)
        self.assertEqual(lue["resultats"][0]["etat"], "rebase")
        self.assertEqual(lue["resultats"][0]["conflits"], [])
        self.assertEqual(
            lue["resultats"][1], {"chemin": "c/d", "etat": "rebase"}
        )

    def test_mettre_a_jour_un_depot_absent_n_ecrit_rien(self):
        self.assertIsNone(
            repo_apply.mettre_a_jour_passe(
                "20260927T0800", "a/b", {"etat": "x"}, racine=self.racine
            )
        )

    def test_noter_resolution_releve_l_arrivee(self):
        repo_apply.ecrire_passe(
            "20260927T0800",
            "18.0",
            [],
            [{"chemin": "a/b", "etat": "conflit", "conflits": ["x.py"]}],
            racine=self.racine,
        )
        res = {"chemin": "a/b", "etat": "conflit"}
        with patch.object(repo_apply, "sha_de", return_value="d" * 40):
            repo_apply.noter_resolution(
                "20260927T0800", res, "rebase", racine=self.racine
            )
        self.assertEqual(res["arrivee"], "d" * 40)
        lue = repo_apply.lire_passe(racine=self.racine)
        self.assertEqual(lue["resultats"][0]["etat"], "rebase")
        self.assertEqual(lue["resultats"][0]["arrivee"], "d" * 40)
        repo_apply.noter_resolution(
            "20260927T0800", res, "abandonne", racine=self.racine
        )
        lue = repo_apply.lire_passe(racine=self.racine)
        self.assertEqual(lue["resultats"][0]["etat"], "abandonne")
        self.assertIsNone(lue["resultats"][0]["arrivee"])

    def test_les_passes_vivent_hors_du_depot_versionne(self):
        """Une trace d'exécution n'a rien à faire dans l'historique."""
        self.assertTrue(
            repo_apply.DOSSIER_PASSES.startswith("tasks" + os.sep)
            or repo_apply.DOSSIER_PASSES.startswith("tasks/")
        )


class TestNomsParDefaut(unittest.TestCase):
    def test_tag(self):
        self.assertEqual(
            repo_apply.nom_par_defaut_tag("9.9.9", "X.0", set(), "20990101"),
            "ERPLibre/v9.9.9_odooX.0",
        )

    def test_tag_existant_suffixe_du_jour(self):
        self.assertEqual(
            repo_apply.nom_par_defaut_tag(
                "9.9.9", "X.0", {"ERPLibre/v9.9.9_odooX.0"}, "20990101T0800"
            ),
            "ERPLibre/v9.9.9_odooX.0_20990101",
        )

    def test_branche(self):
        self.assertEqual(
            repo_apply.nom_par_defaut_branche("X.0_dev", "20990101T0800"),
            "X.0_dev_avant_maj_20990101",
        )

    def test_version_erplibre_lue_dans_tool_poetry(self):
        racine = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, racine, True)
        with open(os.path.join(racine, "pyproject.toml"), "w") as fh:
            fh.write(
                '[tool.black]\nversion = "0.0.1"\n\n'
                '[tool.poetry]\nname = "x"\nversion = "9.9.9"\n'
            )
        self.assertEqual(repo_apply.version_erplibre(racine), "9.9.9")
        self.assertEqual(
            repo_apply.version_erplibre(os.path.join(racine, "absent")), ""
        )


def _git(cwd, *args):
    """Lance git sans dépendre de la configuration de l'hôte ; rend stdout."""
    return subprocess.run(
        [
            "git",
            "-c",
            "init.defaultBranch=principale",
            *args,
        ],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


class TestDepotsReels(unittest.TestCase):
    """Un amont nu, un fork nu, un clone du fork en HEAD détachée.

    L'environnement isole git de la configuration de l'hôte : aucun fichier
    global ni système n'est lu, et l'identité des commits est fixée. Tous
    les remotes sont des chemins du dossier temporaire.
    """

    REVISION = "X.0"
    REMOTE = "fork_origin_amont"
    HORODATAGE = "20990101T0800"

    def setUp(self):
        self.dossier = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dossier, True)
        env = patch.dict(
            os.environ,
            {
                "GIT_CEILING_DIRECTORIES": self.dossier,
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_AUTHOR_NAME": "Test",
                "GIT_AUTHOR_EMAIL": "test@example.invalid",
                "GIT_COMMITTER_NAME": "Test",
                "GIT_COMMITTER_EMAIL": "test@example.invalid",
            },
        )
        env.start()
        self.addCleanup(env.stop)
        self.amont = os.path.join(self.dossier, "amont.git")
        self.fork = os.path.join(self.dossier, "fork.git")
        self.source = os.path.join(self.dossier, "source")
        self.clone = os.path.join(self.dossier, "clone")
        _git(self.dossier, "init", "-q", "--bare", self.amont)
        _git(self.dossier, "init", "-q", "--bare", self.fork)
        _git(self.dossier, "init", "-q", self.source)
        self.u1 = self.commit(self.source, "amont.txt", "un")
        _git(self.source, "push", "-q", self.amont, "HEAD:principale")
        _git(self.source, "push", "-q", self.fork, f"HEAD:{self.REVISION}")
        _git(
            self.dossier,
            "clone",
            "-q",
            "-o",
            self.REMOTE,
            "-b",
            self.REVISION,
            self.fork,
            self.clone,
        )

    def commit(self, depot, fichier, contenu):
        with open(os.path.join(depot, fichier), "w") as fh:
            fh.write(contenu)
        _git(depot, "add", fichier)
        _git(depot, "commit", "-q", "-m", f"{fichier} {contenu}")
        return _git(depot, "rev-parse", "HEAD")

    def commit_du_fork(self):
        """Un commit propre au fork, publié, puis la HEAD détachée dessus."""
        sha = self.commit(self.clone, "fork.txt", "notre")
        _git(self.clone, "push", "-q", self.REMOTE, f"HEAD:{self.REVISION}")
        _git(self.clone, "checkout", "-q", "--detach", sha)
        return sha

    def amont_avance(self, contenu="deux"):
        sha = self.commit(self.source, "amont.txt", contenu)
        _git(self.source, "push", "-q", self.amont, "HEAD:principale")
        return sha

    def amont_reecrit(self):
        """L'amont remplace son historique : la base gelée n'y est plus."""
        _git(self.source, "checkout", "-q", "--orphan", "neuve")
        self.commit(self.source, "amont.txt", "UN")
        sha = self.commit(self.source, "amont.txt", "DEUX")
        _git(self.source, "push", "-q", "-f", self.amont, "HEAD:principale")
        return sha

    def fetch_amont(self):
        _git(self.clone, "fetch", "-q", self.amont, "principale")

    def constat(self, verdict="a_rebaser", **kw):
        c = {
            "chemin": "clone",
            "revision": self.REVISION,
            "remote": self.REMOTE,
            "verdict": verdict,
            "gel": _git(self.clone, "rev-parse", "HEAD"),
        }
        c.update(kw)
        return c

    def appliquer(self, c):
        return repo_apply.appliquer(c, self.HORODATAGE, racine=self.dossier)

    def distant(self, ref=None):
        return _git(
            self.fork, "rev-parse", ref or f"refs/heads/{self.REVISION}"
        )

    # ── appliquer ──

    @unittest.skipIf(
        hasattr(os, "geteuid") and os.geteuid() == 0,
        "root écrit dans un dossier sans droit d'écriture",
    )
    def test_checkout_interrompu_remet_le_depart(self):
        """Un dossier sans droit d'écriture arrête le checkout de l'amont à
        mi-chemin : un fichier suivi et un fichier neuf sont déjà écrits.
        Le dépôt revient sur son départ, sans le fichier neuf ni la branche
        datée ; le fichier non suivi d'avant reste."""
        notre = self.commit_du_fork()
        self.commit(self.source, "a.txt", "neuf")
        os.makedirs(os.path.join(self.source, "z"))
        self.commit(self.source, os.path.join("z", "y.txt"), "bloque")
        self.amont_avance("deux")
        self.fetch_amont()
        with open(os.path.join(self.clone, "a_moi.txt"), "w") as fh:
            fh.write("à moi")
        bloque = os.path.join(self.clone, "z")
        os.makedirs(bloque)
        os.chmod(bloque, 0o500)
        self.addCleanup(os.chmod, bloque, 0o700)
        res = self.appliquer(self.constat())
        self.assertEqual(res["etat"], "rebase_refuse", res["sortie"])
        self.assertIs(res["restaure"], True, res["sortie"])
        self.assertEqual(_git(self.clone, "rev-parse", "HEAD"), notre)
        self.assertEqual(
            _git(self.clone, "status", "--porcelain", "--untracked-files=no"),
            "",
        )
        self.assertFalse(os.path.exists(os.path.join(self.clone, "a.txt")))
        self.assertTrue(os.path.exists(os.path.join(self.clone, "a_moi.txt")))
        self.assertEqual(_git(self.clone, "branch", "--list", "*_maj_*"), "")

    def test_rebase_onto_ne_rejoue_que_nos_commits(self):
        """Sur un amont réécrit, un rebase ordinaire rejouerait l'ancien
        amont avec nos commits ; « --onto » depuis la base gelée ne rejoue
        que le nôtre."""
        notre = self.commit_du_fork()
        nouvel_amont = self.amont_reecrit()
        self.fetch_amont()
        res = self.appliquer(self.constat(base_gelee=self.u1))
        self.assertEqual(res["etat"], "rebase", res["sortie"])
        self.assertTrue(res["onto"])
        self.assertEqual(res["mode"], repo_apply.MODE_ONTO)
        self.assertEqual(res["base"], self.u1)
        self.assertEqual(res["amont"], nouvel_amont)
        self.assertEqual(res["depart"], notre)
        self.assertEqual(
            _git(self.clone, "rev-list", "--count", "FETCH_HEAD..HEAD"), "1"
        )
        self.assertEqual(_git(self.clone, "rev-parse", "HEAD^"), nouvel_amont)

    def test_rebase_sur_la_branche_du_remote_amont_nomme(self):
        """Le remote amont nommé, posé par `preparer_remote` : le rebase
        part de « amont_nomme/principale » même quand FETCH_HEAD désigne
        autre chose, et le reflog le nomme."""
        from script.git import repo_upgrade

        self.commit_du_fork()
        nouvel_amont = self.amont_avance()
        amont = {
            "remote": "amont_nomme",
            "url": self.amont,
            "branche": "principale",
            "source": "declare",
        }
        self.assertEqual(
            repo_upgrade.preparer_remote(self.clone, amont)[0], "ajoute"
        )
        self.assertTrue(
            repo_upgrade.recuperer_amont(
                self.clone, self.amont, "principale", remote="amont_nomme"
            )
        )
        _git(self.clone, "fetch", "-q", self.fork, self.REVISION)
        res = self.appliquer(self.constat(cible="amont_nomme/principale"))
        self.assertEqual(res["etat"], "rebase", res["sortie"])
        self.assertEqual(res["amont"], nouvel_amont)
        self.assertEqual(res["cible"], "amont_nomme/principale")
        self.assertEqual(_git(self.clone, "rev-parse", "HEAD^"), nouvel_amont)
        self.assertIn(
            "checkout amont_nomme/principale",
            _git(self.clone, "reflog", "-n", "20"),
        )

    def test_sans_base_gelee_le_rebase_est_ordinaire(self):
        self.commit_du_fork()
        nouvel_amont = self.amont_avance()
        self.fetch_amont()
        res = self.appliquer(self.constat())
        self.assertEqual(res["etat"], "rebase", res["sortie"])
        self.assertFalse(res["onto"])
        self.assertEqual(_git(self.clone, "rev-parse", "HEAD^"), nouvel_amont)

    def test_notre_commit_repris_en_amont_est_ecarte(self):
        """L'amont reprend notre commit puis retouche le même fichier : le
        rebase ordinaire écarte notre commit par son patch-id, là où
        « --onto » le rejouerait et buterait sur la retouche."""
        self.commit_du_fork()
        _git(self.source, "fetch", "-q", self.fork, self.REVISION)
        _git(self.source, "cherry-pick", "FETCH_HEAD")
        self.commit(self.source, "fork.txt", "retouche amont")
        _git(self.source, "push", "-q", self.amont, "HEAD:principale")
        self.fetch_amont()
        res = self.appliquer(self.constat(base_gelee=self.u1))
        self.assertEqual(res["etat"], "rebase", res["sortie"])
        self.assertFalse(res["onto"])
        self.assertEqual(res["mode"], repo_apply.MODE_BASE_AMONT)
        self.assertEqual(
            _git(self.clone, "rev-parse", "HEAD"),
            _git(self.clone, "rev-parse", "FETCH_HEAD"),
        )

    def test_base_perimee_rebase_ordinaire(self):
        """Le fork a intégré un amont plus récent que sa base gelée :
        « --onto » depuis cette base rejouerait comme nôtres les commits
        amont qui l'ont suivie."""
        gel = self.commit_du_fork()
        self.amont_avance()
        self.fetch_amont()
        _git(self.clone, "rebase", "-q", "FETCH_HEAD")
        _git(
            self.clone,
            "push",
            "-q",
            "-f",
            self.REMOTE,
            f"HEAD:{self.REVISION}",
        )
        nouvel_amont = self.amont_avance("trois")
        self.fetch_amont()
        res = self.appliquer(self.constat(base_gelee=self.u1, gel=gel))
        self.assertEqual(res["etat"], "rebase", res["sortie"])
        self.assertFalse(res["onto"])
        self.assertEqual(res["mode"], repo_apply.MODE_BASE_AMONT)
        self.assertEqual(_git(self.clone, "rev-parse", "HEAD^"), nouvel_amont)
        self.assertEqual(
            _git(self.clone, "rev-list", "--count", "FETCH_HEAD..HEAD"), "1"
        )

    def test_en_retard_avance_en_fast_forward(self):
        _git(self.clone, "checkout", "-q", "--detach", self.u1)
        nouvel_amont = self.amont_avance()
        self.fetch_amont()
        res = self.appliquer(self.constat("en_retard"))
        self.assertEqual(res["etat"], "avance", res["sortie"])
        self.assertEqual(res["arrivee"], nouvel_amont)
        self.assertEqual(
            _git(self.clone, "rev-parse", "--abbrev-ref", "HEAD"),
            "X.0_maj_20990101",
        )

    def test_arbre_sale_refuse(self):
        self.commit_du_fork()
        self.amont_avance()
        self.fetch_amont()
        with open(os.path.join(self.clone, "fork.txt"), "w") as fh:
            fh.write("modifié")
        res = self.appliquer(self.constat())
        self.assertEqual(res["etat"], "sale")
        self.assertIsNone(res["branche"])
        self.assertFalse(
            repo_apply.branche_existe(self.clone, "X.0_maj_20990101")
        )

    def test_fork_en_avance_sur_head_refuse(self):
        """Le distant porte un commit que HEAD n'a pas : publier le
        résultat le perdrait."""
        self.commit_du_fork()
        _git(self.clone, "checkout", "-q", "--detach", self.u1)
        self.amont_avance()
        self.fetch_amont()
        res = self.appliquer(self.constat("a_rebaser"))
        self.assertEqual(res["etat"], "distant_en_avance")
        self.assertIsNone(res["branche"])

    # ── publier ──

    def rebase_publiable(self):
        self.commit_du_fork()
        self.amont_avance()
        self.fetch_amont()
        res = self.appliquer(self.constat(base_gelee=self.u1))
        self.assertEqual(res["etat"], "rebase", res["sortie"])
        return res

    def test_fast_forward_publie_sans_force(self):
        _git(self.clone, "checkout", "-q", "--detach", self.u1)
        nouvel_amont = self.amont_avance()
        self.fetch_amont()
        res = self.appliquer(self.constat("en_retard"))
        plan = repo_apply.plan_publication(self.clone, res)
        self.assertFalse(plan["force"])
        self.assertEqual(plan["a_retenir"], [])
        self.assertEqual(plan["ancien"], self.u1)
        _out, err, code = repo_apply.publier(self.clone, plan)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.distant(), nouvel_amont)
        # HEAD détachée sur le commit poussé, la branche datée gardée.
        with self.assertRaises(subprocess.CalledProcessError):
            _git(self.clone, "symbolic-ref", "-q", "HEAD")
        self.assertEqual(_git(self.clone, "rev-parse", "HEAD"), nouvel_amont)
        self.assertTrue(
            repo_apply.branche_existe(self.clone, "X.0_maj_20990101")
        )

    def test_push_force_refuse_tant_que_l_ancien_n_est_pas_retenu(self):
        res = self.rebase_publiable()
        ancien = self.distant()
        plan = repo_apply.plan_publication(self.clone, res)
        self.assertTrue(plan["force"])
        self.assertEqual(plan["a_retenir"], [ancien])
        _out, _err, code = repo_apply.publier(self.clone, plan)
        self.assertEqual(code, 1)
        self.assertEqual(self.distant(), ancien)

    def test_tag_pousse_puis_push_force_avec_bail(self):
        res = self.rebase_publiable()
        ancien = self.distant()
        plan = repo_apply.plan_publication(self.clone, res)
        _out, err, code = repo_apply.retenir(
            self.clone, ancien, self.REMOTE, "tag", "ERPLibre/v9.9.9_odooX.0"
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(
            self.distant("refs/tags/ERPLibre/v9.9.9_odooX.0"), ancien
        )
        self.assertEqual(
            repo_apply.retenu_par(
                self.clone, ancien, self.REMOTE, self.REVISION
            ),
            ["refs/tags/ERPLibre/v9.9.9_odooX.0"],
        )
        _out, err, code = repo_apply.publier(self.clone, plan)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.distant(), plan["nouveau"])

    def test_branche_poussee_retient_l_ancien(self):
        res = self.rebase_publiable()
        ancien = self.distant()
        plan = repo_apply.plan_publication(self.clone, res)
        nom = repo_apply.nom_par_defaut_branche(self.REVISION, self.HORODATAGE)
        _out, err, code = repo_apply.retenir(
            self.clone, ancien, self.REMOTE, "branche", nom
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(self.distant(f"refs/heads/{nom}"), ancien)
        self.assertEqual(
            repo_apply.a_retenir(
                self.clone,
                ancien,
                plan["gel"],
                plan["nouveau"],
                self.REMOTE,
                self.REVISION,
            ),
            [],
        )

    def test_une_branche_homonyme_n_est_jamais_deplacee(self):
        _git(
            self.source, "push", "-q", self.fork, f"{self.u1}:refs/heads/garde"
        )
        notre = self.commit_du_fork()
        _out, _err, code = repo_apply.retenir(
            self.clone, notre, self.REMOTE, "branche", "garde"
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(self.distant("refs/heads/garde"), self.u1)

    def test_tag_refuse_au_distant_retire_du_clone(self):
        notre = self.commit_du_fork()
        _git(self.source, "push", "-q", self.fork, f"{self.u1}:refs/tags/pris")
        _out, _err, code = repo_apply.retenir(
            self.clone, notre, self.REMOTE, "tag", "pris"
        )
        self.assertNotEqual(code, 0)
        self.assertNotIn("pris", repo_apply.tags(self.clone))

    def test_la_branche_reecrite_ne_retient_rien(self):
        notre = self.commit_du_fork()
        _git(self.clone, "fetch", "-q", self.REMOTE)
        self.assertEqual(
            repo_apply.retenu_par(
                self.clone, notre, self.REMOTE, self.REVISION
            ),
            [],
        )

    def test_un_tag_local_ne_retient_rien(self):
        res = self.rebase_publiable()
        ancien = self.distant()
        _git(self.clone, "tag", "seulement_ici", ancien)
        self.assertEqual(
            repo_apply.retenu_par(
                self.clone, ancien, self.REMOTE, self.REVISION
            ),
            [],
        )
        plan = repo_apply.plan_publication(self.clone, res)
        self.assertEqual(plan["a_retenir"], [ancien])

    def test_un_suivi_perime_ne_retient_rien(self):
        """La branche supprimée au distant survit dans le suivi du clone
        tant qu'aucun « fetch --prune » ne passe : elle ne garde plus
        rien."""
        res = self.rebase_publiable()
        ancien = self.distant()
        _git(
            self.clone,
            "push",
            "-q",
            self.fork,
            f"{ancien}:refs/heads/vieille",
        )
        _git(self.clone, "fetch", "-q", self.REMOTE)
        _git(self.source, "push", "-q", self.fork, ":refs/heads/vieille")
        self.assertTrue(
            repo_apply.sha_de(
                self.clone, f"refs/remotes/{self.REMOTE}/vieille"
            )
        )
        plan = repo_apply.plan_publication(self.clone, res)
        self.assertEqual(plan["a_retenir"], [ancien])

    def test_un_tag_annote_du_distant_retient_son_commit(self):
        self.rebase_publiable()
        ancien = self.distant()
        _git(self.clone, "tag", "-a", "-m", "garde", "annote", ancien)
        _git(self.clone, "push", "-q", self.REMOTE, "refs/tags/annote")
        self.assertEqual(
            repo_apply.retenu_par(
                self.clone, ancien, self.REMOTE, self.REVISION
            ),
            ["refs/tags/annote"],
        )

    def test_une_ref_distante_absente_du_clone_ne_compte_pas(self):
        res = self.rebase_publiable()
        ancien = self.distant()
        _git(self.source, "fetch", "-q", self.fork, self.REVISION)
        _git(self.source, "checkout", "-q", "--detach", "FETCH_HEAD")
        ailleurs = self.commit(self.source, "ailleurs.txt", "x")
        _git(
            self.source,
            "push",
            "-q",
            self.fork,
            f"{ailleurs}:refs/heads/ailleurs",
        )
        self.assertIsNone(repo_apply.sha_de(self.clone, ailleurs))
        plan = repo_apply.plan_publication(self.clone, res)
        self.assertEqual(plan["a_retenir"], [ancien])

    def test_distant_avance_apres_la_passe_refuse(self):
        """Un tiers pousse sur la branche du fork après la passe, et le
        clone le rapatrie : le suivi n'est plus le relevé de la passe."""
        res = self.rebase_publiable()
        ancien = self.distant()
        _git(self.source, "fetch", "-q", self.fork, self.REVISION)
        _git(self.source, "checkout", "-q", "--detach", "FETCH_HEAD")
        tiers = self.commit(self.source, "tiers.txt", "tiers")
        _git(self.source, "push", "-q", self.fork, f"HEAD:{self.REVISION}")
        _git(self.clone, "fetch", "-q", self.REMOTE)
        plan = repo_apply.plan_publication(self.clone, res)
        self.assertTrue(plan["refus"])
        self.assertEqual(plan["ancien"], ancien)
        self.assertEqual(plan["a_retenir"], [])
        _out, _err, code = repo_apply.publier(self.clone, plan)
        self.assertEqual(code, 1)
        self.assertEqual(self.distant(), tiers)
        # Le même plan, sans son refus : le relevé périmé refuse encore.
        plan["refus"] = None
        _out, _err, code = repo_apply.publier(self.clone, plan)
        self.assertEqual(code, 1)
        self.assertEqual(self.distant(), tiers)

    def test_bail_porte_le_releve_de_la_passe(self):
        res = self.rebase_publiable()
        plan = repo_apply.plan_publication(self.clone, res)
        self.assertEqual(plan["ancien"], res["distant"])
        vues = []
        vrai_git = repo_apply.git

        def espion(args, cwd, delai=None):
            vues.append(list(args))
            if args[0] == "push":
                return "", "", 1
            return vrai_git(args, cwd, delai) if delai else vrai_git(args, cwd)

        with patch.object(repo_apply, "git", espion), patch.object(
            repo_apply, "a_retenir", return_value=[]
        ):
            repo_apply.publier(self.clone, plan)
        push = [a for a in vues if a[0] == "push"][0]
        self.assertIn(
            f"--force-with-lease=refs/heads/{self.REVISION}:{res['distant']}",
            push,
        )

    # ── reconcilier ──

    def passe_en_conflit(self):
        """Une passe enregistrée dont le dépôt bute sur un conflit."""
        _git(self.clone, "checkout", "-q", self.REVISION)
        self.commit(self.clone, "amont.txt", "notre")
        _git(self.clone, "push", "-q", self.REMOTE, f"HEAD:{self.REVISION}")
        _git(self.clone, "checkout", "-q", "--detach")
        self.amont_avance()
        self.fetch_amont()
        res = self.appliquer(self.constat())
        self.assertEqual(res["etat"], "conflit", res["sortie"])
        repo_apply.ecrire_passe(
            self.HORODATAGE, "X.0", [], [res], racine=self.dossier
        )
        return repo_apply.lire_passe(racine=self.dossier)

    def test_rebase_fini_hors_du_menu_devient_publiable(self):
        passe = self.passe_en_conflit()
        _git(self.clone, "checkout", "--theirs", "--", "amont.txt")
        _git(self.clone, "add", "amont.txt")
        _git(self.clone, "-c", "core.editor=true", "rebase", "--continue")
        notes = repo_apply.reconcilier_passe(passe, racine=self.dossier)
        self.assertEqual(
            [(n[1], n[2]) for n in notes], [("conflit", "rebase")]
        )
        lue = repo_apply.lire_passe(racine=self.dossier)["resultats"][0]
        self.assertEqual(lue["etat"], "rebase")
        self.assertEqual(lue["conflits"], [])
        self.assertEqual(lue["arrivee"], _git(self.clone, "rev-parse", "HEAD"))
        self.assertTrue(repo_apply.publiable(lue))

    def test_detache_sur_le_depart_devient_revenu(self):
        passe = self.passe_en_conflit()
        _git(self.clone, "rebase", "--abort")
        _git(
            self.clone,
            "checkout",
            "-q",
            "--detach",
            passe["resultats"][0]["depart"],
        )
        notes = repo_apply.reconcilier_passe(passe, racine=self.dossier)
        self.assertEqual(
            [(n[1], n[2]) for n in notes], [("conflit", "revenu")]
        )
        lue = repo_apply.lire_passe(racine=self.dossier)["resultats"][0]
        self.assertEqual(lue["etat"], "revenu")

    def test_issue_inconnue_laissee_telle_quelle(self):
        """Abandonné hors du menu, le dépôt reste sur la branche datée sans
        l'amont : rien ne dit ce qu'il est devenu."""
        passe = self.passe_en_conflit()
        _git(self.clone, "rebase", "--abort")
        chemin_json = os.path.join(
            repo_apply.dossier_passe(self.HORODATAGE, self.dossier),
            "passe.json",
        )
        avant = os.stat(chemin_json).st_mtime_ns
        notes = repo_apply.reconcilier_passe(passe, racine=self.dossier)
        self.assertEqual([(n[1], n[2]) for n in notes], [("conflit", None)])
        self.assertEqual(os.stat(chemin_json).st_mtime_ns, avant)
        self.assertEqual(
            repo_apply.lire_passe(racine=self.dossier)["resultats"][0]["etat"],
            "conflit",
        )

    def test_rebase_encore_en_cours_ignore(self):
        passe = self.passe_en_conflit()
        self.assertEqual(
            repo_apply.reconcilier_passe(passe, racine=self.dossier), []
        )

    def test_rebase_fini_puis_retour_au_depart_reste_publiable(self):
        """La branche datée porte le rebase même quand HEAD est revenue
        sur le départ : c'est elle que la publication pousse."""
        passe = self.passe_en_conflit()
        _git(self.clone, "checkout", "--theirs", "--", "amont.txt")
        _git(self.clone, "add", "amont.txt")
        _git(self.clone, "-c", "core.editor=true", "rebase", "--continue")
        pointe = _git(self.clone, "rev-parse", "HEAD")
        depart = passe["resultats"][0]["depart"]
        _git(self.clone, "checkout", "-q", "--detach", depart)
        notes = repo_apply.reconcilier_passe(passe, racine=self.dossier)
        self.assertEqual(
            [(n[1], n[2]) for n in notes], [("conflit", "rebase")]
        )
        lue = repo_apply.lire_passe(racine=self.dossier)["resultats"][0]
        self.assertEqual(lue["arrivee"], pointe)
        self.assertTrue(repo_apply.publiable(lue))

    def test_distant_bouge_sans_fetch_refuse_avant_la_retention(self):
        """Le suivi du clone ne voit pas le distant qui a bougé : le plan
        lit le distant et refuse avant de proposer de retenir quoi que ce
        soit, donc aucun tag n'est poussé."""
        res = self.rebase_publiable()
        _git(self.source, "fetch", "-q", self.fork, self.REVISION)
        _git(self.source, "checkout", "-q", "--detach", "FETCH_HEAD")
        tiers = self.commit(self.source, "tiers.txt", "tiers")
        _git(self.source, "push", "-q", self.fork, f"HEAD:{self.REVISION}")
        plan = repo_apply.plan_publication(self.clone, res)
        self.assertTrue(plan["refus"])
        self.assertEqual(plan["a_retenir"], [])
        _out, _err, code = repo_apply.publier(self.clone, plan)
        self.assertEqual(code, 1)
        self.assertEqual(self.distant(), tiers)
        self.assertEqual(_git(self.fork, "tag", "--list"), "")

    def test_bail_rompu_quand_le_distant_a_bouge(self):
        res = self.rebase_publiable()
        ancien = self.distant()
        plan = repo_apply.plan_publication(self.clone, res)
        repo_apply.retenir(self.clone, ancien, self.REMOTE, "tag", "garde")
        # Un tiers publie sur la branche du fork ; le clone ne le sait pas.
        _git(self.source, "fetch", "-q", self.fork, self.REVISION)
        _git(self.source, "checkout", "-q", "--detach", "FETCH_HEAD")
        tiers = self.commit(self.source, "tiers.txt", "tiers")
        _git(self.source, "push", "-q", self.fork, f"HEAD:{self.REVISION}")
        _out, _err, code = repo_apply.publier(self.clone, plan)
        self.assertNotEqual(code, 0)
        self.assertEqual(self.distant(), tiers)


if __name__ == "__main__":
    unittest.main()
