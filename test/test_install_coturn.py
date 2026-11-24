#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'installateur coturn, fonction par fonction, sans root ni service.

Chaque fonction shell est extraite du script et jouee dans un bac a sable :
les commandes systeme (`apt-get`, `pacman`, `systemctl`, `chown`, `id`,
`turnadmin`...) y sont des bouchons qui notent leurs appels. Le compte de
controle est ecrit pour de vrai dans une base SQLite temporaire, par un
`sqlite3` bouchon qui execute la requete avec le module sqlite3 de Python,
puis relu et compare a la cle que calcule `turn_client`.
"""
import hashlib
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(RACINE, "script/install/install_coturn.sh")
sys.path.insert(0, os.path.join(RACINE, "script/todo"))

import turn_client  # noqa: E402

# Valeurs inventees : aucun de ces noms ni mots de passe n'existe ailleurs.
REALM = "turn.exemple.test"
MOT_DE_PASSE = "Pz7-controle-invente-41"
CONSTANTES = ("MARKER", "CALL_DIR", "TLS_DIR", "DB_DIR", "DB_FILE",
              "CHECK_USER", "OS_RELEASE", "DEBIAN_CONF", "ARCH_CONF",
              "DEFAULT_FILE", "APPLIED_FILE", "PENDING_FILE", "SYSTEMD_DIR")
TABLES_COTURN = {"turnusers_lt", "turn_secret", "allowed_peer_ip",
                 "denied_peer_ip", "turn_origin_to_realm",
                 "turn_realm_option", "oauth_key", "admin_user"}


def source():
    with open(SCRIPT, encoding="utf-8") as flux:
        return flux.read()


def extraire_fonction(nom):
    """Rend la fonction shell demandee, seule, executable dans un bac a sable.

    La definition est cherchee en debut de ligne (`nom() {`) : un
    commentaire qui cite le nom ne la remplace pas.
    """
    texte = source()
    trouve = re.search(r"^%s\(\) \{" % re.escape(nom), texte, re.M)
    if trouve is None:
        raise AssertionError("fonction absente de install_coturn.sh : %s" % nom)
    debut = trouve.start()
    fin = texte.index("\n}\n", debut) + 3
    return texte[debut:fin]


def fonctions(*noms):
    return "".join(extraire_fonction(nom) for nom in noms)


def constantes(**remplacements):
    """Les constantes que le script fixe en tete, telles qu'il les ecrit ;
    `remplacements` en redirige certaines vers un dossier temporaire."""
    texte = source()
    sortie = []
    for nom in CONSTANTES:
        ligne = re.search(r'^%s="[^"]*"\n' % nom, texte, re.M)
        if ligne is None:
            raise AssertionError("constante absente : %s" % nom)
        sortie.append(ligne.group(0))
    tableau = re.search(r"^DENIED_PEER_RANGES=\(\n.*?^\)\n", texte, re.M | re.S)
    if tableau is None:
        raise AssertionError("tableau absent : DENIED_PEER_RANGES")
    sortie.append(tableau.group(0))
    for nom, valeur in remplacements.items():
        sortie.append('%s="%s"\n' % (nom, valeur))
    return "".join(sortie)


ENTREES = (
    "TURN_REALM=%s\nTURN_PORT=3478\nTURN_TLS_PORT=5349\n"
    "TURN_MIN_PORT=49152\nTURN_MAX_PORT=49252\nTURN_CERT_FILE=\n"
    "TURN_KEY_FILE=\nTURN_EXTERNAL_IP=\nTURN_CHECK_PASSWORD='%s'\n"
    "TURN_GARDER_CONFIG=\nTURN_ALLOW_PRIVATE=\nTURN_ALT_TLS_PORT=\n"
    "TURN_AUTH=fixed\n"
    % (REALM, MOT_DE_PASSE))

# Les plages qu'un relais ne doit pas joindre par defaut, au format de
# denied-peer-ip (adresse, ou premiere-derniere).
PLAGES_REFUSEES = (
    "0.0.0.0-0.255.255.255",
    "10.0.0.0-10.255.255.255",
    "100.64.0.0-100.127.255.255",
    "127.0.0.0-127.255.255.255",
    "169.254.0.0-169.254.255.255",
    "172.16.0.0-172.31.255.255",
    "192.168.0.0-192.168.255.255",
    "::",
    "::1",
    "::ffff:0.0.0.0-::ffff:255.255.255.255",
    "64:ff9b::-64:ff9b::ffff:ffff",
    "fc00::-fdff:ffff:ffff:ffff:ffff:ffff:ffff:ffff",
    "fe80::-febf:ffff:ffff:ffff:ffff:ffff:ffff:ffff",
)

ENTETE = (
    "set -euo pipefail\n"
    "log() { echo \"$*\"; }\n"
    "die() { echo \"ERREUR: $*\" >&2; exit 1; }\n")


def jouer(enveloppe, env=None, timeout=30):
    """Lance `enveloppe` sous bash ; rend le CompletedProcess."""
    complet = dict(os.environ)
    complet.update(env or {})
    return subprocess.run(["bash", "-c", enveloppe], capture_output=True,
                          text=True, env=complet, timeout=timeout)


def lignes(chemin):
    if not os.path.exists(chemin):
        return []
    with open(chemin, encoding="utf-8") as flux:
        return flux.read().splitlines()


class TestConfiguration(unittest.TestCase):
    """`write_config` : le fichier que coturn lit, et rien d'identifiant."""

    def _ecrire(self, variables="", deja=None, avant=None):
        """`avant(dossier, conf)` prepare le dossier avant l'ecriture."""
        with tempfile.TemporaryDirectory() as dossier:
            conf = os.path.join(dossier, "turnserver.conf")
            journal = os.path.join(dossier, "appels")
            if deja is not None:
                with open(conf, "w") as flux:
                    flux.write(deja)
            if avant is not None:
                avant(dossier, conf)
            enveloppe = (
                ENTETE + constantes() + ENTREES + variables + "\n"
                "J=%s\n"
                "chown() { echo \"chown $*\" >> $J; }\n"
                "SERVICE_USER=turnserver\nSERVICE_GROUP=turnserver\n"
                "CONFIG_CHANGED=0\n" % journal
            ) + fonctions("has_cert", "refuse_linked_config",
                          "write_config") + (
                "write_config %s\necho \"CHANGED=$CONFIG_CHANGED\"\n" % conf)
            fait = jouer(enveloppe)
            texte = (open(conf).read()
                     if os.path.exists(conf) and not os.path.islink(conf)
                     else "")
            mode = (stat.S_IMODE(os.stat(conf).st_mode)
                    if os.path.exists(conf) else None)
            restes = sorted(os.listdir(dossier))
            self.victime = None
            victime = os.path.join(dossier, "victime")
            if os.path.exists(victime):
                with open(victime) as flux:
                    self.victime = flux.read()
            return fait, texte, mode, lignes(journal), restes

    @staticmethod
    def _victime(dossier):
        chemin = os.path.join(dossier, "victime")
        with open(chemin, "w") as flux:
            flux.write("intact\n")
        return chemin

    def test_une_configuration_en_lien_est_refusee(self):
        """Le fichier vise par un lien n'est pas celui que l'outil gere :
        rien n'est ecrit, ni le lien ni sa cible."""
        def lien(dossier, conf):
            os.symlink(self._victime(dossier), conf)
        fait, _, _, _, restes = self._ecrire(avant=lien)
        self.assertNotEqual(fait.returncode, 0, fait.stdout)
        self.assertIn("lien", fait.stderr)
        self.assertEqual(self.victime, "intact\n")
        self.assertEqual(restes, ["turnserver.conf", "victime"])

    def test_le_fichier_temporaire_n_a_pas_de_nom_previsible(self):
        """Un lien pose d'avance au nom d'un fichier temporaire fixe ferait
        ecrire root dans sa cible : mktemp cree un nom neuf, exclusif."""
        def piege(dossier, conf):
            os.symlink(self._victime(dossier), conf + ".erplibre-new")
        fait, texte, _, _, _ = self._ecrire(avant=piege)
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertEqual(self.victime, "intact\n")
        self.assertTrue(texte.startswith("# erplibre-call: managed\n"), texte)

    def test_sans_certificat_ni_tls_ni_certificat(self):
        fait, texte, _, _, _ = self._ecrire()
        self.assertEqual(fait.returncode, 0, fait.stderr)
        cles = [ligne.split("=")[0] for ligne in texte.splitlines()]
        self.assertNotIn("tls-listening-port", cles)
        self.assertNotIn("cert", cles)
        self.assertNotIn("pkey", cles)
        # Le port TLS n'est pas ouvert sans certificat a y servir.
        self.assertIn("no-tls", cles)

    def test_les_lignes_attendues(self):
        fait, texte, _, _, _ = self._ecrire()
        self.assertEqual(fait.returncode, 0, fait.stderr)
        contenu = texte.splitlines()
        self.assertEqual(contenu[0], "# erplibre-call: managed")
        for attendue in ("listening-port=3478", "min-port=49152",
                         "max-port=49252", "fingerprint", "lt-cred-mech",
                         "realm=" + REALM,
                         "userdb=/var/lib/erplibre-call/turndb",
                         "no-cli", "no-multicast-peers"):
            self.assertIn(attendue, contenu)
        self.assertFalse([c for c in contenu if c.startswith("external-ip")])

    def test_aucun_identifiant_dans_la_configuration(self):
        """Les comptes vivent dans la base ; use-auth-secret desactiverait
        le compte de controle long terme."""
        for variables in ("", "TURN_CERT_FILE=/c.pem\nTURN_KEY_FILE=/k.pem"):
            fait, texte, _, _, _ = self._ecrire(variables)
            self.assertEqual(fait.returncode, 0, fait.stderr)
            for interdit in ("user=", "static-auth-secret", "use-auth-secret",
                             MOT_DE_PASSE):
                self.assertNotIn(interdit, texte)

    def test_mode_secret_use_auth_secret_au_lieu_de_lt_cred_mech(self):
        """coturn 4.6 ne melange pas les deux : avec use-auth-secret, tout
        compte long terme est refuse."""
        fait, texte, _, _, _ = self._ecrire("TURN_AUTH=secret")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        contenu = texte.splitlines()
        self.assertIn("use-auth-secret", contenu)
        self.assertNotIn("lt-cred-mech", contenu)
        # Les secrets vivent dans la base, jamais dans la configuration.
        self.assertFalse([c for c in contenu
                          if c.startswith("static-auth-secret")])
        self.assertLess(contenu.index("fingerprint"),
                        contenu.index("use-auth-secret"))
        self.assertLess(contenu.index("use-auth-secret"),
                        contenu.index("realm=" + REALM))

    def test_mode_fixe_lt_cred_mech(self):
        for variables in ("", "TURN_AUTH=fixed"):
            with self.subTest(variables=variables):
                fait, texte, _, _, _ = self._ecrire(variables)
                self.assertEqual(fait.returncode, 0, fait.stderr)
                self.assertIn("lt-cred-mech", texte.splitlines())
                self.assertNotIn("use-auth-secret", texte)

    def test_plages_privees_refusees_par_defaut(self):
        """Sans accord explicite, le relais ne sert pas de passerelle vers
        le reseau local de l'hote, sa boucle locale ni ses voisins."""
        fait, texte, _, _, _ = self._ecrire()
        self.assertEqual(fait.returncode, 0, fait.stderr)
        refusees = [ligne.split("=", 1)[1] for ligne in texte.splitlines()
                    if ligne.startswith("denied-peer-ip=")]
        self.assertEqual(refusees, list(PLAGES_REFUSEES))

    def test_plages_privees_permises_seulement_sur_demande(self):
        fait, texte, _, _, _ = self._ecrire("TURN_ALLOW_PRIVATE=1")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertNotIn("denied-peer-ip", texte)
        for valeur in ("0", ""):
            with self.subTest(valeur=valeur):
                fait, texte, _, _, _ = self._ecrire(
                    "TURN_ALLOW_PRIVATE=%s" % valeur)
                self.assertIn("denied-peer-ip=10.0.0.0-10.255.255.255",
                              texte.splitlines())

    def test_avec_certificat(self):
        fait, texte, _, _, _ = self._ecrire(
            "TURN_CERT_FILE=/c.pem\nTURN_KEY_FILE=/k.pem")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        contenu = texte.splitlines()
        self.assertIn("tls-listening-port=5349", contenu)
        self.assertIn("cert=/etc/erplibre-call/tls/turn.crt", contenu)
        self.assertIn("pkey=/etc/erplibre-call/tls/turn.key", contenu)
        self.assertNotIn("no-tls", contenu)

    def test_tls_sur_le_port_alternatif_au_lieu_du_port_tls(self):
        """coturn ne sert TLS que sur un port : TURN_ALT_TLS_PORT remplace
        TURN_TLS_PORT, il ne s'y ajoute pas."""
        fait, texte, _, _, _ = self._ecrire(
            "TURN_CERT_FILE=/c.pem\nTURN_KEY_FILE=/k.pem\n"
            "TURN_ALT_TLS_PORT=443")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        contenu = texte.splitlines()
        self.assertEqual(
            [c for c in contenu if c.startswith("tls-listening-port")],
            ["tls-listening-port=443"])
        self.assertFalse([c for c in contenu
                          if c.startswith("alt-tls-listening-port")])
        self.assertIn("cert=/etc/erplibre-call/tls/turn.crt", contenu)

    def test_ports_et_adresse_externe_choisis(self):
        fait, texte, _, _, _ = self._ecrire(
            "TURN_PORT=3479\nTURN_MIN_PORT=50000\nTURN_MAX_PORT=50100\n"
            "TURN_EXTERNAL_IP=198.51.100.7")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        contenu = texte.splitlines()
        self.assertIn("listening-port=3479", contenu)
        self.assertIn("min-port=50000", contenu)
        self.assertIn("max-port=50100", contenu)
        self.assertIn("external-ip=198.51.100.7", contenu)

    def test_proprietaire_et_droits(self):
        fait, _, mode, appels, restes = self._ecrire()
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertEqual(mode, 0o640)
        self.assertTrue([a for a in appels
                         if a.startswith("chown root:turnserver ")], appels)
        # Le fichier temporaire ne reste pas a cote.
        self.assertEqual(restes, ["appels", "turnserver.conf"])

    def test_meme_contenu_rien_a_redemarrer(self):
        fait, texte, _, _, _ = self._ecrire()
        self.assertIn("CHANGED=1", fait.stdout)
        refait, retexte, _, _, _ = self._ecrire(deja=texte)
        self.assertEqual(refait.returncode, 0, refait.stderr)
        self.assertIn("CHANGED=0", refait.stdout)
        self.assertEqual(retexte, texte)

    def test_cible_conteneur_journal_sur_la_sortie_standard(self):
        """coturn 4.18 en conteneur : le journal part sur la sortie
        standard, lue par le moteur, et les deux lignes que 4.18 ne
        connait plus disparaissent."""
        for variables in ("", "TURN_CERT_FILE=/c.pem\nTURN_KEY_FILE=/k.pem"):
            with self.subTest(variables=variables):
                fait, texte, mode, appels, _ = self._ecrire(
                    variables + "\nTURN_TARGET=container")
                self.assertEqual(fait.returncode, 0, fait.stderr)
                contenu = texte.splitlines()
                self.assertIn("log-file=stdout", contenu)
                for absente in ("syslog", "no-dtls",
                                "no-stun-backward-compatibility"):
                    self.assertNotIn(absente, contenu)
                self.assertEqual(contenu[-3:], [
                    "log-file=stdout", "no-rfc5780",
                    "response-origin-only-with-rfc5780"])
                self.assertEqual("no-tls" in contenu, variables == "")
                self.assertEqual(mode, 0o640)
                self.assertTrue([a for a in appels
                                 if a.startswith("chown root:turnserver ")])

    def test_cible_paquets_explicite_identique_au_defaut(self):
        _, defaut, _, _, _ = self._ecrire()
        fait, explicite, _, _, _ = self._ecrire("TURN_TARGET=packages")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertEqual(explicite, defaut)
        self.assertIn("syslog", defaut.splitlines())
        self.assertIn("no-dtls", defaut.splitlines())


