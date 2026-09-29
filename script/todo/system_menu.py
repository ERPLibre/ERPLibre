#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Menu Système : le diagnostic du poste, et l'espace qu'on peut récupérer.

Les faits viennent de system_diagnostic et les candidats de
system_cleanup ; ce fichier les met en phrases, pose les questions et tient
le formulaire. Rien n'est effacé sans une case cochée ET une confirmation.

Mixin de la classe TODO : ses méthodes vivent sur la même instance que
celles des autres fichiers, elles s'appellent donc par « self. ».
"""

import datetime
import os
import subprocess
import sys

import click

from script.todo import system_cleanup, system_diagnostic
from script.todo.todo_i18n import t

# Les jours d'inactivité au-delà desquels un reste de /tmp ou une session
# web d'Odoo devient un candidat.
JOURS_INACTIFS = 2

LIBELLES_CATEGORIE = {
    system_cleanup.CACHE: "Cache",
    system_cleanup.TMP: "Temporary leftover",
    system_cleanup.FILESTORE: "Orphan filestore",
    system_cleanup.SESSIONS: "Odoo web sessions",
    system_cleanup.VENV: "Other Odoo venv",
}

MISES_EN_GARDE = {
    "reinstall": "reinstall to switch back to this version",
    "recent": "recent: its database may be being created",
}

RAISONS = {
    "link": "path is or crosses a link",
    "owner": "not yours",
    "protected": "private/ or tasks/",
    "outside": "outside the allowed directories",
    "missing": "already gone",
    "database": "its database exists again",
    "no-database-list": "database list unavailable",
}


def octets(n):
    """1536 -> « 1.5 Kio » ; None -> None."""
    if n is None:
        return None
    for unite in ("o", "Kio", "Mio", "Gio", "Tio"):
        if abs(n) < 1024 or unite == "Tio":
            return f"{n:.0f} {unite}" if unite == "o" else f"{n:.1f} {unite}"
        n /= 1024
    return None


def duree(secondes):
    """Secondes -> « 3 j 4 h », « 5 h 12 min », « 7 min »."""
    if secondes is None:
        return None
    minutes = int(secondes // 60)
    jours, minutes = divmod(minutes, 1440)
    heures, minutes = divmod(minutes, 60)
    if jours:
        return f"{jours} j {heures} h"
    if heures:
        return f"{heures} h {minutes} min"
    return f"{minutes} min"


def lignes_diagnostic(faits):
    """Le diagnostic en lignes de texte, section par section."""
    absent = t("unavailable")

    def val(x):
        return absent if x in (None, "", []) else str(x)

    ident = faits["identity"]
    cpu = faits["cpu"]
    mem = faits["memory"]
    charge = faits["load"]
    erp = faits["erplibre"]
    materiel = " ".join(x for x in (ident["vendor"], ident["model"]) if x)
    lignes = [
        f"── {t('Identity')} ──",
        f"  {t('Host name')} : {val(ident['hostname'])}",
        f"  {t('Operating system')} : {val(ident['os'])}",
        f"  {t('Kernel')} : {val(ident['kernel'])}",
        f"  {t('Architecture')} : {val(ident['architecture'])}",
        f"  {t('Chassis')} : {val(ident['chassis'])}",
        f"  {t('Virtualization')} : {val(ident['virtualization'])}",
        f"  {t('Hardware')} : {val(materiel)}",
        "",
        f"── {t('Processor and memory')} ──",
        f"  {t('Processor')} : {val(cpu['model'])}",
        f"  {t('Cores (physical / logical)')} :"
        f" {val(cpu['physical'])} / {val(cpu['logical'])}",
        f"  {t('Memory')} : {val(octets(mem['available']))}"
        f" {t('available of')} {val(octets(mem['total']))}",
        f"  {t('Swap')} : {val(octets(mem['swap_free']))}"
        f" {t('free of')} {val(octets(mem['swap_total']))}",
    ]
    gpu = faits["gpu"]
    lignes.append(
        f"  {t('Graphics')} : "
        + (
            t("lspci not installed")
            if gpu is None
            else (", ".join(gpu) if gpu else absent)
        )
    )
    lignes += ["", f"── {t('Disks')} ──"]
    for p in faits["partitions"] or []:
        pct = 100 * p["used"] / p["total"] if p["total"] else 0
        repere = f"  ← {t('repository')}" if p["repo"] else ""
        lignes.append(
            f"  {p['mountpoint']:<20} {p['fstype']:<6}"
            f" {octets(p['free']):>10} {t('free of')}"
            f" {octets(p['total']):>10} ({pct:.0f} %){repere}"
        )
    if not faits["partitions"]:
        lignes.append(f"  {absent}")
    moyennes = charge["load"]
    lignes += [
        "",
        f"── {t('Load')} ──",
        f"  {t('Load (1, 5, 15 min)')} : "
        + (" ".join(f"{x:.2f}" for x in moyennes) if moyennes else absent),
        f"  {t('Uptime')} : {val(duree(charge['uptime']))}",
        "",
        "── ERPLibre ──",
        f"  ERPLibre : {val(erp['erplibre'])}   Odoo : {val(erp['odoo'])}"
        f"   Python : {val(erp['python'])}",
        f"  {t('Active venv')} : {val(erp['active_venv'])}",
        f"  {t('Venvs')} : {val(', '.join(erp['venvs']))}",
    ]
    return lignes


def libelle(candidat):
    """Une ligne du formulaire : taille, catégorie, nom, mise en garde."""
    nom = candidat.nom
    if len(candidat.chemins) > 1:
        nom += f" ({len(candidat.chemins)})"
    ligne = (
        f"{octets(candidat.taille):>10}  "
        f"{t(LIBELLES_CATEGORIE[candidat.categorie])} : {nom}"
    )
    if candidat.age:
        ligne += f"  · {duree(candidat.age)}"
    if candidat.mise_en_garde:
        ligne += f"  ⚠ {t(MISES_EN_GARDE[candidat.mise_en_garde])}"
    return ligne


def choisir_au_formulaire(candidats):
    """Les indices cochés dans un formulaire Textual ; None si on annule,
    « sans-tui » si Textual manque (l'appelant pose alors la question en
    ligne)."""
    app = formulaire(candidats)
    return "sans-tui" if app is None else app.run()


def formulaire(candidats):
    """L'application Textual du choix, ou None si Textual manque. À part
    de son lancement pour qu'un test la pilote."""
    try:
        from rich.text import Text
        from textual.app import App
        from textual.containers import Horizontal
        from textual.widgets import (
            Button,
            Footer,
            Header,
            SelectionList,
            Static,
        )
        from textual.widgets.selection_list import Selection
    except ImportError:
        return None

    class Formulaire(App):
        TITLE = t("Space to reclaim")
        CSS = """
        SelectionList { height: 1fr; }
        #boutons { height: auto; padding: 1 0 0 0; }
        Button { margin: 0 2 0 0; }
        """
        BINDINGS = [("escape", "annuler", t("Cancel"))]

        def compose(self):
            yield Header()
            # Du texte brut : un chemin porte parfois des crochets, que le
            # balisage de Textual prendrait pour les siens.
            yield Static(Text(t("Check what to delete, then choose Delete.")))
            yield SelectionList(
                *(
                    Selection(Text(libelle(c)), i, c.coche)
                    for i, c in enumerate(candidats)
                )
            )
            with Horizontal(id="boutons"):
                yield Button(t("Delete"), id="effacer", variant="error")
                yield Button(t("Cancel"), id="annuler")
            yield Footer()

        def on_button_pressed(self, event):
            if event.button.id == "effacer":
                self.exit(list(self.query_one(SelectionList).selected))
            else:
                self.exit(None)

        def action_annuler(self):
            self.exit(None)

    return Formulaire()


