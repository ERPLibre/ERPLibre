#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'écran des cibles : ce qu'il retient, ce qu'il écrit, ce qu'il refuse.

Aucune machine, aucun réseau : les trois fichiers de configuration et les
préférences sont déplacés dans un temporaire, et les réponses au clavier sont
une liste. Ce qui est vérifié ici est l'ENCHAÎNEMENT — un écran qui écrirait
la bonne cible en oubliant de la retenir laisserait l'utilisateur croire
qu'il a choisi.
"""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

from script.remote import deploy_target as D  # noqa: E402
from script.todo import deploy_target_menu as M  # noqa: E402
from script.todo.todo import TODO  # noqa: E402


class EcranCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = os.path.join(self.tmp.name, "todo.json")
        with open(self.base, "w") as fh:
            json.dump({D.CONFIG_KEY: []}, fh)
        self.patches = [
            patch("script.config.config_file.CONFIG_FILE", self.base),
            patch(
                "script.config.config_file.CONFIG_OVERRIDE_FILE",
                os.path.join(self.tmp.name, "override.json"),
            ),
            patch(
                "script.config.config_file.CONFIG_OVERRIDE_PRIVATE_FILE",
                os.path.join(self.tmp.name, "private.json"),
            ),
        ]
        for item in self.patches:
            item.start()
        self.prefs = {}
        prefs = patch.multiple(
            "script.remote.deploy_target.todo_prefs",
            get=lambda cle, defaut=None: self.prefs.get(cle, defaut),
            set=lambda cle, valeur: self.prefs.__setitem__(cle, valeur),
        )
        prefs.start()
        self.patches.append(prefs)
        self.ecran = TODO.__new__(TODO)

    def tearDown(self):
        for item in self.patches:
            item.stop()
        self.tmp.cleanup()

    def jouer(self, *reponses):
        """Déroule l'écran sur ces réponses, et rend ce qu'il a affiché."""
        sortie = io.StringIO()
        with patch("builtins.input", side_effect=list(reponses)):
            with redirect_stdout(sortie):
                self.ecran._deploy_ssh_targets()
        return sortie.getvalue()

    def formulaire(self, nom, adresse, **reste):
        """Les réponses au formulaire, DÉRIVÉES de l'ordre de `CHAMPS`.

        Énumérées à la main, elles décalaient d'un cran le jour où un champ
        s'ajoutait ailleurs qu'à la fin — et le test continuait de passer, en
        écrivant chaque valeur dans le champ du voisin.

        Une réponse vide garde la valeur en place, y compris pour le genre,
        qui se choisit par numéro et non en toutes lettres.
        """
        reponses = {"name": nom, "target": adresse, **reste}
        return [reponses.get(cle, "") for cle, _ in M.CHAMPS]

    @staticmethod
    def rang_du_genre(genre):
        """Le numéro qui désigne ce genre à l'écran, DÉRIVÉ de `KINDS`.

        Écrit « 2 », il désignerait l'autre genre le jour où l'ordre change,
        et le test l'affirmerait sans broncher.
        """
        return str(list(D.KINDS).index(genre) + 1)


class TestLEcranVide(EcranCase):
    def test_it_says_there_is_none_and_offers_to_add(self):
        affiche = self.jouer("0")
        self.assertIn("[a]", affiche)

    def test_adding_the_first_one_selects_it(self):
        """Sans cela, la cible existe et l'écran continue de dire
        « aucune » : on croirait avoir choisi."""
        self.jouer(
            "a", *self.formulaire("essai", "compte@machine.example"), "0"
        )
        self.assertEqual(["essai"], D.names())
        self.assertEqual("essai", D.selected()["name"])


class TestChoisirUneCible(EcranCase):
    def setUp(self):
        super().setUp()
        D.save({"name": "un", "target": "compte@un.example"})
        D.save({"name": "deux", "target": "compte@deux.example"})

    def test_a_number_selects_the_target_it_designates(self):
        self.jouer("2", "0")
        self.assertEqual("deux", D.selected()["name"])

    def test_the_selected_one_is_marked_in_the_list(self):
        D.select("deux")
        affiche = self.jouer("0")
        ligne = [l for l in affiche.splitlines() if "deux" in l][0]
        self.assertIn("←", ligne)
        autre = [l for l in affiche.splitlines() if "un —" in l][0]
        self.assertNotIn("←", autre)

    def test_a_number_out_of_range_changes_nothing(self):
        D.select("un")
        self.jouer("9", "0")
        self.assertEqual("un", D.selected()["name"])

    def test_forgetting_clears_the_selection(self):
        D.select("un")
        self.jouer("o", "0")
        self.assertIsNone(D.selected())


class TestModifierUneCible(EcranCase):
    def setUp(self):
        super().setUp()
        D.save({"name": "un", "target": "compte@un.example", "port": "2222"})

    def test_an_empty_answer_keeps_the_value_in_place(self):
        """Corriger un champ ne doit pas obliger à ressaisir les sept
        autres."""
        self.jouer("m", "1", *self.formulaire("", ""), "0")
        cible = D.load("un")
        self.assertEqual("compte@un.example", cible["target"])
        self.assertEqual("2222", cible["port"])

    def test_editing_one_field_leaves_the_others_alone(self):
        self.jouer("m", "1", *self.formulaire("", "compte@autre.example"), "0")
        self.assertEqual("compte@autre.example", D.load("un")["target"])
        self.assertEqual("2222", D.load("un")["port"])

    def test_renaming_removes_the_old_entry(self):
        """Sans le retrait, la même machine serait deux fois dans
        l'inventaire, sous deux noms."""
        D.select("un")
        self.jouer("m", "1", *self.formulaire("deux", ""), "0")
        self.assertEqual(["deux"], D.names())
        self.assertEqual("deux", D.selected()["name"])

    def test_a_refused_value_is_said_and_writes_nothing(self):
        affiche = self.jouer(
            "m", "1", *self.formulaire("", "adresse avec espaces"), "0"
        )
        self.assertIn("✗", affiche)
        self.assertEqual("compte@un.example", D.load("un")["target"])