CERT = "TURN_CERT_FILE=@D@/c.pem\nTURN_KEY_FILE=@D@/k.pem\n"


class TestEntrees(unittest.TestCase):
    """`check_inputs` arrete le script avant toute installation."""

    def _verifier(self, variables, fichiers=False):
        with tempfile.TemporaryDirectory() as dossier:
            if fichiers:
                for nom in ("c.pem", "k.pem"):
                    open(os.path.join(dossier, nom), "w").close()
            enveloppe = (ENTETE + ENTREES + variables.replace("@D@", dossier)
                         + "\n" + fonctions("valid_port", "has_cert", "check_inputs")
                         + "check_inputs\necho OK\n")
            return jouer(enveloppe)

    def test_entrees_par_defaut_acceptees(self):
        fait = self._verifier("")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertIn("OK", fait.stdout)

    def test_refus(self):
        for variables in (
                "TURN_REALM=",
                "TURN_REALM='turn.exemple.test\nuser=x'",
                "TURN_REALM=\"o'brien.exemple.test\"",
                "TURN_PORT=abc",
                "TURN_PORT=70000",
                "TURN_MIN_PORT=50000\nTURN_MAX_PORT=40000",
                "TURN_CERT_FILE=@D@/c.pem",
                "TURN_KEY_FILE=@D@/k.pem",
                "TURN_CERT_FILE=@D@/absent.pem\nTURN_KEY_FILE=@D@/k.pem",
                "TURN_EXTERNAL_IP='198.51.100.7\nuser=x'",
                "TURN_ALLOW_PRIVATE=oui",
                "TURN_AUTH=autre",
                "TURN_AUTH=",
                # TLS sur un port alternatif : seulement avec un
                # certificat, sur un port valide distinct des autres.
                "TURN_ALT_TLS_PORT=443",
                CERT + "TURN_ALT_TLS_PORT=abc",
                CERT + "TURN_ALT_TLS_PORT=0",
                CERT + "TURN_ALT_TLS_PORT=3478",
                CERT + "TURN_ALT_TLS_PORT=5349"):
            with self.subTest(variables=variables):
                fait = self._verifier(variables, fichiers=True)
                self.assertNotEqual(fait.returncode, 0, fait.stdout)
                self.assertNotIn("OK", fait.stdout)

    def test_sans_mot_de_passe_accepte(self):
        """Le mot de passe de controle naît sur l'hote : l'appelant n'en
        donne aucun."""
        fait = self._verifier("TURN_CHECK_PASSWORD=")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertIn("OK", fait.stdout)

    def test_certificat_et_cle_presents_acceptes(self):
        fait = self._verifier(
            "TURN_CERT_FILE=@D@/c.pem\nTURN_KEY_FILE=@D@/k.pem", fichiers=True)
        self.assertEqual(fait.returncode, 0, fait.stderr)

    def test_port_alternatif_avec_certificat_accepte(self):
        fait = self._verifier(CERT + "TURN_ALT_TLS_PORT=443", fichiers=True)
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertIn("OK", fait.stdout)

    def test_mode_secret_accepte(self):
        fait = self._verifier("TURN_AUTH=secret")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertIn("OK", fait.stdout)

    def test_port_alternatif_sans_certificat_nomme_la_raison(self):
        fait = self._verifier("TURN_ALT_TLS_PORT=443", fichiers=True)
        self.assertNotEqual(fait.returncode, 0)
        self.assertIn("TURN_ALT_TLS_PORT", fait.stderr)

    def test_cible_conteneur_avec_compte_acceptee(self):
        fait = self._verifier(
            "TURN_TARGET=container\nTURN_SERVICE_USER=erplibre-coturn")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertIn("OK", fait.stdout)

    def test_cible_refusee_en_nommant_la_variable(self):
        for variables, nommee in (
                ("TURN_TARGET=autre", "TURN_TARGET"),
                ("TURN_TARGET=", "TURN_TARGET"),
                ("TURN_TARGET=container", "TURN_SERVICE_USER"),
                ("TURN_TARGET=container\nTURN_SERVICE_USER=",
                 "TURN_SERVICE_USER"),
                # Un conteneur ne tourne jamais en root.
                ("TURN_TARGET=container\nTURN_SERVICE_USER=root",
                 "TURN_SERVICE_USER"),
                ("TURN_TARGET=container\nTURN_SERVICE_USER='a b'",
                 "TURN_SERVICE_USER"),
                ("TURN_TARGET=container\nTURN_SERVICE_USER=Majuscule",
                 "TURN_SERVICE_USER"),
                # Paquets : le compte vient du paquet, pas de l'appelant.
                ("TURN_TARGET=packages\nTURN_SERVICE_USER=erplibre-coturn",
                 "TURN_SERVICE_USER"),
                ("TURN_SERVICE_USER=erplibre-coturn", "TURN_SERVICE_USER")):
            with self.subTest(variables=variables):
                fait = self._verifier(variables)
                self.assertNotEqual(fait.returncode, 0, fait.stdout)
                self.assertNotIn("OK", fait.stdout)
                self.assertIn(nommee, fait.stderr)


