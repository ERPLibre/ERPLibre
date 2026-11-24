#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""erplibre-serve : lance l'Odoo d'ERPLibre depuis l'environnement d'un hôte.

Le même lanceur sert aux deux façons d'héberger ERPLibre : application d'un
serveur qui lui pose sa base et ses secrets dans l'environnement, et
installation par SSH dont l'unité lit un fichier d'environnement.

CE QU'IL LIT
- La connexion à la base dans l'environnement de libpq : PGHOST, PGPORT,
  PGDATABASE, PGUSER, PGPASSWORD, PGSSLMODE, PGSSLROOTCERT. Le mot de passe
  n'est JAMAIS écrit dans la configuration : Odoo le laisse à libpq, qui le lit
  dans l'environnement.
- ODOO_ADMIN_PASSWD, le mot de passe maître, exigé : sans lui Odoo garde son
  défaut, et le gestionnaire de bases s'ouvre à qui le connaît.
- Les versions d'ERPLibre dans sa propre configuration : `.erplibre-version`
  et `.odoo-version` du dépôt, sinon le couple marqué `default` de
  `conf/supported_version_erplibre.json`. Le venv et le cœur d'Odoo en
  dérivent ; aucune version n'est écrite ici.
- `addons_path` dans le `config.conf` qu'ERPLibre a généré.

CE QU'IL DÉCIDE, une fois par démarrage, d'après la base et un marqueur posé
dans le dossier d'état :
- base vide, pas de marqueur : INITIALISER le profil, puis poser le marqueur ;
- base vide AVEC marqueur : REFUSER. La base a été initialisée puis perdue, ou
  sa restauration n'a pas eu lieu ; initialiser par-dessus ferait naître neuf
  ce qui attend ailleurs ;
- code d'une autre version que celle notée : MIGRER (`-u all`) ;
- sinon SERVIR.

La configuration rendue tient la base à une seule (`db_name`, `dbfilter`),
ferme le gestionnaire de bases (`list_db = False`), impose le mode TLS de
libpq (`db_sslmode`), sert derrière un mandataire (`proxy_mode`) sur la
boucle locale, et sans workers : le canal temps réel exige un second port,
qu'un mandataire à port unique ne relaie pas.
"""

from __future__ import annotations

import argparse
import configparser
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

MARQUE_INITIALISEE = ".erplibre-initialise"
VERSION_NOTEE = ".erplibre-version-code"
PROFIL_MINIMAL = ("base", "web", "mail", "contacts")
CONF_VERSIONS = Path("conf") / "supported_version_erplibre.json"

INITIALISER = "initialiser"
MIGRER = "migrer"
SERVIR = "servir"
REFUSER = "refuser"


class Versions(NamedTuple):
    """Le couple d'ERPLibre (« odoo18.0_python3.12.16 ») et la version
    d'Odoo (« 18.0 »)."""

    couple: str
    odoo: str


def versions(racine: Path) -> Versions | None:
    """Les versions du dépôt `racine`, ou None.

    Les fichiers posés à l'installation d'abord ; sinon le couple `default`
    du registre, que l'installation aurait choisi.
    """
    couple = _lit(racine / ".erplibre-version")
    odoo = _lit(racine / ".odoo-version")
    if couple and odoo:
        return Versions(couple, odoo)
    return versions_du_registre(racine)


def versions_du_registre(racine: Path) -> Versions | None:
    """Le couple marqué `default` du registre des versions, ou None."""
    try:
        registre = json.loads((racine / CONF_VERSIONS).read_text("utf-8"))
    except (OSError, ValueError):
        return None
    for cle, entree in (registre or {}).items():
        if isinstance(entree, dict) and entree.get("default") is True:
            version = str(entree.get("odoo_version") or "")
            return Versions(cle, version) if version else None
    return None


def _lit(chemin: Path) -> str:
    try:
        return chemin.read_text("utf-8").strip()
    except OSError:
        return ""


def chemins(racine: Path, v: Versions) -> tuple[Path, Path]:
    """L'interpréteur du venv d'Odoo et son `odoo-bin`."""
    return (
        racine / f".venv.{v.couple}" / "bin" / "python",
        racine / f"odoo{v.odoo}" / "odoo" / "odoo-bin",
    )


def addons_path_de(texte_conf: str) -> str:
    """L'`addons_path` d'une configuration d'Odoo, ou « »."""
    lecteur = configparser.ConfigParser(interpolation=None)
    try:
        lecteur.read_string(texte_conf)
    except configparser.Error:
        return ""
    return lecteur.get("options", "addons_path", fallback="").strip()


def resoudre_addons_path(chemins: str, racine: Path) -> str:
    """Les entrées relatives d'un `addons_path` résolues contre `racine` :
    un livrable se dépose où l'hôte veut, ses chemins le suivent."""
    rendu = []
    for entree in (e.strip() for e in chemins.split(",")):
        if entree:
            rendu.append(
                entree if entree.startswith("/") else str(racine / entree)
            )
    return ",".join(rendu)


