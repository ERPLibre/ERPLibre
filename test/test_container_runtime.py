#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Docker et Podman : les faits, et surtout le POURQUOI d'un refus.

« permission denied » sur la socket a trois causes qu'aucun message ne
distingue : le service est à l'arrêt, le compte n'est pas dans le groupe, ou
il y est depuis une session ouverte AVANT l'ajout. La troisième est la plus
coûteuse — tout paraît en place, et rien ne marche jusqu'à la reconnexion.

Ce que ces tests gardent :

- chacune des trois causes rend sa propre phrase ;
- un moteur qui répond sans sudo est préféré à un moteur qui l'exige : un
  menu qui réclame un mot de passe à chaque liste d'images ne sert à rien ;
- le préfixe sudo n'est posé que là où il est la seule voie ;
- l'installateur couvre les quatre familles de gestionnaires, pour les deux
  moteurs.
"""

import unittest
from pathlib import Path
from unittest import mock

from script.todo import container_runtime as cr

RACINE = Path(__file__).resolve().parents[1]
INSTALLATEUR = (RACINE / "script/install/install_container.sh").read_text(
    encoding="utf-8"
)


def _lanceur(reponses):
    """Un lanceur qui rend (code, sortie) selon le premier mot reconnu."""

    def lancer(cmd, timeout=10):
        cle = " ".join(cmd)
        for motif, reponse in reponses.items():
            if motif in cle:
                return reponse
        return 127, "not found"

    return lancer


class TestRaisonDuRefus(unittest.TestCase):
    """Le refus rend un CODE, jamais une phrase : une phrase choisirait une
    langue, et le module ne sait pas dans laquelle l'appelant parle."""

    def test_le_groupe_existe_mais_pas_dans_cette_session(self):
        with mock.patch.object(
            cr, "declare_dans_le_groupe", return_value=True
        ):
            with mock.patch.object(cr, "dans_le_groupe", return_value=False):
                code = cr._raison("docker", "permission denied")
        self.assertEqual("groupe_hors_session", code)

    def test_le_compte_n_est_pas_dans_le_groupe(self):
        with mock.patch.object(
            cr, "declare_dans_le_groupe", return_value=False
        ):
            code = cr._raison("docker", "permission denied")
        self.assertEqual("groupe_absent", code)

    def test_le_service_est_a_l_arret(self):
        with mock.patch.object(cr, "noyau_sans_modules", return_value=False):
            with mock.patch.object(cr, "service_actif", return_value=False):
                code = cr._raison(
                    "docker", "Cannot connect to the Docker daemon"
                )
        self.assertEqual("service_arrete", code)

    def test_un_noyau_sans_modules_passe_devant_l_etat_du_service(self):
        """Un démon qui refuse de naître alors que tout est en place n'a que
        cette cause, et le service paraît simplement arrêté."""
        with mock.patch.object(cr, "noyau_sans_modules", return_value=True):
            with mock.patch.object(cr, "service_actif", return_value=False):
                code = cr._raison("docker", "Cannot connect to the daemon")
        self.assertEqual("noyau_perime", code)

    def test_un_delai_depasse_se_dit(self):
        self.assertEqual("delai", cr._raison("podman", "timeout"))


class TestNoyauSansModules(unittest.TestCase):
    def test_il_se_juge_sur_l_arbre_du_noyau_EN_COURS(self):
        """Mettre le noyau à jour emporte /lib/modules de l'ancien : celui qui
        tourne garde ses modules chargés et ne peut plus en charger aucun."""
        with mock.patch.object(cr.os.path, "isdir", return_value=False):
            self.assertTrue(cr.noyau_sans_modules())
        with mock.patch.object(cr.os.path, "isdir", return_value=True):
            self.assertFalse(cr.noyau_sans_modules())


