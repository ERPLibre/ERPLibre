#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Cibles de déploiement : validation, aller-retour disque, et make.

Ni réseau, ni machine distante. Les trois fichiers de configuration fusionnés
sont déplacés dans un répertoire temporaire : un test qui écrirait dans
`private/todo/todo_override_private.json` détruirait l'inventaire de la
personne qui le lance.

L'épreuve qui compte le plus est celle du compte : le Makefile recompose
« $(SSH_USER)@$(SSH_HOST) », et lui passer une adresse qui porte déjà son
compte produit une chaîne à deux « @ » que ssh refuse.
"""

import json
import os
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.remote import deploy_target as D
from script.remote.deploy_target import ValidationError

VALIDE = {
    "name": "essai",
    "target": "compte@machine.example",
    "path": "~/erplibre_deploy_2",
}


class TestLaValidation(unittest.TestCase):
    """Chaque valeur finit dans une ligne de commande."""

    def test_a_plain_target_passes(self):
        """Contrôle positif : refuser tout passerait les épreuves d'à côté."""
        clean = D.validate(VALIDE)
        self.assertEqual("essai", clean["name"])
        self.assertEqual("compte@machine.example", clean["target"])

    def test_a_name_outside_the_alphabet_is_refused(self):
        for nom in ("Essai", "un essai", "essai;rm", "", "a" * 40):
            with self.subTest(nom=nom):
                with self.assertRaises(ValidationError):
                    D.validate(dict(VALIDE, name=nom))

    def test_an_address_with_a_space_is_refused(self):
        for adresse in ("machine autre", "machine; rm -rf /", ""):
            with self.subTest(adresse=adresse):
                with self.assertRaises(ValidationError):
                    D.validate(dict(VALIDE, target=adresse))

    def test_a_domain_carrying_a_user_is_refused(self):
        """Il finirait dans la requête de certificat et dans nginx."""
        with self.assertRaises(ValidationError):
            D.validate(dict(VALIDE, domain="compte@site.example"))
        clean = D.validate(dict(VALIDE, domain="site.example"))
        self.assertEqual("site.example", clean["domain"])

    def test_an_unknown_kind_names_the_known_ones(self):
        with self.assertRaises(ValidationError) as pris:
            D.validate(dict(VALIDE, kind="lima"))
        self.assertIn(D.KIND_SSH, str(pris.exception))

    def test_an_email_that_would_break_certbot_is_refused(self):
        for courriel in ("pas un courriel", "a@b c", "a b@c.example"):
            with self.subTest(courriel=courriel):
                with self.assertRaises(ValidationError):
                    D.validate(dict(VALIDE, admin_email=courriel))
        clean = D.validate(dict(VALIDE, admin_email="admin@site.example"))
        self.assertEqual("admin@site.example", clean["admin_email"])

    def test_the_port_stays_a_string_and_empty_stays_empty(self):
        """« 22 » écrit d'office imposerait le port à un alias qui en
        déclare un autre."""
        self.assertEqual("", D.validate(VALIDE)["port"])
        self.assertEqual("2222", D.validate(dict(VALIDE, port="2222"))["port"])
        for port in ("0", "65536", "vingt-deux"):
            with self.subTest(port=port):
                with self.assertRaises(ValidationError):
                    D.validate(dict(VALIDE, port=port))

    def test_the_default_remote_path_matches_what_make_already_uses(self):
        """Une cible qui omet le chemin se comporte comme la saisie
        qu'elle remplace, sinon elle déploie ailleurs sans le dire."""
        self.assertEqual(D.DEFAULT_PATH, D.validate(VALIDE)["path"])

    def test_a_verdict_outside_the_vocabulary_is_refused(self):
        """Un fichier modifié à la main afficherait un verdict inventé."""
        with self.assertRaises(ValidationError):
            D.validate(dict(VALIDE, verdict="peut-etre"))
        clean = D.validate(dict(VALIDE, verdict="ok"))
        self.assertEqual("ok", clean["verdict"])

    def test_an_unprobed_target_is_valid(self):
        """Jamais sondée n'est pas en panne, et l'écran doit distinguer."""
        clean = D.validate(VALIDE)
        self.assertEqual("", clean["verdict"])
        self.assertEqual("", clean["last_probe"])

    def test_a_probe_date_out_of_shape_is_refused(self):
        with self.assertRaises(ValidationError):
            D.validate(dict(VALIDE, last_probe="hier"))
        clean = D.validate(dict(VALIDE, last_probe="2026-01-31T14:05:00Z"))
        self.assertEqual("2026-01-31T14:05:00Z", clean["last_probe"])


