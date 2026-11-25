#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le push des dépôts du manifeste vers un remote choisi.

Les fonctions pures se testent seules ; le remote, les refspecs et le push
parallèle sur de vrais dépôts git temporaires, avec des distants nus en
« file:// ». Tous les noms, hôtes et chemins sont inventés.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from script.git import push_remote as pr


def _git(cwd, *args):
    """Lance git sans dépendre de la configuration de l'hôte ; rend stdout."""
    return subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "init.defaultBranch=principale",
            *args,
        ],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


class TestProprietaire(unittest.TestCase):
    def test_formes_d_url(self):
        for url, attendu in (
            ("https://forge.example.invalid/Proprio/", "Proprio"),
            ("https://forge.example.invalid/Proprio", "Proprio"),
            ("ssh://git@forge.example.invalid:2222/Proprio/", "Proprio"),
            ("git@forge.example.invalid:Proprio/", "Proprio"),
            ("https://forge.example.invalid/groupe/Proprio/", "Proprio"),
        ):
            with self.subTest(url=url):
                self.assertEqual(pr.proprietaire_de(url), attendu)

    def test_sans_proprietaire(self):
        for url in (None, "", "..", "../", "https://forge.example.invalid/"):
            with self.subTest(url=url):
                self.assertIsNone(pr.proprietaire_de(url))

    def test_url_cible(self):
        self.assertEqual(
            pr.url_cible("ssh://git@forge.invalid:2222/", "Proprio", "d"),
            "ssh://git@forge.invalid:2222/Proprio/d.git",
        )
        self.assertEqual(
            pr.url_cible("https://forge.invalid", "Proprio", "d.git"),
            "https://forge.invalid/Proprio/d.git",
        )

    def test_plan_remote_ecarte_un_projet_sans_proprietaire(self):
        projets = [
            {"chemin": "a", "nom": "a.git", "proprietaire": "P"},
            {"chemin": "b", "nom": "b.git", "proprietaire": None},
        ]
        poses, ecartes = pr.plan_remote(projets, "forge", "https://f.invalid")
        self.assertEqual(
            [(p["chemin"], u) for p, u in poses],
            [("a", "https://f.invalid/P/a.git")],
        )
        self.assertEqual([p["chemin"] for p, _ in ecartes], ["b"])


class _Depots(unittest.TestCase):
    """Un distant d'origine nu, un clone, et une forge nue vide."""

    def setUp(self):
        self.dossier = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dossier, True)
        plafond = patch.dict(
            os.environ, {"GIT_CEILING_DIRECTORIES": self.dossier}
        )
        plafond.start()
        self.addCleanup(plafond.stop)
        self.origine = os.path.join(self.dossier, "origine.git")
        self.forge = os.path.join(self.dossier, "forge.git")
        self.clone = os.path.join(self.dossier, "clone")
        _git(self.dossier, "init", "-q", "--bare", self.origine)
        _git(self.dossier, "init", "-q", "--bare", self.forge)
        _git(self.dossier, "init", "-q", self.clone)
        _git(self.clone, "remote", "add", "Orig", self.origine)
        self.commit("un")
        _git(self.clone, "push", "-q", "Orig", "HEAD:X.0", "HEAD:X.0_dev")
        _git(self.clone, "tag", "v1")
        _git(self.clone, "fetch", "-q", "Orig")
        _git(self.clone, "checkout", "-q", "--detach")

    def commit(self, contenu):
        with open(os.path.join(self.clone, "a.txt"), "w") as fh:
            fh.write(contenu)
        _git(self.clone, "add", "a.txt")
        _git(self.clone, "commit", "-q", "-m", contenu)

    def refs_forge(self):
        return _git(self.forge, "for-each-ref", "--format=%(refname)").split()


class TestPoserRemote(_Depots):
    def test_ajoute_puis_present(self):
        url = f"file://{self.forge}"
        self.assertEqual(
            pr.poser_remote(self.clone, "forge", url), ("ajoute", None)
        )
        self.assertEqual(
            _git(self.clone, "config", "remote.forge.skipFetchAll"), "true"
        )
        self.assertEqual(
            _git(self.clone, "config", "remote.forge.tagOpt"), "--no-tags"
        )
        self.assertEqual(
            pr.poser_remote(self.clone, "forge", url)[0], "present"
        )

    def test_autre_url_n_est_pas_touchee(self):
        _git(self.clone, "remote", "add", "forge", "file:///ailleurs.git")
        etat, en_place = pr.poser_remote(
            self.clone, "forge", f"file://{self.forge}"
        )
        self.assertEqual(
            (etat, en_place), ("autre_url", "file:///ailleurs.git")
        )
        self.assertEqual(
            _git(self.clone, "remote", "get-url", "forge"),
            "file:///ailleurs.git",
        )

    def test_hors_clone(self):
        self.assertEqual(
            pr.poser_remote(os.path.join(self.dossier, "absent"), "f", "u")[0],
            "non_clone",
        )