class TestSocketSansPrivilege(unittest.TestCase):
    """Sans DOCKER_HOST, le client s'adresse à la socket du démon de root : un
    mode sans privilège vivant paraît mort."""

    def test_elle_est_essayee_avant_de_conclure_au_refus(self):
        lanceur = _lanceur(
            {
                "env DOCKER_HOST=unix:///x/docker.sock docker info": (0, "ok"),
                "docker info": (1, "Cannot connect to the Docker daemon"),
                "docker --version": (0, "Docker version 29"),
            }
        )
        with mock.patch.object(cr, "binaire", return_value="/usr/bin/docker"):
            with mock.patch.object(
                cr, "socket_rootless", return_value="/x/docker.sock"
            ):
                with mock.patch.dict(cr.os.environ, {}, clear=True):
                    fiche = cr.etat("docker", lanceur=lanceur)
        self.assertTrue(fiche["sans_sudo"])
        self.assertEqual("unix:///x/docker.sock", fiche["docker_host"])

    def test_la_valeur_retenue_voyage_avec_la_commande(self):
        fiche = {
            "moteur": "docker",
            "sans_sudo": True,
            "docker_host": "unix:///x/docker.sock",
        }
        self.assertEqual(
            [
                "env",
                "DOCKER_HOST=unix:///x/docker.sock",
                "docker",
                "images",
            ],
            cr.commande(fiche, ["images"]),
        )


class TestEtat(unittest.TestCase):
    def test_un_binaire_absent_ne_lance_rien(self):
        with mock.patch.object(cr, "binaire", return_value=None):
            fiche = cr.etat("podman", lanceur=_lanceur({}))
        self.assertIsNone(fiche["binaire"])
        self.assertFalse(fiche["sans_sudo"])
        self.assertFalse(cr.utilisable(fiche))

    def test_un_moteur_qui_repond_porte_sa_composition(self):
        lanceur = _lanceur(
            {
                "podman --version": (0, "podman version 5.0.0"),
                "podman info": (0, "rootless: true"),
                "podman compose version": (0, "v1"),
                "systemctl": (3, "inactive"),
            }
        )
        with mock.patch.object(cr, "binaire", return_value="/usr/bin/podman"):
            with mock.patch.object(cr.shutil, "which", return_value="/x"):
                fiche = cr.etat("podman", lanceur=lanceur)
        self.assertTrue(fiche["sans_sudo"])
        self.assertTrue(fiche["rootless"])
        self.assertEqual(["podman", "compose"], fiche["compose"])


class TestModeSansPrivilege(unittest.TestCase):
    """Les deux moteurs l'annoncent dans des formes sans rapport."""

    def test_podman_le_rend_en_champ(self):
        lanceur = _lanceur(
            {"info": (0, "host:\n  security:\n    rootless: true")}
        )
        self.assertTrue(cr.rootless("podman", lanceur=lanceur))

    def test_podman_en_root_le_nie(self):
        lanceur = _lanceur({"info": (0, "    rootless: false")})
        self.assertFalse(cr.rootless("podman", lanceur=lanceur))

    def test_docker_le_liste_sans_valeur(self):
        """« Security Options » porte le mot seul : le chercher avec « true »
        rendrait « en root » un démon qui n'y est pas."""
        sortie = (
            " Security Options:\n  seccomp\n   Profile: builtin\n  rootless"
        )
        lanceur = _lanceur({"info": (0, sortie)})
        self.assertTrue(cr.rootless("docker", lanceur=lanceur))

    def test_docker_ordinaire_ne_l_annonce_pas(self):
        sortie = " Security Options:\n  seccomp\n   Profile: builtin"
        lanceur = _lanceur({"info": (0, sortie)})
        self.assertFalse(cr.rootless("docker", lanceur=lanceur))

    def test_un_moteur_muet_ne_tranche_pas(self):
        self.assertIsNone(cr.rootless("docker", lanceur=_lanceur({})))


