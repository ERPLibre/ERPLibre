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

* au QUATRIÈME étage, un invité large GÈLE en tout début de démarrage. Mesuré
  deux fois, à douze vCPU puis à huit : même RIP à trois relevés espacés de
  cinq minutes, 32 Mio lus et plus un octet — 106 minutes durant, pour le
  second. Les mêmes 2 vCPU démarrent.

  On avait d'abord imputé le premier gel au SURENGAGEMENT : cette VM à douze
  vCPU tournait sur un hôte qui en avait deux. La seconde mesure l'a réfuté —
  huit vCPU sur un parent qui en avait NEUF, charge 1,47, aucun surengagement,
  et le même gel. C'est bien le nombre de vCPU de l'invité imbriqué, et non son
  rapport à celui de son hôte.

  Au TROISIÈME étage, 9 vCPU démarrent en 117 s. Le seuil est donc entre le
  troisième et le quatrième étage ; tout étage imbriqué reste étroit ;
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
# Une profondeur qu'aucun budget ne borne. Grand, mais fini : « inf » se
# propagerait dans min() et rendrait un float là où tout le reste compte des
# étages entiers.
PLAFOND_LIBRE = 10**6
RAM_MIN_MO = 2048
DISQUE_MIN_GO = 15

# Le processeur NE se dimensionne PAS depuis le bas, contrairement à la
# mémoire et au disque. Trois nombres fixes, et la mesure les impose.
#
# Une première version donnait à chaque parent un vCPU de plus qu'à son enfant,
# pour supprimer le surengagement : le plus profond deux, son parent trois, et
# ainsi de suite jusqu'à onze au premier. Elle rendait donc LARGES les étages
# du milieu — huit au quatrième, sept au cinquième. Or c'est exactement là que
# l'invité gèle : mesuré, l'étage 4 à huit vCPU n'a pas passé son amorçage en
# 106 minutes, sur un parent à neuf vCPU parfaitement sain. La règle rendait
# large ce qui doit rester étroit.
#
# Le plus profond : deux, le seul chiffre dont on ait la preuve qu'il démarre
# au quatrième étage.
VCPU_IMBRIQUE = 2
# Les étages imbriqués PEU PROFONDS : un de plus, pour héberger leur enfant
# sans être aussi étroits que lui. Deux hébergeant deux, c'est cent pour cent
# de surengagement — et l'installation de l'étage 4 dépassait alors 2 h 50
# contre 793 s pour l'étage 3.
#
# « Peu profonds », et c'est la mesure qui l'impose. Ce troisième vCPU ne coûte
# RIEN aux étages 2 et 3 — leur ssh répond en 37 s et 93 s, comme à deux vCPU —
# et il coûte tout au quatrième : 15 608 s, soit 4 h 20, contre 1 664 s à deux
# vCPU. Un seul vCPU de plus, l'amorçage multiplié par 9,4.
VCPU_INTERMEDIAIRE = 3
# Le premier étage qui doit rester au strict minimum.
#
# Amorçage du quatrième étage, mesuré : 1 664 s à 2 vCPU, 15 608 s à 3, jamais
# à 8 ni à 12 — même RIP à cinq minutes d'intervalle. Le « gel » observé à 8 et
# 12 n'est probablement pas autre chose que cette courbe poussée assez loin :
# 1 664 × 9,4 par vCPU supplémentaire dépasse vite toute patience.
#
# Aux étages 2 et 3, la même largeur ne coûte rien. Le seuil est donc là.
SEUIL_ETROIT = 4
# Le premier étage tourne sur le MÉTAL : aucun risque de gel, et son amorçage
# est rapide — onze vCPU y ont démarré en 42 s. Il n'a pourtant qu'un enfant à
# trois vCPU à servir ; quatre suffisent, et laissent la machine physique aux
# autres.
VCPU_METAL = 4
# Ce qu'on LAISSE à la machine physique. L'orchestrateur tourne dessus, son
# ssh vers chaque étage aussi, et la suite de tests avec.
#
# Un nombre fixe, et non une fraction : « la moitié des cœurs » gardait
# quatorze cœurs inutilisés sur vingt-huit, et sur une machine à deux cœurs le
# plancher qui l'accompagnait rendait un budget de deux — soit la machine
# entière, hôte compris.
#
# Deux, et pas plus : l'orchestrateur passe son temps à ATTENDRE du ssh, il ne
# calcule rien. Quatre auraient interdit toute descente sur un hôte à quatre
# cœurs, où un étage tient très bien. Sur une machine trop petite le plan rend
# franchement zéro étage plutôt que de surengager l'hôte.
HOTE_RESERVE_VCPU = 2

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

    Rend {"demandee", "atteignable", "niveaux", "arret", "plafonds"}.

    `arret` nomme la ressource qui BORNE réellement la profondeur — "ram",
    "disque" ou "vcpu" — et "" si la profondeur demandée tient. `plafonds`
    donne les trois profondeurs, une par ressource, pour qu'on puisse voir
    d'un coup ce qu'il faudrait ajouter et de combien.

    Nommer la bonne, c'est le sujet : la version d'avant prenait la première
    d'une chaîne figée ram > disque > vcpu, évaluée à la profondeur DEMANDÉE.
    Sur une machine à deux cœurs et 20 Go, elle annonçait « manque de ram »
    quand le processeur bornait à un seul étage ; l'opérateur doublait la
    mémoire et n'y gagnait pas un étage.

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

        Le processeur n'en fait PAS partie de la même façon : il ne croît
        pas avec la profondeur — il DÉCROÎT, et se stabilise à
        VCPU_IMBRIQUE dès SEUIL_ETROIT. Le premier étage demande VCPU_METAL,
        quelle que soit la profondeur.
        """
        return (
            PVE_RAM_CIBLE_MO + (d - 1) * PVE_RAM_MO,
            PVE_DISQUE_CIBLE_GO + (d - 1) * PVE_DISQUE_GO,
            VCPU_METAL if d > 1 else VCPU_IMBRIQUE,
        )

    budget_vcpu = int(cpu_hote) - HOTE_RESERVE_VCPU
    # La profondeur que chaque budget permet À LUI SEUL. C'est de l'inverse de
    # `besoin` : un balayage décroissant donnait le même résultat, mais son
    # coût suivait la profondeur demandée — nesting_plan(10**6, …) tournait un
    # million de tours pour rendre le même plan.
    plafonds = {
        "ram": (budget_ram - PVE_RAM_CIBLE_MO) // PVE_RAM_MO + 1,
        "disque": (budget_disque - PVE_DISQUE_CIBLE_GO) // PVE_DISQUE_GO + 1,
        # Le processeur ne borne plus la profondeur : les étages imbriqués
        # gardent une largeur fixe, seul le premier compte sur le métal. Il
        # borne encore à ZÉRO une machine trop petite pour ce premier étage.
        "vcpu": PLAFOND_LIBRE if budget_vcpu >= VCPU_METAL else 0,
    }
    plafonds = {nom: max(0, valeur) for nom, valeur in plafonds.items()}
    demandee = max(0, int(profondeur))
    atteignable = min(demandee, *plafonds.values())
    arret = ""
    if atteignable < demandee:
        # La ressource qui BORNE, c'est-à-dire celle dont le plafond est le
        # plus bas — pas la première d'un ordre figé. En ajouter une autre ne
        # ferait pas monter la profondeur d'un seul étage.
        arret = min(plafonds, key=lambda nom: (plafonds[nom], nom))
    niveaux = [
        {
            "niveau": niveau,
            # Le métal peut être large ; un étage imbriqué peu profond
            # gagne son troisième vCPU pour héberger son enfant sans
            # surengagement ; à partir de SEUIL_ETROIT, le strict minimum,
            # parce que là ce troisième vCPU multiplie l'amorçage par 9,4.
            #
            # L'étage juste AU-DESSUS du seuil garde donc trois quand son
            # enfant en a deux : c'est le seul endroit de la descente où le
            # surengagement disparaît, et c'est celui qui compte, puisque
            # l'étage 4 est le premier dont l'installation s'effondrait.
            "vcpu": (
                VCPU_METAL
                if niveau == 1
                else (
                    VCPU_IMBRIQUE
                    if niveau >= SEUIL_ETROIT
                    else VCPU_INTERMEDIAIRE
                )
            ),
            # Les planchers ne sont pas décoratifs : ils tiennent même si
            # quelqu'un baisse une CIBLE un jour. Sans eux, ils n'étaient plus
            # lus par personne et les tests qui les vérifiaient passaient
            # d'eux-mêmes.
            "ram": max(RAM_MIN_MO, PVE_RAM_CIBLE_MO)
            + (atteignable - niveau) * PVE_RAM_MO,
            "disque": max(DISQUE_MIN_GO, PVE_DISQUE_CIBLE_GO)
            + (atteignable - niveau) * PVE_DISQUE_GO,
        }
        for niveau in range(1, atteignable + 1)
    ]
    return {
        "demandee": int(profondeur),
        "atteignable": atteignable,
        "niveaux": niveaux,
        "arret": arret,
        "plafonds": plafonds,
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
