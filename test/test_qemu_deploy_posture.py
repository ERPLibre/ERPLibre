#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Rendre les règles depuis la spec, les poser, et refuser AVANT de créer.

Le déploiement ne connaît pas les postures : il reçoit un fichier déjà rendu
et le passe. C'est ce qui garde le rendu éprouvable sans machine, et le
déploiement libre de savoir ce qu'est une liste blanche.

CE QUI EST REFUSÉ ICI EST L'INVERSE DE CE QUI EST VIDE. Une posture qui
n'attend pas de règles rend une chaîne vide, et la plupart des déploiements
sont dans ce cas. Une posture qui EN attend et dont le site n'a pas nommé
les adresses est refusée : la laisser passer déploierait une machine qui ne
joint pas sa forge, et le manque se découvrirait sur la machine.

Le carnet du site est une donnée de SITE. Celui qu'on lit ici est de banc,
et ses adresses sont des plages de documentation (RFC 5737).
"""

import os
import sys
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

sys.argv = ["todo.py"]

from script.lib_valid import ValidationError  # noqa: E402
from script.posture import allowlist as A  # noqa: E402
from script.posture import registry as R  # noqa: E402
from script.posture import rules as RULES  # noqa: E402
from script.todo.deploy_form_lib import build_spec  # noqa: E402
from script.todo.todo import TODO  # noqa: E402
from script.vm import backend as VM  # noqa: E402

FORM = {
    "res_label": "x1",
    "ssh_key": "",
    "install": None,
    "add_ssh_config": False,
    "parallelism": 1,
}

VM_UNE = {
    "distro": "ubuntu",
    "version": "24.04",
    "arch": "amd64",
    "name": "essai",
    "ram": 4096,
    "vcpus": 2,
    "disk": "30G",
}

# Un carnet de banc : un réseau de documentation par rôle connu.
CARNET = {
    nom: [f"198.51.100.{index + 10}/32"]
    for index, nom in enumerate(A.symbol_names())
}


def menu(carnet=None):
    """Un TODO nu, dont la configuration rend le carnet demandé."""
    todo = TODO.__new__(TODO)
    todo.config_file = type(
        "ConfigDeBanc",
        (),
        {"get_config": staticmethod(lambda _cle: carnet)},
    )()
    return todo


def spec_de(posture):
    return build_spec([VM_UNE], [], dict(FORM, posture=posture))


class TestCeQuiEstRenduEtCeQuiNeLEstPas(unittest.TestCase):
    def test_a_posture_that_asks_for_nothing_renders_nothing(self):
        """La plupart des déploiements sont là, et ne doivent rien payer.

        « local-only » N'EN FAIT PLUS PARTIE, et cette épreuve l'y rangeait
        — elle épinglait donc le défaut comme le comportement attendu. Une
        sortie coupée n'a aucune adresse à nommer, mais elle veut des
        règles : « policy drop » est précisément ce qu'elle promet. Sans
        elles, la posture la plus confinée se déployait avec la sortie
        entière.
        """
        for nom in ("open", "connected"):
            with self.subTest(posture=nom):
                self.assertEqual(
                    "", menu(CARNET)._qemu_egress_rules(spec_de(nom))
                )

    def test_a_cut_egress_does_render_and_drops(self):
        """Le contrôle qui manquait. Ce que le déploiement pose désormais
        pour « local-only », et ce que ces octets valent."""
        rendu = menu(CARNET)._qemu_egress_rules(spec_de("local-only"))
        self.assertTrue(rendu, "la posture qui promet le plus ne posait rien")
        self.assertIn("policy drop", rendu)
        self.assertIn('oif "lo" accept', rendu)

    def test_the_cut_egress_rendering_is_relayed_word_for_word(self):
        """Le déploiement ne compose rien : il relaie. Une recopie
        divergerait au premier correctif du rendu."""
        from script.posture import destinations as D

        posture = R.get_posture("local-only")
        attendu = RULES.render_egress(
            posture, D.destinations_for(posture, CARNET)
        )
        self.assertEqual(
            attendu, menu(CARNET)._qemu_egress_rules(spec_de("local-only"))
        )

    def test_the_address_book_changes_nothing_for_a_cut_egress(self):
        """Elle ne joint rien : un carnet rempli ne doit pas lui faire
        nommer des adresses que le fichier dirait joignables."""
        avec = menu(CARNET)._qemu_egress_rules(spec_de("local-only"))
        sans = menu({})._qemu_egress_rules(spec_de("local-only"))
        self.assertEqual(avec, sans)

    def test_a_mute_spec_renders_nothing_either(self):
        spec = build_spec([VM_UNE], [], FORM)
        self.assertEqual("", menu(CARNET)._qemu_egress_rules(spec))

    def test_a_bounded_posture_renders_what_the_renderer_renders(self):
        """Le déploiement ne compose rien : il relaie le rendu, mot pour
        mot. Une recopie divergerait au premier correctif."""
        from script.posture import destinations as D

        posture = R.get_posture("paranoid")
        attendu = RULES.render_egress(
            posture, D.destinations_for(posture, CARNET)
        )
        self.assertEqual(
            attendu, menu(CARNET)._qemu_egress_rules(spec_de("paranoid"))
        )


class TestCeQuiEstRefuseAvantDeRienCreer(unittest.TestCase):
    def test_an_unknown_posture_is_refused_by_name(self):
        """Replier sur la plus libre déploierait en sortie libre une spec
        qui demandait du confinement — le sens inverse de la demande."""
        with self.assertRaises(VM.VmBackendError) as pris:
            menu(CARNET)._qemu_egress_rules(spec_de("restricted"))
        self.assertIn("restricted", str(pris.exception))

    def test_a_role_the_site_never_addressed_is_refused_by_name(self):
        ampute = {k: v for k, v in CARNET.items() if k != "forge"}
        with self.assertRaises(ValidationError) as pris:
            menu(ampute)._qemu_egress_rules(spec_de("paranoid"))
        self.assertIn("forge", str(pris.exception))

    def test_no_address_book_at_all_is_refused(self):
        with self.assertRaises(ValidationError):
            menu(None)._qemu_egress_rules(spec_de("paranoid"))

    def test_the_refusal_lands_before_the_block_is_entered(self):
        """Le fichier temporaire ne doit pas exister quand le refus tombe :
        c'est ce qui garantit qu'aucune machine n'a été touchée."""
        with self.assertRaises(ValidationError):
            with menu(None)._qemu_egress_file(spec_de("paranoid")):
                self.fail("le bloc ne devait pas s'ouvrir")


