#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""L'état du code d'un checkout en JSON, lu sur de vrais dépôts temporaires.

Un dossier temporaire tient un checkout ERPLibre inventé : ses fichiers de
version, un manifeste local, les fichiers de `manifest/` et des clones sous
« odoo18.0/ » et « odoo17.0/ ». Les branches de suivi que git-repo pose se
créent par « update-ref » : aucun distant n'est joint, aucun réseau. La
configuration git de l'hôte n'est pas lue. Tous les noms de dépôts, de
remotes, de modules et d'hôtes sont inventés.
"""

import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from script.git import repo_state

REMOTE_FORK = "R_origin_U"
WEB18 = "odoo18.0/addons/R_web"
WEB17 = "odoo17.0/addons/R_web"


def _git(cwd, *args):
    """Lance git dans `cwd`. Rend stdout, sans espaces autour."""
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _ecrire(racine, fichiers):
    for chemin, contenu in fichiers.items():
        complet = os.path.join(racine, chemin)
        os.makedirs(os.path.dirname(complet), exist_ok=True)
        with open(complet, "w") as fh:
            fh.write(contenu)


def _manifeste_module(version, entete=""):
    return f'{entete}{{"name": "M", "version": "{version}"}}\n'


def _projet(attrs):
    texte = " ".join(f'{k}="{v}"' for k, v in attrs.items())
    return f"  <project {texte}/>"


class Checkout(unittest.TestCase):
    """Le checkout inventé que chaque test reçoit neuf.

    - R_web (18.0 et 17.0) : un fork de « U ». En 18.0, deux commits amont
      puis nos commits o1 (correctif), o2 (amélioration) ; HEAD sur la
      branche de suivi du fork. En 17.0, un commit amont puis p1 (le même
      correctif, même diff), p2 (même sujet que o2, autre diff), p3 (un
      ajout propre à 17.0), p4 (hors module).
    - R_ahead : HEAD un commit au-dessus de sa branche de suivi.
    - R_behind : HEAD un commit en dessous.
    - R_absent : au manifeste, jamais cloné.
    - R_broken : un « .git » qui pointe dans le vide.
    - R_extra : un clone que le manifeste ne nomme pas.
    """

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
        self.racine = os.path.join(self.dossier, "erplibre")
        os.makedirs(self.racine)
        _ecrire(
            self.racine,
            {
                ".erplibre-version": "odoo18.0_python3.12.10\n",
                ".odoo-version": "18.0\n",
                ".python-odoo-version": "3.12.10\n",
                # Comme le checkout réel, la racine ignore ce que git-repo
                # et les fichiers de `manifest/` y posent.
                ".gitignore": "/.repo/\n/odoo*/\n/manifest/\n",
            },
        )
        _git(self.racine, "init", "-q", "-b", "principale")
        _git(self.racine, "add", "-A")
        _git(self.racine, "commit", "-q", "-m", "départ")
        _git(self.racine, "tag", "v0.1")
        os.makedirs(os.path.join(self.racine, "odoo16.0"))

        self.sha = {}
        self.construire_web18()
        self.construire_web17()
        self.ahead = self.construire_simple("R_ahead", decalage=+1)
        self.behind = self.construire_simple("R_behind", decalage=-1)
        broken = os.path.join(self.racine, "odoo18.0/addons/R_broken")
        os.makedirs(broken)
        _ecrire(broken, {".git": "gitdir: /nonexistent/invented.git\n"})
        extra = self.depot("odoo18.0/addons/R_extra")
        self.commit(extra, {"x.txt": "x\n"}, "extra")
        _git(
            extra,
            "remote",
            "add",
            "origin",
            "https://user:token@example.invalid/extra.git",
        )

        self.local = {
            WEB18: {
                "name": "web.git",
                "path": WEB18,
                "remote": REMOTE_FORK,
                "revision": "18.0_dev",
                "fork-upstream-remote": "U",
                "fork-upstream": "18.0",
            },
            WEB17: {
                "name": "web.git",
                "path": WEB17,
                "remote": REMOTE_FORK,
                "revision": "17.0_dev",
                "fork-upstream-remote": "U",
                "fork-upstream": "17.0",
            },
        }
        for nom in ("R_ahead", "R_behind", "R_absent", "R_broken"):
            chemin = f"odoo18.0/addons/{nom}"
            self.local[chemin] = {
                "name": f"{nom}.git",
                "path": chemin,
                "remote": "R",
                "revision": "18.0",
            }
        self.ecrire_local()
        self.sources18 = {
            WEB18: {
                "name": "web.git",
                "path": WEB18,
                "remote": REMOTE_FORK,
                "revision": "18.0_dev",
                "freeze-revision": self.sha["o2"],
                "fork-upstream-remote": "U",
                "fork-upstream": "18.0",
                "fork-upstream-freeze-revision": self.sha["u2"],
            }
        }
        self.sources17 = {}
        self.ecrire_sources()

    # ── construction ───────────────────────────────────────────────────

    def depot(self, chemin):
        dossier = os.path.join(self.racine, chemin)
        os.makedirs(dossier)
        _git(dossier, "init", "-q", "-b", "travail")
        return dossier

    def commit(self, depot, fichiers, message):
        _ecrire(depot, fichiers)
        _git(depot, "add", "-A")
        _git(depot, "commit", "-q", "-m", message)
        return _git(depot, "rev-parse", "HEAD")

    def construire_web18(self):
        d = self.depot(WEB18)
        self.web18 = d
        self.sha["u1"] = self.commit(
            d,
            {
                "README.md": "web\n",
                "mod_a/__manifest__.py": _manifeste_module(
                    "18.0.1.0.0", "# Un en-tête de commentaire.\n"
                ),
                "mod_a/models.py": "line1\nline2\n",
                "mod_new/__manifest__.py": _manifeste_module("18.0.1.0.0"),
            },
            "[ADD] mod_a",
        )
        self.sha["u2"] = self.commit(
            d, {"mod_a/readme.txt": "doc\n"}, "[DOC] mod_a"
        )
        _git(d, "update-ref", "refs/remotes/U/18.0", self.sha["u2"])
        self.sha["o1"] = self.commit(
            d, {"mod_a/models.py": "line1\nline2\nfix\n"}, "[FIX] mod_a: fix"
        )
        self.sha["o2"] = self.commit(
            d,
            {"mod_a/models.py": "line1\nline2\nfix\nimp18\n"},
            "[IMP] mod_a: improve",
        )
        _git(
            d,
            "update-ref",
            f"refs/remotes/{REMOTE_FORK}/18.0_dev",
            self.sha["o2"],
        )
        _git(d, "checkout", "-q", "--detach", self.sha["o2"])

    def construire_web17(self):
        d = self.depot(WEB17)
        self.web17 = d
        self.sha["v1"] = self.commit(
            d,
            {
                "README.md": "web\n",
                "mod_a/__manifest__.py": _manifeste_module("17.0.1.0.0"),
                "mod_a/models.py": "line1\nline2\n",
                "mod_old/__manifest__.py": _manifeste_module("17.0.1.0.0"),
            },
            "[ADD] mod_a",
        )
        _git(d, "update-ref", "refs/remotes/U/17.0", self.sha["v1"])
        self.sha["p1"] = self.commit(
            d, {"mod_a/models.py": "line1\nline2\nfix\n"}, "[FIX] mod_a: fix"
        )
        self.sha["p2"] = self.commit(
            d,
            {"mod_a/models.py": "line1\nline2\nfix\nimp17\n"},
            "[IMP] mod_a: improve",
        )
        self.sha["p3"] = self.commit(
            d, {"mod_old/models.py": "only17\n"}, "[IMP] mod_old: feature"
        )
        self.sha["p4"] = self.commit(d, {"README.md": "web 17\n"}, "readme")
        _git(
            d,
            "update-ref",
            f"refs/remotes/{REMOTE_FORK}/17.0_dev",
            self.sha["p4"],
        )
        _git(d, "checkout", "-q", "--detach", self.sha["p4"])

    def construire_simple(self, nom, decalage):
        d = self.depot(f"odoo18.0/addons/{nom}")
        un = self.commit(
            d,
            {
                "mod_exec/__manifest__.py": (
                    'raise SystemExit("executed")\n' + _manifeste_module("1.2")
                ),
                "mod_bad/__manifest__.py": '{"version": \n',
                "not_a_module/file.txt": "x\n",
            },
            "un",
        )
        deux = self.commit(d, {"a.txt": "2\n"}, "deux")
        if decalage > 0:
            _git(d, "update-ref", "refs/remotes/R/18.0", un)
            _git(d, "checkout", "-q", "--detach", deux)
        else:
            _git(d, "update-ref", "refs/remotes/R/18.0", deux)
            _git(d, "checkout", "-q", "--detach", un)
        return d

    def ecrire_local(self):
        lignes = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            "<manifest>",
            '  <remote name="R" fetch="https://example.invalid/R/"/>',
            f'  <remote name="{REMOTE_FORK}"'
            ' fetch="https://user:secret@example.invalid/R/"/>',
            '  <remote name="U" fetch="https://example.invalid/U/"/>',
            '  <!-- <project name="x" path="commented"/> -->',
        ]
        lignes += [_projet(a) for _c, a in sorted(self.local.items())]
        lignes.append("</manifest>")
        _ecrire(
            self.racine,
            {
                ".repo/local_manifests/erplibre_manifest.xml": "\n".join(
                    lignes
                )
                + "\n"
            },
        )

    def ecrire_sources(self):
        for version, projets in (
            ("18.0", self.sources18),
            ("17.0", self.sources17),
        ):
            lignes = ["<manifest>"]
            lignes += [_projet(a) for a in projets.values()]
            lignes.append("</manifest>")
            _ecrire(
                self.racine,
                {
                    f"manifest/git_manifest_odoo{version}.xml": "\n".join(
                        lignes
                    )
                },
            )

    # ── appel ──────────────────────────────────────────────────────────

    def lancer(self, *args):
        """(code, JSON) de `repo_state.main`, sur ce checkout.

        « --root » suit la sous-commande, avant tout « -- ».
        """
        racine = ["--root", self.racine]
        if args and args[0] in repo_state.COMMANDES:
            argv = [args[0], *racine, *args[1:]]
        else:
            argv = [*racine, *args]
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie):
            code = repo_state.main(argv)
        return code, json.loads(sortie.getvalue())

    def depots(self, donnees):
        return {r["path"]: r for r in donnees["repos"]}


class TestSnapshot(Checkout):
    def test_contrat_et_etats(self):
        code, d = self.lancer()
        self.assertEqual(code, 0)
        self.assertEqual(d["schema"], 1)
        self.assertEqual(d["command"], "snapshot")
        self.assertEqual(d["odoo"], {"version": "18.0", "python": "3.12.10"})
        self.assertEqual(d["erplibre"]["version"], "odoo18.0_python3.12.10")
        self.assertEqual(d["erplibre"]["commit"], "v0.1")
        self.assertEqual(d["erplibre"]["branch"], "principale")
        self.assertIsNone(d["erplibre"]["dirty"])
        self.assertEqual(d["mode"], "branches")
        self.assertEqual(d["mode_detail"], {"pinned": 0, "total": 6})
        r = self.depots(d)
        self.assertEqual(
            {p: x["state"] for p, x in r.items()},
            {
                WEB18: "conforme",
                WEB17: "conforme",
                "odoo18.0/addons/R_ahead": "en_avance",
                "odoo18.0/addons/R_behind": "decale",
                "odoo18.0/addons/R_absent": "absent",
                "odoo18.0/addons/R_broken": "erreur",
                "odoo18.0/addons/R_extra": "hors_manifeste",
            },
        )
        self.assertEqual(list(r), sorted(r))
        self.assertEqual(
            d["counts"]["states"],
            {
                "absent": 1,
                "conforme": 2,
                "decale": 1,
                "en_avance": 1,
                "erreur": 1,
                "hors_manifeste": 1,
            },
        )
        self.assertEqual(
            (
                r["odoo18.0/addons/R_ahead"]["ahead"],
                r["odoo18.0/addons/R_ahead"]["behind"],
            ),
            (1, 0),
        )
        self.assertEqual(r["odoo18.0/addons/R_behind"]["behind"], 1)
        self.assertTrue(r["odoo18.0/addons/R_broken"]["error"])
        self.assertIsNone(r["odoo18.0/addons/R_absent"]["head"])

    def test_depot_du_manifeste(self):
        _code, d = self.lancer()
        web = self.depots(d)[WEB18]
        self.assertEqual(web["name"], "web.git")
        self.assertEqual(web["remote"], REMOTE_FORK)
        # Le secret du « fetch » ne sort jamais.
        self.assertEqual(web["url"], "https://example.invalid/R/web.git")
        self.assertEqual(web["revision"], "18.0_dev")
        self.assertEqual(web["manifest_branch"], "18.0_dev")
        self.assertEqual(web["freeze_revision"], self.sha["o2"])
        self.assertEqual(web["head"], self.sha["o2"])
        self.assertEqual(web["target"], self.sha["o2"])
        self.assertIsNone(web["branch"])
        self.assertEqual(
            web["upstream"],
            {
                "remote": "U",
                "name": "web.git",
                "branch": "18.0",
                "freeze_revision": self.sha["u2"],
                "declared": True,
                "url": "https://example.invalid/U/web.git",
            },
        )
        self.assertIsNone(
            self.depots(d)["odoo18.0/addons/R_ahead"]["upstream"]
        )

    def test_hors_manifeste(self):
        _code, d = self.lancer()
        extra = self.depots(d)["odoo18.0/addons/R_extra"]
        self.assertEqual(extra["remote"], "origin")
        self.assertEqual(extra["url"], "https://example.invalid/extra.git")
        self.assertIsNone(extra["revision"])
        self.assertIsNone(extra["alignment"])

    def test_modules(self):
        _code, d = self.lancer()
        r = self.depots(d)
        self.assertEqual(
            r[WEB18]["modules"],
            [
                {
                    "name": "mod_a",
                    "version": "18.0.1.0.0",
                    "installable": True,
                    "path": f"{WEB18}/mod_a",
                },
                {
                    "name": "mod_new",
                    "version": "18.0.1.0.0",
                    "installable": True,
                    "path": f"{WEB18}/mod_new",
                },
            ],
        )
        mods = {m["name"]: m for m in r["odoo18.0/addons/R_ahead"]["modules"]}
        self.assertEqual(set(mods), {"mod_exec", "mod_bad"})
        # Lu, jamais exécuté : le « raise » d'avant le dictionnaire ne joue pas.
        self.assertEqual(mods["mod_exec"]["version"], "1.2")
        self.assertIsNone(mods["mod_bad"]["version"])
        self.assertIn("SyntaxError", mods["mod_bad"]["error"])
        self.assertEqual(d["counts"]["modules"], 2 + 2 + 2 + 2 + 0)

    def test_mode_gele(self):
        self.local["odoo18.0/addons/R_behind"]["revision"] = self.sha_de(
            "odoo18.0/addons/R_behind", "HEAD"
        )
        self.ecrire_local()
        _code, d = self.lancer()
        self.assertEqual(d["mode"], "frozen")
        self.assertEqual(d["mode_detail"]["pinned"], 1)
        self.assertEqual(
            self.depots(d)["odoo18.0/addons/R_behind"]["state"], "conforme"
        )

    def sha_de(self, chemin, ref):
        return _git(os.path.join(self.racine, chemin), "rev-parse", ref)

    def test_commit_gele_absent_du_clone(self):
        self.local["odoo18.0/addons/R_behind"]["revision"] = "a" * 40
        self.ecrire_local()
        _code, d = self.lancer()
        r = self.depots(d)["odoo18.0/addons/R_behind"]
        self.assertEqual(r["state"], "decale")
        self.assertIsNone(r["target"])

    def test_sale_seulement_avec_dirty(self):
        _ecrire(self.web18, {"mod_a/models.py": "modifié\n"})
        # R_web 17.0 ignore les fichiers compilés ; sa branche de suivi
        # avance sur ce commit, le clone reste conforme.
        self.commit(self.web17, {".gitignore": "__pycache__/\n*.pyc\n"}, "ign")
        _git(
            self.web17,
            "update-ref",
            f"refs/remotes/{REMOTE_FORK}/17.0_dev",
            "HEAD",
        )
        _ecrire(
            self.web17,
            {"mod_a/__pycache__/models.cpython-312.pyc": "x", "a.pyc": "x"},
        )
        _code, d = self.lancer()
        self.assertEqual(self.depots(d)[WEB18]["state"], "conforme")
        self.assertIsNone(self.depots(d)[WEB18]["dirty"])
        _code, d = self.lancer("--dirty")
        r = self.depots(d)
        self.assertEqual(r[WEB18]["state"], "sale")
        self.assertEqual(r[WEB18]["alignment"], "conforme")
        self.assertTrue(r[WEB18]["dirty"])
        # Un fichier ignoré ne salit pas.
        self.assertEqual(r[WEB17]["state"], "conforme")
        self.assertFalse(r[WEB17]["dirty"])
        self.assertFalse(d["erplibre"]["dirty"])
        self.assertTrue(d["dirty_checked"])
        # Un module non suivi que rien n'ignore est du code qu'Odoo charge.
        _ecrire(
            self.web17,
            {"mod_copie/__manifest__.py": _manifeste_module("17.0.1.0.0")},
        )
        _code, d = self.lancer("--dirty")
        r = self.depots(d)[WEB17]
        self.assertEqual(r["state"], "sale")
        self.assertEqual(r["alignment"], "conforme")
        self.assertTrue(r["dirty"])
        self.assertIn("mod_copie", [m["name"] for m in r["modules"]])

    def test_empreinte(self):
        _c, un = self.lancer()
        _c, deux = self.lancer()
        self.assertEqual(un["fingerprint"], deux["fingerprint"])
        self.assertEqual(len(un["fingerprint"]), 64)
        _git(self.web18, "checkout", "-q", "--detach", self.sha["o1"])
        _c, trois = self.lancer()
        self.assertNotEqual(un["fingerprint"], trois["fingerprint"])
        self.assertEqual(self.depots(trois)[WEB18]["state"], "decale")

    def test_limite_repo(self):
        code, d = self.lancer(
            "--repo", WEB18, "--repo", os.path.join(self.racine, WEB17) + "/"
        )
        self.assertEqual(code, 0)
        self.assertEqual([r["path"] for r in d["repos"]], [WEB17, WEB18])
        code, d = self.lancer("snapshot", "--repo", "odoo18.0/addons/nothing")
        self.assertEqual(code, repo_state.EXIT_CIBLE)
        self.assertEqual(d["repos"], [])
        self.assertTrue(d["errors"])
        code, _d = self.lancer("--repo", "../outside")
        self.assertEqual(code, repo_state.EXIT_CIBLE)

    def test_sans_manifeste_local(self):
        os.remove(
            os.path.join(
                self.racine, ".repo/local_manifests/erplibre_manifest.xml"
            )
        )
        code, d = self.lancer()
        self.assertEqual(code, 0)
        self.assertIsNone(d["mode"])
        self.assertFalse(d["local_manifest"])
        r = self.depots(d)
        # Les fichiers de `manifest/` de la version active prennent le relais.
        self.assertEqual(r[WEB18]["state"], "conforme")
        self.assertEqual(
            r["odoo18.0/addons/R_ahead"]["state"], "hors_manifeste"
        )

    def test_manifeste_illisible(self):
        _ecrire(
            self.racine,
            {".repo/local_manifests/erplibre_manifest.xml": "<manifest>"},
        )
        code, d = self.lancer()
        self.assertEqual(code, 0)
        self.assertTrue(d["errors"])


class TestUrl(unittest.TestCase):
    def test_sans_identifiants(self):
        f = repo_state.sans_identifiants
        self.assertEqual(
            f("https://user:tok@example.invalid/a.git"),
            "https://example.invalid/a.git",
        )
        self.assertEqual(
            f("https://tok@example.invalid/a.git"),
            "https://example.invalid/a.git",
        )
        self.assertEqual(
            f("ssh://git:pw@example.invalid/a.git"),
            "ssh://git@example.invalid/a.git",
        )
        self.assertEqual(
            f("git@example.invalid:a/b.git"), "git@example.invalid:a/b.git"
        )
        self.assertIsNone(f(None))


class TestGit(unittest.TestCase):
    def test_options_de_lecture_seule(self):
        with patch.object(repo_state.subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, "ok", "")
            self.assertEqual(
                repo_state.git(["status"], "/nonexistent", 7), ("ok", "", 0)
            )
        args, kwargs = run.call_args
        commande = args[0]
        self.assertEqual(commande[:3], ["git", "-c", "safe.directory=*"])
        self.assertEqual(commande[-1], "status")
        self.assertEqual(kwargs["env"]["GIT_TERMINAL_PROMPT"], "0")
        self.assertEqual(kwargs["env"]["GIT_OPTIONAL_LOCKS"], "0")
        self.assertEqual(kwargs["timeout"], 7)

    def test_delai_depasse(self):
        with patch.object(
            repo_state.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired("git", 1),
        ):
            out, err, code = repo_state.git(["log"], "/nonexistent", 1)
        self.assertEqual((out, code), ("", 124))
        self.assertIn("timeout", err)


class TestLienGit(unittest.TestCase):
    """Un clone sous un autre dépôt dont le « .git » ne se lit pas : git
    répond pour le parent, le message dit pourquoi."""

    def setUp(self):
        self.racine = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.racine, True)
        _git(self.racine, "init", "-q")
        _git(
            self.racine,
            "-c",
            "user.name=T",
            "-c",
            "user.email=t@exemple.invalid",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "x",
        )
        self.clone = os.path.join(self.racine, WEB17)
        os.makedirs(self.clone)
        self.cible = os.path.join(
            self.racine, ".repo", "projects", "R_web.git"
        )
        os.symlink(self.cible, os.path.join(self.clone, ".git"))

    def test_lien_casse(self):
        _tete, _branche, erreur = repo_state.lire_tete(self.clone)
        self.assertIn("broken .git link", erreur)
        self.assertIn("R_web.git", erreur)

    @unittest.skipIf(os.geteuid() == 0, "root lit tout")
    def test_cible_illisible(self):
        os.makedirs(self.cible)
        os.chmod(self.cible, 0)
        self.addCleanup(os.chmod, self.cible, 0o755)
        _tete, _branche, erreur = repo_state.lire_tete(self.clone)
        self.assertIn(".git not readable", erreur)

    @unittest.skipIf(os.geteuid() == 0, "root lit tout")
    def test_conseil_sous_repo(self):
        os.makedirs(self.cible)
        os.chmod(self.cible, 0)
        self.addCleanup(os.chmod, self.cible, 0o755)
        repo = os.path.join(os.path.realpath(self.racine), ".repo")
        with patch.object(repo_state, "dans_un_conteneur", return_value=True):
            conseil = repo_state.permissions_manquantes(
                self.racine, [self.clone]
            )
        self.assertEqual(conseil["path"], repo)
        self.assertEqual(conseil["command"], f"chmod -R go+rX {repo}")
        self.assertEqual(conseil["container"], repo_state.socket.gethostname())
        self.assertEqual(conseil["count"], 1)

    def test_conseil_absent_quand_tout_se_lit(self):
        os.makedirs(self.cible)
        self.assertIsNone(
            repo_state.permissions_manquantes(self.racine, [self.clone])
        )

    def test_autre_cas_nomme_le_depot_qui_repond(self):
        os.makedirs(self.cible)
        _tete, _branche, erreur = repo_state.lire_tete(self.clone)
        self.assertIn("not the root of a git repository", erreur)
        self.assertIn(
            os.path.realpath(self.racine),
            os.path.realpath(erreur.rsplit(" ", 1)[1]),
        )


RACINE_LIT_TOUT = os.geteuid() == 0


class TestPermissions(Checkout):
    """Un « .git » que ce compte ne lit pas : « permissions » nomme le
    compte, le propriétaire et la commande à lancer en root."""

    def setUp(self):
        super().setUp()
        p = patch.object(repo_state, "dans_un_conteneur", return_value=False)
        p.start()
        self.addCleanup(p.stop)

    def illisible(self, chemin):
        git_dir = os.path.join(self.racine, chemin, ".git")
        os.chmod(git_dir, 0)
        self.addCleanup(os.chmod, git_dir, 0o755)

    def test_rien_a_signaler(self):
        _code, d = self.lancer()
        self.assertIsNone(d["permissions"])
        _code, d = self.lancer("cross-version", WEB18)
        self.assertIsNone(d["permissions"])

    @unittest.skipIf(RACINE_LIT_TOUT, "root lit tout")
    def test_snapshot(self):
        self.illisible("odoo18.0/addons/R_ahead")
        _code, d = self.lancer()
        ahead = self.depots(d)["odoo18.0/addons/R_ahead"]
        self.assertEqual(ahead["state"], "erreur")
        self.assertIn(".git not readable", ahead["error"])
        racine = os.path.realpath(self.racine)
        moi = repo_state._nom_compte(os.geteuid())
        self.assertEqual(
            d["permissions"],
            {
                "account": moi,
                "owner": moi,
                "count": 1,
                "path": racine,
                "command": f"chmod -R go+rX {racine}",
                "container": None,
            },
        )

    def test_l_empreinte_ignore_le_conseil(self):
        _code, d = self.lancer()
        avec = dict(d, permissions={"count": 3})
        self.assertEqual(repo_state.empreinte(avec), d["fingerprint"])

    @unittest.skipIf(RACINE_LIT_TOUT, "root lit tout")
    def test_cross_version_sur_le_depot(self):
        self.illisible(WEB18)
        code, d = self.lancer("cross-version", WEB18)
        self.assertEqual(code, repo_state.EXIT_CIBLE)
        self.assertIn(".git not readable", d["error"])
        self.assertEqual(d["permissions"]["count"], 1)

    @unittest.skipIf(RACINE_LIT_TOUT, "root lit tout")
    def test_cross_version_sur_l_autre_version(self):
        self.illisible(WEB17)
        _code, d = self.lancer("cross-version", WEB18)
        self.assertIsNone(d["error"])
        self.assertEqual(d["permissions"]["count"], 1)


class TestBetween(Checkout):
    def test_plage(self):
        code, d = self.lancer(
            "between", WEB18, self.sha["u1"], self.sha["o2"][:12]
        )
        self.assertEqual(code, 0)
        self.assertEqual(d["count"], 3)
        self.assertEqual(d["removed"], 0)
        self.assertTrue(d["ancestor"])
        self.assertFalse(d["truncated"])
        self.assertEqual(
            [c["sha"] for c in d["commits"]],
            [self.sha["o2"], self.sha["o1"], self.sha["u2"]],
        )
        self.assertEqual(d["commits"][0]["subject"], "[IMP] mod_a: improve")
        self.assertEqual(
            set(d["commits"][0]), {"sha", "author", "date", "subject"}
        )

    def test_bornee(self):
        _code, d = self.lancer(
            "between", WEB18, self.sha["u1"], self.sha["o2"], "--max", "2"
        )
        self.assertEqual(len(d["commits"]), 2)
        self.assertTrue(d["truncated"])
        self.assertEqual(d["count"], 3)

    def test_historique_reecrit(self):
        arbre = _git(self.web18, "rev-parse", f"{self.sha['u2']}^{{tree}}")
        a_cote = _git(
            self.web18, "commit-tree", arbre, "-p", self.sha["u2"], "-m", "x"
        )
        _code, d = self.lancer("between", WEB18, self.sha["o2"], a_cote)
        self.assertEqual(d["count"], 1)
        self.assertEqual(d["removed"], 2)
        self.assertFalse(d["ancestor"])

    def test_ancien_inconnu(self):
        code, d = self.lancer("between", WEB18, "b" * 40, self.sha["o2"])
        self.assertEqual(code, 0)
        self.assertFalse(d["old_known"])
        self.assertTrue(d["new_known"])
        self.assertEqual(d["commits"], [])

    def test_nouveau_inconnu_ou_depot_absent(self):
        code, d = self.lancer("between", WEB18, self.sha["u1"], "b" * 40)
        self.assertEqual(code, repo_state.EXIT_CIBLE)
        self.assertTrue(d["error"])
        code, _d = self.lancer(
            "between", "odoo18.0/addons/R_absent", "HEAD", "HEAD"
        )
        self.assertEqual(code, repo_state.EXIT_CIBLE)
        # Une option glissée à la place d'une révision n'est pas passée à git.
        code, d = self.lancer("between", WEB18, "HEAD", "--", "--output=/x")
        self.assertEqual(code, repo_state.EXIT_CIBLE)

    def test_clone_superficiel_d_un_autre_proprietaire(self):
        """Le compte d'un service Odoo n'est pas le propriétaire du clone :
        « safe.directory=* » le laisse lire, superficiel compris."""
        chemin = "odoo18.0/addons/R_shallow"
        _git(
            self.racine,
            "clone",
            "-q",
            "--depth",
            "1",
            f"file://{self.web18}",
            chemin,
        )
        with patch.dict(os.environ, {"GIT_TEST_ASSUME_DIFFERENT_OWNER": "1"}):
            # git seul refuse le clone ; le module, lui, le lit.
            refus = subprocess.run(
                ["git", "rev-parse", "--is-shallow-repository"],
                cwd=os.path.join(self.racine, chemin),
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(refus.returncode, 0)
            code, d = self.lancer("between", chemin, "HEAD", "HEAD")
        self.assertEqual(code, 0)
        self.assertIs(d["shallow"], True)
        _code, d = self.lancer("between", WEB18, "HEAD", "HEAD")
        self.assertIs(d["shallow"], False)

    def test_fichiers_et_modules_modifies(self):
        _code, d = self.lancer(
            "between", WEB18, self.sha["u1"], self.sha["o2"]
        )
        self.assertIsNone(d["changed_modules"])
        self.assertIsNone(d["paths"])
        _code, d = self.lancer(
            "between", WEB18, self.sha["u1"], self.sha["o2"], "--paths"
        )
        self.assertEqual(d["changed_modules"], ["mod_a"])
        self.assertEqual(d["paths"], ["mod_a/models.py", "mod_a/readme.txt"])
        self.assertEqual(d["paths_count"], 2)
        self.assertFalse(d["paths_truncated"])
        _code, d = self.lancer(
            "between",
            WEB18,
            self.sha["u1"],
            self.sha["o2"],
            "--paths",
            "--max-paths",
            "1",
        )
        self.assertEqual(d["changed_modules"], ["mod_a"])
        self.assertEqual(len(d["paths"]), 1)
        self.assertTrue(d["paths_truncated"])


class TestCrossVersion(Checkout):
    def autre(self, d, version):
        return next(o for o in d["others"] if o["version"] == version)

    def test_depuis_18(self):
        code, d = self.lancer("cross-version", WEB18)
        self.assertEqual(code, 0)
        self.assertEqual(d["version"], "18.0")
        self.assertTrue(d["repo"]["fork"])
        self.assertEqual([o["version"] for o in d["others"]], ["16.0", "17.0"])
        self.assertFalse(self.autre(d, "16.0")["present"])
        o = self.autre(d, "17.0")
        self.assertTrue(o["present"])
        self.assertEqual(o["head"], self.sha["p4"])
        self.assertEqual(
            o["base"], {"sha": self.sha["v1"], "source": "upstream_ref"}
        )
        self.assertEqual(
            o["modules"],
            [
                {
                    "name": "mod_a",
                    "here": {
                        "version": "18.0.1.0.0",
                        "path": f"{WEB18}/mod_a",
                    },
                    "there": {
                        "version": "17.0.1.0.0",
                        "path": f"{WEB17}/mod_a",
                    },
                },
                {
                    "name": "mod_new",
                    "here": {
                        "version": "18.0.1.0.0",
                        "path": f"{WEB18}/mod_new",
                    },
                    "there": None,
                },
                {
                    "name": "mod_old",
                    "here": None,
                    "there": {
                        "version": "17.0.1.0.0",
                        "path": f"{WEB17}/mod_old",
                    },
                },
            ],
        )
        # p1 a le même diff que o1, p2 le même sujet que o2 ; p3 reste à
        # porter, p4 ne touche aucun module.
        self.assertEqual(
            [(c["sha"], c["module"]) for c in o["to_port"]],
            [(self.sha["p3"], "mod_old")],
        )
        apparies = {c["sha"]: c["match"] for c in o["ported"]}
        self.assertEqual(
            apparies,
            {
                self.sha["p1"]: {"by": "patch-id", "sha": self.sha["o1"]},
                self.sha["p2"]: {"by": "subject", "sha": self.sha["o2"]},
            },
        )
        self.assertEqual(o["outside_modules"], 1)
        self.assertFalse(o["truncated"])
        self.assertEqual(len(o["history"]["mod_a"]["here"]), 4)
        self.assertEqual(len(o["history"]["mod_a"]["there"]), 3)
        self.assertEqual(o["history"]["mod_new"]["there"], [])
        # Deux clones, deux magasins d'objets : le diff passe quand même.
        diff = o["diff"]
        self.assertIsNone(diff["error"])
        self.assertEqual(
            (diff["from"], diff["to"]), (self.sha["p4"], self.sha["o2"])
        )
        self.assertEqual(set(diff["modules"]), {"mod_a"})
        mod_a = diff["modules"]["mod_a"]
        self.assertEqual(
            sorted(p["path"] for p in mod_a["paths"]),
            ["mod_a/__manifest__.py", "mod_a/models.py", "mod_a/readme.txt"],
        )
        self.assertEqual(mod_a["files"], 3)
        self.assertNotIn("patch", diff)

    def test_depuis_17_et_filtre(self):
        code, d = self.lancer(
            "cross-version", WEB17, "--module", "mod_a", "--full"
        )
        self.assertEqual(code, 0)
        o = self.autre(d, "18.0")
        self.assertEqual([m["name"] for m in o["modules"]], ["mod_a"])
        self.assertEqual([m["name"] for m in d["repo"]["modules"]], ["mod_a"])
        self.assertEqual(o["base"]["sha"], self.sha["u2"])
        self.assertEqual(o["to_port"], [])
        self.assertEqual(len(o["ported"]), 2)
        self.assertEqual(list(o["history"]), ["mod_a"])
        self.assertIn("+imp17", o["diff"]["patch"])
        self.assertFalse(o["diff"]["patch_truncated"])
        _code, d = self.lancer(
            "cross-version", WEB17, "--full", "--max-bytes", "10"
        )
        diff = self.autre(d, "18.0")["diff"]
        self.assertTrue(diff["patch_truncated"])
        self.assertEqual(len(diff["patch"]), 10)

    def test_base_gelee_puis_inconnue(self):
        _git(self.web17, "update-ref", "-d", "refs/remotes/U/17.0")
        self.sources17[WEB17] = dict(
            self.local[WEB17],
            **{"fork-upstream-freeze-revision": self.sha["v1"]},
        )
        self.ecrire_sources()
        _code, d = self.lancer("cross-version", WEB18)
        o = self.autre(d, "17.0")
        self.assertEqual(
            o["base"], {"sha": self.sha["v1"], "source": "upstream_freeze"}
        )
        self.sources17 = {}
        self.ecrire_sources()
        _code, d = self.lancer("cross-version", WEB18)
        o = self.autre(d, "17.0")
        self.assertIsNone(o["to_port"])
        self.assertEqual(o["to_port_reason"], "upstream_base_unknown")

    def test_la_base_la_plus_recente_l_emporte(self):
        """Une branche de suivi amont restée en arrière ne compte pas comme
        nôtres les commits amont qu'un gel plus récent couvre."""
        _git(self.web18, "update-ref", "refs/remotes/U/18.0", self.sha["u1"])
        _code, d = self.lancer("cross-version", WEB17)
        o = self.autre(d, "18.0")
        self.assertEqual(
            o["base"], {"sha": self.sha["u2"], "source": "upstream_freeze"}
        )
        candidats = {c["sha"] for c in o["to_port"] + o["ported"]}
        self.assertEqual(candidats, {self.sha["o1"], self.sha["o2"]})
        # Un gel plus ancien que la base de fusion ne l'emporte pas.
        _git(self.web18, "update-ref", "refs/remotes/U/18.0", self.sha["u2"])
        self.sources18[WEB18]["fork-upstream-freeze-revision"] = self.sha["u1"]
        self.ecrire_sources()
        _code, d = self.lancer("cross-version", WEB17)
        o = self.autre(d, "18.0")
        self.assertEqual(
            o["base"], {"sha": self.sha["u2"], "source": "upstream_ref"}
        )

    def test_liste_des_fichiers_bornee(self):
        fichiers = {
            f"mod_a/data/f{i:03d}.txt": f"{i}\n"
            for i in range(repo_state.MAX_CHEMINS + 1)
        }
        self.commit(self.web18, fichiers, "[ADD] mod_a: data")
        _code, d = self.lancer("cross-version", WEB18)
        diff = self.autre(d, "17.0")["diff"]
        mod_a = diff["modules"]["mod_a"]
        self.assertEqual(mod_a["files"], repo_state.MAX_CHEMINS + 4)
        self.assertEqual(len(mod_a["paths"]), repo_state.MAX_CHEMINS)
        self.assertTrue(mod_a["paths_truncated"])
        self.assertTrue(diff["paths_truncated"])
        _code, d = self.lancer(
            "cross-version", WEB18, "--max-paths-total", "3"
        )
        diff = self.autre(d, "17.0")["diff"]
        self.assertEqual(
            sum(len(m["paths"]) for m in diff["modules"].values()), 3
        )
        self.assertEqual(
            diff["modules"]["mod_a"]["files"], repo_state.MAX_CHEMINS + 4
        )

    def test_historique_borne_sans_module(self):
        _code, d = self.lancer(
            "cross-version", WEB18, "--history-modules", "1"
        )
        o = self.autre(d, "17.0")
        # mod_a diffère, mod_new et mod_old n'existent que d'un côté :
        # l'ordre alphabétique départage les modules qui diffèrent.
        self.assertEqual(list(o["history"]), ["mod_a"])
        self.assertTrue(o["history_truncated"])
        _code, d = self.lancer(
            "cross-version",
            WEB18,
            "--module",
            "mod_a",
            "--history-modules",
            "0",
        )
        o = self.autre(d, "17.0")
        self.assertEqual(list(o["history"]), ["mod_a"])
        self.assertFalse(o["history_truncated"])

    def test_pas_un_fork(self):
        self.local[WEB17]["remote"] = "U"
        self.ecrire_local()
        _code, d = self.lancer("cross-version", WEB18)
        o = self.autre(d, "17.0")
        self.assertFalse(o["fork"])
        self.assertIsNone(o["to_port"])
        self.assertEqual(o["to_port_reason"], "not_a_fork")
        # Le reste de la comparaison ne dépend pas du fork.
        self.assertIn("mod_a", o["diff"]["modules"])

    def test_cible_invalide(self):
        code, d = self.lancer("cross-version", "odoo18.0/addons/R_absent")
        self.assertEqual(code, repo_state.EXIT_CIBLE)
        code, d = self.lancer("cross-version", ".")
        self.assertEqual(code, repo_state.EXIT_CIBLE)
        self.assertEqual(d["error"], "not under an odoo<V>/ tree")


class TestLectureSeule(Checkout):
    def test_aucun_clone_ne_change(self):
        """Ni ref, ni index, ni objet ne bouge pendant les trois commandes."""

        def etat(dossier):
            refs = _git(
                dossier, "for-each-ref", "--format=%(refname) %(objectname)"
            )
            gitdir = _git(dossier, "rev-parse", "--absolute-git-dir")
            fichiers = []
            for base, _dirs, noms in os.walk(gitdir):
                for nom in noms:
                    complet = os.path.join(base, nom)
                    fichiers.append((complet, os.stat(complet).st_mtime_ns))
            return refs, _git(dossier, "rev-parse", "HEAD"), sorted(fichiers)

        avant = [etat(d) for d in (self.web18, self.web17, self.racine)]
        self.lancer("--dirty")
        self.lancer("between", WEB18, self.sha["u1"], self.sha["o2"])
        self.lancer("cross-version", WEB18, "--full")
        apres = [etat(d) for d in (self.web18, self.web17, self.racine)]
        self.assertEqual(avant, apres)


if __name__ == "__main__":
    unittest.main()
