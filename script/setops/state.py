#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Où en est l'intégration de Set-OPS sur ce poste, ligne par ligne.

Dix segments, dans l'ordre où l'on règle le poste : la plateforme, le
manifeste qui déclare le moteur, l'emplacement privé, Google Repo, le moteur
lui-même, l'environnement Ansible, l'écosystème monté, le site monté, la clé
de voûte et les outils du poste. Chaque ligne dit son état, le geste qui la
règle, et la source d'où elle le tient ; le rendu est celui de
`script.todo.state_screen`, commun aux écrans d'état.

LECTURE SEULE. Ni `make`, ni réseau, ni écriture. Au-delà de `git`, deux
sous-processus bornés par `DELAI`, lancés dans un environnement construit à
neuf : la version d'ansible-core, demandée au Python du venv dédié, et
`scripts/voutes.py etat`, dont seul le CODE DE RETOUR est lu — sa sortie
nomme l'écosystème et n'est ni lue ni conservée.

LE RELEVÉ EST SÉPARÉ DE LA DÉCISION. `releve()` touche le système et ne
lève jamais : une sonde qui échoue rend None. `lignes()` est PURE et se
relit sans machine ni fichier, ce qui permet d'éprouver chaque verdict, y
compris ceux qu'on ne sait pas provoquer sur le poste.

FERMÉ PAR DÉFAUT. Un verdict inconnu n'est jamais porté ; une forme
inattendue — une plage illisible, un code de retour hors vocabulaire —
refuse au lieu de deviner.

