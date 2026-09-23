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
from script.todo import devstack_report as R  # noqa: E402
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
    # LA VM RÉPOND DÉJÀ. L'attente de sshd est bornée par le TEMPS — cinq
    # minutes de sommeil réel — et non par un nombre d'essais : laissée
    # vive, elle fait passer ces épreuves pour la mauvaise raison, une VM
    # « laissée telle quelle » n'installant rien non plus. Ce qui se juge
    # ici est le chargement des règles, pas la naissance de la machine.
    todo._pve_attendre_ssh = lambda *a, **k: True
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
        # LA RAISON DE REFUSER, ou "". Nommée « refus » et non « ok » :
        # la polarité vit dans le nom, faute de quoi un vide se lirait
        # comme un échec et une phrase comme un succès.
        vus["refus"] = todo._pve_write_guide("hote+vm-a", dict(VM), spec, mod)
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
        self.assertEqual("", vus["refus"])
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


class TestUneVmNonConfineeNeRecoitRien(unittest.TestCase):
    """La règle d'or, au dernier instant où elle peut encore tenir.

    Le chargement des règles partait dans le même lot que le guide, et son
    verdict était JETÉ : le lot pouvait céder — sudo refusé, `nft` absent,
    lien coupé — et ERPLibre s'installait quand même sur une VM qui sortait
    librement. Rien ne le disait ; le fichier de règles était peut-être même
    posé, ce qui donne exactement l'apparence du contraire.

    La VM reste au SOMMAIRE : elle existe, et il faut aller la défaire.
    C'est l'installation et le suivi qu'elle ne reçoit pas — l'un et l'autre
    se lisent comme une machine en service.
    """

    def deploie(self, posture, guide_cede):
        """Rejoue `_pve_after_create` sur une VM jointe, et rend ce qu'on a
        installé, suivi, sommé et affiché."""
        todo = menu(CARNET)
        vus = {"suivi": None}
        spec = {
            "user": "erplibre",
            "posture": posture,
            "vms": [dict(VM, vmid=101, ipconfig="ip=198.51.100.5/24")],
            "install": {"cmd": "make install_os", "branch": "develop"},
            "monitor": False,
            "add_ssh_config": True,
            "storage": "local",
            "bridge": "vmbr0",
            "res_label": "",
        }
        todo._qemu_list_domains = lambda: []
        todo._pve_alias_names = lambda *a, **k: (["pve+vm-a"], "")
        todo._qemu_write_ssh_config = lambda *a, **k: None
        todo._pve_alias_perime = lambda *a, **k: []
        todo._ssh_private_key = lambda *a, **k: ""
        todo._pve_set_timezone = lambda *a, **k: None
        todo._pve_print_summary = lambda *a, **k: None
        todo._qemu_per_vm = lambda cartes, commun: False
        # LE VRAI POSEUR DE LA VOIE NON SUIVIE, une VM à la fois. Le
        # laisser passer ferait partir une installation réelle par ssh :
        # l'épreuve a mis une minute à ne rien prouver avant qu'on le voie.
        todo._qemu_install_erplibre_vm = lambda nom, *a, **k: vus.setdefault(
            "installe", []
        ).append(nom)
        todo._qemu_install_erplibre_monitored = (
            lambda noms, *a, **k: vus.update(suivi=list(noms))
        )
        # Le lot du guide cède, ou passe. C'est le SEUL levier de l'épreuve.
        todo._pve_ssh = lambda *a, **k: (
            (255, "no route") if guide_cede else (0, "")
        )
        host = {"target": "compte@pve.example", "sudo": "", "jump": ""}
        with contextlib.redirect_stdout(io.StringIO()) as sortie:
            vus["sommaire"] = todo._pve_after_create(host, spec, {"vm-a"}, "")
        vus["ecran"] = sortie.getvalue()
        return vus

    def test_a_confined_vm_whose_rules_did_not_load_is_not_installed(self):
        vus = self.deploie("local-only", guide_cede=True)
        self.assertEqual([], vus.get("installe", []))
        self.assertIsNone(vus["suivi"])

    def test_it_says_which_vm_and_why(self):
        """Écarter sans nommer laisserait chercher une panne d'installation
        là où il n'y a qu'une posture qui n'a pas pris."""
        ecran = self.deploie("local-only", guide_cede=True)["ecran"]
        self.assertIn("vm-a", ecran)
        self.assertIn(t("egress rules did not load"), ecran)

    def test_it_stays_in_the_summary_because_it_exists(self):
        """Une VM créée et écartée doit se retrouver : il faut aller la
        défaire."""
        vus = self.deploie("local-only", guide_cede=True)
        self.assertEqual(["vm-a"], [vm["name"] for vm in vus["sommaire"]])

    def test_the_same_failure_without_a_posture_installs_anyway(self):
        """Contrôle négatif. Sans posture, le lot qui cède ne coûte qu'un
        guide — et un guide manquant n'est pas une promesse rompue. Refuser
        ici ferait payer à la sortie libre le prix du confinement."""
        vus = self.deploie("open", guide_cede=True)
        self.assertEqual(["vm-a"], vus.get("installe", []))

    def test_a_confined_vm_whose_rules_loaded_is_installed(self):
        """Contrôle positif : refuser tout passerait les trois précédents."""
        vus = self.deploie("local-only", guide_cede=False)
        self.assertEqual(["vm-a"], vus.get("installe", []))


