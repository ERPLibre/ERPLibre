#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le menu Docker / Podman lance-t-il ce qu'il annonce ?

Trois gestes de ce menu sont irréversibles ou coûteux, et chacun se décide
sur un détail que l'affichage seul ne garantit pas :

- l'installation de Docker demande un MODE. Le groupe « docker » équivaut à
  root sur l'hôte, le mode sans privilège n'y touche pas : le drapeau doit
  suivre la réponse, et une faute de frappe ne le choisit jamais ;
- l'effacement porte sur les VOLUMES, donc sur la base de données. Il se
  refuse par un simple non, et rien ne part ;
- les scripts de script/docker/ appellent la commande docker par son nom.
  Sous Podman seul, le menu doit s'arrêter AVANT de lancer, sinon l'erreur
  accuse le script au lieu du moteur absent.
"""

import builtins
import contextlib
import io
import re
import shlex
import sys
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.todo import container_menu, todo_i18n  # noqa: E402
from script.todo.todo import TODO  # noqa: E402


class ExecuteFactice:
    """Le lanceur du CLI rend un CODE DE SORTIE, et c'est sur lui que le menu
    décide d'enchaîner un diagnostic."""

    def __init__(self, code=0):
        self.commandes = []
        self.code = code

    def exec_command_live(self, cmd, **kwargs):
        self.commandes.append(cmd)
        return self.code


class Banc(unittest.TestCase):
    def setUp(self):
        # Un menu dessiné enregistre sa clé de télémétrie dans le HOME :
        # aucun test de ce fichier n'y écrit.
        self.enterContext(mock.patch("script.todo.todo_telemetry.record"))

    def todo(self, fiche=None, code=0):
        todo = TODO.__new__(TODO)
        todo.execute = ExecuteFactice(code)
        if fiche is not None:
            todo._container_fiche = lambda: fiche
        return todo

    @staticmethod
    @contextlib.contextmanager
    def reponses(entrees=(), prompts=()):
        """Joue des réponses écrites d'avance sur input(), qui répond aussi
        aux choix (ui.choose), et sur click.prompt, qui répond aux menus ;
        input() rend "" une fois ses réponses épuisées."""
        suite = iter(entrees)
        ancien = builtins.input
        builtins.input = lambda *a, **k: next(suite, "")
        sortie = io.StringIO()
        try:
            with mock.patch.object(
                container_menu.click, "prompt", side_effect=list(prompts)
            ):
                with contextlib.redirect_stdout(sortie):
                    yield sortie
        finally:
            builtins.input = ancien


class TestInstallation(Banc):
    def test_le_mode_groupe_est_celui_de_la_reponse(self):
        todo = self.todo()
        with self.reponses(entrees=["1", "o"]):
            todo._container_install("docker")
        self.assertEqual(1, len(todo.execute.commandes))
        cmd = todo.execute.commandes[0]
        self.assertIn("--groupe", cmd)
        self.assertNotIn("--rootless", cmd)

    def test_le_mode_sans_privilege_peut_prendre_l_amont(self):
        todo = self.todo()
        with self.reponses(entrees=["2", "o", "o"]):
            todo._container_install("docker")
        cmd = todo.execute.commandes[0]
        self.assertIn("--rootless", cmd)
        self.assertIn("--amont", cmd)

    def test_l_amont_se_refuse_sans_emporter_le_mode(self):
        todo = self.todo()
        with self.reponses(entrees=["2", "n", "o"]):
            todo._container_install("docker")
        cmd = todo.execute.commandes[0]
        self.assertIn("--rootless", cmd)
        self.assertNotIn("--amont", cmd)

    def test_podman_ne_demande_aucun_mode(self):
        """Sans démon ni groupe, il n'y a rien à arbitrer."""
        todo = self.todo()
        with self.reponses(entrees=["o"], prompts=[]):
            todo._container_install("podman")
        cmd = todo.execute.commandes[0]
        self.assertIn("podman", cmd)
        self.assertNotIn("--groupe", cmd)

    def test_un_refus_ne_lance_rien(self):
        todo = self.todo()
        with self.reponses(entrees=["1", "n"]):
            todo._container_install("docker")
        self.assertEqual([], todo.execute.commandes)

    def test_le_mode_se_choisit_sous_les_regles_d_un_choix(self):
        """Vide : le mode sans privilège, marqué ; [0] : rien ne s'installe ;
        une faute de frappe est dite, et la question revient au lieu de
        donner le groupe, équivalent root."""
        for entrees, drapeau in (
            (["", "n", "o"], "--rootless"),
            (["x", "1", "o"], "--groupe"),
            (["0"], None),
        ):
            with self.subTest(entrees=entrees):
                todo = self.todo()
                with self.reponses(entrees=entrees) as sortie:
                    todo._container_install("docker")
                if drapeau is None:
                    self.assertEqual([], todo.execute.commandes)
                else:
                    self.assertIn(drapeau, todo.execute.commandes[0])
        self.assertIn("[2] rootless", sortie.getvalue())
        self.assertIn(todo_i18n.t("(default)"), sortie.getvalue())


