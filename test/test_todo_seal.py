#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le sceau PAdES de TODO › Execute › Security.

Trois promesses : le fichier ne peut pas atterrir là où git le commiterait,
la clé privée n'est jamais écrite en clair, et le certificat porte l'usage
de clé que pyHanko exige. Les tests de génération lancent le vrai openssl.
"""

import io
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from script.todo import seal_menu
from script.todo.seal_menu import (
    NOM_CRT,
    NOM_P12,
    VAR_MDP,
    SealMenuMixin,
    a_la_non_repudiation,
    chemin_commitable,
    commandes_openssl,
    generer_sceau,
)

MOT_DE_PASSE = "essai-sceau-inventé"
OPENSSL = shutil.which("openssl")


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


class TestCheminCommitable(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.depot = os.path.join(self.tmp, "depot")
        os.makedirs(self.depot)
        _git("init", "-q", cwd=self.depot)
        with open(os.path.join(self.depot, ".gitignore"), "w") as fichier:
            fichier.write("/ignore/\n/interne/\n")

    def test_un_dossier_ordinaire_du_depot_est_commitable(self):
        chemin = os.path.join(self.depot, "prive", "sceau.p12")
        self.assertTrue(chemin_commitable(chemin))

    def test_un_dossier_ignore_ne_l_est_pas(self):
        # Le dossier n'existe pas encore : la règle suffit.
        chemin = os.path.join(self.depot, "ignore", "a", "sceau.p12")
        self.assertFalse(chemin_commitable(chemin))

    def test_hors_de_tout_depot_rien_ne_le_commite(self):
        chemin = os.path.join(self.tmp, "hors", "sceau.p12")
        self.assertFalse(chemin_commitable(chemin))

    def test_un_sous_depot_ignore_par_le_parent_le_commiterait(self):
        interne = os.path.join(self.depot, "interne")
        os.makedirs(interne)
        _git("init", "-q", cwd=interne)
        self.assertTrue(chemin_commitable(os.path.join(interne, "sceau.p12")))

    def test_un_fichier_deja_suivi_reste_commitable_sous_une_regle(self):
        chemin = os.path.join(self.depot, "suivi.p12")
        open(chemin, "w").close()
        _git("add", "suivi.p12", cwd=self.depot)
        with open(os.path.join(self.depot, ".gitignore"), "a") as fichier:
            fichier.write("*.p12\n")
        self.assertTrue(chemin_commitable(chemin))

    def test_un_depot_que_git_refuse_d_interroger_compte_comme_commitable(
        self,
    ):
        # Propriétaire douteux : TODO lancé par un autre compte que celui du
        # checkout, root d'un conteneur sur un checkout monté par exemple.
        chemin = os.path.join(self.depot, "ignore", "sceau.p12")
        with patch.dict(os.environ, {"GIT_TEST_ASSUME_DIFFERENT_OWNER": "1"}):
            self.assertTrue(chemin_commitable(chemin))

    def test_un_git_qui_pointe_dans_le_vide_compte_comme_commitable(self):
        casse = os.path.join(self.tmp, "casse")
        os.makedirs(casse)
        with open(os.path.join(casse, ".git"), "w") as fichier:
            fichier.write("gitdir: /inexistant/inventé\n")
        self.assertTrue(chemin_commitable(os.path.join(casse, "sceau.p12")))

    def test_un_lien_vers_l_exterieur_ne_trompe_pas_la_verification(self):
        """os.replace remplace le lien par un vrai fichier : c'est
        l'emplacement du nom qui compte, pas la cible du lien."""
        exterieur = os.path.join(self.tmp, "coffre")
        os.makedirs(exterieur)
        cible = os.path.join(exterieur, "sceau.p12")
        open(cible, "w").close()
        dossier = os.path.join(self.depot, "d")
        os.makedirs(dossier)
        lien = os.path.join(dossier, "sceau.p12")
        os.symlink(cible, lien)
        self.assertTrue(chemin_commitable(lien))

    def test_la_cle_du_sous_dossier_de_travail_est_verifiee(self):
        """Des règles qui ne nomment que les fichiers rendus laissent la
        clé chiffrée du sous-dossier de travail à portée de git."""
        with open(os.path.join(self.depot, ".gitignore"), "a") as fichier:
            fichier.write("/sceau.crt\n/sceau.p12\n/sceau.key\n")
        chemins = seal_menu.chemins_a_proteger(self.depot)
        self.assertFalse(chemin_commitable(chemins[0]))
        self.assertFalse(chemin_commitable(chemins[1]))
        self.assertTrue(chemin_commitable(chemins[2]))

    def test_le_dossier_par_defaut_du_checkout_est_ignore(self):
        racine = seal_menu.RACINE
        defaut = os.path.join(racine, seal_menu.DOSSIER_DEFAUT, NOM_P12)
        self.assertFalse(chemin_commitable(defaut))
        # private/ seul est versionné : il ne protège pas une clé.
        self.assertTrue(
            chemin_commitable(os.path.join(racine, "private", NOM_P12))
        )


