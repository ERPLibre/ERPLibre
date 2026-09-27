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

import datetime
import os
import sys

import click

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.append(new_path)

from script.git import repo_apply, repo_upgrade  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402
from script.version import erplibre_state  # noqa: E402

# La racine du dépôt. Le lanceur de git-repo porte un shebang RELATIF vers le
# venv : lancé depuis un autre répertoire, il ne trouve pas son interpréteur
# et meurt sur « bad interpreter ». Toutes ses invocations partent donc d'ici.
RACINE = new_path
REPO_BIN = ".venv.erplibre/bin/repo"

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


class GitRepoMenuMixin:
    def prompt_execute_git_repo(self):
        version = repo_upgrade.version_active(RACINE) or "?"
        forks = repo_upgrade.etat_forks(version)
        print(f"🔃 {t('Update and upgrade the git repositories')}")
        reglages = erplibre_state.get_git_repo()
        mode = (
            t("frozen mode, pinned to a commit")
            if reglages["mode"] == erplibre_state.MODE_FIGE
            else t("dev mode, follows the branches")
        )
        print(f"   Odoo {version} · {len(forks)} {t('forks')} · {mode}")
        if reglages.get("gel"):
            print(f"   {t('freeze')} : {reglages['gel']}")
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
            {"prompt_description": t("🔀 Toggle frozen or dev mode")},
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
                self._git_repo_basculer_mode()
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

    def _git_repo_geler(self):
        """Épingle chaque dépôt à son commit, dans un fichier versé.

        Le fichier porte le COMMIT dans « revision » et la BRANCHE dans
        « upstream » : un seul fichier sert donc les deux modes, et il n'y
        a pas deux manifestes à tenir alignés.

        Le gel est ENREGISTRÉ mais ne prend effet qu'à la reconfiguration :
        c'est elle qui régénère le manifeste local que git-repo lit.
        """
        version = repo_upgrade.version_active(RACINE) or "?"
        horodatage = datetime.datetime.now().strftime("%Y%m%dT%H%M")
        relatif = os.path.join(
            "manifest", "snapshot", f"odoo{version}_{horodatage}.xml"
        )
        sortie = os.path.join(RACINE, relatif)
        os.makedirs(os.path.dirname(sortie), exist_ok=True)
        cmd = f"{REPO_BIN} manifest -r -o {relatif}"
        print(f"🧊 {t('Freeze the versions')} — Odoo {version}")
        print(f"  {t('Will execute:')} {cmd}")
        status = self.execute.exec_command_live(
            f"cd {RACINE} && {cmd}", source_erplibre=False
        )
        if status or not os.path.isfile(sortie):
            print(f"⚠  {t('The freeze could not be produced.')} ({status})")
            return status or 1
        erplibre_state.set_git_repo_gel(relatif)
        print(f"✅ {t('Freeze written to')} {relatif}")
        print(f"   {t('Reconfigure and synchronize to apply it.')}")
        return 0

    def _git_repo_basculer_mode(self):
        """Fait passer le plan de travail du suivi de branche à l'épinglage.

        Le mode est un état du checkout et non un argument de la commande :
        une reconfiguration lancée ailleurs, par le Makefile par exemple,
        doit lire le même choix, sans quoi le plan de travail bougerait sans
        que personne ne l'ait demandé.
        """
        reglages = erplibre_state.get_git_repo()
        ancien = reglages["mode"]
        neuf = (
            erplibre_state.MODE_DEV
            if ancien == erplibre_state.MODE_FIGE
            else erplibre_state.MODE_FIGE
        )
        if neuf == erplibre_state.MODE_FIGE and not reglages.get("gel"):
            print(f"⚠  {t('No freeze file recorded; freeze first.')}")
            return 1
        erplibre_state.set_git_repo_mode(neuf)
        libelle = (
            t("frozen mode, pinned to a commit")
            if neuf == erplibre_state.MODE_FIGE
            else t("dev mode, follows the branches")
        )
        print(f"✅ {libelle}")
        print(f"   {t('Reconfigure and synchronize to apply it.')}")
        return 0
