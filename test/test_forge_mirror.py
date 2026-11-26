#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le plan des miroirs d'une forge, sans réseau : noms des organisations,
URL d'origine, qualification d'un dépôt existant, paires et configuration
du minuteur.

Tous les propriétaires, dépôts et hôtes sont inventés.
"""

import os
import tempfile
import unittest
from unittest import mock

from script.forgejo import forge_sync
from script.git import forge_mirror as fm


def projet(nom="r.git", proprietaire="Org", branche="18.0", remote="Orig"):
    return {
        "cle": nom,
        "chemin": f"x/{nom}",
        "nom": nom,
        "remote": remote,
        "branche": branche,
        "proprietaire": proprietaire,
    }


class TestNoms(unittest.TestCase):
    def test_le_suffixe_est_celui_du_minuteur(self):
        self.assertEqual(fm.SUFFIXE, forge_sync.SUFFIXE)

    def test_organisation_miroir(self):
        self.assertEqual(fm.organisation_miroir("Org"), ("Org-mirror", ""))
        for proprietaire, interdits, motif in (
            ("x" * 34, (), "name refused by Forgejo"),
            ("x_", (), "name refused by Forgejo"),
            ("Org", {"org-MIRROR"}, "collides with an owner"),
            ("", (), "no owner"),
            (None, (), "no owner"),
        ):
            with self.subTest(proprietaire=proprietaire):
                self.assertEqual(
                    fm.organisation_miroir(proprietaire, interdits),
                    (None, motif),
                )

    def test_intervalle(self):
        for texte in ("1h", "30m", "1h30m", "10m"):
            with self.subTest(texte=texte):
                self.assertTrue(fm.intervalle_valide(texte))
        for texte in ("5m", "0", "", None, "1d", "1h5s", "h", "0h0m"):
            with self.subTest(texte=texte):
                self.assertFalse(fm.intervalle_valide(texte))


class TestUrls(unittest.TestCase):
    def test_url_du_projet_joint_comme_git_repo(self):
        self.assertEqual(
            fm.url_du_projet("https://git.example.invalid/Org", "r.git"),
            "https://git.example.invalid/Org/r.git",
        )
        self.assertEqual(
            fm.url_du_projet("https://git.example.invalid/Org/", "r.git"),
            "https://git.example.invalid/Org/r.git",
        )
        self.assertEqual(
            fm.url_du_projet("git@git.example.invalid:Org", "r"),
            "git@git.example.invalid:Org/r",
        )
        for fetch in ("..", "", None, "../Org"):
            with self.subTest(fetch=fetch):
                self.assertIsNone(fm.url_du_projet(fetch, "r.git"))

    def test_url_origine(self):
        for url in ("git@github.com:Org/r.git", "https://github.com/Org/r"):
            with self.subTest(url=url):
                self.assertEqual(
                    fm.url_origine(url), "https://github.com/Org/r.git"
                )
        self.assertEqual(
            fm.url_origine("https://u:p@git.example.invalid/g/r.git"),
            "https://git.example.invalid/g/r.git",
        )
        for url in (
            "ssh://git@git.example.invalid/g/r",
            "file:///x/r",
            "../r",
            None,
            "http://git.example.invalid/g/r",
        ):
            with self.subTest(url=url):
                self.assertIsNone(fm.url_origine(url))

    def test_meme_origine(self):
        a = "https://github.com/Org/r.git"
        for b in (
            "https://github.com/Org/r",
            "https://github.com/Org/r/",
            "https://GitHub.com/org/R.git",
            "https://u@github.com/Org/r",
        ):
            with self.subTest(b=b):
                self.assertTrue(fm.meme_origine(a, b))
        self.assertFalse(fm.meme_origine(a, "https://github.com/Org/s"))
        self.assertFalse(fm.meme_origine(a, None))

    def test_qualifier(self):
        origine = "https://github.com/Org/r.git"
        self.assertEqual(
            fm.qualifier({"mirror": False}, origine), "pas_miroir"
        )
        self.assertEqual(
            fm.qualifier(
                {"mirror": True, "original_url": "https://github.com/X/r"},
                origine,
            ),
            "autre_origine",
        )
        self.assertEqual(
            fm.qualifier(
                {"mirror": True, "original_url": origine, "empty": True},
                origine,
            ),
            "en_cours",
        )
        self.assertEqual(
            fm.qualifier(
                {"mirror": True, "original_url": origine[:-4], "empty": False},
                origine,
            ),
            "existant",
        )


class TestPlan(unittest.TestCase):
    REMOTES = {"Orig": "https://github.com/Org", "Rel": ".."}

    def test_la_branche_du_manifeste_se_suit_sous_son_nom(self):
        paires, ecartes = fm.plan_miroirs([projet()], self.REMOTES, set())
        self.assertEqual(ecartes, [])
        self.assertEqual(len(paires), 1)
        p = paires[0]
        self.assertEqual(p["depot"], "Org/r")
        self.assertEqual(p["miroir"], "Org-mirror/r")
        self.assertEqual(p["origine"], "https://github.com/Org/r.git")
        self.assertEqual(
            p["branches"],
            [{"travail": "18.0", "miroir": "18.0", "creer": False}],
        )

    def test_la_racine_garde_son_origine_et_ses_branches(self):
        racine = dict(
            projet("E", remote="origin", branche="dev"),
            origine="https://github.com/Org/E.git",
            branches=[
                {"travail": "develop", "miroir": "develop", "creer": True}
            ],
        )
        paires, _ = fm.plan_miroirs([racine], {}, set())
        self.assertEqual(paires[0]["origine"], "https://github.com/Org/E.git")
        self.assertEqual(paires[0]["branches"], racine["branches"])

    def test_deux_projets_du_meme_depot_font_une_paire(self):
        paires, _ = fm.plan_miroirs(
            [
                projet("r.git", branche="17.0"),
                projet("R.git", proprietaire="org", branche="18.0"),
                projet("r.git", branche="17.0"),
            ],
            self.REMOTES,
            set(),
        )
        self.assertEqual(len(paires), 1)
        self.assertEqual(
            [b["travail"] for b in paires[0]["branches"]], ["17.0", "18.0"]
        )

    def test_les_motifs_d_ecart(self):
        cas = [
            (projet(proprietaire=None), "no owner"),
            (projet(remote="Rel"), "no https origin"),
            (projet(proprietaire="Autre"), "collides with an owner"),
            (
                projet(proprietaire="Org-MIRROR"),
                "owner already ends in -mirror",
            ),
            (projet("r!.git"), "invalid repository name"),
            (projet(branche=None), "no branch"),
        ]
        paires, ecartes = fm.plan_miroirs(
            [p for p, _ in cas], self.REMOTES, {"autre-MIRROR"}
        )
        self.assertEqual(paires, [])
        self.assertEqual([m for _, m in ecartes], [m for _, m in cas])

    def test_un_proprietaire_en_mirror_ne_bloque_pas_les_autres(self):
        """Le minuteur refuse toute la configuration pour un dépôt de
        travail dont le propriétaire finit par le suffixe : le plan l'écarte
        seul, et les autres paires restent valides."""
        paires, ecartes = fm.plan_miroirs(
            [
                projet("a.git", proprietaire="acme-mirror"),
                projet("b.git", proprietaire="autre"),
            ],
            self.REMOTES,
            {"acme-mirror", "autre"},
        )
        self.assertEqual([p["depot"] for p in paires], ["autre/b"])
        self.assertEqual(
            [m for _, m in ecartes], ["owner already ends in -mirror"]
        )
        self.assertEqual(forge_sync.valider(fm.config_synchro(paires)), [])

    def test_la_configuration_du_minuteur(self):
        paires, _ = fm.plan_miroirs(
            [projet(), projet("s.git")], self.REMOTES, set()
        )
        config = fm.config_synchro(paires)
        self.assertEqual(forge_sync.valider(config), [])
        self.assertEqual(config["version"], 1)
        for paire in config["paires"]:
            self.assertEqual(set(paire), {"depot", "miroir", "branches"})
        texte = repr(config)
        for absent in ("projet", "origine", "forge", "compte", "github"):
            self.assertNotIn(absent, texte)

    def test_les_proprietaires_connus(self):
        self.assertEqual(
            fm.proprietaires_connus(
                {"a": "https://github.com/Org/", "b": "..", "c": None}
            ),
            {"Org"},
        )


class TestResume(unittest.TestCase):
    def test_le_resume_compte_et_detaille(self):
        etat = {
            "debut": "2099-01-01T08:00:00Z",
            "fin": "2099-01-01T08:01:00Z",
            "resultats": [
                {"depot": "Org/r", "branche": "18.0", "etat": "a_jour"},
                {"depot": "Org/s", "branche": "18.0", "etat": "avance"},
                {
                    "depot": "Org/t",
                    "branche": "18.0",
                    "etat": "divergent",
                    "detail": "+1/-2",
                    "depuis": "2098-12-31T08:00:00Z",
                },
            ],
        }
        lignes = fm.resume_etat(etat)
        self.assertIn("2099-01-01T08:00:00Z", lignes[0])
        self.assertEqual(lignes[1], "1 a_jour, 1 avance, 1 divergent")
        self.assertEqual(
            lignes[2:],
            ["Org/t 18.0: divergent +1/-2 (since 2098-12-31T08:00:00Z)"],
        )
        self.assertEqual(
            fm.resume_etat(etat, libelle=str.upper, depuis="depuis")[2],
            "Org/t 18.0: DIVERGENT +1/-2 (depuis 2098-12-31T08:00:00Z)",
        )
        self.assertEqual(fm.resume_etat(None), [])


class TestRemotesDOrigine(unittest.TestCase):
    def test_la_surcouche_de_forge_est_ignoree(self):
        depart = os.getcwd()
        with tempfile.TemporaryDirectory() as dossier:
            os.makedirs(os.path.join(dossier, "manifest"))
            os.makedirs(os.path.join(dossier, "private", "manifest"))
            with open(
                os.path.join(dossier, "manifest", "git_manifest_odoo99.0.xml"),
                "w",
            ) as fh:
                fh.write(
                    '<manifest><remote name="Orig"'
                    ' fetch="https://github.com/Org" /></manifest>'
                )
            with open(
                os.path.join(
                    dossier, "private", "manifest", "git_manifest_forge_x.xml"
                ),
                "w",
            ) as fh:
                fh.write(
                    '<manifest><remote name="Orig"'
                    ' fetch="ssh://git@forge.example.invalid:2222/Org/" />'
                    "</manifest>"
                )
            try:
                os.chdir(dossier)
                with mock.patch.object(
                    fm.git_freeze_manifest,
                    "default_sources",
                    return_value=[
                        "manifest/git_manifest_odoo99.0.xml",
                        "private/manifest/git_manifest_forge_x.xml",
                    ],
                ), mock.patch.object(
                    fm.git_freeze_manifest,
                    "freeze_sources",
                    return_value=["./manifest/git_manifest_odoo99.0.xml"],
                ):
                    remotes = fm.remotes_d_origine("99.0")
            finally:
                os.chdir(depart)
        self.assertEqual(remotes, {"Orig": "https://github.com/Org"})


class TestOriginePublique(unittest.TestCase):
    def test_sans_identifiants_ni_configuration(self):
        fini = mock.Mock(returncode=0)
        with mock.patch.object(
            fm.subprocess, "run", return_value=fini
        ) as lancer:
            self.assertTrue(
                fm.origine_publique("https://github.com/Org/r.git")
            )
        argv = lancer.call_args[0][0]
        env = lancer.call_args.kwargs["env"]
        self.assertIn("credential.helper=", argv)
        self.assertEqual(env["GIT_CONFIG_GLOBAL"], os.devnull)
        self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")

    def test_un_refus_ou_une_coupure_rendent_faux(self):
        with mock.patch.object(
            fm.subprocess, "run", return_value=mock.Mock(returncode=128)
        ):
            self.assertFalse(fm.origine_publique("https://x.invalid/r.git"))
        with mock.patch.object(
            fm.subprocess, "run", side_effect=OSError("no git")
        ):
            self.assertFalse(fm.origine_publique("https://x.invalid/r.git"))


if __name__ == "__main__":
    unittest.main()
