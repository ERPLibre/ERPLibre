#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Répertoire git › Forker un dépôt pour une organisation.

On choisit un projet des manifestes de la version active, on nomme
l'organisation, et le fork se fait par l'API GitHub (github_fork). Puis,
sur demande, les manifestes choisis prennent ce fork (manifest_fork) :
remote de l'organisation, provenance fork-upstream-*, même branche et
même gel.

Trois questions décident du résultat, chacune avec un défaut :
- l'amont d'un projet DÉJÀ forké : celui d'origine (OCA) ou l'ancien fork
  (ERPLibre) — deux usages, aucun n'est le bon partout ;
- les branches copiées : la branche active seule, posée par une ref sur le
  commit gelé, ou toutes celles de la source ;
- les versions d'Odoo dont le manifeste change : l'active par défaut.

Mixin de la classe TODO : ses méthodes vivent sur la même instance que
celles des autres fichiers, elles s'appellent donc par « self. ».
"""

import os
import re
import sys

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.append(new_path)

from script.git import github_fork, manifest_fork  # noqa: E402
from script.git import manifest_freeze, repo_upgrade  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402

RACINE = new_path
MANIFESTE = re.compile(r"git_manifest_odoo(\d+\.\d+)\.xml$")


def versions_des_manifestes(dossier=None):
    """Les versions d'Odoo qui ont un manifeste, triées."""
    try:
        noms = os.listdir(dossier or repo_upgrade.DOSSIER)
    except OSError:
        return []
    trouvees = {m.group(1) for n in noms if (m := MANIFESTE.match(n))}
    return sorted(trouvees, key=lambda v: [int(x) for x in v.split(".")])


def url_du_projet(projet, remotes):
    """L'URL d'où le projet se clone : fetch de son remote + son nom."""
    return repo_upgrade.url_amont(
        remotes.get(projet.get("remote")), projet.get("name")
    )


def projets_github(version, dossier=None):
    """(remotes, [(projet, propriétaire, dépôt)]) des projets de `version`
    hébergés sur GitHub, triés par chemin."""
    remotes, projets = repo_upgrade.lire_manifestes(
        version, dossier or repo_upgrade.DOSSIER
    )
    res = []
    for projet in projets.values():
        depot = github_fork.depot_github(url_du_projet(projet, remotes))
        if depot:
            res.append((projet, *depot))
    res.sort(key=lambda r: r[0].get("path", ""))
    return remotes, res


def versions_du_depot(proprietaire, depot, dossier=None):
    """{version: (remotes, projet)} des versions dont un manifeste clone
    proprietaire/depot. Le premier projet trouvé par version compte."""
    res = {}
    for version in versions_des_manifestes(dossier):
        remotes, liste = projets_github(version, dossier)
        for projet, p, d in liste:
            if (p.lower(), d.lower()) == (proprietaire.lower(), depot.lower()):
                res[version] = (remotes, projet)
                break
    return res


def fichier_du_projet(version, name, path, dossier=None):
    """Le fichier de manifeste de `version` qui déclare name+path, ou None."""
    for chemin in repo_upgrade.fichiers_manifeste(
        version, dossier or repo_upgrade.DOSSIER
    ):
        with open(chemin, encoding="utf-8") as fh:
            texte = fh.read()
        for _d, _f, attrs in manifest_freeze.iter_projects(texte):
            if attrs.get("name") == name and attrs.get("path") == path:
                return chemin
    return None


def branche_du_projet(projet):
    return manifest_freeze.manifest_branch(
        projet.get("revision"),
        projet.get("upstream"),
        projet.get("dest-branch"),
    )