class TestEffacement(Banc):
    FICHE = {"moteur": "docker", "sans_sudo": True}

    def test_il_nomme_les_volumes_avant_de_demander(self):
        todo = self.todo(self.FICHE)
        with self.reponses(entrees=["o"]) as sortie:
            todo._container_nettoyage()
        self.assertIn("VOLUME", sortie.getvalue().upper())
        self.assertIn("--volumes", todo.execute.commandes[0])

    def test_un_refus_n_efface_rien(self):
        todo = self.todo(self.FICHE)
        with self.reponses(entrees=["n"]):
            todo._container_nettoyage()
        self.assertEqual([], todo.execute.commandes)


class TestLigneDeCommandeDocker(Banc):
    """Les scripts de script/docker/ appellent « docker » par son nom, et
    s'adressent à la socket du défaut."""

    FICHE_VIVANTE = {
        "moteur": "docker",
        "sans_sudo": True,
        "avec_sudo": True,
        "docker_host": None,
    }

    def test_sans_docker_le_sous_menu_ne_s_ouvre_pas(self):
        todo = self.todo()
        with mock.patch.object(
            container_menu.shutil, "which", return_value=None
        ):
            with self.reponses() as sortie:
                todo._container_erplibre()
        self.assertEqual([], todo.execute.commandes)
        self.assertIn("docker", sortie.getvalue())

    def test_avec_docker_chaque_entree_lance_son_script(self):
        todo = self.todo()
        todo._container_fiches = lambda: [self.FICHE_VIVANTE]
        with mock.patch.object(
            container_menu.shutil, "which", return_value="/usr/bin/docker"
        ):
            with self.reponses(prompts=["1", "5", "0"]):
                todo._container_erplibre()
        self.assertEqual(
            [
                "./script/docker/docker_exec.sh",
                "./script/docker/docker_repo_show_status.sh",
            ],
            todo.execute.commandes,
        )

    def test_un_moteur_muet_arrete_avant_le_script(self):
        """Le script s'arrêterait sur « /var/run/docker.sock: no such file or
        directory », qui accuse le script et non le moteur."""
        todo = self.todo()
        todo._container_fiches = lambda: [
            {
                "moteur": "docker",
                "sans_sudo": False,
                "avec_sudo": False,
                "docker_host": None,
            }
        ]
        with mock.patch.object(
            container_menu.shutil, "which", return_value="/usr/bin/docker"
        ):
            with self.reponses() as sortie:
                todo._container_erplibre()
        self.assertEqual([], todo.execute.commandes)
        self.assertIn("docker", sortie.getvalue())

    def test_la_socket_du_compte_voyage_avec_le_script(self):
        """Ces scripts s'adressent à la socket du défaut, où un démon par
        compte n'est pas."""
        todo = self.todo()
        todo._container_fiches = lambda: [
            {
                "moteur": "docker",
                "sans_sudo": True,
                "avec_sudo": True,
                "docker_host": "unix:///run/user/1000/docker.sock",
            }
        ]
        with mock.patch.object(
            container_menu.shutil, "which", return_value="/usr/bin/docker"
        ):
            with self.reponses(prompts=["1", "0"]):
                todo._container_erplibre()
        self.assertEqual(
            [
                "DOCKER_HOST=unix:///run/user/1000/docker.sock"
                " ./script/docker/docker_exec.sh"
            ],
            todo.execute.commandes,
        )

    def test_la_copie_lancee_seule_verifie_le_moteur(self):
        """Lancée seule, depuis la TUI de télémétrie, la copie demande son
        préfixe : la socket du compte voyage avec elle, et sans docker elle
        ne part pas."""
        todo = self.todo()
        todo._container_fiches = lambda: [
            {
                "moteur": "docker",
                "sans_sudo": True,
                "avec_sudo": True,
                "docker_host": "unix:///forged/docker.sock",
            }
        ]
        with mock.patch.object(
            container_menu.shutil, "which", return_value="/usr/bin/docker"
        ):
            with self.reponses(prompts=[__file__, ""]):
                todo._container_copier_fichier()
        self.assertEqual(
            [
                "DOCKER_HOST=unix:///forged/docker.sock "
                + shlex.join(["./script/docker/docker_copy_file.sh", __file__])
            ],
            todo.execute.commandes,
        )
        with mock.patch.object(
            container_menu.shutil, "which", return_value=None
        ):
            with self.reponses() as sortie:
                todo._container_copier_fichier()
        self.assertEqual(1, len(todo.execute.commandes))
        self.assertIn("docker", sortie.getvalue())

    def test_un_script_lance_seul_verifie_le_moteur(self):
        """Lancé seul, depuis la TUI de télémétrie, un script demande son
        préfixe : la socket du compte voyage avec lui, et sans docker il ne
        part pas."""
        todo = self.todo()
        todo._container_fiches = lambda: [
            {
                "moteur": "docker",
                "sans_sudo": True,
                "avec_sudo": True,
                "docker_host": "unix:///forged/docker.sock",
            }
        ]
        with mock.patch.object(
            container_menu.shutil, "which", return_value="/usr/bin/docker"
        ):
            with self.reponses():
                todo._container_script(script="./script/docker/docker_exec.sh")
        with mock.patch.object(
            container_menu.shutil, "which", return_value=None
        ):
            with self.reponses():
                todo._container_script(script="./script/docker/docker_exec.sh")
        self.assertEqual(
            [
                "DOCKER_HOST=unix:///forged/docker.sock"
                " ./script/docker/docker_exec.sh"
            ],
            todo.execute.commandes,
        )

    def test_une_source_absente_ne_lance_pas_la_copie(self):
        todo = self.todo()
        with self.reponses(prompts=["/n/existe/pas"]) as sortie:
            todo._container_copier_fichier("")
        self.assertEqual([], todo.execute.commandes)
        self.assertIn("/n/existe/pas", sortie.getvalue())


