#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Intégrité d'un code Dolibarr exporté, contre son commit épinglé.

La production pose le code par `git archive` du commit épinglé : la
référence est donc cette archive même, relue en flux et jamais extraite.
Chaque membre donne son empreinte git (sha1 de « blob <taille>\\0<contenu> »),
à laquelle se compare celle du fichier installé. export-ignore et
export-subst de .gitattributes sont appliqués par git, comme à
l'installation : rien d'écarté n'est « absent », rien de réécrit n'est
« modifié ».

Écarts : modified (contenu changé), missing, added (présent, inconnu de
l'archive), unreadable. conf/conf.php et install.lock, posés par
l'installation, ne comptent pas. Les dossiers de custom/ sont des modules,
listés à part ; les fichiers que Dolibarr livre à sa racine se vérifient.
"""

import hashlib
import os
import subprocess
import tarfile

# Posés par l'installation, jamais dans le dépôt.
_INSTALLED = {"htdocs/conf/conf.php", "htdocs/install.lock"}
_CUSTOM = "htdocs/custom/"


class IntegrityError(Exception):
    """Le commit ou le checkout ne se lit pas."""


def archive_blobs(checkout, commit):
    """{chemin: (mode, empreinte)} de ce que `git archive` exporte."""
    proc = subprocess.Popen(
        ["git", "-C", checkout, "archive", "--format=tar", commit],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    blobs = {}
    try:
        with tarfile.open(fileobj=proc.stdout, mode="r|") as tar:
            for member in tar:
                if member.issym():
                    target = member.linkname.encode("utf-8", "surrogateescape")
                    blobs[member.name] = ("120000", _hash_bytes(target))
                elif member.isfile():
                    h = hashlib.sha1(b"blob %d\0" % member.size)
                    f = tar.extractfile(member)
                    for chunk in iter(lambda: f.read(1 << 20), b""):
                        h.update(chunk)
                    blobs[member.name] = ("100644", h.hexdigest())
    except tarfile.TarError:
        pass
    err = proc.stderr.read().decode("utf-8", "replace").strip()
    if proc.wait() or not blobs:
        raise IntegrityError(err or f"no archive for {commit}")
    return blobs


def _hash_bytes(data):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def blob_hash(path):
    """L'empreinte git d'un fichier : sha1 de « blob <taille>\\0 » + contenu."""
    h = hashlib.sha1()
    h.update(b"blob %d\0" % os.path.getsize(path))
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _link_hash(path):
    return _hash_bytes(os.readlink(path).encode("utf-8", "surrogateescape"))


def compare_tree(code_root, blobs):
    """Les écarts entre `code_root` et les blobs du commit, triés."""
    diff = {"modified": [], "missing": [], "added": [], "unreadable": []}
    custom = set()
    seen = set()
    closed = []

    def refused(error):
        rel = os.path.relpath(error.filename, code_root).replace(os.sep, "/")
        closed.append(rel + "/")

    for directory, dirs, files in os.walk(code_root, onerror=refused):
        dirs.sort()
        # Un lien vers un dossier est un blob du dépôt, pas un dossier à
        # parcourir.
        links = [d for d in dirs if os.path.islink(os.path.join(directory, d))]
        dirs[:] = [d for d in dirs if d not in links]
        for name in files + links:
            full = os.path.join(directory, name)
            rel = os.path.relpath(full, code_root).replace(os.sep, "/")
            seen.add(rel)
            module, sep, _rest = rel[len(_CUSTOM) :].partition("/")
            if rel.startswith(_CUSTOM) and sep:
                custom.add(module)
                continue
            if rel not in blobs:
                if rel not in _INSTALLED:
                    diff["added"].append(rel)
                continue
            mode, blob = blobs[rel]
            try:
                actual = (
                    _link_hash(full) if mode == "120000" else blob_hash(full)
                )
            except OSError:
                diff["unreadable"].append(rel)
                continue
            if actual != blob:
                diff["modified"].append(rel)
    diff["unreadable"] += closed
    # Ce qu'un dossier illisible cache n'est pas « absent ».
    diff["missing"] = [
        p
        for p in blobs
        if p not in seen and not any(p.startswith(c) for c in closed)
    ]
    for key in diff:
        diff[key].sort()
    diff["custom"] = sorted(custom)
    return diff
