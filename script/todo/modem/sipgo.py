"""erplibre_sip_go : service SIP en Go, vu depuis le CLI.

Le binaire porte toute la logique ; ce module ne fait que l'installer,
l'interroger et l'appeler. Dupliquer ici la validation ou la configuration
produirait deux verites qui divergeraient.
"""
import json
import os
import shlex
import shutil
import subprocess
import threading

from .device import avec_groupe

NOM_BINAIRE = "erplibre-sip-go"

#: Temps laisse au binaire pour raccrocher proprement, en secondes.
DELAI_RACCROCHAGE = 8


def _chemins_env():
    """Les deux emplacements possibles, utilisateur d'abord."""
    return [
        os.path.expanduser("~/.config/erplibre/sip_go.env"),
        "/etc/erplibre/sip_go.env",
    ]


def binaire():
    chemin = shutil.which(NOM_BINAIRE)
    if chemin:
        return chemin
    local = os.path.expanduser(f"~/.local/bin/{NOM_BINAIRE}")
    return local if os.path.isfile(local) else None


def installe():
    return binaire() is not None


def fichier_env():
    for c in _chemins_env():
        if os.path.isfile(c):
            return c
    return None


def config():
    """Lit la configuration SANS jamais renvoyer le mot de passe.

    Un secret qui traverse une couche d'affichage finit par s'afficher : on
    ne le fait pas remonter, on dit seulement s'il est pose.
    """
    chemin = fichier_env()
    if not chemin:
        return {}
    valeurs = {}
    try:
        with open(chemin, encoding="utf-8") as f:
            for ligne in f:
                ligne = ligne.strip()
                if not ligne or ligne.startswith("#") or "=" not in ligne:
                    continue
                cle, _, val = ligne.partition("=")
                cle = cle.strip()
                if cle == "VOIP_PASSWORD":
                    valeurs["mot_de_passe_pose"] = bool(val.strip())
                else:
                    valeurs[cle] = val.strip()
    except OSError:
        return {}
    return valeurs


def configure():
    c = config()
    return bool(c.get("VOIP_TRUNK") and c.get("VOIP_USER")
                and c.get("mot_de_passe_pose"))


def chemin_script():
    return os.path.realpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "..", "..", "install", "install_sip_go.sh")
    )


def environnement():
    """Charge le fichier de configuration dans un environnement de sous-processus.

    Les secrets passent par l'environnement et jamais par la ligne de
    commande : celle-ci est lisible dans la liste des processus de toute la
    machine, pendant toute la duree de l'appel.
    """
    env = dict(os.environ)
    chemin = fichier_env()
    if not chemin:
        return env
    try:
        with open(chemin, encoding="utf-8") as f:
            for ligne in f:
                ligne = ligne.strip()
                if ligne and not ligne.startswith("#") and "=" in ligne:
                    cle, _, val = ligne.partition("=")
                    env[cle.strip()] = val.strip()
    except OSError:
        pass
    return env


def appeler(numero, annonce=None, verbeux=True, transport="modem"):
    """Place un appel. Renvoie (code, sortie_json, journal).

    Transport « modem » par defaut : c'est la voie SANS TIERS, par la carte
    SIM. « sip » reste disponible pour qui possede deja un trunk, mais il
    reintroduit une societe qui voit passer les appels.
    """
    if not binaire():
        return 2, "", "erplibre-sip-go n'est pas installe."
    # Passe par commande_appel : c'est elle qui sait qu'un processus prive du
    # groupe du port doit etre relance par « sg ». La reconstruire ici
    # donnerait une commande AFFICHEE differente de la commande LANCEE.
    args = commande_appel(numero, annonce, transport=transport,
                          verbeux=verbeux)
    try:
        r = subprocess.run(args, capture_output=True, text=True,
                           env=environnement(), timeout=150)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return 1, "", "Delai depasse : aucune reponse en 150 s."
    except OSError as e:
        return 2, "", str(e)


#: Ou l'on retient le mode PCM trouve par la sonde.
FICHIER_MODE = os.path.expanduser("~/.config/erplibre/modem_pcm")

