#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Où poser un ERPLibre, et ce qui l'en empêche.

Le module DÉCIDE et FABRIQUE : il rend un verdict sur un chemin et le bloc
shell qui poserait l'installation. Il n'exécute rien et n'ouvre aucune
socket — c'est le menu qui lance, après avoir montré la commande.

**Une installation déjà là n'est jamais écrasée.** Le chemin est sondé AVANT
toute écriture, et ce qui n'a pas été lu compte pour OCCUPÉ : une sonde muette
ne prouve pas qu'un chemin est libre, et se tromper dans ce sens détruit le
travail de quelqu'un. Un répertoire non vide suffit à refuser, même sans
marqueur : ce qui s'y trouve appartient à quelqu'un, ERPLibre ou non.

**Un seul marqueur ne suffit pas.** Un arbre poussé par rsync n'a pas de
`.git` — l'exclusion est dans le Makefile —, une installation interrompue n'a
pas encore ses fichiers de version, qui s'écrivent en dernier, et un clone
frais n'a que son dépôt. `MARQUEURS` en lit six, et un seul trouvé nomme
l'occupant.

**Les deux poses ne posent pas la même chose.** Le clone donne à la cible son
propre dépôt, à la branche demandée ; la copie lui donne l'arbre d'ici. La
copie EMPORTE `.git`, contrairement à `make ssh_push` : l'installation lance
`update_manifest_local_dev.sh`, qui sert le dépôt local par `git daemon` et
résout sa révision par `git symbolic-ref`. Un arbre sans dépôt s'y arrête sur
« impossible de déterminer une branche pour repo init ».