Aucun import du code du moteur : il se lit par fichiers et sous-processus.
"""

from __future__ import annotations

import os
import platform
import posixpath
import re
import shlex
import shutil
import subprocess
import sys
from typing import NamedTuple

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from script.setops import ansible_env, ecosystems, engine
from script.todo.state_screen import A_REGLER, ABSENT, PORTE, Ligne
from script.todo.todo_i18n import t

# Le venv Ansible dédié. Il est DÉCLARÉ par la couche qui le pose ; l'écran
# le nomme, il ne décide pas de son nom.
VENV = ansible_env.VENV

# Le geste que la ligne « Environnement Ansible » nomme quand elle est à
# régler : la MÊME clé que l'entrée du menu, pour que l'écran renvoie à une
# entrée qui existe. Une épreuve tient les deux ensemble.
GESTE_ANSIBLE = "Set-OPS - Ansible environment (set it up)"

# Les gestes que les lignes nomment, relatifs à la racine d'ERPLibre.
INSTALLER_REPO = "./script/install/install_git_repo.sh"
RAPATRIER = "./script/manifest/update_manifest_local_setops.sh"
OUTIL_REPO = ".venv.erplibre/bin/repo"
# Le manifeste qu'écrit `repo init` : sa présence, et non celle du dossier
# `.repo/` que la seule fusion des manifestes crée, dit l'espace initialisé.
MANIFESTE_REPO = ".repo/manifest.xml"

# Le repère du dossier frère qui porte le `underlay.yml` d'un site, dans le
# geste qui le monte, et le document du moteur qui dit comment l'implanter.
REPERE_SITE = "<site>"
DOC_SITE = "docs/implanter-un-tenant-sur-un-site.md"


# Le SHA affiché sur la ligne du manifeste : douze caractères le gardent
# sans ambiguïté dans un dépôt de la taille du moteur.
SHA_COURT = 12

# Borne, en secondes, de chaque sous-processus du relevé. Aucun ne touche le
# réseau : la dépasser veut dire un interpréteur qui attend quelque chose,
# et l'écran rend alors un verdict inconnu plutôt que de rester figé.
DELAI = 30

# Les seules variables transmises aux sous-processus du relevé, et
# seulement celles qui sont posées. Hérité tel quel, l'environnement
# porterait `CONFIRMER`, les surcharges d'un make parent (`MAKEFLAGS`), ou
# un `SETOPS_INSTANCE` qui ferait juger la clé d'un autre écosystème.
# `XDG_CONFIG_HOME` et `HOME` disent où `voutes.py` cherche les clés.
ENV_TRANSMIS = ("HOME", "PATH", "LANG", "LC_ALL", "XDG_CONFIG_HOME")


# Les dix segments. Chaque nom est une clé de traduction ; l'ordre est
# celui où l'on règle le poste, et non l'état : trier par avancement ferait
# bouger les lignes d'un lancement à l'autre.
PLATEFORME = "Platform"
MANIFESTE = "Engine manifest"
EMPLACEMENT = "Private location"
GOOGLE_REPO = "Google Repo"
MOTEUR = "Engine"
ANSIBLE = "Ansible environment"
ECOSYSTEME = "Mounted ecosystem"
SITE = "Mounted site"
CLE = "Ecosystem vault key"
OUTILS = "Station tools"
SEGMENTS = (
    PLATEFORME,
    MANIFESTE,
    EMPLACEMENT,
    GOOGLE_REPO,
    MOTEUR,
    ANSIBLE,
    ECOSYSTEME,
    SITE,
    CLE,
    OUTILS,
)

# Ce qu'une ligne peut attendre de son préalable : sa ligne PORTÉE, ou
# seulement son dossier PRÉSENT sur le disque.
PRESENT = "present"

# Les préalables, déclarés ici et nulle part ailleurs : {segment: (segment
# préalable, exigence)}. Non tenu, la ligne prend ◐ et le nomme, sans autre
# verdict.
#
# L'écosystème, le site et Ansible attendent le moteur PRÉSENT et non porté :
# un clone manuel laisse la ligne du moteur à régler, et ne doit pas masquer
# un écosystème monté à côté de lui. La clé attend l'écosystème PORTÉ :
# `voutes.py etat` ne juge que la clé de l'instance montée, et son code ne
# prouve rien sans elle.
PREALABLES = {
    MOTEUR: (MANIFESTE, PORTE),
    ANSIBLE: (MOTEUR, PRESENT),
    ECOSYSTEME: (MOTEUR, PRESENT),
    SITE: (MOTEUR, PRESENT),
    CLE: (ECOSYSTEME, PORTE),
}

# D'où chaque ligne tient son verdict, ses chemins relatifs à la racine
# d'ERPLibre ; « {moteur} » est le chemin déclaré, « {sonde} » le chemin que
# `engine.ignore_probe` en tire. Une source nomme ce que la ligne lit ;
# celle de l'emplacement, question posée à git, est la seule qui se rejoue
# telle quelle depuis la racine et rend le verdict de la ligne.
SOURCES = {
    PLATEFORME: "platform.system()",
    MANIFESTE: engine.MANIFEST,
    EMPLACEMENT: "git check-ignore -v --no-index -- {sonde}",
    GOOGLE_REPO: OUTIL_REPO + ", " + MANIFESTE_REPO,
    MOTEUR: "git -C {moteur}, {moteur}/.git, .repo/project.list",
    ANSIBLE: (
        VENV
        + "/bin/ansible-playbook, {moteur}/"
        + ansible_env.DEFAULTS_ANSIBLE
        + " ("
        + ansible_env.CLE_PLAGE
        + "), {moteur}/"
        + ansible_env.REQUIREMENTS_PY
        + ", {moteur}/"
        + ansible_env.REQUIREMENTS_YML
    ),
    ECOSYSTEME: "{moteur}/instance",
    SITE: "{moteur}/underlay.yml ({moteur}/" + DOC_SITE + ")",
    CLE: "{moteur}/scripts/voutes.py etat (rc)",
    OUTILS: "shutil.which",
}

# Les outils sans lesquels aucun geste du moteur ne part.
OUTILS_COEUR = ("make", "git", "ssh")

# Les outils d'un geste particulier, et ce qu'ils bloquent : des noms de
# cibles `make` du moteur, jamais traduits. Leur absence n'empêche que ces
# gestes-là. `rsync` sert au module `synchronize` d'Ansible, que seul
# `depot-hors-site` emploie ; `dig`, à la lecture des DS publiés, que seul
# `dnssec-verifier` fait parmi les `dnssec-*`.
OUTILS_GESTES = (
    ("gpg", "cles-*, remise-*"),
    ("openssl", "ca-racine, expositions-etat"),
    ("curl", "ca-racine, expositions-etat"),
    ("rsync", "depot-hors-site"),
    ("dig", "dnssec-verifier, dns-bascule-devis"),
    ("node", "inventaire-verifier"),
)


class Releve(NamedTuple):
    """Ce que le poste et le moteur disent, à un instant.

    Rassemblé en UNE fois : relire le disque entre deux lignes rendrait un
    écran dont les lignes ne décrivent pas le même état. Un champ qui peut
    valoir None le vaut quand la sonde n'a pas su répondre.
    """

    # `platform.system()`, "" s'il ne sait pas.
    systeme: str
    # Le chemin et la révision du moteur que déclare le manifeste ; ""
    # sans déclaration lisible.
    chemin: str
    revision: str
    # Le parent du chemin est-il ignoré par git ?
    parent_ignore: bool | None
    # `.venv.erplibre/bin/repo` exécutable ; `.repo/` initialisé par
    # `repo init`, c'est-à-dire portant `MANIFESTE_REPO`.
    outil_repo: bool
    repo_initialise: bool
    # Quelque chose occupe le chemin déclaré — un dossier, lisible ou non,
    # un fichier, un lien, même brisé : la règle même du script de
    # rapatriement (`os.path.lexists`).
    chemin_occupe: bool
    # Un dossier lisible au chemin déclaré.
    moteur_present: bool
    # Le chemin figure-t-il dans `.repo/project.list` ?
    gere_par_repo: bool | None
    # Google Repo a-t-il posé l'arbre au chemin (`engine.repo_worktree`) ?
    # La liste dit ce que le dernier sync visait, et s'écrit même quand il
    # échoue : seul le `.git` qui mène sous `.repo/` dit ce qu'il a posé.
    # None quand rien n'occupe le chemin.
    arbre_repo: bool | None
    # Le HEAD du clone face à l'épingle : une relation de
    # `engine.RELATIONS`, et le nombre de commits qui les séparent.
    relation: str
    ecart: int | None
    # Les entrées de `git status --porcelain` du clone.
    modifies: int | None
    # `<VENV>/bin/ansible-playbook` présent.
    ansible_playbook: bool
    # La version d'ansible-core que le venv importe, telle qu'il l'écrit.
    version_ansible: str | None
    # L'exigence `serveur_ops_ansible` du moteur, telle qu'il l'écrit.
    plage_ansible: str | None
    # Le major.minor que rend `python3` RÉSOLU PAR LE PATH du geste, et sa
    # conformité au mineur de la cible. C'est la mesure que fera la garde du
    # moteur, qui lance `python3` nu : un chemin absolu vers `bin/python`
    # répondrait encore là où le geste, lui, échouerait.
    mineur_path: str | None
    # (nom, épinglée, posée ou None) de chaque bibliothèque et de chaque
    # collection dont la version posée ne vaut pas celle que le moteur
    # épingle. Vides quand tout concorde.
    biblios_ecarts: tuple
    collections_ecarts: tuple
    # Ce que le moteur ÉPINGLE, ou None quand son fichier ne se lit pas.
    # La ligne portée dit ainsi sur quoi elle s'est prononcée, et un fichier
    # illisible ne se lit plus « zéro écart ».
    biblios_epinglees: tuple | None
    collections_epinglees: tuple | None
    # `<moteur>/instance` : un vrai dossier plutôt qu'un lien ; le nom de
    # la cible du lien ("" sans lien) ; `plan/serveurs.yml` sous la cible.
    instance_reelle: bool
    ecosysteme: str
    plan_present: bool
    # Le nom du dossier qui porte le `underlay.yml` monté ; "" sans site.
    # `site_brise` : un lien `underlay.yml` est posé, et ne mène à aucun
    # fichier.
    site: str
    site_brise: bool
    # Le code de retour de `voutes.py etat`.
    code_cle: int | None
    # Les outils de `OUTILS_COEUR` et `OUTILS_GESTES` introuvables.
    outils_absents: tuple


def _cite(texte) -> str:
    """`texte` cité pour le shell, recopiable tel quel."""
    return shlex.quote(texte)


def _joindre(constats) -> str:
    """Les constats d'une ligne, joints par le séparateur de la langue."""
    return t("; ").join(constats)


