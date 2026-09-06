#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Confronter le backend Lima au vrai outil. Il ne l'a JAMAIS été.

Le socle Lima d'ERPLibre a été écrit sans machine pour l'éprouver : ses
épreuves unitaires tiennent ce qu'il COMPOSE et ce qu'il ANALYSE, pas ce que
« limactl » en fait. Le backend se déclare donc non éprouvé, et ce script est
ce qui lèvera la mention — pas une relecture.

QUATRE QUESTIONS, ET AUCUNE NE SE DÉDUIT DU CODE :

1. Sous quelle FORME l'inventaire répond-il ? L'analyseur accepte un objet
   par ligne ET un tableau, parce que la version installée décide. Ce script
   dit laquelle arrive, et le commentaire du code pourra cesser d'hésiter.

2. L'inventaire porte-t-il de quoi PROUVER une identité ? Le nom d'instance
   se réutilise ; sans preuve, la suppression retombe sur la confirmation à
   deux mains. Si un champ naît et meurt avec l'instance, il arme le garde.
   Le script montre les clés brutes plutôt que de deviner.

3. « limactl shell <nom> -- bash -c <suite> » exécute-t-il vraiment une
   SUITE ? Le canal d'exec en dépend : sans « bash -c », une suite arriverait
   comme une liste de mots. C'est une hypothèse, ici elle est jouée.

4. La configuration rendue DÉMARRE-t-elle ? Elle se relit très bien en YAML
   et ce n'est pas la question.

Une réponse à chacune vaut mieux qu'un backend qu'on croit bon.

  ./long_test/lima_confront.py              # les quatre questions
  ./long_test/lima_confront.py --dry-run    # ce qui serait fait, rien de fait
  ./long_test/lima_confront.py --detruire   # retirer l'instance d'essai
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)

from script.vm import lima  # noqa: E402

# Un nom qui ne ressemble à aucune instance de travail : ce script en crée
# une et la détruit, et se tromper de cible serait le comble ici.
INSTANCE = "erplibre-confront"

# Une image quelconque et légère suffit : on mesure l'OUTIL, pas la distro.
IMAGE = (
    "https://cloud-images.ubuntu.com/releases/24.04/release/"
    "ubuntu-24.04-server-cloudimg-{arch}.img"
)


def jouer(argv, timeout=900):
    """(code, sortie). Ne lève pas : un outil absent est une réponse."""
    try:
        vu = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 255, str(exc)
    return vu.returncode, (vu.stdout or "") + (vu.stderr or "")


def outil_present():
    chemin = shutil.which("limactl")
    if not chemin:
        print("✗ limactl absent : rien à confronter.")
        return False
    _code, version = jouer([chemin, "--version"], timeout=30)
    print(f"  limactl : {chemin}")
    print(f"  version : {version.strip()}")
    return True


def question_1_et_2():
    """La forme de l'inventaire, et ce qu'il porte comme identité."""
    print("\n── 1 et 2 : la forme de l'inventaire, et son identité ──")
    code, sortie = jouer(["limactl", "list", "--json"], timeout=60)
    if code:
        print(f"  ✗ l'inventaire a échoué ({code}) : {sortie.strip()[:200]}")
        return
    brut = sortie.strip()
    if not brut:
        print("  (aucune instance : relancer après la question 4)")
        return
    try:
        charge = json.loads(brut)
        forme = "un TABLEAU" if isinstance(charge, list) else "un OBJET"
        premier = charge[0] if isinstance(charge, list) and charge else charge
    except ValueError:
        forme = "un objet PAR LIGNE"
        premier = json.loads(brut.splitlines()[0])
    print(f"  forme : {forme}")
    print(f"  clés  : {sorted(premier)}")
    print("  → l'analyseur accepte les deux ; ce relevé dit laquelle")
    print("    la version installée produit, et le code peut cesser")
    print("    d'hésiter dans son commentaire.")
    stables = [
        cle
        for cle in premier
        if cle.lower() not in ("name", "status", "arch", "dir", "vmtype")
    ]
    print(f"  candidats à une PREUVE d'identité : {stables or 'aucun'}")
    print("    (un champ qui naît et meurt avec l'instance armerait le")
    print("     garde de suppression ; à défaut, il reste désarmé)")
    lues = lima.parse_instances(brut)
    print(
        f"  ce que l'analyseur d'ERPLibre en tire : {[i.name for i in lues]}"
    )


def question_3():
    """Une SUITE traverse-t-elle le canal d'exec ?"""
    print("\n── 3 : une suite de commandes traverse-t-elle le canal ? ──")
    from script.vm import backend, verbs

    handle = backend.lima_handle(INSTANCE)
    suite = "echo un && echo deux"
    ligne = f"{verbs.exec_prefix(handle)} {json.dumps(suite)}"
    print(f"  {ligne}")
    code, sortie = jouer(["sh", "-c", ligne], timeout=120)
    attendu = "un\ndeux"
    tenu = sortie.strip() == attendu
    print(f"  rendu : {sortie.strip()!r}")
    print(
        f"  {'✓' if tenu else '✗'} la suite s'exécute ENTIÈRE"
        f"{'' if tenu else ' — le canal est faux'}"
    )


def question_4(dry_run):
    """La configuration rendue démarre-t-elle ?"""
    print("\n── 4 : la configuration rendue démarre-t-elle ? ──")
    arch = "arm64" if os.uname().machine in ("arm64", "aarch64") else "amd64"
    macos = os.uname().sysname == "Darwin"
    texte = lima.render_config(IMAGE.format(arch=arch), arch=arch, macos=macos)
    chemin = os.path.join("/tmp", f"{INSTANCE}.yaml")
    print(f"  système : {os.uname().sysname}   arch : {arch}")
    print(f"  fichier : {chemin}")
    print("  ---")
    for ligne in texte.splitlines():
        print(f"  {ligne}")
    print("  ---")
    if dry_run:
        print("  (--dry-run : rien n'est écrit, rien n'est démarré)")
        return
    with open(chemin, "w", encoding="utf-8") as fh:
        fh.write(texte)
    code, sortie = jouer(
        ["limactl", "start", "--name", INSTANCE, "--tty=false", chemin]
    )
    print(f"  {'✓' if code == 0 else '✗'} démarrage : code {code}")
    if code:
        print(f"    {sortie.strip()[-600:]}")


def detruire():
    print(f"── retrait de l'instance « {INSTANCE} » ──")
    for argv in (
        ["limactl", "stop", "-f", INSTANCE],
        ["limactl", "delete", "-f", INSTANCE],
    ):
        code, sortie = jouer(argv, timeout=300)
        print(f"  {' '.join(argv)} -> {code} {sortie.strip()[:120]}")


def main():
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("--dry-run", action="store_true")
    analyseur.add_argument("--detruire", action="store_true")
    args = analyseur.parse_args()
    if not outil_present():
        return 20
    if args.detruire:
        detruire()
        return 0
    question_4(args.dry_run)
    if not args.dry_run:
        question_3()
    question_1_et_2()
    print(
        "\nCes réponses lèvent — ou non — la mention « non éprouvé » du"
        "\nbackend, dans script/vm/backend.py : PROVEN[LIMA]."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
