#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le sceau PAdES de TODO › Execute › Security.

Trois promesses : le fichier ne peut pas atterrir là où git le commiterait,
la clé privée n'est jamais écrite en clair, et le certificat porte l'usage
de clé que pyHanko exige. Les tests de génération lancent le vrai openssl.
"""

import ast
import datetime
import hashlib
import io
import os
import shlex
import shutil
import stat
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
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
from script.todo.todo_i18n import TRANSLATIONS

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


class TestFormatCommande(unittest.TestCase):
    def test_la_commande_affichee_redonne_la_commande_executee(self):
        """Copiée dans un shell, la forme affichée lance exactement les
        mêmes arguments, accents et espaces compris."""
        for commande in commandes_openssl(
            "/d/.sceau-x", "Sceau inventé", 30, "Org inventée"
        ):
            texte = seal_menu.format_commande(commande)
            self.assertEqual(shlex.split(texte.replace("\\\n", " ")), commande)
            self.assertNotIn(MOT_DE_PASSE, texte)


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


class _Isole(unittest.TestCase):
    """Un dossier temporaire, et le registre comme le dépôt détournés vers
    lui : aucun test n'écrit dans private/sceau/ du checkout, ni ne lit les
    fichiers de clé qui s'y trouveraient."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.registre = os.path.join(self.tmp, "registre", "registre.json")
        for nom, valeur in (
            ("REGISTRE", self.registre),
            ("RACINE", os.path.join(self.tmp, "racine")),
        ):
            detour = patch.object(seal_menu, nom, valeur)
            detour.start()
            self.addCleanup(detour.stop)
        os.makedirs(seal_menu.RACINE)


@unittest.skipUnless(OPENSSL, "openssl absent")
class TestLeMenu(_Isole):
    def _lance(self, reponses, mots_de_passe=(MOT_DE_PASSE, MOT_DE_PASSE)):
        sortie = io.StringIO()
        with patch("builtins.input", side_effect=list(reponses)), patch.object(
            seal_menu.getpass, "getpass", side_effect=list(mots_de_passe)
        ), redirect_stdout(sortie):
            _Menu().execute_generate_seal()
        return sortie.getvalue()

    def test_un_dossier_hors_depot_recoit_le_sceau(self):
        dossier = os.path.join(self.tmp, "sceau")
        sortie = self._lance([dossier, "", "", ""])
        crt = os.path.join(dossier, NOM_CRT)
        self.assertTrue(os.path.isfile(os.path.join(dossier, NOM_P12)))
        # L'empreinte à transmettre avec sceau.crt est affichée.
        self.assertIn(seal_menu.infos_certificat(crt)["empreinte"], sortie)
        self.assertEqual(seal_menu.lire_registre(), [dossier])

    def test_les_commandes_sont_affichees_et_expliquees_sans_mot_de_passe(
        self,
    ):
        dossier = os.path.join(self.tmp, "sceau")
        sortie = self._lance([dossier, "", "", ""])
        self.assertIn("$ openssl req", sortie)
        self.assertIn("$ openssl pkcs12", sortie)
        self.assertIn(seal_menu.USAGE_CLE, sortie)
        self.assertIn(f"env:{VAR_MDP}", sortie)
        self.assertNotIn(MOT_DE_PASSE, sortie)
        # La légende suit les commandes, option par option.
        legende = sortie.split("$ openssl pkcs12")[1]
        for option in ("-subj", "-addext", "-passout", "pkcs12 -export"):
            self.assertIn(option, legende)

    def test_l_organisation_entre_dans_le_sujet(self):
        dossier = os.path.join(self.tmp, "sceau")
        self._lance([dossier, "Organisation inventée", "", ""])
        infos = seal_menu.infos_certificat(os.path.join(dossier, NOM_CRT))
        self.assertIn("O=Organisation inventée", infos["sujet"])

    def test_un_dossier_commitable_est_refuse_sans_rien_ecrire(self):
        depot = os.path.join(self.tmp, "depot")
        os.makedirs(depot)
        _git("init", "-q", cwd=depot)
        dossier = os.path.join(depot, "prive")
        sortie = self._lance([dossier], mots_de_passe=())
        self.assertIn(os.path.join(dossier, NOM_P12), sortie)
        self.assertFalse(os.path.exists(dossier))
        self.assertEqual(seal_menu.lire_registre(), [])

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
        self._lance([dossier, "", "Nom/O=Autre"], mots_de_passe=())
        self.assertFalse(os.path.exists(dossier))

    def test_une_organisation_qui_decouperait_le_sujet_est_refusee(self):
        dossier = os.path.join(self.tmp, "sceau")
        self._lance([dossier, "Org/CN=Autre"], mots_de_passe=())
        self.assertFalse(os.path.exists(dossier))

    def test_une_duree_illisible_est_refusee_sans_planter(self):
        dossier = os.path.join(self.tmp, "sceau")
        sortie = self._lance([dossier, "", "", "²"], mots_de_passe=())
        self.assertIn("'²'", sortie)
        self.assertFalse(os.path.exists(dossier))

    def test_un_nom_trop_long_est_refuse_avant_le_mot_de_passe(self):
        dossier = os.path.join(self.tmp, "sceau")
        self._lance([dossier, "", "x" * 65], mots_de_passe=())
        self.assertFalse(os.path.exists(dossier))

    def test_deux_mots_de_passe_differents_n_ecrivent_rien(self):
        dossier = os.path.join(self.tmp, "sceau")
        self._lance(
            [dossier, "", "", ""], mots_de_passe=(MOT_DE_PASSE, "autre")
        )
        self.assertFalse(os.path.exists(dossier))


