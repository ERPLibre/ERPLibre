#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""« repo_pull » : le git pull épinglé du code déployé, sur de vrais dépôts.

Le banc monte dans un dossier temporaire une racine ERPLibre factice — un
dépôt git avec son remote nu, « .odoo-version » valant « X.0 » et un
manifeste local écrit par le test — et un clone par addon sous
« odooX.0/addons/ ». Tous les remotes sont des chemins du dossier
temporaire ; un clone superficiel passe par « file:// », seul transport
local qui honore « --depth ». La fusion des manifestes, « repo » et
« poetry » sont simulés : rien ne sort du dossier temporaire.

Tous les noms, chemins et commits sont inventés.
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

from script.git import git_freeze_manifest, repo_apply, repo_pull

VERSION = "X.0"
STAMP = "20990101T0800"
CHEMIN_A = "odooX.0/addons/A"
CHEMIN_B = "odooX.0/addons/B"
REMOTE = "ERPLibre"


def _git(cwd, *args, env=None):
    """Lance git sans dépendre de la configuration de l'hôte ; rend stdout.

    `env` complète l'environnement, une date de commit par exemple."""
    return subprocess.run(
        [
            "git",
            "-c",
            "init.defaultBranch=principale",
            "-c",
            "protocol.file.allow=always",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env=dict(os.environ, **(env or {})),
    ).stdout.strip()


class Banc(unittest.TestCase):
    """Une racine ERPLibre factice, un addon « A », et leurs remotes nus.

    La racine et « A » sont sur la branche « X.0 », qui suit celle de leur
    remote. `self.sources[nom]` est un clone de travail d'où le test pousse
    les nouveaux commits d'un remote.
    """

    horloge = 1700000000
    # L'écart entre deux commits, plus grand que la marge sous la frontière
    # d'un clone superficiel : la borne de sa récupération tombe entre deux
    # commits, comme sur un historique ordinaire.
    PAS = 2 * repo_pull.MARGE_FRONTIERE

    def setUp(self):
        self.dossier = tempfile.mkdtemp(prefix="test_repo_pull_")
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
        self.distants = os.path.join(self.dossier, "distants")
        os.makedirs(self.distants)
        self.sources = {}
        self.racine = os.path.join(self.dossier, "racine")
        self.creer_distant(
            "erplibre.git",
            {
                ".gitignore": ".odoo-version\n.repo/\ntasks/\nodooX.0/\n",
                "manifest/lisezmoi.txt": "un\n",
                "conf/lisezmoi.txt": "un\n",
            },
        )
        _git(
            self.dossier,
            "clone",
            "-q",
            "-b",
            VERSION,
            self.distant("erplibre.git"),
            self.racine,
        )
        self.ecrire(self.racine, ".odoo-version", f"{VERSION}\n")
        self.creer_distant("a.git", {"a.txt": "un\n", "b.txt": "un\n"})
        self.cloner("a.git", CHEMIN_A)
        self.manifeste_local([("a.git", CHEMIN_A, VERSION)])
        self.predit = None
        self.appels_regenerer = []

    # ── outils ──

    def distant(self, nom):
        return os.path.join(self.distants, nom)

    def ecrire(self, depot, fichier, contenu):
        chemin = os.path.join(depot, fichier)
        os.makedirs(os.path.dirname(chemin), exist_ok=True)
        with open(chemin, "w") as fh:
            fh.write(contenu)

    def lire(self, depot, fichier):
        with open(os.path.join(depot, fichier)) as fh:
            return fh.read()

    def commit(self, depot, fichiers, message="commit"):
        """Un commit daté de PAS secondes après le précédent : la
        récupération d'un clone superficiel borne par date, et des commits
        de la même seconde la rendraient sans borne."""
        Banc.horloge += Banc.PAS
        date = {
            "GIT_AUTHOR_DATE": f"@{Banc.horloge} +0000",
            "GIT_COMMITTER_DATE": f"@{Banc.horloge} +0000",
        }
        for fichier, contenu in fichiers.items():
            self.ecrire(depot, fichier, contenu)
            _git(depot, "add", fichier)
        _git(depot, "commit", "-q", "-m", message, env=date)
        return _git(depot, "rev-parse", "HEAD")

    def creer_distant(self, nom, fichiers, branche=VERSION):
        _git(self.distants, "init", "-q", "--bare", nom)
        source = os.path.join(self.dossier, "sources", nom)
        _git(self.dossier, "init", "-q", source)
        self.commit(source, fichiers, "initial")
        _git(source, "push", "-q", self.distant(nom), f"HEAD:{branche}")
        self.sources[nom] = source

    def avancer(self, nom, fichiers, message="amont", branche=VERSION):
        sha = self.commit(self.sources[nom], fichiers, message)
        _git(
            self.sources[nom],
            "push",
            "-q",
            "-f",
            self.distant(nom),
            f"HEAD:{branche}",
        )
        return sha

    def cloner(self, nom, chemin, profondeur=None):
        cible = os.path.join(self.racine, chemin)
        args = ["clone", "-q", "-o", REMOTE, "-b", VERSION]
        url = self.distant(nom)
        if profondeur:
            args += ["--depth", str(profondeur)]
            url = "file://" + url
        _git(self.dossier, *args, url, cible)
        return cible

    def manifeste_texte(self, projets):
        lignes = [
            "<manifest>",
            f'  <remote name="{REMOTE}" fetch="{self.distants}/"/>',
            f'  <default remote="{REMOTE}" revision="{VERSION}"/>',
        ]
        for nom, chemin, revision in projets:
            lignes.append(
                f'  <project name="{nom}" path="{chemin}"'
                f' revision="{revision}"/>'
            )
        lignes.append("</manifest>")
        return "\n".join(lignes) + "\n"

    def manifeste_local(self, projets):
        self.ecrire(
            self.racine,
            repo_pull.repo_state.MANIFESTE_LOCAL,
            self.manifeste_texte(projets),
        )

    def regenerer(self, racine, cwd, sortie, geler):
        """La fusion simulée : écrit `self.predit` (une liste de projets,
        ou un texte), sinon le manifeste local tel quel."""
        self.appels_regenerer.append((cwd, geler))
        predit = self.predit
        if callable(predit):
            predit = predit()
        if predit is None:
            texte = self.lire(racine, repo_pull.repo_state.MANIFESTE_LOCAL)
        elif isinstance(predit, str):
            texte = predit
        else:
            texte = self.manifeste_texte(predit)
        with open(sortie, "w") as fh:
            fh.write(texte)
        return 0, ""

    def depot(self, chemin=CHEMIN_A):
        return os.path.join(self.racine, chemin)

    def head(self, chemin=CHEMIN_A):
        return _git(self.depot(chemin), "rev-parse", "HEAD")

    def branches(self, chemin=CHEMIN_A):
        return _git(
            self.depot(chemin), "for-each-ref", "--format=%(refname:short)"
        ).split()

    def diag(self, mode="branche", strategie="rebase", **kw):
        donnees, code = repo_pull.diagnostic(
            self.racine, mode, strategie, regenerer=self.regenerer, **kw
        )
        self.assertEqual(code, 0, donnees)
        return donnees

    def constat(self, donnees, chemin=CHEMIN_A):
        return next(c for c in donnees["depots"] if c["chemin"] == chemin)

    def appliquer(
        self, donnees, approfondir=False, attendus=None, epingles=True, **kw
    ):
        lst = list(donnees["attendus"])
        if approfondir:
            lst += donnees["attendus_superficiel"]
        if attendus is not None:
            lst = attendus
        lus = [repo_apply.lire_attendu(x) for x in lst]
        kw.setdefault("horodatage", STAMP)
        return repo_pull.passe(
            self.racine,
            VERSION,
            donnees["mode"],
            donnees["strategie"],
            attendus=[c for c, _e in lus],
            epingles={c: e for c, e in lus if e} if epingles else None,
            approfondir=approfondir,
            regenerer=self.regenerer,
            **kw,
        )

    def resultat(self, charge, chemin=CHEMIN_A):
        return next(r for r in charge["resultats"] if r["chemin"] == chemin)


class TestBrancheMode(Banc):
    def test_avance_rapide(self):
        depart = self.head()
        cible = self.avancer("a.git", {"a.txt": "deux\n"})
        donnees = self.diag()
        c = self.constat(donnees)
        self.assertEqual(c["verdict"], "avance_rapide")
        self.assertEqual(c["source_cible"], "suivi")
        self.assertEqual(c["cible"], f"refs/remotes/{REMOTE}/{VERSION}")
        self.assertEqual((c["nos"], c["retard"]), (0, 1))
        self.assertEqual(c["entrants"][0]["subject"], "amont")
        self.assertEqual(self.constat(donnees, ".")["verdict"], "a_jour")
        self.assertEqual(donnees["plan"], [CHEMIN_A])
        self.assertEqual(donnees["attendus"], [f"{CHEMIN_A}={cible}:{depart}"])
        self.assertEqual(self.head(), depart, "l'essai à sec ne bouge rien")

        charge, code = self.appliquer(donnees)
        self.assertEqual(code, 0, charge)
        res = self.resultat(charge)
        self.assertEqual(res["etat"], "avance")
        self.assertEqual(self.head(), cible)
        sauvegarde = f"{VERSION}_avant_pull_{STAMP}"
        self.assertEqual(res["sauvegarde"], sauvegarde)
        self.assertEqual(_git(self.depot(), "rev-parse", sauvegarde), depart)
        passe = repo_pull.lire_passe(STAMP, self.racine)
        self.assertEqual(passe["resultats"][0]["etat"], "avance")
        self.assertEqual(passe["diagnostic"]["plan"], [CHEMIN_A])

    def test_rebase_rejoue_le_commit_local(self):
        local = self.commit(self.depot(), {"b.txt": "local\n"}, "local")
        cible = self.avancer("a.git", {"a.txt": "deux\n"})
        donnees = self.diag()
        self.assertEqual(self.constat(donnees)["verdict"], "diverge")
        charge, code = self.appliquer(donnees)
        res = self.resultat(charge)
        self.assertEqual(res["etat"], "tire")
        self.assertEqual(_git(self.depot(), "rev-parse", "HEAD~1"), cible)
        self.assertEqual(
            _git(self.depot(), "log", "-1", "--format=%s"), "local"
        )
        self.assertEqual(
            _git(self.depot(), "rev-parse", res["sauvegarde"]), local
        )
        self.assertEqual(
            _git(self.depot(), "symbolic-ref", "--short", "HEAD"), VERSION
        )

    def test_merge_fait_un_commit_a_deux_parents(self):
        self.commit(self.depot(), {"b.txt": "local\n"}, "local")
        self.avancer("a.git", {"a.txt": "deux\n"})
        donnees = self.diag(strategie="merge")
        charge, _code = self.appliquer(donnees)
        self.assertEqual(self.resultat(charge)["etat"], "tire")
        parents = _git(self.depot(), "log", "-1", "--format=%P").split()
        self.assertEqual(len(parents), 2)

    def test_ff_refuse_une_divergence(self):
        self.commit(self.depot(), {"b.txt": "local\n"}, "local")
        self.avancer("a.git", {"a.txt": "deux\n"})
        c = self.constat(self.diag(strategie="ff"))
        self.assertEqual(c["verdict"], "diverge")
        self.assertFalse(c["applicable"])
        self.assertEqual(c["motif"], "diverged: fast-forward impossible")
        self.assertNotIn(CHEMIN_A, self.diag(strategie="ff")["plan"])

    def _conflit(self, strategie, sale=False):
        """Un commit local et l'amont touchent « a.txt » ; `sale` modifie
        aussi « b.txt » sans le commiter, que le retour doit rendre."""
        depart = self.commit(self.depot(), {"a.txt": "local\n"}, "local")
        self.avancer("a.git", {"a.txt": "amont\n"})
        if sale:
            self.ecrire(self.depot(), "b.txt", "en cours\n")
        donnees = self.diag(strategie=strategie)
        charge, _code = self.appliquer(donnees)
        res = self.resultat(charge)
        self.assertEqual(res["etat"], "conflit_annule")
        self.assertEqual(res["conflits"], ["a.txt"])
        self.assertIsNone(res["sauvegarde"])
        self.assertEqual(self.head(), depart)
        self.assertEqual(
            _git(self.depot(), "symbolic-ref", "--short", "HEAD"), VERSION
        )
        self.assertIsNone(repo_pull.operation_en_cours(self.depot()))
        self.assertNotIn(f"{VERSION}_avant_pull_{STAMP}", self.branches())
        self.assertEqual(_git(self.depot(), "stash", "list"), "")
        if sale:
            self.assertEqual(res["stash"]["etat"], "reapplique")
            self.assertEqual(self.lire(self.depot(), "b.txt"), "en cours\n")
            self.assertEqual(
                _git(self.depot(), "status", "--porcelain"), "M b.txt"
            )
        else:
            self.assertEqual(res["stash"]["etat"], "aucun")
            self.assertEqual(_git(self.depot(), "status", "--porcelain"), "")

    def test_conflit_de_rebase_remis(self):
        self._conflit("rebase")

    def test_conflit_de_merge_remis(self):
        self._conflit("merge")

    def test_conflit_de_rebase_sur_arbre_sale(self):
        self._conflit("rebase", sale=True)

    def test_conflit_de_merge_sur_arbre_sale(self):
        self._conflit("merge", sale=True)

    def test_arbre_sale_stashe_puis_reapplique(self):
        self.ecrire(self.depot(), "b.txt", "modifie\n")
        cible = self.avancer("a.git", {"a.txt": "deux\n"})
        donnees = self.diag()
        c = self.constat(donnees)
        self.assertTrue(c["sale"])
        self.assertTrue(c["stash_prevu"])
        res = self.resultat(self.appliquer(donnees)[0])
        self.assertEqual(res["etat"], "avance")
        self.assertEqual(res["stash"]["etat"], "reapplique")
        self.assertEqual(self.head(), cible)
        self.assertEqual(self.lire(self.depot(), "b.txt"), "modifie\n")

    def test_pop_qui_bute_garde_le_stash(self):
        self.ecrire(self.depot(), "a.txt", "modifie\n")
        cible = self.avancer("a.git", {"a.txt": "deux\n"})
        res = self.resultat(self.appliquer(self.diag())[0])
        self.assertEqual(res["etat"], "stash_garde")
        self.assertEqual(res["arrivee"], cible)
        self.assertEqual(self.head(), cible)
        self.assertEqual(_git(self.depot(), "status", "--porcelain"), "")
        self.assertIn(
            res["stash"]["sha"],
            _git(self.depot(), "stash", "list", "--format=%H").split(),
        )
        self.assertIn("stash apply", res["stash"]["commande"])

    def test_head_detachee_sautee(self):
        self.avancer("a.git", {"a.txt": "deux\n"})
        depart = self.head()
        _git(self.depot(), "checkout", "-q", "--detach")
        donnees = self.diag()
        self.assertEqual(self.constat(donnees)["verdict"], "detache")
        self.assertEqual(self.constat(donnees)["fetch"], "saute")
        self.assertEqual(donnees["plan"], [])
        self.assertEqual(self.head(), depart)

    def test_operation_en_cours_intouchee(self):
        _git(self.depot(), "checkout", "-q", "-b", "autre")
        self.commit(self.depot(), {"a.txt": "autre\n"})
        _git(self.depot(), "checkout", "-q", VERSION)
        self.commit(self.depot(), {"a.txt": "local\n"})
        subprocess.run(
            ["git", "merge", "autre"],
            cwd=self.depot(),
            capture_output=True,
        )
        self.avancer("a.git", {"b.txt": "deux\n"})
        c = self.constat(self.diag())
        self.assertEqual(c["verdict"], "operation_en_cours")
        self.assertEqual(c["operation_en_cours"], "merge")
        self.assertEqual(c["fetch"], "saute")

    def test_sauvegarde_existante_n_ecrit_rien(self):
        depart = self.head()
        _git(self.depot(), "branch", f"{VERSION}_avant_pull_{STAMP}")
        self.avancer("a.git", {"a.txt": "deux\n"})
        res = self.resultat(self.appliquer(self.diag())[0])
        self.assertEqual(res["etat"], "sauvegarde_existante")
        self.assertEqual(self.head(), depart)

    def test_racine_tiree_en_mode_branche(self):
        cible = self.avancer("erplibre.git", {"conf/lisezmoi.txt": "deux\n"})
        donnees = self.diag()
        self.assertEqual(donnees["depots"][0]["chemin"], ".")
        self.assertEqual(donnees["plan"], ["."])
        charge, _code = self.appliquer(donnees)
        self.assertEqual(self.resultat(charge, ".")["etat"], "avance")
        self.assertEqual(self.head("."), cible)
        self.assertEqual(self.appels_regenerer, [], "pas de fusion en branche")

    def test_chemin_seul(self):
        self.avancer("a.git", {"a.txt": "deux\n"})
        self.avancer("erplibre.git", {"conf/lisezmoi.txt": "deux\n"})
        donnees = self.diag(chemin_seul=CHEMIN_A)
        self.assertEqual([c["chemin"] for c in donnees["depots"]], [CHEMIN_A])
        donnees = self.diag(chemin_seul=".")
        self.assertEqual([c["chemin"] for c in donnees["depots"]], ["."])
        _d, code = repo_pull.diagnostic(self.racine, chemin_seul="nulle/part")
        self.assertEqual(code, repo_pull.EXIT_CIBLE)
        _d, code = repo_pull.diagnostic(self.racine, chemin_seul="../hors")
        self.assertEqual(code, repo_pull.EXIT_CIBLE)


class TestEpingles(Banc):
    def setUp(self):
        super().setUp()
        self.depart = self.head()
        self.avancer("a.git", {"a.txt": "deux\n"})
        self.donnees = self.diag()
        self.refs = self.branches()

    def verifier_rien_ecrit(self, charge, code):
        self.assertEqual(code, repo_pull.EXIT_PLAN_CHANGE, charge)
        self.assertEqual(charge["error"], "plan_changed")
        self.assertEqual(self.head(), self.depart)
        self.assertEqual(self.branches(), self.refs)
        self.assertEqual(repo_pull.passes(self.racine), [])

    def test_le_distant_a_bouge(self):
        self.avancer("a.git", {"a.txt": "trois\n"})
        charge, code = self.appliquer(self.donnees)
        self.verifier_rien_ecrit(charge, code)
        self.assertEqual(charge["derives"][0]["cle"], "cible_sha")

    def test_head_a_bouge(self):
        self.commit(self.depot(), {"b.txt": "local\n"})
        self.depart = self.head()
        charge, code = self.appliquer(self.donnees)
        self.verifier_rien_ecrit(charge, code)
        self.assertEqual(charge["derives"][0]["cle"], "head")

    def test_la_liste_differe(self):
        charge, code = self.appliquer(self.donnees, attendus=["autre"])
        self.verifier_rien_ecrit(charge, code)

    def test_la_liste_des_clones_differe(self):
        charge, code = self.appliquer(
            self.donnees, cloner=True, attendus_clone=["odooX.0/addons/Z"]
        )
        self.verifier_rien_ecrit(charge, code)

    def test_verrou_pris(self):
        with repo_pull.verrou(self.racine):
            charge, code = self.appliquer(self.donnees)
        self.assertEqual(code, repo_pull.EXIT_OCCUPE)
        self.assertEqual(charge["error"], "busy")
        self.assertEqual(self.head(), self.depart)

    def test_horodatage_deja_pris(self):
        os.makedirs(repo_pull.dossier_passe(STAMP, self.racine))
        charge, code = self.appliquer(self.donnees)
        self.assertEqual(code, repo_pull.EXIT_USAGE)
        self.assertEqual(charge["error"], "stamp_taken")


class TestLigneDeCommande(Banc):
    def main(self, *args):
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie):
            code = repo_pull.main([*args, "--root", self.racine])
        return json.loads(sortie.getvalue()), code

    def test_aide_sans_git(self):
        with (
            patch.object(repo_pull.repo_state, "git") as git,
            patch("sys.stdout", new_callable=io.StringIO),
        ):
            with self.assertRaises(SystemExit) as fin:
                repo_pull.main(["--help"])
        self.assertEqual(fin.exception.code, 0)
        git.assert_not_called()

    def test_confirm_faux(self):
        charge, code = self.main("--apply", "--confirm", "Y.0")
        self.assertEqual(code, repo_pull.EXIT_USAGE)
        self.assertEqual(charge["error"], "confirm_mismatch")

    def test_expect_illisible(self):
        charge, code = self.main(
            "--apply", "--confirm", VERSION, "--expect", f"{CHEMIN_A}=x:y"
        )
        self.assertEqual(code, repo_pull.EXIT_USAGE)

    def test_chemin_inconnu(self):
        _c, code = self.main("--dry-run", "--mode", "branche", "--path", "z")
        self.assertEqual(code, repo_pull.EXIT_CIBLE)

    def test_nom_de_sauvegarde_refuse(self):
        charge, code = self.main(
            "--restore-backup", f"{CHEMIN_A}=main", "--confirm", VERSION
        )
        self.assertEqual(code, repo_pull.EXIT_USAGE)
        _c, code = self.main(
            "--delete-backup",
            f"z/z={VERSION}_avant_pull_{STAMP}",
            "--confirm",
            VERSION,
        )
        self.assertEqual(code, repo_pull.EXIT_CIBLE)

    def test_essai_puis_application(self):
        cible = self.avancer("a.git", {"a.txt": "deux\n"})
        donnees, code = self.main("--dry-run", "--mode", "branche")
        self.assertEqual(code, 0)
        self.assertEqual(donnees["command"], "dry-run")
        self.assertNotIn("_attrs", donnees["depots"][0])
        args = ["--apply", "--mode", "branche", "--confirm", VERSION]
        for x in donnees["attendus"]:
            args += ["--expect", x]
        charge, code = self.main(*args)
        self.assertEqual(code, 0, charge)
        self.assertEqual(charge["command"], "apply")
        self.assertEqual(self.head(), cible)
        liste, code = self.main("--list-backups")
        self.assertEqual(
            [(x["chemin"], x["horodatage"]) for x in liste["sauvegardes"]],
            [(CHEMIN_A, charge["horodatage"])],
        )