class TestProxmoxRelitSaPosture(unittest.TestCase):
    """La voie Proxmox ne relisait JAMAIS la posture d'une VM.

    Son seul verdict venait du code de retour du lot qui pose et charge, à
    la pose. Un rechargement qui échoue à un démarrage ULTÉRIEUR laisse la
    machine debout et sortante, et rien ne le disait — là où la voie libvirt
    offre « vérifier une VM déployée, couche par couche » autant de fois
    qu'on veut.
    """

    HOTE = {"target": "compte@pve.example", "sudo": "", "jump": ""}

    def ecran(self, reponse_invitee):
        """Rejoue la vérification sur une VM, et rend (verdict, affichage)."""
        todo = menu()
        vus = {}
        todo._pve_host = lambda ask=True: dict(self.HOTE)
        todo._pve_pick_vm = lambda *a, **k: {"vmid": 101, "name": "vm-a"}
        todo._pve_ssh = lambda cible, remote, timeout=60: (
            vus.update(cible=cible, remote=remote) or (0, reponse_invitee)
        )
        with contextlib.redirect_stdout(io.StringIO()) as sortie:
            vus["verdict"] = todo._pve_verify_egress()
        vus["ecran"] = sortie.getvalue()
        return vus

    def mot(self, verdict):
        """Ce qu'une VM répond pour ce verdict, par la sonde du dépôt."""
        return f"{posture_plan.MARQUEUR}{verdict}"

    def test_it_asks_the_vm_through_its_alias(self):
        """Par l'alias et non par l'adresse : lui seul porte le rebond vers
        le réseau interne de l'hôte."""
        vus = self.ecran(self.mot(posture_plan.LOADED))
        self.assertEqual("pve.example+vm-a", vus["cible"])

    def test_the_probe_is_the_one_the_deployment_uses(self):
        """Une seconde sonde écrite ici divergerait de celle du déploiement
        le jour où l'une des deux change."""
        vus = self.ecran(self.mot(posture_plan.LOADED))
        self.assertEqual(posture_plan.probe_command(), vus["remote"])

    def test_a_loaded_table_reads_as_confined(self):
        vus = self.ecran(self.mot(posture_plan.LOADED))
        self.assertEqual(R.DS_OK, vus["verdict"])

    def test_an_absent_table_is_never_read_as_confined(self):
        """Le défaut que cette entrée existe pour voir."""
        vus = self.ecran(self.mot(posture_plan.TABLE_ABSENT))
        self.assertNotEqual(R.DS_OK, vus["verdict"])

    def test_a_missing_analyser_is_named_apart(self):
        """« pas d'outil » et « pas de table » ne se corrigent pas au même
        endroit : l'un s'installe, l'autre se recharge."""
        outil = self.ecran(self.mot(posture_plan.TOOL_ABSENT))["ecran"]
        table = self.ecran(self.mot(posture_plan.TABLE_ABSENT))["ecran"]
        self.assertNotEqual(outil, table)

    def test_a_silent_vm_is_not_read_as_confined(self):
        """Ce qui n'a pas été lu vaut « non lu », jamais « chargé » : un
        silence annoncé comme une garantie est le mensonge que cette
        relecture existe pour empêcher."""
        vus = self.ecran("")
        self.assertNotEqual(R.DS_OK, vus["verdict"])


class TestLAliasNeSeRecopiePlus(unittest.TestCase):
    """La convention « hôte+vm » était écrite à chaque appelant.

    Un caractère de plus admis d'un côté suffit à ce que l'autre cherche un
    alias qui n'existe pas — et l'écran qui écrit ~/.ssh/config et celui qui
    y revient sont justement deux appelants différents.
    """

    def test_one_place_composes_it(self):
        import ast
        import inspect

        from script.todo import proxmox_menu

        source = inspect.getsource(proxmox_menu)
        arbre = ast.parse(source)
        # La sanitisation du nom d'hôte est la marque de la convention.
        recopies = [
            n.lineno
            for n in ast.walk(arbre)
            if isinstance(n, ast.Constant)
            and isinstance(n.value, str)
            and n.value == "[^A-Za-z0-9._-]"
        ]
        self.assertEqual(
            1, len(recopies), f"la convention est écrite {len(recopies)} fois"
        )

    def test_the_composer_sanitises_and_falls_back(self):
        from script.todo.todo import TODO

        compose = TODO._pve_alias_chaine
        self.assertEqual(
            "pve.example+vm-a",
            compose({"target": "compte@pve.example"}, "vm-a"),
        )
        # Un hôte dont le nom ne porte aucun caractère admis : le repli
        # nomme quand même quelque chose, sinon l'alias commencerait par
        # « + » et ssh chercherait une machine sans nom.
        self.assertTrue(compose({"target": "compte@///"}, "x").endswith("+x"))
        self.assertTrue(compose({}, "x").startswith("pve+"))


if __name__ == "__main__":
    unittest.main()
