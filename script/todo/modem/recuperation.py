#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Jouer une recette de messagerie vocale depuis la TUI.

Le service `erplibre-sip-go` compose, ecoute et tape les touches ; ce module
prepare ce qu'il lui faut et relit ce qu'il rend :

- le numero de la messagerie, lu sur la SIM ;
- le code, sorti du coffre au dernier moment et passe par l'ENTREE STANDARD —
  jamais sur la ligne de commande, que tout programme de la machine peut
  lire ;
- un fichier WAV date sous `private/`, avec le bilan a cote.

Les recettes vivent dans `recettes/` et ne contiennent pas le code : elles
portent a la place la marque `{code}`.
"""
from __future__ import annotations

import datetime
import json
import os
import shlex
import subprocess
import wave

#: Ou vont les enregistrements de la messagerie de l'operateur.
DOSSIER_RELATIF = "private/repondeur/operateur"

#: Ou vont les messages extraits de ces enregistrements.
DOSSIER_MESSAGES_RELATIF = "private/repondeur/operateur/messages"

#: Seuil de parole, le meme que le service (`SeuilÉcho`).
SEUIL_PAROLE = 600

#: Marge au-dela de la duree maximale d'une recette, pour composer et
#: raccrocher, avant d'abandonner le processus.
MARGE_S = 60


def racine() -> str:
    return os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def chemin_recette(nom: str) -> str:
    return os.path.join(os.path.dirname(__file__), "recettes", nom + ".json")


#: Au-dela de ce silence apres le « 1 », c'est le menu qui se repete : il
#: separe la fin du message de la suite. Mesure sur une messagerie reelle :
#: 1,2 s entre annonce et message, 1,8 s entre message et menu, 5,5 s entre
#: deux menus.
SILENCE_MENU_MS = 4000

#: Respiration fondue dans une meme plage, pour la decoupe. Mesure sur une
#: messagerie reelle : 0,8 s separent l'annonce du message. Fondre au-dela
#: collerait les deux, et il n'y aurait plus de quoi les distinguer.
PONT_DECOUPE_MS = 600

#: Ce qui commence moins de ce delai apres la touche est la fin de la phrase
#: en cours, et non la reponse a la touche.
REPRISE_APRES_TOUCHE_MS = 300

#: Marge gardee de part et d'autre du message extrait.
MARGE_DECOUPE_MS = 300

#: Ajustements des deux bornes, regles a l'oreille sur une messagerie reelle.
#: Le debut est repousse d'une seconde : la fin de l'annonce du numero, qui
#: precede le message, n'est plus dans l'extrait. La fin est avancee d'une
#: demi-seconde, avant que le menu ne commence.
AJUSTEMENT_DEBUT_MS = 1000
AJUSTEMENT_FIN_MS = -500

#: Debit du WAV enregistre par le service : 8 kHz, 16 bits, mono.
OCTETS_PAR_SECONDE = 16000


def duree_max_s(recette: dict) -> int:
    """La duree la plus longue que la recette peut tenir la ligne."""
    total = 0
    for etape in recette.get("etapes", []):
        if "attendre_silence" in etape:
            total += int(etape["attendre_silence"].get("max_s", 0))
        elif "enregistrer" in etape:
            total += int(etape["enregistrer"].get("max_s", 0))
        elif "pause_ms" in etape:
            total += int(etape["pause_ms"]) // 1000 + 1
    return total


def charger_recette(nom: str) -> dict:
    with open(chemin_recette(nom), encoding="utf-8") as flux:
        return json.load(flux)


def silence_avant_effacement_s(recette: dict):
    """Le silence qui declenche le 7, en secondes, ou None sans effacement.

    Lu dans la recette plutot que recopie dans un message : l'avertissement
    montre a l'utilisateur doit dire la valeur qui s'appliquera vraiment.
    """
    etapes = recette.get("etapes", [])
    for i, etape in enumerate(etapes):
        if "7" not in etape.get("touches", ""):
            continue
        for precedente in reversed(etapes[:i]):
            if "attendre_silence" in precedente:
                return precedente["attendre_silence"]["silence_ms"] / 1000
    return None


def demande_code(recette: dict) -> bool:
    return any("{code}" in e.get("touches", "") for e in recette.get("etapes", []))


def segments(courbe, pont_ms=500, pas_ms=100):
    """Plages de parole de la courbe, respirations courtes fondues."""
    trouves = []
    for i, niveau in enumerate(courbe or []):
        if niveau <= SEUIL_PAROLE:
            continue
        t = i * pas_ms
        if trouves and t - trouves[-1][1] <= pont_ms:
            trouves[-1][1] = t + pas_ms
        else:
            trouves.append([t, t + pas_ms])
    return trouves


def jouer(nom_recette, numero, code, binaire, port, executer=None, maintenant=None):
    """Joue la recette et rend (bilan, chemin_wav).

    `executer(commande, entree, timeout)` rend (code_sortie, stdout, stderr) ;
    il est injectable pour que la logique se verifie sans modem.
    """
    with open(chemin_recette(nom_recette), encoding="utf-8") as flux:
        recette = json.load(flux)
    if demande_code(recette) and not code:
        return {"erreur": "cette recette compose le code, et il n'est pas defini"}, ""

    dossier = os.path.join(racine(), DOSSIER_RELATIF)
    os.makedirs(dossier, mode=0o700, exist_ok=True)
    horodatage = (maintenant or datetime.datetime.now()).strftime("%Y%m%d-%H%M%S")
    wav = os.path.join(dossier, "%s-%s.wav" % (nom_recette, horodatage))

    commande = " ".join(shlex.quote(p) for p in (
        binaire, "-port", port, "-numero", numero,
        "-recette", chemin_recette(nom_recette), "-enregistrer", wav, "-v"))
    executer = executer or _executer
    entree = (code + "\n") if demande_code(recette) else ""
    sortie, stdout, stderr = executer(
        ["sg", "dialout", "-c", commande], entree, duree_max_s(recette) + MARGE_S)
    try:
        bilan = json.loads(stdout)
    except ValueError:
        derniere = (stderr or stdout or "").strip().splitlines()[-1:] or [""]
        bilan = {"erreur": "sortie illisible (code %s) : %s" % (sortie, derniere[0][:120])}
    return bilan, wav


def _executer(commande, entree, timeout):
    try:
        fait = subprocess.run(commande, input=entree, capture_output=True,
                              text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 1, "", "delai depasse"
    return fait.returncode, fait.stdout, fait.stderr


def resume(bilan: dict) -> list:
    """Lignes a afficher : issue, duree, touches, plages de parole."""
    lignes = []
    if bilan.get("erreur"):
        lignes.append("arret : " + bilan["erreur"])
    lignes.append("duree : %.1f s" % (bilan.get("duree_ms", 0) / 1000))
    for evenement in bilan.get("evenements", []):
        lignes.append("  %6.1f s  %s" % (evenement["ms"] / 1000, evenement["quoi"]))
    plages = segments(bilan.get("courbe_crete_100ms"))
    if plages:
        lignes.append("parole :")
        for debut, fin in plages:
            lignes.append("  %6.1f -> %6.1f s" % (debut / 1000, fin / 1000))
    return lignes


def instant_touche(bilan: dict, touche: str):
    """Le moment ou une touche precise est partie, ou None."""
    marque = "touches " + touche
    for evenement in bilan.get("evenements", []):
        if evenement["quoi"].endswith(marque):
            return evenement["ms"]
    return None


def depart_ms(index: int, pas: int) -> int:
    """Le decalage, en millisecondes, d'un index de courbe."""
    return index * pas


