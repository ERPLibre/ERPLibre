#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'installateur certbot de l'infrastructure d'appel, sans root ni reseau.

Le script est joue en entier sous une racine temporaire : sa constante
ROOT, vide en production, prefixe chaque chemin de l'hote qu'il lit ou
ecrit. Les commandes systeme (`apt-get`, `apt-cache`, `dpkg`, `dpkg-query`,
`pacman`, `systemctl`, `certbot`) sont des bouchons qui notent leurs
appels. Le bouchon certbot note son argv, une ligne par appel, et cree la
lignee `live/erplibre-call` sous la racine comme le ferait une vraie
delivrance ; il echoue sur demande, au premier appel (essai a blanc) ou au
second (delivrance).

Les noms, l'adresse et le secret DNS sont inventes (`*.exemple.test`).
"""
import os
import re
import shutil
import stat
import subprocess
import tempfile
import unittest

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(RACINE, "script/install/install_certbot.sh")

NTFY = "ntfy.exemple.test"
TURN = "turn.exemple.test"
ACME = "/var/lib/erplibre-call-acme"
LIGNEE = "/etc/letsencrypt/live/erplibre-call"
RENOUVELLEMENT = "/etc/letsencrypt/renewal/erplibre-call.conf"
GARDE = RENOUVELLEMENT + ".erplibre-hold"
IDENTIFIANTS = "/etc/erplibre-call/dns/ovh.ini"
SECRET = "cle-inventee-7f3a9c"
COURRIEL = "admin@exemple.test"
UNITE_SERVICE = "/etc/systemd/system/erplibre-call-certbot.service"
UNITE_MINUTEUR = "/etc/systemd/system/erplibre-call-certbot.timer"
MARKER = "# erplibre-call: managed"

OS_DEBIAN = 'ID=debian\nVERSION_ID="13"\n'
OS_ARCH = "ID=arch\n"

# Sorties de certbot en echec. « simple » finit sur la ligne a rapporter ;
# « reelle » a la forme de certbot 4 : le motif de l'autorite dans une
# ligne Detail, puis deux lignes d'aide qui ne disent rien de la cause.
SORTIES = {
    "simple": (
        "echo 'Saving debug log to /var/log/letsencrypt/letsencrypt.log'\n"
        "echo 'Certbot failed to authenticate some domains' >&2\n"
        "echo 'Some challenges have failed.' >&2\n"
    ),
    "reelle": (
        "echo 'Saving debug log to /var/log/letsencrypt/letsencrypt.log'\n"
        "echo 'Certbot failed to authenticate some domains "
        "(authenticator: webroot).' >&2\n"
        "echo '  Domain: ntfy.exemple.test' >&2\n"
        "echo '  Type:   unauthorized' >&2\n"
        "echo '  Detail: 192.0.2.10: Invalid response from "
        "http://ntfy.exemple.test/.well-known/acme-challenge/x: 404' >&2\n"
        "echo '' >&2\n"
        "echo 'Some challenges have failed.' >&2\n"
        "echo 'Ask for help or search for solutions at "
        "https://community.letsencrypt.org. See the logfile "
        "/var/log/letsencrypt/letsencrypt.log or re-run Certbot with -v "
        "for more details.' >&2\n"
    ),
}

CERTBOT = """#!/bin/sh
echo "certbot $*" >> "$CB_LOG"
if [ -e "$R/etc/letsencrypt/renewal/erplibre-call.conf" ]; then
    echo "conf presente" >> "$CB_CONF"
else
    echo "conf absente" >> "$CB_CONF"
fi
n=$(wc -l < "$CB_LOG")
case " $* " in
    *" --dry-run "*) essai=1 ;;
    *) essai=0 ;;
esac
if { [ "$essai" = 1 ] && [ -n "$CB_ECHEC_ESSAI" ]; } \\
        || { [ "$essai" = 0 ] && [ -n "$CB_ECHEC_REEL" ]; }; then
    . "$CB_SORTIE"
    exit 1
fi
[ "$essai" = 1 ] && exit 0
live="$R/etc/letsencrypt/live/erplibre-call"
if [ -e "$live/cert.pem" ] && [ -z "$CB_ECHU" ]; then
    echo 'Certificate not yet due for renewal; no action taken.'
    exit 0
fi
arch="$R/etc/letsencrypt/archive/erplibre-call"
mkdir -p "$arch" "$live" "$R/etc/letsencrypt/renewal"
k=$(ls "$arch" | grep -c '^cert' || true)
k=$((k + 1))
for f in cert chain fullchain privkey; do
    echo "$f $k" > "$arch/$f$k.pem"
    ln -sfn "../../archive/erplibre-call/$f$k.pem" "$live/$f.pem"
done
echo "[renewalparams]" > "$R/etc/letsencrypt/renewal/erplibre-call.conf"
echo 'Successfully received certificate.'
exit 0
"""

BOUCHONS = {
    "systemctl": """#!/bin/sh
