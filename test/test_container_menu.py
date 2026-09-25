#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le menu Docker / Podman lance-t-il ce qu'il annonce ?

Trois gestes de ce menu sont irréversibles ou coûteux, et chacun se décide
sur un détail que l'affichage seul ne garantit pas :

- l'installation de Docker demande un MODE. Le groupe « docker » équivaut à
  root sur l'hôte, le mode sans privilège n'y touche pas : le drapeau doit
  suivre la réponse, et jamais un défaut ;
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
import sys
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.todo import container_menu, todo_i18n  # noqa: E402
from script.todo.todo import TODO  # noqa: E402

SOURCE = (RACINE / "script/todo/container_menu.py").read_text(encoding="utf-8")


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
    def todo(self, fiche=None, code=0):
        todo = TODO.__new__(TODO)
        todo.execute = ExecuteFactice(code)
        if fiche is not None:
            todo._container_fiche = lambda: fiche
        return todo

    @staticmethod
    @contextlib.contextmanager
    def reponses(entrees=(), prompts=()):
        """Joue des réponses écrites d'avance sur input() et click.prompt."""
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
        with self.reponses(entrees=["o"], prompts=["1"]):
            todo._container_install("docker")
        self.assertEqual(1, len(todo.execute.commandes))
        cmd = todo.execute.commandes[0]
        self.assertIn("--groupe", cmd)
        self.assertNotIn("--rootless", cmd)

    def test_le_mode_sans_privilege_peut_prendre_l_amont(self):
        todo = self.todo()
        with self.reponses(entrees=["o", "o"], prompts=["2"]):
            todo._container_install("docker")
        cmd = todo.execute.commandes[0]
        self.assertIn("--rootless", cmd)
        self.assertIn("--amont", cmd)

    def test_l_amont_se_refuse_sans_emporter_le_mode(self):
        todo = self.todo()
        with self.reponses(entrees=["n", "o"], prompts=["2"]):
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
        with self.reponses(entrees=["n"], prompts=["1"]):
            todo._container_install("docker")
        self.assertEqual([], todo.execute.commandes)


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

    def test_une_source_absente_ne_lance_pas_la_copie(self):
        todo = self.todo()
        with self.reponses(prompts=["/n/existe/pas"]) as sortie:
            todo._container_copier_fichier("")
        self.assertEqual([], todo.execute.commandes)
        self.assertIn("/n/existe/pas", sortie.getvalue())


class TestInventaire(Banc):
    def test_le_prefixe_sudo_suit_la_fiche(self):
        todo = self.todo({"moteur": "docker", "sans_sudo": False})
        with self.reponses():
            todo._container_inventaire(["images"])
        self.assertEqual("sudo docker images", todo.execute.commandes[0])

    def test_sans_moteur_rien_ne_part(self):
        todo = self.todo()
        todo._container_fiche = lambda: None
        with self.reponses():
            todo._container_inventaire(["images"])
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

    def _jouer(self, todo, selection, reponse):
        with mock.patch.object(
            container_menu.container_runtime,
            "lister_images",
            return_value=self.IMAGES,
        ):
            with self.reponses(entrees=[reponse], prompts=[selection]) as s:
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
        """« 1 x » ne retient pas « 1 » : la saisie entière tombe, et la
        question de confirmation n'est même pas posée."""
        todo = self._banc()
        rendu = self._jouer(todo, "1 x", "o")
        self.assertEqual([], todo.execute.commandes)
        self.assertIn(
            todo_i18n.t("Invalid selection: nothing removed."), rendu
        )
        self.assertNotIn(todo_i18n.t("Will remove:"), rendu)

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
            with self.reponses(entrees=[reponse], prompts=[selection]) as s:
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
        todo = self.todo(self.FICHE)
        self._jouer(todo, "2", "o")
        self.assertEqual([], todo.execute.commandes)


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
    def _banc(self, code=0):
        todo = self.todo(code=code)
        todo._container_exige_docker = lambda: ""
        todo._container_versions_odoo = lambda: ["18.0", "17.0", "12.0"]
        return todo

    def test_une_version_choisie_ne_lance_qu_elle(self):
        todo = self._banc()
        with self.reponses(entrees=["n"], prompts=["3"]):
            todo._container_build_odoo()
        self.assertEqual(
            ["./script/docker/docker_build.sh --odoo_12"],
            todo.execute.commandes,
        )

    def test_toutes_les_lance_dans_l_ordre_du_catalogue(self):
        todo = self._banc()
        with self.reponses(entrees=["o", "n"], prompts=["4"]):
            todo._container_build_odoo()
        self.assertEqual(
            [
                "./script/docker/docker_build.sh --odoo_18",
                "./script/docker/docker_build.sh --odoo_17",
                "./script/docker/docker_build.sh --odoo_12",
            ],
            todo.execute.commandes,
        )

    def test_toutes_demande_confirmation_avant_les_heures(self):
        """Une image de production pèse une dizaine de Go : un refus doit
        tout arrêter."""
        todo = self._banc()
        with self.reponses(entrees=["n"], prompts=["4"]):
            todo._container_build_odoo()
        self.assertEqual([], todo.execute.commandes)

    def test_un_echec_n_arrete_pas_le_balayage(self):
        """Une version qui casse n'apprend rien sur les suivantes, et les
        relancer une à une coûte des heures."""
        todo = self._banc(code=1)
        with self.reponses(entrees=["o", "n"], prompts=["4"]) as sortie:
            todo._container_build_odoo()
        self.assertEqual(3, len(todo.execute.commandes))
        rendu = sortie.getvalue()
        self.assertIn("18.0", rendu)
        self.assertIn("12.0", rendu)

    def test_le_sans_cache_ne_se_demande_qu_une_fois(self):
        todo = self._banc()
        with self.reponses(entrees=["o", "o"], prompts=["4"]):
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


