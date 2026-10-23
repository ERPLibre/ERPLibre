#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le diagnostic d'une mise à niveau, et le compte d'un écart de code.

Aucun réseau, aucun dépôt git réel : « git » est remplacé par une table de
réponses. Les verdicts sont une décision, et une décision se vérifie sur des
entrées choisies plutôt que sur l'état courant d'un amont public.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from script.git import repo_stats, repo_upgrade


class TestClasserFichier(unittest.TestCase):
    def test_traduction_par_repertoire_et_par_extension(self):
        for chemin in ("m/i18n/fr.po", "m/i18n/m.pot", "m/i18n/x.csv"):
            self.assertEqual(repo_stats.classer_fichier(chemin), "i18n")

    def test_documentation(self):
        for chemin in ("m/README.rst", "m/readme/DESCRIPTION.md", "m/a.txt"):
            self.assertEqual(repo_stats.classer_fichier(chemin), "doc")

    def test_page_engendree_est_documentation(self):
        """C'est le cas qui décide du chiffre principal.

        Cette page est ENGENDRÉE à partir du répertoire « readme » du
        module. Une règle qui ne lirait que l'extension la classerait en
        code, et le verdict « documentation seulement » deviendrait faux
        sur la forme de changement la plus courante.
        """
        self.assertEqual(
            repo_stats.classer_fichier("m/static/description/index.html"),
            "doc",
        )

    def test_autre_html_reste_du_code(self):
        self.assertEqual(
            repo_stats.classer_fichier("m/static/src/x.html"), "code"
        )

    def test_code(self):
        for chemin in (
            "m/models/a.py",
            "m/views/v.xml",
            "m/static/s.js",
            "m/security/ir.model.access.csv",
            "m/s.scss",
        ):
            self.assertEqual(repo_stats.classer_fichier(chemin), "code")

    def test_ni_l_un_ni_l_autre(self):
        self.assertEqual(repo_stats.classer_fichier("LICENSE"), "autre")

    def test_insensible_a_la_casse(self):
        self.assertEqual(repo_stats.classer_fichier("m/MODELS/A.PY"), "code")


class TestModuleDe(unittest.TestCase):
    def test_premier_segment(self):
        self.assertEqual(repo_stats.module_de("mon_module/a.py"), "mon_module")

    def test_fichier_a_la_racine_n_a_pas_de_module(self):
        """Lui en attribuer un gonflerait le compte des modules touchés."""
        self.assertIsNone(repo_stats.module_de("setup.py"))

    def test_prefixes_du_coeur(self):
        prefixes = repo_stats.PREFIXES_ODOO_CORE
        self.assertEqual(
            repo_stats.module_de("addons/base/a.py", prefixes), "base"
        )
        self.assertEqual(
            repo_stats.module_de("odoo/addons/web/a.py", prefixes), "web"
        )

    def test_hors_prefixe_du_coeur(self):
        self.assertIsNone(
            repo_stats.module_de("doc/a.py", repo_stats.PREFIXES_ODOO_CORE)
        )


class TestLireNumstat(unittest.TestCase):
    def test_compte_simple(self):
        lst = repo_stats.lire_numstat("3\t1\tm/a.py\n10\t0\tm/b.py\n")
        self.assertEqual(lst, [(3, 1, "m/a.py"), (10, 0, "m/b.py")])

    def test_binaire_compte_zero_mais_reste(self):
        """Un binaire a changé ; le taire ferait disparaître son module."""
        lst = repo_stats.lire_numstat("-\t-\tm/static/logo.png\n")
        self.assertEqual(lst, [(0, 0, "m/static/logo.png")])

    def test_renommage_entre_accolades(self):
        lst = repo_stats.lire_numstat("1\t1\tm/{vieux => neuf}/a.py\n")
        self.assertEqual(lst[0][2], "m/neuf/a.py")

    def test_renommage_complet(self):
        lst = repo_stats.lire_numstat("1\t1\tvieux/a.py => neuf/a.py\n")
        self.assertEqual(lst[0][2], "neuf/a.py")

    def test_ligne_inutilisable_ignoree(self):
        self.assertEqual(repo_stats.lire_numstat("n'importe quoi\n"), [])


