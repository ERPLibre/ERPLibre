#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les Odoo des tests de synchronisation mobile : versions, gabarits, bases,
serveurs.

Chaque version installée dans le checkout (odoo16.0/, odoo17.0/, odoo18.0/)
a son GABARIT : une base `mobile_sync_tpl_<v>` avec project, crm, account et
calendar, sans données de démonstration, un plan comptable, le fuseau de
l'administrateur, une seconde société et l'utilisateur `mc_user` des deux
sociétés. Il se construit une fois et se garde : sa clé (révision d'Odoo,
modules, post-installation) est écrite dans le COMMENT de la base, et un
gabarit dont la clé diffère se reconstruit. La construction se fait sous un
nom temporaire, renommé à la fin : un gabarit interrompu n'est jamais pris
pour un gabarit prêt.

Chaque course copie les gabarits (createdb -T, filestore compris, nouvel
uuid) en bases `mobile_sync_run_<pid>_<horodatage>_<v>`, et démarre un serveur
par base sur des ports libres, sans worker ni cron, filtré sur sa base. Le
balayage supprime les bases et répertoires des courses dont le processus est
mort.

Aucun import d'Odoo : tout passe par odoo-bin, psql et les commandes
PostgreSQL, ce qui laisse ce module importable par les tests unitaires.
"""

import fcntl
import getpass
import hashlib
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
MOBILE = RACINE / "mobile" / "erplibre_home_mobile"
CACHE = RACINE / "cache" / "mobile_sync"
VERSIONS = (16, 17, 18)
MODULES = ("project", "crm", "account", "calendar")
# Sans démo, le plan comptable générique est un module à part en 16 ; en 17
# et 18, account le porte et la post-installation le charge.
# Le module de chat vit dans le dépôt d'addons d'ERPLibre, présent sur le
# chemin d'addons de la 18 seulement.
MODULES_EN_PLUS = {
    16: ("l10n_generic_coa",),
    18: ("erplibre_mobile_chat",),
}
DEPOT_ADDONS_ERPLIBRE = "ERPLibre_erplibre_addons"
MODULE_CHAT = "erplibre_mobile_chat"
HARNESS_API = 4
NODE_MINIMUM = 22
# Le fuseau de l'administrateur des bases ET des tests : une date d'Odoo 16
# (Date) se lit en jour local, et un écart des deux ferait glisser les jours.
FUSEAU = "America/Montreal"
PREFIXE_GABARIT = "mobile_sync_tpl_"
PREFIXE_COURSE = "mobile_sync_run_"
# PostgreSQL limite un nom de base à 63 octets.
LONGUEUR_NOM_MAX = 63

# La post-installation, lancée dans « odoo-bin shell » sur la base du
# gabarit. Elle figure dans la clé : la changer reconstruit les gabarits.
POST_INSTALLATION = """
societe = env.company
if not env["account.journal"].search(
    [("type", "=", "sale"), ("company_id", "=", societe.id)], limit=1
):
    if "account.chart.template" in env and hasattr(
        env["account.chart.template"], "try_loading"
    ) and VERSION >= 17:
        env["account.chart.template"].try_loading("generic_coa", societe)
    else:
        env.ref("l10n_generic_coa.configurable_chart_template").try_loading(
            company=societe
        )
# L'administrateur, pas env.user : odoo-bin shell agit en superutilisateur
env.ref("base.user_admin").tz = FUSEAU
seconde = env["res.company"].create({"name": "MS Seconde societe"})
# L'admin des vérifications voit aussi la seconde société. L'y ajouter
# pendant la course laisse, sur un serveur à threads, des requêtes
# concurrentes avec l'ancienne liste en cache : appels refusés.
env.ref("base.user_admin").company_ids = [(4, seconde.id)]
groupes = [
    env.ref(xmlid).id
    for xmlid in (
        "base.group_user",
        "project.group_project_user",
        "sales_team.group_sale_salesman",
        "account.group_account_invoice",
    )
]
env["res.users"].create(
    {
        "name": "MS Multi societe",
        "login": "mc_user",
        "password": "mc_user",
        "tz": FUSEAU,
        "company_id": societe.id,
        "company_ids": [(6, 0, [societe.id, seconde.id])],
        "groups_id": [(6, 0, groupes)],
    }
)
# Les réglages de chaque utilisateur interne existent d'avance : créés à la
# demande (authentification, chat), deux requêtes simultanées qui les
# créent toutes deux butent sur l'unicité de res.users.settings. Le modèle
# et _find_or_create_for_user sont dans mail en 16, dans base en 17 et 18.
for interne in env["res.users"].search([("share", "=", False)]):
    env["res.users.settings"]._find_or_create_for_user(interne)
