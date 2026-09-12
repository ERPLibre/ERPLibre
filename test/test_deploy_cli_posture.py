#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les invites en ligne posent les deux questions de la règle d'or.

CE QUE CE FICHIER EXISTE POUR EMPÊCHER. Le déploiement libvirt déclare que
« les deux interfaces produisent la MÊME spec » et bâtit sa garde sur cette
promesse : un point de passage unique, traversé par le formulaire comme par
les invites. La promesse portait sur dix-sept clés et en oubliait deux —
`posture` et `real_data`, qu'aucune invite ne posait. La garde lisait alors
les valeurs de repli, « sortie libre » et « pas de données réelles », et ne
pouvait rendre qu'OK. Une machine à données réelles obtenait une sortie
libre sans qu'un mot soit dit.

LE FRAGMENT PLUTÔT QUE DEUX CLÉS. Le helper rend un morceau de spec indexé
par les constantes de `script/posture/spec.py`, et non deux chaînes
recopiées chez chaque appelant : une clé écrite sous un autre nom d'un côté
laisse la ligne vide, sans message et sans erreur.

Ni réseau, ni VM : les invites sont simulées, rien n'est créé.
"""

import contextlib
import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

sys.argv = ["todo.py"]

from script.posture import spec as S  # noqa: E402
from script.todo import vm_profiles as V  # noqa: E402
from script.todo.todo import TODO  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402
from script.vm.backend import VmBackendError  # noqa: E402

MOD = type(
    "ModuleDeBanc",
    (),
    {
        "DISTROS": {"ubuntu": [{"24.04": ("noble", "24.04")}]},
        "image_url": staticmethod(lambda *_a: "http://example.invalid/i.img"),
        "default_image_name": staticmethod(lambda *_a: "i.img"),
    },
)()


VM_APERCU = {
    "name": "vm1",
    "arch": "amd64",
    "distro": "ubuntu",
    "version": "24.04",
    "ram": 4096,
    "vcpus": 2,
    "disk": "32G",
}

SPEC_APERCU = {
    "vms": [VM_APERCU],
    "existing": [],
    "ssh_key": "",
    "install": None,
    "add_ssh_config": False,
    "parallelism": 1,
}


def menu():
    return TODO.__new__(TODO)


def demander(reponses, after_boot=False):
    """Le helper, nourri de réponses simulées. Rend (fragment, écran)."""
    tampon = io.StringIO()
    with mock.patch("builtins.input", side_effect=list(reponses)):
        with redirect_stdout(tampon):
            fragment = menu()._deploy_ask_posture(after_boot=after_boot)
    return fragment, tampon.getvalue()


class TestLeFragmentQueLInviteRend(unittest.TestCase):
    def test_it_carries_both_keys_by_the_constants_that_name_them(self):
        fragment, _ecran = demander(["n", "1"])
        self.assertEqual({S.POSTURE_KEY, S.REAL_DATA_KEY}, set(fragment))

    def test_no_real_data_offers_every_profile(self):
        fragment, ecran = demander(["n", "3"])
        self.assertFalse(fragment[S.REAL_DATA_KEY])
        self.assertEqual("paranoid", fragment[S.POSTURE_KEY])
        for libelle, _p in V.choices():
            self.assertIn(libelle, ecran)

    def test_a_blank_answer_takes_the_freest_and_says_so(self):
        """Le premier offert est étoilé, et une entrée vide le prend : même
        règle que les autres invites du dépôt."""
        fragment, ecran = demander(["", ""])
        self.assertEqual("open", fragment[S.POSTURE_KEY])
        self.assertIn("*", ecran)

    def test_a_name_is_accepted_as_well_as_a_number(self):
        fragment, _ecran = demander(["n", "VM paranoid"])
        self.assertEqual("paranoid", fragment[S.POSTURE_KEY])

    def test_an_invalid_answer_falls_back_without_asking_again(self):
        """Aucune relance : le dépôt n'en fait nulle part, et une invite qui
        rejoue ne se simule plus par une liste de réponses."""
        fragment, ecran = demander(["n", "zzz"])
        self.assertEqual("open", fragment[S.POSTURE_KEY])
        self.assertIn(t("Invalid selection, using"), ecran)


class TestLaListeSeReduitEtLeDit(unittest.TestCase):
    """Une liste qui rétrécit sans rien dire laisse croire que la posture
    n'existe pas, et son absence se lit comme une panne."""

    def test_real_data_offers_only_what_the_guard_accepts(self):
        fragment, _ecran = demander(["o", ""])
        self.assertTrue(fragment[S.REAL_DATA_KEY])
        self.assertEqual("local-only", fragment[S.POSTURE_KEY])

    def test_the_couple_it_forms_is_never_one_the_guard_refuses(self):
        """L'invariant : ce que l'invite laisse composer, la garde
        l'accepte. Sinon le refus tombe douze questions plus tard."""
        for reponse in ("", "1"):
            with self.subTest(reponse=reponse):
                fragment, _ecran = demander(["o", reponse])
                self.assertEqual(S.OK, S.check(fragment))

    def test_the_withheld_are_named_and_not_hidden(self):
        _fragment, ecran = demander(["o", ""])
        for libelle, _p in V.withheld(real_data=True):
            self.assertIn(libelle, ecran)

    def test_each_withheld_says_why_it_cannot_be_chosen(self):
        """La raison vient de `screen_line`, qui la calcule déjà : la
        recopier ici la ferait diverger de ce que le formulaire affiche."""
        _fragment, ecran = demander(["o", ""])
        self.assertIn(V.screen_line("connected"), ecran)
        self.assertIn(V.screen_line("paranoid"), ecran)