def rendre_conf(env, port: int, data_dir: str, addons_path: str) -> str:
    """La configuration d'Odoo, rendue depuis l'environnement.

    `db_password = False` : libpq lit PGPASSWORD dans l'environnement, et le
    secret n'entre dans aucun fichier.
    """
    base = env["PGDATABASE"]
    lignes = [
        "[options]",
        f"admin_passwd = {env['ODOO_ADMIN_PASSWD']}",
        f"db_host = {env.get('PGHOST') or 'False'}",
        f"db_port = {env.get('PGPORT') or 'False'}",
        f"db_user = {env.get('PGUSER') or 'False'}",
        "db_password = False",
        f"db_name = {base}",
        f"dbfilter = ^{base}$",
        "list_db = False",
        f"db_sslmode = {env.get('PGSSLMODE') or 'prefer'}",
        f"data_dir = {data_dir}",
        "proxy_mode = True",
        "http_interface = 127.0.0.1",
        f"http_port = {int(port)}",
        "workers = 0",
    ]
    if addons_path:
        lignes.append(f"addons_path = {addons_path}")
    return "\n".join(lignes) + "\n"


def decider(base_vide: bool, marquee: bool, notee: str, code: str):
    """(action, raison) pour ce démarrage. Voir la docstring du module."""
    if base_vide and marquee:
        return REFUSER, (
            "la base est vide alors que ce dossier d'état l'a déjà"
            " initialisée : restauration incomplète ou base perdue,"
            " rien n'est réinitialisé"
        )
    if base_vide:
        return INITIALISER, "base vide, jamais initialisée ici"
    if code and notee and code != notee:
        return MIGRER, f"code {code}, base notée en {notee}"
    return SERVIR, ""


def manques(env) -> list[str]:
    """Les variables sans lesquelles le lanceur refuse."""
    return [n for n in ("PGDATABASE", "ODOO_ADMIN_PASSWD") if not env.get(n)]


SONDE_BASE = (
    "import psycopg2\n"
    "c = psycopg2.connect('')\n"
    "k = c.cursor()\n"
    'k.execute("select count(*) from information_schema.tables'
    " where table_name = 'ir_module_module'\")\n"
    "print(k.fetchone()[0])\n"
)


def base_vide(python: Path, env, executer=subprocess.run) -> bool | None:
    """Vrai si la base n'a pas de table d'Odoo, None si elle ne répond pas.

    Par psycopg2 du venv d'Odoo, qui lit la même connexion que lui dans
    l'environnement de libpq.
    """
    vu = executer(
        [str(python), "-c", SONDE_BASE],
        env=env,
        capture_output=True,
        text=True,
    )
    if vu.returncode != 0 or not vu.stdout.strip().isdigit():
        return None
    return int(vu.stdout.strip()) == 0


def version_du_code(racine: Path, executer=subprocess.run) -> str:
    """Le commit du dépôt, ou la première ligne de `PROVENANCE.lock` d'un
    livrable ; « » si aucun ne se lit, et alors rien n'est migré."""
    if (racine / ".git").exists():
        vu = executer(
            ["git", "-C", str(racine), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
        )
        if vu.returncode == 0:
            return vu.stdout.strip()
    return _lit(racine / "PROVENANCE.lock").split("\n", 1)[0].strip()


def principal(argv=None, env=None, executer=subprocess.run, remplacer=None):
    """La CLI. Rend un code de sortie ; en cas de service, remplace le
    processus par Odoo et ne rend pas."""
    analyseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analyseur.add_argument("--port", type=int, required=True)
    analyseur.add_argument("--etat", required=True, type=Path)
    analyseur.add_argument(
        "--racine", type=Path, default=Path(__file__).resolve().parents[2]
    )
    analyseur.add_argument("--profil", default=",".join(PROFIL_MINIMAL))
    args = analyseur.parse_args(argv)
    env = dict(os.environ if env is None else env)

    absents = manques(env)
    if absents:
        print(
            f"erplibre-serve : manquent {', '.join(absents)}", file=sys.stderr
        )
        return 2
    v = versions(args.racine)
    if v is None:
        print(
            "erplibre-serve : versions d'ERPLibre illisibles", file=sys.stderr
        )
        return 2
    python, odoo_bin = chemins(args.racine, v)
    if not python.is_file() or not odoo_bin.is_file():
        print(
            f"erplibre-serve : {python} ou {odoo_bin} absent", file=sys.stderr
        )
        return 2

    args.etat.mkdir(parents=True, exist_ok=True)
    conf = args.etat / "odoo.conf"
    texte = rendre_conf(
        env,
        args.port,
        str(args.etat / "filestore"),
        resoudre_addons_path(
            addons_path_de(_lit(args.racine / "config.conf")), args.racine
        ),
    )
    descripteur = os.open(conf, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descripteur, "w", encoding="utf-8") as fichier:
        fichier.write(texte)

    vide = base_vide(python, env, executer)
    if vide is None:
        print("erplibre-serve : la base ne répond pas", file=sys.stderr)
        return 3
    code = version_du_code(args.racine, executer)
    action, raison = decider(
        vide,
        (args.etat / MARQUE_INITIALISEE).exists(),
        _lit(args.etat / VERSION_NOTEE),
        code,
    )
    if action == REFUSER:
        print(f"erplibre-serve : {raison}", file=sys.stderr)
        return 4
    base = [str(python), str(odoo_bin), "-c", str(conf)]
    if action in (INITIALISER, MIGRER):
        options = (
            ["-i", args.profil] if action == INITIALISER else ["-u", "all"]
        )
        print(f"erplibre-serve : {action} — {raison}")
        vu = executer(base + options + ["--stop-after-init"], env=env)
        if vu.returncode != 0:
            return vu.returncode or 5
        (args.etat / MARQUE_INITIALISEE).touch()
        if code:
            (args.etat / VERSION_NOTEE).write_text(code + "\n", "utf-8")
    (remplacer or os.execve)(str(python), base, env)
    return 0


if __name__ == "__main__":
    sys.exit(principal())
