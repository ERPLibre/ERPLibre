#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Poser la configuration de la passerelle dans l'application, par le câble.

Trois valeurs — URL, identifiant, secret — se saisissaient à la main sur un
écran de téléphone. Le secret fait soixante-quatre caractères hexadécimaux :
une faute de frappe y donne un 403 que rien à l'écran ne distingue d'une
panne de réseau, et il faut tout retaper pour en sortir.

L'application garde ces valeurs dans un `SharedPreferences` ordinaire, et
`adb shell run-as` ouvre le dossier privé d'une application DÉBOGABLE. On y
écrit donc le même fichier que l'écran aurait écrit.

Deux limites, et aucune n'est contournable :

- un paquet de production refuse `run-as`, c'est Android qui le refuse ;
- `SharedPreferences` garde sa copie en mémoire et réécrit le fichier à la
  prochaine modification, donc l'application est ARRÊTÉE avant l'écriture.
  Elle est à rouvrir ensuite, et son service de passerelle avec elle.
"""
from __future__ import annotations

import base64
import re
import shlex
import shutil
import subprocess
from pathlib import Path

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


#: Le paquet de l'application mobile ERPLibre.
PAQUET = "ca.erplibre.home"

#: Le fichier, relatif au dossier privé que `run-as` ouvre.
FICHIER_PREFS = "shared_prefs/erplibre_sms_gateway.xml"

#: Un `SharedPreferences` vide, tel que le cadriciel Android l'écrit.
PREFS_VIDE = (
    "<?xml version='1.0' encoding='utf-8' standalone='yes' ?>\n<map>\n</map>"
)

#: Nom de la copie gardée avant écriture, à côté de l'état de la
#: démonstration. Elle porte le secret précédent : elle vit donc dans le même
#: dossier en 0700, et nulle part ailleurs.
COPIE = "prefs-avant-appairage.xml"


class AppairageError(Exception):
    """Ce qui empêche de poser la configuration, dit en une phrase."""


def _adb(args, timeout=30, entree=None):
    """Lance `adb`, rend (code, sortie). Lève si `adb` manque."""
    if not shutil.which("adb"):
        raise AppairageError(t("sms_pair_no_adb"))
    res = subprocess.run(
        ["adb"] + list(args),
        capture_output=True,
        text=True,
        timeout=timeout,
        input=entree,
    )
    return res.returncode, (res.stdout or "") + (res.stderr or "")


def appareils() -> list:
    """Les numéros de série des appareils prêts, et eux seuls.

    `unauthorized` et `offline` sont écartés : ils figurent dans la liste et
    toute commande leur échoue, ce qui ferait chercher la panne dans
    l'application plutôt que dans le dialogue de confiance du téléphone.
    """
    _code, sortie = _adb(["devices"])
    prets = []
    for ligne in sortie.splitlines()[1:]:
        morceaux = ligne.split()
        if len(morceaux) == 2 and morceaux[1] == "device":
            prets.append(morceaux[0])
    return prets


def run_as_ouvre() -> tuple:
    """(possible, motif) — le dossier privé du paquet est-il accessible.

    Le motif rendu est celui d'`adb`, pas une traduction : « unknown package »
    et « not debuggable » demandent deux gestes différents, et les confondre
    ferait réinstaller une application qui est là.
    """
    code, sortie = _adb(["shell", "run-as", PAQUET, "ls", "shared_prefs"])
    if code == 0 and "run-as" not in sortie:
        return True, ""
    return False, sortie.strip().splitlines()[0] if sortie.strip() else ""


def lire_prefs() -> str:
    """Le fichier actuel, ou un `SharedPreferences` vide s'il n'existe pas."""
    code, sortie = _adb(
        ["shell", "run-as", PAQUET, "cat", FICHIER_PREFS], timeout=60
    )
    if code != 0 or not sortie.lstrip().startswith("<?xml"):
        return PREFS_VIDE
    # `adb shell` passe par un pseudo-terminal et traduit les fins de ligne.
    return sortie.replace("\r\n", "\n")


def dernier_defaut() -> str:
    """Ce que l'appareil lui-même retient de son dernier échec, ou "".

    La seule source qui parle de CE téléphone. Le journal du serveur est
    partagé par tout ce qui l'interroge : le refus d'un autre agent s'y lit
    comme celui du téléphone, et l'on va corriger un secret, ou une horloge,
    qui n'ont rien.
    """
    joignable, _motif = possible()
    if not joignable:
        return ""
    trouve = re.search(
        r'<string name="last_error">(.*?)</string>', lire_prefs(), re.S
    )
    if not trouve:
        return ""
    from xml.sax.saxutils import unescape

    return unescape(trouve.group(1)).strip()


def poser_valeurs(xml: str, chaines: dict, booleens: dict) -> str:
    """Le XML, avec ces clés posées. Fonction PURE : aucun téléphone requis.

    Les clés absentes sont ajoutées, les présentes remplacées, et TOUT LE
    RESTE est conservé : le fichier porte aussi le rythme d'interrogation, le
    quota de segments et les choix de journalisation, que l'application a
    reçus du serveur et que les écraser remettrait à des valeurs d'usine.

    Les valeurs sont échappées : un secret ne contient que de l'hexadécimal,
    mais une URL porte des « & » dès qu'elle a deux paramètres, et un « & »
    nu rend le fichier illisible — l'application repart alors de zéro sans
    rien dire.
    """
    from xml.sax.saxutils import escape

    sortie = xml
    for cle, valeur in chaines.items():
        ligne = f'    <string name="{cle}">{escape(str(valeur))}</string>'
        motif = re.compile(
            r'[ \t]*<string name="%s">.*?</string>' % re.escape(cle), re.S
        )
        sortie = _remplacer_ou_ajouter(sortie, motif, ligne)
    for cle, valeur in booleens.items():
        mot = "true" if valeur else "false"
        ligne = f'    <boolean name="{cle}" value="{mot}" />'
        motif = re.compile(
            r'[ \t]*<boolean name="%s" value="[^"]*" ?/>' % re.escape(cle)
        )
        sortie = _remplacer_ou_ajouter(sortie, motif, ligne)
    return sortie


def _remplacer_ou_ajouter(xml: str, motif, ligne: str) -> str:
    """La ligne prend la place de l'ancienne, ou s'ajoute avant `</map>`.

    Le remplacement passe par une fonction et non par une chaîne : `re.sub`
    lit les contre-obliques et les « \\1 » de son remplacement, et une URL en
    porte dès qu'elle vient d'un copier-coller malheureux.
    """
    if motif.search(xml):
        return motif.sub(lambda _m: ligne, xml, count=1)
    return xml.replace("</map>", ligne + "\n</map>", 1)


def url_sort_du_poste(url: str) -> bool:
    """Vrai quand l'URL désigne autre chose que la boucle locale.

    L'application refuse le HTTP en clair hors de la boucle tant que
    « tolérer le réseau local en clair » n'est pas posé : poser l'URL sans
    poser ce drapeau donnerait un refus au premier envoi, loin d'ici.
    """
    return not re.match(r"^https?://(127\.0\.0\.1|localhost)[:/]", url)


def ecrire_prefs(xml: str) -> None:
    """Écrit le fichier dans le dossier privé du paquet.

    Le contenu voyage en base64 : il traverse un shell, et une apostrophe ou
    un retour chariot dans une commande shell casserait le fichier sans que
    rien ne le dise avant le prochain démarrage de l'application.

    Le tube et la redirection sont CITÉS pour le shell d'Android. `adb shell`
    recolle ses arguments par des espaces sans les citer : laissés nus, ils
    reviennent au shell d'`adbd`, dont le répertoire courant n'est pas celui
    de l'application — la redirection échoue alors sur un chemin relatif que
    seul `run-as` sait atteindre.
    """
    charge = base64.b64encode(xml.encode("utf-8")).decode("ascii")
    interne = f"echo {charge} | base64 -d > {FICHIER_PREFS}"
    code, sortie = _adb(
        ["shell", f"run-as {PAQUET} sh -c {shlex.quote(interne)}"],
        timeout=60,
    )
    if code != 0:
        raise AppairageError(sortie.strip()[:300] or t("sms_pair_write_failed"))


def arreter_application() -> None:
    """Arrête l'application, copie en mémoire comprise."""
    _adb(["shell", "am", "force-stop", PAQUET], timeout=60)


