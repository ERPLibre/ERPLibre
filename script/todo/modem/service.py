"""Unites systemd du modem : les poser, les interroger, les retirer.

Deux services, et rien d'autre ne les tient : l'agent de la passerelle et le
service de voix tournaient depuis des PID poses a la main, donc rien ne
survivait a un redemarrage. Pour un studio dont les alertes partent par SMS,
c'est l'ecart entre « ca marche » et « ca tourne ».

Les gabarits vivent dans script/config/ et portent des @JETONS@ : le chemin du
depot, celui du binaire et le compte qui le fait tourner changent d'une machine
a l'autre, et une unite qui les figerait ne serait posable que sur celle-ci.

Le compte est celui qui pose l'unite, jamais root : le port AT appartient au
groupe « dialout » et la carte son du modem au groupe « audio ». systemd donne
a l'unite TOUS les groupes configures du compte, ce qu'une session ouverte
avant l'ajout n'a pas.
"""
import getpass
import os
import re
import shlex
import subprocess

#: Ou systemd lit les unites du systeme.
DOSSIER_UNITES = "/etc/systemd/system"

#: Fichier d'environnement des deux services, celui que lit deja le CLI.
#: Le meme pour les deux : ils partagent l'URL d'Odoo, l'identifiant de
#: l'appareil et le secret HMAC, et deux fichiers finiraient par diverger.
CHEMIN_ENV = "/etc/erplibre/sip_go.env"

#: Adresse d'ecoute du softphone de navigateur. La boucle locale, et pas
#: l'adresse du poste : un navigateur n'ouvre le micro sans certificat que
#: dans un contexte sur, et « localhost » en est un.
ECOUTE_DEFAUT = "127.0.0.1:8189"

VOIX = "erplibre-sip-go.service"
AGENT = "erplibre-passerelle-modem.service"
UNITES = (VOIX, AGENT)

#: Variables que chaque service exige, par unite. Une absente n'empeche pas la
#: pose : elle empeche le service de servir, ce qui n'est pas la meme panne et
#: ne se repare pas au meme endroit.
VARIABLES = {
    VOIX: ("ERPLIBRE_ODOO_URL", "ERPLIBRE_SMS_DEVICE",
           "ERPLIBRE_SMS_HMAC_SECRET", "VOIP_POSTES"),
    AGENT: ("ERPLIBRE_SMS_URL", "ERPLIBRE_SMS_DEVICE",
            "ERPLIBRE_SMS_HMAC_SECRET"),
}


def _run(args, timeout=30):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        return 1, str(exc)


def gabarit(unite):
    """Chemin du gabarit dans le depot."""
    return os.path.realpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "..", "..", "config", unite)
    )


def cible(unite):
    return os.path.join(DOSSIER_UNITES, unite)


def posee(unite):
    return os.path.isfile(cible(unite))


def active(unite):
    """Le service tourne-t-il MAINTENANT ?"""
    _code, sortie = _run(["systemctl", "is-active", unite])
    return sortie.strip() == "active"


def au_demarrage(unite):
    """Repartira-t-il apres un redemarrage ? C'est la question qui compte.

    Un service actif mais non active demarre a la main et disparait au
    prochain redemarrage, ce qui est precisement la panne que ces unites
    existent pour fermer.
    """
    _code, sortie = _run(["systemctl", "is-enabled", unite])
    return sortie.strip() == "enabled"


def racine_depot():
    return os.path.realpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
    )


def _python_du_depot():
    """L'interpreteur qui fait tourner l'agent.

    Celui du venv ERPLibre, et non « python3 » du systeme : l'agent importe
    le paquet du depot, et un interpreteur sans ses dependances echouerait au
    demarrage sans dire laquelle manque.
    """
    venv = os.path.join(racine_depot(), ".venv.erplibre", "bin", "python")
    return venv if os.path.isfile(venv) else "/usr/bin/python3"


def valeurs(unite, ecoute=ECOUTE_DEFAUT):
    """Ce qui remplace les @JETONS@ du gabarit."""
    from script.todo.modem import repondeur as rep_mod
    from script.todo.modem import sipgo as sipgo_mod

    depot = racine_depot()
    return {
        "@DEPOT@": depot,
        "@UTILISATEUR@": getpass.getuser(),
        "@ENV@": CHEMIN_ENV,
        "@BINAIRE@": sipgo_mod.binaire() or "",
        "@PYTHON@": _python_du_depot(),
        "@ECOUTE@": ecoute,
        "@REPONDEUR@": rep_mod.chemin_conf(),
        "@PCM@": str(sipgo_mod.mode_pcm()),
    }