echo "systemctl $*" >> "$J"
case "$1" in
    is-enabled)
        [ "$2" = --quiet ] && shift
        [ -e "$ETATS/$2.enabled" ]; exit ;;
    is-active)
        [ "$2" = --quiet ] && shift
        [ -e "$ETATS/$2.active" ]; exit ;;
    enable)
        u="$2"; [ "$2" = --now ] && u="$3"
        [ -n "$SYSTEMCTL_ECHEC" ] && exit 1
        : > "$ETATS/$u.enabled"
        [ "$2" = --now ] && : > "$ETATS/$u.active" ;;
    start) : > "$ETATS/$2.active" ;;
esac
exit 0
""",
    "dpkg-query": """#!/bin/sh
echo "dpkg-query $*" >> "$J"
for p; do :; done
[ -e "$PAQUETS/$p" ] && echo "install ok installed" && exit 0
exit 1
""",
    "dpkg": """#!/bin/sh
echo "dpkg $*" >> "$J"
exit 0
""",
    # Comme apt : la langue suit LC_ALL, puis LC_MESSAGES, puis LANG ; en
    # francais, une espace insecable precede le deux-points.
    "apt-cache": """#!/bin/sh
echo "apt-cache $*" >> "$J"
for p; do :; done
echo "$p:"
case "${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}" in
    fr*) installe="  Install\\303\\251\\302\\240: (aucun)"
         candidat="  Candidat\\302\\240:"; aucun="(aucun)" ;;
    *) installe="  Installed: (none)"
       candidat="  Candidate:"; aucun="(none)" ;;
esac
printf "$installe\\n"
case " $APT_SANS_CANDIDAT " in
    *" $p "*) printf "$candidat %s\\n" "$aucun" ;;
    *) printf "$candidat %s\\n" 4.0.0-1 ;;
esac
exit 0
""",
    "apt-get": """#!/bin/sh
echo "apt-get $*" >> "$J"
case " $* " in
    *" install "*)
        [ -n "$APT_ECHEC" ] && exit 100
        for p; do
            case "$p" in
                -*|install) ;;
                *) : > "$PAQUETS/$p"
                   [ "$p" = certbot ] && cp "$CB_SRC" "$BOUCHONS/certbot" ;;
            esac
        done ;;
esac
exit 0
""",
    "pacman": """#!/bin/sh
echo "pacman $*" >> "$J"
case "$1" in
    -Q) [ -e "$PAQUETS/$2" ]; exit ;;
    -S)
        for p; do
            case "$p" in
                -*) ;;
                *) : > "$PAQUETS/$p"
                   [ "$p" = certbot ] && cp "$CB_SRC" "$BOUCHONS/certbot" ;;
            esac
        done ;;
esac
exit 0
""",
}


def source():
    with open(SCRIPT, encoding="utf-8") as flux:
        return flux.read()


def extraire_fonction(nom):
    """Rend la fonction shell demandee, seule, cherchee en debut de ligne."""
    texte = source()
    trouve = re.search(r"^%s\(\) \{" % re.escape(nom), texte, re.M)
    if trouve is None:
        raise AssertionError(
            "fonction absente de install_certbot.sh : %s" % nom)
    debut = trouve.start()
    fin = texte.index("\n}\n", debut) + 3
    return texte[debut:fin]


def script_sous(racine):
    """Le script entier, ROOT pointe sur `racine`, check_root neutralise et
    main appele par l'enveloppe."""
    texte = source()
    if not re.search(r'^ROOT=""$', texte, re.M):
        raise AssertionError('constante absente : ROOT=""')
    texte = re.sub(r'^ROOT=""$', 'ROOT="%s"' % racine, texte, count=1,
                   flags=re.M)
    if not texte.endswith('\nmain "$@"\n'):
        raise AssertionError('le script ne finit pas par main "$@"')
    texte = texte[: -len('main "$@"\n')]
    return texte + 'check_root() { :; }\nmain\n'


def lire(chemin):
    with open(chemin, encoding="utf-8") as flux:
        return flux.read()


def ecrire(chemin, texte, mode=None):
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    with open(chemin, "w", encoding="utf-8") as flux:
        flux.write(texte)
    if mode is not None:
        os.chmod(chemin, mode)


def chemin_sans_certbot():
    """Le PATH de l'hote prive des dossiers qui portent un vrai certbot :
    « absent » doit le rester sur une machine qui l'a."""
    garde = []
    for dossier in os.environ.get("PATH", "").split(os.pathsep):
        if dossier and not os.path.exists(os.path.join(dossier, "certbot")):
            garde.append(dossier)
    return os.pathsep.join(garde)


