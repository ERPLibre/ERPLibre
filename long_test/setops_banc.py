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
import re
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

# L'UNDERLAY DU BANC, et il en faut un. Les secrets d'API du moteur ne vivent
# plus dans la voûte d'un locataire mais dans celle de l'underlay, chez
# l'hébergeur, et l'accès à la grappe REFUSE sans le lien qui le désigne : « pas
# de cluster a piloter ». Un banc à un seul dépôt ne peut donc pas matérialiser
# une VM. La convention du moteur nomme les deux moitiés de la même paire
# « SITE-<nom> » et « OPS-<nom> ».
UNDERLAY_BANC = "SITE-Fictif-Trachyte"
UTILISATEUR_API = "banc-fictif-trachyte@pve"
JETON_API = "banc"
GABARIT = "banc-fictif-trachyte-gabarit"

# Le pont du banc ne peut pas être celui du labo : le rendre conscient des VLAN
# changerait le réseau des usages déjà posés dessus. Son numéro de départ est
# haut pour la même raison — on cherche un nom libre, on ne prend pas `vmbr0`.
PONT_DEPART = 9

# L'INDEX DU BANC, et il se VÉRIFIE au lieu de se choisir. Tout l'adressage d'un
# écosystème dérive de ce seul entier : le 2e octet du supernet le porte TEL QUEL
# et la VLAN d'une zone vaut 1000 + index × 10 + zone. Deux dépôts frères qui le
# partageraient dériveraient les mêmes adresses, et le rasage du banc détruirait
# les VM de l'autre en croyant détruire les siennes. `index_libre` refuse ce cas.
# Sites et locataires tirent du MÊME espace, d'où deux valeurs et non une.
INDEX_ECOSYSTEME = 211
INDEX_UNDERLAY = 212

# Le port de l'API d'un Proxmox. Chaîne et non entier : le moteur le compare tel
# quel à ce que porte son fichier d'hébergeur.
PORT_API = "8006"

# LE BANC N'ÉCRIT PAS SA LISTE D'HÔTES, il demande au moteur laquelle amorcer.
# Le plan déclare quelle application vit sur quel hôte, et l'amorçage du socle
# s'en dérive : l'autorité de certification d'abord, puis ce qui s'enrôle auprès
# d'elle. Une seconde liste écrite ici dériverait de la première le jour où le
# modèle déplace une application.
CIBLE_AMORCAGE = "scripts/socle_amorcage.py"

# La forme d'un nom d'hôte, qui sert à distinguer un nom d'une PHRASE : le script
# qui dérive l'amorçage écrit ses erreurs sur la même sortie, et un adaptateur
# fermé par défaut ne doit pas prendre un message pour un hôte.
FORME_HOTE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")

# Les deux liens que le moteur lit, et il les lit PAR LEUR CHEMIN. Son playbook
# de clonage résout `<moteur>/underlay.yml` puis lit `<moteur>/instance/`, sans
# jamais regarder `SETOPS_UNDERLAY` ni `SETOPS_INSTANCE` : ces variables
# suffisent au chemin Python, pas à celui qui matérialise. Les deux noms sont
# ignorés du suivi de version du moteur, donc les poser ne salit pas son
# checkout.
LIEN_UNDERLAY = "underlay.yml"
LIEN_INSTANCE = "instance"
LIENS = (LIEN_UNDERLAY, LIEN_INSTANCE)

# L'ÉTAT D'UN LIEN, vocabulaire CLOS. A_POSER : rien ne porte ce nom. NOTRE :
# c'est déjà le lien du banc, le reposer ne change rien. OCCUPE : autre chose
# est là — un lien vers ailleurs, ou un vrai dossier. INCONNU : on n'a pas su
# regarder. Seuls A_POSER et NOTRE autorisent la suite.
A_POSER = "a_poser"
NOTRE = "notre"
OCCUPE = "occupe"
INCONNU = "inconnu"
ETATS_LIEN = (A_POSER, NOTRE, OCCUPE, INCONNU)