def rendre(unite, ecoute=ECOUTE_DEFAUT):
    """Le texte de l'unite, jetons remplaces. Leve si l'un reste.

    Un jeton oublie donnerait une unite que systemd accepte et qui echoue au
    demarrage sur un chemin litteral « @BINAIRE@ » — illisible dans un
    journal.
    """
    with open(gabarit(unite), encoding="utf-8") as fichier:
        texte = fichier.read()
    for jeton, valeur in valeurs(unite, ecoute).items():
        texte = texte.replace(jeton, valeur)
    # Seules les DIRECTIVES sont controlees : le gabarit explique sa propre
    # convention dans ses commentaires, et un jeton cite la n'est pas une
    # panne. Dans une directive, c'en est une.
    #
    # Cherche PARTOUT dans la ligne et non un mot entier : un jeton y est
    # toujours colle a sa directive — « WorkingDirectory=@DEPOT@ » — et une
    # garde qui n'examine que des mots isoles ne trouve jamais rien.
    reste = set()
    for ligne in texte.splitlines():
        if ligne.startswith("#") or not ligne.strip():
            continue
        reste.update(re.findall(r"@[A-Z_]+@", ligne))
    if reste:
        raise ValueError("jetons non remplaces : " + ", ".join(sorted(reste)))
    return texte


def environnement_pose():
    return os.path.isfile(CHEMIN_ENV)


def variables_manquantes(unite):
    """Variables que le service exige et dont la valeur reste introuvable.

    On interroge les SOURCES — l'etat de la demonstration, le fichier du secret,
    celui du compte — et non le fichier pose : celui-la appartient a root en
    0600, et le relire demanderait sudo pour un simple affichage d'etat. Ce
    sont de toute facon les sources qui decident si la pose reussira.
    """
    try:
        disponibles = valeurs_environnement()
    except Exception:  # noqa: BLE001 — un etat illisible ne doit rien casser
        return list(VARIABLES[unite])
    return [nom for nom in VARIABLES[unite] if not disponibles.get(nom)]


def chemin_postes():
    """Ou vit le compte du softphone, lisible par l'exploitant.

    Pas dans le fichier d'environnement : celui-la appartient a root en 0600,
    et systemd le lit avant d'abandonner ses privileges. L'exploitant ne
    pourrait donc plus relire le mot de passe pour le declarer dans Odoo, alors
    que les DEUX cotes doivent porter le meme.
    """
    return os.path.join(racine_depot(), "private", "conf", "voip", "postes")


def postes(poste="1001"):
    """Le compte « poste:motdepasse » du softphone, cree au premier appel.

    Stable ensuite : le regenerer couperait l'inscription du navigateur, qui
    porte encore l'ancien.
    """
    import secrets

    chemin = chemin_postes()
    try:
        with open(chemin, encoding="utf-8") as fichier:
            existant = fichier.read().strip()
        if existant:
            return existant
    except OSError:
        pass
    valeur = "%s:%s" % (poste, secrets.token_hex(16))
    os.makedirs(os.path.dirname(chemin), mode=0o700, exist_ok=True)
    descripteur = os.open(chemin, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descripteur, "w", encoding="utf-8") as fichier:
        fichier.write(valeur + "\n")
    return valeur


def valeurs_environnement():
    """Ce que les deux services attendent, pris ou c'est deja ecrit.

    Rien n'est demande a l'ecran : l'URL et l'identifiant d'appareil vivent
    dans l'etat de la demonstration, le secret HMAC dans son fichier. Les
    resaisir ouvrirait la porte a deux valeurs differentes pour une seule
    passerelle.
    """
    from script.todo.sms import spec as spec_mod

    etat = spec_mod.load()
    url = "http://127.0.0.1:%d" % etat.spec.odoo_port
    return {
        "ERPLIBRE_SMS_URL": url,
        "ERPLIBRE_ODOO_URL": url,
        "ERPLIBRE_SMS_DEVICE": etat.spec.device_id,
        "ERPLIBRE_SMS_HMAC_SECRET": spec_mod.read_secret(),
        "VOIP_POSTES": postes(),
    }