@unittest.skipUnless(OPENSSL, "openssl absent")
class TestInfosCertificat(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_ce_que_l_etat_lit_d_un_certificat(self):
        crt, _p12 = generer_sceau(
            self.tmp, "Sceau inventé", 30, MOT_DE_PASSE, "Org inventée"
        )
        infos = seal_menu.infos_certificat(crt)
        self.assertIn("CN=Sceau inventé", infos["sujet"])
        self.assertIn("O=Org inventée", infos["sujet"])
        self.assertTrue(infos["non_repudiation"])
        # SHA-256 : 32 octets en hexadécimal, séparés par des deux-points.
        self.assertRegex(
            infos["empreinte"], r"^([0-9A-F]{2}:){31}[0-9A-F]{2}$"
        )
        self.assertIn(seal_menu.jours_restants(infos["fin"]), (28, 29, 30))
        self.assertLess(infos["debut"], infos["fin"])

    def test_un_fichier_qui_n_est_pas_un_certificat_rend_none(self):
        faux = os.path.join(self.tmp, NOM_CRT)
        with open(faux, "w") as fichier:
            fichier.write("pas un certificat")
        self.assertIsNone(seal_menu.infos_certificat(faux))

    def test_les_jours_restants_deviennent_negatifs_une_fois_echu(self):
        utc = datetime.timezone.utc
        maintenant = datetime.datetime(2026, 6, 1, tzinfo=utc)
        fin = datetime.datetime(2026, 5, 20, tzinfo=utc)
        self.assertEqual(seal_menu.jours_restants(fin, maintenant), -12)

    def test_le_dernier_jour_compte_zero_et_le_lendemain_moins_un(self):
        utc = datetime.timezone.utc
        fin = datetime.datetime(2026, 5, 20, 9, 0, tzinfo=utc)
        matin = datetime.datetime(2026, 5, 20, 1, 0, tzinfo=utc)
        soir = datetime.datetime(2026, 5, 20, 23, 0, tzinfo=utc)
        lendemain = datetime.datetime(2026, 5, 21, 1, 0, tzinfo=utc)
        self.assertEqual(seal_menu.jours_restants(fin, matin), 0)
        self.assertEqual(seal_menu.jours_restants(fin, soir), 0)
        self.assertEqual(seal_menu.jours_restants(fin, lendemain), -1)


class TestRegistre(_Isole):
    def test_un_dossier_n_est_inscrit_qu_une_fois(self):
        seal_menu.inscrire_sceau(os.path.join(self.tmp, "a"))
        seal_menu.inscrire_sceau(os.path.join(self.tmp, "a"))
        seal_menu.inscrire_sceau(os.path.join(self.tmp, "b"))
        self.assertEqual(
            seal_menu.lire_registre(),
            [os.path.join(self.tmp, "a"), os.path.join(self.tmp, "b")],
        )
        mode = stat.S_IMODE(os.stat(self.registre).st_mode)
        self.assertEqual(mode, 0o600)

    def test_un_registre_illisible_est_vide_et_n_est_pas_ecrase(self):
        os.makedirs(os.path.dirname(self.registre))
        with open(self.registre, "w") as fichier:
            fichier.write("{pas du json")
        self.assertEqual(seal_menu.lire_registre(), [])
        with self.assertRaises(ValueError):
            seal_menu.inscrire_sceau(os.path.join(self.tmp, "a"))
        with open(self.registre) as fichier:
            self.assertEqual(fichier.read(), "{pas du json")

    def test_le_retrait_garde_les_autres_dans_leur_ordre(self):
        for nom in ("a", "b", "c"):
            seal_menu.inscrire_sceau(os.path.join(self.tmp, nom))
        seal_menu.retirer_du_registre([os.path.join(self.tmp, "b")])
        self.assertEqual(
            seal_menu.lire_registre(),
            [os.path.join(self.tmp, "a"), os.path.join(self.tmp, "c")],
        )
        self.assertEqual(
            sorted(os.listdir(os.path.dirname(self.registre))),
            ["registre.json"],
        )

    def test_le_dossier_par_defaut_compte_s_il_porte_un_certificat(self):
        defaut = os.path.join(self.tmp, "defaut")
        self.assertEqual(seal_menu.sceaux_connus(dossier_defaut=defaut), [])
        os.makedirs(defaut)
        open(os.path.join(defaut, NOM_CRT), "w").close()
        self.assertEqual(
            seal_menu.sceaux_connus(dossier_defaut=defaut), [defaut]
        )


class TestClesAPorteeDeGit(unittest.TestCase):
    def setUp(self):
        self.depot = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.depot)
        _git("init", "-q", cwd=self.depot)

    def _ecrit(self, nom, contenu=""):
        chemin = os.path.join(self.depot, nom)
        os.makedirs(os.path.dirname(chemin), exist_ok=True)
        with open(chemin, "w") as fichier:
            fichier.write(contenu)

    def test_commitee_indexee_et_non_suivie_se_distinguent(self):
        with open(os.path.join(self.depot, ".gitignore"), "w") as fichier:
            fichier.write("/ignore/\n")
        for nom in ("commit.p12", "index.pfx", "libre.key", "ignore/c.p12"):
            self._ecrit(nom)
        self._ecrit("a.crt")
        _git("add", "commit.p12", cwd=self.depot)
        _git(
            "-c", "user.name=x", "-c", "user.email=x@x.invalid",
            "commit", "-q", "-m", "x", cwd=self.depot,
        )  # fmt: skip
        _git("add", "index.pfx", cwd=self.depot)
        self.assertEqual(
            sorted(seal_menu.cles_du_depot(self.depot)),
            [
                ("commit.p12", "commité"),
                ("index.pfx", "indexé"),
                ("libre.key", "non suivi"),
            ],
        )

    def test_les_copies_et_les_cles_pem_sont_vues(self):
        self._ecrit("sceau.p12.bak")
        self._ecrit("cle.key~")
        self._ecrit("cle.pem", "-----BEGIN ENCRYPTED PRIVATE KEY-----\n")
        self._ecrit("cert.pem", "-----BEGIN CERTIFICATE-----\n")
        self.assertEqual(
            sorted(n for n, _ in seal_menu.cles_du_depot(self.depot)),
            ["cle.key~", "cle.pem", "sceau.p12.bak"],
        )

    def test_les_depots_d_addons_sont_balayes(self):
        """La racine ignore le dossier d'addons ; son propre dépôt, listé
        par Google Repo, le commiterait."""
        with open(os.path.join(self.depot, ".gitignore"), "w") as fichier:
            fichier.write("/addons/\n")
        addons = os.path.join(self.depot, "addons", "x")
        os.makedirs(addons)
        _git("init", "-q", cwd=addons)
        self._ecrit("addons/x/data/sceau.p12")
        self._ecrit(".repo/project.list", "addons/x\naddons/absent\n")
        cles, muets = seal_menu.cles_a_portee_de_git(self.depot)
        self.assertIn(("addons/x/data/sceau.p12", "non suivi"), cles)
        self.assertEqual(muets, [])

    def test_une_cle_d_essai_commitee_par_l_amont_n_est_pas_listee(self):
        """Odoo et l'OCA commitent des clés d'essai ; seul un de nos sceaux
        commité dans un dépôt d'addons est signalé."""
        with open(os.path.join(self.depot, ".gitignore"), "w") as fichier:
            fichier.write("/addons/\n")
        addons = os.path.join(self.depot, "addons", "x")
        os.makedirs(addons)
        _git("init", "-q", cwd=addons)
        self._ecrit("addons/x/tests/essai.p12", "amont")
        self._ecrit("addons/x/data/copie.p12", "notre sceau")
        self._ecrit("addons/x/data/sceau.key", "clé")
        _git("add", ".", cwd=addons)
        _git(
            "-c", "user.name=x", "-c", "user.email=x@x.invalid",
            "commit", "-q", "-m", "x", cwd=addons,
        )  # fmt: skip
        self._ecrit(".repo/project.list", "addons/x\n")
        notre = hashlib.sha256(b"notre sceau").hexdigest()
        cles, _muets = seal_menu.cles_a_portee_de_git(
            self.depot, empreintes={notre}
        )
        self.assertEqual(
            sorted(cles),
            [
                ("addons/x/data/copie.p12", "commité"),
                ("addons/x/data/sceau.key", "commité"),
            ],
        )

    def test_un_depot_que_git_ne_lit_pas_est_nomme(self):
        casse = os.path.join(self.depot, "casse")
        os.makedirs(casse)
        with open(os.path.join(casse, ".git"), "w") as fichier:
            fichier.write("gitdir: /inexistant/inventé\n")
        self._ecrit(".repo/project.list", "casse\n")
        _cles, muets = seal_menu.cles_a_portee_de_git(self.depot)
        self.assertEqual(muets, [casse])

    def test_hors_de_tout_depot_git_ne_repond_pas(self):
        dossier = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, dossier)
        self.assertIsNone(seal_menu.cles_du_depot(dossier))


