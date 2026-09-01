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


BASE = _base()
STATE_PATH = BASE / "demo.json"
SECRET_PATH = BASE / "hmac.secret"

#: Longueur du secret partagé, en octets avant encodage hexadécimal.
SECRET_BYTES = 32


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


def _ensure_base() -> None:
    BASE.mkdir(parents=True, exist_ok=True)
    # 0700 : le répertoire voisine le secret partagé.
    os.chmod(BASE, 0o700)


def load() -> DemoState:
    """L'état retenu, ou un état neuf si rien n'a encore été fait.

    Un fichier illisible n'est pas une erreur fatale : on repart d'un état
    neuf. Perdre le suivi d'une démonstration jetable coûte moins cher que
    de refuser d'en lancer une.
    """
    try:
        raw = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return DemoState()
    spec_raw = raw.get("spec") or {}
    connus = {f for f in DemoSpec.__dataclass_fields__}
    spec = DemoSpec(**{k: v for k, v in spec_raw.items() if k in connus})
    return DemoState(
        spec=spec,
        done=list(raw.get("done") or []),
        vm_ip=raw.get("vm_ip") or "",
        errors=dict(raw.get("errors") or {}),
        last_uuid=raw.get("last_uuid") or "",
    )


def save(state: DemoState) -> None:
    _ensure_base()
    payload = {
        "spec": state.spec.as_dict(),
        "done": state.done,
        "vm_ip": state.vm_ip,
        "errors": state.errors,
        "last_uuid": state.last_uuid,
    }
    STATE_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ----------------------------------------------------------------------
# Secret partagé
# ----------------------------------------------------------------------


def read_secret() -> str:
    """Le secret de la démonstration, ou une chaîne vide s'il n'existe pas."""
    try:
        return SECRET_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def ensure_secret() -> str:
    """Le secret, créé au premier appel puis stable.

    Il est écrit en 0600 dans `~/.erplibre/sms/`, la même posture que
    l'`EnvironmentFile` recommandé en production : jamais en base, jamais
    dans le dépôt, jamais dans une variable exportée d'un shell interactif
    où l'historique la garderait.
    """
    existant = read_secret()
    if existant:
        return existant
    _ensure_base()
    secret = _secrets.token_hex(SECRET_BYTES)
    # Créer le fichier AVANT d'y écrire, pour qu'il ne soit jamais lisible
    # par autrui, même une fraction de seconde.
    fd = os.open(SECRET_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(secret + "\n")
    return secret


def forget_secret() -> None:
    """Efface le secret. Appelé quand la démonstration repart de zéro."""
    try:
        SECRET_PATH.unlink()
    except OSError:
        pass
