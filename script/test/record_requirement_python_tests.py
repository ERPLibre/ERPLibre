#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Consigne dans Odoo le résultat des tests Python liés aux requis.

Lit par XML-RPC les lignes devops.requirement.test de type « python » (avec
le code de leur requis). Leur référence est un chemin pointé
odoo.addons.<module>.tests.<fichier>.<Classe>[.<méthode>].

--print-test-tags affiche les modules et la valeur --test-tags qui couvrent
ces lignes, de quoi composer la commande ./test.sh, et sort sans rien écrire.

--log FICHIER analyse le journal d'un ./test.sh --log-level=test et écrit,
par devops.requirement.test.record_result, le verdict de chaque ligne :
- failed si un test qui relève de la référence a un « FAIL: » ;
- error s'il a un « ERROR: », ou si le setUpClass ou le tearDownClass de
  sa classe échoue (la classe entière tombe alors) ;
- skipped si tous ses tests sont sautés, classe sautée comprise ;
- passed si tous ont démarré sans échec, certains pouvant être sautés.
Un test relancé (ODOO_TEST_FAILURE_RETRIES) est jugé sur sa dernière
tentative, et un sous-test sauté ne fait pas sauter son test. Une ligne dont
aucun test n'apparaît au journal n'est PAS écrite : elle garde son dernier
résultat, et le rapport la compte « non vue ».

Rien n'est écrit d'un journal qui n'est pas celui d'une passe complète et
unique : sans la ligne de bilan « N failed, N error(s) of N tests », ou
avec plusieurs, ou avec un test après elle ; passe abandonnée (« Failed to
initialize database », « Failed to load registry ») ou coupée par
ODOO_TEST_MAX_FAILED_TESTS (« Test suite halted ») ; nombre de tests
démarrés, de FAIL ou d'ERROR différent du bilan ; tests de plusieurs bases.

Codes de sortie : 0 toutes les lignes vues passent ou sont sautées, 1 au
moins une échoue (failed ou error), 2 l'outil échoue — connexion, RPC,
journal refusé, référence illisible, code demandé sans ligne, verdict non
remonté, aucune ligne lue ou aucune ligne vue. Une ligne non vue ne change
pas le code tant qu'une autre l'est : une passe limitée à quelques modules
est légitime. --require_all_seen la compte en erreur, pour une passe lancée
avec les --test-tags de --print-test-tags.

