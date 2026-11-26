#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le retour des pull requests d'une forge : lecture, rapatriement, gel.

Les fonctions pures se testent seules, la lecture contre un faux client,
le rapatriement sur de vrais dépôts git temporaires dont la « forge » est
un dépôt nu joint par son chemin. Aucun réseau. Tous les noms, hôtes,
comptes et jetons sont inventés.
"""

import os
import shutil
import tempfile
import unittest
from unittest import mock

from script.git import forge_pull_requests as fpr
from script.git import repo_upgrade
from script.git.forgejo_client import ErreurForgejo
from test.test_push_remote import _git

SHA = "a" * 40
AUTRE = "b" * 40


def pr(numero, **champs):
    """Une pull request de l'API, réduite aux champs que lit le module."""
    base = {
        "number": numero,
        "title": f"PR {numero}",
        "html_url": f"https://forge.example.invalid/P/d/pulls/{numero}",
        "state": "open",
        "merged": False,
        "comments": 0,
        "head": {"ref": "tete", "sha": SHA, "repo": {"full_name": "P/d"}},
        "base": {"ref": "X.0", "repo": {"full_name": "P/d"}},
    }
    base.update(champs)
    return base


class TestPures(unittest.TestCase):
    def test_etat_pr(self):
        for attendu, champs in (
            ("fusionnee", {"merged": True, "state": "closed"}),
            ("fermee", {"state": "closed"}),
            ("brouillon", {"draft": True}),
            ("brouillon", {"title": "wip: x"}),
            ("brouillon", {"title": "[WIP] x"}),
            ("ouverte", {"title": "x WIP:"}),
        ):
            with self.subTest(champs=champs):
                self.assertEqual(fpr.etat_pr(pr(1, **champs)), attendu)

    def test_affichable(self):
        self.assertEqual(fpr.affichable("a\x1b[2Jb"), "a?[2Jb")
        self.assertEqual(fpr.affichable("a\x9bb\nc"), "a?b?c")
        self.assertEqual(fpr.affichable(None), "")

    def revue(self, revues):
        from script.git import manifest_repo

        return manifest_repo.etat_revue(fpr.revues_github(revues))

    def test_revues(self):
        approuve = {"user": {"login": "u"}, "state": "APPROVED"}
        change = {"user": {"login": "u"}, "state": "REQUEST_CHANGES"}
        self.assertEqual(self.revue([approuve, change]), "changements")
        self.assertEqual(self.revue([change, approuve]), "approuvee")
        self.assertIsNone(self.revue([dict(change, dismissed=True)]))
        self.assertIsNone(
            self.revue([{"user": {"login": "u"}, "state": "COMMENT"}])
        )
        self.assertEqual(
            fpr.revues_github([None, "x", change])[0]["state"],
            "CHANGES_REQUESTED",
        )

    def test_etat_ci(self):
        self.assertIsNone(fpr.etat_ci(None))
        self.assertIsNone(fpr.etat_ci({}))
        self.assertIsNone(fpr.etat_ci({"state": "failure", "total_count": 0}))
        for etat, attendu in (
            ("failure", "echec"),
            ("error", "echec"),
            ("pending", "en_cours"),
            ("success", "succes"),
            ("warning", "succes"),
        ):
            with self.subTest(etat=etat):
                self.assertEqual(
                    fpr.etat_ci({"state": etat, "total_count": 2}), attendu
                )

    def test_pertinentes(self):
        par_branche = pr(1, base={"ref": "autre"})
        par_base = pr(2, head={"ref": "inconnue", "sha": SHA})
        hors = pr(3, head={"ref": "inconnue"}, base={"ref": "autre"})
        fork = pr(
            4,
            head={"ref": "tete", "repo": {"full_name": "Autre/d"}},
            base={"ref": "autre"},
        )
        sans_depot = pr(5, head={"ref": "tete"}, base={"ref": "autre"})
        res = fpr.pertinentes(
            [par_branche, par_base, hors, fork, sans_depot, par_branche],
            {"tete"},
            "X.0",
            "p/D",
        )
        self.assertEqual([p["number"] for p in res], [1, 2, 5])


class FauxClient:
    """Rend les listes données et note chaque appel."""

    def __init__(self, ouvertes=(), fermees=(), erreur=None):
        self.ouvertes = list(ouvertes)
        self.fermees = list(fermees)
        self.erreur = erreur
        self.appels = []

    def pull_requests(self, o, d, etat="open", tri=None, limite=None):
        self.appels.append(("pull_requests", etat, tri, limite))
        if self.erreur:
            raise self.erreur
        return self.ouvertes if etat == "open" else self.fermees

    def revues_pull_request(self, o, d, numero):
        self.appels.append(("revues", numero))
        return [{"user": {"login": "u"}, "state": "APPROVED"}]

    def statut_combine(self, o, d, sha):
        self.appels.append(("statut", sha))
        return {"state": "success", "total_count": 1}