def poser_environnement(valeurs_a_poser=None):
    """Ecrit le fichier d'environnement des services. Demande sudo.

    Fusionne avec ce qui s'y trouve deja : l'installateur du service y met les
    reglages d'une ligne d'operateur, et les ecraser retirerait a quelqu'un sa
    voie de sortie sans le dire.

    Le contenu passe par l'entree standard, jamais par la ligne de commande :
    celle-ci est lisible par toute la machine dans la liste des processus, et
    ce fichier porte un secret.
    """
    voulu = dict(valeurs_a_poser or valeurs_environnement())
    manquantes = [nom for nom, valeur in voulu.items() if not valeur]
    if manquantes:
        return False, "valeurs introuvables : " + ", ".join(sorted(manquantes))

    try:
        subprocess.run(["sudo", "-v"], timeout=120)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    lignes = {}
    code, sortie = _run(["sudo", "-n", "cat", CHEMIN_ENV], timeout=30)
    if code == 0:
        for ligne in sortie.splitlines():
            ligne = ligne.strip()
            if ligne and not ligne.startswith("#") and "=" in ligne:
                cle, _, val = ligne.partition("=")
                lignes[cle.strip()] = val.strip()
    lignes.update(voulu)
    contenu = "".join("%s=%s\n" % (cle, lignes[cle]) for cle in sorted(lignes))

    dossier = os.path.dirname(CHEMIN_ENV)
    script = (
        f"install -d -m 0755 {shlex.quote(dossier)} && "
        f"cat > {shlex.quote(CHEMIN_ENV)} && "
        f"chmod 0600 {shlex.quote(CHEMIN_ENV)} && "
        f"chown root:root {shlex.quote(CHEMIN_ENV)}"
    )
    try:
        r = subprocess.run(["sudo", "-n", "sh", "-c", script], input=contenu,
                           capture_output=True, text=True, timeout=60)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, str(exc)
    if r.returncode != 0:
        return False, (r.stdout or "") + (r.stderr or "")
    return True, "%d variables dans %s" % (len(lignes), CHEMIN_ENV)


def poser(unite, ecoute=ECOUTE_DEFAUT):
    """Ecrit l'unite, la recharge et l'active. Demande sudo.

    Active ET demarre d'un coup : poser une unite sans l'activer laisse
    exactement la situation qu'on veut quitter, un service qui ne repart pas
    apres un redemarrage.
    """
    try:
        texte = rendre(unite, ecoute)
    except (OSError, ValueError) as exc:
        return False, str(exc)
    if unite == VOIX and not valeurs(unite)["@BINAIRE@"]:
        return False, ("erplibre-sip-go n'est pas installe : l'unite pointerait"
                       " vers un binaire absent.")
    try:
        subprocess.run(["sudo", "-v"], timeout=120)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    # Le texte passe par l'entree standard et non par la ligne de commande :
    # celle-ci est lisible par toute la machine dans la liste des processus.
    script = (
        f"install -d -m 0755 {shlex.quote(DOSSIER_UNITES)} && "
        f"cat > {shlex.quote(cible(unite))} && "
        f"chmod 0644 {shlex.quote(cible(unite))} && "
        "systemctl daemon-reload && "
        f"systemctl enable --now {shlex.quote(unite)}"
    )
    try:
        r = subprocess.run(["sudo", "-n", "sh", "-c", script], input=texte,
                           capture_output=True, text=True, timeout=90)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, str(exc)
    if r.returncode != 0:
        return False, (r.stdout or "") + (r.stderr or "")
    return True, unite


def retirer(unite):
    """Arrete, desactive et efface l'unite. Demande sudo."""
    try:
        subprocess.run(["sudo", "-v"], timeout=120)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    script = (
        f"systemctl disable --now {shlex.quote(unite)} ; "
        f"rm -f {shlex.quote(cible(unite))} && systemctl daemon-reload"
    )
    try:
        r = subprocess.run(["sudo", "-n", "sh", "-c", script],
                           capture_output=True, text=True, timeout=90)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, str(exc)
    if r.returncode != 0:
        return False, (r.stdout or "") + (r.stderr or "")
    return True, unite


def commander(unite, action):
    """« start », « stop » ou « restart », pour une unite deja posee."""
    if action not in ("start", "stop", "restart"):
        return False, "action inconnue : " + action
    if not posee(unite):
        return False, "unite non posee : " + unite
    try:
        subprocess.run(["sudo", "-v"], timeout=120)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    code, sortie = _run(["sudo", "-n", "systemctl", action, unite], timeout=60)
    return code == 0, sortie.strip()


def journal(unite, lignes=30):
    """Les dernieres lignes du journal du service, sans sudo.

    Le journal d'une unite est lisible par son proprietaire : demander sudo
    pour regarder ce qui ne va pas ajouterait une invite au pire moment.
    """
    code, sortie = _run(
        ["journalctl", "-u", unite, "-n", str(int(lignes)), "--no-pager"],
        timeout=30,
    )
    if code != 0:
        return sortie.strip()
    return sortie.rstrip()


def etat():
    """Etat des deux unites, pret a afficher. Une ligne par unite."""
    lignes = []
    for unite in UNITES:
        if not posee(unite):
            lignes.append((unite, "absente", False, False, []))
            continue
        lignes.append((unite, "posee", active(unite), au_demarrage(unite),
                       variables_manquantes(unite)))
    return lignes