class TestLeSecondGenreDeCible(unittest.TestCase):
    """Le champ « genre » existe pour ce cas-ci.

    Son commentaire le dit : « Un seul genre aujourd'hui, et le champ
    existe quand même : une cible sans genre ne se distinguerait pas d'une
    autre le jour où un second transport arrive, et il faudrait alors
    deviner d'après les champs présents. » Une cible de SAUVEGARDE est ce
    second genre : même transport ssh, même fiche, un usage distinct.
    """

    def test_the_vocabulary_carries_both_kinds(self):
        self.assertIn(D.KIND_SSH, D.KINDS)
        self.assertIn(D.KIND_BACKUP, D.KINDS)
        self.assertEqual(2, len(D.KINDS))

    def test_the_two_kinds_are_not_the_same_word(self):
        """Les confondre ferait déployer sur la cible des sauvegardes."""
        self.assertNotEqual(D.KIND_SSH, D.KIND_BACKUP)

    def test_a_backup_target_validates_like_its_sibling(self):
        cible = D.validate(
            {
                "name": "nas",
                "kind": D.KIND_BACKUP,
                "target": "sauvegarde@203.0.113.9",
                "path": "/tank/erplibre",
            }
        )
        self.assertEqual(D.KIND_BACKUP, cible["kind"])
        self.assertEqual("/tank/erplibre", cible["path"])

    def test_an_unknown_kind_is_still_refused_by_name(self):
        with self.assertRaises(ValidationError) as leve:
            D.validate(
                {
                    "name": "nas",
                    "kind": "inventé",
                    "target": "a@b",
                    "path": "/x",
                }
            )
        self.assertIn("inventé", str(leve.exception))


class TestLaFicheDHote(unittest.TestCase):
    """Ce qu'on écrit et ce qu'on donne au transport ne se confondent pas."""

    def test_it_carries_only_what_the_transport_reads(self):
        fiche = D.fiche(
            dict(
                VALIDE,
                domain="site.example",
                last_probe="2026-01-31T14:05:00Z",
            )
        )
        self.assertEqual("compte@machine.example", fiche["target"])
        self.assertNotIn("domain", fiche)
        self.assertNotIn("last_probe", fiche)
        self.assertNotIn("path", fiche)

    def test_the_transport_accepts_it_as_is(self):
        """Le contrôle qui compte : la fiche doit produire une ligne ssh."""
        from script.remote import appliance_ssh

        argv = appliance_ssh.ssh_argv(
            D.fiche(dict(VALIDE, port="2222", identity="~/.ssh/k")), "vrai"
        )
        self.assertEqual("2222", argv[argv.index("-p") + 1])
        self.assertEqual("~/.ssh/k", argv[argv.index("-i") + 1])
        self.assertEqual(["compte@machine.example", "vrai"], argv[-2:])


