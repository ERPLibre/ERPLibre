#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Ce que le cache pose DANS la VM, et l'ordre dans lequel il le pose.

L'interception est transparente au niveau TCP mais pas au niveau TLS : un
invité qui n'approuve pas l'autorité du cache rejette son certificat, et tout
téléchargement HTTPS échoue. Trois choses doivent donc arriver dans la VM, et
la troisième est un piège que la table seule ne dit pas :

  1. le certificat, à l'endroit où la famille de distribution range ses ancres ;
  2. la commande qui fait relire ce magasin, AVANT tout téléchargement ;
  3. les variables que pip et npm exigent, parce qu'ils embarquent leur propre
     jeu de certificats et ignorent le magasin système.

La table des chemins existe deux fois — ici en Python, et dans
script/qemu_cache/rules.go côté cache. La duplication est assumée : deploy
n'a pas à dépendre du binaire pour générer un user-data. Le dernier test la
rend sûre en comparant les deux.
"""

import argparse
import re
import sys
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from script.qemu.deploy_qemu import (  # noqa: E402
    CACHE_CERT_NAME,
    CACHE_ENV_VARS,
    CACHE_TRUST,
    cache_family,
    cache_files,
    cache_runcmd,
)

RULES_GO = RACINE / "script" / "qemu_cache" / "rules.go"

# Une autorité inventée : un certificat réel dans un test le figerait pour
# toujours, et celui d'un parc n'a rien à faire dans le dépôt.
PEM_DE_TEST = (
    "-----BEGIN CERTIFICATE-----\n"
    "MIIBkTCB+wIJAOk0000000000MA0GCSqGSIb3DQEBCwUAMBQxEjAQBgNVBAMTCXRl\n"
    "c3QtY2FjaGUwHhcNMjYwMTAxMDAwMDAwWhcNMzYwMTAxMDAwMDAwWjAUMRIwEAYD\n"
    "-----END CERTIFICATE-----\n"
)


def faux_args(tmp, distro="arch", ca=True):
    """Le strict nécessaire : ces fonctions ne lisent que deux champs."""
    chemin = ""
    if ca:
        chemin = str(tmp / "ca.crt")
        (tmp / "ca.crt").write_text(PEM_DE_TEST, encoding="utf-8")
    return argparse.Namespace(distro=distro, cache_ca=chemin)


class TestFamilles(unittest.TestCase):
    def test_toutes_les_distributions_du_catalogue_ont_une_famille(self):
        """Une distribution sans famille ne recevrait rien, en silence."""
        for distro in (
            "ubuntu",
            "debian",
            "linuxmint",
            "fedora",
            "almalinux",
            "rocky",
            "opensuse",
            "arch",
        ):
            self.assertIn(
                cache_family(distro),
                CACHE_TRUST,
                f"{distro} n'a pas de famille connue",
            )

    def test_distribution_inconnue_ne_pose_rien(self):
        self.assertEqual(cache_family("plan9"), "")


class TestCertificatPose(unittest.TestCase):
    def test_pose_au_bon_endroit_par_famille(self):
        import tempfile

        for distro, attendu in (
            ("arch", "/etc/ca-certificates/trust-source/anchors"),
            ("debian", "/usr/local/share/ca-certificates"),
            ("fedora", "/etc/pki/ca-trust/source/anchors"),
            ("opensuse", "/etc/pki/trust/anchors"),
        ):
            with tempfile.TemporaryDirectory() as d:
                fichiers = cache_files(faux_args(Path(d), distro))
                self.assertEqual(len(fichiers), 1, f"{distro} : rien de posé")
                chemin, mode, contenu, _ = fichiers[0]
                self.assertEqual(chemin, f"{attendu}/{CACHE_CERT_NAME}")
                self.assertEqual(
                    mode,
                    "0644",
                    "le mode doit être une CHAÎNE : cloud-init lit un entier "
                    "non quoté en décimal et pose des droits absurdes",
                )
                self.assertIn("BEGIN CERTIFICATE", contenu)

    def test_rien_sans_autorite_demandee(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(cache_files(faux_args(Path(d), ca=False)), [])
            self.assertEqual(cache_runcmd(faux_args(Path(d), ca=False)), [])

    def test_autorite_illisible_ne_casse_pas_le_deploiement(self):
        """Sans autorité la VM télécharge en direct, ce qui marche : un
        chemin fautif ne doit pas empêcher de créer la machine."""
        args = argparse.Namespace(distro="arch", cache_ca="/inexistant/ca.crt")
        self.assertEqual(cache_files(args), [])

    def test_fichier_qui_nest_pas_un_certificat_refuse(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            faux = Path(d) / "ca.crt"
            faux.write_text("ceci n'est pas un certificat\n", encoding="utf-8")
            args = argparse.Namespace(distro="arch", cache_ca=str(faux))
            self.assertEqual(cache_files(args), [])

    def test_distribution_hors_table_ne_pose_rien(self):
        """Poser le fichier au hasard le rendrait inopérant sans le dire."""
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(cache_files(faux_args(Path(d), "plan9")), [])


class TestRuncmd(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.lignes = cache_runcmd(faux_args(Path(self.tmp.name), "arch"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_la_confiance_est_relue_en_premier(self):
        """Tout ce qui suit peut télécharger : la commande doit précéder."""
        self.assertTrue(self.lignes, "aucune commande générée")
        self.assertIn("trust extract-compat", self.lignes[0])

    def test_les_trois_variables_sont_ecrites(self):
        texte = "\n".join(self.lignes)
        for var in CACHE_ENV_VARS:
            self.assertIn(var, texte, f"{var} manque")

    def test_les_variables_visent_le_faisceau_pas_notre_ancre(self):
        """Viser le seul certificat du cache ferait perdre à pip toutes les
        autres autorités, et le casserait le jour où le cache disparaît."""
        _, _, faisceau = CACHE_TRUST["pacman"]
        texte = "\n".join(self.lignes[1:])
        self.assertIn(faisceau, texte)
        self.assertNotIn(CACHE_CERT_NAME, texte)

    def test_les_variables_vont_dans_etc_environment(self):
        """PAM lit /etc/environment pour TOUTE session ssh, non interactive
        comprise : c'est la seule voie qui atteint une commande distante."""
        for ligne in self.lignes[1:]:
            self.assertIn("/etc/environment", ligne)

    def test_ecriture_idempotente(self):
        """runcmd ne tourne qu'une fois par instance, mais un opérateur peut
        rejouer la commande : elle ne doit pas empiler les doublons."""
        for ligne in self.lignes[1:]:
            self.assertIn("grep -q", ligne)

    def test_aucune_commande_ne_peut_faire_echouer_le_boot(self):
        """Une VM qui ne démarre pas pour un confort est un mauvais échange."""
        self.assertIn("|| true", self.lignes[0])


