#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Comparer deux gels : lecture des côtés, comparaison, statistiques.

Les côtés se lisent sur de vrais dépôts git temporaires : un checkout qui
committe deux gels successifs dans `manifest/`, et des clones dont les
commits avancent, reculent ou manquent.

Tous les noms de dépôts, chemins et commits sont inventés.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from script.git import git_freeze_diff as fd


def _git(cwd, *args):
    """Lance git sans dépendre de la configuration de l'hôte. Rend la
    sortie."""
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


def _manifeste(projets):
    """Un fichier source : `projets` est une suite de (nom, chemin, sha)."""
    lignes = ['<?xml version="1.0" encoding="UTF-8" ?>', "<manifest>"]
    for nom, chemin, sha in projets:
        gel = f' freeze-revision="{sha}"' if sha else ""
        lignes.append(
            f'  <project name="{nom}" path="{chemin}" revision="18.0"{gel}/>'
        )
    lignes.append("</manifest>")
    return "\n".join(lignes) + "\n"


class TestLecture(unittest.TestCase):
    """La table d'un côté, tirée du texte des fichiers sources."""

    SHA = "1" * 40

    def test_un_projet_commente_est_ignore(self):
        texte = _manifeste([("a", "x/a", self.SHA)]).replace(
            "</manifest>",
            f'<!-- <project name="b" path="x/b" freeze-revision="{self.SHA}"'
            "/> -->\n</manifest>",
        )
        entrees = fd._entries_from_texts([("m.xml", texte)])
        self.assertEqual(list(entrees), ["a+x/a"])
        self.assertEqual(entrees["a+x/a"]["sha"], self.SHA)
        self.assertEqual(entrees["a+x/a"]["branch"], "18.0")
        self.assertEqual(entrees["a+x/a"]["file"], "m.xml")

    def test_la_derniere_definition_l_emporte_comme_dans_la_fusion(self):
        avec = _manifeste([("a", "x/a", self.SHA)])
        sans = _manifeste([("a", "x/a", None)])
        entrees = fd._entries_from_texts([("1.xml", avec), ("2.xml", sans)])
        self.assertIsNone(entrees["a+x/a"]["sha"])
        self.assertEqual(entrees["a+x/a"]["file"], "2.xml")
        entrees = fd._entries_from_texts([("2.xml", sans), ("1.xml", avec)])
        self.assertEqual(entrees["a+x/a"]["sha"], self.SHA)

    def test_un_projet_sans_chemin_prend_son_nom(self):
        texte = '<manifest><project name="seul" revision="18.0"/></manifest>'
        (entree,) = fd._entries_from_texts([("m.xml", texte)]).values()
        self.assertEqual(entree["path"], "seul")

    def test_ordre_de_la_fusion_fichiers_actifs_en_dernier(self):
        with patch.object(
            fd, "active_sources", return_value=["m/b.xml", "m/a.xml"]
        ):
            self.assertEqual(
                fd.merge_order(
                    "/r", ["m/a.xml", "m/z.xml", "m/b.xml", "m/c.xml"]
                ),
                ["m/c.xml", "m/z.xml", "m/b.xml", "m/a.xml"],
            )
        with patch.object(fd, "active_sources", side_effect=OSError):
            self.assertEqual(
                fd.merge_order("/r", ["m/b.xml", "m/a.xml"]),
                ["m/a.xml", "m/b.xml"],
            )


class TestRegroupement(unittest.TestCase):
    def test_par_extension(self):
        self.assertEqual(fd.group_key("a/b/c.PY", "ext"), ".py")
        self.assertEqual(fd.group_key("Makefile", "ext"), "(none)")
        self.assertEqual(fd.group_key(".gitignore", "ext"), "(none)")

    def test_par_module(self):
        self.assertEqual(fd.group_key("web_x/static/a.js", "module"), "web_x")
        self.assertEqual(
            fd.group_key("addons/web/static/a.js", "module"), "addons/web"
        )
        self.assertEqual(
            fd.group_key("odoo/addons/base/models/a.py", "module"),
            "odoo/addons/base",
        )
        self.assertEqual(fd.group_key("README.md", "module"), "(root)")

    def test_par_dossier(self):
        self.assertEqual(fd.group_key("odoo/addons/b/a.py", "dir"), "odoo")

    def test_groupes_tries_du_plus_gros_au_plus_petit(self):
        fichiers = [(1, 0, "a.py"), (10, 5, "b.xml"), (2, 2, "c.py")]
        self.assertEqual(
            fd.group_files(fichiers, "ext"),
            [(".xml", 1, 10, 5), (".py", 2, 3, 2)],
        )