class TestLeFichierTemporaire(unittest.TestCase):
    def test_nothing_to_pose_yields_no_path(self):
        with menu(CARNET)._qemu_egress_file(spec_de("open")) as fichiers:
            self.assertEqual(("", ""), tuple(fichiers))

    def test_both_files_are_written(self):
        """Les règles disent CE QUI passe, l'unité dit QUAND elles sont
        chargées : poser les premières sans la seconde ne confine que
        jusqu'au premier redémarrage."""
        with menu(CARNET)._qemu_egress_file(spec_de("paranoid")) as f:
            self.assertTrue(os.path.exists(f.rules))
            self.assertTrue(os.path.exists(f.unit))
            self.assertNotEqual(f.rules, f.unit)

    def test_they_are_written_readable_by_their_owner_alone(self):
        """Sur la station qui déploie : le fichier de règles nomme les
        adresses internes du site."""
        with menu(CARNET)._qemu_egress_file(spec_de("paranoid")) as f:
            for chemin in (f.rules, f.unit):
                self.assertEqual(0o600, os.stat(chemin).st_mode & 0o777)

    def test_they_carry_what_was_rendered(self):
        with menu(CARNET)._qemu_egress_file(spec_de("paranoid")) as f:
            with open(f.rules, encoding="utf-8") as fichier:
                regles = fichier.read()
            with open(f.unit, encoding="utf-8") as fichier:
                unite = fichier.read()
        self.assertIn("policy drop;", regles)
        self.assertIn("# forge :", regles)
        self.assertIn("Before=network-pre.target", unite)

    def test_they_are_gone_once_the_block_closes(self):
        with menu(CARNET)._qemu_egress_file(spec_de("paranoid")) as f:
            garde = (f.rules, f.unit)
        for chemin in garde:
            self.assertFalse(os.path.exists(chemin))

    def test_they_are_gone_even_when_the_deployment_breaks(self):
        """Le fichier de règles porte les adresses internes du site : il ne
        traîne pas."""
        garde = {}
        with self.assertRaises(RuntimeError):
            with menu(CARNET)._qemu_egress_file(spec_de("paranoid")) as f:
                garde["f"] = (f.rules, f.unit)
                raise RuntimeError("le parc s'arrête au milieu")
        for chemin in garde["f"]:
            self.assertFalse(os.path.exists(chemin))

    def test_the_names_say_nothing_about_the_site(self):
        """Un nom composé serait un chemin PRÉVISIBLE ; ceux-ci ne le sont
        pas, et ne nomment ni la machine ni la posture."""
        with menu(CARNET)._qemu_egress_file(spec_de("paranoid")) as f:
            for chemin in (f.rules, f.unit):
                self.assertNotIn("paranoid", chemin)
                self.assertNotIn("essai", chemin)


