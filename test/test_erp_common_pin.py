#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Épinglage d'un ERP (script/erp_common/pin) : manifest, JSON, images.

Le réseau est simulé. Ce qui se garde :
- read_pin prend le commit au manifest et la version au JSON, et refuse
  tout couple incohérent par PinError, sa seule exception ;
- le projet se trouve par son groupe, jamais par son rang ;
- rewrite_manifest ne touche que le projet du groupe, et refuse zéro ou
  deux projets ;
- une empreinte du Hub qui n'est pas un sha256 complet ne passe pas ;
- le tag visé se résout par sa forme pelée d'abord.
Chaque test qui dépend du nom de l'ERP tourne pour deux noms.
"""

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
if RACINE not in sys.path:
    sys.path.insert(0, RACINE)

from script.erp_common import pin  # noqa: E402

# Deux noms : celui d'un ERP réel et un nom inventé, pour prouver que rien
# n'est écrit en dur.
ERPS = ("dolibarr", "acme")

# Commits et empreintes inventés : aucun n'existe dans un dépôt.
COMMIT = "0123456789abcdef0123456789abcdef01234567"
ANCIEN = "a" * 40
NOUVEAU = "b" * 40
TAG = "c" * 40
DOLI = "docker.io/dolibarr/dolibarr"
MARIA = "docker.io/library/mariadb"
D_2400 = "sha256:" + "1" * 64
D_MARIA = "sha256:" + "3" * 64

KEYS = (
    "version",
    "branch",
    "docker_image",
    "mariadb_image",
    "tools_image",
    "php_min",
    "php_max",
)

PIN = {
    "version": "24.0.1",
    "branch": "24.0",
    "docker_image": "dolibarr/dolibarr:24.0.0",
    "mariadb_image": "mariadb:11.4",
    "tools_image": "docker.io/library/composer:2",
    "php_min": "7.2",
    "php_max": "8.5",
}

# Gabarit de manifest : {group} est le groupe de l'ERP essayé.
MANIFEST = """<?xml version="1.0" encoding="UTF-8" ?>
<manifest>
    <remote name="Upstream" fetch="https://example.org/" />
    <!-- commentaire à garder -->
    <project
        name="erp.git"
        path="{group}/{group}"
        remote="Upstream"
        revision="{{rev}}"
        upstream="{{branch}}"
        dest-branch="{{branch}}"
        clone-depth="1"
        groups="{group}"
    />