class TestSupprimerUneCible(EcranCase):
    def setUp(self):
        super().setUp()
        D.save({"name": "un", "target": "compte@un.example"})

    def test_it_asks_before_deleting(self):
        self.jouer("s", "1", "n", "0")
        self.assertEqual(["un"], D.names())

    def test_a_yes_deletes_it(self):
        self.jouer("s", "1", "y", "0")
        self.assertEqual([], D.names())

    def test_a_deleted_selection_is_simply_asked_for_again(self):
        D.select("un")
        self.jouer("s", "1", "y", "0")
        self.assertIsNone(D.selected())

    def test_a_shared_target_says_why_it_stays(self):
        with open(self.base, "w") as fh:
            json.dump(
                {
                    D.CONFIG_KEY: [
                        {"name": "equipe", "target": "compte@e.example"}
                    ]
                },
                fh,
            )
        # La fusion pose le fichier partagé AVANT le privé : « equipe »
        # est donc la première, et « un » la seconde.
        affiche = self.jouer("s", "1", "y", "0")
        self.assertIn("✗", affiche)
        self.assertIn("equipe", D.names())


class TestLEnteteDuMenu(EcranCase):
    """Cinq entrées installent ou redémarrent : lire à qui l'on parle
    AVANT de choisir est ce qui évite de le découvrir après."""

    def test_it_names_the_selected_target(self):
        D.save({"name": "un", "target": "compte@un.example"})
        D.select("un")
        sortie = io.StringIO()
        with redirect_stdout(sortie):
            self.ecran._deploy_ssh_show_target()
        self.assertIn("un", sortie.getvalue())
        self.assertIn("compte@un.example", sortie.getvalue())

    def test_it_says_so_when_there_is_none(self):
        sortie = io.StringIO()
        with redirect_stdout(sortie):
            self.ecran._deploy_ssh_show_target()
        self.assertNotIn("@", sortie.getvalue())


class Espion:
    """Ce que le menu aurait lancé, sans rien lancer."""

    def __init__(self):
        self.jouees = []

    def exec_command_live(self, commande, **_kwargs):
        self.jouees.append(commande)


