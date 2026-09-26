#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le moteur Set-OPS tient-il sur une grappe jetable, du gabarit au rasage ?

Ce n'est pas un test unitaire : il crée de vraies machines et prend des
HEURES. Il vit donc hors de `test/`, que le lanceur unitaire balaie.

LE TERRAIN SE DÉSIGNE, il ne se devine pas. `deep_proxmox.py` sert au
DÉVELOPPEMENT et monte des Proxmox imbriqués ; le cas réel est une grappe qu'on
possède. Le banc prend donc un terrain en argument, pour que la même épreuve
serve à la répétition puis au cas réel — et il ne touche pas au labo : il pose
SON pont et SON utilisateur d'API, et n'en modifie aucun.

UN SEUL ÉTAGE SUFFIT. Un Proxmox imbriqué est un Proxmox, et chaque étage de
plus rend tout 15 à 30 fois plus lent. Le banc éprouve le moteur, pas
l'imbrication.

TROIS CHOSES QUE LE MOTEUR EXIGE ET QU'UN ÉTAGE NEUF N'A PAS. Son playbook de
clonage parle à l'API et ASSERTE que l'hôte, l'utilisateur, l'identifiant et le
secret du jeton sont non vides : sans jeton il refuse avant d'agir. La carte de
la VM clonée est taguée SUR CE BANC — son écosystème n'a pas d'underlay, donc le
moteur dérive une VLAN de l'index de la flotte et la pose sur la carte ; en SDN
il l'omet au contraire, le VNet la portant déjà, et l'étiqueter deux fois
couperait le fil. Une carte taguée sur un pont qui n'est pas conscient des VLAN
démarre en restant injoignable. Enfin le clonage part d'un gabarit, qu'il faut
donc construire. D'où l'ordre : pont, jeton, gabarit, puis la boucle.

DEUX PASSES, ET ELLES NE PROUVENT PAS LA MÊME CHOSE. La première porte le jeton
par l'ENVIRONNEMENT, ce que le playbook accepte en repli : elle valide la
GRAPPE. La seconde le chiffre dans la VOÛTE de l'écosystème de banc et rejoue la
boucle PAR LES PORTES de todo : elle valide le CHEMIN DE TODO, dont la liste
blanche de l'exécuteur ne transmet exprès aucun `PROXMOX_*`.

Les commandes sont BÂTIES par des fonctions pures : c'est ce qui rend le texte
envoyé éprouvable sans machine, avant même qu'une machine existe.

  ./long_test/setops_banc.py --dry-run          # le plan, rien de créé
  ./long_test/setops_banc.py --detruire         # défaire ce qui a été posé
  ./long_test/setops_banc.py --terrain <alias>  # une grappe qu'on possède
  ./long_test/setops_banc.py --passe env        # jeton par l'environnement