class Hote:
    """Une racine temporaire, ses bouchons et le journal de leurs appels.

    `minuteur` : le minuteur que livre le paquet certbot (« certbot.timer »
    sous Debian, « certbot-renew.timer » sous Arch, None pour aucun) ;
    `actif` dit s'il est deja active et demarre."""

    def __init__(self, dossier, os_release=OS_DEBIAN, certbot=True,
                 minuteur="certbot.timer", actif=True, paquets=()):
        self.dossier = dossier
        self.racine = os.path.join(dossier, "racine")
        self.bouchons = os.path.join(dossier, "bouchons")
        self.journal = os.path.join(dossier, "appels")
        self.cb_log = os.path.join(dossier, "certbot.argv")
        self.cb_conf = os.path.join(dossier, "certbot.conf")
        self.cb_src = os.path.join(dossier, "certbot.src")
        self.cb_sortie = os.path.join(dossier, "certbot.sortie")
        self.etats = os.path.join(dossier, "etats")
        self.paquets = os.path.join(dossier, "paquets")
        for chemin in (self.racine, self.bouchons, self.etats,
                       self.paquets):
            os.makedirs(chemin)
        ecrire(self.chemin("/etc/os-release"), os_release)
        ecrire(self.cb_src, CERTBOT, 0o755)
        self.sortie("simple")
        for nom, texte in BOUCHONS.items():
            ecrire(os.path.join(self.bouchons, nom), texte, 0o755)
        if certbot:
            shutil.copy(self.cb_src, os.path.join(self.bouchons, "certbot"))
            ecrire(os.path.join(self.paquets, "certbot"), "")
        for paquet in paquets:
            ecrire(os.path.join(self.paquets, paquet), "")
        if minuteur:
            ecrire(self.chemin("/usr/lib/systemd/system/" + minuteur),
                   "[Timer]\nOnCalendar=*-*-* 00,12:00:00\n")
            if actif:
                ecrire(os.path.join(self.etats, minuteur + ".enabled"), "")
                ecrire(os.path.join(self.etats, minuteur + ".active"), "")

    def chemin(self, chemin_hote):
        return self.racine + chemin_hote

    def sortie(self, forme):
        ecrire(self.cb_sortie, SORTIES[forme])

    def appels(self):
        if not os.path.exists(self.journal):
            return []
        return lire(self.journal).splitlines()

    def certbot(self):
        """Les argv de chaque appel a certbot, un par ligne."""
        if not os.path.exists(self.cb_log):
            return []
        return lire(self.cb_log).splitlines()

    def conf_vue_par_certbot(self):
        if not os.path.exists(self.cb_conf):
            return []
        return lire(self.cb_conf).splitlines()

    def oublier_appels(self):
        for chemin in (self.journal, self.cb_log, self.cb_conf):
            if os.path.exists(chemin):
                os.remove(chemin)

    def avec_webroot(self):
        os.makedirs(self.chemin(ACME), exist_ok=True)

    def avec_identifiants(self, mode=0o600):
        ecrire(self.chemin(IDENTIFIANTS),
               "dns_ovh_application_secret = %s\n" % SECRET, mode)

    def jouer(self, **variables):
        env = dict(os.environ)
        env.update({
            "PATH": self.bouchons + os.pathsep + chemin_sans_certbot(),
            "J": self.journal, "R": self.racine, "ETATS": self.etats,
            "PAQUETS": self.paquets, "BOUCHONS": self.bouchons,
            "CB_LOG": self.cb_log, "CB_CONF": self.cb_conf,
            "CB_SRC": self.cb_src, "CB_SORTIE": self.cb_sortie,
        })
        for nom in list(env):
            if nom.startswith("CERTBOT_"):
                del env[nom]
        env.update(variables)
        return subprocess.run(["bash", "-c", script_sous(self.racine)],
                              capture_output=True, text=True, env=env,
                              timeout=60)


def entrees(methode="webroot", **autres):
    valeurs = {
        "CERTBOT_NAMES": "%s %s" % (NTFY, TURN),
        "CERTBOT_METHOD": methode,
        "CERTBOT_EMAIL": COURRIEL,
    }
    if methode == "webroot":
        valeurs["CERTBOT_WEBROOT"] = ACME
    if methode == "dns":
        valeurs["CERTBOT_DNS_PLUGIN"] = "ovh"
        valeurs["CERTBOT_DNS_CREDENTIALS"] = IDENTIFIANTS
    valeurs.update(autres)
    return valeurs


def marqueurs(sortie, nom):
    return [ligne.split(" ", 1)[1] if " " in ligne else ""
            for ligne in sortie.splitlines()
            if ligne.split(" ", 1)[0] == "@@" + nom]


def derniere(sortie):
    return sortie.strip().splitlines()[-1]


