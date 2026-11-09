#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le conteneur que visent les scripts de script/docker/ qui entrent dans le
conteneur ERPLibre, par conteneur_erplibre de lib_conteneur.sh. Un faux
« docker » note ses arguments : aucun conteneur n'est touché.

Ce que ces tests gardent, pour chaque script :

- le nom de compose v2 (« - ») est préféré, celui de la v1 (« _ ») sert
  quand le premier n'est pas en marche ;
- seul un conteneur EN MARCHE est retenu, interrogé avec --type container ;
  un conteneur arrêté se signale comme tel, avant docker exec ;
- sans aucun des deux, le script nomme les deux et s'arrête avant docker
  exec ;
- un moteur qui ne répond pas arrête avant docker exec, et son erreur passe
  telle quelle ;
- le projet est celui que nomme « docker compose config », dérivé du
  répertoire quand compose ne répond pas ;
- une commande qui échoue — un test rouge pour docker_make_test.sh — n'est
  pas relancée vers l'autre nom, et son code de sortie est celui du script.
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
DOSSIER = RACINE / "script" / "docker"

# Le nom du script, et ses arguments.
SCRIPTS = {
    "docker_exec.sh": [],
    "docker_list_database.sh": [],
    "docker_make_test.sh": [],
    "docker_repo_show_status.sh": [],
    "docker_gen_config.sh": [],
    "docker_copy_file.sh": ["fichier.txt"],
}

# « version » échoue avec le message FAUX_MOTEUR quand il est posé ;
# « compose » écrit FAUX_CONFIG ; « inspect » d'un conteneur, le dernier
# argument, écrit « true » pour les noms de FAUX_EXISTANTS, « false » pour
# ceux de FAUX_ARRETES, et échoue sinon, comme pour tout autre type ; « exec »
# et « cp » sortent avec FAUX_RC.
FAUX_DOCKER = """#!/usr/bin/env bash
echo "$*" >> "${FAUX_DOCKER_JOURNAL}"
case "$1" in
  version)
    if [[ -n "${FAUX_MOTEUR:-}" ]]; then echo "${FAUX_MOTEUR}" >&2; exit 1; fi
    echo "29.0" ;;
  compose) echo "${FAUX_CONFIG:-}" ;;
  inspect)
    [[ "$2 $3" == "--type container" ]] || exit 1
    nom="${@: -1}"
    for n in ${FAUX_EXISTANTS}; do [[ "$nom" == "$n" ]] && echo true && exit 0; done
    for n in ${FAUX_ARRETES:-}; do [[ "$nom" == "$n" ]] && echo false && exit 0; done
    echo "Error response from daemon: No such container: $nom" >&2
    exit 1 ;;
  exec | cp) exit "${FAUX_RC:-0}" ;;
esac
"""