class TestLire(unittest.TestCase):
    def test_revue_et_ci_pour_les_ouvertes_seulement(self):
        fusionnee = pr(
            9,
            state="closed",
            merged=True,
            merge_commit_sha=AUTRE,
            merged_at="2000-01-02T03:04:05Z",
            comments=3,
        )
        client = FauxClient([pr(1), pr(2, draft=True)], [fusionnee])
        res = fpr.lire(client, "P", "d", {"tete"}, "X.0")
        self.assertEqual([p["numero"] for p in res], [1, 2, 9])
        self.assertEqual(
            [a[1] for a in client.appels if a[0] == "revues"], [1, 2]
        )
        self.assertEqual(
            [a for a in client.appels if a[0] == "statut"],
            [("statut", SHA), ("statut", SHA)],
        )
        ouverte, _brouillon, fermee = res
        self.assertEqual(
            (ouverte["revue"], ouverte["ci"]), ("approuvee", "succes")
        )
        self.assertEqual(
            (fermee["etat"], fermee["sha_fusion"], fermee["fusionnee_le"]),
            ("fusionnee", AUTRE, "2000-01-02"),
        )
        self.assertEqual(fermee["commentaires"], 3)
        self.assertIsNone(fermee["revue"])

    def test_les_fermees_sont_bornees(self):
        fermees = [pr(n, state="closed") for n in range(10, 30)]
        client = FauxClient([], fermees)
        res = fpr.lire(client, "P", "d", {"tete"}, "X.0", fermees=2)
        self.assertEqual([p["numero"] for p in res], [10, 11])
        self.assertIn(
            ("pull_requests", "closed", "recentupdate", 8), client.appels
        )

    def test_le_titre_perd_ses_caracteres_de_controle(self):
        client = FauxClient([pr(1, title="a\x1b[31mb")])
        (res,) = fpr.lire(client, "P", "d", {"tete"}, "X.0")
        self.assertEqual(res["titre"], "a?[31mb")

    def test_un_refus_de_l_api_remonte(self):
        client = FauxClient(erreur=ErreurForgejo("GET : 404", 404))
        with self.assertRaises(ErreurForgejo):
            fpr.lire(client, "P", "d", set(), "X.0")


class _Depots(unittest.TestCase):
    """Une forge nue, un auteur qui y pousse « X.0 », et le clone testé,
    dont le remote « forge » est le chemin de la forge."""

    def setUp(self):
        self.dossier = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dossier, True)
        env = mock.patch.dict(
            os.environ,
            {
                "GIT_CEILING_DIRECTORIES": self.dossier,
                "GIT_AUTHOR_NAME": "Test",
                "GIT_AUTHOR_EMAIL": "test@example.invalid",
                "GIT_COMMITTER_NAME": "Test",
                "GIT_COMMITTER_EMAIL": "test@example.invalid",
            },
        )
        env.start()
        self.addCleanup(env.stop)
        self.forge = os.path.join(self.dossier, "forge.git")
        self.auteur = os.path.join(self.dossier, "auteur")
        self.clone = os.path.join(self.dossier, "clone")
        _git(self.dossier, "init", "-q", "--bare", self.forge)
        _git(self.dossier, "init", "-q", self.auteur)
        _git(self.auteur, "remote", "add", "forge", self.forge)
        self.commit(self.auteur, "un")
        _git(self.auteur, "push", "-q", "forge", "HEAD:refs/heads/X.0")
        _git(self.dossier, "init", "-q", self.clone)
        _git(self.clone, "remote", "add", "forge", self.forge)
        _git(self.clone, "fetch", "-q", "forge")
        _git(self.clone, "checkout", "-q", "-b", "travail", "forge/X.0")

    def commit(self, depot, contenu):
        with open(os.path.join(depot, "a.txt"), "w") as fh:
            fh.write(contenu)
        _git(depot, "add", "a.txt")
        _git(depot, "commit", "-q", "-m", contenu)
        return _git(depot, "rev-parse", "HEAD")

    def avancer_forge(self, contenu="deux"):
        sha = self.commit(self.auteur, contenu)
        _git(self.auteur, "push", "-q", "forge", "HEAD:refs/heads/X.0")
        return sha

    def ref(self, ref):
        return repo_upgrade.commit_de(self.clone, ref)


