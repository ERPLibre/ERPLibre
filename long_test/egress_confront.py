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
import json
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

# LES DEUX DESTINATIONS RÉPONDENT, et c'est ce qui rend l'épreuve
# concluante. Deux adresses qui ne répondent jamais rendent le même verdict
# — un délai épuisé — qu'elles soient nommées ou non : on ne mesure alors
# que le silence du réseau. Ici deux conteneurs ÉCOUTENT, à un adressage
# près identiques, et la seule variable est la règle.
#
# Ces adresses vivent dans le réseau podman d'une instance jetable et
# meurent avec elle. Elles ne désignent aucune machine du parc.
RESEAU_TEMOIN = "10.89.0.0/24"
AUTORISEE = "10.89.0.9"
HORS_LISTE = "10.89.0.10"

# Les deux écouteurs, et le réseau qui les porte. Le SONDEUR reste sur le
# réseau par défaut : c'est ce qui fait traverser FORWARD à son trafic, et
# FORWARD est exactement la chaîne qu'un verrou d'hôte laisse ouverte quand
# il ne garde que OUTPUT.
TEMOIN = "erplibre-egress-temoin"
ECOUTEURS = (("ecouteur-nomme", AUTORISEE), ("ecouteur-hors", HORS_LISTE))


# Podman d'abord : il ne demande pas de démon, donc la question 3 s'y
# observe plus simplement.
MOTEURS = ("podman", "docker")

# L'instance qui sert de terrain. Un nom qui ne ressemble à rien du parc :
# « --detruire » efface ce qu'il nomme.
INSTANCE = "erplibre-egress-confront"

# L'invité, le même que celui de la confrontation Lima : une seule image à
# tenir à jour, et un système dont on sait qu'il porte apt.
IMAGE_INVITE = (
    "https://cloud-images.ubuntu.com/releases/24.04/release/"
    "ubuntu-24.04-server-cloudimg-{arch}.img"
)


def script_de_terrain(regles: str) -> str:
    """Le provisionnement de l'instance : outillage, image, PUIS règles.

    L'ORDRE EST LA PIÈCE MAÎTRESSE. Une fois la sortie coupée, le registre
    de conteneurs n'est plus joignable : tirer l'image APRÈS l'armement
    échouerait, et la question qu'on vient poser ne pourrait plus se poser.
    Le refus ressemblerait alors à un réseau absent, et l'on conclurait que
    les règles marchent alors qu'on n'aurait rien mesuré.

    C'est aussi ce qui rend l'épreuve honnête : l'image est là AVANT, donc
    un refus mesuré ensuite vient des règles et de rien d'autre.
    """
    from script.posture import plan as posture_plan

    return "\n".join(
        [
            "#!/bin/sh",
            "set -eu",
            "export DEBIAN_FRONTEND=noninteractive",
            "# 1. L'outillage, tant que la sortie est encore libre.",
            "apt-get update -qq",
            "apt-get install -y -qq podman nftables >/dev/null",
            "# 2. L'IMAGE AVANT LES RÈGLES : après, le registre est hors",
            "#    d'atteinte et la question ne peut plus se poser.",
            f"podman pull -q {IMAGE} >/dev/null",
            "# 3. Les règles, par le même rendu que le déploiement.",
            _sans_entete(posture_plan.provision_script(regles)),
        ]
    )


def _sans_entete(script: str) -> str:
    """Le corps d'un script, sans son shebang ni son « set ».

    Le poseur de règles rend un script COMPLET — c'est ce qu'il doit faire
    pour les backends qui l'exécutent seul. Embarqué au milieu d'un autre,
    son en-tête ferait un shebang en commentaire et un « set » redit : rien
    ne casse, mais ce qu'on relit ensuite ne se lit plus.
    """
    lignes = (script or "").splitlines()
    while lignes and (
        lignes[0].startswith("#!") or lignes[0].startswith("set ")
    ):
        lignes.pop(0)
    return "\n".join(lignes)


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


def _arch():
    return "arm64" if os.uname().machine in ("arm64", "aarch64") else "amd64"


