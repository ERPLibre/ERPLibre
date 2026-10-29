#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La synchronisation mobile de bout en bout, sur un téléphone branché.

Les écrans que les tests d'intégration ne voient pas, joués sur l'app de
test (ca.erplibre.home.synctest, construite par -PsyncTest, à côté de l'app
de l'utilisateur qu'elle ne touche pas) contre les Odoo de la course : le
sélecteur de cibles, le bandeau d'une date changée sur le serveur, la saisie
pendant un pull, la note datée créée depuis le calendrier et, sur la 18
seulement, le clavardage, un groupe créé depuis le téléphone, dont le
temps réel passe par le websocket natif, les pièces jointes du clavardage
(fichier, message vocal enregistré au micro, image et message vocal
reçus), les actions sur un message, et la recherche et la boîte de
réception du clavardage (épingle, favori, avis des notifications par
courriel, réponse dans le fil d'une tâche), et ses notifications l'app
fermée, puis leurs actions l'app tuée (répondre, marquer lu, sourdine,
👍, reprise par l'app d'une action que le natif ne peut finir).

Le téléphone joint les serveurs par adb reverse (127.0.0.1 de l'appareil vers
celui de l'hôte) ; la page se pilote par CDP (mobile_sync_cdp.py), les écrans
par de vrais touchers, et la mise en place par window.__erplibreTest, que
seule une construction de développement contient. Pour chaque version, l'app
repart de zéro (pm clear) avec la seule application de ce serveur.

Lancé par ./long_test/mobile_sync.py --appareil, ou seul contre les serveurs
gardés d'une course :

  ./long_test/mobile_sync_device.py cache/mobile_sync/runs/<course>/targets.json
"""

import calendar
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mobile_sync_odoo as odoo  # noqa: E402
from mobile_sync_cdp import Cdp, ErreurPage  # noqa: E402

PAQUET = "ca.erplibre.home.synctest"
# L'app de l'utilisateur, à côté de l'app de test : une course ne la touche
# jamais, et lancer() le vérifie
APP_PERSO = "ca.erplibre.home"
DEVICE_HOOK_API = 8
# La permission des notifications (Android 13+), accordée à l'app de test
# par le scénario des notifications et retirée par rendre()
NOTIFIER = "android.permission.POST_NOTIFICATIONS"
APK_CACHE = odoo.CACHE / "apk"
APK_PRODUIT = Path("android/app/build/outputs/apk/debug/app-debug.apk")
# Ce que le pull compare : write_date, à la seconde
SECONDE_SUIVANTE = 1.1
# L'écart des relevés de toucher_pose : trois identiques couvrent
# l'animation d'un clavier qui s'ouvre
POSE = 0.3
# L'état de l'app selon Android, celui que suit appStateChange
APP_ETAT = "window.Capacitor.Plugins.App.getState()"


def adb(*args, executer=subprocess.run, check=True, binaire=False):
    """La sortie d'une commande adb, en texte (binaire : en octets)."""
    resultat = executer(
        ["adb", *args], capture_output=True, text=not binaire, check=False
    )
    if check and resultat.returncode != 0:
        raise RuntimeError(
            f"adb {' '.join(args)} : {resultat.stderr or resultat.stdout}"
        )
    return resultat.stdout


def maj_app_perso(executer=subprocess.run):
    """La date de dernière mise à jour de APP_PERSO selon dumpsys package
    (lastUpdateTime de sa section « Package [ca.erplibre.home] »), None
    quand elle n'est pas installée. RuntimeError quand elle l'est sans date
    lisible : sans elle, rien ne prouve qu'une course l'a laissée."""
    sortie = adb(
        "shell",
        "dumpsys",
        "package",
        APP_PERSO,
        executer=executer,
        check=False,
    )
    debut = sortie.find(f"Package [{APP_PERSO}]")
    if debut < 0:
        return None
    section = sortie[debut:]
    suivante = section.find("Package [", 1)
    if suivante > 0:
        section = section[:suivante]
    trouve = re.search(r"lastUpdateTime=([^\r\n]+)", section)
    if not trouve:
        raise RuntimeError(
            f"{APP_PERSO} installée, mais dumpsys package ne donne pas sa"
            " lastUpdateTime"
        )
    return trouve.group(1).strip()


def verifier_appareil(
    mobile=odoo.MOBILE, executer=subprocess.run, which=shutil.which
):
    """Ce qui empêche de jouer les scénarios sur le téléphone, chacun avec
    la correction à faire ; vide quand tout est prêt."""
    if not which("adb"):
        return [
            "adb absent : installer les platform-tools Android (paquet adb)"
        ]
    problemes = []
    lignes = adb("devices", executer=executer, check=False).splitlines()[1:]
    etats = [ligne.split("\t")[1] for ligne in lignes if "\t" in ligne]
    if "unauthorized" in etats:
        problemes.append(
            "téléphone non autorisé : accepter le débogage USB sur l'écran du téléphone"
        )
    prets = etats.count("device")
    if prets == 0:
        problemes.append(
            "aucun téléphone prêt (adb devices) : brancher le téléphone, débogage USB activé"
        )
    elif prets > 1 and not os.environ.get("ANDROID_SERIAL"):
        problemes.append(
            f"{prets} appareils branchés : choisir par ANDROID_SERIAL=<numéro de série>"
        )
    if prets >= 1 and not problemes:
        fenetre = adb(
            "shell", "dumpsys", "window", executer=executer, check=False
        )
        if (
            "isKeyguardShowing=true" in fenetre
            or "mShowingLockscreen=true" in fenetre
        ):
            problemes.append(
                "écran du téléphone verrouillé : le déverrouiller"
            )
    if not (Path(mobile) / "android" / "gradlew").exists():
        problemes.append(
            f"{mobile}/android/gradlew absent : lancer « npx cap add android » dans le dépôt mobile"
        )
    return problemes


def cle_apk(mobile=odoo.MOBILE, executer=subprocess.run):
    """La clé de l'APK de test : le commit du dépôt mobile et ses changements
    non commités. Un APK en cache sous cette clé contient ce code-là."""
    morceaux = []
    for commande in (
        ["rev-parse", "HEAD"],
        ["diff", "HEAD"],
        ["status", "--porcelain"],
    ):
        morceaux.append(
            executer(
                ["git", *commande],
                cwd=mobile,
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        )
    return hashlib.sha256("\0".join(morceaux).encode()).hexdigest()[:16]


def construire_apk(mobile=odoo.MOBILE, executer=subprocess.run, journal=print):
    """L'APK de test, construit s'il n'est pas déjà en cache sous sa clé : le
    paquet web en mode développement (qui seul contient window.__erplibreTest),
    puis l'APK de débogage -PsyncTest."""
    APK_CACHE.mkdir(parents=True, exist_ok=True)
    apk = APK_CACHE / f"synctest_{cle_apk(mobile, executer)}.apk"
    if apk.exists():
        return apk
    journal("Construction de l'APK de test (quelques minutes)")
    for commande, dossier in (
        (["npm", "run", "build:dev"], mobile),
        (["npx", "cap", "sync", "android"], mobile),
        (
            ["./gradlew", "assembleDebug", "-PsyncTest"],
            Path(mobile) / "android",
        ),
    ):
        resultat = executer(
            commande, cwd=dossier, capture_output=True, text=True, check=False
        )
        if resultat.returncode != 0:
            raise RuntimeError(
                f"{' '.join(commande)} : {(resultat.stdout + resultat.stderr)[-2000:]}"
            )
    shutil.copyfile(Path(mobile) / APK_PRODUIT, apk)
    return apk


class Odoo:
    """Le serveur d'une cible, vu par un de ses comptes (compte : la clé de
    la cible, "admin" par défaut), en JSON-RPC (/jsonrpc) ; route(),
    telecharger() et televerser() passent par une session web comme le
    navigateur de ce compte."""

    def __init__(self, cible, compte="admin"):
        self.url = cible["url"]
        self.base = cible["database"]
        self.login = cible[compte]["login"]
        self.mot_de_passe = cible[compte]["password"]
        self.session = ""
        self.uid = self.appel(
            "common", "login", [self.base, self.login, self.mot_de_passe]
        )

    def poster(self, chemin, params, entetes=None):
        """Le résultat JSON-RPC de params posté sur chemin, et la réponse
        HTTP ; une erreur d'Odoo lève RuntimeError avec son message."""
        corps = json.dumps(
            {"jsonrpc": "2.0", "method": "call", "params": params}
        ).encode()
        requete = urllib.request.Request(
            f"{self.url}{chemin}",
            corps,
            {"Content-Type": "application/json", **(entetes or {})},
        )
        with urllib.request.urlopen(requete, timeout=60) as reponse:
            contenu = json.load(reponse)
        if "error" in contenu:
            raise RuntimeError(
                contenu["error"].get("data", {}).get("message")
                or contenu["error"]
            )
        # Une route qui ne rend rien répond sans clé result
        return contenu.get("result"), reponse

    def appel(self, service, methode, args):
        return self.poster(
            "/jsonrpc", {"service": service, "method": methode, "args": args}
        )[0]

    def ouvrir_session(self):
        """La session web de ce compte, ouverte au premier appel : son
        cookie (session_id=…)."""
        if not self.session:
            _, reponse = self.poster(
                "/web/session/authenticate",
                {
                    "db": self.base,
                    "login": self.login,
                    "password": self.mot_de_passe,
                },
            )
            self.session = next(
                (
                    c.split(";")[0]
                    for c in reponse.headers.get_all("Set-Cookie") or ()
                    if c.startswith("session_id=")
                ),
                "",
            )
            if not self.session:
                raise RuntimeError(f"aucune session web pour {self.login}")
        return self.session

    def route(self, chemin, params):
        """params postés sur une route web (/mail/message/post) dans la
        session de ce compte."""
        return self.poster(chemin, params, {"Cookie": self.ouvrir_session()})[
            0
        ]

    def telecharger(self, chemin):
        """Les octets de chemin (/web/content/<id>) lus dans la session de
        ce compte."""
        requete = urllib.request.Request(
            f"{self.url}{chemin}", headers={"Cookie": self.ouvrir_session()}
        )
        with urllib.request.urlopen(requete, timeout=60) as reponse:
            return reponse.read()

    def televerser(self, canal, nom, octets, type_mime, voix=False):
        """octets téléversés en pièce jointe en attente du canal, comme le
        compositeur du client web : multipart sur /mail/attachment/upload,
        avec la session de ce compte et le jeton CSRF de sa page de
        connexion ; voice=true pour un message vocal. Rend l'id de la pièce
        jointe et son jeton d'accès, pour attachment_tokens."""
        page = self.telecharger("/web/login").decode()
        trouve = re.search(
            r"name=[\"']csrf_token[\"'][^>]*value=[\"']([^\"']+)"
            r"|csrf_token\s*:\s*[\"']([^\"']+)",
            page,
        )
        if not trouve:
            raise RuntimeError("aucun jeton CSRF sur /web/login")
        champs = {
            "thread_id": str(canal),
            "thread_model": "discuss.channel",
            "is_pending": "true",
            "csrf_token": trouve.group(1) or trouve.group(2),
        }
        if voix:
            champs["voice"] = "true"
        limite = f"ms-{uuid.uuid4().hex}"
        corps = b"".join(
            f'--{limite}\r\nContent-Disposition: form-data; name="{cle}"'
            f"\r\n\r\n{valeur}\r\n".encode()
            for cle, valeur in champs.items()
        )
        corps += (
            f'--{limite}\r\nContent-Disposition: form-data; name="ufile";'
            f' filename="{nom}"\r\nContent-Type: {type_mime}\r\n\r\n'
        ).encode()
        corps += octets + f"\r\n--{limite}--\r\n".encode()
        requete = urllib.request.Request(
            f"{self.url}/mail/attachment/upload",
            corps,
            {
                "Content-Type": f"multipart/form-data; boundary={limite}",
                "Cookie": self.ouvrir_session(),
            },
        )
        with urllib.request.urlopen(requete, timeout=60) as reponse:
            fiche = json.load(reponse)["data"]["ir.attachment"][0]
        return fiche["id"], fiche.get("access_token") or False

    def executer(self, modele, methode, args, kwargs=None):
        return self.appel(
            "object",
            "execute_kw",
            [
                self.base,
                self.uid,
                self.mot_de_passe,
                modele,
                methode,
                args,
                kwargs or {},
            ],
        )

    def creer(self, modele, valeurs):
        return self.executer(modele, "create", [valeurs])

    def ecrire(self, modele, ident, valeurs):
        return self.executer(modele, "write", [[ident], valeurs])

    def lire(self, modele, ident, champs):
        lignes = self.executer(
            modele,
            "search_read",
            [[["id", "=", ident]]],
            {"fields": champs, "context": {"active_test": False}},
        )
        return lignes[0] if lignes else None


@dataclass
class Appareil:
    """Le téléphone pendant une course : ports renvoyés vers les serveurs,
    écran gardé allumé, app de test installée. rendre() défait tout ce que
    preparer() a posé, l'app de l'utilisateur jamais touchée."""

    ports: list
    executer: object = subprocess.run
    port_devtools: int = 0
    reste_allume: str = ""
    cdp: Cdp = None
    poses: list = field(default_factory=list)
    notifications_accordees: bool = False
    exemption_posee: bool = False

    def garder_allume(self):
        """L'écran gardé allumé tant que le téléphone est branché (svc
        power stayon usb), le réglage d'avant noté une fois pour rendre().
        Posé avant la construction de l'APK : un écran qui s'éteint pendant
        ces minutes verrouille un téléphone à code, que rien ici ne
        déverrouille."""
        if not self.reste_allume:
            self.reste_allume = adb(
                "shell",
                "settings",
                "get",
                "global",
                "stay_on_while_plugged_in",
                executer=self.executer,
            ).strip()
        adb("shell", "svc", "power", "stayon", "usb", executer=self.executer)

    def preparer(self, apk):
        adb("install", "-r", str(apk), executer=self.executer)
        self.garder_allume()
        for port in self.ports:
            adb(
                "reverse", f"tcp:{port}", f"tcp:{port}", executer=self.executer
            )
            self.poses.append(port)

    def relancer(self):
        """L'app de test repartie de zéro, sa page jointe par CDP, son hook
        prêt ; une API de hook inconnue arrête la course."""
        if self.cdp:
            self.cdp.fermer()
            self.cdp = None
        adb("shell", "pm", "clear", PAQUET, executer=self.executer)
        adb(
            "shell",
            "monkey",
            "-p",
            PAQUET,
            "-c",
            "android.intent.category.LAUNCHER",
            "1",
            executer=self.executer,
        )
        self.joindre()

    def joindre(self):
        """La page de l'app de test qui tourne, jointe par CDP (son pid
        relu : une app relancée par Android en a un autre), son hook prêt ;
        une API de hook inconnue arrête la course."""
        if self.cdp:
            try:
                self.cdp.fermer()
            except OSError:
                # La page d'un processus mort : sa prise est déjà fermée
                pass
            self.cdp = None
        pid = ""
        fin = time.monotonic() + 30
        while not pid and time.monotonic() < fin:
            time.sleep(0.5)
            pid = adb(
                "shell", "pidof", PAQUET, executer=self.executer, check=False
            ).strip()
        if not pid:
            raise RuntimeError(f"{PAQUET} ne démarre pas")
        if self.port_devtools:
            adb(
                "forward",
                "--remove",
                f"tcp:{self.port_devtools}",
                executer=self.executer,
                check=False,
            )
        self.port_devtools = odoo.port_libre()
        adb(
            "forward",
            f"tcp:{self.port_devtools}",
            f"localabstract:webview_devtools_remote_{pid}",
            executer=self.executer,
        )
        fin = time.monotonic() + 60
        while True:
            try:
                self.cdp = Cdp(self.port_devtools)
                api = self.cdp.attendre(
                    "window.__erplibreTest && window.__erplibreTest.api",
                    delai=60,
                )
                break
            except (OSError, StopIteration, ValueError):
                if time.monotonic() > fin:
                    raise RuntimeError(
                        "la page de l'app de test ne répond pas par CDP"
                    )
                time.sleep(1)
        if api != DEVICE_HOOK_API:
            raise RuntimeError(
                f"hook de test d'API {api}, ce lanceur connaît l'API {DEVICE_HOOK_API}"
            )

    def autoriser_notifications(self):
        """POST_NOTIFICATIONS accordée à l'app de test (pm clear la retire :
        à refaire après chaque relancer()). Avant Android 13 (API 33) la
        permission n'existe pas et les notifications sont permises : rien
        n'est accordé."""
        sdk = adb(
            "shell",
            "getprop",
            "ro.build.version.sdk",
            executer=self.executer,
        ).strip()
        if not sdk.isdigit() or int(sdk) < 33:
            return
        adb("shell", "pm", "grant", PAQUET, NOTIFIER, executer=self.executer)
        self.notifications_accordees = True

    def exempter_batterie(self):
        """L'app de test dans la liste d'exemption de l'optimisation de
        batterie (deviceidle) ; rendre() l'en retire, sauf si elle y était
        déjà avant la course."""
        liste = adb(
            "shell",
            "dumpsys",
            "deviceidle",
            "whitelist",
            executer=self.executer,
        )
        if re.search(rf",{re.escape(PAQUET)},", liste):
            return
        adb(
            "shell",
            "dumpsys",
            "deviceidle",
            "whitelist",
            f"+{PAQUET}",
            executer=self.executer,
        )
        self.exemption_posee = True

    def capture(self, chemin):
        Path(chemin).write_bytes(
            adb(
                "exec-out",
                "screencap",
                "-p",
                executer=self.executer,
                binaire=True,
            )
        )

    def rendre(self):
        if self.cdp:
            self.cdp.fermer()
        adb(
            "shell",
            "am",
            "force-stop",
            PAQUET,
            executer=self.executer,
            check=False,
        )
        if self.notifications_accordees:
            adb(
                "shell",
                "pm",
                "revoke",
                PAQUET,
                NOTIFIER,
                executer=self.executer,
                check=False,
            )
            self.notifications_accordees = False
        if self.exemption_posee:
            adb(
                "shell",
                "dumpsys",
                "deviceidle",
                "whitelist",
                f"-{PAQUET}",
                executer=self.executer,
                check=False,
            )
            self.exemption_posee = False
        for port in self.poses:
            adb(
                "reverse",
                "--remove",
                f"tcp:{port}",
                executer=self.executer,
                check=False,
            )
        if self.port_devtools:
            adb(
                "forward",
                "--remove",
                f"tcp:{self.port_devtools}",
                executer=self.executer,
                check=False,
            )
        if self.reste_allume and self.reste_allume != "null":
            adb(
                "shell",
                "settings",
                "put",
                "global",
                "stay_on_while_plugged_in",
                self.reste_allume,
                executer=self.executer,
                check=False,
            )


# ─── Scénarios ────────────────────────────────────────────────────────────────


def js(valeur):
    return json.dumps(valeur, ensure_ascii=False)


@dataclass
class Contexte:
    """Ce qu'un scénario reçoit : la page, le serveur et son application."""

    cdp: Cdp
    odoo: Odoo
    version: int
    config_id: str
    cible: dict = field(default_factory=dict)
    appareil: Appareil = None
    compteur: int = 0
    repertoire: Path = None

    def unique(self, libelle):
        self.compteur += 1
        return f"ms-dev-{os.getpid()}-{int(time.time())}-{self.compteur}-{libelle}"

    def hook(self, appel):
        return self.cdp.evaluer(f"window.__erplibreTest.{appel}")

    def nouvelle_note(self, titre, paragraphes=(), jour=None):
        ident = self.unique("note")
        entrees = []
        if jour:
            entrees.append(
                {
                    "id": f"{ident}-d",
                    "type": "date",
                    "params": {"date": None, "_jour": jour},
                }
            )
        entrees += [
            {
                "id": f"{ident}-t{i}",
                "type": "text",
                "params": {"text": t, "readonly": False},
            }
            for i, t in enumerate(paragraphes)
        ]
        note = {
            "id": ident,
            "title": titre,
            "done": False,
            "archived": False,
            "pinned": False,
            "tags": [],
            "entries": entrees,
        }
        # La date de l'entrée : 9 h à l'heure du téléphone, comme l'app l'écrit
        self.cdp.evaluer(
            f"(() => {{ const n = {js(note)}; for (const e of n.entries) if (e.params._jour) "
            "e.params = { date: new Date(e.params._jour + 'T09:00:00').toISOString() };"
            " return window.__erplibreTest.addNote(n); })()"
        )
        return ident

    def ouvrir(self, url, attendu):
        self.hook(f"open({js(url)})")
        self.cdp.attendre(f"!!document.querySelector({js(attendu)})")

    def lien(self, note, sorte="create", delai=30):
        return self.cdp.attendre(
            f"window.__erplibreTest.links({js(note)}).then(ls => ls.find(l => l.kind === {js(sorte)}) || null)",
            delai=delai,
        )

    def jour_note(self, note):
        return self.cdp.evaluer(
            f"window.__erplibreTest.note({js(note)}).then(n => {{ const e = n.entries.find(e => e.type === 'date');"
            " if (!e) return null; const d = new Date(e.params.date);"
            " return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0'); })"
        )

    def echeance(self, jour):
        """La valeur Odoo d'une échéance de tâche au jour donné : Date en 16, Datetime en 17+."""
        return jour if self.version < 17 else f"{jour} 12:00:00"

    def selecteur_pret(self):
        self.cdp.toucher(".breadcrumb__sync-btn", 1.4)
        self.cdp.attendre(
            "(() => { const p = document.querySelector('.breadcrumb__config-picker');"
            " return !!p && !p.innerText.includes('Vérification du serveur'); })()"
        )

    def cocher(self, selecteur):
        if not self.cdp.evaluer(
            f"document.querySelector({js(selecteur)}).checked"
        ):
            self.cdp.toucher(selecteur)
        self.cdp.attendre(
            f"document.querySelector({js(selecteur)}).checked", delai=5
        )

    def marquer(self, selecteur, texte, ancetre):
        """Un sélecteur de l'ancêtre ancetre du premier élément de selecteur
        dont le texte est texte : cet ancêtre reçoit un attribut
        data-ms-marque, que toucher() retrouve."""
        self.compteur += 1
        marque = str(self.compteur)
        self.cdp.attendre(
            f"(() => {{ const e = [...document.querySelectorAll({js(selecteur)})]"
            f".find(e => e.innerText.trim() === {js(texte)}); if (!e) return false;"
            f" e.closest({js(ancetre)}).dataset.msMarque = {js(marque)}; return true; }})()"
        )
        return f'[data-ms-marque="{marque}"]'

    def capturer(self, nom, voir=None):
        """Une capture d'écran gardée dans le répertoire de la course,
        appareil_<version>_<nom>.png, l'élément de voir d'abord amené au
        milieu de l'écran ; son chemin."""
        if voir:
            self.cdp.evaluer(
                f"document.querySelector({js(voir)})"
                ".scrollIntoView({block: 'center'})"
            )
            time.sleep(POSE)
        chemin = Path(self.repertoire) / f"appareil_{self.version}_{nom}.png"
        self.appareil.capture(chemin)
        return chemin

    def toucher_pose(self, selecteur, delai=10):
        """Touche selecteur une fois l'écran posé (poser)."""
        self.poser(selecteur, delai)
        self.cdp.toucher(selecteur)

    def toucher_maintenir(self, selecteur, ms=700, delai=10):
        """Un appui long sur selecteur une fois l'écran posé (poser) : le
        doigt posé en son centre (Input.dispatchTouchEvent touchStart),
        gardé ms millisecondes, puis levé (touchEnd). Les pointerdown et
        pointerup qui en naissent sont ceux d'un vrai doigt."""
        self.poser(selecteur, delai)
        self.cdp.toucher(selecteur, ms / 1000)

    def poser(self, selecteur, delai=10):
        """Attend que selecteur soit posé : son centre au même endroit trois
        relevés de suite, POSE secondes d'écart, et l'élément lui-même sous
        ce point. Un clavier qui s'ouvre redimensionne la page pendant son
        animation, et un doigt posé avant la fin tombe là où le bouton
        n'est plus."""
        sonde = (
            f"(() => {{ const e = document.querySelector({js(selecteur)});"
            " if (!e) return null; e.scrollIntoView({block: 'center'});"
            " const r = e.getBoundingClientRect(); const x = r.x + r.width / 2,"
            " y = r.y + r.height / 2; const sous = document.elementFromPoint(x, y);"
            " return [Math.round(x), Math.round(y), innerHeight,"
            " !!sous && (sous === e || e.contains(sous))]; })()"
        )
        fin = time.monotonic() + delai
        releves = []
        while True:
            releves = (releves + [self.cdp.evaluer(sonde)])[-3:]
            dernier = releves[-1]
            if (
                len(releves) == 3
                and dernier
                and dernier[3]
                and all(r == dernier for r in releves)
            ):
                break
            if time.monotonic() > fin:
                raise TimeoutError(
                    f"{selecteur} jamais posé en {delai} s : {releves}"
                )
            time.sleep(POSE)

    def choisir(self, selecteur, valeur):
        self.cdp.evaluer(
            f"(() => {{ const s = document.querySelector({js(selecteur)}); s.value = {js(str(valeur))};"
            " s.dispatchEvent(new Event('change', {bubbles: true})); })()"
        )


def scenario_selecteur(ctx):
    """Le sélecteur de cibles : la note part comme tâche du projet choisi."""
    projet = ctx.odoo.creer("project.project", {"name": ctx.unique("projet")})
    note = ctx.nouvelle_note(
        "Depuis le selecteur", ["Envoyee par le selecteur"]
    )
    ctx.ouvrir(f"/note/{note}", ".breadcrumb__sync-btn")
    ctx.selecteur_pret()
    ctx.cocher(".breadcrumb__config-option input")
    ctx.cocher(".breadcrumb__config-kind-label input")
    ctx.cdp.attendre(
        f"!!document.querySelector('#sync-project-0 option[value=\"{projet}\"]')"
    )
    ctx.choisir("#sync-project-0", projet)
    ctx.cdp.toucher(".breadcrumb__config-confirm")
    lien = ctx.lien(note)
    tache = ctx.odoo.lire(
        "project.task", lien["resId"], ["project_id", "description"]
    )
    assert tache["project_id"][0] == projet, tache
    assert (
        f"erplibre-mobile:{lien['clientUuid']}" in tache["description"]
    ), tache["description"]


def scenario_bandeau_date(ctx):
    """Le bandeau d'une date changée sur le serveur : acceptée, la note la prend."""
    note = ctx.nouvelle_note("Date proposee", ["Texte"], jour="2026-11-02")
    ctx.hook(f"sendAsTask({js(note)}, {js(ctx.config_id)}, null)")
    tache = ctx.lien(note)["resId"]
    time.sleep(SECONDE_SUIVANTE)
    ctx.odoo.ecrire(
        "project.task", tache, {"date_deadline": ctx.echeance("2026-11-09")}
    )
    ctx.hook("syncAll()")
    ctx.ouvrir(f"/note/{note}", ".note__date-proposal-btn")
    texte = ctx.cdp.evaluer(
        "document.querySelector('.note__date-proposal-btn').parentElement.parentElement.innerText"
    )
    assert "9 novembre 2026" in texte, texte
    assert ctx.jour_note(note) == "2026-11-02"
    ctx.cdp.toucher(".note__date-proposal-btn")
    ctx.cdp.attendre("!document.querySelector('.note__date-proposal-btn')")
    assert ctx.jour_note(note) == "2026-11-09", ctx.jour_note(note)


def scenario_saisie_pendant_pull(ctx):
    """Des frappes pendant un pull qui change le titre : aucune perdue, le
    titre du serveur affiché, les deux envoyés ensuite."""
    note = ctx.nouvelle_note("Titre de l'app", ["Avant"])
    ctx.hook(f"sendAsTask({js(note)}, {js(ctx.config_id)}, null)")
    tache = ctx.lien(note)["resId"]
    time.sleep(SECONDE_SUIVANTE)
    ctx.odoo.ecrire("project.task", tache, {"name": "Titre du serveur"})
    champ = "textarea:not(#note__title)"
    ctx.ouvrir(f"/note/{note}", champ)
    ctx.cdp.toucher(champ)
    ctx.cdp.evaluer(
        f"(() => {{ const t = document.querySelector({js(champ)}); t.focus(); t.setSelectionRange(t.value.length, t.value.length); }})()"
    )
    ctx.cdp.evaluer(
        "window.__pull = window.__erplibreTest.syncAll().then(() => true); true"
    )
    tape = ""
    for lettre in "abcdefghijklmnop":
        ctx.cdp.taper(lettre)
        tape += lettre
        time.sleep(0.05)
    ctx.cdp.attendre("window.__pull")
    ctx.cdp.taper("Z")
    tape += "Z"
    attendu = "Avant" + tape
    ctx.cdp.attendre(
        f"document.querySelector('#note__title').value === {js('Titre du serveur')}",
        delai=10,
    )
    valeur = ctx.cdp.attendre(
        f"(() => {{ const v = document.querySelector({js(champ)}).value; return v === {js(attendu)} ? v : null; }})()",
        delai=10,
    )
    assert valeur == attendu
    # Le dernier caractère tapé enregistré, puis envoyé avec le titre tiré
    ctx.cdp.attendre(
        f"window.__erplibreTest.note({js(note)}).then(n => n.entries.some(e => e.params.text === {js(attendu)}))",
        delai=10,
    )
    ctx.hook("syncAll()")
    tache_lue = ctx.odoo.lire("project.task", tache, ["name", "description"])
    assert tache_lue["name"] == "Titre du serveur", tache_lue
    assert attendu in tache_lue["description"], tache_lue["description"]


def scenario_calendrier(ctx):
    """La note créée sur un jour du calendrier : datée de ce jour, et son
    activité, due ce jour, créée sur le contact choisi."""
    contact_nom = ctx.unique("contact")
    contact = ctx.odoo.creer("res.partner", {"name": contact_nom})
    ctx.ouvrir("/activities", ".activity-calendar__new")
    jour = ctx.cdp.evaluer(
        "(() => { const d = new Date(); return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-28'; })()"
    )
    ctx.cdp.toucher(f"button[aria-label='{jour}']")
    ctx.cdp.attendre(
        f"document.querySelector(\"button[aria-label='{jour}']\").getAttribute('aria-pressed') === 'true'"
    )
    ctx.cdp.toucher(".activity-calendar__new")
    ctx.cdp.attendre(
        "(() => { const p = document.querySelector('.breadcrumb__config-picker');"
        " return !!p && !!document.querySelector('#sync-act-deadline-0-0') && !p.innerText.includes('Vérification du serveur'); })()"
    )
    note = ctx.cdp.evaluer("location.pathname.split('/').pop()")
    assert ctx.jour_note(note) == jour, ctx.jour_note(note)
    assert (
        ctx.cdp.evaluer(
            "document.querySelector('#sync-act-deadline-0-0').value"
        )
        == jour
    )
    ctx.cocher(".breadcrumb__config-option input")
    filtre = "#sync-act-record-0-0"
    ctx.cdp.evaluer(
        f"(() => {{ const f = document.querySelector({js(filtre)}).previousElementSibling; f.value = {js(contact_nom)};"
        " f.dispatchEvent(new Event('input', {bubbles: true})); })()"
    )
    ctx.cdp.attendre(
        f"!!document.querySelector('{filtre} option[value=\"{contact}\"]')"
    )
    ctx.choisir(filtre, contact)
    ctx.cdp.toucher(".breadcrumb__config-confirm")
    lien = ctx.lien(note, sorte="activity")
    activite = ctx.odoo.lire(
        "mail.activity",
        lien["resId"],
        ["res_model", "res_id", "date_deadline"],
    )
    assert activite == {
        "id": lien["resId"],
        "res_model": "res.partner",
        "res_id": contact,
        "date_deadline": jour,
    }, activite


# La tuile mène à la liste en 2 s au plus : la liste se rend depuis le cache
TUILE_VERS_LISTE = 2.0
# Et à la saisie dans la conversation en 2 s au plus, la liste traversée
TUILE_VERS_SAISIE = 2.0
CANAL_CHAT = "ms chat"
# Les messages que le fil rend à l'ouverture (THREAD_WINDOW de l'app) : un
# message plus ancien que ce nombre est hors de la première fenêtre
FENETRE_FIL = 100
# Le temps qu'une lecture partie du téléphone met au plus à atteindre le
# serveur : la lecture enregistrée y reste inchangée pendant ce délai
LECTURE_DELAI = 10
# Vrai quand la zone de saisie de la conversation ouverte prend le focus
SAISIE_PRETE = (
    "(() => { const i = document.querySelector('.chat-thread__input');"
    " if (!i) return false; i.focus(); return document.activeElement === i; })()"
)
# La place de la zone de saisie, en px CSS : [haut de la barre de navigation
# moins bas de la saisie (null si la barre n'est pas affichée), bas de la
# partie visible de la page moins bas de la saisie, hauteur de la page].
# Négatif, la barre ou le clavier couvre la saisie.
PLACE_SAISIE = (
    "(() => { const c = document.querySelector('.chat-thread__composer');"
    " const n = document.querySelector('nav#nav'); if (!c) return null;"
    " const bas = c.getBoundingClientRect().bottom;"
    " const barre = n && n.getClientRects().length"
    " ? Math.round(n.getBoundingClientRect().top - bas) : null;"
    " const vue = window.visualViewport;"
    " const visible = vue ? vue.offsetTop + vue.height : innerHeight;"
    " return [barre, Math.round(visible - bas), innerHeight]; })()"
)


def scenario_clavardage(ctx):
    """Le clavardage : la tuile 💬 mène à la liste en TUILE_VERS_LISTE au
    plus, et à la saisie dans « ms chat », la conversation de l'échange, en
    TUILE_VERS_SAISIE au plus ; le message tapé arrive une fois sur le
    serveur, et la réponse de chat_user s'affiche dans la conversation par
    le websocket natif. La source est ajoutée l'app ouverte : son bus part
    de l'ajout même, sans retour au premier plan. Rend les deux durées
    mesurées."""
    pair = Odoo(ctx.cible, "chat")
    canaux = pair.executer(
        "discuss.channel",
        "search",
        [[["name", "=", CANAL_CHAT], ["channel_type", "=", "group"]]],
    )
    assert canaux, f"aucun groupe « {CANAL_CHAT} » pour chat_user"
    canal = canaux[0]
    ctx.hook(f"chatLoad({js(ctx.config_id)})")
    ctx.ouvrir("/", ".home-action-card")
    tuile = ctx.marquer(".home-action-card__icon", "💬", ".home-action-card")
    debut = time.monotonic()
    ctx.cdp.toucher(tuile)
    ctx.cdp.attendre("!!document.querySelector('.chat-list__row')", pas=0.05)
    duree = time.monotonic() - debut
    assert duree <= TUILE_VERS_LISTE, f"tuile → liste : {duree:.2f} s"

    ctx.cdp.toucher(
        ctx.marquer(".chat-list__title", CANAL_CHAT, ".chat-list__row")
    )
    ctx.cdp.attendre(
        f"location.pathname.endsWith('/{canal}') && {SAISIE_PRETE}",
        pas=0.05,
    )
    saisie = time.monotonic() - debut
    assert saisie <= TUILE_VERS_SAISIE, f"tuile → saisie : {saisie:.2f} s"
    mesure = echanger(ctx, pair, canal)
    return (
        f"tuile → liste {duree:.2f} s, tuile → saisie {saisie:.2f} s, {mesure}"
    )


# L'écart le plus grand entre le bas de la saisie et le haut de la barre de
# navigation, en px CSS : la marge du fil (0,5 rem, 8 px) et un peu de jeu.
# Au-delà, une bande vide sépare la saisie de la barre : la cellule du fil
# a défilé sous elle
ECART_BARRE_MAX = 16


def place_saisie(ctx, delai=10):
    """PLACE_SAISIE une fois la page posée (trois relevés identiques, POSE
    secondes d'écart), après avoir vérifié que ni la barre ni le bord de la
    partie visible ne couvrent la saisie, et que la saisie se tient au plus
    ECART_BARRE_MAX px au-dessus de la barre."""
    fin = time.monotonic() + delai
    releves = []
    while True:
        releves = (releves + [ctx.cdp.evaluer(PLACE_SAISIE)])[-3:]
        if (
            len(releves) == 3
            and releves[-1]
            and all(r == releves[-1] for r in releves)
        ):
            break
        if time.monotonic() > fin:
            raise TimeoutError(f"saisie jamais posée en {delai} s : {releves}")
        time.sleep(POSE)
    barre, visible, hauteur = releves[-1]
    assert (
        barre is None or barre >= 0
    ), f"la barre couvre la saisie : {barre} px"
    assert (
        barre is None or barre <= ECART_BARRE_MAX
    ), f"bande de {barre} px entre la saisie et la barre"
    assert visible >= 0, f"la saisie sort de l'écran : {visible} px"
    return barre, visible, hauteur


def clavier_affiche(ctx):
    """Vrai quand Android affiche la fenêtre du clavier."""
    sortie = adb(
        "shell",
        "dumpsys",
        "window",
        "InputMethod",
        executer=ctx.appareil.executer,
    )
    return "isVisible=true" in sortie


# Envois de texte de suite dans echanger : le clavier reste ouvert entre eux
ENVOIS_CLAVIER = 3
# Vrai quand la zone de saisie de la conversation a le focus
SAISIE_ACTIVE = (
    "document.activeElement === document.querySelector('.chat-thread__input')"
)


def envoyer_texte(ctx, canal):
    """Un texte unique tapé dans la saisie qui a le focus et envoyé par ➤ ;
    rendu une fois marqué envoyé. Marqué envoyé, le message a sa réponse du
    serveur et quitte l'outbox, qui ne le poste plus : le compte du serveur
    est alors définitif."""
    texte = ctx.unique("message")
    ctx.cdp.taper(texte)
    ctx.cdp.attendre(
        f"document.querySelector('.chat-thread__input').value === {js(texte)}",
        delai=5,
    )
    ctx.toucher_pose(".chat-thread__send")
    ctx.cdp.attendre(
        f"window.__erplibreTest.chatMessages({js(ctx.config_id)}, {canal})"
        f".then(ms => ms.some(m => m.body.includes({js(texte)}) && m.status === 'sent'))",
        delai=30,
    )
    return texte


def echanger(ctx, pair, canal):
    """Dans la conversation canal ouverte : la saisie se tient au-dessus de
    la barre de navigation, clavier fermé puis ouvert ; ENVOIS_CLAVIER
    messages tapés et envoyés de suite arrivent chacun une fois sur le
    serveur, le clavier restant ouvert et la saisie gardant le focus d'un
    envoi à l'autre ; puis la réponse de pair (chat_user) s'affiche dans le
    fil par le websocket natif. Rend la place mesurée de la saisie."""
    ctx.cdp.evaluer("document.activeElement && document.activeElement.blur()")
    ferme = place_saisie(ctx)
    # Touchée à l'endroit où elle s'affiche : un élément couvert ne la reçoit pas
    ctx.toucher_pose(".chat-thread__input")
    fin = time.monotonic() + 10
    while not clavier_affiche(ctx):
        if time.monotonic() > fin:
            raise TimeoutError("le clavier ne s'ouvre pas sur la saisie")
        time.sleep(POSE)
    # La page se réduit au-dessus du clavier : place_saisie vérifie la saisie
    # dans la partie visible et au-dessus de la barre
    ouvert = place_saisie(ctx)
    mesure = (
        f"saisie à {ferme[0]} px au-dessus de la barre clavier fermé,"
        f" {ouvert[0] if ouvert[0] is not None else '—'} px clavier ouvert"
        f" (bas visible à {ferme[1]} puis {ouvert[1]} px,"
        f" page de {ferme[2]} puis {ouvert[2]} px)"
    )
    # Un toucher par CDP ne donne pas toujours le focus, qu'insertText suit
    ctx.cdp.evaluer("document.querySelector('.chat-thread__input').focus()")
    textes = []
    for rang in range(ENVOIS_CLAVIER):
        if rang:
            # Le clavier reste ouvert d'un envoi à l'autre, la saisie gardant
            # le focus : rien ne le redonne ici
            time.sleep(POSE)
            assert clavier_affiche(ctx), f"clavier fermé après l'envoi {rang}"
            assert ctx.cdp.evaluer(
                SAISIE_ACTIVE
            ), f"saisie sans focus après l'envoi {rang}"
        textes.append(envoyer_texte(ctx, canal))
    time.sleep(POSE)
    assert clavier_affiche(
        ctx
    ), f"clavier fermé après l'envoi {ENVOIS_CLAVIER}"
    mesure += f", clavier ouvert sur {ENVOIS_CLAVIER} envois"

    def recus(contenu):
        return pair.executer(
            "mail.message",
            "search_count",
            [
                [
                    ["model", "=", "discuss.channel"],
                    ["res_id", "=", canal],
                    ["message_type", "=", "comment"],
                    ["body", "ilike", contenu],
                ]
            ],
        )

    for envoye in textes:
        assert recus(envoye) == 1, f"{envoye} reçu {recus(envoye)} fois"

    reponse = ctx.unique("reponse")
    ctx.cdp.attendre(f"{APP_ETAT}.then(s => s.isActive)", delai=5)
    pair.route(
        "/mail/message/post",
        {
            "thread_model": "discuss.channel",
            "thread_id": canal,
            "post_data": {
                "body": reponse,
                "message_type": "comment",
                "subtype_xmlid": "mail.mt_comment",
            },
        },
    )
    ctx.cdp.attendre(
        "[...document.querySelectorAll('.chat-thread__body')]"
        f".some(e => e.innerText.includes({js(reponse)}))",
        delai=20,
    )
    return mesure


def scenario_groupe(ctx):
    """Un groupe créé depuis le téléphone avec chat_user : il existe une
    fois sur le serveur sous son nom, sa fiche nomme chat_user parmi les
    membres, et l'échange s'y fait dans les deux sens (echanger). Rend la
    place mesurée de la saisie."""
    pair = Odoo(ctx.cible, "chat")
    partenaire = pair.lire("res.users", pair.uid, ["partner_id"])[
        "partner_id"
    ][0]
    nom = ctx.unique("groupe")
    ctx.hook(f"chatLoad({js(ctx.config_id)})")
    canal = ctx.hook(
        f"chatNewGroup({js(ctx.config_id)}, {js([partenaire])}, {js(nom)})"
    )
    assert isinstance(canal, int) and canal > 0, f"groupe non créé : {canal}"
    groupes = ctx.odoo.executer(
        "discuss.channel",
        "search_read",
        [[["name", "=", nom]]],
        {"fields": ["channel_type", "channel_partner_ids"]},
    )
    assert [g["id"] for g in groupes] == [canal], groupes
    assert groupes[0]["channel_type"] == "group", groupes
    assert partenaire in groupes[0]["channel_partner_ids"], groupes

    ctx.hook(f"chatOpenInfo({js(ctx.config_id)}, {canal})")
    ctx.cdp.attendre(
        "[...document.querySelectorAll('.chat-info__member-name')]"
        ".some(e => e.innerText.includes('MS Chat'))",
        delai=20,
    )
    ctx.hook(
        f"open('/chat/' + encodeURIComponent({js(ctx.config_id)}) + '/{canal}')"
    )
    ctx.cdp.attendre(
        f"location.pathname.endsWith('/{canal}') && {SAISIE_PRETE}", delai=20
    )
    return echanger(ctx, pair, canal)


# L'image déposée sur le téléphone et envoyée par chat_user : un dégradé
# inventé (voir fixtures/PROVENANCE.md)
PHOTO = (
    Path(__file__).resolve().parent
    / "mobile_sync"
    / "fixtures"
    / "photo-2400x1600.jpg"
)
# Où le fichier est déposé, sous files/ de l'app (Directory.Data)
DEPOT = "ms_test"
# La durée d'un message vocal enregistré au micro du téléphone, en secondes
VOIX = 3
# La place des boutons 📎 et 🎤 de la saisie, en px CSS, comme PLACE_SAISIE :
# par bouton, [haut de la barre de navigation moins bas du bouton (null si
# la barre n'est pas affichée), bas de la partie visible moins bas du bouton]
PLACE_BOUTONS = (
    "(() => { const n = document.querySelector('nav#nav');"
    " const vue = window.visualViewport;"
    " const visible = vue ? vue.offsetTop + vue.height : innerHeight;"
    " return ['.chat-thread__attach', '.chat-thread__mic'].map(s => {"
    " const b = document.querySelector(s); if (!b) return null;"
    " const bas = b.getBoundingClientRect().bottom;"
    " return [n && n.getClientRects().length"
    " ? Math.round(n.getBoundingClientRect().top - bas) : null,"
    " Math.round(visible - bas)]; }); })()"
)


def deposer(ctx, source, chemin):
    """source (un fichier de l'hôte) copié à chemin sous files/ de l'app de
    test : poussé dans /data/local/tmp, copié par run-as (seule l'app lit
    son dossier), puis effacé de /data/local/tmp."""
    executer = ctx.appareil.executer
    temporaire = f"/data/local/tmp/{uuid.uuid4().hex}"
    adb("push", str(source), temporaire, executer=executer)
    try:
        dossier = chemin.rsplit("/", 1)[0]
        adb(
            "shell",
            f"run-as {PAQUET} sh -c 'mkdir -p files/{dossier}"
            f" && cp {temporaire} files/{chemin}'",
            executer=executer,
        )
    finally:
        adb("shell", "rm", "-f", temporaire, executer=executer, check=False)


def attendre_envoye(ctx, canal, client_uuid, delai=60):
    """Attend que le message de client_uuid soit marqué envoyé : il a sa
    réponse du serveur et a quitté l'outbox ; rend son id sur le serveur."""
    return ctx.cdp.attendre(
        f"window.__erplibreTest.chatMessages({js(ctx.config_id)}, {canal})"
        f".then(ms => {{ const m = ms.find(m => m.clientUuid === {js(client_uuid)});"
        " return !!m && m.status === 'sent' && m.messageId; })",
        delai=delai,
    )


def poster_avec(pair, canal, texte, pieces):
    """Poste texte avec les pièces jointes (id, jeton) téléversées par pair."""
    pair.route(
        "/mail/message/post",
        {
            "thread_model": "discuss.channel",
            "thread_id": canal,
            "post_data": {
                "body": texte,
                "message_type": "comment",
                "subtype_xmlid": "mail.mt_comment",
                "attachment_ids": [ident for ident, _ in pieces],
            },
            "attachment_tokens": [jeton for _, jeton in pieces],
        },
    )


def scenario_pieces_jointes(ctx):
    """Les pièces jointes du clavardage, dans un groupe neuf avec chat_user.
    Un fichier déposé dans le dossier de l'app part comme le compositeur
    l'envoie après le sélecteur (chatSendFile) et arrive une fois, ses
    octets intacts par le module. Les boutons 📎 et 🎤 se tiennent
    au-dessus de la barre de navigation. Un toucher sur 🎤, VOIX secondes,
    un second toucher : le serveur reçoit un MP3 (audio/mpeg) marqué
    vocal, ce qui prouve que le worker d'encodage se charge dans l'APK.
    L'image de chat_user s'affiche en aperçu et son toucher ouvre la
    visionneuse ; le message vocal de chat_user joue par le lecteur du fil
    (événement playing, position qui avance). La caméra et les sélecteurs
    du système ne sont pas pilotés : leur interface est celle du
    fabricant. Rend la taille des fichiers et la position de lecture."""
    pair = Odoo(ctx.cible, "chat")
    moi = ctx.odoo.lire("res.users", ctx.odoo.uid, ["partner_id"])[
        "partner_id"
    ][0]
    nom = ctx.unique("pieces")
    pair.executer(
        "discuss.channel",
        "create_group",
        [],
        {"partners_to": [moi], "name": nom},
    )
    canal = pair.executer("discuss.channel", "search", [[["name", "=", nom]]])[
        0
    ]
    ctx.hook(f"chatLoad({js(ctx.config_id)})")

    photo = PHOTO.read_bytes()
    empreinte = hashlib.sha1(photo).hexdigest()
    nom_photo = f"{ctx.unique('photo')}.jpg"
    deposer(ctx, PHOTO, f"{DEPOT}/{nom_photo}")
    envoi = ctx.hook(
        f"chatSendFile({js(ctx.config_id)}, {canal},"
        f" {js(f'{DEPOT}/{nom_photo}')}, {js(nom_photo)}, 'image/jpeg')"
    )
    message = attendre_envoye(ctx, canal, envoi)
    pieces = ctx.odoo.executer(
        "ir.attachment",
        "search_read",
        [[["name", "=", nom_photo]]],
        {"fields": ["res_model", "res_id", "checksum", "file_size"]},
    )
    assert len(pieces) == 1, pieces
    assert pieces[0]["res_model"] == "discuss.channel", pieces
    assert pieces[0]["res_id"] == canal, pieces
    assert pieces[0]["checksum"] == empreinte, pieces
    lu = ctx.odoo.lire("mail.message", message, ["attachment_ids"])
    assert lu["attachment_ids"] == [pieces[0]["id"]], lu

    ctx.hook(
        f"open('/chat/' + encodeURIComponent({js(ctx.config_id)}) + '/{canal}')"
    )
    ctx.cdp.attendre(
        f"location.pathname.endsWith('/{canal}') && {SAISIE_PRETE}", delai=20
    )
    ctx.cdp.evaluer("document.activeElement && document.activeElement.blur()")
    place_saisie(ctx)
    for bouton, place in zip(("📎", "🎤"), ctx.cdp.evaluer(PLACE_BOUTONS)):
        assert place, f"{bouton} absent de la saisie"
        barre, visible = place
        assert (
            barre is None or barre >= 0
        ), f"la barre couvre {bouton} : {place}"
        assert visible >= 0, f"{bouton} sort de l'écran : {place}"

    adb(
        "shell",
        "pm",
        "grant",
        PAQUET,
        "android.permission.RECORD_AUDIO",
        executer=ctx.appareil.executer,
    )
    ctx.toucher_pose(".chat-thread__mic")
    ctx.cdp.attendre(
        "!!document.querySelector('.chat-thread__mic--on')", delai=10
    )
    time.sleep(VOIX)
    ctx.toucher_pose(".chat-thread__mic--on")
    domaine = [
        ["res_model", "=", "discuss.channel"],
        ["res_id", "=", canal],
        ["voice_ids", "!=", False],
    ]
    fin = time.monotonic() + 60
    while not (
        voix := ctx.odoo.executer(
            "ir.attachment",
            "search_read",
            [domaine],
            {"fields": ["name", "mimetype", "file_size", "voice_ids"]},
        )
    ):
        if time.monotonic() > fin:
            raise TimeoutError("aucun message vocal sur le serveur en 60 s")
        time.sleep(POSE)
    assert len(voix) == 1, voix
    voix = voix[0]
    assert voix["mimetype"] == "audio/mpeg", voix
    assert re.fullmatch(
        r"Voice-\d{4}-\d{2}-\d{2}-\d+\.mp3", voix["name"]
    ), voix
    assert voix["file_size"] > 0, voix

    nom_image = f"{ctx.unique('image')}.jpg"
    image = pair.televerser(canal, nom_image, photo, "image/jpeg")
    poster_avec(pair, canal, ctx.unique("image"), [image])
    tuile = f".chat-att__tile[aria-label={js(nom_image)}]"
    ctx.cdp.attendre(f"!!document.querySelector({js(tuile)})", delai=30)
    ctx.cdp.evaluer(
        f"document.querySelector({js(tuile)}).scrollIntoView({{block: 'center'}})"
    )
    ctx.cdp.attendre(
        f"(() => {{ const i = document.querySelector({js(tuile + ' .chat-att__img')});"
        " return !!i && i.complete && i.naturalWidth > 0; })()",
        delai=30,
    )
    assert ctx.hook(
        f"chatAttachments({js(ctx.config_id)}, {canal})"
        f".then(as => as.some(a => a.attachmentId === {image[0]} && !!a.thumbPath))"
    ), "aperçu reçu sans fichier en cache"
    ctx.toucher_pose(tuile)
    ctx.cdp.attendre(
        "(() => { const i = document.querySelector('.chat-viewer__img');"
        " return !!i && i.complete && i.naturalWidth > 0; })()",
        delai=30,
    )
    ctx.toucher_pose(".chat-viewer__close")
    ctx.cdp.attendre("!document.querySelector('.chat-viewer')", delai=10)
    # La photo envoyée reste sur le téléphone, l'original reçu s'y ajoute
    espace = ctx.hook(f"chatSpace({js(ctx.config_id)})")
    assert espace >= len(photo), f"espace du clavardage : {espace} o"

    octets = pair.telecharger(f"/web/content/{voix['id']}?download=true")
    recue = pair.televerser(
        canal, voix["name"], octets, "audio/mpeg", voix=True
    )
    poster_avec(pair, canal, "", [recue])
    lecteur = f'audio[data-key="a{recue[0]}"]'
    ctx.cdp.attendre(f"!!document.querySelector({js(lecteur)})", delai=30)
    # Les événements d'un média ne remontent pas : écoutés en capture
    ctx.cdp.evaluer(
        "window.__msJoue = []; document.addEventListener('playing',"
        " e => window.__msJoue.push(e.target.dataset.key), true)"
    )
    bouton = f"[data-ms-lecture='a{recue[0]}']"
    ctx.cdp.evaluer(
        f"document.querySelector({js(lecteur)}).closest('.chat-att__voice')"
        f".querySelector('.chat-att__play').dataset.msLecture = 'a{recue[0]}'"
    )
    ctx.toucher_pose(bouton)
    ctx.cdp.attendre(f"window.__msJoue.includes('a{recue[0]}')", delai=30)
    position = f"document.querySelector({js(lecteur)}).currentTime"
    debut = ctx.cdp.evaluer(position)
    time.sleep(1)
    suite = ctx.cdp.evaluer(position)
    assert suite > debut, f"lecture figée à {debut} puis {suite} s"
    return (
        f"photo {len(photo)} o intacte, voix {voix['file_size']} o,"
        f" {espace} o en cache, lecture reçue à {suite:.1f} s"
    )


# La durée d'un appui long dans les scénarios, en ms : au-delà des 500 ms
# où l'app ouvre le menu d'un message (LONG_PRESS_MS)
APPUI_LONG = 700
# Les messages de chat_user postés après l'original d'une réponse, de
# LIGNES_REMPLISSAGE lignes chacun : l'original sort de l'écran, et un
# toucher sur la citation doit défiler jusqu'à lui
REMPLISSAGE = 6
LIGNES_REMPLISSAGE = 6
# Les clics vus pendant un appui long sur une bulle, par la classe de leur
# cible (préfixée « bulle: » quand elle est dans une bulle) : vus par
# window en capture, arrivés jusqu'à document (ceux que rien n'a avalés)
CLICS = (
    "(() => { window.__msClics = {vus: [], arrives: []};"
    " const noter = (liste) => (e) => liste.push((e.target.closest"
    " && e.target.closest('.chat-thread__bubble') ? 'bulle:' : '')"
    " + String(e.target.className || e.target.nodeName));"
    " window.addEventListener('click', noter(window.__msClics.vus), true);"
    " document.addEventListener('click', noter(window.__msClics.arrives), false);"
    " return true; })()"
)
# Les positions de défilement du fil, une par image pendant 1,5 s, et si
# l'élément de sel a été mis en évidence pendant ce temps (la mise en
# évidence dure moins que le relevé)
DEFILEMENT = (
    "(sel) => { const s = document.querySelector('.chat-thread__scroll');"
    " window.__msDefile = []; window.__msEnEvidence = false;"
    " const debut = performance.now();"
    " const relever = () => { window.__msDefile.push(Math.round(s.scrollTop));"
    " const e = document.querySelector(sel);"
    " if (e && e.classList.contains('chat-thread__bubble--highlight'))"
    " window.__msEnEvidence = true;"
    " if (performance.now() - debut < 1500) requestAnimationFrame(relever); };"
    " requestAnimationFrame(relever); return true; }"
)
# Vrai quand l'élément est dans la partie visible du fil
DANS_LE_FIL = (
    "(sel) => { const e = document.querySelector(sel);"
    " const s = document.querySelector('.chat-thread__scroll');"
    " if (!e || !s) return false; const r = e.getBoundingClientRect(),"
    " v = s.getBoundingClientRect(); return r.bottom > v.top && r.top < v.bottom; }"
)
# La marque « (modifié) » sur la ligne du dernier texte de la bulle :
# [texte de la marque, haut de la marque moins haut de la dernière ligne,
# bas de la dernière ligne moins haut de la marque], en px CSS
MARQUE_EN_LIGNE = (
    "(sel) => { const b = document.querySelector(sel + ' .chat-thread__body');"
    " const m = b && b.querySelector('.chat-msg__edited'); if (!m) return null;"
    " const w = document.createTreeWalker(b, NodeFilter.SHOW_TEXT); let t = null, n;"
    " while ((n = w.nextNode())) if (n.textContent.trim() && !m.contains(n)) t = n;"
    " if (!t) return null; const r = document.createRange(); r.selectNodeContents(t);"
    " const lignes = r.getClientRects(); const l = lignes[lignes.length - 1];"
    " const mr = m.getBoundingClientRect();"
    " return [m.innerText.trim(), Math.round(mr.top - l.top), Math.round(l.bottom - mr.top)]; }"
)
# La règle :has du fil (la marque après un paragraphe se met sur sa ligne),
# essayée sur un corps inventé posé un instant dans le fil : [le WebView
# connaît :has, display du paragraphe]
HAS_DU_FIL = (
    "(() => { const s = document.querySelector('.chat-thread__scroll');"
    " const b = document.createElement('div'); b.className = 'chat-thread__body';"
    " b.innerHTML = '<p>texte inventé</p><em class=\"chat-msg__edited\"> (modifié)</em>';"
    " s.appendChild(b); const d = getComputedStyle(b.querySelector('p')).display; b.remove();"
    " return [CSS.supports('selector(p:has(+ em))'), d]; })()"
)


def reactions_serveur(odoo_, message):
    """Les réactions du message sur le serveur, (contenu, partenaire), les
    plus anciennes d'abord."""
    return [
        (r["content"], r["partner_id"] and r["partner_id"][0])
        for r in odoo_.executer(
            "mail.message.reaction",
            "search_read",
            [[["message_id", "=", message]]],
            {"fields": ["content", "partner_id"], "order": "id asc"},
        )
    ]


def attendre_serveur(quoi, sonde, delai=20):
    """La première valeur vraie de sonde(), relue tous les POSE ;
    TimeoutError après delai secondes, avec quoi et la dernière valeur."""
    fin = time.monotonic() + delai
    while True:
        valeur = sonde()
        if valeur:
            return valeur
        if time.monotonic() > fin:
            raise TimeoutError(f"{quoi} : toujours {valeur!r} après {delai} s")
        time.sleep(POSE)


def ouvrir_menu(ctx, bulle):
    """Le menu du message de bulle, ouvert par un appui long dessus : le
    clic qui termine l'appui, qu'il tombe sur la bulle, sur le voile ou sur
    un bouton du menu ouvert sous le doigt, n'arrive jusqu'au document
    nulle part (le fil l'avale) et le menu reste ouvert. Rend les clics vus
    pendant l'appui et le texte que le WebView a sélectionné."""
    ctx.cdp.evaluer("window.getSelection().removeAllRanges(); " + CLICS)
    ctx.toucher_maintenir(bulle, APPUI_LONG)
    ctx.cdp.attendre("!!document.querySelector('.chat-menu')", delai=5)
    time.sleep(POSE)
    clics = ctx.cdp.evaluer("window.__msClics")
    selection = ctx.cdp.evaluer("window.getSelection().toString()")
    assert not clics["arrives"], f"clic de fin d'appui arrivé : {clics}"
    assert ctx.cdp.evaluer(
        "!!document.querySelector('.chat-menu')"
    ), "le menu s'est refermé à la fin de l'appui"
    return clics["vus"], selection


def reagir_pouce(ctx, bulle, message, moi):
    """👍 choisi dans le menu du message : la puce s'affiche, à soi, et le
    serveur a la réaction de l'utilisateur de l'app."""
    vus, selection = ouvrir_menu(ctx, bulle)
    ctx.toucher_pose(
        ctx.marquer(".chat-menu__emoji", "👍", ".chat-menu__emoji")
    )
    ctx.cdp.attendre("!document.querySelector('.chat-menu')", delai=5)
    ctx.cdp.attendre(
        f"!!document.querySelector({js(bulle + ' .chat-reactions__chip[aria-pressed=true]')})",
        delai=10,
    )
    attendre_serveur(
        "la réaction 👍 sur le serveur",
        lambda: reactions_serveur(ctx.odoo, message) == [("👍", moi)],
    )
    return vus, selection


def scenario_actions_clavardage(ctx):
    """Les actions sur un message, dans un groupe neuf avec chat_user. Un
    appui long sur la bulle de chat_user ouvre le menu, le clic qui le
    termine avalé ; 👍 y met la puce et la réaction sur le serveur ; un
    toucher sur la puce la retire, puis 👍 la remet. Répondre : une
    suggestion @ touchée garde le clavier ouvert et la saisie visible, ➤
    poste la réponse sur l'original (parent_id) avec la mention, et la
    citation s'affiche ; un toucher sur la citation défile en douceur
    jusqu'à l'original, sorti de l'écran, et le met en évidence. Modifier,
    changer le texte, ➤ : « (modifié) » sur la ligne du texte dans la
    bulle, et la marque dans le corps du serveur. Captures gardées dans le
    répertoire de la course ; rend les relevés des vérifications."""
    pair = Odoo(ctx.cible, "chat")
    moi = ctx.odoo.lire("res.users", ctx.odoo.uid, ["partner_id"])[
        "partner_id"
    ][0]
    partenaire = pair.lire("res.users", pair.uid, ["partner_id"])[
        "partner_id"
    ][0]
    nom = ctx.unique("actions")
    pair.executer(
        "discuss.channel",
        "create_group",
        [],
        {"partners_to": [moi], "name": nom},
    )
    canal = pair.executer("discuss.channel", "search", [[["name", "=", nom]]])[
        0
    ]

    def poster(texte):
        return pair.route(
            "/mail/message/post",
            {
                "thread_model": "discuss.channel",
                "thread_id": canal,
                "post_data": {
                    "body": texte,
                    "message_type": "comment",
                    "subtype_xmlid": "mail.mt_comment",
                },
            },
        )["mail.message"][0]["id"]

    original_texte = ctx.unique("original")
    original = poster(original_texte)
    for rang in range(REMPLISSAGE):
        poster(
            "<br>".join(
                f"remplissage {rang} ligne {n}"
                for n in range(LIGNES_REMPLISSAGE)
            )
        )
    ctx.hook(f"chatLoad({js(ctx.config_id)})")
    ctx.hook(
        f"open('/chat/' + encodeURIComponent({js(ctx.config_id)}) + '/{canal}')"
    )
    ctx.cdp.attendre(
        f"location.pathname.endsWith('/{canal}') && {SAISIE_PRETE}", delai=20
    )
    ctx.cdp.evaluer("document.activeElement && document.activeElement.blur()")
    bulle = f'.chat-thread__bubble[data-key="m{original}"]'
    ctx.cdp.attendre(f"!!document.querySelector({js(bulle)})", delai=30)

    vus, selection = reagir_pouce(ctx, bulle, original, moi)
    puce = bulle + " .chat-reactions__chip"
    ctx.toucher_pose(puce)
    ctx.cdp.attendre(f"!document.querySelector({js(puce)})", delai=10)
    attendre_serveur(
        "la réaction retirée du serveur",
        lambda: reactions_serveur(ctx.odoo, original) == [],
    )
    reagir_pouce(ctx, bulle, original, moi)
    reactions = ctx.hook(f"chatReactions({js(ctx.config_id)}, {canal})")
    assert [
        (r["content"], r["selfReacted"]) for r in reactions[f"m{original}"]
    ] == [("👍", True)], reactions
    ctx.capturer("actions_reaction", bulle)

    ouvrir_menu(ctx, bulle)
    ctx.toucher_pose(".chat-menu__reply")
    ctx.cdp.attendre(
        "!!document.querySelector('.chat-banner--reply')", delai=5
    )
    ctx.toucher_pose(".chat-thread__input")
    fin = time.monotonic() + 10
    while not clavier_affiche(ctx):
        if time.monotonic() > fin:
            raise TimeoutError("le clavier ne s'ouvre pas sur la saisie")
        time.sleep(POSE)
    ctx.cdp.evaluer("document.querySelector('.chat-thread__input').focus()")
    ctx.cdp.taper("@MS")
    ctx.toucher_pose(
        ctx.marquer(".chat-suggest__name", "@MS Chat", ".chat-suggest__item")
    )
    ctx.cdp.attendre(
        "document.querySelector('.chat-thread__input').value === '@MS Chat '",
        delai=5,
    )
    time.sleep(POSE)
    assert clavier_affiche(ctx), "clavier fermé par la suggestion"
    assert ctx.cdp.evaluer(
        SAISIE_ACTIVE
    ), "saisie sans focus après la suggestion"
    apres_suggestion = place_saisie(ctx)
    reponse_texte = ctx.unique("reponse")
    ctx.cdp.taper(reponse_texte)
    ctx.toucher_pose(".chat-thread__send")
    reponse = ctx.cdp.attendre(
        f"window.__erplibreTest.chatMessages({js(ctx.config_id)}, {canal})"
        f".then(ms => {{ const m = ms.find(m => m.body.includes({js(reponse_texte)}));"
        " return !!m && m.status === 'sent' && m.messageId; })",
        delai=30,
    )
    lue = ctx.odoo.lire("mail.message", reponse, ["parent_id", "partner_ids"])
    assert lue["parent_id"] and lue["parent_id"][0] == original, lue
    assert lue["partner_ids"] == [partenaire], lue
    citation = (
        f'.chat-thread__bubble[data-key="m{reponse}"] .chat-thread__quote'
    )
    ctx.cdp.attendre(
        f"(() => {{ const q = document.querySelector({js(citation)});"
        f" return !!q && q.innerText.includes({js(original_texte)}); }})()",
        delai=10,
    )
    ctx.capturer("actions_reponse", citation)

    ctx.cdp.evaluer("document.activeElement && document.activeElement.blur()")
    ctx.cdp.evaluer(
        "(() => { const s = document.querySelector('.chat-thread__scroll');"
        " s.scrollTop = s.scrollHeight; })()"
    )
    ctx.poser(citation)
    assert not ctx.cdp.evaluer(
        f"({DANS_LE_FIL})({js(bulle)})"
    ), "l'original est encore à l'écran : rien à défiler"
    ctx.cdp.evaluer(f"({DEFILEMENT})({js(bulle)})")
    ctx.cdp.toucher(citation)
    time.sleep(1.7)
    positions = ctx.cdp.evaluer("window.__msDefile")
    intermediaires = [
        p
        for p in set(positions)
        if min(positions[0], positions[-1])
        < p
        < max(positions[0], positions[-1])
    ]
    assert positions[0] != positions[-1], f"aucun défilement : {positions}"
    assert len(intermediaires) >= 2, f"défilement d'un bond : {positions}"
    assert ctx.cdp.evaluer(f"({DANS_LE_FIL})({js(bulle)})"), positions
    assert ctx.cdp.evaluer(
        "window.__msEnEvidence"
    ), "l'original n'est pas mis en évidence"

    bulle_reponse = f'.chat-thread__bubble[data-key="m{reponse}"]'
    ouvrir_menu(ctx, bulle_reponse)
    ctx.toucher_pose(".chat-menu__edit")
    ctx.cdp.attendre(
        "!!document.querySelector('.chat-banner--edit')"
        f" && document.querySelector('.chat-thread__input').value.includes({js(reponse_texte)})",
        delai=5,
    )
    # Court : la marque a la place de tenir sur la ligne du texte
    modifie = f"modifié {uuid.uuid4().hex[:6]}"
    ctx.cdp.evaluer(
        "(() => { const i = document.querySelector('.chat-thread__input');"
        " i.focus(); i.select(); })()"
    )
    ctx.cdp.taper(modifie)
    ctx.cdp.attendre(
        f"document.querySelector('.chat-thread__input').value === {js(modifie)}",
        delai=5,
    )
    ctx.toucher_pose(".chat-thread__send")
    corps = attendre_serveur(
        "la modification sur le serveur",
        lambda: (
            lambda c: (
                c if modifie in c and "o-mail-Message-edited" in c else None
            )
        )(ctx.odoo.lire("mail.message", reponse, ["body"])["body"] or ""),
    )
    en_ligne = ctx.cdp.attendre(
        f"(() => {{ const b = document.querySelector({js(bulle_reponse + ' .chat-thread__body')});"
        f" return !!b && b.innerText.includes({js(modifie)}) && ({MARQUE_EN_LIGNE})({js(bulle_reponse)}); }})()",
        delai=20,
    )
    marque, ecart_haut, ecart_bas = en_ligne
    assert marque == "(modifié)", en_ligne
    assert (
        ecart_haut > -4 and ecart_bas > 0
    ), f"marque hors de la ligne : {en_ligne}"
    has, affichage = ctx.cdp.evaluer(HAS_DU_FIL)
    assert has and affichage == "inline", f":has : {has}, display {affichage}"
    ctx.capturer("actions_modification", bulle_reponse)
    return (
        f"appui long : clics vus {vus or 'aucun'}, aucun arrivé,"
        f" sélection native {selection!r} ;"
        f" suggestion : clavier ouvert, saisie à {apres_suggestion[0]} px"
        f" de la barre, {apres_suggestion[1]} px du bas visible ;"
        f" citation : {len(set(positions))} positions de {positions[0]}"
        f" à {positions[-1]} ; (modifié) à {ecart_haut} px du haut de la"
        f" ligne ; :has {has}, display {affichage} ; corps {len(corps)} car."
    )


# Vrai quand le message de sel est mis en évidence pendant les 15 s qui
# suivent : relevé à chaque image, la page gardée d'un écran à l'autre
EN_EVIDENCE = (
    "(sel) => { window.__msVu = false; const debut = performance.now();"
    " const relever = () => { const e = document.querySelector(sel);"
    " if (e && e.classList.contains('chat-thread__bubble--highlight'))"
    " { window.__msVu = true; return; }"
    " if (performance.now() - debut < 15000) requestAnimationFrame(relever); };"
    " requestAnimationFrame(relever); return true; }"
)
# Le bouton positif d'une AlertDialog d'Android (Dialog.confirm de Capacitor)
BOUTON_POSITIF = "android:id/button1"
CONTENU_UI = "/data/local/tmp/ms_ui.xml"


def marquer_contenant(ctx, selecteur, texte):
    """Un sélecteur du premier élément de selecteur dont le texte contient
    texte : il reçoit un attribut data-ms-marque, que toucher() retrouve."""
    ctx.compteur += 1
    marque = str(ctx.compteur)
    ctx.cdp.attendre(
        f"(() => {{ const e = [...document.querySelectorAll({js(selecteur)})]"
        f".find(e => e.innerText.includes({js(texte)})); if (!e) return false;"
        f" e.dataset.msMarque = {js(marque)}; return true; }})()",
        delai=30,
    )
    return f'[data-ms-marque="{marque}"]'


def toucher_dialogue(ctx, libelle, delai=10):
    """Touche le bouton positif d'une boîte de dialogue native, une fois
    affichée avec le libellé libelle : Dialog.confirm de Capacitor ouvre
    une AlertDialog d'Android, hors du WebView. La fenêtre est relevée par
    uiautomator, le centre du bouton touché par input tap."""
    executer = ctx.appareil.executer
    fin = time.monotonic() + delai
    vu = None
    try:
        while True:
            adb(
                "shell",
                "uiautomator",
                "dump",
                CONTENU_UI,
                executer=executer,
                check=False,
            )
            contenu = adb("shell", "cat", CONTENU_UI, executer=executer)
            debut = contenu.find("<?xml")
            noeuds = []
            if debut >= 0:
                try:
                    noeuds = list(ET.fromstring(contenu[debut:]).iter("node"))
                except ET.ParseError:
                    noeuds = []
            # Le bouton de la boîte de l'app de test : jamais celui d'une
            # boîte d'une autre app affichée au même moment
            bouton = next(
                (
                    n
                    for n in noeuds
                    if n.get("resource-id") == BOUTON_POSITIF
                    and n.get("package") == PAQUET
                ),
                None,
            )
            vu = bouton.get("text") if bouton is not None else None
            if vu and vu.strip().casefold() == libelle.casefold():
                x1, y1, x2, y2 = map(
                    int, re.findall(r"\d+", bouton.get("bounds"))
                )
                adb(
                    "shell",
                    "input",
                    "tap",
                    str((x1 + x2) // 2),
                    str((y1 + y2) // 2),
                    executer=executer,
                )
                return
            if time.monotonic() > fin:
                raise TimeoutError(
                    f"boîte de dialogue « {libelle} » absente en {delai} s"
                    f" (bouton positif : {vu!r})"
                )
            time.sleep(POSE)
    finally:
        adb("shell", "rm", "-f", CONTENU_UI, executer=executer, check=False)


def place_au_clavier(ctx, champ):
    """place_saisie clavier fermé, puis clavier ouvert par un toucher sur
    champ : rend les deux relevés."""
    ctx.cdp.evaluer("document.activeElement && document.activeElement.blur()")
    ferme = place_saisie(ctx)
    ctx.toucher_pose(champ)
    fin = time.monotonic() + 10
    while not clavier_affiche(ctx):
        if time.monotonic() > fin:
            raise TimeoutError(f"le clavier ne s'ouvre pas sur {champ}")
        time.sleep(POSE)
    return ferme, place_saisie(ctx)


def ecart(releve):
    """La place d'une saisie (place_au_clavier) en texte : px au-dessus de
    la barre, clavier fermé puis ouvert."""
    ferme, ouvert = releve
    return (
        f"{ferme[0]} px fermé,"
        f" {ouvert[0] if ouvert[0] is not None else '—'} px ouvert"
    )


def notification_de(odoo_, message, partenaire):
    """La notification du message pour le partenaire (is_read), None
    quand il n'en a pas."""
    lignes = odoo_.executer(
        "mail.notification",
        "search_read",
        [
            [
                ["mail_message_id", "=", message],
                ["res_partner_id", "=", partenaire],
            ]
        ],
        {"fields": ["is_read"]},
    )
    return lignes[0] if lignes else None


def vu_de(odoo_, canal, partenaire):
    """Le dernier message que le partenaire a vu dans le canal
    (seen_message_id de son membre), 0 quand il n'en a vu aucun."""
    membre = odoo_.executer(
        "discuss.channel.member",
        "search_read",
        [[["channel_id", "=", canal], ["partner_id", "=", partenaire]]],
        {"fields": ["seen_message_id"]},
    )[0]
    return membre["seen_message_id"][0] if membre["seen_message_id"] else 0


def scenario_recherche_boite(ctx):
    """La recherche et la boîte de réception du clavardage, dans « ms chat »
    et sur des tâches que l'administrateur suit. L'index de recherche FTS5
    reste cohérent après un message envoyé (sa ligne remplacée par celle du
    serveur), modifié et supprimé : son contrôle d'intégrité répond « ok ».
    Le mot que chat_user poste se trouve dans la recherche de la liste, et
    un toucher sur le résultat ouvre le fil sur le message, mis en
    évidence. Un appui long : Épingler, confirmé dans la boîte de dialogue
    native, puis Favori, chacun lu sur le serveur. Après un message de
    l'administrateur, deux de chat_user à la suite : la première bulle
    porte son nom et son avatar, l'image chargée, la seconde seulement le
    retrait. La boîte de réception
    affiche l'avis des notifications par courriel ; « Recevoir mes
    notifications dans Odoo » passe l'administrateur à inbox, puis une
    mention de chat_user y arrive et « Marquer comme lu » la marque lue sur
    le serveur. Deux commentaires de chat_user sur une tâche : la réponse
    ouverte sur l'un, fermée, ouverte sur l'autre, puis un retour Android
    ferme la réponse et laisse la boîte à l'écran. Répondre, la photo
    gardée en brouillon, un texte, ➤ : une note avec la photo sur la tâche.
    Les saisies du fil, avant et après les auteurs, et de la réponse se
    tiennent au plus ECART_BARRE_MAX px au-dessus de la barre, clavier
    fermé et ouvert. Un vieux résultat, suivi de plus de FENETRE_FIL
    messages non lus de chat_user, ouvre le fil sur lui sans rien marquer
    lu : la lecture de l'administrateur sur le serveur ne bouge pas
    pendant LECTURE_DELAI s. L'administrateur
    revient à email à la fin, quoi qu'il arrive. Rend le moteur de
    recherche, l'intégrité de l'index et les places mesurées."""
    pair = Odoo(ctx.cible, "chat")
    moi = ctx.odoo.lire("res.users", ctx.odoo.uid, ["partner_id"])[
        "partner_id"
    ][0]
    canaux = pair.executer(
        "discuss.channel",
        "search",
        [[["name", "=", CANAL_CHAT], ["channel_type", "=", "group"]]],
    )
    assert canaux, f"aucun groupe « {CANAL_CHAT} » pour chat_user"
    canal = canaux[0]

    def poster(modele, ident, texte, partenaires=()):
        return pair.route(
            "/mail/message/post",
            {
                "thread_model": modele,
                "thread_id": ident,
                "post_data": {
                    "body": texte,
                    "message_type": "comment",
                    "subtype_xmlid": "mail.mt_comment",
                    "partner_ids": list(partenaires),
                },
            },
        )["mail.message"][0]["id"]

    def corps(message):
        return ctx.odoo.lire("mail.message", message, ["body"])["body"] or ""

    try:
        ctx.hook(f"chatLoad({js(ctx.config_id)})")
        moteur = ctx.hook("chatSearchEngine()")
        texte = ctx.unique("index")
        envoi = ctx.hook(
            f"chatSend({js(ctx.config_id)}, {canal}, {js(texte)})"
        )
        mien = attendre_envoye(ctx, canal, envoi)
        modifie = ctx.unique("index-modifie")
        ctx.hook(
            f"chatEdit({js(ctx.config_id)}, {canal}, {mien}, {js(modifie)})"
        )
        attendre_serveur(
            "la modification sur le serveur", lambda: modifie in corps(mien)
        )
        ctx.hook(f"chatDelete({js(ctx.config_id)}, {canal}, {mien})")
        # Un message modifié puis supprimé garde la marque vide de sa
        # modification : seul le texte s'en va
        attendre_serveur(
            "la suppression sur le serveur",
            lambda: modifie not in corps(mien),
        )
        integrite = ctx.hook("chatSearchIntegrity()")
        assert integrite == (
            "ok" if moteur == "fts5" else "like"
        ), f"index {moteur} : {integrite}"

        mot = ctx.unique("mot")
        trouve = poster("discuss.channel", canal, f"{mot} à trouver")
        ctx.cdp.attendre(
            f"window.__erplibreTest.chatMessages({js(ctx.config_id)}, {canal})"
            f".then(ms => ms.some(m => m.messageId === {trouve}))",
            delai=30,
        )
        ctx.ouvrir("/chat", ".chat-list__search")
        ctx.toucher_pose(".chat-list__search")
        ctx.cdp.evaluer("document.querySelector('.chat-list__search').focus()")
        ctx.cdp.taper(mot)
        resultat = marquer_contenant(ctx, ".chat-search__hit", mot)
        ctx.capturer("recherche_resultat", resultat)
        bulle = f'.chat-thread__bubble[data-key="m{trouve}"]'
        ctx.cdp.evaluer(f"({EN_EVIDENCE})({js(bulle)})")
        ctx.toucher_pose(resultat)
        ctx.cdp.attendre(
            f"location.pathname.endsWith('/{canal}')"
            f" && !!document.querySelector({js(bulle)})",
            delai=20,
        )
        ctx.cdp.attendre("window.__msVu", delai=15)
        assert ctx.cdp.evaluer(
            f"({DANS_LE_FIL})({js(bulle)})"
        ), "le fil ne s'ouvre pas sur le message trouvé"
        ctx.capturer("recherche_fil", bulle)
        place_fil = place_au_clavier(ctx, ".chat-thread__input")
        ctx.cdp.evaluer(
            "document.activeElement && document.activeElement.blur()"
        )

        ouvrir_menu(ctx, bulle)
        ctx.toucher_pose(".chat-menu__pin")
        toucher_dialogue(ctx, "Épingler")
        attendre_serveur(
            "l'épingle sur le serveur",
            lambda: ctx.odoo.lire("mail.message", trouve, ["pinned_at"])[
                "pinned_at"
            ],
        )
        # L'avis d'épingle arrive par le bus sous le message et fait
        # défiler le fil : l'appui suivant attend qu'il soit affiché, sans
        # quoi il tombe sur le lien « Voir tous les messages épinglés »
        ctx.cdp.attendre(
            "[...document.querySelectorAll('.chat-thread__bubble--system')]"
            f".some(b => Number(b.dataset.key.slice(1)) > {trouve})",
            delai=30,
        )
        ouvrir_menu(ctx, bulle)
        ctx.toucher_pose(".chat-menu__star")
        attendre_serveur(
            "le favori sur le serveur",
            lambda: moi
            in ctx.odoo.lire("mail.message", trouve, ["starred_partner_ids"])[
                "starred_partner_ids"
            ],
        )

        # Le message de l'administrateur coupe toute suite d'avant : la
        # première bulle de chat_user ouvre la sienne
        coupe = ctx.hook(
            f"chatSend({js(ctx.config_id)}, {canal}, {js(ctx.unique('coupe'))})"
        )
        attendre_envoye(ctx, canal, coupe)
        tete = poster("discuss.channel", canal, ctx.unique("auteur"))
        suite = poster("discuss.channel", canal, ctx.unique("auteur"))
        bulle_tete = f'.chat-thread__bubble[data-key="m{tete}"]'
        bulle_suite = f'.chat-thread__bubble[data-key="m{suite}"]'
        ctx.cdp.attendre(
            f"!!document.querySelector({js(bulle_suite)})", delai=30
        )
        ctx.cdp.evaluer(
            f"document.querySelector({js(bulle_tete)})"
            ".scrollIntoView({block: 'center'})"
        )
        image = f"{bulle_tete} .chat-thread__author-img"
        ctx.cdp.attendre(
            f"(() => {{ const i = document.querySelector({js(image)});"
            " return !!i && i.complete && i.naturalWidth > 0; })()",
            delai=30,
        )
        nom = ctx.cdp.evaluer(
            f"document.querySelector({js(bulle_tete + ' .chat-thread__author-name')})"
            ".textContent"
        )
        attendu = pair.lire("res.users", pair.uid, ["name"])["name"]
        assert nom == attendu, f"auteur affiché {nom!r}, attendu {attendu!r}"
        assert ctx.cdp.evaluer(
            f"(() => {{ const b = document.querySelector({js(bulle_suite)});"
            " return b.classList.contains('chat-thread__bubble--indent')"
            " && !b.querySelector('.chat-thread__author-name'); })()"
        ), "la seconde bulle de la suite porte un auteur"
        ctx.capturer("auteurs", bulle_tete)
        place_auteurs = place_au_clavier(ctx, ".chat-thread__input")
        ctx.cdp.evaluer(
            "document.activeElement && document.activeElement.blur()"
        )

        ctx.ouvrir("/chat/inbox", ".chat-mailbox__notice")
        ctx.capturer("boite_avis", ".chat-mailbox__notice")
        ctx.toucher_pose(".chat-mailbox__switch")
        attendre_serveur(
            "admin notifié dans Odoo",
            lambda: ctx.odoo.lire(
                "res.users", ctx.odoo.uid, ["notification_type"]
            )["notification_type"]
            == "inbox",
        )
        ctx.cdp.attendre(
            "!document.querySelector('.chat-mailbox__notice')", delai=10
        )
        assert (
            ctx.hook(f"chatNotificationType({js(ctx.config_id)})") == "inbox"
        )

        rappel = ctx.unique("mention")
        mention = poster("discuss.channel", canal, rappel, [moi])
        assert notification_de(ctx.odoo, mention, moi), "mention sans avis"
        item = marquer_contenant(ctx, ".chat-mailbox__item", rappel)
        ctx.toucher_pose(f"{item} .chat-mailbox__mark")
        attendre_serveur(
            "la mention lue sur le serveur",
            lambda: notification_de(ctx.odoo, mention, moi)["is_read"],
        )

        # Dans un projet : une tâche privée n'est lisible que de ses assignés
        projet = ctx.odoo.creer(
            "project.project", {"name": ctx.unique("projet")}
        )
        tache = ctx.odoo.creer(
            "project.task", {"name": ctx.unique("tache"), "project_id": projet}
        )
        premier = ctx.unique("commentaire")
        poster("project.task", tache, premier)
        second = ctx.unique("commentaire")
        commentaire = poster("project.task", tache, second)
        un = marquer_contenant(ctx, ".chat-mailbox__item", premier)
        autre = marquer_contenant(ctx, ".chat-mailbox__item", second)
        ctx.toucher_pose(f"{un} .chat-mailbox__reply")
        ctx.cdp.attendre("!!document.querySelector('.chat-reply')", delai=5)
        ctx.toucher_pose(".chat-reply__close")
        ctx.cdp.attendre("!document.querySelector('.chat-reply')", delai=5)
        ctx.toucher_pose(f"{autre} .chat-mailbox__reply")
        ctx.cdp.attendre("!!document.querySelector('.chat-reply')", delai=5)
        adb("shell", "input", "keyevent", "4", executer=ctx.appareil.executer)
        ctx.cdp.attendre("!document.querySelector('.chat-reply')", delai=5)
        time.sleep(POSE)
        assert ctx.cdp.evaluer(
            "location.pathname === '/chat/inbox'"
            " && !!document.querySelector('.chat-mailbox')"
        ), "le retour a quitté la boîte de réception"

        nom_photo = f"{ctx.unique('photo')}.jpg"
        deposer(ctx, PHOTO, f"{DEPOT}/{nom_photo}")
        ctx.hook(
            f"chatRecordDraftFile({js(ctx.config_id)}, {commentaire},"
            f" {js(f'{DEPOT}/{nom_photo}')}, {js(nom_photo)}, 'image/jpeg')"
        )
        ctx.toucher_pose(f"{autre} .chat-mailbox__reply")
        ctx.cdp.attendre(
            "!!document.querySelector('.chat-reply .chat-attach__chip')",
            delai=10,
        )
        place_reponse = place_au_clavier(ctx, ".chat-reply__input")
        reponse = ctx.unique("reponse")
        ctx.cdp.evaluer("document.querySelector('.chat-reply__input').focus()")
        ctx.cdp.taper(reponse)
        ctx.cdp.attendre(
            f"document.querySelector('.chat-reply__input').value === {js(reponse)}",
            delai=5,
        )
        ctx.capturer("boite_reponse", ".chat-reply")
        ctx.toucher_pose(".chat-reply .chat-thread__send")
        note = ctx.odoo.executer(
            "ir.model.data",
            "search_read",
            [[["module", "=", "mail"], ["name", "=", "mt_note"]]],
            {"fields": ["res_id"]},
        )[0]["res_id"]
        recue = attendre_serveur(
            "la réponse sur la tâche",
            lambda: ctx.odoo.executer(
                "mail.message",
                "search_read",
                [
                    [
                        ["model", "=", "project.task"],
                        ["res_id", "=", tache],
                        ["body", "ilike", reponse],
                    ]
                ],
                {"fields": ["subtype_id", "attachment_ids"]},
            ),
            delai=60,
        )
        assert len(recue) == 1, recue
        assert recue[0]["subtype_id"][0] == note, recue
        pieces = ctx.odoo.executer(
            "ir.attachment",
            "read",
            [recue[0]["attachment_ids"]],
            {"fields": ["name"]},
        )
        assert [p["name"] for p in pieces] == [nom_photo], pieces

        # Un vieux résultat, hors de la première fenêtre du fil, dans une
        # conversation aux messages non lus : l'ouvrir ne lit rien, ni
        # pendant que le fil va vers lui ni une fois qu'il y est
        vieux_mot = ctx.unique("vieux")
        vieux = poster("discuss.channel", canal, f"{vieux_mot} plus haut")
        for _ in range(FENETRE_FIL + 10):
            dernier = poster("discuss.channel", canal, ctx.unique("suite"))
        ctx.cdp.attendre(
            f"window.__erplibreTest.chatMessages({js(ctx.config_id)}, {canal})"
            f".then(ms => ms.some(m => m.messageId === {dernier}))",
            delai=60,
        )
        vu_avant = vu_de(ctx.odoo, canal, moi)
        assert vu_avant < vieux, f"lu jusqu'à {vu_avant} avant l'ouverture"
        ctx.ouvrir("/chat", ".chat-list__search")
        ctx.toucher_pose(".chat-list__search")
        ctx.cdp.evaluer("document.querySelector('.chat-list__search').focus()")
        ctx.cdp.taper(vieux_mot)
        resultat = marquer_contenant(ctx, ".chat-search__hit", vieux_mot)
        bulle_vieux = f'.chat-thread__bubble[data-key="m{vieux}"]'
        ctx.cdp.evaluer(f"({EN_EVIDENCE})({js(bulle_vieux)})")
        ctx.toucher_pose(resultat)
        ctx.cdp.attendre("window.__msVu", delai=30)
        # La mise en évidence part avec le défilement doux vers le message :
        # de loin, il n'est dans le fil qu'à la fin de ce défilement
        ctx.cdp.attendre(f"({DANS_LE_FIL})({js(bulle_vieux)})", delai=10)
        ctx.capturer("recherche_vieux", bulle_vieux)
        fin = time.monotonic() + LECTURE_DELAI
        while time.monotonic() < fin:
            vu = vu_de(ctx.odoo, canal, moi)
            assert vu == vu_avant, (
                f"le vieux résultat a marqué lu jusqu'à {vu} (avant :"
                f" {vu_avant})"
            )
            time.sleep(POSE)
    finally:
        ctx.odoo.ecrire(
            "res.users", ctx.odoo.uid, {"notification_type": "email"}
        )
    return (
        f"moteur {moteur}, intégrité {integrite} ; saisie du fil"
        f" {ecart(place_fil)}, avec les auteurs {ecart(place_auteurs)},"
        f" de la réponse {ecart(place_reponse)}"
    )


# ─── Notifications du clavardage, app fermée ──────────────────────────────────

# Le délai le plus long d'un message posté à sa notification, app fermée
POUSSEE_DELAI = 15
# Le temps que se donne le service pour revenir de lui-même (START_STICKY)
# après la mort du processus, avant que la tâche périodique soit forcée
RETOUR_COLLANT = 20
# Le temps total du retour du service, la tâche forcée comprise
RETOUR_DELAI = 60
# Le temps laissé à une notification qui ne doit pas venir, une fois le
# message arrivé sur le ntfy
SILENCE = 5
TACHE_PERIODIQUE = 4823
ID_PERMANENTE = 9101
RECORD = re.compile(
    r"NotificationRecord\(0x[0-9a-f]+: pkg=(?P<pkg>\S+) user=\S+"
    r" id=(?P<id>-?\d+) tag=(?P<tag>.*?) importance=\d+ key=.*?:"
    r" Notification\(channel=(?P<canal>\S+) .*?flags=(?P<flags>0x[0-9a-f]+)"
    r" .*?vis=(?P<vis>[A-Z]+)"
)


def notifications(executer, paquet=PAQUET):
    """Les notifications affichées du paquet selon dumpsys notification
    --noredact (textes en clair) : une par NotificationRecord, avec son
    tag, son id, son canal, ses drapeaux (int), sa visibilité et le texte
    de son bloc (extras compris)."""
    sortie = adb(
        "shell", "dumpsys", "notification", "--noredact", executer=executer
    )
    debuts = [m.start() for m in re.finditer(r"NotificationRecord\(", sortie)]
    trouvees = []
    for i, debut in enumerate(debuts):
        fin = debuts[i + 1] if i + 1 < len(debuts) else len(sortie)
        bloc = sortie[debut:fin]
        entete = RECORD.match(bloc)
        if not entete or entete["pkg"] != paquet:
            continue
        trouvees.append(
            {
                "tag": None if entete["tag"] == "null" else entete["tag"],
                "id": int(entete["id"]),
                "canal": entete["canal"],
                "flags": int(entete["flags"], 16),
                "vis": entete["vis"],
                "bloc": bloc,
            }
        )
    return trouvees


def extra(notification, nom):
    """La valeur String d'un extra du bloc (android.title, android.text),
    None quand il n'y est pas."""
    trouve = re.search(
        rf"^\s*{re.escape(nom)}=String \((.*)\)\s*$",
        notification["bloc"],
        re.MULTILINE,
    )
    return trouve.group(1) if trouve else None


def attendre_notification(ctx, tag, condition=lambda n: True, delai=15):
    """La notification de tag une fois affichée et condition vraie pour
    elle, et le temps écoulé ; TimeoutError après delai secondes."""
    debut = time.monotonic()
    while True:
        for n in notifications(ctx.appareil.executer):
            if n["tag"] == tag and condition(n):
                return n, time.monotonic() - debut
        if time.monotonic() - debut > delai:
            raise TimeoutError(f"aucune notification {tag} en {delai} s")
        time.sleep(0.5)


def empreinte(config_id):
    """Les 12 premiers chiffres hexadécimaux du SHA-256 du config id : ce
    qui nomme les canaux d'un serveur (chat.<h>, inbox.<h>)."""
    return hashlib.sha256(config_id.encode()).hexdigest()[:12]


def messages_ntfy(ntfy, sujet):
    """Le nombre de messages que le ntfy de la course tient sur sujet, lu
    avec le jeton du téléphone."""
    requete = urllib.request.Request(
        f"{ntfy['url']}/{sujet}/json?poll=1&since=all",
        headers={"Authorization": f"Bearer {ntfy['token']}"},
    )
    with urllib.request.urlopen(requete, timeout=15) as reponse:
        lignes = reponse.read().decode().splitlines()
    return sum(1 for ligne in lignes if '"event":"message"' in ligne)


def accueil(ctx):
    """L'écran d'accueil d'Android : l'app passe à l'arrière-plan."""
    adb(
        "shell",
        "input",
        "keyevent",
        "KEYCODE_HOME",
        executer=ctx.appareil.executer,
    )
    ctx.cdp.attendre(f"{APP_ETAT}.then(s => !s.isActive)", delai=10)


def toucher_notification(ctx, texte, delai=10):
    """Le volet ouvert (cmd statusbar expand-notifications), la ligne
    de la notification de l'app de test qui affiche texte touchée en son
    centre (toucher_dans : jamais une notification d'une autre app)."""
    executer = ctx.appareil.executer
    adb("shell", "cmd", "statusbar", "expand-notifications", executer=executer)
    toucher_dans(
        executer,
        f"la ligne « {texte} »",
        texte,
        lambda n: porte(n, texte),
        delai=delai,
    )


def masque_verrouille(executer):
    """Vrai quand Android masque le contenu sensible des notifications sur
    l'écran verrouillé (lock_screen_show_notifications ou
    lock_screen_allow_private_notifications à 0) ; un réglage illisible
    compte comme montré, comme l'app le compte."""

    def reglage(nom):
        valeur = adb(
            "shell", "settings", "get", "secure", nom, executer=executer
        ).strip()
        return int(valeur) if valeur.lstrip("-").isdigit() else None

    return 0 in (
        reglage("lock_screen_show_notifications"),
        reglage("lock_screen_allow_private_notifications"),
    )


def tout_lire(odoo_, partenaire):
    """Tout le non-lu du partenaire marqué lu sur le serveur, comme le
    client web le marque : chaque conversation dont il est membre lue
    jusqu'à son dernier message (/discuss/channel/mark_as_read), puis sa
    boîte de réception (mark_all_as_read)."""
    membres = odoo_.executer(
        "discuss.channel.member",
        "search_read",
        [[["partner_id", "=", partenaire]]],
        {"fields": ["channel_id"]},
    )
    for membre in membres:
        canal = membre["channel_id"][0]
        dernier = odoo_.executer(
            "mail.message",
            "search",
            [[["model", "=", "discuss.channel"], ["res_id", "=", canal]]],
            {"limit": 1, "order": "id desc"},
        )
        if dernier:
            odoo_.route(
                "/discuss/channel/mark_as_read",
                {"channel_id": canal, "last_message_id": dernier[0]},
            )
    odoo_.executer("mail.message", "mark_all_as_read", [], {"domain": []})


def tache_forcee(ctx, delai=30):
    """Un passage de la tâche périodique forcé (cmd jobscheduler run -f),
    attendu jusqu'à ce que le compte ait été relevé de nouveau (son
    lastCheckAt dans la santé du moteur)."""

    def releve():
        comptes = ctx.hook("chatPushStatus()")["accounts"]
        return max(
            (
                c["lastCheckAt"]
                for c in comptes
                if c["configId"] == ctx.config_id
            ),
            default=0,
        )

    avant = releve()
    adb(
        "shell",
        "cmd",
        "jobscheduler",
        "run",
        "-f",
        PAQUET,
        str(TACHE_PERIODIQUE),
        executer=ctx.appareil.executer,
    )
    fin = time.monotonic() + delai
    while releve() <= avant:
        if time.monotonic() > fin:
            raise TimeoutError(f"la tâche forcée ne relève pas en {delai} s")
        time.sleep(0.5)


def premier_plan(ctx):
    """L'app de test ramenée au premier plan (son lanceur)."""
    adb(
        "shell",
        "monkey",
        "-p",
        PAQUET,
        "-c",
        "android.intent.category.LAUNCHER",
        "1",
        executer=ctx.appareil.executer,
    )
    ctx.cdp.attendre(f"{APP_ETAT}.then(s => s.isActive)", delai=10)


def service_vivant(executer):
    """Vrai quand le processus de l'app de test tourne avec son service
    permanent démarré."""
    if not adb(
        "shell", "pidof", PAQUET, executer=executer, check=False
    ).strip():
        return False
    services = adb(
        "shell",
        "dumpsys",
        "activity",
        "services",
        PAQUET,
        executer=executer,
        check=False,
    )
    return "ChatPushService" in services


def tuer_processus(executer, pid):
    """La mort du processus de l'app de test, comme Android le tue faute
    de mémoire : SIGKILL par run-as quand la politique SELinux de l'appareil
    laisse run-as signaler l'app, sinon `am crash` sur son pid (une mort de
    la VM, sans boîte de dialogue pour une app à l'arrière-plan). Rend la
    manière employée."""
    try:
        adb("shell", "run-as", PAQUET, "kill", "-9", pid, executer=executer)
        return "SIGKILL"
    except RuntimeError:
        adb("shell", "am", "crash", pid, executer=executer)
        return "am crash"


def oublier_appareils(odoo_, ntfy):
    """Les appareils Web Push que le serveur tient sur le ntfy de la course
    supprimés : chaque scénario de notification en enregistre un nouveau
    (pm clear tire un nouveau sujet), et à 5 appareils d'un destinataire
    Odoo passe par une file que seule une tâche planifiée vide (les
    serveurs de la course n'en ont pas) : plus rien ne serait poussé."""
    anciens = odoo_.executer(
        "mail.push.device",
        "search",
        [[["endpoint", "=like", f"{ntfy['url']}/%"]]],
    )
    if anciens:
        odoo_.executer("mail.push.device", "unlink", [anciens])


def scenario_notifications(ctx):
    """Les notifications du clavardage, l'app fermée, par le ntfy de la
    course renvoyé au téléphone (adb reverse) : le lien appliqué au
    niveau 1, le ntfy est « connecté » et une seule notification permanente
    s'affiche. App à l'arrière-plan, un message de chat_user arrive en
    POUSSEE_DELAI au plus sous le tag de sa conversation, dans le canal du
    serveur, son texte en clair dans la notification et jamais sur l'écran
    verrouillé (PRIVATE avec « Nouveau message — <libellé> », ou SECRET,
    selon le réglage d'Android). Le processus tué, le service
    revient (START_STICKY, sinon la tâche forcée) et le message suivant
    s'empile dans la même notification. Touchée dans le volet, elle ouvre
    la conversation et s'efface. App au premier plan, rien ne s'affiche ;
    « Jamais affiché », titre et texte ne disent que « Nouveau message ».
    Le ntfy retiré, la tâche forcée affiche le sommaire direct d'Odoo
    « 2 nouveaux messages — <libellé> », sans rien marquer lu sur le
    serveur. Rend le délai mesuré de chaque poussée."""
    ntfy = ctx.cible.get("ntfy")
    assert ntfy, "aucun ntfy dans la course (commande ntfy absente)"
    executer = ctx.appareil.executer
    oublier_appareils(ctx.odoo, ntfy)
    pair = Odoo(ctx.cible, "chat")
    moi = ctx.odoo.lire("res.users", ctx.odoo.uid, ["partner_id"])[
        "partner_id"
    ][0]
    pair.executer("discuss.channel", "channel_get", [], {"partners_to": [moi]})
    canal = pair.executer(
        "discuss.channel",
        "search",
        [
            [
                ["channel_type", "=", "chat"],
                ["channel_partner_ids", "in", [moi]],
            ]
        ],
    )[0]

    def poster(texte):
        pair.route(
            "/mail/message/post",
            {
                "thread_model": "discuss.channel",
                "thread_id": canal,
                "post_data": {
                    "body": texte,
                    "message_type": "comment",
                    "subtype_xmlid": "mail.mt_comment",
                },
            },
        )

    ctx.appareil.autoriser_notifications()
    ctx.appareil.exempter_batterie()
    config = js(ctx.config_id)
    libelle = next(
        s["label"]
        for s in ctx.hook("chatSources()")
        if s["configId"] == ctx.config_id
    )
    tag = f"chat:{ctx.config_id}:{canal}"
    canal_android = f"chat.{empreinte(ctx.config_id)}"

    # 1. Le lien, le niveau 1, le ntfy connecté, une notification permanente
    ctx.hook(f"chatLoad({config})")
    applique = ctx.hook(f"chatPushApply({config}, {js(ntfy['link'])})")
    assert applique["ok"], f"lien refusé : {applique['reason']}"
    assert applique["registered"] == [ctx.config_id], applique
    ctx.hook("chatPushLevel(1)")
    ctx.cdp.attendre(
        "window.__erplibreTest.chatPushStatus().then(h => h.ntfys.some("
        f"n => n.url === {js(ntfy['url'])} && n.state === 'connected'))",
        delai=30,
    )
    sujet = ctx.hook(f"chatPushRow({config})")["topic"]
    fin = time.monotonic() + 10
    while True:
        permanentes = [n for n in notifications(executer) if n["flags"] & 0x2]
        if len(permanentes) == 1 or time.monotonic() > fin:
            break
        time.sleep(0.5)
    assert [n["id"] for n in permanentes] == [ID_PERMANENTE], permanentes
    assert permanentes[0]["canal"] == "erplibre_permanent", permanentes

    # 2. App à l'arrière-plan : la poussée chiffrée, déchiffrée et affichée
    accueil(ctx)
    premier = ctx.unique("poussee")
    poster(premier)
    notif, delai_2 = attendre_notification(
        ctx, tag, lambda n: premier in n["bloc"], delai=POUSSEE_DELAI
    )
    assert notif["canal"] == canal_android, notif["canal"]
    # « Masqué si verrouillé » : jamais le texte sur l'écran verrouillé.
    # PRIVATE, sa seule version publique « Nouveau message — <libellé> »,
    # là où Android masque le contenu sensible ; SECRET, rien sur l'écran
    # verrouillé, là où Android le montrerait. Vérifié par dumpsys, jamais
    # en verrouillant le téléphone
    bloc = notif["bloc"]
    if masque_verrouille(executer):
        assert notif["vis"] == "PRIVATE", notif["vis"]
        assert "publicVersion=" in bloc, "aucune version publique"
        publique = bloc[bloc.find("publicVersion=") :].split("\n", 1)[0]
        assert premier not in publique, "texte dans la version publique"
    else:
        # SECRET : rien sur l'écran verrouillé. La version publique reste
        # portée, pour qu'un nouvel affichage puisse revenir à PRIVATE ;
        # elle ne dit jamais le texte
        assert notif["vis"] == "SECRET", notif["vis"]
        if "publicVersion=" in bloc:
            publique = bloc[bloc.find("publicVersion=") :].split("\n", 1)[0]
            assert premier not in publique, "texte dans la version publique"
    ctx.capturer("notification_recue")

    # 3. Le processus tué : le service revient, le message suivant s'empile
    pid = adb("shell", "pidof", PAQUET, executer=executer).strip()
    maniere = tuer_processus(executer, pid)
    debut = time.monotonic()
    while (
        adb("shell", "pidof", PAQUET, executer=executer, check=False).strip()
        == pid
    ):
        time.sleep(0.2)
    force = False
    while not service_vivant(executer):
        ecoule = time.monotonic() - debut
        if ecoule > RETOUR_DELAI:
            raise TimeoutError(
                f"service absent {RETOUR_DELAI} s après la mort"
            )
        if not force and ecoule > RETOUR_COLLANT:
            adb(
                "shell",
                "cmd",
                "jobscheduler",
                "run",
                "-f",
                PAQUET,
                str(TACHE_PERIODIQUE),
                executer=executer,
            )
            force = True
        time.sleep(0.5)
    retour = time.monotonic() - debut
    second = ctx.unique("empilee")
    poster(second)
    _, delai_3 = attendre_notification(
        ctx,
        tag,
        lambda n: premier in n["bloc"] and second in n["bloc"],
        delai=30,
    )

    # 4. Touchée dans le volet : la conversation s'ouvre, la notification part
    toucher_notification(ctx, second)
    ctx.appareil.joindre()
    ctx.cdp = ctx.appareil.cdp
    chemin = f"/chat/{urllib.parse.quote(ctx.config_id, safe='')}/{canal}"
    ctx.cdp.attendre(f"location.pathname === {js(chemin)}", delai=30)
    fin = time.monotonic() + 10
    while any(n["tag"] == tag for n in notifications(executer)):
        assert time.monotonic() < fin, "notification restée après le toucher"
        time.sleep(0.5)
    ctx.capturer("conversation_ouverte")

    # 5. App au premier plan, sur la liste : rien ne s'affiche
    ctx.ouvrir("/chat", ".chat-list__row")
    ctx.cdp.attendre(f"{APP_ETAT}.then(s => s.isActive)", delai=5)
    avant = messages_ntfy(ntfy, sujet)
    troisieme = ctx.unique("premier-plan")
    poster(troisieme)
    fin = time.monotonic() + POUSSEE_DELAI
    while messages_ntfy(ntfy, sujet) == avant:
        assert time.monotonic() < fin, "le message n'atteint pas le ntfy"
        time.sleep(0.5)
    time.sleep(SILENCE)
    assert not any(
        n["tag"] == tag for n in notifications(executer)
    ), "notification affichée l'app au premier plan"

    # 6. « Jamais affiché » : rien du message, ni titre ni texte
    ctx.hook(f"chatPushLockScreen({config}, 'never')")
    accueil(ctx)
    quatrieme = ctx.unique("jamais")
    poster(quatrieme)
    notif, delai_6 = attendre_notification(ctx, tag, delai=POUSSEE_DELAI)
    assert extra(notif, "android.title") == "Nouveau message", notif["bloc"]
    assert extra(notif, "android.text") == "Nouveau message", notif["bloc"]
    assert quatrieme not in notif["bloc"], "texte du message affiché"
    assert notif["vis"] == "PUBLIC", notif["vis"]

    # 7. Le ntfy retiré : le sommaire direct d'Odoo, rien marqué lu
    premier_plan(ctx)
    ctx.ouvrir(
        f"/chat/{urllib.parse.quote(ctx.config_id, safe='')}/{canal}",
        ".chat-thread__input",
    )
    dernier = pair.executer(
        "mail.message",
        "search",
        [[["model", "=", "discuss.channel"], ["res_id", "=", canal]]],
        {"limit": 1, "order": "id desc"},
    )[0]
    # Le fil s'ouvre sur le premier non-lu ; il se lit une fois en bas, comme
    # quand un doigt le fait défiler
    fin = time.monotonic() + 20
    while vu_de(ctx.odoo, canal, moi) != dernier:
        assert time.monotonic() < fin, "la conversation ouverte reste non lue"
        ctx.cdp.evaluer(
            "(() => { const e = document.querySelector('.chat-thread__scroll');"
            " if (e) e.scrollTop = e.scrollHeight; })()"
        )
        time.sleep(0.5)
    ctx.hook(f"chatPushRemove({config})")
    accueil(ctx)
    # Le sommaire compte tout le non-lu du compte, celui des scénarios
    # d'avant compris : lu sur le serveur, puis relevé une fois, il part de 0
    tout_lire(ctx.odoo, moi)
    tache_forcee(ctx)
    vu_avant = vu_de(ctx.odoo, canal, moi)
    attente_avant = ctx.odoo.executer(
        "mail.notification",
        "search_count",
        [[["res_partner_id", "=", moi], ["is_read", "=", False]]],
    )
    for rang in (1, 2):
        poster(ctx.unique(f"sommaire-{rang}"))
    tache_forcee(ctx)
    titre = f"2 nouveaux messages — {libelle}"
    notif, _ = attendre_notification(
        ctx,
        f"summary:{ctx.config_id}",
        lambda n: extra(n, "android.title") == titre,
        delai=60,
    )
    ctx.capturer("sommaire_odoo")
    assert vu_de(ctx.odoo, canal, moi) == vu_avant, "sommaire marqué lu"
    assert (
        ctx.odoo.executer(
            "mail.notification",
            "search_count",
            [[["res_partner_id", "=", moi], ["is_read", "=", False]]],
        )
        == attente_avant
    ), "sommaire a lu la boîte de réception"
    return (
        f"poussée → notification {delai_2:.1f} s, service revenu en"
        f" {retour:.1f} s après {maniere}"
        f" ({'tâche forcée' if force else 'START_STICKY'}),"
        f" empilée en {delai_3:.1f} s, « jamais affiché » en {delai_6:.1f} s"
    )


# ─── Actions du clavardage, app tuée ──────────────────────────────────────────

# Le délai le plus long d'un toucher d'action à son effet sur le serveur
ACTION_DELAI = 15
# Le temps laissé à un second envoi d'une réponse qui ne doit pas venir
DOUBLON_DELAI = 60
# Les trois boutons qu'Android dessine sur une notification de
# conversation : « 👍 » en troisième quand le dernier message a un id
# (module 1.5), « Muet 1 h » sinon
ACTIONS_CLAVARDAGE = ["Répondre", "Marquer lu", "👍"]
ACTIONS_SANS_ID = ["Répondre", "Marquer lu", "Muet 1 h"]
ACTION = re.compile(r'^\s*\[\d+\] "(?P<titre>.*)" -> ', re.MULTILINE)
ENVOI_REPONSE = "com.android.systemui:id/remote_input_send"


def actions_de(notification):
    """Les titres des actions de la notification, dans l'ordre (le bloc
    actions={…} de dumpsys notification)."""
    bloc = notification["bloc"]
    debut = bloc.find("actions={")
    if debut < 0:
        return []
    titres = []
    # Une ligne par action, son PendingIntent{…} compris ; le bloc se
    # ferme sur une ligne qui ne porte que « } »
    for ligne in bloc[debut:].splitlines()[1:]:
        if ligne.strip() == "}":
            break
        trouve = ACTION.match(ligne)
        if trouve:
            titres.append(trouve["titre"])
    return titres


# Les paquets que porte la rangée d'une notification de l'app de test : son
# contenu est à l'app, son cadre, le champ de réponse et son envoi à SystemUI
PAQUETS_RANGEE = (PAQUET, "com.android.systemui")
# La vue de SystemUI qui porte une notification du volet (AOSP,
# ExpandableNotificationRow) : ses boutons, son champ de réponse et son
# envoi sont dedans
RANGEE_NOTIFICATION = "com.android.systemui:id/expandableNotificationRow"
# Le libellé du chevron qui déplie une notification repliée
DEPLIER = ("Développer", "Expand")


def arbre_ui(executer):
    """La racine du relevé uiautomator de l'écran, None quand le relevé
    échoue (une animation en cours)."""
    adb(
        "shell",
        "uiautomator",
        "dump",
        CONTENU_UI,
        executer=executer,
        check=False,
    )
    try:
        contenu = adb(
            "shell", "cat", CONTENU_UI, executer=executer, check=False
        )
    finally:
        adb("shell", "rm", "-f", CONTENU_UI, executer=executer, check=False)
    debut = contenu.find("<?xml")
    if debut < 0:
        return None
    try:
        return ET.fromstring(contenu[debut:])
    except ET.ParseError:
        return None


def bornes(noeud):
    """Les bornes (x1, y1, x2, y2) d'un nœud de uiautomator."""
    return tuple(map(int, re.findall(r"\d+", noeud.get("bounds"))))


def porte(noeud, ligne):
    """Vrai quand le nœud est de PAQUET et que son texte porte ligne."""
    return noeud.get("package") == PAQUET and ligne in (
        noeud.get("text") or ""
    )


def rangee(racine, ligne):
    """La rangée (expandableNotificationRow de SystemUI) de la
    notification de l'app de test qui affiche ligne, ou None. Depuis
    chaque nœud de PAQUET dont le texte porte ligne, la rangée est son
    plus proche ancêtre RANGEE_NOTIFICATION ; elle n'est retenue que si
    aucun de ses nœuds n'est d'un autre paquet que PAQUETS_RANGEE. Une
    seule rangée doit porter ligne : deux (deux notifications de l'app
    qui l'affichent) ou aucune, et rien n'est désigné. Le titre et le
    texte d'une même notification peuvent porter ligne tous deux (« Nouveau
    message » d'un serveur « Jamais affiché ») : c'est une rangée."""
    if racine is None:
        return None
    parents = {enfant: parent for parent in racine.iter() for enfant in parent}
    rangees = []
    for texte in racine.iter("node"):
        if not porte(texte, ligne):
            continue
        haut = parents.get(texte)
        while (
            haut is not None
            and haut.tag == "node"
            and haut.get("resource-id") != RANGEE_NOTIFICATION
        ):
            haut = parents.get(haut)
        if haut is None or haut.tag != "node":
            return None
        if haut not in rangees:
            rangees.append(haut)
    if len(rangees) != 1:
        return None
    seule = rangees[0]
    if any(n.get("package") not in PAQUETS_RANGEE for n in seule.iter("node")):
        return None
    return seule


def dedans(noeud, cadre):
    """Vrai quand les bornes du nœud tiennent dans celles du cadre."""
    x1, y1, x2, y2 = bornes(noeud)
    c1, d1, c2, d2 = bornes(cadre)
    return c1 <= x1 and d1 <= y1 and x2 <= c2 and y2 <= d2


def dans_rangee(racine, ligne, choisir):
    """Le premier nœud de la rangée de ligne (rangee) pour lequel
    choisir(nœud) est vrai et dont les bornes tiennent dans celles de la
    rangée ; None sinon."""
    haut = rangee(racine, ligne)
    if haut is None:
        return None
    return next(
        (n for n in haut.iter("node") if choisir(n) and dedans(n, haut)),
        None,
    )


def toucher(executer, noeud):
    """Un toucher au centre du nœud."""
    x1, y1, x2, y2 = bornes(noeud)
    adb(
        "shell",
        "input",
        "tap",
        str((x1 + x2) // 2),
        str((y1 + y2) // 2),
        executer=executer,
    )


def toucher_dans(executer, quoi, ligne, choisir, delai=10):
    """Touche le premier nœud pour lequel choisir(nœud) est vrai dans la
    rangée de la notification de l'app de test qui affiche ligne
    (dans_rangee), relevée par uiautomator jusqu'à delai secondes ;
    TimeoutError nommant quoi sinon. Rien hors de cette rangée n'est
    jamais touché : la notification d'une autre app, même dépliée
    au-dessus, garde son « Répondre », son champ et son envoi."""
    fin = time.monotonic() + delai
    while True:
        noeud = dans_rangee(arbre_ui(executer), ligne, choisir)
        if noeud is not None:
            toucher(executer, noeud)
            return
        if time.monotonic() > fin:
            raise TimeoutError(
                f"{quoi} absent de la notification « {ligne} » en {delai} s"
            )
        time.sleep(POSE)


def deplier(executer, ligne):
    """Déplie la notification de l'app de test qui affiche ligne : le
    chevron « Développer » de sa rangée le plus bas de ceux qui commencent
    au-dessus de cette ligne. Vrai quand il a été touché."""
    haut = rangee(arbre_ui(executer), ligne)
    if haut is None:
        return False
    texte = next(n for n in haut.iter("node") if porte(n, ligne))
    chevrons = [
        n
        for n in haut.iter("node")
        if n.get("content-desc") in DEPLIER
        and bornes(n)[1] <= bornes(texte)[1]
        and dedans(n, haut)
    ]
    if not chevrons:
        return False
    toucher(executer, max(chevrons, key=lambda n: bornes(n)[1]))
    return True


def toucher_action(ctx, titre, ligne, delai=20):
    """Le bouton d'action titre (sans égard à la casse : Android peut
    l'afficher en capitales) de la notification de l'app de test qui
    affiche ligne, touché à ses bornes (toucher_dans : jamais hors de sa
    rangée). Seule la première notification du volet s'affiche dépliée,
    ses boutons visibles : une autre (le débogage USB passé au-dessus) est
    dépliée par son chevron. Chaque relevé rouvre le volet, refermé
    d'abord à partir du second : un volet que l'action d'avant referme en
    s'animant ignore une ouverture demandée pendant l'animation."""
    executer = ctx.appareil.executer
    fin = time.monotonic() + delai
    essai = 0
    bouton = (
        lambda n: (n.get("text") or "").casefold() == titre.casefold()
        and n.get("clickable") == "true"
    )
    while True:
        if essai:
            adb("shell", "cmd", "statusbar", "collapse", executer=executer)
            time.sleep(POSE)
        adb(
            "shell",
            "cmd",
            "statusbar",
            "expand-notifications",
            executer=executer,
        )
        time.sleep(POSE)
        essai += 1
        try:
            toucher_dans(executer, titre, ligne, bouton, delai=0)
            return
        except TimeoutError:
            pass
        if deplier(executer, ligne):
            time.sleep(POSE)
            try:
                toucher_dans(executer, titre, ligne, bouton, delai=0)
                return
            except TimeoutError:
                pass
        if time.monotonic() > fin:
            raise TimeoutError(
                f"le bouton « {titre} » absent de la notification"
                f" « {ligne} » en {delai} s ({essai} ouvertures)"
            )


def champ_focalise(noeud):
    """Vrai pour le champ de réponse qui a le focus."""
    return (
        noeud.get("class") == "android.widget.EditText"
        and noeud.get("focused") == "true"
    )


def attendre_dans(executer, quoi, ligne, choisir, delai):
    """Le nœud de la rangée de ligne pour lequel choisir est vrai
    (dans_rangee), relevé jusqu'à delai secondes ; TimeoutError nommant
    quoi sinon."""
    fin = time.monotonic() + delai
    while True:
        noeud = dans_rangee(arbre_ui(executer), ligne, choisir)
        if noeud is not None:
            return noeud
        if time.monotonic() > fin:
            raise TimeoutError(
                f"{quoi} absent de la notification « {ligne} » en {delai} s"
            )
        time.sleep(POSE)


def champ_seul_dans_rangee(executer, ligne, delai):
    """Attend, jusqu'à delai secondes, un relevé où le seul champ focalisé
    de tout l'écran est celui de la rangée de ligne ; TimeoutError sinon,
    avant que rien ne soit tapé."""
    fin = time.monotonic() + delai
    while True:
        racine = arbre_ui(executer)
        focalises = (
            [n for n in racine.iter("node") if champ_focalise(n)]
            if racine is not None
            else []
        )
        notre = dans_rangee(racine, ligne, champ_focalise)
        if len(focalises) == 1 and notre is focalises[0]:
            return
        if time.monotonic() > fin:
            raise TimeoutError(
                f"{len(focalises)} champ(s) focalisé(s), le champ de la"
                f" notification « {ligne} » pas seul : rien n'est tapé"
            )
        time.sleep(POSE)


def mots_ailleurs(executer, ligne, mots):
    """Les paquets des nœuds hors de la rangée de ligne dont le texte
    porte mots, relevés une fois : où une saisie a pu atterrir. Rien n'y
    est touché."""
    racine = arbre_ui(executer)
    if racine is None:
        return []
    haut = rangee(racine, ligne)
    dedans_rangee = set(haut.iter("node")) if haut is not None else set()
    return sorted(
        {
            n.get("package")
            for n in racine.iter("node")
            if n not in dedans_rangee and mots in (n.get("text") or "")
        }
    )


def repondre_du_volet(ctx, mots, ligne, delai=20):
    """« Répondre » de la notification de l'app de test qui affiche ligne
    touché, mots tapés (input text, ASCII sans espace) une fois relevé
    que le seul champ focalisé de l'écran est celui de cette rangée,
    puis, le champ de la rangée relu et portant mots, son bouton d'envoi
    touché ; l'instant de l'envoi (time.monotonic). Un autre champ
    focalisé : rien n'est tapé. Un champ qui ne porte pas mots : rien
    n'est envoyé, et l'échec nomme le paquet d'un nœud hors de la rangée
    qui porterait les mots, sans jamais y toucher."""
    executer = ctx.appareil.executer
    toucher_action(ctx, "Répondre", ligne, delai=delai)
    champ_seul_dans_rangee(executer, ligne, delai)
    adb("shell", "input", "text", mots, executer=executer)
    try:
        attendre_dans(
            executer,
            f"le champ portant « {mots} »",
            ligne,
            lambda n: champ_focalise(n) and n.get("text") == mots,
            delai,
        )
    except TimeoutError as echec:
        ailleurs = mots_ailleurs(executer, ligne, mots)
        if ailleurs:
            raise TimeoutError(
                f"mots tapés hors de la notification « {ligne} », dans"
                f" {', '.join(ailleurs)} : rien n'est envoyé"
            ) from echec
        raise
    toucher_dans(
        executer,
        "le bouton d'envoi de la réponse",
        ligne,
        lambda n: n.get("resource-id") == ENVOI_REPONSE
        and n.get("enabled") == "true",
        delai=delai,
    )
    return time.monotonic()


def ecran_allume(executer):
    """Vrai quand l'écran est allumé (mWakefulness=Awake de dumpsys
    power)."""
    return "mWakefulness=Awake" in adb(
        "shell", "dumpsys", "power", executer=executer
    )


def attendre_retour_service(ctx, pid):
    """Attend la mort du processus pid de l'app de test, puis le retour
    de son service permanent (START_STICKY, sinon la tâche périodique
    forcée après RETOUR_COLLANT) ; (secondes, forcée)."""
    executer = ctx.appareil.executer
    # Le compte part de la mort : `am crash` peut laisser le processus
    # vivre jusqu'à une minute avant qu'Android le tue
    fin = time.monotonic() + RETOUR_DELAI
    while (
        adb("shell", "pidof", PAQUET, executer=executer, check=False).strip()
        == pid
    ):
        if time.monotonic() > fin:
            raise TimeoutError(f"processus {pid} vivant {RETOUR_DELAI} s")
        time.sleep(0.2)
    debut = time.monotonic()
    force = False
    while not service_vivant(executer):
        ecoule = time.monotonic() - debut
        if ecoule > RETOUR_DELAI:
            raise TimeoutError(
                f"service absent {RETOUR_DELAI} s après la mort"
            )
        if not force and ecoule > RETOUR_COLLANT:
            adb(
                "shell",
                "cmd",
                "jobscheduler",
                "run",
                "-f",
                PAQUET,
                str(TACHE_PERIODIQUE),
                executer=executer,
            )
            force = True
        time.sleep(0.5)
    return time.monotonic() - debut, force


def tuer_app(ctx):
    """Le processus de l'app de test tué (tuer_processus) et son service
    revenu ; la page morte n'est plus jointe. Rend la manière employée."""
    executer = ctx.appareil.executer
    pid = adb("shell", "pidof", PAQUET, executer=executer).strip()
    maniere = tuer_processus(executer, pid)
    attendre_retour_service(ctx, pid)
    return maniere


def scenario_actions_notifications(ctx):
    """Les actions d'une notification de conversation, l'app tuée, le
    module 1.5 sur le serveur de la course : le lien appliqué au niveau 1,
    l'appareil marqué comme celui de l'app. Le processus tué, un message
    de chat_user s'affiche avec ses trois boutons. « Répondre », tapé
    dans le volet, poste une seule fois la réponse, et la poussée de
    lecture de l'auteur efface la notification ; « Marquer lu » lit la
    conversation jusqu'au message ; « 👍 » réagit au message et la
    notification reste, « Muet 1 h » à la place de « 👍 » ; « Muet 1 h »
    la met en sourdine pour une heure. Une lecture dans le navigateur
    efface la notification. « Jamais affiché », la notification ne dit
    que « Nouveau message », avec les mêmes boutons, et la réponse part
    quand même. La copie de session du natif cassée, la réponse est
    confiée à l'app : la notification de reprise s'affiche, touchée elle
    ouvre l'app, qui poste la réponse une fois. L'appareil démarqué, une
    poussée sans id de message offre « Muet 1 h » en troisième. Rend les
    délais mesurés."""
    ntfy = ctx.cible.get("ntfy")
    assert ntfy, "aucun ntfy dans la course (commande ntfy absente)"
    executer = ctx.appareil.executer
    oublier_appareils(ctx.odoo, ntfy)
    pair = Odoo(ctx.cible, "chat")
    moi = ctx.odoo.lire("res.users", ctx.odoo.uid, ["partner_id"])[
        "partner_id"
    ][0]
    pair.executer("discuss.channel", "channel_get", [], {"partners_to": [moi]})
    canal = pair.executer(
        "discuss.channel",
        "search",
        [
            [
                ["channel_type", "=", "chat"],
                ["channel_partner_ids", "in", [moi]],
            ]
        ],
    )[0]

    def poster(texte):
        reponse = pair.route(
            "/mail/message/post",
            {
                "thread_model": "discuss.channel",
                "thread_id": canal,
                "post_data": {
                    "body": texte,
                    "message_type": "comment",
                    "subtype_xmlid": "mail.mt_comment",
                },
            },
        )
        return reponse["mail.message"][0]["id"]

    def miens(mots):
        """Les messages d'admin dans le canal dont le corps porte mots."""
        return ctx.odoo.executer(
            "mail.message",
            "search",
            [
                [
                    ["model", "=", "discuss.channel"],
                    ["res_id", "=", canal],
                    ["author_id", "=", moi],
                    ["body", "ilike", mots],
                ]
            ],
        )

    def affichee(texte=None):
        """La notification de la conversation, quand elle est affichée
        (et porte texte, s'il est donné), sinon None."""
        return next(
            (
                n
                for n in notifications(executer)
                if n["tag"] == tag and (texte is None or texte in n["bloc"])
            ),
            None,
        )

    def partie(quoi, delai=ACTION_DELAI):
        """Attend que la notification de la conversation soit partie ;
        le temps écoulé."""
        debut = time.monotonic()
        attendre_serveur(quoi, lambda: affichee() is None, delai)
        return time.monotonic() - debut

    def capturer(nom):
        assert ecran_allume(executer), f"écran éteint avant « {nom} »"
        ctx.capturer(nom)

    def sourdine(minutes):
        ctx.odoo.route(
            "/discuss/settings/mute", {"channel_id": canal, "minutes": minutes}
        )

    ctx.appareil.autoriser_notifications()
    ctx.appareil.exempter_batterie()
    config = js(ctx.config_id)
    tag = f"chat:{ctx.config_id}:{canal}"
    reprise = f"handoff:{ctx.config_id}"
    try:
        # 1. Le lien, le niveau 1, le ntfy connecté, l'appareil marqué
        ctx.hook(f"chatLoad({config})")
        applique = ctx.hook(f"chatPushApply({config}, {js(ntfy['link'])})")
        assert applique["ok"], f"lien refusé : {applique['reason']}"
        ctx.hook("chatPushLevel(1)")
        ctx.cdp.attendre(
            "window.__erplibreTest.chatPushStatus().then(h => h.ntfys.some("
            f"n => n.url === {js(ntfy['url'])} && n.state === 'connected'))",
            delai=30,
        )
        point = ctx.hook(f"chatPushRow({config})")["endpoint"]
        attendre_serveur(
            "l'appareil marqué comme celui de l'app",
            lambda: ctx.odoo.executer(
                "mail.push.device",
                "search_count",
                [[["endpoint", "=", point], ["erplibre_app", "=", True]]],
            ),
        )

        # 2. App tuée : le message s'affiche avec ses trois boutons
        accueil(ctx)
        maniere = tuer_app(ctx)
        ctx.cdp = None
        premier = ctx.unique("actions")
        poster(premier)
        notif, delai_2 = attendre_notification(
            ctx, tag, lambda n: premier in n["bloc"], delai=POUSSEE_DELAI
        )
        assert actions_de(notif) == ACTIONS_CLAVARDAGE, actions_de(notif)
        capturer("actions_notification")

        # 3. « Répondre » : une seule réponse, la notification effacée
        mots = f"reponse{int(time.time())}a"
        envoi = repondre_du_volet(ctx, mots, premier)
        capturer("actions_reponse_envoyee")
        attendre_serveur(
            "la réponse sur le serveur", lambda: miens(mots), ACTION_DELAI
        )
        delai_reponse = time.monotonic() - envoi
        partie("la notification après la réponse")
        time.sleep(DOUBLON_DELAI)
        assert len(miens(mots)) == 1, f"réponse postée {len(miens(mots))} fois"

        # 4. « Marquer lu » : la conversation lue jusqu'au message
        lire = ctx.unique("a-lire")
        ident = poster(lire)
        attendre_notification(ctx, tag, lambda n: lire in n["bloc"])
        toucher_action(ctx, "Marquer lu", lire)
        attendre_serveur(
            "la conversation lue",
            lambda: vu_de(ctx.odoo, canal, moi) == ident,
            ACTION_DELAI,
        )
        partie("la notification après « Marquer lu »")

        # 5. « 👍 » : une réaction d'admin, « Muet 1 h » à la place de « 👍 »
        pouce = ctx.unique("pouce")
        ident = poster(pouce)
        attendre_notification(
            ctx,
            tag,
            lambda n: pouce in n["bloc"]
            and actions_de(n) == ACTIONS_CLAVARDAGE,
        )
        toucher_action(ctx, "👍", pouce)
        attendre_serveur(
            "le 👍 sur le serveur",
            lambda: reactions_serveur(ctx.odoo, ident) == [("👍", moi)],
            ACTION_DELAI,
        )
        notif, _ = attendre_notification(
            ctx, tag, lambda n: "👍" not in actions_de(n), ACTION_DELAI
        )
        assert actions_de(notif) == ACTIONS_SANS_ID, actions_de(notif)

        # 6. « Muet 1 h », offert une fois le 👍 donné : la sourdine d'une
        # heure, puis levée
        touche = time.time()
        toucher_action(ctx, "Muet 1 h", pouce)
        fin_muet = attendre_serveur(
            "la sourdine",
            lambda: ctx.odoo.executer(
                "discuss.channel.member",
                "search_read",
                [[["channel_id", "=", canal], ["partner_id", "=", moi]]],
                {"fields": ["mute_until_dt"]},
            )[0]["mute_until_dt"],
            ACTION_DELAI,
        )
        fin_epoch = calendar.timegm(
            time.strptime(fin_muet, "%Y-%m-%d %H:%M:%S")
        )
        assert abs(fin_epoch - (touche + 3600)) < 120, fin_muet
        partie("la notification après « Muet 1 h »")
        sourdine(0)

        # 7. Lu dans le navigateur : la notification part
        dernier = ctx.unique("lu-ailleurs")
        ident = poster(dernier)
        attendre_notification(ctx, tag, lambda n: dernier in n["bloc"])
        navigateur = Odoo(ctx.cible)
        lu = time.monotonic()
        navigateur.route(
            "/discuss/channel/mark_as_read",
            {"channel_id": canal, "last_message_id": ident},
        )
        partie("la notification après la lecture au navigateur")
        delai_lecture = time.monotonic() - lu

        # 7b. « Jamais affiché » : « Nouveau message » et les mêmes boutons
        # La page est morte avec le processus : l'app relancée, sa page
        # jointe à nouveau
        adb(
            "shell",
            "monkey",
            "-p",
            PAQUET,
            "-c",
            "android.intent.category.LAUNCHER",
            "1",
            executer=executer,
        )
        ctx.appareil.joindre()
        ctx.cdp = ctx.appareil.cdp
        ctx.cdp.attendre(f"{APP_ETAT}.then(s => s.isActive)", delai=30)
        ctx.hook(f"chatPushLockScreen({config}, 'never')")
        accueil(ctx)
        cache = ctx.unique("jamais")
        poster(cache)
        notif, _ = attendre_notification(ctx, tag, delai=POUSSEE_DELAI)
        assert extra(notif, "android.title") == "Nouveau message", notif[
            "bloc"
        ]
        assert extra(notif, "android.text") == "Nouveau message", notif["bloc"]
        assert cache not in notif["bloc"], "texte du message affiché"
        assert actions_de(notif) == ACTIONS_CLAVARDAGE, actions_de(notif)
        mots_caches = f"cachee{int(time.time())}b"
        repondre_du_volet(ctx, mots_caches, "Nouveau message")
        capturer("actions_jamais_affiche")
        attendre_serveur(
            "la réponse « jamais affiché »",
            lambda: miens(mots_caches),
            ACTION_DELAI,
        )
        fin = time.monotonic() + ACTION_DELAI
        while (restante := affichee()) is not None:
            assert mots_caches not in restante["bloc"], "réponse affichée"
            assert (
                extra(restante, "android.text") == "Nouveau message"
            ), restante["bloc"]
            assert time.monotonic() < fin, "notification restée"
            time.sleep(0.5)
        assert len(miens(mots_caches)) == 1, "réponse postée plus d'une fois"
        premier_plan(ctx)
        ctx.hook(f"chatPushLockScreen({config}, 'hidden_locked')")

        # 8. Session du natif cassée : la réponse confiée à l'app. Le retour
        # au premier plan recopie la vraie session au natif après son
        # chargement : un chargement de plus, rangé derrière, puis la copie
        # cassée, une fois le travail des notifications en file achevé
        ctx.hook(f"chatLoad({config})")
        ctx.hook(f"chatPushBreakSession({config})")
        accueil(ctx)
        tuer_app(ctx)
        ctx.cdp = None
        confie = ctx.unique("confie")
        poster(confie)
        attendre_notification(
            ctx, tag, lambda n: confie in n["bloc"], delai=POUSSEE_DELAI
        )
        mots_confies = f"confiee{int(time.time())}c"
        repondre_du_volet(ctx, mots_confies, confie)
        attendre_notification(ctx, reprise, delai=ACTION_DELAI)
        assert not miens(mots_confies), "réponse postée par une session morte"
        capturer("actions_reprise")
        # « Ouvrez l'app pour terminer … » : la notification de reprise,
        # pas celle d'état d'une session expirée (« … pour reprendre … »)
        toucher_notification(ctx, "pour terminer")
        ctx.appareil.joindre()
        ctx.cdp = ctx.appareil.cdp
        attendre_serveur(
            "la réponse confiée sur le serveur",
            lambda: miens(mots_confies),
            60,
        )
        attendre_serveur(
            "la notification de reprise retirée",
            lambda: not any(
                n["tag"] == reprise for n in notifications(executer)
            ),
            ACTION_DELAI,
        )
        attendre_serveur(
            "le magasin d'actions vidé",
            lambda: ctx.hook("chatPushActions()") == [],
            ACTION_DELAI,
        )
        time.sleep(DOUBLON_DELAI)
        assert (
            len(miens(mots_confies)) == 1
        ), "réponse confiée postée deux fois"

        # 9. Un appareil que le module ne connaît pas : les poussées
        # d'Odoo, sans id de message, offrent « Muet 1 h » en troisième
        ctx.odoo.executer(
            "mail.push.device",
            "write",
            [
                ctx.odoo.executer(
                    "mail.push.device",
                    "search",
                    [[["endpoint", "=", point]]],
                ),
                {"erplibre_app": False},
            ],
        )
        accueil(ctx)
        sans_module = ctx.unique("sans-module")
        poster(sans_module)
        notif, _ = attendre_notification(
            ctx, tag, lambda n: sans_module in n["bloc"], POUSSEE_DELAI
        )
        assert actions_de(notif) == ACTIONS_SANS_ID, actions_de(notif)
        assert ecran_allume(executer), "écran éteint pendant le scénario"
    finally:
        adb(
            "shell",
            "cmd",
            "statusbar",
            "collapse",
            executer=executer,
            check=False,
        )
        sourdine(0)
    return (
        f"poussée → notification {delai_2:.1f} s après {maniere},"
        f" envoi de la réponse → message dans Odoo {delai_reponse:.1f} s,"
        f" lecture au navigateur → notification partie {delai_lecture:.1f} s"
    )


# (nom, scénario, versions d'Odoo qui le jouent) : le chat de l'app ne
# parle qu'à la 18
SCENARIOS = (
    ("sélecteur de cibles", scenario_selecteur, odoo.VERSIONS),
    ("bandeau de date", scenario_bandeau_date, odoo.VERSIONS),
    ("saisie pendant un pull", scenario_saisie_pendant_pull, odoo.VERSIONS),
    ("note datée du calendrier", scenario_calendrier, odoo.VERSIONS),
    ("clavardage", scenario_clavardage, (18,)),
    ("groupe créé du téléphone", scenario_groupe, (18,)),
    ("pièces jointes du clavardage", scenario_pieces_jointes, (18,)),
    ("actions du clavardage", scenario_actions_clavardage, (18,)),
    (
        "recherche et boîte du clavardage",
        scenario_recherche_boite,
        (18,),
    ),
    (
        "notifications du clavardage, app fermée",
        scenario_notifications,
        (18,),
    ),
    (
        "actions du clavardage, app tuée",
        scenario_actions_notifications,
        (18,),
    ),
)


def scenarios_de(version):
    """Les scénarios (nom, fonction) que joue la version d'Odoo donnée."""
    return [(nom, f) for nom, f, versions in SCENARIOS if version in versions]


def ports_de(cibles):
    """Les ports à renvoyer vers l'hôte : celui de chaque serveur, puis celui
    du ntfy de la course quand une cible en porte un ; chacun une fois."""
    urls = [c["url"] for c in cibles] + [
        c["ntfy"]["url"] for c in cibles if c.get("ntfy")
    ]
    ports = []
    for url in urls:
        port = int(url.rsplit(":", 1)[1])
        if port not in ports:
            ports.append(port)
    return ports


def lancer(cibles, repertoire, executer=subprocess.run, journal=print):
    """Les scénarios sur le téléphone, pour chaque cible : (total, échecs).
    Un échec garde une capture d'écran dans repertoire. L'app de
    l'utilisateur (APP_PERSO) est relevée avant et après : une date de mise
    à jour changée, ou devenue illisible, compte pour un échec de plus ;
    illisible dès le départ, la course s'arrête avant de toucher le
    téléphone (RuntimeError)."""
    avant = maj_app_perso(executer)
    appareil = Appareil(ports_de(cibles), executer)
    total = echecs = 0
    try:
        appareil.garder_allume()
        apk = construire_apk(executer=executer, journal=journal)
        appareil.preparer(apk)
        for cible in cibles:
            for nom, scenario in scenarios_de(cible["version"]):
                total += 1
                debut = time.monotonic()
                try:
                    appareil.relancer()
                    config_id = appareil.cdp.evaluer(
                        "window.__erplibreTest.addApplication("
                        + js(
                            {
                                "url": cible["url"],
                                "username": cible["admin"]["login"],
                                "password": cible["admin"]["password"],
                                "database": cible["database"],
                            }
                        )
                        + ")"
                    )
                    detail = scenario(
                        Contexte(
                            appareil.cdp,
                            Odoo(cible),
                            cible["version"],
                            config_id,
                            cible,
                            appareil,
                            repertoire=Path(repertoire),
                        )
                    )
                    journal(
                        f"  ✓ Odoo {cible['version']} — {nom} ({time.monotonic() - debut:.0f} s)"
                        + (f" : {detail}" if detail else "")
                    )
                except (
                    AssertionError,
                    ErreurPage,
                    TimeoutError,
                    RuntimeError,
                    OSError,
                ) as erreur:
                    echecs += 1
                    capture = (
                        Path(repertoire)
                        / f"appareil_{cible['version']}_{scenario.__name__}.png"
                    )
                    try:
                        appareil.capture(capture)
                    except RuntimeError:
                        capture = None
                    journal(
                        f"  ✗ Odoo {cible['version']} — {nom} : {type(erreur).__name__} {erreur}"
                    )
                    if capture:
                        journal(f"    capture : {capture}")
    finally:
        appareil.rendre()
    try:
        apres = maj_app_perso(executer)
    except RuntimeError as erreur:
        apres = f"illisible ({erreur})"
    if apres != avant:
        echecs += 1
        journal(f"  ✗ {APP_PERSO} changée : {avant} avant, {apres} après")
    return total, echecs


def main(argv=None):
    sys.stdout.reconfigure(line_buffering=True)
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(__doc__)
        return 2
    problemes = verifier_appareil()
    if problemes:
        print("Prérequis manquants :")
        for probleme in problemes:
            print(f"  - {probleme}")
        return 2
    chemin = Path(argv[0])
    total, echecs = lancer(json.loads(chemin.read_text()), chemin.parent)
    print(f"Appareil : {total - echecs}/{total} scénarios passés")
    return 0 if total and not echecs else 1


if __name__ == "__main__":
    sys.exit(main())
