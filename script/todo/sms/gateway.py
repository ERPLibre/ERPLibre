#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce qu'il faut dire à Odoo, et ce qu'il faut saisir sur le téléphone.

Deux fonctions de rendu, sans effet de bord : elles produisent du texte, et
c'est l'appelant qui décide de l'exécuter dans une VM ou de l'afficher. Ce
découpage rend le contenu vérifiable sans machine virtuelle — la partie la
plus facile à casser silencieusement est aussi la seule qu'on peut tester
en une milliseconde.
"""
from __future__ import annotations

from script.todo.sms.spec import DemoSpec

#: Nom du fournisseur SMS ajouté par le module à `res.company.sms_provider`.
PROVIDER = "erplibre"

#: Variable lue par le module dans l'environnement du processus Odoo.
ENV_SECRET = "ERPLIBRE_SMS_HMAC_SECRET"

#: Routes du protocole. Elles ne portent PAS le nom du module : le module a
#: été renommé, le protocole non, parce que tout téléphone déjà installé
#: continuerait de les appeler.
ROUTES = (
    "/erplibre_sms/poll",
    "/erplibre_sms/report",
    "/erplibre_sms/inbound",
)


def render_setup_script(spec: DemoSpec) -> str:
    """Le script à passer à `odoo-bin shell` pour préparer la passerelle.

    Rejouable : il réutilise la fiche existante au lieu d'en créer une
    seconde, parce qu'une démonstration se reprend souvent à mi-chemin.
    """
    return f"""# Genere par script/todo/sms — configuration de la passerelle de demo.
import os

company = env.company
company.sms_provider = {PROVIDER!r}

Gateway = env["erplibre.sms.gateway"]
gw = Gateway.search([("device_id", "=", {spec.device_id!r})], limit=1)
values = {{
    "name": "Passerelle de demonstration",
    "device_id": {spec.device_id!r},
    # Le materiel decide des criteres de sante : un modem juge sur ceux d'un
    # telephone s'affiche « cadencement degrade », batterie a zero, et bride
    # a trente segments par minute pour une limite qu'il n'a pas.
    "kind": {spec.materiel!r},
    "company_id": company.id,
    "active": True,
    "poll_interval_seconds": 30,
    "segments_per_minute": 24,
    "alarm_active": False,
    "alarm_reason": False,
}}
if gw:
    gw.write(values)
else:
    gw = Gateway.create(values)
env.cr.commit()

secret = os.environ.get({ENV_SECRET!r})
print("RESULTAT_DEVICE_ID=%s" % gw.device_id)
print("RESULTAT_PROVIDER=%s" % company.sms_provider)
print("RESULTAT_SECRET_PRESENT=%s" % bool(secret))
print("RESULTAT_POLL=%s" % gw.poll_interval_seconds)
"""


def render_test_script(number: str, spec: DemoSpec) -> str:
    """Le script d'envoi d'essai, pour vérifier la chaîne de bout en bout."""
    return f"""# Genere par script/todo/sms — envoi d'essai.
sms = env["sms.sms"].create({{
    "number": {number!r},
    "body": "Essai de la passerelle ERPLibre",
}})
sms.send(auto_commit=True)
env.cr.commit()

d = env["erplibre.sms.dispatch"].search(
    [("gateway_id.device_id", "=", {spec.device_id!r})], order="id desc", limit=1
)
print("RESULTAT_UUID=%s" % (d.sms_uuid or ""))
print("RESULTAT_ETAT=%s" % (d.state or "aucun"))
"""


def server_url(spec: DemoSpec, host: str) -> str:
    """L'URL que le téléphone doit viser.

    Toujours en HTTP ici, et l'appelant doit le savoir : le plugin mobile
    n'accepte le HTTP que pour des adresses non routables. Une VM sur le
    réseau libvirt a une adresse privée, donc l'application la REFUSERA —
    d'où le renvoi par `adb reverse` décrit dans `render_mobile_config`.
    """
    return f"http://{host}:{spec.odoo_port}"


def render_mobile_config(
    spec: DemoSpec, secret: str, vm_ip: str, host_ip: str = ""
) -> str:
    """Le pense-bête à recopier dans l'application mobile.

    Volontairement en texte : ces trois valeurs se saisissent au clavier sur
    le téléphone, et un opérateur a besoin de les voir côte à côte pour
    vérifier qu'elles concordent avec Odoo. Le secret est affiché en entier
    parce qu'il est inutilisable sans l'URL — et parce qu'un secret tronqué
    donne un 401 que personne ne sait diagnostiquer.

    Le contenu dépend du transport, parce que les deux ne demandent pas les
    mêmes gestes ni les mêmes précautions.
    """
    wifi = spec.transport == "wifi"
    url = (
        f"http://{host_ip or '(adresse inconnue)'}:{spec.odoo_port}"
        if wifi
        else f"http://127.0.0.1:{spec.odoo_port}"
    )
    largeur = 68
    barre = "=" * largeur
    lignes = [
        barre,
        "  A SAISIR DANS L'APPLICATION   (Options > Passerelle SMS)",
        barre,
        f"  URL du serveur    {url}",
        f"  Identifiant       {spec.device_id}",
        f"  Secret partage    {secret or '*** non genere ***'}",
        barre,
        "",
    ]
    if wifi:
        lignes += [
            "  Wi-Fi : le telephone et ce poste doivent etre sur le MEME",
            "  reseau. Aucun cable, et le lien ne saute pas tout seul.",
            "",
            "  DEUX conditions, et les deux sont necessaires :",
            "",
            "  1. Un APK construit avec -PlanCleartext. Android bloque le HTTP",
            "     en clair au niveau du SYSTEME, et sa configuration reseau",
            "     n'accepte pas de plages d'adresses : l'APK ordinaire refusera",
            "     la connexion avant meme d'atteindre l'application.",
            "        ./gradlew :app:assembleDebug -PlanCleartext",
            "",
            "  2. Cocher « Tolerer le reseau local en clair » sur l'ecran de la",
            "     passerelle.",
            "",
            "  Ce que cela implique, sans detour : sur ce",
            "  reseau, les numeros et le CORPS des messages sont lisibles par",
            "  quiconque le partage. Acceptable pour une demonstration sur un",
            "  reseau qu'on maitrise ; jamais pour un studio dont le Wi-Fi est",
            "  ouvert aux eleves. Pour ce cas, il faut du HTTPS.",
        ]
    else:
        lignes += [
            "  Cable : branche le telephone en USB, puis :",
            "",
            f"      adb reverse tcp:{spec.odoo_port} tcp:{spec.odoo_port}",
            "",
            "  Le renvoi fait pointer le 127.0.0.1 du telephone vers ce poste,",
            "  ce qui satisfait la regle de l'application sans l'affaiblir :",
            "  rien ne circule sur le reseau.",
            "",
            "  Attention : ce renvoi saute a chaque debranchement, et parfois",
            "  tout seul, EN SILENCE. Une passerelle qui redevient grise",
            "  commence presque toujours la. Le mode Wi-Fi n'a pas ce defaut.",
        ]
    if vm_ip and not wifi:
        lignes += ["", f"  Odoo ecoute sur {vm_ip}:{spec.odoo_port}."]
    return "\n".join(lignes)