class TestAgreger(unittest.TestCase):
    def test_module_de_documentation_seulement(self):
        lignes = repo_stats.lire_numstat(
            "5\t0\tdoc_seul/i18n/fr.po\n"
            "3\t0\tdoc_seul/README.rst\n"
            "9\t1\tavec_code/models/a.py\n"
            "2\t0\tavec_code/i18n/fr.po\n"
        )
        res = repo_stats.agreger(lignes)
        self.assertEqual(res["modules_doc"], ["doc_seul"])
        self.assertEqual(res["modules_code"], ["avec_code"])

    def test_un_seul_fichier_de_code_suffit(self):
        """Un module sort de « documentation seulement » dès le premier
        fichier de code : c'est ce qui le renvoie en relecture."""
        lignes = repo_stats.lire_numstat(
            "50\t0\tm/i18n/fr.po\n1\t0\tm/models/a.py\n"
        )
        self.assertEqual(repo_stats.agreger(lignes)["modules_doc"], [])

    def test_totaux_et_langages(self):
        lignes = repo_stats.lire_numstat("3\t1\tm/a.py\n4\t2\tm/v.xml\n")
        res = repo_stats.agreger(lignes)
        self.assertEqual((res["ajouts"], res["retraits"]), (7, 3))
        self.assertEqual(res["langages"]["XML"]["ajouts"], 4)
        self.assertEqual(res["langages"]["Python"]["retraits"], 1)


def constat_type(branche="18.0"):
    return {
        "chemin": "odooX/addons/Amont_d",
        "nom": "d.git",
        "revision": "18.0_dev",
        "etat": "declare",
        "amont": {
            "remote": "Amont",
            "nom": "d.git",
            "url": "https://example.org/amont/d.git",
            "branche": branche,
            "source": "declare",
            "remote_declare": True,
        },
    }


class GitSimule:
    """Une table de réponses à la place de git.

    Le diagnostic enchaîne une dizaine de commandes ; les simuler une par
    une laisse choisir exactement la situation à éprouver, ce qu'un dépôt
    réel ne permet pas.
    """

    def __init__(self, **reponses):
        self.reponses = reponses
        self.vues = []

    def _clone_et_remote(self, nom, args, cwd):
        """Les réponses qui posent le remote amont, ou None pour les autres.

        `cwd` est la racine de son clone. « url_en_place » est l'URL que le
        clone donne déjà au remote amont, None quand il n'en a aucun.
        """
        if nom == "rev-parse" and "--show-toplevel" in args:
            return cwd + "\n", "", 0
        if nom == "config":
            url = self.reponses.get("url_en_place")
            return ("", "", 1) if url is None else (url + "\n", "", 0)
        if nom == "remote":
            return "", "", self.reponses.get("remote_code", 0)
        return None

    def __call__(self, args, cwd, delai=None):
        self.vues.append(list(args))
        nom = args[0]
        reponse = self._clone_et_remote(nom, args, cwd)
        if reponse is not None:
            return reponse
        if nom == "rev-parse":
            return self.reponses.get("superficiel", "false"), "", 0
        if nom == "fetch":
            return "", "", self.reponses.get("fetch_code", 0)
        if nom == "cat-file":
            return "", "", self.reponses.get("base_presente_code", 0)
        if nom == "rev-list" and "--left-right" not in args:
            return f"{self.reponses.get('depuis_gel', 7)}\n", "", 0
        if nom == "rev-list":
            ecart = self.reponses.get("divergence", (1, 545))
            if ecart is None:
                return "", "", 1
            return f"{ecart[0]}\t{ecart[1]}\n", "", 0
        if nom == "merge-base" and "--is-ancestor" in args:
            return "", "", self.reponses.get("ancetre_code", 0)
        if nom == "merge-base":
            base = self.reponses.get("base", "abc1234")
            return (base or "") + "\n", "", 0 if base else 1
        if nom == "log":
            return self.reponses.get("log", "aaa1111\t[ADD] m\n"), "", 0
        if nom == "diff":
            if "FETCH_HEAD...HEAD" in args:
                return self.reponses.get("nos", "9\t0\tm/models/a.py\n"), "", 0
            return self.reponses.get("amont", "4\t0\tautre/a.py\n"), "", 0
        if nom == "merge-tree":
            conflits = self.reponses.get("conflits", [])
            if not conflits:
                return "tree123\n", "", 0
            return "tree123\n" + "\n".join(conflits) + "\n", "", 1
        if nom == "ls-tree":
            ref = args[3]
            presents = self.reponses.get("arbres", {}).get(ref, [])
            return "\n".join(presents) + "\n", "", 0
        return "", "", 0


