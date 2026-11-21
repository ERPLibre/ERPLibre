#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La mise à jour d'un checkout déjà installé : Python, venvs et dépôts.

Le menu Installation y mène quand une version d'Odoo est déjà installée.
Rien n'est recopié ici : chaque entrée appelle la méthode du menu Python ou
du menu des dépôts qui fait déjà le travail.

La resynchronisation des dépôts régénère le manifeste local dans le mode du
checkout, gelé ou branches, que `repo_state.mode_du_checkout` lit dans le
manifeste local : relancée sans ce mode, elle dégèlerait un checkout gelé.

Un clone fait à la main à un chemin que les manifestes déclarent fait
échouer `repo sync` : git-repo n'adopte qu'un « .git » qui pointe dans
`.repo/projects/`, et un « .git/ » ordinaire le fait refuser (« unsupported
checkout state »). Un tel clone est proposé au déplacement AVANT la
synchronisation, à côté de son chemin, sous un suffixe daté ; ses branches
locales peuvent ensuite être recopiées dans le clone de git-repo.
"""

import os
import shutil
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime

import click

from script.git import repo_state
from script.todo import ui
from script.todo.git_repo_menu import (
    MANIFESTE_LOCAL,
    RACINE,
    etat_manifeste_local,
    gel_des_sources,
    libelle_mode,
)
from script.todo.todo_i18n import t

SUFFIXE_DEPLACE = ".avant_repo_"


def chemins_declares(racine, sources=None):
    """Les chemins de projet que déclarent le manifeste local et les
    fichiers que sa régénération fusionne, relatifs à `racine`.

    Les sources de la fusion comptent : un projet ajouté à un manifeste,
    privé compris, n'entre dans le manifeste local qu'à la régénération, la
    même qui échoue sur un clone fait à la main à son chemin. `sources`, des
    chemins relatifs à `racine`, remplace la liste de
    `git_merge_repo_manifest.default_input_paths`, qui lit le checkout depuis
    le dossier courant. Un fichier absent ou illisible est sauté."""
    if sources is None:
        from script.git import git_merge_repo_manifest

        sources = git_merge_repo_manifest.default_input_paths()
    fichiers = [os.path.join(racine, MANIFESTE_LOCAL)] + [
        os.path.join(racine, s) for s in sources
    ]
    chemins = set()
    for fichier in fichiers:
        try:
            arbre = ET.parse(fichier).getroot()
        except (OSError, ET.ParseError):
            continue
        for projet in arbre.iter("project"):
            chemin = projet.get("path") or projet.get("name")
            if chemin:
                chemins.add(os.path.normpath(chemin))
    return chemins


def clone_gere(racine, chemin):
    """Vrai quand le « .git » de `chemin` est le lien que git-repo pose vers
    `.repo/projects/<chemin>.git`."""
    dotgit = os.path.join(racine, chemin, ".git")
    if not os.path.islink(dotgit):
        return False
    attendu = os.path.join(racine, ".repo", "projects", f"{chemin}.git")
    return os.path.realpath(dotgit) == os.path.realpath(attendu)


def clones_manuels(racine, chemins):
    """Parmi `chemins`, ceux qui portent un « .git » que git-repo n'a pas
    posé : un dossier, un fichier gitdir, ou un lien ailleurs. Triés."""
    return sorted(
        chemin
        for chemin in chemins
        if os.path.lexists(os.path.join(racine, chemin, ".git"))
        and not clone_gere(racine, chemin)
    )


def destination(chemin, maintenant):
    """`chemin` suivi du suffixe daté, à côté de lui :
    « odoo18.0/addons/addons.avant_repo_20261115_143000 ». Hors de
    l'addons_path, que la configuration liste dépôt par dépôt."""
    return f"{chemin}{SUFFIXE_DEPLACE}{maintenant:%Y%m%d_%H%M%S}"


def _git(clone, *args):
    return subprocess.run(
        ["git", "-C", clone, *args], capture_output=True, text=True
    )


def refs_locales(clone):
    """{branche: commit} des branches locales du clone ; {} quand git ne
    peut pas les lire."""
    fait = _git(
        clone,
        "for-each-ref",
        "--format=%(refname:short) %(objectname)",
        "refs/heads",
    )
    if fait.returncode:
        return {}
    return dict(
        ligne.rsplit(" ", 1) for ligne in fait.stdout.splitlines() if ligne
    )


def etat_clone(clone):
    """Ce qu'un clone porte et que git-repo ne connaît pas : fichiers
    modifiés ou non suivis, entrées de stash, commits absents de tout
    remote — HEAD détaché compris —, branches locales. Une commande git
    qui échoue laisse sa valeur à None."""

    def lignes(fait):
        if fait.returncode:
            return None
        return [l for l in fait.stdout.splitlines() if l.strip()]

    modifies = lignes(_git(clone, "status", "--porcelain"))
    stash = lignes(_git(clone, "stash", "list"))
    non_pousses = lignes(
        _git(
            clone,
            "log",
            "--oneline",
            "HEAD",
            "--branches",
            "--not",
            "--remotes",
        )
    )
    if non_pousses is None:
        # HEAD sans commit : les branches seules.
        non_pousses = lignes(
            _git(clone, "log", "--oneline", "--branches", "--not", "--remotes")
        )
    branches = lignes(
        _git(clone, "for-each-ref", "--format=%(refname:short)", "refs/heads")
    )
    return {
        "modifies": None if modifies is None else len(modifies),
        "stash": None if stash is None else len(stash),
        "non_pousses": None if non_pousses is None else len(non_pousses),
        "branches": branches,
    }