class TestLaCommandePosee(unittest.TestCase):
    def test_without_a_file_the_command_is_the_one_from_before(self):
        parts = menu(CARNET)._qemu_deploy_parts_for(
            VM_UNE, spec_de("open"), dry_run=True
        )
        self.assertNotIn("--egress-file", parts)

    def test_the_flags_name_the_files_that_were_written(self):
        todo = menu(CARNET)
        spec = spec_de("paranoid")
        with todo._qemu_egress_file(spec) as f:
            parts = todo._qemu_deploy_parts_for(
                VM_UNE, spec, dry_run=True, egress=f
            )
            self.assertEqual(f.rules, parts[parts.index("--egress-file") + 1])
            self.assertEqual(f.unit, parts[parts.index("--egress-unit") + 1])

    def test_the_flags_come_last_and_change_nothing_before_them(self):
        """Le reste de la commande ne bouge pas d'un mot : une option qui
        déborde sur le cas courant coûte plus qu'elle n'apporte."""
        todo = menu(CARNET)
        spec = spec_de("paranoid")
        nu = todo._qemu_deploy_parts_for(VM_UNE, spec, dry_run=True)
        with todo._qemu_egress_file(spec) as f:
            avec = todo._qemu_deploy_parts_for(
                VM_UNE, spec, dry_run=True, egress=f
            )
            attendu = [
                "--egress-file",
                f.rules,
                "--egress-unit",
                f.unit,
            ]
        self.assertEqual(nu, avec[: len(nu)])
        self.assertEqual(attendu, avec[len(nu) :])

    def test_the_run_path_actually_hands_the_file_over(self):
        """Le maillon qu'aucune épreuve ne pouvait tenir autrement : le
        déploiement réel crée des machines, donc il ne se joue pas ici.

        L'épreuve lit l'ARBRE et non le texte : elle trouve l'appel,
        et tombe s'il disparaît autant que s'il perd son argument. Sans
        elle, retirer « egress= » de la boucle laisse tout vert et ne pose
        plus jamais de règles.
        """
        import ast

        source = os.path.join(RACINE, "script", "todo", "qemu_deploy.py")
        with open(source, encoding="utf-8") as fichier:
            arbre = ast.parse(fichier.read())
        corps = [
            noeud
            for noeud in ast.walk(arbre)
            if isinstance(noeud, ast.FunctionDef)
            and noeud.name == "_qemu_run_spec"
        ]
        self.assertEqual(1, len(corps), "_qemu_run_spec introuvable")
        appels = [
            noeud
            for noeud in ast.walk(corps[0])
            if isinstance(noeud, ast.Call)
            and isinstance(noeud.func, ast.Attribute)
            and noeud.func.attr == "_qemu_deploy_parts_for"
        ]
        self.assertEqual(1, len(appels), "l'appel du déploiement a bougé")
        self.assertIn("egress", [mot.arg for mot in appels[0].keywords])

    def test_the_run_path_opens_the_block_that_writes_the_file(self):
        """L'autre moitié du même maillon : passer « egress » ne sert à
        rien si personne n'ouvre le bloc qui écrit le fichier."""
        import ast

        source = os.path.join(RACINE, "script", "todo", "qemu_deploy.py")
        with open(source, encoding="utf-8") as fichier:
            arbre = ast.parse(fichier.read())
        corps = [
            noeud
            for noeud in ast.walk(arbre)
            if isinstance(noeud, ast.FunctionDef)
            and noeud.name == "_qemu_run_spec"
        ][0]
        ouvertures = [
            noeud
            for noeud in ast.walk(corps)
            if isinstance(noeud, ast.Call)
            and isinstance(noeud.func, ast.Attribute)
            and noeud.func.attr == "_qemu_egress_file"
        ]
        self.assertEqual(1, len(ouvertures))

    def test_the_flag_is_the_one_the_deployment_script_declares(self):
        """Un drapeau que l'autre côté ne connaît pas ferait échouer le
        déploiement sur « unrecognized arguments », après la création."""
        import importlib.util
        from pathlib import Path

        chemin = Path(RACINE) / "script/qemu/deploy_qemu.py"
        spec_mod = importlib.util.spec_from_file_location("dq_flag", chemin)
        module = importlib.util.module_from_spec(spec_mod)
        sys.modules["dq_flag"] = module
        spec_mod.loader.exec_module(module)
        analyse = module.build_parser().parse_args(
            [
                "--name",
                "banc",
                "--egress-file",
                "/x.nft",
                "--egress-unit",
                "/x.service",
            ]
        )
        self.assertEqual("/x.nft", analyse.egress_file)
        self.assertEqual("/x.service", analyse.egress_unit)


if __name__ == "__main__":
    unittest.main()
