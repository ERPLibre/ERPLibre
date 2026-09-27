#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Configurations nginx et PHP-FPM d'une instance Dolibarr.

Rendu pur. En développement, les deux démons tournent sous le compte du
développeur, sur un port local de 127.0.0.1, et tout ce qu'ils écrivent
(pid, socket, journaux, fichiers temporaires, sessions) reste dans le
dossier run/ de l'instance : rien dans /etc, rien en root. Le fichier
mime.types et les paramètres fastcgi sont lus là où les quatre familles
de distributions les posent.

En production, le pool tourne sous le compte système de l'instance et
l'hôte virtuel s'insère dans le nginx de la distribution : voir
render_prod_fpm et render_prod_nginx.

PATH_INFO, dont l'API REST de Dolibarr a besoin, est capturé AVANT
try_files : try_files le viderait. Le PHP de /conf/ et /includes/ n'est
jamais exécuté.
"""

import re

MIME_TYPES = "/etc/nginx/mime.types"
FASTCGI_PARAMS = "/etc/nginx/fastcgi_params"

_TMP = ("client", "fastcgi", "proxy", "uwsgi", "scgi")


def run_dirs(run):
    """Dossiers à créer avant de lancer nginx et PHP-FPM, dans l'ordre."""
    return [run, f"{run}/sessions"] + [f"{run}/tmp/{d}" for d in _TMP]


def render_dev_fpm(run):
    """php-fpm.conf d'une instance de développement, maître non root.

    Sans directive user : un maître qui ne tourne pas en root ne peut pas
    changer de compte, et le pool tourne sous celui qui le lance.
    """
    return f"""[global]
pid = {run}/php-fpm.pid
error_log = {run}/php-fpm.log
daemonize = no

[dolibarr]
listen = {run}/php-fpm.sock
listen.mode = 0600
pm = ondemand
pm.max_children = 5
catch_workers_output = yes
php_admin_value[session.save_path] = {run}/sessions
php_admin_value[upload_max_filesize] = 64M
php_admin_value[post_max_size] = 64M
php_admin_value[memory_limit] = 256M
"""


def render_dev_nginx(run, htdocs, port):
    """nginx.conf complet d'une instance de développement sur `port`."""
    port = int(port)
    if not 1024 <= port <= 65535:
        raise ValueError(f"port {port} is privileged or out of range")
    temp = "\n".join(
        f"    {d}_temp_path {run}/tmp/{d};" for d in ("proxy", "uwsgi", "scgi")
    )
    return f"""worker_processes 1;
pid {run}/nginx.pid;
error_log {run}/nginx-error.log;

events {{
    worker_connections 256;
}}

http {{
    include {MIME_TYPES};
    default_type application/octet-stream;
    access_log {run}/nginx-access.log;
    client_body_temp_path {run}/tmp/client;
    fastcgi_temp_path {run}/tmp/fastcgi;
{temp}
    client_max_body_size 64M;

    server {{
        listen 127.0.0.1:{port};
        root {htdocs};
        index index.php index.html;

        location ~ ^/(conf|includes)/.*\\.php$ {{
            deny all;
        }}

        location ~ [^/]\\.php(/|$) {{
            fastcgi_split_path_info ^(.+?\\.php)(/.*)$;
            set $path_info $fastcgi_path_info;
            try_files $fastcgi_script_name =404;
            include {FASTCGI_PARAMS};
            fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
            fastcgi_param PATH_INFO $path_info;
            fastcgi_param HTTP_PROXY "";
            fastcgi_read_timeout 600;
            fastcgi_pass unix:{run}/php-fpm.sock;
        }}
    }}
}}
"""


# ---------------------------------------------------------------------------
# Production : pool PHP-FPM système et hôte virtuel nginx
# ---------------------------------------------------------------------------

# Un nom d'hôte ou une adresse IPv4 : il entre tel quel dans server_name,
# où un espace, un « ; » ou un saut de ligne changerait la configuration ;
# fullmatch, car « $ » laisserait passer un saut de ligne final.
_DOMAIN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?")

TLS_MODES = ("none", "local", "certbot")


def valid_domain(domain):
    """Vrai si `domain` peut entrer tel quel dans server_name."""
    return bool(_DOMAIN.fullmatch(domain or ""))


def render_prod_fpm(instance, user, web_user, socket, code_root, data_root):
    """Pool PHP-FPM d'une instance de production.

    Il tourne sous le compte système de l'instance ; seul le compte de
    nginx lit sa socket. PHP est confiné au code, aux données et à /tmp.
    """
    return f"""[erplibre-dolibarr-{instance}]
user = {user}
group = {user}
listen = {socket}
listen.owner = {web_user}
listen.group = {web_user}
listen.mode = 0660
pm = ondemand
pm.max_children = 10
pm.process_idle_timeout = 60s
catch_workers_output = yes
php_admin_value[open_basedir] = {code_root}/:{data_root}/:/tmp/
php_admin_value[session.save_path] = {data_root}/sessions
php_admin_value[upload_max_filesize] = 64M
php_admin_value[post_max_size] = 64M
php_admin_value[memory_limit] = 256M
php_admin_flag[display_errors] = off
"""