class TestLaSpecDesInvitesLesPorte(unittest.TestCase):
    """La promesse du point de passage unique, tenue sur dix-neuf clés.

    « Les deux interfaces produisent la MÊME spec » est ce sur quoi la
    garde est bâtie. Elle portait sur dix-sept clés et en oubliait deux.
    """

    BOUCHONS = {
        "_qemu_default_ssh_key": lambda: "/tmp/rien.pub",
        "_qemu_ask_timezone": lambda: "Etc/UTC",
        "_qemu_ask_locale": lambda: "C.UTF-8",
        "_qemu_ask_desktop": lambda: "",
        "_qemu_desktop_suffixes": lambda: {},
        "_qemu_ask_app_store": lambda _vms: "deb",
        "_qemu_ask_vm_tools": lambda _vms: [],
        "_qemu_ask_python_provider": lambda _a: "",
        "_qemu_ask_ai_tools": lambda _t: ("", "", ""),
        "_qemu_list_domains": lambda: [],
        "_qemu_confirm_collisions": lambda _e, _p: True,
        "_qemu_print_recap": lambda _s, _e: None,
        "_confirm_or_discard": lambda _q: True,
    }

    def collecte(self, reponses):
        todo = menu()
        for nom, bouchon in self.BOUCHONS.items():
            setattr(todo, nom, bouchon)
        todo._qemu_split_existing = lambda vms, _d: (list(vms), [])
        vms = [{"name": "vm1", "arch": "amd64", "distro": "ubuntu"}]
        tampon = io.StringIO()
        with mock.patch("builtins.input", side_effect=list(reponses)):
            with redirect_stdout(tampon):
                return todo._qemu_collect_options_cli(vms, "x1")

    def test_the_cli_spec_carries_the_posture_and_the_real_data(self):
        spec = self.collecte(["n", "3", "", "n", "n", "n", "n", ""])
        self.assertEqual("paranoid", spec[S.POSTURE_KEY])
        self.assertIs(False, spec[S.REAL_DATA_KEY])

    def test_the_guard_now_has_something_to_judge(self):
        """Avant, la spec muette faisait replier la garde sur « sortie
        libre » et « pas de données réelles » : elle ne pouvait rendre
        qu'OK, quoi qu'on ait voulu."""
        spec = self.collecte(["o", "", "", "n", "n", "n", "n", ""])
        self.assertEqual("local-only", spec[S.POSTURE_KEY])
        self.assertIs(True, spec[S.REAL_DATA_KEY])
        self.assertEqual(S.OK, S.check(spec))


