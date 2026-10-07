#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce que la démonstration installe, et ce qu'elle retient d'une fois sur
l'autre.

L'état est persisté parce qu'une démonstration s'étale : créer la VM prend
des minutes, la configurer se fait au clavier, et brancher le téléphone se
fait avec le téléphone en main. Rien ne garantit que tout se joue dans la
même session, et devoir tout reprendre depuis le début parce qu'on a fermé
le terminal serait la meilleure façon de ne jamais s'en servir.
"""
from __future__ import annotations

import json
import os
import secrets as _secrets
from dataclasses import asdict, dataclass, field
from pathlib import Path


def _repo_root() -> Path:
    """La racine du depot, deduite de l'emplacement de ce fichier."""
    return Path(__file__).resolve().parents[3]


def _base() -> Path:
    """Ou vivent l'etat et le secret de la demonstration.

    Dans `private/` du depot, comme le veut la convention du projet : c'est
    la que vont les fichiers propres a une installation. La variable
    d'environnement permet de le deplacer — les tests s'en servent pour ne
    pas ecraser la demonstration de qui les lance.

    ATTENTION : `private/` n'est PAS entierement ignore par git, et le
    distant du depot est public. C'est `private/conf/` qui est ignore dans
    `private/.gitignore` — c'est ce qui empeche le secret HMAC de partir
    dans un commit.
    """
    surcharge = os.environ.get("ERPLIBRE_SMS_DEMO_DIR")
    if surcharge:
        return Path(surcharge)
    return _repo_root() / "private" / "conf" / "sms"


#: Ou Google Repo depose les depots d'addons, un dossier par depot.
DOSSIER_ADDONS = "odoo18.0/addons"


def trouver_module(nom: str):
    """Le chemin du module dans l'un des depots d'addons, ou None.

    On CHERCHE au lieu de composer un chemin. Les addons sont repartis par
    Google Repo en plus de cent depots, et lequel porte un module donne ne se
    devine pas : le supposer designait un dossier ou ce module n'a jamais ete,
    et l'etape s'arretait sur « module introuvable » en montrant un chemin que
    personne ne reconnaissait.
    """
    racine = _repo_root() / DOSSIER_ADDONS
    for depot in sorted(racine.glob("*")):
        chemin = depot / nom
        if chemin.is_dir():
            return chemin
    return None


#: La racine commune aux deux démonstrations. Chacune a son sous-dossier.
BASE = _base()

#: Longueur du secret partagé, en octets avant encodage hexadécimal.
SECRET_BYTES = 32

#: Les deux matériels qui peuvent porter la carte SIM, et le seul endroit
#: qui les énumère.
MATERIELS = ("mobile", "modem")

#: Ce qui doit DIFFÉRER d'un matériel à l'autre pour que les deux
#: démonstrations tiennent sur le même poste en même temps : deux bases, deux
#: ports, deux VM, deux fiches. Partager l'une d'elles ferait que configurer
#: la seconde passerelle déferait la première, sans rien dire.
DEFAUTS_PAR_MATERIEL = {
    "mobile": {},
    "modem": {
        "odoo_port": 8170,
        "db_name": "sms_demo_modem",
        "vm_name": "sms-demo-modem",
        "device_id": "demo-modem-01",
    },
}


def dossier(materiel: str) -> Path:
    """Où vivent l'état et le secret de la démonstration de ce matériel."""
    return BASE / materiel


def chemin_etat(materiel: str) -> Path:
    return dossier(materiel) / "demo.json"


def chemin_secret(materiel: str) -> Path:
    return dossier(materiel) / "hmac.secret"


def spec_par_defaut(materiel: str) -> "DemoSpec":
    """La configuration neuve de ce matériel, ses valeurs propres posées."""
    from dataclasses import replace

    return replace(
        DemoSpec(),
        materiel=materiel,
        **DEFAUTS_PAR_MATERIEL.get(materiel, {}),
    )


