#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le banc du moteur : ce qu'il décide avant de toucher une machine.

Le banc crée de vraies VM et les efface. Ce qui est éprouvé ici est donc tout
ce qui se décide AVANT et APRÈS : les préalables, le terrain choisi, le pont
libre, la forme du jeton, l'ordre de la défaite, et l'empreinte qui dit quoi
défaire. Les verbes, eux, exigent une grappe.

Deux propriétés portent le reste. **Rien ne s'efface sans que le nom concorde**,
parce qu'un VMID se réattribue. Et **le jeton se passe en deux morceaux**,
parce que la forme complète produit un 401 muet que le même jeton contredit en
HTTP direct.

Les noms du banc sont inventés, et une épreuve d'ici vérifie qu'ils n'existent
nulle part ailleurs dans le dépôt : un banc qui reprendrait un nom du parc
détruirait, au rasage, ce qui ne lui appartient pas.
"""

import os
import subprocess
import sys
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)
sys.path.append(os.path.join(RACINE, "long_test"))

import setops_banc as B  # noqa: E402


def prealable(tenu, quoi="banc-fictif"):
    return B.Prealable(quoi=quoi, tenu=tenu)


class TestLesPrealablesSeDisentAvant(unittest.TestCase):
    """La règle de ce dossier : dire ce qui manque AVANT de créer quoi que ce
    soit. Un plan qu'on lit après coup ne sert plus à décider."""

    def test_all_held_lets_it_go_on(self):
        """Le contrôle positif : sans lui, un juge qui refuse toujours
        passerait les refus ci-dessous."""
        self.assertEqual(
            B.SORTIE_OK, B.juge([prealable(True), prealable(True)])
        )
        self.assertEqual((), B.manquants([prealable(True)]))

    def test_one_missing_means_nothing_was_attempted(self):
        """20, et non 30 : rien n'a été tenté, donc ce n'est pas une épreuve
        arrêtée en chemin."""
        self.assertEqual(
            B.SORTIE_OUTILLAGE, B.juge([prealable(True), prealable(False)])
        )

    def test_something_unmeasurable_is_not_taken_for_present(self):
        """« Pas su regarder » n'est pas « tenu » : la distinction sert à
        l'écran, le verdict est le même."""
        self.assertEqual(B.SORTIE_OUTILLAGE, B.juge([prealable(None)]))
        self.assertEqual(1, len(B.manquants([prealable(None)])))

    def test_every_exit_code_is_in_the_closed_vocabulary(self):
        for cas in (
            [],
            [prealable(True)],
            [prealable(False)],
            [prealable(None)],
        ):
            with self.subTest(cas=cas):
                self.assertIn(B.juge(cas), B.SORTIES)

    def test_the_three_codes_do_not_read_alike(self):
        """Confondre 0 et 30 ferait lire « concluant » sur une épreuve qui n'a
        rien éprouvé."""
        self.assertEqual(3, len(set(B.SORTIES)))


class TestLeTerrainSeDeduitSansSEnfoncer(unittest.TestCase):
    """Un étage suffit, et le moins profond est le bon : chacun de plus rend
    tout 15 à 30 fois plus lent."""

    RAPPORT = {
        "etages": [
            {"niveau": 1, "alias": "banc-pve-1", "ok": True},
            {"niveau": 2, "alias": "banc-pve-1+banc-pve-2", "ok": True},
        ]
    }

    def test_the_shallowest_floor_is_taken(self):
        self.assertEqual("banc-pve-1", B.terrain_par_defaut(self.RAPPORT))

    def test_a_floor_that_did_not_come_up_is_not_a_terrain(self):
        rapport = {
            "etages": [
                {"niveau": 1, "alias": "banc-pve-1", "ok": False},
                {"niveau": 2, "alias": "banc-pve-2", "ok": True},
            ]
        }
        self.assertEqual("banc-pve-2", B.terrain_par_defaut(rapport))

    def test_a_floor_without_an_alias_is_not_a_terrain(self):
        """L'alias est le seul point d'entrée : l'adresse IP ne figure dans
        aucun rapport du labo."""
        rapport = {"etages": [{"niveau": 1, "alias": "  ", "ok": True}]}
        self.assertEqual("", B.terrain_par_defaut(rapport))

    def test_no_report_gives_no_terrain_rather_than_a_guess(self):
        for vu in (None, {}, {"etages": []}, "pas un rapport"):
            with self.subTest(vu=vu):
                self.assertEqual("", B.terrain_par_defaut(vu))


