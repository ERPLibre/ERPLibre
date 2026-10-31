#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'installateur nginx de l'infrastructure d'appel, sans root ni service.

Le script est joue en entier sous une racine temporaire : sa constante
ROOT, vide en production, prefixe chaque chemin de l'hote qu'il lit ou
ecrit. Les commandes systeme (`apt-get`, `pacman`, `dpkg-query`, `nginx`,
`systemctl`) sont des bouchons qui notent leurs appels ; `nginx -t` echoue
sur demande, `systemctl is-active` rend l'etat d'un fichier.

Les nginx.conf de depart sont ceux que livrent les paquets Debian 13 et
Arch Linux, releves dans des conteneurs jetables. Les noms et les ports
sont inventes (`*.exemple.test`).
"""
import os
import re
import stat
import subprocess
import tempfile
import unittest

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(RACINE, "script/install/install_nginx.sh")

NTFY = "ntfy.exemple.test"
TURN = "turn.exemple.test"
PORT = "2586"
LIGNEE = "/etc/letsencrypt/live/erplibre-call"
ACME = "/var/lib/erplibre-call/acme"
INCLUDE = "include /etc/nginx/erplibre-call.d/*.conf;"

# nginx.conf du paquet Debian 13 (le bloc mail commente en moins).
CONF_DEBIAN = """user www-data;
worker_processes auto;
worker_cpu_affinity auto;
pid /run/nginx.pid;
error_log /var/log/nginx/error.log;
include /etc/nginx/modules-enabled/*.conf;

events {
\tworker_connections 768;
}

http {
\tsendfile on;
\ttcp_nopush on;
\ttypes_hash_max_size 2048;
\tserver_tokens off;
\tinclude /etc/nginx/mime.types;
\tdefault_type application/octet-stream;
\tssl_protocols TLSv1.2 TLSv1.3;
\tssl_prefer_server_ciphers off;
\taccess_log /var/log/nginx/access.log;
\tgzip on;
\tinclude /etc/nginx/conf.d/*.conf;
\tinclude /etc/nginx/sites-enabled/*;
}
"""

# nginx.conf du paquet Arch Linux : aucun dossier inclus dans http, un
# serveur en ligne, des exemples commentes avant l'accolade finale.
CONF_ARCH = """
#user http;
worker_processes  1;

#pid        logs/nginx.pid;


# Load all installed modules
include modules.d/*.conf;

events {
    worker_connections  1024;
}


http {
    include       mime.types;
    default_type  application/octet-stream;

    sendfile        on;
    keepalive_timeout  65;

    server {
        listen       80;
        server_name  localhost;

        location / {
            root   /usr/share/nginx/html;
            index  index.html index.htm;
        }

        error_page   500 502 503 504  /50x.html;
        location = /50x.html {
            root   /usr/share/nginx/html;
        }
    }

    # HTTPS server
    #
    #server {
    #    listen       443 ssl;
    #    server_name  localhost;
    #}

}
"""

OS_DEBIAN = 'ID=debian\nVERSION_ID="13"\n'
OS_ARCH = "ID=arch\n"

BOUCHONS = {
    "systemctl": """#!/bin/sh
echo "systemctl $*" >> "$J"
case "$1" in
    is-active)
        s=$(cat "$ETAT" 2>/dev/null || echo active)
        [ "$2" = --quiet ] || echo "$s"
        [ "$s" = active ]
        exit
        ;;
    enable)
        [ "$2" = --now ] && echo active > "$ETAT"
        ;;
esac
exit 0
""",
    "nginx": """#!/bin/sh
echo "nginx $*" >> "$J"
if [ "$1" = -t ]; then
    if [ -n "$NGINX_T_ECHEC" ]; then
        echo 'nginx: [emerg] cannot load certificate "/x/fullchain.pem"' >&2
        echo 'nginx: configuration file /etc/nginx/nginx.conf test failed' >&2
        exit 1
    fi
    echo 'nginx: configuration file test is successful' >&2
fi
exit 0
""",
    "dpkg-query": """#!/bin/sh
echo "dpkg-query $*" >> "$J"
[ -e "$PRESENT" ] && echo "install ok installed" && exit 0
exit 1
""",
    "dpkg": """#!/bin/sh
echo "dpkg $*" >> "$J"
exit 0
""",
    "apt-get": """#!/bin/sh
echo "apt-get $*" >> "$J"
case " $* " in
    *" install "*)
        [ -n "$APT_ECHEC" ] && exit 100
        : > "$PRESENT"; mkdir -p "$R/etc/nginx"
        cp "$CONF_APRES" "$R/etc/nginx/nginx.conf" ;;
esac
exit 0
""",
    "pacman": """#!/bin/sh
echo "pacman $*" >> "$J"
case "$1" in
    -Q) [ -e "$PRESENT" ]; exit ;;
    -S) : > "$PRESENT"; mkdir -p "$R/etc/nginx"
        cp "$CONF_APRES" "$R/etc/nginx/nginx.conf" ;;
esac
exit 0
""",
}


def source():
    with open(SCRIPT, encoding="utf-8") as flux:
        return flux.read()


def extraire_fonction(nom):
    """Rend la fonction shell demandee, seule. La definition est cherchee en
    debut de ligne (`nom() {`) : un commentaire qui cite le nom ne la
    remplace pas."""
    texte = source()
    trouve = re.search(r"^%s\(\) \{" % re.escape(nom), texte, re.M)
    if trouve is None:
        raise AssertionError("fonction absente de install_nginx.sh : %s" % nom)
    debut = trouve.start()
    fin = texte.index("\n}\n", debut) + 3
    return texte[debut:fin]


def script_sous(racine):
    """Le script entier, ROOT pointe sur `racine`, check_root neutralise et
    main appele par l'enveloppe : seule la ligne finale `main "$@"` et la
    constante ROOT sont remplacees."""
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


class Hote:
    """Une racine temporaire, ses bouchons et le journal de leurs appels."""

    def __init__(self, dossier, os_release=OS_DEBIAN, conf=CONF_DEBIAN,
                 present=True, actif=True):
        self.racine = os.path.join(dossier, "racine")
        self.bouchons = os.path.join(dossier, "bouchons")
        self.journal = os.path.join(dossier, "appels")
        self.etat = os.path.join(dossier, "etat")
        self.present = os.path.join(dossier, "present")
        self.conf_apres = os.path.join(dossier, "conf_apres")
        os.makedirs(self.racine)
        os.makedirs(self.bouchons)
        ecrire(self.chemin("/etc/os-release"), os_release)
        if conf is not None:
            ecrire(self.chemin("/etc/nginx/nginx.conf"), conf)
        ecrire(self.conf_apres, CONF_DEBIAN if "debian" in os_release
               else CONF_ARCH)
        if present:
            ecrire(self.present, "")
        ecrire(self.etat, "active\n" if actif else "inactive\n")
        for nom, texte in BOUCHONS.items():
            ecrire(os.path.join(self.bouchons, nom), texte, 0o755)

    def chemin(self, chemin_hote):
        return self.racine + chemin_hote

    def appels(self):
        if not os.path.exists(self.journal):
            return []
        return lire(self.journal).splitlines()

    def oublier_appels(self):
        if os.path.exists(self.journal):
            os.remove(self.journal)

    def jouer(self, **variables):
        env = dict(os.environ)
        env.update({
            "PATH": self.bouchons + os.pathsep + env.get("PATH", ""),
            "J": self.journal, "ETAT": self.etat, "PRESENT": self.present,
            "R": self.racine, "CONF_APRES": self.conf_apres,
        })
        for nom in list(env):
            if nom.startswith("NGINX_"):
                del env[nom]
        env.update(variables)
        return subprocess.run(["bash", "-c", script_sous(self.racine)],
                              capture_output=True, text=True, env=env,
                              timeout=60)


def entrees(etape="full", **autres):
    valeurs = {
        "NGINX_STAGE": etape,
        "NGINX_NAMES": "%s %s" % (NTFY, TURN),
        "NGINX_NTFY_NAME": NTFY,
        "NGINX_UPSTREAM_PORT": PORT,
        "NGINX_CERT_FILE": LIGNEE + "/fullchain.pem",
        "NGINX_KEY_FILE": LIGNEE + "/privkey.pem",
        "NGINX_ACME_ROOT": ACME,
    }
    valeurs.update(autres)
    return valeurs


def avec_lignee(hote):
    ecrire(hote.chemin(LIGNEE + "/fullchain.pem"), "certificat invente\n")
    ecrire(hote.chemin(LIGNEE + "/privkey.pem"), "cle inventee\n", 0o600)


def marqueurs(sortie, nom):
    return [ligne.split(" ", 1)[1] if " " in ligne else ""
            for ligne in sortie.splitlines()
            if ligne.split(" ", 1)[0] == "@@" + nom]


SITE_DEBIAN = "/etc/nginx/sites-available/erplibre-call-ntfy.conf"
LIEN_DEBIAN = "/etc/nginx/sites-enabled/erplibre-call-ntfy.conf"
SITE_ARCH = "/etc/nginx/erplibre-call.d/erplibre-call-ntfy.conf"
SITE_CONFD = "/etc/nginx/conf.d/erplibre-call-ntfy.conf"


class TestFamilleEtDisposition(unittest.TestCase):
    """`family` et `layout`, extraites seules."""

    def _famille(self, os_id, os_like=""):
        enveloppe = (
            'die() { echo "ERREUR $*" >&2; exit 1; }\n'
            'OS=%s\nOS_LIKE="%s"\n' % (os_id, os_like)
            + extraire_fonction("family") + "family\n")
        return subprocess.run(["bash", "-c", enveloppe], capture_output=True,
                              text=True, timeout=30)

    def test_familles(self):
        for os_id, like, attendu in (("debian", "", "debian"),
                                     ("ubuntu", "debian", "debian"),
                                     ("arch", "", "arch"),
                                     ("manjaro", "arch", "arch"),
                                     ("autre", "debian", "debian")):
            fait = self._famille(os_id, like)
            self.assertEqual(fait.stdout.strip(), attendu, os_id)

    def test_systeme_non_supporte(self):
        fait = self._famille("fedora", "rhel")
        self.assertNotEqual(fait.returncode, 0)
        self.assertIn("non supporte", fait.stderr)

    def _disposition(self, conf):
        with tempfile.TemporaryDirectory() as dossier:
            ecrire(os.path.join(dossier, "etc/nginx/nginx.conf"), conf)
            enveloppe = (
                'ROOT="%s"\nNGINX_CONF="/etc/nginx/nginx.conf"\n'
                'INCLUDE_DIR="/etc/nginx/erplibre-call.d"\n' % dossier
                + extraire_fonction("has_include")
                + extraire_fonction("layout") + "layout\n")
            fait = subprocess.run(["bash", "-c", enveloppe],
                                  capture_output=True, text=True, timeout=30)
            self.assertEqual(fait.returncode, 0, fait.stderr)
            return fait.stdout.strip()

    def test_debian_inclut_sites_enabled(self):
        self.assertEqual(self._disposition(CONF_DEBIAN), "debian")

    def test_conf_d_seul(self):
        conf = "http {\n    include /etc/nginx/conf.d/*.conf;\n}\n"
        self.assertEqual(self._disposition(conf), "confd")

    def test_chemin_relatif_au_prefixe(self):
        conf = "http {\n    include conf.d/*.conf;\n}\n"
        self.assertEqual(self._disposition(conf), "confd")

    def test_arch_sans_dossier_inclus(self):
        self.assertEqual(self._disposition(CONF_ARCH), "arch-include")

    def test_ligne_deja_adoptee_garde_son_dossier(self):
        """Un conf.d inclus apres coup ne deplace pas le site : il resterait
        un double du meme server_name dans erplibre-call.d."""
        conf = ("http {\n    include /etc/nginx/conf.d/*.conf;\n"
                "    %s\n}\n" % INCLUDE)
        self.assertEqual(self._disposition(conf), "arch-include")

    def test_une_inclusion_commentee_ne_compte_pas(self):
        conf = "http {\n    #include /etc/nginx/sites-enabled/*;\n}\n"
        self.assertEqual(self._disposition(conf), "arch-include")


class TestDebian(unittest.TestCase):

    def test_site_et_lien(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier)
            avec_lignee(hote)
            fait = hote.jouer(**entrees())
            self.assertEqual(fait.returncode, 0, fait.stdout + fait.stderr)
            site = hote.chemin(SITE_DEBIAN)
            lien = hote.chemin(LIEN_DEBIAN)
            self.assertTrue(os.path.isfile(site))
            self.assertTrue(os.path.islink(lien))
            self.assertEqual(os.readlink(lien), SITE_DEBIAN)
            self.assertEqual(stat.S_IMODE(os.stat(site).st_mode), 0o644)
            self.assertEqual(marqueurs(fait.stdout, "NGINX_LAYOUT"),
                             ["debian"])
            self.assertEqual(marqueurs(fait.stdout, "NGINX_SITE"),
                             [SITE_DEBIAN])
            self.assertEqual(marqueurs(fait.stdout, "NGINX_LINK"),
                             [LIEN_DEBIAN])
            self.assertEqual(marqueurs(fait.stdout, "NGINX_INCLUDE"), [])
            self.assertEqual(fait.stdout.strip().splitlines()[-1],
                             "@@NGINX active")
            appels = hote.appels()
            self.assertIn("nginx -t", appels)
            self.assertIn("systemctl reload nginx", appels)
            self.assertLess(appels.index("nginx -t"),
                            appels.index("systemctl reload nginx"))
            # nginx.conf d'un autre n'est pas touche.
            self.assertEqual(lire(hote.chemin("/etc/nginx/nginx.conf")),
                             CONF_DEBIAN)

    def test_nginx_arrete_est_demarre(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier, actif=False)
            avec_lignee(hote)
            fait = hote.jouer(**entrees())
            self.assertEqual(fait.returncode, 0, fait.stdout + fait.stderr)
            appels = hote.appels()
            self.assertIn("systemctl enable --now nginx", appels)
            self.assertNotIn("systemctl reload nginx", appels)

    def test_disposition_conf_d(self):
        with tempfile.TemporaryDirectory() as dossier:
            conf = "http {\n    include /etc/nginx/conf.d/*.conf;\n}\n"
            hote = Hote(dossier, conf=conf)
            avec_lignee(hote)
            fait = hote.jouer(**entrees())
            self.assertEqual(fait.returncode, 0, fait.stdout + fait.stderr)
            self.assertTrue(os.path.isfile(hote.chemin(SITE_CONFD)))
            self.assertEqual(marqueurs(fait.stdout, "NGINX_LAYOUT"),
                             ["confd"])
            self.assertEqual(lire(hote.chemin("/etc/nginx/nginx.conf")), conf)


class TestArch(unittest.TestCase):

    def test_sans_accord_nginx_conf_intact(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier, os_release=OS_ARCH, conf=CONF_ARCH,
                        actif=False)
            avec_lignee(hote)
            fait = hote.jouer(**entrees())
            self.assertNotEqual(fait.returncode, 0, fait.stdout)
            self.assertEqual(lire(hote.chemin("/etc/nginx/nginx.conf")),
                             CONF_ARCH)
            self.assertEqual(sorted(os.listdir(hote.chemin("/etc/nginx"))),
                             ["nginx.conf"])
            self.assertEqual(marqueurs(fait.stdout, "NGINX_ADOPT_NEEDED"),
                             ["/etc/nginx/nginx.conf"])
            # Le changement propose est montre.
            self.assertIn("+    " + INCLUDE, fait.stdout)
            self.assertTrue(fait.stdout.strip().splitlines()[-1]
                            .startswith("@@NGINX failed"))
            self.assertFalse([a for a in hote.appels()
                              if a.startswith("systemctl")
                              and "is-active" not in a])

    def test_avec_accord_une_ligne_dans_http(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier, os_release=OS_ARCH, conf=CONF_ARCH,
                        actif=False)
            avec_lignee(hote)
            fait = hote.jouer(NGINX_ADOPT_INCLUDE="1", **entrees())
            self.assertEqual(fait.returncode, 0, fait.stdout + fait.stderr)
            texte = lire(hote.chemin("/etc/nginx/nginx.conf"))
            lignes = texte.splitlines()
            ici = [i for i, ligne in enumerate(lignes) if INCLUDE in ligne]
            self.assertEqual(len(ici), 1, texte)
            self.assertEqual(lignes[ici[0]], "    " + INCLUDE)
            # Dans http {}, juste avant son accolade finale : les serveurs
            # deja la passent avant, le premier reste le serveur par defaut
            # de son port. Le « #} » commente au-dessus ne ferme rien.
            self.assertLess(lignes.index("http {"), ici[0])
            self.assertEqual(lignes[ici[0] + 1], "}")
            self.assertEqual(lignes[ici[0] + 1:], ["}"])
            # Le reste du fichier est celui d'avant, a la ligne pres.
            del lignes[ici[0]]
            self.assertEqual("\n".join(lignes) + "\n", CONF_ARCH)
            copies = [nom for nom in os.listdir(hote.chemin("/etc/nginx"))
                      if nom.startswith("nginx.conf.bak-")]
            self.assertEqual(len(copies), 1)
            self.assertEqual(
                lire(hote.chemin("/etc/nginx/" + copies[0])), CONF_ARCH)
            self.assertTrue(os.path.isfile(hote.chemin(SITE_ARCH)))
            self.assertEqual(marqueurs(fait.stdout, "NGINX_LAYOUT"),
                             ["arch-include"])
            self.assertEqual(marqueurs(fait.stdout, "NGINX_INCLUDE"),
                             ["/etc/nginx/nginx.conf"])
            self.assertEqual(marqueurs(fait.stdout, "NGINX_BACKUP"),
                             ["/etc/nginx/" + copies[0]])
            self.assertIn("systemctl enable --now nginx", hote.appels())

            # Relance : la ligne est deja la, rien n'est ajoute ni copie.
            hote.oublier_appels()
            fait = hote.jouer(NGINX_ADOPT_INCLUDE="1", **entrees())
            self.assertEqual(fait.returncode, 0, fait.stdout + fait.stderr)
            self.assertEqual(lire(hote.chemin("/etc/nginx/nginx.conf")),
                             texte)
            self.assertEqual(marqueurs(fait.stdout, "NGINX_INCLUDE"), [])
            self.assertEqual(len([n for n in os.listdir(
                hote.chemin("/etc/nginx")) if ".bak-" in n]), 1)

    def test_http_introuvable_refuse(self):
        with tempfile.TemporaryDirectory() as dossier:
            conf = "events {}\nhttp\n{\n}\n"
            hote = Hote(dossier, os_release=OS_ARCH, conf=conf)
            avec_lignee(hote)
            fait = hote.jouer(NGINX_ADOPT_INCLUDE="1", **entrees())
            self.assertNotEqual(fait.returncode, 0, fait.stdout)
            self.assertEqual(lire(hote.chemin("/etc/nginx/nginx.conf")), conf)

    def test_fin_de_http_partagee_refusee(self):
        """L'accolade qui ferme http {} partage sa ligne : la ligne ne se
        place pas sans deviner, rien n'est ecrit."""
        with tempfile.TemporaryDirectory() as dossier:
            conf = 'http {\n    server { return 200 "{"; } }\n'
            hote = Hote(dossier, os_release=OS_ARCH, conf=conf)
            avec_lignee(hote)
            fait = hote.jouer(NGINX_ADOPT_INCLUDE="1", **entrees())
            self.assertNotEqual(fait.returncode, 0, fait.stdout)
            self.assertEqual(lire(hote.chemin("/etc/nginx/nginx.conf")), conf)
            self.assertFalse([n for n in os.listdir(
                hote.chemin("/etc/nginx")) if n != "nginx.conf"])

    def test_accolades_entre_guillemets_ignorees(self):
        with tempfile.TemporaryDirectory() as dossier:
            conf = ('http {\n    server {\n        return 200 "}";\n'
                    "    }\n}\n")
            hote = Hote(dossier, os_release=OS_ARCH, conf=conf)
            avec_lignee(hote)
            fait = hote.jouer(NGINX_ADOPT_INCLUDE="1", **entrees())
            self.assertEqual(fait.returncode, 0, fait.stdout + fait.stderr)
            self.assertEqual(lire(hote.chemin("/etc/nginx/nginx.conf")),
                             conf[:-2] + "    " + INCLUDE + "\n}\n")


class TestContenu(unittest.TestCase):
    """Le texte du site, par etape."""

    def _site(self, etape, inet6=False, **autres):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier)
            avec_lignee(hote)
            if inet6:
                ecrire(hote.chemin("/proc/net/if_inet6"), "invente\n")
            fait = hote.jouer(**entrees(etape, **autres))
            self.assertEqual(fait.returncode, 0, fait.stdout + fait.stderr)
            return lire(hote.chemin(SITE_DEBIAN))

    def test_acme_seulement_le_port_80(self):
        texte = self._site("acme")
        self.assertNotIn("listen 443", texte)
        self.assertNotIn("proxy_pass", texte)
        self.assertNotIn("ssl_certificate", texte)
        self.assertIn("listen 80;", texte)
        self.assertIn("server_name %s %s;" % (NTFY, TURN), texte)
        self.assertIn("location ^~ /.well-known/acme-challenge/ {", texte)
        self.assertIn("root %s;" % ACME, texte)
        self.assertIn("return 301 https://$host$request_uri;", texte)
        self.assertTrue(texte.startswith("# erplibre-call: managed\n"))

    def test_full_mandataire_websocket(self):
        texte = self._site("full")
        for attendu in (
                "map $http_upgrade $erplibre_call_upgrade {",
                "listen 443 ssl;",
                "server_name %s;" % NTFY,
                "ssl_certificate %s/fullchain.pem;" % LIGNEE,
                "ssl_certificate_key %s/privkey.pem;" % LIGNEE,
                "ssl_protocols TLSv1.2 TLSv1.3;",
                "client_max_body_size 20m;",
                "proxy_pass http://127.0.0.1:%s;" % PORT,
                "proxy_http_version 1.1;",
                "proxy_set_header Upgrade $http_upgrade;",
                "proxy_set_header Connection $erplibre_call_upgrade;",
                "proxy_set_header Host $host;",
                "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;",
                "proxy_set_header X-Forwarded-Proto $scheme;",
                "proxy_buffering off;",
                "proxy_read_timeout 3h;",
                # Le port 80 reste celui de l'etape acme.
                "listen 80;",
                "root %s;" % ACME,
        ):
            self.assertIn(attendu, texte)
        self.assertNotIn("[::]", texte)

    def test_ipv6_quand_l_hote_l_a(self):
        texte = self._site("full", inet6=True)
        self.assertIn("listen [::]:80;", texte)
        self.assertIn("listen [::]:443 ssl;", texte)

    def test_jamais_default_server(self):
        for etape in ("acme", "full"):
            for inet6 in (False, True):
                texte = self._site(etape, inet6=inet6)
                self.assertNotIn("default_server", texte)
                self.assertNotIn("server_name _", texte)
                self.assertNotIn("*", texte.split("server_name", 1)[1]
                                 .split(";", 1)[0])

    def test_hote_coturn_seul(self):
        texte = self._site("full", NGINX_NTFY_NAME="", NGINX_NAMES=TURN)
        self.assertNotIn("listen 443", texte)
        self.assertIn("server_name %s;" % TURN, texte)

    def test_sans_racine_acme_pas_de_location(self):
        texte = self._site("full", NGINX_ACME_ROOT="")
        self.assertNotIn("acme-challenge", texte)
        self.assertIn("return 301 https://$host$request_uri;", texte)


class TestEchecDuTest(unittest.TestCase):
    """Review Focus 1 : `nginx -t` en echec apres l'ecriture du site."""

    def test_texte_precedent_remis_sans_rechargement(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier)
            avec_lignee(hote)
            fait = hote.jouer(**entrees("acme"))
            self.assertEqual(fait.returncode, 0, fait.stdout + fait.stderr)
            avant = lire(hote.chemin(SITE_DEBIAN))
            applique = hote.chemin("/etc/erplibre-call/nginx.applied")
            applique_avant = lire(applique)
            hote.oublier_appels()

            fait = hote.jouer(NGINX_T_ECHEC="1", **entrees("full"))
            self.assertNotEqual(fait.returncode, 0, fait.stdout)
            self.assertEqual(lire(hote.chemin(SITE_DEBIAN)), avant)
            self.assertTrue(os.path.islink(hote.chemin(LIEN_DEBIAN)))
            appels = hote.appels()
            self.assertIn("nginx -t", appels)
            self.assertFalse([a for a in appels if "reload" in a
                              or "enable" in a or "restart" in a], appels)
            self.assertEqual(
                fait.stdout.strip().splitlines()[-1],
                '@@NGINX failed nginx: [emerg] cannot load certificate '
                '"/x/fullchain.pem"')
            self.assertEqual(lire(applique), applique_avant)
            self.assertEqual(
                [n for n in os.listdir(hote.chemin("/etc/nginx/"
                                                   "sites-available"))],
                ["erplibre-call-ntfy.conf"])

    def test_premiere_ecriture_retiree(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier)
            avec_lignee(hote)
            fait = hote.jouer(NGINX_T_ECHEC="1", **entrees())
            self.assertNotEqual(fait.returncode, 0, fait.stdout)
            self.assertFalse(os.path.lexists(hote.chemin(SITE_DEBIAN)))
            self.assertFalse(os.path.lexists(hote.chemin(LIEN_DEBIAN)))
            self.assertFalse(os.path.exists(
                hote.chemin("/etc/erplibre-call/nginx.applied")))

    def test_ligne_d_inclusion_retiree(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier, os_release=OS_ARCH, conf=CONF_ARCH)
            avec_lignee(hote)
            fait = hote.jouer(NGINX_T_ECHEC="1", NGINX_ADOPT_INCLUDE="1",
                              **entrees())
            self.assertNotEqual(fait.returncode, 0, fait.stdout)
            self.assertEqual(lire(hote.chemin("/etc/nginx/nginx.conf")),
                             CONF_ARCH)
            self.assertFalse(os.path.lexists(hote.chemin(SITE_ARCH)))
            self.assertFalse([n for n in os.listdir(
                hote.chemin("/etc/nginx")) if ".bak-" in n])


class TestRelance(unittest.TestCase):

    def test_meme_entree_rien_ne_recharge(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier)
            avec_lignee(hote)
            fait = hote.jouer(**entrees())
            self.assertEqual(fait.returncode, 0, fait.stdout + fait.stderr)
            site = hote.chemin(SITE_DEBIAN)
            texte = lire(site)
            os.utime(site, (1000000000, 1000000000))
            hote.oublier_appels()

            fait = hote.jouer(**entrees())
            self.assertEqual(fait.returncode, 0, fait.stdout + fait.stderr)
            self.assertEqual(lire(site), texte)
            self.assertEqual(os.stat(site).st_mtime, 1000000000)
            appels = hote.appels()
            self.assertNotIn("nginx -t", appels)
            self.assertFalse([a for a in appels if "reload" in a
                              or "enable" in a], appels)
            self.assertEqual(fait.stdout.strip().splitlines()[-1],
                             "@@NGINX active")

    def test_passage_interrompu_recharge(self):
        """Le site est sur disque mais rien ne dit que nginx l'a charge (un
        passage coupe entre l'ecriture et le rechargement) : la relance
        recharge."""
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier)
            avec_lignee(hote)
            fait = hote.jouer(**entrees())
            self.assertEqual(fait.returncode, 0, fait.stdout + fait.stderr)
            os.remove(hote.chemin("/etc/erplibre-call/nginx.applied"))
            hote.oublier_appels()
            fait = hote.jouer(**entrees())
            self.assertEqual(fait.returncode, 0, fait.stdout + fait.stderr)
            self.assertIn("systemctl reload nginx", hote.appels())


class TestRefus(unittest.TestCase):

    def _refus(self, **variables):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier)
            avec_lignee(hote)
            fait = hote.jouer(**variables)
            self.assertNotEqual(fait.returncode, 0, fait.stdout)
            self.assertFalse(os.path.lexists(hote.chemin(SITE_DEBIAN)))
            self.assertFalse([a for a in hote.appels()
                              if a.startswith(("nginx", "apt-get"))])
            self.assertTrue(fait.stdout.strip().splitlines()[-1]
                            .startswith("@@NGINX failed"))
            return fait

    def test_nom_qui_ouvrirait_une_directive(self):
        self._refus(**entrees(NGINX_NAMES="%s;evil" % NTFY))

    def test_joker_refuse(self):
        self._refus(**entrees(NGINX_NAMES="*.exemple.test %s" % NTFY))

    def test_nom_ntfy_absent_des_noms(self):
        self._refus(**entrees(NGINX_NAMES=TURN))

    def test_etape_inconnue(self):
        self._refus(**entrees("tout"))

    def test_full_sans_certificat(self):
        self._refus(**entrees(NGINX_CERT_FILE="", NGINX_KEY_FILE=""))

    def test_port_invalide(self):
        self._refus(**entrees(NGINX_UPSTREAM_PORT="80; return 200"))

    def test_certificat_absent(self):
        self._refus(**entrees(NGINX_CERT_FILE="/etc/absent/fullchain.pem"))

    def test_fichier_etranger_au_meme_nom(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier)
            avec_lignee(hote)
            etranger = "server { server_name autre.exemple.test; }\n"
            ecrire(hote.chemin(SITE_DEBIAN), etranger)
            fait = hote.jouer(**entrees())
            self.assertNotEqual(fait.returncode, 0, fait.stdout)
            self.assertEqual(lire(hote.chemin(SITE_DEBIAN)), etranger)
            self.assertFalse(os.path.lexists(hote.chemin(LIEN_DEBIAN)))

    def test_lien_vers_ailleurs(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier)
            avec_lignee(hote)
            os.makedirs(hote.chemin("/etc/nginx/sites-enabled"))
            os.symlink("/etc/nginx/sites-available/autre",
                       hote.chemin(LIEN_DEBIAN))
            fait = hote.jouer(**entrees())
            self.assertNotEqual(fait.returncode, 0, fait.stdout)
            self.assertEqual(os.readlink(hote.chemin(LIEN_DEBIAN)),
                             "/etc/nginx/sites-available/autre")
            self.assertFalse(os.path.lexists(hote.chemin(SITE_DEBIAN)))

    def test_racine_acme_illisible_de_nginx(self):
        """nginx sert le defi sous son propre compte : un dossier parent
        ferme aux autres le lui rend illisible, la delivrance echouerait."""
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier)
            avec_lignee(hote)
            ferme = hote.chemin("/var/lib/erplibre-call")
            os.makedirs(ferme)
            os.chmod(ferme, 0o750)
            fait = hote.jouer(**entrees())
            self.assertNotEqual(fait.returncode, 0, fait.stdout)
            self.assertIn("/var/lib/erplibre-call", fait.stderr)
            self.assertFalse(os.path.lexists(hote.chemin(SITE_DEBIAN)))
            self.assertEqual(stat.S_IMODE(os.stat(ferme).st_mode), 0o750)

    def test_racine_acme_creee_lisible(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier)
            avec_lignee(hote)
            fait = hote.jouer(**entrees())
            self.assertEqual(fait.returncode, 0, fait.stdout + fait.stderr)
            for chemin in ("/var", "/var/lib", "/var/lib/erplibre-call",
                           ACME):
                mode = stat.S_IMODE(os.stat(hote.chemin(chemin)).st_mode)
                self.assertEqual(mode & 0o005, 0o005, chemin)


class TestPaquet(unittest.TestCase):

    def test_absent_sans_permission_refuse(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier, conf=None, present=False)
            avec_lignee(hote)
            fait = hote.jouer(**entrees())
            self.assertNotEqual(fait.returncode, 0, fait.stdout)
            self.assertFalse([a for a in hote.appels()
                              if a.startswith("apt-get")])
            self.assertEqual(marqueurs(fait.stdout, "NGINX_INSTALLED"), [])

    def test_debian_installe(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier, conf=None, present=False)
            avec_lignee(hote)
            fait = hote.jouer(NGINX_INSTALL="1", **entrees())
            self.assertEqual(fait.returncode, 0, fait.stdout + fait.stderr)
            installe = [a for a in hote.appels()
                        if a.startswith("apt-get") and " install " in a]
            self.assertEqual(len(installe), 1)
            self.assertIn("nginx", installe[0].split())
            self.assertEqual(marqueurs(fait.stdout, "NGINX_INSTALLED"), ["1"])
            self.assertTrue(os.path.isfile(hote.chemin(SITE_DEBIAN)))

    def test_echec_du_gestionnaire_de_paquets(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier, conf=None, present=False)
            avec_lignee(hote)
            fait = hote.jouer(NGINX_INSTALL="1", APT_ECHEC="1", **entrees())
            self.assertNotEqual(fait.returncode, 0, fait.stdout)
            self.assertEqual(fait.stdout.strip().splitlines()[-1],
                             "@@NGINX failed apt-get install nginx a echoue.")
            self.assertEqual(marqueurs(fait.stdout, "NGINX_INSTALLED"), [])

    def test_arch_installe(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier, os_release=OS_ARCH, conf=None,
                        present=False, actif=False)
            avec_lignee(hote)
            fait = hote.jouer(NGINX_INSTALL="1", NGINX_ADOPT_INCLUDE="1",
                              **entrees())
            self.assertEqual(fait.returncode, 0, fait.stdout + fait.stderr)
            self.assertIn("pacman -S --noconfirm --needed nginx",
                          hote.appels())
            self.assertEqual(marqueurs(fait.stdout, "NGINX_INSTALLED"), ["1"])

    def test_present_rien_n_est_installe(self):
        with tempfile.TemporaryDirectory() as dossier:
            hote = Hote(dossier)
            avec_lignee(hote)
            fait = hote.jouer(NGINX_INSTALL="1", **entrees())
            self.assertEqual(fait.returncode, 0, fait.stdout + fait.stderr)
            self.assertFalse([a for a in hote.appels()
                              if a.startswith("apt-get")])
            self.assertEqual(marqueurs(fait.stdout, "NGINX_INSTALLED"), [])


if __name__ == "__main__":
    unittest.main()
