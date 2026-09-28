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
PONT = "pont"
API = "api"
ECO = "ecosysteme"
UNDERLAY = "underlay"
# Le lien MONTÉ dans le moteur, et la clé qui ouvre une voûte. Tous deux
# vivent HORS des deux dépôts — l'un dans le moteur, l'autre sous
# `~/.config` — donc effacer les dépôts ne les emporte pas.
LIEN = "lien"
CLE = "cle"
# L'interface ROUTÉE d'une VLAN, posée SUR le pont. Son propre genre parce
# qu'elle a sa propre strophe : retirer celle du pont ne l'emporte pas, et une
# interface orpheline reste à réclamer une passerelle sur un pont disparu.
SVI = "svi"
# LE GABARIT N'EST PAS UN GENRE, et c'est une garantie et non un oubli : le
# banc ne le fabrique pas — sa procédure impose une installation depuis
# l'ISO — donc il ne peut pas l'avoir posé, donc il ne doit jamais le
# défaire. Le détruire coûterait à l'exploitant la réinstallation entière,
# et un genre qui existe finit par trouver un appelant.
GENRES = (VM, SVI, PONT, API, LIEN, ECO, UNDERLAY, CLE)


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
    vms: tuple
    liens: tuple = ()
    cles: tuple = ()
    zones: tuple = ()


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


class Mesures(NamedTuple):
    """Ce que le banc a RELEVÉ du terrain avant de rien poser.

    Chaque champ vaut None quand la mesure n'a pas abouti, ce qui se distingue
    d'une mesure qui a répondu « non ». Les préalables lisent cette différence :
    l'écran doit dire « pas su regarder » là où c'est le cas, faute de quoi on
    cherche une machine en panne quand c'est la sonde qui n'est pas passée.
    """

    terrain: str
    elevation: str | None
    liens: tuple
    index_libre: bool | None
    pont: str
    vmid_gabarit: int
    gabarit: str | None
    noeud: str = ""
    stockage: str = ""
    uplink: str = ""
    adresse_api: str = ""


def prealables(mesures):
    """Les conditions à tenir avant que quoi que ce soit soit créé.

    PURE : elle ne mesure rien, elle JUGE des mesures. C'est ce qui rend
    l'ordre des refus éprouvable sans machine, et ce qui fait qu'un refus
    s'explique toujours de la même façon quel que soit le terrain.

    L'ordre suit le coût de ce qu'on éviterait : le terrain d'abord, sans quoi
    aucune autre mesure ne veut rien dire ; puis ce qui appartient à autrui —
    les liens du moteur — puis ce que le banc aurait à choisir.
    """
    vu = mesures
    gabarit = vu.gabarit
    return (
        Prealable(
            quoi="un terrain est désigné",
            tenu=bool((vu.terrain or "").strip()),
            dit=""
            if (vu.terrain or "").strip()
            else "aucun étage, aucun alias",
        ),
        Prealable(
            quoi="le terrain se joue, élévation connue",
            tenu=vu.elevation in (TEL_QUEL, ELEVE)
            if vu.elevation is not None
            else None,
            dit=(
                "sudo réclamerait un mot de passe, qu'une session sans"
                " terminal ne peut pas taper"
                if vu.elevation == IMPOSSIBLE
                else ""
            ),
        ),
        Prealable(
            quoi=f"les {len(LIENS)} liens du moteur sont libres ou à nous",
            tenu=(
                all(etat in (A_POSER, NOTRE) for etat in vu.liens)
                if vu.liens and None not in vu.liens
                else None
            ),
            dit=", ".join(
                f"{nom} : {etat}"
                for nom, etat in zip(LIENS, vu.liens or ())
                if etat not in (A_POSER, NOTRE)
            ),
        ),
        Prealable(
            quoi=f"l'index {INDEX_ECOSYSTEME} est libre chez les frères",
            tenu=vu.index_libre,
            dit="" if vu.index_libre else "un dépôt frère le porte déjà",
        ),
        Prealable(
            quoi="un nom de pont est libre sur le terrain",
            tenu=bool((vu.pont or "").strip()),
            dit=""
            if (vu.pont or "").strip()
            else "aucun nom libre, ou la configuration réseau n'a pas été lue",
        ),
        Prealable(
            quoi="un VMID de gabarit est libre sur la grappe",
            tenu=bool(vu.vmid_gabarit),
            dit="" if vu.vmid_gabarit else "la grappe n'a pas dit ses VMID",
        ),
        Prealable(
            quoi="la grappe nomme un nœud en ligne",
            tenu=bool((vu.noeud or "").strip()),
            dit=""
            if (vu.noeud or "").strip()
            else "aucun nœud en ligne, ou la grappe n'a pas répondu",
        ),
        Prealable(
            quoi=f"un stockage accepte des {CONTENU_IMAGES}",
            tenu=bool((vu.stockage or "").strip()),
            dit=""
            if (vu.stockage or "").strip()
            else "aucun stockage ne DÉCLARE accepter des images de disque",
        ),
        Prealable(
            quoi="le terrain dit par où il sort, et sous quelle adresse",
            tenu=bool((vu.uplink or "").strip())
            and bool((vu.adresse_api or "").strip()),
            dit=""
            if (vu.uplink or "").strip()
            else "aucune route par défaut : le masquage viserait dans le vide",
        ),
        Prealable(
            quoi=f"le gabarit « {GABARIT} » est conforme",
            tenu=(gabarit == GABARIT_CONFORME)
            if gabarit is not None
            else None,
            dit=dit_gabarit(gabarit) if gabarit is not None else "",
        ),
    )


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


def pont_du_banc(interfaces, deja, depart=PONT_DEPART):
    """Le pont à employer : le SIEN s'il est déjà déclaré, sinon le premier
    libre. Ou « ».

    RÉUTILISER LE SIEN, et non en prendre un de plus. Le premier nom libre change
    dès que le banc a posé un pont : une exécution qui ne relirait pas son
    empreinte en poserait un second à chaque fois, et n'en défairait qu'un — le
    précédent resterait, avec son masquage, sur un réseau que plus rien ne
    nomme. C'est la même distinction que pour ses liens et son index : « déjà à
    nous » n'est pas « occupé ».

    `deja` est le nom que porte l'empreinte, ou « ». Il n'est repris que s'il est
    DÉCLARÉ sur le terrain : nommé dans l'empreinte mais absent de l'hôte, il a
    été retiré à la main, et le reprendre supposerait une strophe qui n'existe
    plus.
    """
    texte = interfaces or ""
    voulu = (deja or "").strip()
    if voulu and any(
        ligne.split()[1:2] == [voulu]
        for ligne in texte.splitlines()
        if ligne.split()[:1] in (["auto"], ["iface"])
    ):
        return voulu
    return pont_libre(texte, depart)


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


# Borne d'une CIBLE du moteur. `reconstruire` crée les VM, attend qu'elles
# répondent, amorce l'autorité de certification puis déploie par couches : elle
# dure des dizaines de minutes sur un hyperviseur imbriqué. La borne existe pour
# qu'une grappe qui ne répond plus rende la main, pas pour hâter le geste.
DELAI_ETAPE = 7200

# Borne d'une commande jouée sur le terrain. Un `qm destroy` ou un `apt` prend
# des minutes sur un Proxmox imbriqué ; la borne existe pour qu'une grappe qui
# ne répond plus rende la main.
DELAI_TERRAIN = 900

# La marque qui remplace un secret dans un texte qu'on montre. Sa longueur ne
# dit rien de celle du secret : un gabarit de longueur est déjà un indice.
EXPURGE = "«secret retiré»"


# COMMENT JOUER SUR CE TERRAIN, vocabulaire CLOS. TEL_QUEL : la session est déjà
# root, rien à envelopper. ELEVE : il faut passer par `sudo`, qui répond sans mot
# de passe. IMPOSSIBLE : il le faudrait et `sudo` demanderait un mot de passe —
# ce qu'une session sans terminal ne peut pas taper. None, hors vocabulaire, dit
# qu'on n'a pas su lire.
TEL_QUEL = "tel_quel"
ELEVE = "eleve"
IMPOSSIBLE = "impossible"
ELEVATIONS = (TEL_QUEL, ELEVE, IMPOSSIBLE)

# Ce que la sonde d'élévation imprime. Deux faits sur deux lignes plutôt que
# deux commandes : l'exécuteur ne rend que la sortie de la DERNIÈRE, et la
# première serait perdue.
SONDE_ELEVATION = (
    "printf 'uid=%s\\n' \"$(id -u)\"; "
    "sudo -n true 2>/dev/null && echo 'sudo=oui' || echo 'sudo=non'"
)


def cmds_elevation():
    """La commande qui dit comment jouer sur ce terrain.

    DEUX QUESTIONS, et la seconde n'a de sens que si la première dit non :
    sommes-nous root, et sinon `sudo` répond-il SANS mot de passe ? Une session
    ssh sans terminal ne peut pas en taper un — un sudo interactif n'échoue pas,
    il ATTEND, et l'épreuve pend jusqu'à sa borne.
    """
    return [SONDE_ELEVATION]


def lit_elevation(sortie):
    """Comment jouer sur ce terrain, ou None si la sonde ne s'est pas lue.

    Les outils d'un hyperviseur vivent dans `/usr/sbin`, que le PATH d'une
    session ssh non interactive ne porte pas, et son démon de grappe ne parle
    qu'à root : une commande jouée sans élévation ne dit pas « refusé », elle
    dit « commande introuvable » ou se plaint de son canal de communication.

    Fermé par défaut : les DEUX lignes sont exigées. Une sonde qui n'aurait
    imprimé que l'une, parce que la seconde a été coupée, ferait conclure sur la
    moitié de la réponse.
    """
    texte = sortie or ""
    uid, sudo = None, None
    for ligne in texte.splitlines():
        nu = ligne.strip()
        if nu.startswith("uid="):
            reste = nu[4:].strip()
            uid = int(reste) if reste.isdigit() else None
        elif nu.startswith("sudo="):
            reponse = nu[5:].strip()
            sudo = reponse if reponse in ("oui", "non") else None
    if uid is None or sudo is None:
        return None
    if uid == 0:
        return TEL_QUEL
    return ELEVE if sudo == "oui" else IMPOSSIBLE


def elevation_du_terrain(terrain):
    """Sonde `terrain` et rend son élévation, ou None.

    La sonde elle-même se joue TEL_QUEL : c'est justement ce qu'elle mesure, et
    l'envelopper d'un `sudo` dont on ne sait pas encore s'il répond ferait pendre
    la mesure qui devait l'éviter.
    """
    fait = joue_sur(terrain, cmds_elevation(), TEL_QUEL, delai=60)
    return lit_elevation(fait.sortie) if fait.reussi else None