CE QUI EST POSÉ ICI : les DÉCISIONS, et elles sont toutes gardées — préalables,
terrain, pont libre, forme du jeton, ordre de la défaite, empreinte. Les VERBES
qui créent exigent une grappe pour être éprouvés, donc un vrai lancement ; tant
qu'ils ne le sont pas, un lancement réel REFUSE en le disant, plutôt que
d'exécuter du code que rien n'a vérifié.
"""

from __future__ import annotations

import json
import os
import shlex
from typing import NamedTuple

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# CE QUE RENDENT LES SORTIES, et le vocabulaire est CLOS — celui des autres
# épreuves de ce dossier. 0 : elle est allée jusqu'au bout. OUTILLAGE : de quoi
# la mener manque, et RIEN n'a été tenté. NON_CONCLUANTE : quelque chose l'a
# arrêtée AVANT qu'elle mesure. Confondre 0 et NON_CONCLUANTE ferait lire
# « concluant » sur une épreuve qui n'a rien éprouvé.
SORTIE_OK = 0
SORTIE_OUTILLAGE = 20
SORTIE_NON_CONCLUANTE = 30
SORTIES = (SORTIE_OK, SORTIE_OUTILLAGE, SORTIE_NON_CONCLUANTE)

# Les deux passes, dans l'ORDRE où elles ont un sens : valider la grappe avant
# de valider le chemin qui s'appuie sur elle. Inversées, un échec de la voûte
# ne se distinguerait pas d'une grappe qui ne clone pas.
PASSE_ENV = "env"
PASSE_VOUTE = "voute"
PASSES = (PASSE_ENV, PASSE_VOUTE)

# Ce que le banc pose, nommé UNE fois. Les noms sont inventés et n'existent
# nulle part ailleurs dans le dépôt : un banc qui reprendrait un nom du parc
# détruirait, au rasage, ce qui ne lui appartient pas.
ECOSYSTEME = "OPS-Fictif-Trachyte"
UTILISATEUR_API = "banc-fictif-trachyte@pve"
JETON_API = "banc"
GABARIT = "banc-fictif-trachyte-gabarit"

# Le pont du banc ne peut pas être celui du labo : le rendre conscient des VLAN
# changerait le réseau des usages déjà posés dessus. Son numéro de départ est
# haut pour la même raison — on cherche un nom libre, on ne prend pas `vmbr0`.
PONT_DEPART = 9

# Les genres de ce que le banc pose, et l'ORDRE INVERSE dans lequel ils se
# défont. Vocabulaire CLOS.
VM = "vm"
MODELE = "modele"
PONT = "pont"
API = "api"
ECO = "ecosysteme"
GENRES = (VM, MODELE, PONT, API, ECO)


class Prealable(NamedTuple):
    """Une condition à tenir AVANT que quoi que ce soit soit créé.

    `tenu` vaut None quand la mesure elle-même n'a pas abouti. Confondre avec
    False ferait dire « absent » de ce qu'on n'a pas su regarder.
    """

    quoi: str
    tenu: bool | None
    dit: str = ""


class Empreinte(NamedTuple):
    """Ce que le banc a posé, pour pouvoir le défaire.

    `vms` est une suite de (vmid, nom) : le NOM est gardé parce que c'est lui
    qui autorise l'effacement — un VMID se réattribue.
    """

    terrain: str
    ecosysteme: str
    pont: str
    utilisateur: str
    modele: int
    vms: tuple


class Geste(NamedTuple):
    """Un geste de défaite : où le jouer, son genre, ce qu'il vise, le nom.

    `terrain` VOYAGE AVEC LE GESTE. Lu puis jeté, il fallait le redéduire au
    moment de jouer — et le terrain déduit est celui du DERNIER étage posé,
    potentiellement une autre grappe que celle où l'empreinte a été écrite. Les
    VMID d'une grappe seraient détruits sur une autre. C'est ce que fait le
    labo, qui promène `parent_alias` avec chacun de ses gestes.
    """

    terrain: str
    genre: str
    vise: str
    nom: str


def juge(prealables):
    """Le code de sortie que ces préalables commandent.

    Un préalable non tenu OU non mesurable rend `OUTILLAGE` : la distinction
    entre « absent » et « pas su regarder » sert à l'écran, pas au verdict —
    dans les deux cas rien n'a été tenté, et c'est ce que 20 veut dire.
    """
    return (
        SORTIE_OK
        if all(p.tenu for p in prealables or ())
        else SORTIE_OUTILLAGE
    )


def manquants(prealables):
    """Les préalables à dire AVANT de créer quoi que ce soit."""
    return tuple(p for p in prealables or () if not p.tenu)


def terrain_par_defaut(rapport):
    """L'alias de l'étage le MOINS profond du dernier rapport, ou « ».

    Le moins profond, et non le plus : un étage suffit, et chacun de plus rend
    tout 15 à 30 fois plus lent. L'alias est le seul point d'entrée stable que
    le labo laisse — l'adresse IP ne figure dans aucun rapport.
    """
    if not isinstance(rapport, dict):
        return ""
    # LES TYPES SONT EXIGÉS. Un niveau absent devenait 0 et gagnait comme « le
    # moins profond » ; des niveaux en texte se comparaient dans l'ordre
    # alphabétique, donc « 9 » après « 10 », à rebours de la raison d'être de
    # cette fonction ; des niveaux mixtes levaient un TypeError. Et « ok » en
    # texte est vrai, si bien qu'un étage RATÉ devenait éligible.
    etages = [
        e
        for e in rapport.get("etages") or ()
        if isinstance(e, dict)
        and e.get("ok") is True
        and isinstance(e.get("niveau"), int)
        and not isinstance(e.get("niveau"), bool)
        and (e.get("alias") or "").strip()
    ]
    if not etages:
        return ""
    return min(etages, key=lambda e: e["niveau"])["alias"].strip()


def pont_libre(interfaces, depart=PONT_DEPART):
    """Le premier `vmbrN` que `/etc/network/interfaces` ne déclare pas, ou « ».

    LU sur le terrain, jamais supposé : reprendre un pont déclaré le
    reconfigurerait, et c'est le réseau d'autre chose.

    TROIS CAS RENDENT « », et ils disent tous la même chose : le terrain n'a
    pas été lu. un texte vide, un texte qui ne déclare aucune interface — un
    `ssh … cat` qui échoue imprime sa plainte, et une plainte n'est pas un
    terrain vierge — et un fichier qui DÉLÈGUE par `source`, car les ponts
    peuvent alors vivre ailleurs, ce que PVE fait par défaut pour sa SDN.
    Aucun numéro libre jusqu'à 99 rend « » aussi.
    """
    texte = interfaces or ""
    lignes = texte.splitlines()
    if any(
        l.split()[:1] in (["source"], ["source-directory"]) for l in lignes
    ):
        return ""
    if not any(l.split()[:1] in (["auto"], ["iface"]) for l in lignes):
        return ""
    for numero in range(max(0, int(depart)), 100):
        nom = f"vmbr{numero}"
        if not any(
            ligne.split()[1:2] == [nom]
            for ligne in texte.splitlines()
            if ligne.split()[:1] in (["auto"], ["iface"])
        ):
            return nom
    return ""


def cmds_pont(nom, cidr, uplink=""):
    """Les commandes qui posent le pont du banc, conscient des VLAN.

    Bâties par le module qui sait déjà poser un pont, avec son drapeau : une
    seconde strophe écrite ici dériverait de la première.
    """
    import sys

    if RACINE not in sys.path:
        sys.path.insert(0, RACINE)
    from script.proxmox import proxmox_deploy as pve

    return list(
        pve.bridge_setup_cmds(
            nom=nom, cidr=cidr, uplink=uplink, vlan_aware=True
        )
    )


def cmds_jeton(utilisateur=UTILISATEUR_API, jeton=JETON_API):
    """Les commandes qui créent l'utilisateur d'API et son jeton.

    L'utilisateur est créé AVANT le rôle, et le jeton en dernier : son secret
    ne s'affiche qu'à la création, et une commande qui échouerait après lui
    perdrait le seul moment où il est lisible.

    `--output-format json` : le secret se lit alors sans découper une phrase,
    qui change d'une version à l'autre.
    """
    u, j = shlex.quote(utilisateur), shlex.quote(jeton)
    return [
        f"pveum user list --output-format json | grep -q {u}"
        f" || pveum user add {u}",
        f"pveum acl modify / --users {u} --roles Administrator",
        f"pveum user token remove {u} {j} 2>/dev/null; true",
        f"pveum user token add {u} {j} --privsep 0 --output-format json",
    ]


def lit_jeton(sortie):
    """Le secret que rend `pveum user token add`, ou « ».

    NE SE JOURNALISE PAS, NE S'AFFICHE PAS : l'appelant le passe à
    l'environnement ou le chiffre, et rien d'autre. Rend « » plutôt qu'une
    chaîne douteuse quand la forme change — un secret tronqué donnerait un 401
    que rien n'explique.
    """
    texte = sortie or ""
    debut = texte.find("{")
    if debut < 0:
        return ""
    try:
        lu, _fin = json.JSONDecoder().raw_decode(texte[debut:])
    except ValueError:
        return ""
    valeur = lu.get("value") if isinstance(lu, dict) else None
    return valeur.strip() if isinstance(valeur, str) else ""


def environnement_api(
    hote, secret, utilisateur=UTILISATEUR_API, jeton=JETON_API
):
    """Les variables que le playbook du moteur lit en repli.

    `api_user` et `api_token_id` SE SÉPARENT parce que c'est proxmoxer qui
    recompose « utilisateur!nom » : lui passer la forme complète produit un 401
    muet, que le même jeton contredit en HTTP direct. Le playbook du moteur, lui,
    désamorce le piège en ne gardant que ce qui suit le « ! » — la forme courte
    n'est donc pas une exigence de ce chemin-là, mais elle reste la seule qui
    vaille partout.
    """
    if not (hote or "").strip() or not (secret or "").strip():
        return {}
    return {
        "PROXMOX_API_HOST": hote.strip(),
        "PROXMOX_API_USER": utilisateur,
        "PROXMOX_API_TOKEN_ID": jeton,
        "PROXMOX_API_TOKEN_SECRET": secret.strip(),
    }


def cmds_effacer_vm(vmid, nom):
    """Les commandes qui effacent une VM du banc, le nom VÉRIFIÉ d'abord.

    L'appelant confronte le nom avec `effacable` avant de jouer la suite : ces
    commandes ne protègent rien par elles-mêmes, elles supposent le constat
    fait.
    """
    return [
        f"qm stop {int(vmid)} --skiplock 1 || true",
        f"qm destroy {int(vmid)} --purge 1",
    ]


def effacable(nom_attendu, nom_vu):
    """Le VMID porte-t-il encore le nom que l'empreinte lui donne ?

    Appariement STRICT, comme celui du labo : un VMID réattribué porte un autre
    nom, et l'effacer détruirait le travail de quelqu'un d'autre. Une lecture
    vide REFUSE au lieu de conclure.
    """
    attendu = (nom_attendu or "").strip()
    return bool(attendu) and (nom_vu or "").strip() == attendu


def a_defaire(empreinte):
    """Ce que le banc a posé, dans l'ordre INVERSE de la pose.

    Les VM d'abord, le gabarit ensuite, le pont et l'utilisateur d'API en
    dernier. Défaire le pont avant les VM leur retirerait leur réseau sans les
    effacer, et un gabarit ne s'efface pas tant qu'un clone lié en dépend.
    L'écosystème part en dernier : son plan nomme les VM, et le rasage s'y
    appuie.
    """
    if empreinte is None or not nous(empreinte):
        return ()
    terrain = empreinte.terrain
    gestes = [
        Geste(terrain, VM, str(vmid), nom)
        for vmid, nom in reversed(empreinte.vms or ())
    ]
    if empreinte.modele:
        gestes.append(Geste(terrain, MODELE, str(empreinte.modele), GABARIT))
    if empreinte.pont:
        gestes.append(Geste(terrain, PONT, empreinte.pont, empreinte.pont))
    gestes.append(
        Geste(terrain, API, empreinte.utilisateur, empreinte.utilisateur)
    )
    gestes.append(
        Geste(terrain, ECO, empreinte.ecosysteme, empreinte.ecosysteme)
    )
    return tuple(gestes)


def nous(empreinte):
    """Cette empreinte est-elle celle du BANC ?

    Rien ne rattachait au banc les noms qu'elle porte : `lit_empreinte` valide
    des FORMES — un entier au-dessus de zéro, un nom non vide — jamais une
    appartenance. Une empreinte nommant un écosystème de production passait, et
    ses VM s'effaçaient dès que leur nom concordait.

    L'écosystème, l'utilisateur d'API et le terrain doivent être ceux que ce
    module NOMME. C'est la même idée que le `cree` du labo : « le seul champ qui
    dise que la machine est à NOUS ».
    """
    if empreinte is None:
        return False
    return (
        empreinte.ecosysteme == ECOSYSTEME
        and empreinte.utilisateur == UTILISATEUR_API
        and bool(empreinte.terrain)
    )


def lit_empreinte(texte):
    """L'`Empreinte` que porte `texte`, ou None.

    Fermée par défaut : un VMID qui n'est pas un entier au-dessus de zéro, ou
    une VM sans nom, font refuser TOUTE l'empreinte. Une empreinte partielle
    ferait effacer ce qu'elle nomme en laissant le reste, et le reste est
    justement ce qu'on ne saurait plus retrouver.
    """
    try:
        lu = json.loads(texte or "")
    except (ValueError, TypeError):
        return None
    if not isinstance(lu, dict):
        return None
    vms = []
    brutes = lu.get("vms")
    if brutes is not None and not isinstance(brutes, list):
        return None
    for brute in brutes or ():
        if not isinstance(brute, (list, tuple)) or len(brute) != 2:
            return None
        vmid, nom = brute
        if isinstance(vmid, bool) or not isinstance(vmid, int) or vmid < 1:
            return None
        if not isinstance(nom, str) or not nom.strip():
            return None
        if any(vmid == deja for deja, _n in vms):
            # DEUX VM SUR UN VMID N'ONT PAS DE MAÎTRE, comme deux pools sur un
            # VMID dans le devis. L'appelant confronte le nom geste par geste :
            # le premier refuserait, le second concorderait, et la destruction
            # partirait sur un enregistrement qui se contredit.
            return None
        vms.append((vmid, nom.strip()))
    modele = lu.get("modele") or 0
    if isinstance(modele, bool) or not isinstance(modele, int) or modele < 0:
        return None
    return Empreinte(
        terrain=str(lu.get("terrain") or ""),
        ecosysteme=str(lu.get("ecosysteme") or ""),
        pont=str(lu.get("pont") or ""),
        utilisateur=str(lu.get("utilisateur") or ""),
        modele=modele,
        vms=tuple(vms),
    )


def ecrit_empreinte(empreinte) -> str:
    """L'empreinte en JSON, telle qu'elle se relit.

    Rendue comme TEXTE et non écrite ici : le fichier se pose par l'appelant,
    qui sait où, et l'épreuve relit ce texte sans toucher au disque.
    """
    return json.dumps(
        {
            "terrain": empreinte.terrain,
            "ecosysteme": empreinte.ecosysteme,
            "pont": empreinte.pont,
            "utilisateur": empreinte.utilisateur,
            "modele": empreinte.modele,
            "vms": [list(v) for v in empreinte.vms],
        },
        sort_keys=True,
    )


def plan(passes, terrain):
    """Les étapes, dans l'ordre, avec la durée annoncée de chacune.

    IMPRIMÉ AVANT TOUTE CRÉATION, et c'est la règle de ce dossier : un plan
    qu'on lit après coup ne sert plus à décider.
    """
    etapes = [
        (f"terrain : {terrain or '(aucun)'}", ""),
        ("pont du banc, conscient des VLAN", "~30 s"),
        ("utilisateur d'API et son jeton", "~10 s"),
        ("gabarit doré", "~10 min"),
    ]
    for passe in passes or ():
        ou = (
            "par l'environnement"
            if passe == PASSE_ENV
            else "par la voûte, chemin de todo"
        )
        etapes += [
            (f"passe « {passe} » — {ou}", ""),
            ("  inventaire depuis le plan", "~5 s"),
            ("  clone d'une VM", "~4 min 30"),
            ("  déploiement de l'hôte", "~5 min"),
            ("  rasage", "~1 min"),
        ]
    return tuple(etapes)


def chemin_empreinte(base=""):
    """Où le banc note ce qu'il a posé.

    Le dossier du labo, partagé avec les rapports des descentes : ce qui se
    défait se cherche à un seul endroit.
    """
    racine = base or os.path.join(os.path.expanduser("~"), ".erplibre")
    return os.path.join(racine, "longtest", "setops_banc.json")


def dire_plan(passes, terrain):
    """Imprime le plan. Rien n'est créé par cette fonction."""
    print("── le plan ──")
    for quoi, duree in plan(passes, terrain):
        print(f"  {quoi}" + (f"   ({duree})" if duree else ""))