class TestInventaire(Banc):
    def test_chaque_liste_lance_sa_sous_commande(self):
        todo = self.todo({"moteur": "podman", "sans_sudo": True})
        with self.reponses():
            todo._container_inventaire("images")
            todo._container_inventaire("ps -a")
        self.assertEqual(
            ["podman images", "podman ps -a"], todo.execute.commandes
        )

    def test_le_prefixe_sudo_suit_la_fiche(self):
        todo = self.todo({"moteur": "docker", "sans_sudo": False})
        with self.reponses():
            todo._container_inventaire("images")
        self.assertEqual("sudo docker images", todo.execute.commandes[0])

    def test_sans_moteur_rien_ne_part(self):
        todo = self.todo()
        todo._container_fiche = lambda: None
        with self.reponses():
            todo._container_inventaire("images")
        self.assertEqual([], todo.execute.commandes)


class TestNettoyageImages(Banc):
    FICHE = {"moteur": "docker", "sans_sudo": True}
    IMAGES = [
        {
            "id": "a1",
            "depot": "d/x",
            "etiquette": "1",
            "taille": "2GB",
            "age": "1 day",
        },
        {
            "id": "a2",
            "depot": "<none>",
            "etiquette": "<none>",
            "taille": "1GB",
            "age": "2 days",
        },
        {
            "id": "a3",
            "depot": "d/y",
            "etiquette": "2",
            "taille": "3GB",
            "age": "3 days",
        },
    ]

    def _banc(self, code=0):
        todo = self.todo(self.FICHE, code=code)
        return todo

    def _jouer(self, todo, selection, reponse, usages=None, decisions=()):
        """Joue l'écran sans toucher au moteur : la liste des images ET le
        rattachement aux conteneurs sont simulés — le second interrogerait
        sinon le vrai moteur de la machine qui lance les tests."""
        with (
            mock.patch.object(
                container_menu.container_runtime,
                "lister_images",
                return_value=self.IMAGES,
            ),
            mock.patch.object(
                container_menu.container_runtime,
                "conteneurs_par_image",
                return_value=usages or {},
            ),
        ):
            with self.reponses(entrees=[selection, *decisions, reponse]) as s:
                todo._container_nettoyer_images()
        return s.getvalue()

    def test_les_images_choisies_partent_par_leur_nom(self):
        todo = self._banc()
        self._jouer(todo, "1 2", "o")
        self.assertEqual(
            ["docker rmi d/x:1", "docker rmi a2"], todo.execute.commandes
        )

    def test_jamais_de_force(self):
        """Une image qu'un conteneur emploie doit être refusée."""
        todo = self._banc()
        self._jouer(todo, "*", "o")
        for cmd in todo.execute.commandes:
            with self.subTest(cmd=cmd):
                self.assertNotIn("-f", cmd.split())
                self.assertNotIn("--force", cmd)

    def test_une_selection_fautive_n_efface_rien_et_le_dit(self):
        """« 1 x » ne retient pas « 1 » : la saisie entière est dite
        invalide, la question revient, et une réponse vide n'efface rien
        sans que la confirmation soit posée."""
        todo = self._banc()
        rendu = self._jouer(todo, "1 x", "")
        self.assertEqual([], todo.execute.commandes)
        self.assertIn(f"{todo_i18n.t('Invalid choice: ')}1 x", rendu)
        self.assertEqual(2, rendu.count(todo_i18n.t("Images to remove:")))
        self.assertNotIn(todo_i18n.t("Will remove:"), rendu)

    def test_seule_la_confirmation_efface_ce_que_la_reponse_choisit(self):
        """Vide, [0], « tous », qui n'est pas un mot de tout, une plage à
        l'envers : rien n'est choisi, et rien ne part sans confirmation ;
        les deux derniers sont dits invalides. « tout » choisit les trois,
        que la confirmation nomme avant que rien ne parte."""
        for selection in ("", "0", "tous", "3-1"):
            with self.subTest(selection=selection):
                todo = self._banc()
                rendu = self._jouer(todo, selection, "o")
                self.assertEqual([], todo.execute.commandes)
                self.assertNotIn(todo_i18n.t("Will remove:"), rendu)
                faute = f"{todo_i18n.t('Invalid choice: ')}{selection}\n"
                self.assertEqual(selection in ("tous", "3-1"), faute in rendu)
        todo = self._banc()
        rendu = self._jouer(todo, "tout", "n")
        self.assertEqual([], todo.execute.commandes)
        annonce = rendu.split(todo_i18n.t("Will remove:"))[1]
        for ref in ("d/x:1", "a2", "d/y:2"):
            self.assertIn(ref, annonce)
        todo = self._banc()
        self._jouer(todo, "all", "o")
        self.assertEqual(3, len(todo.execute.commandes))

    def test_une_image_se_choisit_aussi_par_son_nom(self):
        todo = self._banc()
        self._jouer(todo, "d/y:2", "o")
        self.assertEqual(["docker rmi d/y:2"], todo.execute.commandes)

    def test_un_refus_de_confirmation_n_efface_rien(self):
        todo = self._banc()
        self._jouer(todo, "1", "n")
        self.assertEqual([], todo.execute.commandes)

    def test_un_refus_du_moteur_est_nomme(self):
        """Sans le compte rendu, seule la dernière sortie du moteur reste à
        l'écran, et un refus passe pour une réussite."""
        todo = self._banc(code=1)
        rendu = self._jouer(todo, "3", "o")
        refus = [
            ligne
            for ligne in rendu.splitlines()
            if ligne.startswith(todo_i18n.t("Refused:"))
        ]
        self.assertEqual(1, len(refus))
        self.assertIn("d/y:2", refus[0])
        self.assertIn(f"{todo_i18n.t('Removed:')} 0/1", rendu)