class TestLePontDuBancNeReprendRien(unittest.TestCase):
    """Rendre conscient des VLAN un pont déjà posé changerait le réseau des
    usages qui s'appuient dessus."""

    INTERFACES = (
        "auto lo\niface lo inet loopback\n"
        "auto vmbr0\niface vmbr0 inet static\n    address 10.10.10.1/24\n"
        "auto vmbr9\niface vmbr9 inet manual\n"
    )

    def test_a_declared_bridge_is_never_taken(self):
        self.assertEqual("vmbr10", B.pont_libre(self.INTERFACES))

    def test_the_first_free_number_is_taken(self):
        self.assertEqual(
            "vmbr9", B.pont_libre("auto vmbr0\niface vmbr0 inet\n")
        )

    def test_nothing_declared_still_stays_off_the_first_bridges(self):
        """Le numéro de départ est haut exprès : « vmbr0 » est celui du labo."""
        self.assertEqual("vmbr9", B.pont_libre(""))

    def test_no_free_number_gives_no_name_rather_than_one_to_overwrite(self):
        pris = "".join(f"auto vmbr{n}\n" for n in range(0, 100))
        self.assertEqual("", B.pont_libre(pris))

    def test_a_name_inside_another_word_is_not_a_declaration(self):
        """« vmbr90 » n'est pas « vmbr9 » : juger par sous-chaîne sauterait un
        numéro libre, ou pire en reprendrait un pris."""
        self.assertEqual("vmbr9", B.pont_libre("auto vmbr90\n"))

    def test_the_bench_bridge_is_vlan_aware(self):
        joint = "\n".join(B.cmds_pont("vmbr9", "10.99.9.1/24"))
        self.assertIn("bridge-vlan-aware yes", joint)
        self.assertIn("bridge-vids", joint)


class TestLeJetonSePasseEnDeuxMorceaux(unittest.TestCase):
    """proxmoxer recompose « utilisateur!nom » lui-même : la forme complète
    produit un 401 MUET, que le même jeton contredit en HTTP direct."""

    def test_the_token_id_carries_no_user_and_no_separator(self):
        env = B.environnement_api("10.0.0.9", "s3cr3t-fictif")
        self.assertNotIn("!", env["PROXMOX_API_TOKEN_ID"])
        self.assertNotIn("@", env["PROXMOX_API_TOKEN_ID"])
        self.assertEqual(B.UTILISATEUR_API, env["PROXMOX_API_USER"])

    def test_the_four_variables_the_playbook_reads_are_all_there(self):
        """Le playbook ASSERTE les quatre non vides : il en manque une, il
        refuse avant d'agir."""
        env = B.environnement_api("10.0.0.9", "s3cr3t-fictif")
        for nom in (
            "PROXMOX_API_HOST",
            "PROXMOX_API_USER",
            "PROXMOX_API_TOKEN_ID",
            "PROXMOX_API_TOKEN_SECRET",
        ):
            with self.subTest(nom=nom):
                self.assertTrue(env.get(nom))

    def test_nothing_is_passed_without_a_host_or_a_secret(self):
        """Un environnement à moitié posé ferait échouer l'assertion du
        playbook sur une variable, et chercher la panne au mauvais endroit."""
        self.assertEqual({}, B.environnement_api("", "s3cr3t-fictif"))
        self.assertEqual({}, B.environnement_api("10.0.0.9", ""))
        self.assertEqual({}, B.environnement_api(None, None))

    def test_the_secret_is_read_from_the_json_the_command_prints(self):
        self.assertEqual(
            "s3cr3t-fictif",
            B.lit_jeton(
                '{"full-tokenid": "u!banc", "value": "s3cr3t-fictif"}'
            ),
        )

    def test_a_shape_that_changed_gives_nothing_rather_than_a_piece(self):
        """Un secret tronqué donnerait un 401 que rien n'explique."""
        for texte in ("", None, "pas du json", "{}", '{"value": 42}', "[]"):
            with self.subTest(texte=texte):
                self.assertEqual("", B.lit_jeton(texte))

    def test_the_token_is_created_last_of_its_commands(self):
        """Son secret ne s'affiche qu'à la création : une commande qui
        échouerait après lui perdrait le seul moment où il est lisible."""
        cmds = B.cmds_jeton()
        self.assertIn("token add", cmds[-1])
        self.assertTrue(any("user add" in c for c in cmds[:-1]))


