#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Joue les tours web_tour liés aux requis et remonte leur verdict dans Odoo.

Lit par XML-RPC les lignes devops.requirement.test de type « tour » (avec le
code de leur requis), ouvre UNE session navigateur, joue chaque tour en mode
« auto » depuis /odoo, puis écrit le verdict par
devops.requirement.test.record_result. Un tour en échec ou sans verdict
laisse une capture d'écran ; un rapport JSON résume la passe.

Codes de sortie : 0 tous les tours passent, 1 au moins un tour échoue,
2 l'outil échoue — navigateur, connexion, RPC, tour absent ou sans verdict,
verdict non remonté, ou aucune ligne à jouer. Zéro tour n'est pas « zéro
échec » : un filtre qui ne désigne rien rend 2, pas un vert. Un verdict
inconnu l'emporte sur un échec, car la passe est alors incomplète.

Le compte RPC est celui d'un exécutant (groupe
erplibre_devops_requirement.group_devops_requirement_runner, ou système).
Ses identifiants passent par des variables d'environnement dont seuls les
NOMS sont en option : /proc/<pid>/cmdline est lisible par tout utilisateur
de la machine, /proc/<pid>/environ par son seul propriétaire. Les deux
variables posées, elles servent aussi à la connexion navigateur, sauf
--default_email_auth explicite. Sans elles, le RPC reprend le compte
navigateur à condition que son mot de passe vienne lui aussi de
l'environnement (--default_password_auth_env) ; jamais d'argv, jamais d'un
mot de passe par défaut. Une seule des deux variables posée est une erreur.

Effets de bord sur la base visée :
- l'Onboarding du compte navigateur est coupé EN BASE pendant la passe,
  faute de quoi une visite native démarre au chargement de /odoo et se met
  en travers ; il est rallumé à la fin s'il était allumé, et une valeur
  illisible au départ arrête la passe avant d'y toucher ;
- un tour joué en auto y LAISSE les enregistrements qu'il crée, rien ne les
  annule comme le fait un HttpCase.