class TestConflitImage(TestNettoyageImages):
    """Une image qu'un conteneur tient se décide AVANT d'effacer : forcer ne
    retire que son nom, et l'image reste avec toute sa taille."""

    ARRETE = {
        "a1": [
            {"nom": "p-web-1", "etat": "exited", "projet": "p"},
        ]
    }
    EN_MARCHE = {
        "a1": [
            {"nom": "p-web-1", "etat": "running", "projet": "p"},
        ]
    }

    def test_la_liste_montre_qui_tient_chaque_image(self):
        todo = self._banc()
        rendu = self._jouer(todo, "", "n", usages=self.ARRETE)
        ligne = next(l for l in rendu.splitlines() if "d/x:1" in l)
        self.assertIn("p-web-1", ligne)

    def test_la_question_nomme_le_conteneur_son_etat_et_son_projet(self):
        todo = self._banc()
        rendu = self._jouer(
            todo, "1", "n", usages=self.ARRETE, decisions=["1"]
        )
        self.assertIn("p-web-1", rendu)
        self.assertIn("exited", rendu)
        self.assertIn(todo_i18n.t("project") + " p", rendu)

    def test_garder_laisse_l_image_et_efface_les_autres(self):
        todo = self._banc()
        self._jouer(todo, "1 3", "o", usages=self.ARRETE, decisions=["1"])
        self.assertEqual(["docker rmi d/y:2"], todo.execute.commandes)

    def test_vider_efface_les_conteneurs_avant_l_image(self):
        """Tant qu'un seul conteneur tient l'image, « rmi » la refuse."""
        todo = self._banc()
        self._jouer(todo, "1", "o", usages=self.ARRETE, decisions=["2"])
        self.assertEqual(
            ["docker rm -f p-web-1", "docker rmi d/x:1"],
            todo.execute.commandes,
        )

    def test_forcer_retire_le_nom(self):
        todo = self._banc()
        self._jouer(todo, "1", "o", usages=self.ARRETE, decisions=["3"])
        self.assertEqual(["docker rmi -f d/x:1"], todo.execute.commandes)

    def test_un_conteneur_en_marche_retire_le_forcage(self):
        """Le moteur refuserait : « 3 » n'existe plus, la question revient,
        et une réponse vide garde l'image."""
        todo = self._banc()
        rendu = self._jouer(
            todo, "1", "o", usages=self.EN_MARCHE, decisions=["3", ""]
        )
        self.assertEqual([], todo.execute.commandes)
        self.assertNotIn(
            todo_i18n.t("Force - removes the name only; the space stays"),
            rendu,
        )

    def test_un_refus_final_n_efface_pas_meme_les_conteneurs(self):
        """Les décisions ne sont qu'un plan tant que la confirmation n'est
        pas donnée."""
        todo = self._banc()
        self._jouer(todo, "1", "n", usages=self.ARRETE, decisions=["2"])
        self.assertEqual([], todo.execute.commandes)

    def test_dans_le_doute_rien_ne_part(self):
        """Retour et une réponse vide gardent l'image ; une saisie qui n'est
        pas un choix est dite, et la question revient."""
        for decisions in (["0"], [""], ["x", ""]):
            with self.subTest(decisions=decisions):
                todo = self._banc()
                self._jouer(
                    todo, "1", "o", usages=self.ARRETE, decisions=decisions
                )
                self.assertEqual([], todo.execute.commandes)


