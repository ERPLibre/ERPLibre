#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les secrets VPN, dans le coffre KeePassXC.

Nommé `vault` et non `secrets` : `secrets` est un module de la bibliothèque
standard, et masquer un nom de la stdlib dans un paquet importé partout se
paie tôt ou tard.

Une entrée par profil, dans le groupe « ERPLibre VPN », titrée
« ERPLibre VPN / <profil> » :

    username / password   les identifiants PPP (MS-CHAPv2)
    propriété « psk »     la clé pré-partagée IPsec, PROTÉGÉE

« Protégée » veut dire chiffrée en mémoire par KeePassXC et masquée dans son
interface — c'est le même traitement que le champ mot de passe, appliqué à un
champ personnalisé.

Ce module ne fait QUE lire et écrire. Il ne choisit jamais de créer un coffre
tout seul : `ensure_vault` demande, et une réponse vide fait renoncer. Un
outil qui crée silencieusement un fichier de mots de passe dans un répertoire
qu'on n'a pas choisi est un outil qu'on n'ose plus lancer.
"""
from __future__ import annotations

import getpass
import os
import stat

from script.todo.todo_i18n import t

try:
    from pykeepass import PyKeePass, create_database
except ModuleNotFoundError:  # pragma: no cover - dépend de l'installation
    PyKeePass = None
    create_database = None

# Groupe où les entrées sont rangées, pour que le coffre reste lisible dans
# l'interface KeePassXC. Le TITRE reste unique globalement : les autres
# lecteurs du dépôt (kdbx_config) cherchent par titre, sans notion de groupe.
VAULT_GROUP = "ERPLibre VPN"

# Champ secret par défaut : celui de tous les pilotes à clé pré-partagée.
FIELD_PSK = "psk"

MASK = "********"

# Ce qui tient la place d'un secret que le coffre n'a pas rendu, en mode à
# blanc : montrer un plan ne justifie pas d'exiger le mot de passe maître.
#
# Une CONSTANTE partagée, et non une chaîne écrite à deux endroits : un
# pilote qui juge un secret — sa longueur, sa forme — doit pouvoir
# reconnaître le marqueur et se taire, sinon le plan à blanc porte un
# verdict sur une valeur qui n'est pas celle de l'utilisateur.
PLACEHOLDER = "<secret-du-coffre>"

# Le menu a déjà le coffre ouvert quand il lance `vpn.py` : il lui passe les
# secrets par l'ENVIRONNEMENT plutôt que de le faire redemander le mot de
# passe maître — deux fois par connexion, puisqu'un essai à blanc précède le
# vrai montage.
#
# Par l'environnement et non par un argument : /proc/<pid>/environ n'est
# lisible que par le propriétaire du processus, /proc/<pid>/cmdline par tout
# utilisateur de la machine. Et `sudo` remet l'environnement à zéro, donc ces
# variables n'atteignent aucune commande privilégiée : les secrets qui vont à
# root passent, eux, par l'entrée standard.
ENV_MARKER = "EL_VPN_SECRETS_PROVIDED"
ENV_PREFIX = "EL_VPN_SECRET_"


def secrets_to_env(values: dict) -> dict:
    """Variables d'environnement portant `values`, marqueur compris."""
    env = {ENV_MARKER: "1"}
    for key, value in values.items():
        env[f"{ENV_PREFIX}{key.upper()}"] = value or ""
    return env


def secrets_from_env(fields) -> dict | None:
    """Secrets déposés par le processus appelant, ou None s'il n'y en a pas.

    Le marqueur est explicite : sans lui, un champ vide serait indistinguable
    d'un champ absent, et on rouvrirait le coffre pour rien.
    """
    if os.environ.get(ENV_MARKER) != "1":
        return None
    return {
        field: os.environ.get(f"{ENV_PREFIX}{field.upper()}", "")
        for field in fields
    }


# Dit quand on trouve le coffre plus ouvert qu'il ne devrait : ce n'est pas
# nous qui l'avons laissé ainsi, et ça mérite d'être su.
LOOSE_VAULT_TIGHTENED = (
    "Vault permissions tightened to 0600, it was readable by others: "
)


class VaultError(RuntimeError):
    """Le coffre n'a pas pu être ouvert ou écrit. Message pour l'humain."""


