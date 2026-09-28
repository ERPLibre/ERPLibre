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

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import yaml

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

    def test_a_level_that_is_not_an_integer_is_no_terrain(self):
        """Un niveau absent devenait 0 et gagnait comme « le moins profond » ;
        en texte, « 9 » se comparait après « 10 » ; mixtes, ils levaient un
        TypeError au lieu de rendre une réponse."""
        for etage in (
            {"ok": True, "alias": "sans-niveau"},
            {"ok": True, "alias": "en-texte", "niveau": "1"},
            {"ok": True, "alias": "booleen", "niveau": True},
        ):
            with self.subTest(etage=etage):
                self.assertEqual("", B.terrain_par_defaut({"etages": [etage]}))

    def test_a_floor_whose_ok_is_a_word_is_no_terrain(self):
        """« false » en texte est vrai : un étage RATÉ devenait éligible."""
        self.assertEqual(
            "",
            B.terrain_par_defaut(
                {"etages": [{"ok": "false", "alias": "rate", "niveau": 1}]}
            ),
        )

    def test_mixed_levels_answer_instead_of_raising(self):
        self.assertEqual(
            "bon",
            B.terrain_par_defaut(
                {
                    "etages": [
                        {"ok": True, "alias": "texte", "niveau": "2"},
                        {"ok": True, "alias": "bon", "niveau": 1},
                    ]
                }
            ),
        )

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

    def test_a_read_that_says_nothing_is_not_a_clean_terrain(self):
        """Un `ssh … cat` qui échoue imprime sa plainte, et une plainte n'est
        pas un terrain vierge. Rendre « vmbr9 » donnait un feu vert, et le banc
        posait un pont conscient des VLAN sur un nom peut-être pris — le geste
        même que ce module interdit en capitales."""
        for texte in ("", None, "Permission denied", "cat: no such file"):
            with self.subTest(texte=texte):
                self.assertEqual("", B.pont_libre(texte))

    # L'en-tête que PVE écrit lui-même dans /etc/network/interfaces, relevé sur
    # un hôte Proxmox fraîchement installé. Il PARLE de « source » et de
    # « source-directory » en prose, sans déléguer quoi que ce soit.
    ENTETE_PVE = (
        "# network interface settings; autogenerated\n"
        "# Please do NOT modify this file directly, unless you know what\n"
        "# you're doing.\n"
        "#\n"
        "# If you want to manage parts of the network configuration manually,\n"
        "# please utilize the 'source' or 'source-directory' directives to do\n"
        "# so.\n"
        "# PVE will preserve these directives, but will NOT read its network\n"
        "# configuration from sourced files, so do not attempt to move any of\n"
        "# the PVE managed interfaces into external files!\n"
        "\n"
        "auto lo\n"
        "iface lo inet loopback\n"
        "\n"
        "iface enp1s0 inet manual\n"
    )

    def test_the_header_pve_writes_itself_fools_nothing(self):
        """LE GARDE JUGE LE PREMIER MOT, non une sous-chaîne. L'en-tête que PVE
        autogénère PARLE de « source » et de « source-directory » sans rien
        déléguer : cherchés par contenance, ils feraient refuser le banc sur
        TOUT hôte Proxmox réel, et le refus se lirait comme un terrain sale."""
        self.assertEqual("vmbr9", B.pont_libre(self.ENTETE_PVE))

    def test_a_file_that_delegates_is_not_the_whole_declaration(self):
        """PVE écrit « source /etc/network/interfaces.d/* » par défaut, et sa
        SDN y pose ses ponts : le texte reçu ne les montre pas."""
        for delegation in (
            "source /etc/network/interfaces.d/*",
            "source-directory interfaces.d",
        ):
            with self.subTest(delegation=delegation):
                self.assertEqual(
                    "", B.pont_libre(self.INTERFACES + delegation + "\n")
                )

    def test_the_starting_number_stays_off_the_lab_bridge(self):
        """« vmbr0 » est celui du labo, et le rendre conscient des VLAN
        changerait le réseau de ses usages."""
        self.assertEqual(
            "vmbr9", B.pont_libre("auto vmbr0\niface vmbr0 inet static\n")
        )

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
        underlay=B.UNDERLAY_BANC,
        pont="vmbr9",
        utilisateur=B.UTILISATEUR_API,
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
        self.assertLess(genres.index(B.VM), genres.index(B.PONT))

    def test_the_last_created_vm_goes_first(self):
        gestes = [g for g in B.a_defaire(self.EMPREINTE) if g.genre == B.VM]
        self.assertEqual(["900102", "900101"], [g.vise for g in gestes])

    def test_the_underlay_goes_last_of_all(self):
        """IL BORNE TOUT L'ORDRE : raser le locataire passe par la grappe, la
        grappe se joint par le jeton, et le jeton vit dans la voûte de
        l'underlay. Le défaire plus tôt retirerait au banc le moyen de défaire
        le reste."""
        self.assertEqual(B.UNDERLAY, B.a_defaire(self.EMPREINTE)[-1].genre)

    def test_the_tenant_goes_just_before_the_underlay(self):
        """Son plan nomme les VM, et le rasage s'y appuie."""
        genres = [g.genre for g in B.a_defaire(self.EMPREINTE)]
        self.assertEqual([B.ECO, B.UNDERLAY], genres[-2:])

    def test_the_underlay_goes_after_everything_it_serves(self):
        genres = [g.genre for g in B.a_defaire(self.EMPREINTE)]
        rang = genres.index(B.UNDERLAY)
        for servi in (B.VM, B.PONT, B.API, B.ECO):
            with self.subTest(servi=servi):
                self.assertLess(genres.index(servi), rang)

    def test_a_footprint_that_is_not_ours_undoes_nothing(self):
        """Rien ne rattachait au banc les noms qu'elle porte : la lecture valide
        des FORMES, jamais une appartenance. Une empreinte nommant un écosystème
        de production passait, et ses VM s'effaçaient dès que le nom
        concordait."""
        for champ, valeur in (
            ("ecosysteme", "OPS-Fictif-Dolomie"),
            ("underlay", "SITE-Fictif-Dolomie"),
            ("utilisateur", "quelquun-dautre@pve"),
            ("terrain", ""),
        ):
            with self.subTest(champ=champ):
                autre = self.EMPREINTE._replace(**{champ: valeur})
                self.assertFalse(B.nous(autre))
                self.assertEqual((), B.a_defaire(autre))

    def test_the_bench_s_own_footprint_is_recognised(self):
        """Le contrôle positif : sans lui, une appartenance qui refuse tout
        passerait les trois refus ci-dessus."""
        self.assertTrue(B.nous(self.EMPREINTE))
        self.assertTrue(B.a_defaire(self.EMPREINTE))

    def test_every_step_carries_the_machine_to_play_it_on(self):
        """Lu puis jeté, le terrain devait être redéduit au moment de jouer — et
        le terrain déduit est celui du DERNIER étage posé, potentiellement une
        autre grappe. Les VMID d'une grappe détruits sur une autre."""
        for geste in B.a_defaire(self.EMPREINTE):
            with self.subTest(vise=geste.vise):
                self.assertEqual(self.EMPREINTE.terrain, geste.terrain)

    def test_what_was_never_posed_is_not_undone(self):
        vide = B.Empreinte("", "", "", "", "", 0, ())
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

    def test_two_vms_on_one_vmid_refuse_it_all(self):
        """DEUX VM SUR UN VMID N'ONT PAS DE MAÎTRE, comme deux pools sur un VMID
        dans le devis. L'appelant confronte le nom geste par geste : le premier
        refuserait, le second concorderait, et la destruction partirait sur un
        enregistrement qui se contredit."""
        import json

        self.assertIsNone(
            B.lit_empreinte(
                json.dumps({"vms": [[101, "banc-un"], [101, "banc-deux"]]})
            )
        )

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
    def test_it_names_both_repositories(self):
        """DEUX DÉPÔTS, pas un : le locataire porte le plan, l'underlay porte la
        grappe et la voûte au jeton. Un banc à un seul dépôt ne peut pas
        matérialiser une VM."""
        texte = "\n".join(q for q, _d in B.plan(B.PASSES, "banc-pve-1"))
        self.assertIn(B.ECOSYSTEME, texte)
        self.assertIn(B.UNDERLAY_BANC, texte)

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

    LES_SIENS = ("ECOSYSTEME", "UNDERLAY_BANC", "UTILISATEUR_API", "GABARIT")

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


def detail_pont(nom, filtrage="1", champ=True):
    """La forme qu'un Proxmox imprime pour « ip -d link show dev <pont> ».

    Trois lignes : l'entête indexée, le lien, puis la ligne de détail du pont
    qui porte les champs. Les valeurs sont INVENTÉES — une adresse matérielle
    relevée sur une machine n'a rien à faire dans une épreuve — mais l'ordre et
    les noms des champs sont ceux que le noyau écrit.
    """
    detail = (
        "    bridge forward_delay 0 hello_time 200 max_age 2000"
        " ageing_time 30000 stp_state 0 priority 32768"
    )
    if champ:
        detail += f" vlan_filtering {filtrage} vlan_protocol 802.1Q"
    detail += " bridge_id 8000.0:0:0:0:0:0 vlan_default_pvid 1"
    return (
        f"3: {nom}: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 state UNKNOWN\n"
        "    link/ether 02:00:00:00:00:01 brd ff:ff:ff:ff:ff:ff\n"
        + detail
        + "\n"
    )


class TestLeConstatDuPont(unittest.TestCase):
    """Un pont DEBOUT MAIS NON FILTRANT est le pire des trois états : la carte
    taguée d'une VM y démarre et reste injoignable, et la panne ne se voit ni à
    la création, ni dans un code de retour. Le repli de la pose monte justement
    le pont par « ip link add », qui ne demande aucun filtrage."""

    def test_a_vlan_aware_bridge_is_usable(self):
        vu = B.lit_constat_pont(detail_pont("vmbr9"), "vmbr9")
        self.assertEqual(B.Constat(debout=True, vlan=True), vu)
        self.assertTrue(vu.utilisable)

    def test_a_bridge_that_does_not_filter_is_not_usable(self):
        """L'état que le repli de la pose produit."""
        vu = B.lit_constat_pont(detail_pont("vmbr9", filtrage="0"), "vmbr9")
        self.assertEqual(B.Constat(debout=True, vlan=False), vu)
        self.assertFalse(vu.utilisable)

    def test_a_bridge_absent_is_a_fact_not_a_doubt(self):
        """Le noyau l'AFFIRME ; None dirait « on n'a pas su lire »."""
        vu = B.lit_constat_pont('Device "vmbr9" does not exist.', "vmbr9")
        self.assertEqual(B.Constat(debout=False, vlan=None), vu)

    def test_the_field_missing_is_not_the_field_at_zero(self):
        """« Pas vu » n'est pas « ne filtre pas » : sur un noyau qui ne
        l'imprimerait pas, conclure « ne filtre pas » ferait reposer un pont
        qui filtre peut-être."""
        vu = B.lit_constat_pont(detail_pont("vmbr9", champ=False), "vmbr9")
        self.assertEqual(B.Constat(debout=True, vlan=None), vu)
        self.assertFalse(vu.utilisable)

    def test_another_field_carrying_the_same_digit_says_nothing(self):
        """« vlan_default_pvid 1 » porte le même chiffre et ne dit rien du
        filtrage : le champ se lit par son NOM suivi de sa valeur."""
        vu = B.lit_constat_pont(detail_pont("vmbr9", champ=False), "vmbr9")
        self.assertIn("vlan_default_pvid 1", detail_pont("vmbr9", champ=False))
        self.assertIsNone(vu.vlan)

    def test_a_line_about_another_bridge_does_not_answer(self):
        """« vmbr90 » n'est pas « vmbr9 » : l'entête est appariée sur le nom
        entier, suivi de son deux-points."""
        self.assertIsNone(B.lit_constat_pont(detail_pont("vmbr90"), "vmbr9"))

    def test_an_unreadable_output_concludes_nothing(self):
        for texte in ("", None, "bruit quelconque", "Warning: ssh a parlé"):
            with self.subTest(texte=texte):
                self.assertIsNone(B.lit_constat_pont(texte, "vmbr9"))

    def test_no_name_asks_nothing(self):
        self.assertIsNone(B.lit_constat_pont(detail_pont("vmbr9"), ""))

    def test_the_command_reads_the_kernel_not_a_second_path(self):
        """`ip -d link show` est la commande que le dépôt lit déjà pour les
        ponts ; un second chemin vers le même fait dériverait du premier."""
        cmds = B.cmds_constater_pont("vmbr9")
        self.assertEqual(1, len(cmds))
        self.assertIn("ip -d link show", cmds[0])
        self.assertNotIn("/sys/", cmds[0])

    def test_a_name_with_a_space_is_quoted(self):
        """Une commande bâtie sans citation laisserait un nom porteur d'espace
        couper l'argument en deux."""
        self.assertIn(
            "'vmbr9 et plus'", B.cmds_constater_pont("vmbr9 et plus")[0]
        )


