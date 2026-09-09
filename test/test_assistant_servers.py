#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le registre des serveurs LLM : la poignée sort, l'adresse reste.

Ce que ces tests défendent tient en deux phrases, et les deux sont des
règles du dépôt plutôt que des préférences.

Un nom d'hôte, un alias SSH, un nom de VM désignent une machine, et le
détecteur du dépôt ne les voit pas : il reconnaît les adresses, les
courriels et les chemins de compte, et rend une liste vide devant un nom.
Seule la STRUCTURE protège les noms, donc seul `redacted` a le droit de
sortir vers une invite. Une régression ici ne casse aucun écran et ne lève
rien : elle recopie une adresse dans un prompt, et rien ne le dira.

L'écriture ne va que dans le fichier gitignored, par `set_config_value`.
Les deux autres fichiers de configuration suivent le dépôt en amont : un
chemin de clés déplacé, ou un second écrivain ajouté, ferait remonter une
adresse de machine avec le prochain commit. Là encore, tout resterait vert.

Aucun fichier réel n'est touché : les accesseurs de configuration sont
injectés, et le seul cas qui teste le défaut remplace la classe elle-même.

Les hôtes et les libellés sont INVENTÉS. `.claude/rules/04-code-conventions.md`
l'exige pour la valeur qui illustre un interdit, et demande de vérifier son
absence ailleurs dans le dépôt : « grenat.invalid » et « safran.invalid »
n'y paraissent nulle part.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.todo.assistant import servers  # noqa: E402

# Un hôte et un libellé qui n'existent pas : le TLD « .invalid » est réservé
# à cet usage, et ne peut donc pas désigner une machine du parc.
HOST_A = "grenat.invalid"
HOST_B = "safran.invalid"
LABEL_A = "Atelier grenat"


def a_server(**changes):
    """Un serveur complet, dont chaque champ se remplace par son nom."""
    fields = {
        "handle": "server-1",
        "label": LABEL_A,
        "host": HOST_A,
        "port": 11434,
        "software": "ollama",
        "model": "petit-modele:7b",
        "hosting": "lan",
        "secret_ref": "",
    }
    fields.update(changes)
    return servers.Server(**fields)


def an_entry(**changes):
    """Une entrée de configuration telle que `save` en écrit une."""
    fields = {
        "label": LABEL_A,
        "host": HOST_A,
        "port": 11434,
        "software": "ollama",
        "model": "petit-modele:7b",
        "hosting": "lan",
        "secret_ref": "",
    }
    fields.update(changes)
    return fields


class Poignees(unittest.TestCase):
    def test_les_poignees_sont_stables_et_commencent_a_un(self):
        entrees = [
            an_entry(host=HOST_A),
            an_entry(host=HOST_B, label="Poste safran"),
        ]
        premier = servers.load(get_config=lambda keys: entrees)
        second = servers.load(get_config=lambda keys: entrees)
        self.assertEqual([s.handle for s in premier], ["server-1", "server-2"])
        self.assertEqual(
            [s.handle for s in second], [s.handle for s in premier]
        )

    def test_la_poignee_stockee_n_est_jamais_relue(self):
        """Une poignée écrite à la main ne doit pas pouvoir en dupliquer une
        autre, ni porter un nom de machine."""
        entrees = [
            an_entry(handle="server-9", host=HOST_A),
            an_entry(handle="server-9", host=HOST_B),
        ]
        charges = servers.load(get_config=lambda keys: entrees)
        self.assertEqual([s.handle for s in charges], ["server-1", "server-2"])

    def test_assign_handles_ne_touche_pas_ce_qu_on_lui_donne(self):
        original = a_server(handle="")
        rendus = servers.assign_handles([original])
        self.assertEqual(original.handle, "")
        self.assertEqual(rendus[0].handle, "server-1")
        self.assertEqual(rendus[0].host, original.host)


class CeQuiAtteintUneInvite(unittest.TestCase):
    def test_ce_qui_peut_atteindre_une_invite_ne_porte_ni_hote_ni_port(self):
        sortie = servers.redacted(a_server())
        self.assertIn("server-1", sortie)
        self.assertIn("ollama", sortie)
        for interdit in (HOST_A, LABEL_A, "11434", "grenat"):
            self.assertNotIn(interdit, sortie, sortie)

    def test_un_serveur_sans_logiciel_reconnu_rend_sa_seule_poignee(self):
        self.assertEqual(servers.redacted(a_server(software="")), "server-1")

    def test_un_serveur_sans_rang_ne_retombe_pas_sur_son_adresse(self):
        sortie = servers.redacted(a_server(handle=""))
        self.assertEqual(sortie, f"{servers.UNASSIGNED_HANDLE} (ollama)")
        self.assertNotIn(HOST_A, sortie)


