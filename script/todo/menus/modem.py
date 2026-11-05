#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Menus du modem USB et de la démonstration de la passerelle SMS, que
l'Assistant ouvre : Modem, ses sous-menus State, Calls, SMS, Answering
machine, Sound, VoIP et Service, et Gateway, la démonstration de bout en
bout, qu'ouvrent Assistant pour le téléphone et Modem pour le modem.

Des données seulement : `build_code_tree` lit ce fichier sans l'importer,
et le numéro d'une entrée est sa place. Les actions sont des méthodes de
TODO, préfixées `_modem_` (`modem/menu.py`) ou `_sms_` (`sms/menu.py`).

Une entrée qui installe, agit en root (sudo, ou une commande AT qui
arrête ModemManager faute de port réservé), écrit une règle udev, une
règle audio ou un service système, envoie un SMS ou passe un vrai appel
porte `danger` : ni la TUI de télémétrie ni la page web ne la lancent,
son menu seul.
"""

from script.todo.ui.registry import Entry, FromMethod, Menu

# Le premier écran : le clavier, seul outil qui SERT le modem plutôt que
# de le régler, puis les sous-menus. La ligne d'état, relue à chaque
# dessin, dit le modem, la voix, le port AT, la messagerie, le répondeur,
# la règle audio et les deux services VoIP.
MODEM = Menu(
    "prompt_execute_modem",
    "Modem",
    [
        Entry("modem_dialer", "_modem_dialer"),
        Entry("modem_menu_state", "_modem_state_menu"),
        Entry("modem_menu_calls", "_modem_calls_menu"),
        Entry("modem_menu_sms", "_modem_sms_menu"),
        Entry("modem_answering", "_modem_answering_menu"),
        Entry("modem_menu_audio", "_modem_audio_menu"),
        Entry("modem_menu_voip", "_modem_voip_menu"),
        Entry("modem_menu_service", "_modem_service_menu"),
        Entry("modem_gateway_agent", "_modem_gateway"),
    ],
    state="_modem_banner",
    back=None,
)

MODEM_STATE = Menu(
    "_modem_state_menu",
    "State",
    [
        Entry("modem_status", "_modem_status"),
        Entry("modem_diag", "_modem_diagnostic", danger=True),
    ],
    back=None,
)

# Sans port réservé, une commande AT arrête ModemManager par sudo :
# raccrocher et lister les appels en sont, d'où leur `danger`.
MODEM_CALLS = Menu(
    "_modem_calls_menu",
    "Calls",
    [
        Entry("modem_call", "_modem_call", danger=True),
        Entry("modem_hangup", "_modem_hangup", danger=True),
        Entry("modem_calls_list", "_modem_calls_list", danger=True),
        Entry("voip_call", "_modem_voip_call", danger=True),
    ],
    back=None,
)

MODEM_SMS = Menu(
    "_modem_sms_menu",
    "SMS",
    [
        Entry("modem_sms_send", "_modem_sms_send", danger=True),
        Entry("modem_sms_list", "_modem_sms_list"),
    ],
    back=None,
)

# L'état du répondeur et son annonce, relus à chaque dessin ; le code de la
# messagerie et sa remise au service disent leur état entre parenthèses,
# jamais la valeur du code.
MODEM_ANSWERING = Menu(
    "_modem_answering_menu",
    "Answering machine",
    [
        Entry("modem_ans_list", "_modem_answering_messages"),
        Entry("modem_ans_greeting", "_modem_greeting_record"),
        Entry("modem_ans_greeting_play", "_modem_greeting_play"),
        Entry("modem_ans_rings", "_modem_rings"),
        Entry("modem_ans_toggle", "_modem_answering_toggle"),
        Entry("modem_ans_pin", "_modem_pin", suffix="_modem_pin_state"),
        Entry(
            "modem_ans_pin_hand",
            "_modem_pin_hand",
            suffix="_modem_pin_service_state",
        ),
        # Appelle la messagerie de l'opérateur, et peut y effacer un message.
        Entry("modem_ans_fetch", "_modem_fetch", danger=True),
    ],
    state="_modem_answering_state",
    back=None,
)

# Les essais à côté des réglages qu'ils éprouvent. Sonder le chemin audio
# passe un vrai appel ; la carte UAC se réécrit et redémarre le modem ; la
# règle audio relance le serveur de son.
MODEM_AUDIO = Menu(
    "_modem_audio_menu",
    "Sound",
    [
        Entry("modem_probe_audio", "_modem_probe_audio", danger=True),
        Entry("modem_audio_try", "_modem_try_handset"),
        Entry("modem_uac_toggle", "_modem_uac_toggle", danger=True),
        Entry(
            "modem_audio_rule",
            "_modem_audio_rule",
            suffix="_modem_audio_rule_state",
            danger=True,
        ),
        Entry("modem_udev", "_modem_udev_rule", danger=True),
    ],
    back=None,
)

MODEM_VOIP = Menu(
    "_modem_voip_menu",
    "VoIP",
    [
        Entry("voip_install", "_modem_voip_install", danger=True),
        Entry("voip_status", "_modem_voip_status"),
        Entry("voip_softphone_odoo", "_modem_softphone"),
    ],
    back=None,
)

# Les unités systemd du modem : tout ce qui les écrit ou les commande passe
# par sudo.
MODEM_SERVICE = Menu(
    "_modem_service_menu",
    "Service",
    [
        Entry("modem_service_state", "_modem_service_status"),
        Entry("modem_service_env", "_modem_service_env", danger=True),
        Entry("modem_service_install", "_modem_service_install", danger=True),
        Entry(
            "modem_service_start",
            "_modem_service_command",
            kwargs={"action": "start"},
            danger=True,
        ),
        Entry(
            "modem_service_stop",
            "_modem_service_command",
            kwargs={"action": "stop"},
            danger=True,
        ),
        Entry(
            "modem_service_enable",
            "_modem_service_command",
            kwargs={"action": "enable"},
            danger=True,
        ),
        Entry(
            "modem_service_disable",
            "_modem_service_command",
            kwargs={"action": "disable"},
            danger=True,
        ),
        Entry("modem_service_log", "_modem_service_log"),
        Entry("modem_service_remove", "_modem_service_remove", danger=True),
    ],
    back=None,
)

# La démonstration de la passerelle d'un matériel, le téléphone ou le
# modem, que `prompt_execute_sms` tient le temps du menu : l'enchaînement,
# une entrée par étape, puis ce qui suit les étapes. Une entrée gardée
# (`when`) n'existe que pour un matériel, ou pour un mode, et les suivantes
# gardent leur numéro sans elle. Passer à l'autre matériel rend son nom, qui
# referme le menu (`closes_on_result`) : `prompt_execute_sms` le rouvre sur
# l'autre. L'entrée qui détruit vient en dernier, où l'on ne tombe pas
# dessus en visant sa voisine.
GATEWAY = Menu(
    "prompt_execute_sms",
    "Gateway",
    [
        Entry("sms_run_all", "_sms_run_all", danger=True),
        FromMethod("_sms_steps", "_sms_run_step", "step"),
        Entry("sms_phone_menu", "_sms_read_phone", when="_sms_on_mobile"),
        Entry("modem_sms_list", "_sms_list_modem", when="_sms_on_modem"),
        Entry("sms_call_menu", "_sms_test_call", danger=True),
        Entry("sms_open_tui", "_sms_open_tui"),
        Entry(
            "sms_test_number_menu",
            "_sms_test_number",
            suffix="_sms_test_number_shown",
        ),
        Entry("sms_mode_menu", "_sms_mode", suffix="_sms_mode_shown"),
        Entry("sms_pair_menu", "_sms_pair", when="_sms_on_mobile"),
        Entry("sms_switch_materiel", "_sms_switch", suffix="_sms_other_shown"),
        Entry("sms_reset_local", "_sms_reset", when="_sms_local", danger=True),
        Entry("sms_reset", "_sms_reset", when="_sms_in_vm", danger=True),
    ],
    state="_sms_state",
    back=None,
    closes_on_result=True,
)