class TestConteneursParImage(unittest.TestCase):
    """Un conflit se rattache par l'identifiant de l'image, jamais par le
    filtre « ancestor », qui ramasse les images bâties par-dessus."""

    def test_seul_le_conteneur_de_cette_image_la_tient(self):
        from script.todo import container_runtime as cr

        conteneurs = [
            {"nom": "a", "image_id": "aaaa1111bbbb", "etat": "exited"},
            {"nom": "b", "image_id": "cccc2222dddd", "etat": "running"},
        ]
        images = [{"id": "aaaa1111"}, {"id": "eeee3333"}]
        with mock.patch.object(
            cr, "_inspecter_conteneurs", return_value=conteneurs
        ):
            usages = cr.conteneurs_par_image({"moteur": "docker"}, images)
        self.assertEqual({"aaaa1111"}, set(usages))
        self.assertEqual(["a"], [c["nom"] for c in usages["aaaa1111"]])


class TestNettoyageProjets(Banc):
    FICHE = {"moteur": "docker", "sans_sudo": True}
    PROJETS = {
        "p": {
            "dossier": "/d",
            "conteneurs": [
                {"nom": "p-web-1", "image": "img/web:1", "etat": "running"},
                {"nom": "p-db-1", "image": "img/db:2", "etat": "running"},
            ],
            "images": ["img/web:1", "img/db:2"],
        },
    }
    RESSOURCES = {"volume": ["p_db-data"], "network": ["p_default"]}

    def _jouer(self, todo, selection, reponse):
        with (
            mock.patch.object(
                container_menu.container_runtime,
                "lister_projets",
                return_value=self.PROJETS,
            ),
            mock.patch.object(
                container_menu.container_runtime,
                "ressources_projet",
                return_value=self.RESSOURCES,
            ),
        ):
            with self.reponses(entrees=[selection, reponse]) as s:
                todo._container_nettoyer_projets()
        return s.getvalue()

    def test_l_ordre_conteneurs_reseaux_volumes_images(self):
        """Le moteur refuse d'effacer ce qu'un conteneur tient encore."""
        todo = self.todo(self.FICHE)
        self._jouer(todo, "1", "o")
        self.assertEqual(
            [
                "docker rm -f p-web-1",
                "docker rm -f p-db-1",
                "docker network rm p_default",
                "docker volume rm p_db-data",
                "docker rmi img/web:1",
                "docker rmi img/db:2",
            ],
            todo.execute.commandes,
        )

    def test_les_volumes_sont_annonces_avant_la_question(self):
        """Ils portent la base, et ne reviennent pas."""
        todo = self.todo(self.FICHE)
        rendu = self._jouer(todo, "1", "n")
        self.assertIn("p_db-data", rendu)
        self.assertEqual([], todo.execute.commandes)

    def test_les_images_ne_sont_jamais_forcees(self):
        """Une image qu'un AUTRE projet emploie doit être refusée."""
        todo = self.todo(self.FICHE)
        self._jouer(todo, "1", "o")
        for cmd in todo.execute.commandes:
            if " rmi " in cmd:
                with self.subTest(cmd=cmd):
                    self.assertNotIn("-f", cmd.split())

    def test_une_selection_hors_liste_n_efface_rien(self):
        """« 2 » est dit invalide, la question revient, et « o », qui n'est
        pas un choix non plus, n'efface rien."""
        todo = self.todo(self.FICHE)
        rendu = self._jouer(todo, "2", "o")
        self.assertEqual([], todo.execute.commandes)
        self.assertIn(f"{todo_i18n.t('Invalid choice: ')}2", rendu)

    def test_seule_la_confirmation_efface_un_espace_de_travail(self):
        """Vide, [0] : rien n'est choisi ni demandé, même suivi de « o ».
        « tout » et le nom du projet le choisissent, et la confirmation,
        qui nomme ses volumes, garde encore tout sur « n »."""
        cas = (("", "o"), ("0", "o"), ("tout", "n"), ("p", "n"))
        for selection, reponse in cas:
            with self.subTest(selection=selection):
                todo = self.todo(self.FICHE)
                rendu = self._jouer(todo, selection, reponse)
                self.assertEqual([], todo.execute.commandes)
                self.assertEqual(reponse == "n", "p_db-data" in rendu)


