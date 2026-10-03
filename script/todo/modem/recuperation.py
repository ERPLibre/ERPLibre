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

#: Durees mesurees sur une messagerie reelle, stables d'un appel a l'autre :
#: l'annonce (date et numero de l'appelant) et le menu qui suit le message.
#: Elles servent quand le silence ne separe pas deux parties : l'operateur
#: enchaine parfois sans laisser de blanc mesurable.
DUREE_ANNONCE_MS = 7300
DUREE_MENU_MS = 29900

#: Tolerance autour de ces durees. Au-dela, la plage contient autre chose.
TOLERANCE_DUREE = 0.10

#: Ce qui commence moins de ce delai apres la touche est la fin de la phrase
#: en cours, et non la reponse a la touche.
REPRISE_APRES_TOUCHE_MS = 300

#: Marge gardee de part et d'autre du message extrait.
MARGE_DECOUPE_MS = 300

#: Ce qu'on garde de la fin de l'annonce pour y trouver le numero annonce.
#:
#: La messagerie dit la date puis le numero sans silence entre les deux : la
#: frontiere ne se mesure pas. Trois secondes paraissaient couvrir dix
#: chiffres enonces ; a l'ecoute, elles en amputaient le debut. Sept couvrent
#: l'annonce presque entiere, ce qui emporte la date — et c'est le bon
#: compromis : une date en trop se saute d'une seconde, un chiffre manquant
#: rend le numero inutilisable.
DUREE_NUMERO_MS = 7000

#: Ajustements des deux bornes, regles a l'oreille sur une messagerie reelle.
#: Le debut est repousse d'une seconde : la fin de l'annonce du numero, qui
#: precede le message, n'est plus dans l'extrait. La fin est avancee d'une
#: demi-seconde, avant que le menu ne commence.
AJUSTEMENT_DEBUT_MS = 1000
AJUSTEMENT_FIN_MS = -500

#: Debit du WAV enregistre par le service : 8 kHz, 16 bits, mono.
OCTETS_PAR_SECONDE = 16000

#: Route du module erplibre_repondeur qui recoit un message.
ROUTE_MESSAGE = "/erplibre_repondeur/message"


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


def ligne_occupee(service_actif=None) -> str:
    """Rend la raison de ne pas composer, ou "" quand la voie est libre.

    Une recette ouvre le port AT avec un verrou EXCLUSIF. Le service de voix
    le tient en permanence : lance pendant qu'il tourne, le binaire echoue a
    l'ouverture du modem, donc avant meme de composer, et l'erreur parle d'un
    fichier et non de la cause.
    """
    if service_actif is None:
        from script.todo.modem import service as svc_mod

        if not svc_mod.posee(svc_mod.VOIX):
            return ""
        service_actif = svc_mod.active(svc_mod.VOIX)
    if not service_actif:
        return ""
    return (
        "le service de voix tient le port AT : arretez-le, relevez, puis"
        " relancez-le\n"
        "    sudo systemctl stop erplibre-sip-go\n"
        "    sudo systemctl start erplibre-sip-go"
    )


def jouer(nom_recette, numero, code, binaire, port, executer=None, maintenant=None,
          service_actif=None):
    """Joue la recette et rend (bilan, chemin_wav).

    `executer(commande, entree, timeout)` rend (code_sortie, stdout, stderr) ;
    il est injectable pour que la logique se verifie sans modem.
    """
    occupee = ligne_occupee(service_actif)
    if occupee:
        return {"erreur": occupee}, ""
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
    """Les bornes seules, sans la methode. Voir `bornes_et_methode`."""
    trouve = bornes_et_methode(bilan)
    return (trouve[0], trouve[1]) if trouve else None


