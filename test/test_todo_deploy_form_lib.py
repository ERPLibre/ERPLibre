#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le socle commun aux deux formulaires de déploiement.

Le formulaire QEMU/KVM et le formulaire Proxmox posent le même travail :
choisir des systèmes, régler des ressources, vérifier le plan, lancer. Ce qui
est commun vit dans `deploy_form_lib` (logique pure, socle CSS, fabrique des
ressources) et `deploy_form_plan` (surcharges, verrous, exemplaires,
renommage). Ces tests gardent DEUX propriétés :

* le socle fait ce qu'il dit — une ressource libre, un verrou, un écho de
  montage pris pour une saisie ;
* les deux formulaires s'en servent VRAIMENT, au lieu de le redire chacun de
  son côté. C'est la seule chose qui empêche l'architecture de retomber en
  deux copies qui divergent.
"""

import ast
import pathlib
import sys
import unittest

sys.argv = ["todo.py"]
from script.todo import deploy_form_lib as lib  # noqa: E402
from script.todo import deploy_form_plan as plan  # noqa: E402

RACINE = pathlib.Path(__file__).resolve().parent.parent
TODO_DIR = RACINE / "script" / "todo"


class TestRessourcesLibres(unittest.TestCase):
    """« autre… » ne vaut pas zéro : il révèle une saisie."""

    def test_the_free_sentinel_closes_the_list(self):
        choix = lib.res_choices([2, 4, 8])
        self.assertEqual(choix[-1][1], lib.FREE)
        self.assertEqual([v for _l, v in choix[:-1]], ["2", "4", "8"])

    def test_a_formatter_shapes_the_labels(self):
        choix = lib.res_choices([2048, 4096], fmt=lambda v: f"{v // 1024}G")
        self.assertEqual([lbl for lbl, _v in choix[:-1]], ["2G", "4G"])

    def test_free_without_typing_keeps_the_default(self):
        # Le piège payé : valider un formulaire à peine ouvert rétrécissait
        # les machines à zéro.
        self.assertEqual(lib.res_value(lib.FREE, "", 4096), 4096)
        self.assertEqual(lib.res_value(None, "  ", 2), 2)

    def test_a_typed_value_wins(self):
        self.assertEqual(lib.res_value(lib.FREE, "12", 2), 12)
        self.assertEqual(lib.res_value("8", "", 2), 8)


class TestLesBranches(unittest.TestCase):
    """« git ls-remote » rend les branches par ordre alphabétique.

    Rapporté : le formulaire Proxmox proposait « dependabot/pip/aiobotocore-
    3.1.3 » — la première de la liste. Le bon défaut est la branche du DÉPÔT
    qu'on a sous les yeux, puis develop, puis master.
    """

    BRANCHES = [
        "dependabot/pip/aiobotocore-3.1.3",
        "dependabot/pip/boto3-1.42.49",
        "develop",
        "dev_mobile",
        "master",
    ]

    def test_the_checkout_branch_wins(self):
        self.assertEqual(
            lib.branch_default(self.BRANCHES, "dev_mobile"), "dev_mobile"
        )

    def test_without_it_develop_then_master(self):
        self.assertEqual(lib.branch_default(self.BRANCHES, ""), "develop")
        sans_develop = [b for b in self.BRANCHES if b != "develop"]
        self.assertEqual(lib.branch_default(sans_develop, ""), "master")

    def test_a_branch_that_no_longer_exists_is_ignored(self):
        # On déploie une branche qui existe, pas celle qu'on avait localement.
        self.assertEqual(
            lib.branch_default(self.BRANCHES, "partie-en-fumée"), "develop"
        )

    def test_the_last_resort_is_the_first_but_never_by_default(self):
        self.assertEqual(lib.branch_default(["zzz"], ""), "zzz")
        self.assertEqual(lib.branch_default([], "develop"), "")

    def test_the_list_puts_the_useful_ones_first(self):
        ordre = lib.branch_order(self.BRANCHES, "dev_mobile")
        self.assertEqual(ordre[:3], ["dev_mobile", "develop", "master"])

    def test_the_robots_go_last(self):
        ordre = lib.branch_order(self.BRANCHES, "develop")
        self.assertTrue(all(b.startswith("dependabot/") for b in ordre[-2:]))

    def test_nothing_is_lost_nor_duplicated(self):
        # La branche du dépôt EST souvent « develop » : la voir deux fois
        # ferait douter de la liste.
        ordre = lib.branch_order(self.BRANCHES, "develop")
        self.assertEqual(sorted(ordre), sorted(self.BRANCHES))
        self.assertEqual(len(ordre), len(set(ordre)))


class TestPlaceDisque(unittest.TestCase):
    """La demande du plan ne dit pas si ça rentre : il faut la place à côté."""

    def test_it_shows_the_demand_the_room_and_the_capacity(self):
        # Comparé à la traduction et non au français : la langue de
        # l'interface se change (EL_LANG), et un test qui la suppose échoue
        # pour une raison étrangère à ce qu'il vérifie.
        self.assertEqual(
            lib.disk_note(50, 20, 270),
            f"~50 G / 20 G {lib.t('free of')} 270 G",
        )

    def test_without_a_capacity_it_still_shows_the_room(self):
        self.assertEqual(
            lib.disk_note(50, 20), f"~50 G / 20 G {lib.t('free')}"
        )

    def test_without_a_measure_it_invents_nothing(self):
        # Une place inconnue ne doit pas se lire comme « 0 Go libres ».
        self.assertEqual(lib.disk_note(50, 0, 0), "~50 G")
        self.assertEqual(lib.disk_note(50, 0, 270), "~50 G")

    def test_bytes_become_whole_gibibytes(self):
        self.assertEqual(lib.gib(90 * (1 << 30)), 90)
        self.assertEqual(lib.gib(0), 0)
        # Une mesure absente ou illisible vaut zéro, pas une exception : la
        # ligne de totaux doit s'afficher même quand l'hôte n'a rien répondu.
        self.assertEqual(lib.gib(None), 0)
        self.assertEqual(lib.gib("x"), 0)


class TestEtatDuNom(unittest.TestCase):
    """Un nom déjà pris, un disque resté seul : deux gravités différentes."""

    def test_a_defined_vm_is_skipped(self):
        etat, note = lib.vm_status(
            "erplibre-debian-13", ["erplibre-debian-13"]
        )
        self.assertEqual(etat, "exists")
        self.assertTrue(note)

    def test_the_orphan_probe_is_replaceable(self):
        # Proxmox distant : ses disques vivent dans un stockage que seul
        # l'hôte connaît, jamais dans /var/lib/libvirt.
        etat, _n = lib.vm_status("x", [], orphelin=lambda _n: False)
        self.assertEqual(etat, "new")
        etat, _n = lib.vm_status("x", [], orphelin=lambda _n: True)
        self.assertEqual(etat, "orphan")

    def test_plan_rows_carries_the_probe(self):
        vms = [{"name": "x", "vcpus": 2, "ram": 2048, "disk": "32G"}]
        rows = lib.plan_rows(vms, [], 0, orphelin=lambda _n: True)
        self.assertEqual(rows[0]["state"], "orphan")


class FauxPlan(plan.PlanMixin):
    """Le strict contrat du mixin, sans Textual : de quoi éprouver ce qui ne
    touche pas à l'écran."""

    def __init__(self, entrees):
        self.entrees = entrees
        self.copies = {}
        self.overrides = {}
        self.locked = set()
        self.custom = {}
        self.rows = []
        self._gen = 0
        self._shown_ids = ()

    def _selected_entries(self):
        return self.entrees


