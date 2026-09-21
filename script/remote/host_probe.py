#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Est-ce bien l'appliance annoncée, et peut-on lui commander quelque chose ?

Une adresse saisie à la main peut désigner n'importe quelle machine. Sans
preuve, la première commande du produit échoue sur un « command not found »
qui n'explique rien — et le message qui suit envoie chercher au mauvais
endroit.

Ce module DÉCIDE et n'affiche rien. Il rend un verdict nommé, l'appelant
l'écrit comme son menu l'écrit. Séparer les deux est ce qui rend la décision
vérifiable sans terminal, et ce qui permet à deux appliances d'en partager
la logique sans partager leurs phrases.

QUATRE PANNES, ET NON UNE. Un message unique confondait « la machine ne
répond pas » et « elle répond mais le produit n'y est pas » : le premier
envoie vérifier le réseau, le second envoie installer, et les corriger se
fait de deux côtés opposés. S'y ajoutent la clé d'hôte pas encore connue —
qui n'est pas une panne mais un accord qui manque — et le privilège absent.

Le privilège absent se dit de DEUX façons, selon ce que l'appelant en exige :
NEEDS_ROOT quand il le fallait — l'hôte est inutilisable —, NO_PRIVILEGE
quand il était bienvenu sans être requis — l'hôte est utilisable, et ce qui
demande root ne l'est pas. Les confondre ferme un hôte sain, ou laisse
découvrir le refus au milieu d'une installation.
"""

from __future__ import annotations

from typing import Callable, NamedTuple

from script.remote import appliance_ssh

# Le vocabulaire des verdicts, clos. Un cinquième cas se déclare ici, où les
# appelants le verront, plutôt que de se glisser dans une chaîne libre.
OK = "ok"
HOSTKEY = "hostkey"
PRODUCT_ABSENT = "product-absent"
UNREACHABLE = "unreachable"
NEEDS_ROOT = "needs-root"
NO_PRIVILEGE = "no-privilege"
VERDICTS = (
    OK,
    HOSTKEY,
    PRODUCT_ABSENT,
    UNREACHABLE,
    NEEDS_ROOT,
    NO_PRIVILEGE,
)

# Ce que l'appelant EXIGE du privilège, et non ce qu'il en constate. Toutes
# les appliances ne le demandent pas au même titre : administrer un
# hyperviseur l'exige à chaque commande, alors qu'un déploiement lit sa
# version, pousse ses fichiers et lit ses journaux sans lui, et n'en a besoin
# que pour deux verbes sur onze. Refuser l'hôte dans le second cas
# interdirait neuf verbes qui marchent.
REQUIRED = "required"
OPTIONAL = "optional"
SKIP = "skip"
PRIVILEGE_MODES = (REQUIRED, OPTIONAL, SKIP)


class Verdict(NamedTuple):
    """Ce que la sonde a conclu, et de quoi l'écrire.

    `detail` est la ligne qui APPREND quelque chose — ce que la sonde du
    produit a répondu, et non ce que le test de vie a dit : « command not
    found » est la preuve utile, « ok » ne l'est pas.

    `raw` porte la sortie ENTIÈRE de la sonde. Un produit y dit souvent plus
    que sa version — le noyau chargé, une édition — et la redemander coûterait
    un aller-retour de plus pour une réponse qu'on a déjà.
    """

    kind: str
    version: str = ""
    sudo: str = ""
    detail: str = ""
    raw: str = ""


def _premiere_ligne_utile(sortie: str) -> str:
    """La première ligne qui reste une fois ssh retiré de sa propre sortie."""
    for ligne in appliance_ssh.strip_ssh_noise(sortie).splitlines():
        if ligne.strip():
            return ligne.strip()
    return ""


def ssh_alive(host: dict, run: Callable = None) -> tuple:
    """(ssh passe-t-il ?, ce qu'il a dit) — sans rien exiger de la machine.

    La question qu'il faut poser AVANT de conclure : une machine qui répond
    mais n'a pas le produit n'est pas « injoignable », et les deux pannes ne
    se corrigent pas du même côté.
    """
    run = run or appliance_ssh.run
    code, sortie = run(host, "true", timeout=20)
    return code == 0, _premiere_ligne_utile(sortie)


def privilege_prefix(host: dict, run: Callable = None) -> tuple:
    """(préfixe, obtenu ?) — « sudo » quand il faut et qu'il ne demande rien.

    Un sudo qui réclame un mot de passe bloquerait chaque commande du menu
    sur une invite que personne ne voit : on le VÉRIFIE au lieu de l'espérer.
    """
    run = run or appliance_ssh.run
    _code, qui = run(host, "id -u", timeout=20)
    if qui.strip() == "0":
        return "", True
    code, _sortie = run(host, "sudo -n true", timeout=20)
    if code:
        return "", False
    return "sudo ", True


def diagnose(
    host: dict,
    probe: str,
    parse: Callable,
    run: Callable = None,
    privilege: str = REQUIRED,
) -> Verdict:
    """Sonde l'hôte et NOMME ce qu'il a trouvé, sans rien afficher.

    `probe` est la commande qui prouve le produit, `parse` en tire la
    version. Une version vide signifie « pas ce produit », quel qu'ait été le
    code de sortie : un produit absent répond souvent 127, mais pas toujours.

    Rendre HOSTKEY n'est pas un refus : c'est un accord qui manque, et
    l'appelant peut l'obtenir puis re-sonder.

    `privilege` dit ce que l'appelant EXIGE : « required » refuse l'hôte qui
    ne peut pas s'élever, « optional » le constate sans le refuser, « skip »
    ne le mesure pas — et épargne alors un à deux allers-retours, qui sont
    autant de secondes d'attente devant un menu.
    """
    if privilege not in PRIVILEGE_MODES:
        raise ValueError(
            f"privilege={privilege!r} : attendu l'un de"
            f" {', '.join(PRIVILEGE_MODES)}."
        )
    run = run or appliance_ssh.run
    _code, sortie = run(host, probe, timeout=30)
    version = parse(sortie)
    if not version:
        if appliance_ssh.hostkey_missing(sortie):
            return Verdict(
                HOSTKEY,
                detail=_premiere_ligne_utile(sortie),
                raw=sortie,
            )
        joignable, dit = ssh_alive(host, run=run)
        if joignable:
            # Ce que la SONDE a répondu, pas ce que le test de vie a dit.
            return Verdict(
                PRODUCT_ABSENT,
                detail=_premiere_ligne_utile(sortie),
                raw=sortie,
            )
        return Verdict(UNREACHABLE, detail=dit, raw=sortie)
    if privilege == SKIP:
        return Verdict(OK, version=version, raw=sortie)
    prefixe, obtenu = privilege_prefix(host, run=run)
    if not obtenu:
        manque = NEEDS_ROOT if privilege == REQUIRED else NO_PRIVILEGE
        return Verdict(manque, version=version, raw=sortie)
    return Verdict(OK, version=version, sudo=prefixe, raw=sortie)
