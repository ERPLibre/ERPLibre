#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Menu Système : le diagnostic du poste.

Les faits viennent de system_diagnostic ; ce fichier les met en phrases et
propose d'enregistrer le rapport.

Mixin de la classe TODO : ses méthodes vivent sur la même instance que
celles des autres fichiers, elles s'appellent donc par « self. ».
"""

import datetime
import os

import click

from script.todo import system_diagnostic
from script.todo.todo_i18n import t


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


class SystemMenuMixin:
    def prompt_execute_system(self):
        print(f"🤖 {t('System and disk space!')}")
        choices = [
            {"prompt_description": t("System diagnostic")},
        ]
        help_info = self.fill_help_info(choices)
        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self._system_diagnostic()
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
