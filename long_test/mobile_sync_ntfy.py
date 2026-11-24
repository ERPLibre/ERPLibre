#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le ntfy jetable d'une course des tests de synchronisation mobile.

Les notifications du clavardage app fermée passent par un vrai ntfy : Odoo
y publie les poussées chiffrées, l'app (son côté natif, ou sa doublure Node
du kit de test) les lit. La course démarre le sien, `ntfy serve` sur
127.0.0.1 et un port libre, avec un `server.yml`, un fichier d'accès et un
cache sous `<course>/ntfy/`, et l'arrête à la fin (gardé avec les serveurs
par --garder). L'accès du téléphone se crée comme le menu de `todo.py` le
crée (`ntfy_mobile.access_script`) : anonyme en écriture seule sur `up*`,
un utilisateur en lecture seule sur son préfixe, son jeton.

Chaque appel de la CLI porte `--config` : sans lui elle lit
`/etc/ntfy/server.yml`, celui de l'utilisateur, que rien ici ne nomme. Et
chacun tourne sans les variables `NTFY_*` de l'appelant, que la CLI fait
passer avant `--config` (`ntfy_mobile.ntfy_free_env`).
"""

import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "script" / "todo"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import mobile_sync_odoo as odoo  # noqa: E402
import ntfy_mobile  # noqa: E402

UTILISATEUR = "erm_course"
# Un second téléphone sur le même ntfy : son préfixe sert aux tests qui
# déplacent un compte vers un nouveau lien, ou qui vérifient qu'un jeton
# ne lit que le sien
UTILISATEUR_AUTRE = "erm_course_autre"
DUREE_CACHE = "12h"


@dataclass
class Acces:
    """L'accès d'un téléphone au ntfy : son jeton, son préfixe et le lien de
    configuration qui les porte."""

    token: str
    prefix: str
    link: str


@dataclass
class Ntfy:
    """Le ntfy d'une course : son url, sa configuration, l'accès du
    téléphone (jeton, préfixe, lien) et celui d'un second téléphone
    (autre). Les liens donnent la même url côté Odoo : tout tourne sur
    127.0.0.1."""

    url: str
    port: int
    config: Path
    token: str
    prefix: str
    link: str
    processus: subprocess.Popen = field(repr=False, default=None)
    autre: Acces = None


def ntfy_disponible(which=shutil.which):
    """Vrai quand la commande ntfy est installée."""
    return bool(which("ntfy"))


def config_ntfy(dossier, port):
    """Le server.yml d'un ntfy jetable : écoute sur 127.0.0.1:port seul,
    accès refusé par défaut, cache de 12 h, fichiers sous dossier ; 127.0.0.1
    exempté des limites de requêtes, d'où Odoo et les tests publient et
    lisent sans relâche."""
    dossier = Path(dossier)
    return "\n".join(
        [
            f'listen-http: "127.0.0.1:{port}"',
            f'base-url: "http://127.0.0.1:{port}"',
            f'cache-file: "{dossier / "cache.db"}"',
            f'cache-duration: "{DUREE_CACHE}"',
            f'auth-file: "{dossier / "user.db"}"',
            'auth-default-access: "deny-all"',
            'visitor-request-limit-exempt-hosts: "127.0.0.1"',
            "",
        ]
    )


def sante_ntfy(url, delai=2):
    """Vrai quand /v1/health du serveur répond healthy."""
    try:
        with urllib.request.urlopen(f"{url}/v1/health", timeout=delai) as r:
            return b'"healthy":true' in r.read().replace(b" ", b"")
    except (urllib.error.URLError, OSError, ValueError):
        return False


def demarrer_ntfy(
    repertoire,
    lancer=subprocess.Popen,
    executer=subprocess.run,
    sain=sante_ntfy,
    attente=30,
):
    """Démarre le ntfy de la course sous repertoire/ntfy/, attend qu'il
    réponde, puis crée l'accès de deux téléphones (creer_acces).
    RuntimeError, le serveur arrêté, quand l'une des étapes échoue ; une
    interruption (Ctrl-C, SIGTERM changé en KeyboardInterrupt par la
    course) l'arrête aussi avant de remonter : lancé dans sa propre
    session et pas encore noté avec les serveurs, il survivrait sinon."""
    dossier = Path(repertoire) / "ntfy"
    dossier.mkdir(parents=True, exist_ok=True)
    port = odoo.port_libre()
    config = dossier / "server.yml"
    config.write_text(config_ntfy(dossier, port))
    ntfy = Ntfy(f"http://127.0.0.1:{port}", port, config, "", "", "")
    ntfy.processus = lancer(
        ["ntfy", "serve", "--config", str(config)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        env=ntfy_mobile.ntfy_free_env(),
    )
    try:
        fin = time.monotonic() + attente
        while not sain(ntfy.url):
            if ntfy.processus.poll() is not None or time.monotonic() > fin:
                raise RuntimeError(f"ntfy ne répond pas sur {ntfy.url}")
            time.sleep(0.2)
        premier = creer_acces(ntfy, UTILISATEUR, executer)
        ntfy.autre = creer_acces(ntfy, UTILISATEUR_AUTRE, executer)
    except BaseException:
        arreter_ntfy(ntfy)
        raise
    ntfy.token, ntfy.prefix, ntfy.link = (
        premier.token,
        premier.prefix,
        premier.link,
    )
    return ntfy


def creer_acces(ntfy, utilisateur, executer=subprocess.run):
    """L'accès d'un téléphone sur un nouveau préfixe : access_script exécuté
    sous l'utilisateur courant (LocalHost(sudo=())), sa sortie capturée,
    le jeton n'étant pas affiché. RuntimeError sans jeton."""
    prefixe = ntfy_mobile.random_prefix()
    script = ntfy_mobile.access_script(str(ntfy.config), utilisateur, prefixe)
    resultat = executer(
        ntfy_mobile.LocalHost(sudo=()).argv(script, None),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
        env=ntfy_mobile.ntfy_free_env(),
    )
    jeton = ntfy_mobile.parse_token(resultat.stdout or "")
    if resultat.returncode != 0 or not jeton:
        raise RuntimeError(
            f"accès ntfy de {utilisateur} non créé (code {resultat.returncode})"
        )
    lien = ntfy_mobile.build_link(
        ntfy.url,
        jeton,
        prefixe,
        ntfy_mobile.cache_seconds({"cache-duration": DUREE_CACHE}),
        odoo_url=ntfy.url,
    )
    return Acces(jeton, prefixe, lien)


def arreter_ntfy(ntfy, delai=10):
    """SIGTERM au groupe du ntfy, puis SIGKILL s'il traîne."""
    processus = ntfy.processus
    if processus is None or processus.poll() is not None:
        return
    try:
        os.killpg(processus.pid, signal.SIGTERM)
        processus.wait(timeout=delai)
    except subprocess.TimeoutExpired:
        os.killpg(processus.pid, signal.SIGKILL)
        processus.wait()
    except ProcessLookupError:
        pass
