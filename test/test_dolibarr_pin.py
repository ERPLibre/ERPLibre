#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Relever le commit épinglé de Dolibarr.

Le réseau est simulé : ls-remote, le fichier version.inc.php d'un commit
et les étiquettes du Hub répondent d'après des tables écrites à la main.
Ce qui se garde :
- manifest ET JSON changent ensemble, et rien d'autre du manifest ;
- sans --apply, rien n'est écrit ;
- la version lue au commit visé doit appartenir à la branche suivie ;
- l'étiquette Docker ne suit que si le Hub la publie : sinon l'ancienne
  reste, et c'est dit ;
- les images sont épinglées par empreinte, relue au Hub à chaque update :
  une image reconstruite sous la même étiquette déplace l'épinglage.
"""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.dolibarr import lib_dolibarr, pin  # noqa: E402

# Commits et empreintes inventés.
ANCIEN = "a" * 40
NOUVEAU = "b" * 40
TAG = "c" * 40
DOLI = "docker.io/dolibarr/dolibarr"
MARIA = "docker.io/library/mariadb"
D_2400 = "sha256:" + "1" * 64
D_2400_REFAIT = "sha256:" + "4" * 64
D_2402 = "sha256:" + "2" * 64
D_MARIA = "sha256:" + "3" * 64
D_MARIA_REFAIT = "sha256:" + "5" * 64

MANIFEST = """<?xml version="1.0" encoding="UTF-8" ?>
<manifest>
    <remote name="Dolibarr" fetch="https://github.com/Dolibarr/" />
    <!-- commentaire à garder -->
    <project
        name="dolibarr.git"
        path="dolibarr/dolibarr"
        remote="Dolibarr"
        revision="{rev}"
        upstream="{branch}"
        dest-branch="{branch}"
        clone-depth="1"
        groups="dolibarr"
    />
