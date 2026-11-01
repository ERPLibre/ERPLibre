#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Infrastructure d'appel (coturn, ntfy) : sonde d'un hôte, plan
d'installation, script d'installation, état de l'hôte, vérification et
désinstallation.

Fonctions pures, stdlib seule (plus `ntfy_mobile`, `odoo_link` et
`turn_client`, stdlib seule aussi) :
le menu de `todo.py` les appelle, les scripts `sh` qu'elles construisent
sont exécutés en root par `ntfy_mobile.LocalHost` ou `SshHost`, et leur
sortie est relue par des lignes `@@NOM valeur`.

Déroulé :

1. `probe_script()` imprime ce que l'hôte porte ; `parse_probe()` en fait
   un `HostFacts`. La sonde n'écrit rien.
2. `plan_install(facts, answers, now)` refuse (`Refusal`, clé i18n et
   valeurs) ou rend un `InstallPlan` : services adoptés, diffs des fichiers
   remplacés, état à écrire, « rien à changer ».
3. `install_script(plan, stamp)` rend le script qui sauve les
   configurations adoptées, lance les installateurs et n'écrit l'état
   qu'une fois chaque service vu actif.
4. `check_remote_script()` lit l'hôte sans rien écrire ; `check_local()`
   en tire le verdict depuis la machine qui lance `todo.py` : allocations
   TURN réelles, santé de ntfy, certificat, pare-feu, unités.
5. `uninstall_script(state, remove_data, stamp)` défait ce que l'état
   consigne et n'efface l'état qu'en dernier, une fois tout réussi.
6. `odoo_add_script`, `odoo_remove_script` et `odoo_rollback_script`
   posent ou retirent, dans la base de coturn, le secret (module
   `erplibre_turn`) ou le compte fixe d'un serveur Odoo ; `turn_mode_for`
   dit le mode de coturn que ce serveur demande, `ice_urls` les URL que le
   module distribue.
7. `plan_odoo_add(state, facts, url, base, ...)` rend un `OdooPlan` (ou
   refuse) sans rien écrire ; `apply_odoo_add` pose l'identifiant sur
   coturn, puis écrit Odoo, et défait coturn quand Odoo refuse ;
   `apply_odoo_remove` nettoie Odoo, puis révoque sur l'hôte. Les deux
   lancent leurs scripts par le `run` que l'appelant leur donne.

L'état (`STATE_PATH`, root 0600) est le seul registre de ce que l'outil a
fait sur l'hôte ; il ne porte aucun secret. Avant de toucher à un service,
le script dépose dans `PENDING_DIR` ce que l'hôte avait AVANT (paquet déjà
là ou non, configuration adoptée et sa copie) : une installation coupée
avant l'écriture de l'état laisse cette fiche, que la sonde suivante lit, et
la relance consigne l'origine vraie au lieu de celle d'un hôte à moitié
installé.
"""

import base64
import binascii
import copy
import dataclasses
import datetime
import gzip
import hashlib
import http.client
import ipaddress
import json
import os
import re
import secrets
import shlex
import socket
import ssl
import subprocess
import tempfile

from script.todo import ntfy_mobile as nm
from script.todo import odoo_link as ol
from script.todo import turn_client

STATE_PATH = "/etc/erplibre-call/state.json"
STATE_VERSION = 1
CALL_DIR = "/etc/erplibre-call"
PENDING_DIR = "/etc/erplibre-call/pending"

# Première ligne de toute configuration écrite par l'outil, la même que
# celle d'install_coturn.sh : une configuration qui ne la porte pas est
# étrangère, donc adoptée.
MARKER = "# erplibre-call: managed"

SERVICES = ("coturn", "ntfy")
# Libellés d'une règle de pare-feu : les services, plus nginx (80 et 443,
# devant ntfy ou pour le défi ACME) et certbot autonome (80). Le libellé
# finit dans le commentaire de la règle, que la vérification et la
# désinstallation relisent.
FIREWALL_LABELS = SERVICES + ("nginx", "certbot")
MODES = ("development", "production")
# Mode d'identification de coturn, un seul à la fois (coturn 4.6 ne les
# mélange pas) : « fixed », des comptes long terme (`lt-cred-mech`) ;
# « secret », des identifiants temporaires signés par les secrets de
# `turn_secret` (`use-auth-secret`). Absent de l'état : « fixed ».
TURN_MODES = ("fixed", "secret")
# « letsencrypt » n'existe qu'en production ; « none » y est refusé.
TLS_MODES = ("none", "supplied", "letsencrypt")
# Défi ACME : HTTP-01 par le webroot d'un nginx, HTTP-01 par certbot qui
# écoute lui-même sur 80, ou DNS-01 par un greffon DNS de certbot.
ACME_METHODS = ("http-nginx", "http-standalone", "dns")
# Greffons DNS de certbot proposés ; chacun lit un fichier d'identifiants.
DNS_PLUGINS = (
    "cloudflare",
    "digitalocean",
    "dnsimple",
    "google",
    "linode",
    "luadns",
    "nsone",
    "ovh",
    "rfc2136",
)
NGINX_MODES = ("existing", "install")
# Plage des relais de coturn en production : sa plage par défaut entière.
PROD_MIN_PORT, PROD_MAX_PORT = 49152, 65535
# Plage par défaut d'`Answers` : en production, elle cède la place à la
# plage entière (voir `relay_range`).
DEV_MIN_PORT, DEV_MAX_PORT = 49152, 49252
HTTP_PORT, HTTPS_PORT = 80, 443
# coturn ne sert TLS que sur un seul port avec les lignes de l'installateur
# (deux `tls-listening-port` : le dernier gagne ; `alt-tls-listening-port`
# reste inerte avec `no-rfc5780`). Le choix de 443 remplace donc
# `turns_port` au lieu de s'y ajouter.
TURNS_ALT_PORT = 443
SUPPORTED = "Debian, Ubuntu, Arch Linux"
FIREWALLS = ("ufw", "nftables", "none", "unknown")

COTURN_UNITS = {"debian": "coturn", "arch": "turnserver"}
COTURN_CONFIGS = {
    "debian": "/etc/turnserver.conf",
    "arch": "/etc/turnserver/turnserver.conf",
}
COTURN_TLS_DIR = "/etc/erplibre-call/tls"
COTURN_DB = "/var/lib/erplibre-call/turndb"

NTFY_UNIT = "ntfy"
NTFY_CONFIG = nm.DEFAULT_CONFIG
# Le compte « ntfy » doit lire la clé : elle ne peut pas vivre dans
# COTURN_TLS_DIR, réservé au groupe de coturn.
NTFY_TLS_DIR = "/etc/ntfy/tls"
NTFY_AUTH_FILE = "/var/lib/ntfy/user.db"
NTFY_HTTP_PORT = 8080
NTFY_HTTPS_PORT = 8443
# Le compte administrateur qu'install_ntfy.sh crée quand il manque ; il
# imprime alors `@@ADMIN_PASSWORD`, une seule fois.
NTFY_ADMIN_USER = "erplibre"

# Nom du processus qui tient les ports d'un libellé (colonne de `ss -p`) :
# un port que tient ce processus-là n'est pas « occupé » pour lui. certbot
# autonome n'ouvre 80 que le temps d'un défi ; tout autre processus sur 80
# le lui refuse.
PROCESSES = {
    "coturn": "turnserver",
    "ntfy": "ntfy",
    "nginx": "nginx",
    "certbot": "certbot",
}

# nginx de production (voir install_nginx.sh) : le site de l'outil, son
# dossier d'inclusion sur Arch et le dossier du défi HTTP-01, hors de
# /var/lib/erplibre-call que l'installateur coturn garde en 0750.
NGINX_CONF = "/etc/nginx/nginx.conf"
NGINX_SITE_FILE = "erplibre-call-ntfy.conf"
NGINX_INCLUDE_DIR = "/etc/nginx/erplibre-call.d"
NGINX_LAYOUTS = ("debian", "confd", "arch-include")
NGINX_APPLIED = "/etc/erplibre-call/nginx.applied"
ACME_ROOT = "/var/lib/erplibre-call-acme"
# Lignée certbot de l'outil : un seul certificat pour tous ses noms.
CERT_NAME = "erplibre-call"
LINEAGE_DIR = "/etc/letsencrypt/live/erplibre-call"
RENEWAL_FILE = "/etc/letsencrypt/renewal/erplibre-call.conf"
# Fichier de renouvellement mis de côté (désinstallation qui garde le
# certificat) : « certbot renew » ignore alors la lignée.
RENEWAL_HOLD = RENEWAL_FILE + ".erplibre-hold"
HOOK_PATH = "/etc/letsencrypt/renewal-hooks/deploy/erplibre-call"
DNS_DIR = "/etc/erplibre-call/dns"
# Nom du minuteur du paquet qu'install_certbot.sh a activé (TIMER_RECORD) :
# la sonde le lit pour qu'une fiche de passage coupé consigne ce minuteur.
CERTBOT_TIMER_RECORD = "/etc/erplibre-call/certbot-timer.added"
# Certificat fourni en production : nginx le lit en root depuis ces copies,
# coturn reçoit les siennes (turn.crt, turn.key) par son installateur.
SITE_CERT = "/etc/erplibre-call/tls/site.crt"
SITE_KEY = "/etc/erplibre-call/tls/site.key"
# Unité systemd complétée pour que coturn lie 443 (voir install_coturn.sh,
# write_dropin).
COTURN_DROPIN = "/etc/systemd/system/{unit}.service.d/erplibre-call.conf"
# Défi ACME de l'outil → méthode d'install_certbot.sh (CERTBOT_METHOD).
CERTBOT_METHODS = {
    "http-nginx": "webroot",
    "http-standalone": "standalone",
    "dns": "dns",
}
# Paquet du greffon DNS de certbot, par famille de systèmes.
DNS_PACKAGES = {"debian": "python3-certbot-dns-{}", "arch": "certbot-dns-{}"}

_REPO = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
INSTALLERS = {
    "coturn": os.path.join(_REPO, "script", "install", "install_coturn.sh"),
    "ntfy": os.path.join(_REPO, "script", "install", "install_ntfy.sh"),
    "nginx": os.path.join(_REPO, "script", "install", "install_nginx.sh"),
    "certbot": os.path.join(_REPO, "script", "install", "install_certbot.sh"),
}
HOOK_SOURCE = os.path.join(
    _REPO, "script", "install", "erplibre_call_deploy_hook.sh"
)
# Fiches `PENDING_DIR/<nom>.json` : les services, puis nginx et certbot,
# dont l'origine (installés par l'outil ou non) survit à un passage coupé.
PENDING_NAMES = SERVICES + ("nginx", "certbot")

_DEBIAN_IDS = {"debian", "ubuntu", "linuxmint", "pop", "raspbian"}
_ARCH_IDS = {"arch", "manjaro", "endeavouros", "artix", "garuda"}
_MARKER_LINE = re.compile(r"@@([A-Z_]+)(?: (.*))?$")
# Les mêmes bornes qu'install_coturn.sh : le nom public devient le realm,
# écrit dans turnserver.conf et dans une requête SQL.
_NAME = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.:-]*[A-Za-z0-9])?$")
_EXTERNAL_IP = re.compile(r"^[0-9A-Fa-f:./]+$")
# Courriel donné à certbot (`--email`) : une forme simple, sans espace ni
# caractère du shell.
_EMAIL = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
_STAMP = re.compile(r"^[A-Za-z0-9_-]+$")
# Locale des scripts lancés sur l'hôte : ufw traduit ses messages
# (« Status: active », « Skipping »), que les scripts lisent en anglais.
# sudo garde LANG, LANGUAGE et LC_* de l'appelant, et ssh ne les transmet
# que si l'hôte les accepte ; gettext lit LANGUAGE avant LC_ALL.
_C_LOCALE = "LC_ALL=C; export LC_ALL; unset LANGUAGE"
# Réponse de `systemctl is-enabled` : enabled, disabled, static, masked...
_UNIT_STATE = re.compile(r"^[a-z-]+$")
# Authentificateur d'un fichier de renouvellement de certbot que l'outil
# sait reconnaître (voir `certbot_authenticator`).
_AUTHENTICATOR = re.compile(r"^(webroot|standalone|dns-[a-z0-9]+)$")


class Refusal(Exception):
    """Refus avant toute installation : `key` est une clé i18n, `values`
    les champs de son message (`t(key).format(**values)`)."""

    def __init__(self, key, **values):
        super().__init__(key)
        self.key = key
        self.values = values


@dataclasses.dataclass(frozen=True)
class HostFacts:
    """Ce que la sonde a lu sur l'hôte.

    `coturn` et `ntfy` valent None quand ni unité ni configuration ni fiche
    en attente n'existe, sinon un dict : `unit`, `unit_found` (l'unité
    existe, donc le paquet est là), `active` (état systemd), `enabled`
    (réponse de `systemctl is-enabled`, None sans elle), `config`,
    `config_text` (vide sans fichier), `managed` (première ligne MARKER),
    `pending` (fiche laissée par une installation interrompue, ou None).

    `nft_chains` : (famille, table, chaîne) de chaque chaîne de base
    nftables accrochée à « input » en politique drop ; l'outil n'ajoute ses
    règles que quand il y en a exactement une.

    `firewall_pending` : ((ufw|nftables, Rule), ...) des règles que
    `firewall_script` a posées ou gardées et qu'aucun état écrit ne
    consigne encore (fiche `PENDING_DIR/firewall`).

    `ufw_added` : les lignes `ufw ...` de `ufw show added` quand ufw est
    le pare-feu actif, () sinon.

    `nginx` : None sans nginx ni fiche en attente, sinon `state` (active,
    inactive, absent), `layout` (une de NGINX_LAYOUTS, la règle
    d'install_nginx.sh ; None sans nginx), `include` (nginx.conf porte la
    ligne include de l'outil), `names` (((nom, fichier), ...) de chaque
    `server_name` des sites que l'outil n'a pas écrits), `pending`.

    `certbot` : None sans certbot ni lignée, fichier mis de côté ou fiche,
    sinon `version` (None sans certbot), `lineage` (noms de la lignée de
    l'outil, None sans elle), `held` (son fichier de renouvellement est mis
    de côté), `plugins` (greffons DNS installés), `pending`.
    """

    family: str | None
    os_id: str
    os_version: str
    systemd: bool
    hostname: str
    addresses: tuple[str, ...]
    busy_ports: tuple[tuple[str, int, str], ...]
    coturn: dict | None
    ntfy: dict | None
    firewall: str
    state: dict | None
    nft_chains: tuple[tuple[str, str, str], ...] = ()
    firewall_pending: tuple = ()
    ufw_added: tuple[str, ...] = ()
    nginx: dict | None = None
    certbot: dict | None = None


@dataclasses.dataclass(frozen=True)
class Answers:
    """Les réponses de l'utilisateur. `ntfy_port` None : 8080 en http,
    8443 avec un certificat fourni en développement ; 8080 sur 127.0.0.1
    en production, derrière nginx.

    Production (`mode`) : `ntfy_name` et `turn_name` (None : `public_name`,
    qui reste le realm de coturn), `acme` pour `tls="letsencrypt"` (une de
    `ACME_METHODS`), `dns_plugin` et `dns_credentials` (texte du fichier
    d'identifiants, un secret jamais consigné) pour `acme="dns"`, `email`
    pour Let's Encrypt (vide : aucun), `ntfy_web` (interface web de ntfy),
    `turns_443` (TURN sur TLS écoute 443 au lieu de `turns_port`), `nginx`
    (« existing », « install », None sans nginx)."""

    services: frozenset[str]
    tls: str
    cert_pem: str | None
    key_pem: str | None
    public_name: str
    turn_port: int = 3478
    turns_port: int = 5349
    min_port: int = DEV_MIN_PORT
    max_port: int = DEV_MAX_PORT
    ntfy_port: int | None = None
    external_ip: str | None = None
    mode: str = "development"
    ntfy_name: str | None = None
    turn_name: str | None = None
    acme: str | None = None
    dns_plugin: str | None = None
    dns_credentials: str | None = None
    email: str = ""
    ntfy_web: bool = False
    turns_443: bool = False
    nginx: str | None = None


@dataclasses.dataclass(frozen=True)
class InstallPlan:
    """`adopt` : services dont la configuration étrangère sera sauvée puis
    remplacée ; `diffs` : (chemin, diff unifié) de chaque configuration en
    place qui change, valeurs secrètes masquées (`redact_secrets`) ; `new_state` : l'état à écrire, sans les chemins des
    copies, qui dépendent du tampon (voir `written_state`) ; `configs` :
    {service: texte voulu} des configurations que le script écrit lui-même
    (ntfy ; celle de coturn est écrite par son installateur).
    `lineage_unchanged` : la lignée certbot de l'hôte porte déjà exactement
    les noms du certificat et n'est pas mise de côté : certbot passe sans
    essai à blanc (CERTBOT_SKIP_STAGING=1) ; il faut pour cela que son
    fichier de renouvellement porte la méthode voulue
    (`certbot_authenticator`) et, en DNS-01, que les identifiants aient la
    même empreinte que ceux de l'état.
    `certbot_force` : la lignée de l'hôte (active ou mise de côté) porte un
    autre authentificateur ; certbot délivre alors avant l'échéance
    (CERTBOT_FORCE_RENEWAL=1), seule manière de réécrire son fichier de
    renouvellement, qui sans cela renouvellerait par l'ancienne méthode.
    `nginx_include` : install_nginx.sh ajoute sa ligne include à nginx.conf
    (disposition arch-include sans elle) ; le script lui en donne l'accord
    (NGINX_ADOPT_INCLUDE=1), et `diffs` montre la ligne quand nginx.conf
    est déjà sur l'hôte.
    `purge_secrets` : empreintes des anciens secrets d'Odoo expirés que le
    script efface de la base de coturn ; `new_state` ne les porte plus.
    `odoo_readd` : clés des serveurs Odoo dont les URL de TURN changent
    avec ce plan (nom de TURN, ports, TLS) et qu'il faut ajouter de
    nouveau pour qu'ils les reçoivent ; l'avertissement est la clé
    ODOO_READD_WARNING (valeur `odoos`)."""

    answers: Answers
    adopt: tuple[str, ...]
    diffs: tuple[tuple[str, str], ...]
    nothing_to_do: bool
    new_state: dict
    configs: dict = dataclasses.field(default_factory=dict)
    lineage_unchanged: bool = False
    nginx_include: bool = False
    certbot_force: bool = False
    purge_secrets: tuple[str, ...] = ()
    odoo_readd: tuple[str, ...] = ()


# --- Sonde ------------------------------------------------------------------

# `ss -Hlntup` : colonne 1 le protocole, 5 l'adresse locale (le port suit le
# dernier « : »), et `users:(("nom",...` le processus, « ? » sans lui.
_SS_AWK = (
    '{ a = $5; sub(/.*:/, "", a); p = "?";'
    ' if (match($0, /users:\\(\\("[^"]*"/))'
    " p = substr($0, RSTART + 9, RLENGTH - 10);"
    ' print "@@PORT " $1 " " a " " p }'
)
_ADDR_AWK = '{ sub(/\\/.*/, "", $4); print "@@ADDR " $4 }'
# `nft list ruleset` : « table <famille> <nom> { » ouvre une table,
# « chain <nom> { » une chaîne ; la ligne « type ... hook input ... policy
# drop; » fait d'elle une chaîne de base qui rejette ce qu'elle n'accepte
# pas. Le pont (« bridge ») a aussi un crochet input, qui ne voit pas le
# trafic destiné à l'hôte : seuls ip, ip6 et inet comptent. Imprime
# « famille table chaîne », suivi d'un 4e champ « iptables » pour une
# chaîne « INPUT » en ip ou ip6 : c'est celle qu'iptables-nft crée, dans
# une table qu'iptables-persistent recharge en entier, ce qui effacerait
# une règle nft native.
_NFT_CHAINS_AWK = (
    '/^table / { f = $2; t = $3; c = "" }'
    " /^[ \\t]*chain / { c = $2 }"
    " /hook input/ && /policy drop/"
    ' { if (f == "ip" || f == "ip6" || f == "inet")'
    ' print f, t, c ((f != "inet" && c == "INPUT") ? " iptables" : "") }'
)
_EXEC_CONF_SED = (
    "s/^ExecStart=.*[[:space:]](-c|--conf-file)[[:space:]=]+"
    "([^[:space:]]+).*/\\2/p"
)
# Lignes `include` actives de nginx.conf qui décident de la disposition,
# les mêmes motifs qu'install_nginx.sh (`has_include`, `layout`) : la ligne
# de l'outil, sites-enabled (Debian), conf.d (paquet amont de nginx).
_NGINX_INCLUDE_OURS = (
    r"^[[:space:]]*include[[:space:]]+/etc/nginx/erplibre-call\.d/\*\.conf"
    r"[[:space:]]*;"
)
_NGINX_INCLUDE_SITES = (
    r"^[[:space:]]*include[[:space:]]+(/etc/nginx/)?sites-enabled/\*"
    r"[[:space:]]*;"
)
_NGINX_INCLUDE_CONFD = (
    r"^[[:space:]]*include[[:space:]]+(/etc/nginx/)?conf\.d/\*\.conf"
    r"[[:space:]]*;"
)
# Chaque nom d'une directive `server_name`, jusqu'à son « ; », même sur
# plusieurs lignes ; un commentaire (# jusqu'à la fin de ligne) ne compte
# pas. `proxy_ssl_server_name` et les autres mots qui finissent pareil ne
# sont pas `server_name` : seul le mot exact ouvre la liste.
_NGINX_NAMES_AWK = (
    '{ sub(/#.*/, ""); gsub(/;/, " ; "); n = split($0, w);'
    ' for (i = 1; i <= n; i++) { t = w[i]; if (t == "") continue;'
    ' if (on) { if (t == ";") on = 0; else print "@@NGINX_NAME " t " " file }'
    ' else if (t == "server_name") on = 1 } }'
)
# Les mêmes noms dans la sortie de `nginx -T`, qui imprime chaque fichier
# que nginx lit (inclusions comprises) sous une ligne « # configuration
# file <chemin>: ». Un fichier dont la première ligne est `marker` (ceux de
# l'outil) est sauté ; la liste d'un `server_name` ne déborde pas d'un
# fichier sur le suivant.
_NGINX_DUMP_AWK = (
    'index($0, "# configuration file ") == 1 && /:$/'
    " { file = substr($0, 22, length($0) - 22); first = 1; skip = 0; on = 0;"
    " next }"
    " first { first = 0; if ($0 == marker) skip = 1 }"
    ' skip || file == "" { next } ' + _NGINX_NAMES_AWK
)
_DPKG_PLUGINS_AWK = (
    '$3 == "installed" { sub(/^python3-certbot-dns-/, "", $4);'
    ' print "@@CERTBOT_PLUGIN " $4 }'
)


def probe_script(root=""):
    """Script `sh` en lecture seule qui imprime les faits de l'hôte.

    `root` préfixe chaque chemin lu ; vide sur un vrai hôte, un dossier
    temporaire dans les tests. Lignes : `@@OS <id> <version> <id_like>`,
    `@@SYSTEMD yes|no`, `@@HOSTNAME`, `@@ADDR` par adresse globale,
    `@@PORT <proto> <port> <processus>` par port en écoute, `@@COTURN
    <unité> <état> <config de l'unité>` et `@@NTFY <unité> <état> <config>`
    (« - » pour absent), `@@ENABLED <service> <is-enabled>` par unité
    trouvée, `@@FILE <chemin> <base64>` par configuration
    présente, `@@PENDING <service> <base64>`, `@@FIREWALL`, `@@NFT_INPUT
    <famille> <table> <chaîne>` par chaîne input en drop (nftables
    seulement), `@@STATE <base64>`, `@@FIREWALL_PENDING <ufw|nftables>
    <proto> <port> <service>` par règle posée que l'état ne consigne pas
    encore, `@@UFW_ADDED <ligne>` par ligne de `ufw show added` quand ufw
    est actif, `@@NGINX <active|inactive|absent> <disposition> [include]`
    (« include » : nginx.conf porte la ligne de l'outil), `@@NGINX_NAME
    <nom> <fichier>` par nom de `server_name` des fichiers que nginx lit
    et que l'outil n'a pas écrits (`_nginx_probe_lines`), `@@CERTBOT <version|absent>`, `@@CERTBOT_PLUGIN
    <greffon>` par greffon DNS installé, `@@LINEAGE erplibre-call
    <noms...>` (lu par `certbot certificates`, qui n'écrit que son
    journal), `@@HELD erplibre-call` quand son fichier de renouvellement est
    mis de côté, `@@TIMER_ADDED <unité>` par minuteur que l'outil a activé
    ou posé (`_certbot_probe_lines`), puis `@@END` : sans lui, la sortie
    est tronquée.
    """
    files = " ".join(
        [
            COTURN_CONFIGS["debian"],
            COTURN_CONFIGS["arch"],
            '"$CC"',
            NTFY_CONFIG,
        ]
    )
    return "\n".join(
        [
            _C_LOCALE,
            f"R={shlex.quote(root)}",
            # Une invite de sudo sans fin de ligne ne colle pas à la
            # première ligne de faits.
            "echo",
            'if [ -r "$R/etc/os-release" ]; then',
            '  echo "@@OS $(. "$R/etc/os-release"; printf "%s %s %s"'
            ' "${ID:-unknown}" "${VERSION_ID:-${BUILD_ID:--}}"'
            ' "${ID_LIKE:-}")"',
            "else",
            '  echo "@@OS unknown -"',
            "fi",
            'if [ -d "$R/run/systemd/system" ]; then echo "@@SYSTEMD yes";'
            ' else echo "@@SYSTEMD no"; fi',
            'echo "@@HOSTNAME $(uname -n)"',
            "if command -v ip >/dev/null 2>&1; then",
            "  ip -o addr show scope global 2>/dev/null"
            f" | awk {shlex.quote(_ADDR_AWK)}",
            "fi",
            "if command -v ss >/dev/null 2>&1; then",
            f"  ss -Hlntup 2>/dev/null | awk {shlex.quote(_SS_AWK)}",
            "fi",
            'unit_conf() { systemctl cat "$1" 2>/dev/null'
            f" | sed -n -E {shlex.quote(_EXEC_CONF_SED)} | tail -n 1; }}",
            "CU=-; CA=-; CC=-",
            "for u in coturn turnserver; do",
            '  if systemctl cat "$u" >/dev/null 2>&1; then CU=$u; break; fi',
            "done",
            'if [ "$CU" != - ]; then',
            '  CA=$(systemctl is-active "$CU" 2>/dev/null)',
            '  CC=$(unit_conf "$CU")',
            "fi",
            'echo "@@COTURN $CU ${CA:--} ${CC:--}"',
            'if [ "$CU" != - ]; then',
            '  echo "@@ENABLED coturn $(systemctl is-enabled "$CU" 2>/dev/null)"',
            "fi",
            "NU=-; NA=-",
            f"if systemctl cat {NTFY_UNIT} >/dev/null 2>&1; then",
            f"  NU={NTFY_UNIT}; NA=$(systemctl is-active {NTFY_UNIT}"
            " 2>/dev/null)",
            "fi",
            f'echo "@@NTFY $NU ${{NA:--}} {NTFY_CONFIG}"',
            'if [ "$NU" != - ]; then',
            f'  echo "@@ENABLED ntfy $(systemctl is-enabled {NTFY_UNIT}'
            ' 2>/dev/null)"',
            "fi",
            f"for f in {files}; do",
            '  if [ "$f" != - ] && [ -f "$R$f" ]; then',
            '    echo "@@FILE $f $(base64 -w0 < "$R$f")"',
            "  fi",
            "done",
            "for s in " + " ".join(PENDING_NAMES) + "; do",
            f'  f="$R{PENDING_DIR}/$s.json"',
            '  if [ -f "$f" ]; then'
            ' echo "@@PENDING $s $(base64 -w0 < "$f")"; fi',
            "done",
            # Un pare-feu que l'outil ne sait pas compléter sans risque
            # (firewalld, iptables en DROP, y compris par iptables-nft) se
            # dit « unknown ».
            "NI=",
            "command -v nft >/dev/null 2>&1 && NI=$(nft list ruleset"
            f" 2>/dev/null | awk {shlex.quote(_NFT_CHAINS_AWK)})",
            "FW=none",
            "if command -v ufw >/dev/null 2>&1"
            " && ufw status 2>/dev/null | grep -q '^Status: active'; then",
            "  FW=ufw",
            "elif systemctl is-active --quiet firewalld 2>/dev/null; then",
            "  FW=unknown",
            'elif [ -n "$NI" ]; then',
            '  if printf "%s\\n" "$NI" | awk \'$4 != "" { x = 1 }'
            " END { exit !x }'; then FW=unknown; else FW=nftables; fi",
            "elif command -v iptables >/dev/null 2>&1 && iptables -S INPUT"
            " 2>/dev/null | grep -q '^-P INPUT DROP'; then",
            "  FW=unknown",
            "fi",
            'echo "@@FIREWALL $FW"',
            'if [ "$FW" = ufw ]; then',
            "  ufw show added 2>/dev/null | sed 's/^/@@UFW_ADDED /'",
            "fi",
            'if [ "$FW" = nftables ]; then',
            '  printf "%s\\n" "$NI" | sed \'s/^/@@NFT_INPUT /\'',
            "fi",
            *_nginx_probe_lines(),
            *_certbot_probe_lines(),
            f'S="$R{STATE_PATH}"',
            'if [ -f "$S" ]; then echo "@@STATE $(base64 -w0 < "$S")"; fi',
            f'FP="$R{PENDING_DIR}/firewall"',
            'if [ -f "$FP" ]; then sed "s/^/@@FIREWALL_PENDING /" "$FP"; fi',
            'echo "@@END"',
            "",
        ]
    )


def _nginx_probe_lines():
    """Lignes de la sonde pour nginx : présent quand son binaire répond et
    que nginx.conf existe (la règle d'install_nginx.sh). Les noms des
    sites viennent de `nginx -T` (lecture seule, chaque fichier inclus) ;
    quand il échoue (configuration invalide), des emplacements connus :
    nginx.conf, sites-enabled, conf.d, le dossier de l'outil."""
    conf = '"$NC"'
    sites = ['"$NC"'] + [
        f'"$R{d}/"{g}'
        for d, g in (
            ("/etc/nginx/sites-enabled", "*"),
            ("/etc/nginx/conf.d", "*.conf"),
            (NGINX_INCLUDE_DIR, "*.conf"),
        )
    ]
    return [
        "NX=absent; NL=-; NO=",
        f'NC="$R{NGINX_CONF}"',
        f"if command -v nginx >/dev/null 2>&1 && [ -f {conf} ]; then",
        "  NX=$(systemctl is-active nginx 2>/dev/null)",
        '  [ "$NX" = active ] || NX=inactive',
        f"  if grep -qE {shlex.quote(_NGINX_INCLUDE_OURS)} {conf}; then"
        " NL=arch-include; NO=include",
        f"  elif grep -qE {shlex.quote(_NGINX_INCLUDE_SITES)} {conf}; then"
        " NL=debian",
        f"  elif grep -qE {shlex.quote(_NGINX_INCLUDE_CONFD)} {conf}; then"
        " NL=confd",
        "  else NL=arch-include; fi",
        "fi",
        'echo "@@NGINX $NX $NL${NO:+ $NO}"',
        'if [ "$NX" != absent ]; then',
        '  echo "@@NGINX_ENABLED $(systemctl is-enabled nginx 2>/dev/null)"',
        "  if NT=$(nginx -T 2>/dev/null)"
        " && printf '%s\\n' \"$NT\" | grep -q '^# configuration file '; then",
        "    printf '%s\\n' \"$NT\""
        f" | awk -v marker={shlex.quote(MARKER)}"
        f" {shlex.quote(_NGINX_DUMP_AWK)}",
        "  else",
        f"    for f in {' '.join(sites)}; do",
        '      [ -f "$f" ] || continue',
        f'      [ "$(head -n 1 "$f")" = {shlex.quote(MARKER)} ] && continue',
        f'      awk -v file="${{f#"$R"}}" {shlex.quote(_NGINX_NAMES_AWK)} "$f"',
        "    done",
        "  fi",
        "fi",
    ]


def _certbot_probe_lines():
    """Lignes de la sonde pour certbot : version, greffons DNS installés
    (dpkg ou pacman), noms de la lignée de l'outil, fichier mis de côté,
    authentificateur de son fichier de renouvellement (l'actif, sinon celui
    mis de côté), minuteur ajouté par l'outil : la première ligne de
    CERTBOT_TIMER_RECORD, puis CERTBOT_OWN_TIMER quand l'une de ses unités
    porte MARKER en tête. `parse_probe` ne garde qu'un nom de
    CERTBOT_TIMERS."""
    renewal = f'"$R{RENEWAL_FILE}"'
    own = " ".join(_host(path) for path in _CERTBOT_OWN_UNITS)
    return [
        "CV=absent",
        "command -v certbot >/dev/null 2>&1"
        " && CV=$(certbot --version 2>&1 | awk 'NR == 1 { print $NF }')",
        'echo "@@CERTBOT ${CV:-unknown}"',
        'if [ "$CV" != absent ]; then',
        "  if command -v dpkg-query >/dev/null 2>&1; then",
        "    dpkg-query -W -f '${Status} ${Package}\\n'"
        " 'python3-certbot-dns-*' 2>/dev/null"
        f" | awk {shlex.quote(_DPKG_PLUGINS_AWK)}",
        "  elif command -v pacman >/dev/null 2>&1; then",
        "    pacman -Qq 2>/dev/null"
        " | sed -n 's/^certbot-dns-/@@CERTBOT_PLUGIN /p'",
        "  fi",
        f'  if [ -d "$R{LINEAGE_DIR}" ]; then',
        f"    certbot certificates --cert-name {CERT_NAME} 2>/dev/null"
        " | sed -n 's/^[[:space:]]*Domains:[[:space:]]*/"
        f"@@LINEAGE {CERT_NAME} /p'",
        "  fi",
        "fi",
        f'if [ -f "$R{RENEWAL_HOLD}" ]; then echo "@@HELD {CERT_NAME}"; fi',
        f"RF={renewal}",
        f'[ -f "$RF" ] || RF="$R{RENEWAL_HOLD}"',
        'if [ -f "$RF" ]; then',
        "  sed -n 's/^[[:space:]]*authenticator[[:space:]]*=[[:space:]]*/"
        f'@@AUTHENTICATOR {CERT_NAME} /p\' "$RF" | head -n 1',
        "fi",
        f"TR={_host(CERTBOT_TIMER_RECORD)}",
        'if [ -f "$TR" ]; then echo "@@TIMER_ADDED $(head -n 1 "$TR")"; fi',
        f"for f in {own}; do",
        f'  if [ -f "$f" ] && [ "$(head -n 1 "$f")" = {shlex.quote(MARKER)} ];'
        " then",
        f'    echo "@@TIMER_ADDED {CERTBOT_OWN_TIMER}"; break',
        "  fi",
        "done",
    ]


def marker_lines(output):
    """[(NOM, valeur)] des lignes `@@NOM valeur`, dans l'ordre, répétitions
    comprises. Le nom admet `_` (`@@ADMIN_PASSWORD`), un retour chariot de
    `ssh -t` est retiré."""
    found = []
    for line in output.splitlines():
        match = _MARKER_LINE.match(line.rstrip("\r"))
        if match:
            found.append((match.group(1), match.group(2) or ""))
    return found


def os_family(os_id, id_like=""):
    """« debian », « arch » ou None, d'après ID et ID_LIKE d'os-release ;
    les mêmes listes qu'install_coturn.sh."""
    if os_id in _DEBIAN_IDS:
        return "debian"
    if os_id in _ARCH_IDS:
        return "arch"
    like = id_like.split()
    if "debian" in like or "ubuntu" in like:
        return "debian"
    if "arch" in like:
        return "arch"
    return None


def _decode(value):
    """Texte d'un base64 ; None quand il ne se décode pas."""
    try:
        return base64.b64decode(value.strip(), validate=True).decode(
            "utf-8", "replace"
        )
    except (binascii.Error, ValueError):
        return None


def _decode_json(value):
    text = _decode(value)
    if text is None:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def is_managed(text):
    return text.split("\n", 1)[0].rstrip("\r") == MARKER


def is_foreign(text):
    """Vrai pour un fichier non vide sans MARKER en tête : la règle
    d'install_coturn.sh (`config_is_foreign`)."""
    return bool(text) and not is_managed(text)


def _service_facts(
    marker, default_unit, default_config, files, pending, enabled=None
):
    unit, active, config = (marker + ["-", "-", "-"])[:3]
    unit_found = unit != "-"
    path = config if config != "-" else default_config
    text = files.get(path)
    if not unit_found and text is None and pending is None:
        return None
    return {
        "unit": unit if unit_found else default_unit,
        "unit_found": unit_found,
        "active": active if unit_found and active != "-" else "inactive",
        "enabled": enabled if unit_found and enabled else None,
        "config": path,
        "config_text": text or "",
        "managed": is_managed(text or ""),
        "pending": pending,
    }


def parse_probe(output):
    """`HostFacts` de la sortie de `probe_script`.

    Refusal `call_infra_probe_incomplete` sans `@@END` : une sortie
    tronquée (sudo refusé, connexion coupée) ne passe pas pour un hôte vide.
    """
    os_id, os_version, id_like = "unknown", "", ""
    systemd, hostname, firewall, state = False, "", "unknown", None
    addresses, ports, files, pending, chains = [], [], {}, {}, []
    firewall_pending, ufw_added = [], []
    coturn_marker, ntfy_marker, complete, enabled = [], [], False, {}
    nginx_marker, nginx_names, plugins, nginx_enabled = [], [], [], None
    certbot_version, lineage, held, authenticator = None, None, False, None
    timer_added = None
    for name, value in marker_lines(output):
        if name == "OS":
            parts = value.split()
            os_id = parts[0] if parts else "unknown"
            version = parts[1] if len(parts) > 1 else "-"
            os_version = "" if version == "-" else version
            id_like = " ".join(parts[2:])
        elif name == "SYSTEMD":
            systemd = value.strip() == "yes"
        elif name == "HOSTNAME":
            hostname = value.strip()
        elif name == "ADDR":
            address = value.strip()
            if address and address not in addresses:
                addresses.append(address)
        elif name == "PORT":
            parts = value.split(None, 2)
            if len(parts) == 3 and parts[1].isdigit():
                entry = (parts[0], int(parts[1]), parts[2].strip())
                if entry not in ports:
                    ports.append(entry)
        elif name == "COTURN":
            coturn_marker = value.split(None, 2)
        elif name == "NTFY":
            ntfy_marker = value.split(None, 2)
        elif name == "ENABLED":
            svc, _, current = value.partition(" ")
            if svc in SERVICES and _UNIT_STATE.match(current.strip()):
                enabled[svc] = current.strip()
        elif name == "FILE":
            path, _, encoded = value.rpartition(" ")
            text = _decode(encoded)
            if path and text is not None:
                files[path] = text
        elif name == "PENDING":
            svc, _, encoded = value.partition(" ")
            record = _decode_json(encoded)
            if svc in PENDING_NAMES and record is not None:
                pending[svc] = record
        elif name == "NGINX":
            nginx_marker = value.split()
        elif name == "NGINX_ENABLED":
            current = value.strip()
            nginx_enabled = current if _UNIT_STATE.match(current) else None
        elif name == "NGINX_NAME":
            found, _, where = value.strip().partition(" ")
            entry = (found, where.strip())
            if found and entry[1] and entry not in nginx_names:
                nginx_names.append(entry)
        elif name == "CERTBOT":
            certbot_version = value.strip() or "unknown"
        elif name == "CERTBOT_PLUGIN":
            plugin = value.strip()
            if plugin in DNS_PLUGINS and plugin not in plugins:
                plugins.append(plugin)
        elif name == "LINEAGE":
            parts = value.split()
            if parts and parts[0] == CERT_NAME:
                lineage = tuple(parts[1:])
        elif name == "HELD":
            held = held or value.strip() == CERT_NAME
        elif name == "AUTHENTICATOR":
            parts = value.split()
            if (
                len(parts) == 2
                and parts[0] == CERT_NAME
                and _AUTHENTICATOR.match(parts[1])
            ):
                authenticator = parts[1]
        elif name == "TIMER_ADDED":
            unit = value.strip()
            if timer_added is None and unit in CERTBOT_TIMERS:
                timer_added = unit
        elif name == "FIREWALL":
            kind = value.strip()
            firewall = kind if kind in FIREWALLS else "unknown"
        elif name == "NFT_INPUT":
            chain = tuple(value.split())
            if _valid_chain(chain) and chain not in chains:
                chains.append(chain)
        elif name == "STATE":
            state = _decode_json(value)
        elif name == "FIREWALL_PENDING":
            entry = _pending_rule(value)
            if entry is not None and entry not in firewall_pending:
                firewall_pending.append(entry)
        elif name == "UFW_ADDED":
            line = value.strip()
            if line.startswith("ufw ") and line not in ufw_added:
                ufw_added.append(line)
        elif name == "END":
            complete = True
    if not complete:
        raise Refusal("call_infra_probe_incomplete")
    family = os_family(os_id, id_like)
    coturn = _service_facts(
        coturn_marker,
        COTURN_UNITS.get(family, COTURN_UNITS["debian"]),
        COTURN_CONFIGS.get(family, COTURN_CONFIGS["debian"]),
        files,
        pending.get("coturn"),
        enabled.get("coturn"),
    )
    ntfy = _service_facts(
        ntfy_marker,
        NTFY_UNIT,
        NTFY_CONFIG,
        files,
        pending.get("ntfy"),
        enabled.get("ntfy"),
    )
    return HostFacts(
        family=family,
        os_id=os_id,
        os_version=os_version,
        systemd=systemd,
        hostname=hostname,
        addresses=tuple(addresses),
        busy_ports=tuple(ports),
        coturn=coturn,
        ntfy=ntfy,
        firewall=firewall,
        state=state,
        nft_chains=tuple(chains),
        firewall_pending=tuple(firewall_pending),
        ufw_added=tuple(ufw_added),
        nginx=_nginx_facts(
            nginx_marker, nginx_names, nginx_enabled, pending.get("nginx")
        ),
        certbot=_certbot_facts(
            certbot_version,
            lineage,
            held,
            plugins,
            authenticator,
            timer_added,
            pending.get("certbot"),
        ),
    )


def _nginx_facts(marker, names, enabled, pending):
    """`HostFacts.nginx` des lignes `@@NGINX`, `@@NGINX_NAME` et
    `@@NGINX_ENABLED` (réponse de `systemctl is-enabled`)."""
    state = marker[0] if marker[:1] in (["active"], ["inactive"]) else "absent"
    if state == "absent" and pending is None:
        return None
    present = state != "absent"
    layout = marker[1] if len(marker) > 1 else None
    return {
        "state": state,
        "layout": layout if present and layout in NGINX_LAYOUTS else None,
        "include": present and marker[2:3] == ["include"],
        "names": tuple(names) if present else (),
        "enabled": enabled if present else None,
        "pending": pending,
    }


def _certbot_facts(
    version, lineage, held, plugins, authenticator, timer_added, pending
):
    """`HostFacts.certbot` des lignes `@@CERTBOT*`, `@@LINEAGE`, `@@HELD`,
    `@@AUTHENTICATOR` (None quand il manque ou n'est pas reconnu) et
    `@@TIMER_ADDED` (`timer_added` : un minuteur de CERTBOT_TIMERS, ou
    None)."""
    present = version not in (None, "absent")
    if not present and lineage is None and not held and pending is None:
        return None
    return {
        "version": version if present else None,
        "lineage": lineage,
        "held": held,
        "plugins": tuple(plugins),
        "authenticator": authenticator,
        "timer_added": timer_added,
        "pending": pending,
    }


def _pending_rule(value):
    """(ufw|nftables, Rule) d'une ligne « kind proto port service » de la
    fiche du pare-feu, None hors format ou sur le port de ssh."""
    parts = value.split()
    if len(parts) != 4 or parts[0] not in ("ufw", "nftables"):
        return None
    found = Rule(*parts[1:])
    try:
        _check_rule(found)
    except ValueError:
        return None
    return parts[0], found


# --- Configurations ---------------------------------------------------------


def is_production(answers):
    return answers.mode == "production"


def has_tls(answers):
    """Vrai quand coturn reçoit un certificat : fourni, ou de Let's
    Encrypt (copié par le crochet de déploiement)."""
    return answers.tls in ("supplied", "letsencrypt")


def _ntfy_own_tls(answers):
    """Vrai quand ntfy sert https lui-même : un certificat fourni en
    développement. En production, nginx tient le TLS devant lui."""
    return answers.tls == "supplied" and not is_production(answers)


def default_names(domain):
    """(nom de ntfy, nom de TURN) proposés pour un domaine."""
    domain = domain.strip().rstrip(".")
    return f"ntfy.{domain}", f"turn.{domain}"


def ntfy_host(answers):
    return answers.ntfy_name or answers.public_name


def turn_host(answers):
    return answers.turn_name or answers.public_name


def coturn_tls_port(answers):
    """Le port TLS de coturn : 443 quand `turns_443`, sinon `turns_port`."""
    return TURNS_ALT_PORT if answers.turns_443 else answers.turns_port


def relay_range(answers):
    """(min, max) des relais : en production, la plage par défaut des
    réponses devient PROD_MIN_PORT–PROD_MAX_PORT ; une plage choisie
    reste."""
    pair = (answers.min_port, answers.max_port)
    if is_production(answers) and pair == (DEV_MIN_PORT, DEV_MAX_PORT):
        return PROD_MIN_PORT, PROD_MAX_PORT
    return pair


def _nginx_ports(answers):
    """Ports que nginx écoute en production : 80 dès qu'il sert (défi
    ACME, redirection), 443 quand il porte le site de ntfy."""
    if not is_production(answers) or answers.nginx is None:
        return []
    ports = [HTTP_PORT]
    if "ntfy" in answers.services:
        ports.append(HTTPS_PORT)
    return ports


def _certbot_ports(answers):
    """Port que certbot autonome ouvre le temps d'un défi HTTP-01."""
    if (
        is_production(answers)
        and answers.tls == "letsencrypt"
        and answers.acme == "http-standalone"
    ):
        return [HTTP_PORT]
    return []


def external_ip_for(turn_name, addresses, resolve=socket.getaddrinfo):
    """(adresse, raison) pour `external-ip` de coturn.

    `resolve` (forme de `socket.getaddrinfo`) donne les adresses du nom de
    TURN ; `addresses` sont celles des interfaces de l'hôte
    (`HostFacts.addresses`). L'IPv4 est jugée d'abord : un relais IPv4
    derrière un NAT a besoin d'external-ip même quand l'IPv6 du nom est sur
    l'hôte. Raisons : « local » (une adresse résolue de la famille jugée
    est sur l'hôte, pas d'external-ip), « nat » (aucune ne l'est : la
    première est proposée), « unresolved » (le nom ne résout pas : à
    demander), avec None pour adresse.
    """
    try:
        found = resolve(turn_name, None)
    except (OSError, UnicodeError):
        return None, "unresolved"
    resolved = []
    for entry in found or ():
        try:
            address = ipaddress.ip_address(str(entry[4][0]).split("%", 1)[0])
        except (IndexError, TypeError, ValueError):
            continue
        if address not in resolved:
            resolved.append(address)
    if not resolved:
        return None, "unresolved"
    local = set()
    for value in addresses:
        try:
            local.add(ipaddress.ip_address(str(value).split("%", 1)[0]))
        except ValueError:
            continue
    v4 = [a for a in resolved if a.version == 4]
    judged = v4 or resolved
    for address in judged:
        if address in local:
            return str(address), "local"
    return str(judged[0]), "nat"


def ntfy_port(answers):
    """Port de ntfy : `answers.ntfy_port`, sinon 8080 en http et 8443 avec
    un certificat fourni en développement ; en production, son port sur
    127.0.0.1, 8080 par défaut."""
    if answers.ntfy_port is not None:
        return answers.ntfy_port
    return NTFY_HTTPS_PORT if _ntfy_own_tls(answers) else NTFY_HTTP_PORT


def ntfy_http_port(answers):
    """Port http de ntfy. Avec un certificat en développement, http
    n'écoute que sur 127.0.0.1 (la sonde de santé d'`inspect_script` le
    lit) : 8080, ou 8081 quand https a pris 8080. En production, c'est
    `ntfy_port`, sur 127.0.0.1."""
    if not _ntfy_own_tls(answers):
        return ntfy_port(answers)
    return (
        NTFY_HTTP_PORT + 1
        if ntfy_port(answers) == NTFY_HTTP_PORT
        else (NTFY_HTTP_PORT)
    )


def _url_host(name):
    try:
        if ipaddress.ip_address(name).version == 6:
            return f"[{name}]"
    except ValueError:
        pass
    return name


def ntfy_base_url(answers):
    """URL publique de ntfy : en production `https://<nom de ntfy>`, sans
    port (nginx sert 443) ; sinon le nom public et le port de ntfy."""
    if is_production(answers):
        return f"https://{_url_host(ntfy_host(answers))}"
    scheme = "https" if _ntfy_own_tls(answers) else "http"
    return f"{scheme}://{_url_host(answers.public_name)}:{ntfy_port(answers)}"


# Plages refusées aux relais en production : DENIED_PEER_RANGES
# d'install_coturn.sh, dans le même ordre (un test compare les deux).
DENIED_PEER_RANGES = (
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


def coturn_config(answers, turn_mode=None):
    """Le `turnserver.conf` qu'`install_coturn.sh` (`write_config`) écrit
    pour ces réponses, au caractère près : il sert au diff montré avant
    d'adopter et à reconnaître une configuration déjà à jour.

    `turn_mode` est celui de l'état (`TURN_AUTH` de l'installateur) :
    « secret » écrit `use-auth-secret`, tout autre valeur `lt-cred-mech`.

    Développement : TURN_ALLOW_PRIVATE=1, aucune ligne `denied-peer-ip`.
    Production : une ligne `denied-peer-ip` par plage de
    DENIED_PEER_RANGES, la plage des relais de `relay_range`. Un
    certificat, fourni ou de Let's Encrypt, ouvre TLS sur
    `coturn_tls_port` (443 avec `turns_443`, que l'installateur reçoit en
    TURN_ALT_TLS_PORT)."""
    low, high = relay_range(answers)
    lines = [
        MARKER,
        "# Comptes dans userdb, pas ici. Ecrit par install_coturn.sh.",
        f"listening-port={answers.turn_port}",
    ]
    if has_tls(answers):
        lines += [
            f"tls-listening-port={coturn_tls_port(answers)}",
            f"cert={COTURN_TLS_DIR}/turn.crt",
            f"pkey={COTURN_TLS_DIR}/turn.key",
        ]
    else:
        lines += ["no-tls", "no-dtls"]
    lines += [
        f"min-port={low}",
        f"max-port={high}",
        "fingerprint",
        "use-auth-secret" if turn_mode == "secret" else "lt-cred-mech",
        f"realm={answers.public_name}",
        f"userdb={COTURN_DB}",
        "no-cli",
        "no-multicast-peers",
    ]
    if is_production(answers):
        lines += [f"denied-peer-ip={r}" for r in DENIED_PEER_RANGES]
    if answers.external_ip:
        lines.append(f"external-ip={answers.external_ip}")
    lines += [
        "syslog",
        "no-rfc5780",
        "no-stun-backward-compatibility",
        "response-origin-only-with-rfc5780",
    ]
    return "\n".join(lines) + "\n"


# Base d'un `server.yml` neuf, sur le modèle de celui d'install_ntfy.sh ;
# `ntfy_config` y pose ensuite les clés que l'outil gère.
_NTFY_TEMPLATE = f"""{MARKER}
# NTFY Server configuration
# Documentation: https://ntfy.sh/docs/config/

base-url: ""
listen-http: ""

cache-file: "/var/cache/ntfy/cache.db"
cache-duration: "12h"

log-level: info

attachment-cache-dir: "/var/cache/ntfy/attachments"
attachment-total-size-limit: "5G"
attachment-file-size-limit: "15M"
attachment-expiry-duration: "3h"

auth-file: "{NTFY_AUTH_FILE}"
auth-default-access: "deny-all"
"""


def _drop_key(text, key):
    """Retire les lignes actives de `key` ; les autres restent à l'octet
    près."""
    pattern = re.compile(rf"{re.escape(key)}\s*:")
    return "".join(
        line
        for line in text.splitlines(keepends=True)
        if not pattern.match(line)
    )


def _has_live_line(text):
    return any(
        line.strip() and not line.lstrip().startswith("#")
        for line in text.splitlines()
    )


def ntfy_config(answers, existing=None):
    """Le `server.yml` voulu, à partir de celui en place (`existing`).

    Un fichier qui porte des réglages est édité par `_set_key` : ses autres
    lignes, dont les hôtes exemptés et le contrôle d'accès choisi, restent
    telles quelles. Sans fichier, ou avec un fichier fait de commentaires
    seulement, la base est `_NTFY_TEMPLATE`. Clés posées : MARKER en tête,
    `base-url`, `listen-http`, et avec un certificat en développement
    `listen-https`, `cert-file`, `key-file` (retirées sinon). En
    production, ntfy n'écoute que sur 127.0.0.1 derrière nginx :
    `behind-proxy: true` (l'adresse du client vient de X-Forwarded-For,
    sans quoi chaque client serait 127.0.0.1) et `web-root: disable`, ou
    `app` avec `ntfy_web`. `auth-file` et `auth-default-access: deny-all`
    sont ajoutées seulement si elles manquent : avec elles,
    install_ntfy.sh garde le fichier tel quel. Appliquée à son propre
    résultat, elle le rend inchangé.
    """
    text = (
        existing if existing and _has_live_line(existing) else (_NTFY_TEMPLATE)
    )
    if not is_managed(text):
        text = MARKER + "\n" + text
    text = nm._set_key(text, "base-url", ntfy_base_url(answers), True)
    if is_production(answers):
        http = f"127.0.0.1:{ntfy_http_port(answers)}"
        text = nm._set_key(text, "listen-http", http, True)
        for key in ("listen-https", "cert-file", "key-file"):
            text = _drop_key(text, key)
        text = nm._set_key(text, "behind-proxy", "true", False)
        web = "app" if answers.ntfy_web else "disable"
        text = nm._set_key(text, "web-root", web, False)
        return _ntfy_auth_keys(text)
    # Un retour au développement retire ce que la production a posé.
    for key in ("behind-proxy", "web-root"):
        text = _drop_key(text, key)
    if _ntfy_own_tls(answers):
        http = f"127.0.0.1:{ntfy_http_port(answers)}"
        text = nm._set_key(text, "listen-http", http, True)
        text = nm._set_key(
            text, "listen-https", f":{ntfy_port(answers)}", True
        )
        text = nm._set_key(text, "cert-file", f"{NTFY_TLS_DIR}/ntfy.crt", True)
        text = nm._set_key(text, "key-file", f"{NTFY_TLS_DIR}/ntfy.key", True)
    else:
        text = nm._set_key(text, "listen-http", f":{ntfy_port(answers)}", True)
        for key in ("listen-https", "cert-file", "key-file"):
            text = _drop_key(text, key)
    return _ntfy_auth_keys(text)


def _ntfy_auth_keys(text):
    """`text` avec `auth-file` et `auth-default-access: deny-all` quand
    elles manquent ; présentes, elles restent telles quelles."""
    keys = nm.read_yml_keys(text)
    if not keys.get("auth-file"):
        text = nm._set_key(text, "auth-file", NTFY_AUTH_FILE, True)
    if "auth-default-access" not in keys:
        text = nm._set_key(text, "auth-default-access", "deny-all", True)
    return text


# --- Contrôles --------------------------------------------------------------


# Clés dont la valeur est un secret, dans turnserver.conf (`clé=valeur`,
# `clé valeur`) et server.yml (`clé: valeur`) : static-auth-secret,
# cli-password, pkey-pwd, smtp-sender-pass, web-push-private-key,
# upstream-access-token, et les connexions aux bases de coturn, qui portent
# un mot de passe. `user=<nom>:<mot de passe>` garde son nom ; les listes
# auth-users et auth-tokens de ntfy perdent chacun de leurs éléments, en
# tirets comme entre crochets, sur une ligne ou sur plusieurs. En dernier
# filet, toute empreinte bcrypt (`$2a$`, `$2b$`, `$2y$`) et tout jeton ntfy
# (`tk_…`) sont masqués où qu'ils soient, commentaires compris.
_SECRET_KEY = re.compile(
    r"secret|pass|pwd|token|private-key|^(psql|mysql|mongo|redis)-", re.I
)
_SECRET_LISTS = ("auth-users", "auth-tokens")
_CONF_LINE = re.compile(r"^(\s*)([A-Za-z0-9_.-]+)(\s*[:=]\s*|\s+)(.*)$")
_LIST_ITEM = re.compile(r"^(\s*-\s*)\S")
_BCRYPT = re.compile(r"\$2[aby]\$\d{2}\$[./A-Za-z0-9]+")
_NTFY_TOKEN = re.compile(r"\btk_[A-Za-z0-9]+")


def _redact_flow_item(body):
    """(ligne masquée, liste encore ouverte) pour une ligne d'une liste
    entre crochets ouverte plus haut ; « ] » la ferme."""
    stripped = body.strip()
    if stripped.startswith("]"):
        return body, False
    indent = body[: len(body) - len(body.lstrip())]
    closes = "]" in stripped
    return indent + ("***]" if closes else "***"), not closes


def redact_secrets(text):
    """`text` dont chaque valeur secrète devient « *** », guillemets gardés ;
    les autres lignes restent à l'octet près. Sert au diff montré à
    l'écran, jamais au fichier écrit."""
    lines, in_list, in_flow = [], False, False
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        end = line[len(body) :]
        if in_flow:
            body, in_flow = _redact_flow_item(body)
            lines.append(body + end)
            continue
        if in_list:
            item = _LIST_ITEM.match(body)
            if item:
                lines.append(item.group(1) + "***" + end)
                continue
            in_list = False
        match = _CONF_LINE.match(body)
        if match and not body.lstrip().startswith("#"):
            indent, key, sep, value = match.groups()
            bare = value.strip()
            secret = key in _SECRET_LISTS or _SECRET_KEY.search(key)
            if key in _SECRET_LISTS and not bare:
                in_list = True
            elif secret and bare.startswith("["):
                in_flow = not bare.endswith("]")
                shown = (
                    "[" if bare == "[" else "[***" + ("" if in_flow else "]")
                )
                body = f"{indent}{key}{sep}{shown}"
            elif key == "user" and ":" in bare:
                body = f"{indent}{key}{sep}{bare.split(':', 1)[0]}:***"
            elif secret and bare:
                quote = bare[0] if bare[0] in "\"'" else ""
                body = f"{indent}{key}{sep}{quote}***{quote}"
        body = _NTFY_TOKEN.sub("tk_***", _BCRYPT.sub("***", body))
        lines.append(body + end)
    return "".join(lines)