def _plateforme(vu):
    if vu.systeme == "Linux":
        return PORTE, vu.systeme
    return ABSENT, t("{os}: the engine assumes bash and the GNU tools").format(
        os=vu.systeme or "?"
    )


def _manifeste(vu):
    if not vu.chemin:
        return ABSENT, t("no Set-OPS manifest declared")
    if not engine.is_pinned(vu.revision):
        return ABSENT, t("revision « {rev} » is not a pinned commit").format(
            rev=vu.revision
        )
    return PORTE, t("{path} pinned at {sha}").format(
        path=vu.chemin, sha=vu.revision[:SHA_COURT]
    )


def _emplacement(vu):
    """Le parent du moteur, où le moteur cherche ses écosystèmes.

    Sans déclaration, aucun parent ne se nomme : la ligne le dit comme la
    ligne du manifeste, sans verdict sur un chemin inconnu.
    """
    if not vu.chemin:
        return ABSENT, t("no Set-OPS manifest declared")
    parent = (posixpath.dirname(vu.chemin) or ".") + "/"
    if vu.parent_ignore is True:
        return PORTE, t(
            "{parent} is ignored by git: ecosystems placed next to the"
            " engine stay private"
        ).format(parent=parent)
    if vu.parent_ignore is False:
        return ABSENT, t(
            "{parent} is NOT ignored by git: an ecosystem placed next to"
            " the engine would be committed"
        ).format(parent=parent)
    return ABSENT, t("cannot tell whether {parent} is ignored by git").format(
        parent=parent
    )


