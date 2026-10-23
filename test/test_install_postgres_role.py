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

Un rôle présent sans rolsuper ne suffit pas non plus : Odoo s'y connecte,
puis échoue à créer sa base. Il doit être promu, ou l'installeur s'arrêter.

« sudo » est remplacé par un script qui journalise ses arguments et son
répertoire courant, connaît les superutilisateurs de FAUX_ROLES et les rôles
simples de FAUX_ROLES_SIMPLES, et rend FAUX_RC_CREATE pour createuser. Il
n'accepte que la requête à égalité exacte sur le nom : une comparaison plus
lâche prendrait « erplibre2 » pour « erplibre ». Pour l'ALTER ROLE, il imite
psql : un échec (FAUX_RC_ALTER non nul) ne rend un code non nul que sous
ON_ERROR_STOP=1.
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
    sql="$(cat)"
    echo "$(pwd) | sql: $sql" >> "$FAUX_JOURNAL"
    arret=0
    for a in "$@"; do
      case "$a" in
        r=*) role="${a#r=}" ;;
        ON_ERROR_STOP=1) arret=1 ;;
      esac
    done
    case "$sql" in
      "SELECT rolsuper FROM pg_roles WHERE rolname = :'r'")
        for r in $FAUX_ROLES; do
          [[ "$r" == "$role" ]] && echo t
        done
        for r in $FAUX_ROLES_SIMPLES; do
          [[ "$r" == "$role" ]] && echo f
        done
        exit 0 ;;
      'ALTER ROLE :"r" SUPERUSER')
        if [[ "${FAUX_RC_ALTER:-0}" != 0 ]]; then
          echo "ERROR: permission denied" >&2
          (( arret )) && exit 3
        fi
        exit 0 ;;
    esac
    exit 97 ;;
  createuser) exit "${FAUX_RC_CREATE:-0}" ;;
esac
exit 98
"""


class TestRolePostgres(unittest.TestCase):
    def lance(self, roles="", rc_create=0, simples="", rc_alter=0):
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
            FAUX_ROLES_SIMPLES=simples,
            FAUX_RC_ALTER=str(rc_alter),
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
        self.assertFalse([a for a in appels if "ALTER" in a])

    def test_un_role_sans_rolsuper_est_promu(self):
        """createuser sans -s laisse un rôle qui ne peut créer de base."""
        res, appels = self.lance(roles="postgres", simples="erplibre")
        self.assertEqual(0, res.returncode, res.stdout + res.stderr)
        self.assertNotIn("déjà présent", res.stdout)
        self.assertIn("promu superutilisateur", res.stdout)
        self.assertIn('/ | sql: ALTER ROLE :"r" SUPERUSER', appels)
        self.assertTrue(
            [
                a
                for a in appels
                if a.startswith("/ | runuser -u postgres -- psql")
                and "ON_ERROR_STOP=1" in a
                and "r=erplibre" in a
            ],
            appels,
        )
        self.assertFalse([a for a in appels if "createuser" in a])

    def test_une_promotion_refusee_arrete_et_donne_la_commande(self):
        res, appels = self.lance(simples="erplibre", rc_alter=1)
        self.assertEqual(1, res.returncode, res.stdout + res.stderr)
        self.assertIn("superutilisateur", res.stdout)
        self.assertIn(
            "sudo runuser -u postgres -- psql -c "
            "'ALTER ROLE \"erplibre\" SUPERUSER'",
            res.stdout,
        )
        self.assertFalse([a for a in appels if "createuser" in a])

    def test_un_nom_voisin_n_est_pas_pris_pour_le_role(self):
        res, appels = self.lance(roles="erplibre2", simples="erplibre_x")
        self.assertEqual(0, res.returncode, res.stdout + res.stderr)
        self.assertIn("créé", res.stdout)
        self.assertFalse([a for a in appels if "ALTER" in a])

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


class TestInstalleurs(unittest.TestCase):
    def test_aucun_installeur_linux_ne_passe_par_su(self):
        for nom in INSTALLEURS_LINUX:
            src = (RACINE / "script/install" / nom).read_text()
            with self.subTest(nom):
                self.assertNotIn("su - postgres", src)
                self.assertNotIn("createuser", src)
                self.assertIn('el_postgres_role "${EL_USER}" || exit 1', src)


if __name__ == "__main__":
    unittest.main()
