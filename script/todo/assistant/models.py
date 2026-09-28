#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Poser et retirer un modèle sur un serveur reconnu.

Le paquet est en lecture seule partout ailleurs, et `fingerprint` en fait un
invariant : un balayage ne doit pouvoir ni charger un modèle, ni dépenser un
jeton. Ce module est la SEULE exception, et on ne l'atteint que par un choix
explicite du menu. Aucun de ses chemins ne figure dans `probe_plan`, et un
test le vérifie.

**Ce qu'une famille accepte n'est pas ce qu'une autre accepte.** Treize
familles se reconnaissent, et cinq seulement savent poser ET retirer. Deux
savent poser sans savoir retirer — leurs poids vivent dans un répertoire que
le serveur n'expose pas. Six ne savent ni l'un ni l'autre : leur modèle se
choisit au lancement du processus, ou se dépose à la main. `FAMILLES` porte
cette table, et une famille qui n'offre rien le dit avec sa raison plutôt que
de se voir proposer un bouton qui rendra 404.

**La pose est asynchrone chez plusieurs familles.** LocalAI rend un
identifiant de tâche, LM Studio un identifiant de téléchargement, EXO tire
les poids à la création d'une instance. Le module ne guette pas ces tâches :
il rapporte que la pose est LANCÉE, et la liste des modèles dit plus tard si
elle a abouti. Guetter demanderait un sondage par famille, chacun avec son
propre plafond, pour une information que la liste donne déjà.

**Le transport est à part.** `capabilities._http` ne sait pas dire DELETE —
`urllib.request` choisit son verbe sur la seule présence d'un corps — et
plafonne sa lecture à un mégaoctet sous trois secondes, ce qu'un
téléchargement de plusieurs gigaoctets dépasse dès la première seconde. La
pose lit donc un corps NDJSON ligne à ligne, et tout passe par `http.client`,
qui nomme son verbe.