def plages_apres_la_touche(bilan: dict):
    """Les plages de parole qui SUIVENT le « 1 », et la courbe. (None, []) sinon.

    La decoupe ne regarde que ce qui suit la touche : filtrer apres coup ne
    suffit pas, car une plage commencee avant elle absorbe celles d'apres et
    disparait du meme geste — l'annonce et le message se retrouvaient alors
    dans ce qui precede.

    La touche part souvent PENDANT que la messagerie parle : ce qui reste de
    cette phrase n'est pas l'annonce, c'est la fin de la precedente. On ne
    garde donc que ce qui commence apres un vrai silence.
    """
    depart = instant_touche(bilan, "1")
    if depart is None:
        return None, []
    pas = 100
    courbe = bilan.get("courbe_crete_100ms") or []
    debut_index = depart // pas
    plages = [[a + depart_ms(debut_index, pas), z + depart_ms(debut_index, pas)]
              for a, z in segments(courbe[debut_index:], pont_ms=PONT_DECOUPE_MS,
                                   pas_ms=pas)]
    return [p for p in plages if p[0] >= depart + REPRISE_APRES_TOUCHE_MS], courbe


def bornes_du_numero(bilan: dict):
    """Rend (debut_ms, fin_ms) du numero annonce, ou None.

    La messagerie enonce la date PUIS le numero de l'appelant, d'une traite :
    aucun silence ne les separe, et il n'y a donc rien a mesurer entre les
    deux. On prend les dernieres secondes de l'annonce, ou le numero se tient
    toujours — ce qui emporte la fin de la date quand l'annonce est courte,
    et c'est preferable a couper un chiffre en deux.
    """
    plages, _courbe = plages_apres_la_touche(bilan)
    if not plages:
        return None
    annonce = plages[0]
    debut = max(annonce[0], annonce[1] - DUREE_NUMERO_MS)
    fin = annonce[1] + MARGE_DECOUPE_MS
    return (debut, fin) if fin > debut else None


def bornes_et_methode(bilan: dict):
    """Rend (debut_ms, fin_ms) du message dans l'enregistrement, ou None.

    La messagerie joue, apres le « 1 » : une annonce (date, numero de
    l'appelant), le message, puis un menu qui se repete apres un long silence.
    Le message est donc ce qui separe la FIN de l'annonce du DEBUT du menu —
    le menu etant la plage qui precede le premier long silence. Une structure
    qui ne correspond pas rend None : mieux vaut garder l'enregistrement
    complet que decouper au hasard.
    """
    plages, courbe = plages_apres_la_touche(bilan)
    if plages is None:
        return None
    pas = 100
    menu = None
    for i, (debut, fin) in enumerate(plages):
        suivant = plages[i + 1][0] if i + 1 < len(plages) else len(courbe) * pas
        if suivant - fin >= SILENCE_MENU_MS:
            menu = i
            break
    if menu is None or menu < 1:
        return None
    if menu >= 2:
        # Le cas franc : l'annonce, le message et le menu sont separes par
        # des silences mesurables.
        annonce_fin, menu_debut, methode = plages[0][1], plages[menu][0], "silence"
    elif _tient_dans(plages[1], DUREE_MENU_MS):
        # L'annonce et le message se sont colles : leur silence commun est
        # plus court que ce qu'on sait mesurer. La duree de l'annonce, stable
        # chez cet operateur, donne la coupure.
        annonce_fin = plages[0][0] + DUREE_ANNONCE_MS
        menu_debut, methode = plages[0][1], "duree de l'annonce"
    else:
        # Le message s'est colle au MENU : c'est la duree du menu, tout aussi
        # stable, qui dit ou le message s'arrete.
        annonce_fin = plages[0][1]
        menu_debut, methode = plages[1][1] - DUREE_MENU_MS, "duree du menu"
    debut = max(0, annonce_fin - MARGE_DECOUPE_MS + AJUSTEMENT_DEBUT_MS)
    fin = menu_debut + MARGE_DECOUPE_MS + AJUSTEMENT_FIN_MS
    return (debut, fin, methode) if fin > debut else None


def _tient_dans(plage, duree_ms):
    """La plage dure-t-elle a peu pres `duree_ms` ?"""
    mesure = plage[1] - plage[0]
    return abs(mesure - duree_ms) <= duree_ms * TOLERANCE_DUREE