def _google_repo(vu):
    """Porté avec `repo` exécutable et un `.repo/` initialisé.

    Le script de rapatriement initialise `.repo/`, mais refuse un chemin
    qu'occupe ce que Google Repo ne gère pas (`_gere`) : la ligne nomme
    alors sa mise de côté AVANT le script, et seulement alors.
    """
    constats = []
    if not vu.outil_repo:
        constats.append(t("repo missing: {cmd}").format(cmd=INSTALLER_REPO))
    if not vu.repo_initialise and vu.chemin_occupe and _gere(vu) is not True:
        constats.append(
            t(
                ".repo/ not initialized: set aside what occupies the"
                " engine's path ({mv}), then {cmd} initializes it"
            ).format(mv=engine.mise_de_cote(vu.chemin), cmd=RAPATRIER)
        )
    elif not vu.repo_initialise:
        constats.append(
            t(".repo/ not initialized: {cmd} initializes it").format(
                cmd=RAPATRIER
            )
        )
    if constats:
        return A_REGLER, _joindre(constats)
    return PORTE, t("repo and .repo/ present")


def _constat_epingle(relation, ecart) -> str:
    """Ce que la relation à l'épingle laisse à régler ; "" à l'épingle.

    Seule une épingle ABSENTE du clone se règle par un rapatriement ; une
    relation inconnue n'établit rien et ne nomme aucun geste. Une relation
    hors de `engine.RELATIONS` se lit comme inconnue.
    """
    n = "?" if ecart is None else ecart
    if relation == engine.EGAL:
        return ""
    if relation == engine.AVANCE:
        return t("{n} commit(s) ahead of the pin").format(n=n)
    if relation == engine.RETARD:
        return t("{n} commit(s) behind the pin: resynchronize").format(n=n)
    if relation == engine.DIVERGE:
        return t("HEAD does not descend from the pin")
    if relation == engine.ABSENTE:
        return t("the pin is unknown to this clone: resynchronize")
    return t("cannot tell where HEAD stands against the pin")


def _gere(vu):
    """Google Repo gère-t-il le moteur ? True, False, ou None.

    La règle du script de rapatriement, qui refuse tout autre occupant du
    chemin : sa liste porte le chemin ET il y a posé l'arbre — ces deux
    lectures seules, `.repo/manifest.xml` n'y entrant pas. Une seule
    lecture fausse fait un clone manuel : False. Sans lecture fausse, une
    lecture inconnue laisse la question ouverte, None, sauf sans `.repo/`
    initialisé : le script refuse alors, et rien ne gère le dossier.
    """
    lectures = (vu.gere_par_repo, vu.arbre_repo)
    if all(lecture is True for lecture in lectures):
        return True
    if not vu.repo_initialise or any(lecture is False for lecture in lectures):
        return False
    return None