Les pannes sont des CLÉS de traduction, jamais des phrases : le module ne
sait pas dans quelle langue il sera lu.
"""
from __future__ import annotations

import http.client
import json
import ssl
from dataclasses import dataclass
from urllib.parse import quote

from script.todo.assistant import servers as srv

# Le jeton que `Requete` remplace par le nom du modèle, dans le chemin comme
# dans le corps. Une valeur qui ne peut pas apparaître dans un vrai gabarit,
# pour qu'un corps portant littéralement « modele » ne soit pas réécrit.
MODELE = "\x00modele\x00"

# Établir la connexion est court ; télécharger des poids ne l'est pas. Les
# deux budgets sont séparés pour qu'un serveur muet soit vu en secondes sans
# qu'une pose de plusieurs gigaoctets soit coupée en plein vol.
BUDGET_COURT = 10.0
BUDGET_POSE = 3600.0

# Ce qu'une réponse non diffusée a le droit de peser. Elle porte un état, pas
# des poids.
PLAFOND_CORPS = 1 << 20

# Ce qu'une ligne de progression a le droit de peser. Le plafond borne un
# serveur qui en enverrait une sans fin.
PLAFOND_LIGNE = 8192

# Les clés de panne et d'état. Le module nomme, il ne formule pas.
REFUS_FAMILLE = "This server does not offer model management."
REFUS_VIDE = "No model name given."
REFUS_SERVEUR = "The server refused:"
REFUS_MUET = "The server said nothing."
REFUS_JETON = "This server needs a key — set it on the server card."
POSE_LANCEE = "The pull is running at the server."
REFUS_COUPE = "The stream stopped before the end."
POSE_FAITE = "Model posed."
RETRAIT_FAIT = "Model removed."

# Ce qu'une dernière ligne annonce quand la pose est ALLÉE AU BOUT. Ollama
# clôt sur « success » ; un flux qui s'arrête ailleurs s'est arrêté en route,
# et le dire est tout l'intérêt de lire le corps.
FINS = ("success",)

# Pourquoi une famille n'offre rien. Chaque raison dit ce qu'il faut faire à
# la place, parce qu'un refus sans issue se lit comme une panne de l'outil.
SANS_POSE = {
    "jan": "Jan installs its models from its own desktop application.",
    "gpt4all": ("GPT4All serves what its desktop application already loaded."),
    "koboldcpp": (
        "KoboldCpp serves one model chosen when its process started."
    ),
    "textgen_webui": (
        "Text generation web UI downloads its models from its own host."
    ),
    "vllm": "vLLM serves one model chosen when its process started.",
    "openai": "A remote provider serves its own models.",
}

# Pourquoi une famille pose sans savoir retirer. Le retrait s'y fait dans le
# répertoire des modèles, que le serveur n'expose pas.
SANS_RETRAIT = {
    "lmstudio": "LM Studio has no endpoint that deletes weights.",
    "tabbyapi": "TabbyAPI has no endpoint that deletes weights.",
    "exo": ("EXO removes the model card, never the weights it downloaded."),
}


@dataclass(frozen=True)
class Requete:
    """Une requête de gestion : le verbe, le chemin, le corps.

    `chemin` et les valeurs de `corps` peuvent porter `MODELE`, que
    `_remplir` remplace par le nom demandé. Le gabarit est figé ici plutôt
    que construit à l'appel : une famille se relit alors en une ligne, et
    aucune n'a de chemin qu'un test ne voit pas.

    `flux` marque une réponse NDJSON, lue ligne à ligne. `lancee` marque une
    famille qui rend un identifiant de tâche et travaille ensuite seule : le
    succès y veut dire « accepté », jamais « posé ».

    `long` marque une requête qui TÉLÉCHARGE avant de répondre. Elle vaut le
    budget d'une pose même sans diffuser : TabbyAPI tire ses poids puis
    répond, et le budget court la couperait — chez lui, couper la requête
    annule le téléchargement.

    `note` est un fait que le succès ne dit pas de lui-même : chez EXO, le
    retrait ôte la fiche du modèle et laisse les poids sur le disque.
    """

    methode: str
    chemin: str
    corps: dict | None = None
    flux: bool = False
    lancee: bool = False
    long: bool = False
    note: str = ""


@dataclass(frozen=True)
class Famille:
    """Ce qu'une famille de serveurs accepte qu'on fasse à ses modèles.

    `pose` et `retrait` valent None quand la famille n'offre pas le geste ;
    `raison_pose` et `raison_retrait` disent alors POURQUOI, en clé de
    traduction. Une famille qui n'offre rien reste dans la table : son refus
    motivé vaut mieux que son absence, qui se lirait comme un oubli.

    `jeton` vaut "" quand le serveur n'en demande pas, « bearer » quand il en
    accepte un, « admin » quand il l'exige. Une famille « admin » sans clé
    refuse avant d'émettre : présenter la requête pour recevoir 401 apprend
    la même chose en dérangeant le serveur.
    """

    liste: str
    pose: Requete | None = None
    retrait: Requete | None = None
    jeton: str = ""
    raison_pose: str = REFUS_FAMILLE
    raison_retrait: str = REFUS_FAMILLE
    entrees: tuple = ("models", "data")
    champ: str = "name"


# Ce que chaque famille reconnue accepte. Les noms de clés sont ceux que
# `fingerprint.LADDER` attribue, réduits par `_famille` : la table et
# l'échelle se lisent l'une contre l'autre.
#
# Ollama est la seule à diffuser sa progression ; Open WebUI réémet son API
# native sous « /ollama », jeton d'administration en plus. LocalAI ne
# réémet PAS la moitié écrivable de l'API d'Ollama — ni `/api/pull`, ni
# `/api/delete` — et garde ses propres chemins, dont un retrait en POST.
FAMILLES = {
    "ollama": Famille(
        liste="/api/tags",
        pose=Requete("POST", "/api/pull", {"model": MODELE}, flux=True),
        retrait=Requete("DELETE", "/api/delete", {"model": MODELE}),
    ),
    "openwebui": Famille(
        liste="/ollama/api/tags",
        pose=Requete("POST", "/ollama/api/pull", {"model": MODELE}, flux=True),
        retrait=Requete("DELETE", "/ollama/api/delete", {"model": MODELE}),
        jeton="admin",
    ),
    "localai": Famille(
        liste="/v1/models",
        pose=Requete("POST", "/models/apply", {"id": MODELE}, lancee=True),
        retrait=Requete("POST", f"/models/delete/{MODELE}"),
        champ="id",
    ),
    "llamacpp": Famille(
        liste="/models",
        # « lancee » : le routeur valide la fiche, lance un processus fils de
        # téléchargement et répond aussitôt. Annoncer « posé » ferait passer
        # le départ pour l'arrivée.
        pose=Requete("POST", "/models", {"model": MODELE}, lancee=True),
        retrait=Requete("DELETE", f"/models?model={MODELE}"),
        jeton="bearer",
        champ="id",
    ),
    "lmstudio": Famille(
        liste="/api/v1/models",
        pose=Requete(
            "POST",
            "/api/v1/models/download",
            {"model": MODELE},
            lancee=True,
        ),
        jeton="bearer",
        raison_retrait=SANS_RETRAIT["lmstudio"],
        # « key » et non « id » : le catalogue v1 nomme ses modèles ainsi, et
        # « id » n'y existe que sous les instances chargées. Lire « id » rend
        # une liste vide sur un serveur qui porte pourtant des modèles.
        champ="key",
    ),
    "tabbyapi": Famille(
        liste="/v1/model/list",
        # « long » et non « lancee » : le téléchargement est SYNCHRONE, la
        # réponse n'arrive qu'à la fin, et le budget court la couperait —
        # couper la requête annule le téléchargement chez cette famille.
        pose=Requete("POST", "/v1/download", {"repo_id": MODELE}, long=True),
        jeton="admin",
        raison_retrait=SANS_RETRAIT["tabbyapi"],
        champ="id",
    ),
    "exo": Famille(
        liste="/models",
        pose=Requete("POST", "/models/add", {"model_id": MODELE}, lancee=True),
        # Le retrait EXISTE, mais il n'ôte que la fiche : la note le dit sur
        # le succès, là où `raison_retrait` ne se lit que faute de geste.
        retrait=Requete(
            "DELETE", f"/models/custom/{MODELE}", note=SANS_RETRAIT["exo"]
        ),
        champ="id",
    ),
    "jan": Famille(
        liste="/v1/models",
        raison_pose=SANS_POSE["jan"],
        raison_retrait=SANS_POSE["jan"],
        champ="id",
    ),
    "gpt4all": Famille(
        liste="/v1/models",
        raison_pose=SANS_POSE["gpt4all"],
        raison_retrait=SANS_POSE["gpt4all"],
        champ="id",
    ),
    "koboldcpp": Famille(
        liste="/v1/models",
        raison_pose=SANS_POSE["koboldcpp"],
        raison_retrait=SANS_POSE["koboldcpp"],
        champ="id",
    ),
    "textgenwebui": Famille(
        liste="/v1/internal/model/list",
        jeton="admin",
        raison_pose=SANS_POSE["textgen_webui"],
        raison_retrait=SANS_POSE["textgen_webui"],
        champ="id",
    ),
    "vllm": Famille(
        liste="/v1/models",
        raison_pose=SANS_POSE["vllm"],
        raison_retrait=SANS_POSE["vllm"],
        jeton="bearer",
        champ="id",
    ),
    "openai": Famille(
        liste="/v1/models",
        raison_pose=SANS_POSE["openai"],
        raison_retrait=SANS_POSE["openai"],
        jeton="admin",
        champ="id",
    ),
}


@dataclass
class Resultat:
    """Ce qu'une pose ou un retrait a produit.

    `detail` est une clé de traduction, ou une phrase VENUE DU SERVEUR, et
    jamais une phrase d'ici : l'appelant seul sait la langue. `brut` porte ce
    que le serveur a répondu quand il a refusé, pour que le menu puisse le
    montrer sans que le module ait à l'interpréter.

    `note` est une CLÉ, et se traduit ; `brut` n'en est pas une, et ne se
    traduit pas. Les mêler ferait passer une phrase anglaise du serveur par le
    dictionnaire, qui la rendrait inchangée et donnerait l'illusion d'une
    traduction manquante.
    """

    ok: bool
    detail: str
    brut: str = ""
    note: str = ""


def famille(software) -> Famille | None:
    """La table de cette famille, ou None quand elle n'est pas reconnue.

    Un logiciel non reconnu rend la chaîne vide (`fingerprint`) et tombe donc
    à None, ce qui affiche un refus motivé plutôt que de lever sur la table.
    """
    return FAMILLES.get(_famille(software))


def gere(software) -> bool:
    """Vrai quand cette famille accepte qu'on pose ou qu'on retire."""
    table = famille(software)
    return bool(table and (table.pose or table.retrait))


def listing(server, *, jeton="", requete=None) -> list:
    """Les modèles présents, dans l'ordre que le serveur donne. Jamais None.

    Rend une liste vide quand la lecture n'aboutit pas : n'avoir rien lu
    n'est pas une panne du menu, et une famille qui exige une clé répond 401
    à qui n'en présente pas.
    """
    table = famille(server.software)
    if table is None:
        return []
    envoyer = requete if requete is not None else _emettre
    reponse = envoyer(server, "GET", table.liste, None, jeton, False, False)
    if reponse is None or not _abouti(reponse[0]):
        return []
    return _noms(reponse[1], table)


def pose(server, modele, *, jeton="", requete=None, sur_evenement=None):
    """Poser un modèle, en rendant compte pendant le téléchargement.

    Les événements sont des couples opaques, comme ceux de `discover.sweep` :
    ("etat", texte), ("octets", faits, total), ("fini", nom). Le module
    n'imprime rien — c'est le menu qui rend.

    Une interruption ferme le flux et rend un échec plutôt que de laisser une
    socket ouverte. La pose, elle, CONTINUE chez le serveur, et le message le
    dit : couper la lecture n'annule pas un téléchargement déjà lancé.
    """
    return _agir(
        server,
        modele,
        "pose",
        jeton=jeton,
        requete=requete,
        sur_evenement=sur_evenement,
    )


def retrait(server, modele, *, jeton="", requete=None):
    """Retirer un modèle. Le verbe est DELETE là où la famille l'attend, et
    POST là où elle l'attend en POST : LocalAI retire par
    « /models/delete/<nom> », qui n'accepte pas DELETE."""
    return _agir(server, modele, "retrait", jeton=jeton, requete=requete)


