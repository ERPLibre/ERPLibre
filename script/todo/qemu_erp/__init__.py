#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Registre des ERP que les formulaires QEMU et Proxmox installent en VM.

Chaque ERP est un descripteur ErpApp, déclaré dans son propre module
(odoo.py, dolibarr.py) ; REGISTRY les range dans l'ordre d'affichage, Odoo
en tête. Les appelants lisent le descripteur au lieu de comparer une clé :
un ERP de plus est un module de plus, pas une branche de plus chez eux.

Une VM est identifiée par la commande d'installation EXACTE de son profil,
et une entrée de manifeste par sa clé « app ». Une commande qu'aucun
descripteur ne reconnaît, une entrée sans clé ou une clé inconnue désignent
Odoo : c'est ce qu'étaient les VM écrites avant le registre.
"""

from dataclasses import dataclass
from typing import Callable, Optional

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - i18n absent hors du TUI

    def t(key):
        return key


APP_ODOO = "odoo"
APP_DOLIBARR = "dolibarr"


def no_refusal(*_args):
    """Refus vide : ce que rend un ERP qui accepte tout."""
    return ""


def no_hint(_ssh, _el_dir):
    """Aucune ligne d'aide après l'échec du navigateur."""
    return []


@dataclass(frozen=True)
class ErpApp:
    """Ce que les formulaires et le suivi savent d'un ERP installé en VM.

    Les champs `label`, `prod_note`, `offline_refusal`, « *_button » et
    « *_title » sont des clés i18n : l'appelant les traduit par t(). Les
    champs appelables sont des fonctions simples, et non des méthodes : le
    descripteur est une donnée figée.
    """

    # Clé écrite dans le manifeste du suivi (« app ») et passée à
    # deploy_qemu.py par --app ; Odoo ne l'écrit jamais.
    key: str
    # Nom affiché tel quel, en titre du groupe de l'ERP dans les actions.
    name: str
    # Port de l'instance dans l'invité, et port local du tunnel qui y mène.
    port: int
    tunnel_port: int
    # Libellé du bouton de relance du suivi, et titre de son terminal.
    restart_button: str
    restart_title: str
    # Commande du profil, reconnue par égalité après strip(), et le libellé
    # de ce profil dans la liste. None pour Odoo, dont les profils sont
    # bâtis par version dans _qemu_install_profiles.
    install_cmd: Optional[str] = None
    label: Optional[str] = None
    # Vrai quand le profil s'installe en développement quelle que soit la
    # case « Production » ; prod_note dit pourquoi la case se grise.
    dev_only: bool = False
    prod_note: Optional[str] = None
    # Raison du refus d'une spec hors ligne ; None quand l'ERP s'y déploie.
    offline_refusal: Optional[str] = None
    # distro -> raison traduite du refus de ce système, ou "".
    distro_refusal: Callable[[str], str] = no_refusal
    # Vrai quand l'instance n'écoute que sur la boucle locale de l'invité :
    # le suivi la sonde par ssh + curl DANS la VM, et l'ouvre toujours par
    # un tunnel ssh de tunnel_port vers port. Faux : la sonde est celle
    # d'Odoo, une connexion TCP directe sur 8069 ; la page web se joint sur
    # port, ou de tunnel_port vers port par le rebond d'un hôte Proxmox.
    guest_probe: bool = False
    # el_dir -> commande de relance dans l'invité ; None laisse le suivi
    # relancer le service ERPLibre.
    restart_cmd: Optional[Callable[[str], str]] = None
    # Commande de l'invité qui affiche l'identifiant et le mot de passe
    # admin ; None : l'action n'est pas offerte.
    credentials_cmd: Optional[Callable[[], str]] = None
    credentials_button: Optional[str] = None
    credentials_title: Optional[str] = None
    # (kind, parts) -> raison traduite de refuser l'action du suivi, ou "".
    action_refusal: Callable[[str, object], str] = no_refusal
    # (préfixe ssh de la VM, clone de l'invité) -> lignes affichées quand
    # le navigateur sort en erreur.
    web_hint: Callable[[str, str], list] = no_hint

    def matches(self, cmd):
        """Vrai si `cmd` est la commande du profil de cet ERP."""
        return (
            self.install_cmd is not None
            and (cmd or "").strip() == self.install_cmd
        )


def get(key):
    """Le descripteur de `key` ; Odoo pour une clé vide ou inconnue."""
    return next((a for a in REGISTRY if a.key == key), DEFAULT)


def app_for_cmd(cmd):
    """Le descripteur dont `cmd` est la commande de profil, sinon Odoo."""
    return next((a for a in REGISTRY if a.matches(cmd)), DEFAULT)


def profile_app(cmd):
    """La clé de l'ERP que la commande `cmd` installe, APP_ODOO par défaut."""
    return app_for_cmd(cmd).key


def app_of(entry):
    """L'application d'une entrée de manifeste ; sans clé « app », Odoo."""
    return (entry or {}).get("app") or APP_ODOO


def app_for_entry(entry):
    """Le descripteur d'une entrée de manifeste, par app_of puis get."""
    return get(app_of(entry))


def install_refusals(spec):
    """Les raisons de refuser `spec` avant de créer quoi que ce soit.

    Une VM sur un système que son ERP refuse donne « <nom>: <raison> », dans
    l'ordre des VM. Une spec hors ligne ajoute ensuite, une fois par ERP et
    dans l'ordre de première apparition, le offline_refusal traduit de
    chaque ERP qui ne s'y déploie pas. Rend [] sans installation.
    """
    install = spec.get("install")
    if not install:
        return []
    refus = []
    hors_ligne = []
    for vm in spec.get("vms") or []:
        app = app_for_cmd(vm.get("install_cmd") or install.get("cmd"))
        if app.offline_refusal and app.offline_refusal not in hors_ligne:
            hors_ligne.append(app.offline_refusal)
        raison = app.distro_refusal(vm.get("distro", ""))
        if raison:
            refus.append(f"{vm['name']}: {raison}")
    if spec.get("offline"):
        refus += [t(r) for r in hors_ligne]
    return refus


# Les descripteurs importent ErpApp, les clés et les aides ci-dessus, qui ne
# lisent REGISTRY qu'à l'appel : le registre se bâtit en dernier, quel que
# soit le module importé en premier.
from script.todo.qemu_erp import dolibarr, odoo  # noqa: E402

REGISTRY = (odoo.APP, dolibarr.APP)
DEFAULT = REGISTRY[0]
