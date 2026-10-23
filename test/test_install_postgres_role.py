#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""La création du rôle PostgreSQL par les installeurs Linux.

Un rôle manquant ne se voit pas à l'installation : Odoo démarre, puis répond
« Internal Server Error » à chaque page. el_postgres_role doit donc passer
par « sudo runuser -u postgres » — « su - postgres » est refusé quand le
compte système est verrouillé, comme sous Arch, et « sudo -u postgres »
demande le mot de passe de postgres sous « Defaults targetpw », comme sous
openSUSE — et rendre 1, avec la commande à taper, quand la création échoue.

« sudo » est remplacé par un script qui journalise ses arguments et son
répertoire courant, connaît les rôles de FAUX_ROLES et rend FAUX_RC_CREATE
pour createuser. Il n'accepte que la requête à égalité exacte sur le nom :
une comparaison plus lâche prendrait « erplibre2 » pour « erplibre ».
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
LIB = ". ./script/install/lib_postgres_role.sh; el_postgres_role erplibre"
INSTALLEURS_LINUX = [
    "install_arch_linux.sh",
    "install_debian_dependency.sh",
    "install_fedora_dependency.sh",
    "install_suse_dependency.sh",
    "install_production.sh",
]

FAUX_SUDO = r"""#!/bin/bash
echo "$(pwd) | $*" >> "$FAUX_JOURNAL"
[[ "$1 $2 $3 $4" == "runuser -u postgres --" ]] || exit 99
shift 4
case "$1" in
  psql)
    [[ "$(cat)" == "SELECT 1 FROM pg_roles WHERE rolname = :'r'" ]] || exit 97
    for a in "$@"; do
      case "$a" in r=*) role="${a#r=}" ;; esac
    done
    for r in $FAUX_ROLES; do
      [[ "$r" == "$role" ]] && echo 1
    done
    exit 0 ;;
  createuser) exit "${FAUX_RC_CREATE:-0}" ;;
esac
exit 98
"""