Rien ici n'entre dans une invite : les chemins et les alias désignent des
machines qui ne s'annoncent nulle part ailleurs, et `resume` est ce qu'une
cible a le droit de devenir hors de l'écran.
"""
from __future__ import annotations

import os
import shlex
from dataclasses import dataclass

# Les verdicts d'un chemin. MUET se traite comme occupé par l'appelant.
LIBRE = "libre"
ERPLIBRE = "erplibre"
OCCUPE = "occupe"
MUET = "muet"

# Le jeton qui prouve que la sonde elle-même a tourné. Sans lui, un lien
# mort, une clé refusée et un hôte injoignable rendent tous une sortie vide,
# qui se lirait comme un chemin libre — c'est-à-dire comme l'autorisation
# d'écraser.
JETON = "EL_SONDE_OK"

# Ce que la sonde imprime devant le nom d'un marqueur trouvé.
MARQUE = "EL_MARQUEUR"

# Ce que la sonde imprime quand le répertoire porte quelque chose qu'aucun
# marqueur ne nomme.
PLEIN = "EL_PLEIN"

# Ce qui prouve qu'un ERPLibre occupe déjà un chemin. Six marqueurs parce
# qu'aucun n'est présent dans tous les cas : un arbre poussé par rsync n'a pas
# de dépôt, un clone frais n'a pas les fichiers de version — ils se génèrent à
# l'installation et ne suivent pas le dépôt —, et une pose interrompue n'a ni
# `.repo` ni état.
MARQUEURS = (
    ".git",
    ".repo",
    ".erplibre-version",
    ".odoo-version",
    ".erplibre-state.json",
    "script/todo/todo.py",
)

# Ce que la garde imprime avant de renoncer. La clé est celle que le dépôt
# emploie déjà quand un checkout est trouvé en place.
GARDE = "Existing checkout kept, not updated:"

BRANCHE_DEFAUT = "master"

# Le chemin proposé quand l'utilisateur n'en donne pas. Il vit sous le compte
# de la cible, jamais sous un chemin absolu qui porterait un nom de compte.
CHEMIN_DEFAUT = "~/erplibre"

# Ce que la copie laisse derrière elle. Les environnements virtuels et les
# sources d'Odoo se reconstruisent à l'installation et pèsent des gigaoctets ;
# `private/` porte le coffre et les identifiants, et ne sort pas d'ici.
# `.git`, lui, PART — voir l'en-tête du module.
EXCLUS = (
    ".venv.*/",
    "addons/",
    "odoo12.0/",
    "odoo13.0/",
    "odoo14.0/",
    "odoo15.0/",
    "odoo16.0/",
    "odoo17.0/",
    "odoo18.0/",
    "private/",
    "__pycache__/",
    "*.pyc",
)


@dataclass
class Cible:
    """Où poser un ERPLibre.

    `alias` vide désigne cette machine ; sinon c'est une entrée de
    `~/.ssh/config`, et c'est ssh qui y lit l'utilisateur, le port et le
    ProxyJump — on ne les redemande pas, et on ne les réinvente pas.

    `handle` est ce qui a le droit de circuler hors de l'écran : « cible-1 »
    ne désigne personne, là où l'alias et le chemin désignent une machine et
    un compte.
    """

    handle: str
    alias: str
    path: str


def resume(cible) -> str:
    """Ce qu'une cible a le droit de devenir hors de l'affichage du menu.

    Rend la seule poignée, et « ici » ou « là-bas » pour situer sans nommer.
    L'alias et le chemin restent à l'écran et dans la configuration privée :
    le détecteur du dépôt reconnaît les adresses, les courriels et les
    chemins de compte, et ne voit passer ni un alias SSH ni un nom d'hôte nu.
    """
    ou = "ssh" if cible.alias else "local"
    return f"{cible.handle} ({ou})"


def chemin_shell(path) -> str:
    """Le chemin cité pour un interpréteur, son tilde de tête rendu à `$HOME`.

    `shlex.quote` protège TOUT, tilde compris, et le tilde y perd son sens :
    « '~/erplibre' » désigne un répertoire NOMMÉ « ~ » dans le répertoire
    courant, et non le compte de la cible. Le tilde de tête devient donc
    `"$HOME"`, que l'interpréteur de là-bas développe, et le reste est cité.

    Une spécification distante de rsync, elle, développe déjà le tilde chez la
    cible : les deux formes désignent alors le même répertoire, ce qui est la
    condition pour que la sonde et l'écriture jugent le même chemin.

    `~autrui` n'est PAS traité : personne ici ne connaît le compte d'autrui
    sur la cible, et deviner tomberait juste une fois sur deux. L'appelant le
    refuse — `tilde_etranger` le reconnaît.
    """
    if path == "~":
        return '"$HOME"'
    if path.startswith("~/"):
        return '"$HOME"/' + shlex.quote(path[2:])
    return shlex.quote(path)


def tilde_etranger(path) -> bool:
    """Vrai quand le chemin s'ouvre sur le compte de QUELQU'UN D'AUTRE.

    « ~autrui/x » se développe chez la cible sans que rien ici ne sache où :
    la sonde et l'écriture cesseraient de juger le même répertoire, ce qui est
    exactement ce que la garde existe pour empêcher.
    """
    return (
        path.startswith("~")
        and path not in ("~",)
        and not path.startswith("~/")
    )


def _garde_shell(path) -> str:
    """Le fragment qui renonce quand le chemin porte déjà quelque chose.

    Rejoué là où l'écriture a lieu, sur les TROIS méthodes : entre la sonde du
    menu et la pose, il y a le temps de lire une commande et de retaper un
    chemin, et le shell est le seul des deux à tourner là où l'on écrit.

    Le critère est celui de la sonde — un répertoire VIDE n'est pas un
    occupant. Tester la seule existence refuserait un répertoire que l'on
    vient de créer pour y installer, là où la sonde vient de dire « libre ».
    """
    return (
        f"p={chemin_shell(path)}; "
        f'if [ -e "$p" ] && [ -n "$(ls -A "$p" 2>/dev/null)" ]; then '
        f"echo {shlex.quote(GARDE)}; exit 3; fi"
    )


def sonde_shell(path) -> str:
    """Le shell qui dit si un chemin porte déjà quelque chose.

    Imprime un marqueur par ligne, puis `PLEIN` si le répertoire n'est pas
    vide, puis le jeton — et rien d'autre. La même chaîne sert ici et
    par-dessus ssh : un seul texte à relire, et un seul à éprouver par
    `bash -n`.

    Le jeton s'imprime en TOUTE fin, et inconditionnellement : c'est sa
    présence qui distingue « la sonde a tourné et n'a rien vu » de « la sonde
    n'a pas tourné ».
    """
    cible = chemin_shell(path)
    marqueurs = " ".join(shlex.quote(m) for m in MARQUEURS)
    return (
        f"p={cible}; "
        f'if [ -e "$p" ]; then '
        f"for m in {marqueurs}; do "
        f'if [ -e "$p/$m" ]; then echo "{MARQUE} $m"; fi; '
        f"done; "
        f'if [ -n "$(ls -A "$p" 2>/dev/null)" ]; then echo {PLEIN}; fi; '
        f"fi; "
        f"echo {JETON}"
    )


def lire_sonde(code, sortie) -> str:
    """LIBRE, ERPLIBRE, OCCUPE ou MUET, d'après ce que la sonde a rendu.

    Le jeton absent vaut MUET, QUEL QUE SOIT le code de retour : un hôte
    injoignable, une clé refusée et un chemin illisible rendent tous une
    sortie vide, et aucun ne prouve qu'il n'y a rien là-bas.

    Un marqueur l'emporte sur « plein » : savoir que l'occupant est un
    ERPLibre est ce qui permet de le dire à l'utilisateur.
    """
    texte = sortie if isinstance(sortie, str) else ""
    if JETON not in texte.split():
        return MUET
    lignes = texte.split("\n")
    if any(ligne.startswith(f"{MARQUE} ") for ligne in lignes):
        return ERPLIBRE
    if PLEIN in [ligne.strip() for ligne in lignes]:
        return OCCUPE
    return LIBRE


def marqueurs_vus(sortie) -> list:
    """Les marqueurs que la sonde a nommés, dans l'ordre où elle les imprime.

    Sert à DIRE ce qui occupe le chemin. Une liste vide n'est pas une
    absence : elle veut dire qu'aucun marqueur n'a été nommé, ce que
    `lire_sonde` traduit déjà.
    """
    vus = []
    for ligne in (sortie or "").split("\n"):
        ligne = ligne.strip()
        if ligne.startswith(f"{MARQUE} "):
            nom = ligne[len(MARQUE) + 1 :].strip()
            if nom and nom not in vus:
                vus.append(nom)
    return vus


def etat_local(path, *, exists=None, listdir=None) -> str:
    """Le même verdict sans passer par un interpréteur, pour cette machine.

    `exists` et `listdir` valent `os.path.exists` et `os.listdir` quand rien
    n'est injecté, résolus ici pour qu'un test n'ait aucun fichier réel à
    toucher.

    Un répertoire illisible rend MUET et non LIBRE : ne pas avoir pu lire
    n'est pas avoir lu que c'était vide.
    """
    exists = os.path.exists if exists is None else exists
    listdir = os.listdir if listdir is None else listdir
    cible = os.path.expanduser(path)
    if not exists(cible):
        return LIBRE
    if any(exists(os.path.join(cible, m)) for m in MARQUEURS):
        return ERPLIBRE
    try:
        contenu = listdir(cible)
    except OSError:
        return MUET
    return OCCUPE if contenu else LIBRE


def bloc_clone(path, *, git_url, branche=BRANCHE_DEFAUT, cible_make) -> str:
    """Le bloc shell qui clone puis installe, et qui refuse un chemin occupé.

    `git_url` et `cible_make` arrivent par argument : leurs valeurs vivent sur
    la classe TODO, que ce paquet n'importe pas.

    La garde est REJOUÉE ici, après l'avoir été à l'écran. Entre les deux, le
    temps de lire une commande et de retaper un chemin, et le shell est le
    seul des deux à s'exécuter là où l'écriture aura lieu.

    Les suites sont groupées par accolades : « cmd && a; b » ne lie que le
    premier maillon, et b tournerait quand même après un clone échoué.
    """
    cible = shlex.quote(path)
    return (
        f"{_garde_shell(path)}; "
        f'mkdir -p "$(dirname "$p")" && '
        f"git clone --branch {shlex.quote(branche)} "
        f'{shlex.quote(git_url)} "$p" && '
        f'{{ cd "$p" && make install_os && make {shlex.quote(cible_make)}; }}'
    )


def bloc_copie(cible, *, source=".", cible_make) -> str:
    """Le bloc shell qui recopie cet arbre chez la cible, puis y installe.

    La copie emporte `.git`, à la différence de `make ssh_push` : sans dépôt,
    l'installation s'arrête sur la résolution de la branche du manifeste.
    Elle laisse en revanche `private/`, les environnements virtuels et les
    sources d'Odoo, qui se reconstruisent ou ne sortent pas d'ici.

    `--delete` n'y est pas : le chemin a déjà été jugé libre, et un
    effacement récursif n'a rien à faire dans une pose neuve.

    Trois temps, et non un seul : la garde est rejouée CHEZ la cible et y crée
    le répertoire, puis rsync pousse, puis l'installation tourne là-bas. rsync
    seul ne crée que le dernier segment du chemin, et ne vérifie rien.
    """
    exclus = " ".join(f"--exclude={shlex.quote(m)}" for m in EXCLUS)
    distant = shlex.quote(f"{cible.alias}:{_pente(cible.path)}")
    prepare = f'{_garde_shell(cible.path)}; mkdir -p "$p"'
    return (
        f"{bloc_distant(cible.alias, prepare)} && "
        f"rsync -az {exclus} "
        f"-e {shlex.quote('ssh -o BatchMode=yes')} "
        f"{shlex.quote(_pente(source))} {distant} && "
        f"{bloc_distant(cible.alias, _bloc_install(cible.path, cible_make))}"
    )


def bloc_local_copie(path, *, source=".", cible_make) -> str:
    """La même copie, mais vers un chemin de CETTE machine.

    rsync sert aussi en local : il honore les mêmes exclusions, là où `cp -a`
    emporterait les environnements virtuels et les sources d'Odoo.
    """
    exclus = " ".join(f"--exclude={shlex.quote(m)}" for m in EXCLUS)
    return (
        f"{_garde_shell(path)}; "
        f'mkdir -p "$p" && '
        f'rsync -a {exclus} {shlex.quote(_pente(source))} "$p"/ && '
        f'{{ cd "$p" && make install_os && make {shlex.quote(cible_make)}; }}'
    )


def bloc_distant(alias, commande) -> str:
    """La commande, à exécuter chez `alias`, citée en UN SEUL morceau.

    Sans la citation, l'interpréteur d'ici découperait la commande et ssh
    n'en recevrait que le premier mot ; avec elle, c'est l'interpréteur de
    là-bas qui la relit, une fois, ce que le bloc attend.

    `BatchMode` refuse toute question : un hôte qui demanderait un mot de
    passe bloquerait sur une invite que personne ne voit venir.
    """
    return f"ssh -o BatchMode=yes {shlex.quote(alias)} {shlex.quote(commande)}"


def _bloc_install(path, cible_make) -> str:
    """Les deux `make` de l'installation, dans le chemin posé."""
    return (
        f"cd {chemin_shell(path)} && make install_os "
        f"&& make {shlex.quote(cible_make)}"
    )