Le compte RPC est celui d'un exécutant (groupe
erplibre_devops_requirement.group_devops_requirement_runner, ou système).
Ses identifiants passent par deux variables d'environnement dont seuls les
NOMS sont en option : /proc/<pid>/cmdline est lisible par tout utilisateur
de la machine, /proc/<pid>/environ par son seul propriétaire.
"""

import argparse
import datetime
import json
import os
import re
import sys
import xmlrpc.client

RESULTATS = ("passed", "failed", "error", "skipped")

ENV_LOGIN_DEFAUT = "ERPLIBRE_REQUIREMENT_RUNNER_LOGIN"
ENV_PASSWORD_DEFAUT = "ERPLIBRE_REQUIREMENT_RUNNER_PASSWORD"

# Longueur maximale du journal envoyé par ligne, sous la borne de
# record_result (LOG_MAX_LENGTH d'erplibre_devops_requirement, qui garde la
# fin). La tête porte les échecs, puis les noms des tests : la coupe la garde.
LIMITE_JOURNAL = 8000
# Longueur maximale d'un extrait de trace. Une trace se lit par la fin, qui
# porte l'exception et l'assertion : la coupe garde la fin.
LIMITE_TRACE = 2000
MARQUE_TRONQUE = "\n… [tronqué : {} caractères omis]"
MARQUE_TRACE = "[… {} caractères omis]\n"

# En-tête d'un enregistrement du journal d'Odoo :
# « AAAA-MM-JJ hh:mm:ss,mmm <pid> INFO <base> <logger>: <message> ».
# Une ligne qui ne le porte pas continue l'enregistrement précédent (trace
# d'appel).
ENTETE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) \d+ [A-Z]+"
    r" (?P<base>\S+) (?P<logger>[\w.\-]+): (?P<message>.*)$"
)
# Couleurs d'un journal capté depuis un terminal.
ANSI = re.compile(r"\x1b\[[0-9;]*m")
# Messages d'OdooTestResult (odoo/tests/result.py) et d'OdooSuite
# (odoo/tests/suite.py). Le logger d'un test est le module Python de sa
# classe ; celui d'un échec de setUpClass ou tearDownClass est
# odoo.tests.suite, et le message nomme alors la classe en entier.
DEBUT_TEST = re.compile(r"^Starting (?P<desc>[\w.]+) \.\.\.")
ECHEC = re.compile(r"^(?P<sorte>FAIL|ERROR): (?P<desc>.+?)\s*$")
SAUT = re.compile(r"^skipped (?P<desc>.+?) : ?(?P<raison>.*?)\s*$")
NIVEAU_CLASSE = re.compile(
    r"^(?P<phase>setUpClass|tearDownClass) \((?P<classe>[\w.]+)\)$"
)
SOUS_TEST = re.compile(r"^Subtest (?P<desc>[\w.]+)")
BILAN = re.compile(
    r"^(?P<failed>\d+) failed, (?P<errors>\d+) error\(s\) of"
    r" (?P<tests>\d+) tests\b(?: when loading database '(?P<base>[^']+)')?"
)
# Enregistrements d'une passe qui n'a pas abouti, alors que server.run écrit
# quand même le bilan de chaque registre resté chargé : une exception hors
# du lanceur (préchargement, assets des tests post_install) saute toute la
# suite qui restait, et ODOO_TEST_MAX_FAILED_TESTS coupe la suite au milieu
# d'une classe sans rien journaliser des tests qu'elle ne lance pas.
ABANDONS = (
    ("odoo.service.server", "Failed to initialize database"),
    ("odoo.modules.registry", "Failed to load registry"),
    ("odoo.tests.result", "Test suite halted"),
)
# Un enregistrement de ces loggers sort du test en cours : chargement d'un
# module, passage aux tests post_install, arrêt du serveur.
LOGGERS_FRONTIERE = ("odoo.modules.", "odoo.service.server")

PREFIXE_ADDONS = "odoo.addons."


class JournalInvalide(Exception):
    """Journal illisible, tronqué ou sans bilan : rien ne doit être écrit."""


def lire_reference(reference):
    """Rend la référence décomposée, ou None si elle est illisible.

    reference : odoo.addons.<module>.<chemin>.<Classe>[.<méthode>]. La
    classe est le dernier segment qui commence par une majuscule ; seul un
    segment qui commence par « test » peut la suivre, comme méthode. Rend
    {"module", "module_py", "classe", "methode"} : module est le module
    Odoo, module_py le module Python de la classe, methode None pour une
    classe entière.
    """
    reference = (reference or "").strip()
    if not reference.startswith(PREFIXE_ADDONS):
        return None
    segments = reference.split(".")
    if any(not re.fullmatch(r"\w+", s) for s in segments):
        return None
    methode = None
    if segments[-1].startswith("test") and len(segments) >= 2:
        methode = segments[-1]
        segments = segments[:-1]
    classe = segments[-1]
    # odoo, addons, module, au moins un segment de chemin, la classe
    if len(segments) < 5 or not classe[:1].isupper():
        return None
    if any(s[:1].isupper() for s in segments[2:-1]):
        return None
    return {
        "module": segments[2],
        "module_py": ".".join(segments[:-1]),
        "classe": classe,
        "methode": methode,
    }


def etiquette_test(ref):
    """Rend l'élément --test-tags d'une référence décomposée.

    La forme fichier (/module/tests/fichier.py:Classe[.méthode]) désigne la
    classe dans son fichier : la forme module (/module:Classe) prendrait
    aussi une classe homonyme d'un autre fichier du même module. Sans
    étiquette, le TagsSelector d'Odoo exige « standard » et écarte un test
    marqué -standard ; « * » lève cette exigence, et la ligne désigne son
    test quelles que soient ses étiquettes.
    """
    chemin = ref["module_py"][len(PREFIXE_ADDONS) :].replace(".", "/")
    etiquette = f"*/{chemin}.py:{ref['classe']}"
    if ref["methode"]:
        etiquette += f".{ref['methode']}"
    return etiquette


def etiquettes_tests(references):
    """Rend (modules, test_tags) qui couvrent les références décomposées.

    Une classe entière absorbe ses méthodes. Les deux listes sont triées et
    sans doublon ; test_tags se joint par des virgules pour --test-tags.
    """
    classes = {
        (r["module_py"], r["classe"]) for r in references if not r["methode"]
    }
    etiquettes = set()
    for ref in references:
        if ref["methode"] and (ref["module_py"], ref["classe"]) in classes:
            continue
        etiquettes.add(etiquette_test(ref))
    modules = sorted({r["module"] for r in references})
    return modules, sorted(etiquettes)


def _horodatage(texte):
    return datetime.datetime.strptime(texte, "%Y-%m-%d %H:%M:%S,%f")


def enregistrements(lignes):
    """Rend la liste des enregistrements (date, base, logger, message).

    message porte les lignes de continuation (trace d'appel). Le texte qui
    précède le premier en-tête est ignoré.
    """
    resultat = []
    for brute in lignes:
        ligne = ANSI.sub("", brute.rstrip("\n"))
        entete = ENTETE.match(ligne)
        if entete:
            resultat.append(
                [
                    _horodatage(entete["date"]),
                    entete["base"],
                    entete["logger"],
                    entete["message"],
                ]
            )
        elif resultat:
            resultat[-1][3] += "\n" + ligne
    return [tuple(e) for e in resultat]


def _abandon(logger, premiere):
    """Rend le message d'abandon de la passe que porte l'enregistrement, ou None."""
    for nom, debut in ABANDONS:
        if logger == nom and premiere.startswith(debut):
            return premiere
    return None


def _verifier_coherence(bilan, comptes, bases):
    """Lève JournalInvalide si les tests lus ne recoupent pas le bilan.

    comptes : nombre de « Starting », de FAIL et d'ERROR retenus. Chaque
    startTest d'OdooTestResult journalise un « Starting » et compte un test,
    chaque addFailure ou addError journalise un FAIL ou un ERROR et compte
    un échec ; un écart veut dire un journal coupé, mêlé à un autre, ou à un
    niveau qui masque les tests. bases : bases nommées par les
    enregistrements de test, qui doivent être celle du bilan.
    """
    for cle, nom in (
        ("tests", "tests démarrés"),
        ("failed", "FAIL"),
        ("errors", "ERROR"),
    ):
        if comptes[cle] != bilan[cle]:
            raise JournalInvalide(
                f"{comptes[cle]} {nom} au journal, {bilan[cle]} au bilan :"
                " journal incohérent (coupé, mêlé à une autre passe, ou pas"
                " en --log-level=test)"
            )
    attendues = {bilan["base"]} if bilan.get("base") else set()
    if len(bases | attendues) > 1:
        raise JournalInvalide(
            f"tests de plusieurs bases : {', '.join(sorted(bases | attendues))}"
        )


def analyser_journal(lignes):
    """Rend l'analyse d'un journal ./test.sh --log-level=test.

    Rend {"tests", "classes", "evenements", "bilan"} :
    - tests : {(module_py, classe, methode): {"debut", "saute", "echecs",
      "sauts_sous_tests", "tentatives"}}, saute la raison d'un saut du test
      ou None, echecs une liste de (sorte, trace), sauts_sous_tests les
      raisons des sous-tests sautés, qui ne font pas sauter le test ;
    - classes : {"module_py.Classe": [(sorte, phase, texte)]}, sorte
      ERROR ou skipped, phase setUpClass ou tearDownClass ;
    - evenements : liste chronologique de (date, nature, cle) qui sert aux
      durées ; nature vaut test, classe ou frontiere ;
    - bilan : {"failed", "errors", "tests", "base"}, la ligne de bilan.
    Un test qui redémarre (ODOO_TEST_FAILURE_RETRIES) n'est jugé que sur sa
    dernière tentative : Odoo ne compte pas les échecs des précédentes.
    Lève JournalInvalide sans ligne de bilan ou avec plusieurs, sur un
    événement de test après le bilan, sur une passe abandonnée ou coupée
    (voir ABANDONS), et quand les tests lus ne recoupent pas le bilan.
    """
    tests = {}
    classes = {}
    evenements = []
    bilan = None
    comptes = {"tests": 0}
    bases = set()

    def test(cle):
        return tests.setdefault(
            cle,
            {
                "debut": None,
                "saute": None,
                "echecs": [],
                "sauts_sous_tests": [],
                "tentatives": 0,
            },
        )

    def evenement_de_test(date, base, nature, cle):
        if bilan is not None:
            raise JournalInvalide(
                "un test suit la ligne de bilan : journal de plusieurs passes"
            )
        bases.add(base)
        evenements.append((date, nature, cle))

    for date, base, logger, message in enregistrements(lignes):
        premiere, _, suite = message.partition("\n")
        premiere = premiere.rstrip()
        abandon = _abandon(logger, premiere)
        if abandon:
            raise JournalInvalide(f"passe qui n'a pas abouti : {abandon}")
        if logger.startswith("odoo.tests") and BILAN.match(premiere):
            if bilan is not None:
                raise JournalInvalide(
                    "plusieurs lignes de bilan : journal de plusieurs passes"
                    " ou de plusieurs bases"
                )
            b = BILAN.match(premiere).groupdict()
            bilan = {k: int(b[k]) for k in ("failed", "errors", "tests")}
            bilan["base"] = b["base"]
            evenements.append((date, "frontiere", None))
            continue
        if logger.startswith(LOGGERS_FRONTIERE):
            evenements.append((date, "frontiere", None))
            continue
        debut = DEBUT_TEST.match(premiere)
        echec = ECHEC.match(premiere)
        saut = SAUT.match(premiere)
        if debut and "." in debut["desc"]:
            classe, methode = debut["desc"].rsplit(".", 1)
            cle = (logger, classe, methode)
            evenement_de_test(date, base, "test", cle)
            comptes["tests"] += 1
            etat = test(cle)
            if etat["debut"] is None:
                etat["debut"] = date
            else:
                etat.update(saute=None, echecs=[], sauts_sous_tests=[])
            etat["tentatives"] += 1
        elif echec or saut:
            desc = (echec or saut)["desc"]
            niveau = NIVEAU_CLASSE.match(desc)
            if niveau:
                sorte = echec["sorte"] if echec else "skipped"
                texte = suite.strip("\n") if echec else saut["raison"]
                evenement_de_test(date, base, "classe", niveau["classe"])
                classes.setdefault(niveau["classe"], []).append(
                    (sorte, niveau["phase"], texte)
                )
                continue
            sous_test = SOUS_TEST.match(desc)
            if sous_test:
                desc = sous_test["desc"]
            if "." not in desc:
                continue
            classe, methode = desc.rsplit(".", 1)
            cle = (logger, classe, methode)
            evenement_de_test(date, base, "test", cle)
            if echec:
                test(cle)["echecs"].append(
                    (echec["sorte"], f"{premiere}\n{suite}".rstrip())
                )
            elif sous_test:
                test(cle)["sauts_sous_tests"].append(saut["raison"])
            else:
                test(cle)["saute"] = saut["raison"]
    if bilan is None:
        raise JournalInvalide(
            "aucune ligne « N failed, N error(s) of N tests » : journal"
            " tronqué, ou passe qui n'a pas abouti"
        )
    sortes = [s for etat in tests.values() for s, _ in etat["echecs"]]
    sortes += [s for evts in classes.values() for s, _, _ in evts]
    comptes["failed"] = sortes.count("FAIL")
    comptes["errors"] = sortes.count("ERROR")
    _verifier_coherence(bilan, comptes, bases)
    return {
        "tests": tests,
        "classes": classes,
        "evenements": evenements,
        "bilan": bilan,
    }


def _relevant(ref, cle):
    module_py, classe, methode = cle
    return (
        module_py == ref["module_py"]
        and classe == ref["classe"]
        and (ref["methode"] is None or methode == ref["methode"])
    )


def duree_reference(ref, analyse):
    """Rend la durée en secondes des tests d'une référence, ou None.

    Chaque série contiguë de ses tests court de son premier « Starting » au
    premier enregistrement qui sort de la série : un autre test, une autre
    classe, un chargement de module, le bilan. Le setUpClass de la classe
    suivante précède son premier « Starting » sans marque au journal : la
    durée du dernier test d'une classe l'inclut, c'est une borne haute.
    None si la référence n'a pas démarré ou si une série ne se ferme pas.
    """
    nom_classe = f"{ref['module_py']}.{ref['classe']}"
    total = 0.0
    debut_serie = None
    vu = False
    for date, nature, cle in analyse["evenements"]:
        dedans = (nature == "test" and _relevant(ref, cle)) or (
            nature == "classe" and cle == nom_classe
        )
        if dedans:
            if debut_serie is None and nature == "test":
                debut_serie = date
                vu = True
            continue
        if debut_serie is not None:
            total += (date - debut_serie).total_seconds()
            debut_serie = None
    if not vu or debut_serie is not None:
        return None
    return round(total, 3)


def borner_trace(trace, limite=LIMITE_TRACE):
    """Rend la trace bornée à limite caractères, fin gardée."""
    if len(trace) <= limite:
        return trace
    marque = MARQUE_TRACE.format(len(trace))
    garde = max(0, limite - len(marque))
    return (
        MARQUE_TRACE.format(len(trace) - garde) + trace[len(trace) - garde :]
    )


def tronquer(texte, limite=LIMITE_JOURNAL):
    """Rend texte borné à limite caractères, tête gardée, marque comprise."""
    texte = texte or ""
    if len(texte) <= limite:
        return texte
    marque_max = MARQUE_TRONQUE.format(len(texte))
    garde = max(0, limite - len(marque_max))
    return texte[:garde] + MARQUE_TRONQUE.format(len(texte) - garde)


def _resultat_test(etat):
    """Rend le résultat d'un test du journal : FAIL, puis ERROR, puis saut."""
    sortes = {sorte for sorte, _ in etat["echecs"]}
    if "FAIL" in sortes:
        return "failed"
    if "ERROR" in sortes:
        return "error"
    if etat["saute"] is not None:
        return "skipped"
    return "passed"


def _resultat_reference(lignes_tests, erreur_classe, saut_classe):
    """Rend le résultat d'une référence depuis ses tests, ou None."""
    resultats = {t["resultat"] for t in lignes_tests}
    if "failed" in resultats:
        return "failed"
    if "error" in resultats or erreur_classe:
        return "error"
    if resultats == {"skipped"} or (not lignes_tests and saut_classe):
        return "skipped"
    if "passed" in resultats:
        return "passed"
    return None


def _journal_reference(lignes_tests, echecs, saut_classe):
    """Rend le journal consigné : bilan, traces bornées, puis les noms."""
    totaux = {}
    for test in lignes_tests:
        totaux[test["resultat"]] = totaux.get(test["resultat"], 0) + 1
    resume = ", ".join(f"{n} {r}" for r, n in sorted(totaux.items()))
    parties = [f"{len(lignes_tests)} test(s) : {resume or 'aucun'}"]
    if saut_classe is not None:
        parties.append(f"classe sautée : {saut_classe}")
    parties += [borner_trace(trace) for trace in echecs]
    for test in lignes_tests:
        if test["resultat"] in ("failed", "error"):
            continue
        texte = f"{test['resultat']}: {test['nom']}"
        if test.get("raison"):
            texte += f" ({test['raison']})"
        for raison in test.get("sous_tests_sautes", []):
            texte += f" (sous-test sauté : {raison})"
        if test.get("tentatives", 1) > 1:
            texte += f" ({test['tentatives']} tentatives)"
        parties.append(texte)
    return tronquer("\n".join(parties))


def verdict_reference(ref, analyse):
    """Rend le verdict d'une référence décomposée, ou None si non vue.

    Rend {"resultat", "tests", "journal", "duree"} : tests liste
    {"nom", "resultat"} par test du journal qui relève de la référence ;
    journal porte les échecs avec leur trace bornée, puis les noms.
    """
    nom_classe = f"{ref['module_py']}.{ref['classe']}"
    evenements_classe = analyse["classes"].get(nom_classe, [])
    concernes = sorted(
        (cle, etat)
        for cle, etat in analyse["tests"].items()
        if _relevant(ref, cle)
    )
    if not concernes and not evenements_classe:
        return None

    echecs = []
    lignes_tests = []
    for (_, classe, methode), etat in concernes:
        test = {"nom": f"{classe}.{methode}", "resultat": _resultat_test(etat)}
        if test["resultat"] == "skipped":
            test["raison"] = etat["saute"]
        if etat["sauts_sous_tests"]:
            test["sous_tests_sautes"] = list(etat["sauts_sous_tests"])
        if etat["tentatives"] > 1:
            test["tentatives"] = etat["tentatives"]
        lignes_tests.append(test)
        echecs += [trace for _, trace in etat["echecs"]]
    erreur_classe = False
    saut_classe = None
    for sorte, phase, texte in evenements_classe:
        if sorte == "skipped":
            saut_classe = texte
            continue
        erreur_classe = True
        echecs.append(f"{sorte}: {phase} ({nom_classe})\n{texte}".rstrip())

    resultat = _resultat_reference(lignes_tests, erreur_classe, saut_classe)
    if resultat is None:
        return None
    return {
        "resultat": resultat,
        "tests": lignes_tests,
        "journal": _journal_reference(lignes_tests, echecs, saut_classe),
        "duree": duree_reference(ref, analyse),
    }


def lignes_a_traiter(lignes, codes_par_id, codes_demandes=None):
    """Rend (lignes, manquants) depuis les lignes devops.requirement.test.

    lignes : dictionnaires search_read avec requirement_id ([id, nom] ou
    False) et reference. Rend une liste de {"code", "reference", "ref"}
    sans doublon, triée par code puis référence, ref étant la référence
    décomposée ou None ; manquants liste les codes demandés sans ligne.
    La référence garde sa valeur stockée : record_result la compare telle
    quelle.
    """
    vus = set()
    resultat = []
    for ligne in lignes:
        requis = ligne.get("requirement_id")
        id_requis = requis[0] if isinstance(requis, (list, tuple)) else requis
        code = codes_par_id.get(id_requis) or ""
        reference = ligne.get("reference") or ""
        if (code, reference) in vus:
            continue
        vus.add((code, reference))
        resultat.append(
            {
                "code": code,
                "reference": reference,
                "ref": lire_reference(reference),
            }
        )
    resultat.sort(key=lambda ligne: (ligne["code"], ligne["reference"]))
    presents = {ligne["code"] for ligne in resultat}
    manquants = [c for c in (codes_demandes or []) if c not in presents]
    return resultat, manquants


def codes_demandes(valeurs):
    """Rend la liste des codes de --code, répétable et séparable par virgule."""
    codes = []
    for valeur in valeurs or []:
        for code in valeur.split(","):
            code = code.strip()
            if code and code not in codes:
                codes.append(code)
    return codes


def identifiants_rpc(config, environ=None):
    """Rend (login, mot de passe) du compte exécutant.

    Lève ValueError, en nommant les variables en cause, si l'une des deux
    manque : aucun repli sur argv ni sur un mot de passe par défaut.
    """
    environ = os.environ if environ is None else environ
    login = environ.get(config.rpc_login_env or "")
    password = environ.get(config.rpc_password_env or "")
    if login and password:
        return login, password
    manquantes = [
        nom
        for nom, valeur in (
            (config.rpc_login_env, login),
            (config.rpc_password_env, password),
        )
        if not valeur
    ]
    raise ValueError(
        f"variable(s) absente(s) ou vide(s) : {', '.join(manquantes)}"
    )


def code_de_sortie(resultats, erreur_outil=None):
    """Rend 0, 1 ou 2 pour la passe ; voir la docstring du module.

    resultats : lignes du rapport. « remonte » à False veut dire que
    record_result n'a pas écrit : la base afficherait un verdict périmé.
    À None, l'écriture n'a pas été tentée (--dry_run, ligne non vue).
    """
    if erreur_outil or not resultats:
        return 2
    vues = [ligne for ligne in resultats if ligne["resultat"] is not None]
    if not vues:
        return 2
    for ligne in resultats:
        if ligne.get("erreur") or ligne.get("remonte") is False:
            return 2
    if any(ligne["resultat"] in ("failed", "error") for ligne in vues):
        return 1
    return 0


def evaluer(lignes, manquants, analyse):
    """Rend les lignes du rapport, sans rien écrire.

    Une ligne à référence illisible, sans code, ou un code demandé sans
    ligne porte « erreur » et resultat None.
    """
    resultats = []
    for code in manquants:
        resultats.append(
            _ligne_rapport(code, "", erreur="aucune ligne de test python")
        )
    for ligne in lignes:
        if not ligne["code"] or ligne["ref"] is None:
            resultats.append(
                _ligne_rapport(
                    ligne["code"],
                    ligne["reference"],
                    erreur="référence illisible ou ligne sans code de requis",
                )
            )
            continue
        verdict = verdict_reference(ligne["ref"], analyse)
        rapport = _ligne_rapport(ligne["code"], ligne["reference"])
        if verdict:
            rapport.update(verdict)
        resultats.append(rapport)
    return resultats


def _ligne_rapport(code, reference, erreur=None):
    return {
        "code": code,
        "reference": reference,
        "resultat": None,
        "tests": [],
        "journal": "",
        "duree": None,
        "remonte": None,
        "erreur": erreur,
    }


def remonter(rpc, resultats):
    """Écrit le verdict de chaque ligne vue ; renseigne « remonte »."""
    for ligne in resultats:
        if ligne["resultat"] is None or ligne["erreur"]:
            continue
        try:
            ligne["remonte"] = bool(
                rpc.remonter(
                    ligne["code"],
                    ligne["reference"],
                    ligne["resultat"],
                    ligne["journal"],
                    ligne["duree"],
                )
            )
        except Exception as e:
            # Large : une réponse non XML (proxy, page de maintenance) lève
            # ExpatError, et une exception sortie d'ici perdrait le rapport.
            ligne["remonte"] = False
            ligne["erreur"] = f"verdict non remonté : {e}"
            continue
        if not ligne["remonte"]:
            ligne["erreur"] = (
                "verdict non remonté : record_result ne trouve pas la ligne"
            )


def construire_rapport(config, debut, resultats, code, erreur_outil, bilan):
    """Rend le rapport JSON de la passe ; aucun identifiant de compte."""
    totaux = {r: 0 for r in RESULTATS}
    totaux.update({"non_vu": 0, "erreur": 0})
    for ligne in resultats:
        if ligne.get("erreur") and ligne["resultat"] is None:
            totaux["erreur"] += 1
        elif ligne["resultat"] is None:
            totaux["non_vu"] += 1
        else:
            totaux[ligne["resultat"]] += 1
    return {
        "url": config.url,
        "db": config.db,
        "journal": config.log,
        "debut": debut,
        "dry_run": config.dry_run,
        "code_sortie": code,
        "erreur_outil": erreur_outil,
        "bilan_journal": bilan,
        "totaux": totaux,
        "resultats": resultats,
    }


def ecrire_rapport(chemin, rapport):
    dossier = os.path.dirname(chemin)
    if dossier:
        os.makedirs(dossier, exist_ok=True)
    with open(chemin, "w", encoding="utf-8") as fichier:
        json.dump(rapport, fichier, indent=2, ensure_ascii=False)


class Rpc:
    """Client XML-RPC minimal du compte exécutant."""

    def __init__(self, url, db, login, password):
        self.url = url.rstrip("/")
        self.db = db
        self.login = login
        self.password = password
        self.uid = None
        self.models = xmlrpc.client.ServerProxy(
            f"{self.url}/xmlrpc/2/object", allow_none=True
        )

    @staticmethod
    def liste_bases(url):
        db = xmlrpc.client.ServerProxy(
            f"{url.rstrip('/')}/xmlrpc/2/db", allow_none=True
        )
        return db.list()

    def authentifier(self):
        common = xmlrpc.client.ServerProxy(
            f"{self.url}/xmlrpc/2/common", allow_none=True
        )
        self.uid = common.authenticate(self.db, self.login, self.password, {})
        return self.uid

    def appel(self, modele, methode, args, kwargs=None):
        return self.models.execute_kw(
            self.db,
            self.uid,
            self.password,
            modele,
            methode,
            args,
            kwargs or {},
        )

    def lire_lignes(self, codes=None):
        """Rend (lignes, manquants), voir lignes_a_traiter."""
        domaine = [("kind", "=", "python")]
        if codes:
            domaine.append(("requirement_id.code", "in", codes))
        lignes = self.appel(
            "devops.requirement.test",
            "search_read",
            [domaine],
            {"fields": ["requirement_id", "reference"]},
        )
        ids = sorted(
            {
                ligne["requirement_id"][0]
                for ligne in lignes
                if ligne.get("requirement_id")
            }
        )
        codes_par_id = {}
        if ids:
            for requis in self.appel(
                "devops.requirement", "read", [ids], {"fields": ["code"]}
            ):
                codes_par_id[requis["id"]] = requis["code"]
        return lignes_a_traiter(lignes, codes_par_id, codes)

    def remonter(self, code, reference, resultat, journal, duree):
        return self.appel(
            "devops.requirement.test",
            "record_result",
            [code, "python", reference, resultat],
            {"log": journal, "duration": duree},
        )


def fill_parser(parser):
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8069",
        help="Serveur Odoo qui porte les requis.",
    )
    parser.add_argument(
        "--db",
        default="",
        help="Base des requis ; défaut : la seule base du serveur.",
    )
    parser.add_argument(
        "--code",
        action="append",
        default=[],
        help=(
            "Code de requis, répétable ou séparé par des virgules ; défaut :"
            " tous les requis qui ont un test python."
        ),
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--print-test-tags",
        dest="print_test_tags",
        action="store_true",
        help=(
            "Affiche « modules=… » et « test_tags=… » pour ./test.sh -i et"
            " --test-tags, puis sort sans rien écrire."
        ),
    )
    mode.add_argument(
        "--log",
        default="",
        help="Journal d'un ./test.sh --log-level=test à consigner.",
    )
    parser.add_argument(
        "--dry_run",
        action="store_true",
        help="Analyse et rapporte sans écrire les verdicts dans Odoo.",
    )
    parser.add_argument(
        "--require_all_seen",
        action="store_true",
        help=(
            "Sort à 2 si une ligne n'est pas vue : pour une passe lancée avec"
            " les --test-tags de --print-test-tags, où chaque ligne doit"
            " avoir tourné. Les lignes vues sont écrites quand même."
        ),
    )
    parser.add_argument(
        "--report_json",
        default="",
        help=(
            "Chemin du rapport ; défaut : report_<horodatage>.json sous"
            " ./screencasts/requirement_python_tests."
        ),
    )
    parser.add_argument(
        "--rpc_login_env",
        default=ENV_LOGIN_DEFAUT,
        help="NOM de la variable d'environnement du login de l'exécutant.",
    )
    parser.add_argument(
        "--rpc_password_env",
        default=ENV_PASSWORD_DEFAUT,
        help="NOM de la variable d'environnement de son mot de passe.",
    )