class BancSuperficiel(Banc):
    """Un addon « S » cloné sur trois commits d'un historique de trente."""

    CHEMIN_S = "odooX.0/addons/S"

    def setUp(self):
        super().setUp()
        self.creer_distant("s.git", {"s.txt": "0\n"})
        self.historique = [
            self.avancer("s.git", {"s.txt": f"{i}\n"}, f"s{i}")
            for i in range(1, 30)
        ]
        self.cloner("s.git", self.CHEMIN_S, profondeur=3)
        self.manifeste_local(
            [("a.git", CHEMIN_A, VERSION), ("s.git", self.CHEMIN_S, VERSION)]
        )

    def compte(self):
        return int(
            _git(self.depot(self.CHEMIN_S), "rev-list", "--count", "HEAD")
        )

    def diverger_sous_la_frontiere(self):
        """Un commit local, et l'amont réécrit depuis le dixième commit :
        l'historique de HEAD n'est plus joignable depuis le remote."""
        self.commit(self.depot(self.CHEMIN_S), {"local.txt": "x\n"}, "local")
        source = self.sources["s.git"]
        _git(source, "reset", "-q", "--hard", self.historique[9])
        return self.avancer("s.git", {"s.txt": "neuf\n"}, "reecrit")

    def diverger_par_une_fusion_ancienne(self):
        """Un commit local, et l'amont qui fusionne une branche partie du
        cinquième commit : la frontière de cette branche peut cacher une
        meilleure base, que seul l'approfondissement écarte."""
        self.commit(self.depot(self.CHEMIN_S), {"local.txt": "x\n"}, "local")
        source = self.sources["s.git"]
        _git(source, "checkout", "-q", "-b", "cote", self.historique[4])
        self.commit(source, {"cote.txt": "cote\n"}, "cote")
        _git(source, "checkout", "-q", "principale")
        Banc.horloge += Banc.PAS
        _git(
            source,
            "merge",
            "-q",
            "--no-ff",
            "-m",
            "fusion",
            "cote",
            env={"GIT_COMMITTER_DATE": f"@{Banc.horloge} +0000"},
        )
        _git(source, "push", "-q", self.distant("s.git"), f"HEAD:{VERSION}")
        return _git(source, "rev-parse", "HEAD")


