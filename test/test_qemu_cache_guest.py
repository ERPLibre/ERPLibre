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
    CACHE_SUDOERS,
    CACHE_TRUST,
    OFFLINE_ENV_VARS,
    cache_commands,
    cache_env_reload,
    cache_family,
    cache_files,
    cache_runcmd,
    commande_sudoers,
    langue_des_messages,
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
    """Le catalogue est vérifié par TestAucunSystemeNestOublie, plus bas.

    La liste qui était écrite ici nommait « linuxmint », qui n'est pas un
    système déployable, et taisait Proxmox, qui l'est : recopier le catalogue
    dans un test le fige au jour où on l'a recopié.
    """

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
        # Les écritures de variables, sans la confiance ni le sudoers.
        self.variables = [
            l for l in self.lignes[1:] if "/etc/environment" in l
        ]

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
        self.assertEqual(len(self.variables), len(CACHE_ENV_VARS))
        for var in CACHE_ENV_VARS:
            self.assertTrue(any(f"{var}=" in l for l in self.variables), var)

    def test_ecriture_idempotente(self):
        """runcmd ne tourne qu'une fois par instance, mais un opérateur peut
        rejouer la commande : elle ne doit pas empiler les doublons."""
        for ligne in self.variables:
            self.assertIn("grep -q", ligne)

    def test_aucune_commande_ne_peut_faire_echouer_le_boot(self):
        """Une VM qui ne démarre pas pour un confort est un mauvais échange."""
        self.assertIn("|| true", self.lignes[0])


class TestLesVariablesRelues(unittest.TestCase):
    """Une session ouverte avant cloud-init ne reçoit pas ce qu'il écrit.

    PAM lit /etc/environment à l'ouverture, et la commande distante qui attend
    cloud-init s'ouvre avant runcmd. La relecture est jouée ici dans un vrai
    shell, sur un fichier de test : c'est son EFFET qui compte, pas son texte.
    """

    def relire(self, contenu):
        """Lance la relecture sous « set -e » et rend (code, variables vues
        par un processus ENFANT, PATH de la session)."""
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as rep:
            fichier = Path(rep) / "environment"
            if contenu is not None:
                fichier.write_text(contenu, encoding="utf-8")
            script = (
                f"set -e; {cache_env_reload(str(fichier))};"
                ' env | grep -E "^(PIP_CERT|REQUESTS_CA_BUNDLE|NODE_EXTRA_CA_CERTS)="'
                ' || true; echo "PATH=$PATH"'
            )
            res = subprocess.run(
                ["sh", "-c", script],
                capture_output=True,
                text=True,
                env={"PATH": "/usr/bin:/bin"},
            )
        return res.returncode, res.stdout, res.stderr

    def test_les_variables_atteignent_un_processus_enfant(self):
        """npm est un ENFANT du shell : une variable posée sans « export »
        ne l'atteindrait pas."""
        faisceau = "/etc/ssl/certs/ca-certificates.crt"
        contenu = "".join(f"{v}={faisceau}\n" for v in CACHE_ENV_VARS)
        code, sortie, err = self.relire(contenu)
        self.assertEqual(code, 0, err)
        for var in CACHE_ENV_VARS:
            self.assertIn(f"{var}={faisceau}", sortie)

    def test_le_path_de_la_session_est_garde(self):
        """Relire le fichier entier remplacerait le PATH de la session."""
        code, sortie, err = self.relire(
            'PATH="/nulle/part"\nNODE_EXTRA_CA_CERTS=/x.crt\n'
        )
        self.assertEqual(code, 0, err)
        self.assertIn("PATH=/usr/bin:/bin", sortie)

    def test_sans_fichier_ni_variable_rien_n_echoue(self):
        """Une VM sans cache n'a ni les variables ni, parfois, le fichier :
        sous « set -e », l'installation ne doit pas s'arrêter là."""
        for contenu in (None, "LANG=C\n"):
            with self.subTest(contenu=contenu):
                code, _, err = self.relire(contenu)
                self.assertEqual(code, 0, err)


class TestLeHorsLigneCoupeLAuditNpm(unittest.TestCase):
    """Hors ligne, l'audit de npm interroge un service qu'aucun cache ne rejoue."""

    def setUp(self):
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def commandes(self, offline):
        args = faux_args(Path(self.tmp.name), "ubuntu")
        args.offline = offline
        return "\n".join(cache_commands(args))

    def test_une_vm_hors_ligne_recoit_l_audit_coupe(self):
        self.assertIn("NPM_CONFIG_AUDIT=false", self.commandes(True))

    def test_une_vm_en_ligne_garde_son_audit(self):
        self.assertNotIn("NPM_CONFIG_AUDIT", self.commandes(False))

    def test_la_variable_est_relue_apres_cloud_init(self):
        """Le « npm install » lancé sans sudo vit dans une session ouverte
        avant que cloud-init n'écrive la variable."""
        for var, _ in OFFLINE_ENV_VARS:
            self.assertIn(var, cache_env_reload())