class TestLesLiensDuMoteurNeSeVolentPas(unittest.TestCase):
    """LE BANC POSE SES LIENS DANS LE MOTEUR, et le moteur n'est pas à lui. Un
    moteur où une instance est déjà montée porte le travail d'un exploitant :
    remplacer son lien détournerait ses gestes vers l'écosystème du banc, dont
    le rasage détruit tout ce que l'inventaire nomme."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        self.ici = os.path.join(self.d, "lien")

    def test_nothing_there_is_to_be_posed(self):
        """Le contrôle positif : sans lui, un état qui refuse toujours
        passerait tous les refus ci-dessous."""
        self.assertEqual(B.A_POSER, B.lien_etat(self.ici, "../cible"))

    def test_our_own_link_is_recognised(self):
        os.symlink("../cible", self.ici)
        self.assertEqual(B.NOTRE, B.lien_etat(self.ici, "../cible"))

    def test_a_link_pointing_elsewhere_is_occupied(self):
        os.symlink("../celui-de-quelqu-un-d-autre", self.ici)
        self.assertEqual(B.OCCUPE, B.lien_etat(self.ici, "../cible"))

    def test_a_real_directory_is_occupied(self):
        os.mkdir(self.ici)
        self.assertEqual(B.OCCUPE, B.lien_etat(self.ici, "../cible"))

    def test_a_real_file_is_occupied(self):
        with open(self.ici, "w", encoding="utf-8") as ecrit:
            ecrit.write("le fichier d'un exploitant\n")
        self.assertEqual(B.OCCUPE, B.lien_etat(self.ici, "../cible"))

    def test_a_dangling_link_elsewhere_still_occupies_the_name(self):
        """LA PROPRIÉTÉ. Le dépôt que le lien d'un exploitant désigne n'est pas
        toujours monté ; le lien pend alors, et une lecture qui SUIT le lien le
        déclare absent. Le banc écraserait ce lien, et le geste suivant de
        l'exploitant partirait vers l'écosystème du banc."""
        os.symlink(
            os.path.join(self.d, "depot-non-monte", "underlay.yml"), self.ici
        )
        self.assertFalse(os.path.exists(self.ici))
        self.assertEqual(B.OCCUPE, B.lien_etat(self.ici, "../cible"))

    def test_a_dangling_link_of_ours_is_still_ours(self):
        """La contrepartie : notre propre lien pend entre deux passes, et le
        reposer ne doit pas être refusé."""
        os.symlink("../cible", self.ici)
        self.assertFalse(os.path.exists(self.ici))
        self.assertEqual(B.NOTRE, B.lien_etat(self.ici, "../cible"))

    def test_without_a_target_it_refuses_to_conclude(self):
        self.assertEqual(B.INCONNU, B.lien_etat(self.ici, ""))

    def test_every_answer_belongs_to_the_closed_vocabulary(self):
        os.symlink("../ailleurs", self.ici)
        for vise in ("../cible", "../ailleurs", ""):
            with self.subTest(vise=vise):
                self.assertIn(B.lien_etat(self.ici, vise), B.ETATS_LIEN)


class TestLIndexNeSePartagePas(unittest.TestCase):
    """Tout l'adressage d'un écosystème dérive de son index : deux dépôts qui
    le partagent dérivent les mêmes adresses et les mêmes VLAN, et le rasage du
    banc détruit les VM de l'autre en croyant détruire les siennes."""

    def test_a_free_index_is_free(self):
        """Le contrôle positif : sans lui, un garde qui refuse toujours
        passerait les refus ci-dessous."""
        self.assertIs(True, B.index_libre([{"index": 4}], 211))

    def test_a_taken_index_is_refused(self):
        self.assertIs(False, B.index_libre([{"index": 211}], 211))

    def test_a_taken_index_is_refused_even_as_text(self):
        self.assertIs(False, B.index_libre([{"index": "211"}], 211))

    def test_an_unreadable_discovery_does_not_grant(self):
        """Ne pas savoir n'est pas une permission."""
        self.assertIsNone(B.index_libre(None, 211))

    def test_a_malformed_discovery_does_not_grant(self):
        for vu in ([{"index": "pas un nombre"}], ["pas un dictionnaire"]):
            with self.subTest(vu=vu):
                self.assertIsNone(B.index_libre(vu, 211))

    def test_an_entry_without_index_reserves_nothing(self):
        """La découverte du moteur ignore elle aussi ce qui n'en déclare pas."""
        self.assertIs(True, B.index_libre([{"index": None}], 211))

    def test_the_two_indexes_of_the_bench_differ(self):
        """Sites et locataires tirent du MÊME espace d'index."""
        self.assertNotEqual(B.INDEX_ECOSYSTEME, B.INDEX_UNDERLAY)


class TestCeQueLeBancEcritSeLitParLeMoteur(unittest.TestCase):
    """Les fichiers que le banc pose sont lus par le moteur, pas par le banc :
    ce qui est éprouvé ici est donc l'expression du MOTEUR, appliquée au texte
    du banc."""

    def bloc(self, texte):
        """Ce que le lecteur du moteur tire de ce texte : `get(...) or None`."""
        return (yaml.safe_load(texte) or {}).get("underlay") or None

    def test_the_underlay_block_is_never_empty_for_that_reader(self):
        """UN BLOC VIDE SE LIT COMME UN FICHIER ABSENT, et l'accès à la grappe
        refuse alors « pas de cluster à piloter » sans dire que le fichier est
        là."""
        self.assertIsNotNone(self.bloc(B.texte_underlay("un-noeud", "vmbr9")))

    def test_that_reader_would_reject_an_empty_block(self):
        """Le contrôle positif de l'épreuve ci-dessus."""
        self.assertIsNone(self.bloc("underlay: {}\n"))

    def test_the_underlay_declares_its_index(self):
        """Un site sans index déclaré reste invisible à la découverte des
        dossiers frères, donc il n'accueille rien."""
        self.assertEqual(
            B.INDEX_UNDERLAY, self.bloc(B.texte_underlay("n", "p"))["index"]
        )

    def test_the_underlay_refuses_without_a_node_or_a_bridge(self):
        for noeud, pont in (("", "vmbr9"), ("n", ""), ("", "")):
            with self.subTest(noeud=noeud, pont=pont):
                self.assertEqual("", B.texte_underlay(noeud, pont))

    def test_the_hoster_file_carries_no_secret(self):
        """CE FICHIER VOYAGE AVEC UN DÉPÔT. Le jeton vit dans la voûte
        chiffrée à côté, et c'est toute la raison d'être des deux fichiers."""
        lu = yaml.safe_load(B.texte_hebergeur("h", "n", "s", "p")) or {}
        self.assertNotIn("proxmox_api_token_id", lu)
        self.assertNotIn("proxmox_api_token_secret", lu)

    def test_the_vault_does_carry_them(self):
        """Le contrôle positif : sans lui, deux clés jamais écrites nulle part
        passeraient l'épreuve ci-dessus."""
        lu = yaml.safe_load(B.texte_voute("un-secret-invente")) or {}
        self.assertIn("proxmox_api_token_id", lu)
        self.assertIn("proxmox_api_token_secret", lu)

    def test_the_hoster_file_refuses_a_missing_piece(self):
        for vu in (
            ("", "n", "s", "p"),
            ("h", "", "s", "p"),
            ("h", "n", "", "p"),
            ("h", "n", "s", ""),
        ):
            with self.subTest(vu=vu):
                self.assertEqual("", B.texte_hebergeur(*vu))

    def test_the_vault_refuses_without_a_secret(self):
        for vu in ("", "   ", None):
            with self.subTest(secret=vu):
                self.assertEqual("", B.texte_voute(vu))

    def test_the_stored_token_id_is_the_bare_name(self):
        """Le client d'API recompose « utilisateur!nom » à partir des deux
        valeurs ; la forme déjà composée produit un 401 que le même jeton
        contredit en HTTP direct."""
        lu = yaml.safe_load(B.texte_voute("un-secret-invente")) or {}
        self.assertNotIn("!", str(lu["proxmox_api_token_id"]))


class TestLePlanSActiveChirurgicalement(unittest.TestCase):
    """`etat: actif` COMMANDE TOUTE LA BOUCLE. Le générateur d'inventaire range
    dans les hôtes actifs ce qui porte EXACTEMENT « actif » et tout le reste
    dans les planifiés ; les modèles livrés déclarent « planifie ». Un plan
    recopié sans la bascule produit un inventaire vide, et la matérialisation
    comme le rasage sortent à ZÉRO sans avoir rien fait."""

    MODELE = (
        "---\n"
        "# un commentaire du modèle, qui doit survivre\n"
        "serveurs:\n"
        "  infra-pki-01:  { fonction: infra-pki,  etat: planifie }\n"
        "  infra-dns-01:  { fonction: infra-dns,  etat: planifie, disque: 40G }\n"
    )

    def actifs(self, texte):
        """Les hôtes que la règle du moteur rangerait parmi les actifs."""
        lu = (yaml.safe_load(texte) or {}).get("serveurs") or {}
        return sorted(
            nom
            for nom, decl in lu.items()
            if (decl or {}).get("etat") == "actif"
        )

    def test_exactly_one_host_becomes_active(self):
        self.assertEqual(
            ["infra-dns-01"],
            self.actifs(B.active_un_hote(self.MODELE, "infra-dns-01")),
        )

    def test_the_model_as_shipped_has_none(self):
        """Le contrôle positif : sans lui, un plan dont tout serait déjà actif
        passerait l'épreuve ci-dessus."""
        self.assertEqual([], self.actifs(self.MODELE))

    def test_nothing_else_changes(self):
        """CHIRURGICAL : une seule ligne diffère, commentaires compris."""
        avant = self.MODELE.splitlines()
        apres = B.active_un_hote(self.MODELE, "infra-dns-01").splitlines()
        self.assertEqual(len(avant), len(apres))
        differentes = [
            i for i, (a, b) in enumerate(zip(avant, apres)) if a != b
        ]
        self.assertEqual(1, len(differentes))

    def test_it_refuses_rather_than_guess(self):
        for texte, hote in (
            (self.MODELE, "n-existe-pas"),
            (self.MODELE, ""),
            ("", "infra-dns-01"),
            ("serveurs:\n  a: { fonction: f }\n", "a"),
            ("  a: { etat: planifie }\n  a: { etat: planifie }\n", "a"),
        ):
            with self.subTest(hote=hote, texte=texte[:30]):
                self.assertIsNone(B.active_un_hote(texte, hote))


def empreinte_pleine(**change):
    """Une empreinte du banc, complète, que chaque épreuve altère d'un champ."""
    champs = dict(
        terrain="banc-terrain",
        ecosysteme=B.ECOSYSTEME,
        underlay=B.UNDERLAY_BANC,
        pont="vmbr9",
        utilisateur=B.UTILISATEUR_API,
        vms=((101, "banc-fictif-01"),),
        liens=("/moteur/underlay.yml", "/moteur/instance"),
        cles=(
            f"/config/setops-vault-{B.ECOSYSTEME.lower()}",
            f"/config/setops-vault-{B.UNDERLAY_BANC.lower()}",
        ),
    )
    champs.update(change)
    return B.Empreinte(**champs)


class TestCeQueLEmpreinteFaitEffacerLuiAppartient(unittest.TestCase):
    """`--detruire` EFFACE CE QUE L'EMPREINTE NOMME, et l'empreinte est un
    fichier JSON qu'un éditeur ouvre. Y écrire le chemin de la clé de voûte
    d'une production suffirait à la faire effacer — la clé sans laquelle plus
    rien ne s'y déchiffre, et qu'aucune sauvegarde de dépôt ne contient
    puisqu'elle vit exprès dehors."""

    def test_the_two_keys_of_the_bench_are_recognised(self):
        """Le contrôle positif : sans lui, un garde qui refuse toujours
        passerait tous les refus ci-dessous."""
        for nom in (B.ECOSYSTEME, B.UNDERLAY_BANC):
            with self.subTest(nom=nom):
                self.assertTrue(
                    B.cle_du_banc(f"/config/setops-vault-{nom.lower()}")
                )

    def test_a_key_that_is_not_ours_is_refused(self):
        for chemin in (
            "/config/setops-vault-un-autre-ecosysteme",
            "/config/setops-vault-",
            "/config/id_ed25519",
            "setops-vault-ops-fictif-trachyte-bis",
            "",
            None,
        ):
            with self.subTest(chemin=chemin):
                self.assertFalse(B.cle_du_banc(chemin))

    def test_the_two_links_of_the_engine_are_recognised(self):
        for nom in B.LIENS:
            with self.subTest(nom=nom):
                self.assertTrue(B.lien_du_banc(f"/moteur/{nom}"))

    def test_a_link_that_is_not_one_of_the_two_is_refused(self):
        for chemin in ("/moteur/instances", "/moteur/underlay.yaml", "", None):
            with self.subTest(chemin=chemin):
                self.assertFalse(B.lien_du_banc(chemin))

    def test_a_foreign_key_makes_the_whole_footprint_refuse(self):
        """TOUTE l'empreinte, et non la seule ligne ajoutée : une empreinte à
        qui l'on a ajouté une ligne n'est plus celle que le banc a écrite."""
        texte = json.loads(B.ecrit_empreinte(empreinte_pleine()))
        texte["cles"] = ["/config/setops-vault-une-production"]
        self.assertIsNone(B.lit_empreinte(json.dumps(texte)))

    def test_a_foreign_link_makes_the_whole_footprint_refuse(self):
        texte = json.loads(B.ecrit_empreinte(empreinte_pleine()))
        texte["liens"] = ["/etc/passwd"]
        self.assertIsNone(B.lit_empreinte(json.dumps(texte)))

    def test_a_footprint_written_by_the_bench_reads_back(self):
        """Le contrôle positif des deux refus ci-dessus."""
        empreinte = empreinte_pleine()
        self.assertEqual(
            empreinte, B.lit_empreinte(B.ecrit_empreinte(empreinte))
        )

    def test_a_footprint_naming_none_of_them_names_none(self):
        """« Rien à nommer » est une réponse valide, pas une absence."""
        texte = json.loads(B.ecrit_empreinte(empreinte_pleine()))
        del texte["liens"], texte["cles"]
        lu = B.lit_empreinte(json.dumps(texte))
        self.assertEqual(((), ()), (lu.liens, lu.cles))


class TestLOrdreDeLaDefaiteTientLesLiensEtLesCles(unittest.TestCase):
    """L'ordre n'est pas décoratif : chaque geste a besoin que le suivant soit
    encore là. La clé ouvre la voûte, la voûte porte le jeton, le jeton joint la
    grappe, et la grappe est ce par quoi tout le reste se défait."""

    def rangs(self, gestes):
        """Le rang de chaque genre : premier pour les clés, dernier sinon."""
        return {
            genre: (
                min(i for i, g in enumerate(gestes) if g.genre == genre)
                if genre == B.CLE
                else max(i for i, g in enumerate(gestes) if g.genre == genre)
            )
            for genre in {g.genre for g in gestes}
        }

    def test_links_go_before_the_repositories(self):
        """Le dépôt retiré sous un lien qui tient, le moteur nomme un
        inventaire qui n'existe plus."""
        rangs = self.rangs(B.a_defaire(empreinte_pleine()))
        self.assertLess(rangs[B.LIEN], rangs[B.ECO])
        self.assertLess(rangs[B.LIEN], rangs[B.UNDERLAY])

    def test_keys_go_after_everything_that_needs_the_cluster(self):
        rangs = self.rangs(B.a_defaire(empreinte_pleine()))
        for genre in (B.VM, B.PONT, B.API, B.ECO, B.UNDERLAY):
            with self.subTest(genre=genre):
                self.assertGreater(rangs[B.CLE], rangs[genre])

    def test_the_underlay_still_goes_after_the_tenant(self):
        """Ce que les deux genres nouveaux ne doivent pas avoir déplacé."""
        rangs = self.rangs(B.a_defaire(empreinte_pleine()))
        self.assertGreater(rangs[B.UNDERLAY], rangs[B.ECO])

    def test_the_undo_never_names_the_template(self):
        """LE GABARIT EST À L'EXPLOITANT. Le banc ne le fabrique pas — sa
        procédure impose une installation depuis l'ISO, parce qu'une machine naît
        en q35 ou ne le sera jamais proprement — donc il ne peut pas l'avoir
        posé, donc il ne doit JAMAIS le défaire. Le détruire coûterait à
        l'exploitant la réinstallation entière."""
        gestes = B.a_defaire(empreinte_pleine())
        self.assertNotEqual((), gestes)
        for geste in gestes:
            with self.subTest(geste=geste.genre):
                self.assertNotIn(B.GABARIT, (geste.nom, geste.vise))

    def test_no_genre_of_the_vocabulary_could_name_it(self):
        """Un genre qui existe finit par trouver un appelant : le vocabulaire
        clos n'en porte donc aucun pour un modèle."""
        self.assertNotIn("modele", B.GENRES)

    def test_every_genre_belongs_to_the_closed_vocabulary(self):
        for geste in B.a_defaire(empreinte_pleine()):
            with self.subTest(genre=geste.genre):
                self.assertIn(geste.genre, B.GENRES)

    def test_a_footprint_that_is_not_ours_undoes_nothing(self):
        """Le contrôle positif : sans lui, un ordre qui ne rend jamais rien
        passerait les épreuves ci-dessus."""
        self.assertEqual(
            (), B.a_defaire(empreinte_pleine(ecosysteme="OPS-Une-Production"))
        )

    def test_each_path_travels_with_its_gesture(self):
        """Le chemin est ce que le verbe efface ; le nom ne sert qu'à l'écran."""
        gestes = B.a_defaire(empreinte_pleine())
        vises = [g.vise for g in gestes if g.genre in (B.LIEN, B.CLE)]
        self.assertEqual(
            sorted(empreinte_pleine().liens + empreinte_pleine().cles),
            sorted(vises),
        )


