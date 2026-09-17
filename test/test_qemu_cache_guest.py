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

import yaml

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from script.qemu.deploy_qemu import (  # noqa: E402
    CACHE_CERT_NAME,
    CACHE_ENV_VARS,
    CACHE_SUDOERS,
    CACHE_TRUST,
    OFFLINE_BOOTCMD,
    OFFLINE_ENV_VARS,
    build_cloud_config,
    build_parser,
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
        # Le temporaire part toujours, et l'échec se DIT : muet, il se paie
        # plus tard sur un « self-signed certificate » que rien ne relie ici.
        self.assertIn("|| (rm -f /etc/sudoers.d/.essai; echo ", commande)

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


class TestLeHorsLigneNAttendPasLHeure(unittest.TestCase):
    """Une image qui attend la synchronisation NTP avant « cloud-final » ne
    démarre jamais son étape finale sans serveur de temps : ni clés d'hôte, ni
    ssh. Une VM déployée hors ligne lève cette attente dès bootcmd."""

    def config(self, *extra):
        args = build_parser().parse_args(
            ["--distro", "arch", "--hostname", "vm", *extra]
        )
        return yaml.safe_load(build_cloud_config(args, None, []))

    def test_une_vm_hors_ligne_arrete_l_attente(self):
        cmd = self.config("--offline").get("bootcmd") or []
        self.assertTrue(
            any("systemd-time-wait-sync" in c and "stop" in c for c in cmd),
            cmd,
        )

    def test_la_commande_ne_bloque_ni_n_echoue(self):
        """--no-block : bootcmd ne doit pas attendre un travail qui attend
        lui-même le réseau ; « || true » : une image sans l'unité continue."""
        for ligne in OFFLINE_BOOTCMD[1:]:
            self.assertIn("--no-block", ligne)
            self.assertTrue(ligne.rstrip().endswith("|| true"))

    def test_une_vm_en_ligne_garde_sa_synchronisation(self):
        """La levée n'a lieu QUE hors ligne.

        « Aucun bootcmd » l'a longtemps dit, parce que la levée était le seul.
        Le locale en pose un autre depuis — il génère la locale demandée avant
        que le module de cloud-init ne l'applique —, et l'absence GLOBALE ne
        prouve donc plus rien. C'est la levée nommément qui doit manquer, et
        c'est elle que cette classe garde."""
        cmd = self.config().get("bootcmd") or []
        aplati = " ".join(str(c) for c in cmd)
        self.assertNotIn("systemd-time-wait-sync", aplati)


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
        """Chaque famille du catalogue sait poser l'autorité, OU est
        explicitement soustraite au détournement.

        Le détournement porte sur tout le pont : une famille qui ne sait pas
        apprendre l'autorité et qu'on laisse passer n'échoue pas à
        l'installation du certificat — elle échoue sur CHAQUE téléchargement,
        avec un message qui ne dit rien de la cause.

        L'épreuve porte sur le COMPORTEMENT et non sur l'appartenance à une
        table : « nix » ne pose pas l'autorité dans un répertoire d'ancres —
        il n'en a pas — mais il la pose, par un fragment systemd. Compter les
        entrées de CACHE_TRUST l'aurait déclaré manquant alors qu'il est
        servi, et déclarerait manquante toute mécanique future.
        """
        import tempfile

        from script.qemu.deploy_qemu import (
            CACHE_SANS_AUTORITE,
            DISTROS,
            build_parser,
            cache_commands,
            cache_family,
        )

        with tempfile.NamedTemporaryFile(
            "w", suffix=".crt", delete=False
        ) as fh:
            fh.write("-----BEGIN CERTIFICATE-----\nZXNzYWk=\n")
            fh.write("-----END CERTIFICATE-----\n")
            ca = fh.name
        muettes = []
        for distro in DISTROS:
            if not cache_family(distro):
                continue
            if cache_family(distro) in CACHE_SANS_AUTORITE:
                continue
            args = build_parser().parse_args(
                ["--distro", distro, "--hostname", "x", "--cache-ca", ca]
            )
            if not cache_commands(args):
                muettes.append(distro)
        self.assertEqual(
            muettes,
            [],
            f"systèmes qui ne posent rien : {muettes}",
        )

    def test_une_famille_exemptee_nest_pas_aussi_dans_la_table(self):
        """Les deux listes s'excluent : une famille qui sait poser l'autorité
        n'a rien à faire parmi les exemptées, et l'y laisser soustrairait au
        cache une VM qui pouvait parfaitement en vivre."""
        from script.qemu.deploy_qemu import CACHE_SANS_AUTORITE, CACHE_TRUST

        self.assertEqual(set(), set(CACHE_TRUST) & CACHE_SANS_AUTORITE)

    def test_plus_aucun_systeme_du_catalogue_nest_soustrait(self):
        """L'exemption est le dernier recours, et plus personne n'y tombe.

        NixOS y était tant qu'on ne savait pas lui donner l'autorité : /etc
        est en lecture seule, et une déclaration arriverait après le premier
        téléchargement. Il l'a désormais par un fragment systemd, ce qui le
        fait ENTRER dans le cache au lieu de l'en soustraire — et sans cela le
        hors ligne lui était fermé, le magasin étant alors la seule source.
        """
        from script.qemu.deploy_qemu import DISTROS, cache_sans_autorite

        for distro in DISTROS:
            with self.subTest(distro=distro):
                self.assertFalse(cache_sans_autorite(distro))
        self.assertFalse(cache_sans_autorite("inconnue"))

    def test_la_famille_vient_du_catalogue_et_nest_pas_recopiee(self):
        """Deux tables qui disent la même chose dérivent : c'est ce qui a
        laissé Proxmox de côté."""
        from script.qemu.deploy_qemu import DISTRO_PKG, cache_family

        for d, attendue in DISTRO_PKG.items():
            self.assertEqual(cache_family(d), attendue, d)


class LeHorsLigneNeSousTraitPasUneDistributionSansMagasin(unittest.TestCase):
    """Les deux ne se combinent pas, et c'est dit AVANT.

    Hors ligne, l'amont est coupé et le magasin est la SEULE source.
    Soustraire au cache une distribution sans magasin de certificats ne la
    ferait pas télécharger en direct : cela ne lui laisserait RIEN. Et sans
    l'exception, chaque téléchargement bute sur un certificat inconnu. Les
    deux issues échouent — une heure plus tard, si personne ne le dit.
    """

    SRC = (RACINE / "script/qemu/deploy_qemu.py").read_text(encoding="utf-8")

    def _bloc(self):
        i = self.SRC.index("sans_magasin = cache_sans_autorite(")
        return self.SRC[i : i + 1400]

    def test_offline_is_tested_before_the_fallback(self):
        """L'ordre EST la correction : l'ancien code posait l'exception sans
        jamais regarder si l'amont était coupé."""
        bloc = self._bloc()
        self.assertLess(
            bloc.index('getattr(args, "offline", False)'),
            bloc.index("args.cache_bypass = True"),
        )

    def test_offline_never_exempts(self):
        bloc = self._bloc()
        avant = bloc[: bloc.index("args.cache_bypass = True")]
        self.assertNotIn("args.cache_bypass = True", avant)
        self.assertIn("elif sans_magasin", bloc)

    def test_the_dead_end_is_named(self):
        """Un refus qui ne dit pas pourquoi renvoie chercher dans la VM."""
        bloc = self._bloc()
        self.assertIn("Aucune source", bloc)


class NixApprendLAutoriteSansReconstruire(unittest.TestCase):
    """NixOS n'a pas d'ancre de confiance par fichier, et une déclaration
    arriverait après le premier téléchargement — la première reconstruction
    EST ce téléchargement.

    Mesuré sur une VM interceptée : une LECTURE passe par le client nix et se
    contente d'une variable de session, mais RÉALISER une dérivation passe
    par nix-daemon, qui ne la voit pas. Un fragment systemd l'atteint, et
    /run/systemd/system est un tmpfs — inscriptible quand /etc ne l'est pas.
    """

    def _args(self, distro="nixos"):
        import tempfile

        with tempfile.NamedTemporaryFile(
            "w", suffix=".crt", delete=False
        ) as fh:
            fh.write("-----BEGIN CERTIFICATE-----\nZXNzYWk=\n")
            fh.write("-----END CERTIFICATE-----\n")
        return build_parser().parse_args(
            ["--distro", distro, "--hostname", "x", "--cache-ca", fh.name]
        )

    def test_the_authority_lands_where_it_can_be_written(self):
        """/etc est généré depuis le store : y déposer échouerait."""
        from script.qemu.deploy_qemu import NIX_CA_DIR, cache_files

        chemins = [f[0] for f in cache_files(self._args())]
        self.assertTrue(chemins)
        for c in chemins:
            with self.subTest(chemin=c):
                self.assertTrue(c.startswith(NIX_CA_DIR))
                self.assertFalse(c.startswith("/etc/"))

    def test_the_bundle_keeps_the_system_authorities(self):
        """Donner la seule autorité du cache ferait cesser d'approuver tout
        le reste : le faisceau est une CONCATÉNATION."""
        from script.qemu.deploy_qemu import NIX_CA_SYSTEME, cache_commands

        joint = " ".join(cache_commands(self._args()))
        self.assertIn(NIX_CA_SYSTEME, joint)
        self.assertIn("cat ", joint)

    def test_the_daemon_is_reached_not_the_session(self):
        """La session suffit pour LIRE, jamais pour réaliser : c'est le démon
        qui télécharge alors, et seul un fragment l'atteint."""
        from script.qemu.deploy_qemu import NIX_DROPIN, cache_commands

        joint = " ".join(cache_commands(self._args()))
        self.assertIn(NIX_DROPIN, joint)
        self.assertIn("NIX_SSL_CERT_FILE", joint)
        self.assertIn("daemon-reload", joint)

    def test_nothing_needs_a_rebuild(self):
        """Tout l'enjeu : la première reconstruction est elle-même le premier
        téléchargement."""
        joint = " ".join(cache_commands(self._args()))
        self.assertNotIn("nixos-rebuild", joint)

    def test_the_other_families_are_untouched(self):
        """Elles ont un répertoire d'ancres et une commande qui le relit."""
        from script.qemu.deploy_qemu import NIX_DROPIN, cache_commands

        for distro in ("debian", "ubuntu", "fedora", "arch", "opensuse"):
            with self.subTest(distro=distro):
                joint = " ".join(cache_commands(self._args(distro)))
                self.assertNotIn(NIX_DROPIN, joint)
                self.assertIn("/etc/environment", joint)


class LesGestesSurvivententAuTransport(unittest.TestCase):
    """Les commandes du cache voyagent par deux transports, et chacun a ses
    caractères mortels.

    Le premier est le « runcmd » de cloud-init, un scalaire simple de YAML :
    un « : » suivi d'une espace, une accolade ou un crochet en tête y font
    lire autre chose qu'une commande. Le second est « sh -c '…' », que la
    moindre apostrophe referme — le shell distant meurt alors sur
    « unexpected EOF », loin de la ligne fautive.

    Aucun des deux ne se voit à la lecture du Python : la chaîne y est
    correcte, et c'est sa TRAVERSÉE qui échoue. D'où ces épreuves, une par
    transport, sur toutes les familles à la fois.
    """

    def setUp(self):
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _familles(self):
        """Une distribution par famille, nix compris — il est le seul dont
        les gestes ne viennent pas de CACHE_TRUST."""
        return ("debian", "ubuntu", "fedora", "arch", "opensuse", "nixos")

    def test_every_runcmd_line_survives_a_yaml_parse(self):
        for distro in self._familles():
            with self.subTest(distro=distro):
                lignes = cache_runcmd(faux_args(Path(self.tmp.name), distro))
                charge = yaml.safe_load("runcmd:\n" + "\n".join(lignes))
                self.assertEqual(
                    charge["runcmd"],
                    [l.removeprefix("  - ") for l in lignes],
                    "le YAML ne rend pas la commande telle qu'elle est écrite",
                )

    def test_every_command_survives_a_real_shell(self):
        """« sh -n » lit la commande sans rien exécuter : une quote non
        refermée s'y voit, un rm -rf ne s'y joue pas."""
        import subprocess

        for distro in self._familles():
            for commande in cache_commands(
                faux_args(Path(self.tmp.name), distro)
            ):
                with self.subTest(distro=distro, debut=commande[:40]):
                    res = subprocess.run(
                        ["sh", "-n", "-c", commande],
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(res.returncode, 0, res.stderr)


class LeSudoersAtteintVisudoLaOuIlEst(unittest.TestCase):
    """Un système déclaratif ne met pas sudo dans le PATH de cloud-init.

    Mesuré sur une VM : le « runcmd » hérite du PATH du service de
    cloud-init, vingt-six chemins du magasin dont AUCUN ne porte sudo, et
    /usr/bin/visudo n'existe pas non plus. La vérification échouait donc,
    le garde-fou effaçait le fichier au lieu de le poser, et sudo continuait
    de vider l'environnement — l'installation ne rendait plus qu'une
    répétition de refus de certificat.

    Le profil du système est le chemin que ces distributions garantissent ;
    les quatre familles impératives ne l'ont pas, et l'ajout n'y change rien.
    """

    PROFIL = "/run/current-system/sw/bin"

    def test_the_system_profile_is_on_the_path(self):
        self.assertIn(self.PROFIL, commande_sudoers(["A"]))

    def test_the_path_is_extended_not_replaced(self):
        """Remplacer le PATH perdrait echo, chmod et mv, qui viennent du
        magasin eux aussi et ne sont nulle part ailleurs."""
        self.assertIn(f"PATH=$PATH:{self.PROFIL}", commande_sudoers(["A"]))

    def test_a_failure_is_announced(self):
        """Muet, l'échec se paie plus tard sur un « self-signed certificate »
        que rien ne relie à ce geste."""
        self.assertIn("echo ", commande_sudoers(["A"]).split("||")[-1])

    def test_the_message_carries_none_of_the_deadly_characters(self):
        """L'apostrophe referme la commande, et les trois autres font lire au
        YAML autre chose qu'un scalaire simple."""
        from script.qemu.deploy_qemu import t_sudoers_manque

        message = t_sudoers_manque()
        self.assertTrue(message)
        for interdit in ("'", ": ", "{", "}", "[", "]"):
            with self.subTest(interdit=interdit):
                self.assertNotIn(interdit, message)


if __name__ == "__main__":
    unittest.main()