env.cr.commit()
"""


# La partie du chat, ajoutée pour la 18 seulement : les clés des gabarits de
# la 16 et de la 17 ne la voient pas.
POST_INSTALLATION_CHAT = """
# Le second utilisateur du chat et un canal de groupe où il parle avec
# l'administrateur. Le gabarit se construit une fois et les courses le
# copient : la création est idempotente.
admin = env.ref("base.user_admin")
utilisateur = env["res.users"].search([("login", "=", "chat_user")])
if not utilisateur:
    utilisateur = env["res.users"].create(
        {
            "name": "MS Chat",
            "login": "chat_user",
            "password": "chat_user",
            "tz": FUSEAU,
            "groups_id": [(6, 0, [env.ref("base.group_user").id])],
        }
    )
attendus = {admin.partner_id.id, utilisateur.partner_id.id}
# Créé par l'administrateur : create() ajoute l'utilisateur courant, qui
# serait sinon le superutilisateur du shell. Aucun message « a rejoint »
# n'est posté : chat_user démarre sans non-lu.
canal = env["discuss.channel"].search(
    [("name", "=", "ms chat"), ("channel_type", "=", "group")], limit=1
)
if not canal:
    canal = (
        env["discuss.channel"]
        .with_user(admin)
        .create(
            {
                "name": "ms chat",
                "channel_type": "group",
                "channel_partner_ids": [(4, utilisateur.partner_id.id)],
            }
        )
        .sudo()
    )
canal.sudo().add_members(
    partner_ids=list(attendus), post_joined_message=False
)
canal.sudo().channel_member_ids.filtered(
    lambda m: m.partner_id.id not in attendus
).unlink()
presents = set(canal.sudo().channel_member_ids.mapped("partner_id").ids)
if presents != attendus:
    raise Exception("membres du canal ms chat : %s != %s" % (presents, attendus))
# chat_user arrive après les réglages du commun : les siens d'avance aussi
env["res.users.settings"]._find_or_create_for_user(utilisateur)
env.cr.commit()
"""


class PrerequisManquant(Exception):
    """Un prérequis absent : le message dit quoi faire."""


@dataclass
class VersionOdoo:
    """Une version d'Odoo du checkout : son odoo-bin, son python, ses addons."""

    version: int
    odoo_bin: Path
    python: Path

    @property
    def addons_path(self):
        base = self.odoo_bin.parent
        chemins = [str(base / "addons"), str(base / "odoo" / "addons")]
        if self.version >= 18:
            chemins.append(str(self.addons_erplibre))
        return ",".join(chemins)

    @property
    def addons_erplibre(self):
        """Le dépôt d'addons d'ERPLibre de cette version."""
        return self.odoo_bin.parent.parent / "addons" / DEPOT_ADDONS_ERPLIBRE

    @property
    def gabarit(self):
        return f"{PREFIXE_GABARIT}{self.version}"

    @property
    def modules(self):
        return MODULES + MODULES_EN_PLUS.get(self.version, ())


@dataclass
class Serveur:
    """Un serveur démarré pour une course : sa base, ses ports, son processus."""

    version: int
    base: str
    port: int
    config: Path
    journal: Path
    processus: subprocess.Popen = field(repr=False, default=None)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"


# ─── Prérequis ────────────────────────────────────────────────────────────