class TestSysteme(unittest.TestCase):
    """`detect_os`, `family`, `unit_name`, `service_user`, `config_path`."""

    def _famille(self, os_id, os_like=""):
        enveloppe = (ENTETE + "OS=%s\nOS_LIKE='%s'\n" % (os_id, os_like)
                     + fonctions("family") + "family\n")
        return jouer(enveloppe)

    def test_familles_supportees(self):
        for os_id, os_like, attendue in (
                ("debian", "", "debian"), ("ubuntu", "debian", "debian"),
                ("linuxmint", "ubuntu debian", "debian"),
                ("arch", "", "arch"), ("manjaro", "arch", "arch"),
                ("inventeos", "arch", "arch")):
            with self.subTest(os_id=os_id):
                fait = self._famille(os_id, os_like)
                self.assertEqual(fait.returncode, 0, fait.stderr)
                self.assertEqual(fait.stdout.strip(), attendue)

    def test_fedora_refuse_en_nommant_les_supportes(self):
        fait = self._famille("fedora")
        self.assertNotEqual(fait.returncode, 0)
        self.assertEqual(fait.stdout, "")
        for nom in ("fedora", "Debian", "Ubuntu", "Arch"):
            self.assertIn(nom, fait.stderr)

    def test_detect_os_lit_os_release(self):
        with tempfile.TemporaryDirectory() as dossier:
            chemin = os.path.join(dossier, "os-release")
            with open(chemin, "w") as flux:
                flux.write('NAME="Inventee"\nID=ubuntu\nID_LIKE=debian\n'
                           'VERSION_ID="24.04"\n')
            enveloppe = (ENTETE + "OS_RELEASE=%s\n" % chemin
                         + fonctions("detect_os")
                         + "detect_os\necho \"[$OS] [$OS_LIKE]\"\n")
            fait = jouer(enveloppe)
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertIn("[ubuntu] [debian]", fait.stdout)

    def _systeme(self, famille, unite_texte, appel):
        with tempfile.TemporaryDirectory() as dossier:
            texte = os.path.join(dossier, "unite")
            with open(texte, "w") as flux:
                flux.write(unite_texte)
            enveloppe = (
                ENTETE + constantes() + "FAMILY=%s\nUNIT=x\n" % famille
                + "systemctl() { [ \"$1\" = cat ] && cat %s; }\n" % texte
                + fonctions("unit_name", "unit_text", "service_user",
                            "config_path") + appel + "\n")
            return jouer(enveloppe)

    def test_unite_par_famille(self):
        self.assertEqual(self._systeme("debian", "", "unit_name").stdout,
                         "coturn\n")
        self.assertEqual(self._systeme("arch", "", "unit_name").stdout,
                         "turnserver\n")

    def test_compte_de_service(self):
        unite = ("[Service]\nUser=turnsrv-invente\n"
                 "ExecStart=/usr/bin/turnserver -c /etc/turnserver/turnserver.conf\n")
        self.assertEqual(self._systeme("arch", unite, "service_user").stdout,
                         "turnsrv-invente\n")
        self.assertEqual(self._systeme("arch", "", "service_user").stdout,
                         "turnserver\n")
        self.assertEqual(self._systeme("debian", unite,
                                       "service_user").stdout,
                         "turnserver\n")

    def test_chemin_de_configuration(self):
        unite = ("[Service]\nExecStart=/usr/bin/turnserver -c "
                 "/etc/inventee/turn.conf --pidfile=\n")
        self.assertEqual(self._systeme("arch", unite, "config_path").stdout,
                         "/etc/inventee/turn.conf\n")
        self.assertEqual(self._systeme("debian", "", "config_path").stdout,
                         "/etc/turnserver.conf\n")
        self.assertEqual(self._systeme("arch", "", "config_path").stdout,
                         "/etc/turnserver/turnserver.conf\n")


class TestPaquets(unittest.TestCase):
    def _installer(self, famille, presents=False):
        with tempfile.TemporaryDirectory() as dossier:
            journal = os.path.join(dossier, "appels")
            enveloppe = (
                ENTETE + "FAMILY=%s\nJ=%s\n" % (famille, journal)
                + "apt-get() { echo \"apt-get $*\" >> $J; }\n"
                "pacman() {\n"
                "  echo \"pacman $*\" >> $J\n"
                "  [ \"$1\" != -Q ] || [ %d = 1 ]\n"
                "}\n" % (1 if presents else 0)
                + "dpkg-query() {\n"
                "  [ %d = 1 ] || return 1\n"
                "  echo 'install ok installed'; echo 'install ok installed'\n"
                "}\n" % (1 if presents else 0)
                + "dpkg() { echo \"dpkg $* FRONTEND=$DEBIAN_FRONTEND\" >> $J; }\n"
                + fonctions("packages_present", "install_packages")
                + "install_packages\n")
            fait = jouer(enveloppe)
            return fait, lignes(journal)

    def test_debian(self):
        fait, appels = self._installer("debian")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        installe = [a for a in appels if a.startswith("apt-get")
                    and " install " in a]
        self.assertEqual(len(installe), 1, appels)
        self.assertTrue(installe[0].endswith(" coturn sqlite3"), installe)
        self.assertIn("-y", installe[0].split())
        self.assertFalse([a for a in appels if a.startswith("pacman")])

    def test_debian_une_operation_dpkg_coupee_est_reprise(self):
        """Un ssh coupe pendant apt laisse dpkg interrompu, et apt-get
        refuse alors toute installation : la reprise passe avant, sans
        question au terminal."""
        fait, appels = self._installer("debian")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        reprise = [i for i, a in enumerate(appels)
                   if a.startswith("dpkg --configure -a")]
        self.assertEqual(len(reprise), 1, appels)
        self.assertIn("--force-confold", appels[reprise[0]])
        self.assertIn("FRONTEND=noninteractive", appels[reprise[0]])
        installe = [i for i, a in enumerate(appels)
                    if a.startswith("apt-get") and " install " in a]
        self.assertLess(reprise[0], installe[0])

    def test_arch(self):
        fait, appels = self._installer("arch")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertIn("pacman -S --noconfirm --needed coturn sqlite", appels)
        self.assertFalse([a for a in appels if a.startswith("apt-get")])
        self.assertFalse([a for a in appels if a.startswith("dpkg")])

    def test_deja_installes_rien_n_est_mis_a_jour(self):
        for famille in ("debian", "arch"):
            with self.subTest(famille=famille):
                fait, appels = self._installer(famille, presents=True)
                self.assertEqual(fait.returncode, 0, fait.stderr)
                self.assertFalse([a for a in appels
                                  if a.startswith("apt-get")
                                  or a.startswith("pacman -S")
                                  or a.startswith("dpkg")], appels)

    def _sqlite(self, famille, present=False):
        """`install_sqlite`, la cible conteneur : coturn vient de l'image,
        l'hote ne recoit que le client SQLite."""
        with tempfile.TemporaryDirectory() as dossier:
            journal = os.path.join(dossier, "appels")
            enveloppe = (
                ENTETE + "FAMILY=%s\nJ=%s\n" % (famille, journal)
                + "apt-get() { echo \"apt-get $*\" >> $J; }\n"
                "pacman() {\n"
                "  echo \"pacman $*\" >> $J\n"
                "  [ \"$1\" != -Q ] || [ %d = 1 ]\n"
                "}\n" % (1 if present else 0)
                + "dpkg-query() {\n"
                "  echo \"dpkg-query $*\" >> $J\n"
                "  [ %d = 1 ] || return 1\n"
                "  echo 'install ok installed'\n"
                "}\n" % (1 if present else 0)
                + "dpkg() { echo \"dpkg $* FRONTEND=$DEBIAN_FRONTEND\" >> $J; }\n"
                + fonctions("install_sqlite") + "install_sqlite\n")
            fait = jouer(enveloppe)
            return fait, lignes(journal)

    def test_conteneur_debian_sqlite3_seul(self):
        fait, appels = self._sqlite("debian")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        installe = [a for a in appels if a.startswith("apt-get")
                    and " install " in a]
        self.assertEqual(len(installe), 1, appels)
        self.assertTrue(installe[0].endswith("--force-confold sqlite3"),
                        installe)
        self.assertNotIn("coturn", " ".join(appels))
        reprise = [i for i, a in enumerate(appels)
                   if a.startswith("dpkg --configure -a")]
        self.assertEqual(len(reprise), 1, appels)
        self.assertIn("FRONTEND=noninteractive", appels[reprise[0]])
        self.assertLess(reprise[0], appels.index(installe[0]))

    def test_conteneur_arch_sqlite_seul(self):
        fait, appels = self._sqlite("arch")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertIn("pacman -S --noconfirm --needed sqlite", appels)
        self.assertNotIn("coturn", " ".join(appels))

    def test_conteneur_sqlite_deja_la_rien_n_est_mis_a_jour(self):
        for famille in ("debian", "arch"):
            with self.subTest(famille=famille):
                fait, appels = self._sqlite(famille, present=True)
                self.assertEqual(fait.returncode, 0, fait.stderr)
                self.assertFalse([a for a in appels
                                  if a.startswith("apt-get")
                                  or a.startswith("pacman -S")
                                  or a.startswith("dpkg ")], appels)


class TestDefaut(unittest.TestCase):
    """`enable_default` : /etc/default/coturn sur Debian, s'il existe."""

    def _activer(self, contenu, famille="debian"):
        with tempfile.TemporaryDirectory() as dossier:
            chemin = os.path.join(dossier, "coturn")
            if contenu is not None:
                with open(chemin, "w") as flux:
                    flux.write(contenu)
            enveloppe = (ENTETE + "FAMILY=%s\nDEFAULT_FILE=%s\n"
                         % (famille, chemin)
                         + fonctions("enable_default") + "enable_default\n")
            fait = jouer(enveloppe)
            texte = open(chemin).read() if os.path.exists(chemin) else None
            return fait, texte

    def test_ligne_commentee_activee(self):
        fait, texte = self._activer("# Commentaire\n#TURNSERVER_ENABLED=1\n")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertEqual(texte, "# Commentaire\nTURNSERVER_ENABLED=1\n")

    def test_ligne_absente_ajoutee(self):
        _, texte = self._activer("# Commentaire\n")
        self.assertEqual(texte, "# Commentaire\nTURNSERVER_ENABLED=1\n")

    def test_relance_identique(self):
        _, texte = self._activer("TURNSERVER_ENABLED=1\n")
        self.assertEqual(texte, "TURNSERVER_ENABLED=1\n")

    def test_fichier_absent_non_cree(self):
        fait, texte = self._activer(None)
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertIsNone(texte)

    def test_arch_non_concerne(self):
        _, texte = self._activer("#TURNSERVER_ENABLED=1\n", famille="arch")
        self.assertEqual(texte, "#TURNSERVER_ENABLED=1\n")


BOUCHON_SQLITE = r'''#!%(python)s
"""sqlite3 bouchon : note son argv, execute la requete lue sur stdin."""
import os
import sqlite3
import sys

with open(os.environ["STUB_LOG"], "a") as journal:
    journal.write("sqlite3 " + " ".join(sys.argv[1:]) + "\n")
arguments = sys.argv[1:]
base = None
i = 0
while i < len(arguments):
    if arguments[i] == "-init":
        i += 2
        continue
    if arguments[i].startswith("-"):
        i += 1
        continue
    base = arguments[i]
    break
requete = "\n".join(ligne for ligne in sys.stdin.read().splitlines()
                    if not ligne.startswith("."))
with open(os.environ["STUB_SQL"], "a") as copie:
    copie.write(requete + "\n")
connexion = sqlite3.connect(base, isolation_level=None)
connexion.executescript(requete)
connexion.close()
'''