class TestLAmorcageSeLitChezLeMoteur(unittest.TestCase):
    """L'ORDRE EST CELUI DU MOTEUR. L'autorité de certification vient avant ce
    qui s'enrôle auprès d'elle, et cette précédence est déclarée dans le plan de
    l'écosystème. Une seconde liste écrite dans le banc en dériverait le jour où
    le modèle déplace une application."""

    def test_the_order_of_the_engine_is_kept(self):
        """LA PROPRIÉTÉ : l'ordre est celui de la sortie, jamais un tri. Trié,
        « infra-dns-01 » passerait avant « infra-pki-01 » et la flotte
        réclamerait un certificat à une autorité pas encore debout."""
        self.assertEqual(
            ("infra-pki-01", "infra-dns-01"),
            B.lit_amorcage("infra-pki-01\ninfra-dns-01\n"),
        )

    def test_blank_lines_are_not_hosts(self):
        self.assertEqual(
            ("a-01", "b-01"), B.lit_amorcage("\na-01\n\n  \nb-01\n")
        )

    def test_naming_nothing_is_an_answer(self):
        self.assertEqual((), B.lit_amorcage(""))

    def test_an_unreadable_output_refuses(self):
        self.assertIsNone(B.lit_amorcage(None))

    def test_a_sentence_makes_the_whole_read_refuse(self):
        """Le script écrit ses erreurs sur CETTE sortie : une liste dont une
        entrée est une phrase ferait activer un hôte qui n'existe pas."""
        for sortie in (
            "infra-pki-01\nerreur: plan introuvable\n",
            "Refus: relancer avec INSTANCE=nom\n",
            "infra-pki-01\n../ailleurs\n",
        ):
            with self.subTest(sortie=sortie.strip()[:40]):
                self.assertIsNone(B.lit_amorcage(sortie))

    def test_a_name_twice_makes_the_read_refuse(self):
        """Une dérivation qui se répète ne sait plus ce qu'elle dérive."""
        self.assertIsNone(B.lit_amorcage("a-01\na-01\n"))


class TestLePlanSActivePourTousSesHotes(unittest.TestCase):
    """TOUT OU RIEN. Un plan où seul le premier des hôtes d'amorçage serait actif
    se déploie jusqu'à l'autorité de certification puis refuse — et la moitié
    faite a déjà créé des machines."""

    MODELE = (
        "serveurs:\n"
        "  infra-pki-01: { fonction: infra-pki, etat: planifie }\n"
        "  infra-dns-01: { fonction: infra-dns, etat: planifie }\n"
        "  infra-mail-01: { fonction: infra-mail, etat: planifie }\n"
    )

    def actifs(self, texte):
        lu = (yaml.safe_load(texte) or {}).get("serveurs") or {}
        return sorted(
            nom for nom, d in lu.items() if (d or {}).get("etat") == "actif"
        )

    def test_both_bootstrap_hosts_become_active(self):
        self.assertEqual(
            ["infra-dns-01", "infra-pki-01"],
            self.actifs(
                B.active_les_hotes(
                    self.MODELE, ("infra-pki-01", "infra-dns-01")
                )
            ),
        )

    def test_the_others_stay_planned(self):
        """Le reste de la flotte ne monte pas : `reconstruire` ne crée que les
        VM des hôtes ACTIFS, et le banc n'en veut que deux."""
        actifs = self.actifs(
            B.active_les_hotes(self.MODELE, ("infra-pki-01", "infra-dns-01"))
        )
        self.assertNotIn("infra-mail-01", actifs)

    def test_one_host_missing_activates_none(self):
        """Le refus porte sur le TEXTE ENTIER, non sur l'hôte fautif."""
        self.assertIsNone(
            B.active_les_hotes(self.MODELE, ("infra-pki-01", "n-existe-pas"))
        )

    def test_no_host_at_all_is_refused(self):
        """Un plan sans hôte actif fait sortir la flotte à zéro sans rien
        créer, et le moteur le dit : « aucun hote actif dans le plan »."""
        self.assertIsNone(B.active_les_hotes(self.MODELE, ()))


class TestLaBoucleEstCelleDuMoteur(unittest.TestCase):
    """Le banc ne recompose pas les morceaux de la reconstruction. Sans les flux
    d'abord, le dossier des règles dérivées est vide et le socle pose un pare-feu
    en refus par défaut SANS AUCUNE RÈGLE : la flotte monte, ssh répond depuis
    l'administration, et tout le reste est mur."""

    def rang(self, cible):
        return [e.cible for e in B.ETAPES_BOUCLE].index(cible)

    def test_nothing_is_razed_before_it_is_built(self):
        self.assertLess(self.rang("reconstruire"), self.rang("raser"))

    def test_the_inventory_is_applied_before_anything_is_built(self):
        """`reconstruire` ne crée que les VM des hôtes actifs de l'inventaire
        APPLIQUÉ : bâtir avant d'appliquer ne créerait rien."""
        for avant in ("instancier", "instancier-appliquer"):
            with self.subTest(cible=avant):
                self.assertLess(self.rang(avant), self.rang("reconstruire"))
        self.assertLess(
            self.rang("instancier"), self.rang("instancier-appliquer")
        )

    def test_only_the_two_building_gestures_confirm(self):
        """Un geste qui écrit le DIT. Confirmer une mesure la ferait écrire."""
        self.assertEqual(
            ["reconstruire", "raser"],
            [e.cible for e in B.ETAPES_BOUCLE if e.confirmer],
        )

    def test_razing_names_what_it_destroys(self):
        """Le quatrième verrou : le moteur refuse si l'écosystème nommé n'est
        pas celui qui est monté."""
        raser = next(e for e in B.ETAPES_BOUCLE if e.cible == "raser")
        self.assertIn((B.INSTANCE, B.ECOSYSTEME), raser.variables)

    def test_an_announced_duration_says_so(self):
        """Un plan qui confondrait relevé et annoncé promettrait un temps que
        personne n'a chronométré."""
        mesurees = {e.cible for e in B.ETAPES_BOUCLE if e.mesuree}
        self.assertEqual({"instancier", "instancier-appliquer"}, mesurees)

    def test_every_target_exists_in_the_engine(self):
        """LE GARDE QUI SURVIT À UN RENOMMAGE EN AMONT. Une cible disparue ferait
        échouer la boucle au milieu, après avoir créé des VM."""
        makefile = os.path.join(
            RACINE, "private", "repo", "Set-OPS-Public", "Makefile"
        )
        if not os.path.isfile(makefile):
            self.skipTest("le clone du moteur n'est pas là")
        with open(makefile, encoding="utf-8") as lu:
            texte = lu.read()
        for etape in B.ETAPES_BOUCLE:
            with self.subTest(cible=etape.cible):
                self.assertRegex(texte, rf"(?m)^{re.escape(etape.cible)}:")

    def test_the_search_would_miss_a_target_that_is_not_there(self):
        """Le contrôle positif : sans lui, une recherche qui trouve toujours
        passerait l'épreuve ci-dessus."""
        makefile = os.path.join(
            RACINE, "private", "repo", "Set-OPS-Public", "Makefile"
        )
        if not os.path.isfile(makefile):
            self.skipTest("le clone du moteur n'est pas là")
        with open(makefile, encoding="utf-8") as lu:
            texte = lu.read()
        self.assertNotRegex(texte, "(?m)^cible-qui-n-existe-pas:")

    def test_the_plan_marks_what_is_only_announced(self):
        dit = dict(B.plan((B.PASSE_ENV,), "un-terrain"))
        annonces = [
            quoi for quoi, duree in dit.items() if "annoncé" in (duree or "")
        ]
        self.assertEqual(
            len([e for e in B.ETAPES_BOUCLE if not e.mesuree]), len(annonces)
        )


class TestLArgvSshDeriveDuLabo(unittest.TestCase):
    """Un second jeu d'options dériverait du premier, et c'est l'option
    manquante qui pend une épreuve lancée pour des heures sans surveillance."""

    def base_du_labo(self):
        import install_nixos

        return install_nixos.ssh_base("un-terrain")

    def test_everything_the_lab_builds_is_kept_in_order(self):
        """LA PROPRIÉTÉ : ce que le labo pose est une SOUS-SUITE de ce que le
        banc joue. Une option perdue en chemin ne se verrait qu'à l'exécution."""
        argv = list(B.ssh_argv("un-terrain", "hostname"))
        reste = iter(argv)
        self.assertTrue(
            all(morceau in reste for morceau in self.base_du_labo()), argv
        )

    def test_the_check_would_catch_a_dropped_option(self):
        """Le contrôle positif : sans lui, une sous-suite vide passerait."""
        ampute = [m for m in self.base_du_labo() if m != "BatchMode=yes"]
        reste = iter(ampute)
        self.assertFalse(
            all(morceau in reste for morceau in self.base_du_labo())
        )

    def test_the_command_is_last_and_the_terrain_just_before_options_end(self):
        """ssh prend son hôte APRÈS ses options et sa commande APRÈS l'hôte.
        Inversés, l'hôte devient une commande ou la commande un hôte."""
        argv = list(B.ssh_argv("un-terrain", "hostname"))
        self.assertEqual("hostname", argv[-1])
        self.assertEqual("un-terrain", argv[-2])

    def test_it_refuses_without_a_terrain_or_a_command(self):
        for terrain, commande in (
            ("", "hostname"),
            ("   ", "hostname"),
            ("un-terrain", ""),
            ("un-terrain", "   "),
        ):
            with self.subTest(terrain=terrain, commande=commande):
                self.assertIsNone(B.ssh_argv(terrain, commande))


class TestUneSuiteVideNeReussitPas(unittest.TestCase):
    """Un constructeur de commandes qui ne peut pas bâtir refuse par une liste
    VIDE. Une suite vide qui rendrait « code 0, rien à signaler » ferait dire
    que le pont est posé quand il ne l'est pas."""

    def test_something_that_ran_and_returned_zero_succeeds(self):
        """Le contrôle positif : sans lui, un verdict qui refuse toujours
        passerait les refus ci-dessous."""
        self.assertTrue(B.Fait(0, "", 3).reussi)

    def test_an_empty_suite_does_not_succeed(self):
        self.assertFalse(B.Fait(0, "", 0).reussi)

    def test_a_launch_that_could_not_happen_does_not_succeed(self):
        self.assertFalse(B.Fait(None, "", 0).reussi)

    def test_a_non_zero_code_does_not_succeed(self):
        self.assertFalse(B.Fait(2, "raté", 1).reussi)

    def test_an_unusable_terrain_runs_nothing(self):
        """`jouees` dit où reprendre ; zéro dit que rien n'a été touché."""
        fait = B.joue_sur("", ["hostname", "reboot"], B.TEL_QUEL)
        self.assertEqual((None, 0), (fait.code, fait.jouees))


class TestLePlacementNommeLeGabaritTrouve(unittest.TestCase):
    """LE DÉFAUT D'ORIGINE, et il ne se voit qu'en bout de chaîne. Le VMID du
    placement venait du premier numéro LIBRE de la plage — libre PRÉCISÉMENT
    parce que le gabarit occupe celui d'avant. Le moteur refusait alors sur
    « aucun nœud ne détient le gabarit 9001 », sans jamais dire que le numéro
    venait de là.

    Les VMID et les noms sont inventés, et rien ne sort d'ici : l'exécuteur du
    terrain est remplacé.
    """

    CONFORME = "template: 1\nmachine: q35\nbios: ovmf\n"

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        self.moteur = os.path.join(self.d, "Moteur")
        os.makedirs(self.moteur)
        self.eco = os.path.join(self.d, B.ECOSYSTEME)
        os.makedirs(self.eco)

    def placement(self):
        chemin = os.path.join(
            self.eco, "inventories", B.INVENTAIRE_BANC, "group_vars",
            "proxmox.yml",
        )
        with open(chemin, encoding="utf-8") as fh:
            return fh.read()

    def joue(self, *suite):
        restes = list(suite)
        patch = mock.patch.object(
            B, "joue_sur", lambda *a, **k: restes.pop(0)
        )
        patch.start()
        self.addCleanup(patch.stop)

    def test_the_placement_names_the_vmid_the_name_found(self):
        """La grappe porte le gabarit en 9000 ; 9001 y est libre. C'est 9000
        que le clonage doit lire."""
        liste = json.dumps(
            [{"vmid": 100, "name": "autre", "type": "qemu"},
             {"vmid": 9000, "name": B.GABARIT, "type": "qemu"}]
        )
        self.joue(B.Fait(0, liste, 1), B.Fait(0, self.CONFORME, 1))
        vu = B.mesure_le_gabarit("un-terrain", B.ELEVE)
        mesures = B.Mesures(
            terrain="un-terrain", elevation=B.ELEVE,
            liens=(B.A_POSER, B.NOTRE), index_libre=True, pont="vmbr9",
            noeud="un-noeud", stockage="un-stockage", uplink="une-sortie",
            adresse_api="192.0.2.10",
        )
        self.assertEqual("", B.ecrit_le_placement(self.moteur, mesures, vu.vmid))
        texte = self.placement()
        self.assertIn("proxmox_clone_vmid_modele: 9000", texte)
        self.assertNotIn("9001", texte)

    def test_an_engine_with_no_sibling_refuses_rather_than_write(self):
        """La fédération se découvre par les dossiers FRÈRES du moteur : un
        chemin qui n'en a pas — vide, ou la racine — ne dit pas où écrire, et
        écrire au hasard poserait un placement que le moteur ne lit pas.

        « / » dépouillé de ses séparateurs est la chaîne vide, et une chaîne
        vide résolue rend le dossier COURANT : c'est le cas qui tranche.
        """
        mesures = B.Mesures(
            terrain="t", elevation=B.ELEVE, liens=(), index_libre=True,
            pont="vmbr9", noeud="n", stockage="s", uplink="u",
            adresse_api="192.0.2.10",
        )
        for moteur in ("", "   ", os.sep):
            with self.subTest(moteur=repr(moteur)):
                self.assertTrue(
                    B.ecrit_le_placement(moteur, mesures, 9000)
                )

    def test_an_unreadable_vmid_writes_nothing(self):
        """Fermé par défaut : un placement sans VMID donnerait au moteur une
        source qu'il ne sait pas chercher."""
        mesures = B.Mesures(
            terrain="t", elevation=B.ELEVE, liens=(), index_libre=True,
            pont="vmbr9", noeud="un-noeud", stockage="s", uplink="u",
            adresse_api="192.0.2.10",
        )
        self.assertTrue(B.ecrit_le_placement(self.moteur, mesures, 0))