def _check_answers(answers):
    """ValueError pour une réponse hors contrat (erreur de l'appelant) ;
    Refusal `call_infra_bad_value` pour une valeur que l'installateur
    refuserait après avoir commencé."""
    if not answers.services or not answers.services <= set(SERVICES):
        raise ValueError(f"services: {sorted(answers.services)}")
    if answers.mode not in MODES:
        raise ValueError(f"mode: {answers.mode}")
    if answers.tls not in TLS_MODES:
        raise ValueError(f"tls: {answers.tls}")
    if answers.nginx is not None and answers.nginx not in NGINX_MODES:
        raise ValueError(f"nginx: {answers.nginx}")
    if not is_production(answers) and (
        answers.tls == "letsencrypt" or answers.turns_443
    ):
        raise ValueError("letsencrypt and turns_443 need production mode")
    if answers.tls == "letsencrypt" and answers.acme not in ACME_METHODS:
        raise ValueError(f"acme: {answers.acme}")
    if answers.tls == "supplied" and not (
        answers.cert_pem and answers.key_pem
    ):
        raise ValueError("tls supplied without certificate and key")
    if not _NAME.match(answers.public_name or ""):
        raise Refusal(
            "call_infra_bad_value",
            name="public_name",
            value=answers.public_name,
        )
    if is_production(answers):
        for name in ("ntfy_name", "turn_name"):
            value = getattr(answers, name)
            if value is not None and not _NAME.match(value):
                raise Refusal("call_infra_bad_value", name=name, value=value)
        if answers.email and not _EMAIL.match(answers.email):
            raise Refusal(
                "call_infra_bad_value", name="email", value=answers.email
            )
    ports = {
        "turn_port": answers.turn_port,
        "turns_port": answers.turns_port,
        "min_port": answers.min_port,
        "max_port": answers.max_port,
        "ntfy_port": ntfy_port(answers),
    }
    for name, port in ports.items():
        if not isinstance(port, int) or not 1 <= port <= 65535:
            raise Refusal("call_infra_bad_value", name=name, value=port)
    if answers.min_port > answers.max_port:
        raise Refusal(
            "call_infra_bad_value",
            name="min_port",
            value=f"{answers.min_port}-{answers.max_port}",
        )
    if answers.external_ip and not _EXTERNAL_IP.match(answers.external_ip):
        raise Refusal(
            "call_infra_bad_value",
            name="external_ip",
            value=answers.external_ip,
        )


def _check_port_values(answers):
    """Refusal `call_infra_bad_value` pour une règle sur le port de ssh ou
    deux écoutes sur le même port. Après `_check_production` : nginx et
    certbot autonome sur 80 sont un défi mal choisi avant d'être un
    doublon."""
    firewall_rules(answers)
    seen = {}
    for proto, port, svc in needed_ports(answers):
        if (proto, port) in seen:
            raise Refusal(
                "call_infra_bad_value", name="ports", value=f"{port}/{proto}"
            )
        seen[(proto, port)] = svc


def needed_ports(answers):
    """[(proto, port, service)] que les services choisis vont écouter. La
    plage des relais n'y est pas : coturn passe un port pris, et `ss` y
    liste aussi les sockets clients éphémères. En production s'y ajoutent
    80 et 443 de nginx, 80 de certbot autonome ; le port de ntfy, sur
    127.0.0.1, y reste : il doit être libre, sans être ouvert au pare-feu
    (`firewall_rules`)."""
    ports = [("tcp", p, "nginx") for p in _nginx_ports(answers)]
    ports += [("tcp", p, "certbot") for p in _certbot_ports(answers)]
    if "coturn" in answers.services:
        ports += [
            ("udp", answers.turn_port, "coturn"),
            ("tcp", answers.turn_port, "coturn"),
        ]
        if has_tls(answers):
            ports.append(("tcp", coturn_tls_port(answers), "coturn"))
    if "ntfy" in answers.services:
        ports.append(("tcp", ntfy_port(answers), "ntfy"))
        if _ntfy_own_tls(answers):
            ports.append(("tcp", ntfy_http_port(answers), "ntfy"))
    return ports


def _check_ports(facts, answers):
    """Refusal `call_infra_port_busy` pour un port voulu qu'un autre
    processus tient ; un libellé sans processus connu (certbot) veut son
    port libre de tout processus."""
    for proto, port, svc in needed_ports(answers):
        for busy_proto, busy_port, process in facts.busy_ports:
            if (busy_proto, busy_port) == (proto, port) and (
                process != PROCESSES.get(svc)
            ):
                raise Refusal(
                    "call_infra_port_busy",
                    proto=proto,
                    port=port,
                    process=process,
                )


def _certificate_facts(cert_pem):
    """(fin de validité en datetime UTC, noms DNS, adresses IP, sujet) du
    premier certificat de `cert_pem`, lus par la commande openssl."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "cert.pem")
        with open(path, "w") as handle:
            handle.write(cert_pem)
        try:
            done = subprocess.run(
                [
                    "openssl",
                    "x509",
                    "-noout",
                    "-enddate",
                    "-ext",
                    "subjectAltName",
                    "-subject",
                    "-in",
                    path,
                ],
                capture_output=True,
                text=True,
                check=True,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            reason = getattr(exc, "stderr", None) or str(exc)
            raise Refusal(
                "call_infra_cert_unreadable", reason=reason.strip()
            ) from None
    not_after, subject, dns, ips = None, "", [], []
    lines = done.stdout.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("notAfter="):
            seconds = ssl.cert_time_to_seconds(line.split("=", 1)[1].strip())
            not_after = datetime.datetime.fromtimestamp(
                seconds, datetime.timezone.utc
            )
        elif line.startswith("subject="):
            subject = line.split("=", 1)[1].strip()
        elif "Subject Alternative Name" in line and index + 1 < len(lines):
            for entry in lines[index + 1].split(","):
                kind, _, value = entry.strip().partition(":")
                if kind == "DNS":
                    dns.append(value.strip())
                elif kind == "IP Address":
                    ips.append(value.strip())
    if not_after is None:
        raise Refusal("call_infra_cert_unreadable", reason="notAfter")
    return not_after, dns, ips, subject


def _key_matches(cert_pem, key_pem):
    """Vrai quand la clé va avec le certificat : `load_cert_chain` les
    rapproche. Une clé chiffrée reçoit un mot de passe vide et échoue,
    sans invite au terminal ; coturn et ntfy ne pourraient pas la lire."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    with tempfile.TemporaryDirectory() as tmp:
        cert = os.path.join(tmp, "cert.pem")
        key = os.path.join(tmp, "key.pem")
        with open(cert, "w") as handle:
            handle.write(cert_pem)
        with open(key, "w") as handle:
            handle.write(key_pem)
        try:
            context.load_cert_chain(cert, key, password=lambda: b"")
        except ssl.SSLError:
            return False
    return True


def _name_covered(name, dns, ips):
    """Une adresse se cherche parmi les IP du certificat ; un nom parmi ses
    noms DNS, `*.domaine` couvrant une seule étiquette. Le CN seul ne
    compte pas : les clients actuels l'ignorent."""
    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        address = None
    if address is not None:
        for value in ips:
            try:
                if ipaddress.ip_address(value) == address:
                    return True
            except ValueError:
                continue
        return False
    wanted = name.lower().rstrip(".")
    for pattern in dns:
        pattern = pattern.lower().rstrip(".")
        if pattern == wanted:
            return True
        if (
            pattern.startswith("*.")
            and "." in wanted
            and wanted.split(".", 1)[1] == pattern[2:]
        ):
            return True
    return False


def certificate_names(answers):
    """Les noms qu'un certificat fourni doit couvrir : le nom public en
    développement ; en production, le nom de TURN avec coturn et celui de
    ntfy avec ntfy."""
    if not is_production(answers):
        return [answers.public_name]
    names = []
    if "coturn" in answers.services:
        names.append(turn_host(answers))
    if "ntfy" in answers.services and ntfy_host(answers) not in names:
        names.append(ntfy_host(answers))
    return names


def _check_certificate(answers, now):
    not_after, dns, ips, subject = _certificate_facts(answers.cert_pem)
    if not _key_matches(answers.cert_pem, answers.key_pem):
        raise Refusal("call_infra_cert_key_mismatch")
    if now.tzinfo is None:
        now = now.replace(tzinfo=datetime.timezone.utc)
    if not_after <= now:
        raise Refusal(
            "call_infra_cert_expired", date=not_after.strftime("%Y-%m-%d")
        )
    for wanted in certificate_names(answers):
        if not _name_covered(wanted, dns, ips):
            names = [f"DNS:{d}" for d in dns] + [f"IP:{i}" for i in ips]
            raise Refusal(
                "call_infra_cert_name_missing",
                name=wanted,
                names=", ".join(names) or subject,
            )


def _check_production(facts, answers):
    """Refus propres à la production, avant les ports : sans TLS
    (`call_infra_prod_needs_tls`), ntfy sans nginx
    (`call_infra_prod_needs_nginx`), défi ACME que les services ne
    permettent pas (`call_infra_acme_method` : certbot autonome quand
    nginx sert ou écoute déjà 80, webroot sans nginx), greffon DNS inconnu
    ou sans identifiants (`call_infra_dns_plugin`), nom que nginx servirait
    déjà servi par un site que l'outil n'a pas écrit
    (`call_infra_nginx_name_taken`, avec ce fichier : deux `server_name`
    égaux sur un port, nginx n'en garde qu'un), 443 pour coturn quand
    nginx s'en sert ou qu'un autre processus le tient
    (`call_infra_turns_443`)."""
    if answers.tls == "none":
        raise Refusal("call_infra_prod_needs_tls")
    if "ntfy" in answers.services and answers.nginx is None:
        raise Refusal("call_infra_prod_needs_nginx")
    nginx_on_80 = any(
        busy == ("tcp", HTTP_PORT, PROCESSES["nginx"])
        for busy in facts.busy_ports
    )
    if answers.tls == "letsencrypt":
        method = answers.acme
        if (
            method == "http-standalone"
            and (answers.nginx is not None or nginx_on_80)
        ) or (method == "http-nginx" and answers.nginx is None):
            raise Refusal("call_infra_acme_method", method=method)
        if method == "dns" and (
            answers.dns_plugin not in DNS_PLUGINS
            or not (answers.dns_credentials or "").strip()
        ):
            raise Refusal(
                "call_infra_dns_plugin", plugin=answers.dns_plugin or ""
            )
    if answers.nginx is not None:
        taken = _nginx_taken(facts)
        for wanted in certificate_names(answers):
            where = taken.get(wanted.lower())
            if where is not None:
                raise Refusal(
                    "call_infra_nginx_name_taken", name=wanted, file=where
                )
    if answers.turns_443 and "coturn" in answers.services:
        others = [
            process
            for proto, port, process in facts.busy_ports
            if (proto, port) == ("tcp", TURNS_ALT_PORT)
            and process != PROCESSES["coturn"]
        ]
        holder = "nginx" if answers.nginx is not None else None
        holder = holder or (others[0] if others else None)
        if holder is not None:
            raise Refusal(
                "call_infra_turns_443",
                holder=holder,
                port=answers.turns_port,
            )


def _nginx_present(facts):
    return bool(facts.nginx) and facts.nginx.get("state") != "absent"


def _nginx_taken(facts):
    """{nom en minuscules: fichier} des `server_name` exacts des sites
    étrangers. Un joker (`*.x`, `.x`), une expression (`~...`) ou « _ » ne
    prennent aucun nom : nginx préfère le nom exact de l'outil."""
    taken = {}
    if not _nginx_present(facts):
        return taken
    for name, where in facts.nginx.get("names") or ():
        key = name.lower().rstrip(".")
        if _NAME.match(key) and key not in taken:
            taken[key] = where
    return taken


# --- Plan -------------------------------------------------------------------


def _settings(svc, answers, cert_sha):
    """Ce qu'un service a reçu ; deux plans aux mêmes réglages ne changent
    rien à ce service.

    Un plan de développement garde les clés d'avant le mode production, à
    l'identique : un état de développement déjà écrit reste « rien à
    changer ». La production y ajoute les
    noms, la source du certificat (`acme`, `dns_plugin`, `email`) et
    `nginx` en booléen : un nginx que l'outil a installé existe à la
    relance, « install » et « existing » y reviennent au même. Le fichier
    d'identifiants DNS, secret, n'y est jamais."""
    low, high = relay_range(answers)
    if svc == "coturn":
        settings = {
            "tls": answers.tls,
            "public_name": answers.public_name,
            "turn_port": answers.turn_port,
            "turns_port": answers.turns_port,
            "min_port": low,
            "max_port": high,
            "external_ip": answers.external_ip or None,
            "cert_sha256": cert_sha,
        }
        extra = {
            "turn_name": turn_host(answers),
            "turns_443": answers.turns_443,
        }
    else:
        settings = {
            "tls": answers.tls,
            "public_name": answers.public_name,
            "port": ntfy_port(answers),
            "http_port": ntfy_http_port(answers),
            "base_url": ntfy_base_url(answers),
            "cert_sha256": cert_sha,
        }
        extra = {"ntfy_name": ntfy_host(answers), "web": answers.ntfy_web}
    if is_production(answers):
        settings.update(extra)
        settings.update(
            {
                "acme": answers.acme if answers.tls == "letsencrypt" else None,
                "dns_plugin": (
                    answers.dns_plugin
                    if answers.tls == "letsencrypt" and answers.acme == "dns"
                    else None
                ),
                "email": answers.email,
                "nginx": answers.nginx is not None,
            }
        )
    return settings


