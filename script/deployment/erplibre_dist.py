#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""erplibre-dist : un ERPLibre installé devient UN dépôt livrable versionné.

Un serveur d'hébergement lit une application dans un seul dépôt, à une
étiquette, et installe ses dépendances Python SANS index. ERPLibre assemble
son code par Google Repo depuis plus d'une centaine de dépôts, et tire ses
dépendances de PyPI. Ce constructeur part d'un ERPLibre DÉJÀ installé (Google
Repo synchronisé, venv posé) et en tire un dossier qui se suffit :

- `odoo<v>/odoo` et `odoo<v>/addons/<org>_<dépôt>`, sans `.git`, des seuls
  projets de l'arbre Odoo de la version, dans les groupes demandés (le cœur
  et `base`, `addons` par défaut), à leur commit figé EXACT : un projet qui
  suit sa branche fait refuser. `make repo_configure_all FREEZE=1` pose ces
  commits — dans `revision`, d'où `freeze-revision` est retiré — et
  synchronise les dépôts ; c'est le geste qui précède la construction ;
- sans les modules sous licence propriétaire (OPL-1, OEEL-1, « Other
  proprietary »), que le livrable ne peut pas redistribuer ;
- `roues/` : une roue par dépendance du venv, et `requirements.lock.txt` qui
  les nomme avec leur empreinte, pour une installation `--no-index
  --require-hashes` ;
- la configuration d'ERPLibre qui dit ses versions (`.erplibre-version`,
  `.odoo-version`, `conf/supported_version_erplibre.json`) : l'hôte y lit le
  Python à poser, rien n'est écrit ailleurs ;
- `config.conf` dont l'`addons_path` est RELATIF à la racine du livrable, le
  lanceur `script/deployment/erplibre_serve.py`, et `PROVENANCE.lock`.

L'ÉPREUVE suit la construction : un venv neuf, installé depuis `roues/` sans
index, doit initialiser `base` dans une base jetable. Un livrable qui ne
s'installe pas hors ligne n'est pas rendu comme prêt.

