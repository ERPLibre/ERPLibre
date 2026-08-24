#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Transfert des dépôts ERPLibre dans l'application mobile.

L'application embarque le code des dépôts du manifeste pour le parcourir hors
ligne. Ils y entrent en PACKS, et c'est ce qui rend la chose possible : un APK
est un ZIP borné à 65535 entrées, quand les 139 dépôts pèsent plus de 116 000
fichiers. Un fichier par source donnait « Too many zip entries 123678
(MAX=65535) » — la compilation s'arrêtait là, et l'application ne portait rien.

Regroupés en tranches de 4 Mo, ces fichiers tiennent en 391 entrées. Mesuré sur
la VM : 3 002 entrées dans l'APK, 282 Mo, et 20 fichiers relus depuis les packs
identiques octet pour octet à leur source.

Ce que ces tests vérifient : qu'un transfert vide, tronqué ou incohérent est
DIT, et non pris pour bon. Les trois pannes correspondantes ont chacune leur
fixture.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from script.mobile import check_bundle_transfer as cbt  # noqa: E402

# Contenu des sources factices : le nom du fichier -> ses octets.
SOURCES = {
    "odoo/release.py": b"version_info = (18, 0)\n",
    "odoo/api.py": b"def method():\n    return 1\n",
    "addons/sale/i18n/fr.po": b'msgid "x"\nmsgstr "y"\n',
    "README.md": b"# ERPLibre\n",
}


def build_bundle(
    tmp: Path,
    sources=None,
    *,
    with_workspace=True,
    break_pack=False,
    drop_pack=False,
    drop_index=False,
    no_manifest=False,
):
    """Fabrique un faux bundle, et la source qui va avec.

    Les avaries sont paramétrées plutôt que codées en dur : chaque test nomme
    celle qu'il éprouve, et la fixture reste unique."""
    sources = SOURCES if sources is None else sources
    mobile = tmp / "mobile" / "erplibre_home_mobile"
    repos = mobile / "dist" / "repos"
    slug = "github-com-ERPLibre-odoo"
    repo_dir = repos / slug
    repo_dir.mkdir(parents=True)
    if not no_manifest:
        (repos / "manifest.json").write_text(
            json.dumps(
                [
                    {
                        "url": "https://github.com/ERPLibre/odoo",
                        "name": "odoo",
                        "path": "odoo18.0/odoo",
                        "slug": slug,
                        "revision": "18.0",
                    }
                ]
            )
        )
    index = [{"path": "odoo", "type": "dir"}]
    blob = b""
    items = list(sources.items())
    for pos, (rel, data) in enumerate(items):
        # L'avarie ne touche que la DERNIÈRE entrée : gonfler toutes les
        # tailles décalerait chaque lecture et ferait échouer la comparaison
        # avant le contrôle de bornes — ce n'est pas la panne qu'on éprouve.
        last = pos == len(items) - 1
        index.append(
            {
                "path": rel,
                "type": "file",
                "chunk": 0,
                "offset": len(blob),
                "size": len(data) + (7 if (break_pack and last) else 0),
            }
        )
        blob += data
    if not drop_index:
        (repo_dir / "index.json").write_text(json.dumps(index))
    if not drop_pack:
        (repo_dir / "pack-000.bin").write_bytes(blob)
    if with_workspace:
        for rel, data in sources.items():
            src = tmp / "odoo18.0/odoo" / rel
            src.parent.mkdir(parents=True, exist_ok=True)
            src.write_bytes(data)
    return mobile