class TestSuperficiel(BancSuperficiel):
    def test_l_essai_ne_raccourcit_pas_l_historique(self):
        avant = self.compte()
        self.avancer("s.git", {"s.txt": "suite\n"})
        c = self.constat(self.diag(), self.CHEMIN_S)
        self.assertTrue(c["superficiel"])
        self.assertEqual(c["verdict"], "avance_rapide")
        self.assertEqual(self.compte(), avant)

    def test_divergence_sous_la_frontiere(self):
        cible = self.diverger_par_une_fusion_ancienne()
        depart = self.head(self.CHEMIN_S)
        avant = self.compte()
        donnees = self.diag()
        self.assertEqual(self.compte(), avant)
        c = self.constat(donnees, self.CHEMIN_S)
        self.assertEqual(c["verdict"], "superficiel")
        self.assertTrue(c["approfondissement_requis"])
        self.assertEqual(donnees["plan_superficiel"], [self.CHEMIN_S])
        self.assertNotIn(self.CHEMIN_S, donnees["plan"])

        # sans consentement : rien
        charge, code = self.appliquer(donnees)
        self.assertEqual(code, 0)
        self.assertEqual(self.head(self.CHEMIN_S), depart)

        # avec : approfondi, rebasé
        charge, code = self.appliquer(
            self.diag(), approfondir=True, horodatage="20990101T0801"
        )
        self.assertEqual(code, 0, charge)
        res = self.resultat(charge, self.CHEMIN_S)
        self.assertEqual(res["etat"], "tire", res)
        self.assertEqual(res["approfondi"]["profondeur"], 50)
        self.assertEqual(
            _git(self.depot(self.CHEMIN_S), "rev-parse", "HEAD~1"), cible
        )

    def test_sans_consentement_le_superficiel_est_saute(self):
        self.diverger_par_une_fusion_ancienne()
        self.avancer("a.git", {"a.txt": "deux\n"})
        charge, _code = self.appliquer(self.diag())
        self.assertEqual(
            self.resultat(charge, self.CHEMIN_S)["etat"], "saute_superficiel"
        )
        self.assertEqual(self.resultat(charge)["etat"], "avance")

    def test_plafond_atteint(self):
        self.diverger_sous_la_frontiere()
        depart = self.head(self.CHEMIN_S)
        donnees = self.diag()
        self.assertEqual(
            self.constat(donnees, self.CHEMIN_S)["verdict"], "superficiel"
        )
        with patch.object(git_freeze_manifest, "PROFONDEUR_MAX", 100):
            charge, _code = self.appliquer(donnees, approfondir=True)
        res = self.resultat(charge, self.CHEMIN_S)
        self.assertEqual(res["etat"], "superficiel_sans_base")
        self.assertEqual(res["approfondi"]["profondeur"], 100)
        self.assertIsNone(res["sauvegarde"])
        self.assertEqual(self.head(self.CHEMIN_S), depart)


class TestManifeste(Banc):
    """Mode « manifeste » : clones détachés, manifeste régénéré simulé."""

    def setUp(self):
        super().setUp()
        _git(self.depot(), "checkout", "-q", "--detach")
        _git(self.depot(), "branch", "-q", "-D", VERSION)
        # « Y.0 », branche du même remote, en avance sur X.0
        self.cible_y = self.avancer("a.git", {"a.txt": "y\n"}, "y", "Y.0")

    def test_detache_suit_sa_nouvelle_entree(self):
        depart = self.head()
        self.predit = [("a.git", CHEMIN_A, "Y.0")]
        donnees = self.diag("manifeste")
        c = self.constat(donnees)
        self.assertEqual(c["verdict"], "avance_rapide")
        self.assertEqual(c["source_cible"], "manifeste_regenere")
        self.assertEqual(c["cible"], f"refs/remotes/{REMOTE}/Y.0")
        self.assertEqual(
            donnees["manifeste"]["changements"],
            [
                {
                    "chemin": CHEMIN_A,
                    "genre": "change",
                    "avant": VERSION,
                    "apres": "Y.0",
                }
            ],
        )
        self.assertEqual(self.appels_regenerer[0], (self.racine, False))

        charge, code = self.appliquer(donnees)
        self.assertEqual(code, 0, charge)
        res = self.resultat(charge)
        self.assertEqual(res["etat"], "avance")
        self.assertTrue(res["detache"])
        self.assertEqual(self.head(), self.cible_y)
        self.assertEqual(
            _git(self.depot(), "rev-parse", "--abbrev-ref", "HEAD"), "HEAD"
        )
        self.assertEqual(res["sauvegarde"], f"Y.0_avant_pull_{STAMP}")
        self.assertEqual(
            _git(self.depot(), "rev-parse", res["sauvegarde"]), depart
        )
        self.assertTrue(charge["manifeste"]["ecrit"])
        local = self.lire(self.racine, repo_pull.repo_state.MANIFESTE_LOCAL)
        self.assertIn('revision="Y.0"', local)
        avant = os.path.join(
            repo_pull.dossier_passe(STAMP, self.racine),
            "erplibre_manifest.avant.xml",
        )
        with open(avant) as fh:
            self.assertIn(f'revision="{VERSION}"', fh.read())

    def test_manifeste_different_n_integre_aucun_clone(self):
        depart = self.head()
        appels = []

        def predit():
            appels.append(1)
            if len(appels) <= 2:  # essai à sec, puis sa reprise
                return [("a.git", CHEMIN_A, "Y.0")]
            return [("a.git", CHEMIN_A, VERSION)]

        self.predit = predit
        donnees = self.diag("manifeste")
        charge, code = self.appliquer(donnees)
        self.assertEqual(code, 0)
        self.assertEqual(charge["manifeste"]["erreur"], "manifeste_different")
        self.assertFalse(charge["manifeste"]["ecrit"])
        self.assertEqual(charge["resultats"], [])
        self.assertEqual(self.head(), depart)
        local = self.lire(self.racine, repo_pull.repo_state.MANIFESTE_LOCAL)
        self.assertIn(f'revision="{VERSION}"', local)

    def test_racine_predite_sur_son_commit_cible(self):
        self.avancer("erplibre.git", {"manifest/lisezmoi.txt": "deux\n"})
        vus = []

        def predit():
            cwd = self.appels_regenerer[-1][0]
            vus.append(self.lire(cwd, "manifest/lisezmoi.txt"))
            vus.append(os.path.isfile(os.path.join(cwd, ".odoo-version")))
            return None

        self.predit = predit
        self.diag("manifeste")
        self.assertEqual(vus, ["deux\n", True])
        self.assertNotEqual(self.appels_regenerer[0][0], self.racine)

    def test_gel_suit_l_etat_actuel(self):
        sha = self.head()
        self.manifeste_local([("a.git", CHEMIN_A, sha)])
        self.predit = [("a.git", CHEMIN_A, sha)]
        donnees = self.diag("manifeste")
        self.assertEqual(self.appels_regenerer[0][1], True)
        self.assertEqual(donnees["manifeste"]["etat_actuel"], "frozen")
        self.assertEqual(self.constat(donnees)["verdict"], "a_jour")

    def test_regeneration_ratee_sans_secret(self):
        def regenerer(racine, cwd, sortie, geler):
            return 1, "fatal: https://jeton:motdepasse@example.invalid/x.git\n"

        donnees, code = repo_pull.diagnostic(
            self.racine, "manifeste", regenerer=regenerer
        )
        self.assertEqual(code, 0)
        erreur = donnees["manifeste"]["erreur"]
        self.assertIn("https://example.invalid/x.git", erreur)
        self.assertNotIn("motdepasse", json.dumps(donnees))

    def test_nouveau_depot_liste_et_url_nettoyee(self):
        self.predit = self.manifeste_texte(
            [("a.git", CHEMIN_A, VERSION)]
        ).replace(
            "</manifest>",
            '  <remote name="web"'
            ' fetch="https://jeton:secret@example.invalid/org/"/>\n'
            f'  <project name="b.git" path="{CHEMIN_B}" remote="web"'
            ' revision="X.0"/>\n</manifest>',
        )
        donnees = self.diag("manifeste")
        self.assertEqual(
            donnees["nouveaux"],
            [
                {
                    "chemin": CHEMIN_B,
                    "nom": "b.git",
                    "remote": "web",
                    "url": "https://example.invalid/org/b.git",
                    "revision": "X.0",
                    "occupe": False,
                }
            ],
        )
        self.assertEqual(donnees["plan_nouveaux"], [CHEMIN_B])
        self.assertNotIn("secret", json.dumps(repo_pull.public(donnees)))


class TestPasseManifeste(Banc):
    """Le clonage et l'installation que la passe enchaîne sur consentement."""

    def test_clone_apres_le_manifeste_ecrit(self):
        self.predit = [
            ("a.git", CHEMIN_A, VERSION),
            ("b.git", CHEMIN_B, VERSION),
        ]
        donnees = self.diag("manifeste")
        self.assertEqual(donnees["plan_nouveaux"], [CHEMIN_B])
        local = os.path.join(self.racine, repo_pull.repo_state.MANIFESTE_LOCAL)
        vu = []

        def cloner(racine, nouveaux, chemins, jobs=None, echeance=None):
            with open(local) as fh:
                vu.append(CHEMIN_B in fh.read())
            return [{"chemin": CHEMIN_B, "etat": "clone", "sortie": ""}]

        with patch.object(repo_pull, "cloner_nouveaux", side_effect=cloner):
            charge, code = self.appliquer(
                donnees, cloner=True, attendus_clone=[CHEMIN_B]
            )
        self.assertEqual(code, 0, charge)
        self.assertEqual(vu, [True], "le clone suit l'écriture du manifeste")
        self.assertEqual(charge["clones"][0]["etat"], "clone")

    def test_sans_consentement_aucun_clone(self):
        self.predit = [
            ("a.git", CHEMIN_A, VERSION),
            ("b.git", CHEMIN_B, VERSION),
        ]
        with patch.object(repo_pull, "cloner_nouveaux") as cloner:
            charge, code = self.appliquer(self.diag("manifeste"))
        self.assertEqual(code, 0, charge)
        cloner.assert_not_called()