class TestLesVariablesDeMake(unittest.TestCase):
    """Le Makefile recompose « $(SSH_USER)@$(SSH_HOST) »."""

    def test_the_account_is_split_out_of_the_address(self):
        """Sans la coupe, make compose « erplibre@compte@machine »."""
        variables = D.make_vars(VALIDE)
        self.assertEqual("machine.example", variables["SSH_HOST"])
        self.assertEqual("compte", variables["SSH_USER"])
        self.assertNotIn("@", variables["SSH_HOST"])

    def test_an_alias_without_an_account_omits_the_variable(self):
        """Omise, le défaut du Makefile s'applique — le comportement
        d'avant. Écrite vide, elle composerait « @machine »."""
        variables = D.make_vars(dict(VALIDE, target="machine"))
        self.assertEqual("machine", variables["SSH_HOST"])
        self.assertNotIn("SSH_USER", variables)

    def test_an_alias_is_resolved_when_a_resolver_is_given(self):
        """~/.ssh/config porte le compte ; le Makefile ne le lit pas."""
        variables = D.make_vars(
            dict(VALIDE, target="alias"),
            resolve=lambda h: {"user": "compte", "port": "2222"},
        )
        self.assertEqual("compte", variables["SSH_USER"])
        self.assertEqual("2222", variables["SSH_PORT"])

    def test_what_the_target_states_wins_over_what_is_resolved(self):
        """Contrôle positif : le résolveur COMPLÈTE, il n'écrase pas."""
        variables = D.make_vars(
            dict(VALIDE, target="alias", port="9999"),
            resolve=lambda h: {"user": "compte", "port": "2222"},
        )
        self.assertEqual("9999", variables["SSH_PORT"])

    def test_an_address_that_carries_an_account_is_never_resolved(self):
        """Interroger ssh pour une réponse déjà connue coûte un appel."""
        appels = []

        def resolveur(hote):
            appels.append(hote)
            return {"user": "autre"}

        variables = D.make_vars(VALIDE, resolve=resolveur)
        self.assertEqual([], appels)
        self.assertEqual("compte", variables["SSH_USER"])

    def test_empty_variables_are_omitted_and_not_written_empty(self):
        variables = D.make_vars(dict(VALIDE, target="machine"))
        self.assertNotIn("SSH_JUMP", variables)
        self.assertNotIn("SSH_KEY", variables)
        self.assertEqual(D.DEFAULT_PATH, variables["SSH_PATH"])

    def test_the_jump_travels_to_make(self):
        variables = D.make_vars(dict(VALIDE, jump="rebond.example"))
        self.assertEqual("rebond.example", variables["SSH_JUMP"])


class CibleSurDisque(unittest.TestCase):
    """Fusion et écriture, avec les trois fichiers dans un temporaire."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = os.path.join(self.tmp.name, "todo.json")
        with open(base, "w") as fh:
            json.dump({D.CONFIG_KEY: []}, fh)
        self.base = base
        self.private = os.path.join(self.tmp.name, "private.json")
        self.patches = [
            patch("script.config.config_file.CONFIG_FILE", base),
            patch(
                "script.config.config_file.CONFIG_OVERRIDE_FILE",
                os.path.join(self.tmp.name, "override.json"),
            ),
            patch(
                "script.config.config_file.CONFIG_OVERRIDE_PRIVATE_FILE",
                self.private,
            ),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in self.patches:
            item.stop()
        self.tmp.cleanup()


class TestLAllerRetourSurDisque(CibleSurDisque):
    def test_save_then_load(self):
        D.save(VALIDE)
        lue = D.load("essai")
        self.assertEqual("compte@machine.example", lue["target"])
        self.assertEqual(D.DEFAULT_PATH, lue["path"])

    def test_the_private_file_is_owner_only(self):
        """Il nomme les machines d'un site : c'est une carte, et une carte
        se garde."""
        D.save(VALIDE)
        mode = stat.S_IMODE(os.stat(self.private).st_mode)
        self.assertEqual(0o600, mode, oct(mode))

    def test_saving_twice_replaces_and_does_not_pile_up(self):
        D.save(VALIDE)
        D.save(dict(VALIDE, target="autre.example"))
        self.assertEqual(["essai"], D.names())
        self.assertEqual("autre.example", D.load("essai")["target"])

    def test_a_refused_target_leaves_the_inventory_untouched(self):
        """Valider AVANT d'écrire : un refus ne doit rien coûter.

        Le nom diffère volontairement de celui déjà écrit : réutiliser le
        même laisserait une entrée fautive passer inaperçue derrière la
        bonne, que la lecture trouve la première."""
        D.save(VALIDE)
        with self.assertRaises(ValidationError):
            D.save(dict(VALIDE, name="autre", target="machine autre"))
        self.assertEqual(["essai"], D.names())
        self.assertEqual("compte@machine.example", D.load("essai")["target"])

    def test_delete_says_no_when_it_was_not_there(self):
        self.assertFalse(D.delete("jamais-vue"))
        D.save(VALIDE)
        self.assertTrue(D.delete("essai"))
        self.assertEqual([], D.names())

    def test_a_shared_target_is_read_but_not_deletable(self):
        """Elle vient du fichier d'équipe ; faire semblant de l'effacer la
        ferait revenir à la lecture suivante sans explication."""
        with open(self.base, "w") as fh:
            json.dump(
                {D.CONFIG_KEY: [{"name": "equipe", "target": "m.example"}]}, fh
            )
        self.assertIn("equipe", D.names())
        self.assertFalse(D.delete("equipe"))
        self.assertIn("equipe", D.names())

    def test_writing_does_not_recopy_the_shared_targets(self):
        """La fusion ÉTEND les listes : recopier ferait un doublon."""
        with open(self.base, "w") as fh:
            json.dump(
                {D.CONFIG_KEY: [{"name": "equipe", "target": "m.example"}]}, fh
            )
        D.save(VALIDE)
        self.assertEqual(["equipe", "essai"], sorted(D.names()))
        self.assertEqual(["essai"], [t["name"] for t in D.private_targets()])

    def test_correcting_a_shared_target_replaces_it(self):
        """Sans la déduplication, la fusion AJOUTE une seconde entrée du même
        nom, la lecture rend l'ancienne, et la correction s'annonce faite
        sans l'être."""
        with open(self.base, "w") as fh:
            json.dump(
                {D.CONFIG_KEY: [{"name": "equipe", "target": "m.example"}]}, fh
            )
        D.save({"name": "equipe", "target": "corrigee.example"})
        self.assertEqual(["equipe"], D.names())
        self.assertEqual("corrigee.example", D.load("equipe")["target"])

    def test_a_correction_keeps_the_rank_of_what_it_replaces(self):
        """Le rang est ce qu'on tape : le voir bouger ferait choisir
        l'autre."""
        with open(self.base, "w") as fh:
            json.dump(
                {
                    D.CONFIG_KEY: [
                        {"name": "aa", "target": "a.example"},
                        {"name": "bb", "target": "b.example"},
                    ]
                },
                fh,
            )
        D.save({"name": "aa", "target": "corrigee.example"})
        self.assertEqual(["aa", "bb"], D.names())

    def test_deleting_a_correction_brings_the_shared_one_back(self):
        with open(self.base, "w") as fh:
            json.dump(
                {D.CONFIG_KEY: [{"name": "equipe", "target": "m.example"}]}, fh
            )
        D.save({"name": "equipe", "target": "corrigee.example"})
        self.assertTrue(D.delete("equipe"))
        self.assertEqual("m.example", D.load("equipe")["target"])

    def test_an_entry_without_a_name_is_filtered_out(self):
        """Impossible à choisir, à modifier et à supprimer."""
        with open(self.base, "w") as fh:
            json.dump({D.CONFIG_KEY: [{"target": "m.example"}]}, fh)
        self.assertEqual([], D.names())

    def test_a_missing_section_is_not_a_crash(self):
        with open(self.base, "w") as fh:
            json.dump({}, fh)
        self.assertEqual([], D.load_all())
        self.assertIsNone(D.load("essai"))


