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

from script.posture import registry, rules
from script.posture import destinations as posture_destinations

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


class Profile(NamedTuple):
    """Un profil : le nom qu'on reconnaît, et la posture qui le tient.

    `install_half` nomme ce qu'il faudrait installer pour que le profil soit
    complet, ou "" quand la posture suffit. Un profil dont cette moitié
    manque n'est pas refusé — il est UTILISABLE, et il le dit.
    """

    label: str
    posture: str
    install_half: str = ""


# L'ordre est celui du registre : du plus libre au plus contraint. « On
# descend vers la contrainte, on n'y tombe pas par défaut. »
PROFILES = (
    Profile("Sandbox", "open"),
    Profile("VM Connecté", "connected"),
    Profile("VM paranoid", "paranoid"),
    # La moitié installation n'existe pas encore, et le dire vaut mieux que
    # de laisser croire qu'un profil nommé « webui » sert une interface.
    Profile("local-webui", "local-only", install_half="serve-webui"),
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


def choices() -> list:
    """[(libellé, nom de posture)] pour un sélecteur.

    La VALEUR reste le nom de posture : c'est lui que la spec porte et que
    le déploiement lit. Un libellé stocké obligerait à le retraduire, et une
    spec relue dans une autre langue ne se retrouverait plus.
    """
    return [(profil.label, profil.posture) for profil in PROFILES]


def gap_sentence(token: str) -> str:
    """La phrase d'un jeton d'écart, traduite. Lève sur un jeton inconnu.

    Un `dict.get` rendant "" afficherait une ligne vide, qui se lit comme
    « rien à signaler » — le contraire d'un écart.
    """
    if token not in GAP_SENTENCES:
        raise KeyError(f"jeton d'écart sans phrase : {token!r}")
    return t(GAP_SENTENCES[token])


def gaps(posture_name: str) -> tuple:
    """Ce que ce profil promet et que rien ne tient, en jetons.

    Vide veut dire que tout ce qu'elle annonce est tenu — soit par la nature
    de son réseau, soit par des règles réellement posées.
    """
    return rules.unenforced(registry.get_posture(posture_name))


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


def screen_line(posture_name: str) -> str:
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
    for jeton in gaps(posture_name):
        morceaux.append(f"⚠ {gap_sentence(jeton)}")
    return "  ".join(morceaux)


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