class VpnVault:
    """Pont entre les profils VPN et le coffre .kdbx.

    Prend le `ConfigFile` et le `KdbxManager` déjà construits par le CLI
    TODO : le mot de passe maître n'est demandé qu'une fois par session,
    et il n'y a pas deux caches de coffre qui pourraient diverger.
    """

    def __init__(self, config_file, kdbx_manager):
        self._config = config_file
        self._manager = kdbx_manager

    # ------------------------------------------------------------------
    # Le fichier de coffre
    # ------------------------------------------------------------------
    def vault_path(self) -> str:
        """Chemin configuré du coffre, "" s'il n'y en a pas."""
        kdbx = self._config.get_config("kdbx")
        if not isinstance(kdbx, dict):
            return ""
        return str(kdbx.get("path") or "").strip()

    def master_password_is_stored(self) -> bool:
        """Vrai si un mot de passe maître dort dans la configuration.

        C'est légal — `KdbxManager` le lit — mais c'est un mot de passe
        maître en clair sur le disque : le CLI doit pouvoir le SIGNALER.
        """
        kdbx = self._config.get_config("kdbx")
        return bool(isinstance(kdbx, dict) and kdbx.get("password"))

    def ensure_vault(self, ask=input, default_path=None) -> str:
        """Chemin d'un coffre utilisable, "" si l'utilisateur renonce.

        Trois cas : déjà configuré et présent (rien à faire) ; configuré
        mais absent (on propose de le créer) ; pas configuré (on demande
        où, puis on crée si le fichier n'existe pas).
        """
        if create_database is None:
            raise VaultError(
                "pykeepass n'est pas installé : lancer l'installation"
                " ERPLibre, ou `pip install pykeepass` dans"
                " .venv.erplibre."
            )
        path = self.vault_path()
        if path and os.path.exists(os.path.expanduser(path)):
            return path

        if not path:
            default_path = default_path or os.path.expanduser(
                "~/.erplibre/secrets.kdbx"
            )
            answer = ask(f"Chemin du coffre KeePassXC [{default_path}] : ")
            path = (answer or "").strip() or default_path

        path = os.path.expanduser(path)
        if not os.path.exists(path):
            answer = ask(f"Créer le coffre « {path} » ? [o/N] : ")
            if (answer or "").strip().lower() not in ("o", "oui", "y", "yes"):
                return ""
            self._create(path)
        self._config.set_config_value(["kdbx", "path"], path)
        return path

    def _create(self, path: str) -> None:
        """Crée un coffre vide en 0600, mot de passe saisi deux fois."""
        parent = os.path.dirname(path) or "."
        os.makedirs(parent, exist_ok=True)
        first = getpass.getpass("Mot de passe maître du coffre : ")
        if not first:
            raise VaultError("Mot de passe vide : coffre non créé.")
        if first != getpass.getpass("Confirmer : "):
            raise VaultError("Les deux saisies diffèrent : coffre non créé.")
        # Créé puis restreint : `create_database` ne prend pas de mode, et
        # un coffre lisible par tout le monde le reste jusqu'au chmod. La
        # fenêtre existe, elle est d'un tour de boucle ; l'alternative
        # serait de créer le fichier vide en 0600 d'abord, ce que
        # pykeepass refuse (il veut écrire un fichier neuf).
        kdbx = create_database(path, password=first)
        self.protect(path)
        # La base rendue par `create_database` est déjà ouverte : la confier
        # au gestionnaire évite une troisième saisie du mot de passe maître,
        # juste après les deux de la création.
        self._manager.adopt(kdbx)

    def protect(self, path=None) -> bool:
        """Remet le coffre en 0600. Rend True s'il fallait le resserrer.

        À appeler après CHAQUE écriture, et pas seulement à la création :
        `PyKeePass.save()` réécrit le fichier et lui redonne le mode du
        umask — 0664 sur Ubuntu. Un chmod fait une fois à la création ne
        survit donc pas au premier enregistrement, et un coffre de mots de
        passe devient lisible par toute la machine sans que personne ne
        touche à rien.
        """
        path = os.path.expanduser(path or self.vault_path())
        if not path:
            return False
        try:
            current = stat.S_IMODE(os.stat(path).st_mode)
        except OSError:
            return False
        if not current & 0o077:
            return False
        os.chmod(path, 0o600)
        return True

    def _open(self):
        """Coffre ouvert, ou VaultError. Passe par KdbxManager pour ne
        demander le mot de passe maître qu'une fois par session."""
        if not self.vault_path():
            # Court-circuit VOULU : sans chemin, `KdbxManager` ouvre un
            # sélecteur de fichiers graphique — et sur un serveur sans
            # tkinter, il journalise une erreur au lieu de dire ce qui
            # manque. Ici on le dit.
            raise VaultError(
                "Aucun coffre KeePassXC configuré. Le créer depuis TODO ›"
                " Execute › Déploiement › VPN › « Déposer les secrets »."
            )
        if self.protect():
            print(f"! {t(LOOSE_VAULT_TIGHTENED)}{self.vault_path()}")
        kdbx = self._manager.get_kdbx()
        if kdbx is None:
            raise VaultError(
                "Coffre KeePassXC indisponible : chemin non configuré, ou"
                " mot de passe refusé."
            )
        return kdbx

    # ------------------------------------------------------------------
    # Lecture / écriture d'un profil
    # ------------------------------------------------------------------
    def read(self, title: str, fields=(FIELD_PSK,)) -> dict:
        """{"username", "password", <champs>} pour l'entrée `title`.

        Une entrée absente rend un dictionnaire de chaînes vides plutôt
        qu'une exception : « pas encore de secret » est un état NORMAL,
        que l'appelant affiche (`[5] Déposer les secrets`) au lieu de le
        traiter comme une panne.
        """
        empty = {"username": "", "password": ""}
        empty.update({f: "" for f in fields})
        kdbx = self._open()
        entry = kdbx.find_entries_by_title(title, first=True)
        if entry is None:
            return empty
        values = {
            "username": entry.username or "",
            "password": entry.password or "",
        }
        for field in fields:
            # `username` et `password` sont des champs NATIFS de KeePassXC :
            # les chercher parmi les propriétés personnalisées les
            # écraserait par du vide. Un pilote peut légitimement déclarer
            # `password` dans ses `secret_fields`.
            if field in ("username", "password"):
                continue
            values[field] = entry.get_custom_property(field) or ""
        return values

    def write(self, title: str, values: dict) -> None:
        """Crée ou met à jour l'entrée `title`.

        Seules les clés PRÉSENTES dans `values` sont touchées : le menu
        laisse passer un champ pour le garder tel quel. Une chaîne vide,
        elle, efface — c'est une décision, pas un oubli.
        """
        kdbx = self._open()
        entry = kdbx.find_entries_by_title(title, first=True)
        if entry is None:
            entry = kdbx.add_entry(
                self._group(kdbx),
                title,
                values.get("username", ""),
                values.get("password", ""),
            )
        else:
            if "username" in values:
                entry.username = values["username"]
            if "password" in values:
                entry.password = values["password"]
        for field, value in values.items():
            if field in ("username", "password"):
                continue
            entry.set_custom_property(field, value or "", protect=True)
        kdbx.save()
        # Sans ceci, l'enregistrement qu'on vient de faire aurait rendu le
        # coffre lisible par toute la machine.
        self.protect()

    def _group(self, kdbx):
        group = kdbx.find_groups(name=VAULT_GROUP, first=True)
        if group is None:
            group = kdbx.add_group(kdbx.root_group, VAULT_GROUP)
        return group

    def exists(self, title: str) -> bool:
        return (
            self._open().find_entries_by_title(title, first=True) is not None
        )


def redact(text: str, values) -> str:
    """`text` avec chaque secret remplacé par des astérisques.

    Les plus longs d'abord : masquer « ab » avant « abcdef » laisserait la
    fin de « abcdef » en clair. Les secrets de moins de quatre caractères
    sont masqués aussi — un tel secret n'existe pas en pratique, et
    préférer le faux positif au secret imprimé est le bon arbitrage.
    """
    if not text:
        return text
    if isinstance(values, dict):
        values = values.values()
    for secret in sorted({str(v) for v in values if v}, key=len, reverse=True):
        text = text.replace(secret, MASK)
    return text
