#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Répertoire git › Worktree : les worktrees du checkout ERPLibre.

Ce fichier pose les questions ; le travail se fait dans
script/git/git_worktree.py, qui liste aussi seul en ligne de commande.

Rien ne s'efface sans un oui : un worktree aux fichiers modifiés n'est
retiré de force qu'après une seconde question qui dit ce qui sera perdu, et
la branche d'un worktree retiré ne part que par `git branch -d`, qui
refuse une branche non fusionnée.

Mixin de la classe TODO : ses méthodes vivent sur la même instance que
celles des autres fichiers, elles s'appellent donc par « self. ».
"""

import os
import sys

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.append(new_path)

from script.git import git_worktree  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402

RACINE = new_path


class GitWorktreeMenuMixin:
    def _git_worktrees(self):
        """Les worktrees du checkout, ou None après avoir dit pourquoi."""
        try:
            return git_worktree.lister(RACINE)
        except ValueError as exc:
            print(f"❌ {exc}")
            return None

    def _git_worktree_afficher(self, worktrees, numeroter=False):
        for rang, worktree in enumerate(worktrees, 1):
            modifies = (
                git_worktree.fichiers_modifies(worktree["path"])
                if worktree["existe"]
                else None
            )
            ligne = git_worktree.decrire(worktree, modifies, traduire=t)
            print(f"  [{rang}] {ligne}" if numeroter else f"  {ligne}")

    def _git_worktree_lister(self):
        """Affiche chaque worktree : chemin, branche, marques. Rend la
        liste, ou None."""
        worktrees = self._git_worktrees()
        if worktrees is None:
            return None
        print(f"🗂  {t('Worktrees of this checkout')}")
        self._git_worktree_afficher(worktrees)
        print("   $ git worktree list")
        return worktrees

    def _git_worktree_creer(self):
        """Un worktree sur une branche : celle qui existe, ou une nouvelle
        partie d'une base. Rend le chemin créé, ou None."""
        worktrees = self._git_worktrees()
        if worktrees is None:
            return None
        branche = input(
            t("Branch of the worktree (Enter to cancel): ")
        ).strip()
        if not branche:
            return None
        tenue = git_worktree.worktree_de_branche(worktrees, branche)
        if tenue:
            print(
                f"⚠ {t('This branch is already checked out in')}"
                f" {tenue['path']}"
            )
            return None
        nouvelle = not git_worktree.branche_existe(RACINE, branche)
        base = None
        if nouvelle:
            base = (
                input(
                    t("New branch: start it from (Enter for master): ")
                ).strip()
                or "master"
            )
        propose = git_worktree.chemin_propose(worktrees[0]["path"], branche)
        chemin = os.path.expanduser(
            input(f"{t('Directory')} ({propose}) : ").strip() or propose
        )
        if os.path.exists(chemin):
            print(f"❌ {t('This directory already exists:')} {chemin}")
            return None
        print(
            "   $ git "
            + " ".join(
                git_worktree.commande_creer(chemin, branche, base, nouvelle)
            )
        )
        code, message = git_worktree.creer(
            RACINE, chemin, branche, base, nouvelle
        )
        if code:
            print(f"❌ {message}")
            return None
        print(f"✅ {t('Worktree created:')} {chemin}")
        print(
            f"   {t('It holds the tracked files only: no venv, no addons, no config.conf. Run the tooling with the venv of the main checkout.')}"
        )
        print(f"   $ cd {chemin}")
        return chemin

    def _git_worktree_choisir(self, worktrees):
        """Un worktree autre que le principal, choisi par son numéro, ou
        None."""
        autres = [w for w in worktrees if not w["principal"]]
        if not autres:
            print(f"  {t('No worktree besides the main checkout.')}")
            return None
        self._git_worktree_afficher(autres, numeroter=True)
        saisie = input(t("Number, Enter to cancel: ")).strip()
        try:
            return autres[int(saisie) - 1] if int(saisie) >= 1 else None
        except (ValueError, IndexError):
            return None

    def _git_worktree_supprimer(self):
        """Retire un worktree après un oui ; de force, ses fichiers
        modifiés perdus, après un second. Propose ensuite de retirer sa
        branche si elle est fusionnée. Rend True si le worktree est
        parti."""
        worktrees = self._git_worktrees()
        if worktrees is None:
            return False
        choisi = self._git_worktree_choisir(worktrees)
        if choisi is None:
            return False
        chemin = choisi["path"]
        modifies = (
            git_worktree.fichiers_modifies(chemin) if choisi["existe"] else 0
        )
        if not self._is_yes(
            input(f"{t('Delete the worktree')} {chemin} ? (y/N) : ")
        ):
            print(t("Nothing to do."))
            return False
        forcer = False
        if modifies or choisi["locked"]:
            raison = (
                f"{modifies} {t('modified files')}"
                if modifies
                else t("locked")
            )
            print(f"⚠ {chemin} : {raison}")
            forcer = self._is_yes(
                input(t("These changes will be LOST. Delete anyway? (y/N): "))
            )
            if not forcer:
                print(t("Nothing to do."))
                return False
        code, message = git_worktree.supprimer(RACINE, chemin, forcer)
        if code:
            print(f"❌ {message}")
            return False
        print(f"✅ {t('Worktree deleted:')} {chemin}")
        branche = choisi["branch"]
        if branche and self._is_yes(
            input(
                f"{t('Also delete the branch')} {branche}"
                f" {t('if it is merged? (y/N): ')}"
            )
        ):
            code, message = git_worktree.supprimer_branche(RACINE, branche)
            print(f"{'❌' if code else '✅'} {message}")
        return True

    def _git_worktree_nettoyer(self):
        """Montre les entrées dont le répertoire a disparu, puis les
        oublie après un oui. Rend le nombre d'entrées montrées."""
        code, lignes = git_worktree.nettoyer(RACINE, simuler=True)
        if code:
            print(f"❌ {' '.join(lignes)}")
            return 0
        if not lignes:
            print(f"  ✓ {t('No stale worktree entry.')}")
            return 0
        for ligne in lignes:
            print(f"  {ligne}")
        if self._is_yes(input(t("Forget these entries? (y/N): "))):
            code, sortie = git_worktree.nettoyer(RACINE, simuler=False)
            print(f"{'❌' if code else '✅'} $ git worktree prune")
            for ligne in sortie:
                print(f"  {ligne}")
        return len(lignes)

    def _git_worktree_branche(self):
        """Dit quel worktree tient une branche : git refuse de l'extraire
        ailleurs tant qu'elle y est. Rend ce worktree, ou None."""
        worktrees = self._git_worktrees()
        if worktrees is None:
            return None
        branche = input(t("Branch to find (Enter to cancel): ")).strip()
        if not branche:
            return None
        tenue = git_worktree.worktree_de_branche(worktrees, branche)
        if tenue:
            print(f"📍 {branche} → {tenue['path']}")
            print(f"   $ cd {tenue['path']}")
        elif git_worktree.branche_existe(RACINE, branche):
            print(f"  {branche} : {t('checked out in no worktree.')}")
        else:
            print(f"  {branche} : {t('no such local branch.')}")
        return tenue
