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

Les formulaires choisissent un ERP puis une de ses versions (ErpVersion) ;
la commande s'en déduit par ErpApp.install_cmd_for, et la spec porte le
couple dans « app » et « version » à côté de la commande. Le choix APP_NONE
désigne les profils qui n'installent aucun ERP du registre (ERPLibre seul,
Home, hyperviseur…) : ses valeurs sont les commandes elles-mêmes.
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
# Clé du choix « aucun ERP » : un profil hors registre. get() la ramène au
# défaut, comme toute clé inconnue, ce que valait déjà une telle commande
# pour app_for_cmd.
APP_NONE = "none"


def no_refusal(*_args):
    """Refus vide : ce que rend un ERP qui accepte tout."""
    return ""


def no_hint(_ssh, _el_dir):
    """Aucune ligne d'aide après l'échec du navigateur."""
    return []


def no_versions():
    """Aucune version installable : l'ERP n'est pas offert au sélecteur."""
    return ()


@dataclass(frozen=True)
class ErpVersion:
    """Une version qu'un ERP sait installer en VM.

    `key` est la valeur écrite dans la spec (« version ») ; `label` le texte
    de la liste Version, et `profile_label` celui du profil (liste plate,
    « install_label »), tous deux déjà traduits : versions() est appelée au
    moment de l'affichage. `cmd` est la commande lancée depuis le clone
    ERPLibre de l'invité.
    """

    key: str
    label: str
    cmd: str
    profile_label: str
    deprecated: bool = False
    default: bool = False


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
    # () -> les ErpVersion offertes, dans l'ordre d'affichage ; vide, l'ERP
    # n'apparaît pas au sélecteur ERP / Version.
    versions: Callable[[], tuple] = no_versions

    def matches(self, cmd):
        """Vrai si `cmd` est la commande du profil de cet ERP."""
        return (
            self.install_cmd is not None
            and (cmd or "").strip() == self.install_cmd
        )

    def default_version(self):
        """La clé de la version marquée « default », sinon la première ; ""
        sans version."""
        offertes = tuple(self.versions())
        return next(
            (v.key for v in offertes if v.default),
            offertes[0].key if offertes else "",
        )

    def find_version(self, key):
        """L'ErpVersion de clé `key`, ou None."""
        return next((v for v in self.versions() if v.key == key), None)

    def install_cmd_for(self, version=""):
        """La commande qui installe `version` ; une version vide vaut la
        version par défaut, une version inconnue rend ""."""
        trouvee = self.find_version(version or self.default_version())
        return trouvee.cmd if trouvee else ""

    def version_for_cmd(self, cmd):
        """La clé de la version dont `cmd` est la commande, comparée après
        strip(), ou None."""
        cmd = (cmd or "").strip()
        return next((v.key for v in self.versions() if v.cmd == cmd), None)


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


def choice_for_cmd(cmd):
    """(clé d'ERP, version) que la commande `cmd` installe.

    Rend (APP_NONE, "") pour une commande qu'aucune version du registre ne
    porte, vide comprise : c'est un profil hors ERP. À distinguer de
    app_for_cmd, qui ramène une telle commande à Odoo pour le suivi.
    """
    for app in REGISTRY:
        version = app.version_for_cmd(cmd)
        if version is not None:
            return app.key, version
    return APP_NONE, ""


def choice_fields(cmd):
    """{"app", "version", "options"} déduits de `cmd`, tels que la spec
    les porte à côté de la commande. « options » est vide : aucun ERP n'en
    déclare encore."""
    app, version = choice_for_cmd(cmd)
    return {"app": app, "version": version, "options": {}}


def vm_choice_fields(vm):
    """{"app", "app_version", "app_options"} d'une VM de la spec.

    Déduits de sa propre commande « install_cmd » ; vides quand elle n'en a
    pas, la VM suivant alors le bloc d'installation commun. Préfixés : la
    clé « version » d'une VM est déjà celle de son système.
    """
    if not (vm or {}).get("install_cmd"):
        return {"app": "", "app_version": "", "app_options": {}}
    champs = choice_fields(vm["install_cmd"])
    return {
        "app": champs["app"],
        "app_version": champs["version"],
        "app_options": champs["options"],
    }


def vm_app(vm, install=None):
    """Le descripteur de l'ERP que reçoit la VM `vm` d'une spec.

    La VM qui porte sa propre commande est jugée sur sa clé « app », les
    autres sur celle du bloc `install`. Sans clé « app » — une spec écrite
    avant le sélecteur —, la commande décide, par app_for_cmd : la même
    spec rejouée donne le même ERP.
    """
    vm, install = vm or {}, install or {}
    if vm.get("install_cmd"):
        key, cmd = vm.get("app"), vm["install_cmd"]
    else:
        key, cmd = install.get("app"), install.get("cmd")
    return get(key) if key else app_for_cmd(cmd)


class Choices:
    """Le sélecteur ERP puis Version, bâti sur des profils [(libellé, cmd)].

    Un profil dont la commande est celle d'une version du registre range
    cette version sous son ERP ; les autres profils forment la liste
    d'APP_NONE, dont les valeurs sont leurs commandes. Un ERP n'est offert
    que s'il a au moins une version parmi les profils, APP_NONE que s'il
    reste un profil hors registre. La liste de profils reste la référence :
    le libellé d'un choix est celui de son profil.
    """

    def __init__(self, profiles):
        self.profiles = [tuple(p) for p in profiles or ()]
        par_app = {}
        autres = []
        for label, cmd in self.profiles:
            key, version = choice_for_cmd(cmd)
            if key == APP_NONE:
                autres.append((label, cmd))
            else:
                par_app.setdefault(key, set()).add(version)
        self._options = {}
        self.apps = []
        for app in REGISTRY:
            offertes = par_app.get(app.key)
            if not offertes:
                continue
            self._options[app.key] = [
                (v.label, v.key) for v in app.versions() if v.key in offertes
            ]
            self.apps.append((app.name, app.key))
        if autres:
            self._options[APP_NONE] = autres
            self.apps.append((t("No ERP"), APP_NONE))

    def options(self, app):
        """[(libellé, valeur)] de la liste Version pour `app`."""
        return list(self._options.get(app, ()))

    def default(self, app):
        """La valeur par défaut de la liste Version pour `app` : la version
        « default » de l'ERP quand elle est offerte, sinon la première."""
        valeurs = [v for _l, v in self.options(app)]
        if not valeurs:
            return ""
        if app != APP_NONE:
            prefere = get(app).default_version()
            if prefere in valeurs:
                return prefere
        return valeurs[0]

    def first(self):
        """(ERP, valeur) du choix par défaut : le premier ERP offert et sa
        valeur par défaut ; ("", "") sans profil."""
        if not self.apps:
            return "", ""
        app = self.apps[0][1]
        return app, self.default(app)

    def cmd(self, app, value):
        """La commande du choix (`app`, `value`), "" s'il n'est pas offert."""
        if value not in [v for _l, v in self.options(app)]:
            return ""
        if app == APP_NONE:
            return value
        return get(app).install_cmd_for(value)

    def label_of_cmd(self, cmd):
        """Le libellé du profil de commande `cmd`, "" hors de la liste."""
        return next((lbl for lbl, c in self.profiles if c == cmd), "")

    def of_cmd(self, cmd):
        """(ERP, valeur) qui désigne `cmd` dans ce sélecteur ; first() pour
        une commande qu'il n'offre pas."""
        app, version = choice_for_cmd(cmd)
        value = cmd if app == APP_NONE else version
        if self.cmd(app, value):
            return app, value
        return self.first()


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
        app = vm_app(vm, install)
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