def _moteur(vu):
    """Porté seulement géré par Google Repo, à l'épingle, arbre propre.

    Rien au chemin : la ligne nomme le script de rapatriement, qui l'y pose.
    Tout occupant que Google Repo ne gère pas — un clone manuel, ou ce qui
    n'est pas un dossier lisible : un fichier, un lien brisé — est refusé
    par ce script : la ligne nomme sa mise de côté, comme lui. Chaque
    constat est nommé, et ils se joignent sur une ligne : régler le premier
    ne doit pas faire découvrir le suivant au lancement d'après.

    L'épingle ne se juge que dans un clone que git sait lire : sans lui,
    aucun constat d'épingle n'est établi, et la ligne dit seulement que git
    ne lit pas le moteur.
    """
    if not vu.chemin_occupe:
        return A_REGLER, t("absent: {cmd}").format(cmd=RAPATRIER)
    constats = []
    gere = _gere(vu)
    if gere is False and not vu.moteur_present:
        constats.append(
            t(
                "{path} is not a readable folder: move it aside ({cmd}),"
                " then fetch it through the manifest"
            ).format(path=vu.chemin, cmd=engine.mise_de_cote(vu.chemin))
        )
    elif gere is False:
        constats.append(
            t(
                "manual clone: move it aside ({cmd}), then fetch it through"
                " the manifest"
            ).format(cmd=engine.mise_de_cote(vu.chemin))
        )
    elif gere is not True:
        constats.append(
            t("cannot tell whether Google Repo manages {path}").format(
                path=vu.chemin
            )
        )
    if vu.modifies is None:
        constats.append(t("git cannot read the engine"))
    else:
        epingle = _constat_epingle(vu.relation, vu.ecart)
        if epingle:
            constats.append(epingle)
        if vu.modifies:
            constats.append(
                t(
                    "{n} modified file(s): some engine targets rewrite"
                    " tracked files"
                ).format(n=vu.modifies)
            )
    if constats:
        return A_REGLER, _joindre(constats)
    return PORTE, t("managed by Google Repo, at the pin, clean tree")


def _ansible(vu):
    """Porté quand les quatre constats concordent : la version d'ansible-core
    est dans la plage du moteur, le `python3` du PATH porte le mineur de la
    cible, et bibliothèques comme collections sont aux versions épinglées.

    L'ORDRE DES CONSTATS EST CELUI OÙ ILS CASSENT. Un venv absent se règle
    avant un mineur, un mineur avant une collection : dire les quatre d'un
    coup noierait celui qui bloque.
    """
    if not vu.ansible_playbook:
        return A_REGLER, t("{venv} absent: « {geste} » sets it up").format(
            venv=VENV, geste=t(GESTE_ANSIBLE)
        )
    if ansible_env.specifieur(vu.plage_ansible) is None:
        return ABSENT, t("the engine's ansible-core range is unreadable")
    if ansible_env.version(vu.version_ansible) is None:
        return A_REGLER, t(
            "{venv}: the ansible-core version is unreadable"
        ).format(venv=VENV)
    if not ansible_env.dans_la_plage(vu.version_ansible, vu.plage_ansible):
        return A_REGLER, t(
            "{venv}: ansible-core {version}, outside {spec}"
        ).format(
            venv=VENV,
            version=vu.version_ansible.strip(),
            spec=vu.plage_ansible.strip(),
        )
    if vu.biblios_epinglees is None or vu.collections_epinglees is None:
        return ABSENT, t("the engine's pinned requirements are unreadable")
    constats = []
    if vu.mineur_path != ansible_env.MINEUR_CIBLE:
        constats.append(
            t(
                "python3 on the gesture PATH is {lu}, the target runs {cible}"
            ).format(
                lu=vu.mineur_path or t("unreadable"),
                cible=ansible_env.MINEUR_CIBLE,
            )
        )
    for etiquette, ecarts in (
        (t("library"), vu.biblios_ecarts),
        (t("collection"), vu.collections_ecarts),
    ):
        for nom, epinglee, posee in ecarts:
            constats.append(
                t("{kind} {name}: {pinned} pinned, {found} installed").format(
                    kind=etiquette,
                    name=nom,
                    pinned=epinglee,
                    found=posee or t("absent"),
                )
            )
    if constats:
        return A_REGLER, _joindre(constats)
    return PORTE, t(
        "{venv}: ansible-core {version}, within {spec}; python3 {mineur};"
        " {n} libraries and {m} collections at the pin"
    ).format(
        venv=VENV,
        version=vu.version_ansible.strip(),
        spec=vu.plage_ansible.strip(),
        mineur=vu.mineur_path,
        n=len(vu.biblios_epinglees),
        m=len(vu.collections_epinglees),
    )