class TestLaGardePartageeDeProxmox(unittest.TestCase):
    """Le refus vit dans UNE fonction, appelée par les deux voies.

    Sur cet hôte, la voie de l'écran portait seule la règle d'or : le repli
    par questions bâtissait sa propre spec et appelait « qm create » sans
    jamais la traverser. Extraire le refus est ce qui rend impossible de
    l'ajouter d'un seul côté.
    """

    def refus(self, spec):
        tampon = io.StringIO()
        with redirect_stdout(tampon):
            refuse = menu()._pve_posture_refused(spec)
        return refuse, tampon.getvalue()

    def test_free_egress_and_real_data_is_refused(self):
        refuse, ecran = self.refus(
            {S.POSTURE_KEY: "open", S.REAL_DATA_KEY: True}
        )
        self.assertTrue(refuse)
        self.assertIn(S.REAL_DATA_UNCONFINED, ecran)

    def test_an_unknown_posture_is_refused_and_not_folded_back(self):
        """Replier sur la plus libre déploierait en sortie libre une spec
        qui demandait du confinement."""
        refuse, ecran = self.refus({S.POSTURE_KEY: "jamais-vue"})
        self.assertTrue(refuse)
        self.assertIn(S.UNKNOWN_POSTURE, ecran)

    def test_a_coherent_couple_passes_and_says_nothing(self):
        refuse, ecran = self.refus(
            {S.POSTURE_KEY: "local-only", S.REAL_DATA_KEY: True}
        )
        self.assertFalse(refuse)
        self.assertEqual("", ecran)

    def test_a_mute_spec_still_deploys_as_it_always_did(self):
        """Une spec écrite avant que les postures existent n'en nomme
        aucune, et doit continuer de se déployer."""
        self.assertFalse(self.refus({})[0])


class TestLeRepliProxmoxTraverseLaGarde(unittest.TestCase):
    def test_it_refuses_before_asking_anything_else(self):
        """Le refus tombe AVANT « qm create » — et même avant la première
        question sur la machine, puisque rien d'autre n'en dépend."""
        todo = menu()
        todo._pve_host = lambda: {"target": "hote"}
        todo._qemu_import_module = lambda: None
        atteint = []
        todo._qemu_prompt_distro = lambda: atteint.append("distro")
        tampon = io.StringIO()
        with mock.patch.object(V, "choices", return_value=[]):
            with mock.patch("builtins.input", side_effect=["o"]):
                with redirect_stdout(tampon):
                    todo._pve_deploy_prompts()
        self.assertEqual([], atteint)
        self.assertIn(S.REAL_DATA_UNCONFINED, tampon.getvalue())


class TestLeRepliProxmoxPorteLaPostureJusquAuxRegles(unittest.TestCase):
    """Le fragment doit atteindre la spec que lit le poseur de règles.

    Refuser le couple incohérent ne suffisait pas : sans la posture dans la
    spec finale, cette voie créait la VM et ne posait AUCUNE règle, quelle
    que soit la posture choisie. C'est `_pve_after_create` qui mène au
    guide, et le guide au rendu nftables.
    """

    def deployer(self, reponses):
        from script.proxmox import proxmox_deploy as pve

        todo = menu()
        todo._pve_host = lambda: {"target": "hote"}
        todo._qemu_import_module = lambda: MOD
        todo._qemu_prompt_distro = lambda: "ubuntu"
        todo._qemu_prompt_version = lambda _d: "24.04"
        todo._qemu_ask_ram = lambda _l, _d: 4096
        todo._qemu_ask_cpu = lambda _l, _d, _h: 2
        todo._pve_show = lambda *_a, **_k: (0, "")
        todo._pve_vms = lambda: []
        todo._qemu_default_ssh_key = lambda: ""
        todo._qemu_host_timezone = lambda: "Etc/UTC"
        todo._pve_print_summary = lambda *_a, **_k: None
        vues = []
        todo._pve_after_create = lambda _h, spec, *_a: vues.append(spec)
        faux = {
            "parse_storages": lambda _o: ["local"],
            "parse_bridges": lambda _o: ["vmbr0"],
            "parse_bridge_config": lambda _o: {},
            "pick_storage": lambda _s: "local",
            "pick_bridge": lambda _p: "vmbr0",
            "next_vmid": lambda _v: 100,
            "ipconfig_for": lambda _i, _v: "ip=dhcp",
            "image_fetch_cmd": lambda _u, _i: "true",
            "create_cmds": lambda _v, _s: [],
            "ip_from_ipconfig": lambda _i: "198.51.100.7",
        }
        tampon = io.StringIO()
        with contextlib.ExitStack() as pile:
            for nom, bouchon in faux.items():
                pile.enter_context(mock.patch.object(pve, nom, bouchon))
            pile.enter_context(
                mock.patch("builtins.input", side_effect=list(reponses))
            )
            pile.enter_context(redirect_stdout(tampon))
            todo._pve_deploy_prompts()
        return vues

    def test_the_chosen_posture_reaches_the_spec_that_lays_the_rules(self):
        vues = self.deployer(["n", "4", "", "", "", "n"])
        self.assertEqual(1, len(vues))
        self.assertEqual("local-only", vues[0][S.POSTURE_KEY])
        self.assertIs(False, vues[0][S.REAL_DATA_KEY])

    def test_a_free_posture_reaches_it_too_and_says_so(self):
        """« open » n'est pas l'absence de réponse : la spec la PORTE, et
        une relecture sait que la question a été posée."""
        vues = self.deployer(["n", "1", "", "", "", "n"])
        self.assertEqual("open", vues[0][S.POSTURE_KEY])


