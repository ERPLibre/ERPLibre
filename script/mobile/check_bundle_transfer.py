#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le transfert des dépôts ERPLibre dans l'application mobile a-t-il eu lieu ?

L'application embarque le code des dépôts du manifeste pour les parcourir hors
ligne. Ils y entrent sous forme de PACKS : un APK est un ZIP borné à 65535
entrées, et ces dépôts pèsent plus de 120 000 fichiers — un fichier par source
faisait échouer la compilation sur « Too many zip entries ». Chaque dépôt a donc
un `index.json` qui dit, pour chaque fichier, dans quelle tranche il se trouve,
à quel offset et sur quelle longueur.

Ce script VÉRIFIE ce transfert, et il est fait pour être exécuté par
l'installation comme à la main :

    ./script/mobile/check_bundle_transfer.py [racine_du_dépôt_mobile]

Il échoue quand le transfert est vide, quand une tranche manque, ou quand un
index promet des octets que sa tranche n'a pas — trois pannes qu'un simple
« la compilation a réussi » ne dit pas.
"""

import argparse
import json
import random
import sys
from pathlib import Path

# En dessous, ce n'est plus un transfert : c'est un bundle vide qu'on aurait pris
# pour bon. Le seul dépôt odoo en porte près de 40 000 à lui seul.
MIN_FILES = 1000
# Échantillon relu octet pour octet. Tout relire prendrait des minutes pour ne
# rien apprendre de plus : une tranche fausse l'est dès le premier extrait.
SAMPLE = 20
SEED = 7


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def pack_path(repo_dir: Path, chunk: int) -> Path:
    """Nom de tranche, tel que l'écrit le plugin de compilation."""
    return repo_dir / ("pack-%03d.bin" % chunk)


def read_from_pack(repo_dir: Path, entry: dict) -> bytes:
    """Relit un fichier depuis sa tranche. Lève si l'index et le pack mentent."""
    chunk = entry["chunk"]
    path = pack_path(repo_dir, chunk)
    size = entry.get("size", 0)
    offset = entry.get("offset", 0)
    if not path.is_file():
        raise FileNotFoundError(f"tranche absente : {path.name}")
    if offset + size > path.stat().st_size:
        raise ValueError(
            f"{path.name} fait {path.stat().st_size} o, l'index y demande"
            f" {size} o à {offset}"
        )
    with open(path, "rb") as fh:
        fh.seek(offset)
        data = fh.read(size)
    if len(data) != size:
        raise ValueError(f"{path.name} : {len(data)} o lus au lieu de {size}")
    return data


def check(
    mobile_root: Path, workspace: Path = None, min_files: int = None
) -> dict:
    """Vérifie le transfert et rend un compte-rendu.

    `workspace` : racine du checkout ERPLibre. Fournie, un échantillon est
    comparé OCTET POUR OCTET à la source — c'est la seule vérification qui
    prouve un transfert fidèle, et non seulement cohérent.
    """
    # Résolu à l'APPEL, et non dans la signature : un défaut lié à la
    # définition ne suit pas la constante si un appelant la change.
    min_files = MIN_FILES if min_files is None else min_files
    base = mobile_root / "dist" / "repos"
    manifest = base / "manifest.json"
    if not manifest.is_file():
        raise FileNotFoundError(
            f"aucun transfert : {manifest} est absent (npm run build ?)"
        )
    repos = _read_json(manifest)
    report = {
        "repos": len(repos),
        "files": 0,
        "packs": 0,
        "checked": 0,
        "compared": 0,
    }
    sample_pool = []
    for proj in repos:
        repo_dir = base / proj["slug"]
        index = repo_dir / "index.json"
        if not index.is_file():
            raise FileNotFoundError(f"{proj['slug']} : index.json absent")
        entries = _read_json(index)
        files = [
            e
            for e in entries
            if e.get("type") == "file" and e.get("chunk") is not None
        ]
        report["files"] += len(files)
        report["packs"] += len(list(repo_dir.glob("pack-*.bin")))
        sample_pool += [(proj, repo_dir, e) for e in files if e.get("size")]

    if report["files"] < min_files:
        raise ValueError(
            f"transfert trop maigre : {report['files']} fichiers pour"
            f" {report['repos']} dépôts (au moins {min_files} attendus)"
        )

    random.seed(SEED)
    for proj, repo_dir, entry in random.sample(
        sample_pool, min(SAMPLE, len(sample_pool))
    ):
        data = read_from_pack(repo_dir, entry)
        report["checked"] += 1
        if workspace is None:
            continue
        src = workspace / proj["path"] / entry["path"]
        if not src.is_file():
            continue
        if data != src.read_bytes():
            raise ValueError(
                f"{proj['slug']} : {entry['path']} diffère de la source"
            )
        report["compared"] += 1
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mobile_root",
        nargs="?",
        default="mobile/erplibre_home_mobile",
        help="racine du dépôt mobile (défaut : mobile/erplibre_home_mobile)",
    )
    parser.add_argument(
        "--workspace",
        default="",
        help="racine ERPLibre, pour comparer un échantillon à la source",
    )
    args = parser.parse_args()
    root = Path(args.mobile_root)
    ws = Path(args.workspace) if args.workspace else None
    try:
        rep = check(root, ws)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"   ⚠ transfert des dépôts : {exc}")
        return 1
    extra = (
        f", {rep['compared']} comparés à la source" if rep["compared"] else ""
    )
    print(
        f"   {rep['repos']} dépôts, {rep['files']} fichiers en"
        f" {rep['packs']} tranches ({rep['checked']} relus{extra})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