@unittest.skipUnless(OPENSSL, "openssl absent")
class TestEtat(_Isole):
    def _etat(self, reponses=()):
        sortie = io.StringIO()
        with patch(
            "builtins.input", side_effect=list(reponses)
        ), redirect_stdout(sortie):
            _Menu().execute_seal_status()
        return sortie.getvalue()

    def test_l_etat_rend_compte_de_chaque_sceau_inscrit(self):
        dossier = os.path.join(self.tmp, "sceau")
        crt, p12 = generer_sceau(dossier, "Sceau inventé", 10, MOT_DE_PASSE)
        seal_menu.inscrire_sceau(dossier)
        os.chmod(p12, 0o644)
        sortie = self._etat()
        self.assertIn(dossier, sortie)
        self.assertIn(seal_menu.infos_certificat(crt)["empreinte"], sortie)
        # 10 jours : sous le seuil d'alerte, et le .p12 trop ouvert.
        self.assertIn("⚠️", sortie)
        self.assertIn("0o644", sortie)

    def test_un_sceau_disparu_se_retire_du_registre_sur_un_oui(self):
        parti = os.path.join(self.tmp, "parti")
        reste = os.path.join(self.tmp, "reste")
        seal_menu.inscrire_sceau(parti)
        seal_menu.inscrire_sceau(reste)
        sortie = self._etat([""])
        self.assertIn(parti, sortie)
        # Ni droits ni portée de git pour un dossier sans sceau.
        self.assertNotIn("✅", sortie.split(parti)[1].split("📁")[0])
        self.assertEqual(seal_menu.lire_registre(), [parti, reste])
        self._etat(["o"])
        self.assertEqual(seal_menu.lire_registre(), [])

    def test_une_cle_a_portee_de_git_est_signalee(self):
        _git("init", "-q", cwd=seal_menu.RACINE)
        open(os.path.join(seal_menu.RACINE, "sceau.key"), "w").close()
        self.assertIn("sceau.key", self._etat())

    def test_une_cle_commitee_demande_un_nouveau_sceau(self):
        _git("init", "-q", cwd=seal_menu.RACINE)
        open(os.path.join(seal_menu.RACINE, "sceau.p12"), "w").close()
        _git("add", "sceau.p12", cwd=seal_menu.RACINE)
        _git(
            "-c", "user.name=x", "-c", "user.email=x@x.invalid",
            "commit", "-q", "-m", "x", cwd=seal_menu.RACINE,
        )  # fmt: skip
        sortie = self._etat()
        self.assertIn("git rm --cached", sortie)
        self.assertIn(f"« {seal_menu.ENTREE_GENERER} »", sortie)