#: Mode utilise tant que la sonde n'a rien tranche. Il vaut celui du binaire.
MODE_PCM_DEFAUT = 2


def mode_pcm():
    """Rend le mode PCM retenu, ou le defaut.

    Un fichier illisible ou absurde ne doit pas empecher d'appeler : on
    retombe sur le defaut plutot que de lever.
    """
    try:
        with open(FICHIER_MODE, encoding="utf-8") as f:
            valeur = int(f.read().strip())
    except (OSError, ValueError):
        return MODE_PCM_DEFAUT
    return valeur if 0 <= valeur <= 2 else MODE_PCM_DEFAUT


def poser_mode_pcm(valeur):
    """Retient le mode trouve par la sonde. Rend True si c'est ecrit."""
    try:
        os.makedirs(os.path.dirname(FICHIER_MODE), exist_ok=True)
        with open(FICHIER_MODE, "w", encoding="utf-8") as f:
            f.write(str(int(valeur)))
        return True
    except OSError:
        return False


def sonder(numero, mode=None, annonce=None):
    """Lance la sonde et rend (code, sortie_json, journal)."""
    if not binaire():
        return 2, "", "erplibre-sip-go n'est pas installe."
    args = commande_sonde(numero, mode, annonce)
    try:
        r = subprocess.run(args, capture_output=True, text=True,
                           env=environnement(), timeout=180)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return 1, "", "Delai depasse."
    except OSError as e:
        return 2, "", str(e)


def commande_sonde(numero, mode=None, annonce=None):
    """Commande qui mesure le chemin audio pendant un appel reel.

    UN SEUL mode par appel : le modem fige le routage voix des que la voix
    s'etablit et refuse ensuite AT+QPCMV. Comparer les modes demande donc un
    appel par mode.
    """
    exe = binaire() or NOM_BINAIRE
    args = [exe, "-transport", "modem", "-numero", str(numero),
            "-sonder-audio", "-pcm",
            str(mode_pcm() if mode is None else mode)]
    if annonce:
        args += ["-annonce", annonce]
    args.append("-v")
    return avec_groupe(args)


def commande_veille(micro=False, pilotage=True):
    """Commande qui tient la ligne et decroche sur commande.

    Elle OUVRE le port AT et la carte du modem pour toute sa duree : rien
    d'autre ne pourra composer ni interroger le modem pendant ce temps.
    """
    exe = binaire() or NOM_BINAIRE
    args = [exe, "-veille", "-pcm", str(mode_pcm()), "-v"]
    if micro:
        args.append("-micro")
    if pilotage:
        args.append("-pilotage")
    return avec_groupe(args)


def commande_essai_audio(micro=False, pilotage=False):
    """Commande d'essai du combine, sans appeler personne.

    N'ouvre pas le port AT : aucun groupe particulier n'est requis, et le
    modem n'est meme pas sollicite.
    """
    exe = binaire() or NOM_BINAIRE
    # « -v » dans les DEUX cas : la sortie d'erreur est desormais captee et
    # remontee au journal de l'interface, au lieu d'etre jetee. S'en priver
    # laisserait l'essai sans diagnostic.
    args = [exe, "-essai-audio", "-v"]
    if micro:
        args.append("-micro")
    if pilotage:
        args.append("-pilotage")
    return args


def sons_fournis():
    """Annonces livrees avec le depot, prêtes au format du modem."""
    dossier = os.path.realpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "..", "..", "erplibre_sip_go", "sons")
    )
    if not os.path.isdir(dossier):
        return []
    return sorted(
        os.path.join(dossier, f) for f in os.listdir(dossier)
        if f.lower().endswith(".wav")
    )