class TestLesVerbesNeRedemandentPlus(EcranCase):
    """Onze commandes reposaient cinq questions chacune, sans rien retenir.

    C'est le point d'arrivée : la fiche remplace la saisie, et une épreuve
    fait LEVER toute invite pour prouver qu'il n'en reste aucune.
    """

    def setUp(self):
        super().setUp()
        self.ecran.execute = Espion()
        D.save(
            {
                "name": "un",
                "target": "compte@un.example",
                "port": "2222",
                "path": "/opt/erplibre",
            }
        )
        D.select("un")

    # « check » ne passe plus par make : on prend un verbe qui y passe.
    def jouer_verbe(self, methode="_deploy_ssh_run", **reponses):
        sortie = io.StringIO()
        with redirect_stdout(sortie):
            getattr(self.ecran, methode)()
        return sortie.getvalue()

    def test_a_selected_target_is_asked_nothing_at_all(self):
        with patch("builtins.input", side_effect=AssertionError):
            with patch(
                "script.todo.todo.click.prompt", side_effect=AssertionError
            ):
                self.jouer_verbe()
        ligne = self.ecran.execute.jouees[0]
        self.assertIn("SSH_HOST=un.example", ligne)
        self.assertIn("SSH_USER=compte", ligne)
        self.assertIn("SSH_PORT=2222", ligne)
        self.assertIn("SSH_PATH=/opt/erplibre", ligne)

    def test_the_account_never_reaches_the_host_variable(self):
        """Le Makefile recompose « compte@hôte » : sans la coupe, il
        composerait « erplibre@compte@un.example »."""
        with patch("builtins.input", side_effect=AssertionError):
            self.jouer_verbe()
        ligne = self.ecran.execute.jouees[0]
        self.assertNotIn("SSH_HOST=compte@", ligne)

    def test_an_alias_gets_its_account_from_the_ssh_config(self):
        """make ne lit pas ce fichier ; sans cette relecture, un alias qui
        déclare « User root » se ferait joindre sous le compte par défaut."""
        D.save({"name": "alias", "target": "monalias"})
        D.select("alias")
        with patch.object(
            TODO, "_ssh_config_user", staticmethod(lambda hote: "root")
        ):
            with patch("builtins.input", side_effect=AssertionError):
                self.jouer_verbe()
        self.assertIn("SSH_USER=root", self.ecran.execute.jouees[0])

    def test_an_alias_without_a_declared_account_omits_the_variable(self):
        """Omise, le défaut du Makefile s'applique ; écrite vide, elle
        composerait « @monalias »."""
        D.save({"name": "alias", "target": "monalias"})
        D.select("alias")
        with patch.object(
            TODO, "_ssh_config_user", staticmethod(lambda hote: "")
        ):
            with patch("builtins.input", side_effect=AssertionError):
                self.jouer_verbe()
        self.assertNotIn("SSH_USER=", self.ecran.execute.jouees[0])

    def test_with_no_target_the_chooser_opens(self):
        D.select("")
        with patch("builtins.input", side_effect=["1", "0"]):
            self.jouer_verbe()
        self.assertEqual(1, len(self.ecran.execute.jouees))
        self.assertEqual("un", D.selected()["name"])

    def test_giving_up_the_choice_runs_nothing(self):
        """La garde des onze appelants ne bouge pas : None veut toujours
        dire « on renonce »."""
        D.select("")
        with patch("builtins.input", side_effect=["0"]):
            self.jouer_verbe()
        self.assertEqual([], self.ecran.execute.jouees)


