#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Répertoire git › les dépôts des manifestes : forker pour une
organisation, ajouter un dépôt, créer une branche, poser le remote amont.

Ce fichier pose les questions ; le travail se fait dans
script/git/manifest_repo.py, qui se lance aussi seul en ligne de commande.

Le fork décide de trois choses, chacune avec un défaut :
- l'amont d'un projet DÉJÀ forké : celui d'origine (OCA) ou l'ancien fork
  (ERPLibre) — deux usages, aucun n'est le bon partout ;
- les branches copiées : la branche active seule, posée par une ref sur le
  commit gelé, ou toutes celles de la source ;
- les versions d'Odoo dont le manifeste change : l'active par défaut.

Mixin de la classe TODO : ses méthodes vivent sur la même instance que
celles des autres fichiers, elles s'appellent donc par « self. ».
"""

import os
import sys

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.append(new_path)

from script.git import github_fork, manifest_fork, manifest_repo  # noqa: E402
from script.git import repo_upgrade  # noqa: E402
from script.git.manifest_repo import (  # noqa: E402,F401
    branche_du_projet,
    fichier_du_projet,
    projets_github,
    url_du_projet,
    versions_des_manifestes,
    versions_du_depot,
)
from script.todo.todo_i18n import t  # noqa: E402

RACINE = new_path

MESSAGE_JETON = (
    "No GitHub token: export EL_GITHUB_TOKEN in the shell that opens TODO"
    " (env_var.sh is versioned)."
)


def clones(version, racine=RACINE):
    """(remotes, [projet]) des projets de `version` dont le clone existe,
    triés par chemin."""
    remotes, projets = repo_upgrade.lire_manifestes(version)
    liste = [
        p
        for p in projets.values()
        if p.get("path") and os.path.isdir(os.path.join(racine, p["path"]))
    ]
    return remotes, sorted(liste, key=lambda p: p["path"])


class GitForkMenuMixin:
    # ── Choisir ──────────────────────────────────────────────────────

    def _git_filtrer(self, elements, texte):
        """Les `elements` dont `texte(e)` contient le filtre tapé, numérotés
        et affichés ; rend celui qu'on choisit, ou None."""
        filtre = (
            input(
                t(
                    "Filter (part of the path or of the repository), Enter for all: "
                )
            )
            .strip()
            .lower()
        )
        retenus = [e for e in elements if filtre in texte(e).lower()]
        if not retenus:
            print(f"  {t('No repository matches.')}")
            return None
        for i, e in enumerate(retenus, 1):
            print(f"  [{i}] {texte(e)}")
        saisie = input(t("Repository number, Enter for none: ")).strip()
        if not (saisie.isdigit() and 1 <= int(saisie) <= len(retenus)):
            return None
        return retenus[int(saisie) - 1]

    def _git_fork_choisir_projet(self, liste):
        """(projet, propriétaire, dépôt) choisi, ou None."""
        return self._git_filtrer(
            liste, lambda r: f"{r[0].get('path')}  ({r[1]}/{r[2]})"
        )

    def _git_choisir_clone(self):
        """(remotes, projet, chemin du clone) choisi parmi les clones de la
        version active, ou None."""
        version = repo_upgrade.version_active(RACINE)
        if not version:
            print(f"❌ {t('No Odoo version found')}")
            return None
        remotes, liste = clones(version)
        projet = self._git_filtrer(liste, lambda p: p.get("path", ""))
        if projet is None:
            return None
        return remotes, projet, os.path.join(RACINE, projet["path"])

    def _git_choisir_version(self, defaut):
        """La version d'Odoo tapée parmi celles qui ont un manifeste, ou
        `defaut` sur Entrée ; None pour une version sans manifeste."""
        versions = versions_des_manifestes()
        saisie = input(
            f"{t('Odoo version')} ({', '.join(versions)}) [{defaut}] : "
        ).strip()
        version = saisie or defaut
        if version not in versions:
            print(f"⚠ {version} : {t('no manifest for this version.')}")
            return None
        return version

    # ── Forker ───────────────────────────────────────────────────────

    def _git_fork_organisation(self, version=None, preselection=None):
        """Le parcours complet ; rend 0, ou 2 sur un refus ou une erreur.
        `preselection` saute le choix du projet, dans `version`."""
        version = version or repo_upgrade.version_active(RACINE)
        if not version:
            print(f"❌ {t('No Odoo version found')}")
            return 2
        remotes, liste = projets_github(version)
        choix = preselection or self._git_fork_choisir_projet(liste)
        if choix is None:
            return 0
        projet, proprietaire, depot = choix
        organisation = input(
            t("Organisation (or GitHub account) that receives the fork: ")
        ).strip()
        if not organisation:
            return 0
        if organisation.lower() == proprietaire.lower():
            print(
                f"⚠ {t('The repository already belongs to this organisation.')}"
            )
            return 2
        mode = self._git_fork_choisir_mode(projet, remotes)
        branche = branche_du_projet(projet)
        toutes = self._git_fork_choisir_branches(branche)
        jeton = github_fork.jeton(RACINE)
        if not jeton:
            print(f"⚠ {t(MESSAGE_JETON)}")
            return 2
        print(
            f"  {proprietaire}/{depot} → {organisation}/{depot}"
            f" · {t('all branches') if toutes else branche}"
        )
        if not self._is_yes(input(t("Fork it? (y/N): "))):
            return 0
        client = github_fork.ClientGitHub(jeton)
        print(f"  {t('Waiting for GitHub to create the fork…')}")
        try:
            fork, cree, posee = manifest_repo.forker(
                client, proprietaire, depot, organisation, toutes, projet
            )
        except github_fork.ErreurGitHub as exc:
            print(f"❌ GitHub : {exc}")
            return 2
        libelle = t("Fork created:") if cree else t("Fork already present:")
        print(f"  ✓ {libelle} {fork.get('html_url')}")
        if posee:
            print(
                f"  ✓ {t('Branch created in the fork:')}"
                f" {posee[0]} @ {posee[1][:12]}"
            )
        if not self._is_yes(
            input(t("Change the manifest to take this fork? (y/N): "))
        ):
            return 0
        par_version = versions_du_depot(proprietaire, depot)
        print(
            f"  {t('Versions whose manifest clones this repository:')}"
            f" {', '.join(par_version) or '-'}"
        )
        saisie = input(
            f"{t('Versions to change, separated by commas (Enter: the active one)')}"
            f" [{version}] : "
        ).strip()
        voulues = [v.strip() for v in saisie.split(",") if v.strip()] or [
            version
        ]
        resultats = manifest_repo.prendre_le_fork(
            client,
            fork,
            proprietaire,
            depot,
            organisation,
            mode,
            voulues,
            toutes,
        )
        changees = []
        for v, fichier, erreur in resultats:
            if erreur:
                print(f"❌ {v} : {erreur}")
            elif fichier:
                changees.append(v)
                print(f"  ✓ {os.path.relpath(fichier, RACINE)}")
        if not changees:
            return 0
        print(
            f"  {t('Commit manifest/, then synchronise the repositories so the clone follows the fork.')}"
        )
        if version in changees and self._is_yes(
            input(t("Add the upstream remote to the local clone now? (y/N): "))
        ):
            self._git_amont_de(version, projet.get("path"))
        return 0

    def _git_fork_choisir_mode(self, projet, remotes):
        """AMONT_ORIGINE ou AMONT_FORK. Un projet qui n'est pas un fork n'a
        que son ancienne source pour amont : rien à demander."""
        amont = manifest_fork.amont_actuel(projet, remotes)
        if not amont:
            return manifest_fork.AMONT_FORK
        print(
            f"  {t('This repository is already a fork. Upstream of the new fork:')}"
        )
        print(f"  [1] {amont} — {t('keep the original upstream (default)')}")
        print(
            f"  [2] {projet.get('remote')} — {t('the current fork becomes the upstream')}"
        )
        saisie = input("  : ").strip()
        return (
            manifest_fork.AMONT_FORK
            if saisie == "2"
            else manifest_fork.AMONT_ORIGINE
        )

    def _git_fork_choisir_branches(self, branche):
        """Vrai pour copier toutes les branches."""
        print(f"  {t('Branches to copy into the fork:')}")
        print(f"  [1] {branche} — {t('the active branch only (default)')}")
        print(f"  [2] {t('every branch of the source')}")
        return input("  : ").strip() == "2"

    # ── Ajouter un dépôt ─────────────────────────────────────────────

    def _git_ajouter_depot(self):
        """Ajoute un dépôt GitHub au manifeste de la version choisie, puis
        propose de le forker. Rend 0, ou 2 sur un refus."""
        url = input(t("GitHub URL of the repository to add: ")).strip()
        if not url:
            return 0
        if not github_fork.depot_github(url):
            print(f"⚠ {t('Not a GitHub repository URL.')}")
            return 2
        actif = repo_upgrade.version_active(RACINE)
        version = self._git_choisir_version(actif)
        if not version:
            return 2
        branche = (
            input(f"{t('Branch to follow')} [{version}] : ").strip() or version
        )
        fichier = os.path.join(
            manifest_repo.dossier_manifestes(),
            f"git_manifest_odoo{version}.xml",
        )
        with open(fichier, encoding="utf-8") as fh:
            gele = manifest_repo.est_gele(fh.read())
        invite = "Freeze it on the head of the branch? (Y/n): "
        if not gele:
            invite = "Freeze it on the head of the branch? (y/N): "
        reponse = input(t(invite)).strip()
        geler = self._is_yes(reponse) if reponse else gele
        print(f"  {t('Checking the branch on GitHub…')}")
        try:
            fichier, plan, gel = manifest_repo.ajouter_depot(
                url, version, branche, geler
            )
        except ValueError as exc:
            print(f"❌ {exc}")
            return 2
        print(
            f"  ✓ {os.path.relpath(fichier, RACINE)} : {plan['path']}"
            f" ({plan['remote']}, {plan['revision']}"
            f"{' @ ' + gel[:12] if gel else ''})"
        )
        print(
            f"  {t('Commit manifest/, then synchronise the repositories to clone it.')}"
        )
        if self._is_yes(input(t("Fork it for an organisation now? (y/N): "))):
            _remotes, liste = projets_github(version)
            choix = next(
                (r for r in liste if r[0].get("path") == plan["path"]), None
            )
            if choix:
                return self._git_fork_organisation(version, choix)
        return 0

    # ── Branche et remote amont d'un clone ───────────────────────────

    def _git_creer_branche(self):
        """Crée une branche dans le clone choisi, s'y place, et la pousse
        vers le remote tapé, si un est tapé. Rend 0, ou 2 sur un échec."""
        choix = self._git_choisir_clone()
        if choix is None:
            return 0
        _remotes, projet, chemin = choix
        nom = input(t("Name of the new branch: ")).strip()
        if not nom:
            return 0
        depart = input(t("Start from (Enter: the current commit): ")).strip()
        remotes = manifest_repo.remotes_du_clone(chemin)
        pousser = input(
            f"{t('Push it to the remote (Enter: no push)')}"
            f" ({', '.join(remotes) or '-'}) : "
        ).strip()
        if pousser and pousser not in remotes:
            print(f"⚠ {pousser} : {t('no such remote in this clone.')}")
            return 2
        etapes = manifest_repo.brancher(chemin, nom, depart or None, pousser)
        for etape, code, sortie in etapes:
            marque = "✓" if not code else "❌"
            print(
                f"  {marque} {etape} : {sortie.splitlines()[-1] if sortie else ''}"
            )
        return 2 if any(code for _e, code, _s in etapes) else 0

    def _git_ajouter_amont(self):
        """Pose et récupère le remote amont du clone choisi. Rend 0, ou 2."""
        choix = self._git_choisir_clone()
        if choix is None:
            return 0
        remotes, projet, chemin = choix
        return self._git_amont(chemin, projet, remotes)

    def _git_amont_de(self, version, chemin_projet):
        """Le remote amont du clone de `chemin_projet`, relu dans le
        manifeste de `version` que le fork vient de changer."""
        try:
            remotes, projet = manifest_repo.trouver_projet(
                version, chemin_projet
            )
        except ValueError as exc:
            print(f"❌ {exc}")
            return 2
        chemin = os.path.join(RACINE, projet["path"])
        if not os.path.isdir(chemin):
            print(f"⚠ {t('The repository is not cloned yet.')}")
            return 2
        return self._git_amont(chemin, projet, remotes)

    def _git_amont(self, chemin, projet, remotes):
        etat, detail = manifest_repo.ajouter_amont(chemin, projet, remotes)
        if etat in ("ajoute", "present"):
            print(f"  ✓ {t('Upstream remote ready and fetched:')} {detail}")
            return 0
        if etat is None:
            print(f"⚠ {t('No upstream remote:')} {detail}")
        else:
            print(f"⚠ {detail}")
        return 2