class TestNettoyageGlobal(Banc):
    def test_il_dit_ce_qui_reste(self):
        """« Tout » s'arrête à ce qui tourne : prune ne touche pas un
        conteneur en marche."""
        todo = self.todo({"moteur": "docker", "sans_sudo": True})
        with self.reponses(entrees=["n"]) as sortie:
            todo._container_nettoyage()
        self.assertEqual([], todo.execute.commandes)
        self.assertIn(
            todo_i18n.t("Running containers, and what they use, are kept."),
            sortie.getvalue(),
        )


class TestConstructionOdoo(Banc):
    COUT = todo_i18n.t("Several versions: hours of work, tens of GB.")

    def _banc(self, code=0):
        todo = self.todo(code=code)
        todo._container_exige_docker = lambda: ""
        todo._container_versions_odoo = lambda: ["18.0", "17.0", "12.0"]
        return todo

    def test_une_version_choisie_ne_lance_qu_elle(self):
        """Une seule version : ni l'avertissement du coût ni sa question."""
        todo = self._banc()
        with self.reponses(entrees=["3", "n"]) as sortie:
            todo._container_build_odoo()
        self.assertEqual(
            ["./script/docker/docker_build.sh --odoo_12"],
            todo.execute.commandes,
        )
        self.assertNotIn(self.COUT, sortie.getvalue())

    def test_plusieurs_versions_se_choisissent_dans_l_ordre_du_catalogue(
        self,
    ):
        """Vide ou [0] ne construit rien ; « 3 1 » construit ces deux-là,
        après l'avertissement du coût."""
        for entrees in ([""], ["0"]):
            with self.subTest(entrees=entrees):
                todo = self._banc()
                with self.reponses(entrees=entrees):
                    todo._container_build_odoo()
                self.assertEqual([], todo.execute.commandes)
        todo = self._banc()
        with self.reponses(entrees=["3 1", "o", "n"]) as sortie:
            todo._container_build_odoo()
        self.assertIn(self.COUT, sortie.getvalue())
        self.assertEqual(
            [
                "./script/docker/docker_build.sh --odoo_18",
                "./script/docker/docker_build.sh --odoo_12",
            ],
            todo.execute.commandes,
        )

    def test_toutes_les_lance_dans_l_ordre_du_catalogue(self):
        todo = self._banc()
        with self.reponses(entrees=["tout", "o", "n"]):
            todo._container_build_odoo()
        self.assertEqual(
            [
                "./script/docker/docker_build.sh --odoo_18",
                "./script/docker/docker_build.sh --odoo_17",
                "./script/docker/docker_build.sh --odoo_12",
            ],
            todo.execute.commandes,
        )

    def test_plusieurs_demandent_confirmation_avant_les_heures(self):
        """Une image de production pèse une dizaine de Go : dès deux
        versions, toutes ou non, un refus doit tout arrêter."""
        for choix in ("*", "1 3"):
            with self.subTest(choix=choix):
                todo = self._banc()
                with self.reponses(entrees=[choix, "n"]) as sortie:
                    todo._container_build_odoo()
                self.assertEqual([], todo.execute.commandes)
                self.assertIn(self.COUT, sortie.getvalue())

    def test_un_echec_n_arrete_pas_le_balayage(self):
        """Une version qui casse n'apprend rien sur les suivantes, et les
        relancer une à une coûte des heures."""
        todo = self._banc(code=1)
        with self.reponses(entrees=["all", "o", "n"]) as sortie:
            todo._container_build_odoo()
        self.assertEqual(3, len(todo.execute.commandes))
        rendu = sortie.getvalue()
        self.assertIn("18.0", rendu)
        self.assertIn("12.0", rendu)

    def test_le_sans_cache_ne_se_demande_qu_une_fois(self):
        todo = self._banc()
        with self.reponses(entrees=["1-3", "o", "o"]):
            todo._container_build_odoo()
        for cmd in todo.execute.commandes:
            with self.subTest(cmd=cmd):
                self.assertTrue(cmd.endswith(" --no-cache"))


class TestVersionsOdoo(Banc):
    def test_elles_viennent_du_catalogue_la_plus_recente_en_tete(self):
        todo = self.todo()
        versions = todo._container_versions_odoo()
        self.assertTrue(versions)
        self.assertEqual(versions, sorted(versions, key=float, reverse=True))
        self.assertIn("18.0", versions)


class TestRaisonsTraduites(Banc):
    def test_chaque_code_du_module_a_sa_phrase(self):
        """Un code sans phrase n'affiche RIEN : le diagnostic dirait « non »
        sans jamais dire pourquoi, ce qui est tout ce qu'on lui demande."""
        source = (RACINE / "script/todo/container_runtime.py").read_text(
            encoding="utf-8"
        )
        corps = source[
            source.index("def _raison(") : source.index("def etat(")
        ]
        codes = set(re.findall(r'return "([a-z_]+)"', corps))
        self.assertTrue(codes)
        self.assertEqual(set(), codes - set(container_menu.RAISONS))

    def test_chaque_phrase_est_traduite(self):
        for code, phrase in container_menu.RAISONS.items():
            with self.subTest(code=code):
                self.assertIn(phrase, todo_i18n.TRANSLATIONS)