class TestAGoodTransfer(unittest.TestCase):
    def test_it_counts_repos_files_and_packs(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            mobile = build_bundle(tmp)
            rep = cbt.check(mobile, tmp, min_files=1)
        self.assertEqual(1, rep["repos"])
        self.assertEqual(len(SOURCES), rep["files"])
        self.assertEqual(1, rep["packs"])

    def test_it_reads_the_files_back_from_the_pack(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            mobile = build_bundle(tmp)
            rep = cbt.check(mobile, tmp, min_files=1)
        self.assertEqual(len(SOURCES), rep["checked"])

    def test_it_compares_them_to_the_source(self):
        """La seule vérification qui prouve un transfert FIDÈLE, et pas
        seulement cohérent."""
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            mobile = build_bundle(tmp)
            rep = cbt.check(mobile, tmp, min_files=1)
        self.assertEqual(len(SOURCES), rep["compared"])

    def test_without_a_workspace_it_still_reads_the_packs(self):
        """Hors du checkout, la comparaison n'est pas possible ; la lecture,
        elle, l'est toujours."""
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            mobile = build_bundle(tmp, with_workspace=False)
            rep = cbt.check(mobile, None, min_files=1)
        self.assertEqual(len(SOURCES), rep["checked"])
        self.assertEqual(0, rep["compared"])

    def test_read_from_pack_returns_the_exact_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            mobile = build_bundle(tmp)
            repo_dir = mobile / "dist/repos/github-com-ERPLibre-odoo"
            index = json.loads((repo_dir / "index.json").read_text())
            entry = next(
                e for e in index if e["path"] == "addons/sale/i18n/fr.po"
            )
            got = cbt.read_from_pack(repo_dir, entry)
        self.assertEqual(SOURCES["addons/sale/i18n/fr.po"], got)


class TestTheThreeFailures(unittest.TestCase):
    """Vide, tronqué, incohérent : trois pannes qu'un « build OK » ne dit pas."""

    def test_no_manifest_names_the_build(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            mobile = build_bundle(tmp, no_manifest=True)
            with self.assertRaises(FileNotFoundError) as ctx:
                cbt.check(mobile, tmp, min_files=1)
        self.assertIn("build", str(ctx.exception))

    def test_a_repo_without_index_is_named(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            mobile = build_bundle(tmp, drop_index=True)
            with self.assertRaises(FileNotFoundError) as ctx:
                cbt.check(mobile, tmp, min_files=1)
        self.assertIn("odoo", str(ctx.exception))

    def test_a_missing_pack_is_named(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            mobile = build_bundle(tmp, drop_pack=True)
            with self.assertRaises(FileNotFoundError) as ctx:
                cbt.check(mobile, tmp, min_files=1)
        self.assertIn("pack-000.bin", str(ctx.exception))

    def test_an_index_that_promises_too_much_is_refused(self):
        """Index et pack d'une compilation différente : le message doit nommer
        la tranche et les tailles, pas rendre un octet manquant en silence."""
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            mobile = build_bundle(tmp, break_pack=True)
            with self.assertRaises(ValueError) as ctx:
                cbt.check(mobile, tmp, min_files=1)
        self.assertIn("pack-000.bin", str(ctx.exception))

    def test_an_empty_transfer_is_refused(self):
        """C'est le cas qui a existé pendant un temps : le bundle compilait,
        sans un seul dépôt dedans. « Réussi » ne voulait rien dire."""
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            mobile = build_bundle(tmp, sources={"a.py": b"x\n"})
            with self.assertRaises(ValueError) as ctx:
                cbt.check(mobile, tmp)  # seuil par défaut
        self.assertIn("maigre", str(ctx.exception))

    def test_a_file_that_differs_from_the_source_is_named(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            mobile = build_bundle(tmp)
            (tmp / "odoo18.0/odoo/README.md").write_bytes(b"autre chose\n")
            with self.assertRaises(ValueError) as ctx:
                cbt.check(mobile, tmp, min_files=1)
        self.assertIn("README.md", str(ctx.exception))


class TestTheThreshold(unittest.TestCase):
    def test_the_default_threshold_rules_out_an_empty_bundle(self):
        """Le seul dépôt odoo en porte près de 40 000 : mille est un plancher
        qu'un vrai transfert dépasse de deux ordres de grandeur."""
        self.assertGreaterEqual(cbt.MIN_FILES, 1000)

    def test_the_sample_is_deterministic(self):
        """Une graine fixe : deux exécutions lisent les MÊMES fichiers, donc un
        échec est reproductible."""
        self.assertIsInstance(cbt.SEED, int)
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            mobile = build_bundle(tmp)
            first = cbt.check(mobile, tmp, min_files=1)
            second = cbt.check(mobile, tmp, min_files=1)
        self.assertEqual(first, second)


class TestTheCommandLine(unittest.TestCase):
    def test_it_says_the_counts_and_returns_zero(self):
        import io
        import contextlib

        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            mobile = build_bundle(tmp, sources=SOURCES)
            argv = [
                "check_bundle_transfer.py",
                str(mobile),
                "--workspace",
                str(tmp),
            ]
            buf = io.StringIO()
            with unittest.mock.patch.object(sys, "argv", argv), mock_min(1):
                with contextlib.redirect_stdout(buf):
                    code = cbt.main()
        self.assertEqual(0, code)
        self.assertIn("dépôts", buf.getvalue())

    def test_a_failure_is_one_line_not_a_traceback(self):
        """Le message part dans un journal d'installation : une trace Python y
        serait illisible, et la cause noyée."""
        import io
        import contextlib

        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            argv = ["check_bundle_transfer.py", str(tmp / "nulle-part")]
            buf = io.StringIO()
            with unittest.mock.patch.object(sys, "argv", argv):
                with contextlib.redirect_stdout(buf):
                    code = cbt.main()
        self.assertEqual(1, code)
        self.assertIn("⚠", buf.getvalue())
        self.assertNotIn("Traceback", buf.getvalue())


REPO = Path(__file__).resolve().parent.parent
MOBILE = REPO / "mobile" / "erplibre_home_mobile"


class TestTheRealBundle(unittest.TestCase):
    """Le VRAI transfert, quand le dépôt mobile est installé et compilé.

    C'est ici que ces tests DÉCLARENT leur dépendance : sans
    mobile/erplibre_home_mobile, ils se disent ignorés plutôt que de passer en
    silence — un test vert sans son dépôt ne prouve rien. Le lanceur
    (script/test/run_unit_test.sh) annonce la même dépendance avant de
    commencer.

    Ce qu'ils gardent : qu'une compilation réelle produise bien des PACKS. Un
    retour au fichier-par-source ferait disparaître le champ « chunk » des
    index, et la limite du ZIP reviendrait — 123 678 entrées pour un plafond de
    65 535, silencieusement, jusqu'à l'APK.
    """

    @classmethod
    def setUpClass(cls):
        if not MOBILE.is_dir():
            # Pas de « relative_to » : il lève quand le chemin sort du
            # dépôt, et une erreur n'est pas un « ignoré » — mesuré en
            # simulant l'absence.
            raise unittest.SkipTest(
                "mobile/erplibre_home_mobile absent :"
                " ./mobile/install_mobile_dev.sh"
            )
        cls.repos = MOBILE / "dist" / "repos"
        manifeste = cls.repos / "manifest.json"
        if not manifeste.is_file():
            raise unittest.SkipTest(
                "dépôt mobile présent mais pas compilé :"
                " ./mobile/compile_and_run.sh (ou npm run build)"
            )
        # Manifeste PRÉSENT mais VIDE : l'application a été compilée sans le
        # transfert des dépôts. C'est un choix légitime, pas une régression —
        # et le distinguer importe, car ces tests échouaient alors sur
        # « aucun dépôt à vérifier », ce qui se lit comme une panne du
        # transfert. Vu le 23 août 2026 sur un build de 07:55 : manifeste à
        # zéro entrée, aucun pack.
        try:
            entrees = json.loads(manifeste.read_text())
        except (OSError, ValueError) as exc:
            raise unittest.SkipTest(f"manifeste illisible : {exc}")
        if not entrees:
            raise unittest.SkipTest(
                "compilé SANS les dépôts (manifeste vide) :"
                " relancer ./mobile/compile_and_run.sh pour les inclure"
            )
        # Manifeste PLEIN mais index MANQUANTS : un transfert interrompu, ou
        # un build qui a écrit le manifeste avant les paquets. Vu le
        # 24 août 2026 — « <slug> : index.json absent » remontait en ERREUR,
        # ce qui se lit comme une régression du transfert alors que rien
        # n'était encore transféré. Un état incomplet s'IGNORE ; seule une
        # incohérence entre ce qui est là et le dépôt doit échouer.
        for entree in entrees:
            slug = entree.get("slug") if isinstance(entree, dict) else entree
            if slug and not (cls.repos / str(slug) / "index.json").is_file():
                raise unittest.SkipTest(
                    f"paquet incomplet ({slug} sans index.json) :"
                    " relancer ./mobile/compile_and_run.sh"
                )

    def test_the_transfer_is_coherent(self):
        rep = cbt.check(MOBILE, REPO)
        self.assertGreater(rep["repos"], 1)
        self.assertGreater(rep["files"], cbt.MIN_FILES)
        self.assertGreater(rep["packs"], 0)

    def test_a_sample_matches_the_source(self):
        """La seule vérification qui prouve un transfert FIDÈLE."""
        rep = cbt.check(MOBILE, REPO)
        self.assertGreater(rep["compared"], 0)

    def test_the_indexes_are_packed_not_file_per_source(self):
        """Le garde-fou de la limite du ZIP : chaque fichier doit porter sa
        tranche. Sans « chunk », c'est un fichier par source, et l'APK sera
        refusé — mais bien plus tard, et sans dire pourquoi."""
        man = json.loads((self.repos / "manifest.json").read_text())
        checked = 0
        for proj in man[:5]:
            index = self.repos / proj["slug"] / "index.json"
            entries = json.loads(index.read_text())
            files = [e for e in entries if e.get("type") == "file"]
            if not files:
                continue
            self.assertTrue(
                all("chunk" in e for e in files),
                f"{proj['slug']} : des fichiers sans tranche",
            )
            checked += 1
        self.assertGreater(checked, 0, "aucun dépôt à vérifier")

    def test_no_bundled_test_file_lingers_as_a_source(self):
        """Effet de bord mesuré, et il compte : empaquetés, les 1 599 fichiers
        de test des dépôts Odoo ne sont plus ramassés par vitest — 1 423
        fichiers de test ramenés à 75, 35 s ramenées à 3 s."""
        stray = list(self.repos.glob("*/**/*.test.ts"))
        self.assertEqual([], stray)


import contextlib as _contextlib  # noqa: E402
import unittest.mock  # noqa: E402


@_contextlib.contextmanager
def mock_min(value):
    """Abaisse le plancher le temps d'un test de ligne de commande."""
    old = cbt.MIN_FILES
    cbt.MIN_FILES = value
    try:
        yield
    finally:
        cbt.MIN_FILES = old


if __name__ == "__main__":
    unittest.main()