def diagnostiquer_simule(constat, git_simule):
    with patch.object(repo_upgrade, "git", git_simule), patch(
        "os.path.isdir", return_value=True
    ):
        return repo_upgrade.diagnostiquer(constat)


class TestDiagnostiquer(unittest.TestCase):
    def test_a_jour(self):
        res = diagnostiquer_simule(
            constat_type(), GitSimule(divergence=(0, 0))
        )
        self.assertEqual(res["verdict"], "a_jour")

    def test_en_retard(self):
        res = diagnostiquer_simule(
            constat_type(), GitSimule(divergence=(0, 12))
        )
        self.assertEqual(res["verdict"], "en_retard")

    def test_a_rebaser_quand_la_fusion_est_propre(self):
        res = diagnostiquer_simule(
            constat_type(),
            GitSimule(
                divergence=(2, 550),
                conflits=[],
                arbres={"HEAD": ["m/__manifest__.py"]},
            ),
        )
        self.assertEqual(res["verdict"], "a_rebaser")
        self.assertEqual(res["nos"], 2)
        self.assertEqual(res["amont_avance"], 550)

    def test_en_conflit(self):
        res = diagnostiquer_simule(
            constat_type(),
            GitSimule(
                conflits=["m/models/a.py"],
                arbres={
                    "HEAD": ["m/__manifest__.py"],
                    "abc1234": ["m/__manifest__.py"],
                    "FETCH_HEAD": ["m/__manifest__.py"],
                },
            ),
        )
        self.assertEqual(res["verdict"], "en_conflit")
        self.assertEqual(res["modules_repris"], [])

    def test_absorbe_quand_l_amont_a_repris_le_module(self):
        """Absent à la base, présent chez l'amont : il est venu par nous
        puis par eux, et notre commit n'a plus de raison d'être."""
        res = diagnostiquer_simule(
            constat_type(),
            GitSimule(
                conflits=["m/README.rst"],
                arbres={
                    "HEAD": ["m/__manifest__.py"],
                    "abc1234": [],
                    "FETCH_HEAD": ["m/__manifest__.py"],
                },
            ),
        )
        self.assertEqual(res["verdict"], "absorbe")
        self.assertEqual(res["modules_repris"], ["m"])

    def test_module_seulement_modifie_n_est_pas_repris(self):
        """Un module présent DES DEUX CÔTÉS depuis la base n'est pas une
        reprise : proposer d'abandonner le correctif serait une faute."""
        res = diagnostiquer_simule(
            constat_type(),
            GitSimule(
                conflits=["m/models/a.py"],
                arbres={
                    "HEAD": ["m/__manifest__.py"],
                    "abc1234": ["m/__manifest__.py"],
                    "FETCH_HEAD": ["m/__manifest__.py"],
                },
            ),
        )
        self.assertEqual(res["modules_repris"], [])
        self.assertNotEqual(res["verdict"], "absorbe")

    def test_superficiel_non_comparable(self):
        res = diagnostiquer_simule(
            constat_type(), GitSimule(superficiel="true")
        )
        self.assertEqual(res["verdict"], "non_comparable")

    def test_amont_injoignable_non_comparable(self):
        res = diagnostiquer_simule(constat_type(), GitSimule(fetch_code=128))
        self.assertEqual(res["verdict"], "non_comparable")

    def test_sans_branche_amont_non_comparable(self):
        res = diagnostiquer_simule(constat_type(branche=None), GitSimule())
        self.assertEqual(res["verdict"], "non_comparable")

    def test_sans_base_de_fusion_non_comparable(self):
        res = diagnostiquer_simule(constat_type(), GitSimule(base=""))
        self.assertEqual(res["verdict"], "non_comparable")

    def test_aucune_commande_n_ecrit(self):
        """La passe à sec ne touche ni branche locale, ni index, ni arbre :
        elle n'écrit que le remote amont nommé et sa branche de suivi."""
        simule = GitSimule(conflits=[], arbres={"HEAD": []})
        diagnostiquer_simule(constat_type(), simule)
        interdits = {
            "checkout",
            "rebase",
            "merge",
            "push",
            "reset",
            "commit",
            "branch",
            "cherry-pick",
            "am",
            "apply",
            "switch",
            "update-ref",
        }
        for args in simule.vues:
            self.assertNotIn(args[0], interdits, f"commande écrivante {args}")
        remotes = [a for a in simule.vues if a[0] == "remote"]
        self.assertEqual(
            remotes,
            [
                [
                    "remote",
                    "add",
                    "--no-tags",
                    "-t",
                    "18.0",
                    "Amont",
                    "https://example.org/amont/d.git",
                ]
            ],
        )
        (fetch,) = [a for a in simule.vues if a[0] == "fetch"]
        self.assertEqual(fetch[-1], "+refs/heads/18.0:refs/remotes/Amont/18.0")

    def test_la_cible_est_la_branche_du_remote_amont(self):
        res = diagnostiquer_simule(
            constat_type(), GitSimule(divergence=(0, 3))
        )
        self.assertEqual(res["cible"], "Amont/18.0")
        self.assertEqual(res["remote_amont"], "ajoute")

    def test_remote_present_a_la_meme_url_sert_tel_quel(self):
        simule = GitSimule(
            divergence=(0, 0), url_en_place="https://example.org/amont/d.git"
        )
        res = diagnostiquer_simule(constat_type(), simule)
        self.assertEqual(res["remote_amont"], "present")
        self.assertEqual(res["cible"], "Amont/18.0")
        self.assertNotIn("remote", [a[0] for a in simule.vues])

    def test_remote_a_une_autre_url_non_comparable_et_intact(self):
        """Le remote d'un humain n'est jamais réécrit : le constat donne la
        commande qui le corrige, et rien n'est récupéré."""
        simule = GitSimule(url_en_place="https://example.org/ailleurs/d.git")
        res = diagnostiquer_simule(constat_type(), simule)
        self.assertEqual(res["verdict"], "non_comparable")
        self.assertEqual(res["remote_amont"], "autre_url")
        self.assertEqual(
            res["motif"],
            repo_upgrade.t("upstream remote points to another URL"),
        )
        self.assertEqual(
            res["correction"],
            "git -C odooX/addons/Amont_d remote set-url Amont"
            " https://example.org/amont/d.git",
        )
        self.assertIsNone(res["cible"])
        commandes = [a[0] for a in simule.vues]
        self.assertNotIn("remote", commandes)
        self.assertNotIn("fetch", commandes)
        texte = repo_upgrade.render_diagnostic([res], "X", colour=False)
        self.assertIn(res["correction"], texte)
        self.assertIn("https://example.org/ailleurs/d.git", texte)

    def test_remote_refuse_non_comparable(self):
        res = diagnostiquer_simule(constat_type(), GitSimule(remote_code=3))
        self.assertEqual(res["verdict"], "non_comparable")
        self.assertEqual(res["remote_amont"], "refuse")

    def test_amont_devine_recupere_par_l_url_sans_remote(self):
        constat = constat_type()
        constat["amont"]["source"] = "convention"
        simule = GitSimule(divergence=(0, 2))
        res = diagnostiquer_simule(constat, simule)
        self.assertEqual(res["cible"], "FETCH_HEAD")
        self.assertIsNone(res["remote_amont"])
        commandes = [a[0] for a in simule.vues]
        self.assertNotIn("remote", commandes)
        self.assertNotIn("config", commandes)
        (fetch,) = [a for a in simule.vues if a[0] == "fetch"]
        self.assertEqual(
            fetch[-2:], ["https://example.org/amont/d.git", "18.0"]
        )

    def test_superficiel_ne_recoit_ni_remote_ni_fetch(self):
        simule = GitSimule(superficiel="true")
        diagnostiquer_simule(constat_type(), simule)
        commandes = [a[0] for a in simule.vues]
        self.assertNotIn("remote", commandes)
        self.assertNotIn("fetch", commandes)