def choisir_en_ligne(candidats):
    """La même chose sans terminal plein écran : une liste numérotée."""
    for i, c in enumerate(candidats, 1):
        print(f"  [{i}] {'☑' if c.coche else '☐'} {libelle(c)}")
    reponse = input(
        t(
            "Numbers to delete (e.g. 1,3), Enter for the checked ones, c to cancel: "
        )
    ).strip()
    if reponse.lower() == "c":
        return None
    if not reponse:
        return [i for i, c in enumerate(candidats) if c.coche]
    choisis = []
    for morceau in reponse.replace(" ", "").split(","):
        if morceau.isdigit() and 1 <= int(morceau) <= len(candidats):
            choisis.append(int(morceau) - 1)
    return sorted(set(choisis))


class SystemMenuMixin:
    def prompt_execute_system(self):
        print(f"🤖 {t('System and disk space!')}")
        choices = [
            {"prompt_description": t("System diagnostic")},
            {"prompt_description": t("Space to reclaim")},
        ]
        help_info = self.fill_help_info(choices)
        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self._system_diagnostic()
            elif status == "2":
                self._system_espace()
            else:
                print(t("Command not found !"))

    def _system_diagnostic(self):
        faits = system_diagnostic.collecter(".")
        lignes = lignes_diagnostic(faits)
        print("\n".join(lignes))
        print()
        if not self._is_yes(
            input(t("Save this report in private/diagnostic/? (y/N): "))
        ):
            return
        dossier = os.path.join("private", "diagnostic")
        os.makedirs(dossier, exist_ok=True)
        nom = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S") + ".txt"
        chemin = os.path.join(dossier, nom)
        with open(chemin, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lignes) + "\n")
        print(f"  ✓ {t('Report saved:')} {chemin}")

    def _system_bases(self):
        """Les bases que PostgreSQL connaît, ou None s'il ne répond pas.
        La connexion vient de config.conf, en lecture seule."""
        try:
            from script.analyse import lib_analyse

            env = lib_analyse.pg_env(timeout=10)
            res = subprocess.run(
                [
                    "psql",
                    "-d",
                    "postgres",
                    "-Atc",
                    "SELECT datname FROM pg_database",
                ],
                env=env,
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError, ImportError):
            return None
        if res.returncode != 0:
            return None
        return set(res.stdout.split())

    def _system_data_dir(self):
        try:
            from script.analyse import lib_analyse

            data_dir = str(lib_analyse.read_config().get("data_dir", ""))
        except Exception:
            return None
        return (
            data_dir if data_dir.lower() not in ("", "false", "none") else None
        )

    def _system_espace(self):
        print(f"  {t('Searching for space to reclaim…')}")
        data_dir = self._system_data_dir()
        bases = self._system_bases()
        if bases is None:
            print(
                f"  ⚠ {t('PostgreSQL unreachable: Odoo filestores are not proposed.')}"
            )
        try:
            with open(".erplibre-version", encoding="utf-8") as fh:
                actif = ".venv." + fh.read().strip()
        except OSError:
            actif = None
        candidats = system_cleanup.candidats(
            ".",
            data_dir=data_dir,
            bases=bases,
            actif=actif,
            jours=JOURS_INACTIFS,
        )
        if not candidats:
            print(f"  {t('Nothing to reclaim.')}")
            return
        total = sum(c.taille for c in candidats)
        print(f"  {len(candidats)} → {octets(total)}")
        choisis = None
        if sys.stdin.isatty() and sys.stdout.isatty():
            choisis = choisir_au_formulaire(candidats)
        if choisis == "sans-tui" or not (
            sys.stdin.isatty() and sys.stdout.isatty()
        ):
            choisis = choisir_en_ligne(candidats)
        if not choisis:
            print(f"  {t('Nothing selected.')}")
            return
        retenus = [candidats[i] for i in choisis]
        for c in retenus:
            print(f"  - {libelle(c)}")
        prevu = sum(c.taille for c in retenus)
        if not self._is_yes(
            input(f"{t('Delete these items?')} ({octets(prevu)}) (y/N): ")
        ):
            print(f"  {t('Nothing deleted.')}")
            return
        # La liste des bases est RELUE ici : un filestore dont la base est
        # apparue depuis la recherche ne doit pas partir.
        racine = os.path.realpath(".")
        liberes, laisses = system_cleanup.effacer(
            retenus,
            racine,
            system_cleanup.racines_permises(
                racine, os.path.expanduser("~"), "/tmp", data_dir
            ),
            os.getuid(),
            bases=self._system_bases(),
        )
        print(f"  ✓ {t('Freed:')} {octets(liberes)}")
        if laisses:
            print(f"  {t('Left in place:')}")
            for chemin, raison in laisses:
                print(f"    {chemin} — {t(RAISONS.get(raison, raison))}")