class TestGuide(unittest.TestCase):
    def _guide(self, reponse):
        sortie = io.StringIO()
        with patch("builtins.input", side_effect=[reponse]), redirect_stdout(
            sortie
        ):
            _Menu().execute_seal_guide()
        return sortie.getvalue()

    def test_une_cle_interne_se_distribue_par_son_certificat(self):
        sortie = self._guide("")
        self.assertIn("sceau.crt", sortie)
        self.assertIn("step-ca", sortie)
        self.assertNotIn(seal_menu.URL_AATL, sortie)

    def test_une_cle_externe_renvoie_a_la_liste_aatl(self):
        sortie = self._guide("o")
        self.assertIn(seal_menu.URL_AATL, sortie)
        self.assertIn("PKCS#11", sortie)


class TestTraductions(unittest.TestCase):
    """t() rend la clé elle-même quand elle manque : l'écran montrerait
    l'anglais à qui a choisi le français, sans que rien ne le signale."""

    def test_chaque_texte_du_menu_a_ses_deux_langues(self):
        source = Path(seal_menu.__file__).read_text(encoding="utf-8")
        cles = {
            noeud.args[0].value
            for noeud in ast.walk(ast.parse(source))
            if isinstance(noeud, ast.Call)
            and getattr(noeud.func, "id", None) == "t"
            and noeud.args
            and isinstance(noeud.args[0], ast.Constant)
        }
        self.assertGreater(len(cles), 40)
        manques = sorted(
            c for c in cles if not {"fr", "en"} <= set(TRANSLATIONS.get(c, {}))
        )
        self.assertEqual(manques, [])


if __name__ == "__main__":
    unittest.main()