# Note l'argv puis execute la vraie commande, pour que le calcul reste juste.
BOUCHON_RELAIS = '#!/bin/sh\necho "%(nom)s $*" >> "$STUB_LOG"\nexec %(vrai)s "$@"\n'

# runuser -u <compte> -- <commande>... : note l'argv, lance la commande.
BOUCHON_RUNUSER = ('#!/bin/sh\necho "runuser $*" >> "$STUB_LOG"\n'
                   'while [ "$1" != "--" ]; do shift; done\nshift\n'
                   'exec "$@"\n')

BOUCHON_JOURNAL = '#!/bin/sh\necho "%(nom)s $*" >> "$STUB_LOG"\n'


class TestCompteDeControle(unittest.TestCase):
    """`ensure_check_user` : la ligne de la base, et le mot de passe hors de
    tout argv."""

    def _poser(self, dossier, realm=REALM, mot_de_passe=MOT_DE_PASSE,
               sqlite=BOUCHON_SQLITE):
        bouchons = os.path.join(dossier, "bin")
        os.makedirs(bouchons, exist_ok=True)
        ecrits = {
            "sqlite3": sqlite % {"python": sys.executable},
            "runuser": BOUCHON_RUNUSER,
            "turnadmin": BOUCHON_JOURNAL % {"nom": "turnadmin"},
        }
        for nom in ("md5sum", "cut", "sha256sum", "openssl", "head",
                    "base64", "tr"):
            vrai = shutil.which(nom)
            if vrai:
                ecrits[nom] = BOUCHON_RELAIS % {"nom": nom, "vrai": vrai}
        for nom, contenu in ecrits.items():
            chemin = os.path.join(bouchons, nom)
            with open(chemin, "w") as flux:
                flux.write(contenu)
            os.chmod(chemin, 0o755)
        base = os.path.join(dossier, "turndb")
        enveloppe = (
            ENTETE + constantes(DB_FILE=base) + ENTREES
            + "TURN_REALM=%s\nTURN_CHECK_PASSWORD='%s'\n"
              "SERVICE_USER=turnserver\n" % (realm, mot_de_passe)
            + fonctions("schema_sql", "ensure_check_user")
            + "ensure_check_user\n")
        env = {"PATH": bouchons + os.pathsep + os.environ["PATH"],
               "STUB_LOG": os.path.join(dossier, "argv"),
               "STUB_SQL": os.path.join(dossier, "sql")}
        fait = jouer(enveloppe, env)
        return fait, base, lignes(os.path.join(dossier, "argv"))

    def _rangs(self, base):
        connexion = sqlite3.connect(base)
        try:
            return connexion.execute(
                "select realm, name, hmackey from turnusers_lt").fetchall()
        finally:
            connexion.close()

    def test_la_cle_est_celle_de_turn_client(self):
        with tempfile.TemporaryDirectory() as dossier:
            fait, base, _ = self._poser(dossier)
            self.assertEqual(fait.returncode, 0, fait.stderr)
            attendue = turn_client.long_term_key(
                "erplibre-check", REALM, MOT_DE_PASSE).hex()
            self.assertEqual(self._rangs(base),
                             [(REALM, "erplibre-check", attendue)])

    def test_schema_de_coturn(self):
        with tempfile.TemporaryDirectory() as dossier:
            fait, base, _ = self._poser(dossier)
            self.assertEqual(fait.returncode, 0, fait.stderr)
            connexion = sqlite3.connect(base)
            noms = {r[0] for r in connexion.execute(
                "select name from sqlite_master where type='table'")}
            connexion.close()
            self.assertEqual(noms, TABLES_COTURN)

    def test_relance_et_changement_de_realm_une_seule_ligne(self):
        with tempfile.TemporaryDirectory() as dossier:
            self._poser(dossier)
            fait, base, _ = self._poser(dossier)
            self.assertEqual(fait.returncode, 0, fait.stderr)
            self.assertEqual(len(self._rangs(base)), 1)
            fait, base, _ = self._poser(dossier, realm="autre.exemple.test",
                                        mot_de_passe="Autre-invente-9")
            self.assertEqual(fait.returncode, 0, fait.stderr)
            attendue = turn_client.long_term_key(
                "erplibre-check", "autre.exemple.test",
                "Autre-invente-9").hex()
            self.assertEqual(self._rangs(base), [
                ("autre.exemple.test", "erplibre-check", attendue)])

    def test_le_mot_de_passe_ne_passe_dans_aucun_argv(self):
        with tempfile.TemporaryDirectory() as dossier:
            fait, base, argv = self._poser(dossier)
            self.assertEqual(fait.returncode, 0, fait.stderr)
            self.assertTrue(argv, "aucune commande notee")
            cle = turn_client.long_term_key(
                "erplibre-check", REALM, MOT_DE_PASSE).hex()
            for ligne in argv:
                # turnadmin est le seul a qui le contrat le permettrait ;
                # le script ne le lui passe pas non plus.
                self.assertNotIn(MOT_DE_PASSE, ligne)
                # La cle long terme vaut le mot de passe pour coturn.
                self.assertNotIn(cle, ligne)
            for sortie in (fait.stdout, fait.stderr):
                self.assertNotIn(MOT_DE_PASSE, sortie)
                self.assertNotIn(cle, sortie)

    def test_la_sortie_du_compte_ne_forge_aucun_marqueur(self):
        """Ce qu'imprime sqlite3 sous le compte de coturn, qui possede la
        base, arrive en retrait : aucune ligne ne commence par « @@ »."""
        bavard = BOUCHON_SQLITE.replace(
            "import sys\n",
            "import sys\nprint('@@ACCOUNT_ADDED ntfy')\n"
            "print('@@ENGINE_PACKAGE x', file=sys.stderr)\n", 1)
        with tempfile.TemporaryDirectory() as dossier:
            fait, _, _ = self._poser(dossier, sqlite=bavard)
            self.assertEqual(fait.returncode, 0, fait.stderr)
            sortie = fait.stdout + fait.stderr
            self.assertIn("  @@ACCOUNT_ADDED ntfy", sortie)
            self.assertIn("  @@ENGINE_PACKAGE x", sortie)
            for ligne in sortie.splitlines():
                self.assertFalse(ligne.startswith("@@"), ligne)

    def test_sans_mot_de_passe_une_cle_nee_sur_l_hote(self):
        """Aucun secret ne voyage vers l'hote : la cle vient d'un mot de
        passe tire de /dev/urandom, que rien n'affiche ni ne passe en
        argument."""
        with tempfile.TemporaryDirectory() as dossier:
            fait, base, argv = self._poser(dossier, mot_de_passe="")
            self.assertEqual(fait.returncode, 0, fait.stderr)
            rangs = self._rangs(base)
            self.assertEqual(len(rangs), 1, rangs)
            realm, nom, cle = rangs[0]
            self.assertEqual((realm, nom), (REALM, "erplibre-check"))
            self.assertRegex(cle, r"^[0-9a-f]{32}$")
            self.assertNotEqual(cle, turn_client.long_term_key(
                "erplibre-check", REALM, "").hex())
            for ligne in argv + [fait.stdout, fait.stderr]:
                self.assertNotIn(cle, ligne)

    def test_sans_mot_de_passe_la_cle_en_place_est_gardee(self):
        """Une relance ne change pas un compte qui marche."""
        with tempfile.TemporaryDirectory() as dossier:
            _, base, _ = self._poser(dossier, mot_de_passe="")
            avant = self._rangs(base)
            fait, _, _ = self._poser(dossier, mot_de_passe="")
            self.assertEqual(fait.returncode, 0, fait.stderr)
            self.assertEqual(self._rangs(base), avant)

    def test_sans_mot_de_passe_un_realm_change_une_cle_neuve(self):
        with tempfile.TemporaryDirectory() as dossier:
            _, base, _ = self._poser(dossier, mot_de_passe="")
            (_, _, avant), = self._rangs(base)
            fait, _, _ = self._poser(dossier, realm="autre.exemple.test",
                                     mot_de_passe="")
            self.assertEqual(fait.returncode, 0, fait.stderr)
            rangs = self._rangs(base)
            self.assertEqual([r[:2] for r in rangs],
                             [("autre.exemple.test", "erplibre-check")])
            self.assertNotEqual(rangs[0][2], avant)

    def test_un_mot_de_passe_donne_remplace_la_cle_nee_sur_l_hote(self):
        with tempfile.TemporaryDirectory() as dossier:
            self._poser(dossier, mot_de_passe="")
            fait, base, _ = self._poser(dossier)
            self.assertEqual(fait.returncode, 0, fait.stderr)
            attendue = turn_client.long_term_key(
                "erplibre-check", REALM, MOT_DE_PASSE).hex()
            self.assertEqual(self._rangs(base),
                             [(REALM, "erplibre-check", attendue)])

    def test_la_base_est_ecrite_par_le_compte_de_service(self):
        """Le dossier de la base appartient a coturn : root n'y ouvre aucun
        fichier, un lien symbolique pose par ce compte ne vise rien de
        root."""
        with tempfile.TemporaryDirectory() as dossier:
            _, _, argv = self._poser(dossier)
            sqlite = [a for a in argv if a.startswith("runuser ")]
            self.assertEqual(len(sqlite), 1, argv)
            self.assertIn("-u turnserver -- sqlite3", sqlite[0])