@dataclass(frozen=True)
class DemoSpec:
    """La VM de démonstration et ce qu'on y installe.

    Les valeurs par défaut visent une démonstration qui tient sur un poste de
    travail ordinaire, pas une préproduction : 4 Go et 20 Go suffisent à Odoo
    et à PostgreSQL pour quelques centaines d'enregistrements.
    """

    #: "local" — sur le poste courant, sans privilege ni VM. C'est le
    #: DEFAUT : la VM ajoute une heure d'installation, vingt gigaoctets, et
    #: du sudo a chaque interrogation d'adresse. "vm" quand on veut prouver
    #: une installation propre plutot que demontrer la passerelle.
    mode: str = "local"
    #: Le materiel qui porte la carte SIM.
    #:
    #: "mobile" — un telephone Android sous l'application ERPLibre. C'est le
    #: DEFAUT, et la seule voie qui existait. Elle demande le telephone en
    #: main : trois valeurs a saisir a l'ecran, que rien n'automatise.
    #:
    #: "modem"  — un modem USB de ce poste, mene par l'agent de
    #: `script/todo/modem/passerelle.py`. Aucun geste sur un appareil : la
    #: demonstration s'enchaine alors de bout en bout sans intervention.
    materiel: str = "mobile"
    #: Comment le telephone joint Odoo.
    #:
    #: "cable" — renvoi USB `adb reverse`, l'URL reste 127.0.0.1. Rien ne
    #: quitte le cable, donc rien a assouplir. Mais le renvoi saute tout seul.
    #:
    #: "wifi"  — adresse du poste sur le reseau local. Plus stable, et sans
    #: cable ; en revanche numeros et messages circulent EN CLAIR sur le
    #: reseau, ce qui exige d'activer l'exception dans l'application.
    transport: str = "cable"
    vm_name: str = "sms-demo"
    distro: str = "ubuntu"
    version: str = "24.04"
    memory_mb: int = 4096
    disk_gb: int = 20
    #: 8169 et non 8069 : un poste de developpement a presque toujours une
    #: instance sur 8069, et la demonstration ne doit pas la bousculer.
    odoo_port: int = 8169
    db_name: str = "sms_demo"
    #: Doit correspondre EXACTEMENT à ce qui sera saisi dans l'application
    #: mobile : c'est lui qui relie le téléphone à sa fiche dans Odoo. Un
    #: écart ici se manifeste par un 404, pas par un message clair.
    device_id: str = "demo-01"
    module: str = "erplibre_mobile_gateway"
    #: Numero vers lequel partent les essais — SMS comme appels.
    #:
    #: Vide par defaut, et volontairement : envoyer un message ou passer un
    #: appel atteint quelqu'un et coute de l'argent. Le numero doit etre
    #: fourni sciemment, jamais herite d'un exemple qu'on aurait oublie de
    #: changer.
    #:
    #: Format international obligatoire, indicatif compris : +15145550142.
    test_number: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class DemoState:
    """Ce que la démonstration a déjà accompli.

    `done` retient les identifiants d'étapes terminées, pas un simple compteur :
    une étape peut être rejouée seule, et l'ordre d'exécution réel n'est pas
    toujours l'ordre d'affichage.
    """

    spec: DemoSpec = field(default_factory=DemoSpec)
    done: list = field(default_factory=list)
    #: Adresse a laquelle Odoo repond : celle de la VM, ou 127.0.0.1 en
    #: mode local. Le nom reste `vm_ip` pour ne pas invalider les etats deja
    #: ecrits sur disque.
    vm_ip: str = ""
    #: Dernière erreur rencontrée, par étape, pour que le tableau de bord
    #: puisse expliquer un échec sans relire un journal.
    errors: dict = field(default_factory=dict)
    #: Identifiant du dernier envoi d'essai, que l'etape de confirmation
    #: surveille. Sans lui, confirmer reviendrait a regarder « le dernier
    #: envoi », qui n'est pas forcement celui qu'on vient de faire.
    last_uuid: str = ""

    # ------------------------------------------------------------------
    # Étapes
    # ------------------------------------------------------------------

    def mark_done(self, step_id: str) -> None:
        self.errors.pop(step_id, None)
        if step_id not in self.done:
            self.done.append(step_id)

    def mark_failed(self, step_id: str, message: str) -> None:
        # Une étape qui échoue perd son statut de réussite : sans cela, une
        # démonstration rejouée après une panne afficherait encore une coche
        # verte sur l'étape qui vient de casser.
        if step_id in self.done:
            self.done.remove(step_id)
        self.errors[step_id] = str(message)[:2000]

    def is_done(self, step_id: str) -> bool:
        return step_id in self.done

    def reset(self) -> None:
        self.done.clear()
        self.errors.clear()
        self.vm_ip = ""
        self.last_uuid = ""


# ----------------------------------------------------------------------
# Persistance
# ----------------------------------------------------------------------


def _ensure_dossier(materiel: str) -> Path:
    """Crée le dossier de ce matériel en 0700 et le rend."""
    cible = dossier(materiel)
    cible.mkdir(parents=True, exist_ok=True)
    # 0700 : le répertoire voisine le secret partagé.
    os.chmod(cible, 0o700)
    return cible


