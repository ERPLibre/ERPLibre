#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce que le manifeste déclare, ce que la forge porte, et l'écart.

CE MODULE DÉCIDE ET N'APPELLE RIEN. Il reçoit deux listes de noms et rend un
plan ; l'appelant exécute. C'est ce qui rend le rapprochement vérifiable sur
deux cents noms sans forge, et ce qui permet de MONTRER le plan avant de
créer quoi que ce soit.

TROIS PIÈGES, ET CHACUN COÛTE CHER DANS UN SENS DIFFÉRENT.

LE SUFFIXE « .git ». Le manifeste écrit « account-analytic.git » là où la
forge nomme « account-analytic ». Ne pas le retirer fait paraître TOUS les
dépôts manquants, et crée deux cents doublons portant « .git » dans leur
nom. Le retirer avec `rstrip` est pire encore : `rstrip` enlève un ENSEMBLE
de caractères et non un suffixe, si bien que « digit.git » devient « d » et
« tigit.git » la chaîne vide. Seul `removesuffix` fait ce qu'on croit.

LA CASSE. Une forge Gitea ou Forgejo tient l'unicité d'un nom de dépôt sans
égard à la casse : « Server-Tools » et « server-tools » ne peuvent pas
coexister. Comparer en respectant la casse ferait paraître manquant un dépôt
présent, et sa création échouerait en 409 sur toute une liste.