</manifest>
"""


def manifest_for(group, **kw):
    return MANIFEST.format(group=group).format(**kw)


def paths(erp):
    """(json_rel, manifest_rel) selon la convention des ERP du dépôt."""
    return (
        os.path.join("conf", f"supported_version_{erp}.json"),
        os.path.join("manifest", f"git_manifest_{erp}.xml"),
    )


class TestReadPin(unittest.TestCase):
    def _root(
        self, erp, pin_data=PIN, revision=COMMIT, upstream="24.0", text=None
    ):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = tmp.name
        os.makedirs(os.path.join(root, "conf"))
        os.makedirs(os.path.join(root, "manifest"))
        json_rel, manifest_rel = paths(erp)
        if pin_data is not None:
            with open(os.path.join(root, json_rel), "w") as f:
                json.dump(pin_data, f)
        if text is None:
            text = manifest_for(erp, rev=revision, branch=upstream)
        if text is not False:
            with open(os.path.join(root, manifest_rel), "w") as f:
                f.write(text)
        return root

    def read(self, erp, root):
        json_rel, manifest_rel = paths(erp)
        return pin.read_pin(root, json_rel, manifest_rel, erp, KEYS)

    def test_commit_comes_from_the_manifest_and_version_from_the_json(self):
        for erp in ERPS:
            with self.subTest(erp=erp):
                got = self.read(erp, self._root(erp))
                self.assertEqual(got["commit"], COMMIT)
                self.assertEqual(got["version"], "24.0.1")
                self.assertEqual(got["branch"], "24.0")
                self.assertEqual(got["path"], f"{erp}/{erp}")
                self.assertEqual(
                    got["docker_image"], "dolibarr/dolibarr:24.0.0"
                )
                self.assertEqual(set(got), set(KEYS) | {"commit", "path"})

    def test_a_commit_pinned_on_another_branch_is_refused(self):
        # Le JSON annonce 24.0 ; le manifest suit 23.0 : le menu afficherait
        # « 24.0.1 » pour du code 23.
        for erp in ERPS:
            with self.subTest(erp=erp):
                root = self._root(erp, upstream="23.0")
                with self.assertRaises(pin.PinError) as ctx:
                    self.read(erp, root)
                self.assertIn("23.0", str(ctx.exception))
                self.assertIn("24.0", str(ctx.exception))

    def test_a_branch_name_is_not_a_pin(self):
        # revision="24.0" suivrait la branche : ce n'est plus un épinglage.
        for erp in ERPS:
            with self.subTest(erp=erp):
                with self.assertRaises(pin.PinError):
                    self.read(erp, self._root(erp, revision="24.0"))

    def test_a_short_commit_is_not_a_pin(self):
        for erp in ERPS:
            with self.subTest(erp=erp):
                with self.assertRaises(pin.PinError):
                    self.read(erp, self._root(erp, revision=COMMIT[:12]))

    def test_missing_json_raises_pin_error_not_os_error(self):
        # Le menu ne rattrape qu'UNE exception pour dire pourquoi l'entrée
        # manque ; un FileNotFoundError ferait tomber tout l'écran.
        for erp in ERPS:
            with self.subTest(erp=erp):
                with self.assertRaises(pin.PinError) as ctx:
                    self.read(erp, self._root(erp, pin_data=None))
                self.assertIn(paths(erp)[0], str(ctx.exception))

    def test_missing_manifest_raises_pin_error(self):
        for erp in ERPS:
            with self.subTest(erp=erp):
                with self.assertRaises(pin.PinError) as ctx:
                    self.read(erp, self._root(erp, text=False))
                self.assertIn(paths(erp)[1], str(ctx.exception))

    def test_manifest_without_the_erp_project_is_refused(self):
        for erp in ERPS:
            with self.subTest(erp=erp):
                root = self._root(
                    erp,
                    text='<manifest><remote name="x" fetch="https://x/" />'
                    "</manifest>",
                )
                with self.assertRaises(pin.PinError) as ctx:
                    self.read(erp, root)
                self.assertIn(f"group {erp}", str(ctx.exception))

    def test_the_project_of_another_group_is_not_taken(self):
        # Le manifest d'un ERP ne répond pas pour l'autre.
        root = self._root(
            "acme", text=manifest_for("dolibarr", rev=COMMIT, branch="24.0")
        )
        with self.assertRaises(pin.PinError):
            self.read("acme", root)

    def test_the_project_is_found_by_its_group_not_its_rank(self):
        # Un manifest fusionné porte d'autres projets avant celui de l'ERP :
        # prendre le premier venu épinglerait un autre dépôt.
        other = (
            '    <project name="erplibre.git" path="." remote="Upstream"'
            ' revision="fedcba9876543210fedcba9876543210fedcba98"'
            ' upstream="24.0" groups="base" />\n'
        )
        for erp in ERPS:
            with self.subTest(erp=erp):
                text = manifest_for(erp, rev=COMMIT, branch="24.0").replace(
                    "    <project\n", other + "    <project\n"
                )
                got = self.read(erp, self._root(erp, text=text))
                self.assertEqual(got["commit"], COMMIT)
                self.assertEqual(got["path"], f"{erp}/{erp}")

    def test_json_missing_a_key_is_refused(self):
        data = dict(PIN)
        del data["version"]
        for erp in ERPS:
            with self.subTest(erp=erp):
                with self.assertRaises(pin.PinError) as ctx:
                    self.read(erp, self._root(erp, pin_data=data))
                self.assertIn("version", str(ctx.exception))

    def test_only_the_keys_asked_are_required_and_returned(self):
        # Un ERP sans PHP ne déclare ni php_min ni php_max.
        data = {"version": "1.2.3", "branch": "24.0", "image": "x:1"}
        root = self._root("acme", pin_data=data)
        json_rel, manifest_rel = paths("acme")
        got = pin.read_pin(
            root, json_rel, manifest_rel, "acme", ("version", "branch")
        )
        self.assertEqual(
            got,
            {
                "version": "1.2.3",
                "branch": "24.0",
                "commit": COMMIT,
                "path": "acme/acme",
            },
        )


class TestRewriteManifest(unittest.TestCase):
    def test_only_the_erp_pin_changes(self):
        for erp in ERPS:
            with self.subTest(erp=erp):
                avant = manifest_for(erp, rev=ANCIEN, branch="24.0")
                apres = pin.rewrite_manifest(avant, NOUVEAU, "25.0", erp)
                self.assertEqual(
                    apres, manifest_for(erp, rev=NOUVEAU, branch="25.0")
                )

    def test_another_project_keeps_its_revision(self):
        autre = (
            '    <project name="x.git" path="x" remote="Upstream"'
            f' revision="{ANCIEN}" upstream="24.0" groups="base" />\n'
        )
        for erp in ERPS:
            with self.subTest(erp=erp):
                avant = manifest_for(erp, rev=ANCIEN, branch="24.0").replace(
                    "</manifest>", autre + "</manifest>"
                )
                apres = pin.rewrite_manifest(avant, NOUVEAU, "24.0", erp)
                self.assertIn(autre, apres)
                self.assertEqual(apres.count(NOUVEAU), 1)


class TestRewriteRefuses(unittest.TestCase):
    def test_no_erp_project_is_refused(self):
        for erp in ERPS:
            with self.subTest(erp=erp):
                with self.assertRaises(ValueError):
                    pin.rewrite_manifest("<manifest />", NOUVEAU, "24.0", erp)

    def test_the_project_of_another_group_is_refused(self):
        avant = manifest_for("dolibarr", rev=ANCIEN, branch="24.0")
        with self.assertRaises(ValueError) as ctx:
            pin.rewrite_manifest(avant, NOUVEAU, "24.0", "acme")
        self.assertIn("acme", str(ctx.exception))

    def test_two_erp_projects_are_refused(self):
        # Réécrire les deux les épinglerait sur le même commit.
        for erp in ERPS:
            with self.subTest(erp=erp):
                un = manifest_for(erp, rev=ANCIEN, branch="24.0")
                projet = un[un.index("    <project") : un.index("</manifest>")]
                deux = un.replace("</manifest>", projet + "</manifest>")
                with self.assertRaises(ValueError):
                    pin.rewrite_manifest(deux, NOUVEAU, "24.0", erp)


class TestImage(unittest.TestCase):
    def test_a_reference_splits_into_repository_tag_and_digest(self):
        self.assertEqual(
            pin.split_image(f"{DOLI}:24.0.0@{D_2400}"),
            (DOLI, "24.0.0", D_2400),
        )
        self.assertEqual(
            pin.split_image(f"{MARIA}:11.4"), (MARIA, "11.4", None)
        )

    def test_a_reference_is_rebuilt_from_its_parts(self):
        self.assertEqual(
            pin.image_ref(DOLI, "24.0.0", D_2400), f"{DOLI}:24.0.0@{D_2400}"
        )
        self.assertEqual(pin.image_ref(MARIA, "11.4", None), f"{MARIA}:11.4")


class Hub:
    """hub_digest simulé d'après une table (dépôt, étiquette)."""

    def __init__(self, table):
        self.table = table

    def hub_digest(self, repo, tag):
        return self.table.get((repo, tag))


