#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le confinement sur la voie Proxmox : posé, chargé, et refusé à temps.

Cette voie créait ses VM sans aucune règle de sortie quelle que soit la
posture demandée. Le mécanisme existait pourtant de bout en bout : le
rendu, l'unité, et jusqu'à `guide_files`, qui ajoute les deux fichiers à sa
liste dès qu'on les lui donne. Personne ne les lui donnait ici.

TROIS CHOSES, ET AUCUNE NE SUFFIT SEULE. Écrire les règles sans les charger
laisse la machine sortir pour toujours, tout en donnant l'apparence du
contraire. Les charger sans armer l'unité la laisse sortir dès le deuxième
démarrage. Et refuser un couple (posture, données réelles) incohérent après
« qm create » coûte une VM à détruire, là où le même refus avant ne coûte
rien.

Le carnet du site est une donnée de SITE. Celui d'ici est de banc, et ses
adresses sont des plages de documentation (RFC 5737).
"""

import contextlib
import io
import os
import sys
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

sys.argv = ["todo.py"]

from script.posture import allowlist as A  # noqa: E402
from script.posture import plan as posture_plan  # noqa: E402
from script.qemu import deploy_qemu as DQ  # noqa: E402
from script.todo.proxmox_deploy_form import build_spec  # noqa: E402
from script.todo.todo import TODO  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402

CARNET = {
    nom: [f"198.51.100.{index + 10}/32"]
    for index, nom in enumerate(A.symbol_names())
}

VM = {
    "name": "vm-a",
    "distro": "ubuntu",
    "version": "24.04",
    "arch": "amd64",
    "desktop": "",
    "install_cmd": "",
}


def menu(carnet=None):
    """Un TODO nu, dont la configuration rend le carnet demandé."""
    todo = TODO.__new__(TODO)
    todo.config_file = type(
        "ConfigDeBanc",
        (),
        {"get_config": staticmethod(lambda _cle: carnet)},
    )()
    return todo


def ecrit(posture, carnet=CARNET):
    """Rejoue la pose du guide et rend ce qui est parti par ssh."""
    todo = menu(carnet)
    vus = {}
    todo._pve_ssh = lambda cible, remote, timeout=60: (
        vus.update(remote=remote) or (0, "")
    )
    mod = todo._qemu_import_module()
    spec = {"user": "erplibre", "install": None, "posture": posture}
    with contextlib.redirect_stdout(io.StringIO()) as sortie:
        vus["ok"] = todo._pve_write_guide("hote+vm-a", dict(VM), spec, mod)
    vus["ecran"] = sortie.getvalue()
    return vus


class TestCeQuiEstPose(unittest.TestCase):
    def test_a_posture_that_asks_for_nothing_writes_no_rules(self):
        """La sortie libre n'a rien à contraindre, et ne doit rien payer."""
        remote = ecrit("open")["remote"]
        self.assertNotIn(DQ.EGRESS_GUEST_PATH, remote)
        self.assertNotIn(DQ.EGRESS_UNIT_PATH, remote)

    def test_a_confined_posture_lays_the_rules_down(self):
        remote = ecrit("local-only")["remote"]
        self.assertIn(DQ.EGRESS_GUEST_PATH, remote)
        self.assertIn("sudo tee", remote)

    def test_it_lays_the_unit_down_too(self):
        """Le fichier de règles seul ne survit pas au redémarrage."""
        self.assertIn(DQ.EGRESS_UNIT_PATH, ecrit("local-only")["remote"])

    def test_the_unit_is_the_one_the_posture_package_owns(self):
        """Une recopie divergerait au premier correctif.

        Une ligne SANS apostrophe : le contenu part cité par shlex, qui
        réécrit les apostrophes de l'unité — chercher « ExecStart » ne
        prouverait alors que la citation."""
        marque = [
            ligne.strip()
            for ligne in posture_plan.unit_text().splitlines()
            if ligne.strip().startswith("Description=")
        ][0]
        self.assertIn(marque, ecrit("local-only")["remote"])

    def test_a_bounded_posture_names_the_book_addresses(self):
        remote = ecrit("paranoid")["remote"]
        self.assertIn("198.51.100.10/32", remote)


class TestCeQuiEstCharge(unittest.TestCase):
    """Poser sans charger laisse la machine sortir pour toujours."""

    def test_the_rules_are_loaded_in_the_same_batch(self):
        remote = ecrit("local-only")["remote"]
        self.assertIn(f"nft -f {DQ.EGRESS_GUEST_PATH}", remote)

    def test_the_unit_is_armed_in_the_same_batch(self):
        remote = ecrit("local-only")["remote"]
        self.assertIn(f"systemctl enable {DQ.EGRESS_UNIT_NAME}", remote)

    def test_arming_comes_before_loading(self):
        """Charger puis armer laisserait une fenêtre au deuxième
        démarrage si le lot cédait entre les deux.

        L'ordre se lit sur les commandes elles-mêmes et non sur le lot :
        le texte de l'unité CONTIENT « nft -f /etc/erplibre-egress.nft »,
        et une recherche de position dans le lot y tomberait d'abord."""
        todo = menu(CARNET)
        mod = todo._qemu_import_module()
        commandes = todo._pve_egress_arm("table inet {}", "[Unit]", mod)
        self.assertIn(DQ.EGRESS_UNIT_NAME, commandes[0])
        self.assertIn("nft -f", commandes[1])

    def test_nothing_is_loaded_when_nothing_is_posed(self):
        remote = ecrit("open")["remote"]
        self.assertNotIn("nft -f", remote)
        self.assertNotIn("systemctl enable", remote)

    def test_the_operator_is_told_the_rules_are_armed(self):
        """Un déploiement silencieux ne se distingue pas d'un déploiement
        qui n'a rien posé."""
        self.assertIn("✓", ecrit("local-only")["ecran"])