class TestArguments(unittest.TestCase):
    """Les argv passes a certbot, methode par methode."""

    def test_webroot(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier)
            hote.avec_webroot()
            fait = hote.jouer(**entrees())
            self.assertEqual(fait.returncode, 0, fait.stdout + fait.stderr)
            appels = hote.certbot()
            self.assertEqual(len(appels), 2, appels)
            for argv in appels:
                self.assertIn(" --webroot -w %s " % ACME, argv + " ")
                self.assertIn(" --cert-name erplibre-call ", argv)
                self.assertIn(" --non-interactive --agree-tos ", argv)
                self.assertTrue(
                    argv.endswith(" -d %s -d %s" % (NTFY, TURN)), argv)
                self.assertNotIn("--standalone", argv)

    def test_essai_puis_delivrance(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier)
            hote.avec_webroot()
            fait = hote.jouer(**entrees())
            self.assertEqual(fait.returncode, 0, fait.stdout + fait.stderr)
            essai, reel = hote.certbot()
            self.assertTrue(essai.startswith("certbot certonly --dry-run "),
                            essai)
            self.assertNotIn("--keep-until-expiring", essai)
            self.assertNotIn("--dry-run", reel)
            self.assertTrue(reel.startswith("certbot certonly "), reel)
            self.assertIn(" --keep-until-expiring ", reel)
            self.assertIn(" --expand ", reel)
            # Meme methode, memes noms : seuls les drapeaux d'essai et de
            # delivrance different.
            self.assertEqual(
                essai.replace(" --dry-run", ""),
                reel.replace(" --keep-until-expiring --expand", ""))

    def test_autonome(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier)
            fait = hote.jouer(**entrees("standalone"))
            self.assertEqual(fait.returncode, 0, fait.stdout + fait.stderr)
            for argv in hote.certbot():
                self.assertIn(" --standalone ", argv)
                self.assertNotIn("--webroot", argv)

    def test_dns(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier, os_release=OS_ARCH,
                        minuteur="certbot-renew.timer",
                        paquets=("certbot-dns-ovh",))
            hote.avec_identifiants()
            fait = hote.jouer(**entrees("dns"))
            self.assertEqual(fait.returncode, 0, fait.stdout + fait.stderr)
            appels = hote.certbot()
            self.assertEqual(len(appels), 2, appels)
            for argv in appels:
                self.assertIn(
                    " --dns-ovh --dns-ovh-credentials %s " % IDENTIFIANTS,
                    argv)
                self.assertNotIn("--webroot", argv)
                self.assertNotIn("--standalone", argv)

    def test_identifiants_jamais_imprimes(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier, os_release=OS_ARCH,
                        minuteur="certbot-renew.timer",
                        paquets=("certbot-dns-ovh",))
            hote.avec_identifiants()
            for variables in ({}, {"CB_ECHEC_ESSAI": "1"}):
                fait = hote.jouer(**variables, **entrees("dns"))
                self.assertNotIn(SECRET, fait.stdout + fait.stderr)
                self.assertNotIn(SECRET, "\n".join(hote.certbot()))

    def test_courriel(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier)
            hote.avec_webroot()
            fait = hote.jouer(**entrees())
            self.assertEqual(fait.returncode, 0, fait.stdout + fait.stderr)
            for argv in hote.certbot():
                self.assertIn(" --email %s " % COURRIEL, argv)
                self.assertIn(" --no-eff-email ", argv)
                self.assertNotIn("--register-unsafely-without-email", argv)

    def test_sans_courriel(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier)
            hote.avec_webroot()
            fait = hote.jouer(**entrees(CERTBOT_EMAIL=""))
            self.assertEqual(fait.returncode, 0, fait.stdout + fait.stderr)
            appels = hote.certbot()
            self.assertEqual(len(appels), 2)
            for argv in appels:
                self.assertIn(" --register-unsafely-without-email ", argv)
                self.assertNotIn("--email", argv)
            self.assertIn("sans courriel", fait.stderr + fait.stdout)

    def test_jamais_le_greffon_nginx(self):
        """Le greffon --nginx reecrit les sites : aucun argv ne le porte,
        quelle que soit la methode ou l'issue."""
        cas = (("webroot", {}), ("standalone", {}), ("dns", {}),
               ("webroot", {"CB_ECHEC_ESSAI": "1"}),
               ("webroot", {"CB_ECHEC_REEL": "1"}),
               ("webroot", {"CERTBOT_SKIP_STAGING": "1"}))
        for methode, variables in cas:
            with tempfile.TemporaryDirectory() as dossier:
                hote = Hote(dossier, os_release=OS_ARCH,
                            minuteur="certbot-renew.timer",
                            paquets=("certbot-dns-ovh",))
                hote.avec_webroot()
                hote.avec_identifiants()
                hote.jouer(**variables, **entrees(methode))
                appels = hote.certbot()
                self.assertTrue(appels, (methode, variables))
                for argv in appels:
                    self.assertNotIn("--nginx", argv, (methode, variables))
                    self.assertNotIn(" nginx", argv, (methode, variables))


class TestEchec(unittest.TestCase):
    """Review Focus 2 : certbot echoue (nom qui ne pointe pas sur l'hote,
    port 80 bloque, limite de debit, mauvais identifiants DNS)."""

    def test_essai_en_echec_aucune_delivrance(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier, os_release=OS_ARCH, minuteur=None)
            hote.avec_webroot()
            fait = hote.jouer(CB_ECHEC_ESSAI="1", **entrees())
            self.assertNotEqual(fait.returncode, 0, fait.stdout)
            appels = hote.certbot()
            self.assertEqual(len(appels), 1, appels)
            self.assertIn("--dry-run", appels[0])
            self.assertEqual(derniere(fait.stdout),
                             "@@CERTBOT failed Some challenges have failed.")
            self.assertEqual(marqueurs(fait.stdout, "CERTBOT"),
                             ["failed Some challenges have failed."])
            self.assertFalse(os.path.lexists(hote.chemin(LIGNEE)))
            # Rien d'autre n'est pose : ni minuteur, ni unite.
            self.assertFalse(os.path.exists(hote.chemin(UNITE_MINUTEUR)))
            self.assertFalse([a for a in hote.appels() if "enable" in a])

    def test_ligne_detail_preferee_a_l_aide(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier)
            hote.avec_webroot()
            hote.sortie("reelle")
            fait = hote.jouer(CB_ECHEC_ESSAI="1", **entrees())
            self.assertNotEqual(fait.returncode, 0)
            self.assertEqual(
                derniere(fait.stdout),
                "@@CERTBOT failed Detail: 192.0.2.10: Invalid response from "
                "http://ntfy.exemple.test/.well-known/acme-challenge/x: 404")
            # La sortie de certbot reste visible, sur stderr.
            self.assertIn("Some challenges have failed.", fait.stderr)

    def test_delivrance_en_echec(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier)
            hote.avec_webroot()
            fait = hote.jouer(CB_ECHEC_REEL="1", **entrees())
            self.assertNotEqual(fait.returncode, 0, fait.stdout)
            self.assertEqual(len(hote.certbot()), 2)
            self.assertEqual(marqueurs(fait.stdout, "CERTBOT"),
                             ["staging-ok",
                              "failed Some challenges have failed."])