def _pente(chemin) -> str:
    """Le chemin avec sa barre oblique finale, que rsync lit comme « le
    CONTENU de », par opposition au répertoire lui-même.

    Sans elle, `rsync src dst/` crée `dst/src/` : l'arbre entier descend d'un
    cran, et l'installation ne trouve plus son Makefile.
    """
    return chemin if chemin.endswith("/") else f"{chemin}/"


# ----------------------------------------------------------------------
# Le transfert de la configuration LLM


def payload_serveurs(serveurs) -> list:
    """Les serveurs à écrire chez la cible, sous la forme que `servers` lit.

    La poignée n'y est pas : elle se rattribue au chargement, et un rang figé
    survivrait à la suppression d'un voisin.
    """
    return [
        {
            "label": s.label,
            "host": s.host,
            "port": s.port,
            "software": s.software,
            "model": s.model,
            "hosting": s.hosting,
            "secret_ref": s.secret_ref,
        }
        for s in serveurs
    ]


def bloc_ecrire_config(path, keys) -> str:
    """Le shell qui écrit une section de configuration chez la cible.

    La charge arrive par l'ENTRÉE STANDARD et jamais par la ligne de
    commande : elle porte des adresses, et une ligne de commande se lit dans
    un journal comme dans la table des processus de la machine.

    L'écriture passe par `set_config_value`, et par lui seul : il vise le
    seul des trois fichiers fusionnés qui soit gitignored, il crée son
    répertoire en 0700 et son fichier en 0600, et il écrit atomiquement. Un
    `>` de shell ferait les trois autrement, et le mauvais des trois fichiers
    est celui que le dépôt suit.

    La section est REMPLACÉE et non étendue : la fusion des listes concatène,
    et deux poses successives numéroteraient des doublons.
    """
    programme = (
        "import json,sys;"
        "from script.config.config_file import ConfigFile;"
        f"ConfigFile().set_config_value({list(keys)!r},"
        "json.load(sys.stdin))"
    )
    return (
        f"cd {chemin_shell(path)} && "
        f".venv.erplibre/bin/python -c {shlex.quote(programme)}"
    )