class TestCommandes(unittest.TestCase):
    def test_le_mot_de_passe_ne_passe_jamais_en_argument(self):
        for commande in commandes_openssl("/d", "Nom", 30):
            self.assertNotIn(MOT_DE_PASSE, " ".join(commande))
            self.assertIn(f"env:{VAR_MDP}", commande)

    def test_la_cle_est_chiffree_et_porte_la_non_repudiation(self):
        req = commandes_openssl("/d", "Nom", 30)[0]
        self.assertNotIn("-nodes", req)
        self.assertNotIn("-noenc", req)
        self.assertIn(seal_menu.USAGE_CLE, req)
        self.assertIn("nonRepudiation", seal_menu.USAGE_CLE)


@unittest.skipUnless(OPENSSL, "openssl absent")
class TestGeneration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.dossier = os.path.join(self.tmp, "sceau")

    def _ouvre_p12(self, p12, mot_de_passe):
        return subprocess.run(
            [OPENSSL, "pkcs12", "-in", p12, "-nocerts", "-noenc",
             "-passin", f"env:{VAR_MDP}"],
            env=dict(os.environ, **{VAR_MDP: mot_de_passe}),
            capture_output=True,
            text=True,
            # Le nom convivial du .p12 sort dans l'encodage d'openssl.
            errors="replace",
        )  # fmt: skip

    def test_le_sceau_s_ouvre_par_son_mot_de_passe(self):
        crt, p12 = generer_sceau(
            self.dossier, "Sceau inventé", 30, MOT_DE_PASSE
        )
        self.assertTrue(a_la_non_repudiation(crt))
        ouvert = self._ouvre_p12(p12, MOT_DE_PASSE)
        self.assertEqual(ouvert.returncode, 0, ouvert.stderr)
        self.assertIn("PRIVATE KEY", ouvert.stdout)
        self.assertNotEqual(self._ouvre_p12(p12, "autre").returncode, 0)

    def test_un_nom_accentue_arrive_tel_quel_dans_le_sujet(self):
        crt, _p12 = generer_sceau(
            self.dossier, "Sceau inventé", 30, MOT_DE_PASSE
        )
        sujet = subprocess.run(
            [OPENSSL, "x509", "-in", crt, "-noout", "-subject",
             "-nameopt", "utf8"],
            capture_output=True,
            text=True,
        )  # fmt: skip
        self.assertIn("CN=Sceau inventé", sujet.stdout)

    def test_aucune_cle_en_clair_ne_reste(self):
        generer_sceau(self.dossier, "Sceau inventé", 30, MOT_DE_PASSE)
        self.assertEqual(
            sorted(os.listdir(self.dossier)), sorted([NOM_CRT, NOM_P12])
        )

    def test_rien_n_est_lisible_par_un_autre_compte(self):
        crt, p12 = generer_sceau(
            self.dossier, "Sceau inventé", 30, MOT_DE_PASSE
        )
        self.assertEqual(stat.S_IMODE(os.stat(self.dossier).st_mode), 0o700)
        for chemin in (crt, p12):
            self.assertEqual(stat.S_IMODE(os.stat(chemin).st_mode), 0o600)

    def test_un_sceau_remplace_perd_les_droits_de_l_ancien(self):
        os.makedirs(self.dossier)
        for nom in (NOM_CRT, NOM_P12):
            chemin = os.path.join(self.dossier, nom)
            with open(chemin, "w") as fichier:
                fichier.write("ancien")
            os.chmod(chemin, 0o644)
        crt, p12 = generer_sceau(
            self.dossier, "Sceau inventé", 30, MOT_DE_PASSE
        )
        for chemin in (crt, p12):
            self.assertEqual(stat.S_IMODE(os.stat(chemin).st_mode), 0o600)
        self.assertTrue(a_la_non_repudiation(crt))

    def test_un_echec_d_openssl_efface_aussi_la_cle(self):
        """L'export échoue après la création de la clé : rien ne reste du
        travail, et l'ancien sceau est intact."""
        os.makedirs(self.dossier)
        p12 = os.path.join(self.dossier, NOM_P12)
        with open(p12, "w") as fichier:
            fichier.write("ancien")
        reel = subprocess.run

        def echoue_a_l_export(commande, **kwargs):
            if "pkcs12" in commande:
                raise subprocess.CalledProcessError(1, commande)
            return reel(commande, **kwargs)

        with patch.object(seal_menu.subprocess, "run", echoue_a_l_export):
            with self.assertRaises(subprocess.CalledProcessError):
                generer_sceau(self.dossier, "Sceau inventé", 30, MOT_DE_PASSE)
        self.assertEqual(os.listdir(self.dossier), [NOM_P12])
        with open(p12) as fichier:
            self.assertEqual(fichier.read(), "ancien")