class TestCeQueLeBancExigeDuGabarit(unittest.TestCase):
    """La même forme qu'un préalable, joué à un autre MOMENT : la pose faite.

    Son refus n'est donc pas « rien n'a été tenté » — le site est debout, et
    c'est justement lui qui rend la préparation du gabarit possible.
    """

    def test_a_conforming_template_holds(self):
        """Le contrôle positif : sans lui, refuser toujours passerait les
        refus ci-dessous."""
        self.assertTrue(B.exigence_du_gabarit(B.GABARIT_CONFORME).tenu)

    def test_anything_else_refuses_and_says_where_to_look(self):
        for etat in (
            B.GABARIT_ABSENT,
            B.GABARIT_MATERIEL,
            B.GABARIT_PAS_MODELE,
        ):
            with self.subTest(etat=etat):
                exige = B.exigence_du_gabarit(etat)
                self.assertFalse(exige.tenu)
                self.assertIn(B.PROCEDURE_GABARIT, exige.dit)

    def test_an_unread_state_is_not_a_refusal(self):
        """« Pas su regarder » envoie chercher la sonde, non la machine."""
        exige = B.exigence_du_gabarit(None)
        self.assertIsNone(exige.tenu)
        self.assertEqual("", exige.dit)

    def test_a_refusal_after_the_pose_is_not_tooling(self):
        """OUTILLAGE dit « RIEN n'a été tenté » : la pose faite, ce serait
        faux. C'est la boucle qui n'a pas joué, donc NON_CONCLUANTE."""
        for etat in (B.GABARIT_ABSENT, B.GABARIT_MATERIEL, None):
            with self.subTest(etat=etat):
                self.assertEqual(
                    B.SORTIE_NON_CONCLUANTE,
                    B.juge_le_gabarit(B.exigence_du_gabarit(etat)),
                )

    def test_a_conforming_template_lets_the_loop_go(self):
        """Le contrôle positif : sans lui, refuser toujours passerait le
        refus ci-dessus."""
        self.assertEqual(
            B.SORTIE_OK,
            B.juge_le_gabarit(B.exigence_du_gabarit(B.GABARIT_CONFORME)),
        )

    def test_it_names_the_template_the_cloning_looks_for(self):
        """C'est par le NOM que le clonage du moteur cherche sa source : un
        écran qui ne le dit pas laisse chercher lequel corriger."""
        self.assertIn(B.GABARIT, B.exigence_du_gabarit(B.GABARIT_ABSENT).quoi)


class TestLaRelectureDuGabaritSurLaGrappe(unittest.TestCase):
    """RELU sur la grappe, jamais repris d'une mesure d'avant-pose : entre les
    deux, l'exploitant a pu bâtir le gabarit, et une valeur gardée dirait le
    contraire de ce qui est là.

    Les VMID et les noms sont inventés, et l'élévation n'est pas jouée : rien
    ne sort d'ici.
    """

    CONFORME = "template: 1\nmachine: q35\nbios: ovmf\n"

    def joue(self, *suite):
        """Remplace l'exécuteur par une file de faits, et note ses argv."""
        self.vus = []
        restes = list(suite)

        def faux(terrain, cmds, elevation, delai=None):
            self.vus.append(list(cmds))
            return restes.pop(0)

        patch = mock.patch.object(B, "joue_sur", faux)
        patch.start()
        self.addCleanup(patch.stop)

    def liste(self, *paires):
        return json.dumps(
            [{"vmid": v, "name": n, "type": "qemu"} for v, n in paires]
        )

    def test_a_refused_listing_concludes_nothing_even_when_readable(self):
        """LE CAS QUI TRANCHE. Une commande en échec imprime parfois quelque
        chose de lisible — une bannière, une liste partielle. Juger sur sa
        sortie rendrait un verdict tiré d'un refus, et il se lirait comme un
        verdict tiré d'une réponse. C'est le CODE qui décide, pas le texte."""
        self.joue(B.Fait(1, self.liste((9000, B.GABARIT)), 1))
        self.assertEqual(
            B.VuGabarit(0, None), B.mesure_le_gabarit("un-terrain", B.ELEVE)
        )

    def test_a_command_that_never_ran_concludes_nothing(self):
        """Fermé par défaut : un ssh qui n'a pas tourné n'est pas une grappe
        sans gabarit."""
        self.joue(B.Fait(None, "", 0))
        self.assertEqual(
            B.VuGabarit(0, None), B.mesure_le_gabarit("un-terrain", B.ELEVE)
        )

    def test_an_unparsable_listing_concludes_nothing(self):
        self.joue(B.Fait(0, "pas du json", 1))
        self.assertEqual(
            B.VuGabarit(0, None), B.mesure_le_gabarit("un-terrain", B.ELEVE)
        )

    def test_no_vm_by_that_name_is_read_as_absent(self):
        self.joue(B.Fait(0, self.liste((100, "autre")), 1))
        self.assertEqual(
            B.VuGabarit(0, B.GABARIT_ABSENT),
            B.mesure_le_gabarit("un-terrain", B.ELEVE),
        )

    def test_an_unplayed_config_concludes_nothing(self):
        self.joue(
            B.Fait(0, self.liste((9000, B.GABARIT)), 1), B.Fait(1, "", 1)
        )
        # Le VMID est su, la conformité non : les deux se distinguent.
        self.assertEqual(
            B.VuGabarit(9000, None),
            B.mesure_le_gabarit("un-terrain", B.ELEVE),
        )

    def test_the_conformity_comes_from_the_config(self):
        self.joue(
            B.Fait(0, self.liste((9000, B.GABARIT)), 1),
            B.Fait(0, self.CONFORME, 1),
        )
        self.assertEqual(
            B.VuGabarit(9000, B.GABARIT_CONFORME),
            B.mesure_le_gabarit("un-terrain", B.ELEVE),
        )

    def test_the_config_read_is_that_of_the_vmid_the_name_found(self):
        """Le VMID vient de la LISTE, jamais d'un nombre écrit ici : lire la
        configuration d'une autre VM rendrait un verdict sur une autre
        machine, et il se lirait comme celui du gabarit."""
        self.joue(
            B.Fait(0, self.liste((100, "autre"), (9042, B.GABARIT)), 1),
            B.Fait(0, self.CONFORME, 1),
        )
        B.mesure_le_gabarit("un-terrain", B.ELEVE)
        self.assertIn("9042", " ".join(self.vus[1]))


class TestLeSecretNeTraverseNiEcranNiJournal(unittest.TestCase):
    """Le secret d'un jeton d'API ne s'affiche qu'à sa création : il traverse la
    mémoire du banc entre la grappe qui le rend et la voûte qui le chiffre, et
    un écran ou un journal qui l'attrape au passage le rend permanent."""

    SECRET = "un-secret-invente-pour-l-epreuve"

    def test_the_secret_is_gone_from_what_is_shown(self):
        montre = B.expurge(f"value: {self.SECRET}\nok", self.SECRET)
        self.assertNotIn(self.SECRET, montre)

    def test_every_occurrence_is_gone(self):
        """Un seul remplacement laisserait le second passage."""
        deux = f"{self.SECRET} puis encore {self.SECRET}"
        self.assertNotIn(self.SECRET, B.expurge(deux, self.SECRET))

    def test_the_rest_of_the_text_survives(self):
        """Le contrôle positif : sans lui, un expurgeur qui rendrait la chaîne
        vide passerait l'épreuve ci-dessus."""
        self.assertIn("ok", B.expurge(f"{self.SECRET}\nok", self.SECRET))

    def test_a_secret_with_spaces_around_it_is_still_removed(self):
        """Ce que la grappe rend porte une fin de ligne ; le comparer tel quel
        ne retrouverait pas la valeur dans le texte."""
        montre = B.expurge(f"value: {self.SECRET}", f"  {self.SECRET}\n")
        self.assertNotIn(self.SECRET, montre)

    def test_an_empty_secret_removes_nothing(self):
        """Remplacer la chaîne vide marquerait chaque caractère du texte."""
        for vide in ("", "   ", None):
            with self.subTest(secret=vide):
                self.assertEqual("un texte", B.expurge("un texte", vide))

    def test_an_empty_text_stays_empty(self):
        self.assertEqual("", B.expurge(None, self.SECRET))


class TestLesDeuxDepotsSontFreresDuMoteur(unittest.TestCase):
    """La fédération se découvre par les dossiers FRÈRES du moteur : ailleurs, le
    locataire du banc est invisible, et le moteur répond « aucun tenant fédéré
    découvert » — un refus dont la cause ne se lit nulle part."""

    MOTEUR = os.path.join("un", "chemin", "vers", "Moteur")

    def test_both_are_siblings_of_the_engine(self):
        _freres, site, eco = B.chemins_du_banc(self.MOTEUR)
        attendu = os.path.dirname(os.path.abspath(self.MOTEUR))
        self.assertEqual(attendu, os.path.dirname(site))
        self.assertEqual(attendu, os.path.dirname(eco))

    def test_neither_is_inside_the_engine(self):
        """Dedans, ils seraient suivis par le dépôt du moteur et vus par ses
        propres épreuves."""
        racine = os.path.abspath(self.MOTEUR)
        for chemin in B.chemins_du_banc(self.MOTEUR)[1:]:
            with self.subTest(chemin=chemin):
                self.assertFalse(chemin.startswith(racine + os.sep))

    def test_a_trailing_separator_changes_nothing(self):
        self.assertEqual(
            B.chemins_du_banc(self.MOTEUR),
            B.chemins_du_banc(self.MOTEUR + os.sep),
        )

    def test_it_refuses_what_has_no_sibling(self):
        for vu in ("", "   ", os.sep, os.sep * 3, None):
            with self.subTest(moteur=vu):
                self.assertIsNone(B.chemins_du_banc(vu))

    def test_the_answer_never_depends_on_the_working_directory(self):
        """LA PROPRIÉTÉ. Un chemin dépouillé de ses séparateurs peut être la
        chaîne VIDE, et une chaîne vide résolue rend le DOSSIER COURANT sans
        rien dire : le banc prendrait le répertoire de travail pour le moteur,
        y poserait ses liens et créerait ses dépôts à côté."""
        ailleurs = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, ailleurs, True)
        ici = os.getcwd()
        os.chdir(ailleurs)
        try:
            self.assertIsNone(B.chemins_du_banc(os.sep))
        finally:
            os.chdir(ici)

    def test_a_real_engine_path_still_answers(self):
        """Le contrôle positif : sans lui, une fonction qui refuse toujours
        passerait tous les refus ci-dessus."""
        self.assertIsNotNone(B.chemins_du_banc(self.MOTEUR))


class TestLesLiensSontRelatifsEtDesignentLeBonGenre(unittest.TestCase):
    """Le moteur résout `underlay.yml` pour en dériver le dépôt de l'hébergeur,
    et parcourt `instance` pour trouver le plan."""

    def test_both_targets_are_relative(self):
        """Un lien absolu pend dès que le checkout est déplacé, et il porte un
        chemin de compte — que rien dans un dépôt ne doit porter."""
        for nom, vise in B.cibles_des_liens():
            with self.subTest(nom=nom):
                self.assertFalse(os.path.isabs(vise), vise)

    def test_the_underlay_link_names_a_file(self):
        """Le moteur le résout PUIS prend son dossier parent pour trouver la
        grappe de l'hébergeur : pointé sur un dossier, il chercherait la grappe
        un niveau trop haut."""
        vise = dict(B.cibles_des_liens())[B.LIEN_UNDERLAY]
        self.assertTrue(vise.endswith("underlay.yml"), vise)

    def test_the_instance_link_names_the_tenant_directory(self):
        """Le moteur le parcourt pour trouver `plan/` : pointé sur un fichier,
        il chercherait un plan dans un fichier."""
        vise = dict(B.cibles_des_liens())[B.LIEN_INSTANCE]
        self.assertEqual(os.path.basename(vise), B.ECOSYSTEME)

    def test_the_two_names_are_exactly_the_two_the_engine_reads(self):
        """Ni plus ni moins : un troisième lien ne serait défait par rien."""
        self.assertEqual(
            sorted(B.LIENS), sorted(nom for nom, _v in B.cibles_des_liens())
        )

    def test_each_target_points_at_a_repository_of_the_bench(self):
        vises = dict(B.cibles_des_liens())
        self.assertIn(B.UNDERLAY_BANC, vises[B.LIEN_UNDERLAY])
        self.assertIn(B.ECOSYSTEME, vises[B.LIEN_INSTANCE])


class TestUnMontagePartielSeDitPartiel(unittest.TestCase):
    """Un montage interrompu porte quand même ses chemins, parce que c'est par
    eux qu'il se défait : rendre une absence sur un échec laisserait sur le
    disque ce que plus rien ne nomme."""

    def montage(self, **change):
        champs = dict(
            underlay="/f/SITE",
            ecosysteme="/f/OPS",
            liens=("/m/underlay.yml", "/m/instance"),
            cles=("/c/une", "/c/deux"),
            souci="",
        )
        champs.update(change)
        return B.Montage(**champs)

    def test_everything_posed_is_complete(self):
        """Le contrôle positif : sans lui, un « complet » toujours faux
        passerait les refus ci-dessous."""
        self.assertTrue(self.montage().complet)

    def test_a_trouble_makes_it_incomplete(self):
        self.assertFalse(self.montage(souci="le lien est occupé").complet)

    def test_a_missing_link_makes_it_incomplete(self):
        self.assertFalse(self.montage(liens=("/m/underlay.yml",)).complet)

    def test_a_missing_repository_makes_it_incomplete(self):
        for change in ({"underlay": ""}, {"ecosysteme": ""}):
            with self.subTest(**change):
                self.assertFalse(self.montage(**change).complet)

    def test_a_partial_mount_still_names_what_it_posed(self):
        """Ce qui reste à défaire est ce qu'il nomme, souci ou non."""
        partiel = self.montage(souci="arrêté", cles=())
        self.assertEqual("/f/SITE", partiel.underlay)
        self.assertEqual(2, len(partiel.liens))


class TestLIndexSePoseChirurgicalement(unittest.TestCase):
    """Tout l'adressage d'un écosystème dérive de ce seul entier, et le modèle
    livré en déclare un que deux bancs partageraient."""

    MODELE = (
        "---\n"
        "# un commentaire du modèle, qui doit survivre\n"
        "index: 1\n"
        "cidr_hote: 24\n"
        "reservations:\n"
        "  passerelle: 1\n"
    )

    def test_the_index_is_replaced(self):
        lu = yaml.safe_load(B.pose_index(self.MODELE, 211))
        self.assertEqual(211, lu["index"])

    def test_the_model_carries_another_one(self):
        """Le contrôle positif : sans lui, une fonction qui ne change rien
        passerait l'épreuve ci-dessus."""
        self.assertNotEqual(211, yaml.safe_load(self.MODELE)["index"])

    def test_nothing_else_changes(self):
        avant, apres = (
            self.MODELE.splitlines(),
            B.pose_index(self.MODELE, 211).splitlines(),
        )
        self.assertEqual(len(avant), len(apres))
        self.assertEqual(1, sum(1 for a, b in zip(avant, apres) if a != b))

    def test_a_nested_index_is_not_the_one(self):
        """Seul l'`index:` de PREMIER niveau est le seed. Un `index:` indenté
        appartient à autre chose, et le confondre déplacerait l'adressage."""
        imbrique = "reservations:\n  index: 3\n"
        self.assertIsNone(B.pose_index(imbrique, 211))

    def test_it_refuses_rather_than_guess(self):
        for texte, index in (
            ("cidr_hote: 24\n", 211),
            ("index: 1\nindex: 2\n", 211),
            (self.MODELE, "onze"),
            (self.MODELE, None),
            ("", 211),
        ):
            with self.subTest(texte=texte[:24], index=index):
                self.assertIsNone(B.pose_index(texte, index))


