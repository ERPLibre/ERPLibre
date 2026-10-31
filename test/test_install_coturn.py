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
              "DEFAULT_FILE", "APPLIED_FILE")
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
    for nom, valeur in remplacements.items():
        sortie.append('%s="%s"\n' % (nom, valeur))
    return "".join(sortie)


ENTREES = (
    "TURN_REALM=%s\nTURN_PORT=3478\nTURN_TLS_PORT=5349\n"
    "TURN_MIN_PORT=49152\nTURN_MAX_PORT=49252\nTURN_CERT_FILE=\n"
    "TURN_KEY_FILE=\nTURN_EXTERNAL_IP=\nTURN_CHECK_PASSWORD='%s'\n"
    "TURN_GARDER_CONFIG=\n" % (REALM, MOT_DE_PASSE))

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
                             "denied-peer-ip", MOT_DE_PASSE):
                self.assertNotIn(interdit, texte)

    def test_avec_certificat(self):
        fait, texte, _, _, _ = self._ecrire(
            "TURN_CERT_FILE=/c.pem\nTURN_KEY_FILE=/k.pem")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        contenu = texte.splitlines()
        self.assertIn("tls-listening-port=5349", contenu)
        self.assertIn("cert=/etc/erplibre-call/tls/turn.crt", contenu)
        self.assertIn("pkey=/etc/erplibre-call/tls/turn.key", contenu)
        self.assertNotIn("no-tls", contenu)

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
                "TURN_CHECK_PASSWORD=",
                "TURN_REALM='turn.exemple.test\nuser=x'",
                "TURN_REALM=\"o'brien.exemple.test\"",
                "TURN_PORT=abc",
                "TURN_PORT=70000",
                "TURN_MIN_PORT=50000\nTURN_MAX_PORT=40000",
                "TURN_CERT_FILE=@D@/c.pem",
                "TURN_KEY_FILE=@D@/k.pem",
                "TURN_CERT_FILE=@D@/absent.pem\nTURN_KEY_FILE=@D@/k.pem",
                "TURN_EXTERNAL_IP='198.51.100.7\nuser=x'"):
            with self.subTest(variables=variables):
                fait = self._verifier(variables, fichiers=True)
                self.assertNotEqual(fait.returncode, 0, fait.stdout)
                self.assertNotIn("OK", fait.stdout)

    def test_certificat_et_cle_presents_acceptes(self):
        fait = self._verifier(
            "TURN_CERT_FILE=@D@/c.pem\nTURN_KEY_FILE=@D@/k.pem", fichiers=True)
        self.assertEqual(fait.returncode, 0, fait.stderr)


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

    def test_arch(self):
        fait, appels = self._installer("arch")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertIn("pacman -S --noconfirm --needed coturn sqlite", appels)
        self.assertFalse([a for a in appels if a.startswith("apt-get")])

    def test_deja_installes_rien_n_est_mis_a_jour(self):
        for famille in ("debian", "arch"):
            with self.subTest(famille=famille):
                fait, appels = self._installer(famille, presents=True)
                self.assertEqual(fait.returncode, 0, fait.stderr)
                self.assertFalse([a for a in appels
                                  if a.startswith("apt-get")
                                  or a.startswith("pacman -S")], appels)


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

    def _poser(self, dossier, realm=REALM, mot_de_passe=MOT_DE_PASSE):
        bouchons = os.path.join(dossier, "bin")
        os.makedirs(bouchons, exist_ok=True)
        ecrits = {
            "sqlite3": BOUCHON_SQLITE % {"python": sys.executable},
            "runuser": BOUCHON_RUNUSER,
            "turnadmin": BOUCHON_JOURNAL % {"nom": "turnadmin"},
        }
        for nom in ("md5sum", "cut", "sha256sum", "openssl"):
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
            + fonctions("ensure_check_user") + "ensure_check_user\n")
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

    def test_la_base_est_ecrite_par_le_compte_de_service(self):
        """Le dossier de la base appartient a coturn : root n'y ouvre aucun
        fichier, un lien symbolique pose par ce compte ne vise rien de
        root."""
        with tempfile.TemporaryDirectory() as dossier:
            _, _, argv = self._poser(dossier)
            sqlite = [a for a in argv if a.startswith("runuser ")]
            self.assertEqual(len(sqlite), 1, argv)
            self.assertIn("-u turnserver -- sqlite3", sqlite[0])


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


class TestSource(unittest.TestCase):
    def test_le_mot_de_passe_n_est_jamais_affiche(self):
        """Aucune ligne n'imprime la valeur de TURN_CHECK_PASSWORD ; le seul
        printf qui l'etend alimente md5sum par un tube."""
        etendu = re.compile(r"\$\{?TURN_CHECK_PASSWORD")
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
               change=1, unite="", tampon=None, lien=None):
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
                                    CALL_DIR=dossier, APPLIED_FILE=applique)
                + ENTREES + "TURN_GARDER_CONFIG=%s\n" % garder
                + "export TURN_CHECK_PASSWORD\n"
                "J=%s\nE=%s/etats\nU=%s/unite\n" % (journal, dossier, dossier)
                + "check_root() { :; }\n"
                "detect_os() { OS=%s; OS_LIKE=; }\n" % famille
                + "install_packages() { echo install >> $J; }\n"
                "install_certificate() { echo certificat >> $J; }\n"
                "write_config() { echo \"write $1\" >> $J;"
                " [ -e \"$1\" ] || echo '# erplibre-call: managed' > \"$1\";"
                " CONFIG_CHANGED=%d; }\n" % change
                + "install() { echo \"install $*\" >> $J; }\n"
                + "enable_default() { echo default >> $J; }\n"
                "prepare_database() { echo base >> $J; }\n"
                "ensure_check_user() { echo check >> $J;"
                " declare -p TURN_CHECK_PASSWORD | cut -c1-11 >> $J; }\n"
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

    def test_systeme_non_supporte_refuse_avant_installation(self):
        fait, appels, _ = self._jouer(["active"], famille="fedora")
        self.assertNotEqual(fait.returncode, 0)
        self.assertNotIn("install", appels)


if __name__ == "__main__":
    sys.exit(not unittest.main(exit=False).result.wasSuccessful())
