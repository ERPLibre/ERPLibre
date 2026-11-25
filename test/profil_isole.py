#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Isole les profils de production d'un module de tests.

`profil_isole()`, appelé dans le `setUpModule` d'un module de tests, arme
la couture `profil.RACINE_PROFILS` sur un dossier temporaire et pose une
garde : un `os.open`, un `os.mkdir` ou un `open()` intégré (`io.open`, qui
ne passe pas par `os.open`) qui vise le vrai `<RACINE>/private/production`
lève AssertionError avant de toucher quoi que ce soit. Une lecture, ou la
réécriture d'un fichier existant, ne change ni le mtime ni les noms du
dossier : seule la garde les arrête. À la fin du module, la couture est
rendue, le dossier temporaire retiré, et l'état du vrai dossier
(existence, mtime, contenu) comparé à celui du début : un écart fait
échouer le module.

Sans préfixe `test_`, le lanceur unitaire ne le prend pas pour un fichier
de tests.
"""

import builtins
import io
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.lib_ops import profil  # noqa: E402

VRAI_DOSSIER = os.path.join(profil.RACINE, "private", "production")


def etat(dossier=VRAI_DOSSIER):
    """(existe, mtime_ns, noms triés) du dossier, sans l'ouvrir par
    `os.open`."""
    try:
        info = os.stat(dossier)
    except FileNotFoundError:
        return (False, None, ())
    try:
        noms = tuple(sorted(os.listdir(dossier)))
    except OSError:
        noms = None
    return (True, info.st_mtime_ns, noms)


def vise_le_vrai_dossier(chemin, dossier=VRAI_DOSSIER):
    """True si `chemin` est le vrai dossier des profils ou l'un de ses
    descendants."""
    try:
        chemin = os.fsdecode(os.fspath(chemin))
    except TypeError:
        return False
    interdit = os.path.realpath(dossier)
    resolu = os.path.realpath(os.path.abspath(chemin))
    return resolu == interdit or resolu.startswith(interdit + os.sep)


def garder(fonction, dossier=VRAI_DOSSIER):
    """`fonction` (os.open, os.mkdir, open) précédée de la garde. Un
    descripteur entier, que `open()` accepte aussi, ne vise aucun
    chemin et passe."""

    def gardee(chemin, *args, **kwargs):
        if kwargs.get("dir_fd") is None and vise_le_vrai_dossier(
            chemin, dossier
        ):
            raise AssertionError(
                f"a test touches the real profiles directory: {chemin}"
            )
        return fonction(chemin, *args, **kwargs)

    return gardee


def profil_isole():
    """Arme la couture et la garde pour le module de tests en cours ; rend
    le dossier temporaire des profils."""
    temporaire = tempfile.TemporaryDirectory(prefix="erplibre-profil-")
    ancien = profil.RACINE_PROFILS
    avant = etat()
    ouvrir = garder(builtins.open)
    patchs = [
        mock.patch("os.open", garder(os.open)),
        mock.patch("os.mkdir", garder(os.mkdir)),
        mock.patch.object(builtins, "open", ouvrir),
        mock.patch.object(io, "open", ouvrir),
    ]
    for patch in patchs:
        patch.start()
    profil.RACINE_PROFILS = temporaire.name

    def fin():
        for patch in reversed(patchs):
            patch.stop()
        profil.RACINE_PROFILS = ancien
        temporaire.cleanup()
        apres = etat()
        if apres != avant:
            raise AssertionError(
                f"the real profiles directory changed: {avant} -> {apres}"
            )

    unittest.addModuleCleanup(fin)
    return temporaire.name