class TestChoixDuMoteur(unittest.TestCase):
    def test_celui_qui_repond_sans_sudo_l_emporte(self):
        fiches = [
            {"moteur": "docker", "sans_sudo": False, "avec_sudo": True},
            {"moteur": "podman", "sans_sudo": True, "avec_sudo": True},
        ]
        self.assertEqual("podman", cr.moteur_par_defaut(fiches))

    def test_a_defaut_celui_qui_repond_avec_sudo(self):
        fiches = [
            {"moteur": "docker", "sans_sudo": False, "avec_sudo": True},
            {"moteur": "podman", "sans_sudo": False, "avec_sudo": False},
        ]
        self.assertEqual("docker", cr.moteur_par_defaut(fiches))

    def test_aucun_moteur_ne_rend_rien(self):
        fiches = [
            {"moteur": "docker", "sans_sudo": False, "avec_sudo": False},
        ]
        self.assertIsNone(cr.moteur_par_defaut(fiches))


class TestCommande(unittest.TestCase):
    def test_sans_sudo_la_commande_est_nue(self):
        fiche = {"moteur": "podman", "sans_sudo": True}
        self.assertEqual(["podman", "images"], cr.commande(fiche, ["images"]))

    def test_sinon_elle_est_prefixee(self):
        fiche = {"moteur": "docker", "sans_sudo": False}
        self.assertEqual(
            ["sudo", "docker", "images"], cr.commande(fiche, ["images"])
        )


class TestInstallateur(unittest.TestCase):
    def test_les_deux_moteurs_sont_couverts(self):
        for moteur in ("docker", "podman"):
            with self.subTest(moteur=moteur):
                self.assertIn(f"paquets_{moteur}(", INSTALLATEUR)

    def test_les_quatre_familles_sont_couvertes(self):
        for famille in ("debian", "arch", "rhel", "suse"):
            with self.subTest(famille=famille):
                self.assertIn(f"{famille})", INSTALLATEUR)

    def test_le_groupe_docker_est_annonce_comme_equivalent_a_root(self):
        """Un groupe dont la socket monte tout l'hôte se dit avant de
        s'accorder."""
        self.assertIn("équivaut", INSTALLATEUR)

    def test_l_amont_ne_s_engage_que_la_ou_l_editeur_empaquette(self):
        """get.docker.com se télécharge, s'exécute, puis s'arrête sur
        « Unsupported distribution » — après avoir posé son dépôt sur
        certaines familles. Le refus arrive donc avant le téléchargement."""
        self.assertIn("AMONT_SUPPORTE=", INSTALLATEUR)
        for connue in ("ubuntu", "debian", "fedora", "rhel", "sles"):
            with self.subTest(distribution=connue):
                self.assertIn(connue, INSTALLATEUR)
        # Le refus est posé avant l'aiguillage qui appellerait
        # installer_amont, et non dans la fonction elle-même.
        refus = INSTALLATEUR.index("--amont est sans objet")
        aiguillage = INSTALLATEUR.index('case "$MOTEUR" in')
        self.assertLess(refus, aiguillage)

    def test_arch_prend_la_voie_aur_au_lieu_de_s_arreter(self):
        """Refuser n'est bon que là où rien n'existe. Sur Arch le mode sans
        privilège est atteignable — par AUR — donc le script y va."""
        self.assertIn("docker-rootless-extras", INSTALLATEUR)
        self.assertIn("installer_aur", INSTALLATEUR)
        for helper in ("yay", "paru", "pikaur", "trizen"):
            with self.subTest(assistant=helper):
                self.assertIn(helper, INSTALLATEUR)

    def test_l_assistant_aur_n_est_jamais_lance_en_root(self):
        """makepkg refuse root par construction : l'assistant tourne sous le
        compte visé, dont on lit le PATH de connexion."""
        bloc = INSTALLATEUR[
            INSTALLATEUR.index("aur_helper()") : INSTALLATEUR.index(
                "conseil_rootless()"
            )
        ]
        self.assertIn('sudo -u "$compte"', bloc)
        self.assertNotIn("sudo -u root", bloc)

    def test_arch_garde_une_sortie_quand_aucun_assistant_n_est_la(self):
        conseil = INSTALLATEUR[
            INSTALLATEUR.index("conseil_rootless()") : INSTALLATEUR.index(
                "installer_amont()"
            )
        ]
        self.assertIn("makepkg", conseil)
        self.assertIn("podman", conseil)

    def test_le_mode_sans_privilege_se_juge_sur_les_unites(self):
        """Deux chemins mènent aux mêmes unités « utilisateur » : l'outil de
        Docker Inc. les ÉCRIT, le paquet d'Arch les LIVRE et ne fournit donc
        pas l'outil. Juger sur l'outil concluait « rien ici ne le pose » sur
        une machine où tout était posé."""
        self.assertIn("rootless_pret()", INSTALLATEUR)
        self.assertIn("/usr/lib/systemd/user/docker.socket", INSTALLATEUR)
        bloc = INSTALLATEUR[
            INSTALLATEUR.index("rootless_pret()") : INSTALLATEUR.index(
                "poser_rootless()"
            )
        ]
        self.assertIn("dockerd-rootless-setuptool.sh", bloc)
        self.assertIn("UNITE_ROOTLESS", bloc)

    def test_les_deux_chemins_menent_a_une_socket_active(self):
        """Les unités peuvent être en place et le démon refuser de naître :
        la socket est le seul témoin qui vaille."""
        bloc = INSTALLATEUR[INSTALLATEUR.index("poser_rootless() {") :]
        self.assertIn("systemctl --user enable --now docker.socket", bloc)
        self.assertIn("is-active docker.socket", bloc)

    def test_les_plages_subordonnees_sont_posees_pour_les_deux_moteurs(self):
        """Sans elles, newuidmap n'a aucune identité à donner au conteneur et
        le moteur s'arrête sur « could not find records for user »."""
        self.assertEqual(2, INSTALLATEUR.count('assurer_subid "$COMPTE"'))

    def test_la_plage_choisie_ne_recouvre_pas_celle_d_un_autre(self):
        """Deux comptes sur la même plage partagent les identités de leurs
        conteneurs : la plage libre se cherche, elle ne se suppose pas."""
        bloc = INSTALLATEUR[
            INSTALLATEUR.index("prochaine_plage()") : INSTALLATEUR.index(
                "assurer_subid()"
            )
        ]
        self.assertIn("65536", bloc)
        self.assertIn("grep -q", bloc)

    def test_le_mode_sans_privilege_nomme_sa_contrainte(self):
        """Aucun dépôt Debian ni Arch ne porte l'outil : le script le dit
        plutôt que d'échouer sur un binaire introuvable."""
        self.assertIn("dockerd-rootless-setuptool.sh", INSTALLATEUR)
        self.assertIn("--amont", INSTALLATEUR)


