#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le menu « Analyse module » : les modules Odoo du checkout.

Ici on DEMANDE (quels dépôts, faut-il `addons/addons`) et on affiche ; la
comparaison elle-même vit dans `script/git/git_module_diff.py`, qui se lance
aussi seul en ligne de commande. La section Mise à jour n'écrit rien et ne
va pas sur le réseau.

La section Statistique lance `script/statistic/show_evolution_module.py`,
qui CLONE l'amont de chaque dépôt des manifestes sous
.venv.erplibre/stat_repo : réseau, gigaoctets et durée, d'où la
confirmation qui la précède.
"""

import datetime
import os
import shlex
import sys

import click

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.append(new_path)

from script.git import (  # noqa: E402
    git_freeze_diff,
    git_module_diff,
    repo_remove_auto_install,
    repo_upgrade,
)
from script.todo.git_repo_menu import choix_numeros  # noqa: E402
from script.todo.todo_couleur import retour  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402

RACINE = new_path

# La fenêtre des cibles Makefile stat_module_evolution_per_year : un
# relevé au 1er janvier de chaque année depuis STAT_DEPUIS, jusqu'au 1er
# janvier de l'année qui suit la courante. Ce dernier relevé tombe après
# aujourd'hui : il compte l'état actuel des branches, la version sortie
# cette année comprise.
STAT_DEPUIS = "2016-01-01"


def stat_annees(aujourdhui=None):
    """Le nombre d'années après STAT_DEPUIS (« --more_year ») pour que le
    dernier relevé soit le 1er janvier de l'année suivant `aujourdhui`."""
    aujourdhui = aujourdhui or datetime.date.today()
    return str(aujourdhui.year + 1 - int(STAT_DEPUIS[:4]))


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
            {"section": t("Statistic")},
            {
                "prompt_description": t(
                    "📈 Module evolution per year, every repository"
                )
            },
            {
                "prompt_description": t(
                    "📈 Module evolution per year, OCA repositories"
                )
            },
            {"section": t("Modification")},
            {
                "prompt_description": t(
                    "🚫 Disable auto_install in repositories of the manifest"
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
            elif status == "3":
                self._module_statistique()
            elif status == "4":
                self._module_statistique(filtre="/OCA/")
            elif status == "5":
                self._module_auto_install()
            else:
                print(t("Command not found !"))

    def _module_statistique(self, filtre=""):
        """L'évolution du nombre de modules par année depuis 2016 jusqu'à
        aujourd'hui, sur les dépôts des manifestes, ceux dont l'URL contient
        `filtre` s'il est donné. Rien ne se lance sans confirmation : la
        statistique clone chaque dépôt amont. Rend le statut de la commande,
        ou None."""
        commande = [
            ".venv.erplibre/bin/python",
            "script/statistic/show_evolution_module.py",
            "--before_date",
            STAT_DEPUIS,
            "--more_year",
            stat_annees(),
        ]
        if filtre:
            commande += ["--filter", filtre]
        print(
            f"📈 {t('Clones the upstream of every repository of the manifests into')}"
            f" .venv.erplibre/stat_repo — {t('network, several GB, long the first time.')}"
        )
        print(f"  {t('Will execute:')} {shlex.join(commande)}")
        if not click.confirm(f"  {t('Continue?')}", default=False):
            return None
        return self.execute.exec_command_live(
            shlex.join(commande), source_erplibre=False
        )

    def _module_auto_install(self):
        """Désactive auto_install dans les dépôts cochés parmi ceux du
        manifeste de la version active, en parallèle ; committe et pousse
        seulement si on le demande. Rend le nombre de dépôts traités, ou
        None si rien n'a été lancé."""
        version = repo_upgrade.version_active(RACINE)
        if not version:
            print(f"❌ {t('No Odoo version found')}")
            return None
        depots = depots_d_addons(version)
        if not depots:
            print(f"  {t('No addons repository cloned for this version.')}")
            return None
        for i, chemin in enumerate(depots, 1):
            print(f"  [{i}] {chemin}")
        saisie = input(
            t(
                "Numbers separated by commas, all for every one, Enter for none: "
            )
        ).strip()
        if not saisie:
            return None
        choisis = choix_numeros(saisie, depots)
        if not choisis:
            print(t("Command not found !"))
            return None
        commit = click.confirm(
            f"  {t('Commit the changed manifests in each repository (current branch)?')}",
            default=False,
        )
        push = commit and click.confirm(
            f"  {t('Push each commit to its tracked branch?')}", default=False
        )
        print(f"  {len(choisis)} {t('repositories, in parallel…')}")
        resultats = repo_remove_auto_install.traiter(
            [os.path.join(RACINE, c) for c in choisis],
            commit=commit,
            push=push,
        )
        print("\n".join(rendre_auto_install(resultats)))
        return len(resultats)

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


def depots_d_addons(version, racine=RACINE):
    """Les chemins, relatifs à `racine`, des projets du manifeste de
    `version` dont le clone existe, triés. Le cœur d'Odoo n'en fait pas
    partie : ses auto_install font partie de son fonctionnement."""
    _remotes, projets = repo_upgrade.lire_manifestes(version)
    chemins = set()
    for projet in projets.values():
        chemin = projet.get("path") or ""
        if not chemin or os.path.basename(chemin) == "odoo":
            continue
        if os.path.isdir(os.path.join(racine, chemin)):
            chemins.add(chemin)
    return sorted(chemins)


def rendre_auto_install(resultats, racine=RACINE):
    """Une ligne par dépôt : manifestes changés, commit et push s'ils ont
    été tentés, et l'échec quand il y en a un."""
    lignes = []
    for res in resultats:
        chemin = os.path.relpath(res["depot"], racine)
        if res["erreur"]:
            lignes.append(f"❌ {chemin} : {res['erreur']}")
            continue
        ligne = f"{'✓' if res['fichiers'] else '·'} {chemin} : {len(res['fichiers'])}"
        for etape in ("commit", "push"):
            if res[etape] is not None:
                code, sortie = res[etape]
                ligne += f" · {etape} {'✓' if not code else '❌'}"
                if code:
                    ligne += (
                        f" ({sortie.splitlines()[-1] if sortie else code})"
                    )
        lignes.append(ligne)
    total = sum(len(r["fichiers"]) for r in resultats)
    lignes.append(f"📋 {total} {t('manifests changed')}")
    return lignes


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
