#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Odoo dans le registre des ERP installés en VM.

Odoo est l'ERP par défaut : ses versions viennent de
conf/supported_version_erplibre.json (clés « odoo_version »), la plus
récente d'abord, plus « toutes les versions » ; chacune a sa commande, et
aucune commande unique ne reconnaît Odoo. Il accepte la production, tous
les systèmes du catalogue, et le hors-ligne que le cache de téléchargement
gère ailleurs. Le suivi le sonde par une connexion TCP sur 8069 et le
relance par le service ERPLibre. En production, il sert les quatre modes
d'accès web : nginx devant 8069, ou 8069 directement.
"""

import functools
import json
from pathlib import Path

from script.todo.qemu_erp import APP_ODOO, ErpApp, ErpVersion, access, t

# La table des versions d'ERPLibre, lue depuis la racine du dépôt quel que
# soit le répertoire courant.
RACINE = Path(__file__).resolve().parents[3]
CATALOGUE = RACINE / "conf" / "supported_version_erplibre.json"
# Valeur de « version » du profil qui installe toutes les versions.
ALL_VERSIONS = "all"
ALL_VERSIONS_CMD = "make install_os && make install_odoo_all_version"


@functools.lru_cache(maxsize=1)
def _catalogue():
    """Les entrées du catalogue, lues une fois ; () s'il est illisible."""
    try:
        data = json.loads(CATALOGUE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    return tuple(e for e in data.values() if (e or {}).get("odoo_version"))


def _rang(version):
    """Clé de tri numérique de « 18.0 » ; une forme inattendue va en fin."""
    try:
        return tuple(int(p) for p in version.split("."))
    except ValueError:
        return ()


def install_cmd(version):
    """La commande du profil de `version` : la cible make porte la version
    majeure, « 18.0 » s'installe par install_odoo_18."""
    if version == ALL_VERSIONS:
        return ALL_VERSIONS_CMD
    return f"make install_os && make install_odoo_{version.split('.')[0]}"


def versions():
    """Les versions offertes, de la plus récente à la plus ancienne, puis
    toutes les versions. Une version « is_deprecated » le dit dans son
    libellé ; celle marquée « default » est le défaut du sélecteur."""
    entrees = sorted(
        _catalogue(), key=lambda e: _rang(e["odoo_version"]), reverse=True
    )
    out = []
    for e in entrees:
        v = e["odoo_version"]
        majeure = v.split(".")[0]
        obsolete = bool(e.get("is_deprecated"))
        out.append(
            ErpVersion(
                key=v,
                label=t("%s (deprecated)") % v if obsolete else v,
                cmd=install_cmd(v),
                profile_label=f"ERPLibre + Odoo {majeure}",
                deprecated=obsolete,
                default=bool(e.get("default")),
            )
        )
    out.append(
        ErpVersion(
            key=ALL_VERSIONS,
            label=t("All versions"),
            cmd=ALL_VERSIONS_CMD,
            profile_label=t("ERPLibre + all Odoo versions"),
        )
    )
    return tuple(out)


def web_hint(_ssh, _el_dir):
    """La ligne affichée quand le navigateur sort en erreur sur une VM
    Odoo."""
    return [
        "La page ne s'est peut-être pas affichée : Odoo n'est "
        "pas démarré sur :8069, ou réseau/pare-feu. Vérifie que "
        "le service Odoo tourne dans la VM (make run / systemd)."
    ]


APP = ErpApp(
    key=APP_ODOO,
    name="Odoo",
    port=8069,
    tunnel_port=18069,
    restart_button="Restart Odoo",
    restart_title="Restarting Odoo",
    web_hint=web_hint,
    versions=versions,
    access_modes=access.ALL_KEYS,
)