class TestModeSecret(unittest.TestCase):
    """`remove_check_user` : en mode secret, le compte de controle long
    terme quitte la base (coturn le refuserait), les secrets restent."""

    def _jouer(self, dossier, avant=None):
        bouchons = os.path.join(dossier, "bin")
        os.makedirs(bouchons, exist_ok=True)
        for nom, contenu in (
                ("sqlite3", BOUCHON_SQLITE % {"python": sys.executable}),
                ("runuser", BOUCHON_RUNUSER)):
            chemin = os.path.join(bouchons, nom)
            with open(chemin, "w") as flux:
                flux.write(contenu)
            os.chmod(chemin, 0o755)
        base = os.path.join(dossier, "turndb")
        if avant is not None:
            avant(base)
        enveloppe = (
            ENTETE + constantes(DB_FILE=base) + ENTREES
            + "TURN_AUTH=secret\nSERVICE_USER=turnserver\n"
            + fonctions("schema_sql", "remove_check_user")
            + "remove_check_user\n")
        env = {"PATH": bouchons + os.pathsep + os.environ["PATH"],
               "STUB_LOG": os.path.join(dossier, "argv"),
               "STUB_SQL": os.path.join(dossier, "sql")}
        return jouer(enveloppe, env), base, lignes(
            os.path.join(dossier, "argv"))

    @staticmethod
    def _peupler(base):
        connexion = sqlite3.connect(base)
        connexion.executescript(
            "CREATE TABLE turnusers_lt (realm varchar(127) default '',"
            " name varchar(512), hmackey char(128),"
            " PRIMARY KEY (realm,name));"
            "CREATE TABLE turn_secret (realm varchar(127) default '',"
            " value varchar(127), primary key (realm,value));"
            "INSERT INTO turnusers_lt VALUES ('%s', 'erplibre-check', '%s');"
            "INSERT INTO turnusers_lt VALUES ('ancien.exemple.test',"
            " 'erplibre-check', '%s');"
            "INSERT INTO turn_secret VALUES ('%s', 'secretInvente0123');"
            % (REALM, "a" * 32, "b" * 32, REALM))
        connexion.close()

    def test_le_compte_de_controle_part_les_secrets_restent(self):
        with tempfile.TemporaryDirectory() as dossier:
            fait, base, argv = self._jouer(dossier, self._peupler)
            self.assertEqual(fait.returncode, 0, fait.stderr)
            connexion = sqlite3.connect(base)
            utilisateurs = connexion.execute(
                "select name from turnusers_lt").fetchall()
            secrets = connexion.execute(
                "select realm, value from turn_secret").fetchall()
            connexion.close()
            self.assertEqual(utilisateurs, [])
            self.assertEqual(secrets, [(REALM, "secretInvente0123")])
            self.assertTrue([a for a in argv
                             if a.startswith("runuser -u turnserver -- ")])

    def test_un_nouveau_nom_public_emporte_les_secrets(self):
        """Le realm est le nom public : un secret laisse sous l'ancien
        n'authentifierait plus rien. Un doublon de l'ancien realm part."""
        def peupler(base):
            self._peupler(base)
            connexion = sqlite3.connect(base)
            connexion.executescript(
                "INSERT INTO turn_secret VALUES ('ancien.exemple.test',"
                " 'secretAncien0123');"
                "INSERT INTO turn_secret VALUES ('ancien.exemple.test',"
                " 'secretInvente0123');")
            connexion.close()

        with tempfile.TemporaryDirectory() as dossier:
            fait, base, _ = self._jouer(dossier, peupler)
            self.assertEqual(fait.returncode, 0, fait.stderr)
            connexion = sqlite3.connect(base)
            secrets = connexion.execute(
                "select realm, value from turn_secret"
                " order by value").fetchall()
            connexion.close()
            self.assertEqual(secrets, [(REALM, "secretAncien0123"),
                                       (REALM, "secretInvente0123")])

    def test_base_neuve_au_schema_de_coturn(self):
        with tempfile.TemporaryDirectory() as dossier:
            fait, base, _ = self._jouer(dossier)
            self.assertEqual(fait.returncode, 0, fait.stderr)
            connexion = sqlite3.connect(base)
            noms = {r[0] for r in connexion.execute(
                "select name from sqlite_master where type='table'")}
            connexion.close()
            self.assertEqual(noms, TABLES_COTURN)


class TestPreparationBase(unittest.TestCase):
    def _preparer(self, dossier, avant=None):
        journal = os.path.join(dossier, "appels")
        base_dir = os.path.join(dossier, "lib")
        base = os.path.join(base_dir, "turndb")
        if avant:
            os.makedirs(base_dir)
            avant(base)
        enveloppe = (
            ENTETE + constantes(DB_DIR=base_dir, DB_FILE=base)
            + "J=%s\nSERVICE_USER=turnserver\nSERVICE_GROUP=turnserver\n"
            % journal
            + "install() { echo \"install $*\" >> $J; mkdir -p \"${@: -1}\"; }\n"
              "chown() { echo \"chown $*\" >> $J; }\n"
            + fonctions("prepare_database") + "prepare_database\n")
        return jouer(enveloppe), lignes(journal)

    def test_dossier_au_compte_de_service(self):
        with tempfile.TemporaryDirectory() as dossier:
            fait, appels = self._preparer(dossier)
            self.assertEqual(fait.returncode, 0, fait.stderr)
            self.assertTrue([a for a in appels if a.startswith(
                "install -d -m 0750 -o turnserver -g turnserver ")], appels)

    def test_lien_symbolique_refuse(self):
        with tempfile.TemporaryDirectory() as dossier:
            cible = os.path.join(dossier, "cible")
            open(cible, "w").close()
            fait, appels = self._preparer(
                dossier, lambda base: os.symlink(cible, base))
            self.assertNotEqual(fait.returncode, 0)
            self.assertFalse([a for a in appels if a.startswith("chown")])

    def test_base_existante_rendue_au_compte_sans_suivre_de_lien(self):
        with tempfile.TemporaryDirectory() as dossier:
            fait, appels = self._preparer(
                dossier, lambda base: open(base, "w").close())
            self.assertEqual(fait.returncode, 0, fait.stderr)
            self.assertTrue([a for a in appels
                             if a.startswith("chown -h turnserver:turnserver ")],
                            appels)


class TestCertificat(unittest.TestCase):
    def _copier(self, dossier, avec=True):
        journal = os.path.join(dossier, "appels")
        tls = os.path.join(dossier, "tls")
        os.makedirs(tls)
        for nom in ("turn.crt", "turn.key"):
            open(os.path.join(tls, nom), "w").close()
        for nom in ("c.pem", "k.pem"):
            with open(os.path.join(dossier, nom), "w") as flux:
                flux.write(nom)
        variables = ("TURN_CERT_FILE=%s/c.pem\nTURN_KEY_FILE=%s/k.pem\n"
                     % (dossier, dossier)) if avec else ""
        enveloppe = (
            ENTETE + constantes(TLS_DIR=tls, CALL_DIR=dossier) + ENTREES
            + variables + "J=%s\nSERVICE_USER=turnserver\n"
              "SERVICE_GROUP=turnserver\nCONFIG_CHANGED=0\n" % journal
            + "install() { echo \"install $*\" >> $J; }\n"
            + fonctions("has_cert", "install_certificate")
            + "install_certificate\necho \"CHANGED=$CONFIG_CHANGED\"\n")
        return jouer(enveloppe), lignes(journal), tls

    def test_copie_lisible_du_compte_de_service(self):
        with tempfile.TemporaryDirectory() as dossier:
            fait, appels, tls = self._copier(dossier)
            self.assertEqual(fait.returncode, 0, fait.stderr)
            self.assertIn("CHANGED=1", fait.stdout)
            for source_, cible in (("c.pem", "turn.crt"),
                                   ("k.pem", "turn.key")):
                self.assertIn("install -m 0640 -o root -g turnserver "
                              "%s/%s %s/%s" % (dossier, source_, tls, cible),
                              appels)

    def test_sans_certificat_les_anciens_sont_retires(self):
        with tempfile.TemporaryDirectory() as dossier:
            fait, appels, tls = self._copier(dossier, avec=False)
            self.assertEqual(fait.returncode, 0, fait.stderr)
            self.assertEqual(os.listdir(tls), [])
            self.assertIn("CHANGED=1", fait.stdout)
            self.assertEqual(appels, [])


class TestTampon(unittest.TestCase):
    """`applied_digest` : l'empreinte de ce que coturn charge, configuration
    et, avec un certificat, certificat et cle servis."""

    def _empreinte(self, dossier, avec):
        tls = os.path.join(dossier, "tls")
        os.makedirs(tls, exist_ok=True)
        conf = os.path.join(dossier, "turnserver.conf")
        with open(conf, "w") as flux:
            flux.write("# erplibre-call: managed\n")
        variables = ("TURN_CERT_FILE=%s/c.pem\nTURN_KEY_FILE=%s/k.pem\n"
                     % (dossier, dossier)) if avec else ""
        enveloppe = (ENTETE + constantes(TLS_DIR=tls) + ENTREES + variables
                     + fonctions("has_cert", "applied_digest")
                     + "applied_digest %s\n" % conf)
        return jouer(enveloppe), tls

    def test_sans_certificat_la_configuration_seule(self):
        with tempfile.TemporaryDirectory() as dossier:
            fait, _ = self._empreinte(dossier, avec=False)
            self.assertEqual(fait.returncode, 0, fait.stderr)
            self.assertEqual(len(fait.stdout.splitlines()), 1)
            self.assertIn("turnserver.conf", fait.stdout)

    def test_un_certificat_renouvele_change_l_empreinte(self):
        with tempfile.TemporaryDirectory() as dossier:
            avant, tls = None, None
            for contenu in ("ancien", "nouveau"):
                tls = os.path.join(dossier, "tls")
                os.makedirs(tls, exist_ok=True)
                for nom in ("turn.crt", "turn.key"):
                    with open(os.path.join(tls, nom), "w") as flux:
                        flux.write(contenu + nom)
                fait, _ = self._empreinte(dossier, avec=True)
                self.assertEqual(fait.returncode, 0, fait.stderr)
                self.assertEqual(len(fait.stdout.splitlines()), 3)
                self.assertNotEqual(fait.stdout, avant)
                avant = fait.stdout


class TestDropin(unittest.TestCase):
    """`write_dropin` : le droit d'ecouter un port privilegie, donne a
    l'unite par un fragment systemd que l'outil pose et retire."""

    DROPIN = ("# erplibre-call: managed\n[Service]\n"
              "AmbientCapabilities=CAP_NET_BIND_SERVICE\n")

    def _poser(self, dossier, variables="", unite="coturn"):
        enveloppe = (
            ENTETE + constantes(SYSTEMD_DIR=dossier) + ENTREES + variables
            + "\nUNIT=%s\nCONFIG_CHANGED=0\n" % unite
            + fonctions("refuse_linked_config", "write_dropin")
            + "write_dropin\necho \"CHANGED=$CONFIG_CHANGED\"\n")
        return jouer(enveloppe)

    def chemin(self, dossier, unite="coturn"):
        return os.path.join(dossier, "%s.service.d" % unite,
                            "erplibre-call.conf")

    def test_443_pose_le_fragment(self):
        """Les unites des paquets lancent coturn sous un compte sans
        CAP_NET_BIND_SERVICE : sans ce fragment, coturn ne peut ouvrir 443
        et cesse aussi de repondre sur listening-port."""
        for unite in ("coturn", "turnserver"):
            with self.subTest(unite=unite), \
                    tempfile.TemporaryDirectory() as dossier:
                fait = self._poser(dossier, "TURN_ALT_TLS_PORT=443", unite)
                self.assertEqual(fait.returncode, 0, fait.stderr)
                self.assertIn("CHANGED=1", fait.stdout)
                chemin = self.chemin(dossier, unite)
                self.assertEqual(open(chemin).read(), self.DROPIN)
                self.assertEqual(stat.S_IMODE(os.stat(chemin).st_mode),
                                 0o644)
                # Aucun fichier temporaire a cote : systemd lit *.conf.
                self.assertEqual(os.listdir(os.path.dirname(chemin)),
                                 ["erplibre-call.conf"])

    def test_relance_identique_rien_a_redemarrer(self):
        with tempfile.TemporaryDirectory() as dossier:
            self._poser(dossier, "TURN_ALT_TLS_PORT=443")
            fait = self._poser(dossier, "TURN_ALT_TLS_PORT=443")
            self.assertEqual(fait.returncode, 0, fait.stderr)
            self.assertIn("CHANGED=0", fait.stdout)

    def test_sans_port_alternatif_aucun_fragment(self):
        for variables in ("", "TURN_ALT_TLS_PORT=8443"):
            with self.subTest(variables=variables), \
                    tempfile.TemporaryDirectory() as dossier:
                fait = self._poser(dossier, variables)
                self.assertEqual(fait.returncode, 0, fait.stderr)
                self.assertIn("CHANGED=0", fait.stdout)
                self.assertEqual(os.listdir(dossier), [])

    def test_le_choix_retire_retire_le_fragment(self):
        with tempfile.TemporaryDirectory() as dossier:
            self._poser(dossier, "TURN_ALT_TLS_PORT=443")
            fait = self._poser(dossier)
            self.assertEqual(fait.returncode, 0, fait.stderr)
            self.assertIn("CHANGED=1", fait.stdout)
            self.assertFalse(os.path.exists(self.chemin(dossier)))
            self.assertEqual(os.listdir(dossier), [])

    def test_un_fragment_etranger_est_laisse(self):
        with tempfile.TemporaryDirectory() as dossier:
            chemin = self.chemin(dossier)
            os.makedirs(os.path.dirname(chemin))
            with open(chemin, "w") as flux:
                flux.write("[Service]\nNice=5\n")
            fait = self._poser(dossier)
            self.assertEqual(fait.returncode, 0, fait.stderr)
            self.assertIn("CHANGED=0", fait.stdout)
            self.assertEqual(open(chemin).read(), "[Service]\nNice=5\n")

    def test_un_fragment_en_lien_est_refuse(self):
        with tempfile.TemporaryDirectory() as dossier:
            victime = os.path.join(dossier, "victime")
            with open(victime, "w") as flux:
                flux.write("intact\n")
            chemin = self.chemin(dossier)
            os.makedirs(os.path.dirname(chemin))
            os.symlink(victime, chemin)
            fait = self._poser(dossier, "TURN_ALT_TLS_PORT=443")
            self.assertNotEqual(fait.returncode, 0, fait.stdout)
            self.assertEqual(open(victime).read(), "intact\n")