class TestRapatrier(_Depots):
    def test_une_branche_absente_est_creee_sans_toucher_head(self):
        tete = self.ref("HEAD")
        neuf = self.avancer_forge()
        r = fpr.rapatrier(self.clone, "forge", "X.0")
        self.assertEqual(
            (r["etat"], r["sha"], r["ancien"]), ("creee", neuf, None)
        )
        self.assertEqual(self.ref("refs/heads/X.0"), neuf)
        self.assertEqual(self.ref("HEAD"), tete)
        self.assertEqual(
            _git(self.clone, "symbolic-ref", "HEAD"), "refs/heads/travail"
        )
        # Aucune configuration de suivi : repo l'ignore.
        _out, _err, code = repo_upgrade.git(
            ["config", "--get-regexp", r"^branch\.X\.0\."], self.clone
        )
        self.assertEqual(code, 1)

    def test_une_branche_en_retard_non_extraite_avance(self):
        _git(self.clone, "branch", "X.0", "forge/X.0")
        tete = self.ref("HEAD")
        neuf = self.avancer_forge()
        r = fpr.rapatrier(self.clone, "forge", "X.0")
        self.assertEqual(r["etat"], "avance")
        self.assertEqual(self.ref("refs/heads/X.0"), neuf)
        self.assertEqual(self.ref("HEAD"), tete)

    def test_une_branche_extraite_propre_avance(self):
        _git(self.clone, "checkout", "-q", "-b", "X.0", "forge/X.0")
        neuf = self.avancer_forge()
        self.assertEqual(
            fpr.rapatrier(self.clone, "forge", "X.0")["etat"], "avance"
        )
        self.assertEqual(self.ref("HEAD"), neuf)

    def test_une_branche_extraite_sale_reste(self):
        _git(self.clone, "checkout", "-q", "-b", "X.0", "forge/X.0")
        tete = self.ref("HEAD")
        self.avancer_forge()
        with open(os.path.join(self.clone, "a.txt"), "w") as fh:
            fh.write("modifié")
        self.assertEqual(
            fpr.rapatrier(self.clone, "forge", "X.0")["etat"], "sale"
        )
        self.assertEqual(self.ref("HEAD"), tete)

    def test_une_branche_divergee_reste(self):
        _git(self.clone, "checkout", "-q", "-b", "X.0", "forge/X.0")
        local = self.commit(self.clone, "local")
        _git(self.clone, "checkout", "-q", "travail")
        self.avancer_forge()
        r = fpr.rapatrier(self.clone, "forge", "X.0")
        self.assertEqual(r["etat"], "diverge")
        self.assertEqual(self.ref("refs/heads/X.0"), local)

    def test_une_branche_en_avance_reste(self):
        _git(self.clone, "checkout", "-q", "-b", "X.0", "forge/X.0")
        local = self.commit(self.clone, "local")
        r = fpr.rapatrier(self.clone, "forge", "X.0")
        self.assertEqual(r["etat"], "en_avance")
        self.assertEqual(self.ref("refs/heads/X.0"), local)

    def test_une_branche_egale_est_a_jour(self):
        _git(self.clone, "branch", "X.0", "forge/X.0")
        self.assertEqual(
            fpr.rapatrier(self.clone, "forge", "X.0")["etat"], "a_jour"
        )

    def test_un_remote_absent_echoue_au_fetch(self):
        r = fpr.rapatrier(self.clone, "absent", "X.0")
        self.assertEqual(r["etat"], "echec_fetch")

    def test_une_operation_en_cours_bloque(self):
        _git(self.clone, "branch", "X.0", "forge/X.0")
        ancien = self.ref("refs/heads/X.0")
        self.avancer_forge()
        os.makedirs(os.path.join(self.clone, ".git", "rebase-merge"))
        r = fpr.rapatrier(self.clone, "forge", "X.0")
        self.assertEqual(r["etat"], "operation_en_cours")
        self.assertEqual(self.ref("refs/heads/X.0"), ancien)

    def test_un_nom_de_branche_option_ne_touche_pas_git_reseau(self):
        with mock.patch.object(
            fpr.repo_upgrade, "git", wraps=repo_upgrade.git
        ) as git:
            for base in ("--upload-pack=x", "", "a..b", "@{-1}"):
                with self.subTest(base=base):
                    r = fpr.rapatrier(self.clone, "forge", base)
                    self.assertEqual(
                        (r["etat"], r["detail"]), ("refus", fpr.NOM_INVALIDE)
                    )
        self.assertNotIn("fetch", [a.args[0][0] for a in git.call_args_list])

    def test_un_echec_de_fetch_masque_le_secret(self):
        vrai = repo_upgrade.git

        def git(args, cwd, delai=repo_upgrade.DELAI_GIT):
            if args[0] == "fetch":
                return (
                    "",
                    "fatal: unable to access"
                    " 'https://jeton@forge.example.invalid/P/d.git/':"
                    " Could not resolve host",
                    128,
                )
            return vrai(args, cwd, delai)

        with mock.patch.object(fpr.repo_upgrade, "git", side_effect=git):
            r = fpr.rapatrier(self.clone, "forge", "X.0")
        self.assertEqual(r["etat"], "echec_fetch")
        self.assertNotIn("jeton", r["detail"])
        self.assertIn("forge.example.invalid", r["detail"])