def _origin(current, prior_record):
    """Ce que l'hôte avait avant l'outil : du dernier état écrit, sinon de la
    fiche d'une installation interrompue, sinon de la sonde. `backup` vaut
    None pour une adoption de ce passage ; `written_state` le complète.

    `was_active` (l'unité tournait) et `was_enabled` (sa réponse à
    `systemctl is-enabled`) disent ce que la désinstallation d'un service
    adopté remet : les installateurs activent et démarrent toujours
    l'unité. None quand l'unité n'existait pas, ou pour un état écrit
    avant que l'outil ne les consigne."""
    for source in (prior_record, (current or {}).get("pending")):
        if isinstance(source, dict) and "installed_by_tool" in source:
            was_active = source.get("was_active")
            was_enabled = source.get("was_enabled")
            # `admin_added` (voir `mark_admin_added`) ne vit que dans l'état.
            admin = (
                {"admin_added": True}
                if source.get("admin_added") is True
                else {}
            )
            return admin | {
                "installed_by_tool": bool(source.get("installed_by_tool")),
                "adopted": bool(source.get("adopted")),
                "backup": source.get("backup"),
                "was_active": (
                    was_active if isinstance(was_active, bool) else None
                ),
                "was_enabled": (
                    was_enabled
                    if isinstance(was_enabled, str)
                    and _UNIT_STATE.match(was_enabled)
                    else None
                ),
            }
    found = bool(current and current.get("unit_found"))
    return {
        "installed_by_tool": not found,
        "adopted": bool(current) and is_foreign(current["config_text"]),
        "backup": None,
        "was_active": current.get("active") == "active" if found else None,
        "was_enabled": current.get("enabled") if found else None,
    }


def _nginx_paths(layout):
    """(site, lien dans sites-enabled, nginx.conf quand l'outil y a sa
    ligne include) d'une disposition : `site_path`, `link_path` et
    `ensure_include` d'install_nginx.sh."""
    if layout == "debian":
        return (
            f"/etc/nginx/sites-available/{NGINX_SITE_FILE}",
            f"/etc/nginx/sites-enabled/{NGINX_SITE_FILE}",
            None,
        )
    if layout == "confd":
        return f"/etc/nginx/conf.d/{NGINX_SITE_FILE}", None, None
    return f"{NGINX_INCLUDE_DIR}/{NGINX_SITE_FILE}", None, NGINX_CONF


def _tool_origin(prior_record, pending, present):
    """(installé par l'outil, source) : du dernier état écrit, sinon de la
    fiche d'un passage coupé, sinon de la sonde (absent : ce passage
    l'installe). `source` est le dict lu, None pour la sonde."""
    for source in (prior_record, pending):
        if isinstance(source, dict) and "installed_by_tool" in source:
            return bool(source["installed_by_tool"]), source
    return not present, None


def _nginx_settings(answers):
    """Ce que nginx reçoit d'un plan ; deux plans aux mêmes valeurs ne
    changent rien au site."""
    ntfy = "ntfy" in answers.services
    http_challenge = (
        answers.tls == "letsencrypt" and answers.acme == "http-nginx"
    )
    return {
        "names": certificate_names(answers),
        "ntfy_name": ntfy_host(answers) if ntfy else None,
        "upstream_port": ntfy_http_port(answers) if ntfy else None,
        "acme_root": ACME_ROOT if http_challenge else None,
        "tls_files": (
            [SITE_CERT, SITE_KEY] if answers.tls == "supplied" else []
        ),
    }


def certbot_authenticator(answers):
    """L'authentificateur que certbot inscrit dans le fichier de
    renouvellement pour la méthode de `answers` : « webroot »,
    « standalone » ou « dns-<greffon> »."""
    if answers.acme == "dns":
        return f"dns-{answers.dns_plugin}"
    return CERTBOT_METHODS[answers.acme]


def _credentials_sha256(answers):
    """Empreinte du fichier d'identifiants DNS : l'état ne garde jamais le
    secret, mais un jeton remplacé doit être reposé à la relance."""
    if answers.acme != "dns" or answers.dns_credentials is None:
        return None
    return hashlib.sha256(answers.dns_credentials.encode()).hexdigest()


def _certbot_settings(answers):
    dns = answers.acme == "dns"
    return {
        "method": answers.acme,
        "plugin": answers.dns_plugin if dns else None,
        "names": certificate_names(answers),
        "email": answers.email,
        "credentials_sha256": _credentials_sha256(answers),
    }


def _nginx_record(facts, answers, prior):
    """Fiche « nginx » de l'état. `installed_by_tool`, `layout` (et `site`,
    `link`, `include` qui en découlent) et `backup` (copie de nginx.conf
    d'avant la ligne include) sont des valeurs de plan : le script les
    remplace par ce qu'install_nginx.sh imprime (`installed_state`).

    `was_active` et `was_enabled` disent ce qu'était un nginx déjà là,
    qu'install_nginx.sh active et démarre : la désinstallation le remet
    arrêté ou désactivé (comme `_origin` pour les services). None pour un
    nginx que l'outil pose, ou pour un état qui ne les consigne pas."""
    record = prior.get("nginx")
    record = record if isinstance(record, dict) else {}
    pending = (facts.nginx or {}).get("pending")
    tool, source = _tool_origin(record, pending, _nginx_present(facts))
    if source is not None:
        was_active = source.get("was_active")
        was_enabled = source.get("was_enabled")
    elif not tool:
        was_active = facts.nginx.get("state") == "active"
        was_enabled = facts.nginx.get("enabled")
    else:
        was_active = was_enabled = None
    layout = (facts.nginx or {}).get("layout")
    if not _nginx_present(facts) or layout not in NGINX_LAYOUTS:
        # Le paquet Debian inclut sites-enabled ; celui d'Arch, aucun
        # dossier.
        layout = "debian" if facts.family == "debian" else "arch-include"
    site, link, include = _nginx_paths(layout)
    backup = record.get("backup")
    return {
        "installed_by_tool": tool,
        "layout": layout,
        "site": site,
        "link": link,
        "include": include,
        "backup": backup if _run_path(backup) else None,
        "applied": NGINX_APPLIED,
        "was_active": was_active if isinstance(was_active, bool) else None,
        "was_enabled": (
            was_enabled
            if isinstance(was_enabled, str) and _UNIT_STATE.match(was_enabled)
            else None
        ),
        **_nginx_settings(answers),
    }


def _nginx_include_added(facts, record):
    """Vrai quand install_nginx.sh ajoutera sa ligne include à nginx.conf :
    disposition arch-include sans la ligne. nginx absent, la disposition
    du record est celle du paquet que ce passage installe."""
    return record["layout"] == "arch-include" and not (
        (facts.nginx or {}).get("include")
    )


def _include_diff():
    """Le changement d'`ensure_include` (install_nginx.sh) à nginx.conf,
    montré avant le oui : une ligne à la fin du bloc http {}. La sonde ne
    lit pas nginx.conf, d'où un bloc sans numéros de ligne ;
    install_nginx.sh imprime le diff exact et garde la copie d'avant."""
    return (
        f"--- {NGINX_CONF}\n"
        f"+++ {NGINX_CONF}\n"
        "@@ http { } @@\n"
        " http {\n"
        "     ...\n"
        f"+    include {NGINX_INCLUDE_DIR}/*.conf;\n"
        " }\n"
    )


def _added_timer(found):
    """Fiche de minuteur `{unit, added: True}` du minuteur que la sonde dit
    ajouté par l'outil (`timer_added` de `HostFacts.certbot`), None sans."""
    unit = (found or {}).get("timer_added")
    return {"unit": unit, "added": True} if unit in CERTBOT_TIMERS else None


def _certbot_record(facts, answers, prior):
    """Fiche « certbot » de l'état : origine du paquet, paquets de greffons
    DNS que l'outil a installés (union des passages, ceux de la fiche d'un
    passage coupé compris), minuteur de renouvellement (celui de l'état,
    sinon celui que la sonde dit ajouté par l'outil ; `installed_state` le
    remplace par celui de `@@CERTBOT_TIMER`), lignée, identifiants DNS
    posés."""
    record = prior.get("certbot")
    record = record if isinstance(record, dict) else {}
    found = facts.certbot or {}
    tool, source = _tool_origin(
        record, found.get("pending"), bool(found.get("version"))
    )
    plugins = []
    for origin in (source, found.get("pending")):
        listed = origin.get("plugins_installed") if origin else None
        for p in listed if isinstance(listed, list) else ():
            if isinstance(p, str) and _PACKAGE.match(p) and p not in plugins:
                plugins.append(p)
    dns = answers.acme == "dns"
    if dns and answers.dns_plugin not in found.get("plugins", ()):
        package = DNS_PACKAGES[facts.family].format(answers.dns_plugin)
        if package not in plugins:
            plugins.append(package)
    timer = record.get("timer")
    return {
        "installed_by_tool": tool,
        "plugins_installed": plugins,
        "timer": timer if _timer_record(timer) else _added_timer(found),
        "cert_name": CERT_NAME,
        "lineage": LINEAGE_DIR,
        "renewal": RENEWAL_FILE,
        "dns_credentials": (
            f"{DNS_DIR}/{answers.dns_plugin}.ini" if dns else None
        ),
        **_certbot_settings(answers),
    }


def _carry_fiches(new_state, facts, answers):
    """Les fiches nginx et certbot d'un passage coupé que ce plan n'utilise
    pas (relance en développement, ou certificat fourni) passent dans
    l'état, que `install_script` écrit avant de retirer les fiches : sans
    cela, ce que ce passage a posé (paquets, greffons, site de l'étape
    acme, crochet) ne serait jamais défait. Une fiche absente de l'état
    devient une fiche minimale, aux chemins de l'outil ; une fiche déjà
    dans l'état n'y gagne que les greffons de celle du passage coupé et,
    quand elle n'en consigne aucun, le minuteur. Ce minuteur est celui que
    la sonde dit ajouté par l'outil (`_added_timer`) : la désinstallation
    l'arrête, et retire les unités propres de l'outil."""
    nginx_found, certbot_found = facts.nginx or {}, facts.certbot or {}
    pending = nginx_found.get("pending")
    if (
        not _uses_nginx(answers)
        and "nginx" not in new_state
        and isinstance(pending, dict)
        and "installed_by_tool" in pending
    ):
        layout = nginx_found.get("layout")
        if layout not in NGINX_LAYOUTS:
            layout = "debian" if facts.family == "debian" else "arch-include"
        site, link, include = _nginx_paths(layout)
        new_state["nginx"] = {
            "installed_by_tool": bool(pending["installed_by_tool"]),
            "layout": layout,
            "site": site,
            "link": link,
            "include": include,
            "backup": None,
            "applied": NGINX_APPLIED,
            "was_active": (
                pending.get("was_active")
                if isinstance(pending.get("was_active"), bool)
                else None
            ),
            "was_enabled": (
                pending.get("was_enabled")
                if isinstance(pending.get("was_enabled"), str)
                and _UNIT_STATE.match(pending["was_enabled"])
                else None
            ),
            "names": [],
            "ntfy_name": None,
            "upstream_port": None,
            "acme_root": ACME_ROOT,
            "tls_files": [],
        }
    pending = certbot_found.get("pending")
    if _uses_certbot(answers) or not isinstance(pending, dict):
        return
    record = new_state.get("certbot")
    if not isinstance(record, dict):
        if "installed_by_tool" not in pending:
            return
        record = {
            "installed_by_tool": bool(pending["installed_by_tool"]),
            "plugins_installed": [],
            "timer": None,
            "cert_name": CERT_NAME,
            "lineage": LINEAGE_DIR,
            "renewal": RENEWAL_FILE,
            "dns_credentials": None,
            "method": None,
            "plugin": None,
            "names": [],
            "email": "",
            "credentials_sha256": None,
        }
    plugins = record.get("plugins_installed")
    plugins = list(plugins) if isinstance(plugins, list) else []
    listed = pending.get("plugins_installed")
    for p in listed if isinstance(listed, list) else ():
        if p in _DNS_PLUGIN_PACKAGES and p not in plugins:
            plugins.append(p)
    timer = record.get("timer")
    if not _timer_record(timer):
        timer = _added_timer(certbot_found)
    new_state["certbot"] = dict(record, plugins_installed=plugins, timer=timer)


def _lineage_unchanged(facts, answers, prior):
    """Vrai quand la lignée active porte exactement les noms voulus, que son
    fichier de renouvellement passe par la méthode voulue et que les
    identifiants DNS sont ceux que l'état consigne : certbot n'a rien à
    éprouver."""
    found = facts.certbot or {}
    lineage = found.get("lineage")
    if lineage is None or found.get("held"):
        return False
    if found.get("authenticator") != certbot_authenticator(answers):
        return False
    record = prior.get("certbot")
    record = record if isinstance(record, dict) else {}
    if record.get("credentials_sha256") != _credentials_sha256(answers):
        return False
    wanted = {n.lower() for n in certificate_names(answers)}
    return {n.lower() for n in lineage} == wanted


def _certbot_force(facts, answers):
    """Vrai quand une lignée de l'hôte, active ou mise de côté, renouvelle
    par un autre authentificateur que celui de `answers`."""
    found = facts.certbot or {}
    current = found.get("authenticator")
    return (
        found.get("lineage") is not None or bool(found.get("held"))
    ) and current not in (None, certbot_authenticator(answers))


def _production_unchanged(facts, answers, prior):
    """Vrai quand nginx et certbot n'ont rien à refaire : fiches de l'état
    aux mêmes réglages, nginx actif, lignée aux mêmes noms, crochet posé."""

    def same(name, settings):
        record = prior.get(name)
        return isinstance(record, dict) and all(
            record.get(key) == value for key, value in settings.items()
        )

    if answers.nginx is not None and not (
        same("nginx", _nginx_settings(answers))
        and _nginx_present(facts)
        and facts.nginx.get("state") == "active"
    ):
        return False
    if answers.tls == "letsencrypt" and not (
        same("certbot", _certbot_settings(answers))
        and _lineage_unchanged(facts, answers, prior)
        and isinstance(prior.get("hook"), dict)
    ):
        return False
    return True


def plan_install(facts, answers, now):
    """Plan d'installation, ou Refusal avant que rien ne soit touché.

    Refus, dans l'ordre : système (`call_infra_unsupported_os`,
    `call_infra_no_systemd`), état d'une autre version
    (`call_infra_state_version`), réponses (`call_infra_bad_value`), en
    production ceux de `_check_production`, port tenu par un autre
    processus que le service réinstallé (`call_infra_port_busy`),
    certificat fourni illisible, d'une autre clé, expiré ou sans l'un des
    noms de `certificate_names` (`call_infra_cert_unreadable`,
    `call_infra_cert_key_mismatch`, `call_infra_cert_expired`,
    `call_infra_cert_name_missing`), nom public changé alors que des
    serveurs Odoo sont branchés (`call_infra_odoo_realm`).

    La configuration de coturn voulue suit le `turn_mode` de l'état
    (`coturn_config`) : une réinstallation garde le mode qu'un serveur Odoo
    a choisi. Les anciens secrets d'Odoo expirés partent de l'état et de la
    base (`purge_secrets`).

    `nothing_to_do` : chaque service choisi est consigné avec les mêmes
    réglages, son unité est active et sa configuration sur l'hôte est déjà
    celle voulue ; en production, nginx et certbot aussi
    (`_production_unchanged`). Les services consignés et non choisis
    restent dans l'état tels quels, comme toute clé inconnue de l'état
    (pare-feu...).

    Production : l'état gagne les fiches « nginx » (`_nginx_record`),
    « certbot » (`_certbot_record`) et « hook » quand le plan s'en sert, et
    la fiche de coturn son complément d'unité (`dropin`, None sans 443).
    """
    if facts.family is None:
        raise Refusal(
            "call_infra_unsupported_os",
            os=facts.os_id or "?",
            supported=SUPPORTED,
        )
    if not facts.systemd:
        raise Refusal("call_infra_no_systemd")
    prior = facts.state if isinstance(facts.state, dict) else {}
    if prior and prior.get("version") != STATE_VERSION:
        raise Refusal(
            "call_infra_state_version",
            found=prior.get("version"),
            expected=STATE_VERSION,
        )
    _check_answers(answers)
    readd = _odoo_readd(prior, answers)
    if is_production(answers):
        _check_production(facts, answers)
    _check_port_values(answers)
    _check_ports(facts, answers)
    cert_sha = None
    if answers.tls == "supplied":
        _check_certificate(answers, now)
        cert_sha = hashlib.sha256(answers.cert_pem.encode()).hexdigest()

    prior_services = prior.get("services")
    if not isinstance(prior_services, dict):
        prior_services = {}
    services = copy.deepcopy(prior_services)
    adopt, diffs, configs, unchanged = [], [], {}, bool(prior)
    for svc in SERVICES:
        if svc not in answers.services:
            continue
        current = facts.coturn if svc == "coturn" else facts.ntfy
        if svc == "coturn":
            unit = COTURN_UNITS[facts.family]
            config = COTURN_CONFIGS[facts.family]
            if current:
                unit, config = current["unit"], current["config"]
            desired = coturn_config(answers, prior.get("turn_mode"))
            tls_files = [
                f"{COTURN_TLS_DIR}/turn.crt",
                f"{COTURN_TLS_DIR}/turn.key",
            ]
            tls_files = tls_files if has_tls(answers) else []
        else:
            unit, config = NTFY_UNIT, NTFY_CONFIG
            desired = ntfy_config(
                answers, current["config_text"] if current else None
            )
            tls_files = [
                f"{NTFY_TLS_DIR}/ntfy.crt",
                f"{NTFY_TLS_DIR}/ntfy.key",
            ]
            tls_files = tls_files if _ntfy_own_tls(answers) else []
            configs[svc] = desired
        old_text = current["config_text"] if current else ""
        if current and is_foreign(old_text):
            adopt.append(svc)
        if old_text and old_text != desired:
            shown = (redact_secrets(old_text), redact_secrets(desired))
            diffs.append((config, nm.unified_diff(*shown, config)))
        prior_record = prior_services.get(svc)
        settings = _settings(svc, answers, cert_sha)
        unchanged = unchanged and (
            isinstance(prior_record, dict)
            and prior_record.get("settings") == settings
            and bool(current)
            and current.get("active") == "active"
            and old_text == desired
        )
        record = {"unit": unit, "config": config}
        record.update(_origin(current, prior_record))
        record["settings"] = settings
        record["tls_files"] = tls_files
        if svc == "coturn" and is_production(answers):
            # Complément d'unité qui laisse coturn servir TLS sur 443 ; la
            # désinstallation le retire.
            record["dropin"] = (
                COTURN_DROPIN.format(unit=unit) if answers.turns_443 else None
            )
        services[svc] = record

    stamp_now = now.isoformat(timespec="seconds")
    new_state = copy.deepcopy(prior)
    new_state.update(
        {
            "version": STATE_VERSION,
            "method": "packages",
            "mode": answers.mode,
            "created_at": prior.get("created_at") or stamp_now,
            "updated_at": stamp_now,
            "services": services,
        }
    )
    # Une fiche d'un passage précédent que ce plan n'utilise pas reste
    # telle quelle : la désinstallation défait encore ce qu'elle consigne
    # (avec ce qu'en dit la fiche d'un passage coupé, `_carry_fiches`).
    include = False
    if is_production(answers):
        if answers.nginx is not None:
            new_state["nginx"] = _nginx_record(facts, answers, prior)
            include = _nginx_include_added(facts, new_state["nginx"])
            if include and _nginx_present(facts):
                diffs.append((NGINX_CONF, _include_diff()))
            unchanged = unchanged and not include
        if answers.tls == "letsencrypt":
            new_state["certbot"] = _certbot_record(facts, answers, prior)
            new_state["hook"] = {"path": HOOK_PATH, "installed_by_tool": True}
        unchanged = unchanged and _production_unchanged(facts, answers, prior)
    before = [new_state.get(name) for name in ("nginx", "certbot")]
    _carry_fiches(new_state, facts, answers)
    # Une fiche à consigner demande un passage : l'état s'écrit.
    unchanged = unchanged and before == [
        new_state.get(name) for name in ("nginx", "certbot")
    ]
    new_state, purge = _purged(new_state, now)
    unchanged = unchanged and not purge
    letsencrypt = _uses_certbot(answers)
    return InstallPlan(
        answers=answers,
        adopt=tuple(adopt),
        diffs=tuple(diffs),
        nothing_to_do=unchanged,
        new_state=new_state,
        configs=configs,
        lineage_unchanged=(
            letsencrypt and _lineage_unchanged(facts, answers, prior)
        ),
        nginx_include=include,
        certbot_force=letsencrypt and _certbot_force(facts, answers),
        purge_secrets=tuple(purge),
        odoo_readd=readd,
    )


def _odoo_readd(prior, answers):
    """Clés des serveurs Odoo de `prior` dont les URL de TURN changent avec
    `answers`, triées. Le nom public est le realm de coturn : il entre dans
    la clé de chaque compte fixe et dans chaque ligne de `turn_secret`,
    rien ne se migre, et le changer avec des Odoo branchés est refusé
    (`call_infra_odoo_realm`). Un compte fixe ne reçoit pas de `turns:` :
    un changement de TLS ne concerne que les Odoo du module."""
    odoos = _odoos(prior)
    before = state_answers(prior) if odoos else None
    if (
        before is None
        or "coturn" not in before.services
        or "coturn" not in answers.services
    ):
        return ()
    if before.public_name != answers.public_name:
        raise Refusal(
            "call_infra_odoo_realm",
            old=before.public_name,
            new=answers.public_name,
            odoos=", ".join(sorted(odoos)),
        )
    changed = []
    for key, entry in odoos.items():
        module = isinstance(entry, dict) and entry.get("module") is True
        if _ice_urls_for(before, module) != _ice_urls_for(answers, module):
            changed.append(key)
    return tuple(sorted(changed))


def _is_backup_of(config, backup):
    """Vrai pour une copie `<config>.bak-<tampon>` : le chemin vient de
    l'hôte et finit dans un script lancé en root."""
    return (
        isinstance(config, str)
        and isinstance(backup, str)
        and backup.startswith(config + ".bak-")
        and bool(_STAMP.match(backup[len(config) + 5 :]))
    )


def written_state(plan, stamp):
    """L'état tel que `install_script` l'écrit : `new_state` où chaque
    adoption de ce passage reçoit sa copie `<config>.bak-<stamp>`, sauf
    celle qu'une fiche ou un état précédent nomme déjà (un passage coupé) :
    `install_script` copie vers ce chemin-là, le même qui est consigné."""
    state = copy.deepcopy(plan.new_state)
    for svc in plan.adopt:
        record = state["services"][svc]
        if record.get("adopted") and not _is_backup_of(
            record["config"], record.get("backup")
        ):
            record["backup"] = f"{record['config']}.bak-{stamp}"
    return state


def mark_admin_added(state, output):
    """Copie de `state` dont le ntfy adopté porte `admin_added: true` quand
    `output`, celle du script d'installation, montre que l'installateur y a
    créé NTFY_ADMIN_USER (`@@ADMIN_PASSWORD`) : la base des comptes d'un ntfy
    adopté reste à la désinstallation, ce compte-là doit en partir.
    `state` tel quel sinon."""
    created = any(
        name == "ADMIN_PASSWORD" and value.strip()
        for name, value in marker_lines(output or "")
    )
    services = state.get("services") if isinstance(state, dict) else None
    record = services.get("ntfy") if isinstance(services, dict) else None
    if (
        not created
        or not isinstance(record, dict)
        or not record.get("adopted")
    ):
        return state
    marked = copy.deepcopy(state)
    marked["services"]["ntfy"]["admin_added"] = True
    return marked


def state_answers(state):
    """Les réponses d'un état écrit, pour préremplir une relance ; None
    pour un état absent, d'une autre version ou sans service. Le
    certificat, la clé et le fichier d'identifiants DNS n'y sont pas :
    l'état ne garde que l'empreinte du certificat. Un état sans « mode »
    (écrit avant le mode production) est de développement ; un nginx
    consigné se relit « existing »."""
    if not isinstance(state, dict) or state.get("version") != STATE_VERSION:
        return None
    services = state.get("services")
    if not isinstance(services, dict):
        return None
    names = [s for s in SERVICES if isinstance(services.get(s), dict)]
    if not names:
        return None
    # Des réglages qui ne sont pas un dict (état abîmé) comptent pour
    # absents : les valeurs par défaut les remplacent.
    coturn, ntfy = (
        services[s].get("settings") if s in names else {} for s in SERVICES
    )
    coturn = coturn if isinstance(coturn, dict) else {}
    ntfy = ntfy if isinstance(ntfy, dict) else {}
    first = coturn or ntfy
    mode = state.get("mode", "development")
    production = mode == "production"

    def text(settings, key):
        value = settings.get(key) if production else None
        return value if isinstance(value, str) and value else None

    try:
        return Answers(
            services=frozenset(names),
            tls=first.get("tls", "none"),
            cert_pem=None,
            key_pem=None,
            public_name=first.get("public_name", ""),
            turn_port=int(coturn.get("turn_port", 3478)),
            turns_port=int(coturn.get("turns_port", 5349)),
            min_port=int(coturn.get("min_port", DEV_MIN_PORT)),
            max_port=int(coturn.get("max_port", DEV_MAX_PORT)),
            ntfy_port=int(ntfy["port"]) if ntfy.get("port") else None,
            external_ip=coturn.get("external_ip") or None,
            mode=mode if mode in MODES else "development",
            ntfy_name=text(ntfy, "ntfy_name"),
            turn_name=text(coturn, "turn_name"),
            acme=text(first, "acme"),
            dns_plugin=text(first, "dns_plugin"),
            email=text(first, "email") or "",
            ntfy_web=production and ntfy.get("web") is True,
            turns_443=production and coturn.get("turns_443") is True,
            nginx="existing" if production and first.get("nginx") else None,
        )
    except (TypeError, ValueError):
        return None


# --- Script d'installation --------------------------------------------------


def _b64(data):
    if isinstance(data, str):
        data = data.encode("utf-8")
    return base64.b64encode(data).decode("ascii")


def _host(path):
    """Chemin de l'hôte pour le script : préfixé de `$R`, entre guillemets."""
    return '"$R"' + shlex.quote(path)


def _installer_payload(svc):
    """Installateur lu sur le disque, compressé (mtime 0 : même texte, même
    charge) puis en base64 : le script entier tient encore dans un argument
    de `sh -c`, la forme où le test long le passe."""
    with open(INSTALLERS[svc], "rb") as handle:
        return _b64(gzip.compress(handle.read(), mtime=0))


def _decode_to(payload, target, gunzip=False):
    """Ligne `sh` qui écrit le base64 `payload` dans `target` (déjà cité
    pour le shell). `printf` est intégré au shell : la charge ne passe dans
    l'argv d'aucun programme que le script lance. Le texte du script, lui,
    ne reste hors de tout argv que lancé depuis un fichier, comme le font
    `ntfy_mobile.LocalHost` et `SshHost` pour un script root."""
    unzip = " | gzip -dc" if gunzip else ""
    return f"printf %s {shlex.quote(payload)} | base64 -d{unzip} > {target}"


def _export(variables, raw=None):
    """Lignes d'un sous-shell qui exportent `variables` (valeurs citées)
    et `raw` (expressions du shell, résolues sur l'hôte)."""
    lines = [
        f"  {name}={shlex.quote(str(value))}"
        for name, value in variables.items()
    ]
    lines += [f"  {name}={value}" for name, value in (raw or {}).items()]
    lines.append("  export " + " ".join([*variables, *(raw or {})]))
    return lines


def _place(payload, path, mode, group=None, gunzip=False):
    """Écrit un fichier de l'hôte par `.new` puis renommage, droits posés
    avant le renommage : le fichier n'existe jamais avec d'autres droits."""
    new, final = _host(path + ".new"), _host(path)
    owner = f" && chown root:{group} {new}" if group else ""
    return (
        _decode_to(payload, new, gunzip) + owner + f" && chmod {mode} {new}"
        f" && mv -f {new} {final}"
    )


# Lignée de l'outil sur l'hôte, pour les lignes du script (`$R` devant).
_LIVE = f'"$R"{shlex.quote(LINEAGE_DIR)}'


def _coturn_variables(plan):
    """Variables d'install_coturn.sh communes à ses passages."""
    return _coturn_env(
        plan.answers,
        plan.new_state.get("turn_mode"),
        "coturn" in plan.adopt,
    )


def _coturn_env(answers, turn_mode=None, adopt=False):
    """Variables d'install_coturn.sh pour `answers` : celles d'un plan
    (`_coturn_variables`) comme celles de la bascule de mode d'un ajout
    d'Odoo (`odoo_add_script`). `turn_mode` (« fixed », « secret ») part
    en TURN_AUTH ; None, d'un état qui n'en consigne pas, n'exporte rien
    et l'installateur garde son défaut, le mode fixe. `adopt` :
    TURN_GARDER_CONFIG=1."""
    low, high = relay_range(answers)
    variables = {
        "TURN_REALM": answers.public_name,
        "TURN_PORT": answers.turn_port,
        "TURN_TLS_PORT": answers.turns_port,
        "TURN_MIN_PORT": low,
        "TURN_MAX_PORT": high,
    }
    # Un plan de développement relaie aussi vers les plages privées (réseau
    # local, boucle locale) : sans TURN_ALLOW_PRIVATE=1, l'installateur les
    # refuse, et la configuration écrite ne serait plus celle que
    # `coturn_config` décrit. Un plan de production ne l'exporte jamais :
    # le défaut de l'installateur refuse ces plages.
    if answers.mode == "development":
        variables["TURN_ALLOW_PRIVATE"] = "1"
    # TLS sur 443 au lieu de TURN_TLS_PORT : coturn ne sert TLS que sur un
    # port à la fois. L'installateur refuse 443 sans certificat : avec
    # Let's Encrypt, la variable suit la lignée (`_lineage_exports`).
    if answers.turns_443 and answers.tls != "letsencrypt":
        variables["TURN_ALT_TLS_PORT"] = TURNS_ALT_PORT
    if answers.external_ip:
        variables["TURN_EXTERNAL_IP"] = answers.external_ip
    if adopt:
        variables["TURN_GARDER_CONFIG"] = "1"
    if turn_mode in TURN_MODES:
        variables["TURN_AUTH"] = turn_mode
    return variables


def _lineage_exports(answers, indent):
    """Lignes qui donnent à install_coturn.sh la lignée certbot comme
    certificat, et 443 avec `turns_443`."""
    names = ["TURN_CERT_FILE", "TURN_KEY_FILE"]
    lines = [
        f'TURN_CERT_FILE={_LIVE}"/fullchain.pem"',
        f'TURN_KEY_FILE={_LIVE}"/privkey.pem"',
    ]
    if answers.turns_443:
        lines.append(f"TURN_ALT_TLS_PORT={TURNS_ALT_PORT}")
        names.append("TURN_ALT_TLS_PORT")
    lines.append("export " + " ".join(names))
    return [indent + line for line in lines]


def _coturn_block(plan):
    """Premier passage d'install_coturn.sh. Avec Let's Encrypt, la lignée
    déjà sur le disque ($LE=1) lui sert de certificat ; sans elle, coturn
    démarre sans TLS (`no-tls`) et `_coturn_lineage_lines` le reprend après
    la délivrance."""
    answers = plan.answers
    lines = [
        "# coturn",
        _decode_to(
            _installer_payload("coturn"), '"$D/install_coturn.sh"', gunzip=True
        )
        + " || fail payload-coturn",
    ]
    raw = {}
    if answers.tls == "supplied":
        # L'installateur copie ces fichiers dans COTURN_TLS_DIR ; ici ils ne
        # vivent que dans le dossier de travail, effacé en sortie.
        lines += [
            _decode_to(_b64(answers.cert_pem), '"$D/turn.crt"')
            + " || fail cert-coturn",
            _decode_to(_b64(answers.key_pem), '"$D/turn.key"')
            + " || fail cert-coturn",
        ]
        raw = {
            "TURN_CERT_FILE": '"$D/turn.crt"',
            "TURN_KEY_FILE": '"$D/turn.key"',
        }
    # Sans TURN_CHECK_PASSWORD, install_coturn.sh tire le mot de passe du
    # compte de contrôle sur l'hôte et n'en garde que la clé, que la
    # vérification relit : aucun secret de ce compte ne part d'ici.
    lines += ["(", "  umask 022"] + _export(_coturn_variables(plan), raw)
    if answers.tls == "letsencrypt":
        lines.append('  if [ "$LE" = 1 ]; then')
        lines += _lineage_exports(answers, "    ")
        lines.append("  fi")
    lines += ['  exec bash "$D/install_coturn.sh"', ")", "RC_coturn=$?"]
    return lines


def _coturn_lineage_lines(plan):
    """Second passage d'install_coturn.sh, avec la lignée : quand coturn a
    démarré sans elle ($LE=0), ou quand certbot vient d'en délivrer une
    nouvelle que le crochet n'a pas pu lui remettre (`@@HOOK coturn-skip` :
    aucun état ne nomme encore coturn, ou l'état d'avant le dit sur un
    autre certificat). L'installateur écrit alors les lignes TLS et
    redémarre coturn."""
    lines = [
        "CB=$(mval CERTBOT)",
        'if [ "$LE" = 0 ] || { [ "${CB%% *}" = issued ]'
        " && grep -q '^@@HOOK coturn-skip' \"$D/run.m\"; }; then",
        "  (",
        "    umask 022",
    ]
    lines += ["  " + line for line in _export(_coturn_variables(plan))]
    lines += _lineage_exports(plan.answers, "    ")
    lines += [
        '    exec bash "$D/install_coturn.sh"',
        "  )",
        '  [ "$?" = 0 ] || fail coturn-tls',
        "fi",
    ]
    return lines