def _ecosysteme(vu):
    if vu.instance_reelle:
        return A_REGLER, t(
            "« instance » is a real folder, not a link: the engine refuses"
            " to switch"
        )
    if not vu.ecosysteme:
        commande = f"make -C {_cite(vu.chemin)} instance-utiliser NOM=…"
        return A_REGLER, t("no ecosystem mounted: {cmd}").format(cmd=commande)
    if not vu.plan_present:
        return A_REGLER, t("{name} has no plan/serveurs.yml").format(
            name=vu.ecosysteme
        )
    return PORTE, t("{name}: plan present").format(name=vu.ecosysteme)


def _site(vu):
    """Porté quand `<moteur>/underlay.yml` mène à un fichier.

    Le geste se tape depuis la racine d'ERPLibre, comme tous ceux de
    l'écran, mais la cible d'un lien se résout depuis le dossier du LIEN :
    elle se nomme donc relative au moteur, par « .. », vers le dossier
    frère qui porte le site. Le même geste remplace un lien qui ne mène à
    aucun fichier : `-n` le traite en fichier même quand il mène à un
    dossier.
    """
    if vu.site:
        return PORTE, vu.site
    lien = _cite(vu.chemin + "/underlay.yml")
    commande = f"ln -sfn ../{REPERE_SITE}/underlay.yml {lien}"
    if vu.site_brise:
        return A_REGLER, t("underlay.yml leads to no file: {cmd}").format(
            cmd=commande
        )
    return A_REGLER, t("no site mounted: {cmd}").format(cmd=commande)


def _cle(vu):
    """Le code de `voutes.py etat` : 0 la clé est là, 1 elle manque.

    Un script qui lève sort AUSSI en 1 : la ligne nomme donc la commande
    qui en montre la cause, plutôt que de conclure. Tout autre code, et
    l'absence de code, est un verdict illisible.
    """
    if vu.code_cle == 0:
        return PORTE, t("key present")
    if vu.code_cle == 1:
        commande = (
            "python3 " + _cite(vu.chemin + "/scripts/voutes.py") + " etat"
        )
        return A_REGLER, t("missing: {cmd} names it").format(cmd=commande)
    return A_REGLER, t("unreadable verdict (code {code})").format(
        code="?" if vu.code_cle is None else vu.code_cle
    )


def _outils(vu):
    """Porté dès que le cœur est là ; l'outil d'un geste manquant est
    listé en note, avec les gestes qu'il bloque."""
    absents = set(vu.outils_absents)
    coeur = [o for o in OUTILS_COEUR if o in absents]
    gestes = [f"{o} ({bloque})" for o, bloque in OUTILS_GESTES if o in absents]
    constats = []
    if coeur:
        constats.append(t("missing: {tools}").format(tools=", ".join(coeur)))
    if gestes:
        constats.append(
            t("optional, absent: {tools}").format(tools=", ".join(gestes))
        )
    if coeur:
        return A_REGLER, _joindre(constats)
    return PORTE, _joindre(constats) or t("all present")


_DECISIONS = {
    PLATEFORME: _plateforme,
    MANIFESTE: _manifeste,
    EMPLACEMENT: _emplacement,
    GOOGLE_REPO: _google_repo,
    MOTEUR: _moteur,
    ANSIBLE: _ansible,
    ECOSYSTEME: _ecosysteme,
    SITE: _site,
    CLE: _cle,
    OUTILS: _outils,
}


def _tenu(vu, rendus, requis, exigence) -> bool:
    """Le préalable `requis` tient-il l'`exigence` ?

    PRESENT ne se lit que pour le moteur, seul segment qui soit un dossier ;
    pour tout autre, il n'est pas tenu.
    """
    if exigence == PRESENT:
        return requis == MOTEUR and vu.moteur_present is True
    return rendus[requis].etat == PORTE


