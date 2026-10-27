#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Poser un paquet, une seule fois pour tout le CLI.

Quatre familles de gestionnaires, et trois choses qui changent de l'une à
l'autre : la COMMANDE, le NOM du paquet, et le BINAIRE qu'il pose. Chaque
appelant qui refaisait ce travail chez lui en couvrait un sous-ensemble
différent — d'où un CLI où l'on pouvait installer virt-viewer sous openSUSE
mais pas un navigateur ni lm-sensors.

Trois règles que la composante tient à la place des appelants :

- l'ID de /etc/os-release décide AVANT le PATH. Une machine peut porter
  plusieurs gestionnaires — un poste Debian avec dnf installé pour construire
  un paquet — et c'est l'ID qui dit lequel gouverne le système ;
- la commande s'affiche AVANT la question. On approuve ce qu'on a lu, pas un
  « (y/N) » posé à l'aveugle ;
- les index de paquets se rafraîchissent AVANT l'installation
  (install_steps), et un rafraîchissement qui met à jour tout le système se
  confirme à part (run_steps).
"""

import shlex
import shutil

from script.todo.todo_i18n import t

# Les familles, dans l'ordre où le PATH est interrogé quand l'ID de la
# distribution est inconnu.
FAMILIES = ("apt-get", "dnf", "pacman", "zypper")

# Le préfixe de commande de chaque famille ; les paquets s'ajoutent au bout.
# Tous non interactifs : un menu qui rend la main à un prompt apt bloque.
_INSTALL = {
    "apt-get": ("sudo", "apt-get", "install", "-y"),
    "dnf": ("sudo", "dnf", "install", "-y"),
    "pacman": ("sudo", "pacman", "-S", "--needed", "--noconfirm"),
    "zypper": ("sudo", "zypper", "--non-interactive", "install"),
}

# ID de /etc/os-release -> famille. Les dérivées sont nommées explicitement :
# ID_LIKE existe mais manque ou ment sur assez de distributions pour qu'on ne
# s'y fie pas seul, et le repli par le PATH couvre ce qui n'est pas listé.
_OS_ID_FAMILY = {
    "ubuntu": "apt-get",
    "debian": "apt-get",
    "linuxmint": "apt-get",
    "pop": "apt-get",
    "raspbian": "apt-get",
    "fedora": "dnf",
    "rhel": "dnf",
    "centos": "dnf",
    "almalinux": "dnf",
    "rocky": "dnf",
    "arch": "pacman",
    "manjaro": "pacman",
    "endeavouros": "pacman",
    "opensuse": "zypper",
    "opensuse-leap": "zypper",
    "opensuse-tumbleweed": "zypper",
    "sles": "zypper",
}


def os_id() -> str:
    """L'ID de la distribution hôte, ou '' si /etc/os-release est illisible."""
    try:
        with open("/etc/os-release", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("ID="):
                    return line.split("=", 1)[1].strip().strip('"').lower()
    except OSError:
        pass
    return ""


def family() -> str | None:
    """La famille qui gouverne cette machine, ou None si aucune n'est connue.

    L'ID de la distribution d'abord, le PATH ensuite : sur une machine qui
    porte deux gestionnaires, l'ID dit lequel possède le système.
    """
    connue = _OS_ID_FAMILY.get(os_id())
    if connue and shutil.which(connue):
        return connue
    for candidate in FAMILIES:
        if shutil.which(candidate):
            return candidate
    return None


def conseil_sans_gestionnaire() -> str:
    """Ce qu'on peut faire là où aucune famille impérative ne gouverne, ou "".

    « Aucun gestionnaire connu » est VRAI sur NixOS et n'y mène nulle part :
    rien ne s'y installe par une commande, tout s'y déclare. Le dire seul
    ferme la porte ; nommer les deux gestes qui marchent l'ouvre — le shell
    jetable pour essayer, la déclaration pour ce qui reste.

    Vide ailleurs : sur une machine dont on ne sait rien, inventer un conseil
    vaut moins que de se taire.
    """
    if os_id() != "nixos":
        return ""
    return t(
        "NixOS: nix-shell -p <package> for one shell,"
        " or declare it in /etc/nixos/configuration.nix"
    )


# Le rafraîchissement des index, avant une installation. apt-get échoue sur
# des index vides d'un système neuf ; Arch ne supporte pas la mise à jour
# partielle, donc -Syu et jamais -Sy seul ; dnf rafraîchit ses métadonnées
# lui-même quand elles ont expiré.
_REFRESH = {
    "apt-get": ("sudo", "apt-get", "update"),
    "pacman": ("sudo", "pacman", "-Syu", "--noconfirm"),
    "zypper": ("sudo", "zypper", "--non-interactive", "refresh"),
}


def refresh_command(famille=None) -> list | None:
    """La commande qui rafraîchit les index de paquets, ou None s'il n'y en
    a pas à lancer (dnf, ou aucune famille reconnue)."""
    famille = famille or family()
    commande = _REFRESH.get(famille)
    return list(commande) if commande else None


# Les familles dont le rafraîchissement met à jour TOUT le système et pas
# seulement les index : pacman -Syu. Il se confirme à part, réponse par
# défaut Non, après la question de l'installation elle-même.
_FULL_UPGRADE = ("pacman",)


def is_refresh(cmd) -> bool:
    """True si `cmd` est le rafraîchissement d'une des familles."""
    return not isinstance(cmd, str) and tuple(cmd) in _REFRESH.values()


def is_full_upgrade(cmd) -> bool:
    """True si `cmd` est un rafraîchissement qui met à jour tout le système."""
    return not isinstance(cmd, str) and any(
        tuple(cmd) == _REFRESH[f] for f in _FULL_UPGRADE
    )


def install_command(paquets, famille=None) -> list | None:
    """La commande d'installation, en liste d'arguments. None si personne.

    `paquets` est une liste de noms, ou un dict {famille: liste} quand le
    paquet ne porte pas le même nom partout (lm-sensors chez Debian,
    lm_sensors chez Fedora et Arch).
    """
    famille = famille or family()
    if not famille:
        return None
    if isinstance(paquets, dict):
        paquets = paquets.get(famille) or []
    paquets = [paquets] if isinstance(paquets, str) else list(paquets)
    if not paquets:
        return None
    return list(_INSTALL[famille]) + paquets


def install_steps(paquets, famille=None) -> list:
    """Les commandes d'une installation, dans l'ordre où elles tournent.

    Le rafraîchissement des index d'abord quand la famille en a un, puis
    l'installation de `paquets` (mêmes formes qu'install_command). Liste
    vide quand il n'y a rien à installer ou aucun gestionnaire pour le faire :
    un rafraîchissement seul ne se propose jamais.
    """
    famille = famille or family()
    installation = install_command(paquets, famille=famille)
    if not installation:
        return []
    rafraichir = refresh_command(famille)
    return [rafraichir, installation] if rafraichir else [installation]


def resolve(binaires, commun=None, par_famille=None, famille=None):
    """(paquets, inconnus) pour les binaires demandés.

    Le nom du binaire n'est presque jamais celui du paquet : `commun` donne la
    correspondance quand elle vaut pour les quatre familles, `par_famille` la
    corrige là où elle diverge. Les paquets sortent dédoublonnés et dans
    l'ordre demandé — trois binaires d'un même paquet ne le demandent qu'une
    fois. `inconnus` liste ce pour quoi aucun paquet n'est déclaré : à dire,
    jamais à deviner.
    """
    famille = famille or family()
    surcharge = (par_famille or {}).get(famille, {})
    commun = commun or {}
    paquets, inconnus = [], []
    for binaire in binaires:
        paquet = surcharge.get(binaire) or commun.get(binaire)
        if not paquet:
            inconnus.append(binaire)
        elif paquet not in paquets:
            paquets.append(paquet)
    return paquets, inconnus


def as_steps(cmd) -> list:
    """`cmd` en liste d'étapes : une commande seule (chaîne ou liste
    d'arguments) devient une liste à une étape, une liste d'étapes (celle
    d'install_steps) reste telle quelle. Vide pour une commande vide."""
    if not cmd:
        return []
    if isinstance(cmd, str):
        return [cmd]
    if all(isinstance(c, (list, tuple)) for c in cmd):
        return [list(c) for c in cmd if c]
    return [list(cmd)]


def _lisible(cmd) -> str:
    """La commande telle qu'elle s'affiche ET telle qu'elle tourne."""
    return cmd if isinstance(cmd, str) else shlex.join(cmd)


def show_steps(cmd, prefix="  "):
    """Afficher chaque étape ; une mise à jour complète du système le dit
    sur la ligne qui la suit, pour qu'aucune question ne la cache."""
    for etape in as_steps(cmd):
        print(f"{prefix}{t('Will execute:')} {_lisible(etape)}")
        if is_full_upgrade(etape):
            print(
                f"{prefix}  ⚠ {t('This refresh is a full system upgrade, not only the package indexes.')}"
            )


def _oui_explicite(reponse) -> bool:
    """Un oui tapé, rien d'autre : la mise à jour complète du système se
    refuse par défaut, quelle que soit la règle de l'appelant pour ses
    propres questions."""
    return (reponse or "").strip().lower() in ("o", "oui", "y", "yes")


def run_steps(run, cmd, is_yes, prefix="  "):
    """Lancer les étapes dans l'ordre. Rend le code de la dernière lancée,
    ou le premier code non nul, ou None si rien n'a tourné.

    `run` reçoit la commande en chaîne et rend son code de sortie
    (exec_command_live, os.system). Une mise à jour complète du système se
    confirme ici, défaut Non : refusée, elle est sautée et l'installation
    part des index présents. Cette question n'accepte qu'un oui tapé
    (`_oui_explicite`) : `is_yes`, la règle de l'appelant, peut accepter une
    réponse vide, et une Entrée réflexe ne doit pas mettre tout le système
    à jour. `is_yes` reste dans la signature des appelants existants. Un rafraîchissement en échec arrête tout et le
    dit : installer sur des index périmés échouerait plus loin, sans dire
    pourquoi. Le seul appel à input() est celui de cette confirmation ; un
    appelant sans terminal ne doit donc pas passer une telle étape.
    """
    status = None
    for etape in as_steps(cmd):
        if is_full_upgrade(etape) and not _oui_explicite(
            input(f"{prefix}{t('Upgrade the whole system first? (y/N): ')}")
        ):
            print(f"{prefix}{t('Package indexes left as they are.')}")
            continue
        status = run(_lisible(etape))
        if status:
            if is_refresh(etape):
                print(
                    f"{prefix}❌ {t('Refreshing the package indexes failed; nothing installed.')}"
                )
            return status
    return status


def show_and_ask(cmd, question, is_yes, prefix="  ") -> bool:
    """Afficher la commande, PUIS demander. True si l'opérateur accepte.

    L'ordre est le fond de l'affaire : une question posée avant la commande
    fait approuver à l'aveugle. Centralisé ici pour qu'aucun appelant ne
    puisse l'inverser. `cmd` est une commande ou une liste d'étapes, toutes
    affichées avant la question.
    """
    show_steps(cmd, prefix=prefix)
    return bool(is_yes(input(question)))


def ask_and_install(execute, cmd, question, is_yes, prefix="  "):
    """Proposer puis lancer. Rend le code de sortie, ou None si rien n'a été
    lancé — refus de l'opérateur, ou aucune commande à proposer.

    `cmd` est une commande, ou les étapes d'install_steps : une seule
    question les couvre toutes, sauf la mise à jour complète du système qui
    se confirme à part (run_steps). `execute` est le lanceur du CLI :
    exec_command_live REND le code de sortie et ne lève rien, donc
    l'appelant doit tester ce qui revient.
    """
    if not as_steps(cmd):
        print(f"{prefix}⚠ {t('no known package manager here.')}")
        conseil = conseil_sans_gestionnaire()
        if conseil:
            print(f"{prefix}  {conseil}")
        return None
    if not show_and_ask(cmd, question, is_yes, prefix=prefix):
        print(t("Nothing to do."))
        return None
    return run_steps(
        lambda c: execute.exec_command_live(c, source_erplibre=False),
        cmd,
        is_yes,
        prefix=prefix,
    )