def verifier_mobile(mobile=MOBILE, executer=subprocess.run):
    """Les problèmes du dépôt mobile, chacun avec sa correction ; vide s'il
    est prêt : présent, le bon paquet, Node assez récent, dépendances
    installées, kit de test à l'API attendue."""
    problemes = []
    if not (mobile / "package.json").is_file():
        return [
            "mobile/erplibre_home_mobile absent :"
            " ./mobile/install_mobile_dev.sh"
        ]
    try:
        nom = json.loads((mobile / "package.json").read_text())["name"]
    except (ValueError, KeyError):
        nom = None
    if nom != "erplibre-mobile":
        problemes.append(
            f"mobile/erplibre_home_mobile/package.json nomme {nom!r},"
            " pas erplibre-mobile : ce n'est pas le dépôt de l'application"
        )
    try:
        sortie = executer(
            ["node", "--version"], capture_output=True, text=True, check=False
        ).stdout.strip()
        majeure = int(sortie.lstrip("v").split(".")[0])
    except (OSError, ValueError):
        majeure = None
    if majeure is None or majeure < NODE_MINIMUM:
        problemes.append(
            f"Node {NODE_MINIMUM} ou plus requis (trouvé : {majeure or 'aucun'})"
        )
    if not (mobile / "node_modules" / ".bin" / "vitest").exists():
        problemes.append(
            "dépendances du mobile absentes :"
            " cd mobile/erplibre_home_mobile && npm ci"
        )
    kit = mobile / "src" / "testing" / "syncTestKit.ts"
    trouve = re.search(
        r"export const HARNESS_API = (\d+);",
        kit.read_text() if kit.is_file() else "",
    )
    if not trouve:
        problemes.append(
            "kit de test absent du dépôt mobile (src/testing/syncTestKit.ts) :"
            " mettre le dépôt à jour (repo sync, ou git pull)"
        )
    elif int(trouve.group(1)) != HARNESS_API:
        problemes.append(
            f"kit de test à l'API {trouve.group(1)}, ces tests attendent"
            f" l'API {HARNESS_API} : mettre à jour celui qui retarde"
        )
    return problemes


def versions_installees(racine=RACINE, demandees=VERSIONS):
    """Les versions demandées présentes dans le checkout, par version ; lève
    PrerequisManquant pour une version demandée absente ou dont le venv est
    introuvable ou ambigu."""
    trouvees = {}
    for version in demandees:
        odoo_bin = racine / f"odoo{version}.0" / "odoo" / "odoo-bin"
        if not odoo_bin.is_file():
            raise PrerequisManquant(
                f"Odoo {version} absent du checkout ({odoo_bin.relative_to(racine)})"
            )
        venvs = sorted(racine.glob(f".venv.odoo{version}.0_*"))
        if len(venvs) != 1:
            raise PrerequisManquant(
                f"Odoo {version} : {len(venvs)} venv .venv.odoo{version}.0_*"
                " au lieu d'un"
            )
        trouvees[version] = VersionOdoo(
            version, odoo_bin, venvs[0] / "bin" / "python"
        )
    return trouvees


def lire_versions(texte):
    """Les versions de « --versions 16,18 », dans l'ordre, sans doublon ;
    ValueError pour une version hors de VERSIONS."""
    versions = []
    for morceau in texte.split(","):
        morceau = morceau.strip()
        if not morceau:
            continue
        if not morceau.isdigit() or int(morceau) not in VERSIONS:
            raise ValueError(
                f"version {morceau!r} : attendu parmi"
                f" {', '.join(map(str, VERSIONS))}"
            )
        if int(morceau) not in versions:
            versions.append(int(morceau))
    if not versions:
        raise ValueError("aucune version demandée")
    return versions


# ─── PostgreSQL ───────────────────────────────────────────────────────────


def psql(requete, base="postgres", executer=subprocess.run):
    """Une requête psql, sa sortie en texte brut (-At), ou lève."""
    resultat = executer(
        ["psql", "-X", "-d", base, "-Atc", requete],
        capture_output=True,
        text=True,
        check=False,
    )
    if resultat.returncode != 0:
        raise RuntimeError(f"psql : {resultat.stderr.strip()}")
    return resultat.stdout.strip()


def bases_existantes(executer=subprocess.run):
    return set(
        psql(
            "SELECT datname FROM pg_database WHERE datname LIKE 'mobile_sync_%'",
            executer=executer,
        ).split()
    )


def nom_course(pid, horodatage, version):
    """Le nom de la base d'une course, valide pour PostgreSQL."""
    nom = f"{PREFIXE_COURSE}{pid}_{horodatage}_{version}"
    if len(nom) > LONGUEUR_NOM_MAX or not re.fullmatch(r"[a-z0-9_]+", nom):
        raise ValueError(f"nom de base invalide : {nom}")
    return nom