class TestService(unittest.TestCase):
    """`enable_service` : relit les unites avant tout redemarrage."""

    def _activer(self, change):
        with tempfile.TemporaryDirectory() as dossier:
            journal = os.path.join(dossier, "appels")
            enveloppe = (
                ENTETE + "J=%s\nUNIT=coturn\nCONFIG_CHANGED=%d\n"
                % (journal, change)
                + "systemctl() { echo \"systemctl $*\" >> $J; }\n"
                "sleep() { :; }\n"
                + fonctions("enable_service") + "enable_service\n")
            fait = jouer(enveloppe)
            return fait, lignes(journal)

    def test_un_fragment_change_est_lu_avant_le_redemarrage(self):
        """Un fragment pose par un passage interrompu avant le redemarrage
        n'est relu que par daemon-reload : la relance, qui redemarre sur
        l'ecart d'empreinte, le relit aussi."""
        fait, appels = self._activer(1)
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertLess(appels.index("systemctl daemon-reload"),
                        appels.index("systemctl restart coturn"))

    def test_sans_changement_ni_relecture_ni_redemarrage(self):
        fait, appels = self._activer(0)
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertNotIn("systemctl daemon-reload", appels)
        self.assertNotIn("systemctl restart coturn", appels)


class TestSource(unittest.TestCase):
    def test_le_mot_de_passe_n_est_jamais_affiche(self):
        """Aucune ligne n'imprime la valeur de TURN_CHECK_PASSWORD ; le seul
        printf qui l'etend alimente md5sum par un tube."""
        etendu = re.compile(r"\$\{?(TURN_CHECK_PASSWORD|password)\b")
        for numero, ligne in enumerate(source().splitlines(), 1):
            code = ligne.split("#", 1)[0]
            # Chaque commande de la ligne, separee par || && ; ou | : nommer
            # la variable dans un message est permis, l'etendre non.
            for commande in re.split(r"\|\||&&|;|\|", code):
                mots = commande.split()
                if not mots or not etendu.search(commande):
                    continue
                if mots[0] in ("echo", "log", "die", "cat"):
                    self.fail("ligne %d affiche le mot de passe : %s"
                              % (numero, ligne))
                if mots[0] == "printf" or "$(printf" in commande:
                    self.assertRegex(code, r"\|\s*md5sum\b",
                                     "ligne %d : %s" % (numero, ligne))

    def test_ni_trace_ni_turnadmin_avec_mot_de_passe(self):
        code = "\n".join(ligne.split("#", 1)[0]
                         for ligne in source().splitlines())
        self.assertIsNone(re.search(r"(?m)^\s*set\s+-[a-z]*x", code))
        self.assertIsNone(re.search(r"turnadmin[^\n]*-p", code))

    def test_syntaxe(self):
        fait = subprocess.run(["bash", "-n", SCRIPT], capture_output=True,
                              text=True)
        self.assertEqual(fait.returncode, 0, fait.stderr)


