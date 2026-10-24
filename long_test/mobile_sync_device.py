#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La synchronisation mobile de bout en bout, sur un téléphone branché.

Quatre écrans que les tests d'intégration ne voient pas, joués sur l'app de
test (ca.erplibre.home.synctest, construite par -PsyncTest, à côté de l'app
de l'utilisateur qu'elle ne touche pas) contre les Odoo de la course : le
sélecteur de cibles, le bandeau d'une date changée sur le serveur, la saisie
pendant un pull, et la note datée créée depuis le calendrier.

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
import shutil
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mobile_sync_odoo as odoo  # noqa: E402
from mobile_sync_cdp import Cdp, ErreurPage  # noqa: E402

PAQUET = "ca.erplibre.home.synctest"
DEVICE_HOOK_API = 1
APK_CACHE = odoo.CACHE / "apk"
APK_PRODUIT = Path("android/app/build/outputs/apk/debug/app-debug.apk")
# Ce que le pull compare : write_date, à la seconde
SECONDE_SUIVANTE = 1.1


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
    """Le serveur d'une cible, vu par son admin, en JSON-RPC (/jsonrpc)."""

    def __init__(self, cible):
        self.url = cible["url"]
        self.base = cible["database"]
        self.mot_de_passe = cible["admin"]["password"]
        self.uid = self.appel(
            "common",
            "login",
            [self.base, cible["admin"]["login"], self.mot_de_passe],
        )

    def appel(self, service, methode, args):
        corps = json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "call",
                "params": {
                    "service": service,
                    "method": methode,
                    "args": args,
                },
            }
        ).encode()
        requete = urllib.request.Request(
            f"{self.url}/jsonrpc", corps, {"Content-Type": "application/json"}
        )
        reponse = json.load(urllib.request.urlopen(requete, timeout=60))
        if "error" in reponse:
            raise RuntimeError(
                reponse["error"].get("data", {}).get("message")
                or reponse["error"]
            )
        return reponse["result"]

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


SCENARIOS = (
    ("sélecteur de cibles", scenario_selecteur),
    ("bandeau de date", scenario_bandeau_date),
    ("saisie pendant un pull", scenario_saisie_pendant_pull),
    ("note datée du calendrier", scenario_calendrier),
)


def lancer(cibles, repertoire, executer=subprocess.run, journal=print):
    """Les scénarios sur le téléphone, pour chaque cible : (total, échecs).
    Un échec garde une capture d'écran dans repertoire."""
    apk = construire_apk(executer=executer, journal=journal)
    appareil = Appareil(
        [int(c["url"].rsplit(":", 1)[1]) for c in cibles], executer
    )
    total = echecs = 0
    try:
        appareil.preparer(apk)
        for cible in cibles:
            for nom, scenario in SCENARIOS:
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
                    scenario(
                        Contexte(
                            appareil.cdp,
                            Odoo(cible),
                            cible["version"],
                            config_id,
                        )
                    )
                    journal(
                        f"  ✓ Odoo {cible['version']} — {nom} ({time.monotonic() - debut:.0f} s)"
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
