#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le code de la boite vocale de l'operateur, dans le coffre du CLI.

Le meme coffre que les mots de passe courriel (`script.todo.mail.secrets`) :
le kdbx du depot d'abord, le trousseau systeme a defaut, et jamais un
trousseau qui ecrirait en clair.

Ce module ne rend jamais le code a l'ecran ni dans un journal. Il dit
seulement s'il est defini. Le code ne sort du coffre qu'au moment ou
l'automatisation le compose, et part alors en tonalites sur la ligne.
"""
from __future__ import annotations

#: Entree dans le kdbx : groupe ERPLibre > Modem, titre messagerie-vocale.
REF_KDBX = "kdbx:ERPLibre/Modem/messagerie-vocale"

#: Repli dans le trousseau systeme, quand aucun kdbx n'est configure.
REF_KEYRING = "keyring:modem-messagerie-vocale"

#: Un code de messagerie tient en chiffres. Au-dela de ces bornes, c'est une
#: faute de frappe, et la composer ferait echouer l'authentification.
LONGUEUR_MIN = 4
LONGUEUR_MAX = 10


class CodeInvalide(ValueError):
    """Le code saisi n'a pas la forme d'un code de messagerie."""


def kdbx_configure(todo) -> bool:
    """Un fichier KeePass est-il deja designe dans la configuration ?"""
    config = getattr(todo, "config_file", None)
    return bool(config and config.get_config_value(["kdbx", "path"]))


def coffre(todo):
    """Le coffre du CLI, construit comme pour le courriel.

    Le kdbx n'y entre QUE s'il est configure. Sans chemin, l'ouvrir ferait
    surgir un selecteur de fichier graphique au milieu du terminal ; on passe
    alors au trousseau systeme, qui n'est accepte que s'il chiffre.
    """
    from script.todo.mail.secrets import SecretStore

    manager = getattr(todo, "kdbx_manager", None) if kdbx_configure(todo) else None
    return SecretStore(kdbx_manager=manager, use_keyring=True)


def reference(store) -> str:
    """La reference a utiliser : le kdbx s'il existe, sinon le trousseau.

    Leve `SecretError` quand aucun coffre sur n'est disponible : mieux vaut ne
    pas enregistrer le code que de l'ecrire en clair.
    """
    from script.todo.mail.secrets import SecretError

    disponibles = store.available_backends()
    if "kdbx" in disponibles:
        return REF_KDBX
    if "keyring" in disponibles:
        return REF_KEYRING
    raise SecretError("aucun coffre chiffre disponible pour le code de messagerie")


def valider(code: str) -> str:
    code = (code or "").strip()
    if not code.isdigit():
        raise CodeInvalide("le code ne contient que des chiffres")
    if not LONGUEUR_MIN <= len(code) <= LONGUEUR_MAX:
        raise CodeInvalide(
            "le code compte de %d a %d chiffres" % (LONGUEUR_MIN, LONGUEUR_MAX))
    return code


def lire(store) -> str | None:
    return store.get(reference(store))


def est_defini(store) -> bool:
    try:
        return bool(lire(store))
    except Exception:
        return False


def enregistrer(store, code: str) -> str:
    """Valide puis range le code. Rend la reference utilisee."""
    ref = reference(store)
    store.set(ref, valider(code))
    return ref


def effacer(store) -> None:
    store.delete(reference(store))
