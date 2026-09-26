#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Configurations nginx et PHP-FPM d'une instance Dolibarr de développement.

Rendu pur. En développement, les deux démons tournent sous le compte du
développeur, sur un port local de 127.0.0.1, et tout ce qu'ils écrivent
(pid, socket, journaux, fichiers temporaires, sessions) reste dans le
dossier run/ de l'instance : rien dans /etc, rien en root. Le fichier
mime.types et les paramètres fastcgi sont lus là où les quatre familles
de distributions les posent.

PATH_INFO, dont l'API REST de Dolibarr a besoin, est capturé AVANT
try_files : try_files le viderait. Le PHP de /conf/ et /includes/ n'est
jamais exécuté.
"""

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