def _agir(
    server, modele, geste, *, jeton="", requete=None, sur_evenement=None
):
    """Le tronc commun de la pose et du retrait : refuser, puis émettre.

    Les trois refus se prononcent AVANT d'ouvrir une socket — famille sans
    geste, nom vide, clé exigée et absente. Déranger un serveur pour
    apprendre ce que la table dit déjà n'apprend rien de plus et rend le
    diagnostic plus flou.
    """
    table = famille(server.software)
    if table is None:
        return Resultat(False, REFUS_FAMILLE)
    gabarit = getattr(table, geste)
    if gabarit is None:
        return Resultat(
            False,
            table.raison_pose if geste == "pose" else table.raison_retrait,
        )
    modele = (modele or "").strip()
    if not modele:
        return Resultat(False, REFUS_VIDE)
    if table.jeton == "admin" and not jeton:
        return Resultat(False, REFUS_JETON)
    chemin, corps = _remplir(gabarit, modele)
    envoyer = requete if requete is not None else _emettre
    reponse = envoyer(
        server,
        gabarit.methode,
        chemin,
        corps,
        jeton,
        gabarit.flux,
        gabarit.flux or gabarit.long,
    )
    if reponse is None:
        return Resultat(False, REFUS_MUET)
    statut, charge = reponse
    if not _abouti(statut):
        return Resultat(False, REFUS_SERVEUR, _extrait(charge))
    if gabarit.flux:
        return _suivre(charge, modele, sur_evenement)
    if gabarit.lancee:
        return Resultat(True, POSE_LANCEE, _extrait(charge))
    fait = POSE_FAITE if geste == "pose" else RETRAIT_FAIT
    return Resultat(True, fait, note=gabarit.note)


