#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Installer Apertus pour de bon, et vérifier qu'il répond.

Ce que les tests unitaires ne peuvent pas prouver. `test_assistant_apertus.py`
vérifie que les étapes sortent dans le bon ordre et que leurs commandes se
parsent ; il ne lance rien. Or ce qui casse une installation n'est pas la
syntaxe d'une commande : c'est un gestionnaire de paquets qui n'a pas le
moteur, un service qui ne démarre pas, un dépôt de quantification déplacé, un
gabarit de chat qui laisse fuir ses jetons spéciaux. Cela se mesure en
installant.

Le test tourne sur la machine locale par défaut, et sur n'importe quelle
destination ssh par `--hote`. Il ne CRÉE aucune machine : la création de VM a
ses propres tests, et la mêler ici confondrait deux échecs — celui d'un
hyperviseur et celui d'un installateur.

Le modèle par défaut est le Mini 0,5 B, le plus petit téléchargement réel de
la famille. Le but est d'exercer le chemin, pas d'éprouver le lien réseau ;
`--modele 8b-q4` demande le vrai, sciemment.

  ./long_test/apertus_install.py                     # ici, Ollama, Mini 0.5B
  ./long_test/apertus_install.py --dry-run           # le plan, rien de lancé
  ./long_test/apertus_install.py --hote <alias-ssh>  # ailleurs
  ./long_test/apertus_install.py --moteur llamacpp   # un autre moteur
  ./long_test/apertus_install.py --detruire          # défaire ce qui a été posé
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)

from script.todo.assistant import apertus as apt  # noqa: E402

# Délai d'une requête de vérification, en secondes. Un modèle qui vient d'être
# chargé répond lentement au premier appel : le poids monte en mémoire pendant
# que la requête attend.
BUDGET_REPONSE = 180

# DEUX sondes, parce que le test mesure deux choses différentes et qu'une
# seule question les confondrait.
#
# La première éprouve le TUYAU : le moteur écoute, le gabarit de chat est
# appliqué, le modèle répond dans la langue qu'on lui parle. Saluer est la
# seule tâche qu'un modèle de n'importe quelle taille réussit, donc son échec
# accuse l'installation et rien d'autre. C'est elle qui décide du code de
# retour.
SONDE_TUYAU = ("Dis bonjour.", "onjour")

# La seconde éprouve le MODÈLE, et son échec n'est pas celui de l'installation.
# Une variante distillée à 0,5 milliard de paramètres parle un français correct
# et se trompe sur un calcul de deux chiffres : c'est la propriété du modèle,
# pas un défaut du tuyau. Le résultat est rapporté, et ne fait échouer que les
# variantes non distillées.
SONDE_MODELE = (
    "Combien font deux plus deux ? Réponds par un seul chiffre.",
    "4",
)