"""

import argparse
import datetime
import json
import os
import re
import sys
import time
import xmlrpc.client

new_path = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
sys.path.append(new_path)

from script.selenium import selenium_lib, web_login  # noqa: E402

# Valeurs admises par record_result côté Odoo.
RESULTATS = ("not_run", "passed", "failed", "error", "skipped")

# Longueur maximale du journal envoyé à record_result et gardé au rapport.
# Le message d'un tour en échec porte les étapes voisines et les
# console.error de la page : sans borne, un tour bavard gonfle chaque ligne
# de test d'autant à chaque passe. La coupe garde la TÊTE, qui porte
# « FAILED: <étape> », et reste sous la borne de record_result
# (LOG_MAX_LENGTH, erplibre_devops_requirement), qui garderait sinon la fin.
LIMITE_JOURNAL = 8000

MARQUE_TRONQUE = "\n… [tronqué : {} caractères omis]"

ENV_LOGIN_DEFAUT = "ERPLIBRE_REQUIREMENT_RUNNER_LOGIN"
ENV_PASSWORD_DEFAUT = "ERPLIBRE_REQUIREMENT_RUNNER_PASSWORD"


def resultat_du_verdict(ok):
    """Rend la valeur record_result d'un verdict de SeleniumLib.odoo_run_tour.

    True → passed, False → failed (le tour annonce « FAILED »), toute autre
    valeur → error (aucun verdict lisible).
    """
    if ok is True:
        return "passed"
    if ok is False:
        return "failed"
    return "error"


def code_de_sortie(resultats, erreur_outil=None):
    """Rend 0, 1 ou 2 pour la passe ; voir la docstring du module.

    Une ligne dont « remonte » vaut False n'a pas atteint Odoo : la base
    affiche alors un verdict périmé, ce qui compte comme une erreur d'outil.
    « remonte » à None veut dire « non tenté » (--no_record) et ne compte pas.
    """
    if erreur_outil or not resultats:
        return 2
    for ligne in resultats:
        if ligne["resultat"] == "error" or ligne.get("remonte") is False:
            return 2
    if any(ligne["resultat"] == "failed" for ligne in resultats):
        return 1
    return 0


def tronquer(texte, limite=LIMITE_JOURNAL):
    """Rend texte borné à limite caractères, marque de coupe comprise.

    La tête est gardée : c'est elle qui porte « FAILED: <étape> ». La marque
    dit combien de caractères manquent, pour qu'un journal coupé ne se lise
    pas comme complet.
    """
    texte = texte or ""
    if len(texte) <= limite:
        return texte
    # La marque se calcule sur le nombre final de caractères omis, qui
    # dépend de sa propre longueur : on la dimensionne sur le pire cas.
    marque_max = MARQUE_TRONQUE.format(len(texte))
    garde = max(0, limite - len(marque_max))
    return texte[:garde] + MARQUE_TRONQUE.format(len(texte) - garde)


def tours_a_jouer(lignes, codes_par_id, codes_demandes=None):
    """Rend (tours, manquants) depuis les lignes devops.requirement.test.

    lignes : dictionnaires search_read avec requirement_id ([id, nom] ou
    False) et reference. codes_par_id : {id de requis: code}. tours est une
    liste de {"code", "reference"} sans doublon, triée par code puis
    référence ; manquants liste les codes demandés sans aucune ligne.
    """
    vus = set()
    tours = []
    for ligne in lignes:
        requis = ligne.get("requirement_id")
        id_requis = requis[0] if isinstance(requis, (list, tuple)) else requis
        code = codes_par_id.get(id_requis) or ""
        reference = (ligne.get("reference") or "").strip()
        cle = (code, reference)
        if cle in vus:
            continue
        vus.add(cle)
        tours.append({"code": code, "reference": reference})
    tours.sort(key=lambda t: (t["code"], t["reference"]))
    presents = {t["code"] for t in tours}
    manquants = [c for c in (codes_demandes or []) if c not in presents]
    return tours, manquants


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
    """Rend (login, mot de passe, origine) du compte RPC.

    Les variables nommées par --rpc_login_env et --rpc_password_env
    l'emportent. À défaut des deux, le login du compte navigateur avec le
    mot de passe de la variable --default_password_auth_env. origine dit
    lequel des deux sert, pour l'écran. Lève ValueError, en nommant les
    variables en cause, si une seule des deux variables de l'exécutant est
    posée, ou si aucun mot de passe ne vient de l'environnement :
    --default_password_auth, lu dans argv et qui vaut « admin » par défaut,
    n'est jamais repris.
    """
    environ = os.environ if environ is None else environ
    login = environ.get(config.rpc_login_env or "")
    password = environ.get(config.rpc_password_env or "")
    if login and password:
        return login, password, "environnement"
    if login or password:
        manquante = config.rpc_password_env if login else config.rpc_login_env
        raise ValueError(
            f"variable {manquante} absente ou vide : les deux variables de"
            " l'exécutant vont ensemble"
        )
    pass_env = getattr(config, "default_password_auth_env", None)
    password_web = pass_env and environ.get(pass_env)
    if not password_web:
        raise ValueError(
            f"variables {config.rpc_login_env} et {config.rpc_password_env}"
            " absentes, et aucun mot de passe navigateur par"
            " --default_password_auth_env"
        )
    return config.default_email_auth, password_web, "compte navigateur"


def nom_capture(dossier, code, reference, horodatage):
    """Rend le chemin de la capture d'un tour, sûr comme nom de fichier."""
    brut = f"{code or 'sans_code'}_{reference or 'sans_tour'}_{horodatage}"
    propre = re.sub(r"[^A-Za-z0-9_.-]+", "_", brut)
    return os.path.join(dossier, f"{propre}.png")