def _ntfy_block(plan):
    answers = plan.answers
    config = _host(NTFY_CONFIG)
    new = _host(NTFY_CONFIG + ".erplibre-new")
    lines = [
        "# ntfy",
        _decode_to(
            _installer_payload("ntfy"), '"$D/install_ntfy.sh"', gunzip=True
        )
        + " || fail payload-ntfy",
    ]
    variables = {
        "NTFY_PORT": ntfy_http_port(answers),
        "NTFY_BASE_URL": ntfy_base_url(answers),
        "NTFY_NON_INTERACTIVE": 1,
    }
    # Le compte « ntfy » doit traverser le dossier pour lire server.yml ;
    # sans lui, ntfy démarre sur ses valeurs par défaut, sans contrôle
    # d'accès. Créé ici en 0755 malgré l'umask 077 du script ; un dossier
    # déjà là garde ses droits, et ni dpkg ni pacman ne les changent.
    lines.append(
        f"[ -d {_host(os.path.dirname(NTFY_CONFIG))} ]"
        f" || install -d -m 0755 {_host(os.path.dirname(NTFY_CONFIG))}"
        " || fail ntfy-config"
    )
    if _ntfy_own_tls(answers):
        tls_dir = _host(NTFY_TLS_DIR)
        # Le groupe « ntfy » doit exister avant le paquet pour que la clé
        # lui soit lisible : le compte est créé comme install_ntfy.sh le
        # crée, et le paquet garde un compte déjà là.
        lines += [
            "id ntfy >/dev/null 2>&1 || useradd --system --no-create-home"
            " --shell /usr/sbin/nologin ntfy || fail ntfy-user",
            f"mkdir -p {tls_dir} && chown root:ntfy {tls_dir}"
            f" && chmod 0750 {tls_dir} || fail ntfy-tls",
            _place(_b64(answers.cert_pem), f"{NTFY_TLS_DIR}/ntfy.crt", "0644")
            + " || fail ntfy-tls",
            _place(
                _b64(answers.key_pem),
                f"{NTFY_TLS_DIR}/ntfy.key",
                "0640",
                group="ntfy",
            )
            + " || fail ntfy-tls",
        ]
        variables["NTFY_HTTPS_PORT"] = ntfy_port(answers)
        variables["NTFY_CERT_FILE"] = f"{NTFY_TLS_DIR}/ntfy.crt"
        variables["NTFY_KEY_FILE"] = f"{NTFY_TLS_DIR}/ntfy.key"
    else:
        # Comme install_coturn.sh : sans certificat, l'ancienne copie part,
        # et l'état ne consigne plus aucun fichier TLS pour ntfy. En
        # production, nginx tient le certificat : ntfy n'en a aucun.
        lines.append(
            f"rm -f {_host(NTFY_TLS_DIR + '/ntfy.crt')}"
            f" {_host(NTFY_TLS_DIR + '/ntfy.key')} || fail ntfy-tls"
        )
    # La configuration voulue est en place AVANT l'installateur : elle
    # déclare son contrôle d'accès, install_ntfy.sh la garde telle quelle.
    # Un fichier en place garde son propriétaire et ses droits.
    lines += [
        _decode_to(_b64(plan.configs["ntfy"]), new) + " || fail ntfy-config",
        f"if [ -f {config} ]; then",
        f"  chown --reference={config} {new}"
        f" && chmod --reference={config} {new} || fail ntfy-config",
        "else",
        f"  chmod 0644 {new} || fail ntfy-config",
        "fi",
        f"mv -f {new} {config} || fail ntfy-config",
        "{",
        "  (",
        "    umask 022",
    ]
    lines += ["  " + line for line in _export(variables)]
    # La sortie passe par `cap` : `@@ADMIN_PASSWORD` y devient
    # `@@ADMIN_ADDED`, que l'écriture de l'état lit (`admin_added`).
    lines += [
        '    exec bash "$D/install_ntfy.sh"',
        "  )",
        '  echo "$?" > "$D/rc.ntfy"',
        "} | cap",
        'RC_ntfy=$(cat "$D/rc.ntfy" 2>/dev/null)',
    ]
    return lines


def _state_write_lines(state):
    """Lignes `sh` qui écrivent `state` dans "$STATE" : `.new` en root
    0600 puis renommage, l'ancien état reste entier jusqu'au `mv`. Une
    fonction `fail` doit exister."""
    return [
        _decode_to(
            _b64(json.dumps(state, indent=2, sort_keys=True)), '"$STATE.new"'
        )
        + " || fail state",
        'chown root:root "$STATE.new"; chmod 0600 "$STATE.new"',
        'mv -f "$STATE.new" "$STATE" || fail state',
    ]


# Valeurs que le script prend aux marqueurs des installateurs : un paquet
# (`@@CERTBOT_PLUGIN_INSTALLED`), un chemin (`@@NGINX_BACKUP`), une unité
# de minuteur (`@@CERTBOT_TIMER`). Les formes sont celles que les lignes
# `sh` de `_run_field_lines` vérifient, au caractère près.
_PACKAGE = re.compile(r"^[a-z0-9.+-]+$")
_RUN_PATH = re.compile(r"^(/[A-Za-z0-9._-]+)+$")
_TIMER = re.compile(r"^[A-Za-z0-9@._-]*\.timer$")


def _run_path(value):
    return (
        isinstance(value, str)
        and bool(_RUN_PATH.match(value))
        and not {".", ".."} & set(value.split("/"))
    )


def _timer_record(value):
    return (
        isinstance(value, dict)
        and set(value) == {"unit", "added"}
        and isinstance(value["added"], bool)
        and isinstance(value["unit"], str)
        and bool(_TIMER.match(value["unit"]))
    )


def deploy_hook_text():
    """Le crochet de déploiement certbot que l'installation pose en
    HOOK_PATH, tel quel."""
    with open(HOOK_SOURCE, encoding="utf-8") as handle:
        return handle.read()


def _hook_payload():
    with open(HOOK_SOURCE, "rb") as handle:
        return _b64(gzip.compress(handle.read(), mtime=0))


def _uses_nginx(answers):
    return is_production(answers) and answers.nginx is not None


def _uses_certbot(answers):
    return is_production(answers) and answers.tls == "letsencrypt"


def _run_fields(plan):
    """[(nom, (fiche, clé))] des valeurs de l'état que le script prend à la
    sortie des installateurs de ce passage : nginx et certbot impriment ce
    qu'ils ont fait, le plan n'en a qu'une prévision."""
    fields = []
    if _uses_nginx(plan.answers):
        fields += [
            ("nginx_tool", ("nginx", "installed_by_tool")),
            ("nginx_layout", ("nginx", "layout")),
            ("nginx_site", ("nginx", "site")),
            ("nginx_link", ("nginx", "link")),
            ("nginx_include", ("nginx", "include")),
            ("nginx_backup", ("nginx", "backup")),
        ]
    if _uses_certbot(plan.answers):
        fields += [
            ("certbot_tool", ("certbot", "installed_by_tool")),
            ("certbot_plugins", ("certbot", "plugins_installed")),
            ("certbot_timer", ("certbot", "timer")),
        ]
    return fields


def _last_markers(output):
    """{NOM: valeur} de la dernière ligne `@@NOM valeur` de chaque nom."""
    return dict(marker_lines(output or ""))


def _run_values(defaults, last):
    """`defaults` ({nom: valeur de plan}) où chaque marqueur bien formé
    impose ce que l'installateur a fait ; la règle des lignes `sh` de
    `_run_field_lines`."""
    values = dict(defaults)
    if "nginx_tool" in values and last.get("NGINX_INSTALLED"):
        values["nginx_tool"] = True
    layout = last.get("NGINX_LAYOUT")
    if "nginx_layout" in values and layout in NGINX_LAYOUTS:
        values["nginx_layout"] = layout
        (
            values["nginx_site"],
            values["nginx_link"],
            values["nginx_include"],
        ) = _nginx_paths(layout)
    backup = last.get("NGINX_BACKUP")
    if "nginx_backup" in values and _run_path(backup):
        values["nginx_backup"] = backup
    if "certbot_tool" in values and last.get("CERTBOT_INSTALLED"):
        values["certbot_tool"] = True
    plugin = last.get("CERTBOT_PLUGIN_INSTALLED") or ""
    plugins = values.get("certbot_plugins")
    if (
        plugins is not None
        and _PACKAGE.match(plugin)
        and plugin not in plugins
    ):
        values["certbot_plugins"] = [*plugins, plugin]
    unit, sep, kind = (last.get("CERTBOT_TIMER") or "").rpartition(" ")
    if (
        "certbot_timer" in values
        and sep
        and _TIMER.match(unit)
        and kind in ("added", "present")
    ):
        values["certbot_timer"] = {"unit": unit, "added": kind == "added"}
    return values


def _run_field_lines(fields, defaults):
    """Lignes `sh` qui posent `J_<nom>` (texte JSON) pour chaque champ :
    la valeur de plan, remplacée par celle d'un marqueur bien formé de
    "$D/run.m" (voir `cap`). Les valeurs admises ne portent ni « | », ni
    « & », ni « \\ » : elles passent telles quelles dans `sed`."""
    names = {name for name, _key in fields}
    lines = [
        f"J_{name}={shlex.quote(json.dumps(defaults[name]))}"
        for name, _key in fields
    ]
    if "nginx_tool" in names:
        lines.append('[ -n "$(mval NGINX_INSTALLED)" ] && J_nginx_tool=true')
    if "nginx_layout" in names:
        lines.append('case "$(mval NGINX_LAYOUT)" in')
        for layout in NGINX_LAYOUTS:
            site, link, include = _nginx_paths(layout)
            sets = [
                f"J_nginx_layout={shlex.quote(json.dumps(layout))}",
                f"J_nginx_site={shlex.quote(json.dumps(site))}",
                f"J_nginx_link={shlex.quote(json.dumps(link))}",
                f"J_nginx_include={shlex.quote(json.dumps(include))}",
            ]
            lines.append(f"  {layout}) " + "; ".join(sets) + " ;;")
        lines.append("esac")
    if "nginx_backup" in names:
        lines.append(
            'V=$(mval NGINX_BACKUP); okpath "$V" && J_nginx_backup="\\"$V\\""'
        )
    if "certbot_tool" in names:
        lines.append(
            '[ -n "$(mval CERTBOT_INSTALLED)" ] && J_certbot_tool=true'
        )
    if "certbot_plugins" in names:
        lines += [
            "V=$(mval CERTBOT_PLUGIN_INSTALLED)",
            'case "$V" in',
            "  ''|*[!a-z0-9.+-]*) ;;",
            '  *) case "$J_certbot_plugins" in',
            '    *"\\"$V\\""*) ;;',
            '    \'[]\') J_certbot_plugins="[\\"$V\\"]" ;;',
            '    *) J_certbot_plugins="${J_certbot_plugins%]}, \\"$V\\"]" ;;',
            "  esac ;;",
            "esac",
        ]
    if "certbot_timer" in names:
        lines += [
            "V=$(mval CERTBOT_TIMER); U=${V% *}; K=${V##* }",
            'case "$U" in',
            "  *[!A-Za-z0-9@._-]*) ;;",
            '  *.timer) case "$K" in',
            '    added) J_certbot_timer="{\\"added\\": true,'
            ' \\"unit\\": \\"$U\\"}" ;;',
            '    present) J_certbot_timer="{\\"added\\": false,'
            ' \\"unit\\": \\"$U\\"}" ;;',
            "  esac ;;",
            "esac",
        ]
    return lines


def _template(state, fields):
    """`state` en JSON où chaque champ de `fields` devient
    "__RUN_<nom>__", que `sed` remplace sur l'hôte."""
    template = copy.deepcopy(state)
    for name, (record, key) in fields:
        template[record][key] = f"__RUN_{name}__"
    return json.dumps(template, indent=2, sort_keys=True)


def _admin_pending(state):
    """Vrai quand l'état peut encore gagner `admin_added` à ce passage : un
    ntfy adopté qui ne le porte pas (voir `mark_admin_added`)."""
    record = state["services"].get("ntfy")
    return (
        isinstance(record, dict)
        and bool(record.get("adopted"))
        and record.get("admin_added") is not True
    )


def installed_state(plan, stamp, output):
    """L'état que `install_script(plan, stamp)` a écrit, d'après `output`,
    sa sortie : `written_state`, avec `admin_added` quand l'installateur a
    créé le compte d'un ntfy adopté, et les fiches nginx et certbot telles
    que leurs installateurs les ont imprimées. C'est celui que l'appelant
    complète ensuite (pare-feu) : il ne perd rien de ce que le passage root
    a consigné."""
    state = mark_admin_added(written_state(plan, stamp), output)
    state = copy.deepcopy(state)
    fields = _run_fields(plan)
    defaults = {name: state[r][k] for name, (r, k) in fields}
    values = _run_values(defaults, _last_markers(output))
    for name, (record, key) in fields:
        state[record][key] = values[name]
    return state


def _state_from_run_lines(state, fields):
    """Lignes `sh` qui écrivent l'état en prenant aux marqueurs de ce
    passage ce que `_run_fields` désigne et `admin_added` : le même état
    qu'`installed_state` calcule de la sortie. Une seule écriture de
    "$STATE.new", comme `_state_write_lines`."""
    defaults = {name: state[r][k] for name, (r, k) in fields}
    lines = _run_field_lines(fields, defaults)
    tpl = '"$D/state.tpl"'
    plain = _decode_to(_b64(_template(state, fields)), tpl) + " || fail state"
    if _admin_pending(state):
        marked = copy.deepcopy(state)
        marked["services"]["ntfy"]["admin_added"] = True
        lines += [
            "if grep -qx '@@ADMIN_ADDED' \"$D/run.m\" 2>/dev/null; then",
            "  "
            + _decode_to(_b64(_template(marked, fields)), tpl)
            + " || fail state",
            "else",
            "  " + plain,
            "fi",
        ]
    else:
        lines.append(plain)
    edits = " ".join(
        f'-e "s|\\"__RUN_{name}__\\"|$J_{name}|"' for name, _key in fields
    )
    copy_tpl = f"sed {edits}" if edits else "cat"
    lines += [
        f'{copy_tpl} {tpl} > "$STATE.new" || fail state',
        'chown root:root "$STATE.new"; chmod 0600 "$STATE.new"',
        'mv -f "$STATE.new" "$STATE" || fail state',
    ]
    return lines


def _capture_lines():
    """Fonctions `sh` des étapes dont la sortie compte pour l'état.

    `cap` recopie sa sortie ligne à ligne et garde chaque ligne `@@` dans
    "$D/run.m", sauf `@@ADMIN_PASSWORD <mot de passe>` qui y devient
    `@@ADMIN_ADDED` : le mot de passe ne touche pas le disque. `mval
    <NOM>` imprime la valeur de la dernière ligne `@@NOM` gardée.
    `step_rc <étape>` lit le code de sortie déposé par l'étape (une
    étape coupée n'en dépose aucun). `okpath` admet un chemin absolu fait
    de [A-Za-z0-9._-], sans composant « . » ni « .. »."""
    keep = (
        "{ print; fflush() }"
        ' /^@@ADMIN_PASSWORD [^ ]/ { print "@@ADMIN_ADDED" >> f; next }'
        " /^@@[A-Z_]+/ { print >> f }"
    )
    return [
        f'cap() {{ awk -v f="$D/run.m" {shlex.quote(keep)}; }}',
        'mval() { sed -n "s/^@@$1 //p" "$D/run.m" 2>/dev/null | tail -n 1; }',
        'step_rc() { [ "$(cat "$D/rc.$1" 2>/dev/null)" = 0 ]; }',
        "okpath() {",
        '  case "$1" in /?*) ;; *) return 1 ;; esac',
        '  case "$1" in *[!A-Za-z0-9._/-]*|*//*|*/|*/./*|*/../*|*/.|*/..)'
        " return 1 ;; esac",
        "}",
    ]


def _rehold_lines():
    """Fonction `sh` `rehold` : install_certbot.sh a remis le fichier de
    renouvellement mis de côté (`@@CERTBOT_UNHELD`) et ce passage échoue
    ensuite, avant l'état : le fichier repart de côté, faute d'état qui
    consigne Let's Encrypt. Rien quand l'installateur l'a déjà fait
    (`@@CERTBOT_REHELD`)."""
    renewal = f'"$R"{shlex.quote(RENEWAL_FILE)}'
    return [
        "rehold() {",
        "  grep -q '^@@CERTBOT_UNHELD ' \"$D/run.m\" 2>/dev/null || return 0",
        "  grep -q '^@@CERTBOT_REHELD ' \"$D/run.m\" 2>/dev/null && return 0",
        f"  F={renewal}",
        '  if [ -f "$F" ] && [ ! -e "$F.erplibre-hold" ]'
        ' && mv -f "$F" "$F.erplibre-hold"; then',
        f'    echo "@@CERTBOT_REHELD {RENEWAL_FILE}"',
        "  fi",
        "}",
    ]


def _step(name, script, variables, raw=None, env_lines=()):
    """Étape lancée par `bash <script>` dans un sous-shell (umask 022),
    sortie par `cap`, arrêt du script (`fail <nom>`) sur un code non
    nul."""
    lines = ["{", "  (", "    umask 022"]
    # Un `export` sans nom imprimerait tout l'environnement.
    if variables or raw:
        lines += ["  " + line for line in _export(variables, raw)]
    lines += ["    " + line for line in env_lines]
    lines += [
        f"    exec bash {script}",
        "  )",
        f'  echo "$?" > "$D/rc.{name}"',
        "} | cap",
        f"step_rc {name} || fail {name}",
    ]
    return lines


def _nginx_variables(plan):
    """Variables d'install_nginx.sh, les mêmes aux deux étapes : les noms
    du certificat sur 80, ntfy sur 443, la lignée ou le certificat fourni,
    le dossier du défi quand certbot passe par nginx."""
    answers, record = plan.answers, plan.new_state["nginx"]
    ntfy = "ntfy" in answers.services
    if answers.tls == "letsencrypt":
        cert = f"{LINEAGE_DIR}/fullchain.pem"
        key = f"{LINEAGE_DIR}/privkey.pem"
    else:
        cert, key = SITE_CERT, SITE_KEY
    variables = {
        "NGINX_NAMES": " ".join(certificate_names(answers)),
        "NGINX_NTFY_NAME": ntfy_host(answers) if ntfy else "",
    }
    if ntfy:
        variables["NGINX_UPSTREAM_PORT"] = ntfy_http_port(answers)
    variables.update(
        {
            "NGINX_CERT_FILE": cert,
            "NGINX_KEY_FILE": key,
            "NGINX_ACME_ROOT": record["acme_root"] or "",
        }
    )
    if answers.nginx == "install" or record["installed_by_tool"]:
        variables["NGINX_INSTALL"] = 1
    # Sans cet accord, install_nginx.sh montre la ligne include et s'arrête :
    # il n'est donné que pour la ligne que le plan a annoncée
    # (`nginx_include`). install_nginx.sh garde la copie d'avant.
    if plan.nginx_include:
        variables["NGINX_ADOPT_INCLUDE"] = 1
    return variables


def _certbot_variables(plan):
    answers = plan.answers
    variables = {
        "CERTBOT_NAMES": " ".join(certificate_names(answers)),
        "CERTBOT_METHOD": CERTBOT_METHODS[answers.acme],
        "CERTBOT_EMAIL": answers.email,
    }
    if answers.acme == "http-nginx":
        variables["CERTBOT_WEBROOT"] = ACME_ROOT
    if answers.acme == "dns":
        variables["CERTBOT_DNS_PLUGIN"] = answers.dns_plugin
        variables["CERTBOT_DNS_CREDENTIALS"] = plan.new_state["certbot"][
            "dns_credentials"
        ]
    if plan.lineage_unchanged:
        variables["CERTBOT_SKIP_STAGING"] = 1
    if plan.certbot_force:
        variables["CERTBOT_FORCE_RENEWAL"] = 1
    return variables


def _dns_prune_lines(plan):
    """Après une délivrance réussie, les identifiants DNS d'une autre
    méthode ou d'un autre greffon quittent DNS_DIR : le fichier de
    renouvellement ne les nomme plus. Avant elle, ils restent, l'ancien
    fichier pouvant encore les lire."""
    keep = plan.new_state["certbot"]["dns_credentials"]
    test = f'[ "$f" = "$R"{shlex.quote(keep)} ] || ' if keep else ""
    return [
        f'for f in "$R"{shlex.quote(DNS_DIR)}/*.ini; do',
        '  [ -e "$f" ] || continue',
        f'  {test}rm -f "$f"',
        "done",
        f"rmdir {_host(DNS_DIR)} 2>/dev/null",
    ]


def _production_lines(plan):
    """Étapes de production après coturn et ntfy, chacune arrêtant le
    script avant l'état : certificat fourni posé pour nginx, nginx avant
    certbot (défi HTTP-01 par le webroot), identifiants DNS, certbot,
    crochet posé puis lancé sur la lignée, coturn repris sur la lignée,
    nginx complet (443 devant ntfy)."""
    answers = plan.answers
    nginx, certbot = _uses_nginx(answers), _uses_certbot(answers)
    lines = []
    if nginx:
        lines.append(
            _decode_to(
                _installer_payload("nginx"), '"$D/install_nginx.sh"', True
            )
            + " || fail payload-nginx"
        )
    if nginx and answers.tls == "supplied":
        lines += [
            f"mkdir -p {_host(COTURN_TLS_DIR)} || fail site-tls",
            _place(_b64(answers.cert_pem), SITE_CERT, "0600")
            + " || fail site-tls",
            _place(_b64(answers.key_pem), SITE_KEY, "0600")
            + " || fail site-tls",
        ]
    if certbot and answers.acme == "http-nginx":
        # Le défi passe par le port 80 de nginx. Sans lignée, l'étape acme
        # n'écrit que 80 ; avec elle, le site complet sert déjà le défi,
        # et 443 ne tombe pas le temps de certbot.
        lines += ["# nginx avant certbot", 'NS=acme; [ "$LE" = 1 ] && NS=full']
        lines += _step(
            "nginx-acme",
            '"$D/install_nginx.sh"',
            _nginx_variables(plan),
            {"NGINX_STAGE": '"$NS"'},
        )
    if certbot and answers.acme == "dns":
        path = plan.new_state["certbot"]["dns_credentials"]
        lines += [
            f"install -d -m 0700 {_host(DNS_DIR)} || fail dns",
            _place(_b64(answers.dns_credentials), path, "0600")
            + " || fail dns",
        ]
    if certbot:
        hook = _host(HOOK_PATH)
        lines += [
            "# certbot",
            _decode_to(
                _installer_payload("certbot"), '"$D/install_certbot.sh"', True
            )
            + " || fail payload-certbot",
        ]
        lines += _step(
            "certbot", '"$D/install_certbot.sh"', _certbot_variables(plan)
        )
        lines += _dns_prune_lines(plan)
        lines += [
            "# crochet de déploiement",
            f"install -d -m 0755 {_host(os.path.dirname(HOOK_PATH))}"
            " || fail hook",
            _place(_hook_payload(), HOOK_PATH, "0755", gunzip=True)
            + " || fail hook",
        ]
        lines += _step(
            "hook",
            hook,
            {},
            env_lines=(
                'ERPLIBRE_CALL_ROOT="$R"',
                f"RENEWED_LINEAGE={_LIVE}",
                "export ERPLIBRE_CALL_ROOT RENEWED_LINEAGE",
            ),
        )
        if "coturn" in answers.services:
            lines += _coturn_lineage_lines(plan)
    if nginx:
        lines.append("# nginx complet")
        lines += _step(
            "nginx-full",
            '"$D/install_nginx.sh"',
            {"NGINX_STAGE": "full", **_nginx_variables(plan)},
        )
    return lines


def install_script(plan, stamp, root=""):
    """Script `sh` d'installation, lancé en root sur l'hôte.

    Ordre : fiche de l'origine de chaque service, et de nginx et certbot en
    production, dans `PENDING_DIR` (gardée si elle existe déjà), copie
    `cp -p` de chaque configuration adoptée vers le chemin que consigne
    `written_state` (quand ce fichier existe déjà, seule une configuration
    qui en diffère est copiée, sous `<config>.bak-<stamp>`), installateurs
    décodés du base64 et lancés avec leurs variables (umask 022 : ce qu'ils
    écrivent doit rester lisible des comptes de service), en production
    les étapes de `_production_lines`, une ligne `@@ACTIVE <service>
    <état>` par service (et nginx), et SEULEMENT si chaque installateur a
    réussi et chaque unité est active : l'état écrit en `.new` (0600) puis
    renommé, et les fiches retirées. Dernière ligne : `@@SAVED yes`, ou
    `@@SAVED no` et un code non nul. Une coupure en cours de route laisse
    l'ancien état (ou aucun) et les fiches : la relance repart de là.

    L'état écrit est celui d'`installed_state` : `admin_added` et ce que
    nginx et certbot ont imprimé y sont consignés par ce passage même, sans
    attendre un second passage root.

    Production : un échec de coturn ou de ntfy arrête le script avant
    nginx et certbot. Avec Let's Encrypt, coturn démarre sans TLS tant que
    la lignée n'existe pas, puis la reprend après certbot ; un échec après
    certbot, ou une coupure (HUP, INT, TERM), remet de côté le fichier de
    renouvellement qu'il avait remis (`rehold`).

    Le mot de passe du compte de contrôle de coturn n'y figure pas :
    l'installateur le tire sur l'hôte. Le certificat, la clé et les
    identifiants DNS n'y figurent qu'en base64. `root` préfixe chaque
    chemin de l'hôte (tests).

    `plan.purge_secrets` : ces anciens secrets d'Odoo sont effacés de la
    base de coturn avant l'écriture de l'état ; un échec arrête le script
    sans écrire l'état, qui les nomme encore pour la relance.
    """
    if not _STAMP.match(stamp or ""):
        raise ValueError(f"stamp: {stamp!r}")
    answers = plan.answers
    services = [s for s in SERVICES if s in answers.services]
    state = written_state(plan, stamp)
    production = is_production(answers)
    certbot = _uses_certbot(answers)
    # nginx et certbot ont leur fiche quand ce plan s'en sert.
    extra = ["nginx"] if _uses_nginx(answers) else []
    extra += ["certbot"] if certbot else []
    rehold = " rehold;" if certbot else ""
    # Les fiches nginx et certbot que ce plan n'utilise pas sont consignées
    # dans l'état (`_carry_fiches`) : elles partent avec lui.
    carried = [
        name
        for name in ("nginx", "certbot")
        if name not in extra and isinstance(state.get(name), dict)
    ]
    lines = [
        "set -u",
        f"R={shlex.quote(root)}",
        f'CALL="$R"{shlex.quote(CALL_DIR)}',
        f'STATE="$R"{shlex.quote(STATE_PATH)}',
        f'PENDING="$R"{shlex.quote(PENDING_DIR)}',
        "umask 077",
        f'fail() {{ echo "@@FAILED $1";{rehold} echo "@@SAVED no"; exit 1; }}',
        "D=$(mktemp -d) || fail workdir",
        "trap 'rm -rf \"$D\"' EXIT",
        # Une coupure laisse le même trou qu'un échec ; le piège EXIT, qui
        # retire $D, passe après `rehold` qui y lit run.m.
        f"trap '{'rehold; ' if certbot else ''}exit 129' HUP INT TERM",
        *_capture_lines(),
        *(_rehold_lines() if certbot else []),
        # Le dossier reste traversable : coturn y lit son certificat.
        'mkdir -p "$PENDING" && chmod 0755 "$CALL" && chmod 0700 "$PENDING"'
        " || fail pending",
    ]
    origins = {}
    for svc in services:
        record = state["services"][svc]
        origins[svc] = {
            k: record[k]
            for k in (
                "installed_by_tool",
                "adopted",
                "backup",
                "config",
                "was_active",
                "was_enabled",
            )
        }
    for name in extra:
        keys = (
            "installed_by_tool",
            "plugins_installed",
            "was_active",
            "was_enabled",
        )
        origins[name] = {k: state[name][k] for k in keys if k in state[name]}
    for name, origin in origins.items():
        pending = f'"$PENDING/{name}.json"'
        lines += [
            f"if [ ! -e {pending} ]; then",
            "  "
            + _decode_to(_b64(json.dumps(origin)), f'"$PENDING/{name}.new"')
            + f' && mv -f "$PENDING/{name}.new" {pending} || fail pending',
            "fi",
        ]
    for svc in services:
        record = state["services"][svc]
        if svc in plan.adopt:
            backup = record.get("backup")
            if not _is_backup_of(record["config"], backup):
                backup = f"{record['config']}.bak-{stamp}"
            # La copie consignée existe déjà quand un passage coupé l'a faite
            # : elle garde l'original. Une configuration étrangère qui en
            # diffère (refaite à la main depuis) est copiée à part, sous le
            # tampon de ce passage, plutôt que perdue.
            config, extra_copy = (
                record["config"],
                f"{record['config']}.bak-{stamp}",
            )
            lines += [
                f"if [ ! -e {_host(backup)} ]; then",
                f"  cp -p {_host(config)} {_host(backup)} || fail backup-{svc}",
                f"elif ! cmp -s {_host(config)} {_host(backup)}; then",
                f"  cp -p {_host(config)} {_host(extra_copy)}"
                f" || fail backup-{svc}",
                "fi",
            ]
            # Une configuration de coturn sans paquet (installed_by_tool) :
            # pacman refuse un paquet dont un fichier existe déjà sans
            # propriétaire. Copiée, elle quitte sa place ; l'installateur
            # pose celle du paquet puis la remplace (TURN_GARDER_CONFIG=1).
            if svc == "coturn" and record["installed_by_tool"]:
                lines.append(f"rm -f {_host(config)} || fail backup-{svc}")
    if certbot:
        # $LE : la lignée est déjà sur le disque (relance, réinstallation
        # après une désinstallation qui a gardé le certificat).
        lines += [
            "LE=0",
            f'[ -f {_LIVE}"/fullchain.pem" ] && [ -f {_LIVE}"/privkey.pem" ]'
            " && LE=1",
        ]
    for svc in services:
        lines += _coturn_block(plan) if svc == "coturn" else _ntfy_block(plan)
        if production:
            lines.append(f'[ "$RC_{svc}" = 0 ] || fail {svc}')
    if production:
        lines += _production_lines(plan)
    lines += _purge_lines(plan, state)
    units = [(svc, state["services"][svc]["unit"]) for svc in services]
    if _uses_nginx(answers):
        units.append(("nginx", "nginx"))
    lines.append("OK=1")
    for name, unit in units:
        if name in services:
            lines.append(f'[ "$RC_{name}" = 0 ] || OK=0')
        lines += [
            f"A=$(systemctl is-active {shlex.quote(unit)} 2>/dev/null)",
            f'echo "@@ACTIVE {name} ${{A:-unknown}}"',
            '[ "$A" = active ] || OK=0',
        ]
    fields = _run_fields(plan)
    if fields or _admin_pending(state):
        write = _state_from_run_lines(state, fields)
    else:
        write = _state_write_lines(state)
    lines.append('if [ "$OK" = 1 ]; then')
    lines += ["  " + line for line in write]
    if certbot:
        # L'état écrit consigne Let's Encrypt : une coupure ne remet plus
        # le fichier de renouvellement de côté.
        lines.append("  trap 'exit 129' HUP INT TERM")
    lines += [
        *[f'  rm -f "$PENDING/{name}.json"' for name in [*origins, *carried]],
        '  echo "@@SAVED yes"',
        "else",
        *(["  rehold"] if certbot else []),
        '  echo "@@SAVED no"',
        "  exit 1",
        "fi",
        "",
    ]
    return "\n".join(lines)


# --- Pare-feu ---------------------------------------------------------------

# Port de ssh : aucune règle ne le couvre, ni à l'ouverture ni au retrait ;
# retirer « 22/tcp » de ufw enlèverait la règle de l'administrateur.
SSH_PORT = 22
FIREWALL_COMMENT = "erplibre-call"
NFT_PERSIST_DIR = "/etc/nftables.d"
NFT_PERSIST_FILE = "/etc/nftables.d/erplibre-call.nft"
NFT_CONF = "/etc/nftables.conf"
FIREWALL_ACTIONS = ("allow", "delete")

_RULE_PORT = re.compile(r"^([0-9]{1,5})(?::([0-9]{1,5}))?$")
_NFT_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
# Inclusion qui charge NFT_PERSIST_FILE au démarrage : « * » ou « *.nft ».
_NFT_INCLUDE_ERE = (
    '^[[:space:]]*include[[:space:]]+"/etc/nftables\\.d/\\*(\\.nft)?"'
)
# `nft -a list ruleset` : chaque règle finit par « # handle <n> ». Imprime
# « famille table chaîne handle » des règles qui contiennent `m` (protocole,
# port, espace) et `k` (le commentaire de l'outil pour ce service).
_NFT_HANDLES_AWK = (
    "/^table / { f = $2; t = $3 }"
    " /^[ \\t]*chain / { c = $2 }"
    " index($0, m) && index($0, k) && match($0, /# handle [0-9]+$/)"
    " { print f, t, c, substr($0, RSTART + 9) }"
)


@dataclasses.dataclass(frozen=True)
class Rule:
    """Une ouverture : `proto` « tcp » ou « udp », `port` « 3478 » ou une
    plage « 49152:49252 », `service` celui qui l'écoute."""

    proto: str
    port: str
    service: str


def _port_bounds(port):
    """(bas, haut) de « 3478 » ou « 49152:49252 », None hors format."""
    match = _RULE_PORT.match(port if isinstance(port, str) else "")
    if not match:
        return None
    low = int(match.group(1))
    high = int(match.group(2) or low)
    if not 1 <= low <= high <= 65535:
        return None
    return low, high


def _covers_ssh(port):
    low, high = _port_bounds(port)
    return low <= SSH_PORT <= high


def _check_rule(rule):
    """ValueError pour une règle hors format ou qui couvre le port de ssh :
    les règles relues de l'état viennent de l'hôte et finissent dans un
    script lancé en root."""
    if (
        not isinstance(rule, Rule)
        or rule.proto not in ("tcp", "udp")
        or rule.service not in FIREWALL_LABELS
        or _port_bounds(rule.port) is None
    ):
        raise ValueError(f"firewall rule: {rule!r}")
    if _covers_ssh(rule.port):
        raise ValueError(f"firewall rule covers ssh: {rule!r}")


def _span(low, high):
    return str(low) if low == high else f"{low}:{high}"


def firewall_before_install(answers):
    """Vrai quand le défi HTTP-01 de Let's Encrypt (par nginx ou par certbot
    seul) a lieu pendant le script d'installation : le port 80 doit déjà
    passer le pare-feu, sinon l'essai à blanc échoue et aucun état ne
    s'écrit, à chaque passage."""
    return _uses_certbot(answers) and answers.acme in (
        "http-nginx",
        "http-standalone",
    )


def firewall_rules(answers):
    """Les ouvertures des services choisis : en production, nginx en tcp
    sur 80 (et 443 devant ntfy), certbot autonome sur 80 ; coturn TURN en
    udp et tcp, TURNS en tcp avec un certificat (sur `coturn_tls_port`),
    la plage des relais de `relay_range` en udp ; ntfy son port en tcp en
    développement. Son port http interne, sur 127.0.0.1 avec un
    certificat ou en production, n'est pas ouvert. Refusal
    `call_infra_bad_value` pour une règle qui couvrirait le port de
    ssh."""
    rules = [Rule("tcp", str(p), "nginx") for p in _nginx_ports(answers)]
    rules += [Rule("tcp", str(p), "certbot") for p in _certbot_ports(answers)]
    if "coturn" in answers.services:
        turn = str(answers.turn_port)
        rules += [Rule("udp", turn, "coturn"), Rule("tcp", turn, "coturn")]
        if has_tls(answers):
            rules.append(Rule("tcp", str(coturn_tls_port(answers)), "coturn"))
        rules.append(Rule("udp", _span(*relay_range(answers)), "coturn"))
    if "ntfy" in answers.services and not is_production(answers):
        rules.append(Rule("tcp", str(ntfy_port(answers)), "ntfy"))
    for rule in rules:
        bounds = _port_bounds(rule.port)
        if bounds is None or bounds[0] <= SSH_PORT <= bounds[1]:
            raise Refusal(
                "call_infra_bad_value",
                name="port",
                value=f"{rule.port}/{rule.proto}",
            )
    return tuple(rules)


def rules_from_state(state):
    """Les règles consignées dans `state["firewall"]`, celles hors format
    ou sur le port de ssh écartées."""
    firewall = state.get("firewall") if isinstance(state, dict) else None
    entries = firewall.get("rules") if isinstance(firewall, dict) else None
    rules = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, list) or len(entry) != 3:
            continue
        rule = Rule(*entry)
        try:
            _check_rule(rule)
        except ValueError:
            continue
        if rule not in rules:
            rules.append(rule)
    return tuple(rules)


def _comment(rule):
    return f"{FIREWALL_COMMENT} {rule.service}"


def _ufw_spec(rule):
    return f"{rule.port}/{rule.proto}"


def _nft_match(rule):
    """« udp dport 3478 » : nft écrit une plage avec « - »."""
    return f"{rule.proto} dport {rule.port.replace(':', '-')}"


def _nft_rule(rule):
    return f'{_nft_match(rule)} accept comment "{_comment(rule)}"'


def _valid_chain(chain):
    return (
        isinstance(chain, tuple)
        and len(chain) == 3
        and chain[0] in ("ip", "ip6", "inet")
        and all(_NFT_NAME.match(part) for part in chain[1:])
    )