def _suivre(lignes, modele, sur_evenement):
    """Lire un corps NDJSON jusqu'à sa fin, en rendant compte au passage.

    Ollama termine sur `{"status": "success"}` ; une erreur arrive en
    `{"error": …}` AU MILIEU d'un flux déjà répondu 200, ce qui est la raison
    d'être de cette lecture : le statut HTTP seul déclarerait la pose réussie.

    Une interruption remonte telle quelle après fermeture du flux, pour que
    l'appelant distingue un abandon d'un refus.
    """
    dernier = ""
    try:
        for ligne in lignes:
            etape = _objet(ligne)
            if etape is None:
                continue
            souci = etape.get("error")
            if souci:
                return Resultat(False, REFUS_SERVEUR, str(souci))
            dernier = str(etape.get("status") or dernier)
            _rendre(etape, dernier, sur_evenement)
    except KeyboardInterrupt:
        return Resultat(False, POSE_LANCEE)
    except (OSError, http.client.HTTPException, ValueError) as souci:
        # La socket tombe en plein téléchargement : le corps s'arrête au
        # milieu et la lecture lève. Sans cette branche, l'exception traverse
        # `pose` et remonte jusqu'au menu, qui n'en attend aucune.
        return Resultat(False, REFUS_COUPE, str(souci)[:200])
    finally:
        _fermer(lignes)
    if dernier not in FINS:
        # Un corps qui s'arrête avant l'état final est indiscernable d'un
        # corps complet si l'on ne regarde que la fin de la boucle : c'est le
        # trou que cette fonction existe pour fermer, et le statut HTTP l'a
        # déjà laissé passer une fois.
        return Resultat(False, REFUS_COUPE, dernier)
    if sur_evenement is not None:
        sur_evenement(("fini", modele))
    return Resultat(True, POSE_FAITE)