def pid_de_course(nom):
    """Le pid du processus qui a créé cette base, de course ou de gabarit en
    construction, ou None pour un gabarit construit."""
    trouve = re.fullmatch(
        rf"{PREFIXE_COURSE}(\d+)_\d+_\d+|{PREFIXE_GABARIT}\d+_build_(\d+)", nom
    )
    return int(trouve.group(1) or trouve.group(2)) if trouve else None


def processus_vivant(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def a_balayer(bases, vivant=processus_vivant):
    """Les bases de course dont le processus est mort : les autres
    appartiennent à une course en cours, sur cette machine."""
    return sorted(
        nom
        for nom in bases
        if pid_de_course(nom) is not None and not vivant(pid_de_course(nom))
    )


def supprimer_base(nom, executer=subprocess.run):
    executer(
        ["dropdb", "--if-exists", "--force", nom],
        capture_output=True,
        text=True,
        check=False,
    )
    shutil.rmtree(CACHE / "data" / "filestore" / nom, ignore_errors=True)


# ─── Gabarits ─────────────────────────────────────────────────────────────


def _revision(depot, executer):
    """La révision HEAD du dépôt git `depot`."""
    return executer(
        ["git", "-C", str(depot), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()


def _empreinte_dossier(dossier):
    """Chemins triés et contenus d'un dossier : change dès qu'un fichier
    change, y compris non commité. "" si le dossier n'existe pas."""
    condense = hashlib.sha256()
    for fichier in sorted(Path(dossier).rglob("*")):
        if fichier.is_file() and "__pycache__" not in fichier.parts:
            condense.update(str(fichier.relative_to(dossier)).encode())
            condense.update(fichier.read_bytes())
    return condense.hexdigest()


def post_installation(version):
    """Le script de post-installation de la version : le commun, puis le
    chat à partir de la 18."""
    if version >= 18:
        return POST_INSTALLATION + POST_INSTALLATION_CHAT
    return POST_INSTALLATION


def cle_gabarit(version_odoo, executer=subprocess.run):
    """La clé d'un gabarit : révision d'Odoo, modules, post-installation.
    Une seule de ces trois qui change, et le gabarit se reconstruit. En 18,
    la révision du dépôt d'addons d'ERPLibre et le contenu du module de chat
    en font partie."""
    revision = _revision(version_odoo.odoo_bin.parent, executer)
    if version_odoo.version >= 18:
        revision += "\n" + _revision(version_odoo.addons_erplibre, executer)
        revision += "\n" + _empreinte_dossier(
            version_odoo.addons_erplibre / MODULE_CHAT
        )
    empreinte = hashlib.sha256(
        "\n".join(
            [
                revision,
                ",".join(version_odoo.modules),
                post_installation(version_odoo.version),
                FUSEAU,
            ]
        ).encode()
    ).hexdigest()[:16]
    return f"mobile_sync:{version_odoo.version}:{empreinte}"


def cle_posee(nom, executer=subprocess.run):
    """La clé écrite sur la base `nom`, ou "" si la base n'en a pas."""
    return psql(
        "SELECT coalesce(shobj_description(oid, 'pg_database'), '')"
        f" FROM pg_database WHERE datname = '{nom}'",
        executer=executer,
    )


def config_odoo(version_odoo, base, port, port_gevent, repertoire):
    """Le fichier de configuration d'un serveur de test : un seul processus
    sans cron (rien ne touche les données des tests dans leur dos), sur
    127.0.0.1, sa base seule, le cœur d'Odoo seul dans l'addons_path."""
    return "\n".join(
        [
            "[options]",
            "admin_passwd = admin",
            f"db_user = {getpass.getuser()}",
            "db_host = False",
            "db_port = False",
            f"addons_path = {version_odoo.addons_path}",
            "http_interface = 127.0.0.1",
            f"http_port = {port}",
            f"gevent_port = {port_gevent}",
            f"longpolling_port = {port_gevent}",
            "workers = 0",
            "max_cron_threads = 0",
            "list_db = False",
            f"dbfilter = ^{base}$",
            f"db_name = {base}",
            f"data_dir = {CACHE / 'data'}",
            f"logfile = {repertoire / f'odoo{version_odoo.version}.log'}",
            "log_level = warn",
            "",
        ]
    )


def construire_gabarit(version_odoo, executer=subprocess.run, journal=print):
    """Construit le gabarit d'une version, sous verrou : modules sans démo,
    post-installation, clé, renommage. Sans effet s'il est à jour ; rend
    s'il l'a construit. Une construction qui échoue ne laisse pas sa base."""
    CACHE.mkdir(parents=True, exist_ok=True)
    cle = cle_gabarit(version_odoo, executer)
    with open(CACHE / f"gabarit_{version_odoo.version}.lock", "w") as verrou:
        fcntl.flock(verrou, fcntl.LOCK_EX)
        if (
            version_odoo.gabarit in bases_existantes(executer)
            and cle_posee(version_odoo.gabarit, executer) == cle
        ):
            return False
        temporaire = f"{version_odoo.gabarit}_build_{os.getpid()}"
        supprimer_base(temporaire, executer)
        journal(f"Odoo {version_odoo.version} : gabarit en construction")
        try:
            _installer_gabarit(version_odoo, temporaire, executer)
        except BaseException:
            supprimer_base(temporaire, executer)
            raise
        supprimer_base(version_odoo.gabarit, executer)
        psql(
            f'ALTER DATABASE "{temporaire}" RENAME TO "{version_odoo.gabarit}"',
            executer=executer,
        )
        filestore = CACHE / "data" / "filestore"
        if (filestore / temporaire).exists():
            (filestore / temporaire).rename(filestore / version_odoo.gabarit)
        psql(
            f"COMMENT ON DATABASE \"{version_odoo.gabarit}\" IS '{cle}'",
            executer=executer,
        )
        # Personne ne s'y connecte plus : la copie d'une base ouverte échoue
        psql(
            f'ALTER DATABASE "{version_odoo.gabarit}" ALLOW_CONNECTIONS false',
            executer=executer,
        )
        return True


def _installer_gabarit(version_odoo, base, executer):
    """Installe les modules sans démo dans `base`, puis la post-installation
    par odoo-bin shell ; lève en nommant le journal ou la trace."""
    repertoire = CACHE / f"build_{version_odoo.version}"
    repertoire.mkdir(parents=True, exist_ok=True)
    config = repertoire / "odoo.conf"
    config.write_text(
        config_odoo(version_odoo, base, port_libre(), port_libre(), repertoire)
    )
    installer = executer(
        [
            str(version_odoo.python),
            str(version_odoo.odoo_bin),
            "-c",
            str(config),
            "-d",
            base,
            "-i",
            ",".join(version_odoo.modules),
            "--without-demo=all",
            "--stop-after-init",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if installer.returncode != 0:
        raise RuntimeError(
            f"Odoo {version_odoo.version} : installation du gabarit en"
            f" échec, voir {repertoire / f'odoo{version_odoo.version}.log'}"
        )
    script = (
        f"VERSION = {version_odoo.version}\nFUSEAU = {FUSEAU!r}\n"
        + post_installation(version_odoo.version)
    )
    post = executer(
        [
            str(version_odoo.python),
            str(version_odoo.odoo_bin),
            "shell",
            "-c",
            str(config),
            "-d",
            base,
            "--no-http",
        ],
        input=script,
        capture_output=True,
        text=True,
        check=False,
    )
    if post.returncode != 0 or "Traceback" in post.stderr + post.stdout:
        raise RuntimeError(
            f"Odoo {version_odoo.version} : post-installation en échec :\n"
            + (post.stderr or post.stdout)[-2000:]
        )


def copier_gabarit(version_odoo, base, executer=subprocess.run):
    """La base d'une course : copie du gabarit, filestore compris, et un uuid
    à elle, comme une base dupliquée par Odoo."""
    psql(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity"
        f" WHERE datname = '{version_odoo.gabarit}'",
        executer=executer,
    )
    copie = executer(
        ["createdb", "-T", version_odoo.gabarit, "--strategy=file_copy", base],
        capture_output=True,
        text=True,
        check=False,
    )
    if copie.returncode != 0:
        raise RuntimeError(f"createdb {base} : {copie.stderr.strip()}")
    psql(f'ALTER DATABASE "{base}" ALLOW_CONNECTIONS true', executer=executer)
    source = CACHE / "data" / "filestore" / version_odoo.gabarit
    if source.exists():
        shutil.copytree(source, CACHE / "data" / "filestore" / base)
    psql(
        "UPDATE ir_config_parameter SET value = gen_random_uuid()::text"
        " WHERE key = 'database.uuid'",
        base=base,
        executer=executer,
    )


# ─── Serveurs ─────────────────────────────────────────────────────────────


def port_libre():
    """Un port TCP libre sur 127.0.0.1 au moment de l'appel."""
    with socket.socket() as prise:
        prise.bind(("127.0.0.1", 0))
        return prise.getsockname()[1]


def version_repondue(url, delai=2):
    """La version majeure qu'un serveur dit être, ou None s'il ne répond pas."""
    requete = urllib.request.Request(
        f"{url}/web/webclient/version_info",
        data=json.dumps(
            {"jsonrpc": "2.0", "method": "call", "params": {}}
        ).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(requete, timeout=delai) as reponse:
            info = json.load(reponse).get("result", {})
        return int(info["server_version_info"][0])
    except (
        urllib.error.URLError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        IndexError,
    ):
        return None


def demarrer_serveur(version_odoo, base, repertoire, attente=90):
    """Démarre le serveur d'une base et attend qu'il réponde SA version : un
    autre programme sur le même port ne passerait pas pour lui."""
    port = port_libre()
    serveur = Serveur(
        version_odoo.version,
        base,
        port,
        repertoire / f"odoo{version_odoo.version}.conf",
        repertoire / f"odoo{version_odoo.version}.log",
    )
    serveur.config.write_text(
        config_odoo(version_odoo, base, port, port_libre(), repertoire)
    )
    serveur.processus = subprocess.Popen(
        [
            str(version_odoo.python),
            str(version_odoo.odoo_bin),
            "-c",
            str(serveur.config),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    fin = time.monotonic() + attente
    while time.monotonic() < fin:
        if serveur.processus.poll() is not None:
            break
        if version_repondue(serveur.url) == version_odoo.version:
            return serveur
        time.sleep(0.5)
    arreter_serveur(serveur)
    queue = ""
    if serveur.journal.exists():
        queue = "\n".join(
            serveur.journal.read_text(errors="replace").splitlines()[-50:]
        )
    raise RuntimeError(
        f"Odoo {version_odoo.version} ne répond pas sur {serveur.url}\n{queue}"
    )


def arreter_serveur(serveur, delai=10):
    """SIGTERM au groupe du serveur, puis SIGKILL s'il traîne."""
    processus = serveur.processus
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


GARDES = "serveurs.json"


def noter_gardes(repertoire, serveurs):
    """Note, dans le répertoire de la course, les serveurs que --garder
    laisse tourner : la course qui balaiera leurs bases les arrête d'abord."""
    (Path(repertoire) / GARDES).write_text(
        json.dumps(
            [
                {"pid": s.processus.pid, "base": s.base, "url": s.url}
                for s in serveurs
            ],
            indent=2,
        )
    )


def commande_de(pid):
    """La ligne de commande du processus pid, vide s'il n'existe plus."""
    try:
        return (
            Path(f"/proc/{pid}/cmdline")
            .read_bytes()
            .replace(b"\0", b" ")
            .decode(errors="replace")
        )
    except OSError:
        return ""


def arreter_gardes(
    bases, runs=None, lire=commande_de, tuer=os.killpg, delai=10
):
    """Arrête les serveurs gardés (noter_gardes) des bases à supprimer : une
    base supprimée sous son serveur le laisse tourner sur son port, en
    erreur. Seul un processus dont la ligne de commande nomme le répertoire
    de la course est visé : un pid réutilisé depuis par un autre programme
    n'est pas touché. Rend les pids arrêtés."""
    runs = Path(runs) if runs else CACHE / "runs"
    arretes = []
    for fichier in sorted(runs.glob(f"*/{GARDES}")):
        restants = []
        for garde in json.loads(fichier.read_text()):
            if garde["base"] not in bases:
                restants.append(garde)
                continue
            if str(fichier.parent) not in lire(garde["pid"]):
                continue
            try:
                tuer(garde["pid"], signal.SIGTERM)
            except ProcessLookupError:
                continue
            fin = time.monotonic() + delai
            while lire(garde["pid"]) and time.monotonic() < fin:
                time.sleep(0.2)
            if lire(garde["pid"]):
                tuer(garde["pid"], signal.SIGKILL)
            arretes.append(garde["pid"])
        if restants:
            fichier.write_text(json.dumps(restants, indent=2))
        else:
            fichier.unlink()
    return arretes