BASE_GELEE = "e" * 40


def constat_gele():
    return dict(constat_type(), base_gelee=BASE_GELEE)


class TestDepuisLeGel(unittest.TestCase):
    """L'écart à la base amont gelée, lu contre FETCH_HEAD."""

    def test_amont_qui_avance(self):
        simule = GitSimule(divergence=(0, 12), depuis_gel=9)
        res = diagnostiquer_simule(constat_gele(), simule)
        self.assertEqual(res["amont_depuis_gel"], 9)
        self.assertFalse(res["amont_reecrit"])
        self.assertIn(
            ["rev-list", "--count", f"{BASE_GELEE}..FETCH_HEAD"], simule.vues
        )
        self.assertIn(
            ["merge-base", "--is-ancestor", BASE_GELEE, "FETCH_HEAD"],
            simule.vues,
        )

    def test_base_qui_n_est_plus_ancetre_dit_un_amont_reecrit(self):
        res = diagnostiquer_simule(constat_gele(), GitSimule(ancetre_code=1))
        self.assertTrue(res["amont_reecrit"])
        self.assertIsNone(res["amont_depuis_gel"])

    def test_base_absente_du_clone_dit_un_amont_reecrit(self):
        res = diagnostiquer_simule(
            constat_gele(), GitSimule(base_presente_code=1)
        )
        self.assertTrue(res["amont_reecrit"])

    def test_erreur_de_git_ne_tranche_pas(self):
        res = diagnostiquer_simule(constat_gele(), GitSimule(ancetre_code=128))
        self.assertIsNone(res["amont_reecrit"])
        self.assertIsNone(res["amont_depuis_gel"])

    def test_sans_base_gelee_aucune_question(self):
        simule = GitSimule()
        res = diagnostiquer_simule(constat_type(), simule)
        self.assertIsNone(res["amont_depuis_gel"])
        self.assertNotIn("cat-file", [a[0] for a in simule.vues])

    def test_amont_injoignable_aucune_question(self):
        simule = GitSimule(fetch_code=128)
        res = diagnostiquer_simule(constat_gele(), simule)
        self.assertIsNone(res["amont_reecrit"])
        self.assertNotIn("cat-file", [a[0] for a in simule.vues])

    def test_le_rendu(self):
        base = {
            "chemin": "d1",
            "verdict": "en_retard",
            "nos": 0,
            "amont_avance": 9,
            "conflits": [],
            "motif": None,
            "modules_repris": [],
            "base_gelee": BASE_GELEE,
            "amont_depuis_gel": 9,
            "amont_reecrit": False,
        }
        texte = repo_upgrade.render_diagnostic([base], "X", colour=False)
        self.assertIn(
            f"9 {repo_upgrade.t('upstream commits since the freeze')}"
            f" ({BASE_GELEE[:12]})",
            texte,
        )
        reecrit = dict(base, amont_depuis_gel=None, amont_reecrit=True)
        texte = repo_upgrade.render_diagnostic([reecrit], "X", colour=False)
        self.assertIn(
            repo_upgrade.t("upstream rewritten since the freeze"), texte
        )
        sans = dict(base, base_gelee=None)
        self.assertIsNone(repo_upgrade.ligne_gel(sans))