def bloc_commandes_claude(path, gabarits) -> str:
    """Le shell qui pose les commandes Claude Code depuis le clone de la CIBLE.

    Rien de `~/.claude` d'ici ne part : les gabarits viennent du dépôt que la
    cible vient de recevoir, donc à la version qu'elle exécute, et sans le nom
    ni le courriel de l'opérateur d'ici, que les gabarits d'ici portent déjà
    substitués.

    `gabarits` est la table (nom, fichier) que le CLI porte déjà. Un nom qui
    ne serait pas un identifiant nu est ÉCARTÉ : la destination laisse le
    tilde hors des guillemets pour que le shell de là-bas le développe, et
    ce qui n'est pas cité doit alors être sûr par construction.
    """
    racine = chemin_shell(path)
    lignes = ["mkdir -p ~/.claude/commands"]
    for nom, fichier in gabarits:
        if not _nu(nom):
            continue
        source = shlex.quote(f"conf/{fichier}")
        lignes.append(f"cp -f {racine}/{source} ~/.claude/commands/{nom}.md")
    # « && » et non « ; » : chaîné par point-virgule, le bloc rend le code du
    # DERNIER `cp` seul, et un échec au milieu se rapporterait comme un succès.
    return " && ".join(lignes)


def _nu(nom) -> bool:
    """Vrai quand ce nom ne porte que des lettres, des chiffres et des
    soulignés, et peut donc entrer non cité dans un chemin."""
    return bool(nom) and all(c.isalnum() or c == "_" for c in str(nom))