LES COLLISIONS. Deux entrées de manifeste dont le nom se réduit au même nom
de forge ne peuvent pas y coexister. Créer la première et taire la seconde
laisserait un miroir silencieusement incomplet, alors le plan les NOMME et
l'appelant décide.
"""
from __future__ import annotations

from typing import NamedTuple


class Plan(NamedTuple):
    """L'écart entre le manifeste et la forge, sans rien avoir changé.

    `to_create` porte les noms de FORGE à créer, dans l'ordre du manifeste :
    un plan qu'on relit doit se lire dans l'ordre où on l'a écrit.

    `already` porte ceux qui sont déjà là — utile pour dire « 198 sur 200 »
    plutôt que « 2 », qui ne dit pas si le reste va bien ou n'a pas été vu.

    `collisions` est un dictionnaire {nom de forge: [noms de manifeste]} pour
    les seuls noms que plus d'une entrée revendique.
    """

    to_create: tuple
    already: tuple
    collisions: dict


def forge_name(manifest_name: str) -> str:
    """Le nom que ce projet de manifeste porte sur la forge.

    Le dernier segment du chemin, sans son « .git » final. Un nom qui
    contient un point sans finir par « .git » — « whisper.cpp » — est rendu
    tel quel : c'est son nom.
    """
    dernier = (manifest_name or "").strip().rstrip("/").rsplit("/", 1)[-1]
    return dernier.removesuffix(".git")


def _clef(nom: str) -> str:
    """Ce sur quoi deux noms sont LE MÊME nom pour la forge."""
    return forge_name(nom).lower()


def plan(declared, present) -> Plan:
    """Le plan de rapprochement. Ne touche à rien.

    `declared` est la liste des noms du manifeste, `present` celle des noms
    que la forge porte — soit son « name », soit son « full_name » : les deux
    se réduisent au même nom de forge, donc l'appelant n'a pas à choisir.

    Un nom vide est IGNORÉ plutôt que créé : un manifeste peut porter une
    entrée sans nom, et « créer un dépôt sans nom » n'a pas de sens.
    """
    deja = {_clef(nom) for nom in (present or []) if _clef(nom)}

    # Les noms DISTINCTS qui revendiquent une même clé. Le même projet
    # listé deux fois — ce que donnent deux manifestes fusionnés — n'est pas
    # un conflit de nommage : le signaler ferait crier au loup à chaque
    # fusion, et un avertissement qui se lève toujours ne se lit plus.
    revendique: dict = {}
    for nom in declared or []:
        clef = _clef(nom)
        if not clef:
            continue
        connus = revendique.setdefault(clef, [])
        if nom not in connus:
            connus.append(nom)

    collisions = {
        forge_name(noms[0]): list(noms)
        for noms in revendique.values()
        if len(noms) > 1
    }

    a_creer, presents = [], []
    vus = set()
    for nom in declared or []:
        clef = _clef(nom)
        if not clef or clef in vus:
            continue
        vus.add(clef)
        (presents if clef in deja else a_creer).append(forge_name(nom))
    return Plan(tuple(a_creer), tuple(presents), collisions)


def clone_url(fetch: str, manifest_name: str) -> str:
    """L'adresse à cloner pour ce projet, "" si l'un des deux manque.

    LA JONCTION SE NORMALISE. Les URL de « fetch » d'un manifeste ne
    finissent pas toutes par une barre oblique — une seule sur vingt-neuf
    n'en porte pas — et concaténer donnerait « …/ORGANISATIONdepot.git », une
    adresse qui n'existe pas. Le nom, lui, garde son « .git » : c'est l'URL
    de clone, pas le nom sur la forge.
    """
    fetch = (fetch or "").strip()
    nom = (manifest_name or "").strip().lstrip("/")
    if not fetch or not nom:
        return ""
    return f"{fetch.rstrip('/')}/{nom}"


# Les deux sens d'un miroir. ENTRANT : le projet vit ailleurs et la forge
# le suit. SORTANT : il vit chez nous et part se montrer.
ENTRANT = "entrant"
SORTANT = "sortant"
SENS = (ENTRANT, SORTANT)


def sens(clone_url: str, amonts=(), surcharge=None) -> str:
    """Le sens du miroir pour ce projet. Fonction PURE.

    LE MANIFESTE SAIT DÉJÀ. Un projet dont l'adresse de clone est chez un
    amont extérieur y vit : la forge le SUIT, donc le miroir est entrant. Un
    projet que rien d'extérieur ne porte vient d'ici, et part se montrer.
    Le dériver plutôt que le déclarer, c'est un réglage de moins à tenir —
    et un réglage qui ne peut pas mentir, puisque l'adresse est celle qu'on
    clone vraiment.

    LA SURCHARGE EXISTE POUR CE QUE LA DÉRIVATION NE SAIT PAS DIRE :
    pousser vers un amont un dépôt qui en vient aussi. Elle est nommée
    dépôt par dépôt, donc elle se relit ; sans elle, il faudrait déclarer
    les neuf cents autres pour en corriger un.

    `amonts` : les préfixes d'adresse qui désignent un porteur extérieur.
    Vide, tout est sortant — un site sans amont ne suit personne.
    """
    if surcharge in SENS:
        return surcharge
    adresse = (clone_url or "").strip().lower()
    for amont in amonts:
        prefixe = (amont or "").strip().lower()
        if prefixe and adresse.startswith(prefixe):
            return ENTRANT
    return SORTANT


# La section de configuration qui nomme le sens du miroir, dépôt par dépôt.
# Elle ne contient QUE des corrections : le sens se dérive du manifeste, et
# ce qui est écrit ici corrige la dérivation là où elle ne peut pas savoir.
CONFIG_KEY = "forge_mirror"


def amonts_du_manifeste(projets, forge_url="") -> tuple:
    """Les préfixes d'adresse qui désignent un porteur EXTÉRIEUR. PURE.

    DÉRIVÉS, et non déclarés. Tout ce qui n'est pas chez nous est un amont :
    tenir la liste à la main en ferait une de plus à entretenir, et elle
    vieillirait sans un mot le jour où le manifeste change de source.

    Le préfixe est « schéma://hôte/ » : c'est le grain auquel `sens` compare,
    et il survit à une réorganisation des chemins chez l'amont.

    Une `forge_url` vide ne retire rien — un site qui n'a pas dit où vit sa
    forge ne peut pas décider ce qui lui est extérieur, et supposer le
    ferait pousser vers l'amont ce qui en vient.
    """
    from urllib.parse import urlsplit

    def base(adresse):
        morceaux = urlsplit((adresse or "").strip())
        if not morceaux.scheme or not morceaux.netloc:
            return ""
        return f"{morceaux.scheme}://{morceaux.netloc}/".lower()

    chez_nous = base(forge_url)
    vus = []
    for projet in projets or []:
        prefixe = base(projet.get("clone_url", ""))
        if prefixe and prefixe != chez_nous and prefixe not in vus:
            vus.append(prefixe)
    return tuple(vus)


def surcharges(config=None) -> dict:
    """{nom de dépôt: sens} que ce site déclare. Jamais None.

    Lue par la FUSION des trois fichiers, comme les profils : une correction
    peut venir du fichier partagé par l'équipe autant que du fichier privé.
    Une valeur hors vocabulaire est écartée en silence ICI — `sens` la
    refuserait de toute façon, et faire échouer la lecture rendrait un écran
    d'avancement inutilisable sur un fichier corrigé à la main.
    """
    from script.config.config_file import ConfigFile

    cfg = config or ConfigFile()
    try:
        declare = cfg.get_config(CONFIG_KEY)
    except Exception:  # noqa: BLE001 - une lecture, pas le sujet
        return {}
    if not isinstance(declare, dict):
        return {}
    return {
        str(nom): str(valeur)
        for nom, valeur in declare.items()
        if str(valeur or "").strip() in SENS
    }


def declarer(nom: str, sens_voulu: str, config=None) -> dict:
    """Écrit la surcharge de sens de ce dépôt, et rend la table complète.

    Un `sens_voulu` VIDE retire la surcharge : le sens revient alors à ce
    que le manifeste dit, ce qui est le défaut et non une absence de
    réglage. Un sens inconnu est REFUSÉ plutôt que deviné — le vocabulaire
    est clos, et replier sur « sortant » ferait pousser vers un amont un
    dépôt qui en vient.

    L'écriture va dans le fichier PRIVÉ, le seul des trois que
    `set_config_value` touche. La table écrite repart de la FUSION : une
    correction venue du fichier partagé serait sinon perdue au premier
    réglage local.
    """
    from script.config.config_file import ConfigFile
    from script.lib_valid import ValidationError

    propre = str(nom or "").strip()
    if not propre:
        raise ValidationError("Nom de dépôt vide.")
    voulu = str(sens_voulu or "").strip()
    if voulu and voulu not in SENS:
        raise ValidationError(
            f"Sens inconnu : « {voulu} ». Connus : {', '.join(SENS)}."
        )
    cfg = config or ConfigFile()
    table = dict(surcharges(cfg))
    if voulu:
        table[propre] = voulu
    else:
        table.pop(propre, None)
    cfg.set_config_value([CONFIG_KEY], table)
    return table


def sortants(config=None) -> tuple:
    """Les dépôts que ce site déclare POUSSER vers un amont, triés.

    Seules les surcharges sortantes comptent : ce sont les seules qu'un site
    déclare vraiment, puisque le reste se dérive.
    """
    return tuple(
        sorted(n for n, v in surcharges(config).items() if v == SORTANT)
    )


def plan_mirrors(projets, amonts=(), surcharges=None) -> dict:
    """{sens: [noms de forge]} pour un manifeste entier. Fonction PURE.

    Les NOMS DE FORGE et non ceux du manifeste : c'est sous ce nom que la
    forge les porte, et les confondre créerait des doublons en « .git ».
    """
    surcharges = dict(surcharges or {})
    out = {ENTRANT: [], SORTANT: []}
    for projet in projets:
        nom = forge_name(projet.get("name", ""))
        if not nom:
            continue
        out[
            sens(
                projet.get("clone_url", ""),
                amonts,
                surcharges.get(nom) or surcharges.get(projet.get("name", "")),
            )
        ].append(nom)
    return out


def parse_projects(xml_text: str) -> list:
    """[{"name", "clone_url"}] pour chaque projet du manifeste.

    Prend le TEXTE et non un chemin : l'analyse devient pure, donc
    vérifiable sur les neuf cents projets réels du dépôt sans lire de
    fichier, et sur des cas inventés qu'aucun manifeste ne porte.

    LE « REMOTE » S'HÉRITE de « <default remote=…> ». Un seul projet sur
    neuf cents s'en sert dans ce dépôt, et c'est justement pour celui-là que
    l'ignorer donnerait une adresse VIDE — un miroir demandé sur rien, dont
    le refus de la forge ne dirait pas qu'il manque un remote.

    Un XML illisible LÈVE : c'est à l'appelant de dire quoi faire d'un
    manifeste tronqué, et rendre une liste vide se lirait comme « aucun
    projet », ce qui n'est pas la même chose.
    """
    from xml.etree import ElementTree

    racine = ElementTree.fromstring(xml_text)
    fetch_par_remote = {
        remote.get("name"): remote.get("fetch") or ""
        for remote in racine.findall("remote")
    }
    defaut = racine.find("default")
    remote_defaut = defaut.get("remote") if defaut is not None else None

    projets = []
    for projet in racine.findall("project"):
        nom = projet.get("name")
        if not nom:
            continue
        remote = projet.get("remote") or remote_defaut
        projets.append(
            {
                "name": nom,
                "clone_url": clone_url(fetch_par_remote.get(remote, ""), nom),
            }
        )
    return projets
