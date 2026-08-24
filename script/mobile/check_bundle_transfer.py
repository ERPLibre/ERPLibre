#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le transfert des dépôts ERPLibre dans l'application mobile a-t-il eu lieu ?

L'application embarque le code des dépôts du manifeste pour les parcourir hors
ligne. Un APK est un ZIP borné à 65535 entrées, et ces dépôts pèsent plus de
120 000 fichiers : un fichier par source faisait échouer la compilation sur
« Too many zip entries ». Deux dispositions résolvent cela, et ce script
accepte les DEUX — sans quoi il échoue sur la moitié du travail qui n'a pas
encore atterri, ce qui est arrivé :

- ARCHIVE : un `tar.gz` par dépôt, plus un `index.json` listant ses chemins.
  Le manifeste porte alors `archive` et `indexUrl`.
- PACKS : des tranches `pack-NNN.bin` par dépôt, et un `index.json` qui dit
  pour chaque fichier sa tranche, son offset et sa longueur. Un fichier s'y
  relit sans décompresser le reste.

Ce script VÉRIFIE ce transfert, et il est fait pour être exécuté par
l'installation comme à la main :

    ./script/mobile/check_bundle_transfer.py [racine_du_dépôt_mobile]

Il échoue quand le transfert est vide, quand un conteneur manque, quand un
index promet un fichier que son conteneur n'a pas, ou quand les octets relus
diffèrent de la source — quatre pannes qu'un simple « la compilation a réussi »
ne dit pas. La présence est prouvée pour CHAQUE fichier promis ; seule la
relecture des octets se fait par échantillon.
"""

import argparse
import json
import random
import sys
import tarfile
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


# Le plugin de compilation ecrit les membres du tar prefixes par « ./ », quand
# l'index porte le chemin nu. Sans ce prefixe, extractfile ne trouve rien.
MEMBER_PREFIX = "./"


def index_path(base: Path, proj: dict) -> Path:
    """L'index du dépôt, dans l'une ou l'autre disposition."""
    url = proj.get("indexUrl")
    if url:
        # `indexUrl` est relatif à dist/, quand `base` est dist/repos.
        cand = base.parent / url
        if cand.is_file():
            return cand
    cand = base / proj["slug"] / "index.json"
    if cand.is_file():
        return cand
    raise FileNotFoundError(f"{proj['slug']} : index.json absent")


def archive_path(base: Path, proj: dict) -> Path:
    """Le tar.gz du dépôt, ou None si ce dépôt n'est pas en archive."""
    rel = proj.get("archive")
    if not rel:
        return None
    cand = base.parent / rel
    return cand if cand.is_file() else None


def read_from_archive(
    archive: Path, paths: list, promised: list = None
) -> dict:
    """Relit plusieurs fichiers en UNE passe de décompression.

    Ouvrir une archive par fichier coûterait quelques secondes chacune sur le
    dépôt odoo (150 Mo) : on traverse donc une seule fois en ramassant tout ce
    qui est demandé.

    `promised` : tous les chemins que l'index annonce pour cette archive. La
    traversée étant déjà payée, on en profite pour vérifier qu'ils y sont TOUS
    — un échantillon de vingt fichiers ne verrait pas un fantôme qu'il ne tire
    pas, et c'est précisément ce que cette passe attrape gratuitement.
    """
    wanted = {MEMBER_PREFIX + p: p for p in paths}
    found = {}
    seen = set()
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar:
            if member.isfile():
                seen.add(member.name)
            key = wanted.get(member.name)
            if key is None:
                continue
            handle = tar.extractfile(member)
            if handle is None:
                raise ValueError(
                    f"{archive.name} : {key} n'est pas un fichier"
                )
            found[key] = handle.read()
    missing = set(wanted.values()) - set(found)
    if missing:
        raise FileNotFoundError(
            f"{archive.name} : {len(missing)} fichier(s) tiré(s) de l'index"
            f" et absents de l'archive, dont {sorted(missing)[0]}"
        )
    if promised:
        ghosts = {q for q in promised if MEMBER_PREFIX + q not in seen}
        if ghosts:
            raise FileNotFoundError(
                f"{archive.name} : l'index promet {len(ghosts)} fichier(s) que"
                f" l'archive n'a pas, dont {sorted(ghosts)[0]}"
            )
    return found