class TestLaCibleRetenue(CibleSurDisque):
    """Le NOM est retenu ; la fiche est relue à chaque fois."""

    def setUp(self):
        super().setUp()
        self.prefs = {}
        patcheur = patch.multiple(
            "script.remote.deploy_target.todo_prefs",
            get=lambda cle, defaut=None: self.prefs.get(cle, defaut),
            set=lambda cle, valeur: self.prefs.__setitem__(cle, valeur),
        )
        patcheur.start()
        self.addCleanup(patcheur.stop)

    def test_nothing_selected_answers_none(self):
        """Un None dit à l'écran qu'il a une question à poser."""
        self.assertIsNone(D.selected())

    def test_what_is_selected_comes_back(self):
        D.save(VALIDE)
        D.select("essai")
        self.assertEqual("compte@machine.example", D.selected()["target"])

    def test_editing_the_target_moves_the_selection_with_it(self):
        """LA raison de ne garder que le nom : une fiche recopiée
        nommerait encore l'ancienne adresse après une modification."""
        D.save(VALIDE)
        D.select("essai")
        D.save(dict(VALIDE, target="autre.example"))
        self.assertEqual("autre.example", D.selected()["target"])

    def test_a_deleted_target_is_asked_for_again_and_does_not_crash(self):
        D.save(VALIDE)
        D.select("essai")
        D.delete("essai")
        self.assertIsNone(D.selected())

    def test_forgetting_takes_an_empty_name(self):
        D.save(VALIDE)
        D.select("essai")
        D.select("")
        self.assertIsNone(D.selected())


if __name__ == "__main__":
    unittest.main()