def extraire_message(wav: str, bilan: dict, dossier: str, maintenant=None):
    """Ecrit le seul message dans son propre fichier, avec sa description.

    Rend le chemin ecrit, ou "" quand la structure n'a pas ete reconnue ;
    l'enregistrement complet reste alors la seule copie, et il est garde.
    """
    trouve = bornes_et_methode(bilan)
    if not trouve or not os.path.exists(wav):
        return ""
    debut, fin, methode = trouve
    os.makedirs(dossier, mode=0o700, exist_ok=True)
    # Le nom suit l'ENREGISTREMENT et non l'instant de l'extraction : deux
    # relevements traites dans la meme seconde portaient le meme nom, le
    # second ecrasait le premier, et Odoo n'en voyait qu'un — leur reference
    # etant ce nom. Celui de la source est unique par construction.
    sortie = os.path.join(
        dossier, "message-%s.wav" % os.path.splitext(os.path.basename(wav))[0]
    )
    _ecrire_segment(wav, debut, fin, sortie)

    # Le numero annonce part AVEC le message, dans le meme geste : les deux
    # viennent du meme enregistrement et ne servent qu'ensemble — la
    # messagerie ne transmet le numero sous aucune forme lisible, et c'est en
    # ecoutant ces secondes-la qu'on remplit la fiche.
    numero_fichier, numero_duree = "", 0.0
    bornes_numero = bornes_du_numero(bilan)
    if bornes_numero:
        debut_n, fin_n = bornes_numero
        numero_fichier = os.path.join(
            dossier, "numero-%s.wav" % os.path.splitext(os.path.basename(wav))[0]
        )
        _ecrire_segment(wav, debut_n, fin_n, numero_fichier)
        numero_duree = round((fin_n - debut_n) / 1000, 1)
    with open(os.path.splitext(sortie)[0] + ".json", "w", encoding="utf-8") as flux:
        json.dump({
            "source": "messagerie de l'operateur",
            "recupere_le": (maintenant or datetime.datetime.now()).isoformat(),
            "duree_secondes": round((fin - debut) / 1000, 1),
            # Comment les bornes ont ete trouvees : par les silences, ou par
            # une duree connue quand l'operateur n'en laisse pas.
            "decoupe": methode,
            "fichier": sortie,
            # Le numero annonce : son fichier et sa duree, vides quand
            # l'annonce n'a pas ete reconnue. Le message reste utilisable
            # sans lui, et l'inverse n'a pas de sens.
            "numero_fichier": numero_fichier,
            "numero_duree_secondes": numero_duree,
            "enregistrement_complet": wav,
        }, flux, indent=1, ensure_ascii=False)
    return sortie