# Les genres de ce que le banc pose, et l'ORDRE INVERSE dans lequel ils se
# défont. Vocabulaire CLOS.
VM = "vm"
MODELE = "modele"
PONT = "pont"
API = "api"
ECO = "ecosysteme"
UNDERLAY = "underlay"
# Le lien MONTÉ dans le moteur, et la clé qui ouvre une voûte. Tous deux
# vivent HORS des deux dépôts — l'un dans le moteur, l'autre sous
# `~/.config` — donc effacer les dépôts ne les emporte pas.
LIEN = "lien"
CLE = "cle"
GENRES = (VM, MODELE, PONT, API, LIEN, ECO, UNDERLAY, CLE)


# LE NOM QUE `raser` EXIGE, et c'est un verrou et non une commodité : le moteur
# refuse si l'écosystème nommé ne correspond pas à celui qui est MONTÉ. Recopier
# un nom long oblige à regarder ce qu'on détruit.
INSTANCE = "INSTANCE"


class Etape(NamedTuple):
    """Une étape de la boucle : la cible du moteur, ses variables, sa durée.

    `confirmer` dit si le geste ÉCRIT. La ligne montrée porte toujours
    `CONFIRMER=`, si bien qu'un geste qui simule se distingue d'un geste qui
    écrit à la seule lecture, sans rien savoir du moteur.

    `mesuree` distingue une durée RELEVÉE d'une durée annoncée. Un plan qui les
    confond promet à l'opérateur un temps que personne n'a chronométré.
    """

    cible: str
    variables: tuple
    duree: str
    confirmer: bool
    mesuree: bool