class TestComparaison(unittest.TestCase):
    A, B, C = "a" * 40, "b" * 40, "c" * 40

    def entree(self, sha, chemin="x/p", **extra):
        return dict(
            {"name": "p", "path": chemin, "sha": sha, "branch": "18.0"},
            **extra,
        )

    def test_statuts(self):
        gauche = {
            "same": self.entree(self.A, "x/same"),
            "chg": self.entree(self.A, "x/chg"),
            "gone": self.entree(self.A, "x/gone"),
            "absent": self.entree(self.A, "x/absent"),
            "rien": self.entree(None, "x/rien"),
        }
        droite = {
            "same": self.entree(self.A, "x/same", cloned=True),
            "chg": self.entree(self.B, "x/chg", cloned=True),
            "new": self.entree(self.C, "x/new", cloned=True),
            "absent": self.entree(None, "x/absent", cloned=False),
            "rien": self.entree(None, "x/rien", cloned=False),
        }
        statuts = {
            lg["key"]: lg["status"]
            for lg in fd.compare(gauche, droite, clones_side="right")
        }
        self.assertEqual(
            statuts,
            {
                "same": fd.STATUS_SAME,
                "chg": fd.STATUS_CHANGED,
                "gone": fd.STATUS_GONE,
                "new": fd.STATUS_NEW,
                "absent": fd.STATUS_NOT_CLONED,
            },
        )

    def test_clones_a_gauche(self):
        gauche = {"k": self.entree(None, cloned=False)}
        droite = {"k": self.entree(self.A)}
        (ligne,) = fd.compare(gauche, droite, clones_side="left")
        self.assertEqual(ligne["status"], fd.STATUS_NOT_CLONED)
        (ligne,) = fd.compare(gauche, droite)
        self.assertEqual(ligne["status"], fd.STATUS_NEW)

    def test_sans_clones_un_commit_disparu_est_un_degel(self):
        gauche = {"k": self.entree(self.A)}
        droite = {"k": self.entree(None)}
        (ligne,) = fd.compare(gauche, droite)
        self.assertEqual(ligne["status"], fd.STATUS_GONE)

    def test_lignes_triees_par_chemin(self):
        gauche = {
            "k1": self.entree(self.A, "z/p"),
            "k2": self.entree(self.A, "a/p"),
        }
        droite = {
            "k1": self.entree(self.B, "z/p"),
            "k2": self.entree(self.B, "a/p"),
        }
        self.assertEqual(
            [lg["path"] for lg in fd.compare(gauche, droite)], ["a/p", "z/p"]
        )

    def test_plage_d_historique(self):
        base = {"old": self.A, "new": self.B}
        self.assertEqual(
            fd.history_range(dict(base, stats={"ahead": 2, "behind": 0})),
            f"{self.A}..{self.B}",
        )
        self.assertEqual(
            fd.history_range(dict(base, stats={"ahead": 0, "behind": 2})),
            f"{self.B}..{self.A}",
        )
        self.assertEqual(
            fd.history_range(dict(base, stats={"ahead": 1, "behind": 1})),
            f"{self.A}...{self.B}",
        )


class _Checkout(unittest.TestCase):
    """Un checkout ERPLibre inventé, deux clones et un distant nu.

    Un premier commit ne porte aucun gel. Le clone « alpha » a quatre commits et un distant qui en a un
    cinquième ; « beta » en a deux. Le premier gel committé pose alpha
    sur son 1er commit, beta sur son 1er et « gamma » (jamais cloné) sur un
    commit inventé ; le second pose alpha sur son 3e, garde beta et dégèle
    gamma. Le HEAD de chaque clone est son dernier commit.
    """

    def setUp(self):
        self.racine = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.racine, True)
        plafond = patch.dict(
            os.environ, {"GIT_CEILING_DIRECTORIES": self.racine}
        )
        plafond.start()
        self.addCleanup(plafond.stop)
        _git(self.racine, "init", "-q")
        _git(self.racine, "commit", "-q", "--allow-empty", "-m", "départ")
        os.makedirs(os.path.join(self.racine, "manifest"))
        self.alpha = self.clone("c/alpha", 4)
        self.beta = self.clone("c/beta", 2)
        self.gamma = "9" * 40
        nu = os.path.join(self.racine, "distant_alpha.git")
        _git(self.racine, "clone", "-q", "--bare", self.chemin("c/alpha"), nu)
        travail = os.path.join(self.racine, "travail")
        _git(self.racine, "clone", "-q", nu, travail)
        self.fichier(os.path.join(travail, "f.txt"), "distant")
        _git(travail, "commit", "-q", "-am", "distant")
        _git(travail, "push", "-q", "origin", "HEAD")
        self.distant = _git(travail, "rev-parse", "HEAD")
        shutil.rmtree(travail)
        _git(self.chemin("c/alpha"), "remote", "add", "origin", nu)

        self.gel(
            [
                ("alpha", "c/alpha", self.alpha[0]),
                ("beta", "c/beta", self.beta[0]),
                ("gamma", "c/gamma", self.gamma),
            ],
            "premier gel",
        )
        self.gel(
            [
                ("alpha", "c/alpha", self.alpha[2]),
                ("beta", "c/beta", self.beta[0]),
                ("gamma", "c/gamma", None),
            ],
            "second gel",
        )
        _git(self.racine, "commit", "-q", "--allow-empty", "-m", "sans gel")

    def chemin(self, relatif):
        return os.path.join(self.racine, relatif)

    def fichier(self, chemin, contenu):
        with open(chemin, "w") as fh:
            fh.write(contenu)

    def clone(self, relatif, commits):
        chemin = self.chemin(relatif)
        os.makedirs(chemin)
        _git(chemin, "init", "-q")
        shas = []
        for i in range(commits):
            self.fichier(os.path.join(chemin, f"f{i}.py"), "x\n" * (i + 1))
            self.fichier(os.path.join(chemin, "f.txt"), f"{i}\n")
            _git(chemin, "add", "-A")
            _git(chemin, "commit", "-q", "-m", f"commit {i}")
            shas.append(_git(chemin, "rev-parse", "HEAD"))
        return shas

    def gel(self, projets, message):
        self.fichier(
            os.path.join(self.racine, "manifest", "git_manifest_t.xml"),
            _manifeste(projets),
        )
        _git(self.racine, "add", "manifest")
        _git(self.racine, "commit", "-q", "-m", message)

    def definitions(self):
        return fd.read_worktree(self.racine)

    def build(self, gauche, droite):
        with patch.object(
            fd,
            "default_definitions",
            side_effect=lambda r: fd.read_worktree(r),
        ):
            return fd.build(self.racine, gauche, droite, jobs=2)

    @staticmethod
    def par_chemin(rapport):
        return {lg["path"]: lg for lg in rapport["rows"]}


