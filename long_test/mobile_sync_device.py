#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La synchronisation mobile de bout en bout, sur un téléphone branché.

Sept écrans que les tests d'intégration ne voient pas, joués sur l'app de
test (ca.erplibre.home.synctest, construite par -PsyncTest, à côté de l'app
de l'utilisateur qu'elle ne touche pas) contre les Odoo de la course : le
sélecteur de cibles, le bandeau d'une date changée sur le serveur, la saisie
pendant un pull, la note datée créée depuis le calendrier et, sur la 18
seulement, le clavardage, un groupe créé depuis le téléphone, dont le
temps réel passe par le websocket natif, et les pièces jointes du
clavardage (fichier, message vocal enregistré au micro, image et message
vocal reçus).

Le téléphone joint les serveurs par adb reverse (127.0.0.1 de l'appareil vers
celui de l'hôte) ; la page se pilote par CDP (mobile_sync_cdp.py), les écrans
par de vrais touchers, et la mise en place par window.__erplibreTest, que
seule une construction de développement contient. Pour chaque version, l'app
repart de zéro (pm clear) avec la seule application de ce serveur.

Lancé par ./long_test/mobile_sync.py --appareil, ou seul contre les serveurs
gardés d'une course :

  ./long_test/mobile_sync_device.py cache/mobile_sync/runs/<course>/targets.json
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mobile_sync_odoo as odoo  # noqa: E402
from mobile_sync_cdp import Cdp, ErreurPage  # noqa: E402

PAQUET = "ca.erplibre.home.synctest"
# L'app de l'utilisateur, à côté de l'app de test : une course ne la touche
# jamais, et lancer() le vérifie
APP_PERSO = "ca.erplibre.home"
DEVICE_HOOK_API = 4
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
        return contenu["result"], reponse

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

    def preparer(self, apk):
        adb("install", "-r", str(apk), executer=self.executer)
        self.reste_allume = adb(
            "shell",
            "settings",
            "get",
            "global",
            "stay_on_while_plugged_in",
            executer=self.executer,
        ).strip()
        adb("shell", "svc", "power", "stayon", "usb", executer=self.executer)
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

    def toucher_pose(self, selecteur, delai=10):
        """Touche selecteur une fois l'écran posé : son centre au même
        endroit trois relevés de suite, POSE secondes d'écart, et l'élément
        lui-même sous ce point. Un clavier qui s'ouvre redimensionne la
        page pendant son animation, et un doigt posé avant la fin tombe là
        où le bouton n'est plus."""
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
        self.cdp.toucher(selecteur)

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


def place_saisie(ctx, delai=10):
    """PLACE_SAISIE une fois la page posée (trois relevés identiques, POSE
    secondes d'écart), après avoir vérifié que ni la barre ni le bord de la
    partie visible ne couvrent la saisie."""
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


def echanger(ctx, pair, canal):
    """Dans la conversation canal ouverte : la saisie se tient au-dessus de
    la barre de navigation, clavier fermé puis ouvert ; un message tapé et
    envoyé arrive une fois sur le serveur, puis la réponse de pair
    (chat_user) s'affiche dans le fil par le websocket natif. Rend la place
    mesurée de la saisie."""
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
    texte = ctx.unique("message")
    # Un toucher par CDP ne donne pas toujours le focus, qu'insertText suit
    ctx.cdp.evaluer("document.querySelector('.chat-thread__input').focus()")
    ctx.cdp.taper(texte)
    ctx.cdp.attendre(
        f"document.querySelector('.chat-thread__input').value === {js(texte)}",
        delai=5,
    )
    ctx.toucher_pose(".chat-thread__send")

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

    # Marqué envoyé, le message a sa réponse du serveur et quitte l'outbox,
    # qui ne le poste plus : le compte du serveur est alors définitif
    ctx.cdp.attendre(
        f"window.__erplibreTest.chatMessages({js(ctx.config_id)}, {canal})"
        f".then(ms => ms.some(m => m.body.includes({js(texte)}) && m.status === 'sent'))",
        delai=30,
    )
    assert recus(texte) == 1, f"{texte} reçu {recus(texte)} fois"

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
)


def scenarios_de(version):
    """Les scénarios (nom, fonction) que joue la version d'Odoo donnée."""
    return [(nom, f) for nom, f, versions in SCENARIOS if version in versions]


def lancer(cibles, repertoire, executer=subprocess.run, journal=print):
    """Les scénarios sur le téléphone, pour chaque cible : (total, échecs).
    Un échec garde une capture d'écran dans repertoire. L'app de
    l'utilisateur (APP_PERSO) est relevée avant et après : une date de mise
    à jour changée, ou devenue illisible, compte pour un échec de plus ;
    illisible dès le départ, la course s'arrête avant de toucher le
    téléphone (RuntimeError)."""
    avant = maj_app_perso(executer)
    apk = construire_apk(executer=executer, journal=journal)
    appareil = Appareil(
        [int(c["url"].rsplit(":", 1)[1]) for c in cibles], executer
    )
    total = echecs = 0
    try:
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
