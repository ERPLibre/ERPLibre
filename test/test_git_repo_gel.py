#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le gel des versions : un commit écrit à côté de la branche.

Chaque `<project>` d'un fichier source garde sa branche dans « revision »
et peut porter son commit dans « freeze-revision ». Ces tests vérifient
la réécriture TEXTUELLE des fichiers sources (commentaires et mise en forme
rendus à l'octet près), le choix de la révision par la fusion, le plan du
gel à partir de l'état des clones, et la lecture de cet état sur de vrais
dépôts git temporaires.

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

SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_C = "c" * 40

CLE_ALPHA = "alpha.git+odooX/addons/R_alpha"
CLE_BETA = "beta.git+odooX/addons/R_beta"

# Un attribut par ligne, la forme des fichiers de manifest/.
BLOC = """<?xml version="1.0" encoding="UTF-8" ?>
<manifest>
  <project
    name="alpha.git"
    path="odooX/addons/R_alpha"
    remote="R"
    revision="X_dev"
    groups="g"
  />
  <project name="beta.git" path="odooX/addons/R_beta" revision="X"/>
</manifest>
"""


class TestIsSha(unittest.TestCase):
    def test_commit_complet(self):
        self.assertTrue(mf.is_sha("0123456789abcdef" * 2 + "01234567"))

    def test_refuse_ce_qui_n_est_pas_un_commit_complet(self):
        for valeur in (
            None,
            "",
            "X_dev",
            "a" * 39,
            "a" * 41,
            "A" * 40,
            "g" * 40,
            "refs/heads/X",
        ):
            with self.subTest(valeur=valeur):
                self.assertFalse(mf.is_sha(valeur))


class TestManifestBranch(unittest.TestCase):
    def test_une_branche_se_rend_telle_quelle(self):
        self.assertEqual(mf.manifest_branch("X_dev", "Y", "Z"), "X_dev")

    def test_un_commit_rend_dest_branch_d_abord(self):
        self.assertEqual(mf.manifest_branch(SHA_A, "Y", "Z"), "Z")

    def test_un_commit_sans_dest_branch_rend_upstream(self):
        self.assertEqual(mf.manifest_branch(SHA_A, "Y"), "Y")

    def test_un_commit_sans_branche_connue_rend_none(self):
        self.assertIsNone(mf.manifest_branch(SHA_A))
        self.assertIsNone(mf.manifest_branch(SHA_A, "", ""))


class TestRewrite(unittest.TestCase):
    def test_bloc_un_attribut_par_ligne(self):
        """L'attribut s'insère juste après « revision », sur sa propre
        ligne, avec la même indentation."""
        neuf, cles = mf.rewrite(BLOC, freeze={CLE_ALPHA: SHA_A})
        self.assertEqual(cles, [CLE_ALPHA])
        self.assertIn(
            '    revision="X_dev"\n'
            f'    freeze-revision="{SHA_A}"\n'
            '    groups="g"\n',
            neuf,
        )
        # Le reste du fichier, dont l'autre projet, est rendu tel quel.
        self.assertEqual(
            neuf.replace(f'\n    freeze-revision="{SHA_A}"', ""), BLOC
        )

    def test_balise_d_une_ligne(self):
        neuf, cles = mf.rewrite(BLOC, freeze={CLE_BETA: SHA_B})
        self.assertEqual(cles, [CLE_BETA])
        self.assertIn(
            '<project name="beta.git" path="odooX/addons/R_beta"'
            f' revision="X" freeze-revision="{SHA_B}"/>',
            neuf,
        )

    def test_mise_a_jour_d_un_gel_existant(self):
        """Un second gel remplace le commit en place, sans doubler
        l'attribut ni déplacer la ligne."""
        une, _ = mf.rewrite(BLOC, freeze={CLE_ALPHA: SHA_A, CLE_BETA: SHA_B})
        deux, cles = mf.rewrite(une, freeze={CLE_ALPHA: SHA_C})
        self.assertEqual(cles, [CLE_ALPHA])
        self.assertEqual(deux, une.replace(SHA_A, SHA_C))
        self.assertEqual(deux.count("freeze-revision"), 2)

    def test_regeler_au_meme_commit_ne_change_rien(self):
        une, _ = mf.rewrite(BLOC, freeze={CLE_ALPHA: SHA_A})
        deux, cles = mf.rewrite(une, freeze={CLE_ALPHA: SHA_A})
        self.assertEqual(cles, [])
        self.assertEqual(deux, une)

    def test_degel_rend_le_fichier_a_l_octet_pres(self):
        gele, _ = mf.rewrite(BLOC, freeze={CLE_ALPHA: SHA_A, CLE_BETA: SHA_B})
        self.assertNotEqual(gele, BLOC)
        degele, cles = mf.rewrite(gele, unfreeze=True)
        self.assertEqual(degele, BLOC)
        self.assertEqual(sorted(cles), sorted([CLE_ALPHA, CLE_BETA]))

    def test_degel_d_un_fichier_sans_gel_ne_change_rien(self):
        texte, cles = mf.rewrite(BLOC, unfreeze=True)
        self.assertEqual(texte, BLOC)
        self.assertEqual(cles, [])

    def test_un_projet_commente_n_est_pas_touche(self):
        """Un `<project>` commenté a la même clé qu'un projet actif : seul
        le projet actif reçoit le commit."""
        texte = (
            "<manifest>\n"
            "  <!--\n"
            '  <project name="alpha.git" path="odooX/addons/R_alpha"'
            ' revision="X_old"/>\n'
            "  -->\n"
            '  <project name="alpha.git" path="odooX/addons/R_alpha"'
            ' revision="X_dev"/>\n'
            "</manifest>\n"
        )
        neuf, cles = mf.rewrite(texte, freeze={CLE_ALPHA: SHA_A})
        self.assertEqual(cles, [CLE_ALPHA])
        self.assertIn('revision="X_old"/>', neuf)
        self.assertIn(f'revision="X_dev" freeze-revision="{SHA_A}"/>', neuf)
        self.assertEqual(neuf.count("freeze-revision"), 1)
        self.assertEqual(len(list(mf.iter_projects(texte))), 1)

    def test_un_projet_absent_de_la_table_n_est_pas_touche(self):
        neuf, cles = mf.rewrite(
            BLOC, freeze={"inconnu.git+odooX/addons/R_inconnu": SHA_C}
        )
        self.assertEqual(cles, [])
        self.assertEqual(neuf, BLOC)

    def test_le_chemin_fait_partie_de_la_cle(self):
        """Le même dépôt cloné à un autre chemin est un autre projet."""
        neuf, cles = mf.rewrite(
            BLOC, freeze={"alpha.git+odooY/addons/R_alpha": SHA_C}
        )
        self.assertEqual(cles, [])
        self.assertEqual(neuf, BLOC)

    def test_balise_sans_revision_s_ancre_sur_le_chemin(self):
        texte = (
            "<manifest>\n"
            "  <project\n"
            '    name="alpha.git"\n'
            '    path="odooX/addons/R_alpha"\n'
            '    remote="R"\n'
            "  />\n"
            "</manifest>\n"
        )
        neuf, cles = mf.rewrite(texte, freeze={CLE_ALPHA: SHA_A})
        self.assertEqual(cles, [CLE_ALPHA])
        self.assertIn(
            '    path="odooX/addons/R_alpha"\n'
            f'    freeze-revision="{SHA_A}"\n'
            '    remote="R"\n',
            neuf,
        )
        self.assertEqual(mf.rewrite(neuf, unfreeze=True)[0], texte)

    def test_balise_non_auto_fermante(self):
        """`<project ...></project>` et ses enfants : seule la balise
        ouvrante change."""
        texte = (
            "<manifest>\n"
            '  <project name="alpha.git" path="odooX/addons/R_alpha"'
            ' revision="X">\n'
            '    <copyfile src="a" dest="b"/>\n'
            "  </project>\n"
            "</manifest>\n"
        )
        neuf, cles = mf.rewrite(texte, freeze={CLE_ALPHA: SHA_A})
        self.assertEqual(cles, [CLE_ALPHA])
        self.assertIn(f'revision="X" freeze-revision="{SHA_A}">\n', neuf)
        self.assertIn('    <copyfile src="a" dest="b"/>\n  </project>', neuf)
        self.assertEqual(mf.rewrite(neuf, unfreeze=True)[0], texte)

    def test_iter_projects_lit_les_attributs(self):
        gele, _ = mf.rewrite(BLOC, freeze={CLE_ALPHA: SHA_A})
        attrs = [a for _, _, a in mf.iter_projects(gele)]
        self.assertEqual(len(attrs), 2)
        self.assertEqual(attrs[0][mf.FREEZE_ATTR], SHA_A)
        self.assertEqual(attrs[0]["revision"], "X_dev")
        self.assertNotIn(mf.FREEZE_ATTR, attrs[1])


BASE = mf.FORK_UPSTREAM_FREEZE_ATTR

# Un fork : ses attributs d'amont, dans l'ordre des fichiers de manifest/.
FORK = """<manifest>
  <project
    name="alpha.git"
    revision="X_dev"
    path="odooX/addons/R_alpha"
    remote="R_origin_U"
    fork-upstream-remote="U"
    fork-upstream="X"
    groups="g"
  />
  <project name="beta.git" path="odooX/addons/R_beta" revision="X"\
 remote="R_origin_U" fork-upstream-remote="U" fork-upstream-name="b.git"/>
</manifest>
"""


class TestRewriteBaseAmont(unittest.TestCase):
    """« fork-upstream-freeze-revision » : la base amont du commit gelé."""

    def test_pose_apres_fork_upstream(self):
        neuf, cles = mf.rewrite(
            FORK, freeze={CLE_ALPHA: SHA_A}, upstream={CLE_ALPHA: SHA_B}
        )
        self.assertEqual(cles, [CLE_ALPHA])
        attendu = FORK.replace(
            '    revision="X_dev"\n',
            f'    revision="X_dev"\n    freeze-revision="{SHA_A}"\n',
        ).replace(
            '    fork-upstream="X"\n',
            f'    fork-upstream="X"\n    {BASE}="{SHA_B}"\n',
        )
        self.assertEqual(neuf, attendu)

    def test_ancres_successives(self):
        """Sans « fork-upstream », la base suit « fork-upstream-name »,
        puis « fork-upstream-remote », puis « freeze-revision »."""
        cas = (
            (
                'fork-upstream-remote="U" fork-upstream-name="b.git"',
                f'fork-upstream-name="b.git" {BASE}="{SHA_B}"',
            ),
            (
                'fork-upstream-remote="U"',
                f'fork-upstream-remote="U" {BASE}="{SHA_B}"',
            ),
            (
                "",
                f'revision="X" freeze-revision="{SHA_A}" {BASE}="{SHA_B}"',
            ),
        )
        for attrs, attendu in cas:
            with self.subTest(attrs=attrs):
                texte = (
                    '<project name="beta.git" path="odooX/addons/R_beta"'
                    f' revision="X" {attrs}/>'
                )
                neuf, _ = mf.rewrite(
                    texte,
                    freeze={CLE_BETA: SHA_A},
                    upstream={CLE_BETA: SHA_B},
                )
                self.assertIn(attendu, neuf)
                self.assertEqual(neuf.count(BASE), 1)

    def gele(self):
        texte, _ = mf.rewrite(
            FORK,
            freeze={CLE_ALPHA: SHA_A, CLE_BETA: SHA_A},
            upstream={CLE_ALPHA: SHA_B, CLE_BETA: SHA_B},
        )
        return texte

    def test_mise_a_jour_en_place(self):
        une = self.gele()
        deux, cles = mf.rewrite(
            une, freeze={CLE_ALPHA: SHA_A}, upstream={CLE_ALPHA: SHA_C}
        )
        self.assertEqual(cles, [CLE_ALPHA])
        self.assertEqual(
            deux,
            une.replace(f'    {BASE}="{SHA_B}"', f'    {BASE}="{SHA_C}"'),
        )

    def test_meme_commit_sans_base_demandee_garde_la_base(self):
        une = self.gele()
        deux, cles = mf.rewrite(une, freeze={CLE_ALPHA: SHA_A})
        self.assertEqual((deux, cles), (une, []))

    def test_commit_change_sans_base_retire_l_ancienne(self):
        """La base d'un ancien commit ne survit pas à un nouveau gel."""
        une = self.gele()
        deux, cles = mf.rewrite(une, freeze={CLE_ALPHA: SHA_C})
        self.assertEqual(cles, [CLE_ALPHA])
        self.assertEqual(
            deux,
            une.replace(
                f'    freeze-revision="{SHA_A}"',
                f'    freeze-revision="{SHA_C}"',
            ).replace(f'\n    {BASE}="{SHA_B}"', ""),
        )

    def test_none_retire_la_base(self):
        une = self.gele()
        deux, cles = mf.rewrite(
            une, freeze={CLE_ALPHA: SHA_A}, upstream={CLE_ALPHA: None}
        )
        self.assertEqual(cles, [CLE_ALPHA])
        self.assertEqual(deux, une.replace(f'\n    {BASE}="{SHA_B}"', ""))

    def test_degel_retire_les_deux_attributs_a_l_octet_pres(self):
        degele, cles = mf.rewrite(self.gele(), unfreeze=True)
        self.assertEqual(degele, FORK)
        self.assertEqual(sorted(cles), sorted([CLE_ALPHA, CLE_BETA]))

    def test_le_nom_de_l_un_n_est_pas_pris_pour_l_autre(self):
        """« freeze-revision » est un suffixe de
        « fork-upstream-freeze-revision » : poser ou retirer l'un ne
        touche jamais l'autre."""
        seule_base = (
            '<project name="beta.git" path="odooX/addons/R_beta"'
            f' revision="X" {BASE}="{SHA_B}"/>'
        )
        # Poser le gel l'insère après « revision » sans réécrire la base.
        self.assertEqual(
            mf._set_attr(seule_base, mf.FREEZE_ATTR, SHA_C),
            seule_base.replace(
                'revision="X" ', f'revision="X" freeze-revision="{SHA_C}" '
            ),
        )
        self.assertEqual(mf._drop_attr(seule_base, mf.FREEZE_ATTR), seule_base)
        # La base ne passe pas pour un ancien gel au même commit : un gel
        # neuf la retire.
        neuf, _ = mf.rewrite(seule_base, freeze={CLE_BETA: SHA_B})
        self.assertEqual(
            neuf,
            '<project name="beta.git" path="odooX/addons/R_beta"'
            f' revision="X" freeze-revision="{SHA_B}"/>',
        )
        gele = self.gele()
        sans_gel = mf._drop_attr(gele, mf.FREEZE_ATTR)
        self.assertNotIn(" freeze-revision", sans_gel)
        self.assertEqual(sans_gel.count(BASE), 2)
        sans_base = mf._drop_attr(gele, BASE)
        self.assertNotIn(BASE, sans_base)
        self.assertEqual(sans_base.count(mf.FREEZE_ATTR), 2)


class TestApplyFreeze(unittest.TestCase):
    def projets(self):
        return {
            CLE_ALPHA: {"@revision": "X_dev", f"@{mf.FREEZE_ATTR}": SHA_A},
            CLE_BETA: {
                "@revision": "X",
                "@upstream": "X_amont",
                f"@{mf.FREEZE_ATTR}": SHA_B,
            },
            "gamma.git+odooX/addons/R_gamma": {"@revision": "X"},
        }

    def test_gel_pose_le_commit_et_garde_la_branche(self):
        projets = self.projets()
        geles, manquants = mf.apply_freeze(projets, True)
        self.assertEqual(sorted(geles), sorted([CLE_ALPHA, CLE_BETA]))
        self.assertEqual(manquants, ["gamma.git+odooX/addons/R_gamma"])
        self.assertEqual(
            projets[CLE_ALPHA],
            {
                "@revision": SHA_A,
                "@upstream": "X_dev",
                "@dest-branch": "X_dev",
            },
        )

    def test_un_upstream_existant_n_est_pas_ecrase(self):
        projets = self.projets()
        mf.apply_freeze(projets, True)
        self.assertEqual(projets[CLE_BETA]["@revision"], SHA_B)
        self.assertEqual(projets[CLE_BETA]["@upstream"], "X_amont")
        self.assertEqual(projets[CLE_BETA]["@dest-branch"], "X")

    def test_un_projet_sans_commit_suit_sa_branche(self):
        projets = self.projets()
        mf.apply_freeze(projets, True)
        self.assertEqual(
            projets["gamma.git+odooX/addons/R_gamma"], {"@revision": "X"}
        )

    def test_une_revision_deja_commit_ne_devient_pas_une_branche(self):
        projets = {
            CLE_ALPHA: {"@revision": SHA_C, f"@{mf.FREEZE_ATTR}": SHA_A}
        }
        mf.apply_freeze(projets, True)
        self.assertEqual(projets[CLE_ALPHA], {"@revision": SHA_A})

    def test_une_revision_deja_commit_ne_manque_pas(self):
        """Une source qui épingle déjà un commit dans « revision » n'a pas
        de « freeze-revision » à fournir."""
        projets = {CLE_ALPHA: {"@revision": SHA_C}}
        geles, manquants = mf.apply_freeze(projets, True)
        self.assertEqual((geles, manquants), ([], []))
        self.assertEqual(projets[CLE_ALPHA], {"@revision": SHA_C})

    def test_sans_gel_les_branches_restent(self):
        projets = self.projets()
        geles, manquants = mf.apply_freeze(projets, False)
        self.assertEqual((geles, manquants), ([], []))
        self.assertEqual(projets[CLE_ALPHA], {"@revision": "X_dev"})
        self.assertEqual(
            projets[CLE_BETA], {"@revision": "X", "@upstream": "X_amont"}
        )

    def test_l_attribut_est_toujours_retire(self):
        """git-repo ne connaît pas « freeze-revision » : il ne doit jamais
        atteindre le manifeste local, gel ou non."""
        for freeze in (True, False):
            with self.subTest(freeze=freeze):
                projets = self.projets()
                mf.apply_freeze(projets, freeze)
                for valeur in projets.values():
                    self.assertNotIn(f"@{mf.FREEZE_ATTR}", valeur)

    def test_la_base_amont_est_toujours_retiree(self):
        """La source de vérité de la base reste manifest/ : le manifeste
        local ne la porte jamais."""
        for freeze in (True, False):
            with self.subTest(freeze=freeze):
                projets = self.projets()
                projets[CLE_ALPHA][f"@{BASE}"] = SHA_C
                mf.apply_freeze(projets, freeze)
                self.assertNotIn(f"@{BASE}", projets[CLE_ALPHA])


class TestPlanFreeze(unittest.TestCase):
    """Le plan du gel, avec un état de clone injecté à la place de git."""

    ETATS = {
        "odooX/addons/R_alpha": (SHA_A, None, False),
        "odooX/addons/R_beta": (SHA_B, None, True),
        "odooX/addons/R_gamma": (None, "not cloned", False),
        "odooX/addons/R_delta": (SHA_C, "commit on no remote branch", False),
    }

    def definitions(self):
        defs = {}
        for nom, fichier in (
            ("alpha", "m/un.xml"),
            ("beta", "m/deux.xml"),
            ("gamma", "m/un.xml"),
            ("delta", "m/un.xml"),
        ):
            path = f"odooX/addons/R_{nom}"
            defs[mf.project_key(f"{nom}.git", path)] = [
                (fichier, {"name": f"{nom}.git", "path": path})
            ]
        path = "odooX/addons/R_double"
        defs[mf.project_key("double.git", path)] = [
            ("m/un.xml", {"name": "double.git", "path": path}),
            ("m/deux.xml", {"name": "double.git", "path": path}),
        ]
        return defs

    def plan(self):
        self.inspectes = []

        def inspect(path, _amont=None):
            self.inspectes.append(path)
            return self.ETATS[path]

        return gel.plan_freeze(self.definitions(), inspect=inspect, workers=2)

    def test_les_clones_valides_sont_geles_dans_leur_fichier(self):
        par_fichier, _, _ = self.plan()
        self.assertEqual(
            par_fichier,
            {"m/un.xml": {CLE_ALPHA: SHA_A}, "m/deux.xml": {CLE_BETA: SHA_B}},
        )

    def test_les_refus_et_leur_motif(self):
        _, refus, _ = self.plan()
        motifs = dict(refus)
        self.assertEqual(
            motifs["gamma.git+odooX/addons/R_gamma"], "not cloned"
        )
        self.assertEqual(
            motifs["delta.git+odooX/addons/R_delta"],
            "commit on no remote branch",
        )
        self.assertTrue(
            motifs["double.git+odooX/addons/R_double"].startswith(
                "defined in several sources"
            )
        )
        self.assertEqual(len(refus), 3)

    def test_un_projet_en_double_n_est_pas_inspecte(self):
        self.plan()
        self.assertNotIn("odooX/addons/R_double", self.inspectes)
        self.assertEqual(len(self.inspectes), 4)

    def test_inspect_recoit_le_remote_amont_nomme(self):
        """Seul « fork-upstream-remote » est transmis, et jamais quand il
        porte le nom du remote du fork : ses refs prouveraient tout."""
        vus = {}
        defs = {
            "a+x/a": [("m/un.xml", {"path": "x/a", "remote": "R_origin_U"})],
            "b+x/b": [
                (
                    "m/un.xml",
                    {
                        "path": "x/b",
                        "remote": "R_origin_U",
                        "fork-upstream-remote": "U",
                    },
                )
            ],
            "c+x/c": [
                (
                    "m/un.xml",
                    {
                        "path": "x/c",
                        "remote": "U",
                        "fork-upstream-remote": "U",
                    },
                )
            ],
        }

        def inspect(path, amont=None):
            vus[path] = amont
            return (SHA_A, None, False)

        gel.plan_freeze(defs, inspect=inspect, workers=1)
        self.assertEqual(vus, {"x/a": None, "x/b": "U", "x/c": None})

    def test_un_clone_modifie_est_gele_et_signale(self):
        par_fichier, _, sales = self.plan()
        self.assertEqual(sales, [CLE_BETA])
        self.assertIn(CLE_BETA, par_fichier["m/deux.xml"])

    def test_hors_des_fichiers_ecrits_un_projet_est_ignore(self):
        par_fichier, refus, _ = gel.plan_freeze(
            self.definitions(),
            inspect=lambda path, _amont=None: self.ETATS[path],
            workers=2,
            ecrits=["m/deux.xml"],
        )
        self.assertEqual(par_fichier, {"m/deux.xml": {CLE_BETA: SHA_B}})
        # Le double, défini aussi dans m/un.xml, reste refusé ; les projets
        # de m/un.xml seul ne sont ni gelés ni listés.
        self.assertEqual(
            [c for c, _ in refus], ["double.git+odooX/addons/R_double"]
        )


class TestReadWriteSources(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dossier, True)
        self.un = os.path.join(self.dossier, "un.xml")
        self.deux = os.path.join(self.dossier, "deux.xml")
        with open(self.un, "w") as fh:
            fh.write(BLOC)
        with open(self.deux, "w") as fh:
            fh.write(
                "<manifest>\n"
                '  <project name="beta.git" path="odooX/addons/R_beta"'
                ' revision="Y"/>\n'
                "</manifest>\n"
            )

    def lire(self, fichier):
        with open(fichier) as fh:
            return fh.read()

    def test_read_sources_liste_chaque_definition(self):
        defs = gel.read_sources([self.un, self.deux])
        self.assertEqual(len(defs[CLE_ALPHA]), 1)
        self.assertEqual([f for f, _ in defs[CLE_BETA]], [self.un, self.deux])

    def test_dry_run_n_ecrit_rien(self):
        changes = gel.write_sources(
            {self.un: {CLE_ALPHA: SHA_A}}, dry_run=True
        )
        self.assertEqual(changes, {self.un: [CLE_ALPHA]})
        self.assertEqual(self.lire(self.un), BLOC)

    def test_ecriture_puis_degel(self):
        gel.write_sources({self.un: {CLE_ALPHA: SHA_A, CLE_BETA: SHA_B}})
        self.assertEqual(self.lire(self.un).count(mf.FREEZE_ATTR), 2)
        changes = gel.write_sources(
            {}, unfreeze=True, sources=[self.un, self.deux]
        )
        self.assertEqual(list(changes), [self.un])
        self.assertEqual(self.lire(self.un), BLOC)

    def test_degel_dry_run_n_ecrit_rien(self):
        gel.write_sources({self.un: {CLE_ALPHA: SHA_A}})
        gele = self.lire(self.un)
        changes = gel.write_sources(
            {}, unfreeze=True, dry_run=True, sources=[self.un]
        )
        self.assertEqual(changes, {self.un: [CLE_ALPHA]})
        self.assertEqual(self.lire(self.un), gele)


class TestGetConfig(unittest.TestCase):
    def test_fusion_freeze(self):
        self.assertTrue(fusion.get_config(["--freeze"]).freeze)
        self.assertFalse(fusion.get_config([]).freeze)

    def test_gel_options(self):
        config = gel.get_config(
            ["--unfreeze", "--dry-run", "--source", "a", "--source", "b"]
        )
        self.assertTrue(config.unfreeze)
        self.assertTrue(config.dry_run)
        self.assertEqual(config.source, ["a", "b"])
        self.assertIsNone(gel.get_config([]).source)


class TestDefaultInputPaths(unittest.TestCase):
    """L'ordre des fichiers sources, lu dans un checkout factice."""

    def setUp(self):
        self.dossier = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dossier, True)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.dossier)
        for dossier in ("conf", "manifest", "private", ".repo"):
            os.mkdir(dossier)
        with open(".odoo-version", "w") as fh:
            fh.write("X.0")
        for nom in (
            "git_manifest_odooX.0.xml",
            "git_manifest_odooX.0_dev.xml",
            "commun.xml",
            "prive.xml",
        ):
            open(os.path.join("manifest", nom), "w").close()
        self.csv(
            fusion.DEFAULT_PATH_MANIFEST_ODOO_CONF, ["manifest/commun.xml"]
        )
        self.csv(fusion.DEFAULT_PATH_MANIFEST_CONF, ["manifest/commun.xml"])
        self.csv(
            fusion.DEFAULT_PATH_MANIFEST_PRIVATE_CONF,
            ["manifest/git_manifest_odooX.0.xml", "manifest/prive.xml"],
        )
        # La version active est aussi une version installée.
        with open(fusion.DEFAULT_PATH_INSTALLED_ODOO_VERSION, "w") as fh:
            fh.write("odooX.0\n")
        extra = patch.object(fusion, "get_version_extra", return_value=None)
        extra.start()
        self.addCleanup(extra.stop)

    def csv(self, chemin, fichiers):
        with open(chemin, "w") as fh:
            fh.write("filepath\n" + "".join(f"{f}\n" for f in fichiers))

    def test_doublons_gardes_a_leur_premiere_place(self):
        attendu = [
            "manifest/commun.xml",
            "manifest/git_manifest_odooX.0.xml",
            "manifest/git_manifest_odooX.0_dev.xml",
            "manifest/prive.xml",
        ]
        self.assertEqual(fusion.default_input_paths(), attendu)

    def test_ordre_stable_d_un_appel_a_l_autre(self):
        premier = fusion.default_input_paths()
        for _ in range(5):
            self.assertEqual(fusion.default_input_paths(), premier)

    def test_extra_ajoute_apres_les_versions(self):
        open(
            os.path.join("manifest", "git_manifest_extra_odooX.0.xml"), "w"
        ).close()
        with patch.object(fusion, "get_version_extra", return_value=["e"]):
            chemins = fusion.default_input_paths()
        self.assertEqual(
            chemins.index("manifest/git_manifest_extra_odooX.0.xml"),
            chemins.index("manifest/git_manifest_odooX.0_dev.xml") + 1,
        )

    def test_freeze_sources_la_version_active_seule(self):
        open(
            os.path.join("manifest", "git_manifest_extra_odooX.0.xml"), "w"
        ).close()
        open(os.path.join("manifest", "git_manifest_odooY.0.xml"), "w").close()
        self.assertEqual(
            gel.freeze_sources(),
            [
                "manifest/git_manifest_odooX.0.xml",
                "manifest/git_manifest_odooX.0_dev.xml",
                "manifest/git_manifest_extra_odooX.0.xml",
            ],
        )
        self.assertEqual(
            gel.freeze_sources("Y.0"), ["manifest/git_manifest_odooY.0.xml"]
        )

    def test_freeze_sources_sans_version_active(self):
        os.remove(".odoo-version")
        self.assertEqual(gel.freeze_sources(), [])

    PROJET = (
        '  <project name="{n}.git" path="odooX.0/addons/{n}"'
        ' revision="X.0"{gel}/>\n'
    )

    def ecrire(self, fichier, *projets):
        """Écrit `manifest/<fichier>` ; `projets` : (nom, sha ou None)."""
        lignes = "".join(
            self.PROJET.format(
                n=nom, gel=f' {mf.FREEZE_ATTR}="{sha}"' if sha else ""
            )
            for nom, sha in projets
        )
        with open(os.path.join("manifest", fichier), "w") as fh:
            fh.write(f"<manifest>\n{lignes}</manifest>\n")

    def lire(self, fichier):
        with open(os.path.join("manifest", fichier)) as fh:
            return fh.read()

    def geler(self, *argv):
        """Lance le gel dans le checkout factice. Rend (code, sortie)."""
        plan = gel.plan_freeze

        def plan_factice(definitions, **kw):
            # `inspect` est lié à la définition de plan_freeze : patcher
            # inspect_clone ne l'atteint pas.
            return plan(
                definitions,
                inspect=lambda path, _amont=None: (SHA_A, None, False),
                **kw,
            )

        with patch.object(gel, "new_path", self.dossier), patch.object(
            gel, "plan_freeze", side_effect=plan_factice
        ), patch("builtins.print") as imprime:
            code = gel.main(list(argv))
        return code, "\n".join(
            " ".join(map(str, a.args)) for a in imprime.mock_calls
        )

    def test_le_gel_n_ecrit_que_la_version_active(self):
        self.ecrire("git_manifest_odooX.0.xml", ("un", None))
        self.ecrire("commun.xml", ("deux", None))
        code, _ = self.geler()
        self.assertEqual(code, 0)
        self.assertIn(
            f'{mf.FREEZE_ATTR}="{SHA_A}"',
            self.lire("git_manifest_odooX.0.xml"),
        )
        self.assertNotIn(mf.FREEZE_ATTR, self.lire("commun.xml"))

    def test_un_doublon_dans_un_autre_fichier_fusionne_est_refuse(self):
        self.ecrire("git_manifest_odooX.0.xml", ("un", None))
        self.ecrire("commun.xml", ("un", None))
        for argv in ((), ("--source", "manifest/git_manifest_odooX.0.xml")):
            code, sortie = self.geler(*argv)
            self.assertEqual(code, 1, argv)
            self.assertIn("defined in several sources", sortie)
            self.assertNotIn(
                mf.FREEZE_ATTR, self.lire("git_manifest_odooX.0.xml")
            )

    def test_source_hors_de_la_version_active_refusee(self):
        self.ecrire("git_manifest_odooX.0.xml", ("un", None))
        self.ecrire("commun.xml", ("deux", None))
        code, sortie = self.geler("--source", "manifest/commun.xml")
        self.assertEqual(code, 2)
        self.assertIn("not a manifest of the active Odoo version", sortie)
        self.assertNotIn(mf.FREEZE_ATTR, self.lire("commun.xml"))

    def test_avertissement_de_la_fusion_seuls_les_fichiers_geles(self):
        self.ecrire("git_manifest_odooX.0.xml", ("un", None))
        cle_un = mf.project_key("un.git", "odooX.0/addons/un")
        cle_deux = mf.project_key("deux.git", "odooX.0/addons/deux")
        with patch("builtins.print") as imprime:
            fusion.print_missing_freeze([cle_un, cle_deux])
        lignes = [" ".join(map(str, a.args)) for a in imprime.mock_calls]
        self.assertEqual(
            lignes,
            [
                f"WARNING: 1 projects have no {mf.FREEZE_ATTR} and follow"
                " their branch:",
                f"  - {cle_un}",
                "1 projects outside the frozen files follow their branch.",
            ],
        )

    def test_la_fusion_ignore_un_gel_hors_de_la_version_active(self):
        self.ecrire("commun.xml", ("deux", SHA_B))
        self.ecrire("git_manifest_odooX.0.xml", ("un", SHA_A))
        sortie = os.path.join(self.dossier, "local.xml")
        argv = [
            "git_merge_repo_manifest.py",
            "--input",
            "manifest/commun.xml;manifest/git_manifest_odooX.0.xml",
            "--output",
            sortie,
            "--freeze",
        ]
        with patch("sys.argv", argv), patch("builtins.print") as imprime:
            fusion.main()
        texte = " ".join(
            " ".join(map(str, a.args)) for a in imprime.mock_calls
        )
        with open(sortie) as fh:
            local = fh.read()
        self.assertIn(f'revision="{SHA_A}"', local)
        self.assertNotIn(SHA_B, local)
        self.assertIn("are ignored", texte)
        self.assertIn(mf.project_key("deux.git", "odooX.0/addons/deux"), texte)

    def test_strip_freeze(self):
        projets = {
            "a": {"@revision": "X", f"@{mf.FREEZE_ATTR}": SHA_A},
            "b": {"@revision": "X"},
        }
        self.assertEqual(fusion.strip_freeze(projets), ["a"])
        self.assertNotIn(f"@{mf.FREEZE_ATTR}", projets["a"])

    def test_strip_freeze_retire_la_base_amont(self):
        projets = {
            "a": {
                "@revision": "X",
                f"@{mf.FREEZE_ATTR}": SHA_A,
                f"@{BASE}": SHA_B,
            },
            "b": {"@revision": "X", f"@{BASE}": SHA_B},
        }
        self.assertEqual(fusion.strip_freeze(projets), ["a", "b"])
        for valeur in projets.values():
            self.assertEqual(valeur, {"@revision": "X"})

    def fusionner(self, *options):
        """Fusionne commun.xml puis la version active. Rend le local."""
        sortie = os.path.join(self.dossier, "local.xml")
        argv = [
            "git_merge_repo_manifest.py",
            "--input",
            "manifest/commun.xml;manifest/git_manifest_odooX.0.xml",
            "--output",
            sortie,
            *options,
        ]
        with patch("sys.argv", argv), patch("builtins.print"):
            fusion.main()
        with open(sortie) as fh:
            return fh.read()

    def test_la_fusion_n_ecrit_jamais_la_base_amont(self):
        """Une redéfinition reprend le gel et la base du fichier qui
        l'emporte ; ni l'une ni l'autre n'atteint le manifeste local."""
        self.ecrire("commun.xml", ("un", SHA_B))
        self.ecrire("git_manifest_odooX.0.xml", ("un", SHA_A))
        for nom in ("commun.xml", "git_manifest_odooX.0.xml"):
            texte = self.lire(nom).replace("/>", f' {BASE}="{SHA_C}"/>')
            with open(os.path.join("manifest", nom), "w") as fh:
                fh.write(texte)
        for options in (
            (),
            ("--freeze",),
            ("--freeze", "--att_revision_only"),
        ):
            with self.subTest(options=options):
                local = self.fusionner(*options)
                self.assertNotIn(BASE, local)
                self.assertNotIn(SHA_C, local)
                self.assertNotIn(SHA_B, local)
                if options:
                    self.assertIn(f'revision="{SHA_A}"', local)

    def test_default_sources_ne_garde_que_le_xml(self):
        open(os.path.join("private", "notes.txt"), "w").close()
        self.csv(
            fusion.DEFAULT_PATH_MANIFEST_PRIVATE_CONF, ["private/notes.txt"]
        )
        self.assertNotIn("private/notes.txt", gel.default_sources())
        self.assertIn("private/notes.txt", fusion.default_input_paths())


