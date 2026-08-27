#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Combien d'étages de Proxmox tiennent, et avec quelles ressources.

Un Proxmox dans un Proxmox dans un Proxmox : chaque étage est un hyperviseur
qui héberge le suivant. Deux choses s'épuisent en descendant, et une troisième
se dégrade.

Ce qui s'ÉPUISE — et c'est de l'arithmétique :

* la mémoire. Chaque étage garde de quoi faire tourner ses propres démons
  (pve-cluster, pvestatd, pvedaemon, pveproxy) avant de céder le reste ;
* le disque. Le disque de l'enfant vit DANS celui du parent, qui doit aussi
  contenir son propre système.

Ce qui se DÉGRADE — et c'est mesuré, pas supposé. Au quatrième étage, sur un
hôte AMD, une VM tournait 36 fois moins vite que le temps réel : 583 secondes
d'horloge pour 16 secondes de temps invité, chaque ligne d'ACPI prenant une
seconde. Chaque sortie de VM traverse tous les hyperviseurs empilés, et AMD ne
documente l'imbrication qu'à DEUX niveaux.

Deux nombres viennent de la même mesure, et méritent d'être dits :

* 12 vCPU au quatrième étage ont GELÉ le noyau invité en tout début de
  démarrage — même RIP à trois relevés, deux minutes d'écart, pas un octet lu
  de plus. Les mêmes 2 vCPU avançaient. Le nombre n'était pas le fautif : cette
  VM avait douze vCPU sur un hôte qui en avait DEUX, six fois plus large que sa
  propre machine. C'est le surengagement qui gèle, pas le douze — d'où le
  dimensionnement par étage plus bas, qui donne à chaque parent un vCPU de plus
  qu'à son enfant ;
* cette VM-là s'arrêtait après avoir lu 33 682 432 octets — 32 Mio, soit
  simplement la taille de ses fichiers d'amorçage — et le chiffre ne bougeait
  pas quand on lui retirait de la mémoire. La mémoire n'était donc pas le
  levier, et c'est pourquoi ce module n'en borne pas.