# LA BOUCLE EST CELLE DU MOTEUR, pas une recomposition de ses morceaux.
# `reconstruire` enchaîne lui-même les flux, la création de la flotte, l'attente,
# l'amorçage du socle puis le déploiement par couches. L'ORDRE Y COMPTE : sans les
# flux D'ABORD, le dossier des règles dérivées est vide et le socle pose un
# pare-feu en refus par défaut SANS AUCUNE RÈGLE. La flotte monte, ssh répond
# depuis l'administration, et tout le reste est mur — une panne qui ne se voit ni
# à la création, ni dans un code de retour. Recomposer les étapes ici laisserait
# tomber celle-là le jour où le moteur en ajoute une.
#
# L'amorçage dérive SES hôtes du plan : l'autorité de certification d'abord,
# puis ce qui s'enrôle auprès d'elle.
ETAPES_BOUCLE = (
    Etape("instancier", (), "~5 s", False, True),
    Etape("instancier-appliquer", (("FORCE", "1"),), "~5 s", False, True),
    Etape("reconstruire", (), "~45 min", True, False),
    Etape("raser", ((INSTANCE, ECOSYSTEME),), "~2 min", True, False),
)


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

    DEUX DÉPÔTS, pas un. Le locataire porte le plan et ses hôtes ; l'underlay
    porte la grappe et la voûte au jeton. Les deux se posent, donc les deux se
    défont, et pas dans le même ordre : voir `a_defaire`.

    `liens` ET `cles` SONT ENREGISTRÉS, jamais redérivés. Le moteur nomme la clé
    d'une voûte d'après le dépôt qui la porte : le dépôt effacé, il ne la nomme
    plus, et une clé qu'on ne sait plus nommer reste sous `~/.config` pour
    toujours. Chaque chemin est donc gardé — et relu par `lit_empreinte`, qui
    refuse ce qui n'est pas au banc.
    """

    terrain: str
    ecosysteme: str
    underlay: str
    pont: str
    utilisateur: str
    modele: int
    vms: tuple
    liens: tuple = ()
    cles: tuple = ()


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


class Constat(NamedTuple):
    """Ce que le terrain dit du pont du banc, après coup.

    LES DEUX FAITS SE SÉPARENT parce que la pose les dissocie : son repli monte
    le pont par « ip link add », qui ne demande aucun filtrage de VLAN. Un pont
    DEBOUT MAIS NON FILTRANT est alors le pire des trois états, car la carte
    taguée d'une VM y démarre et reste injoignable — la panne ne se voit ni à la
    création, ni dans un code de retour.

    `vlan` vaut None quand le pont a été lu sans que le champ y soit : « pas vu »
    n'est pas « ne filtre pas ».
    """

    debout: bool
    vlan: bool | None

    @property
    def utilisable(self) -> bool:
        """Le banc peut-il clonner dessus ? Les deux faits, ou rien."""
        return self.debout and self.vlan is True


def cmds_constater_pont(nom):
    """La commande qui dit si le pont est debout et s'il filtre les VLAN.

    `ip -d link show` ET NON UNE LECTURE DE /sys : c'est la commande que le
    dépôt lit déjà pour les ponts, et sa ligne de détail porte
    « vlan_filtering 0|1 » — mesuré sur un Proxmox. Un second chemin vers le
    même fait dériverait du premier.
    """
    return [f"ip -d link show dev {shlex.quote(str(nom))}"]


def lit_constat_pont(sortie, nom):
    """Le `Constat` que porte cette sortie, ou None si elle ne se lit pas.

    TROIS RÉPONSES POUR TROIS CAS. `Constat(False, None)` dit « le pont n'est pas
    là », ce que le noyau AFFIRME par « Device "x" does not exist ». None dit
    « on n'a pas su lire », et sur ce doute l'appelant ne conclut rien. Les
    confondre ferait poser un pont par-dessus un autre, ou déclarer absent un
    pont qui filtre.
    """
    texte = sortie or ""
    nom = (nom or "").strip()
    if not nom:
        return None
    if f'Device "{nom}" does not exist' in texte:
        return Constat(debout=False, vlan=None)
    debout = any(
        re.match(rf"^\d+:\s+{re.escape(nom)}:", ligne)
        for ligne in texte.splitlines()
    )
    if not debout:
        return None
    # Le champ se lit par son NOM suivi de sa valeur : « vlan_default_pvid 1 »
    # porte le même chiffre et ne dit rien du filtrage.
    prise = re.search(r"\bvlan_filtering\s+(\d+)\b", texte)
    if prise is None:
        return Constat(debout=True, vlan=None)
    return Constat(debout=True, vlan=prise.group(1) == "1")


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


def lien_etat(chemin, vise):
    """L'état du lien `chemin` au regard de la cible `vise`. Vocabulaire clos.

    FERMÉ PAR DÉFAUT : ce qui ne se lit pas rend INCONNU, jamais A_POSER. Le
    banc pose ses liens DANS le moteur, et un moteur où une instance est déjà
    montée porte le travail d'un exploitant : remplacer son lien détournerait
    ses gestes vers l'écosystème du banc, dont le rasage détruit tout ce que
    l'inventaire nomme.

    `lexists` et non `exists` : un lien BRISÉ occupe le nom sans que sa cible
    existe, et `exists` le déclarerait absent — on écraserait alors le lien d'un
    exploitant dont le dépôt n'est simplement pas monté à cet instant.
    """
    if not vise:
        return INCONNU
    try:
        if not os.path.lexists(chemin):
            return A_POSER
        if not os.path.islink(chemin):
            return OCCUPE
        return NOTRE if os.readlink(chemin) == vise else OCCUPE
    except OSError:
        return INCONNU


def index_libre(instances, voulu):
    """L'index `voulu` est-il libre parmi `instances` ? None si on ne sait pas.

    `instances` est ce que le moteur découvre chez ses dossiers frères. Une
    découverte qui n'aboutit pas REFUSE au lieu de conclure : un index déjà pris
    dérive les mêmes adresses et les mêmes VLAN pour deux écosystèmes, et rien
    dans la suite ne le signalerait.

    Une entrée sans index déclaré ne réserve rien — la découverte du moteur
    l'ignore elle aussi, donc elle ne peut pas entrer en conflit.
    """
    if instances is None:
        return None
    try:
        pris = {
            int(une["index"])
            for une in instances
            if une.get("index") is not None
        }
        return int(voulu) not in pris
    except (AttributeError, TypeError, ValueError):
        return None


def texte_underlay(noeud, pont, index=INDEX_UNDERLAY):
    """Le `underlay.yml` du dépôt d'underlay du banc, ou « ».

    LE BLOC N'EST JAMAIS VIDE, et ce n'est pas un choix de style : le lecteur du
    moteur rend `data.get("underlay") or None`, si bien qu'un `underlay: {}` se
    lit exactement comme un fichier ABSENT — l'accès à la grappe refuse alors
    « pas de cluster à piloter » sans dire que le fichier est là.

    `index` EST DÉCLARÉ, sinon le site reste invisible : la découverte des
    dossiers frères passe tout `SITE-*/underlay.yml` qui n'en porte pas, et le
    site n'entre dans aucun compte.

    Le lien de transit porte `passerelle_sortie`, faute de quoi la flotte est
    routée jusqu'à la bordure puis muette — la panne la plus coûteuse à
    diagnostiquer de ce fichier.
    """
    if not (noeud or "").strip() or not (pont or "").strip():
        return ""
    i = int(index)
    n, p = noeud.strip(), pont.strip()
    return f"""---