class TestTotaux(unittest.TestCase):
    """La ligne des totaux du sommaire, sur des lignes inventées."""

    @staticmethod
    def ligne(missing=(), ahead=None, behind=None, files=()):
        return {
            "stats": {
                "missing": list(missing),
                "ahead": ahead,
                "behind": behind,
                "files": list(files),
            }
        }

    def test_somme_des_commits_fichiers_et_lignes(self):
        lignes = [
            self.ligne(ahead=3, behind=1, files=[(10, 2, "a"), (0, 4, "b")]),
            self.ligne(ahead=2, behind=0, files=[(5, 0, "c")]),
        ]
        self.assertEqual(
            fd._summary_totals(lignes),
            ["Total of the 2 changed: +5 -1 commits, 3 files, +15 -6 lines"],
        )

    def test_commit_manquant_et_clone_superficiel_mis_de_cote(self):
        lignes = [
            self.ligne(ahead=1, behind=0, files=[(1, 1, "a")]),
            self.ligne(missing=["old"]),
            self.ligne(files=[(7, 3, "b")]),
        ]
        total, note = fd._summary_totals(lignes)
        self.assertEqual(
            total,
            "Total of the 3 changed: +1 -0 commits, 2 files, +8 -4 lines",
        )
        self.assertIn("1 with a missing commit, in no total", note)
        self.assertIn("1 without a commit count (shallow)", note)

    def test_rien_de_change(self):
        self.assertEqual(fd._summary_totals([]), [])


class TestDefinitionsDesClones(unittest.TestCase):
    SHA = "2" * 40

    def test_seuls_les_fichiers_de_la_version_active(self):
        racine = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, racine, True)
        os.mkdir(os.path.join(racine, "manifest"))
        with open(os.path.join(racine, ".odoo-version"), "w") as fh:
            fh.write("X.0\n")
        for fichier, nom in (
            ("git_manifest_odooX.0.xml", "un"),
            ("git_manifest_odooX.0_dev.xml", "deux"),
            ("git_manifest_erplibre_odoo.xml", "commun"),
            ("git_manifest_odooY.0.xml", "autre"),
        ):
            with open(os.path.join(racine, "manifest", fichier), "w") as fh:
                fh.write(_manifeste([(nom, f"c/{nom}", None)]))
        depart = os.getcwd()
        self.assertEqual(
            sorted(fd.default_definitions(racine)), ["deux+c/deux", "un+c/un"]
        )
        self.assertEqual(os.getcwd(), depart)

    def test_l_autre_cote_n_ajoute_que_ses_projets_geles(self):
        propres = {"a+x/a": {"path": "x/a", "sha": None}}
        autre = {
            "a+x/a": {"path": "x/a", "sha": self.SHA},
            "b+x/b": {"path": "x/b", "sha": self.SHA},
            "c+x/c": {"path": "x/c", "sha": None},
        }
        with patch.object(fd, "default_definitions", return_value=propres):
            definitions = fd._clone_definitions("/r", [autre, None])
        self.assertEqual(sorted(definitions), ["a+x/a", "b+x/b"])
        self.assertIsNone(definitions["a+x/a"]["sha"])


