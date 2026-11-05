#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le menu « Analyse module » : les modules Odoo du checkout.

Ici on DEMANDE (quels dépôts, faut-il `addons/addons`) et on affiche ; la
comparaison elle-même vit dans `script/git/git_module_diff.py`, qui se lance
aussi seul en ligne de commande. Rien n'y écrit, rien n'y va sur le réseau.
"""

import os
import sys

import click

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.append(new_path)

from script.git import (  # noqa: E402
    git_freeze_diff,
    git_module_diff,
    repo_upgrade,
)
from script.todo.todo_couleur import retour  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402

RACINE = new_path


class ModuleMenuMixin:
    def prompt_execute_module_analysis(self):
        print(f"🧩 {t('Analyse the Odoo modules of the checkout')}")
        choices = [
            {"section": t("Update")},
            {
                "prompt_description": t(
                    "🔀 Modules that differ from the version branch"
                )
            },
            {
                "prompt_description": t(
                    "🔁 Modules a freeze comparison changed (old → new)"
                )
            },
        ]
        help_info = self.fill_help_info(choices)
        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self._module_analysis_diff(git_module_diff.MODE_BRANCHE)
            elif status == "2":
                self._module_analysis_diff(git_module_diff.MODE_GEL)
            else:
                print(t("Command not found !"))

    def _module_analysis_choisir(self):
        """(gauche, droite) de la comparaison de gels qui désigne les
        dépôts, ou None pour revenir."""
        print(
            f"🔀 {t('Repositories: those this freeze comparison sees changed')}"
        )
        print(f"  [1] 💻 {t('Committed freeze → clones (real state)')}")
        print(f"  [2] 📝 {t('Written freeze (manifest/) → clones')}")
        print(
            f"  [3] 🚧 {t('Committed freeze → written freeze, not committed')}"
        )
        print(f"  [4] ⏪ {t('Previous freeze → last freeze')}")
        print(f"  {retour(t('Back'))}")
        choix = input("  : ").strip()
        if choix in git_module_diff.COMPARAISONS:
            return git_module_diff.COMPARAISONS[choix]
        if choix == "4":
            paire = git_freeze_diff.previous_freeze(RACINE)
            if not paire:
                print(f"⚠  {t('Fewer than two commits changed a freeze.')}")
            return paire
        if choix not in ("", "0"):
            print(t("Command not found !"))
        return None

    def _module_analysis_diff(self, mode):
        """Les modules qui diffèrent dans chaque dépôt retenu, selon `mode`
        (`git_module_diff.analyser`), un par ligne, en ordre alphabétique.
        Rend 0, ou 2 sans version d'Odoo ou sur une révision inconnue."""
        version = repo_upgrade.version_active(RACINE)
        if not version:
            print(f"❌ {t('No Odoo version found')}")
            return 2
        cas = self._module_analysis_choisir()
        if not cas:
            return 0
        try:
            depots = git_module_diff.depots_du_choix(RACINE, *cas)
        except ValueError as exc:
            print(f"⚠  {exc}")
            return 2
        hors_manifeste = git_module_diff.depots_addons_addons(RACINE, version)
        if hors_manifeste:
            dossier = os.path.relpath(
                git_module_diff.dossier_addons_addons(RACINE, version), RACINE
            )
            print(
                f"📁 {dossier} : {len(hors_manifeste)}"
                f" {t('git repositories, absent from the manifest')}"
            )
            if mode == git_module_diff.MODE_GEL:
                print(
                    f"   {t('Outside any freeze, they compare to their branch.')}"
                )
            if click.confirm(f"  {t('Include them?')}", default=True):
                depots += [
                    git_module_diff.depot_hors_manifeste(RACINE, d)
                    for d in hors_manifeste
                ]
        resultat = git_module_diff.analyser(RACINE, version, depots, mode)
        print("\n".join(rendre(resultat, len(depots), version, mode)))
        return 0


def rendre(resultat, nb_depots, version, mode=git_module_diff.MODE_BRANCHE):
    """Les lignes du résultat : le contexte, les dépôts mis à part, puis
    les modules seuls, un par ligne, pour qu'ils se copient tels quels."""
    if mode == git_module_diff.MODE_GEL:
        contexte = t("repositories, from the old to the new commit")
    else:
        contexte = f"{t('repositories compared with')} <remote>/{version}"
    lignes = [
        f"🔀 {nb_depots} {contexte}"
        f" {t('(references of the last fetch, no network)')}"
    ]
    for chemin, ref in resultat["repli"]:
        lignes.append(
            f"↪  {t('No version branch, manifest branch taken:')}"
            f" {ref} : {chemin}"
        )
    for chemin, refs in resultat["sans_branche"]:
        lignes.append(f"⚠  {t('No remote branch')} {refs} : {chemin}")
    for chemin in resultat["sans_ancien"]:
        lignes.append(f"·  {t('New project, no old commit:')} {chemin}")
    for chemin, sha in resultat["absents"]:
        lignes.append(
            f"⚠  {t('Commit missing from the clone, fetch it:')}"
            f" {sha} : {chemin}"
        )
    for chemin in resultat["echecs"]:
        lignes.append(f"❌ {t('Git failed:')} {chemin}")
    if not resultat["modules"]:
        lignes.append(f"✅ {t('No module differs.')}")
        return lignes
    lignes.append(f"📋 {len(resultat['modules'])} {t('modules differ:')}")
    lignes.append("")
    lignes.extend(resultat["modules"])
    return lignes