class TestClones(Banc):
    """Le « repo sync » restreint qui clone les nouveaux dépôts."""

    def setUp(self):
        super().setUp()
        self.nouveaux = [{"chemin": CHEMIN_B, "nom": "b.git"}]
        self.ecrire(self.racine, ".repo/project.list", f"{CHEMIN_A}\n")
        self.appels = []

    def faux_lancer(self, connus):
        """`repo_pull.lancer` simulé pour « repo » : « list » rend `connus`,
        « sync » crée le dépôt B."""

        def lancer(argv, delai, cwd, env, en_direct=False):
            self.appels.append(
                (argv, {"delai": delai, "cwd": cwd, "env": env})
            )
            if argv[1] == "list":
                return 0, connus
            os.makedirs(os.path.join(self.racine, CHEMIN_B))
            _git(os.path.join(self.racine, CHEMIN_B), "init", "-q")
            self.commit(os.path.join(self.racine, CHEMIN_B), {"b": "b"})
            return 0, "sync ok\n"

        return lancer

    def test_repo_sync_restreint(self):
        with patch.object(
            repo_pull,
            "lancer",
            side_effect=self.faux_lancer(f"{CHEMIN_A}\n{CHEMIN_B}\n"),
        ):
            lst = repo_pull.cloner_nouveaux(
                self.racine, self.nouveaux, [CHEMIN_B]
            )
        self.assertEqual(lst[0]["etat"], "clone")
        self.assertTrue(lst[0]["arrivee"])
        argv, kw = self.appels[1]
        self.assertEqual(
            argv,
            [
                repo_pull.REPO_BIN,
                "sync",
                "-c",
                "--no-manifest-update",
                "--no-repo-verify",
                "--fail-fast",
                "-j",
                "4",
                CHEMIN_B,
            ],
        )
        self.assertEqual(kw["cwd"], self.racine)
        self.assertEqual(kw["delai"], repo_pull.DELAI_SYNC)
        self.assertEqual(kw["env"]["REPO_SKIP_SELF_UPDATE"], "1")
        self.assertEqual(kw["env"]["GIT_TERMINAL_PROMPT"], "0")

    def test_echeance_passee_ne_lance_rien(self):
        with patch.object(repo_pull, "lancer") as lancer:
            lst = repo_pull.cloner_nouveaux(
                self.racine,
                self.nouveaux,
                [CHEMIN_B],
                echeance=repo_pull.time.monotonic() - 1,
            )
        self.assertEqual(lst[0]["etat"], "saute_delai")
        lancer.assert_not_called()

    def test_un_projet_sortant_refuse_le_sync(self):
        with patch.object(
            repo_pull,
            "lancer",
            side_effect=self.faux_lancer(f"{CHEMIN_B}\n"),
        ):
            lst = repo_pull.cloner_nouveaux(
                self.racine, self.nouveaux, [CHEMIN_B]
            )
        self.assertEqual(lst[0]["etat"], "clone_refuse")
        self.assertIn("drops 1 projects", lst[0]["motif"])
        self.assertEqual([a[0][1] for a in self.appels], ["list"])

    def test_chemin_occupe(self):
        self.ecrire(self.racine, f"{CHEMIN_B}/la.txt", "x")
        with patch.object(repo_pull, "lancer") as run:
            lst = repo_pull.cloner_nouveaux(
                self.racine, self.nouveaux, [CHEMIN_B]
            )
        self.assertEqual(lst[0]["etat"], "clone_chemin_occupe")
        run.assert_not_called()


class TestSauvegardes(Banc):
    def setUp(self):
        super().setUp()
        self.depart = self.head()
        self.cible = self.avancer("a.git", {"a.txt": "deux\n"})
        charge, _code = self.appliquer(self.diag())
        self.nom = self.resultat(charge)["sauvegarde"]

    def test_lister(self):
        lst = repo_pull.lister_sauvegardes(self.racine)["sauvegardes"]
        self.assertEqual(
            lst,
            [
                {
                    "chemin": CHEMIN_A,
                    "nom": self.nom,
                    "sha": self.depart,
                    "horodatage": STAMP,
                    "actuel": False,
                    "branche": VERSION,
                    "detache": False,
                }
            ],
        )

    def test_revenir(self):
        charge, code = repo_pull.restaurer_sauvegarde(
            self.racine, CHEMIN_A, self.nom
        )
        self.assertEqual(code, 0)
        res = charge["resultats"][0]
        self.assertEqual(res["etat"], "revenu")
        self.assertEqual(
            (res["depart"], res["arrivee"]), (self.cible, self.depart)
        )
        self.assertEqual(self.head(), self.depart)
        self.assertIn(self.nom, self.branches(), "la sauvegarde reste")
        passe = repo_pull.lire_passe(STAMP, self.racine)
        self.assertEqual(passe["retours"][0]["etat"], "revenu")

    def test_revenir_refuse_un_arbre_sale(self):
        self.ecrire(self.depot(), "b.txt", "modifie\n")
        charge, _code = repo_pull.restaurer_sauvegarde(
            self.racine, CHEMIN_A, self.nom
        )
        self.assertEqual(charge["resultats"][0]["etat"], "refuse_sale")
        self.assertEqual(self.head(), self.cible)

    def test_revenir_refuse_une_autre_branche(self):
        _git(self.depot(), "checkout", "-q", "-b", "ailleurs")
        charge, _code = repo_pull.restaurer_sauvegarde(
            self.racine, CHEMIN_A, self.nom
        )
        self.assertEqual(charge["resultats"][0]["etat"], "branche_changee")

    def test_nom_hors_motif_et_absent(self):
        with self.assertRaises(ValueError):
            repo_pull.lire_designation(self.racine, f"{CHEMIN_A}=main")
        with self.assertRaises(LookupError):
            repo_pull.lire_designation(self.racine, f"z={self.nom}")
        _c, code = repo_pull.restaurer_sauvegarde(
            self.racine, CHEMIN_A, f"{VERSION}_avant_pull_20980101T0000"
        )
        self.assertEqual(code, repo_pull.EXIT_CIBLE)

    def test_supprimer(self):
        charge, code = repo_pull.supprimer_sauvegarde(
            self.racine, CHEMIN_A, self.nom
        )
        self.assertEqual(charge["resultats"][0]["etat"], "supprime")
        self.assertNotIn(self.nom, self.branches())
        _c, code = repo_pull.supprimer_sauvegarde(
            self.racine, CHEMIN_A, self.nom
        )
        self.assertEqual(code, repo_pull.EXIT_CIBLE)

    def test_supprimer_refuse_la_branche_courante(self):
        _git(self.depot(), "checkout", "-q", self.nom)
        charge, _code = repo_pull.supprimer_sauvegarde(
            self.racine, CHEMIN_A, self.nom
        )
        self.assertEqual(charge["resultats"][0]["etat"], "refuse_courante")


class TestRetourDeLaRacine(Banc):
    def test_le_manifeste_d_avant_revient(self):
        _git(self.depot(), "checkout", "-q", "--detach")
        self.avancer("erplibre.git", {"conf/lisezmoi.txt": "deux\n"})
        self.predit = [("a.git", CHEMIN_A, "Y.0")]
        self.avancer("a.git", {"a.txt": "y\n"}, "y", "Y.0")
        charge, code = self.appliquer(self.diag("manifeste"))
        self.assertEqual(code, 0, charge)
        local = repo_pull.repo_state.MANIFESTE_LOCAL
        self.assertIn('revision="Y.0"', self.lire(self.racine, local))
        nom = self.resultat(charge, ".")["sauvegarde"]
        charge, _code = repo_pull.restaurer_sauvegarde(self.racine, ".", nom)
        res = charge["resultats"][0]
        self.assertEqual(res["etat"], "revenu")
        self.assertTrue(res["manifeste_restaure"])
        self.assertIn(f'revision="{VERSION}"', self.lire(self.racine, local))


class TestDependances(Banc):
    COUPLE = "odooX.0_pythonZ"

    def setUp(self):
        super().setUp()
        source = self.sources["erplibre.git"]
        self.commit(
            source,
            {
                f"requirement/pyproject.{self.COUPLE}.toml": "un\n",
                f"requirement/poetry.{self.COUPLE}.lock": "un\n",
                "requirement/pyproject.autre.toml": "autre\n",
            },
        )
        os.symlink(
            f"./requirement/pyproject.{self.COUPLE}.toml",
            os.path.join(source, "pyproject.toml"),
        )
        os.symlink(
            f"./requirement/poetry.{self.COUPLE}.lock",
            os.path.join(source, "poetry.lock"),
        )
        _git(source, "add", "pyproject.toml", "poetry.lock")
        _git(source, "commit", "-q", "-m", "liens")
        _git(
            source,
            "push",
            "-q",
            self.distant("erplibre.git"),
            f"HEAD:{VERSION}",
        )
        _git(self.racine, "pull", "-q")
        self.ecrire(self.racine, ".erplibre-version", self.COUPLE)

    def test_lock_change_a_installer(self):
        self.avancer(
            "erplibre.git",
            {f"requirement/poetry.{self.COUPLE}.lock": "deux\n"},
        )
        deps = self.diag()["dependances"]
        self.assertEqual(
            deps["fichiers"], [f"requirement/poetry.{self.COUPLE}.lock"]
        )
        self.assertTrue(deps["a_installer"])
        self.assertFalse(deps["changement_de_version"])
        self.assertEqual(
            deps["commande"],
            f"source .venv.{self.COUPLE}/bin/activate"
            " && poetry install --no-root",
        )

    def test_approve_deps_enchaine_l_installation(self):
        self.avancer(
            "erplibre.git",
            {f"requirement/poetry.{self.COUPLE}.lock": "deux\n"},
        )
        donnees = self.diag()
        with patch.object(
            repo_pull, "_installer", return_value=({"code": 0}, 0)
        ) as installer:
            charge, code = self.appliquer(donnees, approuver_deps=True)
        self.assertEqual(code, 0, charge)
        self.assertTrue(charge["dependances"]["a_installer"])
        installer.assert_called_once_with(self.racine, STAMP, echeance=None)
        self.assertEqual(charge["deps"], {"code": 0})

    def test_lien_redirige_changement_de_version(self):
        source = self.sources["erplibre.git"]
        os.remove(os.path.join(source, "pyproject.toml"))
        os.symlink(
            "./requirement/pyproject.autre.toml",
            os.path.join(source, "pyproject.toml"),
        )
        _git(source, "add", "pyproject.toml")
        _git(source, "commit", "-q", "-m", "autre couple")
        _git(
            source,
            "push",
            "-q",
            self.distant("erplibre.git"),
            f"HEAD:{VERSION}",
        )
        deps = self.diag()["dependances"]
        self.assertIn("pyproject.toml", deps["fichiers"])
        self.assertTrue(deps["changement_de_version"])
        self.assertFalse(deps["a_installer"])

    def test_installer_dependances(self):
        venv = os.path.join(self.racine, f".venv.{self.COUPLE}")
        self.ecrire(venv, "bin/poetry", "")
        appels = []

        def lancer(argv, delai, cwd, env, en_direct=False):
            appels.append((argv, {"delai": delai, "cwd": cwd, "env": env}))
            os.makedirs(os.path.join(self.racine, "artifacts"))
            return 0, "ok\n"

        with (
            patch.dict(os.environ, {"PYTHONPATH": "/ailleurs"}),
            patch.object(repo_pull, "lancer", side_effect=lancer),
        ):
            charge, code = repo_pull.installer_dependances(
                self.racine, VERSION, STAMP
            )
        self.assertEqual(code, 0, charge)
        argv, kw = appels[0]
        self.assertEqual(
            argv,
            [
                os.path.join(venv, "bin", "poetry"),
                "install",
                "--no-root",
                "--no-interaction",
            ],
        )
        self.assertEqual(kw["cwd"], self.racine)
        self.assertEqual(kw["delai"], repo_pull.DELAI_DEPS)
        self.assertEqual(kw["env"]["VIRTUAL_ENV"], venv)
        self.assertTrue(
            kw["env"]["PATH"].startswith(os.path.join(venv, "bin"))
        )
        self.assertNotIn("PYTHONPATH", kw["env"])
        self.assertFalse(
            os.path.exists(os.path.join(self.racine, "artifacts"))
        )
        self.assertTrue(
            os.path.isfile(
                os.path.join(
                    repo_pull.dossier_passe(STAMP, self.racine), "deps.log"
                )
            )
        )

        with patch.object(repo_pull, "lancer", return_value=(1, "non\n")):
            charge, code = repo_pull.installer_dependances(self.racine)
        self.assertEqual(code, repo_pull.EXIT_DEPS)
        self.assertEqual(charge["error"], "poetry install failed")

    def test_le_journal_des_dependances_est_sans_secret(self):
        """Un vrai processus : un « poetry » factice affiche une URL
        porteuse d'identifiants, que ni la charge ni « deps.log » ne
        gardent."""
        poetry = os.path.join(
            self.racine, f".venv.{self.COUPLE}", "bin", "poetry"
        )
        self.ecrire(
            os.path.dirname(poetry),
            "poetry",
            "#!/bin/sh\n"
            "echo Cloning https://jeton:motdepasse@example.invalid/x.git\n",
        )
        os.chmod(poetry, 0o755)
        charge, code = repo_pull.installer_dependances(
            self.racine, VERSION, STAMP
        )
        self.assertEqual(code, 0, charge)
        self.assertIn("https://example.invalid/x.git", charge["sortie"])
        journal = self.lire(
            repo_pull.dossier_passe(STAMP, self.racine), "deps.log"
        )
        self.assertIn("https://example.invalid/x.git", journal)
        self.assertNotIn("motdepasse", journal)
        self.assertNotIn("motdepasse", charge["sortie"])