def lance(commande, montrer=True):
    """Une commande shell, son code et sa sortie fusionnée."""
    if montrer:
        print(f"    $ {commande}")
    proc = subprocess.run(
        commande,
        shell=True,
        capture_output=True,
        text=True,
        errors="replace",
        stdin=subprocess.DEVNULL,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def cible_de(hote):
    """La cible au format qu'attend `apertus.etapes`."""
    if not hote:
        return {
            "kind": "local",
            "destination": "",
            "host": "127.0.0.1",
            "label": "local",
        }
    return {"kind": "ssh", "destination": hote, "host": hote, "label": hote}


def tunnel(hote, port):
    """L'adresse à interroger depuis ici pour joindre le moteur.

    Un moteur distant écoute sur la boucle locale de SA machine : il n'est
    pas joignable d'ici sans redirection. Le test en ouvre une plutôt que de
    demander au moteur d'écouter sur toutes les interfaces, ce qui
    l'exposerait au réseau pour la durée d'un test.
    """
    if not hote:
        return None, f"http://127.0.0.1:{port}"
    proc = subprocess.Popen(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-N",
            "-L",
            f"{port}:127.0.0.1:{port}",
            hote,
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(3)
    return proc, f"http://127.0.0.1:{port}"


def interroge(racine, reference, question):
    """Poser une question au modèle. Rend (ok, texte).

    Température nulle : le test compare une réponse, et un tirage aléatoire
    rendrait l'échec intermittent.
    """
    corps = json.dumps(
        {
            "model": reference,
            "max_tokens": 60,
            "temperature": 0,
            "messages": [{"role": "user", "content": question}],
        }
    ).encode()
    requete = urllib.request.Request(
        f"{racine}/chat/completions",
        data=corps,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(requete, timeout=BUDGET_REPONSE) as rep:
            charge = json.loads(rep.read().decode())
    except (urllib.error.URLError, OSError, ValueError) as souci:
        return False, str(souci)
    try:
        texte = charge["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return False, json.dumps(charge)[:400]
    return True, texte


def jouer(liste, depart=1):
    """Les étapes dans l'ordre, arrêt à la première critique en échec.

    Rend le rang en échec, ou 0. Une étape déjà faite se saute : relancer le
    test après un succès partiel ne retélécharge rien.
    """
    total = len(liste)
    for rang, etape in enumerate(liste, 1):
        if rang < depart:
            continue
        print(f"\n  → {rang}/{total} {etape.cle}")
        if etape.deja_fait:
            fait, _ = lance(etape.deja_fait, montrer=False)
            if fait == 0:
                print("    ⏭ déjà fait")
                continue
        debut = time.time()
        code, sortie = lance(etape.commande)
        ecoule = int(time.time() - debut)
        queue = "\n".join(sortie.strip().splitlines()[-8:])
        if code == 0:
            print(f"    ✅ {ecoule} s")
            continue
        if not etape.critique:
            print(f"    ⚠️  {code}, {ecoule} s — non critique, on poursuit")
            continue
        print(f"    ⛔ code {code}, {ecoule} s")
        print("    " + queue.replace("\n", "\n    "))
        return rang
    return 0


def principal(argv=None):
    vue = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    vue.add_argument("--hote", default="", help="destination ssh ; vide = ici")
    vue.add_argument("--moteur", default="ollama", choices=sorted(apt.MOTEURS))
    vue.add_argument(
        "--modele", default="mini-0.5b", choices=sorted(apt.MODELES)
    )
    vue.add_argument("--dry-run", action="store_true")
    vue.add_argument("--detruire", action="store_true")
    args = vue.parse_args(argv)

    cible = cible_de(args.hote)
    moteur = apt.MOTEURS[args.moteur]
    modele = apt.MODELES[args.modele]
    reference = modele.reference[args.moteur]

    if args.detruire:
        liste = apt.desinstaller(args.moteur, args.modele, cible)
        print(f"🧹 {cible['label']} — {moteur.nom} / {modele.nom}")
        if args.dry_run:
            print(apt.plan_lisible(liste))
            return 0
        jouer(liste)
        print("🧹 défait.")
        return 0

    liste = apt.etapes(args.moteur, args.modele, cible)
    print(f"🇨🇭 {cible['label']} — {moteur.nom} ({moteur.licence})")
    print(f"   {modele.nom} — {modele.taille / 1024 ** 3:.1f} Go")
    print(f"   {reference}")
    print(f"   contexte {apt.contexte_utile(modele)}")
    print()
    print(apt.plan_lisible(liste))
    if args.dry_run:
        return 0

    debut = time.time()
    echec = jouer(liste)
    if echec:
        print(f"\n⛔ arrêté à l'étape {echec}/{len(liste)}.")
        print("   reprise : relancer, les étapes faites se sautent.")
        return 1

    proc, racine = tunnel(args.hote, moteur.port)
    reponses = {}
    try:
        for nom, (question, _) in (
            ("tuyau", SONDE_TUYAU),
            ("modele", SONDE_MODELE),
        ):
            reponses[nom] = interroge(
                f"{racine}{moteur.chemin}", reference, question
            )
    finally:
        if proc:
            proc.terminate()
    ecoule = int(time.time() - debut)
    print()

    ok, texte = reponses["tuyau"]
    if not ok:
        print(f"⛔ le moteur écoute mais ne répond pas : {texte[:300]}")
        return 1
    propre = texte.strip()
    print(f"   {SONDE_TUYAU[0]}")
    print(f"   → {propre[:200]}")
    if "<|" in propre:
        print(
            "⛔ des jetons spéciaux fuient dans la réponse : le gabarit de"
            " chat n'est pas appliqué."
        )
        return 1
    if SONDE_TUYAU[1] not in propre:
        print("⛔ le modèle répond, mais pas à ce qu'on lui demande.")
        return 1

    ok, texte = reponses["modele"]
    juste = ok and SONDE_MODELE[1] in texte.strip()
    print(f"   {SONDE_MODELE[0]}")
    print(f"   → {(texte or '').strip()[:200]}")
    print(
        f"\n✅ le tuyau tient : Apertus répond sur {cible['label']}"
        f" en {ecoule} s."
    )
    if juste:
        return 0
    if modele.distille:
        # La variante distillée se trompe sans que l'installation soit en
        # cause : le tuyau vient d'être prouvé par la sonde précédente.
        print(
            "⚠️  mais ce modèle distillé répond faux à un calcul simple."
            " Prendre le 8B pour des réponses factuelles."
        )
        return 0
    print("⛔ un modèle non distillé devrait répondre juste ici.")
    return 1


if __name__ == "__main__":
    sys.exit(principal())