def lancer(
    script,
    existants="projetessai-ERPLibre-1",
    rc=0,
    repertoire="Projet.Essai",
    **variables,
):
    """Lance ``script`` depuis un répertoire « Projet.Essai », dont compose
    tire le projet « projetessai ». ``variables`` pose les autres variables du
    faux docker. Rend la sortie et les commandes exec et cp reçues."""
    with tempfile.TemporaryDirectory() as dossier:
        faux = Path(dossier) / "bin"
        faux.mkdir()
        (faux / "docker").write_text(FAUX_DOCKER, encoding="utf-8")
        (faux / "docker").chmod(0o755)
        projet = Path(dossier) / repertoire
        projet.mkdir()
        (projet / ".odoo-version").write_text("18.0\n", encoding="utf-8")
        (projet / "fichier.txt").write_text("x", encoding="utf-8")
        journal = Path(dossier) / "journal"
        journal.touch()
        env = dict(
            os.environ,
            PATH=f"{faux}:{os.environ['PATH']}",
            FAUX_DOCKER_JOURNAL=str(journal),
            FAUX_EXISTANTS=existants,
            FAUX_RC=str(rc),
        )
        env.update({k: str(v) for k, v in variables.items()})
        sortie = subprocess.run(
            [str(DOSSIER / script), *SCRIPTS[script]],
            cwd=projet,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        appels = journal.read_text(encoding="utf-8").splitlines()
        return sortie, [a for a in appels if a.split()[0] in ("exec", "cp")]


def conteneurs(appels):
    """Les conteneurs visés, dans l'ordre des appels."""
    vus = []
    for appel in appels:
        for mot in appel.split():
            nom = mot.split(":")[0]
            if nom.startswith("projetessai") and nom not in vus:
                vus.append(nom)
    return vus


class TestConteneurErplibre(unittest.TestCase):
    def test_le_nom_v2_est_prefere(self):
        for script in SCRIPTS:
            with self.subTest(script=script):
                sortie, appels = lancer(
                    script,
                    existants="projetessai-ERPLibre-1 projetessai_ERPLibre_1",
                )
                self.assertEqual(sortie.returncode, 0, sortie.stderr)
                self.assertTrue(appels)
                self.assertEqual(
                    ["projetessai-ERPLibre-1"], conteneurs(appels)
                )

    def test_le_nom_v1_en_repli(self):
        for script in SCRIPTS:
            with self.subTest(script=script):
                sortie, appels = lancer(
                    script, existants="projetessai_ERPLibre_1"
                )
                self.assertEqual(sortie.returncode, 0, sortie.stderr)
                self.assertEqual(
                    ["projetessai_ERPLibre_1"], conteneurs(appels)
                )

    def test_aucun_conteneur_arrete_avant_exec(self):
        for script in SCRIPTS:
            with self.subTest(script=script):
                sortie, appels = lancer(script, existants="")
                self.assertEqual(sortie.returncode, 1)
                self.assertEqual([], appels)
                self.assertIn("projetessai-ERPLibre-1", sortie.stderr)
                self.assertIn("projetessai_ERPLibre_1", sortie.stderr)

    def test_un_conteneur_arrete_est_signale_avant_exec(self):
        for script in SCRIPTS:
            with self.subTest(script=script):
                sortie, appels = lancer(
                    script, existants="", FAUX_ARRETES="projetessai-ERPLibre-1"
                )
                self.assertEqual(sortie.returncode, 1)
                self.assertEqual([], appels)
                self.assertIn(
                    "projetessai-ERPLibre-1 is stopped", sortie.stderr
                )
                self.assertIn("docker compose up -d", sortie.stderr)

    def test_le_conteneur_en_marche_passe_avant_l_arrete(self):
        sortie, appels = lancer(
            "docker_exec.sh",
            existants="projetessai_ERPLibre_1",
            FAUX_ARRETES="projetessai-ERPLibre-1",
        )
        self.assertEqual(sortie.returncode, 0, sortie.stderr)
        self.assertEqual(["projetessai_ERPLibre_1"], conteneurs(appels))

    def test_un_moteur_muet_montre_son_erreur(self):
        erreur = "failed to connect to the docker API at unix:///nulle/part"
        for script in SCRIPTS:
            with self.subTest(script=script):
                sortie, appels = lancer(script, FAUX_MOTEUR=erreur)
                self.assertEqual(sortie.returncode, 1)
                self.assertEqual([], appels)
                self.assertIn(erreur, sortie.stderr)
                self.assertNotIn("docker compose directory", sortie.stderr)

    def test_le_projet_vient_de_compose(self):
        """COMPOSE_PROJECT_NAME, .env ou name: : compose en décide."""
        sortie, appels = lancer(
            "docker_exec.sh",
            existants="autre-ERPLibre-1",
            FAUX_CONFIG='{"name": "autre", "services": {}}',
        )
        self.assertEqual(sortie.returncode, 0, sortie.stderr)
        self.assertIn("autre-ERPLibre-1", appels[0].split())

    def test_sans_compose_le_nom_se_derive_comme_compose(self):
        """Minuscules, caractères [a-z0-9_-] seulement, rien de « _ » ni de
        « - » en tête."""
        sortie, appels = lancer(
            "docker_exec.sh",
            existants="mon_projet-2-ERPLibre-1",
            repertoire="_-Mon_Projet+-2 é",
        )
        self.assertEqual(sortie.returncode, 0, sortie.stderr)
        self.assertIn("mon_projet-2-ERPLibre-1", appels[0].split())

    def test_une_commande_en_echec_n_est_pas_relancee(self):
        for script in SCRIPTS:
            if script == "docker_copy_file.sh":
                continue
            with self.subTest(script=script):
                sortie, appels = lancer(script, rc=2)
                self.assertEqual(sortie.returncode, 2)
                self.assertEqual(1, len(appels), appels)

    def test_gen_config_prend_la_version_du_checkout(self):
        _, appels = lancer("docker_gen_config.sh")
        self.assertIn("/ERPLibre/odoo18.0/addons", appels[0])


if __name__ == "__main__":
    unittest.main()