class TestMain(unittest.TestCase):
    """`main` : refus d'une configuration etrangere, ordre des etapes,
    marqueurs, code de sortie."""

    def _jouer(self, etats, famille="debian", conf=None, garder="",
               change=1, unite="", tampon=None, lien=None, variables=""):
        """`tampon` : None, aucun tampon ; "juste", le tampon de la
        configuration presente ; sinon le texte du tampon. `lien` : la
        configuration est un lien vers ce chemin."""
        with tempfile.TemporaryDirectory() as dossier:
            journal = os.path.join(dossier, "appels")
            chemin = os.path.join(dossier, "turnserver.conf")
            applique = os.path.join(dossier, "coturn.applied")
            if conf is not None:
                with open(chemin, "w") as flux:
                    flux.write(conf)
            if lien is not None:
                os.symlink(lien, chemin)
            if tampon is not None:
                if tampon == "juste":
                    tampon = self.empreinte(chemin)
                with open(applique, "w") as flux:
                    flux.write(tampon + "\n")
            with open(os.path.join(dossier, "etats"), "w") as flux:
                flux.write("\n".join(etats) + "\n")
            with open(os.path.join(dossier, "unite"), "w") as flux:
                flux.write(unite.replace("@D@", dossier))
            enveloppe = (
                ENTETE + constantes(DEBIAN_CONF=chemin, ARCH_CONF=chemin,
                                    CALL_DIR=dossier, APPLIED_FILE=applique,
                                    TLS_DIR=os.path.join(dossier, "tls"),
                                    SYSTEMD_DIR=dossier)
                + ENTREES + "TURN_GARDER_CONFIG=%s\n" % garder + variables
                + "export TURN_CHECK_PASSWORD\n"
                "J=%s\nE=%s/etats\nU=%s/unite\n" % (journal, dossier, dossier)
                + "check_root() { :; }\n"
                "detect_os() { OS=%s; OS_LIKE=; }\n" % famille
                + "install_packages() { echo install >> $J; }\n"
                "install_certificate() { echo certificat >> $J; }\n"
                "write_config() { echo \"write $1\" >> $J;"
                " [ -e \"$1\" ] || echo '# erplibre-call: managed' > \"$1\";"
                " CONFIG_CHANGED=%d; }\n" % change
                + "write_dropin() { echo \"dropin $UNIT\" >> $J; }\n"
                + "install() { echo \"install $*\" >> $J; }\n"
                + "enable_default() { echo default >> $J; }\n"
                "prepare_database() { echo base >> $J; }\n"
                "ensure_check_user() { echo check >> $J;"
                " declare -p TURN_CHECK_PASSWORD | cut -c1-11 >> $J; }\n"
                "remove_check_user() { echo sans-controle >> $J; }\n"
                "id() { case \"$1\" in -gn) echo turnserver;; *) echo 999;;"
                " esac; }\n"
                "sleep() { :; }\n"
                "systemctl() {\n"
                "  case \"$1\" in\n"
                "  cat) cat $U; [ -s $U ];;\n"
                "  is-active)\n"
                "    e=$(head -n 1 $E); [ \"$(wc -l < $E)\" -gt 1 ]"
                " && sed -i 1d $E\n"
                "    echo \"$e\"; [ \"$e\" = active ];;\n"
                "  *) echo \"systemctl $*\" >> $J;\n"
                "     [ ! -e \"$APPLIED_FILE\" ] || echo \"tampon pendant $1\""
                " >> $J;;\n"
                "  esac\n"
                "}\n"
            ) + fonctions(
                "valid_port", "has_cert", "check_inputs", "family",
                "unit_name", "unit_text", "service_user", "config_path",
                "refuse_linked_config", "config_is_foreign", "applied_digest", "record_applied",
                "enable_service", "service_state", "main") + "main\n"
            fait = jouer(enveloppe)
            # Le dossier disparait au retour : le contenu est lu avant.
            self.conf_apres = (open(chemin).read() if os.path.exists(chemin)
                               else None)
            self.tampon_apres = (open(applique).read()
                                 if os.path.exists(applique) else None)
            self.empreinte_apres = (self.empreinte(chemin)
                                    if os.path.exists(chemin) else None)
            return fait, lignes(journal), chemin

    def test_service_en_echec_code_non_nul_et_marqueurs(self):
        fait, appels, chemin = self._jouer(["failed"])
        self.assertNotEqual(fait.returncode, 0, fait.stdout)
        sortie = fait.stdout.splitlines()
        self.assertEqual(sortie[-1], "@@ACTIVE coturn failed")
        self.assertIn("@@UNIT coturn", sortie)
        self.assertIn("@@USER turnserver", sortie)
        self.assertIn("@@CONFIG " + chemin, sortie)
        # Le compte de controle est pose avant le redemarrage.
        self.assertLess(appels.index("check"),
                        appels.index("systemctl restart coturn"))

    def test_service_actif_code_nul(self):
        fait, appels, chemin = self._jouer(["active"])
        self.assertEqual(fait.returncode, 0, fait.stdout + fait.stderr)
        self.assertEqual(fait.stdout.splitlines()[-1],
                         "@@ACTIVE coturn active")
        self.assertIn("systemctl enable coturn", appels)
        self.assertIn("write " + chemin, appels)

    def test_un_demarrage_en_cours_est_attendu(self):
        fait, _, _ = self._jouer(["activating", "activating", "active"])
        self.assertEqual(fait.returncode, 0, fait.stdout + fait.stderr)

    def test_le_mot_de_passe_n_est_plus_exporte(self):
        _, appels, _ = self._jouer(["active"])
        self.assertIn("declare -- ", appels)

    def test_configuration_etrangere_refusee_avant_installation(self):
        fait, appels, _ = self._jouer(["active"],
                                      conf="listening-port=3478\n")
        self.assertNotEqual(fait.returncode, 0)
        self.assertNotIn("install", appels)
        self.assertFalse([a for a in appels if a.startswith("write")])
        self.assertIn("TURN_GARDER_CONFIG", fait.stderr)
        self.assertEqual(self.conf_apres, "listening-port=3478\n")

    def test_configuration_etrangere_adoptee_avec_accord(self):
        fait, appels, _ = self._jouer(["active"], conf="listening-port=3478\n",
                                      garder="1")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertIn("install", appels)

    def test_configuration_geree_reprise_sans_accord(self):
        fait, _, _ = self._jouer(
            ["active"], conf="# erplibre-call: managed\nlisten=1\n")
        self.assertEqual(fait.returncode, 0, fait.stderr)

    @staticmethod
    def empreinte(chemin):
        """La ligne que `sha256sum <chemin>` imprime."""
        with open(chemin, "rb") as flux:
            return "%s  %s" % (hashlib.sha256(flux.read()).hexdigest(),
                               chemin)

    def test_configuration_inchangee_pas_de_redemarrage(self):
        """Redemarrer coturn coupe les appels en cours : une configuration
        inchangee, que le tampon dit deja chargee, ne redemarre rien."""
        fait, appels, _ = self._jouer(
            ["active"], change=0, conf="# erplibre-call: managed\n",
            tampon="juste")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertNotIn("systemctl restart coturn", appels)
        self.assertIn("systemctl start coturn", appels)

    def test_configuration_inchangee_sans_tampon_redemarre(self):
        """Un passage interrompu apres write_config laisse sur disque la
        configuration geree, mais coturn tourne encore sur l'ancienne : sans
        tampon, la relance redemarre."""
        fait, appels, _ = self._jouer(
            ["active"], change=0, conf="# erplibre-call: managed\n")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertIn("systemctl restart coturn", appels)
        self.assertEqual(self.tampon_apres, self.empreinte_apres + "\n")

    def test_configuration_inchangee_tampon_perime_redemarre(self):
        fait, appels, _ = self._jouer(
            ["active"], change=0, conf="# erplibre-call: managed\n",
            tampon="0" * 64 + "  /ailleurs/turnserver.conf")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertIn("systemctl restart coturn", appels)
        self.assertEqual(self.tampon_apres, self.empreinte_apres + "\n")

    def test_tampon_retire_avant_le_redemarrage(self):
        """Un passage coupe pendant le redemarrage ne laisse aucun tampon qui
        dirait la nouvelle configuration chargee."""
        _, appels, _ = self._jouer(
            ["active"], conf="# erplibre-call: managed\n", tampon="juste")
        self.assertIn("systemctl restart coturn", appels)
        self.assertNotIn("tampon pendant restart", appels)

    def test_redemarrage_en_echec_aucun_tampon(self):
        fait, appels, _ = self._jouer(
            ["failed"], change=0, conf="# erplibre-call: managed\n",
            tampon="0" * 64 + "  /ailleurs/turnserver.conf")
        self.assertNotEqual(fait.returncode, 0)
        self.assertIn("systemctl restart coturn", appels)
        self.assertIsNone(self.tampon_apres)

    def test_configuration_changee_tampon_ecrit(self):
        fait, appels, _ = self._jouer(["active"])
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertIn("systemctl restart coturn", appels)
        self.assertEqual(self.tampon_apres, self.empreinte_apres + "\n")

    def test_arch_unite_et_compte_lus_du_paquet(self):
        unite = ("[Service]\nUser=turnsrv-invente\nExecStart=/usr/bin/"
                 "turnserver -c @D@/arch.conf\n")
        fait, appels, _ = self._jouer(["active"], famille="arch", unite=unite)
        self.assertEqual(fait.returncode, 0, fait.stderr)
        sortie = fait.stdout.splitlines()
        self.assertIn("@@UNIT turnserver", sortie)
        self.assertIn("@@USER turnsrv-invente", sortie)
        self.assertTrue([s for s in sortie if s.startswith("@@CONFIG ")
                         and s.endswith("/arch.conf")], sortie)
        self.assertIn("systemctl restart turnserver", appels)

    def test_plages_privees_permises_annoncees(self):
        fait, _, _ = self._jouer(["active"], variables="TURN_ALLOW_PRIVATE=1\n")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertIn("TURN_ALLOW_PRIVATE=1", fait.stdout)
        refait, _, _ = self._jouer(["active"])
        self.assertNotIn("TURN_ALLOW_PRIVATE", refait.stdout)

    def test_configuration_en_lien_refusee_avant_installation(self):
        with tempfile.TemporaryDirectory() as ailleurs:
            cible = os.path.join(ailleurs, "turn.conf")
            with open(cible, "w") as flux:
                flux.write("# erplibre-call: managed\n")
            fait, appels, _ = self._jouer(["active"], lien=cible)
        self.assertNotEqual(fait.returncode, 0)
        self.assertNotIn("install", appels)
        self.assertFalse([a for a in appels if a.startswith("write")])
        self.assertIn("lien", fait.stderr)

    def test_le_fragment_suit_la_configuration_avant_le_redemarrage(self):
        _, appels, chemin = self._jouer(["active"])
        self.assertLess(appels.index("write " + chemin),
                        appels.index("dropin coturn"))
        self.assertLess(appels.index("dropin coturn"),
                        appels.index("systemctl restart coturn"))

    def test_mode_secret_retire_le_compte_de_controle(self):
        fait, appels, _ = self._jouer(["active"],
                                      variables="TURN_AUTH=secret\n")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertIn("sans-controle", appels)
        self.assertNotIn("check", appels)
        # Avant le redemarrage, comme le compte en mode fixe.
        self.assertLess(appels.index("sans-controle"),
                        appels.index("systemctl restart coturn"))

    def test_mode_fixe_pose_le_compte_de_controle(self):
        fait, appels, _ = self._jouer(["active"])
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertIn("check", appels)
        self.assertNotIn("sans-controle", appels)

    def test_systeme_non_supporte_refuse_avant_installation(self):
        fait, appels, _ = self._jouer(["active"], famille="fedora")
        self.assertNotEqual(fait.returncode, 0)
        self.assertNotIn("install", appels)


# install sans -o ni -g : le bac a sable ne tourne pas en root. L'argv
# complet est note, la copie ou le dossier sont faits pour de vrai.
BOUCHON_INSTALL = r"""#!%(python)s
import os
import subprocess
import sys

with open(os.environ["STUB_LOG"], "a") as journal:
    journal.write("install " + " ".join(sys.argv[1:]) + "\n")
gardes, sauter = [], False
for mot in sys.argv[1:]:
    if sauter:
        sauter = False
    elif mot in ("-o", "-g"):
        sauter = True
    else:
        gardes.append(mot)
sys.exit(subprocess.call(["%(vrai)s"] + gardes))
"""

# id : seul le compte invente existe, uid et groupe a son nom.
BOUCHON_ID = ('#!/bin/sh\necho "id $*" >> "$STUB_LOG"\n'
              'case "$1 $2" in\n'
              '  "-u erplibre-coturn") echo 990 ;;\n'
              '  "-gn erplibre-coturn") echo erplibre-coturn ;;\n'
              '  *) exit 1 ;;\n'
              'esac\n')

# dpkg-query : sqlite3 installe seulement quand SQLITE_PRESENT vaut 1.
BOUCHON_DPKG_QUERY = ('#!/bin/sh\necho "dpkg-query $*" >> "$STUB_LOG"\n'
                      '[ "$SQLITE_PRESENT" = 1 ] || exit 1\n'
                      "echo 'install ok installed'\n")

BOUCHON_PACMAN = ('#!/bin/sh\necho "pacman $*" >> "$STUB_LOG"\n'
                  '[ "$1" != -Q ] || [ "$SQLITE_PRESENT" = 1 ]\n')

# Ce que la cible conteneur ne lance jamais : systemd, les moteurs, les
# comptes, sudo. Chaque appel est note dans STUB_INTERDIT et echoue.
INTERDITES = ("systemctl", "docker", "podman", "podman-compose",
              "docker-compose", "loginctl", "useradd", "usermod", "userdel",
              "timeout", "getent", "turnadmin", "sudo", "runc")
BOUCHON_INTERDIT = ('#!/bin/sh\necho "%(nom)s $*" >> "$STUB_INTERDIT"\n'
                    'exit 97\n')