def compute_args(args):
    args.code = codes_demandes(args.code)
    args.url = args.url.rstrip("/")
    if not args.report_json:
        horodatage = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        args.report_json = os.path.join(
            ".",
            "screencasts",
            "requirement_python_tests",
            f"report_{horodatage}.json",
        )


def resoudre_base(config):
    """Rend (base, message d'erreur) ; la base vaut --db ou la seule du serveur."""
    if config.db:
        return config.db, None
    try:
        bases = Rpc.liste_bases(config.url)
    except Exception as e:
        return None, f"liste des bases illisible, préciser --db ({e})"
    if len(bases) != 1:
        return None, f"{len(bases)} base(s) sur le serveur : préciser --db"
    return bases[0], None


def preparer_rpc(config, environ=None):
    """Rend (rpc, lignes, manquants, message d'erreur)."""
    config.db, erreur = resoudre_base(config)
    if erreur:
        return None, [], [], erreur
    try:
        login, password = identifiants_rpc(config, environ)
    except ValueError as e:
        return None, [], [], f"identifiants de l'exécutant : {e}"
    rpc = Rpc(config.url, config.db, login, password)
    try:
        if not rpc.authentifier():
            return None, [], [], "authentification RPC refusée"
        lignes, manquants = rpc.lire_lignes(config.code)
    except Exception as e:
        # Large : une réponse HTML (proxy, page de maintenance) lève
        # ExpatError, qui n'est ni xmlrpc.client.Error ni OSError.
        return None, [], [], f"RPC impossible : {e}"
    if not lignes:
        erreur = "aucune ligne devops.requirement.test de type python"
        if manquants:
            erreur += f" pour {', '.join(manquants)}"
        return rpc, [], manquants, erreur
    return rpc, lignes, manquants, None


