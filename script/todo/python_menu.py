#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le menu Python : Poetry, le venv d'Odoo et les outils de l'interpréteur.

Il regroupe ce qui concerne Python, même quand l'outil vit aussi ailleurs :
« Upgrade Poetry » reste dans Code › Update et pip-audit dans Security. Les
deux chemins mènent à la MÊME méthode — rien n'est recopié ici, et
test_todo_menu le vérifie.

L'analyse des écarts DEMANDE et affiche : un venv d'Odoo face à son
poetry.lock, le venv de l'outillage face à ses exigences. La simulation de
Poetry, le relevé des versions et la comparaison vivent dans
script/poetry/poetry_venv_drift.py ; la lecture des exigences, dans
script/poetry/venv_requirements_drift.py. Le Healthcheck offre la même
analyse, par la même méthode.
"""

import glob
import json
import os
import shlex
import subprocess

import click

from script.poetry import poetry_venv_drift as drift
from script.todo import version_manager as vm
from script.todo.todo_couleur import retour
from script.todo.todo_i18n import t
from script.todo.version_manager import (
    diagnostiquer_version,
    get_odoo_version,
)


def _odoo_de(version_erplibre):
    """« odoo18.0_python3.12.16 » -> « odoo18.0 »."""
    return version_erplibre.split("_python", 1)[0]


# Les libellés du rapport, par action de Poetry.
LIBELLES = {
    "Installing": "Missing from the venv",
    "Updating": "Older than the lock",
    "Downgrading": "Newer than the lock",
}


class PythonMenuMixin:
    def prompt_execute_python(self):
        print(f"🤖 {t('Python and Poetry tools!')}")
        choices = [
            {
                "prompt_description": t(
                    "Lock drift - Compare a venv with its lock or requirements"
                )
            },
            {
                "prompt_description": t(
                    "Python versions - Install or update the venvs,"
                    " without the git repos"
                )
            },
            {"prompt_description": t("Upgrade Poetry - Dependency of Odoo")},
            {
                "prompt_description": t(
                    "pip-audit - Check vulnerabilities on Python environments"
                )
            },
            {"prompt_description": t("Install mise - Precompiled Python")},
            {"prompt_description": t("Install uv - Faster pip")},
        ]
        help_info = self.fill_help_info(choices)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self.execute_poetry_drift()
            elif status == "2":
                self.execute_python_versions()
            elif status == "3":
                self.upgrade_poetry()
            elif status == "4":
                self.execute_pip_audit()
            elif status == "5":
                self.execute_install_mise()
            elif status == "6":
                self.execute_install_uv()
            else:
                print(t("Command not found !"))

    def _python_versions_etat(self):
        """(plan, active, anciens) : le plan de planifier_venvs pour ce
        checkout, la version active, et les venvs d'Odoo que le json ne
        connaît plus — un Python d'un ancien patch, gardé après une mise à
        jour."""
        versions = get_odoo_version()[0]
        venvs = {
            chemin[len(".venv.") :]
            for chemin in glob.glob(".venv.odoo*")
            if os.path.isdir(chemin)
        }
        sources = {
            dossier[len("odoo") :]
            for dossier in glob.glob("odoo*")
            if os.path.isfile(os.path.join(dossier, "odoo", "odoo-bin"))
        }
        # Complet : l'interpréteur ET Poetry, que la phase poetry pose en
        # premier. Un venv sans l'un d'eux vient d'une mise à jour coupée.
        complets = {
            venv
            for venv in venvs
            if os.path.isfile(f".venv.{venv}/bin/python")
            and os.path.isfile(f".venv.{venv}/bin/poetry")
        }
        supportees = {v["erplibre_version"] for v in versions}
        anciens = sorted(venvs - supportees)
        active = self._poetry_drift_version()
        return (
            vm.planifier_venvs(versions, venvs, sources, complets, active),
            active,
            anciens,
        )

    def execute_python_versions(self):
        """Installe ou met à jour les venvs d'Odoo selon le json, SANS la
        phase des dépôts git de l'installation.

        Pour chaque cible : le venv d'abord (install_venv.sh — un échec ne
        change encore rien), puis le changement de version active
        (update_env_version.py --switch : fichiers de version et liens du
        lock, aucun dépôt), puis les dépendances du lock (EL_PHASE=poetry
        install_locally.sh, qui saute la phase setup et son
        install_git_repo.sh). L'ancien venv est gardé.
        """
        plan, active, anciens = self._python_versions_etat()
        print(t("Odoo venvs, from conf/supported_version_erplibre.json:"))
        actions = []
        for entree in plan:
            cible = entree["cible"]
            detail = f"Python {entree['python']}, Poetry {entree['poetry']}"
            marque = " ◀" if cible == active else ""
            if entree["action"] in (
                vm.MISE_A_JOUR,
                vm.INSTALLATION,
                vm.REPRISE,
            ):
                actions.append(entree)
                if entree["action"] == vm.REPRISE:
                    quoi = t("incomplete venv: resume")
                elif entree["action"] == vm.INSTALLATION:
                    quoi = t("venv missing, Odoo sources present: install")
                elif os.path.isdir(f".venv.{cible}"):
                    quoi = f"{t('activate instead of')} {entree['depuis']}"
                else:
                    quoi = f"{t('update from')} .venv.{entree['depuis']}"
                print(f"[{len(actions)}] {cible} — {quoi} ({detail}){marque}")
            elif entree["action"] == vm.A_JOUR:
                print(f"    {cible} — {t('up to date')} ({detail}){marque}")
            else:
                print(
                    f"    {cible} — {t('Odoo sources missing: full install')}"
                    f" (make install_odoo_{entree['odoo'].split('.')[0]})"
                )
        if anciens:
            print(
                f"ℹ️  {t('Venvs no longer supported, kept:')}"
                f" {', '.join('.venv.' + a for a in anciens)}"
            )
        if not actions:
            print(f"✅ {t('No Python version to install or update.')}")
            print(f"   {t('For the dependencies of the lock, see [1].')}")
            return
        cibles = self._python_versions_choisir(actions)
        if not cibles:
            return
        print(t("Will execute:"))
        for entree in cibles:
            for commande in self._python_versions_commandes(entree):
                print(f"   {commande}")
        prevu = self._python_versions_retour_prevu(active, cibles)
        if prevu:
            print(
                f"   {self._python_versions_switch(prevu)}"
                f"   ({t('back to the starting Odoo, if its venv exists')})"
            )
        elif self._python_versions_change_odoo(active, cibles):
            self._python_versions_avertir_config(cibles[-1]["cible"])
        question = t("Run them now (y/N, default: N)? ")
        if not self._is_yes(input(f"💬 {question}")):
            return
        self._python_versions_executer(cibles, active)

    def _python_versions_choisir(self, actions):
        """Les entrées choisies par leurs numéros, séparés par des espaces ;
        une saisie qui porte un numéro invalide est redemandée en entier."""
        valides = {str(n) for n in range(1, len(actions) + 1)}
        while True:
            reponse = input(
                f"💬 {t('Numbers separated by spaces, 0 to go back: ')}"
            )
            numeros = reponse.replace(",", " ").split()
            if numeros == ["0"] or not numeros:
                return []
            fautifs = [n for n in numeros if n not in valides]
            if fautifs:
                print(
                    f"{t('Error, cannot understand value')}"
                    f" '{' '.join(fautifs)}'"
                )
                continue
            choisies = []
            for numero in numeros:
                entree = actions[int(numero) - 1]
                if entree not in choisies:
                    choisies.append(entree)
            return choisies

    @staticmethod
    def _python_versions_commandes(entree):
        """Les trois commandes d'une cible, dans l'ordre où elles tournent."""
        cible = entree["cible"]
        return [
            f'./script/install/install_venv.sh "Odoo" .venv.{cible}'
            f" {entree['python']}",
            f"./script/version/update_env_version.py --erplibre_version"
            f" {cible} --switch",
            "EL_PHASE=poetry ./script/install/install_locally.sh",
        ]

    def _python_versions_executer(self, cibles, active):
        """Exécute chaque cible, s'arrête à la première commande en échec
        d'une cible, puis remet active la version supportée de l'Odoo de
        départ quand une autre a pris sa place.

        Une cible réussie est inscrite dans .erplibre-state.json, comme le
        fait l'installation complète : la ligne d'état du TODO lit ce
        fichier, et sans cela elle montrerait l'ancien Python.
        """
        bilan = []
        for entree in cibles:
            reussi = True
            for commande in self._python_versions_commandes(entree):
                status = self.execute.exec_command_live(
                    commande, source_erplibre=False
                )
                if status:
                    print(f"❌ {t('Step failed, the next ones are skipped:')}")
                    print(f"   {commande}")
                    reussi = False
                    break
            if reussi:
                self._python_versions_enregistrer(entree)
            bilan.append((entree["cible"], reussi))
        retour = self._python_versions_retour(active, cibles)
        if retour:
            self.execute.exec_command_live(
                self._python_versions_switch(retour), source_erplibre=False
            )
        finale = self._poetry_drift_version()
        self._python_versions_marquer_courante(finale)
        print()
        for cible, reussi in bilan:
            etat = "✅" if reussi else "❌"
            print(f"{etat} {cible}")
        print(f"ℹ️  {t('Active version:')} {finale}")
        if active and finale and _odoo_de(finale) != _odoo_de(active):
            self._python_versions_avertir_config(finale)

    @staticmethod
    def _python_versions_switch(cible):
        return (
            f"./script/version/update_env_version.py --erplibre_version"
            f" {cible} --switch"
        )

    @staticmethod
    def _python_versions_change_odoo(active, cibles):
        """Vrai si la dernière cible n'est pas de l'Odoo de départ."""
        return bool(
            active
            and cibles
            and _odoo_de(cibles[-1]["cible"]) != _odoo_de(active)
        )

    def _python_versions_retour_prevu(self, active, cibles):
        """La version supportée de l'Odoo de départ, quand la dernière cible
        est d'une autre Odoo ; None sinon. C'est ce que la confirmation
        montre : le retour n'a lieu que si son venv existe à la fin."""
        if not self._python_versions_change_odoo(active, cibles):
            return None
        for version in get_odoo_version()[0]:
            if _odoo_de(version["erplibre_version"]) == _odoo_de(active):
                return version["erplibre_version"]
        return None

    @staticmethod
    def _python_versions_avertir_config(finale):
        """config.conf est généré pour un Odoo précis : finir sur un autre
        laisserait ./run.sh démarrer cet Odoo avec les chemins du premier."""
        print(
            "⚠️  "
            + t(
                "The run ends on another Odoo than the starting one:"
                " config.conf still points at the starting Odoo."
            )
        )
        print(
            f"   {t('Active version:')} {finale} —"
            f" {t('to regenerate config.conf:')} ./script/generate_config.sh"
        )

    @staticmethod
    def _python_versions_enregistrer(entree):
        """Inscrit la cible comme installée, en gardant son choix d'extra."""
        try:
            from script.version import erplibre_state
        except ImportError:
            return
        erplibre_state.set_version_installed(
            entree["odoo"],
            extra=erplibre_state.get_version_extra(entree["odoo"]),
            python=entree["python"],
            poetry=entree["poetry"],
        )

    @staticmethod
    def _python_versions_marquer_courante(finale):
        """set_version_installed marque la dernière cible courante ; après un
        retour, la courante est de nouveau celle de .erplibre-version."""
        if not finale:
            return
        try:
            from script.version import erplibre_state
        except ImportError:
            return
        erplibre_state.set_version_switched(_odoo_de(finale)[len("odoo") :])

    def _python_versions_retour(self, active, cibles):
        """La version à remettre active après les cibles, ou None.

        Le dernier « --switch » laisse active la dernière cible. Quand
        l'Odoo de départ en a une autre, on revient à la version supportée
        de cet Odoo — celle qui vient d'être installée si elle en faisait
        partie —, pourvu que son venv existe : config.conf a été généré
        pour cet Odoo-là.
        """
        prevu = self._python_versions_retour_prevu(active, cibles)
        if prevu and os.path.isdir(f".venv.{prevu}"):
            return prevu
        return None

    def execute_install_mise(self):
        """mise pose un CPython précompilé : la cible du Makefile décide."""
        self.execute.exec_command_live(
            "make install_mise", source_erplibre=False
        )

    def execute_install_uv(self):
        """uv installe les paquets plus vite que pip, dans le venv d'outils."""
        self.execute.exec_command_live(
            "make install_uv", source_erplibre=False
        )

    def _poetry_drift_version(self):
        """La version d'ERPLibre active, lue dans .erplibre-version."""
        try:
            with open(".erplibre-version", encoding="utf-8") as fichier:
                return fichier.read().strip()
        except OSError:
            return ""

    def _poetry_drift_prerequis(self, version):
        """Vrai si l'analyse peut tourner ; sinon dit ce qui manque.

        Poetry lit les liens poetry.lock et pyproject.toml de la racine : un
        lien qui pointe vers un fichier absent — .erplibre-version changé
        sans réinstallation — ferait refuser Poetry sur un message qui ne
        nomme pas la cause.
        """
        if not version:
            print(f"❌ {t('No .erplibre-version: no active Odoo version.')}")
            self._afficher_versions_supportees()
            return False
        c = drift.chemins(version)
        if not os.path.isfile(c["poetry"]):
            print(f"❌ {t('Poetry is missing from the venv:')} {c['poetry']}")
            self._afficher_versions_supportees()
            return False
        for lien in (c["lien_lock"], c["lien_pyproject"]):
            if not os.path.isfile(lien):
                cible = os.readlink(lien) if os.path.islink(lien) else lien
                print(f"❌ {t('Missing file read by Poetry:')} {cible}")
                self._afficher_versions_supportees()
                return False
        return True

    def _afficher_versions_supportees(self):
        """Dit la version active, si conf/supported_version_erplibre.json la
        supporte, et sinon laquelle la remplace et comment y passer.

        C'est la cause la plus fréquente d'un lock ou d'un venv introuvable :
        un checkout resté sur un Python dont le patch n'est plus supporté —
        odoo18.0_python3.12.10 quand le json ne connaît que 3.12.16. Ni son
        lock ni son venv ne sont fournis, et réinstaller la même version ne
        les créerait pas.
        """
        versions = get_odoo_version()[0]
        active = self._poetry_drift_version()
        diag = diagnostiquer_version(active, versions)
        if not active:
            print(f"ℹ️  {t('No .erplibre-version: no active Odoo version.')}")
        else:
            venv = os.path.isdir(f".venv.{active}")
            etat = t("venv present") if venv else t("venv missing")
            print(f"ℹ️  {t('Active version:')} {active} ({etat})")
            majeure = active.split("_python", 1)[0].removeprefix("odoo")
            majeure = majeure.split(".")[0]
            if not diag["supportee"]:
                print(
                    "⚠️  "
                    + t(
                        "This version is not in"
                        " conf/supported_version_erplibre.json: no lock nor"
                        " venv is provided for it."
                    )
                )
                remplacante = diag["remplacante"]
                if remplacante:
                    print(
                        f"   {t('Supported for Odoo')}"
                        f" {remplacante['odoo_version']} :"
                        f" {remplacante['erplibre_version']}"
                        f" (Python {remplacante['python_version']},"
                        f" Poetry {remplacante.get('poetry_version', '?')})"
                    )
                    print(
                        f"   {t('To switch to it:')}"
                        f" make install_odoo_{majeure}"
                    )
            elif not venv:
                print(f"   {t('To install it:')} make install_odoo_{majeure}")
        print(t("Supported versions (conf/supported_version_erplibre.json):"))
        for version in versions[::-1]:
            cle = version["erplibre_version"]
            defaut = f" ({t('Default')})" if version.get("default") else ""
            venv = os.path.isdir(f".venv.{cle}")
            etat = t("venv present") if venv else t("venv missing")
            actif = " ◀" if cle == active else ""
            print(
                f"   {cle} — Odoo {version.get('odoo_version')},"
                f" Python {version.get('python_version')},"
                f" Poetry {version.get('poetry_version', '?')}{defaut}"
                f" — {etat}{actif}"
            )

    def _poetry_drift_afficher(self, version, simulation, lock=None):
        """Affiche une simulation ; rend vrai s'il y a des écarts. `lock`
        nomme le lock comparé, celui de la racine par défaut."""
        c = drift.chemins(version)
        lock = lock or os.path.realpath(c["lien_lock"])
        print(f"   $ {simulation['commande']}")
        print(f"🐍 {c['venv']} ↔ {lock}")
        if not simulation["ok"]:
            print(f"❌ {t('Poetry refuses to compare:')}")
            for ligne in simulation["sortie"].strip().splitlines()[-6:]:
                print(f"   {ligne}")
            return False
        classes = drift.classer(simulation["operations"])
        ecarts = sum(len(classes.get(a, [])) for a in drift.ECARTS)
        if not ecarts:
            print(f"✅ {t('The venv matches the lock.')}")
        else:
            print(f"⚠️  {t('Differences with the lock:')} {ecarts}")
            for action in drift.ECARTS:
                for op in classes.get(action, []):
                    versions = (
                        op["apres"]
                        if action == "Installing"
                        else (f"{op['avant']} → {op['apres']}")
                    )
                    print(f"   {t(LIBELLES[action])} : {op['nom']} {versions}")
        hors_lock = classes.get("Removing", [])
        if hors_lock:
            noms = ", ".join(op["nom"] for op in hors_lock[:10])
            suite = " …" if len(hors_lock) > 10 else ""
            print(
                f"ℹ️  {t('Outside the lock, left untouched by the update:')}"
                f" {len(hors_lock)} ({noms}{suite})"
            )
        return bool(ecarts)

    def execute_poetry_drift(self):
        """Compare un venv, choisi parmi ceux du checkout, à ce qu'il doit
        porter, et propose la mise à jour.

        Un venv d'Odoo se compare à son poetry.lock : celui de la version
        active par les liens de la racine, comme l'installation, un autre
        par son propre lock dans un dossier temporaire, sans toucher à la
        version active. Le venv de l'outillage se compare à ses exigences.
        Un seul venv est pris sans question."""
        active = self._poetry_drift_version()
        candidats = drift.venvs(".", active=active)
        if not active:
            print(f"ℹ️  {t('No .erplibre-version: no active Odoo version.')}")
        if not candidats:
            self._afficher_versions_supportees()
            return
        choix = self._venv_drift_choisir(candidats)
        if choix is None:
            return
        if choix["genre"] == "outillage":
            self._venv_outillage_drift(choix["venv"])
        elif choix["active"]:
            self._poetry_drift_actif(choix["version"])
        else:
            self._poetry_drift_autre(choix["version"])

    def _venv_drift_choisir(self, candidats):
        """Le venv choisi, ou None pour revenir ; un seul est pris
        d'office."""
        if len(candidats) == 1:
            print(f"🐍 {candidats[0]['venv']}")
            return candidats[0]
        for numero, venv in enumerate(candidats, 1):
            if venv["genre"] == "outillage":
                detail = f"{t('tooling')} — {drift.EXIGENCES_OUTILLAGE}"
            else:
                detail = drift.chemins(venv["version"])["lock"]
                if venv["active"]:
                    detail = f"{t('active version')} — {detail}"
            print(f"   [{numero}] {venv['venv']} — {detail}")
        print(f"   {retour(t('Back'))}")
        while True:
            try:
                reponse = input(f"💬 {t('Venv to check: ')}").strip()
            except EOFError:
                print()
                return None
            if reponse in ("", "0"):
                return None
            if reponse.isdigit() and 1 <= int(reponse) <= len(candidats):
                return candidats[int(reponse) - 1]
            print(f"{t('Error, cannot understand value')} '{reponse}'")

    def mettre_a_jour_venv(self, choix):
        """Met à jour le venv `choix` (une entrée de `drift.venvs`) sans
        poser de question : la résolution du Healthcheck qui l'appelle l'a
        fait choisir. La comparaison est refaite d'abord, et rien n'est
        installé si le venv est déjà aligné."""
        if choix["genre"] == "outillage":
            self._venv_outillage_drift(choix["venv"], demander=False)
        elif choix["active"]:
            self._poetry_drift_actif(choix["version"], demander=False)
        else:
            self._poetry_drift_autre(choix["version"], demander=False)

    def _poetry_drift_actif(self, version, demander=True):
        """Le venv de la version active face au lock de la racine.
        `demander` faux : la mise à jour suit sans question."""
        if not self._poetry_drift_prerequis(version):
            return
        simulation = drift.simuler(".", version)
        if not self._poetry_drift_afficher(version, simulation):
            return
        question = t("Update the venv to match the lock (y/N, default: N)? ")
        if demander and not self._is_yes(input(f"💬 {question}")):
            print(
                t("To update it later: %s")
                % "EL_PHASE=poetry ./script/install/install_locally.sh"
            )
            return
        self._poetry_drift_mettre_a_jour(version, simulation)

    def _poetry_drift_autre(self, version, demander=True):
        """Un venv d'Odoo qui n'est pas l'actif, face à SON lock, depuis un
        dossier de projet temporaire : la version active ne bouge pas.
        `demander` faux : la mise à jour suit sans question."""
        c = drift.chemins(version)
        if not os.path.isfile(c["poetry"]):
            print(f"❌ {t('Poetry is missing from the venv:')} {c['poetry']}")
            return
        for fichier in (c["lock"], c["pyproject"]):
            if not os.path.isfile(fichier):
                print(f"❌ {t('Missing file read by Poetry:')} {fichier}")
                return
        with drift.projet_temporaire(".", version) as projet:
            simulation = drift.simuler(".", version, projet=projet)
            if not self._poetry_drift_afficher(
                version, simulation, lock=c["lock"]
            ):
                return
            question = t(
                "Update the venv to match the lock (y/N, default: N)? "
            )
            if demander and not self._is_yes(input(f"💬 {question}")):
                return
            self._poetry_drift_mettre_a_jour(
                version,
                simulation,
                commande=drift.commande_installation(".", version, projet),
                projet=projet,
            )

    def _venv_outillage_drift(self, venv, demander=True):
        """Le venv de l'outillage face à ses exigences : manquantes, hors
        bornes, et paquets que rien ne demande. Propose d'installer ce qui
        manque ; un paquet de trop n'est jamais retiré. `demander` faux :
        l'installation suit sans question."""
        etat = self._venv_outillage_analyser(venv)
        if etat is None or not self._venv_outillage_afficher(venv, etat):
            return
        question = t("Install the missing requirements (y/N, default: N)? ")
        if demander and not self._is_yes(input(f"💬 {question}")):
            return
        commande = (
            ". ./script/install/lib_pip_provider.sh && el_pip_install"
            f" {shlex.quote(venv)} -r {drift.EXIGENCES_OUTILLAGE}"
        )
        print(f"   $ {commande}")
        self.execute.exec_command_live(commande, source_erplibre=False)
        etat = self._venv_outillage_analyser(venv)
        if etat is not None:
            self._venv_outillage_afficher(venv, etat)

    def _venv_outillage_analyser(self, venv):
        """La sortie JSON de venv_requirements_drift.py lancé par le Python
        de `venv`, ou None après l'avoir dit."""
        commande = [
            os.path.join(venv, "bin", "python"),
            "script/poetry/venv_requirements_drift.py",
            drift.EXIGENCES_OUTILLAGE,
        ]
        print(f"   $ {shlex.join(commande)}")
        fini = subprocess.run(commande, capture_output=True, text=True)
        try:
            etat = json.loads(fini.stdout)
        except ValueError:
            etat = {"erreur": (fini.stderr or fini.stdout).strip()}
        if "erreur" in etat:
            print(f"❌ {etat['erreur']}")
            return None
        return etat

    def _venv_outillage_afficher(self, venv, etat):
        """Affiche l'analyse ; rend vrai si une exigence n'est pas tenue."""
        print(f"🐍 {venv} ↔ {drift.EXIGENCES_OUTILLAGE}")
        ecarts = len(etat["manquantes"]) + len(etat["hors_bornes"])
        if not ecarts:
            print(
                f"✅ {t('The venv satisfies its requirements:')}"
                f" {etat['exigences']}"
            )
        else:
            print(f"⚠️  {t('Requirements not satisfied:')} {ecarts}")
            for exigence in etat["manquantes"]:
                print(f"   {t('Missing')} : {exigence}")
            for ecart in etat["hors_bornes"]:
                print(
                    f"   {t('Out of bounds')} : {ecart['exigence']}"
                    f" ({t('installed')} {ecart['installee']})"
                )
        for ligne in etat["illisibles"]:
            print(f"ℹ️  {t('Unreadable requirement:')} {ligne}")
        de_trop = etat["de_trop"]
        if de_trop:
            noms = ", ".join(f"{n} {v}" for n, v in de_trop[:10])
            suite = " …" if len(de_trop) > 10 else ""
            print(
                f"ℹ️  {t('Installed but required by nothing, left untouched:')}"
                f" {len(de_trop)} ({noms}{suite})"
            )
        return bool(ecarts)

    def _poetry_drift_mettre_a_jour(
        self, version, simulation_avant, commande=None, projet=None
    ):
        """Installe le lock, puis rapporte ce qui a changé et ce qui diverge
        encore. Par défaut, par le chemin de l'installation pour la version
        active ; `commande` et `projet` servent une autre version (voir
        `_poetry_drift_autre`)."""
        commande = (
            commande or "EL_PHASE=poetry ./script/install/install_locally.sh"
        )
        avant = drift.relever(".", version)
        print(f"   $ {commande}")
        status = self.execute.exec_command_live(
            commande, source_erplibre=False
        )
        apres = drift.relever(".", version)
        simulation_apres = drift.simuler(".", version, projet=projet)
        texte = self._poetry_drift_rapport(
            version, status, simulation_avant, simulation_apres, avant, apres
        )
        print()
        print(texte)
        chemin = drift.ecrire_rapport(texte, version)
        print(f"📄 {t('Update report:')} {chemin}")

    def _poetry_drift_rapport(
        self, version, status, simulation_avant, simulation_apres, avant, apres
    ):
        """Le rapport de mise à jour, en Markdown, dans la langue du TODO."""
        c = drift.chemins(version)
        lignes = [
            f"# {t('Poetry update report')} — {c['venv']}",
            "",
            f"- {t('Lock:')} {os.path.realpath(c['lien_lock'])}",
            f"- {t('Installation:')} "
            + (
                t("success")
                if not status
                else f"{t('failure, code')} {status}"
            ),
            "",
        ]
        if not avant or not apres:
            lignes.append(t("The venv interpreter did not answer: no list."))
        else:
            diff = drift.comparer(avant, apres)
            lignes.append(f"## {t('Changed versions')}")
            lignes += [f"- {n} : {a} → {b}" for n, a, b in diff["changes"]]
            lignes += ["", f"## {t('Installed')}"]
            lignes += [f"- {n} {v}" for n, v in diff["ajoutes"]]
            lignes += ["", f"## {t('Removed')}"]
            lignes += [f"- {n} {v}" for n, v in diff["retires"]]
            if not any(diff.values()):
                lignes += ["", t("No package changed.")]
        lignes += ["", f"## {t('Remaining differences with the lock')}"]
        if not simulation_apres["ok"]:
            lignes.append(t("Poetry refuses to compare:"))
            lignes += [
                f"    {ligne}"
                for ligne in simulation_apres["sortie"]
                .strip()
                .splitlines()[-6:]
            ]
        else:
            restants = [
                op
                for op in simulation_apres["operations"]
                if op["action"] in drift.ECARTS
            ]
            if not restants:
                lignes.append(t("None: the venv matches the lock."))
            for op in restants:
                lignes.append(
                    f"- {t(LIBELLES[op['action']])} : {op['nom']}"
                    f" {op['avant'] or ''} → {op['apres'] or ''}".rstrip()
                )
        avant_ecarts = sum(
            1
            for op in simulation_avant["operations"]
            if op["action"] in drift.ECARTS
        )
        lignes += ["", f"{t('Differences before the update:')} {avant_ecarts}"]
        return "\n".join(lignes) + "\n"
