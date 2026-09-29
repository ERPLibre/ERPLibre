"""Declarer dans Odoo le softphone servi par le modem.

`voip_oca` fait sonner un softphone dans le navigateur, mais il lui faut deux
choses en base : un serveur a joindre et un poste par utilisateur. Sans elles,
le navigateur ne s'inscrit nulle part et l'INVITE du service de voix n'a
personne a faire sonner — un appel entrant laisse alors une trace dans Odoo
sans qu'aucun telephone ne sonne.

Le mot de passe du poste vient de `service.postes()` et de nulle part ailleurs :
les DEUX cotes doivent porter le meme, et une valeur saisie deux fois finit par
differer.

Le rendu est separe de l'execution, comme pour la passerelle SMS : ce qu'on
envoie a `odoo-bin shell` se verifie alors sans base de donnees.
"""
import os
import subprocess

#: Nom de la fiche serveur. Stable : c'est par lui qu'on la retrouve pour la
#: mettre a jour au lieu d'en creer une seconde.
NOM_PBX = "erplibre_sip_go"

#: « prod » et non « test » : en test, voip_oca ne place pas reellement
#: l'appel. Le defaut du module est « test », ce qui donne un softphone qui
#: s'inscrit et ne sonne jamais.
MODE = "prod"


def render_setup_script(poste, mot_de_passe, ecoute, login="admin"):
    """Le script a passer a `odoo-bin shell`. Rejouable.

    Retrouve la fiche par son nom plutot que d'en creer une seconde : une
    configuration se reprend, et deux serveurs declares pour un seul rendent
    l'etat d'Odoo incomprehensible.

    `ecoute` est « hote:port », tel que le service l'ecoute ; le WebSocket s'en
    deduit. Le domaine SIP est l'hote seul : c'est le « realm » que le service
    annonce dans son defi, et un ecart y fait refuser le mot de passe juste.
    """
    hote = ecoute.split(":")[0]
    ws = "ws://" + ecoute
    return f"""# Genere par script/todo/modem/softphone.py — softphone du modem.
Pbx = env["voip.pbx"]
pbx = Pbx.search([("name", "=", {NOM_PBX!r})], limit=1)
valeurs = {{
    "name": {NOM_PBX!r},
    "domain": {hote!r},
    "ws_server": {ws!r},
    "mode": {MODE!r},
}}
if pbx:
    pbx.write(valeurs)
else:
    pbx = Pbx.create(valeurs)

utilisateur = env["res.users"].search([("login", "=", {login!r})], limit=1)
if not utilisateur:
    print("RESULTAT_ERREUR=utilisateur introuvable : %s" % {login!r})
else:
    utilisateur.write({{
        "voip_pbx_id": pbx.id,
        "voip_username": {poste!r},
        "voip_password": {mot_de_passe!r},
    }})
    env.cr.commit()
    print("RESULTAT_PBX=%s" % pbx.id)
    print("RESULTAT_WS=%s" % pbx.ws_server)
    print("RESULTAT_POSTE=%s" % utilisateur.voip_username)
"""


def _analyser(sortie):
    trouve = {}
    for ligne in (sortie or "").splitlines():
        if ligne.startswith("RESULTAT_"):
            cle, _, valeur = ligne[len("RESULTAT_"):].partition("=")
            trouve[cle] = valeur.strip()
    return trouve


def configurer(base, ecoute=None, login="admin", lancer=None):
    """Ecrit la configuration dans `base`. Rend (succes, detail).

    Le script passe par l'entree standard et non par la ligne de commande : il
    porte le mot de passe du poste, et la ligne de commande est lisible par
    toute la machine dans la liste des processus.
    """
    from script.todo.modem import service as svc_mod

    ecoute = ecoute or svc_mod.ECOUTE_DEFAUT
    poste, _, mot = svc_mod.postes().partition(":")
    if not mot:
        return False, "compte du softphone illisible"
    script = render_setup_script(poste, mot, ecoute, login)

    lancer = lancer or _odoo_shell
    code, sortie = lancer(base, script)
    trouve = _analyser(sortie)
    if trouve.get("ERREUR"):
        return False, trouve["ERREUR"]
    if code != 0 or not trouve.get("PBX"):
        return False, (sortie or "").strip()[-600:]
    return True, "poste %s sur %s" % (trouve.get("POSTE", "?"),
                                      trouve.get("WS", "?"))


def _odoo_shell(base, script):
    """Lance `odoo-bin shell` sur la base, sans HTTP.

    `--no-http` est necessaire : le port est deja tenu par l'instance qui sert,
    et un shell qui tente de l'ouvrir echoue avant d'avoir rien ecrit.
    """
    from script.todo.sms import local as local_mod

    venv = local_mod.find_venv()
    if venv is None:
        return 1, "venv Odoo introuvable"
    commande = [
        str(venv / "bin" / "python"), str(local_mod.odoo_bin()), "shell",
        "-c", "config.conf", "-d", base, "--no-http", "--log-level=error",
    ]
    try:
        r = subprocess.run(commande, cwd=str(local_mod.repo_root()),
                           input=script, capture_output=True, text=True,
                           timeout=600, env=dict(os.environ))
    except (subprocess.TimeoutExpired, OSError) as exc:
        return 1, str(exc)
    return r.returncode, (r.stdout or "") + (r.stderr or "")