class TestBaseGeleeDesManifestes(unittest.TestCase):
    """La base gelée se lit dans les manifestes, sur la définition qui
    l'emporte dans la fusion : principal, puis dev, puis extra."""

    def setUp(self):
        self.dossier = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dossier, True)

    def ecrire(self, fichier, base):
        attr = f' fork-upstream-freeze-revision="{base}"' if base else ""
        with open(os.path.join(self.dossier, fichier), "w") as fh:
            fh.write(
                "<manifest>\n"
                '  <remote name="Amont" fetch="https://example.org/amont/"/>'
                "\n"
                '  <project name="d.git" path="odooX/addons/Amont_d"'
                ' remote="Prop_origin_Amont" fork-upstream-remote="Amont"'
                f' fork-upstream="X" revision="X_dev"{attr}/>\n'
                "</manifest>\n"
            )

    def test_ordre_de_la_fusion(self):
        for fichier in (
            "git_manifest_extra_odooX.xml",
            "git_manifest_odooX_dev.xml",
            "git_manifest_odooX.xml",
        ):
            self.ecrire(fichier, None)
        self.assertEqual(
            [
                os.path.basename(f)
                for f in repo_upgrade.fichiers_manifeste("X", self.dossier)
            ],
            [
                "git_manifest_odooX.xml",
                "git_manifest_odooX_dev.xml",
                "git_manifest_extra_odooX.xml",
            ],
        )

    def test_la_derniere_definition_porte_la_base(self):
        self.ecrire("git_manifest_odooX.xml", "1" * 40)
        self.ecrire("git_manifest_odooX_dev.xml", None)
        (fork,) = repo_upgrade.etat_forks("X", self.dossier)
        self.assertIsNone(fork["base_gelee"])
        self.ecrire("git_manifest_extra_odooX.xml", "2" * 40)
        (fork,) = repo_upgrade.etat_forks("X", self.dossier)
        self.assertEqual(fork["base_gelee"], "2" * 40)
        texte = repo_upgrade.render([fork], False, colour=False)
        self.assertIn(f"{repo_upgrade.t('frozen base')} {'2' * 12}", texte)


