#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le menu Python : Poetry, le venv d'Odoo et les outils de l'interpréteur.

Il regroupe ce qui concerne Python, même quand l'outil vit aussi ailleurs :
« Upgrade Poetry » reste dans Code › Update et pip-audit dans Security. Les
deux chemins mènent à la MÊME méthode — rien n'est recopié ici, et
test_todo_menu le vérifie.

L'analyse des écarts avec poetry.lock DEMANDE et affiche ; la simulation de
Poetry, le relevé des versions et la comparaison vivent dans
script/poetry/poetry_venv_drift.py.
"""

import os

import click

from script.poetry import poetry_venv_drift as drift
from script.todo.todo_i18n import t

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
                    "Lock drift - Compare the venv with poetry.lock"
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
                self.upgrade_poetry()
            elif status == "3":
                self.execute_pip_audit()
            elif status == "4":
                self.execute_install_mise()
            elif status == "5":
                self.execute_install_uv()
            else:
                print(t("Command not found !"))

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
            return False
        c = drift.chemins(version)
        if not os.path.isfile(c["poetry"]):
            print(f"❌ {t('Poetry is missing from the venv:')} {c['poetry']}")
            return False
        for lien in (c["lien_lock"], c["lien_pyproject"]):
            if not os.path.isfile(lien):
                cible = os.readlink(lien) if os.path.islink(lien) else lien
                print(f"❌ {t('Missing file read by Poetry:')} {cible}")
                print(f"   {t('Reinstall this Odoo version to recreate it.')}")
                return False
        return True

    def _poetry_drift_afficher(self, version, simulation):
        """Affiche une simulation ; rend vrai s'il y a des écarts."""
        c = drift.chemins(version)
        print(f"🐍 {c['venv']} ↔ {os.path.realpath(c['lien_lock'])}")
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
        """Compare le venv d'Odoo à son lock, propose la mise à jour, et en
        écrit le rapport."""
        version = self._poetry_drift_version()
        if not self._poetry_drift_prerequis(version):
            return
        simulation = drift.simuler(".", version)
        if not self._poetry_drift_afficher(version, simulation):
            return
        question = t("Update the venv to match the lock (y/N, default: N)? ")
        if not self._is_yes(input(f"💬 {question}")):
            print(
                t("To update it later: %s")
                % "EL_PHASE=poetry ./script/install/install_locally.sh"
            )
            return
        self._poetry_drift_mettre_a_jour(version, simulation)

    def _poetry_drift_mettre_a_jour(self, version, simulation_avant):
        """Installe le lock par le chemin de l'installation, puis rapporte ce
        qui a changé et ce qui diverge encore."""
        avant = drift.relever(".", version)
        status = self.execute.exec_command_live(
            "EL_PHASE=poetry ./script/install/install_locally.sh",
            source_erplibre=False,
        )
        apres = drift.relever(".", version)
        simulation_apres = drift.simuler(".", version)
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