class TestRefspecs(_Depots):
    def test_mode_manifeste_pousse_head_sur_la_branche(self):
        self.assertEqual(
            pr.refspecs(self.clone, pr.MODE_MANIFESTE, "Orig", "X.0"),
            (["HEAD:refs/heads/X.0"], None),
        )

    def test_sans_branche_rien_a_pousser(self):
        self.assertEqual(
            pr.refspecs(self.clone, pr.MODE_MANIFESTE, "Orig", None),
            ([], "no branch to push"),
        )

    def test_mode_tout_sans_doublon_de_destination(self):
        _git(self.clone, "branch", "X.0_dev")
        specs, motif = pr.refspecs(self.clone, pr.MODE_TOUT, "Orig", "X.0")
        self.assertIsNone(motif)
        destinations = [s.split(":", 1)[1] for s in specs]
        self.assertEqual(len(destinations), len(set(destinations)))
        self.assertIn("HEAD:refs/heads/X.0", specs)
        # La branche locale l'emporte sur la branche de suivi homonyme.
        self.assertIn("refs/heads/X.0_dev:refs/heads/X.0_dev", specs)
        self.assertNotIn("refs/remotes/Orig/X.0_dev:refs/heads/X.0_dev", specs)
        self.assertIn("refs/tags/*:refs/tags/*", specs)


class TestPousser(_Depots):
    def setUp(self):
        super().setUp()
        pr.poser_remote(self.clone, "forge", f"file://{self.forge}")

    def test_mode_manifeste(self):
        specs, _ = pr.refspecs(self.clone, pr.MODE_MANIFESTE, "Orig", "X.0")
        (r,) = pr.pousser_en_parallele(
            [{"chemin": self.clone, "remote": "forge", "specs": specs}]
        )
        self.assertEqual(r["code"], 0, r["erreur"])
        self.assertEqual(self.refs_forge(), ["refs/heads/X.0"])

    def test_mode_tout_pousse_branches_et_etiquettes(self):
        specs, _ = pr.refspecs(self.clone, pr.MODE_TOUT, "Orig", "X.0")
        (r,) = pr.pousser_en_parallele(
            [{"chemin": self.clone, "remote": "forge", "specs": specs}]
        )
        self.assertEqual(r["code"], 0, r["erreur"])
        self.assertEqual(
            sorted(self.refs_forge()),
            [
                "refs/heads/X.0",
                "refs/heads/X.0_dev",
                "refs/heads/principale",
                "refs/tags/v1",
            ],
        )

    def test_jamais_de_force(self):
        """Un distant qui porte des commits que le clone n'a pas refuse la
        mise à jour : le refus est rapporté, rien n'est écrasé."""
        autre = os.path.join(self.dossier, "autre")
        _git(self.dossier, "clone", "-q", self.forge, autre)
        with open(os.path.join(autre, "b.txt"), "w") as fh:
            fh.write("ailleurs")
        _git(autre, "add", "b.txt")
        _git(autre, "commit", "-q", "-m", "ailleurs")
        _git(autre, "push", "-q", "origin", "HEAD:X.0")
        tete = _git(self.forge, "rev-parse", "X.0")
        specs, _ = pr.refspecs(self.clone, pr.MODE_MANIFESTE, "Orig", "X.0")
        (r,) = pr.pousser_en_parallele(
            [{"chemin": self.clone, "remote": "forge", "specs": specs}]
        )
        self.assertNotEqual(r["code"], 0)
        self.assertEqual(_git(self.forge, "rev-parse", "X.0"), tete)

    def test_un_echec_passager_est_retente_une_fois_seul(self):
        """Le premier essai échoue (remote absent), le second passe : le
        résultat dit deux essais, et le suivi ne voit que le définitif."""
        manque = os.path.join(self.dossier, "tardif.git")
        cible = {
            "chemin": self.clone,
            "remote": f"file://{manque}",
            "specs": ["HEAD:refs/heads/X.0"],
        }
        appels = []
        original = pr.pousser_un

        def pousser(chemin, remote, specs, delai=None):
            appels.append(remote)
            if len(appels) == 1:
                _git(self.dossier, "init", "-q", "--bare", manque)
                return 1, "forge occupée"
            return original(chemin, remote, specs)

        vus = []
        with patch.object(pr, "pousser_un", side_effect=pousser):
            (r,) = pr.pousser_en_parallele([cible], suivi=vus.append)
        self.assertEqual((r["code"], r["essais"]), (0, 2))
        self.assertEqual(len(appels), 2)
        self.assertEqual([v["essais"] for v in vus], [2])

    def test_un_refus_reel_reste_un_echec(self):
        """Un distant en avance refuse deux fois : jamais de force."""
        autre = os.path.join(self.dossier, "autre")
        _git(self.dossier, "clone", "-q", self.forge, autre)
        with open(os.path.join(autre, "b.txt"), "w") as fh:
            fh.write("ailleurs")
        _git(autre, "add", "b.txt")
        _git(autre, "commit", "-q", "-m", "ailleurs")
        _git(autre, "push", "-q", "origin", "HEAD:X.0")
        specs, _ = pr.refspecs(self.clone, pr.MODE_MANIFESTE, "Orig", "X.0")
        (r,) = pr.pousser_en_parallele(
            [{"chemin": self.clone, "remote": "forge", "specs": specs}]
        )
        self.assertNotEqual(r["code"], 0)
        self.assertEqual(r["essais"], 2)

    def test_sans_reessai(self):
        (r,) = pr.pousser_en_parallele(
            [
                {
                    "chemin": self.clone,
                    "remote": "file:///absent.invalid.git",
                    "specs": ["HEAD:refs/heads/X.0"],
                }
            ],
            reessais=0,
        )
        self.assertEqual(r["essais"], 1)

    def test_resultats_dans_l_ordre_et_suivi(self):
        """Plusieurs pushes en parallèle : un résultat par cible, dans
        l'ordre des cibles, et le suivi appelé pour chacun."""
        cibles = []
        for i in range(5):
            nu = os.path.join(self.dossier, f"f{i}.git")
            _git(self.dossier, "init", "-q", "--bare", nu)
            cibles.append(
                {
                    "chemin": self.clone,
                    "remote": f"file://{nu}",
                    "specs": [f"HEAD:refs/heads/b{i}"],
                }
            )
        vus = []
        resultats = pr.pousser_en_parallele(cibles, jobs=3, suivi=vus.append)
        self.assertEqual(
            [r["remote"] for r in resultats], [c["remote"] for c in cibles]
        )
        self.assertTrue(all(r["code"] == 0 for r in resultats))
        self.assertEqual(len(vus), 5)