class Fait(NamedTuple):
    """Ce qu'une suite de commandes a rendu sur le terrain.

    `code` vaut None quand ssh lui-même n'a pas pu tourner — hôte inconnu,
    binaire absent, délai dépassé. C'est un verdict, pas une absence : un
    appelant qui le confondrait avec zéro annoncerait une réussite.

    `jouees` compte les commandes qui ont VRAIMENT tourné. Une suite qui
    s'arrête à la troisième sur cinq a laissé la grappe à moitié faite, et
    c'est ce nombre qui dit où reprendre — pas le code de retour.
    """

    code: int | None
    sortie: str
    jouees: int

    @property
    def reussi(self) -> bool:
        """Tout a rendu zéro, ET quelque chose a tourné.

        `jouees > 0` N'EST PAS UNE PRÉCAUTION DE STYLE. Un constructeur de
        commandes qui ne peut pas bâtir refuse par une liste VIDE, et une suite
        vide rendrait « code 0, rien à signaler » : le pont n'aurait jamais été
        posé et l'écran dirait qu'il l'est. C'est le même défaut qu'un verdict
        jeté, arrivé par l'autre bout.
        """
        return self.code == 0 and self.jouees > 0


def ssh_argv(terrain, commande, elevation=TEL_QUEL):
    """L'argv qui joue `commande` sur `terrain`, ou None.

    Bâti par le module du labo qui sait déjà joindre une machine : un second
    jeu d'options dériverait du premier, et c'est l'option manquante qui pend
    une épreuve lancée pour des heures sans surveillance.

    `terrain` est un ALIAS ssh, pas une adresse : il porte son utilisateur, son
    port et son rebond dans la configuration de ssh, et l'alias reste le même
    quand l'adresse change.

    UNE SEULE OPTION S'AJOUTE, et ce n'est pas un second jeu. Le banc LIT la
    sortie de ses commandes ; les appelants du labo n'en lisent que le code de
    retour. Or ssh écrit de lui-même « Permanently added ... to the list of
    known hosts » sur la sortie d'erreur à chaque connexion, puisque le fichier
    des hôtes connus est jeté — une ligne qui n'est pas la réponse de la
    commande, qui porte une adresse, et qui fait passer une réponse d'une ligne
    pour une réponse bavarde. `LogLevel=ERROR` la retire en laissant passer les
    vraies erreurs, celles qui disent pourquoi un pas a échoué.
    """
    import sys

    if not (terrain or "").strip() or not (commande or "").strip():
        return None
    chemin = os.path.join(RACINE, "long_test")
    if chemin not in sys.path:
        sys.path.insert(0, chemin)
    try:
        import install_nixos
    except ImportError:
        return None
    base = install_nixos.ssh_base(terrain.strip())
    # L'ENVELOPPE VIENT DU DÉPÔT. « sudo sh -c '<tout>' » et non « sudo <tout> » :
    # une commande du banc est souvent une SUITE, avec un `||`, un tube ou une
    # redirection, et préfixer n'élèverait que son premier mot.
    from script.remote.appliance_ssh import wrap_privilege

    joue = wrap_privilege(commande, "sudo" if elevation == ELEVE else "")
    return tuple(base[:1] + ["-o", "LogLevel=ERROR"] + base[1:] + [joue])


def joue_sur(terrain, cmds, elevation, delai=DELAI_TERRAIN):
    """Joue `cmds` sur `terrain`, dans l'ordre, et rend un `Fait`. Ne lève jamais.

    `elevation` EST EXIGÉE, sans valeur par défaut : on ne joue pas sur une
    machine sans avoir décidé comment. Un défaut la ferait omettre, et une
    commande d'hyperviseur jouée sans élévation se plaint de son canal de
    communication au lieu de dire « refusé » — un diagnostic qui envoie
    chercher un démon en panne là où il n'y a qu'un compte sans droits. Toute
    valeur hors de TEL_QUEL et ELEVE fait refuser SANS RIEN JOUER.

    S'ARRÊTE À LA PREMIÈRE QUI ÉCHOUE. Les commandes du banc se suivent — un
    pont avant la carte qui s'y branche, un utilisateur avant son jeton — et
    poursuivre après un échec joue la suite sur un terrain qui n'est plus celui
    qu'elle suppose. Le `Fait` rendu porte la sortie de CELLE qui a échoué,
    parce que c'est elle qui dit pourquoi.

    LA SORTIE N'EST PAS EXPURGÉE ICI. Elle ne peut pas l'être : le secret qu'un
    pas rend n'est connu qu'après l'avoir lue. L'appelant l'extrait, puis passe
    par `expurge` pour tout ce qu'il montre ou journalise.
    """
    if elevation not in (TEL_QUEL, ELEVE):
        return Fait(None, "", 0)
    sortie, jouees = "", 0
    for commande in cmds or ():
        argv = ssh_argv(terrain, commande, elevation)
        if argv is None:
            return Fait(None, sortie, jouees)
        vu = runner_du_banc().jouer(argv, delai=delai)
        jouees += 1
        if vu.code != 0:
            return Fait(vu.code, vu.sortie, jouees)
        sortie = vu.sortie
    return Fait(0, sortie, jouees)


def runner_du_banc():
    """L'exécuteur du dépôt, chargé à l'appel.

    Chargé ici et non en tête de fichier : le banc se lit et s'éprouve sans
    que le paquet du menu soit importable, et une épreuve du plan n'a pas
    besoin de lui.
    """
    import sys

    if RACINE not in sys.path:
        sys.path.insert(0, RACINE)
    from script.setops import runner

    return runner


def expurge(texte, secret):
    """`texte`, chaque occurrence de `secret` remplacée par une marque.

    TOUT CE QUE LE BANC MONTRE OU JOURNALISE PASSE PAR ICI. Le secret d'un
    jeton d'API ne s'affiche qu'à sa création : il traverse la mémoire du banc
    entre la grappe qui le rend et la voûte qui le chiffre, et un écran ou un
    journal qui l'attrape au passage le rend permanent.

    Un secret vide n'expurge RIEN, et c'est correct : il n'y a rien à retirer,
    et remplacer la chaîne vide marquerait chaque caractère du texte.
    """
    if not (secret or "").strip():
        return texte or ""
    return (texte or "").replace(secret.strip(), EXPURGE)


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


# LE RÉSEAU DU BANC, et il n'est pas celui du labo. Le labo pose son pont interne
# en 10.10.10.1/24 ; sur un plancher où il l'a déjà fait, un banc qui reprendrait
# ce réseau y dupliquerait l'adresse de la passerelle, et les deux ponts se
# disputeraient le trafic. Le NOM du pont se cherche libre — `pont_libre` — donc
# son réseau doit l'être aussi, et le plus simple est qu'il soit à lui seul.
#
# Hors du 10/8 exprès : l'adressage d'un locataire y dérive tout son supernet de
# son index, et une fabrication posée dans la même classe A pourrait y tomber.
CIDR_PONT_BANC = "192.168.212.1/24"


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


# Où le banc commence à chercher un VMID libre pour son gabarit. 9000 est la
# convention du moteur pour un modèle, et sa valeur par défaut ; le banc part de
# là et monte, parce qu'une grappe qu'on possède en a peut-être déjà un.
VMID_GABARIT_DEPART = 9000
VMID_GABARIT_FIN = 9100


def cmds_vmids():
    """La commande qui liste les VMID de TOUTE la grappe.

    De la grappe et non du nœud : un VMID est unique à l'échelle du cluster, et
    `qm list` ne voit que la machine où il tourne. Choisir un numéro libre
    localement le prendrait à une VM d'un autre nœud.
    """
    return ["pvesh get /cluster/resources --type vm --output-format json"]


def lit_vmids(sortie):
    """Les VMID que la grappe déclare, ou None.

    Fermé par défaut : ce qui n'est pas une liste d'objets portant un VMID
    entier fait refuser TOUTE la lecture. Une lecture partielle ferait croire
    un numéro libre alors qu'il est pris, et `qm create` échouerait au milieu
    du gabarit — après le téléchargement de l'image.

    Une grappe sans aucune VM rend `()` : « rien à nommer » est une réponse.
    """
    texte = sortie or ""
    debut = texte.find("[")
    if debut < 0:
        return None
    try:
        lu, _fin = json.JSONDecoder().raw_decode(texte[debut:])
    except ValueError:
        return None
    if not isinstance(lu, list):
        return None
    vus = []
    for entree in lu:
        if not isinstance(entree, dict):
            return None
        vmid = entree.get("vmid")
        if isinstance(vmid, bool) or not isinstance(vmid, int):
            return None
        vus.append(vmid)
    return tuple(vus)


def gabarit_libre(vmids, depart=VMID_GABARIT_DEPART):
    """Le premier VMID libre à partir de `depart`, ou 0.

    LU sur la grappe, jamais supposé. `vmids` à None — la grappe n'a pas
    répondu — rend 0 : prendre un numéro sans savoir lesquels sont pris
    reviendrait à parier sur la VM de quelqu'un d'autre.

    0 dit « pas de numéro », et c'est le seul entier qu'un VMID ne peut pas
    valoir : la grappe les compte à partir de 100.
    """
    # ÉCRIT POUR SE LIRE, et non porteur : le cas None retomberait de toute
    # façon dans le `except` en dessous — parcourir None lève une TypeError. Le
    # dire ici évite de faire dériver l'intention du hasard d'une exception ;
    # aucune mutation de cette seule ligne ne peut donc changer la réponse.
    if vmids is None:
        return 0
    try:
        pris = {int(vu) for vu in vmids}
    except (TypeError, ValueError):
        return 0
    for numero in range(max(0, int(depart)), VMID_GABARIT_FIN):
        if numero not in pris:
            return numero
    return 0


def texte_placement(noeud, stockage, pont, vmid_modele, gabarit=GABARIT):
    """Le `group_vars/proxmox.yml` du locataire : OÙ il se pose. Ou « ».

    TROIS CLÉS APPARTIENNENT AU LOCATAIRE et non à l'hébergeur — le nœud, le
    stockage et le VMID du gabarit — parce que c'est lui qui choisit où se
    poser, même si les trois NOMMENT des objets de l'hébergeur. Le reste de son
    adressage dérive de son seul index, ce qui est ce qui le rend portable
    d'une fabric à l'autre.

    LE PONT EN EST, ICI, ET C'EST UN REPLI. Le générateur d'inventaire pose un
    pont par hôte quand la fabric a une SDN, dérivé du réseau virtuel de sa
    zone. Sans SDN, il ne pose rien et le clonage retombe sur cette valeur —
    qui vaut `vmbr0` par défaut. Une carte étiquetée sur un pont qui n'est pas
    conscient des VLAN démarre et reste injoignable, et la panne ne se voit ni
    à la création, ni dans un code de retour : le banc nomme donc SON pont.
    """
    if not all((vu or "").strip() for vu in (noeud, stockage, pont, gabarit)):
        return ""
    try:
        vmid = int(vmid_modele)
    except (TypeError, ValueError):
        return ""
    if vmid < 1:
        return ""
    return f"""---
# Le placement du locataire du BANC. L'adressage n'est PAS ici : il dérive de
# l'index du plan.
proxmox_clone_noeud: {noeud.strip()}
proxmox_clone_stockage: {stockage.strip()}
proxmox_clone_vmid_modele: {vmid}
proxmox_clone_source_nom: {gabarit.strip()}
proxmox_clone_pont: {pont.strip()}
"""