class TestIconeDesMoteurs(Banc):
    def test_la_liste_porte_les_icones(self):
        todo = self.todo()
        todo._container_fiches = lambda: [
            {"moteur": "docker", "binaire": "/usr/bin/docker"},
            {"moteur": "podman", "binaire": "/usr/bin/podman"},
        ]
        with self.reponses(entrees=["2"]) as sortie:
            fiche = todo._container_choisir_moteur()
        rendu = sortie.getvalue()
        self.assertIn("[1] 🐳 docker", rendu)
        self.assertIn("[2] 🦭 podman", rendu)
        # Le rang choisi désigne toujours le moteur, jamais son libellé :
        # décorer l'affichage ne doit pas décorer ce sur quoi on décide.
        self.assertEqual("podman", fiche["moteur"])

    def test_un_moteur_sans_icone_garde_son_nom(self):
        todo = self.todo()
        self.assertEqual("autre", todo._container_libelle_moteur("autre"))

    def test_un_moteur_se_choisit_par_son_nom_ou_par_defaut(self):
        """Le nom nu, pas son libellé décoré ; une réponse vide prend le
        premier, marqué ; [0] n'en prend aucun."""
        todo = self.todo()
        todo._container_fiches = lambda: [
            {"moteur": "docker", "binaire": "/usr/bin/docker"},
            {"moteur": "podman", "binaire": "/usr/bin/podman"},
        ]
        for reponse, moteur in (("podman", "podman"), ("", "docker")):
            with self.subTest(reponse=reponse):
                with self.reponses(entrees=[reponse]):
                    fiche = todo._container_choisir_moteur()
                self.assertEqual(moteur, fiche["moteur"])
        with self.reponses(entrees=["0"]):
            self.assertIsNone(todo._container_choisir_moteur())

    def test_renoncer_au_moteur_n_efface_rien(self):
        """Entre deux moteurs, [0], ou le libellé décoré, qui n'est pas un
        nom, puis [0] : aucun nettoyage qui efface ne liste ni ne lance.
        Les listes doublées sont vides : un nettoyage qui irait plus loin
        s'arrêterait là, sans interroger le vrai moteur."""
        prets = [{"moteur": m, "sans_sudo": True} for m in ("docker", "x")]
        runtime = container_menu.container_runtime
        faute = todo_i18n.t("Invalid choice: ")
        for nom in ("nettoyage", "nettoyer_images", "nettoyer_projets"):
            for entrees in (["0"], ["🐳 docker", "0"]):
                todo = self.todo()
                todo._container_fiches = lambda: prets
                with (
                    self.subTest(nom=nom, entrees=entrees),
                    mock.patch.object(
                        runtime, "lister_images", return_value=[]
                    ) as images,
                    mock.patch.object(
                        runtime, "lister_projets", return_value={}
                    ) as dirs,
                    self.reponses(entrees=entrees) as sortie,
                ):
                    getattr(todo, f"_container_{nom}")()
                    self.assertEqual([], todo.execute.commandes)
                    self.assertFalse(images.called or dirs.called)
                    fautes = sortie.getvalue().count(faute)
                    self.assertEqual(len(entrees) - 1, fautes)