def _reprendre_etat_unique(materiel: str) -> None:
    """Range un état écrit quand les deux matériels partageaient un dossier.

    L'ancienne disposition gardait `demo.json` et `hmac.secret` à la racine,
    un seul jeu pour les deux matériels. Les laisser là reviendrait à repartir
    de zéro sur une démonstration déjà à moitié faite — VM installée, base
    créée — sans que rien à l'écran n'explique la perte.

    Le fichier part dans le dossier du matériel qu'il DÉCLARE, jamais dans
    celui qu'on demande : un état posé sur le téléphone ne décrit pas la
    passerelle du modem. Le secret le suit, sinon la fiche déjà créée dans
    Odoo refuserait toute requête signée.

    Les valeurs qui IDENTIFIENT l'Odoo — port, base, VM, identifiant
    d'appareil — sont reprises du matériel, parce que l'ancien jeu unique les
    portait pour les deux : les garder mettrait les deux démonstrations sur
    le même port et sous le même identifiant, et la seconde à démarrer
    s'arrêterait sur un port occupé. Ce qu'un serveur avait fait est alors
    oublié : il ne décrivait pas cet Odoo-là.
    """
    ancien = BASE / "demo.json"
    if not ancien.is_file():
        return
    try:
        raw = json.loads(ancien.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    porteur = (raw.get("spec") or {}).get("materiel") or "mobile"
    if porteur not in MATERIELS or chemin_etat(porteur).exists():
        return
    spec_raw = dict(raw.get("spec") or {})
    propres = DEFAUTS_PAR_MATERIEL.get(porteur, {})
    deplace = any(spec_raw.get(k) != v for k, v in propres.items())
    spec_raw.update(propres)
    raw["spec"] = spec_raw
    if deplace:
        # « vm » ne juge que le poste et son venv, qui ne bougent pas.
        raw["done"] = [etape for etape in raw.get("done") or [] if etape == "vm"]
        raw["errors"] = {}
        raw["last_uuid"] = ""
    _ensure_dossier(porteur)
    chemin_etat(porteur).write_text(
        json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    ancien.unlink()
    ancien_secret = BASE / "hmac.secret"
    if ancien_secret.is_file() and not chemin_secret(porteur).exists():
        ancien_secret.replace(chemin_secret(porteur))


def load(materiel: str = "mobile") -> DemoState:
    """L'état retenu pour ce matériel, ou un état neuf.

    Un fichier illisible n'est pas une erreur fatale : on repart d'un état
    neuf. Perdre le suivi d'une démonstration jetable coûte moins cher que
    de refuser d'en lancer une.

    Le matériel demandé l'emporte sur celui qu'un vieux fichier déclare :
    c'est le DOSSIER qui dit de quelle passerelle il s'agit, et une fiche
    jugée sur les critères de l'autre matériel échouerait sans motif lisible.
    """
    _reprendre_etat_unique(materiel)
    defaut = spec_par_defaut(materiel)
    try:
        raw = json.loads(chemin_etat(materiel).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return DemoState(spec=defaut)
    from dataclasses import replace

    spec_raw = raw.get("spec") or {}
    connus = set(DemoSpec.__dataclass_fields__) - {"materiel"}
    spec = replace(
        defaut, **{k: v for k, v in spec_raw.items() if k in connus}
    )
    spec = _rattraper_le_module(spec)
    return DemoState(
        spec=spec,
        done=list(raw.get("done") or []),
        vm_ip=raw.get("vm_ip") or "",
        errors=dict(raw.get("errors") or {}),
        last_uuid=raw.get("last_uuid") or "",
    )


def _rattraper_le_module(spec: DemoSpec) -> DemoSpec:
    """Remplace un nom de module qui n'existe plus par celui d'aujourd'hui.

    Le module a ete renomme ; un etat ecrit avant le renommage designe un
    dossier absent, et chaque etape echoue alors sur « module introuvable ».
    Rien dans l'interface ne permet de corriger ce nom : il faudrait editer un
    JSON dans `private/`, ce que personne ne devinera.

    On ne remplace QUE ce qui est introuvable, et seulement quand le nom par
    defaut existe : un nom volontairement different, mais valide, est laisse
    tel quel.
    """
    from dataclasses import replace

    if trouver_module(spec.module):
        return spec
    defaut = DemoSpec.module
    if spec.module == defaut or not trouver_module(defaut):
        return spec
    return replace(spec, module=defaut)


def save(state: DemoState) -> None:
    """Écrit l'état dans le dossier du matériel qu'il porte."""
    _ensure_dossier(state.spec.materiel)
    payload = {
        "spec": state.spec.as_dict(),
        "done": state.done,
        "vm_ip": state.vm_ip,
        "errors": state.errors,
        "last_uuid": state.last_uuid,
    }
    chemin_etat(state.spec.materiel).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ----------------------------------------------------------------------
# Secret partagé
# ----------------------------------------------------------------------


def read_secret(materiel: str = "mobile") -> str:
    """Le secret de ce matériel, ou une chaîne vide s'il n'existe pas."""
    try:
        return chemin_secret(materiel).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def ensure_secret(materiel: str = "mobile") -> str:
    """Le secret, créé au premier appel puis stable.

    Un secret PAR matériel : les deux démonstrations sont deux Odoo, et
    partager la clé ferait qu'oublier l'une en changerait l'autre.

    Il est écrit en 0600 à côté de l'état, la même posture que
    l'`EnvironmentFile` recommandé en production : jamais en base, jamais
    dans le dépôt, jamais dans une variable exportée d'un shell interactif
    où l'historique la garderait.
    """
    existant = read_secret(materiel)
    if existant:
        return existant
    _ensure_dossier(materiel)
    secret = _secrets.token_hex(SECRET_BYTES)
    # Créer le fichier AVANT d'y écrire, pour qu'il ne soit jamais lisible
    # par autrui, même une fraction de seconde.
    fd = os.open(
        chemin_secret(materiel), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600
    )
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(secret + "\n")
    return secret


def forget_secret(materiel: str = "mobile") -> None:
    """Efface le secret. Appelé quand la démonstration repart de zéro."""
    try:
        chemin_secret(materiel).unlink()
    except OSError:
        pass