class TestLectureDesCotes(_Checkout):
    def test_une_revision_lit_ses_fichiers_committes(self):
        avant = fd.read_ref(self.racine, "HEAD~2")
        apres = fd.read_ref(self.racine, "HEAD")
        self.assertEqual(avant["alpha+c/alpha"]["sha"], self.alpha[0])
        self.assertEqual(avant["gamma+c/gamma"]["sha"], self.gamma)
        self.assertEqual(apres["alpha+c/alpha"]["sha"], self.alpha[2])
        self.assertIsNone(apres["gamma+c/gamma"]["sha"])

    def test_une_revision_inconnue_est_refusee(self):
        with self.assertRaises(ValueError):
            fd.read_side(self.racine, "pas-une-revision")

    def test_le_worktree_lit_le_disque(self):
        self.gel([("alpha", "c/alpha", self.alpha[3])], "x")
        self.assertEqual(
            fd.read_worktree(self.racine)["alpha+c/alpha"]["sha"],
            self.alpha[3],
        )

    def test_les_clones_rendent_leur_head(self):
        clones = fd.read_clones(self.racine, self.definitions(), jobs=2)
        self.assertEqual(clones["alpha+c/alpha"]["sha"], self.alpha[3])
        self.assertTrue(clones["alpha+c/alpha"]["cloned"])
        self.assertFalse(clones["gamma+c/gamma"]["cloned"])
        self.assertIsNone(clones["gamma+c/gamma"]["sha"])

    def test_un_dossier_non_clone_ne_rend_pas_le_commit_du_checkout(self):
        os.makedirs(self.chemin("c/gamma"))
        clones = fd.read_clones(self.racine, self.definitions(), jobs=2)
        self.assertIsNone(clones["gamma+c/gamma"]["sha"])

    def test_clone_modifie_et_sur_une_branche(self):
        self.fichier(os.path.join(self.chemin("c/beta"), "f.txt"), "sale")
        etat = fd.inspect_clone(self.chemin("c/beta"))
        self.assertTrue(etat["dirty"])
        self.assertEqual(etat["head_branch"], "principale")
        _git(self.chemin("c/alpha"), "checkout", "-q", "--detach")
        self.assertIsNone(
            fd.inspect_clone(self.chemin("c/alpha"))["head_branch"]
        )


class TestHistoriqueDesGels(_Checkout):
    def test_commits_de_gel_du_plus_recent_au_plus_ancien(self):
        gels = fd.freeze_commits(self.racine)
        self.assertEqual(
            [s for _, _, s in gels], ["second gel", "premier gel"]
        )

    def test_un_degel_ou_une_branche_changee_n_est_pas_un_gel(self):
        chemin = os.path.join(self.racine, "manifest", "une_ligne.xml")
        self.fichier(chemin, _manifeste([("beta", "c/beta", self.beta[1])]))
        _git(self.racine, "add", "manifest")
        _git(self.racine, "commit", "-q", "-m", "gel une ligne")
        with open(chemin) as fh:
            texte = fh.read()
        self.fichier(
            chemin, texte.replace('revision="18.0"', 'revision="18.1"')
        )
        _git(self.racine, "commit", "-q", "-am", "branche seule")
        self.fichier(chemin, _manifeste([("beta", "c/beta", None)]))
        _git(self.racine, "commit", "-q", "-am", "dégel")
        self.assertEqual(
            [s for _, _, s in fd.freeze_commits(self.racine)],
            ["gel une ligne", "second gel", "premier gel"],
        )

    def test_gel_precedent(self):
        avant, apres = fd.previous_freeze(self.racine)
        self.assertEqual(avant, _git(self.racine, "rev-parse", "HEAD~2"))
        self.assertEqual(apres, _git(self.racine, "rev-parse", "HEAD~1"))

    def test_gel_non_committe(self):
        self.assertEqual(fd.uncommitted_freeze(self.racine), [])
        self.fichier(
            os.path.join(self.racine, "manifest", "git_manifest_t.xml"),
            _manifeste([("alpha", "c/alpha", self.alpha[3])]),
        )
        self.assertEqual(
            fd.uncommitted_freeze(self.racine),
            ["alpha+c/alpha", "beta+c/beta"],
        )