def commande_appel(numero, annonce=None, combine=False, transport="modem",
                   verbeux=True, micro=False, pilotage=False):
    """Construit la ligne de commande, sans la lancer.

    Rendue a part pour que le menu puisse l'AFFICHER avant de la lancer : un
    appel part vers une personne reelle, et voir la commande exacte est le
    dernier moment ou l'on peut se raviser.
    """
    exe = binaire() or NOM_BINAIRE
    args = [exe, "-transport", transport, "-numero", str(numero)]
    if annonce:
        args += ["-annonce", annonce]
    if combine:
        args.append("-combine")
        if micro:
            # Sans ce drapeau le micro demarre FERME : on entend sans etre
            # entendu, et la touche m l'ouvre quand on le decide.
            args.append("-micro")
    if pilotage:
        # AVANT l'enveloppe « sg » : ajoute apres, le drapeau irait a sg et
        # non au binaire, et le pilotage resterait silencieusement absent.
        args.append("-pilotage")
    if transport == "modem":
        # Le mode PCM decide si la carte son est reliee a la ligne : le
        # passer explicitement evite qu'un defaut change sous les pieds.
        args += ["-pcm", str(mode_pcm())]
    if verbeux:
        args.append("-v")
    if transport == "modem":
        # Le transport modem ouvre le port AT : sans le groupe, « permission
        # denied ». Le transport SIP ne touche a aucun peripherique.
        return avec_groupe(args)
    return args


def _message(ligne):
    """Extrait la partie lisible d'une ligne de journal structuree.

    Le format porte l'heure, le niveau, puis « msg=... » et des paires
    cle=valeur. On garde ce qui suit le niveau : l'heure figure deja dans
    le journal de l'interface, et la repeter mange la largeur.
    """
    for marqueur in ("level=WARN", "level=ERROR", "level=INFO"):
        _, sep, reste = ligne.partition(marqueur)
        if not sep:
            continue
        try:
            # shlex retire les guillemets de chaque paire : sans lui, un
            # message contenant une espace ressort coupe en deux avec une
            # apostrophe pendante.
            morceaux = shlex.split(reste.strip())
        except ValueError:
            return reste.strip()
        if morceaux and morceaux[0].startswith("msg="):
            morceaux[0] = morceaux[0][len("msg="):]
        return "  ".join(morceaux)
    return ligne