class TestSelection(unittest.TestCase):
    """Sur un écran qui efface, une faute de frappe ne doit jamais retenir en
    silence le sous-ensemble qu'elle n'a pas abîmé."""

    def test_les_formes_acceptees(self):
        cas = {
            "1 3": [0, 2],
            "1,3": [0, 2],
            "2-4": [1, 2, 3],
            "1 2-3 5": [0, 1, 2, 4],
            "*": [0, 1, 2, 3, 4],
            "tout": [0, 1, 2, 3, 4],
            "3 1 3": [0, 2],
        }
        for texte, attendu in cas.items():
            with self.subTest(texte=texte):
                self.assertEqual(attendu, cr.lire_selection(texte, 5))

    def test_une_partie_fautive_invalide_tout(self):
        for texte in ("1 x", "1,3,9", "0", "4-2", "", "   ", "1-"):
            with self.subTest(texte=texte):
                self.assertIsNone(cr.lire_selection(texte, 5))

    def test_une_liste_vide_ne_rend_rien(self):
        self.assertIsNone(cr.lire_selection("*", 0))


class TestImages(unittest.TestCase):
    def test_une_image_nommee_se_designe_par_son_nom(self):
        """Effacer par identifiant une image à plusieurs noms échoue sans
        --force, et --force l'arracherait à tous ses noms."""
        image = {"id": "abc", "depot": "d/x", "etiquette": "1.0"}
        self.assertEqual("d/x:1.0", cr.reference_image(image))

    def test_une_image_sans_nom_se_designe_par_son_identifiant(self):
        image = {"id": "abc", "depot": "<none>", "etiquette": "<none>"}
        self.assertEqual("abc", cr.reference_image(image))

    def test_les_lignes_etrangeres_sont_ecartees(self):
        """Podman sans privilège écrit ses avertissements sur stderr, que le
        lanceur mêle à la sortie."""
        sortie = (
            'WARN[0000] "/" is not a shared mount\n'
            "a1\td/x\t1.0\t2GB\t3 days ago\n"
            "a2\t<none>\t<none>\t1GB\t4 days ago\n"
        )
        lanceur = _lanceur({"images": (0, sortie)})
        images = cr.lister_images(
            {"moteur": "podman", "sans_sudo": True}, lanceur=lanceur
        )
        self.assertEqual(["a1", "a2"], [i["id"] for i in images])

    def test_un_moteur_qui_refuse_ne_rend_rien(self):
        lanceur = _lanceur({"images": (1, "permission denied")})
        self.assertEqual(
            [],
            cr.lister_images({"moteur": "docker", "sans_sudo": True}, lanceur),
        )