class TestService(Banc):
    """Piloter le service est justement ce qu'on fait quand il ne répond
    pas : la portée des unités décide de la commande."""

    def test_un_moteur_sans_privilege_a_des_unites_de_compte(self):
        todo = self.todo()
        for champ in ("docker_host", "rootless"):
            with self.subTest(champ=champ):
                self.assertTrue(
                    todo._container_par_compte(
                        "docker", {champ: "unix:///x" if champ else True}
                    )
                )

    def test_une_unite_de_compte_se_pilote_sans_sudo(self):
        """root ne voit pas les unités utilisateur : « sudo systemctl » s'y
        plaindrait d'une unité introuvable."""
        todo = self.todo()
        with self.reponses():
            todo._container_systemctl("start", "docker.service", True)
        self.assertEqual(
            ["systemctl --user start docker.service"], todo.execute.commandes
        )

    def test_une_unite_d_hote_exige_sudo(self):
        todo = self.todo()
        with self.reponses():
            todo._container_systemctl("start", "docker.service", False)
        self.assertEqual(
            ["sudo systemctl start docker.service"], todo.execute.commandes
        )

    def test_un_echec_enchaine_l_etat_et_le_journal(self):
        """systemd ne rend qu'un « control process exited with error code »
        et renvoie à deux commandes à taper : la cause n'est que dans le
        journal, et c'est tout ce qu'on cherchait."""
        todo = self.todo(code=1)
        with self.reponses():
            todo._container_systemctl("start", "docker.service", True)
        self.assertEqual(3, len(todo.execute.commandes))
        self.assertIn("status docker.service", todo.execute.commandes[1])
        self.assertIn("journalctl", todo.execute.commandes[2])

    def test_une_reussite_n_ajoute_rien(self):
        todo = self.todo(code=0)
        with self.reponses():
            todo._container_systemctl("start", "docker.service", True)
        self.assertEqual(1, len(todo.execute.commandes))

    def test_l_unite_diagnostiquee_est_celle_qui_a_echoue(self):
        """Activer porte sur la socket : c'est son journal qu'il faut, pas
        celui du démon."""
        todo = self.todo(code=1)
        with self.reponses():
            todo._container_systemctl("enable", "podman.socket", True)
        self.assertIn("status podman.socket", todo.execute.commandes[1])

    def test_le_journal_suit_l_etat(self):
        """« status » donne le code de sortie ; les lignes que le démon a
        écrites avant de mourir ne sont que dans le journal."""
        todo = self.todo()
        with self.reponses():
            todo._container_journal("docker.service", True)
        self.assertEqual(2, len(todo.execute.commandes))
        self.assertIn("systemctl --user status", todo.execute.commandes[0])
        self.assertIn("journalctl --user", todo.execute.commandes[1])

    def test_l_etat_lance_seul_choisit_son_moteur(self):
        """Lancé seul, depuis la TUI de télémétrie, l'état du service
        demande le moteur, puis lit l'état et le journal de son démon."""
        todo = self.todo()
        todo._container_choisir_moteur = lambda: {
            "moteur": "podman",
            "rootless": True,
            "docker_host": None,
        }
        with self.reponses():
            todo._container_etat_service()
        self.assertEqual(
            [
                "systemctl --user status podman.service --no-pager",
                "journalctl --user -u podman.service --no-pager -n 40",
            ],
            todo.execute.commandes,
        )

    def test_l_etat_du_menu_garde_le_moteur_choisi(self):
        """Dans le menu, [6] lit le moteur choisi à son ouverture, sans
        reposer la question."""
        todo = self.todo()
        choix = []

        def choisir():
            choix.append("docker")
            return {"moteur": "docker", "rootless": True, "docker_host": None}

        todo._container_choisir_moteur = choisir
        with self.reponses(prompts=["6", "0"]):
            todo._container_service()
        self.assertEqual(1, len(choix))
        self.assertIn("status docker.service", todo.execute.commandes[0])

    def test_un_geste_lance_seul_choisit_son_moteur(self):
        """Lancé seul, depuis la TUI de télémétrie, un geste demande le
        moteur ; activer porte sur sa socket et rappelle le linger d'une
        unité de compte."""
        todo = self.todo()
        todo._container_choisir_moteur = lambda: {
            "moteur": "podman",
            "rootless": True,
            "docker_host": None,
        }
        with self.reponses() as sortie:
            todo._container_geste(geste="enable")
        self.assertEqual(
            ["systemctl --user enable podman.socket"], todo.execute.commandes
        )
        self.assertIn("loginctl enable-linger", sortie.getvalue())

    def test_activer_porte_sur_la_socket_et_demarrer_sur_le_demon(self):
        """C'est la socket qui fait naître le démon à la première connexion :
        activer le démon seul ne le ferait pas revenir au démarrage."""
        todo = self.todo()
        todo._container_choisir_moteur = lambda: {
            "moteur": "docker",
            "rootless": True,
            "docker_host": None,
        }
        with self.reponses(prompts=["1", "4", "0"]):
            todo._container_service()
        self.assertIn("start docker.service", todo.execute.commandes[0])
        self.assertIn("enable docker.socket", todo.execute.commandes[1])


class TestCompose(Banc):
    """Chaque entrée de Compose lance la commande compose du moteur retenu
    à l'ouverture ; lancée seule, depuis la TUI de télémétrie, elle la
    demande au moteur retenu maintenant."""

    FICHE = {
        "moteur": "podman",
        "sans_sudo": True,
        "compose": ["podman-compose"],
    }

    def test_chaque_entree_lance_sa_sous_commande(self):
        todo = self.todo(self.FICHE)
        with self.reponses(prompts=["1", "2", "3", "4", "5", "0"]):
            self.assertIs(todo._container_compose(), False)
        self.assertEqual(
            [
                "podman-compose up -d",
                "podman-compose down",
                "podman-compose logs -f",
                "podman-compose ps",
            ],
            todo.execute.commandes,
        )

    def test_une_entree_lancee_seule_prend_le_moteur_retenu(self):
        todo = self.todo(dict(self.FICHE, compose=None))
        with self.reponses():
            todo._container_compose_geste(args=["ps"])
        self.assertEqual(["podman compose ps"], todo.execute.commandes)
        todo._container_fiche = lambda: None
        with self.reponses():
            todo._container_compose_geste(args=["ps"])
        self.assertEqual(1, len(todo.execute.commandes))


if __name__ == "__main__":
    unittest.main()