class TestStash(Banc):
    """Un « stash push » ne vaut stash que s'il crée une entrée."""

    def setUp(self):
        super().setUp()
        self.creer_distant("sous.git", {"s.txt": "un\n"})
        source = self.sources["a.git"]
        _git(
            source,
            "submodule",
            "add",
            "-q",
            "-b",
            VERSION,
            self.distant("sous.git"),
            "sous",
        )
        _git(source, "commit", "-q", "-m", "sous-module")
        _git(source, "push", "-q", self.distant("a.git"), f"HEAD:{VERSION}")
        _git(self.depot(), "pull", "-q", "--ff-only")
        _git(self.depot(), "submodule", "update", "-q", "--init")
        # Une entrée de stash ancienne, sans rapport avec la passe.
        self.ecrire(self.depot(), "b.txt", "travail ancien\n")
        _git(self.depot(), "stash", "push", "-q", "-m", "ancien")
        self.ancien = _git(self.depot(), "rev-parse", "refs/stash")

    def verifier_ancien_stash_intact(self):
        self.assertEqual(
            _git(self.depot(), "stash", "list", "--format=%H"), self.ancien
        )
        self.assertEqual(self.lire(self.depot(), "b.txt"), "un\n")

    def test_contenu_de_sous_module_ignore(self):
        self.ecrire(self.depot("odooX.0/addons/A/sous"), "s.txt", "modifie\n")
        cible = self.avancer("a.git", {"a.txt": "deux\n"})
        donnees = self.diag()
        self.assertFalse(self.constat(donnees)["sale"])
        res = self.resultat(self.appliquer(donnees)[0])
        self.assertEqual(res["etat"], "avance")
        self.assertEqual(res["stash"]["etat"], "aucun")
        self.assertEqual(self.head(), cible)
        self.verifier_ancien_stash_intact()

    def test_sous_module_deplace_refuse(self):
        sous = self.depot("odooX.0/addons/A/sous")
        self.commit(sous, {"s.txt": "local\n"}, "local")
        depart = self.head()
        self.avancer("a.git", {"a.txt": "deux\n"})
        donnees = self.diag()
        self.assertTrue(self.constat(donnees)["sale"])
        res = self.resultat(self.appliquer(donnees)[0])
        self.assertEqual(res["etat"], "erreur")
        self.assertIn("cannot save", res["motif"])
        self.assertIsNone(res["sauvegarde"])
        self.assertEqual(self.head(), depart)
        self.assertNotIn(f"{VERSION}_avant_pull_{STAMP}", self.branches())
        self.verifier_ancien_stash_intact()


class TestRetourProtege(Banc):
    """Revenir sur une sauvegarde n'ôte aucun commit fait après la passe."""

    def setUp(self):
        super().setUp()
        self.depart = self.head()
        self.avancer("a.git", {"a.txt": "deux\n"})
        charge, _code = self.appliquer(self.diag())
        self.nom = self.resultat(charge)["sauvegarde"]

    def revenir(self):
        charge, code = repo_pull.restaurer_sauvegarde(
            self.racine, CHEMIN_A, self.nom
        )
        self.assertEqual(code, 0, charge)
        return charge["resultats"][0]["etat"]

    def oublier_la_passe(self):
        shutil.rmtree(repo_pull.dossier_passe(STAMP, self.racine))

    def test_commit_apres_la_passe_refuse(self):
        precieux = self.commit(self.depot(), {"b.txt": "precieux\n"})
        self.assertEqual(self.revenir(), "head_deplacee")
        self.assertEqual(self.head(), precieux)

    def test_une_passe_suivante_d_amont_seul_n_empeche_pas_le_retour(self):
        self.avancer("a.git", {"a.txt": "trois\n"})
        charge, _code = self.appliquer(self.diag(), horodatage="20990101T0900")
        self.assertEqual(self.resultat(charge)["etat"], "avance")
        self.assertEqual(self.revenir(), "revenu")
        self.assertEqual(self.head(), self.depart)

    def test_sans_enregistrement_commit_local_refuse(self):
        self.oublier_la_passe()
        precieux = self.commit(self.depot(), {"b.txt": "precieux\n"})
        self.assertEqual(self.revenir(), "head_deplacee")
        self.assertEqual(self.head(), precieux)

    def test_sans_enregistrement_amont_seul_revient(self):
        self.oublier_la_passe()
        self.assertEqual(self.revenir(), "revenu")
        self.assertEqual(self.head(), self.depart)

    def test_sans_enregistrement_sauvegarde_hors_historique_refusee(self):
        self.oublier_la_passe()
        _git(self.depot(), "reset", "-q", "--hard", self.nom)
        _git(
            self.depot(), "branch", "-q", "-f", self.nom, f"{REMOTE}/{VERSION}"
        )
        self.commit(self.depot(), {"b.txt": "ailleurs\n"})
        self.assertEqual(self.revenir(), "head_deplacee")


class TestBascule(Banc):
    """Mode « manifeste » : un clone détaché qui change de ligne amont."""

    def setUp(self):
        super().setUp()
        self.avancer("a.git", {"a.txt": "x1\n"}, "amont x1")
        self.avancer("a.git", {"a.txt": "x2\n"}, "amont x2")
        _git(self.depot(), "pull", "-q", "--ff-only")
        _git(self.depot(), "checkout", "-q", "--detach")
        _git(self.depot(), "branch", "-q", "-D", VERSION)
        source = self.sources["a.git"]
        _git(source, "checkout", "-q", "-b", "z", "HEAD~2")
        self.cible_z = self.commit(source, {"b.txt": "z\n"}, "amont z")
        _git(source, "push", "-q", self.distant("a.git"), "HEAD:Z.0")
        self.predit = [("a.git", CHEMIN_A, "Z.0")]

    def test_sans_commit_local_le_clone_bascule(self):
        depart = self.head()
        donnees = self.diag("manifeste")
        c = self.constat(donnees)
        self.assertEqual(c["verdict"], "bascule")
        self.assertEqual((c["nos"], c["locaux"]), (2, 0))
        self.assertTrue(c["applicable"])
        charge, code = self.appliquer(donnees)
        self.assertEqual(code, 0, charge)
        res = self.resultat(charge)
        self.assertEqual(res["etat"], "tire")
        self.assertEqual(self.head(), self.cible_z)
        self.assertEqual(
            _git(self.depot(), "rev-parse", "--abbrev-ref", "HEAD"), "HEAD"
        )
        self.assertEqual(
            _git(self.depot(), "rev-parse", res["sauvegarde"]), depart
        )

    def test_bascule_meme_en_ff(self):
        donnees = self.diag("manifeste", strategie="ff")
        self.assertEqual(self.constat(donnees)["verdict"], "bascule")
        charge, _code = self.appliquer(donnees)
        self.assertEqual(self.head(), self.cible_z)

    def test_un_commit_local_garde_le_rebase(self):
        self.commit(self.depot(), {"c.txt": "local\n"}, "local")
        c = self.constat(self.diag("manifeste"))
        self.assertEqual(c["verdict"], "diverge")
        self.assertEqual((c["nos"], c["locaux"]), (3, 1))

    def test_en_mode_branche_rien_ne_bascule(self):
        _git(self.depot(), "checkout", "-q", "-b", VERSION)
        _git(self.depot(), "branch", "-q", "-u", f"{REMOTE}/{VERSION}")
        c = self.constat(self.diag("branche"))
        self.assertEqual(c["verdict"], "a_jour")
        self.assertIsNone(c["locaux"])


class TestFichiersEcrases(Banc):
    """Un fichier ignoré que la cible se met à suivre."""

    def setUp(self):
        super().setUp()
        self.ecrire(self.depot(), ".git/info/exclude", "reglages.conf\n")
        self.ecrire(self.depot(), "reglages.conf", "reglage local\n")

    def copie(self):
        return os.path.join(
            repo_pull.dossier_passe(STAMP, self.racine),
            "ecrases",
            CHEMIN_A.replace("/", "_"),
            "reglages.conf",
        )

    def test_avance_rapide_copie_d_abord(self):
        self.avancer("a.git", {"reglages.conf": "defaut amont\n"})
        donnees = self.diag()
        self.assertEqual(self.constat(donnees)["ecrases"], ["reglages.conf"])
        res = self.resultat(self.appliquer(donnees)[0])
        self.assertEqual(res["etat"], "avance")
        self.assertEqual(res["ecrases"], ["reglages.conf"])
        self.assertEqual(
            self.lire(self.depot(), "reglages.conf"), "defaut amont\n"
        )
        with open(self.copie()) as fh:
            self.assertEqual(fh.read(), "reglage local\n")

    def _conflit(self, strategie):
        self.commit(self.depot(), {"a.txt": "local\n"}, "local")
        self.avancer(
            "a.git", {"a.txt": "amont\n", "reglages.conf": "defaut amont\n"}
        )
        res = self.resultat(self.appliquer(self.diag(strategie=strategie))[0])
        self.assertEqual(res["etat"], "conflit_annule")
        self.assertEqual(
            self.lire(self.depot(), "reglages.conf"), "reglage local\n"
        )

    def test_conflit_de_rebase_remet_le_fichier(self):
        self._conflit("rebase")

    def test_conflit_de_merge_remet_le_fichier(self):
        self._conflit("merge")

    def test_fichier_non_ignore_n_est_pas_liste(self):
        os.remove(os.path.join(self.depot(), ".git/info/exclude"))
        self.avancer("a.git", {"reglages.conf": "defaut amont\n"})
        self.assertEqual(self.constat(self.diag())["ecrases"], [])


class TestTagDuManifeste(Banc):
    def test_l_essai_ne_deplace_pas_un_tag_local(self):
        _git(self.sources["a.git"], "tag", "v1")
        distant = _git(self.sources["a.git"], "rev-parse", "v1")
        _git(self.sources["a.git"], "push", "-q", self.distant("a.git"), "v1")
        local = self.commit(self.depot(), {"b.txt": "local\n"}, "local")
        _git(self.depot(), "tag", "-f", "v1", local)
        _git(self.depot(), "checkout", "-q", "--detach")
        self.predit = [("a.git", CHEMIN_A, "refs/tags/v1")]
        c = self.constat(self.diag("manifeste"))
        self.assertEqual(c["cible"], "refs/repo_pull/tags/v1")
        self.assertEqual(c["cible_sha"], distant)
        self.assertEqual(_git(self.depot(), "rev-parse", "v1"), local)