class TestLeMontageRefuseAvantDeRienCreer(unittest.TestCase):
    """Un lien occupé est celui d'un exploitant. Créer les deux dépôts PUIS
    refuser laisserait deux dossiers que rien ne nomme — et le montage suivant
    les retrouverait sans savoir d'où ils viennent."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        self.moteur = os.path.join(self.d, "Moteur")
        os.makedirs(self.moteur)

    def depots(self):
        """Les deux dépôts qui EXISTENT sous les frères du faux moteur."""
        return sorted(
            n
            for n in os.listdir(self.d)
            if n in (B.ECOSYSTEME, B.UNDERLAY_BANC)
        )

    def test_an_occupied_link_creates_nothing(self):
        """LA PROPRIÉTÉ : rien sur le disque après un refus."""
        os.symlink(
            "../le-depot-de-quelqu-un",
            os.path.join(self.moteur, B.LIEN_INSTANCE),
        )
        montage = B.monte_localement(
            self.moteur, "un-noeud", "vmbr9", "local-lvm", "192.0.2.10"
        )
        self.assertEqual([], self.depots())
        self.assertIn(B.LIEN_INSTANCE, montage.souci)
        self.assertFalse(montage.complet)

    def test_it_names_which_link_stopped_it(self):
        """Le souci DIT lequel : « un lien est occupé » laisse chercher."""
        os.symlink(
            "/ailleurs/underlay.yml",
            os.path.join(self.moteur, B.LIEN_UNDERLAY),
        )
        montage = B.monte_localement(
            self.moteur, "un-noeud", "vmbr9", "local-lvm", "192.0.2.10"
        )
        self.assertIn(B.LIEN_UNDERLAY, montage.souci)

    def test_a_directory_in_the_way_is_refused_too(self):
        """Un vrai dossier `instance/` est un checkout d'exploitant, pas un
        lien : l'effacer détruirait son plan."""
        os.makedirs(os.path.join(self.moteur, B.LIEN_INSTANCE))
        montage = B.monte_localement(
            self.moteur, "un-noeud", "vmbr9", "local-lvm", "192.0.2.10"
        )
        self.assertEqual([], self.depots())
        self.assertFalse(montage.complet)

    def test_an_engine_without_a_sibling_is_refused(self):
        montage = B.monte_localement(
            "", "un-noeud", "vmbr9", "local-lvm", "192.0.2.10"
        )
        self.assertFalse(montage.complet)
        self.assertEqual(("", "", (), ()), montage[:4])

    def test_it_never_raises_on_a_bare_engine(self):
        """Le contrôle positif des refus ci-dessus : un moteur SANS lien occupé
        va plus loin, et s'arrête sur ce qui manque vraiment — son modèle."""
        montage = B.monte_localement(
            self.moteur, "un-noeud", "vmbr9", "local-lvm", "192.0.2.10"
        )
        self.assertNotIn(B.LIEN_INSTANCE, montage.souci)
        self.assertNotIn(B.LIEN_UNDERLAY, montage.souci)
        self.assertTrue(montage.souci)

    def test_a_missing_node_or_bridge_stops_the_underlay(self):
        """`texte_underlay` refuse sans nœud ni pont, et l'écriture d'un texte
        vide n'est pas une écriture réussie."""
        montage = B.monte_localement(
            self.moteur, "", "vmbr9", "local-lvm", "192.0.2.10"
        )
        self.assertIn("underlay.yml", montage.souci)
        self.assertFalse(montage.complet)


class TestLAmorcageNeSeDevinePas(unittest.TestCase):
    """Il est LU chez le moteur, par la variable d'instance, avant que le lien
    soit posé : poser le lien d'abord obligerait à le retirer si l'amorçage
    refusait."""

    def test_it_refuses_without_an_engine_or_an_instance(self):
        for moteur, instance in (
            ("", "/une/instance"),
            ("/un/moteur", ""),
            ("   ", "   "),
        ):
            with self.subTest(moteur=moteur, instance=instance):
                self.assertIsNone(B.amorcage_du_plan(moteur, instance))

    def test_an_engine_that_is_not_one_refuses(self):
        """Une instance sans plan fait sortir le dérivateur en erreur, et le
        lecteur rend None plutôt qu'une liste vide : « aucun hôte » et « pas su
        demander » ne commandent pas la même suite."""
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        self.assertIsNone(B.amorcage_du_plan(d, d))


class TestOnNeJouePasSansAvoirDecideComment(unittest.TestCase):
    """Les outils d'un hyperviseur vivent dans `/usr/sbin`, que le PATH d'une
    session ssh non interactive ne porte pas, et son démon de grappe ne parle
    qu'à root. Jouée sans élévation, une commande ne dit pas « refusé » : elle
    dit « commande introuvable », ou se plaint de son canal de communication —
    un diagnostic qui envoie chercher un démon en panne là où il n'y a qu'un
    compte sans droits."""

    def sonde(self, uid, sudo):
        return f"uid={uid}\nsudo={sudo}\n"

    def test_root_plays_as_is(self):
        self.assertEqual(B.TEL_QUEL, B.lit_elevation(self.sonde(0, "non")))

    def test_a_plain_account_with_passwordless_sudo_is_elevated(self):
        self.assertEqual(B.ELEVE, B.lit_elevation(self.sonde(1000, "oui")))

    def test_a_plain_account_without_it_is_impossible(self):
        """Distingué de « pas su lire » : une session sans terminal ne peut pas
        taper un mot de passe, et un sudo interactif n'échoue pas — il ATTEND,
        et l'épreuve pend jusqu'à sa borne."""
        self.assertEqual(
            B.IMPOSSIBLE, B.lit_elevation(self.sonde(1000, "non"))
        )

    def test_half_a_probe_concludes_nothing(self):
        """Les DEUX lignes sont exigées : conclure sur la moitié de la réponse
        ferait jouer toute la suite sans droits."""
        for sortie in ("uid=1000\n", "sudo=oui\n", "", "bruit sans rapport\n"):
            with self.subTest(sortie=sortie.strip()):
                self.assertIsNone(B.lit_elevation(sortie))

    def test_an_answer_outside_the_vocabulary_concludes_nothing(self):
        for sortie in (
            self.sonde("abc", "oui"),
            self.sonde(1000, "peut-etre"),
            self.sonde("", "oui"),
        ):
            with self.subTest(sortie=sortie.strip()):
                self.assertIsNone(B.lit_elevation(sortie))

    def test_every_answer_is_in_the_closed_vocabulary_or_none(self):
        for uid in (0, 1000):
            for sudo in ("oui", "non"):
                with self.subTest(uid=uid, sudo=sudo):
                    self.assertIn(
                        B.lit_elevation(self.sonde(uid, sudo)), B.ELEVATIONS
                    )

    def test_nothing_runs_without_a_decision(self):
        """LA PROPRIÉTÉ : `jouees` vaut zéro. Refuser en ayant joué la première
        commande laisserait le terrain à moitié touché."""
        for elevation in (None, "", "peut-etre", B.IMPOSSIBLE):
            with self.subTest(elevation=elevation):
                fait = B.joue_sur("un-terrain", ["hostname"], elevation)
                self.assertEqual((None, 0), (fait.code, fait.jouees))

    def test_a_decided_elevation_does_let_it_try(self):
        """Le contrôle positif : sans lui, un exécuteur qui refuse toujours
        passerait les refus ci-dessus. Le terrain est inventé, donc ssh échoue —
        mais il a été LANCÉ, ce que `jouees` dit."""
        fait = B.joue_sur(
            "un-terrain-invente.invalid", ["true"], B.TEL_QUEL, delai=30
        )
        self.assertEqual(1, fait.jouees)

    def test_elevating_wraps_the_whole_command(self):
        """« sudo sh -c '<tout>' » et non « sudo <tout> » : une commande du banc
        est souvent une SUITE, et préfixer n'élèverait que son premier mot."""
        suite = "a && b | c > d"
        argv = B.ssh_argv("un-terrain", suite, B.ELEVE)
        self.assertNotIn(suite, argv)
        self.assertEqual(1, sum(1 for m in argv if suite in m))

    def test_playing_as_is_wraps_nothing(self):
        """Le contrôle positif du précédent."""
        self.assertIn(
            "hostname", B.ssh_argv("un-terrain", "hostname", B.TEL_QUEL)
        )

class TestLePlacementNommeLePontDuBanc(unittest.TestCase):
    """Le générateur d'inventaire pose un pont par hôte quand la fabric a une
    SDN. Sans SDN il ne pose rien, et le clonage retombe sur cette valeur — qui
    vaut `vmbr0` par défaut. Une carte étiquetée sur un pont qui n'est pas
    conscient des VLAN démarre et reste injoignable, et la panne ne se voit ni à
    la création, ni dans un code de retour."""

    def lu(self, **change):
        champs = dict(
            noeud="un-noeud",
            stockage="un-stockage",
            pont="vmbr9",
            vmid_modele=9001,
        )
        champs.update(change)
        return yaml.safe_load(B.texte_placement(**champs) or "") or {}

    def test_the_bridge_of_the_bench_is_named(self):
        self.assertEqual("vmbr9", self.lu()["proxmox_clone_pont"])

    def test_the_default_would_be_another_bridge(self):
        """Le contrôle positif : sans lui, un fichier qui ne nommerait aucun
        pont passerait l'épreuve ci-dessus."""
        self.assertNotEqual("vmbr0", self.lu()["proxmox_clone_pont"])

    def test_the_three_placement_keys_are_there(self):
        """Elles NOMMENT des objets de l'hébergeur mais appartiennent au
        locataire, parce que c'est lui qui choisit où se poser."""
        lu = self.lu()
        for cle in (
            "proxmox_clone_noeud",
            "proxmox_clone_stockage",
            "proxmox_clone_vmid_modele",
        ):
            with self.subTest(cle=cle):
                self.assertIn(cle, lu)

    def test_no_addressing_is_written_here(self):
        """Tout l'adressage dérive du seul index du plan : l'écrire ici le
        figerait, et l'écosystème ne se déplacerait plus d'une fabric à
        l'autre."""
        lu = self.lu()
        for cle in ("proxmox_vmid", "ansible_host", "proxmox_cidr", "index"):
            with self.subTest(cle=cle):
                self.assertNotIn(cle, lu)

    def test_the_template_name_is_the_one_the_bench_captures(self):
        """Un nom qui ne correspond pas se solde par un clonage qui ne trouve
        pas sa source."""
        self.assertEqual(B.GABARIT, self.lu()["proxmox_clone_source_nom"])

    def test_it_refuses_a_missing_piece(self):
        for change in (
            {"noeud": ""},
            {"stockage": ""},
            {"pont": ""},
            {"gabarit": ""},
            {"vmid_modele": 0},
            {"vmid_modele": -1},
            {"vmid_modele": "pas un nombre"},
            {"vmid_modele": None},
        ):
            with self.subTest(**change):
                champs = dict(
                    noeud="n", stockage="s", pont="p", vmid_modele=9001
                )
                champs.update(change)
                self.assertEqual("", B.texte_placement(**champs))

    def test_a_valid_set_still_writes(self):
        """Le contrôle positif des refus ci-dessus."""
        self.assertNotEqual("", B.texte_placement("n", "s", "p", 9001))

    def test_the_bench_fills_only_one_inventory(self):
        """Le moteur prend le PREMIER qui existe parmi lab, principal,
        production, et son générateur crée production : en renseigner un autre
        en ferait deux, et le premier gagnerait sur celui qui est tenu à jour."""
        self.assertEqual("production", B.INVENTAIRE_BANC)


class TestLeSecretNeTouchePasLeDisque(unittest.TestCase):
    """La grappe n'affiche le secret d'un jeton qu'à sa création et ne le
    redonne jamais. Il ne va qu'à deux endroits — l'environnement d'un geste, ou
    l'outil qui le chiffre — et rien ne le journalise en chemin."""

    def identite(self, etiquette="une-etiquette", cle="/config/une-cle"):
        from script.setops.vaults import Identite

        return Identite(etiquette, cle)

    def test_the_plaintext_comes_from_standard_input(self):
        """LA PROPRIÉTÉ : la source est « - ». Chiffrer un fichier posé en clair
        laisserait le secret dans les blocs libérés et dans toute sauvegarde
        prise entre les deux gestes."""
        argv = B.argv_chiffrer("/f/underlay.vault.yml", self.identite())
        self.assertEqual("-", argv[-1])

    def test_no_secret_is_ever_on_the_command_line(self):
        """Une ligne de commande se lit dans la table des processus de la
        machine, par n'importe quel compte."""
        argv = B.argv_chiffrer("/f/v.yml", self.identite())
        for morceau in argv:
            with self.subTest(morceau=morceau):
                self.assertNotIn("SECRET", morceau.upper())

    def test_the_label_travels_with_its_key(self):
        """C'est par l'étiquette inscrite dans l'en-tête que le moteur retrouve
        laquelle de ses clés ouvre le fichier."""
        argv = B.argv_chiffrer("/f/v.yml", self.identite("etiq", "/c/k"))
        self.assertIn("etiq@/c/k", argv)

    def test_it_refuses_a_half_identity(self):
        for identite in (
            None,
            self.identite("", "/c/k"),
            self.identite("etiq", ""),
            self.identite("   ", "/c/k"),
        ):
            with self.subTest(identite=identite):
                self.assertIsNone(B.argv_chiffrer("/f/v.yml", identite))

    def test_it_refuses_without_a_vault_to_write(self):
        for chemin in ("", "   ", None):
            with self.subTest(chemin=chemin):
                self.assertIsNone(B.argv_chiffrer(chemin, self.identite()))

    def test_a_complete_pair_does_build(self):
        """Le contrôle positif : sans lui, un constructeur qui refuse toujours
        passerait les refus ci-dessus."""
        self.assertIsNotNone(B.argv_chiffrer("/f/v.yml", self.identite()))

    def atelier(self):
        """Un dossier jetable, sa clé de voûte, et le chemin d'une voûte.

        UNE VRAIE CLÉ ET UN CHEMIN ÉCRIVABLE : avec un chemin inventé, le
        scellement échoue parce qu'il ne peut pas écrire, et l'épreuve passerait
        pour la mauvaise raison — elle ne mesurerait plus le refus du secret
        vide mais l'absence du dossier.
        """
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        cle = os.path.join(d, "cle")
        with open(cle, "w", encoding="utf-8") as ecrit:
            ecrit.write("une-phrase-de-passe-inventee\n")
        return (
            d,
            self.identite("etiq-inventee", cle),
            os.path.join(d, B.VOUTE_UNDERLAY),
        )

    def test_sealing_nothing_writes_no_vault(self):
        """LA PROPRIÉTÉ : aucun fichier. Une chaîne vide dit que la lecture du
        jeton a échoué ; sceller quand même écrirait une voûte VALIDE portant un
        secret vide — elle s'ouvrirait parfaitement, et la grappe répondrait 401
        sans que rien n'explique pourquoi."""
        d, identite, voute = self.atelier()
        for secret in ("", "   ", None):
            with self.subTest(secret=secret):
                self.assertTrue(B.scelle_jeton(voute, identite, secret, d))
                self.assertFalse(os.path.exists(voute))

    def test_a_real_secret_does_write_one(self):
        """Le contrôle positif : sans lui, un scellement qui n'écrit jamais rien
        passerait l'épreuve ci-dessus. L'épreuve saute là où l'outil de voûte
        n'est pas posé."""
        d, identite, voute = self.atelier()
        if not shutil.which(
            B.OUTIL_VOUTE, path=B.env_ansible(RACINE).get("PATH", "")
        ):
            self.skipTest("l'outil de voûte n'est pas posé")
        souci = B.scelle_jeton(
            voute, identite, "UN-SECRET-INVENTE-POUR-L-EPREUVE", d
        )
        self.assertEqual("", souci)
        with open(voute, encoding="utf-8") as lu:
            self.assertTrue(lu.readline().startswith("$ANSIBLE_VAULT"))

    def test_the_vault_it_names_is_the_one_the_engine_looks_for(self):
        """Le moteur la cherche à côté d'`underlay.yml`, dans le dépôt de
        l'hébergeur."""
        self.assertEqual("underlay.vault.yml", B.VOUTE_UNDERLAY)

    def test_the_token_id_is_not_the_composed_form(self):
        """Le client d'API recompose « utilisateur!nom » ; la forme déjà
        composée produit un 401 que le même jeton contredit en HTTP direct."""
        self.assertNotIn("!", B.JETON_API)

    def test_a_failed_read_yields_no_secret(self):
        """`lire_jeton` rend « » plutôt qu'un secret tronqué, qui rendrait un
        401 que rien n'explique. Le terrain est inventé, donc ssh échoue."""
        self.assertEqual(
            "", B.lire_jeton("un-terrain-invente.invalid", B.TEL_QUEL)
        )