class GitForkMenuMixin:
    def _git_fork_organisation(self):
        """Le parcours complet ; rend 0, ou 2 sur un refus ou une erreur."""
        version = repo_upgrade.version_active(RACINE)
        if not version:
            print(f"❌ {t('No Odoo version found')}")
            return 2
        remotes, liste = projets_github(version)
        choix = self._git_fork_choisir_projet(liste)
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
            print(
                f"⚠ {t('No GitHub token: export EL_GITHUB_TOKEN in the shell that opens TODO (env_var.sh is versioned).')}"
            )
            return 2
        print(
            f"  {proprietaire}/{depot} → {organisation}/{depot}"
            f" · {t('all branches') if toutes else branche}"
        )
        if not self._is_yes(input(t("Fork it? (y/N): "))):
            return 0
        client = github_fork.ClientGitHub(jeton)
        try:
            fork, cree = client.forker(
                proprietaire, depot, organisation, toutes
            )
            nom_complet = fork["full_name"]
            if cree:
                print(f"  {t('Waiting for GitHub to create the fork…')}")
                if not client.attendre(nom_complet):
                    print(
                        f"⚠ {t('The fork is still not ready; try again later.')}"
                    )
                    return 2
                print(f"  ✓ {t('Fork created:')} {fork.get('html_url')}")
            else:
                print(
                    f"  ✓ {t('Fork already present:')} {fork.get('html_url')}"
                )
            if not toutes:
                self._git_fork_branche(
                    client, nom_complet, proprietaire, depot, projet
                )
        except github_fork.ErreurGitHub as exc:
            print(f"❌ GitHub : {exc}")
            return 2
        if not self._is_yes(
            input(t("Change the manifest to take this fork? (y/N): "))
        ):
            return 0
        return self._git_fork_manifestes(
            client,
            nom_complet,
            proprietaire,
            depot,
            organisation,
            mode,
            version,
            toutes,
            fork.get("name"),
        )

    def _git_fork_choisir_projet(self, liste):
        """(projet, propriétaire, dépôt) choisi, ou None."""
        filtre = (
            input(
                t(
                    "Filter (part of the path or of the repository), Enter for all: "
                )
            )
            .strip()
            .lower()
        )
        retenus = [
            r
            for r in liste
            if not filtre
            or filtre in r[0].get("path", "").lower()
            or filtre in f"{r[1]}/{r[2]}".lower()
        ]
        if not retenus:
            print(f"  {t('No repository matches.')}")
            return None
        for i, (projet, proprietaire, depot) in enumerate(retenus, 1):
            print(f"  [{i}] {projet.get('path')}  ({proprietaire}/{depot})")
        saisie = input(t("Repository number, Enter for none: ")).strip()
        if not (saisie.isdigit() and 1 <= int(saisie) <= len(retenus)):
            return None
        return retenus[int(saisie) - 1]

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

    def _git_fork_branche(
        self, client, nom_complet, proprietaire, depot, projet
    ):
        """Pose dans le fork la branche que suit `projet`, sur son commit
        gelé, ou sur la tête de la source s'il n'est pas gelé."""
        branche = branche_du_projet(projet)
        if not branche or client.branche(nom_complet, branche):
            return
        sha = projet.get(manifest_freeze.FREEZE_ATTR) or client.branche(
            f"{proprietaire}/{depot}", branche
        )
        if not sha:
            print(f"⚠ {t('Branch missing at the source:')} {branche}")
            return
        client.creer_branche(nom_complet, branche, sha)
        print(f"  ✓ {t('Branch created in the fork:')} {branche} @ {sha[:12]}")

    def _git_fork_manifestes(
        self,
        client,
        nom_complet,
        proprietaire,
        depot,
        organisation,
        mode,
        version_active,
        toutes,
        nom_fork,
    ):
        par_version = versions_du_depot(proprietaire, depot)
        print(
            f"  {t('Versions whose manifest clones this repository:')}"
            f" {', '.join(par_version) or '-'}"
        )
        saisie = input(
            f"{t('Versions to change, separated by commas (Enter: the active one)')}"
            f" [{version_active}] : "
        ).strip()
        voulues = [v.strip() for v in saisie.split(",") if v.strip()] or [
            version_active
        ]
        changees = []
        for version in voulues:
            if version not in par_version:
                print(
                    f"⚠ {version} : {t('this repository is not in its manifest.')}"
                )
                continue
            remotes, projet = par_version[version]
            try:
                if not toutes:
                    self._git_fork_branche(
                        client, nom_complet, proprietaire, depot, projet
                    )
                changement = manifest_fork.plan(
                    projet, remotes, organisation, mode, nom_fork
                )
            except (github_fork.ErreurGitHub, ValueError) as exc:
                print(f"❌ {version} : {exc}")
                continue
            chemin = fichier_du_projet(
                version, projet.get("name"), projet.get("path")
            )
            if not chemin:
                print(f"⚠ {version} : {t('project not found in the files.')}")
                continue
            with open(chemin, encoding="utf-8") as fh:
                texte = fh.read()
            try:
                neuf, trouve = manifest_fork.appliquer(
                    texte, projet.get("name"), projet.get("path"), changement
                )
            except ValueError as exc:
                print(f"❌ {version} : {exc}")
                continue
            if trouve and neuf != texte:
                with open(chemin, "w", encoding="utf-8") as fh:
                    fh.write(neuf)
                changees.append(os.path.relpath(chemin, RACINE))
                print(
                    f"  ✓ {os.path.relpath(chemin, RACINE)} :"
                    f" remote {changement['remote']}"
                )
        if changees:
            print(
                f"  {t('Commit manifest/, then synchronise the repositories so the clone follows the fork.')}"
            )
        return 0