class TestLignee(unittest.TestCase):

    def test_premiere_delivrance(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier)
            hote.avec_webroot()
            fait = hote.jouer(**entrees())
            self.assertEqual(fait.returncode, 0, fait.stdout + fait.stderr)
            self.assertEqual(marqueurs(fait.stdout, "CERTBOT"),
                             ["staging-ok", "issued " + LIGNEE])
            self.assertEqual(derniere(fait.stdout),
                             "@@CERTBOT issued " + LIGNEE)

    def test_repasse_sans_echeance(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier)
            hote.avec_webroot()
            hote.jouer(**entrees())
            hote.oublier_appels()
            fait = hote.jouer(**entrees())
            self.assertEqual(fait.returncode, 0, fait.stdout + fait.stderr)
            self.assertEqual(derniere(fait.stdout),
                             "@@CERTBOT unchanged " + LIGNEE)

    def test_renouvelee_a_echeance(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier)
            hote.avec_webroot()
            hote.jouer(**entrees())
            fait = hote.jouer(CB_ECHU="1", **entrees())
            self.assertEqual(fait.returncode, 0, fait.stdout + fait.stderr)
            self.assertEqual(derniere(fait.stdout),
                             "@@CERTBOT issued " + LIGNEE)

    def test_sans_essai_quand_la_lignee_existe(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier)
            hote.avec_webroot()
            hote.jouer(**entrees())
            hote.oublier_appels()
            fait = hote.jouer(CERTBOT_SKIP_STAGING="1", **entrees())
            self.assertEqual(fait.returncode, 0, fait.stdout + fait.stderr)
            appels = hote.certbot()
            self.assertEqual(len(appels), 1, appels)
            self.assertNotIn("--dry-run", appels[0])
            self.assertIn("--keep-until-expiring", appels[0])
            self.assertEqual(marqueurs(fait.stdout, "CERTBOT"),
                             ["unchanged " + LIGNEE])

    def test_sans_lignee_l_essai_a_lieu_quand_meme(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier)
            hote.avec_webroot()
            fait = hote.jouer(CERTBOT_SKIP_STAGING="1", **entrees())
            self.assertEqual(fait.returncode, 0, fait.stdout + fait.stderr)
            appels = hote.certbot()
            self.assertEqual(len(appels), 2, appels)
            self.assertIn("--dry-run", appels[0])

    def test_renouvellement_garde_remis_avant_certbot(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier)
            hote.avec_webroot()
            ecrire(hote.chemin(GARDE), "[renewalparams]\nanterieur\n")
            fait = hote.jouer(**entrees())
            self.assertEqual(fait.returncode, 0, fait.stdout + fait.stderr)
            self.assertEqual(hote.conf_vue_par_certbot()[0], "conf presente")
            self.assertFalse(os.path.lexists(hote.chemin(GARDE)))
            self.assertTrue(os.path.exists(hote.chemin(RENOUVELLEMENT)))
            self.assertEqual(marqueurs(fait.stdout, "CERTBOT_UNHELD"),
                             [RENOUVELLEMENT])

    def test_garde_et_fichier_actif_le_fichier_actif_reste(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier)
            hote.avec_webroot()
            ecrire(hote.chemin(RENOUVELLEMENT), "actif\n")
            ecrire(hote.chemin(GARDE), "garde\n")
            fait = hote.jouer(**entrees())
            self.assertEqual(fait.returncode, 0, fait.stdout + fait.stderr)
            self.assertFalse(os.path.lexists(hote.chemin(GARDE)))
            self.assertEqual(hote.conf_vue_par_certbot()[0], "conf presente")