def entree(distro, version, arch="amd64"):
    return {
        "name": f"erplibre-{distro}-{version}",
        "distro": distro,
        "version": version,
        "arch": arch,
        "ram": 2048,
        "disk": "32G",
    }


class TestSocleDuPlan(unittest.TestCase):
    def setUp(self):
        self.app = FauxPlan(
            [entree("debian", "13"), entree("ubuntu", "26.04")]
        )
        self.app.rows = [
            {
                "vm": {
                    "name": e["name"],
                    "distro": e["distro"],
                    "version": e["version"],
                    "arch": e["arch"],
                    "vcpus": 2,
                    "ram": 2048,
                    "disk": "32G",
                },
                "state": "new",
                "note": "",
                "disk_gb": 32,
            }
            for e in self.app.entrees
        ]

    def test_an_override_is_written_then_dropped(self):
        self.app._set_override(0, "ram", 8192)
        cle = self.app._row_key(0)
        self.assertEqual(self.app.overrides[cle]["ram"], 8192)
        # Une saisie vidée RETIRE la surcharge : écrire zéro donnerait une VM
        # à 0 vCPU.
        self.app._set_override(0, "ram", 0)
        self.assertNotIn(cle, self.app.overrides)

    def test_a_common_setting_reclaims_the_unlocked_rows(self):
        self.app._set_override(0, "ram", 8192)
        self.app._set_override(1, "ram", 8192)
        self.app.locked.add(self.app._row_key(1))
        self.app._clear_overrides(("ram",))
        self.assertNotIn(self.app._row_key(0), self.app.overrides)
        self.assertIn(self.app._row_key(1), self.app.overrides)

    def test_clearing_is_per_field(self):
        self.app._set_override(0, "ram", 8192)
        self.app._set_override(0, "disk", "64G")
        self.app._clear_overrides(("ram",))
        self.assertEqual(
            self.app.overrides[self.app._row_key(0)], {"disk": "64G"}
        )

    def test_a_command_drags_its_label_along(self):
        cle = self.app._row_key(0)
        self.app.overrides[cle] = {
            "install_cmd": "make install_odoo_18",
            "install_label": "Odoo 18",
        }
        self.app._clear_overrides(("install_cmd",))
        self.assertNotIn(cle, self.app.overrides)

    def test_the_mount_echo_is_not_input(self):
        # La valeur que le modèle porte déjà : c'est l'écho du montage.
        self.assertTrue(self.app._row_echo(0, "ram", 2048))
        self.assertFalse(self.app._row_echo(0, "ram", 4096))
        # Rang hors plan : rien à appliquer.
        self.assertTrue(self.app._row_echo(99, "ram", 1))

    def test_copies_expand_the_selection(self):
        self.app.copies[("debian", "13", "amd64")] = 1
        entrees = self.app._plan_entries()
        self.assertEqual(len(entrees), 3)
        self.assertEqual(len(set(lib.entry_key(e) for e in entrees)), 3)

    def test_the_head_line_names_what_is_special(self):
        self.app.rows[0]["locked"] = True
        self.assertIn("🔒", self.app._row_head(0, self.app.rows[0]))
        self.app.rows[1]["custom"] = True
        self.assertIn("✎", self.app._row_head(1, self.app.rows[1]))
        self.assertIn("debian", self.app._row_head(0, self.app.rows[0]))

    def test_locking_copies_the_resources(self):
        gele = self.app._lock_fields(0)
        self.assertEqual(gele["ram"], 2048)
        self.assertEqual(gele["disk"], "32G")
        self.assertEqual(gele["vcpus"], 2)