class TestRienNeSEffaceSansQueLeNomConcorde(unittest.TestCase):
    """Un VMID se réattribue : l'effacer sur le seul numéro détruirait le
    travail de quelqu'un d'autre."""

    def test_the_same_name_is_erasable(self):
        self.assertTrue(B.effacable("banc-fictif-01", "banc-fictif-01"))
        self.assertTrue(B.effacable("banc-fictif-01", " banc-fictif-01 "))

    def test_another_name_is_refused(self):
        self.assertFalse(B.effacable("banc-fictif-01", "prod-de-quelquun"))

    def test_a_name_that_only_contains_it_is_refused(self):
        """Appariement STRICT : « banc-fictif-01-bis » n'est pas la VM du
        banc."""
        self.assertFalse(B.effacable("banc-fictif-01", "banc-fictif-01-bis"))

    def test_an_unreadable_name_refuses_instead_of_concluding(self):
        for attendu, vu in (
            ("", "quoi que ce soit"),
            ("banc-fictif-01", ""),
            (None, None),
        ):
            with self.subTest(attendu=attendu, vu=vu):
                self.assertFalse(B.effacable(attendu, vu))


class TestLOrdreDeLaDefaite(unittest.TestCase):
    EMPREINTE = B.Empreinte(
        terrain="banc-pve-1",
        ecosysteme=B.ECOSYSTEME,
        pont="vmbr9",
        utilisateur=B.UTILISATEUR_API,
        modele=9000,
        vms=((900101, "banc-un"), (900102, "banc-deux")),
    )

    def test_the_vms_go_before_the_bridge(self):
        """Défaire le pont d'abord retirerait leur réseau aux VM sans les
        effacer, et il faudrait alors les retrouver à la main."""
        genres = [g.genre for g in B.a_defaire(self.EMPREINTE)]
        self.assertLess(genres.index(B.VM), genres.index(B.PONT))

    def test_the_vms_go_before_the_template(self):
        """Un gabarit ne s'efface pas tant qu'un clone lié en dépend."""
        genres = [g.genre for g in B.a_defaire(self.EMPREINTE)]
        self.assertLess(genres.index(B.VM), genres.index(B.MODELE))

    def test_the_last_created_vm_goes_first(self):
        gestes = [g for g in B.a_defaire(self.EMPREINTE) if g.genre == B.VM]
        self.assertEqual(["900102", "900101"], [g.vise for g in gestes])

    def test_the_ecosystem_goes_last(self):
        """Son plan nomme les VM, et le rasage s'y appuie."""
        self.assertEqual(B.ECO, B.a_defaire(self.EMPREINTE)[-1].genre)

    def test_what_was_never_posed_is_not_undone(self):
        vide = B.Empreinte("", "", "", "", 0, ())
        self.assertEqual((), B.a_defaire(vide))
        self.assertEqual((), B.a_defaire(None))

    def test_every_genre_is_in_the_closed_vocabulary(self):
        for geste in B.a_defaire(self.EMPREINTE):
            with self.subTest(genre=geste.genre):
                self.assertIn(geste.genre, B.GENRES)

    def test_every_step_carries_the_name_that_authorises_it(self):
        for geste in B.a_defaire(self.EMPREINTE):
            with self.subTest(vise=geste.vise):
                self.assertTrue(geste.nom)


