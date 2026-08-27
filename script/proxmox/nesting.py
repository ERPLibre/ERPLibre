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
  de plus. Les mêmes 2 vCPU avançaient. D'où VCPU_IMBRIQUE = 2 : amener douze
  processeurs en ligne demande autant d'allers-retours à travers la pile ;
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

# Ce qu'un étage garde pour lui avant de céder le reste. La RAM vient de
# l'observation d'un Proxmox imbriqué au repos ; le disque, de la mesure d'un
# système installé (5,6 Go) plus de la place pour écrire.
PVE_RAM_MO = 2048
PVE_DISQUE_GO = 10

# En dessous, un Proxmox ne démarre pas ses démons ou n'a plus la place
# d'importer une image cloud.
RAM_MIN_MO = 2048
DISQUE_MIN_GO = 15

# Le premier étage tourne sur la machine physique : il peut être large. Les
# suivants non — voir la mesure dans l'en-tête.
VCPU_NIVEAU1_MAX = 4
VCPU_IMBRIQUE = 2

# Au-delà, l'imbrication n'est pas un terrain documenté par les fabricants.
# On ne refuse pas — on le DIT.
PROFONDEUR_SURE = 2


def nesting_plan(
    profondeur: int,
    cpu_hote: int,
    ram_dispo_mo: int,
    disque_libre_go: int,
) -> dict:
    """Les ressources de chaque étage, et jusqu'où l'arithmétique va.

    Rend {"demandee", "atteignable", "niveaux": [...], "arret"}. `arret`
    nomme ce qui a manqué — « ram » ou « disque » — quand la profondeur
    demandée n'est pas atteinte, sinon "".

    On ne rend jamais un plan qu'on sait impossible : mieux vaut annoncer six
    étages et en réussir six que d'en promettre dix et mourir au septième
    sans savoir pourquoi.
    """
    # Arrondi au gibioctet inférieur : « --memory 25203 » marche, mais un
    # nombre rond se relit, se compare d'un étage à l'autre, et évite de
    # traîner les kibioctets du hasard de la mesure jusqu'au dixième étage.
    reserve = max(HOTE_RESERVE_RAM_MO, int(ram_dispo_mo) // HOTE_RESERVE_PART)
    ram = ((int(ram_dispo_mo) - reserve) // 1024) * 1024
    disque = int(disque_libre_go) - HOTE_RESERVE_DISQUE_GO
    niveaux, arret = [], ""
    # « max(1, …) » forçait un tour : profondeur 0 rendait un plan d'UN
    # étage, et « --depth 0 » créait donc une VM. range(1, 1) est déjà vide,
    # et un plan vide est la bonne réponse à une demande vide.
    for niveau in range(1, int(profondeur) + 1):
        if niveau > 1:
            ram -= PVE_RAM_MO
            disque -= PVE_DISQUE_GO
        if ram < RAM_MIN_MO:
            arret = "ram"
            break
        if disque < DISQUE_MIN_GO:
            arret = "disque"
            break
        niveaux.append(
            {
                "niveau": niveau,
                # Le plancher est VCPU_IMBRIQUE et non 1 : sur un hôte de
                # quatre cœurs, « // 4 » donnait UN vCPU au premier étage —
                # l'hyperviseur parent — alors que son invité en recevait
                # deux. Un parent plus étroit que son enfant est absurde, et
                # c'est tout l'inverse de ce que ce module raconte.
                "vcpu": (
                    max(
                        VCPU_IMBRIQUE,
                        min(VCPU_NIVEAU1_MAX, int(cpu_hote) // 4),
                    )
                    if niveau == 1
                    else VCPU_IMBRIQUE
                ),
                "ram": ram,
                "disque": disque,
            }
        )
    return {
        "demandee": int(profondeur),
        "atteignable": len(niveaux),
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