class TestRefreshedImage(unittest.TestCase):
    def test_the_own_tag_takes_the_hub_digest(self):
        net = Hub({(MARIA, "11.4"): D_MARIA})
        self.assertEqual(
            pin.refreshed_image(net, f"{MARIA}:11.4"),
            f"{MARIA}:11.4@{D_MARIA}",
        )

    def test_a_given_tag_replaces_the_own_one(self):
        net = Hub({(DOLI, "24.0.0"): D_2400})
        self.assertEqual(
            pin.refreshed_image(net, f"{DOLI}:23.0.0", "24.0.0"),
            f"{DOLI}:24.0.0@{D_2400}",
        )

    def test_a_tag_unknown_to_the_hub_keeps_the_current_reference(self):
        current = f"{DOLI}:23.0.0@{D_2400}"
        self.assertEqual(
            pin.refreshed_image(Hub({}), current, "24.0.0"), current
        )


class TestHub(unittest.TestCase):
    """Network.hub_digest lit la réponse du Hub, sans réseau ici."""

    def lire(self, corps):
        reponse = mock.MagicMock()
        reponse.__enter__.return_value = io.BytesIO(corps.encode())
        with mock.patch.object(
            pin.urllib.request, "urlopen", return_value=reponse
        ) as urlopen:
            digest = pin.Network("https://example.org/x.git").hub_digest(
                DOLI, "24.0.0"
            )
        return digest, urlopen.call_args[0][0]

    def test_the_digest_of_the_tag(self):
        digest, url = self.lire(json.dumps({"digest": D_2400}))
        self.assertEqual(digest, D_2400)
        self.assertEqual(
            url,
            "https://hub.docker.com/v2/repositories/dolibarr/dolibarr"
            "/tags/24.0.0",
        )

    def test_anything_but_a_sha256_digest_is_none(self):
        # Il finit dans une commande « run » : rien d'autre n'y entre.
        for corps in (
            json.dumps({"digest": "sha256:court"}),
            json.dumps({"digest": D_2400 + " --privileged"}),
            json.dumps({}),
            "pas du json",
        ):
            with self.subTest(corps=corps):
                self.assertIsNone(self.lire(corps)[0])