class TestLEmpreinte(unittest.TestCase):
    """Une empreinte partielle ferait effacer ce qu'elle nomme en laissant le
    reste — et le reste est justement ce qu'on ne saurait plus retrouver."""

    def test_what_is_written_reads_back_identical(self):
        vue = TestLOrdreDeLaDefaite.EMPREINTE
        self.assertEqual(vue, B.lit_empreinte(B.ecrit_empreinte(vue)))

    def test_a_vmid_that_is_not_a_positive_integer_refuses_it_all(self):
        for vmid in (0, -1, "900101", 900101.0, True, None):
            with self.subTest(vmid=vmid):
                import json

                texte = json.dumps({"vms": [[vmid, "banc-un"]]})
                self.assertIsNone(B.lit_empreinte(texte))

    def test_a_vm_without_a_name_refuses_it_all(self):
        """Sans nom, rien n'autorise son effacement."""
        import json

        self.assertIsNone(
            B.lit_empreinte(json.dumps({"vms": [[900101, "  "]]}))
        )

    def test_anything_that_is_not_a_footprint_is_refused(self):
        for texte in ("", None, "[]", "pas du json", '{"vms": "deux"}'):
            with self.subTest(texte=texte):
                self.assertIsNone(B.lit_empreinte(texte))

    def test_a_footprint_that_posed_nothing_is_still_read(self):
        """Elle est VALIDE : le banc a pu échouer avant de créer."""
        self.assertIsNotNone(B.lit_empreinte("{}"))


class TestLePlanSeLitAvant(unittest.TestCase):
    def test_it_names_the_terrain(self):
        etapes = B.plan(B.PASSES, "banc-pve-1")
        self.assertIn("banc-pve-1", etapes[0][0])

    def test_no_terrain_is_said_and_not_left_blank(self):
        self.assertIn("aucun", B.plan(B.PASSES, "")[0][0])

    def test_each_pass_appears_in_the_plan(self):
        texte = "\n".join(q for q, _d in B.plan(B.PASSES, "banc-pve-1"))
        for passe in B.PASSES:
            with self.subTest(passe=passe):
                self.assertIn(passe, texte)

    def test_the_environment_pass_comes_before_the_vault_pass(self):
        """Inversées, un échec de la voûte ne se distinguerait pas d'une grappe
        qui ne clone pas."""
        texte = "\n".join(q for q, _d in B.plan(B.PASSES, "t"))
        self.assertLess(texte.index(B.PASSE_ENV), texte.index(B.PASSE_VOUTE))

    def test_the_steps_that_take_time_announce_it(self):
        durees = [d for _q, d in B.plan(B.PASSES, "t") if d]
        self.assertTrue(durees)


class TestLesNomsDuBancNexistentNullePartAilleurs(unittest.TestCase):
    """LA RÈGLE DU DÉPÔT, ÉPROUVÉE. Un banc qui reprendrait un nom du parc
    détruirait, au rasage, ce qui ne lui appartient pas. L'épreuve saute là où
    git n'est pas là."""

    LES_SIENS = ("ECOSYSTEME", "UTILISATEUR_API", "GABARIT")

    def cherche(self, valeur):
        """Les fichiers suivis qui portent `valeur`, hors le banc et ceci."""
        try:
            fait = subprocess.run(
                ["git", "grep", "-lF", "--", valeur],
                cwd=RACINE,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            self.skipTest("git indisponible")
        if fait.returncode not in (0, 1):
            self.skipTest("git grep n'a pas répondu")
        siens = {
            "long_test/setops_banc.py",
            "test/test_longtest_setops_banc.py",
            "tasks/todo.md",
        }
        return [f for f in fait.stdout.split() if f and f not in siens]

    def test_no_name_of_the_bench_is_used_elsewhere(self):
        for attribut in self.LES_SIENS:
            valeur = getattr(B, attribut)
            with self.subTest(nom=attribut, valeur=valeur):
                self.assertEqual([], self.cherche(valeur))

    def test_the_search_would_find_a_name_that_is_used(self):
        """Contrôle positif : sans lui, une recherche qui ne trouve jamais
        rien passerait l'épreuve ci-dessus."""
        self.assertNotEqual([], self.cherche("bridge_setup_cmds"))


if __name__ == "__main__":
    unittest.main()
