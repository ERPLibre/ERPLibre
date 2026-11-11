#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Écarts entre le venv d'Odoo et son poetry.lock.

Ce que le lock DEVRAIT donner n'est pas recalculé ici : c'est Poetry qui le
dit, par « poetry sync --dry-run ». Lui seul évalue les marqueurs de
plateforme, les extras et les groupes ; comparer « pip list » au lock à la
main prendrait pour manquant un paquet réservé à Windows, ou pour superflu
une dépendance d'un extra. Ce module lance la simulation, lit ses
opérations, relève les versions installées, et compare deux relevés pour le
rapport d'une mise à jour. L'affichage, et sa traduction, restent au menu.

Les opérations de Poetry se classent ainsi :

    Installing   le lock l'exige, le venv ne l'a pas
    Updating     installé, mais plus ancien que le lock
    Downgrading  installé, mais plus récent que le lock
    Removing     installé, absent du lock — Poetry lui-même, pip-audit,
                 un paquet ajouté à la main. « poetry install », que lance
                 la mise à jour, n'y touche pas : c'est une information,
                 pas un écart à corriger.
"""

import contextlib
import datetime
import glob
import json
import os
import re
import shlex
import subprocess
import tempfile

# Une opération par ligne : « - Updating six (1.16.0 -> 1.17.0) ». Ancrée
# en fin de ligne : en simulation, Poetry imprime aussi chaque opération
# SAUTÉE — « - Installing pip (26.2.2): Skipped for the following reason:
# Already installed » pour tout paquet déjà à la version du lock, « Not
# required » pour un extra non demandé. Lue comme une installation, elle
# ferait de chaque paquet à jour un paquet manquant.
RE_OPERATION = re.compile(
    r"^\s*-\s+(Installing|Updating|Downgrading|Removing)\s+(\S+)"
    r"\s+\(([^()]*)\)\s*$"
)

# Les exigences du venv de l'outillage, qui n'a pas de lock.
EXIGENCES_OUTILLAGE = "requirement/erplibre_require-ments.txt"

# Les trois premières sont des écarts : la mise à jour les corrige.
ECARTS = ("Installing", "Updating", "Downgrading")

# Le relevé des versions passe par importlib.metadata et non par pip : pip
# peut manquer, ou ne plus démarrer, dans un venv dont on cherche justement
# ce qui cloche.
RELEVE = (
    "import importlib.metadata as m, json\n"
    "print(json.dumps({d.metadata['Name']: d.version"
    " for d in m.distributions() if d.metadata['Name']}))\n"
)


def normaliser(nom):
    """Nom de distribution comparable (PEP 503)."""
    return re.sub(r"[-_.]+", "-", nom).lower()


def lire_operations(sortie):
    """Les opérations d'une sortie de Poetry, dans l'ordre où il les donne.

    Chaque opération : {"action", "nom", "avant", "apres"}. « avant » est la
    version installée (None pour une installation), « apres » celle du lock
    (None pour un retrait).
    """
    operations = []
    for ligne in sortie.splitlines():
        trouve = RE_OPERATION.match(ligne)
        if not trouve:
            continue
        action, nom, versions = trouve.groups()
        if "->" in versions:
            avant, apres = (v.strip() for v in versions.split("->", 1))
        elif action == "Installing":
            avant, apres = None, versions.strip()
        else:
            avant, apres = versions.strip(), None
        operations.append(
            {"action": action, "nom": nom, "avant": avant, "apres": apres}
        )
    return operations


def chemins(version_erplibre):
    """Les fichiers en jeu pour une version d'ERPLibre, relatifs à la racine
    du dépôt."""
    return {
        "venv": f".venv.{version_erplibre}",
        "poetry": f".venv.{version_erplibre}/bin/poetry",
        "python": f".venv.{version_erplibre}/bin/python",
        "lock": f"requirement/poetry.{version_erplibre}.lock",
        "pyproject": f"requirement/pyproject.{version_erplibre}.toml",
        "lien_lock": "poetry.lock",
        "lien_pyproject": "pyproject.toml",
    }


def environnement(racine, venv):
    """L'environnement de Poetry : le venv d'Odoo ACTIVÉ.

    poetry.toml porte « virtualenvs.create = false » : sans VIRTUAL_ENV,
    Poetry compare le lock à l'interpréteur de BASE, pas au venv. Le
    trousseau est coupé, comme dans install_locally.sh : sans bureau, il
    bloque Poetry sur une invite que personne ne voit.
    """
    chemin_venv = os.path.join(racine, venv)
    env = dict(os.environ)
    env["VIRTUAL_ENV"] = chemin_venv
    env["PATH"] = (
        os.path.join(chemin_venv, "bin") + os.pathsep + env.get("PATH", "")
    )
    env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
    env.pop("PYTHONHOME", None)
    return env


def venvs(racine, active=None):
    """Les venvs du checkout que la comparaison sait lire, actif d'abord.

    Rend [{"venv", "genre", "version", "active"}] : « genre » vaut
    « odoo » pour un `.venv.odoo*`, comparé à son
    requirement/poetry.<version>.lock, ou « outillage » pour le venv des
    outils (conf/python-erplibre-venv), comparé à
    requirement/erplibre_require-ments.txt. Un dossier sans interpréteur
    n'est pas un venv utilisable et n'est pas rendu."""
    rendus = []
    for dossier in sorted(glob.glob(os.path.join(racine, ".venv.odoo*"))):
        if not os.path.isfile(os.path.join(dossier, "bin", "python")):
            continue
        version = os.path.basename(dossier).removeprefix(".venv.")
        rendus.append(
            {
                "venv": f".venv.{version}",
                "genre": "odoo",
                "version": version,
                "active": version == active,
            }
        )
    rendus.sort(key=lambda v: not v["active"])
    try:
        with open(os.path.join(racine, "conf", "python-erplibre-venv")) as fh:
            outillage = fh.read().strip()
    except OSError:
        outillage = ""
    if outillage and os.path.isfile(
        os.path.join(racine, outillage, "bin", "python")
    ):
        rendus.append(
            {
                "venv": outillage,
                "genre": "outillage",
                "version": None,
                "active": False,
            }
        )
    return rendus


@contextlib.contextmanager
def projet_temporaire(racine, version_erplibre):
    """Un dossier de projet Poetry pour une version qui n'est pas l'active.

    Poetry lit pyproject.toml, poetry.lock et poetry.toml dans son dossier
    courant ; ceux de la racine sont les liens de la version ACTIVE. Ce
    dossier porte des liens vers le pyproject et le lock de
    `version_erplibre`, et vers le poetry.toml de la racine : la version
    active et ses liens ne bougent pas. Le dossier disparaît à la sortie."""
    c = chemins(version_erplibre)
    with tempfile.TemporaryDirectory(prefix="el_poetry_") as dossier:
        for lien, cible in (
            ("pyproject.toml", c["pyproject"]),
            ("poetry.lock", c["lock"]),
            ("poetry.toml", "poetry.toml"),
        ):
            source = os.path.abspath(os.path.join(racine, cible))
            if os.path.exists(source):
                os.symlink(source, os.path.join(dossier, lien))
        yield dossier


def commande_installation(racine, version_erplibre, projet):
    """La commande shell qui installe le lock de `version_erplibre` dans
    son venv depuis `projet` (voir `projet_temporaire`), le venv activé
    comme pour `simuler`. « install » et non « sync » : un paquet hors du
    lock — Poetry lui-même en premier — reste en place."""
    c = chemins(version_erplibre)
    venv = os.path.abspath(os.path.join(racine, c["venv"]))
    poetry = os.path.join(venv, "bin", "poetry")
    return (
        f"cd {shlex.quote(projet)}"
        f" && VIRTUAL_ENV={shlex.quote(venv)}"
        f' PATH={shlex.quote(os.path.join(venv, "bin"))}:"$PATH"'
        " PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring"
        f" {shlex.quote(poetry)} install --no-root"
    )


def simuler(racine, version_erplibre, executer=subprocess.run, projet=None):
    """Demande à Poetry ce que l'installation du lock changerait.

    Rend {"ok", "operations", "sortie", "commande"}. « ok » est faux quand
    Poetry refuse — Python du venv hors des bornes du projet, lock
    désaccordé du pyproject — et « sortie » dit alors pourquoi. Rien n'est
    installé : seule la simulation tourne. Poetry tourne dans `projet`
    quand il est donné (voir `projet_temporaire`), sinon à la racine.
    """
    c = chemins(version_erplibre)
    env = environnement(racine, c["venv"])
    poetry = os.path.join(racine, c["poetry"])
    commande = [poetry, "sync", "--dry-run", "--no-root", "--no-ansi"]
    dossier = projet or racine
    fini = executer(
        commande, cwd=dossier, env=env, capture_output=True, text=True
    )
    sortie = (fini.stdout or "") + (fini.stderr or "")
    # Poetry 1 n'a pas « sync » : son équivalent est « install --sync ».
    if fini.returncode and '"sync" does not exist' in sortie:
        commande = [
            poetry,
            "install",
            "--sync",
            "--dry-run",
            "--no-root",
            "--no-ansi",
        ]
        fini = executer(
            commande, cwd=dossier, env=env, capture_output=True, text=True
        )
        sortie = (fini.stdout or "") + (fini.stderr or "")
    return {
        "ok": fini.returncode == 0,
        "operations": lire_operations(sortie) if not fini.returncode else [],
        "sortie": sortie,
        "commande": " ".join(commande),
    }


def classer(operations):
    """Les opérations rangées par action, dans l'ordre de ECARTS puis
    Removing ; une action sans opération est absente."""
    classes = {}
    for action in ECARTS + ("Removing",):
        trouvees = [op for op in operations if op["action"] == action]
        if trouvees:
            classes[action] = trouvees
    return classes


def a_des_ecarts(operations):
    """Vrai si le venv diverge du lock : un paquet manque ou n'a pas la
    version du lock. Les paquets hors du lock n'en sont pas."""
    return any(op["action"] in ECARTS for op in operations)