class TestPrefixesModule(unittest.TestCase):
    def test_coeur_odoo(self):
        self.assertEqual(
            repo_upgrade.prefixes_module({"chemin": "odoo18.0/odoo"}),
            repo_stats.PREFIXES_ODOO_CORE,
        )

    def test_depot_ordinaire(self):
        self.assertEqual(
            repo_upgrade.prefixes_module(
                {"chemin": "odoo18.0/addons/OCA_web"}
            ),
            repo_stats.PREFIXES_DEFAUT,
        )


class TestCumulerEtRendu(unittest.TestCase):
    def lot(self):
        return [
            {
                "chemin": "d1",
                "verdict": "a_rebaser",
                "nos": 1,
                "amont_avance": 10,
                "conflits": [],
                "motif": None,
                "modules_repris": [],
                "modules_amont_doc": ["m_doc"],
                "modules_amont_code": ["m_code"],
                "stats_amont": {
                    "langages": {"Python": {"ajouts": 5, "retraits": 1}}
                },
            },
            {
                "chemin": "d2",
                "verdict": "non_comparable",
                "nos": 0,
                "amont_avance": 0,
                "conflits": [],
                "motif": "dépôt superficiel",
                "modules_repris": [],
                "modules_amont_doc": [],
                "modules_amont_code": ["m_code"],
                "stats_amont": {
                    "langages": {"Python": {"ajouts": 2, "retraits": 0}}
                },
            },
        ]

    def test_les_langages_s_additionnent(self):
        total = repo_upgrade.cumuler(self.lot())
        self.assertEqual(total["langages"]["Python"]["ajouts"], 7)

    def test_un_module_homonyme_compte_deux_fois(self):
        """Deux dépôts peuvent porter le même nom de module ; les fondre
        en ferait disparaître un du compte."""
        total = repo_upgrade.cumuler(self.lot())
        self.assertEqual(
            total["modules_code"], [("d1", "m_code"), ("d2", "m_code")]
        )

    def test_le_rendu_nomme_les_depots_non_comparables(self):
        """Un dépôt que rien n'a touché est NOMMÉ : « rien à faire » et
        « comparaison impossible » sont deux réponses différentes."""
        texte = repo_upgrade.render_diagnostic(self.lot(), "X", colour=False)
        self.assertIn("d2", texte)
        self.assertIn("dépôt superficiel", texte)

    def test_le_rendu_dit_ce_qui_a_ete_ecrit(self):
        lot = self.lot()
        lot[0]["remote_amont"] = "ajoute"
        lot[1]["remote_amont"] = "present"
        texte = repo_upgrade.render_diagnostic(lot, "X", colour=False)
        self.assertIn(f"{repo_upgrade.t('Upstream remotes added:')} 1", texte)
        self.assertIn(
            repo_upgrade.t("no local branch moved, no work tree touched"),
            texte,
        )


