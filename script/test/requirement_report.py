#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Pousse le verdict de chaque test unitaire vers le registre des requis.

Le registre est une base Odoo où le module `erplibre_devops_requirement`
liste, pour chaque requis, les tests qui le prouvent. Une preuve faite par
un test unitaire d'ERPLibre est une ligne de sorte `repo_unittest` dont la
référence se lit `erplibre:test/<fichier>::<Classe>::<méthode>`, le chemin
étant relatif à la racine du dépôt. Ce module calcule cette référence pour
chaque test noté par unit_file.py, puis écrit le verdict par
`devops.requirement.test.record_result_by_reference`, en JSON-RPC.

La configuration vient de l'environnement, les quatre variables ou aucune :

    ERPLIBRE_REQUIREMENT_URL    racine HTTPS de l'instance Odoo
    ERPLIBRE_REQUIREMENT_DB     sa base
    ERPLIBRE_REQUIREMENT_LOGIN  un utilisateur du groupe des lanceurs
    ERPLIBRE_REQUIREMENT_KEY    sa clé d'API

Aucune définie : `depuis_environnement` rend None sans rien écrire, et le
lanceur se comporte comme sans ce module — aucune connexion, même sortie,
même code. En partie définies : une ligne d'avertissement, aucun envoi.
HTTP sans chiffrement n'est accepté que vers une adresse de bouclage (un
tunnel SSH vers l'instance) : ailleurs, la clé passerait en clair.

Seules les références que le registre déclare partent : une lecture des
lignes `repo_unittest` du dépôt, puis un appel par référence déclarée qui a
un verdict. Un test qu'aucun requis ne cite ne coûte aucun appel et ne
laisse aucun avertissement dans le journal du serveur.

L'envoi s'arrête au premier échec — serveur injoignable, identifiants
refusés, droit manquant, Ctrl+C — et le dit en UNE ligne ; il ne lève
jamais, et le code de sortie de la suite n'en dépend pas. La clé n'est jamais affichée :
tout message lisible passe par `Registre._masquer`.

Le journal d'un verdict, lisible par tout utilisateur interne du registre,
passe par `Registre._neutraliser` avant de partir : la clé y est masquée,
les chemins sous la racine du dépôt deviennent relatifs et le répertoire
personnel devient « ~ ». Les variables elles-mêmes ne sont pas transmises
aux tests (run_unit_test.py les retire de leur environnement).
"""

import ipaddress
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import namedtuple

JAUNE = "\033[0;33m"
FIN = "\033[0m"

VARIABLES = (
    "ERPLIBRE_REQUIREMENT_URL",
    "ERPLIBRE_REQUIREMENT_DB",
    "ERPLIBRE_REQUIREMENT_LOGIN",
    "ERPLIBRE_REQUIREMENT_KEY",
)

DEPOT = "erplibre"
SORTE = "repo_unittest"
MODELE = "devops.requirement.test"

# La racine du dépôt : script/test/ est deux niveaux sous elle.
RACINE = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

# L'issue notée par unit_file.py → la valeur de `last_result` du registre.
RESULTATS = {
    "ok": "passed",
    "echec": "failed",
    "erreur": "error",
    "ignore": "skipped",
}

# Du moins grave au plus grave : plusieurs notes pour un même test — ses
# sous-tests, ses passages de --repeat, la fixture de sa classe — se
# résument à la plus grave.
GRAVITE = {"skipped": 0, "passed": 1, "failed": 2, "error": 3}

FIXTURES_CLASSE = {"setUpClass", "tearDownClass"}
FIXTURES_MODULE = {"setUpModule", "tearDownModule"}

# Délai d'un appel, en secondes : au-delà, l'envoi s'arrête.
DELAI = 30

# Un fichier de tests passé par le lanceur. `tests` : les notes de
# unit_file.py ; `panne` : None, ou la fin du journal d'un fichier qui a
# échoué sans rien noter (mort à l'import, tué par le délai).
Essai = namedtuple("Essai", "chemin tests panne")


class RegistreIndisponible(Exception):
    """Le registre a refusé ou n'a pas répondu ; le message est lisible."""


def _base(chemin, racine):
    """`erplibre:<chemin relatif>`, ou None hors de `racine`."""
    relatif = os.path.relpath(os.path.abspath(chemin), racine)
    if relatif == os.pardir or relatif.startswith(os.pardir + os.sep):
        return None
    return f"{DEPOT}:{relatif.replace(os.sep, '/')}"


def _verdict(resultat, log, duree):
    return {"result": resultat, "log": log or None, "duration": duree}