def construire_rapport(
    config, debut, duree, resultats, code, erreur_outil=None, alertes=None
):
    """Rend le rapport JSON de la passe ; aucun identifiant de compte.

    `alertes` porte ce qui a raté APRÈS les verdicts — un Onboarding non
    rétabli, un navigateur non fermé : le code de sortie n'en dépend pas,
    les verdicts étant acquis, et le rapport est le seul endroit qu'une
    chaîne d'intégration relise après coup.
    """
    totaux = {r: 0 for r in RESULTATS}
    for ligne in resultats:
        totaux[ligne["resultat"]] = totaux.get(ligne["resultat"], 0) + 1
    return {
        "url": config.url,
        "db": config.db,
        "debut": debut,
        "duree": duree,
        "code_sortie": code,
        "erreur_outil": erreur_outil,
        "alertes": list(alertes or []),
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

    def lire_tours(self, codes=None):
        """Rend (tours, manquants), voir tours_a_jouer."""
        domaine = [("kind", "=", "tour")]
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
        return tours_a_jouer(lignes, codes_par_id, codes)

    def remonter(self, code, reference, resultat, journal, duree):
        return self.appel(
            "devops.requirement.test",
            "record_result",
            [code, "tour", reference, resultat],
            {"log": journal, "duration": duree},
        )


def jouer_un_tour(config, selenium_tool, tour):
    """Joue un tour depuis la page de départ ; rend (ok, message, durée)."""
    debut = time.time()
    try:
        # Un tour précédent interrompu serait sinon repris au chargement.
        selenium_tool.odoo_clear_tour_state()
        selenium_tool.driver.get(f"{config.url}{config.start_path}")
        ok, message = selenium_tool.odoo_run_tour(
            tour["reference"],
            step_delay=config.step_delay,
            timeout=config.tour_timeout,
        )
    except Exception as e:
        ok, message = None, f"erreur du navigateur : {e}"
    return ok, message, round(time.time() - debut, 1)


def capturer(config, selenium_tool, tour):
    """Enregistre une capture d'écran ; rend son chemin, ou None."""
    os.makedirs(config.screenshot_dir, exist_ok=True)
    horodatage = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    chemin = nom_capture(
        config.screenshot_dir, tour["code"], tour["reference"], horodatage
    )
    try:
        if selenium_tool.driver.save_screenshot(chemin):
            return chemin
    except Exception as e:
        print(f"  capture impossible : {e}")
    return None


def jouer(config, selenium_tool, rpc, tours):
    """Joue chaque tour et remonte son verdict ; rend la liste des résultats."""
    resultats = []
    for tour in tours:
        ligne = {
            "code": tour["code"],
            "reference": tour["reference"],
            "resultat": "error",
            "message": "",
            "duree": 0.0,
            "capture": None,
            "remonte": None,
        }
        resultats.append(ligne)
        if not tour["reference"] or not tour["code"]:
            ligne["message"] = (
                "ligne de test sans nom de tour ou sans code de requis :"
                " rien à jouer ni à remonter"
            )
            print(f"[{tour['code']}] ERREUR : {ligne['message']}")
            continue

        print(f"[{tour['code']}] tour « {tour['reference']} »…")
        ok, message, duree = jouer_un_tour(config, selenium_tool, tour)
        ligne["resultat"] = resultat_du_verdict(ok)
        ligne["message"] = tronquer(message)
        ligne["duree"] = duree
        if ok is not True:
            ligne["capture"] = capturer(config, selenium_tool, tour)
        print(f"  {ligne['resultat']} en {duree} s")
        if ok is not True:
            print("  " + ligne["message"].replace("\n", "\n  "))

        if config.no_record:
            continue
        try:
            ligne["remonte"] = bool(
                rpc.remonter(
                    tour["code"],
                    tour["reference"],
                    ligne["resultat"],
                    ligne["message"],
                    duree,
                )
            )
        except Exception as e:
            # Large : une réponse non XML (proxy, page de maintenance) lève
            # ExpatError, et une exception sortie d'ici perdrait les
            # résultats déjà joués.
            ligne["remonte"] = False
            print(f"  verdict NON remonté : {e}")
            continue
        if not ligne["remonte"]:
            print(
                "  verdict NON remonté : record_result ne trouve pas la"
                " ligne de test"
            )
    return resultats


def preparer_session(config, selenium_tool):
    """Ouvre la session navigateur ; rend un message d'erreur, ou None."""
    selenium_tool.driver.get(f"{config.url}/web/login?db={config.db}")
    web_login.run(config, selenium_tool)
    selenium_tool.driver.get(f"{config.url}{config.start_path}")
    if "/web/login" in selenium_tool.driver.current_url:
        return "connexion navigateur refusée"
    # Valeur d'origine, rétablie par restaurer_onboarding en fin de passe.
    # Illisible, elle bloque AVANT toute écriture : couper un réglage dont on
    # ignore la valeur le laisserait coupé pour de bon.
    onboarding = selenium_tool.odoo_read_onboarding()
    if onboarding is None:
        return "Onboarding illisible, la session ne répond pas : rien d'écrit"
    selenium_tool.onboarding_initial = onboarding
    ok, message = selenium_tool.odoo_disable_onboarding()
    if not ok:
        # Bloquant : une visite native achevée par les clics du tour écrit
        # le même « tour succeeded » que le tour joué.
        return f"Onboarding non coupé ({message})"
    return None


def restaurer_onboarding(selenium_tool):
    """Rallume l'Onboarding coupé par preparer_session s'il était allumé.

    Ne fait rien s'il était éteint, ou si preparer_session n'a rien lu ni
    coupé. Rend None, ou le message d'un échec : celui-ci ne change pas
    le code de sortie, les verdicts étant acquis, mais il est écrit sur
    stderr et l'appelant le porte au rapport.
    """
    if getattr(selenium_tool, "onboarding_initial", None) is not True:
        return None
    try:
        selenium_tool.driver.get(
            f"{selenium_tool.config.url}{selenium_tool.config.start_path}"
        )
        selenium_tool.odoo_clear_tour_state()
        ok, message = selenium_tool.odoo_set_onboarding(True)
    except Exception as e:
        ok, message = False, str(e)
    if ok:
        return None
    alerte = f"Onboarding non rétabli ({message}) : à rallumer à la main."
    print(alerte, file=sys.stderr)
    return alerte


def fermer_navigateur(selenium_tool):
    """Ferme le navigateur ; rend None, ou le message d'un échec.

    Un pilote distant (--use_network) lève quand sa session est morte,
    là où les pilotes locaux avalent l'erreur. Sorti d'un « finally »,
    l'échec remplacerait le code de sortie par 1 et empêcherait le
    rapport, alors que les verdicts sont déjà écrits dans Odoo.
    """
    try:
        selenium_tool.quit()
    except Exception as e:
        alerte = f"navigateur non fermé : {e}"
        print(alerte, file=sys.stderr)
        return alerte
    return None


def fill_parser(parser):
    groupe = parser.add_argument_group(title="Tours des requis")
    groupe.add_argument(
        "--db",
        default="",
        help="Base visée ; défaut : la seule base du serveur, s'il n'en a qu'une.",
    )
    groupe.add_argument(
        "--code",
        action="append",
        default=[],
        help=(
            "Code de requis à jouer, répétable ou séparé par des virgules ;"
            " défaut : tous les requis qui ont un tour."
        ),
    )
    groupe.add_argument(
        "--start_path",
        default="/odoo",
        help="Page d'où part chaque tour.",
    )
    groupe.add_argument(
        "--step_delay",
        type=int,
        default=0,
        help=(
            "Pause entre deux étapes, en millisecondes ; 800 garde une"
            " démonstration lisible à l'écran ou en vidéo."
        ),
    )
    groupe.add_argument(
        "--tour_timeout",
        type=float,
        default=180.0,
        help="Secondes accordées à un tour entier.",
    )
    groupe.add_argument(
        "--report_json",
        default="",
        help="Chemin du rapport ; défaut : report_<horodatage>.json sous --screenshot_dir.",
    )
    groupe.add_argument(
        "--screenshot_dir",
        default=os.path.join(".", "screencasts", "requirement_tours"),
        help="Dossier des captures d'écran des tours en échec.",
    )
    groupe.add_argument(
        "--rpc_login_env",
        default=ENV_LOGIN_DEFAUT,
        help="NOM de la variable d'environnement du login RPC de l'exécutant.",
    )
    groupe.add_argument(
        "--rpc_password_env",
        default=ENV_PASSWORD_DEFAUT,
        help="NOM de la variable d'environnement du mot de passe RPC.",
    )
    groupe.add_argument(
        "--no_record",
        action="store_true",
        help="Joue les tours sans écrire les verdicts dans Odoo.",
    )
    # configure() lit config.debug quand --gecko_binary_path est passé, sans
    # que selenium_lib.fill_parser le déclare. default_email_auth à None
    # distingue « non passé » de « admin » pour compute_args.
    parser.set_defaults(debug=None, default_email_auth=None)


def compute_args(args, environ=None):
    """Complète args ; la connexion navigateur suit le compte exécutant.

    Les deux variables de l'exécutant posées et --default_email_auth absent,
    le navigateur se connecte avec ce compte, son mot de passe lu dans la
    variable plutôt que dans argv. Sinon --default_email_auth vaut « admin »
    par défaut, comme dans web_login.
    """
    environ = os.environ if environ is None else environ
    login_runner = environ.get(args.rpc_login_env or "")
    password_runner = environ.get(args.rpc_password_env or "")
    if args.default_email_auth is None:
        if login_runner and password_runner:
            args.default_email_auth = login_runner
            if not args.default_password_auth_env:
                args.default_password_auth_env = args.rpc_password_env
        else:
            args.default_email_auth = "admin"
    args.code = codes_demandes(args.code)
    args.url = args.url.rstrip("/")
    if not args.report_json:
        horodatage = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        args.report_json = os.path.join(
            args.screenshot_dir, f"report_{horodatage}.json"
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


def ligne_manquante(code):
    """Rend la ligne de résultat d'un code demandé qui n'a aucun tour."""
    return {
        "code": code,
        "reference": "",
        "resultat": "error",
        "message": "aucune ligne de test de type tour pour ce requis",
        "duree": 0.0,
        "capture": None,
        "remonte": None,
    }


def preparer_rpc(config):
    """Rend (rpc, tours, manquants, message d'erreur)."""
    config.db, erreur = resoudre_base(config)
    if erreur:
        return None, [], [], erreur
    try:
        login, password, origine = identifiants_rpc(config)
    except ValueError as e:
        return None, [], [], f"identifiants RPC : {e}"
    print(f"RPC sur la base « {config.db} », compte : {origine}.")
    rpc = Rpc(config.url, config.db, login, password)
    try:
        if not rpc.authentifier():
            return None, [], [], "authentification RPC refusée"
        tours, manquants = rpc.lire_tours(config.code)
    except Exception as e:
        # Large : une réponse HTML (proxy, page de maintenance) lève
        # ExpatError, qui n'est ni xmlrpc.client.Error ni OSError ; sortie
        # de main(), elle donnerait le code 1 et aucun rapport.
        return None, [], [], f"RPC impossible : {e}"
    for code in manquants:
        print(f"[{code}] ERREUR : aucune ligne de test de type tour.")
    if not tours and not manquants:
        erreur = "aucune ligne devops.requirement.test de type tour"
        return rpc, tours, manquants, erreur
    return rpc, tours, manquants, None


def construire_parser():
    """Le parseur de la ligne de commande, tel que main() s'en sert."""
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
        # Une abréviation (« --cod ») ne passe pas : un script qui enveloppe
        # le lanceur et réserve des options n'a qu'un nom exact à refuser.
        allow_abbrev=False,
    )
    selenium_lib.fill_parser(parser)
    web_login.fill_parser(parser)
    fill_parser(parser)
    return parser


def main():
    args = construire_parser().parse_args()
    web_login.compute_args(args)
    compute_args(args)
    t0 = time.time()
    debut = datetime.datetime.now().isoformat(timespec="seconds")

    rpc, tours, manquants, erreur = preparer_rpc(args)
    # Un code demandé sans tour reste au bilan, en erreur, sans empêcher de
    # jouer les autres.
    resultats = [ligne_manquante(code) for code in manquants]
    alertes = []
    if tours and not erreur:
        selenium_tool = None
        try:
            selenium_tool = selenium_lib.SeleniumLib(args)
            # BiDi : l'enveloppe de la console se précharge dans chaque page,
            # voir SeleniumLib.odoo_pose_crochet_permanent.
            selenium_tool.bidi = True
            selenium_tool.configure(ignore_open_web=True)
            # web_login.run finit par odoo_profile_click, qui cherche aussi
            # l'entrée « color_scheme.switch », absente de certains montages :
            # sa recherche expire et ferait échouer une connexion réussie.
            # L'Onboarding, son autre entrée, est coupé par RPC plus loin.
            selenium_tool.odoo_profile_click = lambda **_: None
            erreur = preparer_session(args, selenium_tool)
            if not erreur:
                resultats += jouer(args, selenium_tool, rpc, tours)
        except Exception as e:
            erreur = f"erreur de l'outil : {e}"
        finally:
            if selenium_tool is not None and selenium_tool.driver is not None:
                for alerte in (
                    restaurer_onboarding(selenium_tool),
                    fermer_navigateur(selenium_tool),
                ):
                    if alerte:
                        alertes.append(alerte)

    if erreur:
        print(f"ERREUR : {erreur}")
    code = code_de_sortie(resultats, erreur)
    duree = round(time.time() - t0, 1)
    rapport = construire_rapport(
        args, debut, duree, resultats, code, erreur, alertes
    )
    try:
        ecrire_rapport(args.report_json, rapport)
        print(f"Rapport : {args.report_json}")
    except OSError as e:
        print(f"Rapport non écrit : {e}")
    totaux = ", ".join(f"{v} {k}" for k, v in rapport["totaux"].items() if v)
    suite = f", {len(alertes)} alerte(s) au rapport" if alertes else ""
    print(f"Bilan : {totaux or 'aucun tour joué'} → sortie {code}{suite}")
    return code


if __name__ == "__main__":
    sys.exit(main())
