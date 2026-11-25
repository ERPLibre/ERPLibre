#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Accès web d'une VM de production : nginx devant l'ERP, ou rien.

Une VM installée en production s'ouvre par l'un des modes de MODES. Les
trois premiers posent nginx dans l'invité, devant l'ERP qui écoute toujours
sur son port ; DIRECT n'en pose aucun, et le navigateur joint l'ERP sur ce
port. Chaque ErpApp déclare les modes qu'il sait servir (access_modes) ; la
clé d'un mode est ce que la spec porte dans « access », à côté de « prod ».

Une spec de production sans clé « access », écrite avant ce choix, vaut
DIRECT : rejouée, elle donne la même VM qu'avant. Le défaut d'un nouveau
choix est DEFAULT.

Module feuille, sans import du registre : le registre l'importe pour
juger une spec (script.todo.qemu_erp.access_refusals).
"""

import re
from dataclasses import dataclass
from typing import Optional

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - i18n absent hors du TUI

    def t(key):
        return key


SELF_SIGNED = "selfsigned"
HTTP = "http"
LETSENCRYPT = "letsencrypt"
DIRECT = "direct"
DEFAULT = SELF_SIGNED

# Raison du refus d'un mode nginx sur NixOS (clé i18n).
NIXOS_REFUSAL = (
    "NixOS: /etc is read-only, nginx is not configured there; choose"
    " Direct :8069."
)


@dataclass(frozen=True)
class AccessMode:
    """Un mode d'accès web, et ce que le suivi en tire pour ouvrir la page.

    `label` est une clé i18n. `port` est celui où écoute nginx dans
    l'invité, None pour DIRECT, qui prend le port de l'ERP ; `tunnel_port`
    le port local du tunnel ssh qui y mène depuis l'hôte, quand la VM vit
    derrière un hôte Proxmox. `needs_domain` : la page se joint par le
    domaine saisi, et non par l'adresse de la VM, qui ne figure pas dans
    son certificat.
    """

    key: str
    label: str
    scheme: str
    port: Optional[int]
    tunnel_port: Optional[int]
    nginx: bool
    needs_domain: bool = False


# Ordre d'affichage du champ « Accès web » ; le premier est DEFAULT.
MODES = (
    AccessMode(SELF_SIGNED, "HTTPS self-signed", "https", 443, 18443, True),
    AccessMode(
        HTTP, "HTTP (TLS terminated elsewhere)", "http", 80, 18480, True
    ),
    AccessMode(
        LETSENCRYPT,
        "Let's Encrypt",
        "https",
        443,
        18443,
        True,
        needs_domain=True,
    ),
    AccessMode(DIRECT, "Direct :8069, no nginx", "http", None, None, False),
)
ALL_KEYS = tuple(m.key for m in MODES)

# Un nom DNS pleinement qualifié : des étiquettes de 1 à 63 caractères,
# alphanumériques et tirets non terminaux, et une étiquette finale
# alphabétique. Let's Encrypt n'émet pas pour un nom sans point ni pour une
# adresse.
_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$",
    re.IGNORECASE,
)
# Partie locale d'un courriel : un jeu de caractères sans métacaractère du
# shell. L'adresse traverse ssh puis la ligne de commande de certbot dans
# l'invité ; « $( », « ; » ou une apostrophe n'y passent pas. Le domaine
# qui suit « @ » répond à _DOMAIN_RE.
_EMAIL_LOCAL_RE = re.compile(r"^[A-Za-z0-9._%+-]{1,64}$")


def get(key):
    """L'AccessMode de clé `key`, ou None."""
    return next((m for m in MODES if m.key == key), None)


def modes_for(keys):
    """Les AccessMode de `keys`, dans l'ordre de MODES."""
    return tuple(m for m in MODES if m.key in (keys or ()))


def fields(install):
    """{"access", "domain", "email"} du bloc d'installation `install`.

    Sans production, ou sans clé « access » (une spec écrite avant ce
    choix), le mode vaut DIRECT. Le domaine et le courriel ne sont lus que
    pour un mode qui les demande ; ailleurs ils valent "".
    """
    install = install or {}
    mode = (install.get("access") or DIRECT) if install.get("prod") else DIRECT
    m = get(mode)
    besoin = bool(m and m.needs_domain)
    return {
        "access": mode,
        "domain": (install.get("domain") or "").strip() if besoin else "",
        "email": (install.get("email") or "").strip() if besoin else "",
    }


def domain_error(domain):
    """La raison traduite de refuser `domain` pour Let's Encrypt, ou ""."""
    domain = (domain or "").strip()
    if not domain:
        return t("Let's Encrypt needs a domain.")
    if not _DOMAIN_RE.match(domain):
        return t("Let's Encrypt: invalid domain: %s") % domain
    return ""


def email_error(email):
    """La raison traduite de refuser `email` pour Let's Encrypt, ou ""."""
    email = (email or "").strip()
    if not email:
        return t("Let's Encrypt needs an admin email.")
    local, _, dom = email.rpartition("@")
    if not _EMAIL_LOCAL_RE.match(local) or not _DOMAIN_RE.match(dom):
        return t("Let's Encrypt: invalid admin email: %s") % email
    return ""


def web_target(mode, ip, domain="", tunnel=None):
    """(argv du tunnel ou None, URL) de la page servie par nginx en `mode`.

    `tunnel(local, cible)` rend l'argv d'un tunnel ssh du port local
    `local` vers le port `cible` de la VM, ou None quand la VM est joignable
    d'ici. Un mode needs_domain s'ouvre toujours par https://<domain>/ :
    le certificat ne porte que ce nom. Rend None pour un mode inconnu ou
    sans nginx ; l'appelant garde alors l'accès direct.
    """
    m = get(mode)
    if m is None or not m.nginx:
        return None
    if m.needs_domain:
        return None, f"{m.scheme}://{domain}/"
    argv = tunnel(m.tunnel_port, m.port) if tunnel else None
    if argv:
        return argv, f"{m.scheme}://127.0.0.1:{m.tunnel_port}/"
    return None, f"{m.scheme}://{ip}/"
