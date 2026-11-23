#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le cache d'images de deploy_qemu : image périmée, `.part` et droits.

Ces tests gardent :

- une image en cache dont la somme publiée a changé (une image « latest »
  republiée) reprise par un téléchargement neuf, jugé AVANT de remplacer
  l'ancienne : refusé, il est écarté et l'ancienne reste ;
- un `.part` qui ne s'efface pas, dans un répertoire accessible : le
  transfert part vers un nom neuf du même répertoire ;
- un répertoire de cache refusé à l'utilisateur, sans sudo : un refus clair
  AVANT le moindre octet, et non « vérifiez la connectivité » ;
- le même répertoire avec sudo : le `.part` d'un autre compte retiré, le
  nouveau créé au nom de l'utilisateur, puis chown et mv par sudo.

Ni réseau ni sudo : `_download_one` et l'URL des sommes sont remplacés par
des faux, et le Runner exécute ses commandes sans sudo, dans un répertoire
temporaire que `os.access` déclare refusé.
"""

import contextlib
import hashlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.qemu import deploy_qemu as d  # noqa: E402

NOM = "image.qcow2"
URL = f"https://miroir.invalid/latest/{NOM}"
ANCIENNE = b"image en cache, version precedente"
NOUVELLE = b"image republiee sous le meme nom" * 100


class FauxReseau:
    """`_download_one` et le fichier de sommes, sans réseau.

    `servi` est ce que le miroir rend pour l'image ; `publie` ce que le
    fichier de sommes déclare. `pannes` : exceptions levées aux premières
    demandes de l'image, dans l'ordre."""

    def __init__(self, servi=NOUVELLE, publie=NOUVELLE, pannes=()):
        self.servi = servi
        self.publie = publie
        self.pannes = list(pannes)
        self.demandes = []

    def telecharge(self, url, tmp, timeout, depuis=0):
        self.demandes.append(url)
        if self.pannes:
            raise self.pannes.pop(0)
        with open(tmp, "wb") as fh:
            fh.write(self.servi)

    def urlopen(self, *_a, **_k):
        corps = f"{hashlib.sha256(self.publie).hexdigest()}  {NOM}\n".encode()
        return contextlib.nullcontext(io.BytesIO(corps))

    @contextlib.contextmanager
    def actif(self):
        with (
            mock.patch.object(d, "_download_one", self.telecharge),
            mock.patch.object(d.urllib.request, "urlopen", self.urlopen),
        ):
            yield


class RunnerSansSudo:
    """Un Runner qui exécute ses commandes telles quelles, sans sudo, et les
    note : (commande, privileged, check)."""

    use_sudo = True

    def __init__(self):
        self.commandes = []

    def run(self, cmd, *, privileged=False, check=True, capture=False):
        self.commandes.append((list(cmd), privileged, check))
        res = subprocess.run(cmd, check=False)
        if check and res.returncode:
            raise SystemExit(f"échec : {cmd}")
        return (res.returncode, "") if capture else None

    def outils(self):
        return [c[0][0] for c in self.commandes]


class Cas(unittest.TestCase):
    def setUp(self):
        coin = tempfile.TemporaryDirectory()
        self.addCleanup(coin.cleanup)
        self.rep = Path(coin.name)
        self.dest = self.rep / NOM
        self.part = self.rep / f"{NOM}.part"

    def refuse_le_repertoire(self):
        """`os.access` répond « écriture refusée » pour le répertoire du
        cache seulement : le reste du système garde sa vraie réponse."""
        vrai = os.access
        rep = str(self.rep)

        def access(chemin, mode, *a, **k):
            if str(chemin) == rep and mode & os.W_OK:
                return False
            return vrai(chemin, mode, *a, **k)

        patch = mock.patch.object(d.os, "access", access)
        patch.start()
        self.addCleanup(patch.stop)

    def verifie(self, reseau, runner=None):
        """verify_sha256 sur self.dest ; rend (sortie, message de sortie)."""
        sortie = io.StringIO()
        message = None
        with reseau.actif(), contextlib.redirect_stdout(sortie):
            try:
                d.verify_sha256(
                    URL, self.dest, False, "arch", (URL,), runner=runner
                )
            except SystemExit as exc:
                message = str(exc)
        return sortie.getvalue(), message


class TestImagePerimee(Cas):
    def test_l_image_perimee_est_remplacee_et_le_dit(self):
        self.dest.write_bytes(ANCIENNE)
        reseau = FauxReseau()
        sortie, message = self.verifie(reseau)
        self.assertIsNone(message)
        self.assertEqual(NOUVELLE, self.dest.read_bytes())
        self.assertEqual(1, len(reseau.demandes))
        self.assertIn("Image en cache périmée", sortie)
        self.assertIn("reste en place tant que la nouvelle", sortie)
        self.assertFalse(self.part.exists())

    def test_une_reprise_non_conforme_garde_l_ancienne_image(self):
        """Le miroir sert autre chose que ce que la somme déclare : les
        octets neufs sont écartés AVANT d'avoir remplacé l'ancienne image."""
        self.dest.write_bytes(ANCIENNE)
        reseau = FauxReseau(servi=b"ni l'une ni l'autre")
        _sortie, message = self.verifie(reseau)
        self.assertIsNotNone(message)
        self.assertIn("NON conforme", message)
        self.assertIn("ancienne image reste en place", message)
        self.assertEqual(ANCIENNE, self.dest.read_bytes())
        self.assertFalse(self.part.exists())
        self.assertEqual(1, len(reseau.demandes))

    def test_l_ancienne_image_n_est_jamais_absente(self):
        """Pendant le contrôle de la nouvelle, l'ancienne est toujours là :
        une conversion lancée à ce moment la trouve entière."""
        self.dest.write_bytes(ANCIENNE)
        vu = []
        vrai = d.download_image

        def espion(*a, controle=None, **k):
            def juge(chemin):
                vu.append(self.dest.read_bytes())
                return controle(chemin)

            return vrai(*a, controle=juge, **k)

        with mock.patch.object(d, "download_image", espion):
            _sortie, message = self.verifie(FauxReseau())
        self.assertIsNone(message)
        self.assertEqual([ANCIENNE], vu)

    def test_une_image_absente_non_conforme_n_est_jamais_posee(self):
        reseau = FauxReseau(servi=b"autre chose")
        _sortie, message = self.verifie(reseau)
        self.assertIn("rien n'a été posé", message)
        self.assertFalse(self.dest.exists())
        self.assertFalse(self.part.exists())

    def test_une_image_conforme_ne_retelecharge_rien(self):
        self.dest.write_bytes(NOUVELLE)
        reseau = FauxReseau()
        _sortie, message = self.verifie(reseau)
        self.assertIsNone(message)
        self.assertEqual([], reseau.demandes)

    def test_download_image_rend_false_sur_refus(self):
        reseau = FauxReseau()
        with reseau.actif(), contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(
                d.download_image(
                    [URL, "https://autre.invalid/i"],
                    self.dest,
                    False,
                    controle=lambda chemin: False,
                )
            )
        self.assertEqual([URL], reseau.demandes, "un autre miroir essayé")
        self.assertFalse(self.dest.exists())
        self.assertFalse(self.part.exists())


class TestImageFraiche(Cas):
    """Une image que l'appelant vient de télécharger n'est pas une image
    gardée : un écart la condamne, sans reprise ni « cache périmé »."""

    def test_une_image_fraiche_non_conforme_est_effacee(self):
        reseau = FauxReseau(servi=b"octets faux")
        sortie = io.StringIO()
        message = None
        with reseau.actif(), contextlib.redirect_stdout(sortie):
            self.assertFalse(d.image_en_cache(self.dest))
            d.download_image([URL], self.dest, False)
            try:
                d.verify_sha256(
                    URL, self.dest, False, "arch", (URL,), frais=True
                )
            except SystemExit as exc:
                message = str(exc)
        self.assertIn("Image supprimée", message)
        self.assertNotIn("périmée", sortie.getvalue())
        self.assertFalse(self.dest.exists())
        self.assertEqual(1, len(reseau.demandes), "reprise inattendue")

    def test_une_image_fraiche_conforme_reste(self):
        reseau = FauxReseau()
        with reseau.actif(), contextlib.redirect_stdout(io.StringIO()):
            d.download_image([URL], self.dest, False)
            d.verify_sha256(URL, self.dest, False, "arch", (URL,), frais=True)
        self.assertEqual(NOUVELLE, self.dest.read_bytes())

    def test_un_fichier_vide_n_est_pas_en_cache(self):
        self.dest.write_bytes(b"")
        self.assertFalse(d.image_en_cache(self.dest))
        self.dest.write_bytes(ANCIENNE)
        self.assertTrue(d.image_en_cache(self.dest))

    def lance_main(self, presente):
        """main() en --download-only, téléchargement et vérifications
        remplacés : rend la valeur de `frais` passée à verify_sha256."""
        if presente:
            (self.rep / "debian-12-genericcloud-amd64.qcow2").write_bytes(
                ANCIENNE
            )
        vu = {}

        def verifie(*_a, frais=False, **_k):
            vu["frais"] = frais

        argv = [
            "deploy_qemu.py",
            "--download-only",
            "--distro",
            "debian",
            "--version",
            "12",
            "--image-dir",
            str(self.rep),
            "--no-sudo",
        ]
        with (
            mock.patch.object(sys, "argv", argv),
            mock.patch.object(d, "download_image", return_value=True),
            mock.patch.object(d, "verify_pinned_sha256"),
            mock.patch.object(d, "verify_sha256", verifie),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            d.main()
        return vu.get("frais")

    def test_main_dit_si_l_image_etait_en_cache(self):
        self.assertTrue(self.lance_main(presente=False))
        self.assertFalse(self.lance_main(presente=True))


class TestPartIneffacable(Cas):
    def test_un_part_qui_ne_s_efface_pas_ne_bloque_rien(self):
        """Laissé par un autre compte dans un répertoire à sticky bit, le
        `.part` refuse de partir : le transfert prend un nom neuf."""
        self.part.write_bytes(b"reste d'un autre compte")
        vrai = Path.unlink
        cible = self.part

        def unlink(chemin, *a, **k):
            if chemin == cible:
                raise PermissionError(1, "Operation not permitted")
            return vrai(chemin, *a, **k)

        reseau = FauxReseau()
        sortie = io.StringIO()
        with (
            mock.patch.object(Path, "unlink", unlink),
            reseau.actif(),
            contextlib.redirect_stdout(sortie),
        ):
            self.assertTrue(d.download_image([URL], self.dest, False))
        self.assertEqual(NOUVELLE, self.dest.read_bytes())
        self.assertIn("ne s'efface pas", sortie.getvalue())
        restes = sorted(p.name for p in self.rep.glob("*.part"))
        self.assertEqual([self.part.name], restes, "nom neuf laissé derrière")


class TestRepertoireRefuse(Cas):
    def setUp(self):
        super().setUp()
        self.refuse_le_repertoire()

    def test_sans_sudo_le_refus_est_dit_avant_tout_octet(self):
        self.dest.write_bytes(ANCIENNE)
        reseau = FauxReseau()
        _sortie, message = self.verifie(reseau, runner=None)
        self.assertIn("Écriture refusée", message)
        self.assertIn("--image-dir", message)
        self.assertIn("ancienne image reste en place", message)
        self.assertNotIn("connectivité", message)
        self.assertEqual([], reseau.demandes)
        self.assertEqual(ANCIENNE, self.dest.read_bytes())

    def test_no_sudo_vaut_sans_sudo(self):
        runner = RunnerSansSudo()
        runner.use_sudo = False
        reseau = FauxReseau()
        with reseau.actif(), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as sortie:
                d.download_image([URL], self.dest, False, runner=runner)
        self.assertIn("Écriture refusée", str(sortie.exception))
        self.assertEqual([], runner.commandes)

    def test_avec_sudo_le_part_d_un_autre_compte_est_remplace(self):
        """Le `.part` laissé par root part avec le même droit ; le nouveau
        est créé au nom de l'utilisateur, puis posé par chown et mv."""
        self.dest.write_bytes(ANCIENNE)
        self.part.write_bytes(b"reste laisse par root")
        runner = RunnerSansSudo()
        _sortie, message = self.verifie(FauxReseau(), runner=runner)
        self.assertIsNone(message)
        self.assertEqual(NOUVELLE, self.dest.read_bytes())
        self.assertFalse(self.part.exists())
        self.assertEqual(["rm", "install", "chown", "mv"], runner.outils())
        self.assertTrue(all(priv for _c, priv, _k in runner.commandes))
        install = runner.commandes[1][0]
        self.assertEqual(str(os.getuid()), install[install.index("-o") + 1])

    def test_avec_sudo_le_verrou_absent_est_cree_d_abord(self):
        runner = RunnerSansSudo()
        with FauxReseau().actif(), contextlib.redirect_stdout(io.StringIO()):
            d.download_image([URL], self.dest, False, runner=runner)
        self.assertEqual("touch", runner.outils()[0])
        self.assertTrue(Path(f"{self.dest}.lock").exists())

    def test_avec_sudo_un_verrou_present_n_est_pas_recree(self):
        Path(f"{self.dest}.lock").touch()
        runner = RunnerSansSudo()
        with FauxReseau().actif(), contextlib.redirect_stdout(io.StringIO()):
            d.download_image([URL], self.dest, False, runner=runner)
        self.assertNotIn("touch", runner.outils())
        self.assertEqual(NOUVELLE, self.dest.read_bytes())

    def test_avec_sudo_un_echec_retire_le_part(self):
        runner = RunnerSansSudo()
        perdu = urllib.error.HTTPError(URL, 404, "Not Found", {}, None)
        reseau = FauxReseau(pannes=[perdu])
        with reseau.actif(), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit):
                d.download_image([URL], self.dest, False, runner=runner)
        self.assertFalse(self.part.exists())
        self.assertFalse(self.dest.exists())
        rm_final = runner.commandes[-1]
        self.assertEqual("rm", rm_final[0][0])
        self.assertFalse(rm_final[2], "un rm final qui échoue arrête tout")

    def test_avec_sudo_une_reprise_refusee_garde_l_ancienne(self):
        self.dest.write_bytes(ANCIENNE)
        runner = RunnerSansSudo()
        _sortie, message = self.verifie(
            FauxReseau(servi=b"autre chose"), runner=runner
        )
        self.assertIn("ancienne image reste en place", message)
        self.assertEqual(ANCIENNE, self.dest.read_bytes())
        self.assertFalse(self.part.exists())
        self.assertNotIn("mv", runner.outils())


if __name__ == "__main__":
    unittest.main()
