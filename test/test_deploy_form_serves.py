#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le couple (libellé choisi, installation choisie), au seul endroit où le
libellé existe.

LES DEUX ÉCRANS. Le second a été écrit en recopiant le premier, et une
épreuve qui n'en pilote qu'un laisse l'autre perdre l'avertissement sans
que rien ne le dise.

POURQUOI PAS AU DÉPLOIEMENT. Un spec porte une POSTURE, pas le libellé sous
lequel on l'a choisie, et le registre sépare les deux exprès : « les séparer
est ce qui permet de servir autre chose sur la même posture ». Un refus
là-bas aurait bloqué la seule posture qui porte une donnée réelle, sur la
foi d'un nom que personne n'avait choisi — c'est ce qu'une épreuve existante
a attrapé.

L'écran, lui, SAIT qu'un libellé a été choisi : c'est lui qui l'a montré.

UN AVERTISSEMENT ET NON UN REFUS. Servir autre chose sur cette posture reste
légitime. Le second F5 vaut confirmation, comme pour un disque orphelin.

Le formulaire est PILOTÉ pour de vrai — `run_app=False` puis `run_test` —
donc ce qui est éprouvé est le comportement et non le texte du fichier.
"""

import asyncio
import sys
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.append(str(RACINE))

sys.argv = ["todo.py"]
from script.todo import todo_i18n, vm_profiles  # noqa: E402
from script.todo.qemu_deploy_form import run_deploy_form  # noqa: E402
from script.todo.todo import TODO  # noqa: E402

# L'installation qui pose Odoo, et celle qui n'en pose pas. Prises dans le
# dépôt et non écrites ici : une copie divergerait au premier profil ajouté.
MENU = TODO.__new__(TODO)._qemu_install_profiles()
AVEC = next(c for _l, c in MENU if vm_profiles.ODOO_MARK in c)
SANS = next(c for _l, c in MENU if vm_profiles.ODOO_MARK not in c)


def contexte():
    todo = TODO.__new__(TODO)
    mod = todo._qemu_import_module()
    todo._qemu_list_domains = lambda: []
    todo._qemu_branch_list = lambda: ["develop", "master"]
    return todo._qemu_form_context(mod)


# Les fixtures viennent de l'épreuve qui les tient déjà, chargée PAR SON
# CHEMIN : « test » est aussi un paquet de la bibliothèque standard, et un
# import par son nom y mènerait. Une seconde copie dériverait de la sienne.
def _fixtures():
    import importlib.util

    chemin = Path(__file__).resolve().parent / "test_qemu_deploy_posture.py"
    spec = importlib.util.spec_from_file_location("tqdp_fixtures", chemin)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.FORM, mod.VM_UNE


FORM, VM_UNE = _fixtures()


class Ecran:
    """Le formulaire PILOTÉ : on presse F5 et on lit ce qu'il fait."""

    def __init__(self, posture, commande):
        self.posture = posture
        self.commande = commande
        self.avertissements = []
        self.deployees = []

    def jouer(self, coups=1):
        async def scenario():
            app = run_deploy_form(contexte(), run_app=False)
            async with app.run_test(size=(200, 60)) as pilote:
                await pilote.pause()
                app.vms = [dict(VM_UNE)]
                app.rows = []
                # La saisie est REMPLACÉE, pas simulée : ce qu'on éprouve
                # est la règle du couple, pas la façon de remplir l'écran.
                app._form_values = lambda: dict(
                    FORM,
                    posture=self.posture,
                    install={"cmd": self.commande, "label": "banc"},
                )
                app.notify = lambda message, **k: self.avertissements.append(
                    (str(message), k.get("severity"))
                )
                app.exit = lambda *a, **k: None
                for _ in range(coups):
                    app.action_deploy()
                    await pilote.pause()
                self.deployees = list(
                    (app._result.get("spec") or {}).get("vms", [])
                )

        asyncio.run(scenario())
        return self


def contexte_pve():
    """Le contexte du second écran, PRIS dans l'épreuve qui le tient déjà.

    Chargé par son CHEMIN : « test » est aussi un paquet de la
    bibliothèque standard, et un import par son nom y mènerait.
    """
    import importlib.util

    chemin = Path(__file__).resolve().parent / "test_proxmox_form.py"
    spec = importlib.util.spec_from_file_location("tpf_fixtures", chemin)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    ctx = mod.contexte()
    # Les mêmes clés que le menu Proxmox construit : le contexte de banc
    # est écrit à la main et ne les portait pas.
    ctx["posture"] = "open"
    ctx["posture_choices"] = vm_profiles.choices()
    ctx["posture_screen"] = {
        nom: vm_profiles.screen_line(nom, after_boot=True)
        for _libelle, nom in vm_profiles.choices()
    }
    return ctx


