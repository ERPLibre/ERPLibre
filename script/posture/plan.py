#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Où le fichier de règles se pose, comment il se charge, et ce qu'on relit.

Le texte des règles existe ; il ne disait ni son chemin, ni la commande qui
le charge, ni comment savoir après coup s'il a pris. Trois chaînes et un
analyseur, tous purs : ils se vérifient en secondes, sans machine et sans
privilège, avant qu'aucun invité n'existe.

LE CHEMIN EST PLAT SOUS /etc, ET CE N'EST PAS UN GOÛT. Le fichier voyage par
la même voie que les autres fichiers d'accueil, et l'une des deux voies le
recopie avec une commande qui NE CRÉE PAS les répertoires parents et qui
tolère son propre échec. Un chemin à deux niveaux se poserait donc sur une
voie et manquerait en silence sur l'autre.

LA LIGNE DE CHARGEMENT EST LA DERNIÈRE. Le code de sortie d'un script est
celui de sa dernière commande : placée là, et sans « || true », son échec
devient celui du script entier. Ailleurs dans la liste, il se perdrait.

CE N'EST PAS LA MÊME CHOSE QUE D'ÊTRE VU. Un chargement qui échoue se voit
dans l'invité ; l'hôte, lui, n'apprend rien tant qu'il ne RELIT pas. C'est
la sonde qui ferme la boucle, et l'analyseur qui la rend lisible sans
terminal.

LE VERDICT EST UN JETON, PAS UN CODE. Traduire ici en vocabulaire de rapport
ferait descendre la couche menu dans un module qui doit rester lisible sans
elle ; l'appelant fait la correspondance, comme il la fait déjà ailleurs.
"""

from __future__ import annotations

from script.lib_valid import ValidationError
# Le nom de la table interrogée vient du RENDU : écrit deux fois, il
# divergerait, et la sonde chercherait une table que personne ne crée.
from script.posture.rules import TABLE

# Le chemin dans l'invité. Plat sous /etc : le répertoire existe partout, et
# la voie qui recopie ne créerait pas un parent manquant.
RULES_PATH = "/etc/erplibre-egress.nft"

# Root écrit, root lit, root charge. Le fichier nomme les adresses internes
# du site : ce qui n'a pas besoin de les lire n'y accède pas, et quiconque
# peut changer les règles est déjà root.
RULES_MODE = "0600"

# Propriétaire vide : root. Un propriétaire nommé imposerait un report à
# l'étape finale, alors que ce fichier doit être là avant tout le reste.
RULES_OWNER = ""

# L'unité qui RECHARGE les règles à chaque démarrage. Sans elle, seul le
# premier amorçage les charge : une machine redémarrée repart sans règles,
# et la voie de l'installateur — qui n'a pas de première commande du tout —
# ne les chargeait jamais.
UNIT_NAME = "erplibre-egress.service"
UNIT_PATH = f"/etc/systemd/system/{UNIT_NAME}"

# Un fichier d'unité se lit, il ne porte pas de secret.
UNIT_MODE = "0644"

# Le marqueur qui distingue la réponse du bruit. Une sonde qui rend « oui »
# tout court se confondrait avec n'importe quelle ligne de transport.
MARQUEUR = "ERPLIBRE-EGRESS:"

# Ce que la relecture peut conclure, et rien d'autre.
LOADED = "loaded"
TABLE_ABSENT = "table-absent"
TOOL_ABSENT = "tool-absent"
NO_PRIVILEGE = "no-privilege"
UNREAD = "unread"

# Ce que l'INVITÉ peut dire. « non lu » n'en est pas : il décrit le silence,
# et un invité qui le prononce reprendrait une réponse déjà donnée.
SAID_BY_GUEST = (LOADED, TABLE_ABSENT, TOOL_ABSENT, NO_PRIVILEGE)
VERDICTS = SAID_BY_GUEST + (UNREAD,)


def file_entry(content: str) -> tuple:
    """(chemin, mode, contenu, propriétaire) — la forme que la pose attend.

    Refuse un contenu vide : posé, il donnerait un fichier que l'analyseur
    accepte sans rien appliquer, et la machine se lirait comme confinée.
    """
    if not (content or "").strip():
        raise ValidationError(
            "Aucune règle à poser. Un fichier vide se chargerait sans rien"
            " appliquer, et la machine se lirait comme confinée."
        )
    return (RULES_PATH, RULES_MODE, content, RULES_OWNER)


def unit_text() -> str:
    """Le contenu de l'unité. Calqué sur celle de nftables, à la ligne.

    `Wants` et `Before` sur la cible d'avant-réseau : les règles sont en
    place avant que la moindre interface soit configurée, sans quoi il
    existe une fenêtre où la machine sort librement à chaque démarrage.

    L'analyseur est appelé PAR UN SHELL, et non par un chemin absolu :
    systemd exige un chemin absolu pour son premier mot, et le répertoire
    de l'outil diffère selon la distribution. Le shell, lui, est au même
    endroit partout et sait le chercher dans le chemin d'exécution.
    """
    return (
        "\n".join(
            [
                "[Unit]",
                "Description=ERPLibre egress rules",
                "Wants=network-pre.target",
                "Before=network-pre.target",
                "",
                "[Service]",
                "Type=oneshot",
                f"ExecStart=/bin/sh -c 'exec nft -f {RULES_PATH}'",
                "",
                "[Install]",
                "WantedBy=multi-user.target",
            ]
        )
        + "\n"
    )


def unit_entry() -> tuple:
    """(chemin, mode, contenu, propriétaire) pour l'unité."""
    return (UNIT_PATH, UNIT_MODE, unit_text(), "")


