#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Gateway, la démonstration de bout en bout de la passerelle SMS,
qu'ouvrent Assistant pour le téléphone et Modem pour le modem.

Des données seulement : `build_code_tree` lit ce fichier sans l'importer,
et le numéro d'une entrée est sa place. Les actions sont des méthodes de
TODO, préfixées `_sms_` (`sms/menu.py`).

Une entrée qui crée une VM, passe un vrai appel ou détruit la
démonstration porte `danger` : ni la TUI de télémétrie ni la page web ne
la lancent, son menu seul.
"""

from script.todo.ui.registry import Entry, FromMethod, Menu

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