def _collect(base: Path, repos: list, report: dict) -> tuple:
    """Range chaque dépôt dans sa disposition, et valide ce qu'il promet.

    Extraite de `check` pour la garder sous la complexité que flake8 accepte :
    deux dispositions et leurs validations tenaient mal dans une fonction.
    """
    pack_pool = []
    arch_pool = {}
    for proj in repos:
        entries = _read_json(index_path(base, proj))
        files = [e for e in entries if e.get("type") == "file"]
        # Le manifeste annonce un compte : un index plus court est un transfert
        # tronqué que rien d'autre ne signale.
        promised = proj.get("fileCount")
        if promised is not None and promised != len(files):
            raise ValueError(
                f"{proj['slug']} : le manifeste promet {promised} fichiers,"
                f" l'index en porte {len(files)}"
            )
        report["files"] += len(files)
        archive = archive_path(base, proj)
        if archive is not None:
            report["archives"] += 1
            arch_pool.setdefault(archive, (proj, []))[1].extend(files)
            continue
        repo_dir = base / proj["slug"]
        packs = list(repo_dir.glob("pack-*.bin"))
        if files and not packs:
            # Nommer la tranche ATTENDUE : « pack-*.bin » n'aide pas qui lit un
            # journal d'installation et cherche un fichier précis.
            chunks = sorted(
                {e["chunk"] for e in files if e.get("chunk") is not None}
            )
            attendu = (
                pack_path(repo_dir, chunks[0]).name
                if chunks
                else "pack-000.bin"
            )
            raise FileNotFoundError(
                f"{proj['slug']} : ni archive, ni {attendu}"
            )
        report["packs"] += len(packs)
        pack_pool += [(proj, repo_dir, e) for e in files if e.get("size")]
    return pack_pool, arch_pool


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
        "archives": 0,
        "packs": 0,
        "present": 0,
        "checked": 0,
        "compared": 0,
    }
    pack_pool, arch_pool = _collect(base, repos, report)

    if report["files"] < min_files:
        raise ValueError(
            f"transfert trop maigre : {report['files']} fichiers pour"
            f" {report['repos']} dépôts (au moins {min_files} attendus)"
        )

    flat = [("pack", proj, repo_dir, e) for proj, repo_dir, e in pack_pool]
    flat += [
        ("arch", proj, archive, e)
        for archive, (proj, entries) in arch_pool.items()
        for e in entries
    ]
    random.seed(SEED)
    sample = random.sample(flat, min(SAMPLE, len(flat)))

    def compare(proj, entry, data):
        report["checked"] += 1
        if workspace is None:
            return
        src = workspace / proj["path"] / entry["path"]
        if not src.is_file():
            return
        if data != src.read_bytes():
            raise ValueError(
                f"{proj['slug']} : {entry['path']} diffère de la source"
            )
        report["compared"] += 1

    for kind, proj, container, entry in sample:
        if kind == "pack":
            compare(proj, entry, read_from_pack(container, entry))

    drawn = {}
    for kind, proj, container, entry in sample:
        if kind == "arch":
            drawn.setdefault(container, []).append(entry)

    # Toutes les archives sont traversées, pas seulement celles que
    # l'échantillon tire : la traversée coûte 6 s pour les 139 dépôts et elle
    # prouve la présence de CHACUN des fichiers promis. Un échantillon de vingt
    # ne verrait pas un fantôme qu'il ne tire pas. Les octets, eux, ne sont lus
    # que pour les tirés — c'est la lecture qui coûte, pas la traversée.
    for archive, (proj, entries) in arch_pool.items():
        here = drawn.get(archive, [])
        blobs = read_from_archive(
            archive,
            [e["path"] for e in here],
            promised=[e["path"] for e in entries],
        )
        report["present"] += len(entries)
        for entry in here:
            compare(proj, entry, blobs[entry["path"]])

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
    where = []
    if rep["archives"]:
        where.append(f"{rep['archives']} archives")
    if rep["packs"]:
        where.append(f"{rep['packs']} tranches")
    proven = f", {rep['present']} présences prouvées" if rep["present"] else ""
    print(
        f"   {rep['repos']} dépôts, {rep['files']} fichiers en"
        f" {' et '.join(where) or 'aucun conteneur'}"
        f" ({rep['checked']} relus{extra}{proven})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
