#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Confronter les règles de sortie à un conteneur vivant. Elles ne l'ont
jamais été.

Le rendu des règles est éprouvé sur ce qu'il COMPOSE, et l'analyseur de
nftables accepte le fichier — vérifié. Rien de cela ne dit que la chaîne
FORWARD attrape ce qu'un conteneur émet. C'est le jeton
« containers-unproven » de `script/posture/rules.py`, et seul ce script peut
le lever.

POURQUOI UN CONTENEUR ET PAS LA MACHINE. Un verrou accroché à la sortie de
l'hôte laisse passer tout ce qu'un conteneur émet : le trafic d'un
conteneur traverse FORWARD et non OUTPUT. Les règles affichent complet
pendant que la donnée sort par la fenêtre, et aucune relecture de fichier ne
le montre — il faut un conteneur qui TENTE une sortie hors liste.

TROIS QUESTIONS, ET AUCUNE NE SE DÉDUIT DU CODE :

1. Une destination NOMMÉE est-elle joignable depuis le conteneur ? Sans ce
   contrôle positif, un jeu de règles qui bloque tout passerait pour bon, et
   il ne confine rien — il coupe.

2. Une destination HORS LISTE est-elle refusée depuis le conteneur ? C'est
   la question qui porte le jeton. Une réponse positive lève « la chaîne
   forward est rendue, jamais confrontée ».

3. Le refus survit-il au DÉMARRAGE du moteur de conteneurs ? Docker et
   podman écrivent leurs propres règles à leur démarrage, et l'ordre des
   tables décide de qui gagne. Poser les nôtres avant lui, puis le
   redémarrer, est le seul moyen de le savoir.

Ce script demande le privilège : charger un jeu de règles et lire une table
en exigent, et « nft -c » — qui ne fait que l'analyse — échoue déjà sans
lui. Il rend 20 là où l'outillage manque, comme les autres épreuves longues.

  ./long_test/egress_confront.py             # les trois questions
  ./long_test/egress_confront.py --dry-run   # ce qui serait fait, rien de fait
  ./long_test/egress_confront.py --detruire  # retirer table et conteneur
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

from script.posture import destinations, registry, rules  # noqa: E402

# Le conteneur d'essai. Un nom qui ne ressemble à rien du parc : ce script
# détruit ce qu'il nomme.
CONTENEUR = "erplibre-egress-confront"

# L'image : la plus petite qui porte de quoi ouvrir une connexion.
IMAGE = "docker.io/library/alpine:3"

# Les deux destinations de l'épreuve, toutes deux dans les plages de
# documentation (RFC 5737) : une NOMMÉE dans la liste, une hors liste. Elles
# ne répondent pas — et c'est sans importance. Ce qui se mesure est la
# différence entre « refusé tout de suite » et « pas de réponse » : la
# première vient des règles, la seconde du réseau.
AUTORISEE = "198.51.100.10"
HORS_LISTE = "203.0.113.10"


# Podman d'abord : il ne demande pas de démon, donc la question 3 s'y
# observe plus simplement.
MOTEURS = ("podman", "docker")


def moteur():
    """Le moteur de conteneurs présent, ou None."""
    for nom in MOTEURS:
        if shutil.which(nom):
            return nom
    return None


def jouer(argv, timeout=120, entree=None):
    try:
        fini = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            input=entree,
        )
    except (OSError, subprocess.SubprocessError) as souci:
        return 255, str(souci)
    return fini.returncode, (fini.stdout or "") + (fini.stderr or "")


def eleve(argv):
    """La même commande, élevée si on n'est pas déjà root."""
    if os.geteuid() == 0:
        return argv
    return ["sudo", "-n"] + argv


def outillage():
    """(moteur, manques) — ce qui est là, et ce qui ne l'est pas."""
    manques = []
    if not shutil.which("nft"):
        manques.append("nft")
    if moteur() is None:
        manques.append("podman ou docker")
    code, _ = jouer(eleve(["true"]), timeout=20)
    if code:
        manques.append("privilège (root, ou sudo sans mot de passe)")
    return moteur(), manques


def regles_de_banc():
    """Le texte des règles de l'épreuve : une seule destination nommée.

    La liste vient du MÊME rendu que le déploiement, pas d'un fichier écrit
    pour l'occasion : une épreuve qui compose ses propres règles ne dit rien
    de celles qui seront posées.
    """
    posture = registry.get_posture("paranoid")
    carnet = {
        nom: [f"{AUTORISEE}/32"] for nom in destinations.symbols_for(posture)
    }
    return rules.render_egress(
        posture, destinations.destinations_for(posture, carnet)
    )


