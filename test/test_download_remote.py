#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le téléchargement d'une sauvegarde distante ne laisse qu'un vrai zip.

`script/database/download_remote.sh` appelle curl, ici remplacé par un faux
placé en tête du PATH, qui joue chaque réponse possible du serveur : un zip,
la page HTML qu'Odoo rend avec un code 200 quand il refuse la sauvegarde, une
écriture refusée (code 23), une erreur HTTP (code 22). Dans tous les cas
d'échec, aucun fichier ne reste sous le nom final, et un fichier qui s'y
trouvait déjà reste intact.

`DatabaseManager.download_database_backup_cli` vérifie ensuite le zip au
chemin choisi, et seulement quand le script a réussi.

Les noms de bases, d'hôtes et les mots de passe sont inventés.
"""

import io
import os
import stat
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from script.todo import database_manager

RACINE = Path(__file__).resolve().parents[1]
SCRIPT = RACINE / "script/database/download_remote.sh"

# Le faux curl : trouve la valeur de -o, se note comme appelé, puis joue le
# mode demandé par FAUX_CURL_MODE.
FAUX_CURL = r"""#!/usr/bin/env bash
sortie=""
while [ $# -gt 0 ]; do
  if [ "$1" = "-o" ]; then sortie="$2"; shift; fi
  shift
done
touch "$FAUX_CURL_APPELE"
case "$FAUX_CURL_MODE" in
  zip) cp "$FAUX_CURL_ZIP" "$sortie" ;;
  html)
    printf '%s' '<html><div class="alert">Database backup error: Database &#39;essai_inconnue&#39; is not known</div></html>' > "$sortie"
    ;;
  ecriture) : > "$sortie"; exit 23 ;;
  http) exit 22 ;;
esac
"""


class TestDownloadRemote(unittest.TestCase):
    def setUp(self):
        self.dossier = Path(tempfile.mkdtemp(prefix="essai_download_"))
        self.addCleanup(
            subprocess.run, ["rm", "-rf", str(self.dossier)], check=False
        )
        outils = self.dossier / "bin"
        outils.mkdir()
        curl = outils / "curl"
        curl.write_text(FAUX_CURL, encoding="utf-8")
        curl.chmod(curl.stat().st_mode | stat.S_IXUSR)
        self.zip = self.dossier / "modele.zip"
        with zipfile.ZipFile(self.zip, "w") as archive:
            archive.writestr("manifest.json", "{}")
        self.cible = self.dossier / "image_db" / "essai_2026-01-01.zip"
        self.cible.parent.mkdir()
        self.appele = self.dossier / "curl_appele"
        self.env = dict(
            os.environ,
            PATH=f"{outils}:{os.environ['PATH']}",
            MASTER_PWD="mdp_essai",
            DATABASE_NAME="essai_base",
            ODOO_URL="https://odoo.essai.invalid",
            OUTPUT_FILE_PATH=str(self.cible),
            FAUX_CURL_ZIP=str(self.zip),
            FAUX_CURL_APPELE=str(self.appele),
        )

    def lancer(self, mode, cible=None):
        env = dict(self.env, FAUX_CURL_MODE=mode)
        if cible is not None:
            env["OUTPUT_FILE_PATH"] = str(cible)
        return subprocess.run(
            ["bash", str(SCRIPT), "--quiet"],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def restes(self):
        """Les fichiers temporaires laissés à côté de la destination."""
        return sorted(p.name for p in self.cible.parent.glob("*.part.*"))

    def test_un_zip_arrive_sous_le_nom_final(self):
        sortie = self.lancer("zip")
        self.assertEqual(0, sortie.returncode, sortie.stderr)
        self.assertEqual(self.zip.read_bytes(), self.cible.read_bytes())
        self.assertEqual([], self.restes())

    def test_la_page_d_erreur_d_odoo_n_est_pas_un_zip(self):
        sortie = self.lancer("html")
        self.assertEqual(1, sortie.returncode)
        self.assertFalse(self.cible.exists())
        self.assertEqual([], self.restes())
        self.assertIn(
            "Database backup error: Database 'essai_inconnue' is not known",
            sortie.stderr,
        )

    def test_une_ecriture_refusee_ne_laisse_aucun_zip_vide(self):
        sortie = self.lancer("ecriture")
        self.assertEqual(1, sortie.returncode)
        self.assertFalse(self.cible.exists())
        self.assertEqual([], self.restes())
        self.assertIn("code 23", sortie.stderr)
        self.assertIn("df -h", sortie.stderr)

    def test_un_echec_ne_touche_pas_au_fichier_deja_la(self):
        self.cible.write_bytes(b"ancienne sauvegarde")
        for mode in ("html", "ecriture", "http"):
            with self.subTest(mode=mode):
                self.assertEqual(1, self.lancer(mode).returncode)
                self.assertEqual(
                    b"ancienne sauvegarde", self.cible.read_bytes()
                )
        self.assertEqual([], self.restes())

    def test_un_dossier_absent_arrete_avant_la_requete(self):
        absente = self.dossier / "absent" / "essai.zip"
        sortie = self.lancer("zip", cible=absente)
        self.assertEqual(1, sortie.returncode)
        self.assertIn("cannot write", sortie.stderr)
        self.assertFalse(self.appele.exists())


class TestDownloadDatabaseBackupCli(unittest.TestCase):
    """La vérification lit le chemin choisi, et seulement après un succès."""

    def setUp(self):
        self.dossier = Path(tempfile.mkdtemp(prefix="essai_download_cli_"))
        self.addCleanup(
            subprocess.run, ["rm", "-rf", str(self.dossier)], check=False
        )
        self.execute = mock.Mock()
        self.gestion = database_manager.DatabaseManager(self.execute, None)

    def telecharger(self, chemin, statut):
        self.execute.exec_command_live.return_value = (statut, "commande")
        reponses = iter(["https://odoo.essai.invalid", "essai_base", chemin])
        with (
            mock.patch("builtins.input", lambda *_: next(reponses)),
            mock.patch.object(
                database_manager.getpass, "getpass", lambda **_: "x"
            ),
            mock.patch("sys.stderr", new_callable=io.StringIO),
        ):
            return self.gestion.download_database_backup_cli(
                show_remote_list=False
            )

    def test_le_chemin_choisi_est_celui_qu_on_verifie(self):
        chemin = str(self.dossier / "choisi.zip")
        with zipfile.ZipFile(chemin, "w") as archive:
            archive.writestr("manifest.json", "{}")
        with self.assertLogs(database_manager._logger, "INFO") as journal:
            statut, rendu, base = self.telecharger(chemin, 0)
        self.assertEqual((0, chemin, "essai_base"), (statut, rendu, base))
        self.assertIn("validated", "\n".join(journal.output))

    def test_un_echec_du_script_n_est_pas_reverifie(self):
        chemin = str(self.dossier / "jamais_ecrit.zip")
        with mock.patch.object(database_manager.zipfile, "ZipFile") as ouvrir:
            statut, _rendu, _base = self.telecharger(chemin, 1)
        self.assertEqual(1, statut)
        ouvrir.assert_not_called()

    def test_un_zip_sans_manifeste_rend_un_echec(self):
        chemin = str(self.dossier / "sans_manifeste.zip")
        with zipfile.ZipFile(chemin, "w") as archive:
            archive.writestr("autre.txt", "")
        with self.assertLogs(database_manager._logger, "ERROR"):
            statut, _rendu, _base = self.telecharger(chemin, 0)
        self.assertEqual(1, statut)


if __name__ == "__main__":
    unittest.main()