# Underlay du BANC — grappe jetable, adresses inventées. Aucun équipement réel
# n'est décrit ici : le banc éprouve le moteur, pas une fabric.
underlay:
  index: {i}
  routeur: banc-switch-01
  dialecte: cisco
  stp:
    mode: rstp
    topologie: etoile
  reseaux:
    - nom: management
      description: Gestion de l'hyperviseur jetable
      vlan: 10
      sous_reseau: 10.{i}.0.0/24
      passerelle: 10.{i}.0.1
      mtu: 1500
    - nom: transit-frontiere
      description: Lien routeur <-> pare-feu de bordure
      vlan: 40
      sous_reseau: 10.{i}.4.0/29
      passerelle: 10.{i}.4.6
      passerelle_sortie: 10.{i}.4.1
      mtu: 1500
  hotes:
    - nom: banc-switch-01
      reseau: management
      ip: 10.{i}.0.1
    - {{ nom: banc-switch-01, role: switch, reseau: transit-frontiere, ip: 10.{i}.4.6 }}
    - {{ nom: banc-parefeu-1, role: frontiere, reseau: transit-frontiere, ip: 10.{i}.4.1 }}
    - {{ nom: {n}, role: hyperviseur, reseau: management, ip: 10.{i}.0.41, via: {p} }}
"""


def texte_hebergeur(hote, noeud, stockage, pont, utilisateur=UTILISATEUR_API):
    """Le `proxmox-hebergeur.yml` du dépôt d'underlay, ou « ».

    QUATRE CLÉS SEULEMENT APPARTIENNENT À L'HÉBERGEUR — l'hôte d'API, son
    utilisateur, son port, la validation TLS ; le placement d'un clone appartient
    au locataire, qui choisit où se poser. Les nœuds, stockages et ponts décrivent
    la grappe, donc l'hébergeur les porte aussi.

    LE SECRET N'EST PAS ICI. Ce fichier voyage avec un dépôt ; le jeton vit dans
    la voûte chiffrée à côté, et c'est toute la raison d'être des deux fichiers.

    `proxmox_validate_certs: false` : une grappe jetable porte un certificat
    auto-signé qu'aucune autorité connue du moteur ne contresigne.
    """
    if not all((vu or "").strip() for vu in (hote, noeud, stockage, pont)):
        return ""
    return f"""---
