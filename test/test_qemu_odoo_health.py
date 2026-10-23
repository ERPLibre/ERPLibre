#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""La vérification d'Odoo qui clôt une installation en VM.

Le suivi d'installation lit le code de sortie de la commande distante : un
Odoo qui rend « Internal Server Error », ou qui n'a pas de rôle PostgreSQL,
doit donc faire sortir la commande en 1, et non en 0 comme un service
simplement actif.

Le snippet est lancé tel quel sous bash, avec psql, curl, systemctl, sudo et
sleep remplacés par des scripts. curl rend tour à tour les codes de
FAUX_CODES, puis répète le dernier — et, comme le vrai, n'écrit le code que
sous « -w '%{http_code}' », et le corps sauf sous « -o /dev/null » ; psql
réussit sauf si FAUX_PSQL_RC le contredit ; systemctl rend FAUX_ACTIF pour
is-active et FAUX_REDEM pour NRestarts. sleep ne dort pas.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from script.todo.qemu_install import QemuInstallMixin  # noqa: E402

FAUX = {
    "psql": """#!/bin/bash
echo "psql $*" >> "$FAUX_JOURNAL"
if [ "${FAUX_PSQL_RC:-0}" != 0 ]; then
  echo 'FATAL:  role "erplibre" does not exist' >&2
  exit "$FAUX_PSQL_RC"
fi
echo 1
""",
    "curl": """#!/bin/bash
echo "curl $*" >> "$FAUX_JOURNAL"
case " $* " in *" -o /dev/null "*) ;; *) printf '<html>corps</html>' ;; esac
case " $* " in *" -w %{http_code} "*) ;; *) exit 0 ;; esac
n=$(cat "$FAUX_COMPTE" 2>/dev/null || echo 0)
echo $((n + 1)) > "$FAUX_COMPTE"
set -- $FAUX_CODES
shift $(( n < $# ? n : $# - 1 ))
printf '%s' "$1"
# Comme le vrai : sans réponse, -w écrit 000 et curl rend 7.
[ "$1" = 000 ] && exit 7
exit 0
""",
    "systemctl": """#!/bin/bash
echo "systemctl $*" >> "$FAUX_JOURNAL"
[ "$1" = show ] && { echo "${FAUX_REDEM:-0}"; exit 0; }
exit "${FAUX_ACTIF:-0}"
""",
    "sudo": """#!/bin/bash
echo "sudo $*" >> "$FAUX_JOURNAL"
[ "$1" = journalctl ] && echo "Traceback: dernière erreur d'Odoo"
exit 0
""",
    "sleep": "#!/bin/bash\nexit 0\n",
}


