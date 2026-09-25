#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le menu Set-OPS : todo pilote le moteur, il ne le recopie pas.

Le moteur Set-OPS reste la seule source de vérité de ses gestes : un geste
s'ajoute ici en LANÇANT le moteur, jamais en recopiant ce qu'il fait. Le
menu n'affiche que ce qui existe — l'écran d'état de l'intégration, en
lecture seule ; les familles de gestes s'y ajoutent par sections.

Ses entrées se déclarent par « method » et non par un numéro : c'est la
forme dont le rang ne dépend pas de ce qui est posé plus haut.
"""

from __future__ import annotations

import os
import shlex

import click

from script.setops import ansible_env, engine, state
from script.todo import state_screen
from script.todo.todo_i18n import t

# La racine d'ERPLibre, deux niveaux au-dessus de ce fichier : c'est sous
# elle que le relevé lit le manifeste du moteur et le chemin qu'il déclare.
RACINE = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)


class SetopsMenuMixin:
    """Menu Set-OPS, mixin de la classe TODO : ses entrées vivent sur la
    même instance que celles des autres menus."""

    def prompt_execute_setops(self):
        """Le menu Set-OPS. Rend False pour rester dans le menu appelant."""
        choices = [
            {"section": t("Integration")},
            {
                "prompt_description": t(
                    "Set-OPS - State of the integration, line by line"
                ),
                "method": "_setops_state",
            },
            {
                "prompt_description": t(state.GESTE_ANSIBLE),
                "method": "_setops_ansible_env",
            },
        ]
        help_info = self.fill_help_info(choices)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif not self._menu_dispatch_extra(choices, status):
                print(t("Command not found !"))

    def _setops_state(self):
        """Les dix lignes de l'intégration de Set-OPS sur ce poste.

        LECTURE SEULE : le relevé de `script.setops.state` ne lance ni
        `make`, ni réseau, et n'écrit rien. Les lignes se décident sur ce
        relevé et s'impriment par le rendu commun des écrans d'état ; chaque
        ligne « à régler ici » nomme le geste qui la règle, et l'écran ne le
        lance pas.
        """
        print(f"\n{t('Set-OPS integration, line by line')}")
        vu = state.releve(RACINE)
        for ligne in state_screen.render(state.lignes(vu)):
            print(ligne)
        print(
            "\n  "
            + t(
                "Each « to set up here » line names the gesture that"
                " settles it; this screen launches nothing."
            )
        )

    def _setops_ansible_env(self):
        """Pose le venv Ansible du contrôleur, ou refait celui qui a dérivé.

        NE LANCE RIEN SANS L'AVOIR MONTRÉ : les commandes s'affichent telles
        qu'elles partiront, la question vient après. Chaque verdict est LU et
        une étape qui échoue arrête la suite — les suivantes bâtiraient sur
        un venv absent et n'échoueraient qu'à la fin, sur un message qui ne
        nomme plus la cause.
        """
        print(f"\n🤖 {t('Set-OPS - Ansible environment (set it up)')}")
        decl = engine.declaration(RACINE)
        moteur = (
            os.path.join(RACINE, decl.path)
            if decl is not None and decl.path
            else ""
        )
        if not moteur or not os.path.isdir(moteur):
            print(
                f"  ✗ {t('the engine is not here yet; see the state screen')}"
            )
            return
        plage = ansible_env.plage_ansible(moteur)
        if ansible_env.specifieur(plage) is None:
            refus = t("the engine's ansible-core range is unreadable")
            print(f"  ✗ {refus}")
            return

        venv = ansible_env.chemin_venv(RACINE)
        posee = (
            ansible_env.version_posee(RACINE, ansible_env.PAQUET_ANSIBLE)
            if os.path.isdir(venv)
            else None
        )
        conforme = ansible_env.dans_la_plage(posee, plage) is True
        print(f"  {t('Engine')}: {decl.path}")
        print(f"  {t('Range')}: {plage}")
        if conforme:
            print(
                f"  {t('Already installed')}: "
                f"{ansible_env.PAQUET_ANSIBLE} {posee}"
            )
            print(f"  {t('Nothing to do; the state screen says the rest.')}")
            return

        python, provenance = ansible_env.interprete()
        if python is None:
            self._setops_dire_python_manquant()
            return
        print(f"  {t('Interpreter')}: {python} ({provenance})")

        refaire = os.path.isdir(venv)
        if refaire:
            print(
                f"  {t('Found')}: {ansible_env.VENV}, "
                + (
                    t("ansible-core {version}").format(version=posee)
                    if posee
                    else t("no readable ansible-core")
                )
            )
        pas = ansible_env.etapes(RACINE, moteur, python, plage, refaire)
        print(f"\n  {t('What will run:')}")
        for rang, etape in enumerate(pas, 1):
            print(f"    {rang}. {ansible_env.montre(etape)}")
        if not self._is_yes(input(f"\n{t('Set it up? (y/N): ')}")):
            print(t("Cancelled."))
            return

        for rang, etape in enumerate(pas, 1):
            print(f"\n▶ {rang}/{len(pas)} {ansible_env.montre(etape)}")
            code = ansible_env.poser(etape, RACINE)
            if code:
                echec = t("step {n} failed (code {code}); stopping").format(
                    n=rang, code=code
                )
                print(f"  ✗ {echec}")
                return
        self._setops_verifier_ansible(moteur, plage)

    def _setops_dire_python_manquant(self):
        """Nomme l'interpréteur qui manque, et la commande qui le pose.

        Le menu ne pose pas un gestionnaire de versions de lui-même : il
        montre le geste, l'opérateur décide.
        """
        mineur = ansible_env.MINEUR_CIBLE
        manque = t("no python{minor} on this station").format(minor=mineur)
        print(f"  ✗ {manque}")
        geste = ansible_env.geste_mise()
        if geste is None:
            faute = t("install python{minor}, or mise, then come back")
            print(f"    {faute.format(minor=mineur)}")
        else:
            print(f"    {shlex.join(geste)}")

    def _setops_verifier_ansible(self, moteur, plage):
        """Les quatre constats d'après la pose, dans l'ordre où ils cassent.

        La vérification MESURE `python3` résolu par le PATH du geste, et non
        l'interpréteur du venv appelé par chemin : c'est ce que fera la garde
        du moteur, qui lance `python3` nu.
        """
        print(f"\n  {t('Verification:')}")
        posee = ansible_env.version_posee(RACINE, ansible_env.PAQUET_ANSIBLE)
        self._setops_constat(
            ansible_env.dans_la_plage(posee, plage) is True,
            f"{ansible_env.PAQUET_ANSIBLE} {posee or t('unreadable')}"
            f" / {plage}",
        )
        mineur = ansible_env.mineur_du_path(RACINE, moteur)
        self._setops_constat(
            mineur == ansible_env.MINEUR_CIBLE,
            t("python3 on the gesture PATH: {lu} (target {cible})").format(
                lu=mineur or t("unreadable"), cible=ansible_env.MINEUR_CIBLE
            ),
        )
        for nom, epinglee in ansible_env.bibliotheques_epinglees(moteur):
            vue = ansible_env.version_posee(RACINE, nom)
            self._setops_constat(
                vue == epinglee, f"{nom} {vue or t('absent')} / {epinglee}"
            )
        for nom, epinglee in ansible_env.collections_epinglees(moteur):
            vue = ansible_env.version_collection(moteur, nom)
            self._setops_constat(
                vue == epinglee, f"{nom} {vue or t('absent')} / {epinglee}"
            )

    @staticmethod
    def _setops_constat(ok, texte):
        print(f"    {'✓' if ok else '✗'} {texte}")