`--figer` joue d'abord `make repo_configure_all FREEZE=1`. `--detache
JOURNAL` relance le même constructeur hors de toute session, sa sortie dans
JOURNAL, puis recopie ce journal jusqu'au verdict : une connexion perdue
n'arrête que le suivi, et le relancer reprend le suivi de la construction
en cours au lieu d'en démarrer une autre.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import os
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import NamedTuple

# Lancé comme script, le dossier du script ouvre sys.path, pas la racine du
# dépôt : le paquet `script` ne s'y trouverait pas.
sys.path.append(str(Path(__file__).resolve().parents[2]))

from script.git.manifest_freeze import is_sha  # noqa: E402

GROUPES_DEFAUT = ("odoo", "base", "addons")
PROPRIETAIRES = frozenset({"OPL-1", "OEEL-1", "Other proprietary"})
# La licence d'un module qui n'en déclare pas, d'après le chargeur d'Odoo.
LICENCE_PAR_DEFAUT = "LGPL-3"
MANIFESTE_FUSIONNE = (
    Path(".repo") / "local_manifests" / "erplibre_manifest.xml"
)
FICHIERS_DE_VERSION = (
    ".erplibre-version",
    ".odoo-version",
    "conf/supported_version_erplibre.json",
    "script/deployment/erplibre_serve.py",
)
BASE_EPREUVE = "erplibre_dist_epreuve"
CIBLE_FIGER = (
    "make",
    "--no-print-directory",
    "repo_configure_all",
    "FREEZE=1",
)
# La dernière ligne d'un constructeur détaché : son code de sortie.
MARQUE_FIN = "erplibre-dist rc="


class Projet(NamedTuple):
    nom: str
    chemin: str
    url: str
    freeze: str


def projets(textes_xml, groupes=GROUPES_DEFAUT, prefixe="") -> list[Projet]:
    """Les projets des manifestes `textes_xml` sous `prefixe` qui portent au
    moins un des `groupes`. Un projet en commentaire n'est pas lu, ce qui est
    voulu.

    Le commit figé est la `freeze-revision`, ou la `revision` quand elle est
    déjà un commit : c'est là que la fusion en mode figé le met."""
    remotes, retenus = {}, {}
    for texte in textes_xml:
        racine = ET.fromstring(texte)
        for r in racine.iter("remote"):
            remotes[r.get("name")] = r.get("fetch") or ""
        for p in racine.iter("project"):
            portes = set((p.get("groups") or "").split(","))
            if not portes & set(groupes):
                continue
            chemin = p.get("path") or p.get("name")
            if not chemin.startswith(prefixe):
                continue
            retenus[chemin] = (p.get("name"), p.get("remote"), p)
    rendus = []
    for chemin, (nom, remote, p) in sorted(retenus.items()):
        rendus.append(
            Projet(
                nom,
                chemin,
                remotes.get(remote, "") + nom,
                p.get("freeze-revision")
                or (p.get("revision") if is_sha(p.get("revision")) else ""),
            )
        )
    return rendus


def ecarts_de_freeze(liste, tetes) -> list[str]:
    """Les projets qui ne sont pas à leur commit figé. `tetes` : chemin →
    commit lu. Un projet qui suit sa branche est un écart : son contenu
    dépendrait du jour de la construction."""
    ecarts = []
    for p in liste:
        tete = tetes.get(p.chemin, "")
        if not p.freeze:
            ecarts.append(f"{p.chemin} : suit sa branche, aucun commit figé")
        elif tete != p.freeze:
            ecarts.append(
                f"{p.chemin} : {tete or 'illisible'} au lieu de {p.freeze}"
            )
    return ecarts


def licence_de(texte_manifeste: str) -> str:
    """La licence qu'un `__manifest__.py` déclare, ou celle d'Odoo par
    défaut. Lue sans exécuter le fichier."""
    try:
        valeur = ast.literal_eval(texte_manifeste)
    except (ValueError, SyntaxError):
        return ""
    if not isinstance(valeur, dict):
        return ""
    return str(valeur.get("license") or LICENCE_PAR_DEFAUT)


def modules_proprietaires(dossier: Path) -> list[tuple[str, str]]:
    """(module, licence) de chaque module propriétaire sous `dossier`."""
    exclus = []
    for manifeste in sorted(dossier.glob("*/__manifest__.py")):
        licence = licence_de(manifeste.read_text("utf-8", errors="replace"))
        if licence in PROPRIETAIRES:
            exclus.append((manifeste.parent.name, licence))
    return exclus


# Une roue : nom-version(-construction)?-python-abi-plateforme.whl (PEP 427).
_ROUE = re.compile(r"^([^-]+)-([^-]+)(?:-\d[^-]*)?-[^-]+-[^-]+-[^-]+\.whl$")


def ligne_lock(nom_roue: str, empreinte: str) -> str:
    """La ligne de `requirements.lock.txt` qui exige cette roue exacte."""
    m = _ROUE.match(nom_roue)
    if not m:
        raise ValueError(f"nom de roue illisible : {nom_roue}")
    return f"{m.group(1)}=={m.group(2)} --hash=sha256:{empreinte}"


def addons_path_relatif(chemins_absolus: str, racine: str, copies) -> str:
    """L'`addons_path` d'ERPLibre, ses entrées rendues relatives à `racine`.

    Seules restent les entrées qui tombent dans un projet de `copies` : une
    entrée hors de la racine, ou dans un dossier que le livrable ne porte
    pas, nommerait un chemin absent, qu'Odoo refuse au démarrage."""
    prefixe = racine.rstrip("/") + "/"
    rendu = []
    for entree in chemins_absolus.split(","):
        entree = entree.strip().rstrip("/")
        if not entree.startswith(prefixe):
            continue
        relatif = entree[len(prefixe) :]
        if any(relatif == c or relatif.startswith(c + "/") for c in copies):
            rendu.append(relatif)
    return ",".join(rendu)


def ignore_pour(source: Path, modules):
    """Ce que la copie d'un projet laisse : `.git` à tout niveau, et les
    `modules` exclus, au premier niveau du projet seulement."""

    def ignore(dossier, noms):
        rendus = [n for n in noms if n == ".git"]
        if Path(dossier) == source:
            rendus += [n for n in noms if n in modules]
        return rendus

    return ignore


def texte_provenance(liste, exclus, couple) -> str:
    """`PROVENANCE.lock` : la première ligne identifie la version du code,
    ce que le lanceur lit pour décider d'une migration."""
    empreinte = hashlib.sha256(
        "\n".join(f"{p.chemin}={p.freeze}" for p in liste).encode()
    ).hexdigest()[:16]
    lignes = [f"{couple}-{empreinte}", ""]
    for p in liste:
        lignes.append(f"{p.chemin}\t{p.url}\t{p.freeze}")
    if exclus:
        lignes += ["", "# exclus pour leur licence"]
        lignes += [f"{c}/{m}\t{lic}" for c, m, lic in exclus]
    return "\n".join(lignes) + "\n"


def _jouer(executer, argv, **kw):
    vu = executer(argv, capture_output=True, text=True, **kw)
    if vu.returncode != 0:
        raise RuntimeError(
            f"{' '.join(map(str, argv[:4]))}… : "
            f"{(vu.stderr or vu.stdout)[-300:]}"
        )
    return vu.stdout


def construire(
    racine: Path,
    sortie: Path,
    groupes=GROUPES_DEFAUT,
    executer=subprocess.run,
    epreuve=True,
    dire=print,
) -> list[str]:
    """Construit le livrable de `racine` dans `sortie`. Rend les écarts ;
    une liste vide veut dire un livrable construit ET éprouvé."""
    from script.deployment import erplibre_serve as S

    v = S.versions(racine)
    if v is None:
        return ["versions d'ERPLibre illisibles"]
    manifeste = racine / MANIFESTE_FUSIONNE
    if not manifeste.is_file():
        return [f"manifeste fusionné absent : {manifeste}"]
    liste = projets([manifeste.read_text("utf-8")], groupes, f"odoo{v.odoo}/")
    if not liste:
        return ["aucun projet dans les groupes demandés"]
    tetes = {}
    for p in liste:
        vu = executer(
            ["git", "-C", str(racine / p.chemin), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
        )
        tetes[p.chemin] = vu.stdout.strip() if vu.returncode == 0 else ""
    ecarts = ecarts_de_freeze(liste, tetes)
    if ecarts:
        return ecarts

    if sortie.exists():
        shutil.rmtree(sortie)
    sortie.mkdir(parents=True)
    exclus = []
    for p in liste:
        source = racine / p.chemin
        proprietaires = modules_proprietaires(source)
        exclus += [(p.chemin, m, lic) for m, lic in proprietaires]
        shutil.copytree(
            source,
            sortie / p.chemin,
            symlinks=True,
            ignore=ignore_pour(source, {m for m, _l in proprietaires}),
        )
    dire(f"  · {len(liste)} projets copiés, {len(exclus)} modules exclus")

    for rel in FICHIERS_DE_VERSION:
        cible = sortie / rel
        cible.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(racine / rel, cible)
    absolu = S.addons_path_de(
        (racine / "config.conf").read_text("utf-8", errors="replace")
    )
    (sortie / "config.conf").write_text(
        "[options]\naddons_path = "
        + addons_path_relatif(absolu, str(racine), [p.chemin for p in liste])
        + "\n",
        "utf-8",
    )
    (sortie / "PROVENANCE.lock").write_text(
        texte_provenance(liste, exclus, v.couple), "utf-8"
    )

    python, odoo_bin = S.chemins(racine, v)
    gel = _jouer(
        executer, [str(python), "-m", "pip", "freeze", "--exclude-editable"]
    )
    requis = sortie / "requirements.txt"
    requis.write_text(
        "\n".join(
            ligne
            for ligne in gel.splitlines()
            if "==" in ligne and not ligne.startswith("pkg_resources")
        )
        + "\n",
        "utf-8",
    )
    roues = sortie / "roues"
    _jouer(
        executer,
        [
            str(python),
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "-r",
            str(requis),
            "-w",
            str(roues),
        ],
    )
    lignes = []
    for roue in sorted(roues.glob("*.whl")):
        empreinte = hashlib.sha256(roue.read_bytes()).hexdigest()
        lignes.append(ligne_lock(roue.name, empreinte))
    (sortie / "requirements.lock.txt").write_text(
        "\n".join(lignes) + "\n", "utf-8"
    )
    dire(f"  · {len(lignes)} roues")
    if not epreuve:
        return []
    return eprouver(sortie, python, executer, dire)


def eprouver(
    sortie: Path,
    python_construction: Path,
    executer=subprocess.run,
    dire=print,
) -> list[str]:
    """Un venv neuf, installé depuis `roues/` SANS index, doit initialiser
    `base` dans une base jetable, détruite ensuite."""
    from script.deployment import erplibre_serve as S

    base = _jouer(
        executer,
        [
            str(python_construction),
            "-c",
            "import sys; print(sys._base_executable)",
        ],
    ).strip()
    v = S.versions(sortie)
    venv = sortie / f".venv.{v.couple}"
    try:
        _jouer(executer, [base, "-m", "venv", str(venv)])
        _jouer(
            executer,
            [
                str(venv / "bin" / "python"),
                "-m",
                "pip",
                "install",
                "--no-index",
                "--find-links",
                str(sortie / "roues"),
                "--require-hashes",
                "-r",
                str(sortie / "requirements.lock.txt"),
            ],
        )
        _python, odoo_bin = S.chemins(sortie, v)
        chemins = ",".join(
            str(sortie / e)
            for e in S.addons_path_de(
                (sortie / "config.conf").read_text("utf-8")
            ).split(",")
            if e
        )
        _jouer(
            executer,
            [
                str(venv / "bin" / "python"),
                str(odoo_bin),
                "--addons-path",
                chemins,
                "-d",
                BASE_EPREUVE,
                "-i",
                "base",
                "--stop-after-init",
                "--without-demo",
                "all",
            ],
        )
    except RuntimeError as souci:
        return [f"épreuve : {souci}"]
    finally:
        # Verdict ignoré : `--if-exists` rend 0 sans base, et un échec ici ne
        # change pas celui de l'épreuve, déjà rendu.
        executer(
            ["dropdb", "--if-exists", BASE_EPREUVE],
            capture_output=True,
            text=True,
        )
        shutil.rmtree(venv, ignore_errors=True)
    dire("  · épreuve : venv hors ligne, base initialisée")
    return []


def figer(racine: Path, executer=subprocess.run, dire=print) -> list[str]:
    """Met chaque projet sur son commit figé par la cible d'ERPLibre, qui
    fusionne le manifeste en mode figé et synchronise. Rend les écarts."""
    vu = executer(
        list(CIBLE_FIGER), cwd=str(racine), capture_output=True, text=True
    )
    if vu.returncode != 0:
        return [f"figer : {(vu.stderr or vu.stdout)[-300:]}"]
    dire("  · dépôts figés")
    return []


def argv_enfant(argv) -> list[str]:
    """L'argv du constructeur détaché : le même, sans `--detache` ni sa
    valeur, marqué pour écrire son verdict en dernière ligne."""
    rendu, sauter = [], False
    for mot in argv:
        if sauter:
            sauter = False
        elif mot == "--detache":
            sauter = True
        elif not mot.startswith("--detache="):
            rendu.append(mot)
    return [sys.executable, str(Path(__file__).resolve()), *rendu, "--marquer"]


def fichier_pid(journal: Path) -> Path:
    return Path(f"{journal}.pid")


def vivant(pid: int) -> bool:
    """Le processus `pid` existe-t-il ? Un processus d'un autre compte
    existe aussi : le signal refusé le prouve."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def pid_en_cours(journal: Path, est_vivant=vivant) -> int | None:
    """Le pid d'une construction encore en cours sur `journal`, ou None."""
    try:
        pid = int(fichier_pid(journal).read_text().strip())
    except (OSError, ValueError):
        return None
    return pid if est_vivant(pid) else None


def lancer_detache(argv, journal: Path, popen=subprocess.Popen):
    """Lance `argv` dans une session à lui, sortie dans `journal`, et
    écrit son pid à côté. Rend le processus.

    Sa PROPRE session : un ssh qui se ferme envoie SIGHUP à son groupe, et
    la construction ne doit pas en faire partie."""
    journal.parent.mkdir(parents=True, exist_ok=True)
    with open(journal, "w", encoding="utf-8") as sortie:
        proc = popen(
            argv,
            stdout=sortie,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            env=dict(os.environ, PYTHONUNBUFFERED="1"),
        )
    fichier_pid(journal).write_text(f"{proc.pid}\n")
    return proc


def verdict_du_journal(texte: str) -> int | None:
    """Le code que la dernière marque de fin porte, ou None sans marque."""
    for ligne in reversed(texte.splitlines()):
        if ligne.startswith(MARQUE_FIN):
            reste = ligne[len(MARQUE_FIN) :].strip()
            return int(reste) if reste.isdigit() else 1
    return None


def suivre(journal: Path, termine, dormir=time.sleep, ecrire=None, pas=5.0):
    """Recopie `journal` au fil de l'eau jusqu'à sa marque de fin, et rend
    le code qu'elle porte.

    `termine()` dit si le constructeur est fini. Fini SANS marque, il a été
    interrompu : c'est un échec, jamais un silence qu'on attendrait."""
    ecrire = ecrire or (lambda s: print(s, end="", flush=True))
    lu = 0
    while True:
        fini = termine()
        try:
            texte = journal.read_text("utf-8", errors="replace")
        except OSError:
            texte = ""
        if len(texte) > lu:
            ecrire(texte[lu:])
            lu = len(texte)
        code = verdict_du_journal(texte)
        if code is not None:
            return code
        # `fini` est lu AVANT le journal : un verdict écrit juste avant la
        # fin est donc toujours vu.
        if fini:
            ecrire("✗ construction interrompue, aucun verdict écrit\n")
            return 1
        dormir(pas)


def principal(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    analyseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analyseur.add_argument("--racine", type=Path, required=True)
    analyseur.add_argument("--sortie", type=Path, required=True)
    analyseur.add_argument("--groupes", default=",".join(GROUPES_DEFAUT))
    analyseur.add_argument("--sans-epreuve", action="store_true")
    analyseur.add_argument("--figer", action="store_true")
    analyseur.add_argument("--detache", type=Path, metavar="JOURNAL")
    analyseur.add_argument(
        "--marquer", action="store_true", help=argparse.SUPPRESS
    )
    args = analyseur.parse_args(argv)
    if args.detache:
        journal = args.detache.expanduser().resolve()
        pid = pid_en_cours(journal)
        if pid is not None:
            print(f"construction déjà en cours, suivie : {journal}")
            return suivre(journal, lambda: not vivant(pid))
        proc = lancer_detache(argv_enfant(argv), journal)
        print(f"construction détachée, journal : {journal}")
        return suivre(journal, lambda: proc.poll() is not None)
    racine = args.racine.resolve()
    ecarts = figer(racine) if args.figer else []
    if not ecarts:
        ecarts = construire(
            racine,
            args.sortie.resolve(),
            tuple(g for g in args.groupes.split(",") if g),
            epreuve=not args.sans_epreuve,
        )
    for ecart in ecarts:
        print(f"✗ {ecart}", file=sys.stderr, flush=True)
    if not ecarts:
        print(f"✓ livrable prêt : {args.sortie}", flush=True)
    code = 1 if ecarts else 0
    if args.marquer:
        print(f"{MARQUE_FIN}{code}", flush=True)
    return code


if __name__ == "__main__":
    sys.exit(principal())