def _rendre(etape, etat, sur_evenement):
    """Émettre l'événement que cette étape porte, s'il y a un auditeur."""
    if sur_evenement is None:
        return
    fait = etape.get("completed")
    total = etape.get("total")
    if isinstance(fait, int) and isinstance(total, int) and total > 0:
        sur_evenement(("octets", fait, total))
    elif etat:
        sur_evenement(("etat", etat))


def _fermer(lignes):
    """Fermer un flux qui sait se fermer, sans exiger qu'il le sache.

    Un test injecte une simple liste de lignes ; elle n'a pas de `close`, et
    l'exiger ferait du harnais la contrainte plutôt que l'inverse.
    """
    fermer = getattr(lignes, "close", None)
    if callable(fermer):
        try:
            fermer()
        except OSError:
            # La socket était déjà tombée : il n'y avait rien à fermer, et
            # l'échec est déjà décidé par l'appelant.
            pass


def _remplir(gabarit, modele):
    """Le chemin et le corps du gabarit, `MODELE` remplacé par le nom.

    Le nom est encodé pour un chemin quand il y entre : un identifiant de
    dépôt porte une barre oblique, qui découperait le chemin, et une
    étiquette porte un deux-points.
    """
    chemin = gabarit.chemin.replace(MODELE, quote(modele, safe=""))
    if gabarit.corps is None:
        return chemin, None
    corps = {
        cle: (modele if valeur == MODELE else valeur)
        for cle, valeur in gabarit.corps.items()
    }
    return chemin, corps


def _emettre(server, methode, chemin, corps, jeton, flux, long=False):
    """(statut, charge) d'une requête de gestion, ou None si elle n'aboutit
    pas.

    `charge` est un itérateur de lignes quand `flux`, et des octets sinon.
    `http.client` plutôt que `urllib` pour deux raisons : lui seul nomme son
    verbe — `urllib` choisit GET ou POST sur la présence d'un corps, et ne
    peut donc pas dire DELETE — et lui seul rend un objet qu'on lit ligne à
    ligne, là où charger plusieurs gigaoctets en mémoire du menu n'a aucun
    sens.
    """
    entetes = {"Accept": "application/json"}
    charge = None
    if corps is not None:
        charge = json.dumps(corps).encode("utf-8")
        entetes["Content-Type"] = "application/json"
    if jeton:
        entetes["Authorization"] = f"Bearer {jeton}"
    budget = BUDGET_POSE if (flux or long) else BUDGET_COURT
    try:
        lien = _lien(server, budget)
        lien.request(methode, chemin, body=charge, headers=entetes)
        reponse = lien.getresponse()
    except (OSError, http.client.HTTPException, ValueError):
        # Socket refusée, délai dépassé, réponse illisible : la requête n'a
        # rien appris, et l'appelant le dira comme un serveur muet.
        return None
    # Seul un flux ABOUTI garde la connexion ouverte, le générateur la
    # fermant à sa fin. Un flux refusé est lu comme un corps ordinaire :
    # sans cette branche, la connexion d'un 404 resterait ouverte.
    if flux and _abouti(reponse.status):
        return reponse.status, _lignes(reponse, lien)
    try:
        return reponse.status, reponse.read(PLAFOND_CORPS)
    except (OSError, http.client.HTTPException):
        return reponse.status, b""
    finally:
        lien.close()


