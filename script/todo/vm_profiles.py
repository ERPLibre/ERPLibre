#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les profils de VM : un nom qu'on reconnaît, et ce qu'il tient VRAIMENT.

POURQUOI DES NOMS À PART. `script/posture/` nomme ses postures pour le code
— « open », « connected » — et son paquet est PUR : il ne traduit rien et
n'affiche rien, une épreuve l'interdit. Les noms qu'un humain reconnaît
vivent donc ici, dans la couche qui parle.

Ils ne sont pas inventés : le registre les porte déjà dans ses propres
commentaires. « Bac à sable » pour la libre, « Connectée », « Paranoïde ».

« LOCAL-WEBUI » N'EST PAS UNE POSTURE, et le registre le dit : « c'est la
moitié « réseau » de ce qu'on appelait « local-webui » ; l'autre moitié est
un profil d'installation, et les séparer est ce qui permet de servir autre
chose sur la même posture ». Le profil porte donc le nom entier, et sa
moitié réseau est `local-only` — mais il ne PRÉTEND pas que la moitié
installation existe : `install_half` dit ce qui manque, en un mot.

CE QUE L'ÉCRAN DOIT DIRE. `rules.unenforced(posture)` rend la liste de ce
qu'une posture promet et que rien ne tient — le mécanisme même que le dépôt
a bâti pour empêcher un « nom rassurant » de passer inaperçu. Rien ne le
lisait. Un profil qui affiche son nom sans afficher ça vend exactement
l'assurance que le registre s'interdit de donner.
"""
from __future__ import annotations

from typing import NamedTuple

from script.posture import destinations as posture_destinations
from script.posture import registry, rules

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


class Profile(NamedTuple):
    """Un profil : le nom qu'on reconnaît, et la posture qui le tient.

    `serves_web` dit que le NOM du profil promet une interface servie. Ce
    n'est pas une posture — le registre l'écrit lui-même : « l'autre moitié
    est un profil d'installation, et les séparer est ce qui permet de servir
    autre chose sur la même posture ». C'est donc une EXIGENCE sur ce qu'on
    installe, vérifiée par déploiement et non déclarée une fois pour toutes.
    """

    label: str
    posture: str
    serves_web: bool = False


# L'ordre est celui du registre : du plus libre au plus contraint. « On
# descend vers la contrainte, on n'y tombe pas par défaut. »
PROFILES = (
    Profile("Sandbox", "open"),
    Profile("VM Connecté", "connected"),
    Profile("VM paranoid", "paranoid"),
    # Son nom promet une interface servie : l'installation choisie doit
    # poser Odoo, sinon la VM ne sert rien et le nom ment.
    Profile("local-webui", "local-only", serves_web=True),
)

# Ce que chaque jeton d'`unenforced` veut dire pour qui lit un écran. La
# table est EXHAUSTIVE : un jeton sans phrase lève plutôt que de s'afficher
# comme une ligne vide, qui se lirait comme « rien à signaler ».
GAP_SENTENCES = {
    rules.NO_RENDERING: (
        "No rule file is produced: this posture states a policy that"
        " nothing installs. It behaves exactly like free egress."
    ),
    rules.RELOAD_FAILURE_UNSEEN: (
        "A failed reload of the rules on a later boot is not reported."
    ),
    rules.CONTAINERS_UNPROVEN: (
        "Container traffic is not proven to be caught: it crosses FORWARD,"
        " which no confrontation has measured yet."
    ),
    rules.BOOT_WINDOW_OPEN: (
        "This path lays the rules down only once the machine answers, so"
        " it goes out freely for the whole of its first boot — minutes,"
        " not seconds."
    ),
}


def profiles() -> tuple:
    """Les profils, dans l'ordre où un écran les propose."""
    return PROFILES


def by_label(label: str):
    """Le profil qui porte ce libellé, ou None."""
    for profil in PROFILES:
        if profil.label == label:
            return profil
    return None


