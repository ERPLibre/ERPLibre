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

        entree = str(4 + len(h.VERIFICATIONS))
        with (
            mock.patch.object(self.TODO, "fill_help_info", return_value=""),
            mock.patch(
                "script.todo.todo.click.prompt",
                side_effect=["1", entree, entree, "0"],
            ),
            mock.patch.object(h, "lancer", side_effect=lancer),
            mock.patch.object(h, "executer_resolution") as executer,
        ):
            obj.prompt_healthcheck()
        executer.assert_called_once()
        self.assertIs(executer.call_args.args[1], res)
        # La vérification repasse ; sans résolution, l'entrée disparaît.
        self.assertEqual(appels, [None, [manifeste]])

    def test_scopes_cycle_and_one_check_runs_alone(self):
        obj = self.TODO.__new__(self.TODO)
        appels = []
        with (
            mock.patch.object(self.TODO, "fill_help_info", return_value=""),
            mock.patch(
                "script.todo.todo.click.prompt",
                side_effect=["2", "3", "1", "4", "2", "2", "1", "0"],
            ),
            mock.patch.object(
                h,
                "lancer",
                side_effect=lambda ctx, v=None: appels.append(
                    (ctx.portee_fichiers, ctx.portee_depots, v)
                ),
            ),
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