def poser(texte, dry_run):
    """Charge le jeu de règles. Rend True si la table est ensuite là."""
    print("── pose des règles ──")
    print(f"  destination nommée   : {AUTORISEE}")
    print(f"  destination hors liste : {HORS_LISTE}")
    if dry_run:
        print("  [à blanc] le fichier qui serait chargé :")
        for ligne in texte.splitlines():
            print(f"    │ {ligne}")
        return False
    # CE QUI VA ÊTRE COUPÉ, DIT AVANT DE LE COUPER. Ces règles se chargent
    # dans le jeu de l'HÔTE, sans espace de noms, en « policy drop » sur
    # output comme sur forward. La seule destination nommée est une adresse
    # de documentation : la machine perd donc sa sortie entière, et une
    # session ssh tombe avec elle — y compris celle qui lit ces lignes.
    # Le rappel de « --detruire » n'arrivait qu'à la fin, c'est-à-dire sur
    # un terminal qui pouvait déjà ne plus rien afficher.
    print()
    print("  ⚠  Ces règles se chargent sur CETTE machine, pas dans un")
    print("     espace de noms. Sortie coupée sauf la destination nommée,")
    print("     donc une session ssh tombe avec le reste.")
    print("     À défaire : ./long_test/egress_confront.py --detruire")
    print("     Une machine JETABLE est le seul endroit raisonnable.")
    if input("\n  Charger quand même ? (tapez OUI) : ").strip() != "OUI":
        print("  Rien n'a été chargé.")
        return False
    with tempfile.NamedTemporaryFile(
        "w", suffix=".nft", delete=False
    ) as fichier:
        fichier.write(texte)
        chemin = fichier.name
    try:
        code, sortie = jouer(eleve(["nft", "-f", chemin]))
        print(f"  nft -f -> {code} {sortie.strip()[:200]}")
    finally:
        os.unlink(chemin)
    code, sortie = jouer(eleve(["nft", "list", "table", "inet", rules.TABLE]))
    print(f"  table présente -> {code == 0}")
    return code == 0


def depuis_le_conteneur(nom_moteur, adresse, dry_run):
    """(code, sortie) d'une tentative de connexion DEPUIS le conteneur."""
    argv = eleve(
        [
            nom_moteur,
            "run",
            "--rm",
            "--name",
            CONTENEUR,
            IMAGE,
            "timeout",
            "5",
            "nc",
            "-z",
            adresse,
            "443",
        ]
    )
    if dry_run:
        print(f"  [à blanc] {' '.join(argv)}")
        return None, ""
    return jouer(argv, timeout=180)


def question_1_et_2(nom_moteur, dry_run):
    """La destination nommée passe, celle hors liste est refusée."""
    print("\n── 1 et 2 : ce qui passe, ce qui ne passe pas ──")
    for etiquette, adresse in (
        ("nommée", AUTORISEE),
        ("hors liste", HORS_LISTE),
    ):
        code, sortie = depuis_le_conteneur(nom_moteur, adresse, dry_run)
        if code is None:
            continue
        # Ce qui DISTINGUE les deux : un refus par les règles répond tout de
        # suite (« Permission denied » ou « unreachable »), une absence de
        # réponse épuise le délai. Les deux rendent un code non nul, donc le
        # code seul ne tranche pas — c'est le TEXTE qui le fait.
        print(f"  {etiquette:11} -> code {code}")
        print(f"    {sortie.strip()[:300]}")
    print(
        "  À LIRE : la ligne « hors liste » doit porter un refus IMMÉDIAT."
        "\n  Un simple délai épuisé ne prouve rien — les deux adresses sont"
        "\n  des plages de documentation et ne répondent ni l'une ni l'autre."
    )


def question_3(nom_moteur, dry_run):
    """Le refus survit-il au démarrage du moteur de conteneurs ?"""
    print("\n── 3 : après un redémarrage du moteur ──")
    argv = eleve(["systemctl", "restart", f"{nom_moteur}.service"])
    if dry_run:
        print(f"  [à blanc] {' '.join(argv)}")
        return
    code, sortie = jouer(argv, timeout=120)
    print(f"  {' '.join(argv)} -> {code} {sortie.strip()[:200]}")
    code, _ = jouer(eleve(["nft", "list", "table", "inet", rules.TABLE]))
    print(f"  notre table est-elle encore là -> {code == 0}")
    question_1_et_2(nom_moteur, dry_run=False)


def detruire(nom_moteur):
    print(f"── retrait de la table « {rules.TABLE} » et du conteneur ──")
    for argv in (
        [nom_moteur, "rm", "-f", CONTENEUR],
        ["nft", "delete", "table", "inet", rules.TABLE],
    ):
        code, sortie = jouer(eleve(argv), timeout=120)
        print(f"  {' '.join(argv)} -> {code} {sortie.strip()[:120]}")


def main():
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("--dry-run", action="store_true")
    analyseur.add_argument("--detruire", action="store_true")
    args = analyseur.parse_args()

    nom_moteur, manques = outillage()
    if manques and not args.dry_run:
        print("Outillage absent : " + ", ".join(manques))
        print("Rien n'a été tenté.")
        return 20
    if nom_moteur is None:
        # À blanc, l'absence de moteur ne doit pas arrêter l'affichage :
        # c'est justement la station où l'on relit ce qui SERAIT fait.
        nom_moteur = MOTEURS[0]
        print(f"  (aucun moteur installé ; « {nom_moteur} » pour l'exemple)")
    if args.detruire:
        detruire(nom_moteur)
        return 0

    texte = regles_de_banc()
    poser(texte, args.dry_run)
    question_1_et_2(nom_moteur, args.dry_run)
    if not args.dry_run:
        question_3(nom_moteur, args.dry_run)
    print(
        "\nCe que ces réponses lèvent — ou non : le jeton"
        f"\n« {rules.CONTAINERS_UNPROVEN} » de script/posture/rules.py, et"
        "\navec lui le champ covers_containers du registre."
        "\n\nÀ défaire ensuite : --detruire."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