# La grappe du BANC, relevée sur elle et non écrite de mémoire. Sans secret.
proxmox_api_host: {hote.strip()}
proxmox_api_port: '{PORT_API}'
proxmox_api_user: {utilisateur}
proxmox_validate_certs: false
proxmox_noeuds:    [{noeud.strip()}]
proxmox_stockages: [{stockage.strip()}]
proxmox_ponts:     [{pont.strip()}]
"""


def texte_voute(secret, utilisateur=UTILISATEUR_API, jeton=JETON_API):
    """Le CLAIR de `underlay.vault.yml`, à chiffrer. Rend « » sans secret.

    NE SE POSE JAMAIS EN CLAIR SUR LE DISQUE. L'appelant le passe à
    `ansible-vault encrypt` par l'ENTRÉE STANDARD : écrit d'abord puis chiffré,
    le secret resterait dans les blocs libérés et dans toute sauvegarde prise
    entre les deux gestes.

    L'IDENTIFIANT EST LE NOM SEUL, sans « utilisateur! » devant : le client d'API
    recompose la forme complète à partir des deux valeurs, et la lui donner déjà
    composée produit un 401 que le même jeton contredit en HTTP direct.

    CETTE VOÛTE GAGNE sur celle du locataire, chez les deux lecteurs qui les
    superposent. Le jeton n'a donc à vivre qu'ici.
    """
    if not (secret or "").strip():
        return ""
    return f"""---