def by_posture(name: str):
    """Le profil bâti sur cette posture, ou None.

    Sert au chemin INVERSE : une spec porte un nom de posture, et l'écran
    qui la relit doit retrouver le libellé sous lequel elle a été choisie.
    """
    for profil in PROFILES:
        if profil.posture == name:
            return profil
    return None


def label_of(posture_name: str) -> str:
    """Le libellé de cette posture, ou son nom brut si aucun profil ne la
    porte.

    Le nom BRUT plutôt qu'une chaîne vide : une posture ajoutée au registre
    sans profil doit rester choisissable et lisible, pas disparaître de
    l'écran — ce qui la rendrait indéployable sans qu'on sache pourquoi.
    """
    profil = by_posture(posture_name)
    return profil.label if profil else str(posture_name or "")


def _carries_real_data(profil) -> bool:
    """Ce profil peut-il porter des données réelles ?

    Le prédicat du registre, et non un champ de plus : `allows_real_data`
    DÉDUIT la réponse de trois propriétés de la posture, et un profil qui
    déclarerait « oui » de son côté pourrait contredire la garde qui refuse
    le déploiement.
    """
    return registry.allows_real_data(registry.get_posture(profil.posture))


def choices(real_data: bool = False) -> list:
    """[(libellé, nom de posture)] pour un sélecteur.

    La VALEUR reste le nom de posture : c'est lui que la spec porte et que
    le déploiement lit. Un libellé stocké obligerait à le retraduire, et une
    spec relue dans une autre langue ne se retrouverait plus.

    `real_data` retire les postures sous lesquelles la garde REFUSERA le
    déploiement. Le filtre lit le même prédicat qu'elle : offrir une posture
    que le déploiement rejette fait répondre à tout le questionnaire avant
    de le dire. Faux par défaut, pour qu'un appelant qui ne pose pas la
    question offre la liste entière.
    """
    return [
        (profil.label, profil.posture)
        for profil in PROFILES
        if not real_data or _carries_real_data(profil)
    ]


def withheld(real_data: bool = False) -> list:
    """Ce que `choices(real_data)` a retiré, dans le même ordre.

    Un écran les nomme au lieu de les taire : une liste qui rétrécit sans
    rien dire laisse croire que la posture n'existe pas, et son absence se
    lit alors comme une panne. Le complément exact de `choices`, pour que
    les deux ne puissent pas diverger.
    """
    offerts = {posture for _libelle, posture in choices(real_data)}
    return [
        (profil.label, profil.posture)
        for profil in PROFILES
        if profil.posture not in offerts
    ]


def gap_sentence(token: str) -> str:
    """La phrase d'un jeton d'écart, traduite. Lève sur un jeton inconnu.

    Un `dict.get` rendant "" afficherait une ligne vide, qui se lit comme
    « rien à signaler » — le contraire d'un écart.
    """
    if token not in GAP_SENTENCES:
        raise KeyError(f"jeton d'écart sans phrase : {token!r}")
    return t(GAP_SENTENCES[token])


def gaps(posture_name: str, after_boot: bool = False) -> tuple:
    """Ce que ce profil promet et que rien ne tient, en jetons.

    Vide veut dire que tout ce qu'elle annonce est tenu — soit par la nature
    de son réseau, soit par des règles réellement posées.

    `after_boot` décrit le CHEMIN et non la posture : là où les règles
    n'arrivent qu'une fois la machine debout, elle sort librement pendant
    tout son démarrage. Faux par défaut, comme dans le paquet posture, pour
    que l'écran d'un chemin qui écrit avant le premier boot ne porte pas un
    écart qui n'est pas le sien.
    """
    return rules.unenforced(registry.get_posture(posture_name), after_boot)