class TestProjetsActifs(unittest.TestCase):
    """Les projets clonés de la version active, dans un checkout factice."""

    def setUp(self):
        self.dossier = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dossier, True)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.dossier)
        plafond = patch.dict(
            os.environ, {"GIT_CEILING_DIRECTORIES": self.dossier}
        )
        plafond.start()
        self.addCleanup(plafond.stop)
        os.mkdir("manifest")
        with open(".odoo-version", "w") as fh:
            fh.write("X.0")
        with open(
            os.path.join("manifest", "git_manifest_odooX.0.xml"), "w"
        ) as fh:
            fh.write(
                "<manifest>\n"
                '  <remote name="Orig" fetch="https://forge.example.invalid/Proprio/"/>\n'
                '  <default remote="Orig" revision="X.0"/>\n'
                '  <project name="a.git" path="c/a" revision="X.0_dev_maj_20990101"/>\n'
                '  <project name="b.git" path="c/b"/>\n'
                '  <project name="absent.git" path="c/absent"/>\n'
                "</manifest>\n"
            )
        for nom in ("a", "b"):
            _git(self.dossier, "init", "-q", os.path.join("c", nom))
        defaut = patch.object(
            pr.git_freeze_manifest, "default_sources", return_value=[]
        )
        defaut.start()
        self.addCleanup(defaut.stop)

    def test_projets_clones_avec_branche_et_proprietaire(self):
        projets = pr.projets_actifs()
        self.assertEqual(
            [
                (
                    p["chemin"],
                    p["nom"],
                    p["remote"],
                    p["branche"],
                    p["proprietaire"],
                )
                for p in projets
            ],
            [
                ("c/a", "a.git", "Orig", "X.0_dev", "Proprio"),
                ("c/b", "b.git", "Orig", "X.0", "Proprio"),
            ],
        )

    def test_remotes_des_clones(self):
        _git(self.dossier, "-C", "c/a", "remote", "add", "forge", "file:///x")
        _git(self.dossier, "-C", "c/b", "remote", "add", "forge", "file:///y")
        _git(self.dossier, "-C", "c/b", "remote", "add", "Orig", "file:///z")
        self.assertEqual(
            pr.remotes_des_clones(["c/a", "c/b"]), {"Orig": 1, "forge": 2}
        )


class TestGetConfig(unittest.TestCase):
    def test_defauts(self):
        config = pr.get_config(["--remote", "forge"])
        self.assertEqual(
            (config.remote, config.url, config.mode, config.jobs),
            ("forge", None, pr.MODE_MANIFESTE, pr.PARALLELE),
        )
        self.assertFalse(config.dry_run or config.unshallow)

    def test_remote_obligatoire(self):
        with patch("sys.stderr"), self.assertRaises(SystemExit):
            pr.get_config([])


if __name__ == "__main__":
    unittest.main()