class TestLsRemote(unittest.TestCase):
    """Network.ls_remote interroge le dépôt reçu, sans réseau ici."""

    def ls(self, upstream, ref, stdout):
        done = subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")
        with mock.patch.object(
            pin.subprocess, "run", return_value=done
        ) as run:
            sha = pin.Network(upstream).ls_remote(ref)
        return sha, run.call_args[0][0]

    def test_the_upstream_given_is_queried(self):
        for erp in ERPS:
            upstream = f"https://example.org/{erp}.git"
            with self.subTest(erp=erp):
                _sha, argv = self.ls(upstream, "refs/heads/1.0", "")
                self.assertEqual(
                    argv, ["git", "ls-remote", upstream, "refs/heads/1.0"]
                )

    def test_only_the_exact_ref_answers(self):
        # ls-remote filtre par motif : refs/tags/1.0 rend aussi sa forme
        # pelée, dont le sha est un autre objet.
        stdout = f"{TAG}\trefs/tags/1.0\n{NOUVEAU}\trefs/tags/1.0^{{}}\n"
        sha, _argv = self.ls(
            "https://example.org/x.git", "refs/tags/1.0", stdout
        )
        self.assertEqual(sha, TAG)

    def test_an_absent_ref_is_none(self):
        sha, _argv = self.ls("https://example.org/x.git", "refs/heads/9", "")
        self.assertIsNone(sha)


class Refs:
    """ls_remote simulé d'après une table de refs."""

    def __init__(self, refs):
        self.refs = refs

    def ls_remote(self, ref):
        return self.refs.get(ref)


class TestTarget(unittest.TestCase):
    def test_without_tag_the_branch_head_is_aimed(self):
        net = Refs({"refs/heads/24.0": NOUVEAU})
        self.assertEqual(
            pin.target(net, "24.0", None), (NOUVEAU, "refs/heads/24.0")
        )

    def test_an_annotated_tag_resolves_to_its_peeled_commit(self):
        net = Refs({"refs/tags/1.0^{}": TAG, "refs/tags/1.0": ANCIEN})
        self.assertEqual(
            pin.target(net, "24.0", "1.0"), (TAG, "refs/tags/1.0^{}")
        )

    def test_a_lightweight_tag_resolves_to_itself(self):
        net = Refs({"refs/tags/1.0": TAG})
        self.assertEqual(
            pin.target(net, "24.0", "1.0"), (TAG, "refs/tags/1.0")
        )

    def test_an_unknown_tag_is_none(self):
        self.assertEqual(
            pin.target(Refs({}), "24.0", "9.9"), (None, "refs/tags/9.9")
        )


if __name__ == "__main__":
    unittest.main()
