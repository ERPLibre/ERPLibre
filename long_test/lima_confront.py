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

# L'instance de la question 5. SÉPARÉE de l'autre : une sortie coupée sur
# l'instance commune ferait relire les réponses 1 à 4 à travers un filtre.
VERROU = "erplibre-confront-verrou"

# La posture éprouvée. « connected » borne des PORTS et n'attend aucune
# adresse : elle rend donc des règles sans qu'un carnet soit nécessaire, ce
# qui garde la question sur le VERROU et non sur sa composition.
POSTURE = "connected"

# Ce qu'on va demander à l'invité, et ce qui prouve chaque réponse.
# Le fichier de règles se lit PAR SUDO : « umask 0066 » le veut illisible
# au compte ordinaire, et une liste d'autorisations lisible de tous
# raconterait ce que la machine a le droit de joindre. Sonder sans sudo
# rendrait donc un vide qui se lit comme « le fichier manque », alors que
# c'est la promesse du provisionnement qui est tenue.
SONDES = (
    (
        "le fichier de règles est là",
        "sudo cat /etc/erplibre-egress.nft",
        "erplibre",
    ),
    (
        "et il n'est lisible que de root",
        "sudo stat -c '%a %U' /etc/erplibre-egress.nft",
        "600 root",
    ),
    (
        "le service est activé",
        "systemctl is-enabled erplibre-egress.service",
        "enabled",
    ),
    (
        "la table est CHARGÉE",
        "sudo nft list table inet erplibre",
        "policy drop",
    ),
    (
        "un port hors liste est refusé",
        "timeout 6 bash -c 'echo > /dev/tcp/192.0.2.1/9999' 2>&1; echo fini",
        "fini",
    ),
)

# Une image quelconque et légère suffit : on mesure l'OUTIL, pas la distro.
IMAGE = (
    "https://cloud-images.ubuntu.com/releases/24.04/release/"
    "ubuntu-24.04-server-cloudimg-{arch}.img"
)


def jouer(argv, timeout=900, separer=False):
    """(code, sortie). Ne lève pas : un outil absent est une réponse.

    L'entrée standard est FERMÉE. Un outil qui pose une question sans
    terminal attend sinon une réponse qui ne viendra jamais, et le relevé
    se fige au lieu de rendre un verdict. Fermée, la question devient une
    fin de fichier — donc un code de retour, donc une réponse.
    """
    try:
        vu = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 255, str(exc)
    if separer:
        return vu.returncode, (vu.stdout or ""), (vu.stderr or "")
    return vu.returncode, (vu.stdout or "") + (vu.stderr or "")


# Les commandes viennent TOUTES de `script.vm.lima`, et aucune n'est écrite
# en littéral ici. Une copie dans ce fichier ferait confronter le script à
# lui-même : il passerait pendant que le code livré porte une autre forme, et
# c'est justement ce que « non éprouvé » veut dire qu'on ne sait pas.
def outil_present():
    chemin = shutil.which(lima.LIMACTL)
    if not chemin:
        print(f"✗ {lima.LIMACTL} absent : rien à confronter.")
        return False
    _code, version = jouer([chemin, "--version"], timeout=30)
    print(f"  {lima.LIMACTL} : {chemin}")
    print(f"  version : {version.strip()}")
    return True


def question_1_et_2():
    """La forme de l'inventaire, et ce qu'il porte comme identité."""
    print("\n── 1 et 2 : la forme de l'inventaire, et son identité ──")
    code, sortie = jouer(lima.list_argv(), timeout=60)
    if code:
        print(f"  ✗ l'inventaire a échoué ({code}) : {sortie.strip()[:200]}")
        return
    brut = sortie.strip()
    # L'inventaire vide n'est pas une sortie VIDE : l'outil écrit un
    # avertissement sur la sortie standard et rend 0. Juger sur « brut est
    # vide » descend alors dans l'analyse de forme avec une ligne qui n'est
    # pas du JSON. C'est l'analyseur du dépôt qui tranche — c'est aussi lui
    # que ce script est là pour confronter.
    lues = lima.parse_instances(brut)
    if not lues:
        print("  (aucune instance : relancer après la question 4)")
        print(f"  ce que l'outil a écrit : {brut[:200] or '(rien)'}")
        return
    premier, forme = _forme_de_linventaire(brut)
    if premier is None:
        print(
            "  ✗ forme illisible, alors que l'analyseur a lu"
            f" {len(lues)} instance(s) : {brut[:200]}"
        )
        return
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
    print(
        f"  ce que l'analyseur d'ERPLibre en tire : {[i.name for i in lues]}"
    )


def _forme_de_linventaire(brut: str):
    """(premier objet, nom de la forme) — (None, "") si rien ne se lit.

    Rend la forme SANS lever : une ligne qui n'est pas du JSON est ce que
    l'outil écrit dans des cas ordinaires, et un relevé qui s'interrompt
    n'apprend rien sur les trois autres questions.
    """
    try:
        charge = json.loads(brut)
    except ValueError:
        for ligne in brut.splitlines():
            try:
                charge = json.loads(ligne.strip())
            except ValueError:
                continue
            if isinstance(charge, dict):
                return charge, "un objet PAR LIGNE"
        return None, ""
    if isinstance(charge, list):
        return (charge[0] if charge else {}), "un TABLEAU"
    if isinstance(charge, dict):
        return charge, "un OBJET"
    return None, ""