class TestSuperficielSuite(BancSuperficiel):
    """Les cas d'un clone superficiel que la borne par date rendait faux."""

    def test_fusion_d_une_vieille_branche_reste_une_avance_rapide(self):
        """L'amont fusionne par-dessus HEAD une branche dont le commit est
        plus ancien que la frontière : sans raccord, la borne cacherait
        HEAD derrière la fusion."""
        source = self.sources["s.git"]
        Banc.horloge += Banc.PAS
        vieux = Banc.horloge - 40 * Banc.PAS
        _git(source, "checkout", "-q", "-b", "vieille", self.historique[4])
        _git(
            source,
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "vieille",
            env={
                "GIT_AUTHOR_DATE": f"@{vieux} +0000",
                "GIT_COMMITTER_DATE": f"@{vieux} +0000",
            },
        )
        _git(source, "checkout", "-q", "principale")
        _git(
            source,
            "merge",
            "-q",
            "--no-ff",
            "-m",
            "fusion",
            "vieille",
            env={"GIT_COMMITTER_DATE": f"@{Banc.horloge} +0000"},
        )
        _git(source, "push", "-q", self.distant("s.git"), f"HEAD:{VERSION}")
        cible = _git(source, "rev-parse", "HEAD")
        avant = self.compte()
        donnees = self.diag()
        c = self.constat(donnees, self.CHEMIN_S)
        self.assertEqual(c["verdict"], "avance_rapide")
        self.assertGreaterEqual(c["raccords"], 1)
        self.assertEqual(donnees["plan_superficiel"], [])
        self.assertGreaterEqual(self.compte(), avant)
        res = self.resultat(self.appliquer(donnees)[0], self.CHEMIN_S)
        self.assertEqual(res["etat"], "avance")
        self.assertEqual(self.head(self.CHEMIN_S), cible)

    def test_date_decalee_ne_raccourcit_pas_l_historique(self):
        """Un commit de l'historique de HEAD daté bien avant son parent."""
        dossier = os.path.join(self.dossier, "decale")
        source = os.path.join(self.dossier, "sources", "decale")
        _git(self.distants, "init", "-q", "--bare", "decale.git")
        _git(self.dossier, "init", "-q", source)
        for i in range(5):
            self.commit(source, {"d.txt": f"{i}\n"}, f"d{i}")
        vieux = Banc.horloge - 10 * Banc.PAS
        self.ecrire(source, "d.txt", "decale\n")
        _git(
            source,
            "commit",
            "-q",
            "-am",
            "decale",
            env={
                "GIT_AUTHOR_DATE": f"@{vieux} +0000",
                "GIT_COMMITTER_DATE": f"@{vieux} +0000",
            },
        )
        self.commit(source, {"d.txt": "apres\n"}, "apres")
        _git(
            source, "push", "-q", self.distant("decale.git"), f"HEAD:{VERSION}"
        )
        self.sources["decale.git"] = source
        chemin = "odooX.0/addons/D"
        self.cloner("decale.git", chemin, profondeur=4)
        self.manifeste_local(
            [("a.git", CHEMIN_A, VERSION), ("decale.git", chemin, VERSION)]
        )
        del dossier
        avant = _git(self.depot(chemin), "rev-list", "--count", "HEAD")
        self.avancer("decale.git", {"d.txt": "neuf\n"})
        c = self.constat(self.diag(), chemin)
        self.assertEqual(c["verdict"], "avance_rapide")
        self.assertEqual(
            _git(self.depot(chemin), "rev-list", "--count", "HEAD"), avant
        )

    def test_ff_apres_approfondissement_refuse(self):
        self.diverger_par_une_fusion_ancienne()
        depart = self.head(self.CHEMIN_S)
        donnees = self.diag(strategie="ff")
        self.assertEqual(donnees["plan_superficiel"], [self.CHEMIN_S])
        charge, code = self.appliquer(donnees, approfondir=True)
        self.assertEqual(code, 0, charge)
        res = self.resultat(charge, self.CHEMIN_S)
        self.assertEqual(res["etat"], "refuse_ff")
        self.assertIsNone(res["sauvegarde"])
        self.assertEqual(self.head(self.CHEMIN_S), depart)
        self.assertNotIn(
            f"{VERSION}_avant_pull_{STAMP}", self.branches(self.CHEMIN_S)
        )

    def test_manifeste_change_de_branche_sous_la_frontiere(self):
        """Le manifeste mène « S » sur « Y.0 », partie du cinquième commit,
        sous la frontière de HEAD : l'approfondissement allonge aussi la
        branche de départ, sans quoi aucune base n'apparaît."""
        self.commit(self.depot(self.CHEMIN_S), {"local.txt": "x\n"}, "local")
        source = self.sources["s.git"]
        _git(source, "checkout", "-q", "-b", "y", self.historique[4])
        self.commit(source, {"y.txt": "y1\n"}, "y1")
        cible = self.commit(source, {"y.txt": "y2\n"}, "y2")
        _git(source, "push", "-q", self.distant("s.git"), "HEAD:Y.0")
        _git(source, "checkout", "-q", "principale")
        self.predit = [
            ("a.git", CHEMIN_A, VERSION),
            ("s.git", self.CHEMIN_S, "Y.0"),
        ]
        donnees = self.diag("manifeste")
        c = self.constat(donnees, self.CHEMIN_S)
        self.assertEqual(c["verdict"], "superficiel")
        self.assertIn("_refspec_depart", c)
        charge, code = self.appliquer(donnees, approfondir=True)
        self.assertEqual(code, 0, charge)
        res = self.resultat(charge, self.CHEMIN_S)
        self.assertEqual(res["etat"], "tire", res)
        self.assertEqual(res["approfondi"]["profondeur"], 50)
        self.assertEqual(
            _git(self.depot(self.CHEMIN_S), "rev-parse", "HEAD~1"), cible
        )


class TestEcheance(Banc):
    """« --budget » : passée l'échéance, rien de neuf ne commence."""

    def test_aucun_depot_ne_commence_apres_l_echeance(self):
        depart = self.head()
        self.avancer("a.git", {"a.txt": "deux\n"})
        donnees = self.diag()
        with patch.object(
            repo_pull,
            "echeance_de",
            return_value=repo_pull.time.monotonic() - 1,
        ):
            charge, code = self.appliquer(donnees, budget=60)
        self.assertEqual(code, 0, charge)
        res = self.resultat(charge)
        self.assertEqual(res["etat"], "saute_delai")
        self.assertTrue(charge["budget_epuise"])
        self.assertEqual(self.head(), depart)
        self.assertEqual(
            self.branches().count(f"{VERSION}_avant_pull_{STAMP}"), 0
        )
        passe = repo_pull.lire_passe(STAMP, self.racine)
        self.assertTrue(passe["termine"])
        self.assertTrue(passe["budget_epuise"])

    def test_l_enregistrement_s_ecrit_apres_chaque_depot(self):
        self.avancer("a.git", {"a.txt": "deux\n"})
        self.avancer("erplibre.git", {"conf/lisezmoi.txt": "deux\n"})
        vus = []
        reel = repo_pull.integrer

        def integrer(racine, constat, *a, **kw):
            passe = repo_pull.lire_passe(STAMP, self.racine) or {}
            vus.append(
                (
                    constat["chemin"],
                    passe.get("termine"),
                    [r["chemin"] for r in passe.get("resultats") or []],
                )
            )
            return reel(racine, constat, *a, **kw)

        with patch.object(repo_pull, "integrer", side_effect=integrer):
            charge, code = self.appliquer(self.diag())
        self.assertEqual(code, 0, charge)
        self.assertEqual(vus, [(".", False, []), (CHEMIN_A, False, ["."])])
        self.assertTrue(repo_pull.lire_passe(STAMP, self.racine)["termine"])

    def test_la_ligne_de_commande_passe_horodatage_et_budget(self):
        self.avancer("a.git", {"a.txt": "deux\n"})
        donnees = self.diag()
        args = ["--apply", "--mode", "branche", "--confirm", VERSION]
        args += ["--pass", "20990102T0900", "--budget", "600"]
        for x in donnees["attendus"]:
            args += ["--expect", x]
        sortie = io.StringIO()
        with (
            contextlib.redirect_stdout(sortie),
            patch.object(repo_pull, "passe", wraps=repo_pull.passe) as passe,
        ):
            code = repo_pull.main([*args, "--root", self.racine])
        self.assertEqual(code, 0, sortie.getvalue())
        self.assertEqual(passe.call_args.kwargs["budget"], 600)
        charge = json.loads(sortie.getvalue())
        self.assertEqual(charge["horodatage"], "20990102T0900")
        with contextlib.redirect_stdout(io.StringIO()):
            code = repo_pull.main(
                ["--apply", "--confirm", VERSION, "--pass", "hier"]
                + ["--root", self.racine]
            )
        self.assertEqual(code, repo_pull.EXIT_USAGE)


class TestRendu(Banc):
    """Le texte que le menu affiche, dans les deux langues."""

    def rendre(self, langue, fonction, donnees):
        from script.todo import todo_i18n

        with patch.object(todo_i18n, "_current_lang", langue):
            return fonction(donnees, colour=False)

    def test_essai_a_sec(self):
        self.ecrire(self.depot(), "b.txt", "modifie\n")
        self.avancer("a.git", {"a.txt": "deux\n"})
        donnees = repo_pull.public(self.diag())
        donnees["nouveaux"] = [
            {
                "chemin": CHEMIN_B,
                "url": "https://example.invalid/b.git",
                "occupe": False,
            }
        ]
        donnees["plan_superficiel"] = ["odooX.0/addons/S"]
        donnees["dependances"].update(
            fichiers=["poetry.lock"], commande="source .venv.c/bin/activate"
        )
        texte = self.rendre("en", repo_pull.render_diagnostic, donnees)
        self.assertIn("branches · rebase", texte)
        self.assertIn("fast-forward possible", texte)
        self.assertIn("[stash]", texte)
        self.assertIn("amont", texte)
        self.assertIn("restricted to their paths", texte)
        self.assertIn("deepening downloads history", texte)
        self.assertIn("source .venv.c/bin/activate", texte)
        texte = self.rendre("fr", repo_pull.render_diagnostic, donnees)
        self.assertIn("avance rapide possible", texte)
        self.assertIn("Nouveaux dépôts", texte)

    def test_passe(self):
        self.ecrire(self.depot(), "a.txt", "modifie\n")
        self.avancer("a.git", {"a.txt": "deux\n"})
        charge, _code = self.appliquer(self.diag())
        charge = repo_pull.public(charge)
        charge["manifeste"] = {"erreur": "manifeste_different"}
        charge["budget_epuise"] = True
        charge["clones"] = [{"chemin": CHEMIN_B, "etat": "clone"}]
        texte = self.rendre("en", repo_pull.render_passe, charge)
        self.assertIn("stash kept", texte)
        self.assertIn("stash apply", texte)
        self.assertIn("differs from the dry run", texte)
        self.assertIn("time budget ran out", texte)
        self.assertIn("cloned", texte)
        texte = self.rendre("fr", repo_pull.render_passe, charge)
        self.assertIn("stash gardé", texte)
        self.assertNotIn("manifeste_different", texte)
        texte = self.rendre("en", repo_pull.render_passe, {"error": "busy"})
        self.assertIn("Another pull is running", texte)


