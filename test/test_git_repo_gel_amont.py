#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""La base amont d'un fork gelé, calculée sur de vrais dépôts temporaires.

Un dépôt « amont », un dépôt nu « fork » qui en descend avec ses propres
commits, et un clone du fork, tous servis par des chemins locaux : le
« réseau » ne sort jamais du dossier temporaire. Le clone superficiel passe
par « file:// », seul transport local qui honore « --depth ».

Tous les noms de dépôts, chemins et commits sont inventés.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from script.git import git_freeze_manifest as gel
from script.git import git_merge_repo_manifest as fusion
from script.git import manifest_freeze as mf
from script.git import repo_upgrade

BASE = mf.FORK_UPSTREAM_FREEZE_ATTR
REMOTE_FORK = "R_origin_U"
SHA_A = "a" * 40
SHA_B = "b" * 40


def _git(cwd, *args):
    """Lance git sans dépendre de la configuration de l'hôte. Rend stdout."""
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
            "-c",
            "protocol.file.allow=always",
            *args,
        ],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


class DepotsTemporaires(unittest.TestCase):
    """Un amont, un fork nu qui en descend, et de quoi les cloner."""

    def setUp(self):
        self.dossier = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dossier, True)
        plafond = patch.dict(
            os.environ, {"GIT_CEILING_DIRECTORIES": self.dossier}
        )
        plafond.start()
        self.addCleanup(plafond.stop)
        self.amont = os.path.join(self.dossier, "amont")
        self.fork = os.path.join(self.dossier, "fork.git")
        _git(self.dossier, "init", "-q", self.amont)

    def commits(self, depot, prefixe, nombre):
        """`nombre` commits sur la branche courante de `depot`. Rend le
        dernier."""
        for i in range(nombre):
            nom = f"{prefixe}{i}.txt"
            with open(os.path.join(depot, nom), "w") as fh:
                fh.write(nom)
            _git(depot, "add", nom)
            _git(depot, "commit", "-q", "-m", f"{prefixe}{i}")
        return _git(depot, "rev-parse", "HEAD")

    def forker(self, nos, amont_apres):
        """Le fork part de l'amont, ajoute `nos` commits ; l'amont avance
        ensuite de `amont_apres`. Rend (base, pointe du fork)."""
        base = self.commits(self.amont, "u", 3)
        travail = os.path.join(self.dossier, "travail")
        _git(self.dossier, "clone", "-q", self.amont, travail)
        pointe = self.commits(travail, "f", nos)
        _git(self.dossier, "init", "-q", "--bare", self.fork)
        _git(travail, "push", "-q", self.fork, "HEAD:principale")
        self.commits(self.amont, "v", amont_apres)
        return base, pointe

    def cloner(self, *options):
        """Clone le fork comme git-repo : son remote porte le nom du
        manifeste. Rend le chemin du clone."""
        clone = os.path.join(self.dossier, "clone")
        _git(
            self.dossier,
            "clone",
            "-q",
            "-o",
            REMOTE_FORK,
            *options,
            f"file://{self.fork}",
            clone,
        )
        return clone

    def amont_declare(self, url=None, branche="principale"):
        return {
            "remote": "U",
            "nom": "amont",
            "url": url or f"file://{self.amont}",
            "branche": branche,
            "source": "declare",
            "remote_declare": True,
        }

    def base_amont(self, clone, sha, amont=None):
        return gel.base_amont(
            clone,
            sha,
            amont or self.amont_declare(),
            remote=REMOTE_FORK,
            ref="principale",
        )


