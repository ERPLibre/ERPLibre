"""La carte son du modem, et le serveur audio qui la convoite.

Un serveur audio de bureau adopte la carte UAC du modem comme n'importe
quel peripherique USB : il en fait une source, la choisit comme micro par
defaut, et la tient ouverte en permanence. La carte devient alors
inutilisable en ALSA direct — « peripherique occupe » — donc toute mesure
du chemin audio echoue, et le micro du bureau bascule sans prevenir sur une
carte muette hors appel.

Ce module pose la regle qui la lui laisse.
"""
import json
import os
import re
import shutil
import subprocess

NOM_REGLE = "50-erplibre-modem-audio.conf"

#: La regle livree par le depot.
SOURCE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "config", NOM_REGLE,
)

#: Ou WirePlumber lit les surcharges de l'utilisateur.
CIBLE = os.path.expanduser(
    "~/.config/wireplumber/wireplumber.conf.d/" + NOM_REGLE
)


def posee():
    return os.path.isfile(CIBLE)


def _relancer():
    """Relance WirePlumber. Rend (ok, message).

    Indispensable apres la pose : WirePlumber lit sa configuration au
    demarrage, et garde la carte deja adoptee tant qu'il n'a pas relu.
    """
    if not shutil.which("systemctl"):
        return False, "systemctl absent : relancez le serveur audio a la main."
    try:
        r = subprocess.run(
            ["systemctl", "--user", "restart", "wireplumber"],
            capture_output=True, text=True, timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        return False, str(e)
    if r.returncode != 0:
        return False, (r.stderr or r.stdout or "").strip()
    return True, "WirePlumber relance."


def poser():
    """Installe la regle et relance le serveur. Rend (ok, message)."""
    if not os.path.isfile(SOURCE):
        return False, f"regle introuvable dans le depot : {SOURCE}"
    try:
        os.makedirs(os.path.dirname(CIBLE), exist_ok=True)
        shutil.copyfile(SOURCE, CIBLE)
    except OSError as e:
        return False, str(e)
    ok, message = _relancer()
    return ok, f"{CIBLE} — {message}"


def retirer():
    """Retire la regle et relance le serveur. Rend (ok, message)."""
    if not posee():
        return True, "regle absente, rien a retirer."
    try:
        os.remove(CIBLE)
    except OSError as e:
        return False, str(e)
    ok, message = _relancer()
    return ok, f"{CIBLE} retire — {message}"


def carte_libre(carte):
    """Ouvre reellement la carte en capture. Rend (ok, motif).

    On l'OUVRE au lieu de se fier a la presence de la regle : un serveur
    audio relance avant qu'elle ne soit lue, ou une autre application, la
    tiennent tout aussi bien.
    """
    if not carte:
        return False, "aucune carte son"
    if not shutil.which("arecord"):
        return False, "arecord absent (paquet alsa-utils)"
    try:
        r = subprocess.run(
            ["arecord", "-D", carte, "-f", "S16_LE", "-c", "1",
             "-r", "8000", "-t", "raw", "-d", "1"],
            capture_output=True, text=True, timeout=15,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        return False, str(e)
    if r.returncode != 0:
        return False, (r.stderr or "").strip().splitlines()[-1:][0] \
            if (r.stderr or "").strip() else "capture refusee"
    return True, "carte libre"


#: « card 0: bref [Nom de carte], device 0: Nom du peripherique [Sous-titre] »
#: Le nom utile est AVANT les crochets finals : ceux-ci sont souvent vides.
MOTIF_PCM = re.compile(
    r"^card (\d+): \S+ \[([^\]]*)\], device (\d+): (.*?)\s*\[([^\]]*)\]\s*$"
)


def _lister(outil, exclure_carte=None):
    """Peripheriques ALSA vus par `outil -l`. Rend [(id, libelle)].

    On rend « hw:C,D » et non le nom long : c'est ce que prend l'option -D
    d'aplay et d'arecord. Le libelle sert a l'affichage, l'identifiant seul
    va au binaire.

    La premiere entree est TOUJOURS le peripherique du systeme, identifiant
    vide : sans elle, on ne pourrait plus annuler un choix.

    exclure_carte retire une carte de la liste. Sert a masquer celle du
    modem : la choisir comme micro ou comme haut-parleur brancherait la
    ligne sur elle-meme.
    """
    sortie = [("", "peripherique du systeme")]
    if not shutil.which(outil):
        return sortie
    try:
        r = subprocess.run([outil, "-l"], capture_output=True, text=True,
                           timeout=10, env={**os.environ, "LC_ALL": "C"})
    except (subprocess.TimeoutExpired, OSError):
        return sortie
    for ligne in (r.stdout or "").splitlines():
        m = MOTIF_PCM.match(ligne.strip())
        if not m:
            continue
        carte, nom_carte, dev, nom_dev, sous_titre = m.groups()
        if exclure_carte is not None and int(carte) == int(exclure_carte):
            continue
        ident = f"hw:{carte},{dev}"
        detail = (sous_titre or nom_dev or "").strip()
        libelle = f"{ident}  {nom_carte}"
        if detail:
            libelle += f" — {detail}"
        if not _ouvrable(outil, ident):
            # On les GARDE en les marquant : un serveur audio de bureau
            # possede les cartes de la machine et refuse l'ouverture
            # directe, mais il peut les rendre. Les cacher ferait chercher
            # un peripherique qui existe.
            libelle += "  [occupe]"
        sortie.append((ident, libelle))
    return sortie


#: Duree d'un essai d'ouverture, en secondes. Court : on veut savoir si le
#: peripherique se laisse prendre, pas enregistrer quoi que ce soit.
ESSAI_OUVERTURE = 4


def _ouvrable(outil, ident):
    """Le peripherique se laisse-t-il ouvrir MAINTENANT ?

    On l'ouvre pour de vrai. Un serveur audio de bureau tient les cartes de
    la machine et refuse l'acces direct ; l'annoncer dans la liste evite de
    choisir un peripherique qui coupera le son sans expliquer pourquoi.
    """
    # « -s 1 » : un seul echantillon. On veut savoir si le peripherique se
    # laisse prendre, pas enregistrer quoi que ce soit — une duree en
    # secondes ferait attendre autant que de peripheriques libres.
    args = [outil, "-D", ident, "-f", "S16_LE", "-c", "1", "-r", "8000",
            "-s", "1", "-t", "raw"]
    if outil == "aplay":
        args += ["/dev/zero"]
    else:
        args += ["/dev/null"]
    try:
        r = subprocess.run(args, capture_output=True,
                           timeout=ESSAI_OUVERTURE)
    except (subprocess.TimeoutExpired, OSError):
        return False
    return r.returncode == 0


#: Prefixe des peripheriques servis par le serveur audio du bureau.
#:
#: Il POSSEDE les cartes de la machine et refuse l'ouverture directe : viser
#: « hw:2,0 » echoue meme quand la carte existe et fonctionne. Passer par lui
#: est la seule facon de choisir un de ses peripheriques.
PREFIXE_PIPEWIRE = "pw:"


def _pw_dump():
    """Etat du serveur audio, ou [] s'il n'y en a pas."""
    if not shutil.which("pw-dump"):
        return []
    try:
        r = subprocess.run(["pw-dump"], capture_output=True, text=True,
                           timeout=10)
        return json.loads(r.stdout or "[]")
    except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError):
        return []


def _defauts_pipewire(objets):
    """Noms des peripheriques par defaut du serveur, (entree, sortie)."""
    for o in objets:
        if o.get("type") != "PipeWire:Interface:Metadata":
            continue
        entree = sortie = None
        for m in o.get("metadata") or []:
            valeur = m.get("value")
            nom = valeur.get("name") if isinstance(valeur, dict) else None
            if m.get("key") == "default.audio.source":
                entree = nom
            elif m.get("key") == "default.audio.sink":
                sortie = nom
        if entree or sortie:
            return entree, sortie
    return None, None


def _noeuds_pipewire(objets, classe):
    """Noeuds d'une classe donnee. Rend [(identifiant, libelle, nom)]."""
    trouves = []
    for o in objets:
        if o.get("type") != "PipeWire:Interface:Node":
            continue
        props = (o.get("info") or {}).get("props") or {}
        if props.get("media.class") != classe:
            continue
        nom = props.get("node.name")
        if not nom:
            continue
        libelle = props.get("node.description") or nom
        trouves.append((PREFIXE_PIPEWIRE + nom, libelle, nom))
    return trouves


def _peripheriques(classe, outil, exclure_carte):
    """Liste unifiee : le systeme, le serveur audio, puis l'ALSA direct.

    Les cartes que le serveur possede ne sont PAS proposees en acces direct :
    les choisir echoue, et le repli silencieux vers le systeme laisse croire
    que le choix n'a pas ete pris en compte. Elles apparaissent comme noeuds
    du serveur, ou elles fonctionnent.
    """
    objets = _pw_dump()
    noeuds = _noeuds_pipewire(objets, classe)
    par_defaut = _defauts_pipewire(objets)[0 if classe == "Audio/Source" else 1]

    # Le libelle du systeme DIT vers quoi il pointe : « systeme » tout court
    # n'apprend rien, et c'est justement ce qu'on cherche a savoir quand un
    # choix explicite echoue.
    libelle_systeme = "peripherique du systeme"
    for _, lib, nom in noeuds:
        if nom == par_defaut:
            libelle_systeme += f" — {lib}"
            break
    sortie = [("", libelle_systeme)]
    sortie += [(ident, lib) for ident, lib, _ in noeuds]
    # L'ALSA direct ne garde que ce qui s'ouvre reellement : la carte du
    # modem, qu'une regle soustrait au serveur.
    for ident, libelle in _lister(outil, exclure_carte):
        if ident and "[occupe]" not in libelle:
            sortie.append((ident, libelle))
    return sortie


def sorties(exclure_carte=None):
    """Sorties audio disponibles, systeme d'abord."""
    return _peripheriques("Audio/Sink", "aplay", exclure_carte)


def entrees(exclure_carte=None):
    """Entrees audio disponibles, systeme d'abord."""
    return _peripheriques("Audio/Source", "arecord", exclure_carte)