def relever(racine, version_erplibre, executer=subprocess.run):
    """Les versions installées dans le venv, {nom normalisé: (nom, version)}.

    Rend {} si l'interpréteur du venv ne répond pas : le rapport le dira
    plutôt que d'inventer un état.
    """
    python = os.path.join(racine, chemins(version_erplibre)["python"])
    fini = executer(
        [python, "-c", RELEVE], cwd=racine, capture_output=True, text=True
    )
    if fini.returncode:
        return {}
    try:
        brut = json.loads(fini.stdout or "{}")
    except ValueError:
        return {}
    return {normaliser(nom): (nom, version) for nom, version in brut.items()}


def comparer(avant, apres):
    """Ce qui a changé entre deux relevés, pour le rapport de mise à jour.

    Rend {"changes": [(nom, avant, apres)], "ajoutes": [(nom, version)],
    "retires": [(nom, version)]}, chaque liste triée par nom.
    """
    changes, ajoutes, retires = [], [], []
    for cle in sorted(set(avant) | set(apres)):
        if cle in avant and cle in apres:
            if avant[cle][1] != apres[cle][1]:
                changes.append((apres[cle][0], avant[cle][1], apres[cle][1]))
        elif cle in apres:
            ajoutes.append(apres[cle])
        else:
            retires.append(avant[cle])
    return {"changes": changes, "ajoutes": ajoutes, "retires": retires}


def dossier_rapports():
    """Où les rapports de mise à jour sont écrits : un cache, hors du dépôt."""
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, "erplibre_poetry")


def ecrire_rapport(texte, version_erplibre, maintenant=None):
    """Écrit le rapport et rend son chemin. Le nom porte la version et
    l'heure : deux mises à jour ne s'écrasent pas."""
    maintenant = maintenant or datetime.datetime.now()
    dossier = dossier_rapports()
    os.makedirs(dossier, exist_ok=True)
    chemin = os.path.join(
        dossier,
        f"{version_erplibre}_{maintenant.strftime('%Y%m%d_%H%M%S')}.md",
    )
    with open(chemin, "w", encoding="utf-8") as fichier:
        fichier.write(texte)
    return chemin