#: Les permissions sans lesquelles la passerelle accepte le travail puis
#: refuse de l'exécuter, sur « GATEWAY_NO_PERMISSION ». Elles se demandent
#: normalement depuis l'écran de la passerelle, et une RÉINSTALLATION les
#: remet toutes à « refusée » : les reposer appartient donc à l'appairage,
#: qui suit chaque installation.
PERMISSIONS = (
    "android.permission.SEND_SMS",
    "android.permission.RECEIVE_SMS",
)


def accorder_permissions() -> list:
    """Accorde les permissions de la passerelle. Rend celles qui ont bougé.

    Rend une liste vide quand tout était déjà accordé, ce qui permet à
    l'appelant de n'en parler que lorsqu'il s'est passé quelque chose.
    """
    posees = []
    for permission in PERMISSIONS:
        if etat_permission(permission):
            continue
        code, _sortie = _adb(["shell", "pm", "grant", PAQUET, permission])
        if code == 0 and etat_permission(permission):
            posees.append(permission.rsplit(".", 1)[-1])
    return posees


def etat_permission(permission: str) -> bool:
    """Vrai quand l'appareil déclare cette permission accordée.

    `dumpsys` donne PLUSIEURS lignes par permission — « restricted=true »
    précède « granted=… » — et seule celle qui porte « granted » dit l'état.
    S'arrêter à la première conclut « refusée » même après un octroi réussi,
    et l'on repose alors sans fin une permission déjà là.
    """
    code, sortie = _adb(["shell", "dumpsys", "package", PAQUET], timeout=60)
    if code != 0:
        return False
    marque = permission + ": granted="
    etats = [ligne for ligne in sortie.splitlines() if marque in ligne]
    return bool(etats) and "granted=true" in etats[-1]