def enable_command() -> str:
    """La commande qui arme l'unité pour les démarrages suivants."""
    return f"systemctl enable {UNIT_NAME}"


def first_boot_command() -> str:
    """Ce qu'il faut jouer au PREMIER amorçage, en une seule commande.

    Armer et charger, dans cet ordre et liés : armer sans charger laisse la
    machine sortir jusqu'au premier redémarrage, charger sans armer la
    laisse sortir à partir du deuxième. Liées par « && », les deux doivent
    réussir, et le code de sortie de l'ensemble est celui de la ligne — ce
    qui n'est vrai que si elle est la DERNIÈRE de sa liste.
    """
    return f"{enable_command()} && {load_command()}"


def load_command() -> str:
    """La commande qui charge le fichier, à placer EN DERNIER.

    Une seule commande, sans repli. « nft » absent rend « command not
    found », ce qui dit déjà la panne ; un « || true » la masquerait, et le
    déploiement continuerait en annonçant un confinement que rien ne tient.
    """
    return f"nft -f {RULES_PATH}"


def provision_script(rules: str) -> str:
    """Le shell qui POSE les deux fichiers et arme, pour un backend qui
    provisionne par script. Vide si les règles le sont.

    Une redirection shell ne prend pas de mode : c'est le masque qui le
    décide, et poser 0600 par un chmod APRÈS laisserait le fichier lisible
    le temps de son écriture — or il porte les adresses du site.

    Composé ICI et non chez l'appelant : les chemins, les modes, le texte
    de l'unité et l'ordre des deux commandes vivent dans ce module, et un
    backend qui les recopierait divergerait du jour où ils changent.
    """
    if not (rules or "").strip():
        return ""
    masque = f"{0o666 ^ int(RULES_MODE, 8):04o}"
    lignes = [
        "#!/bin/sh",
        "set -eu",
        f"umask {masque}",
        f"cat > {RULES_PATH} <<'ERPLIBRE_NFT'",
    ]
    lignes += rules.rstrip("\n").splitlines()
    lignes += [
        "ERPLIBRE_NFT",
        f"cat > {UNIT_PATH} <<'ERPLIBRE_UNIT'",
    ]
    lignes += unit_text().rstrip("\n").splitlines()
    lignes += [
        "ERPLIBRE_UNIT",
        f"chmod {UNIT_MODE} {UNIT_PATH}",
        first_boot_command(),
    ]
    return "\n".join(lignes) + "\n"


def probe_command() -> str:
    """Ce qu'on demande à l'invité pour savoir si les règles ont pris.

    Rend TOUJOURS 0 et répond par un mot : selon la version de l'outil, le
    code de sortie ne distingue pas « pas d'outil » de « pas de table », et
    l'un s'installe quand l'autre se recharge.

    L'élévation est demandée sans invite : lire une table est réservé, et un
    sudo qui attend un mot de passe bloquerait la sonde sur une question que
    personne ne voit.
    """
    lecture = f"sudo -n nft list table inet {TABLE}"
    return (
        f"command -v nft >/dev/null 2>&1 || {{ echo {MARQUEUR}{TOOL_ABSENT};"
        " exit 0; }; "
        f"sudo -n true 2>/dev/null || {{ echo {MARQUEUR}{NO_PRIVILEGE};"
        " exit 0; }; "
        f"{lecture} >/dev/null 2>&1"
        f" && echo {MARQUEUR}{LOADED}"
        f" || echo {MARQUEUR}{TABLE_ABSENT}"
    )


def parse_probe(output: str) -> str:
    """Le verdict lu dans la sortie de la sonde.

    Ce qui n'a pas été lu vaut « non lu », et surtout pas « chargé » : une
    sonde muette annoncée comme un succès est le mensonge que cette relecture
    existe pour empêcher.

    La DERNIÈRE réponse gagne : le transport peut préfixer ses propres
    lignes, et un invité bavard en écrire avant.
    """
    verdict = UNREAD
    for ligne in (output or "").splitlines():
        nu = ligne.strip()
        if not nu.startswith(MARQUEUR):
            continue
        dit = nu[len(MARQUEUR) :].strip()
        if dit in SAID_BY_GUEST:
            verdict = dit
    return verdict