class TestGardeRemiseEnEchec(unittest.TestCase):
    """Un passage qui a remis le fichier de renouvellement et qui echoue le
    remet de cote : aucun etat ne nomme alors la lignee, et le minuteur du
    paquet ne doit pas la renouveler."""

    def _jouer_en_echec(self, hote, garde="[renewalparams]\nanterieur\n",
                        **variables):
        """`garde` : le contenu attendu de la copie remise de cote."""
        ecrire(hote.chemin(GARDE), "[renewalparams]\nanterieur\n")
        fait = hote.jouer(**variables)
        self.assertNotEqual(fait.returncode, 0, fait.stdout)
        self.assertTrue(derniere(fait.stdout).startswith("@@CERTBOT failed "),
                        fait.stdout)
        self.assertEqual(lire(hote.chemin(GARDE)), garde)
        self.assertFalse(os.path.lexists(hote.chemin(RENOUVELLEMENT)))
        self.assertEqual(marqueurs(fait.stdout, "CERTBOT_REHELD"),
                         [RENOUVELLEMENT])
        return fait

    def test_essai_en_echec(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier)
            hote.avec_webroot()
            self._jouer_en_echec(hote, CB_ECHEC_ESSAI="1", **entrees())
            self.assertEqual(hote.conf_vue_par_certbot(), ["conf presente"])

    def test_delivrance_en_echec(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier)
            hote.avec_webroot()
            self._jouer_en_echec(hote, CB_ECHEC_REEL="1", **entrees())

    def test_minuteur_en_echec(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier, os_release=OS_ARCH, minuteur=None)
            hote.avec_webroot()
            # La delivrance a reussi et reecrit le fichier : c'est cette
            # version qui est remise de cote.
            self._jouer_en_echec(hote, garde="[renewalparams]\n",
                                 SYSTEMCTL_ECHEC="1", **entrees())

    def test_succes_garde_le_fichier_actif(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier)
            hote.avec_webroot()
            ecrire(hote.chemin(GARDE), "[renewalparams]\nanterieur\n")
            fait = hote.jouer(**entrees())
            self.assertEqual(fait.returncode, 0, fait.stdout + fait.stderr)
            self.assertTrue(os.path.exists(hote.chemin(RENOUVELLEMENT)))
            self.assertFalse(os.path.lexists(hote.chemin(GARDE)))
            self.assertEqual(marqueurs(fait.stdout, "CERTBOT_REHELD"), [])

    def test_sans_garde_au_depart_rien_n_est_mis_de_cote(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier)
            hote.avec_webroot()
            ecrire(hote.chemin(RENOUVELLEMENT), "actif\n")
            fait = hote.jouer(CB_ECHEC_ESSAI="1", **entrees())
            self.assertNotEqual(fait.returncode, 0, fait.stdout)
            self.assertEqual(lire(hote.chemin(RENOUVELLEMENT)), "actif\n")
            self.assertFalse(os.path.lexists(hote.chemin(GARDE)))
            self.assertEqual(marqueurs(fait.stdout, "CERTBOT_REHELD"), [])


class TestEntrees(unittest.TestCase):
    """Refus avant tout appel a certbot ou au gestionnaire de paquets."""

    def _refus(self, hote, **variables):
        fait = hote.jouer(**variables)
        self.assertNotEqual(fait.returncode, 0, fait.stdout)
        self.assertTrue(derniere(fait.stdout).startswith("@@CERTBOT failed "),
                        fait.stdout)
        self.assertEqual(hote.certbot(), [])
        self.assertFalse([a for a in hote.appels()
                          if a.startswith(("apt-get", "pacman -S"))])
        return fait

    def test_methode_inconnue(self):
        with tempfile.TemporaryDirectory() as dossier:
            self._refus(Hote(dossier), **entrees("nginx"))

    def test_nom_joker(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier)
            hote.avec_webroot()
            self._refus(hote, **entrees(CERTBOT_NAMES="*.exemple.test"))

    def test_sans_nom(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier)
            hote.avec_webroot()
            self._refus(hote, **entrees(CERTBOT_NAMES=""))

    def test_courriel_invalide(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier)
            hote.avec_webroot()
            self._refus(hote, **entrees(CERTBOT_EMAIL="a b@exemple.test"))

    def test_webroot_absent(self):
        with tempfile.TemporaryDirectory() as dossier:
            fait = self._refus(Hote(dossier), **entrees())
            self.assertIn(ACME, derniere(fait.stdout))

    def test_greffon_inconnu(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier)
            hote.avec_identifiants()
            self._refus(hote, **entrees("dns", CERTBOT_DNS_PLUGIN="route53"))

    def test_identifiants_absents(self):
        with tempfile.TemporaryDirectory() as dossier:
            fait = self._refus(Hote(dossier), **entrees("dns"))
            self.assertIn(IDENTIFIANTS, derniere(fait.stdout))

    def test_identifiants_lisibles_par_d_autres(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier)
            hote.avec_identifiants(0o644)
            fait = self._refus(hote, **entrees("dns"))
            self.assertIn("644", derniere(fait.stdout))
            self.assertNotIn(SECRET, fait.stdout + fait.stderr)


