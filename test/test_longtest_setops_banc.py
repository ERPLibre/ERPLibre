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
import shutil
import subprocess
import sys
import tempfile
import unittest

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
        for servi in (B.VM, B.MODELE, B.PONT, B.API, B.ECO):
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


if __name__ == "__main__":
    unittest.main()