</manifest>
"""

VERSION_INC = """<?php
define('DOL_MAJOR_VERSION', '{major}');
define('DOL_MINOR_VERSION', '{minor}');
define('DOL_VERSION', constant('DOL_MAJOR_VERSION').'.'.constant('DOL_MINOR_VERSION'));
"""


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


class TestHub(unittest.TestCase):
    """Network.hub_digest lit la réponse du Hub, sans réseau ici."""

    def lire(self, corps):
        reponse = mock.MagicMock()
        reponse.__enter__.return_value = io.BytesIO(corps.encode())
        with mock.patch.object(
            pin.urllib.request, "urlopen", return_value=reponse
        ) as urlopen:
            digest = pin.Network().hub_digest(DOLI, "24.0.0")
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


class TestParse(unittest.TestCase):
    def test_version_from_version_inc_php(self):
        texte = VERSION_INC.format(major="24", minor="0.2")
        self.assertEqual(pin.parse_version(texte), "24.0.2")

    def test_version_from_an_older_filefunc(self):
        texte = "<?php\ndefine('DOL_VERSION', '22.0.5');\n"
        self.assertEqual(pin.parse_version(texte), "22.0.5")

    def test_no_version_is_none(self):
        self.assertIsNone(pin.parse_version("<?php echo 1;"))


class TestRewriteManifest(unittest.TestCase):
    def test_only_the_dolibarr_pin_changes(self):
        avant = MANIFEST.format(rev=ANCIEN, branch="24.0")
        apres = pin.rewrite_manifest(avant, NOUVEAU, "25.0")
        self.assertEqual(apres, MANIFEST.format(rev=NOUVEAU, branch="25.0"))

    def test_another_project_keeps_its_revision(self):
        autre = (
            '    <project name="x.git" path="x" remote="Dolibarr"'
            f' revision="{ANCIEN}" upstream="24.0" groups="base" />\n'
        )
        avant = MANIFEST.format(rev=ANCIEN, branch="24.0").replace(
            "</manifest>", autre + "</manifest>"
        )
        apres = pin.rewrite_manifest(avant, NOUVEAU, "24.0")
        self.assertIn(autre, apres)
        self.assertEqual(apres.count(NOUVEAU), 1)


class TestRewriteRefuses(unittest.TestCase):
    def test_no_dolibarr_project_is_refused(self):
        with self.assertRaises(ValueError):
            pin.rewrite_manifest("<manifest />", NOUVEAU, "24.0")

    def test_two_dolibarr_projects_are_refused(self):
        # Réécrire les deux les épinglerait sur le même commit.
        un = MANIFEST.format(rev=ANCIEN, branch="24.0")
        projet = un[un.index("    <project") : un.index("</manifest>")]
        deux = un.replace("</manifest>", projet + "</manifest>")
        with self.assertRaises(ValueError):
            pin.rewrite_manifest(deux, NOUVEAU, "24.0")


class Reseau:
    """ls-remote, fichiers bruts et étiquettes du Hub, simulés."""

    def __init__(self):
        self.refs = {
            "refs/heads/24.0": NOUVEAU,
            "refs/heads/25.0": TAG,
            "refs/tags/24.0.2^{}": TAG,
        }
        self.versions = {
            NOUVEAU: VERSION_INC.format(major="24", minor="0.2"),
            TAG: VERSION_INC.format(major="24", minor="0.2"),
        }
        self.hub = {(DOLI, "24.0.0"): D_2400, (MARIA, "11.4"): D_MARIA}

    def ls_remote(self, ref):
        return self.refs.get(ref)

    def raw(self, commit, path):
        return self.versions.get(commit)

    def hub_digest(self, repo, tag):
        return self.hub.get((repo, tag))


class Banc(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.racine = Path(tmp.name)
        (self.racine / "conf").mkdir()
        (self.racine / "manifest").mkdir()
        self.json = self.racine / "conf" / "supported_version_dolibarr.json"
        self.json.write_text(
            json.dumps(
                {
                    "version": "24.0.1",
                    "branch": "24.0",
                    "docker_image": "docker.io/dolibarr/dolibarr:24.0.0",
                    "mariadb_image": "docker.io/library/mariadb:11.4",
                    "php_min": "7.2",
                    "php_max": "8.5",
                },
                indent=4,
            )
            + "\n"
        )
        self.manifest = self.racine / "manifest" / "git_manifest_dolibarr.xml"
        self.manifest.write_text(MANIFEST.format(rev=ANCIEN, branch="24.0"))
        self.net = Reseau()

    def lancer(self, *argv):
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie):
            code = pin.main(list(argv), root=str(self.racine), net=self.net)
        return code, sortie.getvalue()


class TestShow(Banc):
    def test_show_names_the_pin_and_the_branch_head(self):
        code, sortie = self.lancer("show")
        self.assertEqual(code, 0)
        self.assertIn(ANCIEN[:7], sortie)
        self.assertIn(NOUVEAU[:7], sortie)
        self.assertIn("24.0.1", sortie)


class TestUpdate(Banc):
    def test_without_apply_nothing_is_written(self):
        avant_m, avant_j = self.manifest.read_text(), self.json.read_text()
        code, sortie = self.lancer("update")
        # 3 : des changements sont montrés, rien n'est écrit.
        self.assertEqual(code, pin.PENDING)
        self.assertEqual(self.manifest.read_text(), avant_m)
        self.assertEqual(self.json.read_text(), avant_j)
        self.assertIn(NOUVEAU[:7], sortie)
        self.assertIn("24.0.2", sortie)

    def test_apply_moves_the_commit_and_the_version_together(self):
        code, _sortie = self.lancer("update", "--apply")
        self.assertEqual(code, 0)
        epingle = lib_dolibarr.read_pin(str(self.racine))
        self.assertEqual(epingle["commit"], NOUVEAU)
        self.assertEqual(epingle["version"], "24.0.2")
        self.assertIn(
            "<!-- commentaire à garder -->", self.manifest.read_text()
        )

    def test_the_docker_tag_follows_only_when_the_hub_has_it(self):
        _code, sortie = self.lancer("update", "--apply")
        data = json.loads(self.json.read_text())
        self.assertEqual(data["docker_image"], f"{DOLI}:24.0.0@{D_2400}")
        self.assertIn("24.0.0", sortie)
        self.net.hub[(DOLI, "24.0.2")] = D_2402
        self.lancer("update", "--apply")
        data = json.loads(self.json.read_text())
        self.assertEqual(data["docker_image"], f"{DOLI}:24.0.2@{D_2402}")

    def test_images_are_pinned_by_digest(self):
        # Une étiquette peut être repoussée : l'empreinte fixe ce qui tourne.
        self.lancer("update", "--apply")
        data = json.loads(self.json.read_text())
        self.assertEqual(data["mariadb_image"], f"{MARIA}:11.4@{D_MARIA}")
        self.assertEqual(
            lib_dolibarr.read_pin(str(self.racine))["docker_image"],
            f"{DOLI}:24.0.0@{D_2400}",
        )

    def test_a_rebuilt_image_moves_the_digest_of_the_same_tag(self):
        # Les images sont reconstruites (correctifs de PHP, de MariaDB) sous
        # la même étiquette : relever l'épinglage les prend.
        self.lancer("update", "--apply")
        self.net.hub[(DOLI, "24.0.0")] = D_2400_REFAIT
        self.net.hub[(MARIA, "11.4")] = D_MARIA_REFAIT
        code, sortie = self.lancer("update")
        self.assertEqual(code, pin.PENDING)
        self.assertIn(D_2400_REFAIT[:19], sortie)
        self.lancer("update", "--apply")
        data = json.loads(self.json.read_text())
        self.assertEqual(
            data["docker_image"], f"{DOLI}:24.0.0@{D_2400_REFAIT}"
        )
        self.assertEqual(
            data["mariadb_image"], f"{MARIA}:11.4@{D_MARIA_REFAIT}"
        )

    def test_a_rebuilt_mariadb_alone_is_a_change(self):
        self.lancer("update", "--apply")
        self.net.hub[(MARIA, "11.4")] = D_MARIA_REFAIT
        code, _sortie = self.lancer("update")
        self.assertEqual(code, pin.PENDING)

    def test_an_unreachable_hub_keeps_the_images(self):
        self.lancer("update", "--apply")
        avant = json.loads(self.json.read_text())
        self.net.hub = {}
        self.net.refs["refs/heads/24.0"] = TAG
        self.lancer("update", "--apply")
        data = json.loads(self.json.read_text())
        self.assertEqual(data["docker_image"], avant["docker_image"])
        self.assertEqual(data["mariadb_image"], avant["mariadb_image"])
        self.assertEqual(data["version"], "24.0.2")

    def test_a_tag_pins_its_commit(self):
        self.lancer("update", "--tag", "24.0.2", "--apply")
        self.assertEqual(
            lib_dolibarr.read_pin(str(self.racine))["commit"], TAG
        )

    def test_a_new_branch_moves_upstream_and_json_branch(self):
        self.net.versions[TAG] = VERSION_INC.format(major="25", minor="0.0")
        code, _s = self.lancer("update", "--branch", "25.0", "--apply")
        self.assertEqual(code, 0)
        epingle = lib_dolibarr.read_pin(str(self.racine))
        self.assertEqual(epingle["branch"], "25.0")
        self.assertEqual(epingle["version"], "25.0.0")

    def test_a_version_outside_the_branch_is_refused(self):
        # La tête de 25.0 annonce 24.0.2 : suivre 25.0 afficherait faux.
        code, _s = self.lancer("update", "--branch", "25.0", "--apply")
        self.assertEqual(code, 1)
        self.assertEqual(
            lib_dolibarr.read_pin(str(self.racine))["commit"], ANCIEN
        )

    def test_an_unknown_ref_is_refused(self):
        code, _s = self.lancer("update", "--tag", "99.0.0", "--apply")
        self.assertEqual(code, 1)
        self.assertEqual(
            lib_dolibarr.read_pin(str(self.racine))["commit"], ANCIEN
        )

    def test_an_unreadable_version_is_refused(self):
        self.net.versions[NOUVEAU] = None
        code, _s = self.lancer("update", "--apply")
        self.assertEqual(code, 1)

    def test_already_pinned_says_so(self):
        self.lancer("update", "--apply")
        code, sortie = self.lancer("update")
        self.assertEqual(code, 0)
        self.assertIn(pin.t("Already pinned on %s.") % NOUVEAU[:7], sortie)


if __name__ == "__main__":
    unittest.main()
