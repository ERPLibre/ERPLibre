#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Modèles Stream Deck d'Elgato (vendeur USB 0fd9), par identifiant de
produit.

Le nom sert quand le périphérique n'annonce pas le sien : un sysfs sans
fichier « product », un <hostdev> libvirt qui ne porte que VID:PID. Le nom
annoncé passe toujours devant.

Aucun import : qemu_usb.py, que le CLI USB charge par son chemin hors du
dépôt, le lit avec un repli, et erplibre_home_status.py directement.

Chaque PID de la table figure dans le registre du pilote mobile du deck
(mobile/erplibre_home_mobile/…/streamdeck/DeckRegistry.java), que
test/test_streamdeck_models.py relit. Un PID qu'aucune source du dépôt ne
confirme n'y entre pas : un nom faux trompe plus qu'un VID:PID.
"""

DECK_MODELS = {
    "0060": "Stream Deck Original",
    "0063": "Stream Deck Mini",
    "006c": "Stream Deck XL",
    "006d": "Stream Deck Original v2",
    "0080": "Stream Deck MK.2",
    "0084": "Stream Deck +",
    "008f": "Stream Deck XL v2",
    "009a": "Stream Deck Neo",
}


def model_name(pid) -> str:
    """Nom du modèle pour l'idProduct `pid` (« 0x0080 », « 80 », 0x80,
    casse indifférente), "" quand il est inconnu ou illisible."""
    if isinstance(pid, int):
        cle = "%04x" % pid if 0 <= pid <= 0xFFFF else ""
    else:
        texte = str(pid or "").strip().lower()
        if texte.startswith("0x"):
            texte = texte[2:]
        cle = texte.zfill(4) if 0 < len(texte) <= 4 else ""
    return DECK_MODELS.get(cle, "")