class TestSansInvite(unittest.TestCase):
    """Un git lancé par la passe ne peut jamais attendre un identifiant."""

    def _env_passe(self, appel):
        with patch.object(repo_upgrade.subprocess, "run") as run:
            run.return_value.returncode = 1
            run.return_value.stdout = ""
            run.return_value.stderr = ""
            appel()
        return run.call_args.kwargs["env"]

    def test_ls_remote_sans_invite(self):
        env = self._env_passe(
            lambda: repo_upgrade.branches("https://example.invalid/a.git")
        )
        self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")

    def test_git_sans_invite(self):
        env = self._env_passe(lambda: repo_upgrade.git(["fetch"], "/nulle"))
        self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")

    def test_environnement_conserve(self):
        with patch.dict(os.environ, {"GIT_SSH_COMMAND": "ssh -o Batch=yes"}):
            env = repo_upgrade.env_sans_invite()
        self.assertEqual(env["GIT_SSH_COMMAND"], "ssh -o Batch=yes")

    def test_branches_injoignable_rend_none(self):
        with patch.object(repo_upgrade.subprocess, "run") as run:
            run.return_value.returncode = 128
            run.return_value.stdout = ""
            self.assertIsNone(
                repo_upgrade.branches("https://example.invalid/a.git")
            )


def _git_reel(depot, *args):
    return subprocess.run(
        ["git", "-C", depot, *args], check=True, capture_output=True, text=True
    ).stdout.strip()