def lignes(vu: Releve) -> tuple:
    """Les dix lignes, dans l'ordre de `SEGMENTS`. Fonction PURE.

    Une ligne dont le préalable n'est pas tenu dit seulement « d'abord :
    <segment> » : un verdict rendu sur ce qui manque ne décrirait rien.
    """
    moteur = vu.chemin or f"<{t(MOTEUR)}>"
    # Sans déclaration, la sonde se nomme sous le repère du moteur, que la
    # normalisation de `engine.ignore_probe` effacerait.
    if vu.chemin:
        sonde = _cite(engine.ignore_probe(vu.chemin))
    else:
        sonde = _cite(posixpath.join(moteur, "..", engine.SONDE))
    rendus = {}
    for segment in SEGMENTS:
        attendu = PREALABLES.get(segment)
        if attendu is not None and not _tenu(vu, rendus, *attendu):
            etat = A_REGLER
            detail = t("first: {segment}").format(segment=t(attendu[0]))
        else:
            etat, detail = _DECISIONS[segment](vu)
        rendus[segment] = Ligne(
            t(segment),
            etat,
            detail,
            SOURCES[segment].format(moteur=moteur, sonde=sonde),
        )
    return tuple(rendus[s] for s in SEGMENTS)


def _env_neuf() -> dict:
    """L'environnement d'un sous-processus du relevé : `ENV_TRANSMIS` seul."""
    return {k: os.environ[k] for k in ENV_TRANSMIS if k in os.environ}


def _lancer(argv, cwd, capture):
    """Lance `argv` dans `cwd`, environnement neuf, entrée fermée, borné
    par `DELAI`.

    Rend le CompletedProcess, ou None quand le processus n'a pas pu
    tourner jusqu'au bout (introuvable, délai dépassé, argument invalide).
    Sans `capture`, la sortie part au néant sans être lue.
    """
    sortie = subprocess.PIPE if capture else subprocess.DEVNULL
    try:
        return subprocess.run(
            argv,
            cwd=cwd,
            env=_env_neuf(),
            stdin=subprocess.DEVNULL,
            stdout=sortie,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=DELAI,
            check=False,
        )
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        return None


def _systeme() -> str:
    try:
        return platform.system()
    except (OSError, ValueError):
        return ""


def _dossier_lisible(chemin) -> bool:
    try:
        return (
            bool(chemin)
            and os.path.isdir(chemin)
            and os.access(chemin, os.R_OK | os.X_OK)
        )
    except (OSError, ValueError, TypeError):
        return False


def _absent(outil) -> bool:
    try:
        return shutil.which(outil) is None
    except (OSError, ValueError, TypeError):
        return True


def _instance(moteur) -> tuple:
    """(vrai dossier, nom de la cible, plan présent) de `<moteur>/instance`.

    Le nom est celui du dossier où mène le lien, comme le moteur le lit ;
    un lien brisé garde son nom, sans plan.
    """
    lien = os.path.join(moteur, "instance")
    try:
        if os.path.islink(lien):
            cible = os.path.realpath(lien)
            plan = os.path.isfile(os.path.join(cible, "plan", "serveurs.yml"))
            return False, ecosystems.monte(moteur), plan
        return os.path.isdir(lien), "", False
    except (OSError, ValueError):
        return False, "", False


def _lien_brise(chemin) -> bool:
    """Vrai pour un lien symbolique posé en `chemin` qui ne mène à aucun
    fichier : brisé, ou vers un dossier."""
    try:
        return os.path.islink(chemin) and not os.path.isfile(chemin)
    except (OSError, ValueError, TypeError):
        return False


def _executable(chemin) -> bool:
    """Un fichier que le script qui le lance saurait exécuter."""
    try:
        return os.path.isfile(chemin) and os.access(chemin, os.X_OK)
    except (OSError, ValueError, TypeError):
        return False


def _code_cle(moteur):
    """Le code de retour de `<moteur>/scripts/voutes.py etat`, ou None.

    Lancé par l'interpréteur courant, depuis le moteur : le script trouve
    ses modules à côté de lui, et `-B` empêche d'écrire leur bytecode dans
    le moteur. Sa sortie nomme l'écosystème ; elle n'est pas même capturée.
    """
    script = os.path.join(moteur, "scripts", "voutes.py")
    if not os.path.isfile(script):
        return None
    fait = _lancer(
        [sys.executable, "-B", script, "etat"], cwd=moteur, capture=False
    )
    return None if fait is None else fait.returncode