class TestPaquets(unittest.TestCase):

    def test_debian_certbot_installe(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier, certbot=False)
            hote.avec_webroot()
            fait = hote.jouer(**entrees())
            self.assertEqual(fait.returncode, 0, fait.stdout + fait.stderr)
            installe = [a for a in hote.appels()
                        if a.startswith("apt-get") and " install " in a]
            self.assertEqual(len(installe), 1, hote.appels())
            self.assertTrue(installe[0].endswith(" certbot"), installe)
            self.assertIn("--no-install-recommends", installe[0])
            self.assertEqual(marqueurs(fait.stdout, "CERTBOT_INSTALLED"),
                             ["1"])

    def test_certbot_present_rien_n_est_installe(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier)
            hote.avec_webroot()
            fait = hote.jouer(**entrees())
            self.assertEqual(fait.returncode, 0, fait.stdout + fait.stderr)
            self.assertFalse([a for a in hote.appels()
                              if a.startswith(("apt-get", "dpkg "))])
            self.assertEqual(marqueurs(fait.stdout, "CERTBOT_INSTALLED"), [])

    def test_debian_greffon_installe(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier)
            ecrire(hote.chemin("/etc/erplibre-call/dns/cloudflare.ini"),
                   "dns_cloudflare_api_token = %s\n" % SECRET, 0o600)
            fait = hote.jouer(**entrees(
                "dns", CERTBOT_DNS_PLUGIN="cloudflare",
                CERTBOT_DNS_CREDENTIALS="/etc/erplibre-call/dns/"
                                        "cloudflare.ini"))
            self.assertEqual(fait.returncode, 0, fait.stdout + fait.stderr)
            installe = [a for a in hote.appels()
                        if a.startswith("apt-get") and " install " in a]
            self.assertEqual(len(installe), 1, hote.appels())
            self.assertTrue(
                installe[0].endswith(" python3-certbot-dns-cloudflare"),
                installe)
            self.assertEqual(marqueurs(fait.stdout, "CERTBOT_INSTALLED"), [])
            self.assertEqual(
                marqueurs(fait.stdout, "CERTBOT_PLUGIN_INSTALLED"),
                ["python3-certbot-dns-cloudflare"])

    def test_debian_greffon_sans_paquet_refuse(self):
        """Debian 13 ne livre pas tous les greffons : le refus nomme le
        paquet manquant, avant tout appel a certbot."""
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier)
            hote.avec_identifiants()
            fait = hote.jouer(APT_SANS_CANDIDAT="python3-certbot-dns-ovh",
                              **entrees("dns"))
            self.assertNotEqual(fait.returncode, 0, fait.stdout)
            self.assertIn("python3-certbot-dns-ovh", derniere(fait.stdout))
            self.assertTrue(derniere(fait.stdout).startswith(
                "@@CERTBOT failed "))
            self.assertEqual(hote.certbot(), [])
            self.assertFalse([a for a in hote.appels()
                              if a.startswith("apt-get") and " install " in a])

    def test_debian_greffon_sous_un_systeme_en_francais(self):
        """apt lit la langue de l'hote, que sudo et ssh transmettent : le
        greffon livre est trouve meme quand apt ecrit « Candidat : »."""
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier)
            hote.avec_identifiants()
            fait = hote.jouer(LANG="fr_CA.UTF-8", LC_ALL="",
                              LC_MESSAGES="", **entrees("dns"))
            self.assertEqual(fait.returncode, 0, fait.stdout + fait.stderr)
            self.assertEqual(
                marqueurs(fait.stdout, "CERTBOT_PLUGIN_INSTALLED"),
                ["python3-certbot-dns-ovh"])

    def test_debian_greffon_sans_paquet_refuse_en_francais(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier)
            hote.avec_identifiants()
            fait = hote.jouer(LANG="fr_CA.UTF-8", LC_ALL="",
                              LC_MESSAGES="",
                              APT_SANS_CANDIDAT="python3-certbot-dns-ovh",
                              **entrees("dns"))
            self.assertNotEqual(fait.returncode, 0, fait.stdout)
            self.assertIn("python3-certbot-dns-ovh", derniere(fait.stdout))
            self.assertEqual(hote.certbot(), [])

    def test_arch_greffon_installe(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier, os_release=OS_ARCH, certbot=False,
                        minuteur="certbot-renew.timer")
            hote.avec_identifiants()
            fait = hote.jouer(**entrees("dns"))
            self.assertEqual(fait.returncode, 0, fait.stdout + fait.stderr)
            installe = [a for a in hote.appels() if a.startswith("pacman -S")]
            self.assertEqual(
                installe,
                ["pacman -S --noconfirm --needed certbot",
                 "pacman -S --noconfirm --needed certbot-dns-ovh"])
            self.assertEqual(marqueurs(fait.stdout, "CERTBOT_INSTALLED"),
                             ["1"])
            self.assertEqual(
                marqueurs(fait.stdout, "CERTBOT_PLUGIN_INSTALLED"),
                ["certbot-dns-ovh"])

    def test_installation_en_echec(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier, certbot=False)
            hote.avec_webroot()
            fait = hote.jouer(APT_ECHEC="1", **entrees())
            self.assertNotEqual(fait.returncode, 0)
            self.assertTrue(derniere(fait.stdout).startswith(
                "@@CERTBOT failed "), fait.stdout)
            self.assertEqual(hote.certbot(), [])