class TestRapport(_Checkout):
    def test_gel_precedent_vers_dernier(self):
        rapport = self.build("HEAD~2", "HEAD~1")
        lignes = self.par_chemin(rapport)
        self.assertEqual(lignes["c/alpha"]["status"], fd.STATUS_CHANGED)
        self.assertEqual(lignes["c/beta"]["status"], fd.STATUS_SAME)
        self.assertEqual(lignes["c/gamma"]["status"], fd.STATUS_GONE)
        stats = lignes["c/alpha"]["stats"]
        self.assertEqual((stats["ahead"], stats["behind"]), (2, 0))
        self.assertEqual(
            sorted(f for _, _, f in stats["files"]),
            ["f.txt", "f1.py", "f2.py"],
        )

    def test_gel_committe_vers_clones(self):
        rapport = self.build("HEAD", fd.CLONES)
        lignes = self.par_chemin(rapport)
        self.assertEqual(lignes["c/alpha"]["stats"]["ahead"], 1)
        self.assertEqual(lignes["c/beta"]["stats"]["ahead"], 1)
        self.assertNotIn("c/gamma", lignes)
        self.assertEqual(rapport["frozen"]["from"], 2)

    def test_un_chemin_gele_jamais_clone(self):
        rapport = self.build("HEAD~2", fd.CLONES)
        lignes = self.par_chemin(rapport)
        self.assertEqual(lignes["c/gamma"]["status"], fd.STATUS_NOT_CLONED)

    def test_retour_en_arriere(self):
        rapport = self.build(fd.CLONES, "HEAD~1")
        stats = self.par_chemin(rapport)["c/alpha"]["stats"]
        self.assertEqual((stats["ahead"], stats["behind"]), (0, 1))
        sommaire = "\n".join(fd.render_summary(rapport))
        self.assertIn("+0 -1 rollback", sommaire)
        self.assertIn(
            "Total of the 2 changed: +0 -2 commits, 4 files, +2 -8 lines",
            sommaire,
        )

    def test_le_sommaire_signale_clones_modifies_et_gel_non_committe(self):
        self.fichier(os.path.join(self.chemin("c/beta"), "f.txt"), "sale")
        self.fichier(
            os.path.join(self.racine, "manifest", "git_manifest_t.xml"),
            _manifeste([("alpha", "c/alpha", self.alpha[3])]),
        )
        rapport = self.build("HEAD", fd.CLONES)
        sommaire = "\n".join(fd.render_summary(rapport))
        self.assertIn("1 clones have uncommitted changes", sommaire)
        self.assertIn("  - c/beta", sommaire)
        self.assertIn("2 freeze-revision changes not committed", sommaire)
        self.assertIn("ERPLibre HEAD:", sommaire)
        self.assertIn("dirty", sommaire)

    def test_un_cote_sans_gel_est_annonce(self):
        rapport = self.build("HEAD~3", fd.CLONES)
        self.assertIn(
            "HEAD~3 holds no freeze-revision",
            "\n".join(fd.render_summary(rapport)),
        )

    def test_commit_absent_puis_recherche(self):
        self.gel([("alpha", "c/alpha", self.distant)], "gel distant")
        rapport = self.build("HEAD~1", "HEAD")
        ligne = self.par_chemin(rapport)["c/alpha"]
        self.assertEqual(ligne["stats"]["missing"], ["new"])
        self.assertIn("missing new", "\n".join(fd.render_summary(rapport)))
        self.assertEqual(fd.missing_rows(rapport["rows"]), [ligne])
        restes = fd.fetch_missing(self.racine, rapport["rows"], jobs=2)
        self.assertEqual(restes, {})
        self.assertEqual(ligne["stats"]["missing"], [])
        self.assertEqual(ligne["stats"]["ahead"], 2)

    def test_un_commit_introuvable_reste_signale(self):
        self.gel([("alpha", "c/alpha", "8" * 40)], "gel inventé")
        rapport = self.build("HEAD~1", "HEAD")
        restes = fd.fetch_missing(self.racine, rapport["rows"], jobs=2)
        self.assertEqual(restes, {"c/alpha": ["8" * 40]})

    def test_detail_borne_ou_complet(self):
        rapport = self.build("HEAD~2", "HEAD~1")
        self.assertEqual(fd.auto_stat_count(rapport), 0)
        complet = "\n".join(fd.render_details(rapport, stat_count=0))
        self.assertIn("3 files changed", complet)
        self.assertIn("by ext:", complet)
        borne = "\n".join(fd.render_details(rapport, stat_count=1))
        self.assertIn("diffstat limited to 1 of 3 files", borne)
        journal = "\n".join(fd.render_details(rapport, log=True))
        self.assertIn("commit 2", journal)
        self.assertIn("commit 1", journal)
        self.assertNotIn("commit 0", journal)

    def test_journal_numerote_comme_le_tableau(self):
        rapport = self.build("HEAD~2", "HEAD~1")
        journal = fd.render_logs(rapport)
        self.assertTrue(journal[0].startswith("[1] c/alpha"))

    def test_beaucoup_de_fichiers_bornent_le_diffstat(self):
        rapport = self.build("HEAD~2", "HEAD~1")
        with patch.object(fd, "AUTO_FULL_FILES", 2):
            self.assertEqual(fd.auto_stat_count(rapport), fd.AUTO_STAT_COUNT)

    def test_choix_des_lignes(self):
        rapport = self.build("HEAD", fd.CLONES)
        self.assertEqual(
            [lg["path"] for lg in fd.select_rows(rapport, "all")],
            ["c/alpha", "c/beta"],
        )
        self.assertEqual(
            [lg["path"] for lg in fd.select_rows(rapport, "2")], ["c/beta"]
        )
        self.assertEqual(
            [lg["path"] for lg in fd.select_rows(rapport, "c/alpha/")],
            ["c/alpha"],
        )
        self.assertEqual(fd.select_rows(rapport, "9"), [])

    def test_l_historique_prefere_tig(self):
        rapport = self.build("HEAD", fd.CLONES)
        ligne = fd.select_rows(rapport, "1")[0]
        with patch.object(
            fd.shutil, "which", return_value="/bin/tig"
        ), patch.object(fd.subprocess, "Popen") as popen:
            popen.return_value.wait.return_value = 0
            fd.open_history(self.racine, ligne)
        self.assertEqual(popen.call_args[0][0][0], "tig")
        self.assertEqual(
            popen.call_args[1]["cwd"], os.path.join(self.racine, "c/alpha")
        )
        with patch.object(fd.shutil, "which", return_value=None), patch.object(
            fd.subprocess, "Popen"
        ) as popen:
            popen.return_value.wait.return_value = 0
            fd.open_history(self.racine, ligne)
        self.assertEqual(popen.call_args[0][0][:2], ["git", "log"])

    def test_un_ctrl_c_pendant_tig_ne_sort_pas_du_menu(self):
        rapport = self.build("HEAD", fd.CLONES)
        ligne = fd.select_rows(rapport, "1")[0]
        with patch.object(fd.subprocess, "Popen") as popen:
            popen.return_value.wait.side_effect = [KeyboardInterrupt, -2]
            self.assertEqual(fd.open_history(self.racine, ligne), -2)

    def test_un_dossier_qui_n_est_pas_un_clone(self):
        """git ne doit pas tourner dans le checkout : ni ses commits, ni
        ses distants."""
        os.makedirs(self.chemin("c/gamma"))
        self.gel([("gamma", "c/gamma", "7" * 40)], "gamma regelé")
        rapport = self.build("HEAD~3", "HEAD")
        ligne = self.par_chemin(rapport)["c/gamma"]
        self.assertEqual(ligne["stats"]["missing"], ["clone"])
        self.assertNotIn(ligne, fd.missing_rows(rapport["rows"]))
        self.assertEqual(
            fd.fetch_commits(self.chemin("c/gamma"), ["7" * 40]), ["7" * 40]
        )
        self.assertFalse(
            os.path.exists(os.path.join(self.racine, ".git", "FETCH_HEAD"))
        )

    def test_clone_superficiel(self):
        source = self.chemin("c/alpha")
        _git(
            self.racine,
            "clone",
            "-q",
            "--depth",
            "1",
            f"file://{source}",
            self.chemin("c/delta"),
        )
        tete = _git(self.chemin("c/delta"), "rev-parse", "HEAD")
        _git(
            self.chemin("c/delta"),
            "fetch",
            "-q",
            "--depth",
            "1",
            "origin",
            self.alpha[0],
        )
        self.gel([("delta", "c/delta", self.alpha[0])], "delta")
        rapport = self.build("HEAD", fd.CLONES)
        ligne = self.par_chemin(rapport)["c/delta"]
        self.assertEqual(ligne["new"], tete)
        self.assertTrue(ligne["stats"]["shallow"])
        self.assertIsNone(ligne["stats"]["ahead"])
        sommaire = "\n".join(fd.render_summary(rapport))
        self.assertIn("? shallow", sommaire)
        self.assertIn("1 shallow clones", sommaire)

    def test_renommage_et_nom_accentue(self):
        clone = self.chemin("c/beta")
        os.makedirs(os.path.join(clone, "addons", "mod_a"))
        self.fichier(os.path.join(clone, "addons", "mod_a", "x.py"), "a\n")
        _git(clone, "add", "-A")
        _git(clone, "commit", "-q", "-m", "mod_a")
        base = _git(clone, "rev-parse", "HEAD")
        _git(clone, "mv", "addons/mod_a", "addons/mod_b")
        self.fichier(os.path.join(clone, "été.py"), "b\n")
        _git(clone, "add", "-A")
        _git(clone, "commit", "-q", "-m", "renomme")
        fichiers = fd.numstat(clone, base, "HEAD")
        self.assertEqual(
            sorted(f for _, _, f in fichiers),
            ["addons/mod_b/x.py", "été.py"],
        )
        self.assertEqual(
            sorted(g[0] for g in fd.group_files(fichiers, "module")),
            ["(root)", "addons/mod_b"],
        )

    def test_commit_absent_liste_son_sha_complet(self):
        self.gel([("alpha", "c/alpha", "8" * 40)], "gel inventé")
        rapport = self.build("HEAD~1", "HEAD")
        self.assertIn(
            f"  - c/alpha: new {'8' * 40}",
            "\n".join(fd.render_summary(rapport)),
        )

    def test_un_cote_sans_gel_ne_liste_pas_tous_les_projets(self):
        rapport = self.build("HEAD~3", fd.CLONES)
        sommaire = fd.render_summary(rapport)
        self.assertIn("  (--all lists them)", sommaire)
        self.assertNotIn("  - c/alpha", "\n".join(sommaire))
        complet = "\n".join(fd.render_summary(rapport, show_all=True))
        self.assertIn("  - c/alpha", complet)

    def test_les_indications_du_menu(self):
        rapport = self.build("HEAD~2", "HEAD~1")
        borne = "\n".join(fd.render_details(rapport, stat_count=1, menu=True))
        self.assertIn("s N shows all", borne)
        self.assertNotIn("--stat-count", borne)

    def test_suggestion_de_worktree(self):
        rapport = self.build("HEAD", fd.CLONES)
        astuce = "\n".join(fd.render_tip(rapport))
        self.assertIn("git -C c/alpha worktree add --detach", astuce)
        self.assertIn(self.alpha[2], astuce)
        fd.changed_rows(rapport)[0]["path"] = "c/un dossier"
        astuce = "\n".join(fd.render_tip(rapport))
        self.assertIn("git -C 'c/un dossier' worktree", astuce)