class _Menu(SealMenuMixin):
    @staticmethod
    def _is_yes(reponse):
        return reponse.strip().lower() in ("y", "o")


@unittest.skipUnless(OPENSSL, "openssl absent")
class TestLeMenu(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)

    def _lance(self, reponses, mots_de_passe=(MOT_DE_PASSE, MOT_DE_PASSE)):
        sortie = io.StringIO()
        with patch("builtins.input", side_effect=list(reponses)), patch.object(
            seal_menu.getpass, "getpass", side_effect=list(mots_de_passe)
        ), redirect_stdout(sortie):
            _Menu().execute_generate_seal()
        return sortie.getvalue()

    def test_un_dossier_hors_depot_recoit_le_sceau(self):
        dossier = os.path.join(self.tmp, "sceau")
        self._lance([dossier, "", ""])
        self.assertTrue(os.path.isfile(os.path.join(dossier, NOM_P12)))

    def test_un_dossier_commitable_est_refuse_sans_rien_ecrire(self):
        dossier = os.path.join(seal_menu.RACINE, "private", "essai_sceau_x")
        self.addCleanup(shutil.rmtree, dossier, True)
        sortie = self._lance([dossier], mots_de_passe=())
        self.assertIn(os.path.join(dossier, NOM_P12), sortie)
        self.assertFalse(os.path.exists(dossier))

    def test_un_sceau_existant_reste_sans_un_oui(self):
        dossier = os.path.join(self.tmp, "sceau")
        os.makedirs(dossier)
        p12 = os.path.join(dossier, NOM_P12)
        with open(p12, "w") as fichier:
            fichier.write("ancien")
        self._lance([dossier, ""], mots_de_passe=())
        with open(p12) as fichier:
            self.assertEqual(fichier.read(), "ancien")

    def test_un_nom_qui_decouperait_le_sujet_est_refuse(self):
        dossier = os.path.join(self.tmp, "sceau")
        self._lance([dossier, "Nom/O=Autre"], mots_de_passe=())
        self.assertFalse(os.path.exists(dossier))

    def test_une_duree_illisible_est_refusee_sans_planter(self):
        dossier = os.path.join(self.tmp, "sceau")
        sortie = self._lance([dossier, "", "²"], mots_de_passe=())
        self.assertIn("'²'", sortie)
        self.assertFalse(os.path.exists(dossier))

    def test_un_nom_trop_long_est_refuse_avant_le_mot_de_passe(self):
        dossier = os.path.join(self.tmp, "sceau")
        self._lance([dossier, "x" * 65], mots_de_passe=())
        self.assertFalse(os.path.exists(dossier))

    def test_deux_mots_de_passe_differents_n_ecrivent_rien(self):
        dossier = os.path.join(self.tmp, "sceau")
        self._lance([dossier, "", ""], mots_de_passe=(MOT_DE_PASSE, "autre"))
        self.assertFalse(os.path.exists(dossier))


if __name__ == "__main__":
    unittest.main()
