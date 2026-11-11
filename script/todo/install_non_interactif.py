#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Réponses du menu Installation de TODO données d'avance.

« ./todo.sh install » prend ses réponses dans ses options ou, à défaut, dans
l'environnement ; une option l'emporte sur sa variable. Ce qui n'est pas
fourni est demandé comme dans le menu, sauf en mode non interactif
(--non-interactive ou EL_NON_INTERACTIVE=1) : là, une réponse délibérée qui
manque arrête l'installation avant qu'elle commence, en nommant l'option et
la variable qui la donnent. Aucune n'a de défaut : la version d'Odoo,
l'environnement, le type, l'étape système et la pose de mise engagent la
machine.

L'identité git est facultative : sans EL_GIT_NAME et EL_GIT_EMAIL, repo init
tourne sans en demander (script/manifest/repo_init.sh).

preparer() rend le dictionnaire des réponses, aux clés :
- « cible » : version d'Odoo (« 18.0 »), ou « q », « w », « m » comme le menu ;
- « environnement » : « dev » ou « prod » ;
- « type » : « standard » ou « extra » ;
- « systeme », « mise » : True ou False ;
- « git_nom », « git_courriel » : chaînes.
Une réponse absente vaut None.

Ce module ne dépend que de la bibliothèque standard et de todo_i18n :
install.sh et l'amorçage de todo.py le lancent sous le Python du système,
avant que le venv d'outillage existe, pour que rien ne s'installe tant
qu'une réponse manque.
"""

import argparse
import os
import platform
import re
import subprocess
import sys

if __name__ == "__main__":
    sys.path.insert(
        0, os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    )

from script.todo.todo_i18n import t  # noqa: E402

RACINE = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
NON_INTERACTIF = "EL_NON_INTERACTIVE"
CIBLES_HORS_VERSION = ("q", "w", "m")

# clé -> (option, variable, {valeur de l'option: valeur de la variable}).
# La variable porte la valeur que les scripts lisent déjà : EL_FREEZE vaut
# 0 ou 1 pour install_locally_dev.sh et les scripts de manifeste,
# EL_INSTALL_MISE pour script/install/lib_python_provider.sh.
QUESTIONS = {
    "cible": ("--target", "EL_INSTALL_TARGET", None),
    "environnement": ("--env", "EL_FREEZE", {"dev": "0", "prod": "1"}),
    "type": ("--type", "EL_WITH_EXTRA", {"standard": "0", "extra": "1"}),
    "systeme": ("--system", "EL_INSTALL_SYSTEM", {"no": "0", "yes": "1"}),
    "mise": ("--mise", "EL_INSTALL_MISE", {"no": "0", "yes": "1"}),
    "git_nom": ("--git-name", "EL_GIT_NAME", None),
    "git_courriel": ("--git-email", "EL_GIT_EMAIL", None),
}
BOOLEENS = ("systeme", "mise")
COURRIEL = re.compile(r"[^@\s]+@[^@\s]+")


class ReponsesInvalides(Exception):
    """Une ou plusieurs réponses illisibles ; .messages les nomme."""

    def __init__(self, messages):
        super().__init__("; ".join(messages))
        self.messages = messages


def analyseur():
    """L'analyseur des options de « todo.py install »."""
    # Sans abréviation : install.sh reconnaît --non-interactive et --mise
    # en entier, avant que ce module puisse tourner.
    p = argparse.ArgumentParser(
        prog="./todo.sh install",
        description=t("Install ERPLibre with answers given in advance."),
        allow_abbrev=False,
    )
    p.add_argument(
        "--non-interactive",
        action="store_true",
        help=t("Ask nothing: a missing answer stops the installation."),
    )
    p.add_argument(
        "--target", help=t("Odoo version (18.0), or q, w, m as in the menu.")
    )
    p.add_argument("--env", choices=("dev", "prod"))
    p.add_argument("--type", choices=("standard", "extra"))
    p.add_argument("--system", choices=("yes", "no"))
    p.add_argument(
        "--mise",
        choices=("yes", "no"),
        help=t("Install mise when it is absent, rather than compile Python."),
    )
    p.add_argument("--git-name")
    p.add_argument("--git-email")
    return p


def _depuis_variable(cle, environ):
    """La réponse de `cle` lue dans `environ`, ou None ; lève
    ReponsesInvalides sur une valeur hors de celles admises."""
    option, variable, valeurs = QUESTIONS[cle]
    brute = environ.get(variable, "").strip()
    if not brute:
        return None
    if valeurs is None:
        return brute
    inverse = {v: k for k, v in valeurs.items()}
    if brute not in inverse:
        raise ReponsesInvalides(
            [
                f"{variable}={brute} : {t('expected')}"
                f" {' / '.join(sorted(inverse))}"
            ]
        )
    return inverse[brute]