Une descente complète a ensuite RÉFUTÉ ce qu'on avait conclu de la première :
son quatrième étage, à 2 vCPU, a démarré, s'est installé, et a écrit des
gigaoctets. Le plafond était celui du parallélisme sous imbrication, pas celui
de l'imbrication. La profondeur RÉELLEMENT atteignable se mesure — LongTest la
mesure ; ce module ne calcule que ce qui est arithmétiquement possible.
"""

# Ce qu'on laisse à la machine physique : elle fait tourner l'orchestrateur,
# le menu TODO, et le premier QEMU. Un PLANCHER, complété par une part —
# quatre gigaoctets sur une machine de soixante, c'est 6 % laissés à l'hôte,
# et le jour où les invités touchent vraiment leur mémoire c'est l'hôte qui
# part en swap. La mesure serait alors celle du swap, pas de l'imbrication.
HOTE_RESERVE_RAM_MO = 4096
HOTE_RESERVE_PART = 8  # un huitième
HOTE_RESERVE_DISQUE_GO = 20

# Ce qu'un étage garde pour LUI, en plus de ce qu'il cède à son enfant. La
# RAM vient de l'observation d'un Proxmox imbriqué au repos ; le disque, de la
# mesure d'un système installé (5,6 Go) plus de la place pour écrire.
PVE_RAM_MO = 2048
PVE_DISQUE_GO = 10

# Ce dont le PLUS PROFOND a besoin — et c'est de là qu'on part.
#
# Le dimensionnement allait d'abord de haut en bas : chaque étage recevait tout
# ce que son parent pouvait céder. Mesuré sur une descente réelle, l'étage 4 se
# retrouvait avec 44 Go — onze millions de pages à cartographier, chaque défaut
# traversant les quatre hyperviseurs empilés. Son installation dépassait deux
# heures et demie là où l'étage 3 mettait treize minutes, et l'extrapolation
# donnait cinq ANS pour le dixième étage.
#
# On part donc du bas : le plus profond reçoit ce qu'un Proxmox de test demande
# vraiment, et chaque parent ajoute seulement son propre surcoût. Pour dix
# étages, le premier a besoin de 4 + 9×2 = 22 Go au lieu de cinquante — et
# chaque étage est PETIT, donc rapide.
PVE_RAM_CIBLE_MO = 4096
PVE_DISQUE_CIBLE_GO = 25

# En dessous, un Proxmox ne démarre pas ses démons ou n'a plus la place
# d'importer une image cloud.
RAM_MIN_MO = 2048
DISQUE_MIN_GO = 15

# Le processeur se dimensionne DEPUIS LE BAS lui aussi, et pour la même
# raison que la mémoire — mais celle-là s'est vue à l'usage.
#
# Avec deux vCPU à chaque étage imbriqué, l'étage 3 avait deux vCPU pour
# héberger un invité qui en demandait deux : cent pour cent de surengagement,
# et l'hyperviseur lui-même à servir par-dessus. À chaque étage. Mesuré sur une
# descente réelle : une seconde VM démarrée au quatrième étage a lu DEUX
# KILO-OCTETS en onze minutes, affamée par l'installation qui tournait à côté.
#
# Chaque étage reçoit donc UN vCPU de plus que son enfant : le plus profond en
# a deux, son parent trois, et ainsi de suite. Le premier étage d'une descente
# à dix en demande onze — sur vingt-huit cœurs réels, cela passe.
VCPU_IMBRIQUE = 2
# Ce qu'on accepte de prendre à la machine physique : la moitié de ses cœurs.
# L'orchestrateur tourne dessus, et la suite de tests aussi.
VCPU_HOTE_PART = 2

# Au-delà, l'imbrication n'est pas un terrain documenté par les fabricants.
# On ne refuse pas — on le DIT.
PROFONDEUR_SURE = 2


def nesting_plan(
    profondeur: int,
    cpu_hote: int,
    ram_dispo_mo: int,
    disque_libre_go: int,
) -> dict:
    """Les ressources de chaque étage, dimensionnées DEPUIS LE BAS.

    Rend {"demandee", "atteignable", "niveaux": [...], "arret"}. `arret` nomme
    ce qui a manqué — « ram » ou « disque » — quand la profondeur demandée
    n'est pas atteinte, sinon "".

    Depuis le bas, et c'est tout le sujet. De haut en bas, chaque étage
    recevait ce que son parent pouvait céder : mesuré, l'étage 4 se retrouvait
    avec 44 Go de RAM et son installation dépassait deux heures et demie
    contre treize minutes pour l'étage 3. Sous pagination imbriquée, un gros
    invité coûte cher à cartographier, et le coût se multiplie par étage.

    Le plus profond reçoit donc ce qu'un Proxmox de test demande, et chaque
    parent ajoute son surcoût — rien de plus. Une descente à dix étages
    demande alors 22 Go au premier au lieu de cinquante, et chaque étage est
    petit.

    On ne rend jamais un plan qu'on sait impossible : mieux vaut annoncer six
    étages et en réussir six que d'en promettre dix et mourir au septième sans
    savoir pourquoi.
    """
    reserve = max(HOTE_RESERVE_RAM_MO, int(ram_dispo_mo) // HOTE_RESERVE_PART)
    budget_ram = ((int(ram_dispo_mo) - reserve) // 1024) * 1024
    budget_disque = int(disque_libre_go) - HOTE_RESERVE_DISQUE_GO

    def besoin(d):
        """Ce que le PREMIER étage doit avoir pour qu'une descente de `d`
        étages tienne : la cible du bas, plus un surcoût par étage au-dessus.

        Le processeur en fait partie : chaque étage en veut un de plus que son
        enfant, donc le premier en veut VCPU_IMBRIQUE + d - 1. Sans cette
        condition, on annonçait dix étages sur une machine à quatre cœurs.
        """
        return (
            PVE_RAM_CIBLE_MO + (d - 1) * PVE_RAM_MO,
            PVE_DISQUE_CIBLE_GO + (d - 1) * PVE_DISQUE_GO,
            VCPU_IMBRIQUE + d - 1,
        )

    budget_vcpu = max(VCPU_IMBRIQUE, int(cpu_hote) // VCPU_HOTE_PART)
    atteignable, arret = 0, ""
    for d in range(max(0, int(profondeur)), 0, -1):
        ram1, disque1, vcpu1 = besoin(d)
        if (
            ram1 <= budget_ram
            and disque1 <= budget_disque
            and vcpu1 <= budget_vcpu
        ):
            atteignable = d
            break
    if atteignable < int(profondeur):
        # Nommer CE qui a manqué, à la profondeur demandée.
        ram1, disque1, vcpu1 = besoin(max(1, int(profondeur)))
        if ram1 > budget_ram:
            arret = "ram"
        elif disque1 > budget_disque:
            arret = "disque"
        else:
            arret = "vcpu"
    niveaux = [
        {
            "niveau": niveau,
            # UN de plus que son enfant. Un parent aussi étroit que son
            # enfant, c'est cent pour cent de surengagement — et l'hyperviseur
            # à servir en plus.
            "vcpu": VCPU_IMBRIQUE + (atteignable - niveau),
            "ram": PVE_RAM_CIBLE_MO + (atteignable - niveau) * PVE_RAM_MO,
            "disque": PVE_DISQUE_CIBLE_GO
            + (atteignable - niveau) * PVE_DISQUE_GO,
        }
        for niveau in range(1, atteignable + 1)
    ]
    return {
        "demandee": int(profondeur),
        "atteignable": atteignable,
        "niveaux": niveaux,
        "arret": arret,
    }


def depth_from_jumps(jumps: int) -> int:
    """Profondeur d'un hôte, comptée depuis sa chaîne de rebonds.

    Un hôte joint sans rebond est au niveau 1 ; chaque ProxyJump ajoute un
    étage. C'est la seule mesure dont on dispose de l'extérieur, et elle est
    exacte pour les hôtes que nous avons nous-mêmes déployés — c'est nous qui
    écrivons ces entrées.
    """
    return max(1, int(jumps) + 1)


def capped_for_depth(profondeur: int, vcpu: int, ram_mo: int) -> tuple:
    """Ressources bornées pour cette profondeur, et pourquoi.

    Rend (vcpu, ram, raison). `raison` vide quand rien n'a été touché.

    Seul le vCPU est borné, et la mesure le dit : sur la VM examinée au
    quatrième étage, passer de 9 Go à 2 Go n'a rien déplacé — elle s'arrêtait
    après les mêmes 32 Mio, la taille de ses fichiers d'amorçage. Douze vCPU,
    en revanche, gelaient là où deux avançaient, et une descente complète a
    fini par franchir cet étage à 2 vCPU. La RAM passe donc telle quelle : la
    rogner ne gagnerait rien et priverait l'étage suivant, qui en a besoin
    pour héberger le sien.

    Pourquoi borner au lieu d'avertir seulement : l'écran lit la capacité de
    l'HÔTE et l'offre en entier. Sur un troisième étage à 14 cœurs et 9 Go, il
    a proposé 12 vCPU — et la VM n'a jamais démarré. Le nombre n'était pas
    absurde pour la machine ; il l'était pour sa profondeur.
    """
    vcpu, ram_mo = int(vcpu), int(ram_mo)
    if profondeur <= PROFONDEUR_SURE or vcpu <= VCPU_IMBRIQUE:
        return vcpu, ram_mo, ""
    return (
        VCPU_IMBRIQUE,
        ram_mo,
        f"niveau {int(profondeur)} : {vcpu} vCPU -> {VCPU_IMBRIQUE}",
    )