def question_3():
    """Une SUITE traverse-t-elle le canal d'exec ?"""
    print("\n── 3 : une suite de commandes traverse-t-elle le canal ? ──")
    from script.vm import backend, verbs

    handle = backend.lima_handle(INSTANCE)
    suite = "echo un && echo deux"
    ligne = f"{verbs.exec_prefix(handle)} {json.dumps(suite)}"
    print(f"  {ligne}")
    # Les flux restent SÉPARÉS. L'outil écrit des avertissements sur la
    # sortie d'erreur — le canal n'en est pas fautif, et les fusionner
    # ferait échouer la comparaison sur du bruit qui n'a pas traversé la
    # VM. C'est la sortie standard, et elle seule, qui dit ce que la suite
    # a produit là-bas.
    code, sortie, bruit = jouer(["sh", "-c", ligne], timeout=120, separer=True)
    attendu = "un\ndeux"
    rendu = sortie.strip()
    print(f"  rendu : {rendu!r}")
    if bruit.strip():
        print(f"  (sortie d'erreur, hors canal : {bruit.strip()[:120]})")
    # « pas la sortie attendue » recouvre DEUX causes opposées : un canal
    # qui découpe la suite, et une instance qui n'est pas là. Les confondre
    # ferait corriger un canal qui n'a rien fait de mal, et la question
    # reviendrait intacte à la première vraie instance.
    if "does not exist" in rendu or "no instance" in rendu.lower():
        print("  — sans objet : l'instance n'existe pas ;")
        print("    la question 4 doit passer d'abord")
        return
    tenu = rendu == attendu
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
    code, sortie = jouer(lima.start_argv(INSTANCE, chemin))
    print(f"  {'✓' if code == 0 else '✗'} démarrage : code {code}")
    if code:
        print(f"    {sortie.strip()[-600:]}")


def question_5(dry_run):
    """Le verrou de posture arrive-t-il DANS l'invité, et y tient-il ?

    C'est la seule pièce du socle qu'aucune épreuve unitaire ne peut
    atteindre : elles tiennent ce que le bloc COMPOSE, pas ce que Lima en
    fait ni ce que l'invité accepte. Trois choses peuvent tomber ici sans
    que le YAML ait le moindre défaut — le bloc littéral mal indenté, un
    invité sans « nft », un service qui s'active sans se charger.

    L'instance est SÉPARÉE : poser une sortie coupée sur celle des autres
    questions ferait relire leurs réponses à travers un filtre.
    """
    print("\n── 5 : le verrou de posture tient-il dans l'invité ? ──")
    import script.posture as posture
    from script.posture import plan as posture_plan
    from script.posture import rules as posture_rules

    p = posture.get_posture(POSTURE)
    regles = posture_rules.render_egress(p, ())
    script_invite = posture_plan.provision_script(regles)
    arch = "arm64" if os.uname().machine in ("arm64", "aarch64") else "amd64"
    texte = lima.render_config(
        IMAGE.format(arch=arch),
        arch=arch,
        macos=os.uname().sysname == "Darwin",
        provision_script=script_invite,
    )
    chemin = os.path.join("/tmp", f"{VERROU}.yaml")
    print(f"  posture : {POSTURE}   instance : {VERROU}")
    if dry_run:
        print("  (--dry-run : rien n'est écrit, rien n'est démarré)")
        return
    with open(chemin, "w", encoding="utf-8") as fh:
        fh.write(texte)
    code, sortie = jouer(lima.start_argv(VERROU, chemin))
    print(f"  {'✓' if code == 0 else '✗'} démarrage : code {code}")
    if code:
        print(f"    {sortie.strip()[-600:]}")
        return

    from script.vm import backend, verbs

    handle = backend.lima_handle(VERROU)
    for libelle, distant, attendu in SONDES:
        ligne = f"{verbs.exec_prefix(handle)} {json.dumps(distant)}"
        _c, vu, _bruit = jouer(["sh", "-c", ligne], timeout=120, separer=True)
        vu = vu.strip()
        tenu = attendu in vu
        print(f"  {'✓' if tenu else '✗'} {libelle} : {vu[:160]!r}")


def detruire():
    """TOUTES les instances que ce script crée.

    Une instance oubliée ici reste sur la machine indéfiniment : rien
    d'autre ne la nomme, et « --detruire » est la seule sortie annoncée.
    Ajouter une question sans ajouter son nom LAISSE une VM derrière.
    """
    for nom in (INSTANCE, VERROU):
        print(f"── retrait de l'instance « {nom} » ──")
        for argv in (lima.stop_argv(nom), lima.delete_argv(nom)):
            code, sortie = jouer(argv, timeout=300)
            print(f"  {lima.display(argv)} -> {code} {sortie.strip()[:120]}")


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
    question_5(args.dry_run)
    print(
        "\nCes réponses lèvent — ou non — la mention « non éprouvé » du"
        "\nbackend, dans script/vm/backend.py : PROVEN[LIMA]."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
