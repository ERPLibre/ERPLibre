#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Mettre à jour les dépôts git, et les mettre à niveau sur leur amont.

Deux gestes que tout oppose, et que le même mot recouvrait.

La MISE À JOUR déplace chaque dépôt sur la pointe de la branche que le
manifeste lui donne. Elle ne pose aucune question, ne peut pas entrer en
conflit, et se lance tous les matins.

La MISE À NIVEAU va chercher l'amont dont un fork DESCEND — un autre dépôt,
chez une autre organisation — et propose d'y rejouer les commits que le fork
porte en propre. Elle peut entrer en conflit, elle réécrit l'historique, et
elle se décide après avoir regardé.

D'où la séparation des entrées, et d'où le fait que la mise à niveau se
constate AVANT de s'appliquer : sa passe à sec amène l'amont dans FETCH_HEAD
et prédit la fusion en mémoire, sans déplacer de référence ni toucher l'arbre
de travail. Le constat coûte quelques secondes sur l'ensemble des forks, et
se rejoue autant de fois qu'on veut.

Module à part plutôt que méthodes de `TODO` : le fichier principal passe les
cinq mille lignes, et chaque sujet y a désormais le sien.
"""

import os
import sys

import click

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.append(new_path)

from script.git import repo_upgrade  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402

# La racine du dépôt. Le lanceur de git-repo porte un shebang RELATIF vers le
# venv : lancé depuis un autre répertoire, il ne trouve pas son interpréteur
# et meurt sur « bad interpreter ». Toutes ses invocations partent donc d'ici.
RACINE = new_path
REPO_BIN = ".venv.erplibre/bin/repo"


class GitRepoMenuMixin:
    def prompt_execute_git_repo(self):
        version = repo_upgrade.version_active(RACINE) or "?"
        forks = repo_upgrade.etat_forks(version)
        print(f"🔃 {t('Update and upgrade the git repositories')}")
        print(f"   Odoo {version} · {len(forks)} {t('forks')}")
        choices = [
            {"section": t("Update")},
            {"prompt_description": t("🔄 Synchronize the repositories")},
            {"prompt_description": t("🔁 Reconfigure and synchronize")},
            {"section": t("Upgrade")},
            {"prompt_description": t("🔍 Upgrade — dry run")},
            {"section": t("Observe")},
            {"prompt_description": t("🔗 Fork and upstream status")},
        ]
        help_info = self.fill_help_info(choices)
        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self._git_repo_sync()
            elif status == "2":
                self._git_repo_reconfigurer()
            elif status == "3":
                self._git_repo_a_sec()
            elif status == "4":
                self._git_repo_etat_forks()
            else:
                print(t("Command not found !"))

    def _git_repo_sync(self):
        """Ramène chaque dépôt sur la pointe de sa branche de manifeste.

        Le chemin court : il ne régénère pas le manifeste local. Une
        modification apportée aux fichiers de `manifest/` ne prendra donc
        effet qu'après une reconfiguration, et l'entrée voisine est là pour
        cela.
        """
        parallele = os.cpu_count() or 4
        cmd = f"{REPO_BIN} sync -c -j{parallele}"
        print(f"  {t('Will execute:')} {cmd}")
        status = self.execute.exec_command_live(
            f"cd {RACINE} && {cmd}", source_erplibre=False
        )
        if status:
            print(f"⚠  {t('Synchronization failed.')} ({status})")
        else:
            print(f"✅ {t('Repositories synchronized.')}")
        return status

    def _git_repo_reconfigurer(self):
        """Régénère le manifeste local, puis synchronise.

        Le chemin complet, et le seul qui prenne en compte une modification
        des fichiers de `manifest/` : il refond les fragments en un manifeste
        local et relance `repo init` avant de synchroniser.
        """
        cmd = "make repo_configure_all"
        print(f"  {t('Will execute:')} {cmd}")
        status = self.execute.exec_command_live(
            f"cd {RACINE} && {cmd}", source_erplibre=False
        )
        if status:
            print(f"⚠  {t('Reconfiguration failed.')} ({status})")
        else:
            print(f"✅ {t('Repositories reconfigured and synchronized.')}")
        return status

    def _git_repo_a_sec(self):
        """Constate ce qu'une mise à niveau ferait, sans rien écrire.

        Rend le nombre de dépôts qui demandent une décision, ce qui donne à
        l'appelant de quoi s'arrêter là quand il n'y a rien à faire.
        """
        version = repo_upgrade.version_active(RACINE) or "?"
        print(f"🔍 {t('Upgrade dry run')} — Odoo {version}")
        print(f"   {t('Querying each upstream, this takes a few seconds.')}")
        lst = repo_upgrade.passe_diagnostic(version, racine=RACINE)
        print()
        print(repo_upgrade.render_diagnostic(lst, version, colour=True))
        a_decider = [
            x
            for x in lst
            if x["verdict"] in ("a_rebaser", "en_conflit", "absorbe")
        ]
        return len(a_decider)

    def _git_repo_etat_forks(self):
        """D'où descend chaque fork, et l'amont répond-il encore.

        Interroge le réseau : c'est le seul moyen de distinguer une branche
        amont déclarée d'une branche amont qui existe.
        """
        version = repo_upgrade.version_active(RACINE) or "?"
        print(f"🔗 {t('Fork and upstream status')} — Odoo {version}")
        lst = repo_upgrade.etat_forks(version, verifier=True)
        print()
        print(repo_upgrade.render(lst, True, colour=True))
        return len(
            [x for x in lst if x["etat"] in repo_upgrade.ETATS_A_CORRIGER]
        )