proxmox_api_user: {utilisateur}
proxmox_api_token_id: {jeton}
proxmox_api_token_secret: {secret.strip()}
"""


def lit_amorcage(sortie):
    """Les hôtes d'amorçage du socle, dans l'ORDRE du moteur. Ou None.

    L'ORDRE EST CELUI DU MOTEUR, pas celui du banc : l'autorité de certification
    vient avant ce qui s'enrôle auprès d'elle, et cette précédence est déclarée
    dans le plan. Le banc la LIT.

    Fermé par défaut : une ligne qui n'a pas la forme d'un nom d'hôte, ou un nom
    qui revient deux fois, fait refuser TOUTE la lecture. Le script écrit ses
    erreurs sur cette même sortie, et une liste dont une entrée est une phrase
    ferait activer un hôte qui n'existe pas dans le plan — donc un plan dont
    aucun hôte n'est ce qu'on croit.

    Une sortie sans aucune ligne rend `()` : « rien à nommer » est une réponse,
    et c'est à l'appelant de refuser d'amorcer sans hôte.
    """
    if sortie is None:
        return None
    vus = []
    for ligne in sortie.splitlines():
        nom = ligne.strip()
        if not nom:
            continue
        if not FORME_HOTE.match(nom) or nom in vus:
            return None
        vus.append(nom)
    return tuple(vus)


def active_les_hotes(texte, hotes):
    """`texte` avec l'`etat:` de CHACUN de `hotes` porté à « actif ». Ou None.

    TOUT OU RIEN. Un plan où seul le premier des hôtes d'amorçage serait actif se
    déploie jusqu'à l'autorité de certification puis refuse : le second n'est pas
    dans l'inventaire actif, donc le groupe dont il dépend n'y est pas non plus.
    Un plan à moitié activé coûte plus cher qu'un refus, parce que la moitié
    faite a déjà créé des machines.

    Sans hôte à activer, REFUSE : un plan dont aucun hôte n'est actif produit un
    inventaire vide, où la matérialisation et le rasage sortent à zéro sans avoir
    rien fait.
    """
    if not hotes:
        return None
    courant = texte
    for hote in hotes:
        courant = active_un_hote(courant, hote)
        if courant is None:
            return None
    return courant


def active_un_hote(texte, hote):
    """`texte`, le seul `etat:` de `hote` porté à « actif ». None si refus.

    CHIRURGICAL : un attribut d'une ligne change, tout le reste est rendu tel
    quel, commentaires compris. Réécrire le plan en entier le ferait diverger du
    modèle livré à chaque évolution de celui-ci.

    `etat: actif` COMMANDE TOUTE LA BOUCLE. Le générateur d'inventaire range
    dans `hotes_actifs` ce qui porte EXACTEMENT « actif » et tout le reste dans
    `hotes_planifies` ; les modèles livrés déclarent « planifie ». Un plan
    recopié sans cette bascule produit un inventaire dont `hotes_actifs` est
    vide — et la matérialisation comme le rasage sortent alors à ZÉRO sans avoir
    rien fait, ce qui se lit comme une réussite.

    REFUSE plutôt que de deviner : hôte absent, déclaré deux fois, ou ligne sans
    `etat:` à porter.
    """
    if not (texte or "") or not (hote or "").strip():
        return None
    nom = re.escape(hote.strip())
    lignes = (texte or "").splitlines(keepends=True)
    vus = [i for i, l in enumerate(lignes) if re.match(rf"\s*{nom}\s*:", l)]
    if len(vus) != 1:
        return None
    ligne = lignes[vus[0]]
    if len(re.findall(r"\betat\s*:\s*\w+", ligne)) != 1:
        return None
    lignes[vus[0]] = re.sub(r"\betat(\s*:\s*)\w+", r"etat\g<1>actif", ligne)
    return "".join(lignes)


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
    LES LIENS PARTENT AVANT LES DÉPÔTS. Tant qu'ils sont montés, les gestes du
    moteur agissent ; le dépôt retiré sous un lien qui tient, le moteur nomme un
    inventaire qui n'existe plus et refuse en parlant d'une instance absente au
    lieu d'une instance démontée. Démonter d'abord rend l'état lisible.

    L'écosystème part ensuite : son plan nomme les VM, et le rasage s'y appuie.
    L'UNDERLAY PART APRÈS LUI, et c'est lui qui borne tout l'ordre : raser le
    locataire passe par la grappe, la grappe se joint par le jeton, et le jeton
    vit dans la voûte de l'underlay. Le défaire plus tôt retirerait au banc le
    moyen de défaire le reste.

    LES CLÉS PARTENT EN DERNIER, pour la même raison poussée d'un cran : la clé
    ouvre la voûte qui porte le jeton. Elle survit donc à tout ce qui passe par
    la grappe, et ne s'efface qu'une fois qu'il n'y a plus rien à joindre.
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
    gestes += [
        Geste(terrain, LIEN, chemin, os.path.basename(chemin))
        for chemin in empreinte.liens or ()
    ]
    gestes.append(
        Geste(terrain, ECO, empreinte.ecosysteme, empreinte.ecosysteme)
    )
    gestes.append(
        Geste(terrain, UNDERLAY, empreinte.underlay, empreinte.underlay)
    )
    gestes += [
        Geste(terrain, CLE, chemin, os.path.basename(chemin))
        for chemin in empreinte.cles or ()
    ]
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
        and empreinte.underlay == UNDERLAY_BANC
        and empreinte.utilisateur == UTILISATEUR_API
        and bool(empreinte.terrain)
    )


def cle_du_banc(chemin):
    """Ce chemin de clé est-il celui d'une voûte du BANC ?

    `--detruire` EFFACE CE QUE L'EMPREINTE NOMME, et l'empreinte est un fichier
    JSON qu'un éditeur ouvre. Sans cette épreuve, y écrire le chemin de la clé
    de voûte d'une production suffirait à la faire effacer — la clé sans
    laquelle plus rien ne s'y déchiffre, et qu'aucune sauvegarde de dépôt ne
    contient puisqu'elle vit exprès dehors.

    Le moteur nomme une clé d'après son dépôt, en minuscules. Seuls les deux
    dépôts du banc y répondent. L'épreuve porte sur le NOM DE BASE : elle dit
    « ce n'est pas une clé du banc », pas « ce chemin est sûr ».
    """
    attendus = {
        f"setops-vault-{nom.lower()}" for nom in (ECOSYSTEME, UNDERLAY_BANC)
    }
    return os.path.basename((chemin or "").rstrip(os.sep)) in attendus


def lien_du_banc(chemin):
    """Ce chemin de lien est-il l'un des deux que le banc monte ?

    Même raison que pour les clés, et même portée : le NOM DE BASE doit être
    l'un des deux que le moteur lit. Ce que le verbe y ajoute est de n'effacer
    qu'un LIEN — jamais un dossier, jamais un fichier ordinaire.
    """
    return os.path.basename((chemin or "").rstrip(os.sep)) in LIENS


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
    chemins = {}
    for cle, appartient in (("liens", lien_du_banc), ("cles", cle_du_banc)):
        brutes = lu.get(cle)
        if brutes is not None and not isinstance(brutes, list):
            return None
        vues = []
        for brute in brutes or ():
            # UN CHEMIN QUI N'EST PAS AU BANC FAIT REFUSER TOUTE L'EMPREINTE, et
            # non seulement lui : une empreinte à qui l'on a ajouté une ligne
            # n'est plus celle que le banc a écrite, et ce qu'elle nomme
            # d'ailleurs ne se vérifie pas.
            if not isinstance(brute, str) or not appartient(brute):
                return None
            vues.append(brute)
        chemins[cle] = tuple(vues)
    return Empreinte(
        terrain=str(lu.get("terrain") or ""),
        ecosysteme=str(lu.get("ecosysteme") or ""),
        underlay=str(lu.get("underlay") or ""),
        pont=str(lu.get("pont") or ""),
        utilisateur=str(lu.get("utilisateur") or ""),
        modele=modele,
        vms=tuple(vms),
        liens=chemins["liens"],
        cles=chemins["cles"],
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
            "underlay": empreinte.underlay,
            "pont": empreinte.pont,
            "utilisateur": empreinte.utilisateur,
            "modele": empreinte.modele,
            "vms": [list(v) for v in empreinte.vms],
            "liens": list(empreinte.liens),
            "cles": list(empreinte.cles),
        },
        sort_keys=True,
    )


def plan(passes, terrain):
    """Les étapes, dans l'ordre, avec la durée annoncée de chacune.

    IMPRIMÉ AVANT TOUTE CRÉATION, et c'est la règle de ce dossier : un plan
    qu'on lit après coup ne sert plus à décider.

    UNE DURÉE ANNONCÉE LE DIT. Les deux gestes d'inventaire sont chronométrés ;
    la reconstruction et le rasage ne le sont pas encore, et un plan qui les
    donnerait du même ton promettrait un temps que personne n'a relevé.
    """
    etapes = [
        (f"terrain : {terrain or '(aucun)'}", ""),
        (f"underlay du banc : {UNDERLAY_BANC}", "~20 s"),
        (f"locataire du banc : {ECOSYSTEME}", "~20 s"),
        # LES LIENS AVANT LES CLÉS, parce que le moteur nomme la clé de la voûte
        # de l'hébergeur en RÉSOLVANT le lien. Sans lui, il ne la nomme pas.
        (f"les {len(LIENS)} liens du moteur", "~1 s"),
        (f"les {len(LIENS)} clés de voûte", "~1 s"),
        ("pont du banc, conscient des VLAN", "~30 s"),
        ("utilisateur d'API et son jeton", "~10 s"),
        ("gabarit doré, agent qemu compris", "~10 min"),
    ]
    for passe in passes or ():
        ou = (
            "par l'environnement"
            if passe == PASSE_ENV
            else "par la voûte, chemin de todo"
        )
        etapes.append((f"passe « {passe} » — {ou}", ""))
        etapes += [
            (
                f"  make {etape.cible}"
                + ("  (écrit)" if etape.confirmer else ""),
                etape.duree + ("" if etape.mesuree else " annoncé"),
            )
            for etape in ETAPES_BOUCLE
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