class TestBaseAmont(DepotsTemporaires):
    def test_clone_complet(self):
        base, pointe = self.forker(nos=2, amont_apres=4)
        constat = self.base_amont(self.cloner(), pointe)
        self.assertEqual(
            constat,
            {
                "base": base,
                "motif": None,
                "nous": 2,
                "retard": 4,
                "profondeur": None,
            },
        )

    def test_clone_superficiel_approfondi_jusqu_a_la_base(self):
        """La base est hors de portée des premiers tours : la profondeur
        double jusqu'à elle, et le constat dit où elle s'est arrêtée."""
        base, pointe = self.forker(nos=5, amont_apres=5)
        clone = self.cloner("--depth", "1")
        self.assertTrue(repo_upgrade.est_superficiel(clone))
        with patch.object(gel, "PROFONDEUR_DEPART", 2), patch.object(
            gel, "PROFONDEUR_MAX", 16
        ):
            constat = self.base_amont(clone, pointe)
        self.assertEqual(constat["base"], base)
        self.assertIsNone(constat["motif"])
        self.assertEqual(constat["profondeur"], 8)
        self.assertEqual((constat["nous"], constat["retard"]), (5, 5))
        # Seul l'historique a changé : ni branche ni référence distante.
        self.assertEqual(_git(clone, "rev-parse", "HEAD"), pointe)
        self.assertEqual(
            _git(clone, "for-each-ref", "--format=%(refname)"),
            "refs/heads/principale\n"
            f"refs/remotes/{REMOTE_FORK}/HEAD\n"
            f"refs/remotes/{REMOTE_FORK}/principale",
        )

    def test_clone_superficiel_base_cachee_par_la_frontiere(self):
        """La pointe amont fusionne une branche partie d'un commit ancien.

        Tronqué, l'historique amont rejoint ce commit ancien par le second
        parent de la fusion, alors que la vraie base reste derrière la
        frontière de la ligne principale : la base de fusion calculée est
        l'ancien commit. Elle n'est retenue qu'une fois la frontière passée
        sous elle."""
        self.commits(self.amont, "c", 41)
        base = _git(self.amont, "rev-parse", "HEAD")
        travail = os.path.join(self.dossier, "travail")
        _git(self.dossier, "clone", "-q", self.amont, travail)
        pointe = self.commits(travail, "f", 5)
        _git(self.dossier, "init", "-q", "--bare", self.fork)
        _git(travail, "push", "-q", self.fork, "HEAD:principale")
        _git(self.amont, "checkout", "-q", "-b", "pr", "HEAD~30")
        self.commits(self.amont, "p", 2)
        _git(self.amont, "checkout", "-q", "principale")
        self.commits(self.amont, "d", 60)
        _git(self.amont, "merge", "-q", "--no-ff", "-m", "fusion", "pr")
        clone = self.cloner("--depth", "10")
        with patch.object(gel, "PROFONDEUR_DEPART", 2), patch.object(
            gel, "PROFONDEUR_MAX", 128
        ):
            constat = self.base_amont(clone, pointe)
        self.assertEqual(constat["base"], base)
        self.assertIsNone(constat["motif"])
        self.assertEqual(constat["profondeur"], 64)
        self.assertEqual(constat["nous"], 5)

    def test_clone_superficiel_sans_base_dans_le_plafond(self):
        _base, pointe = self.forker(nos=20, amont_apres=1)
        clone = self.cloner("--depth", "1")
        with patch.object(gel, "PROFONDEUR_DEPART", 2), patch.object(
            gel, "PROFONDEUR_MAX", 8
        ):
            constat = self.base_amont(clone, pointe)
        self.assertIsNone(constat["base"])
        self.assertEqual(constat["motif"], "shallow: no base within 8")

    def test_aucune_base_de_fusion(self):
        """Un fork reconstruit de zéro ne partage rien avec l'amont."""
        self.commits(self.amont, "u", 2)
        travail = os.path.join(self.dossier, "travail")
        _git(self.dossier, "init", "-q", travail)
        pointe = self.commits(travail, "f", 2)
        _git(self.dossier, "init", "-q", "--bare", self.fork)
        _git(travail, "push", "-q", self.fork, "HEAD:principale")
        constat = self.base_amont(self.cloner(), pointe)
        self.assertEqual(constat["motif"], "no merge base")
        self.assertIsNone(constat["base"])

    def test_base_ambigue(self):
        """Fusions croisées : deux bases de fusion, aucune n'est écrite."""
        self.commits(self.amont, "a", 1)
        _git(self.amont, "checkout", "-q", "-b", "b1")
        b1 = self.commits(self.amont, "b1_", 1)
        _git(self.amont, "checkout", "-q", "-b", "b2", "principale")
        self.commits(self.amont, "b2_", 1)
        _git(self.amont, "checkout", "-q", "b1")
        _git(self.amont, "merge", "-q", "--no-ff", "-m", "c1", "b2")
        c1 = _git(self.amont, "rev-parse", "HEAD")
        _git(self.amont, "checkout", "-q", "b2")
        _git(self.amont, "merge", "-q", "--no-ff", "-m", "c2", b1)
        _git(self.dossier, "init", "-q", "--bare", self.fork)
        _git(
            self.amont, "push", "-q", self.fork, f"{c1}:refs/heads/principale"
        )
        constat = self.base_amont(
            self.cloner(), c1, self.amont_declare(branche="b2")
        )
        self.assertEqual(constat["motif"], "ambiguous merge base")
        self.assertIsNone(constat["base"])

    def test_amont_injoignable(self):
        _base, pointe = self.forker(nos=1, amont_apres=1)
        absent = f"file://{os.path.join(self.dossier, 'absent')}"
        for options in ((), ("--depth", "1")):
            with self.subTest(options=options):
                clone = self.cloner(*options)
                constat = self.base_amont(
                    clone, pointe, self.amont_declare(url=absent)
                )
                self.assertEqual(constat["motif"], "upstream unreachable")
                shutil.rmtree(clone)

    def test_amont_non_declare_ou_sans_branche_sans_reseau(self):
        devine = dict(self.amont_declare(), source="convention")
        sans_branche = dict(self.amont_declare(), branche=None)
        inconnu = dict(self.amont_declare(), remote_declare=False, url="")
        with patch.object(
            repo_upgrade, "git", side_effect=AssertionError("réseau")
        ):
            for amont, motif in (
                (devine, "upstream not declared"),
                (inconnu, "upstream not declared"),
                (None, "upstream not declared"),
                (sans_branche, "no upstream branch"),
            ):
                with self.subTest(motif=motif):
                    constat = gel.base_amont("inutile", SHA_A, amont)
                    self.assertEqual(constat["motif"], motif)


