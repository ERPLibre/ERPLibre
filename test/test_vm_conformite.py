#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Chaque verbe, chaque backend : ou bien il rend, ou bien il REFUSE.

Ce qu'aucune épreuve ne tenait, et qui a laissé passer deux fois la même
faute : un verbe éprouvé sur deux backends composait, pour le troisième, une
commande à cible VIDE — « ssh compte@ » — sans rien lever. ssh la refuse
alors par un message qui ne nomme aucune machine, et l'écran ne peut pas
dire ce qui manque.

Le contrat tenu ici : pour tout couple (verbe, identité), soit la commande
est UTILISABLE, soit `VerbNotImplemented` le dit. Le silence entre les deux
est ce qui est interdit — c'est la place où un backend neuf tombe, et il y
tombe sans bruit.

« Utilisable » se vérifie par le DÉCOUPAGE : aucun mot vide, aucun mot qui
s'arrête sur « @ ». Relire la chaîne ne prouverait rien.
"""

import os
import shlex
import sys
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

from script.vm import backend as B  # noqa: E402
from script.vm import verbs as V  # noqa: E402

# Les verbes qui composent une commande, chacun ramené à UNE chaîne. Ceux
# qui rendent un enregistrement sont réduits à leur champ de commande.
VERBES = (
    ("delete_command", lambda h: V.delete_command(h)),
    ("console", lambda h: V.console(h).command),
    ("power_command", lambda h: V.power_command(h, "suspend")),
    ("host_command", lambda h: V.host_command(h, "vrai")),
    ("ssh_prefix", lambda h: V.ssh_prefix(h)),
    ("exec_prefix", lambda h: V.exec_prefix(h)),
    ("identity_guard", lambda h: V.identity_guard(h)),
    ("web_access", lambda h: " ".join(V.web_access(h).tunnel)),
)

# Deux états par backend : la fiche COMPLÈTE, et la fiche NUE — celle d'un
# manifeste ancien ou d'une machine à peine créée. C'est la nue qui révèle
# les cibles vides, et c'est elle qu'on oublie d'éprouver.
FICHES = (
    (
        "libvirt complète",
        B.libvirt_handle("vm-a", uuid="abc-123", ip="192.0.2.10"),
    ),
    ("libvirt nue", B.libvirt_handle("vm-a")),
    (
        "pve complète",
        B.pve_handle(
            {
                "vmid": 101,
                "target": "hote.exemple",
                "addr": "198.51.100.7",
                "sudo": "sudo ",
            },
            "vm-a",
            alias="hote+vm-a",
        ),
    ),
    ("pve nue", B.pve_handle({"vmid": 101}, "vm-a")),
    ("lima", B.lima_handle("vm-a")),
    ("lima avec adresse", B.lima_handle("vm-a", ip="192.0.2.10")),
)


def mots_douteux(commande):
    """Les mots qui trahissent une cible manquante, ou () s'il n'y en a pas.

    Un mot VIDE, ou qui s'arrête sur « @ » : dans les deux cas la commande
    part vers personne. Le découpage est fait par l'analyseur du shell, et
    non par une lecture de la chaîne — c'est lui qui décidera pour de vrai.
    """
    try:
        mots = shlex.split(commande)
    except ValueError:
        return ("citation déséquilibrée",)
    return tuple(
        mot for mot in mots if not mot.strip() or mot.rstrip().endswith("@")
    )


class TestChaqueVerbeRendOuRefuse(unittest.TestCase):
    def test_the_table_covers_every_backend(self):
        """Un backend absent de la table passerait toutes les épreuves."""
        couverts = {fiche.backend for _nom, fiche in FICHES}
        self.assertEqual(set(B.BACKENDS), couverts)
        self.assertGreaterEqual(len(VERBES), 8)

    def test_nothing_ever_composes_an_empty_target(self):
        """LA faute que ce fichier existe pour empêcher, et qui est passée
        deux fois : « ssh compte@ », que ssh refuse par un message ne nommant
        aucune machine."""
        for nom_verbe, verbe in VERBES:
            for nom_fiche, fiche in FICHES:
                with self.subTest(verbe=nom_verbe, fiche=nom_fiche):
                    try:
                        rendu = verbe(fiche)
                    except B.VerbNotImplemented:
                        continue
                    self.assertEqual(
                        (),
                        mots_douteux(rendu),
                        f"{nom_verbe}({nom_fiche}) -> {rendu!r}",
                    )

    def test_a_refusal_is_never_a_bare_exception(self):
        """Un backend qui ne sait pas faire doit le DIRE avec le type prévu :
        l'appelant retire alors l'entrée proprement, là où une autre
        exception l'envoie chercher ce qui ne va pas."""
        for nom_verbe, verbe in VERBES:
            for nom_fiche, fiche in FICHES:
                with self.subTest(verbe=nom_verbe, fiche=nom_fiche):
                    try:
                        verbe(fiche)
                    except B.VerbNotImplemented:
                        pass
                    except Exception as autre:  # noqa: BLE001
                        self.fail(
                            f"{nom_verbe}({nom_fiche}) lève"
                            f" {type(autre).__name__} : {autre}"
                        )

    def test_no_identity_is_refused_by_every_verb(self):
        """Aucun verbe ne doit inventer une machine à partir de rien."""
        for nom_verbe, verbe in VERBES:
            with self.subTest(verbe=nom_verbe):
                with self.assertRaises(B.VerbNotImplemented):
                    verbe(None)

    def test_an_unknown_backend_is_refused_by_every_verb(self):
        """Le vocabulaire est clos : un quatrième nom ne doit hériter du
        chemin d'aucun des trois."""
        inconnu = B.libvirt_handle("vm-a", ip="192.0.2.10")._replace(
            backend="jamais-un-backend"
        )
        for nom_verbe, verbe in VERBES:
            with self.subTest(verbe=nom_verbe):
                with self.assertRaises(B.VerbNotImplemented):
                    verbe(inconnu)


class TestCeQueChaqueBackendSaitFaire(unittest.TestCase):
    """L'inventaire, pour que l'écran puisse retirer ce qui n'existe pas."""

    def su(self, fiche):
        rendus = set()
        for nom_verbe, verbe in VERBES:
            try:
                verbe(fiche)
            except B.VerbNotImplemented:
                continue
            rendus.add(nom_verbe)
        return rendus

    def test_a_local_vm_answers_everything_but_the_host_verbs(self):
        """`host_command` s'adresse à la machine PORTEUSE : une VM locale
        n'en a pas, et le refus est juste."""
        su = self.su(FICHES[0][1])
        self.assertIn("delete_command", su)
        self.assertIn("console", su)
        self.assertIn("ssh_prefix", su)
        self.assertNotIn("host_command", su)

    def test_a_hosted_vm_answers_every_verb(self):
        """Contrôle positif : c'est le backend le plus complet."""
        complete = next(f for n, f in FICHES if n == "pve complète")
        self.assertEqual({v for v, _ in VERBES}, self.su(complete))

    def test_the_new_backend_answers_only_what_it_can(self):
        """Il ne sait qu'entrer et exécuter, et c'est déjà son apport."""
        su = self.su(B.lima_handle("vm-a"))
        self.assertIn("exec_prefix", su)
        self.assertNotIn("delete_command", su)
        self.assertNotIn("console", su)
        self.assertNotIn("ssh_prefix", su)


if __name__ == "__main__":
    unittest.main()