def _prod_app(instance, htdocs, socket):
    """Ce qu'un serveur nginx de production sert : la même mécanique que
    le développement, plus le refus de /install/ et des fichiers cachés.

    getUserRemoteIP() de Dolibarr croit X-Forwarded-For, Client-IP puis
    CF-Connecting-IP avant REMOTE_ADDR : ces en-têtes arrivent vides, un
    fastcgi_param HTTP_* remplaçant celui que le client enverrait."""
    return f"""        root {htdocs};
        index index.php;
        client_max_body_size 64M;
        access_log /var/log/nginx/erplibre-dolibarr-{instance}.access.log;
        error_log /var/log/nginx/erplibre-dolibarr-{instance}.error.log;
        add_header X-Content-Type-Options nosniff always;
        add_header X-Frame-Options SAMEORIGIN always;

        location ^~ /install/ {{
            deny all;
        }}

        location ~ /\\. {{
            deny all;
        }}

        location ~ ^/(conf|includes)/.*\\.php$ {{
            deny all;
        }}

        location ~ [^/]\\.php(/|$) {{
            fastcgi_split_path_info ^(.+?\\.php)(/.*)$;
            set $path_info $fastcgi_path_info;
            try_files $fastcgi_script_name =404;
            include {FASTCGI_PARAMS};
            fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
            fastcgi_param PATH_INFO $path_info;
            fastcgi_param HTTP_PROXY "";
            fastcgi_param HTTP_X_FORWARDED_FOR "";
            fastcgi_param HTTP_CLIENT_IP "";
            fastcgi_param HTTP_CF_CONNECTING_IP "";
            fastcgi_read_timeout 600;
            fastcgi_hide_header X-Powered-By;
            fastcgi_pass unix:{socket};
        }}
"""


def render_prod_nginx(
    instance, htdocs, domain, socket, tls, cert=None, key=None
):
    """Hôte virtuel nginx d'une instance de production.

    tls « none » sert l'application en HTTP ; « local » redirige 80 vers
    443 et sert avec `cert` et `key` (l'autorité locale d'ERPLibre) ;
    « certbot » part du HTTP, que certbot --nginx réécrit lui-même en y
    ajoutant le bloc 443 et la redirection.

    Chaque bloc ferme la connexion (444) sur un autre nom que `domain`.
    nginx confie à un bloc les requêtes qu'aucun server_name ne prend dès
    qu'il est le premier déclaré sur son port : selon l'ordre d'inclusion
    de la distribution, en IPv6 où son serveur n'écoute pas, et sur 443 où
    il n'y en a aucun. La garde tient sans dépendre de cet ordre, et
    certbot la garde en greffant son 443 sur le même bloc. Une requête
    HTTP/1.0 sans en-tête Host passe : $host y vaut le server_name.
    """
    return _site(
        instance, domain, tls, cert, key, _prod_app(instance, htdocs, socket)
    )


def _proxy_app(instance, port):
    """Ce que sert le bloc final devant un conteneur : son Apache publié sur
    127.0.0.1:`port`, avec l'adresse du client et le schéma d'origine.

    X-Forwarded-For est ÉCRASÉ par l'adresse vue par nginx : Dolibarr en
    prend la première, que $proxy_add_x_forwarded_for laisserait au
    client. X-Forwarded-Proto rend isHTTPS() vrai : cookie de session
    marqué Secure, sans $dolibarr_main_force_https, qui bouclerait."""
    return f"""        client_max_body_size 64M;
        access_log /var/log/nginx/erplibre-dolibarr-{instance}.access.log;
        error_log /var/log/nginx/erplibre-dolibarr-{instance}.error.log;

        location ^~ /install/ {{
            deny all;
        }}

        location ~ /\\. {{
            deny all;
        }}

        location / {{
            proxy_pass http://127.0.0.1:{port};
            proxy_set_header Host $host;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $remote_addr;
            proxy_set_header Client-IP "";
            proxy_set_header CF-Connecting-IP "";
            proxy_read_timeout 600;
        }}
"""


def render_prod_proxy(instance, domain, port, tls, cert=None, key=None):
    """Hôte virtuel nginx devant le site d'une instance en conteneur.

    Mêmes écoutes, même garde et mêmes modes TLS que render_prod_nginx ;
    seul change ce que sert le bloc final.
    """
    if not 1024 <= port <= 65535:
        raise ValueError(f"port {port} is privileged or out of range")
    return _site(instance, domain, tls, cert, key, _proxy_app(instance, port))


def _site(instance, domain, tls, cert, key, app):
    """Les blocs server d'un site de production ; `app` est ce que sert le
    bloc qui répond (HTTP pour none et certbot, 443 pour local)."""
    if tls not in TLS_MODES:
        raise ValueError(f"unknown TLS mode {tls!r}")
    if not valid_domain(domain):
        raise ValueError(f"invalid domain {domain!r}")
    # $host arrive en minuscules.
    domain = domain.lower()
    head = f"# ERPLibre — Dolibarr, instance {instance}\n"
    guard = f"""        server_name {domain};
        if ($host != "{domain}") {{
            return 444;
        }}
"""
    if tls in ("none", "certbot"):
        return f"""{head}server {{
        listen 80;
        listen [::]:80;
{guard}{app}}}
"""
    if not (cert and key):
        raise ValueError("local TLS needs a certificate and a key")
    return f"""{head}server {{
        listen 80;
        listen [::]:80;
{guard}        location / {{
            return 301 https://{domain}$request_uri;
        }}
}}

server {{
        listen 443 ssl;
        listen [::]:443 ssl;
{guard}        ssl_certificate {cert};
        ssl_certificate_key {key};
{app}}}
"""