class TestLancer(unittest.TestCase):
    """`lancer` : une commande longue dans son propre groupe de processus."""

    def test_le_delai_tue_tout_le_groupe(self):
        dossier = tempfile.mkdtemp(prefix="test_repo_pull_lancer_")
        self.addCleanup(shutil.rmtree, dossier, True)
        temoin = os.path.join(dossier, "enfant.pid")
        code, sortie = repo_pull.lancer(
            ["sh", "-c", f"sleep 30 & echo $! > {temoin}; wait"],
            1,
            dossier,
            dict(os.environ),
        )
        self.assertEqual(code, 124)
        self.assertIn("timeout after 1s", sortie)
        with open(temoin) as fh:
            enfant = int(fh.read())
        for _essai in range(100):
            try:
                with open(f"/proc/{enfant}/stat") as fh:
                    etat = fh.read().split(")")[-1].split()[0]
            except (FileNotFoundError, ProcessLookupError):
                break
            if etat == "Z":
                break
            repo_pull.time.sleep(0.05)
        else:
            self.fail("le processus enfant survit au délai")

    def test_commande_absente(self):
        code, sortie = repo_pull.lancer(
            ["/nulle/part/commande"], 5, os.getcwd(), dict(os.environ)
        )
        self.assertEqual(code, 1)
        self.assertTrue(sortie)


class TestBasesParDefaut(Banc):
    def test_la_cible_par_defaut_est_fetch_head(self):
        self.avancer("a.git", {"a.txt": "deux\n"})
        _git(self.depot(), "fetch", "-q", REMOTE, VERSION)
        head = self.head()
        self.assertEqual(
            git_freeze_manifest._bases(self.depot(), head),
            git_freeze_manifest._bases(self.depot(), head, cible="FETCH_HEAD"),
        )
        self.assertEqual(
            git_freeze_manifest._bases(self.depot(), head), [head]
        )
        self.assertTrue(
            git_freeze_manifest._bases_sures(self.depot(), head, [head])
        )


@unittest.skipIf(os.geteuid() == 0, "root écrit partout : aucun refus")
class TestEcritureRefusee(Banc):
    """Un clone que le compte courant ne peut pas écrire : la garde le dit
    avant le fetch, au lieu de l'erreur de permission de git."""

    def objets_en_lecture_seule(self):
        objets = os.path.join(self.depot(), ".git", "objects")
        os.chmod(objets, 0o555)
        self.addCleanup(os.chmod, objets, 0o755)
        return objets

    def test_clone_inscriptible(self):
        self.assertIsNone(repo_pull.ecriture_refusee(self.depot()))

    def test_objets_en_lecture_seule(self):
        objets = self.objets_en_lecture_seule()
        self.avancer("a.git", {"a.txt": "deux\n"})
        donnees, _code = repo_pull.diagnostic(
            self.racine, "branche", "rebase", regenerer=self.regenerer
        )
        c = self.constat(donnees)
        self.assertEqual(c["verdict"], "fetch_echoue")
        self.assertIn(
            f"{os.path.realpath(objets)} is not writable", c["motif"]
        )
        self.assertNotIn("ERPLIBRE_CODE_OWNER", c["motif"])
        self.assertEqual(self.constat(donnees, ".")["verdict"], "a_jour")

    def test_conteneur_rappelle_le_proprietaire(self):
        self.objets_en_lecture_seule()
        existe = os.path.exists
        with patch.object(
            repo_pull.os.path,
            "exists",
            side_effect=lambda p: p == "/.dockerenv" or existe(p),
        ):
            motif = repo_pull.ecriture_refusee(self.depot())
        self.assertIn("ERPLIBRE_CODE_OWNER=odoo", motif)


class BancRetour(Banc):
    """Un retour à un instantané : « A » a tiré un commit amont depuis
    l'instantané, dont `self.i0` est le commit et `self.c1` celui d'après."""

    def setUp(self):
        super().setUp()
        self.i0 = self.head()
        self.c1 = self.avancer("a.git", {"a.txt": "deux\n"})
        _git(self.depot(), "pull", "-q", "--ff-only")
        self.fichier = os.path.join(self.dossier, "cibles.json")

    def cibles(self, depots, racine=None):
        """Écrit le fichier de cibles et le relit comme la commande."""
        with open(self.fichier, "w") as fh:
            json.dump({"racine": racine, "depots": depots}, fh)
        return repo_pull.lire_cibles(self.fichier, self.racine)

    def cible_a(self, sha=None, branche=VERSION):
        return {CHEMIN_A: {"head": sha or self.i0, "branch": branche}}

    def diag_retour(self, depots, racine=None, **kw):
        donnees, code = repo_pull.diagnostic_retour(
            self.racine, self.cibles(depots, racine), **kw
        )
        self.assertEqual(code, 0, donnees)
        return donnees

    def retour(self, depots, racine=None, donnees=None, **kw):
        """Essai à sec puis application, épinglée sur ce qu'il a montré."""
        donnees = donnees or self.diag_retour(depots, racine)
        lus = [repo_apply.lire_attendu(x) for x in donnees["attendus"]]
        kw.setdefault("horodatage", STAMP)
        return repo_pull.passe_retour(
            self.racine,
            VERSION,
            self.cibles(depots, racine),
            attendus=[c for c, _e in lus],
            epingles={c: e for c, e in lus if e},
            regenerer=self.regenerer,
            **kw,
        )

    def stashs(self, chemin=CHEMIN_A):
        return _git(self.depot(chemin), "stash", "list", "--format=%H").split()


class TestRetourEssai(BancRetour):
    def test_verdicts_et_compteurs(self):
        self.commit(self.depot(), {"b.txt": "local\n"}, "local")
        self.creer_distant("b.git", {"b.txt": "un\n"})
        d1 = self.commit(self.sources["b.git"], {"b.txt": "ailleurs\n"})
        _git(
            self.sources["b.git"],
            "push",
            "-q",
            self.distant("b.git"),
            "HEAD:autre",
        )
        self.cloner("b.git", CHEMIN_B)
        self.creer_distant("d.git", {"d.txt": "un\n"})
        chemin_d = "odooX.0/addons/D"
        self.cloner("d.git", chemin_d)
        self.manifeste_local(
            [
                ("a.git", CHEMIN_A, VERSION),
                ("b.git", CHEMIN_B, VERSION),
                ("d.git", chemin_d, VERSION),
            ]
        )
        self.cloner("d.git", "odoo99.0/addons/E")
        racine = {"head": self.head("."), "branch": VERSION}
        head_b = self.head(CHEMIN_B)
        depots = dict(self.cible_a())
        depots[CHEMIN_B] = {"head": d1, "branch": "autre"}
        depots["odooX.0/addons/C"] = {"head": d1, "branch": None}
        donnees = self.diag_retour(depots, racine)

        self.assertEqual(donnees["mode"], "instantane")
        a = self.constat(donnees)
        self.assertEqual(a["verdict"], "recul")
        self.assertEqual((a["quittes"], a["locaux"]), (2, 1))
        self.assertEqual(a["cible_branche"], VERSION)
        b = self.constat(donnees, CHEMIN_B)
        self.assertEqual(b["verdict"], "deplacement")
        self.assertEqual((b["quittes"], b["locaux"]), (0, 0))
        self.assertEqual(self.constat(donnees, ".")["verdict"], "a_jour")
        self.assertEqual(
            self.constat(donnees, "odooX.0/addons/C")["verdict"], "absent"
        )
        self.assertEqual(
            donnees["hors_instantane"], ["odoo99.0/addons/E", chemin_d]
        )
        self.assertEqual(donnees["plan"], [CHEMIN_A, CHEMIN_B])
        self.assertEqual(
            donnees["attendus"],
            [
                f"{CHEMIN_A}={self.i0}:{self.head()}",
                f"{CHEMIN_B}={d1}:{self.head(CHEMIN_B)}",
            ],
        )
        self.assertEqual(self.head(CHEMIN_B), head_b, "rien ne bouge")
        self.assertEqual(
            _git(self.depot(CHEMIN_B), "branch", "--show-current"), VERSION
        )

    def test_sha_absent_recupere_par_son_sha(self):
        source = self.sources["a.git"]
        _git(source, "checkout", "-q", "-b", "cachee", self.i0)
        cache = self.commit(source, {"a.txt": "cache\n"}, "cache")
        _git(source, "push", "-q", self.distant("a.git"), "HEAD:cachee")
        self.assertFalse(repo_pull.repo_state.resoudre(self.depot(), cache))
        avant = self.branches()
        c = self.constat(self.diag_retour(self.cible_a(cache, None)))
        self.assertEqual((c["verdict"], c["fetch"]), ("deplacement", "ok"))
        self.assertEqual(
            repo_pull.repo_state.resoudre(self.depot(), cache), cache
        )
        self.assertEqual(self.head(), self.c1, "l'essai à sec ne bouge rien")
        self.assertEqual(self.branches(), avant)

    def test_commit_introuvable(self):
        absent = "ab" * 20
        c = self.constat(self.diag_retour(self.cible_a(absent)))
        self.assertEqual(c["verdict"], "commit_introuvable")
        self.assertIn(REMOTE, c["motif"])
        self.assertEqual(self.head(), self.c1)

    def test_remote_injoignable(self):
        _git(
            self.depot(),
            "remote",
            "set-url",
            REMOTE,
            os.path.join(self.distants, "perdu.git"),
        )
        c = self.constat(self.diag_retour(self.cible_a("ab" * 20)))
        self.assertEqual(c["verdict"], "fetch_echoue")

    def test_fichier_de_cibles_refuse(self):
        for depots in (
            {CHEMIN_A: {"head": "court", "branch": None}},
            {"../dehors": {"head": self.i0, "branch": None}},
            {CHEMIN_A: {"head": self.i0, "branch": "-x"}},
        ):
            with self.assertRaises(ValueError):
                self.cibles(depots)

    def test_chemin_seul_hors_des_cibles(self):
        donnees, code = repo_pull.diagnostic_retour(
            self.racine, self.cibles(self.cible_a()), chemin_seul="z"
        )
        self.assertEqual(code, repo_pull.EXIT_CIBLE)