class TestChoixNumerote(Banc):
    """Le numéro plutôt que le nom : taper « docker » en entier pour deux
    entrées coûte plus qu'il ne rapporte."""

    def test_le_rang_saisi_designe_l_option(self):
        todo = self.todo()
        with self.reponses(prompts=["2"]):
            rang = todo._container_choix_numerote("t", ["a", "b", "c"])
        self.assertEqual(1, rang)

    def test_zero_vaut_retour_et_ne_rend_pas_la_derniere(self):
        """options[-1] existe en Python : sans ce garde, « 0 » rendait la
        DERNIÈRE entrée — un choix que personne n'a fait, sur un écran qui
        efface parfois. Il vaut retour, et sort sans se plaindre."""
        todo = self.todo()
        with self.reponses(prompts=["0"]) as sortie:
            self.assertIsNone(
                todo._container_choix_numerote("t", ["a", "b", "c"])
            )
        self.assertNotIn("!", sortie.getvalue())

    def test_un_rang_hors_liste_est_refuse(self):
        todo = self.todo()
        with self.reponses(prompts=["4"]):
            self.assertIsNone(
                todo._container_choix_numerote("t", ["a", "b", "c"])
            )

    def test_une_saisie_qui_n_est_pas_un_nombre_est_refusee(self):
        """Une faute de frappe retombait en silence sur la première."""
        todo = self.todo()
        with self.reponses(prompts=["docker"]):
            self.assertIsNone(todo._container_choix_numerote("t", ["a", "b"]))

    def test_les_options_sont_affichees_numerotees(self):
        todo = self.todo()
        with self.reponses(prompts=["1"]) as sortie:
            todo._container_choix_numerote("Moteurs", ["docker", "podman"])
        rendu = sortie.getvalue()
        self.assertIn("[1] docker", rendu)
        self.assertIn("[2] podman", rendu)


class TestIconeDesMoteurs(Banc):
    def test_la_liste_porte_les_icones(self):
        todo = self.todo()
        todo._container_fiches = lambda: [
            {"moteur": "docker", "binaire": "/usr/bin/docker"},
            {"moteur": "podman", "binaire": "/usr/bin/podman"},
        ]
        with self.reponses(prompts=["2"]) as sortie:
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


class TestNumerotation(Banc):
    def test_chaque_entree_affichee_a_sa_branche(self):
        """Une entrée sans branche rend « Command not found » sur un numéro
        que le menu vient d'afficher."""
        corps = SOURCE[
            SOURCE.index("def prompt_execute_container") : SOURCE.index(
                "def _container_fiches"
            )
        ]
        entrees = len(re.findall(r'"prompt_description":', corps))
        branches = re.findall(r'status == "(\d+)"', corps)
        self.assertEqual(
            [str(n) for n in range(1, entrees + 1)],
            [b for b in branches if b != "0"],
        )


if __name__ == "__main__":
    unittest.main()
