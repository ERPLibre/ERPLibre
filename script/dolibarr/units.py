#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Unités systemd des tâches planifiées d'une instance Dolibarr de production.

Rendu pur. Dolibarr ne lance pas ses tâches lui-même :
scripts/cron/cron_run_jobs.php doit être appelé de l'extérieur, toutes les
5 minutes, avec la clé CRON_KEY et un identifiant (« firstadmin » prend le
premier administrateur). Un service oneshot, sous le compte de l'instance
et confiné à ses données, le lance ; une minuterie le déclenche et rattrape
un passage manqué.

La clé vient d'un fichier d'environnement 0600 lu par systemd. Le script
amont ne l'accepte qu'en argument : pendant l'exécution, elle reste
visible dans la liste des processus de la machine.
"""

import re

# La clé entre dans un fichier KEY=valeur et dans une ligne ExecStart :
# rien qu'un de ces deux formats interpréterait.
_KEY = re.compile(r"[A-Za-z0-9]+")


def cron_unit_names(instance):
    base = f"erplibre-dolibarr-cron-{instance}"
    return f"{base}.service", f"{base}.timer"


def render_cron_service(instance, user, code_root, data_root, env_file):
    script = f"{code_root}/scripts/cron/cron_run_jobs.php"
    return f"""[Unit]
Description=Dolibarr scheduled jobs, instance {instance} (ERPLibre)
After=network.target

[Service]
Type=oneshot
User={user}
Group={user}
EnvironmentFile={env_file}
ExecStart=/usr/bin/php {script} ${{CRON_KEY}} firstadmin
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
ReadWritePaths={data_root}
"""


def render_cron_timer(instance):
    service, _timer = cron_unit_names(instance)
    return f"""[Unit]
Description=Dolibarr scheduled jobs every 5 minutes, instance {instance}

[Timer]
OnCalendar=*:0/5
Persistent=true
Unit={service}

[Install]
WantedBy=timers.target
"""


def render_cron_env(key):
    if not _KEY.fullmatch(key or ""):
        raise ValueError("the cron key holds characters outside [A-Za-z0-9]")
    return f"CRON_KEY={key}\n"