class PiloteAppel:
    """Un appel tenu par le binaire, commande depuis Python.

    Le binaire tient le media et publie son etat ; ce client ne fait que lui
    parler. Rien n'est duplique ici — ni le son, ni le volume, ni l'etat des
    interrupteurs. Deux copies d'un meme etat finissent toujours par
    diverger, et c'est l'affichage qui ment alors, pas le son.

    Le dialogue est en lignes de texte : une commande par ligne sur l'entree
    du binaire, un objet JSON par ligne sur sa sortie.
    """

    def __init__(self, args, sur_etat=None, sur_fin=None, sur_journal=None):
        self.args = list(args)
        self._sur_etat = sur_etat
        self._sur_fin = sur_fin
        self._sur_journal = sur_journal
        self.proc = None
        self.resultat = None

    def demarrer(self):
        """Lance le binaire. Rend True si le processus est parti."""
        try:
            self.proc = subprocess.Popen(
                self.args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, bufsize=1,
                env=environnement(),
            )
        except OSError:
            return False
        threading.Thread(target=self._lire, daemon=True).start()
        threading.Thread(target=self._lire_journal, daemon=True).start()
        return True

    def _lire_journal(self):
        """Fait remonter ce que le binaire ecrit sur sa sortie d'erreur.

        La jeter privait de tout diagnostic : un canal voix refuse, un
        peripherique repris par le systeme, un reglage rejete par le modem
        n'apparaissaient nulle part, et l'appel restait muet sans raison
        visible.
        """
        for ligne in self.proc.stderr:
            texte = ligne.strip()
            if not texte or not self._sur_journal:
                continue
            # On ne garde que ce qui apprend quelque chose : le detail des
            # etats defile cinq fois par seconde.
            if "level=WARN" in texte or "level=ERROR" in texte:
                self._sur_journal("⚠  " + _message(texte))
            elif "level=INFO" in texte:
                self._sur_journal("·  " + _message(texte))

    def _lire(self):
        """Distribue les etats au vol, garde le reste pour le resultat.

        Les etats arrivent en UNE ligne chacun, le resultat final en
        plusieurs : c'est ce qui permet de les separer sans marqueur de fin.
        """
        reste = []
        for ligne in self.proc.stdout:
            depouillee = ligne.strip()
            if not depouillee:
                continue
            if depouillee.startswith("{") and '"type":"etat"' in depouillee:
                try:
                    etat = json.loads(depouillee)
                except json.JSONDecodeError:
                    continue
                if self._sur_etat:
                    self._sur_etat(etat)
                continue
            reste.append(ligne.rstrip("\n"))
        try:
            self.resultat = json.loads("\n".join(reste))
        except (json.JSONDecodeError, ValueError):
            self.resultat = None
        if self._sur_fin:
            self._sur_fin(self.resultat)

    def actif(self):
        return self.proc is not None and self.proc.poll() is None

    def commander(self, ligne):
        """Envoie une commande. Rend False si l'appel n'est plus la."""
        if not self.actif():
            return False
        try:
            self.proc.stdin.write(ligne + "\n")
            self.proc.stdin.flush()
            return True
        except (BrokenPipeError, ValueError, OSError):
            return False

    def micro(self, ouvert):
        return self.commander("micro " + ("on" if ouvert else "off"))

    def haut_parleurs(self, ouverts):
        return self.commander("hp " + ("on" if ouverts else "off"))

    def gain_micro(self, pour_cent):
        return self.commander(f"gain-micro {int(pour_cent)}")

    def gain_hp(self, pour_cent):
        return self.commander(f"gain-hp {int(pour_cent)}")

    def anti_echo(self, actif):
        return self.commander("anti-echo " + ("on" if actif else "off"))

    def bruit_modem(self, actif):
        return self.commander("bruit-modem " + ("on" if actif else "off"))

    def volume_modem(self, cran):
        return self.commander(f"volume-modem {int(cran)}")

    def filtre(self, actif):
        """Passe-haut et porte de bruit sur le micro."""
        return self.commander("filtre " + ("on" if actif else "off"))

    def gain_micro_modem(self, gain):
        """Gain de montee DANS le modem, applique avant le codec."""
        return self.commander(f"gain-micro-modem {int(gain)}")

    def sonnerie(self, actif):
        """Fait sonner, ou non, a l'arrivee d'un appel."""
        return self.commander("sonnerie " + ("on" if actif else "off"))

    def repondre(self):
        """Decroche l'appel entrant."""
        return self.commander("repondre")

    def gain_ecoute_modem(self, gain):
        """Gain de descente DANS le modem, applique avant la carte."""
        return self.commander(f"gain-ecoute-modem {int(gain)}")

    def composer(self, numero):
        """Ajoute un second appel. Le reseau met le premier en attente."""
        return self.commander(f"composer {numero}")

    def touches(self, touches):
        """Joue des tonalites DTMF sur l'appel en cours.

        C'est ainsi qu'on pilote une messagerie d'operateur : mot de passe,
        « 1 pour ecouter ». Les caracteres hors clavier telephonique sont
        ecartes ICI, avant de partir : le binaire les refuserait en bloc.
        """
        propres = "".join(c for c in str(touches).upper() if c in "0123456789*#ABCD")
        if not propres:
            return False
        return self.commander("touches " + propres)

    def fusionner(self):
        """Reunit l'appel actif et celui en attente, DANS le reseau."""
        return self.commander("fusionner")

    def attente(self):
        return self.commander("attente")

    def entree(self, peripherique):
        return self.commander("entree " + (peripherique or ""))

    def sortie(self, peripherique):
        return self.commander("sortie " + (peripherique or ""))

    def raccrocher(self, delai=DELAI_RACCROCHAGE):
        """Demande de raccrocher, puis abat le processus s'il s'attarde.

        On demande d'abord : le binaire sait envoyer ATH et refermer le canal
        voix, ce qu'un abattage immediat empecherait — et la ligne resterait
        ouverte, donc facturee.
        """
        if not self.actif():
            return
        self.commander("raccrocher")
        try:
            self.proc.wait(timeout=delai)
            return
        except subprocess.TimeoutExpired:
            pass
        self.proc.kill()
        try:
            self.proc.wait(timeout=delai)
        except subprocess.TimeoutExpired:
            pass