class TestLeDomaineAppartientALaCible(EcranCase):
    """Un renouvellement de certificat n'est pas une nouvelle saisie."""

    def setUp(self):
        super().setUp()
        self.ecran.execute = Espion()

    def nginx(self, invites=(), clavier=()):
        """`invites` répond aux questions, `clavier` au oui/non final.

        Deux listes séparées : une seule, partagée par les deux patchs,
        servirait la même réponse aux deux et masquerait l'enchaînement.
        """
        sortie = io.StringIO()
        with patch("builtins.input", side_effect=list(clavier)):
            with patch(
                "script.todo.todo.click.prompt", side_effect=list(invites)
            ):
                with redirect_stdout(sortie):
                    self.ecran._deploy_ssh_install_nginx()
        return sortie.getvalue()

    def test_a_target_carrying_a_domain_is_asked_nothing(self):
        D.save(
            {
                "name": "un",
                "target": "compte@un.example",
                "domain": "site.example",
                "admin_email": "admin@site.example",
            }
        )
        D.select("un")
        self.nginx()
        ligne = self.ecran.execute.jouees[0]
        self.assertIn("SSH_DOMAIN=site.example", ligne)
        self.assertIn("SSH_ADMIN_EMAIL=admin@site.example", ligne)

    def test_what_is_typed_can_be_written_onto_the_target(self):
        D.save({"name": "un", "target": "compte@un.example"})
        D.select("un")
        self.nginx(("site.example", "admin@site.example"), ("y",))
        self.assertEqual("site.example", D.load("un")["domain"])
        self.assertEqual("admin@site.example", D.load("un")["admin_email"])

    def test_a_no_leaves_the_target_alone(self):
        """Un certificat posé une fois pour essai n'a pas à s'inscrire."""
        D.save({"name": "un", "target": "compte@un.example"})
        D.select("un")
        self.nginx(("site.example", "admin@site.example"), ("n",))
        self.assertEqual("", D.load("un")["domain"])
        self.assertEqual(1, len(self.ecran.execute.jouees))

    def test_a_malformed_domain_is_refused_before_the_connection(self):
        """certbot le dirait après un aller-retour ssh, et le dirait mal."""
        D.save({"name": "un", "target": "compte@un.example"})
        D.select("un")
        dit = self.nginx(("compte@site.example", "admin@site.example"))
        self.assertIn("✗", dit)
        self.assertEqual([], self.ecran.execute.jouees)