class TestProjets(unittest.TestCase):
    INSPECT = """[
      {"Name": "/p-web-1", "State": {"Status": "running"},
       "Config": {"Image": "img/web:1",
                  "Labels": {"com.docker.compose.project": "p",
                             "com.docker.compose.project.working_dir": "/d"}}},
      {"Name": "/p-db-1", "State": {"Status": "exited"},
       "Config": {"Image": "img/db:2",
                  "Labels": {"com.docker.compose.project": "p"}}},
      {"Name": "/q-a-1", "State": {"Status": "running"},
       "Config": {"Image": "img/web:1",
                  "Labels": {"io.podman.compose.project": "q"}}},
      {"Name": "/seul", "State": {"Status": "running"},
       "Config": {"Image": "img/x:1", "Labels": {}}}
    ]"""

    def _lister(self, prefixe=""):
        lanceur = _lanceur(
            {
                "ps -aq": (0, "WARN bruit\naaaaaaaaaaaa\nbbbbbbbbbbbb\n"),
                "inspect": (0, prefixe + self.INSPECT),
            }
        )
        return cr.lister_projets(
            {"moteur": "docker", "sans_sudo": True}, lanceur=lanceur
        )

    def test_les_conteneurs_se_rangent_sous_leur_projet(self):
        projets = self._lister()
        self.assertEqual({"p", "q"}, set(projets))
        self.assertEqual("/d", projets["p"]["dossier"])
        self.assertEqual(2, len(projets["p"]["conteneurs"]))
        self.assertEqual(["img/web:1", "img/db:2"], projets["p"]["images"])

    def test_un_conteneur_hors_projet_n_appartient_a_personne(self):
        """L'effacer avec un espace de travail serait effacer ce que personne
        n'a désigné."""
        noms = [
            c["nom"] for p in self._lister().values() for c in p["conteneurs"]
        ]
        self.assertNotIn("seul", noms)

    def test_l_etiquette_de_podman_compose_est_lue(self):
        self.assertIn("q", self._lister())

    def test_un_avertissement_avant_le_json_ne_casse_rien(self):
        self.assertEqual({"p", "q"}, set(self._lister("WARN bruit\n")))

    def test_les_volumes_du_projet_ecartent_les_avertissements(self):
        lanceur = _lanceur(
            {"volume ls": (0, "WARN un avertissement\np_data\n")}
        )
        ressources = cr.ressources_projet(
            {"moteur": "docker", "sans_sudo": True}, "p", lanceur=lanceur
        )
        self.assertEqual(["p_data"], ressources["volume"])


if __name__ == "__main__":
    unittest.main()