def _check_kind(kind, rules, action="allow"):
    if kind not in FIREWALLS:
        raise ValueError(f"firewall kind: {kind!r}")
    if action not in FIREWALL_ACTIONS:
        raise ValueError(f"firewall action: {action!r}")
    rules = tuple(rules)
    for rule in rules:
        _check_rule(rule)
    return rules


def firewall_preview(kind, rules, chain=None):
    """Les commandes montrées avant le oui, telles que le script les passe.

    ufw : `ufw allow <port>/<proto> comment 'erplibre-call <service>'`.
    nftables : `nft insert rule <famille> <table> <chaîne> ...` dans
    `chain`, la seule chaîne input en drop (`HostFacts.nft_chains`) ; sans
    elle, liste vide, comme pour « none » et « unknown » : rien ne sera
    ajouté.
    """
    rules = _check_kind(kind, rules)
    if kind == "ufw":
        return [
            f"ufw allow {_ufw_spec(r)} comment '{_comment(r)}'" for r in rules
        ]
    if kind == "nftables" and chain is not None and _valid_chain(chain):
        target = " ".join(chain)
        return [f"nft insert rule {target} {_nft_rule(r)}" for r in rules]
    return []


def firewall_notes(kind):
    """Clés i18n à montrer avec l'aperçu. Le pare-feu du fournisseur
    infonuagique, que la sonde ne voit pas, est rappelé pour tout `kind`."""
    if kind not in FIREWALLS:
        raise ValueError(f"firewall kind: {kind!r}")
    notes = []
    if kind == "none":
        notes.append("call_infra_firewall_none")
    elif kind == "unknown":
        notes.append("call_infra_firewall_unknown")
    notes.append("call_infra_cloud_firewall")
    return notes


def _marker(name, rule):
    return f"@@FIREWALL_{name} {rule.proto} {rule.port} {rule.service}"


def _rule_words(rule):
    return f"{rule.proto} {rule.port} {rule.service}"


def _record_lines(kind):
    """Fonction `rec <ADDED|KEPT> <proto> <port> <service>` d'un script
    d'ajout : imprime la ligne `@@FIREWALL_*` et inscrit la règle dans la
    fiche `PENDING_DIR/firewall`, dans le passage root même qui la pose.
    Un état écrit plus tard (`state_write_script`) la consigne et vide la
    fiche ; s'il échoue, la sonde suivante la relit. Une fiche qui ne
    s'écrit pas fait échouer le script."""
    return [
        f'FWP="$R"{shlex.quote(PENDING_DIR)}/firewall',
        'rec() { echo "@@FIREWALL_$1 $2 $3 $4"; mkdir -p "${FWP%/*}"'
        f' && printf \'%s %s %s %s\\n\' {kind} "$2" "$3" "$4"'
        ' >> "$FWP" || RC=1; }',
    ]


def _script_head(root):
    return [
        "set -u",
        _C_LOCALE,
        f"R={shlex.quote(root)}",
        "umask 077",
        "RC=0",
        'D=$(mktemp -d) || { echo "@@FIREWALL_FAILED workdir"; echo "@@END";'
        " exit 1; }",
        "trap 'rm -rf \"$D\"' EXIT",
        "trap 'exit 129' HUP INT TERM",
    ]


def _script_tail():
    return ['echo "@@END"', 'exit "$RC"', ""]


def _ufw_script(rules, action, root=""):
    """ufw : la règle de l'outil est la ligne exacte `ufw allow <spec>
    comment 'erplibre-call <service>'` de `ufw show added`. Toute autre
    ligne qui porte « <spec> » appartient à l'administrateur, quelle que
    soit son action (deny, reject, limit), son journal ou son sens : elle
    n'est ni ajoutée ni consignée (FOREIGN), et donc jamais retirée. ufw
    remplace une règle qui ne diffère de la nôtre que par l'action ou le
    journal et répond « Rule updated » : cette réponse est FOREIGN aussi.
    ufw garde ses règles d'un démarrage à l'autre."""
    show = (
        'ufw show added > "$D/added" 2>/dev/null'
        ' || { echo "@@FIREWALL_FAILED show"; echo "@@END"; exit 1; }'
    )
    if action == "allow":
        lines = _script_head(root) + _record_lines("ufw") + [show]
    else:
        lines = _script_head(root) + _when_present("ufw", show, '"$D/added"')
    for rule in rules:
        spec = _ufw_spec(rule)
        mine = shlex.quote(f"ufw allow {spec} comment {_comment(rule)!r}")
        other = shlex.quote(f" {spec}( |$)")
        lines.append(
            f'if grep -qxF {mine} "$D/added"; then L=mine;'
            f' elif grep -qE {other} "$D/added"; then L=other; else L=; fi'
        )
        if action == "allow":
            command = f"ufw allow {spec} comment {shlex.quote(_comment(rule))}"
            lines += [
                'case "$L" in',
                f"  mine) rec KEPT {_rule_words(rule)} ;;",
                f'  other) echo "{_marker("FOREIGN", rule)}" ;;',
                f"  *) if O=$({command} 2>&1); then",
                '    case "$O" in',
                f'      *Skipping*|*updated*) echo "{_marker("FOREIGN", rule)}"'
                " ;;",
                f"      *) rec ADDED {_rule_words(rule)} ;;",
                "    esac",
                f'  else echo "{_marker("FAILED", rule)}"; RC=1; fi ;;',
                "esac",
            ]
        else:
            lines += [
                'case "$L" in',
                "  mine)",
                f"    if ufw delete allow {spec} </dev/null >/dev/null; then"
                f' echo "{_marker("REMOVED", rule)}";',
                f'    else echo "{_marker("FAILED", rule)}"; RC=1; fi ;;',
                f'  other) echo "{_marker("FOREIGN", rule)}" ;;',
                f'  *) echo "{_marker("ABSENT", rule)}" ;;',
                "esac",
            ]
    if action == "allow":
        lines.append('[ "$RC" = 0 ] && echo "@@FIREWALL_PERSISTED yes"')
    return "\n".join(lines + _script_tail())


def _when_present(command, listing, target):
    """Lignes `sh` du retrait : `listing` remplit `target` quand `command`
    existe ; sans elle, `target` reste vide et chaque règle se dit ABSENT.
    Un pare-feu désinstallé depuis ne porte plus aucune règle de l'outil,
    et le retrait se termine au lieu d'échouer à chaque relance."""
    return [
        f"if command -v {command} >/dev/null 2>&1; then",
        f"  {listing}",
        f"else : > {target}; fi",
    ]


def _nft_find(rule):
    """Commande `sh` qui imprime « famille table chaîne handle » de chaque
    règle de l'outil pour `rule` dans "$D/handles"."""
    return (
        f"awk -v m={shlex.quote(_nft_match(rule) + ' ')}"
        f" -v k={shlex.quote(f'comment {chr(34)}{_comment(rule)}{chr(34)}')}"
        f' {shlex.quote(_NFT_HANDLES_AWK)} "$D/handles"'
    )


def _nft_allow(rules):
    """nftables : les règles sont insérées en tête de LA chaîne de base
    input en drop, d'une seule transaction (`nft -f`) ; zéro ou plusieurs
    chaînes, ou un nom inattendu : `@@FIREWALL_MANUAL <n>` et rien ne
    change. Une règle de l'outil déjà présente est gardée (KEPT).

    Persistance : seulement quand NFT_CONF inclut NFT_PERSIST_DIR ; le
    fichier reçoit les mêmes lignes, puis `nft -c -f NFT_CONF` vérifie que
    la configuration se charge encore. Sinon, ou si la vérification
    échoue (fichier remis comme avant) : `@@FIREWALL_RUNTIME_ONLY`."""
    conf, persist = _host(NFT_CONF), _host(NFT_PERSIST_FILE)
    lines = [
        'nft list ruleset > "$D/ruleset" 2>/dev/null'
        ' || { echo "@@FIREWALL_FAILED list"; echo "@@END"; exit 1; }',
        f'awk {shlex.quote(_NFT_CHAINS_AWK)} "$D/ruleset" > "$D/chains"',
        "N=$(awk 'END { print NR }' \"$D/chains\")",
        "USABLE=0",
        'if [ "$N" = 1 ]; then',
        '  read -r F T C X < "$D/chains"',
        "  USABLE=1",
        '  [ -n "$X" ] && USABLE=0',
        '  case "$F" in ip|ip6|inet) ;; *) USABLE=0 ;; esac',
        '  case "$T" in ""|*[!A-Za-z0-9_.-]*) USABLE=0 ;; esac',
        '  case "$C" in ""|*[!A-Za-z0-9_.-]*) USABLE=0 ;; esac',
        "fi",
        'if [ "$USABLE" != 1 ]; then',
        '  echo "@@FIREWALL_MANUAL $N"; echo "@@END"; exit 0',
        "fi",
        'echo "@@FIREWALL_CHAIN $F $T $C"',
        'nft -a list ruleset > "$D/handles" 2>/dev/null'
        ' || { echo "@@FIREWALL_FAILED list"; echo "@@END"; exit 1; }',
        ': > "$D/add.nft"; : > "$D/added"; : > "$D/lines"',
    ]
    for rule in rules:
        body = shlex.quote(_nft_rule(rule))
        lines += [
            f'printf "insert rule %s %s %s %s\\n" "$F" "$T" "$C" {body}'
            ' >> "$D/lines"',
            f'if [ -n "$({_nft_find(rule)})" ]; then',
            f"  rec KEPT {_rule_words(rule)}",
            "else",
            f'  printf "insert rule %s %s %s %s\\n" "$F" "$T" "$C" {body}'
            ' >> "$D/add.nft"',
            f"  echo {shlex.quote(_marker('ADDED', rule)[2:])}"
            ' >> "$D/added"',
            "fi",
        ]
    lines += [
        'if [ -s "$D/add.nft" ]; then',
        '  if nft -f "$D/add.nft"; then',
        '    while read -r M P Q S; do rec "${M#FIREWALL_}" "$P" "$Q" "$S";'
        ' done < "$D/added"',
        "  else",
        "    sed 's/^/@@/; s/@@FIREWALL_ADDED/@@FIREWALL_FAILED/'"
        ' "$D/added"',
        "    RC=1",
        "  fi",
        "fi",
        'if [ "$RC" = 0 ]; then',
        f"  if [ -f {conf} ] && grep -Eq {shlex.quote(_NFT_INCLUDE_ERE)}"
        f" {conf}; then",
        f'    if [ -f {persist} ]; then cp {persist} "$D/persist";'
        f' cp -p {persist} "$D/previous";',
        f'    else echo {shlex.quote(MARKER)} > "$D/persist"; fi',
        "    while IFS= read -r LINE; do",
        '      grep -qxF "$LINE" "$D/persist"'
        ' || printf "%s\\n" "$LINE" >> "$D/persist"',
        '    done < "$D/lines"',
        f"    if mkdir -p {_host(NFT_PERSIST_DIR)}"
        f' && cp "$D/persist" {_host(NFT_PERSIST_FILE + ".new")}'
        f" && chmod 0644 {_host(NFT_PERSIST_FILE + '.new')}"
        f" && mv -f {_host(NFT_PERSIST_FILE + '.new')} {persist}"
        f" && nft -c -f {conf} >/dev/null 2>&1; then",
        '      echo "@@FIREWALL_PERSISTED yes"',
        "    else",
        f"      rm -f {_host(NFT_PERSIST_FILE + '.new')}",
        '      if [ -f "$D/previous" ]; then'
        f' cp -p "$D/previous" {persist}; else rm -f {persist}; fi',
        '      echo "@@FIREWALL_RUNTIME_ONLY check"',
        "    fi",
        "  else",
        '    echo "@@FIREWALL_RUNTIME_ONLY"',
        "  fi",
        "fi",
    ]
    return lines


def _nft_delete(rules):
    """nftables : chaque règle de l'outil est retrouvée par son commentaire
    dans tout le jeu (`nft -a list ruleset`), puis retirée par son handle ;
    une règle sans ce commentaire n'est jamais touchée. Ses lignes partent
    aussi de NFT_PERSIST_FILE, effacé quand il n'en reste aucune, que nft
    soit encore là ou non."""
    persist = _host(NFT_PERSIST_FILE)
    listing = (
        'nft -a list ruleset > "$D/handles" 2>/dev/null'
        ' || { echo "@@FIREWALL_FAILED list"; echo "@@END"; exit 1; }'
    )
    lines = _when_present("nft", listing, '"$D/handles"') + ["set --"]
    for rule in rules:
        lines += [
            f'{_nft_find(rule)} > "$D/found"',
            'if [ ! -s "$D/found" ]; then',
            f'  echo "{_marker("ABSENT", rule)}"',
            "else",
            "  GONE=1",
            "  while read -r F T C H; do",
            '    case "$F" in ip|ip6|inet) ;; *) GONE=0; continue ;; esac',
            '    case "$T" in ""|*[!A-Za-z0-9_.-]*) GONE=0; continue ;; esac',
            '    case "$C" in ""|*[!A-Za-z0-9_.-]*) GONE=0; continue ;; esac',
            '    case "$H" in ""|*[!0-9]*) GONE=0; continue ;; esac',
            '    nft delete rule "$F" "$T" "$C" handle "$H" || GONE=0',
            '  done < "$D/found"',
            '  if [ "$GONE" = 1 ]; then',
            f'    echo "{_marker("REMOVED", rule)}"',
            "  else",
            f'    echo "{_marker("FAILED", rule)}"; RC=1',
            "  fi",
            "fi",
            f'set -- "$@" -e {shlex.quote(_nft_rule(rule))}',
        ]
    lines += [
        f"if [ -f {persist} ]; then",
        f'  grep -vF "$@" {persist} > "$D/persist"',
        "  if grep -q '^insert rule' \"$D/persist\"; then",
        f'    chmod 0644 "$D/persist" && cp "$D/persist"'
        f" {_host(NFT_PERSIST_FILE + '.new')}"
        f" && mv -f {_host(NFT_PERSIST_FILE + '.new')} {persist} || RC=1",
        "  else",
        f"    rm -f {persist} || RC=1",
        "  fi",
        "fi",
    ]
    return lines


def firewall_script(kind, rules, action, root=""):
    """Script `sh`, lancé en root, qui ajoute (`allow`) ou retire
    (`delete`) `rules` du pare-feu actif ; "" pour « none » et « unknown »
    ou sans règle.

    Il n'active jamais un pare-feu, ne change aucune politique, ne vide
    rien et ne touche aucune règle qu'il n'a pas posée : chacune porte le
    commentaire « erplibre-call <service> ». Une ligne par règle :
    `@@FIREWALL_ADDED|KEPT|FOREIGN|REMOVED|ABSENT|FAILED <proto> <port>
    <service>` ; puis `@@FIREWALL_PERSISTED yes` ou
    `@@FIREWALL_RUNTIME_ONLY`, `@@FIREWALL_MANUAL <n>` quand nftables n'a
    pas exactement une chaîne input en drop, et `@@END`. Code non nul
    après un échec. `firewall_record` lit cette sortie. Un ajout inscrit
    aussi chaque règle ADDED ou KEPT dans la fiche `PENDING_DIR/firewall`
    (`_record_lines`). `root` préfixe les fichiers de l'hôte (tests).
    """
    rules = _check_kind(kind, rules, action)
    if kind in ("none", "unknown") or not rules:
        return ""
    if kind == "ufw":
        return _ufw_script(rules, action, root)
    if action == "allow":
        body = _record_lines("nftables") + _nft_allow(rules)
    else:
        body = _nft_delete(rules)
    return "\n".join(_script_head(root) + body + _script_tail())


def firewall_record(kind, output, previous=None, pending=()):
    """`state["firewall"]` après un passage de `firewall_script` :
    `{"kind", "rules": [[proto, port, service], ...], "persisted"}`.

    Partant des règles de `previous` (du même `kind`) et de celles de
    `pending` (`HostFacts.firewall_pending`) du même `kind`, les ADDED et KEPT
    s'ajoutent, les REMOVED et ABSENT partent ; FOREIGN et FAILED ne sont
    pas consignées : l'outil ne retirera que ce qu'il a posé. `persisted`
    suit `@@FIREWALL_PERSISTED` / `@@FIREWALL_RUNTIME_ONLY`, sinon reste
    celui de `previous`.
    """
    if kind not in FIREWALLS:
        raise ValueError(f"firewall kind: {kind!r}")
    same = isinstance(previous, dict) and previous.get("kind") == kind
    rules = set(rules_from_state({"firewall": previous}) if same else ())
    rules |= {found for found_kind, found in pending if found_kind == kind}
    persisted = bool(same and previous.get("persisted"))
    for name, value in marker_lines(output or ""):
        if name == "FIREWALL_PERSISTED":
            persisted = True
        elif name == "FIREWALL_RUNTIME_ONLY":
            persisted = False
        elif name.startswith("FIREWALL_"):
            parts = value.split()
            if len(parts) != 3:
                continue
            rule = Rule(*parts)
            try:
                _check_rule(rule)
            except ValueError:
                continue
            if name in ("FIREWALL_ADDED", "FIREWALL_KEPT"):
                rules.add(rule)
            elif name in ("FIREWALL_REMOVED", "FIREWALL_ABSENT"):
                rules.discard(rule)
    ordered = sorted(rules, key=lambda r: (r.proto, r.port, r.service))
    return {
        "kind": kind,
        "rules": [[r.proto, r.port, r.service] for r in ordered],
        "persisted": persisted if ordered else False,
    }


def merge_pending_firewall(state, pending):
    """Copie de `state` dont « firewall » porte aussi les règles de
    `pending` : la désinstallation retire ce qu'un passage a posé sans
    pouvoir le consigner. Le type est celui de l'état, sinon celui de la
    fiche. `state` tel quel quand il n'est pas un dict ou sans fiche."""
    if not isinstance(state, dict) or not pending:
        return state
    record = state.get("firewall")
    kind = record.get("kind") if isinstance(record, dict) else None
    if kind not in ("ufw", "nftables"):
        kind = pending[0][0]
    return with_firewall(state, firewall_record(kind, "", record, pending))


def _ufw_foreign(rule, added):
    """Vrai quand une ligne de `added` (`ufw show added`) porte la règle
    sans être celle de l'outil : le même test que `_ufw_script`, qui la dit
    FOREIGN et ne la consigne jamais."""
    spec = _ufw_spec(rule)
    mine = f"ufw allow {spec} comment {_comment(rule)!r}"
    other = re.compile(rf" {re.escape(spec)}( |$)")
    return mine not in added and any(other.search(line) for line in added)


def firewall_missing(facts, answers):
    """Vrai quand une relance doit encore proposer le pare-feu : une règle
    posée attend d'être consignée, ou une règle voulue que le pare-feu actif
    sait recevoir n'est pas consignée pour lui. Sous ufw, un port qu'une
    règle de l'administrateur couvre déjà (FOREIGN) ne manque pas : elle
    reste non consignée, et la désinstallation n'y touche pas."""
    if facts.firewall_pending:
        return True
    rules = firewall_rules(answers)
    chain = facts.nft_chains[0] if len(facts.nft_chains) == 1 else None
    if not firewall_preview(facts.firewall, rules, chain):
        return False
    state = facts.state if isinstance(facts.state, dict) else {}
    record = state.get("firewall")
    same = isinstance(record, dict) and record.get("kind") == facts.firewall
    recorded = set(rules_from_state(state)) if same else set()
    foreign = facts.ufw_added if facts.firewall == "ufw" else ()
    return any(
        rule not in recorded and not _ufw_foreign(rule, foreign)
        for rule in rules
    )


def with_firewall(state, record):
    """Copie de `state` qui porte `record` sous « firewall »."""
    updated = copy.deepcopy(state) if isinstance(state, dict) else {}
    updated["firewall"] = copy.deepcopy(record)
    return updated


def state_write_script(state, root=""):
    """Script `sh`, lancé en root, qui remplace l'état de l'hôte par
    `state` (après `with_firewall`) : `.new` en 0600 puis renommage, puis
    la fiche `PENDING_DIR/firewall` retirée : l'appelant y a pris les
    règles (`firewall_record`, argument `pending`). Dernière ligne
    `@@SAVED yes`, ou `@@FAILED state` et `@@SAVED no`."""
    lines = [
        "set -u",
        f"R={shlex.quote(root)}",
        f'STATE="$R"{shlex.quote(STATE_PATH)}',
        "umask 077",
        'fail() { echo "@@FAILED $1"; echo "@@SAVED no"; exit 1; }',
        f'mkdir -p "$R"{shlex.quote(CALL_DIR)} || fail state',
        *_state_write_lines(state),
        f'rm -f "$R"{shlex.quote(PENDING_DIR)}/firewall',
        'echo "@@SAVED yes"',
        "",
    ]
    return "\n".join(lines)


# --- Serveurs Odoo ----------------------------------------------------------