class TestApprofondir(unittest.TestCase):
    """Un amont de 30 commits, un fork qui y ajoute 2 commits, et un clone
    du fork à 2 commits de profondeur : sans historique, il n'a aucune base
    de fusion avec l'amont. Tous les dépôts sont dans le dossier temporaire,
    joints par « file:// », la seule URL locale qui respecte « --depth »."""

    REMOTE = "fork_origin_amont"
    REVISION = "X.0"

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
        amont = os.path.join(self.dossier, "amont.git")
        fork = os.path.join(self.dossier, "fork.git")
        source = os.path.join(self.dossier, "source")
        _git_reel(self.dossier, "init", "-q", "--bare", amont)
        _git_reel(self.dossier, "init", "-q", "--bare", fork)
        _git_reel(self.dossier, "init", "-q", source)
        for i in range(30):
            _git_reel(source, "commit", "-q", "--allow-empty", "-m", f"a{i}")
        self.base = _git_reel(source, "rev-parse", "HEAD")
        _git_reel(source, "push", "-q", amont, "HEAD:principale")
        for i in range(2):
            _git_reel(source, "commit", "-q", "--allow-empty", "-m", f"f{i}")
        _git_reel(source, "push", "-q", fork, f"HEAD:{self.REVISION}")
        self.racine = os.path.join(self.dossier, "racine")
        self.clone = os.path.join(self.racine, "c", "p")
        _git_reel(
            self.dossier,
            "clone",
            "-q",
            "--depth",
            "2",
            "-o",
            self.REMOTE,
            "-b",
            self.REVISION,
            f"file://{fork}",
            self.clone,
        )
        self.constat = {
            "chemin": "c/p",
            "remote": self.REMOTE,
            "revision": self.REVISION,
            "amont": {
                "remote": "amont_up",
                "nom": "amont.git",
                "url": f"file://{amont}",
                "branche": "principale",
                "source": "declare",
                "remote_declare": True,
            },
        }

    def test_le_clone_superficiel_est_candidat(self):
        self.assertTrue(repo_upgrade.est_superficiel(self.clone))
        self.assertTrue(repo_upgrade.a_approfondir(self.constat, self.racine))

    def test_complet_avec_sa_base_de_fusion(self):
        tete = _git_reel(self.clone, "rev-parse", "HEAD")
        # Posé sur le clone encore superficiel, comme le fait le diagnostic.
        repo_upgrade.preparer_remote(self.clone, self.constat["amont"])
        res = repo_upgrade.approfondir(self.constat, self.racine)
        self.assertEqual(res["issue"], "complet", res)
        self.assertFalse(repo_upgrade.est_superficiel(self.clone))
        self.assertEqual(
            _git_reel(self.clone, "merge-base", "HEAD", "amont_up/principale"),
            self.base,
        )
        # Ni la branche ni l'arbre n'ont bougé.
        self.assertEqual(_git_reel(self.clone, "rev-parse", "HEAD"), tete)
        out, _err, code = repo_upgrade.git(
            ["config", "--get", "remote.amont_up.skipFetchAll"], self.clone
        )
        self.assertEqual((code, out), (1, ""))
        self.assertFalse(repo_upgrade.a_approfondir(self.constat, self.racine))

    def test_une_branche_absente_du_fork_echoue(self):
        constat = dict(self.constat, revision="inexistante")
        res = repo_upgrade.approfondir(constat, self.racine)
        self.assertEqual(res["issue"], "fork_echoue")
        self.assertTrue(res["erreur"])
        self.assertTrue(repo_upgrade.est_superficiel(self.clone))

    def test_un_clone_complet_n_est_pas_touche(self):
        _git_reel(self.clone, "fetch", "-q", "--unshallow")
        res = repo_upgrade.approfondir(self.constat, self.racine)
        self.assertEqual(res["issue"], "non_applicable")

    def test_les_commandes_a_la_main(self):
        self.assertEqual(
            repo_upgrade.commandes_approfondir(self.constat),
            [
                f"git -C c/p fetch --unshallow --no-tags {self.REMOTE} X.0",
                "git -C c/p fetch amont_up",
            ],
        )

    def test_chaque_issue_a_son_libelle(self):
        for issue in (
            "non_applicable",
            "fork_echoue",
            "encore_superficiel",
            "autre_url",
            "refuse",
            "non_clone",
            "amont_echoue",
            "complet",
        ):
            self.assertIn(issue, repo_upgrade.LIBELLES_APPROFONDIR)


if __name__ == "__main__":
    unittest.main()