def enforcement(posture_name: str) -> str:
    """Ce que ce profil APPLIQUE, en une ligne, sans rien promettre.

    Trois états, et ils ne se confondent pas. « Rien à contraindre » est le
    cas de la sortie libre : il n'y a pas de politique à tenir, et le dire
    n'est pas un aveu. « Des règles sont posées » est le cas où un fichier
    nftables est écrit, chargé et armé dans l'invité. « Intention seulement »
    est le pire des deux mondes, et c'est exactement ce que ce module existe
    pour montrer.
    """
    posture = registry.get_posture(posture_name)
    if posture is None:
        return t("Unknown posture: this profile deploys nothing.")
    if not rules.wants_rules(posture):
        if posture.egress == "nat":
            return t("Nothing is confined, and that is the point.")
        return t(
            "INTENTION ONLY: this posture states a policy that no rule"
            " installs. It behaves like free egress."
        )
    return t("Rules are written, loaded and armed in the guest.")


def bounded_addresses(posture_name: str) -> bool:
    """Ce profil demande-t-il au site de nommer des adresses ?

    Vrai, un carnet vide fait REFUSER le déploiement — et le dire devant
    l'écran vaut mieux que de le découvrir sur la machine.
    """
    return posture_destinations.has_bounded_list(
        registry.get_posture(posture_name)
    )


def screen_line(posture_name: str, after_boot: bool = False) -> str:
    """Ce qu'un écran écrit sous le sélecteur, en une seule chaîne.

    La COMPOSITION vit ici et non dans le formulaire : celui-ci est du
    Textual, qu'aucune épreuve unitaire ne pilote. Ce qui reste là-bas est
    une affectation ; tout ce qui décide est ici, et se relit sans
    terminal.

    Les écarts suivent l'application sur la même ligne, préfixés d'un
    avertissement : les mettre ailleurs les ferait lire séparément de ce
    qu'ils nuancent, et un écart lu seul se prend pour une panne.
    """
    morceaux = [enforcement(posture_name)]
    for jeton in gaps(posture_name, after_boot):
        morceaux.append(f"⚠ {gap_sentence(jeton)}")
    # CE QUE LE NOM PROMET, quand il promet quelque chose. Dit ICI parce que
    # c'est l'instant du choix : l'avertissement de validation, lui, arrive
    # quand les DEUX choix existent, et ne dit que ce qui cloche.
    profil = by_posture(posture_name)
    if profil is not None and profil.serves_web:
        morceaux.append(t(EXPECTS_ODOO))
    return "  ".join(morceaux)


def form_context(after_boot: bool = False) -> dict:
    """Les trois clés de posture qu'un écran de déploiement attend.

    UNE fonction et non trois clés recopiées d'un menu à l'autre. Le
    second écran a été écrit en recopiant le premier, et ce qui s'y perd
    ne se voit pas : une clé écrite d'un côté sous un autre nom laisse la
    ligne vide, sans message et sans erreur.

    `after_boot` décrit le CHEMIN et non la posture : là où les règles
    n'arrivent qu'une fois la machine debout, la ligne porte l'écart de la
    fenêtre de démarrage. Faux par défaut, pour qu'un chemin qui écrit
    avant le premier boot ne porte pas un écart qui n'est pas le sien.
    """
    return {
        # L'ordre du registre, du plus libre au plus contraint : on
        # descend vers la contrainte, on n'y tombe pas.
        "posture": registry.DEFAULT_POSTURE,
        # Les libellés qu'un humain reconnaît. La VALEUR reste le nom de
        # posture : c'est lui que la spec porte, et un libellé stocké se
        # retraduirait mal d'une langue à l'autre.
        "posture_choices": choices(),
        # CE QUE CHACUNE APPLIQUE, ses écarts, et ce que son nom promet —
        # en une ligne. Un écran qui nomme une posture sans dire ce qu'elle
        # applique VRAIMENT vend l'assurance que le registre s'interdit de
        # donner : le nom rassure, et deux postures au nom voisin ne tiennent
        # pas la même chose.
        "posture_screen": {
            nom: screen_line(nom, after_boot)
            for nom in registry.posture_names()
        },
    }