# Durée de vie par défaut des identifiants temporaires, en heures : celle du
# paramètre `erplibre_turn.ttl_hours` du module quand il est absent.
DEFAULT_TTL_HOURS = 24
# Avertissement d'un plan d'installation qui change les URL de TURN des
# serveurs Odoo branchés (`InstallPlan.odoo_readd`), valeur `odoos`.
ODOO_READD_WARNING = "call_infra_odoo_readd"
# Table de l'outil dans la base de coturn, que coturn ne lit pas : la clé
# qu'un compte fixe avait avant d'être remplacé y reste, et
# `odoo_rollback_script` la remet en place quand la base Odoo n'a pas pu
# recevoir le nouveau mot de passe.
HELD_TABLE = "erplibre_held_user"
# Un secret ou un mot de passe de `secrets.token_urlsafe` : il entre tel quel
# dans une requête SQL et dans `turn_secret.value` (varchar(127)).
_CREDENTIAL = re.compile(r"^[A-Za-z0-9_-]{16,127}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_OWNED_USER = re.compile(r"^erplibre-[0-9a-f]{8}$")
_UNIT_NAME = re.compile(r"^[A-Za-z0-9@._-]+$")
_ODOO_DONE = ("ODOO_ADDED", "ODOO_REMOVED", "ODOO_ROLLBACK")
# Tables que les scripts d'un serveur Odoo écrivent, au schéma de coturn
# 4.6 (`schema_sql` d'install_coturn.sh) ; IF NOT EXISTS laisse en place
# une base déjà créée.
_USERDB_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS turnusers_lt ( realm varchar(127)"
    " default '', name varchar(512), hmackey char(128),"
    " PRIMARY KEY (realm,name));",
    "CREATE TABLE IF NOT EXISTS turn_secret (realm varchar(127)"
    " default '', value varchar(127), primary key (realm,value));",
    f"CREATE TABLE IF NOT EXISTS {HELD_TABLE} (realm varchar(127)"
    " default '', name varchar(512), hmackey char(128),"
    " PRIMARY KEY (realm,name));",
)


def odoo_ttl_hours(raw):
    """La durée de vie en heures que le module `erplibre_turn` applique à
    la valeur brute de `erplibre_turn.ttl_hours` : absente ou illisible,
    24 ; zéro ou négative, 1. La même règle que `ttl_hours` du module, pour
    que l'ancien secret d'une rotation vive autant que les identifiants
    qu'il a signés."""
    if raw is None or raw is False or raw == "":
        return DEFAULT_TTL_HOURS
    try:
        hours = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_TTL_HOURS
    return max(hours, 1)


def _ice_urls_for(answers, tls=True):
    """Les URL de TURN de ces réponses : STUN, TURN en UDP et en TCP sur
    `turn_port`, et avec `tls` et un certificat, TURN sur TLS au port que
    coturn sert (`coturn_tls_port`). L'hôte est le nom de TURN
    (`turn_host`), entre crochets pour une IPv6."""
    host = _url_host(turn_host(answers))
    port = answers.turn_port
    urls = [
        f"stun:{host}:{port}",
        f"turn:{host}:{port}?transport=udp",
        f"turn:{host}:{port}?transport=tcp",
    ]
    if tls and has_tls(answers):
        urls.append(f"turns:{host}:{coturn_tls_port(answers)}?transport=tcp")
    return urls


def ice_urls(state):
    """Les URL que le module `erplibre_turn` distribue
    (`erplibre_turn.urls`) pour le coturn de cet état : trois sans TLS,
    quatre avec un `turns:`. ValueError pour un état sans coturn."""
    answers = state_answers(state)
    if answers is None or "coturn" not in answers.services:
        raise ValueError("ice_urls: no coturn in the state")
    return _ice_urls_for(answers)


def _odoos(state):
    """Le registre des serveurs Odoo branchés, {clé: fiche} ; {} quand
    l'état n'en porte pas."""
    odoos = state.get("odoos") if isinstance(state, dict) else None
    return odoos if isinstance(odoos, dict) else {}


def turn_mode_for(state, module_installed):
    """Le mode de coturn qu'un serveur Odoo demande : « secret » avec le
    module `erplibre_turn`, « fixed » sans lui. Refuse
    (`call_infra_turn_mode_mismatch`, valeurs `mode` et `odoos`) quand
    d'autres Odoo sont branchés sur un coturn de l'autre mode : coturn 4.6
    ne mélange pas les deux. Sans Odoo branché, l'un ou l'autre est
    accepté, et l'ajout fait basculer coturn."""
    wanted = "secret" if module_installed else "fixed"
    mode = state.get("turn_mode") if isinstance(state, dict) else None
    mode = mode if mode in TURN_MODES else "fixed"
    odoos = _odoos(state)
    if odoos and mode != wanted:
        raise Refusal(
            "call_infra_turn_mode_mismatch",
            mode=mode,
            odoos=", ".join(sorted(odoos)),
        )
    return wanted


def _switch_to(state, mode):
    """Le mode vers lequel la configuration de coturn bascule pour accueillir
    un Odoo de `mode`, ou None quand elle y est déjà. Un état sans
    `turn_mode` est en `lt-cred-mech`, déjà le mode fixe."""
    current = state.get("turn_mode")
    if mode == "secret" and current != "secret":
        return "secret"
    if mode == "fixed" and current == "secret":
        return "fixed"
    return None


def _sha256(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _expired(item, now):
    """Vrai quand l'ancien secret `item` a passé son `expires_at`. Une date
    illisible compte pour passée : un secret ne reste jamais sans fin."""
    try:
        when = datetime.datetime.fromisoformat(str(item.get("expires_at")))
    except ValueError:
        return True
    if when.tzinfo is None:
        when = when.replace(tzinfo=datetime.timezone.utc)
    return when <= now


def _purged(state, now):
    """(copie de `state` sans les anciens secrets expirés à `now`, leurs
    empreintes). Une entrée qui n'est pas un dict part sans empreinte."""
    new = copy.deepcopy(state)
    digests = []
    for entry in _odoos(new).values():
        if not isinstance(entry, dict) or not isinstance(
            entry.get("retired"), list
        ):
            continue
        kept = []
        for item in entry["retired"]:
            if not isinstance(item, dict):
                continue
            if not _expired(item, now):
                kept.append(item)
            elif _DIGEST.match(str(item.get("value_sha256", ""))):
                digests.append(item["value_sha256"])
        entry["retired"] = kept
    return new, digests


def _coturn_target(state):
    """(unité de coturn, realm) de l'état ; ValueError sans coturn. Les deux
    finissent dans un script root : l'unité a la forme d'un nom d'unité, le
    realm celle de `_NAME`."""
    answers = state_answers(state)
    if answers is None or "coturn" not in answers.services:
        raise ValueError("no coturn in the state")
    record = state["services"]["coturn"]
    unit = record.get("unit")
    if not isinstance(unit, str) or not _UNIT_NAME.match(unit):
        raise ValueError(f"coturn unit: {unit!r}")
    if not _NAME.match(answers.public_name or ""):
        raise ValueError(f"realm: {answers.public_name!r}")
    return unit, answers.public_name


def _has_ntfy(state):
    services = state.get("services") if isinstance(state, dict) else None
    return isinstance(services, dict) and isinstance(
        services.get("ntfy"), dict
    )


def _check_exempt(address):
    """Refuse (`call_infra_odoo_exempt`) ce qui n'est pas une adresse ou un
    réseau IP, et la boucle locale, l'adresse non spécifiée et le lien
    local : derrière nginx, ntfy voit chaque client en 127.0.0.1, et
    l'exempter exempterait tout le monde."""
    try:
        if address != address.strip():
            raise ValueError(address)
        network = ipaddress.ip_network(address, strict=False)
    except (AttributeError, ValueError):
        raise Refusal("call_infra_odoo_exempt", address=address) from None
    if network.is_loopback or network.is_unspecified or network.is_link_local:
        raise Refusal("call_infra_odoo_exempt", address=address)


def _exempt_list(text):
    value = nm.read_yml_keys(text or "").get(nm.EXEMPT_HOSTS_KEY, "")
    return [host.strip() for host in value.split(",") if host.strip()]


def _owned_exempt(state, key, exempt, ntfy_text):
    """L'adresse exemptée que la fiche de `key` consigne : `exempt` quand
    l'outil la pose ou la partage avec un autre Odoo de l'état, None sans
    ntfy dans l'état (ntfy sur un autre hôte : rien n'est écrit) ou quand
    `server.yml` la portait déjà sans qu'aucun Odoo de l'état ne la
    consigne (une entrée écrite à la main, que l'outil ne retire jamais)."""
    if exempt is None or not _has_ntfy(state):
        return None
    _check_exempt(exempt)
    owned = {
        entry.get("exempt")
        for entry in _odoos(state).values()
        if isinstance(entry, dict)
    }
    if exempt in owned:
        return exempt
    if ntfy_text is None:
        raise ValueError("ntfy_text is required to exempt an address")
    return None if exempt in _exempt_list(ntfy_text) else exempt


def _exempt_text(text, before, after):
    """`server.yml` (`text`) dont la liste des hôtes exemptés passe des
    adresses que l'outil consigne dans `before` à celles de `after` : une
    adresse que plus aucun Odoo ne consigne part, une adresse consignée qui
    manque est ajoutée, les entrées écrites à la main restent. Une liste
    vide retire la clé. `text` tel quel quand rien ne change."""

    def owned(state):
        return {
            entry["exempt"]
            for entry in _odoos(state).values()
            if isinstance(entry, dict) and entry.get("exempt")
        }

    present = _exempt_list(text)
    dropped = owned(before) - owned(after)
    kept = [host for host in present if host not in dropped]
    wanted = kept + [h for h in sorted(owned(after)) if h not in kept]
    if wanted == present:
        return text
    if not wanted:
        return _drop_key(text, nm.EXEMPT_HOSTS_KEY)
    return nm._set_key(text, nm.EXEMPT_HOSTS_KEY, ",".join(wanted), True)


def _split_key(key):
    """(URL, base) d'une clé `ol.odoo_key` ; ValueError pour une clé que
    `odoo_key` n'aurait pas rendue telle quelle."""
    url, sep, database = str(key).rpartition("|")
    try:
        if not sep or ol.odoo_key(url, database) != key:
            raise ValueError(f"odoo key: {key!r}")
    except ol.OdooError:
        raise ValueError(f"odoo key: {key!r}") from None
    return url, database


def _check_odoo(state, key, kind, value, user, now):
    """Les arguments d'un ajout : ValueError, une erreur de programmation et
    non un refus pour l'utilisateur. `kind` « secret » (module) ou « user »
    (compte fixe, dont le nom est `ol.owned_username` de la clé)."""
    if kind not in ("secret", "user"):
        raise ValueError(f"kind: {kind!r}")
    if not isinstance(value, str) or not _CREDENTIAL.match(value):
        raise ValueError("credential value")
    url, database = _split_key(key)
    if kind == "user" and user != ol.owned_username(url, database):
        raise ValueError(f"user: {user!r}")
    if kind == "secret" and user is not None:
        raise ValueError("a secret has no user")
    if not isinstance(now, datetime.datetime) or now.tzinfo is None:
        raise ValueError("now must be an aware datetime")
    _coturn_target(state)


def _odoo_host_state(state, kind, now, check_secret):
    """L'état qu'écrit le script d'ajout, avant toute écriture dans Odoo :
    la bascule du mode de coturn quand elle a lieu (`turn_mode`, et
    `check_secret_sha256` en mode secret), les anciens secrets expirés
    retirés. Le registre `odoos` n'y gagne rien : la fiche ne s'écrit
    qu'une fois Odoo écrit (`odoo_added_state`)."""
    mode = turn_mode_for(state, kind == "secret")
    new, _ = _purged(state, now)
    switch = _switch_to(state, mode)
    if switch == "secret":
        if not isinstance(check_secret, str) or not _CREDENTIAL.match(
            check_secret
        ):
            raise ValueError("a check secret is required to switch")
        new["turn_mode"] = "secret"
        new["check_secret_sha256"] = _sha256(check_secret)
    elif switch == "fixed":
        new["turn_mode"] = "fixed"
        new.pop("check_secret_sha256", None)
    return new


def odoo_added_state(
    state,
    key,
    kind,
    value,
    user,
    exempt,
    now,
    *,
    ttl_hours=DEFAULT_TTL_HOURS,
    check_secret=None,
    method=None,
    ntfy_text=None,
):
    """L'état une fois Odoo écrit : celui du script d'ajout
    (`_odoo_host_state`), `turn_mode` posé, et la fiche `odoos[key]` :
    `method` (« webapi », « shell »), `module`, `credential`
    ({"kind": "secret", "value_sha256"} ou {"kind": "user", "user"}),
    `retired`, `rows` (lignes `mail.ice.server` écrites, en mode fixe),
    `exempt` (`_owned_exempt`), `added_at` (le premier ajout).

    Rotation d'un secret : l'ancien passe dans `retired` avec `expires_at`
    = `now` + `odoo_ttl_hours(ttl_hours)` ; il reste dans la base de coturn
    jusqu'au premier script qui le trouve expiré. Un compte fixe est
    remplacé sur-le-champ, sans délai. Aucun secret ni mot de passe n'est
    consigné, seulement l'empreinte d'un secret."""
    _check_odoo(state, key, kind, value, user, now)
    new = _odoo_host_state(state, kind, now, check_secret)
    new["turn_mode"] = "secret" if kind == "secret" else "fixed"
    if not isinstance(new.get("odoos"), dict):
        new["odoos"] = {}
    previous = new["odoos"].get(key)
    previous = previous if isinstance(previous, dict) else {}
    retired = previous.get("retired")
    retired = (
        [r for r in retired if isinstance(r, dict)]
        if isinstance(retired, list)
        else []
    )
    if kind == "secret":
        digest = _sha256(value)
        credential = {"kind": "secret", "value_sha256": digest}
        old = previous.get("credential")
        old = old.get("value_sha256") if isinstance(old, dict) else None
        retired = [r for r in retired if r.get("value_sha256") != digest]
        if isinstance(old, str) and _DIGEST.match(old) and old != digest:
            hours = odoo_ttl_hours(ttl_hours)
            expires = now + datetime.timedelta(hours=hours)
            retired.append(
                {
                    "value_sha256": old,
                    "expires_at": expires.isoformat(timespec="seconds"),
                }
            )
    else:
        credential = {"kind": "user", "user": user}
    new["odoos"][key] = {
        "method": method,
        "module": kind == "secret",
        "credential": credential,
        "retired": retired,
        "rows": kind == "user",
        "exempt": _owned_exempt(state, key, exempt, ntfy_text),
        "added_at": previous.get("added_at")
        or now.isoformat(timespec="seconds"),
    }
    return new


def odoo_removed_state(state, key, now):
    """L'état sans la fiche de `key`, anciens secrets expirés retirés. Le
    mode de coturn reste tel quel, même quand c'était le dernier Odoo."""
    new, _ = _purged(state, now)
    if isinstance(new.get("odoos"), dict):
        new["odoos"].pop(key, None)
    return new


def _userdb_lines(unit, realm):
    """Lignes `sh` qui préparent l'accès à la base de coturn : `DB`,
    `REALM`, `U` (le compte de l'unité, comme la vérification le lit),
    `sq` (requête sur l'entrée standard) et `sqr` (lecture seule, requête en
    argument), lancés sous ce compte par `runuser` : root n'ouvre aucun
    fichier du dossier de la base, qui lui appartient. Puis `revoke`.

    `revoke <empreinte>...` efface de `turn_secret`, pour ce realm, chaque
    valeur dont le sha256 est donné. sqlite3 n'a pas de sha256 : les valeurs
    sont lues puis hachées une à une ; `printf` est intégré au shell, une
    valeur n'atteint `sha256sum` que par le tube et `sqlite3` que par son
    entrée standard, jamais par un argv. Une valeur hors de l'alphabet des
    secrets de l'outil n'entre pas dans la requête. Sans base, rien à
    effacer. Les lignes supposent `R` et une fonction `fail`."""
    return [
        f'DB="$R"{shlex.quote(COTURN_DB)}',
        f"REALM={shlex.quote(realm)}",
        f"U=$(systemctl show -p User --value {shlex.quote(unit)}"
        " 2>/dev/null)",
        "U=${U:-turnserver}",
        'sq() { runuser -u "$U" -- sqlite3 -bail -init /dev/null "$DB"; }',
        'sqr() { runuser -u "$U" -- sqlite3 -readonly -bail -init /dev/null'
        ' "$DB" "$1"; }',
        "revoke() {",
        '  [ -f "$DB" ] || return 0',
        "  VALS=$(sqr \"SELECT value FROM turn_secret WHERE realm='$REALM';\")"
        " || return 1",
        "  printf '%s\\n' \"$VALS\" | while IFS= read -r v; do",
        "    case \"$v\" in ''|*[!A-Za-z0-9_-]*) continue ;; esac",
        "    h=$(printf %s \"$v\" | sha256sum | cut -d ' ' -f 1)",
        '    case " $* " in *" $h "*) ;; *) continue ;; esac',
        "    sq <<EOF || exit 1",
        ".timeout 5000",
        "DELETE FROM turn_secret WHERE realm='$REALM' AND value='$v';",
        "EOF",
        "  done",
        "  RC=$?",
        "  VALS=",
        '  return "$RC"',
        "}",
    ]


def _purge_lines(plan, state):
    """Lignes d'`install_script` qui effacent de la base de coturn les
    anciens secrets d'Odoo expirés (`plan.purge_secrets`), avant que l'état
    qui ne les nomme plus soit écrit ; aucune sans eux."""
    if not plan.purge_secrets:
        return []
    return [
        *_userdb_lines(*_coturn_target(state)),
        _revoke_line(plan.purge_secrets, "purge"),
    ]


def _revoke_line(digests, step):
    """`revoke` des empreintes `digests` (64 chiffres hexa chacune)."""
    for digest in digests:
        if not _DIGEST.match(str(digest)):
            raise ValueError(f"digest: {digest!r}")
    return "revoke " + " ".join(digests) + f" || fail {step}"


def _sql_lines(step, statements):
    """Un `sq` dont la requête, sur l'entrée standard, crée les tables qui
    manquent puis joue `statements`. `$REALM` et les variables du script
    s'y développent ; un échec appelle `fail <step>`."""
    return [
        f"sq <<EOF || fail {step}",
        ".timeout 5000",
        *_USERDB_SCHEMA,
        *statements,
        "EOF",
    ]


def _secret_insert_lines(value, step):
    """Pose le secret `value` dans `turn_secret`. Il voyage en base64 dans
    le script et n'est décodé que sur l'hôte, dans une variable."""
    return [
        f"V=$(printf %s {shlex.quote(_b64(value))} | base64 -d)"
        f" || fail {step}",
        *_sql_lines(
            step,
            [
                "INSERT OR IGNORE INTO turn_secret (realm, value)"
                " VALUES ('$REALM', '$V');"
            ],
        ),
        "V=",
    ]


def _user_insert_lines(user, hmackey):
    """Pose ou remplace le compte fixe `user` (clé long terme `hmackey`) ;
    la clé qu'il avait passe dans HELD_TABLE, dans la même transaction."""
    held = f"{HELD_TABLE} WHERE realm='$REALM' AND name='{user}'"
    return [
        f"K=$(printf %s {shlex.quote(_b64(hmackey))} | base64 -d)"
        " || fail user",
        *_sql_lines(
            "user",
            [
                "BEGIN;",
                f"DELETE FROM {held};",
                f"INSERT INTO {HELD_TABLE} (realm, name, hmackey)"
                " SELECT realm, name, hmackey FROM turnusers_lt"
                f" WHERE realm='$REALM' AND name='{user}';",
                "INSERT OR REPLACE INTO turnusers_lt (realm, name, hmackey)"
                f" VALUES ('$REALM', '{user}', '$K');",
                "COMMIT;",
            ],
        ),
        "K=",
    ]


def _user_undo_lines(user, step):
    """Défait `_user_insert_lines` : la clé gardée dans HELD_TABLE revient,
    ou le compte part quand il n'en avait pas."""
    return _sql_lines(
        step,
        [
            "BEGIN;",
            f"DELETE FROM turnusers_lt WHERE realm='$REALM' AND name='{user}';",
            "INSERT INTO turnusers_lt (realm, name, hmackey)"
            f" SELECT realm, name, hmackey FROM {HELD_TABLE}"
            f" WHERE realm='$REALM' AND name='{user}';",
            f"DELETE FROM {HELD_TABLE} WHERE name='{user}';",
            "COMMIT;",
        ],
    )


def _user_remove_lines(user, step):
    """Retire le compte fixe `user`, de tout realm, et sa clé gardée."""
    return _sql_lines(
        step,
        [
            f"DELETE FROM turnusers_lt WHERE name='{user}';",
            f"DELETE FROM {HELD_TABLE} WHERE name='{user}';",
        ],
    )


def _odoo_head(state, done, root):
    """Début commun des scripts d'un serveur Odoo. `fail <étape>` imprime
    `@@FAILED <étape>`, appelle `undo` (rien tant qu'un script ne le
    redéfinit pas), puis `@@<done> no`, et sort en erreur."""
    return [
        "set -u",
        _C_LOCALE,
        f"R={shlex.quote(root)}",
        f'CALL="$R"{shlex.quote(CALL_DIR)}',
        f'STATE="$R"{shlex.quote(STATE_PATH)}',
        "umask 077",
        "undo() { :; }",
        f'fail() {{ echo "@@FAILED $1"; undo; echo "@@{done} no"; exit 1; }}',
        "D=$(mktemp -d) || fail workdir",
        "trap 'rm -rf \"$D\"' EXIT",
        *_userdb_lines(*_coturn_target(state)),
    ]


def _state_lines(state):
    return [
        'mkdir -p "$CALL" || fail state',
        *_state_write_lines(state),
    ]


def _ntfy_put_lines(source):
    """Remplace `server.yml` par le fichier `source` de l'hôte : voisin
    `.erplibre-new` aux propriétaire et droits de l'original, renommé, puis
    ntfy redémarré."""
    new = '"$N.erplibre-new"'
    return [
        f'cp {source} {new} && chown --reference="$N" {new}'
        f' && chmod --reference="$N" {new} && mv -f {new} "$N"',
        f"systemctl restart {NTFY_UNIT}",
    ]


def _ntfy_lines(old, new):
    """Écrit `new` à la place de `server.yml`, seulement si le fichier de
    l'hôte est encore `old`, le texte que la sonde a lu : une modification
    faite depuis n'est pas écrasée (`fail ntfy-changed`). `NTFY=1` dès que
    le fichier est remplacé ; `undo` remet alors `old`. ntfy doit
    redevenir actif."""
    put = _ntfy_put_lines('"$D/ntfy.new"')
    restore = _ntfy_put_lines('"$D/ntfy.old"')
    return [
        f'N="$R"{shlex.quote(NTFY_CONFIG)}',
        "NTFY=0",
        "undo() {",
        '  if [ "$NTFY" = 1 ]; then',
        "    NTFY=0",
        "    { " + " && ".join(restore) + "; }"
        ' || echo "@@FAILED ntfy-restore"',
        "  fi",
        "}",
        _decode_to(_b64(old), '"$D/ntfy.old"') + " || fail ntfy",
        _decode_to(_b64(new), '"$D/ntfy.new"') + " || fail ntfy",
        'cmp -s "$D/ntfy.old" "$N" || fail ntfy-changed',
        put[0] + " || fail ntfy",
        "NTFY=1",
        put[1] + " || fail ntfy-restart",
        f"A=$(systemctl is-active {NTFY_UNIT} 2>/dev/null)",
        '[ "$A" = active ] || fail ntfy-restart',
    ]


def _switch_lines(state, mode):
    """Bascule la configuration de coturn en `mode` : install_coturn.sh
    rejoué avec les réponses de l'état et TURN_AUTH, qui réécrit
    `turnserver.conf` et redémarre coturn une fois. Le certificat lui est
    rendu : copie de celui en place pour un certificat fourni (sans elle,
    l'installateur retirerait TLS ; une copie absente arrête le script
    avant lui), la lignée certbot avec Let's Encrypt quand elle existe."""
    answers = state_answers(state)
    lines = [
        _decode_to(
            _installer_payload("coturn"), '"$D/install_coturn.sh"', gunzip=True
        )
        + " || fail payload-coturn",
    ]
    raw = {}
    if answers.tls == "supplied":
        lines.append(
            f'cp {_host(COTURN_TLS_DIR + "/turn.crt")} "$D/turn.crt"'
            f' && cp {_host(COTURN_TLS_DIR + "/turn.key")} "$D/turn.key"'
            " || fail tls-copy"
        )
        raw = {
            "TURN_CERT_FILE": '"$D/turn.crt"',
            "TURN_KEY_FILE": '"$D/turn.key"',
        }
    letsencrypt = answers.tls == "letsencrypt"
    if letsencrypt:
        lines += [
            "LE=0",
            f'[ -f {_LIVE}"/fullchain.pem" ] && [ -f {_LIVE}"/privkey.pem" ]'
            " && LE=1",
        ]
    lines += ["(", "  umask 022"] + _export(_coturn_env(answers, mode), raw)
    if letsencrypt:
        lines.append('  if [ "$LE" = 1 ]; then')
        lines += _lineage_exports(answers, "    ")
        lines.append("  fi")
    lines += [
        '  exec bash "$D/install_coturn.sh"',
        ")",
        '[ "$?" = 0 ] || fail switch',
    ]
    return lines


def _need_ntfy_text(state, key, exempt, ntfy_text):
    """ValueError quand `server.yml` peut changer sans que son texte soit
    donné : ntfy dans l'état et une adresse à exempter, ou une adresse que
    la fiche de `key` consigne déjà (elle partirait de l'état et resterait
    dans le fichier)."""
    entry = _odoos(state).get(key)
    held = isinstance(entry, dict) and entry.get("exempt")
    if _has_ntfy(state) and ntfy_text is None and (exempt or held):
        raise ValueError("ntfy_text is required to change the exempt hosts")


def _entry_of(state, key):
    entry = _odoos(state).get(key)
    if not isinstance(entry, dict):
        raise ValueError(f"no Odoo {key!r} in the state")
    return entry


def odoo_add_script(
    state,
    key,
    kind,
    value,
    user,
    exempt,
    now,
    *,
    ttl_hours=DEFAULT_TTL_HOURS,
    check_secret=None,
    ntfy_text=None,
    root="",
):
    """Script `sh`, lancé en root sur l'hôte de coturn, qui y pose le côté
    coturn d'un serveur Odoo, AVANT toute écriture dans Odoo.

    `kind` « secret » : `value` est le secret de cet Odoo (module
    `erplibre_turn`), posé dans `turn_secret` sous le realm. « user » :
    `value` est le mot de passe du compte fixe `user`
    (`ol.owned_username` de la clé), posé dans `turnusers_lt` avec sa clé
    long terme MD5(user:realm:mot de passe) ; la clé qu'il avait est
    gardée pour `odoo_rollback_script`. Secrets et clés ne voyagent qu'en
    base64 dans le corps du script, jamais dans un argv.

    Ordre : bascule du mode de coturn quand `turn_mode_for` le demande
    (`_switch_lines` ; vers « secret » le secret de contrôle `check_secret`
    est posé, vers « fixed » il est effacé, l'installateur remettant le
    compte de contrôle), anciens secrets expirés effacés (tous les Odoo),
    état écrit quand l'un des deux a eu lieu (`_odoo_host_state`), adresse
    exemptée ajoutée à `server.yml` de ntfy (texte `ntfy_text` lu par la
    sonde) quand elle n'y est pas, puis l'identifiant. Un échec après
    `server.yml` le remet tel quel. Dernières lignes : `@@TURN_MODE
    <mode>`, `@@ODOO_ADDED yes` ; `@@FAILED <étape>` et `@@ODOO_ADDED no`
    sinon. `ttl_hours` ne sert qu'à l'état final (`odoo_added_state`) ; il
    est accepté ici pour que l'appelant passe les mêmes arguments aux
    deux. Refus : `call_infra_turn_mode_mismatch`,
    `call_infra_odoo_exempt`."""
    _check_odoo(state, key, kind, value, user, now)
    _need_ntfy_text(state, key, exempt, ntfy_text)
    mode = turn_mode_for(state, kind == "secret")
    switch = _switch_to(state, mode)
    host_state = _odoo_host_state(state, kind, now, check_secret)
    added = odoo_added_state(
        state,
        key,
        kind,
        value,
        user,
        exempt,
        now,
        ttl_hours=ttl_hours,
        check_secret=check_secret,
        ntfy_text=ntfy_text,
    )
    _, purge = _purged(state, now)
    lines = _odoo_head(state, "ODOO_ADDED", root)
    if switch is not None:
        lines += _switch_lines(state, switch)
        if switch == "secret":
            lines += _secret_insert_lines(check_secret, "check-secret")
        elif _DIGEST.match(str(state.get("check_secret_sha256", ""))):
            lines.append(
                _revoke_line([state["check_secret_sha256"]], "check-secret")
            )
    if purge:
        lines.append(_revoke_line(purge, "purge"))
    if host_state != state:
        lines += _state_lines(host_state)
    if _has_ntfy(state) and ntfy_text is not None:
        text = _exempt_text(ntfy_text, state, added)
        if text != ntfy_text:
            lines += _ntfy_lines(ntfy_text, text)
    if kind == "secret":
        lines += _secret_insert_lines(value, "secret")
    else:
        realm = _coturn_target(state)[1]
        hmackey = turn_client.long_term_key(user, realm, value).hex()
        lines += _user_insert_lines(user, hmackey)
    lines += [f'echo "@@TURN_MODE {mode}"', 'echo "@@ODOO_ADDED yes"', ""]
    return "\n".join(lines)


def odoo_remove_script(state, key, *, now=None, ntfy_text=None, root=""):
    """Script `sh`, lancé en root sur l'hôte de coturn, qui débranche le
    serveur Odoo `key` de l'état : son secret courant et ses anciens
    secrets effacés sans délai de grâce (les autres Odoo gardent les
    leurs, donc leurs allocations), ou son compte fixe retiré ; les anciens
    secrets expirés des autres effacés aussi ; son adresse exemptée retirée
    de `server.yml` (texte `ntfy_text`) quand aucun autre Odoo ne la
    consigne ; l'état écrit sans lui (`odoo_removed_state`), le mode de
    coturn inchangé. Dernière ligne `@@ODOO_REMOVED yes`, ou `@@FAILED
    <étape>` et `@@ODOO_REMOVED no`. Rejouer le script après un échec
    refait le même travail. `now` : l'instant de la purge (maintenant, en
    UTC, par défaut)."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    url, database = _split_key(key)
    entry = _entry_of(state, key)
    _need_ntfy_text(state, key, None, ntfy_text)
    removed = odoo_removed_state(state, key, now)
    credential = entry.get("credential")
    credential = credential if isinstance(credential, dict) else {}
    lines = _odoo_head(state, "ODOO_REMOVED", root)
    if credential.get("kind") == "user":
        if credential.get("user") != ol.owned_username(url, database):
            raise ValueError(f"user: {credential.get('user')!r}")
        lines += _user_remove_lines(credential["user"], "revoke")
    digests = [credential.get("value_sha256")] + [
        item.get("value_sha256")
        for item in entry.get("retired") or ()
        if isinstance(item, dict)
    ]
    digests = [d for d in digests if isinstance(d, str) and _DIGEST.match(d)]
    _, purge = _purged(state, now)
    digests += [d for d in purge if d not in digests]
    if digests:
        lines.append(_revoke_line(digests, "revoke"))
    if ntfy_text is not None and _has_ntfy(state):
        text = _exempt_text(ntfy_text, state, removed)
        if text != ntfy_text:
            lines += _ntfy_lines(ntfy_text, text)
            # L'état qui suit ne nomme plus cet Odoo : un échec à l'écrire
            # ne remet pas l'adresse, la relance du retrait la retirerait.
            lines.append("NTFY=0")
    lines += _state_lines(removed)
    lines += ['echo "@@ODOO_REMOVED yes"', ""]
    return "\n".join(lines)


def odoo_rollback_script(
    state, key, credential, *, exempt=None, ntfy_text=None, root=""
):
    """Script `sh`, lancé en root sur l'hôte de coturn, qui défait un
    `odoo_add_script` dont l'écriture dans Odoo a échoué : `credential` est
    l'empreinte sha256 du secret posé (seul ce secret part, l'ancien de cet
    Odoo reste) ou le nom du compte fixe (sa clé d'avant revient, ou il
    part quand il n'existait pas). Avec `ntfy_text` et `exempt`, les mêmes
    qu'à l'ajout, `server.yml` reprend `ntfy_text` s'il porte encore ce
    que l'ajout y a écrit (`@@NTFY_KEPT` sinon). L'état n'est pas touché :
    la bascule de mode que l'ajout a consignée reste vraie. Dernière ligne
    `@@ODOO_ROLLBACK yes`, ou `@@FAILED <étape>` et `@@ODOO_ROLLBACK
    no`."""
    url, database = _split_key(key)
    lines = _odoo_head(state, "ODOO_ROLLBACK", root)
    if isinstance(credential, str) and _DIGEST.match(credential):
        lines.append(_revoke_line([credential], "revoke"))
    elif credential == ol.owned_username(url, database):
        lines += _user_undo_lines(credential, "revoke")
    else:
        raise ValueError(f"credential: {credential!r}")
    if ntfy_text is not None and _has_ntfy(state):
        after = copy.deepcopy(state)
        if not isinstance(after.get("odoos"), dict):
            after["odoos"] = {}
        after["odoos"][key] = {
            "exempt": _owned_exempt(state, key, exempt, ntfy_text)
        }
        written = _exempt_text(ntfy_text, state, after)
        if written != ntfy_text:
            restore = _ntfy_put_lines('"$D/ntfy.old"')
            lines += [
                f'N="$R"{shlex.quote(NTFY_CONFIG)}',
                _decode_to(_b64(ntfy_text), '"$D/ntfy.old"') + " || fail ntfy",
                _decode_to(_b64(written), '"$D/ntfy.cur"') + " || fail ntfy",
                'if cmp -s "$D/ntfy.cur" "$N"; then',
                f"  {restore[0]} || fail ntfy",
                f"  {restore[1]} || fail ntfy-restart",
                "else",
                '  echo "@@NTFY_KEPT"',
                "fi",
            ]
    lines += ['echo "@@ODOO_ROLLBACK yes"', ""]
    return "\n".join(lines)


def odoo_result(output):
    """Ce que dit la sortie d'un script d'Odoo : `ok` (dernier
    `@@ODOO_ADDED`, `@@ODOO_REMOVED` ou `@@ODOO_ROLLBACK` à « yes »),
    `failed` (la première étape de `@@FAILED`, ou None), `turn_mode` (celui
    de `@@TURN_MODE`, ou None)."""
    result = {"ok": False, "failed": None, "turn_mode": None}
    for name, value in marker_lines(output or ""):
        value = (value or "").strip()
        if name in _ODOO_DONE:
            result["ok"] = value == "yes"
        elif name == "FAILED" and result["failed"] is None:
            result["failed"] = value
        elif name == "TURN_MODE" and value in TURN_MODES:
            result["turn_mode"] = value
    return result


# --- Ajouter et retirer un serveur Odoo -------------------------------------

# Avertissements d'un plan d'ajout (`OdooPlan.warnings`) : compte fixe sans
# TURN sur TLS, module absent du chemin des addons (le texte dit comment
# l'y mettre), plus d'entrées ICE qu'Odoo n'en envoie (valeur `count`).
NO_TURNS_WARNING = "call_infra_no_turns"
MODULE_ABSENT_WARNING = "call_infra_module_absent"
ICE_OVER_WARNING = "call_infra_ice_over_5"
# Clés i18n que l'ajout et le retrait rendent : avertissements, puis refus
# (`Refusal`) de `plan_odoo_add`, `apply_odoo_add` et `apply_odoo_remove`.
ODOO_PLAN_KEYS = (
    NO_TURNS_WARNING,
    MODULE_ABSENT_WARNING,
    ICE_OVER_WARNING,
    "call_infra_odoo_no_coturn",
    "call_infra_odoo_version",
    "call_infra_turn_mode_mismatch",
    "call_infra_odoo_exempt",
    "call_infra_odoo_host_failed",
    "call_infra_odoo_write_failed",
    "call_infra_odoo_rollback_failed",
    "call_infra_odoo_state_failed",
    "call_infra_odoo_remove_unreachable",
)
# mail envoie au navigateur au plus cinq serveurs ICE (`search(limit=5)`,
# la borne de Firefox) ; le module `erplibre_turn` garde la même.
MAX_ICE_SERVERS = 5
# États d'`ir.module.module` : module installé (une mise à jour en attente
# ne le désinstalle pas), ou présent sur le chemin des addons et
# installable. Tout autre état, « absent » compris, ne s'installe pas.
_MODULE_INSTALLED = ("installed", "to upgrade")
_MODULE_INSTALLABLE = ("uninstalled", "to install")
# Longueur, en octets, des secrets et mots de passe tirés : celle de
# `secrets.token_urlsafe(32)`, 43 caractères.
_DRAW_BYTES = 32


@dataclasses.dataclass(frozen=True)
class OdooPlan:
    """Ce que « Ajouter un serveur Odoo » fera, calculé avant tout
    changement (`plan_odoo_add`).

    `key` : `ol.odoo_key` de la base. `kind` : « secret » (module
    `erplibre_turn`, identifiants temporaires) ou « user » (compte fixe).
    `install_module` : le module, présent sur le chemin des addons,
    s'installe d'abord. `params` : paramètres d'Odoo à écrire, sans le
    secret, tiré seulement par `apply_odoo_add` (avec le module : la liste
    `erplibre_turn.urls` ; sans lui : None pour chaque paramètre du module
    resté dans la base). `rows` : les trois lignes `mail.ice.server` du
    compte fixe, au nom `ol.owned_username`, sans mot de passe ; () avec le
    module. `rows_total` : les entrées ICE qu'Odoo aura, celles de l'outil
    plus les lignes qui ne sont pas les siennes. `warnings` : clés i18n,
    leurs valeurs dans `messages()`. `exempt` : l'adresse à exempter des
    limites de ntfy, None sans ntfy dans l'état.

    `state` : l'état de l'hôte que le plan suppose (lu par la sonde) ;
    `realm` : celui de coturn ; `ttl_hours` : la durée de vie des
    identifiants que la base applique, qui borne la grâce de l'ancien
    secret ; `ntfy_text` : `server.yml` tel que la sonde l'a lu."""

    key: str
    kind: str
    install_module: bool
    params: dict
    rows: tuple
    rows_total: int
    warnings: tuple
    exempt: str | None
    state: dict = dataclasses.field(default_factory=dict)
    realm: str = ""
    ttl_hours: int = DEFAULT_TTL_HOURS
    ntfy_text: str | None = None

    def messages(self):
        """((clé, valeurs), ...) des avertissements, dans leur ordre, pour
        `t(clé).format(**valeurs)`."""
        values = {ICE_OVER_WARNING: {"count": self.rows_total}}
        return tuple((key, dict(values.get(key, {}))) for key in self.warnings)


def _fixed_row(url, owned):
    """La ligne `mail.ice.server` de l'URL `stun:…` ou `turn:…` : le type
    avant le premier « : », l'URI après (mail les recolle en
    `type:uri`). Chaque ligne porte le nom de l'outil, celle du STUN aussi :
    sans nom, elle ne se distinguerait pas d'une ligne écrite à la main, et
    WebRTC ignore le nom d'une URL `stun:`."""
    server_type, _, uri = url.partition(":")
    return {"server_type": server_type, "uri": uri, "username": owned}


def plan_odoo_add(
    state, facts, url, database, want_module_install, exempt, *, ntfy_text=None
):
    """Le plan d'ajout de la base `database` de l'Odoo `url` (`facts` :
    `ol.OdooFacts` lus par son lien) au coturn de `state`. Rien n'est
    écrit.

    Module installé, ou présent et `want_module_install` : mode secret,
    `erplibre_turn.urls` = `ice_urls(state)`, aucune ligne. Sinon : compte
    fixe, trois lignes (STUN, TURN en UDP et en TCP, jamais `turns:`, que
    `server_type` n'offre pas). L'adresse `exempt` n'est gardée qu'avec
    ntfy dans l'état ; `ntfy_text` est alors requis (ValueError).

    Refus (`Refusal`), avant toute écriture : `call_infra_odoo_no_coturn`
    (aucun coturn dans l'état), `call_infra_odoo_version` (`version`),
    `call_infra_turn_mode_mismatch`, `call_infra_odoo_exempt`. Une URL ou
    une base invalide lève `ol.OdooError`."""
    key = ol.odoo_key(url, database)
    answers = state_answers(state)
    if answers is None or "coturn" not in answers.services:
        raise Refusal("call_infra_odoo_no_coturn")
    if facts.major != ol.SUPPORTED_MAJOR:
        raise Refusal("call_infra_odoo_version", version=facts.version)
    realm = _coturn_target(state)[1]
    installed = facts.module_state in _MODULE_INSTALLED
    install = (
        not installed
        and bool(want_module_install)
        and facts.module_state in _MODULE_INSTALLABLE
    )
    secret = installed or install
    turn_mode_for(state, secret)
    owned = ol.owned_username(url, database)
    warnings = []
    if secret:
        urls = _ice_urls_for(answers)
        params = {ol.PARAM_URLS: "\n".join(urls)}
        rows = ()
        entries = len(urls)
    else:
        params = {
            name: None
            for name in (ol.PARAM_URLS, ol.PARAM_SECRET)
            if name in facts.params
        }
        rows = tuple(
            _fixed_row(u, owned) for u in _ice_urls_for(answers, tls=False)
        )
        entries = len(rows)
        warnings.append(NO_TURNS_WARNING)
    if facts.module_state not in _MODULE_INSTALLED + _MODULE_INSTALLABLE:
        warnings.append(MODULE_ABSENT_WARNING)
    others = [r for r in facts.rows if (r.get("username") or "") != owned]
    total = len(others) + entries
    if total > MAX_ICE_SERVERS:
        warnings.append(ICE_OVER_WARNING)
    if exempt is not None and _has_ntfy(state):
        _check_exempt(exempt)
    else:
        exempt = None
    _need_ntfy_text(state, key, exempt, ntfy_text)
    return OdooPlan(
        key=key,
        kind="secret" if secret else "user",
        install_module=install,
        params=params,
        rows=rows,
        rows_total=total,
        warnings=tuple(warnings),
        exempt=exempt,
        state=copy.deepcopy(state),
        realm=realm,
        ttl_hours=odoo_ttl_hours(facts.params.get(ol.PARAM_TTL)),
        ntfy_text=ntfy_text,
    )


def _link_method(link):
    """« webapi » ou « shell », le chemin du lien vers Odoo que la fiche
    de l'état consigne ; None pour un autre objet."""
    if isinstance(link, ol.OdooShell):
        return "shell"
    if isinstance(link, ol.WebApi):
        return "webapi"
    return None


def _host_step(run, script):
    """Lance `script` par `run` (script → (code, sortie), ou None quand il
    n'a pas tourné) et rend `odoo_result` de sa sortie ; un script qui
    n'a pas abouti rend un résultat `ok` faux, `failed` à « - » quand sa
    sortie ne nomme aucune étape."""
    done = run(script)
    result = odoo_result(done[1] if done else "")
    if not result["ok"] and not result["failed"]:
        result["failed"] = "-"
    return result


def _write_odoo(link, plan, value):
    """Écrit dans Odoo, par `link`, ce que `plan` prévoit, avec le secret
    ou le mot de passe `value`. Avec le module : la liste d'URL d'abord, le
    secret en dernier (sur l'API web, chaque paramètre est sa propre
    transaction : une coupure entre les deux laisse l'ancienne
    configuration ou aucune, jamais un nouveau secret sur d'anciennes URL),
    puis les lignes que l'outil avait écrites retirées. Sans lui : les trois
    lignes (le mot de passe sur les deux TURN, aucun sur le STUN), puis les
    paramètres du module restés dans la base retirés."""
    url, database = _split_key(plan.key)
    owned = ol.owned_username(url, database)
    if plan.kind == "secret":
        link.set_params({**plan.params, ol.PARAM_SECRET: value})
        link.replace_rows(owned, [])
        return
    rows = [
        dict(row, credential=value) if row["server_type"] == "turn" else row
        for row in plan.rows
    ]
    link.replace_rows(owned, rows)
    if plan.params:
        link.set_params(plan.params)


def apply_odoo_add(
    run, link, plan, now, *, draw=secrets.token_urlsafe, root=""
):
    """Branche la base de `plan` sur coturn ; rend l'état écrit.

    `run` lance un script root sur l'hôte de coturn et rend (code, sortie),
    ou None quand il n'a pas tourné : le menu passe son `_call_infra_run`,
    le test long son lanceur, chacun masquant ce qu'il doit. `link` est le
    `ol.WebApi` ou `ol.OdooShell` de la base, `draw(nbytes)` tire les
    secrets (`secrets.token_urlsafe`) sur la machine qui lance `todo.py`.

    Ordre : le module installé quand le plan le demande (sans paramètre,
    il rend ce que mail rend : rien ne change pour les appels, et un échec
    laisse l'hôte intact) ; puis l'hôte (`odoo_add_script`, l'identifiant
    posé sur coturn avant qu'Odoo le distribue) ; puis Odoo
    (`_write_odoo`) ; enfin l'état avec la fiche de la base
    (`odoo_added_state`, `state_write_script`).

    Odoo qui refuse ou ne répond plus pendant l'écriture : le script
    `odoo_rollback_script` retire de coturn l'identifiant qui vient d'y
    être posé, et l'état garde sa fiche d'avant ; `Refusal`
    (`call_infra_odoo_write_failed`), sa cause dans `__cause__`. Une
    interruption (Ctrl-C) est défaite de même, puis relevée telle quelle.
    Autres refus : `call_infra_odoo_host_failed` (`step`), rien n'est
    écrit dans Odoo ; `call_infra_odoo_rollback_failed` (`step`) ;
    `call_infra_odoo_state_failed`. Une erreur d'installation du module
    (`ol.OdooError`) remonte telle quelle, l'hôte n'est pas touché."""
    url, database = _split_key(plan.key)
    secret = plan.kind == "secret"
    user = None if secret else ol.owned_username(url, database)
    mode = turn_mode_for(plan.state, secret)
    check_secret = None
    if _switch_to(plan.state, mode) == "secret":
        check_secret = draw(_DRAW_BYTES)
    value = draw(_DRAW_BYTES)
    if plan.install_module:
        link.install_module()
    common = dict(
        ttl_hours=plan.ttl_hours,
        check_secret=check_secret,
        ntfy_text=plan.ntfy_text,
    )
    script = odoo_add_script(
        plan.state,
        plan.key,
        plan.kind,
        value,
        user,
        plan.exempt,
        now,
        root=root,
        **common,
    )
    result = _host_step(run, script)
    if not result["ok"]:
        raise Refusal("call_infra_odoo_host_failed", step=result["failed"])
    try:
        _write_odoo(link, plan, value)
    except BaseException as error:
        rollback = odoo_rollback_script(
            plan.state,
            plan.key,
            _sha256(value) if secret else user,
            exempt=plan.exempt,
            ntfy_text=plan.ntfy_text,
            root=root,
        )
        undone = _host_step(run, rollback)
        if not isinstance(error, Exception):
            raise
        if not undone["ok"]:
            raise Refusal(
                "call_infra_odoo_rollback_failed", step=undone["failed"]
            ) from error
        raise Refusal("call_infra_odoo_write_failed") from error
    final = odoo_added_state(
        plan.state,
        plan.key,
        plan.kind,
        value,
        user,
        plan.exempt,
        now,
        method=_link_method(link),
        **common,
    )
    done = run(state_write_script(final, root=root))
    saved = dict(marker_lines(done[1] if done else "")).get("SAVED")
    if (saved or "").strip() != "yes":
        raise Refusal("call_infra_odoo_state_failed")
    return final


def apply_odoo_remove(
    run,
    link,
    state,
    key,
    *,
    now=None,
    ntfy_text=None,
    revoke_anyway=False,
    root="",
):
    """Débranche la base `key` de `state` ; rend l'état écrit.

    Odoo d'abord, par `link` : `erplibre_turn.secret` et
    `erplibre_turn.urls` retirés (le module reste installé, sa durée de vie
    aussi), puis les lignes au nom de l'outil (`replace_rows(owned, [])`),
    jamais une autre. Puis l'hôte, par `run` (comme `apply_odoo_add`) :
    `odoo_remove_script`, qui révoque sans grâce et écrit l'état sans la
    fiche. Révoquer avant de nettoyer Odoo laisserait Odoo distribuer un
    identifiant mort.

    Odoo injoignable ou qui refuse (`ol.OdooError`), ou `link` None : sans
    `revoke_anyway`, rien n'est fait sur l'hôte, `Refusal`
    (`call_infra_odoo_remove_unreachable`, la cause dans `__cause__`) ; le
    menu demande alors s'il faut révoquer quand même et rappelle avec
    `revoke_anyway=True`. Script en échec : `call_infra_odoo_host_failed`
    (`step`). `ntfy_text` : `server.yml` lu par la sonde, requis quand la
    fiche consigne une adresse exemptée. ValueError pour une clé absente
    de l'état, avant tout appel."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    url, database = _split_key(key)
    _entry_of(state, key)
    _need_ntfy_text(state, key, None, ntfy_text)
    cleaned, cause = False, None
    if link is not None:
        try:
            link.set_params({ol.PARAM_SECRET: None, ol.PARAM_URLS: None})
            link.replace_rows(ol.owned_username(url, database), [])
            cleaned = True
        except ol.OdooError as error:
            cause = error
    if not cleaned and not revoke_anyway:
        raise Refusal("call_infra_odoo_remove_unreachable") from cause
    script = odoo_remove_script(
        state, key, now=now, ntfy_text=ntfy_text, root=root
    )
    result = _host_step(run, script)
    if not result["ok"]:
        raise Refusal("call_infra_odoo_host_failed", step=result["failed"])
    return odoo_removed_state(state, key, now)


# --- Vérification -----------------------------------------------------------

CHECK_USER = "erplibre-check"
# Un certificat qui expire dans moins de jours que ceci est signalé.
CERT_WARN_DAYS = 14
# Certificats que la vérification lit sur l'hôte, par étiquette : ceux des
# services, celui que nginx sert pour un certificat fourni (`site`) et la
# feuille de la lignée de certbot (`lineage`).
TLS_CERTS = {
    "coturn": f"{COTURN_TLS_DIR}/turn.crt",
    "ntfy": f"{NTFY_TLS_DIR}/ntfy.crt",
    "site": SITE_CERT,
    "lineage": f"{LINEAGE_DIR}/cert.pem",
}
# Minuteurs de renouvellement que l'installation de certbot active ou pose :
# ceux des paquets (Debian et Ubuntu, Arch), puis celui de l'outil quand le
# paquet n'en livre aucun.
CERTBOT_OWN_TIMER = "erplibre-call-certbot.timer"
CERTBOT_TIMERS = ("certbot.timer", "certbot-renew.timer", CERTBOT_OWN_TIMER)
# Pair d'une plage privée (RFC 1918) vers lequel la vérification demande
# une permission : coturn de production doit la refuser.
PRIVATE_PROBE_PEER = "10.0.0.1"
# Mot que Let's Encrypt met dans le nom des émetteurs de son serveur de
# test : un certificat qu'aucun client ne reconnaît.
STAGING_ISSUER = "(STAGING)"
_HEX_KEY = re.compile(r"^[0-9a-f]{32}$")

# Clés i18n que porte `CheckLine.detail` ; chacune a sa traduction dans
# todo_i18n.py, avec les champs de `CheckLine.values` entre accolades.
CHECK_KEYS = (
    "call_infra_check_no_state",
    "call_infra_check_active",
    "call_infra_check_relayed",
    "call_infra_check_open_relay",
    "call_infra_check_turn_error",
    "call_infra_check_no_key",
    "call_infra_check_healthy",
    "call_infra_check_unhealthy",
    "call_infra_check_http_error",
    "call_infra_check_cert_unverified",
    "call_infra_check_cert_days",
    "call_infra_check_cert_missing",
    "call_infra_check_cert_unreadable",
    "call_infra_check_cert_issuer",
    "call_infra_check_cert_staging",
    "call_infra_check_renewal_ok",
    "call_infra_check_renewal_no_hook",
    "call_infra_check_renewal_held",
    "call_infra_check_renewal_timer",
    "call_infra_check_private_denied",
    "call_infra_check_private_open",
    "call_infra_check_private_unknown",
    "call_infra_check_firewall_none",
    "call_infra_check_firewall_ok",
    "call_infra_check_firewall_missing",
)


@dataclasses.dataclass(frozen=True)
class CheckLine:
    """Une ligne du verdict de `check_local`.

    `ok` : True, False, ou None quand la chose n'a pas pu être vérifiée,
    la raison dans `detail`. `detail` est une clé de CHECK_KEYS, `values`
    les champs de son message (`t(detail).format(**values)`).
    """

    name: str
    ok: bool | None
    detail: str
    values: dict = dataclasses.field(default_factory=dict)


# `ufw show added` : la ligne exacte qu'écrit `_ufw_script` pour une règle
# de l'outil. Imprime « @@FIREWALL_RULE ufw <proto> <port> <service> ».
_CHECK_UFW_SED = (
    r"s/^ufw allow ([0-9]+(:[0-9]+)?)\/(tcp|udp) comment"
    f" '{FIREWALL_COMMENT} ({'|'.join(FIREWALL_LABELS)})'$"
    r"/@@FIREWALL_RULE ufw \3 \1 \4/p"
)
# `nft list ruleset` : une règle de l'outil, telle que `_nft_rule` la pose
# (une plage s'y écrit avec « - »).
_CHECK_NFT_SED = (
    r"s/.*[[:space:]](tcp|udp) dport ([0-9]+(-[0-9]+)?) accept comment"
    f' "{FIREWALL_COMMENT} ({"|".join(FIREWALL_LABELS)})".*'
    r"/@@FIREWALL_RULE nftables \1 \2 \4/p"
)


def check_remote_script(root=""):
    """Script `sh` en lecture seule, lancé en root, qui imprime ce que la
    vérification lit sur l'hôte.

    Lignes : `@@STATE <base64>` (l'état, s'il existe), `@@ACTIVE <service>
    <état systemd>` (« absent » sans unité), `@@CHECK_KEY <hex>` (la clé
    long terme du compte de contrôle, lue dans la base de coturn par
    `sqlite3 -readonly` sous le compte du service : root n'ouvre aucun
    fichier de ce dossier, qui appartient à ce compte), `@@CERT <étiquette>
    <base64>` par certificat de TLS_CERTS présent, `@@HOOK <exec|present>`
    quand le crochet de déploiement existe (exécutable ou non),
    `@@RENEWAL <active|held>` selon le fichier de renouvellement de la
    lignée (en place, ou mis de côté), `@@TIMER <unité> <état systemd>` par
    minuteur de CERTBOT_TIMERS que systemd connaît, `@@FIREWALL_RULE
    <ufw|nftables> <proto> <port> <service>` par règle de l'outil présente
    dans un pare-feu actif, puis `@@END`. `root` préfixe chaque chemin lu
    (tests).

    La ligne `@@CHECK_KEY` porte un secret : qui la lit s'authentifie
    auprès du relais sous le compte de contrôle. La sortie se capture sans
    être recopiée à l'écran.
    """
    query = f"select hmackey from turnusers_lt where name='{CHECK_USER}'"
    certs = " ".join(f"{svc}:{path}" for svc, path in TLS_CERTS.items())
    return "\n".join(
        [
            _C_LOCALE,
            f"R={shlex.quote(root)}",
            "echo",
            f'S="$R"{shlex.quote(STATE_PATH)}',
            'if [ -f "$S" ]; then echo "@@STATE $(base64 -w0 < "$S")"; fi',
            "CU=-",
            "for u in " + " ".join(COTURN_UNITS.values()) + "; do",
            '  if systemctl cat "$u" >/dev/null 2>&1; then CU=$u; break; fi',
            "done",
            'if [ "$CU" != - ]; then',
            '  A=$(systemctl is-active "$CU" 2>/dev/null)',
            '  echo "@@ACTIVE coturn ${A:-unknown}"',
            "else",
            '  echo "@@ACTIVE coturn absent"',
            "fi",
            f"if systemctl cat {NTFY_UNIT} >/dev/null 2>&1; then",
            f"  A=$(systemctl is-active {NTFY_UNIT} 2>/dev/null)",
            '  echo "@@ACTIVE ntfy ${A:-unknown}"',
            "else",
            '  echo "@@ACTIVE ntfy absent"',
            "fi",
            f'DB="$R"{shlex.quote(COTURN_DB)}',
            'if [ "$CU" != - ] && [ -f "$DB" ]'
            " && command -v sqlite3 >/dev/null 2>&1; then",
            '  U=$(systemctl show -p User --value "$CU" 2>/dev/null)',
            '  runuser -u "${U:-turnserver}" -- sqlite3 -readonly'
            f' -init /dev/null "$DB" "{query}" 2>/dev/null'
            " | sed 's/^/@@CHECK_KEY /'",
            "fi",
            f"for c in {certs}; do",
            '  f="$R${c#*:}"',
            '  if [ -f "$f" ]; then'
            ' echo "@@CERT ${c%%:*} $(base64 -w0 < "$f")"; fi',
            "done",
            f'H="$R"{shlex.quote(HOOK_PATH)}',
            'if [ -f "$H" ] && [ -x "$H" ]; then echo "@@HOOK exec";'
            ' elif [ -e "$H" ]; then echo "@@HOOK present"; fi',
            f'if [ -f "$R"{shlex.quote(RENEWAL_FILE)} ]; then'
            ' echo "@@RENEWAL active";'
            f' elif [ -f "$R"{shlex.quote(RENEWAL_HOLD)} ]; then'
            ' echo "@@RENEWAL held"; fi',
            "for u in " + " ".join(CERTBOT_TIMERS) + "; do",
            '  if systemctl cat "$u" >/dev/null 2>&1; then',
            '    A=$(systemctl is-active "$u" 2>/dev/null)',
            '    echo "@@TIMER $u ${A:-unknown}"',
            "  fi",
            "done",
            "if command -v ufw >/dev/null 2>&1"
            " && ufw status 2>/dev/null | grep -q '^Status: active'; then",
            "  ufw show added 2>/dev/null"
            f" | sed -n -E {shlex.quote(_CHECK_UFW_SED)}",
            "fi",
            "if command -v nft >/dev/null 2>&1; then",
            "  nft list ruleset 2>/dev/null"
            f" | sed -n -E {shlex.quote(_CHECK_NFT_SED)}",
            "fi",
            'echo "@@END"',
            "",
        ]
    )


def parse_check_remote(output):
    """Dict de la sortie de `check_remote_script` : `state` (dict ou None),
    `active` {service: état}, `check_key` (32 chiffres hexa ou None),
    `firewall_rules` [(ufw|nftables, Rule)], `certs` {étiquette de
    TLS_CERTS: PEM}, `hook` (« exec », « present » ou None), `renewal`
    (« active », « held » ou None), `timers` {minuteur de CERTBOT_TIMERS:
    état}. Une valeur hors de ces formes est écartée.

    Une règle hors format ou sur le port de ssh est écartée, comme dans
    `rules_from_state`. Refusal `call_infra_probe_incomplete` sans `@@END`.
    """
    state, active, key, rules, certs = None, {}, None, [], {}
    hook = renewal = None
    timers = {}
    complete = False
    for name, value in marker_lines(output):
        if name == "STATE":
            state = _decode_json(value)
        elif name == "ACTIVE":
            svc, _, current = value.partition(" ")
            if svc in SERVICES:
                active[svc] = current.strip() or "unknown"
        elif name == "CHECK_KEY":
            candidate = value.strip().lower()
            if key is None and _HEX_KEY.match(candidate):
                key = candidate
        elif name == "FIREWALL_RULE":
            parts = value.split()
            if len(parts) != 4 or parts[0] not in ("ufw", "nftables"):
                continue
            found = Rule(parts[1], parts[2].replace("-", ":"), parts[3])
            try:
                _check_rule(found)
            except ValueError:
                continue
            if (parts[0], found) not in rules:
                rules.append((parts[0], found))
        elif name == "CERT":
            label, _, encoded = value.partition(" ")
            text = _decode(encoded)
            if label in TLS_CERTS and text:
                certs[label] = text
        elif name == "HOOK":
            if value.strip() in ("exec", "present"):
                hook = value.strip()
        elif name == "RENEWAL":
            if value.strip() in ("active", "held"):
                renewal = value.strip()
        elif name == "TIMER":
            parts = value.split()
            if (
                len(parts) == 2
                and parts[0] in CERTBOT_TIMERS
                and _UNIT_STATE.match(parts[1])
            ):
                timers[parts[0]] = parts[1]
        elif name == "END":
            complete = True
    if not complete:
        raise Refusal("call_infra_probe_incomplete")
    return {
        "state": state,
        "active": active,
        "check_key": key,
        "firewall_rules": rules,
        "certs": certs,
        "hook": hook,
        "renewal": renewal,
        "timers": timers,
    }


class _NamedHTTPS(http.client.HTTPConnection):
    """Connexion https vers `host` dont le certificat est vérifié sous
    `server_name` : l'adresse jointe et le nom attendu diffèrent quand on
    vérifie un hôte par son adresse."""

    def __init__(self, host, port, server_name, context, timeout):
        super().__init__(host, port, timeout=timeout)
        self.server_name = server_name
        self.tls_context = context

    def connect(self):
        super().connect()
        self.sock = self.tls_context.wrap_socket(
            self.sock, server_hostname=self.server_name
        )


def https_get(
    address, port, path, tls, server_name=None, cafile=None, timeout=5.0
):
    """(statut, corps) d'un GET sur `address`:`port`, en https si `tls`.

    Le certificat est vérifié sous `server_name` (sinon `address`) contre
    `cafile`, sinon contre les autorités du système ; un certificat que
    rien ne garantit lève ssl.SSLCertVerificationError. Les autres échecs
    lèvent OSError ou http.client.HTTPException. Corps lu sur 64 Kio au
    plus."""
    name = server_name or address
    if tls:
        context = ssl.create_default_context(cafile=cafile)
        connection = _NamedHTTPS(address, port, name, context, timeout)
    else:
        connection = http.client.HTTPConnection(address, port, timeout=timeout)
    try:
        connection.request(
            "GET", path, headers={"Host": f"{_url_host(name)}:{port}"}
        )
        response = connection.getresponse()
        body = response.read(65536).decode("utf-8", "replace")
        return response.status, body
    finally:
        connection.close()


def _int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _turn_lines(settings, key, address, cafile, allocate, timeout):
    """Une allocation réelle par transport, sous le compte de contrôle ;
    TLS dès qu'un certificat existe (fourni ou de Let's Encrypt), sur 443
    quand coturn y sert TLS. Le nom attendu dans le certificat est celui de
    TURN en production, le nom public sinon. Un certificat de Let's Encrypt
    se vérifie contre les autorités du système ; un certificat fourni,
    contre `cafile`. Sans autorité fournie, un échec TLS sur un certificat
    fourni ne distingue pas une autorité que le système ne connaît pas
    d'une panne : la ligne vaut None."""
    tls = settings.get("tls")
    turn_port = _int(settings.get("turn_port"), 3478)
    transports = [("udp", turn_port), ("tcp", turn_port)]
    if tls in ("supplied", "letsencrypt"):
        tls_port = (
            TURNS_ALT_PORT
            if settings.get("turns_443")
            else _int(settings.get("turns_port"), 5349)
        )
        transports.append(("tls", tls_port))
    if not key:
        return [
            CheckLine(f"turn-{transport}", None, "call_infra_check_no_key")
            for transport, _ in transports
        ]
    authority = cafile if tls == "supplied" else None
    lines = []
    for transport, port in transports:
        extra = {}
        if transport == "tls":
            extra = dict(
                cafile=authority,
                server_name=settings.get("turn_name")
                or settings.get("public_name")
                or address,
            )
        result = allocate(
            address,
            port,
            transport,
            CHECK_USER,
            bytes.fromhex(key),
            timeout=timeout,
            **extra,
        )
        name = f"turn-{transport}"
        if result.ok:
            host, relayed_port = result.relayed or ("?", 0)
            relayed = f"{_url_host(host)}:{relayed_port}"
            lines.append(
                CheckLine(
                    name,
                    True,
                    "call_infra_check_relayed",
                    {"relayed": relayed},
                )
            )
        elif result.error == "no-auth":
            lines.append(CheckLine(name, False, "call_infra_check_open_relay"))
        elif result.error == "tls" and transport == "tls" and not authority:
            if tls == "supplied":
                lines.append(
                    CheckLine(name, None, "call_infra_check_cert_unverified")
                )
            else:
                lines.append(
                    CheckLine(
                        name,
                        False,
                        "call_infra_check_turn_error",
                        {"error": result.error},
                    )
                )
        else:
            lines.append(
                CheckLine(
                    name,
                    False,
                    "call_infra_check_turn_error",
                    {"error": result.error},
                )
            )
    return lines


def _private_line(settings, key, address, permission, timeout):
    """Production : une permission demandée vers PRIVATE_PROBE_PEER depuis
    une allocation du compte de contrôle. coturn la refuse (403) quand ses
    plages privées sont refusées ; accordée, n'importe quel détenteur
    d'identifiants relaie vers le réseau de l'hôte. Une allocation en échec
    ne dit rien des plages : None, la cause dans `error`."""
    name = "private-denied"
    if not key:
        return CheckLine(name, None, "call_infra_check_no_key")
    result = permission(
        address,
        _int(settings.get("turn_port"), 3478),
        "udp",
        CHECK_USER,
        bytes.fromhex(key),
        PRIVATE_PROBE_PEER,
        timeout=timeout,
    )
    peer = {"peer": PRIVATE_PROBE_PEER}
    if result.ok:
        return CheckLine(name, False, "call_infra_check_private_open", peer)
    if (result.error or "").startswith("403"):
        return CheckLine(name, True, "call_infra_check_private_denied", peer)
    return CheckLine(
        name, None, "call_infra_check_private_unknown", {"error": result.error}
    )


def _ntfy_line(settings, address, cafile, https_get, timeout, production):
    """`/v1/health` de ntfy : en production par nginx, en https sur 443 sous
    le nom de ntfy ; sinon sur le port de ntfy, en https avec un
    certificat fourni. Un échec de vérification ne vaut None que pour un
    certificat fourni sans autorité donnée."""
    tls_mode = settings.get("tls")
    if production:
        tls, port = True, HTTPS_PORT
        server_name = settings.get("ntfy_name") or settings.get("public_name")
    else:
        tls = tls_mode == "supplied"
        port = _int(
            settings.get("port"), NTFY_HTTPS_PORT if tls else NTFY_HTTP_PORT
        )
        server_name = settings.get("public_name")
    authority = cafile if tls and tls_mode == "supplied" else None
    name = "ntfy-health"
    try:
        status, body = https_get(
            address,
            port,
            "/v1/health",
            tls,
            server_name=server_name or address,
            cafile=authority,
            timeout=timeout,
        )
    except ssl.SSLCertVerificationError as exc:
        if tls_mode == "supplied" and not authority:
            return CheckLine(name, None, "call_infra_check_cert_unverified")
        error = str(exc) or type(exc).__name__
        return CheckLine(
            name, False, "call_infra_check_http_error", {"error": error}
        )
    except (OSError, http.client.HTTPException, ValueError) as exc:
        error = str(exc) or type(exc).__name__
        return CheckLine(
            name, False, "call_infra_check_http_error", {"error": error}
        )
    try:
        healthy = json.loads(body).get("healthy") is True
    except (ValueError, AttributeError):
        healthy = False
    if status == 200 and healthy:
        return CheckLine(name, True, "call_infra_check_healthy")
    return CheckLine(
        name, False, "call_infra_check_unhealthy", {"status": status}
    )


def _cert_labels(settings, production):
    """Étiquettes de TLS_CERTS des certificats que voient les clients :
    celui de coturn dès qu'il a TLS ; pour ntfy, le sien en développement
    avec un certificat fourni, en production celui que sert nginx (la
    copie `site` d'un certificat fourni, ou la lignée de Let's Encrypt)."""
    labels = []
    coturn = settings.get("coturn")
    if coturn is not None and coturn.get("tls") in ("supplied", "letsencrypt"):
        labels.append("coturn")
    ntfy = settings.get("ntfy")
    if ntfy is not None:
        tls = ntfy.get("tls")
        if production and tls == "supplied":
            labels.append("site")
        elif production and tls == "letsencrypt":
            labels.append("lineage")
        elif tls == "supplied":
            labels.append("ntfy")
    return labels


def _expiry_line(labels, certs, now):
    """Le certificat installé qui expire le premier, parmi `labels` ; sous
    CERT_WARN_DAYS jours, la ligne échoue."""
    name = "cert-expiry"
    earliest = None
    for label in labels:
        pem = certs.get(label)
        if not pem:
            return CheckLine(
                name,
                False,
                "call_infra_check_cert_missing",
                {"service": label},
            )
        try:
            not_after = _certificate_facts(pem)[0]
        except Refusal as refusal:
            return CheckLine(
                name,
                False,
                "call_infra_check_cert_unreadable",
                {"reason": refusal.values.get("reason", "")},
            )
        earliest = not_after if earliest is None else min(earliest, not_after)
    days = (earliest - now).days
    return CheckLine(
        name,
        days >= CERT_WARN_DAYS,
        "call_infra_check_cert_days",
        {"days": days, "date": earliest.strftime("%Y-%m-%d")},
    )


def _certificate_issuer(cert_pem):
    """(nom commun de l'émetteur, texte de l'émetteur) du premier
    certificat de `cert_pem`, lus par la commande openssl ; le nom commun
    vaut le texte entier quand l'émetteur n'en a pas. Refusal
    `call_infra_cert_unreadable` sinon."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "cert.pem")
        with open(path, "w") as handle:
            handle.write(cert_pem)
        try:
            done = subprocess.run(
                [
                    "openssl",
                    "x509",
                    "-noout",
                    "-issuer",
                    "-nameopt",
                    "multiline,utf8",
                    "-in",
                    path,
                ],
                capture_output=True,
                text=True,
                check=True,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            reason = getattr(exc, "stderr", None) or str(exc)
            raise Refusal(
                "call_infra_cert_unreadable", reason=reason.strip()
            ) from None
    fields = []
    for line in done.stdout.splitlines()[1:]:
        key, sep, value = line.partition("=")
        if sep:
            fields.append((key.strip(), value.strip()))
    text = ", ".join(value for _key, value in fields)
    common = [value for key, value in fields if key == "commonName"]
    return (common[0] if common else text), text


def _issuer_line(labels, certs):
    """L'émetteur des certificats lisibles de `labels` (None sans aucun) ;
    un émetteur du serveur de test de Let's Encrypt (STAGING_ISSUER) fait
    échouer la ligne : aucun navigateur ni téléphone ne le reconnaît."""
    issuers = []
    for label in labels:
        pem = certs.get(label)
        if not pem:
            continue
        try:
            found = _certificate_issuer(pem)
        except Refusal:
            continue
        if found not in issuers:
            issuers.append(found)
    if not issuers:
        return None
    staging = [common for common, text in issuers if STAGING_ISSUER in text]
    if staging:
        return CheckLine(
            "cert-issuer",
            False,
            "call_infra_check_cert_staging",
            {"issuer": staging[0]},
        )
    names = []
    for common, _text in issuers:
        if common not in names:
            names.append(common)
    return CheckLine(
        "cert-issuer",
        True,
        "call_infra_check_cert_issuer",
        {"issuer": ", ".join(names)},
    )


def _renewal_line(state, facts_remote):
    """Let's Encrypt : le renouvellement passe par le crochet de
    déploiement (présent et exécutable), le fichier de renouvellement de
    la lignée en place (pas mis de côté) et un minuteur actif, celui que
    l'état consigne, sinon n'importe lequel de CERTBOT_TIMERS."""
    name = "renewal"
    if facts_remote.get("hook") != "exec":
        return CheckLine(
            name,
            False,
            "call_infra_check_renewal_no_hook",
            {"path": HOOK_PATH},
        )
    if facts_remote.get("renewal") != "active":
        return CheckLine(
            name,
            False,
            "call_infra_check_renewal_held",
            {"path": RENEWAL_FILE},
        )
    timers = facts_remote.get("timers") or {}
    record = state.get("certbot")
    timer = record.get("timer") if isinstance(record, dict) else None
    if _timer_record(timer):
        unit = timer["unit"]
        current = timers.get(unit, "absent")
    else:
        active = [u for u in CERTBOT_TIMERS if timers.get(u) == "active"]
        unit, current = (
            (active[0], "active")
            if active
            else next(
                iter(timers.items()), (", ".join(CERTBOT_TIMERS), "absent")
            )
        )
    if current != "active":
        return CheckLine(
            name,
            False,
            "call_infra_check_renewal_timer",
            {"timer": unit, "state": current},
        )
    return CheckLine(
        name, True, "call_infra_check_renewal_ok", {"timer": unit}
    )


def _firewall_line(state, present):
    """Les règles consignées comparées à celles de l'outil que le pare-feu
    consigné porte encore ; une règle du même port dans un autre pare-feu
    ne compte pas."""
    record = state.get("firewall")
    kind = record.get("kind") if isinstance(record, dict) else "none"
    kind = kind if kind in FIREWALLS else "unknown"
    recorded = rules_from_state(state)
    if kind not in ("ufw", "nftables") or not recorded:
        return CheckLine(
            "firewall", None, "call_infra_check_firewall_none", {"kind": kind}
        )
    have = {found for found_kind, found in present if found_kind == kind}
    missing = [r for r in recorded if r not in have]
    if missing:
        text = ", ".join(_ufw_spec(r) for r in missing)
        return CheckLine(
            "firewall",
            False,
            "call_infra_check_firewall_missing",
            {"rules": text},
        )
    return CheckLine(
        "firewall",
        True,
        "call_infra_check_firewall_ok",
        {"count": len(recorded)},
    )


def check_local(
    facts_remote,
    address,
    cafile,
    allocate=turn_client.allocate,
    https_get=https_get,
    now=None,
    timeout=5.0,
    permission=turn_client.permission,
):
    """Vérification depuis la machine qui lance `todo.py`.

    `facts_remote` vient de `parse_check_remote` ; `address` est le nom ou
    l'adresse par où l'hôte est joint ; `cafile` l'autorité d'un certificat
    fourni (None : celles du système, qui vérifient Let's Encrypt). Lignes,
    pour les services consignés dans l'état : `turn-udp`, `turn-tcp`,
    `turn-tls` (avec un certificat ; allocations réelles sous le compte de
    contrôle), `private-denied` (production : `_private_line`),
    `ntfy-health` (`/v1/health`, par nginx sur 443 en production),
    `cert-expiry` et `cert-issuer` (avec un certificat), `renewal` (Let's
    Encrypt), `firewall`, puis `service-<service>`. Sans état : une seule
    ligne `state` en échec.
    """
    state = facts_remote.get("state")
    services = state.get("services") if isinstance(state, dict) else None
    records = {
        svc: services[svc]
        for svc in SERVICES
        if isinstance(services, dict) and isinstance(services.get(svc), dict)
    }
    if not records:
        return [CheckLine("state", False, "call_infra_check_no_state")]
    if now is None:
        now = datetime.datetime.now(datetime.timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=datetime.timezone.utc)
    production = state.get("mode") == "production"
    settings = {
        svc: (
            record.get("settings")
            if isinstance(record.get("settings"), dict)
            else {}
        )
        for svc, record in records.items()
    }
    key = facts_remote.get("check_key")
    lines = []
    if "coturn" in records:
        lines += _turn_lines(
            settings["coturn"], key, address, cafile, allocate, timeout
        )
        if production:
            lines.append(
                _private_line(
                    settings["coturn"], key, address, permission, timeout
                )
            )
    if "ntfy" in records:
        lines.append(
            _ntfy_line(
                settings["ntfy"],
                address,
                cafile,
                https_get,
                timeout,
                production,
            )
        )
    labels = _cert_labels(settings, production)
    certs = facts_remote.get("certs") or {}
    if labels:
        lines.append(_expiry_line(labels, certs, now))
        issuer = _issuer_line(labels, certs)
        if issuer is not None:
            lines.append(issuer)
    if any(s.get("tls") == "letsencrypt" for s in settings.values()):
        lines.append(_renewal_line(state, facts_remote))
    lines.append(
        _firewall_line(state, facts_remote.get("firewall_rules") or [])
    )
    active = facts_remote.get("active") or {}
    for svc in records:
        current = active.get(svc, "unknown")
        lines.append(
            CheckLine(
                f"service-{svc}",
                current == "active",
                "call_infra_check_active",
                {"state": current},
            )
        )
    return lines


# --- Désinstallation --------------------------------------------------------

PACKAGES = {"coturn": "coturn", "ntfy": "ntfy"}
COTURN_DATA_DIR = os.path.dirname(COTURN_DB)
NTFY_DATA_DIR = os.path.dirname(NTFY_AUTH_FILE)
NTFY_CACHE_DIR = "/var/cache/ntfy"
# L'unité et le binaire que pose install_ntfy.sh quand aucun paquet ne
# fournit ntfy ; sa ligne Description signe l'unité.
NTFY_TOOL_UNIT = "/etc/systemd/system/ntfy.service"
NTFY_TOOL_BINARY = "/usr/local/bin/ntfy"
NTFY_TOOL_DESCRIPTION = "Description=ntfy push notification server"
# La purge du paquet ntfy peut emporter ses dossiers (script postrm) : ce
# que l'outil garde y est mis de côté, sous HOLD_PREFIX<tampon>, le temps
# de la purge, puis remis. Une désinstallation coupée entre les deux le
# laisse là ; la suivante le remet en premier.
HOLD_PREFIX = "/var/lib/erplibre-call.hold-"
_HELD = (("ntfy-data", NTFY_DATA_DIR), ("ntfy-tls", NTFY_TLS_DIR))
_UNITS = {"coturn": tuple(COTURN_UNITS.values()), "ntfy": (NTFY_UNIT,)}
_TLS_FILES = {
    "coturn": {f"{COTURN_TLS_DIR}/turn.crt", f"{COTURN_TLS_DIR}/turn.key"},
    "ntfy": {f"{NTFY_TLS_DIR}/ntfy.crt", f"{NTFY_TLS_DIR}/ntfy.key"},
}
_HOST_PATH = re.compile(r"^(/[A-Za-z0-9._@+-]+)+$")


def _safe_path(path):
    """Chemin absolu fait de caractères sûrs, sans « . » ni « .. » : il
    vient de l'état de l'hôte et finit dans un script lancé en root."""
    return (
        isinstance(path, str)
        and bool(_HOST_PATH.match(path))
        and not any(part in (".", "..") for part in path.split("/"))
    )


def _uninstall_records(state):
    """[(service, fiche)] des services consignés, chaque valeur vérifiée :
    unité connue, chemins sûrs, copie `<config>.bak-<tampon>`, fichiers TLS
    de ceux que l'outil pose, complément d'unité de coturn (COTURN_DROPIN
    de son unité). Refusal `call_infra_state_invalid` sinon."""
    services = state.get("services", {})
    if not isinstance(services, dict):
        raise Refusal("call_infra_state_invalid", service="services")
    records = []
    for svc in SERVICES:
        if svc not in services:
            continue
        record = services[svc]
        invalid = Refusal("call_infra_state_invalid", service=svc)
        if not isinstance(record, dict):
            raise invalid
        config, backup = record.get("config"), record.get("backup")
        tls_files = record.get("tls_files") or []
        if record.get("unit") not in _UNITS[svc] or not _safe_path(config):
            raise invalid
        if backup is not None and not _is_backup_of(config, backup):
            raise invalid
        was_active = record.get("was_active")
        was_enabled = record.get("was_enabled")
        if was_active not in (True, False, None) or not (
            was_enabled is None
            or (
                isinstance(was_enabled, str) and _UNIT_STATE.match(was_enabled)
            )
        ):
            raise invalid
        if not isinstance(tls_files, list) or not all(
            isinstance(path, str) and path in _TLS_FILES[svc]
            for path in tls_files
        ):
            raise invalid
        dropin = record.get("dropin") if svc == "coturn" else None
        if dropin is not None and dropin != COTURN_DROPIN.format(
            unit=record["unit"]
        ):
            raise invalid
        records.append(
            (
                svc,
                {
                    "unit": record["unit"],
                    "config": config,
                    "installed_by_tool": bool(record.get("installed_by_tool")),
                    "adopted": bool(record.get("adopted")),
                    "backup": backup,
                    "was_active": was_active,
                    "was_enabled": was_enabled,
                    "admin_added": record.get("admin_added") is True,
                    "tls_files": sorted(tls_files),
                    "dropin": dropin,
                },
            )
        )
    return records


# États dpkg qu'une opération coupée (ssh perdu pendant apt) laisse au
# paquet : il est encore sur l'hôte et se purge, mais apt-get refuse toute
# action tant que « dpkg --configure -a » n'a pas tourné, comme le font
# install_coturn.sh et install_ntfy.sh avant d'installer.
_DPKG_INTERRUPTED = (
    "half-installed|unpacked|half-configured|triggers-awaited|triggers-pending"
)


def _uninstall_helpers():
    """Fonctions `sh` du script : famille du système (os-release, mêmes
    listes qu'`os_family`), paquet présent et purge, remise en place de ce
    qui a été mis de côté. Sur Debian, un paquet dans un état de
    _DPKG_INTERRUPTED compte comme présent, et sa purge passe d'abord par
    « dpkg --configure -a » ; « config-files » ne compte pas."""
    debian = "|".join(sorted(_DEBIAN_IDS))
    arch = "|".join(sorted(_ARCH_IDS))
    held = " ".join(f"{name}:{path}" for name, path in _HELD)
    return [
        "FAMILY=",
        'if [ -r "$R/etc/os-release" ]; then',
        '  FAMILY=$(. "$R/etc/os-release"; for i in "${ID:-}" ${ID_LIKE:-};'
        f' do case "$i" in {debian}) echo debian; break ;;'
        f" {arch}) echo arch; break ;; esac; done)",
        "fi",
        "dpkg_status() {",
        "  S=$(dpkg-query -W -f='${Status}' \"$1\" 2>/dev/null) || S=",
        '  echo "${S##* }"',
        "}",
        "pkg_installed() {",
        '  case "$FAMILY" in',
        '    debian) case "$(dpkg_status "$1")" in'
        f" installed|{_DPKG_INTERRUPTED}) return 0 ;; esac; return 1 ;;",
        '    arch) pacman -Qq "$1" >/dev/null 2>&1 ;;',
        "    *) return 1 ;;",
        "  esac",
        "}",
        "pkg_purge() {",
        '  case "$FAMILY" in',
        f'    debian) case "$(dpkg_status "$1")" in {_DPKG_INTERRUPTED})',
        "      DEBIAN_FRONTEND=noninteractive dpkg --configure -a"
        " --force-confdef --force-confold </dev/null ;;",
        "    esac",
        '    DEBIAN_FRONTEND=noninteractive apt-get purge -y "$1"'
        " </dev/null ;;",
        '    arch) pacman -Rn --noconfirm "$1" </dev/null ;;',
        "    *) return 1 ;;",
        "  esac",
        "}",
        "held_back() {",
        f"  for E in {held}; do",
        '    N=${E%%:*}; P="$R${E#*:}"',
        '    [ -e "$1/$N" ] || continue',
        '    if [ -d "$P" ]; then rmdir "$P" 2>/dev/null; fi',
        '    if [ -e "$P" ]; then failed "hold-$N"; continue; fi',
        '    mkdir -p "$(dirname "$P")" && mv "$1/$N" "$P"'
        ' || failed "hold-$N"',
        "  done",
        '  rmdir "$1" 2>/dev/null',
        "}",
    ]


def _is_managed_test(path):
    """Test `sh` vrai quand le fichier de l'hôte porte MARKER en tête."""
    host = _host(path)
    return (
        f'[ -f {host} ] && [ "$(head -n 1 {host})" = {shlex.quote(MARKER)} ]'
    )


def _stop_lines(svc, unit):
    quoted = shlex.quote(unit)
    return [
        f"if systemctl cat {quoted} >/dev/null 2>&1; then",
        f"  if systemctl disable --now {quoted} >/dev/null 2>&1; then"
        f' echo "@@REMOVED unit {unit}";',
        f"  else failed stop-{svc}; fi",
        "fi",
    ]


def _remove_managed_lines(svc, config):
    return [
        f"if {_is_managed_test(config)}; then",
        f'  if rm -f {_host(config)}; then echo "@@REMOVED config {config}";'
        f" else failed config-{svc}; fi",
        "fi",
    ]


def _ntfy_tool_files_lines():
    """L'unité qu'install_ntfy.sh a écrite (sa Description), et le binaire
    qu'elle lance s'il est celui qu'il a posé ; une unité d'une autre main
    reste."""
    unit, binary = _host(NTFY_TOOL_UNIT), _host(NTFY_TOOL_BINARY)
    return [
        f"if [ -f {unit} ] && grep -qxF"
        f" {shlex.quote(NTFY_TOOL_DESCRIPTION)} {unit}; then",
        "  B=$(sed -n -E 's/^ExecStart=([^[:space:]]+) serve.*/\\1/p'"
        f" {unit} | head -n 1)",
        f"  if rm -f {unit}; then"
        f' echo "@@REMOVED unit-file {NTFY_TOOL_UNIT}";'
        " else failed unit-file-ntfy; fi",
        "  systemctl daemon-reload >/dev/null 2>&1",
        f'  if [ "$B" = {NTFY_TOOL_BINARY} ] && [ -f {binary} ]; then',
        f"    if rm -f {binary}; then"
        f' echo "@@REMOVED binary {NTFY_TOOL_BINARY}";'
        " else failed binary-ntfy; fi",
        "  fi",
        "fi",
    ]


def _admin_removal_lines():
    """Retrait de NTFY_ADMIN_USER d'un ntfy adopté, sous la configuration
    de l'outil, encore en place, et sous le compte du service quand il
    existe (comme install_ntfy.sh) : root laisserait dans le dossier de la
    base des fichiers que ntfy ne peut plus écrire. Un compte déjà parti
    ne fait rien."""
    config, user = _host(NTFY_CONFIG), shlex.quote(NTFY_ADMIN_USER)
    found = shlex.quote(f"^user {NTFY_ADMIN_USER} ")
    return [
        "if command -v ntfy >/dev/null 2>&1; then",
        '  U=; id ntfy >/dev/null 2>&1 && U="runuser -u ntfy --"',
        f"  if $U ntfy user --config {config} list 2>&1 | grep -q {found};"
        " then",
        f"    if $U ntfy user --config {config} del {user} >/dev/null 2>&1;"
        f' then echo "@@REMOVED account {NTFY_ADMIN_USER}";',
        "    else failed account-ntfy; fi",
        "  fi",
        "fi",
    ]


def _restore_lines(svc, record, before_restart=()):
    """Copie remise par `mv` (droits et propriétaire de l'original) ; une
    copie disparue alors que la configuration de l'outil est en place se
    dit (`@@BACKUP_MISSING`) et laisse le service tel que l'outil l'a
    configuré (KEEP_<service>=1, KEPT=1) : ni ses fichiers TLS, ni ses
    données, ni l'état ne partent, sans bloquer les autres services.

    L'unité retrouve ce qu'elle était avant l'outil, dont l'installateur
    l'a activée et démarrée : arrêtée si elle ne tournait pas, désactivée
    si `is-enabled` disait « disabled », relancée sinon (et pour un état
    qui ne le consigne pas). `before_restart` (lignes `sh`) passe juste
    avant, la configuration remise."""
    config, backup = record["config"], record["backup"]
    unit = shlex.quote(record["unit"])
    lines = []
    if backup:
        lines += [f"if [ -f {_host(backup)} ]; then"]
        if svc == "ntfy" and record.get("admin_added"):
            lines += ["  " + line for line in _admin_removal_lines()]
        lines += [
            f"  if mv -f {_host(backup)} {_host(config)}; then"
            f' echo "@@RESTORED {config} {backup}";',
            f"  else failed restore-{svc}; fi",
            f"elif {_is_managed_test(config)}; then",
        ]
    else:
        lines.append(f"if {_is_managed_test(config)}; then")
    lines += [
        f'  echo "@@BACKUP_MISSING {svc} {backup or "-"}";'
        f" KEEP_{svc}=1; KEPT=1",
        "fi",
        f'if [ "$KEEP_{svc}" = 0 ]; then',
        *["  " + line for line in before_restart],
    ]
    if record.get("was_active") is False:
        lines.append(
            f"  systemctl stop {unit} >/dev/null 2>&1 || failed stop-{svc}"
        )
    else:
        lines.append(
            f"  systemctl try-restart {unit} >/dev/null 2>&1"
            f' || echo "@@RESTART_FAILED {svc}"'
        )
    if record.get("was_enabled") == "disabled":
        lines.append(
            f"  systemctl disable {unit} >/dev/null 2>&1"
            f" || failed disable-{svc}"
        )
    lines.append("fi")
    return lines


def _put_back_lines(svc, record):
    """La copie d'origine remise par `mv` après la purge d'un service que
    l'outil a posé ET dont il a adopté la configuration (fichier resté sans
    paquet) : l'hôte retrouve son fichier, sans service à relancer. Une
    copie disparue se dit (`@@BACKUP_LOST`) sans rien bloquer : le paquet
    est déjà parti, il n'y a plus rien à garder."""
    config, backup = _host(record["config"]), _host(record["backup"])
    return [
        f"if [ -f {backup} ]; then",
        f"  if mv -f {backup} {config}; then"
        f' echo "@@RESTORED {record["config"]} {record["backup"]}";',
        f"  else failed restore-{svc}; fi",
        "else",
        f'  echo "@@BACKUP_LOST {svc} {record["backup"]}"',
        "fi",
    ]


def _service_uninstall_lines(svc, record, remove_data, stamp):
    """Lignes `sh` d'un service. Posé par l'outil : arrêt, purge du
    paquet, fichiers et configuration retirés, puis la configuration
    d'origine remise quand l'outil l'avait aussi adoptée. Adopté :
    configuration d'origine remise, unité rendue à son état d'avant
    l'outil, paquet laissé. Paquet déjà là sans configuration : arrêt et
    configuration de l'outil retirée. Le complément d'unité de coturn
    (`_dropin_lines`) part une fois le service arrêté, ou avant que
    l'unité adoptée ne reparte. Puis ses fichiers TLS et ses données,
    retirés ou gardés selon `remove_data`."""
    installed = record["installed_by_tool"]
    hold = svc == "ntfy" and installed and not remove_data
    package = PACKAGES[svc]
    dropin = _dropin_lines(record["dropin"]) if record.get("dropin") else []
    lines = [f"# {svc}", f"KEEP_{svc}=0"]
    if installed:
        lines += _stop_lines(svc, record["unit"])
        lines += dropin
        purge = [
            f"if pkg_installed {package}; then",
            f"  if pkg_purge {package}; then"
            f' echo "@@REMOVED package {package}";'
            f" else failed package-{svc}; fi",
            "fi",
        ]
        if hold:
            target = f'"$R"{shlex.quote(HOLD_PREFIX + stamp)}'
            lines += [f"H={target}", 'HOLD=1; mkdir -p "$H" || HOLD=0']
            for name, path in _HELD:
                lines.append(
                    f"if [ -e {_host(path)} ]; then"
                    f' mv {_host(path)} "$H/{name}" || HOLD=0; fi'
                )
            # Rien ne se purge tant que les données ne sont pas à l'abri.
            lines += ['if [ "$HOLD" = 1 ]; then']
            lines += ["  " + line for line in purge]
            lines += [f"else failed hold-{svc}; fi"]
        else:
            lines += purge
        if svc == "ntfy":
            lines += _ntfy_tool_files_lines()
        lines += _remove_managed_lines(svc, record["config"])
        if record["adopted"] and record["backup"]:
            lines += _put_back_lines(svc, record)
        if svc == "ntfy":
            cache = _host(NTFY_CACHE_DIR)
            lines.append(
                f"if [ -e {cache} ]; then rm -rf {cache}"
                f' && echo "@@REMOVED data {NTFY_CACHE_DIR}"'
                " || failed cache-ntfy; fi"
            )
            if hold:
                lines.append('held_back "$H"')
            else:
                data = _host(NTFY_DATA_DIR)
                lines.append(
                    f"if [ -e {data} ]; then rm -rf {data}"
                    f' && echo "@@REMOVED data {NTFY_DATA_DIR}"'
                    " || failed data-ntfy; fi"
                )
    elif record["adopted"]:
        lines += _restore_lines(svc, record, before_restart=dropin)
    else:
        lines += _stop_lines(svc, record["unit"])
        lines += dropin
        lines += _remove_managed_lines(svc, record["config"])
    lines.append(f'if [ "$KEEP_{svc}" = 0 ]; then')
    for path in record["tls_files"]:
        host = _host(path)
        if remove_data:
            lines.append(
                f"  if [ -e {host} ]; then rm -f {host}"
                f' && echo "@@REMOVED tls {path}" || failed tls-{svc}; fi'
            )
        else:
            lines.append(f'  if [ -e {host} ]; then echo "@@KEPT {path}"; fi')
    if svc == "coturn":
        data = _host(COTURN_DATA_DIR)
        lines.append(
            f"  if [ -e {data} ]; then rm -rf {data}"
            f' && echo "@@REMOVED data {COTURN_DATA_DIR}"'
            " || failed data-coturn; fi"
        )
    else:
        auth = _host(NTFY_AUTH_FILE)
        lines += [
            f'  if [ -e {auth} ]; then echo "@@KEPT {NTFY_AUTH_FILE}"; fi',
            f"  rmdir {_host(NTFY_TLS_DIR)} 2>/dev/null",
            f"  rmdir {_host(os.path.dirname(NTFY_CONFIG))} 2>/dev/null",
        ]
    lines += ["  :", "fi"]
    return lines


# Ligne include qu'install_nginx.sh ajoute à nginx.conf (disposition
# arch-include), reconnue telle que `ensure_include` l'écrit, à l'espace
# près.
_NGINX_INCLUDE_LINE_ERE = (
    r"^[[:space:]]*include[[:space:]]+"
    + NGINX_INCLUDE_DIR.replace(".", r"\.")
    + r"/\*\.conf[[:space:]]*;[[:space:]]*$"
)
# Copie de nginx.conf d'avant la ligne include : `<nginx.conf>.bak-<date>`,
# suivie de « .<pid> » quand la date était déjà prise.
_NGINX_BACKUP_SUFFIX = re.compile(r"^[0-9]+(\.[0-9]+)?$")
# Paquets de greffons DNS que l'installation de certbot peut poser.
_DNS_PLUGIN_PACKAGES = frozenset(
    pattern.format(plugin)
    for pattern in DNS_PACKAGES.values()
    for plugin in DNS_PLUGINS
)
# Unités du minuteur que l'outil écrit quand le paquet n'en livre aucun.
_CERTBOT_OWN_UNITS = tuple(
    f"/etc/systemd/system/{CERTBOT_OWN_TIMER[: -len('.timer')]}{suffix}"
    for suffix in (".service", ".timer")
)
# Paquets que la purge d'un nginx posé par l'outil retire : Debian sépare
# la configuration (nginx-common) du binaire.
_NGINX_PACKAGES = ("nginx", "nginx-common")


def _production_records(state):
    """Fiches « nginx », « certbot » et « hook » de l'état, chaque valeur
    vérifiée : chemins exactement ceux de l'outil (site, lien et nginx.conf
    déduits de la disposition), copie `nginx.conf.bak-<date>`, paquets de
    greffons connus, minuteur de CERTBOT_TIMERS, identifiants sous DNS_DIR.
    Une fiche absente vaut None. Refusal `call_infra_state_invalid` sinon,
    `service` nommant la fiche."""
    found = {"nginx": None, "certbot": None, "hook": False}
    nginx = state.get("nginx")
    if nginx is not None:
        invalid = Refusal("call_infra_state_invalid", service="nginx")
        if not isinstance(nginx, dict):
            raise invalid
        layout = nginx.get("layout")
        if layout not in NGINX_LAYOUTS:
            raise invalid
        site, link, include = _nginx_paths(layout)
        backup = nginx.get("backup")
        tls_files = nginx.get("tls_files") or []
        if (
            (nginx.get("site"), nginx.get("link"), nginx.get("include"))
            != (site, link, include)
            or nginx.get("acme_root") not in (None, ACME_ROOT)
            or not (
                backup is None
                or (
                    isinstance(backup, str)
                    and backup.startswith(NGINX_CONF + ".bak-")
                    and _NGINX_BACKUP_SUFFIX.match(
                        backup[len(NGINX_CONF) + 5 :]
                    )
                )
            )
            or not isinstance(tls_files, list)
            or not all(
                isinstance(path, str) and path in (SITE_CERT, SITE_KEY)
                for path in tls_files
            )
        ):
            raise invalid
        was_enabled = nginx.get("was_enabled")
        found["nginx"] = {
            "installed_by_tool": nginx.get("installed_by_tool") is True,
            "was_active": nginx.get("was_active") is not False,
            "was_disabled": was_enabled == "disabled",
            "site": site,
            "link": link,
            "include": include,
            "backup": backup,
            "tls_files": sorted(tls_files),
        }
    certbot = state.get("certbot")
    if certbot is not None:
        invalid = Refusal("call_infra_state_invalid", service="certbot")
        if not isinstance(certbot, dict):
            raise invalid
        plugins = certbot.get("plugins_installed") or []
        timer = certbot.get("timer")
        credentials = certbot.get("dns_credentials")
        expected = {
            "cert_name": CERT_NAME,
            "lineage": LINEAGE_DIR,
            "renewal": RENEWAL_FILE,
        }
        if (
            any(
                certbot.get(key, value) != value
                for key, value in expected.items()
            )
            or not isinstance(plugins, list)
            or not all(p in _DNS_PLUGIN_PACKAGES for p in plugins)
            or not (
                timer is None
                or (_timer_record(timer) and timer["unit"] in CERTBOT_TIMERS)
            )
            or credentials
            not in (None, *(f"{DNS_DIR}/{p}.ini" for p in DNS_PLUGINS))
        ):
            raise invalid
        found["certbot"] = {
            "installed_by_tool": certbot.get("installed_by_tool") is True,
            "plugins": list(dict.fromkeys(plugins)),
            "timer": timer["unit"] if timer and timer["added"] else None,
        }
    hook = state.get("hook")
    if hook is not None:
        if not isinstance(hook, dict) or hook.get("path") != HOOK_PATH:
            raise Refusal("call_infra_state_invalid", service="hook")
        found["hook"] = True
    return found


def _dropin_lines(path):
    """Le complément d'unité de coturn que l'outil a posé (MARKER en tête)
    part, son dossier s'il est vide, puis systemd relit les unités ; un
    complément d'une autre main reste."""
    host = _host(path)
    return [
        f"if {_is_managed_test(path)}; then",
        f'  if rm -f {host}; then echo "@@REMOVED dropin {path}";'
        " else failed dropin-coturn; fi",
        f"  rmdir {_host(os.path.dirname(path))} 2>/dev/null",
        "  systemctl daemon-reload >/dev/null 2>&1",
        "fi",
    ]


def _hook_lines():
    host = _host(HOOK_PATH)
    return [
        "# crochet de déploiement",
        f"if [ -e {host} ] || [ -L {host} ]; then",
        f'  if rm -f {host}; then echo "@@REMOVED hook {HOOK_PATH}";'
        " else failed hook; fi",
        "fi",
    ]


def _foreign_lineage_lines():
    """FOREIGN=1 quand certbot renouvelle une autre lignée que celle de
    l'outil : son minuteur, son paquet et ses greffons restent alors."""
    return [
        "FOREIGN=0",
        f'for f in "$R"{shlex.quote(os.path.dirname(RENEWAL_FILE))}/*.conf;'
        " do",
        '  [ -f "$f" ] || continue',
        f'  [ "$f" = "$R"{shlex.quote(RENEWAL_FILE)} ] || FOREIGN=1',
        "done",
    ]


def _timer_lines(unit):
    """Le minuteur que l'outil a activé ou posé (`@@CERTBOT_TIMER <unité>
    added`) s'arrête ; ses unités propres partent. Une autre lignée garde
    le minuteur."""
    quoted = shlex.quote(unit)
    lines = [
        "# minuteur de renouvellement",
        'if [ "$FOREIGN" = 1 ]; then',
        f'  echo "@@KEPT timer {unit}"',
        "else",
        f"  if systemctl cat {quoted} >/dev/null 2>&1; then",
        f"    if systemctl disable --now {quoted} >/dev/null 2>&1; then"
        f' echo "@@REMOVED timer {unit}";',
        "    else failed timer; fi",
        "  fi",
    ]
    if unit == CERTBOT_OWN_TIMER:
        for path in _CERTBOT_OWN_UNITS:
            lines += [
                f"  if {_is_managed_test(path)}; then",
                f"    if rm -f {_host(path)}; then"
                f' echo "@@REMOVED unit-file {path}";'
                " else failed timer; fi",
                "  fi",
            ]
        lines.append("  systemctl daemon-reload >/dev/null 2>&1")
    lines.append("fi")
    return lines


def _nginx_remove_lines(record):
    """Le site de l'outil (MARKER en tête), son lien dans sites-enabled et
    la ligne include de nginx.conf partent ; chacun est d'abord copié dans
    `$D/nginx` pour que `_nginx_restore_lines` le remette. NGX=1 quand
    quelque chose a changé. Un fichier au même nom sans MARKER reste."""
    site = record["site"]
    lines = [
        "# nginx",
        'NGX=0; NOK=1; NB="$D/nginx"',
        'mkdir -p "$NB" || failed nginx-workdir',
        f"if [ ! -L {_host(site)} ] && {_is_managed_test(site)}; then",
        f'  if cp -p {_host(site)} "$NB/site" && rm -f {_host(site)}; then',
        f'    echo "@@REMOVED nginx-site {site}"; NGX=1',
        "  else failed nginx-site; fi",
        "fi",
    ]
    if record["link"]:
        link = _host(record["link"])
        lines += [
            f'if [ -L {link} ] && [ "$(readlink {link})" = {shlex.quote(site)} ];'
            " then",
            f'  if rm -f {link}; then echo "@@REMOVED nginx-link'
            f' {record["link"]}"; NGX=1;',
            "  else failed nginx-link; fi",
            "fi",
        ]
    if record["include"]:
        conf = _host(record["include"])
        ere = shlex.quote(_NGINX_INCLUDE_LINE_ERE)
        lines += [
            f"if [ -f {conf} ] && [ ! -L {conf} ] && grep -qE {ere} {conf};"
            " then",
            f'  T=$(mktemp "$(dirname {conf})/.nginx.conf.XXXXXX")' " || T=",
            f'  if [ -n "$T" ] && cp -p {conf} "$NB/conf"'
            f' && grep -vE {ere} {conf} > "$T"'
            f' && chmod --reference={conf} "$T"'
            f' && chown --reference={conf} "$T"'
            f' && mv -f "$T" {conf}; then',
            f'    echo "@@REMOVED nginx-include {record["include"]}"; NGX=1',
            '  else [ -z "$T" ] || rm -f "$T"; failed nginx-include; fi',
            "fi",
            f"rmdir {_host(NGINX_INCLUDE_DIR)} 2>/dev/null",
        ]
    return lines


def _nginx_restore_lines(record):
    """Les copies de `$D/nginx` remises : site, lien, nginx.conf."""
    lines = [
        f'  if [ -f "$NB/site" ]; then mkdir -p'
        f" {_host(os.path.dirname(record['site']))}"
        f' && mv -f "$NB/site" {_host(record["site"])}; fi',
    ]
    if record["link"]:
        link = _host(record["link"])
        lines.append(
            f"  if [ ! -e {link} ] && [ ! -L {link} ]; then"
            f" ln -s {shlex.quote(record['site'])} {link}; fi"
        )
    if record["include"]:
        lines.append(
            f'  if [ -f "$NB/conf" ]; then'
            f' mv -f "$NB/conf" {_host(record["include"])}; fi'
        )
    return lines


def _nginx_backup_lines(record):
    """Après le retrait de la ligne include, nginx.conf est remis par sa
    copie d'avant l'outil quand il lui est identique (droits et
    propriétaire d'origine) ; une copie qui diffère dit que l'administrateur
    a changé nginx.conf depuis : elle reste, ses changements aussi."""
    backup = record["backup"]
    if not (record["include"] and backup):
        return []
    conf, saved = _host(record["include"]), _host(backup)
    return [
        f"  if [ -f {saved} ] && cmp -s {conf} {saved}; then",
        f"    if mv -f {saved} {conf}; then"
        f' echo "@@RESTORED {record["include"]} {backup}";',
        "    else failed nginx-backup; fi",
        f'  elif [ -f {saved} ]; then echo "@@KEPT {backup}"; fi',
    ]


def _nginx_other_sites_lines():
    """NGP reste à 1 quand nginx n'a plus que ce que son paquet livre :
    aucun fichier dans sites-enabled hormis le lien `default` du paquet,
    aucun conf.d/*.conf, rien dans erplibre-call.d, et aucun fichier de
    configuration du paquet modifié (`dpkg -V`, `pacman -Qii`), qu'une
    purge emporterait. Chaque raison de garder nginx s'imprime, puis
    `@@KEPT package nginx`."""
    default = "/etc/nginx/sites-enabled/default"
    places = (
        '"$R"/etc/nginx/sites-enabled/* "$R"/etc/nginx/conf.d/*.conf'
        f' "$R"{NGINX_INCLUDE_DIR}/*'
    )
    return [
        f"  for f in {places}; do",
        '    [ -e "$f" ] || [ -L "$f" ] || continue',
        f'    if [ "$f" = "$R"{shlex.quote(default)} ]; then',
        '      case "$(readlink "$f")" in',
        "        /etc/nginx/sites-available/default|../sites-available/default)"
        " continue ;;",
        "      esac",
        "    fi",
        '    NGP=0; echo "@@NGINX_OTHER_SITE ${f#"$R"}"',
        "  done",
        '  case "$FAMILY" in',
        "    debian) M=$(dpkg -V " + " ".join(_NGINX_PACKAGES) + " 2>/dev/null"
        " | awk '$NF ~ /^\\/etc\\/nginx\\// { print $NF; exit }') ;;",
        "    arch) M=$(pacman -Qii nginx 2>/dev/null"
        ' | awk \'$1 == "MODIFIED" && $NF ~ /^\\/etc\\/nginx\\//'
        " { print $NF; exit }') ;;",
        "    *) M= ;;",
        "  esac",
        '  if [ -n "$M" ]; then NGP=0; echo "@@NGINX_MODIFIED $M"; fi',
        '  if [ "$NGP" = 0 ] && pkg_installed nginx; then'
        ' echo "@@KEPT package nginx"; fi',
    ]


def _nginx_finish_lines(record, remove_data):
    """Après le retrait : purge du paquet quand l'outil l'a posé et que
    rien d'autre n'y vit (NGP=1, `_nginx_other_sites_lines`), sans test ni
    rechargement ; sinon, si un fichier a changé, « nginx -t » puis
    rechargement de nginx s'il tourne. Un test en échec remet les fichiers
    de l'outil (`_nginx_restore_lines`), ne recharge rien, imprime
    `@@NGINX_TEST_FAILED <ligne>` et met NOK à 0 : le dossier du défi et la
    lignée, que le site remis lit, restent. Puis les copies du certificat
    fourni lues par nginx, gardées ou retirées selon `remove_data`."""
    lines = ["NGP=0"]
    if record["installed_by_tool"]:
        lines += ['if [ "$OK" = 1 ]; then', "  NGP=1"]
        lines += _nginx_other_sites_lines()
        lines.append("fi")
    lines += [
        'if [ "$NGP" = 1 ]; then',
        *_nginx_backup_lines(record),
        "  if systemctl cat nginx >/dev/null 2>&1; then",
        "    systemctl disable --now nginx >/dev/null 2>&1"
        " || failed stop-nginx",
        "  fi",
    ]
    for package in _NGINX_PACKAGES:
        lines += [
            f"  if pkg_installed {package}; then",
            f"    if pkg_purge {package}; then"
            f' echo "@@REMOVED package {package}";'
            " else failed package-nginx; fi",
            "  fi",
        ]
    lines += [
        'elif [ "$NGX" = 1 ] && command -v nginx >/dev/null 2>&1; then',
        "  if NT=$(nginx -t 2>&1); then",
        *["  " + line for line in _nginx_backup_lines(record)],
        "    if systemctl is-active --quiet nginx; then",
        "      systemctl reload nginx >/dev/null 2>&1"
        ' && echo "@@RELOADED nginx" || failed nginx-reload',
        "    fi",
        "  else",
        "    E=$(printf '%s\\n' \"$NT\" | grep -m 1 -F '[emerg]')"
        " || E=$(printf '%s\\n' \"$NT\" | tail -n 1)",
        '    echo "@@NGINX_TEST_FAILED $E"',
        *["  " + line for line in _nginx_restore_lines(record)],
        "    NOK=0; failed nginx-test",
        "  fi",
    ]
    if _nginx_backup_lines(record):
        lines += ['elif [ "$NGX" = 1 ]; then', *_nginx_backup_lines(record)]
    lines.append("fi")
    # Un nginx déjà là retrouve ce qu'il était : install_nginx.sh l'a
    # activé et démarré. Pas après un test en échec : le site de l'outil
    # est revenu, la relance reprendra.
    restore = []
    if not record["was_active"]:
        restore.append(
            "  systemctl stop nginx >/dev/null 2>&1 || failed stop-nginx"
        )
    if record["was_disabled"]:
        restore.append(
            "  systemctl disable nginx >/dev/null 2>&1 || failed disable-nginx"
        )
    if restore:
        lines += [
            'if [ "$NGP" = 0 ] && [ "$NOK" = 1 ]'
            " && systemctl cat nginx >/dev/null 2>&1; then",
            *restore,
            "fi",
        ]
    for path in record["tls_files"]:
        host = _host(path)
        if remove_data:
            lines.append(
                f"if [ -e {host} ]; then rm -f {host}"
                f' && echo "@@REMOVED tls {path}" || failed tls-nginx; fi'
            )
        else:
            lines.append(f'if [ -e {host} ]; then echo "@@KEPT {path}"; fi')
    return lines


def _lineage_lines(remove_data):
    """La lignée de l'outil. Gardée : son fichier de renouvellement est mis
    de côté (RENEWAL_HOLD), « certbot renew » l'ignore et une
    réinstallation le remet. Avec `remove_data` et NOK à 1 : un fichier mis
    de côté revient, puis « certbot delete » retire la lignée ; sans
    certbot sur l'hôte, ses dossiers partent à la main. Un échec remet le
    fichier de côté."""
    live, renewal = _host(LINEAGE_DIR), _host(RENEWAL_FILE)
    hold = _host(RENEWAL_HOLD)
    if not remove_data:
        return [
            "# certificat gardé",
            f"if [ -e {renewal} ]; then",
            f'  if mv -f {renewal} {hold}; then echo "@@HELD {RENEWAL_FILE}";'
            " else failed hold-renewal; fi",
            "fi",
            f'if [ -e {live} ]; then echo "@@KEPT {LINEAGE_DIR}"; fi',
        ]
    archive = _host(LINEAGE_DIR.replace("/live/", "/archive/"))
    config = (
        f'"$R"{shlex.quote(os.path.dirname(os.path.dirname(LINEAGE_DIR)))}'
    )
    return [
        "# certificat retiré",
        'if [ "$NOK" = 1 ]; then',
        "  UH=0",
        f"  if [ ! -e {renewal} ] && [ -e {hold} ]; then",
        f"    mv -f {hold} {renewal} && UH=1",
        "  fi",
        f"  if [ -e {renewal} ] || [ -e {live} ]; then",
        "    if command -v certbot >/dev/null 2>&1; then",
        f"      certbot delete --cert-name {CERT_NAME} --non-interactive"
        f' --config-dir {config} > "$D/certbot.out" 2>&1; CRC=$?',
        "    else",
        f"      rm -rf {live} {archive} {renewal}; CRC=$?",
        "    fi",
        '    if [ "$CRC" = 0 ]; then',
        f'      rm -f {hold}; echo "@@REMOVED certificate {CERT_NAME}"',
        "    else",
        '      tail -n 1 "$D/certbot.out" 2>/dev/null >&2',
        f'      [ "$UH" = 0 ] || mv -f {renewal} {hold}',
        "      failed certbot-delete",
        "    fi",
        "  fi",
        "fi",
    ]


def _dns_lines():
    """Les identifiants DNS sous DNS_DIR partent, quoi qu'il arrive aux
    autres étapes : ce sont des clés d'API."""
    return [
        "# identifiants DNS",
        f'for f in "$R"{shlex.quote(DNS_DIR)}/*.ini; do',
        '  [ -e "$f" ] || continue',
        '  if rm -f "$f"; then echo "@@REMOVED dns ${f#"$R"}";'
        " else failed dns; fi",
        "done",
        f"rmdir {_host(DNS_DIR)} 2>/dev/null",
    ]


def _certbot_package_lines(record, remove_data):
    """Paquets que l'outil a posés : ses greffons DNS quand certbot ne
    renouvelle aucune autre lignée, certbot en plus quand la lignée de
    l'outil a quitté le disque (`remove_data`, « certbot delete » réussi) ;
    gardés, ils se disent."""
    lines = []
    for package in record["plugins"]:
        lines += [
            f"if pkg_installed {package}; then",
            '  if [ "$FOREIGN" = 1 ]; then'
            f' echo "@@KEPT package {package}";',
            f"  elif pkg_purge {package}; then"
            f' echo "@@REMOVED package {package}";',
            "  else failed package-certbot; fi",
            "fi",
        ]
    if record["installed_by_tool"] and remove_data:
        gone = " && ".join(
            f"[ ! -e {_host(path)} ]"
            for path in (LINEAGE_DIR, RENEWAL_FILE, RENEWAL_HOLD)
        )
        lines += [
            "if pkg_installed certbot; then",
            f'  if [ "$FOREIGN" = 0 ] && {gone}; then',
            "    if pkg_purge certbot; then"
            ' echo "@@REMOVED package certbot";',
            "    else failed package-certbot; fi",
            '  else echo "@@KEPT package certbot"; fi',
            "fi",
        ]
    elif record["installed_by_tool"]:
        lines.append(
            'if pkg_installed certbot; then echo "@@KEPT package certbot"; fi'
        )
    return lines


def _production_uninstall_lines(prod, remove_data):
    """Lignes `sh` des fiches de production, après les services : minuteur
    ajouté, site nginx, dossier du défi ACME, lignée, identifiants DNS,
    paquets. Le crochet part avant les services (`_hook_lines`)."""
    lines = []
    certbot, nginx = prod["certbot"], prod["nginx"]
    if certbot:
        lines += _foreign_lineage_lines()
        if certbot["timer"]:
            lines += _timer_lines(certbot["timer"])
    if nginx:
        lines += _nginx_remove_lines(nginx)
        lines += _nginx_finish_lines(nginx, remove_data)
    else:
        lines.append("NOK=1")
    if nginx or certbot:
        acme = _host(ACME_ROOT)
        lines += [
            f'if [ "$NOK" = 1 ] && [ -e {acme} ]; then',
            f'  if rm -rf {acme}; then echo "@@REMOVED acme {ACME_ROOT}";'
            " else failed acme; fi",
            "fi",
        ]
    if certbot:
        lines += _lineage_lines(remove_data)
        lines += _dns_lines()
        lines += _certbot_package_lines(certbot, remove_data)
    return lines


def uninstall_script(state, remove_data, stamp, root=""):
    """Script `sh` de désinstallation, lancé en root sur l'hôte.

    Sans état (`state` None) : `@@PENDING <nom>` pour chaque fiche d'une
    installation interrompue (PENDING_NAMES), puis `@@NOTHING` ; rien ne
    change.

    Avec un état, dans l'ordre : ce qu'une désinstallation coupée a laissé
    de côté revient ; les règles consignées partent du pare-feu
    (`firewall_script` « delete », ses lignes `@@FIREWALL_*` relayées) ;
    le crochet de déploiement de certbot part (`_hook_lines`) ; chaque
    service consigné est traité par `_service_uninstall_lines` ; les fiches
    de production par `_production_uninstall_lines` (minuteur ajouté, site
    nginx et ligne include, dossier du défi ACME, lignée gardée ou retirée,
    identifiants DNS, paquets posés par l'outil) ;
    puis, SEULEMENT si aucune étape n'a échoué, `/etc/erplibre-call` est
    retiré, sauf `tls/` (gardé sans `remove_data`) et les fiches des
    services que l'état ne consigne pas (`@@PENDING_LEFT <service>`), l'état
    en dernier (`@@REMOVED state`). Chaque retrait imprime `@@REMOVED
    <quoi> <chemin ou nom>`, chaque chose gardée `@@KEPT <chemin>`, une
    configuration remise `@@RESTORED <config> <copie>`, un échec `@@FAILED
    <étape>`. Dernière ligne `@@DONE yes` ; `@@DONE no` après un échec, ou
    `@@DONE partial` quand un service adopté sans copie d'origine reste
    configuré par l'outil (`@@BACKUP_MISSING`), avec un code non nul : l'état
    reste, et la relance reprend là où elle s'est arrêtée, chaque étape
    étant sans effet une fois faite. Le service gardé se défait à la relance
    qui suit la remise en place de sa configuration par l'administrateur.

    La base des comptes de ntfy n'est retirée, avec `remove_data`, que si
    l'outil a posé ntfy : celle d'un ntfy adopté porte les comptes et
    jetons d'avant lui ; seul le compte que l'installateur y a ajouté
    (`admin_added`) en part (`@@REMOVED account <nom>`). De même, la lignée
    de Let's Encrypt n'est retirée qu'avec `remove_data` ; gardée, elle est
    mise de côté (`@@HELD <fichier>`). Refusal `call_infra_state_version`
    ou `call_infra_state_invalid` pour un état qu'on ne peut pas suivre.
    `root` préfixe chaque chemin de l'hôte (tests).
    """
    if not _STAMP.match(stamp or ""):
        raise ValueError(f"stamp: {stamp!r}")
    head = [
        "set -u",
        f"R={shlex.quote(root)}",
        f'CALL="$R"{shlex.quote(CALL_DIR)}',
        f'STATE="$R"{shlex.quote(STATE_PATH)}',
        f'PENDING="$R"{shlex.quote(PENDING_DIR)}',
    ]
    if not isinstance(state, dict):
        return "\n".join(
            head
            + [
                "for s in " + " ".join(PENDING_NAMES) + "; do",
                '  if [ -f "$PENDING/$s.json" ]; then echo "@@PENDING $s"; fi',
                "done",
                'echo "@@NOTHING"',
                "",
            ]
        )
    if state.get("version") != STATE_VERSION:
        raise Refusal(
            "call_infra_state_version",
            found=state.get("version"),
            expected=STATE_VERSION,
        )
    records = _uninstall_records(state)
    prod = _production_records(state)
    record = state.get("firewall")
    kind = record.get("kind") if isinstance(record, dict) else None
    rules = rules_from_state(state)
    firewall = (
        firewall_script(kind, rules, "delete", root=root)
        if kind in FIREWALLS
        else ""
    )
    lines = head + [
        "umask 077",
        "OK=1",
        "KEPT=0",
        'failed() { echo "@@FAILED $1"; OK=0; }',
        'D=$(mktemp -d) || { echo "@@FAILED workdir"; echo "@@DONE no";'
        " exit 1; }",
        "trap 'rm -rf \"$D\"' EXIT",
        "trap 'exit 129' HUP INT TERM",
        *_uninstall_helpers(),
        f'for H in "$R"{shlex.quote(HOLD_PREFIX)}*; do',
        '  if [ -d "$H" ]; then held_back "$H"; fi',
        "done",
    ]
    if firewall:
        lines += [
            "# pare-feu",
            _decode_to(_b64(firewall), '"$D/firewall.sh"')
            + " || failed firewall",
            'sh "$D/firewall.sh" > "$D/firewall.out"; FRC=$?',
            "grep -v '^@@END$' \"$D/firewall.out\"",
            '[ "$FRC" = 0 ] || failed firewall',
        ]
    if prod["hook"] or prod["certbot"]:
        lines += _hook_lines()
    for svc, svc_record in records:
        lines += _service_uninstall_lines(svc, svc_record, remove_data, stamp)
    lines += _production_uninstall_lines(prod, remove_data)
    recorded = [svc for svc, _ in records]
    recorded += [name for name in ("nginx", "certbot") if prod[name]]
    others = [name for name in PENDING_NAMES if name not in recorded]
    tls = '"$CALL/tls"'
    # Un service gardé (KEPT) est encore configuré par l'outil : l'état,
    # ses fiches et `tls/`, que sa configuration nomme, restent.
    lines += [
        'if [ "$OK" = 1 ] && [ "$KEPT" = 0 ]; then',
        *[f'  rm -f "$PENDING/{svc}.json"' for svc in recorded],
        *[
            f'  if [ -f "$PENDING/{svc}.json" ]; then'
            f' echo "@@PENDING_LEFT {svc}"; fi'
            for svc in others
        ],
        '  rm -f "$PENDING/firewall"',
        '  rmdir "$PENDING" 2>/dev/null',
        '  for E in "$CALL"/*; do',
        '    case "${E##*/}" in',
        "      tls|pending|state.json|\\*) ;;",
        '      *) rm -rf "$E" || failed call-dir ;;',
        "    esac",
        "  done",
    ]
    if remove_data:
        lines.append(
            f"  if [ -e {tls} ]; then rm -rf {tls}"
            f' && echo "@@REMOVED tls {COTURN_TLS_DIR}" || failed tls; fi'
        )
    else:
        lines.append(
            f'  if [ -e {tls} ]; then echo "@@KEPT {COTURN_TLS_DIR}"; fi'
        )
    lines += [
        '  if [ "$OK" = 1 ]; then',
        '    rm -f "$STATE" && echo "@@REMOVED state" || failed state',
        "  fi",
        '  rmdir "$CALL" 2>/dev/null',
        "fi",
        'if [ "$OK" = 0 ]; then echo "@@DONE no"; exit 1; fi',
        'if [ "$KEPT" = 1 ]; then echo "@@DONE partial"; exit 1; fi',
        'echo "@@DONE yes"',
        "",
    ]
    return "\n".join(lines)