class OuLEcritureVa(unittest.TestCase):
    def test_l_ecriture_passe_par_le_fichier_prive_et_pas_par_un_autre(self):
        ecrits = []
        servers.save(
            [a_server()],
            set_config=lambda keys, value: ecrits.append((keys, value)),
        )
        self.assertEqual(len(ecrits), 1, ecrits)
        keys, value = ecrits[0]
        self.assertEqual(keys, ["assistant", "servers"])
        self.assertEqual([e["host"] for e in value], [HOST_A])

        # `set_config_value` vise le seul des trois fichiers fusionnés qui
        # soit gitignored. La classe est remplacée pour prouver le défaut
        # sans qu'aucun fichier réel soit ouvert.
        with patch("script.config.config_file.ConfigFile") as classe:
            servers.save([a_server()])
        instance = classe.return_value
        instance.set_config_value.assert_called_once()
        appel = instance.set_config_value.call_args
        self.assertEqual(appel.args[0], ["assistant", "servers"])

        source = Path(servers.__file__).read_text(encoding="utf-8")
        self.assertNotIn("CONFIG_OVERRIDE_FILE", source)
        self.assertNotIn("CONFIG_FILE", source)

    def test_la_lecture_par_defaut_passe_par_le_meme_chemin_de_cles(self):
        with patch("script.config.config_file.ConfigFile") as classe:
            classe.return_value.get_config_value.return_value = []
            self.assertEqual(servers.load(), [])
        classe.return_value.get_config_value.assert_called_once_with(
            ["assistant", "servers"]
        )

    def test_l_entree_ecrite_ne_porte_ni_poignee_ni_horodatage(self):
        """Un rang figé sur le disque survivrait à la suppression d'un
        voisin, et une trace de contact décrirait une machine que personne
        n'a désignée."""
        ecrits = []
        servers.save(
            [a_server()],
            set_config=lambda keys, value: ecrits.append(value),
        )
        self.assertTrue(ecrits, "rien n'a été écrit")
        for entree in ecrits[0]:
            self.assertEqual(
                sorted(entree),
                [
                    "host",
                    "hosting",
                    "label",
                    "model",
                    "port",
                    "secret_ref",
                    "software",
                ],
            )

    def test_un_serveur_sans_secret_a_une_reference_vide(self):
        charge = servers.load(
            get_config=lambda keys: [an_entry(secret_ref=None)]
        )
        self.assertTrue(charge, "l'entrée aurait dû être chargée")
        self.assertEqual(charge[0].secret_ref, "")
        ecrits = []
        servers.save(
            charge, set_config=lambda keys, value: ecrits.append(value)
        )
        self.assertEqual(ecrits[0][0]["secret_ref"], "")


class Chargement(unittest.TestCase):
    def test_une_configuration_vide_est_une_liste_vide(self):
        self.assertEqual(servers.load(get_config=lambda keys: None), [])
        self.assertEqual(servers.load(get_config=lambda keys: []), [])
        self.assertEqual(servers.load(get_config=lambda keys: {}), [])

    def test_une_section_absente_ne_leve_pas(self):
        """`get_config_value` lève `TypeError` quand la clé de tête manque :
        c'est l'état d'une machine où rien n'a encore été configuré."""

        def absente(keys):
            raise TypeError("argument of type 'NoneType' is not iterable")

        self.assertEqual(servers.load(get_config=absente), [])

    def test_un_json_abime_ou_illisible_ne_leve_pas(self):
        def abime(keys):
            raise ValueError("Expecting value")

        def illisible(keys):
            raise OSError("Permission denied")

        self.assertEqual(servers.load(get_config=abime), [])
        self.assertEqual(servers.load(get_config=illisible), [])

    def test_une_entree_corrompue_ne_fait_pas_tomber_le_chargement(self):
        entrees = [
            "une chaîne au lieu d'un objet",
            None,
            an_entry(host=""),
            an_entry(port="onze mille"),
            an_entry(port=True),
            an_entry(port=99999),
            {"host": HOST_B},
            an_entry(host=HOST_A),
        ]
        charges = servers.load(get_config=lambda keys: entrees)
        self.assertEqual([s.host for s in charges], [HOST_A])
        self.assertEqual(charges[0].handle, "server-1")

    def test_un_port_en_chaine_de_chiffres_est_accepte(self):
        charges = servers.load(get_config=lambda keys: [an_entry(port="8080")])
        self.assertTrue(charges, "l'entrée aurait dû être chargée")
        self.assertEqual(charges[0].port, 8080)

    def test_un_hebergement_inconnu_se_lit_comme_global(self):
        """La lecture est pessimiste : la classe la plus exposée impose la
        confirmation la plus stricte au lieu de la lever."""
        for stocke in ("", "atelier", None, 3):
            charges = servers.load(
                get_config=lambda keys, v=stocke: [an_entry(hosting=v)]
            )
            self.assertTrue(charges, f"entrée écartée pour {stocke!r}")
            self.assertEqual(charges[0].hosting, "global")

    def test_un_libelle_absent_retombe_sur_l_hote(self):
        charges = servers.load(
            get_config=lambda keys: [an_entry(label={"a": 1})]
        )
        self.assertTrue(charges, "l'entrée aurait dû être chargée")
        self.assertEqual(charges[0].label, HOST_A)


class RacineDApi(unittest.TestCase):
    def test_open_webui_ne_recoit_pas_un_v1(self):
        for ecrit in ("open-webui", "Open WebUI", "open_webui", "openwebui"):
            url = servers.base_url(a_server(software=ecrit, port=3000))
            self.assertEqual(url, f"http://{HOST_A}:3000/api", ecrit)
            self.assertNotIn("v1", url, ecrit)

    def test_toute_autre_famille_parle_a_v1(self):
        for ecrit in ("ollama", "llamacpp", "vllm", "lmstudio", ""):
            self.assertEqual(
                servers.base_url(a_server(software=ecrit)),
                f"http://{HOST_A}:11434/v1",
                ecrit,
            )

    def test_le_port_443_passe_en_tls(self):
        self.assertEqual(
            servers.base_url(a_server(port=443)),
            f"https://{HOST_A}:443/v1",
        )


class LaFrontiere(unittest.TestCase):
    def test_le_registre_ne_tire_pas_todo(self):
        """Importer `script.todo.todo` coûte près d'une seconde et imprime
        sur la sortie : le paquet doit rester importable seul."""
        self.assertNotIn("script.todo.todo", sys.modules)


if __name__ == "__main__":
    unittest.main()
