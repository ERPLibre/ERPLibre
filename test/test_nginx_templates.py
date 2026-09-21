#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Un proxy inverse qui annonce une bascule WebSocket doit pouvoir la tenir.

nginx parle HTTP/1.0 à son amont par défaut, et la bascule d'un WebSocket
EXIGE HTTP/1.1. Un bloc qui pose « Upgrade » et « Connection » sans
« proxy_http_version 1.1 » annonce donc une bascule que la poignée de main ne
peut pas terminer : la configuration est valide, `nginx -t` la trouve bonne,
et le temps réel d'Odoo ne remonte jamais.

La variable « $connection_upgrade » n'existe pas d'office : un gabarit qui
l'emploie sans la définir par une « map » empêche nginx de DÉMARRER, ce qui
est une panne plus brutale et plus visible.
"""

import re
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
GABARITS = RACINE / "script" / "nginx"

# Un « location » de premier niveau et son corps, jusqu'au suivant.
LOCATION = re.compile(r"^\s*location\s+([^{]+)\{", re.M)


def gabarits():
    """Les gabarits nginx du dépôt, triés."""
    return sorted(GABARITS.glob("template_nginx*.txt"))


def blocs_location(texte):
    """[(nom, corps)] pour chaque « location » du gabarit."""
    trouves = list(LOCATION.finditer(texte))
    blocs = []
    for indice, debut in enumerate(trouves):
        fin = (
            trouves[indice + 1].start()
            if indice + 1 < len(trouves)
            else len(texte)
        )
        blocs.append((debut.group(1).strip(), texte[debut.end() : fin]))
    return blocs


class TestUneBasculeAnnonceeEstTenable(unittest.TestCase):
    """« Upgrade » sans HTTP/1.1 est une promesse que le proxy ne tient pas."""

    def test_every_upgrading_block_speaks_http_1_1(self):
        vus, manquants = 0, []
        for chemin in gabarits():
            texte = chemin.read_text(encoding="utf-8")
            for nom, corps in blocs_location(texte):
                if "proxy_set_header Upgrade" not in corps:
                    continue
                vus += 1
                if "proxy_http_version 1.1" not in corps:
                    manquants.append(f"{chemin.name} :: location {nom}")
        # Le plancher : un glob qui ne trouve plus rien, un « location »
        # réindenté ou un analyseur cassé passeraient au vert sans lui.
        self.assertGreaterEqual(vus, 16, "trop peu de blocs lus")
        self.assertEqual([], manquants)

    def test_the_parser_reads_the_blocks_it_is_given(self):
        """Contrôle positif de l'analyseur, sans lequel le compte ci-dessus
        pourrait être atteint par un découpage faux."""
        texte = "location / {\n  a;\n}\nlocation /ws {\n  b;\n}\n"
        blocs = blocs_location(texte)
        self.assertEqual(["/", "/ws"], [nom for nom, _ in blocs])
        self.assertIn("a;", blocs[0][1])
        self.assertNotIn("b;", blocs[0][1])

    def test_the_check_would_notice_a_block_without_the_version(self):
        """Contrôle positif de la RÈGLE : elle doit voir le manque."""
        texte = "location / {\n  proxy_set_header Upgrade $http_upgrade;\n}\n"
        nom, corps = blocs_location(texte)[0]
        self.assertIn("proxy_set_header Upgrade", corps)
        self.assertNotIn("proxy_http_version 1.1", corps)


class TestUneVariableEmployeeEstDefinie(unittest.TestCase):
    """« $connection_upgrade » sans sa « map » empêche nginx de démarrer."""

    def test_every_template_using_the_variable_defines_it(self):
        employeurs = []
        for chemin in gabarits():
            texte = chemin.read_text(encoding="utf-8")
            if "$connection_upgrade" not in texte:
                continue
            employeurs.append(chemin.name)
            self.assertRegex(
                texte,
                r"map\s+\$http_upgrade\s+\$connection_upgrade",
                f"{chemin.name} emploie la variable sans la définir",
            )
        self.assertTrue(employeurs, "aucun employeur : rien n'est prouvé")


if __name__ == "__main__":
    unittest.main()