# CE QU'ON DEMANDE AU MOTEUR sur ses dossiers frères. Lancé chez lui, avec son
# python : sa règle de découverte a déjà changé une fois, et la deviner du nom
# d'un dossier la ferait diverger en silence.
SONDE_INSTANCES = (
    "import json, sys; sys.path.insert(0, 'scripts');"
    " import instances; print(json.dumps(instances.decouvrir()))"
)

# Le groupe que le générateur d'inventaire du moteur remplit des hôtes ACTIFS.
# C'est lui que la matérialisation et le rasage lisent.
GROUPE_ACTIFS = "hotes_actifs"

# Les trois valeurs qu'une zone exige pour être routée. L'étiquette dit QUEL
# domaine, la passerelle QUI y répond, le préfixe JUSQU'OÙ il s'étend.
CHAMPS_ZONE = ("proxmox_vlan", "proxmox_passerelle", "proxmox_cidr")


class Zone(NamedTuple):
    """Un domaine de diffusion à router : son étiquette et sa passerelle.

    `cidr` porte la passerelle AVEC son préfixe, ce que la strophe d'une
    interface attend. Le séparer ferait recomposer la chaîne à chaque appelant,
    et l'un d'eux finirait par oublier le préfixe — sans quoi la dérivation le
    suppose à /32 et l'interface monte sans masque.
    """

    vlan: int
    cidr: str


def lit_inventaire(chemin):
    """L'inventaire généré, ou None. Ne lève jamais.

    Lu ici plutôt que par l'appelant : `zones_a_router` reste alors une fonction
    PURE, éprouvable sans fichier.
    """
    import sys

    if RACINE not in sys.path:
        sys.path.insert(0, RACINE)
    try:
        import yaml
    except ImportError:
        return None
    try:
        with open(chemin, encoding="utf-8") as ouvert:
            lu = yaml.safe_load(ouvert.read())
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return None
    return lu if isinstance(lu, dict) else None


def zones_a_router(inventaire):
    """Les zones que les hôtes ACTIFS exigent, sans doublon. Ou None.

    DÉRIVÉ DE L'INVENTAIRE GÉNÉRÉ, jamais recalculé. C'est le moteur qui tire la
    VLAN et la passerelle de chaque zone du seul index du plan ; une seconde
    dérivation écrite ici divergerait de la sienne le jour où sa règle change, et
    le banc routerait alors des domaines où personne n'habite.

    Fermé par défaut : un hôte actif à qui manque l'une des trois valeurs fait
    refuser TOUTE la lecture. Router une zone sur deux laisse la moitié de la
    flotte injoignable, et rien dans l'inventaire ne dira laquelle — le
    déploiement échouera sur un hôte qui « ne répond pas ».

    Zéro hôte actif rend `()` : il n'y a rien à router, ce qui est une réponse.
    """
    # CHAQUE NIVEAU EST VÉRIFIÉ AVANT D'ÊTRE PARCOURU. Un `all` qui n'est pas un
    # dictionnaire faisait LEVER au lieu de refuser, et une exception remonte
    # très loin de l'inventaire qui l'a causée. Un inventaire se lit aussi après
    # avoir été édité à la main.
    if not isinstance(inventaire, dict):
        return None
    tout = inventaire.get("all")
    if tout is None:
        return ()
    if not isinstance(tout, dict):
        return None
    enfants = tout.get("children")
    if enfants is None:
        return ()
    if not isinstance(enfants, dict):
        return None
    groupe = enfants.get(GROUPE_ACTIFS)
    if groupe is None:
        return ()
    if not isinstance(groupe, dict):
        return None
    hotes = groupe.get("hosts")
    if hotes is None:
        return ()
    if not isinstance(hotes, dict):
        return None
    vues = []
    for nom in sorted(hotes):
        variables = hotes[nom]
        if not isinstance(variables, dict):
            return None
        vlan, passerelle, prefixe = (
            variables.get(champ) for champ in CHAMPS_ZONE
        )
        if isinstance(vlan, bool) or not isinstance(vlan, int):
            return None
        if not isinstance(passerelle, str) or not passerelle.strip():
            return None
        try:
            prefixe = int(prefixe)
        except (TypeError, ValueError):
            return None
        zone = Zone(vlan, f"{passerelle.strip()}/{prefixe}")
        if zone not in vues:
            vues.append(zone)
    return tuple(vues)