#: Le récepteur de l'application qui relance sa passerelle, et l'action que
#: le shell a le droit de lui envoyer. `BOOT_COMPLETED` et
#: `MY_PACKAGE_REPLACED` sont des diffusions PROTÉGÉES : Android n'autorise
#: que le système à les émettre, et `am broadcast` s'y voit refuser.
RECEPTEUR = ".SmsBootReceiver"
ACTION_REVEIL = "android.intent.action.QUICKBOOT_POWERON"


def reveiller_passerelle() -> bool:
    """Redémarre le service de passerelle de l'application.

    Arrêter l'application tue son service, et rouvrir son écran ne le relance
    pas : seul son récepteur de démarrage le fait, ou un geste humain sur le
    bouton. Sans ce réveil, la configuration est posée, l'application est
    ouverte, et plus rien n'interroge le serveur — ce qui se lit comme un
    silence réseau alors que tout est en place.

    Le récepteur vérifie lui-même que la passerelle est activée et
    configurée : on lui demande, on ne décide pas à sa place.
    """
    code, _sortie = _adb(
        [
            "shell",
            "am",
            "broadcast",
            "-a",
            ACTION_REVEIL,
            "-n",
            f"{PAQUET}/{RECEPTEUR}",
        ],
        timeout=60,
    )
    return code == 0


def possible() -> tuple:
    """(possible, motif) — le câble peut-il porter la configuration.

    Interrogé AVANT de présenter un pense-bête à recopier : savoir que le
    câble suffit évite de taper soixante-quatre caractères pour rien.
    """
    try:
        prets = appareils()
    except AppairageError as exc:
        return False, str(exc)
    if not prets:
        return False, t("sms_pair_no_device")
    if len(prets) > 1:
        return False, t("sms_pair_many_devices")
    ouvre, motif = run_as_ouvre()
    if not ouvre:
        return False, f"{t('sms_pair_not_debuggable')} — {motif}"
    return True, ""


def appairer(spec, secret: str, url: str, copie_vers: Path = None) -> tuple:
    """Pose URL, identifiant et secret dans l'application. Rend (ok, detail).

    L'ancien fichier est copié avant d'être remplacé quand un chemin est
    donné : la copie porte le secret précédent, elle va donc à côté de l'état
    de la démonstration, dans un dossier en 0700.
    """
    if not secret:
        return False, t("sms_pair_no_secret")
    joignable, motif = possible()
    if not joignable:
        return False, motif

    avant = lire_prefs()
    if copie_vers is not None:
        copie_vers.write_text(avant, encoding="utf-8")
        copie_vers.chmod(0o600)

    apres = poser_valeurs(
        avant,
        {
            "odoo_base_url": url,
            "device_id": spec.device_id,
            "hmac_secret": secret,
            # Un refus d'hier ne decrit pas la configuration d'aujourd'hui :
            # le laisser ferait lire « HTTP 403 » sur une passerelle saine.
            "last_error": "",
        },
        {
            "enabled": True,
            "allow_plain_lan": url.startswith("http://")
            and url_sort_du_poste(url),
        },
    )
    # L'application est arretee APRES la lecture et AVANT l'ecriture : lire
    # d'abord evite de perdre les reglages qu'elle tient du serveur.
    arreter_application()
    ecrire_prefs(apres)
    posees = accorder_permissions()
    # Le SERVICE, et pas l'ecran : la passerelle interroge sans interface, et
    # forcer l'activite au premier plan depuis le cable la laisse par moments
    # derriere la fenetre de lancement du systeme, l'application paraissant
    # alors ne plus demarrer. Le recepteur releve le service sans rien
    # afficher, et l'ecran se rouvre quand son porteur le decide.
    reveiller_passerelle()
    detail = f"{spec.device_id} → {url}"
    if posees:
        detail += f" | {t('sms_pair_granted')} : {', '.join(posees)}"
    return True, detail