def _ecarts(epingles, lire):
    """(nom, épinglée, posée) pour chaque épingle que `lire` ne confirme pas.

    `lire` n'est appelée QU'UNE FOIS par nom : chaque lecture est un
    sous-processus ou un fichier, et la condition ne doit pas en payer une
    seconde.
    """
    vus = []
    for nom, epinglee in epingles:
        posee = lire(nom)
        if posee != epinglee:
            vus.append((nom, epinglee, posee))
    return tuple(vus)


def releve(racine) -> Releve:
    """L'état du poste et du moteur sous la racine d'ERPLibre `racine`.

    Touche le système — fichiers, `git`, deux sous-processus bornés — et
    ne lève jamais : ce qu'une sonde ne sait pas dire vaut None. Sans
    déclaration du moteur, rien du moteur n'est lu ; sans dossier lisible
    au chemin déclaré, ni git ni `voutes.py` ne sont lancés. `voutes.py` ne
    l'est qu'avec un écosystème monté et son plan : c'est le préalable de
    la ligne de la clé, seule à lire son code.
    """
    decl = engine.declaration(racine)
    chemin = decl.path if decl is not None else ""
    revision = decl.revision if decl is not None else ""
    moteur = os.path.join(racine, chemin) if chemin else ""
    occupe = bool(moteur) and os.path.lexists(moteur)
    present = _dossier_lisible(moteur)
    if present:
        relation, ecart = engine.relation_to_pin(moteur, revision)
        reelle, ecosysteme, plan = _instance(moteur)
    else:
        relation, ecart = engine.INCONNUE, None
        reelle, ecosysteme, plan = False, "", False
    venv = os.path.join(racine, VENV)
    playbook = os.path.isfile(os.path.join(venv, "bin", "ansible-playbook"))
    epingles_py = (
        ansible_env.bibliotheques_epinglees(moteur) if present else None
    )
    epingles_yml = (
        ansible_env.collections_epinglees(moteur) if present else None
    )
    # Les écarts ne se mesurent QUE si les deux côtés existent : sans venv,
    # « absente » serait vrai de tout et noierait la ligne.
    if playbook:
        mineur = ansible_env.mineur_du_path(racine, moteur)
        biblios = _ecarts(
            epingles_py or (),
            lambda nom: ansible_env.version_posee(racine, nom),
        )
        collections = _ecarts(
            epingles_yml or (),
            lambda nom: ansible_env.version_collection(moteur, nom),
        )
    else:
        mineur = None
        biblios, collections = (), ()
    outils = OUTILS_COEUR + tuple(o for o, _ in OUTILS_GESTES)
    return Releve(
        systeme=_systeme(),
        chemin=chemin,
        revision=revision,
        parent_ignore=(
            engine.parent_is_ignored(racine, chemin) if chemin else None
        ),
        outil_repo=_executable(os.path.join(racine, OUTIL_REPO)),
        repo_initialise=os.path.lexists(os.path.join(racine, MANIFESTE_REPO)),
        chemin_occupe=occupe,
        moteur_present=present,
        gere_par_repo=(
            engine.managed_by_repo(racine, chemin) if chemin else None
        ),
        arbre_repo=engine.repo_worktree(racine, chemin) if occupe else None,
        relation=relation,
        ecart=ecart,
        modifies=engine.dirty_count(moteur) if present else None,
        ansible_playbook=playbook,
        version_ansible=(
            ansible_env.version_posee(racine, ansible_env.PAQUET_ANSIBLE)
            if playbook
            else None
        ),
        plage_ansible=(ansible_env.plage_ansible(moteur) if present else None),
        mineur_path=mineur,
        biblios_ecarts=biblios,
        collections_ecarts=collections,
        biblios_epinglees=epingles_py,
        collections_epinglees=epingles_yml,
        instance_reelle=reelle,
        ecosysteme=ecosysteme,
        plan_present=plan,
        site=ecosystems.site_monte(moteur) if present else "",
        site_brise=(
            _lien_brise(os.path.join(moteur, "underlay.yml"))
            if present
            else False
        ),
        code_cle=_code_cle(moteur) if plan else None,
        outils_absents=tuple(o for o in outils if _absent(o)),
    )
