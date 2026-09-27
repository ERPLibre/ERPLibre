#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le diagnostic d'une mise à niveau, et le compte d'un écart de code.

Aucun réseau, aucun dépôt git réel : « git » est remplacé par une table de
réponses. Les verdicts sont une décision, et une décision se vérifie sur des
entrées choisies plutôt que sur l'état courant d'un amont public.
"""

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

    def __call__(self, args, cwd, delai=None):
        self.vues.append(list(args))
        nom = args[0]
        if nom == "rev-parse":
            return self.reponses.get("superficiel", "false"), "", 0
        if nom == "fetch":
            return "", "", self.reponses.get("fetch_code", 0)
        if nom == "rev-list":
            ecart = self.reponses.get("divergence", (1, 545))
            if ecart is None:
                return "", "", 1
            return f"{ecart[0]}\t{ecart[1]}\n", "", 0
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
        """La passe à sec ne doit toucher ni branche, ni remote, ni index."""
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
            "remote",
            "cherry-pick",
            "am",
            "apply",
            "switch",
        }
        for args in simule.vues:
            self.assertNotIn(args[0], interdits, f"commande écrivante {args}")


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

    def test_le_rendu_annonce_l_absence_d_ecriture(self):
        texte = repo_upgrade.render_diagnostic(self.lot(), "X", colour=False)
        self.assertIn(repo_upgrade.t("No state was written"), texte)


if __name__ == "__main__":
    unittest.main()