class TestLeCarnetVide(unittest.TestCase):
    """Une posture qui attend des adresses que le site n'a pas nommées.

    Ce chemin est le DERNIER RECOURS : le rendu est désormais tenté à la
    porte, avant « qm create », comme le font libvirt et Lima. On n'arrive
    donc plus ici par le carnet — mais s'il s'y trouve une autre cause, la
    machine EXISTE déjà, et s'arrêter ne la confinerait pas davantage.

    Ce qui se dit alors compte double : c'est le seul endroit d'où l'on
    peut apprendre qu'une posture n'est pas tenue.
    """

    def test_the_guide_still_goes_out(self):
        """S'arrêter ici laisserait une VM debout ET sans son guide : deux
        manques au lieu d'un."""
        vus = ecrit("paranoid", carnet={})
        self.assertTrue(vus["ok"])
        self.assertIn("/etc/motd", vus["remote"])

    def test_no_rule_is_laid(self):
        vus = ecrit("paranoid", carnet={})
        self.assertNotIn(DQ.EGRESS_GUEST_PATH, vus["remote"])

    def test_the_screen_says_the_machine_is_not_confined(self):
        """« Règles non rendues » se lisait comme un détail d'affichage au
        milieu d'un flot de déploiement. Ce qui compte est qu'une posture
        de confinement n'est PAS tenue sur une machine qui tourne."""
        ecran = ecrit("paranoid", carnet={})["ecran"]
        self.assertIn(t("This VM gets NO egress rule:"), ecran)
        self.assertIn(
            t("It runs with free egress, despite its posture."), ecran
        )


class TestLesDeuxHelpers(unittest.TestCase):
    """Ce que rendent les deux fonctions, sans passer par ssh."""

    def test_texts_are_empty_for_a_free_posture(self):
        todo = menu(CARNET)
        mod = todo._qemu_import_module()
        self.assertEqual(("", ""), todo._pve_egress_texts({}, mod))

    def test_arming_is_empty_without_rules(self):
        todo = menu(CARNET)
        mod = todo._qemu_import_module()
        self.assertEqual([], todo._pve_egress_arm("", "", mod))

    def test_arming_without_a_unit_still_loads(self):
        """Un rendu sans unité doit quand même charger : sortir librement
        parce que l'unité manque serait le pire des deux."""
        todo = menu(CARNET)
        mod = todo._qemu_import_module()
        commandes = todo._pve_egress_arm("table inet {}", "", mod)
        self.assertEqual(1, len(commandes))
        self.assertIn("nft -f", commandes[0])


class TestLaRegleDOr(unittest.TestCase):
    """Le refus arrive AVANT que la machine existe.

    Après « qm create », une posture incohérente se corrige en détruisant
    la VM : le même refus, au même endroit, ne coûte rien une minute plus
    tôt.
    """

    def _deploie(self, posture, real_data):
        todo = menu(CARNET)
        touche = []
        todo._pve_confirm_spec = lambda *a, **k: touche.append("confirm")
        todo._pve_push_key = lambda *a, **k: touche.append("key")
        todo._qemu_default_ssh_key = staticmethod(lambda: "")
        spec = {
            "storage": "local-lvm",
            "bridge": "vmbr0",
            "vms": [dict(VM, vmid=100)],
            "posture": posture,
            "real_data": real_data,
        }
        with contextlib.redirect_stdout(io.StringIO()) as sortie:
            todo._pve_deploy_spec({"target": "hote"}, spec, None)
        return sortie.getvalue(), touche

    def test_an_unknown_posture_is_refused(self):
        """Replier sur la plus libre déploierait en sortie libre une spec
        qui demandait du confinement."""
        ecran, touche = self._deploie("posture-inventee", False)
        self.assertIn("unknown-posture", ecran)
        self.assertEqual([], touche)

    def test_real_data_on_an_unconfined_posture_is_refused(self):
        ecran, touche = self._deploie("open", True)
        self.assertIn("real-data-unconfined", ecran)
        self.assertEqual([], touche)

    def test_a_coherent_pair_goes_through_to_the_confirmation(self):
        _ecran, touche = self._deploie("local-only", True)
        self.assertIn("confirm", touche)


class TestLaSpecPorteLeChoix(unittest.TestCase):
    """Une clé non nommée par `build_spec` n'existe pas pour le
    déploiement, quel que soit le widget qui l'a produite."""

    FORM = {
        "host": {"target": "hote"},
        "storage": "local-lvm",
        "bridge": "vmbr0",
        "res_label": "x1",
        "ssh_key": "",
        "start": True,
        "add_ssh_config": False,
        "install": None,
        "monitor": False,
        "parallelism": 1,
    }

    def test_the_posture_reaches_the_spec(self):
        spec = build_spec([dict(VM)], [], dict(self.FORM, posture="paranoid"))
        self.assertEqual("paranoid", spec["posture"])

    def test_real_data_reaches_the_spec(self):
        spec = build_spec([dict(VM)], [], dict(self.FORM, real_data=True))
        self.assertIs(True, spec["real_data"])

    def test_an_older_form_still_builds(self):
        """Les deux clés absentes valent « rien de demandé », et non une
        erreur : la voie par questions n'en pose aucune."""
        spec = build_spec([dict(VM)], [], dict(self.FORM))
        self.assertEqual("", spec["posture"])
        self.assertIs(False, spec["real_data"])


if __name__ == "__main__":
    unittest.main()