class TestLaSondeDeLaCible(EcranCase):
    """Vérifier la connexion, c'est répondre à trois questions.

    ssh aboutit-il, le produit est-il là et à quelle version, le compte
    peut-il s'élever. Ces trois réponses décident de ce que les dix autres
    verbes peuvent faire ; « echo » n'en donnait aucune.
    """

    def setUp(self):
        super().setUp()
        D.save(
            {"name": "un", "target": "compte@un.example", "path": "/opt/el"}
        )
        D.select("un")

    def sonder(self, **reponses):
        """Joue la vérification avec un exécuteur ssh de banc."""
        journal = []

        def run(host, remote, timeout=0):
            journal.append(remote)
            for motif, reponse in reponses.items():
                if motif in remote:
                    return reponse
            return 127, "command not found"

        sortie = io.StringIO()
        with patch("script.remote.host_probe.appliance_ssh.run", run):
            with redirect_stdout(sortie):
                self.ecran._deploy_ssh_check()
        return sortie.getvalue(), journal

    def test_a_healthy_host_is_said_layer_by_layer(self):
        affiche, _ = self.sonder(cat=(0, "1.8.0\n"), id=(0, "0\n"))
        self.assertIn("transport", affiche)
        self.assertIn("ERPLibre 1.8.0", affiche)

    def test_what_was_found_is_written_onto_the_target(self):
        """Rouvrir l'écran sans re-sonder doit pouvoir dire ce qu'on savait
        et depuis quand."""
        self.sonder(cat=(0, "1.8.0\n"), id=(0, "0\n"))
        cible = D.load("un")
        self.assertEqual("ok", cible["verdict"])
        self.assertEqual("1.8.0", cible["version"])
        self.assertTrue(cible["last_probe"].endswith("Z"), cible["last_probe"])

    def test_the_elevation_found_is_kept_for_the_other_verbs(self):
        self.sonder(cat=(0, "1.8.0\n"), id=(0, "1000\n"), sudo=(0, ""))
        self.assertEqual("sudo ", D.load("un")["sudo"])

    def test_a_host_without_sudo_is_not_closed(self):
        """Neuf verbes sur onze s'en passent : les fermer tous pour les
        deux autres serait pire que de le dire."""
        affiche, _ = self.sonder(
            cat=(0, "1.8.0\n"),
            id=(0, "1000\n"),
            sudo=(1, "sudo: a password is required"),
        )
        self.assertIn("ERPLibre 1.8.0", affiche)
        self.assertEqual("no-privilege", D.load("un")["verdict"])

    def test_reachable_without_the_product_points_at_the_product(self):
        affiche, _ = self.sonder(cat=(0, ""), true=(0, ""))
        self.assertIn("transport", affiche)
        self.assertEqual("product-absent", D.load("un")["verdict"])

    def test_an_unreachable_host_points_at_the_network(self):
        affiche, _ = self.sonder(
            cat=(255, "ssh: connect to host: timeout"),
            true=(255, "ssh: connect to host: timeout"),
        )
        self.assertIn("timeout", affiche)
        self.assertEqual("unreachable", D.load("un")["verdict"])

    def test_the_probe_reads_the_targets_own_path(self):
        """Sonder le chemin par défaut dirait « absent » d'un ERPLibre
        parfaitement installé ailleurs."""
        _affiche, journal = self.sonder(cat=(0, "1.8.0\n"), id=(0, "0\n"))
        self.assertIn("/opt/el/.erplibre-semver-version", journal[0])

    def test_the_remote_error_names_the_path_that_was_looked_for(self):
        """C'est la réponse utile quand le produit n'est pas là : elle dit
        OÙ l'on a cherché, ce qu'un message générique ne dit pas."""
        affiche, _ = self.sonder(
            cat=(
                1,
                "cat: /opt/el/.erplibre-semver-version: No such file"
                " or directory",
            ),
            true=(0, ""),
        )
        self.assertIn("/opt/el/.erplibre-semver-version", affiche)
        self.assertEqual("product-absent", D.load("un")["verdict"])

    def test_a_shell_error_is_never_taken_for_a_version(self):
        """La version se reconnaît à sa FORME, pas au fait qu'une ligne
        soit là — c'est ce qui permet de garder l'erreur."""
        self.sonder(
            cat=(1, "cat: 1.8.0: No such file or directory"), true=(0, "")
        )
        self.assertEqual("product-absent", D.load("un")["verdict"])
        self.assertEqual("", D.load("un")["version"])

    def test_something_that_merely_begins_like_a_version_is_refused(self):
        """La ligne doit être une version ENTIÈRE. Un fichier quelconque
        peut commencer par des chiffres et des points sans en être une, et
        l'accepter ferait annoncer le produit présent là où il n'est pas."""
        for ligne in ("1.2.3.tar.gz", "1.8.0-dev build 42", "1.8.0 1.9.0"):
            with self.subTest(ligne=ligne):
                D.save(dict(D.load("un"), verdict="", version=""))
                self.sonder(cat=(0, ligne + "\n"), true=(0, ""))
                self.assertEqual("product-absent", D.load("un")["verdict"])

    def test_a_stray_file_is_not_taken_for_a_version(self):
        """« cat » sur un dossier quelconque peut rendre n'importe quoi."""
        self.sonder(cat=(0, "ceci n'est pas une version\n"), true=(0, ""))
        self.assertEqual("product-absent", D.load("un")["verdict"])