def membres(chemin, classe=None):
    """Noms des fonctions/méthodes définies dans un fichier (ou une classe)."""
    arbre = ast.parse(pathlib.Path(chemin).read_text(encoding="utf-8"))
    trouves = set()
    for n in ast.walk(arbre):
        if isinstance(n, ast.ClassDef) and (
            classe is None or n.name == classe
        ):
            trouves |= {
                m.name for m in n.body if isinstance(m, ast.FunctionDef)
            }
        if classe is None and isinstance(n, ast.FunctionDef):
            trouves.add(n.name)
    return trouves


class TestPasDeDoublon(unittest.TestCase):
    """L'architecture demandée : un seul endroit par idée.

    Ces tests échouent le jour où quelqu'un recopie un geste du plan dans un
    formulaire plutôt que de l'appeler. C'est exactement ce qu'ils gardent.
    """

    PARTAGES = {
        "_plan_entries",
        "_row_ids",
        "_row_key",
        "_is_current",
        "_focused_row",
        "_set_override",
        "_clear_overrides",
        "_set_lock",
        "_add_copy",
        "_rename",
        "_row_free",
        "_read_row_free",
        "_show_free",
        "_apply_free",
        "_sync_free_inputs",
        "_row_echo",
    }

    def test_the_mixin_owns_the_plan_gestures(self):
        self.assertTrue(
            self.PARTAGES <= membres(TODO_DIR / "deploy_form_plan.py")
        )

    def test_neither_form_redefines_them(self):
        for fichier in ("qemu_deploy_form.py", "proxmox_deploy_form.py"):
            redits = self.PARTAGES & membres(TODO_DIR / fichier)
            self.assertEqual(
                redits,
                set(),
                f"{fichier} redit ce que le socle porte déjà : {redits}",
            )

    def test_both_forms_inherit_the_mixin(self):
        for fichier in ("qemu_deploy_form.py", "proxmox_deploy_form.py"):
            src = pathlib.Path(TODO_DIR / fichier).read_text(encoding="utf-8")
            self.assertIn("PlanMixin, App", src, fichier)

    def test_the_pure_logic_lives_in_one_place(self):
        pures = {
            "parse_ram",
            "parse_disk",
            "positive_int",
            "plan_rows",
            "plan_totals",
            "build_vms",
            "apply_profile",
            "apply_overrides",
            "expand_copies",
            "entry_key",
            "vm_name",
            "clean_hostname",
            "clip_payload",
            "run_deploy_progress",
        }
        self.assertTrue(pures <= membres(TODO_DIR / "deploy_form_lib.py"))
        # Réexportées par l'ancien module : les appelants historiques (et les
        # tests déjà écrits) importent encore ces noms LÀ.
        from script.todo import qemu_deploy_form as ancien

        for nom in pures:
            self.assertTrue(hasattr(ancien, nom), nom)

    def test_the_row_factory_is_shared(self):
        for fichier in ("qemu_deploy_form.py", "proxmox_deploy_form.py"):
            src = pathlib.Path(TODO_DIR / fichier).read_text(encoding="utf-8")
            self.assertIn("res_row_widgets(", src, fichier)

    def test_the_css_base_is_shared(self):
        self.assertIn("#plan", lib.CSS_BASE)
        self.assertIn("PreviewScreen", lib.CSS_BASE)
        for fichier in ("qemu_deploy_form.py", "proxmox_deploy_form.py"):
            src = pathlib.Path(TODO_DIR / fichier).read_text(encoding="utf-8")
            self.assertIn("CSS_BASE", src, fichier)
            # Les règles communes ne doivent PAS être recopiées à côté.
            self.assertNotIn("#totals { height: auto;", src, fichier)


if __name__ == "__main__":
    unittest.main(verbosity=2)
