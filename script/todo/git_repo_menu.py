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
constate AVANT de s'appliquer : sa passe à sec récupère l'amont par son remote
nommé, « <remote>/<branche> », et prédit la fusion en mémoire, sans créer ni
déplacer de branche locale ni toucher l'arbre de travail. Le constat coûte
quelques secondes sur l'ensemble des forks, et se rejoue autant de fois qu'on
veut.

Le GEL écrit le commit de chaque clone de la version d'Odoo active à côté
de sa branche, dans ses fichiers de `manifest/` (`git_manifest_odoo<V>.xml`,
`_dev`, `git_manifest_extra_odoo<V>.xml`). Suivre les branches ou les commits gelés est un
argument de la reconfiguration, jamais un état enregistré : le mode que
l'en-tête affiche se lit dans le manifeste local que git-repo utilise.

Le SUIVI des pull requests d'une forge lit celles qui concernent chaque
clone, rapatrie la branche de base de celles qui sont fusionnées sans jamais
forcer une branche locale, puis propose d'avancer le gel des projets déjà
gelés (`forge_pull_requests`). Les MIROIRS d'une forge suivent l'origine
de chaque dépôt, et un minuteur sur l'hôte de la forge en avance les
branches de travail sans jamais forcer (`forge_mirror`, `forge_sync`).