def bornes_du_message(bilan: dict):
    """Rend (debut_ms, fin_ms) du message dans l'enregistrement, ou None.

    La messagerie joue, apres le « 1 » : une annonce (date, numero de
    l'appelant), le message, puis un menu qui se repete apres un long silence.
    Le message est donc ce qui separe la FIN de l'annonce du DEBUT du menu —
    le menu etant la plage qui precede le premier long silence. Une structure
    qui ne correspond pas rend None : mieux vaut garder l'enregistrement
    complet que decouper au hasard.
    """
    depart = instant_touche(bilan, "1")
    if depart is None:
        return None
    pas = 100
    courbe = bilan.get("courbe_crete_100ms") or []
    # La decoupe ne regarde QUE ce qui suit la touche : filtrer les plages
    # apres coup ne suffit pas, car une plage commencee avant la touche
    # absorbe celles d'apres et disparait du meme geste — l'annonce et le
    # message se retrouvaient alors dans ce qui precede.
    debut_index = depart // pas
    plages = [[a + depart_ms(debut_index, pas), z + depart_ms(debut_index, pas)]
              for a, z in segments(courbe[debut_index:], pont_ms=PONT_DECOUPE_MS,
                                   pas_ms=pas)]
    # La touche part souvent PENDANT que la messagerie parle : ce qui reste de
    # cette phrase n'est pas l'annonce du message, c'est la fin de la
    # precedente. On ne garde que ce qui commence apres un vrai silence.
    plages = [p for p in plages if p[0] >= depart + REPRISE_APRES_TOUCHE_MS]
    menu = None
    for i, (debut, fin) in enumerate(plages):
        suivant = plages[i + 1][0] if i + 1 < len(plages) else len(courbe) * pas
        if suivant - fin >= SILENCE_MENU_MS:
            menu = i
            break
    if menu is None or menu < 2:
        return None
    annonce_fin = plages[0][1]
    menu_debut = plages[menu][0]
    debut = max(0, annonce_fin - MARGE_DECOUPE_MS + AJUSTEMENT_DEBUT_MS)
    fin = menu_debut + MARGE_DECOUPE_MS + AJUSTEMENT_FIN_MS
    return (debut, fin) if fin > debut else None