def pertes_a_la_suppression(vieux, nouveau):
    """Ce que supprimer le clone `vieux` perdrait, `nouveau` gardé : des
    libellés, vides quand rien ne se perd. Un commit est sauf quand le
    nouveau clone l'a déjà, poussé sur un remote ou recopié ; les fichiers
    modifiés et le stash ne passent jamais d'un clone à l'autre."""
    etat = etat_clone(vieux)
    pertes = []
    if etat["modifies"] is None:
        pertes.append(t("unreadable git state"))
        return pertes
    if etat["modifies"]:
        pertes.append(f"{etat['modifies']} {t('modified files')}")
    if etat["stash"]:
        pertes.append(f"{etat['stash']} {t('stash entries')}")
    pointes = dict(refs_locales(vieux))
    tete = _git(vieux, "rev-parse", "--verify", "-q", "HEAD")
    if tete.returncode == 0:
        pointes["HEAD"] = tete.stdout.strip()
    absents = sorted(
        nom
        for nom, commit in pointes.items()
        if _git(nouveau, "cat-file", "-e", f"{commit}^{{commit}}").returncode
    )
    if absents:
        pertes.append(
            f"{t('commits found only in the old clone:')} {', '.join(absents)}"
        )
    return pertes


class InstallUpdateMenuMixin:
    def prompt_install_update(self):
        print(f"🤖 {t('Update what is installed!')}")
        choices = [
            {"section": "Python"},
            {
                "prompt_description": t(
                    "Python versions - Install or update the venvs,"
                    " without the git repos"
                )
            },
            {
                "prompt_description": t(
                    "Lock drift - Compare a venv with its lock or requirements"
                )
            },
            {"section": t("Repositories")},
            {
                "prompt_description": t(
                    "Resynchronize the repositories with the manifests"
                )
            },
            {"prompt_description": t("⬇️ Pull the repositories")},
        ]
        help_info = self.fill_help_info(choices)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self.execute_python_versions()
            elif status == "2":
                self.execute_poetry_drift()
            elif status == "3":
                self.execute_update_repos()
            elif status == "4":
                self._git_repo_tirer()
            else:
                print(t("Command not found !"))

    def execute_update_repos(self, racine=RACINE, maintenant=None):
        """Régénère le manifeste local dans le mode du checkout et
        synchronise, après avoir proposé de déplacer les clones faits à la
        main. Rend le code de la reconfiguration, ou None quand rien n'est
        lancé.

        Toutes les réponses sont prises avant le premier déplacement :
        renoncer, ou Ctrl+D à l'une d'elles, laisse chaque clone à sa
        place. Après la synchronisation, réussie ou non, chaque clone
        déplacé est repris : rendu à son chemin quand repo ne l'a pas
        recréé, sinon ses branches proposées à la copie. Un Ctrl+D à l'une
        de ces questions vaut non pour ce clone, et les suivants sont repris
        quand même."""
        mode = repo_state.mode_du_checkout(racine)[0]
        if mode == "frozen":
            sources = gel_des_sources(racine)
            if sources is not None and not sources[0]:
                print(f"⚠  {t('No commit is frozen in the manifest files.')}")
                print(f"   {t('Freeze the versions first.')}")
                return None
        plan = self._update_choisir_deplacements(
            racine, maintenant or datetime.now()
        )
        if plan is None:
            return None
        deplaces = []
        for chemin, ancien in plan:
            try:
                os.rename(
                    os.path.join(racine, chemin), os.path.join(racine, ancien)
                )
            except OSError as erreur:
                print(f"❌ {t('Could not move')} {chemin} : {erreur}")
                continue
            print(f"✅ {t('Moved:')} {chemin} → {ancien}")
            deplaces.append((chemin, ancien))
        etat = etat_manifeste_local(racine)
        print(f"{t('Checkout mode kept:')} {libelle_mode(etat)}")
        status = self._git_repo_reconfigurer(freeze=mode == "frozen")
        for chemin, ancien in deplaces:
            self._update_reprendre(racine, chemin, ancien)
        return status

    def _update_choisir_deplacements(self, racine, maintenant):
        """Demande, pour chaque clone fait à la main à un chemin déclaré,
        s'il faut le déplacer ; rien n'est encore déplacé. Rend les
        (chemin, destination) acceptés, ou None quand l'utilisateur, ayant
        gardé un clone, renonce à synchroniser, ou sur Ctrl+D à l'une des
        questions."""
        plan = []
        garde = False
        for chemin in clones_manuels(racine, chemins_declares(racine)):
            ancien = destination(chemin, maintenant)
            print(
                f"⚠️  {chemin} : {t('cloned by hand at a path of the manifest, repo sync cannot adopt it and fails on it.')}"
            )
            self._update_decrire_clone(os.path.join(racine, chemin))
            try:
                reponse = ui.ask(
                    f"💬 {t('Move it aside to %s? (y/N): ') % ancien}"
                )
            except EOFError:
                return None
            if self._is_yes(reponse):
                plan.append((chemin, ancien))
            else:
                print(
                    f"   {t('Kept: repo sync will fail on this repository.')}"
                )
                garde = True
        if garde:
            try:
                encore = ui.ask(f"💬 {t('Synchronize anyway? (y/N): ')}")
            except EOFError:
                return None
            if not self._is_yes(encore):
                return None
        return plan

    def _update_decrire_clone(self, clone):
        """Affiche ce que le clone porte et qu'un déplacement garde."""
        etat = etat_clone(clone)
        for cle, libelle in (
            ("modifies", "modified files"),
            ("stash", "stash entries"),
            ("non_pousses", "commits on no remote"),
        ):
            if etat[cle]:
                print(f"   {etat[cle]} {t(libelle)}")
        if etat["branches"]:
            print(f"   {t('local branches:')} {', '.join(etat['branches'])}")

    def _update_reprendre(self, racine, chemin, ancien):
        """Après la synchronisation, le sort du clone déplacé `ancien`.

        Le chemin resté vide — repo ne l'a pas cloné, synchronisation
        échouée ou projet retiré des manifestes — reprend son clone. Un
        clone de git-repo s'y trouve : les branches locales de l'ancien
        peuvent y être recopiées ; git-repo laisse HEAD détaché, le fetch
        peut donc les écrire. Chaque branche est vérifiée par son commit,
        car `git fetch` rejette sans erreur une ref qu'un clone superficiel
        ne peut pas recevoir. La suppression de l'ancien n'est offerte que
        si rien ne s'y perdrait. Ctrl+D à l'une des deux questions vaut
        non : l'ancien clone reste, sans copie ni suppression, et une ligne
        à part dit où il est gardé."""
        nouveau = os.path.join(racine, chemin)
        vieux = os.path.join(racine, ancien)
        if not os.path.lexists(nouveau):
            try:
                os.rename(vieux, nouveau)
            except OSError as erreur:
                print(f"❌ {t('Could not move')} {ancien} : {erreur}")
                return
            print(
                f"↩️  {t('Put back, repo sync did not clone it:')} {ancien} → {chemin}"
            )
            return
        if not clone_gere(racine, chemin):
            print(
                f"⚠️  {chemin} : {t('not cloned by repo sync, the old clone is kept:')} {ancien}"
            )
            return
        anciennes = refs_locales(vieux)
        try:
            copier = anciennes and self._is_yes_default_yes(
                ui.ask(
                    f"💬 {t('Copy the local branches of %s into the new clone? (Y/n): ') % ancien}"
                )
            )
        except EOFError:
            self._update_garder(chemin, ancien)
            return
        if copier:
            fait = _git(
                nouveau,
                "fetch",
                "--update-shallow",
                vieux,
                "refs/heads/*:refs/heads/*",
            )
            recopiees = refs_locales(nouveau)
            copiees = sorted(
                b for b, c in anciennes.items() if recopiees.get(b) == c
            )
            manquantes = sorted(set(anciennes) - set(copiees))
            if copiees:
                print(f"✅ {t('Branches copied:')} {', '.join(copiees)}")
            if manquantes:
                print(
                    f"❌ {t('Branches not copied:')} {', '.join(manquantes)}"
                )
                if fait.stderr.strip():
                    print(f"   {fait.stderr.strip()}")
        pertes = pertes_a_la_suppression(vieux, nouveau)
        if pertes:
            print(
                f"⚠️  {t('Old clone kept, deleting it would lose:')} {ancien}"
            )
            for perte in pertes:
                print(f"   {perte}")
            return
        try:
            supprimer = self._is_yes(
                ui.ask(f"💬 {t('Delete the old clone %s? (y/N): ') % ancien}")
            )
        except EOFError:
            self._update_garder(chemin, ancien)
            return
        if supprimer:
            try:
                shutil.rmtree(vieux)
            except OSError as erreur:
                print(f"❌ {t('Could not delete')} {ancien} : {erreur}")
                return
            print(f"✅ {t('Deleted:')} {ancien}")

    @staticmethod
    def _update_garder(chemin, ancien):
        """Dit, sur sa propre ligne, que le clone de `chemin` reste gardé
        sous `ancien`. `input` n'écrit pas de saut de ligne sur Ctrl+D :
        le premier `print` en tient lieu, sinon la ligne suivante
        s'écrirait à la suite de la question."""
        print()
        print(f"⚠️  {chemin} : {t('Kept as')} {ancien}")