def dire_manquants(prealables):
    """Imprime ce qui manque, en distinguant l'absent de l'illisible."""
    for vu in manquants(prealables):
        marque = "✗" if vu.tenu is False else "?"
        print(f"  {marque} {vu.quoi}" + (f" — {vu.dit}" if vu.dit else ""))


def principal(argv=None):
    """La CLI du banc. Rend un code du vocabulaire clos."""
    import argparse

    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("--dry-run", action="store_true")
    analyseur.add_argument("--detruire", action="store_true")
    analyseur.add_argument(
        "--terrain",
        default="",
        help="l'alias ssh de la grappe jetable ; déduit du dernier étage posé",
    )
    analyseur.add_argument(
        "--passe",
        choices=PASSES,
        action="append",
        help="la passe à jouer ; les deux dans l'ordre si l'on n'en dit aucune",
    )
    args = analyseur.parse_args(argv)
    passes = tuple(args.passe) if args.passe else PASSES

    if args.detruire:
        return defaire(args.dry_run)

    terrain = args.terrain.strip() or terrain_deduit()
    dire_plan(passes, terrain)
    if args.dry_run:
        return SORTIE_OK
    print()
    print("  ⛔ les verbes du banc ne sont pas encore posés.")
    print("     Le plan ci-dessus est complet ; rien n'a été tenté.")
    return SORTIE_OUTILLAGE