class TestLeFormulaireNOubliePersonne(unittest.TestCase):
    """Le formulaire réclame CHAQUE champ que le site doit déclarer.

    DÉRIVÉ, et non compté. Le défaut que ce garde attrape est celui qui l'a
    fait naître : `kind` manquait à `CHAMPS`, donc toute cible créée à
    l'écran était une cible de déploiement, et le seul écran que le code
    nomme pour en créer une de sauvegarde ne savait pas en créer.
    """

    def test_every_declarable_field_is_asked(self):
        demandes = {cle for cle, _ in M.CHAMPS}
        self.assertEqual(
            set(D.DEFAULTS) - set(M.CHAMPS_SONDE),
            demandes,
            "un champ de DEFAULTS n'est ni demandé au formulaire, ni nommé"
            " dans CHAMPS_SONDE comme déposé par la sonde",
        )

    def test_the_probe_fields_are_really_the_probe_s(self):
        """`CHAMPS_SONDE` est l'exemption du garde précédent.

        Sans cette épreuve, y glisser un champ de SAISIE ferait taire l'autre
        test au lieu de le faire rougir. L'autorité est `record_probe` : les
        clés qu'il écrit sont exactement celles que personne ne saisit.
        """
        import ast
        import inspect

        arbre = ast.parse(inspect.getsource(D.record_probe))
        ecrites = {
            mot.arg
            for noeud in ast.walk(arbre)
            if isinstance(noeud, ast.Call)
            and isinstance(noeud.func, ast.Name)
            and noeud.func.id == "dict"
            for mot in noeud.keywords
            if mot.arg
        }
        self.assertEqual(set(M.CHAMPS_SONDE), ecrites)

    def test_every_kind_has_a_sentence(self):
        """Un genre sans phrase se montrerait comme un nom technique nu.

        `GENRES` est interrogée sans défaut : l'oubli lèverait à l'écran. Ce
        garde le dit avant.
        """
        self.assertEqual(set(D.KINDS), set(M.GENRES))


class TestDeclarerUneCibleDeSauvegarde(EcranCase):
    """Le genre se choisit, s'écrit, et ne se prend jamais pour l'autre."""

    def test_the_form_can_declare_a_backup_target(self):
        """Sans cela le segment « sauvegarde hors instance » reste à régler
        et aucun geste de l'écran ne peut le régler."""
        self.jouer(
            "a",
            *self.formulaire(
                "archives",
                "compte@depot.example",
                kind=self.rang_du_genre(D.KIND_BACKUP),
            ),
            "0",
        )
        self.assertEqual(D.KIND_BACKUP, D.load("archives")["kind"])

    def test_an_empty_answer_keeps_the_kind_in_place(self):
        D.save(
            {
                "name": "archives",
                "target": "a@b.example",
                "kind": D.KIND_BACKUP,
            }
        )
        self.jouer("m", "1", *self.formulaire("", ""), "0")
        self.assertEqual(D.KIND_BACKUP, D.load("archives")["kind"])

    def test_an_answer_that_designates_nothing_is_said_and_asked_again(self):
        """Retomber sur le défaut poserait une cible de déploiement là où on
        voulait une cible de sauvegarde, et les deux se ressemblent trop dans
        la liste pour qu'on le remarque."""
        affiche = self.jouer(
            "a",
            "essai",
            "9",
            self.rang_du_genre(D.KIND_BACKUP),
            "compte@depot.example",
            "",
            "",
            "",
            "",
            "",
            "",
            "0",
        )
        self.assertIn("✗", affiche)
        self.assertEqual(D.KIND_BACKUP, D.load("essai")["kind"])

    def test_a_backup_target_never_becomes_the_deployment_one(self):
        """Onze commandes agissent sur la cible retenue, dont cinq
        installent : y retenir un dépôt d'archives y installerait ERPLibre."""
        self.jouer(
            "a",
            *self.formulaire(
                "archives",
                "compte@depot.example",
                kind=self.rang_du_genre(D.KIND_BACKUP),
            ),
            "0",
        )
        self.assertIsNone(D.selected())

    def test_choosing_it_says_why_rather_than_doing_nothing(self):
        D.save(
            {
                "name": "archives",
                "target": "a@b.example",
                "kind": D.KIND_BACKUP,
            }
        )
        affiche = self.jouer("1", "0")
        self.assertIn("✗", affiche)
        self.assertIsNone(D.selected())

    def test_changing_the_kind_of_the_selected_one_drops_it(self):
        """La sélection se relit ; elle ne se fige pas au moment du choix."""
        D.save({"name": "un", "target": "compte@un.example"})
        D.select("un")
        self.assertIsNotNone(D.selected())
        D.save(
            {
                "name": "un",
                "target": "compte@un.example",
                "kind": D.KIND_BACKUP,
            }
        )
        self.assertIsNone(D.selected())


if __name__ == "__main__":
    unittest.main()