def monter_le_terrain(regles, dry_run):
    """Crée l'instance et y pose tout. Rend True si elle est debout.

    UNE MACHINE JETABLE, et c'est la condition de l'épreuve. Ces règles se
    chargent en « policy drop » : posées sur l'hôte, elles coupent la
    session qui les pose et tout ce qui tourne à côté. Le script le disait
    déjà et demandait un OUI ; il fabrique désormais le terrain lui-même.
    """
    from script.vm import lima

    texte = lima.render_config(
        IMAGE_INVITE.format(arch=_arch()),
        arch=_arch(),
        macos=os.uname().sysname == "Darwin",
        provision_script=script_de_terrain(regles),
    )
    chemin = os.path.join(tempfile.gettempdir(), f"{INSTANCE}.yaml")
    print("── le terrain ──")
    print(f"  instance : {INSTANCE}   arch : {_arch()}")
    print(f"  fichier  : {chemin}")
    if dry_run:
        print("  [à blanc] provisionnement qui serait posé :")
        for ligne in script_de_terrain(regles).splitlines():
            print(f"    │ {ligne}")
        return False
    with open(chemin, "w", encoding="utf-8") as fh:
        fh.write(texte)
    code, sortie = jouer(lima.start_argv(INSTANCE, chemin), timeout=1800)
    print(f"  {'✓' if code == 0 else '✗'} démarrage : code {code}")
    if code:
        print(f"    {sortie.strip()[-600:]}")
    return code == 0


def dans_le_terrain(commande, timeout=180):
    """(code, sortie) d'une commande lancée DANS l'instance."""
    from script.vm import backend, verbs

    handle = backend.lima_handle(INSTANCE)
    ligne = f"{verbs.exec_prefix(handle)} {json.dumps(commande)}"
    return jouer(["sh", "-c", ligne], timeout=timeout)


def retirer_le_terrain():
    """L'instance, et rien d'autre. Une instance oubliée reste
    indéfiniment : rien ne la nomme ailleurs."""
    from script.vm import lima

    print(f"── retrait de l'instance « {INSTANCE} » ──")
    for argv in (lima.stop_argv(INSTANCE), lima.delete_argv(INSTANCE)):
        code, sortie = jouer(argv, timeout=300)
        print(f"  {lima.display(argv)} -> {code} {sortie.strip()[:120]}")


def poser_les_temoins():
    """Deux conteneurs qui ÉCOUTENT, sur un réseau à eux. Vrai s'ils y sont.

    Sur un réseau SÉPARÉ de celui du sondeur : container vers container à
    travers deux ponts se route par l'invité, donc par FORWARD. Sur le même
    pont, le trafic ne traverserait que le pont, et l'épreuve ne dirait rien
    de la chaîne qu'elle vient éprouver.

    Rien ici ne demande la sortie : l'image est déjà tirée, et créer un
    réseau local ne sort pas de la machine. C'est pourquoi les témoins se
    posent APRÈS l'armement sans que cela pose de question.
    """
    print("\n── les témoins ──")
    code, _s = dans_le_terrain(
        f"sudo podman network exists {TEMOIN}"
        f" || sudo podman network create --subnet {RESEAU_TEMOIN} {TEMOIN}",
        timeout=120,
    )
    if code:
        return False
    for nom, adresse in ECOUTEURS:
        code, sortie = dans_le_terrain(
            f"sudo podman rm -f {nom} >/dev/null 2>&1;"
            f" sudo podman run -d --name {nom} --network {TEMOIN}"
            f" --ip {adresse} {IMAGE}"
            " sh -c 'while true; do echo ok | nc -l -p 443; done'",
            timeout=180,
        )
        print(f"  {'✓' if code == 0 else '✗'} {nom} sur {adresse}")
        if code:
            print(f"    {sortie.strip()[-200:]}")
            return False
    return True


def sonder(adresse):
    """« PASSE » ou « BLOQUE », vu depuis un conteneur du réseau par défaut.

    Le sondeur est JETABLE et sans nom fixe : un conteneur qui resterait
    d'un tour à l'autre porterait l'état du tour précédent.
    """
    code, _sortie = dans_le_terrain(
        f"sudo podman run --rm {IMAGE} timeout 4 nc -z {adresse} 443",
        timeout=120,
    )
    return "PASSE" if code == 0 else "BLOQUE"


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


# CE QUE RENDENT LES SORTIES, et le vocabulaire est clos. 0 : l'épreuve est
# allée jusqu'au bout. OUTILLAGE : de quoi la mener manque, rien n'a été
# tenté. NON_CONCLUANTE : quelque chose l'a arrêtée AVANT qu'elle mesure —
# un refus de charger les règles, des témoins qui ne répondent pas.
# Confondre 0 et NON_CONCLUANTE ferait lire « concluant » sur une épreuve
# qui n'a rien confronté, et l'épilogue invite à lever un jeton de posture
# sur cette lecture.
SORTIE_OUTILLAGE = 20
SORTIE_NON_CONCLUANTE = 30