class TestLeReseauDuBancNestPasCeluiDuLabo(unittest.TestCase):
    """Le labo pose son pont interne en 10.10.10.1/24. Sur un plancher où il l'a
    déjà fait, un banc qui reprendrait ce réseau y dupliquerait l'adresse de la
    passerelle, et les deux ponts se disputeraient le trafic."""

    def test_it_differs_from_the_lab_internal_network(self):
        import sys

        sys.path.insert(0, RACINE)
        from script.proxmox import proxmox_deploy as pve

        self.assertNotEqual(pve.INTERNAL_CIDR, B.CIDR_PONT_BANC)

    def test_it_stays_out_of_the_class_a_the_tenants_derive_from(self):
        """L'adressage d'un locataire y dérive tout son supernet de son index :
        une fabrication posée dans la même classe A pourrait y tomber."""
        import ipaddress

        reseau = ipaddress.ip_interface(B.CIDR_PONT_BANC).network
        self.assertFalse(reseau.subnet_of(ipaddress.ip_network("10.0.0.0/8")))

    def test_it_is_a_private_network(self):
        import ipaddress

        self.assertTrue(ipaddress.ip_interface(B.CIDR_PONT_BANC).is_private)


class TestLeBancMesureSonGabaritSansLeFabriquer(unittest.TestCase):
    """Sa procédure impose une installation depuis l'ISO : une machine NAÎT en
    q35 ou ne le sera jamais proprement. Convertir le chipset sous un système
    installé remplace son matériel virtuel, et chacune des pannes qui s'ensuivent
    ressemble à autre chose qu'à sa cause."""

    def ressources(self, *paires):
        return json.dumps(
            [{"vmid": v, "name": n, "type": "qemu"} for v, n in paires]
        )

    def test_the_template_is_found_by_its_exact_name(self):
        """C'est par le nom que le clonage du moteur cherche sa source, et « un
        nom qui ne correspond pas se solde par un clonage qui ne trouve rien »."""
        self.assertEqual(
            9000,
            B.lit_gabarit(self.ressources((100, "autre"), (9000, B.GABARIT))),
        )

    def test_a_name_that_merely_contains_ours_is_not_ours(self):
        self.assertEqual(
            0, B.lit_gabarit(self.ressources((1, B.GABARIT + "-bis")))
        )

    def test_no_template_of_that_name_is_a_zero_not_a_refusal(self):
        """Zéro dit « aucune », ce qui est une réponse ; None dirait « pas su
        lire », et les deux ne commandent pas la même suite."""
        self.assertEqual(0, B.lit_gabarit(self.ressources((100, "autre"))))

    def test_two_vms_of_the_same_name_refuse(self):
        """Le clonage ne saurait pas laquelle prendre, et choisir pour lui serait
        deviner."""
        self.assertIsNone(
            B.lit_gabarit(self.ressources((1, "g"), (2, "g")), "g")
        )

    def test_an_unreadable_listing_refuses(self):
        for sortie in ("ipcc_send_rec failed", "", None, '{"vmid": 1}'):
            with self.subTest(sortie=str(sortie)[:24]):
                self.assertIsNone(B.lit_gabarit(sortie))

    def test_a_bad_vmid_refuses(self):
        for entree in (
            '[{"vmid": "9000", "name": "g"}]',
            '[{"vmid": 0, "name": "g"}]',
            '[{"vmid": true, "name": "g"}]',
        ):
            with self.subTest(entree=entree):
                self.assertIsNone(B.lit_gabarit(entree, "g"))

    def test_a_missing_key_means_the_default_not_the_unknown(self):
        """LA PROPRIÉTÉ. `qm config` n'imprime que ce qui DIFFÈRE du défaut, et
        les défauts sont justement le chipset PCI et le micrologiciel hérité que
        la procédure refuse. Une clé absente dit donc « c'est le défaut »."""
        for config in (
            "template: 1\nbios: ovmf\n",
            "template: 1\nmachine: q35\n",
            "template: 1\n",
        ):
            with self.subTest(config=config.replace("\n", "|")):
                self.assertEqual(
                    B.GABARIT_MATERIEL, B.lit_conformite_gabarit(config)
                )

    def test_a_living_vm_is_not_a_template(self):
        """Cloner une VM vivante n'est pas la même opération, et le moteur
        suppose un modèle."""
        self.assertEqual(
            B.GABARIT_PAS_MODELE,
            B.lit_conformite_gabarit("machine: q35\nbios: ovmf\nname: g\n"),
        )

    def test_the_right_hardware_on_a_template_conforms(self):
        """Le contrôle positif : sans lui, une lecture qui refuse toujours
        passerait tous les refus ci-dessus."""
        self.assertEqual(
            B.GABARIT_CONFORME,
            B.lit_conformite_gabarit(
                "template: 1\nmachine: q35\nbios: ovmf\nname: g\n"
            ),
        )

    def test_an_empty_config_concludes_nothing(self):
        for sortie in ("", "   ", None):
            with self.subTest(sortie=repr(sortie)):
                self.assertIsNone(B.lit_conformite_gabarit(sortie))

    def test_every_answer_is_in_the_closed_vocabulary(self):
        for config in (
            "template: 1\nmachine: q35\nbios: ovmf\n",
            "template: 1\nmachine: i440fx\nbios: ovmf\n",
            "machine: q35\nbios: ovmf\n",
        ):
            with self.subTest(config=config.replace("\n", "|")):
                self.assertIn(
                    B.lit_conformite_gabarit(config), B.ETATS_GABARIT
                )

    def test_every_refusal_says_where_the_making_is_described(self):
        """Le banc ne fabrique pas le gabarit : il doit donc dire où sa
        fabrication est décrite, sans quoi « non conforme » laisse chercher."""
        for etat in B.ETATS_GABARIT:
            if etat == B.GABARIT_CONFORME:
                continue
            with self.subTest(etat=etat):
                self.assertIn(B.PROCEDURE_GABARIT, B.dit_gabarit(etat))

    def test_a_conforming_template_says_nothing(self):
        self.assertEqual("", B.dit_gabarit(B.GABARIT_CONFORME))

    def test_the_procedure_it_cites_exists_in_the_engine(self):
        """LE GARDE CONTRE UN RENOMMAGE EN AMONT : un refus qui renvoie à une
        page disparue est un refus sans issue."""
        moteur = os.path.join(RACINE, "private", "repo", "Set-OPS-Public")
        if not os.path.isdir(moteur):
            self.skipTest("le clone du moteur n'est pas là")
        self.assertTrue(
            os.path.isfile(os.path.join(moteur, B.PROCEDURE_GABARIT)),
            B.PROCEDURE_GABARIT,
        )

    def test_the_check_would_catch_a_page_that_is_not_there(self):
        """Le contrôle positif du précédent."""
        moteur = os.path.join(RACINE, "private", "repo", "Set-OPS-Public")
        if not os.path.isdir(moteur):
            self.skipTest("le clone du moteur n'est pas là")
        self.assertFalse(
            os.path.isfile(
                os.path.join(moteur, "docs/page-qui-n-existe-pas.md")
            )
        )


def inventaire_de(*hotes):
    """Un inventaire généré, réduit à ses hôtes actifs et leurs variables."""
    return {
        "all": {
            "children": {
                B.GROUPE_ACTIFS: {
                    "hosts": {nom: variables for nom, variables in hotes}
                }
            }
        }
    }


def hote_actif(vlan=3114, passerelle="10.211.19.1", cidr=24, **reste):
    champs = {
        "proxmox_vlan": vlan,
        "proxmox_passerelle": passerelle,
        "proxmox_cidr": cidr,
    }
    champs.update(reste)
    return {c: v for c, v in champs.items() if v is not None}


class TestLesZonesSeDerivnentDeLInventaire(unittest.TestCase):
    """C'est le moteur qui tire la VLAN et la passerelle de chaque zone du seul
    index du plan. Une seconde dérivation écrite dans le banc divergerait de la
    sienne le jour où sa règle change, et le banc routerait des domaines où
    personne n'habite."""

    def test_one_zone_per_distinct_tag(self):
        zones = B.zones_a_router(
            inventaire_de(("a", hote_actif()), ("b", hote_actif()))
        )
        self.assertEqual([B.Zone(3114, "10.211.19.1/24")], list(zones))

    def test_two_tags_give_two_zones(self):
        zones = B.zones_a_router(
            inventaire_de(
                ("a", hote_actif()),
                ("b", hote_actif(vlan=3111, passerelle="10.211.16.1")),
            )
        )
        self.assertEqual(2, len(zones))

    def test_the_gateway_carries_its_prefix(self):
        """Sans préfixe, la dérivation le suppose à /32 et l'interface monte
        sans masque."""
        zone = B.zones_a_router(inventaire_de(("a", hote_actif())))[0]
        self.assertEqual("10.211.19.1/24", zone.cidr)

    def test_a_host_missing_one_value_refuses_everything(self):
        """Router une zone sur deux laisse la moitié de la flotte injoignable, et
        rien dans l'inventaire ne dira laquelle : le déploiement échouera sur un
        hôte qui « ne répond pas »."""
        for absent in ("proxmox_vlan", "proxmox_passerelle", "proxmox_cidr"):
            with self.subTest(absent=absent):
                self.assertIsNone(
                    B.zones_a_router(
                        inventaire_de(
                            (
                                "a",
                                hote_actif(
                                    **{
                                        {
                                            "proxmox_vlan": "vlan",
                                            "proxmox_passerelle": "passerelle",
                                            "proxmox_cidr": "cidr",
                                        }[absent]: None
                                    }
                                ),
                            )
                        )
                    )
                )

    def test_a_tag_that_is_not_an_integer_refuses(self):
        for vlan in ("3114", True, 3.5, None):
            with self.subTest(vlan=vlan):
                self.assertIsNone(
                    B.zones_a_router(
                        inventaire_de(("a", hote_actif(vlan=vlan)))
                    )
                )

    def test_a_prefix_that_is_not_a_number_refuses(self):
        self.assertIsNone(
            B.zones_a_router(inventaire_de(("a", hote_actif(cidr="vingt"))))
        )

    def test_no_active_host_is_an_answer(self):
        """Il n'y a rien à router, ce qui n'est pas la même nouvelle que « on n'a
        pas su lire »."""
        self.assertEqual((), B.zones_a_router(inventaire_de()))
        self.assertEqual((), B.zones_a_router({"all": {"children": {}}}))

    def test_something_that_is_not_an_inventory_refuses(self):
        for lu in ("du texte", [], None, {"all": "pas un dict"}):
            with self.subTest(lu=str(lu)[:20]):
                self.assertIsNone(B.zones_a_router(lu))

    def test_a_real_inventory_does_yield_a_zone(self):
        """Le contrôle positif : sans lui, un lecteur qui refuse toujours
        passerait tous les refus ci-dessus."""
        self.assertEqual(
            1, len(B.zones_a_router(inventaire_de(("a", hote_actif()))))
        )

    def test_an_unreadable_file_yields_nothing(self):
        self.assertIsNone(B.lit_inventaire("/n-existe-pas-du-tout.yml"))

    def test_the_commands_come_from_the_module_that_knows(self):
        """Une seconde strophe écrite dans le banc perdrait les leçons du
        montage à distance une à une."""
        cmds = B.cmds_svi(B.Zone(3114, "10.211.19.1/24"), "vmbr9")
        self.assertIn("mkdir -p /run/network", cmds[-1])
        self.assertIn("type vlan id 3114", cmds[-1])

    def test_no_zone_or_no_bridge_builds_nothing(self):
        for zone, pont in (
            (None, "vmbr9"),
            (B.Zone(3114, "10.211.19.1/24"), ""),
            (B.Zone(1, "10.211.19.1/24"), "vmbr9"),
        ):
            with self.subTest(zone=zone, pont=pont):
                self.assertEqual([], B.cmds_svi(zone, pont))


