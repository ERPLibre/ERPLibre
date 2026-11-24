#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""erplibre-dist : un ERPLibre installé devient un dépôt livrable, figé, sans
module propriétaire, installable hors ligne."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from script.deployment import erplibre_dist as X
from script.deployment import erplibre_serve as S

GIT = [
    "git",
    "-c",
    "user.name=essai",
    "-c",
    "user.email=essai@invente.test",
    "-c",
    "commit.gpgsign=false",
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "init.defaultBranch=principale",
]


def depot(chemin: Path, fichiers: dict) -> str:
    """Un vrai dépôt git d'un seul commit portant `fichiers` ; rend son SHA.
    Une valeur `("lien", cible)` pose un lien symbolique."""
    for rel, contenu in fichiers.items():
        f = chemin / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(contenu, tuple):
            f.symlink_to(contenu[1])
        else:
            f.write_text(contenu)
    for argv in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "x"]):
        subprocess.run([*GIT, "-C", str(chemin), *argv], check=True)
    return subprocess.run(
        ["git", "-C", str(chemin), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


SHA_CŒUR = "a" * 40
SHA_ADDONS = "b" * 40
MANIFESTE = f"""<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="Org" fetch="https://forge.invente.test/Org/" />
  <project name="odoo.git" path="odoo18.0/odoo" remote="Org"
           freeze-revision="{SHA_CŒUR}" groups="odoo,odoo18.0" />
  <project name="outils.git" path="odoo18.0/addons/Org_outils" remote="Org"
           freeze-revision="{SHA_ADDONS}" groups="addons,odoo18.0" />
  <project name="dev.git" path="odoo18.0/addons/Org_dev" remote="Org"
           freeze-revision="{"c" * 40}" groups="migration" />
  <project name="outil.git" path="script/Org_outil" remote="Org"
           revision="main" groups="odoo,code_generator" />
  <project name="fige.git" path="odoo18.0/addons/Org_fige" remote="Org"
           revision="{"e" * 40}" upstream="18.0" groups="addons,odoo18.0" />
  <!-- <project name="eteint.git" path="x" remote="Org" groups="addons" /> -->
</manifest>
"""


class LesProjets(unittest.TestCase):
    def test_groups_and_tree_filter_and_url(self):
        liste = X.projets([MANIFESTE], prefixe="odoo18.0/")
        self.assertEqual(
            [
                "odoo18.0/addons/Org_fige",
                "odoo18.0/addons/Org_outils",
                "odoo18.0/odoo",
            ],
            [p.chemin for p in liste],
        )
        self.assertEqual(
            "https://forge.invente.test/Org/odoo.git",
            [p for p in liste if p.nom == "odoo.git"][0].url,
        )

    def test_a_sha_revision_is_the_frozen_commit_a_branch_is_not(self):
        par_chemin = {p.chemin: p.freeze for p in X.projets([MANIFESTE])}
        self.assertEqual("e" * 40, par_chemin["odoo18.0/addons/Org_fige"])
        self.assertEqual("", par_chemin["script/Org_outil"])

    def test_freeze_mismatch_or_absence_is_an_ecart(self):
        liste = X.projets([MANIFESTE], prefixe="odoo18.0/odoo")
        liste += X.projets([MANIFESTE], prefixe="odoo18.0/addons/Org_outils")
        tetes = {
            "odoo18.0/odoo": SHA_CŒUR,
            "odoo18.0/addons/Org_outils": "d" * 40,
        }
        ecarts = X.ecarts_de_freeze(liste, tetes)
        self.assertEqual(1, len(ecarts))
        self.assertIn("Org_outils", ecarts[0])
        sans = liste[0]._replace(freeze="")
        self.assertIn(
            "suit sa branche",
            X.ecarts_de_freeze([sans], {sans.chemin: "x"})[0],
        )
        self.assertEqual(
            [],
            X.ecarts_de_freeze(
                liste,
                {
                    "odoo18.0/odoo": SHA_CŒUR,
                    "odoo18.0/addons/Org_outils": SHA_ADDONS,
                },
            ),
        )


class LesLicences(unittest.TestCase):
    def test_declared_default_and_unreadable(self):
        self.assertEqual("OPL-1", X.licence_de("{'license': 'OPL-1'}"))
        self.assertEqual("LGPL-3", X.licence_de("{'name': 'x'}"))
        self.assertEqual("", X.licence_de("pas un dict ("))

    def test_proprietary_modules_are_removed_from_what_is_shipped(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        for module, licence in (
            ("libre", "AGPL-3"),
            ("prive", "OPL-1"),
            ("ferme", "Other proprietary"),
            ("sans", None),
        ):
            texte = {"name": module}
            if licence:
                texte["license"] = licence
            (d / module).mkdir()
            (d / module / "__manifest__.py").write_text(repr(texte))
        self.assertEqual(
            [("ferme", "Other proprietary"), ("prive", "OPL-1")],
            X.retirer_proprietaires(d),
        )
        self.assertEqual(
            ["libre", "sans"], sorted(p.name for p in d.iterdir())
        )


class LaCopie(unittest.TestCase):
    """L'arbre du commit, extrait par git archive, avec un vrai dépôt."""

    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, True)

    def test_the_commit_is_copied_not_the_working_tree(self):
        source = self.d / "projet"
        sha = depot(source, {"a.txt": "v1", ".gitignore": ".env\n"})
        (source / "a.txt").write_text("CORRECTIF LOCAL")
        (source / ".env").write_text("SECRET=1")
        (source / "non_suivi.txt").write_text("x")
        X.extraire_commit(source, sha, self.d / "copie")
        c = self.d / "copie"
        self.assertEqual("v1", (c / "a.txt").read_text())
        self.assertEqual(
            [".gitignore", "a.txt"], sorted(p.name for p in c.iterdir())
        )

    def test_an_unknown_commit_raises(self):
        source = self.d / "projet"
        depot(source, {"a.txt": "v1"})
        with self.assertRaises(RuntimeError):
            X.extraire_commit(source, "0" * 40, self.d / "copie")

    def test_a_link_leaving_the_tree_is_refused(self):
        source = self.d / "projet"
        sha = depot(source, {"sortie": ("lien", "../../../etc")})
        with self.assertRaises(RuntimeError):
            X.extraire_commit(source, sha, self.d / "copie")


class LesPieces(unittest.TestCase):
    def test_lock_line_from_a_wheel_name(self):
        self.assertEqual(
            "psycopg2==2.9.10 --hash=sha256:ab",
            X.ligne_lock("psycopg2-2.9.10-cp312-cp312-linux_x86_64.whl", "ab"),
        )
        self.assertEqual(
            "zope.event==5.0 --hash=sha256:cd",
            X.ligne_lock("zope.event-5.0-1-py3-none-any.whl", "cd"),
        )
        with self.assertRaises(ValueError):
            X.ligne_lock("pas-une-roue.tar.gz", "x")

    def test_addons_path_keeps_only_copied_projects_relative(self):
        self.assertEqual(
            "odoo18.0/odoo/addons,odoo18.0/addons/Org_outils",
            X.addons_path_relatif(
                "/r/odoo18.0/odoo/addons, /r/odoo18.0/addons/Org_outils/,"
                "/r/odoo18.0/addons/addons,/r/odoo18.0/addons/Org_outils2,"
                "/ailleurs/addons",
                "/r",
                ["odoo18.0/odoo", "odoo18.0/addons/Org_outils"],
            ),
        )

    def test_addons_path_through_a_symlinked_checkout(self):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        (d / "phys" / "odoo18.0" / "odoo" / "addons").mkdir(parents=True)
        (d / "lien").symlink_to(d / "phys")
        self.assertEqual(
            "odoo18.0/odoo/addons",
            X.addons_path_relatif(
                f"{d}/lien/odoo18.0/odoo/addons",
                str(d / "phys"),
                ["odoo18.0/odoo"],
            ),
        )

    def test_freeze_lines_kept_git_ones_included_odd_ones_refused(self):
        gardees, refusees = X.lignes_du_gel(
            "# en-tête\naaa==1.0\n"
            "ccc @ git+https://forge.invente.test/ccc.git@" + "1" * 40 + "\n"
            "pkg_resources==0.0.0\npkg-resources==0.0.0\n\nbizarre\n"
        )
        self.assertEqual(
            [
                "aaa==1.0",
                "ccc @ git+https://forge.invente.test/ccc.git@" + "1" * 40,
            ],
            gardees,
        )
        self.assertEqual(["bizarre"], refusees)

    def test_the_launcher_resolves_relative_entries(self):
        self.assertEqual(
            "/srv/l/odoo18.0/odoo/addons,/abs",
            S.resoudre_addons_path(
                "odoo18.0/odoo/addons,/abs", Path("/srv/l")
            ),
        )

    def test_provenance_first_line_follows_the_frozen_code(self):
        liste = X.projets([MANIFESTE])
        a = X.texte_provenance(liste, [], "odoo18.0_python3.12.16")
        b = X.texte_provenance(
            [liste[0]._replace(freeze="f" * 40)] + liste[1:],
            [],
            "odoo18.0_python3.12.16",
        )
        self.assertTrue(a.startswith("odoo18.0_python3.12.16-"))
        self.assertNotEqual(a.splitlines()[0], b.splitlines()[0])


class LaConstruction(unittest.TestCase):
    """De bout en bout sur un faux ERPLibre aux VRAIS dépôts git, un faux
    exécuteur à la place de pip et d'Odoo."""

    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, True)
        r = self.racine = self.d / "erplibre"
        sha_coeur = depot(r / "odoo18.0" / "odoo", {"odoo-bin": ""})
        sha_outils = depot(
            r / "odoo18.0" / "addons" / "Org_outils",
            {
                "libre/__manifest__.py": repr({"license": "AGPL-3"}),
                "prive/__manifest__.py": repr({"license": "OPL-1"}),
                ".gitignore": ".env\n",
            },
        )
        sha_fige = depot(r / "odoo18.0" / "addons" / "Org_fige", {"L": "x"})
        (r / "odoo18.0" / "odoo" / "odoo-bin").write_text("CORRECTIF LOCAL")
        outils = r / "odoo18.0" / "addons" / "Org_outils"
        (outils / ".env").write_text("SECRET=1")
        (outils / "non_suivi.txt").write_text("x")
        (r / ".repo" / "local_manifests").mkdir(parents=True)
        (r / X.MANIFESTE_FUSIONNE).write_text(
            MANIFESTE.replace(SHA_CŒUR, sha_coeur)
            .replace(SHA_ADDONS, sha_outils)
            .replace("e" * 40, sha_fige)
        )
        (r / ".erplibre-version").write_text("odoo18.0_python3.12.16")
        (r / ".odoo-version").write_text("18.0")
        (r / "conf").mkdir()
        (r / "conf" / "supported_version_erplibre.json").write_text(
            json.dumps({"odoo18.0_python3.12.16": {"odoo_version": "18.0"}})
        )
        (r / "script" / "deployment").mkdir(parents=True)
        (r / "script" / "deployment" / "erplibre_serve.py").write_text("# x")
        (r / "config.conf").write_text(
            f"[options]\naddons_path = {r}/odoo18.0/odoo/addons,"
            f"{r}/odoo18.0/addons/Org_outils\n"
        )
        self.sortie = self.d / "dist"
        self.joues = []
        self.gel = (
            "aaa==1.0\nccc @ git+https://forge.invente.test/ccc.git@"
            + "1" * 40
            + "\nbbb==2.0\npkg_resources==0.0.0\n"
        )
        self.roues = [
            "aaa-1.0-py3-none-any.whl",
            "bbb-2.0-cp312-cp312-linux_x86_64.whl",
            "ccc-3.0-py3-none-any.whl",
        ]

    def executer(self, tetes=None, odoo_rc=0):
        tetes = tetes or {}

        def faux(argv, capture_output=False, text=False, **_k):
            self.joues.append(argv)
            if argv[0] == "git":
                if argv[3:] == ["rev-parse", "HEAD"] and argv[2] in tetes:
                    return subprocess.CompletedProcess(
                        argv, 0, tetes[argv[2]] + "\n", ""
                    )
                return subprocess.run(argv, capture_output=True, text=True)
            if argv[1:3] == ["-m", "pip"] and argv[3] == "freeze":
                return subprocess.CompletedProcess(argv, 0, self.gel, "")
            if argv[1:3] == ["-m", "pip"] and argv[3] == "wheel":
                dossier = Path(argv[argv.index("-w") + 1])
                dossier.mkdir(parents=True, exist_ok=True)
                for nom in self.roues:
                    (dossier / nom).write_bytes(nom.encode())
                return subprocess.CompletedProcess(argv, 0, "", "")
            if "-c" in argv and "_base_executable" in argv[-1]:
                return subprocess.CompletedProcess(argv, 0, "/py\n", "")
            if "--stop-after-init" in argv:
                return subprocess.CompletedProcess(argv, odoo_rc, "", "boum")
            return subprocess.CompletedProcess(argv, 0, "", "")

        return faux

    def test_a_built_distribution_is_complete_and_free(self):
        ecarts = X.construire(
            self.racine,
            self.sortie,
            executer=self.executer(),
            epreuve=False,
            dire=lambda *_a: None,
        )
        self.assertEqual([], ecarts)
        s = self.sortie
        outils = s / "odoo18.0/addons/Org_outils"
        self.assertTrue((outils / "libre").is_dir())
        self.assertFalse((outils / "prive").exists())
        self.assertFalse(any(s.rglob(".git")))
        self.assertEqual("", (s / "odoo18.0/odoo/odoo-bin").read_text())
        self.assertFalse((outils / ".env").exists())
        self.assertFalse((outils / "non_suivi.txt").exists())
        self.assertFalse((s / "odoo18.0/addons/Org_dev").exists())
        self.assertTrue((s / "odoo18.0/addons/Org_fige/L").is_file())
        self.assertFalse((s / "script/Org_outil").exists())
        verrou = (s / "requirements.lock.txt").read_text().splitlines()
        self.assertEqual(3, len(verrou))
        self.assertTrue(all("--hash=sha256:" in ligne for ligne in verrou))
        requis = (s / "requirements.txt").read_text()
        self.assertIn("ccc @ git+", requis)
        self.assertNotIn("pkg_resources", requis)
        self.assertEqual(
            "odoo18.0/odoo/addons,odoo18.0/addons/Org_outils",
            S.addons_path_de((s / "config.conf").read_text()),
        )
        self.assertIn("prive\tOPL-1", (s / "PROVENANCE.lock").read_text())
        self.assertEqual(
            S.Versions("odoo18.0_python3.12.16", "18.0"), S.versions(s)
        )

    def test_an_unfrozen_project_refuses_and_writes_nothing(self):
        ecarts = X.construire(
            self.racine,
            self.sortie,
            executer=self.executer(
                {str(self.racine / "odoo18.0/odoo"): "f" * 40}
            ),
            epreuve=False,
            dire=lambda *_a: None,
        )
        self.assertEqual(1, len(ecarts))
        self.assertFalse(self.sortie.exists())

    def construit(self, **kw):
        return X.construire(
            self.racine,
            kw.pop("sortie", self.sortie),
            executer=self.executer(),
            epreuve=False,
            dire=lambda *_a: None,
        )

    def test_a_freeze_line_without_a_reproducible_version_refuses(self):
        self.gel = "aaa==1.0\nbizarre\n"
        ecarts = self.construit()
        self.assertEqual(1, len(ecarts))
        self.assertIn("bizarre", ecarts[0])

    def test_a_dependency_without_its_wheel_is_an_ecart(self):
        self.roues = self.roues[:2]
        self.assertEqual(["3 dépendances mais 2 roues"], self.construit())

    def test_an_output_overlapping_the_checkout_is_refused(self):
        temoin = self.racine / "odoo18.0" / "odoo" / "odoo-bin"
        for sortie in (self.racine, self.d, self.racine / "odoo18.0" / "x"):
            with self.subTest(sortie=sortie):
                ecarts = self.construit(sortie=sortie)
                self.assertIn("chevauche", ecarts[0])
                self.assertTrue(temoin.is_file())

    def test_a_directory_that_is_no_bundle_is_never_emptied(self):
        autre = self.d / "maison"
        (autre / ".ssh").mkdir(parents=True)
        ecarts = self.construit(sortie=autre)
        self.assertIn("pas un livrable", ecarts[0])
        self.assertTrue((autre / ".ssh").is_dir())

    def test_a_rebuild_keeps_the_bundle_s_git_and_nothing_stale(self):
        (self.sortie / ".git").mkdir(parents=True)
        (self.sortie / ".git" / "HEAD").write_text("ref")
        (self.sortie / "PROVENANCE.lock").write_text("ancien\n")
        (self.sortie / "perime.txt").write_text("x")
        self.assertEqual([], self.construit())
        self.assertEqual("ref", (self.sortie / ".git" / "HEAD").read_text())
        self.assertFalse((self.sortie / "perime.txt").exists())

    def test_the_proof_installs_offline_and_drops_its_base(self):
        ecarts = X.construire(
            self.racine,
            self.sortie,
            executer=self.executer(),
            dire=lambda *_a: None,
        )
        self.assertEqual([], ecarts)
        installe = [j for j in self.joues if "install" in j]
        self.assertTrue(installe)
        self.assertIn("--no-index", installe[0])
        self.assertIn("--require-hashes", installe[0])
        self.assertEqual(
            ["dropdb", "--if-exists", X.BASE_EPREUVE], self.joues[-1]
        )

    def test_a_failed_proof_is_an_ecart_and_still_drops_its_base(self):
        ecarts = X.construire(
            self.racine,
            self.sortie,
            executer=self.executer(odoo_rc=1),
            dire=lambda *_a: None,
        )
        self.assertEqual(1, len(ecarts))
        self.assertIn("épreuve", ecarts[0])
        self.assertEqual("dropdb", self.joues[-1][0])


class LeFigeage(unittest.TestCase):
    def test_freezing_runs_erplibre_s_own_target_in_the_checkout(self):
        vus = []

        def faux(argv, **kw):
            vus.append((argv, kw.get("cwd")))
            return subprocess.CompletedProcess(argv, 0, "", "")

        self.assertEqual([], X.figer(Path("/r"), faux, lambda *_a: None))
        self.assertEqual(
            [
                (
                    [
                        "make",
                        "--no-print-directory",
                        "repo_configure_all",
                        "FREEZE=1",
                    ],
                    "/r",
                )
            ],
            vus,
        )

    def test_a_failed_freeze_is_an_ecart_and_nothing_is_built(self):
        def faux(argv, **_kw):
            return subprocess.CompletedProcess(argv, 2, "", "sync refusé")

        ecarts = X.figer(Path("/r"), faux, lambda *_a: None)
        self.assertEqual(1, len(ecarts))
        self.assertIn("sync refusé", ecarts[0])
        construit = []
        with (
            mock.patch.object(X, "figer", lambda _r: ["figer : non"]),
            mock.patch.object(
                X, "construire", lambda *a, **k: construit.append(1) or []
            ),
        ):
            code = X.principal(["--racine", "/r", "--sortie", "/s", "--figer"])
        self.assertEqual(1, code)
        self.assertEqual([], construit)


class LeDetachement(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.d, True)
        self.journal = self.d / "j" / "journal.log"

    def test_the_child_is_the_same_command_without_detach_and_marked(self):
        argv = X.argv_enfant(
            [
                "--racine",
                ".",
                "--detache",
                "/j.log",
                "--figer",
                "--detache=/k.log",
            ]
        )
        self.assertEqual(sys.executable, argv[0])
        self.assertTrue(argv[1].endswith("erplibre_dist.py"))
        self.assertEqual(["--racine", ".", "--figer", "--marquer"], argv[2:])

    def test_the_child_runs_in_its_own_session_and_leaves_its_pid(self):
        vus = {}

        class Proc:
            pid = 4242

        def popen(argv, **kw):
            vus.update(kw)
            return Proc()

        X.lancer_detache(["x"], self.journal, popen)
        self.assertTrue(vus["start_new_session"])
        self.assertEqual(subprocess.DEVNULL, vus["stdin"])
        self.assertEqual(
            "4242", X.fichier_pid(self.journal).read_text().strip()
        )
        oui, non = (lambda _p: True), (lambda _p: False)
        self.assertEqual(4242, X.pid_en_cours(self.journal, oui, oui))
        self.assertIsNone(X.pid_en_cours(self.journal, non, oui))
        self.assertIsNone(X.pid_en_cours(self.journal, oui, non))

    def test_the_follow_up_copies_the_journal_and_returns_its_verdict(self):
        self.journal.parent.mkdir(parents=True)
        etapes = [
            "== début\n",
            "== début\n  · 462 roues\n",
            f"== début\n  · 462 roues\n{X.MARQUE_FIN}0\n",
        ]
        ecrit = []

        def dormir(_s):
            self.journal.write_text(etapes.pop(0))

        code = X.suivre(self.journal, lambda: False, dormir, ecrit.append)
        self.assertEqual(0, code)
        self.assertEqual(etapes, [])
        self.assertIn("462 roues", "".join(ecrit))
        self.assertEqual(1, "".join(ecrit).count("== début"))

    def test_a_finished_child_without_verdict_is_a_failure(self):
        self.journal.parent.mkdir(parents=True)
        self.journal.write_text("== début\n")
        ecrit = []
        code = X.suivre(
            self.journal, lambda: True, lambda _s: None, ecrit.append
        )
        self.assertEqual(1, code)
        self.assertIn("interrompue", ecrit[-1])

    def test_a_verdict_written_as_the_child_ends_is_still_read(self):
        self.journal.parent.mkdir(parents=True)
        self.journal.write_text(f"✗ x\n{X.MARQUE_FIN}1\n")
        self.assertEqual(
            1, X.suivre(self.journal, lambda: True, lambda _s: None, print)
        )
        self.assertEqual(None, X.verdict_du_journal("rien"))
        self.assertEqual(0, X.verdict_du_journal(f"{X.MARQUE_FIN}0"))

    def test_a_running_build_is_followed_not_started_again(self):
        """Suivie, elle est ATTENDUE : son verdict arrive après le début du
        suivi, là où une construction finie se lit d'un coup."""
        self.journal.parent.mkdir(parents=True)
        X.fichier_pid(self.journal).write_text("77\n")
        self.journal.write_text("== début\n")
        appels = []

        def vivant(_p):
            appels.append(1)
            if len(appels) == 2:
                self.journal.write_text(f"== début\n{X.MARQUE_FIN}0\n")
            return True

        lances = []
        with (
            mock.patch.object(X, "vivant", vivant),
            mock.patch.object(X, "est_constructeur", lambda _p: True),
            mock.patch.object(
                X, "lancer_detache", lambda *a: lances.append(a)
            ),
        ):
            code = X.principal(
                [
                    "--racine",
                    ".",
                    "--sortie",
                    "/s",
                    "--detache",
                    str(self.journal),
                ]
            )
        self.assertEqual(0, code)
        self.assertEqual([], lances)
        self.assertFalse(X.fichier_pid(self.journal).exists())

    def detache(self, vivant, constructeur, lances):
        class Proc:
            pid = 99

            def poll(self_inner):
                return 0

        def lancer(_argv, journal):
            lances.append(journal)
            journal.write_text(f"{X.MARQUE_FIN}0\n")
            X.fichier_pid(journal).write_text("99\n")
            return Proc()

        with (
            mock.patch.object(X, "vivant", lambda _p: vivant),
            mock.patch.object(X, "est_constructeur", lambda _p: constructeur),
            mock.patch.object(X, "lancer_detache", lancer),
        ):
            return X.principal(
                [
                    "--racine",
                    ".",
                    "--sortie",
                    "/s",
                    "--detache",
                    str(self.journal),
                ]
            )

    def test_a_build_finished_offline_gives_its_verdict_once(self):
        self.journal.parent.mkdir(parents=True)
        X.fichier_pid(self.journal).write_text("77\n")
        self.journal.write_text(f"✗ x\n{X.MARQUE_FIN}1\n")
        lances = []
        self.assertEqual(1, self.detache(False, True, lances))
        self.assertEqual([], lances)
        self.assertFalse(X.fichier_pid(self.journal).exists())
        self.assertEqual(0, self.detache(False, True, lances))
        self.assertEqual(1, len(lances))

    def test_a_reused_pid_is_not_taken_for_the_build(self):
        self.journal.parent.mkdir(parents=True)
        X.fichier_pid(self.journal).write_text("77\n")
        self.journal.write_text("== début\n")
        lances = []
        self.assertEqual(1, self.detache(True, False, lances))
        self.assertEqual([], lances)

    def test_an_abbreviated_detach_is_refused(self):
        with (
            self.assertRaises(SystemExit),
            mock.patch("sys.stderr"),
        ):
            X.principal(["--racine", ".", "--sortie", "/s", "--detach", "/j"])

    def test_a_marked_build_writes_its_code_last(self):
        with (
            mock.patch.object(X, "construire", lambda *a, **k: []),
            mock.patch("builtins.print") as imprime,
        ):
            X.principal(["--racine", "/r", "--sortie", "/s", "--marquer"])
        self.assertEqual(
            f"{X.MARQUE_FIN}0", imprime.call_args_list[-1].args[0]
        )


if __name__ == "__main__":
    unittest.main()