def _git(cwd, *args):
    """Lance git sans dépendre de la configuration de l'hôte."""
    subprocess.run(
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
    )


class TestInspectClone(unittest.TestCase):
    """L'état d'un vrai clone : un distant nu, un clone, des commits."""

    def setUp(self):
        self.dossier = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dossier, True)
        # git ne remonte pas au-dessus du dossier temporaire : un dossier
        # qui n'est pas un clone ne doit pas trouver un dépôt parent.
        plafond = patch.dict(
            os.environ, {"GIT_CEILING_DIRECTORIES": self.dossier}
        )
        plafond.start()
        self.addCleanup(plafond.stop)
        self.nu = os.path.join(self.dossier, "distant.git")
        self.clone = os.path.join(self.dossier, "clone")
        _git(self.dossier, "init", "-q", "--bare", self.nu)
        _git(self.dossier, "init", "-q", self.clone)
        _git(self.clone, "remote", "add", "origin", self.nu)
        self.fichier = os.path.join(self.clone, "a.txt")
        self.commit("un")
        _git(self.clone, "push", "-q", "origin", "HEAD:principale")
        _git(self.clone, "fetch", "-q", "origin")

    def commit(self, contenu):
        with open(self.fichier, "w") as fh:
            fh.write(contenu)
        _git(self.clone, "add", "a.txt")
        _git(self.clone, "commit", "-q", "-m", contenu)

    def head(self):
        return subprocess.run(
            ["git", "-C", self.clone, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    def test_commit_pousse_et_arbre_propre(self):
        self.assertEqual(
            gel.inspect_clone(self.clone), (self.head(), None, False)
        )

    def test_arbre_modifie_est_signale_sans_refus(self):
        with open(self.fichier, "w") as fh:
            fh.write("modifié")
        self.assertEqual(
            gel.inspect_clone(self.clone), (self.head(), None, True)
        )

    def test_fichier_non_suivi_n_est_pas_une_modification(self):
        open(os.path.join(self.clone, "nouveau.txt"), "w").close()
        self.assertEqual(gel.inspect_clone(self.clone)[1:], (None, False))

    def test_commit_non_pousse_est_refuse(self):
        self.commit("deux")
        sha, motif, sale = gel.inspect_clone(self.clone)
        self.assertEqual(sha, self.head())
        self.assertEqual(motif, "commit on no remote branch")
        self.assertFalse(sale)

    def test_tete_detachee_sur_un_commit_pousse(self):
        """Un clone que git-repo a posé sur un commit, sans branche locale,
        reste gelable : le distant contient ce commit."""
        sha = self.head()
        _git(self.clone, "checkout", "-q", "--detach", sha)
        self.assertEqual(gel.inspect_clone(self.clone), (sha, None, False))

    def test_ref_m_de_git_repo_ne_prouve_rien(self):
        """« refs/remotes/m/ » suit la révision du manifeste, pas le
        distant : un commit qu'elle seule contient reste refusé."""
        self.commit("deux")
        _git(self.clone, "update-ref", "refs/remotes/m/principale", "HEAD")
        self.assertEqual(
            gel.inspect_clone(self.clone)[1], "commit on no remote branch"
        )

    def test_ref_du_remote_amont_ne_prouve_rien(self):
        """La branche de suivi du remote amont nommé dit que l'AMONT a le
        commit, pas le fork d'où git-repo le récupère."""
        self.commit("deux")
        _git(self.clone, "update-ref", "refs/remotes/U/principale", "HEAD")
        self.assertEqual(
            gel.inspect_clone(self.clone, "U")[1], "commit on no remote branch"
        )
        self.assertIsNone(gel.inspect_clone(self.clone)[1])

    def test_sous_dossier_d_un_depot_n_est_pas_un_clone(self):
        """Un dossier non cloné sous un autre dépôt ne rend pas le commit
        de ce dépôt parent."""
        sous = os.path.join(self.clone, "sous")
        os.mkdir(sous)
        self.assertEqual(
            gel.inspect_clone(sous), (None, "not a git clone", False)
        )

    def test_chemin_absent(self):
        self.assertEqual(
            gel.inspect_clone(os.path.join(self.dossier, "absent")),
            (None, "not cloned", False),
        )

    def test_dossier_qui_n_est_pas_un_clone(self):
        vide = os.path.join(self.dossier, "vide")
        os.mkdir(vide)
        self.assertEqual(
            gel.inspect_clone(vide), (None, "not a git clone", False)
        )

    def test_clone_sans_commit(self):
        neuf = os.path.join(self.dossier, "neuf")
        _git(self.dossier, "init", "-q", neuf)
        self.assertEqual(
            gel.inspect_clone(neuf), (None, "not a git clone", False)
        )


if __name__ == "__main__":
    unittest.main()