class EcranPve(Ecran):
    """Le second écran, piloté de la même façon que le premier."""

    def jouer(self, coups=1):
        from script.todo.proxmox_deploy_form import run_proxmox_form

        async def scenario():
            app = run_proxmox_form(contexte_pve(), run_app=False)
            async with app.run_test(size=(200, 60)) as pilote:
                await pilote.pause()
                app.vms = [dict(VM_UNE, vmid=100)]
                app._form_values = lambda: dict(
                    FORM_PVE,
                    posture=self.posture,
                    install={"cmd": self.commande, "label": "banc"},
                )
                app.notify = lambda message, **k: self.avertissements.append(
                    (str(message), k.get("severity"))
                )
                app.exit = lambda *a, **k: None
                for _ in range(coups):
                    app.action_deploy()
                    await pilote.pause()
                self.deployees = list((app.result or {}).get("vms", []))

        asyncio.run(scenario())
        return self


FORM_PVE = {
    "host": {"target": "hote"},
    "storage": "local-lvm",
    "bridge": "vmbr0",
    "res_label": "x1",
    "ssh_key": "",
    "start": True,
    "add_ssh_config": False,
    "monitor": False,
    "parallelism": 1,
}


class TestLeCoupleAuMomentDuChoix(unittest.TestCase):
    def test_the_bench_finds_both_kinds_of_install(self):
        """Contrôle du banc : sans les deux, les épreuves suivantes
        compareraient une commande à elle-même."""
        self.assertIn(vm_profiles.ODOO_MARK, AVEC)
        self.assertNotIn(vm_profiles.ODOO_MARK, SANS)

    def test_the_rule_is_the_one_the_module_states(self):
        """Le formulaire ne recompose pas la règle : il la demande."""
        self.assertEqual(
            vm_profiles.SERVES_NOTHING,
            vm_profiles.check_install("local-webui", SANS),
        )
        self.assertEqual(
            vm_profiles.INSTALL_OK,
            vm_profiles.check_install("local-webui", AVEC),
        )

    def test_a_posture_chosen_under_another_label_is_untouched(self):
        """La même posture sert légitimement autre chose : c'est la raison
        même pour laquelle le registre sépare les deux."""
        for libelle in ("Sandbox", "VM Connecté", "VM paranoid"):
            with self.subTest(libelle=libelle):
                self.assertEqual(
                    vm_profiles.INSTALL_OK,
                    vm_profiles.check_install(libelle, SANS),
                )


class TestLEcranPreVientPuisLaisseFaire(unittest.TestCase):
    """Un avertissement et non un refus : servir autre chose sur cette
    posture reste légitime, et le second F5 vaut confirmation.

    La langue est ÉPINGLÉE en anglais : le message est TRADUIT, et
    comparer un mot ferait dépendre le verdict de ce qu'une autre épreuve
    a laissé dans `_current_lang`.
    """

    # L'écran piloté. Une sous-classe le remplace, et hérite de chaque
    # épreuve écrite ici sans en recopier une seule.
    ECRAN = Ecran

    def setUp(self):
        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = "en"

    def test_the_bench_deploys_when_nothing_is_wrong(self):
        """Contrôle du banc : si le pilotage n'aboutissait jamais, les
        épreuves suivantes seraient vertes sans rien mesurer."""
        ecran = self.ECRAN("local-only", AVEC).jouer()
        self.assertTrue(ecran.deployees)

    def test_the_first_press_warns_and_does_not_deploy(self):
        ecran = self.ECRAN("local-only", SANS).jouer()
        self.assertEqual([], ecran.deployees)
        self.assertTrue(ecran.avertissements)

    def test_the_warning_says_what_is_wrong(self):
        ecran = self.ECRAN("local-only", SANS).jouer()
        message, _severite = ecran.avertissements[-1]
        self.assertIn("no Odoo", message)

    def test_it_warns_and_never_refuses(self):
        """Une sévérité d'erreur se lit comme un refus, et il n'y en a
        pas : la posture sert légitimement autre chose."""
        ecran = self.ECRAN("local-only", SANS).jouer()
        _message, severite = ecran.avertissements[-1]
        self.assertEqual("warning", severite)

    def test_the_second_press_goes_through(self):
        """Sans l'accusé, l'écran avertirait à chaque F5 et on ne pourrait
        JAMAIS déployer ce couple — ce qui est un refus déguisé."""
        ecran = self.ECRAN("local-only", SANS).jouer(coups=2)
        self.assertTrue(ecran.deployees)

    def test_a_sound_pair_never_warns(self):
        """Contrôle positif : avertir toujours ne dirait plus rien."""
        ecran = self.ECRAN("local-only", AVEC).jouer()
        self.assertEqual([], ecran.avertissements)

    def test_another_label_on_the_same_posture_is_untouched(self):
        """« Sandbox » sur une installation sans Odoo est parfaitement
        sensé, et l'écran ne doit rien dire."""
        ecran = self.ECRAN("open", SANS).jouer()
        self.assertEqual([], ecran.avertissements)
        self.assertTrue(ecran.deployees)


class TestLeSecondEcranPrevientAussi(TestLEcranPreVientPuisLaisseFaire):
    """Les MÊMES épreuves, sur l'écran Proxmox.

    Hériter plutôt que recopier : une épreuve ajoutée au premier écran
    couvre le second le jour où elle est écrite, et une divergence entre
    les deux devient impossible à laisser passer.
    """

    ECRAN = EcranPve


if __name__ == "__main__":
    unittest.main()