def extraire_message(wav: str, bilan: dict, dossier: str, maintenant=None):
    """Ecrit le seul message dans son propre fichier, avec sa description.

    Rend le chemin ecrit, ou "" quand la structure n'a pas ete reconnue ;
    l'enregistrement complet reste alors la seule copie, et il est garde.
    """
    bornes = bornes_du_message(bilan)
    if not bornes or not os.path.exists(wav):
        return ""
    debut, fin = bornes
    os.makedirs(dossier, mode=0o700, exist_ok=True)
    horodatage = (maintenant or datetime.datetime.now()).strftime("%Y%m%d-%H%M%S")
    sortie = os.path.join(dossier, "message-%s.wav" % horodatage)
    with wave.open(wav, "rb") as source:
        cadres = source.getframerate()
        source.setpos(min(source.getnframes(), debut * cadres // 1000))
        donnees = source.readframes(max(0, (fin - debut) * cadres // 1000))
        with wave.open(sortie, "wb") as cible:
            cible.setparams(source.getparams())
            cible.writeframes(donnees)
    os.chmod(sortie, 0o600)
    with open(os.path.splitext(sortie)[0] + ".json", "w", encoding="utf-8") as flux:
        json.dump({
            "source": "messagerie de l'operateur",
            "recupere_le": (maintenant or datetime.datetime.now()).isoformat(),
            "duree_secondes": round((fin - debut) / 1000, 1),
            "fichier": sortie,
            "enregistrement_complet": wav,
        }, flux, indent=1, ensure_ascii=False)
    return sortie


def dossier_messages() -> str:
    return os.path.join(racine(), DOSSIER_MESSAGES_RELATIF)


def lister_messages(dossier=None) -> list:
    """Les messages recuperes, du plus recent au plus ancien.

    Un WAV sans description est ignore : sans date ni duree, la ligne
    n'apprend rien et l'enregistrement complet reste de toute facon a cote.
    """
    dossier = dossier or dossier_messages()
    try:
        noms = os.listdir(dossier)
    except OSError:
        return []
    messages = []
    for nom in noms:
        if not nom.endswith(".json"):
            continue
        try:
            with open(os.path.join(dossier, nom), encoding="utf-8") as flux:
                message = json.load(flux)
        except (OSError, ValueError):
            continue
        if message.get("fichier"):
            messages.append(message)
    messages.sort(key=lambda m: m.get("recupere_le") or "", reverse=True)
    return messages


def effacer_message(message: dict) -> None:
    """Retire le message extrait ET sa description.

    L'enregistrement COMPLET de l'appel n'est pas touche : c'est la copie de
    secours, celle qui porte aussi l'annonce du numero de l'appelant.
    """
    fichier = message.get("fichier") or ""
    for chemin in (fichier, os.path.splitext(fichier)[0] + ".json"):
        try:
            os.remove(chemin)
        except OSError:
            pass