class TestBranches(_Checkout):
    """Les branches autour des commits : celle du manifeste, les refs du
    clone, et les branches ou tags d'ERPLibre qui portent un gel."""

    def setUp(self):
        super().setUp()
        self.clone_alpha = self.chemin("c/alpha")
        _git(self.clone_alpha, "branch", "18.0")

    def test_la_pointe_de_la_branche_du_manifeste(self):
        self.assertEqual(
            fd.branch_tip(self.clone_alpha, "18.0"), "refs/heads/18.0"
        )
        _git(self.clone_alpha, "update-ref", "refs/remotes/m/18.0", "HEAD")
        _git(self.clone_alpha, "update-ref", "refs/remotes/zed/18.0", "HEAD")
        self.assertEqual(
            fd.branch_tip(self.clone_alpha, "18.0"), "refs/remotes/zed/18.0"
        )
        _git(self.clone_alpha, "update-ref", "refs/remotes/abc/18.0", "HEAD")
        self.assertEqual(
            fd.branch_tip(self.clone_alpha, "18.0", "zed"),
            "refs/remotes/zed/18.0",
        )
        self.assertIsNone(fd.branch_tip(self.clone_alpha, "19.0"))
        self.assertIsNone(fd.branch_tip(self.clone_alpha, "a" * 40))

    def test_place_d_un_commit(self):
        tip = "refs/heads/18.0"
        ctx = fd.commit_context(self.clone_alpha, self.alpha[1], tip)
        self.assertEqual((ctx["behind"], ctx["off"]), (2, 0))
        self.assertEqual(ctx["at"], [])
        self.assertIn("18.0", ctx["refs"])
        ctx = fd.commit_context(self.clone_alpha, self.alpha[3], tip)
        self.assertEqual(ctx["behind"], 0)
        self.assertIn("18.0", ctx["at"])
        self.assertNotIn("18.0", ctx["refs"])
        _git(self.clone_alpha, "checkout", "-q", "-b", "cote", self.alpha[1])
        self.fichier(os.path.join(self.clone_alpha, "f.txt"), "cote")
        _git(self.clone_alpha, "commit", "-q", "-am", "cote")
        hors = _git(self.clone_alpha, "rev-parse", "HEAD")
        ctx = fd.commit_context(self.clone_alpha, hors, tip)
        self.assertEqual((ctx["behind"], ctx["off"]), (2, 1))

    def test_au_dela_de_la_limite_les_refs_se_comptent(self):
        for i in range(fd.REFS_LIMIT + 3):
            _git(self.clone_alpha, "tag", f"t{i:02d}", self.alpha[3])
        ctx = fd.commit_context(self.clone_alpha, self.alpha[0])
        self.assertEqual(len(ctx["refs"]), fd.REFS_LIMIT)
        self.assertGreaterEqual(ctx["more"], 3)
        self.assertIsNone(ctx["behind"])

    def test_colonne_et_detail(self):
        rapport = self.build("HEAD", fd.CLONES)
        ligne = self.par_chemin(rapport)["c/alpha"]
        self.assertEqual(fd._colonne_branche(ligne), "18.0 -1->tip")
        self.assertEqual(
            fd._colonne_branche(self.par_chemin(rapport)["c/beta"]),
            "18.0 (no ref)",
        )
        sommaire = "\n".join(fd.render_summary(rapport))
        self.assertIn("vs branch", sommaire)
        self.assertIn("18.0 -1->tip", sommaire)
        detail = "\n".join(fd.render_branches(rapport, ligne))
        self.assertIn("branch 18.0 = 18.0", detail)
        self.assertIn(f"old {self.alpha[2][:8]}: 1 behind the tip", detail)
        self.assertIn(f"new {self.alpha[3][:8]}: at the tip; is ", detail)

    def test_fraicheur_des_refs(self):
        rapport = self.build("HEAD", fd.CLONES)
        sommaire = "\n".join(fd.render_summary(rapport))
        self.assertIn("never fetched", sommaire)
        _git(self.clone_alpha, "fetch", "-q", "origin")
        rapport = self.build("HEAD", fd.CLONES)
        ligne = self.par_chemin(rapport)["c/alpha"]
        self.assertIsNotNone(ligne["branches"]["fetched"])
        self.assertNotIn("c/alpha: ", "\n".join(fd.render_summary(rapport)))
        rapport["now"] = ligne["branches"]["fetched"] + 30 * 86400
        self.assertIn(
            "  - c/alpha: 30 days ago", "\n".join(fd.render_summary(rapport))
        )

    def test_gels_des_branches_et_tags_d_erplibre(self):
        _git(self.racine, "branch", "release", "HEAD~1")
        _git(self.racine, "tag", "-a", "-m", "v", "v-ancien", "HEAD~2")
        _git(self.racine, "branch", "vide", "HEAD~3")
        refs, ecartes = fd.frozen_refs(self.racine)
        noms = [n for n, _ in refs]
        self.assertEqual(ecartes, 0)
        self.assertIn("v-ancien", noms)
        self.assertTrue(any("release" in n for n in noms))
        self.assertFalse(any("vide" in n for n in noms))
        refs, ecartes = fd.frozen_refs(self.racine, limite=1)
        self.assertEqual((len(refs), ecartes), (1, len(noms) - 1))
        rapport = self.build("HEAD~2", "HEAD~1")
        ligne = self.par_chemin(rapport)["c/alpha"]
        detail = "\n".join(fd.render_branches(rapport, ligne))
        self.assertIn("frozen by ERPLibre v-ancien", detail)
        self.assertIn("release", detail)

    def test_matrice(self):
        table = fd.matrix(self.racine, ["HEAD~2", "HEAD~1", fd.CLONES])
        lignes = dict(table["rows"])
        self.assertEqual(
            lignes["c/alpha"], [self.alpha[0], self.alpha[2], self.alpha[3]]
        )
        self.assertEqual(lignes["c/gamma"], [self.gamma, None, None])
        (beta,) = [r for r in fd.render_matrix(table) if "c/beta" in r]
        self.assertEqual(
            beta.split()[1:], [self.beta[0][:8], "=", self.beta[1][:8]]
        )
        _git(self.chemin("c/beta"), "checkout", "-q", self.beta[0])
        table = fd.matrix(self.racine, ["HEAD~1", fd.CLONES])
        rendu = fd.render_matrix(table)
        self.assertFalse(any("c/beta" in r for r in rendu))
        self.assertTrue(
            any("c/beta" in r for r in fd.render_matrix(table, show_all=True))
        )

    def test_graphe_avec_la_pointe(self):
        rapport = self.build("HEAD~2", "HEAD~1")
        ligne = self.par_chemin(rapport)["c/alpha"]
        with patch.object(
            fd.shutil, "which", return_value="/bin/tig"
        ), patch.object(fd, "_attendre", return_value=0) as lance:
            fd.open_graph(self.racine, ligne)
        commande, chemin = lance.call_args[0]
        self.assertEqual(chemin, self.clone_alpha)
        self.assertEqual(
            commande, ["tig", self.alpha[0], self.alpha[2], "18.0"]
        )
        _git(self.clone_alpha, "branch", "-f", "18.0", self.alpha[1])
        rapport = self.build("HEAD~1", fd.CLONES)
        ligne = self.par_chemin(rapport)["c/alpha"]
        with patch.object(fd.shutil, "which", return_value=None), patch.object(
            fd, "_attendre", return_value=0
        ) as lance:
            fd.open_graph(self.racine, ligne)
        commande = lance.call_args[0][0]
        self.assertEqual(commande[:2], ["git", "log"])
        self.assertEqual(commande[-1], f"^{self.alpha[1]}^@")