class TestLesVariablesTraversentSudo(unittest.TestCase):
    """sudo remet l'environnement à zéro : sans « env_keep », une installation
    lancée par « sudo npm » rejette l'autorité du cache là où PAM ne relit pas
    /etc/environment pour sudo."""

    def setUp(self):
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def commande(self, offline=False, distro="debian"):
        args = faux_args(Path(self.tmp.name), distro)
        args.offline = offline
        lignes = [c for c in cache_commands(args) if "env_keep" in c]
        self.assertEqual(len(lignes), 1, "une seule écriture du sudoers")
        return lignes[0]

    def test_chaque_variable_du_cache_est_gardee(self):
        commande = self.commande()
        for var in CACHE_ENV_VARS:
            self.assertIn(var, commande)
        self.assertNotIn("NPM_CONFIG_AUDIT", commande)

    def test_hors_ligne_l_audit_coupe_traverse_aussi(self):
        for var, _ in OFFLINE_ENV_VARS:
            self.assertIn(var, self.commande(offline=True))

    def test_vient_apres_les_variables(self):
        """La confiance reste la première commande ; le sudoers suit."""
        args = faux_args(Path(self.tmp.name), "debian")
        commandes = cache_commands(args)
        self.assertIn("env_keep", commandes[-1])

    def test_le_fichier_ecrit_est_celui_que_sudo_lit(self):
        """sudo ignore un nom de sudoers.d qui porte un point : c'est ce qui
        rend le temporaire inoffensif, et interdit ce point au nom final."""
        nom_final = CACHE_SUDOERS.rsplit("/", 1)[1]
        self.assertNotIn(".", nom_final)
        self.assertTrue(CACHE_SUDOERS.startswith("/etc/sudoers.d/"))

    def test_le_fichier_est_verifie_avant_d_etre_pose(self):
        commande = commande_sudoers(["A"], "/etc/sudoers.d/essai")
        self.assertLess(
            commande.index("visudo -cf"),
            commande.index("mv /etc/sudoers.d/.essai /etc/sudoers.d/essai"),
        )
        self.assertIn("chmod 0440", commande)
        self.assertTrue(
            commande.rstrip("'").endswith("|| rm -f /etc/sudoers.d/.essai")
        )

    def test_le_contenu_ecrit_est_une_ligne_par_variable(self):
        """Joué dans un vrai shell, visudo remplacé : c'est le fichier produit
        qui compte, et son absence quand la vérification échoue."""
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as rep:
            bin_ = Path(rep) / "bin"
            bin_.mkdir()
            dossier = Path(rep) / "sudoers.d"
            dossier.mkdir()
            for verdict, attendu in (("0", True), ("1", False)):
                faux = bin_ / "visudo"
                faux.write_text(f"#!/bin/sh\nexit {verdict}\n")
                faux.chmod(0o755)
                fichier = dossier / "erplibre-cache"
                commande = commande_sudoers(
                    ["PIP_CERT", "NODE_EXTRA_CA_CERTS"], str(fichier)
                )
                res = subprocess.run(
                    ["sh", "-c", commande],
                    capture_output=True,
                    text=True,
                    env={"PATH": f"{bin_}:/usr/bin:/bin"},
                )
                with self.subTest(visudo=verdict):
                    self.assertEqual(res.returncode, 0, res.stderr)
                    self.assertEqual(fichier.exists(), attendu)
                    self.assertFalse((dossier / ".erplibre-cache").exists())
                    if attendu:
                        self.assertEqual(
                            fichier.read_text(),
                            "Defaults env_keep += PIP_CERT\n"
                            "Defaults env_keep += NODE_EXTRA_CA_CERTS\n",
                        )
                        fichier.unlink()


class TestLaLangueDesMessagesDuCache(unittest.TestCase):
    def test_l_option_du_deploiement_l_emporte(self):
        self.assertEqual(
            langue_des_messages(argparse.Namespace(lang="en")), "en"
        )
        self.assertEqual(
            langue_des_messages(argparse.Namespace(lang="FR")), "fr"
        )

    def test_une_valeur_inconnue_rend_le_francais(self):
        self.assertEqual(
            langue_des_messages(argparse.Namespace(lang="de")), "fr"
        )


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


class TestAucunSystemeNestOublie(unittest.TestCase):
    """Tout système déployable doit pouvoir recevoir l'autorité du cache.

    Le détournement s'applique à TOUT le pont : un invité qui ne reçoit pas
    l'autorité est intercepté quand même et échoue sur « self-signed
    certificate in certificate chain » à chaque téléchargement HTTPS. Le
    message ne dit rien d'une table incomplète, et c'est ainsi que Proxmox est
    resté sans autorité — la famille de paquets était recopiée à côté du
    catalogue, et la copie l'avait oublié.

    Le contrôle porte donc sur la PROPRIÉTÉ : le catalogue et la table des
    familles doivent couvrir les mêmes systèmes.
    """

    def test_chaque_systeme_du_catalogue_a_une_famille(self):
        from script.qemu.deploy_qemu import DISTROS, cache_family

        sans = sorted(d for d in DISTROS if not cache_family(d))
        self.assertEqual(
            sans,
            [],
            "ces systèmes seraient déployés SANS l'autorité du cache, et"
            f" chaque téléchargement HTTPS y échouerait : {sans}",
        )

    def test_chaque_famille_sait_poser_lautorite(self):
        from script.qemu.deploy_qemu import CACHE_TRUST, DISTROS, cache_family

        manquantes = sorted(
            {cache_family(d) for d in DISTROS} - set(CACHE_TRUST)
        )
        self.assertEqual(
            manquantes,
            [],
            f"familles sans commande de confiance : {manquantes}",
        )

    def test_la_famille_vient_du_catalogue_et_nest_pas_recopiee(self):
        """Deux tables qui disent la même chose dérivent : c'est ce qui a
        laissé Proxmox de côté."""
        from script.qemu.deploy_qemu import DISTRO_PKG, cache_family

        for d, attendue in DISTRO_PKG.items():
            self.assertEqual(cache_family(d), attendue, d)


if __name__ == "__main__":
    unittest.main()