def missing_addresses(posture_name: str, book) -> tuple:
    """Les rôles que ce profil nomme et que le carnet n'adresse pas.

    Vide veut dire que le déploiement passera. Non vide, il REFUSERA — et
    le dire devant l'écran vaut mieux que de le découvrir après avoir
    rempli un formulaire entier.

    Le carnet est un PARAMÈTRE : ce module ne lit aucun fichier, et la
    liste des rôles vient du paquet posture, qui la déduit de la posture.
    """
    from script.posture import destinations as posture_destinations

    # PAS DE GARDE SUR None : `symbols_for` en pose déjà un — il passe par
    # `has_bounded_list`, qui répond faux pour une posture absente. Le
    # doubler ici ferait deux endroits à tenir en accord, et le second ne
    # se casserait jamais assez fort pour qu'on s'en aperçoive.
    posture = registry.get_posture(posture_name)
    carnet = book or {}
    return tuple(
        symbole
        for symbole in posture_destinations.symbols_for(posture)
        if symbole not in carnet
    )


# CE QUI, DANS UNE COMMANDE D'INSTALLATION, POSE ODOO. La marque et non la
# liste des profils : ceux-ci se composent — « install_odoo_18 »,
# « install_odoo_all_version » — et une liste recopiée manquerait le
# suivant. C'est la même marque que le déploiement emploie pour décider
# d'enregistrer le service systemd, et elle est nommée UNE fois.
ODOO_MARK = "install_odoo"

# Ce que dit un profil dont le nom promet une interface servie, au moment
# du CHOIX. Une attente et non un refus : servir autre chose sur la même
# posture reste légitime, et le registre sépare les deux pour cela.
EXPECTS_ODOO = "This profile expects an install that lays down Odoo."

# L'en-tête des postures que `withheld` a retirées. Elles s'affichent avec
# leur raison plutôt que de disparaître : une liste qui rétrécit en silence
# laisse croire que la posture n'existe pas, et son absence se lit alors
# comme une panne plutôt que comme une règle.
CANNOT_CARRY_REAL_DATA = "Cannot carry real data:"

# Le verdict du couple (profil, installation). Clos, comme celui du couple
# (posture, données réelles) dont il est le frère.
INSTALL_OK = "ok"
SERVES_NOTHING = "serves-nothing"
INSTALL_VERDICTS = (INSTALL_OK, SERVES_NOTHING)

INSTALL_SENTENCES = {
    INSTALL_OK: "The install serves what the profile promises.",
    SERVES_NOTHING: (
        "This profile's name promises a served interface, and the chosen"
        " install lays down no Odoo. The machine would serve nothing under"
        " a name that says otherwise."
    ),
}


def check_install(label: str, final_cmd: str) -> str:
    """Le verdict du couple (LIBELLÉ choisi, installation). Ne lève pas.

    IL PREND UN LIBELLÉ ET NON UNE POSTURE, et c'est tout le sujet. Une
    spec porte une posture ; le registre sépare les deux exprès — « les
    séparer est ce qui permet de servir autre chose sur la même posture ».
    Déduire « on voulait une interface web » de « on a choisi local-only »
    inverse cette séparation : ce serait refuser la seule posture qui porte
    une donnée réelle, sur la foi d'un nom que personne n'a choisi.

    La question ne se pose donc QUE là où le libellé existe — le
    formulaire, au moment du choix — et elle s'y dit, elle ne s'y refuse
    pas : servir autre chose sur cette posture reste légitime.

    Un profil qui ne promet rien accepte toute installation.
    """
    profil = by_label(label)
    if profil is None or not profil.serves_web:
        return INSTALL_OK
    if ODOO_MARK in (final_cmd or ""):
        return INSTALL_OK
    return SERVES_NOTHING


def install_sentence(verdict: str) -> str:
    """La phrase d'un verdict d'installation. Lève sur un verdict inconnu.

    Un `dict.get` rendant "" afficherait une ligne vide, qui se lit comme
    « rien à signaler » — le contraire d'un refus.
    """
    if verdict not in INSTALL_SENTENCES:
        raise KeyError(f"verdict d'installation sans phrase : {verdict!r}")
    return t(INSTALL_SENTENCES[verdict])