class TestLigneDeCommande(_Checkout):
    def main(self, *argv):
        with patch.object(fd, "new_path", self.racine), patch.object(
            fd,
            "default_definitions",
            side_effect=lambda r: fd.read_worktree(r),
        ), patch("builtins.print") as sortie:
            code = fd.main(list(argv))
        texte = "\n".join(
            " ".join(str(a) for a in appel.args) for appel in sortie.mock_calls
        )
        return code, texte

    def test_par_defaut_head_vers_clones(self):
        code, texte = self.main("--summary")
        self.assertEqual(code, 0)
        self.assertIn("-> clones", texte)

    def test_gel_precedent(self):
        code, texte = self.main("--previous", "--summary")
        self.assertEqual(code, 0)
        self.assertIn("1 changed", texte)

    def test_liste_des_gels(self):
        code, texte = self.main("--list")
        self.assertEqual(code, 0)
        self.assertIn("premier gel", texte)

    def test_revision_inconnue(self):
        code, texte = self.main("--from", "nulle-part")
        self.assertEqual(code, 2)
        self.assertIn("unknown revision", texte)

    def test_matrice_et_refs(self):
        code, texte = self.main("--matrix", "HEAD~2,HEAD~1")
        self.assertEqual(code, 0)
        self.assertIn("c/alpha", texte)
        code, _ = self.main("--matrix", "HEAD~2,nulle-part")
        self.assertEqual(code, 2)
        code, texte = self.main("--list-refs")
        self.assertEqual(code, 0)
        self.assertIn("principale", texte)

    def test_graphe_par_numero(self):
        with patch.object(fd, "open_graph", return_value=0) as graphe:
            code, _ = self.main("--summary", "--graph", "1")
        self.assertEqual(code, 0)
        graphe.assert_called_once()

    def test_aucun_projet_gele(self):
        code, texte = self.main("--from", "HEAD~3", "--to", "HEAD~3")
        self.assertEqual(code, 0)
        self.assertIn("No project has a frozen commit on either side.", texte)
        self.assertNotIn("0 projects:", texte)

    def test_tig_sur_un_projet_absent(self):
        code, _ = self.main("--summary", "--tig", "c/rien")
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
