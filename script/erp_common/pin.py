# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Épinglage d'un ERP : commit au manifest, version et images au JSON.

L'épinglage tient en deux fichiers relatifs à la racine du dépôt. Le
manifest Google Repo porte le COMMIT du projet de son groupe, sous la forme
revision="<sha>" upstream="<branche>" que Repo sait synchroniser. Le JSON
porte ce que le commit ne dit pas sans être récupéré : version affichée,
branche suivie, références d'images. read_pin refuse un couple incohérent
plutôt que de rendre une version fausse.

Les images s'épinglent par empreinte, dépôt:étiquette@sha256:…, lue au
Docker Hub : une image reconstruite sous la même étiquette déplace
l'épinglage. Le réseau passe par Network, que les tests remplacent par un
objet aux mêmes méthodes.
"""

import json
import os
import re
import subprocess
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

HUB = "https://hub.docker.com/v2/repositories"

_SHA = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


class PinError(Exception):
    """L'épinglage est absent, illisible ou incohérent."""


def read_pin(root, json_rel, manifest_rel, group, keys):
    """Rend l'épinglage lu sous la racine du dépôt `root`.

    `json_rel` et `manifest_rel` sont relatifs à `root` et nomment les
    fichiers dans les messages. Le projet retenu est le premier du manifest
    dont `groups` contient `group`. `keys` liste les clés exigées non vides
    du JSON et doit contenir « branch », comparée à l'upstream du projet.

    Clés rendues : celles de `keys` en texte, plus « commit » (sha complet
    du manifest) et « path » (chemin du checkout relatif à `root`). Lève
    PinError pour tout défaut, et seulement PinError : l'appelant n'a qu'une
    exception à rattraper pour dire pourquoi l'ERP n'est pas proposé.
    """
    json_path = os.path.join(root, json_rel)
    try:
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise PinError(f"{json_rel}: {e}") from e
    if not isinstance(data, dict):
        raise PinError(f"{json_rel}: not a JSON object")
    missing = [k for k in keys if not data.get(k)]
    if missing:
        raise PinError(f"{json_rel}: missing {', '.join(missing)}")

    manifest_path = os.path.join(root, manifest_rel)
    try:
        tree = ET.parse(manifest_path)
    except (OSError, ET.ParseError) as e:
        raise PinError(f"{manifest_rel}: {e}") from e
    project = None
    for node in tree.getroot().iter("project"):
        groups = (node.get("groups") or "").split(",")
        if group in (g.strip() for g in groups):
            project = node
            break
    if project is None:
        raise PinError(f"{manifest_rel}: no project in group {group}")

    commit = project.get("revision") or ""
    if not _SHA.match(commit):
        raise PinError(
            f"{manifest_rel}: revision {commit!r} is not a full commit"
        )
    upstream = project.get("upstream") or ""
    if upstream != data["branch"]:
        raise PinError(
            f"{manifest_rel} follows {upstream!r},"
            f" {json_rel} declares {data['branch']!r}"
        )

    pin = {k: str(data[k]) for k in keys}
    pin["commit"] = commit
    pin["path"] = project.get("path") or ""
    return pin


def rewrite_manifest(text, commit, branch, group):
    """`text` où le projet du groupe `group` prend `commit` et `branch`.

    Seul ce projet change : revision, upstream et dest-branch ; le reste
    du fichier, commentaires compris, est rendu tel quel. Lève ValueError
    si le groupe ne compte pas exactement un projet : en réécrire deux les
    épinglerait sur le même commit.
    """

    def one(m):
        block = m.group(0)
        block = re.sub(r'revision="[^"]*"', f'revision="{commit}"', block)
        block = re.sub(r'upstream="[^"]*"', f'upstream="{branch}"', block)
        return re.sub(r'dest-branch="[^"]*"', f'dest-branch="{branch}"', block)

    pattern = re.compile(
        r"<project\b[^>]*groups=\"[^\"]*\b"
        + re.escape(group)
        + r"\b[^\"]*\"[^>]*/>",
        re.S,
    )
    new, count = pattern.subn(one, text)
    if count != 1:
        raise ValueError(f"{count} {group} projects in the manifest")
    return new


class Network:
    """ls-remote sur le dépôt `upstream` et étiquettes du Docker Hub."""

    def __init__(self, upstream):
        self.upstream = upstream

    def ls_remote(self, ref):
        """Sha de `ref` exactement nommée chez `upstream`, ou None."""
        r = subprocess.run(
            ["git", "ls-remote", self.upstream, ref],
            capture_output=True,
            text=True,
            timeout=60,
        )
        for line in r.stdout.splitlines():
            sha, name = line.split("\t", 1)
            if name == ref:
                return sha
        return None

    def hub_digest(self, repo, tag):
        """Empreinte de l'index de `repo`:`tag` au Hub, ou None.

        Toute réponse autre qu'une empreinte sha256 complète rend None :
        l'empreinte finit dans une commande « run » d'un moteur de
        conteneurs, rien d'autre n'y entre.
        """
        path = repo.removeprefix("docker.io/")
        try:
            with urllib.request.urlopen(
                f"{HUB}/{path}/tags/{tag}", timeout=30
            ) as resp:
                digest = json.load(resp).get("digest")
        except (urllib.error.URLError, OSError, ValueError):
            return None
        return digest if _DIGEST.fullmatch(digest or "") else None


def split_image(ref):
    """(dépôt, étiquette, empreinte ou None) d'une référence d'image."""
    ref, _at, digest = ref.partition("@")
    repo, _colon, tag = ref.rpartition(":")
    return repo, tag, digest or None


def image_ref(repo, tag, digest):
    """Référence dépôt:étiquette, suivie de @empreinte si elle est donnée."""
    return f"{repo}:{tag}@{digest}" if digest else f"{repo}:{tag}"


def refreshed_image(net, current, tag=None):
    """`current` à l'étiquette `tag` (la sienne par défaut), empreinte lue
    au Hub ; `current` tel quel si le Hub ne connaît pas cette étiquette."""
    repo, own_tag, _digest = split_image(current)
    tag = tag or own_tag
    digest = net.hub_digest(repo, tag)
    return image_ref(repo, tag, digest) if digest else current


def target(net, branch, tag):
    """(commit, ref) visé : le tag s'il est donné, sinon la tête de branche.

    Un tag annoté se résout par sa forme pelée ^{} d'abord, qui nomme le
    commit et non l'objet tag. Rien en amont rend (None, ref).
    """
    if tag:
        for ref in (f"refs/tags/{tag}^{{}}", f"refs/tags/{tag}"):
            commit = net.ls_remote(ref)
            if commit:
                return commit, ref
        return None, f"refs/tags/{tag}"
    ref = f"refs/heads/{branch}"
    return net.ls_remote(ref), ref