class TestRolePostgres(unittest.TestCase):
    def lance(self, roles="", rc_create=0):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        faux = Path(tmp.name, "sudo")
        faux.write_text(FAUX_SUDO, encoding="utf-8")
        faux.chmod(0o755)
        journal = Path(tmp.name, "journal")
        env = dict(os.environ)
        env.update(
            PATH=f"{tmp.name}:{env['PATH']}",
            FAUX_JOURNAL=str(journal),
            FAUX_ROLES=roles,
            FAUX_RC_CREATE=str(rc_create),
        )
        res = subprocess.run(
            ["bash", "-c", LIB],
            cwd=RACINE,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        appels = journal.read_text().splitlines() if journal.exists() else []
        return res, appels

    def test_un_role_present_n_est_pas_recree(self):
        res, appels = self.lance(roles="postgres erplibre")
        self.assertEqual(0, res.returncode, res.stdout + res.stderr)
        self.assertIn("déjà présent", res.stdout)
        self.assertFalse([a for a in appels if "createuser" in a])

    def test_un_role_absent_est_cree_par_runuser(self):
        res, appels = self.lance(roles="postgres")
        self.assertEqual(0, res.returncode, res.stdout + res.stderr)
        self.assertIn(
            "/ | runuser -u postgres -- createuser -s erplibre", appels
        )

    def test_les_commandes_partent_de_la_racine(self):
        """Le dépôt peut être illisible pour postgres."""
        _res, appels = self.lance(roles="")
        self.assertTrue(appels)
        self.assertTrue(all(a.startswith("/ | ") for a in appels), appels)

    def test_un_echec_arrete_et_donne_la_commande(self):
        res, _appels = self.lance(roles="", rc_create=1)
        self.assertEqual(1, res.returncode)
        self.assertIn("Internal Server Error", res.stdout)
        self.assertIn(
            "sudo runuser -u postgres -- createuser -s erplibre", res.stdout
        )


FAUX_PSQL = r"""#!/bin/bash
echo "psql $*" >> "$FAUX_JOURNAL"
[[ "$(cat)" == "SELECT 1 FROM pg_roles WHERE rolname = :'r'" ]] || exit 97
for a in "$@"; do
  case "$a" in r=*) role="${a#r=}" ;; esac
done
for r in $FAUX_ROLES; do
  [[ "$r" == "$role" ]] && echo 1
done
exit 0
"""
FAUX_CREATEUSER = r"""#!/bin/bash
echo "createuser $*" >> "$FAUX_JOURNAL"
exit "${FAUX_RC_CREATE:-0}"
"""
# Aucun appel ne doit passer par sudo : il n'y a pas de compte postgres.
FAUX_SUDO_REFUSE = r"""#!/bin/bash
echo "sudo $*" >> "$FAUX_JOURNAL"
exit 99
"""


class TestRoleLocal(unittest.TestCase):
    """macOS : PostgreSQL de Homebrew, sous le compte de l'usager."""

    def lance(self, roles="", rc_create=0):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for nom, texte in (
            ("psql", FAUX_PSQL),
            ("createuser", FAUX_CREATEUSER),
            ("sudo", FAUX_SUDO_REFUSE),
            ("pg_isready", "#!/bin/bash\nexit 0\n"),
        ):
            faux = Path(tmp.name, nom)
            faux.write_text(texte, encoding="utf-8")
            faux.chmod(0o755)
        journal = Path(tmp.name, "journal")
        env = dict(os.environ)
        env.update(
            PATH=f"{tmp.name}:{env['PATH']}",
            FAUX_JOURNAL=str(journal),
            FAUX_ROLES=roles,
            FAUX_RC_CREATE=str(rc_create),
        )
        res = subprocess.run(
            [
                "bash",
                "-c",
                ". ./script/install/lib_postgres_role.sh; "
                "el_postgres_role_local erplibre",
            ],
            cwd=RACINE,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        appels = journal.read_text().splitlines() if journal.exists() else []
        return res, appels

    def test_a_present_role_is_kept(self):
        res, appels = self.lance(roles="erplibre")
        self.assertEqual(0, res.returncode, res.stdout + res.stderr)
        self.assertIn("déjà présent", res.stdout)
        self.assertFalse([a for a in appels if a.startswith("createuser")])

    def test_a_missing_role_is_created_by_the_current_account(self):
        res, appels = self.lance(roles="")
        self.assertEqual(0, res.returncode, res.stdout + res.stderr)
        self.assertIn("createuser -s erplibre", appels)
        self.assertFalse([a for a in appels if a.startswith("sudo")])

    def test_a_failure_stops_and_gives_the_command(self):
        res, _appels = self.lance(roles="", rc_create=1)
        self.assertEqual(1, res.returncode)
        self.assertIn("Internal Server Error", res.stdout)
        self.assertIn("createuser -s erplibre", res.stdout)


class TestInstalleurs(unittest.TestCase):
    def test_aucun_installeur_linux_ne_passe_par_su(self):
        for nom in INSTALLEURS_LINUX:
            src = (RACINE / "script/install" / nom).read_text()
            with self.subTest(nom):
                self.assertNotIn("su - postgres", src)
                self.assertNotIn("createuser", src)
                self.assertIn('el_postgres_role "${EL_USER}" || exit 1', src)

    def test_the_macos_installer_reaches_the_keg_only_binaries(self):
        """postgresql@15 est « keg-only » : Homebrew ne lie pas psql ni
        createuser dans le PATH. Le passage de l'installeur qui crée le rôle
        est joué pour de vrai, avec un brew simulé dont le keg porte les
        commandes, hors du PATH."""
        src = (RACINE / "script/install/install_OSX_dependency.sh").read_text()
        debut = src.index("# postgresql@15 est une formule")
        fin = src.index("|| exit 1", debut) + len("|| exit 1")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        keg = Path(tmp.name, "keg")
        (keg / "bin").mkdir(parents=True)
        for nom, texte in (
            ("psql", FAUX_PSQL),
            ("createuser", FAUX_CREATEUSER),
            ("pg_isready", "#!/bin/bash\nexit 0\n"),
        ):
            faux = keg / "bin" / nom
            faux.write_text(texte, encoding="utf-8")
            faux.chmod(0o755)
        outils = Path(tmp.name, "outils")
        outils.mkdir()
        # Le PATH ci-dessous perd la doublure du lanceur : ce faux sudo
        # refuse, et rien ici ne doit d'ailleurs passer par sudo.
        sudo = outils / "sudo"
        sudo.write_text(FAUX_SUDO_REFUSE, encoding="utf-8")
        sudo.chmod(0o755)
        brew = outils / "brew"
        brew.write_text(f"#!/bin/bash\necho {keg}\n", encoding="utf-8")
        brew.chmod(0o755)
        env = dict(os.environ)
        env.update(
            PATH=f"{outils}:/usr/bin:/bin",
            FAUX_JOURNAL=str(Path(tmp.name, "journal")),
            FAUX_ROLES="erplibre",
            EL_USER="erplibre",
        )
        res = subprocess.run(
            ["bash", "-c", src[debut:fin]],
            cwd=RACINE,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, res.returncode, res.stdout + res.stderr)
        self.assertIn("déjà présent", res.stdout)

    def test_the_macos_installer_no_longer_goes_through_su(self):
        src = (RACINE / "script/install/install_OSX_dependency.sh").read_text()
        self.assertNotIn("su - postgres", src)
        self.assertIn('el_postgres_role_local "${EL_USER}" || exit 1', src)


if __name__ == "__main__":
    unittest.main()