def references(essai, racine=RACINE):
    """{clé: [verdict, ...]} de ce que l'essai a noté.

    La clé d'un test est sa référence complète. Une fixture de classe en
    échec ou ignorée n'a pas de méthode : sa clé est le PRÉFIXE de sa
    classe, `<base>::<Classe>::` ; une fixture de module et une panne, celui
    du fichier, `<base>::`. Un sous-test est rangé sous son test. Rend {}
    pour un fichier hors de `racine`, qui n'a pas de référence `erplibre:`.
    """
    base = _base(essai.chemin, racine)
    if base is None:
        return {}
    notes = {}
    if essai.panne:
        notes[f"{base}::"] = [_verdict("error", essai.panne, 0.0)]
    for test in essai.tests:
        # « test_x (i=1) » : un sous-test, rangé sous test_x.
        methode = test["nom"].split(" ", 1)[0]
        if methode in FIXTURES_MODULE:
            cle = f"{base}::"
        elif methode in FIXTURES_CLASSE:
            cle = f"{base}::{test['classe']}::"
        else:
            cle = f"{base}::{test['classe']}::{methode}"
        resultat = RESULTATS.get(test["etat"], "error")
        notes.setdefault(cle, []).append(
            _verdict(resultat, test.get("message"), test.get("duree", 0.0))
        )
    return notes


def _prefixes(reference):
    """Les préfixes dont les notes s'appliquent aussi à `reference` : celui
    de son fichier et celui de sa classe."""
    morceaux = reference.split("::")
    if len(morceaux) < 3:
        return []
    return [f"{morceaux[0]}::", f"{morceaux[0]}::{morceaux[1]}::"]


def _pire(verdicts):
    """Le verdict le plus grave ; sa durée est la plus longue, son journal
    réunit ceux des notes de même gravité."""
    pire = max(verdicts, key=lambda v: GRAVITE[v["result"]])
    journaux = [
        v["log"]
        for v in verdicts
        if v["result"] == pire["result"] and v["log"]
    ]
    return _verdict(
        pire["result"],
        "\n\n".join(journaux),
        max(v["duration"] for v in verdicts),
    )


def verdicts_declares(essais, declarees, racine=RACINE):
    """{référence: verdict} pour chaque référence de `declarees` notée par
    les `essais`, elle-même ou par le préfixe de sa classe ou de son
    fichier. Une référence que rien n'a notée n'y figure pas : son test n'a
    pas tourné, son dernier verdict reste celui du registre."""
    notes = {}
    for essai in essais:
        for cle, verdicts in references(essai, racine).items():
            notes.setdefault(cle, []).extend(verdicts)
    resultat = {}
    for reference in declarees:
        verdicts = list(notes.get(reference, []))
        for prefixe in _prefixes(reference):
            verdicts += notes.get(prefixe, [])
        if verdicts:
            resultat[reference] = _pire(verdicts)
    return resultat


def _affichable(url):
    """`url` sans identifiants ni requête : ce qu'on peut afficher."""
    morceaux = urllib.parse.urlsplit(url)
    hote = morceaux.hostname or ""
    try:
        if morceaux.port:
            hote += f":{morceaux.port}"
    except ValueError:
        pass
    return urllib.parse.urlunsplit(
        (morceaux.scheme, hote, morceaux.path, "", "")
    )


def avertir(message, sortie=None):
    """Une ligne jaune « Registre des requis : `message` » sur `sortie`,
    la sortie standard par défaut."""
    print(
        f"  {JAUNE}Registre des requis : {message}{FIN}",
        file=sortie or sys.stdout,
    )


def _bouclage(hote):
    """Vrai si `hote` désigne la machine elle-même : `localhost` ou une
    adresse de bouclage, IPv4 ou IPv6."""
    if (hote or "").lower() in ("localhost", "localhost."):
        return True
    try:
        return ipaddress.ip_address(hote).is_loopback
    except ValueError:
        return False


def depuis_environnement(env=None, sortie=None):
    """Le Registre que l'environnement configure, ou None.

    Aucune variable : None, sans rien écrire. Une partie seulement, une URL
    qui n'est pas HTTPS, ou HTTP vers un hôte qui n'est pas de bouclage :
    None et une ligne d'avertissement sur `sortie`, sans aucune
    connexion."""
    env = os.environ if env is None else env
    sortie = sortie or sys.stdout
    valeurs = {nom: (env.get(nom) or "").strip() for nom in VARIABLES}
    if not any(valeurs.values()):
        return None
    manquantes = [nom for nom, valeur in valeurs.items() if not valeur]
    if manquantes:
        avertir(
            f"{', '.join(manquantes)} absente(s), aucun verdict envoyé.",
            sortie=sortie,
        )
        return None
    url, base, login, cle = (valeurs[nom] for nom in VARIABLES)
    morceaux = urllib.parse.urlsplit(url)
    if morceaux.scheme == "https":
        return Registre(url, base, login, cle)
    if morceaux.scheme == "http" and _bouclage(morceaux.hostname):
        return Registre(url, base, login, cle)
    if morceaux.scheme == "http":
        raison = (
            "HTTP sans chiffrement hors de la machine, la clé passerait en"
            " clair ; HTTPS, ou un tunnel vers localhost"
        )
    else:
        raison = "ni HTTPS ni HTTP"
    avertir(
        f"URL « {_affichable(url)} » : {raison}, aucun verdict envoyé.",
        sortie=sortie,
    )
    return None