class TestLesInterfacesDeVlanSeDefontAvantLeurPont(unittest.TestCase):
    """Retirer le pont d'abord laisse des strophes qui nomment un parent
    disparu, et le montage des interfaces s'en plaint à chaque démarrage de
    l'hôte sans que rien ne dise d'où elles viennent."""

    def gestes(self, **change):
        return B.a_defaire(empreinte_pleine(zones=(3111, 3114), **change))

    def rangs(self, gestes):
        return {
            genre: max(i for i, g in enumerate(gestes) if g.genre == genre)
            for genre in {g.genre for g in gestes}
        }

    def test_each_zone_gets_its_own_gesture(self):
        """Chacune a sa propre strophe : retirer celle du pont ne les emporte
        pas."""
        vlans = [g.nom for g in self.gestes() if g.genre == B.SVI]
        self.assertEqual({"3111", "3114"}, set(vlans))

    def test_they_go_before_the_bridge(self):
        rangs = self.rangs(self.gestes())
        self.assertLess(rangs[B.SVI], rangs[B.PONT])

    def test_the_gesture_names_the_interface_not_just_the_tag(self):
        """C'est le nom complet que le retrait apparie, par champ exact."""
        vises = [g.vise for g in self.gestes() if g.genre == B.SVI]
        self.assertEqual({"vmbr9.3111", "vmbr9.3114"}, set(vises))

    def test_no_bridge_means_no_vlan_interface_to_undo(self):
        """Sans pont, aucune interface de VLAN n'a pu être posée : en nommer
        une ferait annoncer un retrait qui n'a pas lieu."""
        self.assertEqual(
            [], [g for g in self.gestes(pont="") if g.genre == B.SVI]
        )

    def test_a_footprint_naming_no_zone_names_none(self):
        """Le contrôle positif : sans lui, un ordre qui nomme toujours une
        interface passerait l'épreuve ci-dessus."""
        gestes = B.a_defaire(empreinte_pleine(zones=()))
        self.assertEqual([], [g for g in gestes if g.genre == B.SVI])
        self.assertNotEqual([], gestes)

    def test_a_tag_outside_the_standard_refuses_the_footprint(self):
        """Une étiquette hors de la plage 802.1Q ne nomme aucune interface : le
        geste porterait sur un nom qui n'existe pas, et l'écran annoncerait un
        retrait qui n'a pas eu lieu."""
        for zones in (
            [1],
            [0],
            [4095],
            [9999],
            ["3114"],
            [True],
            [3114, 3114],
        ):
            with self.subTest(zones=zones):
                texte = json.loads(
                    B.ecrit_empreinte(empreinte_pleine(zones=(3114,)))
                )
                texte["zones"] = zones
                self.assertIsNone(B.lit_empreinte(json.dumps(texte)))

    def test_a_footprint_of_the_bench_reads_its_zones_back(self):
        """Le contrôle positif des refus ci-dessus."""
        empreinte = empreinte_pleine(zones=(3111, 3114))
        self.assertEqual(
            (3111, 3114), B.lit_empreinte(B.ecrit_empreinte(empreinte)).zones
        )

    def test_the_plan_announces_them_before_anything_is_created(self):
        dit = " ".join(
            quoi for quoi, _d in B.plan((B.PASSE_ENV,), "un-terrain")
        )
        self.assertIn("interface routée", dit)


def mesures_bonnes(**change):
    """Des mesures où tout est tenu, que chaque épreuve altère d'un champ."""
    champs = dict(
        terrain="un-terrain",
        elevation=B.ELEVE,
        liens=(B.A_POSER, B.NOTRE),
        index_libre=True,
        pont="vmbr9",
        noeud="un-noeud",
        stockage="un-stockage",
        uplink="une-sortie",
        adresse_api="192.0.2.10",
    )
    champs.update(change)
    return B.Mesures(**champs)


class TestLesDepotsDuBancNeSeReserventPasAEuxMemes(unittest.TestCase):
    """Ils portent l'index par construction dès le premier montage. Les compter
    ferait refuser toute exécution suivante, et le banc ne tournerait qu'une
    fois — c'est la même distinction que pour ses liens : « déjà à nous » n'est
    pas « occupé »."""

    def test_our_own_repository_does_not_reserve_the_index(self):
        for nom in (B.ECOSYSTEME, B.UNDERLAY_BANC):
            with self.subTest(nom=nom):
                self.assertIs(
                    True,
                    B.index_libre(
                        [{"nom": nom, "index": B.INDEX_ECOSYSTEME}],
                        B.INDEX_ECOSYSTEME,
                    ),
                )

    def test_a_third_party_holding_it_still_blocks(self):
        """Le contrôle positif : sans lui, un garde qui accorde toujours
        passerait l'épreuve ci-dessus."""
        self.assertIs(
            False,
            B.index_libre(
                [{"nom": "OPS-Un-Autre", "index": B.INDEX_ECOSYSTEME}],
                B.INDEX_ECOSYSTEME,
            ),
        )

    def test_an_entry_without_a_name_still_reserves(self):
        """Ne pas savoir à qui appartient un dépôt n'autorise pas à le
        recouvrir."""
        self.assertIs(
            False,
            B.index_libre([{"index": B.INDEX_ECOSYSTEME}], B.INDEX_ECOSYSTEME),
        )


class TestLesPrealablesJugentSansMesurer(unittest.TestCase):
    """PURE : elle ne mesure rien, elle juge des mesures. C'est ce qui rend
    l'ordre des refus éprouvable sans machine, et ce qui fait qu'un refus
    s'explique de la même façon quel que soit le terrain."""

    def test_everything_held_lets_it_go_on(self):
        """Le contrôle positif de tous les refus ci-dessous."""
        self.assertEqual(B.SORTIE_OK, B.juge(B.prealables(mesures_bonnes())))

    def test_each_missing_measure_stops_it(self):
        for change in (
            {"terrain": ""},
            {"elevation": B.IMPOSSIBLE},
            {"liens": (B.OCCUPE, B.NOTRE)},
            {"index_libre": False},
            {"pont": ""},
            {"noeud": ""},
            {"stockage": ""},
            {"uplink": ""},
            {"adresse_api": ""},
        ):
            with self.subTest(**change):
                self.assertEqual(
                    B.SORTIE_OUTILLAGE,
                    B.juge(B.prealables(mesures_bonnes(**change))),
                )

    def test_an_unmeasured_condition_is_not_a_refusal(self):
        """« Pas su regarder » se distingue de « non » : l'écran doit envoyer
        chercher la sonde, non la machine."""
        for champ in ("elevation", "index_libre"):
            with self.subTest(champ=champ):
                vus = B.prealables(mesures_bonnes(**{champ: None}))
                inconnus = [p for p in vus if p.tenu is None]
                self.assertEqual(1, len(inconnus))

    def test_the_template_is_not_one_of_them(self):
        """LE GABARIT EST UN ARTEFACT DU SITE : la préparation que le moteur
        lui applique exige un serveur d'artefacts et un résolveur que le plan
        du site déclare, et le site n'existe qu'une fois posé. L'exiger ici
        refusait au premier tour ce que le premier tour seul rend possible."""
        quoi = " ".join(p.quoi for p in B.prealables(mesures_bonnes()))
        self.assertNotIn(B.GABARIT, quoi)
        # Contrôle positif : les autres préalables sont toujours jugés ici.
        self.assertIn("pont", quoi)

    def test_an_unreadable_link_state_is_not_a_refusal(self):
        vus = B.prealables(mesures_bonnes(liens=(None, B.NOTRE)))
        self.assertIn(None, [p.tenu for p in vus])

    def test_a_refused_elevation_says_why(self):
        """Un sudo interactif n'échoue pas, il attend : le dire évite de chercher
        une machine en panne."""
        vus = B.prealables(mesures_bonnes(elevation=B.IMPOSSIBLE))
        dit = " ".join(p.dit for p in B.manquants(vus))
        self.assertIn("mot de passe", dit)

    def test_an_occupied_link_names_which_one(self):
        vus = B.prealables(mesures_bonnes(liens=(B.OCCUPE, B.NOTRE)))
        dit = " ".join(p.dit for p in B.manquants(vus))
        self.assertIn(B.LIEN_UNDERLAY, dit)
        self.assertNotIn(B.LIEN_INSTANCE, dit)

    def test_no_storage_declaring_images_says_so(self):
        """Un stockage à sauvegardes ou à modèles de conteneur n'accepte pas un
        clone, et le clonage échoue alors sur un message qui parle du stockage
        sans dire pourquoi."""
        vus = B.prealables(mesures_bonnes(stockage=""))
        dit = " ".join(p.dit for p in B.manquants(vus))
        self.assertIn("images de disque", dit)

    def test_no_default_route_says_the_masquerading_would_aim_nowhere(self):
        """Viser la mauvaise interface laisse les VM se parler entre elles sans
        jamais sortir, et « apt ne répond pas » n'envoie pas regarder une règle
        de traduction d'adresses."""
        vus = B.prealables(mesures_bonnes(uplink=""))
        dit = " ".join(p.dit for p in B.manquants(vus))
        self.assertIn("masquage", dit)

    def test_the_terrain_is_judged_first(self):
        """Sans terrain, aucune autre mesure ne veut rien dire."""
        self.assertIn("terrain", B.prealables(mesures_bonnes())[0].quoi)


class TestRienNeSePoseSansAvoirEteNomme(unittest.TestCase):
    """Écrite APRÈS la pose, une interruption entre les deux laisserait sur la
    grappe un objet que plus rien ne nomme — et `--detruire` ne défait que ce que
    l'empreinte nomme. Nommé d'abord, le pire cas est un nom sans objet, et tous
    les gestes de défaite tolèrent l'absence."""

    def chantier(self):
        dossier = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, dossier, True)
        return B.Chantier(
            "un-terrain", os.path.join(dossier, "creux", "empreinte.json")
        )

    def relu(self, chantier):
        with open(chantier.chemin, encoding="utf-8") as lu:
            return B.lit_empreinte(lu.read())

    def test_the_name_is_on_disk_before_anything_is_posed(self):
        """LA PROPRIÉTÉ : le fichier porte le nom dès que `nomme` a rendu."""
        chantier = self.chantier()
        self.assertEqual("", chantier.nomme(pont="vmbr9"))
        self.assertEqual("vmbr9", self.relu(chantier).pont)

    def test_it_creates_the_directory_it_needs(self):
        """Le dossier du labo peut ne pas exister au premier lancement."""
        chantier = self.chantier()
        self.assertEqual("", chantier.ecrit())
        self.assertTrue(os.path.isfile(chantier.chemin))

    def test_every_addition_is_written(self):
        chantier = self.chantier()
        chantier.nomme(pont="vmbr9")
        chantier.nomme(zones=(3114,))
        chantier.nomme(vms=((101, "banc-fictif-01"),))
        relu = self.relu(chantier)
        self.assertEqual(
            ("vmbr9", (3114,), ((101, "banc-fictif-01"),)),
            (relu.pont, relu.zones, relu.vms),
        )

    def test_what_it_writes_is_ours(self):
        """`a_defaire` refuse une empreinte qui n'est pas celle du banc : un
        chantier qui écrirait autre chose ne se défairait jamais."""
        chantier = self.chantier()
        chantier.nomme(pont="vmbr9")
        self.assertTrue(B.nous(self.relu(chantier)))
        self.assertNotEqual((), B.a_defaire(self.relu(chantier)))

    def test_a_directory_that_cannot_be_written_says_so(self):
        """Rendu et non levé : l'appelant décide s'il continue — mais il ne doit
        pas poser ce qu'il n'a pas pu nommer."""
        chantier = B.Chantier("un-terrain", "/proc/interdit/empreinte.json")
        self.assertTrue(chantier.nomme(pont="vmbr9"))

    def test_no_temporary_file_is_left_behind(self):
        """CE QUE CETTE ÉPREUVE MESURE : aucun reste. Elle ne prouve PAS
        l'atomicité — il faudrait tuer le processus au bon moment — mais un
        fichier de travail oublié à côté de l'empreinte se retrouve plus tard
        sans qu'on sache lequel des deux compte.
        """
        chantier = self.chantier()
        chantier.nomme(pont="vmbr9")
        restes = [
            n
            for n in os.listdir(os.path.dirname(chantier.chemin))
            if n.endswith(".chantier")
        ]
        self.assertEqual([], restes)


class TestLeBancReutiliseSonPontPlutotQueDenPrendreUnDePlus(unittest.TestCase):
    """Le premier nom libre CHANGE dès que le banc a posé un pont. Une exécution
    qui ne relirait pas son empreinte en poserait un second à chaque fois, et
    n'en défairait qu'un — le précédent resterait, avec son masquage, sur un
    réseau que plus rien ne nomme."""

    DECLARE = (
        "auto lo\niface lo inet loopback\n\n"
        "auto vmbr9\niface vmbr9 inet static\n    address 10.0.0.1/24\n"
    )

    def test_its_own_declared_bridge_is_reused(self):
        self.assertEqual("vmbr9", B.pont_du_banc(self.DECLARE, "vmbr9"))

    def test_a_free_name_is_taken_when_it_has_none(self):
        """Le contrôle positif : sans lui, une reprise inconditionnelle
        passerait l'épreuve ci-dessus."""
        self.assertEqual("vmbr10", B.pont_du_banc(self.DECLARE, ""))

    def test_a_name_it_remembers_but_the_host_lost_is_not_reused(self):
        """Nommé dans l'empreinte mais absent de l'hôte, il a été retiré à la
        main : le reprendre supposerait une strophe qui n'existe plus."""
        self.assertEqual("vmbr10", B.pont_du_banc(self.DECLARE, "vmbr42"))

    def test_an_unread_terrain_gives_no_bridge(self):
        """Trois cas rendent « », et ils disent tous la même chose : le terrain
        n'a pas été lu. Reprendre un nom sans avoir lu la configuration
        reconfigurerait le réseau d'autre chose."""
        for interfaces in ("", None, "Permission denied"):
            with self.subTest(interfaces=interfaces):
                self.assertEqual("", B.pont_du_banc(interfaces, "vmbr9"))

    def test_it_never_returns_a_name_the_host_already_uses_otherwise(self):
        """Ce que `pont_libre` garantit déjà, et que la reprise ne doit pas
        défaire : seul le nom de l'EMPREINTE est repris, jamais un autre nom
        déclaré."""
        self.assertNotEqual("vmbr9", B.pont_du_banc(self.DECLARE, "vmbr11"))

    def test_the_name_remembered_comes_from_a_footprint_of_the_bench(self):
        """Une empreinte qui n'est pas la nôtre ne nomme rien pour nous : c'est
        `nous` qui tranche, comme pour la défaite."""
        dossier = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, dossier, True)
        chemin = os.path.join(dossier, "empreinte.json")
        for ecosysteme, attendu in (
            (B.ECOSYSTEME, "vmbr9"),
            ("OPS-Une-Production", ""),
        ):
            with self.subTest(ecosysteme=ecosysteme):
                with open(chemin, "w", encoding="utf-8") as ecrit:
                    ecrit.write(
                        B.ecrit_empreinte(
                            empreinte_pleine(
                                ecosysteme=ecosysteme, pont="vmbr9"
                            )
                        )
                    )
                self.assertEqual(attendu, B.pont_deja_nomme(chemin))

    def test_no_footprint_remembers_nothing(self):
        self.assertEqual("", B.pont_deja_nomme("/n-existe-pas-du-tout.json"))