class Base(unittest.TestCase):
    def lance(self, delai=30, conf="", absents=(), set_e=False, **env_faux):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        bin_dir = Path(tmp.name, "bin")
        bin_dir.mkdir()
        for nom, corps in FAUX.items():
            if nom in absents:
                continue
            f = bin_dir / nom
            f.write_text(corps, encoding="utf-8")
            f.chmod(0o755)
        svc = Path(tmp.name, "svc")
        svc.mkdir()
        (svc / "config.conf").write_text(
            "[options]\n" + conf, encoding="utf-8"
        )
        journal = Path(tmp.name, "journal")
        # PATH minimal : les vrais psql et curl de l'hôte ne doivent pas
        # répondre à la place des faux, ni manquer quand on les veut absents.
        outils = Path(tmp.name, "outils")
        outils.mkdir()
        for nom in ("sed", "head", "date", "cat", "whoami"):
            vrai = subprocess.run(
                ["bash", "-c", f"command -v {nom}"],
                capture_output=True,
                text=True,
            ).stdout.strip()
            if vrai:
                (outils / nom).symlink_to(vrai)
        env = {
            "PATH": f"{bin_dir}:{outils}",
            "HOME": tmp.name,
            "SVC_DIR": str(svc),
            "FAUX_JOURNAL": str(journal),
            "FAUX_COMPTE": str(Path(tmp.name, "compte")),
            "FAUX_CODES": "303",
        }
        env.update({k: str(v) for k, v in env_faux.items()})
        res = subprocess.run(
            [
                "/bin/bash",
                "-c",
                ("set -e; " if set_e else "")
                + QemuInstallMixin._qemu_odoo_health_cmd(delai),
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        appels = journal.read_text().splitlines() if journal.exists() else []
        return res, appels


class TestOdooSain(Base):
    def test_un_odoo_qui_repond_passe(self):
        res, appels = self.lance(conf="db_host = False\ndb_user = erplibre\n")
        self.assertEqual(0, res.returncode, res.stdout + res.stderr)
        self.assertIn("répond 303", res.stdout)
        self.assertTrue([a for a in appels if a.startswith("psql")], appels)

    def test_curl_borne_chaque_tentative(self):
        """Sans -m, un Odoo qui accepte la connexion sans répondre
        suspendrait la boucle au-delà de son échéance."""
        _res, appels = self.lance()
        self.assertTrue(
            all(" -m " in a for a in appels if a.startswith("curl")), appels
        )

    def test_un_5xx_isole_au_demarrage_n_echoue_pas(self):
        res, _ = self.lance(FAUX_CODES="502 303")
        self.assertEqual(0, res.returncode, res.stdout)

    def test_le_db_user_de_la_configuration_est_employe(self):
        _res, appels = self.lance(conf="db_user = odoo_svc\n")
        self.assertTrue(
            [a for a in appels if a.startswith("psql") and "-U odoo_svc" in a],
            appels,
        )


class TestOdooCasse(Base):
    def test_un_role_manquant_echoue_et_donne_la_commande(self):
        """Le cas qu'Odoo 15 à 17 masquent derrière le sélecteur de bases."""
        res, appels = self.lance(
            conf="db_host = False\ndb_user = erplibre\n", FAUX_PSQL_RC=2
        )
        self.assertEqual(1, res.returncode)
        self.assertIn('role "erplibre" does not exist', res.stdout)
        self.assertIn("sudo runuser -u postgres -- createuser -s", res.stdout)
        self.assertFalse([a for a in appels if a.startswith("curl")])

    def test_deux_5xx_echouent_avec_le_journal(self):
        res, appels = self.lance(FAUX_CODES="500")
        self.assertEqual(1, res.returncode)
        self.assertIn("HTTP 500", res.stdout)
        self.assertIn("dernière erreur d'Odoo", res.stdout)
        self.assertEqual(2, len([a for a in appels if a.startswith("curl")]))

    def test_un_service_qui_redemarre_en_boucle_echoue(self):
        """Restart=always le relance sans fin : « is-active » le voit souvent
        actif, NRestarts le trahit."""
        res, _ = self.lance(
            delai=0, FAUX_CODES="000", FAUX_ACTIF=0, FAUX_REDEM=3
        )
        self.assertEqual(1, res.returncode, res.stdout)
        self.assertIn("redémarré 3 fois", res.stdout)

    def test_un_service_arrete_sans_reponse_echoue(self):
        res, _ = self.lance(delai=0, FAUX_CODES="000", FAUX_ACTIF=3)
        self.assertEqual(1, res.returncode)
        self.assertIn("ne tourne plus", res.stdout)


class TestCasLimites(Base):
    def test_un_5xx_isole_a_l_echeance_n_est_pas_deux_de_suite(self):
        res, _ = self.lance(delai=0, FAUX_CODES="500", FAUX_ACTIF=0)
        self.assertEqual(0, res.returncode, res.stdout)
        self.assertIn("⚠", res.stdout)

    def test_set_e_ne_coupe_pas_l_attente(self):
        """La commande distante tourne sous « set -e », actif dans le bloc
        quand il ferme la chaîne « && » : un curl sans réponse ne doit pas
        terminer le shell avant la seconde tentative."""
        res, appels = self.lance(set_e=True, FAUX_CODES="000 303")
        self.assertEqual(0, res.returncode, res.stdout + res.stderr)
        self.assertEqual(2, len([a for a in appels if a.startswith("curl")]))

    def test_un_service_actif_mais_lent_avertit_sans_echouer(self):
        """Sous émulation, le premier démarrage peut dépasser le délai."""
        res, _ = self.lance(delai=0, FAUX_CODES="000", FAUX_ACTIF=0)
        self.assertEqual(0, res.returncode, res.stdout)
        self.assertIn("⚠", res.stdout)

    def test_un_db_host_explicite_saute_psql(self):
        """Odoo passerait par TCP avec un mot de passe que psql n'a pas."""
        res, appels = self.lance(conf="db_host = db.example.invalid\n")
        self.assertEqual(0, res.returncode, res.stdout)
        self.assertFalse([a for a in appels if a.startswith("psql")])
        self.assertIn("non vérifiée", res.stdout)

    def test_sans_psql_ni_curl_rien_n_echoue(self):
        res, _ = self.lance(absents=("psql", "curl"))
        self.assertEqual(0, res.returncode, res.stdout + res.stderr)
        self.assertIn("psql absent", res.stdout)
        self.assertIn("curl absent", res.stdout)


class TestPlaceDansLeService(unittest.TestCase):
    def test_la_verification_suit_le_fi_des_deux_voies(self):
        """Après le « fi » qui ferme les voies NixOS et systemd classique :
        placée avant, elle ne couvrirait que l'une des deux."""
        for prod in (False, True):
            with self.subTest(prod=prod):
                cmd = QemuInstallMixin._qemu_odoo_service_cmd(
                    QemuInstallMixin(), prod=prod
                )
                self.assertTrue(
                    cmd.endswith(
                        "fi; " + QemuInstallMixin._qemu_odoo_health_cmd()
                    )
                )

    def test_svc_dir_est_pose_avant_l_aiguillage(self):
        """La vérification lit $SVC_DIR/config.conf, sur NixOS aussi."""
        cmd = QemuInstallMixin._qemu_odoo_service_cmd(QemuInstallMixin())
        self.assertLess(cmd.index("SVC_DIR="), cmd.index("ID=nixos"))


if __name__ == "__main__":
    unittest.main()