class TestCibleConteneur(unittest.TestCase):
    """`main` avec TURN_TARGET=container, toutes les fonctions du script
    jouees pour de vrai dans un dossier temporaire : seules les commandes
    systeme sont des bouchons, en tete du PATH. Rien ne redemarre : le
    script dit s'il faut recreer le conteneur."""

    COMPTE = "erplibre-coturn"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        d = self.d = self._tmp.name
        self.bouchons = os.path.join(d, "bin")
        os.makedirs(self.bouchons)
        self.journaux = os.path.join(d, "journaux")
        os.makedirs(self.journaux)
        ecrits = {
            "sqlite3": BOUCHON_SQLITE % {"python": sys.executable},
            "runuser": BOUCHON_RUNUSER,
            "install": BOUCHON_INSTALL % {"python": sys.executable,
                                          "vrai": shutil.which("install")},
            "id": BOUCHON_ID,
            "chown": BOUCHON_JOURNAL % {"nom": "chown"},
            "apt-get": BOUCHON_JOURNAL % {"nom": "apt-get"},
            "dpkg": BOUCHON_JOURNAL % {"nom": "dpkg"},
            "dpkg-query": BOUCHON_DPKG_QUERY,
            "pacman": BOUCHON_PACMAN,
        }
        for nom in INTERDITES:
            ecrits[nom] = BOUCHON_INTERDIT % {"nom": nom}
        for nom, contenu in ecrits.items():
            chemin = os.path.join(self.bouchons, nom)
            with open(chemin, "w") as flux:
                flux.write(contenu)
            os.chmod(chemin, 0o755)
        self.call = os.path.join(d, "etc-call")
        self.chemins = {
            "CALL_DIR": self.call,
            "TLS_DIR": os.path.join(self.call, "tls"),
            "DB_DIR": os.path.join(d, "lib"),
            "DB_FILE": os.path.join(d, "lib", "turndb"),
            "DEBIAN_CONF": os.path.join(d, "turnserver.conf"),
            "ARCH_CONF": os.path.join(d, "arch", "turnserver.conf"),
            "APPLIED_FILE": os.path.join(self.call, "coturn.applied"),
            "PENDING_FILE": os.path.join(
                self.call, "coturn.applied.erplibre-pending"),
            "SYSTEMD_DIR": os.path.join(d, "systemd"),
            "DEFAULT_FILE": os.path.join(d, "default-coturn"),
            "OS_RELEASE": os.path.join(d, "os-release"),
        }
        self.applique = self.chemins["APPLIED_FILE"]
        self.attente = self.chemins["PENDING_FILE"]
        for nom in ("c.pem", "k.pem"):
            with open(os.path.join(d, nom), "w") as flux:
                flux.write("premier " + nom)

    def _jouer(self, variables="", compte=COMPTE, famille="debian",
               sqlite_present=False):
        with open(self.chemins["OS_RELEASE"], "w") as flux:
            flux.write("ID=%s\n" % famille)
        noms = [n for n in re.findall(r"^([a-z_]+)\(\) \{$", source(), re.M)
                if n != "check_root"]
        enveloppe = (
            ENTETE + constantes(**self.chemins) + ENTREES
            + "TURN_TARGET=container\nTURN_SERVICE_USER=%s\n" % compte
            + variables.replace("@D@", self.d) + "\n"
            # EUID ne se change pas : la verification de root seule est
            # remplacee, le reste du script est celui du fichier.
            + "check_root() { :; }\n"
            + fonctions(*noms) + "main\n")
        # Chaque passage a ses propres journaux.
        for nom in os.listdir(self.journaux):
            os.remove(os.path.join(self.journaux, nom))
        env = {"PATH": self.bouchons + os.pathsep + os.environ["PATH"],
               "STUB_LOG": os.path.join(self.journaux, "argv"),
               "STUB_SQL": os.path.join(self.journaux, "sql"),
               "STUB_INTERDIT": os.path.join(self.journaux, "interdit"),
               "SQLITE_PRESENT": "1" if sqlite_present else "0"}
        fait = jouer(enveloppe, env)
        self.appels = lignes(env["STUB_LOG"])
        self.interdits = lignes(env["STUB_INTERDIT"])
        return fait

    @staticmethod
    def _lire(chemin):
        if not os.path.exists(chemin):
            return None
        with open(chemin) as flux:
            return flux.read()

    def _empreinte(self, conf):
        """Ce que `applied_digest` imprime, calcule ici."""
        fichiers = [conf]
        tls = self.chemins["TLS_DIR"]
        if os.path.exists(os.path.join(tls, "turn.crt")):
            fichiers += [os.path.join(tls, "turn.crt"),
                         os.path.join(tls, "turn.key")]
        sortie = []
        for chemin in fichiers:
            with open(chemin, "rb") as flux:
                sortie.append("%s  %s" % (hashlib.sha256(flux.read())
                                          .hexdigest(), chemin))
        return "\n".join(sortie) + "\n"

    def _promouvoir(self):
        """Ce que fait l'appelant une fois le conteneur recree et en
        marche : l'empreinte en attente devient celle qui est chargee."""
        os.replace(self.attente, self.applique)

    def test_configuration_au_chemin_de_la_famille_sans_systemd(self):
        fait = self._jouer()
        self.assertEqual(fait.returncode, 0, fait.stdout + fait.stderr)
        self.assertEqual(self.interdits, [])
        sortie = fait.stdout.splitlines()
        self.assertEqual(sortie[-1], "@@CONFIGURED coturn")
        self.assertIn("@@RECREATE 1", sortie)
        self.assertFalse([s for s in sortie if s.startswith("@@ACTIVE")])
        conf = self.chemins["DEBIAN_CONF"]
        contenu = self._lire(conf).splitlines()
        self.assertIn("log-file=stdout", contenu)
        for absente in ("syslog", "no-dtls",
                        "no-stun-backward-compatibility"):
            self.assertNotIn(absente, contenu)
        self.assertEqual(stat.S_IMODE(os.stat(conf).st_mode), 0o640)
        dossier = os.path.dirname(conf)
        self.assertTrue([a for a in self.appels if re.fullmatch(
            r"chown root:erplibre-coturn %s/\.turnserver\.conf\.\S+"
            % re.escape(dossier), a)], self.appels)
        # Ni fragment d'unite ni /etc/default : aucune unite ne lance coturn.
        self.assertFalse(os.path.exists(self.chemins["SYSTEMD_DIR"]))
        self.assertFalse(os.path.exists(self.chemins["DEFAULT_FILE"]))

    def test_base_et_compte_de_controle_sous_le_compte_donne(self):
        fait = self._jouer()
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertIn("install -d -m 0750 -o erplibre-coturn -g "
                      "erplibre-coturn " + self.chemins["DB_DIR"],
                      self.appels)
        self.assertTrue([a for a in self.appels if a.startswith(
            "runuser -u erplibre-coturn -- sqlite3 ")], self.appels)
        connexion = sqlite3.connect(self.chemins["DB_FILE"])
        try:
            rangs = connexion.execute(
                "select realm, name from turnusers_lt").fetchall()
        finally:
            connexion.close()
        self.assertEqual(rangs, [(REALM, "erplibre-check")])

    def test_mode_secret_retire_le_compte_de_controle(self):
        self.assertEqual(self._jouer().returncode, 0)
        fait = self._jouer("TURN_AUTH=secret")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertIn("use-auth-secret",
                      self._lire(self.chemins["DEBIAN_CONF"]).splitlines())
        connexion = sqlite3.connect(self.chemins["DB_FILE"])
        try:
            self.assertEqual(connexion.execute(
                "select count(*) from turnusers_lt").fetchone(), (0,))
        finally:
            connexion.close()
        self.assertEqual(self.interdits, [])

    def test_sqlite3_seul_installe_sur_l_hote(self):
        self._jouer()
        installe = [a for a in self.appels
                    if a.startswith("apt-get") and " install " in a]
        self.assertEqual(len(installe), 1, self.appels)
        self.assertTrue(installe[0].endswith(" sqlite3"), installe)
        self.assertNotIn("coturn", installe[0].replace(
            "erplibre-coturn", ""))
        self._jouer(sqlite_present=True)
        self.assertFalse([a for a in self.appels
                          if a.startswith("apt-get")], self.appels)

    def test_arch_configuration_au_chemin_du_paquet(self):
        fait = self._jouer(famille="arch")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertIn("pacman -S --noconfirm --needed sqlite", self.appels)
        self.assertIsNotNone(self._lire(self.chemins["ARCH_CONF"]))
        self.assertIsNone(self._lire(self.chemins["DEBIAN_CONF"]))
        self.assertEqual(self.interdits, [])

    def test_empreinte_en_attente_et_tampon_intact(self):
        os.makedirs(self.call)
        with open(self.applique, "w") as flux:
            flux.write("0" * 64 + "  /ailleurs/turnserver.conf\n")
        fait = self._jouer()
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertIn("@@RECREATE 1", fait.stdout.splitlines())
        self.assertEqual(self._lire(self.applique),
                         "0" * 64 + "  /ailleurs/turnserver.conf\n")
        self.assertEqual(self._lire(self.attente),
                         self._empreinte(self.chemins["DEBIAN_CONF"]))
        self.assertEqual(stat.S_IMODE(os.stat(self.attente).st_mode), 0o600)
        self.assertIn("install -d -m 0755 -o root -g root " + self.call,
                      self.appels)
        self.assertFalse(os.path.exists(self.attente + ".erplibre-new"))

    def test_relance_identique_rien_a_recreer(self):
        self.assertEqual(self._jouer().returncode, 0)
        self._promouvoir()
        applique = self._lire(self.applique)
        fait = self._jouer()
        self.assertEqual(fait.returncode, 0, fait.stderr)
        sortie = fait.stdout.splitlines()
        self.assertIn("@@RECREATE 0", sortie)
        self.assertNotIn("@@RECREATE 1", sortie)
        self.assertEqual(sortie[-1], "@@CONFIGURED coturn")
        self.assertFalse(os.path.exists(self.attente))
        self.assertEqual(self._lire(self.applique), applique)
        self.assertEqual(self.interdits, [])

    def test_conteneur_jamais_recree_la_relance_le_redemande(self):
        """Sans promotion, le conteneur tourne encore sur l'ancienne
        configuration : la relance demande toujours de le recreer."""
        self.assertEqual(self._jouer().returncode, 0)
        fait = self._jouer()
        self.assertIn("@@RECREATE 1", fait.stdout.splitlines())
        self.assertIsNone(self._lire(self.applique))

    def test_attente_perimee_retiree_quand_rien_n_est_a_recreer(self):
        self.assertEqual(self._jouer().returncode, 0)
        self._promouvoir()
        with open(self.attente, "w") as flux:
            flux.write("0" * 64 + "  /ailleurs/turnserver.conf\n")
        fait = self._jouer()
        self.assertIn("@@RECREATE 0", fait.stdout.splitlines())
        self.assertFalse(os.path.exists(self.attente))

    def test_certificat_renouvele_a_recreer(self):
        self.assertEqual(self._jouer(CERT).returncode, 0)
        self._promouvoir()
        tls = self.chemins["TLS_DIR"]
        self.assertEqual(self._lire(os.path.join(tls, "turn.crt")),
                         "premier c.pem")
        self.assertIn("@@RECREATE 0",
                      self._jouer(CERT).stdout.splitlines())
        with open(os.path.join(self.d, "c.pem"), "w") as flux:
            flux.write("second c.pem")
        fait = self._jouer(CERT)
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertIn("@@RECREATE 1", fait.stdout.splitlines())
        self.assertIn("install -m 0640 -o root -g erplibre-coturn %s/c.pem "
                      "%s/turn.crt" % (self.d, tls), self.appels)
        self.assertEqual(self._lire(self.attente),
                         self._empreinte(self.chemins["DEBIAN_CONF"]))

    def _rien_ecrit(self, fait, nommee):
        self.assertNotEqual(fait.returncode, 0, fait.stdout)
        self.assertIn(nommee, fait.stderr)
        self.assertNotIn("@@CONFIGURED coturn", fait.stdout)
        self.assertEqual(sorted(os.listdir(self.d)),
                         ["bin", "c.pem", "journaux", "k.pem",
                          "os-release"])
        self.assertFalse([a for a in self.appels
                          if a.split()[0] in ("apt-get", "dpkg", "pacman",
                                              "install", "chown",
                                              "runuser", "sqlite3")],
                         self.appels)
        self.assertEqual(self.interdits, [])

    def test_sans_compte_refuse_avant_toute_ecriture(self):
        self._rien_ecrit(self._jouer(compte=""), "TURN_SERVICE_USER")

    def test_compte_absent_refuse_avant_toute_ecriture(self):
        self._rien_ecrit(self._jouer(compte="compte-invente"),
                         "compte-invente")

    def test_root_refuse_avant_toute_ecriture(self):
        self._rien_ecrit(self._jouer(compte="root"), "TURN_SERVICE_USER")

    def test_configuration_etrangere_refusee_avant_toute_ecriture(self):
        conf = self.chemins["DEBIAN_CONF"]
        with open(conf, "w") as flux:
            flux.write("listening-port=3478\n")
        fait = self._jouer()
        self.assertNotEqual(fait.returncode, 0)
        self.assertIn("TURN_GARDER_CONFIG", fait.stderr)
        self.assertEqual(self._lire(conf), "listening-port=3478\n")
        self.assertFalse([a for a in self.appels
                          if a.startswith("apt-get")], self.appels)
        fait = self._jouer("TURN_GARDER_CONFIG=1")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertEqual(self._lire(conf).splitlines()[0],
                         "# erplibre-call: managed")


if __name__ == "__main__":
    sys.exit(not unittest.main(exit=False).result.wasSuccessful())
