#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Une dérivation de clé rapide à la place d'Argon2, pour les tests KeePass.

Un coffre KeePass 4 dérive sa clé par Argon2, réglé pour coûter environ un
quart de seconde à chaque ouverture et à chaque enregistrement : c'est sa
protection contre la force brute. Un test qui crée, enregistre et rouvre
des coffres paie ce quart de seconde des dizaines de fois, et Argon2
occupait presque toute la durée des fichiers de tests du coffre.

`setUpModule`, importé dans un fichier de tests, remplace pour tout le
module `argon2.low_level.hash_secret_raw` — la fonction qu'appelle pykeepass
— par un SHA-256 des mêmes entrées. La clé dépend toujours du mot de passe,
du sel et des paramètres : un mauvais mot de passe reste refusé, et un
coffre créé dans le test s'y rouvre. Ce que ces tests ne vérifient plus,
c'est la dérivation Argon2 elle-même, qui est l'affaire d'argon2-cffi et de
pykeepass ; `test_argon2_rapide.py` garde un test sur la vraie.

Une exception : le coffre modèle que pykeepass livre, et que
`create_database` ouvre pour bâtir chaque nouveau coffre, a été chiffré par
le vrai Argon2 sous le mot de passe « password ». Sa clé composite est
reconnue et passe par la vraie dérivation, mise en cache : le modèle ne
coûte qu'une dérivation par processus.

Ne convient pas à un test qui ouvre un autre coffre créé AILLEURS — un
fichier versionné, ou écrit par un autre processus : sa clé a été dérivée
par le vrai Argon2.

Sans préfixe `test_`, le lanceur unitaire ne le prend pas pour un fichier
de tests.
"""

import functools
import hashlib
import unittest
from unittest import mock

import argon2.low_level
from pykeepass.kdbx_parsing.common import compute_key_composite
from pykeepass.pykeepass import BLANK_DATABASE_PASSWORD

# Capturée avant tout remplacement : c'est la vraie.
_VRAIE = argon2.low_level.hash_secret_raw
_CLE_DU_MODELE = compute_key_composite(password=BLANK_DATABASE_PASSWORD)


@functools.lru_cache(maxsize=None)
def _vraie_memorisee(
    secret, salt, time_cost, memory_cost, parallelism, hash_len, type, version
):
    return _VRAIE(
        secret=secret,
        salt=salt,
        time_cost=time_cost,
        memory_cost=memory_cost,
        parallelism=parallelism,
        hash_len=hash_len,
        type=type,
        version=version,
    )


def derivation_rapide(
    secret,
    salt,
    time_cost,
    memory_cost,
    parallelism,
    hash_len,
    type,
    version=19,
):
    """Même signature que `argon2.low_level.hash_secret_raw`, en SHA-256.

    Chaque entrée est préfixée de sa longueur : deux découpages différents
    des mêmes octets ne donnent pas la même clé."""
    if bytes(secret) == _CLE_DU_MODELE:
        return _vraie_memorisee(
            bytes(secret),
            bytes(salt),
            time_cost,
            memory_cost,
            parallelism,
            hash_len,
            type,
            version,
        )
    empreinte = hashlib.sha256()
    parametres = repr(
        # Le type est une énumération d'argon2-cffi : son nom le distingue.
        (
            time_cost,
            memory_cost,
            parallelism,
            getattr(type, "name", type),
            version,
        )
    )
    for partie in (bytes(secret), bytes(salt), parametres.encode()):
        empreinte.update(len(partie).to_bytes(8, "big"))
        empreinte.update(partie)
    cle = empreinte.digest()
    return (cle * (hash_len // len(cle) + 1))[:hash_len]


def setUpModule():
    patch = mock.patch("argon2.low_level.hash_secret_raw", derivation_rapide)
    patch.start()
    unittest.addModuleCleanup(patch.stop)