class TestDejaLocal(_Depots):
    def test_selon_l_ascendance(self):
        _git(self.clone, "branch", "X.0", "forge/X.0")
        dans = self.ref("refs/heads/X.0")
        hors = self.commit(self.clone, "hors")
        self.assertTrue(
            fpr.deja_local(self.clone, {"sha_fusion": dans, "base": "X.0"})
        )
        self.assertFalse(
            fpr.deja_local(self.clone, {"sha_fusion": hors, "base": "X.0"})
        )
        self.assertFalse(
            fpr.deja_local(self.clone, {"sha_fusion": SHA, "base": "X.0"})
        )
        self.assertFalse(
            fpr.deja_local(self.clone, {"sha_fusion": "", "base": "X.0"})
        )


class TestCandidatsGel(unittest.TestCase):
    FETCH = {"Orig": "https://code.example.invalid/Orig/"}

    def projet(self, nom, **champs):
        p = {
            "cle": f"{nom}+x/{nom}",
            "chemin": f"/r/x/{nom}",
            "affiche": f"x/{nom}",
            "nom": nom,
            "remote": "Orig",
            "branche": "X.0",
        }
        p.update(champs)
        return p

    def lancer(self, projets, rapatries, gels, avance=True):
        definitions = {
            p["cle"]: [
                ("manifest/m.xml", {"freeze-revision": gels.get(p["nom"])})
            ]
            for p in projets
        }
        return fpr.candidats_gel(
            projets,
            rapatries,
            definitions,
            self.FETCH,
            avance_sur=lambda chemin, ancien, neuf: avance,
        )

    def test_un_projet_gele_avance(self):
        p = self.projet("a")
        depots, ignores = self.lancer(
            [p],
            {p["chemin"]: ("X.0", {"etat": "avance", "sha": SHA})},
            {"a": AUTRE},
        )
        self.assertEqual(ignores, [])
        self.assertEqual(
            depots,
            [
                {
                    "path": "x/a",
                    "name": "a",
                    "head": SHA,
                    "freeze_revision": AUTRE,
                    "url": "https://code.example.invalid/Orig/a",
                    "manifest_branch": "X.0",
                    "branch": "X.0",
                }
            ],
        )

    def test_les_ecartes(self):
        racine = self.projet("r", racine=True)
        sans_gel = self.projet("b")
        meme = self.projet("c")
        autre_base = self.projet("d")
        sans_path = self.projet("e", cle="e+None")
        non_gelable = self.projet("f")
        projets = [racine, sans_gel, meme, autre_base, sans_path, non_gelable]
        ok = {"etat": "avance", "sha": SHA}
        rapatries = {p["chemin"]: ("X.0", ok) for p in projets}
        rapatries[autre_base["chemin"]] = ("Y.0", ok)
        rapatries[non_gelable["chemin"]] = (
            "X.0",
            {"etat": "diverge", "sha": SHA},
        )
        depots, ignores = self.lancer(
            projets,
            rapatries,
            {"r": AUTRE, "c": SHA, "d": AUTRE, "e": AUTRE, "f": AUTRE},
        )
        self.assertEqual(depots, [])
        self.assertEqual(
            [(p["nom"], motif) for p, motif in ignores],
            [
                ("b", "not frozen"),
                ("c", "freeze already on this commit"),
                ("d", "merged into another branch"),
                ("e", "no path in the manifest"),
            ],
        )

    def test_le_gel_n_avance_que_vers_l_avant(self):
        p = self.projet("a")
        rapatries = {p["chemin"]: ("X.0", {"etat": "creee", "sha": SHA})}
        for avance, motif in (
            (False, "the freeze is not an ancestor of the merged commit"),
            (None, "freeze commit not in the clone"),
        ):
            with self.subTest(avance=avance):
                depots, ignores = self.lancer(
                    [p], rapatries, {"a": AUTRE}, avance
                )
                self.assertEqual(depots, [])
                self.assertEqual([m for _p, m in ignores], [motif])

    def test_le_dernier_gel_des_definitions_l_emporte(self):
        p = self.projet("a")
        definitions = {
            p["cle"]: [
                ("manifest/m.xml", {"freeze-revision": SHA}),
                ("manifest/m_dev.xml", {}),
                ("private/manifest/p.xml", {"freeze-revision": AUTRE}),
            ]
        }
        depots, _ = fpr.candidats_gel(
            [p],
            {p["chemin"]: ("X.0", {"etat": "avance", "sha": "c" * 40})},
            definitions,
            self.FETCH,
            avance_sur=lambda *a: True,
        )
        self.assertEqual(depots[0]["freeze_revision"], AUTRE)


if __name__ == "__main__":
    unittest.main()