class TestAccordAvecLeGo(unittest.TestCase):
    """La table Python et la table Go doivent dire la même chose.

    Sans ce test, la duplication dérive : un chemin corrigé d'un seul côté
    laisse soit un cache qui annonce le mauvais répertoire, soit une VM dont
    le certificat atterrit là où personne ne le lit.
    """

    def test_memes_chemins_et_memes_commandes(self):
        go = RULES_GO.read_text(encoding="utf-8")
        bloc = go[go.index("func GuestTrustCommand") :]
        trouve = dict(
            (famille, (dossier, commande, faisceau))
            for famille, dossier, commande, faisceau in re.findall(
                r'case "([a-z]+)":\s*\n(?:\s*//[^\n]*\n)*'
                r'\s*return "([^"]+)", "([^"]+)",\s*\n?\s*"([^"]+)", true',
                bloc,
            )
        )
        self.assertTrue(trouve, "aucune famille lue dans rules.go")
        self.assertEqual(
            trouve,
            {k: tuple(v) for k, v in CACHE_TRUST.items()},
            "les tables Python et Go ont divergé",
        )

    def test_memes_variables(self):
        go = RULES_GO.read_text(encoding="utf-8")
        for var in CACHE_ENV_VARS:
            self.assertIn(
                var, go, f"{var} est écrite côté VM mais absente du Go"
            )


if __name__ == "__main__":
    unittest.main()