class TestRetourApplication(BancRetour):
    def test_recul_puis_retour_par_la_sauvegarde(self):
        charge, code = self.retour(self.cible_a())
        self.assertEqual(code, 0, charge)
        res = self.resultat(charge)
        nom = f"{VERSION}_avant_retour_{STAMP}"
        self.assertEqual(res["etat"], "recule")
        self.assertEqual((res["depart"], res["arrivee"]), (self.c1, self.i0))
        self.assertEqual(res["sauvegarde"], nom)
        self.assertEqual(res["stash"]["etat"], "aucun")
        self.assertEqual(self.head(), self.i0)
        self.assertEqual(
            _git(self.depot(), "branch", "--show-current"), VERSION
        )
        passe = repo_pull.lire_passe(STAMP, self.racine)
        self.assertEqual(passe["mode"], "instantane")
        self.assertTrue(passe["termine"])
        lst = repo_pull.lister_sauvegardes(self.racine)["sauvegardes"]
        self.assertEqual(
            [(x["nom"], x["sha"], x["branche"]) for x in lst],
            [(nom, self.c1, VERSION)],
        )
        charge, code = repo_pull.restaurer_sauvegarde(
            self.racine, CHEMIN_A, nom
        )
        self.assertEqual(charge["resultats"][0]["etat"], "revenu", charge)
        self.assertEqual(self.head(), self.c1)

    def test_arbre_sale_stashe_et_garde(self):
        self.ecrire(self.depot(), "b.txt", "travail\n")
        donnees = self.diag_retour(self.cible_a())
        self.assertTrue(self.constat(donnees)["stash_prevu"])
        charge, _code = self.retour(self.cible_a(), donnees=donnees)
        stash = self.resultat(charge)["stash"]
        self.assertEqual(stash["etat"], "garde")
        self.assertEqual(self.stashs(), [stash["sha"]])
        self.assertEqual(stash["message"], f"repo_pull retour {STAMP}")
        self.assertEqual(
            stash["commande"], f"git -C {CHEMIN_A} stash apply {stash['sha']}"
        )
        self.assertEqual(self.lire(self.depot(), "b.txt"), "un\n")
        self.assertEqual(self.head(), self.i0)

    def test_cible_detachee(self):
        charge, _code = self.retour(self.cible_a(branche=None))
        self.assertEqual(self.resultat(charge)["etat"], "recule")
        self.assertEqual(self.head(), self.i0)
        self.assertEqual(_git(self.depot(), "branch", "--show-current"), "")
        self.assertEqual(
            _git(self.depot(), "rev-parse", VERSION),
            self.c1,
            "branche intacte",
        )

    def test_branche_absente_creee_sur_le_sha(self):
        charge, _code = self.retour(self.cible_a(branche="ancienne"))
        res = self.resultat(charge)
        self.assertEqual(res["etat"], "recule")
        self.assertEqual(res["branche_arrivee"], "ancienne")
        self.assertEqual(
            _git(self.depot(), "branch", "--show-current"), "ancienne"
        )
        self.assertEqual(self.head(), self.i0)
        self.assertEqual(_git(self.depot(), "rev-parse", VERSION), self.c1)
        charge, _code = repo_pull.restaurer_sauvegarde(
            self.racine, CHEMIN_A, res["sauvegarde"]
        )
        self.assertEqual(charge["resultats"][0]["etat"], "revenu", charge)
        self.assertEqual(
            _git(self.depot(), "branch", "--show-current"), VERSION
        )
        self.assertEqual(self.head(), self.c1)

    def test_autre_branche_existante_sauvegardee_puis_rendue(self):
        _git(self.depot(), "branch", "ancienne", self.c1)
        charge, _code = self.retour(self.cible_a(branche="ancienne"))
        res = self.resultat(charge)
        self.assertEqual(
            res["sauvegarde_cible"], f"ancienne_avant_retour_{STAMP}"
        )
        self.assertEqual(_git(self.depot(), "rev-parse", "ancienne"), self.i0)
        charge, _code = repo_pull.restaurer_sauvegarde(
            self.racine, CHEMIN_A, res["sauvegarde"]
        )
        self.assertEqual(charge["resultats"][0]["etat"], "revenu", charge)
        self.assertEqual(
            _git(self.depot(), "branch", "--show-current"), VERSION
        )
        self.assertEqual(_git(self.depot(), "rev-parse", "ancienne"), self.c1)

    def test_racine_en_dernier_puis_manifeste_regenere(self):
        r0 = self.head(".")
        self.avancer("erplibre.git", {"conf/lisezmoi.txt": "deux\n"})
        _git(self.racine, "pull", "-q", "--ff-only")
        r1 = self.head(".")
        self.predit = [("a.git", CHEMIN_A, "Y.0")]
        ordre = []
        vrai = repo_pull.retourner

        def retourner(racine, constat, *a, **kw):
            ordre.append(constat["chemin"])
            return vrai(racine, constat, *a, **kw)

        racine = {"head": r0, "branch": VERSION}
        with patch.object(repo_pull, "retourner", retourner):
            charge, code = self.retour(self.cible_a(), racine)
        self.assertEqual(code, 0, charge)
        self.assertEqual(ordre, [CHEMIN_A, "."])
        self.assertEqual(self.head("."), r0)
        self.assertEqual([x[0] for x in self.appels_regenerer], [self.racine])
        manifeste = charge["manifeste"]
        self.assertTrue(manifeste["ecrit"], manifeste)
        local = repo_pull.repo_state.MANIFESTE_LOCAL
        self.assertIn('revision="Y.0"', self.lire(self.racine, local))
        nom = self.resultat(charge, ".")["sauvegarde"]
        charge, _code = repo_pull.restaurer_sauvegarde(self.racine, ".", nom)
        res = charge["resultats"][0]
        self.assertEqual(res["etat"], "revenu", charge)
        self.assertTrue(res["manifeste_restaure"])
        self.assertEqual(self.head("."), r1)
        self.assertIn(f'revision="{VERSION}"', self.lire(self.racine, local))

    def test_clone_hors_manifeste_revient_par_sa_sauvegarde(self):
        chemin = "odoo99.0/addons/E"
        self.cloner("a.git", chemin)
        charge, _code = self.retour(
            {chemin: {"head": self.i0, "branch": VERSION}}
        )
        nom = self.resultat(charge, chemin)["sauvegarde"]
        self.assertEqual(self.head(chemin), self.i0)
        designe = repo_pull.lire_designation(self.racine, f"{chemin}={nom}")
        charge, _code = repo_pull.restaurer_sauvegarde(self.racine, *designe)
        self.assertEqual(charge["resultats"][0]["etat"], "revenu", charge)
        self.assertEqual(self.head(chemin), self.c1)

    def test_hors_plan_dans_les_resultats(self):
        depots = dict(self.cible_a())
        racine = {"head": self.head("."), "branch": VERSION}
        charge, _code = self.retour(depots, racine)
        self.assertEqual(self.resultat(charge, ".")["etat"], "a_jour")
        self.assertIsNone(charge["manifeste"], "la racine n'a pas bougé")
        depots[CHEMIN_A] = {"head": "ab" * 20, "branch": None}
        charge, _code = self.retour(depots, horodatage="20990101T0900")
        self.assertEqual(self.resultat(charge)["etat"], "saute_introuvable")
        self.assertIsNone(charge["horodatage"], "rien n'est écrit")

    def test_epingle_derivee(self):
        donnees = self.diag_retour(self.cible_a())
        self.commit(self.depot(), {"b.txt": "local\n"}, "local")
        charge, code = self.retour(self.cible_a(), donnees=donnees)
        self.assertEqual(code, repo_pull.EXIT_PLAN_CHANGE)
        self.assertEqual(charge["derives"][0]["cle"], "head")
        self.assertNotIn(f"{VERSION}_avant_retour_{STAMP}", self.branches())
        self.assertFalse(
            os.path.exists(repo_pull.dossier_passe(STAMP, self.racine))
        )

    def test_plan_different(self):
        donnees = self.diag_retour(self.cible_a())
        donnees["attendus"] = []
        charge, code = self.retour(self.cible_a(), donnees=donnees)
        self.assertEqual(code, repo_pull.EXIT_PLAN_CHANGE)
        self.assertEqual(self.head(), self.c1)


class TestRetourSuperficiel(BancSuperficiel):
    def test_commit_sous_la_frontiere_recupere_seul(self):
        ancien = self.historique[5]
        fichier = os.path.join(self.dossier, "cibles.json")
        with open(fichier, "w") as fh:
            json.dump(
                {
                    "racine": None,
                    "depots": {
                        self.CHEMIN_S: {"head": ancien, "branch": None}
                    },
                },
                fh,
            )
        cibles = repo_pull.lire_cibles(fichier, self.racine)
        donnees, _code = repo_pull.diagnostic_retour(self.racine, cibles)
        c = self.constat(donnees, self.CHEMIN_S)
        self.assertIn(c["verdict"], ("recul", "deplacement"), c)
        self.assertEqual(self.compte(), 3, "l'historique de HEAD reste")
        depot = self.depot(self.CHEMIN_S)
        self.assertEqual(_git(depot, "rev-list", "--count", ancien), "1")
        lus = [repo_apply.lire_attendu(x) for x in donnees["attendus"]]
        charge, code = repo_pull.passe_retour(
            self.racine,
            VERSION,
            cibles,
            attendus=[c for c, _e in lus],
            epingles={c: e for c, e in lus if e},
            horodatage=STAMP,
        )
        self.assertEqual(code, 0, charge)
        self.assertEqual(self.head(self.CHEMIN_S), ancien)


class TestReappliquerStash(BancRetour):
    def setUp(self):
        super().setUp()
        self.ecrire(self.depot(), "b.txt", "travail\n")
        charge, _code = self.retour(self.cible_a())
        self.sha = self.resultat(charge)["stash"]["sha"]

    def reappliquer(self):
        charge, code = repo_pull.reappliquer_stash(
            self.racine, CHEMIN_A, self.sha
        )
        return charge, code

    def test_applique_et_garde_le_stash(self):
        charge, code = self.reappliquer()
        self.assertEqual((charge["etat"], code), ("applique", 0), charge)
        self.assertEqual(self.lire(self.depot(), "b.txt"), "travail\n")
        self.assertEqual(self.stashs(), [self.sha])

    def test_refuse_un_arbre_sale(self):
        self.ecrire(self.depot(), "a.txt", "autre\n")
        charge, _code = self.reappliquer()
        self.assertEqual(charge["etat"], "refuse_sale")
        self.assertEqual(self.lire(self.depot(), "a.txt"), "autre\n")

    def test_conflit_laisse_l_arbre_propre(self):
        _git(self.depot(), "checkout", "-q", VERSION)
        _git(self.depot(), "reset", "-q", "--hard", self.c1)
        self.ecrire(self.depot(), "a.txt", "travail\n")
        _git(self.depot(), "stash", "push", "-q", "-m", "a")
        self.sha = _git(self.depot(), "rev-parse", "refs/stash")
        _git(self.depot(), "reset", "-q", "--hard", self.i0)
        charge, _code = self.reappliquer()
        self.assertEqual(charge["etat"], "conflit", charge)
        self.assertEqual(
            _git(
                self.depot(), "status", "--porcelain", "--untracked-files=no"
            ),
            "",
        )
        self.assertIn(self.sha, self.stashs())

    def test_introuvable(self):
        self.sha = self.c1
        charge, code = self.reappliquer()
        self.assertEqual(charge["etat"], "introuvable")
        self.assertEqual(code, repo_pull.EXIT_CIBLE)


class TestRetourLigneDeCommande(BancRetour):
    def main(self, *args):
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie):
            code = repo_pull.main([*args, "--root", self.racine])
        return json.loads(sortie.getvalue()), code

    def test_essai_puis_application(self):
        self.ecrire(self.depot(), "b.txt", "travail\n")
        self.cibles(self.cible_a())
        commun = ["--mode", "instantane", "--targets", self.fichier, "--json"]
        donnees, code = self.main("--dry-run", *commun)
        self.assertEqual(code, 0, donnees)
        self.assertEqual(donnees["plan"], [CHEMIN_A])
        self.assertNotIn("_attrs", donnees["depots"][0])
        args = ["--apply", *commun, "--confirm", VERSION, "--pass", STAMP]
        for x in donnees["attendus"]:
            args += ["--expect", x]
        charge, code = self.main(*args)
        self.assertEqual(code, 0, charge)
        self.assertEqual(self.resultat(charge)["etat"], "recule")
        sha = self.resultat(charge)["stash"]["sha"]
        charge, code = self.main(
            "--apply-stash", f"{CHEMIN_A}={sha}", "--confirm", VERSION
        )
        self.assertEqual(
            (charge["command"], charge["etat"]), ("apply-stash", "applique")
        )
        _c, code = self.main("--apply-stash", f"{CHEMIN_A}={sha}")
        self.assertEqual(code, repo_pull.EXIT_USAGE, "--confirm exigé")

    def test_usage(self):
        _c, code = self.main("--dry-run", "--mode", "instantane")
        self.assertEqual(code, repo_pull.EXIT_USAGE)
        self.cibles(self.cible_a())
        _c, code = self.main("--dry-run", "--targets", self.fichier)
        self.assertEqual(code, repo_pull.EXIT_USAGE)
        with open(self.fichier, "w") as fh:
            fh.write("{")
        _c, code = self.main(
            "--dry-run", "--mode", "instantane", "--targets", self.fichier
        )
        self.assertEqual(code, repo_pull.EXIT_USAGE)
        _c, code = self.main(
            "--apply-stash", "z=" + "ab" * 20, "--confirm", VERSION
        )
        self.assertEqual(code, repo_pull.EXIT_CIBLE)


if __name__ == "__main__":
    unittest.main()