def imprimer_test_tags(lignes, manquants, sortie=None, erreurs=None):
    """Écrit modules= et test_tags= sur sortie ; rend le code de sortie.

    Les références illisibles et les codes sans ligne vont sur erreurs et
    rendent 2, sans empêcher d'imprimer ce qui est lisible.
    """
    sortie = sortie or sys.stdout
    erreurs = erreurs or sys.stderr
    code = 0
    for manquant in manquants:
        print(
            f"[{manquant}] ERREUR : aucune ligne de test python.", file=erreurs
        )
        code = 2
    references = []
    for ligne in lignes:
        if ligne["ref"] is None or not ligne["code"]:
            print(
                f"[{ligne['code']}] ERREUR : référence illisible"
                f" « {ligne['reference']} ».",
                file=erreurs,
            )
            code = 2
            continue
        references.append(ligne["ref"])
    if not references:
        return 2
    modules, etiquettes = etiquettes_tests(references)
    print(f"modules={','.join(modules)}", file=sortie)
    print(f"test_tags={','.join(etiquettes)}", file=sortie)
    return code


def consigner(config, rpc, lignes, manquants):
    """Analyse le journal, écrit les verdicts ; rend (résultats, bilan, erreur)."""
    try:
        with open(config.log, encoding="utf-8", errors="replace") as fichier:
            analyse = analyser_journal(fichier)
    except (OSError, JournalInvalide) as e:
        return [], None, f"journal {config.log} : {e}"
    resultats = evaluer(lignes, manquants, analyse)
    if not config.dry_run:
        remonter(rpc, resultats)
    return resultats, analyse["bilan"], None


