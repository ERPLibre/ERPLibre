#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le healthcheck du TODO : portées, verdicts, commandes notées, sommaire."""

import ast
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from script.todo import healthcheck as h
from script.todo.todo_i18n import TRANSLATIONS, t

RACINE_DEPOT = Path(__file__).resolve().parent.parent
ENV_GIT = {
    "GIT_AUTHOR_NAME": "Essai",
    "GIT_AUTHOR_EMAIL": "essai@exemple.invalid",
    "GIT_COMMITTER_NAME": "Essai",
    "GIT_COMMITTER_EMAIL": "essai@exemple.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}


def git(racine, *args, check=True):
    return subprocess.run(
        ["git", "-C", racine, *args],
        check=check,
        capture_output=True,
        text=True,
    )


def ecrire(racine, chemin, texte):
    complet = os.path.join(racine, chemin)
    os.makedirs(os.path.dirname(complet), exist_ok=True)
    with open(complet, "w", encoding="utf-8") as fh:
        fh.write(texte)


class TestChemin(unittest.TestCase):
    def test_lines_of_each_kind(self):
        cas = {
            "1 .M N... 100644 100644 100644 a b chemin avec espace.py": (
                ".M",
                "chemin avec espace.py",
            ),
            "2 R. N... 100644 100644 100644 a b R100 neuf.py\tvieux.py": (
                "R.",
                "neuf.py",
            ),
            "u UU N... 100644 100644 100644 100644 a b c conflit.py": (
                "UU",
                "conflit.py",
            ),
            "? nouveau fichier.txt": ("??", "nouveau fichier.txt"),
        }
        for ligne, attendu in cas.items():
            with self.subTest(ligne=ligne):
                self.assertEqual(h.chemin_status(ligne), attendu)


@unittest.skipUnless(shutil.which("git"), "git absent")
class DepotJetable(unittest.TestCase):
    """Un dépôt « master » avec un commit, isolé de la config du compte."""

    def setUp(self):
        env = mock.patch.dict(os.environ, ENV_GIT)
        env.start()
        self.addCleanup(env.stop)
        self.racine = tempfile.mkdtemp(prefix="healthcheck_")
        self.addCleanup(shutil.rmtree, self.racine)
        git(self.racine, "init", "-q", "-b", "master")
        ecrire(self.racine, "a.py", "x = 1\n")
        ecrire(self.racine, "b.py", "y = 2\n")
        git(self.racine, "add", ".")
        git(self.racine, "commit", "-q", "-m", "init")

    def ctx(self, **kw):
        ctx = h.Contexte(self.racine, **kw)
        ctx.commencer()
        return ctx


class TestPorteeFichiers(DepotJetable):
    def test_uncommitted_takes_modified_and_new_not_deleted(self):
        ecrire(self.racine, "a.py", "x = 3\n")
        ecrire(self.racine, "neuf.py", "z = 1\n")
        os.remove(os.path.join(self.racine, "b.py"))
        fichiers, raison = self.ctx().fichiers(".", None)
        self.assertIsNone(raison)
        self.assertEqual(sorted(fichiers), ["a.py", "neuf.py"])

    def test_since_master_adds_the_branch_commits(self):
        git(self.racine, "switch", "-q", "-c", "dev/essai")
        ecrire(self.racine, "c.py", "c = 1\n")
        git(self.racine, "add", "c.py")
        git(self.racine, "commit", "-q", "-m", "c")
        ecrire(self.racine, "a.py", "x = 3\n")
        ctx = self.ctx(fichiers=h.FICHIERS_DEPUIS_BASE)
        fichiers, _ = ctx.fichiers(".", None)
        self.assertEqual(sorted(fichiers), ["a.py", "c.py"])
        # La commande notée est celle qu'on peut relancer telle quelle.
        self.assertIn("git -C . merge-base master HEAD", ctx.commandes())

    def test_since_master_without_master_says_why(self):
        git(self.racine, "branch", "-m", "master", "principal")
        fichiers, raison = self.ctx(fichiers=h.FICHIERS_DEPUIS_BASE).fichiers(
            ".", None
        )
        self.assertIsNone(fichiers)
        self.assertIn("master", raison)

    def test_every_tracked_file(self):
        fichiers, _ = self.ctx(fichiers=h.FICHIERS_TOUS).fichiers(".", None)
        self.assertEqual(sorted(fichiers), ["a.py", "b.py"])


class TestVerificationsGit(DepotJetable):
    def test_clean_repository(self):
        ctx = self.ctx()
        self.assertEqual(h.verifier_non_commites(ctx).statut, h.OK)
        self.assertEqual(h.verifier_conflits(ctx).statut, h.OK)

    def test_uncommitted_files_warn_and_name_the_files(self):
        ecrire(self.racine, "a.py", "x = 3\n")
        resultat = h.executer(self.ctx(), h.verifier_non_commites)
        self.assertEqual(resultat.statut, h.ALERTE)
        self.assertIn("   .M a.py", resultat.details)
        self.assertIn(
            "git -C . status --porcelain=v2 --untracked-files=normal",
            resultat.commandes,
        )

    def test_a_merge_conflict_fails(self):
        git(self.racine, "switch", "-q", "-c", "autre")
        ecrire(self.racine, "a.py", "x = 'autre'\n")
        git(self.racine, "commit", "-q", "-am", "autre")
        git(self.racine, "switch", "-q", "master")
        ecrire(self.racine, "a.py", "x = 'master'\n")
        git(self.racine, "commit", "-q", "-am", "master")
        git(self.racine, "merge", "autre", check=False)
        resultat = h.verifier_conflits(self.ctx())
        self.assertEqual(resultat.statut, h.ECHEC)
        self.assertTrue(any("merge" in d for d in resultat.details))
        self.assertIn("   a.py", resultat.details)

    def test_unpushed_commits_against_the_known_remote_refs(self):
        distant = tempfile.mkdtemp(prefix="healthcheck_distant_")
        self.addCleanup(shutil.rmtree, distant)
        git(distant, "init", "-q", "--bare")
        git(self.racine, "remote", "add", "origin", distant)
        git(self.racine, "push", "-q", "-u", "origin", "master")
        self.assertEqual(h.verifier_non_pousses(self.ctx()).statut, h.OK)

        git(self.racine, "commit", "-q", "--allow-empty", "-m", "local")
        git(self.racine, "switch", "-q", "-c", "dev/seule")
        git(self.racine, "commit", "-q", "--allow-empty", "-m", "seule")
        resultat = h.verifier_non_pousses(self.ctx())
        self.assertEqual(resultat.statut, h.ALERTE)
        self.assertIn("ERPLibre : master +1 commits", resultat.details)
        self.assertTrue(
            any(
                d.startswith("ERPLibre : dev/seule +2")
                for d in resultat.details
            )
        )


class TestFormatage(DepotJetable):
    def test_each_context_gets_the_formatters_of_make_format(self):
        ecrire(self.racine, "script/outil.py", "a=1\n")
        ecrire(self.racine, "odoo18.0/addons/depot/m/models.py", "b=1\n")
        appels = []

        def lancer(args, cwd=None, forme=None, delai=None, env=None):
            appels.append(args)
            sortie = ""
            if "black" in args[0]:
                sortie = "would reformat odoo18.0/addons/depot/m/models.py\n"
            return subprocess.CompletedProcess(args, 1, "", sortie)

        ctx = self.ctx()
        with (
            mock.patch.object(ctx, "outil", side_effect=lambda n: f"/bin/{n}"),
            mock.patch.object(h.Contexte, "lancer", side_effect=lancer),
        ):
            # Le relevé des fichiers passe par git, que lancer remplace :
            # la portée se donne donc ici directement.
            with mock.patch.object(
                ctx,
                "fichiers",
                return_value=(
                    ["script/outil.py", "odoo18.0/addons/depot/m/models.py"],
                    None,
                ),
            ):
                resultat = h.verifier_formatage(ctx)
        par_outil = {a[0]: a for a in appels}
        self.assertIn(
            "odoo18.0/addons/depot/m/models.py", par_outil["/bin/black"]
        )
        self.assertNotIn("script/outil.py", par_outil["/bin/black"])
        self.assertIn("-t", par_outil["/bin/black"])
        self.assertIn("script/outil.py", par_outil["/bin/ruff"])
        self.assertEqual(resultat.statut, h.ALERTE)
        self.assertIn(
            "black : odoo18.0/addons/depot/m/models.py", resultat.details
        )

    def test_reported_paths_per_tool(self):
        def sortie(texte):
            return subprocess.CompletedProcess([], 1, "", texte)

        self.assertEqual(
            h.fichiers_fautifs(
                "ruff", sortie("Would reformat: script/x.py\n"), "/r"
            ),
            ["script/x.py"],
        )
        self.assertEqual(
            h.fichiers_fautifs(
                "isort",
                sortie("ERROR: /r/a/b.py Imports are incorrectly sorted\n"),
                "/r",
            ),
            ["a/b.py"],
        )
        self.assertEqual(
            h.fichiers_fautifs(
                "ruff",
                subprocess.CompletedProcess(
                    [], 1, "script/y.py:1:1: I001 [*] Import block\n", ""
                ),
                "/r",
            ),
            ["script/y.py"],
        )

    def test_nothing_in_scope_is_fine(self):
        self.assertEqual(h.verifier_formatage(self.ctx()).statut, h.OK)


@unittest.skipUnless(
    os.access(RACINE_DEPOT / ".venv.erplibre" / "bin" / "mmg", os.X_OK),
    "mmg absent",
)
class TestDocs(DepotJetable):
    BASE = (
        "<!---------------------------->\n"
        "<!-- multilingual suffix: en, fr -->\n"
        "<!-- no suffix: en -->\n"
        "<!---------------------------->\n\n"
        "<!-- [en] -->\n# Title\n\n<!-- [fr] -->\n# Titre\n"
    )

    def ctx(self, **kw):
        ctx = super().ctx(**kw)
        mmg = str(RACINE_DEPOT / ".venv.erplibre" / "bin" / "mmg")
        ctx.outil = lambda nom: mmg if nom == "mmg" else None
        return ctx

    def test_a_stale_generated_file_is_reported_then_cleared(self):
        ecrire(self.racine, "doc/X.base.md", self.BASE)
        ecrire(self.racine, "doc/X.md", "vieux\n")
        ecrire(self.racine, "doc/X.fr.md", "vieux\n")
        resultat = h.verifier_docs(self.ctx())
        self.assertEqual(resultat.statut, h.ALERTE)
        self.assertEqual(resultat.details, ["doc/X.md", "doc/X.fr.md"])
        # Le checkout n'est pas touché par la vérification.
        with open(os.path.join(self.racine, "doc/X.md")) as fh:
            self.assertEqual(fh.read(), "vieux\n")

        subprocess.run(
            [self.ctx().outil("mmg"), "--yes", "doc/X.base.md"],
            cwd=self.racine,
            capture_output=True,
            check=True,
        )
        self.assertEqual(h.verifier_docs(self.ctx()).statut, h.OK)


class TestEnvironnement(unittest.TestCase):
    def ctx_df(self, libre_ko):
        ctx = h.Contexte(tempfile.gettempdir())
        sortie = (
            "Filesystem 1024-blocks Used Available Capacity Mounted on\n"
            f"/dev/x 100 1 {libre_ko} 1% /\n"
        )
        ctx.lancer = lambda *a, **k: subprocess.CompletedProcess(
            [], 0, sortie, ""
        )
        return ctx

    def test_disk_thresholds(self):
        gio = 1024**2
        self.assertEqual(h.verifier_disque(self.ctx_df(20 * gio)).statut, h.OK)
        self.assertEqual(
            h.verifier_disque(self.ctx_df(3 * gio)).statut, h.ALERTE
        )
        self.assertEqual(
            h.verifier_disque(self.ctx_df(gio // 2)).statut, h.ECHEC
        )

    def test_a_stopped_odoo_is_information_not_a_fault(self):
        ctx = h.Contexte(tempfile.gettempdir())
        with mock.patch.object(h, "_port_ouvert", return_value=False):
            self.assertEqual(h.verifier_odoo(ctx).statut, h.INFO)


class TestManifeste(unittest.TestCase):
    """« Addons face au manifeste » sur une sortie de `repo_state` simulée."""

    def ctx_snapshot(self, depots, sales=()):
        """Un Contexte dont `repo_state snapshot` rend `depots` et dont
        `git status` dit modifiés les chemins de `sales`."""
        ctx = h.Contexte(tempfile.gettempdir())
        sortie = json.dumps({"local_manifest": True, "repos": depots})

        def lancer(args, *a, **k):
            if "status" in args:
                chemin = args[args.index("-C") + 1]
                modifie = " M x.py\n" if chemin in sales else ""
                return subprocess.CompletedProcess(args, 0, modifie, "")
            return subprocess.CompletedProcess(args, 0, sortie, "")

        ctx.lancer = lancer
        return ctx

    def test_resolutions_by_kind_of_gap(self):
        def ecart(alignement):
            return {"ahead": None, "behind": None, "alignment": alignement}

        resultat = h.verifier_manifeste(
            self.ctx_snapshot(
                [
                    self.depot("A/retard", "b" * 40, ecart("en_retard")),
                    self.depot(
                        "A/introuvable", "c" * 40, ecart("introuvable")
                    ),
                    self.depot("A/avance", "d" * 40, ecart("en_avance")),
                    self.depot("A/decale", "e" * 40, ecart("decale")),
                    self.depot("A/sale", "f" * 40, ecart("en_retard")),
                    self.depot("A/gel", "a" * 40, ecart("conforme")),
                ],
                sales={"A/sale"},
            )
        )
        par_cle = {r.cle: r for r in resultat.resolutions}
        remettre = par_cle[h.freeze_resolution.REMETTRE]
        self.assertEqual(
            [d["path"] for d in remettre.depots], ["A/retard", "A/introuvable"]
        )
        self.assertIn("2", remettre.libelle)
        self.assertEqual(
            [d["path"] for d in par_cle[h.freeze_resolution.MAJ_GEL].depots],
            ["A/avance"],
        )
        # Le dépôt modifié et l'écart dans les deux sens ne font qu'expliquer.
        explications = [r for r in resultat.resolutions if not r.actionnable]
        self.assertEqual(len(explications), 2)
        texte = "\n".join(l for r in explications for l in r.lignes)
        self.assertIn("A/sale", texte)
        self.assertIn("git -C A/decale log --oneline --left-right", texte)
        self.assertNotIn("A/sale", "\n".join(remettre.lignes))

    def test_no_resolution_when_every_repository_is_on_its_freeze(self):
        resultat = h.verifier_manifeste(
            self.ctx_snapshot(
                [
                    self.depot(
                        "A/gel",
                        "a" * 40,
                        {"ahead": 0, "behind": 0, "alignment": "conforme"},
                    )
                ]
            )
        )
        self.assertEqual(resultat.resolutions, [])

    def depot(self, chemin, gel=None, ecart=None):
        return {
            "path": chemin,
            "state": "conforme",
            "head": "a" * 40,
            "freeze_revision": gel,
            "freeze": ecart,
        }

    def test_a_repository_conforming_to_its_branch_but_off_its_freeze(self):
        resultat = h.verifier_manifeste(
            self.ctx_snapshot(
                [
                    self.depot(
                        "odoo18.0/addons/R_gel",
                        "a" * 40,
                        {"ahead": 0, "behind": 0, "alignment": "conforme"},
                    ),
                    self.depot("odoo18.0/addons/R_sans_gel"),
                    self.depot(
                        "odoo18.0/addons/R_retard",
                        "b" * 40,
                        {"ahead": 0, "behind": 2, "alignment": "en_retard"},
                    ),
                    self.depot(
                        "odoo18.0/addons/R_introuvable",
                        "c" * 40,
                        {
                            "ahead": None,
                            "behind": None,
                            "alignment": "introuvable",
                        },
                    ),
                ]
            )
        )
        self.assertEqual(resultat.statut, h.ALERTE)
        self.assertIn(f"2 {t('off the freeze')}", resultat.resume)
        self.assertEqual(len(resultat.details), 2)
        retard, introuvable = resultat.details
        self.assertIn("odoo18.0/addons/R_retard", retard)
        self.assertIn(t("behind the freeze"), retard)
        self.assertIn("(+0 −2)", retard)
        self.assertIn("odoo18.0/addons/R_introuvable", introuvable)
        self.assertIn(t("frozen commit missing from the clone"), introuvable)
        self.assertNotIn("(+", introuvable)

    def test_a_repository_whose_target_is_its_freeze_shows_once(self):
        depot = self.depot(
            "odoo18.0/addons/R_gele",
            "b" * 40,
            {"ahead": 0, "behind": 1, "alignment": "en_retard"},
        )
        depot.update(state="decale", target="b" * 40)
        resultat = h.verifier_manifeste(self.ctx_snapshot([depot]))
        self.assertEqual(resultat.statut, h.ALERTE)
        self.assertEqual(resultat.details, ["decale : odoo18.0/addons/R_gele"])
        self.assertNotIn(t("off the freeze"), resultat.resume)

    def test_ahead_and_diverged_repositories_are_named_with_their_gap(self):
        avance = self.depot("odoo18.0/addons/R_avance")
        avance.update(state="en_avance", ahead=2, behind=0)
        decale = self.depot("odoo18.0/addons/R_decale")
        decale.update(state="decale", ahead=1, behind=3)
        resultat = h.verifier_manifeste(self.ctx_snapshot([avance, decale]))
        self.assertEqual(resultat.statut, h.ALERTE)
        self.assertEqual(
            resultat.details,
            [
                "en_avance : odoo18.0/addons/R_avance (+2 −0)",
                "decale : odoo18.0/addons/R_decale (+1 −3)",
            ],
        )

    def ctx_gele(self, depots, mode="frozen"):
        ctx = h.Contexte(tempfile.gettempdir())
        ctx.snapshot = lambda: (
            {"local_manifest": True, "mode": mode, "repos": depots},
            "",
        )
        ctx.lancer = lambda args, *a, **k: subprocess.CompletedProcess(
            args, 0, "", ""
        )
        return ctx

    def depot_perime(self):
        # La cible locale est l'ancien gel ; HEAD est sur le gel actuel.
        depot = self.depot(
            "odoo18.0/addons/R_perime",
            "b" * 40,
            {"ahead": 0, "behind": 0, "alignment": "conforme"},
        )
        depot.update(
            state="en_avance",
            revision="a" * 40,
            target="a" * 40,
            head="b" * 40,
            ahead=1,
            behind=0,
        )
        return depot

    def test_a_stale_local_manifest_is_named_not_counted_ahead(self):
        resultat = h.verifier_manifeste(self.ctx_gele([self.depot_perime()]))
        self.assertEqual(resultat.statut, h.ALERTE)
        self.assertIn(f"1 {t('stale local manifest')}", resultat.resume)
        self.assertNotIn("en_avance", resultat.resume)
        (ligne,) = resultat.details
        self.assertIn("odoo18.0/addons/R_perime", ligne)
        self.assertIn("aaaaaaaaaa", ligne)
        self.assertIn("bbbbbbbbbb", ligne)
        (resolution,) = resultat.resolutions
        self.assertEqual(resolution.cle, h.REGENERER)
        self.assertIn(h.COMMANDE_REGENERER, resolution.libelle)

    def test_a_branch_checkout_is_never_stale(self):
        depot = self.depot_perime()
        depot["revision"] = "18.0"
        resultat = h.verifier_manifeste(
            self.ctx_gele([depot], mode="branches")
        )
        self.assertNotIn(t("stale local manifest"), resultat.resume)
        self.assertIn("1 en_avance", resultat.resume)

    def test_regenerating_asks_first_and_shows_the_command(self):
        ctx = h.Contexte(tempfile.gettempdir())
        lances, lignes = [], []

        def lancer(commande):
            lances.append(commande)
            return 0

        self.assertFalse(
            h._regenerer_manifeste(
                ctx, [{}], lambda _q: "", lignes.append, lancer=lancer
            )
        )
        self.assertEqual(lances, [])
        self.assertTrue(
            h._regenerer_manifeste(
                ctx, [{}], lambda _q: "o", lignes.append, lancer=lancer
            )
        )
        self.assertEqual(lances, [h.COMMANDE_REGENERER])
        self.assertIn(f"   $ {h.COMMANDE_REGENERER}", lignes)

    def test_every_repository_on_its_freeze_is_fine(self):
        resultat = h.verifier_manifeste(
            self.ctx_snapshot(
                [
                    self.depot(
                        "odoo18.0/addons/R_gel",
                        "a" * 40,
                        {"ahead": 0, "behind": 0, "alignment": "conforme"},
                    ),
                    self.depot("odoo18.0/addons/R_sans_gel"),
                ]
            )
        )
        self.assertEqual(resultat.statut, h.OK)
        self.assertEqual(resultat.resume, "2 conforme")


class TestBranches(unittest.TestCase):
    """« Branches des dépôts » sur un vrai dépôt jetable."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.racine = tmp.name
        self.chemin = "odoo18.0/addons/R_branches"
        clone = os.path.join(self.racine, self.chemin)
        os.makedirs(clone)
        env = {**os.environ, **ENV_GIT}

        def g(*args):
            return subprocess.run(
                ["git", "-C", clone, *args],
                env=env,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()

        self.g = g
        g("init", "-q", "-b", "18.0")
        for nom in ("un", "deux"):
            ecrire(clone, f"{nom}.txt", nom)
            g("add", ".")
            g("commit", "-q", "-m", nom)
        self.head = g("rev-parse", "HEAD")

    def verifier(self):
        ctx = h.Contexte(self.racine)
        ctx.snapshot = lambda: (
            {"repos": [{"path": self.chemin, "head": self.head}]},
            "",
        )
        return h.verifier_branches(ctx)

    def test_branch_on_head_is_fine(self):
        resultat = self.verifier()
        self.assertEqual(resultat.statut, h.OK)
        self.assertIn(t("no local branch off HEAD"), resultat.resume)

    def test_a_branch_with_commits_head_lacks_is_flagged(self):
        self.g("checkout", "-q", "-b", "travail")
        ecrire(os.path.join(self.racine, self.chemin), "trois.txt", "trois")
        self.g("add", ".")
        self.g("commit", "-q", "-m", "trois")
        self.g("checkout", "-q", "--detach", self.head)
        self.g("branch", "vieille", "HEAD~1")
        resultat = self.verifier()
        self.assertEqual(resultat.statut, h.ALERTE)
        self.assertIn(f"{self.chemin} : travail (+1 −0)", resultat.details)
        self.assertIn(f"{self.chemin} : vieille (+0 −1)", resultat.details)

    def test_a_branch_only_behind_head_is_information(self):
        self.g("branch", "vieille", "HEAD~1")
        resultat = self.verifier()
        self.assertEqual(resultat.statut, h.INFO)
        self.assertEqual(
            resultat.details, [f"{self.chemin} : vieille (+0 −1)"]
        )


class TestResolutions(unittest.TestCase):
    """Le bloc « Résolution » et l'exécution confirmée."""

    def resolution(self, cle, depots):
        return h.Resolution(cle, "🧊 X", ["explication"], depots)

    def test_the_report_explains_and_announces_the_menu_entries(self):
        res = self.resolution(h.freeze_resolution.REMETTRE, [])

        def verifier_manifeste(_ctx):
            return h.Resultat("M", h.ALERTE, "", resolutions=[res])

        lignes = []
        h.lancer(
            h.Contexte(tempfile.gettempdir()),
            [("code", verifier_manifeste)],
            sortie=lignes.append,
        )
        texte = "\n".join(lignes)
        self.assertIn(f"── {t('Resolution')} ──", texte)
        self.assertLess(
            texte.index(t("Summary")), texte.index(t("Resolution"))
        )
        self.assertIn("explication", texte)
        self.assertIn(f"{t('Menu entry:')} 🧊 X", texte)
        self.assertIn(
            t("These entries now appear in the menu, under Resolution."), texte
        )

    def test_selection_by_numbers_ranges_all_or_back(self):
        depots = [
            {"path": f"A/{n}", "freeze": {"alignment": "en_retard"}}
            for n in ("un", "deux", "trois")
        ]

        def choisir(*reponses):
            suite = iter(reponses)
            lignes = []
            choisis = h.choisir_depots(
                depots, lambda _q: next(suite), lignes.append
            )
            return [d["path"] for d in choisis], lignes

        self.assertEqual(choisir("1 3")[0], ["A/un", "A/trois"])
        self.assertEqual(choisir("3,1")[0], ["A/un", "A/trois"])
        self.assertEqual(choisir("2-3")[0], ["A/deux", "A/trois"])
        self.assertEqual(choisir("a")[0], ["A/un", "A/deux", "A/trois"])
        self.assertEqual(choisir("0")[0], [])
        self.assertEqual(choisir("")[0], [])
        # Une partie fautive refuse toute la saisie, qui est redemandée.
        choisis, lignes = choisir("1 9", "2")
        self.assertEqual(choisis, ["A/deux"])
        self.assertIn(f"{t('Error, cannot understand value')} '1 9'", lignes)
        self.assertIn("   [1] A/un — " + t("behind the freeze"), lignes)
        self.assertIn(f"   [a] {t('All repositories')}", lignes)

    def test_put_back_asks_first(self):
        depots = [{"path": "A/x", "freeze": {"alignment": "en_retard"}}]
        res = self.resolution(h.freeze_resolution.REMETTRE, depots)
        ctx = h.Contexte(tempfile.gettempdir())
        with mock.patch.object(
            h.freeze_resolution, "remettre_au_gel", return_value=(True, "ok")
        ) as remettre:
            self.assertFalse(
                h.executer_resolution(
                    ctx, res, demander=lambda _q: "", sortie=lambda _l: None
                )
            )
            remettre.assert_not_called()
            self.assertTrue(
                h.executer_resolution(
                    ctx, res, demander=lambda _q: "1", sortie=lambda _l: None
                )
            )
            remettre.assert_called_once()
            self.assertEqual(remettre.call_args.args, (ctx.racine, depots[0]))

    def test_the_commands_show_as_they_run(self):
        depots = [{"path": "A/x", "freeze": {"alignment": "en_retard"}}]
        res = self.resolution(h.freeze_resolution.REMETTRE, depots)

        def remettre(_racine, _depot, noter):
            noter("git -C A/x checkout --quiet --detach abc")
            return True, "abc"

        lignes = []
        with mock.patch.object(
            h.freeze_resolution, "remettre_au_gel", side_effect=remettre
        ):
            h.executer_resolution(
                h.Contexte(tempfile.gettempdir()),
                res,
                demander=lambda _q: "a",
                sortie=lignes.append,
            )
        commande = lignes.index(
            "   $ git -C A/x checkout --quiet --detach abc"
        )
        self.assertLess(commande, lignes.index("   ✅ A/x — abc"))

    def test_end_of_input_means_no(self):
        res = self.resolution(
            h.freeze_resolution.REMETTRE,
            [{"path": "A/x", "freeze": {"alignment": "en_retard"}}],
        )

        def fin(_question):
            raise EOFError

        with mock.patch.object(
            h.freeze_resolution, "remettre_au_gel"
        ) as remettre:
            self.assertFalse(
                h.executer_resolution(
                    h.Contexte(tempfile.gettempdir()),
                    res,
                    demander=fin,
                    sortie=lambda _l: None,
                )
            )
        remettre.assert_not_called()

    def test_freeze_update_writes_only_pushed_heads(self):
        publie = {"path": "A/publie", "freeze": {"alignment": "en_avance"}}
        local = {"path": "A/local", "freeze": {"alignment": "en_avance"}}
        res = self.resolution(h.freeze_resolution.MAJ_GEL, [publie, local])
        ctx = h.Contexte(tempfile.gettempdir())
        lignes = []
        with (
            mock.patch.object(
                h.freeze_resolution,
                "publication",
                side_effect=[(True, "18.0"), (False, "git push x")],
            ),
            mock.patch.object(
                h.freeze_resolution,
                "mettre_a_jour_gel",
                return_value=({"manifest/m.xml": ["k"]}, []),
            ) as maj,
        ):
            change = h.executer_resolution(
                ctx, res, demander=lambda _q: "a", sortie=lignes.append
            )
        self.assertTrue(change)
        self.assertEqual(maj.call_args_list[-1].args[1], [publie])
        self.assertIn("git push x", "\n".join(lignes))


class TestDependancesVenvs(unittest.TestCase):
    """« Dépendances des venvs » : chaque venv face à son lock ou à ses
    exigences, Poetry et l'analyse remplacés."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.racine = tmp.name
        self.version = "odoo18.0_python3.12.16"
        ecrire(self.racine, ".erplibre-version", self.version + "\n")
        for f in (
            f".venv.{self.version}/bin/poetry",
            f"requirement/poetry.{self.version}.lock",
        ):
            ecrire(self.racine, f, "")
        self.venvs = [
            {
                "venv": f".venv.{self.version}",
                "genre": "odoo",
                "version": self.version,
                "active": True,
            },
            {
                "venv": ".venv.erplibre",
                "genre": "outillage",
                "version": None,
                "active": False,
            },
        ]

    def verifier(self, simulation, analyse):
        ctx = h.Contexte(self.racine)
        ctx.lancer = lambda *a, **k: subprocess.CompletedProcess(
            [], 0, json.dumps(analyse), ""
        )
        with (
            mock.patch.object(h.drift, "venvs", return_value=self.venvs),
            mock.patch.object(h.drift, "simuler", return_value=simulation),
        ):
            return h.verifier_dependances_venvs(ctx)

    def simulation(self, texte):
        return {
            "ok": True,
            "operations": h.drift.lire_operations(texte),
            "sortie": texte,
            "commande": "poetry sync --dry-run",
        }

    ANALYSE_OK = {
        "exigences": 3,
        "manquantes": [],
        "hors_bornes": [],
        "illisibles": [],
        "de_trop": [],
    }

    def test_every_venv_aligned_is_fine(self):
        resultat = self.verifier(self.simulation(""), self.ANALYSE_OK)
        self.assertEqual(resultat.statut, h.OK)
        self.assertEqual(resultat.resume, "2 venvs")
        self.assertEqual(resultat.resolutions, [])

    def test_gaps_are_listed_and_offered_to_the_resolution(self):
        analyse = dict(self.ANALYSE_OK, manquantes=["absent>=1"])
        resultat = self.verifier(
            self.simulation(
                "  - Updating requests (2.31.0 -> 2.32.3)\n"
                "  - Removing poetry (2.1.3)\n"
            ),
            analyse,
        )
        self.assertEqual(resultat.statut, h.ALERTE)
        self.assertIn(f"2 {t('to update')}", resultat.resume)
        texte = "\n".join(resultat.details)
        self.assertIn("requests 2.31.0 → 2.32.3", texte)
        self.assertIn("absent>=1", texte)
        self.assertIn(f"1 {t('outside the lock')}", texte)
        (resolution,) = resultat.resolutions
        self.assertEqual(resolution.cle, h.MAJ_VENVS)
        self.assertEqual(
            [c["venv"] for c in resolution.depots],
            [f".venv.{self.version}", ".venv.erplibre"],
        )

    def test_the_resolution_updates_the_chosen_venvs(self):
        choix = [
            {"venv": ".venv.a", "resume": "1 écart"},
            {"venv": ".venv.b", "resume": "2 écarts"},
        ]
        res = h.Resolution(h.MAJ_VENVS, "📦 X", [], choix)
        mis_a_jour = []
        change = h.executer_resolution(
            h.Contexte(tempfile.gettempdir()),
            res,
            demander=lambda _q: "2",
            sortie=lambda _l: None,
            mettre_a_jour_venv=mis_a_jour.append,
        )
        self.assertTrue(change)
        self.assertEqual(mis_a_jour, [choix[1]])

    def test_a_venv_missing_from_the_catalogue_is_obsolete(self):
        ecrire(
            self.racine,
            "conf/supported_version_erplibre.json",
            json.dumps({self.version: {}}),
        )
        ancien = "odoo18.0_python3.12.10"
        self.venvs[0] = dict(
            self.venvs[0], venv=f".venv.{ancien}", version=ancien
        )
        resultat = self.verifier(self.simulation(""), self.ANALYSE_OK)
        self.assertEqual(resultat.statut, h.ALERTE)
        self.assertIn(f"1 {t('obsolete')}", resultat.resume)
        self.assertNotIn(t("unreadable"), resultat.resume)
        (resolution,) = resultat.resolutions
        self.assertEqual(resolution.cle, h.VENVS_OBSOLETES)
        self.assertEqual(resolution.depots[0]["remplacant"], self.version)

    def test_the_replacement_is_the_newest_python_of_that_odoo(self):
        cles = {
            "odoo18.0_python3.12.9",
            "odoo18.0_python3.12.16",
            "odoo17.0_python3.10.18",
        }
        self.assertEqual(
            h.remplacant("odoo18.0_python3.12.10", cles),
            "odoo18.0_python3.12.16",
        )
        self.assertIsNone(h.remplacant("odoo11.0_python3.7.17", cles))

    def test_packages_nothing_requires_are_offered_for_removal(self):
        analyse = dict(self.ANALYSE_OK, de_trop=[["agithub", "2.2.2"]])
        resultat = self.verifier(self.simulation(""), analyse)
        self.assertEqual(resultat.statut, h.INFO)
        (resolution,) = resultat.resolutions
        self.assertEqual(resolution.cle, h.PAQUETS_DE_TROP)
        self.assertEqual(
            resolution.depots,
            [
                {
                    "venv": ".venv.erplibre",
                    "paquet": "agithub",
                    "version": "2.2.2",
                }
            ],
        )

    def test_removing_packages_runs_one_pip_for_the_chosen_ones(self):
        paquets = [
            {"venv": ".venv.erplibre", "paquet": p, "version": "1"}
            for p in ("agithub", "cssselect", "giturlparse")
        ]
        lances, lignes = [], []
        change = h._retirer_paquets(
            h.Contexte(self.racine),
            paquets,
            lambda _q: "1 3",
            lignes.append,
            lancer=lambda c: lances.append(c) or 0,
        )
        self.assertTrue(change)
        self.assertEqual(
            lances,
            [
                [
                    ".venv.erplibre/bin/python",
                    "-m",
                    "pip",
                    "uninstall",
                    "-y",
                    "agithub",
                    "giturlparse",
                ]
            ],
        )
        self.assertIn(
            "   $ .venv.erplibre/bin/python -m pip uninstall -y agithub giturlparse",
            lignes,
        )

    def obsolete(self):
        ancien = f"{self.racine}/.venv.odoo18.0_python3.12.10"
        os.makedirs(os.path.join(ancien, "bin"))
        return ancien, [
            {
                "venv": ".venv.odoo18.0_python3.12.10",
                "remplacant": self.version,
            }
        ]

    def test_a_missing_replacement_is_installed_then_the_old_venv_deleted(
        self,
    ):
        shutil.rmtree(os.path.join(self.racine, f".venv.{self.version}"))
        ancien, venvs = self.obsolete()
        reponses = iter(["a", "o", "o"])
        lances = []
        change = h._remplacer_venvs_obsoletes(
            h.Contexte(self.racine),
            venvs,
            lambda _q: next(reponses),
            lambda _l: None,
            lancer=lambda c: lances.append(c) or 0,
        )
        self.assertTrue(change)
        self.assertEqual(
            lances,
            [
                [
                    "./script/version/update_env_version.py",
                    "--erplibre_version",
                    self.version,
                    "--install_dev",
                ]
            ],
        )
        self.assertFalse(os.path.isdir(ancien))

    def test_a_refused_installation_keeps_the_obsolete_venv(self):
        shutil.rmtree(os.path.join(self.racine, f".venv.{self.version}"))
        ancien, venvs = self.obsolete()
        reponses = iter(["a", ""])
        lances = []
        self.assertFalse(
            h._remplacer_venvs_obsoletes(
                h.Contexte(self.racine),
                venvs,
                lambda _q: next(reponses),
                lambda _l: None,
                lancer=lambda c: lances.append(c) or 0,
            )
        )
        self.assertEqual(lances, [])
        self.assertTrue(os.path.isdir(ancien))

    def test_an_existing_replacement_only_asks_to_delete(self):
        ancien, venvs = self.obsolete()
        reponses = iter(["1", "o"])
        lances = []
        self.assertTrue(
            h._remplacer_venvs_obsoletes(
                h.Contexte(self.racine),
                venvs,
                lambda _q: next(reponses),
                lambda _l: None,
                lancer=lambda c: lances.append(c) or 0,
            )
        )
        self.assertEqual(lances, [])
        self.assertFalse(os.path.isdir(ancien))


class TestRapport(unittest.TestCase):
    def test_a_crashing_check_fails_under_its_title(self):
        def verifier_conflits(_ctx):
            raise RuntimeError("boum")

        ctx = h.Contexte(tempfile.gettempdir())
        resultat = h.executer(ctx, verifier_conflits)
        self.assertEqual(resultat.statut, h.ECHEC)
        self.assertEqual(resultat.titre, h.titre(h.verifier_conflits))
        self.assertIn("boum", resultat.resume)

    def test_each_block_shows_its_commands_and_the_summary_counts(self):
        def verifier_disque(ctx):
            ctx.noter("df -Pk .")
            return h.Resultat("D", h.ALERTE, "peu")

        def verifier_odoo(ctx):
            ctx.noter("python3 -c x")
            ctx.noter("python3 -c x")
            return h.Resultat("O", h.OK, "bien")

        lignes = []
        h.lancer(
            h.Contexte(tempfile.gettempdir()),
            [
                ("environnement", verifier_disque),
                ("environnement", verifier_odoo),
            ],
            sortie=lignes.append,
        )
        texte = "\n".join(lignes)
        self.assertIn("   $ df -Pk .", texte)
        self.assertIn("   $ python3 -c x   (×2)", texte)
        self.assertIn("1 ✅ · 1 ⚠️", texte)
        # L'icône du titre vit dans sa traduction : le code n'en ajoute pas.
        from script.todo.todo_i18n import t

        self.assertTrue(lignes[0].startswith(f"{t('Healthcheck')} — "))
        self.assertNotIn("🩺 🩺", lignes[0])

    def test_failures_then_warnings_are_repeated_above_the_summary(self):
        def verifier_conflits(ctx):
            ctx.noter("git status")
            return h.Resultat("C", h.ALERTE, "conflit", ["fichier.py"])

        def verifier_disque(_ctx):
            return h.Resultat("D", h.OK, "assez")

        def verifier_odoo(_ctx):
            return h.Resultat("O", h.ECHEC, "plantage", ["trace"])

        lignes = []
        h.lancer(
            h.Contexte(tempfile.gettempdir()),
            [
                ("code", verifier_conflits),
                ("environnement", verifier_disque),
                ("environnement", verifier_odoo),
            ],
            sortie=lignes.append,
        )
        texte = "\n".join(lignes)
        attention = texte.index(f"── ⚠️  {t('Attention')} ──")
        resume = texte.index(f"── {t('Summary')} ──")
        self.assertLess(attention, resume)
        bloc = texte[attention:resume]
        # Le détail est celui du rapport, commandes comprises, l'échec en
        # premier ; une vérification qui va bien n'y figure pas.
        self.assertLess(bloc.index("── O ──"), bloc.index("── C ──"))
        self.assertIn("   $ git status", bloc)
        self.assertIn("      fichier.py", bloc)
        self.assertIn("      trace", bloc)
        self.assertNotIn("── D ──", bloc)
        self.assertEqual(texte.count("      fichier.py"), 2)

    def test_no_attention_block_when_everything_is_fine(self):
        lignes = []
        h.lancer(
            h.Contexte(tempfile.gettempdir()),
            [("environnement", lambda _ctx: h.Resultat("D", h.OK, "assez"))],
            sortie=lignes.append,
        )
        self.assertNotIn(t("Attention"), "\n".join(lignes))


class TestParallele(unittest.TestCase):
    """« Tout vérifier » lance les vérifications en parallèle et affiche
    leurs blocs, et leurs commandes, toujours dans le même ordre."""

    def test_checks_run_together_and_print_in_list_order(self):
        import threading

        signal = threading.Event()

        def verifier_disque(ctx):
            # Bloquerait jusqu'au délai si la suivante ne tournait pas en
            # même temps.
            ctx.noter("attend")
            self.assertTrue(signal.wait(timeout=10))
            return h.Resultat("D", h.OK, "premier")

        def verifier_odoo(ctx):
            ctx.noter("signale")
            signal.set()
            return h.Resultat("O", h.OK, "second")

        lignes = []
        h.lancer(
            h.Contexte(tempfile.gettempdir()),
            [
                ("environnement", verifier_disque),
                ("environnement", verifier_odoo),
            ],
            sortie=lignes.append,
        )
        texte = "\n".join(lignes)
        self.assertLess(texte.index("premier"), texte.index("second"))
        # Chaque bloc ne porte que ses propres commandes.
        bloc_d = texte[texte.index("── D ──") : texte.index("── O ──")]
        self.assertIn("$ attend", bloc_d)
        self.assertNotIn("signale", bloc_d)

    def test_commands_of_parallel_items_keep_the_items_order(self):
        import time

        ctx = h.Contexte(tempfile.gettempdir())
        ctx.commencer()

        def examiner(rang):
            # Le premier élément finit le dernier.
            time.sleep(0.05 * (3 - rang))
            ctx.noter(f"commande {rang}")
            return rang

        self.assertEqual(ctx.en_parallele(examiner, [0, 1, 2]), [0, 1, 2])
        self.assertEqual(
            ctx.commandes(), ["commande 0", "commande 1", "commande 2"]
        )


class TestHooks(DepotJetable):
    """Des hooks git absents, inertes ou pointés ailleurs : la vérification
    offre de les installer, la résolution les pose."""

    def setUp(self):
        super().setUp()
        for hook in h.todo_etat.HOOKS_GIT:
            ecrire(self.racine, f"script/git/hooks/{hook}", "#!/bin/sh\n")

    def hooks_path(self):
        return git(
            self.racine, "config", "--get", "core.hooksPath", check=False
        ).stdout.strip()

    def test_missing_hooks_offer_their_installation(self):
        resultat = h.verifier_hooks(self.ctx())
        self.assertEqual(resultat.statut, h.ALERTE)
        self.assertEqual([r.cle for r in resultat.resolutions], [h.HOOKS_GIT])

    def test_missing_hooks_are_found_silently_at_menu_opening(self):
        """La passe d'ouverture du menu trouve les hooks manquants sans
        rien afficher."""
        self.assertIn(h.verifier_hooks, h.VERIFICATIONS_IMMEDIATES)
        with mock.patch("builtins.print") as imprime:
            resultats = h.verifier_en_silence(self.ctx(), [h.verifier_hooks])
        imprime.assert_not_called()
        self.assertEqual(
            [r.cle for r in resultats[0].resolutions], [h.HOOKS_GIT]
        )

    def test_installed_hooks_offer_nothing(self):
        for hook in h.todo_etat.HOOKS_GIT:
            os.chmod(
                os.path.join(self.racine, "script/git/hooks", hook), 0o755
            )
        git(self.racine, "config", "core.hooksPath", "script/git/hooks")
        resultat = h.verifier_hooks(self.ctx())
        self.assertEqual(resultat.statut, h.OK)
        self.assertEqual(resultat.resolutions, [])

    def test_the_resolution_sets_the_path_and_the_execution_bits(self):
        lignes = []
        resolution = h.verifier_hooks(self.ctx()).resolutions[0]
        self.assertTrue(
            h.executer_resolution(
                self.ctx(), resolution, lambda _q: "", lignes.append
            )
        )
        self.assertEqual(self.hooks_path(), "script/git/hooks")
        for hook in h.todo_etat.HOOKS_GIT:
            self.assertTrue(
                os.access(
                    os.path.join(self.racine, "script/git/hooks", hook),
                    os.X_OK,
                )
            )
        self.assertIn(
            "   $ git -C . config core.hooksPath script/git/hooks", lignes
        )
        self.assertEqual(h.verifier_hooks(self.ctx()).statut, h.OK)

    def test_an_absolute_path_to_the_same_hooks_needs_no_resolution(self):
        for hook in h.todo_etat.HOOKS_GIT:
            os.chmod(
                os.path.join(self.racine, "script/git/hooks", hook), 0o755
            )
        git(
            self.racine,
            "config",
            "core.hooksPath",
            os.path.join(self.racine, "script/git/hooks"),
        )
        resultat = h.verifier_hooks(self.ctx())
        self.assertEqual(resultat.statut, h.OK)
        self.assertEqual(resultat.resolutions, [])

    def test_another_hooks_path_is_replaced_only_on_a_yes(self):
        git(self.racine, "config", "core.hooksPath", "ailleurs/hooks")
        resolution = h.verifier_hooks(self.ctx()).resolutions[0]
        self.assertFalse(
            h.executer_resolution(self.ctx(), resolution, lambda _q: "", print)
        )
        self.assertEqual(self.hooks_path(), "ailleurs/hooks")
        with mock.patch("builtins.print"):
            self.assertTrue(
                h.executer_resolution(
                    self.ctx(), resolution, lambda _q: "o", print
                )
            )
        self.assertEqual(self.hooks_path(), "script/git/hooks")


class TestCommandesClaude(unittest.TestCase):
    """Les commandes Claude manquantes ou périmées : offertes au
    déploiement, sans jamais écrire dans le vrai ~/.claude."""

    COMMANDES = {"commit": "gabarit_commit.md", "autre": "gabarit_autre.md"}

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = os.path.join(tmp.name, "home")
        os.makedirs(self.home)
        env = mock.patch.dict(os.environ, {"HOME": self.home})
        env.start()
        self.addCleanup(env.stop)
        sans_claude = mock.patch.object(h.shutil, "which", return_value=None)
        sans_claude.start()
        self.addCleanup(sans_claude.stop)
        self.racine = os.path.join(tmp.name, "depot")
        for gabarit in self.COMMANDES.values():
            ecrire(self.racine, f"conf/{gabarit}", gabarit)

    def ctx(self):
        def etat(deploye, gabarit):
            if not os.path.isfile(deploye):
                return t("missing")
            with open(deploye) as a, open(gabarit) as b:
                return (
                    t("up to date")
                    if a.read() == b.read()
                    else t("redeploy needed")
                )

        return h.Contexte(
            self.racine,
            etat_commande_claude=etat,
            commandes_claude=self.COMMANDES,
        )

    def test_without_claude_code_the_check_is_skipped(self):
        self.assertEqual(
            h.verifier_commandes_claude(self.ctx()).statut, h.SAUTE
        )

    def test_claude_code_without_its_commands_offers_them_all(self):
        os.makedirs(os.path.join(self.home, ".claude"))
        resultat = h.verifier_commandes_claude(self.ctx())
        self.assertEqual(resultat.statut, h.ALERTE)
        (resolution,) = resultat.resolutions
        self.assertEqual(resolution.cle, h.CLAUDE)
        self.assertEqual(
            sorted(c["commande"] for c in resolution.depots),
            ["autre", "commit"],
        )

    def test_only_the_stale_command_is_offered(self):
        commandes = os.path.join(self.home, ".claude", "commands")
        ecrire(commandes, "commit.md", "gabarit_commit.md")
        ecrire(commandes, "autre.md", "ancienne copie")
        (resolution,) = h.verifier_commandes_claude(self.ctx()).resolutions
        self.assertEqual(
            [(c["commande"], c["etat"]) for c in resolution.depots],
            [("autre", t("redeploy needed"))],
        )

    def test_every_command_up_to_date_offers_nothing(self):
        commandes = os.path.join(self.home, ".claude", "commands")
        for commande, gabarit in self.COMMANDES.items():
            ecrire(commandes, f"{commande}.md", gabarit)
        resultat = h.verifier_commandes_claude(self.ctx())
        self.assertEqual(resultat.statut, h.OK)
        self.assertEqual(resultat.resolutions, [])

    def test_the_resolution_deploys_the_chosen_commands_only(self):
        os.makedirs(os.path.join(self.home, ".claude"))
        (resolution,) = h.verifier_commandes_claude(self.ctx()).resolutions
        deployees = []

        def deployer(commande, gabarit):
            deployees.append((commande, gabarit))
            return True

        with mock.patch("builtins.print"):
            self.assertFalse(
                h.executer_resolution(
                    self.ctx(),
                    resolution,
                    lambda _q: "0",
                    print,
                    deployer_commande_claude=deployer,
                )
            )
            self.assertEqual(deployees, [])
            self.assertTrue(
                h.executer_resolution(
                    self.ctx(),
                    resolution,
                    lambda _q: "a",
                    print,
                    deployer_commande_claude=deployer,
                )
            )
        self.assertEqual(
            sorted(deployees),
            [("autre", "gabarit_autre.md"), ("commit", "gabarit_commit.md")],
        )


class TestTraductions(unittest.TestCase):
    """Chaque libellé du healthcheck a sa traduction : une clé absente
    s'afficherait en anglais dans un TODO en français."""

    def test_every_key_is_translated(self):
        source = (RACINE_DEPOT / "script/todo/healthcheck.py").read_text()
        cles = {
            n.args[0].value
            for n in ast.walk(ast.parse(source))
            if isinstance(n, ast.Call)
            and getattr(n.func, "id", None) == "t"
            and n.args
            and isinstance(n.args[0], ast.Constant)
        }
        cles |= set(h.TITRES.values())
        cles |= set(h.LIBELLES_FICHIERS.values())
        cles |= set(h.LIBELLES_DEPOTS.values())
        cles |= set(h.SECTIONS.values())
        cles |= set(h.ECARTS_GEL.values())
        cles.discard("PostgreSQL")
        self.assertEqual(sorted(cles - set(TRANSLATIONS)), [])

    def test_every_check_has_a_title(self):
        for _section, verification in h.VERIFICATIONS:
            self.assertIn(verification.__name__, h.TITRES)

    def test_every_check_has_a_one_code_point_icon(self):
        """Le sommaire aligne par len() : une icône suivie d'un sélecteur
        de variante (U+FE0F) compterait deux et décalerait sa ligne."""
        for _section, verification in h.VERIFICATIONS:
            icone = h.ICONES_VERIFICATIONS[verification.__name__]
            self.assertEqual(len(icone), 1, verification.__name__)
            self.assertTrue(h.titre(verification).startswith(f"{icone} "))


class TestImmediates(unittest.TestCase):
    def test_immediate_checks_belong_to_the_healthcheck(self):
        """Une vérification immédiate est aussi une vérification du
        bilan : sa résolution repasse par elle, et une passe la remplace."""
        toutes = {v for _s, v in h.VERIFICATIONS}
        for verification in h.VERIFICATIONS_IMMEDIATES:
            self.assertIn(verification, toutes)

    def test_a_failing_immediate_check_does_not_raise(self):
        def casse(ctx):
            raise RuntimeError("boom")

        casse.__name__ = "verifier_hooks"
        resultats = h.verifier_en_silence(
            h.Contexte(tempfile.gettempdir()), [casse]
        )
        self.assertEqual(resultats[0].statut, h.ECHEC)
        self.assertEqual(resultats[0].resolutions, [])


class TestMenu(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import sys

        sys.argv = ["todo.py"]
        from script.todo.todo import TODO

        cls.TODO = TODO

    def test_a_resolution_becomes_a_menu_entry_and_reruns_its_check(self):
        obj = self.TODO.__new__(self.TODO)
        obj._claude_context_root = lambda: tempfile.gettempdir()
        res = h.Resolution(h.freeze_resolution.REMETTRE, "🧊 X", [], [])
        manifeste = next(
            (s, v) for s, v in h.VERIFICATIONS if v is h.verifier_manifeste
        )
        appels = []

        def lancer(ctx, v=None):
            appels.append(v)
            return [
                h.Resultat(
                    h.titre(h.verifier_manifeste),
                    h.ALERTE,
                    "",
                    resolutions=[res] if len(appels) == 1 else [],
                )
            ]

        # Juste après l'entrée « Une seule vérification ».
        entree = "5"
        with (
            mock.patch.object(self.TODO, "fill_help_info", return_value=""),
            mock.patch(
                "script.todo.todo.click.prompt",
                side_effect=["1", entree, entree, "0"],
            ),
            mock.patch.object(h, "lancer", side_effect=lancer),
            mock.patch.object(h, "verifier_en_silence", return_value=[]),
            mock.patch.object(h, "executer_resolution") as executer,
        ):
            obj.prompt_healthcheck()
        executer.assert_called_once()
        self.assertIs(executer.call_args.args[1], res)
        # La vérification repasse ; sans résolution, l'entrée disparaît.
        self.assertEqual(appels, [None, [manifeste]])

    def test_an_immediate_check_offers_its_resolution_without_a_pass(self):
        """Un écart qu'une vérification immédiate trouve à l'ouverture
        du menu est une entrée dès le premier choix : aucune passe ne
        tourne avant qu'on la lance, puis sa vérification repasse."""
        obj = self.TODO.__new__(self.TODO)
        obj._claude_context_root = lambda: tempfile.gettempdir()
        res = h.Resolution(h.HOOKS_GIT, "🪝 X", [], [])
        hooks = next(
            (s, v) for s, v in h.VERIFICATIONS if v is h.verifier_hooks
        )
        appels = []
        with (
            mock.patch.object(self.TODO, "fill_help_info", return_value=""),
            mock.patch(
                "script.todo.todo.click.prompt", side_effect=["5", "5", "0"]
            ),
            mock.patch.object(
                h,
                "verifier_en_silence",
                return_value=[
                    h.Resultat(
                        h.titre(h.verifier_hooks),
                        h.ALERTE,
                        "",
                        resolutions=[res],
                    )
                ],
            ),
            mock.patch.object(
                h,
                "lancer",
                side_effect=lambda ctx, v=None: appels.append(v)
                or [h.Resultat(h.titre(h.verifier_hooks), h.OK, "")],
            ),
            mock.patch.object(h, "executer_resolution") as executer,
            mock.patch("builtins.print"),
        ):
            obj.prompt_healthcheck()
        executer.assert_called_once()
        self.assertIs(executer.call_args.args[1], res)
        # Le second « 5 » ne trouve plus d'entrée : les hooks sont posés.
        self.assertEqual(appels, [[hooks]])

    def test_one_check_lists_every_check_in_its_own_menu(self):
        obj = self.TODO.__new__(self.TODO)
        menus = []
        with (
            mock.patch.object(
                self.TODO,
                "fill_help_info",
                side_effect=lambda choix: menus.append(choix) or "",
            ),
            mock.patch("script.todo.todo.click.prompt", side_effect=["0"]),
            mock.patch("builtins.print"),
        ):
            self.assertIsNone(
                obj._healthcheck_une_verification(list(h.VERIFICATIONS))
            )
        self.assertEqual(
            [c["prompt_description"] for c in menus[0]],
            [h.titre(v) for _s, v in h.VERIFICATIONS],
        )

    def test_scopes_cycle_and_one_check_runs_alone(self):
        obj = self.TODO.__new__(self.TODO)
        appels = []
        with (
            mock.patch.object(self.TODO, "fill_help_info", return_value=""),
            mock.patch(
                "script.todo.todo.click.prompt",
                # 3 et 4 font tourner les portées ; 2 ouvre la liste des
                # vérifications, 1 y choisit la première, 0 revient sans
                # rien lancer.
                side_effect=[
                    "3",
                    "4",
                    "1",
                    "2",
                    "1",
                    "2",
                    "0",
                    "3",
                    "3",
                    "1",
                    "0",
                ],
            ),
            mock.patch.object(
                h,
                "lancer",
                side_effect=lambda ctx, v=None: appels.append(
                    (ctx.portee_fichiers, ctx.portee_depots, v)
                ),
            ),
            mock.patch.object(h, "verifier_en_silence", return_value=[]),
        ):
            obj.prompt_healthcheck()
        self.assertEqual(
            appels,
            [
                (h.FICHIERS_DEPUIS_BASE, h.DEPOTS_TOUS, None),
                (h.FICHIERS_DEPUIS_BASE, h.DEPOTS_TOUS, [h.VERIFICATIONS[0]]),
                # Deux pas de plus : « tous » puis retour au début.
                (h.FICHIERS_NON_COMMITES, h.DEPOTS_TOUS, None),
            ],
        )


class TestJournaux(unittest.TestCase):
    """Les journaux de session : compte, poids, droits."""

    def setUp(self):
        self.etat = tempfile.mkdtemp(prefix="hc_journaux_")
        self.addCleanup(shutil.rmtree, self.etat, ignore_errors=True)
        env = mock.patch.dict(
            os.environ, {"XDG_STATE_HOME": self.etat, "ERPLIBRE_TODO_LOG": ""}
        )
        env.start()
        self.addCleanup(env.stop)
        self.dossier = os.path.join(self.etat, "erplibre", "todo")
        self.ctx = h.Contexte(self.etat)

    def journal(self, nom, taille, mode=0o600):
        os.makedirs(self.dossier, mode=0o700, exist_ok=True)
        chemin = os.path.join(self.dossier, nom)
        with open(chemin, "w") as fh:
            fh.write("x" * taille)
        os.chmod(chemin, mode)
        return chemin

    def test_sans_dossier_rien_encore(self):
        r = h.executer(self.ctx, h.verifier_journaux)
        self.assertEqual(r.statut, h.INFO)
        self.assertIn(t("no log yet"), r.resume)

    def test_compte_et_poids_des_seuls_journaux_du_todo(self):
        self.journal("todo_2026-01-01_10h00m00s_1.log", 1024)
        self.journal("todo_2026-01-02_10h00m00s_2.log", 2048)
        self.journal("autre.txt", 999999)
        r = h.executer(self.ctx, h.verifier_journaux)
        self.assertEqual(r.statut, h.OK)
        self.assertIn(f"2 {t('logs')}, 3.0 Kio", r.resume)
        self.assertTrue(r.commandes)

    def test_un_journal_lisible_par_d_autres_alerte(self):
        self.journal("todo_2026-01-01_10h00m00s_1.log", 10, mode=0o644)
        r = h.executer(self.ctx, h.verifier_journaux)
        self.assertEqual(r.statut, h.ALERTE)
        self.assertIn("todo_2026-01-01_10h00m00s_1.log", r.details[-1])

    def test_desactive_par_la_variable(self):
        with mock.patch.dict(os.environ, {"ERPLIBRE_TODO_LOG": "0"}):
            r = h.executer(self.ctx, h.verifier_journaux)
        self.assertEqual(r.statut, h.SAUTE)

    def test_un_secret_dans_un_journal_alerte_sans_etre_recopie(self):
        cle = "AKIA" + "Z" * 16
        chemin = self.journal("todo_2026-01-01_10h00m00s_1.log", 0)
        with open(chemin, "w") as fh:
            fh.write("ligne propre\nexport CLE=" + cle + "\n")
        r = h.executer(self.ctx, h.verifier_journaux)
        self.assertEqual(r.statut, h.ALERTE)
        texte = "\n".join(r.details)
        self.assertIn("todo_2026-01-01_10h00m00s_1.log:2", texte)
        self.assertNotIn(cle, texte)

    def test_la_session_en_cours_est_nommee(self):
        from script.todo import todo_journal

        chemin = todo_journal.ouvrir()
        self.addCleanup(todo_journal.fermer)
        r = h.executer(self.ctx, h.verifier_journaux)
        detail = [d for d in r.details if d.startswith(t("current session:"))]
        self.assertEqual(len(detail), 1)
        self.assertIn(os.path.basename(chemin), detail[0])
        self.assertIn(t("display copied"), detail[0])

    def test_au_dela_du_seuil_alerte(self):
        self.journal("todo_2026-01-01_10h00m00s_1.log", 10)
        with mock.patch.object(h, "JOURNAUX_ALERTE", 5):
            r = h.executer(self.ctx, h.verifier_journaux)
        self.assertEqual(r.statut, h.ALERTE)


if __name__ == "__main__":
    unittest.main()