def _ecrire_segment(source_wav: str, debut_ms: int, fin_ms: int, sortie: str):
    """Recopie une tranche de l'enregistrement dans son propre fichier."""
    with wave.open(source_wav, "rb") as source:
        cadres = source.getframerate()
        source.setpos(min(source.getnframes(), debut_ms * cadres // 1000))
        donnees = source.readframes(max(0, (fin_ms - debut_ms) * cadres // 1000))
        with wave.open(sortie, "wb") as cible:
            cible.setparams(source.getparams())
            cible.writeframes(donnees)
    os.chmod(sortie, 0o600)


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

    Le numero extrait part AVEC le message : il n'a aucun usage seul — on ne
    rappelle pas un numero dont on a jete ce qu'il voulait dire — et le
    laisser remplirait le dossier de fichiers que plus rien ne designe.
    """
    fichier = message.get("fichier") or ""
    numero = message.get("numero_fichier") or ""
    for chemin in (fichier, os.path.splitext(fichier)[0] + ".json",
                   numero):
        if not chemin:
            continue
        try:
            os.remove(chemin)
        except OSError:
            pass


def transport_odoo(ouvrir=None):
    """Le transport signe de l'agent de la passerelle, ou None s'il manque.

    Le meme secret, la meme signature, le meme jeton a usage unique : Odoo
    n'a pas a distinguer qui lui parle, et un second protocole serait un
    second endroit ou se tromper. Rien de configure rend None — une
    installation sans Odoo garde ses messages en local, ce qui suffit.
    """
    import os

    from script.todo.modem import passerelle

    valeurs = [os.environ.get(nom) for nom in
               (passerelle.VARIABLE_URL, passerelle.VARIABLE_SECRET,
                passerelle.VARIABLE_APPAREIL)]
    if not all(valeurs):
        return None
    url, secret, appareil = valeurs
    return passerelle.Transport(url, secret, appareil, ouvrir=ouvrir)


def televerser(message: dict, transport=None) -> tuple:
    """Depose un message de l'operateur dans Odoo. Rend (succes, detail).

    Le numero part VIDE : la boite vocale de l'operateur annonce l'appelant a
    la voix, dans son annonce parlee, et ne le transmet sous aucune forme
    lisible. Y mettre le numero de la messagerie ferait croire que c'est lui
    qui a appele.

    La reference est le nom du fichier : un televersement rejoue apres une
    reponse perdue retrouve le meme message au lieu d'en creer un second.
    """
    import base64
    import os

    transport = transport or transport_odoo()
    if transport is None:
        return False, "Odoo n'est pas configure pour cette machine"
    chemin_son = message.get("fichier") or ""
    try:
        with open(chemin_son, "rb") as flux:
            son = base64.b64encode(flux.read()).decode("ascii")
    except OSError as exc:
        return False, str(exc)
    charge = {
        "source": "operateur",
        "numero": "",
        "recu_le": _horodatage_odoo(message.get("recupere_le")),
        # Arrondie et non tronquee : un message de 1,9 s affiche « 1 s »
        # laisserait croire a un enregistrement rate.
        "duree_secondes": round(float(message.get("duree_secondes") or 0)),
        "nom_fichier": os.path.basename(chemin_son),
        "audio_b64": son,
        "reference": "operateur-" + os.path.basename(chemin_son),
    }
    # Le numero annonce voyage AVEC le message, dans la meme charge : deux
    # envois qui peuvent reussir separement laisseraient une fiche portant
    # l'un sans l'autre, et c'est precisement ensemble qu'ils servent.
    numero_son = message.get("numero_fichier") or ""
    if numero_son:
        try:
            with open(numero_son, "rb") as flux:
                charge["numero_audio_b64"] = base64.b64encode(
                    flux.read()).decode("ascii")
            charge["numero_nom_fichier"] = os.path.basename(numero_son)
            charge["numero_duree_secondes"] = round(
                float(message.get("numero_duree_secondes") or 0))
        except OSError:
            # Le message monte quand meme : mieux vaut une fiche sans
            # l'annonce du numero qu'aucune fiche du tout.
            charge.pop("numero_audio_b64", None)
            charge.pop("numero_nom_fichier", None)
    try:
        reponse = transport.poster(ROUTE_MESSAGE, charge)
    except Exception as exc:
        return False, str(exc)
    return True, str(reponse.get("id") or "")


def _horodatage_odoo(iso: str) -> str:
    """Odoo stocke en UTC sans fuseau ; un horodatage local y serait lu comme
    de l'UTC, et le message s'afficherait decale de plusieurs heures."""
    try:
        instant = datetime.datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        instant = datetime.datetime.now()
    if instant.tzinfo is None:
        instant = instant.astimezone()
    return instant.astimezone(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def marquer_televerse(message: dict, identifiant: str) -> None:
    """Note dans la description que le message est monte dans Odoo.

    Note APRES la reponse, jamais avant : une reponse perdue fait reessayer,
    et la reference evite le doublon. L'inverse perdrait le message pour Odoo.
    """
    compagnon = os.path.splitext(message.get("fichier") or "")[0] + ".json"
    try:
        with open(compagnon, encoding="utf-8") as flux:
            contenu = json.load(flux)
    except (OSError, ValueError):
        return
    contenu["televerse_odoo"] = identifiant or True
    with open(compagnon, "w", encoding="utf-8") as flux:
        json.dump(contenu, flux, indent=1, ensure_ascii=False)


#: Marque posee par le service a cote d'un enregistrement qu'il vient de
#: deposer. Le menu n'en pose pas : ce qu'il releve, il le traite lui-meme, et
#: sans cette distinction les deux chemins creeraient deux fiches du meme
#: message.
MARQUE_A_TRAITER = ".a_traiter"

#: Marque qui remplace la precedente, une fois le depot traite. Elle porte ce
#: qui s'est passe : un depot qui echoue ne doit pas etre rejoue en boucle,
#: et il faut pouvoir dire pourquoi sans relire tout le journal.
MARQUE_FAITE = ".fait"


def depots_a_traiter(dossier=None) -> list:
    """Les enregistrements que le service a deposes et pas encore traites.

    La marque est ecrite EN DERNIER par le service, apres le son et le bilan :
    sa presence dit que les deux sont complets, ce qu'un simple `*.wav` ne
    dirait pas d'un relevement encore en cours.
    """
    dossier = dossier or os.path.join(racine(), DOSSIER_RELATIF)
    if not os.path.isdir(dossier):
        return []
    trouves = []
    for nom in sorted(os.listdir(dossier)):
        if not nom.endswith(MARQUE_A_TRAITER):
            continue
        wav = os.path.join(dossier, nom[: -len(MARQUE_A_TRAITER)])
        if os.path.exists(wav) and os.path.exists(compagnon_du_son(wav)):
            trouves.append(wav)
    return trouves


def compagnon_du_son(wav: str) -> str:
    """Le bilan ecrit a cote d'un enregistrement."""
    return os.path.splitext(wav)[0] + ".json"


def _marquer_fait(wav: str, detail: str) -> None:
    try:
        os.replace(wav + MARQUE_A_TRAITER, wav + MARQUE_FAITE)
        with open(wav + MARQUE_FAITE, "w", encoding="utf-8") as flux:
            flux.write(detail + "\n")
    except OSError:
        pass


def traiter_un_depot(wav: str, maintenant=None, transport=None) -> tuple:
    """Decoupe et televerse UN depot du service. Rend (succes, detail).

    Le decoupage est celui du menu, et c'est voulu : une seconde version,
    reglee ailleurs, finirait par couper autrement le meme enregistrement.
    """
    try:
        with open(compagnon_du_son(wav), encoding="utf-8") as flux:
            bilan = json.load(flux)
    except (OSError, ValueError) as exc:
        _marquer_fait(wav, "bilan illisible : %s" % exc)
        return False, "bilan illisible : %s" % exc

    message = extraire_message(
        wav, bilan, os.path.join(racine(), DOSSIER_MESSAGES_RELATIF),
        maintenant=maintenant,
    )
    if not message:
        # L'enregistrement COMPLET reste : il porte le message, meme mal
        # borne, et le jeter perdrait ce qu'on n'a pas su couper.
        _marquer_fait(wav, "structure non reconnue : enregistrement garde")
        return False, "structure non reconnue"

    for recupere in lister_messages():
        if recupere.get("fichier") != message:
            continue
        monte, detail = televerser(recupere, transport)
        if monte:
            marquer_televerse(recupere, detail)
            _marquer_fait(wav, "televerse : %s" % detail)
            return True, detail
        # NON marque : un Odoo absent se repare tout seul, et le depot
        # repartira au prochain tour.
        return False, detail
    _marquer_fait(wav, "message extrait introuvable dans la liste")
    return False, "message extrait introuvable"


def ramasser_les_depots(dossier=None, maintenant=None, transport=None) -> list:
    """Traite tout ce que le service a depose. Rend un compte rendu par depot."""
    comptes = []
    for wav in depots_a_traiter(dossier):
        ok, detail = traiter_un_depot(wav, maintenant, transport)
        comptes.append({"fichier": os.path.basename(wav), "ok": ok,
                        "detail": detail})
    return comptes