class TestLaPorteTextualDeProxmox(unittest.TestCase):
    """Proposer d'installer Textual, plutôt que dégrader en silence.

    Toutes les autres portes Textual du dépôt appellent `ensure()` avant
    d'importer leur écran ; celle-ci était la seule à tomber directement
    dans le repli. Le repli reste un choix offert — il ne doit pas être ce
    qu'on obtient sans l'avoir demandé.
    """

    def ouvrir(self, disponible):
        from script.todo import textual_setup

        todo = menu()
        todo._pve_host = lambda: {"target": "hote"}
        todo._qemu_import_module = lambda: MOD
        vus = []
        todo._pve_form_context = lambda _m, _h: vus.append("écran") or {}
        todo._pve_deploy_prompts = lambda *_a: vus.append("questions")
        tampon = io.StringIO()
        with mock.patch.object(
            textual_setup, "ensure", return_value=disponible
        ) as porte:
            with mock.patch(
                "script.todo.proxmox_deploy_form.run_proxmox_form",
                return_value={},
            ):
                with redirect_stdout(tampon):
                    todo._pve_deploy()
        return vus, porte

    def test_the_door_is_consulted_before_the_screen_is_reached(self):
        _vus, porte = self.ouvrir(True)
        self.assertTrue(porte.called)

    def test_without_textual_it_falls_back_without_touching_the_screen(self):
        """Le repli reste atteignable — il ne devient pas impossible — mais
        il n'est plus ce qu'on obtient sans avoir rien demandé."""
        vus, _porte = self.ouvrir(False)
        self.assertEqual(["questions"], vus)


class TestLeRefusSeLitAuLieuDeSeDerouler(unittest.TestCase):
    """La garde LÈVE, et rien ne la rattrapait.

    Le refus du couple incohérent est une décision, pas une panne : la voie
    Proxmox imprime son verdict et revient au menu. Sur la voie libvirt, la
    levée traversait tout et sortait du menu en pile — y compris depuis
    l'APERÇU, qui ne crée pourtant rien.
    """

    REFUSE = {S.POSTURE_KEY: "open", S.REAL_DATA_KEY: True}

    def test_the_menu_prints_the_verdict_and_comes_back(self):
        todo = menu()

        def lever(_mod, _dry):
            raise VmBackendError("Déploiement refusé : real-data-unconfined.")

        todo._qemu_import_module = lambda: MOD
        todo._qemu_last_run_line = lambda: ""
        todo._qemu_active_install = lambda: False
        todo._qemu_check_libvirt_group = lambda: None
        todo._qemu_check_kvm = lambda: None
        todo._qemu_deploy_decided = lever
        tampon = io.StringIO()
        with redirect_stdout(tampon):
            self.assertIsNone(todo._qemu_deploy())
        self.assertIn(S.REAL_DATA_UNCONFINED, tampon.getvalue())

    def test_the_preview_shows_the_refusal_instead_of_a_command(self):
        """L'aperçu ne crée rien : il n'a aucune raison de finir en pile.
        Il dit ce que le déploiement dirait, et reste une ligne."""
        ligne = menu()._qemu_preview_command({}, self.REFUSE, True)
        self.assertIn(S.REAL_DATA_UNCONFINED, ligne)

    def test_an_accepted_couple_still_previews_its_command(self):
        spec = dict(SPEC_APERCU, **{S.POSTURE_KEY: "open"})
        ligne = menu()._qemu_preview_command(VM_APERCU, spec, True)
        self.assertIn("deploy_qemu.py", ligne)


class TestLaFenetreDuPremierDemarrage(unittest.TestCase):
    def test_after_boot_changes_what_the_lines_say(self):
        """`after_boot` décrit le CHEMIN : là où les règles n'arrivent
        qu'une fois la machine debout, la ligne porte l'écart."""
        _f, avant = demander(["n", "3"])
        _f, apres = demander(["n", "3"], after_boot=True)
        self.assertNotEqual(avant, apres)
        self.assertIn(V.screen_line("paranoid", True), apres)


if __name__ == "__main__":
    unittest.main()
