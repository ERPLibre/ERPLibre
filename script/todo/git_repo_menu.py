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

Le GEL écrit le commit de chaque clone à côté de sa branche, dans les
fichiers de `manifest/`. Suivre les branches ou les commits gelés est un
argument de la reconfiguration, jamais un état enregistré : le mode que
l'en-tête affiche se lit dans le manifeste local que git-repo utilise.

Module à part plutôt que méthodes de `TODO` : le fichier principal passe les
cinq mille lignes, et chaque sujet y a désormais le sien.
"""

import datetime
import os
import sys

import click

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.append(new_path)

from script.git import (  # noqa: E402
    git_freeze_diff,
    git_freeze_manifest,
    manifest_freeze,
    repo_apply,
    repo_upgrade,
)
from script.todo.todo_i18n import t  # noqa: E402

# La racine du dépôt. Le lanceur de git-repo porte un shebang RELATIF vers le
# venv : lancé depuis un autre répertoire, il ne trouve pas son interpréteur
# et meurt sur « bad interpreter ». Toutes ses invocations partent donc d'ici.
RACINE = new_path
REPO_BIN = ".venv.erplibre/bin/repo"
PYTHON_ERPLIBRE = "./.venv.erplibre/bin/python"
FREEZE_SCRIPT = "script/git/git_freeze_manifest.py"
# Le manifeste que git-repo lit, produit par la fusion des fichiers de
# `manifest/`. Ses « revision » disent ce que le checkout suit réellement.
MANIFESTE_LOCAL = os.path.join(
    ".repo", "local_manifests", "erplibre_manifest.xml"
)

# Les états que « repo_apply » rend, traduits en clés d'affichage. Les clés
# du catalogue sont des phrases anglaises ; les états sont des identifiants
# internes, et les passer tels quels à t() y ferait entrer du français.
ETATS = {
    "rebase": "rebased",
    "conflit": "conflicting",
    "ignore": "untouched",
    "branche_existante": "a dated branch already exists",
    "branche_refusee": "the branch could not be created",
    "rebase_deja_en_cours": "a rebase was already in progress",
}


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


def gel_des_sources(racine=RACINE):
    """(gelés, total) des projets des fichiers sources, ou None illisible.

    Un projet est gelé quand l'un de ses fichiers lui donne
    « freeze-revision ». Les chemins des sources sont relatifs à la racine
    du dépôt : le répertoire courant y passe le temps de la lecture, puis
    revient.
    """
    depart = os.getcwd()
    try:
        os.chdir(racine)
        definitions = git_freeze_manifest.read_sources(
            git_freeze_manifest.default_sources()
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


class GitRepoMenuMixin:
    def prompt_execute_git_repo(self):
        version = repo_upgrade.version_active(RACINE) or "?"
        forks = repo_upgrade.etat_forks(version)
        print(f"🔃 {t('Update and upgrade the git repositories')}")
        print(
            f"   Odoo {version} · {len(forks)} {t('forks')}"
            f" · {libelle_mode(etat_manifeste_local())}"
        )
        sources = gel_des_sources()
        if sources:
            print(
                f"   {t('Frozen in the manifest files:')}"
                f" {sources[0]}/{sources[1]}"
            )
        choices = [
            {"section": t("Update")},
            {"prompt_description": t("🔄 Synchronize the repositories")},
            {"prompt_description": t("🔁 Reconfigure and synchronize")},
            {"section": t("Upgrade")},
            {"prompt_description": t("🔍 Upgrade — dry run")},
            {"prompt_description": t("⬆️ Apply the upgrade")},
            {"prompt_description": t("🧩 Conflict queue")},
            {"section": t("Observe")},
            {"prompt_description": t("📊 Report of the last pass")},
            {"prompt_description": t("🖥️ Browse the upgrade on screen")},
            {"prompt_description": t("🔗 Fork and upstream status")},
            {"section": t("Versions")},
            {"prompt_description": t("🧊 Freeze the versions")},
            {"prompt_description": t("📌 Reconfigure on the frozen commits")},
            {"prompt_description": t("🫗 Unfreeze the versions")},
            {"prompt_description": t("🔀 Compare two freezes")},
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
                self._git_repo_appliquer()
            elif status == "5":
                self._git_repo_file_conflits()
            elif status == "6":
                self._git_repo_rapport()
            elif status == "7":
                self._git_repo_ecran()
            elif status == "8":
                self._git_repo_etat_forks()
            elif status == "9":
                self._git_repo_geler()
            elif status == "10":
                self._git_repo_reconfigurer(freeze=True)
            elif status == "11":
                self._git_repo_geler(unfreeze=True)
            elif status == "12":
                self._git_repo_comparer()
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

    def _git_repo_appliquer(self):
        """Constate, montre, fait retaper la version, puis applique.

        La passe à sec tourne TOUJOURS d'abord et son compte fait contrat :
        une question posée avant de savoir ce qui sera touché n'est pas un
        consentement, c'est un pari. La confirmation redemande la version
        plutôt qu'un « o » : recopier oblige à regarder.

        Rend le nombre de dépôts rebasés.
        """
        version = repo_upgrade.version_active(RACINE) or "?"
        print(f"⬆️  {t('Apply the upgrade')} — Odoo {version}")
        print(f"   {t('Querying each upstream, this takes a few seconds.')}")
        lst = repo_upgrade.passe_diagnostic(version, racine=RACINE)
        a_faire = [
            x for x in lst if x["verdict"] in repo_apply.VERDICTS_A_APPLIQUER
        ]
        print()
        print(repo_upgrade.render_diagnostic(lst, version, colour=True))
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
            print(f"     {x['chemin']} → {branche}")
        print(f"   {t('Nothing is pushed.')}")
        tape = input(
            f"💬 {t('Type the Odoo version to confirm (empty to cancel): ')}"
        ).strip()
        if tape != version:
            print(f"↩️  {t('Cancelled: nothing was written.')}")
            return 0

        print()
        resultats = repo_apply.passe_appliquer(lst, horodatage, racine=RACINE)
        dossier = repo_apply.ecrire_passe(
            horodatage, version, lst, resultats, racine=RACINE
        )
        self._git_repo_resume_passe(resultats)
        print(f"   {t('Pass recorded in')} {dossier}")
        return len([r for r in resultats if r["etat"] == "rebase"])

    def _git_repo_resume_passe(self, resultats):
        """Une ligne par état, et la façon de reprendre ce qui a buté."""
        par_etat = {}
        for res in resultats:
            par_etat.setdefault(res["etat"], []).append(res)
        rebases = len(par_etat.get("rebase", []))
        conflits = par_etat.get("conflit", [])
        print(
            f"✅ {rebases} {t('rebased')} · {len(conflits)} {t('conflicting')}"
        )
        for etat, lst in sorted(par_etat.items()):
            if etat in ("rebase", "ignore"):
                continue
            for res in lst:
                print(
                    f"   ⚠  {res['chemin']} :" f" {t(ETATS.get(etat, etat))}"
                )
        if conflits:
            print(f"   {t('Work them through the conflict queue.')}")

    def _git_repo_rapport(self):
        """Ce que la dernière passe a fait, relu depuis son enregistrement."""
        passe = repo_apply.lire_passe(racine=RACINE)
        if not passe:
            print(f"↩️  {t('No pass recorded yet.')}")
            return 0
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
        """
        passe = repo_apply.lire_passe(racine=RACINE)
        if not passe:
            print(f"↩️  {t('No pass recorded yet.')}")
            return 0
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
            self._git_repo_resoudre(res)

    def _git_repo_resoudre(self, res):
        """Les gestes offerts sur un dépôt en conflit.

        « Garder le nôtre » et « prendre l'amont » traversent
        `repo_apply`, qui porte l'inversion de « ours » et « theirs »
        propre au rebase. Les appeler d'ici avec le drapeau qui semble
        juste garderait l'inverse de ce que le libellé annonce.
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
            print(f"  [0] 🔙 {t('Later')}")
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
                    print(f"  ✅ {t('Rebase finished.')}")
                    return
            elif choix == "6":
                repo_apply.sauter_le_commit(chemin)
                if not repo_apply.rebase_en_cours(chemin):
                    print(f"  ✅ {t('Rebase finished.')}")
                    return
            elif choix == "7":
                repo_apply.abandonner_rebase(chemin)
                print(f"  ↩️  {t('Rebase aborted.')}")
                return
            elif choix == "8":
                repo_apply.revenir_a_repo(chemin, res.get("depart"))
                print(f"  ↩️  {t('Back to the state managed by repo.')}")
                return
            else:
                print(t("Command not found !"))

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
        """Écrit le commit de chaque clone dans son fichier source, ou l'ôte.

        Le geste écrit des fichiers de `manifest/` à committer et ne déplace
        aucun clone. La passe à sec tourne d'abord et montre chaque fichier
        touché ; rien ne s'écrit sans confirmation. Le gel prend effet à la
        reconfiguration sur les commits gelés ; le dégel, à la
        reconfiguration qui suit les branches.

        Rend le code de sortie du script : 1 quand aucun clone n'est gelable.
        """
        script = f"{PYTHON_ERPLIBRE} {FREEZE_SCRIPT}"
        if unfreeze:
            script += " --unfreeze"
            print(f"🫗 {t('Unfreeze the versions')}")
        else:
            print(f"🧊 {t('Freeze the versions')}")
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
            print(f"   {t('Apply with: Reconfigure and synchronize.')}")
        else:
            print(f"   {t('Apply with: Reconfigure on the frozen commits.')}")
        return 0

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
        print(f"  [1] {t('Committed freeze → clones (real state)')}")
        print(f"  [2] {t('Written freeze (manifest/) → clones')}")
        print(f"  [3] {t('Committed freeze → written freeze, not committed')}")
        print(f"  [4] {t('Previous freeze → last freeze')}")
        print(f"  [5] {t('Two revisions of your choice')}")
        print(
            f"  [6] {t('Matrix: the ERPLibre branches and tags side by side')}"
        )
        print(f"  [0] {t('Back')}")
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
            print(f"  ⏎   {t('Back')}")
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
                print(
                    f"  📥 {t('Refreshing the clones, in parallel.')}"
                )
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