class TestLaGrappeDitSesNoeudsEtSesStockages(unittest.TestCase):
    """Le banc ne devine ni l'un ni l'autre. Cloner sur un nœud éteint échoue
    APRÈS avoir attendu, et l'attente ressemble à un clonage lent ; poser une VM
    sur un stockage qui n'accepte pas d'images échoue sur un message qui parle du
    stockage sans dire pourquoi."""

    def test_only_online_nodes_are_named(self):
        """LA PROPRIÉTÉ : un nœud éteint est écarté, pas rendu."""
        self.assertEqual(
            ("vivant",),
            B.lit_noeuds(
                json.dumps(
                    [
                        {"node": "vivant", "status": "online"},
                        {"node": "eteint", "status": "offline"},
                    ]
                )
            ),
        )

    def test_a_node_without_a_status_is_not_online(self):
        """Une absence dit « on ne sait pas », et on ne clone pas sur un nœud
        dont on ne sait rien."""
        self.assertEqual((), B.lit_noeuds(json.dumps([{"node": "muet"}])))

    def test_every_node_online_is_kept(self):
        """Le contrôle positif : sans lui, un lecteur qui n'en rend jamais aucun
        passerait les épreuves ci-dessus."""
        self.assertEqual(
            ("a", "b"),
            B.lit_noeuds(
                json.dumps(
                    [
                        {"node": "a", "status": "online"},
                        {"node": "b", "status": "online"},
                    ]
                )
            ),
        )

    def test_only_storages_declaring_images_are_named(self):
        """LA PROPRIÉTÉ : le contenu accepté est DÉCLARÉ par le stockage. Le
        deviner de son nom se tromperait sur toute grappe qui nomme ses stockages
        autrement que la nôtre."""
        self.assertEqual(
            ("qui-porte",),
            B.lit_stockages(
                json.dumps(
                    [
                        {
                            "storage": "qui-porte",
                            "content": "iso,images,vztmpl",
                        },
                        {"storage": "sauvegardes", "content": "backup"},
                    ]
                )
            ),
        )

    def test_a_storage_without_declared_content_does_not_count(self):
        """Ce n'est pas « il accepte tout », c'est « on ne sait pas »."""
        self.assertEqual(
            (), B.lit_stockages(json.dumps([{"storage": "muet"}]))
        )

    def test_a_content_that_merely_contains_the_word_is_not_enough(self):
        """L'appariement porte sur un ÉLÉMENT de la liste, pas sur une
        sous-chaîne : « imagesx » n'est pas « images »."""
        self.assertEqual(
            (),
            B.lit_stockages(
                json.dumps([{"storage": "presque", "content": "imagesx,iso"}])
            ),
        )

    def test_a_storage_declaring_images_is_kept(self):
        """Le contrôle positif des trois épreuves ci-dessus."""
        self.assertEqual(
            ("bon",),
            B.lit_stockages(
                json.dumps([{"storage": "bon", "content": "images"}])
            ),
        )

    def test_both_refuse_what_is_not_a_list_of_objects(self):
        for sortie in (
            "ipcc_send_rec failed",
            "",
            None,
            '{"node": "a"}',
            "[1, 2]",
            '[{"node": 42}]',
        ):
            for lecteur in (B.lit_noeuds, B.lit_stockages):
                with self.subTest(sortie=str(sortie)[:24], lecteur=lecteur):
                    self.assertIsNone(lecteur(sortie))

    def test_a_truncated_answer_refuses(self):
        """Une réponse coupée en chemin n'est pas une grappe sans nœud."""
        self.assertIsNone(B.lit_noeuds('[{"node": "a", "statu'))


class TestLeTerrainDitParOuIlSort(unittest.TestCase):
    """L'interface est celle de la ROUTE PAR DÉFAUT, pas un nom deviné. Viser la
    mauvaise laisse les VM se parler entre elles sans jamais sortir, et le
    symptôme — « apt ne répond pas » — n'envoie pas regarder une règle de
    traduction d'adresses."""

    def test_both_facts_are_read(self):
        self.assertEqual(
            ("une-sortie", "192.0.2.10"),
            B.lit_sortie("sortie=une-sortie\nadresse=192.0.2.10/24\n"),
        )

    def test_the_prefix_is_dropped_from_the_address(self):
        """C'est l'adresse par laquelle on joint l'API, pas un réseau."""
        _i, adresse = B.lit_sortie("sortie=s\nadresse=192.0.2.10/24\n")
        self.assertNotIn("/", adresse)

    def test_half_an_answer_concludes_nothing(self):
        """Une interface sans adresse ne permet pas de joindre son
        hyperviseur."""
        for sortie in (
            "sortie=s\n",
            "adresse=192.0.2.10/24\n",
            "sortie=\nadresse=192.0.2.10/24\n",
            "sortie=s\nadresse=\n",
            "",
            None,
            "du bruit sans rapport\n",
        ):
            with self.subTest(sortie=repr(sortie)):
                self.assertIsNone(B.lit_sortie(sortie))

    def test_a_complete_answer_is_not_refused(self):
        """Le contrôle positif des refus ci-dessus."""
        self.assertIsNotNone(B.lit_sortie("sortie=s\nadresse=192.0.2.10/24\n"))


class TestLaDefaiteNEffaceQueCeQuiEstAuBanc(unittest.TestCase):
    """L'empreinte est un fichier JSON qu'un éditeur ouvre. Chaque verbe qui
    efface confronte donc ce qu'il reçoit à ce que le banc peut avoir posé — et
    refuse le reste, plutôt que de faire confiance à un fichier."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)

    def fichier(self, nom, contenu="x"):
        chemin = os.path.join(self.d, nom)
        with open(chemin, "w", encoding="utf-8") as ecrit:
            ecrit.write(contenu)
        return chemin

    def test_a_link_of_the_bench_is_removed(self):
        """Le contrôle positif : sans lui, un verbe qui refuse toujours
        passerait tous les refus ci-dessous."""
        chemin = os.path.join(self.d, B.LIEN_INSTANCE)
        os.symlink("../quelque-part", chemin)
        self.assertEqual("", B._retire_lien(chemin))
        self.assertFalse(os.path.lexists(chemin))

    def test_a_link_at_another_name_is_refused(self):
        """L'ÉPREUVE PORTE SUR UN LIEN, et pas sur un fichier : un fichier est
        déjà refusé par le garde du genre, si bien qu'elle passerait par le
        mauvais chemin sans rien dire du garde du NOM."""
        cible = self.fichier("la-cible-de-quelqu-un")
        chemin = os.path.join(self.d, "un-lien-qui-n-est-pas-a-nous")
        os.symlink(cible, chemin)
        self.assertTrue(B._retire_lien(chemin))
        self.assertTrue(os.path.lexists(chemin))

    def test_a_plain_file_at_our_name_is_never_removed(self):
        """Le banc ne pose QUE des liens à ces deux noms : un fichier ordinaire
        y est quelque chose que personne d'ici n'a écrit."""
        chemin = self.fichier(B.LIEN_UNDERLAY, "le fichier de quelqu'un\n")
        self.assertTrue(B._retire_lien(chemin))
        self.assertTrue(os.path.isfile(chemin))

    def test_a_real_directory_is_never_removed(self):
        """Le banc ne pose jamais de dossier à ce nom : c'est le checkout d'un
        exploitant, et l'effacer détruirait son plan."""
        chemin = os.path.join(self.d, B.LIEN_INSTANCE)
        os.makedirs(chemin)
        with open(
            os.path.join(chemin, "plan.yml"), "w", encoding="utf-8"
        ) as e:
            e.write("le plan de quelqu'un\n")
        self.assertTrue(B._retire_lien(chemin))
        self.assertTrue(os.path.isdir(chemin))

    def test_a_link_already_gone_is_not_a_failure(self):
        """L'empreinte nomme AVANT la pose : un nom sans objet est le cas normal
        d'une pose interrompue."""
        self.assertEqual(
            "", B._retire_lien(os.path.join(self.d, B.LIEN_UNDERLAY))
        )

    def test_a_key_of_the_bench_is_removed(self):
        """Le contrôle positif des refus de clés."""
        chemin = self.fichier(f"setops-vault-{B.ECOSYSTEME.lower()}")
        self.assertEqual("", B._retire_cle(chemin))
        self.assertFalse(os.path.exists(chemin))

    def test_a_key_that_is_not_ours_is_refused(self):
        """La clé sans laquelle une voûte ne s'ouvre plus, et qu'aucune
        sauvegarde de dépôt ne contient puisqu'elle vit exprès dehors."""
        chemin = self.fichier("setops-vault-une-production")
        self.assertTrue(B._retire_cle(chemin))
        self.assertTrue(os.path.exists(chemin))

    def test_removing_a_link_never_touches_what_it_points_at(self):
        """CE QUE CETTE ÉPREUVE MESURE : l'effacement ne SUIT PAS un lien. Un
        lien posé à notre nom perd le lien, et la clé de quelqu'un d'autre au
        bout reste. Le garde de NOM, lui, est éprouvé à côté."""
        vraie = self.fichier("la-cle-de-quelqu-un")
        piege = os.path.join(self.d, f"setops-vault-{B.ECOSYSTEME.lower()}")
        os.symlink(vraie, piege)
        self.assertEqual("", B._retire_cle(piege))
        self.assertFalse(os.path.lexists(piege))
        self.assertTrue(os.path.isfile(vraie))

    def test_the_repositories_path_comes_from_the_engine(self):
        """DÉRIVÉ, pas lu dans l'empreinte : le lire d'un fichier qu'un éditeur
        ouvre donnerait à ce fichier le pouvoir de faire effacer n'importe quel
        dossier."""
        self.assertTrue(B._retire_depot("", B.ECO))

    def test_a_repository_already_gone_is_not_a_failure(self):
        moteur = os.path.join(self.d, "Moteur")
        os.makedirs(moteur)
        for genre in (B.ECO, B.UNDERLAY):
            with self.subTest(genre=genre):
                self.assertEqual("", B._retire_depot(moteur, genre))

    def test_a_repository_of_the_bench_is_removed(self):
        """Le contrôle positif du précédent."""
        moteur = os.path.join(self.d, "Moteur")
        os.makedirs(moteur)
        _freres, site, eco = B.chemins_du_banc(moteur)
        for chemin, genre in ((eco, B.ECO), (site, B.UNDERLAY)):
            with self.subTest(genre=genre):
                os.makedirs(chemin, exist_ok=True)
                self.assertEqual("", B._retire_depot(moteur, genre))
                self.assertFalse(os.path.isdir(chemin))

    def test_an_unreadable_vmid_leaves_a_trouble(self):
        """LA PROPRIÉTÉ : ce n'est PAS « déjà absente ». Sans ce refus, un VMID
        qu'on n'a pas su lire fait rendre « rien à faire », et la défaite
        annonce une réussite pour une VM qu'elle n'a jamais regardée — alors
        que l'empreinte la nommait."""
        for vise in ("", "abc", "0", "-3"):
            with self.subTest(vise=vise):
                geste = B.Geste("un-terrain", B.VM, vise, "banc-fictif-01")
                self.assertTrue(B.defait_un_geste(geste, "", B.TEL_QUEL))

    def test_an_unknown_genre_is_refused(self):
        """Le vocabulaire est CLOS : un genre hors de lui vient d'une empreinte
        qui n'est pas celle du banc."""
        geste = B.Geste("un-terrain", "genre-invente", "cible", "nom")
        self.assertTrue(B.defait_un_geste(geste, "", B.TEL_QUEL))

    def test_every_genre_of_the_vocabulary_is_handled(self):
        """Le contrôle positif du précédent : aucun genre du vocabulaire ne doit
        tomber dans le refus « genre inconnu »."""
        for genre in B.GENRES:
            with self.subTest(genre=genre):
                geste = B.Geste("un-terrain-invente.invalid", genre, "", "")
                self.assertNotIn(
                    "genre inconnu", B.defait_un_geste(geste, "", B.TEL_QUEL)
                )


class TestUneVmNeSEffacePasSansQueSonNomConcorde(unittest.TestCase):
    """Un VMID se réattribue. Effacer sans avoir lu le nom détruirait le travail
    de quelqu'un d'autre."""

    def test_the_name_is_read_from_the_configuration(self):
        self.assertEqual(
            "banc-fictif-01",
            B.lit_nom_vm("vmid: 101\nname: banc-fictif-01\ncores: 2\n"),
        )

    def test_a_configuration_without_a_name_reads_nothing(self):
        for sortie in ("cores: 2\n", "", None, "  name: indenté\n"):
            with self.subTest(sortie=repr(sortie)):
                self.assertEqual("", B.lit_nom_vm(sortie))

    def test_an_unread_name_refuses_the_erasure(self):
        """« » dit « pas su lire », et l'appariement REFUSE alors."""
        self.assertFalse(B.effacable("banc-fictif-01", B.lit_nom_vm("")))

    def test_deleting_the_api_user_takes_its_token_with_it(self):
        """Les retirer séparément laisserait, si l'un échouait, un compte
        d'administration sur une grappe que le banc croit avoir quittée."""
        joint = " ".join(B.cmds_effacer_api("un-compte@pve"))
        self.assertIn("user delete", joint)
        self.assertEqual(1, len(B.cmds_effacer_api()))


class TestLeCompteDApiNeResteJamaisEnSilence(unittest.TestCase):
    """C'est le seul geste de la défaite dont l'échec silencieux laisse un ACCÈS
    OUVERT : un compte d'administration et le jeton qui va avec, sur une grappe
    que le banc croit avoir quittée."""

    def comptes(self, *ids):
        return json.dumps([{"userid": i, "enable": 1} for i in ids])

    def test_the_declared_accounts_are_read(self):
        self.assertEqual(
            ("root@pam", "banc@pve"),
            B.lit_utilisateurs(self.comptes("root@pam", "banc@pve")),
        )

    def test_an_unreadable_answer_refuses(self):
        """Une lecture qui conclurait à tort « il n'est pas là » laisserait le
        compte en place en annonçant une défaite complète."""
        for sortie in (
            "ipcc_send_rec failed",
            "",
            None,
            '{"userid": "x"}',
            "[42]",
            '[{"user": "sans-userid"}]',
        ):
            with self.subTest(sortie=str(sortie)[:24]):
                self.assertIsNone(B.lit_utilisateurs(sortie))

    def test_a_well_formed_list_is_not_refused(self):
        """Le contrôle positif des refus ci-dessus."""
        self.assertIsNotNone(B.lit_utilisateurs(self.comptes("root@pam")))

    def test_an_account_that_is_there_is_to_be_removed(self):
        self.assertIs(
            True,
            B.api_a_retirer(
                ("root@pam", B.UTILISATEUR_API), B.UTILISATEUR_API
            ),
        )

    def test_an_account_already_gone_is_not(self):
        """Une réussite, pas un souci : c'est le cas normal d'une seconde
        défaite."""
        self.assertIs(False, B.api_a_retirer(("root@pam",), B.UTILISATEUR_API))

    def test_a_cluster_that_said_nothing_is_not_an_absence(self):
        """LA PROPRIÉTÉ : None n'est pas False. « La grappe n'a pas dit ses
        comptes » et « le compte n'y est plus » commandent des suites
        opposées — l'une laisse un souci, l'autre est une réussite."""
        self.assertIsNone(B.api_a_retirer(None, B.UTILISATEUR_API))

    def test_a_cluster_that_did_not_answer_leaves_a_trouble(self):
        """LA PROPRIÉTÉ : ne pas savoir n'est pas « c'est fait ». Le terrain est
        inventé, donc la grappe ne répond pas."""
        geste = B.Geste(
            "un-terrain-invente.invalid",
            B.API,
            B.UTILISATEUR_API,
            B.UTILISATEUR_API,
        )
        souci = B.defait_un_geste(geste, "", B.TEL_QUEL)
        self.assertTrue(souci)
        self.assertIn(B.UTILISATEUR_API, souci)


if __name__ == "__main__":
    unittest.main()