def terrain_deduit():
    """Le terrain que le dernier étage posé par le labo offre, ou « »."""
    import sys

    if RACINE not in sys.path:
        sys.path.insert(0, RACINE)
    chemin = os.path.join(RACINE, "long_test")
    if chemin not in sys.path:
        sys.path.insert(0, chemin)
    try:
        import descente
    except ImportError:
        return ""
    return terrain_par_defaut(
        descente.dernier_rapport("deep_proxmox", "deep-pve")
    )


def defaire(dry_run=False):
    """Défait ce que l'empreinte nomme, ou dit pourquoi il ne défait rien.

    REFUSE PENDANT QU'UNE AUTRE ÉPREUVE TOURNE : elle pourrait être en train de
    poser ce que celle-ci s'apprête à effacer, et l'empreinte ne serait plus à
    jour de ce qu'elle a créé.
    """
    import sys

    chemin = os.path.join(RACINE, "long_test")
    if chemin not in sys.path:
        sys.path.insert(0, chemin)
    try:
        import descente
    except ImportError:
        # NE PAS SAVOIR N'EST PAS UNE PERMISSION. Le garde protège contre
        # l'effacement de ce qu'une autre épreuve est en train de poser ; sans
        # lui, on ne détruit pas.
        print("  ⛔ le verrou des épreuves longues est illisible.")
        return SORTIE_NON_CONCLUANTE
    vivante = descente.autre_descente()
    if vivante:
        print(f"  ⛔ {vivante} tourne : rien ne sera détruit.")
        return SORTIE_NON_CONCLUANTE
    try:
        with open(chemin_empreinte(), encoding="utf-8") as tenu:
            empreinte = lit_empreinte(tenu.read())
    except FileNotFoundError:
        print("  aucune empreinte : rien à défaire.")
        return SORTIE_OK
    except OSError as souci:
        # PRÉSENTE MAIS ILLISIBLE. Rendue en succès, `--detruire` annonçait
        # qu'il n'y avait rien à défaire pendant que des VM, un gabarit, un
        # pont et un utilisateur d'API Administrator restaient sur la grappe.
        print(f"  ⛔ empreinte illisible : {souci.strerror or souci}")
        return SORTIE_NON_CONCLUANTE
    if empreinte is None:
        print(f"  ⛔ empreinte illisible : {chemin_empreinte()}")
        return SORTIE_NON_CONCLUANTE
    gestes = a_defaire(empreinte)
    if not gestes:
        if not nous(empreinte):
            print(
                "  ⛔ cette empreinte n'est pas celle du banc : rien touché."
            )
            return SORTIE_NON_CONCLUANTE
        print("  l'empreinte ne nomme rien : rien à défaire.")
        return SORTIE_OK
    print(f"── à défaire, sur {empreinte.terrain} ──")
    for geste in gestes:
        print(f"  {geste.genre:<11} {geste.vise:<12} {geste.nom}")
    if dry_run:
        return SORTIE_OK
    print()
    print("  ⛔ les verbes du banc ne sont pas encore posés.")
    print("     Rien n'a été touché ; la liste ci-dessus est ce qui reste.")
    return SORTIE_OUTILLAGE


if __name__ == "__main__":
    raise SystemExit(principal())