def afficher(resultats):
    for ligne in resultats:
        etat = ligne["resultat"] or (
            "ERREUR" if ligne["erreur"] else "non vue"
        )
        print(f"[{ligne['code']}] {etat} : {ligne['reference']}")
        if ligne["erreur"]:
            print(f"  {ligne['erreur']}")


def main(argv=None, environ=None):
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
        # Un script qui enveloppe l'outil n'a qu'un nom exact à refuser.
        allow_abbrev=False,
    )
    fill_parser(parser)
    args = parser.parse_args(argv)
    compute_args(args)

    rpc, lignes, manquants, erreur = preparer_rpc(args, environ)
    if args.print_test_tags:
        if erreur:
            print(f"ERREUR : {erreur}", file=sys.stderr)
            return 2
        return imprimer_test_tags(lignes, manquants)

    debut = datetime.datetime.now().isoformat(timespec="seconds")
    resultats, bilan = [], None
    if not erreur:
        resultats, bilan, erreur = consigner(args, rpc, lignes, manquants)
        afficher(resultats)
        non_vues = [
            ligne
            for ligne in resultats
            if ligne["resultat"] is None and not ligne["erreur"]
        ]
        if not erreur and resultats and len(non_vues) == len(resultats):
            erreur = "aucune ligne vue dans le journal"
        elif not erreur and non_vues and args.require_all_seen:
            erreur = (
                f"{len(non_vues)} ligne(s) non vue(s) avec --require_all_seen :"
                " test renommé, supprimé ou non chargé"
            )
    if erreur:
        print(f"ERREUR : {erreur}")
    code = code_de_sortie(resultats, erreur)
    rapport = construire_rapport(args, debut, resultats, code, erreur, bilan)
    try:
        ecrire_rapport(args.report_json, rapport)
        print(f"Rapport : {args.report_json}")
    except OSError as e:
        print(f"Rapport non écrit : {e}")
    totaux = ", ".join(f"{v} {k}" for k, v in rapport["totaux"].items() if v)
    ecrit = " (rien écrit : --dry_run)" if args.dry_run else ""
    print(f"Bilan : {totaux or 'aucune ligne'}{ecrit} → sortie {code}")
    return code


if __name__ == "__main__":
    sys.exit(main())