class TestGelAmont(DepotsTemporaires):
    """Le gel complet, dans un checkout factice qui contient le clone."""

    CHEMIN = "odooX.0/addons/R_fork"

    def setUp(self):
        super().setUp()
        self.checkout = os.path.join(self.dossier, "checkout")
        os.makedirs(os.path.join(self.checkout, "manifest"))
        with open(os.path.join(self.checkout, ".odoo-version"), "w") as fh:
            fh.write("X.0")
        self.addCleanup(os.chdir, os.getcwd())
        extra = patch.object(fusion, "get_version_extra", return_value=None)
        extra.start()
        self.addCleanup(extra.stop)
        self.base, self.pointe = self.forker(nos=2, amont_apres=3)
        clone = self.cloner()
        cible = os.path.join(self.checkout, self.CHEMIN)
        os.makedirs(os.path.dirname(cible))
        os.rename(clone, cible)

    def manifeste(self, amont=None, attrs=""):
        """Écrit le manifeste de la version active ; `amont` est le dossier
        servi par le remote amont."""
        texte = (
            "<manifest>\n"
            f'  <remote name="{REMOTE_FORK}" fetch="file://{self.dossier}/"/>\n'
            f'  <remote name="U" fetch="file://{amont or self.dossier}/"/>\n'
            "  <project\n"
            '    name="fork.git"\n'
            '    revision="principale"\n'
            f"{attrs}"
            f'    path="{self.CHEMIN}"\n'
            f'    remote="{REMOTE_FORK}"\n'
            '    fork-upstream-remote="U"\n'
            '    fork-upstream-name="amont"\n'
            '    fork-upstream="principale"\n'
            "  />\n"
            "</manifest>\n"
        )
        with open(self.fichier(), "w") as fh:
            fh.write(texte)
        return texte

    def fichier(self):
        return os.path.join(
            self.checkout, "manifest", "git_manifest_odooX.0.xml"
        )

    def lire(self):
        with open(self.fichier()) as fh:
            return fh.read()

    def geler(self, *argv):
        with patch.object(gel, "new_path", self.checkout), patch(
            "builtins.print"
        ) as imprime:
            code = gel.main(list(argv))
        return code, "\n".join(
            " ".join(map(str, a.args)) for a in imprime.mock_calls
        )

    def test_upstream_ecrit_la_base_et_la_provenance(self):
        texte = self.manifeste()
        code, sortie = self.geler("--upstream")
        self.assertEqual(code, 0)
        self.assertEqual(
            self.lire(),
            texte.replace(
                '    revision="principale"\n',
                '    revision="principale"\n'
                f'    freeze-revision="{self.pointe}"\n',
            ).replace(
                '    fork-upstream="principale"\n',
                '    fork-upstream="principale"\n'
                f'    {BASE}="{self.base}"\n',
            ),
        )
        self.assertIn(
            f"  {self.CHEMIN}: {self.pointe[:12]} = upstream"
            f" {self.base[:12]} +2 ours, 3 behind upstream",
            sortie,
        )
        self.assertIn("Upstream: 1 bases found, 0 forks without base.", sortie)

    def test_amont_injoignable_ne_bloque_pas_le_gel(self):
        """Le commit est gelé ; la base périmée d'un ancien gel part."""
        attrs = f'    freeze-revision="{SHA_A}"\n    {BASE}="{SHA_B}"\n'
        self.manifeste(amont=os.path.join(self.dossier, "absent"), attrs=attrs)
        code, sortie = self.geler("--upstream")
        self.assertEqual(code, 0)
        texte = self.lire()
        self.assertIn(f'freeze-revision="{self.pointe}"', texte)
        self.assertNotIn(BASE, texte)
        self.assertIn("WARNING: no upstream base: 1", sortie)
        self.assertIn(
            f"  - fork.git+{self.CHEMIN}: upstream unreachable", sortie
        )

    def test_sans_upstream_aucun_reseau(self):
        """Sans --upstream, rien n'interroge l'amont : la base suit seule la
        règle du commit gelé, gardée s'il ne change pas."""
        attrs = f'    freeze-revision="{self.pointe}"\n    {BASE}="{SHA_B}"\n'
        texte = self.manifeste(attrs=attrs)
        interdit = AssertionError("réseau sans --upstream")
        with patch.object(
            repo_upgrade, "recuperer_amont", side_effect=interdit
        ), patch.object(repo_upgrade, "git", side_effect=interdit):
            code, sortie = self.geler()
            self.assertEqual(code, 0)
            self.assertEqual(self.lire(), texte)
            self.assertNotIn("Upstream", sortie)
            # Un commit gelé qui change emporte la base sans réseau.
            self.manifeste(
                attrs=f'    freeze-revision="{SHA_A}"\n    {BASE}="{SHA_B}"\n'
            )
            code, _ = self.geler()
        self.assertEqual(code, 0)
        self.assertIn(f'freeze-revision="{self.pointe}"', self.lire())
        self.assertNotIn(BASE, self.lire())