Module à part plutôt que méthodes de `TODO` : le fichier principal passe les
cinq mille lignes, et chaque sujet y a désormais le sien.
"""

import datetime
import os
import re
import sys

import click

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.append(new_path)

from script.git import (  # noqa: E402
    forge_manifest,
    forge_mirror,
    forge_pull_requests,
    forgejo_client,
    freeze_resolution,
    git_freeze_diff,
    git_freeze_manifest,
    manifest_freeze,
    manifest_repo,
    push_remote,
    repo_apply,
    repo_upgrade,
)
from script.todo.git_fork_menu import (  # noqa: E402
    ICONES_ETAT,
    LIBELLES_CI,
    LIBELLES_REVUE,
)
from script.todo.todo_couleur import bleu_poudre, retour  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402

# La racine du dépôt. Le lanceur de git-repo porte un shebang RELATIF vers le
# venv : lancé depuis un autre répertoire, il ne trouve pas son interpréteur
# et meurt sur « bad interpreter ». Toutes ses invocations partent donc d'ici.
RACINE = new_path
REPO_BIN = ".venv.erplibre/bin/repo"
PYTHON_ERPLIBRE = "./.venv.erplibre/bin/python"
FREEZE_SCRIPT = "script/git/git_freeze_manifest.py"
# Le groupe du coffre KeePass où se rangent les jetons des forges Forgejo,
# une entrée par hôte.
GROUPE_FORGE = "ERPLibre Forgejo"
# Le manifeste que git-repo lit, produit par la fusion des fichiers de
# `manifest/`. Ses « revision » disent ce que le checkout suit réellement.
MANIFESTE_LOCAL = os.path.join(
    ".repo", "local_manifests", "erplibre_manifest.xml"
)

# Les états que « repo_apply » rend, traduits en clés d'affichage. Les clés
# du catalogue sont des phrases anglaises ; les états sont des identifiants
# internes, et les passer tels quels à t() y ferait entrer du français.
ETATS = {
    "rebase": "rebased (one)",
    "conflit": "conflicting",
    "ignore": "untouched",
    "branche_existante": "a dated branch already exists",
    "branche_refusee": "the branch could not be created",
    "rebase_deja_en_cours": "a rebase was already in progress",
    "avance": "fast-forwarded (one)",
    "avance_refusee": "the fast-forward was refused",
    "rebase_refuse": "git refused to start the rebase",
    "sale": "the work tree has uncommitted changes",
    "distant_en_avance": "the fork branch has commits HEAD lacks",
    "abandonne": "rebase aborted",
    "revenu": "back to the state managed by repo",
    "publie": "published (one)",
}

# Les libellés d'un décompte, au pluriel, quand ETATS nomme un seul dépôt.
DECOMPTES = {
    "rebase": "rebased",
    "avance": "fast-forwarded",
    "publie": "published",
}


# Les états de `forge_pull_requests.rapatrier`, traduits en clés
# d'affichage, pour la même raison qu'ETATS.
RAPATRIEMENTS = {
    "creee": "branch created",
    "a_jour": "already up to date",
    "avance": "fast-forwarded (one)",
    "en_avance": "the local branch is ahead",
    "diverge": "diverged: left as is",
    "indetermine": "undetermined (shallow clone): left as is",
    "sale": "the work tree has uncommitted changes",
    "operation_en_cours": "an operation is in progress",
    "refus": "refused by git",
    "echec_fetch": "fetch failed",
}


# Les états de `forge_sync` (le minuteur des miroirs) et ceux d'un miroir
# assuré sur la forge, traduits en clés d'affichage, pour la même raison
# qu'ETATS.
ETATS_SYNCHRO = {
    "a_jour": "up to date",
    "avance": "fast-forwarded",
    "creee": "branch created",
    "en_avance": "ahead of the origin",
    "divergent": "diverged",
    "absente": "absent",
    "absente_miroir": "absent from the mirror",
    "depot_absent": "repository absent",
    "refuse": "refused",
    "erreur": "error",
}
LIBELLES_MIROIR = {
    "cree": "created",
    "en_cours": "in progress",
    "existant": "existing",
    "autre_origine": "mirror of another origin",
    "pas_miroir": "not a mirror",
    "erreur": "error",
}


def decompte(nombre, etat):
    """« <nombre> <libellé> », au singulier d'`ETATS` pour un seul dépôt, au
    pluriel de `DECOMPTES` sinon."""
    libelle = ETATS[etat] if nombre == 1 else DECOMPTES[etat]
    return f"{nombre} {t(libelle)}"


def etat_manifeste_local(racine=RACINE):
    """(épinglés, total) des projets du manifeste local, ou None s'il manque.

    Un projet est épinglé quand sa « revision » est un commit complet. Le
    mode du checkout se LIT ici plutôt que de s'enregistrer à part : c'est
    la dernière reconfiguration qui l'a fixé, et ce fichier en est la trace.
    """
    try:
        with open(os.path.join(racine, MANIFESTE_LOCAL)) as fh:
            texte = fh.read()
    except OSError:
        return None
    projets = [attrs for _, _, attrs in manifest_freeze.iter_projects(texte)]
    epingles = [
        p for p in projets if manifest_freeze.is_sha(p.get("revision"))
    ]
    return len(epingles), len(projets)


def libelle_mode(etat):
    """Le mode que l'en-tête affiche, tiré d'`etat_manifeste_local`."""
    if etat is None:
        return t("no local manifest")
    epingles, total = etat
    if epingles:
        return f"{epingles}/{total} {t('projects pinned to a commit')}"
    return t("follows the branches")


def gel_des_sources(racine=RACINE, odoo_version=None):
    """(gelés, total) des projets des fichiers que le gel écrit — ceux de
    `odoo_version` (« 18.0 »), par défaut de la version d'Odoo active —, ou
    None illisible.

    Un projet est gelé quand l'un de ses fichiers lui donne
    « freeze-revision ». Les chemins des sources sont relatifs à la racine
    du dépôt : le répertoire courant y passe le temps de la lecture, puis
    revient.
    """
    depart = os.getcwd()
    try:
        os.chdir(racine)
        definitions = git_freeze_manifest.read_sources(
            git_freeze_manifest.freeze_sources(odoo_version)
        )
    except OSError:
        return None
    finally:
        os.chdir(depart)
    geles = [
        cle
        for cle, defs in definitions.items()
        if any(attrs.get(manifest_freeze.FREEZE_ATTR) for _, attrs in defs)
    ]
    return len(geles), len(definitions)


def ligne_du_gel(sources, forks):
    """La ligne d'en-tête du gel des fichiers de `manifest/`, ou None.

    `sources` vient de `gel_des_sources`, `forks` d'`etat_forks`. La ligne
    compte les projets gelés, puis les forks dont le gel a écrit la base
    amont dans « fork-upstream-freeze-revision » : la lire ne coûte aucun
    réseau. Sans `sources`, pas de ligne.
    """
    if not sources:
        return None
    ligne = (
        f"   {t('Frozen in the manifest files:')} {sources[0]}/{sources[1]}"
    )
    if forks:
        avec = len([f for f in forks if f.get("base_gelee")])
        ligne += f" · {avec}/{len(forks)} {t('forks with upstream base')}"
    return ligne


def choix_numeros(saisie, candidats):
    """Les éléments de `candidats` que `saisie` désigne, ou None.

    « all » les rend tous ; sinon des numéros séparés par des virgules,
    chacun entre 1 et len(candidats). Un numéro hors de ces bornes ou qui
    n'est pas un entier rend None. Un numéro répété ne compte qu'une fois,
    à sa première place : chaque élément se traite une seule fois.
    """
    if saisie == "all":
        return list(candidats)
    numeros = []
    for morceau in saisie.split(","):
        try:
            numero = int(morceau)
        except ValueError:
            return None
        if not 1 <= numero <= len(candidats):
            return None
        if numero not in numeros:
            numeros.append(numero)
    return [candidats[n - 1] for n in numeros]


def ligne_pull_request(pr):
    """La ligne d'une pull request de `forge_pull_requests.lire` : icône,
    numéro, titre, commentaires, puis revue et CI d'une ouverte, date de
    fusion et présence locale d'une fusionnée. L'URL suit, sauf pour une
    fermée ou une fusionnée déjà locale."""
    morceaux = [f"{ICONES_ETAT[pr['etat']]} #{pr['numero']} {pr['titre']}"]
    if pr.get("commentaires"):
        morceaux.append(f"💬 {pr['commentaires']}")
    url = pr.get("url")
    if pr["etat"] in ("ouverte", "brouillon"):
        morceaux.append(t(LIBELLES_REVUE[pr.get("revue")]))
        if pr.get("ci"):
            morceaux.append(t(LIBELLES_CI[pr["ci"]]))
    elif pr["etat"] == "fusionnee":
        morceaux.append(
            f"{t('merged (pull request)')} {pr.get('fusionnee_le', '')}".rstrip()
        )
        if pr.get("local"):
            morceaux.append(f"✓ {t('local')}")
            url = ""
        else:
            morceaux.append(f"⬇ {t('to bring back')}")
    else:
        morceaux.append(t("closed (pull request)"))
        url = ""
    ligne = " · ".join(morceaux)
    return f"{ligne} — {url}" if url else ligne


class GitRepoMenuMixin:
    def prompt_execute_git_repo(self):
        version = repo_upgrade.version_active(RACINE) or "?"
        forks = repo_upgrade.etat_forks(version)
        print(f"🔃 {t('Update and upgrade the git repositories')}")
        print(
            f"   Odoo {version} · {len(forks)} {t('forks')}"
            f" · {libelle_mode(etat_manifeste_local())}"
        )
        ligne = ligne_du_gel(gel_des_sources(), forks)
        if ligne:
            print(ligne)
        choices = [
            {"section": t("Update")},
            {"prompt_description": t("🔄 Synchronize the repositories")},
            {
                "prompt_description": t(
                    "🔁 Switch to development: each repository follows its branch"
                )
            },
            {"prompt_description": t("⬇️ Pull the repositories")},
            {"section": t("Upgrade")},
            {"prompt_description": t("🌐 Add the upstream remotes")},
            {"prompt_description": t("🔍 Upgrade — dry run")},
            {"prompt_description": t("⬆️ Apply the upgrade")},
            {"prompt_description": t("🧩 Conflict queue")},
            {"prompt_description": t("📤 Publish the updated forks")},
            {"section": t("Observe")},
            {"prompt_description": t("📊 Report of the last pass")},
            {"prompt_description": t("🖥️ Browse the upgrade on screen")},
            {"prompt_description": t("🔗 Fork and upstream status")},
            {"section": t("Versions")},
            {"prompt_description": t("🧊 Freeze the versions")},
            {
                "prompt_description": t(
                    "📌 Switch to production: each repository on its frozen commit"
                )
            },
            {"prompt_description": t("🫗 Unfreeze the versions")},
            {"prompt_description": t("🔀 Compare two freezes")},
            {"section": t("Remotes")},
            {"prompt_description": t("📡 Push the repositories to a remote")},
            {"prompt_description": t("📬 Open pull requests on a forge")},
            {
                "prompt_description": t(
                    "🧭 Sync from a forge: private manifest overlay"
                )
            },
            {
                "prompt_description": t(
                    "📥 Follow the pull requests of a forge"
                )
            },
            {
                "prompt_description": t(
                    "🪞 Follow the origins: mirrors on the forge"
                )
            },
        ]
        help_info = self.fill_help_info(choices)
        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            self._git_repo_choix(status)

    def _git_repo_choix(self, status):
        """Lance l'entrée numéro `status` du menu, hors « 0 »."""
        if status == "1":
            self._git_repo_sync()
        elif status == "2":
            self._git_repo_reconfigurer()
        elif status == "3":
            self._git_repo_tirer()
        elif status == "4":
            self._git_repo_ajouter_remotes()
        elif status == "5":
            self._git_repo_a_sec()
        elif status == "6":
            self._git_repo_appliquer()
        elif status == "7":
            self._git_repo_file_conflits()
        elif status == "8":
            self._git_repo_publier()
        elif status == "9":
            self._git_repo_rapport()
        elif status == "10":
            self._git_repo_ecran()
        elif status == "11":
            self._git_repo_etat_forks()
        elif status == "12":
            self._git_repo_geler()
        elif status == "13":
            self._git_repo_reconfigurer(freeze=True)
        elif status == "14":
            self._git_repo_geler(unfreeze=True)
        elif status == "15":
            self._git_repo_comparer()
        elif status == "16":
            self._git_repo_pousser_remote()
        elif status == "17":
            self._git_repo_pull_requests()
        elif status == "18":
            self._git_repo_surcouche()
        elif status == "19":
            self._git_repo_suivre_pull_requests()
        elif status == "20":
            self._git_repo_miroirs()
        else:
            print(t("Command not found !"))

    def _git_repo_sync(self):
        """Ramène chaque dépôt sur la révision de son manifeste local.

        Cette révision est la pointe de la branche, ou le commit gelé quand
        la dernière reconfiguration a tourné sur les commits gelés.

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

    def _git_repo_reconfigurer(self, freeze=False):
        """Régénère le manifeste local, puis synchronise.

        Le chemin complet, et le seul qui prenne en compte une modification
        des fichiers de `manifest/` : il refond les fragments en un manifeste
        local et relance `repo init` avant de synchroniser.

        Sans `freeze`, chaque projet suit sa branche. Avec `freeze`, chaque
        projet qui porte « freeze-revision » est posé sur ce commit, et les
        autres suivent leur branche ; la fusion les liste. Le choix n'est
        enregistré nulle part : la reconfiguration suivante, lancée sans
        l'argument, revient aux branches.
        """
        if freeze:
            sources = gel_des_sources()
            if sources is not None and not sources[0]:
                print(f"⚠  {t('No commit is frozen in the manifest files.')}")
                print(f"   {t('Freeze the versions first.')}")
                return 1
        cmd = "make repo_configure_all"
        if freeze:
            cmd += " FREEZE=1"
        print(f"  {t('Will execute:')} {cmd}")
        status = self.execute.exec_command_live(
            f"cd {RACINE} && {cmd}", source_erplibre=False
        )
        if status:
            print(f"⚠  {t('Reconfiguration failed.')} ({status})")
        else:
            print(f"✅ {t('Repositories reconfigured and synchronized.')}")
        return status

    def _git_repo_tirer(self):
        """Tire chaque dépôt : essai à sec, confirmation, passe épinglée.

        Le mode « manifeste » tire la racine ERPLibre, régénère le manifeste
        local et intègre la nouvelle cible de chaque clone ; le mode
        « branche » tire la branche suivie de chaque clone. L'essai à sec ne
        fait que récupérer, sous le verrou du checkout comme la passe ; la
        passe le refait et n'écrit rien si un dépôt a bougé depuis (voir
        `repo_pull.passe`). Approfondir un clone superficiel, cloner un
        nouveau dépôt et installer les dépendances Python se demandent
        chacun à part ; la réponse par défaut est non. Quand les réponses
        ne laissent rien à tirer, rien n'est demandé de plus.

        `repo_pull` s'importe ici et non en tête : `repo_state`, qu'il
        importe, importe ce module.

        Rend le nombre de dépôts avancés ou tirés.
        """
        from script.git import repo_pull

        oui = ("o", "oui", "y", "yes")
        version = repo_upgrade.version_active(RACINE) or "?"
        choix = click.prompt(
            t("Mode: 1 manifest, 2 branches"),
            default="1",
            type=click.Choice(["1", "2"]),
        )
        mode = "branche" if choix == "2" else "manifeste"
        strategie = click.prompt(
            t("Strategy (rebase, ff, merge)"),
            default="rebase",
            type=click.Choice(repo_pull.STRATEGIES),
        )
        print(f"   {t('Querying each remote, this takes a few seconds.')}")
        try:
            with repo_pull.verrou(RACINE):
                donnees, code = repo_pull.diagnostic(RACINE, mode, strategie)
        except repo_pull.Occupe:
            print(f"⚠  {t('Another pull is running on this checkout.')}")
            return 0
        print()
        print(repo_pull.render_diagnostic(donnees, colour=True))
        if code or not (
            donnees["plan"]
            or donnees["plan_superficiel"]
            or donnees["plan_nouveaux"]
        ):
            print(f"\n↩️  {t('Nothing to pull: nothing to confirm.')}")
            return 0

        approfondir = False
        if donnees["plan_superficiel"]:
            print()
            avis = t("Shallow clones: deepening downloads history (network).")
            print(f"⚠️  {avis}")
            for chemin in donnees["plan_superficiel"]:
                print(f"     {chemin}")
            reponse = input(
                f"💬 {t('Deepen the shallow clones (network)? (y/N): ')}"
            )
            approfondir = reponse.strip().lower() in oui
        cloner = False
        if donnees["plan_nouveaux"]:
            reponse = input(f"💬 {t('Clone the new repositories? (y/N): ')}")
            cloner = reponse.strip().lower() in oui

        attendus = list(donnees["attendus"])
        if approfondir:
            attendus += donnees["attendus_superficiel"]
        lus = [repo_apply.lire_attendu(x) for x in attendus]
        if not lus and not cloner:
            print(f"\n↩️  {t('Nothing to pull: nothing to confirm.')}")
            return 0
        par_chemin = {c["chemin"]: c for c in donnees["depots"]}
        stash = [c for c, _e in lus if par_chemin.get(c, {}).get("sale")]
        print()
        print(f"⚠️  {len(lus)} {t('repositories will be pulled.')}")
        if lus:
            print(f"   {t('A backup branch is created on each HEAD:')}")
        for chemin, _e in lus:
            prefixe = par_chemin[chemin].get("sauvegarde_prefixe") or ""
            print(f"     {chemin} → {prefixe}<…>")
        if stash:
            print(f"   {t('Stashed, then reapplied:')} {', '.join(stash)}")
        if cloner:
            print(f"   {t('Cloned by a restricted repo sync:')}")
            for chemin in donnees["plan_nouveaux"]:
                print(f"     {chemin}")
        if (donnees.get("manifeste") or {}).get("changements"):
            print(
                f"   {t('The local manifest is regenerated and rewritten:')}"
                f" {repo_pull.repo_state.MANIFESTE_LOCAL}"
            )
        print(f"   {t('Nothing is pushed.')}")
        reponse = input(f"💬 {t('Pull the repositories? (y/N): ')}")
        if reponse.strip().lower() not in oui:
            print(f"↩️  {t('Cancelled: nothing was written.')}")
            return 0

        print()
        charge, code = repo_pull.passe(
            RACINE,
            version,
            mode,
            strategie,
            attendus=[c for c, _e in lus],
            epingles={c: e for c, e in lus if e},
            approfondir=approfondir,
            cloner=cloner,
            attendus_clone=donnees["plan_nouveaux"] if cloner else (),
        )
        if code == repo_pull.EXIT_PLAN_CHANGE:
            avis = t(
                "The remote moved since the dry run: nothing was written."
            )
            print(f"⚠  {avis}")
            return 0
        print(repo_pull.render_passe(charge, colour=True))
        if charge.get("dossier"):
            print(f"   {t('Pass recorded in')} {charge['dossier']}")

        commande = ".venv.erplibre/bin/python script/git/repo_pull.py"
        deps = charge.get("dependances") or {}
        if deps.get("a_installer"):
            question = t(
                "Install the Python dependencies now"
                " (poetry install --no-root)? (y/N): "
            )
            plus_tard = (
                f"     {commande} --install-deps --confirm {version}"
                + (
                    f" --pass {charge['horodatage']}"
                    if charge.get("horodatage")
                    else ""
                )
            )
            if input(f"💬 {question}").strip().lower() in oui:
                resultat, code_deps = repo_pull.installer_dependances(
                    RACINE, version, charge["horodatage"], en_direct=True
                )
                if code_deps:
                    erreur = repo_pull.libelle_erreur(
                        resultat.get("error") or str(code_deps)
                    )
                    print(
                        f"⚠  {repo_upgrade.paint(erreur, 'broken', True)}"
                        f" ({t('exit code')} {code_deps})"
                    )
                    if resultat.get("dossier") and resultat.get("code"):
                        journal = os.path.join(resultat["dossier"], "deps.log")
                        print(f"   {t('Log:')} {journal}")
                    print(f"   {t('To retry:')}")
                    print(plus_tard)
                    print(
                        f"   {t('The server can also restart without installing.')}"
                    )
                else:
                    print(f"✅ {t('The Python dependencies are installed.')}")
            else:
                print(f"   {t('To install them later:')}")
                print(plus_tard)

        for res in charge.get("resultats") or []:
            if not res.get("sauvegarde"):
                continue
            designation = f"{res['chemin']}={res['sauvegarde']}"
            print(f"   {res['chemin']} — {t('To restore:')}")
            print(
                f"     {commande} --restore-backup {designation}"
                f" --confirm {version}"
            )
            print(f"   {t('To delete:')}")
            print(
                f"     {commande} --delete-backup {designation}"
                f" --confirm {version}"
            )
        return len(
            [
                r
                for r in charge.get("resultats") or []
                if r["etat"] in repo_pull.ETATS_DEPLACES
            ]
        )

    def _git_repo_ajouter_remotes(self):
        """Pose et récupère le remote amont nommé de chaque fork, sans
        diagnostic (voir `repo_upgrade.ajouter_remotes`).

        Le remote porte le nom de « fork-upstream-remote » et ne suit que
        la branche amont déclarée : elle se lit ensuite
        « <remote>/<branche> », et sur un clone complet un « git fetch
        <remote> » fait à la main la rafraîchit. Un clone superficiel ne se
        rafraîchit que par la commande « fetch --depth » que le rapport
        donne. Un remote homonyme à une autre URL n'est pas touché ; le
        rapport donne la commande qui le corrige, et nomme les forks sautés.

        Toutes les versions d'Odoo du checkout passent, et non la seule
        active : synchroniser une autre version demande ses amonts aussi.

        Rend le nombre de forks dont l'amont est récupéré.
        """
        versions = repo_upgrade.versions_installees(RACINE)
        if not versions:
            versions = [repo_upgrade.version_active(RACINE) or "?"]
        print(
            f"🌐 {t('Add the upstream remotes')} — Odoo {', '.join(versions)}"
        )
        print(f"   {t('Querying each upstream, this takes a few seconds.')}")
        recuperes = 0
        for version in versions:
            lst = repo_upgrade.ajouter_remotes(version, racine=RACINE)
            print()
            print(repo_upgrade.render_remotes(lst, version, colour=True))
            recuperes += len([x for x in lst if x["cible"]])
        return recuperes

    def _git_repo_a_sec(self):
        """Constate ce qu'une mise à niveau ferait.

        N'écrit que le remote amont nommé de chaque fork et sa branche de
        suivi (voir `repo_upgrade.diagnostiquer`) : aucune branche locale,
        aucun arbre de travail.

        Rend le nombre de dépôts qui demandent une décision, ce qui donne à
        l'appelant de quoi s'arrêter là quand il n'y a rien à faire.
        """
        version = repo_upgrade.version_active(RACINE) or "?"
        print(f"🔍 {t('Upgrade dry run')} — Odoo {version}")
        print(f"   {t('Querying each upstream, this takes a few seconds.')}")
        lst = repo_upgrade.passe_diagnostic(version, racine=RACINE)
        print()
        print(repo_upgrade.render_diagnostic(lst, version, colour=True))
        lst = self._git_repo_approfondir(lst, version)
        a_decider = [
            x
            for x in lst
            if x["verdict"] in ("a_rebaser", "en_conflit", "absorbe")
        ]
        return len(a_decider)

    def _git_repo_approfondir(self, lst, version):
        """Propose de compléter les clones superficiels du diagnostic `lst`.

        Un clone superficiel n'a pas de base de fusion avec son amont : le
        diagnostic le laisse « non comparable », hors de la mise à niveau.
        `repo_upgrade.approfondir` rapatrie l'historique entier de la branche
        du fork puis de son amont, un clone après l'autre : en parallèle,
        plusieurs cœurs Odoo se téléchargeraient à la fois. La réponse par
        défaut est non.

        Rend le diagnostic, refait quand au moins un clone a été complété,
        et `lst` tel quel sinon.
        """
        candidats = [x for x in lst if repo_upgrade.a_approfondir(x, RACINE)]
        if not candidats:
            return lst
        print()
        avis = t("Shallow clones: deepening downloads history (network).")
        print(f"⚠️  {avis}")
        print(f"   {t('The whole fork branch, then its upstream branch:')}")
        for x in candidats:
            amont = x["amont"]
            print(
                f"     {x['chemin']} ({x['revision']} ·"
                f" {amont['remote']}/{amont['branche']})"
            )
        reponse = input(
            f"💬 {t('Deepen the shallow clones (network)? (y/N): ')}"
        )
        if reponse.strip().lower() not in ("o", "oui", "y", "yes"):
            print(f"↩️  {t('Not deepened: these forks stay out of it.')}")
            return lst
        complets = 0
        for x in candidats:
            print(f"   {x['chemin']} …", flush=True)
            res = repo_upgrade.approfondir(x, racine=RACINE)
            libelle = repo_upgrade.LIBELLES_APPROFONDIR[res["issue"]]
            if res["issue"] == "complet":
                complets += 1
                print(f"   ✅ {libelle}")
                continue
            erreur = f" — {res['erreur']}" if res["erreur"] else ""
            print(f"   ⚠  {libelle}{erreur}")
            print(f"      {t('By hand:')}")
            for commande in res["commandes"]:
                print(f"        {commande}")
        if not complets:
            return lst
        print()
        print(f"   {t('Querying each upstream, this takes a few seconds.')}")
        lst = repo_upgrade.passe_diagnostic(version, racine=RACINE)
        print()
        print(repo_upgrade.render_diagnostic(lst, version, colour=True))
        return lst

    def _git_repo_etat_forks(self):
        """D'où descend chaque fork, et l'amont répond-il encore.

        Interroge le réseau : c'est le seul moyen de distinguer une branche
        amont déclarée d'une branche amont qui existe. Les commits gelés de
        chaque fork depuis sa base amont gelée se parcourent ensuite, eux
        sans réseau.
        """
        version = repo_upgrade.version_active(RACINE) or "?"
        print(f"🔗 {t('Fork and upstream status')} — Odoo {version}")
        lst = repo_upgrade.etat_forks(version, verifier=True)
        print()
        print(repo_upgrade.render(lst, True, colour=True))
        self._git_repo_parcourir_forks(lst)
        return len(
            [x for x in lst if x["etat"] in repo_upgrade.ETATS_A_CORRIGER]
        )

    def _git_repo_parcourir_forks(self, forks):
        """La table des forks qui portent un commit gelé ET une base amont
        gelée, puis les gestes qui ouvrent « base..gel » dans tig.

        La table se lit dans les clones, sans réseau. « N » ouvre la plage
        du fork N (plusieurs numéros séparés par des virgules aussi), « a »
        chacune de celles qui s'ouvrent ; un tig quitté autrement que par
        « q » arrête la suite. Sans ligne ouvrable, rien n'est demandé.
        """
        lignes = repo_upgrade.nos_commits_geles(forks, RACINE)
        if not lignes:
            return
        print()
        print(f"  {t('Our frozen commits since the frozen upstream base:')}")
        largeur = max(len(lg["chemin"] or "") for lg in lignes)
        for numero, lg in enumerate(lignes, 1):
            plage = f"{lg['base'][:12]}..{lg['gel'][:12]}"
            if lg["motif"]:
                fin = f"⚠ {lg['motif']}"
            else:
                fin = f"+{lg['nos']} {t('ours')}"
            print(
                f"  {numero:>3}  {lg['chemin'] or '':<{largeur}}"
                f"  {plage}  {fin}"
            )
        if all(lg["motif"] for lg in lignes):
            return
        while True:
            print()
            print(f"  N   🐯 {t('tig on fork N: its commits since the base')}")
            print(f"  a   🐯 {t('tig on each fork, one after another')}")
            print(f"  {bleu_poudre('⏎   ' + t('Back'))}")
            choix = input("  : ").strip().lower()
            if choix in ("", "0"):
                return
            if choix == "a":
                choisis = [lg for lg in lignes if not lg["motif"]]
            elif choix == "all":
                choisis = None
            else:
                choisis = choix_numeros(choix, lignes)
            if choisis is None:
                print(t("Command not found !"))
                continue
            for lg in choisis:
                if lg["motif"]:
                    print(f"⚠  {lg['chemin']} — {lg['motif']}")
                    continue
                plage = f"{lg['base']}..{lg['gel']}"
                if git_freeze_diff.open_range(lg["dossier"], plage):
                    break

    def _git_repo_appliquer(self):
        """Constate, montre, demande confirmation, puis applique.

        La passe à sec tourne TOUJOURS d'abord et son compte fait contrat :
        une question posée avant de savoir ce qui sera touché n'est pas un
        consentement, c'est un pari. La réponse par défaut est non.

        Un fork sans commit propre, en retard sur l'amont, avance par
        fast-forward au lieu d'être rebasé.

        Rend le nombre de dépôts rebasés ou avancés.
        """
        version = repo_upgrade.version_active(RACINE) or "?"
        print(f"⬆️  {t('Apply the upgrade')} — Odoo {version}")
        print(f"   {t('Querying each upstream, this takes a few seconds.')}")
        lst = repo_upgrade.passe_diagnostic(version, racine=RACINE)
        print()
        print(repo_upgrade.render_diagnostic(lst, version, colour=True))
        lst = self._git_repo_approfondir(lst, version)
        a_faire = [
            x for x in lst if x["verdict"] in repo_apply.VERDICTS_A_APPLIQUER
        ]
        if not a_faire:
            print(f"\n↩️  {t('Nothing to upgrade: nothing to confirm.')}")
            return 0

        horodatage = datetime.datetime.now().strftime("%Y%m%dT%H%M")
        print()
        print(
            f"⚠️  {len(a_faire)} {t('repositories will be rebased.')}"
            f" {t('A dated branch is created; the current one stays.')}"
        )
        for x in a_faire:
            branche = repo_apply.nom_branche(
                x.get("revision") or "HEAD", horodatage
            )
            avance = (
                f" ({t('fast-forward')})"
                if x["verdict"] == "en_retard"
                else ""
            )
            print(f"     {x['chemin']} → {branche}{avance}")
        print(f"   {t('Nothing is pushed.')}")
        reponse = input(f"💬 {t('Apply the upgrade? (y/N): ')}")
        if reponse.strip().lower() not in ("o", "oui", "y", "yes"):
            print(f"↩️  {t('Cancelled: nothing was written.')}")
            return 0

        print()
        resultats = repo_apply.passe_appliquer(lst, horodatage, racine=RACINE)
        dossier = repo_apply.ecrire_passe(
            horodatage, version, lst, resultats, racine=RACINE
        )
        self._git_repo_resume_passe(resultats)
        print(f"   {t('Pass recorded in')} {dossier}")
        return len(
            [r for r in resultats if r["etat"] in repo_apply.ETATS_PUBLIABLES]
        )

    def _git_repo_resume_passe(self, resultats):
        """Une ligne par état, et la façon de reprendre ce qui a buté."""
        par_etat = {}
        for res in resultats:
            par_etat.setdefault(res["etat"], []).append(res)
        rebases = len(par_etat.get("rebase", []))
        conflits = par_etat.get("conflit", [])
        ligne = (
            f"✅ {decompte(rebases, 'rebase')}"
            f" · {len(conflits)} {t('conflicting')}"
        )
        for etat in ("avance", "publie"):
            if par_etat.get(etat):
                ligne += f" · {decompte(len(par_etat[etat]), etat)}"
        print(ligne)
        for etat, lst in sorted(par_etat.items()):
            if etat in ("rebase", "ignore", "avance", "publie"):
                continue
            for res in lst:
                ligne = f"   ⚠  {res['chemin']} : {t(ETATS.get(etat, etat))}"
                if res.get("restaure") is True:
                    ligne += f" — {t('put back on its start commit')}"
                print(ligne)
                if res.get("restaure") is False:
                    print(
                        f"      {t('could not be put back on its start commit')}"
                    )
                    for x in (res.get("sortie") or "").splitlines()[-1:]:
                        print(f"      {x}")
        if conflits:
            print(f"   {t('Work them through the conflict queue.')}")

    def _git_repo_rapport(self):
        """Ce que la dernière passe a fait, relu depuis son enregistrement
        une fois réconcilié avec l'état réel des dépôts."""
        passe = repo_apply.lire_passe(racine=RACINE)
        if not passe:
            print(f"↩️  {t('No pass recorded yet.')}")
            return 0
        self._git_repo_reconcilier(passe)
        print(
            f"📊 {t('Report of the last pass')} — Odoo {passe['version']}"
            f" — {passe['horodatage']}"
        )
        print()
        self._git_repo_resume_passe(passe["resultats"])
        print()
        for res in passe["resultats"]:
            if res["etat"] == "ignore":
                continue
            ligne = (
                f"   {res['chemin']:44s}"
                f" {t(ETATS.get(res['etat'], res['etat']))}"
            )
            if res.get("branche"):
                ligne += f"  [{res['branche']}]"
            print(ligne)
            for fichier in res.get("conflits") or []:
                print(f"        {fichier}")
        return len(passe["resultats"])

    def _git_repo_file_conflits(self):
        """Les dépôts restés en conflit, repris un par un.

        La file se relit depuis l'enregistrement de passe ET depuis l'état
        réel des dépôts : un rebase repris à la main hors de ce menu doit
        disparaître de la file, et l'enregistrement seul ne le saurait pas.
        La réconciliation (voir `_git_repo_reconcilier`) inscrit l'issue
        d'un tel rebase dans la passe avant de dresser la file.
        """
        passe = repo_apply.lire_passe(racine=RACINE)
        if not passe:
            print(f"↩️  {t('No pass recorded yet.')}")
            return 0
        self._git_repo_reconcilier(passe)
        while True:
            file_attente = [
                res
                for res in passe["resultats"]
                if repo_apply.rebase_en_cours(
                    os.path.join(RACINE, res["chemin"])
                )
            ]
            if not file_attente:
                print(f"✅ {t('No repository is left in conflict.')}")
                return 0
            print(f"\n🧩 {t('Conflict queue')} — {len(file_attente)}")
            for i, res in enumerate(file_attente, 1):
                fichiers = repo_apply.fichiers_en_conflit(
                    os.path.join(RACINE, res["chemin"])
                )
                print(
                    f"  [{i}] {res['chemin']} — {len(fichiers)} "
                    f"{t('conflicting files')}"
                )
            choix = input(
                f"💬 {t('Repository number (empty to go back): ')}"
            ).strip()
            if not choix:
                return len(file_attente)
            try:
                res = file_attente[int(choix) - 1]
            except (ValueError, IndexError):
                print(t("Command not found !"))
                continue
            self._git_repo_resoudre(res, passe["horodatage"])

    def _git_repo_resoudre(self, res, horodatage=None):
        """Les gestes offerts sur un dépôt en conflit.

        « Garder le nôtre » et « prendre l'amont » traversent
        `repo_apply`, qui porte l'inversion de « ours » et « theirs »
        propre au rebase. Les appeler d'ici avec le drapeau qui semble
        juste garderait l'inverse de ce que le libellé annonce.

        Un geste qui quitte le rebase (le dernier « Continuer » ou
        « Sauter », « Abandonner », « Revenir ») réécrit l'enregistrement
        du dépôt dans la passe `horodatage` : la publication et le rapport
        lisent cet état, et non un conflit qui n'existe plus.
        """
        chemin = os.path.join(RACINE, res["chemin"])
        while True:
            fichiers = repo_apply.fichiers_en_conflit(chemin)
            if not fichiers:
                print(f"  {t('Nothing left in conflict here.')}")
            print(f"\n▸ {res['chemin']}")
            for fichier in fichiers:
                print(f"     {fichier}")
            print(f"  [1] 🐚 {t('Open a shell here')}")
            print(f"  [2] 👀 {t('Show the conflicting diff')}")
            print(f"  [3] ⬅️  {t('Keep ours')}")
            print(f"  [4] ➡️  {t('Take upstream')}")
            print(f"  [5] ▶️  {t('Continue the rebase')}")
            print(f"  [6] ⏭️  {t('Skip this commit')}")
            print(f"  [7] ⏸️  {t('Abort this rebase')}")
            print(f"  [8] ↩️  {t('Return to the state managed by repo')}")
            print(f"  {retour('🔙 ' + t('Later'))}")
            choix = input("  : ").strip()
            if choix in ("0", ""):
                return
            if choix == "1":
                self.execute.exec_command_live(
                    f"cd {chemin} && $SHELL", source_erplibre=False
                )
            elif choix == "2":
                self.execute.exec_command_live(
                    f"cd {chemin} && git diff --diff-filter=U",
                    source_erplibre=False,
                )
            elif choix == "3":
                repo_apply.garder_le_notre(chemin, fichiers)
                repo_apply.marquer_resolus(chemin, fichiers)
            elif choix == "4":
                repo_apply.prendre_l_amont(chemin, fichiers)
                repo_apply.marquer_resolus(chemin, fichiers)
            elif choix == "5":
                _out, err, code = repo_apply.continuer_rebase(chemin)
                if code:
                    print(f"  ⚠  {err.strip()[:200]}")
                if not repo_apply.rebase_en_cours(chemin):
                    self._git_repo_noter(horodatage, res, "rebase")
                    print(f"  ✅ {t('Rebase finished.')}")
                    return
            elif choix == "6":
                repo_apply.sauter_le_commit(chemin)
                if not repo_apply.rebase_en_cours(chemin):
                    self._git_repo_noter(horodatage, res, "rebase")
                    print(f"  ✅ {t('Rebase finished.')}")
                    return
            elif choix == "7":
                repo_apply.abandonner_rebase(chemin)
                self._git_repo_noter(horodatage, res, "abandonne")
                print(f"  ↩️  {t('Rebase aborted.')}")
                return
            elif choix == "8":
                repo_apply.revenir_a_repo(chemin, res.get("depart"))
                self._git_repo_noter(horodatage, res, "revenu")
                print(f"  ↩️  {t('Back to the state managed by repo.')}")
                return
            else:
                print(t("Command not found !"))

    def _git_repo_reconcilier(self, passe):
        """Aligne `passe` sur l'état réel des dépôts, voir
        `repo_apply.reconcilier_passe`, et dit ce qui a changé ou non."""
        for res, avant, apres in repo_apply.reconcilier_passe(
            passe, racine=RACINE
        ):
            if apres:
                print(
                    f"   🔁 {res['chemin']}: {t(ETATS.get(avant, avant))}"
                    f" → {t(ETATS.get(apres, apres))}"
                )
            else:
                print(
                    f"   ⚠  {res['chemin']}:"
                    f" {t('no rebase in progress and no known outcome, record left as is')}"
                )

    def _git_repo_noter(self, horodatage, res, etat):
        """Inscrit `etat` pour `res` dans la passe, quand elle est connue."""
        if horodatage:
            repo_apply.noter_resolution(horodatage, res, etat, racine=RACINE)

    def _git_repo_publier(self):
        """Pousse sur leur fork les branches datées de la dernière passe.

        Chaque dépôt montre ce qui partirait — remote, branche, ancienne et
        nouvelle pointe, forcé ou non — et rien ne part sans confirmation.
        Avant un push forcé, une ancienne pointe qu'aucun tag ni aucune
        autre branche ne retient reçoit d'abord un tag ou une branche, au
        nom proposé et modifiable, poussé AVANT le push forcé. Un distant
        dont la pointe suivie a quitté celle que la passe a relevée refuse
        la publication du dépôt. Les dépôts publiés se regèlent ensuite sur
        demande, par le gel du menu. La passe est d'abord réconciliée avec
        l'état réel des dépôts (voir `_git_repo_reconcilier`) : un rebase
        fini hors du menu y devient publiable.

        Rend le nombre de dépôts publiés.
        """
        passe = repo_apply.lire_passe(racine=RACINE)
        if not passe:
            print(f"↩️  {t('No pass recorded yet.')}")
            return 0
        self._git_repo_reconcilier(passe)
        candidats = [r for r in passe["resultats"] if repo_apply.publiable(r)]
        print(f"📤 {t('Publish the updated forks')} — {passe['horodatage']}")
        if not candidats:
            print(f"↩️  {t('Nothing to publish in the last pass.')}")
            return 0
        for i, res in enumerate(candidats, 1):
            print(
                f"  [{i}] {res['chemin']}  [{res['branche']}]"
                f" {t(ETATS.get(res['etat'], res['etat']))}"
            )
        choix = input(
            f"💬 {t('Numbers to publish, separated by commas (all, empty to cancel): ')}"
        ).strip()
        if not choix:
            print(f"↩️  {t('Cancelled: nothing was pushed.')}")
            return 0
        choisis = choix_numeros(choix, candidats)
        if choisis is None:
            print(t("Command not found !"))
            return 0
        publies = []
        for res in choisis:
            if self._git_repo_publier_un(passe, res):
                publies.append(res["chemin"])
        print(f"\n✅ {decompte(len(publies), 'publie')}")
        if publies:
            print(
                f"   {t('The manifest still holds the old frozen commits.')}"
            )
            if click.confirm(
                t("Freeze the versions again now?"), default=True
            ):
                self._git_repo_geler()
            else:
                print(f"   {t('Freeze the versions, then commit manifest/.')}")
        return len(publies)

    def _git_repo_publier_un(self, passe, res):
        """Publie un dépôt de la passe. True une fois le push accepté."""
        chemin = os.path.join(RACINE, res["chemin"])
        plan = repo_apply.plan_publication(chemin, res)
        print(f"\n▸ {res['chemin']}")
        if not plan:
            print(f"  ⚠  {t('The dated branch is missing: nothing to push.')}")
            return False
        if plan.get("refus"):
            print(f"  ⚠  {plan['refus']}")
            return False
        if plan["a_retenir"] and not self._git_repo_retenir(
            chemin, plan, passe
        ):
            return False
        ancien = (plan["ancien"] or "—")[:12]
        genre = t("forced (lease)") if plan["force"] else t("fast-forward")
        print(f"  {t('Remote:')} {plan['remote']}")
        print(f"  {t('Branch:')} {plan['branche']} → {plan['revision']}")
        print(f"  {ancien} → {plan['nouveau'][:12]} · {genre}")
        if not click.confirm(t("Push to the fork?"), default=False):
            print(f"  ↩️  {t('Cancelled: the fork branch was not pushed.')}")
            return False
        _out, err, code = repo_apply.publier(chemin, plan)
        if code:
            print(f"  ⚠  {err.strip()[:400]}")
            return False
        repo_apply.mettre_a_jour_passe(
            passe["horodatage"],
            res["chemin"],
            {"etat": "publie", "publie": plan["nouveau"]},
            racine=RACINE,
        )
        print(f"  ✅ {t(ETATS['publie'])} {plan['nouveau'][:12]}")
        return True

    def _git_repo_retenir(self, chemin, plan, passe):
        """Pose un tag ou une branche sur l'ancienne pointe, puis la pousse.

        Le nom proposé se modifie avant la confirmation. Rend True quand
        plus aucun commit n'est à retenir.
        """
        ancien = plan["ancien"]
        print(
            f"  ⚠  {ancien[:12]}"
            f" {t('is retained by no tag or branch: the forced push would lose it.')}"
        )
        genre = click.prompt(
            f"  {t('Keep it with a tag or a branch?')}",
            type=click.Choice(["tag", "branch"]),
            default="tag",
        )
        horodatage = passe["horodatage"]
        if genre == "tag":
            defaut = repo_apply.nom_par_defaut_tag(
                repo_apply.version_erplibre(RACINE),
                passe["version"],
                repo_apply.tags(chemin),
                horodatage,
            )
        else:
            defaut = repo_apply.nom_par_defaut_branche(
                plan["revision"], horodatage
            )
        nom = click.prompt(f"  {t('Name')}", default=defaut).strip()
        question = (
            f"{t('Push')} {genre} {nom} ({ancien[:12]}) → {plan['remote']}?"
        )
        if not nom or not click.confirm(question, default=False):
            print(f"  ↩️  {t('Cancelled: nothing was pushed.')}")
            return False
        _out, err, code = repo_apply.retenir(
            chemin,
            ancien,
            plan["remote"],
            "tag" if genre == "tag" else "branche",
            nom,
        )
        if code:
            print(f"  ⚠  {err.strip()[:400]}")
            return False
        plan["a_retenir"] = repo_apply.a_retenir(
            chemin,
            ancien,
            plan.get("gel"),
            plan["nouveau"],
            plan["remote"],
            plan["revision"],
        )
        if plan["a_retenir"]:
            print(f"  ⚠  {t('commits retained by no tag or branch')}")
            return False
        return True

    def _git_repo_ecran(self):
        """Ouvre l'écran de parcours. Lecture seule.

        L'écran ne fait que MONTRER : sur seize dépôts et quelques centaines
        de modules apportés, le rapport texte dit tout d'un coup, et ce
        qu'on cherche se trouve quelque part au milieu.
        """
        from script.todo import git_repo_tui, textual_setup

        if not textual_setup.ensure():
            print(f"↩️  {t('Falling back to the text report.')}")
            return self._git_repo_a_sec()
        version = repo_upgrade.version_active(RACINE) or "?"
        print(f"   {t('Querying each upstream, this takes a few seconds.')}")
        lst = repo_upgrade.passe_diagnostic(version, racine=RACINE)
        git_repo_tui.run_git_repo_tui({"version": version, "forks": lst})
        return len(lst)

    def _git_repo_geler(self, unfreeze=False):
        """Écrit le commit de chaque clone de la version d'Odoo active dans
        son fichier de `manifest/`, ou l'ôte de tous les fichiers.

        Le geste écrit des fichiers de `manifest/` à committer et ne déplace
        aucun clone. La passe à sec tourne d'abord et montre chaque fichier
        touché ; rien ne s'écrit sans confirmation. Le gel prend effet à la
        reconfiguration sur les commits gelés ; le dégel, à la
        reconfiguration qui suit les branches.

        Le gel demande d'abord s'il écrit aussi la base amont de chaque fork
        (« --upstream »), non par défaut : elle passe par le réseau. La
        réponse vaut pour la passe à sec ET pour l'écriture : la passe à sec
        montre donc les bases que l'écriture posera. Chaque passe interroge
        l'amont, la passe à sec ne laissant rien que l'écriture puisse
        relire ; le second fetch ne rapatrie que ce qui a bougé depuis le
        premier.

        Il demande ensuite s'il gèle aussi la branche de chaque clone
        (« --branches »), non par défaut : un clone extrait sur une branche
        autre que celle du manifeste la donne à « revision ». Une branche
        absente de son remote, ou en avance sur lui, ne peut s'écrire ; le
        menu les liste et propose de les pousser, sans force, AVANT la passe
        à sec, qui montre alors les branches que l'écriture posera.

        Rend le code de sortie du script : 1 quand aucun clone n'est gelable.
        """
        script = f"{PYTHON_ERPLIBRE} {FREEZE_SCRIPT}"
        if unfreeze:
            script += " --unfreeze"
            print(f"🫗 {t('Unfreeze the versions')}")
        else:
            print(f"🧊 {t('Freeze the versions')}")
            if click.confirm(
                t("Also freeze the upstream base of each fork (network)?"),
                default=False,
            ):
                script += " --upstream"
                attente = t(
                    "Querying each upstream, this takes a few seconds."
                )
                print(f"   {attente}")
            if click.confirm(
                t("Also freeze the branch each clone is on (revision)?"),
                default=False,
            ):
                script += " --branches"
                self._git_repo_publier_branches()
        cmd = f"{script} --dry-run"
        print(f"  {t('Will execute:')} {cmd}")
        status = self.execute.exec_command_live(
            f"cd {RACINE} && {cmd}", source_erplibre=False
        )
        if status:
            echec = t("Nothing was written; see the messages above.")
            print(f"⚠  {echec} ({status})")
            return status
        if not click.confirm(
            t("Write these changes to the manifest files?"), default=False
        ):
            print(f"↩️  {t('Cancelled: nothing was written.')}")
            return 0
        print(f"  {t('Will execute:')} {script}")
        status = self.execute.exec_command_live(
            f"cd {RACINE} && {script}", source_erplibre=False
        )
        if status:
            print(f"⚠  {t('The manifest files were not written.')} ({status})")
            return status
        print(f"✅ {t('Manifest files written; commit them to share them.')}")
        if unfreeze:
            print(f"   {t('Apply with: Switch to development.')}")
        else:
            print(f"   {t('Apply with: Switch to production.')}")
        return 0

    def _git_repo_publier_branches(self):
        """Propose de pousser les branches que le gel ne peut écrire.

        Liste les branches extraites absentes de leur remote ou en avance
        sur lui (`git_freeze_manifest.branches_a_publier`), puis demande :
        toutes, une à une, ou aucune, aucune par défaut ; puis vers quel
        remote, par défaut celui du manifeste de chaque projet. Un autre
        remote se choisit parmi ceux des clones retenus, mais le gel
        n'écrit une branche que si le remote du MANIFESTE la porte : il est
        donc signalé. Chaque push porte la branche locale sur la branche
        homonyme, jamais de force, `push_remote.PARALLELE` à la fois. Rend
        le nombre de branches poussées.
        """
        depart = os.getcwd()
        try:
            os.chdir(RACINE)
            lst = git_freeze_manifest.branches_a_publier()
        finally:
            os.chdir(depart)
        if not lst:
            return 0
        print(
            f"   {len(lst)}"
            f" {t('branches are missing from their remote or behind it: the freeze cannot write them.')}"
        )
        for e in lst:
            genre = (
                t("new branch")
                if e["motif"] == git_freeze_manifest.BRANCHE_ABSENTE
                else t("fast-forward")
            )
            print(
                f"   ▸ {e['chemin']}: {e['branche']} → {e['remote']} · {genre}"
            )
        choix = click.prompt(
            f"💬 {t('Push them? all, each or none')}",
            type=click.Choice(["all", "each", "none"]),
            default="none",
        )
        if choix == "none":
            print(
                f"↩️  {t('Nothing pushed: these projects keep their manifest branch.')}"
            )
            return 0
        choisies = [
            e
            for e in lst
            if choix == "all"
            or click.confirm(
                f"{t('Push')} {e['branche']} ({e['chemin']}) → {e['remote']}?",
                default=False,
            )
        ]
        if not choisies:
            return 0
        remote = self._git_repo_choisir_remote_branches(choisies)
        cibles = [
            {
                "chemin": os.path.join(RACINE, e["chemin"]),
                "remote": remote or e["remote"],
                "specs": [
                    f"refs/heads/{e['branche']}:refs/heads/{e['branche']}"
                ],
                "entree": e,
            }
            for e in choisies
        ]

        def suivi(r):
            e = r["entree"]
            if not r["code"]:
                print(f"  ✅ {e['chemin']}: {e['branche']} → {r['remote']}")
                return
            print(f"  ⚠  {e['chemin']}: {r['erreur'][:400]}")
            if e["motif"] == git_freeze_manifest.BRANCHE_ABSENTE:
                conseil = t(
                    "If the remote already has this branch, fetch it,"
                    " then freeze again."
                )
                print(f"     {conseil}")

        resultats = push_remote.pousser_en_parallele(cibles, suivi=suivi)
        poussees = len([r for r in resultats if not r["code"]])
        print(f"   {poussees}/{len(lst)} {t('branches pushed.')}")
        return poussees

    def _git_repo_choisir_remote_branches(self, entrees):
        """Le remote où pousser les branches `entrees`, ou None pour celui
        du manifeste de chaque projet (le défaut). Seuls les remotes qu'un
        des clones porte se proposent."""
        chemins = [os.path.join(RACINE, e["chemin"]) for e in entrees]
        du_manifeste = {e["remote"] for e in entrees}
        autres = [
            r
            for r in push_remote.remotes_des_clones(chemins)
            if r not in du_manifeste
        ]
        if not autres:
            return None
        choix = click.prompt(
            f"💬 {t('Push to: manifest (the remote of each project) or')}"
            f" {', '.join(autres)}",
            type=click.Choice(["manifest"] + autres),
            default="manifest",
        )
        if choix == "manifest":
            return None
        print(
            f"   ⚠  {t('The freeze writes a branch only when the manifest remote carries it.')}"
        )
        return choix

    def _git_repo_pousser_remote(self):
        """Pousse les dépôts de la version active vers un remote choisi.

        Le remote est l'un de ceux des clones, ou un remote neuf que
        `_git_repo_nouveau_remote` pose à partir de l'URL d'une forge. Le
        contenu se demande : la branche du manifeste (le défaut) ou tout ce
        que le clone connaît. Un clone superficiel peut d'abord être
        approfondi, non par défaut. Rien ne part sans confirmation ; les
        pushes, jamais forcés, tournent `push_remote.PARALLELE` à la fois.
        Rend le nombre d'échecs, ou 0.
        """
        print(f"📡 {t('Push the repositories to a remote')}")
        depart = os.getcwd()
        try:
            os.chdir(RACINE)
            projets = push_remote.projets_actifs()
        finally:
            os.chdir(depart)
        if not projets:
            print(
                f"⚠  {t('No cloned repository for the active Odoo version.')}"
            )
            return 0
        for p in projets:
            p["affiche"] = p["chemin"]
            p["chemin"] = os.path.join(RACINE, p["chemin"])
        racine = push_remote.projet_racine(RACINE)
        if racine and click.confirm(
            f"💬 {t('Also push the ERPLibre repository, which holds the manifests?')}"
            f" ({racine['branche']})",
            default=True,
        ):
            racine["affiche"] = f"ERPLibre ({racine['branche']})"
            projets.insert(0, racine)
        remotes = push_remote.remotes_des_clones(
            [p["chemin"] for p in projets]
        )
        noms = list(remotes)
        print(
            f"   {len(projets)}"
            f" {t('cloned repositories of the active Odoo version.')}"
        )
        for i, nom in enumerate(noms, 1):
            print(f"   {i}. {nom} ({remotes[nom]}/{len(projets)})")
        print(f"   n. {t('New remote from the URL of a forge')}")
        choix = click.prompt(f"💬 {t('Remote')}", default="n").strip().lower()
        exclus = set()
        if choix == "n":
            nom, exclus = self._git_repo_nouveau_remote(projets)
            if not nom:
                print(f"↩️  {t('Cancelled: nothing was pushed.')}")
                return 0
        elif choix.isdigit() and 1 <= int(choix) <= len(noms):
            nom = noms[int(choix) - 1]
        else:
            print(t("Command not found !"))
            return 0
        mode = click.prompt(
            f"💬 {t('What to push? manifest: the manifest branch; all: every branch and tag')}",
            type=click.Choice(list(push_remote.MODES)),
            default=push_remote.MODE_MANIFESTE,
        )
        projets = [p for p in projets if p["chemin"] not in exclus]
        superficiels = [
            p for p in projets if repo_upgrade.est_superficiel(p["chemin"])
        ]
        if superficiels:
            for p in superficiels:
                print(f"   ▸ {p['affiche']}")
            question = t(
                "These clones are shallow: fetch their full history first? It can take long."
            )
            if click.confirm(f"💬 {question}", default=False):
                for p in superficiels:
                    code, err = push_remote.approfondir(
                        p["chemin"], p["remote"]
                    )
                    if code:
                        print(f"  ⚠  {p['affiche']}: {err[-300:]}")
        cibles, ecartes = push_remote.preparer_cibles(projets, nom, mode)
        for p, motif in ecartes:
            print(f"   - {p['affiche']}: {motif}")
        if not cibles or not click.confirm(
            f"{t('Push')} {len(cibles)} {t('repositories to')} {nom}"
            f" ({push_remote.PARALLELE} {t('at a time')})?",
            default=False,
        ):
            print(f"↩️  {t('Cancelled: nothing was pushed.')}")
            return 0
        affiches = {p["chemin"]: p["affiche"] for p in projets}

        def suivi(r):
            marque = "✅" if not r["code"] else "⚠ "
            print(f"  {marque} {affiches[r['chemin']]}", flush=True)

        resultats = push_remote.pousser_en_parallele(cibles, suivi=suivi)
        echecs = [r for r in resultats if r["code"]]
        print(
            f"   {len(resultats) - len(echecs)}/{len(resultats)}"
            f" {t('repositories pushed.')}"
        )
        for r in echecs:
            print(f"   - {affiches[r['chemin']]}: {r['erreur'][-300:]}")
        pousses = {r["chemin"] for r in resultats if not r["code"]}
        manifeste = [
            p
            for p in projets
            if p["chemin"] in pousses and p["chemin"] != RACINE
        ]
        if manifeste and nom not in {p["remote"] for p in projets}:
            self._git_repo_proposer_surcouche(nom, manifeste)
        return len(echecs)

    def _git_repo_nouveau_remote(self, projets):
        """Pose un remote neuf dans chaque clone. Rend (nom, chemins exclus)
        ou (None, ()) quand rien n'est posé.

        Le nom ne peut pas être celui d'un remote du manifeste : git-repo en
        réécrirait l'URL à la synchronisation suivante. L'URL de chaque
        clone est « <base>/<propriétaire>/<dépôt> » (`push_remote.plan_remote`).
        Un clone où ce nom vise déjà un autre dépôt garde son remote et est
        exclu du push, comme un clone sans propriétaire connu.
        """
        nom = click.prompt(
            f"💬 {t('Name of the new remote')}", default="forge"
        ).strip()
        if nom in {p["remote"] for p in projets}:
            print(
                f"⚠  {t('This name is a manifest remote: git-repo would rewrite its URL.')}"
            )
            return None, ()
        if not forge_manifest.NOM_VALIDE.match(nom):
            print(
                f"⚠  {t('Invalid remote name: letters, digits, dot, dash and underscore.')}"
            )
            return None, ()
        base = click.prompt(
            f"💬 {t('Base URL of the forge (https://… or ssh://…), or qemu to create a Forgejo VM')}"
        ).strip()
        if base.lower() == "qemu":
            base = self._git_forge_creer_vm(projets)
            if not base:
                return None, ()
        if not re.match(r"^(?:https?|ssh)://[^/]+|^[^@/:]+@[^/:]+:", base):
            print(f"⚠  {t('Not a forge URL.')}")
            return None, ()
        if base.startswith("http://"):
            print(
                f"   ⚠  {t('Plain HTTP: credentials cross the network in clear.')}"
            )
        poses, sans = push_remote.plan_remote(projets, nom, base)
        for p, motif in sans:
            print(f"   - {p['affiche']}: {motif}")
        if not poses:
            return None, ()
        exemple_p, exemple_url = poses[0]
        print(f"   {t('Example:')} {exemple_p['affiche']} → {exemple_url}")
        if not click.confirm(
            f"{t('Add the remote')} {nom} {t('to')} {len(poses)} {t('clones?')}",
            default=False,
        ):
            return None, ()
        etats = {}
        exclus = {p["chemin"] for p, _ in sans}
        for (p, url), (etat, en_place) in zip(
            poses,
            push_remote._en_parallele(
                lambda pu: push_remote.poser_remote(
                    pu[0]["chemin"], nom, pu[1]
                ),
                poses,
                push_remote.PARALLELE,
            ),
        ):
            etats[etat] = etats.get(etat, 0) + 1
            if etat in ("autre_url", "refuse", "non_clone"):
                exclus.add(p["chemin"])
                print(
                    f"   ⚠  {p['affiche']}: {etat} {en_place or ''}".rstrip()
                )
        print("   " + ", ".join(f"{n} {e}" for e, n in sorted(etats.items())))
        retenus = [(p, u) for p, u in poses if p["chemin"] not in exclus]
        if retenus and not self._git_repo_preparer_forge(base, retenus):
            return None, ()
        return nom, exclus

    # ── Forge Forgejo ────────────────────────────────────────────────

    def _git_forge_titre(self, hote):
        return f"Forgejo token {hote}"

    def _git_forge_kp(self):
        """Le coffre KeePass ouvert, ou None : aucun coffre configuré, son
        fichier absent, ou son ouverture abandonnée. Un « kdbx.path » dont
        le fichier manque n'est pas ouvert : PyKeePass lèverait
        FileNotFoundError après avoir demandé le mot de passe maître."""
        vault = self._git_forge_vault()
        if vault:
            chemin = vault.vault_path()
            if chemin and not os.path.exists(os.path.expanduser(chemin)):
                return None
        coffre = getattr(self, "_git_coffre", None)
        if not coffre:
            return None
        try:
            return coffre()
        except (OSError, EOFError):
            return None

    def _git_forge_jeton_du_coffre(self, hote):
        """Le jeton de la forge `hote` (« hôte[:port] ») rangé dans le
        coffre KeePass, ou "" sans coffre ou sans entrée."""
        kp = self._git_forge_kp()
        if not kp:
            return ""
        entree = kp.find_entries_by_title(
            self._git_forge_titre(hote), first=True
        )
        return getattr(entree, "password", "") or ""

    def _git_forge_ranger_jeton(self, hote, jeton):
        """Range le jeton de `hote` dans le coffre, entrée créée ou
        remplacée, groupe GROUPE_FORGE. Rend False sans coffre configuré."""
        return self._git_forge_ranger(self._git_forge_titre(hote), jeton)

    def _git_forge_ranger(self, titre, secret, compte=""):
        """Range `secret` sous l'entrée `titre` du groupe GROUPE_FORGE,
        créée ou remplacée, avec `compte` pour identifiant. Rend False sans
        coffre configuré."""
        kp = self._git_forge_kp()
        if not kp:
            return False
        entree = kp.find_entries_by_title(titre, first=True)
        if entree is None:
            groupe = next(
                (g for g in kp.root_group.subgroups if g.name == GROUPE_FORGE),
                None,
            ) or kp.add_group(kp.root_group, GROUPE_FORGE)
            kp.add_entry(groupe, titre, compte, secret)
        else:
            entree.password = secret
            if compte:
                entree.username = compte
        kp.save()
        # save() redonne au fichier le mode du umask : le coffre revient
        # en 0600.
        vault = self._git_forge_vault()
        if vault:
            vault.protect()
        return True

    def _git_forge_vault(self):
        """Le pont vers le coffre KeePass de la session (celui du menu VPN),
        ou None hors du CLI TODO."""
        config = getattr(self, "config_file", None)
        manager = getattr(self, "kdbx_manager", None)
        if not (config and manager):
            return None
        from script.vpn.vault import VpnVault

        return VpnVault(config, manager)

    def _git_forge_creer_coffre(self):
        """Propose de créer le coffre KeePass absent. Rend vrai quand un
        coffre est configuré à la sortie.

        La création passe par `VpnVault.ensure_vault` : chemin demandé
        (~/.erplibre/secrets.kdbx par défaut), mot de passe maître saisi
        deux fois, fichier en 0600, et « kdbx.path » écrit dans la
        configuration privée, que git ne suit pas."""
        vault = self._git_forge_vault()
        if not vault:
            return False
        chemin = vault.vault_path()
        if chemin and os.path.exists(os.path.expanduser(chemin)):
            # Un coffre configuré et présent qui ne s'est pas ouvert (mot de
            # passe maître abandonné) : rien à créer, et le redemander
            # tournerait en rond.
            print(
                f"   ⚠  {t('The KeePass vault could not be opened: the token stays for this session only.')}"
            )
            return False
        if not click.confirm(
            f"💬 {t('No KeePass vault configured (kdbx.path): create one now?')}",
            default=True,
        ):
            return False
        from script.vpn.vault import VaultError

        try:
            return bool(vault.ensure_vault(ask=input, confirm_create=False))
        except (VaultError, OSError, EOFError) as exc:
            print(f"   ✗ {exc}")
            return False

    def _git_forge_obtenir_jeton(self, web):
        """Un jeton pour la forge `web`, ou "" si l'utilisateur renonce.

        Trois façons, la première par défaut : le coller ; le créer par
        l'API avec l'identifiant et le mot de passe du compte, saisis sans
        écho ; ou le créer sur l'hôte de la forge par SSH, avec la CLI
        d'administration de Forgejo aux chemins de l'installateur du dépôt.
        Un jeton créé porte les portées que la préparation exige et un nom
        daté, unique pour le compte."""
        import getpass
        import time
        import urllib.parse

        print(
            f"   {t('A Forgejo access token is needed, with the write:organization, write:repository and write:user scopes.')}"
        )
        facon = click.prompt(
            f"💬 {t('Token: paste it, create it with the account password (password), or on the forge host by SSH (ssh)')}",
            type=click.Choice(["paste", "password", "ssh"]),
            default="paste",
        )
        nom = f"erplibre-todo-{time.strftime('%Y%m%d-%H%M%S')}"
        if facon == "paste":
            return getpass.getpass(
                t("Paste the token (hidden, Enter to cancel): ")
            ).strip()
        if facon == "password":
            if web.startswith("http://") and not forgejo_client.est_locale(
                web
            ):
                if not click.confirm(
                    f"💬 {t('Plain HTTP: the account PASSWORD would cross the network in clear. Continue?')}",
                    default=False,
                ):
                    return ""
            compte = click.prompt(
                f"💬 {t('Forge account')}", default="", show_default=False
            ).strip()
            mot_de_passe = getpass.getpass(
                t("Password of the account (hidden): ")
            )
            if not compte or not mot_de_passe:
                return ""
            try:
                return forgejo_client.ClientForgejo(
                    web, identifiants=(compte, mot_de_passe)
                ).creer_jeton(nom, forgejo_client.PORTEES)
            except forgejo_client.ErreurForgejo as exc:
                print(f"❌ Forgejo : {exc}")
                return ""
        hote = urllib.parse.urlsplit(web).hostname or ""
        cible = click.prompt(
            f"💬 {t('SSH access to the forge host')}",
            default=f"erplibre@{hote}",
        ).strip()
        compte = click.prompt(
            f"💬 {t('Forge account that receives the token')}",
            default="erplibre",
        ).strip()
        jeton, motif = forgejo_client.creer_jeton_par_ssh(cible, compte, nom)
        if not jeton:
            print(f"❌ {cible} : {motif}")
            print(
                f"   {t('The host needs the forge installed by ERPLibre and sudo without a password; otherwise create the token there and paste it.')}"
            )
            return ""
        print(f"   ✓ {t('Token created:')} {nom}")
        return jeton

    def _git_forge_client(self, base):
        """Le client Forgejo de la forge de `base`, vérifié, ou None.

        L'URL web se déduit d'une base http(s) ; une base SSH la fait
        demander. Une URL http:// hors de cette machine demande
        confirmation, non par défaut : le jeton y passerait en clair. Le
        jeton vient de EL_FORGEJO_TOKEN ou du coffre (une entrée par forge,
        hôte et port), sinon `_git_forge_obtenir_jeton` le fait coller ou
        créer. La forge doit répondre
        à « version » puis reconnaître le jeton ; un jeton refusé (401 ou
        403) peut se ressaisir, et le jeton saisi peut être rangé dans le
        coffre, en remplaçant l'entrée périmée.
        """
        session = getattr(self, "_git_forge_session", {}).get(base)
        web = session["web"] if session else forgejo_client.base_web(base)
        if not web:
            web = forgejo_client.base_web(
                click.prompt(
                    f"💬 {t('Web URL of the forge (https://…)')}"
                ).strip()
            )
            if not web:
                print(f"⚠  {t('Not a forge URL.')}")
                return None
        # La forge que cette session vient de créer dans une VM locale est
        # jointe par le pont libvirt de la machine, où son mot de passe
        # administrateur est déjà passé : la question ne se repose pas.
        if (
            not session
            and web.startswith("http://")
            and not forgejo_client.est_locale(web)
        ):
            if not click.confirm(
                f"💬 {t('Plain HTTP: send the token in clear to')}"
                f" {forgejo_client.cle_forge(web)}?",
                default=False,
            ):
                return None
        forge = forgejo_client.cle_forge(web)
        if session:
            jeton, source = session["jeton"], "vm"
        else:
            jeton, source = forgejo_client.jeton(
                forge, coffre=self._git_forge_jeton_du_coffre
            )
        print(f"   {t('Forge:')} {web}")
        while True:
            if not jeton:
                jeton = self._git_forge_obtenir_jeton(web)
                if not jeton:
                    return None
                source = "saisi"
            try:
                client = forgejo_client.ClientForgejo(web, jeton_api=jeton)
                version = client.version()
                compte = client.identite()
                break
            except forgejo_client.ErreurForgejo as exc:
                print(f"❌ Forgejo : {exc}")
                refuse = (
                    exc.statut in (401, 403)
                    or exc.statut is None
                    and ("token" in str(exc))
                )
                if not refuse or not click.confirm(
                    f"💬 {t('The token was refused')} ({source})."
                    f" {t('Type another one?')}",
                    default=True,
                ):
                    return None
                jeton = ""
        print(f"   Forgejo {version} · {compte}")
        if source == "saisi" and click.confirm(
            f"💬 {t('Store the token in the ERPLibre KeePass vault?')}",
            default=True,
        ):
            if self._git_forge_ranger_jeton(forge, jeton) or (
                self._git_forge_creer_coffre()
                and self._git_forge_ranger_jeton(forge, jeton)
            ):
                print(f"   ✓ {GROUPE_FORGE} › {self._git_forge_titre(forge)}")
            elif not self._git_forge_vault():
                print(
                    f"   ⚠  {t('No KeePass vault configured (kdbx.path): the token stays for this session only.')}"
                )
        return client

    def _git_repo_preparer_forge(self, base, poses):
        """Prépare la forge avant le push. Rend False pour tout arrêter.

        Le push-to-create de Forgejo ne crée jamais le propriétaire d'un
        dépôt. Chaque propriétaire est lu (`plan_proprietaires`) : une
        organisation absente se crée, privée, après confirmation ; le
        compte du jeton reçoit ses dépôts sur lui-même ; un autre compte est
        signalé et ses projets laissés hors des créations. Les dépôts se
        créent par l'API seulement sur demande, non par défaut : une forge
        réglée en push-to-create les crée au premier push. Une forge
        injoignable, un jeton refusé ou une lecture refusée laissent
        choisir de pousser quand même, non par défaut.
        """
        if not click.confirm(
            f"💬 {t('Check the forge through its API and create the missing organisations?')}",
            default=True,
        ):
            return True
        client = self._git_forge_client(base)
        pousser_quand_meme = (
            f"💬 {t('Push anyway, without preparing the forge?')}"
        )
        if client is None:
            return click.confirm(pousser_quand_meme, default=False)
        natures = forgejo_client.plan_proprietaires(
            client,
            forgejo_client.organisations_requises(
                p["proprietaire"] for p, _ in poses
            ),
        )
        erreurs = {n: v for n, v in natures.items() if v.startswith("erreur")}
        for nom, nature in natures.items():
            if nature in ("utilisateur", "compte") or nom in erreurs:
                libelle = {
                    "utilisateur": t("another user account: left as is"),
                    "compte": t("the account of the token"),
                }.get(nature, nature)
                print(f"   ▸ {nom}: {libelle}")
        if erreurs:
            return click.confirm(pousser_quand_meme, default=False)
        absentes = [n for n, v in natures.items() if v == "absent"]
        print(
            f"   {len(natures)} {t('organisations,')} {len(absentes)}"
            f" {t('to create:')} {', '.join(absentes) or '—'}"
        )
        if absentes and click.confirm(
            f"💬 {t('Create the missing organisations, private?')}",
            default=True,
        ):
            for nom, (etat, message) in forgejo_client.assurer_organisations(
                client, absentes
            ).items():
                print(
                    f"   {'✅' if etat != 'erreur' else '⚠ '} {nom}: {etat} {message}".rstrip()
                )
        a_creer = [
            (p, u)
            for p, u in poses
            if natures.get(
                next(
                    (
                        n
                        for n in natures
                        if n.lower() == p["proprietaire"].lower()
                    ),
                    "",
                )
            )
            in ("organisation", "compte", "absent")
        ]
        if a_creer and click.confirm(
            f"💬 {t('Create the missing repositories through the API? Needed when the forge does not create them on push.')}",
            default=False,
        ):

            def assurer(pu):
                p = pu[0]
                try:
                    return (
                        client.assurer_depot(p["proprietaire"], p["nom"])[0],
                        "",
                    )
                except forgejo_client.ErreurForgejo as exc:
                    return "erreur", str(exc)

            compte = {}
            for (p, _), (etat, message) in zip(
                a_creer, push_remote._en_parallele(assurer, a_creer, 4)
            ):
                compte[etat] = compte.get(etat, 0) + 1
                if etat == "erreur":
                    print(f"   ⚠  {p['affiche']}: {message}")
            print(
                "   "
                + ", ".join(f"{n} {e}" for e, n in sorted(compte.items()))
            )
        return True

    def _git_forge_creer_vm(self, projets=()):
        """Crée une VM QEMU qui porte une forge Forgejo et rend la base SSH
        de ses dépôts, ou None.

        `forge_vm.deployer` y pose .venv.erplibre seul — pas d'Odoo — et
        Forgejo en push-to-create, inscriptions fermées, dépôts privés par
        défaut. Le compte administrateur ne doit recouvrir aucun
        propriétaire des `projets` : Forgejo compare les noms sans égard à
        la casse, et ce compte empêcherait l'organisation. Son mot de passe,
        tiré au hasard, et le jeton créé se rangent dans le coffre KeePass ;
        sans coffre, le mot de passe s'affiche une fois. La clé d'hôte SSH
        de la forge est enregistrée pour le push, et la session retient
        l'URL web et le jeton : la préparation de la forge ne les redemande
        pas. Une étape échouée laisse la VM en place, avec son journal."""
        import subprocess
        import time

        from script.forgejo import forge_vm

        print(
            f"   {t('A QEMU VM receives .venv.erplibre (no Odoo) and Forgejo:')}"
            f" {forge_vm.DISTRO} {forge_vm.VERSION}, {forge_vm.VCPUS} vCPU,"
            f" {forge_vm.MEMOIRE_MO} MB, {forge_vm.DISQUE_GO} GB."
        )
        print(
            f"   {t('It takes from 15 to 40 minutes; creating the VM needs sudo.')}"
        )
        venv_cmd = getattr(self, "_QEMU_ERPLIBRE_VENV_CMD", "")
        if not venv_cmd or not hasattr(self, "_qemu_vm_ip"):
            print(f"⚠  {t('Creating a VM needs the TODO CLI.')}")
            return None
        if not forge_vm.cle_publique():
            print(
                f"⚠  {t('No SSH public key in ~/.ssh: the push needs one.')}"
            )
            return None
        nom = click.prompt(
            f"💬 {t('Name of the VM')}",
            default=f"forge-{time.strftime('%y%m%d-%H%M')}",
        ).strip()
        if not re.match(r"^[A-Za-z0-9][A-Za-z0-9-]{0,62}$", nom):
            print(f"⚠  {t('Invalid name: letters, digits and dashes.')}")
            return None
        admin = click.prompt(
            f"💬 {t('Forgejo administrator account')}", default="forge-admin"
        ).strip()
        proprietaires = {
            (p.get("proprietaire") or "").lower() for p in projets
        }
        if (
            not forgejo_client.nom_organisation_valide(admin)
            or admin.lower() in proprietaires
        ):
            print(
                f"⚠  {t('Invalid account, or the name of an owner of the repositories.')}"
            )
            return None
        if not click.confirm(f"💬 {t('Create the VM')} {nom}?", default=True):
            return None
        if subprocess.run(["sudo", "-v"]).returncode:
            print(f"⚠  {t('sudo was refused: no VM created.')}")
            return None
        dossier = os.path.join(os.path.expanduser("~/.erplibre/forge"), nom)
        os.makedirs(dossier, exist_ok=True)
        journal = dossier + ".log"
        print(f"   {t('Log:')} {journal}")
        ca = getattr(self, "_qemu_cache_ca_path", lambda: "")()
        cache = ["--cache-ca", ca] if ca else ["--cache-bypass"]

        def etape(n, ok, detail=""):
            marque = "✅" if ok else "❌"
            print(
                f"   {marque} {n}{' : ' + detail if detail else ''}",
                flush=True,
            )
            return ok

        forge = forge_vm.deployer(
            nom,
            admin,
            journal,
            dossier,
            lambda n: self._qemu_vm_ip(n, timeout=forge_vm.DELAI_SSH),
            venv_cmd,
            etape,
            cache=cache,
            preambule=getattr(self, "_qemu_cloud_init_wait", lambda: "true")(),
        )
        if forge is None:
            print(
                f"⚠  {t('The forge is not ready; the VM, if created, stays in place. Log:')}"
                f" {journal}"
            )
            return None
        if not forge_vm.enregistrer_cle_hote(forge["ip"]):
            print(
                f"   ⚠  {t('The SSH host key of the forge could not be read.')}"
            )
        self._git_forge_session = getattr(self, "_git_forge_session", {})
        self._git_forge_session[forge["base_ssh"]] = {
            "web": forge["web"],
            "jeton": forge["jeton"],
            "ip": forge["ip"],
        }
        cle = forgejo_client.cle_forge(forge["web"])
        print(f"   {t('Forge:')} {forge['web']} · {admin}")

        def ranger():
            return self._git_forge_ranger(
                self._git_forge_titre(cle), forge["jeton"]
            ) and self._git_forge_ranger(
                f"Forgejo admin {cle}", forge["mot_de_passe"], admin
            )

        if ranger() or (self._git_forge_creer_coffre() and ranger()):
            print(
                f"   ✓ {GROUPE_FORGE} › {self._git_forge_titre(cle)},"
                f" Forgejo admin {cle}"
            )
        else:
            print(
                f"   {t('Password of the administrator, shown once:')}"
                f" {forge['mot_de_passe']}"
            )
        return forge["base_ssh"]

    def _git_repo_proposer_surcouche(self, nom, projets):
        """Après un push vers le remote `nom`, propose, non par défaut,
        d'écrire la surcouche privée qui fait synchroniser les `projets`
        poussés depuis cette forge."""
        base = forge_manifest.base_du_remote(projets, nom)
        if (
            not base
            or not forge_manifest.NOM_VALIDE.match(nom)
            or not click.confirm(
                f"💬 {t('Write a private manifest so that repo sync fetches these repositories from')}"
                f" {nom}?",
                default=False,
            )
        ):
            return False
        return self._git_repo_ecrire_surcouche(nom, base, projets)

    def _git_repo_ecrire_surcouche(self, nom, base, projets):
        """Écrit la surcouche `forge_manifest` du remote `nom` : chaque
        remote du manifeste des `projets` vise `base`.

        Un remote se redirige en entier. Les projets de la fusion qu'il
        sert sans être parmi les `projets` — ceux des fragments communs à
        toutes les versions, par exemple — chercheraient sur la forge un
        dépôt absent : ils sont listés, et le choix porte alors sur
        « partial » (le défaut quand il reste un remote : seuls les remotes
        dont chaque projet est sur la forge), « all » ou « cancel »."""
        if not forge_manifest.NOM_VALIDE.match(nom or ""):
            print(
                f"⚠  {t('Invalid remote name: letters, digits, dot, dash and underscore.')}"
            )
            return False
        remotes = forge_manifest.remotes_rediriges(projets, base)
        if not remotes:
            print(f"⚠  {t('No manifest remote to redirect.')}")
            return False
        depart = os.getcwd()
        try:
            os.chdir(RACINE)
            manquants = forge_manifest.projets_non_couverts(
                set(remotes), {p["cle"] for p in projets}
            )
        finally:
            os.chdir(depart)
        for remote, fetch in remotes.items():
            print(f"   ▸ {remote} → {fetch}")
        if manquants:
            print(
                f"   ⚠  {len(manquants)}"
                f" {t('projects of the merged manifests use these remotes but are not on the forge; their sync would fail:')}"
            )
            for cle, remote in list(manquants.items())[:10]:
                print(f"      - {cle} ({remote})")
            if len(manquants) > 10:
                print(f"      … {len(manquants) - 10}")
            complets = {
                r: f
                for r, f in remotes.items()
                if r not in set(manquants.values())
            }
            choix = click.prompt(
                f"💬 {t('partial: redirect only the remotes whose projects are all on the forge')}"
                f" ({len(complets)}/{len(remotes)});"
                f" {t('all: redirect every remote; cancel')}",
                type=click.Choice(["partial", "all", "cancel"]),
                default="partial" if complets else "cancel",
            )
            if choix == "cancel" or (choix == "partial" and not complets):
                return False
            if choix == "partial":
                remotes = complets
        chemin = forge_manifest.ecrire(RACINE, nom, remotes)
        print(f"   ✓ {chemin}")
        print(
            f"   {t('It takes effect at the next reconfiguration; removing it brings back the original URLs.')}"
        )
        return True

    def _git_repo_projets_absolus(self):
        """Les projets de la version active, chemins absolus et
        « affiche » relatif ; [] hors d'un checkout configuré."""
        depart = os.getcwd()
        try:
            os.chdir(RACINE)
            projets = push_remote.projets_actifs()
        finally:
            os.chdir(depart)
        for p in projets:
            p["affiche"] = p["chemin"]
            p["chemin"] = os.path.join(RACINE, p["chemin"])
        return projets

    def _git_repo_choisir_remote_forge(self, projets):
        """Le nom d'un remote des clones qui n'est pas un remote du
        manifeste, choisi dans la liste, ou None."""
        manifeste = {p["remote"] for p in projets}
        remotes = {
            n: c
            for n, c in push_remote.remotes_des_clones(
                [p["chemin"] for p in projets]
            ).items()
            if n not in manifeste
        }
        if not remotes:
            print(
                f"⚠  {t('No forge remote in the clones: push the repositories to a remote first.')}"
            )
            return None
        noms = list(remotes)
        for i, n in enumerate(noms, 1):
            print(f"   {i}. {n} ({remotes[n]}/{len(projets)})")
        choix = click.prompt(f"💬 {t('Remote')}", default="1").strip()
        if not choix.isdigit() or not 1 <= int(choix) <= len(noms):
            print(t("Command not found !"))
            return None
        return noms[int(choix) - 1]

    def _git_repo_sur_la_forge(self, projets, nom, base):
        """Les `projets` dont le remote `nom` vise
        « <base>/<propriétaire>/<dépôt>.git » et dont la branche du
        manifeste existe sur la forge, lue par « git ls-remote », en
        parallèle : un clone qui porte le remote sans que son push ait
        abouti n'en est pas."""

        def present(p):
            if not p.get("proprietaire") or not p.get("branche"):
                return False
            attendu = push_remote.url_cible(base, p["proprietaire"], p["nom"])
            if repo_upgrade.url_du_remote(p["chemin"], nom) != attendu:
                return False
            out, _err, code = repo_upgrade.git(
                ["ls-remote", nom, f"refs/heads/{p['branche']}"],
                p["chemin"],
                120,
            )
            return code == 0 and bool(out.strip())

        return [
            p
            for p, ok in zip(
                projets,
                push_remote._en_parallele(
                    present, projets, push_remote.PARALLELE
                ),
            )
            if ok
        ]

    def _git_repo_surcouche(self):
        """Écrit ou retire une surcouche privée de manifeste
        (`forge_manifest`), puis propose de reconfigurer dans le mode
        actuel du checkout, non par défaut."""
        print(f"🧭 {t('Sync from a forge: private manifest overlay')}")
        existantes = forge_manifest.surcouches(RACINE)
        for n in existantes:
            remotes = forge_manifest.lire(RACINE, n)
            exemple = next(iter(remotes.values()), "")
            print(f"   ▸ {n}: {len(remotes)} remotes · {exemple}")
        print(f"   w. {t('Write the overlay of a forge remote')}")
        if existantes:
            print(f"   r. {t('Remove an overlay')}")
        choix = click.prompt(f"💬 {t('Choice')}", default="w").strip().lower()
        if choix == "w":
            projets = self._git_repo_projets_absolus()
            nom = self._git_repo_choisir_remote_forge(projets)
            if not nom:
                return False
            base = forge_manifest.base_du_remote(projets, nom)
            if not base:
                print(
                    f"⚠  {t('The forge URL cannot be deduced from this remote.')}"
                )
                return False
            portes = self._git_repo_sur_la_forge(projets, nom, base)
            print(
                f"   {len(portes)}/{len(projets)}"
                f" {t('clones have their manifest branch on the forge.')}"
            )
            if not self._git_repo_ecrire_surcouche(nom, base, portes):
                return False
        elif choix == "r" and existantes:
            nom = (
                existantes[0]
                if len(existantes) == 1
                else click.prompt(
                    f"💬 {t('Overlay')}",
                    type=click.Choice(existantes),
                )
            )
            if not click.confirm(
                f"💬 {t('Remove the overlay')} {nom}?", default=True
            ):
                return False
            forge_manifest.retirer(RACINE, nom)
            print(f"   ✓ {t('Overlay removed:')} {nom}")
        else:
            print(t("Command not found !"))
            return False
        etat = etat_manifeste_local()
        gele = bool(etat and etat[0])
        if click.confirm(
            f"💬 {t('Reconfigure now? Every clone takes the new URLs.')}",
            default=False,
        ):
            self._git_repo_reconfigurer(freeze=gele)
        return True

    def _git_repo_pull_requests(self):
        """Ouvre sur la forge une pull request par clone dont la branche
        extraite diffère de la branche du manifeste.

        Le remote choisi est un remote de forge des clones. Chaque branche
        se pousse sous son nom, en parallèle et sans force, puis la pull
        request va de cette branche vers la branche du manifeste dans le
        même dépôt de la forge. Un clone est écarté quand la branche du
        manifeste manque sur la forge, ou quand elle porte déjà le commit de
        la branche : il n'y a rien à fusionner. Une pull request ouverte
        pour la même paire est reprise, jamais doublée. Le titre est le
        sujet du dernier commit de la branche."""
        print(f"📬 {t('Open pull requests on a forge')}")
        projets = self._git_repo_projets_absolus()
        nom = self._git_repo_choisir_remote_forge(projets)
        if not nom:
            return 0
        candidats = []
        for p in projets:
            out, _err, code = repo_upgrade.git(
                ["rev-parse", "--abbrev-ref", "HEAD"], p["chemin"]
            )
            tete = out.strip()
            depot = manifest_repo.depot_de_l_url(
                repo_upgrade.url_du_remote(p["chemin"], nom)
            )
            if (
                code
                or not depot
                or not p["branche"]
                or tete in ("", "HEAD", p["branche"])
            ):
                continue
            candidats.append(dict(p, tete=tete, depot=depot[:2]))
        if not candidats:
            print(
                f"   {t('No clone is on a branch other than its manifest branch.')}"
            )
            return 0
        for c in candidats:
            print(f"   ▸ {c['affiche']}: {c['tete']} → {c['branche']}")
        base = forge_manifest.base_du_remote(projets, nom)
        if not base:
            print(
                f"⚠  {t('The forge URL cannot be deduced from this remote.')}"
            )
            return 0
        if not click.confirm(
            f"💬 {t('Push these branches to')} {nom}"
            f" {t('and open the pull requests?')}",
            default=False,
        ):
            print(f"↩️  {t('Cancelled: nothing was pushed.')}")
            return 0
        client = self._git_forge_client(base)
        if client is None:
            return len(candidats)
        cibles = [
            {
                "chemin": c["chemin"],
                "remote": nom,
                "specs": [f"refs/heads/{c['tete']}:refs/heads/{c['tete']}"],
            }
            for c in candidats
        ]
        resultats = push_remote.pousser_en_parallele(cibles)
        echecs = 0
        for c, r in zip(candidats, resultats):
            if r["code"]:
                echecs += 1
                print(f"   ⚠  {c['affiche']}: {r['erreur'][-300:]}")
                continue
            proprietaire, depot = c["depot"]
            try:
                sur_forge = client.commit_de_branche(
                    proprietaire, depot, c["branche"]
                )
                if sur_forge is None:
                    print(
                        f"   - {c['affiche']}: {c['branche']}"
                        f" {t('is absent from the forge: push the repositories first.')}"
                    )
                    continue
                if sur_forge == repo_upgrade.commit_de(c["chemin"], "HEAD"):
                    print(f"   - {c['affiche']}: {t('nothing to merge.')}")
                    continue
                sujet, _err, _code = repo_upgrade.git(
                    ["log", "-1", "--format=%s", "HEAD"], c["chemin"]
                )
                etat, pr = client.assurer_pull_request(
                    proprietaire,
                    depot,
                    c["tete"],
                    c["branche"],
                    sujet.strip() or c["tete"],
                )
            except forgejo_client.ErreurForgejo as exc:
                echecs += 1
                print(f"   ⚠  {c['affiche']}: {exc}")
                continue
            libelle = t("created") if etat == "creee" else t("already open")
            print(
                f"   ✅ {c['affiche']}: #{pr.get('number')} {libelle}"
                f" {pr.get('html_url', '')}".rstrip()
            )
        return echecs

    def _git_repo_suivre_pull_requests(self):
        """Suit les pull requests de la forge d'un remote des clones.

        Les dépôts lus sont les clones de la version active, plus ERPLibre
        quand il porte le même remote. Le rapport montre, par dépôt, les
        pull requests qui le concernent (`forge_pull_requests.lire`). Le
        travail fusionné qui manque aux branches locales se rapatrie sur
        demande, sous le verrou des passes, ERPLibre d'abord : un manifeste
        fusionné peut changer la branche d'un clone. Le gel des projets
        déjà gelés avance ensuite, après aperçu et confirmation. Aucun push,
        aucune écriture sur la forge, aucune branche supprimée.

        Rend le nombre d'échecs : dépôts illisibles et rapatriements
        refusés."""
        print(f"📥 {t('Follow the pull requests of a forge')}")
        projets = self._git_repo_projets_absolus()
        nom = self._git_repo_choisir_remote_forge(projets)
        if not nom:
            return 0
        # La base se déduit des clones seuls : `base_du_remote` exige un
        # propriétaire et un nom cohérents avec l'URL du remote.
        base = forge_manifest.base_du_remote(projets, nom)
        if not base:
            print(
                f"⚠  {t('The forge URL cannot be deduced from this remote.')}"
            )
            return 0
        racine = push_remote.projet_racine(RACINE)
        if racine is not None and repo_upgrade.url_du_remote(RACINE, nom):
            racine["affiche"] = f"ERPLibre ({racine['branche']})"
            racine["racine"] = True
            projets = [racine] + projets
        client = self._git_forge_client(base)
        if client is None:
            return 0
        lus = self._git_repo_lire_pull_requests(client, projets, nom)
        erreurs = sum(bool(err) for _p, _prs, err in lus)
        if not self._git_repo_rapport_pull_requests(lus, nom):
            return erreurs
        return erreurs + self._git_repo_rapatrier_fusionnees(lus, nom)

    def _git_repo_lire_pull_requests(self, client, projets, nom):
        """[(projet, pull requests, erreur)] dans l'ordre de `projets`, lus
        en parallèle. Une pull request fusionnée porte en plus « local » :
        son commit est déjà dans la branche locale de sa base. Un dépôt
        illisible a une erreur et aucune pull request ; les autres
        continuent. Un clone sans le remote `nom` n'a jamais été poussé
        vers cette forge, et une URL qui ne nomme pas de dépôt n'en désigne
        aucun : l'un et l'autre sont omis, sans erreur, comme le fait
        l'ouverture des pull requests."""

        def lire(p):
            depot = manifest_repo.depot_de_l_url(
                repo_upgrade.url_du_remote(p["chemin"], nom)
            )
            if not depot:
                return None
            try:
                prs = forge_pull_requests.lire(
                    client,
                    depot[0],
                    depot[1],
                    forge_pull_requests.branches_locales(p["chemin"]),
                    p["branche"],
                )
            except forgejo_client.ErreurForgejo as exc:
                if exc.statut == 404:
                    return p, [], t("absent from the forge")
                return p, [], forge_pull_requests.affichable(exc)
            for pr in prs:
                fusionnee = pr["etat"] == "fusionnee"
                pr["local"] = fusionnee and forge_pull_requests.deja_local(
                    p["chemin"], pr
                )
            return p, prs, ""

        lus = push_remote._en_parallele(lire, projets, push_remote.PARALLELE)
        return [lu for lu in lus if lu is not None]

    def _git_repo_rapport_pull_requests(self, lus, nom):
        """Imprime le rapport de `lus` : un bloc par dépôt qui a des pull
        requests, les dépôts en erreur, puis le total par état. Rend le
        nombre de pull requests."""
        compte = dict.fromkeys(ICONES_ETAT, 0)
        erreurs = 0
        for p, prs, err in lus:
            if err:
                erreurs += 1
                print(f"   ⚠  {p['affiche']}: {err}")
                continue
            if not prs:
                continue
            print(f"── {p['affiche']} ({nom} → {p['branche'] or '?'})")
            for pr in prs:
                compte[pr["etat"]] += 1
                print(f"  {ligne_pull_request(pr)}")
        total = sum(compte.values())
        if total:
            print(
                f"   {total} {t('pull requests')}: "
                + " · ".join(
                    f"{ICONES_ETAT[e]} {n}" for e, n in compte.items()
                )
            )
        else:
            print(f"   {t('No pull request on the forge for these clones.')}")
        if erreurs:
            print(f"   ⚠  {erreurs} {t('repositories in error')}")
        return total

    def _git_repo_rapatrier_fusionnees(self, lus, nom):
        """Propose de rapatrier la base des pull requests fusionnées dont
        le commit manque à la branche locale, une ligne par (dépôt, base).
        Le rapatriement et le gel tournent sous le verrou des passes du
        checkout. Rend le nombre de rapatriements en échec."""
        paires = {}
        for p, prs, _err in lus:
            for pr in prs:
                if pr["etat"] != "fusionnee" or pr.get("local"):
                    continue
                if not pr["base"]:
                    continue
                cle = (p["chemin"], pr["base"])
                paires.setdefault(cle, {"p": p, "base": pr["base"], "prs": []})
                paires[cle]["prs"].append(pr["numero"])
        if not paires:
            return 0
        candidats = list(paires.values())
        print()
        for i, c in enumerate(candidats, 1):
            numeros = ", ".join(f"#{n}" for n in c["prs"])
            print(
                f"   {i}. {c['p']['affiche']}:"
                f" {forge_pull_requests.affichable(c['base'])} ← {numeros}"
            )
        saisie = click.prompt(
            f"💬 {t('Bring back the merged work? Numbers, all, or Enter for none')}",
            default="",
            show_default=False,
        ).strip()
        if not saisie:
            print(f"↩️  {t('Cancelled: nothing was fetched.')}")
            return 0
        choisis = choix_numeros(saisie, candidats)
        if choisis is None:
            print(t("Command not found !"))
            return 0
        from script.git import repo_pull

        try:
            with repo_pull.verrou(RACINE):
                return self._git_repo_rapatrier_choisis(choisis, nom)
        except repo_pull.Occupe:
            print(f"⚠  {t('Another pull is running on this checkout.')}")
            return 1

    def _git_repo_rapatrier_choisis(self, choisis, nom):
        """Rapatrie chaque (dépôt, base) de `choisis` depuis le remote
        `nom` : ERPLibre seul d'abord, puis les clones en parallèle, relus
        quand ERPLibre a avancé. Avertit quand le commit rapatrié manque à
        la branche de suivi du remote du manifeste : la synchronisation
        suivante ramènerait la pointe de l'amont, sauf sous une surcouche
        de ce remote. Puis avance le gel. Rend le nombre d'échecs."""
        racines = [c for c in choisis if c["p"].get("racine")]
        clones = [c for c in choisis if not c["p"].get("racine")]
        resultats = [
            (
                c,
                forge_pull_requests.rapatrier(
                    c["p"]["chemin"], nom, c["base"]
                ),
            )
            for c in racines
        ]
        if any(r["etat"] in ("creee", "avance") for _c, r in resultats):
            relus = {p["chemin"]: p for p in self._git_repo_projets_absolus()}
            clones = [
                dict(c, p=relus.get(c["p"]["chemin"], c["p"])) for c in clones
            ]
        resultats += list(
            zip(
                clones,
                push_remote._en_parallele(
                    lambda c: forge_pull_requests.rapatrier(
                        c["p"]["chemin"], nom, c["base"]
                    ),
                    clones,
                    push_remote.PARALLELE,
                ),
            )
        )
        surcouche = nom in forge_manifest.surcouches(RACINE)
        echecs = 0
        rapatries = {}
        for c, r in resultats:
            p, etat = c["p"], r["etat"]
            base = forge_pull_requests.affichable(c["base"])
            libelle = t(RAPATRIEMENTS[etat])
            if etat in ("creee", "avance"):
                print(
                    f"   ✅ {p['affiche']}: {base} → {r['sha'][:10]} ({libelle})"
                )
            elif etat == "a_jour":
                print(f"   =  {p['affiche']}: {base} {libelle}")
            else:
                detail = r["detail"]
                if detail == forge_pull_requests.NOM_INVALIDE:
                    detail = t(detail)
                detail = forge_pull_requests.affichable(detail)
                print(
                    f"   ⚠  {p['affiche']}: {base} {libelle} {detail}".rstrip()
                )
                echecs += etat != "en_avance"
            if etat not in forge_pull_requests.ETATS_GELABLES:
                continue
            if not p.get("racine"):
                # Deux bases pour un clone : celle du manifeste l'emporte.
                if p["chemin"] not in rapatries or c["base"] == p["branche"]:
                    rapatries[p["chemin"]] = (c["base"], r)
                if surcouche:
                    continue
            _out, _err, code = repo_upgrade.git(
                [
                    "merge-base",
                    "--is-ancestor",
                    r["sha"],
                    f"refs/remotes/{p['remote']}/{c['base']}",
                ],
                p["chemin"],
            )
            if code:
                message = (
                    t("push them to origin")
                    if p.get("racine")
                    else t(
                        "the merged commits are on the forge only: a sync brings back the upstream tip; push them (entry 16, mode all) or use an overlay (entry 18)"
                    )
                )
                print(f"      ⚠  {message}")
        projets = list({c["p"]["chemin"]: c["p"] for c in clones}.values())
        self._git_repo_avancer_gel(projets, rapatries)
        return echecs

    def _git_repo_avancer_gel(self, projets, rapatries):
        """Avance le gel des `projets` déjà gelés vers le commit rapatrié
        (`forge_pull_requests.candidats_gel`), quand le checkout a un gel.

        Seul un commit publié à l'URL du manifeste s'écrit : `manifest/`
        est versionné, et un gel que personne ne peut rapatrier casserait
        l'installation suivante. L'aperçu montre chaque fichier et chaque
        clé, puis l'écriture attend une confirmation, non par défaut."""
        sources = gel_des_sources()
        if not sources or not sources[0]:
            return False
        if not any(
            r["etat"] in forge_pull_requests.ETATS_GELABLES
            for _base, r in rapatries.values()
        ):
            return False
        depart = os.getcwd()
        try:
            os.chdir(RACINE)
            portee = git_freeze_manifest.freeze_sources()
            lus = list(
                dict.fromkeys(git_freeze_manifest.default_sources() + portee)
            )
            definitions = git_freeze_manifest.read_sources(portee)
            fetch = git_freeze_manifest.read_remotes(
                git_freeze_manifest.sans_surcouches(lus)
            )
        except OSError as exc:
            print(f"⚠  {exc}")
            return False
        finally:
            os.chdir(depart)
        depots, ignores = forge_pull_requests.candidats_gel(
            projets, rapatries, definitions, fetch
        )
        print(f"🧊 {t('Freeze the versions')}")
        for p, motif in ignores:
            print(f"   - {p['affiche']}: {t(motif)}")
        if not depots:
            print(f"   {t('Nothing changed.')}")
            return False
        publications = push_remote._en_parallele(
            lambda d: freeze_resolution.publication(RACINE, d),
            depots,
            push_remote.PARALLELE,
        )
        publies = []
        for d, (publie, detail) in zip(depots, publications):
            if publie:
                publies.append(d)
                print(f"   ✅ {d['path']} — {t('pushed on')} {detail}")
            elif publie is False:
                print(
                    f"   ⚠  {d['path']} — {t('not pushed, push it first:')}"
                    f" {detail}"
                )
            else:
                print(f"   ❌ {d['path']} — {detail}")
        if not publies:
            print(f"   {t('Nothing changed.')}")
            return False
        changes, _sans_base = freeze_resolution.mettre_a_jour_gel(
            RACINE, publies, ecrire=False
        )
        if not changes:
            print(f"   {t('Nothing changed.')}")
            return False
        for fichier, cles in changes.items():
            print(f"   {fichier}: {', '.join(cles)}")
        if not click.confirm(
            t("Write these changes to the manifest files?"), default=False
        ):
            print(f"↩️  {t('Cancelled: nothing was written.')}")
            return False
        changes, sans_base = freeze_resolution.mettre_a_jour_gel(
            RACINE, publies, ecrire=True
        )
        print(f"✅ {t('Freeze updated in:')} {', '.join(changes)}")
        if sans_base:
            print(
                f"   {t('Their fork-upstream-freeze-revision is removed: make repo_freeze UPSTREAM=1 computes it again.')}"
            )
        print(f"   {t('Commit these manifests to share the new freeze.')}")
        etat = etat_manifeste_local()
        if etat and etat[0]:
            print(f"   {t('Apply with: Switch to production.')}")
        return True

    def _git_forge_cible_ssh(self, base):
        """(cible, options) de l'hôte de la forge de `base`, pour ssh.

        Une forge créée dans cette session (une session qui porte « ip »)
        donne « <UTILISATEUR>@<ip> » et les options de la VM neuve, sans
        question. Sinon la cible se demande, par défaut
        « erplibre@<hôte de la forge> », avec les options d'un hôte connu
        (`forge_vm.OPTIONS_SSH_CONNU`). Une cible qui ne serait pas
        « utilisateur@hôte » rend (None, None)."""
        from script.forgejo import forge_vm

        session = getattr(self, "_git_forge_session", {}).get(base) or {}
        if session.get("ip"):
            return (
                f"{forge_vm.UTILISATEUR}@{session['ip']}",
                forge_vm.OPTIONS_SSH,
            )
        hote = forgejo_client.hote_de(session.get("web") or base) or ""
        cible = click.prompt(
            f"💬 {t('SSH access to the forge host')}",
            default=f"erplibre@{hote}",
        ).strip()
        if not re.match(r"^[A-Za-z0-9_][-.\w]*@[-.\w:\[\]]+$", cible):
            print(f"⚠  {t('Not an SSH access: user@host expected.')}")
            return None, None
        return cible, forge_vm.OPTIONS_SSH_CONNU

    def _git_repo_branches_racine(self, racine, exclues=()):
        """Parmi develop et master, celles qui existent en
        refs/remotes/<remote>/<branche> dans le checkout de `racine` (un
        projet de `push_remote.projet_racine`), lu localement, sans réseau,
        et qui ne sont pas dans `exclues`.

        La branche extraite n'est pas proposée : c'est la tête de la pull
        request qu'ouvre l'entrée 17, et l'avance du minuteur sur une tête
        de pull request lance la CI (« synchronize »)."""
        res = []
        for b in ("develop", "master"):
            if b in exclues:
                continue
            _out, _err, code = repo_upgrade.git(
                [
                    "rev-parse",
                    "--verify",
                    "-q",
                    f"refs/remotes/{racine['remote']}/{b}",
                ],
                racine["chemin"],
            )
            if code == 0:
                res.append(b)
        return res

    def _git_repo_afficher_synchro(self, etat):
        """Affiche l'état du minuteur lu par `forge_vm.lire_etat_synchro` :
        les paires suivies, un avertissement sans jeton ou pour une
        configuration refusée, puis le résumé de la dernière passe."""
        config = etat.get("config") or {}
        print(
            f"   {len(config.get('paires') or [])} {t('pairs followed')}"
            f" · {etat.get('compte') or '?'}"
        )
        if not etat.get("jeton"):
            print(
                f"   ⚠  {t('No token on the forge host: reinstall the timer.')}"
            )
        for erreur in etat.get("erreurs_config") or []:
            print(f"   ⚠  {t('Invalid configuration:')} {erreur}")
        lignes = forge_mirror.resume_etat(
            etat.get("etat"),
            libelle=lambda e: (
                t(ETATS_SYNCHRO[e]) if e in ETATS_SYNCHRO else str(e)
            ),
            depuis=t("since"),
        )
        if not lignes:
            print(f"   {t('no pass yet')}")
        for ligne in lignes:
            print(f"   {ligne}")

    def _git_repo_passe_synchro(self, cible, options, journal):
        """Lance une passe du minuteur et en affiche le résultat. Rend 1
        quand la passe a échoué, 0 sinon. Une passe qui ne laisse pas de
        nouvel état (une condition de l'unité manque) est signalée."""
        from script.forgejo import forge_vm

        avant = forge_vm.lire_etat_synchro(cible, options) or {}
        code = forge_vm.lancer_passe(cible, journal, options)
        apres = forge_vm.lire_etat_synchro(cible, options)
        if apres is None:
            print(
                f"⚠  {t('No state: the timer is not installed, or sudo without a password was refused.')}"
            )
            return 1
        debut_avant = (avant.get("etat") or {}).get("debut")
        if (apres.get("etat") or {}).get("debut") == debut_avant:
            print(
                f"⚠  {t('No pass ran: no configuration or no token on the forge.')}"
            )
        self._git_repo_afficher_synchro(apres)
        if code != 0:
            print(f"   {t('Log:')} {journal}")
        return 1 if code != 0 else 0

    def _git_repo_miroirs(self):
        """Fait suivre leur origine aux dépôts de la forge d'un remote.

        Chaque dépôt de travail « <propriétaire>/<dépôt> » reçoit un
        miroir natif « <propriétaire>-mirror/<dépôt> », en lecture seule,
        que la forge rafraîchit depuis le remote du manifeste
        (`forge_mirror`). Un minuteur sur l'hôte de la forge
        (`forge_sync`) avance ensuite les branches de travail jusqu'au
        miroir, en fast-forward seulement ; une divergence est notée et la
        branche laissée telle quelle. ERPLibre se suit aussi, sur les
        branches choisies, quand le remote porte son dépôt.

        Rien n'est créé avant confirmation, et tout est vérifié avant le
        premier appel à l'API : noms, collisions, configuration. Seule une
        origine lisible anonymement se suit : aucun jeton GitHub n'entre
        dans la forge. Une branche d'ERPLibre qui porte une pull request
        ouverte ne se suit pas. « s » montre l'état de la dernière passe,
        « n » en lance une. Rend le nombre d'échecs."""
        from script.forgejo import forge_sync, forge_vm

        print(f"🪞 {t('Follow the origins: mirrors on the forge')}")
        projets = self._git_repo_projets_absolus()
        nom = self._git_repo_choisir_remote_forge(projets)
        if not nom:
            return 0
        base = forge_manifest.base_du_remote(projets, nom)
        if not base:
            print(
                f"⚠  {t('The forge URL cannot be deduced from this remote.')}"
            )
            return 0
        dossier = os.path.expanduser("~/.erplibre/forge")
        os.makedirs(dossier, exist_ok=True)
        journal = os.path.join(
            dossier, f"synchro-{forgejo_client.hote_de(base) or 'forge'}.log"
        )
        choix = (
            click.prompt(
                f"💬 {t('c: create or extend the mirrors; s: state of the last pass; n: run a pass now')}",
                default="c",
            )
            .strip()
            .lower()
        )
        if choix in ("s", "n"):
            cible, options = self._git_forge_cible_ssh(base)
            if not cible:
                return 0
            if choix == "n":
                return self._git_repo_passe_synchro(cible, options, journal)
            etat = forge_vm.lire_etat_synchro(cible, options)
            if etat is None:
                print(
                    f"⚠  {t('No state: the timer is not installed, or sudo without a password was refused.')}"
                )
                return 0
            self._git_repo_afficher_synchro(etat)
            return 0
        if choix != "c":
            print(t("Command not found !"))
            return 0

        # 1. Le plan : seules l'identité et les pull requests ouvertes
        # d'ERPLibre se lisent sur la forge, rien ne s'y écrit.
        portes = self._git_repo_sur_la_forge(projets, nom, base)
        racine = push_remote.projet_racine(RACINE)
        a_suivre = list(portes)
        client = self._git_forge_client(base)
        if client is None:
            return 0
        try:
            compte = client.identite()
        except forgejo_client.ErreurForgejo as exc:
            print(f"❌ Forgejo : {exc}")
            return 0
        if racine and repo_upgrade.url_du_remote(
            RACINE, nom
        ) == push_remote.url_cible(
            base, racine["proprietaire"], racine["nom"]
        ):
            if click.confirm(
                f"💬 {t('Also follow the ERPLibre repository?')}",
                default=True,
            ):
                # Une branche qui porte une pull request ouverte ne se suit
                # pas : chaque avance du minuteur y lancerait la CI.
                depot_racine = racine["nom"]
                if depot_racine.endswith(".git"):
                    depot_racine = depot_racine[: -len(".git")]
                try:
                    tetes = {
                        (pr.get("head") or {}).get("ref")
                        for pr in client.pull_requests(
                            racine["proprietaire"], depot_racine, etat="open"
                        )
                    }
                except forgejo_client.ErreurForgejo as exc:
                    # Un dépôt absent de la forge ne porte aucune pull
                    # request : rien n'est exclu, sa paire se lira
                    # « depot_absent » tant qu'il n'est pas poussé.
                    if exc.statut != 404:
                        print(f"❌ Forgejo : {exc}")
                        return 0
                    tetes = set()
                saisie = click.prompt(
                    f"💬 {t('Branches of ERPLibre to follow (comma-separated)')}",
                    default=",".join(
                        self._git_repo_branches_racine(racine, tetes)
                    ),
                    show_default=True,
                )
                branches = []
                for b in dict.fromkeys(
                    b.strip() for b in saisie.split(",") if b.strip()
                ):
                    if b in tetes:
                        print(
                            f"   - ERPLibre {b}: {t('heads an open pull request: not followed')}"
                        )
                    else:
                        branches.append(b)
                if branches:
                    racine["affiche"] = "ERPLibre"
                    racine["origine"] = forge_mirror.url_origine(
                        repo_upgrade.url_du_remote(RACINE, racine["remote"])
                    )
                    racine["branches"] = [
                        {"travail": b, "miroir": b, "creer": True}
                        for b in branches
                    ]
                    if racine["origine"]:
                        a_suivre.append(racine)
                    else:
                        print(f"   - ERPLibre: {t('no https origin')}")
        depart = os.getcwd()
        try:
            os.chdir(RACINE)
            remotes = forge_mirror.remotes_d_origine()
        finally:
            os.chdir(depart)
        interdits = (
            forge_mirror.proprietaires_connus(remotes)
            | {p["proprietaire"] for p in projets if p.get("proprietaire")}
            | ({racine["proprietaire"]} if racine else set())
            | ({compte} if compte else set())
        )
        paires, ecartes = forge_mirror.plan_miroirs(
            a_suivre, remotes, interdits
        )
        for p, motif in ecartes:
            print(f"   - {p.get('affiche') or p.get('nom')}: {t(motif)}")
        erreurs = forge_sync.valider(forge_mirror.config_synchro(paires))
        if erreurs:
            for erreur in erreurs:
                print(f"   ✗ {erreur}")
            return 0
        print(
            f"   {t('Checking that each origin can be read anonymously…')}",
            flush=True,
        )
        origines = list(dict.fromkeys(p["origine"] for p in paires))
        lisibles = dict(
            zip(
                origines,
                push_remote._en_parallele(
                    forge_mirror.origine_publique,
                    origines,
                    push_remote.PARALLELE,
                ),
            )
        )
        for p in paires:
            if not lisibles[p["origine"]]:
                print(
                    f"   - {p['projet'].get('affiche') or p['depot']}:"
                    f" {t('origin not readable anonymously (private?): left out')}"
                )
        paires = [p for p in paires if lisibles[p["origine"]]]
        if not paires:
            print(f"⚠  {t('No repository to mirror.')}")
            return 0
        exemple = paires[0]
        print(
            f"   {len(paires)} {t('mirrors to create or follow')},"
            f" {len(ecartes)} {t('set aside')}"
        )
        print(
            f"   ▸ {exemple['depot']} ← {exemple['origine']}"
            f" ({exemple['miroir']})"
        )
        intervalle = click.prompt(
            f"💬 {t('Mirror refresh interval (Go duration, 10m at least)')}",
            default=forge_mirror.INTERVALLE_DEFAUT,
        ).strip()
        if not forge_mirror.intervalle_valide(intervalle):
            print(
                f"⚠  {t('Invalid interval: hours and minutes, 10m at least.')}"
            )
            return 0
        cible, options = self._git_forge_cible_ssh(base)
        if not cible:
            return 0
        if not click.confirm(
            f"💬 {t('Create the mirrors and install the fast-forward timer on')}"
            f" {cible}? ({len(paires)})",
            default=False,
        ):
            print(f"   {t('Cancelled: nothing was created.')}")
            return 0

        # 2. Les organisations des miroirs.
        echecs = 0
        orgs = {p["miroir"].split("/")[0] for p in paires}
        natures = forgejo_client.plan_proprietaires(
            client, forgejo_client.organisations_requises(orgs)
        )
        refusees = set()
        for org, nature in natures.items():
            if nature in ("utilisateur", "compte"):
                print(
                    f"   ⚠  {org}: {t('mirror organisation is a user account: left out')}"
                )
                refusees.add(org.lower())
            elif nature.startswith("erreur"):
                print(f"   ✗ {org}: {nature}")
                refusees.add(org.lower())
                echecs += 1
        absentes = [o for o, n in natures.items() if n == "absent"]
        for org, (etat, message) in forgejo_client.assurer_organisations(
            client, absentes
        ).items():
            if etat == "erreur":
                print(f"   ✗ {org}: {message}")
                refusees.add(org.lower())
                echecs += 1
            else:
                print(
                    f"   ✓ {org}:"
                    f" {t('created') if etat == 'creee' else t('existing')}"
                )
        paires = [
            p
            for p in paires
            if p["miroir"].split("/")[0].lower() not in refusees
        ]

        # 3. Les miroirs, deux à la fois : chaque création clone toute
        # l'histoire de l'origine.
        def assurer(p):
            org, depot = p["miroir"].split("/")
            try:
                etat, res = client.assurer_miroir(
                    org, depot, p["origine"], intervalle
                )
            except forgejo_client.ErreurForgejo as exc:
                etat, res = "erreur", str(exc)
            print(
                f"   {'✗' if etat == 'erreur' else '▸'} {p['miroir']}:"
                f" {t(LIBELLES_MIROIR[etat])}",
                flush=True,
            )
            return etat, res

        # Un dépôt déjà présent là où le miroir est attendu, qui n'est pas
        # le miroir de l'origine du manifeste, ne se suit pas : le minuteur
        # pousserait son contenu dans le dépôt de travail. Une paire qu'une
        # passe précédente a écrite pour ce dépôt se retire de l'hôte.
        retenues, a_retirer, decompte_etats = [], [], {}
        for p, (etat, res) in zip(
            paires, push_remote._en_parallele(assurer, paires, 2)
        ):
            if etat == "existant":
                etat = forge_mirror.qualifier(res, p["origine"])
                org, depot = p["miroir"].split("/")
                if etat == "existant":
                    try:
                        client.synchroniser_miroir(org, depot)
                    except forgejo_client.ErreurForgejo as exc:
                        print(f"   ⚠  {p['miroir']}: {exc}")
                elif etat == "autre_origine":
                    print(
                        f"   ⚠  {p['miroir']}: {t('mirror of another origin: not followed')}"
                    )
                elif etat == "pas_miroir":
                    print(
                        f"   ✗ {p['miroir']}: {t('not a mirror: left as is')}"
                    )
            elif etat == "erreur":
                print(f"   ✗ {p['miroir']}: {res}")
            decompte_etats[etat] = decompte_etats.get(etat, 0) + 1
            if etat in ("erreur", "pas_miroir"):
                echecs += 1
            if etat in ("autre_origine", "pas_miroir"):
                a_retirer.append(p["depot"])
            elif etat != "erreur":
                retenues.append(p)
        print(
            "   "
            + ", ".join(
                f"{n} {t(LIBELLES_MIROIR[e])}"
                for e, n in sorted(decompte_etats.items())
            )
        )
        if a_retirer and not forge_vm.retirer_paires_synchro(
            cible, a_retirer, journal, options
        ):
            print(
                f"❌ {t('The configuration could not be written. Log:')} {journal}"
            )
            echecs += 1
        if not retenues:
            return echecs

        # 4. Le minuteur sur l'hôte, puis sa configuration.
        if not forge_vm.installer_synchro(cible, journal, compte, options):
            print(
                f"❌ {t('The timer could not be installed. Log:')} {journal}"
            )
            return echecs + 1
        if not forge_vm.ecrire_config_synchro(
            cible, forge_mirror.config_synchro(retenues), journal, options
        ):
            print(
                f"❌ {t('The configuration could not be written. Log:')} {journal}"
            )
            return echecs + 1
        print(f"   ✓ {len(retenues)} {t('pairs followed')} · {cible}")
        if click.confirm(
            f"💬 {t('Run a pass now? Mirrors still being created are reported as absent.')}",
            default=True,
        ):
            echecs += self._git_repo_passe_synchro(cible, options, journal)
        return echecs

    def _git_repo_comparer(self):
        """Compare deux gels, puis ouvre l'historique d'un projet sur demande.

        Le rapport se calcule une fois, en mémoire : la boucle qui suit en
        relit les lignes sans refaire la comparaison. Rend 0, ou 2 sur une
        révision inconnue.
        """
        print(f"🔀 {t('Compare two freezes')}")
        cas = self._git_repo_choisir_comparaison()
        if not cas:
            return 0
        try:
            rapport = git_freeze_diff.build(RACINE, *cas)
        except ValueError as exc:
            print(f"⚠  {exc}")
            return 2
        print("\n".join(git_freeze_diff.render_summary(rapport, menu=True)))
        self._git_repo_parcourir_comparaison(rapport)
        return 0

    def _git_repo_choisir_comparaison(self):
        """(gauche, droite) que l'on compare, ou None pour revenir."""
        print(f"  [1] 💻 {t('Committed freeze → clones (real state)')}")
        print(f"  [2] 📝 {t('Written freeze (manifest/) → clones')}")
        print(
            f"  [3] 🚧 {t('Committed freeze → written freeze, not committed')}"
        )
        print(f"  [4] ⏪ {t('Previous freeze → last freeze')}")
        print(f"  [5] 🎯 {t('Two revisions of your choice')}")
        print(
            "  [6] 🧮"
            f" {t('Matrix: the ERPLibre branches and tags side by side')}"
        )
        print(f"  {retour(t('Back'))}")
        choix = input("  : ").strip()
        cas = {
            "1": ("HEAD", git_freeze_diff.CLONES),
            "2": (git_freeze_diff.WORKTREE, git_freeze_diff.CLONES),
            "3": ("HEAD", git_freeze_diff.WORKTREE),
        }
        if choix in cas:
            return cas[choix]
        if choix == "4":
            paire = git_freeze_diff.previous_freeze(RACINE)
            if not paire:
                print(f"⚠  {t('Fewer than two commits changed a freeze.')}")
            return paire
        if choix == "5":
            return self._git_repo_saisir_revisions()
        if choix == "6":
            self._git_repo_matrice()
            return None
        if choix not in ("", "0"):
            print(t("Command not found !"))
        return None

    def _git_repo_saisir_revisions(self):
        """Demande les deux côtés : un numéro des listes affichées (commits
        de gel, puis branches et tags d'ERPLibre qui portent un gel), une
        révision d'ERPLibre, « worktree » ou « clones »."""
        gels = git_freeze_diff.freeze_commits(RACINE)
        refs, _ = git_freeze_diff.frozen_refs(RACINE)
        choix = [sha for sha, _, _ in gels] + [c for _, c in refs]
        if gels:
            print(f"  {t('Commits that changed a freeze:')}")
            for i, (sha, date, sujet) in enumerate(gels, 1):
                print(f"   {i:>2}. {sha[:8]}  {date}  {sujet}")
        else:
            print(f"  {t('No commit changed a freeze yet.')}")
        if refs:
            print(f"  {t('ERPLibre branches and tags holding a freeze:')}")
            for i, (noms, commit) in enumerate(refs, len(gels) + 1):
                print(f"   {i:>2}. {commit[:8]}  {noms}")

        def lire(question, defaut):
            valeur = click.prompt(question, default=defaut).strip()
            if valeur.isdecimal() and 1 <= int(valeur) <= len(choix):
                return choix[int(valeur) - 1]
            return valeur

        aide = t("number, revision, worktree or clones")
        gauche = lire(f"  {t('From')} ({aide})", "HEAD")
        droite = lire(f"  {t('To')} ({aide})", git_freeze_diff.CLONES)
        return gauche, droite

    def _git_repo_matrice(self):
        """Affiche la matrice des gels : les branches et tags d'ERPLibre qui
        en portent un, le disque et les clones, ou les côtés saisis."""
        defaut = ",".join(git_freeze_diff.default_matrix_sides(RACINE))
        cotes = click.prompt(
            f"  {t('Sides, separated by commas')}", default=defaut
        )
        try:
            table = git_freeze_diff.matrix(
                RACINE, [c.strip() for c in cotes.split(",") if c.strip()]
            )
        except ValueError as exc:
            print(f"⚠  {exc}")
            return 2
        print("\n".join(git_freeze_diff.render_matrix(table)))
        return 0

    def _git_repo_geste_projet(self, rapport, prefixe, choix, groupe):
        """Un geste sur les projets que `choix` désigne (un numéro, ou
        « all ») : « s » le diffstat complet, « b » le graphe avec les
        branches, rien l'historique dans tig.

        Un tig quitté autrement que par « q » (Ctrl-C, une erreur) arrête la
        suite : « a » se laisse interrompre.
        """
        lignes = git_freeze_diff.select_rows(rapport, choix)
        if not lignes:
            print(f"⚠  {t('No changed project with both commits here.')}")
            return
        if prefixe == "s":
            details = git_freeze_diff.render_details(
                rapport,
                stat_count=0,
                group_by=groupe,
                numeros={int(choix)},
                menu=True,
            )
            print("\n".join(details))
            return
        ouvrir = (
            git_freeze_diff.open_graph
            if prefixe == "b"
            else git_freeze_diff.open_history
        )
        for ligne in lignes:
            if ouvrir(RACINE, ligne):
                break

    def _git_repo_parcourir_comparaison(self, rapport):
        """Les gestes offerts sur un rapport de comparaison.

        tig hérite du terminal : il ne passe pas par `exec_command_live`,
        dont le tube sur la sortie le priverait de son écran.
        """
        groupes = [g for g in git_freeze_diff.GROUPS if g != "none"]
        groupe = groupes[0]
        while True:
            if not git_freeze_diff.changed_rows(rapport):
                return
            print()
            print(f"  N   🐯 {t('tig on project N of the table')}")
            print(f"  a   🐯 {t('tig on each project, one after another')}")
            print("  l   📜 git log --oneline")
            print(f"  d   📊 {t('Diffstat and groups')} ({groupe})")
            print(f"  s N 📊 {t('Full diffstat of project N')}")
            print(f"  b N 🌿 {t('Graph of project N with its branches')}")
            print(f"  g   🗂  {t('Next grouping: file type, module, folder')}")
            print(
                f"  f   📥 {t('Refresh: branches, tags and missing commits')}"
            )
            print(f"  w   🌳 {t('Open an old commit in a git worktree')}")
            print(f"  {bleu_poudre('⏎   ' + t('Back'))}")
            choix = input("  : ").strip().lower()
            if choix in ("", "0"):
                return
            prefixe = choix[:1] if choix[:1] in ("s", "b") else ""
            numero = choix[len(prefixe) :].strip()
            if numero.isdecimal() or choix == "a":
                self._git_repo_geste_projet(
                    rapport, prefixe, "all" if choix == "a" else numero, groupe
                )
            elif choix == "l":
                print("\n".join(git_freeze_diff.render_logs(rapport)))
            elif choix == "d":
                print(
                    "\n".join(
                        git_freeze_diff.render_details(
                            rapport, group_by=groupe, menu=True
                        )
                    )
                )
            elif choix == "g":
                groupe = groupes[(groupes.index(groupe) + 1) % len(groupes)]
                print(f"  {t('Grouping:')} {groupe}")
            elif choix == "f":
                print(f"  📥 {t('Refreshing the clones, in parallel.')}")
                restes = git_freeze_diff.fetch_missing(RACINE, rapport["rows"])
                for chemin, shas in sorted(restes.items()):
                    print(
                        f"⚠  {t('Still missing:')} {chemin} {', '.join(shas)}"
                    )
                print(
                    "\n".join(
                        git_freeze_diff.render_summary(rapport, menu=True)
                    )
                )
            elif choix == "w":
                print("\n".join(git_freeze_diff.render_tip(rapport)))
            else:
                print(t("Command not found !"))
