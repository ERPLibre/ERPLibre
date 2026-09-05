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

    # Le formulaire, dans l'ordre de CHAMPS : nom, adresse, rebond, port,
    # clé, chemin, domaine, courriel. Une réponse vide garde la valeur.
    def formulaire(self, nom, adresse, **reste):
        return [
            nom,
            adresse,
            reste.get("jump", ""),
            reste.get("port", ""),
            reste.get("identity", ""),
            reste.get("path", ""),
            reste.get("domain", ""),
            reste.get("admin_email", ""),
        ]


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

    def jouer_verbe(self, methode="_deploy_ssh_check", **reponses):
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


if __name__ == "__main__":
    unittest.main()