def lire_reponses(argv, environ):
    """Rend (réponses, non_interactif) pour les options `argv` de
    « todo.py install » et l'environnement `environ`. Lève
    ReponsesInvalides sur une variable mal formée, une identité à moitié
    donnée ou un courriel invalide ; argparse sort lui-même (code 2) sur
    une option inconnue ou hors de ses choix."""
    args = analyseur().parse_args(argv)
    depuis_option = {
        "cible": args.target,
        "environnement": args.env,
        "type": args.type,
        "systeme": args.system,
        "mise": args.mise,
        "git_nom": args.git_name,
        "git_courriel": args.git_email,
    }
    reponses, erreurs = {}, []
    for cle, valeur in depuis_option.items():
        if valeur is None:
            try:
                valeur = _depuis_variable(cle, environ)
            except ReponsesInvalides as e:
                erreurs.extend(e.messages)
                continue
        reponses[cle] = valeur
    if reponses.get("cible"):
        reponses["cible"] = reponses["cible"].strip().lower()
    for cle in BOOLEENS:
        if reponses.get(cle) is not None:
            reponses[cle] = reponses[cle] == "yes"
    nom, courriel = reponses.get("git_nom"), reponses.get("git_courriel")
    if bool(nom) != bool(courriel):
        erreurs.append(
            t("Git identity: give both the name and the email, or neither.")
        )
    if courriel and not COURRIEL.fullmatch(courriel):
        erreurs.append(f"{t('Invalid email:')} '{courriel}'")
    if erreurs:
        raise ReponsesInvalides(erreurs)
    non_interactif = args.non_interactive or environ.get(NON_INTERACTIF) == "1"
    return reponses, non_interactif


def mise_requis(environ):
    """Vrai quand l'installation pourrait demander de poser mise : mise est
    absent, pyenv n'est pas imposé, et l'architecture n'est pas s390x, où
    mise ne publie aucun binaire. La présence de mise est lue par
    el_mise_cmd de script/install/lib_python_provider.sh, la fonction même
    qui décide de la question. Le Python qu'une version précise demandera
    n'est pas connu ici : la réponse est exigée dès que mise manque."""
    if environ.get("EL_PYTHON_PROVIDER", "auto") == "pyenv":
        return False
    if platform.machine() == "s390x":
        return False
    fait = subprocess.run(
        [
            "bash",
            "-c",
            ". ./script/install/lib_python_provider.sh && el_mise_cmd",
        ],
        cwd=RACINE,
        env=dict(environ),
        capture_output=True,
        text=True,
    )
    return fait.returncode != 0


def manquantes(reponses, mise_absent=False):
    """Les clés des réponses délibérées que `reponses` ne donne pas, dans
    l'ordre du menu. L'environnement et le type ne valent que pour une
    version d'Odoo ; la réponse sur mise, que si `mise_absent`."""
    requises = ["cible"]
    cible = reponses.get("cible")
    if cible not in CIBLES_HORS_VERSION:
        requises += ["environnement", "type"]
    requises.append("systeme")
    if mise_absent:
        requises.append("mise")
    return [cle for cle in requises if reponses.get(cle) is None]


def message_manquante(cle):
    """La ligne qui nomme l'option et la variable d'une réponse absente.
    Pour l'environnement, elle nomme aussi FREEZE : sous make, le Makefile
    exporte EL_FREEZE lui-même, et un EL_FREEZE venu du shell n'y arrive
    pas."""
    option, variable, valeurs = QUESTIONS[cle]
    if not valeurs:
        return f"{option} …  {t('or')}  {variable}=…"
    ligne = (
        f"{option} {'|'.join(valeurs)}  {t('or')}"
        f"  {variable}={'|'.join(valeurs.values())}"
    )
    if cle == "environnement":
        ligne += "  (make : FREEZE=0|1)"
    return ligne


def preparer(argv, environ):
    """Rend (réponses, non_interactif, erreurs) pour `argv` et `environ`.
    `erreurs` liste les lignes à afficher avant de refuser l'installation :
    une réponse illisible, une réponse délibérée absente en mode non
    interactif, ou la cible « m » dans ce mode, dont la dernière étape fait
    choisir un appareil Android au clavier. Vide, l'installation peut
    partir."""
    try:
        reponses, non_interactif = lire_reponses(argv, environ)
    except ReponsesInvalides as e:
        return {}, False, list(e.messages)
    if not non_interactif:
        return reponses, False, []
    if reponses.get("cible") == "m":
        return (
            reponses,
            True,
            [
                t(
                    "Target m chooses an Android device at the keyboard: not available in non-interactive mode."
                )
            ],
        )
    absentes = manquantes(reponses, mise_absent=mise_requis(environ))
    if absentes:
        erreurs = [
            t("Non-interactive mode: missing answers, nothing was installed.")
        ]
        erreurs += [f"   {message_manquante(cle)}" for cle in absentes]
        return reponses, True, erreurs
    return reponses, True, []


def exporter(reponses, non_interactif, environ):
    """Pose dans `environ` ce que les scripts d'installation lisent : le
    mode, et la réponse sur mise pour script/install/lib_python_provider.sh.
    Sans effet hors du mode non interactif."""
    if not non_interactif:
        return
    environ[NON_INTERACTIF] = "1"
    if reponses.get("mise") is not None:
        environ["EL_INSTALL_MISE"] = "1" if reponses["mise"] else "0"


def verifier(argv, environ):
    """Affiche les erreurs de preparer() et rend le code de sortie : 0 si
    l'installation peut partir, 2 sinon. Pour install.sh et l'amorçage de
    todo.py, qui vérifient avant de poser le venv d'outillage."""
    _, _, erreurs = preparer(argv, environ)
    for ligne in erreurs:
        print(ligne if ligne.startswith("   ") else f"❌ {ligne}")
    return 2 if erreurs else 0


if __name__ == "__main__":
    # « python3 script/todo/install_non_interactif.py <options d'install> »
    sys.exit(verifier(sys.argv[1:], os.environ))