class TestNosCommitsGeles(DepotsTemporaires):
    """La plage « base..gel » de chaque fork, lue dans son clone sans
    réseau : le compte quand les deux commits y sont, la raison sinon."""

    def setUp(self):
        super().setUp()
        self.base, self.pointe = self.forker(nos=2, amont_apres=1)
        self.clone = self.cloner()

    def constat(self, chemin="clone", base=None, gel=None):
        return {
            "chemin": chemin,
            "base_gelee": self.base if base is None else base,
            "gel": self.pointe if gel is None else gel,
        }

    def test_le_compte_de_nos_commits(self):
        (ligne,) = repo_upgrade.nos_commits_geles(
            [self.constat()], self.dossier
        )
        self.assertEqual(ligne["nos"], 2)
        self.assertIsNone(ligne["motif"])
        self.assertEqual(ligne["dossier"], self.clone)
        self.assertEqual(
            (ligne["base"], ligne["gel"]), (self.base, self.pointe)
        )

    def test_seuls_les_forks_aux_deux_commits_entrent(self):
        sans_base = dict(self.constat(), base_gelee=None)
        sans_gel = dict(self.constat(), gel=None)
        lignes = repo_upgrade.nos_commits_geles(
            [sans_base, self.constat(), sans_gel], self.dossier
        )
        self.assertEqual([lg["nos"] for lg in lignes], [2])

    def test_un_clone_absent_ou_un_simple_dossier(self):
        os.makedirs(os.path.join(self.clone, "sous"))
        lignes = repo_upgrade.nos_commits_geles(
            [self.constat("absent"), self.constat("clone/sous")],
            self.dossier,
        )
        self.assertEqual(
            [lg["motif"] for lg in lignes], [repo_upgrade.t("not cloned")] * 2
        )
        self.assertEqual([lg["nos"] for lg in lignes], [None, None])

    def test_un_commit_absent_du_clone_n_est_pas_recupere(self):
        inconnu = "3" * 40
        with patch.object(
            repo_upgrade, "git", wraps=repo_upgrade.git
        ) as espion:
            base, gel = repo_upgrade.nos_commits_geles(
                [self.constat(base=inconnu), self.constat(gel=inconnu)],
                self.dossier,
            )
        self.assertEqual(
            base["motif"],
            repo_upgrade.t(
                "base absent from the clone: run the freeze with the"
                " upstream base"
            ),
        )
        self.assertEqual(
            gel["motif"],
            repo_upgrade.t(
                "frozen commit absent from the clone: synchronize the"
                " repositories"
            ),
        )
        self.assertIsNone(base["nos"])
        sous_commandes = {appel.args[0][0] for appel in espion.call_args_list}
        self.assertNotIn("fetch", sous_commandes)

    def test_un_clone_en_retard_sur_le_gel_se_synchronise(self):
        """Ni le commit gelé ni sa base dans le clone : le conseil est de
        synchroniser, pas de regeler un HEAD en retard."""
        (ligne,) = repo_upgrade.nos_commits_geles(
            [self.constat(base="3" * 40, gel="4" * 40)], self.dossier
        )
        self.assertEqual(
            ligne["motif"],
            repo_upgrade.t(
                "frozen commit absent from the clone: synchronize the"
                " repositories"
            ),
        )

    def test_un_historique_recoupe_ne_compte_pas_une_plage_tronquee(self):
        """Un fetch superficiel pose la frontière entre la base et le
        commit gelé : la base reste dans le magasin d'objets, mais
        « base..gel » ne compterait qu'une partie de nos commits."""
        _git(self.clone, "fetch", "-q", "--depth=1", REMOTE_FORK, "principale")
        self.assertEqual(
            _git(self.clone, "rev-parse", "--is-shallow-repository"), "true"
        )
        (ligne,) = repo_upgrade.nos_commits_geles(
            [self.constat()], self.dossier
        )
        self.assertIsNone(ligne["nos"])
        self.assertEqual(
            ligne["motif"],
            repo_upgrade.t(
                "history cut between the base and the frozen commit"
                " (shallow clone)"
            ),
        )


if __name__ == "__main__":
    unittest.main()
