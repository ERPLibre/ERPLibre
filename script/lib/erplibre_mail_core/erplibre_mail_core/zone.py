# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le fuseau du processus en `tzinfo`.

Les calculs de calendrier du noyau prennent un fuseau explicite ; sans
fuseau, ils prennent celui que rend `local_zone`, le même que voit
`time.localtime`.
"""

import datetime
import os
import time
import zoneinfo

# Écart entre les instants que compare le contrôle : un an couvre une
# heure d'été et une heure d'hiver.
_DEMI_ANNEE_S = 182 * 86400


def _depuis_tz(valeur: str) -> datetime.tzinfo:
    """Le fuseau que nomme une valeur de `TZ` déjà privée de son `:`
    initial : un chemin absolu de fichier TZif, ou un nom IANA."""
    if os.path.isabs(valeur):
        with open(valeur, "rb") as fichier:
            return zoneinfo.ZoneInfo.from_file(fichier, key=valeur)
    return zoneinfo.ZoneInfo(valeur)


def _depuis_localtime() -> datetime.tzinfo | None:
    """Le fuseau de `/etc/localtime`, sous sa clé IANA quand le lien mène
    sous un répertoire de `zoneinfo.TZPATH` ; None quand le fichier
    manque."""
    chemin = "/etc/localtime"
    if not os.path.exists(chemin):
        return None
    reel = os.path.realpath(chemin)
    for racine in zoneinfo.TZPATH:
        racine = os.path.realpath(racine)
        if reel.startswith(racine + os.sep):
            return zoneinfo.ZoneInfo(os.path.relpath(reel, racine))
    with open(chemin, "rb") as fichier:
        return zoneinfo.ZoneInfo.from_file(fichier, key="localtime")


def _accord_libc(zone: datetime.tzinfo) -> bool:
    """Vrai quand `zone` donne le décalage de `time.localtime` maintenant,
    six mois avant et six mois après."""
    now = int(time.time())
    for instant in (now, now - _DEMI_ANNEE_S, now + _DEMI_ANNEE_S):
        decalage = datetime.datetime.fromtimestamp(instant, zone).utcoffset()
        attendu = datetime.timedelta(seconds=time.localtime(instant).tm_gmtoff)
        if decalage != attendu:
            return False
    return True


def _decalage_fixe() -> datetime.tzinfo:
    """Le décalage actuel de `time.localtime`, fixe, sous son abréviation."""
    lt = time.localtime()
    return datetime.timezone(
        datetime.timedelta(seconds=lt.tm_gmtoff), lt.tm_zone
    )


def local_zone() -> datetime.tzinfo:
    """Le fuseau du processus, celui que voit `time.localtime`, en
    `tzinfo` ; relu à chaque appel (suit `TZ` et `time.tzset()`).

    `TZ` (privé d'un `:` initial) nomme un fichier ou un fuseau IANA ; vide,
    c'est UTC ; absent, `/etc/localtime` répond, et UTC sans lui. Un fuseau
    que la libc contredit (le paquet `tzdata` de pip connaît des fuseaux que
    le système n'a pas) ou une chaîne POSIX qui n'est pas un fichier TZif
    donnent le décalage fixe de `time.localtime` : l'heure d'été d'une
    chaîne POSIX à règles est alors perdue.
    """
    try:
        if "TZ" in os.environ:
            valeur = os.environ["TZ"]
            if valeur.startswith(":"):
                valeur = valeur[1:]
            if not valeur:
                return datetime.timezone.utc
            zone = _depuis_tz(valeur)
        else:
            zone = _depuis_localtime()
            if zone is None:
                return datetime.timezone.utc
    except (zoneinfo.ZoneInfoNotFoundError, ValueError, OSError):
        return _decalage_fixe()
    if not _accord_libc(zone):
        return _decalage_fixe()
    return zone