def main():
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("--dry-run", action="store_true")
    analyseur.add_argument("--detruire", action="store_true")
    analyseur.add_argument(
        "--terrain",
        choices=("lima", "hote"),
        default="lima",
        help=(
            "où poser les règles. « lima » fabrique une instance jetable ;"
            " « hote » les charge ICI et coupe la sortie de cette machine."
        ),
    )
    args = analyseur.parse_args()

    if args.terrain == "lima":
        return _sur_lima(args)
    return _sur_lhote(args)


def _sur_lima(args):
    """Le terrain jetable : l'instance porte tout, l'hôte ne risque rien."""
    from script.vm import lima

    if not shutil.which(lima.LIMACTL) and not args.dry_run:
        print(f"Outillage absent : {lima.LIMACTL}")
        print("Rien n'a été tenté.")
        return SORTIE_OUTILLAGE
    if args.detruire:
        retirer_le_terrain()
        return 0
    regles = regles_de_banc()
    if not monter_le_terrain(regles, args.dry_run):
        if args.dry_run:
            _epilogue()
        return 0
    if not poser_les_temoins():
        print("  ✗ les témoins ne sont pas debout : rien n'est concluant.")
        return SORTIE_NON_CONCLUANTE
    print("\n── 1 et 2 : ce qui passe, ce qui ne passe pas, DANS l'invité ──")
    verdicts = {}
    for etiquette, adresse in (
        ("nommée", AUTORISEE),
        ("hors liste", HORS_LISTE),
    ):
        verdicts[etiquette] = sonder(adresse)
        print(f"  {etiquette:11} {adresse} -> {verdicts[etiquette]}")
    # LE VERDICT EST UNE DIFFÉRENCE, et il se lit sans interprétation : les
    # deux écouteurs répondent, donc un refus ne peut venir que des règles.
    conclusif = (
        verdicts.get("nommée") == "PASSE"
        and verdicts.get("hors liste") == "BLOQUE"
    )
    print(
        f"  {'✓' if conclusif else '✗'} la chaîne forward attrape ce qu'un"
        " conteneur émet, et laisse passer ce qui est nommé"
    )
    print("\n── 3 : après un redémarrage du moteur, DANS l'invité ──")
    code, sortie = dans_le_terrain("sudo systemctl restart podman.socket")
    print(f"  redémarrage -> {code} {sortie.strip()[:160]}")
    code, _s = dans_le_terrain(
        f"sudo nft list table inet {rules.TABLE} >/dev/null"
    )
    print(f"  notre table est-elle encore là -> {code == 0}")
    _epilogue()
    return 0


def _sur_lhote(args):
    """L'ancien terrain : ICI, et il coupe la sortie de cette machine."""
    nom_moteur, manques = outillage()
    if manques and not args.dry_run:
        print("Outillage absent : " + ", ".join(manques))
        print("Rien n'a été tenté.")
        return SORTIE_OUTILLAGE
    if nom_moteur is None:
        # À blanc, l'absence de moteur ne doit pas arrêter l'affichage :
        # c'est justement la station où l'on relit ce qui SERAIT fait.
        nom_moteur = MOTEURS[0]
        print(f"  (aucun moteur installé ; « {nom_moteur} » pour l'exemple)")
    if args.detruire:
        detruire(nom_moteur)
        return 0

    texte = regles_de_banc()
    # LE REFUS ARRÊTE TOUT. « tapez OUI » n'est pas une formalité : sans
    # règles chargées, les sondes mesurent une machine ordinaire et rendent
    # deux fois « passe ». Cela se lit comme une confrontation concluante
    # alors que rien n'a été confronté — et l'épilogue invite à lever un
    # jeton de posture sur cette lecture.
    #
    # À BLANC, `poser` rend faux par construction : l'affichage EST le but,
    # et la suite continue pour montrer ce qui serait fait.
    if not poser(texte, args.dry_run) and not args.dry_run:
        return SORTIE_NON_CONCLUANTE
    question_1_et_2(nom_moteur, args.dry_run)
    if not args.dry_run:
        question_3(nom_moteur, args.dry_run)
    _epilogue()
    return 0


def _epilogue():
    print(
        "\nCe que ces réponses lèvent — ou non : le jeton"
        f"\n« {rules.CONTAINERS_UNPROVEN} » de script/posture/rules.py, et"
        "\navec lui le champ covers_containers du registre."
        "\n\nÀ défaire ensuite : --detruire."
    )


if __name__ == "__main__":
    sys.exit(main())