def cmds_svi(zone, pont, uplink=""):
    """Les commandes qui posent l'interface routée de `zone` sur `pont`.

    Bâties par le module qui sait déjà poser une interface à distance, avec
    toutes ses leçons — le verrou d'ifupdown2, le refus de tout recharger, le
    nom échappé dans le motif d'idempotence. Une seconde strophe écrite ici les
    perdrait une à une.
    """
    import sys

    if zone is None or not (pont or "").strip():
        return []
    if RACINE not in sys.path:
        sys.path.insert(0, RACINE)
    from script.proxmox import proxmox_deploy as pve

    return list(
        pve.svi_setup_cmds(
            pont=pont, vlan=zone.vlan, cidr=zone.cidr, uplink=uplink
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


def chemins_du_banc(moteur):
    """Où vivent les deux dépôts du banc : (frères, underlay, locataire). Ou None.

    DES DOSSIERS FRÈRES DU MOTEUR, jamais un dossier temporaire et jamais dedans.
    La fédération se découvre par les dossiers frères : ailleurs, le locataire du
    banc est invisible au moteur, qui répond alors « aucun tenant fédéré
    découvert » — un refus dont la cause ne se lit nulle part.

    Le chemin rendu est ABSOLU, parce que le banc y écrit ; ce sont les LIENS qui
    sont relatifs, et pour une autre raison.
    """
    # LE VIDE SE TESTE APRÈS LE DÉPOUILLEMENT. « / » dépouillé de ses
    # séparateurs est la chaîne vide, et une chaîne vide donnée à la résolution
    # rend le DOSSIER COURANT — sans rien dire. Le banc prendrait alors le
    # répertoire de travail pour le moteur, y poserait ses liens et créerait ses
    # dépôts à côté.
    nu = (moteur or "").strip().rstrip(os.sep)
    if not nu:
        return None
    racine = os.path.abspath(nu)
    freres = os.path.dirname(racine)
    if not freres or freres == racine:
        return None
    return (
        freres,
        os.path.join(freres, UNDERLAY_BANC),
        os.path.join(freres, ECOSYSTEME),
    )


def cibles_des_liens():
    """Les deux liens à poser : ((nom, cible), …), les cibles RELATIVES.

    RELATIVES ET NON ABSOLUES. Le moteur résout `underlay.yml` pour en dériver
    le dépôt de l'hébergeur ; un lien absolu pend dès que le checkout est
    déplacé ou monté ailleurs, et il porte un chemin de compte, que rien dans un
    dépôt ne doit porter.

    `underlay.yml` désigne un FICHIER, `instance` un DOSSIER : le moteur lit le
    premier puis prend son dossier parent pour trouver la grappe de l'hébergeur,
    et parcourt le second pour trouver le plan. Les échanger ferait chercher un
    plan dans un fichier.
    """
    return (
        (LIEN_UNDERLAY, f"..{os.sep}{UNDERLAY_BANC}{os.sep}underlay.yml"),
        (LIEN_INSTANCE, f"..{os.sep}{ECOSYSTEME}"),
    )


class Montage(NamedTuple):
    """Ce que le montage local a posé, et ce qui l'a arrêté.

    Les chemins sont ceux de ce qui EXISTE désormais. Un montage interrompu les
    porte quand même, parce que c'est par eux qu'il se défait : rendre une
    absence sur un échec laisserait sur le disque ce que plus rien ne nomme.

    `souci` est vide quand tout a été posé. Non vide, il DIT quoi, et le montage
    partiel reste à défaire.
    """

    underlay: str
    ecosysteme: str
    liens: tuple
    cles: tuple
    souci: str

    @property
    def complet(self) -> bool:
        """Tout est posé : les deux dépôts, les deux liens, et pas de souci."""
        return (
            not self.souci
            and bool(self.underlay)
            and bool(self.ecosysteme)
            and len(self.liens) == len(LIENS)
        )


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


def index_libre(instances, voulu, siens=(ECOSYSTEME, UNDERLAY_BANC)):
    """L'index `voulu` est-il libre parmi `instances` ? None si on ne sait pas.

    `instances` est ce que le moteur découvre chez ses dossiers frères. Une
    découverte qui n'aboutit pas REFUSE au lieu de conclure : un index déjà pris
    dérive les mêmes adresses et les mêmes VLAN pour deux écosystèmes, et rien
    dans la suite ne le signalerait.

    LES DÉPÔTS DU BANC NE SE RÉSERVENT PAS À EUX-MÊMES. Ils portent l'index par
    construction dès le premier montage : les compter ferait refuser toute
    exécution suivante, et le banc ne tournerait qu'une fois. C'est la même
    distinction que pour ses liens — « déjà à nous » n'est pas « occupé ».

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
            and (une.get("nom") or "") not in siens
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


# L'INVENTAIRE que le banc renseigne. Le moteur en connaît trois — lab,
# principal, production — et prend le PREMIER qui existe, dans cet ordre.
# `production` est celui que son générateur crée, donc le seul qui existera de
# toute façon : en renseigner un autre en ferait deux, et le premier gagnerait
# sur celui que le générateur tient à jour.
INVENTAIRE_BANC = "production"

# Le modèle d'écosystème dont le banc part, relatif au moteur. Celui que le
# moteur livre et que ses propres preuves valident : un modèle écrit par le banc
# dériverait de celui-là sans que rien ne le dise.
MODELE_SOCLE = os.path.join("exemples", "modeles", "socle")


def pose_index(texte, index):
    """`texte`, son `index:` de premier niveau porté à `index`. Ou None.

    CHIRURGICAL, comme l'activation d'un hôte : une ligne change, le reste du
    fichier est rendu tel quel. Tout l'adressage d'un écosystème dérive de ce
    seul entier, et le modèle livré en déclare un que deux bancs partageraient.

    REFUSE plutôt que de deviner : pas d'`index:` de premier niveau, ou plus
    d'un. Un index absent fait retomber la dérivation sur son défaut de bac à
    sable, qui est le même pour tout le monde.
    """
    if not (texte or ""):
        return None
    try:
        voulu = int(index)
    except (TypeError, ValueError):
        return None
    lignes = texte.splitlines(keepends=True)
    vus = [i for i, l in enumerate(lignes) if re.match(r"index\s*:", l)]
    if len(vus) != 1:
        return None
    lignes[vus[0]] = re.sub(
        r"^index(\s*:\s*).*?(\r?\n?)$",
        rf"index\g<1>{voulu}\g<2>",
        lignes[vus[0]],
    )
    return "".join(lignes)


def _ecrit(chemin, texte):
    """Écrit `texte` dans `chemin`. Rend le souci, ou « ».

    Pas de secret ici : ce que le montage pose voyage avec un dépôt. Le jeton
    passe par un autre chemin, qui le chiffre sans jamais le poser en clair.
    """
    if not texte:
        return f"rien à écrire dans {os.path.basename(chemin)}"
    try:
        with open(chemin, "w", encoding="utf-8") as ouvert:
            ouvert.write(texte)
    except OSError as souci:
        return f"{os.path.basename(chemin)} : {souci.strerror or souci}"
    return ""


def _recrit(chemin, transforme):
    """Relit `chemin`, le passe à `transforme`, le réécrit. Rend le souci.

    `transforme` REFUSE en rendant None, et le fichier n'est alors pas touché :
    une réécriture partielle laisserait un plan que le moteur lit à moitié.
    """
    try:
        with open(chemin, encoding="utf-8") as ouvert:
            avant = ouvert.read()
    except OSError as souci:
        return f"{os.path.basename(chemin)} : {souci.strerror or souci}"
    apres = transforme(avant)
    if apres is None:
        return f"{os.path.basename(chemin)} : la réécriture a refusé"
    return _ecrit(chemin, apres)


def amorcage_du_plan(moteur, instance):
    """Les hôtes d'amorçage que le plan d'`instance` dérive. Ou None.

    LU CHEZ LE MOTEUR, avant que le lien soit posé : son lecteur d'instance
    honore `SETOPS_INSTANCE`, si bien que le banc peut interroger un dépôt
    qu'il vient de copier sans avoir encore rien monté. Poser le lien d'abord
    obligerait à le retirer si l'amorçage refusait.
    """
    if not (moteur or "").strip() or not (instance or "").strip():
        return None
    vu = runner_du_banc().jouer(
        ("python3", "-B", CIBLE_AMORCAGE),
        env=dict(runner_du_banc().base(), SETOPS_INSTANCE=instance),
        cwd=moteur,
        fusionner=False,
        delai=60,
    )
    return lit_amorcage(vu.sortie) if vu.code == 0 else None


def monte_localement(moteur, noeud, pont, stockage, hote_api, vmid_modele):
    """Pose les deux dépôts du banc et les deux liens du moteur. Rend un `Montage`.

    LES LIENS SE JUGENT AVANT QUE RIEN NE SOIT CRÉÉ. Un lien occupé est celui
    d'un exploitant, et le remplacer dirigerait son geste suivant vers
    l'écosystème du banc, dont le rasage détruit tout ce que l'inventaire nomme.
    Créer les dépôts puis refuser laisserait deux dossiers que rien ne nomme.

    `vmid_modele` VIENT DE LA GRAPPE, pas d'une constante : il est choisi parmi
    les numéros qu'elle ne porte pas, comme le pont est choisi parmi les noms
    qu'elle ne déclare pas. L'appelant l'a donc déjà sondée.

    L'ORDRE : l'underlay, puis le locataire, puis son index, ses hôtes
    d'amorçage et son placement, puis les liens. L'amorçage se lit AVANT les liens, par la
    variable d'instance ; les clés se posent APRÈS eux, le moteur nommant celle
    de l'hébergeur en résolvant son lien.

    NE LÈVE JAMAIS, et rend ce qu'elle a posé même en échec : c'est par ces
    chemins que le montage se défait, et rendre une absence laisserait sur le
    disque ce que plus rien ne nomme.
    """
    import shutil

    vide = Montage("", "", (), (), "")
    chemins = chemins_du_banc(moteur)
    if chemins is None:
        return vide._replace(souci="le moteur n'a pas de dossier frère")
    _freres, site, eco = chemins

    for nom, cible in cibles_des_liens():
        etat = lien_etat(os.path.join(moteur, nom), cible)
        if etat not in (A_POSER, NOTRE):
            return vide._replace(souci=f"le lien « {nom} » est {etat}")

    pose = vide
    try:
        os.makedirs(site, exist_ok=True)
    except OSError as souci:
        return pose._replace(souci=f"{UNDERLAY_BANC} : {souci.strerror}")
    pose = pose._replace(underlay=site)
    for fichier, texte in (
        ("underlay.yml", texte_underlay(noeud, pont)),
        (
            "proxmox-hebergeur.yml",
            texte_hebergeur(hote_api, noeud, stockage, pont),
        ),
    ):
        souci = _ecrit(os.path.join(site, fichier), texte)
        if souci:
            return pose._replace(souci=souci)

    if not os.path.isdir(eco):
        try:
            shutil.copytree(os.path.join(moteur, MODELE_SOCLE), eco)
        except (OSError, shutil.Error) as souci:
            return pose._replace(souci=f"{ECOSYSTEME} : {souci}")
    pose = pose._replace(ecosysteme=eco)

    hotes = amorcage_du_plan(moteur, eco)
    if not hotes:
        return pose._replace(souci="le plan ne dérive aucun hôte d'amorçage")
    for fichier, transforme in (
        ("nomenclature.yml", lambda t: pose_index(t, INDEX_ECOSYSTEME)),
        ("serveurs.yml", lambda t: active_les_hotes(t, hotes)),
    ):
        souci = _recrit(os.path.join(eco, "plan", fichier), transforme)
        if souci:
            return pose._replace(souci=souci)

    # LE PLACEMENT, et le modèle n'en livre aucun : il dit ce que l'écosystème
    # VEUT, pas sur quelle grappe il se pose. Le dossier n'existe pas encore —
    # le générateur d'inventaire le créera, mais le clonage lit ce fichier.
    groupe = os.path.join(eco, "inventories", INVENTAIRE_BANC, "group_vars")
    try:
        os.makedirs(groupe, exist_ok=True)
    except OSError as souci:
        return pose._replace(souci=f"{INVENTAIRE_BANC} : {souci.strerror}")
    souci = _ecrit(
        os.path.join(groupe, "proxmox.yml"),
        texte_placement(noeud, stockage, pont, vmid_modele),
    )
    if souci:
        return pose._replace(souci=souci)

    liens = []
    for nom, cible in cibles_des_liens():
        chemin = os.path.join(moteur, nom)
        if lien_etat(chemin, cible) == A_POSER:
            try:
                os.symlink(cible, chemin)
            except OSError as souci:
                return pose._replace(
                    liens=tuple(liens),
                    souci=f"le lien « {nom} » : {souci.strerror or souci}",
                )
        liens.append(chemin)
    return pose._replace(liens=tuple(liens))


# L'outil qui chiffre, et le nom de la voûte que le banc scelle. Le moteur la
# cherche à côté d'`underlay.yml`, dans le dépôt de l'hébergeur.
OUTIL_VOUTE = "ansible-vault"
VOUTE_UNDERLAY = "underlay.vault.yml"


def env_ansible(moteur):
    """L'environnement d'un outil ansible, bâti par le module du dépôt.

    L'OUTIL DE VOÛTE NE VIT PAS DANS LE PATH ORDINAIRE. Il est posé dans le venv
    que todo tient pour le moteur, et l'environnement neuf de l'exécuteur en
    retire au contraire le venv d'ERPLibre. Sans ce montage, chiffrer échoue sur
    « commande introuvable » — un message qui envoie installer ansible sur une
    machine qui l'a déjà.
    """
    import sys

    if RACINE not in sys.path:
        sys.path.insert(0, RACINE)
    from script.setops import ansible_env

    return ansible_env.environnement(RACINE, moteur, runner_du_banc().base())


def argv_chiffrer(chemin, identite):
    """L'argv qui chiffre la voûte `chemin` sous `identite`, ou None.

    `-` EN SOURCE, et c'est tout l'intérêt : le clair arrive par l'entrée
    standard et ne touche jamais le disque. Chiffrer un fichier posé en clair
    laisserait le secret dans les blocs libérés et dans toute sauvegarde prise
    entre les deux gestes.

    `--output` ÉCRASE, et c'est voulu : la voûte du banc ne porte que le jeton du
    banc, et un second passage y remplace un jeton révoqué par le neuf. Ce n'est
    PAS le cas d'une voûte de production, où l'écrasement perd les autres
    secrets — d'où le fait que cette fonction nomme un chemin plutôt que d'en
    dériver un.

    `--vault-id étiquette@clé` : l'étiquette est inscrite dans l'en-tête du
    fichier, et c'est par elle que le moteur retrouve laquelle de ses clés
    l'ouvre. Chiffré sans elle, le fichier s'ouvre encore, mais le moteur essaie
    toutes ses clés et ne dit pas laquelle a servi.
    """
    if not (chemin or "").strip() or identite is None:
        return None
    if not (identite.etiquette or "").strip():
        return None
    if not (identite.cle or "").strip():
        return None
    return (
        OUTIL_VOUTE,
        "encrypt",
        "--vault-id",
        f"{identite.etiquette.strip()}@{identite.cle.strip()}",
        "--output",
        chemin.strip(),
        "-",
    )


def lire_jeton(terrain, elevation):
    """Crée l'utilisateur d'API et son jeton sur `terrain`, et rend son secret.

    C'EST LE SEUL MOMENT OÙ LE SECRET EXISTE : la grappe ne l'affiche qu'à la
    création du jeton, et ne le redonne jamais. Rendu à l'appelant, il ne va
    qu'à deux endroits — l'environnement d'un geste, ou l'outil qui le chiffre —
    et rien ne le journalise en chemin.

    Rend « » dès que quoi que ce soit échoue. Une chaîne vide REFUSE la suite
    plutôt que d'envoyer un secret tronqué, qui rendrait un 401 que rien
    n'explique.
    """
    fait = joue_sur(terrain, cmds_jeton(), elevation)
    return lit_jeton(fait.sortie) if fait.reussi else ""


def scelle_jeton(voute, identite, secret, moteur):
    """Chiffre `secret` dans `voute` sous `identite`. Rend le souci, ou « ».

    Le secret PASSE PAR L'ENTRÉE STANDARD de l'outil, jamais par un fichier ni
    par une ligne de commande — une ligne de commande se lit dans la table des
    processus de la machine, par n'importe quel compte.

    Le souci rendu est EXPURGÉ : la plainte d'un outil de chiffrement cite
    parfois ce qu'il a reçu, et ce qu'il a reçu est le secret.

    `moteur` sert à bâtir l'environnement de l'outil, qui ne vit pas dans le PATH
    ordinaire, et à lui donner son répertoire de travail.
    """
    if not (secret or "").strip():
        return "aucun secret à sceller"
    argv = argv_chiffrer(voute, identite)
    if argv is None:
        return "la voûte ou son identité manque"
    vu = runner_du_banc().jouer(
        argv,
        env=env_ansible(moteur),
        cwd=moteur or None,
        entree=texte_voute(secret),
        delai=120,
    )
    if vu.code == 0:
        return ""
    return f"{OUTIL_VOUTE} : {expurge(vu.sortie, secret).strip()[-200:]}"


# L'ÉTAT DU GABARIT, vocabulaire CLOS. Le banc ne le fabrique pas : sa procédure
# impose une installation depuis l'ISO, parce qu'une machine NAÎT en q35 ou ne le
# sera jamais proprement — convertir le chipset sous un système installé remplace
# son matériel virtuel, et chacune des pannes qui s'ensuivent ressemble à autre
# chose qu'à sa cause. Le banc le MESURE donc, et refuse plutôt que de cloner un
# gabarit qui le trahirait.
GABARIT_ABSENT = "absent"
GABARIT_PAS_MODELE = "pas_modele"
GABARIT_MATERIEL = "materiel"
GABARIT_CONFORME = "conforme"
ETATS_GABARIT = (
    GABARIT_ABSENT,
    GABARIT_PAS_MODELE,
    GABARIT_MATERIEL,
    GABARIT_CONFORME,
)

# CE QUE LA PROCÉDURE DU MOTEUR EXIGE DU MATÉRIEL VIRTUEL, et la vérifier est ce
# qu'elle appelle « le dernier moment où la correction est gratuite » : le gabarit
# lègue ces valeurs à chacun de ses clones.
#
# `q35` est PCIe là où le défaut est PCI : la topologie des bus décide des noms
# d'interfaces prédictibles, qui en dérivent, et des chemins de disques. Une VM
# clonée d'un gabarit au mauvais chipset démarre avec une configuration réseau qui
# désigne une interface inexistante.
MATERIEL_GABARIT = (("machine", "q35"), ("bios", "ovmf"))

# Où la procédure du moteur se lit, cité au refus : sans elle, « gabarit non
# conforme » laisse chercher quoi corriger.
PROCEDURE_GABARIT = "docs/procedure-template-debian13-proxmox.md"


# Ce qu'un stockage doit savoir porter pour accueillir un clone : des IMAGES de
# disque. Un stockage à sauvegardes ou à modèles de conteneur ne l'accepte pas, et
# le clonage échoue alors sur un message qui parle du stockage sans dire pourquoi.
CONTENU_IMAGES = "images"


def cmds_noeuds():
    """La commande qui nomme les nœuds de la grappe."""
    return ["pvesh get /nodes --output-format json"]


def lit_noeuds(sortie):
    """Les nœuds EN LIGNE de la grappe, ou None.

    En ligne seulement : cloner sur un nœud éteint échoue après avoir attendu,
    et l'attente ressemble à un clonage lent.

    Fermé par défaut : ce qui n'est pas une liste d'objets nommés fait refuser
    toute la lecture. Une grappe sans nœud en ligne rend `()`.
    """
    lu = _json_liste(sortie)
    if lu is None:
        return None
    vus = []
    for entree in lu:
        if not isinstance(entree, dict):
            return None
        nom = entree.get("node")
        if not isinstance(nom, str) or not nom.strip():
            return None
        if (entree.get("status") or "") != "online":
            continue
        vus.append(nom.strip())
    return tuple(vus)


def cmds_stockages():
    """La commande qui dit ce que chaque stockage de la grappe accepte."""
    return ["pvesh get /storage --output-format json"]


def lit_stockages(sortie):
    """Les stockages qui acceptent des IMAGES de disque, ou None.

    Le contenu accepté est déclaré par le stockage lui-même : le deviner de son
    nom se tromperait sur toute grappe qui nomme ses stockages autrement que la
    nôtre.

    Fermé par défaut, et un stockage sans contenu déclaré NE COMPTE PAS : ce
    n'est pas « il accepte tout », c'est « on ne sait pas », et on ne pose pas
    une VM sur un stockage dont on ne sait rien.
    """
    lu = _json_liste(sortie)
    if lu is None:
        return None
    vus = []
    for entree in lu:
        if not isinstance(entree, dict):
            return None
        nom = entree.get("storage")
        if not isinstance(nom, str) or not nom.strip():
            return None
        contenu = entree.get("content")
        if not isinstance(contenu, str):
            continue
        if CONTENU_IMAGES in [c.strip() for c in contenu.split(",")]:
            vus.append(nom.strip())
    return tuple(vus)


def _json_liste(sortie):
    """La liste JSON que `sortie` porte, ou None. Fermé par défaut.

    Partagé par les lecteurs de la grappe : ils reçoivent tous une liste
    d'objets, et tous doivent refuser la même chose — une plainte de l'outil,
    une réponse tronquée, un objet là où une liste est attendue.
    """
    texte = sortie or ""
    debut = texte.find("[")
    if debut < 0:
        return None
    try:
        lu, _fin = json.JSONDecoder().raw_decode(texte[debut:])
    except ValueError:
        return None
    return lu if isinstance(lu, list) else None


# Ce que la sonde de sortie imprime : l'interface qui porte la route par défaut,
# puis son adresse. Deux faits sur deux lignes d'une SEULE commande, l'exécuteur
# ne rendant que la sortie de la dernière.
SONDE_SORTIE = (
    "s=$(ip -o -4 route show default | awk '{for(i=1;i<NF;i++)"
    'if($i=="dev")print $(i+1)}\' | head -1); '
    "printf 'sortie=%s\\n' \"$s\"; "
    'ip -o -4 addr show dev "$s" 2>/dev/null'
    " | awk '{print \"adresse=\" $4}' | head -1"
)


def cmds_sortie():
    """La commande qui dit par où le terrain sort, et sous quelle adresse."""
    return [SONDE_SORTIE]


def lit_sortie(sortie):
    """(interface de sortie, adresse sans préfixe), ou None.

    L'INTERFACE EST CELLE DE LA ROUTE PAR DÉFAUT, pas un nom deviné. C'est elle
    que le masquage du pont doit viser : viser la mauvaise laisse les VM se
    parler entre elles sans jamais sortir, et le symptôme — « apt ne répond
    pas » — n'envoie pas regarder une règle de traduction d'adresses.

    L'ADRESSE EST CELLE PAR LAQUELLE ON JOINT L'API de la grappe. Fermé par
    défaut : les deux lignes sont exigées, une interface sans adresse ne
    permettant pas de joindre son hyperviseur.
    """
    interface, adresse = "", ""
    for ligne in (sortie or "").splitlines():
        nu = ligne.strip()
        if nu.startswith("sortie="):
            interface = nu[7:].strip()
        elif nu.startswith("adresse="):
            adresse = nu[8:].strip().split("/")[0]
    if not interface or not adresse:
        return None
    return (interface, adresse)


def vmid_lisible(vmid):
    """`vmid` en entier positif, ou 0. Ne lève jamais.

    UN VMID VIENT DE L'EMPREINTE, donc d'un fichier qu'un éditeur ouvre : le
    convertir sans filet ferait LEVER sur le chemin de la défaite, et une
    exception y remplace le verdict par une trace.
    """
    try:
        lu = int(vmid)
    except (TypeError, ValueError):
        return 0
    return lu if lu > 0 else 0


def cmds_config_vm(vmid):
    """La commande qui rend la configuration d'une VM. Vide si le VMID n'en est
    pas un : on n'interroge pas la grappe sur un numéro qu'on n'a pas lu."""
    lu = vmid_lisible(vmid)
    return [f"qm config {lu}"] if lu else []


def lit_gabarit(sortie, nom=GABARIT):
    """Le VMID de la VM nommée `nom`, 0 si aucune, ou None si on n'a pas lu.

    APPARIEMENT STRICT SUR LE NOM, comme l'effacement : c'est par le nom que le
    clonage du moteur cherche sa source, et « un nom qui ne correspond pas se
    solde par un clonage qui ne trouve rien ». Un nom qui CONTIENT le nôtre n'est
    pas le nôtre.

    Deux VM du même nom rendent None : le clonage ne saurait pas laquelle prendre,
    et choisir pour lui serait deviner.
    """
    texte = sortie or ""
    debut = texte.find("[")
    if debut < 0:
        return None
    try:
        lu, _fin = json.JSONDecoder().raw_decode(texte[debut:])
    except ValueError:
        return None
    if not isinstance(lu, list):
        return None
    attendu = (nom or "").strip()
    if not attendu:
        return None
    trouves = []
    for entree in lu:
        if not isinstance(entree, dict):
            return None
        if (entree.get("name") or "").strip() != attendu:
            continue
        vmid = entree.get("vmid")
        if isinstance(vmid, bool) or not isinstance(vmid, int) or vmid < 1:
            return None
        trouves.append(vmid)
    if len(trouves) > 1:
        return None
    return trouves[0] if trouves else 0


def lit_conformite_gabarit(sortie):
    """L'état du gabarit d'après sa configuration. Ou None si elle ne se lit pas.

    FERMÉ PAR DÉFAUT SUR CHAQUE CLÉ : une clé ABSENTE vaut non conforme, et ce
    n'est pas un excès de prudence — `qm config` n'imprime que ce qui diffère du
    défaut, et ces défauts sont justement le chipset PCI et le micrologiciel
    d'amorçage hérité que la procédure refuse. Une absence dit donc « c'est le
    défaut », pas « on ne sait pas ».

    `template` distingue une VM VIVANTE d'un modèle. Cloner une VM vivante n'est
    pas la même opération, et le moteur suppose un modèle.
    """
    texte = sortie or ""
    if not texte.strip():
        return None
    lu = {}
    for ligne in texte.splitlines():
        if ":" not in ligne or ligne.startswith((" ", "\t")):
            continue
        cle, valeur = ligne.split(":", 1)
        lu[cle.strip()] = valeur.strip()
    if not lu:
        return None
    if lu.get("template") != "1":
        return GABARIT_PAS_MODELE
    for cle, attendu in MATERIEL_GABARIT:
        if lu.get(cle) != attendu:
            return GABARIT_MATERIEL
    return GABARIT_CONFORME


def dit_gabarit(etat, nom=GABARIT):
    """Ce que l'écran dit d'un gabarit non conforme, ou « » s'il l'est.

    LE REFUS CITE LA PROCÉDURE. « Gabarit non conforme » laisse chercher quoi
    corriger ; le banc ne fabrique pas le gabarit, donc il doit dire où la
    fabrication est décrite.
    """
    if etat == GABARIT_CONFORME:
        return ""
    attendu = ", ".join(f"{c} : {v}" for c, v in MATERIEL_GABARIT)
    raisons = {
        GABARIT_ABSENT: f"aucune VM nommée « {nom} » sur la grappe",
        GABARIT_PAS_MODELE: (
            f"« {nom} » existe mais n'est pas un modèle : le convertir"
        ),
        GABARIT_MATERIEL: (
            f"« {nom} » n'a pas le matériel voulu ({attendu}) ; il ne se"
            " corrige PAS après coup, il se réinstalle"
        ),
    }
    return (
        raisons.get(etat, f"état du gabarit illisible : {etat!r}")
        + f" — voir {PROCEDURE_GABARIT} chez le moteur"
    )


def cmds_effacer_vm(vmid, nom):
    """Les commandes qui effacent une VM du banc, le nom VÉRIFIÉ d'abord.

    L'appelant confronte le nom avec `effacable` avant de jouer la suite : ces
    commandes ne protègent rien par elles-mêmes, elles supposent le constat
    fait.
    """
    lu = vmid_lisible(vmid)
    if not lu:
        return []
    return [
        f"qm stop {lu} --skiplock 1 || true",
        f"qm destroy {lu} --purge 1",
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
    # LES INTERFACES DE VLAN AVANT LEUR PONT. Retirer le pont d'abord laisse
    # des strophes qui nomment un parent disparu, et le montage des interfaces
    # s'en plaint à chaque démarrage de l'hôte sans que rien ne dise d'où elles
    # viennent.
    gestes += [
        Geste(terrain, SVI, f"{empreinte.pont}.{vlan}", str(vlan))
        for vlan in reversed(empreinte.zones or ())
        if empreinte.pont
    ]
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
    zones = []
    etiquettes = lu.get("zones")
    if etiquettes is not None and not isinstance(etiquettes, list):
        return None
    for brute in etiquettes or ():
        # Une étiquette hors de la plage 802.1Q ne nomme aucune interface : le
        # geste de défaite porterait alors sur un nom qui n'existe pas, et
        # l'écran annoncerait un retrait qui n'a pas eu lieu.
        if isinstance(brute, bool) or not isinstance(brute, int):
            return None
        if not 2 <= brute <= 4094 or brute in zones:
            return None
        zones.append(brute)
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
        vms=tuple(vms),
        liens=chemins["liens"],
        cles=chemins["cles"],
        zones=tuple(zones),
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
            "vms": [list(v) for v in empreinte.vms],
            "liens": list(empreinte.liens),
            "cles": list(empreinte.cles),
            "zones": list(empreinte.zones),
        },
        sort_keys=True,
    )


def mesure_le_terrain(moteur, terrain):
    """Relève tout ce que les préalables jugent, sans rien poser. Ne lève jamais.

    AUCUNE ÉCRITURE ICI. Chaque commande jouée est une lecture : l'élévation, la
    configuration réseau, les VMID de la grappe, la configuration du gabarit. Un
    banc qui poserait en mesurant ne pourrait plus refuser sans avoir déjà sali
    le terrain.

    L'élévation se mesure EN PREMIER, parce que toutes les autres en dépendent :
    lues sans droits, elles rendraient « commande introuvable » et le banc
    conclurait à un terrain vierge.
    """
    elevation = elevation_du_terrain(terrain)
    liens = tuple(
        lien_etat(os.path.join(moteur, nom), cible)
        for nom, cible in cibles_des_liens()
    )
    vide = Mesures(terrain or "", elevation, liens, None, "", 0, None)
    if elevation not in (TEL_QUEL, ELEVE):
        return vide

    interfaces = joue_sur(terrain, ["cat /etc/network/interfaces"], elevation)
    pont = (
        pont_du_banc(interfaces.sortie, pont_deja_nomme())
        if interfaces.reussi
        else ""
    )

    noeuds = joue_sur(terrain, cmds_noeuds(), elevation)
    lus = lit_noeuds(noeuds.sortie) if noeuds.reussi else None

    stockages = joue_sur(terrain, cmds_stockages(), elevation)
    portants = lit_stockages(stockages.sortie) if stockages.reussi else None

    dehors = joue_sur(terrain, cmds_sortie(), elevation)
    dedans = lit_sortie(dehors.sortie) if dehors.reussi else None

    ressources = joue_sur(terrain, cmds_vmids(), elevation)
    vmids = lit_vmids(ressources.sortie) if ressources.reussi else None
    vmid = gabarit_libre(vmids)

    gabarit = None
    trouve = lit_gabarit(ressources.sortie) if ressources.reussi else None
    if trouve == 0:
        gabarit = GABARIT_ABSENT
    elif trouve:
        config = joue_sur(terrain, cmds_config_vm(trouve), elevation)
        gabarit = (
            lit_conformite_gabarit(config.sortie) if config.reussi else None
        )

    return vide._replace(
        index_libre=index_libre(instances_freres(moteur), INDEX_ECOSYSTEME),
        pont=pont,
        vmid_gabarit=vmid,
        gabarit=gabarit,
        # LE PREMIER, et le banc n'en CHOISIT pas : une grappe de banc n'a qu'un
        # nœud et qu'un stockage à images. Sur une grappe qui en a plusieurs,
        # choisir pour l'exploitant serait deviner où il veut se poser — et c'est
        # ce que le fichier de placement sert à écrire, qui est à lui.
        noeud=(lus or ("",))[0] if lus else "",
        stockage=(portants or ("",))[0] if portants else "",
        uplink=(dedans or ("", ""))[0],
        adresse_api=(dedans or ("", ""))[1],
    )


def pont_deja_nomme(chemin=""):
    """Le pont que l'empreinte en place nomme, ou « ». Ne lève jamais.

    Lu SANS juger : ce n'est pas ici qu'on décide s'il est réutilisable, mais
    dans `pont_du_banc`, qui confronte ce nom au terrain. Une empreinte absente
    ou illisible rend « », et le banc prend alors un nom libre — ce qui est le
    comportement d'un premier lancement.
    """
    try:
        with open(chemin or chemin_empreinte(), encoding="utf-8") as lu:
            empreinte = lit_empreinte(lu.read())
    except OSError:
        return ""
    return empreinte.pont if empreinte and nous(empreinte) else ""


def instances_freres(moteur):
    """Ce que le moteur découvre chez ses dossiers frères, ou None.

    DEMANDÉ AU MOTEUR, jamais deviné du nom d'un dossier : c'est lui qui décide
    ce qui compte pour une instance — un `plan/nomenclature.yml` ici, un
    `SITE-*/underlay.yml` là — et sa règle a déjà changé une fois.
    """
    vu = runner_du_banc().jouer(
        ("python3", "-B", "-c", SONDE_INSTANCES),
        env=runner_du_banc().base(),
        cwd=moteur,
        fusionner=False,
        delai=60,
    )
    if vu.code != 0:
        return None
    try:
        lu = json.loads(vu.sortie or "")
    except (ValueError, TypeError):
        return None
    return lu if isinstance(lu, list) else None


class Chantier:
    """Ce que le banc a posé, écrit sur disque à CHAQUE ajout.

    NOMMÉ D'ABORD, POSÉ ENSUITE, et l'ordre n'est pas un détail. Écrite APRÈS la
    pose, une interruption entre les deux — une coupure, un délai dépassé, une
    frappe — laisserait sur la grappe un objet que plus rien ne nomme, et
    `--detruire` ne défait que ce que l'empreinte nomme. Nommé d'abord, le pire
    cas est un nom sans objet : tous les gestes de défaite tolèrent l'absence,
    et l'écran le dit.

    L'ÉCRITURE EST ATOMIQUE. Le fichier est écrit à côté puis déplacé : tronqué
    par une coupure au mauvais moment, il deviendrait illisible, et une empreinte
    illisible fait refuser TOUTE la défaite — c'est-à-dire tout laisser en place.
    """

    def __init__(self, terrain, chemin=""):
        self.chemin = chemin or chemin_empreinte()
        self.empreinte = Empreinte(
            terrain=terrain,
            ecosysteme=ECOSYSTEME,
            underlay=UNDERLAY_BANC,
            pont="",
            utilisateur=UTILISATEUR_API,
            vms=(),
        )

    def nomme(self, **champs):
        """Ajoute au nom ce qui va être posé, puis écrit. Rend le souci, ou « ».

        Rendu et non levé : l'appelant décide s'il continue. Mais il ne DOIT pas
        poser ce qu'il n'a pas pu nommer — c'est exactement ce que le souci dit.
        """
        self.empreinte = self.empreinte._replace(**champs)
        return self.ecrit()

    def ecrit(self):
        """Écrit l'empreinte. Rend le souci, ou « »."""
        try:
            os.makedirs(os.path.dirname(self.chemin), exist_ok=True)
            cote = self.chemin + ".chantier"
            with open(cote, "w", encoding="utf-8") as ouvert:
                ouvert.write(ecrit_empreinte(self.empreinte))
            os.replace(cote, self.chemin)
        except OSError as souci:
            return f"empreinte non écrite : {souci.strerror or souci}"
        return ""


def vaults_du_banc():
    """Le module du dépôt qui lit les voûtes du moteur, chargé à l'appel."""
    import sys

    if RACINE not in sys.path:
        sys.path.insert(0, RACINE)
    from script.setops import vaults

    return vaults


def voutes_du_moteur(moteur):
    """Les voûtes que le moteur recense, ou None. Ne lève jamais.

    DEMANDÉ AU MOTEUR : c'est lui qui décide où vit la clé de chaque voûte, et
    son nom dérive du dépôt qui la porte. Le recomposer ici le ferait diverger le
    jour où sa règle change — et une clé posée au mauvais nom n'ouvre rien.
    """
    vaults = vaults_du_banc()
    vu = runner_du_banc().jouer(
        vaults.ARGV_ETAT,
        env=env_ansible(moteur),
        cwd=moteur,
        fusionner=False,
        delai=60,
    )
    return vaults.lit_etat(vu.sortie)


def identite_hebergeur(moteur, voutes):
    """L'identité de la voûte de l'HÉBERGEUR, ou None. Ne lève jamais.

    APPARIÉE PAR LE CHEMIN DE LA CLÉ, jamais par l'étiquette : l'étiquette dérive
    du nom du dépôt, et deviner cette dérivation reviendrait à la recopier. Le
    chemin, lui, vient des deux recensements du moteur — celui des états et celui
    des identités — donc l'appariement est le SIEN.

    C'est la voûte de l'hébergeur parce que c'est elle qui porte le jeton : celle
    du locataire est lue AVANT elle par les deux lecteurs du moteur, et la sienne
    l'emporte quand les deux portent la clé.
    """
    vaults = vaults_du_banc()
    hebergeur = next(
        (v for v in voutes or () if v.role == vaults.HEBERGEUR), None
    )
    if hebergeur is None:
        return None
    vu = runner_du_banc().jouer(
        vaults.ARGV_IDENTITES,
        env=env_ansible(moteur),
        cwd=moteur,
        fusionner=False,
        delai=60,
    )
    identites = vaults.lit_identites(vu.sortie)
    if not identites:
        return None
    return next((i for i in identites if i.cle == hebergeur.chemin), None)


def pose_le_banc(moteur, mesures, chantier, dire=print):
    """Pose ce que le banc exige. Rend (souci, secret). Ne lève jamais.

    LE SECRET EST RENDU À SON SEUL APPELANT, qui le garde en mémoire pour la
    passe qui le porte par l'environnement, et ne le donne à rien d'autre. Il est
    DÉJÀ scellé dans la voûte quand cette fonction rend : la passe par la voûte
    n'en a donc pas besoin, et c'est exactement ce qu'elle prouve.

    NOMMÉ AVANT POSÉ, à chaque pas : c'est le chantier qui écrit, et un pas qui
    n'a pas pu être nommé n'est pas joué.

    L'ORDRE SUIT LES DÉPENDANCES MESURÉES, et chacune a sa raison. Le pont
    d'abord, conscient des VLAN, parce qu'une carte étiquetée sur un pont qui ne
    filtre pas démarre et reste injoignable. L'utilisateur d'API et son jeton
    ensuite : la grappe ne se joint que par lui, et son secret ne s'affiche qu'à
    sa création. Les deux dépôts et leurs liens après, parce que le moteur nomme
    la voûte de l'hébergeur en RÉSOLVANT un lien — sans lui, il ne la nomme pas.
    Les clés enfin, et le jeton scellé dedans.

    S'ARRÊTE AU PREMIER ÉCHEC. Ce qui suit suppose ce qui précède : poser la
    suite sur un pont qui n'a pas monté ferait des VM injoignables, et le
    diagnostic partirait sur la VM.
    """
    terrain, elevation = mesures.terrain, mesures.elevation

    souci = chantier.nomme(pont=mesures.pont)
    if souci:
        return souci, ""
    dire(f"  · pont {mesures.pont} en {CIDR_PONT_BANC}, conscient des VLAN")
    fait = joue_sur(
        terrain,
        cmds_pont(mesures.pont, CIDR_PONT_BANC, mesures.uplink),
        elevation,
    )
    if not fait.reussi:
        return f"le pont n'est pas posé : {fait.sortie.strip()[-200:]}", ""
    vu = joue_sur(terrain, cmds_constater_pont(mesures.pont), elevation)
    constat = lit_constat_pont(vu.sortie, mesures.pont) if vu.reussi else None
    if constat is None or not constat.utilisable:
        # DEBOUT MAIS NON FILTRANT est le pire des trois états : une carte
        # taguée y démarre et reste injoignable, et la panne ne se voit ni à la
        # création, ni dans un code de retour.
        return f"le pont n'est pas utilisable : {constat}", ""

    dire(f"  · utilisateur d'API {UTILISATEUR_API} et son jeton")
    secret = lire_jeton(terrain, elevation)
    if not secret:
        return (
            "le jeton d'API n'a pas été créé, ou son secret ne s'est pas lu",
            "",
        )

    chemins = chemins_du_banc(moteur)
    if chemins is None:
        return "le moteur n'a pas de dossier frère", secret
    _freres, site, _eco = chemins
    souci = chantier.nomme(
        liens=tuple(
            os.path.join(moteur, nom) for nom, _c in cibles_des_liens()
        )
    )
    if souci:
        return souci, secret
    dire(f"  · {UNDERLAY_BANC} et {ECOSYSTEME}, puis les {len(LIENS)} liens")
    montage = monte_localement(
        moteur,
        mesures.noeud,
        mesures.pont,
        mesures.stockage,
        mesures.adresse_api,
        mesures.vmid_gabarit,
    )
    if not montage.complet:
        return montage.souci or "le montage local n'est pas complet", secret

    voutes = voutes_du_moteur(moteur)
    if not voutes:
        return "le moteur n'a pas dit ses voûtes", secret
    souci = chantier.nomme(cles=tuple(v.chemin for v in voutes))
    if souci:
        return souci, secret
    dire(f"  · les {len(voutes)} clés de voûte")
    vaults = vaults_du_banc()
    for voute in voutes:
        pose = vaults.poser_cle(voute.chemin)
        if pose.resultat not in (vaults.POSEE, vaults.DEJA_LA):
            return (
                f"la clé de {voute.nom} : {pose.souci or pose.resultat}",
                secret,
            )

    identite = identite_hebergeur(moteur, voutes)
    if identite is None:
        return "l'identité de la voûte de l'hébergeur ne s'est pas lue", secret
    dire(f"  · le jeton scellé dans {VOUTE_UNDERLAY}")
    return (
        scelle_jeton(
            os.path.join(site, VOUTE_UNDERLAY), identite, secret, moteur
        ),
        secret,
    )


def moteur_du_banc():
    """Le chemin du moteur, tel que le manifeste le DÉCLARE. Ou « ».

    Lu dans la déclaration plutôt qu'écrit ici : c'est le manifeste qui décide où
    le moteur est cloné, et c'est lui aussi qui porte son épingle. Un chemin
    écrit dans le banc dériverait du sien le jour où le manifeste bouge, et le
    banc éprouverait alors un autre moteur que celui que le dépôt épingle.
    """
    import sys

    if RACINE not in sys.path:
        sys.path.insert(0, RACINE)
    from script.setops import engine

    decl = engine.declaration(RACINE)
    if decl is None or not decl.path:
        return ""
    chemin = os.path.join(RACINE, decl.path)
    return chemin if os.path.isdir(chemin) else ""


def chemin_inventaire(moteur):
    """L'inventaire que le générateur du moteur écrit pour le banc."""
    return os.path.join(
        moteur, "instance", "inventories", INVENTAIRE_BANC, "hosts.yml"
    )


def joue_une_passe(moteur, mesures, chantier, passe, secret, dire=print):
    """Joue les cibles du moteur pour une passe. Rend le souci, ou « ».

    L'INVENTAIRE D'ABORD, LES ZONES ENSUITE, LA CONSTRUCTION APRÈS. Le générateur
    vient d'écrire quelles étiquettes et quelles passerelles les hôtes attendent ;
    sans une interface routée par zone, ils démarrent dans un domaine où aucune
    adresse ne répond et la construction ne les joint jamais. Le partage se fait
    sur `confirmer` : ce qui n'écrit pas prépare, ce qui écrit bâtit.

    LES DEUX PASSES NE PROUVENT PAS LA MÊME CHOSE. `env` porte le jeton par
    l'ENVIRONNEMENT, ce que le playbook du moteur accepte en repli : elle valide
    la GRAPPE. `voute` ne le porte pas du tout — le secret est dans la voûte, et
    l'environnement d'un geste est construit à neuf sans aucun `PROXMOX_*` : elle
    valide le CHEMIN DE TODO. Donner le secret aux deux ne prouverait plus rien
    de la voûte.
    """
    env = env_ansible(moteur)
    if passe == PASSE_ENV:
        env = dict(env, **environnement_api(mesures.adresse_api, secret))

    for etape in (e for e in ETAPES_BOUCLE if not e.confirmer):
        souci = joue_une_etape(moteur, env, etape, dire)
        if souci:
            return souci

    souci = route_les_zones(moteur, mesures, chantier, env, dire)
    if souci:
        return souci

    for etape in (e for e in ETAPES_BOUCLE if e.confirmer):
        souci = joue_une_etape(moteur, env, etape, dire)
        if souci:
            return souci
    return ""


def joue_une_etape(moteur, env, etape, dire=print):
    """Joue une cible du moteur et LIT son verdict. Rend le souci, ou « ».

    LE VERDICT SE LIT, code ET sortie : plusieurs gestes du moteur rendent zéro
    en ayant trouvé un écart, et un appelant qui ne lirait que le code
    annoncerait une réussite qui n'a pas eu lieu.
    """
    argv = runner_du_banc().cible(
        moteur, etape.cible, etape.variables, confirmer=etape.confirmer
    )
    dire(f"    {runner_du_banc().cite(argv)}")
    vu = runner_du_banc().jouer(argv, env=env, cwd=moteur, delai=DELAI_ETAPE)
    if vu.code != 0:
        return f"make {etape.cible} : {vu.sortie.strip()[-400:]}"
    return ""


def route_les_zones(moteur, mesures, chantier, env, dire=print):
    """Pose une interface routée par zone du plan. Rend le souci, ou « ».

    DÉRIVÉE DE L'INVENTAIRE QUI VIENT D'ÊTRE APPLIQUÉ, jamais recalculée : c'est
    le moteur qui tire l'étiquette et la passerelle de chaque zone du seul index
    du plan.
    """
    zones = zones_a_router(lit_inventaire(chemin_inventaire(moteur)))
    if zones is None:
        return "l'inventaire généré ne s'est pas lu"
    if not zones:
        return (
            "l'inventaire n'a aucun hôte actif : rien à router, rien à bâtir"
        )
    souci = chantier.nomme(zones=tuple(z.vlan for z in zones))
    if souci:
        return souci
    for zone in zones:
        dire(f"    interface routée {mesures.pont}.{zone.vlan} → {zone.cidr}")
        fait = joue_sur(
            mesures.terrain,
            cmds_svi(zone, mesures.pont, mesures.uplink),
            mesures.elevation,
        )
        if not fait.reussi:
            return (
                f"la zone {zone.vlan} n'est pas routée :"
                f" {fait.sortie.strip()[-200:]}"
            )
    return ""


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
        # APRÈS l'inventaire dans le temps, mais annoncé ici : les zones à
        # router se DÉRIVENT de l'inventaire généré, donc le plan ne peut pas
        # les nommer avant de l'avoir. Il dit ce qu'il fera, pas combien.
        ("une interface routée par zone du plan", "~10 s"),
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

    moteur = moteur_du_banc()
    if not moteur:
        print("\n  ⛔ le moteur n'est pas là : voir l'écran d'état de todo.")
        return SORTIE_OUTILLAGE

    # LES PRÉALABLES SONT TOUS DITS, tenus compris. Ne montrer que ce qui
    # manque laisse croire que le reste n'a pas été regardé, et c'est justement
    # ce qu'on veut pouvoir relire après coup.
    print("\n── les préalables ──")
    mesures = mesure_le_terrain(moteur, terrain)
    vus = prealables(mesures)
    for prealable in vus:
        marque = (
            "✓"
            if prealable.tenu
            else ("✗" if prealable.tenu is False else "?")
        )
        print(f"  {marque} {prealable.quoi}")
        if prealable.dit:
            print(f"      {prealable.dit}")
    if juge(vus) != SORTIE_OK:
        print("\n  rien n'a été tenté.")
        return SORTIE_OUTILLAGE

    print("\n── la pose ──")
    chantier = Chantier(terrain)
    souci, secret = pose_le_banc(moteur, mesures, chantier)
    if souci:
        # EXPURGÉ, comme tout ce que le banc montre : la plainte d'un outil cite
        # parfois ce qu'il a reçu, et ce qu'il a reçu est le secret.
        print(f"\n  ⛔ {expurge(souci, secret)}")
        print(f"     ce qui est posé est nommé dans {chantier.chemin}")
        return SORTIE_NON_CONCLUANTE

    for passe in passes:
        print(f"\n── passe « {passe} » ──")
        souci = joue_une_passe(moteur, mesures, chantier, passe, secret)
        if souci:
            print(f"\n  ⛔ {expurge(souci, secret)}")
            print(f"     ce qui est posé est nommé dans {chantier.chemin}")
            return SORTIE_NON_CONCLUANTE

    print(f"\n  ✓ le banc est allé au bout des {len(passes)} passe(s).")
    print(f"     défaire : {os.path.basename(__file__)} --detruire")
    return SORTIE_OK


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


def lit_nom_vm(sortie):
    """Le nom que `qm config` donne à cette VM, ou « ».

    « » dit « pas su lire », et l'appariement du nom REFUSE alors l'effacement :
    un VMID se réattribue, et effacer sans avoir lu le nom détruirait le travail
    de quelqu'un d'autre.
    """
    for ligne in (sortie or "").splitlines():
        if ligne.startswith("name:"):
            return ligne.split(":", 1)[1].strip()
    return ""


def cmds_utilisateurs():
    """La commande qui nomme les utilisateurs que la grappe connaît."""
    return ["pveum user list --output-format json"]


def lit_utilisateurs(sortie):
    """Les identifiants d'utilisateur que la grappe déclare, ou None.

    Fermé par défaut : ce qui n'est pas une liste d'objets identifiés fait
    refuser toute la lecture. Une lecture qui conclurait à tort « il n'est pas
    là » laisserait sur la grappe un compte d'ADMINISTRATION que le banc croit
    avoir retiré.
    """
    lu = _json_liste(sortie)
    if lu is None:
        return None
    vus = []
    for entree in lu:
        if not isinstance(entree, dict):
            return None
        nom = entree.get("userid")
        if not isinstance(nom, str) or not nom.strip():
            return None
        vus.append(nom.strip())
    return tuple(vus)


def cmds_effacer_api(utilisateur=UTILISATEUR_API):
    """La commande qui retire l'utilisateur d'API et, avec lui, son jeton.

    Retirer l'utilisateur emporte ses jetons et ses entrées de contrôle d'accès :
    les retirer séparément laisserait, si l'un des gestes échouait, un compte
    d'administration sur une grappe que le banc croit avoir quittée.
    """
    return [f"pveum user delete {shlex.quote(utilisateur)}"]


def api_a_retirer(presents, utilisateur):
    """Ce compte d'API est-il à retirer ? None si on ne sait pas.

    SÉPARÉE DU GESTE pour être éprouvable sans grappe : c'est la seule décision
    de la défaite dont l'erreur laisse un ACCÈS OUVERT, et une décision qu'on ne
    peut éprouver que contre une machine n'est pas éprouvée.

    None n'est pas False. « La grappe n'a pas dit ses comptes » et « le compte
    n'y est plus » commandent des suites opposées : la première laisse un souci,
    la seconde est une réussite.
    """
    if presents is None:
        return None
    return (utilisateur or "") in presents


def defait_un_geste(geste, moteur, elevation, dire=print):
    """Défait un geste. Rend le souci, ou « ». Ne lève jamais.

    TOLÈRE L'ABSENCE. L'empreinte nomme AVANT que la pose ait lieu : un nom sans
    objet est donc le cas normal d'une pose interrompue, et non une panne. Ce qui
    n'est PAS toléré est d'effacer autre chose que ce qui est nommé.

    LE RÉSEAU MASQUÉ PART AVEC LA STROPHE. La descente d'une interface joue son
    `post-down`, qui retire la règle de traduction d'adresses : la nommer une
    seconde fois ici la ferait dériver de la strophe.
    """
    genre, vise = geste.genre, geste.vise

    if genre == VM:
        if not vmid_lisible(vise):
            return f"« {vise} » n'est pas un VMID : rien n'est effacé"
        vu = joue_sur(geste.terrain, cmds_config_vm(vise), elevation)
        if not vu.reussi:
            # Une VM déjà absente n'est pas une panne : `qm config` échoue, et
            # il n'y a rien à effacer.
            return ""
        if not effacable(geste.nom, lit_nom_vm(vu.sortie)):
            return (
                f"la VM {vise} ne porte plus le nom « {geste.nom} » :"
                " rien n'est effacé"
            )
        fait = joue_sur(
            geste.terrain, cmds_effacer_vm(vise, geste.nom), elevation
        )
        return "" if fait.reussi else f"la VM {vise} n'a pas été effacée"

    if genre in (SVI, PONT):
        cmds = interface_teardown_cmds_du_banc(vise)
        fait = joue_sur(geste.terrain, cmds, elevation)
        return "" if fait.reussi else f"l'interface {vise} n'a pas été retirée"

    if genre == API:
        # ON DEMANDE D'ABORD S'IL EST LÀ, et ce n'est pas du zèle : un
        # utilisateur déjà absent fait échouer la commande exactement comme un
        # vrai refus. Confondre les deux ferait annoncer une défaite complète
        # alors qu'un compte d'ADMINISTRATION, et le jeton qui va avec, restent
        # sur la grappe — c'est le seul geste de cette liste dont l'échec
        # silencieux laisse un accès ouvert.
        vu = joue_sur(geste.terrain, cmds_utilisateurs(), elevation)
        a_retirer = api_a_retirer(
            lit_utilisateurs(vu.sortie) if vu.reussi else None, vise
        )
        if a_retirer is None:
            return (
                "la grappe n'a pas dit ses utilisateurs :"
                f" « {vise} » n'est pas retiré"
            )
        if not a_retirer:
            return ""
        fait = joue_sur(geste.terrain, cmds_effacer_api(vise), elevation)
        if fait.reussi:
            return ""
        return f"l'utilisateur d'API « {vise} » n'a pas été retiré"

    if genre == LIEN:
        return _retire_lien(vise)

    if genre in (ECO, UNDERLAY):
        return _retire_depot(moteur, genre)

    if genre == CLE:
        return _retire_cle(vise)

    return f"genre inconnu : {genre!r}"


def interface_teardown_cmds_du_banc(nom):
    """Les commandes qui retirent une interface, bâties par le module du dépôt."""
    import sys

    if RACINE not in sys.path:
        sys.path.insert(0, RACINE)
    from script.proxmox import proxmox_deploy as pve

    return list(pve.interface_teardown_cmds(nom))


def _retire_lien(chemin):
    """Retire un lien du moteur. N'efface QUE des liens. Rend le souci, ou « »."""
    if not lien_du_banc(chemin):
        return f"« {chemin} » n'est pas un lien du banc : rien n'est retiré"
    try:
        if not os.path.lexists(chemin):
            return ""
        if not os.path.islink(chemin):
            # NI DOSSIER NI FICHIER ORDINAIRE. Le banc ne pose QUE des liens à
            # ces deux noms : un dossier y est le checkout d'un exploitant, et
            # un fichier ordinaire y est quelque chose que personne d'ici n'a
            # écrit. Effacer l'un détruirait un plan, effacer l'autre un
            # fichier dont on ne sait rien.
            return f"« {chemin} » n'est pas un lien : rien n'est retiré"
        os.remove(chemin)
    except OSError as souci:
        return f"{chemin} : {souci.strerror or souci}"
    return ""


def _retire_depot(moteur, genre):
    """Efface l'un des deux dépôts du banc. Rend le souci, ou « ».

    LE CHEMIN EST DÉRIVÉ, pas lu dans l'empreinte : il dérive du moteur, et le
    lire d'un fichier qu'un éditeur ouvre donnerait à ce fichier le pouvoir de
    faire effacer n'importe quel dossier.
    """
    import shutil

    chemins = chemins_du_banc(moteur)
    if chemins is None:
        return "le moteur n'a pas de dossier frère : rien n'est effacé"
    _freres, site, eco = chemins
    chemin = eco if genre == ECO else site
    try:
        if not os.path.isdir(chemin):
            return ""
        shutil.rmtree(chemin)
    except OSError as souci:
        return f"{chemin} : {souci.strerror or souci}"
    return ""


def _retire_cle(chemin):
    """Efface une clé de voûte DU BANC. Rend le souci, ou « ».

    La clé sans laquelle une voûte ne s'ouvre plus : le garde de NOM est ce qui
    empêche une empreinte modifiée de faire effacer celle d'une production. Il
    est le seul garde ici, et il suffit — l'effacement ne SUIT PAS un lien, si
    bien qu'un lien posé à notre nom perd le lien et non sa cible.
    """
    if not cle_du_banc(chemin):
        return f"« {chemin} » n'est pas une clé du banc : rien n'est effacé"
    try:
        if not os.path.lexists(chemin):
            return ""
        os.remove(chemin)
    except OSError as souci:
        return f"{chemin} : {souci.strerror or souci}"
    return ""


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
    elevation = elevation_du_terrain(empreinte.terrain)
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
        print(f"  {geste.genre:<11} {geste.vise:<42} {geste.nom}")
    if dry_run:
        return SORTIE_OK
    if elevation not in (TEL_QUEL, ELEVE):
        # SANS ÉLÉVATION, RIEN NE SE DÉFAIT SUR LA GRAPPE, et les gestes locaux
        # partiraient quand même : l'empreinte serait alors effacée alors que le
        # pont, les interfaces et l'utilisateur d'API restent. On refuse en bloc.
        print(
            f"  ⛔ le terrain ne se joue pas ({elevation}) : rien n'est défait."
        )
        return SORTIE_NON_CONCLUANTE
    print()
    moteur = moteur_du_banc()
    soucis = []
    for geste in gestes:
        souci = defait_un_geste(geste, moteur, elevation)
        print(f"  {'✗' if souci else '✓'} {geste.genre:<11} {geste.nom}")
        if souci:
            print(f"      {souci}")
            soucis.append(souci)
    if soucis:
        # L'EMPREINTE RESTE. Elle nomme encore ce qui n'a pas été défait, et
        # c'est par elle qu'on y revient ; l'effacer perdrait les noms.
        print(
            f"\n  {len(soucis)} geste(s) n'ont pas abouti :"
            f" l'empreinte reste en place."
        )
        return SORTIE_NON_CONCLUANTE
    try:
        os.remove(chemin_empreinte())
    except OSError:
        # Tout est défait : une empreinte qui survit nommerait du vide, ce qui
        # se voit et ne détruit rien.
        pass
    print("\n  ✓ tout ce que l'empreinte nommait est défait.")
    return SORTIE_OK


if __name__ == "__main__":
    raise SystemExit(principal())