class TestMinuteur(unittest.TestCase):

    def test_debian_minuteur_du_paquet_deja_actif(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier)
            hote.avec_webroot()
            fait = hote.jouer(**entrees())
            self.assertEqual(fait.returncode, 0, fait.stdout + fait.stderr)
            self.assertEqual(marqueurs(fait.stdout, "CERTBOT_TIMER"),
                             ["certbot.timer present"])
            self.assertFalse(os.path.exists(hote.chemin(UNITE_MINUTEUR)))
            self.assertFalse([a for a in hote.appels()
                              if a.startswith(("systemctl enable",
                                               "systemctl start"))])

    def test_arch_minuteur_du_paquet_active(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier, os_release=OS_ARCH,
                        minuteur="certbot-renew.timer", actif=False)
            hote.avec_webroot()
            fait = hote.jouer(**entrees())
            self.assertEqual(fait.returncode, 0, fait.stdout + fait.stderr)
            self.assertIn("systemctl enable --now certbot-renew.timer",
                          hote.appels())
            self.assertEqual(marqueurs(fait.stdout, "CERTBOT_TIMER"),
                             ["certbot-renew.timer added"])
            self.assertFalse(os.path.exists(hote.chemin(UNITE_MINUTEUR)))
            # Le minuteur active par l'outil le reste a la repasse :
            # la desinstallation ne coupera que lui.
            hote.oublier_appels()
            fait = hote.jouer(**entrees())
            self.assertEqual(fait.returncode, 0, fait.stdout + fait.stderr)
            self.assertEqual(marqueurs(fait.stdout, "CERTBOT_TIMER"),
                             ["certbot-renew.timer added"])
            self.assertFalse([a for a in hote.appels()
                              if a.startswith("systemctl enable")])

    def test_arch_sans_minuteur_du_paquet_les_deux_unites(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier, os_release=OS_ARCH, minuteur=None)
            hote.avec_webroot()
            fait = hote.jouer(**entrees())
            self.assertEqual(fait.returncode, 0, fait.stdout + fait.stderr)
            service = lire(hote.chemin(UNITE_SERVICE))
            minuteur = lire(hote.chemin(UNITE_MINUTEUR))
            self.assertEqual(service.splitlines()[0], MARKER)
            self.assertEqual(minuteur.splitlines()[0], MARKER)
            self.assertRegex(service, r"(?m)^ExecStart=/\S*certbot "
                                      r"renew --quiet$")
            self.assertIn("Type=oneshot", service)
            self.assertIn("OnCalendar=*-*-* 00,12:00:00", minuteur)
            self.assertIn("WantedBy=timers.target", minuteur)
            appels = hote.appels()
            self.assertIn("systemctl daemon-reload", appels)
            self.assertIn(
                "systemctl enable --now erplibre-call-certbot.timer", appels)
            self.assertLess(
                appels.index("systemctl daemon-reload"),
                appels.index(
                    "systemctl enable --now erplibre-call-certbot.timer"))
            self.assertEqual(marqueurs(fait.stdout, "CERTBOT_TIMER"),
                             ["erplibre-call-certbot.timer added"])
            # Repasse : unites identiques, rien a recharger.
            hote.oublier_appels()
            fait = hote.jouer(**entrees())
            self.assertEqual(fait.returncode, 0, fait.stdout + fait.stderr)
            self.assertEqual(lire(hote.chemin(UNITE_MINUTEUR)), minuteur)
            self.assertNotIn("systemctl daemon-reload", hote.appels())
            self.assertEqual(marqueurs(fait.stdout, "CERTBOT_TIMER"),
                             ["erplibre-call-certbot.timer added"])

    def test_unite_etrangere_au_meme_nom_refusee(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier, os_release=OS_ARCH, minuteur=None)
            hote.avec_webroot()
            ecrire(hote.chemin(UNITE_MINUTEUR), "[Timer]\nOnCalendar=daily\n")
            fait = hote.jouer(**entrees())
            self.assertNotEqual(fait.returncode, 0)
            self.assertIn(UNITE_MINUTEUR, derniere(fait.stdout))
            self.assertEqual(lire(hote.chemin(UNITE_MINUTEUR)),
                             "[Timer]\nOnCalendar=daily\n")

    def test_activation_en_echec(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier, os_release=OS_ARCH, minuteur=None)
            hote.avec_webroot()
            fait = hote.jouer(SYSTEMCTL_ECHEC="1", **entrees())
            self.assertNotEqual(fait.returncode, 0)
            self.assertTrue(derniere(fait.stdout).startswith(
                "@@CERTBOT failed "), fait.stdout)


class TestFonctions(unittest.TestCase):

    def test_derniere_ligne_d_erreur_ignore_l_aide(self):
        texte = ("Saving debug log to /x.log\n"
                 "An unexpected error occurred:\n"
                 "Too many certificates already issued for this set\n"
                 "Ask for help or search for solutions at https://x. "
                 "See the logfile /x.log or re-run Certbot with -v\n\n")
        fait = subprocess.run(
            ["bash", "-c", extraire_fonction("last_error_line")
             + "last_error_line"],
            input=texte, capture_output=True, text=True, timeout=30)
        self.assertEqual(fait.stdout.strip(),
                         "Too many certificates already issued for this set")

    def test_mode_du_script(self):
        mode = stat.S_IMODE(os.stat(SCRIPT).st_mode)
        self.assertTrue(mode & 0o100, oct(mode))


if __name__ == "__main__":
    unittest.main()