class Registre:
    """Une instance Odoo qui reçoit les verdicts, par /jsonrpc."""

    def __init__(self, url, base, login, cle, delai=DELAI):
        self.url = url.rstrip("/")
        self.base = base
        self.login = login
        self.cle = cle
        self.delai = delai
        self._rang = 0

    def _masquer(self, texte, borne=None):
        """`texte` sur une ligne, la clé remplacée par « *** » ; coupé à
        `borne` caractères quand elle est donnée."""
        if self.cle:
            texte = texte.replace(self.cle, "***")
        texte = " ".join(texte.split())
        if borne and len(texte) > borne:
            texte = texte[: borne - 1] + "…"
        return texte

    def _neutraliser(self, journal, racine):
        """`journal` tel qu'il peut partir au registre, lignes gardées : la
        clé remplacée par « *** », un chemin sous `racine` rendu relatif à
        elle, le répertoire personnel remplacé par « ~ ». None reste None.

        Un chemin n'est remplacé qu'entier : `/depot` ne touche ni
        `/depot2` ni `/x/depot`. La racine passe avant le répertoire
        personnel, qui la contient d'ordinaire."""
        if not journal:
            return journal
        if self.cle:
            journal = journal.replace(self.cle, "***")
        for chemin, dessous, seul in (
            (os.path.abspath(racine), "", "."),
            (os.path.expanduser("~"), "~/", "~"),
        ):
            chemin = re.escape(chemin.rstrip(os.sep))
            if not chemin:
                continue
            avant = r"(?<![\w.-])"
            journal = re.sub(
                avant + chemin + re.escape(os.sep), dessous, journal
            )
            journal = re.sub(avant + chemin + r"(?![\w.-])", seul, journal)
        return journal

    def _appel(self, service, methode, args):
        """Le `result` d'un appel JSON-RPC ; RegistreIndisponible si le
        serveur rend une erreur."""
        self._rang += 1
        corps = {
            "jsonrpc": "2.0",
            "method": "call",
            "id": self._rang,
            "params": {"service": service, "method": methode, "args": args},
        }
        requete = urllib.request.Request(
            self.url + "/jsonrpc",
            data=json.dumps(corps).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(requete, timeout=self.delai) as reponse:
            donnees = json.loads(reponse.read().decode("utf-8"))
        erreur = donnees.get("error")
        if erreur:
            detail = (erreur.get("data") or {}).get("message")
            raise RegistreIndisponible(detail or erreur.get("message") or "")
        return donnees.get("result")

    def _execute(self, uid, methode, args, kwargs):
        return self._appel(
            "object",
            "execute_kw",
            [self.base, uid, self.cle, MODELE, methode, args, kwargs],
        )

    def pousser(self, essais, racine=None, sortie=None):
        """Envoie le verdict de chaque référence déclarée que les `essais`
        ont notée, puis écrit une ligne : le bilan, ou l'avertissement du
        premier échec. Ne lève jamais. `racine` : RACINE par défaut, lue à
        l'appel."""
        racine = racine or RACINE
        sortie = sortie or sys.stdout
        envoyes = mises_a_jour = 0
        try:
            uid = self._appel(
                "common", "login", [self.base, self.login, self.cle]
            )
            if not uid:
                raise RegistreIndisponible(
                    f"identifiants refusés pour « {self.login} »"
                )
            lignes = self._execute(
                uid,
                "search_read",
                [
                    [
                        ["kind", "=", SORTE],
                        ["reference", "=like", f"{DEPOT}:%"],
                    ]
                ],
                {"fields": ["reference"]},
            )
            declarees = {ligne["reference"] for ligne in lignes or []}
            verdicts = verdicts_declares(essais, declarees, racine)
            for reference in sorted(verdicts):
                verdict = verdicts[reference]
                mises_a_jour += int(
                    self._execute(
                        uid,
                        "record_result_by_reference",
                        [SORTE, reference, verdict["result"]],
                        {
                            "log": self._neutraliser(verdict["log"], racine),
                            "duration": verdict["duration"],
                        },
                    )
                    or 0
                )
                envoyes += 1
        # Tout échec, y compris imprévu, devient la ligne d'avertissement :
        # le registre ne décide jamais du code de sortie de la suite. Ctrl+C,
        # ou SIGTERM que le lanceur change en KeyboardInterrupt, arrête
        # l'envoi de même, et la suite rend son propre code.
        except (Exception, KeyboardInterrupt) as exc:  # noqa: BLE001
            raison = str(exc)
            if isinstance(exc, KeyboardInterrupt):
                raison = "arrêté par Ctrl+C ou SIGTERM"
            elif not isinstance(
                exc, (RegistreIndisponible, urllib.error.URLError)
            ):
                raison = f"{type(exc).__name__}: {raison}"
            avertir(
                self._masquer(
                    f"envoi interrompu après {envoyes} verdict(s)"
                    f" ({self._masquer(raison, borne=300)}) ; le code de"
                    " sortie de la suite n'en dépend pas."
                ),
                sortie=sortie,
            )
            return
        print(
            "  "
            + self._masquer(
                f"Registre des requis : {envoyes} verdicts envoyés,"
                f" {mises_a_jour} lignes mises à jour"
                f" ({_affichable(self.url)})."
            ),
            file=sortie,
        )