def _lien(server, budget):
    """La connexion au serveur, TLS sur 443 et en clair partout ailleurs.

    Le schéma se déduit du port comme dans `servers.base_url` : c'est ce
    qu'un serveur de modèle sert par défaut, et une famille derrière un
    mandataire TLS écoute sur 443.
    """
    hote = _hote(server.host)
    if server.port == srv.HTTPS_PORT:
        return http.client.HTTPSConnection(
            hote,
            server.port,
            timeout=budget,
            context=ssl.create_default_context(),
        )
    return http.client.HTTPConnection(hote, server.port, timeout=budget)


def _lignes(reponse, lien):
    """Les lignes d'un corps diffusé, plafonnées, la connexion fermée au bout.

    Le plafond borne une ligne sans fin de retour chariot ; la ligne trop
    longue est coupée et lue telle quelle, parce qu'un JSON tronqué se jette
    plus loin sans bruit.
    """

    def suite():
        try:
            while True:
                ligne = reponse.readline(PLAFOND_LIGNE)
                if not ligne:
                    return
                yield ligne
        finally:
            lien.close()

    flux = suite()
    # Le générateur porte la fermeture ; l'exposer permet à `_fermer` de la
    # déclencher sur interruption sans connaître la connexion.
    return flux


def _hote(host) -> str:
    """L'hôte tel que `http.client` l'attend : nu, sans crochets IPv6.

    `HTTPConnection` met lui-même les crochets dans l'en-tête `Host` ; les
    lui donner déjà posés produirait « [[::1]] ».
    """
    hote = (host or "").strip()
    if hote.startswith("[") and hote.endswith("]"):
        hote = hote[1:-1]
    return hote


def _abouti(statut) -> bool:
    """Vrai pour un statut de succès. 2xx, et rien d'autre."""
    return isinstance(statut, int) and 200 <= statut < 300


def _objet(ligne):
    """Le dictionnaire d'une ligne NDJSON, ou None si ce n'en est pas un.

    Une ligne vide, un fragment coupé par le plafond ou une ligne de
    remplissage se jettent : le flux continue, et une étape manquée ne change
    que l'affichage.
    """
    try:
        valeur = json.loads(ligne)
    except (ValueError, TypeError):
        return None
    return valeur if isinstance(valeur, dict) else None


def _extrait(charge) -> str:
    """Le corps d'un refus, réduit à ce qui tient sur une ligne.

    Le serveur explique souvent en clair ce que le statut ne dit pas. Le
    texte est rendu tel quel, sans traduction : il vient de là-bas.
    """
    if isinstance(charge, bytes):
        charge = charge.decode("utf-8", "replace")
    if not isinstance(charge, str):
        return ""
    texte = " ".join(charge.split())
    objet = _objet(texte)
    if objet is not None:
        for cle in ("error", "message", "detail"):
            valeur = objet.get(cle)
            if isinstance(valeur, str) and valeur:
                texte = valeur
                break
    return texte[:200]


def _noms(charge, table) -> list:
    """Les noms de modèles d'une réponse de liste, dédoublonnés, dans l'ordre.

    Deux enveloppes cohabitent — « models » chez Ollama, « data » chez les
    familles qui suivent OpenAI — et le champ du nom change avec elles. La
    table porte les deux, plutôt qu'une chaîne d'essais qui prendrait le
    premier champ non vide et donnerait un chemin de fichier pour un nom.
    """
    if isinstance(charge, bytes):
        charge = charge.decode("utf-8", "replace")
    objet = _objet(charge)
    if objet is None:
        return []
    noms = []
    for enveloppe in table.entrees:
        entrees = objet.get(enveloppe)
        if not isinstance(entrees, list):
            continue
        for entree in entrees:
            if not isinstance(entree, dict):
                continue
            nom = entree.get(table.champ) or entree.get("name")
            if isinstance(nom, str) and nom and nom not in noms:
                noms.append(nom)
    return noms


def _famille(software) -> str:
    """Le nom d'un logiciel réduit à ses lettres et ses chiffres, en bas de
    casse.

    Même réduction que `servers._family`, et pour la même raison : l'échelle
    nomme « Open WebUI » et « textgen_webui », dont l'espace, le tiret et le
    souligné varient d'une source à l'autre sans changer la famille.
    """
    return "".join(c for c in (software or "").lower() if c.isalnum())
